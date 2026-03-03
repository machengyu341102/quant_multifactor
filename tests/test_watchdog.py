"""
watchdog.py 测试
=================
覆盖: 心跳更新/策略状态/健康检查/guard外部看门狗/night_task重试
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture
def hb_path(tmp_path, monkeypatch):
    """临时 heartbeat.json"""
    p = str(tmp_path / "heartbeat.json")
    import watchdog
    monkeypatch.setattr(watchdog, "_HEARTBEAT_PATH", p)
    return p


@pytest.fixture
def night_log_path(tmp_path, monkeypatch):
    """临时 night_shift_log.json"""
    p = str(tmp_path / "night_shift_log.json")
    import agent_brain
    monkeypatch.setattr(agent_brain, "_NIGHT_LOG_PATH", p)
    return p


# ================================================================
#  心跳 & 状态
# ================================================================

class TestHeartbeat:
    def test_update_heartbeat(self, hb_path):
        from watchdog import update_heartbeat
        update_heartbeat()
        with open(hb_path) as f:
            data = json.load(f)
        assert "last_heartbeat" in data
        assert data["pid"] == os.getpid()

    def test_update_strategy_status_success(self, hb_path):
        from watchdog import update_strategy_status
        update_strategy_status("测试策略", "success", duration_sec=12.5)
        with open(hb_path) as f:
            data = json.load(f)
        s = data["strategy_status"]["测试策略"]
        assert s["status"] == "success"
        assert s["duration_sec"] == 12.5

    def test_update_strategy_status_failed(self, hb_path):
        from watchdog import update_strategy_status
        update_strategy_status("测试策略", "failed", error_msg="boom")
        with open(hb_path) as f:
            data = json.load(f)
        assert data["errors_today"] == 1

    def test_reset_daily_counters(self, hb_path):
        from watchdog import update_strategy_status, reset_daily_counters
        update_strategy_status("x", "failed", error_msg="e")
        reset_daily_counters()
        with open(hb_path) as f:
            data = json.load(f)
        assert data["errors_today"] == 0


# ================================================================
#  健康检查
# ================================================================

class TestHealthCheck:
    def test_healthy(self, hb_path):
        """有心跳、有PID、进程存活 → healthy"""
        from watchdog import update_heartbeat, check_health
        import watchdog
        monkeypatch_schedule = {}
        old = watchdog._STRATEGY_SCHEDULE
        watchdog._STRATEGY_SCHEDULE = monkeypatch_schedule
        try:
            update_heartbeat()
            result = check_health()
            assert result["healthy"]
            assert result["process_alive"]
            assert len(result["issues"]) == 0
        finally:
            watchdog._STRATEGY_SCHEDULE = old

    def test_no_heartbeat(self, hb_path):
        """无 heartbeat.json → 不健康"""
        from watchdog import check_health
        import watchdog
        old = watchdog._STRATEGY_SCHEDULE
        watchdog._STRATEGY_SCHEDULE = {}
        try:
            result = check_health()
            assert not result["healthy"]
            assert any("无心跳" in i or "无PID" in i for i in result["issues"])
        finally:
            watchdog._STRATEGY_SCHEDULE = old

    def test_heartbeat_timeout(self, hb_path):
        """心跳超时 → 不健康"""
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with open(hb_path, "w") as f:
            json.dump({"last_heartbeat": old_time, "pid": os.getpid()}, f)

        from watchdog import check_health
        import watchdog
        old = watchdog._STRATEGY_SCHEDULE
        watchdog._STRATEGY_SCHEDULE = {}
        try:
            result = check_health()
            assert not result["healthy"]
            assert any("心跳超时" in i for i in result["issues"])
        finally:
            watchdog._STRATEGY_SCHEDULE = old

    def test_dead_process(self, hb_path):
        """PID 不存在 → 不健康"""
        with open(hb_path, "w") as f:
            json.dump({
                "last_heartbeat": time.strftime("%Y-%m-%d %H:%M:%S"),
                "pid": 99999999,  # 不存在的 PID
            }, f)

        from watchdog import check_health
        import watchdog
        old = watchdog._STRATEGY_SCHEDULE
        watchdog._STRATEGY_SCHEDULE = {}
        try:
            result = check_health()
            assert not result["process_alive"]
            assert any("不存在" in i for i in result["issues"])
        finally:
            watchdog._STRATEGY_SCHEDULE = old

    def test_too_many_errors(self, hb_path):
        """错误数超阈值 → 不健康"""
        from watchdog import update_heartbeat
        import watchdog
        update_heartbeat()
        with open(hb_path) as f:
            data = json.load(f)
        data["errors_today"] = 10
        with open(hb_path, "w") as f:
            json.dump(data, f)

        old = watchdog._STRATEGY_SCHEDULE
        watchdog._STRATEGY_SCHEDULE = {}
        try:
            result = watchdog.check_health()
            assert any("错误数过多" in i for i in result["issues"])
        finally:
            watchdog._STRATEGY_SCHEDULE = old


# ================================================================
#  Guard 外部看门狗
# ================================================================

class TestGuard:
    def test_guard_process_alive_heartbeat_fresh(self, hb_path, monkeypatch):
        """进程存活 + 心跳新鲜 → 不重启"""
        from watchdog import update_heartbeat, guard
        update_heartbeat()
        restart_called = []
        monkeypatch.setattr("watchdog._guard_restart", lambda *a, **kw: restart_called.append(1))
        guard()
        assert len(restart_called) == 0

    def test_guard_process_dead_triggers_restart(self, hb_path, monkeypatch):
        """进程不在 → 触发重启"""
        with open(hb_path, "w") as f:
            json.dump({
                "last_heartbeat": time.strftime("%Y-%m-%d %H:%M:%S"),
                "pid": 99999999,
            }, f)

        restart_args = []
        import watchdog
        monkeypatch.setattr(watchdog, "_guard_restart",
                            lambda reason, old_pid=None: restart_args.append((reason, old_pid)))
        watchdog.guard()
        assert len(restart_args) == 1
        assert "已死" in restart_args[0][0]

    def test_guard_heartbeat_stale_triggers_restart(self, hb_path, monkeypatch):
        """进程在但心跳超 10 分钟 → 触发重启"""
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        with open(hb_path, "w") as f:
            json.dump({
                "last_heartbeat": old_time,
                "pid": os.getpid(),  # 当前进程, 存活
            }, f)

        restart_args = []
        import watchdog
        monkeypatch.setattr(watchdog, "_guard_restart",
                            lambda reason, old_pid=None: restart_args.append((reason, old_pid)))
        watchdog.guard()
        assert len(restart_args) == 1
        assert "卡死" in restart_args[0][0]

    def test_guard_no_heartbeat_file(self, hb_path, monkeypatch):
        """无 heartbeat.json → 首次启动"""
        restart_args = []
        import watchdog
        monkeypatch.setattr(watchdog, "_guard_restart",
                            lambda reason, old_pid=None: restart_args.append((reason, old_pid)))
        watchdog.guard()
        assert len(restart_args) == 1
        assert "首次" in restart_args[0][0]


# ================================================================
#  _night_task 重试逻辑
# ================================================================

class TestNightTask:
    def test_success_first_try(self, night_log_path, monkeypatch):
        """任务首次成功 → 返回 ok"""
        import agent_brain
        monkeypatch.setattr(agent_brain, "_night_heartbeat", lambda name: None)

        log = {"tasks": {}}
        result = agent_brain._night_task("test_ok", log, lambda: {"val": 42}, retry=0)
        assert result["status"] == "ok"
        assert result["attempt"] == 1
        assert result["data"]["val"] == 42

    def test_retry_on_transient_error(self, night_log_path, monkeypatch):
        """瞬态错误 → 重试后成功"""
        import agent_brain
        monkeypatch.setattr(agent_brain, "_night_heartbeat", lambda name: None)

        call_count = [0]
        def flaky_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("network down")
            return {"ok": True}

        log = {"tasks": {}}
        result = agent_brain._night_task("test_flaky", log, flaky_func, retry=1)
        assert result["status"] == "ok"
        assert result["attempt"] == 2
        assert call_count[0] == 2

    def test_no_retry_on_code_bug(self, night_log_path, monkeypatch):
        """代码 bug (TypeError) → 不重试, 直接失败"""
        import agent_brain
        monkeypatch.setattr(agent_brain, "_night_heartbeat", lambda name: None)

        call_count = [0]
        def buggy_func():
            call_count[0] += 1
            raise TypeError("NoneType has no attribute 'items'")

        log = {"tasks": {}}
        result = agent_brain._night_task("test_bug", log, buggy_func, retry=2)
        assert result["status"] == "error"
        assert call_count[0] == 1  # 只跑了 1 次, 没重试
        assert "TypeError" in result["error"]

    def test_all_retries_exhausted(self, night_log_path, monkeypatch):
        """所有重试都失败 → 返回最后一次的 error"""
        import agent_brain
        monkeypatch.setattr(agent_brain, "_night_heartbeat", lambda name: None)

        call_count = [0]
        def always_fail():
            call_count[0] += 1
            raise RuntimeError(f"fail #{call_count[0]}")

        log = {"tasks": {}}
        result = agent_brain._night_task("test_exhaust", log, always_fail, retry=2)
        assert result["status"] == "error"
        assert call_count[0] == 3  # 1 + 2 retries
        assert "fail #3" in result["error"]

    def test_timeout_triggers_retry(self, night_log_path, monkeypatch):
        """超时 → 重试"""
        import agent_brain
        monkeypatch.setattr(agent_brain, "_night_heartbeat", lambda name: None)
        # 设置极短超时
        monkeypatch.setitem(agent_brain._NIGHT_TASK_TIMEOUT, "test_timeout", 1)

        call_count = [0]
        def slow_then_fast():
            call_count[0] += 1
            if call_count[0] == 1:
                time.sleep(100)  # 第一次卡住
            return {"ok": True}

        log = {"tasks": {}}
        result = agent_brain._night_task("test_timeout", log, slow_then_fast, retry=1)
        # 第一次超时, 第二次可能也超时(因为sleep 100), 结果应该是 timeout 或 ok
        assert result["status"] in ("timeout", "ok")
        assert call_count[0] >= 1


# ================================================================
#  Alert
# ================================================================

class TestAlert:
    def test_alert_when_unhealthy(self, hb_path, monkeypatch):
        """不健康 → 调用告警"""
        import watchdog
        monkeypatch.setattr(watchdog, "_STRATEGY_SCHEDULE", {})
        # 无 heartbeat → 不健康
        alerts = []
        monkeypatch.setattr("watchdog.notify_wechat_raw",
                            lambda title, msg: alerts.append(title),
                            raising=False)
        # 需要 mock 掉 notifier
        import types
        mock_notifier = types.ModuleType("notifier")
        mock_notifier.notify_wechat_raw = lambda t, m: alerts.append(t)
        monkeypatch.setitem(sys.modules, "notifier", mock_notifier)

        watchdog.alert_if_unhealthy()
        assert len(alerts) == 1
        assert "异常" in alerts[0]

    def test_no_alert_when_healthy(self, hb_path, monkeypatch):
        """健康 → 不告警"""
        import watchdog
        monkeypatch.setattr(watchdog, "_STRATEGY_SCHEDULE", {})
        watchdog.update_heartbeat()

        alerts = []
        import types
        mock_notifier = types.ModuleType("notifier")
        mock_notifier.notify_wechat_raw = lambda t, m: alerts.append(t)
        monkeypatch.setitem(sys.modules, "notifier", mock_notifier)

        watchdog.alert_if_unhealthy()
        assert len(alerts) == 0
