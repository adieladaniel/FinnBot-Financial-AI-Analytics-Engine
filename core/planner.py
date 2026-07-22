from core.resolver import resolve_query


def _pick_measure_with_agg(base_col, measures, target_agg):
    for m_name, m_def in measures.items():
        if m_def["column"] == base_col and m_def["agg"] == target_agg:
            return m_name
    return None


def _normalize_multi_measures(measure_names, measures, intent, agg):
    final_measures = []

    for m in measure_names:
        if m not in measures:
            continue

        base_col = measures[m]["column"]
        chosen = None

        if intent in ["ranking", "count"]:
            chosen = _pick_measure_with_agg(base_col, measures, "sum")
        elif intent == "value":
            chosen = _pick_measure_with_agg(base_col, measures, agg)

        if not chosen:
            chosen = m

        final_measures.append(chosen)

    # unique preserve order
    unique_measures = []
    seen = set()
    for m in final_measures:
        if m not in seen:
            unique_measures.append(m)
            seen.add(m)

    return unique_measures


def build_plan(question, df, schema, measures, domain_config):
    intent_data = resolve_query(question, df, schema, measures, domain_config)

    intent = intent_data["intent"]
    measure = intent_data["measure"]
    measures_list = intent_data.get("measures", [])
    entity = intent_data["entity"]
    agg = intent_data["aggregation"]
    is_multi_measure = intent_data.get("is_multi_measure", False)

    if entity and any(x in question.lower() for x in ["max", "min", "highest", "lowest"]):
        if intent == "value":
            intent = "ranking"

    if measure:
        base_col = measures[measure]["column"]

        if intent == "ranking":
            new_measure = _pick_measure_with_agg(base_col, measures, "sum")
            if new_measure:
                measure = new_measure

        elif intent == "value":
            new_measure = _pick_measure_with_agg(base_col, measures, agg)
            if new_measure:
                measure = new_measure

        elif intent == "count":
            new_measure = _pick_measure_with_agg(base_col, measures, "sum")
            if new_measure:
                measure = new_measure

    if is_multi_measure:
        measures_list = _normalize_multi_measures(measures_list, measures, intent, agg)

    if is_multi_measure and measures_list:
        if intent == "ranking":
            if not entity:
                entity = schema.get("dimensions", [None])[0]

            sort_measure = measure if measure else measures_list[0]

            return {
                "task": "grouped_table_multi",
                "group_by": [entity] if entity else [],
                "measures": measures_list,
                "sort_by": sort_measure,
                "sort_order": intent_data["sort_order"],
                "limit": intent_data["limit"],
                "filters": intent_data["filters"],
                "resolver_meta": intent_data
            }

        if intent == "value":
            return {
                "task": "single_value_multi",
                "measures": measures_list,
                "filters": intent_data["filters"],
                "resolver_meta": intent_data
            }

    if intent == "count":
        ranking_words = ["highest", "lowest", "least", "most", "top", "bottom", "max", "min", "largest", "smallest"]

        if any(word in question.lower() for word in ranking_words):
            if not entity:
                entity = schema.get("dimensions", [None])[0]

            return {
                "task": "count_extreme",
                "group_by": [entity] if entity else [],
                "measure": measure,
                "sort_order": intent_data["sort_order"],
                "filters": intent_data["filters"],
                "resolver_meta": intent_data
            }

        return {
            "task": "count",
            "group_by": [entity] if entity else [],
            "measure": measure,
            "filters": intent_data["filters"],
            "resolver_meta": intent_data
        }

    if intent == "ranking":
        if not entity:
            entity = schema.get("dimensions", [None])[0]

        return {
            "task": "grouped_table",
            "group_by": [entity] if entity else [],
            "measure": measure,
            "sort_by": measure,
            "sort_order": intent_data["sort_order"],
            "limit": intent_data["limit"],
            "filters": intent_data["filters"],
            "resolver_meta": intent_data
        }

    if intent == "raw":
        return {
            "task": "raw_table",
            "columns": schema.get("dimensions", [])[:5],
            "filters": intent_data["filters"],
            "limit": intent_data["limit"],
            "resolver_meta": intent_data
        }

    return {
        "task": "single_value",
        "measure": measure,
        "filters": intent_data["filters"],
        "resolver_meta": intent_data
    }