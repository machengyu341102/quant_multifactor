"""
实盘记分卡
==========
- 每日评分昨日推荐 (次日表现)
- 累计统计 (胜率/收益/分策略)
- 资金曲线 (累计净值/最大回撤/Sharpe)
- 每周推送周报

数据存储: SQLite (quant_data.db, WAL 模式) — OP-07 迁移自 scorecard.json
"""

from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from config import TRADE_COST, STOP_LOSS_PCT, TAKE_PROFIT_PCT, POSITION_FILE
from json_store import safe_load, safe_load_strict, safe_save
from log_config import get_logger

logger = get_logger("scorecard")

_DIR = os.path.dirname(os.path.abspath(__file__))
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_SCORECARD_DEFAULT = _SCORECARD_PATH
_POS_PATH = os.path.join(_DIR, POSITION_FILE)

# 交易成本: 佣金×2 + 印花税 + 滑点
_TOTAL_COST_PCT = (
    TRADE_COST["commission"] * 2 + TRADE_COST["stamp_tax"] + TRADE_COST["slippage"]
) * 100  # 转为百分比


# ================================================================
#  交易日历工具
# ================================================================

_trade_dates_cache: set[str] | None = None


def _get_trading_dates_set() -> set[str]:
    """获取交易日历集合 (ak.tool_trade_date_hist_sina, 缓存)"""
    global _trade_dates_cache
    if _trade_dates_cache is not None:
        return _trade_dates_cache

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        col = "trade_date"
        if col not in df.columns:
            col = df.columns[0]
        _trade_dates_cache = set(df[col].astype(str).str[:10].tolist())
        return _trade_dates_cache
    except Exception as e:
        logger.warning("交易日历获取失败: %s, 使用空集合", e)
        _trade_dates_cache = set()
        return _trade_dates_cache


def _prev_trading_day(from_date: str) -> str | None:
    """找 from_date 之前的上一个交易日"""
    trade_dates = _get_trading_dates_set()
    if not trade_dates:
        d = datetime.strptime(from_date, "%Y-%m-%d").date()
        for i in range(1, 10):
            prev = d - timedelta(days=i)
            if prev.weekday() < 5:
                return prev.isoformat()
        return None
    sorted_dates = sorted(d for d in trade_dates if d < from_date)
    return sorted_dates[-1] if sorted_dates else None


def _next_trading_day(from_date: str) -> str | None:
    """找 from_date 之后的下一个交易日"""
    trade_dates = _get_trading_dates_set()
    if not trade_dates:
        d = datetime.strptime(from_date, "%Y-%m-%d").date()
        for i in range(1, 10):
            nxt = d + timedelta(days=i)
            if nxt.weekday() < 5:
                return nxt.isoformat()
        return None
    sorted_dates = sorted(d for d in trade_dates if d > from_date)
    return sorted_dates[0] if sorted_dates else None


# ================================================================
#  数据获取
# ================================================================

def _tx_sym(code: str) -> str:
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def _fetch_next_day_ohlc(code: str, rec_date: str) -> dict | None:
    """获取推荐日次日的 OHLC (腾讯优先, 东财备选, 独立断路器)"""
    next_day = _next_trading_day(rec_date)
    if not next_day:
        return None

    import akshare as ak
    from api_guard import smart_source, SOURCE_TENCENT_KLINE, SOURCE_EM_KLINE

    start = next_day.replace("-", "")
    d = datetime.strptime(next_day, "%Y-%m-%d").date()
    end = (d + timedelta(days=5)).strftime("%Y%m%d")

    def _tx():
        df = ak.stock_zh_a_hist_tx(
            symbol=_tx_sym(code),
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ValueError("腾讯OHLC返回空")
        df["date_str"] = df["date"].astype(str).str[:10]
        target = df[df["date_str"] == next_day]
        if target.empty:
            target = df.head(1)
        row = target.iloc[0]
        return {
            "date": next_day,
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
        }

    def _em():
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start, end_date=end, adjust="qfq",
        )
        if df is None or df.empty:
            raise ValueError("东财OHLC返回空")
        date_col = "日期" if "日期" in df.columns else "date"
        df["date_str"] = df[date_col].astype(str).str[:10]
        target = df[df["date_str"] == next_day]
        if target.empty:
            target = df.head(1)
        row = target.iloc[0]
        return {
            "date": next_day,
            "open": float(row.get("开盘", row.get("open", 0))),
            "close": float(row.get("收盘", row.get("close", 0))),
            "high": float(row.get("最高", row.get("high", 0))),
            "low": float(row.get("最低", row.get("low", 0))),
        }

    try:
        return smart_source([
            (SOURCE_TENCENT_KLINE, _tx),
            (SOURCE_EM_KLINE, _em),
        ])
    except Exception as e:
        logger.warning("获取 %s 次日K线双源均失败: %s", code, e)
        return None


