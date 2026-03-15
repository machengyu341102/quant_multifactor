"""
纸盘模拟交易
============
模拟实盘执行但不真实下单, 记录虚拟持仓/盈亏.
用于上线前验证策略实际表现.

核心功能:
  1. 开仓: 接收策略推荐, 模拟买入 (考虑滑点+手续费)
  2. 监控: 实时/定时检查止损/止盈/追踪止盈/分批出场
  3. 平仓: 模拟卖出, 记录盈亏
  4. 统计: 胜率/收益/夏普/最大回撤/策略对比
  5. 日终: 每日自动结算, 生成报告

数据隔离: paper_positions.json / paper_trades.json / paper_equity.json
与真实 positions.json 完全隔离, 互不干扰.

用法:
  python3 paper_trader.py status        # 当前持仓
  python3 paper_trader.py history       # 交易历史
  python3 paper_trader.py stats         # 统计分析
  python3 paper_trader.py settle        # 手动结算
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("paper_trader")

_DIR = os.path.dirname(os.path.abspath(__file__))
_POSITIONS_PATH = os.path.join(_DIR, "paper_positions.json")
_TRADES_PATH = os.path.join(_DIR, "paper_trades.json")
_EQUITY_PATH = os.path.join(_DIR, "paper_equity.json")

# 从 config 读取交易成本和风控参数
try:
    from config import TRADE_COST, RISK_PARAMS, SMART_TRADE_ENABLED
except ImportError:
    TRADE_COST = {"commission": 0.00025, "stamp_tax": 0.0005, "slippage": 0.001}
    RISK_PARAMS = {"max_positions": 9, "max_daily_trades": 9,
                   "daily_loss_limit_pct": -5.0}
    SMART_TRADE_ENABLED = False

PAPER_PARAMS = {
    "initial_capital": 100000,      # 初始资金
    "single_position_pct": 15,      # 单笔仓位上限 (%)
    "max_positions": 9,             # 最大持仓数
    "max_daily_trades": 9,          # 每日最大开仓数
    "stop_loss_pct": -3.0,          # 基础止损 (%)
    "take_profit_pct": 5.0,         # 基础止盈 (%)
    "force_exit_days": 3,           # 最大持仓天数
    "use_smart_trade": True,        # 使用智能交易 (ATR止损/追踪/分批)
}

try:
    from config import PAPER_PARAMS as _CFG_PP
    PAPER_PARAMS.update(_CFG_PP)
except ImportError:
    pass


# ================================================================
#  持仓管理
# ================================================================

def load_positions() -> list[dict]:
    """加载纸盘持仓"""
    return safe_load(_POSITIONS_PATH, default=[])


def save_positions(positions: list[dict]):
    """保存纸盘持仓"""
    safe_save(_POSITIONS_PATH, positions)


def load_trades() -> list[dict]:
    """加载交易历史"""
    return safe_load(_TRADES_PATH, default=[])


def save_trades(trades: list[dict]):
    """保存交易历史 (保留最近500条)"""
    if len(trades) > 500:
        trades = trades[-500:]
    safe_save(_TRADES_PATH, trades)


def load_equity() -> list[dict]:
    """加载权益曲线"""
    return safe_load(_EQUITY_PATH, default=[])


def save_equity(equity: list[dict]):
    """保存权益曲线 (保留最近365天)"""
    if len(equity) > 365:
        equity = equity[-365:]
    safe_save(_EQUITY_PATH, equity)


# ================================================================
#  开仓
# ================================================================

def open_position(code: str, name: str, strategy: str,
                  entry_price: float, score: float = 0,
                  reason: str = "", atr: float = 0,
                  factor_scores: dict = None) -> dict | None:
    """模拟开仓

    Args:
        code: 股票代码
        name: 股票名称
        strategy: 策略名称
        entry_price: 买入价格
        score: 策略打分
        reason: 买入理由
        atr: ATR 值 (用于智能止损)
        factor_scores: 因子得分 (ML模型用)

    Returns:
        持仓记录, 或 None (被风控拦截)
    """
    positions = load_positions()
    today = date.today().isoformat()

    # 风控检查
    holding = [p for p in positions if p.get("status") == "holding"]
    if len(holding) >= PAPER_PARAMS["max_positions"]:
        logger.info("[纸盘] 持仓已满 (%d/%d), 跳过 %s",
                    len(holding), PAPER_PARAMS["max_positions"], code)
        return None

    # 今日开仓数检查
    today_opens = sum(1 for p in positions
                      if p.get("entry_date") == today and p.get("status") == "holding")
    if today_opens >= PAPER_PARAMS["max_daily_trades"]:
        logger.info("[纸盘] 今日开仓已达上限 %d, 跳过 %s",
                    PAPER_PARAMS["max_daily_trades"], code)
        return None

    # 不重复开仓
    if any(p.get("code") == code and p.get("status") == "holding"
           for p in positions):
        logger.info("[纸盘] 已持有 %s, 跳过", code)
        return None

    # 计算滑点成本后的实际买入价
    slippage = entry_price * TRADE_COST.get("slippage", 0.001)
    actual_price = round(entry_price + slippage, 2)

    # 计算买入手续费
    capital = PAPER_PARAMS["initial_capital"]
    position_size = capital * PAPER_PARAMS["single_position_pct"] / 100
    commission = position_size * TRADE_COST.get("commission", 0.00025)

    # 止损价
    stop_price = 0
    if PAPER_PARAMS["use_smart_trade"] and atr > 0:
        try:
            from smart_trader import calc_adaptive_stop
            stop_price = calc_adaptive_stop(actual_price, atr)
        except ImportError:
            stop_price = round(actual_price * (1 + PAPER_PARAMS["stop_loss_pct"] / 100), 2)
    else:
        stop_price = round(actual_price * (1 + PAPER_PARAMS["stop_loss_pct"] / 100), 2)

    position = {
        "code": code,
        "name": name,
        "strategy": strategy,
        "entry_price": actual_price,
        "entry_date": today,
        "entry_time": datetime.now().strftime("%H:%M:%S"),
        "score": round(score, 4),
        "reason": reason,
        "status": "holding",
        "mode": "paper",
        "atr": round(atr, 4) if atr else 0,
        "stop_price": round(stop_price, 2),
        "highest_price": actual_price,
        "lowest_price": actual_price,
        "partial_exited": False,
        "remaining_ratio": 1.0,
        "position_size": round(position_size, 2),
        "entry_commission": round(commission, 2),
        "factor_scores": factor_scores or {},
    }

    positions.append(position)
    save_positions(positions)

    # 记录开仓交易
    trade = {
        "action": "open",
        "code": code,
        "name": name,
        "strategy": strategy,
        "price": actual_price,
        "time": datetime.now().isoformat(),
        "reason": reason,
        "score": round(score, 4),
        "mode": "paper",
    }
    trades = load_trades()
    trades.append(trade)
    save_trades(trades)

    logger.info("[纸盘] 开仓: %s %s @ %.2f (策略: %s, 止损: %.2f)",
                code, name, actual_price, strategy, stop_price)

    # 事件总线通知
    _emit_event("paper_open", {
        "code": code, "name": name, "strategy": strategy,
        "price": actual_price, "message": f"纸盘开仓 {code} {name} @ {actual_price}",
    })

    return position


def batch_open(candidates: list[dict], strategy: str) -> list[dict]:
    """批量开仓 (策略推荐 → 纸盘执行)

    Args:
        candidates: [{code, name, price, score, reason, atr, factor_scores}]
        strategy: 策略名称

    Returns:
        成功开仓的持仓列表
    """
    opened = []
    for c in candidates:
        pos = open_position(
            code=c.get("code", ""),
            name=c.get("name", ""),
            strategy=strategy,
            entry_price=c.get("price", c.get("entry_price", 0)),
            score=c.get("score", c.get("total_score", 0)),
            reason=c.get("reason", ""),
            atr=c.get("atr", 0),
            factor_scores=c.get("factor_scores"),
        )
        if pos:
            opened.append(pos)
    return opened


# ================================================================
#  监控 & 平仓
# ================================================================

def check_exits(price_map: dict = None) -> list[dict]:
    """检查所有持仓的出场条件

    Args:
        price_map: {code: current_price} 如果为 None, 尝试获取实时行情

    Returns:
        本次平仓的记录列表
    """
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]
    if not holding:
        return []

    # 获取实时价格
    if price_map is None:
        price_map = _fetch_prices([p["code"] for p in holding])

    exits = []
    today = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M:%S")

    for pos in holding:
        code = pos["code"]
        price = price_map.get(code, 0)
        if price <= 0:
            continue

        entry_price = pos["entry_price"]
        pnl_pct = (price - entry_price) / entry_price * 100

        # 更新最高/最低价
        pos["highest_price"] = max(pos.get("highest_price", entry_price), price)
        pos["lowest_price"] = min(pos.get("lowest_price", entry_price), price)

        exit_reason = None

        # 1. 止损检查
        stop_price = pos.get("stop_price", 0)
        if stop_price > 0 and price <= stop_price:
            exit_reason = "止损"

        # 2. 智能追踪止盈
        if exit_reason is None and PAPER_PARAMS["use_smart_trade"]:
            try:
                from smart_trader import calc_trailing_stop
                trail = calc_trailing_stop(
                    entry_price, pos["highest_price"], price)
                if trail.get("should_exit"):
                    exit_reason = trail.get("exit_reason", "追踪止盈")
            except ImportError:
                pass

        # 3. 基础止盈
        if exit_reason is None and pnl_pct >= PAPER_PARAMS["take_profit_pct"]:
            exit_reason = "止盈"

        # 4. 基础止损 (备用)
        if exit_reason is None and pnl_pct <= PAPER_PARAMS["stop_loss_pct"]:
            exit_reason = "止损"

        # 5. 持仓天数到期
        if exit_reason is None:
            entry_date = pos.get("entry_date", today)
            try:
                days_held = (date.fromisoformat(today) -
                             date.fromisoformat(entry_date)).days
                if days_held >= PAPER_PARAMS["force_exit_days"]:
                    exit_reason = "到期离场"
            except (ValueError, TypeError):
                pass

        # 6. 分批出场检查
        if exit_reason is None and PAPER_PARAMS["use_smart_trade"]:
            if not pos.get("partial_exited", False):
                try:
                    from smart_trader import check_partial_exit
                    partial = check_partial_exit(entry_price, price, pos)
                    if partial.get("should_partial_exit"):
                        pos["partial_exited"] = True
                        pos["remaining_ratio"] = partial.get("remaining_ratio", 0.5)
                        logger.info("[纸盘] 分批止盈 %s: 卖出%.0f%%",
                                    code, (1 - pos["remaining_ratio"]) * 100)
                except ImportError:
                    pass

        if exit_reason:
            exit_record = _close_position(pos, price, exit_reason)
            exits.append(exit_record)

    save_positions(positions)
    return exits


def force_close_all(reason: str = "手动全平") -> list[dict]:
    """强制平仓所有持仓"""
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]
    if not holding:
        return []

    price_map = _fetch_prices([p["code"] for p in holding])
    exits = []
    for pos in holding:
        price = price_map.get(pos["code"], pos["entry_price"])
        exit_record = _close_position(pos, price, reason)
        exits.append(exit_record)

    save_positions(positions)
    return exits


def _close_position(pos: dict, exit_price: float, reason: str) -> dict:
    """执行平仓 (修改 pos dict in-place)"""
    entry_price = pos["entry_price"]

    # 滑点
    slippage = exit_price * TRADE_COST.get("slippage", 0.001)
    actual_exit = round(exit_price - slippage, 2)

    # 手续费 + 印花税
    position_size = pos.get("position_size", 10000)
    remaining = pos.get("remaining_ratio", 1.0)
    sell_value = position_size * remaining * (actual_exit / entry_price)
    commission = sell_value * TRADE_COST.get("commission", 0.00025)
    stamp_tax = sell_value * TRADE_COST.get("stamp_tax", 0.0005)

    # 盈亏
    raw_pnl_pct = (actual_exit - entry_price) / entry_price * 100
    total_cost_pct = (TRADE_COST.get("commission", 0.00025) * 2 +
                      TRADE_COST.get("stamp_tax", 0.0005) +
                      TRADE_COST.get("slippage", 0.001) * 2) * 100
    net_pnl_pct = round(raw_pnl_pct * remaining - total_cost_pct, 2)

    now = datetime.now()
    pos["status"] = "exited"
    pos["exit_price"] = actual_exit
    pos["exit_date"] = date.today().isoformat()
    pos["exit_time"] = now.strftime("%H:%M:%S")
    pos["exit_reason"] = reason
    pos["raw_pnl_pct"] = round(raw_pnl_pct, 2)
    pos["net_pnl_pct"] = net_pnl_pct
    pos["exit_commission"] = round(commission, 2)
    pos["exit_stamp_tax"] = round(stamp_tax, 2)

    result_label = "win" if net_pnl_pct > 0 else "loss"
    pos["result"] = result_label

    logger.info("[纸盘] 平仓: %s %s @ %.2f → %.2f (%+.2f%%) [%s]",
                pos["code"], pos["name"], entry_price, actual_exit,
                net_pnl_pct, reason)

    # 记录交易
    trade = {
        "action": "close",
        "code": pos["code"],
        "name": pos["name"],
        "strategy": pos.get("strategy", ""),
        "entry_price": entry_price,
        "exit_price": actual_exit,
        "raw_pnl_pct": round(raw_pnl_pct, 2),
        "net_pnl_pct": net_pnl_pct,
        "result": result_label,
        "reason": reason,
        "time": now.isoformat(),
        "days_held": _calc_days_held(pos),
        "mode": "paper",
    }
    trades = load_trades()
    trades.append(trade)
    save_trades(trades)

    # 事件通知
    _emit_event("paper_close", {
        "code": pos["code"], "name": pos["name"],
        "pnl_pct": net_pnl_pct, "reason": reason,
        "message": f"纸盘平仓 {pos['code']} {pos['name']} {net_pnl_pct:+.2f}% [{reason}]",
    })

    return trade


# ================================================================
#  日终结算
# ================================================================

def daily_settle() -> dict:
    """每日结算: 统计当日盈亏, 更新权益曲线

    Returns:
        {date, trades_today, pnl_today, equity, holdings}
    """
    today = date.today().isoformat()
    trades = load_trades()
    equity_curve = load_equity()

    # 今日已平仓的交易
    today_closed = [t for t in trades
                    if t.get("action") == "close"
                    and t.get("time", "")[:10] == today]

    # 今日盈亏
    pnl_today = sum(t.get("net_pnl_pct", 0) for t in today_closed)

    # 计算总权益
    all_closed = [t for t in trades if t.get("action") == "close"]
    total_pnl_pct = sum(t.get("net_pnl_pct", 0) for t in all_closed)
    initial = PAPER_PARAMS["initial_capital"]
    equity = round(initial * (1 + total_pnl_pct / 100), 2)

    # 当前持仓数
    positions = load_positions()
    n_holding = sum(1 for p in positions if p.get("status") == "holding")

    # 更新权益曲线
    entry = {
        "date": today,
        "equity": equity,
        "pnl_today": round(pnl_today, 2),
        "trades_today": len(today_closed),
        "holdings": n_holding,
        "total_pnl_pct": round(total_pnl_pct, 2),
    }

    # 去重 (同一天只保留最后一次)
    equity_curve = [e for e in equity_curve if e.get("date") != today]
    equity_curve.append(entry)
    equity_curve.sort(key=lambda x: x.get("date", ""))
    save_equity(equity_curve)

    logger.info("[纸盘] 日终结算: 今日 %d 笔, PnL %+.2f%%, 权益 %.0f, 持仓 %d",
                len(today_closed), pnl_today, equity, n_holding)

    return entry


# ================================================================
#  统计分析
# ================================================================

def calc_statistics(days: int = None) -> dict:
    """计算纸盘交易统计

    Args:
        days: 统计天数 (None=全部)

    Returns:
        {total, wins, losses, win_rate, avg_pnl, total_pnl,
         max_win, max_loss, avg_days_held, sharpe, max_drawdown,
         by_strategy: {...}}
    """
    trades = load_trades()
    closed = [t for t in trades if t.get("action") == "close"]

    if days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        closed = [t for t in closed if t.get("time", "")[:10] >= cutoff]

    if not closed:
        return {"total": 0, "error": "no_trades"}

    pnls = [t.get("net_pnl_pct", 0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    stats = {
        "total": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_pnl": round(float(np.mean(pnls)), 2),
        "total_pnl": round(sum(pnls), 2),
        "max_win": round(max(pnls), 2) if pnls else 0,
        "max_loss": round(min(pnls), 2) if pnls else 0,
        "avg_days_held": round(float(np.mean(
            [t.get("days_held", 1) for t in closed])), 1),
    }

    # 夏普比率
    if len(pnls) > 1:
        pnl_arr = np.array(pnls)
        mean_ret = float(np.mean(pnl_arr))
        std_ret = float(np.std(pnl_arr, ddof=1))
        stats["sharpe"] = round(mean_ret / std_ret * np.sqrt(252), 2) if std_ret > 0 else 0
    else:
        stats["sharpe"] = 0

    # 最大回撤
    equity_curve = load_equity()
    if equity_curve:
        equities = [e.get("equity", PAPER_PARAMS["initial_capital"])
                    for e in equity_curve]
        stats["max_drawdown"] = round(_calc_max_drawdown(equities), 2)
    else:
        stats["max_drawdown"] = 0

    # 按策略统计
    by_strategy = {}
    for t in closed:
        s = t.get("strategy", "unknown")
        if s not in by_strategy:
            by_strategy[s] = {"total": 0, "wins": 0, "pnls": []}
        by_strategy[s]["total"] += 1
        by_strategy[s]["pnls"].append(t.get("net_pnl_pct", 0))
        if t.get("net_pnl_pct", 0) > 0:
            by_strategy[s]["wins"] += 1

    for s, d in by_strategy.items():
        d["win_rate"] = round(d["wins"] / d["total"] * 100, 1) if d["total"] else 0
        d["avg_pnl"] = round(float(np.mean(d["pnls"])), 2)
        d["total_pnl"] = round(sum(d["pnls"]), 2)
        del d["pnls"]  # 不返回原始列表

    stats["by_strategy"] = by_strategy

    return stats


def get_holdings_summary() -> dict:
    """获取当前持仓汇总"""
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        return {"count": 0, "positions": []}

    price_map = _fetch_prices([p["code"] for p in holding])

    details = []
    total_pnl = 0
    for p in holding:
        price = price_map.get(p["code"], p["entry_price"])
        pnl = (price - p["entry_price"]) / p["entry_price"] * 100 if p["entry_price"] else 0
        total_pnl += pnl
        details.append({
            "code": p["code"],
            "name": p["name"],
            "strategy": p.get("strategy", ""),
            "entry_price": p["entry_price"],
            "current_price": price,
            "pnl_pct": round(pnl, 2),
            "days_held": _calc_days_held(p),
        })

    return {
        "count": len(holding),
        "total_pnl_pct": round(total_pnl, 2),
        "positions": sorted(details, key=lambda x: x["pnl_pct"], reverse=True),
    }


# ================================================================
#  报告生成
# ================================================================

def generate_paper_report(days: int = 30) -> str:
    """生成纸盘交易报告 (Markdown)"""
    stats = calc_statistics(days)
    holdings = get_holdings_summary()

    lines = [
        f"## 纸盘模拟交易报告",
        f"统计周期: 近{days}天 | 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if stats.get("error"):
        lines.append("暂无交易数据")
        return "\n".join(lines)

    # 总览
    lines.append("### 总体表现")
    lines.append(f"- 总交易: {stats['total']}笔 | 胜率: {stats['win_rate']}%")
    lines.append(f"- 累计收益: {stats['total_pnl']:+.2f}% | 平均收益: {stats['avg_pnl']:+.2f}%")
    lines.append(f"- 最大盈利: {stats['max_win']:+.2f}% | 最大亏损: {stats['max_loss']:+.2f}%")
    lines.append(f"- 夏普比率: {stats['sharpe']} | 最大回撤: {stats['max_drawdown']:.2f}%")
    lines.append(f"- 平均持仓: {stats['avg_days_held']:.1f}天")
    lines.append("")

    # 策略对比
    if stats.get("by_strategy"):
        lines.append("### 策略表现")
        lines.append("| 策略 | 笔数 | 胜率 | 平均收益 | 累计收益 |")
        lines.append("|------|------|------|----------|----------|")
        for s, d in sorted(stats["by_strategy"].items(),
                           key=lambda x: x[1]["total_pnl"], reverse=True):
            lines.append(
                f"| {s} | {d['total']} | {d['win_rate']}%"
                f" | {d['avg_pnl']:+.2f}% | {d['total_pnl']:+.2f}% |"
            )
        lines.append("")

    # 当前持仓
    if holdings.get("count", 0) > 0:
        lines.append(f"### 当前持仓 ({holdings['count']}笔)")
        lines.append("| 代码 | 名称 | 策略 | 成本 | 现价 | 盈亏 | 天数 |")
        lines.append("|------|------|------|------|------|------|------|")
        for p in holdings["positions"]:
            lines.append(
                f"| {p['code']} | {p['name']} | {p['strategy']}"
                f" | {p['entry_price']:.2f} | {p['current_price']:.2f}"
                f" | {p['pnl_pct']:+.2f}% | {p['days_held']}天 |"
            )
        lines.append("")

    return "\n".join(lines)


# ================================================================
#  与策略对接
# ================================================================

def on_strategy_picks(picks: list[dict], strategy: str) -> list[dict]:
    """策略推荐 → 纸盘自动开仓 (主入口)

    在各策略的推送之后调用, 自动将推荐转为纸盘持仓.

    Args:
        picks: 策略推荐列表 [{code, name, score/total_score, reason, atr, factor_scores}]
        strategy: 策略名称

    Returns:
        成功开仓的列表
    """
    if not picks:
        return []

    # 获取实时价格作为入场价 (如果 picks 里没有 price)
    codes_need_price = [p["code"] for p in picks if not p.get("price")]
    if codes_need_price:
        pm = _fetch_prices(codes_need_price)
        for p in picks:
            if not p.get("price") and p["code"] in pm:
                p["price"] = pm[p["code"]]

    opened = batch_open(picks, strategy)
    if opened:
        logger.info("[纸盘] 策略 %s 开仓 %d/%d 笔",
                    strategy, len(opened), len(picks))
    return opened


# ================================================================
#  辅助函数
# ================================================================

def _fetch_prices(codes: list[str]) -> dict[str, float]:
    """获取实时价格 (批量)"""
    if not codes:
        return {}
    try:
        from intraday_strategy import _sina_batch_quote
        df = _sina_batch_quote(codes)
        if df is not None and not df.empty and "code" in df.columns and "price" in df.columns:
            return {row["code"]: float(row["price"])
                    for _, row in df.iterrows()
                    if row.get("price", 0) > 0}
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # 回退: 逐个尝试
    prices = {}
    try:
        import akshare as ak
        for code in codes[:10]:  # 限制请求数
            try:
                df = ak.stock_zh_a_spot_em()
                row = df[df["代码"] == code]
                if len(row) > 0:
                    prices[code] = float(row.iloc[0]["最新价"])
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
    except ImportError:
        pass

    return prices


def _calc_days_held(pos: dict) -> int:
    """计算持仓天数"""
    entry = pos.get("entry_date", date.today().isoformat())
    exit_d = pos.get("exit_date", date.today().isoformat())
    try:
        return max(1, (date.fromisoformat(exit_d) -
                        date.fromisoformat(entry)).days)
    except (ValueError, TypeError):
        return 1


def _calc_max_drawdown(equity_values: list[float]) -> float:
    """计算最大回撤 (%)"""
    if len(equity_values) < 2:
        return 0
    arr = np.array(equity_values)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak * 100
    return abs(float(np.min(dd)))


def _emit_event(event_type: str, payload: dict):
    """发送事件到事件总线"""
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        priority = Priority.URGENT if "stop" in event_type.lower() else Priority.NORMAL
        bus.emit(
            source="paper_trader",
            priority=priority,
            event_type=event_type,
            category="strategy",
            payload=payload,
        )
    except Exception as _exc:
        logger.warning("Suppressed exception: %s", _exc)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "status":
        summary = get_holdings_summary()
        if summary["count"] == 0:
            print("当前无纸盘持仓")
        else:
            print(f"纸盘持仓: {summary['count']}笔, 浮盈 {summary['total_pnl_pct']:+.2f}%")
            for p in summary["positions"]:
                print(f"  {p['code']} {p['name']} "
                      f"({p['strategy']}) "
                      f"{p['entry_price']:.2f}→{p['current_price']:.2f} "
                      f"{p['pnl_pct']:+.2f}% [{p['days_held']}天]")

    elif mode == "history":
        trades = load_trades()
        closed = [t for t in trades if t.get("action") == "close"]
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        for t in closed[-n:]:
            print(f"  {t.get('time', '')[:10]} {t['code']} {t['name']} "
                  f"({t.get('strategy', '?')}) "
                  f"{t.get('net_pnl_pct', 0):+.2f}% [{t.get('reason', '')}]")

    elif mode == "stats":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        stats = calc_statistics(days)
        if stats.get("error"):
            print("暂无交易数据")
        else:
            print(f"近{days}天纸盘统计:")
            print(f"  总交易: {stats['total']}笔 | 胜率: {stats['win_rate']}%")
            print(f"  累计收益: {stats['total_pnl']:+.2f}% | 平均: {stats['avg_pnl']:+.2f}%")
            print(f"  夏普: {stats['sharpe']} | 最大回撤: {stats['max_drawdown']:.2f}%")
            if stats.get("by_strategy"):
                print("\n  策略对比:")
                for s, d in sorted(stats["by_strategy"].items(),
                                   key=lambda x: x[1]["total_pnl"], reverse=True):
                    print(f"    {s}: {d['total']}笔 胜率{d['win_rate']}% "
                          f"收益{d['total_pnl']:+.2f}%")

    elif mode == "report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print(generate_paper_report(days))

    elif mode == "settle":
        result = daily_settle()
        print(f"日终结算: 今日{result.get('trades_today', 0)}笔, "
              f"PnL {result.get('pnl_today', 0):+.2f}%, "
              f"权益 {result.get('equity', 0):.0f}")

    elif mode == "close_all":
        exits = force_close_all()
        print(f"已平仓 {len(exits)} 笔")

    else:
        print("用法:")
        print("  python3 paper_trader.py status       # 当前持仓")
        print("  python3 paper_trader.py history [n]   # 交易历史")
        print("  python3 paper_trader.py stats [days]  # 统计分析")
        print("  python3 paper_trader.py report [days]  # 完整报告")
        print("  python3 paper_trader.py settle        # 日终结算")
        print("  python3 paper_trader.py close_all     # 全部平仓")
        sys.exit(1)
