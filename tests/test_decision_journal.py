"""
决策闭环验证 + 事件因果链 + 在线学习 测试
==========================================
覆盖:
  - decision journal: 记录/验证/准确率EMA/自适应阈值
  - event causal chain: parent_event_id/get_causal_chain
  - online learning: incremental_update/budget control
"""

import json
import os
import sys
import pytest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================================================================
#  Task 1: Decision Journal
# ================================================================

@pytest.fixture
def brain_tmp(tmp_path, monkeypatch):
    """将 agent_brain 的文件路径重定向到临时目录"""
    import agent_brain
    monkeypatch.setattr(agent_brain, "_MEMORY_PATH",
                        str(tmp_path / "agent_memory.json"))
    monkeypatch.setattr(agent_brain, "_SCORECARD_PATH",
                        str(tmp_path / "scorecard.json"))
    monkeypatch.setattr(agent_brain, "_DECISION_JOURNAL_PATH",
                        str(tmp_path / "decision_journal.json"))
    # 重置缓存
    agent_brain._observe_cache["scorecard_len"] = 0
    agent_brain._observe_cache["last_date"] = ""
    agent_brain._last_saved_hash = None
    return tmp_path


class TestRecordDecision:
    def test_record_creates_entry(self, brain_tmp):
        import agent_brain
        did = agent_brain._record_decision(
            "pause_strategy", "放量突破选股", "连亏4次", regime="weak")
        assert did.startswith("D")

        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        assert len(journal) == 1
        assert journal[0]["action"] == "pause_strategy"
        assert journal[0]["strategy"] == "放量突破选股"
        assert journal[0]["regime"] == "weak"
        assert journal[0]["verified"] is False

    def test_record_sets_verify_date(self, brain_tmp):
        import agent_brain
        agent_brain._record_decision(
            "resume_strategy", "集合竞价选股", "恢复")
        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        verify_days = agent_brain.AGENT_PARAMS.get(
            "decision_verify_after_days", 5)
        expected = (date.today() + timedelta(days=verify_days)).isoformat()
        assert journal[0]["verify_date"] == expected

    def test_record_with_parent_event(self, brain_tmp):
        import agent_brain
        agent_brain._record_decision(
            "pause_strategy", "放量突破选股", "test",
            parent_event_id="abc123")
        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        assert journal[0]["parent_event_id"] == "abc123"

    def test_journal_capped_at_500(self, brain_tmp):
        import agent_brain
        # Pre-fill with 500 entries
        existing = [{"id": f"D{i}", "action": "log", "verified": True}
                    for i in range(500)]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, existing)

        agent_brain._record_decision("pause_strategy", "test", "overflow")
        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        assert len(journal) == 500  # capped


