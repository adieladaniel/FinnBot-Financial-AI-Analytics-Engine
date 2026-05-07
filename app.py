from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import uuid

from core.loader import load_dataset
from core.profiler import profile_dataset
from core.schema_builder import build_schema
from core.measures_builder import build_measures
from core.planner import build_plan
from core.executor import execute_plan
from core.memory import get_session, update_session
from core.context import refine_question_with_context
from core.llm_fallback import call_gemini_planner, gemini_available 
from core.config_loader import load_domain_config
from core.api_loader import fetch_api_data_from_curl
# from core.context_engine import (
#     init_context_memory,
#     refine_question_with_context,
#     update_context_memory
# )


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/")
def serve_ui():
    return FileResponse("frontend/index.html")


DATASETS = {}
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


class ChatRequest(BaseModel):
    session_id: str = "default"
    question: str
    domain: str = "generic"

class ApiUploadRequest(BaseModel):
    curl: str
    max_pages: int = 1


def prepare_dataset_session(df, dataset_name):
    session_id = str(uuid.uuid4())


    if {"student_name", "class", "section", "admission_number"}.issubset(df.columns):

        df["student_display"] = (
            df["student_name"].fillna("").astype(str).str.strip()
            + " - " +
            df["class"].fillna("").astype(str).str.strip()
            + " - " +
            df["section"].fillna("").astype(str).str.strip()
            + " - " +
            df["admission_number"].fillna("").astype(str).str.strip()
        )

    elif {"studentname", "classname", "sectionname", "admissionno"}.issubset(df.columns):

        df["student_display"] = (
            df["studentname"].fillna("").astype(str).str.strip()
            + " - " +
            df["classname"].fillna("").astype(str).str.strip()
            + " - " +
            df["sectionname"].fillna("").astype(str).str.strip()
            + " - " +
            df["admissionno"].fillna("").astype(str).str.strip()
        )

    # if {"studentname", "classname", "sectionname"}.issubset(df.columns):
    #     df["student_display"] = (
    #         df["studentname"].astype(str).str.strip()
    #         + " - " +
    #         df["classname"].astype(str).str.strip()
    #         + " - " +
    #         df["sectionname"].astype(str).str.strip()
    #     )

    # elif {"student_name", "class", "section"}.issubset(df.columns):
    #     df["student_display"] = (
    #         df["student_name"].astype(str).str.strip()
    #         + " - " +
    #         df["class"].astype(str).str.strip()
    #         + " - " +
    #         df["section"].astype(str).str.strip()
    #     )

    # elif {"student_name", "admission_number"}.issubset(df.columns):
    #     df["student_display"] = (
    #         df["student_name"].astype(str).str.strip()
    #         + " - " +
    #         df["admission_number"].astype(str).str.strip()
    #     )

    profile = profile_dataset(df)
    schema = build_schema(dataset_name, profile)
    measures = build_measures(profile)

    DATASETS[session_id] = {
        "df": df,
        "schema": schema,
        "measures": measures
    }

    return {
        "session_id": session_id,
        "columns": [c["name"] for c in profile["columns"]],
        "dimensions": profile["dimensions"],
        "measures": list(measures.keys()),
        "rows": len(df)
    }

@app.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    df = load_dataset(file_path)

    return prepare_dataset_session(df, file.filename)


@app.post("/upload/api")
async def upload_dataset_from_api(req: ApiUploadRequest):
    try:
        df = fetch_api_data_from_curl(
            curl_command=req.curl,
            max_pages=req.max_pages
        )

        return prepare_dataset_session(df, "api_dataset")

    except Exception as e:
        return {
            "error": str(e),
            "message": "API data could not be loaded."
        }


