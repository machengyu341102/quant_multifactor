"""
Factor Forge 单元测试
=====================
覆盖: 指标库 / IC评估 / WF验证 / 部署 / 生命周期 / 钩子函数 / 主循环
"""

import os
import sys
import json
import copy
import tempfile
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import factor_forge as ff


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture
def sample_ohlcv():
    """生成 120 天的 OHLCV 数据"""
    np.random.seed(42)
    n = 120
    closes = 10.0 + np.cumsum(np.random.randn(n) * 0.1)
    closes = np.maximum(closes, 1.0)
    highs = closes + np.abs(np.random.randn(n) * 0.05)
    lows = closes - np.abs(np.random.randn(n) * 0.05)
    volumes = np.random.randint(1000, 10000, n).astype(float)
    return closes, highs, lows, volumes


@pytest.fixture
def sample_df():
    """生成 120 天的 DataFrame"""
    np.random.seed(42)
    n = 120
    closes = 10.0 + np.cumsum(np.random.randn(n) * 0.1)
    closes = np.maximum(closes, 1.0)
    df = pd.DataFrame({
        "close": closes,
        "high": closes + np.abs(np.random.randn(n) * 0.05),
        "low": closes - np.abs(np.random.randn(n) * 0.05),
        "amount": np.random.randint(1000, 10000, n).astype(float),
    })
    return df


@pytest.fixture
def short_ohlcv():
    """5 天的不足数据"""
    c = np.array([10.0, 10.1, 10.2, 10.0, 10.3])
    return c, c + 0.1, c - 0.1, np.array([1000.0] * 5)


@pytest.fixture
def forge_config_dir(tmp_path):
    """临时目录替换 forge 配置路径"""
    orig_config = ff._FORGE_CONFIG_PATH
    orig_tunable = ff._TUNABLE_PATH
    ff._FORGE_CONFIG_PATH = str(tmp_path / "forge_config.json")
    ff._TUNABLE_PATH = str(tmp_path / "tunable_params.json")
    yield tmp_path
    ff._FORGE_CONFIG_PATH = orig_config
    ff._TUNABLE_PATH = orig_tunable


@pytest.fixture
def mock_scorecard():
    """合成 scorecard 数据 (30 天 × 20 只股票)"""
    records = []
    np.random.seed(123)
    codes = [f"00{i:04d}" for i in range(20)]
    base = date.today() - timedelta(days=30)
    for d in range(30):
        dt = (base + timedelta(days=d)).isoformat()
        for code in codes:
            records.append({
                "date": dt,
                "code": code,
                "net_return_pct": np.random.randn() * 2,
            })
    return records


@pytest.fixture
def mock_kline_map():
    """合成 K 线缓存 (20 只股票各 120 天)"""
    np.random.seed(456)
    kmap = {}
    for i in range(20):
        code = f"00{i:04d}"
        n = 120
        closes = 10.0 + np.cumsum(np.random.randn(n) * 0.1)
        closes = np.maximum(closes, 1.0)
        kmap[code] = pd.DataFrame({
            "close": closes,
            "high": closes + np.abs(np.random.randn(n) * 0.05),
            "low": closes - np.abs(np.random.randn(n) * 0.05),
            "amount": np.random.randint(1000, 10000, n).astype(float),
        })
    return kmap


# ================================================================
#  TestIndicatorLibrary: 23 个指标
# ================================================================

