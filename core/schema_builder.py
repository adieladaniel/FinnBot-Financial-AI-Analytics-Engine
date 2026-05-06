def build_schema(dataset_name, profile):
    schema = {
        "dataset_name":dataset_name,
        "columns": [],
        "dimensions": profile["dimensions"],
        "measures": profile["measures"],
        "date_columns": profile["date_columns"],
        "id_columns": profile["id_columns"]
    }

    for col in profile["columns"]:
        dtype = col["dtype"]

        if "int" in dtype or "float" in dtype:
            ctype = "number"
        else:
            ctype = "string"

        if col["name"] in profile["date_columns"]:
            ctype = "date"

        schema["columns"].append({
            "name": col["name"],
            "type": ctype
        })
    return schema