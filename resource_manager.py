"""
全局资源管理器
=============
单例模式管理线程池, 防止信号量泄漏和资源枯竭。

用法:
    from resource_manager import get_pool, submit_parallel

    # 获取共享线程池 (同名返回同实例)
    pool = get_pool("strategy_scan", max_workers=20)
    future = pool.submit(some_func, arg1, arg2)

    # 并行执行快捷方式 (自动收集结果)
    results = submit_parallel("scan", func, items, max_workers=10, timeout=60)
"""

from __future__ import annotations

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed

from log_config import get_logger

logger = get_logger("resource_manager")

# 全系统并发上限 (防止线程爆炸)
_GLOBAL_MAX_WORKERS = 50


class ResourceManager:
    """线程池单例管理器"""

    _instance: ResourceManager | None = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pools: dict[str, ThreadPoolExecutor] = {}
                    cls._instance._pool_lock = threading.Lock()
                    cls._instance._total_workers = 0
                    atexit.register(cls._instance.shutdown_all)
        return cls._instance

    def get_pool(self, name: str, max_workers: int = 10) -> ThreadPoolExecutor:
        """获取命名线程池 (已存在则复用)"""
        with self._pool_lock:
            if name in self._pools:
                pool = self._pools[name]
                if not pool._broken:
                    return pool
                # 池已损坏, 重建
                del self._pools[name]

            # 限制总并发
            actual = min(max_workers, max(1, _GLOBAL_MAX_WORKERS - self._total_workers))
            if actual < max_workers:
                logger.warning("线程池 %s 请求 %d workers, 实际分配 %d (全局上限 %d)",
                               name, max_workers, actual, _GLOBAL_MAX_WORKERS)

            pool = ThreadPoolExecutor(
                max_workers=actual,
                thread_name_prefix=f"quant-{name}",
            )
            self._pools[name] = pool
            self._total_workers += actual
            logger.debug("创建线程池: %s (workers=%d, 全局总=%d)",
                         name, actual, self._total_workers)
            return pool

    def shutdown_all(self):
        """关闭所有线程池, 取消挂起任务"""
        with self._pool_lock:
            for name, pool in self._pools.items():
                try:
                    pool.shutdown(wait=False, cancel_futures=True)
                    logger.debug("关闭线程池: %s", name)
                except TypeError:
                    # Python 3.8 不支持 cancel_futures
                    pool.shutdown(wait=False)
                except Exception as e:
                    logger.warning("关闭线程池 %s 异常: %s", name, e)
            self._pools.clear()
            self._total_workers = 0

    def stats(self) -> dict:
        """获取资源统计"""
        with self._pool_lock:
            return {
                "pools": list(self._pools.keys()),
                "total_workers": self._total_workers,
                "pool_count": len(self._pools),
            }


# 模块级便捷函数
_manager = ResourceManager()


def get_pool(name: str, max_workers: int = 10) -> ThreadPoolExecutor:
    """获取命名线程池"""
    return _manager.get_pool(name, max_workers)


def submit_parallel(pool_name: str, func, items, max_workers: int = 10,
                    timeout: float = 120) -> list:
    """并行执行 func(item) 对每个 item, 收集非 None 结果

    Args:
        pool_name: 线程池名称
        func: 要并行执行的函数
        items: 可迭代参数列表
        max_workers: 最大并发数
        timeout: 单个 Future 超时 (秒)

    Returns:
        成功结果列表 (跳过异常和 None)
    """
    pool = get_pool(pool_name, max_workers)
    futures: dict[Future, any] = {}
    for item in items:
        f = pool.submit(func, item)
        futures[f] = item

    results = []
    for f in as_completed(futures, timeout=timeout):
        try:
            result = f.result(timeout=5)
            if result is not None:
                results.append(result)
        except Exception as e:
            item = futures[f]
            logger.debug("并行任务异常 [%s] %s: %s", pool_name, item, e)

    return results


def get_stats() -> dict:
    """获取资源管理器统计"""
    return _manager.stats()
