#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_app_version(app_json_path: Path) -> str:
    payload = json.loads(_read_text(app_json_path))
    expo = payload.get("expo", {})
    version = str(expo.get("version", "")).strip()
    if not version:
        raise ValueError(f"app.json 缺少 expo.version: {app_json_path}")
    return version


def _parse_android_version_code(build_gradle_path: Path) -> int:
    text = _read_text(build_gradle_path)
    match = re.search(r"versionCode\s+(\d+)", text)
    if not match:
        raise ValueError(f"build.gradle 缺少 versionCode: {build_gradle_path}")
    return int(match.group(1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_base_url(base_url: str) -> str:
    value = base_url.strip()
    return value.rstrip("/") if value else ""


def _load_notes(args: argparse.Namespace) -> list[str]:
    notes: list[str] = []
    for note in args.note:
        text = note.strip()
        if text:
            notes.append(text)
    if args.notes_file:
        raw = _read_text(Path(args.notes_file))
        for line in raw.splitlines():
            text = line.strip().lstrip("-").strip()
            if text:
                notes.append(text)
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Android 发布 bundle 与 release.json")
    parser.add_argument("--apk", required=True, help="输入 APK 路径")
    parser.add_argument("--output-dir", required=True, help="输出 bundle 目录")
    parser.add_argument("--app-json", default="native_app/app.json", help="app.json 路径")
    parser.add_argument("--build-gradle", default="native_app/android/app/build.gradle", help="Android build.gradle 路径")
    parser.add_argument("--public-base-url", default="", help="公开下载根路径，例如 https://download.example.com/app")
    parser.add_argument("--channel", default="stable", help="发布通道")
    parser.add_argument("--note", action="append", default=[], help="单条发布说明，可重复传入")
    parser.add_argument("--notes-file", default="", help="发布说明文件，每行一条")
    args = parser.parse_args()

    apk_path = Path(args.apk).expanduser().resolve()
    if not apk_path.is_file():
        raise FileNotFoundError(f"APK 不存在: {apk_path}")

    app_json_path = Path(args.app_json).expanduser().resolve()
    build_gradle_path = Path(args.build_gradle).expanduser().resolve()

    version = _parse_app_version(app_json_path)
    version_code = _parse_android_version_code(build_gradle_path)
    output_dir = Path(args.output_dir).expanduser().resolve()
    releases_dir = output_dir / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    apk_name = f"alpha-ai-v{version}.apk"
    latest_name = "alpha-ai-latest.apk"
    target_apk = releases_dir / apk_name
    latest_apk = output_dir / latest_name

    shutil.copy2(apk_path, target_apk)
    shutil.copy2(apk_path, latest_apk)

    size_bytes = target_apk.stat().st_size
    sha256 = _sha256(target_apk)
    published_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    public_base_url = _normalize_base_url(args.public_base_url)

    latest_path = latest_name
    direct_path = f"releases/{apk_name}"
    release_json_path = "releases/release.json"

    url = f"{public_base_url}/{latest_path}" if public_base_url else latest_path
    direct_url = f"{public_base_url}/{direct_path}" if public_base_url else direct_path
    release_json_url = f"{public_base_url}/{release_json_path}" if public_base_url else release_json_path

    manifest = {
        "version": version,
        "versionCode": version_code,
        "channel": args.channel,
        "apkName": apk_name,
        "latestName": latest_name,
        "size": size_bytes,
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "publishedAt": published_at,
        "url": url,
        "directUrl": direct_url,
        "releaseJsonUrl": release_json_url,
        "notes": _load_notes(args),
    }

    (releases_dir / "release.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (releases_dir / f"{apk_name}.sha256").write_text(f"{sha256}  {apk_name}\n", encoding="utf-8")
    (output_dir / f"{latest_name}.sha256").write_text(f"{sha256}  {latest_name}\n", encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
