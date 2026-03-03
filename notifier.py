"""
多渠道通知模块
==============
- 终端格式化输出
- macOS 桌面通知 (osascript)
- 微信 Server酱 推送
"""

import os
import subprocess
import requests
from datetime import datetime, date
from config import SERVERCHAN_SENDKEY, MAX_WECHAT_DAILY
from log_config import get_logger

logger = get_logger("notifier")

# 同花顺自选股导出目录 (与本文件同目录)
_THS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ths_export")


# ================================================================
#  格式化推荐结果
# ================================================================

def format_recommendation(strategy_name: str, items: list[dict]) -> tuple[str, str]:
    """
    将标准化的 list[dict] 格式化为 (title, body)

    每个 item 至少包含: code, name, price, score, reason
    返回: (通知标题, 详情正文)
    """
    now_str = datetime.now().strftime("%H:%M")
    title = f"[{now_str}] {strategy_name} - 推荐 {len(items)} 只"

    if not items:
        return title, "本轮无符合条件的推荐标的"

    lines = []
    for i, it in enumerate(items, 1):
        code = it.get("code", "")
        name = it.get("name", "")
        price = it.get("price", 0)
        score = it.get("score", 0)
        reason = it.get("reason", "")
        lines.append(f"{i}. {code} {name}  ¥{price:.2f}  得分:{score:+.3f}")
        if reason:
            lines.append(f"   {reason}")

    body = "\n".join(lines)
    return title, body


# ================================================================
#  终端通知
# ================================================================

def notify_terminal(strategy_name: str, items: list[dict]):
    """终端格式化打印推荐结果"""
    try:
        title, body = format_recommendation(strategy_name, items)
        print()
        print("=" * 60)
        print(f"  {title}")
        print("=" * 60)
        if items:
            print(body)
        else:
            print("  本轮无符合条件的推荐标的")
        print("=" * 60)
        print()
    except Exception as e:
        print(f"[终端通知异常] {e}")


# ================================================================
#  macOS 桌面通知
# ================================================================

def notify_macos(strategy_name: str, items: list[dict]):
    """通过 osascript 发送 macOS 桌面通知"""
    try:
        title, body = format_recommendation(strategy_name, items)
        # 截断 body 避免通知太长
        short_body = body[:200] if len(body) > 200 else body
        # 转义双引号
        safe_title = title.replace('"', '\\"')
        safe_body = short_body.replace('"', '\\"')

        script = (
            f'display notification "{safe_body}" '
            f'with title "{safe_title}" '
            f'sound name "Glass"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            timeout=10,
            capture_output=True,
        )
    except Exception as e:
        print(f"[macOS通知异常] {e}")


# ================================================================
#  微信 Server酱 推送
# ================================================================

