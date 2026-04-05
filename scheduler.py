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
  python3 scheduler.py execution_policy_export [daily|weekly]  # 导出执行策略快照
  python3 scheduler.py world_state_export [daily|weekly]  # 导出顶层世界状态快照
  python3 scheduler.py world_state_feeds  # 刷新顶层世界模型自动源
  python3 scheduler.py world_hard_sources  # 刷新更硬的世界模型源
  python3 scheduler.py world_refresh_tick [--force]  # 动态世界抓取节奏
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
    SCHEDULE_MORNING_PREP, SCHEDULE_HK_STOCK,
    SCHEDULE_CROSS_ASSET, SCHEDULE_REGIME_ROUTER,
    SCHEDULE_ENSEMBLE_MIDDAY, SCHEDULE_ENSEMBLE_AFTERNOON,
    SCHEDULE_ATTRIBUTION,
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
#  从 scheduler_jobs 导入所有定时任务
# ================================================================
from scheduler_jobs import (
    # 辅助
    _check_market_regime, _record_learning, _init_multi_agent,
    _is_futures_trading_day, _execute_futures_trades,
    _show_system_status,
    # 所有 job_* 任务
    job_futures_monitor, job_cross_market, job_morning_prep,
    job_reset_api_stats,
    job_batch_morning, job_batch_midday, job_batch_afternoon,
    job_learning_progress,
    job_learning, job_learning_health, job_midday_learning,
    job_signal_tracker,
    job_monitor, job_scorecard, job_backfill_returns,
    job_weekly_report, job_execution_policy_export,
    job_world_state_export,
    job_world_state_feeds, job_world_hard_sources, job_world_refresh_tick,
    job_agent_morning, job_agent_evening, job_night_shift,
    job_smoke_test, job_daily_optimize, job_var_risk,
    job_weekend_optimize, job_full_retrain,
    job_verify_optimizations, job_factor_lifecycle, job_factor_forge,
    job_stock_diagnosis,
    job_paper_monitor, job_paper_settle, job_broker_monitor,
    job_ml_train, job_proactive_experiment,
    job_cross_asset_factor, job_regime_router,
    job_ensemble_midday, job_ensemble_afternoon,
    job_attribution, job_global_news,
)

# ================================================================
#  全天候学习节流器
# ================================================================

_last_online_learning_hour = None


def _trigger_online_learning():
    """策略跑完后触发在线学习 (节流: 同一小时最多1次)"""
    global _last_online_learning_hour

    current_hour = datetime.now().hour
    if _last_online_learning_hour == current_hour:
        return

    try:
        from signal_tracker import verify_outcomes
        result = verify_outcomes()
        if result.get("verified", 0) > 0:
            logger.info("[全天候学习] 验证 %d 条信号, 触发在线学习", result["verified"])
            _last_online_learning_hour = current_hour
    except Exception as e:
        logger.debug("[全天候学习] 异常: %s", e)


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
    "morning": [],
    "midday": [],
    "afternoon": [],
}

# 持仓监控时间点
SCHEDULE_MONITOR = ["10:30", "11:15", "13:30", "14:50"]


def _notify_zero_result(time_slot: str, strategies: str):
    """零产出 → 简短心跳"""
    try:
        from notifier import notify_alert, LEVEL_INFO
        notify_alert(LEVEL_INFO, f"{time_slot} 心跳", f"策略正常运行, 本轮无推荐")
    except Exception as e:
        logger.warning("零产出通知失败: %s", e)


def _notify_scheduler_event(event: str, detail: str = ""):
    """推送调度器关键事件"""
    try:
        from notifier import notify_wechat_raw
        now_str = datetime.now().strftime("%H:%M")
        notify_wechat_raw(f"[{now_str}] 调度器{event}", detail or f"调度器已{event}")
    except Exception as e:
        logger.warning("调度器事件通知失败: %s", e)


# ================================================================
#  交易日判断
# ================================================================

_trading_date_cache = {}


def _fetch_trading_dates():
    """通过 akshare API 获取交易日历"""
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
        return None


