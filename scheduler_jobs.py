"""
调度器任务模块
=============
从 scheduler.py 拆分出的所有 job_* 定时任务函数。
scheduler.py 保留核心基础设施 (调度循环/重试/批量推送/CLI)。
"""

import os
import sys
import time
from datetime import datetime

from config import (
    SCHEDULE_CROSS_MARKET, SCHEDULE_MORNING_PREP,
    SCHEDULE_CROSS_ASSET,
    SMART_TRADE_ENABLED,
)
from notifier import notify_batch_wechat
from log_config import get_logger

logger = get_logger("scheduler")

# 由 scheduler.py 在导入后注入, 避免循环依赖
_scheduler_ref = None  # type: ignore


def _get_scheduler():
    """获取 scheduler 模块引用 (run_with_retry / _batch_buffer / is_trading_day 等)"""
    global _scheduler_ref
    if _scheduler_ref is None:
        import scheduler
        _scheduler_ref = scheduler
    return _scheduler_ref


# ================================================================
#  辅助函数 (从 scheduler.py 搬移)
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


def _record_learning(items, strategy_name, regime_result):
    """策略运行后记录上下文 (供学习引擎分析)"""
    try:
        from learning_engine import record_trade_context
        record_trade_context(strategy_name, items or [], regime_result)
    except Exception as e:
        print(f"[学习记录异常] {e}")


def _is_futures_trading_day():
    """期货交易日: 仅跳过周六日 (不受股票节假日限制)"""
    return datetime.now().weekday() < 5


def _execute_futures_trades(items):
    """调用交易执行器开仓 (信号→交易)"""
    try:
        from trade_executor import execute_signals
        from config import TRADE_EXECUTOR_PARAMS
        mode = TRADE_EXECUTOR_PARAMS.get("mode", "paper")
        executed = execute_signals(items, mode=mode)
        if executed:
            mode_label = {"paper": "模拟", "simnow": "SimNow", "live": "实盘"}.get(mode, mode)
            logger.info("[交易执行] %s模式 开仓 %d 笔", mode_label, len(executed))
    except Exception as e:
        logger.warning("[交易执行异常] %s", e)


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


# ================================================================
#  期货相关
# ================================================================

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
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
            print("\n".join(lines))
        else:
            portfolio = get_portfolio_status()
            if portfolio["count"] > 0:
                print(f"  持仓 {portfolio['count']}个  浮动盈亏 ¥{portfolio['total_pnl']:.2f}")
            else:
                print("  无期货持仓")
    except Exception as e:
        print(f"[期货监控异常] {e}")


# ================================================================
#  跨市场 / 作战计划 / API 重置
# ================================================================

def job_cross_market():
    """06:00 跨市场信号推演 (美股收盘+夜盘收盘后)"""
    from cross_market_strategy import get_cross_market_signal
    from notifier import notify_wechat_raw
    result = get_cross_market_signal()
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
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
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
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)


def job_morning_prep():
    """07:30 开盘前作战计划"""
    from morning_prep import run_morning_prep
    from notifier import notify_wechat_raw
    result = run_morning_prep()
    if result and result.get("plan_text"):
        try:
            notify_wechat_raw(f"[{SCHEDULE_MORNING_PREP}] 开盘作战计划", result["plan_text"])
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)


def job_reset_api_stats():
    """00:05 每日重置 API 统计"""
    try:
        from api_guard import reset_daily_stats, get_api_stats
        stats = get_api_stats()
        logger.info("API 日统计: calls=%d cache_hits=%d retries=%d errors=%d rate_limited=%d",
                     stats["total_calls"], stats["cache_hits"], stats["retries"],
                     stats["errors"], stats["rate_limited"])
        reset_daily_stats()
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)


# ================================================================
#  批量推送任务
# ================================================================

def job_batch_morning():
    """09:35 合并发送上午早盘结果 (集合竞价)"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    buf = s._batch_buffer["morning"]
    if buf:
        notify_batch_wechat("早盘选股汇总", buf)
    else:
        s._notify_zero_result("09:35 早盘选股", "事件驱动+集合竞价")
    s._batch_buffer["morning"] = []


def job_batch_midday():
    """10:30 合并发送盘中结果 (放量突破+低吸+缩量+趋势)"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    buf = s._batch_buffer["midday"]
    if buf:
        notify_batch_wechat("盘中选股汇总", buf)
    else:
        s._notify_zero_result("10:30 盘中选股", "放量突破+低吸回调+缩量整理+趋势跟踪")
    s._batch_buffer["midday"] = []


