"""
开盘前数据准备 + 作战计划
========================
夜班最后一步: 汇总跨市场信号/期货夜盘/学习引擎建议, 生成开盘作战计划推送微信

流程:
  1. 收集跨市场信号推演结果
  2. 收集期货夜盘持仓状态
  3. 收集 Agent Brain 早报摘要
  4. 收集学习引擎最新发现
  5. 汇总生成作战计划
  6. 推送微信

调度:
  07:30 开盘前 (夜班尾声)
"""

import os
import traceback
from datetime import datetime

try:
    from config import MORNING_PREP_PARAMS
except ImportError:
    MORNING_PREP_PARAMS = {"enabled": True}


# ================================================================
#  数据收集
# ================================================================

def _collect_cross_market():
    """收集跨市场信号"""
    try:
        from cross_market_strategy import analyze_cross_market
        return analyze_cross_market()
    except Exception:
        return None


def _collect_futures_positions():
    """收集期货持仓状态"""
    try:
        from trade_executor import get_portfolio_status
        return get_portfolio_status()
    except Exception:
        return None


def _collect_agent_insights():
    """收集 Agent Brain 最新洞察"""
    try:
        from agent_brain import AgentBrain
        brain = AgentBrain()
        brain.load()
        findings = brain.state.get("findings", [])
        recent = findings[-5:] if findings else []
        return recent
    except Exception:
        return []


def _collect_learning_summary():
    """收集学习引擎最新发现"""
    try:
        from learning_engine import get_learning_summary
        return get_learning_summary()
    except Exception:
        return None


def _collect_strategy_health():
    """收集各策略健康度"""
    try:
        from watchdog import get_all_strategy_status
        return get_all_strategy_status()
    except Exception:
        return {}


def _collect_news_digest():
    """收集最新新闻摘要"""
    try:
        from global_news_monitor import get_latest_digest
        return get_latest_digest()
    except Exception:
        return None


# ================================================================
#  作战计划生成
# ================================================================

