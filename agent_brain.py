"""
智能体大脑 — OODA 循环 + LLM 深度推理 + 多智能体协调
=====================================================
多智能体协调中心 (总经理):
  - 观察 (Observe): 收集系统状态快照
  - 判断 (Orient): 9个检测器 + 事件总线 + 冲突仲裁 + LLM深度分析
  - 决策 (Decide): 规则引擎 + LLM辅助决策
  - 行动 (Act): 暂停/恢复策略, 通知用户, 记录洞察
  - 学习 (Learn): 更新规则 + LLM认知提取
  - 夜班 (Night): 22:30+ 深度复盘/因子体检/明日预判

CLI:
  python3 agent_brain.py              # 运行OODA循环
  python3 agent_brain.py status       # 查看策略状态 + 活跃规则
  python3 agent_brain.py pause 放量突破  # 手动暂停
  python3 agent_brain.py resume 放量突破 # 手动恢复
  python3 agent_brain.py rules        # 查看所有规则及置信度
  python3 agent_brain.py insights     # 查看历史洞察
  python3 agent_brain.py agents       # 查看注册智能体
  python3 agent_brain.py events       # 查看事件总线
  python3 agent_brain.py night        # 手动运行夜班分析
"""

from __future__ import annotations

import os
import sys
import copy
from datetime import datetime, date, timedelta

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from config import AGENT_PARAMS
from log_config import get_logger

logger = get_logger("agent_brain")

# ================================================================
#  常量 & 路径
# ================================================================

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_MEMORY_PATH = os.path.join(_BASE_DIR, "agent_memory.json")
_SCORECARD_PATH = os.path.join(_BASE_DIR, "scorecard.json")

STRATEGY_NAMES = [
    "集合竞价选股", "放量突破选股", "尾盘短线选股",
    "低吸回调选股", "缩量整理选股", "趋势跟踪选股", "板块轮动选股",
    "事件驱动选股", "期货趋势选股", "币圈趋势选股", "美股收盘分析",
]

# 每日主动推送计数 (进程内)
_proactive_push_count = {"date": "", "count": 0}


# ================================================================
#  种子规则
# ================================================================

SEED_RULES = [
    {
        "id": "R001", "type": "consecutive_loss",
        "condition": {"strategy": "*", "metric": "consecutive_losses",
                      "operator": ">=", "threshold": 4},
        "action": "pause_strategy", "confidence": 0.90,
        "evidence_count": 0, "source": "seed",
        "description": "连亏4次自动暂停",
    },
    {
        "id": "R002", "type": "regime_mismatch",
        "condition": {"metric": "regime_win_rate", "operator": "<",
                      "threshold": 0.25},
        "action": "pause_strategy", "confidence": 0.70,
        "evidence_count": 0, "source": "seed",
        "description": "策略在当前行情下历史胜率<25%, 暂停",
    },
    {
        "id": "R003", "type": "recovery",
        "condition": {"metric": "regime_win_rate", "operator": ">=",
                      "threshold": 0.45},
        "action": "resume_strategy", "confidence": 0.65,
        "evidence_count": 0, "source": "seed",
        "description": "被暂停策略在当前行情下恢复到45%胜率, 恢复",
    },
]


# ================================================================
#  默认记忆结构
# ================================================================

def _default_memory() -> dict:
    """返回默认的 agent_memory 结构"""
    states = {}
    for name in STRATEGY_NAMES:
        states[name] = {
            "status": "active",
            "paused_since": None,
            "pause_reason": None,
            "auto_resume_date": None,
            "consecutive_losses": 0,
            "consecutive_wins": 0,
            "last_5_results": [],
        }
    return {
        "strategy_states": states,
        "rules": copy.deepcopy(SEED_RULES),
        "insights": [],
        "meta": {"last_cycle": None, "total_cycles": 0},
    }


def _load_memory() -> dict:
    """加载记忆, 确保结构完整"""
    mem = safe_load(_MEMORY_PATH, default=_default_memory())
    # 确保 strategy_states 包含所有策略
    states = mem.setdefault("strategy_states", {})
    for name in STRATEGY_NAMES:
        if name not in states:
            states[name] = {
                "status": "active", "paused_since": None,
                "pause_reason": None, "auto_resume_date": None,
                "consecutive_losses": 0, "consecutive_wins": 0,
                "last_5_results": [],
            }
    mem.setdefault("rules", copy.deepcopy(SEED_RULES))
    mem.setdefault("insights", [])
    mem.setdefault("meta", {"last_cycle": None, "total_cycles": 0})
    return mem


_last_saved_hash = None


def _save_memory(mem: dict):
    """只在内容变化时写磁盘, 减少无效 IO"""
    global _last_saved_hash
    import hashlib, json
    # 用策略状态+洞察数+meta 做轻量哈希
    key_data = json.dumps({
        "states": {k: v.get("status") for k, v in mem.get("strategy_states", {}).items()},
        "n_insights": len(mem.get("insights", [])),
        "cycles": mem.get("meta", {}).get("total_cycles", 0),
    }, sort_keys=True)
    h = hashlib.md5(key_data.encode()).hexdigest()
    if h == _last_saved_hash:
        return  # 无变化, 跳过写入
    safe_save(_MEMORY_PATH, mem)
    _last_saved_hash = h


# ================================================================
#  1. 观察 — observe()
# ================================================================

# 增量缓存: 避免每次 OODA 全量扫描 scorecard
_observe_cache = {
    "metrics": {},         # strategy_name -> metrics dict
    "scorecard_len": 0,    # 上次处理的 scorecard 长度
    "last_date": "",       # 上次处理的最新日期
}


def observe() -> dict:
    """收集系统状态快照 (增量处理 scorecard, 仅新数据触发重算)"""
    global _observe_cache
    snapshot = {
        "strategy_metrics": {},
        "signal_health": [],
        "regime_fit": [],
        "current_regime": "neutral",
    }

    # --- 从 scorecard.json 计算每个策略的滚动指标 (增量) ---
    scorecard = safe_load(_SCORECARD_PATH, default=[])
    sc_len = len(scorecard)
    latest_date = max((r.get("rec_date", "") for r in scorecard), default="") if scorecard else ""

    # 有新数据时才重算
    if sc_len != _observe_cache["scorecard_len"] or latest_date != _observe_cache["last_date"]:
        for name in STRATEGY_NAMES:
            records = [r for r in scorecard if r.get("strategy") == name]
            records.sort(key=lambda r: r.get("rec_date", ""), reverse=True)

            recent_5 = records[:5]
            results_5 = [r.get("result", "") for r in recent_5]
            wins_5 = sum(1 for r in results_5 if r == "win")
            win_rate_5 = wins_5 / len(results_5) if results_5 else None
            avg_return_5 = (sum(r.get("net_return_pct", 0) for r in recent_5) / len(recent_5)
                            if recent_5 else None)

            consec_losses = 0
            consec_wins = 0
            for r in records:
                if r.get("result") == "loss":
                    consec_losses += 1
                else:
                    break
            for r in records:
                if r.get("result") == "win":
                    consec_wins += 1
                else:
                    break

            _observe_cache["metrics"][name] = {
                "consecutive_losses": consec_losses,
                "consecutive_wins": consec_wins,
                "rolling_5d_win_rate": win_rate_5,
                "rolling_5d_avg_return": avg_return_5,
                "total_samples": len(records),
            }

        _observe_cache["scorecard_len"] = sc_len
        _observe_cache["last_date"] = latest_date
        logger.info("[Agent] observe: scorecard 变更, 重算指标 (%d条, 最新%s)", sc_len, latest_date)
    else:
        logger.debug("[Agent] observe: scorecard 无变化, 复用缓存")

    snapshot["strategy_metrics"] = dict(_observe_cache["metrics"])

    # --- 信号健康度 ---
    try:
        from learning_engine import analyze_signal_accuracy
        snapshot["signal_health"] = analyze_signal_accuracy()
    except Exception as e:
        logger.debug("信号分析不可用: %s", e)

    # --- 策略-行情适配 ---
    try:
        from learning_engine import analyze_strategy_regime_fit
        snapshot["regime_fit"] = analyze_strategy_regime_fit()
    except Exception as e:
        logger.debug("行情适配分析不可用: %s", e)

    return snapshot


# ================================================================
#  2. 判断 — orient()
# ================================================================

def orient(snapshot: dict, memory: dict) -> list:
    """运行所有异常检测器, 返回 findings 列表"""
    findings = []
    detectors = [
        detect_consecutive_losses,
        detect_win_rate_degradation,
        detect_regime_strategy_mismatch,
        detect_factor_decay,
        detect_signal_drift,
        detect_strategy_recovery,
        detect_auto_resume,
        detect_optimization_regression,
        detect_portfolio_risk,
        detect_signal_quality,
    ]
    for detector in detectors:
        try:
            findings.extend(detector(snapshot, memory))
        except Exception as e:
            logger.debug("检测器 %s 异常: %s", detector.__name__, e)

    # 将 findings 发射到事件总线 (供其他模块观察)
    _emit_findings_to_bus(findings)

    return findings


def detect_consecutive_losses(snapshot: dict, memory: dict) -> list:
    """连亏 >= auto_pause_consecutive_losses → critical: pause_strategy"""
    threshold = AGENT_PARAMS.get("auto_pause_consecutive_losses", 4)
    findings = []
    for name, metrics in snapshot.get("strategy_metrics", {}).items():
        consec = metrics.get("consecutive_losses", 0)
        state = memory.get("strategy_states", {}).get(name, {})
        if consec >= threshold and state.get("status") != "paused":
            findings.append({
                "type": "anomaly",
                "severity": "critical",
                "strategy": name,
                "message": f"{name}连续亏损{consec}次, 达到阈值{threshold}",
                "suggested_action": "pause_strategy",
                "confidence": 0.90,
            })
    return findings


