"""
策略参数自动调优
================
- 评估策略健康度 (基于实盘记分卡)
- 生成候选参数集 (微调权重)
- 回测验证效果
- 采纳/回滚管理
- 演化历史审计日志

数据文件:
  tunable_params.json   — 当前生效的覆盖参数
  evolution_history.json — 演化审计日志

用法:
  python3 auto_optimizer.py evaluate          # 查看各策略健康度
  python3 auto_optimizer.py optimize          # 立即优化
  python3 auto_optimizer.py history           # 查看演化历史
  python3 auto_optimizer.py rollback breakout # 手动回滚某策略
"""

from __future__ import annotations

import copy
import os
import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    BREAKOUT_PARAMS, AUCTION_PARAMS, AFTERNOON_PARAMS,
    DIP_BUY_PARAMS, CONSOLIDATION_PARAMS, TREND_FOLLOW_PARAMS, SECTOR_ROTATION_PARAMS,
    NEWS_EVENT_PARAMS,
    OPTIMIZATION_PARAMS,
)
from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("optimizer")

_DIR = os.path.dirname(os.path.abspath(__file__))
_TUNABLE_PATH = os.path.join(_DIR, "tunable_params.json")
_EVOLUTION_PATH = os.path.join(_DIR, "evolution_history.json")
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_SCORECARD_DEFAULT = _SCORECARD_PATH
_VERIFICATION_PATH = os.path.join(_DIR, "optimization_verifications.json")

# 支持的策略列表
SUPPORTED_STRATEGIES = [
    "breakout", "auction", "afternoon",
    "dip_buy", "consolidation", "trend_follow", "sector_rotation",
    "news_event", "futures_trend", "crypto_trend", "us_stock",
]


# ================================================================
#  参数读取
# ================================================================

def get_tunable_params(strategy: str) -> dict:
    """获取策略当前参数 (tunable_params.json 覆盖 > config.py 默认)

    供回测调用, 替代硬编码权重
    """
    tunable = safe_load(_TUNABLE_PATH, default={})

    if strategy in tunable and "weights" in tunable[strategy]:
        return tunable[strategy]

    # 返回 config.py 默认值
    defaults = _get_default_weights(strategy)
    if defaults:
        return {"weights": defaults}

    return {}


def _get_default_weights(strategy: str) -> dict:
    """获取策略的默认权重"""
    if strategy == "breakout":
        return copy.deepcopy(BREAKOUT_PARAMS["weights"])
    if strategy == "auction":
        return copy.deepcopy(AUCTION_PARAMS["weights"])
    if strategy == "afternoon":
        return copy.deepcopy(AFTERNOON_PARAMS["weights"])
    if strategy == "dip_buy":
        return copy.deepcopy(DIP_BUY_PARAMS["weights"])
    if strategy == "consolidation":
        return copy.deepcopy(CONSOLIDATION_PARAMS["weights"])
    if strategy == "trend_follow":
        return copy.deepcopy(TREND_FOLLOW_PARAMS["weights"])
    if strategy == "sector_rotation":
        return copy.deepcopy(SECTOR_ROTATION_PARAMS["weights"])
    if strategy == "news_event":
        return copy.deepcopy(NEWS_EVENT_PARAMS["weights"])
    if strategy == "futures_trend":
        from config import FUTURES_PARAMS
        return copy.deepcopy(FUTURES_PARAMS["weights"])
    return {}


# ================================================================
#  策略健康评估
# ================================================================

