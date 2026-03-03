"""
ML训练数据回填器
================
用历史K线数据回填 trade_journal + scorecard,
让 ML 因子模型可以立即训练, 不用等50天。

原理:
  1. 拉CSI1000成分股过去60天日K线
  2. 每天计算因子得分 (RSI/MA/波动率/量比等)
  3. 用 T+1 实际收益率作为标签
  4. 写入 trade_journal.json + scorecard.json
  5. 触发 ML 模型训练

用法:
  python3 ml_backfill.py          # 回填60天 + 训练
  python3 ml_backfill.py --days 90  # 回填90天
"""

from __future__ import annotations

import os
import sys
import time
import numpy as np
import pandas as pd
from datetime import date, timedelta

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("ml_backfill")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(BASE_DIR, "trade_journal.json")
SCORECARD_PATH = os.path.join(BASE_DIR, "scorecard.json")


def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """计算 RSI"""
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else 50.0


def _calc_factors(df: pd.DataFrame) -> dict | None:
    """从日K线计算因子得分"""
    if df is None or len(df) < 30:
        return None

    close = df["close"]
    volume = df.get("amount", df.get("volume", pd.Series(dtype=float)))
    if volume is None or volume.empty:
        return None

    latest = close.iloc[-1]
    if latest <= 0:
        return None

    rsi = _calc_rsi(close)
    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else close.rolling(20).mean().iloc[-1]

    above_ma60 = 1.0 if latest > ma60 else 0.0
    ma_aligned = 1.0 if ma5 > ma10 > ma20 else 0.0

    # 波动率 (20日)
    returns = close.pct_change().dropna()
    volatility = float(returns.tail(20).std()) if len(returns) >= 20 else 0.15

    # 量比
    vol_ma5 = volume.rolling(5).mean().iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else vol_ma5
    vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0

    # 缩量/放量
    consecutive_vol = 0.0
    if len(volume) >= 3:
        last3 = volume.tail(3).values
        if last3[-1] > last3[-2] > last3[-3]:
            consecutive_vol = 1.0

    # 回撤
    pullback_5d = float((latest / close.iloc[-6] - 1)) if len(close) >= 6 else 0
    pullback_20d = float((latest / close.iloc[-21] - 1)) if len(close) >= 21 else 0

    # 近3日收益
    ret_3d = float((latest / close.iloc[-4] - 1)) if len(close) >= 4 else 0

    # 阻力位
    high_20d = close.tail(20).max()
    resistance_ratio = latest / high_20d if high_20d > 0 else 0.9

    # 当日涨幅
    pct_chg = float((latest / close.iloc[-2] - 1)) if len(close) >= 2 else 0

    return {
        "rsi": rsi,
        "above_ma60": above_ma60,
        "ma_aligned": ma_aligned,
        "volatility": volatility,
        "vol_ratio": vol_ratio,
        "consecutive_vol": consecutive_vol,
        "pullback_5d": pullback_5d,
        "pullback_20d": pullback_20d,
        "ret_3d": ret_3d,
        "resistance_ratio": resistance_ratio,
        "pct_chg": pct_chg,
        # 评分因子
        "s_rsi": max(0, (50 - abs(rsi - 45)) / 50),
        "s_volatility": max(0, 1 - volatility * 3),
        "s_ma_alignment": ma_aligned,
        "s_momentum": min(1, max(-1, ret_3d * 10)),
        "s_volume_breakout": min(1, max(0, (vol_ratio - 1) / 2)),
        "s_resistance_break": resistance_ratio,
    }


