"""
持仓管理器
==========
- 持仓记录 (JSON 文件存储, 文件锁保护)
- 止损止盈监控
- 卖出信号生成

状态机: holding → exited (止损/止盈/T+1强制), 单向不可逆
"""

from __future__ import annotations

import os
from datetime import datetime, date, timedelta

from config import (
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, FORCE_EXIT_TIME, POSITION_FILE,
    SMART_TRADE_ENABLED,
)
from json_store import safe_load, safe_load_strict, safe_save
from log_config import get_logger

logger = get_logger("position")

# 持仓文件路径 (与本文件同目录)
_POS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), POSITION_FILE)


# ================================================================
#  持仓读写 (文件锁保护)
# ================================================================

def load_positions() -> list[dict]:
    """从 JSON 文件加载持仓 (严格模式: 文件损坏则抛异常, 不静默返回空)"""
    return safe_load_strict(_POS_PATH)


def save_positions(positions: list[dict]):
    """保存持仓到 JSON 文件"""
    safe_save(_POS_PATH, positions)


# ================================================================
#  记录买入
# ================================================================

def record_entry(strategy_name: str, items: list[dict]):
    """策略推荐后自动记录买入

    items: 标准化 list[dict], 每项包含 code, name, price, score, reason
    """
    if not items:
        return

    positions = load_positions()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # 获取今日已持仓的代码 (避免重复录入同一天同策略的推荐)
    existing = {
        (p["code"], p["entry_date"], p["strategy"])
        for p in positions
        if p.get("status") == "holding"
    }

    new_count = 0
    for it in items:
        code = it.get("code", "")
        if not code or code == "ERROR":
            continue
        key = (code, today_str, strategy_name)
        if key in existing:
            continue

        entry_price = float(it.get("price", 0))
        pos = {
            "code": code,
            "name": it.get("name", ""),
            "strategy": strategy_name,
            "entry_price": entry_price,
            "entry_date": today_str,
            "entry_time": time_str,
            "score": float(it.get("score", 0)),
            "reason": it.get("reason", ""),
            "status": "holding",
        }
        # 多日持仓支持 (趋势跟踪等策略)
        pos["holding_days"] = int(it.get("holding_days", 1))
        # 智能交易: 追踪止盈 + 分批卖出 + 自适应止损字段
        if SMART_TRADE_ENABLED:
            pos["highest_price"] = entry_price
            pos["atr"] = float(it.get("atr", 0))
            pos["partial_exited"] = False
            pos["remaining_ratio"] = 1.0
        positions.append(pos)
        existing.add(key)
        new_count += 1

    if new_count > 0:
        save_positions(positions)
        logger.info("新增 %d 条持仓记录 (%s)", new_count, strategy_name)


# ================================================================
#  退出信号检查
# ================================================================

def _get_current_prices(codes: list[str]) -> dict:
    """批量获取当前价格, 返回 {code: price}

    数据源优先级:
      1. 新浪批量报价 (_sina_batch_quote)
      2. 东方财富全量快照 (ak.stock_zh_a_spot_em) — 备用
      3. 腾讯逐只查询 (ak.stock_zh_a_hist_tx) — 兜底
    """
    if not codes:
        return {}

    # 过滤: 只查A股代码 (6位数字, 排除期货/美股等)
    stock_codes = [c for c in codes if len(c) == 6 and c.isdigit()]
    non_stock = {c for c in codes if c not in stock_codes}
    if non_stock:
        logger.debug("跳过非A股代码: %s", non_stock)

    if not stock_codes:
        return {}

    # 主数据源: 新浪
    try:
        from intraday_strategy import _sina_batch_quote
        df = _sina_batch_quote(stock_codes)
        if not df.empty:
            result = dict(zip(df["code"], df["price"]))
            if result:
                return result
    except Exception as e:
        logger.warning("新浪报价失败: %s, 切换备用源", e)

    # 备用数据源: 东方财富
    try:
        import akshare as ak
        logger.info("使用东方财富备用数据源...")
        df = ak.stock_zh_a_spot_em()
        code_col = "代码" if "代码" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else df.columns[2]
        df[code_col] = df[code_col].astype(str)
        df[price_col] = df[price_col].apply(
            lambda x: float(x) if str(x).replace(".", "").replace("-", "").isdigit() else 0
        )
        code_set = set(stock_codes)
        filtered = df[df[code_col].isin(code_set)]
        result = dict(zip(filtered[code_col], filtered[price_col]))
        if result:
            logger.info("东方财富备用源获取成功: %d/%d", len(result), len(stock_codes))
            return result
    except Exception as e:
        logger.error("东方财富备用源也失败: %s, 尝试腾讯源", e)

    # 兜底数据源: 腾讯逐只查询最近收盘价
    try:
        import akshare as ak
        from overnight_strategy import _tx_sym
        logger.info("使用腾讯逐只查询兜底...")
        result = {}
        for code in stock_codes[:20]:  # 限制20只防止太慢
            try:
                df = ak.stock_zh_a_hist_tx(
                    symbol=_tx_sym(code), start_date="20260101",
                    end_date="20261231", adjust="qfq"
                )
                if df is not None and not df.empty:
                    close_col = next(
                        (c for c in ["close", "收盘", "收盘价"] if c in df.columns),
                        None
                    )
                    if close_col:
                        result[code] = float(df[close_col].iloc[-1])
            except Exception:
                pass
        if result:
            logger.info("腾讯兜底源获取成功: %d/%d", len(result), len(stock_codes))
            return result
    except Exception as e:
        logger.error("腾讯兜底源也失败: %s", e)

    return {}