# ================================================================
#  核心评分逻辑
# ================================================================

def score_yesterday() -> list[dict]:
    """对前一交易日推荐进行次日表现评分

    评分 T-2 的推荐, 用 T-1 (昨天) 的完整 K 线打分.
    这样确保次日 OHLC 数据已完整可用.

    流程:
    1. 确定 T-1 = 上一交易日, T-2 = T-1 的上一交易日
    2. 从 positions.json 找 entry_date = T-2 的记录
    3. 对每条: 获取 T-1 K线 -> 计算收益 -> 判定 win/loss
    4. 去重后写入 scorecard (SQLite)
    """
    today_str = date.today().isoformat()
    yesterday = _prev_trading_day(today_str)
    if not yesterday:
        logger.warning("无法确定昨日交易日, 跳过评分")
        return []

    # 评分 T-2 的推荐 (用 T-1 的 OHLC, 确保数据完整)
    score_date = _prev_trading_day(yesterday)
    if not score_date:
        logger.warning("无法确定前日交易日, 跳过评分")
        return []

    logger.info("评分日期: %s → 次日表现(%s)", score_date, yesterday)

    positions = safe_load_strict(_POS_PATH)
    score_entries = [
        p for p in positions
        if p.get("entry_date") == score_date
    ]

    if not score_entries:
        logger.info("%s 无推荐记录, 跳过", score_date)
        return []

    from db_store import load_scorecard as _db_load, save_scorecard_records
    existing = _db_load()
    existing_keys = {
        (r.get("rec_date", ""), r.get("code", ""), r.get("strategy", ""))
        for r in existing
    }

    new_scores = []
    for p in score_entries:
        code = p["code"]
        strategy = p["strategy"]
        key = (score_date, code, strategy)
        if key in existing_keys:
            continue

        entry_price = p.get("entry_price", 0)
        if entry_price <= 0:
            continue

        if p.get("status") == "exited" and p.get("exit_price"):
            exit_price = p["exit_price"]
            raw_return_pct = (exit_price - entry_price) / entry_price * 100
            net_return_pct = raw_return_pct - _TOTAL_COST_PCT
            hit_sl = p.get("exit_reason") == "止损"
            hit_tp = p.get("exit_reason") == "止盈"

            record = {
                "rec_date": score_date,
                "strategy": strategy,
                "code": code,
                "name": p.get("name", ""),
                "entry_price": entry_price,
                "next_open": exit_price,
                "next_close": exit_price,
                "next_high": exit_price,
                "next_low": exit_price,
                "raw_return_pct": round(raw_return_pct, 2),
                "net_return_pct": round(net_return_pct, 2),
                "hit_stop_loss": hit_sl,
                "hit_take_profit": hit_tp,
                "result": "win" if net_return_pct > 0 else "loss",
            }
        else:
            ohlc = _fetch_next_day_ohlc(code, score_date)
            if not ohlc:
                logger.warning("%s %s 次日(%s)数据获取失败, 跳过", code, p.get("name", ""), yesterday)
                continue

            time.sleep(0.3)

            next_open = ohlc["open"]
            next_close = ohlc["close"]
            next_high = ohlc["high"]
            next_low = ohlc["low"]

            stop_loss_price = entry_price * (1 + STOP_LOSS_PCT / 100)
            take_profit_price = entry_price * (1 + TAKE_PROFIT_PCT / 100)
            hit_sl = next_low <= stop_loss_price
            hit_tp = next_high >= take_profit_price

            raw_return_pct = (next_close - entry_price) / entry_price * 100
            net_return_pct = raw_return_pct - _TOTAL_COST_PCT

            record = {
                "rec_date": score_date,
                "strategy": strategy,
                "code": code,
                "name": p.get("name", ""),
                "entry_price": entry_price,
                "next_open": next_open,
                "next_close": next_close,
                "next_high": next_high,
                "next_low": next_low,
                "raw_return_pct": round(raw_return_pct, 2),
                "net_return_pct": round(net_return_pct, 2),
                "hit_stop_loss": hit_sl,
                "hit_take_profit": hit_tp,
                "result": "win" if net_return_pct > 0 else "loss",
            }

        new_scores.append(record)
        existing_keys.add(key)

        tag = "+" if record["net_return_pct"] > 0 else ""
        sl_tag = " [触发止损]" if record["hit_stop_loss"] else ""
        tp_tag = " [触发止盈]" if record["hit_take_profit"] else ""
        logger.info("%s %s (%s): %s%.1f%% (%s)%s%s",
                    code, record["name"], strategy,
                    tag, record["net_return_pct"], record["result"],
                    sl_tag, tp_tag)

    if new_scores:
        save_scorecard_records(new_scores)
        wins = sum(1 for s in new_scores if s["result"] == "win")
        losses = len(new_scores) - wins
        logger.info("%s 评分完成: %d 只 (%d胜%d负)", score_date, len(new_scores), wins, losses)
    else:
        logger.info("%s 无新增评分记录", score_date)

    return new_scores