def job_learning_progress():
    """10:30 推送学习效果报告"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from learning_engine import check_learning_health, analyze_factor_importance
        from json_store import safe_load
        from db_store import load_scorecard

        health = check_learning_health()
        h_ok = sum(1 for c in health.get("checks", []) if c["status"] == "ok")
        h_total = len(health.get("checks", []))

        sc = load_scorecard(days=1)
        today_count = len(sc)

        pos = neg = dead = total = 0
        for strat in ["隔夜选股", "板块轮动选股", "趋势跟踪选股", "尾盘短线选股",
                       "集合竞价选股", "低吸回调选股", "缩量整理选股"]:
            for f in analyze_factor_importance(strat):
                if f.get("correlation") is None:
                    continue
                total += 1
                c = f["correlation"]
                if c == 0.0:
                    dead += 1
                elif c > 0.02:
                    pos += 1
                elif c < -0.02:
                    neg += 1

        tunable = safe_load("tunable_params.json", default={})
        strats_shifted = 0
        for key in ["auction", "afternoon", "dip_buy", "consolidation",
                     "trend_follow", "sector_rotation"]:
            tw = tunable.get(key, {}).get("weights", {})
            if any(abs(v - 1.0 / max(len(tw), 1)) > 0.01 for v in tw.values()):
                strats_shifted += 1

        state = safe_load("learning_state.json", default={})
        version = state.get("version", 0)

        import collections as _coll
        by_strat = _coll.Counter()
        for r in sc:
            by_strat[r.get("strategy", "?")] += 1
        strat_lines = [f"  {ss}: {cc}" for ss, cc in by_strat.most_common()]

        hour = datetime.now().hour
        if hour <= 10:
            expected = 50
        elif hour <= 12:
            expected = 200
        elif hour <= 14:
            expected = 300
        else:
            expected = 400
        on_track = "✅ 进度正常" if today_count >= expected * 0.7 else "⚠️ 数据不足!"

        ran_strats = set(by_strat.keys())
        all_strats = ["集合竞价选股", "隔夜选股", "趋势跟踪选股", "板块轮动选股",
                      "低吸回调选股", "缩量整理选股", "尾盘短线选股"]
        not_ran = [ss for ss in all_strats if ss not in ran_strats]

        lines = [
            f"📊 学习数据监控 ({datetime.now().strftime('%H:%M')})",
            f"",
            f"今日数据: {today_count} 条 (目标{expected}) {on_track}",
        ] + strat_lines + [
            f"",
            f"未跑: {', '.join(not_ran) if not_ran else '全部完成'}",
            f"健康: {h_ok}/{h_total} 通过",
            f"因子: {total}个 (正{pos} 负{neg} 废{dead})",
            f"权重: {strats_shifted}/6 策略已优化",
            f"版本: v{version}",
        ]

        from notifier import notify_wechat_raw
        notify_wechat_raw("学习数据监控", "\n".join(lines))
        print(f"[学习监控] 已推送: {today_count}条 {on_track}")
    except Exception as e:
        print(f"[学习监控] 推送失败: {e}")


def job_batch_afternoon():
    """14:50 合并发送午后结果 (尾盘+板块轮动)"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    buf = s._batch_buffer["afternoon"]
    if buf:
        notify_batch_wechat("午后选股汇总", buf)
    else:
        s._notify_zero_result("14:50 午后选股", "尾盘短线+板块轮动")
    s._batch_buffer["afternoon"] = []


# ================================================================
#  学习引擎
# ================================================================

def job_learning():
    """16:30 运行学习引擎"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from learning_engine import run_learning_cycle
        run_learning_cycle()
    except Exception as e:
        print(f"[学习引擎异常] {e}")


def job_learning_health():
    """16:35 学习健康独立检查"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from learning_engine import check_learning_health
        health = check_learning_health()
        status = health.get("status", "unknown")
        n_checks = len(health.get("checks", []))
        n_healed = len(health.get("healed", []))
        print(f"  [学习健康] 状态={status}, {n_checks}项检查, {n_healed}项自愈")
    except Exception as e:
        print(f"  [学习健康异常] {e}")


