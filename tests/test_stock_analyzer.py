"""
个股诊断智能体 — 单元测试
"""

import sys
import os
import math
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  技术指标计算测试
# ================================================================

class TestCalcMA:
    def test_basic(self):
        from stock_analyzer import _calc_ma
        closes = [10, 11, 12, 13, 14]
        assert _calc_ma(closes, 5) == pytest.approx(12.0)

    def test_insufficient_data(self):
        from stock_analyzer import _calc_ma
        assert _calc_ma([10, 11], 5) is None

    def test_period_1(self):
        from stock_analyzer import _calc_ma
        assert _calc_ma([42.0], 1) == pytest.approx(42.0)


class TestCalcEMA:
    def test_basic(self):
        from stock_analyzer import _calc_ema
        closes = list(range(1, 21))  # 1..20
        result = _calc_ema(closes, 10)
        assert result is not None
        assert result > 10  # EMA 应偏向近期

    def test_insufficient(self):
        from stock_analyzer import _calc_ema
        assert _calc_ema([1, 2], 10) is None


class TestCalcRSI:
    def test_all_gains(self):
        from stock_analyzer import _calc_rsi
        closes = list(range(100, 120))  # 持续上涨
        rsi = _calc_rsi(closes, 14)
        assert rsi is not None
        assert rsi == 100.0

    def test_mixed(self):
        from stock_analyzer import _calc_rsi
        closes = [10, 11, 10.5, 11.5, 10.8, 11.2, 10.9, 11.3,
                  10.7, 11.1, 10.6, 11.4, 10.8, 11.2, 10.9, 11.0]
        rsi = _calc_rsi(closes, 14)
        assert rsi is not None
        assert 30 < rsi < 70  # 震荡市 RSI 应在中间

    def test_insufficient(self):
        from stock_analyzer import _calc_rsi
        assert _calc_rsi([10, 11], 14) is None


class TestCalcMACD:
    def test_basic(self):
        from stock_analyzer import _calc_macd
        # 生成足够长的数据
        closes = [10 + i * 0.1 + (i % 3 - 1) * 0.05 for i in range(60)]
        result = _calc_macd(closes)
        assert result is not None
        assert "dif" in result
        assert "dea" in result
        assert "macd" in result

    def test_insufficient(self):
        from stock_analyzer import _calc_macd
        assert _calc_macd(list(range(10))) is None


class TestCalcBollinger:
    def test_basic(self):
        from stock_analyzer import _calc_bollinger
        closes = [10 + (i % 5 - 2) * 0.1 for i in range(30)]
        result = _calc_bollinger(closes, 20)
        assert result is not None
        assert result["upper"] > result["mid"] > result["lower"]
        assert result["width"] > 0

    def test_insufficient(self):
        from stock_analyzer import _calc_bollinger
        assert _calc_bollinger([10, 11], 20) is None


class TestCalcATR:
    def test_basic(self):
        from stock_analyzer import _calc_atr
        klines = []
        for i in range(20):
            klines.append({
                "open": 10 + i * 0.1,
                "high": 10.5 + i * 0.1,
                "low": 9.5 + i * 0.1,
                "close": 10.2 + i * 0.1,
            })
        atr = _calc_atr(klines, 14)
        assert atr is not None
        assert atr > 0

    def test_insufficient(self):
        from stock_analyzer import _calc_atr
        assert _calc_atr([{"high": 10, "low": 9, "close": 9.5}], 14) is None


# ================================================================
#  打分函数测试
# ================================================================

class TestScoreTrend:
    def test_bullish(self):
        from stock_analyzer import _score_trend
        # 构造多头排列: 价格 > MA5 > MA10 > MA20 > MA60
        closes = list(range(40, 110))  # 70个点, 持续上涨
        price = closes[-1]
        score, details = _score_trend(closes, price)
        assert score > 0.5
        assert any("多头" in d for d in details)

    def test_bearish(self):
        from stock_analyzer import _score_trend
        closes = list(range(110, 40, -1))  # 持续下跌
        price = closes[-1]
        score, details = _score_trend(closes, price)
        assert score < 0.5


