"""
Cloudflared 隧道管理器
======================
功能:
  1. 启动 cloudflared quick tunnel
  2. 自动解析新 URL
  3. URL 变化时推送微信通知
  4. 自动重启 (进程挂了5秒后重新拉起)

用法:
  python3 tunnel_manager.py          # 启动隧道
  python3 tunnel_manager.py status   # 查看当前URL
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_DIR, "tunnel_state.json")
_PORT = int(os.environ.get("TUNNEL_TARGET_PORT", "8501"))
_PROTOCOL = os.environ.get("TUNNEL_PROTOCOL", "http2")
_INVALID_PUBLIC_HOSTS = {"api.trycloudflare.com"}


def _load_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _notify_url(url: str):
    """推送新 URL 到微信"""
    try:
        sys.path.insert(0, _DIR)
        from notifier import notify_alert, LEVEL_INFO
        notify_alert(
            LEVEL_INFO,
            "隧道URL已更新",
            f"新回调地址:\n{url}/wecom_callback\n\n"
            f"请到企业微信后台更新「接收消息」的URL\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        print(f"[tunnel] 通知失败: {e}")


def _is_valid_quick_tunnel_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme != "https" or not host.endswith(".trycloudflare.com"):
        return False
    if host in _INVALID_PUBLIC_HOSTS:
        return False
    return True


def _extract_quick_tunnel_url(line: str) -> str | None:
    matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
    for match in matches:
        if _is_valid_quick_tunnel_url(match):
            return match
    return None


def _cloudflared_command() -> list[str]:
    return [
        "cloudflared",
        "tunnel",
        "--protocol",
        _PROTOCOL,
        "--url",
        f"http://127.0.0.1:{_PORT}",
    ]


def start_tunnel():
    """启动隧道并监控"""
    state = _load_state()
    old_url = state.get("url", "")
    manager_pid = os.getpid()

    print(f"[tunnel] 启动 cloudflared → localhost:{_PORT}")
    print(f"[tunnel] 上次URL: {old_url or '无'}")

    _save_state(
        {
            "url": "",
            "previous_url": old_url,
            "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pid": None,
            "manager_pid": manager_pid,
            "protocol": _PROTOCOL,
            "target": f"http://127.0.0.1:{_PORT}",
            "status": "connecting",
        }
    )

    proc = None
    while True:
        try:
            proc = subprocess.Popen(
                _cloudflared_command(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            new_url = None
            pending_url = None
            for line in proc.stdout:
                line = line.strip()
                candidate = _extract_quick_tunnel_url(line)
                if candidate:
                    pending_url = candidate
                    print(f"[tunnel] 候选URL: {pending_url}")
                    _save_state(
                        {
                            "url": "",
                            "previous_url": old_url,
                            "candidate_url": pending_url,
                            "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pid": proc.pid,
                            "manager_pid": manager_pid,
                            "protocol": _PROTOCOL,
                            "target": f"http://127.0.0.1:{_PORT}",
                            "status": "connecting",
                        }
                    )

                # 连接状态
                if "Registered tunnel" in line:
                    print(f"[tunnel] 隧道已连接")
                    if pending_url:
                        new_url = pending_url
                        print(f"[tunnel] URL: {new_url}")
                        state = {
                            "url": new_url,
                            "previous_url": old_url,
                            "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "pid": proc.pid,
                            "manager_pid": manager_pid,
                            "protocol": _PROTOCOL,
                            "target": f"http://127.0.0.1:{_PORT}",
                            "status": "connected",
                        }
                        _save_state(state)

                        if new_url != old_url:
                            print(f"[tunnel] URL 变了! 旧={old_url}, 新={new_url}")
                            _notify_url(new_url)
                            old_url = new_url
                        else:
                            print(f"[tunnel] URL 未变, 不通知")
                if "ERR" in line:
                    print(f"[tunnel] {line}")

            # 进程退出
            proc.wait()
            _save_state(
                {
                    "url": "",
                    "previous_url": old_url,
                    "candidate_url": pending_url,
                    "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "pid": None,
                    "manager_pid": manager_pid,
                    "protocol": _PROTOCOL,
                    "target": f"http://127.0.0.1:{_PORT}",
                    "status": "retrying",
                    "last_exit_code": proc.returncode,
                }
            )
            print(f"[tunnel] cloudflared 退出 (code={proc.returncode}), 5秒后重启...")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\n[tunnel] 手动停止")
            if proc:
                proc.terminate()
            break
        except Exception as e:
            print(f"[tunnel] 异常: {e}, 5秒后重试...")
            time.sleep(5)


def show_status():
    state = _load_state()
    if state:
        print(f"状态: {state.get('status', '未知')}")
        print(f"URL: {state.get('url', '未知')}")
        if state.get("candidate_url"):
            print(f"候选URL: {state.get('candidate_url')}")
        if state.get("previous_url"):
            print(f"上次URL: {state.get('previous_url')}")
        print(f"启动: {state.get('started', '未知')}")
        print(f"PID: {state.get('pid', '未知')}")
        print(f"回调: {state.get('url', '')}/wecom_callback")
    else:
        print("隧道未启动")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "status":
        show_status()
    else:
        start_tunnel()
