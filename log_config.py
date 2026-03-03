"""
集中日志配置
============
- 控制台输出 (INFO 级别, 保持现有 print 风格)
- 文件轮转 (DEBUG 级别, 5MB × 3 个备份)
- 每个模块独立日志文件 + 汇总日志

用法:
    from log_config import get_logger
    logger = get_logger("scheduler")
    logger.info("策略运行完成")
    logger.error("获取数据失败", exc_info=True)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_DIR, "logs")

# 确保日志目录存在
os.makedirs(_LOG_DIR, exist_ok=True)

# 格式
_CONSOLE_FMT = logging.Formatter(
    "  [%(name)s] %(message)s"
)
_FILE_FMT = logging.Formatter(
    "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 汇总文件 handler (所有模块共用)
_combined_handler: RotatingFileHandler | None = None


def _get_combined_handler() -> RotatingFileHandler:
    global _combined_handler
    if _combined_handler is None:
        _combined_handler = RotatingFileHandler(
            os.path.join(_LOG_DIR, "quant_all.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
            delay=True,  # 延迟打开, 避免 Python 3.9 shutdown 时 NameError
        )
        _combined_handler.setLevel(logging.DEBUG)
        _combined_handler.setFormatter(_FILE_FMT)
    return _combined_handler


def get_logger(name: str) -> logging.Logger:
    """获取模块专属 logger

    自动配置:
      - 控制台 StreamHandler (INFO)
      - 模块文件 RotatingFileHandler (DEBUG, 5MB×3)
      - 汇总文件 RotatingFileHandler (DEBUG, 10MB×5)
    """
    logger = logging.getLogger(f"quant.{name}")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不传播到 root logger

    # 1. 控制台
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(_CONSOLE_FMT)
    logger.addHandler(ch)

    # 2. 模块独立文件
    fh = RotatingFileHandler(
        os.path.join(_LOG_DIR, f"{name}.log"),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
        delay=True,  # 延迟打开, 避免 shutdown NameError
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_FILE_FMT)
    logger.addHandler(fh)

    # 3. 汇总文件
    logger.addHandler(_get_combined_handler())

    return logger
