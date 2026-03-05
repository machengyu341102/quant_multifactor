"""
多渠道通知模块
==============
- 终端格式化输出
- macOS 桌面通知 (osascript)
- 企业微信应用消息 (直推个人, 支持 Markdown/文本卡片)
- 企业微信群机器人 (Webhook, 备选)
- Server酱 (最后备选)
"""

import os
import subprocess
import requests
import time
import threading
from datetime import datetime, date
from config import SERVERCHAN_SENDKEY, MAX_WECHAT_DAILY
from log_config import get_logger

logger = get_logger("notifier")

try:
    from config import WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_SECRET
except ImportError:
    WECOM_CORP_ID = ""
    WECOM_AGENT_ID = 0
    WECOM_SECRET = ""

try:
    from config import WECOM_BOT_KEY
except ImportError:
    WECOM_BOT_KEY = ""

# 同花顺自选股导出目录 (与本文件同目录)
_THS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ths_export")

# ================================================================
#  异步推送队列 (不阻塞 OODA 循环)
# ================================================================
import queue as _queue

_push_queue: _queue.Queue = _queue.Queue(maxsize=200)
_push_worker_started = False
_push_worker_lock = threading.Lock()


def _push_worker():
    """后台线程: 从队列取消息逐条发送"""
    while True:
        try:
            title, markdown = _push_queue.get(timeout=5)
            _send_push_sync(title, markdown)
        except _queue.Empty:
            continue
        except Exception as e:
            logger.warning("异步推送异常: %s", e)


def _ensure_push_worker():
    """确保推送 worker 线程已启动"""
    global _push_worker_started
    if _push_worker_started:
        return
    with _push_worker_lock:
        if _push_worker_started:
            return
        t = threading.Thread(target=_push_worker, daemon=True, name="push-worker")
        t.start()
        _push_worker_started = True


# ================================================================
#  格式化推荐结果
# ================================================================

def format_recommendation(strategy_name: str, items: list[dict]) -> tuple[str, str]:
    """
    将标准化的 list[dict] 格式化为 (title, body)

    每个 item 至少包含: code, name, price, score, reason
    返回: (通知标题, 详情正文)
    """
    if items is None:
        items = []
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
#  企业微信应用消息 (主渠道 — 直推个人)
# ================================================================

# access_token 缓存 (有效期 7200s, 提前 300s 刷新)
_token_cache = {"token": "", "expire_at": 0.0}
_token_lock = threading.Lock()


def _get_access_token() -> str:
    """获取企业微信 access_token (自动缓存+刷新)"""
    if not WECOM_CORP_ID or not WECOM_SECRET:
        return ""

    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expire_at"]:
            return _token_cache["token"]

    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {"corpid": WECOM_CORP_ID, "corpsecret": WECOM_SECRET}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            token = data["access_token"]
            with _token_lock:
                _token_cache["token"] = token
                _token_cache["expire_at"] = time.time() + data.get("expires_in", 7200) - 300
            return token
        logger.warning("获取access_token失败: %s", data)
    except Exception as e:
        logger.warning("获取access_token异常: %s", e)
    return ""


def _strip_markdown(text: str) -> str:
    """去掉 Markdown 标记, 转成普通微信能看的纯文本"""
    import re
    text = re.sub(r'<font[^>]*>', '', text)
    text = text.replace('</font>', '')
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)  # ## 标题 → 标题
    text = text.replace('**', '')   # 加粗
    text = text.replace('> ', '  ')  # 引用
    return text.strip()