def check_exit_signals() -> list[dict]:
    """检查所有 holding 仓位的退出信号

    返回: 需要卖出的仓位列表 (已更新 status='exited')
    """
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        logger.info("无持仓, 跳过监控")
        return []

    logger.info("检查 %d 只持仓...", len(holding))

    # 批量获取当前价格
    codes = [p["code"] for p in holding]
    price_map = _get_current_prices(codes)

    if not price_map:
        logger.warning("获取实时价格失败, 跳过本次检查")
        return []

    now = datetime.now()
    now_time = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    exits = []
    for p in holding:
        code = p["code"]
        current_price = price_map.get(code)
        if not current_price or current_price <= 0:
            continue

        entry_price = p["entry_price"]
        if entry_price <= 0:
            continue

        pnl_pct = (current_price - entry_price) / entry_price * 100
        exit_reason = None
        exit_ratio = 1.0  # 默认全部卖出

        if SMART_TRADE_ENABLED:
            from smart_trader import (
                calc_adaptive_stop, calc_trailing_stop, check_partial_exit,
                detect_market_regime, get_regime_params,
            )

            # v2.0: 获取当前regime参数, 覆盖止损止盈设置
            try:
                regime_result = detect_market_regime()
                rp = regime_result.get("regime_params", {})
            except Exception:
                rp = get_regime_params("neutral")

            # 更新最高价
            highest = max(p.get("highest_price", entry_price), current_price)
            p["highest_price"] = highest

            atr = p.get("atr", 0)

            # 1. ATR 自适应止损 (使用regime的atr_multiplier)
            stop_price = calc_adaptive_stop(entry_price, atr,
                                            atr_multiplier_override=rp.get("atr_multiplier"))
            if current_price <= stop_price:
                exit_reason = "自适应止损"

            # 2. 分批止盈 (使用regime的first_exit参数)
            if not exit_reason:
                partial = check_partial_exit(
                    entry_price, current_price,
                    {"partial_exited": p.get("partial_exited", False),
                     "remaining_ratio": p.get("remaining_ratio", 1.0)},
                    first_exit_pct_override=rp.get("first_exit_pct"),
                    first_exit_ratio_override=rp.get("first_exit_ratio"),
                )
                if partial["should_partial_exit"]:
                    p["partial_exited"] = True
                    p["remaining_ratio"] = partial["remaining_ratio"]
                    exit_reason = "分批止盈"
                    exit_ratio = partial["exit_ratio"]

            # 3. 追踪止盈 (使用regime的trail参数)
            if not exit_reason:
                trail = calc_trailing_stop(entry_price, highest, current_price,
                                           trail_pct_override=rp.get("trail_pct"),
                                           initial_target_override=rp.get("initial_target_pct"))
                if trail["should_exit"]:
                    exit_reason = trail["exit_reason"]

            # 4. 动态持仓期强制离场
            if not exit_reason:
                max_hold = p.get("holding_days", 1)
                entry_d = datetime.strptime(p["entry_date"], "%Y-%m-%d").date()
                held_days = (date.today() - entry_d).days
                if held_days >= max_hold and now_time >= FORCE_EXIT_TIME:
                    exit_reason = f"T+{max_hold}离场"

        else:
            # 原逻辑
            if pnl_pct <= STOP_LOSS_PCT:
                exit_reason = "止损"
            elif pnl_pct >= TAKE_PROFIT_PCT:
                exit_reason = "止盈"
            else:
                max_hold = p.get("holding_days", 1)
                entry_d = datetime.strptime(p["entry_date"], "%Y-%m-%d").date()
                held_days = (date.today() - entry_d).days
                if held_days >= max_hold and now_time >= FORCE_EXIT_TIME:
                    exit_reason = f"T+{max_hold}离场"

        if exit_reason:
            # 分批止盈时不设 exited 状态, 只有全部退出才改状态
            if exit_reason == "分批止盈":
                # 部分卖出: 记录但保持 holding
                p["exit_price"] = current_price
                p["exit_date"] = today_str
                p["exit_time"] = now_time
                p["last_exit_reason"] = exit_reason
                p["pnl_pct"] = round(pnl_pct, 2)
            else:
                p["status"] = "exited"
                p["exit_price"] = current_price
                p["exit_date"] = today_str
                p["exit_time"] = now_time
                p["exit_reason"] = exit_reason
                p["pnl_pct"] = round(pnl_pct, 2)
            exits.append(p)

    if exits:
        save_positions(positions)
        reasons = [f"{e['code']}({e['exit_reason']})" for e in exits]
        logger.info("触发退出: %s", ", ".join(reasons))
    else:
        logger.debug("未触发退出信号")

    return exits