def evaluate_strategy_health(strategy: str, days: int = None) -> dict:
    """评估策略近期表现

    从 scorecard.json 读取数据, 返回:
      score (0-100), win_rate, avg_return, sample_count, trend
    score 计算: 胜率占40分 + 平均收益占40分 + 稳定性(收益标准差)占20分
    trend: 比较前半段 vs 后半段的平均收益
    """
    if days is None:
        days = OPTIMIZATION_PARAMS["eval_window_days"]

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        records = load_scorecard(days=days)
    except Exception:
        records = safe_load(_SCORECARD_PATH)
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    # 按策略名称匹配 (记分卡中策略名可能含中文后缀)
    strategy_map = {
        "breakout": "放量突破",
        "auction": "集合竞价",
        "afternoon": "尾盘短线",
        "dip_buy": "低吸回调",
        "consolidation": "缩量整理",
        "trend_follow": "趋势跟踪",
        "sector_rotation": "板块轮动",
        "news_event": "事件驱动",
        "futures_trend": "期货趋势",
    }
    keyword = strategy_map.get(strategy, strategy)

    filtered = [
        r for r in records
        if r.get("rec_date", "") >= cutoff
        and keyword in r.get("strategy", "")
    ]

    sample_count = len(filtered)
    if sample_count == 0:
        return {
            "strategy": strategy,
            "score": 50,
            "win_rate": 0,
            "avg_return": 0,
            "sample_count": 0,
            "trend": "insufficient_data",
            "details": "无评分数据",
        }

    # 胜率
    wins = sum(1 for r in filtered if r.get("result") == "win")
    win_rate = wins / sample_count * 100

    # 平均收益
    returns = [r.get("net_return_pct", 0) for r in filtered]
    avg_return = sum(returns) / len(returns)

    # 稳定性 (收益标准差)
    mean_r = avg_return
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_return = variance ** 0.5

    # --- score 计算 ---
    # 胜率得分 (40分): 50% → 20分, 60% → 32分, 70% → 40分
    wr_score = min(40, max(0, win_rate / 70 * 40))

    # 收益得分 (40分): 0% → 20分, 1% → 30分, 2% → 40分
    ret_score = min(40, max(0, (avg_return + 1) / 3 * 40))

    # 稳定性得分 (20分): std < 1 → 20分, std > 5 → 0分
    stab_score = max(0, min(20, (5 - std_return) / 4 * 20))

    score = round(wr_score + ret_score + stab_score)

    # --- trend 计算 ---
    half = sample_count // 2
    if half >= 2:
        first_half = returns[:half]
        second_half = returns[half:]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        diff = avg_second - avg_first
        if diff > 0.3:
            trend = "improving"
        elif diff < -0.3:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    return {
        "strategy": strategy,
        "score": score,
        "win_rate": round(win_rate, 1),
        "avg_return": round(avg_return, 2),
        "std_return": round(std_return, 2),
        "sample_count": sample_count,
        "trend": trend,
    }


# ================================================================
#  候选参数生成
# ================================================================

def generate_candidates(strategy: str, current_weights: dict,
                        n_candidates: int = 5) -> list[dict]:
    """生成候选参数集

    对每个权重 ±max_weight_delta 随机扰动, 归一化使总和=1
    生成 n_candidates 组候选参数
    """
    max_delta = OPTIMIZATION_PARAMS["max_weight_delta"]
    candidates = []

    for _ in range(n_candidates):
        new_weights = {}
        for key, val in current_weights.items():
            # 随机扰动
            delta = random.uniform(-max_delta, max_delta)
            new_val = max(0.01, val + delta)  # 保证最小值 > 0
            new_weights[key] = new_val

        # 归一化使总和 = 1.0
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}

        # 验证单次调整幅度
        valid = True
        for key in current_weights:
            if key in new_weights:
                if abs(new_weights[key] - current_weights[key]) > max_delta + 0.01:
                    valid = False
                    break

        if valid:
            candidates.append({"weights": new_weights})

    return candidates


# ================================================================
#  回测验证
# ================================================================