def backfill(days: int = 60, max_stocks: int = 100):
    """回填历史训练数据

    Args:
        days: 回填天数
        max_stocks: 每天采样股票数 (不需要全部, 采样即可)
    """
    import akshare as ak
    from api_guard import guarded_call

    print(f"=== ML训练数据回填 ({days}天, 每天{max_stocks}只) ===\n")

    # 获取股票池
    try:
        from api_guard import cached_pool
        pool_set, name_map = cached_pool()
        all_codes = list(pool_set)
    except Exception:
        print("获取股票池失败, 使用备用列表")
        all_codes = ["000001", "600000", "601398", "600036", "000858"]
        name_map = {}

    print(f"股票池: {len(all_codes)} 只")

    # 随机采样
    np.random.seed(42)
    if len(all_codes) > max_stocks:
        sample_codes = list(np.random.choice(all_codes, max_stocks, replace=False))
    else:
        sample_codes = all_codes

    # 拉K线
    print(f"拉取 {len(sample_codes)} 只股票K线...")
    kline_cache = {}
    success = 0
    for i, code in enumerate(sample_codes):
        try:
            from overnight_strategy import _tx_sym
            df = ak.stock_zh_a_hist_tx(
                symbol=_tx_sym(code),
                start_date=(date.today() - timedelta(days=days + 90)).strftime("%Y%m%d"),
                end_date=date.today().strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df is not None and len(df) >= 30:
                # 标准化列名
                if "close" not in df.columns:
                    col_map = {"收盘": "close", "开盘": "open", "最高": "high", "最低": "low"}
                    df = df.rename(columns=col_map)
                if "date" not in df.columns and "日期" in df.columns:
                    df = df.rename(columns={"日期": "date"})
                kline_cache[code] = df
                success += 1
        except Exception:
            pass

        if (i + 1) % 20 == 0:
            print(f"  进度: {i+1}/{len(sample_codes)} (成功: {success})")
        time.sleep(0.15)  # 限速

    print(f"\nK线获取完成: {success}/{len(sample_codes)} 只\n")

    if success < 20:
        print("有效股票太少, 放弃回填")
        return 0

    # 生成训练数据
    journal_entries = safe_load(JOURNAL_PATH, default=[])
    scorecard_entries = safe_load(SCORECARD_PATH, default=[])

    existing_keys = {
        (e.get("date", ""), e.get("picks", [{}])[0].get("code", "") if e.get("picks") else "")
        for e in journal_entries
    }

    new_journal = 0
    new_scorecard = 0
    trade_dates = _get_trade_dates(days)

    for trade_date in trade_dates:
        date_str = trade_date.isoformat()
        picks = []

        for code, df in kline_cache.items():
            if "date" not in df.columns:
                continue

            # 找到这个日期的位置
            df["date"] = df["date"].astype(str)
            date_mask = df["date"].str.startswith(date_str)

            if not date_mask.any():
                continue

            idx = df.index[date_mask][0]
            loc = df.index.get_loc(idx)

            # 需要至少30天历史 + 1天未来
            if loc < 30 or loc >= len(df) - 1:
                continue

            # 用截止当天的数据算因子
            hist = df.iloc[:loc + 1].copy()
            hist["close"] = hist["close"].astype(float)
            if "amount" in hist.columns:
                hist["amount"] = hist["amount"].astype(float)

            factors = _calc_factors(hist)
            if factors is None:
                continue

            # T+1 收益率作为标签
            close_today = float(df.iloc[loc]["close"])
            close_tomorrow = float(df.iloc[loc + 1]["close"])
            if close_today <= 0:
                continue
            ret_t1 = (close_tomorrow - close_today) / close_today * 100

            total_score = (
                factors.get("s_rsi", 0) * 0.1 +
                factors.get("s_volatility", 0) * 0.15 +
                factors.get("s_ma_alignment", 0) * 0.25 +
                factors.get("s_momentum", 0) * 0.15 +
                factors.get("s_volume_breakout", 0) * 0.2 +
                factors.get("s_resistance_break", 0) * 0.15
            )

            picks.append({
                "code": code,
                "name": name_map.get(code, ""),
                "total_score": round(total_score, 4),
                "factor_scores": {k: round(v, 4) for k, v in factors.items()},
            })

            # 写 scorecard
            scorecard_entries.append({
                "rec_date": date_str,
                "code": code,
                "strategy": "ml_backfill",
                "rec_price": close_today,
                "next_close": close_tomorrow,
                "net_return_pct": round(ret_t1, 4),
                "win": 1 if ret_t1 > 0 else 0,
            })
            new_scorecard += 1

        if picks:
            # 取得分最高的10只作为当天的"推荐"
            picks.sort(key=lambda x: x["total_score"], reverse=True)
            top_picks = picks[:10]

            journal_entries.append({
                "date": date_str,
                "strategy": "ml_backfill",
                "regime": {"score": 50, "regime": "neutral"},
                "picks": top_picks,
            })
            new_journal += 1

    # 保存
    safe_save(JOURNAL_PATH, journal_entries)
    safe_save(SCORECARD_PATH, scorecard_entries)

    total_samples = new_scorecard
    print(f"回填完成:")
    print(f"  trade_journal: +{new_journal} 天")
    print(f"  scorecard:     +{new_scorecard} 条样本")
    print(f"  总训练样本:    {total_samples}")

    return total_samples


def _get_trade_dates(days: int) -> list:
    """获取最近N个交易日"""
    try:
        from config import CN_HOLIDAYS_2026
    except ImportError:
        CN_HOLIDAYS_2026 = set()

    dates = []
    d = date.today() - timedelta(days=1)  # 从昨天开始
    while len(dates) < days:
        d -= timedelta(days=1)
        if d.weekday() >= 5:  # 周末
            continue
        if d.isoformat() in CN_HOLIDAYS_2026:
            continue
        dates.append(d)

    return sorted(dates)


def train_after_backfill():
    """回填后立即训练"""
    from ml_factor_model import train_model
    print("\n=== 开始ML模型训练 ===")
    result = train_model(lookback_days=180)
    if "error" in result:
        print(f"训练失败: {result['error']}")
        if result.get("error") == "insufficient_data":
            print(f"  样本量不足: {result.get('samples', 0)} (需要 >= 50)")
    else:
        metrics = result.get("metrics", {})
        print(f"训练成功!")
        print(f"  样本量: {result.get('training_samples', 0)}")
        print(f"  特征数: {len(result.get('features', []))}")
        if "r2" in metrics:
            print(f"  R²:      {metrics['r2']:.4f}")
            print(f"  RMSE:    {metrics.get('rmse', 0):.4f}")
        if "accuracy" in metrics:
            print(f"  准确率:  {metrics['accuracy']:.1%}")
        # 特征重要性 top5
        imp = result.get("feature_importance", {})
        if imp:
            top5 = sorted(imp.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"  Top5特征: {', '.join(f'{k}({v:.3f})' for k,v in top5)}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60, help="回填天数")
    parser.add_argument("--stocks", type=int, default=100, help="采样股票数")
    parser.add_argument("--no-train", action="store_true", help="只回填不训练")
    args = parser.parse_args()

    n = backfill(days=args.days, max_stocks=args.stocks)
    if n > 0 and not args.no_train:
        train_after_backfill()
    elif n == 0:
        print("无数据回填, 跳过训练")
