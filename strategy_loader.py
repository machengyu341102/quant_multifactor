"""
策略动态加载器
=============
从 strategies.json 读取策略配置, 动态生成 job 函数并注册到调度器。
新增策略只需编辑 strategies.json, 无需修改 scheduler.py。

支持两种策略类型:
  - astock: A股选股策略 (标准 gate 检查 + 批量推送)
  - direct_push: 直推微信策略 (期货/币圈/美股)
"""

from __future__ import annotations

import importlib
import os

from json_store import safe_load
from log_config import get_logger

logger = get_logger("strategy_loader")

_STRATEGIES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "strategies.json"
)

_strategies_cache: list[dict] | None = None


def load_strategies() -> list[dict]:
    """加载策略配置 (带缓存)"""
    global _strategies_cache
    if _strategies_cache is not None:
        return _strategies_cache
    _strategies_cache = safe_load(_STRATEGIES_PATH, default=[])
    return _strategies_cache


def reload_strategies() -> list[dict]:
    """强制重新加载 (热更新用)"""
    global _strategies_cache
    _strategies_cache = None
    return load_strategies()


def get_strategy(strategy_id: str) -> dict | None:
    """按 ID 获取单个策略配置"""
    for s in load_strategies():
        if s.get("id") == strategy_id:
            return s
    return None


def get_enabled_strategies(*types: str) -> list[dict]:
    """获取指定类型的已启用策略"""
    all_types = types or ("astock", "direct_push")
    return [
        s for s in load_strategies()
        if s.get("type") in all_types and s.get("enabled", True)
    ]


def _import_func(module_name: str, func_name: str):
    """动态导入策略函数"""
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


# ================================================================
#  Job 工厂: A股标准策略
# ================================================================

def _make_astock_job(cfg: dict, sched_mod):
    """为 A 股策略创建 job 闭包

    标准流水线:
      trading_day → agent_check → regime_check → circuit_breaker
      → [pre_hook] → run_with_retry → batch_buffer → learning
    """
    strategy_name = cfg["name"]
    module_name = cfg["module"]
    func_name = cfg["function"]
    batch_slot = cfg.get("batch_slot")
    gates = cfg.get("gates", {})
    pre_hook = cfg.get("pre_hook")
    schedule_time = cfg.get("schedule", "")

    def job():
        # Gate 1: 交易日
        if gates.get("trading_day", True):
            if not sched_mod.is_trading_day():
                print(f"  [{schedule_time}] 非交易日, 跳过{strategy_name}")
                return

        # Gate 2: Agent 启停
        if gates.get("agent_check", True):
            try:
                from agent_brain import should_strategy_run
                if not should_strategy_run(strategy_name):
                    print(f"  [{schedule_time}] [Agent] {strategy_name} 已暂停, 跳过")
                    return
            except Exception:
                pass

        # Gate 3: 大盘环境
        regime_result = None
        if gates.get("regime_check", True):
            should_run, regime, regime_result = sched_mod._check_market_regime()
            if not should_run:
                print(f"  [{schedule_time}] 大盘熊市({regime}), 跳过{strategy_name}")
                return

        # Gate 4: 熔断
        if gates.get("circuit_breaker", False):
            try:
                from risk_manager import check_daily_circuit_breaker
                if check_daily_circuit_breaker():
                    print(f"  [{schedule_time}] 熔断已触发, 跳过{strategy_name}")
                    return
            except Exception:
                pass

        # Pre-hook
        if pre_hook == "clear_ths_watchlist":
            try:
                from notifier import clear_ths_watchlist
                clear_ths_watchlist()
            except Exception as e:
                logger.warning("Pre-hook %s 失败: %s", pre_hook, e)

        # 执行策略
        func = _import_func(module_name, func_name)
        items = sched_mod.run_with_retry(func, strategy_name, skip_wechat=True)

        # 批量推送缓冲区
        if batch_slot:
            sched_mod._batch_buffer[batch_slot].append(
                (strategy_name, items or [])
            )

        # 学习记录
        sched_mod._record_learning(items, strategy_name, regime_result)

    job.__name__ = f"job_{cfg['id']}"
    job.__doc__ = f"{strategy_name} (动态加载)"
    return job


# ================================================================
#  Job 工厂: 直推策略 (期货/币圈/美股)
# ================================================================