def validate_with_backtest(strategy: str, candidates: list[dict],
                           lookback_days: int = 90) -> dict | None:
    """用回测验证候选参数

    对每组候选调用 backtest_strategy(param_overrides=...)
    返回最优候选 (胜率和收益都优于当前) 或 None
    """
    if not OPTIMIZATION_PARAMS["backtest_validate"]:
        logger.info("回测验证已关闭, 跳过")
        return None

    try:
        from backtest import backtest_strategy
    except ImportError:
        logger.error("无法导入 backtest 模块")
        return None

    # 先获取当前参数的回测基线
    logger.info("回测基线 (当前参数)...")
    baseline = backtest_strategy(strategy, lookback_days)
    if baseline.get("error") or baseline.get("total_trades", 0) == 0:
        logger.warning("基线回测失败或无交易, 跳过优化")
        return None

    baseline_wr = baseline["win_rate"]
    baseline_ar = baseline["avg_return"]
    threshold = OPTIMIZATION_PARAMS["improve_threshold_pct"]

    best = None
    best_improvement = 0

    for i, candidate in enumerate(candidates):
        logger.info("回测候选 %d/%d ...", i + 1, len(candidates))
        try:
            result = backtest_strategy(
                strategy, lookback_days,
                param_overrides=candidate
            )
            if result.get("error") or result.get("total_trades", 0) == 0:
                continue

            wr = result["win_rate"]
            ar = result["avg_return"]

            # 胜率和收益都需要优于基线
            wr_improve = wr - baseline_wr
            ar_improve = ar - baseline_ar

            if wr_improve >= 0 and ar_improve >= threshold:
                total_improve = wr_improve + ar_improve * 10
                if total_improve > best_improvement:
                    best_improvement = total_improve
                    best = {
                        "weights": candidate["weights"],
                        "backtest": {
                            "win_rate": wr,
                            "avg_return": ar,
                            "total_return": result.get("total_return", 0),
                        },
                        "improvement": {
                            "win_rate": f"+{wr_improve:.1f}%",
                            "avg_return": f"+{ar_improve:.2f}%",
                        },
                    }
        except Exception as e:
            logger.warning("候选 %d 回测异常: %s", i + 1, e)

    if best:
        logger.info("找到更优参数: 胜率 %s, 收益 %s",
                     best["improvement"]["win_rate"],
                     best["improvement"]["avg_return"])
    else:
        logger.info("未找到优于当前的候选参数")

    return best


# ================================================================
#  采纳 / 回滚
# ================================================================

def apply_optimization(strategy: str, new_weights: dict, reason: str,
                       improvement: dict = None, backtest_result: dict = None):
    """采纳新参数: 写入 tunable_params.json + 记录 evolution_history.json"""
    tunable = safe_load(_TUNABLE_PATH, default={})

    old_weights = {}
    old_version = 0
    if strategy in tunable:
        old_weights = tunable[strategy].get("weights", {})
        old_version = tunable[strategy].get("version", 0)

    new_version = old_version + 1
    tunable[strategy] = {
        "weights": new_weights,
        "updated_at": date.today().isoformat(),
        "version": new_version,
        "previous_weights": old_weights,
    }
    safe_save(_TUNABLE_PATH, tunable)

    # 记录演化历史
    history = safe_load(_EVOLUTION_PATH)
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy,
        "action": "adopt",
        "reason": reason,
        "old_weights": old_weights,
        "new_weights": new_weights,
        "version": new_version,
        "improvement": improvement or {},
        "backtest_result": backtest_result or {},
    })
    safe_save(_EVOLUTION_PATH, history)

    logger.info("采纳新参数 v%d: %s — %s", new_version, strategy, reason)

    # 自动调度验证
    try:
        schedule_verification(strategy, old_weights, reason)
    except Exception as e:
        logger.debug("调度验证异常: %s", e)


def rollback_strategy(strategy: str, reason: str = "手动回滚"):
    """回滚策略参数到上一版本"""
    tunable = safe_load(_TUNABLE_PATH, default={})

    if strategy not in tunable:
        logger.warning("策略 %s 无可回滚参数", strategy)
        return False

    prev = tunable[strategy].get("previous_weights")
    if not prev:
        logger.warning("策略 %s 无前一版本参数", strategy)
        return False

    old_weights = tunable[strategy].get("weights", {})
    old_version = tunable[strategy].get("version", 0)

    tunable[strategy] = {
        "weights": prev,
        "updated_at": date.today().isoformat(),
        "version": old_version + 1,
        "previous_weights": old_weights,
    }
    safe_save(_TUNABLE_PATH, tunable)

    # 记录历史
    history = safe_load(_EVOLUTION_PATH)
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy,
        "action": "rollback",
        "reason": reason,
        "old_weights": old_weights,
        "new_weights": prev,
        "version": old_version + 1,
    })
    safe_save(_EVOLUTION_PATH, history)

    logger.info("已回滚 %s 到 v%d: %s", strategy, old_version + 1, reason)
    return True