def generate_morning_plan():
    """
    生成开盘作战计划

    Returns:
        dict: {
            "cross_market": dict,      # 跨市场信号
            "futures": dict,           # 期货持仓
            "insights": list,          # Agent洞察
            "learning": dict,          # 学习摘要
            "health": dict,            # 策略健康度
            "plan_text": str,          # 作战计划文本
            "risk_level": str,         # 风险等级 (low/medium/high)
            "timestamp": str,
        }
    """
    print("=" * 65)
    print(f"  开盘前作战计划")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 收集数据
    print("\n[1/7] 收集跨市场信号...")
    cross_market = _collect_cross_market()

    print("[2/7] 收集期货持仓...")
    futures = _collect_futures_positions()

    print("[3/7] 收集Agent洞察...")
    insights = _collect_agent_insights()

    print("[4/7] 收集学习引擎摘要...")
    learning = _collect_learning_summary()

    print("[5/7] 收集策略健康度...")
    health = _collect_strategy_health()

    print("[6/7] 收集全球新闻...")
    news_digest = _collect_news_digest()

    # 生成计划
    print("[7/7] 生成作战计划...")
    plan_lines = []
    risk_factors = 0  # 风险因子计数

    # --- 跨市场研判 ---
    plan_lines.append("【跨市场研判】")
    if cross_market:
        impact_map = {"bullish": "利多▲", "bearish": "利空▼", "neutral": "中性─"}
        impact = cross_market.get("a_stock_impact", "neutral")
        plan_lines.append(f"  综合信号: {cross_market.get('composite_signal', 0):+.3f} → {impact_map.get(impact, '?')}")
        plan_lines.append(f"  美股{cross_market.get('us_signal', 0):+.3f} | "
                         f"A50{cross_market.get('a50_signal', 0):+.3f} | "
                         f"币圈{cross_market.get('crypto_signal', 0):+.3f}")
        if cross_market.get("suggestion"):
            plan_lines.append(f"  建议: {cross_market['suggestion']}")
        if impact == "bearish":
            risk_factors += 2
        elif impact == "neutral":
            risk_factors += 1
        # 背离提示
        for d in cross_market.get("divergences", []):
            plan_lines.append(f"  ⚠ {d}")
    else:
        plan_lines.append("  数据不可用")
        risk_factors += 1

    # --- 全球新闻 ---
    plan_lines.append("\n【全球新闻】")
    if news_digest and news_digest.get("events"):
        sentiment = news_digest.get("sentiment", 0)
        mood = "偏多" if sentiment > 0.3 else "偏空" if sentiment < -0.3 else "均衡"
        plan_lines.append(f"  情绪: {mood} ({sentiment:+.2f})")

        for ev in news_digest["events"][:3]:
            a = ev.get("analysis", {})
            tag = {"bullish": "利好", "bearish": "利空"}.get(
                a.get("impact_direction", ""), "中性")
            plan_lines.append(f"  · [{tag}] {ev.get('title', '')[:60]}")

        heatmap = news_digest.get("heatmap", {})
        if heatmap:
            hm_parts = []
            for sector, val in list(heatmap.items())[:5]:
                arrow = "↑" * min(int(abs(val)), 3) if val > 0 else "↓" * min(int(abs(val)), 3)
                hm_parts.append(f"{sector}{arrow}")
            plan_lines.append(f"  热力图: {' | '.join(hm_parts)}")

        if sentiment < -0.3:
            risk_factors += 1
    else:
        plan_lines.append("  暂无数据")

    # --- 期货持仓 ---
    plan_lines.append("\n【期货持仓】")
    if futures and futures.get("count", 0) > 0:
        plan_lines.append(f"  持仓{futures['count']}个  保证金¥{futures.get('total_margin', 0):.0f}  "
                         f"浮动盈亏¥{futures.get('total_pnl', 0):.2f}")
        for p in futures.get("positions", []):
            plan_lines.append(f"  {p.get('code', '?')} {p.get('name', '?')} "
                             f"{p.get('direction', '?')} {p.get('pnl_pct', 0):+.2f}%")
        if futures.get("total_pnl", 0) < -1000:
            risk_factors += 1
    else:
        plan_lines.append("  无持仓")

    # --- Agent洞察 ---
    plan_lines.append("\n【最近洞察】")
    if insights:
        for ins in insights[-3:]:
            if isinstance(ins, dict):
                plan_lines.append(f"  · {ins.get('text', ins.get('message', str(ins)[:80]))}")
            else:
                plan_lines.append(f"  · {str(ins)[:80]}")
    else:
        plan_lines.append("  暂无")

    # --- 策略健康度 ---
    plan_lines.append("\n【策略健康度】")
    if health:
        unhealthy = []
        for name, status in health.items():
            if isinstance(status, dict):
                s = status.get("status", "unknown")
                if s == "failed":
                    unhealthy.append(name)
        if unhealthy:
            plan_lines.append(f"  ⚠ 异常策略: {', '.join(unhealthy)}")
            risk_factors += len(unhealthy)
        else:
            plan_lines.append("  全部正常")
    else:
        plan_lines.append("  状态不可用")

    # --- 风险等级 ---
    if risk_factors >= 3:
        risk_level = "high"
    elif risk_factors >= 1:
        risk_level = "medium"
    else:
        risk_level = "low"

    risk_label = {"low": "低风险 ✓", "medium": "中等风险 ⚡", "high": "高风险 ⚠"}

    # --- 入场时机建议 ---
    plan_lines.append("\n【入场时机建议】")
    try:
        from json_store import safe_load as _sl_timing
        timing_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timing_analysis.json")
        timing_data = _sl_timing(timing_path, default={})
        advice = timing_data.get("timing_advice", {})
        if advice:
            for strategy, adv in advice.items():
                if adv["action"] == "wait_pullback":
                    plan_lines.append(f"  {strategy}: 等回踩 {adv['pullback_target_pct']:.1f}% "
                                     f"(命中{adv['hit_rate']:.0f}%)")
                else:
                    plan_lines.append(f"  {strategy}: 立即买入")
        else:
            plan_lines.append("  数据不足")
    except Exception:
        plan_lines.append("  不可用")

    # --- 今日操作要点 ---
    plan_lines.append(f"\n【今日风险等级】 {risk_label.get(risk_level, '?')}")
    plan_lines.append("\n【操作要点】")
    if risk_level == "high":
        plan_lines.append("  1. 控制仓位, 减少新开仓")
        plan_lines.append("  2. 收紧止损, 保护利润")
        plan_lines.append("  3. 重点关注防守型策略 (低吸回调/缩量整理)")
    elif risk_level == "medium":
        plan_lines.append("  1. 维持现有仓位, 谨慎加仓")
        plan_lines.append("  2. 均衡配置, 进攻防守兼顾")
        plan_lines.append("  3. 关注跨市场信号变化")
    else:
        plan_lines.append("  1. 可适度积极, 关注趋势策略信号")
        plan_lines.append("  2. 重点关注放量突破/趋势跟踪")
        plan_lines.append("  3. 板块轮动关注强势板块龙头")

    if cross_market and cross_market.get("suggestion"):
        plan_lines.append(f"  4. 外围: {cross_market['suggestion']}")

    plan_text = "\n".join(plan_lines)

    # 打印
    print(f"\n{plan_text}")

    return {
        "cross_market": cross_market,
        "futures": futures,
        "insights": insights,
        "learning": learning,
        "health": health,
        "news_digest": news_digest,
        "plan_text": plan_text,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ================================================================
#  标准化接口
# ================================================================

def run_morning_prep():
    """标准化接口 (供 scheduler 调用)

    Returns:
        dict: 作战计划结果
    """
    if not MORNING_PREP_PARAMS.get("enabled", True):
        print("[开盘准备] 已禁用")
        return {}

    try:
        return generate_morning_plan()
    except Exception as e:
        print(f"[开盘准备异常] {e}")
        traceback.print_exc()
        return {}


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    result = run_morning_prep()
    if result and result.get("plan_text"):
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw("开盘作战计划", result["plan_text"])
            print("\n[微信推送完成]")
        except Exception as e:
            print(f"\n[微信推送失败] {e}")