class TestVerifyPastDecisions:
    def test_verify_pause_correct(self, brain_tmp):
        """暂停后策略继续亏 → correct"""
        import agent_brain
        past = (date.today() - timedelta(days=6)).isoformat()
        verify_date = (date.today() - timedelta(days=1)).isoformat()
        journal = [{
            "id": "D001", "action": "pause_strategy",
            "strategy": "放量突破选股", "reason": "连亏",
            "date": past, "regime": "weak", "context": {},
            "verified": False, "verify_date": verify_date,
            "outcome": None, "parent_event_id": "",
        }]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, journal)

        # Scorecard: 暂停后的记录全是loss
        scorecard = []
        for i in range(3):
            d = (date.today() - timedelta(days=i + 1)).isoformat()
            scorecard.append({
                "rec_date": d, "strategy": "放量突破选股",
                "result": "loss", "net_return_pct": -2.0,
            })
        _write_json(agent_brain._SCORECARD_PATH, scorecard)

        results = agent_brain.verify_past_decisions()
        assert len(results) == 1
        assert results[0]["outcome"] == "correct"

    def test_verify_pause_incorrect(self, brain_tmp):
        """暂停后策略表现好 → incorrect"""
        import agent_brain
        past = (date.today() - timedelta(days=6)).isoformat()
        verify_date = (date.today() - timedelta(days=1)).isoformat()
        journal = [{
            "id": "D002", "action": "pause_strategy",
            "strategy": "放量突破选股", "reason": "连亏",
            "date": past, "regime": "weak", "context": {},
            "verified": False, "verify_date": verify_date,
            "outcome": None, "parent_event_id": "",
        }]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, journal)

        # Scorecard: 暂停后全是 win
        scorecard = []
        for i in range(4):
            d = (date.today() - timedelta(days=i + 1)).isoformat()
            scorecard.append({
                "rec_date": d, "strategy": "放量突破选股",
                "result": "win", "net_return_pct": 2.0,
            })
        _write_json(agent_brain._SCORECARD_PATH, scorecard)

        results = agent_brain.verify_past_decisions()
        assert len(results) == 1
        assert results[0]["outcome"] == "incorrect"

    def test_verify_resume_correct(self, brain_tmp):
        """恢复后策略赚了 → correct"""
        import agent_brain
        past = (date.today() - timedelta(days=6)).isoformat()
        verify_date = (date.today() - timedelta(days=1)).isoformat()
        journal = [{
            "id": "D003", "action": "resume_strategy",
            "strategy": "尾盘短线选股", "reason": "恢复",
            "date": past, "regime": "neutral", "context": {},
            "verified": False, "verify_date": verify_date,
            "outcome": None, "parent_event_id": "",
        }]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, journal)

        scorecard = []
        for i in range(4):
            d = (date.today() - timedelta(days=i + 1)).isoformat()
            scorecard.append({
                "rec_date": d, "strategy": "尾盘短线选股",
                "result": "win", "net_return_pct": 1.5,
            })
        _write_json(agent_brain._SCORECARD_PATH, scorecard)

        results = agent_brain.verify_past_decisions()
        assert len(results) == 1
        assert results[0]["outcome"] == "correct"

    def test_skip_future_verify_date(self, brain_tmp):
        """未到验证日期 → 跳过"""
        import agent_brain
        future = (date.today() + timedelta(days=3)).isoformat()
        journal = [{
            "id": "D004", "action": "pause_strategy",
            "strategy": "test", "reason": "test",
            "date": date.today().isoformat(), "verified": False,
            "verify_date": future, "outcome": None,
            "regime": "", "context": {}, "parent_event_id": "",
        }]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, journal)

        results = agent_brain.verify_past_decisions()
        assert len(results) == 0

    def test_skip_already_verified(self, brain_tmp):
        """已验证的 → 跳过"""
        import agent_brain
        journal = [{
            "id": "D005", "action": "pause_strategy",
            "strategy": "test", "reason": "test",
            "date": "2026-02-01", "verified": True,
            "verify_date": "2026-02-06", "outcome": "correct",
            "regime": "", "context": {}, "parent_event_id": "",
        }]
        _write_json(agent_brain._DECISION_JOURNAL_PATH, journal)

        results = agent_brain.verify_past_decisions()
        assert len(results) == 0


class TestAdaptiveThreshold:
    def test_high_accuracy_lowers_threshold(self, brain_tmp):
        """多次高准确率 EMA 更新后阈值应降低"""
        import agent_brain
        batch = [{"outcome": "correct"} for _ in range(9)] + \
                [{"outcome": "incorrect"}]
        # Run EMA multiple times to converge above 0.7
        for _ in range(6):
            agent_brain._update_decision_accuracy(batch)

        memory = agent_brain._load_memory()
        meta = memory.get("meta", {})
        assert meta.get("decision_accuracy") is not None
        assert meta["decision_accuracy"] >= 0.7
        assert meta.get("adaptive_consecutive_loss_threshold") == 3

    def test_low_accuracy_raises_threshold(self, brain_tmp):
        """多次低准确率 EMA 更新后阈值应提高"""
        import agent_brain
        batch = [{"outcome": "correct"}] + \
                [{"outcome": "incorrect"} for _ in range(9)]
        for _ in range(6):
            agent_brain._update_decision_accuracy(batch)

        memory = agent_brain._load_memory()
        meta = memory.get("meta", {})
        assert meta["decision_accuracy"] <= 0.4
        assert meta.get("adaptive_consecutive_loss_threshold") == 5

    def test_get_adaptive_threshold(self, brain_tmp):
        import agent_brain
        # No memory → use default
        val = agent_brain.get_adaptive_threshold(
            "consecutive_loss_threshold", 4)
        assert val == 4

    def test_pause_records_decision(self, brain_tmp):
        """_action_pause_strategy 应记录到 decision_journal"""
        import agent_brain
        memory = agent_brain._default_memory()
        agent_brain._action_pause_strategy(
            "放量突破选股", memory, "连亏4次")

        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        assert len(journal) == 1
        assert journal[0]["action"] == "pause_strategy"

    def test_resume_records_decision(self, brain_tmp):
        """_action_resume_strategy 应记录到 decision_journal"""
        import agent_brain
        memory = agent_brain._default_memory()
        agent_brain._action_resume_strategy(
            "集合竞价选股", memory, "恢复")

        journal = json.loads(
            open(agent_brain._DECISION_JOURNAL_PATH).read())
        assert len(journal) == 1
        assert journal[0]["action"] == "resume_strategy"


