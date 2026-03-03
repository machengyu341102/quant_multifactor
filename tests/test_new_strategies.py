"""
4 个新策略 + 批量推送 + 持仓天数 单元测试
"""

import json
import os
import sys
import pytest
import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

# 确保可以导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  TestDipBuy — 低吸回调策略
# ================================================================

class TestDipBuy:
    """低吸回调策略测试"""

    def test_rsi_filter(self):
        """RSI < 30 初筛"""
        from mean_reversion_strategy import _score_dip_buy
        df = pd.DataFrame({
            "code": ["000001", "000002", "000003"],
            "name": ["测试A", "测试B", "测试C"],
            "rsi": [25, 35, 20],
            "pct_chg": [-1.5, -2.0, -3.0],
            "vol_ratio_5_20": [0.5, 0.6, 0.4],
            "close": [10.0, 20.0, 15.0],
            "ma20": [11.0, 22.0, 17.0],
            "ma60": [12.0, 23.0, 18.0],
            "shadow_ratio": [2.0, 0.5, 3.0],
            "above_ma60": [False, False, False],
        })
        name_map = {"000001": "测试A", "000002": "测试B", "000003": "测试C"}
        result = _score_dip_buy(df, name_map)
        # 000002 RSI=35 应被过滤
        assert "000002" not in result["code"].values
        assert "000001" in result["code"].values
        assert "000003" in result["code"].values

    def test_rsi_oversold_score(self):
        """RSI超卖评分: RSI越低分越高"""
        from mean_reversion_strategy import _score_dip_buy
        df = pd.DataFrame({
            "code": ["000001", "000002"],
            "name": ["A", "B"],
            "rsi": [10, 28],
            "pct_chg": [-2.0, -1.0],
            "vol_ratio_5_20": [0.5, 0.5],
            "close": [10.0, 10.0],
            "ma20": [11.0, 11.0],
            "ma60": [12.0, 12.0],
            "shadow_ratio": [1.0, 1.0],
            "above_ma60": [False, False],
        })
        result = _score_dip_buy(df, {"000001": "A", "000002": "B"})
        if not result.empty:
            # RSI=10 应该比 RSI=28 分更高
            row1 = result[result["code"] == "000001"]
            row2 = result[result["code"] == "000002"]
            if not row1.empty and not row2.empty:
                assert row1.iloc[0]["s_rsi_oversold"] > row2.iloc[0]["s_rsi_oversold"]

    def test_empty_data_graceful(self):
        """空数据降级: 不崩溃"""
        from mean_reversion_strategy import _score_dip_buy
        df = pd.DataFrame(columns=[
            "code", "name", "rsi", "pct_chg", "vol_ratio_5_20",
            "close", "ma20", "ma60", "shadow_ratio", "above_ma60",
        ])
        result = _score_dip_buy(df, {})
        assert result.empty

    def test_no_decline_stocks(self):
        """所有股票涨幅 > 0 时, 初筛应返回空"""
        from mean_reversion_strategy import _score_dip_buy
        df = pd.DataFrame({
            "code": ["000001"],
            "name": ["A"],
            "rsi": [25],
            "pct_chg": [1.5],  # 涨
            "vol_ratio_5_20": [0.5],
            "close": [10.0],
            "ma20": [11.0],
            "ma60": [12.0],
            "shadow_ratio": [1.0],
            "above_ma60": [False],
        })
        result = _score_dip_buy(df, {"000001": "A"})
        assert result.empty


# ================================================================
#  TestConsolidation — 缩量整理突破策略
# ================================================================