def is_trading_day():
    """判断今天是否为交易日"""
    today = date.today()
    today_str = today.isoformat()

    api_result = _fetch_trading_dates()
    if api_result is not None:
        tag = "交易日" if api_result else "非交易日"
        print(f"  [交易日判断-API] {today_str} → {tag}")
        return api_result

    print("  [交易日判断] API不可用, 使用本地日历")
    weekday = today.weekday()

    if today_str in CN_WORKDAYS_2026:
        print(f"  [交易日判断-本地] {today_str} 调休补班 → 交易日")
        return True

    if today_str in CN_HOLIDAYS_2026:
        print(f"  [交易日判断-本地] {today_str} 法定假日 → 非交易日")
        return False

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
    """运行策略, 最多重试 MAX_RETRIES 次; 成功后自动记录持仓"""
    t0 = time.time()

    # Safe Mode 检查
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

    # 环境路由
    try:
        from regime_router import should_skip_strategy
        if should_skip_strategy(strategy_name):
            print(f"[路由跳过] {strategy_name} (当前regime不适配)")
            try:
                from watchdog import update_strategy_status
                update_strategy_status(strategy_name, "skipped_regime")
            except Exception:
                pass
            return
    except ImportError:
        pass
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

            try:
                import pandas as pd
                if isinstance(items, pd.DataFrame):
                    items = items.to_dict(orient="records")
            except Exception:
                pass

            try:
                from learning_engine import record_trade_context
                record_trade_context(strategy_name, items or [])
            except Exception:
                pass

            try:
                from intraday_strategy import flush_scored_to_scorecard
                flush_scored_to_scorecard(strategy_name)
            except Exception as e:
                print(f"  [数据管道异常] {strategy_name}: {e}")

            try:
                from risk_manager import filter_recommendations
                items = filter_recommendations(strategy_name, items)
            except Exception as e:
                print(f"[风控过滤异常] {e}")

            try:
                from risk_manager import get_position_sizing
                items = get_position_sizing(100000, items, strategy_name=strategy_name)
            except Exception as e:
                print(f"[仓位建议异常] {e}")

            try:
                from adversarial_engine import apply_game_theory_filter
                items = apply_game_theory_filter(items)
            except Exception as e:
                print(f"[博弈引擎异常] {e}")

            if skip_wechat:
                notify_terminal(strategy_name, items)
                notify_macos(strategy_name, items)
                export_ths_watchlist(strategy_name, items)
            else:
                notify_all(strategy_name, items)

            try:
                from position_manager import record_entry
                record_entry(strategy_name, items)
            except Exception as e:
                print(f"[持仓记录异常] {e}")

            try:
                from paper_trader import on_strategy_picks
                opened = on_strategy_picks(items, strategy_name)
                if opened:
                    print(f"[纸盘] {strategy_name} 自动开仓 {len(opened)} 笔")
            except Exception as e:
                print(f"[纸盘开仓异常] {e}")

            try:
                from watchdog import update_strategy_status
                update_strategy_status(strategy_name, "success", duration_sec=elapsed)
            except Exception:
                pass

            try:
                _trigger_online_learning()
            except Exception:
                pass

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
                try:
                    from watchdog import update_strategy_status
                    update_strategy_status(strategy_name, "failed", error_msg=str(e))
                except Exception:
                    pass
                try:
                    _push_dashboard_event("strategy_failed", {
                        "strategy": strategy_name,
                        "error": str(e)[:200],
                    })
                except Exception:
                    pass
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
#  调度器设置
# ================================================================

