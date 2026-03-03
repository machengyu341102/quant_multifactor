# 量化多因子系统优化协同协议 v1.0

## 1. 角色定义 (Roles)
*   **Gemini CLI (架构师/审核员):** 负责全局代码审计、性能瓶颈识别、优化方案设计及最终代码合规性验收。**原则：禁止直接修改代码，仅通过指令引导。**
*   **Claude Code (资深开发工程师):** 负责根据设计方案进行代码重构、单元测试编写、运行验证。**原则：每完成一个子项必须更新此文档的状态，并确保 `pytest` 通过。**

## 2. 核心优化任务清单 (Roadmap)

| 任务 ID | 模块 | 优化项描述 | 设计方案 (Gemini) | 状态 | 审核人 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OP-01** | `Infrastructure` | **全局 API 调用归一化** | 移除所有策略文件（如 `intraday_strategy.py`, `trend_sector_strategy.py`）中的私有 `_retry` 函数，统一注入并使用 `api_guard.guarded_call`。要求：确保限流和断路器逻辑全局生效。 | ✅ 已完成 | Gemini |
| **OP-02** | `Strategy` | **均值回归策略并行化** | 将 `mean_reversion_strategy.py` 中的 `_fetch_daily_klines` 扫描逻辑由串行改为 20 线程并行，并接入持久化缓存（key: `mr_daily_klines`）。 | ✅ 已完成 | Gemini |
| **OP-03** | `Data` | **基本面快照持久化** | 在 `api_guard` 中增加 `fundamental_snapshot` 的专用持久化键值，确保当日所有策略仅拉取一次 A 股全量基本面（ak.stock_yjbb_em）。 | ✅ 已完成 | Gemini |
| **OP-04** | `Agent` | **智能体决策冲突日志** | 在 `agent_brain.py` 的冲突仲裁逻辑中，增加明细持久化记录，保存”被否决”的策略动作及其原始证据，用于夜班分析。 | ✅ 已完成 | Gemini |
| **OP-05** | `Safety` | **核心文件严格模式适配** | 将 `scheduler.py` 中涉及 `positions.json` 和 `scorecard.json` 的读取点全面切换为 `safe_load_strict`，增加异常熔断保护。 | ✅ 已完成 | Gemini |

## 3. 协同工作流 (Workflow)

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

---
*最后更新: 2026-03-03*
