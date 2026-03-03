"""
事件总线 — 多智能体通信基础设施
================================
任何模块 → bus.emit() → EventBus 内存队列 (去重+排序)
→ agent_brain → bus.consume() → 按优先级返回 → 转为 findings

核心组件:
  - Priority: 事件优先级枚举 (CRITICAL/URGENT/NORMAL/LOW)
  - Event: 事件数据结构
  - EventBus: 发布/消费/去重/持久化

用法:
  from event_bus import get_event_bus
  bus = get_event_bus()
  bus.emit("portfolio_risk", Priority.CRITICAL, "drawdown_breach", "risk", {"dd": -8.5})
  events = bus.consume()
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import IntEnum
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("event_bus")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_QUEUE_PATH = os.path.join(_BASE_DIR, "event_queue.json")


# ================================================================
#  Priority 枚举
# ================================================================

class Priority(IntEnum):
    CRITICAL = 1   # 风控熔断、组合回撤超限
    URGENT = 2     # 行情转熊、策略连亏、止损触发
    NORMAL = 3     # 策略信号、开仓执行
    LOW = 4        # 信息记录、统计


# ================================================================
#  Event 数据结构
# ================================================================

@dataclass
class Event:
    source: str          # 发射模块 "portfolio_risk"
    priority: int        # Priority 值 (1-4)
    event_type: str      # "drawdown_breach"
    category: str        # "risk"/"regime"/"strategy"/"info"
    payload: dict        # 自由数据
    timestamp: str = ""  # ISO, 自动生成
    event_id: str = ""   # UUID, 自动生成
    consumed: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.event_id:
            self.event_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            source=d.get("source", ""),
            priority=d.get("priority", Priority.NORMAL),
            event_type=d.get("event_type", ""),
            category=d.get("category", "info"),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", ""),
            event_id=d.get("event_id", ""),
            consumed=d.get("consumed", False),
        )


# ================================================================
#  EventBus 类
# ================================================================

class EventBus:
    """事件总线: 发布/消费/去重/持久化"""

    def __init__(self, dedup_window_sec: int = 60, max_events: int = 500):
        self._events: list[Event] = []
        self._subscribers: dict[str, list[Callable]] = {}
        self._dedup_window_sec = dedup_window_sec
        self._max_events = max_events
        self._total_emitted = 0
        self._total_consumed = 0
        self._total_deduped = 0
        # 加载持久化
        self._load()

    def emit(self, source: str, priority: Priority, event_type: str,
             category: str, payload: dict) -> str:
        """发射事件, 返回 event_id. 重复事件返回空字符串."""
        # 去重检查
        if self._is_duplicate(source, event_type, payload):
            self._total_deduped += 1
            return ""

        event = Event(
            source=source,
            priority=int(priority),
            event_type=event_type,
            category=category,
            payload=payload,
        )
        self._events.append(event)
        self._total_emitted += 1

        # 触发订阅回调
        callbacks = self._subscribers.get(event_type, [])
        for cb in callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.debug("事件回调异常 (%s): %s", event_type, e)

        # 容量控制
        self._enforce_limit()

        logger.debug("事件发射: [%s] %s.%s", Priority(priority).name,
                      source, event_type)
        return event.event_id

    def consume(self, max_count: int = 50) -> list[Event]:
        """按优先级+时间排序消费未处理事件"""
        unconsumed = [e for e in self._events if not e.consumed]
        # 按 priority (低值优先) 再按 timestamp
        unconsumed.sort(key=lambda e: (e.priority, e.timestamp))

        to_consume = unconsumed[:max_count]
        for e in to_consume:
            e.consumed = True
        self._total_consumed += len(to_consume)
        return to_consume

    def peek(self, priority: int = None) -> list[Event]:
        """查看未消费事件 (不标记已消费)"""
        unconsumed = [e for e in self._events if not e.consumed]
        if priority is not None:
            unconsumed = [e for e in unconsumed if e.priority == priority]
        unconsumed.sort(key=lambda e: (e.priority, e.timestamp))
        return unconsumed

    def subscribe(self, event_type: str, callback: Callable):
        """注册回调: 当特定 event_type 被 emit 时立即触发"""
        self._subscribers.setdefault(event_type, []).append(callback)

    def stats(self) -> dict:
        """统计信息"""
        unconsumed = sum(1 for e in self._events if not e.consumed)
        by_priority = {}
        for e in self._events:
            pname = Priority(e.priority).name if e.priority in (1, 2, 3, 4) else str(e.priority)
            by_priority[pname] = by_priority.get(pname, 0) + 1
        return {
            "total_events": len(self._events),
            "unconsumed": unconsumed,
            "total_emitted": self._total_emitted,
            "total_consumed": self._total_consumed,
            "total_deduped": self._total_deduped,
            "by_priority": by_priority,
        }

    def persist(self):
        """保存到 event_queue.json"""
        data = [e.to_dict() for e in self._events]
        safe_save(_QUEUE_PATH, data)

    def clear(self):
        """清空所有事件 (测试/重置用)"""
        self._events.clear()

    # ---- 内部方法 ----

    def _is_duplicate(self, source: str, event_type: str, payload: dict) -> bool:
        """同 (source, event_type, payload_hash) 在 dedup_window_sec 内忽略"""
        payload_hash = self._hash_payload(payload)
        now = datetime.now()
        for e in reversed(self._events):
            if e.source != source or e.event_type != event_type:
                continue
            if self._hash_payload(e.payload) != payload_hash:
                continue
            try:
                event_time = datetime.fromisoformat(e.timestamp)
                if (now - event_time).total_seconds() < self._dedup_window_sec:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _enforce_limit(self):
        """超过 max_events 时, 先丢 LOW 级别已消费事件"""
        while len(self._events) > self._max_events:
            # 找 LOW+consumed 优先删除
            removed = False
            for i, e in enumerate(self._events):
                if e.consumed and e.priority == Priority.LOW:
                    self._events.pop(i)
                    removed = True
                    break
            if not removed:
                # 删最老的已消费事件
                for i, e in enumerate(self._events):
                    if e.consumed:
                        self._events.pop(i)
                        removed = True
                        break
            if not removed:
                # 没有已消费事件, 删最老的 LOW 事件
                for i, e in enumerate(self._events):
                    if e.priority == Priority.LOW:
                        self._events.pop(i)
                        removed = True
                        break
            if not removed:
                # 最后手段: 删最老
                self._events.pop(0)

    def _load(self):
        """从持久化文件加载"""
        data = safe_load(_QUEUE_PATH, default=[])
        for d in data:
            try:
                self._events.append(Event.from_dict(d))
            except Exception:
                continue


# ================================================================
#  单例
# ================================================================

_bus_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """获取全局 EventBus 单例"""
    global _bus_instance
    if _bus_instance is None:
        try:
            from config import MULTI_AGENT_PARAMS
            params = MULTI_AGENT_PARAMS.get("event_bus", {})
        except (ImportError, AttributeError):
            params = {}
        _bus_instance = EventBus(
            dedup_window_sec=params.get("dedup_window_sec", 60),
            max_events=params.get("max_events", 500),
        )
    return _bus_instance


def reset_event_bus():
    """重置单例 (测试用)"""
    global _bus_instance
    _bus_instance = None


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    bus = get_event_bus()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "stats":
        s = bus.stats()
        print(f"\n=== 事件总线统计 ===")
        print(f"  总事件: {s['total_events']}")
        print(f"  未消费: {s['unconsumed']}")
        print(f"  累计发射: {s['total_emitted']}")
        print(f"  累计消费: {s['total_consumed']}")
        print(f"  去重拦截: {s['total_deduped']}")
        print(f"  按优先级: {s['by_priority']}")
    elif cmd == "peek":
        events = bus.peek()
        print(f"\n=== 未消费事件 ({len(events)}) ===")
        for e in events[:20]:
            pname = Priority(e.priority).name if e.priority in (1, 2, 3, 4) else str(e.priority)
            print(f"  [{pname}] {e.source}.{e.event_type} "
                  f"({e.category}) {e.timestamp[:19]}")
    elif cmd == "clear":
        bus.clear()
        bus.persist()
        print("事件队列已清空")
    else:
        print("用法:")
        print("  python3 event_bus.py stats   # 统计")
        print("  python3 event_bus.py peek    # 查看未消费事件")
        print("  python3 event_bus.py clear   # 清空队列")
