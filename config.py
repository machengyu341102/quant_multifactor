"""
集中配置文件
============
微信推送、调度时间、策略参数、交易日历
"""

# ================================================================
#  微信 Server酱 推送配置
# ================================================================
# 请在 https://sct.ftqq.com/ 注册获取 SendKey
SERVERCHAN_SENDKEY = "SCT317368TiF9totWqQwnLSVyyVIfZpmB6"

# ================================================================
#  调度时间 (HH:MM 格式)
# ================================================================
SCHEDULE_NEWS_EVENT    = "09:22"   # 事件驱动策略 (开盘前新闻扫描)
SCHEDULE_AUCTION       = "09:25"   # 集合竞价策略
SCHEDULE_BREAKOUT      = "10:00"   # 放量突破策略
SCHEDULE_AFTERNOON     = "14:30"   # 尾盘短线策略
SCHEDULE_DIP_BUY       = "09:50"   # 低吸回调 (开盘下杀后)
SCHEDULE_CONSOLIDATION = "10:15"   # 缩量整理突破
SCHEDULE_TREND_FOLLOW  = "10:05"   # 趋势跟踪 (放量突破后5分钟)
SCHEDULE_SECTOR_ROTATION = "14:00" # 板块轮动 (午后板块分化明确)

# ================================================================
#  策略通用参数
# ================================================================
TOP_N = 3  # 每次推荐 TOP N 只

# ================================================================
#  放量突破策略参数
# ================================================================
BREAKOUT_PARAMS = {
    # 初筛条件
    "pct_min": 1.0,          # 涨幅下限 (%)
    "pct_max": 7.0,          # 涨幅上限 (%)
    "volume_ratio_min": 2.0, # 量比下限
    "turnover_min": 1.0,     # 换手率下限 (%)

    # 因子权重 (v6: 有效因子主导, 空因子降权)
    "weights": {
        "s_volume_breakout":  0.25,  # 量比强度 (核心, 0.20→0.25)
        "s_ma_alignment":     0.22,  # 均线排列 (核心, 0.15→0.22)
        "s_momentum":         0.15,  # 动量 (0.10→0.15)
        "s_rsi":              0.12,  # RSI (0.08→0.12)
        "s_fundamental":      0.03,  # 基本面 (0.08→0.03, 经常缺失)
        "s_hot":              0.03,  # 热门 (0.07→0.03, 经常缺失)
        "s_turnover":         0.08,  # 换手率 (0.04→0.08)
        "s_resistance_break": 0.05,  # 突破阻力 (0.03→0.05)
        "s_fund_flow":        0.03,  # 资金流 (0.10→0.03, 经常全零)
        "s_lhb":              0.02,  # 龙虎榜 (0.08→0.02, 数据不全)
        "s_chip":             0.02,  # 筹码 (0.07→0.02)
    },
}

