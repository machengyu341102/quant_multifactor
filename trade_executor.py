"""
期货交易执行器
==============
桥接 futures_strategy.py 信号 → 交易执行(模拟/实盘)

模式:
  paper  — 纸上模拟, 记录虚拟盈亏 (默认)
  simnow — SimNow 模拟盘 (tqsdk, 真撮合无真钱)
  live   — 实盘 (tqsdk + 期货账户)

流程:
  信号 → execute_signals() → 开仓记录 → check_futures_exits() → 平仓
  所有交易记录在 futures_positions.json + futures_trades.json

用法:
  python3 trade_executor.py status    # 查看持仓
  python3 trade_executor.py history   # 交易历史
  python3 trade_executor.py check     # 检查止损止盈
"""

import os
import sys
import time
from datetime import datetime

from json_store import safe_load, safe_save
from log_config import get_logger
from config import FUTURES_PARAMS, TRADE_EXECUTOR_PARAMS

logger = get_logger("futures_executor")

_DIR = os.path.dirname(os.path.abspath(__file__))
_POSITIONS_PATH = os.path.join(_DIR, "futures_positions.json")
_TRADES_PATH = os.path.join(_DIR, "futures_trades.json")


# ================================================================
#  持仓 / 交易记录 读写
# ================================================================

def load_futures_positions() -> list:
    return safe_load(_POSITIONS_PATH, default=[])


def save_futures_positions(positions: list):
    safe_save(_POSITIONS_PATH, positions)


def load_trade_history() -> list:
    return safe_load(_TRADES_PATH, default=[])


def save_trade_history(trades: list):
    safe_save(_TRADES_PATH, trades)


# ================================================================
#  tqsdk 引擎 (SimNow / 实盘)
# ================================================================

