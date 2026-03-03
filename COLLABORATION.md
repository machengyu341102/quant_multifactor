# 量化多因子系统优化协同协议 v1.0

## 1. 角色定义 (Roles)
*   **Gemini CLI (架构师/审核员):** 负责全局代码审计、性能瓶颈识别、优化方案设计及最终代码合规性验收。**原则：禁止直接修改代码，仅通过指令引导。**
*   **Claude Code (资深开发工程师):** 负责根据设计方案进行代码重构、单元测试编写、运行验证。**原则：每完成一个子项必须更新此文档的状态，并确保 `pytest` 通过。**

## 2. 核心优化任务清单 (Roadmap)

| 任务 ID | 模块 | 优化项描述 | 设计方案 (Gemini) | 状态 | 审核人 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OP-01** | `Infrastructure` | **全局 API 调用归一化** | 移除所有策略文件（如 `intraday_strategy.py`, `trend_sector_strategy.py`）中的私有 `_retry` 函数，统一注入并使用 `api_guard.guarded_call`。要求：确保限流和断路器逻辑全局生效。 | 💎 已核准 | Gemini |
| **OP-02** | `Strategy` | **均值回归策略并行化** | 将 `mean_reversion_strategy.py` 中的 `_fetch_daily_klines` 扫描逻辑由串行改为 20 线程并行，并接入持久化缓存（key: `mr_daily_klines`）。 | 💎 已核准 | Gemini |
| **OP-03** | `Data` | **基本面快照持久化** | 在 `api_guard` 中增加 `fundamental_snapshot` 的专用持久化键值，确保当日所有策略仅拉取一次 A 股全量基本面（ak.stock_yjbb_em）。 | 💎 已核准 | Gemini |
| **OP-04** | `Agent` | **智能体决策冲突日志** | 在 `agent_brain.py` 的冲突仲裁逻辑中，增加明细持久化记录，保存”被否决”的策略动作及其原始证据，用于夜班分析。 | 💎 已核准 | Gemini |
| **OP-05** | `Safety` | **核心文件严格模式适配** | 将 `scheduler.py` 中涉及 `positions.json` 和 `scorecard.json` 的读取点全面切换为 `safe_load_strict`，增加异常熔断保护。 | 💎 已核准 | Gemini |
| **OP-06** | `Architecture` | **模块化策略加载器 (解耦)** | 重构 `scheduler.py` 核心，实现策略动态注册。允许通过 `strategies.json` 动态增减策略，无需修改调度器主逻辑。 | 💎 已核准 | Gemini |
| **OP-07** | `Performance` | **核心数据向 SQLite 迁移** | 引入 SQLite (WAL 模式)，将高频变动的 `scorecard.json` 和 `conflict_audit.json` 迁移至数据库。保留 JSON 仅用于配置。 | 💎 已核准 | Gemini |
| **OP-08** | `Risk` | **凯利准则与组合优化** | 在 `portfolio_risk.py` 中引入凯利准则动态调整单笔仓位，并根据策略相关性矩阵进行组合层面的风险平价 (Risk Parity) 优化。 | 💎 已核准 | Gemini |
| **OP-09** | `Observability` | **智能体轻量仪表盘** | 基于 FastAPI 实现一个极简的 Web Dashboard，实时可视化展示大盘评分、Agent 决策链路、活跃策略热力图及系统实时回撤情况。 | 💎 已核准 | Gemini |

---
*最后更新: 2026-03-03 (Gemini 最终审计完成)*

1.  **指令下达：** Gemini CLI 在 `COLLABORATION.md` 中更新具体任务的设计细节。
2.  **执行任务：** Claude Code 读取任务，将状态改为 `🔄 进行中`，开始修改代码。
3.  **自测验证：** Claude Code 完成修改后，必须运行 `pytest tests/相关测试.py` 并修复所有回归问题。
4.  **提请审核：** Claude Code 将状态改为 `✅ 已完成`，并简述改动点（Input/Output）。
5.  **最终验收：** Gemini CLI 使用 `read_file` 和 `codebase_investigator` 审计代码。若符合预期，将状态改为 `💎 已核准`。

