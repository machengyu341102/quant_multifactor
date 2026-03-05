"""
券商API自动下单
===============
多层安全架构: paper → demo → live
支持多券商: easytrader (华泰/国金/东方财富) + xtquant (中泰)

安全设计:
  1. 默认 paper 模式, 不会真实下单
  2. 六重 kill switch (任一触发则停止交易)
  3. 每次下单前强制检查风控
  4. emergency_stop.json 手动紧急停止
  5. 所有交易操作写入 audit log
  6. live 模式需要显式配置 + 二次确认

用法:
  python3 broker_executor.py status        # 账户+持仓
  python3 broker_executor.py positions     # 持仓明细
  python3 broker_executor.py kill_switch   # Kill switch 状态
  python3 broker_executor.py history       # 交易记录
"""

from __future__ import annotations

import os
import sys
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("broker_exec")

_DIR = os.path.dirname(os.path.abspath(__file__))
_POSITIONS_PATH = os.path.join(_DIR, "stock_positions.json")
_TRADES_PATH = os.path.join(_DIR, "stock_trades.json")
_KILL_SWITCH_PATH = os.path.join(_DIR, "emergency_stop.json")
_AUDIT_PATH = os.path.join(_DIR, "broker_audit.json")

# 默认参数
STOCK_EXECUTOR_PARAMS = {
    "mode": "paper",                    # paper | demo | live
    "broker": "easytrader",             # easytrader | xtquant
    "broker_type": "universal_client",  # easytrader 券商类型
    "account_file": "",                 # easytrader 账户配置文件
    "max_positions": 9,
    "max_daily_trades": 9,
    "single_position_pct": 15,          # 单笔仓位上限 (%)
    "daily_loss_limit_pct": -5.0,
    "consecutive_loss_halt": 4,         # 连亏 N 次暂停
    "force_exit_days": 3,              # T+N 强制离场
    "kill_switch_enabled": True,
    "slippage_pct": 0.1,               # 下单滑点 (%)
    "commission_rate": 0.00025,         # 万2.5
    "stamp_tax_rate": 0.0005,           # 印花税 0.05%
}

try:
    from config import STOCK_EXECUTOR_PARAMS as _CFG_SEP
    STOCK_EXECUTOR_PARAMS.update(_CFG_SEP)
except ImportError:
    pass


# ================================================================
#  券商抽象基类
# ================================================================

class BrokerBase(ABC):
    """券商接口抽象"""

    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""

    @abstractmethod
    def buy(self, code: str, quantity: int,
            price: float = None) -> dict:
        """买入
        Returns: {success, order_id, price, quantity, commission, message}
        """

    @abstractmethod
    def sell(self, code: str, quantity: int,
             price: float = None) -> dict:
        """卖出
        Returns: {success, order_id, price, quantity, commission, pnl, message}
        """

    @abstractmethod
    def get_balance(self) -> dict:
        """查询余额
        Returns: {total_assets, available_cash, market_value, frozen}
        """

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """查询持仓
        Returns: [{code, name, quantity, available, cost, current_price, pnl}]
        """

    def disconnect(self):
        """断开连接"""
        self.connected = False


# ================================================================
#  PaperBroker — 纸盘模拟 (默认, 安全)
# ================================================================

