import json
import os


def load_domain_config(domain_name: str | None = None):
    base_path = "configs"

    if not domain_name:
        domain_name = "generic"

    file_path = os.path.join(base_path, f"{domain_name}.json")

    if not os.path.exists(file_path):
        file_path = os.path.join(base_path, "generic.json")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)