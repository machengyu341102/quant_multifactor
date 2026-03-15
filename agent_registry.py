"""
智能体注册表 — 多智能体管理基础设施
====================================
注册、追踪、健康监控所有子智能体

核心组件:
  - AgentInfo: 智能体信息数据结构
  - AgentRegistry: 注册/注销/健康追踪/持久化
  - register_builtin_agents(): 启动时自动注册内建智能体

用法:
  from agent_registry import get_registry
  registry = get_registry()
  registry.register("my_agent", "我的智能体", "my_module", ["cap1"])
  registry.report_run("my_agent", success=True)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("agent_registry")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_REGISTRY_PATH = os.path.join(_BASE_DIR, "agents_registry.json")


# ================================================================
#  AgentInfo 数据结构
# ================================================================

@dataclass
class AgentInfo:
    name: str                  # "risk_inspector"
    display_name: str          # "风控督察"
    module: str                # "portfolio_risk"
    capabilities: list = field(default_factory=list)  # ["risk_monitoring"]
    schedule: str = "every OODA cycle"
    status: str = "active"     # "active" / "paused" / "error"
    health: float = 1.0        # 0.0-1.0
    last_run: str = ""         # ISO 时间戳
    error_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> AgentInfo:
        return cls(
            name=d.get("name", ""),
            display_name=d.get("display_name", ""),
            module=d.get("module", ""),
            capabilities=d.get("capabilities", []),
            schedule=d.get("schedule", "every OODA cycle"),
            status=d.get("status", "active"),
            health=d.get("health", 1.0),
            last_run=d.get("last_run", ""),
            error_count=d.get("error_count", 0),
            last_error=d.get("last_error", ""),
        )


# ================================================================
#  AgentRegistry 类
# ================================================================

class AgentRegistry:
    """智能体注册表"""

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._load()

    def register(self, name: str, display_name: str, module: str,
                 capabilities: list, schedule: str = "every OODA cycle") -> AgentInfo:
        """注册智能体 (已存在则更新 display_name/module/capabilities)"""
        if name in self._agents:
            agent = self._agents[name]
            agent.display_name = display_name
            agent.module = module
            agent.capabilities = capabilities
            agent.schedule = schedule
        else:
            agent = AgentInfo(
                name=name,
                display_name=display_name,
                module=module,
                capabilities=capabilities,
                schedule=schedule,
            )
            self._agents[name] = agent
            logger.debug("注册智能体: %s (%s)", display_name, name)
        return agent

    def unregister(self, name: str) -> bool:
        """注销智能体"""
        if name in self._agents:
            del self._agents[name]
            return True
        return False

    def get_agent(self, name: str) -> AgentInfo | None:
        """获取智能体信息"""
        return self._agents.get(name)

    def list_agents(self, status: str = None) -> list[AgentInfo]:
        """列出所有智能体, 可按状态过滤"""
        agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a.status == status]
        return agents

    def update_health(self, name: str, health: float, error_msg: str = None):
        """更新健康度. health < 0.3 自动标记 error"""
        agent = self._agents.get(name)
        if not agent:
            return
        agent.health = max(0.0, min(1.0, health))
        if error_msg:
            agent.last_error = error_msg
        if agent.health < 0.3:
            agent.status = "error"
        elif agent.status == "error" and agent.health >= 0.5:
            agent.status = "active"

    def report_run(self, name: str, success: bool = True, error_msg: str = None):
        """报告运行结果, 更新 last_run + error_count + health"""
        agent = self._agents.get(name)
        if not agent:
            return
        agent.last_run = datetime.now().isoformat()
        if success:
            agent.error_count = 0
            # 健康度回升 (EMA)
            agent.health = min(1.0, agent.health * 0.8 + 0.2)
            if agent.status == "error":
                agent.status = "active"
        else:
            agent.error_count += 1
            if error_msg:
                agent.last_error = error_msg
            # 健康度下降
            agent.health = max(0.0, agent.health * 0.8)
            if agent.error_count >= 3:
                agent.status = "error"

    def get_unhealthy(self, threshold: float = 0.5) -> list[AgentInfo]:
        """获取健康度低于阈值的智能体"""
        return [a for a in self._agents.values() if a.health < threshold]

    def persist(self):
        """保存到 agents_registry.json"""
        data = {name: agent.to_dict() for name, agent in self._agents.items()}
        safe_save(_REGISTRY_PATH, data)

    # ---- 内部方法 ----

    def _load(self):
        """从持久化文件加载"""
        data = safe_load(_REGISTRY_PATH, default={})
        if isinstance(data, dict):
            for name, d in data.items():
                try:
                    self._agents[name] = AgentInfo.from_dict(d)
                except Exception:
                    continue


# ================================================================
#  内建注册
# ================================================================

def register_builtin_agents(registry: AgentRegistry = None):
    """启动时自动注册内建智能体"""
    if registry is None:
        registry = get_registry()

    builtins = [
        ("brain",            "智能体大脑",  "agent_brain",    ["ooda_cycle", "coordination"]),
        ("risk_inspector",   "风控督察",    "portfolio_risk", ["risk_monitoring", "drawdown_alert"]),
        ("market_radar",     "行情雷达",    "smart_trader",   ["regime_detection"]),
        ("factor_researcher","选股研究员",   "experiment_lab", ["factor_discovery", "ab_test"]),
        ("execution_judge",  "执行裁判",    "trade_executor", ["trade_monitoring"]),
        ("healer",           "系统自愈",    "self_healer",    ["health_check", "auto_repair"]),
        ("crypto_scanner",   "币圈扫描",    "crypto_strategy",["crypto_trend_scan"]),
        ("us_stock_analyzer","美股分析",    "us_stock_strategy",["us_stock_analysis"]),
        ("cross_market",     "跨市场推演",  "cross_market_strategy",["cross_market_signal", "risk_appetite"]),
        ("stock_analyst",    "个股诊断",    "stock_analyzer",      ["single_stock_analysis", "on_demand"]),
    ]
    for name, display, module, caps in builtins:
        registry.register(name, display, module, caps)

    return registry


# ================================================================
#  绩效考核
# ================================================================

def run_performance_review() -> dict:
    """每日绩效考核 — 22:30 夜班调用

    基于 watchdog (准时率) + scorecard (产出质量) + registry (稳定性) 综合打分

    Returns:
        {
            "date": "2026-03-02",
            "agents": {name: {score, grade, details}},
            "summary": "...",
        }
    """
    from datetime import date as _date
    today_str = _date.today().isoformat()
    registry = get_registry()
    register_builtin_agents(registry)

    # --- 数据采集 ---

    # 1. watchdog: 策略运行状态 (准时率/成功率)
    heartbeat = {}
    try:
        heartbeat = safe_load(
            os.path.join(_BASE_DIR, "heartbeat.json"), default={})
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    strategy_status = heartbeat.get("strategy_status", {})

    # 2. scorecard: 产出质量 (胜率/收益)
    strategy_scores = {}
    try:
        from scorecard import calc_cumulative_stats
        stats_7d = calc_cumulative_stats(7)
        strategy_scores = stats_7d.get("by_strategy", {})
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # --- 智能体逐个评分 ---
    # 映射: 智能体 → 关联策略
    agent_strategies = {
        "brain":            [],
        "risk_inspector":   [],
        "market_radar":     [],
        "factor_researcher":[],
        "execution_judge":  list(strategy_status.keys()),
        "healer":           [],
    }

    results = {}
    for agent in registry.list_agents():
        score = 50.0  # 基础分
        details = []

        # (A) 健康度加减分: 满分 +20, 每降0.1扣4分
        health_bonus = (agent.health - 0.5) * 40  # 1.0→+20, 0.5→0, 0→-20
        score += health_bonus
        details.append(f"健康度{agent.health:.0%} ({health_bonus:+.0f})")

        # (B) 错误次数扣分: 每次 -5
        error_penalty = agent.error_count * -5
        if error_penalty:
            score += error_penalty
            details.append(f"错误{agent.error_count}次 ({error_penalty:+.0f})")

        # (C) 执行裁判: 关联策略的成功率
        if agent.name == "execution_judge" and strategy_status:
            successes = sum(1 for s in strategy_status.values()
                           if s.get("status") == "success")
            total = len(strategy_status)
            if total > 0:
                success_rate = successes / total
                exec_bonus = (success_rate - 0.8) * 50  # 100%→+10, 80%→0, 60%→-10
                score += exec_bonus
                details.append(f"策略成功率{success_rate:.0%} ({exec_bonus:+.0f})")

        # (D) 行情雷达: 有没有及时检测行情
        if agent.name == "market_radar":
            if agent.last_run and agent.last_run[:10] == today_str:
                score += 10
                details.append("今日已检测行情 (+10)")
            else:
                score -= 10
                details.append("今日未检测行情 (-10)")

        # (E) 选股研究员: 策略整体胜率
        if agent.name == "factor_researcher" and strategy_scores:
            overall_wr = sum(s.get("win_rate", 0) for s in strategy_scores.values())
            n = len(strategy_scores)
            if n > 0:
                avg_wr = overall_wr / n
                factor_bonus = (avg_wr - 50) * 0.4  # 60%→+4, 50%→0, 40%→-4
                score += factor_bonus
                details.append(f"策略均胜率{avg_wr:.0f}% ({factor_bonus:+.1f})")

        # (F) 风控督察: 有无漏报风险
        if agent.name == "risk_inspector":
            if agent.last_run and agent.last_run[:10] == today_str:
                score += 10
                details.append("今日已执行风控检查 (+10)")

        # (G) 总经理: OODA 循环是否执行
        if agent.name == "brain":
            try:
                mem = safe_load(os.path.join(_BASE_DIR, "agent_memory.json"), default={})
                last_cycle = mem.get("meta", {}).get("last_cycle", "")
                if last_cycle[:10] == today_str:
                    score += 15
                    details.append("今日OODA已执行 (+15)")
                else:
                    score -= 15
                    details.append("今日OODA未执行 (-15)")
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        # 分数边界
        score = max(0, min(100, score))

        # 等级
        if score >= 90:
            grade = "S"
        elif score >= 75:
            grade = "A"
        elif score >= 60:
            grade = "B"
        elif score >= 40:
            grade = "C"
        else:
            grade = "D"

        results[agent.name] = {
            "display_name": agent.display_name,
            "score": round(score, 1),
            "grade": grade,
            "health": agent.health,
            "details": details,
        }

        # 绩效反馈到健康度: S/A 加分, D 扣分
        if grade in ("S", "A"):
            registry.update_health(agent.name, min(1.0, agent.health + 0.02))
        elif grade == "D":
            registry.update_health(agent.name, max(0.0, agent.health - 0.05))

    registry.persist()

    # 汇总
    avg_score = (sum(r["score"] for r in results.values()) / len(results)
                 if results else 0)
    grade_counts = {}
    for r in results.values():
        grade_counts[r["grade"]] = grade_counts.get(r["grade"], 0) + 1

    summary = (f"团队均分 {avg_score:.0f} | "
               + " ".join(f"{g}:{c}" for g, c in sorted(grade_counts.items())))

    review = {
        "date": today_str,
        "agents": results,
        "summary": summary,
        "avg_score": round(avg_score, 1),
    }

    # 持久化考核记录
    reviews_path = os.path.join(_BASE_DIR, "performance_reviews.json")
    reviews = safe_load(reviews_path, default=[])
    # 保留最近 30 天
    reviews = [r for r in reviews if r.get("date", "") >= today_str[:8]][-29:]
    reviews.append(review)
    safe_save(reviews_path, reviews)

    logger.info("[绩效] %s", summary)
    return review


# ================================================================
#  单例
# ================================================================

_registry_instance: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """获取全局 AgentRegistry 单例"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = AgentRegistry()
    return _registry_instance


