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
_SCORECARD_DEFAULT = _SCORECARD_PATH

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

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=days)
    except Exception:
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
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard()
    except Exception:
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
#  凯利准则 (OP-08)
# ================================================================

def calc_kelly_fractions(days: int = None) -> dict:
    """为每个策略计算 Half-Kelly 最优仓位比例

    Kelly 公式: f* = W - (1-W)/R
    W = 胜率, R = 平均盈利/平均亏损
    使用 Half-Kelly (f*/2) 降低波动风险

    Returns:
        {
            strategy_name: {
                "kelly_full": float,      # 完整 Kelly
                "kelly_half": float,      # Half-Kelly (实际使用)
                "win_rate": float,
                "avg_win": float,
                "avg_loss": float,
                "sample_count": int,
            }
        }
    """
    if days is None:
        days = PORTFOLIO_RISK_PARAMS.get("correlation_window_days", 30)

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=days)
    except Exception:
        scorecard = safe_load(_SCORECARD_PATH, default=[])

    cutoff = (date.today() - timedelta(days=days)).isoformat()

    # 按策略分组收益
    strategy_returns = {}
    for r in scorecard:
        if r.get("rec_date", "") < cutoff:
            continue
        strategy = r.get("strategy", "")
        ret = r.get("net_return_pct", 0)
        strategy_returns.setdefault(strategy, []).append(ret)

    result = {}
    for name in STRATEGY_NAMES:
        rets = strategy_returns.get(name, [])
        if len(rets) < 5:
            result[name] = {
                "kelly_full": 0.0, "kelly_half": 0.0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "sample_count": len(rets),
            }
            continue

        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]

        win_rate = len(wins) / len(rets) if rets else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.01

        # Kelly: f* = W - (1-W)/R
        R = avg_win / avg_loss if avg_loss > 0 else 1.0
        kelly_full = win_rate - (1 - win_rate) / R if R > 0 else 0
        kelly_full = max(0.0, kelly_full)  # 负值意味着不应下注
        kelly_half = kelly_full / 2

        result[name] = {
            "kelly_full": round(kelly_full, 4),
            "kelly_half": round(kelly_half, 4),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "sample_count": len(rets),
        }

    return result


# ================================================================
#  风险平价 (OP-08)
# ================================================================

def calc_risk_parity_allocation(days: int = None) -> dict:
    """风险平价: 按策略波动率的倒数分配权重, 使每个策略对组合风险贡献相等

    Returns:
        {
            "weights": {strategy: float},    # 归一化权重
            "volatilities": {strategy: float},
            "equal_risk_contribution": float, # 每个策略的目标风险贡献
        }
    """
    if days is None:
        days = PORTFOLIO_RISK_PARAMS.get("correlation_window_days", 30)

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=days)
    except Exception:
        scorecard = safe_load(_SCORECARD_PATH, default=[])

    cutoff = (date.today() - timedelta(days=days)).isoformat()

    # 按策略+日期聚合收益
    daily_returns = {}
    for r in scorecard:
        if r.get("rec_date", "") < cutoff:
            continue
        strategy = r.get("strategy", "")
        rec_date = r.get("rec_date", "")
        daily_returns.setdefault(strategy, {}).setdefault(rec_date, []).append(
            r.get("net_return_pct", 0))

    # 计算每个策略的波动率 (日收益标准差)
    volatilities = {}
    for name in STRATEGY_NAMES:
        raw = daily_returns.get(name, {})
        if len(raw) < 3:
            volatilities[name] = 999.0  # 数据不足, 给高波动率(低权重)
            continue
        daily_means = [sum(v) / len(v) for v in raw.values()]
        mean = sum(daily_means) / len(daily_means)
        var = sum((x - mean) ** 2 for x in daily_means) / len(daily_means)
        volatilities[name] = max(var ** 0.5, 0.01)

    # 反波动率加权
    inv_vols = {name: 1.0 / vol for name, vol in volatilities.items()}
    total_inv = sum(inv_vols.values())

    if total_inv <= 0:
        n = len(STRATEGY_NAMES)
        weights = {name: round(1.0 / n, 4) for name in STRATEGY_NAMES}
    else:
        weights = {name: round(iv / total_inv, 4) for name, iv in inv_vols.items()}

    active = sum(1 for v in volatilities.values() if v < 999)
    erc = round(1.0 / active, 4) if active > 0 else 0

    return {
        "weights": weights,
        "volatilities": {k: round(v, 4) for k, v in volatilities.items()},
        "equal_risk_contribution": erc,
    }


# ================================================================
#  动态资金分配建议 (增强: Kelly + Risk Parity)
# ================================================================

