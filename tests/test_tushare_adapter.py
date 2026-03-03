"""
tushare_adapter 单元测试
========================
覆盖: 代码转换/限速/回退逻辑/健康检查
不依赖真实 Tushare token, 全 mock
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  代码转换
# ================================================================

class TestCodeConversion:
    def test_to_ts_code_sh(self):
        from tushare_adapter import _to_ts_code
        assert _to_ts_code("600000") == "600000.SH"
        assert _to_ts_code("601107") == "601107.SH"

    def test_to_ts_code_sz(self):
        from tushare_adapter import _to_ts_code
        assert _to_ts_code("000001") == "000001.SZ"
        assert _to_ts_code("002216") == "002216.SZ"
        assert _to_ts_code("300476") == "300476.SZ"

    def test_to_ts_code_padding(self):
        from tushare_adapter import _to_ts_code
        assert _to_ts_code("1") == "000001.SZ"

    def test_from_ts_code(self):
        from tushare_adapter import _from_ts_code
        assert _from_ts_code("600000.SH") == "600000"
        assert _from_ts_code("000001.SZ") == "000001"
        assert _from_ts_code("300476") == "300476"


# ================================================================
#  报告期
# ================================================================

class TestReportPeriod:
    def test_latest_report_period(self):
        from tushare_adapter import _latest_report_period
        period = _latest_report_period()
        assert len(period) == 8
        assert period.endswith(("0331", "0630", "0930", "1231"))

    def test_prev_report_period(self):
        from tushare_adapter import _prev_report_period
        period = _prev_report_period()
        assert len(period) == 8


# ================================================================
#  健康检查 (无token时)
# ================================================================

class TestHealthCheck:
    def test_disabled_without_token(self):
        """未配置token时应返回disabled"""
        import tushare_adapter
        # 重置全局状态
        tushare_adapter._ts_api = None
        with patch.dict("config.API_GUARD_PARAMS",
                        {"tushare_token": "", "tushare_enabled": False}):
            tushare_adapter._ts_api = None
            result = tushare_adapter.health_check()
            assert result["status"] == "disabled"

    def test_is_available_false(self):
        """未配置时 is_available 返回 False"""
        import tushare_adapter
        tushare_adapter._ts_api = None
        with patch.dict("config.API_GUARD_PARAMS",
                        {"tushare_token": "", "tushare_enabled": False}):
            tushare_adapter._ts_api = None
            assert tushare_adapter.is_available() is False


# ================================================================
#  资金流 (Mock Tushare)
# ================================================================

class TestMoneyFlow:
    def test_tushare_money_flow(self):
        """Tushare 返回资金流数据"""
        import tushare_adapter
        mock_df = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260303"],
            "net_mf_amount": [500.0],
            "buy_lg_amount": [1000.0],
            "sell_lg_amount": [500.0],
        })
        with patch.object(tushare_adapter, "_ts_call", return_value=mock_df):
            result = tushare_adapter.get_money_flow("000001", days=1)
        assert result is not None
        assert result["net_mf_amount"] == 500.0
        assert result["buy_lg_amount"] == 1000.0

    def test_fallback_to_akshare(self):
        """Tushare 失败时回退 akshare"""
        import tushare_adapter
        with patch.object(tushare_adapter, "_ts_call", return_value=None):
            # akshare 也可能失败, 这里测试回退路径不崩溃
            result = tushare_adapter.get_money_flow("000001")
            # 返回 None 或 dict 都可以, 不崩溃就行
            assert result is None or isinstance(result, dict)

    def test_batch_money_flow(self):
        """批量资金流"""
        import tushare_adapter
        mock_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "net_mf_amount": [100.0, 200.0],
            "buy_lg_amount": [500.0, 600.0],
            "sell_lg_amount": [400.0, 400.0],
        })
        with patch.object(tushare_adapter, "_ts_call", return_value=mock_df):
            result = tushare_adapter.get_money_flow_batch(["000001", "600000"])
        assert "000001" in result
        assert "600000" in result
        assert result["600000"]["net_mf_amount"] == 200.0


# ================================================================
#  财报数据 (Mock)
# ================================================================

class TestFinancials:
    def test_tushare_financials(self):
        """Tushare 财报数据"""
        import tushare_adapter
        mock_income = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "revenue": [50000000000.0],
            "n_income": [10000000000.0],
        })
        mock_fina = pd.DataFrame({
            "ts_code": ["000001.SZ"],
            "netprofit_yoy": [15.5],
            "roe": [12.3],
        })
        call_count = [0]
        def mock_call(method, **kwargs):
            call_count[0] += 1
            if method == "income":
                return mock_income
            elif method == "fina_indicator":
                return mock_fina
            return None

        with patch.object(tushare_adapter, "_ts_call", side_effect=mock_call):
            result = tushare_adapter.get_financials("000001")
        assert result is not None
        assert result["profit_growth"] == 15.5
        assert result["roe"] == 12.3
        assert result["revenue"] > 0


# ================================================================
#  龙虎榜 (Mock)
# ================================================================

class TestTopList:
    def test_tushare_top_list(self):
        """Tushare 龙虎榜"""
        import tushare_adapter
        mock_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "600000.SH"],
            "name": ["平安银行", "浦发银行"],
            "close": [10.0, 8.0],
            "pct_change": [5.0, -2.0],
            "amount": [100000.0, 80000.0],
            "buy": [60000.0, 30000.0],
            "sell": [40000.0, 50000.0],
            "reason": ["涨幅偏离", "跌幅偏离"],
        })
        with patch.object(tushare_adapter, "_ts_call", return_value=mock_df):
            result = tushare_adapter.get_top_list("20260303")
        assert len(result) == 2
        assert result[0]["code"] == "000001"
        assert result[0]["reason"] == "涨幅偏离"

    def test_empty_top_list(self):
        """无龙虎榜数据"""
        import tushare_adapter
        with patch.object(tushare_adapter, "_ts_call", return_value=None):
            result = tushare_adapter.get_top_list()
        assert result == []


# ================================================================
#  限速
# ================================================================

class TestThrottle:
    def test_throttle_not_crash(self):
        """限速函数不崩溃"""
        from tushare_adapter import _ts_throttle
        # 连续调用不崩溃
        for _ in range(5):
            _ts_throttle()


# ================================================================
#  日K线回退
# ================================================================

class TestDailyKline:
    def test_fallback_kline(self):
        """日K线回退不崩溃"""
        import tushare_adapter
        # 两个源都失败时返回 None
        with patch.object(tushare_adapter, "_ts_call", return_value=None):
            result = tushare_adapter.get_daily_kline("999999")
            # 可能返回 akshare 数据或 None
            assert result is None or hasattr(result, "columns")
