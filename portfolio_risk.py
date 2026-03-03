"""
组合层全局风控 — 跨策略相关性 / 全局回撤 / 动态资金分配
==========================================================
从单策略风控升级到组合层全局视角:
  - 计算策略间收益相关系数矩阵
  - 组合层回撤监控
  - 基于健康度+相关性动态建议资金分配
  - 产生组合层 findings 供 agent_brain 决策

CLI:
  python3 portfolio_risk.py check    # 组合风控检查
  python3 portfolio_risk.py report   # 生成组合风控报告
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load
from config import PORTFOLIO_RISK_PARAMS
from log_config import get_logger

logger = get_logger("portfolio_risk")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCORECARD_PATH = os.path.join(_BASE_DIR, "scorecard.json")

STRATEGY_NAMES = [
    "集合竞价选股", "放量突破选股", "尾盘短线选股",
    "低吸回调选股", "缩量整理选股", "趋势跟踪选股", "板块轮动选股",
    "事件驱动选股", "期货趋势选股", "币圈趋势选股", "美股收盘分析",
]


# ================================================================
#  策略间收益相关系数矩阵
# ================================================================

def calc_strategy_correlation(days: int = None) -> dict:
    """计算策略间日收益的 Pearson 相关系数矩阵

    Returns:
        {
            "matrix": {("A","B"): corr, ...},
            "diversification_score": float,  # 0-100, 越高越分散
            "dominant_pair": (str, str) | None,
        }
    """
    if days is None:
        days = PORTFOLIO_RISK_PARAMS.get("correlation_window_days", 30)

    scorecard = safe_load(_SCORECARD_PATH, default=[])
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    # 按策略+日期聚合日收益
    daily_returns = {}  # {strategy: {date: avg_return}}
    for r in scorecard:
        rec_date = r.get("rec_date", "")
        if rec_date < cutoff:
            continue
        strategy = r.get("strategy", "")
        ret = r.get("net_return_pct", 0)
        daily_returns.setdefault(strategy, {}).setdefault(rec_date, []).append(ret)

    # 平均每日收益
    strategy_series = {}
    for strategy in STRATEGY_NAMES:
        raw = daily_returns.get(strategy, {})
        series = {}
        for d, rets in raw.items():
            series[d] = sum(rets) / len(rets)
        strategy_series[strategy] = series

    # 获取所有共同日期
    all_dates = set()
    for series in strategy_series.values():
        all_dates |= set(series.keys())

    # 计算两两相关系数
    matrix = {}
    pairs = []
    for i, a in enumerate(STRATEGY_NAMES):
        for b in STRATEGY_NAMES[i + 1:]:
            common_dates = sorted(
                set(strategy_series[a].keys()) & set(strategy_series[b].keys())
            )
            if len(common_dates) < 3:
                matrix[(a, b)] = 0.0
                continue
            xs = [strategy_series[a][d] for d in common_dates]
            ys = [strategy_series[b][d] for d in common_dates]
            corr = _pearson(xs, ys)
            matrix[(a, b)] = round(corr, 4)
            pairs.append(((a, b), corr))

    # 分散度评分: 100 - avg_abs_corr * 100
    if pairs:
        avg_abs_corr = sum(abs(c) for _, c in pairs) / len(pairs)
        diversification_score = round(max(0, (1 - avg_abs_corr)) * 100, 1)
    else:
        diversification_score = 100.0

    # 最高相关的一对
    dominant_pair = None
    if pairs:
        pairs.sort(key=lambda x: abs(x[1]), reverse=True)
        dominant_pair = pairs[0][0]

    return {
        "matrix": matrix,
        "diversification_score": diversification_score,
        "dominant_pair": dominant_pair,
    }


def _pearson(xs: list, ys: list) -> float:
    """计算 Pearson 相关系数"""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (var_x * var_y) ** 0.5
    if denom < 1e-10:
        return 0.0
    return cov / denom


# ================================================================
#  组合层回撤
# ================================================================

def calc_portfolio_drawdown() -> dict:
    """计算组合层回撤 (合并所有策略日收益)

    Returns:
        {
            "current_drawdown_pct": float,
            "max_drawdown_pct": float,
            "drawdown_days": int,
            "nav": float,
            "breached": bool,
        }
    """
    scorecard = safe_load(_SCORECARD_PATH, default=[])
    if not scorecard:
        return {
            "current_drawdown_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "drawdown_days": 0,
            "nav": 1.0,
            "breached": False,
        }

    # 按日期聚合所有策略的平均收益
    daily_agg = {}
    for r in scorecard:
        rec_date = r.get("rec_date", "")
        ret = r.get("net_return_pct", 0)
        daily_agg.setdefault(rec_date, []).append(ret)

    dates = sorted(daily_agg.keys())
    if not dates:
        return {
            "current_drawdown_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "drawdown_days": 0,
            "nav": 1.0,
            "breached": False,
        }

    # 计算 NAV 序列
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    dd_start = None
    dd_days = 0

    for d in dates:
        rets = daily_agg[d]
        avg_ret = sum(rets) / len(rets)
        nav *= (1 + avg_ret / 100)
        if nav > peak:
            peak = nav
            dd_start = None
        dd = (nav - peak) / peak * 100 if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd
        if dd < 0 and dd_start is None:
            dd_start = d

    current_dd = (nav - peak) / peak * 100 if peak > 0 else 0

    # 计算连续回撤天数
    if dd_start is not None:
        dd_days = sum(1 for d in dates if d >= dd_start)

    max_dd_threshold = PORTFOLIO_RISK_PARAMS.get("max_portfolio_drawdown_pct", -8.0)
    breached = current_dd <= max_dd_threshold

    return {
        "current_drawdown_pct": round(current_dd, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "drawdown_days": dd_days,
        "nav": round(nav, 4),
        "breached": breached,
    }


# ================================================================
#  动态资金分配建议
# ================================================================

def suggest_allocation(strategy_health: dict = None) -> dict:
    """基于健康度+相关性建议资金分配

    Args:
        strategy_health: {strategy_name: health_dict} from auto_optimizer

    Returns:
        {
            "allocation": {strategy: pct},
            "reason": str,
            "changes": [{strategy, old, new, reason}],
        }
    """
    default_alloc = PORTFOLIO_RISK_PARAMS.get("strategy_allocation", {})
    max_alloc = PORTFOLIO_RISK_PARAMS.get("max_strategy_allocation", 0.50)
    min_alloc = PORTFOLIO_RISK_PARAMS.get("min_strategy_allocation", 0.10)

    if not strategy_health:
        return {
            "allocation": dict(default_alloc),
            "reason": "无健康度数据, 保持默认等权分配",
            "changes": [],
        }

    # 计算健康度加权分配
    scores = {}
    for name in STRATEGY_NAMES:
        health = strategy_health.get(name, {})
        scores[name] = health.get("score", 50)

    total_score = sum(scores.values())
    if total_score <= 0:
        return {
            "allocation": dict(default_alloc),
            "reason": "所有策略评分为0, 保持默认分配",
            "changes": [],
        }

    # 按健康度加权
    raw_alloc = {name: score / total_score for name, score in scores.items()}

    # 应用上下限
    allocation = {}
    for name, pct in raw_alloc.items():
        allocation[name] = max(min_alloc, min(max_alloc, pct))

    # 重新归一化
    total = sum(allocation.values())
    if total > 0:
        allocation = {k: round(v / total, 4) for k, v in allocation.items()}

    # 计算变化
    changes = []
    threshold = PORTFOLIO_RISK_PARAMS.get("rebalance_threshold", 0.15)
    for name in STRATEGY_NAMES:
        old = default_alloc.get(name, 0.33)
        new = allocation.get(name, 0.33)
        if abs(new - old) >= threshold:
            direction = "增加" if new > old else "减少"
            changes.append({
                "strategy": name,
                "old": round(old, 4),
                "new": round(new, 4),
                "reason": f"{direction}配比 ({old:.0%}→{new:.0%}), 健康度={scores.get(name, 0):.0f}",
            })

    reason = "基于策略健康度动态分配" if changes else "各策略健康度接近, 无需调整"

    return {
        "allocation": allocation,
        "reason": reason,
        "changes": changes,
    }


# ================================================================
#  组合风控检查 (主入口)
# ================================================================

def check_portfolio_risk(emit_events: bool = False) -> dict:
    """组合风控检查, 产出 findings 列表

    Args:
        emit_events: 是否将风控发现发射到事件总线

    Returns:
        {
            "findings": [finding_dict, ...],
            "drawdown": drawdown_dict,
            "correlation": correlation_dict,
            "allocation_suggestion": allocation_dict,
        }
    """
    if not PORTFOLIO_RISK_PARAMS.get("enabled", True):
        return {"findings": [], "drawdown": {}, "correlation": {},
                "allocation_suggestion": {}}

    findings = []

    # 1. 回撤检查
    drawdown = calc_portfolio_drawdown()
    if drawdown.get("breached"):
        findings.append({
            "type": "anomaly",
            "severity": "critical",
            "strategy": None,
            "message": (f"组合回撤 {drawdown['current_drawdown_pct']:.1f}% "
                        f"超过阈值 {PORTFOLIO_RISK_PARAMS['max_portfolio_drawdown_pct']}%, "
                        f"连续 {drawdown['drawdown_days']} 天"),
            "suggested_action": "escalate_human",
            "confidence": 0.95,
            "source": "portfolio_risk",
        })

    # 2. 相关性检查
    correlation = calc_strategy_correlation()
    for pair, corr in correlation.get("matrix", {}).items():
        if corr > 0.7:
            findings.append({
                "type": "anomaly",
                "severity": "warning",
                "strategy": None,
                "message": (f"策略 {pair[0]} 与 {pair[1]} 收益高度相关 "
                            f"({corr:.2f}), 分散化不足"),
                "suggested_action": "log_insight",
                "confidence": 0.70,
                "source": "portfolio_risk",
            })

    # 3. 资金分配检查
    try:
        from auto_optimizer import evaluate_strategy_health
        health = {}
        strategy_map = {
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
        for name in STRATEGY_NAMES:
            eng_name = strategy_map.get(name, name)
            h = evaluate_strategy_health(eng_name)
            health[name] = h
    except Exception:
        health = {}

    allocation_suggestion = suggest_allocation(health)
    if allocation_suggestion.get("changes"):
        findings.append({
            "type": "anomaly",
            "severity": "info",
            "strategy": None,
            "message": f"建议调整资金分配: {allocation_suggestion['reason']}",
            "suggested_action": "log_insight",
            "confidence": 0.60,
            "source": "portfolio_risk",
        })

    result = {
        "findings": findings,
        "drawdown": drawdown,
        "correlation": correlation,
        "allocation_suggestion": allocation_suggestion,
    }

    # 发射风控事件到事件总线
    if emit_events and findings:
        try:
            from event_bus import get_event_bus, Priority
            bus = get_event_bus()
            for f in findings:
                severity = f.get("severity", "info")
                priority = Priority.CRITICAL if severity == "critical" else (
                    Priority.URGENT if severity == "warning" else Priority.NORMAL)
                bus.emit(
                    source="portfolio_risk",
                    priority=priority,
                    event_type="drawdown_breach" if "回撤" in f.get("message", "") else "correlation_warning",
                    category="risk",
                    payload={
                        "message": f.get("message", ""),
                        "strategy": f.get("strategy"),
                    },
                )
        except Exception:
            pass

    # 更新注册表健康度
    try:
        from agent_registry import get_registry
        registry = get_registry()
        has_critical = any(f.get("severity") == "critical" for f in findings)
        registry.report_run("risk_inspector", success=not has_critical,
                            error_msg="组合回撤超限" if has_critical else None)
    except Exception:
        pass

    return result


# ================================================================
#  组合风控报告
# ================================================================

def generate_portfolio_report() -> str:
    """生成组合风控 Markdown 报告"""
    result = check_portfolio_risk()
    drawdown = result.get("drawdown", {})
    correlation = result.get("correlation", {})
    alloc = result.get("allocation_suggestion", {})
    findings = result.get("findings", [])

    lines = ["## 组合风控报告", ""]

    # 回撤
    lines.append("### 组合回撤")
    lines.append(f"- 当前回撤: {drawdown.get('current_drawdown_pct', 0):.2f}%")
    lines.append(f"- 最大回撤: {drawdown.get('max_drawdown_pct', 0):.2f}%")
    lines.append(f"- 回撤天数: {drawdown.get('drawdown_days', 0)}")
    lines.append(f"- 组合净值: {drawdown.get('nav', 1.0):.4f}")
    if drawdown.get("breached"):
        lines.append(f"- **警告: 回撤超过阈值!**")
    lines.append("")

    # 相关性
    lines.append("### 策略相关性")
    lines.append(f"- 分散度评分: {correlation.get('diversification_score', 0):.1f}/100")
    matrix = correlation.get("matrix", {})
    for pair, corr in matrix.items():
        tag = " (高!)" if corr > 0.7 else ""
        lines.append(f"- {pair[0]} vs {pair[1]}: {corr:.4f}{tag}")
    lines.append("")

    # 分配
    lines.append("### 资金分配建议")
    lines.append(f"- {alloc.get('reason', '无')}")
    allocation = alloc.get("allocation", {})
    for name, pct in allocation.items():
        lines.append(f"- {name}: {pct:.1%}")
    lines.append("")

    # findings
    if findings:
        lines.append("### 风控发现")
        for f in findings:
            lines.append(f"- [{f.get('severity')}] {f.get('message', '')}")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "check":
        result = check_portfolio_risk()
        findings = result["findings"]
        print(f"\n=== 组合风控检查 ({len(findings)} 个发现) ===")
        for f in findings:
            print(f"  [{f['severity']}] {f['message']}")
        if not findings:
            print("  一切正常")
    elif cmd == "report":
        print(generate_portfolio_report())
    else:
        print("用法:")
        print("  python3 portfolio_risk.py check    # 组合风控检查")
        print("  python3 portfolio_risk.py report   # 生成报告")
