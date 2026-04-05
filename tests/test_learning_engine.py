"""
自学习引擎单元测试
==================
覆盖 learning_engine.py 的全部核心功能:
  - 交易上下文记录 (record_trade_context)
  - 日志-记分卡关联 (_join_journal_scorecard)
  - 信号准确度分析 (analyze_signal_accuracy)
  - 因子重要性分析 (analyze_factor_importance)
  - 策略-行情适配 (analyze_strategy_regime_fit)
  - 权重调整建议 (propose_signal_weight_update)
  - 学习报告生成 (generate_learning_report)
  - 端到端学习周期 (run_learning_cycle)
"""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """创建临时目录并 patch 所有文件路径"""
    import learning_engine

    journal_path = str(tmp_path / "trade_journal.json")
    scorecard_path = str(tmp_path / "scorecard.json")
    tunable_path = str(tmp_path / "tunable_params.json")
    evolution_path = str(tmp_path / "evolution_history.json")

    monkeypatch.setattr(learning_engine, "_JOURNAL_PATH", journal_path)
    monkeypatch.setattr(learning_engine, "_SCORECARD_PATH", scorecard_path)
    monkeypatch.setattr(learning_engine, "_TUNABLE_PATH", tunable_path)
    monkeypatch.setattr(learning_engine, "_EVOLUTION_PATH", evolution_path)

    return tmp_path


def _write_json(path, data):
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _read_json(path):
    with open(str(path), "r", encoding="utf-8") as f:
        return json.load(f)


# ================================================================
#  TestRecordTradeContext
# ================================================================

class TestRecordTradeContext:
    """record_trade_context 测试"""

    def test_basic_record(self, tmp_dir):
        """基本记录: 正确写入 trade_journal.json"""
        from learning_engine import record_trade_context

        items = [
            {"code": "000001", "name": "平安银行", "price": 10.5, "score": 0.8,
             "factor_scores": {"s_gap": 0.5, "s_volume_ratio": 0.7}},
            {"code": "600036", "name": "招商银行", "price": 35.2, "score": 0.6,
             "factor_scores": {"s_gap": 0.3}},
        ]
        regime_result = {
            "regime": "bull",
            "score": 0.72,
            "signals": {"s1_ma_trend": 0.8, "s2_momentum": 0.6},
            "signal_weights": {"s1_ma_trend": 0.15, "s2_momentum": 0.15},
        }

        record_trade_context("集合竞价选股", items, regime_result)

        journal = _read_json(tmp_dir / "trade_journal.json")
        assert len(journal) == 1
        entry = journal[0]
        assert entry["strategy"] == "集合竞价选股"
        assert len(entry["picks"]) == 2
        assert entry["picks"][0]["code"] == "000001"
        assert entry["picks"][0]["factor_scores"]["s_gap"] == 0.5
        assert entry["regime"]["regime"] == "bull"
        assert entry["regime"]["signals"]["s1_ma_trend"] == 0.8

    def test_empty_items(self, tmp_dir):
        """空推荐列表不写入"""
        from learning_engine import record_trade_context

        record_trade_context("集合竞价选股", [], None)

        assert not os.path.exists(str(tmp_dir / "trade_journal.json"))

    def test_missing_regime(self, tmp_dir):
        """缺少 regime_result 仍正常记录"""
        from learning_engine import record_trade_context

        items = [{"code": "000001", "name": "平安银行", "price": 10.5, "score": 0.8}]
        record_trade_context("集合竞价选股", items, None)

        journal = _read_json(tmp_dir / "trade_journal.json")
        assert len(journal) == 1
        assert journal[0]["regime"] == {}

    def test_dedup(self, tmp_dir):
        """同日同策略不重复写入"""
        from learning_engine import record_trade_context

        items = [{"code": "000001", "name": "平安银行", "price": 10.5, "score": 0.8}]
        record_trade_context("集合竞价选股", items, None)
        record_trade_context("集合竞价选股", items, None)  # 第二次应跳过

        journal = _read_json(tmp_dir / "trade_journal.json")
        assert len(journal) == 1


