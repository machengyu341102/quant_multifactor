"""
定时调度器
==========
自动在交易日指定时间运行八个策略, 批量合并推送通知

用法:
  python3 scheduler.py             # 启动守护进程 (常驻运行)
  python3 scheduler.py test        # 立即运行全部策略 (测试用)
  python3 scheduler.py news_event  # 单独运行事件驱动
  python3 scheduler.py auction     # 单独运行集合竞价
  python3 scheduler.py breakout    # 单独运行放量突破
  python3 scheduler.py afternoon   # 单独运行尾盘短线
  python3 scheduler.py dip_buy     # 单独运行低吸回调
  python3 scheduler.py consolidation # 单独运行缩量整理
  python3 scheduler.py trend       # 单独运行趋势跟踪
  python3 scheduler.py sector      # 单独运行板块轮动
  python3 scheduler.py scorecard   # 对昨日推荐打分
  python3 scheduler.py weekly      # 生成并推送周报
  python3 scheduler.py learning    # 手动触发学习引擎
  python3 scheduler.py agent       # 手动触发 Agent OODA 循环
  python3 scheduler.py verify      # 手动触发优化验证
  python3 scheduler.py lifecycle   # 手动触发因子生命周期检查
  python3 scheduler.py crypto      # 单独运行币圈趋势
  python3 scheduler.py us_stock    # 单独运行美股分析
  python3 scheduler.py cross_market # 单独运行跨市场推演
  python3 scheduler.py morning_prep # 开盘前作战计划
  python3 scheduler.py night       # 手动触发夜班深度分析
  python3 scheduler.py analyze 002221         # 个股诊断
  python3 scheduler.py analyze 002221 --push  # 诊断并推微信
  python3 scheduler.py analyze 002221,600519  # 批量诊断

建议:
  caffeinate -i python3 scheduler.py   # 防止 macOS 休眠
"""

import sys
import os
import time
import traceback
from datetime import datetime, date

import schedule

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    SCHEDULE_AUCTION, SCHEDULE_BREAKOUT, SCHEDULE_AFTERNOON,
    SCHEDULE_DIP_BUY, SCHEDULE_CONSOLIDATION,
    SCHEDULE_TREND_FOLLOW, SCHEDULE_SECTOR_ROTATION,
    SCHEDULE_NEWS_EVENT,
    SCHEDULE_FUTURES_DAY, SCHEDULE_FUTURES_NIGHT,
    SCHEDULE_CRYPTO, SCHEDULE_US_STOCK, SCHEDULE_CROSS_MARKET,
    SCHEDULE_MORNING_PREP,
    TOP_N, CN_HOLIDAYS_2026, CN_WORKDAYS_2026,
    SMART_TRADE_ENABLED,
)
from notifier import (
    notify_all, notify_exit, clear_ths_watchlist,
    notify_terminal, notify_macos, export_ths_watchlist,
    notify_batch_wechat,
)
from log_config import get_logger

logger = get_logger("scheduler")

# ================================================================
#  Dashboard 实时推送 (HTTP → WebSocket)
# ================================================================

_DASHBOARD_URL = "http://127.0.0.1:8501/api/push_event"


