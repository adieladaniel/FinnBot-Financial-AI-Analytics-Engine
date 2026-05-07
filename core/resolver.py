import re
from difflib import SequenceMatcher
from core.vocabulary import build_dimension_vocab, build_measure_vocab, normalize_text


def similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def best_match(query, candidates, threshold=0.7):
    best = None
    best_score = 0.0

    for c in candidates:
        score = similarity(query, c)
        if score > best_score:
            best = c
            best_score = score

    if best_score >= threshold:
        return best, best_score

    return None, best_score


def detect_intent(q):
    q = normalize_text(q)

    if any(x in q for x in ["count", "how many", "number of"]):
        return "count", 0.95

    if q.startswith("what is") or q.startswith("what's") or q.startswith("tell me") or q.startswith("give me"):
        return "value", 0.85

    if any(x in q for x in ["top", "bottom", "highest", "lowest", "least", "most", "largest", "smallest"]):
        return "ranking", 0.9

    if any(x in q for x in ["list", "show rows", "records", "details"]):
        return "raw", 0.9

    return "value", 0.5


def detect_sort(q):
    q = normalize_text(q)

    if any(x in q for x in ["least", "lowest", "smallest", "min"]):
        return "asc"

    return "desc"


def detect_limit(q):
    q = normalize_text(q)

    m = re.search(r"\btop\s+(\d+)", q)
    if m:
        return int(m.group(1))

    m = re.search(r"\bbottom\s+(\d+)", q)
    if m:
        return int(m.group(1))

    if any(x in q for x in ["highest", "lowest", "least", "most", "largest", "smallest", "max", "min"]):
        return 1

    return 10


def detect_aggregation(q):
    q = normalize_text(q)

    if any(x in q for x in ["max", "maximum"]):
        return "max"

    if any(x in q for x in ["min", "minimum"]):
        return "min"

    if any(x in q for x in ["average", "avg", "mean"]):
        return "mean"

    if any(x in q for x in ["count", "how many", "number of"]):
        return "count"

    return "sum"


def is_multi_measure_query(q: str):
    q = normalize_text(q)
    comparison_words = ["compare", "comparison", "versus", " vs ", "against"]
    if any(word in q for word in comparison_words):
        return True

    # common analytics patterns
    if " and " in q:
        return True

    return False


def resolve_entity(q, schema, domain_config=None):
    q = normalize_text(q)
    vocab = build_dimension_vocab(schema)
    # if any(word in q for word in ["student", "students"]):
    #     if "student_display" in schema.get("dimensions", []):
    #         return "student_display", 0.98
        
    if any(word in q for word in ["student", "students"]):

        preferred_student_cols = [
            "student_display",
            "student_name",
            "studentname"
        ]

        for col in preferred_student_cols:
            if col in schema.get("dimensions", []):
                return col, 0.99
            
    exact_hits = []
    for phrase, col in vocab.items():
        if phrase in q:
            exact_hits.append((len(phrase), col, 0.95))

    if exact_hits:
        exact_hits.sort(reverse=True)
        _, col, conf = exact_hits[0]
        return col, conf

    tokens = q.split()
    best = None
    best_score = 0.0

    for token in tokens:
        for phrase, col in vocab.items():
            score = similarity(token, phrase)
            if score > best_score:
                best_score = score
                best = col

    if best_score > 0.75:
        return best, best_score

    return None, 0.0