# ================================================================
#  Task 2: Event Causal Chain
# ================================================================

@pytest.fixture(autouse=False)
def clean_bus(tmp_path, monkeypatch):
    from event_bus import reset_event_bus
    reset_event_bus()
    monkeypatch.setattr("event_bus._QUEUE_PATH",
                        str(tmp_path / "event_queue.json"))
    yield
    reset_event_bus()


class TestEventParentId:
    def test_emit_with_parent(self, clean_bus):
        from event_bus import EventBus, Priority
        bus = EventBus(dedup_window_sec=1, max_events=100)

        # Event A (root)
        eid_a = bus.emit("module_a", Priority.NORMAL, "signal_detected",
                         "strategy", {"msg": "found signal"})
        # Event B (child of A)
        eid_b = bus.emit("module_b", Priority.URGENT, "action_taken",
                         "strategy", {"msg": "paused"},
                         parent_event_id=eid_a)

        assert eid_a != ""
        assert eid_b != ""

        events = bus.consume()
        child = [e for e in events if e.event_id == eid_b][0]
        assert child.parent_event_id == eid_a

    def test_causal_chain(self, clean_bus):
        from event_bus import EventBus, Priority
        bus = EventBus(dedup_window_sec=1, max_events=100)

        # Chain: A → B → C
        eid_a = bus.emit("mod", Priority.NORMAL, "step1",
                         "info", {"step": 1})
        eid_b = bus.emit("mod", Priority.NORMAL, "step2",
                         "info", {"step": 2},
                         parent_event_id=eid_a)
        eid_c = bus.emit("mod", Priority.NORMAL, "step3",
                         "info", {"step": 3},
                         parent_event_id=eid_b)

        chain = bus.get_causal_chain(eid_c)
        assert len(chain) == 3
        assert chain[0].event_id == eid_c
        assert chain[1].event_id == eid_b
        assert chain[2].event_id == eid_a

    def test_causal_chain_single(self, clean_bus):
        from event_bus import EventBus, Priority
        bus = EventBus(dedup_window_sec=1, max_events=100)

        eid = bus.emit("mod", Priority.NORMAL, "solo",
                       "info", {"alone": True})
        chain = bus.get_causal_chain(eid)
        assert len(chain) == 1
        assert chain[0].event_id == eid

    def test_get_children(self, clean_bus):
        from event_bus import EventBus, Priority
        bus = EventBus(dedup_window_sec=1, max_events=100)

        eid_parent = bus.emit("mod", Priority.NORMAL, "parent",
                              "info", {"p": True})
        bus.emit("mod", Priority.NORMAL, "child1",
                 "info", {"c": 1}, parent_event_id=eid_parent)
        bus.emit("mod", Priority.NORMAL, "child2",
                 "info", {"c": 2}, parent_event_id=eid_parent)
        bus.emit("mod", Priority.NORMAL, "orphan",
                 "info", {"c": 3})

        children = bus.get_children(eid_parent)
        assert len(children) == 2

    def test_event_from_dict_preserves_parent(self, clean_bus):
        from event_bus import Event, Priority
        d = {
            "source": "test", "priority": Priority.NORMAL,
            "event_type": "test", "category": "info",
            "payload": {}, "timestamp": "2026-03-05T10:00:00",
            "event_id": "abc", "consumed": False,
            "parent_event_id": "parent123",
        }
        event = Event.from_dict(d)
        assert event.parent_event_id == "parent123"
        # Round-trip
        assert event.to_dict()["parent_event_id"] == "parent123"


# ================================================================
#  Task 3: Online Learning
# ================================================================