class TestIndicatorLibrary:
    """所有指标返回 [0,1] 或 NaN"""

    def test_all_indicators_return_01(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        for name, fn in ff.INDICATOR_LIBRARY.items():
            val = fn(c, h, l, v)
            assert val is not None, f"{name} returned None"
            if np.isnan(val):
                continue
            assert 0.0 <= val <= 1.0, f"{name} returned {val}, expected [0,1]"

    def test_short_data_returns_nan(self, short_ohlcv):
        c, h, l, v = short_ohlcv
        nan_expected = [
            "macd_cross", "macd_histogram", "adx_strength", "di_crossover",
            "roc_20", "stochastic_d", "obv_trend", "volume_zscore",
            "vwap_distance", "boll_width_pctile", "atr_pctile",
        ]
        for name in nan_expected:
            fn = ff.INDICATOR_LIBRARY[name]
            val = fn(c, h, l, v)
            assert val is None or np.isnan(val), \
                f"{name} should return NaN for short data, got {val}"

    def test_indicator_count(self):
        assert len(ff.INDICATOR_LIBRARY) == 23

    def test_macd_cross(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_macd_cross(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_stochastic_k(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_stochastic_k(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_cci_14(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_cci_14(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_obv_trend(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_obv_trend(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_boll_width_pctile(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_boll_width_pctile(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_inside_bar(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_inside_bar(c, h, l, v)
        assert 0.0 <= val <= 1.0

    def test_vol_price_diverge(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_vol_price_diverge(c, h, l, v)
        assert val in (0.1, 0.3, 0.7, 0.9)

    def test_gap_factor(self, sample_ohlcv):
        c, h, l, v = sample_ohlcv
        val = ff.ind_gap_factor(c, h, l, v)
        assert 0.0 <= val <= 1.0


# ================================================================
#  TestICEvaluation
# ================================================================

class TestICEvaluation:

    def test_ic_with_synthetic_data(self, mock_kline_map, mock_scorecard):
        """合成数据 IC 计算基本功能"""
        result = ff.evaluate_indicator_ic(
            ff.ind_roc_5, mock_kline_map, mock_scorecard, min_dates=3
        )
        assert "mean_ic" in result
        assert "ic_ir" in result
        assert "n_dates" in result
        assert isinstance(result["n_dates"], int)

    def test_ic_insufficient_data(self):
        """数据不足时返回 passed=False"""
        result = ff.evaluate_indicator_ic(
            ff.ind_roc_5, {}, [], min_dates=10
        )
        assert result["passed"] is False
        assert result["n_dates"] == 0

    def test_ic_with_correlated_indicator(self, mock_kline_map, mock_scorecard):
        """强相关指标的 IC 应有意义"""
        # 制造一个完美预测指标
        def perfect_indicator(c, h, l, v):
            return ff._clip01(0.5 + (c[-1] / c[-2] - 1) * 10) if len(c) >= 2 else 0.5

        result = ff.evaluate_indicator_ic(
            perfect_indicator, mock_kline_map, mock_scorecard, min_dates=3
        )
        assert result["n_dates"] >= 3


# ================================================================
#  TestWFValidation
# ================================================================

class TestWFValidation:

    def test_wf_insufficient_dates(self, mock_kline_map):
        """数据不足时 WF 应返回 passed=False"""
        # 只有 5 条 scorecard
        few_records = [
            {"date": "2026-01-01", "code": "000001", "net_return_pct": 1.0}
        ] * 5
        result = ff.walk_forward_ic_check(
            ff.ind_roc_5, mock_kline_map, few_records, n_windows=3
        )
        assert result["passed"] is False

    def test_wf_returns_structure(self, mock_kline_map, mock_scorecard):
        """WF 返回正确结构"""
        result = ff.walk_forward_ic_check(
            ff.ind_roc_5, mock_kline_map, mock_scorecard, n_windows=2
        )
        assert "passed" in result
        assert "windows" in result


# ================================================================
#  TestDeployment
# ================================================================

class TestDeployment:

    def test_deploy_creates_config(self, forge_config_dir):
        """部署因子应创建 forge_config.json"""
        ic_stats = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        wf = {"passed": True, "passed_windows": 2, "total_windows": 3}

        success = ff.deploy_factor("roc_5", ic_stats, wf)
        assert success

        config = ff._safe_load(ff._FORGE_CONFIG_PATH)
        assert "roc_5" in config["active_factors"]

    def test_deploy_injects_weights(self, forge_config_dir):
        """部署应注入 tunable_params 权重"""
        # 预写 tunable_params
        tunable = {"breakout_weights": {"weights": {"s_rsi": 0.5, "s_trend": 0.5}}}
        ff._safe_save(ff._TUNABLE_PATH, tunable)

        ic_stats = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        wf = {"passed": True}
        ff.deploy_factor("roc_5", ic_stats, wf)

        tunable = ff._safe_load(ff._TUNABLE_PATH)
        weights = tunable["breakout_weights"]["weights"]
        assert "s_forge_roc_5" in weights
        # 总和约 1.0
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_deploy_duplicate_skipped(self, forge_config_dir):
        """重复部署应跳过"""
        ic_stats = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        wf = {"passed": True}
        assert ff.deploy_factor("roc_5", ic_stats, wf)
        assert not ff.deploy_factor("roc_5", ic_stats, wf)

    def test_deploy_respects_max_active(self, forge_config_dir):
        """超出上限应拒绝"""
        ic = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        wf = {"passed": True}

        with patch.dict(ff.FACTOR_FORGE_PARAMS, {"max_active_per_strategy": 2}):
            assert ff.deploy_factor("ind_a", ic, wf)
            assert ff.deploy_factor("ind_b", ic, wf)
            assert not ff.deploy_factor("ind_c", ic, wf)

    def test_daily_deployment_count(self, forge_config_dir):
        """今日部署计数"""
        assert ff._count_today_deployments() == 0
        ic = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        ff.deploy_factor("roc_5", ic, {"passed": True})
        assert ff._count_today_deployments() == 1

    def test_weight_normalization(self, forge_config_dir):
        """权重归一化: 部署后所有权重总和 = 1.0"""
        tunable = {}
        for key in ff._STRATEGY_KEYS:
            tunable[key] = {"weights": {
                "s_a": 0.3, "s_b": 0.3, "s_c": 0.4,
            }}
        ff._safe_save(ff._TUNABLE_PATH, tunable)

        ic = {"mean_ic": 0.05, "ic_ir": 0.8, "passed": True}
        ff.deploy_factor("test_ind", ic, {"passed": True})

        tunable = ff._safe_load(ff._TUNABLE_PATH)
        for key in ff._STRATEGY_KEYS:
            total = sum(tunable[key]["weights"].values())
            assert abs(total - 1.0) < 0.01, f"{key} weights sum = {total}"


# ================================================================
#  TestLifecycle
# ================================================================

class TestLifecycle:

    def test_retire_weak_factor(self, forge_config_dir):
        """退役弱因子"""
        config = {
            "active_factors": {
                "old_ind": {
                    "factor_key": "s_forge_old_ind",
                    "deployed_date": (date.today() - timedelta(days=15)).isoformat(),
                    "status": "active",
                }
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        # 模拟 signal_tracker 返回弱效力
        mock_eff = {"s_forge_old_ind": {"spread": 1.0, "predictive": False}}
        with patch("signal_tracker.get_factor_effectiveness", return_value=mock_eff):
            results = ff.check_forge_lifecycle()

        assert len(results) == 1
        assert results[0]["action"] == "retired"

        # 检查已移到 retired
        config = ff._safe_load(ff._FORGE_CONFIG_PATH)
        assert "old_ind" not in config["active_factors"]
        assert "old_ind" in config["retired_factors"]

    def test_young_factor_protected(self, forge_config_dir):
        """年轻因子受保护, 不退役"""
        config = {
            "active_factors": {
                "young_ind": {
                    "factor_key": "s_forge_young_ind",
                    "deployed_date": (date.today() - timedelta(days=3)).isoformat(),
                    "status": "active",
                }
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        mock_eff = {"s_forge_young_ind": {"spread": 0.5}}
        with patch("signal_tracker.get_factor_effectiveness", return_value=mock_eff):
            results = ff.check_forge_lifecycle()

        assert len(results) == 0

    def test_retire_removes_weight(self, forge_config_dir):
        """退役应删除 tunable_params 中的权重"""
        tunable = {"breakout_weights": {"weights": {
            "s_rsi": 0.5, "s_forge_old": 0.5
        }}}
        ff._safe_save(ff._TUNABLE_PATH, tunable)

        config = {
            "active_factors": {
                "old": {
                    "factor_key": "s_forge_old",
                    "deployed_date": (date.today() - timedelta(days=15)).isoformat(),
                }
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        mock_eff = {"s_forge_old": {"spread": 1.0}}
        with patch("signal_tracker.get_factor_effectiveness", return_value=mock_eff):
            ff.check_forge_lifecycle()

        tunable = ff._safe_load(ff._TUNABLE_PATH)
        assert "s_forge_old" not in tunable["breakout_weights"]["weights"]
        # 剩余权重归一化
        total = sum(tunable["breakout_weights"]["weights"].values())
        assert abs(total - 1.0) < 0.01


# ================================================================
#  TestComputeForgeFactors
# ================================================================

class TestComputeForgeFactors:

    def test_no_active_factors_passthrough(self, forge_config_dir):
        """无活跃因子时直接返回原 df"""
        df = pd.DataFrame({"code": ["000001"], "s_rsi": [0.5]})
        result = ff.compute_forge_factors(df)
        assert list(result.columns) == ["code", "s_rsi"]

    def test_adds_forge_columns(self, forge_config_dir, sample_df):
        """有活跃因子时添加列"""
        config = {
            "active_factors": {
                "roc_5": {
                    "factor_key": "s_forge_roc_5",
                    "deployed_date": date.today().isoformat(),
                }
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        # 填充缓存
        ff._forge_kline_cache["000001"] = sample_df

        df = pd.DataFrame({"code": ["000001"], "s_rsi": [0.5]})
        result = ff.compute_forge_factors(df)
        assert "s_forge_roc_5" in result.columns

    def test_exception_safe(self, forge_config_dir):
        """异常安全: 不崩溃"""
        # 写一个坏的 config
        with open(ff._FORGE_CONFIG_PATH, "w") as f:
            f.write("{invalid json")

        df = pd.DataFrame({"code": ["000001"]})
        result = ff.compute_forge_factors(df)
        assert len(result) == 1  # 安全返回


# ================================================================
#  TestGetForgeWeights
# ================================================================

class TestGetForgeWeights:

    def test_empty_when_no_config(self, forge_config_dir):
        assert ff.get_forge_weights() == {}

    def test_returns_weights(self, forge_config_dir):
        config = {
            "active_factors": {
                "roc_5": {"factor_key": "s_forge_roc_5"}
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        tunable = {"breakout_weights": {"weights": {"s_forge_roc_5": 0.02}}}
        ff._safe_save(ff._TUNABLE_PATH, tunable)

        weights = ff.get_forge_weights()
        assert "s_forge_roc_5" in weights
        assert weights["s_forge_roc_5"] == 0.02


# ================================================================
#  TestRunForgeCycle
# ================================================================

class TestRunForgeCycle:

    def test_disabled(self, forge_config_dir):
        """disabled 时直接返回"""
        with patch.dict(ff.FACTOR_FORGE_PARAMS, {"enabled": False}):
            result = ff.run_forge_cycle()
            assert result["status"] == "disabled"

    def test_insufficient_cache(self, forge_config_dir):
        """K 线缓存不足时跳过"""
        ff._forge_kline_cache.clear()
        with patch.object(ff, "_ensure_kline_cache"):
            with patch.dict(ff.FACTOR_FORGE_PARAMS, {"enabled": True}):
                result = ff.run_forge_cycle()
                assert result["status"] == "insufficient_data"

    def test_full_cycle_integration(self, forge_config_dir, mock_kline_map, mock_scorecard):
        """端到端集成 (含 scorecard mock)"""
        ff._forge_kline_cache.clear()
        ff._forge_kline_cache.update(mock_kline_map)

        with patch("db_store.load_scorecard", return_value=mock_scorecard):
            with patch.dict(ff.FACTOR_FORGE_PARAMS, {"enabled": True, "min_ic_dates": 3}):
                result = ff.run_forge_cycle()

        assert "evaluated" in result
        assert "deployed" in result
        assert len(result["evaluated"]) > 0


# ================================================================
#  TestForgeStatus
# ================================================================

class TestForgeStatus:

    def test_empty_status(self, forge_config_dir):
        status = ff.get_forge_status()
        assert status["active_count"] == 0
        assert status["retired_count"] == 0

    def test_with_active_factor(self, forge_config_dir):
        config = {
            "active_factors": {
                "roc_5": {
                    "factor_key": "s_forge_roc_5",
                    "deployed_date": "2026-03-05",
                    "ic_stats": {"ic_ir": 0.8},
                }
            },
            "retired_factors": {},
            "deploy_log": [],
        }
        ff._safe_save(ff._FORGE_CONFIG_PATH, config)

        status = ff.get_forge_status()
        assert status["active_count"] == 1
        assert "roc_5" in status["active_factors"]


# ================================================================
#  TestCacheKlines
# ================================================================

class TestCacheKlines:

    def test_cache_sufficient_data(self, sample_df):
        ff._forge_kline_cache.clear()
        ff.cache_klines_for_forge("TEST001", sample_df)
        assert "TEST001" in ff._forge_kline_cache
        assert len(ff._forge_kline_cache["TEST001"]) == 120

    def test_cache_short_data_ignored(self):
        ff._forge_kline_cache.clear()
        short_df = pd.DataFrame({"close": [1, 2, 3]})
        ff.cache_klines_for_forge("SHORT", short_df)
        assert "SHORT" not in ff._forge_kline_cache

    def test_cache_none_ignored(self):
        ff._forge_kline_cache.clear()
        ff.cache_klines_for_forge("NONE", None)
        assert "NONE" not in ff._forge_kline_cache


# ================================================================
#  TestExtractOHLCV
# ================================================================

class TestExtractOHLCV:

    def test_extract_with_amount(self, sample_df):
        c, h, l, v = ff._extract_ohlcv(sample_df)
        assert len(c) == 120
        assert len(v) == 120

    def test_extract_fallback_volumes(self):
        df = pd.DataFrame({"close": [10.0], "high": [10.5], "low": [9.5]})
        c, h, l, v = ff._extract_ohlcv(df)
        assert v[0] == 1.0  # 默认填 1


# ================================================================
#  TestHelpers
# ================================================================

class TestHelpers:

    def test_clip01(self):
        assert ff._clip01(0.5) == 0.5
        assert ff._clip01(-0.1) == 0.0
        assert ff._clip01(1.5) == 1.0
        assert np.isnan(ff._clip01(np.nan))

    def test_safe_div(self):
        assert ff._safe_div(10, 2) == 5.0
        assert ff._safe_div(10, 0) == 0.0
        assert ff._safe_div(10, np.nan) == 0.0

    def test_safe_load_missing(self):
        assert ff._safe_load("/nonexistent/path.json", default=[]) == []

    def test_safe_save_load(self, tmp_path):
        path = str(tmp_path / "test.json")
        ff._safe_save(path, {"key": "value"})
        loaded = ff._safe_load(path)
        assert loaded["key"] == "value"