def _push_dashboard_event(event_type: str, payload: dict):
    """向 Dashboard 推送事件 (非阻塞, 失败静默)"""
    import urllib.request
    import json as _json
    try:
        req = urllib.request.Request(
            _DASHBOARD_URL,
            data=_json.dumps({"type": event_type, "payload": payload}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


# ================================================================
#  批量推送缓冲区
# ================================================================
_batch_buffer = {
    "morning": [],     # 09:25 集合竞价
    "midday": [],      # 09:50-10:15 放量突破+低吸+缩量+趋势
    "afternoon": [],   # 14:00-14:30 尾盘+板块轮动
}

# 持仓监控时间点
SCHEDULE_MONITOR = ["10:30", "11:15", "13:30", "14:50"]


def _notify_zero_result(time_slot: str, strategies: str):
    """零产出 → 简短心跳, 不发长篇空表格"""
    try:
        from notifier import notify_alert, LEVEL_INFO
        notify_alert(LEVEL_INFO, f"{time_slot} 心跳", f"策略正常运行, 本轮无推荐")
    except Exception as e:
        logger.warning("零产出通知失败: %s", e)


def _notify_scheduler_event(event: str, detail: str = ""):
    """推送调度器关键事件 (启动/重启/异常)"""
    try:
        from notifier import notify_wechat_raw
        now_str = datetime.now().strftime("%H:%M")
        notify_wechat_raw(f"[{now_str}] 调度器{event}", detail or f"调度器已{event}")
    except Exception as e:
        logger.warning("调度器事件通知失败: %s", e)


# ================================================================
#  交易日判断
# ================================================================

_trading_date_cache = {}  # {date_str: bool}


def _fetch_trading_dates():
    """通过 akshare API 获取交易日历 (每日缓存一次)"""
    today_str = date.today().isoformat()
    if today_str in _trading_date_cache:
        return _trading_date_cache[today_str]

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        col = "trade_date"
        if col not in df.columns:
            col = df.columns[0]
        trade_dates = set(df[col].astype(str).str[:10].tolist())
        is_td = today_str in trade_dates
        _trading_date_cache[today_str] = is_td
        return is_td
    except Exception:
        return None  # API 失败, 由 fallback 处理


def is_trading_day():
    """判断今天是否为交易日"""
    today = date.today()
    today_str = today.isoformat()

    # 优先用 API
    api_result = _fetch_trading_dates()
    if api_result is not None:
        tag = "交易日" if api_result else "非交易日"
        print(f"  [交易日判断-API] {today_str} → {tag}")
        return api_result

    # Fallback: 硬编码节假日 + 周末
    print("  [交易日判断] API不可用, 使用本地日历")
    weekday = today.weekday()  # 0=周一, 6=周日

    # 调休补班日 (周末但需上班)
    if today_str in CN_WORKDAYS_2026:
        print(f"  [交易日判断-本地] {today_str} 调休补班 → 交易日")
        return True

    # 法定节假日
    if today_str in CN_HOLIDAYS_2026:
        print(f"  [交易日判断-本地] {today_str} 法定假日 → 非交易日")
        return False

    # 周末
    if weekday >= 5:
        print(f"  [交易日判断-本地] {today_str} 周末 → 非交易日")
        return False

    print(f"  [交易日判断-本地] {today_str} 工作日 → 交易日")
    return True


# ================================================================
#  策略运行 (带重试)
# ================================================================

MAX_RETRIES = 2


def run_with_retry(strategy_func, strategy_name, skip_wechat=False):
    """运行策略, 最多重试 MAX_RETRIES 次; 成功后自动记录持仓

    Args:
        skip_wechat: True 时只走终端/macOS/同花顺通知, 不发微信 (由批量推送统一处理)
    """
    t0 = time.time()

    # Safe Mode 检查: 降级模式下跳过策略扫描
    try:
        from api_guard import is_safe_mode
        if is_safe_mode():
            print(f"[Safe Mode] 跳过策略 {strategy_name} (系统处于降级模式)")
            try:
                from watchdog import update_strategy_status
                update_strategy_status(strategy_name, "skipped_safe_mode")
            except Exception:
                pass
            return
    except Exception:
        pass

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"\n{'#' * 60}")
            print(f"  运行策略: {strategy_name} (第 {attempt} 次)")
            print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#' * 60}")

            items = strategy_func(top_n=TOP_N)
            elapsed = time.time() - t0

            # 先记录原始推荐到 trade_journal (风控过滤前, 确保不遗漏)
            try:
                from learning_engine import record_trade_context
                record_trade_context(strategy_name, items or [])
            except Exception:
                pass

            # 风控过滤
            try:
                from risk_manager import filter_recommendations
                items = filter_recommendations(strategy_name, items)
            except Exception as e:
                print(f"[风控过滤异常] {e}")

            # 仓位建议 (组合分配 + 动态仓位)
            try:
                from risk_manager import get_position_sizing
                items = get_position_sizing(100000, items, strategy_name=strategy_name)
            except Exception as e:
                print(f"[仓位建议异常] {e}")

            # 通知: 批量模式只走终端/macOS/THS, 微信由 batch 统一发
            if skip_wechat:
                notify_terminal(strategy_name, items)
                notify_macos(strategy_name, items)
                export_ths_watchlist(strategy_name, items)
            else:
                notify_all(strategy_name, items)

            # 策略成功后自动记录持仓
            try:
                from position_manager import record_entry
                record_entry(strategy_name, items)
            except Exception as e:
                print(f"[持仓记录异常] {e}")

            # 纸盘自动开仓
            try:
                from paper_trader import on_strategy_picks
                opened = on_strategy_picks(items, strategy_name)
                if opened:
                    print(f"[纸盘] {strategy_name} 自动开仓 {len(opened)} 笔")
            except Exception as e:
                print(f"[纸盘开仓异常] {e}")

            # 更新 watchdog 状态
            try:
                from watchdog import update_strategy_status
                update_strategy_status(strategy_name, "success", duration_sec=elapsed)
            except Exception:
                pass

            # 推送 Dashboard 实时事件
            try:
                _push_dashboard_event("strategy_complete", {
                    "strategy": strategy_name,
                    "count": len(items) if items else 0,
                    "elapsed": round(elapsed, 1),
                    "picks": [{"code": it.get("code"), "name": it.get("name"),
                               "score": round(it.get("score", 0), 3)}
                              for it in (items or [])[:5]],
                })
            except Exception:
                pass

            return items

        except Exception as e:
            print(f"\n[策略异常] {strategy_name} 第 {attempt} 次失败:")
            traceback.print_exc()
            if attempt < MAX_RETRIES:
                wait = 60 * attempt
                print(f"  等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                # 报告失败状态
                try:
                    from watchdog import update_strategy_status
                    update_strategy_status(strategy_name, "failed", error_msg=str(e))
                except Exception:
                    pass
                # 推送 Dashboard 失败事件
                try:
                    _push_dashboard_event("strategy_failed", {
                        "strategy": strategy_name,
                        "error": str(e)[:200],
                    })
                except Exception:
                    pass
                # 发射失败事件到事件总线
                try:
                    from event_bus import get_event_bus, Priority
                    bus = get_event_bus()
                    bus.emit(
                        source="scheduler",
                        priority=Priority.URGENT,
                        event_type="job_failed",
                        category="strategy",
                        payload={
                            "strategy": strategy_name,
                            "error": str(e),
                            "message": f"{strategy_name} 重试{MAX_RETRIES}次后仍失败: {e}",
                        },
                    )
                except Exception:
                    pass
                # 最终失败通知 (终端+macOS)
                error_msg = f"{strategy_name} 运行失败: {type(e).__name__}: {e}"
                error_items = [{
                    "code": "ERROR",
                    "name": "策略异常",
                    "price": 0,
                    "score": 0,
                    "reason": error_msg,
                }]
                notify_terminal(strategy_name, error_items)
                notify_macos(strategy_name, error_items)
                # 微信通知策略失败 — 失败也必须回响
                try:
                    from notifier import notify_wechat_raw
                    now_str = datetime.now().strftime("%H:%M")
                    notify_wechat_raw(
                        f"[{now_str}] 策略异常: {strategy_name}",
                        f"重试{MAX_RETRIES}次后仍失败\n错误: {type(e).__name__}: {e}",
                    )
                except Exception:
                    pass
                return []


# ================================================================
#  各策略入口
# ================================================================

def _check_market_regime():
    """策略运行前检查大盘环境 (v2.0 — 8信号评分制)

    返回 (should_run, regime_str, regime_result)
    regime_result: detect_market_regime() 的完整返回值, 供学习引擎记录
    """
    if not SMART_TRADE_ENABLED:
        return True, "", None
    try:
        from smart_trader import detect_market_regime
        regime = detect_market_regime()
        regime_str = regime.get("regime", "neutral")
        score = regime.get("score", 0)
        rp = regime.get("regime_params", {})
        scale = rp.get("position_scale", regime.get("position_scale", 1.0))

        logger.info("大盘环境: %s (score=%.2f, scale=%.1f, max_pos=%d)",
                     regime_str, score, scale, rp.get("max_positions", 9))

        # 打印信号明细
        signals = regime.get("signals", {})
        if signals:
            sig_str = " | ".join(f"{k}={v:.2f}" for k, v in signals.items())
            logger.info("信号明细: %s", sig_str)

        if regime_str == "bear":
            return False, regime_str, regime
        if regime_str == "weak":
            logger.info("弱势市场, 允许运行 (仓位自动缩放至%.0f%%)", scale * 100)
        return True, regime_str, regime
    except Exception as e:
        logger.warning("大盘检测失败: %s, 默认允许运行", e)
        return True, "unknown", {"regime": "unknown", "score": 0.5, "signals": {}, "error": str(e)}


# ================================================================
#  A 股策略: 由 strategy_loader 从 strategies.json 动态加载
#  (8 个策略已移至 strategies.json, 通过 register_strategies 注册)
# ================================================================


# ================================================================
#  期货趋势策略
# ================================================================

def _is_futures_trading_day():
    """期货交易日: 仅跳过周六日 (不受股票节假日限制)"""
    return datetime.now().weekday() < 5


def _execute_futures_trades(items):
    """调用交易执行器开仓 (信号→交易)"""
    try:
        from trade_executor import execute_signals
        from config import TRADE_EXECUTOR_PARAMS
        mode = TRADE_EXECUTOR_PARAMS.get("mode", "paper")
        # 补充完整字段 (run_with_retry 输出的标准格式可能缺少部分字段)
        from futures_strategy import run_futures_scan
        # items 已经是标准推荐格式, 直接传给执行器
        executed = execute_signals(items, mode=mode)
        if executed:
            mode_label = {"paper": "模拟", "simnow": "SimNow", "live": "实盘"}.get(mode, mode)
            logger.info("[交易执行] %s模式 开仓 %d 笔", mode_label, len(executed))
    except Exception as e:
        logger.warning("[交易执行异常] %s", e)


def job_futures_monitor():
    """期货持仓监控: 检查止损止盈"""
    if not _is_futures_trading_day():
        return
    try:
        from trade_executor import check_futures_exits, get_portfolio_status
        print(f"\n{'─' * 60}")
        print(f"  期货持仓监控  {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'─' * 60}")
        exits = check_futures_exits()
        if exits:
            from notifier import notify_wechat_raw
            lines = ["期货持仓止损/止盈触发:"]
            for e in exits:
                dir_l = "多" if e.get("direction") == "long" else "空"
                lines.append(
                    f"  {e['code']} {e.get('name','')} {dir_l} "
                    f"{e['entry_price']:.2f}→{e['exit_price']:.2f} "
                    f"{e['exit_reason']} {e['pnl_pct']:+.2f}% "
                    f"¥{e.get('pnl_amount', 0):+.2f}")
            try:
                notify_wechat_raw("[期货] 平仓通知", "\n".join(lines))
            except Exception:
                pass
            print("\n".join(lines))
        else:
            # 打印当前持仓概况
            portfolio = get_portfolio_status()
            if portfolio["count"] > 0:
                print(f"  持仓 {portfolio['count']}个  浮动盈亏 ¥{portfolio['total_pnl']:.2f}")
            else:
                print("  无期货持仓")
    except Exception as e:
        print(f"[期货监控异常] {e}")


# ================================================================
#  期货/币圈/美股策略: 由 strategy_loader 从 strategies.json 动态加载
#  (4 个直推策略已移至 strategies.json, 通过 register_strategies 注册)
# ================================================================


def job_cross_market():
    """06:00 跨市场信号推演 (美股收盘+夜盘收盘后)"""
    from cross_market_strategy import get_cross_market_signal
    from notifier import notify_wechat_raw
    result = get_cross_market_signal()
    # 注入事件总线 — 让 Agent Brain 感知跨市场信号
    if result and result.get("a_stock_impact") in ("bullish", "bearish"):
        try:
            from event_bus import get_event_bus, Priority
            bus = get_event_bus()
            impact = result["a_stock_impact"]
            p = Priority.HIGH if abs(result.get("composite_signal", 0)) > 0.5 else Priority.NORMAL
            bus.emit(
                source="cross_market",
                priority=p,
                event_type="cross_market_signal",
                category="regime",
                payload={
                    "impact": impact,
                    "composite_signal": result.get("composite_signal", 0),
                    "suggestion": result.get("suggestion", ""),
                    "message": f"跨市场信号: {impact} (综合{result.get('composite_signal', 0):+.3f})",
                },
            )
        except Exception:
            pass
    if result:
        impact_map = {"bullish": "利多▲", "bearish": "利空▼", "neutral": "中性─"}
        lines = [
            f"综合信号: {result.get('composite_signal', 0):+.3f} → "
            f"{impact_map.get(result.get('a_stock_impact', ''), '?')}",
            f"美股{result.get('us_signal', 0):+.3f} | "
            f"A50{result.get('a50_signal', 0):+.3f} | "
            f"币圈{result.get('crypto_signal', 0):+.3f}",
        ]
        for d in result.get("details", []):
            lines.append(d)
        lines.append(f"\n建议: {result.get('suggestion', '')}")
        try:
            notify_wechat_raw(f"[{SCHEDULE_CROSS_MARKET}] 跨市场信号推演", "\n".join(lines))
        except Exception:
            pass


def job_morning_prep():
    """07:30 开盘前作战计划"""
    from morning_prep import run_morning_prep
    from notifier import notify_wechat_raw
    result = run_morning_prep()
    if result and result.get("plan_text"):
        try:
            notify_wechat_raw(f"[{SCHEDULE_MORNING_PREP}] 开盘作战计划", result["plan_text"])
        except Exception:
            pass


def job_reset_api_stats():
    """00:05 每日重置 API 统计"""
    try:
        from api_guard import reset_daily_stats, get_api_stats
        stats = get_api_stats()
        logger.info("API 日统计: calls=%d cache_hits=%d retries=%d errors=%d rate_limited=%d",
                     stats["total_calls"], stats["cache_hits"], stats["retries"],
                     stats["errors"], stats["rate_limited"])
        reset_daily_stats()
    except Exception:
        pass


# ================================================================
#  批量推送任务
# ================================================================

def job_batch_morning():
    """09:35 合并发送上午早盘结果 (集合竞价)"""
    if not is_trading_day():
        return
    buf = _batch_buffer["morning"]
    if buf:
        notify_batch_wechat("早盘选股汇总", buf)
    else:
        _notify_zero_result("09:35 早盘选股", "事件驱动+集合竞价")
    _batch_buffer["morning"] = []


def job_batch_midday():
    """10:30 合并发送盘中结果 (放量突破+低吸+缩量+趋势)"""
    if not is_trading_day():
        return
    buf = _batch_buffer["midday"]
    if buf:
        notify_batch_wechat("盘中选股汇总", buf)
    else:
        _notify_zero_result("10:30 盘中选股", "放量突破+低吸回调+缩量整理+趋势跟踪")
    _batch_buffer["midday"] = []


def job_batch_afternoon():
    """14:50 合并发送午后结果 (尾盘+板块轮动)"""
    if not is_trading_day():
        return
    buf = _batch_buffer["afternoon"]
    if buf:
        notify_batch_wechat("午后选股汇总", buf)
    else:
        _notify_zero_result("14:50 午后选股", "尾盘短线+板块轮动")
    _batch_buffer["afternoon"] = []


# ================================================================
#  学习引擎钩子
# ================================================================

def _record_learning(items, strategy_name, regime_result):
    """策略运行后记录上下文 (供学习引擎分析)"""
    try:
        from learning_engine import record_trade_context
        record_trade_context(strategy_name, items or [], regime_result)
    except Exception as e:
        print(f"[学习记录异常] {e}")


def job_learning():
    """16:30 运行学习引擎"""
    if not is_trading_day():
        return
    try:
        from learning_engine import run_learning_cycle
        run_learning_cycle()
    except Exception as e:
        print(f"[学习引擎异常] {e}")


def job_signal_tracker():
    """16:15 信号追踪: 入库今日信号 + 回查历史信号 T+1/T+3/T+5 结果"""
    if not is_trading_day():
        return
    try:
        from signal_tracker import daily_ingest_and_verify
        result = daily_ingest_and_verify()
        print(f"[信号追踪] {result['stats_summary']}")
    except Exception as e:
        print(f"[信号追踪异常] {e}")


# ================================================================
#  系统状态面板
# ================================================================

def _show_system_status():
    """一屏看系统全貌: 进程/策略/持仓/信号/风控/健康"""
    from datetime import datetime

    print("=" * 60)
    print("  量化多因子系统 — 状态面板")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 进程状态
    try:
        from watchdog import check_health
        h = check_health()
        tag = "正常" if h["healthy"] else "异常"
        print(f"\n[进程] {tag}")
        if h.get("heartbeat_age_sec") is not None:
            print(f"  心跳: {h['heartbeat_age_sec']:.0f}s 前")
        print(f"  进程: {'存活' if h['process_alive'] else '不存在'}")
        print(f"  今日错误: {h.get('errors_today', 0)}")
        if h["issues"]:
            for i in h["issues"]:
                print(f"  !! {i}")
    except Exception as e:
        print(f"\n[进程] 检查失败: {e}")

    # 2. 今日策略运行
    try:
        from json_store import safe_load
        hb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heartbeat.json")
        hb = safe_load(hb_path, default={})
        status = hb.get("strategy_status", {})
        if status:
            print(f"\n[今日策略]")
            for name, info in status.items():
                s = info.get("status", "?")
                t = info.get("last_run", "")[:16]
                d = info.get("duration_sec", 0)
                tag = "OK" if s == "success" else "FAIL"
                err = f" | {info.get('error_msg', '')}" if s == "failed" else ""
                print(f"  [{tag}] {name}: {t} ({d:.0f}s){err}")
        else:
            print("\n[今日策略] 无运行记录")
    except Exception:
        pass

    # 3. 持仓 (严格模式: 文件损坏则熔断告警)
    try:
        from position_manager import get_positions
        pos = get_positions()
        print(f"\n[A股持仓] {len(pos)} 只")
        for p in pos[:5]:
            print(f"  {p.get('code', '?')} {p.get('name', '?')}"
                  f" 入:{p.get('entry_price', 0):.2f}"
                  f" 分:{p.get('score', 0):.2f}")
        if len(pos) > 5:
            print(f"  ... 共 {len(pos)} 只")
    except ValueError as e:
        print(f"\n[A股持仓] !! 熔断: positions.json 损坏 — {e}")
        logger.error("positions.json 严格模式熔断: %s", e)
    except Exception:
        print("\n[A股持仓] 无数据")

    # 4. 纸盘
    try:
        from paper_trader import get_holdings_summary, calc_statistics
        holdings = get_holdings_summary()
        stats = calc_statistics(days=7)
        print(f"\n[纸盘模拟]")
        print(f"  持仓: {holdings.get('count', 0)} 笔"
              f" | 资金: {holdings.get('available_capital', 0):.0f}")
        if stats.get("total", 0) > 0:
            print(f"  7天: {stats['total']}笔"
                  f" | 胜率{stats['win_rate']}%"
                  f" | 收益{stats['total_pnl']:+.2f}%")
    except Exception:
        pass

    # 5. 信号追踪
    try:
        from signal_tracker import get_stats
        sig = get_stats(days=7)
        if sig.get("total", 0) > 0:
            o = sig["overall"]
            print(f"\n[信号追踪 7天] {sig['total']} 条信号")
            for p in [1, 3, 5]:
                wr = o.get(f"t{p}_win_rate")
                avg = o.get(f"avg_t{p}")
                if wr is not None:
                    print(f"  T+{p}: 胜率{wr}% 均收{avg:+.2f}%")
        else:
            print(f"\n[信号追踪] 暂无数据")
    except Exception:
        pass

    # 6. VaR 风控
    try:
        from json_store import safe_load as _sl
        var_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "var_results.json")
        history = _sl(var_path, default=[])
        if history:
            latest = history[-1]
            rating = latest.get("risk_rating", "?")
            p = latest.get("portfolio", {})
            print(f"\n[VaR风控] 评级: {rating}")
            print(f"  VaR(95%): {p.get('hist_var_95', 0):+.4f}%"
                  f" | CVaR(99%): {p.get('hist_cvar_99', 0):+.4f}%")
    except Exception:
        pass

    # 7. 夜班
    try:
        from json_store import safe_load as _sl2
        nl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "night_shift_log.json")
        nl = _sl2(nl_path, default={})
        if nl.get("date"):
            status = nl.get("status", "?")
            tasks = nl.get("tasks", {})
            ok = sum(1 for t in tasks.values() if isinstance(t, dict) and t.get("status") == "ok")
            fail = sum(1 for t in tasks.values() if isinstance(t, dict) and t.get("status") in ("error", "timeout"))
            print(f"\n[夜班] {nl['date']} {status}")
            print(f"  成功: {ok} | 失败: {fail} | 总: {len(tasks)}")
    except Exception:
        pass

    print(f"\n{'=' * 60}")