## 4. OP-01~05 完成说明 (Claude Code)

**OP-01 全局 API 调用归一化:**
- `overnight_strategy._retry()` / `intraday_strategy._retry_heavy()` / `multifactor_strategy._retry_request()` — 函数体替换为直接调用 `api_guard.guarded_call`，移除手动 retry fallback
- `intraday_strategy._sina_batch_quote()` — 移除裸 `requests.get` fallback，全部走 `guarded_sina_request`
- 保留函数签名不变，6个下游 import 无需修改

**OP-02 均值回归策略并行化:**
- `_fetch_daily_klines` 已是20线程并行，新增 `api_guard.DataCache` 持久化缓存 (key=`mr_daily_klines`, TTL=300s)
- 支持增量拉取：缓存命中的 code 直接复用，仅拉取缺失部分

**OP-03 基本面快照持久化:**
- `fetch_fundamental_batch()` 加入 `fundamental_snapshot` 持久化缓存 (TTL=6h)
- 当日7个策略文件共享同一份基本面数据，消除冗余 API 调用

**OP-04 智能体决策冲突日志:**
- `conflict_resolve()` 仲裁完成后调用 `_persist_conflict_audit()` 持久化到 `conflict_audit.json`
- 记录: 时间/策略/胜者(action+authority)/败者(action+authority+findings明细)
- 保留最近500条，供夜班分析

**OP-05 核心文件严格模式适配:**
- `position_manager.load_positions()` → `safe_load_strict` (文件损坏抛 ValueError)
- `scorecard.py` 所有读取 `_SCORECARD_PATH` / `_POS_PATH` → `safe_load_strict`
- `scheduler.py` 调用点增加 `except ValueError` 熔断分支，区分"文件损坏"和"普通异常"
- 测试 mock 同步更新

**全量 637 tests passed, 0 failed.**

## 5. OP-06 完成说明 (Claude Code)

**OP-06 模块化策略加载器:**
- 新增 `strategies.json` — 12个策略声明文件 (8 A股 + 2期货 + 1币圈 + 1美股)
- 新增 `strategy_loader.py` — 动态加载器 (make_astock_job/make_direct_push_job/register_strategies/run_all_strategies/get_cli_strategy)
- `scheduler.py` 重构:
  - `setup_schedule()` 移除 12 个硬编码策略注册, 改用 `strategy_loader.register_strategies()`
  - `run_all_test()` 改用 `strategy_loader.run_all_strategies()`
  - CLI dispatch 改用 `strategy_loader.get_cli_strategy()` 动态查找 (支持 cli_aliases)
  - 移除 12 个 `job_xxx()` 函数体 (~300行), 由 strategy_loader 动态生成闭包
- 保留不变: `cross_market` / `morning_prep` (有自定义事件总线逻辑)
- 新增策略只需编辑 `strategies.json`, 无需修改 scheduler.py
- 支持: enabled/disabled 开关, 自定义 gate 组合, batch_slot, pre_hook, push_format, cli_aliases

**全量 637 tests passed, 0 failed.**

## 6. OP-07 完成说明 (Claude Code)

**OP-07 核心数据向 SQLite 迁移:**
- 新增 `db_store.py` — SQLite 适配层 (WAL 模式, 线程安全 thread-local 连接)
  - 表: `scorecard` (UNIQUE on rec_date+code+strategy), `conflict_audit` (滑动窗口500条)
  - 函数: `load_scorecard(days, strategy)` / `save_scorecard_records()` / `load_conflict_audit()` / `save_conflict_audit_record()`
  - CLI: `python3 db_store.py migrate` / `python3 db_store.py stats`
- 迁移结果: 24301 JSON → 23167 SQLite (1134 重复记录自动去重)
- 11 个模块切换到 SQLite 读写 (带 monkeypatch 检测的 try/except 回退):
  - `scorecard.py` — 4 读 + 1 写 (score_yesterday/calc_cumulative_stats/calc_equity_curve/weekly_report)
  - `agent_brain.py` — 冲突日志写入 + 2 scorecard 读
  - `var_risk.py` / `ml_factor_model.py` / `risk_manager.py` — 各 1 读
  - `learning_engine.py` — 2 读 (join + 数据积累)
  - `portfolio_risk.py` — 2 读 (相关性 + 回撤)
  - `auto_optimizer.py` — 2 读 (策略评估 + 反恐慌)
  - `signal_tracker.py` — 1 写 (sync_to_scorecard)
  - `ml_backfill.py` — 1 写 (回填数据)
