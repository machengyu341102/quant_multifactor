"""智能体注册表测试"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_registry import (
    AgentInfo, AgentRegistry, register_builtin_agents,
    get_registry, reset_registry,
)


@pytest.fixture(autouse=True)
def clean_registry(tmp_path, monkeypatch):
    """每个测试用独立的 Registry, 使用临时路径"""
    reset_registry()
    monkeypatch.setattr("agent_registry._REGISTRY_PATH", str(tmp_path / "agents_registry.json"))
    yield
    reset_registry()


class TestAgentInfo:
    def test_default_values(self):
        a = AgentInfo(name="test", display_name="测试", module="mod")
        assert a.status == "active"
        assert a.health == 1.0
        assert a.error_count == 0

    def test_to_dict_roundtrip(self):
        a = AgentInfo(name="test", display_name="测试", module="mod",
                      capabilities=["cap1", "cap2"], health=0.8)
        d = a.to_dict()
        a2 = AgentInfo.from_dict(d)
        assert a2.name == a.name
        assert a2.display_name == a.display_name
        assert a2.capabilities == a.capabilities
        assert a2.health == a.health


class TestAgentRegistryRegister:
    def test_register_new_agent(self):
        r = AgentRegistry()
        agent = r.register("test", "测试智能体", "test_module", ["cap1"])
        assert agent.name == "test"
        assert r.get_agent("test") is not None

    def test_register_existing_updates(self):
        r = AgentRegistry()
        r.register("test", "旧名字", "old_mod", ["cap1"])
        r.register("test", "新名字", "new_mod", ["cap1", "cap2"])
        agent = r.get_agent("test")
        assert agent.display_name == "新名字"
        assert agent.module == "new_mod"
        assert len(agent.capabilities) == 2


class TestAgentRegistryUnregister:
    def test_unregister_existing(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        assert r.unregister("test") is True
        assert r.get_agent("test") is None

    def test_unregister_nonexistent(self):
        r = AgentRegistry()
        assert r.unregister("nonexistent") is False


class TestAgentRegistryHealth:
    def test_update_health_normal(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.update_health("test", 0.8)
        assert r.get_agent("test").health == 0.8

    def test_update_health_auto_error(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.update_health("test", 0.2, error_msg="something broke")
        agent = r.get_agent("test")
        assert agent.status == "error"
        assert agent.last_error == "something broke"

    def test_update_health_auto_recover(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.update_health("test", 0.2)
        assert r.get_agent("test").status == "error"
        r.update_health("test", 0.6)
        assert r.get_agent("test").status == "active"

    def test_health_clamp(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.update_health("test", 1.5)
        assert r.get_agent("test").health == 1.0
        r.update_health("test", -0.5)
        assert r.get_agent("test").health == 0.0


class TestAgentRegistryReportRun:
    def test_report_success(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.update_health("test", 0.5)
        r.report_run("test", success=True)
        agent = r.get_agent("test")
        assert agent.last_run  # 已设置时间
        assert agent.error_count == 0
        assert agent.health > 0.5  # 回升

    def test_report_failure_accumulates(self):
        r = AgentRegistry()
        r.register("test", "测试", "mod", [])
        r.report_run("test", success=False, error_msg="err1")
        r.report_run("test", success=False, error_msg="err2")
        r.report_run("test", success=False, error_msg="err3")
        agent = r.get_agent("test")
        assert agent.error_count == 3
        assert agent.status == "error"
        assert agent.last_error == "err3"


class TestAgentRegistryGetUnhealthy:
    def test_get_unhealthy(self):
        r = AgentRegistry()
        r.register("good", "好的", "mod", [])
        r.register("bad", "差的", "mod", [])
        r.update_health("bad", 0.3)
        unhealthy = r.get_unhealthy(threshold=0.5)
        assert len(unhealthy) == 1
        assert unhealthy[0].name == "bad"


class TestAgentRegistryListAgents:
    def test_list_all(self):
        r = AgentRegistry()
        r.register("a", "A", "mod", [])
        r.register("b", "B", "mod", [])
        assert len(r.list_agents()) == 2

    def test_list_by_status(self):
        r = AgentRegistry()
        r.register("a", "A", "mod", [])
        r.register("b", "B", "mod", [])
        r.update_health("b", 0.1)  # → error
        active = r.list_agents(status="active")
        error = r.list_agents(status="error")
        assert len(active) == 1
        assert len(error) == 1


class TestAgentRegistryPersist:
    def test_persist_and_reload(self, tmp_path, monkeypatch):
        path = str(tmp_path / "reg_test.json")
        monkeypatch.setattr("agent_registry._REGISTRY_PATH", path)

        r = AgentRegistry()
        r.register("test", "测试", "mod", ["cap1"])
        r.update_health("test", 0.7)
        r.persist()

        r2 = AgentRegistry()
        agent = r2.get_agent("test")
        assert agent is not None
        assert agent.display_name == "测试"
        assert agent.health == 0.7


class TestBuiltinAgents:
    def test_register_builtins(self):
        r = AgentRegistry()
        register_builtin_agents(r)
        agents = r.list_agents()
        assert len(agents) == 10
        names = {a.name for a in agents}
        assert "brain" in names
        assert "risk_inspector" in names
        assert "market_radar" in names
        assert "execution_judge" in names
        assert "healer" in names
        assert "crypto_scanner" in names
        assert "stock_analyst" in names
        assert "us_stock_analyzer" in names
        assert "cross_market" in names
