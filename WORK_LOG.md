# Claude 工作日志

> 查看命令: `cat WORK_LOG.md`
> 我每完成一步就更新这个文件。断了就看这里，知道干到哪了。

---

## 2026-03-03

### 已完成
- [x] 性能优化: 集合竞价策略 1564s → 预计~300s (4项优化)
  - calc_daily_technicals 改5线程并行 (ThreadPoolExecutor)
  - K线缓存: 技术面拉的K线供筹码模块复用, 消除重复API调用
  - enhance_candidates 三子模块(资金流/龙虎榜/筹码)并行执行
  - news_risk_screen sleep 1.0s→0.3s
  - api_guard 限流 40rpm→60rpm, burst 10→15
- [x] 放量突破策略: 同样改5线程并行 + K线缓存
- [x] watchdog 补全: 新增5个日间策略监控 (事件驱动/低吸/趋势跟踪/缩量整理/板块轮动)
- [x] 纸盘自动对接: run_with_retry 统一接入 on_strategy_picks, 所有策略推荐自动开纸盘仓
- [x] Tushare `days` 参数修复 + enhance_candidates 重新启用 (20s vs 22min)
- [x] 智能体激活: 6/9 子智能体全部激活运行 (3个夜班智能体按计划不日间运行)
- [x] learning_engine 持久化: _persist_learning_state() 写 learning_state.json
- [x] optimization_verifications: 修复 change_date/adopt_date 字段兼容, 清除重复
- [x] 个股诊断智能体: stock_analyzer.py (五维打分: 趋势/动量/量价/位置/资金)
  - CLI: `scheduler.py analyze 002221 [--push] [--journal]`
  - 批量: `scheduler.py analyze 002221,600519`
  - 写入 trade_journal 进闭环验证
  - 注册第10个智能体 stock_analyst
  - 31个单元测试 + 全量 637 passed
- [x] scheduler 重启: PID 5919
- [x] 盘中选股提速 (4项优化, 637 tests passed)
  - get_intraday_pattern: 串行→20线程并行 (集合竞价 ~8min→~2min)
  - calc_daily_technicals: 10线程→20线程
  - _fetch_daily_klines: 10线程→20线程 (低吸回调)
  - mean_reversion 缓存: _fetch_candidates + enhance_candidates 10分钟缓存 (低吸→缩量整理复用, 省~22min)
  - dip_buy pool 50→100, 与 consolidation 共享缓存
- [x] scheduler 重启: PID 29564
- [x] **P0 信号闭环打通** (3个bug, 637 tests passed)
  - guarded_call 传字符串→传函数 (A股收盘价获取修复)
  - 新增 _fetch_futures_close (新浪主力连续, 中文列名适配)
  - verify_outcomes → _sync_to_scorecard 自动同步 (agent_brain/learning_engine数据源)
  - FU燃油 T+1 +9.01% 验证成功, scorecard 首条实盘数据写入
- [x] **P1 趋势跟踪/缩量整理修复**: SCHEDULE_TREND_FOLLOW 10:00→10:05 错开
- [x] scheduler 重启: PID 63312
- [x] **指令3: json_store加固** — safe_load错误日志+safe_load_strict严格模式+safe_save写前校验
- [x] **指令1: api_guard持久化缓存** — DataCache磁盘缓存(TTL≥300s自动持久化, fcntl锁, 跨进程共享)
- [x] **指令2: overnight_strategy全链路并行** — scan_signals/scan_fund_flow/news_risk_screen 全部20线程
- [x] **指令4: agent_brain增量observe** — scorecard增量处理(仅新数据触发重算)+_save_memory仅变化时写入
- [x] 637 tests passed, scheduler 重启: PID 64259

### 待办队列
- [ ] 放量突破 _sina_batch_quote 返回 dict→DataFrame 兼容 (paper_trader._fetch_prices)
- [ ] overnight_strategy 隔夜策略也接入并行优化
- [ ] 系统运行满一周后: 信号追踪报告分析 + 参数首次调优

## 2026-03-02 晚

### 已完成
- [x] 夜班重试: 1→2次, 退避10/30/60s, 代码bug不重试
- [x] 外部看门狗: watchdog.py guard + launchd (每5分钟, 已安装)
- [x] watchdog 测试: 20个, 全部通过
- [x] 信号追踪器: signal_tracker.py 712行 (入库→T+1/T+3/T+5验证→统计)
- [x] 信号追踪测试: 21个, 全部通过
- [x] 信号追踪集成: scheduler 16:05 / agent_brain晚报 / learning_engine反馈 / self_healer
- [x] 信号质量检测器: agent_brain 第10个检测器 (策略退化/信号衰减/整体质量)
- [x] 周报增强: 信号多周期验证 + 策略排行 + 系统健康摘要
- [x] 系统状态面板: `scheduler.py status` 一屏看全貌
- [x] watchdog 误报修复: 夜班策略不再误报"未运行"

---

*最后更新: 2026-03-03 21:50*
