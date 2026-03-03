"""paper_trader.py 单元测试"""

import os
import sys
import json
import pytest
import numpy as np
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestOpenPosition:
    """开仓"""

    def test_basic_open(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import open_position, load_positions
        pos = open_position("000001", "平安银行", "放量突破选股", 12.50, score=0.8)
        assert pos is not None
        assert pos["code"] == "000001"
        assert pos["status"] == "holding"
        assert pos["mode"] == "paper"
        assert pos["entry_price"] > 12.50  # 含滑点

        positions = load_positions()
        assert len(positions) == 1

    def test_duplicate_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import open_position
        pos1 = open_position("000001", "平安银行", "放量突破选股", 12.50)
        pos2 = open_position("000001", "平安银行", "放量突破选股", 12.50)
        assert pos1 is not None
        assert pos2 is None  # 重复开仓被拒绝

    def test_max_positions_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader.PAPER_PARAMS",
                            {**__import__("paper_trader").PAPER_PARAMS,
                             "max_positions": 2, "max_daily_trades": 10})
        from paper_trader import open_position
        open_position("000001", "A", "s1", 10.0)
        open_position("000002", "B", "s1", 20.0)
        pos3 = open_position("000003", "C", "s1", 30.0)
        assert pos3 is None  # 超出最大持仓数

    def test_atr_stop_price(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import open_position
        pos = open_position("000001", "A", "s1", 10.0, atr=0.5)
        assert pos is not None
        assert pos["stop_price"] > 0
        assert pos["atr"] == 0.5


class TestBatchOpen:
    """批量开仓"""

    def test_batch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import batch_open
        candidates = [
            {"code": "000001", "name": "A", "price": 10.0, "score": 0.8, "reason": "test"},
            {"code": "000002", "name": "B", "price": 20.0, "score": 0.7, "reason": "test"},
        ]
        opened = batch_open(candidates, "测试策略")
        assert len(opened) == 2


class TestCheckExits:
    """止损止盈"""

    def test_stop_loss(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import open_position, check_exits, load_positions
        pos = open_position("000001", "A", "s1", 10.0)
        stop = pos["stop_price"]
        # 价格跌到止损价以下
        exits = check_exits({"000001": stop - 0.5})
        assert len(exits) == 1
        assert exits[0]["reason"] == "止损"
        assert exits[0]["net_pnl_pct"] < 0

    def test_take_profit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader.PAPER_PARAMS",
                            {**__import__("paper_trader").PAPER_PARAMS,
                             "use_smart_trade": False, "take_profit_pct": 5.0})
        from paper_trader import open_position, check_exits
        pos = open_position("000001", "A", "s1", 10.0)
        entry = pos["entry_price"]
        exits = check_exits({"000001": entry * 1.06})  # +6%
        assert len(exits) == 1
        assert exits[0]["reason"] == "止盈"

    def test_force_exit_days(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader.PAPER_PARAMS",
                            {**__import__("paper_trader").PAPER_PARAMS,
                             "use_smart_trade": False, "force_exit_days": 2})
        from paper_trader import open_position, check_exits, load_positions
        open_position("000001", "A", "s1", 10.0)
        # 修改入场日期为3天前
        positions = load_positions()
        old_date = (date.today() - timedelta(days=3)).isoformat()
        positions[0]["entry_date"] = old_date
        from paper_trader import save_positions
        save_positions(positions)

        exits = check_exits({"000001": 10.05})
        assert len(exits) == 1
        assert exits[0]["reason"] == "到期离场"

    def test_no_exit_when_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader.PAPER_PARAMS",
                            {**__import__("paper_trader").PAPER_PARAMS,
                             "use_smart_trade": False})
        from paper_trader import open_position, check_exits
        pos = open_position("000001", "A", "s1", 10.0)
        entry = pos["entry_price"]
        exits = check_exits({"000001": entry * 1.01})  # +1%
        assert len(exits) == 0  # 不触发任何出场


class TestForceClose:
    """强制平仓"""

    def test_close_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._fetch_prices",
                            lambda codes: {c: 10.5 for c in codes})
        from paper_trader import open_position, force_close_all, load_positions
        open_position("000001", "A", "s1", 10.0)
        open_position("000002", "B", "s1", 20.0)
        exits = force_close_all("测试全平")
        assert len(exits) == 2
        positions = load_positions()
        holding = [p for p in positions if p.get("status") == "holding"]
        assert len(holding) == 0


