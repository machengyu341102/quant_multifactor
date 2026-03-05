# 量化多因子智能体系统 v2.0 运维手册

> **版本:** v2.0 (2026-03-04)
> **状态:** 生产级 (Enterprise Ready)
> **核心特性:** 模块化解耦、SQLite 存储、多源负载均衡、企业微信双向中控

---

## 1. 核心架构总览 (Architecture)

系统采用 **“大脑 - 调度 - 执行”** 三层架构：
1.  **Agent Brain (`agent_brain.py`):** 系统的灵魂。执行 OODA 循环，负责冲突仲裁、策略启停决策及认知提取。
2.  **Scheduler (`scheduler.py`):** 系统的节奏器。通过 `strategies.json` 动态加载 12 个策略，管理 37 个定时任务。
3.  **Infrastructure:**
    *   **`api_guard.py`:** 护城河。实现 11 个数据源的负载均衡、限流与断路保护。
    *   **`db_store.py`:** 记忆库。使用 SQLite (WAL模式) 存储高频成交、信号与审计数据。
    *   **`dashboard.py`:** 监控塔。提供 WebSocket 实时看板与企业微信双向指令回调。

---

## 2. 启动与运行 (Quick Start)

### 2.1 核心服务启动
建议在后台或 `tmux` 会话中运行：
```bash
# 1. 启动调度器 (管理定时选股/风控)
python3 scheduler.py daemon

# 2. 启动可视化仪表盘 (含 Webhook 回调)
python3 dashboard.py --port 8501

# 3. 启动智能体大脑 (15分钟一个周期)
python3 agent_brain.py
```

### 2.2 CLI 常用指令
*   **查看当前任务倒计时:** `python3 scheduler.py status`
*   **手动测试所有选股:** `python3 scheduler.py test`
*   **查看 API 源健康度:** `python3 scheduler.py sources`
*   **查看数据库统计:** `python3 db_store.py stats`
*   **手动个股诊断:** `python3 scheduler.py analyze 002221`

---

## 3. 企业微信远程中控 (Remote Control)

系统已集成双向通信，您可以在企业微信中通过发送关键字直接下令：

| 指令关键词 | 功能说明 | 响应示例 |
| :--- | :--- | :--- |
| **`状态`** | 查看全系统进程、策略活跃数及大盘评分 | 🟢 系统运行中, 大盘: 0.85 (牛) |
| **`持仓`** | 查询当前实盘/纸盘 A股、期货持仓明细 | 300303 聚飞光电 (浮盈 +5.2%) |
| **`今日`** | 获取今日所有已生成的选股信号汇总 | [放量突破] 航天彩虹 ... |
| **`风险`** | 查看系统当前的 VaR 风险值及组合回撤 | 组合 VaR: -2.3%, 风险平价: 正常 |
| **`诊断 300XXX`** | 对特定个股进行实时因子诊断 | RSI: 58 (中性), 量价: 0.45 ... |
| **`跑策略 集合竞价`** | 远程立即触发特定策略运行 | 正在为您执行 [集合竞价选股]... |

---

## 4. 智能风控体系 (Risk Control)

1.  **Regime Filter (大盘过滤):** 8 指标评分制。评分 < 0.35 (Bear) 时自动拦截所有买入指令。
2.  **Kelly Criterion (仓位管理):** 基于历史胜率/盈亏比自动调整单笔仓位，保护本金。
3.  **Risk Parity (风险平价):** 根据策略波动率自动分配权重，防止单一策略风险过载。
4.  **Conflict Resolution (冲突仲裁):** 当风控建议“卖出”而策略建议“买入”时，Agent 强制执行风控指令，并将仲裁过程存入 `conflict_audit` 表。

---

## 5. 日常维护指南 (Maintenance)

### 5.1 数据库维护
系统会自动清理 `conflict_audit` 表，仅保留最近 500 条记录。建议每月执行一次数据库压缩：
```bash
sqlite3 quant_data.db "VACUUM;"
```

### 5.2 缓存与 API 保护
*   **API 熔断恢复:** 若某个源（如东财）被封禁，`api_guard` 会自动熔断 120s。无需人工干预，系统会自动降级到腾讯或新浪源。
*   **持久化缓存:** 核心数据存在 `.api_cache.json`。如需强制全量更新，删除该文件即可。

### 5.3 故障自愈 (Self-Healing)
系统每日 09:10 会自动运行“冒烟测试”：
*   若发现 akshare 失效或磁盘空间不足，会通过企业微信推送 **🔴 Critical** 告警。
*   您可以发送 `优化` 指令给机器人，尝试触发 `self_healer.py` 的自动修复逻辑。

---
*Gemini CLI 架构室 2026-03-04*
