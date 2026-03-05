"""
配置校验器
=========
对 strategies.json 等关键配置文件进行 Schema 校验。
启动时自动验证, 阻止无效配置进入系统。

用法:
    from config_validator import validate_strategies

    errors = validate_strategies()  # 返回 [] 表示合法
"""

from __future__ import annotations

import os
from log_config import get_logger

logger = get_logger("config_validator")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================
#  策略配置 Schema
# ================================================================

_VALID_TYPES = {"astock", "direct_push", "interval"}
_VALID_GATE_KEYS = {"trading_day", "agent_check", "regime_check", "circuit_breaker"}
_VALID_PRE_HOOKS = {"clear_ths_watchlist"}


def validate_strategies(path: str = "") -> list[str]:
    """校验 strategies.json, 返回错误列表 (空=合法)

    检查项:
      1. 文件可解析为 JSON 数组
      2. 每个策略有 id/name/module/function/schedule/type
      3. id 唯一
      4. type 在合法范围内
      5. schedule 格式正确 (HH:MM 或 Nmin)
      6. astock 策略必须有 batch_slot
      7. gates 键合法
      8. module 文件存在
    """
    if not path:
        path = os.path.join(_BASE_DIR, "strategies.json")

    errors: list[str] = []

    # 1. 解析
    try:
        from json_store import safe_load
        data = safe_load(path, default=None)
    except Exception as e:
        return [f"strategies.json 解析失败: {e}"]

    if data is None:
        return [f"strategies.json 不存在或为空: {path}"]

    if not isinstance(data, list):
        return [f"strategies.json 应为数组, 实际为 {type(data).__name__}"]

    if len(data) == 0:
        return ["strategies.json 为空数组 (无策略)"]

    # 2. 逐项校验
    seen_ids: set[str] = set()
    required_fields = {"id", "name", "module", "function", "schedule", "type"}

    for i, cfg in enumerate(data):
        prefix = f"策略[{i}]"

        if not isinstance(cfg, dict):
            errors.append(f"{prefix}: 应为对象, 实际为 {type(cfg).__name__}")
            continue

        sid = cfg.get("id", f"<无id, 索引{i}>")
        prefix = f"策略[{sid}]"

        # 必填字段
        for field in required_fields:
            if field not in cfg:
                errors.append(f"{prefix}: 缺少必填字段 '{field}'")

        # id 唯一
        if "id" in cfg:
            if cfg["id"] in seen_ids:
                errors.append(f"{prefix}: id 重复")
            seen_ids.add(cfg["id"])

        # type 合法
        stype = cfg.get("type", "")
        if stype and stype not in _VALID_TYPES:
            errors.append(f"{prefix}: type='{stype}' 不合法, 应为 {_VALID_TYPES}")

        # schedule 格式
        schedule = cfg.get("schedule", "")
        if schedule:
            import re
            if not (re.match(r"^\d{2}:\d{2}$", schedule) or
                    re.match(r"^\d+min$", schedule)):
                errors.append(
                    f"{prefix}: schedule='{schedule}' 格式错误, 应为 HH:MM 或 Nmin")

        # astock 需要 batch_slot
        if stype == "astock" and "batch_slot" not in cfg:
            errors.append(f"{prefix}: astock 类型策略缺少 batch_slot")

        # gates 键合法
        gates = cfg.get("gates", {})
        if isinstance(gates, dict):
            unknown = set(gates.keys()) - _VALID_GATE_KEYS
            if unknown:
                errors.append(f"{prefix}: gates 包含未知键 {unknown}")

        # pre_hook 合法
        pre_hook = cfg.get("pre_hook")
        if pre_hook and pre_hook not in _VALID_PRE_HOOKS:
            errors.append(f"{prefix}: pre_hook='{pre_hook}' 不合法")

        # module 文件存在
        module = cfg.get("module", "")
        if module:
            mod_path = os.path.join(_BASE_DIR, module + ".py")
            if not os.path.exists(mod_path):
                errors.append(f"{prefix}: module='{module}' 对应文件不存在 ({mod_path})")

        # push_format 校验 (direct_push 专用)
        push_fmt = cfg.get("push_format")
        if push_fmt is not None and not isinstance(push_fmt, dict):
            errors.append(f"{prefix}: push_format 应为对象")

    return errors


def validate_on_load(path: str = "") -> list[dict]:
    """校验并加载 — 校验失败时记录警告但仍返回数据 (宽容模式)

    Returns:
        策略列表 (即使有非致命错误也返回)
    """
    errors = validate_strategies(path)
    if errors:
        for e in errors:
            logger.warning("配置校验: %s", e)

    if not path:
        path = os.path.join(_BASE_DIR, "strategies.json")

    from json_store import safe_load
    return safe_load(path, default=[])


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    errors = validate_strategies()
    if errors:
        print(f"❌ 发现 {len(errors)} 个配置问题:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("✅ strategies.json 校验通过")
