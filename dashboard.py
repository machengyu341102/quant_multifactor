"""
智能体轻量仪表盘 (OP-09)
========================
FastAPI 极简 Web Dashboard, 实时可视化:
  - 大盘评分 / 市场状态
  - Agent 决策链路 / 冲突日志
  - 活跃策略热力图
  - 系统实时回撤 / VaR

启动:
  python3 dashboard.py              # http://0.0.0.0:8501
  python3 dashboard.py --port 9000  # 自定义端口
"""

from __future__ import annotations

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from datetime import date, timedelta

from json_store import safe_load
from log_config import get_logger

logger = get_logger("dashboard")

_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="量化多因子仪表盘", version="1.0")


# ================================================================
#  WebSocket 实时推送 (EX-01)
# ================================================================

class ConnectionManager:
    """管理 WebSocket 连接, 支持广播"""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = threading.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket 连接: %d 个客户端", len(self._connections))

    def disconnect(self, ws: WebSocket):
        with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket 断开: %d 个客户端", len(self._connections))

    async def broadcast(self, data: dict):
        """广播 JSON 消息给所有连接"""
        if not self._connections:
            return
        msg = json.dumps(data, ensure_ascii=False, default=str)
        with self._lock:
            stale = []
            for ws in self._connections:
                try:
                    await ws.send_text(msg)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.remove(ws)

    @property
    def count(self):
        return len(self._connections)


ws_manager = ConnectionManager()


def push_event(event_type: str, payload: dict):
    """从外部模块推送事件到 Dashboard (线程安全)

    用法:
        from dashboard import push_event
        push_event("strategy_complete", {"name": "放量突破", "status": "ok"})
        push_event("signal_new", {"code": "000001", "score": 85})
        push_event("position_change", {"action": "buy", "code": "600036"})
    """
    if ws_manager.count == 0:
        return
    data = {"type": event_type, "payload": payload, "ts": date.today().isoformat()}
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(ws_manager.broadcast(data))
        else:
            loop.run_until_complete(ws_manager.broadcast(data))
    except RuntimeError:
        # 没有事件循环 (从非 async 线程调用)
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws_manager.broadcast(data))
            loop.close()
        except Exception:
            pass


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # 保持连接, 接收客户端心跳
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ================================================================
#  API 路由
# ================================================================

@app.get("/api/overview")
def api_overview():
    """系统总览: 进程状态 / 今日策略 / 持仓 / VaR"""
    heartbeat = safe_load(os.path.join(_DIR, "heartbeat.json"), default={})
    positions = safe_load(os.path.join(_DIR, "positions.json"), default=[])
    var_results = safe_load(os.path.join(_DIR, "var_results.json"), default=[])
    night_log = safe_load(os.path.join(_DIR, "night_shift_log.json"), default={})

    # 策略执行状态
    strategy_status = heartbeat.get("strategy_status", {})
    strategies = []
    for name, info in strategy_status.items():
        strategies.append({
            "name": name,
            "status": info.get("status", "unknown"),
            "last_run": info.get("last_run", ""),
            "duration": info.get("duration_sec", 0),
            "error": info.get("error_msg", ""),
        })

    # VaR
    var_latest = var_results[-1] if var_results else {}
    var_info = {
        "risk_rating": var_latest.get("risk_rating", "N/A"),
        "var_95": var_latest.get("portfolio", {}).get("hist_var_95", 0),
        "cvar_99": var_latest.get("portfolio", {}).get("hist_cvar_99", 0),
        "date": var_latest.get("date", ""),
    }

    # 持仓
    holdings = []
    for p in positions[:20]:
        holdings.append({
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "strategy": p.get("strategy", ""),
            "entry_price": p.get("entry_price", 0),
            "score": p.get("score", 0),
            "entry_date": p.get("entry_date", ""),
        })

    return {
        "date": date.today().isoformat(),
        "heartbeat_age": heartbeat.get("age_seconds", 0),
        "strategies": strategies,
        "holdings_count": len(positions),
        "holdings": holdings,
        "var": var_info,
        "night_shift": {
            "date": night_log.get("date", ""),
            "status": night_log.get("status", "unknown"),
        },
    }


