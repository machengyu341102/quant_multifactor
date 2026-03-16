"""
特征工程引擎 + ML集成 测试
"""
import os
import sys
import json
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 隔离: 把 feature_config.json 指向临时目录
_TMPDIR = tempfile.mkdtemp()


class TestDiscoverFactorColumns(unittest.TestCase):
    """因子列自动发现"""

    def test_discover_s_prefix(self):
        from feature_engineer import discover_factor_columns
        df = pd.DataFrame({
            "s_rsi": np.random.randn(50),
            "s_trend": np.random.randn(50),
            "s_vol": np.random.randn(50),
            "code": ["000001"] * 50,  # 非数值列应跳过
            "name": ["test"] * 50,
        })
        cols = discover_factor_columns(df)
        self.assertIn("s_rsi", cols)
        self.assertIn("s_trend", cols)
        self.assertIn("s_vol", cols)
        self.assertNotIn("code", cols)
        self.assertNotIn("name", cols)

    def test_discover_raw_features(self):
        from feature_engineer import discover_factor_columns
        df = pd.DataFrame({
            "rsi": np.random.randn(50),
            "volatility": np.random.randn(50),
            "total_score": np.random.randn(50),
        })
        cols = discover_factor_columns(df)
        self.assertIn("rsi", cols)
        self.assertIn("volatility", cols)
        self.assertIn("total_score", cols)

    def test_skip_sparse_columns(self):
        from feature_engineer import discover_factor_columns
        df = pd.DataFrame({
            "s_rsi": np.random.randn(50),
            "s_sparse": [np.nan] * 45 + [1.0] * 5,  # 只有 10% 非空
        })
        cols = discover_factor_columns(df)
        self.assertIn("s_rsi", cols)
        self.assertNotIn("s_sparse", cols)


class TestGenerateInteractions(unittest.TestCase):
    """交互特征生成"""

    def test_basic_interactions(self):
        from feature_engineer import generate_interactions
        np.random.seed(42)
        df = pd.DataFrame({
            "s_a": np.random.randn(100),
            "s_b": np.random.randn(100),
            "s_c": np.random.randn(100),
        })
        df_out, interactions = generate_interactions(df, ["s_a", "s_b", "s_c"])
        # 3 pairs × 2 types = 6 interactions
        self.assertEqual(len(interactions), 6)
        for ix in interactions:
            self.assertIn(ix["name"], df_out.columns)

    def test_multiply_interaction(self):
        from feature_engineer import generate_interactions
        df = pd.DataFrame({
            "s_a": [2.0, 3.0, 4.0],
            "s_b": [1.0, 2.0, 3.0],
        })
        df_out, interactions = generate_interactions(df, ["s_a", "s_b"])
        mul_ix = [ix for ix in interactions if ix["type"] == "multiply"]
        self.assertTrue(len(mul_ix) > 0)
        col = mul_ix[0]["name"]
        expected = df["s_a"] * df["s_b"]
        pd.testing.assert_series_equal(df_out[col], expected, check_names=False)

    def test_ratio_clipped(self):
        from feature_engineer import generate_interactions
        df = pd.DataFrame({
            "s_a": [100.0, -100.0, 0.0],
            "s_b": [0.001, 0.001, 1.0],
        })
        df_out, interactions = generate_interactions(df, ["s_a", "s_b"])
        rat_ix = [ix for ix in interactions if ix["type"] == "ratio"]
        self.assertTrue(len(rat_ix) > 0)
        col = rat_ix[0]["name"]
        # 应该被裁剪到 [-10, 10]
        self.assertTrue(df_out[col].max() <= 10.0)
        self.assertTrue(df_out[col].min() >= -10.0)

    def test_max_interactions_cap(self):
        import feature_engineer as fe
        old_defaults = fe.DEFAULTS["max_interactions"]
        old_params = dict(fe._FE_PARAMS) if fe._FE_PARAMS else {}
        fe.DEFAULTS["max_interactions"] = 4
        fe._FE_PARAMS["max_interactions"] = 4
        try:
            np.random.seed(42)
            df = pd.DataFrame({
                f"s_{i}": np.random.randn(50) for i in range(10)
            })
            cols = [f"s_{i}" for i in range(10)]
            _, interactions = fe.generate_interactions(df, cols)
            self.assertLessEqual(len(interactions), 4)
        finally:
            fe.DEFAULTS["max_interactions"] = old_defaults
            fe._FE_PARAMS.clear()
            fe._FE_PARAMS.update(old_params)

    def test_top_k_selection(self):
        from feature_engineer import _select_top_factors
        np.random.seed(42)
        df = pd.DataFrame({
            "s_high_var": np.random.randn(100) * 10,    # high variance
            "s_med_var": np.random.randn(100) * 1,
            "s_low_var": np.random.randn(100) * 0.01,   # low variance
        })
        top = _select_top_factors(df, ["s_high_var", "s_med_var", "s_low_var"], 2)
        self.assertEqual(len(top), 2)
        self.assertIn("s_high_var", top)
        self.assertNotIn("s_low_var", top)


