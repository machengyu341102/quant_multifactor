"""
Brain Orchestrator — LLM 增强的决策编排层
==========================================
在现有 agent_brain OODA 循环之上, 提供:
  1. 结构化请求/响应契约 (BrainRequest / BrainResponse)
  2. Prompt Builder — 根据场景自动组装 system + context + user prompt
  3. Context Assembler — 从各模块收集上下文数据
  4. Tool Hub 注册 — 可调用的工具 (暂为骨架, Phase 2 实现)

架构位置:
  regime_router → cascade_engine → [Brain Orchestrator] → strategy_ensemble → agent_brain
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from log_config import get_logger

logger = get_logger("brain_orchestrator")

_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("DATA_DIR", _DIR)


# ================================================================
#  契约定义: 请求 / 响应
# ================================================================

class BrainIntent(str, Enum):
    """Brain 请求意图类型"""
    MARKET_ASSESSMENT = "market_assessment"      # 盘前/盘中市场研判
    STRATEGY_REVIEW = "strategy_review"          # 策略表现复盘
    RISK_ALERT = "risk_alert"                    # 风险预警分析
    POSITION_ADVICE = "position_advice"          # 仓位建议
    SIGNAL_EVALUATION = "signal_evaluation"      # 信号质量评估
    NIGHT_ANALYSIS = "night_analysis"            # 夜间深度分析
    FREEFORM = "freeform"                        # 自由问答


class BrainRequest(BaseModel):
    """Brain 编排请求"""
    intent: BrainIntent
    user_query: str = ""
    context_scope: list[str] = Field(
        default_factory=lambda: ["regime", "positions", "signals"],
        description="需要注入的上下文模块: regime, positions, signals, scorecard, "
                    "policy, industry_capital, news, learning, memory",
    )
    max_tokens: int = 2000
    temperature: float = 0.3
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """LLM 请求的工具调用"""
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class BrainResponse(BaseModel):
    """Brain 编排响应"""
    intent: BrainIntent
    answer: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    context_used: list[str] = Field(default_factory=list)
    model_used: str = ""
    latency_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ================================================================
#  Context Assembler — 从各模块收集上下文
# ================================================================

class ContextAssembler:
    """按需收集系统上下文, 组装成结构化文本供 Prompt Builder 使用"""

    def __init__(self, data_dir: str = _DATA_DIR):
        self._data_dir = data_dir

    def assemble(self, scopes: list[str]) -> dict[str, str]:
        """返回 {scope_name: context_text} 字典"""
        result = {}
        for scope in scopes:
            collector = getattr(self, f"_collect_{scope}", None)
            if collector:
                try:
                    result[scope] = collector()
                except Exception as e:
                    logger.debug("上下文收集失败 [%s]: %s", scope, e)
                    result[scope] = f"[{scope}] 数据暂不可用"
            else:
                logger.debug("未知上下文模块: %s", scope)
        return result

    def _load_json(self, filename: str) -> Any:
        path = os.path.join(self._data_dir, filename)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _collect_regime(self) -> str:
        memory = self._load_json("agent_memory.json")
        meta = memory.get("meta", {})
        regime = meta.get("current_regime", "neutral")
        regime_score = meta.get("regime_score", "N/A")
        return f"当前市场环境: {regime} (评分: {regime_score})"

    def _collect_positions(self) -> str:
        positions = self._load_json("paper_positions.json")
        if not positions:
            return "当前无持仓"
        lines = [f"持仓 {len(positions)} 只:"]
        for p in positions[:10]:
            code = p.get("code", "?")
            name = p.get("name", "?")
            pnl = p.get("pnl_pct", 0)
            lines.append(f"  {code} {name} 盈亏{pnl:+.1f}%")
        return "\n".join(lines)

    def _collect_signals(self) -> str:
        from json_store import safe_load
        tracker = safe_load(
            os.path.join(self._data_dir, "signal_tracker.json"), default=[]
        )
        today = datetime.now().strftime("%Y-%m-%d")
        today_signals = [s for s in tracker if s.get("date", "").startswith(today)]
        if not today_signals:
            return "今日暂无信号"
        lines = [f"今日信号 {len(today_signals)} 条:"]
        for s in today_signals[:8]:
            lines.append(
                f"  [{s.get('strategy', '?')}] {s.get('code', '?')} "
                f"{s.get('direction', '?')} 置信{s.get('confidence', 0):.0%}"
            )
        return "\n".join(lines)

    def _collect_scorecard(self) -> str:
        try:
            from db_store import load_scorecard
            records = load_scorecard(days=7)
        except Exception:
            records = []
        if not records:
            return "近7日无打分记录"
        wins = sum(1 for r in records if r.get("result") == "win")
        total = len(records)
        return f"近7日打分: {total}条, 胜率{wins/total:.0%}" if total else "无数据"

    def _collect_policy(self) -> str:
        catalog = self._load_json("policy_direction_catalog.json")
        if not catalog:
            return "政策方向数据为空"
        items = catalog if isinstance(catalog, list) else catalog.get("directions", [])
        lines = [f"政策方向 {len(items)} 条:"]
        for item in items[:5]:
            lines.append(f"  {item.get('title', item.get('name', '?'))}")
        return "\n".join(lines)

    def _collect_industry_capital(self) -> str:
        data = self._load_json("industry_capital_research_log.json")
        if not data:
            return "产业资本数据为空"
        items = data if isinstance(data, list) else data.get("entries", [])
        return f"产业资本追踪 {len(items)} 条记录"

    def _collect_news(self) -> str:
        digest = self._load_json("news_digest.json")
        if not digest:
            return "新闻摘要为空"
        items = digest if isinstance(digest, list) else digest.get("items", [])
        lines = [f"新闻摘要 {len(items)} 条:"]
        for item in items[:3]:
            lines.append(f"  {item.get('title', item.get('headline', '?'))}")
        return "\n".join(lines)

    def _collect_learning(self) -> str:
        state = self._load_json("learning_state.json")
        if not state:
            return "学习状态为空"
        return (
            f"学习进度: 胜率{state.get('win_rate', 0):.0%}, "
            f"累计信号{state.get('total_signals', 0)}条"
        )

    def _collect_memory(self) -> str:
        memory = self._load_json("agent_memory.json")
        insights = memory.get("insights", [])
        if not insights:
            return "Agent 无历史洞察"
        recent = insights[-3:]
        lines = ["近期洞察:"]
        for ins in recent:
            lines.append(f"  - {ins}")
        return "\n".join(lines)


# ================================================================
#  Prompt Builder — 组装 LLM Prompt
# ================================================================

# 系统角色提示: 看大做小, 深度融合, 上帝视角
SYSTEM_PROMPT = """你是 Alpha AI 量化交易系统的核心决策大脑。

