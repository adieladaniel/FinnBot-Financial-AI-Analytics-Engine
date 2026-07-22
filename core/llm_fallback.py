import os
import time
from dotenv import load_dotenv
from google.genai.errors import APIError, ClientError, ServerError
from langchain_google_genai import ChatGoogleGenerativeAI

from core.plan_schema import LLMPlan

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")


MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

# cooldown state
GEMINI_COOLDOWN_UNTIL = 0


def _now():
    return time.time()


def gemini_available():
    return _now() >= GEMINI_COOLDOWN_UNTIL


def _set_cooldown(seconds: int):
    global GEMINI_COOLDOWN_UNTIL
    GEMINI_COOLDOWN_UNTIL = max(GEMINI_COOLDOWN_UNTIL, _now() + seconds)


def _extract_retry_delay_seconds(error: ClientError) -> int:
    payload = getattr(error, "details", None)
    if not isinstance(payload, dict):
        return 60

    inner = payload.get("error", payload)

    for item in inner.get("details", []) or []:
        if isinstance(item, dict) and item.get("@type", "").endswith("RetryInfo"):
            retry_delay = item.get("retryDelay", "")
            if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                try:
                    return int(float(retry_delay[:-1]))
                except ValueError:
                    pass

    return 60


def enforce_finance_plan_rules(plan: dict, schema: dict, question: str) -> dict:
    q = question.lower()

    dimensions = schema.get("dimensions", [])

    if "student_display" in dimensions and ("student" in q or "students" in q):
        plan["group_by"] = ["student_display"]

    if not plan.get("filters"):
        plan["filters"] = []

    if (
        plan.get("task") == "grouped_table"
        and "highest" in q
        and plan.get("measure")
    ):
        measure_col = plan["measure"].replace("Sum ", "").strip()

        already_filtered = any(
            f.get("column") == measure_col for f in plan["filters"]
        )

        if not already_filtered:
            plan["filters"].append({
                "column": measure_col,
                "operator": "gt",
                "values": ["0"]
            })

    for f in plan["filters"]:
        if isinstance(f.get("column"), str):
            f["column"] = (
                f["column"]
                .replace("Sum ", "")
                .replace("Avg ", "")
                .strip()
            )

    return plan


def call_gemini_planner(question, schema, measures, context=None):
    if not gemini_available():
        remaining = int(GEMINI_COOLDOWN_UNTIL - _now())
        print(f"Gemini skipped due to cooldown. Retry after {remaining}s.")
        return None

    prompt = f"""
You are a data analytics planner.

Convert the user question into a structured plan for a deterministic analytics engine.

Available dimension columns:
{schema.get("dimensions", [])}

Available measures:
{list(measures.keys())}

Previous context:
{context}

Question:
{question}
""".strip()

    for model_name in MODELS:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=GEMINI_API_KEY,
            temperature=0,
        ).with_structured_output(LLMPlan)

        for attempt in range(2):
            try:
                result: LLMPlan = llm.invoke(prompt)
                plan = result.model_dump()
                plan = enforce_finance_plan_rules(plan, schema, question)
                return plan

            except ClientError as e:
                if e.code == 429:
                    retry_after = _extract_retry_delay_seconds(e)
                    print(f"Gemini quota exhausted [{model_name}]: {e}")
                    _set_cooldown(retry_after)
                    return None

                # bad model name / auth / invalid request -> try next model
                print(f"Gemini client error [{model_name}] (code={e.code}): {e}")
                break

            except ServerError as e:
                print(f"Gemini unavailable [{model_name}] attempt {attempt + 1}: {e}")
                if attempt == 0:
                    time.sleep(2)
                    continue
                _set_cooldown(30)
                break

            except APIError as e:
                print(f"Gemini API error [{model_name}]: {e}")
                break

            except Exception as e:
                print(f"Gemini parsing/network error [{model_name}] attempt {attempt + 1}: {e}")
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    return None