class TestPruneCorrelated(unittest.TestCase):
    """相关性剪枝"""

    def test_prune_perfect_correlation(self):
        from feature_engineer import prune_correlated
        df = pd.DataFrame({
            "s_a": [1, 2, 3, 4, 5],
            "s_b": [2, 4, 6, 8, 10],   # 完全相关 (s_a * 2)
            "s_c": [5, 4, 3, 2, 1],     # 负相关
        })
        kept = prune_correlated(df, ["s_a", "s_b", "s_c"], threshold=0.95)
        # s_a 和 s_b 完全相关, 应该剪掉一个
        self.assertIn("s_a", kept)
        self.assertTrue(len(kept) < 3)

    def test_prune_prefers_dropping_interactions(self):
        from feature_engineer import prune_correlated
        df = pd.DataFrame({
            "s_a": [1, 2, 3, 4, 5],
            "ix_s_a_s_b_mul": [1, 2, 3, 4, 5],   # 完全相关, 但是交互特征
        })
        kept = prune_correlated(df, ["s_a", "ix_s_a_s_b_mul"], threshold=0.95)
        # 应该保留原始因子 s_a, 剪掉交互因子
        self.assertIn("s_a", kept)
        self.assertNotIn("ix_s_a_s_b_mul", kept)

    def test_no_prune_below_threshold(self):
        from feature_engineer import prune_correlated
        np.random.seed(42)
        df = pd.DataFrame({
            "s_a": np.random.randn(100),
            "s_b": np.random.randn(100),
        })
        kept = prune_correlated(df, ["s_a", "s_b"], threshold=0.95)
        self.assertEqual(len(kept), 2)


class TestExpandFeatures(unittest.TestCase):
    """一站式训练接口"""

    def test_expand_returns_more_features(self):
        from feature_engineer import expand_features
        np.random.seed(42)
        df = pd.DataFrame({
            "s_rsi": np.random.randn(100),
            "s_trend": np.random.randn(100),
            "s_vol": np.random.randn(100),
            "s_momentum": np.random.randn(100),
        })
        original_cols = len(df.columns)
        df_out, feature_cols = expand_features(df, save_config=False)
        # 应该比原始列多 (有交互特征)
        self.assertGreater(len(feature_cols), 4)
        # 所有 feature_cols 都在 df_out 中
        for col in feature_cols:
            self.assertIn(col, df_out.columns)

    def test_disabled_returns_raw(self):
        import feature_engineer as fe
        old_defaults = fe.DEFAULTS["enabled"]
        old_params = dict(fe._FE_PARAMS) if fe._FE_PARAMS else {}
        fe.DEFAULTS["enabled"] = False
        fe._FE_PARAMS["enabled"] = False
        try:
            df = pd.DataFrame({
                "s_rsi": np.random.randn(50),
                "s_trend": np.random.randn(50),
            })
            df_out, feature_cols = fe.expand_features(df, save_config=False)
            # 不应该有交互特征
            ix_cols = [c for c in feature_cols if c.startswith("ix_")]
            self.assertEqual(len(ix_cols), 0)
        finally:
            fe.DEFAULTS["enabled"] = old_defaults
            fe._FE_PARAMS.clear()
            fe._FE_PARAMS.update(old_params)


