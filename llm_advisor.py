"""
LLM 顾问 — 接入 Claude API 深度推理/分析/辅助决策
===================================================
核心能力:
  L1 润色: 增强早报/晚报 (市场预判+操作建议+风险提示)
  L1 建议: 对 medium-confidence findings 提供 LLM 建议
  L2 深度推理: OODA 各阶段 LLM 深度介入 (orient/decide/learn)
  L2 夜班分析: 22:30+ 深度复盘/因子体检/明日预判/认知沉淀
  对话: CLI 问答系统状态

安全机制:
  - API key 不存在 → 所有函数降级为原始输出
  - 调用异常 → 捕获返回空字符串
  - 每日调用上限 max_daily_calls (持久化计数)

CLI:
  python3 llm_advisor.py chat "最近表现如何"
  python3 llm_advisor.py usage                 # 查看今日 API 使用量
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from config import LLM_ADVISOR_PARAMS
from log_config import get_logger

logger = get_logger("llm_advisor")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_USAGE_PATH = os.path.join(_BASE_DIR, "llm_usage.json")

# 延迟初始化的 client
_client = None
_client_init_attempted = False


# ================================================================
#  Client 初始化
# ================================================================

def _get_client():
    """延迟初始化 Anthropic client (异常安全)

    Returns:
        Anthropic client 或 None
    """
    global _client, _client_init_attempted

    if _client_init_attempted:
        return _client

    _client_init_attempted = True

    if not LLM_ADVISOR_PARAMS.get("enabled", True):
        logger.info("[LLM] 已禁用")
        return None

    api_key_env = LLM_ADVISOR_PARAMS.get("api_key_env", "ANTHROPIC_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        logger.info("[LLM] 环境变量 %s 未设置, LLM 功能降级", api_key_env)
        logger.info("[LLM] 启用方法: export %s=sk-ant-xxx (添加到 ~/.zshrc 可持久化)", api_key_env)
        return None

    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        logger.info("[LLM] Client 初始化成功")
        return _client
    except ImportError:
        logger.info("[LLM] anthropic 包未安装, LLM 功能降级")
        return None
    except Exception as e:
        logger.warning("[LLM] Client 初始化失败: %s", e)
        return None


def reset_client():
    """重置 client 状态 (供测试使用)"""
    global _client, _client_init_attempted
    _client = None
    _client_init_attempted = False


# ================================================================
#  调用限额
# ================================================================

def _check_daily_limit() -> bool:
    """检查今日 API 调用是否超限

    Returns:
        True if under limit, False if exceeded
    """
    usage = safe_load(_USAGE_PATH, default={})
    today = date.today().isoformat()
    if usage.get("date") != today:
        return True
    count = usage.get("count", 0)
    max_calls = LLM_ADVISOR_PARAMS.get("max_daily_calls", 20)
    return count < max_calls


def _increment_usage():
    """递增今日调用计数"""
    usage = safe_load(_USAGE_PATH, default={})
    today = date.today().isoformat()
    if usage.get("date") != today:
        usage = {"date": today, "count": 0}
    usage["count"] = usage.get("count", 0) + 1
    safe_save(_USAGE_PATH, usage)


def get_usage_today() -> dict:
    """获取今日 API 使用量"""
    usage = safe_load(_USAGE_PATH, default={})
    today = date.today().isoformat()
    if usage.get("date") != today:
        return {"date": today, "count": 0,
                "max": LLM_ADVISOR_PARAMS.get("max_daily_calls", 20)}
    return {"date": today, "count": usage.get("count", 0),
            "max": LLM_ADVISOR_PARAMS.get("max_daily_calls", 20)}


# ================================================================
#  统一 LLM 调用
# ================================================================

def _call_llm(prompt: str, system: str = "", max_tokens: int = None) -> str:
    """统一 LLM 调用 (限流+异常安全+计数)

    Returns:
        LLM 回复文本, 或空字符串 (失败时)
    """
    client = _get_client()
    if client is None:
        return ""

    if not _check_daily_limit():
        logger.info("[LLM] 今日调用已达上限")
        return ""

    if max_tokens is None:
        max_tokens = LLM_ADVISOR_PARAMS.get("max_tokens", 1024)
    model = LLM_ADVISOR_PARAMS.get("model", "claude-sonnet-4-20250514")
    temperature = LLM_ADVISOR_PARAMS.get("temperature", 0.3)
    timeout = LLM_ADVISOR_PARAMS.get("timeout_sec", 30)

    try:
        messages = [{"role": "user", "content": prompt}]
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs, timeout=timeout)
        _increment_usage()

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        return text
    except Exception as e:
        logger.warning("[LLM] 调用失败: %s", e)
        return ""


# ================================================================
#  系统上下文构建
# ================================================================

def _build_system_context() -> str:
    """构建系统上下文 (策略状态+统计+持仓+regime)"""
    parts = [
        "你是一个量化交易系统的总经理(AI大脑)。"
        "系统运行9个策略: 集合竞价、放量突破、尾盘短线、低吸回调、缩量整理、趋势跟踪、板块轮动、事件驱动(以上A股) + 期货趋势。"
        "你的职责是分析数据、发现问题、做出判断、给出可执行的建议。不要说空话, 要有具体的数据依据。"
    ]

    # 近30天统计
    try:
        from scorecard import calc_cumulative_stats
        stats = calc_cumulative_stats(30)
        parts.append(f"\n近30天统计: 总记录{stats.get('total_records', 0)}, "
                     f"胜率{stats.get('win_rate', 0):.1f}%, "
                     f"平均收益{stats.get('avg_net_return', 0):.2f}%")
    except Exception:
        pass

    # 资金曲线
    try:
        from scorecard import calc_equity_curve
        eq = calc_equity_curve(30)
        parts.append(f"净值{eq.get('nav_final', 1.0):.4f}, "
                     f"夏普{eq.get('sharpe', 0):.2f}, "
                     f"最大回撤{eq.get('max_drawdown', 0):.2f}%")
    except Exception:
        pass

    # 当前持仓
    try:
        from position_manager import get_portfolio_summary
        summary = get_portfolio_summary()
        parts.append(f"当前持仓{summary.get('count', 0)}只, "
                     f"组合盈亏{summary.get('total_pnl_pct', 0):.2f}%")
    except Exception:
        pass

    # Agent 状态
    try:
        from agent_brain import _load_memory
        memory = _load_memory()
        states = memory.get("strategy_states", {})
        for name, state in states.items():
            status = state.get("status", "active")
            if status == "paused":
                parts.append(f"{name}: 暂停 (原因: {state.get('pause_reason', '?')})")
            else:
                parts.append(f"{name}: 运行中")
    except Exception:
        pass

    # 组合风控
    try:
        from portfolio_risk import check_portfolio_risk
        pr = check_portfolio_risk()
        dd = pr.get("drawdown", {})
        parts.append(f"组合回撤{dd.get('current_drawdown_pct', 0):.2f}%, "
                     f"净值{dd.get('nav', 1.0):.4f}")
    except Exception:
        pass

    parts.append("\n请用简洁中文回答。关注风险, 给出可操作的建议。")
    return "\n".join(parts)


# ================================================================
#  增强早报
# ================================================================

def enhance_morning_briefing(raw: str, snapshot: dict = None,
                              memory: dict = None) -> str:
    """LLM 增强早报 (市场预判+操作建议+风险提示)

    Args:
        raw: 原始早报文本
        snapshot: observe() 的快照
        memory: agent_memory

    Returns:
        增强后的文本, 或原始文本 (LLM 不可用时)
    """
    system = _build_system_context()
    prompt = (
        f"以下是今日交易系统自动生成的早报:\n\n{raw}\n\n"
        "请在此基础上增强, 添加:\n"
        "1. 市场预判 (基于当前策略状态和近期表现)\n"
        "2. 今日操作建议 (重点关注哪些策略, 注意什么)\n"
        "3. 风险提示\n\n"
        "保持 Markdown 格式, 简洁专业。"
    )

    enhanced = _call_llm(prompt, system=system)
    if enhanced:
        return enhanced
    return raw


# ================================================================
#  增强晚报
# ================================================================

def enhance_evening_summary(raw: str, snapshot: dict = None,
                             decisions: list = None,
                             memory: dict = None) -> str:
    """LLM 增强晚报 (复盘+展望+调优建议)

    Args:
        raw: 原始晚报文本
        snapshot: observe() 的快照
        decisions: decide() 的决策列表
        memory: agent_memory

    Returns:
        增强后的文本, 或原始文本 (LLM 不可用时)
    """
    system = _build_system_context()

    decisions_text = ""
    if decisions:
        decisions_text = "\n今日决策:\n"
        for d in decisions[:5]:
            f = d.get("finding", {})
            decisions_text += (f"- [{f.get('severity')}] {f.get('message', '')} "
                               f"→ {d.get('action')} "
                               f"(executed={d.get('execute')})\n")

    prompt = (
        f"以下是今日交易系统自动生成的晚报:\n\n{raw}\n{decisions_text}\n"
        "请在此基础上增强, 添加:\n"
        "1. 今日复盘要点\n"
        "2. 明日展望\n"
        "3. 参数调优建议 (如果发现问题)\n\n"
        "保持 Markdown 格式, 简洁专业。"
    )

    enhanced = _call_llm(prompt, system=system)
    if enhanced:
        return enhanced
    return raw


# ================================================================
#  Findings 建议
# ================================================================

def advise_on_findings(findings: list) -> list:
    """对 medium-confidence findings 添加 LLM 建议

    Args:
        findings: orient() 产出的 findings 列表

    Returns:
        原始 findings 列表 (可能附加了 llm_advice 字段)
    """
    client = _get_client()
    if client is None:
        return findings

    # 只对 0.4-0.7 置信度的 findings 提供建议
    medium = [f for f in findings
              if 0.4 <= f.get("confidence", 0) <= 0.7
              and f.get("severity") in ("warning", "info")]

    if not medium:
        return findings

    # 批量构建 prompt
    system = _build_system_context()
    descriptions = []
    for i, f in enumerate(medium[:3]):  # 最多3个
        descriptions.append(
            f"{i+1}. [{f.get('severity')}] {f.get('message', '')} "
            f"(置信度={f.get('confidence', 0):.2f}, "
            f"建议动作={f.get('suggested_action', '')})"
        )

    prompt = (
        "系统发现以下中等置信度的异常:\n\n"
        + "\n".join(descriptions)
        + "\n\n对每个异常, 请给出:\n"
        "1. 你的判断 (是否需要行动)\n"
        "2. 具体建议\n"
        "每条控制在50字以内。"
    )

    advice = _call_llm(prompt, system=system, max_tokens=512)
    if advice:
        for f in medium[:3]:
            f["llm_advice"] = advice

    return findings


# ================================================================
#  L2 深度推理 — OODA 各阶段 LLM 深度介入
# ================================================================

def llm_deep_orient(findings: list, snapshot: dict, memory: dict) -> list:
    """LLM 深度分析 findings: 找根因、发现关联、补充检测器遗漏

    不只是"连亏4次→暂停", 而是分析"为什么连亏、是策略问题还是行情问题"

    Returns:
        可能追加的新 findings 列表 (LLM 发现的检测器遗漏)
    """
    client = _get_client()
    if client is None or not findings:
        return []

    system = _build_system_context()

    # 构建 findings 描述
    findings_text = []
    for i, f in enumerate(findings[:8]):  # 最多分析8个
        findings_text.append(
            f"{i+1}. [{f.get('severity')}] {f.get('message', '')} "
            f"(策略={f.get('strategy', '全局')}, "
            f"置信度={f.get('confidence', 0):.2f}, "
            f"建议={f.get('suggested_action', '')})"
        )

    # 构建快照摘要
    metrics_text = []
    for name, m in snapshot.get("strategy_metrics", {}).items():
        wr = m.get("rolling_5d_win_rate")
        wr_str = f"{wr:.0%}" if wr is not None else "无数据"
        metrics_text.append(
            f"  {name}: 连亏{m.get('consecutive_losses', 0)} "
            f"连赢{m.get('consecutive_wins', 0)} "
            f"5日胜率{wr_str}"
        )

    regime = snapshot.get("current_regime", "unknown")

    prompt = (
        f"当前大盘环境: {regime}\n\n"
        f"各策略近期表现:\n" + "\n".join(metrics_text) + "\n\n"
        f"系统检测器发现 {len(findings)} 个信号:\n" + "\n".join(findings_text) + "\n\n"
        "请你作为总经理进行深度分析:\n"
        "1. 根因分析: 这些信号背后的真正原因是什么? (不要重复信号本身, 要挖深一层)\n"
        "2. 关联发现: 多个信号之间有没有关联? (例如: 行情转弱导致多个策略同时下滑)\n"
        "3. 遗漏检测: 基于你的分析, 有没有检测器没发现但值得关注的问题?\n\n"
        "对于第3点的遗漏, 请用以下JSON格式输出 (如果没有遗漏, 输出空数组[]):\n"
        '```json\n[{"severity": "warning/info", "strategy": "策略名或null", '
        '"message": "具体发现", "suggested_action": "log_insight/escalate_human/pause_strategy"}]\n```\n\n'
        "分析控制在200字以内, 然后输出JSON。"
    )

    response = _call_llm(prompt, system=system, max_tokens=800)
    if not response:
        return []

    # 解析 LLM 发现的新 findings
    new_findings = []
    try:
        import json
        import re
        # 提取 JSON 块
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            items = json.loads(json_match.group(1))
            for item in items:
                if not isinstance(item, dict) or not item.get("message"):
                    continue
                new_findings.append({
                    "type": "llm_insight",
                    "severity": item.get("severity", "info"),
                    "strategy": item.get("strategy"),
                    "message": f"[LLM洞察] {item['message']}",
                    "suggested_action": item.get("suggested_action", "log_insight"),
                    "confidence": 0.55,  # LLM 发现的初始置信度
                    "source": "llm_deep_orient",
                    "category": "strategy",
                })
    except Exception as e:
        logger.debug("[LLM] 解析深度分析结果异常: %s", e)

    # 把 LLM 的文字分析存为 context (供后续 decide 使用)
    if response:
        # 去掉 JSON 部分, 保留分析文字
        analysis_text = response.split("```json")[0].strip() if "```json" in response else response
        for f in findings:
            f["_llm_analysis"] = analysis_text

    if new_findings:
        logger.info("[LLM] 深度分析发现 %d 个新信号", len(new_findings))

    return new_findings


def llm_smart_decide(findings: list, memory: dict) -> list:
    """LLM 辅助决策: 对关键 findings 给出行动建议

    不再是机械地 confidence >= 0.6 就执行, 而是让 LLM 综合判断

    Returns:
        findings 列表 (可能修改了 suggested_action 和 confidence)
    """
    client = _get_client()
    if client is None:
        return findings

    # 筛选需要 LLM 决策的 findings (非 log_insight, 且 confidence 在 0.4-0.85)
    candidates = [
        f for f in findings
        if f.get("suggested_action") != "log_insight"
        and 0.4 <= f.get("confidence", 0) <= 0.85
        and f.get("severity") in ("warning", "critical")
    ]

    if not candidates:
        return findings

    system = _build_system_context()

    # 加入 LLM 分析上下文 (如果有)
    analysis = ""
    for f in candidates:
        if f.get("_llm_analysis"):
            analysis = f"\n前序分析:\n{f['_llm_analysis']}\n"
            break

    descs = []
    for i, f in enumerate(candidates[:5]):
        descs.append(
            f"{i+1}. [{f.get('severity')}] {f.get('message', '')} "
            f"(策略={f.get('strategy', '全局')}, "
            f"当前建议={f.get('suggested_action', '')}, "
            f"置信度={f.get('confidence', 0):.2f})"
        )

    # 获取暂停策略列表
    paused = [name for name, s in memory.get("strategy_states", {}).items()
              if s.get("status") == "paused"]
    paused_text = f"当前已暂停策略: {', '.join(paused)}" if paused else "当前无暂停策略"

    prompt = (
        f"{paused_text}\n{analysis}"
        f"以下信号需要你做决策:\n" + "\n".join(descs) + "\n\n"
        "对每个信号, 请判断:\n"
        "1. 是否应该执行建议的动作? (是/否)\n"
        "2. 如果不应该, 更好的动作是什么?\n"
        "3. 你的置信度 (0.0-1.0)\n\n"
        "用以下JSON格式输出:\n"
        '```json\n[{"index": 1, "execute": true/false, "action": "动作", '
        '"confidence": 0.8, "reason": "简要原因"}]\n```'
    )

    response = _call_llm(prompt, system=system, max_tokens=600)
    if not response:
        return findings

    try:
        import json
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            decisions = json.loads(json_match.group(1))
            for d in decisions:
                idx = d.get("index", 0) - 1
                if 0 <= idx < len(candidates):
                    f = candidates[idx]
                    if d.get("action"):
                        f["suggested_action"] = d["action"]
                    if d.get("confidence"):
                        # 混合: 70% LLM判断 + 30% 原始置信度
                        original_conf = f.get("confidence", 0.5)
                        llm_conf = float(d["confidence"])
                        f["confidence"] = 0.7 * llm_conf + 0.3 * original_conf
                    if d.get("reason"):
                        f["_llm_decision_reason"] = d["reason"]
                    f["_llm_decided"] = True
                    logger.info("[LLM决策] %s → %s (置信度%.2f, 原因: %s)",
                                f.get("message", "")[:40],
                                f.get("suggested_action"),
                                f.get("confidence", 0),
                                d.get("reason", ""))
    except Exception as e:
        logger.debug("[LLM] 解析决策结果异常: %s", e)

    return findings


def llm_extract_insights(findings: list, decisions: list,
                          snapshot: dict, memory: dict) -> list:
    """LLM 提取认知洞察: OODA 循环后沉淀经验

    不是记流水账, 而是提炼"下次遇到类似情况该怎么办"的认知

    Returns:
        认知洞察列表 [{pattern, lesson, applicable_when}]
    """
    client = _get_client()
    if client is None:
        return []

    # 没有有意义的 findings 就不分析
    meaningful = [f for f in findings if f.get("severity") in ("warning", "critical")]
    if not meaningful and not decisions:
        return []

    system = _build_system_context()

    # 构建本次循环摘要
    cycle_text = []
    regime = snapshot.get("current_regime", "unknown")
    cycle_text.append(f"大盘环境: {regime}")
    cycle_text.append(f"发现 {len(findings)} 个信号, 其中 {len(meaningful)} 个需关注")

    executed = [d for d in decisions if d.get("execute")]
    cycle_text.append(f"执行了 {len(executed)} 个动作")
    for d in executed:
        f = d.get("finding", {})
        cycle_text.append(f"  - {f.get('message', '')} → {d.get('action')}")

    # 近期洞察 (避免重复)
    recent_insights = memory.get("insights", [])[-10:]
    recent_text = ""
    if recent_insights:
        recent_msgs = [i.get("message", "") for i in recent_insights]
        recent_text = f"\n近期已有洞察 (避免重复):\n" + "\n".join(f"- {m}" for m in recent_msgs[-5:])

    prompt = (
        f"本次 OODA 循环结果:\n" + "\n".join(cycle_text)
        + f"\n{recent_text}\n\n"
        "请提炼认知洞察 (不是重复上面的信号, 而是更高层次的经验总结):\n"
        "1. 有什么规律/模式值得记住?\n"
        "2. 下次遇到类似情况该怎么办?\n"
        "3. 有什么应该改进的判断逻辑?\n\n"
        "用JSON输出 (没有洞察则输出[]):\n"
        '```json\n[{"pattern": "识别到的模式", "lesson": "经验教训", '
        '"applicable_when": "什么时候适用"}]\n```\n'
        "最多3条, 每条控制在30字以内。"
    )

    response = _call_llm(prompt, system=system, max_tokens=500)
    if not response:
        return []

    insights = []
    try:
        import json
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            items = json.loads(json_match.group(1))
            for item in items:
                if isinstance(item, dict) and item.get("lesson"):
                    insights.append(item)
    except Exception as e:
        logger.debug("[LLM] 解析认知洞察异常: %s", e)

    if insights:
        logger.info("[LLM] 提炼 %d 条认知洞察", len(insights))

    return insights


# ================================================================
#  L2 夜班分析 — 22:30+ 深度复盘
# ================================================================

def llm_night_analysis(memory: dict, performance_review: dict = None) -> str:
    """夜班深度分析: 全面复盘 + 因子体检 + 明日预判 + 认知沉淀 + 绩效考核

    在 22:30 运行, 不受白天节奏影响, 可以深入思考

    Args:
        memory: agent_memory 数据
        performance_review: 绩效考核结果 (来自 run_performance_review)

    Returns:
        夜班分析报告 (Markdown), 空字符串表示 LLM 不可用
    """
    client = _get_client()
    if client is None:
        return ""

    system = _build_system_context()

    # 收集今日所有洞察
    today_str = date.today().isoformat()
    today_insights = [i for i in memory.get("insights", [])
                      if i.get("time", "").startswith(today_str)]

    insights_text = ""
    if today_insights:
        insights_text = "今日系统洞察:\n"
        for i in today_insights:
            insights_text += f"- [{i.get('severity')}] {i.get('message', '')} (动作: {i.get('action_taken', '')})\n"

    # 策略状态
    states_text = "策略状态:\n"
    for name, s in memory.get("strategy_states", {}).items():
        status = s.get("status", "active")
        cl = s.get("consecutive_losses", 0)
        cw = s.get("consecutive_wins", 0)
        last5 = s.get("last_5_results", [])
        states_text += f"- {name}: {status} 连亏{cl} 连赢{cw} 近5次{last5}\n"

    # 事件总线摘要
    bus_text = ""
    try:
        from event_bus import get_event_bus
        bus = get_event_bus()
        stats = bus.stats()
        bus_text = (f"\n事件总线: 今日{stats.get('total_emitted', 0)}个事件, "
                    f"已消费{stats.get('total_consumed', 0)}个, "
                    f"去重{stats.get('total_deduped', 0)}个\n")
    except Exception:
        pass

    # 智能体健康
    agents_text = ""
    try:
        from agent_registry import get_registry
        registry = get_registry()
        agents = registry.list_agents()
        if agents:
            agents_text = "\n子智能体健康:\n"
            for a in agents:
                agents_text += f"- {a.display_name}: {a.status} 健康{a.health:.0%}\n"
    except Exception:
        pass

    # 记分卡统计
    scorecard_text = ""
    try:
        from scorecard import calc_cumulative_stats
        stats_7d = calc_cumulative_stats(7)
        stats_30d = calc_cumulative_stats(30)
        scorecard_text = (
            f"\n业绩统计:\n"
            f"- 近7天: {stats_7d.get('total_records', 0)}笔 胜率{stats_7d.get('win_rate', 0):.1f}% "
            f"均收益{stats_7d.get('avg_net_return', 0):.2f}%\n"
            f"- 近30天: {stats_30d.get('total_records', 0)}笔 胜率{stats_30d.get('win_rate', 0):.1f}% "
            f"均收益{stats_30d.get('avg_net_return', 0):.2f}%\n"
        )
    except Exception:
        pass

    # 绩效考核数据
    review_text = ""
    if performance_review and performance_review.get("agents"):
        review_text = f"\n绩效考核 (团队均分{performance_review.get('avg_score', 0):.0f}):\n"
        for name, r in performance_review["agents"].items():
            details = ", ".join(r.get("details", []))
            review_text += (f"- {r.get('display_name', name)}: "
                            f"{r.get('grade', '?')}级 {r.get('score', 0):.0f}分 "
                            f"({details})\n")

    prompt = (
        f"现在是 {datetime.now().strftime('%H:%M')}, 你正在进行每日深度复盘。\n\n"
        f"{states_text}\n{insights_text}\n{scorecard_text}{bus_text}{agents_text}{review_text}\n"
        "请作为总经理完成以下工作:\n\n"
        "## 一、今日复盘\n"
        "- 今天整体表现如何? 哪些策略表现好/差? 为什么?\n"
        "- 系统做出了哪些决策? 是否正确?\n\n"
        "## 二、因子体检\n"
        "- 各策略的胜率趋势是否健康?\n"
        "- 有没有需要关注的因子衰减迹象?\n\n"
        "## 三、明日预判\n"
        "- 基于今日表现和大盘状态, 明天需要注意什么?\n"
        "- 哪些策略可能需要调整?\n\n"
        "## 四、认知沉淀\n"
        "- 今天学到了什么? 有什么经验值得记住?\n\n"
        "## 五、改进建议\n"
        "- 对系统参数或逻辑有什么具体改进建议? (要具体到参数名和数值)\n\n"
        "## 六、绩效考核点评\n"
        "- 对每个智能体的表现给出一句话点评\n"
        "- 谁表现最好? 谁需要改进? 具体改进方向是什么?\n"
        "- D级智能体是否需要降级或暂停?\n\n"
        "保持 Markdown 格式, 务实不空谈, 有数据支撑。"
    )

    report = _call_llm(prompt, system=system, max_tokens=2000)
    if report:
        logger.info("[LLM] 夜班深度分析完成 (%d字)", len(report))
    return report


# ================================================================
#  CLI 对话
# ================================================================

def chat(question: str) -> str:
    """CLI 对话 (问答系统状态)

    Args:
        question: 用户问题

    Returns:
        LLM 回答, 或降级提示
    """
    client = _get_client()
    if client is None:
        return "[LLM 不可用] 请设置环境变量 ANTHROPIC_API_KEY"

    system = _build_system_context()
    answer = _call_llm(question, system=system)
    if answer:
        return answer
    return "[LLM] 调用失败, 请稍后重试"


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "usage"
    arg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    if cmd == "chat" and arg:
        print(chat(arg))
    elif cmd == "usage":
        usage = get_usage_today()
        print(f"\n=== LLM 使用量 ===")
        print(f"  日期: {usage['date']}")
        print(f"  今日调用: {usage['count']} / {usage['max']}")
    else:
        print("用法:")
        print('  python3 llm_advisor.py chat "最近表现如何"  # 对话')
        print("  python3 llm_advisor.py usage               # 使用量")