def rollback_if_declined(strategy: str):
    """回滚检查: 采纳后若 7 天表现比采纳前差, 恢复旧参数"""
    if not OPTIMIZATION_PARAMS["rollback_on_decline"]:
        return

    tunable = safe_load(_TUNABLE_PATH, default={})
    if strategy not in tunable:
        return

    updated_at = tunable[strategy].get("updated_at", "")
    if not updated_at:
        return

    # 检查是否已过 7 天
    try:
        adopt_date = datetime.strptime(updated_at, "%Y-%m-%d").date()
    except ValueError:
        return

    days_since = (date.today() - adopt_date).days
    if days_since < 7:
        return

    prev_weights = tunable[strategy].get("previous_weights")
    if not prev_weights:
        return

    # 评估采纳后的表现
    health = evaluate_strategy_health(strategy, days=7)
    if health["sample_count"] < 3:
        return

    # 评估采纳前的基线 (用更早的数据)
    baseline = evaluate_strategy_health(strategy, days=14)

    # 如果采纳后得分明显下降, 回滚
    if health["score"] < baseline["score"] - 10:
        logger.warning("策略 %s 采纳后表现下降 (score %d → %d), 触发回滚",
                       strategy, baseline["score"], health["score"])
        rollback_strategy(strategy, reason=f"自动回滚: 得分从 {baseline['score']} 降至 {health['score']}")


# ================================================================
#  反恐慌机制
# ================================================================

def _check_panic_freeze(strategy: str) -> bool:
    """连续 3 天大幅亏损时冻结优化 (避免追涨杀跌式调参)"""
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        records = load_scorecard(days=3)
    except Exception:
        records = safe_load(_SCORECARD_PATH)
    cutoff = (date.today() - timedelta(days=3)).isoformat()

    strategy_map = {
        "breakout": "放量突破",
        "auction": "集合竞价",
        "afternoon": "尾盘短线",
        "dip_buy": "低吸回调",
        "consolidation": "缩量整理",
        "trend_follow": "趋势跟踪",
        "sector_rotation": "板块轮动",
        "news_event": "事件驱动",
        "futures_trend": "期货趋势",
    }
    keyword = strategy_map.get(strategy, strategy)

    recent = [
        r for r in records
        if r.get("rec_date", "") >= cutoff
        and keyword in r.get("strategy", "")
    ]

    if len(recent) < 3:
        return False

    # 检查最近 3 条是否都大幅亏损 (< -2%)
    sorted_recent = sorted(recent, key=lambda x: x.get("rec_date", ""), reverse=True)[:3]
    all_big_loss = all(r.get("net_return_pct", 0) < -2.0 for r in sorted_recent)

    if all_big_loss:
        logger.warning("策略 %s 连续大幅亏损, 冻结优化", strategy)
    return all_big_loss


# ================================================================
#  每日优化 / 周末深度搜索
# ================================================================

def run_daily_optimization():
    """每日优化 (16:00 收盘后运行)

    流程:
      1. 对每个策略 evaluate_strategy_health()
      2. score < 60 的策略 → generate_candidates → validate → apply
      3. 已优化的策略 → rollback_if_declined 检查
    """
    logger.info("=" * 50)
    logger.info("每日策略优化开始")
    logger.info("=" * 50)

    min_samples = OPTIMIZATION_PARAMS["min_samples"]

    for strategy in SUPPORTED_STRATEGIES:
        try:
            # 反恐慌检查
            if _check_panic_freeze(strategy):
                continue

            # 评估健康度
            health = evaluate_strategy_health(strategy)
            logger.info("[%s] 健康度: score=%d, 胜率=%.1f%%, 收益=%.2f%%, 趋势=%s (n=%d)",
                        strategy, health["score"], health["win_rate"],
                        health["avg_return"], health["trend"], health["sample_count"])

            # 回滚检查
            rollback_if_declined(strategy)

            # 样本不足
            if health["sample_count"] < min_samples:
                logger.info("[%s] 样本不足 (%d < %d), 跳过优化",
                            strategy, health["sample_count"], min_samples)
                continue

            # 得分足够高, 无需优化
            if health["score"] >= 60:
                logger.info("[%s] 表现良好 (score=%d >= 60), 无需优化", strategy, health["score"])
                continue

            # 生成候选参数
            current = get_tunable_params(strategy)
            current_weights = current.get("weights")
            if not current_weights:
                logger.info("[%s] 无可优化权重, 跳过", strategy)
                continue

            logger.info("[%s] 得分偏低 (%d), 生成候选参数...", strategy, health["score"])
            candidates = generate_candidates(strategy, current_weights, n_candidates=5)

            if not candidates:
                logger.warning("[%s] 候选参数生成失败", strategy)
                continue

            # 回测验证
            best = validate_with_backtest(strategy, candidates, lookback_days=90)
            if best:
                apply_optimization(
                    strategy, best["weights"],
                    reason="每日优化",
                    improvement=best.get("improvement"),
                    backtest_result=best.get("backtest"),
                )
            else:
                logger.info("[%s] 未找到更优参数", strategy)

        except Exception as e:
            logger.error("[%s] 优化异常: %s", strategy, e, exc_info=True)

    logger.info("每日策略优化完成")