def setup_schedule():
    """设置定时任务"""
    _init_multi_agent()

    import strategy_loader
    sched_mod = sys.modules[__name__]
    n_strategies = strategy_loader.register_strategies(sched_mod, schedule)
    print(f"  策略加载器: {n_strategies} 个策略已从 strategies.json 动态注册")

    # 3 个批量推送
    schedule.every().day.at("09:26").do(job_batch_morning)
    schedule.every().day.at("10:30").do(job_batch_midday)
    schedule.every().day.at("10:30").do(job_learning_progress)
    schedule.every().day.at("11:30").do(job_learning_progress)
    schedule.every().day.at("14:00").do(job_learning_progress)
    schedule.every().day.at("14:50").do(job_batch_afternoon)

    for t in SCHEDULE_MONITOR:
        schedule.every().day.at(t).do(job_monitor)

    schedule.every().day.at("15:35").do(job_scorecard)
    schedule.every().day.at("15:40").do(job_execution_policy_export, "daily")
    schedule.every().day.at("15:41").do(job_world_state_export, "daily")
    schedule.every().day.at("16:30").do(job_backfill_returns)

    schedule.every().friday.at("15:30").do(job_weekly_report)
    schedule.every().friday.at("15:40").do(job_execution_policy_export, "weekly")
    schedule.every().friday.at("15:41").do(job_world_state_export, "weekly")

    schedule.every().day.at("09:10").do(job_smoke_test)
    schedule.every().day.at("12:30").do(job_midday_learning)
    schedule.every().day.at("16:00").do(job_daily_optimize)
    schedule.every().day.at("16:05").do(job_signal_tracker)
    schedule.every().day.at("16:10").do(job_var_risk)
    schedule.every().day.at("16:30").do(job_learning)
    schedule.every().day.at("16:35").do(job_learning_health)
    schedule.every().day.at("17:10").do(job_ml_train)
    schedule.every().day.at("17:30").do(job_factor_forge)

    schedule.every().day.at("11:00").do(job_paper_monitor)
    schedule.every().day.at("14:00").do(job_paper_monitor)
    schedule.every().day.at("15:30").do(job_paper_settle)

    schedule.every().day.at("10:30").do(job_broker_monitor)
    schedule.every().day.at("13:30").do(job_broker_monitor)
    schedule.every().day.at("14:45").do(job_broker_monitor)
    schedule.every().saturday.at("10:00").do(job_weekend_optimize)
    schedule.every().sunday.at("20:00").do(job_full_retrain)

    schedule.every().day.at("09:15").do(job_agent_morning)
    schedule.every().day.at("16:15").do(job_agent_evening)
    schedule.every().day.at("16:45").do(job_proactive_experiment)
    schedule.every().day.at("16:50").do(job_verify_optimizations)
    schedule.every().day.at("17:00").do(job_factor_lifecycle)
    schedule.every().day.at("18:00").do(job_night_shift)

    schedule.every().day.at(SCHEDULE_CROSS_ASSET).do(job_cross_asset_factor)
    schedule.every().day.at(SCHEDULE_REGIME_ROUTER).do(job_regime_router)
    schedule.every().day.at(SCHEDULE_ENSEMBLE_MIDDAY).do(job_ensemble_midday)
    schedule.every().day.at(SCHEDULE_ENSEMBLE_AFTERNOON).do(job_ensemble_afternoon)
    schedule.every().day.at(SCHEDULE_ATTRIBUTION).do(job_attribution)

    schedule.every().day.at(SCHEDULE_CROSS_MARKET).do(job_cross_market)
    schedule.every().day.at(SCHEDULE_MORNING_PREP).do(job_morning_prep)

    for ft in ["09:30", "10:30", "11:15", "13:30", "14:30", "21:30", "22:30"]:
        schedule.every().day.at(ft).do(job_futures_monitor)

    schedule.every().day.at("00:05").do(job_reset_api_stats)

    schedule.every(5).minutes.do(job_world_refresh_tick)

    print(f"已注册定时任务:")
    for cfg in strategy_loader.load_strategies():
        if cfg.get("enabled", True):
            print(f"  {cfg['schedule']}  → {cfg['name']} (动态)")
    print(f"  09:10  → 冒烟测试 (开盘前)")
    print(f"  09:15  → Agent 早报 [微信1/5]")
    print(f"  09:20  → 昨日推荐评分 + 黑名单更新")
    print(f"  09:35  → 批量推送: 早盘汇总 [微信2/5]")
    print(f"  10:30  → 批量推送: 盘中汇总 [微信3/5]")
    print(f"  每5分钟 → 世界抓取节奏 tick (基础轮询 + 事件升级 + 隔夜补扫)")
    print(f"  14:50  → 批量推送: 午后汇总 [微信4/5]")
    print(f"  {', '.join(SCHEDULE_MONITOR)}  → 持仓监控(止损止盈, 仅终端)")
    print(f"  15:40  → execution policy 日级导出")
    print(f"  {SCHEDULE_CROSS_ASSET}  → 跨市场因子 (US/BTC/A50/VIX)")
    print(f"  {SCHEDULE_REGIME_ROUTER}  → 环境路由 (动态策略开关)")
    print(f"  {SCHEDULE_ENSEMBLE_MIDDAY}/{SCHEDULE_ENSEMBLE_AFTERNOON}  → 多策略共识扫描")
    print(f"  12:30  → 午盘加速学习 (信号验证/健康检查/WF)")
    print(f"  16:00~17:30  → 优化/信号/归因/VaR/学习/ML/因子发现")
    print(f"  22:30  → 夜班深度分析 (LLM复盘/预判/认知沉淀)")
    print(f"  周五 15:40  → execution policy 周级导出")
    print(f"  {SCHEDULE_CROSS_MARKET}  → 跨市场信号推演 (夜班)")
    print(f"  {SCHEDULE_MORNING_PREP}  → 开盘前作战计划")
    print(f"  09:30~22:30  → 期货持仓监控(止损止盈, 7次/日)")
    print(f"  00:05  → API统计重置")
    print(f"  07:00/20:00+周末  → 全球新闻雷达 (6源+LLM)")
    print(f"  每 5 分钟 tick  → 顶层世界模型动态抓取/自适应提频")


