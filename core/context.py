import re


def _contains_term(q: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", q) is not None


def _contains_any(q: str, terms) -> bool:
    return any(_contains_term(q, term) for term in terms)


def refine_question_with_context(question, session, domain_config):
    q = question.lower().strip()

    last_measure = session.get("last_measure")
    last_group_by = session.get("last_group_by", [])
    last_top_entity_column = session.get("last_top_entity_column")
    last_top_entity_value = session.get("last_top_entity_value")
    last_entity_values = session.get("last_entity_values", [])
    last_plan = session.get("last_plan") or {}
    last_limit = last_plan.get("limit", 10)

    measure_words = domain_config.get("context_measure_words", {})

    new_measure_word = None
    for word, mapped in measure_words.items():
        if _contains_term(q, word):
            new_measure_word = mapped
            break

    result = {
        "refined_question": question,
        "extra_filters": [],
        "force_group_by": None,
        "force_limit": None,
        "carry_measure": None,
        "carry_sort_order": None,
        "carry_task": None
    }

    singular_terms = [
        "his", "her", "that student", "this student",
        "that one", "this one"
    ]

    plural_terms = [
        "their", "there", "those students", "those",
        "these students", "these", "them",
        "all 3", "all three", "all 5", "all five"
    ]

    all_n_match = re.search(r"\ball\s+(\d+)\b", q)
    requested_n = int(all_n_match.group(1)) if all_n_match else None

    vague_group_terms = ["group", "category", "segment", "type"]

    fresh_query_keywords = [
        "any student",
        "overall",
        "in the dataset",
        "in the table",
        "across all",
        "maximum",
        "minimum",
        "max",
        "min"
    ]

    if _contains_any(q, fresh_query_keywords):
        return result

    if _contains_any(q, singular_terms):
        if last_top_entity_column and last_top_entity_value is not None:
            result["extra_filters"].append({
                "column": last_top_entity_column,
                "operator": "eq",
                "values": [last_top_entity_value]
            })

            if new_measure_word:
                result["carry_measure"] = new_measure_word
            elif last_measure:
                result["carry_measure"] = last_measure

            result["carry_task"] = "single_value"
            result["refined_question"] = question

            return result

    if _contains_any(q, plural_terms) or requested_n is not None:
        if last_group_by and last_entity_values:
            group_col = last_group_by[0]

            values = last_entity_values
            if requested_n is not None:
                values = values[:requested_n]

            result["extra_filters"].append({
                "column": group_col,
                "operator": "in",
                "values": values
            })

            result["force_group_by"] = last_group_by
            result["force_limit"] = len(values)

            if new_measure_word:
                result["carry_measure"] = new_measure_word
            elif last_measure:
                result["carry_measure"] = last_measure

            result["carry_sort_order"] = "desc"
            result["carry_task"] = "grouped_table"

            result["refined_question"] = question

            return result

    if _contains_any(q, vague_group_terms):
        if last_group_by:
            result["force_group_by"] = last_group_by

    if (
        q.startswith("what about")
        or q.startswith("now tell")
        or q.startswith("now show")
        or q.startswith("show the")
    ):
        if last_group_by and new_measure_word and last_entity_values:
            group_col = last_group_by[0]

            result["extra_filters"].append({
                "column": group_col,
                "operator": "in",
                "values": last_entity_values
            })

            result["force_group_by"] = last_group_by
            result["force_limit"] = len(last_entity_values)
            # result["refined_question"] = f"show top {len(last_entity_values)} by {new_measure_word}"
            result["carry_measure"] = new_measure_word
            result["carry_sort_order"] = "desc"
            result["carry_task"] = "grouped_table"

            result["refined_question"] = question

            return result

        if last_group_by and last_top_entity_column and last_top_entity_value is not None:
            result["extra_filters"].append({
                "column": last_top_entity_column,
                "operator": "eq",
                "values": [last_top_entity_value]
            })

            if new_measure_word:
                result["carry_measure"] = new_measure_word
            elif last_measure:
                result["carry_measure"] = last_measure

            result["carry_task"] = "single_value"
            result["refined_question"] = question

            return result

        # Previous turn wasn't entity-scoped (no group_by) — nothing to carry
        # an entity filter from. Just carry the measure/task forward and keep
        # the real wording intact so any new filter mentioned here (e.g. a
        # month) still gets picked up downstream.
        if new_measure_word:
            result["carry_measure"] = new_measure_word
        elif last_measure:
            result["carry_measure"] = last_measure

        if last_plan.get("task"):
            result["carry_task"] = last_plan["task"]

        result["refined_question"] = question

        return result

    return result


def apply_context_to_plan(plan: dict, context_data: dict, measures: dict):
    if context_data.get("carry_measure"):
        carry_measure = str(context_data["carry_measure"]).lower().strip()

        matched_measure = None

        for m in measures.keys():
            ml = m.lower()

            if carry_measure in ml:
                matched_measure = m
                break

            if carry_measure == "waiver" and "waiver_amount" in ml:
                matched_measure = m
                break

            if carry_measure == "concession" and "concession_amount" in ml:
                matched_measure = m
                break

            if carry_measure in ["pending", "balance", "outstanding"] and "outstanding_fee" in ml:
                matched_measure = m
                break

        if matched_measure:
            plan["measure"] = matched_measure
            plan["sort_by"] = matched_measure

    if context_data.get("carry_task"):
        plan["task"] = context_data["carry_task"]

    if context_data.get("carry_sort_order"):
        plan["sort_order"] = context_data["carry_sort_order"]

    if context_data["extra_filters"]:
        existing_filters = plan.get("filters", [])
        plan["filters"] = existing_filters + context_data["extra_filters"]

    if context_data["force_group_by"]:
        plan["group_by"] = context_data["force_group_by"]
        if plan.get("task") == "single_value":
            plan["task"] = "grouped_table"
        elif plan.get("task") == "single_value_multi":
            plan["task"] = "grouped_table_multi"

    if context_data["force_limit"] is not None:
        plan["limit"] = context_data["force_limit"]

    return plan