class TestScoreMomentum:
    def test_overbought(self):
        from stock_analyzer import _score_momentum
        # 持续大涨 → RSI 高
        closes = [10 + i * 0.5 for i in range(60)]
        score, details = _score_momentum(closes)
        assert any("RSI" in d for d in details)

    def test_returns_valid_range(self):
        from stock_analyzer import _score_momentum
        closes = [10 + (i % 7 - 3) * 0.2 for i in range(60)]
        score, details = _score_momentum(closes)
        assert 0 <= score <= 1


class TestScoreVolume:
    def test_high_volume_ratio(self):
        from stock_analyzer import _score_volume
        klines = [{"open": 10, "high": 10.5, "low": 9.5, "close": 10.3, "volume": 1000} for _ in range(10)]
        rt = {"volume_ratio": 3.5, "turnover_rate": 5.0}
        score, details = _score_volume(klines, rt)
        assert score > 0.5
        assert any("放" in d for d in details)

    def test_no_rt(self):
        from stock_analyzer import _score_volume
        klines = [{"open": 10, "high": 10.5, "low": 9.5, "close": 10.3, "volume": 1000} for _ in range(10)]
        score, details = _score_volume(klines, None)
        assert 0 <= score <= 1


class TestScorePosition:
    def test_near_high(self):
        from stock_analyzer import _score_position
        closes = list(range(80, 110))  # 30个点
        price = closes[-1]  # 109, 接近最高点
        klines = [{"high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]
        score, details = _score_position(closes, price, klines)
        assert score < 0.5  # 高位应偏低

    def test_near_low(self):
        from stock_analyzer import _score_position
        closes = list(range(110, 80, -1))
        price = closes[-1]  # 81, 接近最低点
        klines = [{"high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]
        score, details = _score_position(closes, price, klines)
        assert score > 0.5  # 低位应偏高


class TestScoreFundFlow:
    def test_strong_inflow(self):
        from stock_analyzer import _score_fund_flow
        fund = {"net_mf": 8000, "net_mf_3d": 15000, "main_pct": 12}
        score, details = _score_fund_flow(fund)
        assert score > 0.5

    def test_strong_outflow(self):
        from stock_analyzer import _score_fund_flow
        fund = {"net_mf": -8000, "net_mf_3d": -15000, "main_pct": -12}
        score, details = _score_fund_flow(fund)
        assert score < 0.5

    def test_zero(self):
        from stock_analyzer import _score_fund_flow
        score, details = _score_fund_flow({"net_mf": 0, "net_mf_3d": 0, "main_pct": 0})
        assert score == pytest.approx(0.5)


# ================================================================
#  WEIGHTS 配置测试
# ================================================================

class TestWeights:
    def test_weights_sum_to_one(self):
        from stock_analyzer import WEIGHTS
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_all_positive(self):
        from stock_analyzer import WEIGHTS
        for k, v in WEIGHTS.items():
            assert v > 0, f"{k} weight should be positive"


# ================================================================
#  analyze_stock 集成测试 (mock 数据)
# ================================================================

class TestAnalyzeStock:
    def test_with_mock_data(self, monkeypatch):
        """用 mock 数据测试完整流程"""
        import stock_analyzer as sa

        # Mock K线
        klines = []
        for i in range(120):
            base = 10 + i * 0.05 + (i % 5 - 2) * 0.1
            klines.append({
                "date": f"2026-01-{(i % 28) + 1:02d}",
                "open": base - 0.1,
                "high": base + 0.3,
                "low": base - 0.3,
                "close": base,
                "volume": 10000 + i * 100,
                "turnover": 3.0,
            })
        monkeypatch.setattr(sa, "_fetch_klines", lambda code, days=120: klines)

        # Mock 实时行情
        monkeypatch.setattr(sa, "_fetch_realtime", lambda code: {
            "price": 15.0, "pct_change": 2.5, "volume_ratio": 1.8,
            "turnover_rate": 4.5, "name": "测试股票", "total_mv": 5e9,
            "circ_mv": 3e9, "pe": 25.0, "pb": 3.0,
            "high": 15.3, "low": 14.5, "open": 14.8, "pre_close": 14.6,
            "amount": 1e8,
        })

        # Mock 资金流
        monkeypatch.setattr(sa, "_fetch_fund_flow", lambda code: {
            "net_mf": 2000, "net_mf_3d": 5000, "main_pct": 8.0,
        })

        result = sa.analyze_stock("000001")
        assert result["code"] == "000001"
        assert result["name"] == "测试股票"
        assert 0 <= result["total_score"] <= 1
        assert result["direction"] in ("bullish", "bearish", "neutral")
        assert result["verdict"] in ("看多", "看空", "中性观望")
        assert "report_text" in result
        assert "scores" in result
        assert len(result["scores"]) == 5

    def test_no_klines(self, monkeypatch):
        """K线为空时返回 error"""
        import stock_analyzer as sa
        monkeypatch.setattr(sa, "_fetch_klines", lambda code, days=120: [])
        result = sa.analyze_stock("999999")
        assert "error" in result

    def test_journal_write(self, monkeypatch, tmp_path):
        """测试写入 trade_journal"""
        import stock_analyzer as sa

        klines = [{"date": "2026-03-01", "open": 10, "high": 10.5, "low": 9.5,
                    "close": 10 + i * 0.05, "volume": 10000, "turnover": 3.0}
                   for i in range(120)]
        monkeypatch.setattr(sa, "_fetch_klines", lambda code, days=120: klines)
        monkeypatch.setattr(sa, "_fetch_realtime", lambda code: {
            "price": 16.0, "pct_change": 1.0, "volume_ratio": 1.5,
            "turnover_rate": 3.0, "name": "测试", "total_mv": 1e9,
            "circ_mv": 5e8, "pe": 20, "pb": 2,
            "high": 16.1, "low": 15.8, "open": 15.9, "pre_close": 15.8,
            "amount": 5e7,
        })
        monkeypatch.setattr(sa, "_fetch_fund_flow", lambda code: {
            "net_mf": 0, "net_mf_3d": 0, "main_pct": 0,
        })

        # 用 tmp_path 替换 journal 路径
        journal_path = str(tmp_path / "trade_journal.json")
        monkeypatch.setattr(sa, "_DIR", str(tmp_path))

        # Mock smart_trader
        monkeypatch.setattr(sa, "_write_journal", lambda result: None)

        result = sa.analyze_stock("000001", journal=False)
        assert "error" not in result


class TestAnalyzeBatch:
    def test_batch(self, monkeypatch):
        import stock_analyzer as sa

        klines = [{"date": "2026-03-01", "open": 10, "high": 10.5, "low": 9.5,
                    "close": 10 + i * 0.05, "volume": 10000, "turnover": 3.0}
                   for i in range(120)]
        monkeypatch.setattr(sa, "_fetch_klines", lambda code, days=120: klines)
        monkeypatch.setattr(sa, "_fetch_realtime", lambda code: {
            "price": 16.0, "pct_change": 1.0, "volume_ratio": 1.5,
            "turnover_rate": 3.0, "name": f"股票{code}", "total_mv": 1e9,
            "circ_mv": 5e8, "pe": 20, "pb": 2,
            "high": 16.1, "low": 15.8, "open": 15.9, "pre_close": 15.8,
            "amount": 5e7,
        })
        monkeypatch.setattr(sa, "_fetch_fund_flow", lambda code: {
            "net_mf": 0, "net_mf_3d": 0, "main_pct": 0,
        })

        results = sa.analyze_batch(["000001", "000002", "600519"])
        assert len(results) == 3
        # 应按 total_score 降序
        for i in range(len(results) - 1):
            assert results[i]["total_score"] >= results[i + 1]["total_score"]