class TestApplySavedFeatures(unittest.TestCase):
    """预测时特征复现"""

    def test_apply_reproduces_interactions(self):
        from feature_engineer import apply_saved_features
        candidates = [
            {"factor_scores": {"s_a": 1.0, "s_b": 2.0}},
            {"factor_scores": {"s_a": 3.0, "s_b": 4.0}},
        ]
        config = {
            "interactions": [
                {"type": "multiply", "a": "s_a", "b": "s_b", "name": "ix_s_a_s_b_mul"},
            ],
            "final_features": ["s_a", "s_b", "ix_s_a_s_b_mul"],
        }
        df, features = apply_saved_features(candidates, config)
        self.assertIn("ix_s_a_s_b_mul", df.columns)
        self.assertAlmostEqual(df.iloc[0]["ix_s_a_s_b_mul"], 2.0)  # 1 * 2
        self.assertAlmostEqual(df.iloc[1]["ix_s_a_s_b_mul"], 12.0)  # 3 * 4

    def test_missing_factor_fills_zero(self):
        from feature_engineer import apply_saved_features
        candidates = [{"factor_scores": {"s_a": 1.0}}]  # s_b 缺失
        config = {
            "interactions": [
                {"type": "multiply", "a": "s_a", "b": "s_b", "name": "ix_s_a_s_b_mul"},
            ],
            "final_features": ["s_a", "s_b", "ix_s_a_s_b_mul"],
        }
        df, features = apply_saved_features(candidates, config)
        # 缺失因子填 0, 所以乘积也是 0
        self.assertEqual(df.iloc[0]["ix_s_a_s_b_mul"], 0.0)

    def test_empty_config_returns_raw(self):
        from feature_engineer import apply_saved_features
        candidates = [{"factor_scores": {"s_a": 1.0}}]
        df, features = apply_saved_features(candidates, {})
        self.assertIn("s_a", df.columns)


class TestFeatureImportanceTracking(unittest.TestCase):
    """特征重要性持久化"""

    def setUp(self):
        import feature_engineer
        self._orig_path = feature_engineer._FEATURE_CFG_PATH
        self._tmp = os.path.join(_TMPDIR, "test_feat_cfg.json")
        feature_engineer._FEATURE_CFG_PATH = self._tmp
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def tearDown(self):
        import feature_engineer
        feature_engineer._FEATURE_CFG_PATH = self._orig_path

    def test_update_importance(self):
        from feature_engineer import update_feature_importance
        update_feature_importance({"s_rsi": 0.3, "s_trend": 0.2, "ix_mul": 0.1})
        with open(self._tmp) as f:
            cfg = json.load(f)
        history = cfg.get("importance_history", [])
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["importance"]["s_rsi"], 0.3)

    def test_get_feature_trends(self):
        from feature_engineer import update_feature_importance, get_feature_trends
        # 写入两天数据
        update_feature_importance({"s_rsi": 0.3, "s_trend": 0.2})
        update_feature_importance({"s_rsi": 0.35, "s_trend": 0.15})
        trends = get_feature_trends(top_n=5)
        self.assertTrue(len(trends) > 0)
        self.assertEqual(trends[0]["feature"], "s_rsi")  # 最高重要性排第一