class TQSDKEngine:
    """天勤量化交易引擎

    职责:
      - 连接 SimNow 或实盘 CTP
      - 获取实时行情 (替代 akshare 日K)
      - 提交/撤销订单
      - 查询成交回报

    合约代码映射:
      我们的 "RB" → tqsdk 主力合约 "KQ.m@SHFE.rb"
    """

    # 交易所映射
    EXCHANGE_MAP = {
        "SHFE": "SHFE", "DCE": "DCE", "CZCE": "CZCE",
        "CFFEX": "CFFEX", "INE": "INE",
    }

    def __init__(self, mode="simnow"):
        self.mode = mode
        self.api = None
        self._connected = False

    def _get_tq_symbol(self, code, exchange=""):
        """我们的代码 → tqsdk 主力合约代码

        "RB" + "SHFE" → "KQ.m@SHFE.rb"
        CZCE 特殊: 品种代码保持大写 → "KQ.m@CZCE.CF"
        """
        if not exchange:
            try:
                from futures_strategy import CONTRACT_INFO
                exchange = CONTRACT_INFO.get(code, {}).get("exchange", "SHFE")
            except ImportError:
                exchange = "SHFE"
        ex = self.EXCHANGE_MAP.get(exchange, exchange)
        # CZCE 品种代码大写, 其余小写
        sym = code.upper() if ex == "CZCE" else code.lower()
        return f"KQ.m@{ex}.{sym}"

    def _resolve_main_contract(self, kq_symbol):
        """将 KQ.m 连续主力合约解析为实际合约代码

        TqSim 不支持 KQ.m 下单, 需要解析为如 SHFE.rb2510 的实际合约。
        通过查询 quote.underlying_symbol 获取。
        """
        if not self._connected or not self.api:
            return kq_symbol
        try:
            quote = self.api.get_quote(kq_symbol)
            deadline = time.time() + 5
            while not quote.underlying_symbol and time.time() < deadline:
                self.api.wait_update(deadline=time.time() + 2)
            if quote.underlying_symbol:
                logger.info("[tqsdk] %s → %s", kq_symbol, quote.underlying_symbol)
                return quote.underlying_symbol
        except Exception as e:
            logger.warning("[tqsdk] 解析主力合约失败 %s: %s", kq_symbol, e)
        return kq_symbol

    def connect(self):
        """建立连接"""
        if self._connected:
            return True

        try:
            from tqsdk import TqApi, TqAuth, TqSim, TqAccount

            auth_user = TRADE_EXECUTOR_PARAMS.get("tqsdk_user", "")
            auth_pass = TRADE_EXECUTOR_PARAMS.get("tqsdk_password", "")

            if not auth_user or not auth_pass:
                logger.error("[tqsdk] 未配置账号, 请在 config.py TRADE_EXECUTOR_PARAMS 中设置 tqsdk_user/tqsdk_password")
                return False

            auth = TqAuth(auth_user, auth_pass)

            if self.mode == "simnow":
                self.api = TqApi(TqSim(), auth=auth)
            elif self.mode == "live":
                broker_id = TRADE_EXECUTOR_PARAMS.get("broker_id", "")
                account = TRADE_EXECUTOR_PARAMS.get("futures_account", "")
                password = TRADE_EXECUTOR_PARAMS.get("futures_password", "")
                if not all([broker_id, account, password]):
                    logger.error("[tqsdk] 实盘缺少 broker_id/futures_account/futures_password")
                    return False
                self.api = TqApi(
                    TqAccount(broker_id, account, password),
                    auth=auth,
                )
            else:
                logger.error("[tqsdk] 未知模式: %s", self.mode)
                return False

            self._connected = True
            logger.info("[tqsdk] 连接成功 (mode=%s)", self.mode)
            return True

        except Exception as e:
            logger.error("[tqsdk] 连接失败: %s", e)
            return False

    def disconnect(self):
        """断开连接"""
        if self.api:
            try:
                self.api.close()
            except Exception:
                pass
            self.api = None
            self._connected = False

    # CFFEX 合约免费版不支持, 需跳过
    CFFEX_CODES = {"IF", "IC", "IM", "IH", "TS", "TF", "T"}

    def get_quote(self, code, exchange=""):
        """获取实时行情

        Returns:
            float: 最新价, 失败返回 0
        """
        if not self._connected:
            return 0
        # 免费版不支持 CFFEX, 跳过
        if code.upper() in self.CFFEX_CODES or exchange == "CFFEX":
            return 0
        try:
            symbol = self._get_tq_symbol(code, exchange)
            quote = self.api.get_quote(symbol)
            # 带超时等待 (非交易时段无推送, 避免卡死)
            deadline = time.time() + 5
            while quote.last_price != quote.last_price and time.time() < deadline:
                self.api.wait_update(deadline=time.time() + 2)
            price = float(quote.last_price) if quote.last_price == quote.last_price else 0
            return price
        except Exception as e:
            logger.warning("[tqsdk] 获取 %s 行情失败: %s", code, e)
            return 0

    def get_quotes(self, codes, exchanges=None):
        """批量获取实时行情

        Returns:
            dict: {code: price}
        """
        if not self._connected:
            return {}
        result = {}
        exchanges = exchanges or {}
        for code in codes:
            price = self.get_quote(code, exchanges.get(code, ""))
            if price > 0:
                result[code] = price
        return result

    def submit_order(self, code, exchange, direction, volume, price=None):
        """提交订单

        Args:
            code: 品种代码 "RB"
            exchange: 交易所 "SHFE"
            direction: "long" 买入开仓 / "short" 卖出开仓
            volume: 手数
            price: 限价, None 为市价

        Returns:
            dict: {success, order_id, fill_price, message}
        """
        if not self._connected:
            return {"success": False, "message": "未连接"}
        if code.upper() in self.CFFEX_CODES or exchange == "CFFEX":
            return {"success": False, "message": "CFFEX合约需付费版tqsdk"}

        try:
            kq_symbol = self._get_tq_symbol(code, exchange)
            # TqSim 不支持 KQ.m 下单, 解析为实际合约
            symbol = self._resolve_main_contract(kq_symbol)

            if direction == "long":
                tq_direction = "BUY"
                tq_offset = "OPEN"
            else:
                tq_direction = "SELL"
                tq_offset = "OPEN"

            if price:
                order = self.api.insert_order(
                    symbol=symbol,
                    direction=tq_direction,
                    offset=tq_offset,
                    volume=volume,
                    limit_price=price,
                )
            else:
                # 市价单: 用对手价 (从 KQ.m 获取行情)
                quote = self.api.get_quote(kq_symbol)
                self.api.wait_update(deadline=time.time() + 5)
                market_price = quote.ask_price1 if direction == "long" else quote.bid_price1
                if not market_price or market_price != market_price:
                    return {"success": False, "message": "无法获取对手价(可能非交易时段)"}
                order = self.api.insert_order(
                    symbol=symbol,
                    direction=tq_direction,
                    offset=tq_offset,
                    volume=volume,
                    limit_price=market_price,
                )

            # 等待成交 (最多 15 秒)
            deadline = time.time() + 15
            while order.status != "FINISHED" and time.time() < deadline:
                self.api.wait_update(deadline=time.time() + 3)

            if order.status == "FINISHED":
                fill_price = order.trade_price if hasattr(order, "trade_price") else price
                # 检测 NaN: 午休拒单 status=FINISHED 但 trade_price=NaN
                import math
                if fill_price is None or (isinstance(fill_price, float) and math.isnan(fill_price)):
                    logger.warning("[tqsdk] 订单完成但无成交价 (可能非交易时段), %s", code)
                    return {
                        "success": False,
                        "order_id": getattr(order, "order_id", ""),
                        "fill_price": 0,
                        "message": "订单无成交(非交易时段)",
                    }
                logger.info("[tqsdk] 成交 %s %s %s 价格=%.2f 手数=%d",
                            code, direction, symbol, fill_price or 0, volume)
                return {
                    "success": True,
                    "order_id": order.order_id,
                    "fill_price": fill_price,
                    "message": "成交",
                }
            else:
                # 超时未成交, 撤单
                try:
                    self.api.cancel_order(order)
                except Exception:
                    pass
                return {
                    "success": False,
                    "order_id": getattr(order, "order_id", ""),
                    "fill_price": 0,
                    "message": f"超时未成交, 已撤单 (status={order.status})",
                }

        except Exception as e:
            logger.error("[tqsdk] 下单失败 %s: %s", code, e)
            return {"success": False, "message": str(e)}

    def close_position(self, code, exchange, direction, volume, price=None):
        """平仓

        Args:
            direction: 原持仓方向 "long"/"short"
            平多头 → SELL + CLOSE, 平空头 → BUY + CLOSE
        """
        if not self._connected:
            return {"success": False, "message": "未连接"}
        if code.upper() in self.CFFEX_CODES or exchange == "CFFEX":
            return {"success": False, "message": "CFFEX合约需付费版tqsdk"}

        try:
            kq_symbol = self._get_tq_symbol(code, exchange)
            symbol = self._resolve_main_contract(kq_symbol)

            if direction == "long":
                tq_direction = "SELL"
            else:
                tq_direction = "BUY"

            if price:
                order = self.api.insert_order(
                    symbol=symbol,
                    direction=tq_direction,
                    offset="CLOSE",
                    volume=volume,
                    limit_price=price,
                )
            else:
                quote = self.api.get_quote(kq_symbol)
                self.api.wait_update(deadline=time.time() + 5)
                market_price = quote.bid_price1 if direction == "long" else quote.ask_price1
                if not market_price or market_price != market_price:
                    return {"success": False, "fill_price": 0, "message": "无法获取对手价"}
                order = self.api.insert_order(
                    symbol=symbol,
                    direction=tq_direction,
                    offset="CLOSE",
                    volume=volume,
                    limit_price=market_price,
                )

            deadline = time.time() + 15
            while order.status != "FINISHED" and time.time() < deadline:
                self.api.wait_update(deadline=time.time() + 3)

            if order.status == "FINISHED":
                fill_price = order.trade_price if hasattr(order, "trade_price") else price
                import math
                if fill_price is None or (isinstance(fill_price, float) and math.isnan(fill_price)):
                    return {"success": False, "fill_price": 0, "message": "平仓无成交(非交易时段)"}
                return {"success": True, "fill_price": fill_price, "message": "平仓成交"}
            else:
                try:
                    self.api.cancel_order(order)
                except Exception:
                    pass
                return {"success": False, "fill_price": 0, "message": "平仓超时"}

        except Exception as e:
            logger.error("[tqsdk] 平仓失败 %s: %s", code, e)
            return {"success": False, "message": str(e)}


