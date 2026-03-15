"""ml_factor_model.py 单元测试"""

import os
import sys
import json
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildTrainingData:
    """训练数据构建"""

    def test_empty_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ml_factor_model._JOURNAL_PATH",
                            str(tmp_path / "j.json"))
        monkeypatch.setattr("ml_factor_model._SCORECARD_PATH",
                            str(tmp_path / "s.json"))
        from ml_factor_model import build_training_data
        df = build_training_data(30)
        assert len(df) == 0

    def test_with_data(self, tmp_path, monkeypatch):
        today = date.today().isoformat()
        journal = [{
            "date": today,
            "strategy": "放量突破选股",
            "regime": {"regime": "bull", "score": 70, "signals": {}},
            "picks": [
                {"code": "000001", "name": "平安银行", "total_score": 0.8,
                 "factor_scores": {"rsi": 55, "vol_ratio": 2.5, "volatility": 0.25}},
                {"code": "000002", "name": "万科A", "total_score": 0.6,
                 "factor_scores": {"rsi": 48, "vol_ratio": 1.8, "volatility": 0.30}},
            ],
        }]
        scorecard = [
            {"rec_date": today, "code": "000001", "strategy": "放量突破选股",
             "net_return_pct": 1.5, "result": "win"},
            {"rec_date": today, "code": "000002", "strategy": "放量突破选股",
             "net_return_pct": -0.8, "result": "loss"},
        ]

        jp = tmp_path / "j.json"
        sp = tmp_path / "s.json"
        jp.write_text(json.dumps(journal))
        sp.write_text(json.dumps(scorecard))
        monkeypatch.setattr("ml_factor_model._JOURNAL_PATH", str(jp))
        monkeypatch.setattr("ml_factor_model._SCORECARD_PATH", str(sp))

        from ml_factor_model import build_training_data
        df = build_training_data(30)
        assert len(df) == 2
        assert "target" in df.columns
        assert "rsi" in df.columns


class TestCreateModel:
    """模型创建"""

    def test_regression(self):
        from ml_factor_model import _create_model
        model = _create_model("regression")
        assert hasattr(model, "fit")
        assert hasattr(model, "predict")

    def test_classification(self):
        from ml_factor_model import _create_model
        model = _create_model("classification")
        assert hasattr(model, "fit")
        assert hasattr(model, "predict_proba")


class TestTrainModel:
    """模型训练"""

    def test_insufficient_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ml_factor_model._JOURNAL_PATH",
                            str(tmp_path / "j.json"))
        monkeypatch.setattr("ml_factor_model._SCORECARD_PATH",
                            str(tmp_path / "s.json"))
        from ml_factor_model import train_model
        result = train_model()
        assert "error" in result

    def test_train_with_synthetic_data(self, tmp_path, monkeypatch):
        """用合成数据测试完整训练流程"""
        rng = np.random.RandomState(42)
        n = 100
        today = date.today()

        journal = []
        scorecard = []
        for i in range(n):
            d = (today - timedelta(days=n - i)).isoformat()
            code = f"{600000 + i % 20:06d}"
            rsi = rng.uniform(30, 70)
            vol = rng.uniform(1, 4)
            ret = rsi * 0.02 + vol * 0.3 + rng.normal(0, 1)

            journal.append({
                "date": d,
                "strategy": "放量突破选股",
                "regime": {"regime": "bull", "score": 60, "signals": {}},
                "picks": [{
                    "code": code, "name": f"stock_{i}",
                    "total_score": rng.uniform(0, 1),
                    "factor_scores": {
                        "rsi": rsi, "vol_ratio": vol,
                        "volatility": rng.uniform(0.1, 0.5),
                        "pullback_5d": rng.uniform(-0.1, 0),
                        "ret_3d": rng.uniform(-0.05, 0.05),
                        "pct_chg": rng.uniform(-3, 5),
                    },
                }],
            })
            scorecard.append({
                "rec_date": d, "code": code, "strategy": "放量突破选股",
                "net_return_pct": round(ret, 2),
                "result": "win" if ret > 0 else "loss",
            })

        jp = tmp_path / "j.json"
        sp = tmp_path / "s.json"
        jp.write_text(json.dumps(journal))
        sp.write_text(json.dumps(scorecard))
        monkeypatch.setattr("ml_factor_model._JOURNAL_PATH", str(jp))
        monkeypatch.setattr("ml_factor_model._SCORECARD_PATH", str(sp))
        monkeypatch.setattr("ml_factor_model._MODEL_DIR", str(tmp_path / "models"))

        from ml_factor_model import train_model
        result = train_model(lookback_days=200)
        assert "error" not in result
        assert result["training_samples"] == n
        assert len(result["features"]) > 0
        assert "metrics" in result
        assert "feature_importance" in result


