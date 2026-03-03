"""
VaR / CVaR 风险度量
==================
专业级组合风控:
  - Historical VaR (历史模拟法)
  - Parametric VaR (参数法, 正态假设)
  - CVaR / Expected Shortfall (条件VaR, 尾部风险)
  - 压力测试 (极端情景模拟)
  - 策略级 + 组合级风险度量
  - 接入晚报/Agent Brain

用法:
  python3 var_risk.py                    # 计算组合VaR
  python3 var_risk.py stress             # 压力测试
  python3 var_risk.py report             # 生成风控报告
"""

from __future__ import annotations

import os
import sys
import math
from datetime import date, datetime, timedelta
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("var_risk")

_DIR = os.path.dirname(os.path.abspath(__file__))
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_VAR_RESULTS_PATH = os.path.join(_DIR, "var_results.json")

# 置信水平
CONFIDENCE_LEVELS = [0.95, 0.99]

# 压力测试情景
STRESS_SCENARIOS = {
    "股灾暴跌": {"daily_shock": -0.08, "description": "单日大盘暴跌8%"},
    "连续阴跌": {"daily_shock": -0.02, "duration_days": 10, "description": "连续10天日跌2%"},
    "黑天鹅": {"daily_shock": -0.15, "description": "极端黑天鹅事件跌15%"},
    "流动性危机": {"daily_shock": -0.05, "vol_multiplier": 3.0, "description": "流动性枯竭, 波动率×3"},
    "缓慢复苏": {"daily_shock": 0.005, "duration_days": 20, "description": "缓慢反弹测试"},
}


# ================================================================
#  数据准备
# ================================================================

def _load_return_series(lookback_days: int = 60,
                        strategy: str = None) -> dict:
    """从 scorecard.json 加载收益率序列

    Args:
        lookback_days: 回望天数
        strategy: 指定策略 (None=全部)

    Returns:
        {
            "portfolio": [float],          # 组合每日平均收益率 (%)
            "by_strategy": {name: [float]}, # 分策略
            "dates": [str],                 # 日期序列
            "n_trades": int,                # 总交易笔数
        }
    """
    records = safe_load(_SCORECARD_PATH, default=[])
    if not records:
        return {"portfolio": [], "by_strategy": {}, "dates": [], "n_trades": 0}

    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    records = [r for r in records if r.get("rec_date", "") >= cutoff]

    if strategy:
        records = [r for r in records if r.get("strategy") == strategy]

    if not records:
        return {"portfolio": [], "by_strategy": {}, "dates": [], "n_trades": 0}

    # 按日聚合
    daily_agg = defaultdict(list)
    daily_by_strategy = defaultdict(lambda: defaultdict(list))

    for r in records:
        d = r.get("rec_date", "")
        ret = r.get("net_return_pct", 0)
        strat = r.get("strategy", "未知")
        daily_agg[d].append(ret)
        daily_by_strategy[strat][d].append(ret)

    dates = sorted(daily_agg.keys())
    portfolio_returns = [float(np.mean(daily_agg[d])) for d in dates]

    by_strategy = {}
    for strat, daily in daily_by_strategy.items():
        strat_dates = sorted(daily.keys())
        by_strategy[strat] = [float(np.mean(daily[d])) for d in strat_dates]

    return {
        "portfolio": portfolio_returns,
        "by_strategy": by_strategy,
        "dates": dates,
        "n_trades": len(records),
    }


# ================================================================
#  Historical VaR (历史模拟法)
# ================================================================

def calc_historical_var(returns: list[float],
                        confidence: float = 0.95) -> float:
    """历史模拟法 VaR

    VaR = 收益率分布的 (1-confidence) 分位数
    例: 95% VaR = 5th percentile

    Args:
        returns: 收益率序列 (%)
        confidence: 置信水平

    Returns:
        VaR 值 (%, 负数表示损失)
    """
    if not returns or len(returns) < 5:
        return 0.0

    arr = np.array(returns)
    percentile = (1 - confidence) * 100
    var = float(np.percentile(arr, percentile))
    return round(var, 4)


def calc_historical_cvar(returns: list[float],
                         confidence: float = 0.95) -> float:
    """历史模拟法 CVaR (Expected Shortfall)

    CVaR = VaR之下的平均损失
    比 VaR 更好地衡量尾部风险

    Returns:
        CVaR 值 (%, 负数表示损失)
    """
    if not returns or len(returns) < 5:
        return 0.0

    arr = np.array(returns)
    var = calc_historical_var(returns, confidence)
    tail = arr[arr <= var]

    if len(tail) == 0:
        return var

    return round(float(np.mean(tail)), 4)


# ================================================================
#  Parametric VaR (参数法)
# ================================================================

