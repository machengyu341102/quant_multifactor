"""
信号追踪器 (Signal Tracker)
===========================
闭环验证: 信号生成 → T+1/T+3/T+5 结果回查 → 按策略/regime/因子统计命中率

解决的核心问题:
  - trade_journal 有丰富的信号上下文 (regime/factor_scores)
  - scorecard 有 T+1 结果
  - 但两者没有关联, 学习引擎半盲调参
  - 本模块把信号上下文 + 多周期结果串起来, 形成完整闭环

数据文件:
  signals_db.json — 信号数据库 (自动生成, 每条信号含上下文+验证结果)

用法:
  python3 signal_tracker.py ingest     # 从 trade_journal 导入今日信号
  python3 signal_tracker.py verify     # 回查 T+1/T+3/T+5 结果
  python3 signal_tracker.py report     # 信号质量报告
  python3 signal_tracker.py stats      # 快速统计
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("signal_tracker")

_DIR = os.path.dirname(os.path.abspath(__file__))
_SIGNALS_DB_PATH = os.path.join(_DIR, "signals_db.json")
_JOURNAL_PATH = os.path.join(_DIR, "trade_journal.json")

# 验证周期: T+1, T+3, T+5
VERIFY_PERIODS = [1, 3, 5]


# ================================================================
#  交易日工具 (复用 scorecard 的逻辑)
# ================================================================

_trade_dates_cache: set[str] | None = None


def _get_trading_dates() -> set[str]:
    global _trade_dates_cache
    if _trade_dates_cache is not None:
        return _trade_dates_cache
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        _trade_dates_cache = set(df[col].astype(str).str[:10].tolist())
    except Exception:
        _trade_dates_cache = set()
    return _trade_dates_cache


def _nth_trading_day_after(from_date: str, n: int) -> str | None:
    """找 from_date 之后的第 n 个交易日"""
    trade_dates = _get_trading_dates()
    if trade_dates:
        future = sorted(d for d in trade_dates if d > from_date)
        return future[n - 1] if len(future) >= n else None
    # fallback: 跳过周末
    d = datetime.strptime(from_date, "%Y-%m-%d").date()
    count = 0
    for i in range(1, n * 3):
        nxt = d + timedelta(days=i)
        if nxt.weekday() < 5:
            count += 1
            if count == n:
                return nxt.isoformat()
    return None


def _is_stock_code(code: str) -> bool:
    """判断是否为 A 股代码 (6位数字)"""
    return len(code) == 6 and code.isdigit()


# ================================================================
#  价格获取
# ================================================================

def _fetch_stock_close(code: str, target_date: str) -> float | None:
    """获取 A 股某日收盘价"""
    try:
        from api_guard import guarded_call
        import akshare as ak

        start = target_date.replace("-", "")
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
        end = (d + timedelta(days=5)).strftime("%Y%m%d")

        sym = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
        df = guarded_call(
            ak.stock_zh_a_hist_tx,
            symbol=sym, start_date=start, end_date=end, adjust="qfq",
            cache_key=f"signal_tracker_{code}",
            cache_ttl=300,
        )
        if df is None or df.empty:
            return None

        df["date_str"] = df["date"].astype(str).str[:10]
        row = df[df["date_str"] == target_date]
        if row.empty:
            row = df.head(1)
        return float(row.iloc[0]["close"])
    except Exception as e:
        logger.debug("获取 %s %s 收盘价失败: %s", code, target_date, e)
        return None


def _fetch_crypto_close(symbol: str, target_date: str) -> float | None:
    """获取币圈某日收盘价 (Binance)"""
    try:
        import requests
        pair = f"{symbol}USDT"
        ts = int(datetime.strptime(target_date, "%Y-%m-%d").timestamp() * 1000)
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": pair, "interval": "1d", "startTime": ts, "limit": 1}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data and len(data) > 0:
            return float(data[0][4])  # close
    except Exception as e:
        logger.debug("获取 %s %s 币价失败: %s", symbol, target_date, e)
    return None


def _fetch_us_close(symbol: str, target_date: str) -> float | None:
    """获取美股某日收盘价 (yfinance)"""
    try:
        import yfinance as yf
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
        end = d + timedelta(days=5)
        t = yf.Ticker(symbol)
        hist = t.history(start=d.isoformat(), end=end.isoformat())
        if hist is not None and not hist.empty:
            hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
            target = hist[hist.index.date == d]
            if not target.empty:
                return float(target.iloc[0]["Close"])
            return float(hist.iloc[0]["Close"])
    except Exception as e:
        logger.debug("获取 %s %s 美股价失败: %s", symbol, target_date, e)
    return None


def _fetch_futures_close(symbol: str, target_date: str) -> float | None:
    """获取期货某日收盘价 (akshare, 新浪主力连续)"""
    try:
        import akshare as ak
        sym = symbol.lower() + "0"  # e.g. FU→fu0 (主力连续)
        df = ak.futures_main_sina(symbol=sym)
        if df is None or df.empty:
            return None
        # 列名为中文: 日期/收盘价
        date_col = "日期" if "日期" in df.columns else "date"
        close_col = "收盘价" if "收盘价" in df.columns else "close"
        df["date_str"] = df[date_col].astype(str).str[:10]
        row = df[df["date_str"] == target_date]
        if not row.empty:
            return float(row.iloc[0][close_col])
        return None
    except Exception as e:
        logger.debug("获取 %s %s 期货价失败: %s", symbol, target_date, e)
    return None


def _fetch_close(code: str, target_date: str, strategy: str) -> float | None:
    """根据策略类型选择价格源"""
    if "币圈" in strategy or "crypto" in strategy.lower():
        return _fetch_crypto_close(code, target_date)
    elif "美股" in strategy or "us_stock" in strategy.lower():
        return _fetch_us_close(code, target_date)
    elif "期货" in strategy or "futures" in strategy.lower():
        return _fetch_futures_close(code, target_date)
    else:
        return _fetch_stock_close(code, target_date)


# ================================================================
#  信号入库
# ================================================================

def ingest_from_journal(target_date: str | None = None) -> int:
    """从 trade_journal.json 导入信号到 signals_db

    Args:
        target_date: 导入哪天的信号, 默认今天

    Returns:
        新增信号数
    """
    if target_date is None:
        target_date = date.today().isoformat()

    journal = safe_load(_JOURNAL_PATH, default=[])
    db = safe_load(_SIGNALS_DB_PATH, default=[])

    # 已有信号的 key 集合 (date+strategy+code 去重)
    existing_keys = set()
    for sig in db:
        key = f"{sig['date']}|{sig['strategy']}|{sig['code']}"
        existing_keys.add(key)

    added = 0
    for entry in journal:
        if entry.get("date") != target_date:
            continue

        strategy = entry.get("strategy", "")
        regime = entry.get("regime", {})

        for pick in entry.get("picks", []):
            code = pick.get("code", "")
            if not code:
                continue

            key = f"{target_date}|{strategy}|{code}"
            if key in existing_keys:
                continue

            signal = {
                "date": target_date,
                "strategy": strategy,
                "code": code,
                "name": pick.get("name", ""),
                "entry_price": pick.get("price", 0),
                "score": pick.get("total_score", 0),
                "factor_scores": pick.get("factor_scores", {}),
                "regime": regime.get("regime", "unknown"),
                "regime_score": regime.get("score", 0),
                "market_signals": regime.get("signals", {}),
                "direction": "long",  # 默认做多, 期货/币圈可做空
                "verify": {},  # T+1/T+3/T+5 验证结果
                "status": "pending",  # pending/partial/complete
            }

            # 从 reason 或 factor_scores 判断方向
            reason = pick.get("reason", "")
            if "做空" in reason or "short" in reason.lower():
                signal["direction"] = "short"

            db.append(signal)
            existing_keys.add(key)
            added += 1

    if added > 0:
        safe_save(_SIGNALS_DB_PATH, db)
        logger.info("信号入库: %s, 新增 %d 条", target_date, added)

    return added


# ================================================================
#  结果验证
# ================================================================

def verify_outcomes() -> dict:
    """回查所有 pending/partial 信号的 T+1/T+3/T+5 结果

    Returns:
        {"verified": int, "skipped": int, "completed": int}
    """
    db = safe_load(_SIGNALS_DB_PATH, default=[])
    if not db:
        return {"verified": 0, "skipped": 0, "completed": 0}

    today = date.today().isoformat()
    verified = 0
    skipped = 0
    completed = 0

    for sig in db:
        if sig["status"] == "complete":
            continue

        sig_date = sig["date"]
        entry_price = sig.get("entry_price", 0)
        if not entry_price or entry_price <= 0:
            continue

        strategy = sig.get("strategy", "")
        code = sig["code"]
        direction = sig.get("direction", "long")
        verify = sig.get("verify", {})
        any_new = False

        for period in VERIFY_PERIODS:
            t_key = f"t{period}"
            if t_key in verify:
                continue  # 已验证

            target_date = _nth_trading_day_after(sig_date, period)
            if not target_date or target_date > today:
                continue  # 还没到验证日

            close = _fetch_close(code, target_date, strategy)
            if close is None:
                skipped += 1
                continue

            if direction == "long":
                return_pct = (close - entry_price) / entry_price * 100
            else:
                return_pct = (entry_price - close) / entry_price * 100

            verify[t_key] = {
                "date": target_date,
                "close": round(close, 4),
                "return_pct": round(return_pct, 2),
                "result": "win" if return_pct > 0 else "loss",
            }
            any_new = True
            verified += 1

        if any_new:
            sig["verify"] = verify
            # 检查是否全部验证完成
            all_done = all(f"t{p}" in verify for p in VERIFY_PERIODS)
            if all_done:
                sig["status"] = "complete"
                completed += 1
            else:
                sig["status"] = "partial"

    safe_save(_SIGNALS_DB_PATH, db)

    # T+1 结果写入 scorecard.json, 打通 agent_brain/learning_engine 闭环
    _sync_to_scorecard(db)

    logger.info("信号验证: 新增 %d 条, 跳过 %d, 完成 %d", verified, skipped, completed)
    return {"verified": verified, "skipped": skipped, "completed": completed}


_SCORECARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scorecard.json")


def _sync_to_scorecard(signals: list):
    """将已验证 T+1 的信号同步到 scorecard.json (agent_brain/learning_engine 数据源)"""
    scorecard = safe_load(_SCORECARD_PATH, default=[])
    existing_keys = {(r.get("rec_date"), r.get("code"), r.get("strategy"))
                     for r in scorecard}

    new_entries = 0
    for sig in signals:
        t1 = sig.get("verify", {}).get("t1")
        if not t1:
            continue
        key = (sig["date"], sig["code"], sig.get("strategy", ""))
        if key in existing_keys:
            continue

        scorecard.append({
            "rec_date": sig["date"],
            "code": sig["code"],
            "name": sig.get("name", ""),
            "strategy": sig.get("strategy", ""),
            "score": sig.get("score", 0),
            "entry_price": sig.get("entry_price", 0),
            "exit_price": t1["close"],
            "net_return_pct": t1["return_pct"],
            "result": t1["result"],
            "regime": sig.get("regime", "unknown"),
            "factor_scores": sig.get("factor_scores", {}),
            "verify_date": t1["date"],
        })
        new_entries += 1

    if new_entries:
        safe_save(_SCORECARD_PATH, scorecard)
        logger.info("scorecard 同步: 新增 %d 条 (总 %d)", new_entries, len(scorecard))


# ================================================================
#  统计分析
# ================================================================

def get_stats(days: int = 30) -> dict:
    """信号质量统计

    Returns:
        {
            "total": int,
            "by_strategy": {strategy: {total, t1_win_rate, t3_win_rate, t5_win_rate, avg_t1, avg_t3, avg_t5}},
            "by_regime": {regime: {total, t1_win_rate, ...}},
            "by_score_band": {"high/mid/low": {total, t1_win_rate, ...}},
            "overall": {t1_win_rate, t3_win_rate, t5_win_rate, avg_t1, avg_t3, avg_t5},
        }
    """
    db = safe_load(_SIGNALS_DB_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    signals = [s for s in db if s["date"] >= cutoff and s.get("verify")]

    if not signals:
        return {"total": 0, "by_strategy": {}, "by_regime": {},
                "by_score_band": {}, "overall": {}}

    def _calc_group(group: list[dict]) -> dict:
        """计算一组信号的统计"""
        result = {"total": len(group)}
        for period in VERIFY_PERIODS:
            t_key = f"t{period}"
            verified = [s for s in group if t_key in s.get("verify", {})]
            if not verified:
                result[f"t{period}_win_rate"] = None
                result[f"avg_t{period}"] = None
                continue
            wins = sum(1 for s in verified if s["verify"][t_key]["result"] == "win")
            returns = [s["verify"][t_key]["return_pct"] for s in verified]
            result[f"t{period}_win_rate"] = round(wins / len(verified) * 100, 1)
            result[f"avg_t{period}"] = round(sum(returns) / len(returns), 2)
        return result

    # 总体
    overall = _calc_group(signals)

    # 按策略
    by_strategy = defaultdict(list)
    for s in signals:
        by_strategy[s["strategy"]].append(s)
    by_strategy = {k: _calc_group(v) for k, v in by_strategy.items()}

    # 按 regime
    by_regime = defaultdict(list)
    for s in signals:
        by_regime[s.get("regime", "unknown")].append(s)
    by_regime = {k: _calc_group(v) for k, v in by_regime.items()}

    # 按分数段
    by_score_band = {"high": [], "mid": [], "low": []}
    for s in signals:
        score = s.get("score", 0)
        if score >= 0.7:
            by_score_band["high"].append(s)
        elif score >= 0.5:
            by_score_band["mid"].append(s)
        else:
            by_score_band["low"].append(s)
    by_score_band = {k: _calc_group(v) for k, v in by_score_band.items() if v}

    return {
        "total": len(signals),
        "by_strategy": dict(by_strategy),
        "by_regime": dict(by_regime),
        "by_score_band": by_score_band,
        "overall": overall,
    }


def get_factor_effectiveness(days: int = 30) -> dict:
    """分析哪些因子最能预测 T+1 胜负

    Returns:
        {factor_name: {win_avg, loss_avg, spread, predictive}}
    """
    db = safe_load(_SIGNALS_DB_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    signals = [s for s in db if s["date"] >= cutoff
               and "t1" in s.get("verify", {})
               and s.get("factor_scores")]

    if len(signals) < 10:
        return {}

    # 收集所有因子名
    all_factors = set()
    for s in signals:
        all_factors.update(s["factor_scores"].keys())

    result = {}
    for factor in all_factors:
        wins = [s["factor_scores"][factor] for s in signals
                if factor in s["factor_scores"]
                and s["verify"]["t1"]["result"] == "win"]
        losses = [s["factor_scores"][factor] for s in signals
                  if factor in s["factor_scores"]
                  and s["verify"]["t1"]["result"] == "loss"]

        if not wins or not losses:
            continue

        win_avg = sum(wins) / len(wins)
        loss_avg = sum(losses) / len(losses)
        spread = win_avg - loss_avg

        result[factor] = {
            "win_avg": round(win_avg, 4),
            "loss_avg": round(loss_avg, 4),
            "spread": round(spread, 4),
            "predictive": abs(spread) > 0.05,
            "win_count": len(wins),
            "loss_count": len(losses),
        }

    # 按 spread 绝对值排序
    result = dict(sorted(result.items(), key=lambda x: abs(x[1]["spread"]), reverse=True))
    return result


def get_regime_strategy_matrix(days: int = 30) -> dict:
    """策略 × 市场环境 胜率矩阵

    Returns:
        {strategy: {regime: t1_win_rate}}
    """
    db = safe_load(_SIGNALS_DB_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    signals = [s for s in db if s["date"] >= cutoff and "t1" in s.get("verify", {})]

    matrix = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0}))
    for s in signals:
        strategy = s["strategy"]
        regime = s.get("regime", "unknown")
        cell = matrix[strategy][regime]
        cell["total"] += 1
        if s["verify"]["t1"]["result"] == "win":
            cell["wins"] += 1

    result = {}
    for strategy, regimes in matrix.items():
        result[strategy] = {}
        for regime, counts in regimes.items():
            rate = counts["wins"] / counts["total"] * 100 if counts["total"] > 0 else 0
            result[strategy][regime] = {
                "win_rate": round(rate, 1),
                "total": counts["total"],
            }

    return result


def get_feedback_for_learning() -> dict:
    """为 learning_engine 提供反馈数据

    Returns:
        {
            "factor_adjustments": {factor: suggested_delta},
            "strategy_regime_fit": {strategy: {best_regime, worst_regime}},
            "signal_decay": {strategy: {t1_vs_t5_spread}},
        }
    """
    stats = get_stats(days=30)
    factors = get_factor_effectiveness(days=30)
    matrix = get_regime_strategy_matrix(days=30)

    # 因子权重建议
    factor_adjustments = {}
    for name, info in factors.items():
        if info["predictive"]:
            # spread > 0 说明该因子高分时胜率高, 应提高权重
            delta = round(info["spread"] * 0.1, 4)  # 保守调整
            factor_adjustments[name] = delta

    # 策略-环境适配
    strategy_regime_fit = {}
    for strategy, regimes in matrix.items():
        if not regimes:
            continue
        best = max(regimes.items(), key=lambda x: x[1]["win_rate"])
        worst = min(regimes.items(), key=lambda x: x[1]["win_rate"])
        if best[1]["total"] >= 3 and worst[1]["total"] >= 3:
            strategy_regime_fit[strategy] = {
                "best_regime": best[0],
                "best_win_rate": best[1]["win_rate"],
                "worst_regime": worst[0],
                "worst_win_rate": worst[1]["win_rate"],
            }

    # 信号衰减 (T+1 vs T+5)
    signal_decay = {}
    for strategy, info in stats.get("by_strategy", {}).items():
        t1 = info.get("avg_t1")
        t5 = info.get("avg_t5")
        if t1 is not None and t5 is not None:
            signal_decay[strategy] = {
                "avg_t1": t1,
                "avg_t5": t5,
                "decay": round(t1 - t5, 2),
                "fast_decay": (t1 - t5) > 1.0,  # T+1 比 T+5 好超过1%
            }

    return {
        "factor_adjustments": factor_adjustments,
        "strategy_regime_fit": strategy_regime_fit,
        "signal_decay": signal_decay,
    }


# ================================================================
#  报告
# ================================================================

def generate_signal_report(days: int = 30) -> str:
    """生成信号质量报告 (Markdown, 随周报推送)"""
    stats = get_stats(days)
    factors = get_factor_effectiveness(days)
    matrix = get_regime_strategy_matrix(days)

    lines = [f"## 信号质量报告 (近{days}天)"]

    if stats["total"] == 0:
        lines.append("\n暂无验证数据")
        return "\n".join(lines)

    # 总体
    o = stats["overall"]
    lines.append(f"\n### 总体 ({o['total']} 条信号)")
    lines.append("| 周期 | 胜率 | 平均收益 |")
    lines.append("|------|------|---------|")
    for p in VERIFY_PERIODS:
        wr = o.get(f"t{p}_win_rate")
        avg = o.get(f"avg_t{p}")
        wr_str = f"{wr}%" if wr is not None else "—"
        avg_str = f"{avg:+.2f}%" if avg is not None else "—"
        lines.append(f"| T+{p} | {wr_str} | {avg_str} |")

    # 按策略
    if stats["by_strategy"]:
        lines.append("\n### 按策略")
        lines.append("| 策略 | 信号数 | T+1胜率 | T+1均收 | T+3胜率 | T+5胜率 |")
        lines.append("|------|--------|---------|---------|---------|---------|")
        for name, info in sorted(stats["by_strategy"].items(),
                                 key=lambda x: x[1].get("t1_win_rate") or 0,
                                 reverse=True):
            t1wr = f"{info['t1_win_rate']}%" if info.get("t1_win_rate") is not None else "—"
            t1avg = f"{info['avg_t1']:+.2f}%" if info.get("avg_t1") is not None else "—"
            t3wr = f"{info['t3_win_rate']}%" if info.get("t3_win_rate") is not None else "—"
            t5wr = f"{info['t5_win_rate']}%" if info.get("t5_win_rate") is not None else "—"
            lines.append(f"| {name} | {info['total']} | {t1wr} | {t1avg} | {t3wr} | {t5wr} |")

    # 按环境
    if stats["by_regime"]:
        lines.append("\n### 按市场环境")
        lines.append("| 环境 | 信号数 | T+1胜率 | T+1均收 |")
        lines.append("|------|--------|---------|---------|")
        for regime, info in stats["by_regime"].items():
            t1wr = f"{info['t1_win_rate']}%" if info.get("t1_win_rate") is not None else "—"
            t1avg = f"{info['avg_t1']:+.2f}%" if info.get("avg_t1") is not None else "—"
            lines.append(f"| {regime} | {info['total']} | {t1wr} | {t1avg} |")

    # 按分数段
    if stats["by_score_band"]:
        lines.append("\n### 按信号强度")
        lines.append("| 强度 | 信号数 | T+1胜率 | T+1均收 |")
        lines.append("|------|--------|---------|---------|")
        for band in ["high", "mid", "low"]:
            if band not in stats["by_score_band"]:
                continue
            info = stats["by_score_band"][band]
            label = {"high": "强 (≥0.7)", "mid": "中 (0.5-0.7)", "low": "弱 (<0.5)"}[band]
            t1wr = f"{info['t1_win_rate']}%" if info.get("t1_win_rate") is not None else "—"
            t1avg = f"{info['avg_t1']:+.2f}%" if info.get("avg_t1") is not None else "—"
            lines.append(f"| {label} | {info['total']} | {t1wr} | {t1avg} |")

    # 因子有效性 TOP5
    if factors:
        lines.append("\n### 因子有效性 TOP5")
        lines.append("| 因子 | 赢均值 | 输均值 | 差值 | 预测力 |")
        lines.append("|------|--------|--------|------|--------|")
        for i, (name, info) in enumerate(factors.items()):
            if i >= 5:
                break
            pred = "强" if info["predictive"] else "弱"
            lines.append(f"| {name} | {info['win_avg']:.3f} | "
                         f"{info['loss_avg']:.3f} | {info['spread']:+.3f} | {pred} |")

    # 策略×环境矩阵
    if matrix:
        regimes = set()
        for _, r in matrix.items():
            regimes.update(r.keys())
        regimes = sorted(regimes)

        if regimes:
            lines.append("\n### 策略×环境胜率矩阵")
            header = "| 策略 | " + " | ".join(regimes) + " |"
            lines.append(header)
            lines.append("|" + "------|" * (len(regimes) + 1))
            for strategy in sorted(matrix.keys()):
                cells = []
                for r in regimes:
                    info = matrix[strategy].get(r)
                    if info and info["total"] >= 2:
                        cells.append(f"{info['win_rate']}% ({info['total']})")
                    else:
                        cells.append("—")
                lines.append(f"| {strategy} | " + " | ".join(cells) + " |")

    return "\n".join(lines)


# ================================================================
#  每日任务 (scheduler 调用)
# ================================================================

def daily_ingest_and_verify() -> dict:
    """每日定时任务: 入库今日信号 + 回查历史信号结果

    Returns:
        {"ingested": int, "verify_result": dict, "stats_summary": str}
    """
    ingested = ingest_from_journal()
    verify_result = verify_outcomes()

    # 简短统计
    stats = get_stats(days=7)
    overall = stats.get("overall", {})
    t1wr = overall.get("t1_win_rate")
    summary = f"入库{ingested}条, 验证{verify_result['verified']}条"
    if t1wr is not None:
        summary += f", 近7天T+1胜率{t1wr}%"

    logger.info("信号追踪日任务: %s", summary)
    return {"ingested": ingested, "verify_result": verify_result, "stats_summary": summary}


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "ingest":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        n = ingest_from_journal(target)
        print(f"导入 {n} 条信号")

    elif mode == "verify":
        result = verify_outcomes()
        print(f"验证: {result}")

    elif mode == "report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print(generate_signal_report(days))

    elif mode == "stats":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        import json
        stats = get_stats(days)
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif mode == "factors":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        import json
        factors = get_factor_effectiveness(days)
        print(json.dumps(factors, ensure_ascii=False, indent=2))

    elif mode == "feedback":
        import json
        fb = get_feedback_for_learning()
        print(json.dumps(fb, ensure_ascii=False, indent=2))

    elif mode == "daily":
        result = daily_ingest_and_verify()
        print(result["stats_summary"])

    else:
        print("用法:")
        print("  python3 signal_tracker.py ingest     # 导入今日信号")
        print("  python3 signal_tracker.py verify     # 回查结果")
        print("  python3 signal_tracker.py report     # 信号质量报告")
        print("  python3 signal_tracker.py stats      # 统计 JSON")
        print("  python3 signal_tracker.py factors    # 因子有效性")
        print("  python3 signal_tracker.py feedback   # 学习反馈数据")
        print("  python3 signal_tracker.py daily      # 每日定时任务")
        sys.exit(1)