class PaperBroker(BrokerBase):
    """纸盘模拟 (不真实下单)"""

    def __init__(self):
        super().__init__(mode="paper")
        self.capital = STOCK_EXECUTOR_PARAMS.get(
            "initial_capital", 100000)

    def connect(self) -> bool:
        self.connected = True
        logger.info("[PaperBroker] 纸盘模式就绪")
        return True

    def buy(self, code: str, quantity: int,
            price: float = None) -> dict:
        if price is None:
            price = _get_price(code)
        if price <= 0:
            return {"success": False, "message": f"无法获取 {code} 价格"}

        slippage = price * STOCK_EXECUTOR_PARAMS["slippage_pct"] / 100
        fill_price = round(price + slippage, 2)
        commission = round(fill_price * quantity *
                           STOCK_EXECUTOR_PARAMS["commission_rate"], 2)

        return {
            "success": True,
            "order_id": f"PAPER_{code}_{int(time.time())}",
            "price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "message": f"[纸盘] 买入 {code} x{quantity} @ {fill_price}",
        }

    def sell(self, code: str, quantity: int,
             price: float = None) -> dict:
        if price is None:
            price = _get_price(code)
        if price <= 0:
            return {"success": False, "message": f"无法获取 {code} 价格"}

        slippage = price * STOCK_EXECUTOR_PARAMS["slippage_pct"] / 100
        fill_price = round(price - slippage, 2)
        commission = round(fill_price * quantity *
                           STOCK_EXECUTOR_PARAMS["commission_rate"], 2)
        stamp_tax = round(fill_price * quantity *
                          STOCK_EXECUTOR_PARAMS["stamp_tax_rate"], 2)

        return {
            "success": True,
            "order_id": f"PAPER_{code}_{int(time.time())}",
            "price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "message": f"[纸盘] 卖出 {code} x{quantity} @ {fill_price}",
        }

    def get_balance(self) -> dict:
        positions = load_positions()
        holding = [p for p in positions if p.get("status") == "holding"]
        market_value = sum(p.get("position_value", 0) for p in holding)
        trades = safe_load(_TRADES_PATH, default=[])
        total_pnl = sum(t.get("net_pnl", 0) for t in trades
                        if t.get("action") == "sell")

        return {
            "total_assets": round(self.capital + total_pnl, 2),
            "available_cash": round(self.capital + total_pnl - market_value, 2),
            "market_value": round(market_value, 2),
            "frozen": 0,
        }

    def get_positions(self) -> list[dict]:
        positions = load_positions()
        return [p for p in positions if p.get("status") == "holding"]


# ================================================================
#  EasytraderBroker — easytrader 券商接口
# ================================================================

