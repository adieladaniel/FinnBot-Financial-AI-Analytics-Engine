import pandas as pd

import re
import pandas as pd

def is_probable_id(col_name, series):
    name = col_name.lower()

    # 1. Strong keyword detection (whole words OR suffix)
    if re.search(r'(?:^|_)(id|code|seq|no|number)(?:$|_)', name):
        return True

    # Also catch suffix patterns like enrollmentno, studentid
    if name.endswith(("id", "code", "seq", "no", "number")):
        return True

    # 2. High uniqueness integer columns → likely IDs
    if pd.api.types.is_integer_dtype(series):
        unique_ratio = series.nunique(dropna=True) / max(len(series), 1)
        if unique_ratio > 0.7:
            return True

    # 3. Whole numbers + high uniqueness
    
    if pd.api.types.is_numeric_dtype(series):
        s = series.dropna()

        if len(s) > 0 and (s % 1 == 0).all():
            unique_ratio = s.nunique() / len(s)

            if unique_ratio > 0.6:
                return True

    return False




def profile_dataset(df):
    profile = {
        "columns": [],
        "dimensions": [],
        "measures": [],
        "date_columns": [],
        "id_columns": []
    }

    for col in df.columns:
        original_s = df[col]

        # Try numeric conversion first
        numeric_series = pd.to_numeric(original_s, errors="coerce")
        numeric_ratio = numeric_series.notna().mean()

        if numeric_ratio > 0.8:
            s = numeric_series
            detected_dtype = str(s.dtype)
        else:
            s = original_s
            detected_dtype = str(s.dtype)

        info = {
            "name": col,
            "dtype": detected_dtype,
            "nulls": int(original_s.isna().sum()),
            "unique": int(original_s.nunique(dropna=True)),
            "sample": original_s.dropna().astype(str).head(5).tolist()
        }

        profile["columns"].append(info)

        # 1. Numeric detection FIRST
        if pd.api.types.is_numeric_dtype(s):
            if is_probable_id(col, s):
                profile["id_columns"].append(col)
            else:
                profile["measures"].append(col)
            continue

        # 2. Date detection ONLY for non-numeric columns
        parsed = pd.to_datetime(original_s, errors="coerce", format="mixed")
        if parsed.notna().mean() > 0.8:
            profile["date_columns"].append(col)
            continue

        # 3. Otherwise dimension
        profile["dimensions"].append(col)

    return profile