# 全局引擎实例 (按需创建)
_tqsdk_engine = None


def _get_engine():
    """获取或创建 tqsdk 引擎"""
    global _tqsdk_engine
    mode = TRADE_EXECUTOR_PARAMS.get("mode", "paper")
    if mode == "paper":
        return None
    if _tqsdk_engine is None or not _tqsdk_engine._connected:
        _tqsdk_engine = TQSDKEngine(mode=mode)
        if not _tqsdk_engine.connect():
            _tqsdk_engine = None
    return _tqsdk_engine


# ================================================================
#  期货实时报价 (自动选择数据源)
# ================================================================

def _get_futures_prices(codes: list) -> dict:
    """批量获取期货当前价格 {code: price}

    数据源优先级:
      1. tqsdk 实时行情 (simnow/live 模式)
      2. akshare 日K收盘价 (paper 模式回退)
    """
    if not codes:
        return {}

    # 尝试 tqsdk
    engine = _get_engine()
    if engine:
        try:
            from futures_strategy import CONTRACT_INFO
            exchanges = {c: CONTRACT_INFO.get(c, {}).get("exchange", "") for c in codes}
        except ImportError:
            exchanges = {}
        prices = engine.get_quotes(codes, exchanges)
        if prices:
            return prices

    # 回退: akshare
    result = {}
    try:
        from futures_strategy import _fetch_futures_daily
        for code in codes:
            try:
                df = _fetch_futures_daily(code)
                if df is not None and not df.empty:
                    result[code] = float(df["close"].values[-1])
            except Exception:
                pass
            time.sleep(0.2)
    except ImportError:
        logger.warning("无法导入 futures_strategy, 跳过价格获取")
    return result


