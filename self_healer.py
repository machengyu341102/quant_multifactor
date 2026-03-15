"""
系统自愈
========
- 错误模式识别 + 自动修复
- 每日冒烟测试 (开盘前)
- 旧日志清理
- 系统健康报告

数据文件:
  error_patterns.json — 错误模式库 (自动更新计数)
  heal_history.json   — 修复审计日志

用法:
  python3 self_healer.py smoke       # 运行冒烟测试
  python3 self_healer.py heal        # 扫描错误 + 自动修复
  python3 self_healer.py report      # 查看健康报告
  python3 self_healer.py clean       # 清理旧日志
"""

from __future__ import annotations

import glob
import importlib
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("healer")

_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_DIR, "logs")
_ERROR_PATTERNS_PATH = os.path.join(_DIR, "error_patterns.json")
_HEAL_HISTORY_PATH = os.path.join(_DIR, "heal_history.json")

# ================================================================
#  预定义错误模式
# ================================================================

DEFAULT_ERROR_PATTERNS = [
    {
        "pattern": "JSONDecodeError",
        "action": "repair_json",
        "description": "JSON文件损坏",
        "count": 0,
        "last_seen": "",
    },
    {
        "pattern": "TimeoutError|ReadTimeout",
        "action": "clear_cache",
        "description": "API超时",
        "count": 0,
        "last_seen": "",
    },
    {
        "pattern": "ConnectionError|MaxRetryError|ConnectionRefusedError",
        "action": "log_connection",
        "description": "连接拒绝",
        "count": 0,
        "last_seen": "",
    },
    {
        "pattern": "No space left|OSError.*No space",
        "action": "clean_logs",
        "description": "磁盘空间不足",
        "count": 0,
        "last_seen": "",
    },
    {
        "pattern": "HTTP 403|HTTP 429|rate limit|Forbidden|banned|blocked|断路器已熔断",
        "action": "log_rate_limit",
        "description": "API限流/封禁",
        "count": 0,
        "last_seen": "",
    },
]


def _load_error_patterns() -> list[dict]:
    """加载错误模式库, 不存在则初始化默认模式"""
    patterns = safe_load(_ERROR_PATTERNS_PATH)
    if not patterns:
        patterns = DEFAULT_ERROR_PATTERNS
        safe_save(_ERROR_PATTERNS_PATH, patterns)
    return patterns


# ================================================================
#  日志扫描
# ================================================================

def scan_recent_errors(hours: int = 24) -> list[dict]:
    """扫描 logs/ 目录, 提取最近 N 小时的 ERROR 级别日志

    解析: 时间, 模块, 错误信息
    """
    if not os.path.isdir(_LOG_DIR):
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    errors = []

    log_files = glob.glob(os.path.join(_LOG_DIR, "*.log"))
    # 日志格式: [2026-03-01 10:30:00] module ERROR: message
    pattern = re.compile(
        r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+(\S+)\s+ERROR:\s+(.*)"
    )

    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = pattern.match(line.strip())
                    if not m:
                        continue
                    timestamp_str, module, message = m.groups()
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    if timestamp >= cutoff:
                        errors.append({
                            "timestamp": timestamp_str,
                            "module": module,
                            "message": message.strip(),
                            "file": os.path.basename(log_file),
                        })
        except Exception as e:
            logger.warning("扫描日志文件 %s 异常: %s", log_file, e)

    logger.info("扫描到 %d 条近 %d 小时 ERROR 日志", len(errors), hours)
    return errors


# ================================================================
#  错误模式匹配
# ================================================================

