"""
环境路由器
=========
检测 regime 后动态路由: 牛市加仓 breakout/trend, 熊市只开 overnight/dip_buy。
止损大头来自"在错误环境跑错误策略"。

核心:
  calc_strategy_fitness() — 计算每个策略在当前 regime 下的适应度
  get_capital_ratios()    — 返回各策略资金分配比例
  should_skip_strategy()  — 资金比例 < min_ratio 则跳过
  get_position_scale()    — regime-adjusted 仓位缩放系数

调度: 09:08 (开盘后、首个策略前)
数据: regime_routing.json

CLI:
  python3 regime_router.py          # 显示当前路由状态
  python3 regime_router.py status   # 同上
  python3 regime_router.py calc     # 强制重算
"""

import os
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger
from json_store import safe_load, safe_save

logger = get_logger("regime_router")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROUTING_PATH = os.path.join(_BASE_DIR, "regime_routing.json")

try:
    from config import REGIME_ROUTER_PARAMS
except ImportError:
    REGIME_ROUTER_PARAMS = {
        "enabled": True, "lookback_days": 60, "min_ratio": 0.05,
        "max_ratio": 0.30, "min_samples": 10, "default_fitness": 0.5,
    }

# 策略名映射 (中文→英文 key)
_STRATEGY_NAME_MAP = {
    "集合竞价选股": "auction",
    "尾盘短线选股": "afternoon",
    "放量突破选股": "breakout",
    "低吸回调选股": "dip_buy",
    "缩量整理选股": "consolidation",
    "趋势跟踪选股": "trend_follow",
    "板块轮动选股": "sector_rotation",
    "事件驱动选股": "news_event",
}

_STRATEGY_KEY_MAP = {v: k for k, v in _STRATEGY_NAME_MAP.items()}


def _get_current_regime() -> dict:
    """获取当前 regime"""
    try:
        from smart_trader import detect_market_regime
        return detect_market_regime()
    except Exception as e:
        logger.warning("detect_market_regime failed: %s", e)
        return {"regime": "neutral", "score": 0.5, "signals": {}}


def calc_strategy_fitness(lookback_days: int = None) -> dict:
    """计算每个策略在当前 regime 下的适应度

    1. detect_market_regime() → 当前 regime
    2. get_regime_strategy_matrix(days) → {strategy: {regime: {win_rate, total}}}
    3. fitness[s] = win_rate_in_current_regime × confidence(min(1, total/20))
    4. 数据不足(<min_samples) → fitness = default_fitness

    Returns:
        {strategy_key: {"fitness": float, "win_rate": float, "samples": int, "regime": str}}
    """
    if lookback_days is None:
        lookback_days = REGIME_ROUTER_PARAMS.get("lookback_days", 60)

    min_samples = REGIME_ROUTER_PARAMS.get("min_samples", 10)
    default_fitness = REGIME_ROUTER_PARAMS.get("default_fitness", 0.5)

    # 当前 regime
    regime_result = _get_current_regime()
    current_regime = regime_result.get("regime", "neutral")

    # 策略 × regime 胜率矩阵
    try:
        from signal_tracker import get_regime_strategy_matrix
        matrix = get_regime_strategy_matrix(days=lookback_days)
    except Exception as e:
        logger.warning("get_regime_strategy_matrix failed: %s", e)
        matrix = {}

    result = {}
    for cn_name, eng_key in _STRATEGY_NAME_MAP.items():
        strategy_data = matrix.get(cn_name, {})
        regime_data = strategy_data.get(current_regime, {})

        win_rate = regime_data.get("win_rate", 0)
        total = regime_data.get("total", 0)

        if total < min_samples:
            fitness = default_fitness
        else:
            confidence = min(1.0, total / 20)
            fitness = (win_rate / 100) * confidence  # win_rate 是百分比

        result[eng_key] = {
            "fitness": round(fitness, 4),
            "win_rate": win_rate,
            "samples": total,
            "regime": current_regime,
        }

    return result


def get_capital_ratios() -> dict:
    """主入口: 返回各策略资金分配比例

    1. calc_strategy_fitness()
    2. 归一化: 每个 in [min_ratio, max_ratio], 总和 = 1.0
    3. 缓存今日结果到 regime_routing.json

    Returns:
        {strategy_key: ratio}
    """
    if not REGIME_ROUTER_PARAMS.get("enabled", True):
        # 禁用时返回等权
        n = len(_STRATEGY_NAME_MAP)
        return {k: round(1.0 / n, 4) for k in _STRATEGY_NAME_MAP.values()}

    fitness_map = calc_strategy_fitness()
    min_ratio = REGIME_ROUTER_PARAMS.get("min_ratio", 0.05)
    max_ratio = REGIME_ROUTER_PARAMS.get("max_ratio", 0.30)

    # fitness → raw ratio
    raw = {k: v["fitness"] for k, v in fitness_map.items()}
    total = sum(raw.values())
    if total <= 0:
        n = len(raw)
        ratios = {k: round(1.0 / n, 4) for k in raw}
    else:
        ratios = {k: v / total for k, v in raw.items()}

    # clamp to [min_ratio, max_ratio]
    ratios = {k: max(min_ratio, min(max_ratio, v)) for k, v in ratios.items()}

    # 再次归一化到 sum=1.0
    total2 = sum(ratios.values())
    if total2 > 0:
        ratios = {k: round(v / total2, 4) for k, v in ratios.items()}

    # 缓存
    routing_data = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "regime": fitness_map.get(list(fitness_map.keys())[0], {}).get("regime", "unknown") if fitness_map else "unknown",
        "fitness": {k: v["fitness"] for k, v in fitness_map.items()},
        "ratios": ratios,
        "details": fitness_map,
    }
    safe_save(_ROUTING_PATH, routing_data)

    # 级联引擎: 检测 regime 是否切换, 通知学习引擎等下游
    new_regime = routing_data["regime"]
    try:
        old_data = safe_load(_ROUTING_PATH, default={})
        old_regime = old_data.get("_prev_regime", new_regime)
        if new_regime != old_regime:
            from cascade_engine import cascade
            cascade('regime_change', new_regime=new_regime,
                    old_regime=old_regime)
            logger.info("Regime切换: %s → %s, 已级联通知", old_regime, new_regime)
        routing_data["_prev_regime"] = new_regime
        safe_save(_ROUTING_PATH, routing_data)
    except Exception as e:
        logger.debug("[Cascade] regime级联通知失败: %s", e)

    logger.info("路由更新: regime=%s, 跳过=%s",
                new_regime,
                [k for k, v in ratios.items() if v < min_ratio])

    return ratios