def run_weekend_broad_search():
    """周末深度搜索 (样本更大, 候选更多)

    - generate 10 组候选 (vs 每日 5 组)
    - backtest 用 180 天 (vs 每日 90 天)
    """
    logger.info("=" * 50)
    logger.info("周末深度优化搜索开始")
    logger.info("=" * 50)

    for strategy in SUPPORTED_STRATEGIES:
        try:
            current = get_tunable_params(strategy)
            current_weights = current.get("weights")
            if not current_weights:
                continue

            health = evaluate_strategy_health(strategy, days=30)
            logger.info("[%s] 近30天健康度: score=%d, 胜率=%.1f%%, 收益=%.2f%%",
                        strategy, health["score"], health["win_rate"], health["avg_return"])

            # 周末不管得分高低都搜索
            candidates = generate_candidates(strategy, current_weights, n_candidates=10)
            if not candidates:
                continue

            best = validate_with_backtest(strategy, candidates, lookback_days=180)
            if best:
                apply_optimization(
                    strategy, best["weights"],
                    reason="周末深度搜索",
                    improvement=best.get("improvement"),
                    backtest_result=best.get("backtest"),
                )
            else:
                logger.info("[%s] 周末搜索未找到更优参数", strategy)

        except Exception as e:
            logger.error("[%s] 周末搜索异常: %s", strategy, e, exc_info=True)

    logger.info("周末深度优化搜索完成")


# ================================================================
#  验证闭环 — 采纳后自动验证, 变差自动回滚
# ================================================================

def schedule_verification(strategy: str, old_weights: dict, reason: str):
    """采纳后记录待验证条目 (5 天后自动检查)"""
    pre_health = evaluate_strategy_health(strategy)
    entry = {
        "strategy": strategy,
        "change_date": date.today().isoformat(),
        "pre_score": pre_health.get("score", 50),
        "pre_win_rate": pre_health.get("win_rate", 0),
        "pre_avg_return": pre_health.get("avg_return", 0),
        "verify_after_days": OPTIMIZATION_PARAMS.get("verify_after_days", 5),
        "status": "pending",
        "reason": reason,
    }
    vlist = safe_load(_VERIFICATION_PATH, default=[])
    vlist.append(entry)
    safe_save(_VERIFICATION_PATH, vlist)
    logger.info("[验证] 已调度 %s 验证 (%d天后)", strategy, entry["verify_after_days"])


