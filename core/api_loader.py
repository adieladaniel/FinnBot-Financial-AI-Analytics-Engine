import json
import shlex
import requests
import pandas as pd
from urllib.parse import urlparse


def clean_curl(curl_command: str):
    return (
        curl_command
        .replace("\\\n", " ")
        .replace("^\n", " ")
        .replace("\n", " ")
        .strip()
    )


def parse_curl(curl_command: str):
    curl_command = clean_curl(curl_command)
    tokens = shlex.split(curl_command)

    method = "GET"
    url = None
    headers = {}
    data = None
    json_body = None
    params = {}
    cookies = {}
    verify_ssl = True
    timeout = 60

    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token == "curl":
            i += 1
            continue

        if token.startswith("http://") or token.startswith("https://"):
            url = token

        elif token in ["--url"]:
            url = tokens[i + 1]
            i += 1

        elif token in ["-X", "--request"]:
            method = tokens[i + 1].upper()
            i += 1

        elif token in ["-H", "--header"]:
            header = tokens[i + 1]
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()
            i += 1

        elif token in ["-d", "--data", "--data-raw", "--data-binary", "--data-ascii"]:
            raw = tokens[i + 1]

            if method == "GET":
                method = "POST"

            try:
                json_body = json.loads(raw)
                headers.setdefault("Content-Type", "application/json")
            except Exception:
                data = raw

            i += 1

        elif token in ["-G", "--get"]:
            method = "GET"

        elif token in ["--form", "-F"]:
            data = data or {}
            form_value = tokens[i + 1]
            if "=" in form_value:
                key, value = form_value.split("=", 1)
                data[key] = value
            i += 1

        elif token in ["-b", "--cookie"]:
            cookie_raw = tokens[i + 1]
            for part in cookie_raw.split(";"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    cookies[key.strip()] = value.strip()
            i += 1

        elif token in ["-k", "--insecure"]:
            verify_ssl = False

        elif token == "--connect-timeout":
            timeout = int(float(tokens[i + 1]))
            i += 1

        elif token in ["--compressed", "-L", "--location"]:
            pass

        i += 1

    if not url:
        raise ValueError("No API URL found in cURL.")

    parsed = urlparse(url)
    if parsed.scheme not in ["http", "https"]:
        raise ValueError("Invalid API URL.")

    return {
        "method": method,
        "url": url,
        "headers": headers,
        "params": params,
        "data": data,
        "json": json_body,
        "cookies": cookies,
        "verify_ssl": verify_ssl,
        "timeout": timeout
    }


def find_largest_list(obj):
    found = []

    def walk(x):
        if isinstance(x, list):
            found.append(x)
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            for value in x.values():
                walk(value)

    walk(obj)

    if not found:
        return None

    return max(found, key=len)


def normalize_api_data(data):
    if isinstance(data, list):
        rows = data

    elif isinstance(data, dict):
        common_paths = [
            ["data"],
            ["data", "data"],
            ["result"],
            ["results"],
            ["records"],
            ["rows"],
            ["items"],
            ["response"],
            ["response", "data"],
            ["payload"],
            ["payload", "data"]
        ]

        rows = None

        for path in common_paths:
            temp = data
            valid = True

            for key in path:
                if isinstance(temp, dict) and key in temp:
                    temp = temp[key]
                else:
                    valid = False
                    break

            if valid and isinstance(temp, list):
                rows = temp
                break

        if rows is None:
            rows = find_largest_list(data)

        if rows is None:
            rows = [data]

    else:
        raise ValueError("Unsupported API response format.")

    df = pd.json_normalize(rows)

    if df.empty:
        raise ValueError("API returned empty data.")

    df.columns = [
        str(col)
        .replace(".", "_")
        .replace(" ", "_")
        .replace("-", "_")
        .lower()
        for col in df.columns
    ]

    money_keywords = [
        "fee",
        "amount",
        "payable",
        "received",
        "concession",
        "waiver",
        "outstanding",
        "balance"
    ]

    for col in df.columns:
        if any(keyword in col.lower() for keyword in money_keywords):
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def get_next_url(data):
    possible_paths = [
        ["next"],
        ["next_page"],
        ["nextPage"],
        ["links", "next"],
        ["pagination", "next"],
        ["page", "next"],
        ["meta", "next"],
        ["data", "next"]
    ]

    for path in possible_paths:
        temp = data
        valid = True

        for key in path:
            if isinstance(temp, dict) and key in temp:
                temp = temp[key]
            else:
                valid = False
                break

        if valid and isinstance(temp, str) and temp.startswith("http"):
            return temp

    return None


def fetch_api_data_from_curl(curl_command: str, max_pages: int = 1):
    req = parse_curl(curl_command)

    all_frames = []
    current_url = req["url"]

    for _ in range(max_pages):
        response = requests.request(
            method=req["method"],
            url=current_url,
            headers=req["headers"],
            params=req["params"],
            data=req["data"],
            json=req["json"],
            cookies=req["cookies"],
            timeout=req["timeout"],
            verify=req["verify_ssl"]
        )

        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError(
                f"API failed with status {response.status_code}: {response.text[:500]}"
            )

        content_type = response.headers.get("content-type", "").lower()

        if "application/json" not in content_type and not response.text.strip().startswith(("{", "[")):
            raise ValueError("API response is not JSON.")

        data = response.json()
        df = normalize_api_data(data)
        all_frames.append(df)

        next_url = get_next_url(data)

        if not next_url:
            break

        current_url = next_url

    final_df = pd.concat(all_frames, ignore_index=True)

    if final_df.empty:
        raise ValueError("No rows found from API.")

    return final_df