# ================================================================
#  持仓监控任务
# ================================================================

def job_monitor():
    """持仓监控定时任务: 检查止损止盈 + 动态持仓期强制离场

    卖出信号仅走终端+macOS通知, 不消耗微信配额
    """
    if not is_trading_day():
        return
    try:
        from position_manager import check_exit_signals
        from notifier import format_exit_signal
        print(f"\n{'─' * 60}")
        print(f"  持仓监控  {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'─' * 60}")
        exits = check_exit_signals()
        if exits:
            # 终端 + macOS 通知, 不走微信 (节省配额)
            title, body = format_exit_signal(exits)
            print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}\n{body}\n{'=' * 60}\n")
            try:
                import subprocess
                short_body = body[:200] if len(body) > 200 else body
                safe_title = title.replace('"', '\\"')
                safe_body = short_body.replace('"', '\\"')
                script = (
                    f'display notification "{safe_body}" '
                    f'with title "{safe_title}" '
                    f'sound name "Sosumi"'
                )
                subprocess.run(["osascript", "-e", script], timeout=10, capture_output=True)
            except Exception:
                pass
    except Exception as e:
        print(f"[持仓监控异常] {e}")


# ================================================================
#  调度器
# ================================================================

def job_scorecard():
    """09:20 评分昨日推荐 + 更新黑名单 + 刷新 Agent 策略状态"""
    if not is_trading_day():
        return
    try:
        from scorecard import score_yesterday
        score_yesterday()
    except ValueError as e:
        print(f"[记分卡熔断] scorecard.json/positions.json 损坏 — {e}")
        logger.error("scorecard 严格模式熔断: %s", e)
    except Exception as e:
        print(f"[记分卡异常] {e}")
    try:
        from risk_manager import update_blacklist
        update_blacklist()
    except Exception as e:
        print(f"[黑名单更新异常] {e}")
    try:
        from agent_brain import update_strategy_states
        update_strategy_states()
    except Exception as e:
        print(f"[Agent状态更新异常] {e}")


