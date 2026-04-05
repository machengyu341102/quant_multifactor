#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_DIR="$ROOT_DIR/public_release"
RELEASES_DIR="$PUBLIC_DIR/releases"
DEFAULT_APK="$ROOT_DIR/native_app/android/app/build/outputs/apk/release/app-release.apk"
APK_PATH="${1:-$DEFAULT_APK}"
PUBLIC_BASE_URL="${PUBLIC_RELEASE_BASE_URL:-}"

if [ ! -f "$APK_PATH" ]; then
  echo "APK 不存在: $APK_PATH" >&2
  exit 1
fi

python3 "$ROOT_DIR/scripts/refresh_official_ingest.py"

mkdir -p "$RELEASES_DIR"
python3 "$ROOT_DIR/scripts/create_android_release_bundle.py" \
  --apk "$APK_PATH" \
  --output-dir "$PUBLIC_DIR" \
  --app-json "$ROOT_DIR/native_app/app.json" \
  --build-gradle "$ROOT_DIR/native_app/android/app/build.gradle" \
  --public-base-url "$PUBLIC_BASE_URL"

LATEST_APK="$PUBLIC_DIR/alpha-ai-latest.apk"
VERSIONED_APK="$(python3 - <<'PY'
import json
from pathlib import Path
import os
root = Path(os.environ["ROOT_DIR"])
payload = json.loads((root / "public_release" / "releases" / "release.json").read_text())
print(root / "public_release" / "releases" / payload["apkName"])
PY
)"
SHA256="$(python3 - <<'PY'
import json
from pathlib import Path
import os
root = Path(os.environ["ROOT_DIR"])
payload = json.loads((root / "public_release" / "releases" / "release.json").read_text())
print(payload["sha256"])
PY
)"

chmod 644 "$LATEST_APK" "$VERSIONED_APK" "$PUBLIC_DIR/releases/release.json"
echo "发布完成: $VERSIONED_APK"
echo "latest: $LATEST_APK"
echo "SHA-256: $SHA256"
