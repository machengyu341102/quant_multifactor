"""
API 防封机制
===========
集中式速率限制 + 断路器 + 智能重试 + 缓存 + 动态源负载均衡
防止 API 被封禁 (403/429), 消除冗余调用

组件:
  1. RateLimiter  — 令牌桶, 全局 40 rpm, burst 10
  2. CircuitBreaker — 按源分组, 连续5次失败 → 熔断120s
  3. smart_retry  — 限流vs网络错误区分退避
  4. DataCache    — TTL缓存, CSI1000 1小时 / 日K 5分钟
  5. SourceHealth — 每个 API 源独立健康追踪 (延迟/成功率/状态)
  6. smart_source — 优先级自动切换, 主源挂了自动降级备用源
"""

import time
import threading
from enum import Enum
from datetime import datetime

try:
    from config import API_GUARD_PARAMS
except ImportError:
    API_GUARD_PARAMS = {
        "enabled": True, "max_rpm": 40, "burst": 10,
        "circuit_failure_threshold": 5, "circuit_cooldown_sec": 120,
        "pool_cache_ttl_sec": 3600, "daily_kline_cache_ttl_sec": 300,
    }


# ================================================================
#  统计
# ================================================================

_stats = {
    "total_calls": 0,
    "cache_hits": 0,
    "retries": 0,
    "circuit_breaks": 0,
    "rate_limited": 0,
    "errors": 0,
    "reset_date": datetime.now().strftime("%Y-%m-%d"),
}
_stats_lock = threading.Lock()


def get_api_stats() -> dict:
    with _stats_lock:
        return dict(_stats)


def reset_daily_stats():
    with _stats_lock:
        _stats["total_calls"] = 0
        _stats["cache_hits"] = 0
        _stats["retries"] = 0
        _stats["circuit_breaks"] = 0
        _stats["rate_limited"] = 0
        _stats["errors"] = 0
        _stats["reset_date"] = datetime.now().strftime("%Y-%m-%d")


# ================================================================
#  RateLimiter (令牌桶)
# ================================================================

class RateLimiter:
    """跨进程令牌桶限速器 (文件锁协调)

    通过文件记录全局调用时间戳, 实现多进程共享限速。
    同一进程内用 threading.Lock, 跨进程用 fcntl 文件锁。
    """

    def __init__(self, max_rpm: int = 40, burst: int = 10):
        self.max_rpm = max_rpm
        self.burst = burst
        self.tokens = float(burst)
        self.rate = max_rpm / 60.0  # tokens per second
        self.last_time = time.monotonic()
        self._lock = threading.Lock()
        # 跨进程文件锁
        import os
        self._lock_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".api_rate_lock")
        self._min_interval = 1.0 / self.rate  # 两次调用最小间隔

    def acquire(self, timeout: float = 30.0) -> bool:
        """获取一个令牌, 阻塞直到可用或超时"""
        import fcntl, os
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_time
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_time = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    # 跨进程协调: 文件锁 + 最小间隔
                    try:
                        fd = os.open(self._lock_path,
                                     os.O_CREAT | os.O_RDWR, 0o644)
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # 读取上次调用时间
                        try:
                            raw = os.read(fd, 32)
                            last_ts = float(raw) if raw else 0
                        except (ValueError, OSError):
                            last_ts = 0
                        wall_now = time.time()
                        gap = wall_now - last_ts
                        if gap < self._min_interval:
                            time.sleep(self._min_interval - gap)
                        # 写入当前时间
                        os.lseek(fd, 0, os.SEEK_SET)
                        os.ftruncate(fd, 0)
                        os.write(fd, str(time.time()).encode())
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                    except (BlockingIOError, OSError):
                        # 拿不到文件锁, 短暂等待后重试
                        try:
                            os.close(fd)
                        except Exception:
                            pass
                        time.sleep(0.05)
                        continue
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


_global_limiter = RateLimiter(
    max_rpm=API_GUARD_PARAMS.get("max_rpm", 40),
    burst=API_GUARD_PARAMS.get("burst", 10),
)