class TestPredictScores:
    """预测得分"""

    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ml_factor_model._MODEL_DIR", str(tmp_path))
        from ml_factor_model import predict_scores
        candidates = [
            {"code": "000001", "factor_scores": {"rsi": 55, "vol_ratio": 2.5}},
        ]
        result = predict_scores(candidates)
        assert result[0]["ml_score"] == 0  # 无模型则返回0

    def test_with_model(self, tmp_path, monkeypatch):
        """训练后预测"""
        import pickle
        from sklearn.ensemble import GradientBoostingRegressor

        model = GradientBoostingRegressor(n_estimators=10, max_depth=3, random_state=42)
        X = np.random.randn(50, 3)
        y = X[:, 0] * 0.5 + X[:, 1] * 0.3 + np.random.randn(50) * 0.1
        model.fit(X, y)

        model_dir = tmp_path / "models"
        model_dir.mkdir()
        model_path = model_dir / "ml_all.pkl"
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": model,
                "features": ["rsi", "vol_ratio", "volatility"],
                "task": "regression",
            }, f)

        monkeypatch.setattr("ml_factor_model._MODEL_DIR", str(model_dir))
        from ml_factor_model import predict_scores
        candidates = [
            {"code": "000001", "factor_scores": {"rsi": 55, "vol_ratio": 2.5, "volatility": 0.25}},
            {"code": "000002", "factor_scores": {"rsi": 30, "vol_ratio": 1.0, "volatility": 0.40}},
        ]
        result = predict_scores(candidates)
        assert all("ml_score" in c for c in result)
        # 不同输入应该有不同分数
        assert result[0]["ml_score"] != result[1]["ml_score"]


class TestFuseScores:
    """分数融合"""

    def test_basic_fusion(self):
        from ml_factor_model import fuse_scores
        candidates = [
            {"code": "000001", "ml_score": 0.8, "total_score": 0.6},
            {"code": "000002", "ml_score": 0.3, "total_score": 0.9},
        ]
        result = fuse_scores(candidates, ml_weight=0.5)
        assert all("fused_score" in c for c in result)

    def test_zero_ml_weight(self):
        """ml_weight=0 时, ML 排名不影响, 排序完全由规则分决定"""
        from ml_factor_model import fuse_scores
        candidates = [
            {"code": "000001", "ml_score": 0.8, "total_score": 0.9},
            {"code": "000002", "ml_score": 0.2, "total_score": 0.3},
        ]
        result = fuse_scores(candidates, ml_weight=0.0)
        # 规则分高的应该排在前面 (fused_score 更高)
        scores = {c["code"]: c["fused_score"] for c in result}
        assert scores["000001"] > scores["000002"]


class TestMLReport:
    """报告生成"""

    def test_report_format(self):
        from ml_factor_model import generate_ml_report
        eval_result = {
            "strategy": "all",
            "timestamp": "2026-03-02T22:00:00",
            "task": "regression",
            "n_windows": 2,
            "windows": [
                {"window": 1, "train_samples": 60, "test_samples": 20,
                 "is_r2": 0.35, "oos_r2": 0.12,
                 "is_direction_acc": 0.65, "oos_direction_acc": 0.55},
            ],
            "summary": {
                "avg_is_r2": 0.35, "avg_oos_r2": 0.12,
                "avg_is_direction_acc": 0.65, "avg_oos_direction_acc": 0.55,
                "r2_decay": 0.23, "model_useful": True,
            },
        }
        report = generate_ml_report(eval_result)
        assert "ML" in report
        assert "R²" in report
        assert "方向准确率" in report

    def test_report_error(self):
        from ml_factor_model import generate_ml_report
        result = {
            "strategy": "test", "timestamp": "2026-01-01",
            "task": "regression", "n_windows": 0, "windows": [],
            "summary": {"error": "no data"},
        }
        report = generate_ml_report(result)
        assert "错误" in report


class TestMLSummary:
    """汇总计算"""

    def test_regression_summary(self):
        from ml_factor_model import _calc_ml_summary
        windows = [
            {"is_r2": 0.4, "oos_r2": 0.15, "is_direction_acc": 0.65, "oos_direction_acc": 0.55},
            {"is_r2": 0.35, "oos_r2": 0.10, "is_direction_acc": 0.60, "oos_direction_acc": 0.53},
        ]
        summary = _calc_ml_summary(windows, "regression")
        assert "avg_is_r2" in summary
        assert "avg_oos_r2" in summary
        assert "model_useful" in summary

    def test_empty(self):
        from ml_factor_model import _calc_ml_summary
        summary = _calc_ml_summary([], "regression")
        assert "error" in summary


class TestGetFeatureColumns:
    """特征列选择"""

    def test_basic(self):
        from ml_factor_model import _get_feature_columns
        df = pd.DataFrame({
            "rsi": [50, 55, 60, 45, 52],
            "vol_ratio": [2.0, 1.5, 3.0, 2.5, 1.8],
            "empty_col": [np.nan] * 5,
            "target": [1.0, -0.5, 0.3, -0.2, 0.8],
        })
        cols = _get_feature_columns(df)
        assert "rsi" in cols
        assert "vol_ratio" in cols
        assert "empty_col" not in cols