def resolve_measure(q, measures, domain_config):
    q = normalize_text(q)
    finance_priority = [
        ("outstanding", "outstanding_fee"),
        ("pending", "outstanding_fee"),
        ("due", "outstanding_fee"),
        ("balance", "outstanding_fee"),
        ("waiver", "waiver_amount"),
        ("concession", "concession_amount"),
        ("paid", "paid_amount")
    ]

    for keyword, measure_name in finance_priority:
        if keyword in q:
            if f"Sum {measure_name}" in measures:
                return f"Sum {measure_name}", 0.99
    vocab = build_measure_vocab(measures)

    semantic_aliases = domain_config.get("semantic_aliases", {})

    for phrase, target_column in semantic_aliases.items():
        if phrase in q:
            candidates = []
            for m_name, m_def in measures.items():
                if m_def["column"] == target_column:
                    candidates.append(m_name)

            if candidates:
                for c in candidates:
                    if "sum" in c.lower():
                        return c, 0.9
                return candidates[0], 0.85

    phrase_hits = []
    for phrase, m_name in vocab.items():
        if phrase in q:
            phrase_hits.append((len(phrase), m_name, 0.95))

    if phrase_hits:
        phrase_hits.sort(reverse=True)
        _, m_name, conf = phrase_hits[0]
        return m_name, conf

    scores = []
    for m_name in measures:
        name = m_name.lower()
        score = 0

        for word in q.split():
            if word in name:
                score += 1

        if "sum" in name:
            score += 1

        scores.append((score, m_name))

    scores.sort(reverse=True)

    if scores and scores[0][0] > 0:
        raw_score, m_name = scores[0]
        conf = min(0.7, 0.35 + raw_score * 0.1)
        return m_name, conf

    return None, 0.0


def resolve_multiple_measures(q, measures, domain_config):
    q = normalize_text(q)

    multi_triggers = ["compare", " vs ", "versus", "against"]
    if not any(t in q for t in multi_triggers):
        return [], 0.0

    semantic_aliases = domain_config.get("semantic_aliases", {})
    context_words = domain_config.get("context_measure_words", {})
    ignored_aliases = set(
        normalize_text(x)
        for x in domain_config.get("ignore_aliases_for_comparison", [])
    )

    comparison_part = q

    if "compare" in q:
        comparison_part = q.split("compare", 1)[1]

    stop_phrases = [
        " for top",
        " with highest",
        " with lowest",
        " by ",
        " along with",
        " as chart",
        " as a chart",
        " with a chart"
    ]

    for stop in stop_phrases:
        if stop in comparison_part:
            comparison_part = comparison_part.split(stop, 1)[0]

    matched_columns = []
    confidence_scores = []

    aliases_sorted = sorted(
        semantic_aliases.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )

    for phrase, target_column in aliases_sorted:
        phrase_norm = normalize_text(phrase)

        if phrase_norm in ignored_aliases:
            continue

        if phrase_norm in comparison_part and target_column not in matched_columns:
            matched_columns.append(target_column)
            confidence_scores.append(0.9)

    tokens = comparison_part.split()

    for token in tokens:
        if token in context_words:
            mapped_word = context_words[token]

            for phrase, target_column in semantic_aliases.items():
                phrase_norm = normalize_text(phrase)

                if mapped_word in phrase_norm and target_column not in matched_columns:
                    matched_columns.append(target_column)
                    confidence_scores.append(0.85)
                    break

    for m_name, m_def in measures.items():
        col = m_def["column"]
        col_phrase = normalize_text(col.replace("_", " "))

        if col_phrase in comparison_part and col not in matched_columns:
            matched_columns.append(col)
            confidence_scores.append(0.95)

    resolved = []

    for col in matched_columns:
        for m_name, m_def in measures.items():
            if m_def["column"] == col and m_def["agg"] == "sum":
                resolved.append(m_name)
                break

    final = []
    seen = set()

    for m in resolved:
        if m not in seen:
            final.append(m)
            seen.add(m)

    if len(final) < 2:
        return [], 0.0

    return final, round(sum(confidence_scores) / len(confidence_scores), 3)

