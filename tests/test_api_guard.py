"""
API 防封机制测试
===============
测试 RateLimiter / CircuitBreaker / DataCache / guarded_call / smart_retry
"""

import sys
import os
import time
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_guard import (
    RateLimiter, CircuitBreaker, CircuitState, DataCache,
    guarded_call, guarded_sina_request, cached_pool,
    get_api_stats, reset_daily_stats,
    smart_retry, _is_rate_limit_error,
    _global_limiter, _global_breaker, _global_cache,
)


class TestRateLimiter(unittest.TestCase):
    """令牌桶限速器测试"""

    def test_burst_allows_immediate(self):
        """burst 内的请求应立即通过"""
        rl = RateLimiter(max_rpm=60, burst=5)
        for _ in range(5):
            self.assertTrue(rl.acquire(timeout=0.1))

    def test_burst_exceeded_blocks(self):
        """超过 burst 后应阻塞/超时"""
        import tempfile, os
        rl = RateLimiter(max_rpm=6, burst=1)  # 0.1 token/s, 补充极慢
        # 用临时锁文件避免文件锁sleep干扰
        rl._lock_path = os.path.join(tempfile.mkdtemp(), ".rate_lock_test")
        rl._min_interval = 0
        rl.acquire(timeout=1.0)  # 消耗唯一1个令牌
        # 第2次应该超时 (0.1 token/s × 0.05s = 0.005, 远不够1个令牌)
        self.assertFalse(rl.acquire(timeout=0.05))

    def test_tokens_refill(self):
        """令牌应随时间恢复"""
        rl = RateLimiter(max_rpm=600, burst=2)  # 10/s
        for _ in range(2):
            rl.acquire(timeout=0.1)
        time.sleep(0.15)  # wait for refill
        self.assertTrue(rl.acquire(timeout=0.1))

    def test_thread_safety(self):
        """多线程并发不应丢失令牌"""
        rl = RateLimiter(max_rpm=6000, burst=100)
        results = []

        def worker():
            results.append(rl.acquire(timeout=1.0))

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 50)
        self.assertTrue(all(results))


class TestCircuitBreaker(unittest.TestCase):
    """断路器测试"""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_sec=1)
        self.assertEqual(cb.get_state("test"), "closed")
        self.assertTrue(cb.allow("test"))

    def test_open_after_threshold(self):
        """连续失败达阈值 → OPEN"""
        cb = CircuitBreaker(failure_threshold=3, cooldown_sec=60)
        for _ in range(3):
            cb.record_failure("src")
        self.assertEqual(cb.get_state("src"), "open")
        self.assertFalse(cb.allow("src"))

    def test_half_open_after_cooldown(self):
        """冷却期后 → HALF_OPEN → 允许一次探测"""
        cb = CircuitBreaker(failure_threshold=2, cooldown_sec=0.1)
        cb.record_failure("src")
        cb.record_failure("src")
        self.assertFalse(cb.allow("src"))
        time.sleep(0.15)
        self.assertTrue(cb.allow("src"))  # HALF_OPEN 探测
        self.assertEqual(cb.get_state("src"), "half_open")

    def test_half_open_success_closes(self):
        """HALF_OPEN 成功 → CLOSED"""
        cb = CircuitBreaker(failure_threshold=2, cooldown_sec=0.1)
        cb.record_failure("src")
        cb.record_failure("src")
        time.sleep(0.15)
        cb.allow("src")  # transition to HALF_OPEN
        cb.record_success("src")
        self.assertEqual(cb.get_state("src"), "closed")

    def test_half_open_failure_reopens(self):
        """HALF_OPEN 再次失败 → OPEN"""
        cb = CircuitBreaker(failure_threshold=2, cooldown_sec=0.1)
        cb.record_failure("src")
        cb.record_failure("src")
        time.sleep(0.15)
        cb.allow("src")  # HALF_OPEN
        cb.record_failure("src")
        self.assertEqual(cb.get_state("src"), "open")

    def test_independent_sources(self):
        """不同源的断路器独立"""
        cb = CircuitBreaker(failure_threshold=2, cooldown_sec=60)
        cb.record_failure("a")
        cb.record_failure("a")
        self.assertFalse(cb.allow("a"))
        self.assertTrue(cb.allow("b"))  # b 不受 a 影响


