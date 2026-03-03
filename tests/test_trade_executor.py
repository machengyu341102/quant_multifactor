"""
trade_executor 单元测试
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# 确保能导入
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  测试数据
# ================================================================

SAMPLE_SIGNALS = [
    {
        "code": "RB",
        "name": "螺纹钢",
        "exchange": "SHFE",
        "price": 3650.0,
        "score": 0.85,
        "reason": "做多 | ADX=32 | 突破20日高 | 保证金3650",
        "direction": "long",
        "margin_per_lot": 3650.0,
        "atr": 45.0,
        "lots": 2,
    },
    {
        "code": "AU",
        "name": "黄金",
        "exchange": "SHFE",
        "price": 650.0,
        "score": 0.82,
        "reason": "做空 | ADX=28 | 突破20日低 | 保证金52000",
        "direction": "short",
        "margin_per_lot": 52000.0,
        "atr": 8.5,
        "lots": 1,
    },
]


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture(autouse=True)
def _temp_files(tmp_path, monkeypatch):
    """将持仓/交易文件指向临时目录"""
    pos_path = str(tmp_path / "futures_positions.json")
    trades_path = str(tmp_path / "futures_trades.json")

    import trade_executor
    monkeypatch.setattr(trade_executor, "_POSITIONS_PATH", pos_path)
    monkeypatch.setattr(trade_executor, "_TRADES_PATH", trades_path)

    # 初始化空文件
    with open(pos_path, "w") as f:
        json.dump([], f)
    with open(trades_path, "w") as f:
        json.dump([], f)


# ================================================================
#  开仓测试
# ================================================================

class TestExecuteSignals:
    def test_basic_open(self):
        from trade_executor import execute_signals, load_futures_positions, load_trade_history

        executed = execute_signals(SAMPLE_SIGNALS, mode="paper")

        assert len(executed) == 2
        assert executed[0]["code"] == "RB"
        assert executed[0]["action"] == "open"
        assert executed[1]["code"] == "AU"

        positions = load_futures_positions()
        assert len(positions) == 2
        assert positions[0]["status"] == "holding"
        assert positions[0]["direction"] == "long"
        assert positions[1]["direction"] == "short"

        trades = load_trade_history()
        assert len(trades) == 2

    def test_skip_duplicate(self):
        from trade_executor import execute_signals, load_futures_positions

        execute_signals(SAMPLE_SIGNALS, mode="paper")
        # 再次执行相同信号
        executed2 = execute_signals(SAMPLE_SIGNALS, mode="paper")

        assert len(executed2) == 0  # 不应重复开仓
        positions = load_futures_positions()
        assert len(positions) == 2  # 仍然只有2个

    def test_empty_signals(self):
        from trade_executor import execute_signals

        result = execute_signals([], mode="paper")
        assert result == []

    def test_stop_price_long(self):
        from trade_executor import execute_signals, load_futures_positions

        execute_signals([SAMPLE_SIGNALS[0]], mode="paper")
        positions = load_futures_positions()

        pos = positions[0]
        assert pos["direction"] == "long"
        # 止损 = 3650 - 45 * 2.0 = 3560
        assert pos["stop_price"] == 3560.0

    def test_stop_price_short(self):
        from trade_executor import execute_signals, load_futures_positions

        execute_signals([SAMPLE_SIGNALS[1]], mode="paper")
        positions = load_futures_positions()

        pos = positions[0]
        assert pos["direction"] == "short"
        # 止损 = 650 + 8.5 * 2.0 = 667
        assert pos["stop_price"] == 667.0

    def test_zero_price_skipped(self):
        from trade_executor import execute_signals

        bad_signal = [{"code": "XX", "price": 0, "direction": "long"}]
        result = execute_signals(bad_signal, mode="paper")
        assert len(result) == 0


# ================================================================
#  止损止盈测试
# ================================================================

class TestCheckExits:
    def _setup_position(self, direction="long", entry_price=100.0, atr=5.0):
        from trade_executor import execute_signals
        signal = [{
            "code": "TEST",
            "name": "测试品种",
            "exchange": "TEST",
            "price": entry_price,
            "score": 0.8,
            "reason": "测试",
            "direction": direction,
            "margin_per_lot": 1000.0,
            "atr": atr,
            "lots": 1,
        }]
        execute_signals(signal, mode="paper")

    @patch("trade_executor._get_futures_prices")
    def test_long_stop_loss(self, mock_prices):
        self._setup_position(direction="long", entry_price=100.0, atr=5.0)
        # 止损价 = 100 - 5*2 = 90, 当前价 89 < 90 → 触发
        mock_prices.return_value = {"TEST": 89.0}

        from trade_executor import check_futures_exits
        with patch("trade_executor.CONTRACT_INFO", {"TEST": {"multiplier": 10}}, create=True):
            exits = check_futures_exits()

        assert len(exits) == 1
        assert exits[0]["exit_reason"] == "ATR止损"
        assert exits[0]["status"] == "exited"

    @patch("trade_executor._get_futures_prices")
    def test_short_stop_loss(self, mock_prices):
        self._setup_position(direction="short", entry_price=100.0, atr=5.0)
        # 止损价 = 100 + 5*2 = 110, 当前价 111 > 110 → 触发
        mock_prices.return_value = {"TEST": 111.0}

        from trade_executor import check_futures_exits
        with patch("trade_executor.CONTRACT_INFO", {"TEST": {"multiplier": 10}}, create=True):
            exits = check_futures_exits()

        assert len(exits) == 1
        assert exits[0]["exit_reason"] == "ATR止损"

    @patch("trade_executor._get_futures_prices")
    def test_fixed_take_profit(self, mock_prices):
        self._setup_position(direction="long", entry_price=100.0, atr=5.0)
        # 盈利 6% → 固定止盈
        mock_prices.return_value = {"TEST": 106.0}

        from trade_executor import check_futures_exits
        with patch("trade_executor.CONTRACT_INFO", {"TEST": {"multiplier": 10}}, create=True):
            exits = check_futures_exits()

        assert len(exits) == 1
        assert exits[0]["exit_reason"] == "固定止盈"

    @patch("trade_executor._get_futures_prices")
    def test_no_exit_in_range(self, mock_prices):
        self._setup_position(direction="long", entry_price=100.0, atr=5.0)
        # 当前价 102 → 不触发任何退出
        mock_prices.return_value = {"TEST": 102.0}

        from trade_executor import check_futures_exits
        with patch("trade_executor.CONTRACT_INFO", {"TEST": {"multiplier": 10}}, create=True):
            exits = check_futures_exits()

        assert len(exits) == 0

    @patch("trade_executor._get_futures_prices")
    def test_trailing_stop_long(self, mock_prices):
        self._setup_position(direction="long", entry_price=100.0, atr=5.0)

        # 先模拟价格涨到 104 (盈利4%>3%, 激活追踪)
        from trade_executor import load_futures_positions, save_futures_positions
        positions = load_futures_positions()
        positions[0]["highest_price"] = 104.0
        save_futures_positions(positions)

        # 然后价格回到 102.3 → 从最高104回撤 1.63% > 1.5% → 追踪止盈
        mock_prices.return_value = {"TEST": 102.3}

        from trade_executor import check_futures_exits
        with patch("trade_executor.CONTRACT_INFO", {"TEST": {"multiplier": 10}}, create=True):
            exits = check_futures_exits()

        assert len(exits) == 1
        assert exits[0]["exit_reason"] == "追踪止盈"


# ================================================================
#  持仓查询测试
# ================================================================

class TestPortfolioStatus:
    @patch("trade_executor._get_futures_prices")
    def test_empty_portfolio(self, mock_prices):
        from trade_executor import get_portfolio_status
        result = get_portfolio_status()
        assert result["count"] == 0

    @patch("trade_executor._get_futures_prices")
    def test_with_positions(self, mock_prices):
        from trade_executor import execute_signals, get_portfolio_status
        execute_signals(SAMPLE_SIGNALS[:1], mode="paper")

        mock_prices.return_value = {"RB": 3700.0}
        result = get_portfolio_status()
        assert result["count"] == 1
        assert result["positions"][0]["pnl_pct"] > 0  # 3700 > 3650


# ================================================================
#  交易统计测试
# ================================================================

class TestTradeSummary:
    def test_empty_history(self):
        from trade_executor import get_trade_summary
        result = get_trade_summary()
        assert result["total_trades"] == 0

    def test_with_trades(self):
        from trade_executor import save_trade_history, get_trade_summary
        trades = [
            {"action": "open", "code": "RB", "direction": "long", "price": 100, "lots": 1},
            {"action": "close", "code": "RB", "direction": "long", "price": 105,
             "lots": 1, "pnl_pct": 5.0, "pnl_amount": 500},
            {"action": "open", "code": "AU", "direction": "short", "price": 200, "lots": 1},
            {"action": "close", "code": "AU", "direction": "short", "price": 210,
             "lots": 1, "pnl_pct": -5.0, "pnl_amount": -500},
        ]
        save_trade_history(trades)
        result = get_trade_summary()
        assert result["total_trades"] == 2
        assert result["wins"] == 1
        assert result["losses"] == 1
        assert result["win_rate"] == 50.0