def job_midday_learning():
    """12:30 午盘学习"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    print(f"[午盘学习] {datetime.now().strftime('%H:%M')} 开始")

    try:
        from signal_tracker import verify_outcomes
        verify_outcomes()
        print("[午盘学习] 信号验证+在线学习完成")
    except Exception as e:
        print(f"[午盘学习] 信号验证异常: {e}")

    try:
        from auto_optimizer import evaluate_strategy_health
        sick = []
        for strat in ["放量突破选股", "集合竞价选股", "尾盘短线选股",
                       "低吸回调选股", "趋势跟踪选股"]:
            health = evaluate_strategy_health(strat, days=14)
            if health.get("score", 100) < 30:
                sick.append(f"{strat}({health['score']}分)")
        if sick:
            print(f"[午盘学习] 告警: {', '.join(sick)} 需要关注")
            try:
                from notifier import notify_wechat_raw
                notify_wechat_raw("[午盘] 策略健康告警",
                                  f"以下策略14天表现差:\n" + "\n".join(sick))
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        else:
            print("[午盘学习] 策略健康OK")
    except Exception as e:
        print(f"[午盘学习] 健康检查异常: {e}")

    try:
        from walk_forward import run_walk_forward
        for strat in ["breakout", "auction"]:
            result = run_walk_forward(strat, n_windows=2)
            if result.get("overfit_warning"):
                print(f"[午盘学习] {strat} 过拟合预警!")
            else:
                print(f"[午盘学习] WF {strat}: OOS效率={result.get('oos_efficiency', 'N/A')}")
    except Exception as e:
        print(f"[午盘学习] WF检测异常: {e}")

    print("[午盘学习] 完成")


def job_signal_tracker():
    """16:15 信号追踪"""
    s = _get_scheduler()
    if not s.is_trading_day():
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
    """一屏看系统全貌"""
    print("=" * 60)
    print("  量化多因子系统 — 状态面板")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    print(f"\n{'=' * 60}")


# ================================================================
#  持仓监控
# ================================================================

def job_monitor():
    """持仓监控定时任务"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from position_manager import check_exit_signals
        from notifier import format_exit_signal
        print(f"\n{'─' * 60}")
        print(f"  持仓监控  {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'─' * 60}")
        exits = check_exit_signals()
        if exits:
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
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
    except Exception as e:
        print(f"[持仓监控异常] {e}")


# ================================================================
#  评分 / 回填 / 周报
# ================================================================

def job_scorecard():
    """09:20 评分昨日推荐 + 更新黑名单 + 刷新 Agent 策略状态"""
    s = _get_scheduler()
    if not s.is_trading_day():
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


def job_backfill_returns():
    """16:30 回填全量候选的 T+1 收益率"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from scorecard import backfill_pending_returns
        n = backfill_pending_returns()
        if n > 0:
            print(f"[T+1回填] 完成 {n} 条")
    except Exception as e:
        print(f"[T+1回填异常] {e}")


def job_weekly_report():
    """周五 15:30 推送周报"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from scorecard import generate_weekly_report, notify_scorecard
        report = generate_weekly_report()
        try:
            from self_healer import generate_health_report
            report += "\n\n---\n\n" + generate_health_report()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        try:
            from auto_optimizer import generate_optimization_summary
            report += "\n\n---\n\n" + generate_optimization_summary()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        notify_scorecard(report)
    except ValueError as e:
        print(f"[周报熔断] scorecard.json 损坏 — {e}")
        logger.error("周报 严格模式熔断: %s", e)
    except Exception as e:
        print(f"[周报异常] {e}")


# ================================================================
#  Agent Brain
# ================================================================

def job_agent_morning():
    """09:15 推送早报"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from agent_brain import push_morning_briefing
        push_morning_briefing()
    except Exception as e:
        print(f"[Agent早报异常] {e}")


def job_agent_evening():
    """16:15 运行 OODA 循环 + 晚间摘要推送"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from agent_brain import run_agent_cycle, generate_evening_summary
        summary = run_agent_cycle()
        print(summary)
        evening = generate_evening_summary()
        if evening:
            from notifier import notify_wechat_raw
            now_str = datetime.now().strftime("%H:%M")
            notify_wechat_raw(f"[{now_str}] Agent 晚间摘要", evening)
    except Exception as e:
        print(f"[Agent OODA异常] {e}")


