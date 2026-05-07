import pandas as pd


def apply_filters(data: pd.DataFrame, filters: list[dict]):
    filtered = data.copy()

    for f in filters:
        column = f.get("column")
        operator = f.get("operator")
        values = f.get("values", [])

        # Add this block here
        if "value" in f and "values" not in f:
            values = [f.get("value")]

        if operator == "=":
            operator = "eq"
        elif operator == ">":
            operator = "gt"
        elif operator == "<":
            operator = "lt"
        elif operator == ">=":
            operator = "gte"
        elif operator == "<=":
            operator = "lte"

        if column not in filtered.columns:
            continue

        if operator == "date_between" and len(values) == 2:
            start = pd.to_datetime(values[0], errors="coerce")
            end = pd.to_datetime(values[1], errors="coerce")

            col_dates = pd.to_datetime(filtered[column], errors="coerce")

            filtered = filtered[
                (col_dates >= start) &
                (col_dates <= end)
            ]

            continue


        if operator == "eq" and values:
            val = values[0]

            if pd.api.types.is_numeric_dtype(filtered[column]) or isinstance(val, (int, float)):
                filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") == float(val)]
            else:
                filtered = filtered[filtered[column].astype(str) == str(val)]

        elif operator == "in" and values:
            filtered = filtered[filtered[column].astype(str).isin([str(v) for v in values])]

        elif operator == "gt" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") > float(values[0])]

        elif operator == "lt" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") < float(values[0])]

        elif operator == "gte" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") >= float(values[0])]

        elif operator == "lte" and values:
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") <= float(values[0])]
        print("APPLYING FILTER:", column, operator, values)

    return filtered


def get_measure_value(data: pd.DataFrame, measure_name: str, measures: dict):
    measure = measures[measure_name]
    col = measure["column"]
    agg = measure["agg"]

    if col not in data.columns:
        raise ValueError(f"Column not found for measure: {col}")

    if agg == "sum":
        return data[col].sum()
    if agg == "mean":
        return data[col].mean()
    if agg == "max":
        return data[col].max()
    if agg == "min":
        return data[col].min()

    raise ValueError(f"Unsupported aggregation: {agg}")


def format_value(value):
    if pd.isna(value):
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}"
    return str(value)


def _remove_blank_groups(data, group_by):
    filtered_data = data.copy()
    for g in group_by:
        filtered_data = filtered_data[
            filtered_data[g].notna() &
            (filtered_data[g].astype(str).str.strip() != "")
        ]
    return filtered_data


def _normalize_plan_shapes(plan: dict):
    task = plan.get("task")
    measure = plan.get("measure")
    measures_list = plan.get("measures")

    # Gemini may return measure as list instead of measures
    if isinstance(measure, list):
        plan["measures"] = measure
        plan["measure"] = None
        if task == "grouped_table":
            plan["task"] = "grouped_table_multi"
        elif task == "single_value":
            plan["task"] = "single_value_multi"

    # If measures exists but task is single-measure, upgrade it
    if isinstance(measures_list, list) and len(measures_list) >= 2:
        if task == "grouped_table":
            plan["task"] = "grouped_table_multi"
        elif task == "single_value":
            plan["task"] = "single_value_multi"

    # If measures exists but only one item, collapse to single measure
    if isinstance(measures_list, list) and len(measures_list) == 1 and not plan.get("measure"):
        plan["measure"] = measures_list[0]
        if task == "grouped_table_multi":
            plan["task"] = "grouped_table"
        elif task == "single_value_multi":
            plan["task"] = "single_value"

    return plan


