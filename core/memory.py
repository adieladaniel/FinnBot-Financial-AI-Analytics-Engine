SESSION_MEMORY = {}


def get_session(session_id):
    if session_id not in SESSION_MEMORY:
        SESSION_MEMORY[session_id] = {
            "last_question": None,
            "last_plan": None,
            "last_measure": None,
            "last_group_by": [],
            "last_filters": [],
            "last_result": None,
            "last_rows": [],
            "last_top_entity_column": None,
            "last_top_entity_value": None,
            "last_entity_values": []
        }
    return SESSION_MEMORY[session_id]


def update_session(session_id, question=None, plan=None, result=None):
    session = get_session(session_id)

    if question is not None:
        session["last_question"] = question

    if plan is not None:
        session["last_plan"] = plan
        session["last_measure"] = plan.get("measure")
        session["last_group_by"] = plan.get("group_by", [])
        session["last_filters"] = plan.get("filters", [])

    if result is not None:
        session["last_result"] = result
        rows = result.get("rows", [])
        session["last_rows"] = rows
        session["last_entity_values"] = []

        group_by = session.get("last_group_by", [])
        if rows and group_by:
            first_group_col = group_by[0]

            for row in rows:
                if first_group_col in row:
                    session["last_entity_values"].append(row[first_group_col])

            top_row = rows[0]
            if first_group_col in top_row:
                session["last_top_entity_column"] = first_group_col
                session["last_top_entity_value"] = top_row[first_group_col]     