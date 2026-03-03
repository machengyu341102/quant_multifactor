"""
自主实验 — 发现异常后自动设计 A/B 回测实验, 验证后采纳
========================================================
工作流:
  1. 从 findings 中筛选可实验的异常
  2. 设计实验 (候选参数组)
  3. 回测执行 (基线 + 候选)
  4. 超过阈值则采纳

安全机制:
  - cooldown_days: 同策略两次实验最小间隔
  - max_concurrent_experiments: 并发上限
  - adopt_threshold_pct: 收益提升 >= 阈值才采纳

CLI:
  python3 experiment_lab.py history  # 查看实验历史
  python3 experiment_lab.py report   # 生成实验报告
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from config import EXPERIMENT_PARAMS
from log_config import get_logger

logger = get_logger("experiment_lab")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_EXPERIMENTS_PATH = os.path.join(_BASE_DIR, "experiments.json")

# finding type → 策略英文名映射
_STRATEGY_MAP = {
    "集合竞价选股": "auction",
    "放量突破选股": "breakout",
    "尾盘短线选股": "afternoon",
    "低吸回调选股": "dip_buy",
    "缩量整理选股": "consolidation",
    "趋势跟踪选股": "trend_follow",
    "板块轮动选股": "sector_rotation",
    "事件驱动选股": "news_event",
    "期货趋势选股": "futures_trend",
    "币圈趋势选股": "crypto_trend",
    "美股收盘分析": "us_stock",
}

# 可触发实验的 finding 类型
_EXPERIMENTABLE_TYPES = {
    "consecutive_loss",
    "win_rate_degradation",
    "regime_mismatch",
}


# ================================================================
#  实验设计
# ================================================================

def design_experiment(strategy: str, finding: dict) -> dict | None:
    """基于异常类型设计实验 (候选参数组)

    Args:
        strategy: 英文策略名 (breakout/auction/afternoon)
        finding: 触发的异常 finding

    Returns:
        experiment dict 或 None (如果不可实验)
    """
    try:
        from auto_optimizer import get_tunable_params, generate_candidates
    except ImportError:
        logger.warning("无法导入 auto_optimizer, 跳过实验设计")
        return None

    # 获取当前参数
    current = get_tunable_params(strategy)
    current_weights = current.get("weights", {})
    if not current_weights:
        logger.info("策略 %s 无可调参数, 跳过", strategy)
        return None

    # 生成候选
    n = EXPERIMENT_PARAMS.get("n_candidates", 5)
    candidates = generate_candidates(strategy, current_weights, n)
    if not candidates:
        logger.info("策略 %s 未生成有效候选, 跳过", strategy)
        return None

    # 确定假设
    severity = finding.get("severity", "info")
    msg = finding.get("message", "")
    suggested_action = finding.get("suggested_action", "")

    if "连亏" in msg or "连续亏损" in msg or "consecutive" in suggested_action:
        hypothesis = "调整因子权重以减少连续亏损"
    elif "胜率" in msg or "win_rate" in suggested_action:
        hypothesis = "搜索更优权重以提升胜率"
    elif "行情" in msg or "regime" in suggested_action:
        hypothesis = "调整因子权重以适应当前行情"
    else:
        hypothesis = "探索更优参数组合"

    experiment_id = f"EXP_{strategy}_{date.today().strftime('%Y%m%d')}_{_next_seq(strategy)}"

    return {
        "experiment_id": experiment_id,
        "strategy": strategy,
        "hypothesis": hypothesis,
        "trigger": {
            "severity": severity,
            "message": msg,
            "suggested_action": suggested_action,
        },
        "current_weights": current_weights,
        "candidates": candidates,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "designed",
    }


def _next_seq(strategy: str) -> str:
    """获取下一个实验序号"""
    history = safe_load(_EXPERIMENTS_PATH, default=[])
    today_prefix = f"EXP_{strategy}_{date.today().strftime('%Y%m%d')}"
    today_exps = [e for e in history if e.get("experiment_id", "").startswith(today_prefix)]
    return f"{len(today_exps) + 1:03d}"


# ================================================================
#  实验执行
# ================================================================

def run_experiment(experiment: dict) -> dict:
    """执行回测: 基线 + 候选参数

    Args:
        experiment: design_experiment() 的返回值

    Returns:
        更新后的 experiment dict (含 baseline_result, best_candidate, conclusion)
    """
    strategy = experiment.get("strategy", "")
    candidates = experiment.get("candidates", [])
    current_weights = experiment.get("current_weights", {})
    lookback = EXPERIMENT_PARAMS.get("backtest_lookback_days", 90)

    try:
        from backtest import backtest_strategy
    except ImportError:
        logger.error("无法导入 backtest 模块")
        experiment["status"] = "error"
        experiment["conclusion"] = "error"
        experiment["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return experiment

    # 基线回测
    logger.info("[Experiment] %s — 基线回测...", experiment.get("experiment_id", ""))
    try:
        baseline = backtest_strategy(strategy, lookback)
    except Exception as e:
        logger.error("基线回测失败: %s", e)
        experiment["status"] = "error"
        experiment["conclusion"] = "error"
        experiment["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return experiment

    experiment["baseline_result"] = {
        "win_rate": baseline.get("win_rate", 0),
        "avg_return": baseline.get("avg_return", 0),
        "total_return": baseline.get("total_return", 0),
        "total_trades": baseline.get("total_trades", 0),
    }

    # 候选回测
    best = None
    best_improvement = 0
    threshold = EXPERIMENT_PARAMS.get("adopt_threshold_pct", 1.0)

    for i, candidate in enumerate(candidates):
        logger.info("[Experiment] 候选 %d/%d ...", i + 1, len(candidates))
        try:
            result = backtest_strategy(strategy, lookback,
                                       param_overrides=candidate)
            if result.get("error") or result.get("total_trades", 0) == 0:
                continue

            ar_improve = result.get("avg_return", 0) - baseline.get("avg_return", 0)
            wr_improve = result.get("win_rate", 0) - baseline.get("win_rate", 0)

            if ar_improve >= threshold and wr_improve >= 0:
                total_improve = ar_improve + wr_improve * 0.1
                if total_improve > best_improvement:
                    best_improvement = total_improve
                    best = {
                        "weights": candidate.get("weights", {}),
                        "win_rate": result.get("win_rate", 0),
                        "avg_return": result.get("avg_return", 0),
                        "total_return": result.get("total_return", 0),
                        "improvement_pct": round(ar_improve, 2),
                    }
        except Exception as e:
            logger.warning("候选 %d 回测异常: %s", i + 1, e)

    if best:
        experiment["best_candidate"] = best
        experiment["conclusion"] = "found_better"
    else:
        experiment["best_candidate"] = None
        experiment["conclusion"] = "no_improvement"

    experiment["status"] = "completed"
    experiment["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return experiment


# ================================================================
#  采纳实验结果
# ================================================================

def adopt_experiment_result(experiment: dict) -> bool:
    """最优候选超过阈值则采纳

    Returns:
        True if adopted, False otherwise
    """
    if experiment.get("conclusion") != "found_better":
        return False

    best = experiment.get("best_candidate")
    if not best or not best.get("weights"):
        return False

    strategy = experiment.get("strategy", "")
    hypothesis = experiment.get("hypothesis", "")

    try:
        from auto_optimizer import apply_optimization
        apply_optimization(
            strategy,
            best["weights"],
            reason=f"实验采纳: {hypothesis} (收益+{best.get('improvement_pct', 0):.2f}%)",
            improvement={"avg_return": f"+{best.get('improvement_pct', 0):.2f}%"},
            backtest_result={
                "win_rate": best.get("win_rate"),
                "avg_return": best.get("avg_return"),
            },
        )
        experiment["adopted"] = True
        logger.info("[Experiment] 采纳 %s: %s", experiment.get("experiment_id"), hypothesis)
        return True
    except Exception as e:
        logger.error("采纳失败: %s", e)
        experiment["adopted"] = False
        return False


# ================================================================
#  冷却期 + 并发检查
# ================================================================

def _check_cooldown(strategy: str) -> bool:
    """检查策略是否在冷却期内

    Returns:
        True if in cooldown (should skip), False if ok
    """
    cooldown_days = EXPERIMENT_PARAMS.get("cooldown_days", 7)
    history = safe_load(_EXPERIMENTS_PATH, default=[])
    cutoff = (date.today() - timedelta(days=cooldown_days)).isoformat()

    for exp in reversed(history):
        if exp.get("strategy") != strategy:
            continue
        completed = exp.get("completed_at", "")
        if completed and completed[:10] >= cutoff:
            return True
    return False


def _count_running() -> int:
    """计算当前运行中的实验数"""
    history = safe_load(_EXPERIMENTS_PATH, default=[])
    return sum(1 for e in history if e.get("status") == "running")


# ================================================================
#  主入口: 自动实验循环
# ================================================================

def run_auto_experiment_cycle(findings: list, memory: dict) -> list:
    """筛选可实验的 findings, 设计→执行→采纳

    Args:
        findings: orient() 产出的 findings 列表
        memory: agent_memory

    Returns:
        实验结果列表 [{experiment_id, conclusion, adopted}, ...]
    """
    if not EXPERIMENT_PARAMS.get("enabled", True):
        return []

    max_concurrent = EXPERIMENT_PARAMS.get("max_concurrent_experiments", 2)
    results = []

    # 筛选可实验的 findings
    experimentable = []
    for f in findings:
        strategy_cn = f.get("strategy")
        if not strategy_cn:
            continue
        strategy_en = _STRATEGY_MAP.get(strategy_cn)
        if not strategy_en:
            continue

        # 检查 finding 类型 (通过 message 关键字推断)
        msg = f.get("message", "")
        severity = f.get("severity", "")
        if severity not in ("critical", "warning"):
            continue

        # 检查策略健康度
        try:
            from auto_optimizer import evaluate_strategy_health
            health = evaluate_strategy_health(strategy_en)
            if health.get("score", 100) >= EXPERIMENT_PARAMS.get("min_health_score_trigger", 50):
                continue
        except Exception:
            pass

        experimentable.append((strategy_en, f))

    # 去重: 同一策略只实验一次
    seen_strategies = set()
    unique = []
    for strategy_en, f in experimentable:
        if strategy_en not in seen_strategies:
            seen_strategies.add(strategy_en)
            unique.append((strategy_en, f))

    for strategy_en, finding in unique:
        # 并发检查
        if _count_running() >= max_concurrent:
            logger.info("[Experiment] 并发上限 %d, 跳过", max_concurrent)
            break

        # 冷却期检查
        if _check_cooldown(strategy_en):
            logger.info("[Experiment] %s 在冷却期, 跳过", strategy_en)
            continue

        # 设计
        experiment = design_experiment(strategy_en, finding)
        if not experiment:
            continue

        # 记录为 running
        experiment["status"] = "running"
        history = safe_load(_EXPERIMENTS_PATH, default=[])
        history.append(experiment)
        safe_save(_EXPERIMENTS_PATH, history)

        # 执行
        experiment = run_experiment(experiment)

        # 采纳
        adopted = False
        if experiment.get("conclusion") == "found_better":
            adopted = adopt_experiment_result(experiment)

        # 更新历史
        history = safe_load(_EXPERIMENTS_PATH, default=[])
        for i, e in enumerate(history):
            if e.get("experiment_id") == experiment.get("experiment_id"):
                history[i] = experiment
                break
        safe_save(_EXPERIMENTS_PATH, history)

        results.append({
            "experiment_id": experiment.get("experiment_id"),
            "strategy": strategy_en,
            "conclusion": experiment.get("conclusion"),
            "adopted": adopted,
            "hypothesis": experiment.get("hypothesis", ""),
        })

    return results


# ================================================================
#  查询 & 报告
# ================================================================

def get_experiment_history(days: int = 30) -> list:
    """获取最近 N 天的实验历史"""
    history = safe_load(_EXPERIMENTS_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [e for e in history if e.get("created_at", "")[:10] >= cutoff]


def generate_experiment_report() -> str:
    """生成实验报告 Markdown"""
    history = get_experiment_history(30)

    lines = ["## 自主实验报告 (近30天)", ""]

    if not history:
        lines.append("暂无实验记录")
        return "\n".join(lines)

    total = len(history)
    completed = sum(1 for e in history if e.get("status") == "completed")
    adopted = sum(1 for e in history if e.get("adopted"))
    found_better = sum(1 for e in history if e.get("conclusion") == "found_better")

    lines.append(f"- 总实验: {total}")
    lines.append(f"- 已完成: {completed}")
    lines.append(f"- 找到更优: {found_better}")
    lines.append(f"- 已采纳: {adopted}")
    lines.append("")

    lines.append("### 实验详情")
    for e in history[-10:]:  # 最近10条
        eid = e.get("experiment_id", "?")
        conclusion = e.get("conclusion", "?")
        hypothesis = e.get("hypothesis", "?")
        adopted_str = "已采纳" if e.get("adopted") else "未采纳"
        lines.append(f"- **{eid}**: {hypothesis} → {conclusion} ({adopted_str})")

        best = e.get("best_candidate")
        if best:
            lines.append(f"  - 收益提升: +{best.get('improvement_pct', 0):.2f}%")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "history"

    if cmd == "history":
        history = get_experiment_history(30)
        print(f"\n=== 实验历史 (近30天, {len(history)}条) ===")
        for e in history:
            print(f"  {e.get('experiment_id', '?')}: "
                  f"{e.get('conclusion', '?')} "
                  f"({'adopted' if e.get('adopted') else 'not adopted'})")
    elif cmd == "report":
        print(generate_experiment_report())
    else:
        print("用法:")
        print("  python3 experiment_lab.py history  # 查看实验历史")
        print("  python3 experiment_lab.py report   # 生成实验报告")
