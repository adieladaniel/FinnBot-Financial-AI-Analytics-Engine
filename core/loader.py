import pandas as pd
from pathlib import Path

def load_dataset(file_path: str):
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix==".csv":
        return pd.read_csv(path)
    if suffix==".json":
        return pd.read_json(path)
    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    
    return ValueError(f"Unsupported File Type: {suffix}")