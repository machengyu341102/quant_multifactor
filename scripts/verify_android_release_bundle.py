#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "AlphaAI-ReleaseVerify/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    path.write_bytes(data)


def _verify_local(bundle_dir: Path) -> dict:
    release_json_path = bundle_dir / "releases" / "release.json"
    latest_apk = bundle_dir / "alpha-ai-latest.apk"
    if not release_json_path.is_file():
        raise FileNotFoundError(f"缺少 release.json: {release_json_path}")
    if not latest_apk.is_file():
        raise FileNotFoundError(f"缺少 latest apk: {latest_apk}")
    payload = json.loads(release_json_path.read_text(encoding="utf-8"))
    sha256 = _sha256(latest_apk)
    if sha256 != payload.get("sha256"):
        raise ValueError(f"本地 latest.apk SHA-256 不匹配: {sha256} != {payload.get('sha256')}")
    if latest_apk.stat().st_size != int(payload.get("size", -1)):
        raise ValueError("本地 latest.apk 大小与 release.json 不一致")
    return payload


def _verify_remote(base_url: str, expected_sha256: str, expected_size: int) -> dict:
    latest_url = f"{base_url.rstrip('/')}/alpha-ai-latest.apk"
    release_json_url = f"{base_url.rstrip('/')}/releases/release.json"
    tmp_apk = Path("/tmp/alpha_ai_latest_verify.apk")
    tmp_json = Path("/tmp/alpha_ai_release_verify.json")
    _download(latest_url, tmp_apk)
    _download(release_json_url, tmp_json)
    remote_payload = json.loads(tmp_json.read_text(encoding="utf-8"))
    remote_sha256 = _sha256(tmp_apk)
    remote_size = tmp_apk.stat().st_size
    if remote_sha256 != expected_sha256:
        raise ValueError(f"公网 latest.apk SHA-256 不匹配: {remote_sha256} != {expected_sha256}")
    if remote_size != expected_size:
        raise ValueError(f"公网 latest.apk 大小不匹配: {remote_size} != {expected_size}")
    if remote_payload.get("sha256") != expected_sha256:
        raise ValueError("公网 release.json 里的 sha256 不匹配")
    return {
        "url": latest_url,
        "releaseJsonUrl": release_json_url,
        "sha256": remote_sha256,
        "size": remote_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Android 发布 bundle（本地与公网）")
    parser.add_argument("--bundle-dir", required=True, help="本地 release bundle 目录")
    parser.add_argument("--public-base-url", default="", help="公网下载根路径，例如 https://download.example.com/app")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).expanduser().resolve()
    payload = _verify_local(bundle_dir)
    result = {
        "local": {
            "bundleDir": str(bundle_dir),
            "version": payload.get("version"),
            "versionCode": payload.get("versionCode"),
            "sha256": payload.get("sha256"),
            "size": payload.get("size"),
        }
    }

    public_base_url = args.public_base_url.strip()
    if public_base_url:
        result["remote"] = _verify_remote(
            public_base_url,
            expected_sha256=str(payload.get("sha256") or ""),
            expected_size=int(payload.get("size", 0)),
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"校验失败: {exc}", file=sys.stderr)
        raise
