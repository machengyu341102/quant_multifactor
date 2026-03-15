"""
系统自监控 (Watchdog)
=====================
- 心跳检测 (scheduler.py 主循环每30s调用)
- 策略运行状态跟踪
- 异常告警
- 调度器进程重启

数据文件: heartbeat.json

建议配合 launchd 外部定时检查 (见 launchd/ 目录)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("watchdog")

_DIR = os.path.dirname(os.path.abspath(__file__))
_HEARTBEAT_PATH = os.path.join(_DIR, "heartbeat.json")

# 日间策略时刻表 (策略名 -> 预期运行时间 HH:MM)
# 注意: 币圈/美股/跨市场/作战计划 是夜班子任务, 不在这里检查
_STRATEGY_SCHEDULE = {
    "期货趋势选股": "09:05",
    "事件驱动选股": "09:22",
    "集合竞价选股": "09:25",
    "可转债T+0选债": "09:35",
    "低吸回调选股": "09:50",
    "放量突破选股": "10:00",
    "趋势跟踪选股": "10:00",
    "缩量整理选股": "10:15",
    "板块轮动选股": "14:00",
    "尾盘短线选股": "14:30",
    # 板块异动监控: 轮询策略(每5分钟), 不做定时检查
    # 币圈/美股/跨市场/作战计划: 夜班子任务, 从 night_shift_log 检查
}

_HEARTBEAT_TIMEOUT = 300  # 5分钟
_ERROR_THRESHOLD = 5


# ================================================================
#  心跳 & 状态更新
# ================================================================

def update_heartbeat():
    """更新心跳 (scheduler.py 主循环每30s调用)"""
    data = safe_load(_HEARTBEAT_PATH, default={})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["last_heartbeat"] = now_str
    data["pid"] = os.getpid()
    if "start_time" not in data:
        data["start_time"] = now_str
    safe_save(_HEARTBEAT_PATH, data)


def update_strategy_status(strategy_name: str, status: str,
                           error_msg: str | None = None,
                           duration_sec: float = 0):
    """策略运行完成后更新状态 (run_with_retry 调用)"""
    data = safe_load(_HEARTBEAT_PATH, default={})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if "strategy_status" not in data:
        data["strategy_status"] = {}

    data["strategy_status"][strategy_name] = {
        "last_run": now_str,
        "status": status,
        "error_msg": error_msg,
        "duration_sec": round(duration_sec, 1),
    }
    data["last_strategy_run"] = now_str

    if status == "failed":
        data["errors_today"] = data.get("errors_today", 0) + 1
        logger.error("策略 [%s] 运行失败: %s", strategy_name, error_msg)
    else:
        logger.info("策略 [%s] 运行成功 (%.1fs)", strategy_name, duration_sec)

    safe_save(_HEARTBEAT_PATH, data)


def reset_daily_counters():
    """每日开盘前重置错误计数"""
    data = safe_load(_HEARTBEAT_PATH, default={})
    data["errors_today"] = 0
    safe_save(_HEARTBEAT_PATH, data)


# ================================================================
#  健康检查
# ================================================================

def check_health() -> dict:
    """综合健康检查

    返回: {healthy, issues[], heartbeat_age_sec, process_alive, strategies_ok, errors_today}
    """
    data = safe_load(_HEARTBEAT_PATH, default={})
    now = datetime.now()
    issues = []

    # 1. 心跳超时检查
    heartbeat_age = None
    last_hb = data.get("last_heartbeat")
    if last_hb:
        try:
            hb_time = datetime.strptime(last_hb, "%Y-%m-%d %H:%M:%S")
            heartbeat_age = (now - hb_time).total_seconds()
            if heartbeat_age > _HEARTBEAT_TIMEOUT:
                issues.append(
                    f"心跳超时: 最后心跳 {last_hb} "
                    f"(已 {heartbeat_age / 60:.0f} 分钟)"
                )
        except ValueError:
            issues.append(f"心跳时间格式异常: {last_hb}")
    else:
        issues.append("无心跳记录 (调度器可能未启动)")

    # 2. 进程存活检查
    pid = data.get("pid")
    process_alive = False
    if pid:
        try:
            os.kill(pid, 0)
            process_alive = True
        except (OSError, ProcessLookupError):
            issues.append(f"调度器进程不存在 (PID={pid})")
    else:
        issues.append("无PID记录")

    # 3. 策略运行检查 (只在交易时间段检查)
    today_str = now.strftime("%Y-%m-%d")
    strategies_ok = True
    strategy_status = data.get("strategy_status", {})

    for name, expected_time in _STRATEGY_SCHEDULE.items():
        expected_dt = datetime.strptime(f"{today_str} {expected_time}", "%Y-%m-%d %H:%M")
        buffer_minutes = 30
        buffer_dt = expected_dt.replace(minute=0, hour=0) + \
            __import__("datetime").timedelta(
                hours=expected_dt.hour,
                minutes=expected_dt.minute + buffer_minutes,
            )
        if now < buffer_dt:
            continue

        status_info = strategy_status.get(name, {})
        last_run = status_info.get("last_run", "")

        if not last_run or last_run[:10] != today_str:
            issues.append(f"策略 [{name}] 今日未运行 (预期 {expected_time})")
            strategies_ok = False
        elif status_info.get("status") == "failed":
            issues.append(
                f"策略 [{name}] 运行失败: {status_info.get('error_msg', '未知错误')}"
            )
            strategies_ok = False

    # 4. 夜班状态检查 (从 night_shift_log.json 读取)
    try:
        night_log_path = os.path.join(_DIR, "night_shift_log.json")
        night_log = safe_load(night_log_path, default={})
        night_date = night_log.get("date", "")
        # 夜班结果属于"前一天发起, 今天凌晨完成", 检查昨天或今天的日期
        yesterday_str = (now - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
        if night_date in (today_str, yesterday_str):
            tasks = night_log.get("tasks", {})
            failed_tasks = [
                name for name, info in tasks.items()
                if isinstance(info, dict) and info.get("status") in ("error", "timeout")
            ]
            if failed_tasks:
                issues.append(f"夜班失败任务: {', '.join(failed_tasks[:3])}")
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # 5. 错误计数检查
    errors_today = data.get("errors_today", 0)
    if errors_today >= _ERROR_THRESHOLD:
        issues.append(f"今日错误数过多: {errors_today} 次 (阈值 {_ERROR_THRESHOLD})")

    healthy = len(issues) == 0
    return {
        "healthy": healthy,
        "issues": issues,
        "heartbeat_age_sec": heartbeat_age,
        "process_alive": process_alive,
        "strategies_ok": strategies_ok,
        "errors_today": errors_today,
    }


# ================================================================
#  告警
# ================================================================

_ALERT_LOCK_PATH = os.path.join(_DIR, ".watchdog_alert_lock")
_ALERT_COOLDOWN = 3600  # 同一问题1小时内只报一次


def alert_if_unhealthy():
    """不健康时推送告警 (1小时冷却, 不重复刷屏)"""
    result = check_health()
    if result["healthy"]:
        logger.info("系统健康")
        # 健康时清除锁
        if os.path.exists(_ALERT_LOCK_PATH):
            os.remove(_ALERT_LOCK_PATH)
        return

    # 冷却检查: 1小时内不重复告警
    if os.path.exists(_ALERT_LOCK_PATH):
        try:
            lock_age = time.time() - os.path.getmtime(_ALERT_LOCK_PATH)
            if lock_age < _ALERT_COOLDOWN:
                logger.info("告警冷却中 (%.0f秒前已报), 跳过", lock_age)
                return
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    issues_text = "\n".join(f"- {i}" for i in result["issues"])
    alert_msg = (
        f"系统告警\n\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"异常项:\n{issues_text}\n\n"
        f"进程状态: {'存活' if result['process_alive'] else '不存在'}\n"
        f"今日错误: {result['errors_today']} 次"
    )

    logger.error("系统异常! %s", "; ".join(result["issues"]))

    try:
        from notifier import notify_alert, LEVEL_CRITICAL
        notify_alert(LEVEL_CRITICAL, "系统异常告警", alert_msg)
        # 写锁文件
        with open(_ALERT_LOCK_PATH, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        logger.error("告警推送失败: %s", e)


# ================================================================
#  重启调度器
# ================================================================

def restart_scheduler():
    """重启调度器: SIGTERM -> 等5s -> SIGKILL -> 启动新进程"""
    data = safe_load(_HEARTBEAT_PATH, default={})
    pid = data.get("pid")

    if pid:
        logger.info("终止调度器进程 PID=%d...", pid)
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(5)
            try:
                os.kill(pid, 0)
                logger.warning("SIGTERM 未生效, 发送 SIGKILL...")
                os.kill(pid, signal.SIGKILL)
                time.sleep(1)
            except (OSError, ProcessLookupError):
                logger.info("进程已终止")
        except (OSError, ProcessLookupError):
            logger.info("进程 %d 已不存在", pid)

    scheduler_path = os.path.join(_DIR, "scheduler.py")
    logger.info("启动新调度器进程...")
    proc = subprocess.Popen(
        [sys.executable, scheduler_path, "daemon"],
        cwd=_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info("新调度器已启动, PID=%d", proc.pid)

    try:
        from notifier import notify_wechat_raw
        notify_wechat_raw(
            "调度器重启",
            f"旧PID: {pid or '无'}\n新PID: {proc.pid}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)


# ================================================================
#  CLI
# ================================================================

def _cli_status():
    data = safe_load(_HEARTBEAT_PATH, default={})
    if not data:
        print("无心跳记录 (调度器可能未启动)")
        return

    print("=" * 50)
    print("  系统状态")
    print("=" * 50)
    print(f"  最后心跳: {data.get('last_heartbeat', '无')}")
    print(f"  最后策略: {data.get('last_strategy_run', '无')}")
    print(f"  PID: {data.get('pid', '无')}")
    print(f"  启动时间: {data.get('start_time', '无')}")
    print(f"  今日错误: {data.get('errors_today', 0)}")

    pid = data.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            print(f"  进程状态: 存活")
        except (OSError, ProcessLookupError):
            print(f"  进程状态: 不存在")

    strategy_status = data.get("strategy_status", {})
    if strategy_status:
        print(f"\n  策略运行状态:")
        for name, info in strategy_status.items():
            status = info.get("status", "未知")
            last_run = info.get("last_run", "无")
            duration = info.get("duration_sec", 0)
            error = info.get("error_msg")
            status_tag = "OK" if status == "success" else "FAIL"
            line = f"    [{status_tag}] {name}: {last_run} ({duration:.0f}s)"
            if error:
                line += f" | {error}"
            print(line)


def guard():
    """外部看门狗: 检查 scheduler 是否存活, 挂了自动重启 + 告警

    设计给 launchd / cron 每 5 分钟调用:
      python3 watchdog.py guard

    判断逻辑:
      1. heartbeat.json 有 PID → 检查进程是否存活
      2. 进程不在 → 自动重启 + 微信告警
      3. 心跳超时 (>10分钟) → 进程可能卡死 → kill + 重启 + 告警
      4. 无 heartbeat.json → 首次启动, 直接拉起
    """
    data = safe_load(_HEARTBEAT_PATH, default={})
    pid = data.get("pid")
    now = datetime.now()

    # —— 检查进程是否存活 ——
    process_alive = False
    if pid:
        try:
            os.kill(pid, 0)
            process_alive = True
        except (OSError, ProcessLookupError):
            pass

    if process_alive:
        # 进程在, 但心跳可能卡死
        last_hb = data.get("last_heartbeat", "")
        if last_hb:
            try:
                hb_time = datetime.strptime(last_hb, "%Y-%m-%d %H:%M:%S")
                age = (now - hb_time).total_seconds()
                if age > 600:  # 10 分钟无心跳, 进程可能卡死
                    reason = f"进程存活但心跳超时 {age/60:.0f} 分钟, 疑似卡死"
                    logger.error("[guard] %s, 强制重启", reason)
                    _guard_restart(reason, old_pid=pid)
                else:
                    logger.debug("[guard] 调度器正常 (PID=%d, 心跳 %ds 前)", pid, age)
            except ValueError:
                logger.warning("[guard] 心跳时间格式异常: %s", last_hb)
        else:
            # 有进程无心跳, 可能刚启动, 不管
            logger.debug("[guard] 进程在 (PID=%d), 无心跳记录, 跳过", pid)
    else:
        # —— 进程不存活, 需要重启 ——
        if pid:
            reason = f"调度器进程已死 (PID={pid})"
        else:
            reason = "无 PID 记录, 首次启动调度器"
        logger.warning("[guard] %s, 自动重启", reason)
        _guard_restart(reason, old_pid=pid)

    # —— Tunnel 检活 (无论 scheduler 状态如何) ——
    try:
        _guard_tunnel()
    except Exception as e:
        logger.error("[guard-tunnel] 检查异常: %s", e)


def _guard_tunnel():
    """检查 Cloudflare Tunnel 是否存活, 挂了自动重启 tunnel_manager"""
    import requests

    state_path = os.path.join(_DIR, "tunnel_state.json")
    state = safe_load(state_path, default={})
    url = state.get("url", "")
    tunnel_pid = state.get("pid")

    if not url:
        logger.debug("[guard-tunnel] 无 tunnel URL, 跳过")
        return

    # 1. 检查 tunnel URL 是否可达
    alive = False
    try:
        resp = requests.get(url + "/", timeout=8)
        alive = resp.status_code < 500
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    if alive:
        logger.debug("[guard-tunnel] tunnel 正常: %s", url)
        return

    # 2. Tunnel 挂了, 检查 cloudflared 进程
    logger.warning("[guard-tunnel] tunnel 不可达: %s, 准备重启", url)

    # 杀旧 tunnel_manager + cloudflared
    if tunnel_pid:
        try:
            os.kill(tunnel_pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    # 杀所有 tunnel_manager 和 cloudflared
    try:
        subprocess.run(["pkill", "-f", "tunnel_manager.py"], timeout=5,
                       capture_output=True)
        subprocess.run(["pkill", "-f", "cloudflared tunnel"], timeout=5,
                       capture_output=True)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    time.sleep(2)

    # 3. 重启 tunnel_manager
    try:
        tm_path = os.path.join(_DIR, "tunnel_manager.py")
        proc = subprocess.Popen(
            [sys.executable, tm_path],
            cwd=_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("[guard-tunnel] tunnel_manager 已重启, PID=%d", proc.pid)
    except Exception as e:
        logger.error("[guard-tunnel] 重启失败: %s", e)
        return

    # 4. 等待新 URL 生成 (最多 20 秒)
    new_url = ""
    for _ in range(4):
        time.sleep(5)
        new_state = safe_load(state_path, default={})
        new_url = new_state.get("url", "")
        if new_url and new_url != url:
            break

    # 5. 微信告警
    msg = (f"旧URL: {url}\n"
           f"新URL: {new_url or '等待中...'}\n"
           f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
           f"{'请到企业微信后台更新回调URL' if new_url != url else ''}")
    try:
        from notifier import notify_wechat_raw
        notify_wechat_raw("隧道自动重启", msg)
    except Exception as e:
        logger.error("[guard-tunnel] 告警推送失败: %s", e)


def _guard_restart(reason: str, old_pid: int | None = None):
    """Guard 触发的重启: 拉起新 scheduler + 微信告警"""
    # 确保旧进程死透
    if old_pid:
        try:
            os.kill(old_pid, signal.SIGKILL)
            time.sleep(1)
        except (OSError, ProcessLookupError):
            pass

    # 启动新 scheduler
    scheduler_path = os.path.join(_DIR, "scheduler.py")
    try:
        proc = subprocess.Popen(
            [sys.executable, scheduler_path, "daemon"],
            cwd=_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        new_pid = proc.pid
        logger.info("[guard] 新调度器已启动, PID=%d", new_pid)
    except Exception as e:
        logger.error("[guard] 启动调度器失败: %s", e)
        new_pid = None

    # 微信告警
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (f"原因: {reason}\n"
           f"旧PID: {old_pid or '无'}\n"
           f"新PID: {new_pid or '启动失败'}\n"
           f"时间: {now_str}")
    try:
        from notifier import notify_wechat_raw
        notify_wechat_raw("调度器自动重启", msg)
    except Exception as e:
        logger.error("[guard] 告警推送失败: %s", e)

    print(f"[guard] {now_str} | {reason} → 新PID={new_pid or '失败'}")


def install_launchd():
    """安装 macOS launchd plist, 每 5 分钟自动执行 watchdog guard

    plist 位置: ~/Library/LaunchAgents/com.quant.watchdog.plist
    """
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    plist_name = "com.quant.watchdog.plist"
    plist_path = os.path.join(plist_dir, plist_name)

    python_path = sys.executable
    watchdog_path = os.path.abspath(__file__)
    log_stdout = os.path.join(_DIR, "logs", "watchdog_launchd.log")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_name.replace('.plist', '')}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{watchdog_path}</string>
        <string>guard</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>WorkingDirectory</key>
    <string>{_DIR}</string>
    <key>StandardOutPath</key>
    <string>{log_stdout}</string>
    <key>StandardErrorPath</key>
    <string>{log_stdout}</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    os.makedirs(plist_dir, exist_ok=True)

    # 先卸载旧的
    try:
        subprocess.run(["launchctl", "unload", plist_path],
                        capture_output=True, timeout=10)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    with open(plist_path, "w") as f:
        f.write(plist_content)
    print(f"plist 已写入: {plist_path}")

    # 加载
    result = subprocess.run(["launchctl", "load", plist_path],
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        print(f"launchd 已加载, 每 5 分钟自动执行 guard")
        print(f"日志: {log_stdout}")
        print(f"\n卸载命令: launchctl unload {plist_path}")
    else:
        print(f"加载失败: {result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "check":
        alert_if_unhealthy()
    elif mode == "status":
        _cli_status()
    elif mode == "restart":
        restart_scheduler()
    elif mode == "guard":
        guard()
    elif mode == "install":
        install_launchd()
    else:
        print("用法:")
        print("  python3 watchdog.py check    # 健康检查 (异常则推送告警)")
        print("  python3 watchdog.py status   # 查看心跳状态")
        print("  python3 watchdog.py restart  # 重启调度器")
        print("  python3 watchdog.py guard    # 外部看门狗 (检测+自动重启)")
        print("  python3 watchdog.py install  # 安装 launchd 定时任务 (每5分钟guard)")
        sys.exit(1)