# ================================================================
#  累计统计
# ================================================================

def calc_cumulative_stats(days: int | None = None) -> dict:
    """累计统计: 总推荐数, 胜率, 平均收益, 分策略明细"""
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        records = load_scorecard(days=days)
    except Exception:
        records = safe_load_strict(_SCORECARD_PATH)
    # 排除 ML 回测填充数据, 只统计真实交易信号
    records = [r for r in records if r.get("strategy") != "ml_backfill"]
    if not records:
        return {
            "total": 0, "win_rate": 0,
            "avg_raw_return": 0, "avg_net_return": 0,
            "by_strategy": {},
        }

    total = len(records)
    wins = sum(1 for r in records if r.get("result") == "win")
    win_rate = wins / total * 100 if total > 0 else 0
    avg_raw = sum(r.get("raw_return_pct", 0) for r in records) / total if total > 0 else 0
    avg_net = sum(r.get("net_return_pct", 0) for r in records) / total if total > 0 else 0

    by_strategy = defaultdict(lambda: {"total": 0, "wins": 0, "raw_sum": 0, "net_sum": 0})
    for r in records:
        s = r.get("strategy", "未知")
        by_strategy[s]["total"] += 1
        if r.get("result") == "win":
            by_strategy[s]["wins"] += 1
        by_strategy[s]["raw_sum"] += r.get("raw_return_pct", 0)
        by_strategy[s]["net_sum"] += r.get("net_return_pct", 0)

    strategy_stats = {}
    for s, d in by_strategy.items():
        strategy_stats[s] = {
            "total": d["total"],
            "wins": d["wins"],
            "win_rate": d["wins"] / d["total"] * 100 if d["total"] > 0 else 0,
            "avg_raw_return": d["raw_sum"] / d["total"] if d["total"] > 0 else 0,
            "avg_net_return": d["net_sum"] / d["total"] if d["total"] > 0 else 0,
        }

    return {
        "total": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(win_rate, 1),
        "avg_raw_return": round(avg_raw, 2),
        "avg_net_return": round(avg_net, 2),
        "by_strategy": strategy_stats,
    }


# ================================================================
#  资金曲线 (Equity Curve)
# ================================================================

def calc_equity_curve(days: int | None = None) -> dict:
    """计算资金曲线指标

    返回:
      nav_series: [(date, nav)] 按日聚合的净值序列 (初始=1.0)
      total_return: 累计收益率 (%)
      max_drawdown: 最大回撤 (%)
      sharpe: 年化 Sharpe (无风险利率=2%)
      daily_returns: [float] 每日平均收益率序列
    """
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        records = load_scorecard(days=days)
    except Exception:
        records = safe_load_strict(_SCORECARD_PATH)
    # 排除 ML 回测填充数据
    records = [r for r in records if r.get("strategy") != "ml_backfill"]
    if not records:
        return {"nav_series": [], "total_return": 0, "max_drawdown": 0,
                "sharpe": 0, "daily_returns": []}

    # 按日期聚合: 每日所有推荐的平均净收益
    daily_agg = defaultdict(list)
    for r in records:
        daily_agg[r.get("rec_date", "")].append(r.get("net_return_pct", 0))

    sorted_dates = sorted(daily_agg.keys())
    daily_returns = []
    nav_series = []
    nav = 1.0

    for d in sorted_dates:
        rets = daily_agg[d]
        avg_ret = sum(rets) / len(rets)
        daily_returns.append(avg_ret)
        nav *= (1 + avg_ret / 100)
        nav_series.append((d, round(nav, 4)))

    total_return = (nav - 1) * 100

    # 最大回撤
    peak = 0
    max_dd = 0
    for _, n in nav_series:
        if n > peak:
            peak = n
        dd = (peak - n) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe (年化, 无风险=2%)
    sharpe = 0
    if len(daily_returns) >= 5:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns))
        if std_r > 0:
            rf_daily = 2.0 / 252  # 无风险日利率
            sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252)

    return {
        "nav_series": nav_series,
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "daily_returns": daily_returns,
    }


