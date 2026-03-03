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

    关联键: (date, code, strategy)
    返回: [{signals, factor_scores, net_return_pct, regime, strategy, ...}]
    """
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

    # 建 scorecard 索引: (rec_date, code, strategy) → record
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

        # 设置验证期 (5天后检查效果)
        try:
            verif_path = os.path.join(_DIR, "optimization_verifications.json")
            verifs = safe_load(verif_path, default=[])
            verifs.append({
                "strategy": strategy,
                "adopt_date": date.today().isoformat(),
                "verify_date": (date.today() + timedelta(days=5)).isoformat(),
                "source": "night_backtest",
                "version": version,
                "status": "pending",
            })
            safe_save(verif_path, verifs)
        except Exception:
            pass

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
    regime_fit = analyze_strategy_regime_fit(lookback_days=60)
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


def _persist_learning_state(report: str, proposal: dict | None):
    """持久化学习状态: 因子分析 + 信号分析 + 权重调整 + 报告摘要"""
    state = safe_load(_LEARNING_STATE_PATH, default={
        "version": 0, "history": []})

    state["last_run"] = datetime.now().isoformat()
    state["version"] = state.get("version", 0) + 1

    # 因子分析快照
    try:
        factors = analyze_factor_importance("ml_backfill", lookback_days=60)
        # 也尝试真实策略
        for strat in ["集合竞价选股", "放量突破选股", "尾盘短线选股"]:
            strat_factors = analyze_factor_importance(strat, lookback_days=60)
            if strat_factors:
                factors.extend(strat_factors)
        state["factor_analysis"] = factors
    except Exception:
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

    # 历史记录 (最多保留30条)
    state["history"] = state.get("history", [])[-29:]
    state["history"].append({
        "date": date.today().isoformat(),
        "version": state["version"],
        "n_factors": len(state.get("factor_analysis", [])),
        "n_signals": len(state.get("signal_analysis", [])),
        "weight_adjusted": proposal is not None,
    })

    safe_save(_LEARNING_STATE_PATH, state)
    logger.info("学习状态已持久化 v%d", state["version"])


# ================================================================
#  5. 主循环 — run_learning_cycle
# ================================================================

def run_learning_cycle():
    """串联: analyze → propose → apply → auto_adopt → report → push"""
    params = LEARNING_ENGINE_PARAMS
    if not params.get("learning_enabled", True):
        logger.info("学习引擎已禁用, 跳过")
        return

    logger.info("=== 学习引擎启动 ===")

    # 生成报告 (内含分析)
    try:
        report = generate_learning_report()
        logger.info("学习报告已生成")
    except Exception as e:
        logger.error("学习报告生成失败: %s", e)
        report = f"学习报告生成失败: {e}"

    # 提出并应用信号权重调整
    try:
        proposal = propose_signal_weight_update()
        if proposal:
            apply_weight_update(proposal)
            logger.info("信号权重调整已应用")
        else:
            logger.info("无需调整信号权重")
    except Exception as e:
        logger.error("信号权重调整失败: %s", e)

    # 自动采纳回测最优参数
    try:
        adopted = auto_adopt_backtest_results()
        if adopted:
            logger.info("自动采纳 %d 个策略参数", len(adopted))
    except Exception as e:
        logger.debug("回测参数采纳: %s", e)

    # 信号追踪器反馈: 用实际验证结果微调因子权重
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

    # 学习报告不走微信 (内容已纳入晚报汇总, 节省配额)
    if params.get("wechat_learning_report", False):
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw("自学习引擎报告", report)
        except Exception as e:
            logger.error("学习报告推送失败: %s", e)

    # 持久化学习状态 (供其他模块查询)
    try:
        _persist_learning_state(report, proposal)
    except Exception as e:
        logger.debug("学习状态持久化失败: %s", e)

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
    else:
        print(f"未知模式: {mode}")
        print("用法:")
        print("  python3 learning_engine.py           # 运行学习周期")
        print("  python3 learning_engine.py report    # 仅生成报告")
        print("  python3 learning_engine.py analyze   # 仅分析")
        sys.exit(1)