def _wecom_app_send(content: str, msgtype: str = "text") -> bool:
    """企业微信应用消息 — 直推到个人 (纯文本, 兼容普通微信)"""
    token = _get_access_token()
    if not token:
        return False

    # 强制用 text, 普通微信不支持 markdown
    content = _strip_markdown(content)

    if len(content.encode("utf-8")) > 2000:
        content = content[:1000] + "\n\n...(内容过长已截断)"

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": "@all",
        "msgtype": "text",
        "agentid": WECOM_AGENT_ID,
        "text": {"content": content},
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        # token 过期, 清缓存重试一次
        if data.get("errcode") in (40014, 42001):
            with _token_lock:
                _token_cache["token"] = ""
            token = _get_access_token()
            if token:
                url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
                resp2 = requests.post(url, json=payload, timeout=15)
                data2 = resp2.json()
                if data2.get("errcode") == 0:
                    return True
                logger.warning("企业微信重试失败: %s", data2)
            return False
        logger.warning("企业微信应用消息失败: %s", data)
        return False
    except Exception as e:
        logger.warning("企业微信应用消息异常: %s", e)
        return False


def _wecom_app_send_to(userid: str, content: str) -> bool:
    """企业微信应用消息 — 发给指定用户"""
    token = _get_access_token()
    if not token:
        return False
    if len(content.encode("utf-8")) > 2000:
        content = content[:1000] + "\n\n...(内容过长已截断)"
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": userid,
        "msgtype": "text",
        "agentid": WECOM_AGENT_ID,
        "text": {"content": content}
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        return resp.json().get("errcode") == 0
    except Exception as e:
        logger.warning("企业微信定向发送失败: %s", e)
        return False


def _wecom_bot_send(content: str) -> bool:
    """企业微信群机器人 Webhook (备选渠道)"""
    if not WECOM_BOT_KEY:
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECOM_BOT_KEY}"
    if len(content.encode("utf-8")) > 4000:
        content = content[:2000] + "\n\n...(内容过长已截断)"

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        return resp.json().get("errcode") == 0
    except Exception:
        return False


def _send_push_sync(title: str, markdown: str) -> bool:
    """同步推送 (内部用, 由 worker 线程调用)"""
    if not _wechat_quota_ok():
        print(f"[推送] 今日已达上限 {MAX_WECHAT_DAILY} 条, 跳过: {title}")
        return False

    # 1. 企业微信应用消息 (直推个人)
    if WECOM_CORP_ID and WECOM_SECRET:
        ok = _wecom_app_send(markdown)
        if ok:
            _wechat_quota_incr()
            print(f"[企业微信] 成功: {title}")
            return True
        logger.warning("企业微信应用消息失败, 尝试备选: %s", title)

    # 2. 企业微信群机器人
    if WECOM_BOT_KEY:
        ok = _wecom_bot_send(markdown)
        if ok:
            _wechat_quota_incr()
            print(f"[企业微信Bot] 成功: {title}")
            return True

    # 3. Server酱备选
    if SERVERCHAN_SENDKEY:
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
            resp = requests.post(url, data={"title": title, "desp": markdown}, timeout=15)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    _wechat_quota_incr()
                    print(f"[Server酱] 成功: {title}")
                    return True
                print(f"[Server酱] 返回异常: {result}")
            else:
                print(f"[Server酱] HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Server酱异常] {e}")

    return False


def _send_push(title: str, markdown: str) -> bool:
    """异步推送入口: 投入队列立即返回, 不阻塞调用方"""
    _ensure_push_worker()
    try:
        _push_queue.put_nowait((title, markdown))
        return True
    except _queue.Full:
        logger.warning("推送队列已满, 降级为同步: %s", title)
        return _send_push_sync(title, markdown)


# ================================================================
#  微信推送 (兼容接口)
# ================================================================

def notify_wechat(strategy_name: str, items: list[dict]):
    """推送策略推荐结果 (企业微信优先)"""
    title, body = format_recommendation(strategy_name, items)

    # 构建 Markdown
    md_lines = [f"## {title}", ""]
    if items:
        for i, it in enumerate(items, 1):
            code = it.get("code", "")
            name = it.get("name", "")
            price = it.get("price", 0)
            score = it.get("score", 0)
            reason = it.get("reason", "")
            md_lines.append(f"**{i}. {code} {name}**")
            md_lines.append(f"> 现价: ¥{price:.2f}  得分: {score:+.3f}")
            if reason:
                md_lines.append(f"> {reason}")
            md_lines.append("")
    else:
        md_lines.append("本轮无符合条件的推荐标的")

    md_lines.append(f"\n<font color=\"comment\">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>")
    _send_push(title, "\n".join(md_lines))


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
    """直接推送 Markdown 内容 (用于周报、告警等非标准格式)"""
    _send_push(title, desp)