def match_error_pattern(error_msg: str) -> dict | None:
    """匹配已知错误模式, 返回推荐修复动作"""
    patterns = _load_error_patterns()
    for p in patterns:
        if re.search(p["pattern"], error_msg, re.IGNORECASE):
            # 更新计数
            p["count"] = p.get("count", 0) + 1
            p["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            safe_save(_ERROR_PATTERNS_PATH, patterns)
            return p
    return None


# ================================================================
#  修复动作
# ================================================================

def repair_json(filepath: str) -> bool:
    """修复损坏的 JSON 文件:
    1. 尝试读取 .bak 文件 (json_store 的备份)
    2. .bak 不存在则初始化为 [] 或 {}
    3. 记录修复日志
    """
    import json

    bak_path = filepath + ".bak"

    # 尝试从 .bak 恢复
    if os.path.exists(bak_path):
        try:
            with open(bak_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            safe_save(filepath, data)
            logger.info("从 .bak 恢复 JSON: %s", filepath)
            return True
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # .bak 也坏了或不存在, 初始化为空
    # 根据文件名推断默认结构
    basename = os.path.basename(filepath)
    if basename in ("tunable_params.json", "heartbeat.json"):
        default = {}
    else:
        default = []

    safe_save(filepath, default)
    logger.info("初始化空 JSON: %s → %s", filepath, type(default).__name__)
    return True


def clean_old_logs(days: int = 30):
    """清理超过 N 天的日志文件, 释放磁盘空间"""
    if not os.path.isdir(_LOG_DIR):
        return

    cutoff = datetime.now() - timedelta(days=days)
    cleaned = 0
    freed_bytes = 0

    for f in os.listdir(_LOG_DIR):
        filepath = os.path.join(_LOG_DIR, f)
        if not os.path.isfile(filepath):
            continue
        # 只清理 .log 和 .log.N 文件
        if not (f.endswith(".log") or re.match(r".*\.log\.\d+$", f)):
            continue

        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
        if mtime < cutoff:
            size = os.path.getsize(filepath)
            try:
                os.remove(filepath)
                cleaned += 1
                freed_bytes += size
            except OSError as e:
                logger.warning("删除日志文件失败 %s: %s", f, e)

    freed_mb = freed_bytes / (1024 * 1024)
    logger.info("清理旧日志: %d 个文件, 释放 %.1f MB", cleaned, freed_mb)


def _extract_json_path_from_error(error_msg: str) -> str | None:
    """尝试从错误信息中提取 JSON 文件路径"""
    # 匹配常见文件名
    json_files = [
        "positions.json", "scorecard.json", "blacklist.json",
        "heartbeat.json", "tunable_params.json", "evolution_history.json",
        "error_patterns.json", "heal_history.json",
    ]
    for jf in json_files:
        if jf in error_msg:
            return os.path.join(_DIR, jf)
    return None


# ================================================================
#  冒烟测试
# ================================================================

def run_smoke_test() -> dict:
    """每日冒烟测试 (09:10, 开盘前)

    检查项:
      1. 所有 JSON 文件可读
      2. akshare 可用
      3. 模块可导入
      4. 磁盘空间充足 (> 100MB)
      5. 日志文件不过大 (单文件 < 50MB)

    返回: {passed: bool, results: [{name, passed, error}]}
    """
    results = []

    # 1. JSON 文件可读
    json_files = [
        "positions.json", "scorecard.json", "heartbeat.json",
    ]
    for jf in json_files:
        path = os.path.join(_DIR, jf)
        try:
            if os.path.exists(path):
                safe_load(path)
            results.append({"name": f"JSON可读: {jf}", "passed": True, "error": None})
        except Exception as e:
            results.append({"name": f"JSON可读: {jf}", "passed": False, "error": str(e)})

    # 2. akshare 可用 (用缓存池检测, 避免裸调被限流误报)
    try:
        from api_guard import cached_pool
        pool = cached_pool()
        if pool and len(pool) > 100:
            results.append({"name": "akshare可用", "passed": True, "error": None})
        else:
            results.append({"name": "akshare可用", "passed": False, "error": f"返回{len(pool) if pool else 0}只"})
    except Exception as e:
        results.append({"name": "akshare可用", "passed": False, "error": str(e)})

    # 2b. Binance API 可用 (币圈策略)
    try:
        import requests as _req
        r = _req.get("https://api.binance.com/api/v3/ping", timeout=10)
        if r.status_code == 200:
            results.append({"name": "Binance可用", "passed": True, "error": None})
        else:
            results.append({"name": "Binance可用", "passed": False, "error": f"HTTP {r.status_code}"})
    except Exception as e:
        results.append({"name": "Binance可用", "passed": False, "error": str(e)})

    # 2c. Yahoo Finance 可用 (美股策略)
    try:
        import yfinance as _yf
        t = _yf.Ticker("SPY")
        hist = t.history(period="1d")
        if hist is not None and not hist.empty:
            results.append({"name": "YFinance可用", "passed": True, "error": None})
        else:
            results.append({"name": "YFinance可用", "passed": False, "error": "返回空数据"})
    except Exception as e:
        results.append({"name": "YFinance可用", "passed": False, "error": str(e)})

    # 3. 模块可导入
    modules = ["scorecard", "risk_manager", "watchdog", "position_manager",
               "crypto_strategy", "us_stock_strategy", "cross_market_strategy", "morning_prep",
               "walk_forward", "var_risk", "ml_factor_model",
               "paper_trader", "broker_executor", "signal_tracker"]
    for mod_name in modules:
        try:
            importlib.import_module(mod_name)
            results.append({"name": f"模块导入: {mod_name}", "passed": True, "error": None})
        except Exception as e:
            results.append({"name": f"模块导入: {mod_name}", "passed": False, "error": str(e)})

    # 4. 磁盘空间
    try:
        usage = shutil.disk_usage(_DIR)
        free_mb = usage.free / (1024 * 1024)
        if free_mb > 100:
            results.append({"name": "磁盘空间", "passed": True, "error": None})
        else:
            results.append({"name": "磁盘空间", "passed": False,
                            "error": f"剩余 {free_mb:.0f}MB < 100MB"})
    except Exception as e:
        results.append({"name": "磁盘空间", "passed": False, "error": str(e)})

    # 5. 日志文件大小
    if os.path.isdir(_LOG_DIR):
        large_logs = []
        for f in os.listdir(_LOG_DIR):
            filepath = os.path.join(_LOG_DIR, f)
            if os.path.isfile(filepath):
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                if size_mb > 50:
                    large_logs.append(f"{f} ({size_mb:.0f}MB)")
        if large_logs:
            results.append({"name": "日志大小", "passed": False,
                            "error": f"过大: {', '.join(large_logs)}"})
        else:
            results.append({"name": "日志大小", "passed": True, "error": None})

    passed = all(r["passed"] for r in results)
    total = len(results)
    pass_count = sum(1 for r in results if r["passed"])

    tag = "PASSED" if passed else "FAILED"
    logger.info("冒烟测试: %s (%d/%d)", tag, pass_count, total)
    for r in results:
        if not r["passed"]:
            logger.warning("  FAIL: %s — %s", r["name"], r["error"])

    # 发射健康事件到事件总线
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        if not passed:
            failed_names = [r["name"] for r in results if not r["passed"]]
            bus.emit(
                source="self_healer",
                priority=Priority.URGENT,
                event_type="smoke_test_failed",
                category="risk",
                payload={
                    "passed": False,
                    "failed": failed_names,
                    "message": f"冒烟测试失败: {', '.join(failed_names)}",
                },
            )
    except Exception as _exc:
        logger.warning("Suppressed exception: %s", _exc)

    # 更新注册表健康度
    try:
        from agent_registry import get_registry
        registry = get_registry()
        health = pass_count / total if total > 0 else 1.0
        registry.report_run("healer", success=passed,
                            error_msg=None if passed else f"{total - pass_count} checks failed")
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return {"passed": passed, "results": results}


# ================================================================
#  自动修复流程
# ================================================================

def auto_heal():
    """自动修复流程

    1. scan_recent_errors()
    2. 对每条错误 match_error_pattern()
    3. 匹配成功 → 执行修复动作
    4. 记录到 heal_history.json
    5. 无法自动修复的 → 推送告警
    """
    logger.info("=" * 50)
    logger.info("自动修复开始")
    logger.info("=" * 50)

    errors = scan_recent_errors(hours=24)
    if not errors:
        logger.info("最近 24 小时无 ERROR 日志")
        return

    healed = 0
    unresolved = []

    # 去重: 同类错误只处理一次
    seen_patterns = set()

    for err in errors:
        matched = match_error_pattern(err["message"])
        if not matched:
            # 检查是否已记录过同一消息
            short_msg = err["message"][:80]
            if short_msg not in seen_patterns:
                unresolved.append(err)
                seen_patterns.add(short_msg)
            continue

        action = matched["action"]
        pattern_key = matched["pattern"]
        if pattern_key in seen_patterns:
            continue
        seen_patterns.add(pattern_key)

        result = "skipped"
        try:
            if action == "repair_json":
                json_path = _extract_json_path_from_error(err["message"])
                if json_path:
                    repair_json(json_path)
                    result = "success"
                else:
                    result = "no_file_found"

            elif action == "clean_logs":
                clean_old_logs(days=30)
                result = "success"

            elif action == "clear_cache":
                logger.info("API超时: 记录频率, 建议检查网络")
                result = "logged"

            elif action == "log_connection":
                logger.info("连接异常: 记录频率, 等待恢复")
                result = "logged"

            else:
                result = "unknown_action"

        except Exception as e:
            result = f"error: {e}"
            logger.error("修复动作 %s 异常: %s", action, e)

        # 记录修复历史
        history = safe_load(_HEAL_HISTORY_PATH)
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_type": matched["description"],
            "file": err.get("file", ""),
            "action": action,
            "result": result,
        })
        safe_save(_HEAL_HISTORY_PATH, history)

        if result == "success":
            healed += 1

    logger.info("自动修复完成: %d 项修复, %d 项无法自动处理", healed, len(unresolved))

    # 推送无法自动修复的告警
    if unresolved:
        logger.warning("以下错误需人工处理:")
        for err in unresolved[:5]:
            logger.warning("  [%s] %s: %s", err["timestamp"], err["module"], err["message"][:100])


