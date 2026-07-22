from langgraph.graph import END, StateGraph

from core.context import apply_context_to_plan, refine_question_with_context
from core.date_filter import add_date_filter_to_plan, add_month_comparison_to_plan
from core.executor import execute_plan
from core.graph_state import ChatState
from core.llm_fallback import call_gemini_planner, gemini_available
from core.planner import build_plan
from core.query_normalizer import build_correction_vocabulary, correct_query_typos

MULTI_MEASURE_TASKS = ("grouped_table_multi", "single_value_multi")


def should_use_fallback(
    plan: dict,
    result: dict,
    confidence: float,
    measure_conf: float,
    context_used: bool,
    is_multi_measure: bool,
    question: str,
    domain_config: dict,
) -> bool:
    task = plan.get("task")

    if not plan.get("measure") and not plan.get("measures"):
        return True

    if task in ["grouped_table", "grouped_table_multi", "count", "count_extreme"] and not plan.get("group_by"):
        return True

    if result["rows"] == [] and task in ["grouped_table", "grouped_table_multi", "raw_table"]:
        return True

    if not context_used and not is_multi_measure:
        if confidence < 0.68:
            return True
        if measure_conf < 0.55:
            return True

    semantic_phrases = domain_config.get("semantic_phrases_for_fallback", [])
    if any(p in question.lower() for p in semantic_phrases):
        return True

    return False


def node_normalize_query(state: ChatState) -> dict:
    vocabulary = build_correction_vocabulary(
        state["schema"], state["measures"], state["domain_config"]
    )
    corrected = correct_query_typos(state["question"], vocabulary)

    return {
        "original_question": state["question"],
        "question": corrected,
    }


def node_refine_context(state: ChatState) -> dict:
    context_data = refine_question_with_context(
        state["question"], state["session"], state["domain_config"]
    )
    refined_question = context_data["refined_question"]

    context_used = bool(
        context_data.get("extra_filters")
        or context_data.get("force_group_by")
        or context_data.get("force_limit")
        or context_data.get("carry_measure")
        or context_data.get("carry_task")
    )

    return {
        "refined_question": refined_question,
        "context_data": context_data,
        "context_used": context_used,
    }


def node_rule_plan(state: ChatState) -> dict:
    df = state["df"]
    schema = state["schema"]
    measures = state["measures"]
    domain_config = state["domain_config"]
    refined_question = state["refined_question"]

    plan = build_plan(refined_question, df, schema, measures, domain_config)
    plan = add_date_filter_to_plan(plan, refined_question, df)
    plan = add_month_comparison_to_plan(plan, refined_question, df)
    plan = apply_context_to_plan(plan, state["context_data"], measures)

    return {"plan": plan}


def node_execute_rule(state: ChatState) -> dict:
    plan = state["plan"]
    result = execute_plan(plan, state["df"], state["measures"])

    resolver_meta = plan.get("resolver_meta", {})
    confidence = resolver_meta.get("confidence", 0.0)
    measure_conf = resolver_meta.get("measure_confidence", 0.0)
    entity_conf = resolver_meta.get("entity_confidence", 0.0)

    is_multi_measure = plan.get("task") in MULTI_MEASURE_TASKS
    context_used = state["context_used"]

    use_fallback = should_use_fallback(
        plan,
        result,
        confidence,
        measure_conf,
        context_used,
        is_multi_measure,
        state["question"],
        state["domain_config"],
    )

    if context_used:
        use_fallback = False
        confidence = max(confidence, 0.90)

    return {
        "result": result,
        "confidence": confidence,
        "measure_confidence": measure_conf,
        "entity_confidence": entity_conf,
        "use_fallback": use_fallback,
        "source": "rule_based",
    }


def node_llm_fallback(state: ChatState) -> dict:
    question = state["question"]
    plan = state["plan"]
    is_multi_measure = plan.get("task") in MULTI_MEASURE_TASKS

    if not gemini_available():
        return {
            "source": "low_confidence_fail",
            "result": {
                "answer": "AI fallback is temporarily unavailable. Please try again shortly or rephrase the question more directly.",
                "rows": [],
            },
        }

    gemini_plan = call_gemini_planner(
        question=question,
        schema=state["schema"],
        measures=state["measures"],
        context=state["session"].get("last_question"),
    )

    if not gemini_plan:
        if state["confidence"] < 0.7 and not is_multi_measure:
            return {
                "source": "low_confidence_fail",
                "result": {
                    "answer": "I could not confidently understand the question. Please rephrase.",
                    "rows": [],
                },
            }
        return {"source": "rule_based_failed"}

    df = state["df"]
    gemini_plan = add_date_filter_to_plan(gemini_plan, question, df)
    gemini_plan = add_month_comparison_to_plan(gemini_plan, question, df)

    result = execute_plan(gemini_plan, df, state["measures"])

    return {
        "plan": gemini_plan,
        "result": result,
        "source": "gemini_fallback",
    }


def _route_after_execute(state: ChatState) -> str:
    return "llm_fallback" if state.get("use_fallback") else END


def build_graph():
    graph = StateGraph(ChatState)

    graph.add_node("normalize_query", node_normalize_query)
    graph.add_node("refine_context", node_refine_context)
    graph.add_node("rule_plan", node_rule_plan)
    graph.add_node("execute_rule", node_execute_rule)
    graph.add_node("llm_fallback", node_llm_fallback)

    graph.set_entry_point("normalize_query")
    graph.add_edge("normalize_query", "refine_context")
    graph.add_edge("refine_context", "rule_plan")
    graph.add_edge("rule_plan", "execute_rule")

    graph.add_conditional_edges(
        "execute_rule",
        _route_after_execute,
        {"llm_fallback": "llm_fallback", END: END},
    )

    graph.add_edge("llm_fallback", END)

    return graph.compile()


GRAPH = build_graph()