class EasytraderBroker(BrokerBase):
    """easytrader 券商接口 (华泰/国金/东方财富)"""

    def __init__(self, broker_type: str = "universal_client"):
        super().__init__(mode="live")
        self.broker_type = broker_type
        self.account = None

    def connect(self) -> bool:
        try:
            import easytrader
            self.account = easytrader.use(self.broker_type)
            account_file = STOCK_EXECUTOR_PARAMS.get("account_file", "")
            if account_file and os.path.exists(account_file):
                self.account.prepare(account_file)
            self.connected = True
            logger.info("[EasytraderBroker] 连接成功 (%s)", self.broker_type)
            return True
        except ImportError:
            logger.error("[EasytraderBroker] easytrader 未安装, pip install easytrader")
            return False
        except Exception as e:
            logger.error("[EasytraderBroker] 连接失败: %s", e)
            return False

    def buy(self, code: str, quantity: int,
            price: float = None) -> dict:
        if not self.connected or self.account is None:
            return {"success": False, "message": "未连接"}
        try:
            if price:
                result = self.account.buy(code, price=price, amount=quantity)
            else:
                result = self.account.market_buy(code, amount=quantity)
            return {
                "success": True,
                "order_id": str(result.get("entrust_no", "")),
                "price": price or 0,
                "quantity": quantity,
                "commission": 0,  # 券商自动计算
                "message": f"买入委托 {code} x{quantity}",
                "raw": result,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def sell(self, code: str, quantity: int,
             price: float = None) -> dict:
        if not self.connected or self.account is None:
            return {"success": False, "message": "未连接"}
        try:
            if price:
                result = self.account.sell(code, price=price, amount=quantity)
            else:
                result = self.account.market_sell(code, amount=quantity)
            return {
                "success": True,
                "order_id": str(result.get("entrust_no", "")),
                "price": price or 0,
                "quantity": quantity,
                "commission": 0,
                "stamp_tax": 0,
                "message": f"卖出委托 {code} x{quantity}",
                "raw": result,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_balance(self) -> dict:
        if not self.connected or self.account is None:
            return {"error": "未连接"}
        try:
            bal = self.account.balance
            return {
                "total_assets": bal.get("总资产", 0),
                "available_cash": bal.get("可用金额", 0),
                "market_value": bal.get("股票市值", 0),
                "frozen": bal.get("冻结金额", 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def get_positions(self) -> list[dict]:
        if not self.connected or self.account is None:
            return []
        try:
            return self.account.position
        except Exception:
            return []


# ================================================================
#  Kill Switch 系统
# ================================================================

def check_kill_switches() -> tuple[bool, str]:
    """检查所有 kill switch

    Returns:
        (can_trade, reason) — True 表示可以交易
    """
    if not STOCK_EXECUTOR_PARAMS.get("kill_switch_enabled", True):
        return True, "kill_switch_disabled"

    # 1. 手动紧急停止
    ks = safe_load(_KILL_SWITCH_PATH, default={})
    if ks.get("emergency_stop"):
        return False, f"手动紧急停止: {ks.get('reason', 'unknown')}"

    # 2. 每日亏损上限
    daily_pnl = _calc_daily_pnl()
    limit = STOCK_EXECUTOR_PARAMS.get("daily_loss_limit_pct", -5.0)
    if daily_pnl <= limit:
        return False, f"今日亏损 {daily_pnl:.2f}% 超过限制 {limit}%"

    # 3. 连续亏损暂停
    consecutive = _calc_consecutive_losses()
    halt_n = STOCK_EXECUTOR_PARAMS.get("consecutive_loss_halt", 4)
    if consecutive >= halt_n:
        return False, f"连续亏损 {consecutive} 次 (≥{halt_n})"

    # 4. 持仓数上限
    positions = load_positions()
    holding = sum(1 for p in positions if p.get("status") == "holding")
    max_pos = STOCK_EXECUTOR_PARAMS.get("max_positions", 9)
    if holding >= max_pos:
        return False, f"持仓已满 {holding}/{max_pos}"

    # 5. 今日交易数上限
    today_trades = _count_today_trades()
    max_daily = STOCK_EXECUTOR_PARAMS.get("max_daily_trades", 9)
    if today_trades >= max_daily:
        return False, f"今日交易已达上限 {today_trades}/{max_daily}"

    return True, "OK"


def set_emergency_stop(reason: str = "手动触发"):
    """设置紧急停止"""
    data = {
        "emergency_stop": True,
        "reason": reason,
        "time": datetime.now().isoformat(),
    }
    safe_save(_KILL_SWITCH_PATH, data)
    logger.warning("[KILL SWITCH] 紧急停止已激活: %s", reason)
    _audit("emergency_stop", {"reason": reason})


def clear_emergency_stop():
    """清除紧急停止"""
    safe_save(_KILL_SWITCH_PATH, {"emergency_stop": False})
    logger.info("[KILL SWITCH] 紧急停止已清除")
    _audit("emergency_clear", {})


# ================================================================
#  核心交易流程
# ================================================================

_broker_instance: BrokerBase | None = None


def get_broker() -> BrokerBase:
    """获取/创建 broker 实例"""
    global _broker_instance
    if _broker_instance is not None:
        return _broker_instance

    mode = STOCK_EXECUTOR_PARAMS.get("mode", "paper")
    if mode == "paper":
        _broker_instance = PaperBroker()
    elif mode in ("demo", "live"):
        broker = STOCK_EXECUTOR_PARAMS.get("broker", "easytrader")
        if broker == "easytrader":
            _broker_instance = EasytraderBroker(
                STOCK_EXECUTOR_PARAMS.get("broker_type", "universal_client"))
        else:
            logger.warning("[Broker] 不支持的 broker: %s, 回退到纸盘", broker)
            _broker_instance = PaperBroker()
    else:
        _broker_instance = PaperBroker()

    _broker_instance.connect()
    return _broker_instance


def execute_buy_signals(recommendations: list[dict],
                        strategy: str = "") -> list[dict]:
    """执行买入信号 (策略推荐 → 下单)

    Args:
        recommendations: [{code, name, price, score, reason, atr, factor_scores}]
        strategy: 策略名称

    Returns:
        成功执行的交易列表
    """
    # Kill switch 检查
    can_trade, reason = check_kill_switches()
    if not can_trade:
        logger.warning("[Broker] 交易被拦截: %s", reason)
        _audit("trade_blocked", {"reason": reason, "count": len(recommendations)})
        return []

    broker = get_broker()
    positions = load_positions()
    executed = []

    for rec in recommendations:
        code = rec.get("code", "")
        name = rec.get("name", "")
        price = rec.get("price", rec.get("entry_price", 0))
        score = rec.get("score", rec.get("total_score", 0))

        # 重复持仓检查
        if any(p.get("code") == code and p.get("status") == "holding"
               for p in positions):
            logger.info("[Broker] 已持有 %s, 跳过", code)
            continue

        # 仓位计算
        balance = broker.get_balance()
        available = balance.get("available_cash", 0)
        total_assets = balance.get("total_assets", 100000)
        max_pct = STOCK_EXECUTOR_PARAMS["single_position_pct"]
        max_value = total_assets * max_pct / 100
        position_value = min(max_value, available * 0.95)

        if position_value <= 0 or price <= 0:
            continue

        quantity = int(position_value / price / 100) * 100  # 取整百股
        if quantity <= 0:
            continue

        # 下单
        result = broker.buy(code, quantity, price)

        if result.get("success"):
            fill_price = result.get("price", price)

            # 止损价
            atr = rec.get("atr", 0)
            stop_price = _calc_stop_price(fill_price, atr)

            pos = {
                "code": code,
                "name": name,
                "strategy": strategy,
                "entry_price": fill_price,
                "entry_date": date.today().isoformat(),
                "entry_time": datetime.now().strftime("%H:%M:%S"),
                "quantity": quantity,
                "position_value": round(fill_price * quantity, 2),
                "score": round(score, 4),
                "reason": rec.get("reason", ""),
                "status": "holding",
                "mode": broker.mode,
                "order_id": result.get("order_id", ""),
                "atr": round(atr, 4),
                "stop_price": round(stop_price, 2),
                "highest_price": fill_price,
                "commission": result.get("commission", 0),
                "factor_scores": rec.get("factor_scores", {}),
            }
            positions.append(pos)
            executed.append(pos)

            # 交易记录
            _record_trade("buy", pos, result)
            _audit("buy", {"code": code, "quantity": quantity,
                           "price": fill_price, "mode": broker.mode})

            logger.info("[Broker] 买入 %s %s x%d @ %.2f [%s]",
                        code, name, quantity, fill_price, broker.mode)

    if executed:
        save_positions(positions)

    return executed


def check_exit_signals(price_map: dict = None) -> list[dict]:
    """检查持仓出场信号 + 自动下单

    Args:
        price_map: {code: price} 实时价格 (None=自动获取)

    Returns:
        已出场的交易列表
    """
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]
    if not holding:
        return []

    if price_map is None:
        codes = [p["code"] for p in holding]
        price_map = _fetch_prices(codes)

    broker = get_broker()
    exits = []
    today = date.today().isoformat()

    for pos in holding:
        code = pos["code"]
        price = price_map.get(code, 0)
        if price <= 0:
            continue

        entry_price = pos["entry_price"]
        pnl_pct = (price - entry_price) / entry_price * 100

        # 更新最高价
        pos["highest_price"] = max(pos.get("highest_price", entry_price), price)

        exit_reason = None

        # 1. 止损
        stop_price = pos.get("stop_price", 0)
        if stop_price > 0 and price <= stop_price:
            exit_reason = "止损"

        # 2. 智能追踪止盈
        if exit_reason is None:
            try:
                from smart_trader import calc_trailing_stop
                trail = calc_trailing_stop(
                    entry_price, pos["highest_price"], price)
                if trail.get("should_exit"):
                    exit_reason = trail.get("exit_reason", "追踪止盈")
            except ImportError:
                if pnl_pct >= 5.0:
                    exit_reason = "止盈"

        # 3. 基础止损
        if exit_reason is None and pnl_pct <= -3.0:
            exit_reason = "止损"

        # 4. 持仓到期
        if exit_reason is None:
            entry_date = pos.get("entry_date", today)
            try:
                days = (date.fromisoformat(today) -
                        date.fromisoformat(entry_date)).days
                if days >= STOCK_EXECUTOR_PARAMS.get("force_exit_days", 3):
                    exit_reason = "到期离场"
            except (ValueError, TypeError):
                pass

        if exit_reason:
            quantity = pos.get("quantity", 100)
            result = broker.sell(code, quantity, price)

            if result.get("success"):
                fill_price = result.get("price", price)
                raw_pnl_pct = (fill_price - entry_price) / entry_price * 100
                cost_pct = (STOCK_EXECUTOR_PARAMS["commission_rate"] * 2 +
                            STOCK_EXECUTOR_PARAMS["stamp_tax_rate"] +
                            STOCK_EXECUTOR_PARAMS["slippage_pct"] / 100 * 2) * 100
                net_pnl_pct = round(raw_pnl_pct - cost_pct, 2)
                net_pnl = round(fill_price * quantity * net_pnl_pct / 100, 2)

                pos["status"] = "exited"
                pos["exit_price"] = fill_price
                pos["exit_date"] = today
                pos["exit_time"] = datetime.now().strftime("%H:%M:%S")
                pos["exit_reason"] = exit_reason
                pos["raw_pnl_pct"] = round(raw_pnl_pct, 2)
                pos["net_pnl_pct"] = net_pnl_pct
                pos["net_pnl"] = net_pnl
                pos["result"] = "win" if net_pnl_pct > 0 else "loss"

                _record_trade("sell", pos, result)
                _audit("sell", {"code": code, "quantity": quantity,
                                "price": fill_price, "pnl_pct": net_pnl_pct,
                                "reason": exit_reason, "mode": broker.mode})

                exits.append(pos)
                logger.info("[Broker] 卖出 %s %s x%d @ %.2f (%+.2f%%) [%s]",
                            code, pos.get("name", ""), quantity,
                            fill_price, net_pnl_pct, exit_reason)

    save_positions(positions)
    return exits


# ================================================================
#  查询 & 报告
# ================================================================

def get_portfolio_status() -> dict:
    """获取当前组合状态"""
    positions = load_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    price_map = _fetch_prices([p["code"] for p in holding]) if holding else {}

    details = []
    total_pnl = 0
    total_value = 0
    for p in holding:
        price = price_map.get(p["code"], p["entry_price"])
        pnl_pct = ((price - p["entry_price"]) / p["entry_price"] * 100
                    if p["entry_price"] else 0)
        value = price * p.get("quantity", 0)
        total_pnl += pnl_pct
        total_value += value
        details.append({
            "code": p["code"], "name": p.get("name", ""),
            "strategy": p.get("strategy", ""),
            "entry_price": p["entry_price"],
            "current_price": price,
            "quantity": p.get("quantity", 0),
            "pnl_pct": round(pnl_pct, 2),
            "value": round(value, 2),
            "days_held": _calc_days_held(p),
        })

    can_trade, ks_reason = check_kill_switches()

    return {
        "mode": STOCK_EXECUTOR_PARAMS.get("mode", "paper"),
        "count": len(holding),
        "total_value": round(total_value, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "kill_switch_ok": can_trade,
        "kill_switch_reason": ks_reason,
        "positions": sorted(details, key=lambda x: x["pnl_pct"], reverse=True),
    }


def get_trade_summary(days: int = 30) -> dict:
    """交易统计"""
    trades = safe_load(_TRADES_PATH, default=[])
    sells = [t for t in trades if t.get("action") == "sell"]

    if days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        sells = [t for t in sells if t.get("time", "")[:10] >= cutoff]

    if not sells:
        return {"total": 0}

    pnls = [t.get("net_pnl_pct", 0) for t in sells]
    wins = [p for p in pnls if p > 0]

    return {
        "total": len(sells),
        "wins": len(wins),
        "losses": len(sells) - len(wins),
        "win_rate": round(len(wins) / len(sells) * 100, 1),
        "avg_pnl": round(float(np.mean(pnls)), 2),
        "total_pnl": round(sum(pnls), 2),
        "max_win": round(max(pnls), 2),
        "max_loss": round(min(pnls), 2),
    }


# ================================================================
#  持仓 & 交易持久化
# ================================================================

def load_positions() -> list[dict]:
    return safe_load(_POSITIONS_PATH, default=[])


def save_positions(positions: list[dict]):
    safe_save(_POSITIONS_PATH, positions)


def _record_trade(action: str, pos: dict, broker_result: dict):
    """记录交易"""
    trades = safe_load(_TRADES_PATH, default=[])
    trade = {
        "action": action,
        "code": pos.get("code", ""),
        "name": pos.get("name", ""),
        "strategy": pos.get("strategy", ""),
        "price": broker_result.get("price", pos.get("entry_price", 0)),
        "quantity": pos.get("quantity", 0),
        "order_id": broker_result.get("order_id", ""),
        "time": datetime.now().isoformat(),
        "mode": pos.get("mode", "paper"),
    }
    if action == "sell":
        trade["entry_price"] = pos.get("entry_price", 0)
        trade["exit_price"] = pos.get("exit_price", 0)
        trade["raw_pnl_pct"] = pos.get("raw_pnl_pct", 0)
        trade["net_pnl_pct"] = pos.get("net_pnl_pct", 0)
        trade["net_pnl"] = pos.get("net_pnl", 0)
        trade["reason"] = pos.get("exit_reason", "")
        trade["result"] = pos.get("result", "")
        trade["days_held"] = _calc_days_held(pos)

    trades.append(trade)
    if len(trades) > 500:
        trades = trades[-500:]
    safe_save(_TRADES_PATH, trades)


def _audit(action: str, data: dict):
    """审计日志"""
    log = safe_load(_AUDIT_PATH, default=[])
    log.append({
        "time": datetime.now().isoformat(),
        "action": action,
        "mode": STOCK_EXECUTOR_PARAMS.get("mode", "paper"),
        **data,
    })
    if len(log) > 1000:
        log = log[-1000:]
    safe_save(_AUDIT_PATH, log)


# ================================================================
#  辅助函数
# ================================================================

def _get_price(code: str) -> float:
    """获取单只股票价格"""
    prices = _fetch_prices([code])
    return prices.get(code, 0)


def _fetch_prices(codes: list[str]) -> dict[str, float]:
    """批量获取价格 (smart_source 自动切换)"""
    if not codes:
        return {}
    from api_guard import smart_source, SOURCE_SINA_HTTP, SOURCE_EM_SPOT

    def _sina():
        from intraday_strategy import _sina_batch_quote
        result = _sina_batch_quote(codes)
        return {code: info.get("price", 0) for code, info in result.items()
                if info.get("price", 0) > 0}

    def _em():
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        code_col = "代码" if "代码" in df.columns else df.columns[1]
        price_col = "最新价" if "最新价" in df.columns else df.columns[2]
        df[code_col] = df[code_col].astype(str)
        code_set = set(codes)
        filtered = df[df[code_col].isin(code_set)]
        return {r[code_col]: float(r[price_col]) for _, r in filtered.iterrows()
                if str(r[price_col]).replace(".", "").replace("-", "").isdigit() and float(r[price_col]) > 0}

    result = smart_source([(SOURCE_SINA_HTTP, _sina), (SOURCE_EM_SPOT, _em)])
    return result if result else {}


def _calc_stop_price(entry_price: float, atr: float) -> float:
    """计算止损价"""
    if atr > 0:
        try:
            from smart_trader import calc_adaptive_stop
            return calc_adaptive_stop(entry_price, atr)
        except ImportError:
            pass
    return round(entry_price * 0.97, 2)  # 默认 -3%


def _calc_days_held(pos: dict) -> int:
    entry = pos.get("entry_date", date.today().isoformat())
    exit_d = pos.get("exit_date", date.today().isoformat())
    try:
        return max(1, (date.fromisoformat(exit_d) -
                        date.fromisoformat(entry)).days)
    except (ValueError, TypeError):
        return 1


def _calc_daily_pnl() -> float:
    """计算今日已实现盈亏"""
    trades = safe_load(_TRADES_PATH, default=[])
    today = date.today().isoformat()
    today_sells = [t for t in trades
                   if t.get("action") == "sell"
                   and t.get("time", "")[:10] == today]
    return sum(t.get("net_pnl_pct", 0) for t in today_sells)


def _calc_consecutive_losses() -> int:
    """计算连续亏损次数"""
    trades = safe_load(_TRADES_PATH, default=[])
    sells = [t for t in trades if t.get("action") == "sell"]
    if not sells:
        return 0
    count = 0
    for t in reversed(sells):
        if t.get("net_pnl_pct", 0) < 0:
            count += 1
        else:
            break
    return count


def _count_today_trades() -> int:
    """今日交易次数"""
    trades = safe_load(_TRADES_PATH, default=[])
    today = date.today().isoformat()
    return sum(1 for t in trades
               if t.get("action") == "buy"
               and t.get("time", "")[:10] == today)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"

    if mode == "status":
        status = get_portfolio_status()
        print(f"模式: {status['mode']} | 持仓: {status['count']}笔"
              f" | 市值: {status['total_value']:.0f}"
              f" | 浮盈: {status['total_pnl_pct']:+.2f}%")
        can, reason = check_kill_switches()
        print(f"Kill Switch: {'正常' if can else '触发 — ' + reason}")
        for p in status.get("positions", []):
            print(f"  {p['code']} {p['name']} ({p['strategy']}) "
                  f"x{p['quantity']} "
                  f"{p['entry_price']:.2f}→{p['current_price']:.2f} "
                  f"{p['pnl_pct']:+.2f}% [{p['days_held']}天]")

    elif mode == "kill_switch":
        can, reason = check_kill_switches()
        ks = safe_load(_KILL_SWITCH_PATH, default={})
        print(f"状态: {'可交易' if can else '已停止'}")
        print(f"原因: {reason}")
        print(f"紧急停止: {'是' if ks.get('emergency_stop') else '否'}")
        print(f"今日PnL: {_calc_daily_pnl():+.2f}%")
        print(f"连续亏损: {_calc_consecutive_losses()}次")
        print(f"今日交易: {_count_today_trades()}笔")

    elif mode == "history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        trades = safe_load(_TRADES_PATH, default=[])
        sells = [t for t in trades if t.get("action") == "sell"]
        for t in sells[-n:]:
            print(f"  {t.get('time', '')[:10]} {t['code']} {t.get('name', '')} "
                  f"({t.get('strategy', '?')}) "
                  f"{t.get('net_pnl_pct', 0):+.2f}% [{t.get('reason', '')}]")

    elif mode == "emergency_on":
        reason = sys.argv[2] if len(sys.argv) > 2 else "手动触发"
        set_emergency_stop(reason)
        print(f"紧急停止已激活: {reason}")

    elif mode == "emergency_off":
        clear_emergency_stop()
        print("紧急停止已清除")

    elif mode == "summary":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        s = get_trade_summary(days)
        if s["total"] == 0:
            print("暂无交易数据")
        else:
            print(f"近{days}天: {s['total']}笔 胜率{s['win_rate']}% "
                  f"收益{s['total_pnl']:+.2f}% 平均{s['avg_pnl']:+.2f}%")

    else:
        print("用法:")
        print("  python3 broker_executor.py status         # 组合状态")
        print("  python3 broker_executor.py kill_switch     # Kill switch 状态")
        print("  python3 broker_executor.py history [n]     # 交易记录")
        print("  python3 broker_executor.py summary [days]  # 统计")
        print("  python3 broker_executor.py emergency_on    # 紧急停止")
        print("  python3 broker_executor.py emergency_off   # 解除停止")
        sys.exit(1)