class TestDailySettle:
    """日终结算"""

    def test_settle_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        from paper_trader import daily_settle
        result = daily_settle()
        assert result["trades_today"] == 0
        assert result["equity"] == 100000

    def test_settle_with_trades(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        from paper_trader import open_position, check_exits, daily_settle
        monkeypatch.setattr("paper_trader.PAPER_PARAMS",
                            {**__import__("paper_trader").PAPER_PARAMS,
                             "use_smart_trade": False, "take_profit_pct": 3.0})
        pos = open_position("000001", "A", "s1", 10.0)
        check_exits({"000001": pos["entry_price"] * 1.04})  # 触发止盈
        result = daily_settle()
        assert result["trades_today"] == 1
        assert result["pnl_today"] > 0


class TestStatistics:
    """统计分析"""

    def test_no_trades(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        from paper_trader import calc_statistics
        stats = calc_statistics()
        assert stats.get("error") == "no_trades"

    def test_with_trades(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        # 写入模拟交易
        trades = [
            {"action": "close", "code": "000001", "name": "A", "strategy": "s1",
             "net_pnl_pct": 2.5, "result": "win", "days_held": 2,
             "time": datetime.now().isoformat()},
            {"action": "close", "code": "000002", "name": "B", "strategy": "s1",
             "net_pnl_pct": -1.5, "result": "loss", "days_held": 1,
             "time": datetime.now().isoformat()},
            {"action": "close", "code": "000003", "name": "C", "strategy": "s2",
             "net_pnl_pct": 3.0, "result": "win", "days_held": 3,
             "time": datetime.now().isoformat()},
        ]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from paper_trader import calc_statistics
        stats = calc_statistics()
        assert stats["total"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["win_rate"] > 60
        assert len(stats["by_strategy"]) == 2


class TestReport:
    """报告生成"""

    def test_empty_report(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._fetch_prices", lambda codes: {})
        from paper_trader import generate_paper_report
        report = generate_paper_report()
        assert "纸盘" in report
        assert "暂无" in report

    def test_report_with_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._fetch_prices", lambda codes: {})
        trades = [
            {"action": "close", "code": "000001", "name": "A", "strategy": "s1",
             "net_pnl_pct": 2.5, "result": "win", "days_held": 2,
             "time": datetime.now().isoformat()},
        ]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from paper_trader import generate_paper_report
        report = generate_paper_report()
        assert "胜率" in report
        assert "100.0%" in report


class TestMaxDrawdown:
    """最大回撤"""

    def test_drawdown(self):
        from paper_trader import _calc_max_drawdown
        values = [100, 110, 105, 115, 100, 120]
        dd = _calc_max_drawdown(values)
        # 最大回撤从 115 → 100, 即 13.04%
        assert 13.0 < dd < 13.1

    def test_no_drawdown(self):
        from paper_trader import _calc_max_drawdown
        values = [100, 110, 120, 130]
        dd = _calc_max_drawdown(values)
        assert dd == 0


class TestOnStrategyPicks:
    """策略对接"""

    def test_picks_integration(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import on_strategy_picks
        picks = [
            {"code": "000001", "name": "A", "price": 10.0,
             "total_score": 0.8, "reason": "高位突破"},
            {"code": "000002", "name": "B", "price": 20.0,
             "total_score": 0.7, "reason": "量能配合"},
        ]
        opened = on_strategy_picks(picks, "放量突破选股")
        assert len(opened) == 2

    def test_empty_picks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._POSITIONS_PATH", str(tmp_path / "pos.json"))
        monkeypatch.setattr("paper_trader._TRADES_PATH", str(tmp_path / "trades.json"))
        from paper_trader import on_strategy_picks
        result = on_strategy_picks([], "test")
        assert result == []


class TestEquityCurve:
    """权益曲线"""

    def test_equity_persistence(self, tmp_path, monkeypatch):
        monkeypatch.setattr("paper_trader._EQUITY_PATH", str(tmp_path / "eq.json"))
        from paper_trader import save_equity, load_equity
        data = [
            {"date": "2026-03-01", "equity": 100000, "pnl_today": 0},
            {"date": "2026-03-02", "equity": 101500, "pnl_today": 1.5},
        ]
        save_equity(data)
        loaded = load_equity()
        assert len(loaded) == 2
        assert loaded[1]["equity"] == 101500
