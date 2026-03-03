# 量化多因子系统优化协同协议 v1.0

## 1. 角色定义 (Roles)
*   **Gemini CLI (架构师/审核员):** 负责全局代码审计、性能瓶颈识别、优化方案设计及最终代码合规性验收。**原则：禁止直接修改代码，仅通过指令引导。**
*   **Claude Code (资深开发工程师):** 负责根据设计方案进行代码重构、单元测试编写、运行验证。**原则：每完成一个子项必须更新此文档的状态，并确保 `pytest` 通过。**

## 2. 核心优化任务清单 (Roadmap)

| 任务 ID | 模块 | 优化项描述 | 设计方案 (Gemini) | 状态 | 审核人 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OP-01** | `Infrastructure` | **全局 API 调用归一化** | 移除所有策略文件（如 `intraday_strategy.py`, `trend_sector_strategy.py`）中的私有 `_retry` 函数，统一注入并使用 `api_guard.guarded_call`。要求：确保限流和断路器逻辑全局生效。 | 🔄 进行中 | Gemini |
| **OP-02** | `Strategy` | **均值回归策略并行化** | 将 `mean_reversion_strategy.py` 中的 `_fetch_daily_klines` 扫描逻辑由串行改为 20 线程并行，并接入持久化缓存（key: `mr_daily_klines`）。 | ⏳ 待开始 | Gemini |
| **OP-03** | `Data` | **基本面快照持久化** | 在 `api_guard` 中增加 `fundamental_snapshot` 的专用持久化键值，确保当日所有策略仅拉取一次 A 股全量基本面（ak.stock_yjbb_em）。 | ⏳ 待开始 | Gemini |
| **OP-04** | `Agent` | **智能体决策冲突日志** | 在 `agent_brain.py` 的冲突仲裁逻辑中，增加明细持久化记录，保存“被否决”的策略动作及其原始证据，用于夜班分析。 | ⏳ 待开始 | Gemini |
| **OP-05** | `Safety` | **核心文件严格模式适配** | 将 `scheduler.py` 中涉及 `positions.json` 和 `scorecard.json` 的读取点全面切换为 `safe_load_strict`，增加异常熔断保护。 | ⏳ 待开始 | Gemini |

## 3. 协同工作流 (Workflow)

1.  **指令下达：** Gemini CLI 在 `COLLABORATION.md` 中更新具体任务的设计细节。
2.  **执行任务：** Claude Code 读取任务，将状态改为 `🔄 进行中`，开始修改代码。
3.  **自测验证：** Claude Code 完成修改后，必须运行 `pytest tests/相关测试.py` 并修复所有回归问题。
4.  **提请审核：** Claude Code 将状态改为 `✅ 已完成`，并简述改动点（Input/Output）。
5.  **最终验收：** Gemini CLI 使用 `read_file` 和 `codebase_investigator` 审计代码。若符合预期，将状态改为 `💎 已核准`。

---
*最后更新: 2026-03-03*
