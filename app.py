import json
import re
from pathlib import Path
from typing import Any
import hashlib
import time

import os
from dotenv import load_dotenv

import pandas as pd
from collections import defaultdict 
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "fee_compile_dataset_merged_powerbi.json"
SCHEMA_PATH = BASE_DIR / "schema.json"
MEASURES_PATH = BASE_DIR / "measures.json"
SESSION_MEMORY = defaultdict(dict)
RESULT_CACHE = {}
CACHE_TTL_SECONDS = 300

with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    SCHEMA = json.load(f)

with open(MEASURES_PATH, "r", encoding="utf-8") as f:
    MEASURES = json.load(f)

with open(DATA_PATH, "r", encoding="utf-8") as f:
    raw_data = json.load(f)

df = pd.json_normalize(raw_data)
df["student_display"] = (
    df["studentname"].astype(str) + " - " +
    df["classname"].astype(str) + " - " +
    df["sectionname"].astype(str)
)

NUMERIC_COLUMNS = [
    "totalamount",
    "concession_amount",
    "waiver_amount",
    "total_payable_amount",
    "paid_amount",
    "balance_amount",
    "enrollmentno",
    "academicyearid",
    "classseq",
    "studentstatusid"
]
for col in NUMERIC_COLUMNS:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class ChatRequest(BaseModel):
    question: str
    report_filters: list[dict[str, Any]] = []
    session_id:str


def build_measure_alias_map():
    alias_map = {}
    for measure_name, measure_def in MEASURES.items():
        alias_map[measure_name.lower()] = measure_name
        for alias in measure_def.get("aliases", []):
            alias_map[alias.lower()] = measure_name
    return alias_map


MEASURE_ALIAS_MAP = build_measure_alias_map()

GROUP_BY_ALIASES = {
    "class": ["classname"],
    "classname": ["classname"],
    "section": ["sectionname"],
    "sectionname": ["sectionname"],
    "student": ["student_display"],
    "students": ["student_display"],
    "studentname": ["student_display"],
    "component": ["componentname"],
    "componentname": ["componentname"],
    "fee component": ["componentname"],
    "category": ["feecategory"],
    "fee category": ["feecategory"],
    "period": ["periodname"],
    "periodname": ["periodname"],
    "installment": ["installmentname"],
    "installmentname": ["installmentname"],
    "school": ["school_db"],
    "school_db": ["school_db"],
    "academic year": ["academicyearname"],
    "year": ["academicyearname"],
    "gender": ["gender"]
}


def find_measure_from_question(question: str):
    q = question.lower()
    matches = []

    for alias, measure_name in MEASURE_ALIAS_MAP.items():
        if alias in q:
            matches.append((len(alias), measure_name))

    if not matches:
        return None

    matches.sort(reverse=True)
    return matches[0][1]

def find_group_by_from_question(question: str):
    q = question.lower()

    for alias, cols in GROUP_BY_ALIASES.items():
        if f"by {alias}" in q or f"group by {alias}" in q:
            return cols

    if "student" in q or "defaulter" in q or "defaulters" in q:
        return ["student_display"]

    return []


def find_limit_from_question(question: str):
    q = question.lower()

    limit = 10
    sort_order = "desc"

    top_match = re.search(r"\btop\s+(\d+)\b", q)
    bottom_match = re.search(r"\bbottom\s+(\d+)\b", q)

    if top_match:
        limit = int(top_match.group(1))
    elif bottom_match:
        limit = int(bottom_match.group(1))
        sort_order = "asc"

    if any(word in q for word in ["lowest", "least", "minimum", "min"]):
        sort_order = "asc"
        if not top_match and not bottom_match:
            limit = 1

    elif any(word in q for word in ["highest", "largest", "maximum", "max"]):
        sort_order = "desc"
        if not top_match and not bottom_match:
            limit = 1

    return limit, sort_order

import re