def notify_wechat(strategy_name: str, items: list[dict]):
    """通过 Server酱 API 推送 Markdown 到微信"""
    if not SERVERCHAN_SENDKEY:
        return
    if not _wechat_quota_ok():
        print(f"[微信推送] 今日已达上限 {MAX_WECHAT_DAILY} 条, 跳过: {strategy_name}")
        return

    try:
        title, body = format_recommendation(strategy_name, items)

        # 构建 Markdown 正文
        md_lines = [f"## {title}", ""]
        if items:
            for i, it in enumerate(items, 1):
                code = it.get("code", "")
                name = it.get("name", "")
                price = it.get("price", 0)
                score = it.get("score", 0)
                reason = it.get("reason", "")
                md_lines.append(f"**{i}. {code} {name}**")
                md_lines.append(f"- 现价: ¥{price:.2f}")
                md_lines.append(f"- 得分: {score:+.3f}")
                if reason:
                    md_lines.append(f"- 理由: {reason}")
                md_lines.append("")
        else:
            md_lines.append("本轮无符合条件的推荐标的")

        md_lines.append(f"---\n*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        desp = "\n".join(md_lines)

        url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0:
                _wechat_quota_incr()
                print(f"[微信推送] 成功: {title}")
            else:
                print(f"[微信推送] 返回异常: {result}")
        else:
            print(f"[微信推送] HTTP {resp.status_code}")
    except Exception as e:
        print(f"[微信推送异常] {e}")


# ================================================================
#  统一通知入口
# ================================================================

def notify_all(strategy_name: str, items: list[dict]):
    """同时触发三个通知渠道 + 导出同花顺自选股 (互不影响)"""
    notify_terminal(strategy_name, items)
    notify_macos(strategy_name, items)
    notify_wechat(strategy_name, items)
    export_ths_watchlist(strategy_name, items)


# ================================================================
#  同花顺自选股导出
# ================================================================

def _to_ths_code(code: str) -> str:
    """纯数字代码 → 同花顺格式 (SH600036 / SZ000001)"""
    if code.startswith(("6", "9")):
        return f"SH{code}"
    return f"SZ{code}"


def export_ths_watchlist(strategy_name: str, items: list[dict]):
    """导出推荐股票为同花顺可导入的自选股文件

    生成两个文件:
    - ths_export/{策略名}.txt — 单策略自选股
    - ths_export/全部推荐.txt — 当日所有策略汇总
    """
    if not items:
        return

    codes = [it.get("code", "") for it in items if it.get("code") and it["code"] != "ERROR"]
    if not codes:
        return

    try:
        os.makedirs(_THS_DIR, exist_ok=True)

        # 单策略文件
        safe_name = strategy_name.replace("/", "_").replace(" ", "_")
        strategy_file = os.path.join(_THS_DIR, f"{safe_name}.txt")
        with open(strategy_file, "w", encoding="utf-8") as f:
            for code in codes:
                f.write(_to_ths_code(code) + "\n")

        # 汇总文件 (追加去重)
        combined_file = os.path.join(_THS_DIR, "全部推荐.txt")
        existing = set()
        if os.path.exists(combined_file):
            with open(combined_file, "r", encoding="utf-8") as f:
                existing = {line.strip() for line in f if line.strip()}

        new_codes = [_to_ths_code(c) for c in codes if _to_ths_code(c) not in existing]
        if new_codes:
            with open(combined_file, "a", encoding="utf-8") as f:
                for tc in new_codes:
                    f.write(tc + "\n")

        total = len(existing) + len(new_codes)
        print(f"[同花顺导出] {strategy_file} ({len(codes)}只) | 汇总 {total} 只")
    except Exception as e:
        print(f"[同花顺导出异常] {e}")


def notify_wechat_raw(title: str, desp: str):
    """直接推送 Markdown 内容到微信 (不经过 format_recommendation)

    用于周报、告警等非标准格式推送
    """
    if not SERVERCHAN_SENDKEY:
        return
    if not _wechat_quota_ok():
        print(f"[微信推送] 今日已达上限 {MAX_WECHAT_DAILY} 条, 跳过: {title}")
        return

    try:
        url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0:
                _wechat_quota_incr()
                print(f"[微信推送] 成功: {title}")
            else:
                print(f"[微信推送] 返回异常: {result}")
        else:
            print(f"[微信推送] HTTP {resp.status_code}")
    except Exception as e:
        print(f"[微信推送异常] {e}")


def clear_ths_watchlist():
    """清空汇总自选股文件 (每日开盘前调用)"""
    combined_file = os.path.join(_THS_DIR, "全部推荐.txt")
    if os.path.exists(combined_file):
        os.remove(combined_file)
        print("[同花顺导出] 已清空昨日汇总")


# ================================================================
#  微信推送每日额度控制
# ================================================================

_wechat_daily_count = {"date": "", "count": 0}


def _wechat_quota_ok() -> bool:
    """检查今日微信推送是否还有剩余额度"""
    today_str = date.today().isoformat()
    if _wechat_daily_count["date"] != today_str:
        _wechat_daily_count["date"] = today_str
        _wechat_daily_count["count"] = 0
    return _wechat_daily_count["count"] < MAX_WECHAT_DAILY


def _wechat_quota_incr():
    """推送成功后递增计数"""
    today_str = date.today().isoformat()
    if _wechat_daily_count["date"] != today_str:
        _wechat_daily_count["date"] = today_str
        _wechat_daily_count["count"] = 0
    _wechat_daily_count["count"] += 1


# ================================================================
#  卖出信号格式化与推送
# ================================================================

def format_exit_signal(exits: list[dict]) -> tuple[str, str]:
    """格式化卖出信号为 (title, body)

    exits: list[dict], 每项包含 code, name, entry_price, exit_price, pnl_pct, exit_reason
    """
    now_str = datetime.now().strftime("%H:%M")
    title = f"[{now_str}] 卖出信号 - {len(exits)} 只"

    if not exits:
        return title, "无卖出信号"

    lines = []
    for i, e in enumerate(exits, 1):
        code = e.get("code", "")
        name = e.get("name", "")
        entry = e.get("entry_price", 0)
        exit_p = e.get("exit_price", 0)
        pnl = e.get("pnl_pct", 0)
        reason = e.get("exit_reason", "")
        sign = "+" if pnl >= 0 else ""
        lines.append(
            f"{i}. {code} {name}  "
            f"买入¥{entry:.2f} → 现价¥{exit_p:.2f}  "
            f"{sign}{pnl:.1f}% [{reason}]"
        )

    body = "\n".join(lines)
    return title, body


def _notify_exit_wechat(title: str, exits: list[dict]):
    """通过 Server酱推送卖出信号 (Markdown 格式)"""
    if not SERVERCHAN_SENDKEY:
        return
    if not _wechat_quota_ok():
        print(f"[微信推送] 今日已达上限 {MAX_WECHAT_DAILY} 条, 跳过卖出信号推送")
        return

    try:
        md_lines = [f"## {title}", ""]
        for i, e in enumerate(exits, 1):
            code = e.get("code", "")
            name = e.get("name", "")
            entry = e.get("entry_price", 0)
            exit_p = e.get("exit_price", 0)
            pnl = e.get("pnl_pct", 0)
            reason = e.get("exit_reason", "")
            sign = "+" if pnl >= 0 else ""
            emoji = "\u2705" if pnl >= 0 else "\u274c"
            md_lines.append(f"**{i}. {code} {name}** {emoji}")
            md_lines.append(f"- 买入: \u00a5{entry:.2f}")
            md_lines.append(f"- 现价: \u00a5{exit_p:.2f}")
            md_lines.append(f"- 盈亏: {sign}{pnl:.1f}%")
            md_lines.append(f"- 原因: **{reason}**")
            md_lines.append("")

        md_lines.append(f"---\n*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        desp = "\n".join(md_lines)

        url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0:
                _wechat_quota_incr()
                print(f"[微信推送] 卖出信号成功: {title}")
            else:
                print(f"[微信推送] 返回异常: {result}")
        else:
            print(f"[微信推送] HTTP {resp.status_code}")
    except Exception as e:
        print(f"[微信推送异常] {e}")


def notify_batch_wechat(batch_title: str, strategy_results: list[tuple]):
    """将多个策略结果合并为一条微信推送

    Args:
        batch_title: 批次标题 (如 "上午选股汇总")
        strategy_results: [(strategy_name, items), ...]
    """
    # 过滤空结果
    valid = [(name, items) for name, items in strategy_results if items]
    if not valid:
        print(f"[批量推送] {batch_title}: 无有效结果, 跳过")
        return

    if not SERVERCHAN_SENDKEY:
        return
    if not _wechat_quota_ok():
        print(f"[微信推送] 今日已达上限 {MAX_WECHAT_DAILY} 条, 跳过: {batch_title}")
        return

    try:
        now_str = datetime.now().strftime("%H:%M")
        title = f"[{now_str}] {batch_title}"

        md_lines = [f"# {title}", ""]
        for strategy_name, items in valid:
            md_lines.append(f"## {strategy_name} ({len(items)}只)")
            md_lines.append("")
            if items:
                for i, it in enumerate(items, 1):
                    code = it.get("code", "")
                    name = it.get("name", "")
                    price = it.get("price", 0)
                    score = it.get("score", 0)
                    reason = it.get("reason", "")
                    md_lines.append(f"**{i}. {code} {name}**")
                    md_lines.append(f"- 现价: ¥{price:.2f}")
                    md_lines.append(f"- 得分: {score:+.3f}")
                    if reason:
                        md_lines.append(f"- 理由: {reason}")
                    md_lines.append("")
            else:
                md_lines.append("无符合条件的推荐")
                md_lines.append("")

        md_lines.append(f"---\n*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        desp = "\n".join(md_lines)

        url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
        resp = requests.post(url, data={"title": title, "desp": desp}, timeout=15)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("code") == 0:
                _wechat_quota_incr()
                strategies_str = "+".join(name for name, _ in valid)
                print(f"[批量推送] 成功: {batch_title} ({strategies_str})")
            else:
                print(f"[批量推送] 返回异常: {result}")
        else:
            print(f"[批量推送] HTTP {resp.status_code}")
    except Exception as e:
        print(f"[批量推送异常] {e}")


def notify_exit(exits: list[dict]):
    """推送卖出信号 — 合并为一条推送"""
    if not exits:
        return

    title, body = format_exit_signal(exits)

    # 终端
    try:
        print()
        print("=" * 60)
        print(f"  {title}")
        print("=" * 60)
        print(body)
        print("=" * 60)
        print()
    except Exception as e:
        print(f"[终端通知异常] {e}")

    # macOS 桌面通知
    try:
        short_body = body[:200] if len(body) > 200 else body
        safe_title = title.replace('"', '\\"')
        safe_body = short_body.replace('"', '\\"')
        script = (
            f'display notification "{safe_body}" '
            f'with title "{safe_title}" '
            f'sound name "Sosumi"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            timeout=10, capture_output=True,
        )
    except Exception as e:
        print(f"[macOS通知异常] {e}")

    # 微信 (合并一条)
    _notify_exit_wechat(title, exits)