def detect_win_rate_degradation(snapshot: dict, memory: dict) -> list:
    """5日胜率 < 20% 且样本>=5 → warning: escalate_human"""
    findings = []
    for name, metrics in snapshot.get("strategy_metrics", {}).items():
        win_rate = metrics.get("rolling_5d_win_rate")
        samples = metrics.get("total_samples", 0)
        if win_rate is not None and win_rate < 0.20 and samples >= 5:
            state = memory.get("strategy_states", {}).get(name, {})
            if state.get("status") != "paused":
                findings.append({
                    "type": "anomaly",
                    "severity": "warning",
                    "strategy": name,
                    "message": f"{name}近5日胜率{win_rate:.0%}, 远低于正常水平",
                    "suggested_action": "escalate_human",
                    "confidence": 0.75,
                })
    return findings


def detect_regime_strategy_mismatch(snapshot: dict, memory: dict) -> list:
    """策略在当前行情下历史胜率 < 25% → warning: pause_strategy"""
    findings = []
    regime_fit = snapshot.get("regime_fit", [])
    current_regime = snapshot.get("current_regime", "neutral")

    for item in regime_fit:
        name = item.get("strategy", "")
        regime = item.get("regime", "")
        win_rate = item.get("win_rate")
        samples = item.get("samples", 0)

        if regime != current_regime or win_rate is None or samples < 5:
            continue

        state = memory.get("strategy_states", {}).get(name, {})
        if win_rate < 0.25 and state.get("status") != "paused":
            findings.append({
                "type": "anomaly",
                "severity": "warning",
                "strategy": name,
                "message": (f"{name}在{regime}行情下胜率仅{win_rate:.0%}"
                            f"(样本{samples}), 建议暂停"),
                "suggested_action": "pause_strategy",
                "confidence": 0.70,
            })
    return findings


def detect_factor_decay(snapshot: dict, memory: dict) -> list:
    """因子相关性从正转负 → 轻微: log_insight, 严重: deweight_factor"""
    findings = []
    decay_threshold = -0.05
    severe_threshold = -0.15

    for sig in snapshot.get("signal_health", []):
        corr = sig.get("correlation")
        signal_name = sig.get("signal", "")
        if corr is None or corr >= decay_threshold:
            continue

        if corr < severe_threshold:
            # 严重衰减: 主动降权
            findings.append({
                "type": "anomaly",
                "severity": "warning",
                "strategy": None,
                "signal_name": signal_name,
                "message": f"信号{signal_name}相关性严重转负({corr:.3f}), 建议降权",
                "suggested_action": "deweight_factor",
                "confidence": 0.70,
            })
        else:
            # 轻微衰减: 记录观察
            findings.append({
                "type": "anomaly",
                "severity": "info",
                "strategy": None,
                "signal_name": signal_name,
                "message": f"信号{signal_name}相关性转负({corr:.3f}), 因子可能失效",
                "suggested_action": "log_insight",
                "confidence": 0.50,
            })
    return findings


def detect_signal_drift(snapshot: dict, memory: dict) -> list:
    """信号预测力骤降 → info: log_insight"""
    findings = []
    for sig in snapshot.get("signal_health", []):
        pred = sig.get("predictive_value")
        signal_name = sig.get("signal", "")
        if pred is not None and pred < 2.0:
            findings.append({
                "type": "anomaly",
                "severity": "info",
                "strategy": None,
                "message": f"信号{signal_name}预测力低({pred:.1f}%), 可能漂移",
                "suggested_action": "log_insight",
                "confidence": 0.40,
            })
    return findings


def detect_strategy_recovery(snapshot: dict, memory: dict) -> list:
    """被暂停策略在当前行情下恢复到45%胜率 → info: resume_strategy"""
    findings = []
    regime_fit = snapshot.get("regime_fit", [])
    current_regime = snapshot.get("current_regime", "neutral")

    for item in regime_fit:
        name = item.get("strategy", "")
        regime = item.get("regime", "")
        win_rate = item.get("win_rate")
        samples = item.get("samples", 0)

        if regime != current_regime or win_rate is None or samples < 5:
            continue

        state = memory.get("strategy_states", {}).get(name, {})
        if state.get("status") == "paused" and win_rate >= 0.45:
            findings.append({
                "type": "anomaly",
                "severity": "info",
                "strategy": name,
                "message": (f"{name}在{regime}行情下胜率恢复至{win_rate:.0%}"
                            f", 可以考虑恢复"),
                "suggested_action": "resume_strategy",
                "confidence": 0.65,
            })
    return findings


def detect_auto_resume(snapshot: dict, memory: dict) -> list:
    """暂停已到 auto_resume_date → info: resume_strategy"""
    findings = []
    today_str = date.today().isoformat()
    for name, state in memory.get("strategy_states", {}).items():
        if state.get("status") != "paused":
            continue
        resume_date = state.get("auto_resume_date")
        if resume_date and today_str >= resume_date:
            findings.append({
                "type": "anomaly",
                "severity": "info",
                "strategy": name,
                "message": f"{name}暂停期已满(目标恢复日{resume_date}), 自动恢复",
                "suggested_action": "resume_strategy",
                "confidence": 0.90,
            })
    return findings


def detect_optimization_regression(snapshot: dict, memory: dict) -> list:
    """优化验证: 检查是否有待验证的优化到期, 触发回滚"""
    try:
        from auto_optimizer import check_pending_verifications
        results = check_pending_verifications()
        findings = []
        for r in results:
            if r.get("verdict") == "rolled_back":
                findings.append({
                    "type": "anomaly",
                    "severity": "warning",
                    "strategy": r.get("strategy"),
                    "message": (f"{r['strategy']}优化验证失败 "
                                f"(得分 {r['pre_score']}→{r['post_score']}), 已自动回滚"),
                    "suggested_action": "escalate_human",
                    "confidence": 0.90,
                })
            elif r.get("verdict") == "verified_ok":
                findings.append({
                    "type": "info",
                    "severity": "info",
                    "strategy": r.get("strategy"),
                    "message": (f"{r['strategy']}优化验证通过 "
                                f"(得分 {r['pre_score']}→{r['post_score']})"),
                    "suggested_action": "log_insight",
                    "confidence": 0.95,
                })
        return findings
    except Exception:
        return []


def detect_portfolio_risk(snapshot: dict, memory: dict) -> list:
    """组合层风控检测器 (L4): 调用 portfolio_risk 模块"""
    try:
        from portfolio_risk import check_portfolio_risk
        return check_portfolio_risk().get("findings", [])
    except Exception:
        return []


def detect_signal_quality(snapshot: dict, memory: dict) -> list:
    """信号质量检测器: 用实际验证数据发现策略退化"""
    findings = []
    try:
        from signal_tracker import get_stats, get_feedback_for_learning

        stats = get_stats(days=14)
        if stats.get("total", 0) < 10:
            return []  # 数据不够, 不做判断

        # 1. 策略级 T+1 胜率暴跌
        for strategy, info in stats.get("by_strategy", {}).items():
            wr = info.get("t1_win_rate")
            if wr is not None and info["total"] >= 5 and wr < 30:
                findings.append({
                    "type": "signal_quality_degradation",
                    "message": f"策略 [{strategy}] T+1胜率仅 {wr}% (近14天, {info['total']}条)",
                    "severity": "warning",
                    "confidence": 0.7,
                    "suggested_action": "pause_strategy",
                    "details": {"strategy": strategy, "win_rate": wr, "total": info["total"]},
                })

        # 2. 信号衰减严重 (T+1 赚但 T+5 亏 → 信号太短命)
        feedback = get_feedback_for_learning()
        for strategy, decay in feedback.get("signal_decay", {}).items():
            if decay.get("fast_decay") and decay.get("avg_t1", 0) > 0 and decay.get("avg_t5", 0) < -1:
                findings.append({
                    "type": "signal_fast_decay",
                    "message": f"策略 [{strategy}] 信号快速衰减: T+1={decay['avg_t1']:+.1f}% → T+5={decay['avg_t5']:+.1f}%",
                    "severity": "info",
                    "confidence": 0.6,
                    "suggested_action": "log_insight",
                    "details": {"strategy": strategy, **decay},
                })

        # 3. 整体胜率过低
        overall = stats.get("overall", {})
        overall_wr = overall.get("t1_win_rate")
        if overall_wr is not None and overall_wr < 35:
            findings.append({
                "type": "overall_signal_weak",
                "message": f"整体信号质量偏低: T+1胜率 {overall_wr}% ({stats['total']}条)",
                "severity": "warning",
                "confidence": 0.65,
                "suggested_action": "reduce_exposure",
                "details": {"win_rate": overall_wr, "total": stats["total"]},
            })

    except Exception:
        pass
    return findings


# ================================================================
#  3. 决策 — decide()
# ================================================================

