"""broker_executor.py 单元测试"""

import os
import sys
import json
import pytest
import numpy as np
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPaperBroker:
    """纸盘 broker"""

    def test_connect(self):
        from broker_executor import PaperBroker
        broker = PaperBroker()
        assert broker.connect() is True
        assert broker.connected is True

    def test_buy(self):
        from broker_executor import PaperBroker
        broker = PaperBroker()
        broker.connect()
        result = broker.buy("000001", 100, price=12.50)
        assert result["success"] is True
        assert result["quantity"] == 100
        assert result["price"] > 0  # 含滑点
        assert "PAPER_" in result["order_id"]

    def test_sell(self):
        from broker_executor import PaperBroker
        broker = PaperBroker()
        broker.connect()
        result = broker.sell("000001", 100, price=12.50)
        assert result["success"] is True
        assert result["quantity"] == 100
        assert result["price"] < 12.50  # 滑点使卖出价略低

    def test_buy_no_price(self):
        """无价格时应返回失败"""
        from broker_executor import PaperBroker
        broker = PaperBroker()
        broker.connect()
        with patch("broker_executor._get_price", return_value=0):
            result = broker.buy("999999", 100)
            assert result["success"] is False

    def test_get_balance(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        from broker_executor import PaperBroker
        broker = PaperBroker()
        broker.connect()
        bal = broker.get_balance()
        assert "total_assets" in bal
        assert "available_cash" in bal
        assert bal["total_assets"] > 0


class TestKillSwitch:
    """Kill Switch 系统"""

    def test_all_clear(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        from broker_executor import check_kill_switches
        can, reason = check_kill_switches()
        assert can is True
        assert reason == "OK"

    def test_emergency_stop(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        from broker_executor import set_emergency_stop, check_kill_switches
        set_emergency_stop("测试停止")
        can, reason = check_kill_switches()
        assert can is False
        assert "紧急" in reason

    def test_clear_emergency(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        from broker_executor import set_emergency_stop, clear_emergency_stop, check_kill_switches
        set_emergency_stop("测试")
        clear_emergency_stop()
        can, _ = check_kill_switches()
        assert can is True

    def test_daily_loss_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        # 写入今日大亏交易
        today = datetime.now().isoformat()
        trades = [
            {"action": "sell", "time": today, "net_pnl_pct": -3.0},
            {"action": "sell", "time": today, "net_pnl_pct": -3.0},
        ]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from broker_executor import check_kill_switches
        can, reason = check_kill_switches()
        assert can is False
        assert "亏损" in reason

    def test_consecutive_losses(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        # 连续 5 笔亏损
        trades = [{"action": "sell", "time": f"2026-03-0{i}T10:00:00",
                    "net_pnl_pct": -1.0} for i in range(1, 6)]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from broker_executor import check_kill_switches
        can, reason = check_kill_switches()
        assert can is False
        assert "连续亏损" in reason

    def test_max_positions_block(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor.STOCK_EXECUTOR_PARAMS",
                            {**__import__("broker_executor").STOCK_EXECUTOR_PARAMS,
                             "max_positions": 2})
        # 写入 2 笔持仓
        positions = [
            {"code": "000001", "status": "holding"},
            {"code": "000002", "status": "holding"},
        ]
        (tmp_path / "pos.json").write_text(json.dumps(positions))
        from broker_executor import check_kill_switches
        can, reason = check_kill_switches()
        assert can is False
        assert "持仓" in reason

    def test_kill_switch_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor.STOCK_EXECUTOR_PARAMS",
                            {**__import__("broker_executor").STOCK_EXECUTOR_PARAMS,
                             "kill_switch_enabled": False})
        from broker_executor import check_kill_switches
        can, _ = check_kill_switches()
        assert can is True


class TestExecuteBuySignals:
    """买入执行"""

    def test_basic_buy(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        monkeypatch.setattr("broker_executor._broker_instance", None)
        import broker_executor
        monkeypatch.setitem(broker_executor.STOCK_EXECUTOR_PARAMS, "mode", "paper")

        from broker_executor import execute_buy_signals, load_positions
        recs = [
            {"code": "000001", "name": "平安银行", "price": 12.50,
             "score": 0.8, "reason": "突破"},
        ]
        executed = execute_buy_signals(recs, "放量突破选股")
        assert len(executed) == 1
        assert executed[0]["code"] == "000001"
        assert executed[0]["status"] == "holding"
        assert executed[0]["mode"] == "paper"

        positions = load_positions()
        assert len(positions) == 1

    def test_blocked_by_kill_switch(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        # 激活紧急停止
        (tmp_path / "ks.json").write_text(
            json.dumps({"emergency_stop": True, "reason": "test"}))
        from broker_executor import execute_buy_signals
        recs = [{"code": "000001", "name": "A", "price": 10.0}]
        executed = execute_buy_signals(recs, "test")
        assert len(executed) == 0

    def test_no_duplicate(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        monkeypatch.setattr("broker_executor._broker_instance", None)

        from broker_executor import execute_buy_signals
        recs = [{"code": "000001", "name": "A", "price": 10.0}]
        execute_buy_signals(recs, "s1")
        executed2 = execute_buy_signals(recs, "s1")  # 重复
        assert len(executed2) == 0


class TestCheckExitSignals:
    """出场信号"""

    def test_stop_loss_exit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        monkeypatch.setattr("broker_executor._broker_instance", None)

        from broker_executor import execute_buy_signals, check_exit_signals
        recs = [{"code": "000001", "name": "A", "price": 10.0}]
        executed = execute_buy_signals(recs, "s1")
        entry = executed[0]["entry_price"]
        stop = executed[0]["stop_price"]

        exits = check_exit_signals({"000001": stop - 0.5})
        assert len(exits) == 1
        assert exits[0]["exit_reason"] == "止损"
        assert exits[0]["net_pnl_pct"] < 0

    def test_no_exit_when_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        monkeypatch.setattr("broker_executor._broker_instance", None)

        from broker_executor import execute_buy_signals, check_exit_signals
        recs = [{"code": "000001", "name": "A", "price": 10.0}]
        executed = execute_buy_signals(recs, "s1")
        entry = executed[0]["entry_price"]

        exits = check_exit_signals({"000001": entry * 1.01})  # +1%
        assert len(exits) == 0


class TestPortfolioStatus:
    """组合状态"""

    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        from broker_executor import get_portfolio_status
        status = get_portfolio_status()
        assert status["count"] == 0
        assert status["kill_switch_ok"] is True

    def test_with_positions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._POSITIONS_PATH",
                            str(tmp_path / "pos.json"))
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        monkeypatch.setattr("broker_executor._KILL_SWITCH_PATH",
                            str(tmp_path / "ks.json"))
        monkeypatch.setattr("broker_executor._fetch_prices",
                            lambda codes: {c: 11.0 for c in codes})
        positions = [
            {"code": "000001", "name": "A", "strategy": "s1",
             "entry_price": 10.0, "entry_date": "2026-03-01",
             "quantity": 100, "status": "holding"},
        ]
        (tmp_path / "pos.json").write_text(json.dumps(positions))
        from broker_executor import get_portfolio_status
        status = get_portfolio_status()
        assert status["count"] == 1
        assert status["positions"][0]["pnl_pct"] == 10.0


class TestTradeSummary:
    """交易统计"""

    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        from broker_executor import get_trade_summary
        s = get_trade_summary()
        assert s["total"] == 0

    def test_with_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        trades = [
            {"action": "sell", "time": datetime.now().isoformat(),
             "net_pnl_pct": 2.5},
            {"action": "sell", "time": datetime.now().isoformat(),
             "net_pnl_pct": -1.0},
        ]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from broker_executor import get_trade_summary
        s = get_trade_summary()
        assert s["total"] == 2
        assert s["wins"] == 1
        assert s["win_rate"] == 50.0


class TestHelpers:
    """辅助函数"""

    def test_consecutive_losses(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._TRADES_PATH",
                            str(tmp_path / "trades.json"))
        trades = [
            {"action": "sell", "net_pnl_pct": 2.0},   # win
            {"action": "sell", "net_pnl_pct": -1.0},   # loss
            {"action": "sell", "net_pnl_pct": -0.5},   # loss
            {"action": "sell", "net_pnl_pct": -2.0},   # loss
        ]
        (tmp_path / "trades.json").write_text(json.dumps(trades))
        from broker_executor import _calc_consecutive_losses
        assert _calc_consecutive_losses() == 3

    def test_days_held(self):
        from broker_executor import _calc_days_held
        pos = {"entry_date": "2026-03-01", "exit_date": "2026-03-03"}
        assert _calc_days_held(pos) == 2

    def test_audit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broker_executor._AUDIT_PATH",
                            str(tmp_path / "audit.json"))
        from broker_executor import _audit
        _audit("test", {"key": "value"})
        data = json.loads((tmp_path / "audit.json").read_text())
        assert len(data) == 1
        assert data[0]["action"] == "test"


class TestGetBroker:
    """Broker 工厂"""

    def test_default_paper(self, monkeypatch):
        monkeypatch.setattr("broker_executor._broker_instance", None)
        monkeypatch.setattr("broker_executor.STOCK_EXECUTOR_PARAMS",
                            {**__import__("broker_executor").STOCK_EXECUTOR_PARAMS,
                             "mode": "paper"})
        from broker_executor import get_broker, PaperBroker
        broker = get_broker()
        assert isinstance(broker, PaperBroker)
        assert broker.connected is True
        # Reset for other tests
        monkeypatch.setattr("broker_executor._broker_instance", None)

    def test_unknown_broker_fallback(self, monkeypatch):
        monkeypatch.setattr("broker_executor._broker_instance", None)
        monkeypatch.setattr("broker_executor.STOCK_EXECUTOR_PARAMS",
                            {**__import__("broker_executor").STOCK_EXECUTOR_PARAMS,
                             "mode": "live", "broker": "unknown_broker"})
        from broker_executor import get_broker, PaperBroker
        broker = get_broker()
        assert isinstance(broker, PaperBroker)
        monkeypatch.setattr("broker_executor._broker_instance", None)