# ================================================================
#  开仓执行
# ================================================================

def execute_signals(recommendations: list, mode: str = "paper") -> list:
    """接收期货推荐信号, 执行开仓

    Args:
        recommendations: futures_strategy 的推荐输出
            每项含: code, name, price, score, reason, direction, atr,
                    margin_per_lot, lots, exchange
        mode: "paper" / "simnow" / "live"

    Returns:
        list: 已执行的开仓记录
    """
    if not recommendations:
        return []

    positions = load_futures_positions()
    trades = load_trade_history()
    now = datetime.now()

    # 已有持仓的品种 (避免重复开仓)
    holding_codes = {p["code"] for p in positions if p.get("status") == "holding"}

    # tqsdk 引擎 (simnow/live 时使用)
    engine = _get_engine() if mode != "paper" else None

    executed = []
    for rec in recommendations:
        code = rec.get("code", "")
        if not code:
            continue

        if code in holding_codes:
            logger.info("[跳过] %s 已有持仓", code)
            continue

        direction = rec.get("direction", "long")
        price = float(rec.get("price", 0))
        lots = int(rec.get("lots", 1))
        atr = float(rec.get("atr", 0))
        margin = float(rec.get("margin_per_lot", 0))
        exchange = rec.get("exchange", "")

        if price <= 0:
            continue

        # ---- 下单 ----
        fill_price = price
        order_id = ""

        if engine and mode in ("simnow", "live"):
            # tqsdk 真实下单
            result = engine.submit_order(code, exchange, direction, lots, price=None)
            if result["success"]:
                fill_price = result.get("fill_price") or price
                order_id = result.get("order_id", "")
            else:
                logger.warning("[下单失败] %s: %s", code, result["message"])
                continue
        # paper 模式: 直接以信号价成交

        # ATR 止损价
        atr_mult = FUTURES_PARAMS.get("atr_stop_multiplier", 2.0)
        if direction == "long":
            stop_price = round(fill_price - atr * atr_mult, 2)
        else:
            stop_price = round(fill_price + atr * atr_mult, 2)

        pos = {
            "code": code,
            "name": rec.get("name", ""),
            "exchange": exchange,
            "direction": direction,
            "entry_price": fill_price,
            "entry_date": now.strftime("%Y-%m-%d"),
            "entry_time": now.strftime("%H:%M"),
            "lots": lots,
            "margin_per_lot": margin,
            "total_margin": round(margin * lots, 0),
            "atr": atr,
            "stop_price": stop_price,
            "score": float(rec.get("score", 0)),
            "reason": rec.get("reason", ""),
            "status": "holding",
            "highest_price": fill_price,
            "lowest_price": fill_price,
            "mode": mode,
            "order_id": order_id,
        }

        positions.append(pos)
        holding_codes.add(code)

        # 记录开仓交易
        trade = {
            "code": code,
            "name": rec.get("name", ""),
            "action": "open",
            "direction": direction,
            "price": fill_price,
            "lots": lots,
            "margin": round(margin * lots, 0),
            "stop_price": stop_price,
            "time": now.isoformat(),
            "reason": rec.get("reason", ""),
            "mode": mode,
            "order_id": order_id,
        }
        trades.append(trade)
        executed.append(trade)

        dir_label = "做多" if direction == "long" else "做空"
        mode_label = {"paper": "PAPER", "simnow": "SIMNOW", "live": "LIVE"}.get(mode, mode)
        logger.info("[%s开仓] %s %s 价格=%.2f 手数=%d 保证金=%.0f 止损=%.2f",
                    mode_label, code, dir_label, fill_price, lots,
                    margin * lots, stop_price)

    if executed:
        save_futures_positions(positions)
        save_trade_history(trades)
        logger.info("共执行 %d 笔开仓", len(executed))

    # 发射交易事件到事件总线
    if executed:
        try:
            from event_bus import get_event_bus, Priority
            bus = get_event_bus()
            codes = [t.get("code", "") for t in executed]
            bus.emit(
                source="trade_executor",
                priority=Priority.NORMAL,
                event_type="trades_executed",
                category="strategy",
                payload={
                    "count": len(executed),
                    "codes": codes,
                    "mode": mode,
                    "message": f"开仓 {len(executed)} 笔: {', '.join(codes)}",
                },
            )
        except Exception:
            pass

    # 更新注册表
    try:
        from agent_registry import get_registry
        get_registry().report_run("execution_judge", success=True)
    except Exception:
        pass

    return executed