def decide(findings: list, memory: dict) -> list:
    """对每个 finding 匹配规则, 决定是否自主行动"""
    min_conf = AGENT_PARAMS.get("min_rule_confidence", 0.6)
    decisions = []

    for f in findings:
        action = f.get("suggested_action", "log_insight")
        confidence = f.get("confidence", 0)
        severity = f.get("severity", "info")

        # 匹配规则 (可能覆盖置信度)
        matched_rule = _match_rule(f, memory.get("rules", []))
        if matched_rule:
            confidence = max(confidence, matched_rule.get("confidence", 0))

        # critical 无论置信度都执行+通知
        if severity == "critical":
            decisions.append({
                "finding": f,
                "action": action,
                "execute": True,
                "notify": True,
                "rule": matched_rule,
            })
        elif confidence >= min_conf:
            decisions.append({
                "finding": f,
                "action": action,
                "execute": True,
                "notify": action != "log_insight",
                "rule": matched_rule,
            })
        elif confidence >= 0.4:
            decisions.append({
                "finding": f,
                "action": action,
                "execute": False,
                "notify": True,
                "rule": matched_rule,
            })
        else:
            # 低置信: 只记录
            decisions.append({
                "finding": f,
                "action": "log_insight",
                "execute": False,
                "notify": False,
                "rule": matched_rule,
            })

    return decisions


def _match_rule(finding: dict, rules: list) -> dict | None:
    """匹配 finding 到规则"""
    f_type = finding.get("type", "")
    strategy = finding.get("strategy", "")
    action = finding.get("suggested_action", "")

    for rule in rules:
        cond = rule.get("condition", {})
        rule_strategy = cond.get("strategy", "*")
        # 策略匹配
        if rule_strategy != "*" and rule_strategy != strategy:
            continue
        # action 匹配
        if rule.get("action") == action:
            return rule
    return None


# ================================================================
#  4. 行动 — act()
# ================================================================

def act(decisions: list, memory: dict):
    """执行决策列表"""
    for d in decisions:
        action = d.get("action", "log_insight")
        finding = d.get("finding", {})
        execute = d.get("execute", False)
        notify = d.get("notify", False)
        strategy = finding.get("strategy")
        message = finding.get("message", "")

        if execute:
            if action == "pause_strategy" and strategy:
                _action_pause_strategy(strategy, memory, message)
            elif action == "resume_strategy" and strategy:
                _action_resume_strategy(strategy, memory, message)
            elif action == "deweight_factor":
                _action_deweight_factor(finding)

        if notify:
            if action == "escalate_human":
                _action_escalate(message)
            elif action in ("pause_strategy", "resume_strategy"):
                _action_escalate(message)

        # 所有 findings 都记录为洞察
        _action_log_insight(memory, finding)


def _action_pause_strategy(strategy: str, memory: dict, reason: str):
    """暂停策略"""
    state = memory.get("strategy_states", {}).get(strategy)
    if not state:
        return
    resume_days = AGENT_PARAMS.get("auto_resume_days", 5)
    resume_date = (date.today() + timedelta(days=resume_days)).isoformat()

    state["status"] = "paused"
    state["paused_since"] = date.today().isoformat()
    state["pause_reason"] = reason
    state["auto_resume_date"] = resume_date
    logger.info("[Agent] 暂停策略: %s | 原因: %s | 自动恢复: %s",
                strategy, reason, resume_date)


def _action_resume_strategy(strategy: str, memory: dict, reason: str):
    """恢复策略"""
    state = memory.get("strategy_states", {}).get(strategy)
    if not state:
        return
    state["status"] = "active"
    state["paused_since"] = None
    state["pause_reason"] = None
    state["auto_resume_date"] = None
    logger.info("[Agent] 恢复策略: %s | 原因: %s", strategy, reason)


def _action_deweight_factor(finding: dict):
    """对衰减因子执行降权 (所有使用该因子的策略)"""
    signal_name = finding.get("signal_name", "")
    if not signal_name:
        return
    try:
        from auto_optimizer import deweight_factor, get_tunable_params, SUPPORTED_STRATEGIES
        for strategy in SUPPORTED_STRATEGIES:
            params = get_tunable_params(strategy)
            weights = params.get("weights", {})
            if signal_name in weights:
                deweight_factor(strategy, signal_name,
                                reason=f"Agent: {finding.get('message', '因子衰减')}")
    except Exception as e:
        logger.warning("[Agent] 因子降权异常: %s", e)


def _action_escalate(message: str):
    """主动推送洞察到微信 (受每日限额)"""
    global _proactive_push_count
    today_str = date.today().isoformat()
    max_push = AGENT_PARAMS.get("max_proactive_push_daily", 2)

    if _proactive_push_count["date"] != today_str:
        _proactive_push_count = {"date": today_str, "count": 0}

    if _proactive_push_count["count"] >= max_push:
        logger.info("[Agent] 今日主动推送已达上限 %d, 跳过: %s", max_push, message)
        return

    # 洞察不走微信 (节省配额, 纳入晚报汇总), 仅终端+macOS
    logger.info("[Agent洞察] %s", message)
    try:
        import subprocess
        short_msg = message[:180] if len(message) > 180 else message
        safe_msg = short_msg.replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "[Agent] 策略洞察" sound name "Glass"'],
            timeout=10, capture_output=True,
        )
    except Exception:
        pass
    _proactive_push_count["count"] += 1


def _action_log_insight(memory: dict, finding: dict):
    """记录洞察到 memory"""
    insight = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "severity": finding.get("severity", "info"),
        "message": finding.get("message", ""),
        "action_taken": finding.get("suggested_action", "log_insight"),
        "pushed": False,
    }
    insights = memory.setdefault("insights", [])
    insights.append(insight)
    # 保留最近 200 条
    if len(insights) > 200:
        memory["insights"] = insights[-200:]


# ================================================================
#  5. 学习 — learn()
# ================================================================

def learn(snapshot: dict, memory: dict):
    """更新策略状态, 发现/淘汰规则"""
    _update_strategy_states_from_snapshot(snapshot, memory)
    _discover_new_rules(snapshot, memory)
    _prune_rules(memory)


def _update_strategy_states_from_snapshot(snapshot: dict, memory: dict):
    """从快照更新连亏/连赢/last_5"""
    for name, metrics in snapshot.get("strategy_metrics", {}).items():
        state = memory.get("strategy_states", {}).get(name)
        if not state:
            continue
        state["consecutive_losses"] = metrics.get("consecutive_losses", 0)
        state["consecutive_wins"] = metrics.get("consecutive_wins", 0)

        # 从 scorecard 提取 last_5_results
        scorecard = safe_load(_SCORECARD_PATH, default=[])
        records = [r for r in scorecard if r.get("strategy") == name]
        records.sort(key=lambda r: r.get("rec_date", ""), reverse=True)
        state["last_5_results"] = [r.get("result", "") for r in records[:5]]


def update_strategy_states():
    """外部调用入口: scorecard 更新后刷新策略状态"""
    try:
        snapshot = observe()
        memory = _load_memory()
        _update_strategy_states_from_snapshot(snapshot, memory)
        _save_memory(memory)
        logger.info("[Agent] 策略状态已更新")
    except Exception as e:
        logger.warning("[Agent] 更新策略状态失败: %s", e)


def _discover_new_rules(snapshot: dict, memory: dict):
    """从 regime_fit 中发现新规则 (初始置信度 0.5)"""
    regime_fit = snapshot.get("regime_fit", [])
    existing_ids = {r["id"] for r in memory.get("rules", [])}

    for item in regime_fit:
        name = item.get("strategy", "")
        regime = item.get("regime", "")
        win_rate = item.get("win_rate")
        samples = item.get("samples", 0)

        if win_rate is None or samples < 5:
            continue

        # 发现新的低胜率规则
        if win_rate < 0.25:
            rule_id = f"R_auto_{name}_{regime}_low"
            if rule_id not in existing_ids:
                new_rule = {
                    "id": rule_id,
                    "type": "regime_mismatch_learned",
                    "condition": {
                        "strategy": name, "regime": regime,
                        "metric": "regime_win_rate",
                        "operator": "<", "threshold": 0.25,
                    },
                    "action": "pause_strategy",
                    "confidence": 0.50,
                    "evidence_count": 1,
                    "source": "learned",
                    "description": f"{name}在{regime}行情下胜率<25%(样本{samples})",
                }
                memory.setdefault("rules", []).append(new_rule)
                existing_ids.add(rule_id)
                logger.info("[Agent] 发现新规则: %s", new_rule["description"])


def _prune_rules(memory: dict):
    """清理低置信度规则 (评估次数 >= N 且置信度 < threshold)"""
    min_evals = AGENT_PARAMS.get("rule_prune_min_evals", 10)
    min_conf = AGENT_PARAMS.get("rule_prune_confidence", 0.2)
    rules = memory.get("rules", [])
    kept = []
    for r in rules:
        if r.get("source") == "seed":
            kept.append(r)
            continue
        evals = r.get("evidence_count", 0)
        conf = r.get("confidence", 0)
        if evals >= min_evals and conf < min_conf:
            logger.info("[Agent] 清理低效规则: %s (conf=%.2f, evals=%d)",
                        r.get("id"), conf, evals)
            continue
        kept.append(r)
    memory["rules"] = kept


def update_rule_confidence(rule_id: str, outcome: float, memory: dict):
    """EMA 更新规则置信度: new = 0.8 * old + 0.2 * outcome"""
    for r in memory.get("rules", []):
        if r.get("id") == rule_id:
            old = r.get("confidence", 0.5)
            r["confidence"] = 0.8 * old + 0.2 * outcome
            r["evidence_count"] = r.get("evidence_count", 0) + 1
            break


# ================================================================
#  5b. 多智能体协调 — 事件总线 + 冲突仲裁 + 健康检查
# ================================================================