def calc_parametric_var(returns: list[float],
                        confidence: float = 0.95) -> float:
    """参数法 VaR (假设正态分布)

    VaR = μ - z * σ
    z(95%) = 1.645, z(99%) = 2.326

    Returns:
        VaR 值 (%)
    """
    if not returns or len(returns) < 5:
        return 0.0

    arr = np.array(returns)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr))

    if sigma < 1e-8:
        return 0.0

    # 正态分布分位数
    from scipy.stats import norm
    z = norm.ppf(1 - confidence)  # 负值
    var = mu + z * sigma

    return round(var, 4)


def calc_parametric_cvar(returns: list[float],
                         confidence: float = 0.95) -> float:
    """参数法 CVaR

    CVaR = μ - σ * φ(z) / (1-confidence)
    φ = 标准正态密度函数

    Returns:
        CVaR 值 (%)
    """
    if not returns or len(returns) < 5:
        return 0.0

    arr = np.array(returns)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr))

    if sigma < 1e-8:
        return 0.0

    from scipy.stats import norm
    z = norm.ppf(1 - confidence)
    phi_z = norm.pdf(z)  # 密度函数值
    cvar = mu - sigma * phi_z / (1 - confidence)

    return round(cvar, 4)


# ================================================================
#  蒙特卡洛 VaR
# ================================================================

def calc_monte_carlo_var(returns: list[float],
                         confidence: float = 0.95,
                         n_simulations: int = 10000,
                         horizon_days: int = 1) -> float:
    """蒙特卡洛模拟 VaR

    基于历史收益率的均值和标准差, 生成随机路径

    Args:
        returns: 历史收益率 (%)
        confidence: 置信水平
        n_simulations: 模拟次数
        horizon_days: 持有期 (天)

    Returns:
        VaR 值 (%)
    """
    if not returns or len(returns) < 10:
        return 0.0

    arr = np.array(returns)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr))

    if sigma < 1e-8:
        return 0.0

    rng = np.random.RandomState(42)

    # 模拟 horizon_days 天的累计收益
    if horizon_days == 1:
        simulated = rng.normal(mu, sigma, n_simulations)
    else:
        # 多日: 复利累计
        daily_returns = rng.normal(mu / 100, sigma / 100,
                                   (n_simulations, horizon_days))
        cumulative = np.prod(1 + daily_returns, axis=1) - 1
        simulated = cumulative * 100

    percentile = (1 - confidence) * 100
    var = float(np.percentile(simulated, percentile))

    return round(var, 4)


# ================================================================
#  压力测试
# ================================================================

def run_stress_test(returns: list[float],
                    capital: float = 100000) -> list[dict]:
    """运行预定义压力测试情景

    Args:
        returns: 历史收益率序列 (用于计算波动率)
        capital: 当前组合市值

    Returns:
        [{scenario, description, impact_pct, impact_amount, recovery_days_est}]
    """
    if not returns:
        return []

    arr = np.array(returns)
    daily_vol = float(np.std(arr)) / 100  # 转为小数
    avg_daily_ret = float(np.mean(arr)) / 100

    results = []
    for name, params in STRESS_SCENARIOS.items():
        shock = params["daily_shock"]
        duration = params.get("duration_days", 1)
        vol_mult = params.get("vol_multiplier", 1.0)

        # 计算冲击
        if duration == 1:
            impact_pct = shock * 100
        else:
            # 多日连续冲击 (复利)
            impact_pct = ((1 + shock) ** duration - 1) * 100

        # 波动率调整 (流动性危机等)
        adjusted_vol = daily_vol * vol_mult
        # 实际影响 = 冲击 + 额外波动
        vol_impact = adjusted_vol * np.sqrt(duration) * 1.5 * 100  # 1.5x 保守系数
        total_impact_pct = impact_pct - abs(vol_impact) if shock < 0 else impact_pct

        impact_amount = capital * total_impact_pct / 100

        # 估算恢复天数 (假设日均收益率正常)
        recovery_days = 0
        if total_impact_pct < 0 and avg_daily_ret > 0:
            recovery_days = int(abs(total_impact_pct) / (avg_daily_ret * 100))

        results.append({
            "scenario": name,
            "description": params["description"],
            "impact_pct": round(total_impact_pct, 2),
            "impact_amount": round(impact_amount, 0),
            "recovery_days_est": recovery_days,
            "vol_multiplier": vol_mult,
        })

    return results


# ================================================================
#  综合风险度量
# ================================================================