@app.get("/api/regime")
def api_regime():
    """大盘评分 / 市场状态"""
    memory = safe_load(os.path.join(_DIR, "agent_memory.json"), default={})
    regime = memory.get("regime", {})
    return {
        "score": regime.get("score", 50),
        "regime": regime.get("regime", "neutral"),
        "updated": regime.get("updated", ""),
        "details": regime.get("details", {}),
    }


@app.get("/api/drawdown")
def api_drawdown():
    """组合回撤 + Kelly + Risk Parity"""
    try:
        from portfolio_risk import calc_portfolio_drawdown, calc_kelly_fractions, calc_risk_parity_allocation
        drawdown = calc_portfolio_drawdown()
        kelly = calc_kelly_fractions()
        rp = calc_risk_parity_allocation()
        return {
            "drawdown": drawdown,
            "kelly": kelly,
            "risk_parity": rp,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/signals")
def api_signals():
    """信号追踪统计"""
    try:
        from signal_tracker import get_stats
        return get_stats(days=7)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/conflicts")
def api_conflicts():
    """Agent 冲突仲裁日志"""
    try:
        from db_store import load_conflict_audit
        records = load_conflict_audit(limit=50)
        return {"conflicts": records, "total": len(records)}
    except Exception:
        records = safe_load(os.path.join(_DIR, "conflict_audit.json"), default=[])
        return {"conflicts": records[-50:], "total": len(records)}


@app.get("/api/agents")
def api_agents():
    """智能体注册状态"""
    try:
        from agent_registry import get_registry
        registry = get_registry()
        agents = []
        for name, info in registry._agents.items():
            agents.append({
                "name": name,
                "role": info.role,
                "status": info.status,
                "last_run": info.last_run,
                "error_count": info.error_count,
                "uptime_pct": round(info.uptime_pct(), 1),
            })
        return {"agents": agents}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/equity")
def api_equity():
    """资金曲线"""
    try:
        from scorecard import calc_equity_curve
        return calc_equity_curve()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/paper")
def api_paper():
    """纸盘模拟交易 (EX-04)"""
    try:
        from paper_trader import get_holdings_summary, calc_statistics
        holdings = get_holdings_summary()
        stats = calc_statistics(days=7)
        trades = safe_load(os.path.join(_DIR, "paper_trades.json"), default=[])
        return {
            "holdings": holdings,
            "stats": stats,
            "recent_trades": trades[-20:],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/factors")
def api_factors():
    """ML 因子重要性排名 (EX-03)"""
    try:
        results = safe_load(os.path.join(_DIR, "ml_model_results.json"), default={})
        importance = results.get("feature_importance", {})
        # 按重要性排序
        sorted_factors = sorted(importance.items(), key=lambda x: -x[1])
        return {
            "factors": [{"name": k, "importance": round(v, 4)} for k, v in sorted_factors],
            "model_date": results.get("train_date", ""),
            "model_score": results.get("test_score", 0),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/heatmap")
def api_heatmap():
    """策略热力图: 近7天每个策略每天的平均收益"""
    try:
        from db_store import load_scorecard
        records = load_scorecard(days=7)
    except Exception:
        records = safe_load(os.path.join(_DIR, "scorecard.json"), default=[])

    cutoff = (date.today() - timedelta(days=7)).isoformat()

    # {strategy: {date: avg_return}}
    heatmap = {}
    for r in records:
        rec_date = r.get("rec_date", "")
        if rec_date < cutoff:
            continue
        strategy = r.get("strategy", "")
        ret = r.get("net_return_pct", 0)
        heatmap.setdefault(strategy, {}).setdefault(rec_date, []).append(ret)

    # 平均化
    result = {}
    all_dates = set()
    for strategy, dates_dict in heatmap.items():
        result[strategy] = {}
        for d, rets in dates_dict.items():
            result[strategy][d] = round(sum(rets) / len(rets), 2)
            all_dates.add(d)

    return {
        "heatmap": result,
        "dates": sorted(all_dates),
    }


# ================================================================
#  前端 HTML (单页内嵌)
# ================================================================

@app.get("/", response_class=HTMLResponse)
def index():
    return _DASHBOARD_HTML


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>量化多因子仪表盘</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'SF Pro', 'Helvetica Neue', sans-serif;
       background: #0d1117; color: #c9d1d9; }
.header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
           display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 18px; color: #58a6ff; }
.header .time { font-size: 13px; color: #8b949e; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
        gap: 16px; padding: 16px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
        padding: 16px; }
.card h2 { font-size: 14px; color: #58a6ff; margin-bottom: 12px;
           border-bottom: 1px solid #21262d; padding-bottom: 8px; }
.metric { display: flex; justify-content: space-between; padding: 4px 0;
          font-size: 13px; border-bottom: 1px solid #21262d; }
.metric:last-child { border-bottom: none; }
.metric .label { color: #8b949e; }
.metric .value { font-weight: 600; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 12px;
       font-size: 11px; font-weight: 600; }
.tag-ok { background: #0d4429; color: #3fb950; }
.tag-warn { background: #4a3200; color: #d29922; }
.tag-err { background: #490202; color: #f85149; }
.tag-info { background: #0c2d6b; color: #58a6ff; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
table th { text-align: left; color: #8b949e; padding: 6px 4px;
           border-bottom: 1px solid #30363d; }
table td { padding: 6px 4px; border-bottom: 1px solid #21262d; }
.heatmap-cell { display: inline-block; width: 48px; height: 28px;
                text-align: center; line-height: 28px; font-size: 11px;
                border-radius: 4px; margin: 1px; }
.regime-bar { height: 8px; border-radius: 4px; margin-top: 8px; }
.nav-chart { width: 100%; height: 120px; }
#refresh-btn { cursor: pointer; background: #21262d; border: 1px solid #30363d;
               color: #c9d1d9; padding: 4px 12px; border-radius: 6px; font-size: 12px; }
#refresh-btn:hover { background: #30363d; }
</style>
</head>
<body>
<div class="header">
  <h1>量化多因子仪表盘</h1>
  <div>
    <button id="refresh-btn" onclick="loadAll()">刷新</button>
    <span class="time" id="update-time"></span>
  </div>
</div>
<div class="grid" id="dashboard"></div>

<script>
const $ = id => document.getElementById(id);

function tag(status) {
  const map = { ok: 'tag-ok', success: 'tag-ok', running: 'tag-info',
                error: 'tag-err', failed: 'tag-err', warning: 'tag-warn',
                unknown: 'tag-warn', healthy: 'tag-ok', degraded: 'tag-warn' };
  const cls = map[status] || 'tag-info';
  return `<span class="tag ${cls}">${status}</span>`;
}

function heatColor(val) {
  if (val > 2) return '#0d4429';
  if (val > 0) return '#1a3a2a';
  if (val > -1) return '#3a2a1a';
  return '#490202';
}

async function fetchJSON(url) {
  try {
    const r = await fetch(url);
    return await r.json();
  } catch { return {}; }
}

async function loadAll() {
  $('update-time').textContent = new Date().toLocaleTimeString();
  const [overview, regime, drawdown, signals, heatmap, agents, equity, conflicts, paper, factors] =
    await Promise.all([
      fetchJSON('/api/overview'),
      fetchJSON('/api/regime'),
      fetchJSON('/api/drawdown'),
      fetchJSON('/api/signals'),
      fetchJSON('/api/heatmap'),
      fetchJSON('/api/agents'),
      fetchJSON('/api/equity'),
      fetchJSON('/api/conflicts'),
      fetchJSON('/api/paper'),
      fetchJSON('/api/factors'),
    ]);

  let html = '';

  // 大盘评分
  const rs = regime.score || 50;
  const regColor = rs >= 70 ? '#3fb950' : rs >= 40 ? '#d29922' : '#f85149';
  html += `<div class="card">
    <h2>大盘评分</h2>
    <div class="metric"><span class="label">评分</span>
      <span class="value" style="color:${regColor};font-size:24px">${rs}</span></div>
    <div class="metric"><span class="label">状态</span>
      <span class="value">${regime.regime || 'N/A'}</span></div>
    <div class="metric"><span class="label">更新</span>
      <span class="value">${regime.updated || 'N/A'}</span></div>
    <div class="regime-bar" style="background:linear-gradient(90deg,#f85149 0%,#d29922 40%,#3fb950 100%);position:relative">
      <div style="position:absolute;left:${rs}%;top:-4px;width:3px;height:16px;background:#fff;border-radius:2px"></div>
    </div>
  </div>`;

  // VaR 风控
  const v = overview.var || {};
  html += `<div class="card">
    <h2>VaR 风控</h2>
    <div class="metric"><span class="label">风险评级</span>
      <span class="value">${tag(v.risk_rating || 'N/A')}</span></div>
    <div class="metric"><span class="label">VaR(95%)</span>
      <span class="value">${(v.var_95 || 0).toFixed(2)}%</span></div>
    <div class="metric"><span class="label">CVaR(99%)</span>
      <span class="value">${(v.cvar_99 || 0).toFixed(2)}%</span></div>
  </div>`;

  // 组合回撤
  const dd = drawdown.drawdown || {};
  html += `<div class="card">
    <h2>组合回撤</h2>
    <div class="metric"><span class="label">当前回撤</span>
      <span class="value" style="color:${(dd.current_drawdown_pct||0)<-3?'#f85149':'#c9d1d9'}">${(dd.current_drawdown_pct||0).toFixed(2)}%</span></div>
    <div class="metric"><span class="label">最大回撤</span>
      <span class="value">${(dd.max_drawdown_pct||0).toFixed(2)}%</span></div>
    <div class="metric"><span class="label">回撤天数</span>
      <span class="value">${dd.drawdown_days||0}</span></div>
    <div class="metric"><span class="label">组合净值</span>
      <span class="value">${(dd.nav||1).toFixed(4)}</span></div>
  </div>`;

  // 信号追踪
  const sig = signals.overall || {};
  html += `<div class="card">
    <h2>信号追踪 (7天)</h2>
    <div class="metric"><span class="label">总信号</span>
      <span class="value">${signals.total_signals || 0}</span></div>
    <div class="metric"><span class="label">T+1 胜率</span>
      <span class="value">${((sig.t1_win_rate||0)*100).toFixed(1)}%</span></div>
    <div class="metric"><span class="label">T+3 胜率</span>
      <span class="value">${((sig.t3_win_rate||0)*100).toFixed(1)}%</span></div>
    <div class="metric"><span class="label">T+1 平均收益</span>
      <span class="value">${(sig.t1_avg_return||0).toFixed(2)}%</span></div>
  </div>`;

  // 持仓
  let holdHtml = '<table><tr><th>代码</th><th>名称</th><th>策略</th><th>评分</th></tr>';
  for (const h of (overview.holdings || []).slice(0, 8)) {
    holdHtml += `<tr><td>${h.code}</td><td>${h.name}</td><td>${h.strategy}</td><td>${h.score}</td></tr>`;
  }
  holdHtml += '</table>';
  html += `<div class="card">
    <h2>A股持仓 (${overview.holdings_count || 0})</h2>${holdHtml}</div>`;

  // 策略执行
  let stHtml = '<table><tr><th>策略</th><th>状态</th><th>耗时</th></tr>';
  for (const s of overview.strategies || []) {
    stHtml += `<tr><td>${s.name}</td><td>${tag(s.status)}</td><td>${s.duration}s</td></tr>`;
  }
  stHtml += '</table>';
  html += `<div class="card"><h2>今日策略</h2>${stHtml}</div>`;

  // 智能体
  let agHtml = '<table><tr><th>智能体</th><th>状态</th><th>在线率</th></tr>';
  for (const a of (agents.agents || [])) {
    agHtml += `<tr><td>${a.name}</td><td>${tag(a.status)}</td><td>${a.uptime_pct}%</td></tr>`;
  }
  agHtml += '</table>';
  html += `<div class="card"><h2>子智能体</h2>${agHtml}</div>`;

  // 策略热力图
  const hm = heatmap.heatmap || {};
  const dates = heatmap.dates || [];
  let hmHtml = '<div style="overflow-x:auto">';
  hmHtml += '<table><tr><th></th>';
  for (const d of dates) hmHtml += `<th style="font-size:10px">${d.slice(5)}</th>`;
  hmHtml += '</tr>';
  for (const [strat, vals] of Object.entries(hm)) {
    hmHtml += `<tr><td style="font-size:11px;white-space:nowrap">${strat}</td>`;
    for (const d of dates) {
      const val = vals[d] ?? '-';
      const bg = typeof val === 'number' ? heatColor(val) : '#21262d';
      const txt = typeof val === 'number' ? val.toFixed(1) : '-';
      hmHtml += `<td><div class="heatmap-cell" style="background:${bg}">${txt}</div></td>`;
    }
    hmHtml += '</tr>';
  }
  hmHtml += '</table></div>';
  html += `<div class="card" style="grid-column:1/-1"><h2>策略热力图 (近7天, %)</h2>${hmHtml}</div>`;

  // 资金曲线
  const navs = equity.nav_series || [];
  if (navs.length > 0) {
    const maxNav = Math.max(...navs.map(n => n[1]));
    const minNav = Math.min(...navs.map(n => n[1]));
    const range = maxNav - minNav || 0.01;
    let path = '';
    const w = 800, h = 120;
    navs.forEach((n, i) => {
      const x = (i / (navs.length - 1 || 1)) * w;
      const y = h - ((n[1] - minNav) / range) * (h - 10) - 5;
      path += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1);
    });
    html += `<div class="card" style="grid-column:1/-1">
      <h2>资金曲线 (总收益 ${(equity.total_return||0).toFixed(2)}%, Sharpe ${(equity.sharpe||0).toFixed(2)})</h2>
      <svg viewBox="0 0 ${w} ${h}" class="nav-chart">
        <path d="${path}" fill="none" stroke="#58a6ff" stroke-width="2"/>
      </svg></div>`;
  }

  // 冲突日志
  const cfs = (conflicts.conflicts || []).slice(-10).reverse();
  if (cfs.length > 0) {
    let cfHtml = '<table><tr><th>时间</th><th>胜者</th><th>败者</th></tr>';
    for (const c of cfs) {
      cfHtml += `<tr><td style="font-size:11px">${(c.timestamp||'').slice(11,19)}</td>
        <td style="color:#3fb950">${c.winner_action||''}</td>
        <td style="color:#f85149">${c.loser_action||''}</td></tr>`;
    }
    cfHtml += '</table>';
    html += `<div class="card"><h2>冲突仲裁 (最近10条)</h2>${cfHtml}</div>`;
  }

  // Kelly 准则
  const kelly = drawdown.kelly || {};
  const kellyEntries = Object.entries(kelly).filter(([_,v]) => v.sample_count >= 5);
  if (kellyEntries.length > 0) {
    let kHtml = '<table><tr><th>策略</th><th>胜率</th><th>Half-K</th><th>样本</th></tr>';
    kellyEntries.sort((a,b) => b[1].kelly_half - a[1].kelly_half);
    for (const [name, k] of kellyEntries) {
      kHtml += `<tr><td style="font-size:11px">${name}</td>
        <td>${(k.win_rate*100).toFixed(0)}%</td>
        <td style="color:#58a6ff">${(k.kelly_half*100).toFixed(1)}%</td>
        <td>${k.sample_count}</td></tr>`;
    }
    kHtml += '</table>';
    html += `<div class="card"><h2>Kelly 准则</h2>${kHtml}</div>`;
  }

  // 纸盘模拟交易 (EX-04)
  const ps = paper.stats || {};
  const ph = paper.holdings || {};
  if (!paper.error) {
    let pHtml = `<div class="metric"><span class="label">持仓数</span>
      <span class="value">${(ph.positions||[]).length}</span></div>
    <div class="metric"><span class="label">可用资金</span>
      <span class="value">${(ph.available_capital||0).toLocaleString()}</span></div>
    <div class="metric"><span class="label">7天胜率</span>
      <span class="value">${((ps.win_rate||0)*100).toFixed(0)}%</span></div>
    <div class="metric"><span class="label">7天盈亏</span>
      <span class="value" style="color:${(ps.total_pnl||0)>=0?'#3fb950':'#f85149'}">${(ps.total_pnl||0).toFixed(2)}%</span></div>`;
    const ptrades = (paper.recent_trades||[]).slice(-5).reverse();
    if (ptrades.length) {
      pHtml += '<table style="margin-top:8px"><tr><th>日期</th><th>代码</th><th>方向</th><th>盈亏</th></tr>';
      for (const t of ptrades) {
        const pnl = t.pnl_pct || 0;
        pHtml += `<tr><td style="font-size:11px">${(t.date||'').slice(5)}</td>
          <td>${t.code||''}</td><td>${t.action||''}</td>
          <td style="color:${pnl>=0?'#3fb950':'#f85149'}">${pnl.toFixed(2)}%</td></tr>`;
      }
      pHtml += '</table>';
    }
    html += `<div class="card"><h2>纸盘模拟</h2>${pHtml}</div>`;
  }

  // 因子重要性 (EX-03)
  const flist = (factors.factors||[]).slice(0, 12);
  if (flist.length > 0) {
    const maxImp = flist[0].importance || 0.01;
    let fHtml = '';
    for (const f of flist) {
      const pct = (f.importance / maxImp * 100).toFixed(0);
      fHtml += `<div style="display:flex;align-items:center;margin:3px 0;font-size:12px">
        <span style="width:120px;color:#8b949e">${f.name}</span>
        <div style="flex:1;height:14px;background:#21262d;border-radius:3px;overflow:hidden">
          <div style="width:${pct}%;height:100%;background:#58a6ff;border-radius:3px"></div>
        </div>
        <span style="width:50px;text-align:right;color:#c9d1d9">${f.importance.toFixed(3)}</span>
      </div>`;
    }
    html += `<div class="card"><h2>因子重要性 (${factors.model_date||''})</h2>${fHtml}</div>`;
  }

  $('dashboard').innerHTML = html;
}

loadAll();
setInterval(loadAll, 60000);

// WebSocket 实时推送
let ws, wsRetry = 0;
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => { wsRetry = 0; console.log('WS connected'); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'pong') return;
    // 收到实时事件, 局部刷新
    console.log('WS event:', msg.type, msg.payload);
    if (['strategy_complete','signal_new','position_change','regime_update'].includes(msg.type)) {
      loadAll();  // 简单策略: 收到事件就全量刷新
    }
  };
  ws.onclose = () => {
    wsRetry++;
    const delay = Math.min(wsRetry * 2000, 30000);
    console.log(`WS closed, retry in ${delay}ms`);
    setTimeout(connectWS, delay);
  };
  // 心跳
  setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 25000);
}
connectWS();
</script>
</body>
</html>"""


# ================================================================
#  启动
# ================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="量化多因子仪表盘")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import uvicorn
    print(f"\n  仪表盘启动: http://{args.host}:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