def job_night_shift():
    """18:00 夜班"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    s.run_with_retry(_run_night_shift, "夜班分析")


def _run_night_shift(**kwargs):
    """夜班深度分析"""
    from agent_brain import run_night_shift
    report = run_night_shift()
    if report:
        print(f"[夜班] 分析完成, 报告 {len(report)} 字")
    else:
        print("[夜班] LLM 不可用或无分析结果")
    return []


# ================================================================
#  冒烟测试 / 自动优化 / VaR / 因子
# ================================================================

def job_smoke_test():
    """09:10 开盘前冒烟测试"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from self_healer import run_smoke_test, auto_heal
        result = run_smoke_test()
        if not result["passed"]:
            auto_heal()
    except Exception as e:
        print(f"[冒烟测试异常] {e}")


def job_daily_optimize():
    """16:00 收盘后每日优化"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from auto_optimizer import run_daily_optimization
        run_daily_optimization()
    except Exception as e:
        print(f"[每日优化异常] {e}")


def job_var_risk():
    """16:10 收盘后 VaR/CVaR 风险度量"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from var_risk import calc_comprehensive_var
        result = calc_comprehensive_var(lookback_days=60)
        rating = result.get("risk_rating", "unknown")
        var95 = result.get("portfolio", {}).get("hist_var_95", 0)
        print(f"[VaR] 风险评级: {rating}, VaR(95%): {var95:+.4f}%")

        if rating == "high":
            try:
                from var_risk import generate_var_report
                from notifier import notify_alert, LEVEL_CRITICAL
                report = generate_var_report(result)
                notify_alert(LEVEL_CRITICAL, "高风险告警", report)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
    except Exception as e:
        print(f"[VaR异常] {e}")


def job_weekend_optimize():
    """周六 10:00 深度搜索"""
    try:
        from auto_optimizer import run_weekend_broad_search
        run_weekend_broad_search()
    except Exception as e:
        print(f"[周末优化异常] {e}")


def job_full_retrain():
    """周日 20:00 大周期重训"""
    try:
        from learning_engine import run_full_retrain
        run_full_retrain()
        print(f"[大周期重训] 完成")
    except Exception as e:
        print(f"[大周期重训异常] {e}")


def job_verify_optimizations():
    """16:50 验证近期优化效果"""
    s = _get_scheduler()
    if not s.is_trading_day():
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
                except Exception as _exc:
                    logger.debug("Suppressed exception: %s", _exc)
    except Exception as e:
        print(f"[优化验证异常] {e}")


def job_factor_lifecycle():
    """17:00 检查因子健康"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from auto_optimizer import check_factor_lifecycle
        results = check_factor_lifecycle()
        for r in results:
            print(f"[因子生命周期] {r.get('strategy')}: {r.get('factor')} → {r.get('action')}")
    except Exception as e:
        print(f"[因子生命周期异常] {e}")


def job_factor_forge():
    """17:30 Factor Forge"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from factor_forge import run_forge_cycle
        result = run_forge_cycle()
        deployed = result.get("deployed", [])
        retired = result.get("retired", [])
        if deployed or retired:
            from notifier import notify_wechat_raw
            lines = ["[17:30] Factor Forge"]
            for name in deployed:
                lines.append(f"  🚀 部署: s_forge_{name}")
            for r in retired:
                lines.append(f"  🗑️ 退役: {r['name']} ({r.get('reason', '')})")
            notify_wechat_raw("Factor Forge", "\n".join(lines))
    except Exception as e:
        logger.error("job_factor_forge failed: %s", e)


# ================================================================
#  个股诊断
# ================================================================

