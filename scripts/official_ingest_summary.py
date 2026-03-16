#!/usr/bin/env python3
"\"\"\"Print a table of direction official entries and their freshness status.\"\"\""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INGEST_PATH = ROOT / "policy_official_ingest.json"


def _freshness(entry: dict[str, Any]) -> str:
    date_text = entry.get("published_at") or ""
    return date_text if date_text else "missing date"


def _tagline(entry: dict[str, Any]) -> str:
    watch_tags = entry.get("watch_tags") or []
    return "/".join(str(tag) for tag in watch_tags[:3]) or "no tags"


def main() -> None:
    payload = json.loads(INGEST_PATH.read_text(encoding="utf-8"))
    print("方向 · 官方原文 · 日期 · 重要 tags · ref")
    for direction in payload.get("directions", []):
        dir_name = direction.get("direction") or direction.get("id")
        for entry in direction.get("official_source_entries", []):
            title = entry.get("title", "unnamed")
            print(
                f"{dir_name[:16]:<16} · {title[:28]:<28} · { _freshness(entry) } · {_tagline(entry):<20} · {entry.get('reference_url') or entry.get('reference') or 'no link'}"
            )


if __name__ == "__main__":
    main()