def job_weekly_report():
    """周五 15:30 推送周报 (含健康报告 + 优化建议)"""
    if not is_trading_day():
        return
    try:
        from scorecard import generate_weekly_report, notify_scorecard
        report = generate_weekly_report()
        # 附加健康报告
        try:
            from self_healer import generate_health_report
            report += "\n\n---\n\n" + generate_health_report()
        except Exception:
            pass
        # 附加优化建议
        try:
            from auto_optimizer import generate_optimization_summary
            report += "\n\n---\n\n" + generate_optimization_summary()
        except Exception:
            pass
        notify_scorecard(report)
    except ValueError as e:
        print(f"[周报熔断] scorecard.json 损坏 — {e}")
        logger.error("周报 严格模式熔断: %s", e)
    except Exception as e:
        print(f"[周报异常] {e}")


# ================================================================
#  Agent Brain 定时任务
# ================================================================

def job_agent_morning():
    """09:15 推送早报"""
    if not is_trading_day():
        return
    try:
        from agent_brain import push_morning_briefing
        push_morning_briefing()
    except Exception as e:
        print(f"[Agent早报异常] {e}")


def job_agent_evening():
    """16:15 运行 OODA 循环 + 晚间摘要推送"""
    if not is_trading_day():
        return
    try:
        from agent_brain import run_agent_cycle, generate_evening_summary
        summary = run_agent_cycle()
        print(summary)
        # 推送晚间摘要到微信
        evening = generate_evening_summary()
        if evening:
            from notifier import notify_wechat_raw
            now_str = datetime.now().strftime("%H:%M")
            notify_wechat_raw(f"[{now_str}] Agent 晚间摘要", evening)
    except Exception as e:
        print(f"[Agent OODA异常] {e}")