# ================================================================
#  止损止盈检查
# ================================================================

def check_futures_exits() -> list:
    """检查所有期货持仓, 触发止损/追踪止盈/固定止盈

    规则:
      1. ATR 止损: 价格触及 stop_price
      2. 追踪止盈: 盈利>=3% 后从最高回撤>=1.5% (做多) 或反弹>=1.5% (做空)
      3. 固定止盈: 盈利>=5%

    simnow/live 模式下会自动提交平仓单。

    Returns:
        list[dict]: 触发平仓的持仓记录 (已更新 status='exited')
    """
    positions = load_futures_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        logger.info("无期货持仓")
        return []

    logger.info("检查 %d 个期货持仓...", len(holding))

    codes = [p["code"] for p in holding]
    prices = _get_futures_prices(codes)

    if not prices:
        logger.warning("获取期货价格失败, 跳过检查")
        return []

    try:
        from futures_strategy import CONTRACT_INFO
    except ImportError:
        CONTRACT_INFO = {}

    trail_act = TRADE_EXECUTOR_PARAMS.get("trailing_activation_pct", 3.0)
    trail_dd = TRADE_EXECUTOR_PARAMS.get("trailing_drawdown_pct", 1.5)
    fixed_tp = TRADE_EXECUTOR_PARAMS.get("fixed_take_profit_pct", 5.0)

    engine = _get_engine()

    exits = []
    for p in holding:
        code = p["code"]
        current = prices.get(code)
        if not current or current <= 0:
            continue

        direction = p.get("direction", "long")
        entry_price = p["entry_price"]
        stop_price = p.get("stop_price", 0)

        # 更新极值
        if direction == "long":
            p["highest_price"] = max(p.get("highest_price", entry_price), current)
        else:
            p["lowest_price"] = min(p.get("lowest_price", entry_price), current)

        # 盈亏
        if direction == "long":
            pnl_pct = (current - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current) / entry_price * 100

        exit_reason = None

        # 1. ATR 止损
        if direction == "long" and stop_price > 0 and current <= stop_price:
            exit_reason = "ATR止损"
        elif direction == "short" and stop_price > 0 and current >= stop_price:
            exit_reason = "ATR止损"

        # 2. 追踪止盈
        if not exit_reason:
            if direction == "long":
                highest = p.get("highest_price", entry_price)
                max_pnl = (highest - entry_price) / entry_price * 100
                drawdown = (highest - current) / highest * 100 if highest > 0 else 0
                if max_pnl >= trail_act and drawdown >= trail_dd:
                    exit_reason = "追踪止盈"
            else:
                lowest = p.get("lowest_price", entry_price)
                max_pnl = (entry_price - lowest) / entry_price * 100
                bounce = (current - lowest) / lowest * 100 if lowest > 0 else 0
                if max_pnl >= trail_act and bounce >= trail_dd:
                    exit_reason = "追踪止盈"

        # 3. 固定止盈
        if not exit_reason and pnl_pct >= fixed_tp:
            exit_reason = "固定止盈"

        if exit_reason:
            # simnow/live: 提交平仓单
            if engine and p.get("mode") in ("simnow", "live"):
                close_result = engine.close_position(
                    code, p.get("exchange", ""), direction, p.get("lots", 1))
                if close_result["success"]:
                    current = close_result.get("fill_price") or current
                    logger.info("[tqsdk平仓] %s %s 成交价=%.2f", code, exit_reason, current)
                else:
                    logger.warning("[tqsdk平仓失败] %s: %s", code, close_result["message"])
                    continue  # 平仓失败则不更新状态

            now = datetime.now()
            p["status"] = "exited"
            p["exit_price"] = current
            p["exit_date"] = now.strftime("%Y-%m-%d")
            p["exit_time"] = now.strftime("%H:%M")
            p["exit_reason"] = exit_reason
            p["pnl_pct"] = round(pnl_pct, 2)

            # 实际盈亏金额
            info = CONTRACT_INFO.get(code, {})
            multiplier = info.get("multiplier", 10)
            lots = p.get("lots", 1)
            if direction == "long":
                pnl_amount = (current - entry_price) * multiplier * lots
            else:
                pnl_amount = (entry_price - current) * multiplier * lots
            p["pnl_amount"] = round(pnl_amount, 2)

            exits.append(p)

            # 记录平仓交易
            trades = load_trade_history()
            trades.append({
                "code": code,
                "name": p.get("name", ""),
                "action": "close",
                "direction": direction,
                "price": current,
                "lots": lots,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_amount": round(pnl_amount, 2),
                "reason": exit_reason,
                "time": now.isoformat(),
                "mode": p.get("mode", "paper"),
            })
            save_trade_history(trades)

            dir_label = "多" if direction == "long" else "空"
            logger.info("[平仓] %s %s %.2f→%.2f %s 盈亏%.2f%% (¥%.2f)",
                        code, dir_label, entry_price, current,
                        exit_reason, pnl_pct, pnl_amount)

    save_futures_positions(positions)

    # 发射止损/止盈事件到事件总线
    if exits:
        try:
            from event_bus import get_event_bus, Priority
            bus = get_event_bus()
            for ex in exits:
                is_stop = "止损" in ex.get("exit_reason", "")
                bus.emit(
                    source="trade_executor",
                    priority=Priority.URGENT if is_stop else Priority.NORMAL,
                    event_type="stop_loss_triggered" if is_stop else "take_profit_triggered",
                    category="risk" if is_stop else "strategy",
                    payload={
                        "code": ex.get("code", ""),
                        "name": ex.get("name", ""),
                        "pnl_pct": ex.get("pnl_pct", 0),
                        "exit_reason": ex.get("exit_reason", ""),
                        "message": (f"{ex.get('code', '')} {ex.get('name', '')} "
                                    f"{ex.get('exit_reason', '')} {ex.get('pnl_pct', 0):+.2f}%"),
                    },
                )
        except Exception:
            pass

    return exits


