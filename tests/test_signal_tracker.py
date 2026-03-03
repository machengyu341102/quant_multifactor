"""
signal_tracker.py 测试
=======================
覆盖: 信号入库/去重/验证/统计/因子有效性/环境矩阵/报告/反馈
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """临时 signals_db.json"""
    p = str(tmp_path / "signals_db.json")
    import signal_tracker
    monkeypatch.setattr(signal_tracker, "_SIGNALS_DB_PATH", p)
    return p


@pytest.fixture
def journal_path(tmp_path, monkeypatch):
    """临时 trade_journal.json"""
    p = str(tmp_path / "trade_journal.json")
    import signal_tracker
    monkeypatch.setattr(signal_tracker, "_JOURNAL_PATH", p)
    return p


def _make_journal_entry(date_str, strategy, picks):
    """构造 trade_journal 条目"""
    return {
        "date": date_str,
        "strategy": strategy,
        "regime": {
            "regime": "bull",
            "score": 0.75,
            "signals": {"MA排列": 0.8, "资金面": 0.7},
            "signal_weights": {"MA排列": 0.15},
        },
        "picks": picks,
    }


def _make_signal(date_str, strategy, code, score=0.7, verify=None, regime="bull"):
    """构造信号记录"""
    sig = {
        "date": date_str,
        "strategy": strategy,
        "code": code,
        "name": f"stock_{code}",
        "entry_price": 10.0,
        "score": score,
        "factor_scores": {"s_momentum": 0.8, "s_volume": 0.6, "s_value": 0.5},
        "regime": regime,
        "regime_score": 0.75,
        "market_signals": {},
        "direction": "long",
        "verify": verify or {},
        "status": "pending" if not verify else ("complete" if len(verify) == 3 else "partial"),
    }
    return sig


# ================================================================
#  信号入库
# ================================================================

class TestIngest:
    def test_basic_ingest(self, db_path, journal_path):
        """从 journal 导入信号"""
        from json_store import safe_save
        import signal_tracker

        entries = [_make_journal_entry("2026-03-01", "放量突破选股", [
            {"code": "000001", "name": "平安银行", "price": 10.5,
             "total_score": 0.756, "factor_scores": {"s_momentum": 0.85}},
            {"code": "600036", "name": "招商银行", "price": 30.0,
             "total_score": 0.68, "factor_scores": {"s_value": 0.7}},
        ])]
        safe_save(journal_path, entries)

        n = signal_tracker.ingest_from_journal("2026-03-01")
        assert n == 2

        db = json.load(open(db_path))
        assert len(db) == 2
        assert db[0]["code"] == "000001"
        assert db[0]["regime"] == "bull"
        assert db[0]["score"] == 0.756

    def test_dedup(self, db_path, journal_path):
        """重复导入不会产生重复记录"""
        from json_store import safe_save
        import signal_tracker

        entries = [_make_journal_entry("2026-03-01", "放量突破选股", [
            {"code": "000001", "name": "X", "price": 10, "total_score": 0.7},
        ])]
        safe_save(journal_path, entries)

        n1 = signal_tracker.ingest_from_journal("2026-03-01")
        n2 = signal_tracker.ingest_from_journal("2026-03-01")
        assert n1 == 1
        assert n2 == 0

        db = json.load(open(db_path))
        assert len(db) == 1

    def test_wrong_date_skipped(self, db_path, journal_path):
        """只导入指定日期的信号"""
        from json_store import safe_save
        import signal_tracker

        entries = [
            _make_journal_entry("2026-03-01", "A", [
                {"code": "000001", "name": "X", "price": 10, "total_score": 0.7}]),
            _make_journal_entry("2026-03-02", "B", [
                {"code": "000002", "name": "Y", "price": 20, "total_score": 0.8}]),
        ]
        safe_save(journal_path, entries)

        n = signal_tracker.ingest_from_journal("2026-03-02")
        assert n == 1
        db = json.load(open(db_path))
        assert db[0]["code"] == "000002"

    def test_empty_picks_skipped(self, db_path, journal_path):
        """空 picks 不入库"""
        from json_store import safe_save
        import signal_tracker

        entries = [_make_journal_entry("2026-03-01", "空策略", [])]
        safe_save(journal_path, entries)
        n = signal_tracker.ingest_from_journal("2026-03-01")
        assert n == 0

    def test_short_direction(self, db_path, journal_path):
        """reason 含做空 → direction=short"""
        from json_store import safe_save
        import signal_tracker

        entries = [_make_journal_entry("2026-03-01", "期货", [
            {"code": "IM", "name": "中证1000", "price": 8500,
             "total_score": 0.7, "reason": "做空信号"},
        ])]
        safe_save(journal_path, entries)
        signal_tracker.ingest_from_journal("2026-03-01")
        db = json.load(open(db_path))
        assert db[0]["direction"] == "short"


# ================================================================
#  结果验证
# ================================================================

class TestVerify:
    def test_verify_with_mock_price(self, db_path, monkeypatch):
        """mock 价格源, 验证 T+1"""
        from json_store import safe_save
        import signal_tracker

        sig = _make_signal("2026-01-01", "放量突破选股", "000001")
        sig["entry_price"] = 10.0
        safe_save(db_path, [sig])

        # mock 价格获取和交易日
        monkeypatch.setattr(signal_tracker, "_fetch_close",
                            lambda code, date, strategy: 10.5)
        monkeypatch.setattr(signal_tracker, "_nth_trading_day_after",
                            lambda d, n: f"2026-01-0{n + 1}")

        result = signal_tracker.verify_outcomes()
        assert result["verified"] == 3  # T+1, T+3, T+5

        db = json.load(open(db_path))
        assert db[0]["status"] == "complete"
        assert db[0]["verify"]["t1"]["return_pct"] == 5.0
        assert db[0]["verify"]["t1"]["result"] == "win"

    def test_verify_short_direction(self, db_path, monkeypatch):
        """做空信号: 价格下跌 = win"""
        from json_store import safe_save
        import signal_tracker

        sig = _make_signal("2026-01-01", "期货", "IM")
        sig["entry_price"] = 100.0
        sig["direction"] = "short"
        safe_save(db_path, [sig])

        monkeypatch.setattr(signal_tracker, "_fetch_close",
                            lambda code, date, strategy: 95.0)  # 跌5%
        monkeypatch.setattr(signal_tracker, "_nth_trading_day_after",
                            lambda d, n: f"2026-01-0{n + 1}")

        signal_tracker.verify_outcomes()
        db = json.load(open(db_path))
        assert db[0]["verify"]["t1"]["return_pct"] == 5.0  # 做空赚5%
        assert db[0]["verify"]["t1"]["result"] == "win"

    def test_verify_skip_no_price(self, db_path, monkeypatch):
        """价格获取失败 → 跳过"""
        from json_store import safe_save
        import signal_tracker

        sig = _make_signal("2026-01-01", "放量突破选股", "000001")
        safe_save(db_path, [sig])

        monkeypatch.setattr(signal_tracker, "_fetch_close",
                            lambda code, date, strategy: None)
        monkeypatch.setattr(signal_tracker, "_nth_trading_day_after",
                            lambda d, n: f"2026-01-0{n + 1}")

        result = signal_tracker.verify_outcomes()
        assert result["verified"] == 0
        assert result["skipped"] == 3

    def test_complete_signal_not_reverified(self, db_path, monkeypatch):
        """已完成的信号不再验证"""
        from json_store import safe_save
        import signal_tracker

        sig = _make_signal("2026-01-01", "X", "000001", verify={
            "t1": {"date": "2026-01-02", "close": 10.5, "return_pct": 5.0, "result": "win"},
            "t3": {"date": "2026-01-06", "close": 11.0, "return_pct": 10.0, "result": "win"},
            "t5": {"date": "2026-01-08", "close": 10.2, "return_pct": 2.0, "result": "win"},
        })
        sig["status"] = "complete"
        safe_save(db_path, [sig])

        call_count = [0]
        orig = signal_tracker._fetch_close
        def counting_fetch(*a, **kw):
            call_count[0] += 1
            return orig(*a, **kw)
        monkeypatch.setattr(signal_tracker, "_fetch_close", counting_fetch)

        signal_tracker.verify_outcomes()
        assert call_count[0] == 0  # 不应该调用任何价格获取


# ================================================================
#  统计分析
# ================================================================

class TestStats:
    def _seed_db(self, db_path):
        """填充测试数据"""
        from json_store import safe_save
        signals = [
            _make_signal("2026-03-01", "放量突破选股", "000001", 0.8, regime="bull",
                         verify={"t1": {"date": "d", "close": 10.5, "return_pct": 5.0, "result": "win"},
                                 "t3": {"date": "d", "close": 11.0, "return_pct": 10.0, "result": "win"},
                                 "t5": {"date": "d", "close": 10.8, "return_pct": 8.0, "result": "win"}}),
            _make_signal("2026-03-01", "放量突破选股", "600036", 0.6, regime="bull",
                         verify={"t1": {"date": "d", "close": 9.5, "return_pct": -5.0, "result": "loss"},
                                 "t3": {"date": "d", "close": 9.0, "return_pct": -10.0, "result": "loss"},
                                 "t5": {"date": "d", "close": 9.8, "return_pct": -2.0, "result": "loss"}}),
            _make_signal("2026-03-01", "集合竞价选股", "000002", 0.75, regime="bear",
                         verify={"t1": {"date": "d", "close": 10.2, "return_pct": 2.0, "result": "win"}}),
            _make_signal("2026-03-02", "集合竞价选股", "000003", 0.45, regime="bear",
                         verify={"t1": {"date": "d", "close": 9.8, "return_pct": -2.0, "result": "loss"}}),
        ]
        safe_save(db_path, signals)
        return signals

    def test_overall_stats(self, db_path):
        self._seed_db(db_path)
        import signal_tracker
        stats = signal_tracker.get_stats(days=30)
        assert stats["total"] == 4
        assert stats["overall"]["t1_win_rate"] == 50.0  # 2/4
        assert stats["overall"]["avg_t1"] == 0.0  # (5-5+2-2)/4

    def test_by_strategy(self, db_path):
        self._seed_db(db_path)
        import signal_tracker
        stats = signal_tracker.get_stats(days=30)
        assert "放量突破选股" in stats["by_strategy"]
        assert stats["by_strategy"]["放量突破选股"]["t1_win_rate"] == 50.0

    def test_by_regime(self, db_path):
        self._seed_db(db_path)
        import signal_tracker
        stats = signal_tracker.get_stats(days=30)
        assert "bull" in stats["by_regime"]
        assert "bear" in stats["by_regime"]
        assert stats["by_regime"]["bull"]["total"] == 2
        assert stats["by_regime"]["bear"]["total"] == 2

    def test_by_score_band(self, db_path):
        self._seed_db(db_path)
        import signal_tracker
        stats = signal_tracker.get_stats(days=30)
        assert "high" in stats["by_score_band"]  # >=0.7
        assert "low" in stats["by_score_band"]   # <0.5
        assert stats["by_score_band"]["high"]["total"] == 2

    def test_empty_db(self, db_path):
        import signal_tracker
        stats = signal_tracker.get_stats(days=30)
        assert stats["total"] == 0


# ================================================================
#  因子有效性
# ================================================================

class TestFactorEffectiveness:
    def test_with_enough_data(self, db_path):
        """10+ 条数据 → 计算因子有效性"""
        from json_store import safe_save
        import signal_tracker

        signals = []
        for i in range(12):
            code = f"{i:06d}"
            # 赢的信号 momentum 高, 输的信号 momentum 低
            if i < 6:
                verify = {"t1": {"date": "d", "close": 11, "return_pct": 10, "result": "win"}}
                fs = {"s_momentum": 0.9, "s_volume": 0.5}
            else:
                verify = {"t1": {"date": "d", "close": 9, "return_pct": -10, "result": "loss"}}
                fs = {"s_momentum": 0.3, "s_volume": 0.5}

            sig = _make_signal(f"2026-03-{i+1:02d}", "X", code, verify=verify)
            sig["factor_scores"] = fs
            signals.append(sig)

        safe_save(db_path, signals)
        factors = signal_tracker.get_factor_effectiveness(days=30)
        assert "s_momentum" in factors
        assert factors["s_momentum"]["spread"] > 0  # 赢家 momentum 更高
        assert factors["s_momentum"]["predictive"] is True
        # s_volume 平均值相同, spread 应该接近 0
        assert abs(factors["s_volume"]["spread"]) < 0.01

    def test_insufficient_data(self, db_path):
        """不足 10 条 → 返回空"""
        from json_store import safe_save
        import signal_tracker
        safe_save(db_path, [_make_signal("2026-03-01", "X", "000001",
                                        verify={"t1": {"date": "d", "close": 11, "return_pct": 10, "result": "win"}})])
        factors = signal_tracker.get_factor_effectiveness(days=30)
        assert factors == {}


# ================================================================
#  策略×环境矩阵
# ================================================================

class TestMatrix:
    def test_basic_matrix(self, db_path):
        from json_store import safe_save
        import signal_tracker

        signals = [
            _make_signal("2026-03-01", "A策略", "000001", regime="bull",
                         verify={"t1": {"date": "d", "close": 11, "return_pct": 10, "result": "win"}}),
            _make_signal("2026-03-01", "A策略", "000002", regime="bull",
                         verify={"t1": {"date": "d", "close": 9, "return_pct": -10, "result": "loss"}}),
            _make_signal("2026-03-01", "A策略", "000003", regime="bear",
                         verify={"t1": {"date": "d", "close": 11, "return_pct": 10, "result": "win"}}),
        ]
        safe_save(db_path, signals)
        matrix = signal_tracker.get_regime_strategy_matrix(days=30)
        assert "A策略" in matrix
        assert matrix["A策略"]["bull"]["win_rate"] == 50.0
        assert matrix["A策略"]["bull"]["total"] == 2


# ================================================================
#  报告
# ================================================================

class TestReport:
    def test_empty_report(self, db_path):
        import signal_tracker
        report = signal_tracker.generate_signal_report(30)
        assert "暂无验证数据" in report

    def test_report_with_data(self, db_path):
        from json_store import safe_save
        import signal_tracker

        signals = [
            _make_signal("2026-03-01", "放量突破选股", "000001", 0.8, regime="bull",
                         verify={"t1": {"date": "d", "close": 10.5, "return_pct": 5.0, "result": "win"}}),
            _make_signal("2026-03-01", "集合竞价选股", "000002", 0.6, regime="bear",
                         verify={"t1": {"date": "d", "close": 9.5, "return_pct": -5.0, "result": "loss"}}),
        ]
        safe_save(db_path, signals)
        report = signal_tracker.generate_signal_report(30)
        assert "信号质量报告" in report
        assert "放量突破选股" in report
        assert "bull" in report
        assert "50.0%" in report


# ================================================================
#  反馈
# ================================================================

class TestFeedback:
    def test_feedback_structure(self, db_path):
        from json_store import safe_save
        import signal_tracker

        # 足够多数据才能生成反馈
        signals = []
        for i in range(15):
            code = f"{i:06d}"
            verify = {
                "t1": {"date": "d", "close": 10.5 if i % 2 == 0 else 9.5,
                        "return_pct": 5.0 if i % 2 == 0 else -5.0,
                        "result": "win" if i % 2 == 0 else "loss"},
                "t5": {"date": "d", "close": 10.2 if i % 2 == 0 else 9.8,
                        "return_pct": 2.0 if i % 2 == 0 else -2.0,
                        "result": "win" if i % 2 == 0 else "loss"},
            }
            sig = _make_signal(f"2026-03-{i+1:02d}", "放量突破选股", code,
                               regime="bull" if i < 8 else "bear", verify=verify)
            signals.append(sig)
        safe_save(db_path, signals)

        fb = signal_tracker.get_feedback_for_learning()
        assert "factor_adjustments" in fb
        assert "strategy_regime_fit" in fb
        assert "signal_decay" in fb


# ================================================================
#  daily 任务
# ================================================================

class TestDaily:
    def test_daily_task(self, db_path, journal_path, monkeypatch):
        """daily 任务: 入库 + 验证"""
        from json_store import safe_save
        import signal_tracker
        from datetime import date as _date

        today = _date.today().isoformat()
        entries = [_make_journal_entry(today, "放量突破选股", [
            {"code": "000001", "name": "X", "price": 10, "total_score": 0.7},
        ])]
        safe_save(journal_path, entries)

        # mock verify 不做真实网络调用
        monkeypatch.setattr(signal_tracker, "verify_outcomes",
                            lambda: {"verified": 0, "skipped": 0, "completed": 0})

        result = signal_tracker.daily_ingest_and_verify()
        assert result["ingested"] == 1
        assert "入库1条" in result["stats_summary"]