def check_pending_verifications() -> list:
    """检查所有待验证的优化, 到期则评估, 变差则回滚

    Returns:
        验证结果列表 [{strategy, verdict, pre_score, post_score}]
    """
    vlist = safe_load(_VERIFICATION_PATH, default=[])
    results = []
    changed = False
    min_samples = OPTIMIZATION_PARAMS.get("verify_min_samples", 3)
    score_limit = OPTIMIZATION_PARAMS.get("verify_score_drop_limit", -5)

    for v in vlist:
        if v.get("status") != "pending":
            continue
        change_date = v.get("change_date") or v.get("adopt_date", "")
        try:
            dt = datetime.strptime(change_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        days_since = (date.today() - dt).days
        verify_days = v.get("verify_after_days", 5)
        if days_since < verify_days:
            continue

        strategy = v.get("strategy")
        post_health = evaluate_strategy_health(strategy, days=verify_days)

        if post_health.get("sample_count", 0) < min_samples:
            # 数据不足, 延长验证窗口
            v["verify_after_days"] = verify_days + 3
            changed = True
            logger.info("[验证] %s 样本不足, 延长验证期至 %d 天", strategy, v["verify_after_days"])
            continue

        pre_score = v.get("pre_score", 50)
        post_score = post_health.get("score", 50)

        v["post_score"] = post_score
        v["post_win_rate"] = post_health.get("win_rate", 0)
        v["post_avg_return"] = post_health.get("avg_return", 0)
        v["verified_at"] = date.today().isoformat()

        if post_score < pre_score + score_limit:
            rollback_strategy(
                strategy,
                reason=f"验证失败: 得分 {pre_score}→{post_score} (下降>{abs(score_limit)})",
            )
            v["status"] = "rolled_back"
            results.append({
                "strategy": strategy, "verdict": "rolled_back",
                "pre_score": pre_score, "post_score": post_score,
            })
            logger.warning("[验证] %s 优化后表现恶化 (%d→%d), 已回滚",
                           strategy, pre_score, post_score)
        else:
            v["status"] = "verified_ok"
            results.append({
                "strategy": strategy, "verdict": "verified_ok",
                "pre_score": pre_score, "post_score": post_score,
            })
            logger.info("[验证] %s 优化验证通过 (%d→%d)", strategy, pre_score, post_score)

        changed = True

    if changed:
        safe_save(_VERIFICATION_PATH, vlist)
    return results


# ================================================================
#  因子生命周期 — 衰减降权 / 淘汰
# ================================================================

def deweight_factor(strategy: str, factor_name: str,
                    reason: str = "因子衰减") -> bool:
    """降低特定因子权重 (减半), 重新分配给其他因子

    Returns:
        True if successfully deweighted
    """
    params = get_tunable_params(strategy)
    weights = params.get("weights", {})
    if factor_name not in weights:
        return False

    old_weight = weights[factor_name]
    if old_weight <= 0.02:
        return False  # 已经最低, 不再降

    new_weight = round(max(0.01, old_weight * 0.5), 4)
    freed = old_weight - new_weight

    new_weights = dict(weights)
    new_weights[factor_name] = new_weight

    # 释放的权重按比例分配给其他因子
    others = {k: v for k, v in new_weights.items() if k != factor_name and v > 0}
    if others:
        others_total = sum(others.values())
        for k in others:
            new_weights[k] = round(
                new_weights[k] + freed * (new_weights[k] / others_total), 4
            )

    # 归一化
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}

    apply_optimization(
        strategy, new_weights,
        reason=f"{reason}: {factor_name} {old_weight:.4f}→{new_weight:.4f}",
    )
    logger.info("[因子生命周期] %s: %s 降权 %.4f→%.4f",
                strategy, factor_name, old_weight, new_weight)
    return True


def check_factor_lifecycle() -> list:
    """检查所有策略中权重过低的因子, 必要时降权/淘汰

    Returns:
        操作列表 [{strategy, factor, action}]
    """
    min_threshold = OPTIMIZATION_PARAMS.get("factor_min_weight", 0.03)
    max_per_cycle = OPTIMIZATION_PARAMS.get("max_deweight_per_cycle", 1)
    results = []

    for strategy in SUPPORTED_STRATEGIES:
        params = get_tunable_params(strategy)
        weights = params.get("weights", {})

        # 找出权重低于阈值且 > 0 的因子 (候选淘汰)
        dying = [(k, v) for k, v in weights.items()
                 if 0 < v < min_threshold]
        dying.sort(key=lambda x: x[1])  # 最低的先处理

        count = 0
        for factor, weight in dying:
            if count >= max_per_cycle:
                break
            if deweight_factor(strategy, factor, reason="因子权重低于阈值"):
                results.append({
                    "strategy": strategy, "factor": factor,
                    "old_weight": weight, "action": "deweighted",
                })
                count += 1

    return results


# ================================================================
#  优化建议摘要 (供周报)
# ================================================================

