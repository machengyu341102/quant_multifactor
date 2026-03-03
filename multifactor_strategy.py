"""
A股多因子选股量化交易策略 v2
==============================
改进点:
  1. 动量反转过滤: 20日涨但5日跌超阈值 → 惩罚
  2. 波动率惩罚: 高波动个股扣分
  3. 低基数成长修正: 去年EPS过低导致的虚高增速打折
  4. 行业中性化: 因子在行业内部标准化，避免行业偏差
数据源: akshare (腾讯行情 + 东方财富财务)
"""

import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

RETRY_TIMES = 3
REQUEST_DELAY = 0.3


def _retry_request(func, *args, **kwargs):
    """统一 API 调用入口 — 全部走 api_guard 限流+断路器+智能重试"""
    from api_guard import guarded_call
    return guarded_call(func, *args, source="akshare", retries=RETRY_TIMES, **kwargs)


def _to_tx_symbol(code):
    """纯数字代码 → 腾讯格式 sz000001 / sh600000"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _to_em_symbol(code):
    """纯数字代码 → 东方财富格式 000001.SZ / 600000.SH"""
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    return f"{code}.SH"


# ================================================================
#  1. 数据获取
# ================================================================

def get_stock_pool(pool_size=50):
    """获取沪深300成分股"""
    print("[1/5] 获取股票池...")
    df = _retry_request(ak.index_stock_cons, symbol="000300")
    stock_list = df["品种代码"].tolist()[:pool_size]
    name_map = dict(zip(df["品种代码"], df["品种名称"]))
    print(f"  股票池: 沪深300取前 {len(stock_list)} 只")
    return stock_list, name_map


def get_price_data(stock_list, days=90):
    """
    获取行情数据(腾讯源)
    新增: 日收益率序列 → 计算波动率、动量反转信号
    """
    print("[2/5] 获取行情数据...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    records = []

    for i, code in enumerate(stock_list):
        try:
            time.sleep(REQUEST_DELAY)
            df = _retry_request(
                ak.stock_zh_a_hist,
                symbol=code, start_date=start_date, end_date=end_date, adjust="qfq"
            )
            if df.empty or len(df) < 20:
                continue

            closes = df["收盘"].values
            daily_ret = np.diff(closes) / closes[:-1]

            ret_20 = closes[-1] / closes[-20] - 1
            ret_5 = closes[-1] / closes[-5] - 1 if len(closes) >= 5 else np.nan
            volatility_20d = np.std(daily_ret[-20:]) * np.sqrt(252)  # 年化波动率

            # 20日区间内最高价到最新价的回撤
            high_20 = df["最高"].iloc[-20:].max()
            drawdown_20d = closes[-1] / high_20 - 1

            records.append({
                "code": code,
                "ret_20d": ret_20,
                "ret_5d": ret_5,
                "volatility_20d": volatility_20d,
                "drawdown_20d": drawdown_20d,
                "latest_close": closes[-1],
            })
        except Exception:
            continue
        if (i + 1) % 10 == 0:
            print(f"  行情进度: {i + 1}/{len(stock_list)}")

    print(f"  获取到 {len(records)} 只股票的行情数据")
    return pd.DataFrame(records)


def get_financial_data(stock_list):
    """
    获取财务指标 + 上一期EPS(用于低基数修正)
    """
    print("[3/5] 获取财务数据...")
    records = []

    for i, code in enumerate(stock_list):
        try:
            time.sleep(REQUEST_DELAY)
            df = _retry_request(
                ak.stock_financial_analysis_indicator_em,
                symbol=_to_em_symbol(code)
            )
            if df.empty:
                continue

            def safe_float(val, default=np.nan):
                try:
                    v = float(val)
                    return v if not pd.isna(v) else default
                except (ValueError, TypeError):
                    return default

            latest = df.iloc[0]
            # 上一年同期数据(用于低基数判断)
            prev_eps = np.nan
            if len(df) >= 4:
                prev_eps = safe_float(df.iloc[3].get("EPSJB"))  # 同比对应的上年同期
            elif len(df) >= 2:
                prev_eps = safe_float(df.iloc[1].get("EPSJB"))

            records.append({
                "code": code,
                "roe": safe_float(latest.get("ROEJQ")),
                "gross_margin": safe_float(latest.get("XSMLL")),
                "revenue_growth": safe_float(latest.get("TOTALOPERATEREVETZ")),
                "net_profit_growth": safe_float(latest.get("PARENTNETPROFITTZ")),
                "debt_ratio": safe_float(latest.get("ZCFZL")),
                "eps": safe_float(latest.get("EPSJB")),
                "bps": safe_float(latest.get("BPS")),
                "prev_eps": prev_eps,
                "report_date": str(latest.get("REPORT_DATE", ""))[:10],
            })
        except Exception:
            continue
        if (i + 1) % 10 == 0:
            print(f"  财务进度: {i + 1}/{len(stock_list)}")

    print(f"  获取到 {len(records)} 只股票的财务数据")
    return pd.DataFrame(records)


def get_industry_data(stock_list):
    """获取行业分类 (东方财富)"""
    print("[4/5] 获取行业分类...")
    records = []
    for i, code in enumerate(stock_list):
        try:
            time.sleep(REQUEST_DELAY)
            df = _retry_request(ak.stock_individual_info_em, symbol=code)
            info = dict(zip(df["item"], df["value"]))
            records.append({
                "code": code,
                "industry": info.get("行业", "未知"),
            })
        except Exception:
            records.append({"code": code, "industry": "未知"})
        if (i + 1) % 10 == 0:
            print(f"  行业进度: {i + 1}/{len(stock_list)}")

    print(f"  获取到 {len(records)} 只股票的行业数据")
    return pd.DataFrame(records)


# ================================================================
#  2. 四层防护: 因子修正与过滤
# ================================================================

def apply_momentum_reversal_filter(df):
    """
    【防护1】动量反转过滤
    - 如果20日涨但近5日跌超10%, 动量因子打折
    - 如果20日区间内回撤超20%, 额外惩罚
    """
    print("  [防护1] 动量反转过滤...")
    # 动量衰减系数: 5日大跌 → 打折
    reversal_penalty = np.where(
        (df["ret_20d"] > 0) & (df["ret_5d"] < -0.10),
        0.3,   # 20日涨但5日跌超10%: 动量只保留30%
        np.where(
            (df["ret_20d"] > 0) & (df["ret_5d"] < -0.05),
            0.6,   # 5日跌5~10%: 保留60%
            1.0    # 正常
        )
    )
    df["ret_20d_adj"] = df["ret_20d"] * reversal_penalty

    # 额外: 20日内从高点回撤超20%的直接标记
    df["momentum_crash"] = df["drawdown_20d"] < -0.20

    filtered_count = df["momentum_crash"].sum()
    discounted_count = (reversal_penalty < 1.0).sum()
    print(f"    动量打折: {discounted_count} 只, 回撤过大标记: {filtered_count} 只")
    return df


def apply_volatility_penalty(df):
    """
    【防护2】波动率惩罚
    - 年化波动率作为负向因子
    - 波动率超过80%的极端妖股直接剔除
    """
    print("  [防护2] 波动率惩罚...")
    before = len(df)
    df = df[df["volatility_20d"] < 0.80].copy()
    print(f"    剔除极端高波动: {before - len(df)} 只 (年化波动率>80%)")
    # 波动率作为负向因子，后续标准化时取反
    return df


def apply_low_base_growth_correction(df):
    """
    【防护3】低基数成长修正
    - 如果上年同期EPS < 0.3, 成长因子增速打折
    - 如果上年同期EPS < 0, 成长因子归零
    逻辑: 去年亏损/微利 → 今年同比+400%没意义
    """
    print("  [防护3] 低基数成长修正...")
    EPS_THRESHOLD = 0.3

    # 计算修正系数
    growth_discount = np.where(
        df["prev_eps"].isna(),
        0.5,  # 无上期数据的保守处理
        np.where(
            df["prev_eps"] <= 0,
            0.0,   # 上年亏损 → 同比增速无意义,归零
            np.where(
                df["prev_eps"] < EPS_THRESHOLD,
                df["prev_eps"] / EPS_THRESHOLD,  # 线性打折: EPS=0.15 → 保留50%
                1.0
            )
        )
    )
    df["revenue_growth_adj"] = df["revenue_growth"] * growth_discount
    df["net_profit_growth_adj"] = df["net_profit_growth"] * growth_discount

    corrected = (growth_discount < 1.0).sum()
    zeroed = (growth_discount == 0).sum()
    print(f"    成长因子打折: {corrected} 只, 其中归零: {zeroed} 只")
    return df


def apply_industry_neutralization(df, factor_cols):
    """
    【防护4】行业中性化
    - 每个因子在行业内部做Z-Score标准化
    - 行业内不足3只股票的,归入"其他"大组统一处理
    """
    print("  [防护4] 行业中性化...")

    # 行业内样本不足3只的合并为"其他"
    industry_counts = df["industry"].value_counts()
    small_industries = industry_counts[industry_counts < 3].index.tolist()
    df["industry_group"] = df["industry"].apply(
        lambda x: "其他" if x in small_industries or x == "未知" else x
    )

    n_groups = df["industry_group"].nunique()
    print(f"    行业分组: {n_groups} 个 (含'其他'组)")

    # 行业内Z-Score
    for col in factor_cols:
        if col not in df.columns:
            continue
        df[col] = df.groupby("industry_group")[col].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )

    return df


# ================================================================
#  3. 基础因子处理
# ================================================================

def winsorize(series, lower=0.05, upper=0.95):
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


def zscore_normalize(series):
    mean, std = series.mean(), series.std()
    if std == 0:
        return series * 0
    return (series - mean) / std


def process_factors(df, factor_cols, ascending_better=None):
    """缩尾 → 标准化 (行业中性化之前的全局预处理)"""
    if ascending_better is None:
        ascending_better = {}
    for col in factor_cols:
        if col not in df.columns:
            continue
        df[col] = winsorize(df[col])
        df[col] = zscore_normalize(df[col])
        if ascending_better.get(col, False):
            df[col] = -df[col]
    return df


def calc_composite_score(df, factor_weights):
    """加权合成综合得分"""
    df["composite_score"] = 0.0
    total_weight = sum(factor_weights.values())
    for factor, weight in factor_weights.items():
        if factor in df.columns:
            df["composite_score"] += df[factor].fillna(0) * (weight / total_weight)
    return df


# ================================================================
#  4. 回测
# ================================================================

def simple_backtest(selected_codes, hold_days=20):
    """等权持有N天回测"""
    print(f"\n[回测] 等权持有 {hold_days} 个交易日...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=hold_days * 2)).strftime("%Y%m%d")

    returns = []
    for code in selected_codes:
        try:
            time.sleep(REQUEST_DELAY)
            df = _retry_request(
                ak.stock_zh_a_hist,
                symbol=code, start_date=start_date, end_date=end_date, adjust="qfq"
            )
            if len(df) < hold_days:
                continue
            buy_price = df["收盘"].iloc[-hold_days]
            sell_price = df["收盘"].iloc[-1]
            ret = (sell_price / buy_price) - 1
            returns.append({"code": code, "return": ret})
        except Exception:
            continue

    if not returns:
        print("  回测无有效数据")
        return None

    ret_df = pd.DataFrame(returns)
    avg_ret = ret_df["return"].mean()
    win_rate = (ret_df["return"] > 0).mean()

    try:
        bench = _retry_request(ak.stock_zh_index_daily, symbol="sh000300")
        bench = bench.tail(hold_days + 1)
        bench_ret = (bench["close"].iloc[-1] / bench["close"].iloc[0]) - 1
    except Exception:
        bench_ret = np.nan

    return {
        "组合平均收益": f"{avg_ret:.2%}",
        "胜率": f"{win_rate:.2%}",
        "基准收益(沪深300)": f"{bench_ret:.2%}" if not np.isnan(bench_ret) else "N/A",
        "超额收益": f"{avg_ret - bench_ret:.2%}" if not np.isnan(bench_ret) else "N/A",
        "持仓数量": len(ret_df),
        "个股明细": ret_df.sort_values("return", ascending=False),
    }


# ================================================================
#  5. 主流程
# ================================================================

def run_strategy(pool_size=50, top_n=10):
    print("=" * 60)
    print("    A股多因子选股量化策略 v2 (含四层防护)")
    print(f"    运行日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # ---- 数据获取 ----
    stock_list, name_map = get_stock_pool(pool_size)
    price_df = get_price_data(stock_list)
    fin_df = get_financial_data(stock_list)
    ind_df = get_industry_data(stock_list)

    # ---- 合并 ----
    print("[5/5] 因子修正与选股...")
    df = price_df.merge(fin_df, on="code", how="inner")
    df = df.merge(ind_df, on="code", how="left")
    df["name"] = df["code"].map(name_map)
    df["industry"] = df["industry"].fillna("未知")
    print(f"  合并后有效样本: {len(df)} 只")

    # 计算PE/PB
    df["pe"] = np.where(df["eps"] > 0, df["latest_close"] / df["eps"], np.nan)
    df["pb"] = np.where(df["bps"] > 0, df["latest_close"] / df["bps"], np.nan)

    # 基本过滤
    df = df.dropna(subset=["pe", "pb", "roe"]).copy()
    df = df[(df["pe"] > 0) & (df["pb"] > 0)].copy()
    print(f"  基本过滤后: {len(df)} 只")

    # 保存原始值用于最终展示
    raw_cols = {
        "pe_raw": df["pe"].copy(),
        "pb_raw": df["pb"].copy(),
        "roe_raw": df["roe"].copy(),
        "revenue_growth_raw": df["revenue_growth"].copy(),
        "net_profit_growth_raw": df["net_profit_growth"].copy(),
        "volatility_raw": df["volatility_20d"].copy(),
        "ret_20d_raw": df["ret_20d"].copy(),
        "ret_5d_raw": df["ret_5d"].copy(),
        "drawdown_raw": df["drawdown_20d"].copy(),
        "prev_eps_raw": df["prev_eps"].copy(),
    }

    # ======== 四层防护 ========
    print()
    df = apply_momentum_reversal_filter(df)       # 防护1
    df = apply_volatility_penalty(df)             # 防护2
    df = apply_low_base_growth_correction(df)     # 防护3

    # 用修正后的因子替换原始因子
    df["ret_20d"] = df["ret_20d_adj"]
    df["revenue_growth"] = df["revenue_growth_adj"]
    df["net_profit_growth"] = df["net_profit_growth_adj"]

    # 剔除动量崩溃标记的股票
    before = len(df)
    df = df[~df["momentum_crash"]].copy()
    print(f"  剔除动量崩溃(20日回撤>20%): {before - len(df)} 只")
    print(f"  四层防护后剩余: {len(df)} 只")

    if len(df) < top_n:
        print(f"  样本不足 {top_n} 只，请增大 pool_size")
        return df

    # ======== 全局因子标准化 ========
    factor_cols = ["pe", "pb", "ret_20d", "roe", "revenue_growth",
                   "net_profit_growth", "debt_ratio", "gross_margin",
                   "volatility_20d"]
    ascending_better = {"pe": True, "pb": True, "debt_ratio": True, "volatility_20d": True}
    df = process_factors(df, factor_cols, ascending_better)

    # ======== 防护4: 行业中性化 ========
    neutralize_cols = ["pe", "pb", "roe", "gross_margin", "revenue_growth",
                       "net_profit_growth", "debt_ratio"]
    df = apply_industry_neutralization(df, neutralize_cols)

    # ======== 加权打分 ========
    factor_weights = {
        "pe": 0.12,
        "pb": 0.08,
        "roe": 0.18,
        "gross_margin": 0.08,
        "revenue_growth": 0.13,
        "net_profit_growth": 0.10,
        "ret_20d": 0.10,            # 已含反转修正
        "debt_ratio": 0.08,
        "volatility_20d": 0.13,     # 新增: 波动率惩罚
    }
    df = calc_composite_score(df, factor_weights)

    # ======== 排名选股 ========
    df = df.sort_values("composite_score", ascending=False)
    selected = df.head(top_n).copy()

    # 恢复原始值用于展示
    for col_name, raw_series in raw_cols.items():
        df[col_name] = raw_series
        if col_name in raw_series.index.intersection(selected.index):
            selected[col_name] = raw_series

    # 重新对齐 selected
    selected = df.head(top_n).copy()

    # ======== 输出 ========
    print("\n" + "=" * 70)
    print(f"  多因子选股 TOP {top_n} (v2 含四层防护)")
    print("=" * 70)

    for rank, (_, row) in enumerate(selected.iterrows(), 1):
        pe_raw = row.get("pe_raw", np.nan)
        roe_raw = row.get("roe_raw", np.nan)
        rev_raw = row.get("revenue_growth_raw", np.nan)
        vol_raw = row.get("volatility_raw", np.nan)
        ret5_raw = row.get("ret_5d_raw", np.nan)
        prev_eps = row.get("prev_eps_raw", np.nan)

        print(f"\n  {rank:>2}. {row['code']} {row.get('name',''):　<6} "
              f"| 行业: {row.get('industry','?'):　<6} "
              f"| 得分: {row['composite_score']:+.3f} "
              f"| 价格: {row['latest_close']:.2f}")
        print(f"      PE={pe_raw:.1f}  ROE={roe_raw:.1f}%  "
              f"营收增长={rev_raw:.1f}%  "
              f"波动率={vol_raw:.0%}  "
              f"5日涨跌={ret5_raw:.1%}  "
              f"上期EPS={prev_eps:.2f}")

    # ======== 回测 ========
    result = simple_backtest(selected["code"].tolist(), hold_days=20)
    if result:
        print("\n" + "-" * 50)
        print("  近20个交易日回测结果")
        print("-" * 50)
        detail = result.pop("个股明细")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print("\n  个股收益明细:")
        print(detail.to_string(index=False))

    # ======== 保存 ========
    output_file = "multifactor_result_v2.csv"
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\n完整排名已保存至: {output_file}")

    return df


if __name__ == "__main__":
    result_df = run_strategy(pool_size=300, top_n=10)