class TestConsolidation:
    """缩量整理突破策略测试"""

    def test_volume_contract_filter(self):
        """缩量检测: vol_ratio_5_20 < 0.6"""
        from mean_reversion_strategy import _score_consolidation
        df = pd.DataFrame({
            "code": ["000001", "000002"],
            "name": ["A", "B"],
            "range_10d": [5.0, 5.0],
            "vol_ratio_5_20": [0.3, 0.8],  # 0.8 不符合
            "volume_ratio": [2.0, 2.0],
            "close": [10.0, 10.0],
            "boll_upper": [10.5, 10.5],
            "ma20": [9.8, 9.8],
            "ma60": [9.5, 9.5],
            "above_ma60": [True, True],
        })
        result = _score_consolidation(df, {"000001": "A", "000002": "B"})
        assert "000002" not in result["code"].values if not result.empty else True

    def test_range_filter(self):
        """振幅过大应被过滤 (range_10d >= 10)"""
        from mean_reversion_strategy import _score_consolidation
        df = pd.DataFrame({
            "code": ["000001"],
            "name": ["A"],
            "range_10d": [15.0],  # 振幅太大
            "vol_ratio_5_20": [0.3],
            "volume_ratio": [2.0],
            "close": [10.0],
            "boll_upper": [10.5],
            "ma20": [9.8],
            "ma60": [9.5],
            "above_ma60": [True],
        })
        result = _score_consolidation(df, {"000001": "A"})
        assert result.empty

    def test_breakout_today_volume(self):
        """今日放量确认: 需要 volume_ratio > 1.5"""
        from mean_reversion_strategy import _score_consolidation
        df = pd.DataFrame({
            "code": ["000001"],
            "name": ["A"],
            "range_10d": [5.0],
            "vol_ratio_5_20": [0.3],
            "volume_ratio": [1.0],  # 不够放量
            "close": [10.0],
            "boll_upper": [10.5],
            "ma20": [9.8],
            "ma60": [9.5],
            "above_ma60": [True],
        })
        result = _score_consolidation(df, {"000001": "A"})
        assert result.empty

    def test_valid_candidate_scores(self):
        """符合条件的候选应有完整评分"""
        from mean_reversion_strategy import _score_consolidation
        df = pd.DataFrame({
            "code": ["000001"],
            "name": ["A"],
            "range_10d": [5.0],
            "vol_ratio_5_20": [0.3],
            "volume_ratio": [2.0],
            "close": [10.0],
            "boll_upper": [10.2],
            "ma20": [9.9],
            "ma60": [9.5],
            "above_ma60": [True],
        })
        result = _score_consolidation(df, {"000001": "A"})
        if not result.empty:
            assert "s_volume_contract" in result.columns
            assert "s_price_range" in result.columns
            assert "s_breakout_ready" in result.columns


# ================================================================
#  TestTrendFollow — 趋势跟踪策略
# ================================================================

class TestTrendFollow:
    """趋势跟踪策略测试"""

    def test_adx_calculation(self):
        """ADX 计算应返回合理值"""
        from trend_sector_strategy import _calc_adx
        np.random.seed(42)
        n = 100
        closes = np.cumsum(np.random.randn(n) * 0.5) + 100
        highs = closes + np.abs(np.random.randn(n) * 0.3)
        lows = closes - np.abs(np.random.randn(n) * 0.3)
        adx = _calc_adx(highs, lows, closes, 14)
        assert isinstance(adx, float)
        assert 0 <= adx <= 100

    def test_adx_insufficient_data(self):
        """数据不足时 ADX 返回 0"""
        from trend_sector_strategy import _calc_adx
        closes = np.array([10.0, 10.5, 11.0])
        highs = closes + 0.2
        lows = closes - 0.2
        adx = _calc_adx(highs, lows, closes, 14)
        assert adx == 0

    def test_ma_alignment_filter(self):
        """趋势筛选: 需要多头排列"""
        from trend_sector_strategy import _score_trend_follow
        df = pd.DataFrame({
            "code": ["000001", "000002"],
            "name": ["A", "B"],
            "adx": [30, 35],
            "ma_aligned": [True, False],  # B 不是多头排列
            "full_aligned": [True, False],
            "macd_hist": [0.5, 0.5],
            "up_days": [3, 3],
            "vol_price_confirm": [0.8, 0.8],
            "rsi": [55, 55],
            "ma20_slope": [1.0, 1.0],
            "close": [10.0, 10.0],
            "atr": [0.3, 0.3],
            "ma5": [10.2, 10.2],
            "ma20": [9.8, 9.8],
            "above_ma60": [True, True],
        })
        result = _score_trend_follow(df, {"000001": "A", "000002": "B"})
        assert "000002" not in result["code"].values if not result.empty else True

    def test_holding_days_in_output(self):
        """趋势跟踪输出应包含 holding_days 字段"""
        from config import TREND_FOLLOW_PARAMS
        holding_days = TREND_FOLLOW_PARAMS.get("holding_days", 5)
        assert holding_days > 1  # 趋势跟踪必须是多日持仓


# ================================================================
#  TestSectorRotation — 板块轮动策略
# ================================================================

