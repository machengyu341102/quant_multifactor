"""
板块异动监控 → 跟涨潜力股
========================
每5分钟扫描行业+概念板块:
  1. 检测异动板块 (涨幅≥2% / 上涨占比高)
  2. 从异动板块成分股中选跟涨潜力股TOP3
     (涨幅0~板块*0.8, 量能放大, 换手适中, 盘中偏强)
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


def _fetch_board_stocks(board_code: str, num: int = 30) -> list[dict]:
    """获取板块成分股 (取 num 只, 按涨幅排序)"""
    url = (
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
        f"?page=1&num={num}&sort=changepercent&asc=0&node={board_code}"
    )
    try:
        raw = _sina_get(url)
        if not raw or raw.strip() == "[]":
            return []
        data = json.loads(raw)
        stocks = []
        for d in data:
            code = d.get("code", d.get("symbol", ""))
            price = float(d.get("trade", d.get("settlement", 0)))
            high = float(d.get("high", price))
            low = float(d.get("low", price))
            stocks.append({
                "code": code,
                "name": d.get("name", ""),
                "change_pct": float(d.get("changepercent", 0)),
                "price": price,
                "high": high,
                "low": low,
                "turnover": float(d.get("turnoverratio", 0)),
                "volume": int(float(d.get("volume", 0))),
                "amount": float(d.get("amount", 0)),
            })
        return stocks
    except Exception as e:
        logger.debug("板块成分股获取失败 %s: %s", board_code, e)
        return []


def _pick_followers(board: dict, all_stocks: list) -> list[dict]:
    """从板块成分股中选出潜力股 TOP 3

    上涨异动: 选还没跟上但方向对、有资金进场的补涨票
    下跌异动: 选逆势抗跌/上涨的强势股 (板块跌但个股不跌, 有独立行情)

    Args:
        board: 板块信息 (含 change_pct)
        all_stocks: _fetch_board_stocks 返回的成分股列表

    Returns:
        top 3 潜力股 (附带评分、标签、买卖点)
    """
    sector_pct = board.get("change_pct", 0)
    is_up = sector_pct > 0

    # 1. 过滤
    candidates = []
    for s in all_stocks:
        name = s.get("name", "")
        pct = s.get("change_pct", 0)
        if "ST" in name or "*ST" in name:
            continue
        if pct > 9.5:
            continue

        if is_up:
            # 上涨异动: 选 0% ≤ 涨幅 ≤ 板块*0.8 的补涨票
            if pct < 0 or pct > sector_pct * 0.8:
                continue
        else:
            # 下跌异动: 选逆势抗跌/上涨的 (pct > 板块涨幅, 即跌得少或不跌)
            if pct < sector_pct * 0.5:
                continue
            # 排除跌停
            if pct < -9.5:
                continue

        candidates.append(s)

    if not candidates:
        return []

    # 2. 计算 amount 排名百分位
    amounts = [c.get("amount", 0) for c in candidates]
    if amounts:
        sorted_amounts = sorted(amounts)
        n = len(sorted_amounts)
        for c in candidates:
            amt = c.get("amount", 0)
            rank = sum(1 for a in sorted_amounts if a <= amt)
            c["_amount_pct"] = rank / n if n > 0 else 0.5
    else:
        for c in candidates:
            c["_amount_pct"] = 0.5

    # 3. 评分
    abs_sector = abs(sector_pct) if sector_pct != 0 else 1
    for c in candidates:
        pct = c.get("change_pct", 0)
        price = c.get("price", 0)
        high = c.get("high", price)
        low = c.get("low", price)
        turnover = c.get("turnover", 0)

        if is_up:
            # 补涨空间 = (板块涨幅 - 个股涨幅) / 板块涨幅
            gap = (sector_pct - pct) / abs_sector
        else:
            # 抗跌强度 = (个股涨幅 - 板块涨幅) / |板块涨幅|
            gap = (pct - sector_pct) / abs_sector
        gap_score = min(max(gap, 0), 1.0)

        vol_score = c.get("_amount_pct", 0.5)

        # price_strength: 盘中偏强 (上涨) / 尾盘回升 (下跌)
        rng = high - low
        pos_score = (price - low) / rng if rng > 0 else 0.5

        if 3 <= turnover <= 8:
            turn_score = 1.0
        elif 1 <= turnover < 3 or 8 < turnover <= 12:
            turn_score = 0.6
        else:
            turn_score = 0.2

        if is_up:
            if 1 <= pct <= 2:
                heat_score = 1.0
            elif 0.5 <= pct < 1 or 2 < pct <= 3:
                heat_score = 0.7
            else:
                heat_score = 0.3
        else:
            # 下跌异动: 涨幅越高越好 (逆势强势)
            if pct >= 1:
                heat_score = 1.0
            elif 0 <= pct < 1:
                heat_score = 0.7
            else:
                heat_score = 0.3

        total = (
            gap_score * 0.30
            + vol_score * 0.25
            + pos_score * 0.20
            + turn_score * 0.15
            + heat_score * 0.10
        )
        c["follow_score"] = round(total, 4)

        if is_up:
            c["gap_pct"] = round(sector_pct - pct, 2)
        else:
            c["gap_pct"] = round(pct - sector_pct, 2)  # 相对强度

        # 标签
        labels = []
        if vol_score > 0.7:
            labels.append("资金进场")
        if 3 <= turnover <= 8:
            labels.append("换手适中")
        if pos_score > 0.6:
            labels.append("盘中偏强")
        if is_up:
            if gap_score > 0.6:
                labels.append(f"补涨空间{c['gap_pct']:.1f}%")
        else:
            if pct >= 0:
                labels.append("逆势上涨")
            else:
                labels.append("抗跌")
        c["label"] = " ".join(labels) if labels else ("逆势强势" if not is_up else f"补涨{c['gap_pct']:.1f}%")

    # 4. 买卖点计算
    for c in candidates:
        price = c.get("price", 0)
        high = c.get("high", price)
        low = c.get("low", price)
        gap_pct = c.get("gap_pct", 0)

        if price <= 0:
            continue

        c["buy_price"] = round(price - price * 0.003, 2)

        if is_up:
            c["stop_loss"] = round(low * 0.995, 2)
        else:
            # 逆势股止损更紧: 买入价下方 1.5%
            c["stop_loss"] = round(price * 0.985, 2)
        c["stop_pct"] = round((c["stop_loss"] / price - 1) * 100, 1)

        if is_up:
            target_gain = max(gap_pct, sector_pct * 0.8, 2.0)
        else:
            # 下跌异动中逆势股: 板块企稳后弹性更大, 目标 3%
            target_gain = max(gap_pct * 0.5, 3.0)
        c["target_price"] = round(price * (1 + target_gain / 100), 2)
        c["target_pct"] = round(target_gain, 1)

        risk = price - c["stop_loss"]
        reward = c["target_price"] - price
        c["risk_reward"] = round(reward / risk, 1) if risk > 0 else 0

    # 5. 排序取 top 3
    candidates.sort(key=lambda x: x["follow_score"], reverse=True)
    return candidates[:3]


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

    # 4. 获取成分股 → 选跟涨潜力股 (并行)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _calc_trade_points(f, sector_pct):
        """为单只股票计算买卖点"""
        price = f.get("price", 0)
        if price <= 0:
            return
        high = f.get("high", price)
        low = f.get("low", price * 0.98)
        gap_pct = f.get("gap_pct", 0)
        f["buy_price"] = round(price - price * 0.003, 2)
        f["stop_loss"] = round(low * 0.995, 2)
        f["stop_pct"] = round((f["stop_loss"] / price - 1) * 100, 1)
        target_gain = max(gap_pct, sector_pct * 0.8, 2.0)
        f["target_price"] = round(price * (1 + target_gain / 100), 2)
        f["target_pct"] = round(target_gain, 1)
        risk = price - f["stop_loss"]
        reward = f["target_price"] - price
        f["risk_reward"] = round(reward / risk, 1) if risk > 0 else 0

    def _fetch_and_pick(board):
        sector_pct = board.get("change_pct", 0)
        all_stocks = _fetch_board_stocks(board["code"], num=30)
        followers = _pick_followers(board, all_stocks) if all_stocks else []
        if not followers:
            followers = [{
                "code": board.get("top_code", ""),
                "name": board.get("top_name", ""),
                "change_pct": board.get("top_change_pct", 0),
                "price": board.get("top_price", 0),
                "high": board.get("top_price", 0),
                "low": board.get("top_price", 0) * 0.97,
                "turnover": 0,
                "label": "领涨股",
                "gap_pct": 0,
            }]
        # 确保所有 follower 都有买卖点
        for f in followers:
            if not f.get("buy_price"):
                _calc_trade_points(f, abs(sector_pct))
        return board, followers

    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(_fetch_and_pick, b): b for b in new_anomalies}
        for fut in as_completed(futs):
            try:
                board, followers = fut.result(timeout=10)
                board["followers"] = followers
            except Exception:
                board = futs[fut]
                sector_pct = abs(board.get("change_pct", 0))
                fallback = {
                    "code": board.get("top_code", ""),
                    "name": board.get("top_name", ""),
                    "change_pct": board.get("top_change_pct", 0),
                    "price": board.get("top_price", 0),
                    "high": board.get("top_price", 0),
                    "low": board.get("top_price", 0) * 0.97,
                    "turnover": 0, "label": "领涨股", "gap_pct": 0,
                }
                _calc_trade_points(fallback, sector_pct)
                board["followers"] = [fallback]

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
    """推送板块异动 → 跟涨潜力股到微信"""
    try:
        from notifier import notify_wechat_raw
    except ImportError:
        logger.error("notifier 导入失败")
        return

    lines = ["板块异动 → 潜力股", ""]
    for i, b in enumerate(boards, 1):
        tag = "概念" if b.get("type") == "concept" else "行业"
        arrow = "↑" if b.get("direction") == "up" else "↓"
        is_up = b.get("change_pct", 0) > 0
        lines.append(
            f"{i}. {b['name']} ({tag}) "
            f"{arrow}{b['change_pct']:+.2f}% "
            f"({b['count']}只)"
        )
        followers = b.get("followers", [])
        if followers:
            hint = "跟涨潜力:" if is_up else "逆势强势:"
            lines.append(f"   {hint}")
            for j, fl in enumerate(followers, 1):
                label = fl.get("label", "")
                lines.append(
                    f"   {_num_icon(j)} {fl['code']} {fl['name']} "
                    f"{fl['change_pct']:+.1f}% {label}"
                )
                # 买卖点提示
                if fl.get("buy_price"):
                    lines.append(
                        f"      买:{fl['buy_price']} "
                        f"止损:{fl['stop_loss']}({fl['stop_pct']}%) "
                        f"目标:{fl['target_price']}(+{fl['target_pct']}%) "
                        f"盈亏比:{fl['risk_reward']}"
                    )
        lines.append("")

    lines.append(f"扫描时间: {datetime.now().strftime('%H:%M:%S')}")

    try:
        notify_wechat_raw("板块异动 → 跟涨潜力股", "\n".join(lines))
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
            "followers": [
                {"code": fl["code"], "name": fl["name"], "change_pct": fl["change_pct"],
                 "label": fl.get("label", ""),
                 "buy_price": fl.get("buy_price"), "stop_loss": fl.get("stop_loss"),
                 "target_price": fl.get("target_price"), "risk_reward": fl.get("risk_reward")}
                for fl in b.get("followers", [])
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
        for fl in r.get("followers", r.get("leaders", [])):
            label = f" {fl['label']}" if fl.get("label") else ""
            print(f"    {fl['code']} {fl['name']} {fl['change_pct']:+.2f}%{label}")


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
