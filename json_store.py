"""
JSON 安全存储
=============
- fcntl.flock 文件锁防止并发读写
- 原子写入 (先写 .tmp 再 rename) 防止写入中断导致损坏
- safe_load / safe_load_strict 双模式
- safe_save 写前校验

用法:
    from json_store import safe_load, safe_save, safe_load_strict
    data = safe_load("positions.json")           # 宽容模式
    data = safe_load_strict("positions.json")    # 严格模式: 损坏则抛异常
    safe_save("positions.json", data)             # 原子写入
"""

from __future__ import annotations

import fcntl
import json
import os
import traceback
from typing import Union

try:
    from log_config import get_logger
    logger = get_logger("json_store")
except ImportError:
    import logging
    logger = logging.getLogger("json_store")

# 核心文件: safe_load_strict 默认保护的文件名
_CRITICAL_FILES = {
    "positions.json", "paper_portfolio.json", "agent_memory.json",
    "config.py", "scorecard.json",
}


def safe_load(path: str, default: Union[list, dict, None] = None) -> Union[list, dict]:
    """安全加载 JSON 文件 (共享锁, 宽容模式)

    Args:
        path: JSON 文件路径
        default: 文件不存在或解析失败时的默认值, None 则自动推断为 []
    Returns:
        解析后的 list 或 dict
    """
    if default is None:
        default = []

    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # 共享读锁
            try:
                content = f.read()
                if not content.strip():
                    return default
                return json.loads(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError as e:
        logger.error("JSON解析失败: %s — %s\n%s", path, e, traceback.format_exc())
        return default
    except (IOError, OSError) as e:
        logger.error("IO异常: %s — %s\n%s", path, e, traceback.format_exc())
        return default


def safe_load_strict(path: str, default: Union[list, dict, None] = None) -> Union[list, dict]:
    """严格模式加载 JSON: 文件存在但损坏时抛出异常, 防止空数据掩盖损坏

    适用场景: positions.json / paper_portfolio.json 等核心文件
    文件不存在: 返回 default (正常情况)
    文件存在但损坏: 抛出 ValueError
    """
    if default is None:
        default = []

    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                content = f.read()
                if not content.strip():
                    # 空文件视为正常 (刚创建)
                    return default
                return json.loads(content)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except json.JSONDecodeError as e:
        logger.error("严格模式: JSON损坏, 拒绝返回默认值: %s — %s", path, e)
        raise ValueError(f"核心文件损坏, 拒绝静默降级: {path} — {e}") from e
    except (IOError, OSError) as e:
        logger.error("严格模式: IO异常: %s — %s", path, e)
        raise ValueError(f"核心文件读取失败: {path} — {e}") from e


def safe_save(path: str, data: Union[list, dict]):
    """安全保存 JSON 文件 (排他锁 + 原子写入 + 写前校验)

    流程:
      1. 校验 data 合法性
      2. 写入 path.tmp (排他锁)
      3. os.replace 原子替换 (POSIX rename 保证原子性)
    """
    # 写前校验: 防止 None/非法类型写入
    if data is None:
        logger.error("safe_save 拒绝写入 None: %s", path)
        raise TypeError(f"拒绝将 None 写入 {path}")
    if not isinstance(data, (list, dict)):
        logger.error("safe_save 拒绝写入非法类型 %s: %s", type(data).__name__, path)
        raise TypeError(f"拒绝将 {type(data).__name__} 写入 {path}, 只接受 list/dict")

    tmp_path = path + ".tmp"
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # 排他写锁
            try:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # 确保写入磁盘
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp_path, path)  # 原子替换
    except Exception:
        # 清理临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