def extract_filters_from_question(question: str):
    filters = []
    q = question.lower()

    searchable_columns = [
        "classname",
        "sectionname",
        "academicyearname",
        "school_db",
        "componentname",
        "periodname",
        "installmentname"
    ]

    for col in searchable_columns:
        if col not in df.columns:
            continue

        unique_vals = df[col].dropna().astype(str).unique().tolist()

        for original_val in unique_vals:
            val = str(original_val).strip()
            val_lower = val.lower()

            if not val_lower:
                continue

            if col == "classname":
                pattern = rf"\bclass\s+{re.escape(val_lower)}\b"
                if re.search(pattern, q):
                    filters.append({
                        "column": col,
                        "operator": "eq",
                        "values": [original_val]
                    })

            elif col == "sectionname":
                pattern = rf"\bsection\s+{re.escape(val_lower)}\b"
                if re.search(pattern, q):
                    filters.append({
                        "column": col,
                        "operator": "eq",
                        "values": [original_val]
                    })

            else:
                pattern = rf"\b{re.escape(val_lower)}\b"
                if len(val_lower) >= 3 and re.search(pattern, q):
                    filters.append({
                        "column": col,
                        "operator": "eq",
                        "values": [original_val]
                    })

    if any(word in q for word in ["pending", "outstanding", "due", "unpaid"]):
        if "balance_amount" in df.columns:
            filters.append({
                "column": "balance_amount",
                "operator": "gt",
                "values": [0]
            })

    return filters
    


def rule_based_plan(question: str):
    q = question.lower().strip()

    measure = find_measure_from_question(q)
    group_by = find_group_by_from_question(q)
    filters = extract_filters_from_question(q)
    limit, sort_order = find_limit_from_question(q)

    if any(word in q for word in ["top", "bottom", "highest", "lowest"]) and measure and group_by:
        return {
            "task": "grouped_table",
            "measure": measure,
            "group_by": group_by,
            "columns": [],
            "filters": filters,
            "sort_by": measure,
            "sort_order": sort_order,
            "limit": limit
        }

    if " by " in q and measure and group_by:
        return {
            "task": "grouped_table",
            "measure": measure,
            "group_by": group_by,
            "columns": [],
            "filters": filters,
            "sort_by": measure,
            "sort_order": "desc",
            "limit": limit
        }

    if any(word in q for word in ["list", "show rows", "details", "records"]):
        # columns = ["studentname", "enrollmentno", "classname", "sectionname", "componentname", "paid_amount", "balance_amount"]
        columns = ["studentname", "enrollmentno", "classname", "sectionname", "componentname", "totalamount", "paid_amount", "balance_amount"]
        columns = [c for c in columns if c in df.columns]
        return {
            "task": "raw_table",
            "measure": None,
            "group_by": [],
            "columns": columns,
            "filters": filters,
            "sort_by": "balance_amount" if "balance_amount" in df.columns else None,
            "sort_order": "desc",
            "limit": limit
        }

    if measure:
        return {
            "task": "single_value",
            "measure": measure,
            "group_by": [],
            "columns": [],
            "filters": filters,
            "sort_by": None,
            "sort_order": "desc",
            "limit": limit
        }

    return None


def compact_schema_for_llm():
    return {
        "columns": [c["name"] for c in SCHEMA["columns"]],
        "default_grouping_keys": SCHEMA.get("default_grouping_keys", [])
    }


def compact_measures_for_llm():
    return {
        measure_name: {
            "aliases": measure_def.get("aliases", [])
        }
        for measure_name, measure_def in MEASURES.items()
    }


def build_prompt(question: str) -> str:
    schema_text = json.dumps(compact_schema_for_llm(), ensure_ascii=False)
    measures_text = json.dumps(compact_measures_for_llm(), ensure_ascii=False)

    return f"""
You are an analytics planner.

Columns:
{schema_text}

Measures:
{measures_text}

User question:
{question}

Return ONLY valid JSON in this exact format:
{{
  "task": "single_value | grouped_table | raw_table",
  "measure": "measure name or null",
  "group_by": ["col1", "col2"],
  "columns": ["col1", "col2"],
  "filters": [
    {{
      "column": "column_name",
      "operator": "eq | in | gt | lt",
      "values": ["value"]
    }}
  ],
  "sort_by": "measure or column name",
  "sort_order": "asc | desc",
  "limit": 10
}}

Rules:
- Use only the provided columns and measures.
- For student-level queries, prefer grouping by ["studentname", "enrollmentno"].
- For totals/KPI return single_value.
- For top/bottom/by/grouped summary return grouped_table.
- For list/details/rows return raw_table.
- If user refers to pending/due/outstanding/unpaid, map to "Total Balance".
- Return JSON only. No explanation.
"""


def extract_json(text: str):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No valid JSON found in Gemini response")
    return json.loads(match.group(0))


