"""
个股诊断智能体 (Stock Analyzer)
===============================
按需深度分析单只股票, 输出结构化诊断报告, 信号入 trade_journal 走闭环验证。

功能:
  - 技术面: K线形态/MA排列/RSI/MACD/布林/ATR
  - 资金面: 主力净流入/大单占比/3日趋势
  - 量价面: 量比/换手率/量价背离
  - 位置面: 压力支撑/距高低点/布林位
  - 综合打分 + 方向判定(看多/看空/中性) + 建议

CLI:
  python3 stock_analyzer.py 002221           # 分析东华能源
  python3 stock_analyzer.py 002221 --push    # 分析并推送微信
  python3 stock_analyzer.py 002221 --journal # 分析并写入 trade_journal (进闭环)

集成:
  from stock_analyzer import analyze_stock
  result = analyze_stock("002221")
"""

from __future__ import annotations

import os
import sys
import math
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_config import get_logger

logger = get_logger("stock_analyzer")

_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_stock_name(code: str) -> str:
    """尝试获取股票名称, 失败返回代码"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        row = df[df["code"] == code]
        if not row.empty:
            return str(row.iloc[0]["name"])
    except Exception:
        pass
    return code


# ================================================================
#  数据获取
# ================================================================

def _fetch_klines(code: str, days: int = 120) -> list[dict]:
    """获取日K线数据, 返回 [{date, open, high, low, close, volume, turnover}, ...]
    按日期升序排列 (最旧在前). 腾讯优先, 东财备选 (独立断路器).
    """
    import akshare as ak
    from api_guard import smart_source, SOURCE_TENCENT_KLINE, SOURCE_EM_KLINE

    end_d = date.today()
    start_d = end_d - timedelta(days=days + 30)
    sym = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"

    def _tx():
        df = ak.stock_zh_a_hist_tx(
            symbol=sym,
            start_date=start_d.strftime("%Y%m%d"),
            end_date=end_d.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ValueError("腾讯K线返回空")
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "date": str(r["date"])[:10],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("amount", r.get("volume", 0))),
                "turnover": float(r.get("turnover", 0)),
            })
        return rows

    def _em():
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_d.strftime("%Y%m%d"),
            end_date=end_d.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ValueError("东财K线返回空")
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "date": str(r.get("日期", r.get("date", "")))[:10],
                "open": float(r.get("开盘", r.get("open", 0))),
                "high": float(r.get("最高", r.get("high", 0))),
                "low": float(r.get("最低", r.get("low", 0))),
                "close": float(r.get("收盘", r.get("close", 0))),
                "volume": float(r.get("成交额", r.get("amount", 0))),
                "turnover": float(r.get("换手率", r.get("turnover", 0))),
            })
        return rows

    try:
        return smart_source([
            (SOURCE_TENCENT_KLINE, _tx),
            (SOURCE_EM_KLINE, _em),
        ])
    except Exception as e:
        logger.warning("K线双源均失败 %s: %s", code, e)
        return []


def _fetch_realtime(code: str) -> dict | None:
    """获取实时行情快照 (东财优先, 新浪备选, 独立断路器)"""
    from api_guard import smart_source, SOURCE_EM_SPOT, SOURCE_SINA_HTTP

    def _em():
        import akshare as ak
        from api_guard import guarded_call
        df = guarded_call(
            ak.stock_zh_a_spot_em,
            source=SOURCE_EM_SPOT,
            cache_key="analyzer_spot_em",
            cache_ttl=60,
        )
        if df is None or df.empty:
            raise ValueError("东财快照返回空")
        row = df[df["代码"] == code]
        if row.empty:
            raise ValueError(f"东财快照无 {code}")
        r = row.iloc[0]
        return {
            "price": float(r.get("最新价", 0)),
            "pct_change": float(r.get("涨跌幅", 0)),
            "volume_ratio": float(r.get("量比", 0)),
            "turnover_rate": float(r.get("换手率", 0)),
            "name": str(r.get("名称", "")),
            "total_mv": float(r.get("总市值", 0)),
            "circ_mv": float(r.get("流通市值", 0)),
            "pe": float(r.get("市盈率-动态", 0)) if r.get("市盈率-动态") else 0,
            "pb": float(r.get("市净率", 0)) if r.get("市净率") else 0,
            "high": float(r.get("最高", 0)),
            "low": float(r.get("最低", 0)),
            "open": float(r.get("今开", 0)),
            "pre_close": float(r.get("昨收", 0)),
            "amount": float(r.get("成交额", 0)),
        }

    def _sina():
        import requests, re
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        m = re.search(r'"(.+)"', resp.text)
        if not m:
            raise ValueError("新浪行情解析失败")
        f = m.group(1).split(",")
        if len(f) < 32:
            raise ValueError("新浪行情字段不足")
        return {
            "price": float(f[3]),
            "pct_change": round((float(f[3]) - float(f[2])) / float(f[2]) * 100, 2) if float(f[2]) > 0 else 0,
            "volume_ratio": 0,
            "turnover_rate": 0,
            "name": f[0],
            "total_mv": 0,
            "circ_mv": 0,
            "pe": 0,
            "pb": 0,
            "high": float(f[4]),
            "low": float(f[5]),
            "open": float(f[1]),
            "pre_close": float(f[2]),
            "amount": float(f[9]),
        }

    try:
        return smart_source([
            (SOURCE_EM_SPOT, _em),
            (SOURCE_SINA_HTTP, _sina),
        ])
    except Exception as e:
        logger.warning("行情双源均失败 %s: %s", code, e)
        return None


def _fetch_fund_flow(code: str) -> dict:
    """获取资金流向"""
    result = {"net_mf": 0, "net_mf_3d": 0, "main_pct": 0}
    try:
        from tushare_adapter import is_available, get_money_flow_batch
        if is_available():
            batch = get_money_flow_batch([code], days=5)
            if code in batch:
                d = batch[code]
                result["net_mf"] = d.get("net_mf_amount", 0)
                result["net_mf_3d"] = d.get("net_mf_amount_3d", 0)
                buy_lg = d.get("buy_lg_amount", 0)
                sell_lg = d.get("sell_lg_amount", 0)
                total = buy_lg + sell_lg
                result["main_pct"] = (d["net_mf_amount"] / total * 100) if total > 0 else 0
                return result
    except Exception:
        pass

    # fallback: akshare
    try:
        from api_guard import guarded_call
        import akshare as ak
        mkt = "sh" if code.startswith(("6", "9")) else "sz"
        df = guarded_call(
            ak.stock_individual_fund_flow,
            stock=code,
            market=mkt,
            cache_key=f"analyzer_{code}_fund",
            cache_ttl=300,
        )
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            result["net_mf"] = float(latest.get("主力净流入-净额", 0)) / 1e4
            # 3日合计
            tail = df.tail(3)
            result["net_mf_3d"] = tail["主力净流入-净额"].sum() / 1e4 if "主力净流入-净额" in tail.columns else 0
            result["main_pct"] = float(latest.get("主力净流入-净占比", 0))
    except Exception as e:
        logger.debug("资金流获取失败 %s: %s", code, e)

    return result


# ================================================================
#  技术指标计算
# ================================================================

def _calc_ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _calc_ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _calc_macd(closes: list[float]) -> dict | None:
    if len(closes) < 35:
        return None
    ema12 = _calc_ema(closes, 12)
    ema26 = _calc_ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None
    dif = ema12 - ema26
    # 简化DEA: 用最后9个DIF的EMA
    # 为更准确, 逐bar计算
    difs = []
    k12 = 2 / 13
    k26 = 2 / 27
    e12 = sum(closes[:12]) / 12
    e26 = sum(closes[:26]) / 26
    for c in closes[12:26]:
        e12 = c * k12 + e12 * (1 - k12)
    for i in range(26, len(closes)):
        e12 = closes[i] * k12 + e12 * (1 - k12)
        e26 = closes[i] * k26 + e26 * (1 - k26)
        difs.append(e12 - e26)
    if len(difs) < 9:
        return None
    k9 = 2 / 10
    dea = sum(difs[:9]) / 9
    for d in difs[9:]:
        dea = d * k9 + dea * (1 - k9)
    macd_bar = (difs[-1] - dea) * 2
    return {"dif": round(difs[-1], 4), "dea": round(dea, 4), "macd": round(macd_bar, 4)}


def _calc_bollinger(closes: list[float], period: int = 20) -> dict | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    return {
        "upper": round(mid + 2 * std, 3),
        "mid": round(mid, 3),
        "lower": round(mid - 2 * std, 3),
        "width": round(4 * std / mid * 100, 2) if mid > 0 else 0,
    }


def _calc_atr(klines: list[dict], period: int = 14) -> float | None:
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        h = klines[i]["high"]
        l = klines[i]["low"]
        pc = klines[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / period


# ================================================================
#  打分
# ================================================================

def _score_trend(closes: list[float], price: float) -> tuple[float, list[str]]:
    """趋势评分 (0-1): MA排列 + 价格位置"""
    details = []
    score = 0.5

    ma5 = _calc_ma(closes, 5)
    ma10 = _calc_ma(closes, 10)
    ma20 = _calc_ma(closes, 20)
    ma60 = _calc_ma(closes, 60)

    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            score += 0.2
            details.append("MA5>10>20 多头排列")
        elif ma5 < ma10 < ma20:
            score -= 0.2
            details.append("MA5<10<20 空头排列")

        if price > ma5:
            score += 0.1
            details.append(f"站上MA5({ma5:.2f})")
        elif price < ma20:
            score -= 0.1
            details.append(f"跌破MA20({ma20:.2f})")

    if ma60:
        if price > ma60:
            score += 0.1
            details.append(f"站上MA60({ma60:.2f})")
        else:
            score -= 0.1
            details.append(f"在MA60({ma60:.2f})下方")

    return max(0, min(1, score)), details


def _score_momentum(closes: list[float]) -> tuple[float, list[str]]:
    """动量评分 (0-1): RSI + MACD + 多周期涨幅"""
    details = []
    score = 0.5

    rsi14 = _calc_rsi(closes, 14)
    if rsi14 is not None:
        details.append(f"RSI(14)={rsi14:.1f}")
        if rsi14 > 80:
            score -= 0.15
            details.append("严重超买")
        elif rsi14 > 70:
            score -= 0.05
            details.append("超买区")
        elif rsi14 < 20:
            score += 0.15
            details.append("严重超卖")
        elif rsi14 < 30:
            score += 0.05
            details.append("超卖区")

    macd = _calc_macd(closes)
    if macd:
        if macd["dif"] > macd["dea"]:
            score += 0.1
            details.append("MACD金叉")
        else:
            score -= 0.05
            details.append("MACD死叉")
        if macd["macd"] > 0:
            score += 0.05
        else:
            score -= 0.05

    # 多周期涨幅
    if len(closes) >= 6:
        pct5 = (closes[-1] / closes[-6] - 1) * 100
        details.append(f"5日涨幅{pct5:+.1f}%")
        if pct5 > 15:
            score -= 0.1  # 连续大涨，回调风险
        elif pct5 > 5:
            score += 0.05
        elif pct5 < -10:
            score += 0.1  # 超跌反弹
        elif pct5 < -5:
            score += 0.05

    return max(0, min(1, score)), details


def _score_volume(klines: list[dict], rt: dict | None) -> tuple[float, list[str]]:
    """量价评分 (0-1): 量比 + 换手 + 量价配合"""
    details = []
    score = 0.5

    vol_ratio = rt.get("volume_ratio", 0) if rt else 0
    turnover = rt.get("turnover_rate", 0) if rt else 0

    if vol_ratio > 0:
        details.append(f"量比{vol_ratio:.2f}")
        if vol_ratio > 3:
            score += 0.15
            details.append("放巨量")
        elif vol_ratio > 1.5:
            score += 0.1
            details.append("放量")
        elif vol_ratio < 0.5:
            score -= 0.1
            details.append("极度缩量")

    if turnover > 0:
        details.append(f"换手{turnover:.1f}%")
        if 3 <= turnover <= 8:
            score += 0.05  # 健康换手
        elif turnover > 15:
            score -= 0.1  # 过度换手

    # 量价配合: 上涨放量、下跌缩量为佳
    if len(klines) >= 5:
        recent = klines[-5:]
        up_vol = [k["volume"] for k in recent if k["close"] > k["open"]]
        dn_vol = [k["volume"] for k in recent if k["close"] < k["open"]]
        if up_vol and dn_vol:
            avg_up = sum(up_vol) / len(up_vol)
            avg_dn = sum(dn_vol) / len(dn_vol)
            if avg_up > avg_dn * 1.3:
                score += 0.1
                details.append("量价配合良好")
            elif avg_dn > avg_up * 1.3:
                score -= 0.1
                details.append("量价背离")

    return max(0, min(1, score)), details


def _score_position(closes: list[float], price: float, klines: list[dict]) -> tuple[float, list[str]]:
    """位置评分 (0-1): 布林位置 + 距高低点 + 支撑压力"""
    details = []
    score = 0.5

    boll = _calc_bollinger(closes, 20)
    if boll:
        boll_range = boll["upper"] - boll["lower"]
        if boll_range > 0:
            boll_pct = (price - boll["lower"]) / boll_range * 100
            details.append(f"布林位置{boll_pct:.0f}%")
            if boll_pct > 95:
                score -= 0.15
                details.append("触及布林上轨")
            elif boll_pct > 80:
                score -= 0.05
            elif boll_pct < 5:
                score += 0.15
                details.append("触及布林下轨")
            elif boll_pct < 20:
                score += 0.05

    # 距20日高低点
    if len(closes) >= 20:
        high_20 = max(closes[-20:])
        low_20 = min(closes[-20:])
        range_20 = high_20 - low_20
        if range_20 > 0:
            pos_pct = (price - low_20) / range_20 * 100
            details.append(f"20日区间位{pos_pct:.0f}%")
            if pos_pct > 90:
                score -= 0.1
                details.append("接近20日高点")
            elif pos_pct < 10:
                score += 0.1
                details.append("接近20日低点")

    # ATR止损空间
    atr = _calc_atr(klines, 14)
    if atr and price > 0:
        atr_pct = atr / price * 100
        details.append(f"ATR(14)={atr:.2f} ({atr_pct:.1f}%)")

    return max(0, min(1, score)), details


def _score_fund_flow(fund: dict) -> tuple[float, list[str]]:
    """资金面评分 (0-1)"""
    details = []
    score = 0.5

    net = fund.get("net_mf", 0)
    net_3d = fund.get("net_mf_3d", 0)
    main_pct = fund.get("main_pct", 0)

    if net != 0:
        details.append(f"今日主力净流{net:+.0f}万")
    if net_3d != 0:
        details.append(f"3日主力净流{net_3d:+.0f}万")

    if net > 5000:
        score += 0.2
    elif net > 1000:
        score += 0.1
    elif net < -5000:
        score -= 0.2
    elif net < -1000:
        score -= 0.1

    if net_3d > 10000:
        score += 0.1
    elif net_3d < -10000:
        score -= 0.1

    if main_pct > 10:
        score += 0.05
        details.append(f"主力净占比{main_pct:+.1f}%")
    elif main_pct < -10:
        score -= 0.05
        details.append(f"主力净占比{main_pct:+.1f}%")

    return max(0, min(1, score)), details


# ================================================================
#  综合分析
# ================================================================

# 各维度权重
WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.25,
    "volume": 0.20,
    "position": 0.15,
    "fund_flow": 0.15,
}


def analyze_stock(code: str, push: bool = False, journal: bool = False) -> dict:
    """分析单只股票, 返回完整诊断报告

    Args:
        code: 股票代码 (6位数字)
        push: 是否推送微信
        journal: 是否写入 trade_journal (进入闭环验证)

    Returns:
        {
            code, name, price, date,
            scores: {trend, momentum, volume, position, fund_flow},
            total_score, direction, verdict, details,
            report_text,
        }
    """
    today_str = date.today().isoformat()

    # 1. 数据获取
    klines = _fetch_klines(code, days=120)
    rt = _fetch_realtime(code)
    fund = _fetch_fund_flow(code)

    if not klines:
        return {"code": code, "error": "无法获取K线数据"}

    closes = [k["close"] for k in klines]
    price = rt["price"] if rt and rt["price"] > 0 else closes[-1]
    name = rt["name"] if rt and rt.get("name") else _get_stock_name(code)

    # 将实时数据注入 closes/klines, 让技术指标反映盘中最新状态
    if rt and rt["price"] > 0:
        today_str_check = date.today().isoformat()
        last_date = klines[-1]["date"][:10] if klines else ""
        if last_date != today_str_check:
            # K线数据还没有今天的, 用实时行情构造当日K线
            today_kline = {
                "date": today_str_check,
                "open": rt.get("open", price),
                "high": rt.get("high", price),
                "low": rt.get("low", price),
                "close": price,
                "volume": rt.get("amount", 0),
                "turnover": rt.get("turnover_rate", 0),
            }
            klines = klines + [today_kline]
            closes = closes + [price]
        else:
            # K线已有今天的数据, 用实时价格覆盖收盘价
            klines[-1] = {**klines[-1], "close": price,
                          "high": max(klines[-1]["high"], price),
                          "low": min(klines[-1]["low"], price)}
            closes[-1] = price

    # 2. 五维打分
    s_trend, d_trend = _score_trend(closes, price)
    s_mom, d_mom = _score_momentum(closes)
    s_vol, d_vol = _score_volume(klines, rt)
    s_pos, d_pos = _score_position(closes, price, klines)
    s_fund, d_fund = _score_fund_flow(fund)

    scores = {
        "trend": round(s_trend, 3),
        "momentum": round(s_mom, 3),
        "volume": round(s_vol, 3),
        "position": round(s_pos, 3),
        "fund_flow": round(s_fund, 3),
    }

    total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    total = round(total, 3)

    # 3. 方向判定
    if total >= 0.65:
        direction = "bullish"
        verdict = "看多"
    elif total <= 0.35:
        direction = "bearish"
        verdict = "看空"
    else:
        direction = "neutral"
        verdict = "中性观望"

    # 4. 详细建议
    advice_parts = []
    if s_mom < 0.35:
        advice_parts.append("动量弱, 谨慎追高")
    if s_mom > 0.65:
        rsi = _calc_rsi(closes, 14)
        if rsi and rsi > 75:
            advice_parts.append(f"RSI={rsi:.0f}超买, 注意回调风险")
    if s_fund > 0.65:
        advice_parts.append("资金持续流入, 有支撑")
    if s_fund < 0.35:
        advice_parts.append("资金流出, 警惕")
    if s_pos < 0.35:
        advice_parts.append("低位区, 关注支撑")
    if s_pos > 0.7:
        advice_parts.append("高位区, 注意压力")
    if s_vol > 0.65:
        advice_parts.append("量能充足")
    if s_vol < 0.35:
        advice_parts.append("量能不足, 观望")

    # ATR 止损位
    atr = _calc_atr(klines, 14)
    stop_loss = round(price - 2 * atr, 2) if atr else None
    take_profit = round(price + 3 * atr, 2) if atr else None

    advice = "; ".join(advice_parts) if advice_parts else "指标中性, 需结合盘面判断"

    # 5. 生成报告文本
    report_lines = [
        f"个股诊断: {name}({code})",
        f"价格: {price:.2f}  涨跌: {rt['pct_change']:+.2f}%" if rt else f"价格: {price:.2f}",
        f"",
        f"综合评分: {total:.2f} → {verdict}",
        f"",
        f"[趋势] {s_trend:.2f}  {' | '.join(d_trend)}",
        f"[动量] {s_mom:.2f}  {' | '.join(d_mom)}",
        f"[量价] {s_vol:.2f}  {' | '.join(d_vol)}",
        f"[位置] {s_pos:.2f}  {' | '.join(d_pos)}",
        f"[资金] {s_fund:.2f}  {' | '.join(d_fund)}",
        f"",
        f"建议: {advice}",
    ]
    if stop_loss and take_profit:
        report_lines.append(f"参考止损: {stop_loss:.2f}  止盈: {take_profit:.2f}")
    if rt:
        report_lines.append(f"PE: {rt['pe']:.1f}  PB: {rt['pb']:.2f}  流通市值: {rt['circ_mv']/1e8:.0f}亿")

    report_text = "\n".join(report_lines)

    result = {
        "code": code,
        "name": name,
        "price": price,
        "date": today_str,
        "scores": scores,
        "total_score": total,
        "direction": direction,
        "verdict": verdict,
        "advice": advice,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "details": {
            "trend": d_trend,
            "momentum": d_mom,
            "volume": d_vol,
            "position": d_pos,
            "fund_flow": d_fund,
        },
        "report_text": report_text,
        "factor_scores": scores,  # 供 signal_tracker 用
    }

    # 6. 可选: 写入 trade_journal
    if journal:
        _write_journal(result)

    # 7. 可选: 推送微信
    if push:
        _push_wechat(result)

    return result


def _write_journal(result: dict):
    """写入 trade_journal.json, 进入 signal_tracker 闭环验证"""
    try:
        from json_store import safe_load, safe_save
        journal_path = os.path.join(_DIR, "trade_journal.json")
        journal = safe_load(journal_path, default=[])

        # 获取当前行情环境
        regime = {}
        try:
            from smart_trader import detect_market_regime
            regime = detect_market_regime()
        except Exception:
            pass

        entry = {
            "date": result["date"],
            "strategy": "个股诊断",
            "regime": regime,
            "picks": [{
                "code": result["code"],
                "name": result["name"],
                "price": result["price"],
                "total_score": result["total_score"],
                "factor_scores": result["scores"],
                "reason": f"{result['verdict']}: {result['advice']}",
            }],
        }
        journal.append(entry)
        safe_save(journal_path, journal)
        logger.info("个股诊断 %s 写入 trade_journal", result["code"])
    except Exception as e:
        logger.warning("写入 trade_journal 失败: %s", e)


def _push_wechat(result: dict):
    """推送微信"""
    try:
        from notifier import notify_wechat_raw
        title = f"个股诊断: {result['name']}({result['code']}) → {result['verdict']}"
        notify_wechat_raw(title, result["report_text"])
    except Exception as e:
        logger.warning("微信推送失败: %s", e)


# ================================================================
#  批量诊断
# ================================================================

def analyze_batch(codes: list[str], push: bool = False, journal: bool = False) -> list[dict]:
    """批量分析多只股票

    Returns:
        list of analyze_stock results, 按 total_score 降序排列
    """
    results = []
    for code in codes:
        try:
            r = analyze_stock(code, push=False, journal=journal)
            if "error" not in r:
                results.append(r)
        except Exception as e:
            logger.warning("批量分析 %s 失败: %s", code, e)

    results.sort(key=lambda x: x["total_score"], reverse=True)

    if push and results:
        try:
            from notifier import notify_wechat_raw
            lines = [f"批量诊断 ({len(results)}只)\n"]
            for r in results:
                lines.append(
                    f"{r['name']}({r['code']}) "
                    f"{r['total_score']:.2f} {r['verdict']} "
                    f"¥{r['price']:.2f}"
                )
            notify_wechat_raw("批量个股诊断", "\n".join(lines))
        except Exception:
            pass

    return results


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 stock_analyzer.py 002221           # 分析东华能源")
        print("  python3 stock_analyzer.py 002221 --push    # 分析并推微信")
        print("  python3 stock_analyzer.py 002221 --journal # 分析并入 journal")
        print("  python3 stock_analyzer.py 002221,600519    # 批量分析")
        sys.exit(0)

    codes_str = sys.argv[1]
    do_push = "--push" in sys.argv
    do_journal = "--journal" in sys.argv

    codes = [c.strip() for c in codes_str.split(",") if c.strip()]

    if len(codes) == 1:
        result = analyze_stock(codes[0], push=do_push, journal=do_journal)
        if "error" in result:
            print(f"错误: {result['error']}")
        else:
            print(result["report_text"])
    else:
        results = analyze_batch(codes, push=do_push, journal=do_journal)
        for r in results:
            print(f"\n{'='*50}")
            print(r["report_text"])
        print(f"\n共分析 {len(results)} 只")