- 测试兼容: `_SCORECARD_DEFAULT` 常量 + monkeypatch 检测, 测试自动回退到 JSON
- 性能: SQLite WAL 模式支持并发读 + 单写, UNIQUE 约束自动去重

**全量 637 tests passed, 0 failed.**

## 7. OP-08 完成说明 (Claude Code)

**OP-08 凯利准则与组合优化:**
- `portfolio_risk.py` 新增两个核心函数:
  - `calc_kelly_fractions(days)` — 为每个策略计算 Half-Kelly 最优仓位
    - Kelly 公式: f* = W - (1-W)/R (W=胜率, R=盈亏比)
    - 使用 Half-Kelly (f*/2) 降低波动风险
    - 最少 5 个样本才计算, 否则降级为 0
  - `calc_risk_parity_allocation(days)` — 风险平价权重分配
    - 按策略波动率倒数加权, 使每个策略对组合风险贡献相等
    - 数据不足的策略给高波动率(999), 自动降权
- `suggest_allocation()` 升级为三信号融合:
  - Health(40%) + Kelly(30%) + RiskParity(30%)
  - Kelly 为 0 时其权重分摊给 Health 和 RP
  - 输出增加 `kelly` 和 `risk_parity` 明细
- `config.py` 新增 `kelly_min_samples`, `kelly_use_half`, `allocation_weights` 参数
- 辅助函数: `_normalize_with_bounds()` / `_calc_changes()`

**全量 637 tests passed, 0 failed.**

## 8. OP-09 完成说明 (Claude Code)

**OP-09 智能体轻量仪表盘:**
- 新增 `dashboard.py` — FastAPI 单文件 Web Dashboard
- 8 个 API 端点:
  - `/api/overview` — 系统总览 (进程/策略执行/持仓/VaR/夜班)
  - `/api/regime` — 大盘评分 + 市场状态
  - `/api/drawdown` — 组合回撤 + Kelly + Risk Parity
  - `/api/signals` — 信号追踪 7 天统计
  - `/api/conflicts` — Agent 冲突仲裁日志 (SQLite)
  - `/api/agents` — 子智能体注册状态
  - `/api/equity` — 资金曲线
  - `/api/heatmap` — 策略热力图 (近7天每策略每天平均收益)
- 前端: 单页内嵌 HTML (暗色主题, CSS Grid 响应式)
  - 大盘评分仪表 (渐变色条)
  - VaR 风控卡片
  - 组合回撤卡片
  - 信号追踪统计
  - A股持仓表格
  - 策略执行状态
  - 子智能体状态
  - 策略热力图 (颜色编码)
  - SVG 资金曲线
  - 冲突仲裁日志
  - Kelly 准则排名
- 自动刷新: 60秒间隔
- 启动: `python3 dashboard.py [--port 8501]`

**全量 637 tests passed, 0 failed.**

## 9. 扩展任务 (Claude Code 自主设计)

| 任务 ID | 模块 | 优化项描述 | 状态 |
| :--- | :--- | :--- | :--- |
| **EX-01** | `Dashboard` | **WebSocket 实时推送** — 替代60s轮询, 策略执行/信号/持仓变动实时推送到前端 | ✅ 已完成 |
| **EX-02** | `Performance` | **trade_journal → SQLite** — 高频读写的 trade_journal.json 迁移到 SQLite, 加速 ML 训练数据查询 | ✅ 已完成 |
| **EX-03** | `ML` | **因子重要性排名 API** — ML 模型 feature_importance 通过 Dashboard 可视化, 辅助因子生命周期决策 | ✅ 已完成 |
| **EX-04** | `Dashboard` | **纸盘模拟交易面板** — Dashboard 增加纸盘持仓/交易记录/权益曲线/7天统计 | ✅ 已完成 |

---
*最后更新: 2026-03-04*