# ================================================================
#  持仓查询
# ================================================================

def get_portfolio_status() -> dict:
    """当前期货持仓状态"""
    positions = load_futures_positions()
    holding = [p for p in positions if p.get("status") == "holding"]

    if not holding:
        return {"count": 0, "total_margin": 0, "total_pnl": 0, "positions": []}

    codes = [p["code"] for p in holding]
    prices = _get_futures_prices(codes)

    try:
        from futures_strategy import CONTRACT_INFO
    except ImportError:
        CONTRACT_INFO = {}

    total_margin = 0
    total_pnl = 0
    details = []

    for p in holding:
        code = p["code"]
        current = prices.get(code, p["entry_price"])
        entry = p["entry_price"]
        direction = p.get("direction", "long")

        if direction == "long":
            pnl_pct = (current - entry) / entry * 100
        else:
            pnl_pct = (entry - current) / entry * 100

        info = CONTRACT_INFO.get(code, {})
        multiplier = info.get("multiplier", 10)
        lots = p.get("lots", 1)
        if direction == "long":
            pnl_amount = (current - entry) * multiplier * lots
        else:
            pnl_amount = (entry - current) * multiplier * lots

        margin = p.get("total_margin", 0)
        total_margin += margin
        total_pnl += pnl_amount

        details.append({
            "code": code,
            "name": p.get("name", ""),
            "direction": "多" if direction == "long" else "空",
            "entry_price": entry,
            "current_price": current,
            "stop_price": p.get("stop_price", 0),
            "lots": lots,
            "margin": margin,
            "pnl_pct": round(pnl_pct, 2),
            "pnl_amount": round(pnl_amount, 2),
            "entry_date": p.get("entry_date", ""),
            "mode": p.get("mode", "paper"),
        })

    return {
        "count": len(details),
        "total_margin": round(total_margin, 0),
        "total_pnl": round(total_pnl, 2),
        "positions": details,
    }


