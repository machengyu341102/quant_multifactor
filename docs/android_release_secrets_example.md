# Android Release Secrets 示例

下面这组 Secrets 是给 `.github/workflows/android-release.yml` 用的。

## Android 签名

- `ANDROID_KEYSTORE_BASE64`
  - `base64` 编码后的 keystore 文件内容
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

示例：

```text
ANDROID_KEYSTORE_BASE64=<base64 of ci-release.keystore>
ANDROID_KEYSTORE_PASSWORD=********
ANDROID_KEY_ALIAS=alpha-ai-release
ANDROID_KEY_PASSWORD=********
```

## 对象存储

### 阿里云 OSS / 腾讯云 COS / Cloudflare R2 / S3 兼容

- `RELEASE_ACCESS_KEY_ID`
- `RELEASE_SECRET_ACCESS_KEY`
- `RELEASE_BUCKET`
- `RELEASE_REGION`
- `RELEASE_PUBLIC_BASE_URL`
- `RELEASE_PREFIX`
- `RELEASE_ENDPOINT_URL`（可选）

建议：

```text
RELEASE_BUCKET=alpha-download
RELEASE_REGION=auto
RELEASE_PUBLIC_BASE_URL=https://download.example.com
RELEASE_PREFIX=app
```

如果是 Cloudflare R2 这类 S3 兼容端点，再补：

```text
RELEASE_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
```

## 最终下载地址

当 `RELEASE_PUBLIC_BASE_URL=https://download.example.com` 且 `RELEASE_PREFIX=app` 时，
发布成功后固定入口是：

- `https://download.example.com/app/alpha-ai-latest.apk`
- `https://download.example.com/app/alpha-ai-latest.apk.sha256`
- `https://download.example.com/app/releases/release.json`

## 推荐做法

- 主下载源用对象存储/CDN
- GitHub Releases 只做备份
- 不再把临时隧道链接发给最终用户