def job_stock_diagnosis(code=None):
    """10:00/13:00 盘中自动诊断"""
    s = _get_scheduler()
    if code is None and not s.is_trading_day():
        return
    try:
        from position_manager import load_positions
        from stock_analyzer import analyze_stock
        from db_store import load_trade_journal
        from notifier import notify_wechat_raw
        from datetime import date as _date

        today_str = _date.today().isoformat()
        codes_to_check = {}

        manual_code = str(code or "").strip()
        if manual_code:
            codes_to_check[manual_code] = "手动诊断"
        else:
            try:
                positions = load_positions()
                holding = [p for p in positions if not p.get("exit_date")]
                for p in holding:
                    codes_to_check[p["code"]] = f"持仓({p.get('strategy', '')})"
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            try:
                journal = load_trade_journal(days=0)
                for entry in journal:
                    if entry.get("date") == today_str:
                        for pick in entry.get("picks", []):
                            pick_code = pick.get("code", "")
                            if pick_code and len(pick_code) == 6:
                                codes_to_check.setdefault(pick_code, f"推荐({entry.get('strategy', '')})")
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            try:
                journal_2d = load_trade_journal(days=1)
                for entry in journal_2d:
                    if entry.get("date") != today_str:
                        for pick in entry.get("picks", []):
                            pick_code = pick.get("code", "")
                            if pick_code and len(pick_code) == 6:
                                codes_to_check.setdefault(pick_code, f"昨推({entry.get('strategy', '')})")
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        if not codes_to_check:
            print("[诊断] 无持仓/推荐, 跳过")
            return

        print(f"[诊断] 开始诊断 {len(codes_to_check)} 只...")
        alerts = []

        for c, source in codes_to_check.items():
            try:
                result = analyze_stock(c)
                if "error" in result:
                    continue

                name = result.get("name", c)
                price = result.get("price", 0)
                total = result.get("total_score", 0.5)
                verdict = result.get("verdict", "")
                stop_loss = result.get("stop_loss", 0)
                scores = result.get("scores", {})

                alert_reasons = []
                if total <= 0.40:
                    alert_reasons.append(f"评分{total:.2f}偏低")
                if result.get("direction") == "bearish":
                    alert_reasons.append("信号看空")
                if scores.get("momentum", 0.5) <= 0.30:
                    alert_reasons.append(f"动量极弱({scores['momentum']:.2f})")
                if scores.get("volume", 0.5) <= 0.30:
                    alert_reasons.append(f"量价异常({scores['volume']:.2f})")

                status_str = "正常" if not alert_reasons else "⚠告警"
                print(f"  {c}({name}) [{source}] {total:.2f} {verdict} {status_str}")

                if alert_reasons:
                    alerts.append({
                        "code": c, "name": name, "source": source,
                        "price": price, "total": total, "verdict": verdict,
                        "stop_loss": stop_loss, "reasons": alert_reasons,
                        "report": result.get("report_text", ""),
                    })
            except Exception as e:
                print(f"  {c} 诊断失败: {e}")

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


# ================================================================
#  纸盘 / 券商
# ================================================================

def job_paper_monitor():
    """11:00/14:00 纸盘持仓监控"""
    s = _get_scheduler()
    if not s.is_trading_day():
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
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from paper_trader import daily_settle
        result = daily_settle()
        n = result.get("trades_today", 0)
        if n > 0:
            print(f"[纸盘结算] {n}笔, PnL {result.get('pnl_today',0):+.2f}%")
    except Exception as e:
        print(f"[纸盘结算异常] {e}")


def job_broker_monitor():
    """10:30/13:30/14:45 券商持仓监控"""
    s = _get_scheduler()
    if not s.is_trading_day():
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


# ================================================================
#  ML / 实验 / 跨市场因子 / 环境路由 / 策略共识 / 收益归因
# ================================================================