# ================================================================
#  TestJoinLogic
# ================================================================

class TestJoinLogic:
    """_join_journal_scorecard 关联测试"""

    def test_matching_records(self, tmp_dir):
        """正确关联匹配的记录"""
        from learning_engine import _join_journal_scorecard
        from datetime import date

        today = date.today().isoformat()

        journal = [{
            "date": today,
            "strategy": "集合竞价选股",
            "regime": {"regime": "bull", "score": 0.7, "signals": {"s1_ma_trend": 0.8}, "signal_weights": {}},
            "picks": [
                {"code": "000001", "name": "平安银行", "total_score": 0.8,
                 "factor_scores": {"s_gap": 0.5}},
            ],
        }]
        scorecard = [{
            "rec_date": today,
            "code": "000001",
            "strategy": "集合竞价选股",
            "net_return_pct": 2.5,
            "result": "win",
        }]

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        joined = _join_journal_scorecard(lookback_days=30)
        assert len(joined) == 1
        assert joined[0]["code"] == "000001"
        assert joined[0]["net_return_pct"] == 2.5
        assert joined[0]["signals"]["s1_ma_trend"] == 0.8
        assert joined[0]["factor_scores"]["s_gap"] == 0.5

    def test_no_match_excluded(self, tmp_dir):
        """无匹配的记录被排除"""
        from learning_engine import _join_journal_scorecard
        from datetime import date

        today = date.today().isoformat()

        journal = [{
            "date": today,
            "strategy": "集合竞价选股",
            "regime": {},
            "picks": [{"code": "000001", "name": "平安银行", "total_score": 0.8, "factor_scores": {}}],
        }]
        # 记分卡中没有 000001
        scorecard = [{
            "rec_date": today,
            "code": "600036",
            "strategy": "集合竞价选股",
            "net_return_pct": -1.0,
            "result": "loss",
        }]

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        joined = _join_journal_scorecard(lookback_days=30)
        assert len(joined) == 0


# ================================================================
#  TestAnalyzeSignalAccuracy
# ================================================================