@app.get("/dataset/{session_id}")
def get_dataset(session_id: str):
    if session_id not in DATASETS:
        return {"error": "Invalid session"}

    data = DATASETS[session_id]

    return {
        "schema": data["schema"],
        "measures": list(data["measures"].keys())
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or "default"

    if session_id not in DATASETS:
        return {
            "question": req.question,
            "answer": "Invalid session. Upload dataset first.",
            "rows": [],
            "source": "invalid_session",
            "confidence": 0.0
        }

    dataset = DATASETS[session_id]
    df = dataset["df"]
    schema = dataset["schema"]
    measures = dataset["measures"]

    domain_config = load_domain_config(req.domain)
    session = get_session(session_id)

    context_data = refine_question_with_context(req.question, session, domain_config)
    refined_question = context_data["refined_question"]

    context_used = bool(
        context_data.get("extra_filters")
        or context_data.get("force_group_by")
        or context_data.get("force_limit")
        or context_data.get("carry_measure")
        or context_data.get("carry_task")
    )

    plan = build_plan(refined_question, df, schema, measures, domain_config)

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

    result = execute_plan(plan, df, measures)

    resolver_meta = plan.get("resolver_meta", {})
    confidence = resolver_meta.get("confidence", 0.0)
    measure_conf = resolver_meta.get("measure_confidence", 0.0)
    entity_conf = resolver_meta.get("entity_confidence", 0.0)

    task = plan.get("task")
    is_multi_measure = task in ["grouped_table_multi", "single_value_multi"]

    use_fallback = False

    if not plan.get("measure") and not plan.get("measures"):
        use_fallback = True

    if task in ["grouped_table", "grouped_table_multi", "count", "count_extreme"] and not plan.get("group_by"):
        use_fallback = True

    if result["rows"] == [] and task in ["grouped_table", "grouped_table_multi", "raw_table"]:
        use_fallback = True

    # Let rule-based multi-measure plans pass more easily
    if not context_used and not is_multi_measure:
        if confidence < 0.68:
            use_fallback = True

        if measure_conf < 0.55:
            use_fallback = True

    semantic_phrases = domain_config.get("semantic_phrases_for_fallback", [])
    if any(p in req.question.lower() for p in semantic_phrases):
        use_fallback = True

    if context_used:
        use_fallback = False
        confidence = max(confidence, 0.90)

    source = "rule_based"

    if use_fallback:
        if not gemini_available():
            return {
                "question": req.question,
                "refined_question": refined_question,
                "plan": plan,
                "answer": "AI fallback is temporarily unavailable. Please try again shortly or rephrase the question more directly.",
                "rows": [],
                "source": "low_confidence_fail",
                "confidence": confidence,
                "measure_confidence": measure_conf,
                "entity_confidence": entity_conf
            }

        gemini_plan = call_gemini_planner(
            question=req.question,
            schema=schema,
            measures=measures,
            context=session.get("last_question")
        )

        if gemini_plan:
            if isinstance(gemini_plan.get("measure"), list):
                gemini_plan["measures"] = gemini_plan["measure"]
                gemini_plan["measure"] = None

            if gemini_plan.get("measures") and len(gemini_plan["measures"]) >= 2:
                if gemini_plan.get("task") == "grouped_table":
                    gemini_plan["task"] = "grouped_table_multi"
                elif gemini_plan.get("task") == "single_value":
                    gemini_plan["task"] = "single_value_multi"

            if gemini_plan.get("measures") and len(gemini_plan["measures"]) == 1 and not gemini_plan.get("measure"):
                gemini_plan["measure"] = gemini_plan["measures"][0]
                if gemini_plan.get("task") == "grouped_table_multi":
                    gemini_plan["task"] = "grouped_table"
                elif gemini_plan.get("task") == "single_value_multi":
                    gemini_plan["task"] = "single_value"

            plan = gemini_plan
            result = execute_plan(plan, df, measures)
            source = "gemini_fallback"
        else:
            if confidence < 0.7 and not is_multi_measure:
                return {
                    "question": req.question,
                    "refined_question": refined_question,
                    "plan": plan,
                    "answer": "I could not confidently understand the question. Please rephrase.",
                    "rows": [],
                    "source": "low_confidence_fail",
                    "confidence": confidence,
                    "measure_confidence": measure_conf,
                    "entity_confidence": entity_conf
                }
            source = "rule_based_failed"

    update_session(session_id, refined_question, plan, result)

    return {
        "question": req.question,
        "refined_question": refined_question,
        "plan": plan,
        "answer": result["answer"],
        "rows": result["rows"],
        "source": source,
        "confidence": confidence,
        "measure_confidence": measure_conf,
        "entity_confidence": entity_conf
    }