def job_ml_train():
    """17:10 ML 因子模型增量训练"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from ml_factor_model import train_all_strategies
        result = train_all_strategies(lookback_days=1500)
        print(f"[ML训练] {result['summary']}")

        gr = result.get("global_result", {})
        if "error" not in gr:
            fi = gr.get("feature_importance", {})
            top3 = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:3]
            if top3:
                print(f"[ML训练] Top特征: {', '.join(f'{k}={v:.3f}' for k, v in top3)}")

        for strat, sr in result.get("strategy_results", {}).items():
            if "error" not in sr:
                n_feat = len(sr.get("features", []))
                n_ix = sr.get("n_interaction_features", 0)
                print(f"[ML训练]   {strat}: {sr['training_samples']}条 "
                      f"{n_feat}特征({n_ix}交互) {sr['metrics']}")
    except Exception as e:
        print(f"[ML训练异常] {e}")


def job_proactive_experiment():
    """16:45 主动扫描低健康度策略, 触发实验"""
    s = _get_scheduler()
    if not s.is_trading_day():
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

            history = safe_load(_EXPERIMENTS_PATH, default=[])
            for i, e in enumerate(history):
                if e.get("experiment_id") == exp.get("experiment_id"):
                    history[i] = exp
                    break
            safe_save(_EXPERIMENTS_PATH, history)
            print(f"[主动实验] {eng}: {exp.get('conclusion', '?')}")
    except Exception as e:
        print(f"[主动实验异常] {e}")


def job_cross_asset_factor():
    """07:35 跨市场因子计算"""
    try:
        from cross_asset_factor import calc_all_indicators
        result = calc_all_indicators()
        risk = result.get("ca_risk_appetite", 0.5)
        label = "RiskOn" if risk >= 0.65 else ("RiskOff" if risk <= 0.35 else "中性")
        print(f"[跨市场因子] risk={risk:.3f} [{label}] "
              f"US={result.get('ca_us_momentum', 0):.3f} "
              f"BTC={result.get('ca_btc_trend', 0):.3f}")
    except Exception as e:
        print(f"[跨市场因子异常] {e}")


def job_regime_router():
    """09:08 环境路由"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from regime_router import get_capital_ratios, get_routing_status
        get_capital_ratios()
        status = get_routing_status()
        skipped = status.get("skipped", [])
        print(f"[环境路由] regime={status.get('regime', '?')} "
              f"跳过={skipped if skipped else '无'}")
    except Exception as e:
        print(f"[环境路由异常] {e}")


def job_ensemble_midday():
    """10:20 盘中共识扫描"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from strategy_ensemble import get_consensus_recommendations
        consensus = get_consensus_recommendations()
        if consensus:
            from notifier import notify_wechat_raw
            lines = [f"多策略共识 ({len(consensus)}只)\n"]
            for c in consensus:
                lines.append(f"  {c['code']}({c['name']}) "
                             f"共识分{c['consensus_score']:.3f} "
                             f"策略{c['n_strategies']}个 "
                             f"族{c['families']}")
            notify_wechat_raw("🎯 盘中共识", "\n".join(lines))
            try:
                from learning_engine import record_trade_context
                items = [{"code": c["code"], "name": c["name"],
                          "score": c["consensus_score"],
                          "reason": f"共识{c['n_strategies']}策略"}
                         for c in consensus]
                record_trade_context("consensus", items)
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
        else:
            print("[共识] 盘中无共识信号")
    except Exception as e:
        print(f"[共识异常] {e}")


def job_ensemble_afternoon():
    """14:40 午后共识扫描"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from strategy_ensemble import get_consensus_recommendations
        consensus = get_consensus_recommendations()
        if consensus:
            from notifier import notify_wechat_raw
            lines = [f"多策略共识 ({len(consensus)}只)\n"]
            for c in consensus:
                lines.append(f"  {c['code']}({c['name']}) "
                             f"共识分{c['consensus_score']:.3f} "
                             f"策略{c['n_strategies']}个")
            notify_wechat_raw("🎯 午后共识", "\n".join(lines))
        else:
            print("[共识] 午后无共识信号")
    except Exception as e:
        print(f"[共识异常] {e}")


def job_attribution():
    """16:20 收益归因"""
    s = _get_scheduler()
    if not s.is_trading_day():
        return
    try:
        from attribution import run_full_attribution, format_attribution_report
        result = run_full_attribution()
        report = format_attribution_report(result)
        print(f"[归因] {report[:200]}...")

        sources = result.get("alpha_sources", [])
        drains = result.get("alpha_drains", [])
        if sources or drains:
            from notifier import notify_wechat_raw
            lines = ["收益归因摘要"]
            if sources:
                lines.append("Alpha来源: " + " | ".join(sources))
            if drains:
                lines.append("Alpha流失: " + " | ".join(drains))
            notify_wechat_raw("[16:20] 收益归因", "\n".join(lines))
    except Exception as e:
        print(f"[归因异常] {e}")


def job_global_news():
    """全球新闻雷达"""
    try:
        from global_news_monitor import scan_global_news
        result = scan_global_news()
        n = result.get("n_events", 0)
        ss = result.get("sentiment", 0)
        if n > 0:
            print(f"[新闻雷达] {n} 条重大新闻, 情绪 {ss:+.2f}")
        else:
            print("[新闻雷达] 无重大新闻")
    except Exception as e:
        print(f"[新闻雷达异常] {e}")
