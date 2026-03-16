#!/usr/bin/env python3
"""
Refresh policy_official_ingest.json entries before committing.
Ensures each entry has published_at (ISO), reference_url, and normalized watch tags.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
INGEST_PATH = ROOT / "policy_official_ingest.json"


def _ensure_date(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    try:
        # accept YYYY-MM-DD
        date.fromisoformat(text)
        return text
    except ValueError:
        return None


def _ensure_watch_tags(item: Dict[str, Any]) -> list[str]:
    tags = item.get("watch_tags") or []
    normalized = [str(t).strip() for t in tags if str(t).strip()]
    if normalized:
        return normalized[:4]
    fallback = item.get("key_points") or []
    return [str(t).strip() for t in fallback if str(t).strip()][:4]


def _normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(entry)
    normalized["published_at"] = _ensure_date(entry.get("published_at"))
    normalized["reference_url"] = (
        str(entry.get("reference_url") or entry.get("url") or "").strip() or None
    )
    normalized["key_points"] = [str(p).strip() for p in entry.get("key_points", []) if str(p).strip()][:4]
    normalized["watch_tags"] = _ensure_watch_tags(entry)
    return normalized


def refresh():
    payload = json.loads(INGEST_PATH.read_text(encoding="utf-8"))
    directions = payload.get("directions", [])
    for direction in directions:
        entries = direction.get("official_source_entries", [])
        normalized = [_normalize_entry(entry) for entry in entries if isinstance(entry, dict)]
        normalized.sort(
            key=lambda item: item.get("published_at") or "",
            reverse=True,
        )
        direction["official_source_entries"] = normalized

    INGEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    refresh()
