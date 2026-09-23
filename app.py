from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import time
import uuid

from core.loader import load_dataset
from core.profiler import profile_dataset
from core.schema_builder import build_schema
from core.measures_builder import build_measures
from core.memory import get_session, update_session, append_history
from core.config_loader import load_domain_config
from core.api_loader import fetch_api_data_from_curl
from core.graph import GRAPH
from core.graph_state import ChatState

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
    domain_config = load_domain_config(req.domain)
    session = get_session(session_id)

    initial_state: ChatState = {
        "session_id": session_id,
        "question": req.question,
        "domain": req.domain,
        "df": dataset["df"],
        "schema": dataset["schema"],
        "measures": dataset["measures"],
        "domain_config": domain_config,
        "session": session,
    }

    final_state = GRAPH.invoke(initial_state)

    plan = final_state.get("plan", {})
    result = final_state.get("result") or {"answer": "", "rows": []}
    refined_question = final_state.get("refined_question", req.question)

    update_session(session_id, refined_question, plan, result)

    source = final_state.get("source", "rule_based")
    confidence = final_state.get("confidence", 0.0)

    append_history(session_id, {
        "question": req.question,
        "answer": result.get("answer"),
        "source": source,
        "confidence": confidence,
        "row_count": len(result.get("rows", [])),
        "timestamp": time.time()
    })

    return {
        "question": req.question,
        "normalized_question": final_state.get("question", req.question),
        "refined_question": refined_question,
        "plan": plan,
        "answer": result.get("answer"),
        "rows": result.get("rows", []),
        "source": source,
        "confidence": confidence,
        "measure_confidence": final_state.get("measure_confidence", 0.0),
        "entity_confidence": final_state.get("entity_confidence", 0.0)
    }


@app.get("/history/{session_id}")
def get_history(session_id: str):
    if session_id not in DATASETS:
        return {"error": "Invalid session"}

    session = get_session(session_id)
    return {"history": list(reversed(session.get("history", [])))}

