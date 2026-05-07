import re


FOLLOWUP_WORDS = [
    "their",
    "them",
    "those",
    "same",
    "above",
    "previous",
    "last",
    "now give",
    "now show",
    "for them",
    "for those",
    "for same"
]


MEASURE_KEYWORDS = {
    "waiver": "waiver amount",
    "concession": "concession amount",
    "pending": "pending fees",
    "outstanding": "outstanding fees",
    "balance": "pending fees",
    "paid": "paid amount",
    "received": "received amount",
    "fee": "fees",
    "fees": "fees",
    "payable": "payable amount"
}


def init_context_memory():
    return {
        "turns": [],
        "active_entities": [],
        "active_entity_column": None,
        "active_task": None,
        "active_measure": None,
        "active_group_by": [],
        "active_filters": [],
        "active_limit": None,
        "last_refined_question": None
    }


def is_followup_question(question: str):
    q = question.lower()
    return any(word in q for word in FOLLOWUP_WORDS)


def detect_requested_measure_text(question: str):
    q = question.lower()

    for key, value in MEASURE_KEYWORDS.items():
        if key in q:
            return value

    return None


def extract_entities_from_result(plan, result):
    rows = result.get("rows", [])
    group_by = plan.get("group_by", [])

    if not rows or not group_by:
        return [], None

    entity_col = group_by[0]
    entities = []

    for row in rows:
        if entity_col in row:
            val = row.get(entity_col)
            if val not in [None, ""]:
                entities.append(str(val))

    return entities, entity_col


def build_entity_filter_phrase(entity_col, entities):
    quoted = [f'"{e}"' for e in entities]
    return f"where {entity_col} is in [{', '.join(quoted)}]"


def refine_question_with_context(question, context):
    q = question.strip()

    if not is_followup_question(q):
        return q, False

    entities = context.get("active_entities", [])
    entity_col = context.get("active_entity_column")

    if not entities or not entity_col:
        return q, False

    requested_measure = detect_requested_measure_text(q)

    if not requested_measure:
        requested_measure = context.get("active_measure") or ""

    entity_filter_text = build_entity_filter_phrase(entity_col, entities)

    refined = f"show {requested_measure} grouped by {entity_col} {entity_filter_text}"

    return refined, True


def update_context_memory(context, question, refined_question, plan, result):
    if context is None:
        context = init_context_memory()

    rows = result.get("rows", [])
    entities, entity_col = extract_entities_from_result(plan, result)

    turn = {
        "question": question,
        "refined_question": refined_question,
        "plan": plan,
        "answer": result.get("answer"),
        "row_count": len(rows)
    }

    context["turns"].append(turn)
    context["turns"] = context["turns"][-8:]

    if entities:
        context["active_entities"] = entities
        context["active_entity_column"] = entity_col

    context["active_task"] = plan.get("task")
    context["active_measure"] = plan.get("measure")
    context["active_group_by"] = plan.get("group_by", [])
    context["active_filters"] = plan.get("filters", [])
    context["active_limit"] = plan.get("limit")
    context["last_refined_question"] = refined_question

    return context