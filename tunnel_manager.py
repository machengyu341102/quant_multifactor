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

_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_DIR, "tunnel_state.json")
_PORT = 8501  # dashboard 端口


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


def start_tunnel():
    """启动隧道并监控"""
    state = _load_state()
    old_url = state.get("url", "")

    print(f"[tunnel] 启动 cloudflared → localhost:{_PORT}")
    print(f"[tunnel] 上次URL: {old_url or '无'}")

    while True:
        try:
            proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{_PORT}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            new_url = None
            for line in proc.stdout:
                line = line.strip()
                # 解析 URL
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    new_url = m.group(0)
                    print(f"[tunnel] URL: {new_url}")

                    # 保存并通知
                    state = {
                        "url": new_url,
                        "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "pid": proc.pid,
                    }
                    _save_state(state)

                    if new_url != old_url:
                        print(f"[tunnel] URL 变了! 旧={old_url}, 新={new_url}")
                        _notify_url(new_url)
                        old_url = new_url
                    else:
                        print(f"[tunnel] URL 未变, 不通知")

                # 连接状态
                if "Registered tunnel" in line:
                    print(f"[tunnel] 隧道已连接")
                if "ERR" in line:
                    print(f"[tunnel] {line}")

            # 进程退出
            proc.wait()
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
        print(f"URL: {state.get('url', '未知')}")
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