def job_night_shift():
    """22:30 夜班: LLM 深度复盘/因子体检/明日预判/认知沉淀"""
    if not is_trading_day():
        return
    run_with_retry(_run_night_shift, "夜班分析")


def _run_night_shift(**kwargs):
    """夜班深度分析 (接受 **kwargs 兼容 run_with_retry 的 top_n 参数)"""
    from agent_brain import run_night_shift
    report = run_night_shift()
    if report:
        print(f"[夜班] 分析完成, 报告 {len(report)} 字")
    else:
        print("[夜班] LLM 不可用或无分析结果")
    return []  # run_with_retry 期望返回 list


# ================================================================
#  冒烟测试 / 自动优化 / 周末搜索
# ================================================================

def job_smoke_test():
    """09:10 开盘前冒烟测试"""
    if not is_trading_day():
        return
    try:
        from self_healer import run_smoke_test, auto_heal
        result = run_smoke_test()
        if not result["passed"]:
            auto_heal()  # 尝试自动修复
    except Exception as e:
        print(f"[冒烟测试异常] {e}")


def job_daily_optimize():
    """16:00 收盘后每日优化"""
    if not is_trading_day():
        return
    try:
        from auto_optimizer import run_daily_optimization
        run_daily_optimization()
    except Exception as e:
        print(f"[每日优化异常] {e}")


def job_var_risk():
    """16:10 收盘后 VaR/CVaR 风险度量"""
    if not is_trading_day():
        return
    try:
        from var_risk import calc_comprehensive_var
        result = calc_comprehensive_var(lookback_days=60)
        rating = result.get("risk_rating", "unknown")
        var95 = result.get("portfolio", {}).get("hist_var_95", 0)
        print(f"[VaR] 风险评级: {rating}, VaR(95%): {var95:+.4f}%")

        # 高风险时推送告警
        if rating == "high":
            try:
                from var_risk import generate_var_report
                from notifier import notify_alert, LEVEL_CRITICAL
                report = generate_var_report(result)
                notify_alert(LEVEL_CRITICAL, "高风险告警", report)
            except Exception:
                pass
    except Exception as e:
        print(f"[VaR异常] {e}")


def job_weekend_optimize():
    """周六 10:00 深度搜索"""
    try:
        from auto_optimizer import run_weekend_broad_search
        run_weekend_broad_search()
    except Exception as e:
        print(f"[周末优化异常] {e}")


def job_verify_optimizations():
    """16:50 验证近期优化效果, 变差则自动回滚"""
    if not is_trading_day():
        return
    try:
        from auto_optimizer import check_pending_verifications
        results = check_pending_verifications()
        for r in results:
            verdict = r.get("verdict", "")
            strategy = r.get("strategy", "")
            pre = r.get("pre_score", 0)
            post = r.get("post_score", 0)
            print(f"[优化验证] {strategy}: {verdict} ({pre}→{post})")
            if verdict == "rolled_back":
                # 回滚通知仅终端+macOS, 不消耗微信配额 (留给晚报汇总)
                logger.warning("[优化回滚] %s 验证失败 (%d→%d), 已自动回滚",
                               strategy, pre, post)
                try:
                    import subprocess
                    msg = f"{strategy} 优化验证失败 ({pre}→{post}), 已自动回滚"
                    subprocess.run(
                        ["osascript", "-e",
                         f'display notification "{msg}" with title "[Agent] 优化回滚" sound name "Basso"'],
                        timeout=10, capture_output=True,
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"[优化验证异常] {e}")


def job_factor_lifecycle():
    """17:00 检查因子健康, 淘汰衰减因子"""
    if not is_trading_day():
        return
    try:
        from auto_optimizer import check_factor_lifecycle
        results = check_factor_lifecycle()
        for r in results:
            print(f"[因子生命周期] {r.get('strategy')}: {r.get('factor')} → {r.get('action')}")
    except Exception as e:
        print(f"[因子生命周期异常] {e}")


def job_stock_diagnosis():
    """10:00/13:00 盘中自动诊断: 持仓+今日推荐, 异常推送微信"""
    if not is_trading_day():
        return
    try:
        from position_manager import load_positions
        from stock_analyzer import analyze_stock
        from db_store import load_trade_journal
        from notifier import notify_wechat_raw
        from datetime import date as _date

        today_str = _date.today().isoformat()

        # 收集需要诊断的代码: 持仓 + 今日推荐
        codes_to_check = {}  # code -> source

        # 1) 持仓
        try:
            positions = load_positions()
            holding = [p for p in positions if not p.get("exit_date")]
            for p in holding:
                codes_to_check[p["code"]] = f"持仓({p.get('strategy', '')})"
        except Exception:
            pass

        # 2) 今日推荐 (从 trade_journal)
        try:
            journal = load_trade_journal(days=0)
            for entry in journal:
                if entry.get("date") == today_str:
                    for pick in entry.get("picks", []):
                        code = pick.get("code", "")
                        if code and len(code) == 6:  # 只诊断A股
                            codes_to_check.setdefault(code, f"推荐({entry.get('strategy', '')})")
        except Exception:
            pass

        # 3) 昨日推荐也跟踪
        try:
            journal_2d = load_trade_journal(days=1)
            for entry in journal_2d:
                if entry.get("date") != today_str:
                    for pick in entry.get("picks", []):
                        code = pick.get("code", "")
                        if code and len(code) == 6:
                            codes_to_check.setdefault(code, f"昨推({entry.get('strategy', '')})")
        except Exception:
            pass

        if not codes_to_check:
            print("[诊断] 无持仓/推荐, 跳过")
            return

        print(f"[诊断] 开始诊断 {len(codes_to_check)} 只...")
        alerts = []  # 需要告警的

        for code, source in codes_to_check.items():
            try:
                result = analyze_stock(code)
                if "error" in result:
                    continue

                name = result.get("name", code)
                price = result.get("price", 0)
                total = result.get("total_score", 0.5)
                verdict = result.get("verdict", "")
                stop_loss = result.get("stop_loss", 0)
                scores = result.get("scores", {})

                # 告警条件: 看空 / 跌破止损 / 动量极弱
                alert_reasons = []
                if total <= 0.40:
                    alert_reasons.append(f"评分{total:.2f}偏低")
                if result.get("direction") == "bearish":
                    alert_reasons.append("信号看空")
                if scores.get("momentum", 0.5) <= 0.30:
                    alert_reasons.append(f"动量极弱({scores['momentum']:.2f})")
                if scores.get("volume", 0.5) <= 0.30:
                    alert_reasons.append(f"量价异常({scores['volume']:.2f})")

                status = "正常" if not alert_reasons else "⚠告警"
                print(f"  {code}({name}) [{source}] {total:.2f} {verdict} {status}")

                if alert_reasons:
                    alerts.append({
                        "code": code, "name": name, "source": source,
                        "price": price, "total": total, "verdict": verdict,
                        "stop_loss": stop_loss, "reasons": alert_reasons,
                        "report": result.get("report_text", ""),
                    })
            except Exception as e:
                print(f"  {code} 诊断失败: {e}")

        # 有告警就推送微信
        if alerts:
            lines = [f"盘中诊断告警 ({len(alerts)}只异常)\n"]
            for a in alerts:
                lines.append(
                    f"⚠ {a['name']}({a['code']}) [{a['source']}]\n"
                    f"  现价{a['price']:.2f} 评分{a['total']:.2f} {a['verdict']}\n"
                    f"  止损位: {a['stop_loss']}\n"
                    f"  原因: {', '.join(a['reasons'])}\n"
                )
            from notifier import notify_alert, LEVEL_WARNING
            notify_alert(LEVEL_WARNING, "盘中诊断告警", "\n".join(lines))
            print(f"[诊断] {len(alerts)} 只告警已推送微信")
        else:
            print(f"[诊断] {len(codes_to_check)} 只全部正常")

    except Exception as e:
        print(f"[诊断异常] {e}")
        import traceback
        traceback.print_exc()


