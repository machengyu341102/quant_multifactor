#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-}"
if [[ -z "$BUNDLE_DIR" ]]; then
  echo "用法: $0 <release_bundle_dir>" >&2
  exit 1
fi

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "bundle 目录不存在: $BUNDLE_DIR" >&2
  exit 1
fi

: "${RELEASE_BUCKET:?缺少 RELEASE_BUCKET}"
: "${RELEASE_PUBLIC_BASE_URL:?缺少 RELEASE_PUBLIC_BASE_URL}"

RELEASE_PREFIX="${RELEASE_PREFIX:-app}"
RELEASE_REGION="${RELEASE_REGION:-auto}"
ENDPOINT_ARGS=()

if [[ -n "${RELEASE_ENDPOINT_URL:-}" ]]; then
  ENDPOINT_ARGS+=(--endpoint-url "$RELEASE_ENDPOINT_URL")
fi

aws --version >/dev/null

TARGET_URI="s3://${RELEASE_BUCKET}/${RELEASE_PREFIX}"

aws s3 cp "${BUNDLE_DIR}/alpha-ai-latest.apk" "${TARGET_URI}/alpha-ai-latest.apk" \
  "${ENDPOINT_ARGS[@]}" \
  --region "$RELEASE_REGION" \
  --content-type "application/vnd.android.package-archive" \
  --cache-control "public, max-age=300"

aws s3 cp "${BUNDLE_DIR}/alpha-ai-latest.apk.sha256" "${TARGET_URI}/alpha-ai-latest.apk.sha256" \
  "${ENDPOINT_ARGS[@]}" \
  --region "$RELEASE_REGION" \
  --content-type "text/plain; charset=utf-8" \
  --cache-control "no-store"

aws s3 cp "${BUNDLE_DIR}/releases" "${TARGET_URI}/releases" \
  "${ENDPOINT_ARGS[@]}" \
  --region "$RELEASE_REGION" \
  --recursive \
  --cache-control "public, max-age=31536000"

aws s3 cp "${BUNDLE_DIR}/releases/release.json" "${TARGET_URI}/releases/release.json" \
  "${ENDPOINT_ARGS[@]}" \
  --region "$RELEASE_REGION" \
  --content-type "application/json" \
  --cache-control "no-store"

echo "上传完成:"
echo "  ${RELEASE_PUBLIC_BASE_URL%/}/${RELEASE_PREFIX}/alpha-ai-latest.apk"
echo "  ${RELEASE_PUBLIC_BASE_URL%/}/${RELEASE_PREFIX}/alpha-ai-latest.apk.sha256"
echo "  ${RELEASE_PUBLIC_BASE_URL%/}/${RELEASE_PREFIX}/releases/release.json"
