def prettify_column_name(col: str):
    return col.replace("_", " ")

def build_measures(profile: dict):
    measures = {}

    for col in profile["measures"]:
        pretty = prettify_column_name(col)

        aliases_sum = [
            f"sum {col}",
            f"sum {pretty}",
            f"total {col}",
            f"total {pretty}",
            col,
            pretty
        ]

        aliases_avg = [
            f"average {col}",
            f"average {pretty}",
            f"avg {col}",
            f"avg {pretty}"
        ]

        aliases_max = [
            f"max {col}",
            f"max {pretty}",
            f"highest {col}",
            f"highest {pretty}"
        ]

        aliases_min = [
            f"min {col}",
            f"min {pretty}",
            f"lowest {col}",
            f"lowest {pretty}"
        ]

        if col == "balance_amount":
            aliases_sum += [
                "balance",
                "total balance",
                "pending fees",
                "pending fee",
                "due fees",
                "due fee",
                "unpaid fees",
                "outstanding fees"
            ]

        if col == "totalamount":
            aliases_sum += [
                "fees",
                "total fees",
                "fee amount",
                "total amount"
            ]

        if col == "paid_amount":
            aliases_sum += [
                "paid",
                "total paid",
                "amount paid",
                "fees paid",
                "collection"
            ]

        if col == "concession_amount":
            aliases_sum += [
                "concession",
                "discount",
                "total concession"
            ]

        if col == "waiver_amount":
            aliases_sum += [
                "waiver",
                "total waiver"
            ]

        if col == "total_payable_amount":
            aliases_sum += [
                "payable",
                "total payable",
                "net payable"
            ]

        measures[f"Sum {col}"] = {
            "column": col,
            "agg": "sum",
            "aliases": list(dict.fromkeys(aliases_sum))
        }

        measures[f"Average {col}"] = {
            "column": col,
            "agg": "mean",
            "aliases": list(dict.fromkeys(aliases_avg))
        }

        measures[f"Max {col}"] = {
            "column": col,
            "agg": "max",
            "aliases": list(dict.fromkeys(aliases_max))
        }

        measures[f"Min {col}"] = {
            "column": col,
            "agg": "min",
            "aliases": list(dict.fromkeys(aliases_min))
        }

    return measures