def _make_direct_push_job(cfg: dict, sched_mod):
    """为直推微信策略创建 job 闭包 (期货/币圈/美股)"""
    strategy_name = cfg["name"]
    module_name = cfg["module"]
    func_name = cfg["function"]
    gates = cfg.get("gates", {})
    schedule_time = cfg.get("schedule", "")
    push_title = cfg.get("push_title", strategy_name)
    push_header = cfg.get("push_header", f"{strategy_name}:")
    push_fmt = cfg.get("push_format", {})
    execute_trades = cfg.get("execute_trades", False)

    def job():
        # Gate 1: 交易日类型
        td_type = gates.get("trading_day", "none")
        if td_type == "futures":
            if not sched_mod._is_futures_trading_day():
                print(f"  [{schedule_time}] 周末, 跳过{push_title}")
                return
        elif td_type == "stock" or td_type is True:
            if not sched_mod.is_trading_day():
                return
        # "none" / False = 24h 市场, 不检查

        # Gate 2: Agent 启停
        if gates.get("agent_check", True):
            try:
                from agent_brain import should_strategy_run
                if not should_strategy_run(strategy_name):
                    print(f"  [{schedule_time}] [Agent] {strategy_name} 已暂停, 跳过")
                    return
            except Exception:
                pass

        # 执行策略
        func = _import_func(module_name, func_name)
        items = sched_mod.run_with_retry(func, strategy_name, skip_wechat=True)

        if items:
            # 期货交易执行
            if execute_trades:
                sched_mod._execute_futures_trades(items)

            # 直推微信
            from notifier import notify_wechat_raw
            price_sym = push_fmt.get("price_symbol", "¥")
            price_fmt = push_fmt.get("price_fmt", ".1f")
            show_dir = push_fmt.get("show_direction", False)

            lines = [push_header]
            for it in items:
                d = ""
                if show_dir:
                    d = "▲" if it.get("direction") == "long" else "▼"
                    d += " "
                lines.append(
                    f"  {d}{it['code']} {it['name']} "
                    f"{price_sym}{it['price']:{price_fmt}} "
                    f"评分{it['score']:.3f} {it['reason']}"
                )
            try:
                notify_wechat_raw(f"[{schedule_time}] {push_title}", "\n".join(lines))
            except Exception:
                pass

        # 学习记录
        sched_mod._record_learning(items, strategy_name, None)

    job.__name__ = f"job_{cfg['id']}"
    job.__doc__ = f"{push_title} (动态加载)"
    return job


# ================================================================
#  注册入口
# ================================================================

def register_strategies(sched_mod, schedule_obj) -> int:
    """将所有启用策略注册到 schedule 定时器

    Args:
        sched_mod: scheduler 模块 (提供 is_trading_day, run_with_retry 等)
        schedule_obj: schedule 库实例

    Returns:
        注册的策略数量
    """
    strategies = load_strategies()
    count = 0

    for cfg in strategies:
        if not cfg.get("enabled", True):
            logger.debug("策略 %s 已禁用, 跳过注册", cfg.get("id"))
            continue

        stype = cfg.get("type", "astock")
        schedule_time = cfg.get("schedule", "")

        if not schedule_time:
            logger.warning("策略 %s 缺少 schedule 时间, 跳过", cfg.get("id"))
            continue

        # 创建 job
        if stype == "astock":
            job = _make_astock_job(cfg, sched_mod)
        elif stype == "direct_push":
            job = _make_direct_push_job(cfg, sched_mod)
        else:
            logger.warning("策略 %s 未知类型 %s, 跳过", cfg.get("id"), stype)
            continue

        # 注册到定时器
        schedule_day = cfg.get("schedule_day", "every_day")
        if schedule_day == "friday":
            schedule_obj.every().friday.at(schedule_time).do(job)
        elif schedule_day == "saturday":
            schedule_obj.every().saturday.at(schedule_time).do(job)
        else:
            schedule_obj.every().day.at(schedule_time).do(job)

        count += 1
        logger.debug("注册策略: %s @ %s", cfg.get("name"), schedule_time)

    logger.info("策略加载器: %d/%d 策略已注册", count, len(strategies))
    return count


def run_all_strategies(sched_mod):
    """测试模式: 立即运行所有启用策略 (跳过所有 gate 检查)"""
    strategies = load_strategies()

    print("=" * 60)
    print("  [测试模式] 动态加载运行全部策略")
    print(f"  从 strategies.json 加载 {len(strategies)} 个策略")
    print("=" * 60)

    for cfg in strategies:
        if not cfg.get("enabled", True):
            continue

        module_name = cfg["module"]
        func_name = cfg["function"]
        strategy_name = cfg["name"]

        func = _import_func(module_name, func_name)
        sched_mod.run_with_retry(func, strategy_name)

    print("\n全部策略运行完毕")


def get_cli_strategy(strategy_id: str) -> tuple[str, str, str] | None:
    """CLI 用: 按 ID 或别名获取 (module, function, name)"""
    cfg = get_strategy(strategy_id)
    if cfg and cfg.get("enabled", True):
        return cfg["module"], cfg["function"], cfg["name"]
    # 查找别名
    for s in load_strategies():
        if strategy_id in s.get("cli_aliases", []) and s.get("enabled", True):
            return s["module"], s["function"], s["name"]
    return None