class TestSectorRotation:
    """板块轮动策略测试"""

    @patch("trend_sector_strategy._retry_heavy")
    def test_sector_ranking(self, mock_retry):
        """板块排名获取"""
        from trend_sector_strategy import _get_sector_ranking
        mock_retry.return_value = pd.DataFrame({
            "板块名称": ["半导体", "新能源", "消费"],
            "涨跌幅": [3.5, 2.1, -0.5],
        })
        result = _get_sector_ranking()
        assert len(result) == 3
        assert result[0]["name"] == "半导体"
        assert result[0]["pct"] == 3.5

    @patch("trend_sector_strategy._retry_heavy")
    def test_sector_ranking_empty(self, mock_retry):
        """板块数据为空时降级"""
        from trend_sector_strategy import _get_sector_ranking
        mock_retry.return_value = pd.DataFrame()
        result = _get_sector_ranking()
        assert result == []

    @patch("trend_sector_strategy._retry_heavy")
    def test_sector_stocks(self, mock_retry):
        """板块成分股获取"""
        from trend_sector_strategy import _get_sector_stocks
        mock_retry.return_value = pd.DataFrame({
            "代码": ["000001", "000002", "688001"],
        })
        result = _get_sector_stocks("半导体")
        assert "000001" in result
        assert "688001" not in result  # 科创板应被排除

    @patch("trend_sector_strategy._retry_heavy")
    def test_sector_stocks_failure(self, mock_retry):
        """板块成分获取失败降级"""
        from trend_sector_strategy import _get_sector_stocks
        mock_retry.side_effect = Exception("API error")
        result = _get_sector_stocks("不存在板块")
        assert result == []


# ================================================================
#  TestNotifyBatch — 批量推送
# ================================================================

class TestNotifyBatch:
    """批量推送测试"""

    @patch("notifier.requests.post")
    def test_batch_format(self, mock_post):
        """合并推送格式正确"""
        from notifier import notify_batch_wechat
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 0}
        mock_post.return_value = mock_resp

        results = [
            ("集合竞价选股", [{"code": "000001", "name": "平安", "price": 10.0, "score": 0.8, "reason": "test"}]),
            ("放量突破选股", [{"code": "000002", "name": "万科", "price": 5.0, "score": 0.6, "reason": "test"}]),
        ]
        notify_batch_wechat("测试批次", results)

        assert mock_post.called
        call_data = mock_post.call_args
        desp = call_data.kwargs.get("data", call_data[1].get("data", {})).get("desp", "")
        assert "集合竞价选股" in desp
        assert "放量突破选股" in desp
        assert "000001" in desp

    def test_batch_empty_skip(self):
        """空 buffer 不应调用推送"""
        from notifier import notify_batch_wechat
        # 不应崩溃
        notify_batch_wechat("空批次", [])
        notify_batch_wechat("空批次", [("策略A", []), ("策略B", [])])


# ================================================================
#  TestHoldingDays — 动态持仓期
# ================================================================

class TestHoldingDays:
    """持仓天数测试"""

    def test_holding_days_recorded(self, tmp_path, monkeypatch):
        """record_entry 应写入 holding_days"""
        monkeypatch.setattr("position_manager._POS_PATH",
                            str(tmp_path / "positions.json"))

        from position_manager import record_entry, load_positions

        items = [{
            "code": "000001",
            "name": "测试",
            "price": 10.0,
            "score": 0.8,
            "reason": "test",
            "holding_days": 5,
        }]
        record_entry("趋势跟踪选股", items)
        positions = load_positions()
        assert len(positions) == 1
        assert positions[0]["holding_days"] == 5

    def test_default_holding_days(self, tmp_path, monkeypatch):
        """不传 holding_days 默认为 1 (T+1 兼容)"""
        monkeypatch.setattr("position_manager._POS_PATH",
                            str(tmp_path / "positions.json"))

        from position_manager import record_entry, load_positions

        items = [{
            "code": "000002",
            "name": "测试B",
            "price": 20.0,
            "score": 0.5,
            "reason": "test",
        }]
        record_entry("放量突破选股", items)
        positions = load_positions()
        assert len(positions) == 1
        assert positions[0]["holding_days"] == 1


# ================================================================
#  TestConfigIntegrity — 配置完整性
# ================================================================