def suggest_allocation(strategy_health: dict = None) -> dict:
    """基于健康度+Kelly+Risk Parity 综合建议资金分配

    融合三个信号:
      - 健康度加权 (40%): auto_optimizer 的 score
      - Kelly 准则 (30%): 历史胜率+盈亏比 → 最优仓位
      - Risk Parity (30%): 波动率倒数 → 等风险贡献

    Args:
        strategy_health: {strategy_name: health_dict} from auto_optimizer

    Returns:
        {
            "allocation": {strategy: pct},
            "reason": str,
            "changes": [{strategy, old, new, reason}],
            "kelly": {strategy: kelly_dict},
            "risk_parity": {strategy: weight},
        }
    """
    default_alloc = PORTFOLIO_RISK_PARAMS.get("strategy_allocation", {})
    max_alloc = PORTFOLIO_RISK_PARAMS.get("max_strategy_allocation", 0.50)
    min_alloc = PORTFOLIO_RISK_PARAMS.get("min_strategy_allocation", 0.10)

    kelly_data = calc_kelly_fractions()
    rp_data = calc_risk_parity_allocation()
    rp_weights = rp_data.get("weights", {})

    if not strategy_health:
        # 无健康度数据时, 用 Kelly(50%) + RP(50%) 混合
        allocation = {}
        for name in STRATEGY_NAMES:
            kelly_w = kelly_data.get(name, {}).get("kelly_half", 0)
            rp_w = rp_weights.get(name, 1.0 / len(STRATEGY_NAMES))
            # Kelly可能为0(样本不足), 降级到 RP
            if kelly_w <= 0:
                allocation[name] = rp_w
            else:
                allocation[name] = kelly_w * 0.5 + rp_w * 0.5
        # 归一化 + 上下限
        allocation = _normalize_with_bounds(allocation, min_alloc, max_alloc)
        return {
            "allocation": allocation,
            "reason": "Kelly+RiskParity 混合 (无健康度数据)",
            "changes": _calc_changes(default_alloc, allocation, {}),
            "kelly": kelly_data,
            "risk_parity": rp_weights,
        }

    # 三信号融合
    health_scores = {}
    for name in STRATEGY_NAMES:
        health = strategy_health.get(name, {})
        health_scores[name] = health.get("score", 50)

    total_score = sum(health_scores.values())
    if total_score <= 0:
        total_score = 1

    allocation = {}
    w_health, w_kelly, w_rp = 0.4, 0.3, 0.3

    for name in STRATEGY_NAMES:
        # 健康度权重
        h_w = health_scores[name] / total_score
        # Kelly 权重
        k_w = kelly_data.get(name, {}).get("kelly_half", 0)
        # Risk Parity 权重
        rp_w = rp_weights.get(name, 1.0 / len(STRATEGY_NAMES))

        # Kelly 为 0 时, 将其份额分给 health 和 RP
        if k_w <= 0:
            allocation[name] = h_w * (w_health + w_kelly / 2) + rp_w * (w_rp + w_kelly / 2)
        else:
            allocation[name] = h_w * w_health + k_w * w_kelly + rp_w * w_rp

    allocation = _normalize_with_bounds(allocation, min_alloc, max_alloc)

    changes = _calc_changes(default_alloc, allocation, health_scores)
    reason = "Health(40%)+Kelly(30%)+RiskParity(30%) 综合分配" if changes else "各策略综合评分接近, 无需调整"

    return {
        "allocation": allocation,
        "reason": reason,
        "changes": changes,
        "kelly": kelly_data,
        "risk_parity": rp_weights,
    }


def _normalize_with_bounds(alloc: dict, min_w: float, max_w: float) -> dict:
    """归一化权重并应用上下限"""
    result = {}
    for name, w in alloc.items():
        result[name] = max(min_w, min(max_w, w))
    total = sum(result.values())
    if total > 0:
        result = {k: round(v / total, 4) for k, v in result.items()}
    return result


def _calc_changes(default_alloc: dict, new_alloc: dict, scores: dict) -> list:
    """计算分配变化"""
    changes = []
    threshold = PORTFOLIO_RISK_PARAMS.get("rebalance_threshold", 0.15)
    for name in STRATEGY_NAMES:
        old = default_alloc.get(name, 0.09)
        new = new_alloc.get(name, 0.09)
        if abs(new - old) >= threshold:
            direction = "增加" if new > old else "减少"
            score_str = f", 健康度={scores[name]:.0f}" if name in scores else ""
            changes.append({
                "strategy": name,
                "old": round(old, 4),
                "new": round(new, 4),
                "reason": f"{direction}配比 ({old:.0%}→{new:.0%}){score_str}",
            })
    return changes


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
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    # 更新注册表健康度
    try:
        from agent_registry import get_registry
        registry = get_registry()
        has_critical = any(f.get("severity") == "critical" for f in findings)
        registry.report_run("risk_inspector", success=not has_critical,
                            error_msg="组合回撤超限" if has_critical else None)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

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
