from typing import Any, TypedDict

import pandas as pd


class ChatState(TypedDict, total=False):
    # inputs
    session_id: str
    question: str
    domain: str
    df: pd.DataFrame
    schema: dict
    measures: dict
    domain_config: dict
    session: dict

    # normalize_query output
    original_question: str

    # refine_context output
    refined_question: str
    context_data: dict
    context_used: bool

    # rule_plan / execute_rule output
    plan: dict
    result: dict
    confidence: float
    measure_confidence: float
    entity_confidence: float
    use_fallback: bool

    # final
    source: str
    answer: Any
    rows: list
