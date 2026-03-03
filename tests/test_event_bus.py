"""事件总线测试"""

import os
import sys
import time
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from event_bus import EventBus, Event, Priority, get_event_bus, reset_event_bus


@pytest.fixture(autouse=True)
def clean_bus(tmp_path, monkeypatch):
    """每个测试用独立的 EventBus, 使用临时路径"""
    reset_event_bus()
    monkeypatch.setattr("event_bus._QUEUE_PATH", str(tmp_path / "event_queue.json"))
    yield
    reset_event_bus()


class TestPriority:
    def test_priority_ordering(self):
        assert Priority.CRITICAL < Priority.URGENT < Priority.NORMAL < Priority.LOW

    def test_priority_values(self):
        assert Priority.CRITICAL == 1
        assert Priority.URGENT == 2
        assert Priority.NORMAL == 3
        assert Priority.LOW == 4


class TestEvent:
    def test_event_creation(self):
        e = Event(source="test", priority=Priority.NORMAL,
                  event_type="test_event", category="info", payload={"a": 1})
        assert e.source == "test"
        assert e.priority == Priority.NORMAL
        assert e.event_id  # 自动生成
        assert e.timestamp  # 自动生成
        assert not e.consumed

    def test_event_to_dict_roundtrip(self):
        e = Event(source="test", priority=Priority.URGENT,
                  event_type="alert", category="risk", payload={"level": "high"})
        d = e.to_dict()
        e2 = Event.from_dict(d)
        assert e2.source == e.source
        assert e2.priority == e.priority
        assert e2.event_type == e.event_type
        assert e2.payload == e.payload


class TestEventBusEmit:
    def test_basic_emit(self):
        bus = EventBus()
        eid = bus.emit("test", Priority.NORMAL, "signal", "strategy", {"code": "000001"})
        assert eid  # 返回非空 event_id
        assert bus.stats()["total_events"] == 1

    def test_emit_returns_empty_for_duplicate(self):
        bus = EventBus(dedup_window_sec=60)
        eid1 = bus.emit("src", Priority.NORMAL, "evt", "info", {"k": 1})
        eid2 = bus.emit("src", Priority.NORMAL, "evt", "info", {"k": 1})
        assert eid1  # 第一次成功
        assert eid2 == ""  # 重复, 返回空
        assert bus.stats()["total_deduped"] == 1

    def test_different_payload_not_deduped(self):
        bus = EventBus(dedup_window_sec=60)
        eid1 = bus.emit("src", Priority.NORMAL, "evt", "info", {"k": 1})
        eid2 = bus.emit("src", Priority.NORMAL, "evt", "info", {"k": 2})
        assert eid1 and eid2
        assert bus.stats()["total_events"] == 2


class TestEventBusConsume:
    def test_consume_returns_by_priority(self):
        bus = EventBus()
        bus.emit("a", Priority.LOW, "low_evt", "info", {})
        bus.emit("b", Priority.CRITICAL, "crit_evt", "risk", {})
        bus.emit("c", Priority.NORMAL, "normal_evt", "strategy", {})

        events = bus.consume()
        assert len(events) == 3
        assert events[0].priority == Priority.CRITICAL
        assert events[1].priority == Priority.NORMAL
        assert events[2].priority == Priority.LOW

    def test_consume_marks_as_consumed(self):
        bus = EventBus()
        bus.emit("a", Priority.NORMAL, "evt", "info", {})
        events = bus.consume()
        assert len(events) == 1
        assert events[0].consumed
        # 再次消费应为空
        events2 = bus.consume()
        assert len(events2) == 0

    def test_consume_max_count(self):
        bus = EventBus()
        for i in range(10):
            bus.emit("src", Priority.NORMAL, f"evt_{i}", "info", {"i": i})
        events = bus.consume(max_count=3)
        assert len(events) == 3


class TestEventBusPeek:
    def test_peek_does_not_consume(self):
        bus = EventBus()
        bus.emit("a", Priority.NORMAL, "evt", "info", {})
        peeked = bus.peek()
        assert len(peeked) == 1
        # peek 后仍可消费
        consumed = bus.consume()
        assert len(consumed) == 1

    def test_peek_filter_by_priority(self):
        bus = EventBus()
        bus.emit("a", Priority.CRITICAL, "crit", "risk", {})
        bus.emit("b", Priority.LOW, "low", "info", {})
        critical = bus.peek(priority=Priority.CRITICAL)
        assert len(critical) == 1
        assert critical[0].event_type == "crit"


class TestEventBusSubscribe:
    def test_subscribe_callback(self):
        bus = EventBus()
        received = []
        bus.subscribe("my_event", lambda e: received.append(e))
        bus.emit("src", Priority.NORMAL, "my_event", "info", {"data": 42})
        assert len(received) == 1
        assert received[0].payload["data"] == 42


class TestEventBusCapacity:
    def test_enforce_limit_drops_low_consumed(self):
        bus = EventBus(max_events=5)
        # 填充 5 个 LOW 事件
        for i in range(5):
            bus.emit("src", Priority.LOW, f"low_{i}", "info", {"i": i})
        bus.consume()  # 全部标记已消费
        # 再 emit 一个, 应触发清理
        bus.emit("src", Priority.CRITICAL, "crit", "risk", {})
        assert len(bus._events) <= 5


class TestEventBusPersist:
    def test_persist_and_reload(self, tmp_path, monkeypatch):
        path = str(tmp_path / "bus_test.json")
        monkeypatch.setattr("event_bus._QUEUE_PATH", path)

        bus = EventBus()
        bus.emit("src", Priority.URGENT, "alert", "risk", {"dd": -5.0})
        bus.persist()

        # 新实例应能加载
        bus2 = EventBus()
        assert len(bus2._events) == 1
        assert bus2._events[0].event_type == "alert"


class TestEventBusStats:
    def test_stats_accuracy(self):
        bus = EventBus()
        bus.emit("a", Priority.CRITICAL, "e1", "risk", {})
        bus.emit("b", Priority.LOW, "e2", "info", {})
        bus.consume(max_count=1)

        s = bus.stats()
        assert s["total_events"] == 2
        assert s["unconsumed"] == 1
        assert s["total_emitted"] == 2
        assert s["total_consumed"] == 1