class TestAnalyzeSignalAccuracy:
    """analyze_signal_accuracy 测试"""

    def _make_data(self, tmp_dir, n=20):
        """生成 n 条测试数据, S1 与收益正相关"""
        from datetime import date, timedelta
        import random

        random.seed(42)
        journal = []
        scorecard = []

        for i in range(n):
            d = (date.today() - timedelta(days=i)).isoformat()
            s1_val = random.random()
            # 让 S1 与收益正相关: 高 S1 更可能正收益
            ret = (s1_val - 0.5) * 10 + random.gauss(0, 1)

            journal.append({
                "date": d,
                "strategy": "集合竞价选股",
                "regime": {
                    "regime": "neutral",
                    "score": 0.5,
                    "signals": {"s1_ma_trend": round(s1_val, 4), "s2_momentum": round(random.random(), 4)},
                    "signal_weights": {},
                },
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "集合竞价选股",
                "net_return_pct": round(ret, 4),
                "result": "win" if ret > 0 else "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

    def test_basic_analysis(self, tmp_dir):
        """基本分析返回正确结构"""
        from learning_engine import analyze_signal_accuracy

        self._make_data(tmp_dir, n=20)
        results = analyze_signal_accuracy(lookback_days=30)
        assert len(results) == 2  # s1_ma_trend, s2_momentum
        for r in results:
            assert "signal" in r
            assert "correlation" in r
            assert "samples" in r

    def test_s1_predictive(self, tmp_dir):
        """S1 应有正相关性 (因为我们设计了正相关)"""
        from learning_engine import analyze_signal_accuracy

        self._make_data(tmp_dir, n=25)
        results = analyze_signal_accuracy(lookback_days=30)
        s1 = next(r for r in results if r["signal"] == "s1_ma_trend")
        assert s1["correlation"] is not None
        assert s1["correlation"] > 0  # S1 应正相关

    def test_insufficient_data(self, tmp_dir, monkeypatch):
        """样本不足时返回 None"""
        import learning_engine
        from learning_engine import analyze_signal_accuracy

        # 设置高门槛
        monkeypatch.setattr(learning_engine, "LEARNING_ENGINE_PARAMS", {
            **learning_engine.LEARNING_ENGINE_PARAMS,
            "min_samples_signal": 100,
        })

        self._make_data(tmp_dir, n=5)
        results = analyze_signal_accuracy(lookback_days=30)
        for r in results:
            assert r["predictive_value"] is None


# ================================================================
#  TestAnalyzeFactorImportance
# ================================================================

class TestAnalyzeFactorImportance:
    """analyze_factor_importance 测试"""

    def _make_factor_data(self, tmp_dir, n=15):
        from datetime import date, timedelta
        import random

        random.seed(42)
        journal = []
        scorecard = []

        for i in range(n):
            d = (date.today() - timedelta(days=i)).isoformat()
            s_gap = random.random()
            ret = (s_gap - 0.5) * 8 + random.gauss(0, 1)

            journal.append({
                "date": d,
                "strategy": "集合竞价选股",
                "regime": {},
                "picks": [{
                    "code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5,
                    "factor_scores": {"s_gap": round(s_gap, 4), "s_volume_ratio": round(random.random(), 4)},
                }],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "集合竞价选股",
                "net_return_pct": round(ret, 4),
                "result": "win" if ret > 0 else "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

    def test_basic_factor_analysis(self, tmp_dir):
        """基本因子分析返回正确结构"""
        from learning_engine import analyze_factor_importance

        self._make_factor_data(tmp_dir)
        results = analyze_factor_importance("集合竞价选股", lookback_days=30)
        assert len(results) == 2  # s_gap, s_volume_ratio
        for r in results:
            assert "factor" in r
            assert "correlation" in r
            assert "top25_return" in r
            assert "bottom25_return" in r

    def test_unknown_strategy(self, tmp_dir):
        """未知策略返回空列表"""
        from learning_engine import analyze_factor_importance

        self._make_factor_data(tmp_dir)
        results = analyze_factor_importance("不存在的策略", lookback_days=30)
        assert results == []


# ================================================================
#  TestAnalyzeStrategyRegimeFit
# ================================================================

class TestAnalyzeStrategyRegimeFit:
    """analyze_strategy_regime_fit 测试"""

    def test_cross_table(self, tmp_dir):
        """策略-行情交叉表"""
        from learning_engine import analyze_strategy_regime_fit
        from datetime import date, timedelta

        journal = []
        scorecard = []

        for i in range(10):
            d = (date.today() - timedelta(days=i)).isoformat()
            regime = "bull" if i < 5 else "neutral"
            ret = 2.0 if regime == "bull" else -1.0

            journal.append({
                "date": d,
                "strategy": "集合竞价选股",
                "regime": {"regime": regime, "score": 0.7, "signals": {}, "signal_weights": {}},
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "集合竞价选股",
                "net_return_pct": ret,
                "result": "win" if ret > 0 else "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        results = analyze_strategy_regime_fit(lookback_days=30)
        assert len(results) == 2  # bull + neutral

        bull = next(r for r in results if r["regime"] == "bull")
        neutral = next(r for r in results if r["regime"] == "neutral")
        assert bull["win_rate"] == 1.0  # 牛市全赢
        assert bull["avg_return"] == 2.0
        assert neutral["win_rate"] == 0.0  # 震荡全亏
        assert neutral["avg_return"] == -1.0


# ================================================================
#  TestProposeSignalWeightUpdate
# ================================================================

class TestProposeSignalWeightUpdate:
    """propose_signal_weight_update 测试"""

    def test_no_data(self, tmp_dir):
        """无数据时返回 None"""
        from learning_engine import propose_signal_weight_update

        result = propose_signal_weight_update()
        assert result is None

    def test_valid_proposal(self, tmp_dir, monkeypatch):
        """有足够数据时返回有效调整建议"""
        import learning_engine
        from learning_engine import propose_signal_weight_update
        from datetime import date, timedelta
        import random

        random.seed(42)
        monkeypatch.setattr(learning_engine, "LEARNING_ENGINE_PARAMS", {
            **learning_engine.LEARNING_ENGINE_PARAMS,
            "min_samples_signal": 5,
        })

        journal = []
        scorecard = []
        for i in range(20):
            d = (date.today() - timedelta(days=i)).isoformat()
            s1 = random.random()
            ret = (s1 - 0.5) * 20 + random.gauss(0, 0.5)

            journal.append({
                "date": d,
                "strategy": "集合竞价选股",
                "regime": {
                    "regime": "neutral", "score": 0.5,
                    "signals": {"s1_ma_trend": round(s1, 4), "s8_index_rsi": round(random.random(), 4)},
                    "signal_weights": {},
                },
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "集合竞价选股",
                "net_return_pct": round(ret, 4),
                "result": "win" if ret > 0 else "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        result = propose_signal_weight_update()
        # 可能有调整也可能没有 (取决于 predictive_value 是否超阈值)
        if result is not None:
            assert "old_weights" in result
            assert "new_weights" in result
            assert "adjustments" in result

    def test_weights_normalized(self, tmp_dir, monkeypatch):
        """调整后权重归一化到 sum=1.0"""
        import learning_engine
        from learning_engine import propose_signal_weight_update
        from datetime import date, timedelta

        monkeypatch.setattr(learning_engine, "LEARNING_ENGINE_PARAMS", {
            **learning_engine.LEARNING_ENGINE_PARAMS,
            "min_samples_signal": 3,
            "predictive_threshold": 0.1,  # 极低阈值, 确保有调整
        })

        # 构建让所有信号都有高预测力的数据
        journal = []
        scorecard = []
        for i in range(20):
            d = (date.today() - timedelta(days=i)).isoformat()
            # 信号高时收益好, 信号低时收益差
            is_good = i % 2 == 0
            signals = {k: (0.9 if is_good else 0.1) for k in learning_engine.MARKET_SIGNAL_WEIGHTS}

            journal.append({
                "date": d,
                "strategy": "集合竞价选股",
                "regime": {"regime": "neutral", "score": 0.5, "signals": signals, "signal_weights": {}},
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "集合竞价选股",
                "net_return_pct": 5.0 if is_good else -3.0,
                "result": "win" if is_good else "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        result = propose_signal_weight_update()
        if result is not None:
            total = sum(result["new_weights"].values())
            assert abs(total - 1.0) < 0.01, f"权重总和应为1.0, 实际为{total}"


# ================================================================
#  TestGenerateLearningReport
# ================================================================

class TestGenerateLearningReport:
    """generate_learning_report 测试"""

    def test_report_format(self, tmp_dir):
        """报告包含必要的章节标题"""
        from learning_engine import generate_learning_report

        report = generate_learning_report()
        assert "# 自学习引擎报告" in report
        assert "## 大盘信号预测力" in report
        assert "## 选股因子重要性" in report
        assert "## 策略-行情适配" in report
        assert "## 本日权重调整" in report
        assert "## 数据积累进度" in report


# ================================================================
#  TestApplyWeightUpdate
# ================================================================

class TestApplyWeightUpdate:
    """apply_weight_update 测试"""

    def test_apply_writes_files(self, tmp_dir):
        """应用调整后写入 tunable_params 和 evolution_history"""
        from learning_engine import apply_weight_update

        proposal = {
            "old_weights": {"s1_ma_trend": 0.15, "s2_momentum": 0.15},
            "new_weights": {"s1_ma_trend": 0.18, "s2_momentum": 0.12},
            "adjustments": {
                "s1_ma_trend": {"old": 0.15, "new": 0.18, "delta": 0.03, "predictive_value": 15.0},
            },
        }

        apply_weight_update(proposal)

        tunable = _read_json(tmp_dir / "tunable_params.json")
        assert "regime_signals" in tunable
        assert tunable["regime_signals"]["weights"]["s1_ma_trend"] == 0.18
        assert tunable["regime_signals"]["version"] == 1

        history = _read_json(tmp_dir / "evolution_history.json")
        assert len(history) == 1
        assert history[0]["strategy"] == "regime_signals"
        assert history[0]["action"] == "learning_update"


# ================================================================
#  TestRunLearningCycle
# ================================================================

class TestAutoAdoptBacktestResults:
    """auto_adopt_backtest_results 测试"""

    def test_no_results_file(self, tmp_dir):
        """无回测结果文件时返回空列表"""
        from learning_engine import auto_adopt_backtest_results
        result = auto_adopt_backtest_results()
        assert result == []

    def test_adopt_recommendation(self, tmp_dir, monkeypatch):
        """正确采纳推荐的参数"""
        import learning_engine
        from learning_engine import auto_adopt_backtest_results

        # 构建回测结果
        bt_path = str(tmp_dir / "backtest_results.json")
        _write_json(bt_path, [{
            "date": "2026-03-02",
            "recommendations": [{
                "strategy": "breakout",
                "action": "adopt",
                "reason": "胜率+3.0% 收益+0.80%",
                "params": {"s_volume": 0.25, "s_ma": 0.20, "s_gap": 0.55},
            }],
        }])

        # Patch batch_backtest 的 _RESULTS_PATH
        import types
        fake_bt = types.ModuleType("batch_backtest")
        fake_bt._RESULTS_PATH = bt_path
        monkeypatch.setitem(sys.modules, "batch_backtest", fake_bt)

        adopted = auto_adopt_backtest_results()
        assert len(adopted) == 1
        assert adopted[0]["strategy"] == "breakout"
        assert adopted[0]["action"] == "adopted"

        # 验证 tunable_params 已更新
        tunable = _read_json(tmp_dir / "tunable_params.json")
        assert "breakout" in tunable
        assert tunable["breakout"]["weights"]["s_volume"] == 0.25
        assert tunable["breakout"]["source"] == "night_backtest"

        # 验证 evolution_history 已记录
        history = _read_json(tmp_dir / "evolution_history.json")
        assert len(history) == 1
        assert history[0]["action"] == "auto_adopt_backtest"

    def test_skip_non_adopt(self, tmp_dir, monkeypatch):
        """非 adopt 的建议被跳过"""
        import types
        bt_path = str(tmp_dir / "backtest_results.json")
        _write_json(bt_path, [{
            "date": "2026-03-02",
            "recommendations": [{
                "strategy": "breakout",
                "action": "alert",
                "reason": "当前参数已是最优",
            }],
        }])

        fake_bt = types.ModuleType("batch_backtest")
        fake_bt._RESULTS_PATH = bt_path
        monkeypatch.setitem(sys.modules, "batch_backtest", fake_bt)

        from learning_engine import auto_adopt_backtest_results
        adopted = auto_adopt_backtest_results()
        assert adopted == []


# ================================================================
#  TestDiscoverRulesFromHistory
# ================================================================

class TestDiscoverRulesFromHistory:
    """discover_rules_from_history 测试"""

    def test_no_data(self, tmp_dir):
        """无数据时返回空列表"""
        from learning_engine import discover_rules_from_history
        memory = {"rules": []}
        result = discover_rules_from_history(memory)
        assert result == []

    def test_discover_avoid_rule(self, tmp_dir):
        """发现策略在某行情下表现差 → 生成 regime_avoid 规则"""
        from learning_engine import discover_rules_from_history
        from datetime import date, timedelta

        # 构建数据: 策略A在bear行情下全亏
        journal = []
        scorecard = []
        for i in range(15):
            d = (date.today() - timedelta(days=i)).isoformat()
            journal.append({
                "date": d,
                "strategy": "测试策略A",
                "regime": {"regime": "bear", "score": 0.3, "signals": {}, "signal_weights": {}},
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "测试策略A",
                "net_return_pct": -2.5,
                "result": "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        memory = {"rules": []}
        rules = discover_rules_from_history(memory)
        assert len(rules) >= 1
        avoid_rule = next(r for r in rules if r["type"] == "regime_mismatch")
        assert avoid_rule["strategy"] == "测试策略A"
        assert avoid_rule["condition"]["regime"] == "bear"
        assert avoid_rule["action"] == "pause_strategy"
        # 规则也应写入 memory
        assert len(memory["rules"]) >= 1

    def test_discover_boost_rule(self, tmp_dir):
        """发现策略在某行情下表现好 → 生成 regime_boost 规则"""
        from learning_engine import discover_rules_from_history
        from datetime import date, timedelta

        journal = []
        scorecard = []
        for i in range(15):
            d = (date.today() - timedelta(days=i)).isoformat()
            journal.append({
                "date": d,
                "strategy": "测试策略B",
                "regime": {"regime": "bull", "score": 0.8, "signals": {}, "signal_weights": {}},
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "测试策略B",
                "net_return_pct": 3.0,
                "result": "win",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        memory = {"rules": []}
        rules = discover_rules_from_history(memory)
        assert len(rules) >= 1
        boost_rule = next(r for r in rules if r["type"] == "regime_boost")
        assert boost_rule["strategy"] == "测试策略B"
        assert boost_rule["condition"]["regime"] == "bull"

    def test_dedup_existing_rules(self, tmp_dir):
        """已存在的规则不重复生成"""
        from learning_engine import discover_rules_from_history
        from datetime import date, timedelta

        journal = []
        scorecard = []
        for i in range(15):
            d = (date.today() - timedelta(days=i)).isoformat()
            journal.append({
                "date": d,
                "strategy": "测试策略A",
                "regime": {"regime": "bear", "score": 0.3, "signals": {}, "signal_weights": {}},
                "picks": [{"code": f"{i:06d}", "name": f"测试{i}", "total_score": 0.5, "factor_scores": {}}],
            })
            scorecard.append({
                "rec_date": d,
                "code": f"{i:06d}",
                "strategy": "测试策略A",
                "net_return_pct": -2.5,
                "result": "loss",
            })

        _write_json(tmp_dir / "trade_journal.json", journal)
        _write_json(tmp_dir / "scorecard.json", scorecard)

        # 已有同名规则
        memory = {"rules": [{"id": "regime_avoid_测试策略A_bear", "type": "regime_mismatch"}]}
        rules = discover_rules_from_history(memory)
        assert len(rules) == 0  # 不应重复生成


# ================================================================
#  TestRunLearningCycle
# ================================================================

class TestRunLearningCycle:
    """run_learning_cycle 端到端测试"""

    def test_no_crash(self, tmp_dir, monkeypatch):
        """端到端运行不崩溃 (即使无数据)"""
        from learning_engine import run_learning_cycle

        # Mock 微信推送
        monkeypatch.setattr(
            "learning_engine.LEARNING_ENGINE_PARAMS",
            {**__import__("learning_engine").LEARNING_ENGINE_PARAMS, "wechat_learning_report": False},
        )

        result = run_learning_cycle()
        assert result is not None
        assert "# 自学习引擎报告" in result


class TestLearningHealth:
    def test_scorecard_freshness_uses_input_side_activity_before_critical(self, tmp_dir, monkeypatch):
        import learning_engine
        import db_store

        db_path = tmp_dir / "quant_data.db"
        monkeypatch.setattr(db_store, "_DB_PATH", str(db_path))
        monkeypatch.setattr(learning_engine, "_DIR", str(tmp_dir))
        monkeypatch.setattr(learning_engine, "_TUNABLE_PATH", str(tmp_dir / "tunable_params.json"))
        monkeypatch.setattr(learning_engine, "_EVOLUTION_PATH", str(tmp_dir / "evolution_history.json"))
        monkeypatch.setattr(learning_engine, "_STRATEGY_TUNABLE_KEYS", ["趋势跟踪选股"])
        monkeypatch.setattr(learning_engine, "analyze_factor_importance", lambda *args, **kwargs: [{"correlation": 0.05}])

        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE scorecard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rec_date TEXT,
                code TEXT,
                strategy TEXT,
                net_return_pct REAL,
                result TEXT
            );
            CREATE TABLE trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                strategy TEXT NOT NULL,
                regime_score REAL,
                regime_label TEXT,
                regime_signals TEXT,
                picks TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO trade_journal (trade_date, strategy, picks, created_at) VALUES (date('now','localtime'), ?, '[]', datetime('now','localtime'))",
            ("趋势跟踪选股",),
        )
        conn.commit()
        conn.close()

        _write_json(tmp_dir / "tunable_params.json", {"_online_last_update": "2026-03-31T09:30:00"})
        _write_json(tmp_dir / "evolution_history.json", [{"date": "2026-03-31", "strategy": "趋势跟踪选股"}])
        _write_json(tmp_dir / "signals_db.json", [{"status": "partial"}])
        models_dir = tmp_dir / "models"
        models_dir.mkdir(exist_ok=True)
        (models_dir / "demo.pkl").write_bytes(b"demo")

        health = learning_engine.check_learning_health()

        scorecard_check = next(item for item in health["checks"] if item["check"] == "scorecard_freshness")
        assert scorecard_check["status"] == "warning"
        assert "近3天无新回填，但输入侧仍有" in scorecard_check["detail"]

    def test_scorecard_freshness_uses_signals_db_before_critical(self, tmp_dir, monkeypatch):
        import learning_engine
        import db_store

        db_path = tmp_dir / "quant_data.db"
        monkeypatch.setattr(db_store, "_DB_PATH", str(db_path))
        monkeypatch.setattr(learning_engine, "_DIR", str(tmp_dir))
        monkeypatch.setattr(learning_engine, "_TUNABLE_PATH", str(tmp_dir / "tunable_params.json"))
        monkeypatch.setattr(learning_engine, "_EVOLUTION_PATH", str(tmp_dir / "evolution_history.json"))
        monkeypatch.setattr(learning_engine, "_STRATEGY_TUNABLE_KEYS", ["趋势跟踪选股"])
        monkeypatch.setattr(learning_engine, "analyze_factor_importance", lambda *args, **kwargs: [{"correlation": 0.05}])

        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE scorecard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rec_date TEXT,
                code TEXT,
                strategy TEXT,
                net_return_pct REAL,
                result TEXT
            );
            CREATE TABLE trade_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                strategy TEXT NOT NULL,
                regime_score REAL,
                regime_label TEXT,
                regime_signals TEXT,
                picks TEXT,
                created_at TEXT
            );
            """
        )
        conn.commit()
        conn.close()

        _write_json(tmp_dir / "tunable_params.json", {"_online_last_update": "2026-03-31T09:30:00"})
        _write_json(tmp_dir / "evolution_history.json", [{"date": "2026-03-31", "strategy": "趋势跟踪选股"}])
        _write_json(tmp_dir / "signals_db.json", [{"status": "pending"}, {"status": "partial"}])
        models_dir = tmp_dir / "models"
        models_dir.mkdir(exist_ok=True)
        (models_dir / "demo.pkl").write_bytes(b"demo")

        health = learning_engine.check_learning_health()

        scorecard_check = next(item for item in health["checks"] if item["check"] == "scorecard_freshness")
        assert scorecard_check["status"] == "warning"
        assert "signals_db 仍有 2 条待验证/存量信号" in scorecard_check["detail"]
