import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")


# cooldown state
GEMINI_COOLDOWN_UNTIL = 0


def _now():
    return time.time()


def gemini_available():
    return _now() >= GEMINI_COOLDOWN_UNTIL


def _set_cooldown(seconds: int):
    global GEMINI_COOLDOWN_UNTIL
    GEMINI_COOLDOWN_UNTIL = max(GEMINI_COOLDOWN_UNTIL, _now() + seconds)


def _extract_retry_delay_seconds(error_json: dict) -> int | None:
    try:
        details = error_json.get("error", {}).get("details", [])
        for item in details:
            if item.get("@type", "").endswith("RetryInfo"):
                retry_delay = item.get("retryDelay", "")
                if retry_delay.endswith("s"):
                    return int(float(retry_delay[:-1]))
    except Exception:
        pass
    return None


def _extract_json_from_text(text: str):
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end])
    except Exception:
        return None


def enforce_finance_plan_rules(plan, schema, question):
    q = question.lower()

    if not isinstance(plan, dict):
        return plan

    dimensions = schema.get("dimensions", [])

    if "student_display" in dimensions and ("student" in q or "students" in q):
        plan["group_by"] = ["student_display"]

    if "sort_by" not in plan and plan.get("measure"):
        plan["sort_by"] = plan["measure"]

    if "filters" not in plan or not isinstance(plan["filters"], list):
        plan["filters"] = []

    if (
        plan.get("task") == "grouped_table"
        and "highest" in q
        and plan.get("measure")
    ):
        measure_col = plan["measure"].replace("Sum ", "").strip()

        already_filtered = any(
            isinstance(f, dict) and f.get("column") == measure_col
            for f in plan["filters"]
        )

        if not already_filtered:
            plan["filters"].append({
                "column": measure_col,
                "operator": "gt",
                "values": [0]
            })

    normalized_filters = []

    for f in plan.get("filters", []):

        if not isinstance(f, dict):
            continue

        # Gemini sometimes sends dimension instead of column
        if "dimension" in f and "column" not in f:
            f["column"] = f["dimension"]

        # remove Sum prefix
        if "column" in f and isinstance(f["column"], str):
            f["column"] = (
                f["column"]
                .replace("Sum ", "")
                .replace("Avg ", "")
                .strip()
            )

        # Gemini sends value instead of values
        if "value" in f and "values" not in f:
            f["values"] = [f["value"]]

        # normalize operators
        op_map = {
            "=": "eq",
            ">": "gt",
            "<": "lt",
            ">=": "gte",
            "<=": "lte"
        }

        if f.get("operator") in op_map:
            f["operator"] = op_map[f["operator"]]

        normalized_filters.append(f)

    plan["filters"] = normalized_filters

    return plan

def call_gemini_planner(question, schema, measures, context=None):
    global GEMINI_COOLDOWN_UNTIL

    if not gemini_available():
        remaining = int(GEMINI_COOLDOWN_UNTIL - _now())
        print(f"Gemini skipped due to cooldown. Retry after {remaining}s.")
        return None

    models = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash"
    ]

    prompt = f"""
You are a data analytics planner.

Convert the user question into a JSON plan for a deterministic analytics engine.

Available dimension columns:
{schema.get("dimensions", [])}

Available measures:
{list(measures.keys())}

Previous context:
{context}

Question:
{question}

Return ONLY valid JSON in this exact format:
{{
  "task": "grouped_table | single_value | count | count_extreme | raw_table",
  "group_by": [],
  "measure": "",
  "sort_order": "asc | desc",
  "limit": 10,
  "filters": []
}}
""".strip()

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=20)

                if response.status_code == 200:
                    data = response.json()

                    if "candidates" not in data or not data["candidates"]:
                        print("Gemini unexpected response:", data)
                        break

                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if not parts:
                        print("Gemini missing parts:", data)
                        break

                    text = parts[0].get("text", "")
                    if not text:
                        print("Gemini empty text:", data)
                        break

                    plan = _extract_json_from_text(text)
                    if not isinstance(plan, dict):
                        print("Gemini returned non-JSON text:", text)
                        break
                    plan = enforce_finance_plan_rules(plan, schema, question)
                    return plan

                try:
                    err = response.json()
                except Exception:
                    err = {"raw_text": response.text}

                print(f"Gemini HTTP error [{model}] attempt {attempt+1}: {response.status_code} {err}")

                # quota / exhausted
                if response.status_code == 429:
                    retry_after = _extract_retry_delay_seconds(err) or 60
                    _set_cooldown(retry_after)
                    return None

                # temporary unavailable / high demand
                if response.status_code == 503:
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    _set_cooldown(30)
                    break

                # model not found / invalid / auth issues -> try next model
                if response.status_code in [400, 401, 403, 404]:
                    break

                # other 5xx -> short retry once
                if 500 <= response.status_code < 600:
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    break

                break

            except Exception as e:
                print(f"Gemini parsing/network error [{model}] attempt {attempt+1}: {str(e)}")
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    return None