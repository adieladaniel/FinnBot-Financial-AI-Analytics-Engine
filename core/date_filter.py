import re
import calendar
from datetime import date, timedelta
import pandas as pd


DATE_KEYWORDS = [
    "date",
    "day",
    "month",
    "year",
    "receipt",
    "received",
    "payment",
    "collection",
    "period",
    "installment"
]


def find_date_column(df):
    candidates = []

    for col in df.columns:
        c = col.lower()

        if any(k in c for k in DATE_KEYWORDS):
            converted = pd.to_datetime(df[col], errors="coerce", dayfirst=False)
            valid_ratio = converted.notna().mean()

            if valid_ratio > 0.5:
                candidates.append((col, valid_ratio))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    return None


def parse_date_range(question, today=None):
    q = question.lower()
    today = today or date.today()

    if "today" in q:
        return today, today

    if "yesterday" in q:
        d = today - timedelta(days=1)
        return d, d

    if "this month" in q or "current month" in q:
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return start, end

    if "last month" in q or "previous month" in q:
        first_this_month = date(today.year, today.month, 1)
        last_month_end = first_this_month - timedelta(days=1)
        start = date(last_month_end.year, last_month_end.month, 1)
        return start, last_month_end

    day_month_match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|october|oct|november|nov|december|dec)"
        r"(?:\s+(20\d{2}))?\b",
        q
    )

    if day_month_match:
        day = int(day_month_match.group(1))
        month_text = day_month_match.group(2)
        year = int(day_month_match.group(3)) if day_month_match.group(3) else today.year

        month_map = {
            "january": 1, "jan": 1,
            "february": 2, "feb": 2,
            "march": 3, "mar": 3,
            "april": 4, "apr": 4,
            "may": 5,
            "june": 6, "jun": 6,
            "july": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9,
            "october": 10, "oct": 10,
            "november": 11, "nov": 11,
            "december": 12, "dec": 12
        }

        d = date(year, month_map[month_text], day)
        return d, d

    month_map = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12
    }

    for name, month_num in month_map.items():
        if re.search(rf"\b{name}\b", q):
            year_match = re.search(r"\b(20\d{2})\b", q)
            year = int(year_match.group(1)) if year_match else today.year
            start = date(year, month_num, 1)
            end = date(year, month_num, calendar.monthrange(year, month_num)[1])
            return start, end

    date_patterns = [
        r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
        r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"
    ]

    for pattern in date_patterns:
        m = re.search(pattern, q)

        if not m:
            continue

        parts = list(map(int, m.groups()))

        if pattern.startswith(r"\b(\d{4})"):
            d = date(parts[0], parts[1], parts[2])
        else:
            d = date(parts[2], parts[1], parts[0])

        return d, d

    return None, None


def add_date_filter_to_plan(plan, question, df):
    start, end = parse_date_range(question)

    if not start or not end:
        return plan

    date_col = find_date_column(df)

    if not date_col:
        return plan

    filters = plan.get("filters", [])

    filters.append({
        "column": date_col,
        "operator": "date_between",
        "values": [str(start), str(end)]
    })

    plan["filters"] = filters

    return plan


def detect_month_comparison(question, today=None):
    q = question.lower()
    today = today or date.today()

    month_map = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9,
        "october": 10, "oct": 10,
        "november": 11,
        "december": 12
    }

    if " vs " not in q and " versus " not in q and " compare " not in q:
        return None

    found = []

    for name, num in month_map.items():
        if re.search(rf"\b{name}\b", q):
            found.append((name, num))

    unique = []
    seen = set()

    for name, num in found:
        if num not in seen:
            unique.append((name, num))
            seen.add(num)

    if len(unique) < 2:
        return None

    year_match = re.search(r"\b(20\d{2})\b", q)
    year = int(year_match.group(1)) if year_match else today.year

    return [
        {
            "label": name.capitalize(),
            "start": str(date(year, num, 1)),
            "end": str(date(year, num, calendar.monthrange(year, num)[1]))
        }
        for name, num in unique[:2]
    ]



def add_month_comparison_to_plan(plan, question, df):
    comparison = detect_month_comparison(question)

    if not comparison:
        return plan

    date_col = find_date_column(df)

    if not date_col:
        return plan

    plan["task"] = "grouped_table"
    plan["group_by"] = ["_month_bucket"]
    plan["month_comparison"] = {
        "date_column": date_col,
        "buckets": comparison
    }

    plan["filters"] = [
        f for f in plan.get("filters", [])
        if f.get("operator") != "date_between"
        and f.get("column") != "academic_year"
        and f.get("dimension") != "academic_year"
    ]

    return plan