def reset_registry():
    """重置单例 (测试用)"""
    global _registry_instance
    _registry_instance = None


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    registry = get_registry()
    register_builtin_agents(registry)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        agents = registry.list_agents()
        print(f"\n=== 注册智能体 ({len(agents)}) ===")
        for a in agents:
            health_bar = "+" * int(a.health * 10) + "-" * (10 - int(a.health * 10))
            print(f"  {a.display_name} ({a.name})")
            print(f"    模块: {a.module} | 状态: {a.status} | 健康: [{health_bar}] {a.health:.0%}")
            print(f"    能力: {', '.join(a.capabilities)}")
            if a.last_run:
                print(f"    上次运行: {a.last_run[:19]}")
            if a.last_error:
                print(f"    最近错误: {a.last_error}")
    elif cmd == "health":
        unhealthy = registry.get_unhealthy()
        if unhealthy:
            print(f"\n=== 不健康智能体 ({len(unhealthy)}) ===")
            for a in unhealthy:
                print(f"  {a.display_name}: 健康度 {a.health:.0%}, 错误 {a.error_count} 次")
        else:
            print("所有智能体状态正常")
    else:
        print("用法:")
        print("  python3 agent_registry.py list     # 列出所有智能体")
        print("  python3 agent_registry.py health   # 查看不健康智能体")