class TestMLIntegration(unittest.TestCase):
    """ML 模型与特征工程集成"""

    def test_build_training_data_dynamic_factors(self):
        """验证 build_training_data 能提取动态 s_* 键"""
        import ml_factor_model as ml
        # 注入测试数据
        orig_j = ml._JOURNAL_PATH
        orig_s = ml._SCORECARD_PATH
        try:
            j_path = os.path.join(_TMPDIR, "test_journal.json")
            s_path = os.path.join(_TMPDIR, "test_scorecard.json")
            ml._JOURNAL_PATH = j_path
            ml._SCORECARD_PATH = s_path
            ml._SCORECARD_DEFAULT = "force_json_mode"

            from datetime import date, timedelta
            today = date.today().isoformat()

            journal = [{
                "date": today,
                "strategy": "test",
                "regime": {"score": 0.6, "regime": "bull"},
                "picks": [{
                    "code": "000001",
                    "total_score": 0.8,
                    "factor_scores": {
                        "s_rsi": 0.5, "s_trend": 0.3, "s_custom_factor": 0.7,
                        "rsi": 45.0, "volatility": 0.02,
                    },
                }],
            }]
            scorecard = [{
                "rec_date": today,
                "code": "000001",
                "strategy": "test",
                "net_return_pct": 2.5,
            }]

            with open(j_path, "w") as f:
                json.dump(journal, f)
            with open(s_path, "w") as f:
                json.dump(scorecard, f)

            df = ml.build_training_data(lookback_days=30, strategy="test")
            self.assertEqual(len(df), 1)
            # 动态发现的 s_custom_factor 应该在 df 中
            self.assertIn("s_custom_factor", df.columns)
            self.assertAlmostEqual(df.iloc[0]["s_custom_factor"], 0.7)
        finally:
            ml._JOURNAL_PATH = orig_j
            ml._SCORECARD_PATH = orig_s
            ml._SCORECARD_DEFAULT = orig_s

    def test_train_with_feature_engineering(self):
        """验证启用特征工程后训练正常"""
        import ml_factor_model as ml
        orig_j = ml._JOURNAL_PATH
        orig_s = ml._SCORECARD_PATH
        orig_model_dir = ml._MODEL_DIR
        try:
            j_path = os.path.join(_TMPDIR, "test_journal2.json")
            s_path = os.path.join(_TMPDIR, "test_scorecard2.json")
            m_dir = os.path.join(_TMPDIR, "test_models")
            ml._JOURNAL_PATH = j_path
            ml._SCORECARD_PATH = s_path
            ml._SCORECARD_DEFAULT = "force_json_mode"
            ml._MODEL_DIR = m_dir

            from datetime import date, timedelta
            today = date.today()

            journal = []
            scorecard = []
            np.random.seed(42)
            for i in range(80):
                d = (today - timedelta(days=i)).isoformat()
                code = f"00000{i % 10}"
                fs = {
                    "s_rsi": float(np.random.randn()),
                    "s_trend": float(np.random.randn()),
                    "s_vol": float(np.random.randn()),
                    "s_momentum": float(np.random.randn()),
                    "rsi": float(np.random.uniform(20, 80)),
                    "volatility": float(np.random.uniform(0.01, 0.1)),
                }
                journal.append({
                    "date": d, "strategy": "test",
                    "regime": {"score": 0.5, "regime": "neutral"},
                    "picks": [{"code": code, "total_score": 0.5, "factor_scores": fs}],
                })
                scorecard.append({
                    "rec_date": d, "code": code, "strategy": "test",
                    "net_return_pct": float(np.random.randn() * 2),
                })

            with open(j_path, "w") as f:
                json.dump(journal, f)
            with open(s_path, "w") as f:
                json.dump(scorecard, f)

            # 启用特征工程
            old_fe = ml.ML_PARAMS.get("use_feature_engineering")
            ml.ML_PARAMS["use_feature_engineering"] = True

            result = ml.train_model(strategy="test", lookback_days=180)
            self.assertNotIn("error", result)
            self.assertGreater(result.get("n_interaction_features", 0), 0)
            self.assertGreater(len(result["features"]), 6)

            ml.ML_PARAMS["use_feature_engineering"] = old_fe if old_fe is not None else False
        finally:
            ml._JOURNAL_PATH = orig_j
            ml._SCORECARD_PATH = orig_s
            ml._SCORECARD_DEFAULT = orig_s
            ml._MODEL_DIR = orig_model_dir

    def test_predict_with_interaction_features(self):
        """验证预测时能正确复现交互特征"""
        import ml_factor_model as ml
        orig_model_dir = ml._MODEL_DIR
        try:
            m_dir = os.path.join(_TMPDIR, "test_models_pred")
            ml._MODEL_DIR = m_dir
            os.makedirs(m_dir, exist_ok=True)

            # 创建一个包含交互特征的模型
            from sklearn.ensemble import GradientBoostingClassifier
            features = ["s_rsi", "s_trend", "ix_s_rsi_s_trend_mul"]
            model = GradientBoostingClassifier(
                n_estimators=10, max_depth=2, random_state=42
            )
            np.random.seed(42)
            X = np.random.randn(50, 3)
            y = (X[:, 0] > 0).astype(int)
            model.fit(X, y)

            import pickle
            model_path = os.path.join(m_dir, "ml_test.pkl")
            with open(model_path, "wb") as f:
                pickle.dump({
                    "model": model,
                    "features": features,
                    "task": "classification",
                    "feature_config": {
                        "interactions": [
                            {"type": "multiply", "a": "s_rsi", "b": "s_trend",
                             "name": "ix_s_rsi_s_trend_mul"},
                        ],
                        "final_features": features,
                    },
                }, f)

            candidates = [
                {"factor_scores": {"s_rsi": 1.0, "s_trend": 2.0}},
                {"factor_scores": {"s_rsi": -1.0, "s_trend": 0.5}},
            ]
            result = ml.predict_scores(candidates, strategy="test")
            # 应该有 ml_score
            for c in result:
                self.assertIn("ml_score", c)
                self.assertIsInstance(c["ml_score"], float)
        finally:
            ml._MODEL_DIR = orig_model_dir