def llm_plan(question: str):
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_prompt(question)
    )
    return extract_json(response.text.strip())


def apply_filters(data: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
    filtered = data.copy()

    for f in filters:
        column = f.get("column")
        operator = f.get("operator")
        values = f.get("values", [])

        if column not in filtered.columns:
            continue

        if operator == "eq" and values:
            filtered = filtered[filtered[column].astype(str) == str(values[0])]
        elif operator == "in" and values:
            filtered = filtered[filtered[column].astype(str).isin([str(v) for v in values])]
        elif operator == "gt" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") > float(values[0])]
        elif operator == "lt" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") < float(values[0])]

    return filtered


def get_measure_value(data: pd.DataFrame, measure_name: str):
    measure = MEASURES[measure_name]
    col = measure["column"]
    agg = measure["agg"]

    if agg == "sum":
        return data[col].sum()
    if agg == "mean":
        return data[col].mean()
    if agg == "max":
        return data[col].max()
    if agg == "min":
        return data[col].min()

    raise ValueError("Unsupported aggregation")


def format_value(value, fmt="number"):
    if pd.isna(value):
        return "N/A"
    if fmt == "currency":
        return f"{value:,.2f}"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}"
    return str(value)


def execute_plan(plan: dict, report_filters: list[dict[str, Any]]) -> dict:
    combined_filters = report_filters + plan.get("filters", [])
    data = apply_filters(df, combined_filters)

    task = plan.get("task")
    measure = plan.get("measure")
    group_by = plan.get("group_by", [])
    columns = plan.get("columns", [])
    sort_by = plan.get("sort_by")
    sort_order = plan.get("sort_order", "desc")
    limit = int(plan.get("limit", 10) or 10)

    if task == "single_value":
        if not measure or measure not in MEASURES:
            return {"answer": "I could not map that question to a valid measure.", "rows": []}

        value = get_measure_value(data, measure)
        fmt = MEASURES[measure].get("format", "number")
        return {
            "answer": f"{measure}: {format_value(value, fmt)}",
            "rows": []
        }

    if task == "grouped_table":
        if not measure or measure not in MEASURES or not group_by:
            return {"answer": "I could not identify a valid grouped analysis.", "rows": []}

        group_by = [g for g in group_by if g in data.columns]
        if not group_by:
            return {"answer": "No valid grouping columns found.", "rows": []}

        measure_def = MEASURES[measure]
        grouped = data.groupby(group_by, dropna=False)[measure_def["column"]].agg(measure_def["agg"]).reset_index()
        grouped = grouped.rename(columns={measure_def["column"]: measure})

        if sort_by in grouped.columns:
            grouped = grouped.sort_values(by=sort_by, ascending=(sort_order == "asc"))
        elif measure in grouped.columns:
            grouped = grouped.sort_values(by=measure, ascending=(sort_order == "asc"))

        grouped = grouped.head(limit)
        rows = grouped.fillna("").to_dict(orient="records")

        if rows:
            first = rows[0]
            entity = " | ".join(str(first[g]) for g in group_by)
            return {
                "answer": f"Top result: {entity} with {format_value(first[measure], MEASURES[measure].get('format', 'number'))}",
                "rows": rows
            }

        return {"answer": "No matching rows found.", "rows": []}

    if task == "raw_table":
        keep_cols = [c for c in columns if c in data.columns]
        if not keep_cols:
            keep_cols = [c for c in ["studentname", "enrollmentno", "classname", "sectionname", "componentname", "paid_amount", "balance_amount"] if c in data.columns]

        raw = data[keep_cols].copy()

        if sort_by and sort_by in raw.columns:
            raw = raw.sort_values(by=sort_by, ascending=(sort_order == "asc"))

        raw = raw.head(limit)
        rows = raw.fillna("").astype(str).to_dict(orient="records")

        return {
            "answer": f"Found {len(rows)} matching rows.",
            "rows": rows
        }

    return {"answer": "I could not process that request. LOL ", "rows": []}