def job_paper_monitor():
    """11:00/14:00 纸盘持仓监控 (止损/止盈检查)"""
    if not is_trading_day():
        return
    try:
        from paper_trader import check_exits
        exits = check_exits()
        if exits:
            for e in exits:
                print(f"[纸盘] {e['code']} {e.get('name','')} "
                      f"{e.get('net_pnl_pct',0):+.2f}% [{e.get('reason','')}]")
    except Exception as e:
        print(f"[纸盘监控异常] {e}")


def job_paper_settle():
    """15:30 纸盘日终结算"""
    if not is_trading_day():
        return
    try:
        from paper_trader import daily_settle, generate_paper_report
        result = daily_settle()
        n = result.get("trades_today", 0)
        if n > 0:
            print(f"[纸盘结算] {n}笔, PnL {result.get('pnl_today',0):+.2f}%")
    except Exception as e:
        print(f"[纸盘结算异常] {e}")


def job_broker_monitor():
    """10:30/13:30/14:45 券商持仓监控 (止损/止盈)"""
    if not is_trading_day():
        return
    try:
        from broker_executor import check_exit_signals, check_kill_switches
        can, reason = check_kill_switches()
        if not can:
            print(f"[券商] Kill switch: {reason}")
            return
        exits = check_exit_signals()
        for e in exits:
            print(f"[券商] {e.get('code', '')} {e.get('name', '')} "
                  f"{e.get('net_pnl_pct', 0):+.2f}% [{e.get('exit_reason', '')}]")
    except Exception as e:
        print(f"[券商监控异常] {e}")


def job_ml_train():
    """17:10 ML 因子模型增量训练 (每日)"""
    if not is_trading_day():
        return
    try:
        from ml_factor_model import train_model
        result = train_model(lookback_days=180)
        if "error" in result:
            print(f"[ML训练] 跳过: {result['error']}")
        else:
            samples = result.get("training_samples", 0)
            features = len(result.get("features", []))
            print(f"[ML训练] 完成: {samples}条 {features}特征")
            # 特征重要性 top3
            fi = result.get("feature_importance", {})
            top3 = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:3]
            if top3:
                print(f"[ML训练] Top特征: {', '.join(f'{k}={v:.3f}' for k, v in top3)}")
    except Exception as e:
        print(f"[ML训练异常] {e}")


def job_proactive_experiment():
    """16:45 主动扫描低健康度策略, 触发实验"""
    if not is_trading_day():
        return
    try:
        from config import EXPERIMENT_PARAMS
        if not EXPERIMENT_PARAMS.get("enabled", True):
            return
        from auto_optimizer import evaluate_strategy_health
        from experiment_lab import (
            design_experiment, run_experiment, adopt_experiment_result,
            _check_cooldown, _count_running, EXPERIMENT_PARAMS as EP,
        )
        from experiment_lab import _EXPERIMENTS_PATH
        from json_store import safe_load, safe_save

        threshold = EP.get("min_health_score_trigger", 50)
        max_concurrent = EP.get("max_concurrent_experiments", 2)
        strategy_map = {"breakout": "放量突破选股", "auction": "集合竞价选股",
                        "afternoon": "尾盘短线选股", "dip_buy": "低吸回调选股",
                        "consolidation": "缩量整理选股", "trend_follow": "趋势跟踪选股",
                        "sector_rotation": "板块轮动选股", "news_event": "事件驱动选股",
                        "futures_trend": "期货趋势选股"}

        for eng, cn in strategy_map.items():
            if _count_running() >= max_concurrent:
                break
            if _check_cooldown(eng):
                continue
            health = evaluate_strategy_health(eng)
            if health.get("score", 100) >= threshold:
                continue
            # 构造一个虚拟 finding 触发实验
            finding = {
                "severity": "warning",
                "message": f"{cn}健康度{health.get('score', 0):.0f}分, 主动实验",
                "suggested_action": "log_insight",
            }
            exp = design_experiment(eng, finding)
            if not exp:
                continue
            exp["status"] = "running"
            history = safe_load(_EXPERIMENTS_PATH, default=[])
            history.append(exp)
            safe_save(_EXPERIMENTS_PATH, history)

            exp = run_experiment(exp)
            if exp.get("conclusion") == "found_better":
                adopt_experiment_result(exp)

            # 更新历史
            history = safe_load(_EXPERIMENTS_PATH, default=[])
            for i, e in enumerate(history):
                if e.get("experiment_id") == exp.get("experiment_id"):
                    history[i] = exp
                    break
            safe_save(_EXPERIMENTS_PATH, history)
            print(f"[主动实验] {eng}: {exp.get('conclusion', '?')}")
    except Exception as e:
        print(f"[主动实验异常] {e}")


def _init_multi_agent():
    """启动时初始化多智能体基础设施"""
    try:
        from agent_registry import get_registry, register_builtin_agents
        registry = get_registry()
        register_builtin_agents(registry)
        registry.persist()
        logger.info("[多智能体] 注册表初始化完成, %d 个智能体", len(registry.list_agents()))
    except ImportError:
        logger.debug("[多智能体] agent_registry 模块不可用")
    except Exception as e:
        logger.warning("[多智能体] 初始化异常: %s", e)


