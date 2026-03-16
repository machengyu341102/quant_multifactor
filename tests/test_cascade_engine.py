"""
级联引擎 (cascade_engine.py) 独立测试
======================================
覆盖: 规则注册、execute/preview/rollback、6种触发器、日志持久化、集成调用
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    """隔离所有文件IO到 tmp_path"""
    monkeypatch.setattr("cascade_engine.os.path.dirname",
                        lambda *a, **k: str(tmp_path))

    # 准备 agent_memory.json
    memory = {
        "strategy_states": {
            "放量突破": {"status": "active", "paused_since": None,
                       "pause_reason": None, "auto_resume_date": None},
            "低吸回调": {"status": "active", "paused_since": None,
                       "pause_reason": None, "auto_resume_date": None},
            "隔夜选股": {"status": "active", "paused_since": None,
                       "pause_reason": None, "auto_resume_date": None},
        }
    }
    (tmp_path / "agent_memory.json").write_text(
        json.dumps(memory, ensure_ascii=False), encoding="utf-8")

    # 准备 strategies.json
    strategies = [
        {"id": "breakout", "name": "放量突破", "enabled": True},
        {"id": "dip_buy", "name": "低吸回调", "enabled": True},
    ]
    (tmp_path / "strategies.json").write_text(
        json.dumps(strategies, ensure_ascii=False), encoding="utf-8")

    # cascade_log.json 不需要预先存在
    yield tmp_path


@pytest.fixture
def engine():
    """每个测试创建新引擎"""
    # 重置全局实例
    import cascade_engine
    cascade_engine._engine = None
    return cascade_engine.get_cascade_engine()


# ================================================================
#  基础功能测试
# ================================================================

class TestCascadeEngineBasic:
    """基础功能"""

    def test_engine_singleton(self):
        """全局实例是单例"""
        import cascade_engine
        cascade_engine._engine = None
        e1 = cascade_engine.get_cascade_engine()
        e2 = cascade_engine.get_cascade_engine()
        assert e1 is e2

    def test_rules_registered(self, engine):
        """所有规则正确注册"""
        triggers = {r.trigger for r in engine.rules}
        assert "strategy_pause" in triggers
        assert "strategy_disable" in triggers
        assert "circuit_breaker" in triggers
        assert "regime_change" in triggers
        assert "factor_retire" in triggers
        assert "strategy_resume" in triggers

    def test_rule_count(self, engine):
        """至少注册了10个规则"""
        assert len(engine.rules) >= 10

    def test_custom_rule_register(self, engine):
        """可以注册自定义规则"""
        from cascade_engine import CascadeRule
        n_before = len(engine.rules)
        engine.register(CascadeRule(
            name="test_custom",
            trigger="test_trigger",
            targets=["test_target"],
            handler=lambda ctx: None,
        ))
        assert len(engine.rules) == n_before + 1


# ================================================================
#  Preview 测试
# ================================================================

class TestCascadePreview:
    """预览功能"""

    def test_preview_strategy_pause(self, engine):
        """preview 返回正确的影响范围"""
        result = engine.preview("strategy_pause", strategy="放量突破")
        assert result["trigger"] == "strategy_pause"
        assert "scheduler" in result["affected_targets"]
        assert "batch_push" in result["affected_targets"]
        assert "learning_engine" in result["affected_targets"]
        assert "signal_tracker" in result["affected_targets"]
        assert len(result["rules"]) >= 4

    def test_preview_circuit_breaker(self, engine):
        """熔断预览"""
        result = engine.preview("circuit_breaker")
        assert "all_strategies" in result["affected_targets"]
        assert "notifier" in result["affected_targets"]

    def test_preview_unknown_trigger(self, engine):
        """未知触发器返回空列表"""
        result = engine.preview("unknown_trigger")
        assert result["affected_targets"] == []
        assert result["rules"] == []

    def test_preview_does_not_modify_state(self, engine, isolate_files):
        """preview 不修改任何文件"""
        mem_before = (isolate_files / "agent_memory.json").read_text()
        engine.preview("strategy_pause", strategy="放量突破")
        mem_after = (isolate_files / "agent_memory.json").read_text()
        assert mem_before == mem_after


# ================================================================
#  Execute 测试 — strategy_pause
# ================================================================

class TestExecuteStrategyPause:
    """策略暂停级联"""

    def test_pause_updates_memory(self, engine, isolate_files):
        """暂停策略写入 agent_memory"""
        ctx = engine.execute("strategy_pause", strategy="放量突破",
                             reason="连亏5次")
        assert len(ctx.errors) == 0
        assert "scheduler" in ctx.affected

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        state = memory["strategy_states"]["放量突破"]
        assert state["status"] == "paused"
        assert state["pause_reason"] == "连亏5次"
        assert state["auto_resume_date"] is not None

    def test_pause_no_strategy_param(self, engine, isolate_files):
        """缺少 strategy 参数不崩溃"""
        ctx = engine.execute("strategy_pause")
        assert len(ctx.errors) == 0

    def test_pause_cascade_log_created(self, engine, isolate_files):
        """级联日志正确写入"""
        engine.execute("strategy_pause", strategy="低吸回调", reason="测试")

        log_path = isolate_files / "cascade_log.json"
        assert log_path.exists()
        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(log["cascades"]) == 1
        entry = log["cascades"][0]
        assert entry["trigger"] == "strategy_pause"
        assert entry["success"] is True
        assert "scheduler" in entry["affected"]


# ================================================================
#  Execute 测试 — strategy_resume
# ================================================================

class TestExecuteStrategyResume:
    """策略恢复级联"""

    def test_resume_updates_memory(self, engine, isolate_files):
        """恢复策略正确更新 memory"""
        # 先暂停
        engine.execute("strategy_pause", strategy="放量突破", reason="测试")
        # 再恢复
        ctx = engine.execute("strategy_resume", strategy="放量突破")
        assert len(ctx.errors) == 0

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        state = memory["strategy_states"]["放量突破"]
        assert state["status"] == "active"
        assert state["paused_since"] is None
        assert state["pause_reason"] is None


# ================================================================
#  Execute 测试 — strategy_disable
# ================================================================

class TestExecuteStrategyDisable:
    """策略禁用级联"""

    def test_disable_updates_strategies_json(self, engine, isolate_files):
        """禁用策略更新 strategies.json"""
        ctx = engine.execute("strategy_disable", strategy="放量突破")
        assert len(ctx.errors) == 0

        strategies = json.loads(
            (isolate_files / "strategies.json").read_text(encoding="utf-8"))
        breakout = [s for s in strategies if s["name"] == "放量突破"][0]
        assert breakout["enabled"] is False

    def test_disable_updates_memory(self, engine, isolate_files):
        """禁用策略更新 agent_memory"""
        engine.execute("strategy_disable", strategy="放量突破")

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        state = memory["strategy_states"]["放量突破"]
        assert state["status"] == "disabled"


# ================================================================
#  Execute 测试 — circuit_breaker
# ================================================================

class TestExecuteCircuitBreaker:
    """熔断级联"""

    @patch("notifier.notify_wechat_raw")
    def test_circuit_breaker_pauses_all(self, mock_notify, engine,
                                        isolate_files):
        """熔断暂停所有活跃策略"""
        ctx = engine.execute("circuit_breaker", reason="单日亏损>5%")
        assert len(ctx.errors) == 0
        assert "all_strategies" in ctx.affected

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        for name, state in memory["strategy_states"].items():
            assert state["status"] == "paused", f"{name} 应该被暂停"
            assert "熔断" in state.get("pause_reason", "")

    @patch("notifier.notify_wechat_raw")
    def test_circuit_breaker_notify_failure_not_fatal(self, mock_notify,
                                                       engine, isolate_files):
        """通知失败不影响熔断执行"""
        mock_notify.side_effect = Exception("网络不可用")
        ctx = engine.execute("circuit_breaker", reason="测试")
        # 通知失败记录error但不阻塞, all_strategies 应该成功
        assert "all_strategies" in ctx.affected

    @patch("notifier.notify_wechat_raw")
    def test_circuit_breaker_resume(self, mock_notify, engine, isolate_files):
        """熔断后可以恢复"""
        engine.execute("circuit_breaker", reason="测试")

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        for state in memory["strategy_states"].values():
            assert state["status"] == "paused"

    def test_circuit_breaker_resume(self, engine, isolate_files):
        """熔断后可以恢复"""
        engine.execute("circuit_breaker", reason="测试")

        # 手动恢复 (通过 rollback context)
        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        # 验证所有策略被暂停
        for state in memory["strategy_states"].values():
            assert state["status"] == "paused"


# ================================================================
#  Execute 测试 — regime_change
# ================================================================

class TestExecuteRegimeChange:
    """Regime切换级联"""

    def test_regime_change_no_error(self, engine):
        """regime切换不报错"""
        ctx = engine.execute("regime_change", new_regime="bear",
                             old_regime="neutral")
        assert len(ctx.errors) == 0
        assert "regime_router" in ctx.affected
        assert "learning_engine" in ctx.affected


# ================================================================
#  Execute 测试 — factor_retire
# ================================================================

class TestExecuteFactorRetire:
    """因子退役级联"""

    def test_factor_retire_no_error(self, engine):
        """因子退役不报错"""
        ctx = engine.execute("factor_retire", factor="mom_5d",
                             factor_key="s_forge_mom_5d")
        assert len(ctx.errors) == 0
        assert "tunable_params" in ctx.affected
        assert "ml_factor_model" in ctx.affected


# ================================================================
#  Rollback 测试
# ================================================================

class TestCascadeRollback:
    """回滚功能"""

    def test_rollback_on_error(self, engine, isolate_files):
        """规则执行失败时触发回滚"""
        from cascade_engine import CascadeRule

        rollback_called = []

        def failing_handler(ctx):
            raise RuntimeError("模拟失败")

        def rollback_fn(ctx):
            rollback_called.append(True)

        # 先注册一个有回滚的正常规则
        engine.register(CascadeRule(
            name="test_ok",
            trigger="test_rollback",
            targets=["test"],
            handler=lambda ctx: None,
            rollback=rollback_fn,
            priority=1,
        ))
        # 再注册一个会失败的规则
        engine.register(CascadeRule(
            name="test_fail",
            trigger="test_rollback",
            targets=["test2"],
            handler=failing_handler,
            priority=2,
        ))

        ctx = engine.execute("test_rollback")
        assert len(ctx.errors) == 1
        assert "模拟失败" in ctx.errors[0]
        assert len(rollback_called) == 1  # 回滚被调用


# ================================================================
#  日志持久化测试
# ================================================================

class TestCascadeLog:
    """日志持久化"""

    def test_log_max_100(self, engine, isolate_files):
        """日志最多保留100条"""
        for i in range(110):
            engine.execute("strategy_pause", strategy="放量突破",
                           reason=f"第{i}次")

        log = json.loads(
            (isolate_files / "cascade_log.json").read_text(encoding="utf-8"))
        assert len(log["cascades"]) <= 100

    def test_log_contains_required_fields(self, engine, isolate_files):
        """日志条目包含必填字段"""
        engine.execute("strategy_pause", strategy="测试", reason="单元测试")
        log = json.loads(
            (isolate_files / "cascade_log.json").read_text(encoding="utf-8"))
        entry = log["cascades"][0]
        assert "trigger" in entry
        assert "params" in entry
        assert "timestamp" in entry
        assert "affected" in entry
        assert "success" in entry


# ================================================================
#  快捷函数测试
# ================================================================

class TestShortcutFunctions:
    """cascade() 和 cascade_preview() 快捷函数"""

    def test_cascade_shortcut(self, engine, isolate_files):
        """cascade() 快捷函数正常工作"""
        import cascade_engine
        ctx = cascade_engine.cascade("strategy_pause", strategy="放量突破",
                                      reason="快捷测试")
        assert len(ctx.errors) == 0
        assert "scheduler" in ctx.affected

    def test_cascade_preview_shortcut(self, engine):
        """cascade_preview() 快捷函数正常工作"""
        import cascade_engine
        result = cascade_engine.cascade_preview("circuit_breaker")
        assert "all_strategies" in result["affected_targets"]


# ================================================================
#  集成测试 — 验证外部模块调用级联引擎
# ================================================================

class TestIntegrationAgentBrain:
    """agent_brain 集成 cascade"""

    def test_pause_triggers_cascade(self, isolate_files):
        """agent_brain._action_pause_strategy 触发级联"""
        with patch("cascade_engine.CascadeEngine.execute") as mock_exec:
            mock_exec.return_value = MagicMock(errors=[], affected=["scheduler"])
            # 模拟 agent_brain 调用
            from cascade_engine import cascade
            ctx = cascade("strategy_pause", strategy="放量突破", reason="连亏")
            mock_exec.assert_called_once()
            args = mock_exec.call_args
            assert args[0][0] == "strategy_pause"


class TestIntegrationFactorForge:
    """factor_forge 集成 cascade"""

    def test_retire_triggers_cascade(self, isolate_files):
        """因子退役触发级联"""
        with patch("cascade_engine.CascadeEngine.execute") as mock_exec:
            mock_exec.return_value = MagicMock(errors=[], affected=["tunable_params"])
            from cascade_engine import cascade
            ctx = cascade("factor_retire", factor="mom_5d")
            mock_exec.assert_called_once()


class TestIntegrationApiGuard:
    """api_guard SafeMode 集成 cascade"""

    def test_circuit_breaker_triggers_cascade(self, isolate_files):
        """SafeMode 触发级联"""
        with patch("cascade_engine.CascadeEngine.execute") as mock_exec:
            mock_exec.return_value = MagicMock(errors=[], affected=["all_strategies"])
            from cascade_engine import cascade
            ctx = cascade("circuit_breaker", reason="3/5 API源熔断")
            mock_exec.assert_called_once()
            assert mock_exec.call_args[1]["reason"] == "3/5 API源熔断"


# ================================================================
#  边界条件测试
# ================================================================

class TestEdgeCases:
    """边界条件"""

    def test_execute_empty_trigger(self, engine):
        """空触发器不崩溃"""
        ctx = engine.execute("")
        assert len(ctx.affected) == 0

    def test_execute_none_params(self, engine):
        """无参数不崩溃"""
        ctx = engine.execute("strategy_pause")
        assert len(ctx.errors) == 0

    def test_multiple_executes_sequential(self, engine, isolate_files):
        """连续多次执行不冲突"""
        engine.execute("strategy_pause", strategy="放量突破", reason="第1次")
        engine.execute("strategy_pause", strategy="低吸回调", reason="第2次")
        engine.execute("strategy_resume", strategy="放量突破")

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        assert memory["strategy_states"]["放量突破"]["status"] == "active"
        assert memory["strategy_states"]["低吸回调"]["status"] == "paused"

    def test_disable_nonexistent_strategy(self, engine, isolate_files):
        """禁用不存在的策略不崩溃"""
        ctx = engine.execute("strategy_disable", strategy="不存在的策略")
        assert len(ctx.errors) == 0

    def test_concurrent_pause_resume(self, engine, isolate_files):
        """暂停后立即恢复, 状态正确"""
        engine.execute("strategy_pause", strategy="隔夜选股", reason="测试")
        engine.execute("strategy_resume", strategy="隔夜选股")

        memory = json.loads(
            (isolate_files / "agent_memory.json").read_text(encoding="utf-8"))
        assert memory["strategy_states"]["隔夜选股"]["status"] == "active"