_SEVERITY_TO_PRIORITY = {
    "critical": 1,  # Priority.CRITICAL
    "warning": 2,   # Priority.URGENT
    "info": 3,      # Priority.NORMAL
}


def _emit_findings_to_bus(findings: list):
    """将 orient() 的 findings 发射到事件总线 (供其他模块观察)"""
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        for f in findings:
            severity = f.get("severity", "info")
            priority_val = _SEVERITY_TO_PRIORITY.get(severity, Priority.NORMAL)
            bus.emit(
                source="agent_brain",
                priority=priority_val,
                event_type=f.get("suggested_action", "log_insight"),
                category="strategy",
                payload={
                    "message": f.get("message", ""),
                    "strategy": f.get("strategy"),
                    "severity": severity,
                },
            )
    except ImportError:
        pass
    except Exception as e:
        logger.debug("发射 findings 到总线异常: %s", e)


def process_bus_events() -> list:
    """消费总线中来自外部模块的事件, 转为标准 finding dict

    跳过 source='agent_brain' 避免与 orient() 重复
    """
    findings = []
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        events = bus.consume()
        for event in events:
            if event.source == "agent_brain":
                continue  # 跳过自己发射的
            # 转为 finding 格式
            severity_map = {
                Priority.CRITICAL: "critical",
                Priority.URGENT: "warning",
                Priority.NORMAL: "info",
                Priority.LOW: "info",
            }
            severity = severity_map.get(event.priority, "info")
            action_map = {
                "drawdown_breach": "escalate_human",
                "correlation_warning": "log_insight",
                "regime_change": "log_insight",
                "smoke_test_failed": "escalate_human",
                "trades_executed": "log_insight",
                "stop_loss_triggered": "escalate_human",
                "job_failed": "escalate_human",
            }
            finding = {
                "type": "bus_event",
                "severity": severity,
                "strategy": event.payload.get("strategy"),
                "message": event.payload.get("message", f"[{event.source}] {event.event_type}"),
                "suggested_action": action_map.get(event.event_type, "log_insight"),
                "confidence": 0.80 if severity == "critical" else 0.60,
                "source": event.source,
                "category": event.category,
            }
            findings.append(finding)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("消费总线事件异常: %s", e)
    return findings


def conflict_resolve(findings: list) -> list:
    """冲突仲裁: 同一策略如有矛盾动作, 按类别权威度仲裁

    权威度: risk(4) > regime(3) > strategy(2) > info(1)
    胜者执行, 败者降级为 log_insight (保留审计)
    """
    try:
        from config import MULTI_AGENT_PARAMS
        authority = MULTI_AGENT_PARAMS.get("conflict_resolution", {}).get(
            "authority", {"risk": 4, "regime": 3, "strategy": 2, "info": 1}
        )
    except (ImportError, AttributeError):
        authority = {"risk": 4, "regime": 3, "strategy": 2, "info": 1}

    # 按策略分组
    strategy_groups = {}
    non_strategy = []
    for f in findings:
        strategy = f.get("strategy")
        if strategy:
            strategy_groups.setdefault(strategy, []).append(f)
        else:
            non_strategy.append(f)

    resolved = list(non_strategy)

    for strategy, group in strategy_groups.items():
        if len(group) <= 1:
            resolved.extend(group)
            continue

        # 检查是否有矛盾: pause vs resume
        pause_findings = [f for f in group if f.get("suggested_action") == "pause_strategy"]
        resume_findings = [f for f in group if f.get("suggested_action") == "resume_strategy"]

        if pause_findings and resume_findings:
            # 有冲突, 按 authority 仲裁
            def get_authority(f):
                cat = f.get("category", "info")
                return authority.get(cat, 1)

            max_pause_auth = max(get_authority(f) for f in pause_findings)
            max_resume_auth = max(get_authority(f) for f in resume_findings)

            if max_pause_auth >= max_resume_auth:
                # pause 胜出
                resolved.extend(pause_findings)
                for f in resume_findings:
                    demoted = dict(f)
                    demoted["suggested_action"] = "log_insight"
                    demoted["_conflict_demoted"] = True
                    demoted["_original_action"] = "resume_strategy"
                    resolved.append(demoted)
                # 其他动作保留
                for f in group:
                    if f not in pause_findings and f not in resume_findings:
                        resolved.append(f)
            else:
                # resume 胜出
                resolved.extend(resume_findings)
                for f in pause_findings:
                    demoted = dict(f)
                    demoted["suggested_action"] = "log_insight"
                    demoted["_conflict_demoted"] = True
                    demoted["_original_action"] = "pause_strategy"
                    resolved.append(demoted)
                for f in group:
                    if f not in pause_findings and f not in resume_findings:
                        resolved.append(f)

            logger.info("[Agent] 冲突仲裁: %s — pause(%d) vs resume(%d), %s 胜出",
                        strategy, max_pause_auth, max_resume_auth,
                        "pause" if max_pause_auth >= max_resume_auth else "resume")
        else:
            resolved.extend(group)

    return resolved


def agent_health_check() -> list:
    """检查注册表中健康度低于阈值的智能体, 生成 findings"""
    findings = []
    try:
        from agent_registry import get_registry
        from config import MULTI_AGENT_PARAMS
        threshold = MULTI_AGENT_PARAMS.get("agent_registry", {}).get(
            "unhealthy_threshold", 0.5)
        registry = get_registry()
        unhealthy = registry.get_unhealthy(threshold=threshold)
        for agent in unhealthy:
            severity = "critical" if agent.health < 0.2 else "warning"
            findings.append({
                "type": "agent_health",
                "severity": severity,
                "strategy": None,
                "message": (f"子智能体 {agent.display_name}({agent.name}) "
                            f"健康度 {agent.health:.0%}, "
                            f"错误 {agent.error_count} 次"
                            + (f" ({agent.last_error})" if agent.last_error else "")),
                "suggested_action": "escalate_human",
                "confidence": 0.80,
                "category": "risk",
            })
    except ImportError:
        pass
    except Exception as e:
        logger.debug("智能体健康检查异常: %s", e)
    return findings


# ================================================================
#  6. 门控 — should_strategy_run()
# ================================================================

def should_strategy_run(strategy_name: str) -> bool:
    """检查智能体是否暂停了该策略 (异常安全: 出错返回 True)"""
    try:
        if not AGENT_PARAMS.get("enabled", True):
            return True
        memory = safe_load(_MEMORY_PATH, default=_default_memory())
        state = memory.get("strategy_states", {}).get(strategy_name, {})
        if state.get("status") == "paused":
            resume_date = state.get("auto_resume_date")
            if resume_date and date.today().isoformat() >= resume_date:
                _action_resume_strategy(strategy_name, memory,
                                        "自动恢复(已过暂停期)")
                _save_memory(memory)
                return True
            logger.info("[Agent] 策略 %s 已暂停 (原因: %s), 跳过运行",
                        strategy_name, state.get("pause_reason", "未知"))
            return False
        return True
    except Exception as e:
        logger.warning("[Agent] 门控检查异常, 默认允许运行: %s", e)
        return True


# ================================================================
#  7. 早报 — generate_morning_briefing()
# ================================================================

def generate_morning_briefing() -> str:
    """生成每日早报 Markdown"""
    memory = _load_memory()
    snapshot = observe()

    lines = ["## 今日交易简报", ""]

    # 大盘状态
    regime_str = "unknown"
    regime_score = 0
    try:
        from smart_trader import detect_market_regime
        regime = detect_market_regime()
        regime_str = regime.get("regime", "unknown")
        regime_score = regime.get("score", 0)
        snapshot["current_regime"] = regime_str
    except Exception as e:
        logger.debug("早报: 大盘检测不可用: %s", e)
    lines.append(f"**大盘:** {regime_str} (评分 {regime_score:.2f})")
    lines.append("")

    # 今日事件
    try:
        from news_event_strategy import get_event_summary
        event_summary = get_event_summary()
        if event_summary:
            lines.append(f"**今日事件:** {event_summary}")
            lines.append("")
    except Exception:
        pass

    # 策略状态
    lines.append("**策略状态:**")
    for name in STRATEGY_NAMES:
        state = memory.get("strategy_states", {}).get(name, {})
        metrics = snapshot.get("strategy_metrics", {}).get(name, {})
        status = state.get("status", "active")
        win_rate = metrics.get("rolling_5d_win_rate")

        if status == "active":
            wr_str = f"近5日胜率 {win_rate:.0%}" if win_rate is not None else "暂无数据"
            lines.append(f"- {name}: 运行中 ({wr_str})")
        else:
            reason = state.get("pause_reason", "")
            resume = state.get("auto_resume_date", "?")
            lines.append(f"- {name}: **暂停** ({reason}, {resume}自动恢复)")
    lines.append("")

    # 子智能体状态
    try:
        from agent_registry import get_registry, register_builtin_agents
        registry = get_registry()
        register_builtin_agents(registry)
        agents = registry.list_agents()
        if agents:
            lines.append("**子智能体状态:**")
            for a in agents:
                health_icon = "OK" if a.health >= 0.5 else "WARN" if a.health >= 0.2 else "ERR"
                lines.append(f"- {a.display_name}: {a.status} ({health_icon} {a.health:.0%})")
            lines.append("")
    except ImportError:
        pass

    # 跨市场信号 (夜间采集结果)
    try:
        from cross_market_strategy import analyze_cross_market
        cm = analyze_cross_market()
        if cm:
            impact_map = {"bullish": "利多▲", "bearish": "利空▼", "neutral": "中性─"}
            lines.append("**跨市场信号:**")
            lines.append(f"- 综合: {cm.get('composite_signal', 0):+.3f} → {impact_map.get(cm.get('a_stock_impact', ''), '?')}")
            lines.append(f"- 美股{cm.get('us_signal', 0):+.3f} | A50{cm.get('a50_signal', 0):+.3f} | 币圈{cm.get('crypto_signal', 0):+.3f}")
            if cm.get("suggestion"):
                lines.append(f"- {cm['suggestion']}")
            lines.append("")
    except Exception:
        pass

    # 系统性能
    try:
        from watchdog import safe_load
        hb = safe_load("heartbeat.json", default={})
        strats = hb.get("strategy_status", {})
        if strats:
            lines.append("**策略耗时:**")
            for sname, sinfo in sorted(strats.items(), key=lambda x: x[1].get("duration_sec", 0), reverse=True):
                dur = sinfo.get("duration_sec", 0)
                status_icon = "OK" if sinfo.get("status") == "success" else "FAIL"
                if dur > 600:
                    lines.append(f"- {sname}: {dur:.0f}s ({dur/60:.1f}分) [{status_icon}] **慢**")
                elif dur > 120:
                    lines.append(f"- {sname}: {dur:.0f}s [{status_icon}]")
                else:
                    lines.append(f"- {sname}: {dur:.0f}s [{status_icon}]")
            lines.append("")
    except Exception:
        pass

    # 待关注
    findings = orient(snapshot, memory)
    warnings = [f for f in findings if f.get("severity") in ("warning", "critical")]
    if warnings:
        lines.append("**待关注:**")
        for w in warnings[:3]:
            sev = w.get("severity", "info")
            msg = w.get("message", "")
            lines.append(f"- [{sev}] {msg}")
    else:
        lines.append("**待关注:** 暂无异常")

    raw = "\n".join(lines)

    # LLM 增强早报
    try:
        from llm_advisor import enhance_morning_briefing
        enhanced = enhance_morning_briefing(raw, snapshot, memory)
        if enhanced:
            return enhanced
    except Exception:
        pass

    return raw