def generate_optimization_summary() -> str:
    """生成优化建议摘要 (Markdown, 随周报一起推送)"""
    lines = ["## 策略优化报告"]

    # 各策略健康度
    lines.append("\n### 策略健康度")
    lines.append("| 策略 | 得分 | 胜率 | 平均收益 | 趋势 | 样本数 |")
    lines.append("|------|------|------|----------|------|--------|")
    for strategy in SUPPORTED_STRATEGIES:
        h = evaluate_strategy_health(strategy)
        trend_map = {
            "improving": "上升",
            "stable": "稳定",
            "declining": "下降",
            "insufficient_data": "数据不足",
        }
        trend_label = trend_map.get(h["trend"], h["trend"])
        lines.append(f"| {strategy} | {h['score']} | {h['win_rate']:.1f}% "
                     f"| {h['avg_return']:+.2f}% | {trend_label} | {h['sample_count']} |")

    # 最近演化历史
    history = safe_load(_EVOLUTION_PATH)
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    recent = [h for h in history if h.get("date", "")[:10] >= week_ago]

    if recent:
        lines.append("\n### 本周优化动作")
        for h in recent:
            action_map = {"adopt": "采纳", "rollback": "回滚"}
            action = action_map.get(h.get("action"), h.get("action"))
            lines.append(f"- {h['date'][:10]} {h['strategy']} — {action}: {h.get('reason', '')}")
    else:
        lines.append("\n### 本周优化动作\n- 本周无优化动作")

    # 当前覆盖参数
    tunable = safe_load(_TUNABLE_PATH, default={})
    if tunable:
        lines.append("\n### 当前推荐参数版本")
        for strategy, params in tunable.items():
            v = params.get("version", 0)
            updated = params.get("updated_at", "")
            lines.append(f"- {strategy}: v{v} (更新于 {updated})")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

def _cli_evaluate():
    """CLI: 查看各策略健康度"""
    print("\n" + "=" * 60)
    print("  策略健康度评估")
    print("=" * 60)

    for strategy in SUPPORTED_STRATEGIES:
        h = evaluate_strategy_health(strategy)
        trend_map = {
            "improving": "↑ 上升",
            "stable": "→ 稳定",
            "declining": "↓ 下降",
            "insufficient_data": "? 数据不足",
        }
        print(f"\n  [{strategy}]")
        print(f"    得分: {h['score']}/100")
        print(f"    胜率: {h['win_rate']:.1f}%")
        print(f"    平均收益: {h['avg_return']:+.2f}%")
        print(f"    趋势: {trend_map.get(h['trend'], h['trend'])}")
        print(f"    样本数: {h['sample_count']}")

    print("\n" + "=" * 60)


def _cli_history():
    """CLI: 查看演化历史"""
    history = safe_load(_EVOLUTION_PATH)
    if not history:
        print("暂无演化历史")
        return

    print("\n" + "=" * 60)
    print("  演化历史")
    print("=" * 60)

    for h in history[-20:]:  # 最近 20 条
        action_map = {"adopt": "采纳", "rollback": "回滚"}
        action = action_map.get(h.get("action"), h.get("action"))
        imp = h.get("improvement", {})
        imp_str = ""
        if imp:
            imp_str = f" (胜率{imp.get('win_rate', '')}, 收益{imp.get('avg_return', '')})"
        print(f"  {h['date']} | {h['strategy']:10s} | {action} | {h.get('reason', '')}{imp_str}")

    print("=" * 60)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "evaluate":
        _cli_evaluate()
    elif mode == "optimize":
        run_daily_optimization()
    elif mode == "weekend":
        run_weekend_broad_search()
    elif mode == "history":
        _cli_history()
    elif mode == "rollback":
        if len(sys.argv) > 2:
            strategy = sys.argv[2]
            rollback_strategy(strategy, reason="CLI手动回滚")
        else:
            print("用法: python3 auto_optimizer.py rollback <strategy>")
    elif mode == "summary":
        print(generate_optimization_summary())
    else:
        print("用法:")
        print("  python3 auto_optimizer.py evaluate          # 查看各策略健康度")
        print("  python3 auto_optimizer.py optimize          # 立即每日优化")
        print("  python3 auto_optimizer.py weekend           # 周末深度搜索")
        print("  python3 auto_optimizer.py history           # 查看演化历史")
        print("  python3 auto_optimizer.py rollback breakout # 手动回滚某策略")
        print("  python3 auto_optimizer.py summary           # 优化摘要")
        sys.exit(1)
