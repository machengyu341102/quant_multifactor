#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLIC_DIR="$ROOT_DIR/public_release"
RELEASES_DIR="$PUBLIC_DIR/releases"
DEFAULT_APK="$ROOT_DIR/native_app/android/app/build/outputs/apk/release/alpha-ai-v1.0.1.apk"
APK_PATH="${1:-$DEFAULT_APK}"
VERSION="${2:-1.0.1}"

if [ ! -f "$APK_PATH" ]; then
  echo "APK 不存在: $APK_PATH" >&2
  exit 1
fi

python3 "$ROOT_DIR/scripts/refresh_official_ingest.py"

mkdir -p "$RELEASES_DIR"

APK_NAME="alpha-ai-v${VERSION}.apk"
TARGET_APK="$RELEASES_DIR/$APK_NAME"
ROOT_ALIAS_APK="$PUBLIC_DIR/$APK_NAME"

cp "$APK_PATH" "$TARGET_APK"
ln -sfn "releases/$APK_NAME" "$ROOT_ALIAS_APK"
ln -sfn "releases/$APK_NAME" "$PUBLIC_DIR/alpha-ai-latest.apk"

FILE_SIZE_BYTES=$(wc -c < "$TARGET_APK" | tr -d ' ')
SHA256=$(shasum -a 256 "$TARGET_APK" | awk '{print $1}')
PUBLISHED_AT=$(date +"%Y-%m-%dT%H:%M:%S%z")

cat > "$RELEASES_DIR/release.json" <<EOF
{
  "version": "$VERSION",
  "apk_name": "$APK_NAME",
  "apk_path": "releases/$APK_NAME",
  "latest_path": "alpha-ai-latest.apk",
  "size_bytes": $FILE_SIZE_BYTES,
  "sha256": "$SHA256",
  "published_at": "$PUBLISHED_AT"
}
EOF

echo "发布完成: $TARGET_APK"
echo "SHA-256: $SHA256"
