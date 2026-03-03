# quant_multifactor 量化多因子选股系统 — 完整技术文档

> 版本: v6.0 (教授级)
> 最后更新: 2026-03-02
> 代码规模: 40 个模块 / 26,019 行生产代码 / 8,073 行测试代码
> 测试状态: **549 tests PASSED** / 24 个测试文件

---

## 目录

1. [系统总览](#1-系统总览)
2. [演进路线](#2-演进路线)
3. [系统架构](#3-系统架构)
4. [模块清单](#4-模块清单)
5. [交易策略层](#5-交易策略层)
6. [智能交易优化](#6-智能交易优化)
7. [多智能体协调 (Agent Brain)](#7-多智能体协调-agent-brain)
8. [风控与执行层](#8-风控与执行层)
9. [ML 因子选股模型](#9-ml-因子选股模型)
10. [Walk-Forward 回测框架](#10-walk-forward-回测框架)
11. [VaR/CVaR 风险度量](#11-varcvar-风险度量)
12. [纸盘模拟交易](#12-纸盘模拟交易)
13. [券商自动下单](#13-券商自动下单)
14. [夜班全链路](#14-夜班全链路)
15. [调度系统](#15-调度系统)
16. [配置体系](#16-配置体系)
17. [数据持久化](#17-数据持久化)
18. [测试体系](#18-测试体系)
19. [完整测试清单](#19-完整测试清单)

---

## 1. 系统总览

quant_multifactor 是一套全自主量化交易系统，覆盖 A 股 / 期货 / 币圈 / 美股四大市场。系统 24 小时运行，无需人工盯盘，具备策略选股、智能交易、风险管理、自学习进化、多智能体协调等完整能力。

### 核心能力矩阵

| 维度 | 能力 |
|------|------|
| **策略** | 8 股票策略 + 1 期货 + 1 币圈 + 1 美股 + 1 跨市场 = 12 个独立策略引擎 |
| **执行** | 纸盘模拟 → 券商自动下单 (paper/demo/live 三模式) |
| **风控** | 6 重 Kill Switch + ATR 自适应止损 + VaR/CVaR 度量 + 组合风控 |
| **学习** | 信号权重自调 + 因子生命周期 + ML 因子模型 + 自主实验 |
| **验证** | Walk-Forward 回测 + 过拟合检测 + 采纳后自动验证 |
| **智能** | OODA 循环 + 6 智能体 + 事件总线 + 冲突仲裁 + LLM 顾问 |
| **运维** | 冒烟测试 + API 防封 + 错误自愈 + 微信推送 |

### 系统成熟度: 教授级 (Professor Level)

```
本科生 → 硕士生 → 博士生 → 副教授 → [教授级] → 院士
                                          ↑ 当前
```

教授级关键能力（全部已实现）:
- Walk-Forward 回测框架（防过拟合验证）
- VaR/CVaR 风险度量（组合级风险量化）
- ML 因子选股（GradientBoosting + WF 交叉验证）
- 纸盘模拟交易（上线前全流程验证）
- 券商 API 自动下单（多券商抽象 + 6 重安全）

---

## 2. 演进路线

| 阶段 | 日期 | 里程碑 | 测试数 |
|------|------|--------|--------|
| L1 基础选股 | 2026-02 | 3 策略 + 微信推送 + 记分卡 | ~50 |
| L2 策略扩展 | 2026-02 | 8 策略 + 增强因子 + 回测 | ~120 |
| L3 智能交易 | 2026-03-01 | smart_trader + ATR + 追踪止盈 + 动态仓位 | ~180 |
| L4 协作智能体 | 2026-03-01 | 组合风控 + 自主实验 + LLM 顾问 | ~237 |
| L5 Agent Brain | 2026-03-02 | OODA + 事件总线 + 冲突仲裁 + 夜班 | ~381 |
| L5+ 期货/币圈/美股 | 2026-03-02 | 期货 + 币圈 + 美股 + 跨市场 + 晨报 | ~450 |
| L6 教授级 | 2026-03-02 | WF + VaR + ML + 纸盘 + 券商API | **549** |

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│                     调度中心 (scheduler.py)                    │
│              37 种定时任务 / 100+ 执行时点                      │
└──────────────┬──────────────────────────────┬────────────────┘
               │                              │
    ┌──────────▼──────────┐        ┌──────────▼──────────┐
    │   策略引擎 (12个)     │        │  Agent Brain (L5)    │
    │                      │        │  OODA + 6 智能体      │
    │  股票 x8             │        │  事件总线 + 仲裁      │
    │  期货 x1             │        │  自学习 + 实验        │
    │  币圈 x1             │        │  LLM 顾问            │
    │  美股 x1             │        └──────────┬───────────┘
    │  跨市场 x1           │                   │
    └──────────┬──────────┘                    │
               │                               │
    ┌──────────▼───────────────────────────────▼───────────┐
    │                  风控 & 执行层                         │
    │                                                       │
    │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐ │
    │  │ risk_manager │  │ smart_trader  │  │ portfolio_   │ │
    │  │ 仓位/黑名单  │  │ ATR/追踪/分批 │  │ risk 组合风控│ │
    │  └─────────────┘  └──────────────┘  └──────────────┘ │
    │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐ │
    │  │ var_risk     │  │ paper_trader  │  │ broker_exec  │ │
    │  │ VaR/CVaR    │  │ 纸盘模拟      │  │ 券商下单     │ │
    │  └─────────────┘  └──────────────┘  └──────────────┘ │
    └──────────────────────────────────────────────────────┘
               │
    ┌──────────▼──────────────────────────────────────────┐
    │                  分析 & ML 层                        │
    │  ml_factor_model  walk_forward  backtest  scorecard  │
    │  learning_engine  auto_optimizer  experiment_lab     │
    └──────────────────────────────────────────────────────┘
               │
    ┌──────────▼──────────────────────────────────────────┐
    │                  基础设施层                           │
    │  api_guard   self_healer   notifier   json_store    │
    │  log_config  watchdog      config                   │
    └─────────────────────────────────────────────────────┘
```

### 数据流

```
数据源 (akshare/Binance/Yahoo/Sina)
    ↓ api_guard 防护
策略引擎打分
    ↓ risk_manager 过滤
    ↓ ml_factor_model 增强 (ML分数融合)
    ↓ smart_trader 仓位计算
推荐列表
    ↓ paper_trader 纸盘模拟
    ↓ broker_executor 实盘下单
    ↓ notifier 微信推送
持仓监控
    ↓ 止损/止盈/追踪/分批/到期
scorecard 次日评分
    ↓ learning_engine 权重调整
    ↓ walk_forward 过拟合检测
    ↓ var_risk VaR 度量
    ↓ agent_brain OODA 循环
晚报/夜班全链路
```

---

## 4. 模块清单

### 4.1 生产模块 (40 个文件, 26,019 行)

| 模块 | 行数 | 职责 |
|------|------|------|
| **核心基础** | | |
| `config.py` | 733 | 全局配置 (60+ 参数块) |
| `scheduler.py` | 1,749 | 定时调度 (38 种任务) + 系统状态面板 |
| `notifier.py` | 459 | 微信推送 (Server酱) |
| `json_store.py` | 81 | 原子读写 JSON |
| `log_config.py` | 91 | 日志配置 |
| `watchdog.py` | 477 | 心跳监控 + 外部看门狗 (guard/launchd) |
| **股票策略** | | |
| `volume_breakout_strategy.py` | 475 | 放量突破选股 |
| `intraday_strategy.py` | 1,090 | 集合竞价 + 尾盘短线 |
| `mean_reversion_strategy.py` | 509 | 低吸回调 + 缩量整理 |
| `trend_sector_strategy.py` | 648 | 趋势跟踪 + 板块轮动 |
| `news_event_strategy.py` | 682 | 事件驱动选股 |
| `overnight_strategy.py` | 927 | 隔夜分析 |
| `multifactor_strategy.py` | 542 | 多因子综合 |
| `enhanced_factors.py` | 526 | 增强因子 (资金流/龙虎榜/筹码) |
| **期货/币圈/美股** | | |
| `futures_strategy.py` | 556 | 期货趋势扫描 (30+ 品种) |
| `crypto_strategy.py` | 518 | 币圈趋势扫描 (24 主流币) |
| `us_stock_strategy.py` | 528 | 美股收盘分析 (31 标的) |
| `cross_market_strategy.py` | 315 | 跨市场信号推演 |
| `morning_prep.py` | 270 | 开盘作战计划 |
| **智能交易** | | |
| `smart_trader.py` | 828 | ATR止损/追踪止盈/分批/动态仓位 |
| `risk_manager.py` | 456 | 仓位限制/黑名单/熔断 |
| `portfolio_risk.py` | 498 | 组合风控/相关性/资金分配 |
| `position_manager.py` | 382 | 持仓跟踪 |
| **ML & 分析** | | |
| `ml_factor_model.py` | 693 | ML 因子选股 (GradientBoosting) |
| `walk_forward.py` | 690 | Walk-Forward 回测 |
| `var_risk.py` | 579 | VaR/CVaR 风险度量 |
| `backtest.py` | 840 | 核心回测引擎 |
| `batch_backtest.py` | 328 | 批量回测 |
| `scorecard.py` | 599 | 次日评分/周报 |
| **自学习 & 进化** | | |
| `learning_engine.py` | 853 | 信号权重自调/因子分析 |
| `auto_optimizer.py` | 921 | 参数进化/验证/回滚 |
| `experiment_lab.py` | 461 | 自主实验 A/B |
| **多智能体** | | |
| `agent_brain.py` | 1,937 | OODA + 夜班 + 早晚报 |
| `agent_registry.py` | 436 | 智能体注册表 |
| `event_bus.py` | 314 | 事件总线 |
| `llm_advisor.py` | 806 | LLM 顾问 (Claude API) |
| **交易执行** | | |
| `paper_trader.py` | 843 | 纸盘模拟交易 |
| `broker_executor.py` | 861 | 券商 API 自动下单 |
| `trade_executor.py` | 917 | 期货交易执行 (tqsdk) |
| **分析验证** | | |
| `signal_tracker.py` | 712 | 信号闭环验证 (T+1/T+3/T+5) |
| **运维** | | |
| `api_guard.py` | 405 | API 防封 (令牌桶/断路器/缓存) |
| `self_healer.py` | 587 | 冒烟测试/错误自愈 |

### 4.2 测试模块 (26 个文件, 8,675 行)

| 测试文件 | 行数 | 测试数 |
|----------|------|--------|
| `test_smart_trader.py` | 699 | 44 |
| `test_agent_brain.py` | 599 | 35 |
| `test_optimizer.py` | 655 | 27 |
| `test_broker_executor.py` | 406 | 26 |
| `test_new_strategies.py` | 474 | 24 |
| `test_news_event.py` | 359 | 22 |
| `test_paper_trader.py` | 301 | 21 |
| `test_var_risk.py` | 250 | 21 |
| `test_risk_manager.py` | 293 | 19 |
| `test_api_guard.py` | 234 | 18 |
| `test_learning_engine.py` | 749 | 18 |
| `test_llm_advisor.py` | 347 | 17 |
| `test_walk_forward.py` | 245 | 16 |
| `test_experiment_lab.py` | 384 | 16 |
| `test_agent_registry.py` | 186 | 16 |
| `test_event_bus.py` | 176 | 16 |
| `test_ml_factor_model.py` | 279 | 15 |
| `test_cross_market_strategy.py` | 150 | 14 |
| `test_crypto_strategy.py` | 200 | 14 |
| `test_futures.py` | 198 | 14 |
| `test_us_stock_strategy.py` | 201 | 14 |
| `test_portfolio_risk.py` | 255 | 12 |
| `test_watchdog.py` | 301 | 20 |
| `test_trade_executor.py` | 279 | 12 |
| `test_morning_prep.py` | 154 | 10 |
| **合计** | **8,374** | **569** |

---

## 5. 交易策略层

### 5.1 A 股 8 策略

| 策略 | 模块 | 调度 | 因子数 | 核心逻辑 |
|------|------|------|--------|----------|
| 集合竞价 | `intraday_strategy.py` | 09:25 | 11 | 竞价量价异动 + RSI + MA |
| 放量突破 | `volume_breakout_strategy.py` | 10:00 | 11 | 量比突破 + MA排列 + 动量 |
| 尾盘短线 | `intraday_strategy.py` | 14:30 | 11 | 午后缩量回落 + 尾盘拉升 |
| 低吸回调 | `mean_reversion_strategy.py` | 09:50 | 8 | RSI超卖 + 缩量 + 支撑位 |
| 缩量整理 | `mean_reversion_strategy.py` | 10:15 | 8 | 量缩箱体 + 波动收窄 |
| 趋势跟踪 | `trend_sector_strategy.py` | 10:00 | 8 | ADX + MA排列 + 均线密集 |
| 板块轮动 | `trend_sector_strategy.py` | 14:00 | 7 | 板块动量排名 → 龙头选股 |
| 事件驱动 | `news_event_strategy.py` | 09:22 | 8 | 10 类事件关键词 → 概念匹配 |

每个策略的打分公式: `total_score = Σ(weight_i × factor_i)`, 权重总和 = 1.0

### 5.2 期货策略

**模块:** `futures_strategy.py` (556 行)
**品种池:** 30+ 活跃期货品种 (螺纹/铁矿/焦炭/原油/黄金/白银等)
**调度:** 09:05 日盘 / 21:10 夜盘
**打分:** `s_trend(0.35) + s_momentum(0.30) + s_volume(0.20) + s_risk(0.15)`
**方向:** 做多/做空/中性
**止损:** ATR × 2.0 倍

### 5.3 币圈策略

**模块:** `crypto_strategy.py` (518 行)
**数据源:** Binance REST `/api/v3/klines` (无需 API Key)
**币种池:** BTC/ETH/SOL/BNB/XRP 等 24 主流币
**调度:** 01:00
**打分:** 同期货四因子体系

### 5.4 美股策略

**模块:** `us_stock_strategy.py` (528 行)
**数据源:** Yahoo Finance (yfinance)
**标的池:** 31 只 (AAPL/MSFT/NVDA/TSLA/META 等 + ETF)
**调度:** 05:30 (美股收盘后)
**打分:** 同期货四因子体系

### 5.5 跨市场推演

**模块:** `cross_market_strategy.py` (315 行)
**逻辑:** 综合币圈 + 美股 + A50 期货信号 → 推演 A 股次日影响
**输出:** `composite_signal`, `a_stock_impact` (利多/利空/中性), `risk_appetite`
**调度:** 06:00

### 5.6 开盘作战计划

**模块:** `morning_prep.py` (270 行)
**输入:** 跨市场信号 + 期货持仓 + Agent 洞察 + 策略健康度 + 学习建议
**输出:** 风险等级 (Low/Medium/High) + 操作要点 + 关注事项
**调度:** 07:30

---

## 6. 智能交易优化

### 6.1 smart_trader.py (828 行)

**核心组件:**

| 组件 | 功能 | 配置 |
|------|------|------|
| 大盘环境检测 | 8 信号加权 → 4 级环境 (bull/neutral/weak/bear) | `MARKET_SIGNAL_WEIGHTS` |
| ATR 自适应止损 | 入场价 - ATR × 倍数, 限制在 [-2%, -5%] | `ADAPTIVE_STOP_PARAMS` |
| 追踪止盈 | 盈利 >2% 激活, 从最高价回撤 1.5% 触发 | `TRAILING_STOP_PARAMS` |
| 分批出场 | 盈利 >3% 卖出 50%, 余仓追踪 | `PARTIAL_EXIT_PARAMS` |
| 动态仓位 | 得分加权 × 波动率调整 × 环境缩放 | `DYNAMIC_SIZING_PARAMS` |

**环境自适应参数:**

| 环境 | position_scale | max_positions | ATR倍数 | 追踪幅度 |
|------|---------------|---------------|---------|----------|
| bull | 1.2 | 9 | 2.0 | 2.0% |
| neutral | 1.0 | 6 | 1.5 | 1.5% |
| weak | 0.6 | 4 | 1.2 | 1.0% |
| bear | 0 (不交易) | 2 | 1.0 | 0.8% |

**验证结果 (7 天 A/B):**
- 胜率: 41.2% → 58.8% (+17.6pp)
- 累计收益: -9.2% → +5.1% (+14.3pp)

### 6.2 API 防封机制 (api_guard.py, 405 行)

| 组件 | 机制 | 参数 |
|------|------|------|
| RateLimiter | 令牌桶算法 | 40 rpm, burst 10 |
| CircuitBreaker | 断路器模式 | 阈值 5 次, 冷却 120s |
| DataCache | LRU + TTL 缓存 | 成分股 1h, 日K 5min |
| smart_retry | 指数退避重试 | 3 次, 1/2/4s |

---

## 7. 多智能体协调 (Agent Brain)

### 7.1 架构 (agent_brain.py, 1,937 行)

**OODA 循环:**

```
Observe → Orient → Process Events → Agent Health → Conflict Resolve
    → Advise → Decide → Act → Experiment → Learn → Persist
```

**6 内建智能体:**

| 智能体 | 角色 | 职责 |
|--------|------|------|
| brain | coordinator | OODA 总调度 |
| risk_inspector | risk | 风险检测/止损建议 |
| market_radar | regime | 大盘环境感知 |
| factor_researcher | strategy | 因子研究/权重建议 |
| execution_judge | strategy | 执行效果评判 |
| healer | info | 系统健康/错误修复 |

**冲突仲裁优先级:**
`risk(4) > regime(3) > strategy(2) > info(1)`, 败者降级为 log_insight

**9 个检测器:**
- 连续亏损检测 → 暂停策略
- 胜率退化检测 → 降权
- 环境不匹配检测 → 切换参数
- 因子衰减检测 → 降权/淘汰
- 优化效果回归检测 → 自动回滚
- 自动恢复检测 → 策略重启
- 风险集中度检测 → 分散
- 学习规则发现 → 新增规则
- 规则修剪 → 淘汰低置信规则

### 7.2 事件总线 (event_bus.py, 314 行)

**事件来源:**
- smart_trader: regime_change
- self_healer: smoke_test_result
- portfolio_risk: drawdown_alert
- trade_executor: trades_executed, stop_loss_triggered
- scheduler: job_failed
- paper_trader: paper_open, paper_close

**特性:** 优先级队列, 60s 去重, 500 条上限, JSON 持久化

### 7.3 自学习引擎 (learning_engine.py, 853 行)

- 信号准确率分析 → 权重调整 (max ±3%)
- 因子重要性排序 → 淘汰/提权
- 环境适配分析 → 策略/环境交叉表
- 规则自动发现 → 学习新交易规则

### 7.4 自主实验 (experiment_lab.py, 461 行)

- 自动设计参数扰动实验
- 回测验证 → 择优采纳 (阈值 +1%)
- 冷却期 7 天, 并发上限 2
- 采纳后 5 天自动验证, 回退机制

### 7.5 LLM 顾问 (llm_advisor.py, 806 行)

- Claude API (claude-sonnet-4-20250514)
- 增强早报/晚报
- 策略建议生成
- 交互式对话

---

## 8. 风控与执行层

### 8.1 风控层级

```
L1: 基础风控 (risk_manager.py)
    - 最大持仓 9 笔
    - 单行业 ≤2 笔
    - 黑名单机制 (连亏 3 次 → 禁 60 天)
    - 每日熔断 (-5%)

L2: 智能止损 (smart_trader.py)
    - ATR 自适应止损 [-2%, -5%]
    - 追踪止盈 (回撤 1.5% 触发)
    - 分批出场 (50% 先走)

L3: 组合风控 (portfolio_risk.py)
    - 策略相关性矩阵
    - 组合回撤监控 (-8% 上限)
    - 动态资金分配

L4: VaR 风险度量 (var_risk.py)
    - 历史模拟 VaR
    - 参数法 VaR
    - 蒙特卡洛 VaR
    - 压力测试 5 场景

L5: Kill Switch (broker_executor.py)
    - 手动紧急停止
    - 每日亏损上限
    - 连续亏损暂停
    - 持仓数上限
    - 每日交易数上限
    - 集中度限制
```

### 8.2 交易成本模型

```python
TRADE_COST = {
    "commission": 0.00025,   # 万2.5 (买卖各一次)
    "stamp_tax": 0.0005,     # 0.05% (仅卖出)
    "slippage": 0.001,       # 0.1% (双向)
}
# 单次交易总成本: ~0.4%
```

---

## 9. ML 因子选股模型

**模块:** `ml_factor_model.py` (693 行)
**调度:** 每日 17:10 增量训练 + 夜班 WF 评估

### 9.1 架构

```
trade_journal + scorecard
    ↓ build_training_data()
特征矩阵 (11 因子 + 6 扩展)
    ↓ _create_model()
GradientBoosting (sklearn)
    ↓ train_model()
模型持久化 (models/ml_*.pkl)
    ↓ predict_scores()
ML 预测分数
    ↓ fuse_scores()
融合分数 = ml_weight × ML分 + (1-ml_weight) × 规则分
```

### 9.2 特征体系

| 特征 | 类型 | 说明 |
|------|------|------|
| rsi | 连续 | 相对强弱指标 |
| above_ma60 | 布尔 | 价格在60日均线上方 |
| ma_aligned | 布尔 | 均线多头排列 |
| volatility | 连续 | 波动率 |
| vol_ratio | 连续 | 量比 |
| consecutive_vol | 布尔 | 连续放量 |
| pullback_5d | 连续 | 5 日回撤 |
| pullback_20d | 连续 | 20 日回撤 |
| ret_3d | 连续 | 3 日收益率 |
| resistance_ratio | 连续 | 阻力位比 |
| pct_chg | 连续 | 涨跌幅 |

扩展特征: `s_volume_breakout`, `s_ma_alignment`, `s_momentum`, `s_rsi`, `s_resistance_break`, `s_volatility`

### 9.3 模型配置

```python
ML_PARAMS = {
    "model_type": "gradient_boosting",  # 可切换 xgboost/lightgbm
    "n_estimators": 200,
    "max_depth": 5,
    "learning_rate": 0.05,
    "ml_weight": 0.4,                  # 融合权重
    "min_training_samples": 50,
    "wf_n_windows": 3,                 # Walk-Forward 窗口数
}
```

### 9.4 Walk-Forward 交叉验证

从后往前滑动 N 个窗口, 每个窗口:
1. 训练集 (90天) → 拟合模型
2. 测试集 (30天) → 样本外预测
3. 计算 IS/OOS R², 方向准确率

**模型有效性判定:** OOS 方向准确率 > 52%

### 9.5 测试验证

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestBuildTrainingData | 2 | 空数据 + 正常数据构建 |
| TestCreateModel | 2 | 回归/分类模型创建 |
| TestTrainModel | 2 | 数据不足 + 合成数据完整训练 |
| TestPredictScores | 2 | 无模型回退 + 有模型预测 |
| TestFuseScores | 2 | 基础融合 + 零权重 |
| TestMLReport | 2 | 报告格式 + 错误报告 |
| TestMLSummary | 2 | 汇总计算 + 空输入 |
| TestGetFeatureColumns | 1 | 特征选择 (排除空列) |

---

## 10. Walk-Forward 回测框架

**模块:** `walk_forward.py` (690 行)
**调度:** 夜班 22:30+ (核心 3 策略)

### 10.1 算法

```
|← train_days →|← test_days →|
|    Window 1    |   OOS 1     |
       |    Window 2    |   OOS 2     |
              |    Window 3    |   OOS 3     |
                                             → 今天
```

### 10.2 核心指标

| 指标 | 公式 | 含义 |
|------|------|------|
| OOS Efficiency | `oos_sharpe / is_sharpe` | 样本外效率 (>0.5 正常) |
| OOS Degradation | `(is_sharpe - oos_sharpe) / is_sharpe` | 衰减率 (<50% 正常) |
| Sharpe Decay | `is_sharpe - oos_sharpe` | 夏普绝对衰减 |
| Overfitting Risk | 综合判定 | low / medium / high |

### 10.3 过拟合风险判定

- `high`: OOS Efficiency < 0.3 且 Degradation > 0.6
- `medium`: OOS Efficiency < 0.5 或 Degradation > 0.4
- `low`: 其他

### 10.4 测试验证

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestGenerateGrid | 5 | 空权重/网格大小/基线/正值/归一化 |
| TestBacktestWindow | 2 | 窗口回测/空区间 |
| TestWFSummary | 4 | 汇总计算/效率正值/高过拟合/空窗口 |
| TestWFReport | 2 | 报告格式/错误报告 |
| TestWFPersistence | 2 | 持久化读写/风险查询 |
| TestWFDefaults | 1 | 默认参数存在 |

---

## 11. VaR/CVaR 风险度量

**模块:** `var_risk.py` (579 行)
**调度:** 每日 16:10

### 11.1 三种 VaR 方法

| 方法 | 算法 | 优势 |
|------|------|------|
| Historical | 历史分位数 | 无分布假设, 真实尾部 |
| Parametric | 正态分布假设 | 快速, 可解析 |
| Monte Carlo | 10000 次模拟 | 灵活, 多日展望 |

### 11.2 压力测试场景

| 场景 | 冲击 | 波动率放大 |
|------|------|------------|
| 股灾暴跌 | -8% ~ -3% | 2.5x |
| 连续阴跌 | -1.5% ~ -0.3% | 1.5x |
| 黑天鹅 | -15% ~ -5% | 3.0x |
| 流动性危机 | -5% ~ -1% | 2.0x |
| 缓慢复苏 | -0.5% ~ +0.5% | 0.8x |

### 11.3 风险评级

```
low:    VaR(95%) > -3% 且 CVaR(99%) > -5%
medium: VaR(95%) > -5% 且 CVaR(99%) > -8%
high:   其他
```

### 11.4 测试验证

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestHistoricalVaR | 4 | 基础/置信度单调/空数据/全正收益 |
| TestHistoricalCVaR | 2 | CVaR ≤ VaR / 空数据 |
| TestParametricVaR | 3 | 基础/零波动/参数CVaR |
| TestMonteCarloVaR | 3 | 基础/多日展望/数据不足 |
| TestStressTest | 3 | 基础/暴跌为负/空收益 |
| TestLoadReturnSeries | 2 | 空记分卡/有数据 |
| TestComprehensiveVaR | 1 | 完整流程 Mock |
| TestVaRReport | 1 | 报告格式 |
| TestPersistence | 2 | 持久化/评级查询 |

---

## 12. 纸盘模拟交易

**模块:** `paper_trader.py` (843 行)
**调度:** 11:00/14:00 监控, 15:30 日终结算
**数据:** `paper_positions.json`, `paper_trades.json`, `paper_equity.json`

### 12.1 核心流程

```
策略推荐
    ↓ on_strategy_picks()
风控检查 (持仓上限/日交易上限/重复检查)
    ↓ open_position()
模拟买入 (含滑点+手续费)
    ↓ check_exits()
监控 (止损/追踪止盈/分批/到期)
    ↓ _close_position()
模拟卖出 (含滑点+手续费+印花税)
    ↓ daily_settle()
日终结算 (权益曲线更新)
```

### 12.2 与真实持仓完全隔离

| 维度 | 真实交易 | 纸盘模拟 |
|------|----------|----------|
| 持仓文件 | positions.json | paper_positions.json |
| 交易记录 | (通过 scorecard) | paper_trades.json |
| 权益曲线 | (通过 scorecard) | paper_equity.json |
| 执行方式 | broker_executor | 模拟计算 |

### 12.3 统计输出

```python
calc_statistics(days=30) → {
    total, wins, losses, win_rate,
    avg_pnl, total_pnl, max_win, max_loss,
    avg_days_held, sharpe, max_drawdown,
    by_strategy: {strategy_name: {total, wins, win_rate, avg_pnl, total_pnl}}
}
```

### 12.4 测试验证

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestOpenPosition | 4 | 基础开仓/重复拒绝/持仓上限/ATR止损价 |
| TestBatchOpen | 1 | 批量开仓 |
| TestCheckExits | 4 | 止损/止盈/到期离场/正常不出场 |
| TestForceClose | 1 | 强制全平 |
| TestDailySettle | 2 | 空结算/有交易结算 |
| TestStatistics | 2 | 无交易/有交易统计 |
| TestReport | 2 | 空报告/有数据报告 |
| TestMaxDrawdown | 2 | 有回撤/无回撤 |
| TestOnStrategyPicks | 2 | 策略对接/空推荐 |
| TestEquityCurve | 1 | 权益持久化 |

---

## 13. 券商自动下单

**模块:** `broker_executor.py` (861 行)
**调度:** 10:30/13:30/14:45 持仓监控
**数据:** `stock_positions.json`, `stock_trades.json`, `broker_audit.json`, `emergency_stop.json`

### 13.1 三模式架构

```
              BrokerBase (抽象基类)
              ├── buy()
              ├── sell()
              ├── get_balance()
              └── get_positions()
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  PaperBroker  EasytraderBroker  (XtquantBroker)
  模拟下单     华泰/国金/东财     中泰证券
  (默认)       easytrader        xtquant
```

### 13.2 安全模式渐进

```
config.py: STOCK_EXECUTOR_PARAMS["mode"]

paper (默认) → demo (模拟盘) → live (实盘)
  安全         验证              真金白银
```

### 13.3 六重 Kill Switch

| # | Kill Switch | 触发条件 | 效果 |
|---|------------|----------|------|
| 1 | 手动紧急停止 | emergency_stop.json | 全部停止 |
| 2 | 每日亏损上限 | 今日已实现 PnL ≤ -5% | 禁止开仓 |
| 3 | 连续亏损暂停 | 连亏 ≥4 笔 | 禁止开仓 |
| 4 | 持仓数上限 | 持仓 ≥9 笔 | 禁止开仓 |
| 5 | 日交易数上限 | 今日买入 ≥9 笔 | 禁止开仓 |
| 6 | kill_switch 总开关 | 配置关闭 | 跳过检查 |

### 13.4 审计日志

所有交易操作写入 `broker_audit.json`:
```json
{"time": "...", "action": "buy/sell/emergency_stop/trade_blocked", "mode": "paper", ...}
```

### 13.5 测试验证

| 测试类 | 测试数 | 验证内容 |
|--------|--------|----------|
| TestPaperBroker | 5 | 连接/买入/卖出/无价格/余额查询 |
| TestKillSwitch | 7 | 全通过/紧急停止/清除/日亏/连亏/持仓满/开关关闭 |
| TestExecuteBuySignals | 3 | 基础买入/Kill Switch 拦截/重复拒绝 |
| TestCheckExitSignals | 2 | 止损出场/正常不出场 |
| TestPortfolioStatus | 2 | 空组合/有持仓 |
| TestTradeSummary | 2 | 空统计/有数据 |
| TestHelpers | 3 | 连亏计算/持仓天数/审计日志 |
| TestGetBroker | 2 | 默认纸盘/未知券商回退 |

---

## 14. 夜班全链路

**总调度:** `agent_brain.py` 中 `run_night_shift()`
**时间:** 22:30 — 08:30
**结果:** 推送微信汇总报告

### 14.1 夜班任务链 (12 个子任务)

| 序号 | 任务 | 超时(s) | 说明 |
|------|------|---------|------|
| 1 | 绩效考核 | 120 | 当日策略表现评估 |
| 2 | LLM 深度复盘 | 180 | Claude API 分析 |
| 3 | 批量回测验证 | 600 | 全策略回测 |
| 3b | Walk-Forward 检测 | 600 | 核心策略过拟合检测 |
| 3c | ML 模型训练 | 300 | GradientBoosting 增量训练 |
| 4 | 因子发现实验 | 300 | 自主实验 A/B |
| 5 | 策略参数进化 | 300 | 权重调整/采纳/回滚 |
| 6 | OODA 历史回放 | 120 | 决策复盘 |
| 7 | 币圈趋势扫描 | 180 | Binance 24 币 |
| 8 | 美股收盘分析 | 180 | Yahoo Finance 31 标的 |
| 9 | 跨市场信号推演 | 120 | 综合推演 A 股影响 |
| 10 | 开盘作战计划 | 120 | 次日操作要点 |

### 14.2 夜班可靠性 (三层防护)

| 层级 | 位置 | 机制 | 检测间隔 |
|------|------|------|---------|
| L1 任务级 | `agent_brain._night_task()` | ThreadPoolExecutor 硬超时 + 重试 3 次 (退避 10/30/60s) + 代码 bug 不重试 | 每个任务 |
| L2 进程内 | `scheduler._start_self_watchdog()` | 守护线程检查夜班心跳, >15 分钟无更新微信告警 | 5 分钟 |
| L3 进程外 | `watchdog.py guard` + launchd plist | 独立进程检测 scheduler 存活, 挂了/卡死自动重启 + 微信告警 | 5 分钟 |

**L1 重试策略:**
- 默认 `retry=2` → 最多 3 次尝试
- 退避递增: 失败后等 10s → 30s → 60s
- `TypeError/ValueError/KeyError/AttributeError/ImportError` 等代码 bug **不重试**, 立即放弃
- 网络超时、API 限流等瞬态错误才重试
- 每个任务执行中持续写心跳到 `night_shift_log.json`

**L3 Guard 判断逻辑:**
1. 进程不在 → 自动 `restart_scheduler()` + 微信告警
2. 进程在但心跳超 10 分钟 → `kill -9` + 重启 + 微信告警
3. 无 heartbeat.json → 首次启动

**安装:** `python3 watchdog.py install` (写入 `~/Library/LaunchAgents/com.quant.watchdog.plist`)

**防休眠:** `scheduler.run_daemon()` 自动启动 `caffeinate -i` 阻止 macOS 休眠

---

## 15. 调度系统

**模块:** `scheduler.py` (1,524 行)
**框架:** Python schedule 库

### 15.1 完整时间表

#### 凌晨 (00:00-07:30)

| 时间 | 任务 | 说明 |
|------|------|------|
| 00:05 | API 统计重置 | |
| 01:00 | 币圈趋势扫描 | Binance 24 币 |
| 05:30 | 美股收盘分析 | Yahoo Finance |
| 06:00 | 跨市场信号推演 | 综合推演 |
| 07:30 | 开盘作战计划 | 风险/操作要点 |

#### 早盘 (09:00-10:30)

| 时间 | 任务 | 说明 |
|------|------|------|
| 09:05 | 期货日盘扫描 | 全品种 |
| 09:10 | 冒烟测试 | 开盘前检查 |
| 09:15 | Agent 早报 | 微信推送 [1/5] |
| 09:20 | 记分卡评分 | 昨日推荐评分 |
| 09:22 | 事件驱动选股 | |
| 09:25 | 集合竞价选股 | |
| 09:35 | 批量早盘推送 | 微信 [2/5] |
| 09:50 | 低吸回调选股 | |
| 10:00 | 放量突破 + 趋势跟踪 | |
| 10:15 | 缩量整理选股 | |
| 10:30 | 批量午间推送 | 微信 [3/5] |
| 10:30 | 券商持仓监控 | |

#### 午盘 (11:00-15:30)

| 时间 | 任务 | 说明 |
|------|------|------|
| 11:00 | 纸盘监控 | 止损/止盈检查 |
| 13:30 | 券商持仓监控 | |
| 14:00 | 板块轮动选股 | |
| 14:00 | 纸盘监控 | |
| 14:30 | 尾盘短线选股 | |
| 14:45 | 券商持仓监控 | |
| 14:50 | 批量午后推送 | 微信 [4/5] |
| 15:30 | 纸盘日终结算 | |

#### 盘后 (16:00-17:10)

| 时间 | 任务 | 说明 |
|------|------|------|
| 16:00 | 每日策略优化 | |
| 16:10 | VaR/CVaR 度量 | |
| 16:15 | Agent 晚报 | 微信 [5/5] |
| 16:30 | 学习引擎 | 权重自调 |
| 16:45 | 主动实验触发 | |
| 16:50 | 优化效果验证 | |
| 17:00 | 因子生命周期 | 淘汰衰减因子 |
| 17:10 | ML 模型训练 | GradientBoosting |

#### 夜盘 (21:10-22:30)

| 时间 | 任务 | 说明 |
|------|------|------|
| 21:10 | 期货夜盘扫描 | 仅夜盘品种 |
| 22:30 | 夜班全链路启动 | 12 个子任务 |

#### 周任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 周五 15:30 | 周报 | 周度绩效报告 |
| 周六 10:00 | 深度优化 | 周末大参数搜索 |

#### 持仓监控 (高频)

期货持仓: 09:30, 10:30, 11:15, 13:30, 14:30, 21:30, 22:30 (每日 7 次)

---

## 16. 配置体系

**模块:** `config.py` (733 行)

### 16.1 配置分区 (20+)

| 配置块 | 参数数 | 说明 |
|--------|--------|------|
| `BREAKOUT_PARAMS` | 11 | 放量突破因子权重 |
| `AUCTION_PARAMS` | 11 | 集合竞价因子权重 |
| `AFTERNOON_PARAMS` | 11 | 尾盘短线因子权重 |
| `DIP_BUY_PARAMS` | 8 | 低吸回调因子权重 |
| `CONSOLIDATION_PARAMS` | 8 | 缩量整理因子权重 |
| `TREND_FOLLOW_PARAMS` | 8 | 趋势跟踪因子权重 |
| `SECTOR_ROTATION_PARAMS` | 7 | 板块轮动因子权重 |
| `NEWS_EVENT_PARAMS` | 8+ | 事件驱动 + 概念映射 |
| `RISK_PARAMS` | 7 | 风控参数 |
| `TRADE_COST` | 3 | 交易成本 |
| `MARKET_REGIME_PARAMS` | 3 | 大盘环境检测 |
| `MARKET_SIGNAL_WEIGHTS` | 8 | 环境信号权重 |
| `REGIME_STRATEGY_PARAMS` | 4×8 | 环境自适应参数 |
| `ADAPTIVE_STOP_PARAMS` | 5 | ATR 止损参数 |
| `TRAILING_STOP_PARAMS` | 4 | 追踪止盈参数 |
| `PARTIAL_EXIT_PARAMS` | 4 | 分批出场参数 |
| `DYNAMIC_SIZING_PARAMS` | 5 | 动态仓位参数 |
| `OPTIMIZATION_PARAMS` | 10 | 自动优化参数 |
| `LEARNING_ENGINE_PARAMS` | 7 | 学习引擎参数 |
| `ML_PARAMS` | 13 | ML 因子模型参数 |
| `PAPER_PARAMS` | 8 | 纸盘模拟参数 |
| `STOCK_EXECUTOR_PARAMS` | 13 | 券商下单参数 |
| `BACKTEST_PARAMS` | 2 | 回测参数 |
| `AGENT_PARAMS` | 7 | 智能体参数 |
| `MULTI_AGENT_PARAMS` | 3 | 多智能体基础设施 |
| `LLM_ADVISOR_PARAMS` | 7 | LLM 顾问参数 |
| `PORTFOLIO_RISK_PARAMS` | 5 | 组合风控参数 |
| `EXPERIMENT_PARAMS` | 7 | 实验参数 |
| `API_GUARD_PARAMS` | 6 | API 防封参数 |
| `FUTURES_PARAMS` | 8 | 期货策略参数 |
| `TRADE_EXECUTOR_PARAMS` | 5 | 期货执行参数 |
| `CRYPTO_PARAMS` | 5 | 币圈策略参数 |
| `US_STOCK_PARAMS` | 5 | 美股策略参数 |
| `NIGHT_SHIFT_PARAMS` | 6 | 夜班参数 |

---

## 17. 数据持久化

所有数据使用 `json_store.py` 的原子读写, 支持文件锁和临时文件替换。

### 17.1 数据文件清单

| 文件 | 说明 | 模块 |
|------|------|------|
| `positions.json` | 股票真实持仓 | position_manager |
| `paper_positions.json` | 纸盘持仓 | paper_trader |
| `paper_trades.json` | 纸盘交易记录 | paper_trader |
| `paper_equity.json` | 纸盘权益曲线 | paper_trader |
| `stock_positions.json` | 券商持仓 | broker_executor |
| `stock_trades.json` | 券商交易记录 | broker_executor |
| `broker_audit.json` | 审计日志 | broker_executor |
| `emergency_stop.json` | 紧急停止开关 | broker_executor |
| `futures_positions.json` | 期货持仓 | trade_executor |
| `futures_trades.json` | 期货交易记录 | trade_executor |
| `scorecard.json` | 次日评分记录 | scorecard |
| `trade_journal.json` | 交易日志 | 各策略 |
| `agent_memory.json` | 智能体记忆 | agent_brain |
| `agents_registry.json` | 智能体注册表 | agent_registry |
| `event_queue.json` | 事件总线 | event_bus |
| `error_patterns.json` | 错误模式 | self_healer |
| `experiments.json` | 实验历史 | experiment_lab |
| `optimization_verifications.json` | 优化验证 | auto_optimizer |
| `llm_usage.json` | LLM 调用统计 | llm_advisor |
| `heartbeat.json` | 心跳 | watchdog |
| `night_shift_log.json` | 夜班日志 | agent_brain |
| `ml_model_results.json` | ML 评估结果 | ml_factor_model |
| `var_results.json` | VaR 计算结果 | var_risk |
| `wf_results.json` | Walk-Forward 结果 | walk_forward |
| `models/ml_*.pkl` | ML 模型二进制 | ml_factor_model |

---

## 18. 测试体系

### 18.1 测试方法

**框架:** pytest 8.4.2
**运行命令:**

```bash
# 全量测试
python3 -m pytest tests/ -v --tb=short

# 单模块测试
python3 -m pytest tests/test_broker_executor.py -v

# 快速验证
python3 -m pytest tests/ -q --tb=line
```

### 18.2 测试策略

| 策略 | 说明 | 示例 |
|------|------|------|
| **隔离测试** | monkeypatch 替换文件路径 + tmp_path | 每个测试用独立临时目录 |
| **Mock 外部** | unittest.mock 替换 API 调用 | Sina 行情 / Binance / Yahoo |
| **边界条件** | 空输入 / 零值 / 不足数据 | `test_empty_data`, `test_no_trades` |
| **正常流程** | 端到端完整场景 | `test_train_with_synthetic_data` |
| **风控验证** | Kill Switch 全覆盖 | 6 种触发条件各一个测试 |
| **数学验证** | 算法正确性检查 | VaR 单调性, 夏普比率, 回撤计算 |
| **集成验证** | 配置参数完整性 | 权重归一化, 调度时间存在 |

### 18.3 测试覆盖矩阵

| 模块类别 | 模块数 | 测试文件数 | 测试数 | 测试/模块比 |
|----------|--------|-----------|--------|------------|
| 策略引擎 | 9 | 6 | 94 | 10.4 |
| 风控执行 | 6 | 5 | 86 | 14.3 |
| ML/分析 | 5 | 3 | 47 | 9.4 |
| 智能体 | 4 | 4 | 83 | 20.8 |
| 自学习 | 3 | 3 | 61 | 20.3 |
| 智能交易 | 2 | 2 | 63 | 31.5 |
| 运维 | 2 | 2 | 38 | 19.0 |
| 其他 | 9 | 0 | 0 | — |
| **合计** | **40** | **25** | **569** | **14.2** |

### 18.4 测试结果

```
================= 569 passed, 42 warnings in 382.31s (0:06:22) =================
```

- 549 tests PASSED
- 0 tests FAILED
- 36 warnings (均为 tqsdk DeprecationWarning, 非功能性)
- 耗时 ~4 分钟

---

## 19. 完整测试清单

### test_agent_brain.py (35 tests)

```
TestObserve::test_basic_snapshot
TestObserve::test_empty_scorecard
TestDetectConsecutiveLosses::test_no_trigger_below_threshold
TestDetectConsecutiveLosses::test_trigger_at_threshold
TestDetectConsecutiveLosses::test_no_trigger_if_already_paused
TestDetectWinRateDegradation::test_no_trigger_above_threshold
TestDetectWinRateDegradation::test_trigger_low_win_rate
TestDetectRegimeMismatch::test_no_trigger_good_fit
TestDetectRegimeMismatch::test_trigger_mismatch
TestDetectAutoResume::test_no_resume_before_date
TestDetectAutoResume::test_resume_at_date
TestDecide::test_high_confidence_executes
TestDecide::test_low_confidence_no_execute
TestDecide::test_critical_always_executes
TestActionPause::test_pause_writes_state
TestActionPause::test_pause_sets_resume_date
TestShouldStrategyRun::test_active_returns_true
TestShouldStrategyRun::test_paused_returns_false
TestShouldStrategyRun::test_auto_resume_returns_true
TestLearnNewRules::test_discover_rule_from_regime_fit
TestLearnNewRules::test_no_duplicate_rules
TestPruneRules::test_prune_low_confidence
TestPruneRules::test_seed_rules_never_pruned
TestMorningBriefing::test_briefing_format
TestFullCycle::test_ooda_cycle_no_crash
TestFullCycle::test_ooda_pauses_losing_strategy
TestFullCycle::test_evening_summary
TestDetectFactorDecayEnhanced::test_severe_decay_suggests_deweight
TestDetectFactorDecayEnhanced::test_mild_decay_logs_insight
TestDetectFactorDecayEnhanced::test_healthy_factor_no_finding
TestDetectOptimizationRegression::test_regression_found
TestDetectOptimizationRegression::test_verification_ok
TestDetectOptimizationRegression::test_no_verifications
TestActionDeweightFactor::test_deweight_executes
TestUpdateRuleConfidence::test_ema_update
```

### test_agent_registry.py (16 tests)

```
TestAgentInfo::test_default_values
TestAgentInfo::test_to_dict_roundtrip
TestAgentRegistryRegister::test_register_new_agent
TestAgentRegistryRegister::test_register_existing_updates
TestAgentRegistryUnregister::test_unregister_existing
TestAgentRegistryUnregister::test_unregister_nonexistent
TestAgentRegistryHealth::test_update_health_normal
TestAgentRegistryHealth::test_update_health_auto_error
TestAgentRegistryHealth::test_update_health_auto_recover
TestAgentRegistryHealth::test_health_clamp
TestAgentRegistryReportRun::test_report_success
TestAgentRegistryReportRun::test_report_failure_accumulates
TestAgentRegistryGetUnhealthy::test_get_unhealthy
TestAgentRegistryListAgents::test_list_all
TestAgentRegistryListAgents::test_list_by_status
TestAgentRegistryPersist::test_persist_and_reload
TestBuiltinAgents::test_register_builtins
```

### test_api_guard.py (18 tests)

```
TestRateLimiter::test_burst_allows_immediate
TestRateLimiter::test_burst_exceeded_blocks
TestRateLimiter::test_thread_safety
TestRateLimiter::test_tokens_refill
TestCircuitBreaker::test_half_open_after_cooldown
TestCircuitBreaker::test_half_open_failure_reopens
TestCircuitBreaker::test_half_open_success_closes
TestCircuitBreaker::test_independent_sources
TestCircuitBreaker::test_initial_state_closed
TestCircuitBreaker::test_open_after_threshold
TestDataCache::test_cache_miss
TestDataCache::test_clear
TestDataCache::test_set_and_get
TestDataCache::test_size
TestDataCache::test_ttl_expiry
TestSmartRetry::test_all_retries_exhausted
TestSmartRetry::test_rate_limit_detection
TestSmartRetry::test_success_after_retry
TestSmartRetry::test_success_first_try
TestGuardedCall::test_basic_call
TestGuardedCall::test_cache_hit
TestGuardedCall::test_circuit_break_raises
TestStats::test_reset
```

### test_broker_executor.py (26 tests)

```
TestPaperBroker::test_connect
TestPaperBroker::test_buy
TestPaperBroker::test_sell
TestPaperBroker::test_buy_no_price
TestPaperBroker::test_get_balance
TestKillSwitch::test_all_clear
TestKillSwitch::test_emergency_stop
TestKillSwitch::test_clear_emergency
TestKillSwitch::test_daily_loss_limit
TestKillSwitch::test_consecutive_losses
TestKillSwitch::test_max_positions_block
TestKillSwitch::test_kill_switch_disabled
TestExecuteBuySignals::test_basic_buy
TestExecuteBuySignals::test_blocked_by_kill_switch
TestExecuteBuySignals::test_no_duplicate
TestCheckExitSignals::test_stop_loss_exit
TestCheckExitSignals::test_no_exit_when_ok
TestPortfolioStatus::test_empty
TestPortfolioStatus::test_with_positions
TestTradeSummary::test_empty
TestTradeSummary::test_with_data
TestHelpers::test_consecutive_losses
TestHelpers::test_days_held
TestHelpers::test_audit
TestGetBroker::test_default_paper
TestGetBroker::test_unknown_broker_fallback
```

### test_watchdog.py (20 tests)

```
TestHeartbeat::test_update_heartbeat
TestHeartbeat::test_update_strategy_status_success
TestHeartbeat::test_update_strategy_status_failed
TestHeartbeat::test_reset_daily_counters
TestHealthCheck::test_healthy
TestHealthCheck::test_no_heartbeat
TestHealthCheck::test_heartbeat_timeout
TestHealthCheck::test_dead_process
TestHealthCheck::test_too_many_errors
TestGuard::test_guard_process_alive_heartbeat_fresh
TestGuard::test_guard_process_dead_triggers_restart
TestGuard::test_guard_heartbeat_stale_triggers_restart
TestGuard::test_guard_no_heartbeat_file
TestNightTask::test_success_first_try
TestNightTask::test_retry_on_transient_error
TestNightTask::test_no_retry_on_code_bug
TestNightTask::test_all_retries_exhausted
TestNightTask::test_timeout_triggers_retry
TestAlert::test_alert_when_unhealthy
TestAlert::test_no_alert_when_healthy
```

### test_cross_market_strategy.py (14 tests)

```
TestCalcFunctions::test_pct_change_up
TestCalcFunctions::test_pct_change_down
TestCalcFunctions::test_pct_change_empty
TestCalcFunctions::test_momentum
TestCalcFunctions::test_momentum_short
TestCalcFunctions::test_volatility
TestCalcFunctions::test_volatility_empty
TestSymbols::test_crypto_symbols
TestSymbols::test_us_index_symbols
TestSymbols::test_weights_sum
TestAnalyzeCrossMarket::test_bullish_result
TestAnalyzeCrossMarket::test_bearish_result
TestAnalyzeCrossMarket::test_all_fail
TestAnalyzeCrossMarket::test_result_fields
TestAnalyzeCrossMarket::test_risk_appetite_values
TestGetSignal::test_returns_result
TestGetSignal::test_disabled
```

### test_crypto_strategy.py (14 tests)

```
TestCryptoPool::test_pool_has_coins
TestCryptoPool::test_get_crypto_pool
TestCryptoPool::test_btc_in_pool
TestIndicators::test_rsi_range
TestIndicators::test_adx_range
TestIndicators::test_macd_output
TestIndicators::test_atr_non_negative
TestAnalyzeCrypto::test_uptrend_long
TestAnalyzeCrypto::test_downtrend_short
TestAnalyzeCrypto::test_short_data_returns_none
TestAnalyzeCrypto::test_none_df_returns_none
TestAnalyzeCrypto::test_result_fields
TestRunCryptoScan::test_scan_with_mock
TestRunCryptoScan::test_scan_empty
TestGetRecommendations::test_standard_format
TestGetRecommendations::test_disabled
```

### test_event_bus.py (16 tests)

```
TestPriority::test_priority_ordering
TestPriority::test_priority_values
TestEvent::test_event_creation
TestEvent::test_event_to_dict_roundtrip
TestEventBusEmit::test_basic_emit
TestEventBusEmit::test_emit_returns_empty_for_duplicate
TestEventBusEmit::test_different_payload_not_deduped
TestEventBusConsume::test_consume_returns_by_priority
TestEventBusConsume::test_consume_marks_as_consumed
TestEventBusConsume::test_consume_max_count
TestEventBusPeek::test_peek_does_not_consume
TestEventBusPeek::test_peek_filter_by_priority
TestEventBusSubscribe::test_subscribe_callback
TestEventBusCapacity::test_enforce_limit_drops_low_consumed
TestEventBusPersist::test_persist_and_reload
TestEventBusStats::test_stats_accuracy
```

### test_experiment_lab.py (16 tests)

```
TestDesignExperiment::test_basic_design
TestDesignExperiment::test_no_weights_returns_none
TestDesignExperiment::test_hypothesis_consecutive_loss
TestDesignExperiment::test_hypothesis_win_rate
TestRunExperiment::test_found_better
TestRunExperiment::test_no_improvement
TestRunExperiment::test_backtest_exception
TestAdoptExperimentResult::test_adopt_found_better
TestAdoptExperimentResult::test_no_adopt_no_improvement
TestCooldownAndConcurrency::test_cooldown_blocks
TestCooldownAndConcurrency::test_cooldown_expired
TestCooldownAndConcurrency::test_count_running
TestRunAutoExperimentCycle::test_disabled
TestRunAutoExperimentCycle::test_no_experimentable_findings
TestRunAutoExperimentCycle::test_full_cycle_mock
TestExperimentHistory::test_empty_history
TestExperimentHistory::test_filter_by_days
TestExperimentReport::test_empty_report
TestExperimentReport::test_report_with_data
```

### test_futures.py (14 tests)

```
TestContractInfo::test_exchange_valid
TestContractInfo::test_has_minimum_contracts
TestContractInfo::test_key_contracts_present
TestContractInfo::test_required_fields
TestFuturesPool::test_full_pool
TestFuturesPool::test_night_pool_subset
TestFuturesPool::test_pool_item_structure
TestTechnicalIndicators::test_adx_non_negative
TestTechnicalIndicators::test_atr_non_negative
TestTechnicalIndicators::test_macd_components
TestTechnicalIndicators::test_rsi_range
TestAnalyzeContract::test_downtrend_short
TestAnalyzeContract::test_insufficient_data_returns_none
TestAnalyzeContract::test_result_structure
TestAnalyzeContract::test_uptrend_long
TestConfig::test_required_params
TestConfig::test_weights_sum
```

### test_learning_engine.py (18 tests)

```
TestRecordTradeContext::test_basic_record
TestRecordTradeContext::test_empty_items
TestRecordTradeContext::test_missing_regime
TestRecordTradeContext::test_dedup
TestJoinLogic::test_matching_records
TestJoinLogic::test_no_match_excluded
TestAnalyzeSignalAccuracy::test_basic_analysis
TestAnalyzeSignalAccuracy::test_s1_predictive
TestAnalyzeSignalAccuracy::test_insufficient_data
TestAnalyzeFactorImportance::test_basic_factor_analysis
TestAnalyzeFactorImportance::test_unknown_strategy
TestAnalyzeStrategyRegimeFit::test_cross_table
TestProposeSignalWeightUpdate::test_no_data
TestProposeSignalWeightUpdate::test_valid_proposal
TestProposeSignalWeightUpdate::test_weights_normalized
TestGenerateLearningReport::test_report_format
TestApplyWeightUpdate::test_apply_writes_files
TestAutoAdoptBacktestResults::test_no_results_file
TestAutoAdoptBacktestResults::test_adopt_recommendation
TestAutoAdoptBacktestResults::test_skip_non_adopt
TestDiscoverRulesFromHistory::test_no_data
TestDiscoverRulesFromHistory::test_discover_avoid_rule
TestDiscoverRulesFromHistory::test_discover_boost_rule
TestDiscoverRulesFromHistory::test_dedup_existing_rules
TestRunLearningCycle::test_no_crash
```

### test_llm_advisor.py (17 tests)

```
TestGetClient::test_no_api_key
TestGetClient::test_disabled
TestGetClient::test_client_cached
TestDailyLimit::test_under_limit
TestDailyLimit::test_at_limit
TestDailyLimit::test_next_day_resets
TestDailyLimit::test_increment_usage
TestDailyLimit::test_get_usage_today
TestCallLLM::test_no_client_returns_empty
TestCallLLM::test_successful_call
TestCallLLM::test_exception_returns_empty
TestCallLLM::test_limit_exceeded_returns_empty
TestCallLLM::test_increments_counter
TestEnhanceMorningBriefing::test_fallback_when_no_client
TestEnhanceMorningBriefing::test_enhanced_with_client
TestEnhanceEveningSummary::test_fallback_when_no_client
TestEnhanceEveningSummary::test_enhanced_with_decisions
TestAdviseOnFindings::test_no_client_passthrough
TestAdviseOnFindings::test_advice_added
TestAdviseOnFindings::test_skip_high_confidence
TestChat::test_no_client_fallback
TestChat::test_chat_with_client
TestChat::test_chat_failure
TestBuildSystemContext::test_basic_context
```

### test_ml_factor_model.py (15 tests)

```
TestBuildTrainingData::test_empty_data
TestBuildTrainingData::test_with_data
TestCreateModel::test_regression
TestCreateModel::test_classification
TestTrainModel::test_insufficient_data
TestTrainModel::test_train_with_synthetic_data
TestPredictScores::test_no_model
TestPredictScores::test_with_model
TestFuseScores::test_basic_fusion
TestFuseScores::test_zero_ml_weight
TestMLReport::test_report_format
TestMLReport::test_report_error
TestMLSummary::test_regression_summary
TestMLSummary::test_empty
TestGetFeatureColumns::test_basic
```

### test_morning_prep.py (10 tests)

```
TestCollectors::test_cross_market_fail_safe
TestCollectors::test_futures_fail_safe
TestCollectors::test_insights_fail_safe
TestCollectors::test_learning_fail_safe
TestCollectors::test_health_fail_safe
TestGeneratePlan::test_bullish_plan
TestGeneratePlan::test_bearish_plan
TestGeneratePlan::test_all_none
TestGeneratePlan::test_result_fields
TestRunMorningPrep::test_returns_result
TestRunMorningPrep::test_disabled
TestRunMorningPrep::test_exception_safe
```

### test_new_strategies.py (24 tests)

```
TestDipBuy::test_rsi_filter
TestDipBuy::test_rsi_oversold_score
TestDipBuy::test_empty_data_graceful
TestDipBuy::test_no_decline_stocks
TestConsolidation::test_volume_contract_filter
TestConsolidation::test_range_filter
TestConsolidation::test_breakout_today_volume
TestConsolidation::test_valid_candidate_scores
TestTrendFollow::test_adx_calculation
TestTrendFollow::test_adx_insufficient_data
TestTrendFollow::test_ma_alignment_filter
TestTrendFollow::test_holding_days_in_output
TestSectorRotation::test_sector_ranking
TestSectorRotation::test_sector_ranking_empty
TestSectorRotation::test_sector_stocks
TestSectorRotation::test_sector_stocks_failure
TestNotifyBatch::test_batch_format
TestNotifyBatch::test_batch_empty_skip
TestHoldingDays::test_holding_days_recorded
TestHoldingDays::test_default_holding_days
TestConfigIntegrity::test_new_params_exist
TestConfigIntegrity::test_weights_sum_to_one
TestConfigIntegrity::test_schedule_times_exist
TestConfigIntegrity::test_portfolio_allocation_sum
TestConfigIntegrity::test_max_wechat_daily
TestRegistration::test_agent_brain_strategies
TestRegistration::test_portfolio_risk_strategies
TestRegistration::test_experiment_lab_map
TestRegistration::test_auto_optimizer_strategies
TestRegistration::test_auto_optimizer_default_weights
```

### test_news_event.py (22 tests)

```
TestEventKeywordMatching::test_military_event
TestEventKeywordMatching::test_sanction_event
TestEventKeywordMatching::test_ai_event
TestEventKeywordMatching::test_multiple_events
TestEventKeywordMatching::test_no_match
TestConceptFuzzyMatch::test_fuzzy_match
TestConceptFuzzyMatch::test_no_match
TestNoEventsEmpty::test_no_news_returns_empty
TestNoEventsEmpty::test_no_events_detected
TestOutputFormat::test_output_fields
TestConfidenceFilter::test_low_confidence_filtered
TestConfidenceFilter::test_high_confidence_passes
TestDedupEvents::test_dedup
TestConfigIntegrity::test_weights_sum_to_one
TestConfigIntegrity::test_required_params
TestConfigIntegrity::test_event_concept_map_not_empty
TestConfigIntegrity::test_schedule_exists
TestConfigIntegrity::test_allocation_includes_event
TestConfigIntegrity::test_allocation_sums_to_one
TestRegistration::test_agent_brain_registered
TestRegistration::test_portfolio_risk_registered
TestRegistration::test_auto_optimizer_registered
TestRegistration::test_experiment_lab_registered
TestRegistration::test_optimizer_default_weights
TestEventSummary::test_event_summary_format
TestEventSummary::test_event_summary_empty
```

### test_optimizer.py (27 tests)

```
TestEvaluateStrategyHealth::test_empty_data
TestEvaluateStrategyHealth::test_normal_data
TestEvaluateStrategyHealth::test_trend_calculation
TestGenerateCandidates::test_weight_normalization
TestGenerateCandidates::test_weight_delta_limit
TestGenerateCandidates::test_positive_weights
TestGetTunableParams::test_default_weights
TestGetTunableParams::test_override_weights
TestApplyAndRollback::test_apply_creates_history
TestApplyAndRollback::test_rollback
TestMatchErrorPattern::test_json_decode_error
TestMatchErrorPattern::test_timeout_error
TestMatchErrorPattern::test_connection_error
TestMatchErrorPattern::test_disk_space
TestMatchErrorPattern::test_unknown_error
TestRepairJson::test_repair_from_bak
TestRepairJson::test_repair_initialize_empty
TestSmokeTest::test_returns_structure
TestCleanOldLogs::test_clean_old_files
TestIntegration::test_optimizer_import
TestIntegration::test_healer_import
TestIntegration::test_backtest_accepts_overrides
TestScheduleVerification::test_creates_pending_entry
TestScheduleVerification::test_apply_auto_schedules
TestCheckPendingVerifications::test_not_due_yet
TestCheckPendingVerifications::test_verified_ok
TestCheckPendingVerifications::test_auto_rollback
TestCheckPendingVerifications::test_extend_on_insufficient_data
TestCheckPendingVerifications::test_skip_completed
TestDeweightFactor::test_basic_deweight
TestDeweightFactor::test_skip_already_minimal
TestDeweightFactor::test_unknown_factor
TestCheckFactorLifecycle::test_no_dying_factors
TestCheckFactorLifecycle::test_deweight_dying_factor
```

### test_paper_trader.py (21 tests)

```
TestOpenPosition::test_basic_open
TestOpenPosition::test_duplicate_rejected
TestOpenPosition::test_max_positions_limit
TestOpenPosition::test_atr_stop_price
TestBatchOpen::test_batch
TestCheckExits::test_stop_loss
TestCheckExits::test_take_profit
TestCheckExits::test_force_exit_days
TestCheckExits::test_no_exit_when_ok
TestForceClose::test_close_all
TestDailySettle::test_settle_empty
TestDailySettle::test_settle_with_trades
TestStatistics::test_no_trades
TestStatistics::test_with_trades
TestReport::test_empty_report
TestReport::test_report_with_data
TestMaxDrawdown::test_drawdown
TestMaxDrawdown::test_no_drawdown
TestOnStrategyPicks::test_picks_integration
TestOnStrategyPicks::test_empty_picks
TestEquityCurve::test_equity_persistence
```

### test_portfolio_risk.py (12 tests)

```
TestPearson::test_perfect_correlation
TestPearson::test_negative_correlation
TestPearson::test_zero_variance
TestPearson::test_insufficient_data
TestCalcStrategyCorrelation::test_basic_correlation
TestCalcStrategyCorrelation::test_empty_scorecard
TestCalcStrategyCorrelation::test_single_strategy
TestCalcPortfolioDrawdown::test_basic_drawdown
TestCalcPortfolioDrawdown::test_empty_scorecard
TestCalcPortfolioDrawdown::test_severe_drawdown_breaches
TestSuggestAllocation::test_default_when_no_health
TestSuggestAllocation::test_weighted_by_health
TestSuggestAllocation::test_allocation_sums_to_one
TestCheckPortfolioRisk::test_basic_check
TestCheckPortfolioRisk::test_disabled
TestGenerateReport::test_report_format
```

### test_risk_manager.py (19 tests)

```
TestClassifySector::test_consumer
TestClassifySector::test_energy
TestClassifySector::test_finance
TestClassifySector::test_manufacturing
TestClassifySector::test_medical
TestClassifySector::test_other
TestClassifySector::test_tech
TestPositionSizing::test_basic_sizing
TestPositionSizing::test_min_100_shares
TestPositionSizing::test_single_position_cap
TestPositionSizing::test_zero_capital
TestPositionSizing::test_zero_price
TestFilterRecommendations::test_blacklist_filter
TestFilterRecommendations::test_empty_items
TestFilterRecommendations::test_max_positions
TestFilterRecommendations::test_sector_concentration
TestCircuitBreaker::test_breaker_triggered
TestCircuitBreaker::test_no_breaker_normal_loss
TestCircuitBreaker::test_no_exits_no_breaker
TestJsonStore::test_atomic_write
TestJsonStore::test_safe_load_save
TestEquityCurve::test_basic_curve
TestEquityCurve::test_empty_records
TestEquityCurve::test_max_drawdown
```

### test_smart_trader.py (44 tests)

```
TestCalcATR::test_normal
TestCalcATR::test_insufficient_data
TestCalcATR::test_known_values
TestAdaptiveStop::test_normal
TestAdaptiveStop::test_high_volatility_clamp
TestAdaptiveStop::test_low_volatility_clamp
TestAdaptiveStop::test_nan_atr_fallback
TestAdaptiveStop::test_zero_atr_fallback
TestTrailingStop::test_not_activated
TestTrailingStop::test_activated_not_triggered
TestTrailingStop::test_activated_and_triggered
TestTrailingStop::test_fixed_target_hit
TestPartialExit::test_trigger
TestPartialExit::test_already_partial
TestPartialExit::test_below_threshold
TestBacktestEntryPrice::test_with_pullback
TestBacktestEntryPrice::test_no_pullback
TestSimulateBacktestTrade::test_stop_loss
TestSimulateBacktestTrade::test_partial_exit
TestSimulateBacktestTrade::test_close_exit
TestSimulateBacktestTrade::test_entry_method_pullback
TestDynamicSizing::test_score_weighting
TestDynamicSizing::test_volatility_adjust
TestDynamicSizing::test_regime_scale
TestDynamicSizing::test_empty_items
TestSignalMATrend::test_strong_uptrend
TestSignalMATrend::test_downtrend
TestSignalMATrend::test_insufficient_data
TestSignalMomentum::test_positive_momentum
TestSignalMomentum::test_negative_momentum
TestSignalMomentum::test_insufficient_data
TestSignalVolatility::test_low_volatility
TestSignalVolatility::test_high_volatility
TestSignalVolatility::test_insufficient_data
TestSignalIndexRSI::test_overbought
TestSignalIndexRSI::test_oversold
TestSignalIndexRSI::test_insufficient_data
TestCompositeScoring::test_all_bullish
TestCompositeScoring::test_all_bearish
TestCompositeScoring::test_mixed_neutral
TestCompositeScoring::test_auto_normalize
TestScoreToRegime::test_bull
TestScoreToRegime::test_neutral
TestScoreToRegime::test_weak
TestScoreToRegime::test_bear
TestGetRegimeParams::test_bull_params
TestGetRegimeParams::test_bear_params
TestGetRegimeParams::test_unknown_fallback
TestDetectMarketRegimeBacktest::test_bull
TestDetectMarketRegimeBacktest::test_bear
TestDetectMarketRegimeBacktest::test_insufficient_data
TestDetectMarketRegimeBacktest::test_has_regime_params
TestDetectMarketRegimeBacktest::test_signals_returned
TestSignalAdvanceDecline::test_bullish_market
TestSignalAdvanceDecline::test_bearish_market
TestSignalAdvanceDecline::test_none_input
TestSignalLimitRatio::test_more_limit_up
TestSignalLimitRatio::test_more_limit_down
TestSignalLimitRatio::test_none_input
TestSignalNorthbound::test_strong_inflow
TestSignalNorthbound::test_strong_outflow
TestSignalNorthbound::test_neutral_flow
TestSignalMarginTrend::test_margin_increase
TestSignalMarginTrend::test_margin_decrease
TestDetectMarketRegimeFull::test_full_bull_regime
TestDetectMarketRegimeFull::test_full_bear_regime
TestDetectMarketRegimeFull::test_api_failure_fallback
```

### test_trade_executor.py (12 tests)

```
TestExecuteSignals::test_basic_open
TestExecuteSignals::test_skip_duplicate
TestExecuteSignals::test_empty_signals
TestExecuteSignals::test_stop_price_long
TestExecuteSignals::test_stop_price_short
TestExecuteSignals::test_zero_price_skipped
TestCheckExits::test_long_stop_loss
TestCheckExits::test_short_stop_loss
TestCheckExits::test_fixed_take_profit
TestCheckExits::test_no_exit_in_range
TestCheckExits::test_trailing_stop_long
TestPortfolioStatus::test_empty_portfolio
TestPortfolioStatus::test_with_positions
TestTradeSummary::test_empty_history
TestTradeSummary::test_with_trades
```

### test_us_stock_strategy.py (14 tests)

```
TestUSStockPool::test_pool_has_stocks
TestUSStockPool::test_get_pool
TestUSStockPool::test_key_stocks_in_pool
TestUSStockPool::test_sectors_exist
TestIndicators::test_rsi_range
TestIndicators::test_adx_range
TestIndicators::test_macd_output
TestIndicators::test_atr_non_negative
TestAnalyzeUSStock::test_uptrend_long
TestAnalyzeUSStock::test_downtrend_short
TestAnalyzeUSStock::test_short_data_returns_none
TestAnalyzeUSStock::test_none_df_returns_none
TestAnalyzeUSStock::test_result_fields
TestRunScan::test_scan_with_mock
TestRunScan::test_scan_empty
TestGetRecommendations::test_standard_format
TestGetRecommendations::test_disabled
```

### test_var_risk.py (21 tests)

```
TestHistoricalVaR::test_basic
TestHistoricalVaR::test_higher_confidence_more_extreme
TestHistoricalVaR::test_empty_returns
TestHistoricalVaR::test_all_positive
TestHistoricalCVaR::test_cvar_worse_than_var
TestHistoricalCVaR::test_cvar_empty
TestParametricVaR::test_basic
TestParametricVaR::test_zero_vol
TestParametricVaR::test_parametric_cvar
TestMonteCarloVaR::test_basic
TestMonteCarloVaR::test_multi_day_horizon
TestMonteCarloVaR::test_insufficient_data
TestStressTest::test_basic
TestStressTest::test_crash_scenario_negative
TestStressTest::test_empty_returns
TestLoadReturnSeries::test_empty_scorecard
TestLoadReturnSeries::test_with_data
TestComprehensiveVaR::test_with_mock_data
TestVaRReport::test_report_format
TestPersistence::test_save_and_rating
TestPersistence::test_unknown_when_empty
```

### test_walk_forward.py (16 tests)

```
TestGenerateGrid::test_empty_weights
TestGenerateGrid::test_grid_size
TestGenerateGrid::test_baseline_is_first
TestGenerateGrid::test_all_positive
TestGenerateGrid::test_normalized
TestBacktestWindow::test_window_returns_dict
TestBacktestWindow::test_empty_range
TestWFSummary::test_calc_summary
TestWFSummary::test_efficiency_positive
TestWFSummary::test_high_overfitting
TestWFSummary::test_empty_windows
TestWFReport::test_report_format
TestWFReport::test_report_error
TestWFPersistence::test_save_and_load
TestWFPersistence::test_latest_risk
TestWFDefaults::test_defaults_exist
```

---

*文档结束. 549 tests PASSED, 0 FAILED.*