# ================================================================
#  守护进程基础设施
# ================================================================

def _start_caffeinate():
    """启动 caffeinate 防止 macOS 休眠"""
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
    """启动自监控线程"""
    import threading
    from datetime import timedelta

    def _watchdog_loop():
        _last_alert_task = None
        _last_alert_time = 0.0
        _ALERT_COOLDOWN = 3600

        while True:
            time.sleep(interval)
            try:
                night_log_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "night_shift_log.json")
                from json_store import safe_load as _sl
                night_log = _sl(night_log_path, default={})
                if night_log.get("status") == "running":
                    date_str = night_log.get("date", "")
                    hb = night_log.get("_heartbeat", "")
                    if hb and date_str:
                        from datetime import datetime as _dt
                        try:
                            today = _dt.now().date()
                            valid_dates = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
                            if date_str not in valid_dates:
                                continue
                            last = _dt.strptime(hb, "%Y-%m-%d %H:%M:%S")
                            age = (_dt.now() - last).total_seconds()
                            task = night_log.get("_current_task", "?")
                            if age > 900:
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
                                except Exception as _exc:
                                    logger.debug("Suppressed exception: %s", _exc)
                        except ValueError:
                            pass
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    t = threading.Thread(target=_watchdog_loop, daemon=True, name="self_watchdog")
    t.start()
    print(f"  自监控线程已启动 (每{interval}s检查)")
    return t


