"""
自学习引擎
==========
闭合 做→记→评→调→报 的学习闭环:
  1. 记 — record_trade_context(): 每次策略推荐后记录完整上下文
  2. 评 — analyze_signal_accuracy() / analyze_factor_importance() / analyze_strategy_regime_fit()
  3. 调 — propose_signal_weight_update(): 根据预测力调整信号权重
  4. 报 — generate_learning_report(): Markdown 格式推送微信
  5. 主循环 — run_learning_cycle(): 串联全部步骤

数据文件:
  trade_journal.json    — 交易上下文日志 (输入侧)
  tunable_params.json   — 调优后参数 (输出侧, 与 auto_optimizer 共用)
  evolution_history.json — 演化审计日志 (与 auto_optimizer 共用)
  scorecard.json        — 实盘记分卡 (只读)

用法:
  python3 learning_engine.py           # 运行学习周期
  python3 learning_engine.py report    # 仅生成报告
  python3 learning_engine.py analyze   # 仅分析 (不调参)
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    LEARNING_ENGINE_PARAMS,
    MARKET_SIGNAL_WEIGHTS,
)
from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("learning")

_DIR = os.path.dirname(os.path.abspath(__file__))
_JOURNAL_PATH = os.path.join(_DIR, "trade_journal.json")
_JOURNAL_DEFAULT = _JOURNAL_PATH
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_SCORECARD_DEFAULT = _SCORECARD_PATH
_TUNABLE_PATH = os.path.join(_DIR, "tunable_params.json")
_EVOLUTION_PATH = os.path.join(_DIR, "evolution_history.json")


# ================================================================
#  1. 记 — record_trade_context
# ================================================================

def record_trade_context(strategy: str, items: list[dict],
                         regime_result: dict | None = None):
    """每次策略推荐后调用, 将完整上下文存入 trade_journal.json

    Args:
        strategy: 策略名称 (如 "集合竞价选股")
        items: 推荐列表, 每项含 code/name/price/score, 可选 factor_scores
        regime_result: detect_market_regime() 返回的完整结果
    """
    if not LEARNING_ENGINE_PARAMS.get("learning_enabled", True):
        return

    if not items:
        return

    today_str = date.today().isoformat()

    # 构建记录
    picks = []
    for it in items:
        code = it.get("code", "")
        if not code or code == "ERROR":
            continue
        picks.append({
            "code": code,
            "name": it.get("name", ""),
            "price": it.get("price", 0),
            "total_score": it.get("score", 0),
            "factor_scores": it.get("factor_scores", {}),
        })

    if not picks:
        return

    regime_info = {}
    if regime_result:
        regime_info = {
            "regime": regime_result.get("regime", "unknown"),
            "score": regime_result.get("score", 0),
            "signals": regime_result.get("signals", {}),
            "signal_weights": regime_result.get("signal_weights", {}),
        }

    entry = {
        "date": today_str,
        "strategy": strategy,
        "regime": regime_info,
        "picks": picks,
    }

    # 写入 SQLite (UNIQUE 自动去重), 降级到 JSON
    try:
        if _JOURNAL_PATH != _JOURNAL_DEFAULT:
            raise ImportError("test mode")
        from db_store import save_trade_journal_entry
        if save_trade_journal_entry(entry):
            logger.info("trade_journal 记录 (SQLite): %s %s (%d picks)", today_str, strategy, len(picks))
        else:
            logger.info("trade_journal 已存在 %s %s, 跳过", today_str, strategy)
        return
    except ImportError:
        pass

    journal = safe_load(_JOURNAL_PATH, default=[])
    for existing in journal:
        if existing.get("date") == today_str and existing.get("strategy") == strategy:
            logger.info("trade_journal 已存在 %s %s, 跳过", today_str, strategy)
            return
    journal.append(entry)
    safe_save(_JOURNAL_PATH, journal)
    logger.info("trade_journal 记录: %s %s (%d picks)", today_str, strategy, len(picks))


# ================================================================
#  2. 评 — 核心关联 + 三个分析函数
# ================================================================

def _join_journal_scorecard(lookback_days: int = 30) -> list[dict]:
    """将 trade_journal (输入上下文) JOIN scorecard (输出结果)

    V4.0: 优先从 DB scorecard 穿透提取 (10万+量级),
    回退到 journal+scorecard 关联路径.

    关联键: (date, code, strategy)
    返回: [{signals, factor_scores, net_return_pct, regime, strategy, ...}]
    """
    # === V4.0 穿透式: 直接从 DB scorecard 提取 ===
    db_result = _join_scorecard_direct(lookback_days)
    if db_result and len(db_result) >= 20:
        logger.info("[学习] V4穿透: %d 条 (lookback=%s)",
                    len(db_result), lookback_days or "全量")
        return db_result

    # === 回退: journal + scorecard 关联 ===
    logger.info("[学习] DB穿透不足, 回退 journal 关联")
    return _join_journal_scorecard_legacy(lookback_days)


def _join_scorecard_direct(lookback_days: int = None) -> list[dict] | None:
    """V4.0 穿透式: 直接从 SQLite scorecard 提取因子+收益数据

    从 scorecard 读取 factor_scores + 收益, 并从 trade_journal 补充 regime signals.
    支持 lookback_days=None 全量读取 (大周期重训).
    """
    import sqlite3
    import json as _json
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            return None  # test mode
        from db_store import _DB_PATH
    except Exception:
        _db = os.path.join(_DIR, "quant_data.db")
        if not os.path.exists(_db):
            return None
        _DB_PATH = _db

    import time as _time
    raw = None
    for _attempt in range(3):
        try:
            conn = sqlite3.connect(_DB_PATH, timeout=10)
            where_parts = ["net_return_pct != 0",
                           "factor_scores IS NOT NULL",
                           "length(factor_scores) > 5"]
            params = []

            if lookback_days:
                cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
                where_parts.append("rec_date >= ?")
                params.append(cutoff)

            where = "WHERE " + " AND ".join(where_parts)
            sql = f"SELECT rec_date, code, strategy, factor_scores, net_return_pct, regime FROM scorecard {where}"
            import pandas as pd
            raw = pd.read_sql(sql, conn, params=params)
            conn.close()
            break
        except Exception as e:
            if _attempt < 2:
                _time.sleep(1)
                continue
            logger.warning("[学习] DB穿透读取失败(3次重试): %s", e)
            return None

    if raw.empty:
        return None

    # 从 trade_journal 补充 regime signals (按日期索引, 同日共享)
    signals_by_date = {}
    try:
        from db_store import load_trade_journal
        journal = load_trade_journal(days=lookback_days or 365)
        for entry in journal:
            d = entry.get("date", "")
            if d and d not in signals_by_date:
                regime_info = entry.get("regime", {})
                signals_by_date[d] = {
                    "signals": regime_info.get("signals", {}),
                    "signal_weights": regime_info.get("signal_weights", {}),
                    "regime_score": regime_info.get("score", 0),
                }
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    joined = []
    for _, rec in raw.iterrows():
        try:
            fs_raw = rec["factor_scores"]
            fs = _json.loads(fs_raw) if isinstance(fs_raw, str) else fs_raw
            if not isinstance(fs, dict) or not fs:
                continue

            d = rec["rec_date"]
            day_ctx = signals_by_date.get(d, {})

            joined.append({
                "date": d,
                "strategy": rec["strategy"],
                "code": rec["code"],
                "name": "",
                "total_score": 0,
                "factor_scores": fs,
                "signals": day_ctx.get("signals", {}),
                "signal_weights": day_ctx.get("signal_weights", {}),
                "regime": rec.get("regime") or "unknown",
                "regime_score": day_ctx.get("regime_score", 0),
                "net_return_pct": float(rec["net_return_pct"]),
                "result": "win" if float(rec["net_return_pct"]) > 0 else "lose",
            })
        except Exception:
            continue

    return joined if joined else None


def _join_journal_scorecard_legacy(lookback_days: int = 30) -> list[dict]:
    """旧路径: journal + scorecard 关联 (回退用)"""
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    try:
        if _JOURNAL_PATH != _JOURNAL_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_trade_journal
        journal = load_trade_journal(days=lookback_days)
    except Exception:
        journal = safe_load(_JOURNAL_PATH, default=[])
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=lookback_days)
    except Exception:
        scorecard = safe_load(_SCORECARD_PATH, default=[])

    sc_index = {}
    for rec in scorecard:
        key = (rec.get("rec_date", ""), rec.get("code", ""), rec.get("strategy", ""))
        sc_index[key] = rec

    joined = []
    for entry in journal:
        entry_date = entry.get("date", "")
        if entry_date < cutoff:
            continue
        strategy = entry.get("strategy", "")
        regime = entry.get("regime", {})
        signals = regime.get("signals", {})
        signal_weights = regime.get("signal_weights", {})

        for pick in entry.get("picks", []):
            code = pick.get("code", "")
            key = (entry_date, code, strategy)
            sc_rec = sc_index.get(key)
            if sc_rec is None:
                continue

            joined.append({
                "date": entry_date,
                "strategy": strategy,
                "code": code,
                "name": pick.get("name", ""),
                "total_score": pick.get("total_score", 0),
                "factor_scores": pick.get("factor_scores", {}),
                "signals": signals,
                "signal_weights": signal_weights,
                "regime": regime.get("regime", "unknown"),
                "regime_score": regime.get("score", 0),
                "net_return_pct": sc_rec.get("net_return_pct", 0),
                "result": sc_rec.get("result", ""),
            })

    return joined


def analyze_signal_accuracy(lookback_days: int = None) -> list[dict]:
    """分析 8 个大盘信号的预测力

    每个信号计算:
    - correlation: 与收益的 Pearson 相关系数
    - high_win_rate: 信号值 > 0.6 时的胜率
    - low_win_rate: 信号值 <= 0.4 时的胜率
    - predictive_value: abs(high_win_rate - low_win_rate) × 100

    返回: [{signal, correlation, high_win_rate, low_win_rate, predictive_value, samples}]
    """
    if lookback_days is None:
        lookback_days = LEARNING_ENGINE_PARAMS.get("lookback_days", 30)
    min_samples = LEARNING_ENGINE_PARAMS.get("min_samples_signal", 15)

    joined = _join_journal_scorecard(lookback_days)
    if not joined:
        return []

    # 收集所有信号名
    all_signals = set()
    for rec in joined:
        all_signals.update(rec.get("signals", {}).keys())

    results = []
    for sig_name in sorted(all_signals):
        sig_vals = []
        returns = []
        for rec in joined:
            val = rec.get("signals", {}).get(sig_name)
            if val is not None:
                sig_vals.append(float(val))
                returns.append(float(rec.get("net_return_pct", 0)))

        n = len(sig_vals)
        if n < min_samples:
            results.append({
                "signal": sig_name,
                "correlation": None,
                "high_win_rate": None,
                "low_win_rate": None,
                "predictive_value": None,
                "samples": n,
            })
            continue

        sig_arr = np.array(sig_vals)
        ret_arr = np.array(returns)

        # Pearson 相关
        std_s = np.std(sig_arr)
        std_r = np.std(ret_arr)
        if std_s > 0 and std_r > 0:
            corr = float(np.corrcoef(sig_arr, ret_arr)[0, 1])
        else:
            corr = 0.0

        # 高值胜率 (> 0.6)
        high_mask = sig_arr > 0.6
        high_count = int(high_mask.sum())
        if high_count > 0:
            high_win_rate = float((ret_arr[high_mask] > 0).sum() / high_count)
        else:
            high_win_rate = None

        # 低值胜率 (<= 0.4)
        low_mask = sig_arr <= 0.4
        low_count = int(low_mask.sum())
        if low_count > 0:
            low_win_rate = float((ret_arr[low_mask] > 0).sum() / low_count)
        else:
            low_win_rate = None

        # 预测力
        if high_win_rate is not None and low_win_rate is not None:
            predictive_value = abs(high_win_rate - low_win_rate) * 100
        else:
            predictive_value = None

        results.append({
            "signal": sig_name,
            "correlation": round(corr, 4),
            "high_win_rate": round(high_win_rate, 4) if high_win_rate is not None else None,
            "low_win_rate": round(low_win_rate, 4) if low_win_rate is not None else None,
            "predictive_value": round(predictive_value, 2) if predictive_value is not None else None,
            "samples": n,
        })

    return results


def analyze_factor_importance(strategy: str, lookback_days: int = None) -> list[dict]:
    """分析指定策略的选股因子重要性

    每个因子计算:
    - correlation: 与收益的 Pearson 相关系数
    - top25_return: 因子值 TOP25% 的平均收益
    - bottom25_return: 因子值 BOTTOM25% 的平均收益

    返回: [{factor, correlation, top25_return, bottom25_return, samples}]
    """
    if lookback_days is None:
        lookback_days = LEARNING_ENGINE_PARAMS.get("lookback_days", 30)
    min_samples = LEARNING_ENGINE_PARAMS.get("min_samples_factor", 10)

    joined = _join_journal_scorecard(lookback_days)
    # 按策略过滤
    joined = [r for r in joined if r.get("strategy") == strategy]

    if not joined:
        return []

    # 收集所有因子名
    all_factors = set()
    for rec in joined:
        all_factors.update(rec.get("factor_scores", {}).keys())

    results = []
    for factor in sorted(all_factors):
        factor_vals = []
        returns = []
        for rec in joined:
            val = rec.get("factor_scores", {}).get(factor)
            if val is not None:
                factor_vals.append(float(val))
                returns.append(float(rec.get("net_return_pct", 0)))

        n = len(factor_vals)
        if n < min_samples:
            results.append({
                "factor": factor,
                "correlation": None,
                "top25_return": None,
                "bottom25_return": None,
                "samples": n,
            })
            continue

        f_arr = np.array(factor_vals)
        r_arr = np.array(returns)

        # Pearson 相关
        std_f = np.std(f_arr)
        std_r = np.std(r_arr)
        if std_f > 0 and std_r > 0:
            corr = float(np.corrcoef(f_arr, r_arr)[0, 1])
        else:
            corr = 0.0

        # TOP25% / BOTTOM25% 收益
        threshold_high = np.percentile(f_arr, 75)
        threshold_low = np.percentile(f_arr, 25)

        top_mask = f_arr >= threshold_high
        bottom_mask = f_arr <= threshold_low

        top25_return = float(np.mean(r_arr[top_mask])) if top_mask.sum() > 0 else None
        bottom25_return = float(np.mean(r_arr[bottom_mask])) if bottom_mask.sum() > 0 else None

        results.append({
            "factor": factor,
            "correlation": round(corr, 4),
            "top25_return": round(top25_return, 4) if top25_return is not None else None,
            "bottom25_return": round(bottom25_return, 4) if bottom25_return is not None else None,
            "samples": n,
        })

    return results


def analyze_strategy_regime_fit(lookback_days: int = None) -> list[dict]:
    """分析策略在不同行情下的表现 (策略 × 行情交叉分析)

    返回: [{strategy, regime, win_rate, avg_return, samples}]
    """
    if lookback_days is None:
        lookback_days = LEARNING_ENGINE_PARAMS.get("lookback_days", 30)
    min_samples = LEARNING_ENGINE_PARAMS.get("min_samples_regime", 5)

    joined = _join_journal_scorecard(lookback_days)
    if not joined:
        return []

    # 按 (strategy, regime) 分组
    groups = {}
    for rec in joined:
        key = (rec.get("strategy", ""), rec.get("regime", "unknown"))
        if key not in groups:
            groups[key] = []
        groups[key].append(rec)

    results = []
    for (strategy, regime), recs in sorted(groups.items()):
        n = len(recs)
        if n < min_samples:
            results.append({
                "strategy": strategy,
                "regime": regime,
                "win_rate": None,
                "avg_return": None,
                "samples": n,
            })
            continue

        returns = [float(r.get("net_return_pct", 0)) for r in recs]
        wins = sum(1 for r in returns if r > 0)

        results.append({
            "strategy": strategy,
            "regime": regime,
            "win_rate": round(wins / n, 4),
            "avg_return": round(float(np.mean(returns)), 4),
            "samples": n,
        })

    return results


# ================================================================
#  3. 调 — propose_signal_weight_update
# ================================================================

def propose_signal_weight_update() -> dict | None:
    """根据信号预测力提出权重调整建议

    规则:
    - predictive_value 高于阈值 → 加权 (max +max_weight_delta)
    - predictive_value 低于阈值 → 减权 (max -max_weight_delta)
    - 下限 min_weight, 归一化至 sum=1.0

    返回: {"old_weights": {}, "new_weights": {}, "adjustments": {}} 或 None (无需调整)
    """
    params = LEARNING_ENGINE_PARAMS
    max_delta = params.get("max_weight_delta", 0.03)
    min_weight = params.get("min_weight", 0.03)
    threshold = params.get("predictive_threshold", 5.0)

    signal_analysis = analyze_signal_accuracy()
    if not signal_analysis:
        logger.info("信号分析无数据, 跳过权重调整")
        return None

    # 只考虑有足够数据的信号
    valid = [s for s in signal_analysis if s.get("predictive_value") is not None]
    if not valid:
        logger.info("无足够样本的信号, 跳过权重调整")
        return None

    # 读取当前权重
    tunable = safe_load(_TUNABLE_PATH, default={})
    current_weights = tunable.get("regime_signals", {}).get("weights", dict(MARKET_SIGNAL_WEIGHTS))

    new_weights = dict(current_weights)
    adjustments = {}

    for sig in valid:
        sig_name = sig["signal"]
        if sig_name not in current_weights:
            continue

        pv = sig["predictive_value"]
        old_w = current_weights[sig_name]

        if pv >= threshold:
            # 高预测力 → 加权
            delta = min(max_delta, (pv - threshold) / 100)
            new_w = old_w + delta
        else:
            # 低预测力 → 减权
            delta = -min(max_delta, (threshold - pv) / 100)
            new_w = old_w + delta

        new_w = max(min_weight, new_w)
        new_weights[sig_name] = new_w

        if abs(new_w - old_w) > 1e-6:
            adjustments[sig_name] = {
                "old": round(old_w, 4),
                "new": round(new_w, 4),
                "delta": round(new_w - old_w, 4),
                "predictive_value": pv,
            }

    if not adjustments:
        logger.info("权重无需调整")
        return None

    # 归一化至 sum=1.0
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: v / total for k, v in new_weights.items()}

    return {
        "old_weights": {k: round(v, 4) for k, v in current_weights.items()},
        "new_weights": {k: round(v, 4) for k, v in new_weights.items()},
        "adjustments": adjustments,
    }


def apply_weight_update(proposal: dict):
    """将权重调整应用到 tunable_params.json 和 evolution_history.json"""
    if not proposal:
        return

    new_weights = proposal["new_weights"]
    old_weights = proposal["old_weights"]

    # 写入 tunable_params.json
    tunable = safe_load(_TUNABLE_PATH, default={})
    existing = tunable.get("regime_signals", {})
    version = existing.get("version", 0) + 1

    tunable["regime_signals"] = {
        "weights": new_weights,
        "updated_at": date.today().isoformat(),
        "version": version,
        "previous_weights": old_weights,
    }
    safe_save(_TUNABLE_PATH, tunable)

    # 记录演化历史
    history = safe_load(_EVOLUTION_PATH, default=[])
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": "regime_signals",
        "action": "learning_update",
        "reason": "学习引擎基于信号预测力自动调整",
        "old_weights": old_weights,
        "new_weights": new_weights,
        "version": version,
        "adjustments": proposal.get("adjustments", {}),
    })
    safe_save(_EVOLUTION_PATH, history)

    logger.info("信号权重已更新至 v%d, 调整 %d 个信号", version, len(proposal.get("adjustments", {})))


# ================================================================
#  3b. 自主进化 — 从回测结果自动采纳最优参数
# ================================================================

def auto_adopt_backtest_results() -> list[dict]:
    """从夜班批量回测结果中自动采纳更优的参数

    规则:
    - 胜率提升 >= 2% 且 收益提升 >= 0.5% → 自动采纳
    - 采纳后记录到 evolution_history.json
    - 设置 5 天验证期 (复用 optimization_verifications)

    Returns:
        [{strategy, action, old_params, new_params, improvement}]
    """
    try:
        from batch_backtest import _RESULTS_PATH as bt_path
    except ImportError:
        return []

    results_history = safe_load(bt_path, default=[])
    if not results_history:
        return []

    # 取最近一次回测结果
    latest = results_history[-1]
    if not latest.get("recommendations"):
        logger.info("[自主进化] 无采纳建议")
        return []

    adopted = []
    for rec in latest["recommendations"]:
        if rec.get("action") != "adopt":
            continue

        strategy = rec.get("strategy", "")
        new_params = rec.get("params")
        if not strategy or not new_params:
            continue

        # 读取当前参数
        tunable = safe_load(_TUNABLE_PATH, default={})
        current = tunable.get(strategy, {})
        old_weights = current.get("weights", {})
        version = current.get("version", 0) + 1

        # 写入 tunable_params.json
        tunable[strategy] = {
            "weights": new_params,
            "updated_at": date.today().isoformat(),
            "version": version,
            "previous_weights": old_weights,
            "source": "night_backtest",
        }
        safe_save(_TUNABLE_PATH, tunable)

        # 记录演化历史
        history = safe_load(_EVOLUTION_PATH, default=[])
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": strategy,
            "action": "auto_adopt_backtest",
            "reason": f"夜班回测发现更优参数: {rec.get('reason', '')}",
            "old_weights": old_weights,
            "new_weights": new_params,
            "version": version,
        })
        safe_save(_EVOLUTION_PATH, history)

        # 设置验证期 (5天后检查效果) — 去重: 同策略同日不重复添加
        try:
            verif_path = os.path.join(_DIR, "optimization_verifications.json")
            verifs = safe_load(verif_path, default=[])
            today_str = date.today().isoformat()
            already_exists = any(
                v.get("strategy") == strategy
                and v.get("adopt_date") == today_str
                and v.get("status") == "pending"
                for v in verifs
            )
            if not already_exists:
                verifs.append({
                    "strategy": strategy,
                    "adopt_date": today_str,
                    "verify_date": (date.today() + timedelta(days=5)).isoformat(),
                    "source": "night_backtest",
                    "version": version,
                    "status": "pending",
                })
                safe_save(verif_path, verifs)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        adopted.append({
            "strategy": strategy,
            "action": "adopted",
            "reason": rec.get("reason", ""),
            "version": version,
        })
        logger.info("[自主进化] 采纳 %s v%d: %s", strategy, version, rec.get("reason", ""))

    return adopted


def discover_rules_from_history(memory: dict) -> list[dict]:
    """从历史数据中自动发现新规则

    分析 trade_journal + scorecard, 寻找:
    - 特定行情下某策略表现异常好/差 → 生成行情匹配规则
    - 某信号组合的胜率显著高于平均 → 生成信号组合规则

    Returns:
        新发现的规则列表
    """
    regime_fit = analyze_strategy_regime_fit(lookback_days=None)
    if not regime_fit:
        return []

    new_rules = []
    existing_rules = memory.get("rules", [])
    existing_ids = {r.get("id") for r in existing_rules}

    for item in regime_fit:
        strategy = item.get("strategy", "")
        regime = item.get("regime", "")
        win_rate = item.get("win_rate")
        avg_return = item.get("avg_return")
        samples = item.get("samples", 0)

        if win_rate is None or samples < 10:
            continue

        # 发现: 策略在某行情下表现特别差
        if win_rate < 0.35 and avg_return is not None and avg_return < -1:
            rule_id = f"regime_avoid_{strategy}_{regime}"
            if rule_id not in existing_ids:
                new_rules.append({
                    "id": rule_id,
                    "type": "regime_mismatch",
                    "description": (f"{strategy} 在 {regime} 行情下胜率仅 "
                                    f"{win_rate:.0%}, 建议暂停"),
                    "action": "pause_strategy",
                    "strategy": strategy,
                    "condition": {"regime": regime},
                    "confidence": min(0.9, 0.5 + samples * 0.02),
                    "source": "auto_discovery",
                    "evidence_count": samples,
                })

        # 发现: 策略在某行情下表现特别好
        if win_rate > 0.65 and avg_return is not None and avg_return > 1.5:
            rule_id = f"regime_boost_{strategy}_{regime}"
            if rule_id not in existing_ids:
                new_rules.append({
                    "id": rule_id,
                    "type": "regime_boost",
                    "description": (f"{strategy} 在 {regime} 行情下胜率 "
                                    f"{win_rate:.0%}, 可加大仓位"),
                    "action": "log_insight",
                    "strategy": strategy,
                    "condition": {"regime": regime},
                    "confidence": min(0.9, 0.5 + samples * 0.02),
                    "source": "auto_discovery",
                    "evidence_count": samples,
                })

    if new_rules:
        memory.setdefault("rules", []).extend(new_rules)
        logger.info("[自主进化] 发现 %d 条新规则", len(new_rules))

    return new_rules


# ================================================================
#  4. 报 — generate_learning_report
# ================================================================

def generate_learning_report() -> str:
    """生成 Markdown 格式学习报告"""
    params = LEARNING_ENGINE_PARAMS
    lookback = params.get("lookback_days", 30)
    today_str = date.today().isoformat()

    lines = [
        f"# 自学习引擎报告",
        f"日期: {today_str}  回望: {lookback}天",
        "",
    ]

    # --- 信号准确度 ---
    lines.append("## 大盘信号预测力")
    signal_results = analyze_signal_accuracy(lookback)
    if signal_results:
        lines.append("| 信号 | 预测力 | 高值胜率 | 低值胜率 | 相关性 | 样本 |")
        lines.append("|------|--------|----------|----------|--------|------|")
        for s in signal_results:
            pv = f"{s['predictive_value']:.1f}%" if s['predictive_value'] is not None else "N/A"
            hwr = f"{s['high_win_rate']:.0%}" if s['high_win_rate'] is not None else "N/A"
            lwr = f"{s['low_win_rate']:.0%}" if s['low_win_rate'] is not None else "N/A"
            corr = f"{s['correlation']:.3f}" if s['correlation'] is not None else "N/A"
            lines.append(f"| {s['signal']} | {pv} | {hwr} | {lwr} | {corr} | {s['samples']} |")
    else:
        lines.append("暂无数据")
    lines.append("")

    # --- 因子重要性 (每个策略) ---
    lines.append("## 选股因子重要性")
    strategies = [
        "集合竞价选股", "放量突破选股", "尾盘短线选股",
        "低吸回调选股", "缩量整理选股", "趋势跟踪选股", "板块轮动选股",
        "事件驱动选股", "期货趋势选股", "币圈趋势选股", "美股收盘分析",
    ]
    for strat in strategies:
        factor_results = analyze_factor_importance(strat, lookback)
        if not factor_results:
            continue
        lines.append(f"### {strat}")
        lines.append("| 因子 | 相关性 | TOP25%收益 | BOT25%收益 | 样本 |")
        lines.append("|------|--------|------------|------------|------|")
        for f in sorted(factor_results, key=lambda x: abs(x.get("correlation") or 0), reverse=True):
            corr = f"{f['correlation']:.3f}" if f['correlation'] is not None else "N/A"
            t25 = f"{f['top25_return']:+.2f}%" if f['top25_return'] is not None else "N/A"
            b25 = f"{f['bottom25_return']:+.2f}%" if f['bottom25_return'] is not None else "N/A"
            lines.append(f"| {f['factor']} | {corr} | {t25} | {b25} | {f['samples']} |")
        lines.append("")

    # --- 策略-行情适配 ---
    lines.append("## 策略-行情适配")
    regime_results = analyze_strategy_regime_fit(lookback)
    if regime_results:
        lines.append("| 策略 | 行情 | 胜率 | 平均收益 | 样本 |")
        lines.append("|------|------|------|----------|------|")
        for r in regime_results:
            wr = f"{r['win_rate']:.0%}" if r['win_rate'] is not None else "N/A"
            ar = f"{r['avg_return']:+.2f}%" if r['avg_return'] is not None else "N/A"
            lines.append(f"| {r['strategy']} | {r['regime']} | {wr} | {ar} | {r['samples']} |")
    else:
        lines.append("暂无数据")
    lines.append("")

    # --- 权重调整 ---
    lines.append("## 本日权重调整")
    proposal = propose_signal_weight_update()
    if proposal and proposal.get("adjustments"):
        lines.append("| 信号 | 原权重 | 新权重 | 变化 | 预测力 |")
        lines.append("|------|--------|--------|------|--------|")
        for sig, adj in proposal["adjustments"].items():
            lines.append(
                f"| {sig} | {adj['old']:.4f} | {adj['new']:.4f} | "
                f"{adj['delta']:+.4f} | {adj['predictive_value']:.1f}% |"
            )
    else:
        lines.append("无调整 (数据不足或无需调整)")
    lines.append("")

    # --- 数据积累进度 ---
    lines.append("## 数据积累进度")
    try:
        if _JOURNAL_PATH != _JOURNAL_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_trade_journal
        journal = load_trade_journal(days=lookback)
    except Exception:
        journal = safe_load(_JOURNAL_PATH, default=[])
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=lookback)
    except Exception:
        scorecard = safe_load(_SCORECARD_PATH, default=[])
    joined = _join_journal_scorecard(lookback)
    min_signal = params.get("min_samples_signal", 15)
    min_factor = params.get("min_samples_factor", 10)

    lines.append(f"- 交易日志: {len(journal)} 条")
    lines.append(f"- 记分卡: {len(scorecard)} 条")
    lines.append(f"- 可关联记录: {len(joined)} 条 (近{lookback}天)")
    lines.append(f"- 信号分析门槛: {min_signal} (当前{'已达' if len(joined) >= min_signal else '未达'})")
    lines.append(f"- 因子分析门槛: {min_factor} (当前{'已达' if len(joined) >= min_factor else '未达'})")
    lines.append("")

    return "\n".join(lines)


_LEARNING_STATE_PATH = os.path.join(_DIR, "learning_state.json")


def _persist_learning_state(report: str, proposal: dict | None,
                            factor_adjusted: int = 0, health: dict | None = None):
    """持久化学习状态: 因子分析 + 信号分析 + 权重调整 + 健康状态"""
    state = safe_load(_LEARNING_STATE_PATH, default={
        "version": 0, "history": []})

    state["last_run"] = datetime.now().isoformat()
    state["version"] = state.get("version", 0) + 1

    # 因子分析快照 (按真实策略名分析)
    # 重要: 如果本次分析失败(DB锁/并发冲突), 保留上一次成功的结果而不是覆盖为空
    prev_factors = state.get("factor_analysis", [])
    try:
        factors = []
        for strat in ["隔夜选股", "板块轮动选股", "趋势跟踪选股", "尾盘短线选股",
                       "集合竞价选股", "放量突破选股", "低吸回调选股", "缩量整理选股"]:
            strat_factors = analyze_factor_importance(strat, lookback_days=None)
            if strat_factors:
                factors.extend(strat_factors)
        if factors:
            state["factor_analysis"] = factors
            logger.info("因子分析快照: %d 因子 (8策略)", len(factors))
        elif prev_factors:
            # 本次分析为空但上次有数据 → 保留上次 (可能是DB锁导致)
            state["factor_analysis"] = prev_factors
            logger.warning("因子分析快照为空(可能DB锁), 保留上次 %d 因子", len(prev_factors))
        else:
            state["factor_analysis"] = []
    except Exception as e:
        import traceback
        logger.error("因子分析快照失败: %s\n%s", e, traceback.format_exc())
        if prev_factors:
            state["factor_analysis"] = prev_factors
            logger.info("异常后保留上次 %d 因子", len(prev_factors))
        else:
            state["factor_analysis"] = []

    # 信号分析快照
    state["signal_analysis"] = analyze_signal_accuracy()

    # 权重调整记录
    if proposal:
        state["last_weight_update"] = {
            "date": date.today().isoformat(),
            "adjustments": proposal.get("adjustments", {}),
        }

    # 报告摘要 (前500字)
    state["last_report_summary"] = (report or "")[:500]

    # 健康状态
    if health:
        state["health"] = health

    # 历史记录 (最多保留30条)
    state["history"] = state.get("history", [])[-29:]
    state["history"].append({
        "date": date.today().isoformat(),
        "version": state["version"],
        "n_factors": len(state.get("factor_analysis", [])),
        "n_signals": len(state.get("signal_analysis", [])),
        "signal_adjusted": proposal is not None,
        "factor_adjusted": factor_adjusted,
        "health": health.get("status") if health else "unknown",
    })

    safe_save(_LEARNING_STATE_PATH, state)
    logger.info("学习状态已持久化 v%d", state["version"])


# ================================================================
#  4b. 在线学习 — T+1 验证后实时微调
# ================================================================

# 进程内: 跟踪今日在线调整总量
_online_daily_tracker = {"date": "", "total_delta": 0.0, "updates": 0}

# 策略名 → tunable_params key 映射
_STRATEGY_TUNABLE_KEYS = {
    "集合竞价选股": "auction",
    "尾盘短线选股": "afternoon",
    "放量突破选股": "breakout",
    "低吸回调选股": "dip_buy",
    "缩量整理选股": "consolidation",
    "趋势跟踪选股": "trend_follow",
    "板块轮动选股": "sector_rotation",
    "事件驱动选股": "news_event",
    "隔夜选股": "overnight",
}


def _apply_online_deltas_to_strategies(tunable: dict, adjustments: dict,
                                        strategy_factors: dict):
    """将在线学习的因子 delta 实际应用到各策略的权重中

    对每个策略: 找到该策略使用的因子, 将 EMA delta 累加到其权重上.
    这使得在线学习不再空转, 因子权重真正随 T+1 反馈动态调整.
    """
    min_weight = LEARNING_ENGINE_PARAMS.get("min_weight", 0.03)

    for strat_name, factor_set in strategy_factors.items():
        key = _STRATEGY_TUNABLE_KEYS.get(strat_name, "")
        if not key:
            continue

        # 读取当前策略权重 (无则从默认初始化)
        strat_section = tunable.get(key, {})
        weights = dict(strat_section.get("weights", {}))
        if not weights:
            try:
                from auto_optimizer import _get_default_weights
                weights = _get_default_weights(key)
            except Exception:
                weights = {}
            if not weights:
                continue
            strat_section["weights"] = weights
            strat_section["initialized_from"] = "default"
            tunable[key] = strat_section

        changed = False
        for fname in factor_set:
            if fname not in adjustments or fname not in weights:
                continue
            delta = adjustments[fname]["delta"]
            old_w = weights[fname]
            new_w = max(min_weight, old_w + delta)
            if new_w != old_w:
                weights[fname] = round(new_w, 4)
                changed = True

        if changed:
            strat_section["weights"] = weights
            strat_section["online_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tunable[key] = strat_section
            logger.debug("[在线学习] 策略 %s 权重已微调", strat_name)


def incremental_update(verified_signals: list[dict]) -> dict:
    """T+1 验证结果出来后立即做增量权重微调

    与夜班全量学习互补:
    - 在线: ±0.01 限幅, 单日总量 ±0.05, 用 EMA 快速响应
    - 夜班: ±0.03 限幅, 全量统计分析

    Args:
        verified_signals: [{strategy, code, factor_scores, t1_return_pct, t1_result}]

    Returns:
        {"adjusted": int, "skipped_budget": bool, "adjustments": {}}
    """
    global _online_daily_tracker

    params = LEARNING_ENGINE_PARAMS
    if not params.get("online_learning_enabled", True):
        return {"adjusted": 0, "skipped_budget": False}

    max_delta = params.get("online_max_weight_delta", 0.01)
    daily_max = params.get("online_daily_max_total_delta", 0.05)
    alpha = params.get("online_ema_alpha", 0.1)

    today = date.today().isoformat()
    if _online_daily_tracker["date"] != today:
        _online_daily_tracker = {"date": today, "total_delta": 0.0, "updates": 0}

    # 预算检查
    if _online_daily_tracker["total_delta"] >= daily_max:
        logger.debug("[在线学习] 今日调整预算已用尽 (%.4f/%.4f)",
                     _online_daily_tracker["total_delta"], daily_max)
        return {"adjusted": 0, "skipped_budget": True}

    if not verified_signals:
        return {"adjusted": 0, "skipped_budget": False}

    # 按策略聚合: 每个因子的 (return, factor_score) 对
    factor_outcomes = {}  # factor_name -> [(score, return)]
    strategy_factors = {}  # strategy -> set(factor_names) — 追踪每个策略用了哪些因子
    for sig in verified_signals:
        factor_scores = sig.get("factor_scores", {})
        ret = sig.get("t1_return_pct", 0)
        strat = sig.get("strategy", "")
        for fname, fscore in factor_scores.items():
            if isinstance(fscore, (int, float)):
                factor_outcomes.setdefault(fname, []).append((fscore, ret))
                if strat:
                    strategy_factors.setdefault(strat, set()).add(fname)

    if not factor_outcomes:
        return {"adjusted": 0, "skipped_budget": False}

    # 读取当前策略权重 (从 tunable_params.json)
    tunable = safe_load(_TUNABLE_PATH, default={})
    adjustments = {}
    adjusted = 0

    # 对每个因子做 EMA 更新
    online_state = tunable.setdefault("_online_ema", {})

    for fname, outcomes in factor_outcomes.items():
        if len(outcomes) < 1:
            continue

        # 计算本批次该因子的信号质量: 高分时收益 vs 低分时收益
        scores = [o[0] for o in outcomes]
        returns = [o[1] for o in outcomes]
        median_score = sorted(scores)[len(scores) // 2] if scores else 0.5

        high_returns = [r for s, r in outcomes if s >= median_score]
        low_returns = [r for s, r in outcomes if s < median_score]

        if not high_returns or not low_returns:
            continue

        avg_high = sum(high_returns) / len(high_returns)
        avg_low = sum(low_returns) / len(low_returns)
        spread = avg_high - avg_low  # > 0 说明因子有效

        # EMA 更新
        old_ema = online_state.get(fname, 0.0)
        new_ema = (1 - alpha) * old_ema + alpha * spread
        online_state[fname] = round(new_ema, 6)

        # 根据 EMA 方向决定调整
        deadband = params.get("online_ema_deadband", 0.1)
        if abs(new_ema) < deadband:
            continue  # 信号太弱, 不调

        remaining_budget = daily_max - _online_daily_tracker["total_delta"]
        if remaining_budget <= 0:
            break

        delta = max_delta if new_ema > 0 else -max_delta
        delta = max(-remaining_budget, min(remaining_budget, delta))

        adjustments[fname] = {
            "delta": round(delta, 4),
            "ema_spread": round(new_ema, 4),
            "batch_spread": round(spread, 4),
        }
        _online_daily_tracker["total_delta"] += abs(delta)
        adjusted += 1

    # 保存 online EMA 状态
    tunable["_online_ema"] = online_state
    if adjustments:
        tunable["_online_last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tunable["_online_daily_adjustments"] = tunable.get("_online_daily_adjustments", 0) + adjusted

        # === 关键: 将 EMA delta 实际应用到各策略的因子权重 ===
        _apply_online_deltas_to_strategies(tunable, adjustments, strategy_factors)

    safe_save(_TUNABLE_PATH, tunable)
    _online_daily_tracker["updates"] += adjusted

    if adjustments:
        logger.info("[在线学习] 微调 %d 个因子 (今日第%d次, 预算%.4f/%.4f)",
                    adjusted, _online_daily_tracker["updates"],
                    _online_daily_tracker["total_delta"], daily_max)
        # 写入 evolution_history, 让 weight_evolution 健康检查能看到变更
        try:
            history = safe_load(_EVOLUTION_PATH, default=[])
            history.append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "online_ema",
                "action": "incremental_update",
                "reason": f"T+1在线学习微调 {adjusted} 个因子",
                "n_factors": adjusted,
                "details": {k: v["delta"] for k, v in adjustments.items()},
            })
            safe_save(_EVOLUTION_PATH, history)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    return {
        "adjusted": adjusted,
        "skipped_budget": False,
        "adjustments": adjustments,
    }


# ================================================================
#  3c. 因子权重直调 — 基于因子重要性分析直接调权
# ================================================================

def propose_factor_weight_update() -> list[dict]:
    """基于因子重要性分析, 直接调整各策略的因子权重

    与 incremental_update (在线EMA) 互补:
    - incremental_update: T+1验证 → 快速EMA微调 (需要signal_tracker数据)
    - propose_factor_weight: 全量统计分析 → 周期性校正 (只需scorecard)

    这确保即使 signal_tracker 停摆, 学习系统仍能从历史数据中调权.
    """
    params = LEARNING_ENGINE_PARAMS
    max_delta = params.get("max_weight_delta", 0.03)
    min_weight = params.get("min_weight", 0.03)
    min_samples = params.get("min_samples_factor", 10)

    all_adjustments = []
    tunable = safe_load(_TUNABLE_PATH, default={})

    for strat_name, tunable_key in _STRATEGY_TUNABLE_KEYS.items():
        try:
            factors = analyze_factor_importance(strat_name, lookback_days=None)
        except Exception:
            continue
        if not factors:
            continue

        # 读取当前策略权重
        strat_section = tunable.get(tunable_key, {})
        weights = dict(strat_section.get("weights", {}))
        if not weights:
            try:
                from auto_optimizer import _get_default_weights
                weights = _get_default_weights(tunable_key)
            except Exception:
                weights = {}
            if not weights:
                continue

        changed = False
        adjustments = {}
        for f in factors:
            fname = f["factor"]
            if fname not in weights or f.get("samples", 0) < min_samples:
                continue

            corr = f.get("correlation", 0) or 0
            top25 = f.get("top25_return", 0) or 0
            bot25 = f.get("bottom25_return", 0) or 0
            spread = top25 - bot25

            # --- 死因子检测: corr=0 且 top25==bottom25 → 压到最低权重 ---
            if corr == 0.0 and abs(spread) < 0.001:
                old_w = weights[fname]
                if old_w > min_weight + 0.001:
                    weights[fname] = min_weight
                    changed = True
                    adjustments[fname] = {
                        "old": old_w, "new": min_weight,
                        "delta": round(min_weight - old_w, 4),
                        "corr": 0.0, "spread": 0.0,
                        "reason": "zero_variance",
                    }
                    logger.info("[因子直调] %s:%s 零方差→压至最低 %.3f→%.3f",
                                strat_name, fname, old_w, min_weight)
                continue

            # 信号太弱则跳过
            if abs(corr) < 0.02 and abs(spread) < 0.5:
                continue

            # --- 毒因子快速降权: corr < -0.05 使用加倍 delta ---
            if corr < -0.05 and spread < 0:
                # 负相关+负spread = 确定性毒因子, 加速降权
                strength = min(abs(corr) * 10 + abs(spread) / 2, 1.0)
                aggressive_delta = max_delta * 2  # 2倍速降权
                delta = -1 * min(aggressive_delta, aggressive_delta * strength)
            else:
                # 正常调整
                direction = 1 if (corr > 0 and spread > 0) else (-1 if (corr < 0 and spread < 0) else 0)
                if direction == 0:
                    # 信号矛盾 (corr和spread方向不一致), 小幅度调整
                    direction = 1 if corr > 0 else -1
                    strength = min(abs(corr) * 5, 0.5)  # 半强度
                else:
                    strength = min(abs(corr) * 10 + abs(spread) / 2, 1.0)
                delta = direction * min(max_delta, max_delta * strength)

            old_w = weights[fname]
            new_w = max(min_weight, round(old_w + delta, 4))
            if abs(new_w - old_w) > 1e-5:
                weights[fname] = new_w
                changed = True
                adjustments[fname] = {
                    "old": old_w, "new": new_w,
                    "delta": round(new_w - old_w, 4),
                    "corr": round(corr, 4), "spread": round(spread, 4),
                }

        if changed:
            # 归一化
            total_w = sum(weights.values())
            if total_w > 0:
                weights = {k: round(v / total_w, 4) for k, v in weights.items()}

            strat_section["weights"] = weights
            strat_section["factor_updated_at"] = datetime.now().isoformat()
            strat_section["version"] = strat_section.get("version", 0) + 1
            tunable[tunable_key] = strat_section

            all_adjustments.append({
                "strategy": strat_name, "tunable_key": tunable_key,
                "adjustments": adjustments,
            })
            logger.info("[因子直调] %s: 调整 %d 个因子", strat_name, len(adjustments))

    if all_adjustments:
        safe_save(_TUNABLE_PATH, tunable)
        # 演化历史
        history = safe_load(_EVOLUTION_PATH, default=[])
        history.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": "factor_weight_update",
            "action": "factor_importance_update",
            "reason": "基于因子重要性分析周期性校正",
            "n_strategies": len(all_adjustments),
            "details": [{a["strategy"]: len(a["adjustments"])} for a in all_adjustments],
        })
        safe_save(_EVOLUTION_PATH, history)
        logger.info("[因子直调] 完成: %d 个策略调整", len(all_adjustments))

    return all_adjustments


# ================================================================
#  3d. 学习健康监控 — 自检 + 自愈 + 告警
# ================================================================

def check_learning_health() -> dict:
    """全链路学习健康检查 — 检测断裂 + 自动修复 + 推送告警

    检查项:
      1. scorecard 数据新鲜度 (最近交易日有无数据)
      2. 因子分析是否有结果
      3. ML 模型最后训练时间
      4. 在线学习是否活跃
      5. 信号验证是否运行
      6. 权重实际变化率

    返回: {"status": "ok"|"warning"|"critical", "checks": [...], "healed": [...]}
    """
    checks = []
    healed = []
    status = "ok"

    # ---- 1. scorecard 数据新鲜度 ----
    try:
        import sqlite3
        from db_store import _DB_PATH
        conn = sqlite3.connect(_DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            SELECT rec_date, COUNT(*) FROM scorecard
            WHERE rec_date >= date('now', 'localtime', '-3 days')
            GROUP BY rec_date ORDER BY rec_date DESC
        """)
        recent = cur.fetchall()
        if recent:
            latest_date = recent[0][0]
            latest_count = recent[0][1]
            checks.append({"check": "scorecard_freshness", "status": "ok",
                          "detail": f"最新{latest_date}: {latest_count}条"})
        else:
            checks.append({"check": "scorecard_freshness", "status": "critical",
                          "detail": "近3天无新数据 → 学习引擎无输入"})
            status = "critical"

        # 检查未回填记录比例
        cur.execute("SELECT COUNT(*) FROM scorecard WHERE net_return_pct = 0")
        unfilled = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM scorecard")
        total = cur.fetchone()[0]
        if total > 0 and unfilled / total > 0.1:
            checks.append({"check": "backfill_ratio", "status": "warning",
                          "detail": f"{unfilled}/{total} 未回填 ({unfilled/total:.0%})"})
            if status == "ok":
                status = "warning"

        conn.close()
    except Exception as e:
        checks.append({"check": "scorecard_freshness", "status": "error",
                      "detail": f"检查失败: {e}"})
        status = "critical"

    # ---- 2. 因子分析 ----
    try:
        total_factors = 0
        strats_with_data = 0
        # 健康检查用 90 天宽窗口, 避免周末/节假日误报
        health_lookback = max(
            LEARNING_ENGINE_PARAMS.get("lookback_days", 60), 90)
        for strat in _STRATEGY_TUNABLE_KEYS:
            f = analyze_factor_importance(strat, lookback_days=health_lookback)
            if f:
                total_factors += len(f)
                strats_with_data += 1

        if total_factors > 0:
            checks.append({"check": "factor_analysis", "status": "ok",
                          "detail": f"{strats_with_data}/{len(_STRATEGY_TUNABLE_KEYS)} 策略, {total_factors} 因子"})
        else:
            checks.append({"check": "factor_analysis", "status": "critical",
                          "detail": "0个因子可分析 → 权重调整无数据源"})
            status = "critical"
    except Exception as e:
        checks.append({"check": "factor_analysis", "status": "error",
                      "detail": f"分析失败: {e}"})

    # ---- 3. ML 模型新鲜度 ----
    try:
        import pickle
        model_dir = os.path.join(_DIR, "models")
        if os.path.isdir(model_dir):
            model_files = [f for f in os.listdir(model_dir) if f.endswith(".pkl")]
            if model_files:
                latest_mtime = max(
                    os.path.getmtime(os.path.join(model_dir, f))
                    for f in model_files
                )
                age_hours = (datetime.now().timestamp() - latest_mtime) / 3600
                if age_hours <= 48:
                    checks.append({"check": "ml_model", "status": "ok",
                                  "detail": f"{len(model_files)} 模型, {age_hours:.0f}h前训练"})
                else:
                    checks.append({"check": "ml_model", "status": "warning",
                                  "detail": f"模型已过期 ({age_hours:.0f}h未训练)"})
                    if status == "ok":
                        status = "warning"
                    # 自愈: 触发 ML 重训
                    try:
                        from ml_factor_model import train_all_strategies
                        train_all_strategies()
                        healed.append("ml_retrain: 触发模型重训")
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
            else:
                checks.append({"check": "ml_model", "status": "critical",
                              "detail": "无模型文件"})
                status = "critical"
        else:
            checks.append({"check": "ml_model", "status": "critical",
                          "detail": "模型目录不存在"})
            status = "critical"
    except Exception as e:
        checks.append({"check": "ml_model", "status": "error",
                      "detail": f"检查失败: {e}"})

    # ---- 4. 在线学习活跃度 ----
    try:
        tunable = safe_load(_TUNABLE_PATH, default={})
        online_update = tunable.get("_online_last_update", "")
        online_adj = tunable.get("_online_daily_adjustments", 0)
        if online_update:
            from datetime import datetime as dt
            last = dt.fromisoformat(online_update)
            age_hours = (datetime.now() - last).total_seconds() / 3600
            # 周末/节假日放宽到 96h (无新信号验证 → 不触发在线学习是正常的)
            threshold_hours = 96 if date.today().weekday() >= 5 else 48
            if age_hours <= threshold_hours:
                checks.append({"check": "online_learning", "status": "ok",
                              "detail": f"最后更新 {online_update} (累计{online_adj}次)"})
            else:
                checks.append({"check": "online_learning", "status": "warning",
                              "detail": f"在线学习 {age_hours:.0f}h 未活跃"})
                if status == "ok":
                    status = "warning"
        else:
            # 从未运行: 检查是否有可用信号数据
            signals_path = os.path.join(_DIR, "signals_db.json")
            has_signals = os.path.exists(signals_path) and os.path.getsize(signals_path) > 10
            if has_signals:
                checks.append({"check": "online_learning", "status": "warning",
                              "detail": "在线学习从未运行 (有信号数据但未触发)"})
                if status == "ok":
                    status = "warning"
            else:
                checks.append({"check": "online_learning", "status": "info",
                              "detail": "在线学习待激活 (暂无信号数据)"})
    except Exception as e:
        checks.append({"check": "online_learning", "status": "error",
                      "detail": str(e)})

    # ---- 5. 信号验证 ----
    try:
        signals_path = os.path.join(_DIR, "signals_db.json")
        if os.path.exists(signals_path):
            sigs = safe_load(signals_path, default=[])
            pending = sum(1 for s in sigs if s.get("status") == "pending")
            completed = sum(1 for s in sigs if s.get("status") == "completed")
            partial = sum(1 for s in sigs if s.get("status") == "partial")
            total_sigs = len(sigs)

            if completed > 0 or partial > 0:
                checks.append({"check": "signal_verification", "status": "ok",
                              "detail": f"总{total_sigs}: 完成{completed} 部分{partial} 待验{pending}"})
            elif total_sigs > 0:
                checks.append({"check": "signal_verification", "status": "warning",
                              "detail": f"{total_sigs}条信号, 0条完成验证"})
                if status == "ok":
                    status = "warning"
            else:
                checks.append({"check": "signal_verification", "status": "warning",
                              "detail": "无信号数据"})
        else:
            checks.append({"check": "signal_verification", "status": "warning",
                          "detail": "signals_db.json 不存在"})
    except Exception as e:
        checks.append({"check": "signal_verification", "status": "error",
                      "detail": str(e)})

    # ---- 6. 权重变化率 ----
    try:
        evo_history = safe_load(_EVOLUTION_PATH, default=[])
        recent_evo = [e for e in evo_history
                      if e.get("date", "") >= (date.today() - timedelta(days=7)).isoformat()]
        if recent_evo:
            checks.append({"check": "weight_evolution", "status": "ok",
                          "detail": f"近7天 {len(recent_evo)} 次权重变更"})
        else:
            checks.append({"check": "weight_evolution", "status": "warning",
                          "detail": "近7天无权重变更 → 学习停滞"})
            if status == "ok":
                status = "warning"

            # 自愈: 触发因子直调
            try:
                adj = propose_factor_weight_update()
                if adj:
                    healed.append(f"factor_weight_update: 调整 {len(adj)} 个策略")
            except Exception as _exc:
                logger.warning("Suppressed exception: %s", _exc)
    except Exception as _exc:
        logger.warning("Suppressed exception: %s", _exc)

    result = {
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "healed": healed,
    }

    # 持久化
    health_path = os.path.join(_DIR, "learning_health.json")
    safe_save(health_path, result)

    # 告警: critical 时推送微信
    if status == "critical":
        try:
            from notifier import notify_wechat_raw
            lines = ["学习系统健康告警\n"]
            for c in checks:
                icon = "❌" if c["status"] == "critical" else "⚠️" if c["status"] == "warning" else "✅"
                lines.append(f"{icon} {c['check']}: {c['detail']}")
            if healed:
                lines.append("\n自动修复:")
                for h in healed:
                    lines.append(f"  🔧 {h}")
            notify_wechat_raw("学习健康告警", "\n".join(lines))
        except Exception as _exc:
            logger.warning("Suppressed exception: %s", _exc)

    logger.info("[学习健康] 状态=%s, 检查=%d项, 自愈=%d项",
                status, len(checks), len(healed))
    return result


