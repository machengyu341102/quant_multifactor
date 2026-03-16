"""
同花顺 Web 交易接口 (ThsWebBroker)
====================================
通过 HTTP API 连接同花顺交易网关, macOS 原生可用.

架构:
  Mac (策略系统) ──HTTP──→ 同花顺交易网关 (本机/VM/远程)
                            ├─ 国盛证券账户
                            └─ 买/卖/查询

支持两种模式:
  - demo: 不实际调用 API, 记录操作日志, 返回模拟结果
  - live: HTTP 请求到同花顺网关

支持两种认证:
  - token: 用户名+密码换取 token, 后续请求带 token
  - cookie: 直接使用浏览器 cookie

用法:
  python3 ths_broker.py test              # 连接测试
  python3 ths_broker.py demo_buy 600519   # demo 模式测试买入
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger
from json_store import safe_load, safe_save

logger = get_logger("ths_broker")

_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_LOG_PATH = os.path.join(_DIR, "ths_demo_log.json")
_SESSION_PATH = os.path.join(_DIR, "ths_session.json")

# 默认配置 (会被 config.py STOCK_EXECUTOR_PARAMS 覆盖)
_DEFAULT_THS_CONFIG = {
    "ths_base_url": "http://127.0.0.1:9099",
    "ths_username": "",
    "ths_password": "",
    "ths_auth_mode": "token",       # token | cookie
    "ths_cookie": "",               # cookie 模式时填入
    "ths_timeout_sec": 10,
    "ths_retry_count": 2,
    "ths_token_refresh_min": 30,    # token 刷新间隔 (分钟)
}


def _get_ths_config() -> dict:
    """获取 THS 配置 (合并默认值 + config.py)"""
    cfg = dict(_DEFAULT_THS_CONFIG)
    try:
        from config import STOCK_EXECUTOR_PARAMS as _sep
        for k, v in _sep.items():
            if k.startswith("ths_"):
                cfg[k] = v
    except ImportError:
        pass
    return cfg


class ThsWebBroker:
    """同花顺 Web 交易接口

    继承自 BrokerBase 的全部抽象方法:
      connect / buy / sell / get_balance / get_positions / disconnect
    """

    def __init__(self, mode: str = "demo"):
        # BrokerBase 兼容
        self.mode = mode
        self.connected = False

        self._cfg = _get_ths_config()
        self._base_url = self._cfg["ths_base_url"].rstrip("/")
        self._auth_mode = self._cfg["ths_auth_mode"]
        self._token = ""
        self._token_time = 0.0
        self._session = None  # requests.Session (延迟创建)
        self._demo_seq = 0    # demo 模式订单序号

    # ----------------------------------------------------------
    #  连接 / 断开
    # ----------------------------------------------------------

    def connect(self) -> bool:
        """建立连接"""
        if self.mode == "demo":
            self.connected = True
            logger.info("[ThsWebBroker] Demo 模式就绪 (不实际连接网关)")
            return True

        try:
            import requests
            self._session = requests.Session()
            self._session.timeout = self._cfg["ths_timeout_sec"]

            if self._auth_mode == "cookie":
                cookie = self._cfg.get("ths_cookie", "")
                if cookie:
                    self._session.headers["Cookie"] = cookie
                self.connected = True
                logger.info("[ThsWebBroker] Cookie 认证模式就绪")
                return True

            # token 认证: 登录获取 token
            return self._login()

        except ImportError:
            logger.error("[ThsWebBroker] requests 未安装, pip install requests")
            return False
        except Exception as e:
            logger.error("[ThsWebBroker] 连接失败: %s", e)
            return False

    def disconnect(self):
        """断开连接"""
        self.connected = False
        if self._session:
            try:
                self._session.close()
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)
            self._session = None
        logger.info("[ThsWebBroker] 已断开")

    def _login(self) -> bool:
        """Token 认证登录"""
        url = f"{self._base_url}/api/login"
        payload = {
            "username": self._cfg["ths_username"],
            "password": self._cfg["ths_password"],
        }
        try:
            resp = self._session.post(url, json=payload,
                                      timeout=self._cfg["ths_timeout_sec"])
            data = resp.json()
            if data.get("success") or data.get("code") == 0:
                self._token = data.get("token", data.get("data", {}).get("token", ""))
                self._token_time = time.time()
                self._session.headers["Authorization"] = f"Bearer {self._token}"
                self.connected = True
                # 持久化 session
                safe_save(_SESSION_PATH, {
                    "token": self._token,
                    "time": datetime.now().isoformat(),
                    "auth_mode": self._auth_mode,
                })
                logger.info("[ThsWebBroker] Token 登录成功")
                return True
            else:
                logger.error("[ThsWebBroker] 登录失败: %s", data.get("message", data))
                return False
        except Exception as e:
            logger.error("[ThsWebBroker] 登录请求失败: %s", e)
            return False

    def _ensure_token(self):
        """检查 token 是否过期, 自动刷新"""
        if self.mode == "demo" or self._auth_mode == "cookie":
            return
        refresh_min = self._cfg.get("ths_token_refresh_min", 30)
        if time.time() - self._token_time > refresh_min * 60:
            logger.info("[ThsWebBroker] Token 过期, 重新登录")
            self._login()

    def _request(self, method: str, path: str,
                 payload: dict = None) -> dict:
        """发送 HTTP 请求到交易网关"""
        self._ensure_token()
        url = f"{self._base_url}{path}"
        retry = self._cfg.get("ths_retry_count", 2)

        for attempt in range(retry + 1):
            try:
                if method == "GET":
                    resp = self._session.get(
                        url, params=payload,
                        timeout=self._cfg["ths_timeout_sec"])
                else:
                    resp = self._session.post(
                        url, json=payload,
                        timeout=self._cfg["ths_timeout_sec"])
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning("[ThsWebBroker] 请求失败 %s (attempt %d/%d): %s",
                               path, attempt + 1, retry + 1, e)
                if attempt < retry:
                    time.sleep(1 * (attempt + 1))

        return {"success": False, "message": f"请求失败: {path}"}

    # ----------------------------------------------------------
    #  买入
    # ----------------------------------------------------------

    def buy(self, code: str, quantity: int,
            price: float = None) -> dict:
        """买入股票"""
        if self.mode == "demo":
            return self._demo_buy(code, quantity, price)

        if not self.connected:
            return {"success": False, "message": "未连接交易网关"}

        payload = {
            "action": "buy",
            "code": code,
            "quantity": quantity,
        }
        if price:
            payload["price"] = price
            payload["order_type"] = "limit"
        else:
            payload["order_type"] = "market"

        data = self._request("POST", "/api/order", payload)

        if data.get("success") or data.get("code") == 0:
            order_data = data.get("data", data)
            result = {
                "success": True,
                "order_id": str(order_data.get("order_id",
                               order_data.get("entrust_no", ""))),
                "price": order_data.get("price", price or 0),
                "quantity": quantity,
                "commission": order_data.get("commission", 0),
                "message": f"买入委托 {code} x{quantity}",
                "raw": data,
            }
            logger.info("[ThsWebBroker] 买入 %s x%d @ %s",
                        code, quantity, price or "市价")
            return result
        else:
            msg = data.get("message", str(data))
            logger.error("[ThsWebBroker] 买入失败 %s: %s", code, msg)
            return {"success": False, "message": msg}

    # ----------------------------------------------------------
    #  卖出
    # ----------------------------------------------------------

    def sell(self, code: str, quantity: int,
             price: float = None) -> dict:
        """卖出股票"""
        if self.mode == "demo":
            return self._demo_sell(code, quantity, price)

        if not self.connected:
            return {"success": False, "message": "未连接交易网关"}

        payload = {
            "action": "sell",
            "code": code,
            "quantity": quantity,
        }
        if price:
            payload["price"] = price
            payload["order_type"] = "limit"
        else:
            payload["order_type"] = "market"

        data = self._request("POST", "/api/order", payload)

        if data.get("success") or data.get("code") == 0:
            order_data = data.get("data", data)
            result = {
                "success": True,
                "order_id": str(order_data.get("order_id",
                               order_data.get("entrust_no", ""))),
                "price": order_data.get("price", price or 0),
                "quantity": quantity,
                "commission": order_data.get("commission", 0),
                "stamp_tax": order_data.get("stamp_tax", 0),
                "message": f"卖出委托 {code} x{quantity}",
                "raw": data,
            }
            logger.info("[ThsWebBroker] 卖出 %s x%d @ %s",
                        code, quantity, price or "市价")
            return result
        else:
            msg = data.get("message", str(data))
            logger.error("[ThsWebBroker] 卖出失败 %s: %s", code, msg)
            return {"success": False, "message": msg}

    # ----------------------------------------------------------
    #  查询余额
    # ----------------------------------------------------------

    def get_balance(self) -> dict:
        """查询账户余额"""
        if self.mode == "demo":
            return self._demo_balance()

        if not self.connected:
            return {"error": "未连接交易网关"}

        data = self._request("GET", "/api/balance")

        if data.get("success") or data.get("code") == 0:
            bal = data.get("data", data)
            return {
                "total_assets": bal.get("total_assets",
                               bal.get("总资产", 0)),
                "available_cash": bal.get("available_cash",
                                 bal.get("可用金额", 0)),
                "market_value": bal.get("market_value",
                               bal.get("股票市值", 0)),
                "frozen": bal.get("frozen",
                         bal.get("冻结金额", 0)),
            }
        else:
            return {"error": data.get("message", "查询失败")}

    # ----------------------------------------------------------
    #  查询持仓
    # ----------------------------------------------------------

    def get_positions(self) -> list[dict]:
        """查询持仓"""
        if self.mode == "demo":
            return self._demo_positions()

        if not self.connected:
            return []

        data = self._request("GET", "/api/positions")

        if data.get("success") or data.get("code") == 0:
            positions = data.get("data", [])
            result = []
            for p in positions:
                result.append({
                    "code": p.get("code", p.get("证券代码", "")),
                    "name": p.get("name", p.get("证券名称", "")),
                    "quantity": p.get("quantity",
                               p.get("持仓数量", 0)),
                    "available": p.get("available",
                                p.get("可用数量", 0)),
                    "cost": p.get("cost",
                           p.get("成本价", 0)),
                    "current_price": p.get("current_price",
                                   p.get("最新价", 0)),
                    "pnl": p.get("pnl",
                          p.get("盈亏", 0)),
                })
            return result
        else:
            return []

    # ----------------------------------------------------------
    #  Demo 模式 (模拟结果, 记录日志)
    # ----------------------------------------------------------

    def _demo_buy(self, code: str, quantity: int,
                  price: float = None) -> dict:
        """Demo 模式买入 (不实际下单)"""
        self._demo_seq += 1
        if price is None:
            price = self._demo_get_price(code)

        # 模拟滑点
        try:
            from config import STOCK_EXECUTOR_PARAMS as _sep
            slippage_pct = _sep.get("slippage_pct", 0.1)
        except ImportError:
            slippage_pct = 0.1
        fill_price = round(price * (1 + slippage_pct / 100), 2)
        commission = round(fill_price * quantity * 0.00025, 2)

        order_id = f"THS_DEMO_{code}_{self._demo_seq}_{int(time.time())}"

        result = {
            "success": True,
            "order_id": order_id,
            "price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "message": f"[THS-Demo] 买入 {code} x{quantity} @ {fill_price}",
        }

        self._log_demo("buy", code, quantity, fill_price, order_id)
        logger.info("[ThsWebBroker-Demo] 买入 %s x%d @ %.2f",
                    code, quantity, fill_price)
        return result

    def _demo_sell(self, code: str, quantity: int,
                   price: float = None) -> dict:
        """Demo 模式卖出 (不实际下单)"""
        self._demo_seq += 1
        if price is None:
            price = self._demo_get_price(code)

        try:
            from config import STOCK_EXECUTOR_PARAMS as _sep
            slippage_pct = _sep.get("slippage_pct", 0.1)
        except ImportError:
            slippage_pct = 0.1
        fill_price = round(price * (1 - slippage_pct / 100), 2)
        commission = round(fill_price * quantity * 0.00025, 2)
        stamp_tax = round(fill_price * quantity * 0.0005, 2)

        order_id = f"THS_DEMO_{code}_{self._demo_seq}_{int(time.time())}"

        result = {
            "success": True,
            "order_id": order_id,
            "price": fill_price,
            "quantity": quantity,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "message": f"[THS-Demo] 卖出 {code} x{quantity} @ {fill_price}",
        }

        self._log_demo("sell", code, quantity, fill_price, order_id)
        logger.info("[ThsWebBroker-Demo] 卖出 %s x%d @ %.2f",
                    code, quantity, fill_price)
        return result

    def _demo_balance(self) -> dict:
        """Demo 模式余额"""
        return {
            "total_assets": 100000,
            "available_cash": 80000,
            "market_value": 20000,
            "frozen": 0,
        }

    def _demo_positions(self) -> list[dict]:
        """Demo 模式持仓 (返回空, 由 broker_executor 管理)"""
        return []

    def _demo_get_price(self, code: str) -> float:
        """Demo 模式获取参考价格"""
        try:
            from broker_executor import _get_price
            p = _get_price(code)
            if p > 0:
                return p
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        return 10.0  # 兜底价格

    def _log_demo(self, action: str, code: str,
                  quantity: int, price: float, order_id: str):
        """记录 demo 操作日志"""
        log = safe_load(_DEMO_LOG_PATH, default=[])
        log.append({
            "time": datetime.now().isoformat(),
            "action": action,
            "code": code,
            "quantity": quantity,
            "price": price,
            "order_id": order_id,
        })
        if len(log) > 500:
            log = log[-500:]
        safe_save(_DEMO_LOG_PATH, log)

    # ----------------------------------------------------------
    #  连接测试
    # ----------------------------------------------------------

    def test_connection(self) -> dict:
        """测试与交易网关的连接"""
        result = {
            "mode": self.mode,
            "base_url": self._base_url,
            "auth_mode": self._auth_mode,
        }

        if self.mode == "demo":
            result["status"] = "ok"
            result["message"] = "Demo 模式, 无需连接网关"
            # 测试 demo 买卖
            buy = self._demo_buy("000001", 100, 10.0)
            result["demo_buy"] = buy
            return result

        # Live 模式: 测试连接
        try:
            import requests
            resp = requests.get(
                f"{self._base_url}/api/ping",
                timeout=self._cfg["ths_timeout_sec"])
            result["ping_status"] = resp.status_code
            result["ping_body"] = resp.text[:200]

            if resp.status_code == 200:
                result["status"] = "ok"
                result["message"] = "网关连接正常"
            else:
                result["status"] = "error"
                result["message"] = f"网关返回 HTTP {resp.status_code}"

        except Exception as e:
            result["status"] = "error"
            result["message"] = f"无法连接网关: {e}"

        return result


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"

    # 读取配置
    cfg = _get_ths_config()
    try:
        from config import STOCK_EXECUTOR_PARAMS as _sep
        mode = _sep.get("mode", "demo")
    except ImportError:
        mode = "demo"

    broker = ThsWebBroker(mode=mode)

    if cmd == "test":
        print("=" * 50)
        print("同花顺交易网关连接测试")
        print("=" * 50)
        broker.connect()
        result = broker.test_connection()
        for k, v in result.items():
            if k == "demo_buy":
                print(f"  Demo买入测试: {v.get('message', v)}")
            else:
                print(f"  {k}: {v}")
        print()
        if result.get("status") == "ok":
            print("连接测试通过!")
        else:
            print("连接测试失败, 请检查配置")
            print(f"  网关地址: {cfg['ths_base_url']}")
            print(f"  认证模式: {cfg['ths_auth_mode']}")

    elif cmd == "demo_buy":
        code = sys.argv[2] if len(sys.argv) > 2 else "600519"
        broker.mode = "demo"
        broker.connect()
        result = broker.buy(code, 100, 10.0)
        print(f"Demo 买入: {result}")

    elif cmd == "demo_sell":
        code = sys.argv[2] if len(sys.argv) > 2 else "600519"
        broker.mode = "demo"
        broker.connect()
        result = broker.sell(code, 100, 10.0)
        print(f"Demo 卖出: {result}")

    elif cmd == "demo_log":
        log = safe_load(_DEMO_LOG_PATH, default=[])
        print(f"Demo 操作日志 ({len(log)}条):")
        for entry in log[-20:]:
            print(f"  {entry['time'][:19]} {entry['action']} "
                  f"{entry['code']} x{entry['quantity']} @ {entry['price']}")

    else:
        print("用法:")
        print("  python3 ths_broker.py test              # 连接测试")
        print("  python3 ths_broker.py demo_buy [code]    # Demo 买入")
        print("  python3 ths_broker.py demo_sell [code]   # Demo 卖出")
        print("  python3 ths_broker.py demo_log           # Demo 操作日志")
