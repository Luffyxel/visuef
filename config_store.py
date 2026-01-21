import json
import os
from typing import Dict, Any


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "configs.json")


def load_configs() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("profiles"), dict):
        return data["profiles"]
    if isinstance(data, dict):
        return data
    return {}


def save_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    payload = {"version": 1, "profiles": configs}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