class TestGetFeatureColumnsUsesFE(unittest.TestCase):
    """_get_feature_columns 在启用FE时动态发现"""

    def test_dynamic_discovery(self):
        import ml_factor_model as ml
        df = pd.DataFrame({
            "s_rsi": np.random.randn(50),
            "s_trend": np.random.randn(50),
            "s_custom": np.random.randn(50),
            "rsi": np.random.randn(50),
            "total_score": np.random.randn(50),
        })
        # use_fe=True should discover all s_* + raw features
        cols = ml._get_feature_columns(df, use_fe=True)
        self.assertIn("s_custom", cols)
        self.assertIn("s_rsi", cols)
        self.assertIn("rsi", cols)

    def test_static_fallback(self):
        import ml_factor_model as ml
        df = pd.DataFrame({
            "rsi": np.random.randn(50),
            "s_custom_unknown": np.random.randn(50),
            "total_score": np.random.randn(50),
        })
        # use_fe=False should NOT discover s_custom_unknown
        cols = ml._get_feature_columns(df, use_fe=False)
        self.assertNotIn("s_custom_unknown", cols)
        self.assertIn("rsi", cols)


class TestRegimeAwareFeatures(unittest.TestCase):
    """Regime-Aware 交叉特征"""

    def test_regime_interactions_generated(self):
        from feature_engineer import generate_regime_interactions
        np.random.seed(42)
        df = pd.DataFrame({
            "s_rsi": np.random.randn(50),
            "s_trend": np.random.randn(50),
            "s_momentum": np.random.randn(50),
            "regime_score": np.random.uniform(0, 1, 50),
        })
        df_out, ixs = generate_regime_interactions(df, ["s_rsi", "s_trend", "s_momentum"])
        self.assertGreater(len(ixs), 0)
        for ix in ixs:
            self.assertEqual(ix["type"], "regime_cross")
            self.assertIn(ix["name"], df_out.columns)
            self.assertTrue(ix["name"].startswith("rx_"))

    def test_regime_cross_values(self):
        from feature_engineer import generate_regime_interactions
        df = pd.DataFrame({
            "s_rsi": [1.0, 2.0, 3.0],
            "regime_score": [0.8, 0.5, 0.2],
        })
        df_out, ixs = generate_regime_interactions(df, ["s_rsi"])
        self.assertEqual(len(ixs), 1)
        col = ixs[0]["name"]
        # s_rsi * regime_score = [0.8, 1.0, 0.6]
        self.assertAlmostEqual(df_out[col].iloc[0], 0.8)
        self.assertAlmostEqual(df_out[col].iloc[1], 1.0)
        self.assertAlmostEqual(df_out[col].iloc[2], 0.6)

    def test_no_regime_score_skips(self):
        from feature_engineer import generate_regime_interactions
        df = pd.DataFrame({
            "s_rsi": [1.0, 2.0],
        })
        df_out, ixs = generate_regime_interactions(df, ["s_rsi"])
        self.assertEqual(len(ixs), 0)

    def test_expand_includes_regime_cross(self):
        from feature_engineer import expand_features
        np.random.seed(42)
        df = pd.DataFrame({
            "s_rsi": np.random.randn(100),
            "s_trend": np.random.randn(100),
            "s_vol": np.random.randn(100),
            "regime_score": np.random.uniform(0, 1, 100),
        })
        df_out, feature_cols = expand_features(df, save_config=False)
        rx_cols = [c for c in feature_cols if c.startswith("rx_")]
        self.assertGreater(len(rx_cols), 0, "expand_features should include regime cross features")

    def test_apply_regime_cross(self):
        from feature_engineer import apply_saved_features
        candidates = [
            {"factor_scores": {"s_rsi": 2.0}, "regime_score": 0.7},
        ]
        config = {
            "interactions": [
                {"type": "regime_cross", "a": "s_rsi", "b": "regime_score",
                 "name": "rx_s_rsi_regime"},
            ],
            "final_features": ["s_rsi", "regime_score", "rx_s_rsi_regime"],
        }
        df, features = apply_saved_features(candidates, config)
        self.assertAlmostEqual(df.iloc[0]["rx_s_rsi_regime"], 1.4)  # 2.0 * 0.7