# ================================================================
#  5a. 大周期重训 — 全量数据重设初始权重
# ================================================================

def run_full_retrain():
    """大周期重训: 一次性吃掉全量 scorecard 数据, 重设因子初始权重.

    与日常 EMA 微调互补:
    - 大周期: 全量数据 (10万+), 统计显著, 设初始权重 → 周日夜班跑
    - 日常 EMA: 近期数据, 快速响应, 微调权重 → 每天3轮

    流程:
    1. 从 DB 全量提取 (lookback_days=None)
    2. 按策略分组, 每个因子计算胜率贡献
    3. 将统计结果写入 tunable_params.json 作为初始权重
    4. 训练 8+1 个 ML 专家模型
    """
    logger.info("=== 大周期重训启动 (全量数据) ===")
    lines = []

    # Step 1: 全量穿透提取
    joined = _join_scorecard_direct(lookback_days=None)
    if not joined or len(joined) < 100:
        msg = f"全量数据不足 ({len(joined) if joined else 0} 条), 跳过重训"
        logger.warning(msg)
        return msg

    lines.append(f"📊 全量数据: {len(joined)} 条")

    # Step 2: 用 analyze_factor_importance 的 correlation+spread 定权
    #   旧逻辑 bug: 每条记录的 win/lose 加给所有因子 → 全因子等权
    #   新逻辑: 直接用因子相关性分析, 正向因子提权, 负向/废因子压权
    tunable = safe_load(_TUNABLE_PATH, default={})
    strategies_updated = 0
    min_weight = LEARNING_ENGINE_PARAMS.get("min_weight", 0.03)
    max_retrain_delta = 0.05  # 重训最大偏移量, 保护在线学习成果

    for strat_name, tunable_key in _STRATEGY_TUNABLE_KEYS.items():
        try:
            factors = analyze_factor_importance(strat_name, lookback_days=None)
        except Exception as e:
            logger.warning("[重训] %s 因子分析失败: %s", strat_name, e)
            continue
        if not factors:
            continue

        strat_section = tunable.get(tunable_key, {})
        old_weights = dict(strat_section.get("weights", {}))
        if not old_weights:
            try:
                from auto_optimizer import _get_default_weights
                old_weights = _get_default_weights(tunable_key)
            except Exception:
                old_weights = {}
            if not old_weights:
                continue

        # 基于因子分析计算目标权重
        new_weights = dict(old_weights)
        changed = False
        for f in factors:
            fname = f["factor"]
            if fname not in new_weights:
                continue
            corr = f.get("correlation", 0) or 0
            top25 = f.get("top25_return", 0) or 0
            bot25 = f.get("bottom25_return", 0) or 0
            spread = top25 - bot25
            samples = f.get("samples", 0)
            if samples < 20:
                continue

            old_w = old_weights[fname]

            # 废因子 → 压到最低
            if corr == 0.0 and abs(spread) < 0.001:
                target = min_weight
            # 毒因子 → 大幅压权
            elif corr < -0.05 and spread < 0:
                target = max(min_weight, old_w - max_retrain_delta * 2)
            # 负向因子 → 小幅压权
            elif corr < -0.02:
                strength = min(abs(corr) * 10, 1.0)
                target = max(min_weight, old_w - max_retrain_delta * strength)
            # 正向因子 → 提权
            elif corr > 0.02:
                strength = min(abs(corr) * 10 + abs(spread) / 2, 1.0)
                target = old_w + max_retrain_delta * strength
            else:
                continue  # 中性因子不动

            # 限幅: 相对当前权重最多偏移 max_retrain_delta
            clamped = max(min_weight, min(old_w + max_retrain_delta, max(old_w - max_retrain_delta, target)))
            if abs(clamped - old_w) > 1e-5:
                new_weights[fname] = round(clamped, 4)
                changed = True

        if not changed:
            continue

        # 归一化
        total_w = sum(new_weights.values())
        if total_w > 0:
            new_weights = {k: round(v / total_w, 4) for k, v in new_weights.items()}

        strat_section["weights"] = new_weights
        strat_section["full_retrain_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        strat_section["full_retrain_samples"] = len(joined)
        tunable[tunable_key] = strat_section
        strategies_updated += 1

        n_factors = len(new_weights)
        top3 = sorted(new_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join(f"{k}={v:.3f}" for k, v in top3)
        lines.append(f"  {strat_name} ({tunable_key}): {n_factors}因子, top: {top_str}")

    safe_save(_TUNABLE_PATH, tunable)
    lines.append(f"\n✅ {strategies_updated} 个策略权重已重设")

    # Step 4: ML 专家模型全量重训
    try:
        from ml_factor_model import train_all_strategies
        ml_result = train_all_strategies(lookback_days=1500)
        lines.append(f"🤖 ML: {ml_result['summary']}")
    except Exception as e:
        lines.append(f"⚠️ ML重训失败: {e}")

    report = "🔄 大周期重训报告\n" + "\n".join(lines)
    logger.info("=== 大周期重训完成: %d 策略 ===", strategies_updated)

    # 推送微信
    try:
        from notifier import notify_wechat_raw
        notify_wechat_raw("大周期重训完成", report)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return report


# ================================================================
#  5b. 主循环 — run_learning_cycle
# ================================================================

def run_learning_cycle():
    """串联: analyze → signal_adjust → factor_adjust → auto_adopt → health_check → push

    学习闭环:
      1. 生成分析报告
      2. 信号权重调整 (regime macro)
      3. 因子权重直调 (stock micro) — 即使信号调整失败也能调权
      4. 自动采纳回测参数
      5. 信号追踪反馈
      6. 健康检查 + 自愈
    """
    params = LEARNING_ENGINE_PARAMS
    if not params.get("learning_enabled", True):
        logger.info("学习引擎已禁用, 跳过")
        return

    logger.info("=== 学习引擎启动 ===")

    # 1. 生成报告 (内含分析)
    try:
        report = generate_learning_report()
        logger.info("学习报告已生成")
    except Exception as e:
        logger.error("学习报告生成失败: %s", e)
        report = f"学习报告生成失败: {e}"

    # 2. 信号权重调整 (macro: regime signals)
    proposal = None
    try:
        proposal = propose_signal_weight_update()
        if proposal:
            apply_weight_update(proposal)
            logger.info("信号权重调整已应用")
        else:
            logger.info("无需调整信号权重")
    except Exception as e:
        logger.error("信号权重调整失败: %s", e)

    # 3. 因子权重直调 (micro: factor importance → 直接调权)
    factor_adjusted = 0
    try:
        factor_updates = propose_factor_weight_update()
        factor_adjusted = len(factor_updates)
        if factor_adjusted > 0:
            logger.info("因子权重直调: %d 个策略", factor_adjusted)
    except Exception as e:
        logger.error("因子权重直调失败: %s", e)

    # 4. 自动采纳回测最优参数
    try:
        adopted = auto_adopt_backtest_results()
        if adopted:
            logger.info("自动采纳 %d 个策略参数", len(adopted))
    except Exception as e:
        logger.debug("回测参数采纳: %s", e)

    # 5. 信号追踪器反馈
    try:
        from signal_tracker import get_feedback_for_learning
        feedback = get_feedback_for_learning()
        adj = feedback.get("factor_adjustments", {})
        if adj:
            logger.info("信号追踪反馈: %d 个因子权重建议", len(adj))
            for factor, delta in adj.items():
                logger.info("  %s: %+.4f", factor, delta)
        decay = feedback.get("signal_decay", {})
        for strategy, info in decay.items():
            if info.get("fast_decay"):
                logger.warning("信号衰减警告: %s T+1=%.2f%% T+5=%.2f%% (快衰减)",
                               strategy, info["avg_t1"], info["avg_t5"])
    except Exception as e:
        logger.debug("信号追踪反馈: %s", e)

    # 6. 学习健康检查 + 自愈
    health = None
    try:
        health = check_learning_health()
        h_status = health.get("status", "unknown")
        if h_status == "critical":
            logger.error("[学习健康] 状态=CRITICAL, 已自动告警")
            report += f"\n\n⚠️ 学习健康: CRITICAL"
            for c in health.get("checks", []):
                if c["status"] in ("critical", "error"):
                    report += f"\n  ❌ {c['check']}: {c['detail']}"
        elif h_status == "warning":
            report += f"\n\n⚠️ 学习健康: WARNING"
        # 自愈报告
        for h in health.get("healed", []):
            report += f"\n  🔧 自愈: {h}"
    except Exception as e:
        logger.error("学习健康检查失败: %s", e)

    # 学习报告不走微信 (内容已纳入晚报汇总, 节省配额)
    if params.get("wechat_learning_report", False):
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw("自学习引擎报告", report)
        except Exception as e:
            logger.error("学习报告推送失败: %s", e)

    # 持久化学习状态 (供其他模块查询)
    try:
        _persist_learning_state(report, proposal, factor_adjusted, health)
    except Exception as e:
        import traceback
        logger.error("学习状态持久化失败: %s\n%s", e, traceback.format_exc())

    # 终端输出
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    logger.info("=== 学习引擎完成 ===")
    return report


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "run":
        run_learning_cycle()
    elif mode == "report":
        print(generate_learning_report())
    elif mode == "analyze":
        import json
        print("=== 信号准确度 ===")
        print(json.dumps(analyze_signal_accuracy(), indent=2, ensure_ascii=False))
        print("\n=== 策略-行情适配 ===")
        print(json.dumps(analyze_strategy_regime_fit(), indent=2, ensure_ascii=False))
    elif mode in ("full_retrain", "retrain", "full"):
        print(run_full_retrain())
    else:
        print(f"未知模式: {mode}")
        print("用法:")
        print("  python3 learning_engine.py              # 运行学习周期")
        print("  python3 learning_engine.py report       # 仅生成报告")
        print("  python3 learning_engine.py analyze      # 仅分析")
        print("  python3 learning_engine.py full_retrain # 大周期全量重训")
        sys.exit(1)