def _render_nav_sparkline(nav_series: list[tuple], width: int = 30) -> str:
    """用文本字符绘制简易净值曲线"""
    if len(nav_series) < 2:
        return "(数据不足)"

    values = [n for _, n in nav_series]
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else 0.001

    blocks = " ▁▂▃▄▅▆▇█"
    # 如果数据点 > width, 采样
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    chars = []
    for v in sampled:
        idx = int((v - lo) / span * (len(blocks) - 1))
        chars.append(blocks[idx])

    return "".join(chars)


# ================================================================
#  周报生成
# ================================================================

def generate_weekly_report() -> str:
    """生成过去7天的周报 (Markdown格式, 含资金曲线)"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    today_str = today.isoformat()
    week_ago_str = week_ago.isoformat()

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        week_records = load_scorecard(days=7)
    except Exception:
        week_records = safe_load_strict(_SCORECARD_PATH)

    total = len(week_records)
    wins = sum(1 for r in week_records if r.get("result") == "win")
    losses = total - wins
    win_rate = wins / total * 100 if total > 0 else 0
    avg_raw = sum(r.get("raw_return_pct", 0) for r in week_records) / total if total > 0 else 0
    avg_net = sum(r.get("net_return_pct", 0) for r in week_records) / total if total > 0 else 0

    lines = [
        "## 每周实盘记分卡",
        f"**统计周期:** {week_ago_str} ~ {today_str}",
        "",
        "### 总览",
        f"- 推荐总数: {total} 只",
        f"- 胜率: {win_rate:.1f}% ({wins}胜{losses}负)",
        f"- 平均收益: {avg_raw:+.1f}% (扣费后 {avg_net:+.1f}%)",
        "",
    ]

    # 资金曲线指标
    eq = calc_equity_curve()
    if eq["nav_series"]:
        sparkline = _render_nav_sparkline(eq["nav_series"])
        lines.extend([
            "### 资金曲线",
            f"- 累计净值: {eq['nav_series'][-1][1]:.4f}",
            f"- 累计收益: {eq['total_return']:+.2f}%",
            f"- 最大回撤: {eq['max_drawdown']:.2f}%",
            f"- Sharpe: {eq['sharpe']:.2f}",
            f"- 走势: `{sparkline}`",
            "",
        ])

    # 分策略表现
    by_strategy = defaultdict(lambda: {"total": 0, "wins": 0, "net_sum": 0})
    for r in week_records:
        s = r.get("strategy", "未知")
        by_strategy[s]["total"] += 1
        if r.get("result") == "win":
            by_strategy[s]["wins"] += 1
        by_strategy[s]["net_sum"] += r.get("net_return_pct", 0)

    if by_strategy:
        lines.append("### 分策略表现")
        lines.append("| 策略 | 推荐数 | 胜率 | 平均收益 |")
        lines.append("|------|--------|------|----------|")
        for s, d in by_strategy.items():
            wr = d["wins"] / d["total"] * 100 if d["total"] > 0 else 0
            avg = d["net_sum"] / d["total"] if d["total"] > 0 else 0
            lines.append(f"| {s} | {d['total']} | {wr:.0f}% | {avg:+.1f}% |")
        lines.append("")

    if week_records:
        sorted_by_return = sorted(week_records, key=lambda x: x.get("net_return_pct", 0))
        best = sorted_by_return[-1]
        worst = sorted_by_return[0]
        lines.append("### 最佳/最差推荐")
        lines.append(
            f"- 最佳: {best.get('code', '')} {best.get('name', '')} "
            f"{best.get('net_return_pct', 0):+.1f}% "
            f"({best.get('strategy', '')} {best.get('rec_date', '')})"
        )
        lines.append(
            f"- 最差: {worst.get('code', '')} {worst.get('name', '')} "
            f"{worst.get('net_return_pct', 0):+.1f}% "
            f"({worst.get('strategy', '')} {worst.get('rec_date', '')})"
        )

    # 信号追踪多周期验证 (T+1/T+3/T+5)
    try:
        from signal_tracker import get_stats
        sig_stats = get_stats(days=7)
        if sig_stats.get("total", 0) > 0:
            o = sig_stats["overall"]
            lines.append("")
            lines.append("### 信号多周期验证")
            lines.append("| 周期 | 胜率 | 平均收益 |")
            lines.append("|------|------|---------|")
            for p in [1, 3, 5]:
                wr = o.get(f"t{p}_win_rate")
                avg = o.get(f"avg_t{p}")
                wr_s = f"{wr}%" if wr is not None else "—"
                avg_s = f"{avg:+.2f}%" if avg is not None else "—"
                lines.append(f"| T+{p} | {wr_s} | {avg_s} |")

            # 策略排行 (按 T+1 胜率)
            by_strat = sig_stats.get("by_strategy", {})
            if by_strat:
                ranked = sorted(by_strat.items(),
                                key=lambda x: x[1].get("t1_win_rate") or 0,
                                reverse=True)
                lines.append("")
                lines.append("**策略排行 (T+1胜率):**")
                for name, info in ranked:
                    t1wr = info.get("t1_win_rate")
                    if t1wr is not None:
                        lines.append(f"- {name}: {t1wr}% ({info['total']}条)")
    except Exception:
        pass

    # 系统健康摘要
    try:
        from self_healer import generate_health_report
        health = generate_health_report()
        if health:
            lines.append("")
            lines.append(health)
    except Exception:
        pass

    return "\n".join(lines)


# ================================================================
#  推送周报
# ================================================================

def notify_scorecard(report: str):
    """推送周报 (终端 + 微信)"""
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    try:
        from notifier import notify_wechat_raw
        notify_wechat_raw("每周实盘记分卡", report)
    except Exception as e:
        logger.error("微信推送失败: %s", e)


# ================================================================
#  CLI
# ================================================================

def _cli_stats(days: int | None = None):
    stats = calc_cumulative_stats(days)
    period = f"最近{days}天" if days else "全部"

    print(f"\n{'=' * 50}")
    print(f"  累计统计 ({period})")
    print(f"{'=' * 50}")
    print(f"  总推荐: {stats['total']} 只")

    if stats["total"] == 0:
        print("  暂无评分记录")
        return

    print(f"  胜率: {stats['win_rate']}% ({stats.get('wins', 0)}胜{stats.get('losses', 0)}负)")
    print(f"  平均收益: {stats['avg_raw_return']:+.2f}% (扣费后 {stats['avg_net_return']:+.2f}%)")

    if stats["by_strategy"]:
        print(f"\n  分策略:")
        for s, d in stats["by_strategy"].items():
            print(f"    {s}: {d['total']}只 胜率{d['win_rate']:.0f}% "
                  f"平均{d['avg_net_return']:+.2f}%")

    # 资金曲线
    eq = calc_equity_curve(days)
    if eq["nav_series"]:
        sparkline = _render_nav_sparkline(eq["nav_series"])
        print(f"\n  资金曲线:")
        print(f"    累计收益: {eq['total_return']:+.2f}%")
        print(f"    最大回撤: {eq['max_drawdown']:.2f}%")
        print(f"    Sharpe:   {eq['sharpe']:.2f}")
        print(f"    走势: {sparkline}")


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "score":
        score_yesterday()
    elif mode == "stats":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else None
        _cli_stats(days)
    elif mode == "weekly":
        report = generate_weekly_report()
        notify_scorecard(report)
    elif mode == "curve":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else None
        eq = calc_equity_curve(days)
        if not eq["nav_series"]:
            print("暂无评分数据, 无法生成资金曲线")
        else:
            sparkline = _render_nav_sparkline(eq["nav_series"])
            print(f"累计收益: {eq['total_return']:+.2f}%")
            print(f"最大回撤: {eq['max_drawdown']:.2f}%")
            print(f"Sharpe:   {eq['sharpe']:.2f}")
            print(f"走势: {sparkline}")
            print(f"\n日期          净值")
            for d, n in eq["nav_series"]:
                print(f"  {d}  {n:.4f}")
    else:
        print("用法:")
        print("  python3 scorecard.py score       # 对昨日推荐打分")
        print("  python3 scorecard.py stats        # 查看累计统计")
        print("  python3 scorecard.py stats 30     # 最近30天")
        print("  python3 scorecard.py weekly       # 生成并推送周报")
        print("  python3 scorecard.py curve        # 查看资金曲线")
        print("  python3 scorecard.py curve 30     # 最近30天资金曲线")
        sys.exit(1)