class TestTrainAllStrategies(unittest.TestCase):
    """策略级专属模型训练"""

    def test_train_all_with_data(self):
        import ml_factor_model as ml
        orig_j = ml._JOURNAL_PATH
        orig_s = ml._SCORECARD_PATH
        orig_m = ml._MODEL_DIR
        try:
            j_path = os.path.join(_TMPDIR, "test_journal_all.json")
            s_path = os.path.join(_TMPDIR, "test_scorecard_all.json")
            m_dir = os.path.join(_TMPDIR, "test_models_all")
            ml._JOURNAL_PATH = j_path
            ml._SCORECARD_PATH = s_path
            ml._SCORECARD_DEFAULT = "force_json"
            ml._MODEL_DIR = m_dir

            from datetime import date, timedelta
            today = date.today()
            np.random.seed(42)

            journal = []
            scorecard = []
            # 为 "集合竞价选股" 生成足够数据
            for i in range(80):
                d = (today - timedelta(days=i)).isoformat()
                code = f"00000{i % 10}"
                fs = {
                    "s_rsi": float(np.random.randn()),
                    "s_trend": float(np.random.randn()),
                    "s_vol": float(np.random.randn()),
                }
                journal.append({
                    "date": d, "strategy": "集合竞价选股",
                    "regime": {"score": 0.5, "regime": "neutral"},
                    "picks": [{"code": code, "total_score": 0.5, "factor_scores": fs}],
                })
                scorecard.append({
                    "rec_date": d, "code": code, "strategy": "集合竞价选股",
                    "net_return_pct": float(np.random.randn() * 2),
                })

            with open(j_path, "w") as f:
                json.dump(journal, f)
            with open(s_path, "w") as f:
                json.dump(scorecard, f)

            result = ml.train_all_strategies(lookback_days=180, min_samples=30)
            self.assertIn("summary", result)
            self.assertGreater(result["trained"], 0)

            # "集合竞价选股" 应该训练成功
            auction_r = result["strategy_results"].get("集合竞价选股", {})
            self.assertNotIn("error", auction_r)

            # 其他策略应该因数据不足而跳过
            self.assertGreater(result["skipped"], 0)

        finally:
            ml._JOURNAL_PATH = orig_j
            ml._SCORECARD_PATH = orig_s
            ml._SCORECARD_DEFAULT = orig_s
            ml._MODEL_DIR = orig_m

    def test_predict_with_strategy_fallback(self):
        """策略无专属模型时回退到全局"""
        import ml_factor_model as ml
        orig_m = ml._MODEL_DIR
        try:
            m_dir = os.path.join(_TMPDIR, "test_models_fallback")
            ml._MODEL_DIR = m_dir
            os.makedirs(m_dir, exist_ok=True)

            # 只创建全局模型
            from sklearn.ensemble import GradientBoostingClassifier
            import pickle
            model = GradientBoostingClassifier(n_estimators=10, max_depth=2, random_state=42)
            np.random.seed(42)
            X = np.random.randn(50, 2)
            y = (X[:, 0] > 0).astype(int)
            model.fit(X, y)

            path = os.path.join(m_dir, "ml_all.pkl")
            with open(path, "wb") as f:
                pickle.dump({"model": model, "features": ["s_rsi", "s_trend"], "task": "classification"}, f)

            candidates = [{"factor_scores": {"s_rsi": 1.0, "s_trend": 0.5}}]
            result = ml.predict_scores(candidates, strategy="集合竞价选股")
            # 应该回退到全局模型而不是返回 0
            self.assertNotEqual(result[0]["ml_score"], 0)

        finally:
            ml._MODEL_DIR = orig_m


class TestFactorScoresInStrategies(unittest.TestCase):
    """验证各策略模块返回 factor_scores"""

    def test_strategy_result_format(self):
        """检查策略结果格式应该包含 factor_scores 键"""
        # 这个测试验证的是代码结构, 不需要实际运行策略
        import ast
        strategies = [
            ("mean_reversion_strategy.py", "get_dip_buy_recommendations"),
            ("mean_reversion_strategy.py", "get_consolidation_recommendations"),
            ("trend_sector_strategy.py", "get_trend_follow_recommendations"),
            ("trend_sector_strategy.py", "get_sector_rotation_recommendations"),
            ("news_event_strategy.py", "get_news_event_recommendations"),
            ("volume_breakout_strategy.py", "get_breakout_recommendations"),
            ("intraday_strategy.py", "get_auction_recommendations"),
            ("intraday_strategy.py", "get_afternoon_recommendations"),
        ]
        base_dir = os.path.join(os.path.dirname(__file__), "..")
        for filename, func_name in strategies:
            filepath = os.path.join(base_dir, filename)
            with open(filepath) as f:
                source = f.read()
            self.assertIn("factor_scores", source,
                          f"{filename} 应该包含 factor_scores")


if __name__ == "__main__":
    unittest.main()