def run_daemon():
    """守护进程模式"""
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print("  每日定时超短线选股推荐系统")
    print(f"  启动时间: {start_time}")
    print("=" * 60)

    caff_proc = _start_caffeinate()

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    _start_self_watchdog()
    _notify_scheduler_event("启动", f"系统已启动: {start_time}\n所有定时任务已注册, 正常运行中。")

    setup_schedule()

    print(f"\n调度器已启动, 每 30 秒检查一次...")
    print("caffeinate 已自动启动, 无需手动加\n")

    try:
        from watchdog import update_heartbeat
        update_heartbeat()
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    import threading

    def _heartbeat_loop():
        while True:
            try:
                from watchdog import update_heartbeat
                update_heartbeat()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
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
    """测试模式: 立即运行全部策略"""
    import strategy_loader
    sched_mod = sys.modules[__name__]
    strategy_loader.run_all_strategies(sched_mod)


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    import strategy_loader

    if mode == "test":
        run_all_test()
    elif strategy_loader.get_cli_strategy(mode):
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
    elif mode == "execution_policy_export":
        period = sys.argv[2] if len(sys.argv) > 2 else "daily"
        job_execution_policy_export(period)
    elif mode == "world_state_export":
        period = sys.argv[2] if len(sys.argv) > 2 else "daily"
        job_world_state_export(period)
    elif mode == "world_state_feeds":
        job_world_state_feeds()
    elif mode == "world_hard_sources":
        job_world_hard_sources()
    elif mode == "world_refresh_tick":
        force = "--force" in sys.argv[2:]
        job_world_refresh_tick(force=force)
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
    elif mode == "learning_health":
        from learning_engine import check_learning_health
        health = check_learning_health()
        for c in health.get("checks", []):
            icon = {"ok": "✅", "warning": "⚠️", "critical": "❌", "error": "💥"}.get(c["status"], "?")
            print(f"  {icon} {c['check']}: {c['detail']}")
        if health.get("healed"):
            print("\n自愈:")
            for h in health["healed"]:
                print(f"  🔧 {h}")
        print(f"\n总体状态: {health['status'].upper()}")
    elif mode == "agent":
        from agent_brain import run_agent_cycle
        print(run_agent_cycle())
    elif mode == "verify":
        job_verify_optimizations()
    elif mode == "lifecycle":
        job_factor_lifecycle()
    elif mode == "night":
        from scheduler_jobs import _run_night_shift
        _run_night_shift()
    elif mode == "signals":
        job_signal_tracker()
    elif mode == "status":
        _show_system_status()
    elif mode == "ensemble":
        from strategy_ensemble import get_consensus_recommendations
        consensus = get_consensus_recommendations()
        if consensus:
            for c in consensus:
                print(f"  {c['code']}({c['name']}) 共识={c['consensus_score']:.3f} "
                      f"策略={c['n_strategies']} 族={c['families']}")
        else:
            print("无共识信号")
    elif mode == "routing":
        from regime_router import get_routing_status
        status = get_routing_status()
        if status.get("status") == "not_calculated":
            print("路由未计算, 运行: python3 regime_router.py calc")
        else:
            print(f"Regime: {status.get('regime')}")
            for k, v in status.get("strategies", {}).items():
                tag = "SKIP" if v["skip"] else "OK"
                print(f"  {v['name']}: ratio={v['ratio']:.3f} scale={v['position_scale']:.2f} [{tag}]")
    elif mode == "cascade":
        from cascade_engine import get_cascade_engine
        engine = get_cascade_engine()
        sub = sys.argv[2] if len(sys.argv) > 2 else "help"
        if sub == "help":
            print("用法:")
            print("  scheduler.py cascade preview strategy_pause strategy=放量突破")
            print("  scheduler.py cascade execute strategy_pause strategy=放量突破 reason=连亏5次")
            print("  scheduler.py cascade execute circuit_breaker reason=单日亏损>5%")
            print("  scheduler.py cascade execute strategy_resume strategy=放量突破")
            print("  scheduler.py cascade execute factor_retire factor=mom_5d")
        elif sub in ("preview", "execute"):
            trigger = sys.argv[3] if len(sys.argv) > 3 else None
            if not trigger:
                print("缺少 trigger 参数")
                sys.exit(1)
            params = {}
            for arg in sys.argv[4:]:
                if '=' in arg:
                    k, v = arg.split('=', 1)
                    params[k] = v
            if sub == "preview":
                result = engine.preview(trigger, **params)
                print(f"触发器: {result['trigger']}  参数: {result['params']}")
                print(f"影响目标: {result['affected_targets']}")
                for r in result['rules']:
                    print(f"  {r['name']}: {r['description']}")
            else:
                ctx = engine.execute(trigger, **params)
                for t in set(ctx.affected):
                    print(f"  ✓ {t}")
                if ctx.errors:
                    for e in ctx.errors:
                        print(f"  ✗ {e}")
                else:
                    print("✅ 级联执行成功")
        else:
            print(f"未知子命令: {sub}  (用 cascade help 查看用法)")
    elif mode == "attribution":
        from attribution import run_full_attribution, format_attribution_report
        print(format_attribution_report(run_full_attribution()))
    elif mode == "timing":
        from execution_timing import run_timing_analysis, format_timing_report
        result = run_timing_analysis()
        if result:
            print(format_timing_report(result))
        else:
            print("数据不足")
    elif mode == "cross_asset":
        from cross_asset_factor import calc_all_indicators
        r = calc_all_indicators()
        risk = r.get("ca_risk_appetite", 0.5)
        label = "RiskOn" if risk >= 0.65 else ("RiskOff" if risk <= 0.35 else "中性")
        print(f"risk={risk:.3f} [{label}] US={r.get('ca_us_momentum',0):.3f} "
              f"BTC={r.get('ca_btc_trend',0):.3f} A50={r.get('ca_a50_premium',0):.3f} "
              f"VIX={r.get('ca_vix_level',0):.3f}")
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
        print("  python3 scheduler.py execution_policy_export [daily|weekly]  # 导出执行策略快照")
        print("  python3 scheduler.py world_state_export [daily|weekly]  # 导出顶层世界状态快照")
        print("  python3 scheduler.py world_state_feeds  # 刷新顶层世界模型自动源")
        print("  python3 scheduler.py world_hard_sources  # 刷新更硬的世界模型源")
        print("  python3 scheduler.py world_refresh_tick [--force]  # 动态世界抓取节奏")
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