def calc_comprehensive_var(lookback_days: int = 60,
                           capital: float = 100000) -> dict:
    """计算综合风险度量

    Returns:
        {
            "portfolio": {var_95, var_99, cvar_95, cvar_99, ...},
            "by_strategy": {name: {var_95, var_99, ...}},
            "stress_test": [...],
            "risk_rating": "low" | "medium" | "high",
            "data_quality": {n_trades, n_days, sufficient},
        }
    """
    data = _load_return_series(lookback_days)

    portfolio_returns = data["portfolio"]
    n_trades = data["n_trades"]
    n_days = len(data["dates"])
    sufficient = n_days >= 20 and n_trades >= 30

    # 组合级
    portfolio_var = {}
    for conf in CONFIDENCE_LEVELS:
        pct = int(conf * 100)
        portfolio_var[f"hist_var_{pct}"] = calc_historical_var(portfolio_returns, conf)
        portfolio_var[f"hist_cvar_{pct}"] = calc_historical_cvar(portfolio_returns, conf)
        try:
            portfolio_var[f"param_var_{pct}"] = calc_parametric_var(portfolio_returns, conf)
            portfolio_var[f"param_cvar_{pct}"] = calc_parametric_cvar(portfolio_returns, conf)
        except ImportError:
            portfolio_var[f"param_var_{pct}"] = None
            portfolio_var[f"param_cvar_{pct}"] = None
        portfolio_var[f"mc_var_{pct}"] = calc_monte_carlo_var(portfolio_returns, conf)

    # 额外统计
    if portfolio_returns:
        arr = np.array(portfolio_returns)
        portfolio_var["daily_vol"] = round(float(np.std(arr)), 4)
        portfolio_var["annual_vol"] = round(float(np.std(arr) * np.sqrt(252)), 4)
        portfolio_var["max_daily_loss"] = round(float(np.min(arr)), 4)
        portfolio_var["max_daily_gain"] = round(float(np.max(arr)), 4)
        portfolio_var["skewness"] = round(float(
            np.mean(((arr - np.mean(arr)) / np.std(arr)) ** 3)
        ) if np.std(arr) > 0 else 0, 4)
        portfolio_var["kurtosis"] = round(float(
            np.mean(((arr - np.mean(arr)) / np.std(arr)) ** 4)
        ) if np.std(arr) > 0 else 0, 4)

    # 策略级
    by_strategy = {}
    for strat, rets in data["by_strategy"].items():
        if len(rets) < 5:
            continue
        strat_var = {}
        for conf in CONFIDENCE_LEVELS:
            pct = int(conf * 100)
            strat_var[f"hist_var_{pct}"] = calc_historical_var(rets, conf)
            strat_var[f"hist_cvar_{pct}"] = calc_historical_cvar(rets, conf)
        strat_var["daily_vol"] = round(float(np.std(rets)), 4)
        strat_var["n_days"] = len(rets)
        by_strategy[strat] = strat_var

    # 压力测试
    stress_results = run_stress_test(portfolio_returns, capital)

    # 风险评级
    var_95 = abs(portfolio_var.get("hist_var_95", 0))
    cvar_99 = abs(portfolio_var.get("hist_cvar_99", 0))
    annual_vol = abs(portfolio_var.get("annual_vol", 0))

    if cvar_99 > 5 or annual_vol > 40 or var_95 > 3:
        risk_rating = "high"
    elif cvar_99 > 2.5 or annual_vol > 25 or var_95 > 1.5:
        risk_rating = "medium"
    else:
        risk_rating = "low"

    result = {
        "timestamp": datetime.now().isoformat(),
        "lookback_days": lookback_days,
        "portfolio": portfolio_var,
        "by_strategy": by_strategy,
        "stress_test": stress_results,
        "risk_rating": risk_rating,
        "data_quality": {
            "n_trades": n_trades,
            "n_days": n_days,
            "sufficient": sufficient,
        },
    }

    # 持久化
    _save_var_results(result)

    return result


# ================================================================
#  报告生成
# ================================================================