@pytest.fixture
def learning_tmp(tmp_path, monkeypatch):
    import learning_engine
    monkeypatch.setattr(learning_engine, "_TUNABLE_PATH",
                        str(tmp_path / "tunable_params.json"))
    monkeypatch.setattr(learning_engine, "_JOURNAL_PATH",
                        str(tmp_path / "trade_journal.json"))
    monkeypatch.setattr(learning_engine, "_SCORECARD_PATH",
                        str(tmp_path / "scorecard.json"))
    monkeypatch.setattr(learning_engine, "_EVOLUTION_PATH",
                        str(tmp_path / "evolution_history.json"))
    # Reset daily tracker
    learning_engine._online_daily_tracker = {
        "date": "", "total_delta": 0.0, "updates": 0}
    return tmp_path


class TestIncrementalUpdate:
    def test_basic_update(self, learning_tmp):
        import learning_engine
        signals = [
            {"strategy": "放量突破选股", "code": "000001",
             "factor_scores": {"s_trend": 0.8, "s_volume": 0.3},
             "t1_return_pct": 2.0, "t1_result": "win"},
            {"strategy": "放量突破选股", "code": "000002",
             "factor_scores": {"s_trend": 0.2, "s_volume": 0.9},
             "t1_return_pct": -1.5, "t1_result": "loss"},
        ]
        result = learning_engine.incremental_update(signals)
        assert result["adjusted"] >= 0
        assert result["skipped_budget"] is False

    def test_empty_signals_noop(self, learning_tmp):
        import learning_engine
        result = learning_engine.incremental_update([])
        assert result["adjusted"] == 0

    def test_budget_limit(self, learning_tmp):
        import learning_engine
        # Exhaust budget
        learning_engine._online_daily_tracker = {
            "date": date.today().isoformat(),
            "total_delta": 0.05,  # at limit
            "updates": 10,
        }
        signals = [
            {"strategy": "test", "code": "000001",
             "factor_scores": {"s_trend": 0.9},
             "t1_return_pct": 5.0, "t1_result": "win"},
        ]
        result = learning_engine.incremental_update(signals)
        assert result["skipped_budget"] is True
        assert result["adjusted"] == 0

    def test_disabled_noop(self, learning_tmp, monkeypatch):
        import learning_engine
        from config import LEARNING_ENGINE_PARAMS
        monkeypatch.setitem(LEARNING_ENGINE_PARAMS,
                            "online_learning_enabled", False)
        signals = [
            {"strategy": "test", "code": "000001",
             "factor_scores": {"s_trend": 0.9},
             "t1_return_pct": 5.0, "t1_result": "win"},
        ]
        result = learning_engine.incremental_update(signals)
        assert result["adjusted"] == 0

    def test_ema_state_persisted(self, learning_tmp):
        import learning_engine
        from json_store import safe_load
        signals = [
            {"strategy": "s1", "code": "001",
             "factor_scores": {"s_trend": 0.9, "s_rsi": 0.1},
             "t1_return_pct": 3.0, "t1_result": "win"},
            {"strategy": "s1", "code": "002",
             "factor_scores": {"s_trend": 0.1, "s_rsi": 0.8},
             "t1_return_pct": -2.0, "t1_result": "loss"},
        ]
        learning_engine.incremental_update(signals)

        tunable = safe_load(str(learning_tmp / "tunable_params.json"),
                            default={})
        assert "_online_ema" in tunable

    def test_daily_tracker_resets(self, learning_tmp):
        """新的一天应重置跟踪器"""
        import learning_engine
        learning_engine._online_daily_tracker = {
            "date": "2026-01-01",
            "total_delta": 0.04,
            "updates": 5,
        }
        signals = [
            {"strategy": "s1", "code": "001",
             "factor_scores": {"s_trend": 0.9, "s_rsi": 0.1},
             "t1_return_pct": 3.0, "t1_result": "win"},
            {"strategy": "s1", "code": "002",
             "factor_scores": {"s_trend": 0.1, "s_rsi": 0.8},
             "t1_return_pct": -2.0, "t1_result": "loss"},
        ]
        learning_engine.incremental_update(signals)
        # Should have reset since date changed
        assert learning_engine._online_daily_tracker["date"] == \
            date.today().isoformat()