class TestDataCache(unittest.TestCase):
    """TTL 缓存测试"""

    def test_set_and_get(self):
        cache = DataCache()
        cache.set("k1", "value1", 10)
        self.assertEqual(cache.get("k1"), "value1")

    def test_ttl_expiry(self):
        cache = DataCache()
        cache.set("k1", "value1", 0.1)
        time.sleep(0.15)
        self.assertIsNone(cache.get("k1"))

    def test_cache_miss(self):
        cache = DataCache()
        self.assertIsNone(cache.get("nonexistent"))

    def test_clear(self):
        cache = DataCache()
        cache.set("k1", "v1", 10)
        cache.set("k2", "v2", 10)
        cache.clear()
        self.assertIsNone(cache.get("k1"))
        self.assertIsNone(cache.get("k2"))

    def test_size(self):
        cache = DataCache()
        cache.set("k1", "v1", 10)
        cache.set("k2", "v2", 10)
        self.assertEqual(cache.size(), 2)


class TestSmartRetry(unittest.TestCase):
    """智能重试测试"""

    def test_success_first_try(self):
        result = smart_retry(lambda: 42, source="test", retries=3)
        self.assertEqual(result, 42)

    def test_success_after_retry(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("网络错误")
            return "ok"

        result = smart_retry(flaky, source="test_flaky", retries=3)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)

    def test_all_retries_exhausted(self):
        def always_fail():
            raise ValueError("always")

        with self.assertRaises(ValueError):
            smart_retry(always_fail, source="test_fail", retries=2)

    def test_rate_limit_detection(self):
        self.assertTrue(_is_rate_limit_error(RuntimeError("HTTP 403")))
        self.assertTrue(_is_rate_limit_error(RuntimeError("429 Too Many Requests")))
        self.assertTrue(_is_rate_limit_error(RuntimeError("rate limit exceeded")))
        self.assertFalse(_is_rate_limit_error(RuntimeError("timeout")))
        self.assertFalse(_is_rate_limit_error(ConnectionError("refused")))


class TestGuardedCall(unittest.TestCase):
    """主 API 入口测试"""

    def test_basic_call(self):
        result = guarded_call(lambda x: x * 2, 21, source="test")
        self.assertEqual(result, 42)

    def test_cache_hit(self):
        """缓存命中应返回缓存值"""
        call_count = [0]

        def counter():
            call_count[0] += 1
            return "data"

        _global_cache.clear()
        r1 = guarded_call(counter, source="test", cache_key="ck", cache_ttl=60)
        r2 = guarded_call(counter, source="test", cache_key="ck", cache_ttl=60)
        self.assertEqual(r1, "data")
        self.assertEqual(r2, "data")
        self.assertEqual(call_count[0], 1)  # 只调用一次

    def test_circuit_break_raises(self):
        """断路器熔断应抛异常"""
        # 手动触发熔断 (阈值从config动态读取)
        threshold = _global_breaker.failure_threshold
        for _ in range(threshold):
            _global_breaker.record_failure("test_break_src")
        with self.assertRaises(RuntimeError) as ctx:
            guarded_call(lambda: None, source="test_break_src")
        self.assertIn("断路器", str(ctx.exception))
        # 清理
        _global_breaker.record_success("test_break_src")


class TestStats(unittest.TestCase):
    """统计测试"""

    def test_reset(self):
        reset_daily_stats()
        stats = get_api_stats()
        self.assertEqual(stats["total_calls"], 0)
        self.assertEqual(stats["cache_hits"], 0)


if __name__ == "__main__":
    unittest.main()
