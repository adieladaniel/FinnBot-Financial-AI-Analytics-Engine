import re
from difflib import SequenceMatcher


def normalize_text(text: str):
    text = text.lower().strip()
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str):
    return re.findall(r"\w+", normalize_text(text))


def split_schema_name(name: str):
    name = normalize_text(name)

    # split common suffixes
    suffixes = ["name", "amount", "date", "id", "code", "number", "no", "seq"]
    parts = [name]

    for suf in suffixes:
        if name.endswith(suf) and len(name) > len(suf):
            base = name[: -len(suf)].strip()
            if base:
                parts.append(base)
                parts.append(f"{base} {suf}")

    return list(dict.fromkeys(parts))


def similarity(a: str, b: str):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# ---------- GENERIC SEMANTIC ANALYTICS TERMS ----------
GENERIC_MEASURE_SEMANTICS = {
    "pending fees": ["balance", "balance amount"],
    "pending fee": ["balance", "balance amount"],
    "due fees": ["balance", "balance amount"],
    "due fee": ["balance", "balance amount"],
    "outstanding": ["balance", "balance amount"],
    "outstanding fees": ["balance", "balance amount"],
    "unpaid": ["balance", "balance amount"],
    "unpaid fees": ["balance", "balance amount"],

    "total fees": ["total amount", "amount"],
    "fee amount": ["total amount", "amount"],
    "fees": ["total amount", "amount"],
    "fees": ["total amount", "totalamount"],
    "highest fees": ["total amount"],
    "lowest fees": ["total amount"],
    "total paid": ["paid", "paid amount"],
    "amount paid": ["paid", "paid amount"],
    "fees paid": ["paid", "paid amount"],
    "collection": ["paid", "paid amount"],

    "concession": ["concession", "concession amount", "discount"],
    "discount": ["concession", "concession amount"],

    "waiver": ["waiver", "waiver amount"],

    "payable": ["payable", "total payable", "payable amount"]
}


def build_dimension_vocab(schema: dict):
    vocab = {}

    for col in schema.get("dimensions", []):
        forms = set()

        col_norm = normalize_text(col)
        forms.add(col_norm)

        expanded = split_schema_name(col)
        for f in expanded:
            forms.add(normalize_text(f))

        # plural/singular helpers
        for f in list(forms):
            if f.endswith(" name"):
                root = f[:-5].strip()
                if root:
                    forms.add(root)
                    forms.add(root + "s")
            elif f.endswith("y"):
                forms.add(f[:-1] + "ies")
            else:
                forms.add(f + "s")

        for f in forms:
            vocab[f] = col

    return vocab


def build_measure_vocab(measures: dict):
    vocab = {}

    for measure_name, measure_def in measures.items():
        forms = set()

        measure_norm = normalize_text(measure_name)
        forms.add(measure_norm)

        col = measure_def["column"]
        col_forms = split_schema_name(col)
        for f in col_forms:
            forms.add(normalize_text(f))

        for alias in measure_def.get("aliases", []):
            forms.add(normalize_text(alias))

        # generate agg-aware forms
        agg = measure_def["agg"]
        for f in list(forms):
            if agg == "sum":
                forms.add(f"sum {f}")
                forms.add(f"total {f}")
            elif agg == "mean":
                forms.add(f"average {f}")
                forms.add(f"avg {f}")
            elif agg == "max":
                forms.add(f"max {f}")
                forms.add(f"highest {f}")
            elif agg == "min":
                forms.add(f"min {f}")
                forms.add(f"lowest {f}")
                forms.add(f"least {f}")

        for f in forms:
            vocab[f] = measure_name

    return vocab


def best_match(query: str, candidates: list[str], threshold=0.72):
    query = normalize_text(query)
    best_candidate = None
    best_score = 0.0

    for candidate in candidates:
        score = similarity(query, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_score >= threshold:
        return best_candidate, best_score

    return None, best_score


def resolve_dimension(question: str, schema: dict):
    q = normalize_text(question)
    vocab = build_dimension_vocab(schema)

    # 1. exact phrase match first
    exact_hits = []
    for phrase, col in vocab.items():
        if phrase in q:
            exact_hits.append((len(phrase), col))

    if exact_hits:
        exact_hits.sort(reverse=True)
        return exact_hits[0][1]

    # 2. fuzzy on whole question
    match, score = best_match(q, list(vocab.keys()), threshold=0.72)
    if match:
        return vocab[match]

    # 3. fuzzy on tokens
    for token in tokenize(q):
        match, score = best_match(token, list(vocab.keys()), threshold=0.78)
        if match:
            return vocab[match]

    return None


def resolve_measure(question: str, measures: dict):
    q = normalize_text(question)
    vocab = build_measure_vocab(measures)

    # 1. semantic layer first
    semantic_hits = []
    for phrase, candidate_terms in GENERIC_MEASURE_SEMANTICS.items():
        if phrase in q:
            for measure_name, measure_def in measures.items():
                all_terms = " ".join(
                    [normalize_text(measure_name)]
                    + [normalize_text(a) for a in measure_def.get("aliases", [])]
                    + [normalize_text(measure_def["column"])]
                )
                for term in candidate_terms:
                    if term in all_terms:
                        semantic_hits.append((len(phrase), measure_name))

    if semantic_hits:
        semantic_hits.sort(reverse=True)
        return semantic_hits[0][1]

    # 2. exact phrase match
    phrase_hits = []
    for phrase, measure_name in vocab.items():
        if phrase in q:
            phrase_hits.append((len(phrase), measure_name))

    if phrase_hits:
        phrase_hits.sort(reverse=True)
        return phrase_hits[0][1]

    # 3. fuzzy full-question match
    match, score = best_match(q, list(vocab.keys()), threshold=0.72)
    if match:
        return vocab[match]
    

    # prioritize strong keywords
# prioritize strong keywords
    # PRIORITY_KEYWORDS = {
    #     "balance": "balance",
    #     "paid": "paid",
    #     "concession": "concession",
    #     "waiver": "waiver",
    #     "payable": "payable",
    #     "total": "total"
    # }

    


    # for key, val in PRIORITY_KEYWORDS.items():
    #     if key in q:
    #         for m_name in measures:
    #             if val in m_name.lower():
    #                 return m_name\

    priority = resolve_by_keyword_priority(q, measures)
    if priority:
        return priority

    return None


def resolve_by_keyword_priority(question: str, measures: dict):
    q = question.lower()

    KEYWORDS = ["balance", "paid", "concession", "waiver", "payable", "total"]

    for key in KEYWORDS:
        if key in q:
            candidates = []

            for m_name in measures:
                if key in m_name.lower():
                    candidates.append(m_name)

            if candidates:
                # prefer SUM measures over min/max
                for c in candidates:
                    if "sum" in c.lower():
                        return c

                return candidates[0]

    return None