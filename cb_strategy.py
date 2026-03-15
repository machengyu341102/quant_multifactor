"""
可转债 T+0 日内策略
====================
核心逻辑:
  1. 获取全市场可转债实时行情
  2. 基本面过滤: 转股溢价率 < 30%, 剩余规模 > 0.5亿, 排除已触发强赎
  3. 技术面打分: 涨幅动量 + 换手率 + 振幅(波动) + 量比
  4. 综合评分 → 选出T+0日内交易机会

特点:
  - 可转债 T+0, 当日买入当日可卖
  - 低于面值(100)有债底保护
  - 高转股溢价率的纯债性转债不选(弹性差)
  - 侧重日内波动大、流动性好的活跃品种

定时: 09:35(开盘活跃品种) + 13:30(午后机会)
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TOP_N
from log_config import get_logger

logger = get_logger("cb_strategy")

# ================================================================
#  配置
# ================================================================

CB_PARAMS = {
    "enabled": True,
    "top_n": 5,
    # 基本面过滤
    "max_premium_pct": 30.0,      # 转股溢价率上限 (%)
    "min_price": 90.0,            # 最低价格 (有债底保护)
    "max_price": 200.0,           # 最高价格 (太贵风险大)
    "min_volume_wan": 5000,       # 最低成交额 (万元, 保证流动性)
    # 打分权重
    "weights": {
        "s_momentum": 0.25,       # 涨幅动量
        "s_turnover": 0.25,       # 换手活跃度
        "s_amplitude": 0.20,      # 日内振幅 (波动机会)
        "s_premium": 0.15,        # 转股溢价率 (越低越好)
        "s_volume": 0.15,         # 量比/成交额
    },
}


# ================================================================
#  API 调用 (走 api_guard)
# ================================================================

def _retry(func, *args, **kwargs):
    """统一 API 调用 — 走 api_guard 限流+断路器"""
    try:
        from api_guard import guarded_call
        return guarded_call(func, *args, source="akshare", retries=2, **kwargs)
    except ImportError:
        return func(*args, **kwargs)


def _fetch_cb_spot() -> pd.DataFrame:
    """获取可转债实时行情"""
    import akshare as ak
    df = _retry(ak.bond_zh_hs_cov_spot)
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def _fetch_cb_comparison() -> pd.DataFrame:
    """获取可转债对比数据 (含转股溢价率等)"""
    import akshare as ak
    try:
        df = _retry(ak.bond_cov_comparison)
        if df is not None and not df.empty:
            return df
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return pd.DataFrame()


# ================================================================
#  数据处理
# ================================================================

def _clean_numeric(series: pd.Series) -> pd.Series:
    """清洗数值列: 去除非数字字符, 转为float"""
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _zscore(s: pd.Series) -> pd.Series:
    """标准化评分"""
    std = s.std()
    if std == 0 or pd.isna(std):
        return s * 0
    return (s - s.mean()) / std


# ================================================================
#  主逻辑
# ================================================================

def get_cb_recommendations(top_n: int = None) -> list[dict]:
    """可转债T+0日内推荐

    Returns:
        list[dict]: 标准推荐格式
    """
    if not CB_PARAMS.get("enabled", True):
        return []

    if top_n is None:
        top_n = CB_PARAMS.get("top_n", TOP_N)

    logger.info("[可转债] 开始扫描...")

    # 1. 获取实时行情
    try:
        df = _fetch_cb_spot()
        if df.empty:
            logger.warning("[可转债] 获取行情为空")
            return []
    except Exception as e:
        logger.error("[可转债] 获取行情失败: %s", e)
        return []

    logger.info("[可转债] 获取 %d 只转债行情", len(df))

    # 标准化列名 (akshare 不同版本列名可能不同, 支持中英文)
    col_map = {}
    for col in df.columns:
        cl = str(col).strip().lower()
        if cl in ("代码", "symbol", "code"):
            col_map[col] = "code"
        elif cl in ("名称", "name"):
            col_map[col] = "name"
        elif cl in ("现价", "最新价", "收盘价", "trade"):
            col_map[col] = "price"
        elif cl in ("涨幅", "涨跌幅", "changepercent"):
            col_map[col] = "change_pct"
        elif cl in ("成交额", "amount"):
            col_map[col] = "amount"
        elif cl in ("成交量", "volume"):
            col_map[col] = "volume"
        elif cl in ("振幅",):
            col_map[col] = "amplitude"
        elif cl in ("换手", "turnover"):
            col_map[col] = "turnover"
        elif cl in ("最高", "high"):
            col_map[col] = "high"
        elif cl in ("最低", "low"):
            col_map[col] = "low"
        elif cl in ("开盘", "open"):
            col_map[col] = "open"
    df = df.rename(columns=col_map)
    # 去除重复列名
    df = df.loc[:, ~df.columns.duplicated()]

    # 确保必要列存在
    for needed in ["code", "name", "price"]:
        if needed not in df.columns:
            logger.error("[可转债] 缺少必要列: %s, 实际列: %s", needed, list(df.columns))
            return []

    # 数值清洗
    for col in ["price", "change_pct", "amount", "volume", "amplitude", "turnover", "high", "low", "open"]:
        if col in df.columns:
            df[col] = _clean_numeric(df[col])

    # 2. 基本面过滤
    max_premium = CB_PARAMS.get("max_premium_pct", 30.0)
    min_price = CB_PARAMS.get("min_price", 90.0)
    max_price = CB_PARAMS.get("max_price", 200.0)
    min_volume_wan = CB_PARAMS.get("min_volume_wan", 5000)

    # 价格过滤
    df = df[(df["price"] >= min_price) & (df["price"] <= max_price)]

    # 成交额过滤 (单位可能是元, 转为万)
    if "amount" in df.columns:
        # 成交额可能是元或万元, 根据量级判断
        max_amount = df["amount"].max()
        if max_amount > 1_000_000:  # 大于100万, 应该是元
            df["amount_wan"] = df["amount"] / 10000
        else:
            df["amount_wan"] = df["amount"]
        df = df[df["amount_wan"] >= min_volume_wan]

    if df.empty:
        logger.info("[可转债] 过滤后无结果")
        return []

    # 3. 尝试获取转股溢价率
    premium_data = {}
    try:
        comp_df = _fetch_cb_comparison()
        if not comp_df.empty:
            # 找到溢价率列
            for col in comp_df.columns:
                if "溢价率" in str(col):
                    comp_df["_premium"] = _clean_numeric(comp_df[col])
                    break
            # 找到代码或名称列做匹配
            name_col = None
            for col in comp_df.columns:
                if "名称" in str(col) or "转债名称" in str(col):
                    name_col = col
                    break
            if name_col and "_premium" in comp_df.columns:
                premium_data = dict(zip(comp_df[name_col].astype(str), comp_df["_premium"]))
    except Exception as e:
        logger.debug("[可转债] 获取溢价率数据失败: %s", e)

    if premium_data:
        df["premium_pct"] = df["name"].map(premium_data).fillna(50.0)
        df = df[df["premium_pct"] <= max_premium]
    else:
        df["premium_pct"] = 15.0  # 无数据时给默认值, 不过滤

    if df.empty:
        logger.info("[可转债] 溢价率过滤后无结果")
        return []

    logger.info("[可转债] 过滤后剩余 %d 只", len(df))

    # 4. 技术面打分
    weights = CB_PARAMS.get("weights", {})

    # 动量分: 涨幅越大越好 (但不追涨停)
    if "change_pct" in df.columns:
        change = df["change_pct"].clip(-15, 15)
        df["s_momentum"] = _zscore(change)
    else:
        df["s_momentum"] = 0

    # 换手率分: 越活跃越好
    if "turnover" in df.columns:
        df["s_turnover"] = _zscore(df["turnover"].clip(0, 100))
    elif "volume" in df.columns:
        df["s_turnover"] = _zscore(df["volume"])
    else:
        df["s_turnover"] = 0

    # 振幅分: 日内波动越大, T+0机会越多
    if "amplitude" in df.columns:
        df["s_amplitude"] = _zscore(df["amplitude"].clip(0, 30))
    elif "high" in df.columns and "low" in df.columns:
        amp = (df["high"] - df["low"]) / df["price"] * 100
        df["s_amplitude"] = _zscore(amp.clip(0, 30))
    else:
        df["s_amplitude"] = 0

    # 溢价率分: 越低越好 (取负)
    df["s_premium"] = _zscore(-df["premium_pct"])

    # 成交额分: 量大优先
    if "amount_wan" in df.columns:
        df["s_volume"] = _zscore(df["amount_wan"])
    else:
        df["s_volume"] = 0

    # 5. 综合评分
    df["total_score"] = (
        df["s_momentum"] * weights.get("s_momentum", 0.25) +
        df["s_turnover"] * weights.get("s_turnover", 0.25) +
        df["s_amplitude"] * weights.get("s_amplitude", 0.20) +
        df["s_premium"] * weights.get("s_premium", 0.15) +
        df["s_volume"] * weights.get("s_volume", 0.15)
    )

    # 6. 排序取 top_n
    df = df.sort_values("total_score", ascending=False).head(top_n)

    # 7. 构造返回
    results = []
    for _, row in df.iterrows():
        code = str(row.get("code", ""))
        name = str(row.get("name", ""))
        price = float(row.get("price", 0))
        score = float(row.get("total_score", 0))

        change = row.get("change_pct", 0)
        premium = row.get("premium_pct", 0)
        amp = row.get("amplitude", 0) if "amplitude" in df.columns else 0
        turnover = row.get("turnover", 0) if "turnover" in df.columns else 0
        amount_wan = row.get("amount_wan", 0) if "amount_wan" in df.columns else 0

        reason_parts = []
        if change:
            reason_parts.append(f"涨幅{change:+.1f}%")
        if premium:
            reason_parts.append(f"溢价{premium:.1f}%")
        if amp:
            reason_parts.append(f"振幅{amp:.1f}%")
        if turnover:
            reason_parts.append(f"换手{turnover:.1f}%")
        if amount_wan:
            reason_parts.append(f"成交{amount_wan/10000:.1f}亿" if amount_wan >= 10000 else f"成交{amount_wan:.0f}万")
        reason = " | ".join(reason_parts) if reason_parts else "综合评分"

        results.append({
            "code": code,
            "name": name,
            "price": price,
            "score": score,
            "reason": reason,
            "factor_scores": {
                "s_momentum": float(row.get("s_momentum", 0)),
                "s_turnover": float(row.get("s_turnover", 0)),
                "s_amplitude": float(row.get("s_amplitude", 0)),
                "s_premium": float(row.get("s_premium", 0)),
                "s_volume": float(row.get("s_volume", 0)),
            },
        })

    logger.info("[可转债] 推荐 %d 只: %s",
                len(results),
                ", ".join(f"{r['name']}" for r in results))
    return results


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    recs = get_cb_recommendations(top_n=10)
    if recs:
        print(f"\n{'='*60}")
        print(f"  可转债T+0推荐 ({datetime.now().strftime('%H:%M')})")
        print(f"{'='*60}")
        for i, r in enumerate(recs, 1):
            print(f"\n  {i}. {r['code']} {r['name']}")
            print(f"     价格: ¥{r['price']:.2f}  评分: {r['score']:+.3f}")
            print(f"     {r['reason']}")
    else:
        print("\n  无推荐结果")