# ================================================================
#  CircuitBreaker (断路器)
# ================================================================

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """按源分组的断路器"""

    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 120):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._circuits: dict = {}  # source -> state dict
        self._lock = threading.Lock()

    def _get(self, source: str) -> dict:
        if source not in self._circuits:
            self._circuits[source] = {
                "state": CircuitState.CLOSED,
                "failures": 0,
                "last_failure": 0.0,
            }
        return self._circuits[source]

    def allow(self, source: str) -> bool:
        with self._lock:
            c = self._get(source)
            if c["state"] == CircuitState.CLOSED:
                return True
            if c["state"] == CircuitState.OPEN:
                if time.monotonic() - c["last_failure"] >= self.cooldown_sec:
                    c["state"] = CircuitState.HALF_OPEN
                    return True
                return False
            # HALF_OPEN: allow one probe
            return True

    def record_success(self, source: str):
        with self._lock:
            c = self._get(source)
            c["failures"] = 0
            c["state"] = CircuitState.CLOSED

    def record_failure(self, source: str):
        with self._lock:
            c = self._get(source)
            c["failures"] += 1
            c["last_failure"] = time.monotonic()
            if c["state"] == CircuitState.HALF_OPEN:
                c["state"] = CircuitState.OPEN
            elif c["failures"] >= self.failure_threshold:
                c["state"] = CircuitState.OPEN

    def get_state(self, source: str) -> str:
        with self._lock:
            c = self._get(source)
            return c["state"].value


_global_breaker = CircuitBreaker(
    failure_threshold=API_GUARD_PARAMS.get("circuit_failure_threshold", 5),
    cooldown_sec=API_GUARD_PARAMS.get("circuit_cooldown_sec", 120),
)


# ================================================================
#  DataCache (TTL缓存)
# ================================================================

