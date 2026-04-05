# Android 稳定分发方案

这套方案的目标是把 Android 安装包分发从“本机临时隧道”切到“CI 构建 + 固定公网下载”。

## 发布链路

1. GitHub Actions 构建 `release APK`
2. 生成标准 bundle：
   - `alpha-ai-latest.apk`
   - `alpha-ai-latest.apk.sha256`
   - `releases/alpha-ai-vX.Y.Z.apk`
   - `releases/release.json`
   - `releases/alpha-ai-vX.Y.Z.apk.sha256`
3. 上传到固定公网位置：
   - 对象存储/CDN
   - 或 GitHub Releases
4. 从公网回拉校验：
   - 文件大小
   - SHA-256
   - `release.json`

## 推荐下载路径

固定给用户的入口只保留两个：

- `https://download.example.com/app/alpha-ai-latest.apk`
- `https://download.example.com/app/releases/release.json`

历史版本放在：

- `https://download.example.com/app/releases/alpha-ai-v1.0.142.apk`

## Workflow 文件

- `.github/workflows/android-release.yml`

触发方式：

- 手动 `workflow_dispatch`
- 推送 tag：`android-v*`

## 必要 Secrets

Android 签名：

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

对象存储：

- `RELEASE_ACCESS_KEY_ID`
- `RELEASE_SECRET_ACCESS_KEY`
- `RELEASE_BUCKET`
- `RELEASE_REGION`
- `RELEASE_PUBLIC_BASE_URL`

可选：

- `RELEASE_PREFIX`
  - 默认建议：`app`
- `RELEASE_ENDPOINT_URL`
  - 用于 R2 / OSS / COS 这类 S3 兼容入口

## 本地生成同款 bundle

```bash
python3 scripts/create_android_release_bundle.py \
  --apk native_app/android/app/build/outputs/apk/release/app-release.apk \
  --output-dir release_bundle \
  --app-json native_app/app.json \
  --build-gradle native_app/android/app/build.gradle \
  --public-base-url https://download.example.com/app
```

输出目录：

- `release_bundle/alpha-ai-latest.apk`
- `release_bundle/alpha-ai-latest.apk.sha256`
- `release_bundle/releases/alpha-ai-vX.Y.Z.apk`
- `release_bundle/releases/release.json`

## 本地上传到对象存储

```bash
export RELEASE_ACCESS_KEY_ID=xxx
export RELEASE_SECRET_ACCESS_KEY=xxx
export RELEASE_BUCKET=alpha-download
export RELEASE_REGION=auto
export RELEASE_PUBLIC_BASE_URL=https://download.example.com
export RELEASE_PREFIX=app

bash scripts/upload_android_release_bundle.sh release_bundle
```

## 本地校验 bundle / 公网回拉

只校验本地：

```bash
python3 scripts/verify_android_release_bundle.py \
  --bundle-dir release_bundle
```

带公网回拉校验：

```bash
python3 scripts/verify_android_release_bundle.py \
  --bundle-dir release_bundle \
  --public-base-url https://download.example.com/app
```

## release.json 字段

`release.json` 至少包含：

- `version`
- `versionCode`
- `channel`
- `size`
- `sha256`
- `publishedAt`
- `url`
- `directUrl`
- `releaseJsonUrl`
- `notes`

## 建议

- 主下载源用对象存储/CDN
- GitHub Releases 只做备份归档
- 不再用本机 HTTP + 临时隧道做正式分发