def _load_today_routing() -> dict:
    """加载今日路由缓存"""
    data = safe_load(_ROUTING_PATH, default={})
    if data.get("date") == date.today().isoformat():
        return data
    return {}


def should_skip_strategy(strategy_name: str) -> bool:
    """资金比例 < min_ratio 则跳过该策略

    Args:
        strategy_name: 中文策略名 或 英文 key
    """
    if not REGIME_ROUTER_PARAMS.get("enabled", True):
        return False

    routing = _load_today_routing()
    if not routing:
        return False  # 路由未运行, 不跳过

    ratios = routing.get("ratios", {})
    min_ratio = REGIME_ROUTER_PARAMS.get("min_ratio", 0.05)

    # 查找 key
    eng_key = _STRATEGY_NAME_MAP.get(strategy_name, strategy_name)
    ratio = ratios.get(eng_key)

    if ratio is None:
        return False  # 未知策略不跳过

    skip = ratio < min_ratio
    if skip:
        logger.info("策略跳过: %s (ratio=%.3f < min=%.3f)", strategy_name, ratio, min_ratio)
    return skip


def get_position_scale(strategy_name: str) -> float:
    """返回该策略的 regime-adjusted 仓位缩放系数

    = base_regime_scale × (strategy_ratio / avg_ratio)
    """
    if not REGIME_ROUTER_PARAMS.get("enabled", True):
        return 1.0

    routing = _load_today_routing()
    if not routing:
        return 1.0

    ratios = routing.get("ratios", {})
    eng_key = _STRATEGY_NAME_MAP.get(strategy_name, strategy_name)
    ratio = ratios.get(eng_key)

    if ratio is None:
        return 1.0

    # avg ratio = 1/N
    n = len(ratios) if ratios else 1
    avg_ratio = 1.0 / n

    # scale: ratio / avg_ratio, clamp to [0.3, 2.0]
    scale = ratio / avg_ratio if avg_ratio > 0 else 1.0
    scale = max(0.3, min(2.0, scale))

    return round(scale, 3)


def get_routing_status() -> dict:
    """当前路由状态: regime, 各策略 fitness/ratio/skip"""
    routing = _load_today_routing()
    if not routing:
        return {"enabled": REGIME_ROUTER_PARAMS.get("enabled", True),
                "status": "not_calculated"}

    ratios = routing.get("ratios", {})
    min_ratio = REGIME_ROUTER_PARAMS.get("min_ratio", 0.05)
    details = routing.get("details", {})

    strategies = {}
    for eng_key, ratio in ratios.items():
        cn_name = _STRATEGY_KEY_MAP.get(eng_key, eng_key)
        d = details.get(eng_key, {})
        strategies[eng_key] = {
            "name": cn_name,
            "ratio": ratio,
            "fitness": d.get("fitness", 0),
            "win_rate": d.get("win_rate", 0),
            "samples": d.get("samples", 0),
            "skip": ratio < min_ratio,
            "position_scale": get_position_scale(cn_name),
        }

    return {
        "enabled": REGIME_ROUTER_PARAMS.get("enabled", True),
        "status": "active",
        "regime": routing.get("regime", "unknown"),
        "timestamp": routing.get("timestamp", ""),
        "strategies": strategies,
        "skipped": [k for k, v in strategies.items() if v["skip"]],
    }


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    print("=" * 55)
    print("  环境路由器")
    print("=" * 55)

    if mode == "calc":
        ratios = get_capital_ratios()
        status = get_routing_status()
        print(f"\n  Regime: {status.get('regime', '?')}")
        print(f"\n  {'策略':<16} {'比例':>6} {'适应度':>7} {'胜率':>6} {'样本':>5} {'状态':>6}")
        print(f"  {'-'*50}")
        for k, v in status.get("strategies", {}).items():
            tag = "SKIP" if v["skip"] else "OK"
            print(f"  {v['name']:<16} {v['ratio']:>6.3f} {v['fitness']:>7.3f} "
                  f"{v['win_rate']:>5.1f}% {v['samples']:>5d} {tag:>6}")

    else:  # status
        status = get_routing_status()
        if status.get("status") == "not_calculated":
            print("\n  今日路由尚未计算")
            print("  运行: python3 regime_router.py calc")
        else:
            print(f"\n  Regime: {status.get('regime', '?')}")
            print(f"  更新: {status.get('timestamp', '?')}")
            print(f"  跳过: {status.get('skipped', [])}")
            print(f"\n  {'策略':<16} {'比例':>6} {'适应度':>7} {'仓位缩放':>8} {'状态':>6}")
            print(f"  {'-'*50}")
            for k, v in status.get("strategies", {}).items():
                tag = "SKIP" if v["skip"] else "OK"
                print(f"  {v['name']:<16} {v['ratio']:>6.3f} {v['fitness']:>7.3f} "
                      f"{v['position_scale']:>8.2f} {tag:>6}")