def push_morning_briefing():
    """推送早报到微信"""
    if not AGENT_PARAMS.get("morning_briefing", True):
        return
    try:
        briefing = generate_morning_briefing()
        from notifier import notify_wechat_raw
        now_str = datetime.now().strftime("%H:%M")
        notify_wechat_raw(f"[{now_str}] 今日交易简报", briefing)
        logger.info("[Agent] 早报已推送")
    except Exception as e:
        logger.warning("[Agent] 早报推送失败: %s", e)


# ================================================================
#  8. OODA 主循环
# ================================================================

def run_agent_cycle() -> str:
    """运行完整 OODA 循环 (多智能体协调版), 返回摘要"""
    logger.info("[Agent] 开始 OODA 循环")
    memory = _load_memory()

    # 初始化多智能体基础设施
    try:
        from agent_registry import get_registry, register_builtin_agents
        registry = get_registry()
        register_builtin_agents(registry)
        registry.report_run("brain", success=True)
    except ImportError:
        registry = None

    # Observe
    snapshot = observe()

    # 获取当前行情 → 行情雷达
    try:
        from smart_trader import detect_market_regime
        regime = detect_market_regime()
        snapshot["current_regime"] = regime.get("regime", "neutral")
        if registry:
            registry.report_run("market_radar", success=True)
    except Exception as e:
        if registry:
            registry.report_run("market_radar", success=False, error=str(e))

    # Orient (10个检测器 + emit 到总线)
    findings = orient(snapshot, memory)

    # 消费总线事件 (来自外部模块)
    bus_findings = process_bus_events()
    if bus_findings:
        logger.info("[Agent] 总线事件: %d 个", len(bus_findings))
        findings.extend(bus_findings)

    # 智能体健康检查 + 风控督察巡检
    health_findings = agent_health_check()
    if health_findings:
        findings.extend(health_findings)

    # 风控督察: 组合层风控检查
    try:
        from portfolio_risk import check_portfolio_risk
        risk_result = check_portfolio_risk()
        risk_findings = risk_result.get("findings", []) if risk_result else []
        if risk_findings:
            findings.extend(risk_findings)
            logger.info("[Agent] 风控督察发现 %d 个预警", len(risk_findings))
        if registry:
            registry.report_run("risk_inspector", success=True)
    except Exception as e:
        if registry:
            registry.report_run("risk_inspector", success=False, error=str(e))

    # 执行裁判: 纸盘持仓监控
    try:
        from paper_trader import check_exits, load_positions
        positions = load_positions()
        if positions:
            exits = check_exits()
            if exits:
                for ex in exits:
                    findings.append({
                        "type": "execution",
                        "severity": "info",
                        "strategy": ex.get("strategy"),
                        "message": (f"纸盘平仓 {ex.get('code','')} {ex.get('name','')}"
                                    f" {ex.get('reason','')} 盈亏{ex.get('pnl_pct',0):.1f}%"),
                        "suggested_action": "log_insight",
                        "confidence": 0.90,
                        "category": "strategy",
                    })
        if registry:
            registry.report_run("execution_judge", success=True)
    except Exception as e:
        if registry:
            registry.report_run("execution_judge", success=False, error=str(e))

    # 冲突仲裁
    findings = conflict_resolve(findings)

    # LLM 深度分析 (L2: 找根因/发现关联/补充遗漏)
    try:
        from llm_advisor import llm_deep_orient
        new_findings = llm_deep_orient(findings, snapshot, memory)
        if new_findings:
            findings.extend(new_findings)
            logger.info("[Agent] LLM深度分析发现 %d 个新信号", len(new_findings))
    except Exception:
        pass

    # LLM 对 medium-confidence findings 提供建议 (L1)
    try:
        from llm_advisor import advise_on_findings
        findings = advise_on_findings(findings)
    except Exception:
        pass

    # LLM 辅助决策 (L2: 综合判断是否执行)
    try:
        from llm_advisor import llm_smart_decide
        findings = llm_smart_decide(findings, memory)
    except Exception:
        pass

    # Decide
    decisions = decide(findings, memory)

    # Act
    act(decisions, memory)

    # 自主实验 → 选股研究员
    try:
        from experiment_lab import run_auto_experiment_cycle
        exp_results = run_auto_experiment_cycle(findings, memory)
        for er in exp_results:
            _action_log_insight(memory, {
                "severity": "info",
                "message": (f"实验 {er.get('experiment_id', '?')}: "
                            f"{er.get('hypothesis', '')} → {er.get('conclusion', '?')} "
                            f"({'已采纳' if er.get('adopted') else '未采纳'})"),
                "suggested_action": "log_insight",
            })
        if registry:
            registry.report_run("factor_researcher", success=True)
    except Exception as e:
        if registry:
            registry.report_run("factor_researcher", success=False, error=str(e))

    # Learn
    learn(snapshot, memory)

    # 系统自愈: 运行健康检查
    try:
        from self_healer import auto_heal
        heal_result = auto_heal()
        if heal_result:
            repairs = heal_result if isinstance(heal_result, list) else []
            for repair in repairs:
                msg = repair if isinstance(repair, str) else str(repair)
                _action_log_insight(memory, {
                    "severity": "info",
                    "message": f"[自愈] {msg}",
                    "suggested_action": "log_insight",
                })
        if registry:
            registry.report_run("healer", success=True)
    except Exception as e:
        if registry:
            registry.report_run("healer", success=False, error=str(e))

    # LLM 认知提取 (L2: 沉淀经验)
    try:
        from llm_advisor import llm_extract_insights
        insights = llm_extract_insights(findings, decisions, snapshot, memory)
        if insights:
            for ins in insights:
                _action_log_insight(memory, {
                    "severity": "info",
                    "message": (f"[认知] {ins.get('pattern', '')}: "
                                f"{ins.get('lesson', '')}"),
                    "suggested_action": "log_insight",
                })
            logger.info("[Agent] LLM提取 %d 个认知洞察", len(insights))
    except Exception:
        pass

    # 更新 meta
    memory["meta"]["last_cycle"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    memory["meta"]["total_cycles"] = memory["meta"].get("total_cycles", 0) + 1

    _save_memory(memory)

    # 持久化事件总线 + 注册表
    try:
        from event_bus import get_event_bus
        get_event_bus().persist()
    except Exception:
        pass
    if registry:
        try:
            registry.persist()
        except Exception:
            pass

    # 生成摘要
    summary_lines = [f"OODA循环完成 (第{memory['meta']['total_cycles']}次)"]
    n_findings = len(findings)
    n_actions = sum(1 for d in decisions if d.get("execute"))
    n_bus = len(bus_findings) if bus_findings else 0
    summary_lines.append(f"  发现 {n_findings} 个信号 (含总线{n_bus}), 执行 {n_actions} 个动作")

    for d in decisions:
        if d.get("execute"):
            f = d.get("finding", {})
            summary_lines.append(f"  - [{f.get('severity')}] {f.get('message', '')}"
                                 f" → {d.get('action')}")

    summary = "\n".join(summary_lines)
    logger.info(summary)
    return summary


def generate_evening_summary() -> str:
    """生成晚间摘要 (融入 OODA 循环后)"""
    memory = _load_memory()
    today_str = date.today().isoformat()

    # 收集今日洞察
    today_insights = [i for i in memory.get("insights", [])
                      if i.get("time", "").startswith(today_str)]

    if not today_insights:
        today_insights = []

    lines = ["## Agent 今日洞察", ""]
    for i in today_insights:
        sev = i.get("severity", "info")
        msg = i.get("message", "")
        action = i.get("action_taken", "")
        lines.append(f"- [{sev}] {msg} (动作: {action})")

    # 跨市场收盘总结
    try:
        from cross_market_strategy import analyze_cross_market
        cm = analyze_cross_market()
        if cm:
            impact_map = {"bullish": "利多▲", "bearish": "利空▼", "neutral": "中性─"}
            lines.append("")
            lines.append("**跨市场收盘:**")
            lines.append(f"- 综合{cm.get('composite_signal', 0):+.3f} → {impact_map.get(cm.get('a_stock_impact', ''), '?')}")
            lines.append(f"- 美股{cm.get('us_signal', 0):+.3f} | A50{cm.get('a50_signal', 0):+.3f} | 币圈{cm.get('crypto_signal', 0):+.3f}")
    except Exception:
        pass

    # VaR 风控摘要
    try:
        from var_risk import get_latest_risk_rating, safe_load as _vl, _VAR_RESULTS_PATH
        history = _vl(_VAR_RESULTS_PATH, default=[])
        if history:
            latest = history[-1]
            rating = latest.get("risk_rating", "unknown")
            portfolio = latest.get("portfolio", {})
            rating_map = {"low": "🟢低", "medium": "🟡中", "high": "🔴高"}
            lines.append("")
            lines.append(f"**风控VaR:** {rating_map.get(rating, '?')}"
                         f" | VaR(95%)={portfolio.get('hist_var_95', 0):+.4f}%"
                         f" | CVaR(99%)={portfolio.get('hist_cvar_99', 0):+.4f}%"
                         f" | 年化波动={portfolio.get('annual_vol', 0):.1f}%")
    except Exception:
        pass

    # 纸盘模拟交易摘要
    try:
        from paper_trader import calc_statistics, get_holdings_summary
        stats = calc_statistics(days=7)
        if stats.get("total", 0) > 0:
            holdings = get_holdings_summary()
            lines.append("")
            lines.append(f"**纸盘模拟(7天):** {stats['total']}笔"
                         f" | 胜率{stats['win_rate']}%"
                         f" | 收益{stats['total_pnl']:+.2f}%"
                         f" | 持仓{holdings.get('count', 0)}笔")
    except Exception:
        pass

    # 信号追踪摘要
    try:
        from signal_tracker import get_stats
        sig_stats = get_stats(days=7)
        overall = sig_stats.get("overall", {})
        if sig_stats.get("total", 0) > 0:
            t1wr = overall.get("t1_win_rate")
            t3wr = overall.get("t3_win_rate")
            avg_t1 = overall.get("avg_t1")
            parts = [f"**信号追踪(7天):** {sig_stats['total']}条"]
            if t1wr is not None:
                parts.append(f"T+1胜率{t1wr}%")
            if avg_t1 is not None:
                parts.append(f"T+1均收{avg_t1:+.2f}%")
            if t3wr is not None:
                parts.append(f"T+3胜率{t3wr}%")
            lines.append("")
            lines.append(" | ".join(parts))
    except Exception:
        pass

    if not lines or lines == ["## Agent 今日洞察", ""]:
        return ""

    raw = "\n".join(lines)

    # LLM 增强晚报
    try:
        from llm_advisor import enhance_evening_summary
        enhanced = enhance_evening_summary(raw, memory=memory)
        if enhanced:
            return enhanced
    except Exception:
        pass

    return raw


# ================================================================
#  9. 夜班引擎 (22:30 - 06:30, 多任务调度)
# ================================================================

_NIGHT_LOG_PATH = os.path.join(_BASE_DIR, "night_shift_log.json")


def run_night_shift() -> str:
    """22:30+ 夜班: 多任务全流程

    任务链: 绩效考核 → LLM复盘 → 批量回测 → 因子实验 → 策略进化
            → OODA回放 → 晨报准备

    每个子任务独立 try/except, 一个失败不影响其他.
    进度实时写入 night_shift_log.json, 最终推送汇总报告.

    Returns:
        夜班汇总报告 Markdown
    """
    start_time = datetime.now()
    logger.info("[夜班] === 夜班开始 %s ===", start_time.strftime("%H:%M"))

    log = {
        "date": start_time.strftime("%Y-%m-%d"),
        "start": start_time.strftime("%H:%M:%S"),
        "tasks": {},
        "status": "running",
    }
    _save_night_log(log)

    memory = _load_memory()
    results = {}  # {task_name: {status, duration, output}}

    # ---- Task 1: 绩效考核 ----
    results["performance_review"] = _night_task(
        "绩效考核", log, _night_performance_review)

    # ---- Task 2: LLM 深度分析 ----
    review = results["performance_review"].get("data", {})
    results["llm_analysis"] = _night_task(
        "LLM深度复盘", log,
        lambda: _night_llm_analysis(memory, review))

    # ---- Task 3: 批量回测 ----
    results["batch_backtest"] = _night_task(
        "批量回测验证", log, _night_batch_backtest)

    # ---- Task 3b: Walk-Forward 过拟合检测 ----
    results["walk_forward"] = _night_task(
        "Walk-Forward检测", log, _night_walk_forward)

    # ---- Task 3c: ML 模型训练 ----
    results["ml_train"] = _night_task(
        "ML模型训练", log, _night_ml_train)

    # ---- Task 4: 因子发现实验 ----
    results["factor_discovery"] = _night_task(
        "因子发现实验", log,
        lambda: _night_factor_discovery(memory))

    # ---- Task 5: 策略参数进化 ----
    results["strategy_evolution"] = _night_task(
        "策略参数进化", log, _night_strategy_evolution)

    # ---- Task 6: OODA 历史回放 ----
    results["ooda_replay"] = _night_task(
        "OODA历史回放", log,
        lambda: _night_ooda_replay(memory))

    # ---- Task 7: 币圈趋势扫描 ----
    results["crypto_scan"] = _night_task(
        "币圈趋势扫描", log, _night_crypto_scan)

    # ---- Task 8: 美股收盘分析 ----
    results["us_stock_analysis"] = _night_task(
        "美股收盘分析", log, _night_us_stock_analysis)

    # ---- Task 9: 跨市场信号推演 ----
    results["cross_market_signal"] = _night_task(
        "跨市场信号推演", log, _night_cross_market)

    # ---- Task 10: 开盘作战计划 ----
    results["morning_prep"] = _night_task(
        "开盘作战计划", log, _night_morning_prep)

    # ---- 汇总 ----
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    log["end"] = end_time.strftime("%H:%M:%S")
    log["duration_min"] = round(duration / 60, 1)
    log["status"] = "completed"
    _save_night_log(log)

    # 生成汇总报告
    report = _format_night_report(results, log)

    # 保存 insight
    n_ok = sum(1 for r in results.values() if r.get("status") == "ok")
    n_fail = sum(1 for r in results.values() if r.get("status") == "error")
    _action_log_insight(memory, {
        "severity": "info",
        "message": f"[夜班] 完成 {n_ok}/{len(results)} 任务, 耗时 {log['duration_min']}分钟",
        "suggested_action": "log_insight",
    })
    memory["meta"]["last_night_shift"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
    _save_memory(memory)

    # 推送微信
    try:
        from notifier import notify_wechat_raw
        now_str = end_time.strftime("%H:%M")
        notify_wechat_raw(f"[{now_str}] 夜班完工报告", report)
        logger.info("[夜班] 报告已推送")
    except Exception as e:
        logger.warning("[夜班] 推送失败: %s", e)

    logger.info("[夜班] === 夜班结束, 耗时 %.1f 分钟 ===", duration / 60)
    return report


_NIGHT_TASK_TIMEOUT = {
    "绩效考核": 120, "LLM深度复盘": 180, "批量回测验证": 600,
    "Walk-Forward检测": 600, "ML模型训练": 300, "因子发现实验": 300, "策略参数进化": 300,
    "OODA历史回放": 120, "币圈趋势扫描": 180, "美股收盘分析": 180,
    "跨市场信号推演": 120, "开盘作战计划": 120,
}


def _night_task(name: str, log: dict, func, retry: int = 2) -> dict:
    """执行一个夜班子任务, 真正超时强杀 + 失败重试 + 心跳

    改进:
      1. 用 ThreadPoolExecutor 做硬超时, 卡死的任务会被放弃
      2. 失败自动重试 2 次 (退避递增: 10s/30s/60s)
      3. 执行中写心跳, 让 watchdog 知道夜班还活着
      4. 代码 bug (TypeError/ValueError/KeyError 等) 不重试, 立即失败
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    # 代码 bug 类错误, 重试也不会好, 直接放弃
    _NO_RETRY_ERRORS = (TypeError, ValueError, KeyError, AttributeError,
                        ImportError, SyntaxError, NameError, IndexError)
    # 退避间隔 (秒): 第1次失败后等10s, 第2次30s, 第3次60s...
    _BACKOFF = [10, 30, 60, 120]

    timeout_sec = _NIGHT_TASK_TIMEOUT.get(name, 300)
    hard_timeout = timeout_sec + 60  # 硬超时 = 阈值 + 60s 缓冲

    for attempt in range(1, retry + 2):  # retry=2 → 最多跑 3 次
        logger.info("[夜班] 开始: %s (第%d次)", name, attempt)
        log["tasks"][name] = {
            "status": "running",
            "start": datetime.now().strftime("%H:%M:%S"),
            "attempt": attempt,
        }
        _save_night_log(log)

        # 写心跳: 让 watchdog 知道夜班在干活
        _night_heartbeat(name)

        t0 = _time.time()
        try:
            # 硬超时: 用线程池 submit + timeout
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(func)
                result = future.result(timeout=hard_timeout)

            elapsed = _time.time() - t0
            entry = {
                "status": "ok",
                "duration_sec": round(elapsed, 1),
                "attempt": attempt,
                "data": result if isinstance(result, dict) else {},
                "output": str(result)[:500] if result else "",
            }
            logger.info("[夜班] 完成: %s (%.1fs, 第%d次)", name, elapsed, attempt)

            # 超时告警 (完成但慢)
            if elapsed > timeout_sec:
                entry["timeout_warning"] = True
                logger.warning("[夜班] %s 耗时 %.0fs, 超过阈值 %ds",
                               name, elapsed, timeout_sec)
                try:
                    from notifier import notify_wechat_raw
                    notify_wechat_raw(
                        "夜班任务超时告警",
                        f"任务: {name}\n耗时: {elapsed:.0f}s (阈值 {timeout_sec}s)\n"
                        f"状态: 已完成但耗时过长",
                    )
                except Exception:
                    pass

            log["tasks"][name] = entry
            _save_night_log(log)
            return entry

        except FutureTimeout:
            elapsed = _time.time() - t0
            err_msg = f"硬超时 {hard_timeout}s, 任务被强杀"
            logger.error("[夜班] %s %s (第%d次)", name, err_msg, attempt)
            entry = {
                "status": "timeout",
                "duration_sec": round(elapsed, 1),
                "attempt": attempt,
                "error": err_msg,
            }
            # 超时推送微信
            try:
                from notifier import notify_wechat_raw
                notify_wechat_raw(
                    "夜班任务卡死",
                    f"任务: {name}\n状态: 超时被强杀 ({hard_timeout}s)\n"
                    f"第 {attempt} 次尝试",
                )
            except Exception:
                pass

        except Exception as e:
            elapsed = _time.time() - t0
            entry = {
                "status": "error",
                "duration_sec": round(elapsed, 1),
                "attempt": attempt,
                "error": f"{type(e).__name__}: {e}",
            }
            logger.warning("[夜班] 失败: %s — %s (第%d次)", name, e, attempt)

            # 代码 bug 不重试, 立即退出循环
            if isinstance(e, _NO_RETRY_ERRORS):
                logger.error("[夜班] %s 是代码错误, 不重试", name)
                break

        # 失败了, 如果还有重试机会
        if attempt <= retry:
            backoff = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
            logger.info("[夜班] %s 将在 %ds 后重试 (第%d→%d次)...",
                        name, backoff, attempt, attempt + 1)
            _time.sleep(backoff)

    # 所有尝试都失败
    log["tasks"][name] = entry
    _save_night_log(log)
    return entry


def _night_heartbeat(task_name: str):
    """夜班心跳: 写入 heartbeat.json, 让 watchdog 知道夜班在活动"""
    try:
        from watchdog import update_heartbeat
        update_heartbeat()
    except Exception:
        pass
    try:
        hb = safe_load(_NIGHT_LOG_PATH, default={})
        hb["_heartbeat"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hb["_current_task"] = task_name
        safe_save(_NIGHT_LOG_PATH, hb)
    except Exception:
        pass


def _save_night_log(log: dict):
    """保存夜班进度"""
    try:
        safe_save(_NIGHT_LOG_PATH, log)
    except Exception:
        pass


# ---- 夜班子任务实现 ----

def _night_performance_review() -> dict:
    """子任务: 绩效考核"""
    from agent_registry import run_performance_review
    return run_performance_review()


def _night_llm_analysis(memory: dict, review: dict) -> str:
    """子任务: LLM 深度分析"""
    try:
        from llm_advisor import llm_night_analysis
        report = llm_night_analysis(memory, performance_review=review)
        return report or ""
    except ImportError:
        return ""


def _night_batch_backtest() -> dict:
    """子任务: 批量回测验证"""
    try:
        from batch_backtest import run_batch_backtest
        return run_batch_backtest()
    except ImportError:
        logger.debug("[夜班] batch_backtest 模块尚未构建")
        return {"status": "not_implemented"}


def _night_walk_forward() -> dict:
    """子任务: Walk-Forward 过拟合检测 (核心策略)"""
    try:
        from walk_forward import walk_forward_test
        # 只测核心3策略 (全量太慢)
        core_strategies = ["breakout", "auction", "afternoon"]
        results = {}
        for s in core_strategies:
            try:
                r = walk_forward_test(s, n_windows=3, train_days=90, test_days=20)
                risk = r.get("summary", {}).get("overfitting_risk", "unknown")
                results[s] = risk
                if risk == "high":
                    logger.warning("[WF] %s 过拟合风险高!", s)
            except Exception as e:
                logger.debug("[WF] %s 失败: %s", s, e)
                results[s] = "error"
        return {"strategies_checked": len(results), "results": results}
    except ImportError:
        return {"status": "not_implemented"}


def _night_ml_train() -> dict:
    """子任务: ML 因子模型训练 + Walk-Forward 评估"""
    try:
        from ml_factor_model import train_model, evaluate_walk_forward
        # 训练全策略混合模型
        train_result = train_model(lookback_days=180)
        if "error" in train_result:
            return {"status": "skip", "reason": train_result["error"]}

        # Walk-Forward 评估
        eval_result = evaluate_walk_forward(lookback_days=180)
        useful = eval_result.get("summary", {}).get("model_useful", False)

        return {
            "training_samples": train_result.get("training_samples", 0),
            "features": len(train_result.get("features", [])),
            "model_useful": useful,
            "oos_direction_acc": eval_result.get("summary", {}).get(
                "avg_oos_direction_acc", 0),
        }
    except ImportError:
        return {"status": "not_implemented"}


def _night_factor_discovery(memory: dict) -> dict:
    """子任务: 因子发现实验 (复用 experiment_lab)"""
    try:
        from experiment_lab import run_auto_experiment_cycle
        findings = []  # 无实时 findings, 用空列表触发主动扫描
        results = run_auto_experiment_cycle(findings, memory)
        return {
            "experiments_run": len(results),
            "adopted": sum(1 for r in results if r.get("adopted")),
        }
    except ImportError:
        return {"status": "not_implemented"}


def _night_strategy_evolution() -> dict:
    """子任务: 策略参数进化 (learning_engine + auto_optimizer + 回测自动采纳)"""
    result = {"learning": False, "optimized": False, "adopted": []}

    # Step 1: 学习引擎 — 信号权重调整
    try:
        from learning_engine import run_learning_cycle
        run_learning_cycle()
        result["learning"] = True
    except Exception as e:
        logger.debug("[夜班] learning_engine: %s", e)

    # Step 2: 自动采纳回测最优参数
    try:
        from learning_engine import auto_adopt_backtest_results
        adopted = auto_adopt_backtest_results()
        result["adopted"] = adopted
        if adopted:
            logger.info("[夜班] 自动采纳 %d 个策略的最优参数", len(adopted))
    except Exception as e:
        logger.debug("[夜班] auto_adopt: %s", e)

    # Step 3: 日常优化器
    try:
        from auto_optimizer import run_daily_optimization
        run_daily_optimization()
        result["optimized"] = True
    except Exception as e:
        logger.debug("[夜班] auto_optimizer: %s", e)

    return result


def _night_ooda_replay(memory: dict) -> dict:
    """子任务: OODA 历史回放 + 自动规则发现"""
    # 加载历史 scorecard 数据, 回放 orient + decide
    try:
        from scorecard import calc_cumulative_stats
        stats = calc_cumulative_stats(30)
    except Exception:
        stats = {}

    by_strategy = stats.get("by_strategy", {})
    replay_count = 0
    new_rules = 0

    for strategy_name, s in by_strategy.items():
        win_rate = s.get("win_rate", 50)
        avg_return = s.get("avg_net_return", 0)

        # 模拟: 如果胜率低, 生成"历史观察到的"finding
        if win_rate < 40:
            snapshot = {"strategy_metrics": {strategy_name: {
                "rolling_5d_win_rate": win_rate / 100,
                "avg_return": avg_return,
            }}}
            learn(snapshot, memory)
            replay_count += 1

        # 模拟: 高收益策略, 强化规则
        if avg_return > 1.0 and win_rate > 55:
            snapshot = {"strategy_metrics": {strategy_name: {
                "rolling_5d_win_rate": win_rate / 100,
                "avg_return": avg_return,
            }}}
            learn(snapshot, memory)
            replay_count += 1

    # 自动规则发现: 从历史 strategy×regime 交叉分析中挖掘新规则
    try:
        from learning_engine import discover_rules_from_history
        discovered = discover_rules_from_history(memory)
        new_rules = len(discovered)
        if discovered:
            logger.info("[夜班] OODA回放发现 %d 条新规则", new_rules)
    except Exception as e:
        logger.debug("[夜班] 规则发现: %s", e)

    _save_memory(memory)
    return {"replay_count": replay_count, "new_rules": new_rules}


def _night_crypto_scan() -> dict:
    """子任务: 币圈趋势扫描"""
    from crypto_strategy import run_crypto_scan
    results = run_crypto_scan(top_n=5)
    return {
        "count": len(results),
        "top": [f"{r['symbol']} {r['direction']} {r['score']:.3f}" for r in results[:3]],
    }


def _night_us_stock_analysis() -> dict:
    """子任务: 美股收盘分析"""
    from us_stock_strategy import run_us_stock_scan
    results = run_us_stock_scan(top_n=5)
    return {
        "count": len(results),
        "top": [f"{r['symbol']} {r['direction']} {r['score']:.3f}" for r in results[:3]],
    }


def _night_cross_market() -> dict:
    """子任务: 跨市场信号推演"""
    from cross_market_strategy import analyze_cross_market
    result = analyze_cross_market()
    return {
        "composite_signal": result.get("composite_signal", 0),
        "a_stock_impact": result.get("a_stock_impact", "neutral"),
        "suggestion": result.get("suggestion", ""),
    }


def _night_morning_prep() -> dict:
    """子任务: 开盘作战计划"""
    from morning_prep import generate_morning_plan
    plan = generate_morning_plan()
    return {
        "risk_level": plan.get("risk_level", "unknown"),
        "risk_factors": plan.get("risk_factors", 0),
    }


def _format_night_report(results: dict, log: dict) -> str:
    """生成夜班汇总报告"""
    lines = [f"## 夜班完工报告 ({log.get('date', '')})", ""]
    lines.append(f"**时间**: {log.get('start', '')} → {log.get('end', '')} "
                 f"(共 {log.get('duration_min', 0)} 分钟)")

    n_ok = sum(1 for r in results.values() if r.get("status") == "ok")
    n_err = sum(1 for r in results.values() if r.get("status") == "error")
    n_skip = sum(1 for r in results.values()
                 if r.get("data", {}).get("status") == "not_implemented")
    lines.append(f"**完成**: {n_ok} 成功 / {n_err} 失败 / {n_skip} 待建")
    lines.append("")

    status_icon = {"ok": "done", "error": "FAIL"}
    for name, r in results.items():
        status = r.get("status", "?")
        icon = status_icon.get(status, "?")
        dur = r.get("duration_sec", 0)
        lines.append(f"- [{icon}] **{name}** ({dur:.0f}s)")
        if status == "error":
            lines.append(f"  错误: {r.get('error', '')}")
        elif r.get("output"):
            # 只显示前100字
            out = r["output"][:100]
            if out:
                lines.append(f"  {out}")

    # 嵌入 LLM 分析报告 (如果有)
    llm_output = results.get("llm_analysis", {}).get("output", "")
    if llm_output and len(llm_output) > 10:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(llm_output)

    # 嵌入绩效考核
    review_data = results.get("performance_review", {}).get("data", {})
    if review_data and review_data.get("agents"):
        lines.append("")
        lines.append(f"**绩效考核**: {review_data.get('summary', '')}")
        for name, r in review_data.get("agents", {}).items():
            lines.append(f"- {r.get('display_name', name)}: "
                         f"{r.get('grade', '?')} ({r.get('score', 0):.0f}分)")

    return "\n".join(lines)


# ================================================================
#  CLI
# ================================================================

def _cli_status():
    """显示策略状态 + 活跃规则"""
    memory = _load_memory()
    print("\n=== 策略状态 ===")
    for name in STRATEGY_NAMES:
        state = memory.get("strategy_states", {}).get(name, {})
        status = state.get("status", "active")
        consec_l = state.get("consecutive_losses", 0)
        consec_w = state.get("consecutive_wins", 0)
        last5 = state.get("last_5_results", [])
        print(f"  {name}: {status}")
        print(f"    连亏={consec_l} 连赢={consec_w} 近5次={last5}")
        if status == "paused":
            print(f"    暂停原因: {state.get('pause_reason', '')}")
            print(f"    自动恢复: {state.get('auto_resume_date', '')}")

    print(f"\n=== 活跃规则 ({len(memory.get('rules', []))}) ===")
    for r in memory.get("rules", []):
        print(f"  [{r.get('id')}] {r.get('description', '')}"
              f"  置信度={r.get('confidence', 0):.2f}"
              f"  评估={r.get('evidence_count', 0)}次")

    meta = memory.get("meta", {})
    print(f"\n  上次循环: {meta.get('last_cycle', '从未')}")
    print(f"  总循环次数: {meta.get('total_cycles', 0)}")


def _cli_rules():
    """显示所有规则"""
    memory = _load_memory()
    rules = memory.get("rules", [])
    print(f"\n=== 规则列表 ({len(rules)}) ===")
    for r in rules:
        print(f"\n  [{r.get('id')}] {r.get('description', '')}")
        print(f"    类型: {r.get('type', '')}")
        print(f"    动作: {r.get('action', '')}")
        print(f"    置信度: {r.get('confidence', 0):.2f}")
        print(f"    来源: {r.get('source', '')}")
        print(f"    评估次数: {r.get('evidence_count', 0)}")


def _cli_insights():
    """显示历史洞察"""
    memory = _load_memory()
    insights = memory.get("insights", [])
    print(f"\n=== 历史洞察 (最近20条, 共{len(insights)}条) ===")
    for i in insights[-20:]:
        print(f"  [{i.get('severity')}] {i.get('time', '')} - {i.get('message', '')}")
        print(f"    动作: {i.get('action_taken', '')}")


def _cli_agents():
    """显示注册智能体"""
    try:
        from agent_registry import get_registry, register_builtin_agents
        registry = get_registry()
        register_builtin_agents(registry)
        agents = registry.list_agents()
        print(f"\n=== 注册智能体 ({len(agents)}) ===")
        for a in agents:
            health_bar = "+" * int(a.health * 10) + "-" * (10 - int(a.health * 10))
            print(f"  {a.display_name} ({a.name})")
            print(f"    模块: {a.module} | 状态: {a.status} | 健康: [{health_bar}] {a.health:.0%}")
            if a.last_run:
                print(f"    上次运行: {a.last_run[:19]}")
            if a.last_error:
                print(f"    最近错误: {a.last_error}")
    except ImportError:
        print("agent_registry 模块不可用")


def _cli_events():
    """显示事件总线状态"""
    try:
        from event_bus import get_event_bus, Priority
        bus = get_event_bus()
        s = bus.stats()
        print(f"\n=== 事件总线 ===")
        print(f"  总事件: {s['total_events']}")
        print(f"  未消费: {s['unconsumed']}")
        print(f"  累计发射: {s['total_emitted']}")
        print(f"  累计消费: {s['total_consumed']}")
        print(f"  去重拦截: {s['total_deduped']}")
        print(f"  按优先级: {s['by_priority']}")
        # 展示最近未消费事件
        events = bus.peek()
        if events:
            print(f"\n  最近未消费事件 (前10):")
            for e in events[:10]:
                pname = Priority(e.priority).name if e.priority in (1, 2, 3, 4) else str(e.priority)
                print(f"    [{pname}] {e.source}.{e.event_type} ({e.category}) {e.timestamp[:19]}")
    except ImportError:
        print("event_bus 模块不可用")


def _cli_pause(strategy_keyword: str):
    """手动暂停策略"""
    memory = _load_memory()
    matched = [n for n in STRATEGY_NAMES if strategy_keyword in n]
    if not matched:
        print(f"未找到匹配的策略: {strategy_keyword}")
        print(f"可用策略: {', '.join(STRATEGY_NAMES)}")
        return
    name = matched[0]
    _action_pause_strategy(name, memory, "手动暂停")
    _save_memory(memory)
    print(f"已暂停: {name}")


def _cli_resume(strategy_keyword: str):
    """手动恢复策略"""
    memory = _load_memory()
    matched = [n for n in STRATEGY_NAMES if strategy_keyword in n]
    if not matched:
        print(f"未找到匹配的策略: {strategy_keyword}")
        print(f"可用策略: {', '.join(STRATEGY_NAMES)}")
        return
    name = matched[0]
    _action_resume_strategy(name, memory, "手动恢复")
    _save_memory(memory)
    print(f"已恢复: {name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    arg = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "status":
        _cli_status()
    elif cmd == "rules":
        _cli_rules()
    elif cmd == "insights":
        _cli_insights()
    elif cmd == "agents":
        _cli_agents()
    elif cmd == "events":
        _cli_events()
    elif cmd == "pause" and arg:
        _cli_pause(arg)
    elif cmd == "resume" and arg:
        _cli_resume(arg)
    elif cmd in ("cycle", "run"):
        summary = run_agent_cycle()
        print(summary)
    elif cmd == "morning":
        push_morning_briefing()
    elif cmd == "night":
        report = run_night_shift()
        if report:
            print(report)
        else:
            print("[夜班] LLM 不可用或无分析结果")
    elif cmd == "chat" and arg:
        try:
            from llm_advisor import chat
            print(chat(arg))
        except ImportError:
            print("[LLM] llm_advisor 模块不可用")
    else:
        print("Agent Brain CLI")
        print("用法:")
        print("  python3 agent_brain.py              # 运行OODA循环")
        print("  python3 agent_brain.py status        # 查看策略状态")
        print("  python3 agent_brain.py pause 放量突破  # 手动暂停")
        print("  python3 agent_brain.py resume 放量突破 # 手动恢复")
        print("  python3 agent_brain.py rules         # 查看所有规则")
        print("  python3 agent_brain.py insights      # 查看历史洞察")
        print("  python3 agent_brain.py agents        # 查看注册智能体")
        print("  python3 agent_brain.py events        # 查看事件总线")
        print("  python3 agent_brain.py morning       # 推送早报")
        print("  python3 agent_brain.py night         # 手动运行夜班分析")
        print('  python3 agent_brain.py chat "问题"    # LLM 对话')