# ================================================================
#  2026年中国法定节假日 (交易所休市日)
# ================================================================
CN_HOLIDAYS_2026 = {
    # 元旦
    "2026-01-01", "2026-01-02", "2026-01-03",
    # 春节 (1/26除夕 ~ 2/1)
    "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29",
    "2026-01-30", "2026-01-31", "2026-02-01",
    # 清明节
    "2026-04-04", "2026-04-05", "2026-04-06",
    # 劳动节
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    # 端午节
    "2026-06-19", "2026-06-20", "2026-06-21",
    # 中秋节
    "2026-09-25", "2026-09-26", "2026-09-27",
    # 国庆节
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# 调休补班日 (周末上班)
CN_WORKDAYS_2026 = {
    "2026-01-24",  # 春节调休
    "2026-02-07",  # 春节调休
    "2026-04-26",  # 劳动节调休
    "2026-06-28",  # 端午节调休
    "2026-09-19",  # 中秋节调休
    "2026-10-10",  # 国庆节调休
}

# ================================================================
#  集合竞价策略参数
# ================================================================
AUCTION_PARAMS = {
    "weights": {
        "s_gap":          0.22,  # 高开幅度 (0.15→0.22, 竞价核心)
        "s_volume_ratio": 0.18,  # 量比 (0.12→0.18, 竞价量是关键)
        "s_auction":      0.12,  # 竞价强度 (0.08→0.12)
        "s_trend":        0.18,  # 趋势 (0.12→0.18, 区分度最大)
        "s_rsi":          0.12,  # RSI (0.08→0.12)
        "s_fundamental":  0.05,  # 基本面 (0.10→0.05, 经常缺失降权)
        "s_hot":          0.03,  # 热门 (0.07→0.03, 经常缺失降权)
        "s_turnover":     0.05,  # 换手 (0.03→0.05)
        "s_fund_flow":    0.02,  # 资金流 (0.10→0.02, 经常全零降权)
        "s_lhb":          0.02,  # 龙虎榜 (0.08→0.02, 龙虎榜数据不全)
        "s_chip":         0.01,  # 筹码 (0.07→0.01)
    },
}

# ================================================================
#  尾盘短线策略参数
# ================================================================
AFTERNOON_PARAMS = {
    "weights": {
        "s_pm_gain":      0.22,  # 午后涨幅 (核心信号, 0.15→0.22)
        "s_pct":          0.10,  # 日涨幅
        "s_vol_turn":     0.12,  # 量价 (0.08→0.12)
        "s_trend":        0.18,  # 趋势 (区分度最大, 0.12→0.18)
        "s_rsi":          0.12,  # RSI (0.08→0.12)
        "s_fundamental":  0.05,  # 基本面 (降权)
        "s_hot":          0.03,  # 热门 (降权)
        "s_5m_speed":     0.10,  # 5分钟加速 (0.07→0.10)
        "s_fund_flow":    0.03,  # 资金流 (降权)
        "s_lhb":          0.03,  # 龙虎榜 (降权)
        "s_chip":         0.02,  # 筹码 (降权)
    },
}

# ================================================================
#  增强因子权重 (资金流向 / 龙虎榜 / 筹码压力支撑)
# ================================================================
# ================================================================
#  低吸回调策略参数
# ================================================================
DIP_BUY_PARAMS = {
    "weights": {
        "s_rsi_oversold":   0.20,   # RSI<30 超卖程度
        "s_volume_shrink":  0.15,   # 缩量程度 (跌时量萎缩=抄底安全)
        "s_support":        0.15,   # 支撑位距离 (接近MA20/MA60)
        "s_rebound_signal": 0.12,   # 反弹信号 (下影线/十字星)
        "s_fundamental":    0.10,   # 基本面
        "s_ma_distance":    0.08,   # 偏离均线程度
        "s_fund_flow":      0.10,   # 资金流向
        "s_chip":           0.10,   # 筹码分布
    },
    "rsi_threshold": 30,            # RSI 低于此值才入选
    "max_drawdown_5d_pct": -8,      # 近5日跌幅 ≥ 8%
}

# ================================================================
#  缩量整理突破策略参数
# ================================================================
CONSOLIDATION_PARAMS = {
    "weights": {
        "s_volume_contract": 0.20,  # 缩量程度 (近5日量/20日均量)
        "s_price_range":     0.18,  # 价格区间收窄 (近10日振幅)
        "s_breakout_ready":  0.15,  # 突破准备度 (价格贴近上轨)
        "s_ma_support":      0.12,  # 均线支撑
        "s_fundamental":     0.10,  # 基本面
        "s_trend_strength":  0.08,  # 整理前趋势强度
        "s_fund_flow":       0.10,  # 资金流向
        "s_chip":            0.07,  # 筹码集中度
    },
    "consolidation_days": 10,       # 整理天数下限
    "volume_ratio_threshold": 0.6,  # 量比 < 0.6 视为缩量
}

# ================================================================
#  趋势跟踪策略参数
# ================================================================
TREND_FOLLOW_PARAMS = {
    "weights": {
        "s_trend_score":    0.22,   # 趋势强度 (ADX/均线斜率)
        "s_ma_alignment":   0.18,   # 多头排列 (MA5>MA10>MA20>MA60)
        "s_momentum":       0.15,   # 动量 (MACD/收益连续性)
        "s_volume_confirm": 0.12,   # 量价配合
        "s_fundamental":    0.08,   # 基本面
        "s_sector_trend":   0.10,   # 所属板块趋势
        "s_fund_flow":      0.08,   # 资金流向
        "s_chip":           0.07,   # 筹码
    },
    "holding_days": 5,              # 默认持仓天数
    "adx_threshold": 25,            # ADX > 25 视为有趋势
}

# ================================================================
#  板块轮动策略参数
# ================================================================
SECTOR_ROTATION_PARAMS = {
    "weights": {
        "s_sector_momentum":  0.25, # 板块近5日涨幅排名
        "s_sector_flow":      0.20, # 板块资金净流入
        "s_sector_breadth":   0.15, # 板块内上涨家数占比
        "s_leader_score":     0.15, # 龙头股强度
        "s_fundamental":      0.08, # 基本面
        "s_relative_strength": 0.10,# 相对大盘强度
        "s_chip":             0.07, # 筹码
    },
    "top_sectors": 3,               # 选最强 3 个板块
    "picks_per_sector": 1,          # 每板块选 1 只龙头
}

# ================================================================
#  事件驱动选股策略参数
# ================================================================
NEWS_EVENT_PARAMS = {
    "weights": {
        "s_event_relevance":  0.25,  # 事件关联度 (属于几个相关概念板块)
        "s_concept_momentum": 0.20,  # 概念板块当日涨幅
        "s_leader_score":     0.15,  # 龙头评分
        "s_trend":            0.10,  # 趋势 (站上MA)
        "s_fundamental":      0.08,  # 基本面
        "s_fund_flow":        0.10,  # 资金流向
        "s_chip":             0.07,  # 筹码
        "s_volume_confirm":   0.05,  # 量价配合
    },
    "event_concept_map": {
        "战争|冲突|军事|军演|导弹|南海|台海": ["军工", "国防", "航天", "航空"],
        "制裁|贸易战|关税|脱钩|断供|出口管制": ["国产替代", "自主可控", "信创", "华为概念"],
        "降息|宽松|放水|降准|LPR": ["房地产", "银行", "证券", "保险"],
        "疫情|传染病|流感|病毒|公共卫生": ["医药", "生物医药", "医疗器械", "疫苗"],
        "涨价|通胀|CPI|PPI|供给紧张": ["有色金属", "煤炭", "石油", "化工", "农业"],
        "芯片|半导体|光刻|EDA|集成电路": ["芯片", "半导体", "消费电子"],
        "新能源|碳中和|光伏|风电|储能": ["新能源", "光伏", "风电", "储能", "锂电池"],
        "AI|人工智能|大模型|算力|GPU": ["人工智能", "算力", "CPO", "机器人"],
        "国企改革|混改|央企": ["国企改革", "央企"],
        "消费|促消费|内需|假期": ["消费", "白酒", "旅游", "零售"],
    },
    "min_event_confidence": 0.3,   # 置信度下限
    "max_concept_boards": 5,       # 最多扫描板块数
    "picks_per_board": 2,          # 每板块选几只
}

ENHANCED_FACTOR_WEIGHTS = {
    "fund_flow": 0.10,  # 资金流向权重
    "lhb":       0.08,  # 龙虎榜权重
    "chip":      0.07,  # 筹码/压力支撑权重
}

# ================================================================
#  止损止盈参数
# ================================================================
STOP_LOSS_PCT = -3.0       # 跌3%止损
TAKE_PROFIT_PCT = 5.0      # 涨5%止盈
FORCE_EXIT_TIME = "14:50"  # T+1尾盘强制离场
POSITION_FILE = "positions.json"  # 持仓记录文件

# ================================================================
#  智能交易优化 (总开关 + 6组参数)
# ================================================================
SMART_TRADE_ENABLED = True  # 总开关, False 时走原逻辑

# 大盘环境检测 (基础参数)
MARKET_REGIME_PARAMS = {
    "index_code": "000852",         # 中证1000指数
    "ma_period": 20,                # MA 周期
    "trend_lookback": 5,            # 趋势回望天数
}

# ================================================================
#  多信号大盘行情判断 v2.0 — 8信号评分制
# ================================================================

# 8个信号的权重 (三个层次, 合计 1.0)
# Tier1 价格结构(40%): S1均线趋势 + S2多周期动量 + S3波动率
# Tier2 市场广度(35%): S4涨跌比 + S5涨跌停比 + S6北向资金
# Tier3 杠杆确认(25%): S7融资趋势 + S8指数RSI
MARKET_SIGNAL_WEIGHTS = {
    "s1_ma_trend":      0.15,   # 均线趋势 (价格 vs MA5/MA20/MA60)
    "s2_momentum":      0.15,   # 多周期动量 (5/10/20日涨跌幅)
    "s3_volatility":    0.10,   # 波动率状态 (20日波动率分位)
    "s4_advance_decline":0.15,  # 涨跌比 (上涨家数/下跌家数)
    "s5_limit_ratio":   0.10,   # 涨跌停比 (涨停数/跌停数)
    "s6_northbound":    0.10,   # 北向资金 (5日净流入)
    "s7_margin_trend":  0.10,   # 融资趋势 (5日融资余额变化)
    "s8_index_rsi":     0.15,   # 指数RSI (14日)
}

# 回测版只用4个纯K线信号, 权重重新归一化
MARKET_SIGNAL_WEIGHTS_BACKTEST = {
    "s1_ma_trend":   0.15,
    "s2_momentum":   0.15,
    "s3_volatility": 0.10,
    "s8_index_rsi":  0.15,
}
# 自动归一化: 0.15+0.15+0.10+0.15 = 0.55 → 各自 /0.55

# 合成评分 → 4种市场状态的阈值
MARKET_REGIME_THRESHOLDS = {
    "bull":    0.65,   # score >= 0.65 → 牛市
    "neutral": 0.45,   # score >= 0.45 → 震荡
    "weak":    0.30,   # score >= 0.30 → 弱势
    # score < 0.30 → 熊市
}

# 4种市场状态下的策略参数自适应表
REGIME_STRATEGY_PARAMS = {
    "bull": {
        "position_scale":    1.2,
        "max_positions":     9,
        "min_single_pct":    0.5,
        "max_single_pct":    9.0,
        "volume_ratio_min":  1.5,
        "atr_multiplier":    2.0,
        "trail_pct":         2.0,
        "initial_target_pct":8.0,
        "first_exit_pct":    5.0,
        "first_exit_ratio":  0.3,
    },
    "neutral": {
        "position_scale":    0.8,
        "max_positions":     6,
        "min_single_pct":    1.0,
        "max_single_pct":    7.0,
        "volume_ratio_min":  2.0,
        "atr_multiplier":    1.5,
        "trail_pct":         1.5,
        "initial_target_pct":5.0,
        "first_exit_pct":    3.0,
        "first_exit_ratio":  0.5,
    },
    "weak": {
        "position_scale":    0.4,
        "max_positions":     3,
        "min_single_pct":    2.0,
        "max_single_pct":    5.0,
        "volume_ratio_min":  2.5,
        "atr_multiplier":    1.0,
        "trail_pct":         1.0,
        "initial_target_pct":3.0,
        "first_exit_pct":    2.0,
        "first_exit_ratio":  0.7,
    },
    "bear": {
        "position_scale":    0.0,
        "max_positions":     0,
        "min_single_pct":    0.0,
        "max_single_pct":    0.0,
        "volume_ratio_min":  999,
        "atr_multiplier":    1.0,
        "trail_pct":         1.0,
        "initial_target_pct":3.0,
        "first_exit_pct":    2.0,
        "first_exit_ratio":  0.7,
    },
}

# 回撤入场
PULLBACK_ENTRY_PARAMS = {
    "enabled": True,
    "pullback_pct": 1.0,            # 等回撤 1% 再入场
    "use_open_as_base": True,       # 回测用次日开盘价
    "limit_order_offset": 0.5,      # 实盘限价单低于现价 0.5%
}

# 自适应止损 (ATR)
ADAPTIVE_STOP_PARAMS = {
    "enabled": True,
    "atr_period": 14,
    "atr_multiplier": 1.5,          # 止损 = 入场价 - 1.5×ATR
    "min_stop_pct": -2.0,           # 最紧 -2%
    "max_stop_pct": -5.0,           # 最宽 -5%
    "fallback_stop_pct": -3.0,      # ATR 不可用时回退
}

# 追踪止盈
TRAILING_STOP_PARAMS = {
    "enabled": True,
    "activation_pct": 2.0,          # 盈利 ≥2% 激活追踪
    "trail_pct": 1.5,               # 从最高价回撤 1.5% 触发
    "initial_target_pct": 5.0,      # 追踪未激活前的固定止盈
}

# 分批止盈
PARTIAL_EXIT_PARAMS = {
    "enabled": True,
    "first_exit_pct": 3.0,          # 盈利 ≥3% 卖第一批
    "first_exit_ratio": 0.5,        # 卖出 50%
    "remainder_trail": True,        # 剩余用追踪止盈
}

# 动态仓位
DYNAMIC_SIZING_PARAMS = {
    "enabled": True,
    "score_weight": 0.6,            # 高分多买
    "equal_weight": 0.4,            # 均等部分
    "volatility_adjust": True,      # 低波动多买
    "max_single_pct": 20.0,
    "min_single_pct": 5.0,
}

# ================================================================
#  交易成本
# ================================================================
TRADE_COST = {
    "commission": 0.00025,  # 佣金万2.5 (单边)
    "stamp_tax": 0.0005,    # 印花税0.05% (卖出)
    "slippage": 0.001,      # 滑点0.1%
}

# ================================================================
#  风控参数
# ================================================================
RISK_PARAMS = {
    "max_positions": 9,           # 最大同时持仓数
    "max_per_sector": 2,          # 同行业最大持仓数
    "max_daily_trades": 9,        # 每日最大新增持仓数
    "single_position_pct": 15,    # 单只持仓占总资金比例上限 (%)
    "daily_loss_limit_pct": -5.0, # 每日总亏损熔断线 (%)
    "blacklist_threshold": 3,     # 连续亏损次数 → 拉黑
    "blacklist_days": 60,         # 黑名单持续天数
}

# ================================================================
#  自动优化参数
# ================================================================
OPTIMIZATION_PARAMS = {
    "eval_window_days": 14,       # 评估窗口 (天)
    "min_samples": 10,            # 最少样本数才触发优化
    "improve_threshold_pct": 1.0, # 收益提升 >= 1% 才采纳
    "max_weight_delta": 0.05,     # 单次权重调整幅度上限
    "backtest_validate": True,    # 回测验证开关
    "rollback_on_decline": True,  # 采纳后表现变差则自动回滚
    # 验证闭环
    "verify_after_days": 5,       # 采纳后 N 天验证效果
    "verify_score_drop_limit": -5, # 得分下降超过此值则回滚
    "verify_min_samples": 3,      # 验证期最少样本数
    # 因子生命周期
    "factor_min_weight": 0.03,    # 因子权重低于此值 → 候选淘汰
    "factor_decay_correlation": -0.05,  # 因子相关性低于此值 → 衰减
    "max_deweight_per_cycle": 1,  # 每次最多降权 1 个因子/策略
}

# ================================================================
#  ML 因子模型参数
# ================================================================
ML_PARAMS = {
    "model_type": "gradient_boosting",     # gradient_boosting | xgboost | lightgbm
    "task": "classification",                 # 分类: 预测涨跌方向 (比回归更实用)
    "n_estimators": 80,                    # 200→80 防过拟合
    "max_depth": 3,                        # 5→3 限制树深度
    "learning_rate": 0.05,
    "min_samples_leaf": 25,                # 10→25 每叶最少样本
    "subsample": 0.7,                      # 0.8→0.7 增加随机性
    "ml_weight": 0.3,                      # 0.4→0.3 OOS未验证前降低ML权重
    "min_training_samples": 50,
    "wf_train_days": 30,                   # 90→30 适配54天数据
    "wf_test_days": 8,                     # 30→8 更多窗口
    "wf_n_windows": 5,                     # 3→5 多窗口验证
}

# ================================================================
#  纸盘模拟交易参数
# ================================================================
PAPER_PARAMS = {
    "initial_capital": 100000,      # 初始资金
    "single_position_pct": 15,      # 单笔仓位上限 (%)
    "max_positions": 9,             # 最大持仓数
    "max_daily_trades": 9,          # 每日最大开仓数
    "stop_loss_pct": -3.0,          # 基础止损 (%)
    "take_profit_pct": 5.0,         # 基础止盈 (%)
    "force_exit_days": 3,           # 最大持仓天数
    "use_smart_trade": True,        # 使用智能交易 (ATR止损/追踪/分批)
}

# ================================================================
#  券商自动下单参数
# ================================================================
STOCK_EXECUTOR_PARAMS = {
    "mode": "paper",                    # paper | demo | live
    "broker": "easytrader",             # easytrader | xtquant
    "broker_type": "universal_client",  # easytrader 券商类型
    "account_file": "",                 # easytrader 账户配置文件
    "max_positions": 9,
    "max_daily_trades": 9,
    "single_position_pct": 15,          # 单笔仓位上限 (%)
    "daily_loss_limit_pct": -5.0,
    "consecutive_loss_halt": 4,         # 连亏 N 次暂停
    "force_exit_days": 3,
    "kill_switch_enabled": True,
    "slippage_pct": 0.1,
    "commission_rate": 0.00025,         # 万2.5
    "stamp_tax_rate": 0.0005,           # 印花税 0.05%
}

# ================================================================
#  回测参数
# ================================================================
BACKTEST_PARAMS = {
    "lookback_days": 90,        # 回测区间(天)
    "initial_capital": 100000,  # 初始资金
}

# ================================================================
#  微信推送每日上限
# ================================================================
MAX_WECHAT_DAILY = 5  # 批量合并推送: 1早报 + 1上午批 + 1盘中批 + 1下午批 + 1晚报

# ================================================================
#  智能体 (Agent Brain) 参数
# ================================================================
AGENT_PARAMS = {
    "enabled": True,
    "auto_pause_consecutive_losses": 4,   # 连亏N次自动暂停策略
    "auto_resume_days": 5,                # 暂停后N个交易日自动恢复
    "min_rule_confidence": 0.6,           # 规则置信度 >= 此值才自主行动
    "max_proactive_push_daily": 2,        # 每日最多主动推送N条洞察
    "morning_briefing": True,             # 每日早报开关
    "rule_prune_confidence": 0.2,         # 置信度低于此值的规则被清理
    "rule_prune_min_evals": 10,           # 至少评估N次后才清理
}

# ================================================================
#  自学习引擎参数
# ================================================================
LEARNING_ENGINE_PARAMS = {
    "learning_enabled": True,
    "min_samples_signal": 15,     # 信号分析最少样本
    "min_samples_factor": 10,     # 因子分析最少样本
    "min_samples_regime": 5,      # 策略-行情分析最少样本
    "lookback_days": 30,
    "max_weight_delta": 0.03,     # 单次最大调整 3%
    "min_weight": 0.03,           # 权重下限
    "predictive_threshold": 5.0,  # 预测力阈值 (%)
    "wechat_learning_report": False,  # 改为False: 学习报告纳入晚报, 不单独发微信
}

# ================================================================
#  LLM 顾问 (Claude API)
# ================================================================
LLM_ADVISOR_PARAMS = {
    "enabled": True,
    "api_key_env": "ANTHROPIC_API_KEY",    # 从环境变量读取
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 1024,
    "temperature": 0.3,
    "timeout_sec": 30,
    "max_daily_calls": 20,                  # 每日 API 调用上限
}

# ================================================================
#  组合层全局风控
# ================================================================
PORTFOLIO_RISK_PARAMS = {
    "enabled": True,
    "max_portfolio_drawdown_pct": -8.0,     # 组合最大回撤
    "correlation_window_days": 30,
    "rebalance_threshold": 0.15,
    "strategy_allocation": {
        "集合竞价选股": 0.10,
        "放量突破选股": 0.10,
        "尾盘短线选股": 0.10,
        "低吸回调选股": 0.10,
        "缩量整理选股": 0.09,
        "趋势跟踪选股": 0.09,
        "板块轮动选股": 0.08,
        "事件驱动选股": 0.08,
        "期货趋势选股": 0.10,
        "币圈趋势选股": 0.08,
        "美股收盘分析": 0.08,
    },
    "max_strategy_allocation": 0.50,
    "min_strategy_allocation": 0.10,
    # Kelly / Risk Parity (OP-08)
    "kelly_min_samples": 5,              # Kelly 最少样本数
    "kelly_use_half": True,              # 使用 Half-Kelly (更保守)
    "allocation_weights": {              # 三信号融合权重
        "health": 0.4,
        "kelly": 0.3,
        "risk_parity": 0.3,
    },
}

# ================================================================
#  自主实验
# ================================================================
EXPERIMENT_PARAMS = {
    "enabled": True,
    "max_concurrent_experiments": 2,
    "min_health_score_trigger": 50,          # score < 50 才触发实验
    "backtest_lookback_days": 90,
    "n_candidates": 5,
    "adopt_threshold_pct": 1.0,              # 收益提升 >= 1% 才采纳
    "cooldown_days": 7,                      # 同策略最小间隔
}

# ================================================================
#  API 防封机制
# ================================================================
API_GUARD_PARAMS = {
    "enabled": True,
    "max_rpm": 600,                         # 全局每分钟最大请求数 (跨进程文件锁协调)
    "burst": 60,                            # 令牌桶突发容量
    "circuit_failure_threshold": 10,        # 连续失败N次 → 熔断 (5→10, akshare波动大)
    "circuit_cooldown_sec": 60,             # 熔断冷却时间 (120→60s, 快速恢复)
    "pool_cache_ttl_sec": 3600,             # 中证1000成分股缓存 1小时
    "daily_kline_cache_ttl_sec": 300,       # 日K缓存 5分钟
    # Tushare Pro 配置 (注册后填入)
    "tushare_token": "26f714bafd61fc50e93eed1260549b918b1f367c7915a2fa329bc51e",
    "tushare_enabled": True,
}

# ================================================================
#  期货趋势策略
# ================================================================
SCHEDULE_FUTURES_DAY = "09:05"              # 日盘扫描 (全品种)
SCHEDULE_FUTURES_NIGHT = "21:10"            # 夜盘扫描 (有夜盘品种)

FUTURES_PARAMS = {
    "enabled": True,
    "top_n": 5,                             # 推荐TOP N个合约
    "weights": {
        "s_trend":    0.35,                 # 趋势强度 (MA排列+ADX)
        "s_momentum": 0.30,                 # 动量 (RSI+MACD)
        "s_volume":   0.20,                 # 量仓配合
        "s_risk":     0.15,                 # 风险评分 (ATR/波动率)
    },
    "min_adx": 20,                          # ADX最低阈值
    "min_volume_ratio": 1.2,                # 成交量比最低阈值
    "risk_per_trade_pct": 2.0,              # 每笔交易风险占比 (%)
    "max_lots_per_contract": 5,             # 单合约最大手数
    "atr_stop_multiplier": 2.0,             # ATR止损倍数
}

# ================================================================
#  期货交易执行器
# ================================================================
TRADE_EXECUTOR_PARAMS = {
    "mode": "simnow",                       # "paper" 模拟 / "simnow" SimNow / "live" 实盘
    "trailing_activation_pct": 3.0,         # 追踪止盈激活阈值 (%)
    "trailing_drawdown_pct": 1.5,           # 追踪止盈回撤触发 (%)
    "fixed_take_profit_pct": 5.0,           # 固定止盈 (%)
    "monitor_interval_minutes": 30,         # 持仓监控间隔 (分钟)
    # --- tqsdk 天勤量化 (simnow/live 模式需要) ---
    "tqsdk_user": "蓝天ma12345",             # 天勤账号
    "tqsdk_password": "as341102",           # 天勤密码
    # --- 实盘专用 (live 模式需要) ---
    "broker_id": "",                        # 期货公司 BrokerID
    "futures_account": "",                  # 期货资金账号
    "futures_password": "",                 # 期货交易密码
}

# ================================================================
#  多智能体协调系统
# ================================================================
MULTI_AGENT_PARAMS = {
    "enabled": True,
    "event_bus": {
        "dedup_window_sec": 60,              # 同事件去重窗口 (秒)
        "max_events": 500,                   # 队列最大事件数
    },
    "agent_registry": {
        "unhealthy_threshold": 0.5,          # 健康度低于此值报警
    },
    "conflict_resolution": {
        "authority": {                       # 类别优先级 (越高越权威)
            "risk": 4,
            "regime": 3,
            "strategy": 2,
            "info": 1,
        },
    },
}

# ================================================================
#  币圈趋势策略
# ================================================================
SCHEDULE_CRYPTO = "01:00"                      # 夜班期间扫描

CRYPTO_PARAMS = {
    "enabled": True,
    "top_n": 5,                                # 推荐 TOP N 个币种
    "weights": {
        "s_trend":    0.35,                    # 趋势强度 (MA排列+ADX)
        "s_momentum": 0.30,                    # 动量 (RSI+MACD)
        "s_volume":   0.20,                    # 量能变化
        "s_risk":     0.15,                    # 风险评分 (波动率)
    },
    "min_adx": 20,                             # ADX最低阈值
    "min_volume_ratio": 1.2,                   # 量比最低阈值
    "atr_stop_multiplier": 2.0,                # ATR止损倍数
}

# ================================================================
#  美股收盘分析策略
# ================================================================
SCHEDULE_US_STOCK = "05:30"                    # 美股收盘后 (北京时间05:30)

US_STOCK_PARAMS = {
    "enabled": True,
    "top_n": 5,                                # 推荐 TOP N 个标的
    "weights": {
        "s_trend":    0.35,                    # 趋势强度 (MA排列+ADX)
        "s_momentum": 0.30,                    # 动量 (RSI+MACD)
        "s_volume":   0.20,                    # 量能变化
        "s_risk":     0.15,                    # 风险评分 (波动率)
    },
    "min_adx": 20,                             # ADX最低阈值
    "min_volume_ratio": 1.2,                   # 量比最低阈值
    "atr_stop_multiplier": 2.0,                # ATR止损倍数
}

# ================================================================
#  跨市场信号推演
# ================================================================
SCHEDULE_CROSS_MARKET = "06:00"                # 美股收盘+夜盘收盘后综合推演

CROSS_MARKET_PARAMS = {
    "enabled": True,
}

# ================================================================
#  开盘前作战计划
# ================================================================
SCHEDULE_MORNING_PREP = "07:30"                # 开盘前作战计划

MORNING_PREP_PARAMS = {
    "enabled": True,
}

# ================================================================
#  夜班系统 (22:30 - 06:30)
# ================================================================
NIGHT_SHIFT_PARAMS = {
    "enabled": True,
    "start_time": "22:30",
    "end_time": "08:30",                 # 10 小时夜班 (含开盘前准备)
    "tasks": [
        # (任务名, 预计分钟, 说明)
        ("performance_review",   1,   "绩效考核"),
        ("llm_analysis",         2,   "LLM 深度复盘"),
        ("batch_backtest",       120, "批量回测验证"),
        ("factor_discovery",     120, "因子发现实验"),
        ("strategy_evolution",   90,  "策略参数进化"),
        ("ooda_replay",          90,  "OODA 历史回放"),
        ("crypto_scan",          30,  "币圈趋势扫描"),
        ("us_stock_analysis",    30,  "美股收盘分析"),
        ("cross_market_signal",  30,  "跨市场信号推演"),
        ("morning_prep",         60,  "开盘前数据准备+作战计划"),
    ],
    "backtest": {
        "lookback_days": 180,            # 回测历史天数
        "param_grid_size": 10,           # 每个参数的网格点数
        "top_k_params": 3,               # 保留前 K 组最优参数
    },
    "wechat_progress": True,             # 是否推送夜班进度
}
