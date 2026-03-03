"""
仓位管理 / 风控模块
===================
- 黑名单管理 (连续亏损自动拉黑)
- 持仓上限 / 行业集中度检查
- 每日熔断
- 仓位建议

设计原则: 所有异常不阻断策略运行
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date, timedelta

from config import RISK_PARAMS, POSITION_FILE, SMART_TRADE_ENABLED
from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("risk")

_DIR = os.path.dirname(os.path.abspath(__file__))
_BLACKLIST_PATH = os.path.join(_DIR, "blacklist.json")
_POS_PATH = os.path.join(_DIR, POSITION_FILE)
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_SCORECARD_DEFAULT = _SCORECARD_PATH


# ================================================================
#  行业分类 (复用 overnight_strategy.py)
# ================================================================

SECTOR_RULES = [
    ("医药", ["药", "医", "生物", "制药", "康", "健康", "诊断", "基因"]),
    ("科技", ["电子", "芯", "半导", "光电", "智能", "信息", "软件", "科技", "数据", "通信", "网络"]),
    ("金融", ["银行", "保险", "证券", "金融", "信托", "投资"]),
    ("消费", ["食品", "饮料", "酒", "乳", "农", "牧", "肉", "粮", "茶", "百货", "商业", "零售", "超市", "服饰", "家居"]),
    ("制造", ["机械", "设备", "汽车", "电机", "钢", "铝", "铜", "材料", "化工", "化学", "玻璃", "水泥"]),
    ("地产", ["地产", "置业", "房", "建设", "建工", "建筑"]),
    ("能源", ["能源", "电力", "电气", "石油", "燃气", "煤", "油", "风电", "光伏", "太阳", "新能"]),
    ("传媒", ["传媒", "文化", "影视", "游戏", "教育", "出版", "动漫"]),
]


def classify_sector(name: str) -> str:
    if not name:
        return "其他"
    for sector, keywords in SECTOR_RULES:
        for kw in keywords:
            if kw in name:
                return sector
    return "其他"


# ================================================================
#  风控过滤
# ================================================================

def filter_recommendations(strategy_name: str, items: list[dict]) -> list[dict]:
    """风控过滤 — 在 notify_all 之前调用

    规则 (按顺序):
      1. 移除黑名单股票
      2. 检查每日交易数上限 (max_daily_trades)
      3. 检查总持仓数上限 (max_positions)
      4. 检查行业集中度 (max_per_sector, 合并当前持仓)
    返回: 过滤后的推荐列表
    """
    if not items:
        return items

    max_positions = RISK_PARAMS.get("max_positions", 9)
    max_per_sector = RISK_PARAMS.get("max_per_sector", 2)
    max_daily_trades = RISK_PARAMS.get("max_daily_trades", 9)
    today_str = date.today().isoformat()

    # v2.0: 用regime参数覆盖max_positions
    if SMART_TRADE_ENABLED:
        try:
            from smart_trader import detect_market_regime
            regime_result = detect_market_regime()
            rp = regime_result.get("regime_params", {})
            regime_max_pos = rp.get("max_positions")
            if regime_max_pos is not None:
                max_positions = min(max_positions, regime_max_pos)
                logger.info("regime覆盖max_positions=%d (regime=%s)",
                            max_positions, regime_result.get("regime"))
        except Exception as e:
            logger.warning("regime获取失败, 使用默认max_positions: %s", e)

    positions = safe_load(_POS_PATH)
    holding = [p for p in positions if p.get("status") == "holding"]

    # 今日已新增持仓数
    today_entries = [
        p for p in positions
        if p.get("entry_date") == today_str
    ]

    original_count = len(items)
    filtered = list(items)

    # 1. 移除黑名单股票
    blacklist = safe_load(_BLACKLIST_PATH)
    bl_codes = {
        b["code"] for b in blacklist
        if b.get("until", "9999-12-31") >= today_str
    }
    if bl_codes:
        before = len(filtered)
        filtered = [it for it in filtered if it.get("code") not in bl_codes]
        removed = before - len(filtered)
        if removed > 0:
            logger.info("黑名单过滤: 移除 %d 只", removed)

    # 2. 每日交易数上限
    remaining_trades = max_daily_trades - len(today_entries)
    if remaining_trades <= 0:
        logger.warning("今日已达交易上限 %d, 全部过滤", max_daily_trades)
        return []
    if len(filtered) > remaining_trades:
        logger.info("今日交易余额 %d, 截断推荐", remaining_trades)
        filtered = filtered[:remaining_trades]

    # 3. 总持仓数上限 (按资产类别分开计算, 期货/币圈/美股 不占 A 股名额)
    _NON_STOCK = {"期货趋势选股", "币圈趋势选股", "美股收盘分析", "跨市场信号"}
    is_stock_strategy = strategy_name not in _NON_STOCK
    if is_stock_strategy:
        same_class_holding = [p for p in holding if p.get("strategy", "") not in _NON_STOCK]
    else:
        same_class_holding = [p for p in holding if p.get("strategy", "") in _NON_STOCK]
    remaining_positions = max_positions - len(same_class_holding)
    if remaining_positions <= 0:
        logger.warning("已达持仓上限 %d (%s类持仓%d), 全部过滤",
                       max_positions, "A股" if is_stock_strategy else "非A股",
                       len(same_class_holding))
        return []
    if len(filtered) > remaining_positions:
        logger.info("持仓余额 %d, 截断推荐", remaining_positions)
        filtered = filtered[:remaining_positions]

    # 4. 行业集中度检查 (仅 A 股策略, 跳过币圈/期货/美股)
    _SKIP_SECTOR_CHECK = {"币圈趋势选股", "期货趋势选股", "美股收盘分析", "跨市场信号"}
    if strategy_name not in _SKIP_SECTOR_CHECK:
        holding_sectors = Counter(classify_sector(p.get("name", "")) for p in holding)
        passed = []
        for it in filtered:
            sector = classify_sector(it.get("name", ""))
            current_count = holding_sectors.get(sector, 0)
            if current_count >= max_per_sector:
                logger.info("行业集中度: %s %s (%s已%d只, 上限%d)",
                            it.get("code"), it.get("name"), sector,
                            current_count, max_per_sector)
                continue
            passed.append(it)
            holding_sectors[sector] = current_count + 1
        filtered = passed

    if len(filtered) < original_count:
        logger.info("%s: %d → %d 只", strategy_name, original_count, len(filtered))

    return filtered


# ================================================================
#  每日熔断
# ================================================================

def check_daily_circuit_breaker() -> bool:
    """每日熔断检查

    统计今日已退出仓位的平均亏损, 超过 daily_loss_limit_pct (-5%) 则触发
    返回 True = 已熔断, 应停止所有策略
    """
    daily_loss_limit = RISK_PARAMS.get("daily_loss_limit_pct", -5.0)
    today_str = date.today().isoformat()

    positions = safe_load(_POS_PATH)

    # 清理 >3 天前的 exited 记录, 防止脏数据导致反复熔断
    cleaned = False
    new_positions = []
    for p in positions:
        if p.get("status") == "exited":
            exit_dt = p.get("exit_date", "")
            try:
                if exit_dt and (date.today() - date.fromisoformat(exit_dt)).days > 3:
                    cleaned = True
                    continue  # 丢弃旧记录
            except (ValueError, TypeError):
                pass
        new_positions.append(p)
    if cleaned:
        safe_save(_POS_PATH, new_positions)
        logger.info("已清理过期的 exited 持仓记录")
        positions = new_positions

    today_exits = [
        p for p in positions
        if p.get("status") == "exited" and p.get("exit_date") == today_str
    ]

    if not today_exits:
        return False

    pnl_list = [p.get("pnl_pct", 0) for p in today_exits]
    avg_pnl = sum(pnl_list) / len(pnl_list)

    if avg_pnl <= daily_loss_limit:
        logger.error("熔断! 今日平均亏损 %.1f%% <= %.1f%% (退出 %d 只)",
                      avg_pnl, daily_loss_limit, len(today_exits))
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw(
                "熔断告警",
                f"今日平均亏损 {avg_pnl:.1f}% 超过熔断线 {daily_loss_limit}%\n\n"
                f"已退出 {len(today_exits)} 只, 后续策略暂停"
            )
        except Exception:
            pass
        return True

    return False


# ================================================================
#  黑名单管理
# ================================================================

def update_blacklist():
    """扫描 scorecard.json, 连续亏损 >= blacklist_threshold 的股票加入黑名单

    过期黑名单 (超 blacklist_days 天) 自动移除
    """
    threshold = RISK_PARAMS.get("blacklist_threshold", 3)
    bl_days = RISK_PARAMS.get("blacklist_days", 60)
    today_str = date.today().isoformat()

    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        records = load_scorecard(days=90)
    except Exception:
        records = safe_load(_SCORECARD_PATH)
    if not records:
        return

    # 按股票分组, 按日期排序, 计算连续亏损
    code_records = defaultdict(list)
    for r in records:
        code_records[r["code"]].append(r)

    blacklist = safe_load(_BLACKLIST_PATH)
    bl_codes = {b["code"] for b in blacklist if b.get("until", "9999-12-31") >= today_str}
    new_bl = []

    for code, recs in code_records.items():
        if code in bl_codes:
            continue
        recs_sorted = sorted(recs, key=lambda x: x.get("rec_date", ""))
        consecutive_loss = 0
        for r in reversed(recs_sorted):
            if r.get("result") == "loss":
                consecutive_loss += 1
            else:
                break

        if consecutive_loss >= threshold:
            name = recs_sorted[-1].get("name", "")
            until = (date.today() + timedelta(days=bl_days)).isoformat()
            new_bl.append({
                "code": code,
                "name": name,
                "reason": f"连续{consecutive_loss}次亏损",
                "added_date": today_str,
                "until": until,
            })
            logger.info("黑名单新增: %s %s (连续%d次亏损, 至%s)",
                        code, name, consecutive_loss, until)

    # 移除过期黑名单
    active_bl = [b for b in blacklist if b.get("until", "9999-12-31") >= today_str]
    expired = len(blacklist) - len(active_bl)
    if expired > 0:
        logger.info("黑名单移除 %d 条过期记录", expired)

    active_bl.extend(new_bl)
    safe_save(_BLACKLIST_PATH, active_bl)

    if new_bl:
        logger.info("黑名单更新完成: 当前 %d 只", len(active_bl))


# ================================================================
#  仓位建议
# ================================================================

def get_position_sizing(capital: float, items: list[dict],
                        strategy_name: str = "") -> list[dict]:
    """仓位建议

    SMART_TRADE_ENABLED=True:
      调用 calc_dynamic_sizing (分数+波动率加权) + detect_market_regime 的 scale
    SMART_TRADE_ENABLED=False:
      原等权逻辑: 每只 = min(资金 * single_position_pct%, 资金 / 推荐数)

    strategy_name: 策略名(中文), 用于查询组合风控分配比例缩放资金
    向下取整到100股, 添加 suggested_amount 和 suggested_shares 字段
    """
    if not items or capital <= 0:
        return items

    # 应用组合风控资金分配 (缩放本策略可用资金)
    if strategy_name:
        try:
            from portfolio_risk import suggest_allocation
            from auto_optimizer import evaluate_strategy_health
            strategy_map = {
                "集合竞价选股": "auction",
                "放量突破选股": "breakout",
                "尾盘短线选股": "afternoon",
                "低吸回调选股": "dip_buy",
                "缩量整理选股": "consolidation",
                "趋势跟踪选股": "trend_follow",
                "板块轮动选股": "sector_rotation",
                "事件驱动选股": "news_event",
                "期货趋势选股": "futures_trend",
                "币圈趋势选股": "crypto_trend",
                "美股收盘分析": "us_stock",
            }
            health = {}
            for cn, en in strategy_map.items():
                try:
                    health[cn] = evaluate_strategy_health(en)
                except Exception:
                    health[cn] = {"score": 50}
            alloc = suggest_allocation(health)
            ratio = alloc.get("allocation", {}).get(strategy_name, 0.33)
            # 3 个策略共享资金, 按比例缩放
            capital = capital * ratio * len(strategy_map)
            logger.info("组合分配: %s → %.0f%% 资金", strategy_name, ratio * 100)
        except Exception:
            pass

    if SMART_TRADE_ENABLED:
        try:
            from smart_trader import calc_dynamic_sizing, detect_market_regime
            regime = detect_market_regime()
            rp = regime.get("regime_params", {})
            scale = rp.get("position_scale", regime.get("position_scale", 1.0))
            logger.info("动态仓位: 大盘=%s, score=%.2f, scale=%.1f",
                        regime.get("regime"), regime.get("score", 0), scale)
            return calc_dynamic_sizing(capital, items, regime_scale=scale)
        except Exception as e:
            logger.warning("动态仓位计算失败, 回退原逻辑: %s", e)

    # 原等权逻辑
    single_pct = RISK_PARAMS.get("single_position_pct", 15) / 100.0
    n = len(items)

    result = []
    for it in items:
        price = float(it.get("price", 0))
        if price <= 0:
            result.append(it)
            continue

        max_by_pct = capital * single_pct
        max_by_equal = capital / n
        amount = min(max_by_pct, max_by_equal)

        shares = int(amount / price / 100) * 100
        if shares < 100:
            shares = 100
        actual_amount = shares * price

        it_copy = dict(it)
        it_copy["suggested_shares"] = shares
        it_copy["suggested_amount"] = round(actual_amount, 2)
        result.append(it_copy)

    return result


# ================================================================
#  CLI 入口
# ================================================================

def _cli_filter():
    positions = safe_load(_POS_PATH)
    holding = [p for p in positions if p.get("status") == "holding"]
    blacklist = safe_load(_BLACKLIST_PATH)
    today_str = date.today().isoformat()
    active_bl = [b for b in blacklist if b.get("until", "9999-12-31") >= today_str]
    today_entries = [p for p in positions if p.get("entry_date") == today_str]

    max_pos = RISK_PARAMS.get("max_positions", 9)
    max_daily = RISK_PARAMS.get("max_daily_trades", 9)

    print("=" * 50)
    print("  风控状态")
    print("=" * 50)
    print(f"  当前持仓: {len(holding)}/{max_pos}")
    print(f"  今日新增: {len(today_entries)}/{max_daily}")
    print(f"  黑名单: {len(active_bl)} 只")

    if holding:
        sectors = Counter(classify_sector(p.get("name", "")) for p in holding)
        print(f"  行业分布: {dict(sectors)}")

    if active_bl:
        print("\n  黑名单详情:")
        for b in active_bl:
            print(f"    {b['code']} {b.get('name', '')} - {b.get('reason', '')} "
                  f"(至{b.get('until', '')})")


def _cli_breaker():
    if check_daily_circuit_breaker():
        print("熔断状态: 已触发!")
    else:
        print("熔断状态: 正常")


def _cli_blacklist():
    update_blacklist()
    blacklist = safe_load(_BLACKLIST_PATH)
    today_str = date.today().isoformat()
    active = [b for b in blacklist if b.get("until", "9999-12-31") >= today_str]

    if not active:
        print("黑名单: 空")
    else:
        print(f"黑名单: {len(active)} 只")
        for b in active:
            print(f"  {b['code']} {b.get('name', '')} - {b.get('reason', '')} "
                  f"(至{b.get('until', '')})")


def _cli_sizing(capital_str: str):
    try:
        capital = float(capital_str)
    except ValueError:
        print(f"无效资金额: {capital_str}")
        return

    positions = safe_load(_POS_PATH)
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        print("无持仓, 无法计算仓位建议")
        return

    items = [
        {"code": p["code"], "name": p.get("name", ""), "price": p.get("entry_price", 0)}
        for p in holding
    ]
    result = get_position_sizing(capital, items)

    print(f"仓位建议 (总资金: ¥{capital:,.0f})")
    print("-" * 50)
    for it in result:
        print(f"  {it['code']} {it.get('name', ''):　<8} "
              f"¥{it.get('price', 0):.2f} × {it.get('suggested_shares', 0)}股 "
              f"= ¥{it.get('suggested_amount', 0):,.0f}")


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "filter":
        _cli_filter()
    elif mode == "breaker":
        _cli_breaker()
    elif mode == "blacklist":
        _cli_blacklist()
    elif mode == "sizing":
        if len(sys.argv) > 2:
            _cli_sizing(sys.argv[2])
        else:
            print("用法: python3 risk_manager.py sizing <资金额>")
    else:
        print("用法:")
        print("  python3 risk_manager.py filter          # 查看风控状态")
        print("  python3 risk_manager.py breaker         # 检查熔断")
        print("  python3 risk_manager.py blacklist       # 查看/更新黑名单")
        print("  python3 risk_manager.py sizing 100000   # 仓位计算")
        sys.exit(1)