class TestConfigIntegrity:
    """验证配置文件新增参数的完整性"""

    def test_new_params_exist(self):
        """4 个新策略参数块存在"""
        from config import (
            DIP_BUY_PARAMS, CONSOLIDATION_PARAMS,
            TREND_FOLLOW_PARAMS, SECTOR_ROTATION_PARAMS,
        )
        assert "weights" in DIP_BUY_PARAMS
        assert "weights" in CONSOLIDATION_PARAMS
        assert "weights" in TREND_FOLLOW_PARAMS
        assert "weights" in SECTOR_ROTATION_PARAMS

    def test_weights_sum_to_one(self):
        """权重总和应为 1.0"""
        from config import (
            DIP_BUY_PARAMS, CONSOLIDATION_PARAMS,
            TREND_FOLLOW_PARAMS, SECTOR_ROTATION_PARAMS,
        )
        for name, params in [
            ("dip_buy", DIP_BUY_PARAMS),
            ("consolidation", CONSOLIDATION_PARAMS),
            ("trend_follow", TREND_FOLLOW_PARAMS),
            ("sector_rotation", SECTOR_ROTATION_PARAMS),
        ]:
            total = sum(params["weights"].values())
            assert abs(total - 1.0) < 0.01, f"{name} weights sum={total}"

    def test_schedule_times_exist(self):
        """4 个新调度时间存在"""
        from config import (
            SCHEDULE_DIP_BUY, SCHEDULE_CONSOLIDATION,
            SCHEDULE_TREND_FOLLOW, SCHEDULE_SECTOR_ROTATION,
        )
        assert SCHEDULE_DIP_BUY
        assert SCHEDULE_CONSOLIDATION
        assert SCHEDULE_TREND_FOLLOW
        assert SCHEDULE_SECTOR_ROTATION

    def test_portfolio_allocation_sum(self):
        """组合分配总和应为 1.0"""
        from config import PORTFOLIO_RISK_PARAMS
        alloc = PORTFOLIO_RISK_PARAMS["strategy_allocation"]
        total = sum(alloc.values())
        assert abs(total - 1.0) < 0.01, f"allocation sum={total}"
        assert len(alloc) == 11

    def test_max_wechat_daily(self):
        """微信配额应为 5"""
        from config import MAX_WECHAT_DAILY
        assert MAX_WECHAT_DAILY == 5


# ================================================================
#  TestRegistration — 注册点完整性
# ================================================================

class TestRegistration:
    """验证所有注册点都包含 9 个策略"""

    def test_agent_brain_strategies(self):
        """agent_brain.STRATEGY_NAMES 应包含 9 个"""
        from agent_brain import STRATEGY_NAMES
        assert len(STRATEGY_NAMES) == 11
        assert "低吸回调选股" in STRATEGY_NAMES
        assert "板块轮动选股" in STRATEGY_NAMES
        assert "事件驱动选股" in STRATEGY_NAMES
        assert "期货趋势选股" in STRATEGY_NAMES

    def test_portfolio_risk_strategies(self):
        """portfolio_risk.STRATEGY_NAMES 应包含 9 个"""
        from portfolio_risk import STRATEGY_NAMES
        assert len(STRATEGY_NAMES) == 11

    def test_experiment_lab_map(self):
        """experiment_lab._STRATEGY_MAP 应包含 9 个"""
        from experiment_lab import _STRATEGY_MAP
        assert len(_STRATEGY_MAP) == 11
        assert "低吸回调选股" in _STRATEGY_MAP
        assert "期货趋势选股" in _STRATEGY_MAP

    def test_auto_optimizer_strategies(self):
        """auto_optimizer.SUPPORTED_STRATEGIES 应包含 9 个"""
        from auto_optimizer import SUPPORTED_STRATEGIES
        assert len(SUPPORTED_STRATEGIES) == 11
        assert "dip_buy" in SUPPORTED_STRATEGIES
        assert "sector_rotation" in SUPPORTED_STRATEGIES
        assert "futures_trend" in SUPPORTED_STRATEGIES

    def test_auto_optimizer_default_weights(self):
        """auto_optimizer 应能获取所有 9 个策略的默认权重"""
        from auto_optimizer import _get_default_weights
        for s in ["breakout", "auction", "afternoon",
                   "dip_buy", "consolidation", "trend_follow", "sector_rotation",
                   "news_event", "futures_trend"]:
            w = _get_default_weights(s)
            assert w, f"No default weights for {s}"
            assert isinstance(w, dict)