def extract_filters(q, df, schema, measures=None, domain_config=None):
    q = normalize_text(q)
    filters = []
    matched = 0

    for col in schema.get("dimensions", []):
        if col not in df.columns:
            continue

        values = df[col].dropna().astype(str).unique().tolist()

        for v in values:
            v_low = v.lower().strip()

            if not v_low:
                continue

            if col == "classname":
                if re.search(rf"\bclass\s+{re.escape(v_low)}\b", q):
                    filters.append({
                        "column": col,
                        "operator": "eq",
                        "values": [v]
                    })
                    matched += 1
                    break
                continue

            if col == "sectionname":
                if re.search(rf"\bsection\s+{re.escape(v_low)}\b", q):
                    filters.append({
                        "column": col,
                        "operator": "eq",
                        "values": [v]
                    })
                    matched += 1
                    break
                continue

            if len(v_low) < 3:
                continue

            if v_low.isdigit():
                continue

            if v_low in q:
                filters.append({
                    "column": col,
                    "operator": "eq",
                    "values": [v]
                })
                matched += 1
                break

    zero_value_phrases = {}
    if domain_config:
        zero_value_phrases = domain_config.get("zero_value_phrases", {})

    for target_col, phrases in zero_value_phrases.items():
        if any(p in q for p in phrases):
            filters.append({
                "column": target_col,
                "operator": "eq",
                "values": [0]
            })
            matched += 1

    filter_conf = 0.0 if matched == 0 else min(0.9, 0.3 + matched * 0.2)
    op, numeric_value = extract_numeric_condition(q)

    if numeric_value is not None and measures:
        matched_measure, _ = resolve_measure(q, measures, domain_config or {})

        if matched_measure and matched_measure in measures:
            target_col = measures[matched_measure]["column"]

            filters.append({
                "column": target_col,
                "operator": op,
                "values": [numeric_value]
            })
            matched += 1
    return filters, filter_conf


def resolve_query(question, df, schema, measures, domain_config):
    q = normalize_text(question)

    intent, intent_conf = detect_intent(q)
    measure, measure_conf = resolve_measure(q, measures, domain_config)
    measures_list, multi_measure_conf = resolve_multiple_measures(q, measures, domain_config)
    entity, entity_conf = resolve_entity(q, schema, domain_config)
    aggregation = detect_aggregation(q)
    sort_order = detect_sort(q)
    limit = detect_limit(q)
    filters, filter_conf = extract_filters(q, df, schema, measures, domain_config)
    multi_query = is_multi_measure_query(q)

    overall_conf = 0.0
    overall_conf += intent_conf * 0.25
    overall_conf += max(measure_conf, multi_measure_conf) * 0.45
    overall_conf += entity_conf * 0.2
    overall_conf += filter_conf * 0.1

    if intent == "value":
        overall_conf += 0.05

    overall_conf = min(1.0, overall_conf)

    return {
        "intent": intent,
        "measure": measure,
        "measures": measures_list,
        "is_multi_measure": multi_query and len(measures_list) >= 2,
        "entity": entity,
        "aggregation": aggregation,
        "sort_order": sort_order,
        "limit": limit,
        "filters": filters,
        "confidence": round(overall_conf, 3),
        "intent_confidence": round(intent_conf, 3),
        "measure_confidence": round(max(measure_conf, multi_measure_conf), 3),
        "entity_confidence": round(entity_conf, 3),
        "filter_confidence": round(filter_conf, 3)
    }


def extract_numeric_condition(q):
    q = normalize_text(q)

    patterns = [

        (
            r"(?:is|equals|equal to|=|as)\s*(\d+(?:\.\d+)?)",
            "eq"
        ),

        (
            r"(?:greater than|more than|above|over)\s*(\d+(?:\.\d+)?)",
            "gt"
        ),

        (
            r"(?:less than|below|under)\s*(\d+(?:\.\d+)?)",
            "lt"
        ),

        (
            r"(?:at least|minimum of|min of)\s*(\d+(?:\.\d+)?)",
            "gte"
        ),

        (
            r"(?:at most|maximum of|max of)\s*(\d+(?:\.\d+)?)",
            "lte"
        ),

        (
            r"(?:exactly)\s*(\d+(?:\.\d+)?)",
            "eq"
        ),

        (
            r"(?:no|zero)\s+(?:fees?|amount|balance|outstanding|pending)",
            "eq_zero_keyword"
        )
    ]

    for pattern, op in patterns:
        match = re.search(pattern, q)

        if match:

            if op == "eq_zero_keyword":
                return "eq", 0

            return op, float(match.group(1))

    return None, None