# ================================================================
#  健康报告
# ================================================================

def generate_health_report() -> str:
    """生成系统健康报告 (Markdown, 随周报一起推送)

    包含: 本周错误统计, 自动修复次数, 冒烟测试结果, 磁盘使用
    """
    lines = ["## 系统健康报告"]

    # 本周错误统计
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    patterns = _load_error_patterns()
    active_patterns = [p for p in patterns if p.get("last_seen", "") >= week_ago]
    if active_patterns:
        lines.append("\n### 本周错误统计")
        lines.append("| 错误类型 | 出现次数 | 最后出现 |")
        lines.append("|----------|----------|----------|")
        for p in active_patterns:
            lines.append(f"| {p['description']} | {p['count']} | {p['last_seen'][:10]} |")
    else:
        lines.append("\n### 本周错误统计\n- 本周无错误记录")

    # 自动修复次数
    heal_history = safe_load(_HEAL_HISTORY_PATH)
    recent_heals = [h for h in heal_history if h.get("date", "")[:10] >= week_ago]
    if recent_heals:
        success_count = sum(1 for h in recent_heals if h["result"] == "success")
        lines.append(f"\n### 自动修复\n- 本周修复: {len(recent_heals)} 次 (成功 {success_count} 次)")
    else:
        lines.append(f"\n### 自动修复\n- 本周无修复动作")

    # 磁盘使用
    try:
        usage = shutil.disk_usage(_DIR)
        total_gb = usage.total / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        used_pct = usage.used / usage.total * 100
        lines.append(f"\n### 磁盘使用\n- 总空间: {total_gb:.1f}GB | "
                     f"剩余: {free_gb:.1f}GB | 使用率: {used_pct:.0f}%")
    except Exception:
        lines.append("\n### 磁盘使用\n- 无法获取磁盘信息")

    # 日志目录大小
    if os.path.isdir(_LOG_DIR):
        total_log_size = sum(
            os.path.getsize(os.path.join(_LOG_DIR, f))
            for f in os.listdir(_LOG_DIR)
            if os.path.isfile(os.path.join(_LOG_DIR, f))
        )
        log_mb = total_log_size / (1024 * 1024)
        lines.append(f"- 日志目录: {log_mb:.1f}MB")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "smoke":
        result = run_smoke_test()
        print()
        for r in result["results"]:
            tag = "PASS" if r["passed"] else "FAIL"
            err = f" — {r['error']}" if r["error"] else ""
            print(f"  [{tag}] {r['name']}{err}")
        print(f"\n  结果: {'PASSED' if result['passed'] else 'FAILED'}")

    elif mode == "heal":
        auto_heal()

    elif mode == "report":
        print(generate_health_report())

    elif mode == "clean":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        clean_old_logs(days)

    elif mode == "scan":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        errors = scan_recent_errors(hours)
        if errors:
            print(f"\n最近 {hours} 小时 ERROR 日志 ({len(errors)} 条):")
            for e in errors[:20]:
                print(f"  [{e['timestamp']}] {e['module']}: {e['message'][:80]}")
        else:
            print(f"最近 {hours} 小时无 ERROR 日志")

    else:
        print("用法:")
        print("  python3 self_healer.py smoke       # 运行冒烟测试")
        print("  python3 self_healer.py heal        # 扫描错误 + 自动修复")
        print("  python3 self_healer.py report      # 查看健康报告")
        print("  python3 self_healer.py clean       # 清理旧日志 (默认30天)")
        print("  python3 self_healer.py clean 7     # 清理7天前日志")
        print("  python3 self_healer.py scan        # 扫描最近24小时错误")
        sys.exit(1)