def setup_schedule():
    """设置定时任务"""
    # 初始化多智能体
    _init_multi_agent()

    # 动态加载策略 (从 strategies.json)
    import strategy_loader
    sched_mod = sys.modules[__name__]
    n_strategies = strategy_loader.register_strategies(sched_mod, schedule)
    print(f"  策略加载器: {n_strategies} 个策略已从 strategies.json 动态注册")

    # 3 个批量推送
    schedule.every().day.at("09:26").do(job_batch_morning)
    schedule.every().day.at("10:30").do(job_batch_midday)
    schedule.every().day.at("14:50").do(job_batch_afternoon)

    # 持仓监控
    for t in SCHEDULE_MONITOR:
        schedule.every().day.at(t).do(job_monitor)

    # 每日评分 + 黑名单更新
    schedule.every().day.at("15:35").do(job_scorecard)

    # 每周周报 (周五 15:30)
    schedule.every().friday.at("15:30").do(job_weekly_report)

    # 冒烟测试 + 自动优化 + 学习引擎
    schedule.every().day.at("09:10").do(job_smoke_test)
    schedule.every().day.at("16:00").do(job_daily_optimize)
    schedule.every().day.at("16:05").do(job_signal_tracker)
    schedule.every().day.at("16:10").do(job_var_risk)
    schedule.every().day.at("16:30").do(job_learning)
    schedule.every().day.at("17:10").do(job_ml_train)

    # 盘中自动诊断 (持仓+推荐 实时复诊)
    schedule.every().day.at("10:00").do(job_stock_diagnosis)
    schedule.every().day.at("13:00").do(job_stock_diagnosis)

    # 纸盘模拟交易
    schedule.every().day.at("11:00").do(job_paper_monitor)
    schedule.every().day.at("14:00").do(job_paper_monitor)
    schedule.every().day.at("15:30").do(job_paper_settle)

    # 券商自动下单 (持仓监控)
    schedule.every().day.at("10:30").do(job_broker_monitor)
    schedule.every().day.at("13:30").do(job_broker_monitor)
    schedule.every().day.at("14:45").do(job_broker_monitor)
    schedule.every().saturday.at("10:00").do(job_weekend_optimize)

    # Agent Brain
    schedule.every().day.at("09:15").do(job_agent_morning)
    schedule.every().day.at("16:15").do(job_agent_evening)
    schedule.every().day.at("16:45").do(job_proactive_experiment)
    schedule.every().day.at("16:50").do(job_verify_optimizations)
    schedule.every().day.at("17:00").do(job_factor_lifecycle)
    schedule.every().day.at("22:30").do(job_night_shift)

    # 跨市场信号推演 (夜班期间) — 有事件总线自定义逻辑, 保持硬编码
    schedule.every().day.at(SCHEDULE_CROSS_MARKET).do(job_cross_market)

    # 开盘前作战计划 — 有自定义逻辑, 保持硬编码
    schedule.every().day.at(SCHEDULE_MORNING_PREP).do(job_morning_prep)

    # 期货持仓监控 (日盘: 09:30~15:00, 夜盘: 21:30~23:00)
    for ft in ["09:30", "10:30", "11:15", "13:30", "14:30", "21:30", "22:30"]:
        schedule.every().day.at(ft).do(job_futures_monitor)

    # API 统计重置
    schedule.every().day.at("00:05").do(job_reset_api_stats)

    # 打印已注册任务 (策略部分从 JSON 动态读取)
    print(f"已注册定时任务:")
    for cfg in strategy_loader.load_strategies():
        if cfg.get("enabled", True):
            print(f"  {cfg['schedule']}  → {cfg['name']} (动态)")
    print(f"  09:10  → 冒烟测试 (开盘前)")
    print(f"  09:15  → Agent 早报 [微信1/5]")
    print(f"  09:20  → 昨日推荐评分 + 黑名单更新")
    print(f"  09:35  → 批量推送: 早盘汇总 [微信2/5]")
    print(f"  10:30  → 批量推送: 盘中汇总 [微信3/5]")
    print(f"  14:50  → 批量推送: 午后汇总 [微信4/5]")
    print(f"  {', '.join(SCHEDULE_MONITOR)}  → 持仓监控(止损止盈, 仅终端)")
    print(f"  16:00~17:10  → 优化/信号/VaR/学习/ML训练")
    print(f"  22:30  → 夜班深度分析 (LLM复盘/预判/认知沉淀)")
    print(f"  {SCHEDULE_CROSS_MARKET}  → 跨市场信号推演 (夜班)")
    print(f"  {SCHEDULE_MORNING_PREP}  → 开盘前作战计划")
    print(f"  09:30~22:30  → 期货持仓监控(止损止盈, 7次/日)")
    print(f"  00:05  → API统计重置")


def _start_caffeinate():
    """启动 caffeinate 防止 macOS 休眠 (自动, 无需手动)"""
    import subprocess as _sp
    try:
        proc = _sp.Popen(
            ["caffeinate", "-i", "-w", str(os.getpid())],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
        )
        print(f"  caffeinate 已启动 (PID={proc.pid}), macOS 不会休眠")
        return proc
    except FileNotFoundError:
        print("  caffeinate 不可用 (非 macOS?), 跳过")
        return None


def _start_self_watchdog(interval: int = 300):
    """启动自监控线程: 每 5 分钟检查调度器自身健康

    检查项:
      1. 夜班是否卡死 (night_shift_log 超过 15 分钟无更新)
      2. 主循环心跳是否在更新
    如果异常 → 微信告警
    """
    import threading

    def _watchdog_loop():
        _last_alert_task = None   # 上次告警的任务名
        _last_alert_time = 0.0    # 上次告警时间戳
        _ALERT_COOLDOWN = 3600    # 同一任务1小时内只报一次

        while True:
            time.sleep(interval)
            try:
                night_log_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "night_shift_log.json")
                from json_store import safe_load as _sl
                night_log = _sl(night_log_path, default={})
                if night_log.get("status") == "running":
                    hb = night_log.get("_heartbeat", "")
                    if hb:
                        from datetime import datetime as _dt
                        try:
                            last = _dt.strptime(hb, "%Y-%m-%d %H:%M:%S")
                            age = (_dt.now() - last).total_seconds()
                            task = night_log.get("_current_task", "?")
                            if age > 900:  # 15 分钟无心跳
                                # 冷却: 同一任务1小时内只告警一次
                                now_ts = time.time()
                                if task == _last_alert_task and (now_ts - _last_alert_time) < _ALERT_COOLDOWN:
                                    continue
                                _last_alert_task = task
                                _last_alert_time = now_ts
                                msg = (f"夜班疑似卡死!\n"
                                       f"当前任务: {task}\n"
                                       f"最后心跳: {hb} ({age/60:.0f}分钟前)")
                                print(f"[自监控] {msg}")
                                try:
                                    from notifier import notify_alert, LEVEL_CRITICAL
                                    notify_alert(LEVEL_CRITICAL, "夜班卡死告警", msg)
                                except Exception:
                                    pass
                        except ValueError:
                            pass
            except Exception:
                pass

    t = threading.Thread(target=_watchdog_loop, daemon=True, name="self_watchdog")
    t.start()
    print(f"  自监控线程已启动 (每{interval}s检查)")
    return t


def run_daemon():
    """守护进程模式: 常驻运行, 每30秒检查

    自动启动:
      1. caffeinate 防休眠
      2. 自监控线程 (夜班卡死检测)
    """
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print("  每日定时超短线选股推荐系统")
    print(f"  启动时间: {start_time}")
    print("=" * 60)

    # 自动防休眠
    caff_proc = _start_caffeinate()

    # 自监控线程
    _start_self_watchdog()

    # 启动/重启通知 — 让用户知道系统在线
    _notify_scheduler_event("启动", f"系统已启动: {start_time}\n所有定时任务已注册, 正常运行中。")

    setup_schedule()

    print(f"\n调度器已启动, 每 30 秒检查一次...")
    print("caffeinate 已自动启动, 无需手动加\n")

    # 启动时立即更新心跳 (避免 watchdog 误报)
    try:
        from watchdog import update_heartbeat
        update_heartbeat()
    except Exception:
        pass

    # 清理遗留的夜班 "running" 状态 (防止重启后自监控误报卡死)
    try:
        from json_store import safe_load, safe_save
        _night_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "night_shift_log.json")
        _nl = safe_load(_night_log_path, default={})
        if _nl.get("status") == "running":
            _nl["status"] = "interrupted"
            _nl["_heartbeat"] = ""
            _nl["_current_task"] = ""
            safe_save(_night_log_path, _nl)
            print("  清理遗留夜班状态: running → interrupted")
    except Exception:
        pass

    # 心跳独立线程: 不受策略执行阻塞影响
    import threading

    def _heartbeat_loop():
        while True:
            try:
                from watchdog import update_heartbeat
                update_heartbeat()
            except Exception:
                pass
            time.sleep(30)

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="heartbeat")
    hb_thread.start()

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n调度器已停止")
        if caff_proc:
            caff_proc.terminate()