class DataCache:
    """线程安全的 TTL 缓存 + 高价值数据磁盘持久化

    内存缓存: 所有数据 (快速命中)
    磁盘缓存: TTL >= 300s 的数据 (跨进程共享, 如 csi1000_pool)
    """

    # TTL >= 此阈值的缓存项会写磁盘
    _PERSIST_TTL_THRESHOLD = 300  # 5分钟

    def __init__(self):
        self._store: dict = {}  # key -> (value, expire_time)
        self._lock = threading.Lock()
        import os
        self._disk_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".cache_api.json")

    def get(self, key: str):
        with self._lock:
            # 1. 内存缓存
            if key in self._store:
                value, expire = self._store[key]
                if time.monotonic() < expire:
                    return value
                del self._store[key]

        # 2. 磁盘缓存 (跨进程共享)
        disk_val = self._disk_get(key)
        if disk_val is not None:
            return disk_val

        return None

    def set(self, key: str, value, ttl_sec: float):
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_sec)

        # 高价值数据写磁盘 (跨进程)
        if ttl_sec >= self._PERSIST_TTL_THRESHOLD:
            self._disk_set(key, value, ttl_sec)

    def clear(self):
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (_, exp) in self._store.items() if now >= exp]
            for k in expired:
                del self._store[k]
            return len(self._store)

    def _disk_get(self, key: str):
        """从磁盘缓存读取 (fcntl 共享锁)"""
        import fcntl, json, os
        import pandas as pd
        if not os.path.exists(self._disk_path):
            return None
        try:
            with open(self._disk_path, "r", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    store = json.loads(f.read())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            entry = store.get(key)
            if entry and time.time() < entry.get("expire_ts", 0):
                val = entry["value"]
                # 类型恢复
                type_tag = entry.get("type_tag")
                if type_tag == "dataframe":
                    val = pd.DataFrame(val)
                elif type_tag == "set":
                    val = set(val)
                elif type_tag == "tuple":
                    # 递归恢复 tuple 中的元素 (处理 cached_pool 返回 (set, dict))
                    recovered = []
                    for item in val:
                        if isinstance(item, list) and len(item) > 0 and isinstance(item[0], str) and key == "csi1000_pool":
                            # 启发式判断: csi1000_pool 的第一个元素是 set(list)
                            recovered.append(set(item))
                        else:
                            recovered.append(item)
                    val = tuple(recovered)

                # 回填内存缓存
                remain = entry["expire_ts"] - time.time()
                with self._lock:
                    self._store[key] = (val, time.monotonic() + remain)
                return val
        except Exception:
            pass
        return None

    def _disk_set(self, key: str, value, ttl_sec: float):
        """写磁盘缓存 (fcntl 排他锁, 原子写入)"""
        import fcntl, json, os
        import pandas as pd

        type_tag = "json"
        serializable_val = value

        try:
            if isinstance(value, pd.DataFrame):
                type_tag = "dataframe"
                serializable_val = value.to_dict(orient="records")
            elif isinstance(value, set):
                type_tag = "set"
                serializable_val = list(value)
            elif isinstance(value, tuple):
                type_tag = "tuple"
                # 处理 cached_pool 返回的 (set, dict)
                serializable_val = []
                for item in value:
                    if isinstance(item, set):
                        serializable_val.append(list(item))
                    else:
                        serializable_val.append(item)

            # 校验是否可序列化
            json.dumps(serializable_val, ensure_ascii=False)
        except (TypeError, ValueError):
            return  # 依然不可序列化的跳过

        try:
            # 读已有缓存
            store = {}
            if os.path.exists(self._disk_path):
                try:
                    with open(self._disk_path, "r", encoding="utf-8") as f:
                        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                        try:
                            store = json.loads(f.read())
                        finally:
                            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    store = {}

            # 清理过期项
            now = time.time()
            store = {k: v for k, v in store.items()
                     if isinstance(v, dict) and v.get("expire_ts", 0) > now}

            # 写入新项
            store[key] = {
                "value": serializable_val, 
                "expire_ts": now + ttl_sec,
                "type_tag": type_tag
            }

            tmp = self._disk_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(store, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            os.replace(tmp, self._disk_path)
        except Exception:
            pass
  # 磁盘缓存是优化, 失败不影响主流程


_global_cache = DataCache()


# ================================================================
#  源健康追踪 (SourceHealth)
# ================================================================

# 标准源标识 — 每个逻辑 API 端点一个独立断路器
SOURCE_TENCENT_KLINE = "tencent_kline"   # ak.stock_zh_a_hist_tx
SOURCE_EM_KLINE = "em_kline"             # ak.stock_zh_a_hist
SOURCE_EM_SPOT = "em_spot"               # ak.stock_zh_a_spot_em
SOURCE_EM_MISC = "em_misc"               # fund_flow, lhb, financials
SOURCE_SINA_HTTP = "sina_http"           # hq.sinajs.cn batch quotes
SOURCE_SINA_FUTURES = "sina_futures"     # ak.futures_main_sina
SOURCE_SINA_CALENDAR = "sina_calendar"   # ak.tool_trade_date_hist_sina
SOURCE_AKSHARE_POOL = "akshare_pool"    # ak.index_stock_cons_*
SOURCE_BINANCE = "binance"               # api.binance.com
SOURCE_YFINANCE = "yfinance"             # yfinance lib
SOURCE_TUSHARE = "tushare"               # tushare pro

# 旧 "akshare" 键映射到默认源 (向后兼容)
_LEGACY_SOURCE = "akshare"


class SourceHealth:
    """每源独立健康追踪: 延迟、成功/失败计数、状态"""

    def __init__(self):
        self._data: dict = {}  # source -> {calls, ok, fail, avg_ms, last_fail_ts}
        self._lock = threading.Lock()

    def _ensure(self, source: str) -> dict:
        if source not in self._data:
            self._data[source] = {
                "calls": 0, "ok": 0, "fail": 0,
                "avg_ms": 0.0, "last_fail_ts": 0.0,
                "last_ok_ts": 0.0,
            }
        return self._data[source]

    def record_call(self, source: str, success: bool, latency_ms: float = 0):
        with self._lock:
            d = self._ensure(source)
            d["calls"] += 1
            if success:
                d["ok"] += 1
                d["last_ok_ts"] = time.time()
                # 指数移动平均延迟
                if d["avg_ms"] == 0:
                    d["avg_ms"] = latency_ms
                else:
                    d["avg_ms"] = d["avg_ms"] * 0.7 + latency_ms * 0.3
            else:
                d["fail"] += 1
                d["last_fail_ts"] = time.time()

    def success_rate(self, source: str) -> float:
        """成功率 0~1, 无数据返回 1.0 (乐观)"""
        with self._lock:
            d = self._ensure(source)
            return d["ok"] / d["calls"] if d["calls"] > 0 else 1.0

    def get_all(self) -> dict:
        """获取所有源健康数据 (dashboard 用)"""
        with self._lock:
            result = {}
            for src, d in self._data.items():
                rate = d["ok"] / d["calls"] if d["calls"] > 0 else 1.0
                result[src] = {
                    "calls": d["calls"],
                    "success_rate": round(rate, 3),
                    "avg_ms": round(d["avg_ms"], 1),
                    "circuit": _global_breaker.get_state(src),
                }
            return result

    def reset(self):
        with self._lock:
            self._data.clear()


_source_health = SourceHealth()


def get_source_health() -> dict:
    """获取所有 API 源健康状态 (供 dashboard / CLI)"""
    return _source_health.get_all()


def smart_source(sources: list, cache_key: str = "", cache_ttl: int = 0):
    """
    优先级自动切换 — 按顺序尝试多个 API 源, 自动跳过熔断源

    Args:
        sources: [(source_key, callable), ...] 优先级从高到低
        cache_key: 缓存键 (空=不缓存)
        cache_ttl: 缓存 TTL 秒

    Returns:
        第一个成功的 callable 返回值

    Raises:
        最后一个源的异常 (全部失败)
    """
    # 1. 查缓存
    if cache_key and cache_ttl > 0:
        cached = _global_cache.get(cache_key)
        if cached is not None:
            with _stats_lock:
                _stats["cache_hits"] += 1
            return cached

    last_exc = None
    for source_key, fn in sources:
        # 跳过已熔断的源
        if not _global_breaker.allow(source_key):
            continue

        # 限速
        if not _global_limiter.acquire(timeout=10):
            continue

        with _stats_lock:
            _stats["total_calls"] += 1

        t0 = time.monotonic()
        try:
            result = fn()
            latency = (time.monotonic() - t0) * 1000
            _global_breaker.record_success(source_key)
            _source_health.record_call(source_key, True, latency)

            # 写缓存
            if cache_key and cache_ttl > 0:
                _global_cache.set(cache_key, result, cache_ttl)
            return result
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            _global_breaker.record_failure(source_key)
            _source_health.record_call(source_key, False, latency)
            with _stats_lock:
                _stats["errors"] += 1
            last_exc = e
            import logging
            logging.getLogger("api_guard").debug(
                "smart_source %s 失败: %s, 尝试下一个源", source_key, e)
            continue

    if last_exc:
        raise last_exc
    raise RuntimeError("所有 API 源均不可用 (全部熔断)")


# ================================================================
#  智能重试
# ================================================================

def _is_rate_limit_error(exc: Exception) -> bool:
    """判断是否为限流/封禁错误"""
    msg = str(exc).lower()
    code_str = str(getattr(exc, 'status_code', '')) or str(getattr(exc, 'code', ''))
    if code_str in ('403', '429'):
        return True
    rate_keywords = ['403', '429', 'rate limit', 'too many', 'forbidden', 'banned', 'blocked']
    return any(kw in msg for kw in rate_keywords)


def smart_retry(func, args=(), kwargs=None, source="akshare", retries=3):
    """智能重试: 限流用指数退避, 网络错误用线性退避"""
    kwargs = kwargs or {}
    last_exc = None

    for attempt in range(retries):
        try:
            result = func(*args, **kwargs)
            _global_breaker.record_success(source)
            return result
        except Exception as e:
            last_exc = e
            _global_breaker.record_failure(source)
            with _stats_lock:
                _stats["retries"] += 1

            if attempt < retries - 1:
                if _is_rate_limit_error(e):
                    # 指数退避: 2, 6, 18s
                    wait = 2 * (3 ** attempt)
                    with _stats_lock:
                        _stats["rate_limited"] += 1
                else:
                    # 线性退避: 2, 4, 6s
                    wait = 2 * (attempt + 1)
                time.sleep(wait)

    raise last_exc


# ================================================================
#  主 API
# ================================================================

def guarded_call(func, *args, source="akshare", retries=3, cache_key="", cache_ttl=0, **func_kwargs):
    """
    带防护的 API 调用入口

    Args:
        func: 要调用的函数
        *args: 函数位置参数
        source: API 源标识 (用于断路器分组)
        retries: 重试次数
        cache_key: 缓存键 (空字符串=不缓存)
        cache_ttl: 缓存 TTL (秒)
        **func_kwargs: 函数关键字参数 (透传给 func)

    Returns:
        func 的返回值

    Raises:
        RuntimeError: 断路器熔断
        原始异常: 重试耗尽
    """
    if not API_GUARD_PARAMS.get("enabled", True):
        return func(*args, **func_kwargs)

    # 1. 查缓存
    if cache_key and cache_ttl > 0:
        cached = _global_cache.get(cache_key)
        if cached is not None:
            with _stats_lock:
                _stats["cache_hits"] += 1
            return cached

    # 2. 断路器检查
    if not _global_breaker.allow(source):
        with _stats_lock:
            _stats["circuit_breaks"] += 1
        raise RuntimeError(f"API断路器已熔断: {source} (状态={_global_breaker.get_state(source)})")

    # 3. 限速
    if not _global_limiter.acquire(timeout=30):
        with _stats_lock:
            _stats["rate_limited"] += 1
        raise RuntimeError("API限速: 获取令牌超时")

    with _stats_lock:
        _stats["total_calls"] += 1

    # 4. 执行 + 智能重试 + 源健康追踪
    t0 = time.monotonic()
    try:
        result = smart_retry(func, args=args, kwargs=func_kwargs, source=source, retries=retries)
        latency = (time.monotonic() - t0) * 1000
        _source_health.record_call(source, True, latency)
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        _source_health.record_call(source, False, latency)
        with _stats_lock:
            _stats["errors"] += 1
        raise

    # 5. 写缓存
    if cache_key and cache_ttl > 0:
        _global_cache.set(cache_key, result, cache_ttl)

    return result


def guarded_sina_request(url: str, headers: dict, timeout: float = 15) -> str:
    """
    带防护的 HTTP GET 请求 (新浪行情专用)

    Returns:
        response.text
    """
    import requests

    if not API_GUARD_PARAMS.get("enabled", True):
        r = requests.get(url, headers=headers, timeout=timeout)
        return r.text

    if not _global_breaker.allow("sina_http"):
        with _stats_lock:
            _stats["circuit_breaks"] += 1
        raise RuntimeError("API断路器已熔断: sina_http")

    if not _global_limiter.acquire(timeout=30):
        with _stats_lock:
            _stats["rate_limited"] += 1
        raise RuntimeError("API限速: 获取令牌超时")

    with _stats_lock:
        _stats["total_calls"] += 1

    def _do_request():
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code in (403, 429):
            raise RuntimeError(f"HTTP {r.status_code}: 限流/封禁")
        r.raise_for_status()
        return r.text

    try:
        result = smart_retry(_do_request, source="sina_http", retries=3)
    except Exception as e:
        with _stats_lock:
            _stats["errors"] += 1
        raise

    return result


def cached_pool():
    """
    带缓存的中证1000成分股获取 (消除冗余调用)

    Returns:
        (pool_set, name_map) — 与 intraday_strategy.get_stock_pool() 格式兼容
    """
    cache_key = "csi1000_pool"
    cache_ttl = API_GUARD_PARAMS.get("pool_cache_ttl_sec", 3600)

    cached = _global_cache.get(cache_key)
    if cached is not None:
        with _stats_lock:
            _stats["cache_hits"] += 1
        return cached

    # 磁盘回退: 跨进程复用 (list→set 转换)
    disk_val = _global_cache._disk_get(cache_key + "_disk")
    if disk_val is not None and isinstance(disk_val, (list, tuple)) and len(disk_val) == 2:
        codes_list, name_map = disk_val
        pool_set = set(codes_list)
        result = (pool_set, name_map)
        _global_cache.set(cache_key, result, cache_ttl)  # 回填内存
        with _stats_lock:
            _stats["cache_hits"] += 1
        return result

    # 实际获取
    import akshare as ak

    try:
        df = guarded_call(
            ak.index_stock_cons_csindex, "000852",
            source=SOURCE_AKSHARE_POOL, retries=3,
        )
        code_col = "成分券代码" if "成分券代码" in df.columns else "品种代码"
        name_col = "成分券名称" if "成分券名称" in df.columns else "品种名称"
        all_codes = df[code_col].astype(str).str.zfill(6).tolist()
        name_map = dict(zip(
            df[code_col].astype(str).str.zfill(6),
            df[name_col]
        ))
    except Exception:
        df = guarded_call(
            ak.index_stock_cons, "000852",
            source=SOURCE_AKSHARE_POOL, retries=3,
        )
        all_codes = df["品种代码"].tolist()
        name_map = dict(zip(df["品种代码"], df["品种名称"]))

    all_codes = [c for c in all_codes if not c.startswith(("688", "8", "4"))]
    all_codes = list(dict.fromkeys(all_codes))
    pool_set = set(all_codes)

    result = (pool_set, name_map)
    # 内存缓存存 set
    _global_cache.set(cache_key, result, cache_ttl)
    # 磁盘缓存额外存 list 版本 (set 不可 JSON 序列化)
    _global_cache._disk_set(cache_key + "_disk", (all_codes, name_map), cache_ttl)
    return result