核心理念:
- 看大做小: 宏观研判定方向, 微观执行求精准
- 深度融合: 政策方向、产业资本、主题雷达、因子选股、regime路由、级联引擎、策略集成 —— 互相喂数据、互相校验
- 上帝视角: 先把全局看透 (政策→产业→资金→情绪→技术), 再落到具体标的和仓位决策

你的回答应该:
1. 简洁、有操作价值
2. 先给结论, 再给依据
3. 明确标注置信度 (高/中/低)
4. 给出可执行的建议 (买入/卖出/观望/调仓)
"""

# 按意图匹配的 user prompt 模板
INTENT_TEMPLATES: dict[BrainIntent, str] = {
    BrainIntent.MARKET_ASSESSMENT: (
        "请基于以下系统上下文, 给出今日市场研判和操作建议。\n\n{context}"
    ),
    BrainIntent.STRATEGY_REVIEW: (
        "请复盘以下策略表现, 分析胜率变化原因和优化方向。\n\n{context}"
    ),
    BrainIntent.RISK_ALERT: (
        "系统检测到以下风险信号, 请评估风险等级并给出应对建议。\n\n{context}"
    ),
    BrainIntent.POSITION_ADVICE: (
        "基于当前持仓和市场环境, 请给出仓位调整建议。\n\n{context}"
    ),
    BrainIntent.SIGNAL_EVALUATION: (
        "请评估以下交易信号的质量, 给出是否跟随的建议。\n\n{context}"
    ),
    BrainIntent.NIGHT_ANALYSIS: (
        "请进行夜间深度分析: 今日复盘 + 明日展望 + 策略调优建议。\n\n{context}"
    ),
    BrainIntent.FREEFORM: "{user_query}\n\n参考上下文:\n{context}",
}


class PromptBuilder:
    """根据意图和上下文组装完整 prompt"""

    def __init__(self, system_prompt: str = SYSTEM_PROMPT):
        self._system_prompt = system_prompt

    def build(
        self,
        intent: BrainIntent,
        context_blocks: dict[str, str],
        user_query: str = "",
    ) -> dict[str, str]:
        """返回 {"system": ..., "user": ...} 用于 LLM 调用"""
        # 合并上下文块
        context_text = "\n\n".join(
            f"## {name}\n{text}" for name, text in context_blocks.items()
        )
        # 选模板
        template = INTENT_TEMPLATES.get(intent, INTENT_TEMPLATES[BrainIntent.FREEFORM])
        user_prompt = template.format(
            context=context_text,
            user_query=user_query or "",
        )
        return {
            "system": self._system_prompt,
            "user": user_prompt,
        }


# ================================================================
#  Tool Hub — 可注册的工具 (Phase 2 完整实现)
# ================================================================

class ToolHub:
    """Brain 可调用的工具注册中心 (骨架)"""

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, handler: callable,
                 parameters: Optional[dict] = None):
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
            "parameters": parameters or {},
        }
        logger.info("Tool registered: %s", name)

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {"name": t["name"], "description": t["description"]}
            for t in self._tools.values()
        ]

    def call(self, name: str, arguments: dict) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"未知工具: {name}")
        return tool["handler"](**arguments)

    def to_llm_schema(self) -> list[dict]:
        """导出为 LLM function-calling 格式"""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in self._tools.values()
        ]


# ================================================================
#  Orchestrator — 核心编排
# ================================================================

# 单例组件
_context_assembler = ContextAssembler()
_prompt_builder = PromptBuilder()
_tool_hub = ToolHub()


def orchestrate(request: BrainRequest) -> BrainResponse:
    """
    核心编排入口:
      1. Context Assembler 收集上下文
      2. Prompt Builder 组装 prompt
      3. 调用 LLM (当前为骨架, 返回 prompt 摘要)
      4. 解析响应, 执行 tool calls
      5. 返回 BrainResponse
    """
    t0 = time.perf_counter()

    # Step 1: 收集上下文
    context_blocks = _context_assembler.assemble(request.context_scope)

    # Step 2: 组装 prompt
    prompts = _prompt_builder.build(
        intent=request.intent,
        context_blocks=context_blocks,
        user_query=request.user_query,
    )

    # Step 3: LLM 调用 (骨架 — Phase 2 接入实际 LLM)
    # 当前返回 prompt 摘要作为占位
    answer = _call_llm_stub(prompts, request)

    latency_ms = (time.perf_counter() - t0) * 1000

    response = BrainResponse(
        intent=request.intent,
        answer=answer,
        confidence=0.5,
        context_used=list(context_blocks.keys()),
        model_used="stub",
        latency_ms=round(latency_ms, 2),
    )

    logger.info(
        "Brain orchestrate [%s] %.0fms, context=%s",
        request.intent.value,
        latency_ms,
        request.context_scope,
    )

    return response


def _call_llm_stub(prompts: dict[str, str], request: BrainRequest) -> str:
    """LLM 调用占位 — Phase 2 替换为 DeepSeek / Anthropic API"""
    context_summary = ", ".join(
        f"{k}({len(v)}字)" for k, v in
        _context_assembler.assemble(request.context_scope).items()
    )
    return (
        f"[Brain Stub] 意图: {request.intent.value}\n"
        f"上下文模块: {context_summary}\n"
        f"System prompt: {len(prompts['system'])}字\n"
        f"User prompt: {len(prompts['user'])}字\n"
        f"等待 Phase 2 接入实际 LLM 后返回真实分析结果。"
    )


# ================================================================
#  便捷 API
# ================================================================

def market_assessment(extra_scopes: Optional[list[str]] = None) -> BrainResponse:
    """盘前市场研判"""
    scopes = ["regime", "positions", "signals", "policy", "news"]
    if extra_scopes:
        scopes.extend(extra_scopes)
    return orchestrate(BrainRequest(
        intent=BrainIntent.MARKET_ASSESSMENT,
        context_scope=scopes,
    ))


def risk_alert(alert_context: str = "") -> BrainResponse:
    """风险预警分析"""
    return orchestrate(BrainRequest(
        intent=BrainIntent.RISK_ALERT,
        user_query=alert_context,
        context_scope=["regime", "positions", "scorecard"],
    ))


def night_analysis() -> BrainResponse:
    """夜间深度分析"""
    return orchestrate(BrainRequest(
        intent=BrainIntent.NIGHT_ANALYSIS,
        context_scope=[
            "regime", "positions", "signals", "scorecard",
            "policy", "industry_capital", "news", "learning", "memory",
        ],
    ))


def ask(query: str, scopes: Optional[list[str]] = None) -> BrainResponse:
    """自由问答"""
    return orchestrate(BrainRequest(
        intent=BrainIntent.FREEFORM,
        user_query=query,
        context_scope=scopes or ["regime", "positions", "signals"],
    ))


# ================================================================
#  注册默认工具 (Phase 2 扩展)
# ================================================================

def _register_default_tools():
    """注册系统内置工具"""
    _tool_hub.register(
        name="pause_strategy",
        description="暂停指定策略",
        handler=lambda strategy, reason="brain_decision": logger.info(
            "Tool: pause_strategy(%s, %s)", strategy, reason
        ),
        parameters={
            "type": "object",
            "properties": {
                "strategy": {"type": "string", "description": "策略名称"},
                "reason": {"type": "string", "description": "暂停原因"},
            },
            "required": ["strategy"],
        },
    )
    _tool_hub.register(
        name="get_scorecard",
        description="获取近N日策略打分数据",
        handler=lambda days=7: logger.info("Tool: get_scorecard(%d)", days),
        parameters={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "查询天数", "default": 7},
            },
        },
    )


_register_default_tools()
