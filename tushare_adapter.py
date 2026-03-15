"""
Tushare Pro 数据适配器
=====================
统一数据层: 优先走 Tushare Pro, 失败回退 akshare
解决资金流/财报/龙虎榜数据缺失问题

使用:
  1. config.py 填入 tushare_token, 设 tushare_enabled=True
  2. 策略中: from tushare_adapter import get_money_flow, get_financials, ...
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, date, timedelta
from functools import lru_cache

from log_config import get_logger

logger = get_logger("tushare_adapter")

# ================================================================
#  初始化
# ================================================================

_ts_api = None
_init_lock = threading.Lock()


def _get_api():
    """懒加载 Tushare API (线程安全)"""
    global _ts_api
    if _ts_api is not None:
        return _ts_api

    with _init_lock:
        if _ts_api is not None:
            return _ts_api
        try:
            from config import API_GUARD_PARAMS
            token = API_GUARD_PARAMS.get("tushare_token", "")
            enabled = API_GUARD_PARAMS.get("tushare_enabled", False)
            if not enabled or not token:
                return None
            import tushare as ts
            ts.set_token(token)
            _ts_api = ts.pro_api()
            logger.info("Tushare Pro 初始化成功")
            return _ts_api
        except Exception as e:
            logger.warning("Tushare Pro 初始化失败: %s, 回退 akshare", e)
            return None


def is_available() -> bool:
    """Tushare Pro 是否可用"""
    return _get_api() is not None


# ================================================================
#  限速 (Tushare Pro 有频率限制, 2000积分约200次/分钟)
# ================================================================

_ts_call_times: list[float] = []
_ts_rate_lock = threading.Lock()
_TS_RPM = 180  # 留余量


def _ts_throttle():
    """简单滑窗限速"""
    with _ts_rate_lock:
        now = time.monotonic()
        _ts_call_times[:] = [t for t in _ts_call_times if now - t < 60]
        if len(_ts_call_times) >= _TS_RPM:
            sleep_sec = 60 - (now - _ts_call_times[0]) + 0.1
            time.sleep(max(0.1, sleep_sec))
        _ts_call_times.append(time.monotonic())


def _ts_call(method, **kwargs):
    """带限速的 Tushare 调用"""
    api = _get_api()
    if api is None:
        return None
    _ts_throttle()
    try:
        df = getattr(api, method)(**kwargs)
        return df
    except Exception as e:
        logger.warning("Tushare %s 失败: %s", method, e)
        return None


# ================================================================
#  资金流向 (核心缺失数据)
# ================================================================

def get_money_flow(code: str, days: int = 5) -> dict | None:
    """获取个股资金流向

    Returns:
        {
            "net_mf_amount": 主力净流入(万元),
            "net_mf_amount_3d": 3日累计净流入,
            "buy_lg_amount": 大单买入,
            "sell_lg_amount": 大单卖出,
        } or None
    """
    # Tushare
    df = _ts_call(
        "moneyflow",
        ts_code=_to_ts_code(code),
        start_date=_n_days_ago(days),
        end_date=_today(),
    )
    if df is not None and not df.empty:
        latest = df.iloc[0]
        net_3d = df["net_mf_amount"].head(3).sum() if len(df) >= 3 else df["net_mf_amount"].sum()
        return {
            "net_mf_amount": float(latest.get("net_mf_amount", 0)),
            "net_mf_amount_3d": float(net_3d),
            "buy_lg_amount": float(latest.get("buy_lg_amount", 0)),
            "sell_lg_amount": float(latest.get("sell_lg_amount", 0)),
        }

    # 回退 akshare
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
        if df is not None and not df.empty:
            net_col = next((c for c in df.columns if "主力净流入" in c), None)
            if net_col:
                latest_val = float(df[net_col].iloc[-1]) / 10000  # 元→万
                return {
                    "net_mf_amount": latest_val,
                    "net_mf_amount_3d": float(df[net_col].tail(3).sum()) / 10000,
                    "buy_lg_amount": 0,
                    "sell_lg_amount": 0,
                }
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return None


def get_money_flow_batch(codes: list[str], days: int = 1) -> dict[str, dict]:
    """批量获取资金流向

    Args:
        codes: 股票代码列表
        days: 获取天数 (1=仅当日, >1=多日聚合, 最多5次API调用)

    Returns:
        {code: money_flow_dict, ...}
    """
    ts_codes_set = {_to_ts_code(c): c for c in codes}
    days = min(days, 10)  # 上限

    # 按日期批量查 (每天1次API调用, N天=N次)
    frames = []
    for offset in range(days):
        d = (date.today() - timedelta(days=offset)).strftime("%Y%m%d")
        df = _ts_call("moneyflow", trade_date=d)
        if df is not None and not df.empty:
            frames.append(df)

    if frames:
        import pandas as pd
        all_df = pd.concat(frames, ignore_index=True)
        result = {}
        for ts_code, code in ts_codes_set.items():
            rows = all_df[all_df["ts_code"] == ts_code]
            if rows.empty:
                continue
            latest = rows.iloc[0]
            net_3d = rows["net_mf_amount"].head(3).sum() if len(rows) >= 3 else rows["net_mf_amount"].sum()
            result[code] = {
                "net_mf_amount": float(latest.get("net_mf_amount", 0)),
                "net_mf_amount_3d": float(net_3d),
                "buy_lg_amount": float(latest.get("buy_lg_amount", 0)),
                "sell_lg_amount": float(latest.get("sell_lg_amount", 0)),
            }
        if result:
            logger.info("Tushare批量资金流: %d/%d (%d天)", len(result), len(codes), len(frames))
            return result

    # 回退: 逐只查
    result = {}
    for code in codes[:50]:  # 限50只防止太慢
        mf = get_money_flow(code, days=1)
        if mf:
            result[code] = mf
    return result


# ================================================================
#  财报数据
# ================================================================

def get_financials(code: str) -> dict | None:
    """获取最新财报数据

    Returns:
        {
            "revenue": 营收(万元),
            "net_profit": 净利润(万元),
            "profit_growth": 净利润同比(%),
            "roe": ROE(%),
            "pe": 市盈率,
        } or None
    """
    ts_code = _to_ts_code(code)

    # 利润表
    df_income = _ts_call("income", ts_code=ts_code, period=_latest_report_period())
    if df_income is None or df_income.empty:
        # 试前一期
        df_income = _ts_call("income", ts_code=ts_code, period=_prev_report_period())

    # 财务指标
    df_fina = _ts_call("fina_indicator", ts_code=ts_code, period=_latest_report_period())
    if df_fina is None or df_fina.empty:
        df_fina = _ts_call("fina_indicator", ts_code=ts_code, period=_prev_report_period())

    result = {}
    if df_income is not None and not df_income.empty:
        row = df_income.iloc[0]
        result["revenue"] = float(row.get("revenue", 0)) / 10000  # 元→万
        result["net_profit"] = float(row.get("n_income", 0)) / 10000

    if df_fina is not None and not df_fina.empty:
        row = df_fina.iloc[0]
        result["profit_growth"] = float(row.get("netprofit_yoy", 0))
        result["roe"] = float(row.get("roe", 0))

    if result:
        return result

    # 回退: akshare
    try:
        import akshare as ak
        df = ak.stock_financial_analysis_indicator(symbol=code)
        if df is not None and not df.empty:
            row = df.iloc[0]
            roe_col = next((c for c in df.columns if "净资产收益率" in c), None)
            profit_col = next((c for c in df.columns if "净利润增长率" in c), None)
            return {
                "revenue": 0,
                "net_profit": 0,
                "profit_growth": float(row[profit_col]) if profit_col else 0,
                "roe": float(row[roe_col]) if roe_col else 0,
            }
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return None


# ================================================================
#  龙虎榜
# ================================================================

def get_top_list(trade_date: str = "") -> list[dict]:
    """获取龙虎榜数据

    Returns:
        [{ts_code, name, close, pct_change, turnover_rate, amount, ...}]
    """
    if not trade_date:
        trade_date = _today()

    df = _ts_call("top_list", trade_date=trade_date)
    if df is not None and not df.empty:
        records = []
        for _, row in df.iterrows():
            records.append({
                "code": _from_ts_code(row.get("ts_code", "")),
                "name": row.get("name", ""),
                "close": float(row.get("close", 0)),
                "pct_change": float(row.get("pct_change", 0)),
                "amount": float(row.get("amount", 0)),
                "buy": float(row.get("buy", 0)),
                "sell": float(row.get("sell", 0)),
                "reason": row.get("reason", ""),
            })
        logger.info("Tushare龙虎榜: %d条 (%s)", len(records), trade_date)
        return records

    return []


def get_top_inst(trade_date: str = "") -> list[dict]:
    """获取龙虎榜机构明细"""
    if not trade_date:
        trade_date = _today()

    df = _ts_call("top_inst", trade_date=trade_date)
    if df is not None and not df.empty:
        records = []
        for _, row in df.iterrows():
            records.append({
                "code": _from_ts_code(row.get("ts_code", "")),
                "exalter": row.get("exalter", ""),
                "buy": float(row.get("buy", 0)),
                "sell": float(row.get("sell", 0)),
                "net_buy": float(row.get("net_buy", 0)),
            })
        return records

    return []


# ================================================================
#  日线行情 (Tushare作为备用源)
# ================================================================

def get_daily_kline(code: str, days: int = 60):
    """获取日K线 (DataFrame)

    优先 akshare (免费不限频), Tushare 作为备用
    """
    # akshare 优先
    try:
        import akshare as ak
        from overnight_strategy import _tx_sym
        df = ak.stock_zh_a_hist_tx(
            symbol=_tx_sym(code),
            start_date=(date.today() - timedelta(days=days * 2)).strftime("%Y%m%d"),
            end_date=date.today().strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is not None and not df.empty:
            return df
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # Tushare 备用
    df = _ts_call(
        "daily",
        ts_code=_to_ts_code(code),
        start_date=_n_days_ago(days * 2),
        end_date=_today(),
    )
    if df is not None and not df.empty:
        df = df.sort_values("trade_date").reset_index(drop=True)
        # 重命名列名兼容
        col_map = {
            "trade_date": "date", "open": "open", "high": "high",
            "low": "low", "close": "close", "vol": "volume",
            "amount": "amount", "pct_chg": "pct_change",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    return None


# ================================================================
#  实时价格 (Tushare不提供实时, 仅盘后)
#  保留akshare/新浪作为实时数据源
# ================================================================


# ================================================================
#  工具函数
# ================================================================

def _to_ts_code(code: str) -> str:
    """6位代码 → Tushare格式 (000001 → 000001.SZ)"""
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _from_ts_code(ts_code: str) -> str:
    """Tushare格式 → 6位代码 (000001.SZ → 000001)"""
    return ts_code.split(".")[0] if "." in ts_code else ts_code


def _today() -> str:
    return date.today().strftime("%Y%m%d")


def _n_days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).strftime("%Y%m%d")


@lru_cache(maxsize=1)
def _latest_report_period() -> str:
    """最新财报期 (20251231 / 20250930 等)"""
    today = date.today()
    year = today.year
    month = today.month
    # 按披露节奏: 4月底前出年报, 8月底前出半年报
    if month <= 4:
        return f"{year - 1}0930"  # Q3 of last year
    elif month <= 8:
        return f"{year - 1}1231"  # 年报
    elif month <= 10:
        return f"{year}0630"  # 半年报
    else:
        return f"{year}0930"  # Q3


@lru_cache(maxsize=1)
def _prev_report_period() -> str:
    """前一期财报"""
    today = date.today()
    year = today.year
    month = today.month
    if month <= 4:
        return f"{year - 1}0630"
    elif month <= 8:
        return f"{year - 1}0930"
    elif month <= 10:
        return f"{year - 1}1231"
    else:
        return f"{year}0630"


# ================================================================
#  健康检查
# ================================================================

def health_check() -> dict:
    """检查 Tushare Pro 连接状态"""
    api = _get_api()
    if api is None:
        return {"status": "disabled", "message": "未配置token或未启用"}

    try:
        df = api.trade_cal(exchange="SSE", start_date=_today(), end_date=_today())
        if df is not None and not df.empty:
            return {"status": "ok", "message": "Tushare Pro 连接正常"}
        return {"status": "warning", "message": "返回空数据"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ================================================================
#  入口测试
# ================================================================

if __name__ == "__main__":
    status = health_check()
    print(f"Tushare状态: {status['status']} — {status['message']}")

    if is_available():
        # 测试资金流
        mf = get_money_flow("000001")
        print(f"平安银行资金流: {mf}")

        # 测试财报
        fin = get_financials("000001")
        print(f"平安银行财报: {fin}")

        # 测试龙虎榜
        top = get_top_list()
        print(f"今日龙虎榜: {len(top)} 条")
    else:
        print("Tushare未启用, 请在config.py设置tushare_token和tushare_enabled")