# ================================================================
#  持仓汇总
# ================================================================

def get_portfolio_summary() -> dict:
    """当前持仓汇总

    返回: {count, details: [{code, name, entry_price, current_price, pnl_pct}]}
    """
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        return {"count": 0, "details": []}

    codes = [p["code"] for p in holding]
    price_map = _get_current_prices(codes)

    details = []
    total_pnl = 0
    for p in holding:
        current = price_map.get(p["code"], 0)
        entry = p["entry_price"]
        pnl_pct = (current - entry) / entry * 100 if entry > 0 and current > 0 else 0
        total_pnl += pnl_pct
        details.append({
            "code": p["code"],
            "name": p["name"],
            "strategy": p["strategy"],
            "entry_price": entry,
            "current_price": current,
            "pnl_pct": round(pnl_pct, 2),
        })

    return {
        "count": len(details),
        "total_pnl_pct": round(total_pnl, 2),
        "details": details,
    }


# ================================================================
#  清理历史记录
# ================================================================

def clean_old_positions(days=30):
    """清理 N 天前已退出的仓位记录"""
    positions = load_positions()
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    before = len(positions)
    positions = [
        p for p in positions
        if p.get("status") == "holding"
        or p.get("exit_date", "9999-12-31") >= cutoff
    ]
    after = len(positions)

    if before != after:
        save_positions(positions)
        logger.info("清理 %d 条过期记录 (%d天前已退出)", before - after, days)


# ================================================================
#  入口 (独立运行时)
# ================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "check":
        exits = check_exit_signals()
        if exits:
            for e in exits:
                print(f"  {e['code']} {e['name']} {e['exit_reason']} "
                      f"买入¥{e['entry_price']:.2f} → 退出¥{e['exit_price']:.2f} "
                      f"{e['pnl_pct']:+.2f}%")
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary = get_portfolio_summary()
        print(f"持仓: {summary['count']} 只")
        for d in summary.get("details", []):
            print(f"  {d['code']} {d['name']} "
                  f"买入¥{d['entry_price']:.2f} → 现价¥{d['current_price']:.2f} "
                  f"{d['pnl_pct']:+.2f}%")
    elif len(sys.argv) > 1 and sys.argv[1] == "clean":
        clean_old_positions()
    else:
        print("用法:")
        print("  python3 position_manager.py check    # 检查退出信号")
        print("  python3 position_manager.py summary  # 持仓汇总")
        print("  python3 position_manager.py clean    # 清理历史记录")