# ================================================================
#  三色分级推送 (红黄绿)
# ================================================================

LEVEL_CRITICAL = "critical"  # 红: 风控熔断/断路器/止损
LEVEL_WARNING = "warning"    # 橙: 策略偏差/冒烟失败/异常
LEVEL_INFO = "info"          # 绿: 常规选股/早晚报/健康

_LEVEL_ICON = {
    LEVEL_CRITICAL: "🔴",
    LEVEL_WARNING: "🟡",
    LEVEL_INFO: "🟢",
}
_LEVEL_COLOR = {
    LEVEL_CRITICAL: "warning",   # 企业微信 warning = 橙红
    LEVEL_WARNING: "warning",
    LEVEL_INFO: "info",          # 企业微信 info = 绿
}


def notify_alert(level: str, title: str, details: str):
    """三色分级推送

    Args:
        level: LEVEL_CRITICAL / LEVEL_WARNING / LEVEL_INFO
        title: 简短标题
        details: 详细内容 (支持Markdown)
    """
    icon = _LEVEL_ICON.get(level, "📢")
    color = _LEVEL_COLOR.get(level, "comment")
    md = (f"## {icon} {title}\n\n"
          f"<font color=\"{color}\">{details}</font>\n\n"
          f"<font color=\"comment\">{datetime.now().strftime('%H:%M:%S')}</font>")
    _send_push(f"{icon} {title}", md)


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
    """推送卖出信号"""
    md_lines = [f"## {title}", ""]
    for i, e in enumerate(exits, 1):
        code = e.get("code", "")
        name = e.get("name", "")
        entry = e.get("entry_price", 0)
        exit_p = e.get("exit_price", 0)
        pnl = e.get("pnl_pct", 0)
        reason = e.get("exit_reason", "")
        sign = "+" if pnl >= 0 else ""
        color = "info" if pnl >= 0 else "warning"
        md_lines.append(f"**{i}. {code} {name}**")
        md_lines.append(f"> 买入: ¥{entry:.2f} → 现价: ¥{exit_p:.2f}")
        md_lines.append(f"> <font color=\"{color}\">盈亏: {sign}{pnl:.1f}%</font>")
        md_lines.append(f"> 原因: **{reason}**")
        md_lines.append("")

    md_lines.append(f"\n<font color=\"comment\">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>")
    _send_push(title, "\n".join(md_lines))


def notify_batch_wechat(batch_title: str, strategy_results: list[tuple]):
    """将多个策略结果合并为一条推送"""
    valid = [(name, items) for name, items in strategy_results if items]
    if not valid:
        print(f"[批量推送] {batch_title}: 无有效结果, 跳过")
        return

    now_str = datetime.now().strftime("%H:%M")
    title = f"[{now_str}] {batch_title}"

    md_lines = [f"# {title}", ""]
    for strategy_name, items in valid:
        md_lines.append(f"## {strategy_name} ({len(items)}只)")
        md_lines.append("")
        for i, it in enumerate(items, 1):
            code = it.get("code", "")
            name = it.get("name", "")
            price = it.get("price", 0)
            score = it.get("score", 0)
            reason = it.get("reason", "")
            md_lines.append(f"**{i}. {code} {name}**")
            md_lines.append(f"> ¥{price:.2f}  得分: {score:+.3f}")
            if reason:
                md_lines.append(f"> {reason}")
            md_lines.append("")

    md_lines.append(f"\n<font color=\"comment\">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>")
    _send_push(title, "\n".join(md_lines))


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
