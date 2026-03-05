# 量化多因子系统 — 移动端 APP 接口规范 (v2.0)

本规范定义了从本地脚本向“移动端前后端分离架构”演进时的核心接口契约。后端将基于 `FastAPI` 重构，前端（如 Flutter/React Native）将通过本规范与智能体大脑交互。

## 1. 核心架构升级要求
*   **安全认证:** 所有非公开接口必须在 Header 中携带 `Authorization: Bearer <JWT_TOKEN>`。
*   **实时通信:** 引入 WebSocket 协议，用于大盘异动和 Agent 紧急决策的毫秒级推送，消除长轮询延迟。
*   **统一路由:** 新版 API 统一挂载至 `/api/v2/` 路由下。

---

## 2. RESTful API 规范

### 2.1 鉴权模块 (Auth)
*   **`POST /api/v2/auth/login`**
    *   **描述:** 用户登录获取 Token。
    *   **Payload:** `{"username": "admin", "password": "***"}`
    *   **Response:** `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 86400}`

### 2.2 仪表盘总览 (Dashboard)
*   **`GET /api/v2/dashboard/overview`**
    *   **描述:** 获取首页核心数据（大盘评分、VaR 风险、当日盈亏估算）。
    *   **Response:**
        ```json
        {
          "regime": {"status": "bull", "score": 0.85},
          "risk": {"var_95": -2.3, "portfolio_health": 0.9},
          "pnl": {"daily_pct": 1.2, "win_rate": 0.65}
        }
        ```

### 2.3 策略与控制 (Strategy Management)
*   **`GET /api/v2/strategies`**
    *   **描述:** 获取 12 个策略的运行状态与历史胜率。
*   **`PUT /api/v2/strategies/{strategy_id}/status`**
    *   **描述:** 手动干预策略（APP 内的启停开关）。
    *   **Payload:** `{"action": "pause", "reason": "手机端手动干预"}`

### 2.4 持仓与交易 (Portfolio & Trades)
*   **`GET /api/v2/portfolio/positions`**
    *   **描述:** 获取当前 A股/期货/币圈 的实时持仓与浮亏浮盈。
*   **`POST /api/v2/portfolio/liquidate`**
    *   **描述:** **【高危接口】** 一键清仓某策略下的所有持仓（需二次密码验证）。

### 2.5 智能体洞察 (Agent Brain)
*   **`GET /api/v2/agent/insights`**
    *   **描述:** 获取 OODA 循环产生的分级洞察列表（Critical / Warning / Info）。

---

## 3. WebSocket 实时推送 (WSS)

### 3.1 频道: `/api/v2/ws/system`
移动端连接后，后端将在以下事件发生时主动下发消息：
1.  **策略发车提醒:** `{"event": "job_started", "strategy": "放量突破选股"}`
2.  **交易信号生成:** `{"event": "signal_generated", "code": "300303", "action": "buy"}`
3.  **Agent 紧急风控:** `{"event": "agent_action", "severity": "critical", "message": "大盘转熊，自动平仓"}`

---
*设计人: Gemini CLI 架构师*
*更新日期: 2026-03-04*