def get_trade_summary() -> dict:
    """交易统计汇总"""
    trades = load_trade_history()
    closes = [t for t in trades if t.get("action") == "close"]

    if not closes:
        return {"total_trades": 0, "win_rate": 0, "total_pnl": 0}

    wins = sum(1 for t in closes if t.get("pnl_pct", 0) > 0)
    total_pnl = sum(t.get("pnl_amount", 0) for t in closes)

    return {
        "total_trades": len(closes),
        "win_rate": round(wins / len(closes) * 100, 1),
        "wins": wins,
        "losses": len(closes) - wins,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in closes) / len(closes), 2),
    }


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        portfolio = get_portfolio_status()
        mode = TRADE_EXECUTOR_PARAMS.get("mode", "paper")
        mode_label = {"paper": "模拟", "simnow": "SimNow", "live": "实盘"}.get(mode, mode)
        if portfolio["count"] == 0:
            print(f"无期货持仓 (模式: {mode_label})")
        else:
            print(f"期货持仓: {portfolio['count']}个  "
                  f"保证金: ¥{portfolio['total_margin']:.0f}  "
                  f"浮动盈亏: ¥{portfolio['total_pnl']:.2f}  "
                  f"(模式: {mode_label})")
            print("-" * 70)
            for p in portfolio["positions"]:
                print(f"  {p['code']} {p['name']} {p['direction']}  "
                      f"开仓¥{p['entry_price']:.2f} → 现价¥{p['current_price']:.2f}  "
                      f"止损¥{p['stop_price']:.2f}  "
                      f"{p['pnl_pct']:+.2f}% (¥{p['pnl_amount']:+.2f})")

    elif cmd == "history":
        summary = get_trade_summary()
        trades = load_trade_history()
        print(f"交易统计: {summary['total_trades']}笔  "
              f"胜率{summary.get('win_rate', 0):.1f}%  "
              f"总盈亏¥{summary.get('total_pnl', 0):.2f}")
        print("-" * 70)
        for t in trades[-20:]:
            action = "开仓" if t["action"] == "open" else "平仓"
            dir_label = "多" if t["direction"] == "long" else "空"
            line = (f"  {t['time'][:16]}  {action} {t['code']} "
                    f"{t.get('name', '')} {dir_label} ¥{t['price']:.2f} ×{t['lots']}")
            if t["action"] == "close":
                line += (f"  {t.get('pnl_pct', 0):+.2f}% "
                         f"¥{t.get('pnl_amount', 0):+.2f} ({t.get('reason', '')})")
            print(line)

    elif cmd == "check":
        exits = check_futures_exits()
        if exits:
            for e in exits:
                print(f"  [平仓] {e['code']} {e['name']} {e['exit_reason']}  "
                      f"¥{e['entry_price']:.2f}→¥{e['exit_price']:.2f}  "
                      f"{e['pnl_pct']:+.2f}%")
        else:
            print("  无触发止损/止盈")

    else:
        print("用法:")
        print("  python3 trade_executor.py status   # 查看期货持仓")
        print("  python3 trade_executor.py history   # 交易历史")
        print("  python3 trade_executor.py check     # 检查止损止盈")
