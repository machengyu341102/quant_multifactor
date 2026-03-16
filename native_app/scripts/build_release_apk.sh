#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK_NAME="alpha-ai-native.apk"

TARGET_DIR="${1:-$ROOT_DIR/../public_release}"
mkdir -p "$TARGET_DIR"

echo "1/3 ▶ 正在打包 Android release（gradle assembleRelease）..."
pushd "$ROOT_DIR/android" >/dev/null
./gradlew assembleRelease >/tmp/gradle-build.log
popd >/dev/null
echo "   已完成 gradle 构建，日志：/tmp/gradle-build.log"

APK_PATH="$ROOT_DIR/android/app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK_PATH" ]]; then
  echo "❌ 找不到 release APK，请确认 gradle 构建成功。"
  exit 1
fi

echo "2/3 ▶ 复制 APK 到 $TARGET_DIR/$APK_NAME"
cp "$APK_PATH" "$TARGET_DIR/$APK_NAME"

echo "3/3 ▶ 计算 MD5"
md5sum "$TARGET_DIR/$APK_NAME"

cat <<EOF
打包完成：$TARGET_DIR/$APK_NAME
如果要在内网给手机下载，可以在该目录运行：
  python3 -m http.server 8090
然后用手机访问 http://<你的IP>:8090/$APK_NAME
EOF
