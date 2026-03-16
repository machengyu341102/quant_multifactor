#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "running official ingest ci cycle"
PYTHON="python3"

cd "$ROOT_DIR"

echo "1. checking for missing metadata"
$PYTHON scripts/check_official_updates.py

echo "2. refreshing ingest file"
$PYTHON scripts/refresh_official_ingest.py

echo "official ingest cycle complete"
