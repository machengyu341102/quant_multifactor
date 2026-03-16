#!/usr/bin/env python3
"\"\"\"Report which official entries need a follow-up check.\"\"\""

from pathlib import Path
from typing import Any
import json

ROOT = Path(__file__).resolve().parent.parent
INGEST_PATH = ROOT / "policy_official_ingest.json"


def _needs_update(entry: dict[str, Any]) -> bool:
    if not entry.get("published_at") or not entry.get("reference_url"):
        return True
    try:
        date_parts = entry["published_at"].split("-")
        if len(date_parts) != 3:
            return True
    except Exception:
        return True
    return False


def main() -> None:
    payload = json.loads(INGEST_PATH.read_text(encoding="utf-8"))
    for direction in payload.get("directions", []):
        dir_id = direction.get("id", "UNKNOWN")
        dir_name = direction.get("direction", dir_id)
        for entry in direction.get("official_source_entries", []):
            if _needs_update(entry):
                print(f"{dir_id} {dir_name} needs update: {entry.get('title')}")


if __name__ == "__main__":
    main()