def generate_var_report(result: dict = None) -> str:
    """生成风控报告 Markdown"""
    if result is None:
        result = calc_comprehensive_var()

    portfolio = result.get("portfolio", {})
    stress = result.get("stress_test", [])
    by_strategy = result.get("by_strategy", {})
    dq = result.get("data_quality", {})
    risk = result.get("risk_rating", "unknown")

    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")

    lines = [
        f"## VaR/CVaR 风控报告",
        f"时间: {result.get('timestamp', '?')[:19]}",
        f"回望: {result.get('lookback_days', '?')}天"
        f" ({dq.get('n_trades', 0)}笔交易, {dq.get('n_days', 0)}个交易日)",
        "",
        f"### 组合风险评级: {risk_emoji} {risk.upper()}",
        "",
    ]

    # 组合VaR表
    lines.append("### 组合 VaR / CVaR")
    lines.append("| 方法 | VaR (95%) | VaR (99%) | CVaR (95%) | CVaR (99%) |")
    lines.append("|------|-----------|-----------|------------|------------|")

    h95 = portfolio.get("hist_var_95", 0)
    h99 = portfolio.get("hist_var_99", 0)
    hc95 = portfolio.get("hist_cvar_95", 0)
    hc99 = portfolio.get("hist_cvar_99", 0)
    lines.append(f"| 历史模拟 | {h95:+.4f}% | {h99:+.4f}% | {hc95:+.4f}% | {hc99:+.4f}% |")

    p95 = portfolio.get("param_var_95")
    p99 = portfolio.get("param_var_99")
    pc95 = portfolio.get("param_cvar_95")
    pc99 = portfolio.get("param_cvar_99")
    if p95 is not None:
        lines.append(f"| 参数法 | {p95:+.4f}% | {p99:+.4f}% | {pc95:+.4f}% | {pc99:+.4f}% |")

    mc95 = portfolio.get("mc_var_95", 0)
    mc99 = portfolio.get("mc_var_99", 0)
    lines.append(f"| 蒙特卡洛 | {mc95:+.4f}% | {mc99:+.4f}% | - | - |")
    lines.append("")

    # 波动率统计
    lines.append("### 波动率统计")
    lines.append(f"- 日波动率: {portfolio.get('daily_vol', 0):.4f}%")
    lines.append(f"- 年化波动率: {portfolio.get('annual_vol', 0):.2f}%")
    lines.append(f"- 最大单日亏损: {portfolio.get('max_daily_loss', 0):+.4f}%")
    lines.append(f"- 最大单日盈利: {portfolio.get('max_daily_gain', 0):+.4f}%")
    lines.append(f"- 偏度: {portfolio.get('skewness', 0):.4f}"
                 f" ({'左偏(尾部风险大)' if portfolio.get('skewness', 0) < -0.5 else '基本对称'})")
    lines.append(f"- 峰度: {portfolio.get('kurtosis', 0):.4f}"
                 f" ({'厚尾' if portfolio.get('kurtosis', 0) > 4 else '正常'})")
    lines.append("")

    # 压力测试
    if stress:
        lines.append("### 压力测试")
        lines.append("| 情景 | 冲击 | 损失金额 | 预计恢复 |")
        lines.append("|------|------|----------|----------|")
        for s in stress:
            impact = s["impact_pct"]
            amount = s["impact_amount"]
            recovery = f"{s['recovery_days_est']}天" if s["recovery_days_est"] > 0 else "N/A"
            lines.append(
                f"| {s['scenario']} | {impact:+.2f}% | ¥{amount:,.0f} | {recovery} |"
            )
        lines.append("")

    # 分策略
    if by_strategy:
        lines.append("### 分策略风险")
        lines.append("| 策略 | VaR(95%) | CVaR(95%) | 日波动率 | 交易日 |")
        lines.append("|------|----------|-----------|----------|--------|")
        for strat, sv in sorted(by_strategy.items(),
                                key=lambda x: x[1].get("hist_var_95", 0)):
            lines.append(
                f"| {strat} "
                f"| {sv.get('hist_var_95', 0):+.4f}% "
                f"| {sv.get('hist_cvar_95', 0):+.4f}% "
                f"| {sv.get('daily_vol', 0):.4f}% "
                f"| {sv.get('n_days', 0)} |"
            )

    return "\n".join(lines)


# ================================================================
#  持久化
# ================================================================

def _save_var_results(result: dict):
    """保存VaR结果"""
    history = safe_load(_VAR_RESULTS_PATH, default=[])
    if not isinstance(history, list):
        history = []
    history.append(result)
    if len(history) > 30:
        history = history[-30:]
    safe_save(_VAR_RESULTS_PATH, history)


def get_latest_risk_rating() -> str:
    """获取最新风险评级"""
    history = safe_load(_VAR_RESULTS_PATH, default=[])
    if not history:
        return "unknown"
    return history[-1].get("risk_rating", "unknown")


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "var"

    if mode == "var":
        result = calc_comprehensive_var()
        print(generate_var_report(result))
    elif mode == "stress":
        data = _load_return_series(60)
        stress = run_stress_test(data["portfolio"])
        for s in stress:
            print(f"  {s['scenario']}: {s['impact_pct']:+.2f}%"
                  f" (¥{s['impact_amount']:,.0f})")
    elif mode == "report":
        result = calc_comprehensive_var()
        report = generate_var_report(result)
        print(report)
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw("VaR风控报告", report)
        except Exception as e:
            logger.error("推送失败: %s", e)
    else:
        print("用法:")
        print("  python3 var_risk.py              # 计算组合VaR")
        print("  python3 var_risk.py stress        # 压力测试")
        print("  python3 var_risk.py report        # 生成并推送报告")
        sys.exit(1)
