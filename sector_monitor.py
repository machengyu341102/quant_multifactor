"""
板块异动监控
============
每5分钟扫描行业+概念板块:
  1. 检测异动板块 (涨幅≥2% / 上涨占比高)
  2. 获取异动板块领涨股TOP3
  3. 去重推送微信 (同板块30分钟内不重复)

数据源: 新浪财经 (免费, 稳定)

用法:
  python3 sector_monitor.py          # 立即扫描一次
  python3 sector_monitor.py history   # 查看今日异动记录
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("sector_monitor")

_DIR = os.path.dirname(os.path.abspath(__file__))
_ALERT_HISTORY_PATH = os.path.join(_DIR, "sector_alerts.json")

# ================================================================
#  配置
# ================================================================

_CHANGE_THRESHOLD = 2.0       # 板块涨幅 ≥ 2% 为异动
_CHANGE_SOFT = 1.5            # 涨幅 ≥ 1.5% + 领涨强也算异动
_TOP_SECTORS = 5              # 最多推5个板块
_TOP_LEADERS = 3              # 每板块领涨股数
_DEDUP_MINUTES = 30           # 同板块30分钟内不重复

_SINA_HEADERS = {
    "Referer": "http://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
}
_TIMEOUT = 10


# ================================================================
#  新浪板块数据
# ================================================================

def _sina_get(url: str) -> str:
    """新浪HTTP请求"""
    req = urllib.request.Request(url, headers=_SINA_HEADERS)
    resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
    return resp.read().decode("gbk")


def _parse_sina_boards(raw: str) -> list[dict]:
    """解析新浪板块数据
    格式: code,name,stock_count,avg_price,change_pct,change_amt,
          volume,amount,top_code,top_change_pct,top_price,top_change_amt,top_name
    """
    m = re.search(r"\{(.+)\}", raw)
    if not m:
        return []
    data = json.loads("{" + m.group(1) + "}")
    boards = []
    for key, val in data.items():
        parts = val.split(",")
        if len(parts) < 13:
            continue
        try:
            boards.append({
                "code": parts[0],
                "name": parts[1],
                "count": int(parts[2]),
                "change_pct": float(parts[4]),
                "volume": int(parts[6]),
                "amount": int(parts[7]),
                "top_code": parts[8],
                "top_change_pct": float(parts[9]),
                "top_price": float(parts[10]),
                "top_name": parts[12],
            })
        except (ValueError, IndexError):
            continue
    return boards


def _fetch_industry_boards() -> list[dict]:
    """获取行业板块"""
    try:
        raw = _sina_get("http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php")
        boards = _parse_sina_boards(raw)
        for b in boards:
            b["type"] = "industry"
        return boards
    except Exception as e:
        logger.error("行业板块获取失败: %s", e)
        return []


def _fetch_concept_boards() -> list[dict]:
    """获取概念板块"""
    try:
        raw = _sina_get("http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class")
        boards = _parse_sina_boards(raw)
        for b in boards:
            b["type"] = "concept"
        return boards
    except Exception as e:
        logger.error("概念板块获取失败: %s", e)
        return []


def _fetch_board_stocks(board_code: str) -> list[dict]:
    """获取板块成分股 (按涨幅排序, 取TOP N)"""
    url = (
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
        f"?page=1&num={_TOP_LEADERS}&sort=changepercent&asc=0&node={board_code}"
    )
    try:
        raw = _sina_get(url)
        if not raw or raw.strip() == "[]":
            return []
        data = json.loads(raw)
        leaders = []
        for d in data:
            code = d.get("code", d.get("symbol", ""))
            leaders.append({
                "code": code,
                "name": d.get("name", ""),
                "change_pct": float(d.get("changepercent", 0)),
                "price": float(d.get("trade", d.get("settlement", 0))),
                "turnover": float(d.get("turnoverratio", 0)),
                "volume": int(float(d.get("volume", 0))),
            })
        return leaders
    except Exception as e:
        logger.debug("板块成分股获取失败 %s: %s", board_code, e)
        return []


# ================================================================
#  异动检测 & 评分
# ================================================================

def _score_board(board: dict) -> float:
    """板块异动评分 (0-100)"""
    change = board.get("change_pct", 0)
    top_change = board.get("top_change_pct", 0)
    count = board.get("count", 1)

    score = 0.0

    # 涨幅分 (0-40): 2%=20, 3%=30, 5%+=40
    score += min(change * 10, 40)

    # 领涨股强度分 (0-30): 涨停=30, 5%=15
    score += min(top_change * 3, 30)

    # 板块规模分 (0-15): 大板块(>50只)异动更有意义
    if count >= 50:
        score += 15
    elif count >= 20:
        score += 10
    else:
        score += 5

    # 成交额加分 (0-15)
    amount = board.get("amount", 0)
    if amount > 10_000_000_000:     # >100亿
        score += 15
    elif amount > 5_000_000_000:    # >50亿
        score += 10
    elif amount > 1_000_000_000:    # >10亿
        score += 5

    return round(score, 1)


def _detect_anomalies(boards: list[dict]) -> list[dict]:
    """筛选异动板块"""
    anomalies = []
    for b in boards:
        change = abs(b.get("change_pct", 0))
        top_change = abs(b.get("top_change_pct", 0))

        # 涨幅 ≥ 2%
        # 或 涨幅 ≥ 1.5% 且领涨股涨幅 ≥ 5%
        if change >= _CHANGE_THRESHOLD or (change >= _CHANGE_SOFT and top_change >= 5):
            b["score"] = _score_board(b)
            # 标记方向
            b["direction"] = "up" if b.get("change_pct", 0) > 0 else "down"
            anomalies.append(b)

    anomalies.sort(key=lambda x: x["score"], reverse=True)
    return anomalies[:_TOP_SECTORS]


# ================================================================
#  去重
# ================================================================

def _load_history() -> dict:
    return safe_load(_ALERT_HISTORY_PATH, default={"alerts": {}, "today_log": []})


def _is_deduped(name: str, history: dict) -> bool:
    last_str = history.get("alerts", {}).get(name, "")
    if not last_str:
        return False
    try:
        last = datetime.fromisoformat(last_str)
        return (datetime.now() - last).total_seconds() < _DEDUP_MINUTES * 60
    except (ValueError, TypeError):
        return False


def _mark_alerted(names: list[str], history: dict):
    now_str = datetime.now().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    for name in names:
        history["alerts"][name] = now_str
    # 清理昨天的
    history["alerts"] = {k: v for k, v in history.get("alerts", {}).items() if v[:10] >= today}
    safe_save(_ALERT_HISTORY_PATH, history)


# ================================================================
#  核心扫描
# ================================================================

def scan_sector_anomaly(**kwargs) -> list[dict]:
    """扫描板块异动, 有异动则推送微信

    Returns:
        异动板块列表, 无异动返回空列表
    """
    logger.info("[板块监控] 开始扫描...")

    # 1. 拉取行业+概念
    industry = _fetch_industry_boards()
    concept = _fetch_concept_boards()
    all_boards = industry + concept
    logger.info("[板块监控] 获取 %d 行业 + %d 概念板块", len(industry), len(concept))

    if not all_boards:
        logger.warning("[板块监控] 无板块数据")
        return []

    # 2. 异动检测
    anomalies = _detect_anomalies(all_boards)
    if not anomalies:
        logger.info("[板块监控] 无异动板块")
        return []

    # 3. 去重
    history = _load_history()
    new_anomalies = [a for a in anomalies if not _is_deduped(a["name"], history)]
    if not new_anomalies:
        logger.info("[板块监控] %d个异动均已推过, 跳过", len(anomalies))
        return []

    # 4. 获取领涨股TOP3
    for board in new_anomalies:
        leaders = _fetch_board_stocks(board["code"])
        if not leaders:
            # 用板块自带的领涨股作为兜底
            leaders = [{
                "code": board.get("top_code", ""),
                "name": board.get("top_name", ""),
                "change_pct": board.get("top_change_pct", 0),
                "price": board.get("top_price", 0),
                "turnover": 0,
            }]
        board["leaders"] = leaders
        time.sleep(0.2)

    # 5. 推送微信
    _push_alert(new_anomalies)

    # 6. 标记 + 日志
    _mark_alerted([b["name"] for b in new_anomalies], history)
    _log_today(new_anomalies)

    logger.info("[板块监控] 发现 %d 个异动板块, 已推送", len(new_anomalies))
    return new_anomalies


# ================================================================
#  推送
# ================================================================

def _push_alert(boards: list[dict]):
    """推送板块异动到微信"""
    try:
        from notifier import notify_wechat_raw
    except ImportError:
        logger.error("notifier 导入失败")
        return

    lines = ["板块异动预警", ""]
    for i, b in enumerate(boards, 1):
        tag = "概念" if b.get("type") == "concept" else "行业"
        arrow = "↑" if b.get("direction") == "up" else "↓"
        lines.append(
            f"{i}. {b['name']} ({tag}) "
            f"{arrow}{b['change_pct']:+.2f}% "
            f"({b['count']}只) "
            f"评分{b.get('score', 0):.0f}"
        )
        for j, ld in enumerate(b.get("leaders", []), 1):
            to_str = f" 换手{ld['turnover']:.1f}%" if ld.get("turnover") else ""
            lines.append(
                f"   {_num_icon(j)} {ld['code']} {ld['name']} "
                f"{ld['change_pct']:+.2f}% "
                f"¥{ld['price']:.2f}{to_str}"
            )
        lines.append("")

    lines.append(f"扫描时间: {datetime.now().strftime('%H:%M:%S')}")

    try:
        notify_wechat_raw("板块异动预警", "\n".join(lines))
    except Exception as e:
        logger.error("推送失败: %s", e)


def _num_icon(n: int) -> str:
    return {1: "①", 2: "②", 3: "③"}.get(n, f"{n}.")


def _log_today(boards: list[dict]):
    """记录今日日志"""
    history = safe_load(_ALERT_HISTORY_PATH, default={"alerts": {}, "today_log": []})
    today = datetime.now().strftime("%Y-%m-%d")
    history["today_log"] = [r for r in history.get("today_log", []) if r.get("date") == today]
    for b in boards:
        history["today_log"].append({
            "date": today,
            "time": datetime.now().strftime("%H:%M:%S"),
            "sector": b["name"],
            "type": b.get("type", "industry"),
            "change_pct": b["change_pct"],
            "score": b.get("score", 0),
            "leaders": [
                {"code": ld["code"], "name": ld["name"], "change_pct": ld["change_pct"]}
                for ld in b.get("leaders", [])
            ],
        })
    safe_save(_ALERT_HISTORY_PATH, history)


# ================================================================
#  CLI
# ================================================================

def show_history():
    history = safe_load(_ALERT_HISTORY_PATH, default={})
    today = datetime.now().strftime("%Y-%m-%d")
    logs = [r for r in history.get("today_log", []) if r.get("date") == today]
    if not logs:
        print("今日暂无板块异动记录")
        return
    print(f"今日板块异动 ({len(logs)}条):")
    for r in logs:
        print(f"\n  [{r['time']}] {r['sector']} ({r['type']}) {r['change_pct']:+.2f}% 评分{r.get('score',0):.0f}")
        for ld in r.get("leaders", []):
            print(f"    {ld['code']} {ld['name']} {ld['change_pct']:+.2f}%")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "history":
        show_history()
    else:
        result = scan_sector_anomaly()
        if result:
            print(f"\n发现 {len(result)} 个异动板块")
        else:
            print("当前无板块异动")