def execute_plan(plan: dict, df, measures: dict):
    plan = _normalize_plan_shapes(plan)


    if plan.get("month_comparison"):
        mc = plan["month_comparison"]
        date_col = mc["date_column"]
        buckets = mc["buckets"]

        df = df.copy()
        df["_month_bucket"] = None

        col_dates = pd.to_datetime(df[date_col], errors="coerce")

        for bucket in buckets:
            start = pd.to_datetime(bucket["start"])
            end = pd.to_datetime(bucket["end"])
            label = bucket["label"]

            df.loc[
                (col_dates >= start) & (col_dates <= end),
                "_month_bucket"
            ] = label

        df = df[df["_month_bucket"].notna()]

    data = apply_filters(df, plan.get("filters", []))

    task = plan.get("task")
    measure = plan.get("measure")
    measures_list = plan.get("measures", [])
    group_by = plan.get("group_by", [])
    columns = plan.get("columns", [])
    sort_by = plan.get("sort_by")
    sort_order = plan.get("sort_order", "desc")
    limit = int(plan.get("limit", 10) or 10)

    if task == "single_value":
        if not isinstance(measure, str) or measure not in measures:
            return {"answer": "I could not map that question to a valid measure.", "rows": []}

        value = get_measure_value(data, measure, measures)
        return {
            "answer": f"{measure}: {format_value(value)}",
            "rows": []
        }

    if task == "single_value_multi":
        if not isinstance(measures_list, list) or not measures_list:
            return {"answer": "I could not identify valid measures for comparison.", "rows": []}

        result_row = {}
        for m in measures_list:
            if isinstance(m, str) and m in measures:
                result_row[m] = format_value(get_measure_value(data, m, measures))

        if not result_row:
            return {"answer": "I could not identify valid measures for comparison.", "rows": []}

        return {
            "answer": "Computed multiple measures.",
            "rows": [result_row]
        }

    if task == "grouped_table":
        if not isinstance(measure, str) or measure not in measures or not group_by:
            return {"answer": "I could not identify a valid grouped analysis.", "rows": []}

        group_by = [g for g in group_by if g in data.columns]
        if not group_by:
            return {"answer": "No valid grouping columns found.", "rows": []}

        filtered_data = _remove_blank_groups(data, group_by)

        measure_def = measures[measure]
        measure_col = measure_def["column"]
        agg = measure_def["agg"]

        filtered_data[measure_col] = pd.to_numeric(
            filtered_data[measure_col],
            errors="coerce"
        ).fillna(0)

        grouped = (
            filtered_data
            .groupby(group_by, dropna=False)[measure_col]
            .agg(agg)
            .reset_index()
        )

        grouped = grouped.rename(columns={measure_col: measure})

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
                "answer": f"Top result: {entity} with {format_value(first[measure])}",
                "rows": rows
            }

        return {"answer": "No matching rows found.", "rows": []}

    if task == "grouped_table_multi":
        if not isinstance(measures_list, list) or not measures_list or not group_by:
            return {"answer": "I could not identify a valid multi-measure grouped analysis.", "rows": []}

        group_by = [g for g in group_by if g in data.columns]
        if not group_by:
            return {"answer": "No valid grouping columns found.", "rows": []}

        filtered_data = _remove_blank_groups(data, group_by)

        valid_measures = []
        all_required_measures = list(measures_list)

        if sort_by and sort_by in measures and sort_by not in all_required_measures:
            all_required_measures.append(sort_by)

        agg_map = {}
        rename_map = {}

        for m in all_required_measures:
            if isinstance(m, str) and m in measures:
                m_def = measures[m]
                agg_map[m_def["column"]] = m_def["agg"]
                rename_map[m_def["column"]] = m
                if m in measures_list:
                    valid_measures.append(m)

        if not valid_measures:
            return {"answer": "I could not identify valid measures for comparison.", "rows": []}

        grouped = (
            filtered_data
            .groupby(group_by, dropna=False)
            .agg(agg_map)
            .reset_index()
        )

        grouped = grouped.rename(columns=rename_map)

        if sort_by in grouped.columns:
            grouped = grouped.sort_values(by=sort_by, ascending=(sort_order == "asc"))
        else:
            grouped = grouped.sort_values(by=valid_measures[0], ascending=(sort_order == "asc"))

        # output_cols = group_by + valid_measures
        output_measures = valid_measures.copy()

        if sort_by in grouped.columns and sort_by not in output_measures:
            output_measures = [sort_by] + output_measures

        output_cols = group_by + output_measures
        
        grouped = grouped[output_cols].head(limit)

        rows = grouped.fillna("").to_dict(orient="records")

        if rows:
            first = rows[0]
            entity = " | ".join(str(first[g]) for g in group_by)
            return {
                "answer": f"Top result: {entity}",
                "rows": rows
            }

        return {"answer": "No matching rows found.", "rows": []}

    if task == "count":

        filters = plan.get("filters", [])

        # SIMPLE TOTAL COUNT
        if group_by:

            col = group_by[0]

            if col not in df.columns:
                return {
                    "answer": "Count: 0",
                    "rows": []
                }

            # NO MEASURE FILTERS → DISTINCT COUNT
            if not filters or not measure or measure not in measures:

                count = int(df[col].nunique())

                return {
                    "answer": f"Count: {count}",
                    "rows": []
                }

            # FINANCE AGGREGATED COUNT
            measure_def = measures[measure]
            measure_col = measure_def["column"]
            agg = measure_def["agg"]

            count_data = df.copy()
            count_data[measure_col] = pd.to_numeric(
                count_data[measure_col],
                errors="coerce"
            ).fillna(0)

            grouped = (
                count_data
                .groupby(group_by, dropna=False)[measure_col]
                .agg(agg)
                .reset_index()
            )

            grouped = grouped.rename(columns={measure_col: measure})

            # APPLY FILTERS AFTER AGGREGATION
            for f in filters:

                f_col = f.get("column")
                op = f.get("operator")
                values = f.get("values", [])

                if not values:
                    continue

                val = values[0]

                if f_col != measure_col:
                    continue

                if op == "eq":
                    grouped = grouped[grouped[measure] == val]

                elif op == "gt":
                    grouped = grouped[grouped[measure] > val]

                elif op == "lt":
                    grouped = grouped[grouped[measure] < val]

                elif op == "gte":
                    grouped = grouped[grouped[measure] >= val]

                elif op == "lte":
                    grouped = grouped[grouped[measure] <= val]

            count = int(grouped[group_by[0]].nunique())

        else:
            count = int(len(df))

        return {
            "answer": f"Count: {count}",
            "rows": []
        }

    if task == "count_extreme":
        if not isinstance(measure, str) or measure not in measures or not group_by:
            return {"answer": "I could not identify a valid extreme-count analysis.", "rows": []}

        group_by = [g for g in group_by if g in data.columns]
        if not group_by:
            return {"answer": "No valid grouping columns found.", "rows": []}

        filtered_data = _remove_blank_groups(data, group_by)

        measure_def = measures[measure]
        measure_col = measure_def["column"]
        agg = measure_def["agg"]

        grouped = (
            filtered_data
            .groupby(group_by, dropna=False)[measure_col]
            .agg(agg)
            .reset_index()
        )

        grouped = grouped.rename(columns={measure_col: measure})

        if grouped.empty:
            return {"answer": "Count: 0", "rows": []}

        if plan.get("sort_order", "desc") == "asc":
            extreme_value = grouped[measure].min()
        else:
            extreme_value = grouped[measure].max()

        count = int((grouped[measure] == extreme_value).sum())

        return {
            "answer": f"Count: {count}",
            "rows": []
        }

    if task == "raw_table":
        keep_cols = [c for c in columns if c in data.columns]
        if not keep_cols:
            keep_cols = list(data.columns[:8])

        raw = data[keep_cols].copy()

        if sort_by and sort_by in raw.columns:
            raw = raw.sort_values(by=sort_by, ascending=(sort_order == "asc"))

        raw = raw.head(limit)
        rows = raw.fillna("").astype(str).to_dict(orient="records")

        return {
            "answer": f"Found {len(rows)} matching rows.",
            "rows": rows
        }

    return {"answer": "I could not process that request.", "rows": []}