def build_cache_key(session_id: str, question:str, report_filters:list[dict[str, Any]]):
    raw=json.dumps({
        "session_id":session_id,
        "question":question.lower().strip(),
        "report_filters":report_filters
    }, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()

def get_cached_result(cache_key:str):
    item=RESULT_CACHE.get(cache_key)
    if not item:
        return None
    
    if time.time() - item["timestamp"]>CACHE_TTL_SECONDS:
        del RESULT_CACHE[cache_key]
        return None
    return item["value"]

def set_cached_result(cache_key:str, value:dict):
    RESULT_CACHE[cache_key] = {
        "timestamp":time.time(),
        "value":value
    }

def update_session_memory(session_id:str, question:str, plan:dict, result:dict):
    memory = SESSION_MEMORY[session_id]
    
    memory["last_question"] = question
    memory["last_plan"] = plan
    memory["last_result"] = result.get("answer")
    memory["last_rows"] = result.get("rows", [])

    if plan.get("measure"):
        memory["last_measure"] = plan["measure"]

    if plan.get("group_by"):
        memory["last_group_by"] = plan["group_by"]

    if plan.get("filters"):
        memory["last_filters"] = plan["filters"]

    rows=result.get(rows, [])
    if rows:
        first_row = rows[0]
        if "student_display" in first_row:
            memory["last_student_display"] = first_row["student_display"]
        if "classname" in first_row:
            memory["last_classname"] = first_row["classname"]
        if "sectionname" in first_row:
            memory["last_sectionname"] = first_row["sectionname"]
        
        memory["last_top_row"] = first_row

def is_followup_question(question:str):
    q=question.lower().strip()
    followup_terms = [
        "his", "her", "that student", "that one", "same student",
        "same class", "same section", "what about", "also",
        "now show", "only top", "top one", "this student"
    ]
    return any(term in q for term in followup_terms)

def resolve_followup_question(session_id:str, question:str):
    memory = SESSION_MEMORY.get(session_id, {})
    if not memory:
        return None
    q=question.lower().strip()

    inferred_measure = find_measure_from_question(q) or memory.get("last_measure")
    inferred_group_by = find_group_by_from_question(q) or memory.get("last_group_by")
    inferred_filters = []

    if "his" or "her" or "that student" or "same student" or "this student" in q:
        student_display = memory.get("last_student_display")
        if student_display:
            inferred_filters.append({
                "column": "student_display",
                "operator": "eq",
                "values": [student_display]
            })

    if "same class" in q:
        classname = memory.get("last_classname")
        if classname:
            inferred_filters.append({
                "column": "classname",
                "operator": "eq",
                "values": [classname]
            })
    if "same section" in q:
        sectionname = memory.get("last_sectionname")
        if sectionname:
            inferred_filters.append({
                "column": "sectionname",
                "operator": "eq",
                "values": [sectionname]
            })

    explicit_filters = extract_filters_from_question(q)
    inferred_filters.extend(explicit_filters)

    limit, sort_order =find_limit_from_question(question)
    if "only top one" in q or "top one" in q or "highest" in q:
        limit = 1
        sort_order = "desc"

    if "lowest" in q or "least" in q or "minimum" in q:
        limit = 1 if "top" not in q else limit
        sort_order = "asc"

    if any(word in q for word in ["what is", "how much", "tell me", "total", "give", "show the"]):
        if inferred_measure and inferred_filters:
            return {
                "task": "single_value",
                "measure": inferred_measure,
                "group_by": [],
                "columns": [],
                "filters": inferred_filters,
                "sort_by": None,
                "sort_order": "desc",
                "limit": 1
            }

    if inferred_measure and inferred_group_by:
        return {
            "task": "grouped_table",
            "measure": inferred_measure,
            "group_by": inferred_group_by,
            "columns": [],
            "filters": inferred_filters,
            "sort_by": inferred_measure,
            "sort_order": sort_order,
            "limit": limit
        }

    if inferred_measure:
        return {
            "task": "single_value",
            "measure": inferred_measure,
            "group_by": [],
            "columns": [],
            "filters": inferred_filters,
            "sort_by": None,
            "sort_order": "desc",
            "limit": 1
        }
    return None




@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        plan = rule_based_plan(req.question)
        source = "rule_based"

        if not plan:
            plan = llm_plan(req.question)
            source = "gemini"

        result = execute_plan(plan, req.report_filters)

        return {
            "question": req.question,
            "planner_used": source,
            "plan": plan,
            "answer": result["answer"],
            "rows": result["rows"]
        }

    except Exception as e:
        return {
            "question": req.question,
            "answer": f"Error: {str(e)}",
            "rows": []
        }