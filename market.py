import re
import requests

WORKER = "https://portable-market.danvox123hyu.workers.dev"

SERVERS = [
    {"id": 0,  "slug": "vc",          "label": "[0] Vice City"},
    # ... (вставь полный список из main.py)
    {"id": 32, "slug": "space",       "label": "[32] Space"},
]

def get_item_name_id(raw_id):
    if isinstance(raw_id, int):
        return raw_id, ""
    s = str(raw_id)
    m = re.match(r"^(\d+)(?:\(([^)]*)\))?$", s)
    if m:
        return int(m.group(1)), m.group(2) or ""
    try:
        return int(s), ""
    except ValueError:
        return None, ""

def strip_enchant(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

def fetch_items_dict():
    r = requests.get(f"{WORKER}/api/items", timeout=10)
    r.raise_for_status()
    items = r.json()
    return {item["id"]: item["name"] for item in items}

def fetch_marketplace(server_id: int):
    r = requests.get(f"{WORKER}/api/marketplace/{server_id}", timeout=15)
    r.raise_for_status()
    return r.json()