def run_all_test():
    """测试模式: 立即运行全部策略 (从 strategies.json 动态加载)"""
    import strategy_loader
    sched_mod = sys.modules[__name__]
    strategy_loader.run_all_strategies(sched_mod)


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    # 策略 CLI: 优先从 strategies.json 动态查找
    import strategy_loader

    if mode == "test":
        run_all_test()
    elif strategy_loader.get_cli_strategy(mode):
        # 动态加载策略 (news_event/auction/breakout/afternoon/dip_buy/
        # consolidation/trend/sector/futures/crypto/us_stock 等)
        mod_name, func_name, strat_name = strategy_loader.get_cli_strategy(mode)
        func = strategy_loader._import_func(mod_name, func_name)
        run_with_retry(func, strat_name)
    elif mode == "cross_market":
        from cross_market_strategy import run_cross_market_analysis
        run_cross_market_analysis()
    elif mode == "morning_prep":
        from morning_prep import run_morning_prep
        run_morning_prep()
    elif mode == "futures_status":
        from trade_executor import get_portfolio_status, get_trade_summary
        portfolio = get_portfolio_status()
        summary = get_trade_summary()
        if portfolio["count"] > 0:
            print(f"期货持仓: {portfolio['count']}个  保证金¥{portfolio['total_margin']:.0f}  浮动盈亏¥{portfolio['total_pnl']:.2f}")
            for p in portfolio["positions"]:
                print(f"  {p['code']} {p['name']} {p['direction']}  "
                      f"¥{p['entry_price']:.2f}→¥{p['current_price']:.2f}  "
                      f"止损¥{p['stop_price']:.2f}  {p['pnl_pct']:+.2f}%")
        else:
            print("无期货持仓")
        if summary["total_trades"] > 0:
            print(f"\n历史: {summary['total_trades']}笔  胜率{summary['win_rate']:.1f}%  总盈亏¥{summary['total_pnl']:.2f}")
    elif mode == "futures_check":
        job_futures_monitor()
    elif mode == "monitor":
        job_monitor()
    elif mode == "scorecard":
        from scorecard import score_yesterday
        score_yesterday()
    elif mode == "weekly":
        from scorecard import generate_weekly_report, notify_scorecard
        notify_scorecard(generate_weekly_report())
    elif mode == "smoke":
        from self_healer import run_smoke_test
        result = run_smoke_test()
        print("PASSED" if result["passed"] else "FAILED")
    elif mode == "optimize":
        from auto_optimizer import run_daily_optimization
        run_daily_optimization()
    elif mode == "heal":
        from self_healer import auto_heal
        auto_heal()
    elif mode == "learning":
        from learning_engine import run_learning_cycle
        run_learning_cycle()
    elif mode == "agent":
        from agent_brain import run_agent_cycle
        print(run_agent_cycle())
    elif mode == "verify":
        job_verify_optimizations()
    elif mode == "lifecycle":
        job_factor_lifecycle()
    elif mode == "night":
        _run_night_shift()
    elif mode == "signals":
        job_signal_tracker()
    elif mode == "status":
        _show_system_status()
    elif mode == "sources":
        from api_guard import get_source_health, get_api_stats
        health = get_source_health()
        stats = get_api_stats()
        print("=" * 60)
        print("  API 源健康状态")
        print("=" * 60)
        if health:
            print(f"{'源':<20} {'成功率':>8} {'延迟ms':>8} {'调用数':>6} {'断路器':>10}")
            print("-" * 60)
            for src, d in sorted(health.items()):
                rate_str = f"{d['success_rate']*100:.0f}%"
                print(f"{src:<20} {rate_str:>8} {d['avg_ms']:>8.0f} {d['calls']:>6} {d['circuit']:>10}")
        else:
            print("  (暂无数据, 需要运行策略后才有)")
        print(f"\n全局统计: 总调用={stats.get('total_calls',0)} "
              f"缓存命中={stats.get('cache_hits',0)} "
              f"重试={stats.get('retries',0)} "
              f"限流={stats.get('rate_limited',0)} "
              f"错误={stats.get('errors',0)}")
    elif mode.startswith("analyze"):
        # python3 scheduler.py analyze 002221 [--push] [--journal]
        codes_arg = sys.argv[2] if len(sys.argv) > 2 else ""
        if not codes_arg or codes_arg.startswith("--"):
            print("用法: python3 scheduler.py analyze 002221 [--push] [--journal]")
            print("      python3 scheduler.py analyze 002221,600519")
            sys.exit(1)
        do_push = "--push" in sys.argv
        do_journal = "--journal" in sys.argv
        from stock_analyzer import analyze_stock, analyze_batch
        codes = [c.strip() for c in codes_arg.split(",") if c.strip()]
        if len(codes) == 1:
            result = analyze_stock(codes[0], push=do_push, journal=do_journal)
            if "error" in result:
                print(f"错误: {result['error']}")
            else:
                print(result["report_text"])
        else:
            results = analyze_batch(codes, push=do_push, journal=do_journal)
            for r in results:
                print(f"\n{'='*50}")
                print(r["report_text"])
            print(f"\n共分析 {len(results)} 只")
    elif mode == "daemon":
        run_daemon()
    else:
        print(f"未知模式: {mode}")
        print("用法:")
        print("  python3 scheduler.py             # 启动守护进程")
        print("  python3 scheduler.py test        # 立即运行全部策略")
        print("  python3 scheduler.py news_event  # 事件驱动")
        print("  python3 scheduler.py auction     # 集合竞价")
        print("  python3 scheduler.py breakout    # 放量突破")
        print("  python3 scheduler.py afternoon   # 尾盘短线")
        print("  python3 scheduler.py dip_buy     # 低吸回调")
        print("  python3 scheduler.py consolidation # 缩量整理")
        print("  python3 scheduler.py trend       # 趋势跟踪")
        print("  python3 scheduler.py sector      # 板块轮动")
        print("  python3 scheduler.py monitor     # 立即运行持仓监控")
        print("  python3 scheduler.py scorecard   # 对昨日推荐打分")
        print("  python3 scheduler.py weekly      # 生成并推送周报")
        print("  python3 scheduler.py smoke       # 冒烟测试")
        print("  python3 scheduler.py optimize    # 策略优化")
        print("  python3 scheduler.py heal        # 自动修复")
        print("  python3 scheduler.py learning    # 自学习引擎")
        print("  python3 scheduler.py agent       # Agent OODA 循环")
        print("  python3 scheduler.py crypto      # 币圈趋势")
        print("  python3 scheduler.py us_stock    # 美股收盘分析")
        print("  python3 scheduler.py cross_market # 跨市场推演")
        print("  python3 scheduler.py morning_prep # 开盘作战计划")
        print("  python3 scheduler.py night       # 夜班深度分析")
        print("  python3 scheduler.py signals     # 信号追踪 (入库+验证)")
        print("  python3 scheduler.py status      # 系统状态面板")
        print("  python3 scheduler.py analyze 002221  # 个股诊断")
        print("  python3 scheduler.py sources     # API源健康状态")
        sys.exit(1)
