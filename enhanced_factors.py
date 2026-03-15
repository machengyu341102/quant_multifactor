"""
多维度增强因子模块
==================
三个新维度: 资金流向 / 龙虎榜 / 筹码压力支撑

每个维度独立 try-except, 失败不影响其他维度。
统一入口: enhance_candidates(df, name_map) → 添加 s_fund_flow, s_lhb, s_chip 三列
"""

import time
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

from overnight_strategy import _retry, _sina_market, REQUEST_DELAY
from resource_manager import get_pool


# ================================================================
#  工具函数
# ================================================================

def _zscore(series):
    """Z-score 标准化, 避免全零 std"""
    s = series.fillna(0)
    std = s.std()
    if std == 0 or np.isnan(std):
        return s * 0
    return (s - s.mean()) / std


# ================================================================
#  1. 资金流向模块
# ================================================================

def scan_fund_flow_batch(codes, top_n=300):
    """
    批量获取个股资金流向
    优先 Tushare (批量调用, ~75%命中率), 失败回退 akshare (逐只串行)

    返回 DataFrame: code, main_pct_1d, main_pct_3d, main_pct_5d,
                    flow_trend, super_large_pct, s_fund_flow
    """
    codes = list(codes)[:top_n]
    total = len(codes)
    print(f"  [增强因子] 资金流向扫描 ({total} 只)...")
    records = []

    # ---- 快速路径: Tushare 批量 (≤5次API调用 vs 50次串行) ----
    try:
        from tushare_adapter import is_available, get_money_flow_batch
        if is_available():
            batch = get_money_flow_batch(codes, days=5)
            for code, data in batch.items():
                net = data.get("net_mf_amount", 0)
                net_3d = data.get("net_mf_amount_3d", 0)
                buy_lg = data.get("buy_lg_amount", 0)
                sell_lg = data.get("sell_lg_amount", 0)
                lg_total = buy_lg + sell_lg
                main_pct = net / max(lg_total, 1) * 100 if lg_total > 0 else 0
                main_pct_3d = net_3d / max(lg_total * 3, 1) * 100 if lg_total > 0 else 0
                records.append({
                    "code": code,
                    "main_pct_1d": main_pct,
                    "main_pct_3d": main_pct_3d,
                    "main_pct_5d": main_pct * 0.6,
                    "flow_trend": main_pct - main_pct_3d,
                    "super_large_pct": (buy_lg - sell_lg) / max(lg_total, 1) * 100,
                    "consecutive_inflow": net > 0,
                })
            if records:
                print(f"    Tushare批量资金流: {len(records)} 只 ({min(5, len(codes))}次API调用)")
    except Exception as e:
        print(f"    Tushare资金流失败, 回退akshare: {e}")
        records = []

    # ---- 慢速路径: akshare 逐只串行 (仅处理Tushare未覆盖的) ----
    covered_codes = set(r["code"] for r in records)
    remaining = [c for c in codes if c not in covered_codes][:50]  # 串行最多补50只
    if remaining and len(records) < len(codes) * 0.5:
        print(f"    Akshare补充: {len(remaining)} 只 (Tushare已覆盖 {len(records)})")
        for i, code in enumerate(remaining):
            try:
                time.sleep(REQUEST_DELAY)
                market = _sina_market(code)
                df = _retry(ak.stock_individual_fund_flow, stock=code, market=market)
                if df.empty or len(df) < 3:
                    continue

                recent = df.tail(5)
                main_pct_1d = float(recent["主力净流入-净占比"].iloc[-1])
                main_pct_3d = recent["主力净流入-净占比"].tail(3).astype(float).mean()
                main_pct_5d = recent["主力净流入-净占比"].astype(float).mean()
                main_vals = recent["主力净流入-净占比"].tail(3).astype(float).values
                flow_trend = main_vals[-1] - main_vals[0]
                super_large_pct = 0.0
                if "超大单净流入-净占比" in recent.columns:
                    super_large_pct = float(recent["超大单净流入-净占比"].iloc[-1])
                consecutive_inflow = all(v > 0 for v in main_vals)

                records.append({
                    "code": code,
                    "main_pct_1d": main_pct_1d,
                    "main_pct_3d": main_pct_3d,
                    "main_pct_5d": main_pct_5d,
                    "flow_trend": flow_trend,
                    "super_large_pct": super_large_pct,
                    "consecutive_inflow": consecutive_inflow,
                })
            except Exception:
                continue
            if (i + 1) % 10 == 0:
                print(f"    资金流进度: {i + 1}/{total}, 有效: {len(records)}")

    print(f"    资金流完成: {len(records)} 只有效")

    if not records:
        return pd.DataFrame()

    flow_df = pd.DataFrame(records)

    # 打分: Z-score(主力1日净占比)*0.5 + Z-score(3日趋势)*0.3 + 超大单加分*0.2
    flow_df["s_fund_flow"] = (
        _zscore(flow_df["main_pct_1d"]) * 0.5
        + _zscore(flow_df["flow_trend"]) * 0.3
        + _zscore(flow_df["super_large_pct"]) * 0.2
    )
    # 连续3日主力净流入额外加 0.5 分
    flow_df.loc[flow_df["consecutive_inflow"], "s_fund_flow"] += 0.5

    return flow_df


# ================================================================
#  2. 龙虎榜模块
# ================================================================

def scan_lhb_signals():
    """
    获取近一月龙虎榜数据, 返回个股机构买卖信号

    返回 DataFrame: code, lhb_count, lhb_net_buy, lhb_gain,
                    inst_buy_count, inst_sell_count, inst_net_buy, s_lhb
    """
    print("  [增强因子] 龙虎榜数据获取...")
    lhb_records = {}

    # Part A: 近一月上榜统计
    try:
        stat_df = _retry(ak.stock_lhb_stock_statistic_em, symbol="近一月")
        if stat_df is not None and not stat_df.empty:
            # 列名可能包含: 序号, 代码, 名称, 上榜次数, 累积购买额, 累积卖出额, 净额, 买入席位数, 卖出席位数
            code_col = "代码" if "代码" in stat_df.columns else stat_df.columns[1]
            for _, row in stat_df.iterrows():
                code = str(row[code_col]).zfill(6)
                lhb_count = float(row.get("上榜次数", 1))
                net_buy = float(row.get("净额", 0)) if pd.notna(row.get("净额")) else 0
                # 龙虎榜涨幅
                lhb_gain = 0.0
                for col_name in stat_df.columns:
                    if "涨幅" in str(col_name):
                        lhb_gain = float(row.get(col_name, 0)) if pd.notna(row.get(col_name)) else 0
                        break
                lhb_records[code] = {
                    "code": code,
                    "lhb_count": lhb_count,
                    "lhb_net_buy": net_buy,
                    "lhb_gain": lhb_gain,
                    "inst_buy_count": 0,
                    "inst_sell_count": 0,
                    "inst_net_buy": 0.0,
                }
            print(f"    近一月上榜: {len(lhb_records)} 只")
    except Exception as e:
        print(f"    龙虎榜统计获取失败: {e}")

    # Part B: 机构买卖明细
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        inst_df = _retry(ak.stock_lhb_jgmmtj_em, start_date=start_date, end_date=end_date)
        if inst_df is not None and not inst_df.empty:
            code_col = "代码" if "代码" in inst_df.columns else inst_df.columns[1]
            for _, row in inst_df.iterrows():
                code = str(row[code_col]).zfill(6)
                # 机构买入/卖出次数和金额
                buy_count = int(row.get("买入次数", 0)) if pd.notna(row.get("买入次数")) else 0
                sell_count = int(row.get("卖出次数", 0)) if pd.notna(row.get("卖出次数")) else 0
                buy_amt = float(row.get("累积购买额", 0)) if pd.notna(row.get("累积购买额")) else 0
                sell_amt = float(row.get("累积卖出额", 0)) if pd.notna(row.get("累积卖出额")) else 0
                inst_net = buy_amt - sell_amt

                if code in lhb_records:
                    lhb_records[code]["inst_buy_count"] = buy_count
                    lhb_records[code]["inst_sell_count"] = sell_count
                    lhb_records[code]["inst_net_buy"] = inst_net
                else:
                    lhb_records[code] = {
                        "code": code,
                        "lhb_count": 0,
                        "lhb_net_buy": 0,
                        "lhb_gain": 0,
                        "inst_buy_count": buy_count,
                        "inst_sell_count": sell_count,
                        "inst_net_buy": inst_net,
                    }
            print(f"    机构买卖明细: {len(inst_df)} 条")
    except Exception as e:
        print(f"    机构买卖明细获取失败: {e}")

    if not lhb_records:
        print("    龙虎榜无数据")
        return pd.DataFrame()

    lhb_df = pd.DataFrame(list(lhb_records.values()))

    # 打分
    # 机构净买入为正 → 加分；机构卖出多于买入 → 减分
    inst_score = np.where(
        lhb_df["inst_net_buy"] > 0, 1.0,
        np.where(lhb_df["inst_sell_count"] > lhb_df["inst_buy_count"], -0.5, 0)
    )
    # 上榜次数越多关注度越高
    count_score = _zscore(lhb_df["lhb_count"])
    # 龙虎榜近1月上榜后涨幅为正 → 额外加分
    gain_bonus = np.where(lhb_df["lhb_gain"] > 0, 0.3, 0)

    lhb_df["s_lhb"] = _zscore(pd.Series(inst_score, index=lhb_df.index)) * 0.5 + count_score * 0.3 + gain_bonus

    print(f"    龙虎榜打分完成: {len(lhb_df)} 只")
    return lhb_df


# ================================================================
#  3. 筹码/压力支撑模块
# ================================================================

def scan_chip_and_support(codes, price_map=None):
    """
    获取主力成本 + 机构参与度, 计算压力支撑位

    Args:
        codes: 候选股代码列表
        price_map: dict {code: current_price}, 用于计算主力成本偏离度
                   如果不提供则从 stock_comment_em 中取

    返回 DataFrame: code, main_cost, inst_participation, support, resistance,
                    position_ratio, s_chip
    """
    print("  [增强因子] 筹码/压力支撑分析...")

    # ---- Part A: 主力成本 & 机构参与度 (批量, 一次API调全市场) ----
    comment_data = {}
    try:
        comment_df = _retry(ak.stock_comment_em)
        if comment_df is not None and not comment_df.empty:
            code_col = "代码" if "代码" in comment_df.columns else comment_df.columns[0]
            # 查找主力成本和机构参与度列
            cost_col = None
            inst_col = None
            price_col = None
            for col in comment_df.columns:
                col_str = str(col)
                if "主力成本" in col_str:
                    cost_col = col
                if "机构参与度" in col_str:
                    inst_col = col
                if col_str in ("最新价", "收盘价", "现价"):
                    price_col = col

            for _, row in comment_df.iterrows():
                code = str(row[code_col]).zfill(6)
                if code not in set(codes):
                    continue
                main_cost = float(row[cost_col]) if cost_col and pd.notna(row.get(cost_col)) else None
                inst_part = float(row[inst_col]) if inst_col and pd.notna(row.get(inst_col)) else None
                comment_price = float(row[price_col]) if price_col and pd.notna(row.get(price_col)) else None
                comment_data[code] = {
                    "main_cost": main_cost,
                    "inst_participation": inst_part,
                    "comment_price": comment_price,
                }
            print(f"    stock_comment_em 匹配: {len(comment_data)} 只")
    except Exception as e:
        print(f"    stock_comment_em 获取失败: {e}")

    # ---- Part B: 压力/支撑位 (从日K线数据计算) ----
    # 优先从 K 线缓存获取, 缺失的再拉
    from overnight_strategy import _tx_sym
    kline_cache = {}
    try:
        from intraday_strategy import get_kline_cache
        kline_cache = get_kline_cache()
    except ImportError:
        pass

    support_data = {}
    codes_list = list(codes)
    cached_count = 0
    fetch_count = 0

    for code in codes_list:
        if code in kline_cache:
            kd = kline_cache[code]
            highs = kd["high"]
            lows = kd["low"]
            closes = kd["close"]
            n = min(20, len(closes))
            if n < 10:
                continue
            support_data[code] = {
                "support": float(np.min(lows[-n:])),
                "resistance": float(np.max(highs[-n:])),
                "current_price": float(closes[-1]),
            }
            cached_count += 1

    # 仅拉缓存中不存在的
    missing = [c for c in codes_list if c not in support_data]
    if missing:
        print(f"    压力支撑: {cached_count} 只命中缓存, {len(missing)} 只需拉取...")
        for i, code in enumerate(missing):
            try:
                time.sleep(REQUEST_DELAY * 0.5)
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
                kdf = _retry(
                    ak.stock_zh_a_hist_tx,
                    symbol=_tx_sym(code),
                    start_date=start_date, end_date=end_date, adjust="qfq"
                )
                if kdf is None or kdf.empty or len(kdf) < 10:
                    continue

                closes = kdf["close"].values.astype(float)
                highs = kdf["high"].values.astype(float)
                lows = kdf["low"].values.astype(float)

                n = min(20, len(kdf))
                support_data[code] = {
                    "support": float(np.min(lows[-n:])),
                    "resistance": float(np.max(highs[-n:])),
                    "current_price": float(closes[-1]),
                }
                fetch_count += 1
            except Exception:
                continue
            if (i + 1) % 20 == 0:
                print(f"      压力支撑进度: {i + 1}/{len(missing)}")
    else:
        print(f"    压力支撑: {cached_count} 只全部命中缓存")

    print(f"    压力支撑计算完成: {len(support_data)} 只 (缓存{cached_count}/拉取{fetch_count})")

    # ---- 合并打分 ----
    records = []
    codes_set = set(codes)
    for code in codes_set:
        rec = {"code": code}

        # 主力成本得分
        cost_score = 0.0
        if code in comment_data:
            cd = comment_data[code]
            rec["main_cost"] = cd["main_cost"]
            rec["inst_participation"] = cd["inst_participation"]

            # 现价 vs 主力成本
            current = None
            if price_map and code in price_map:
                current = price_map[code]
            elif cd["comment_price"]:
                current = cd["comment_price"]
            elif code in support_data:
                current = support_data[code]["current_price"]

            if current and cd["main_cost"] and cd["main_cost"] > 0:
                deviation = (current - cd["main_cost"]) / cd["main_cost"]
                if 0 <= deviation <= 0.10:
                    cost_score = 1.0  # 略高于主力成本, 拉升意愿强
                elif 0.10 < deviation <= 0.20:
                    cost_score = 0.5  # 中等获利
                elif deviation > 0.20:
                    cost_score = -0.5  # 获利丰厚, 抛压大
                elif -0.10 <= deviation < 0:
                    cost_score = 0.3  # 主力被套, 有护盘动力
                else:
                    cost_score = -0.3  # 深度被套, 风险大
        else:
            rec["main_cost"] = None
            rec["inst_participation"] = None

        rec["cost_score"] = cost_score

        # 压力支撑位置得分
        position_score = 0.0
        if code in support_data:
            sd = support_data[code]
            rec["support"] = sd["support"]
            rec["resistance"] = sd["resistance"]
            price_range = sd["resistance"] - sd["support"]
            if price_range > 0:
                position_ratio = (sd["current_price"] - sd["support"]) / price_range
                rec["position_ratio"] = position_ratio
                # 0.3~0.7 区间最优
                if 0.3 <= position_ratio <= 0.7:
                    position_score = 1.0
                elif 0.2 <= position_ratio < 0.3 or 0.7 < position_ratio <= 0.8:
                    position_score = 0.5
                else:
                    position_score = 0.0
            else:
                rec["position_ratio"] = 0.5
        else:
            rec["support"] = None
            rec["resistance"] = None
            rec["position_ratio"] = None

        rec["position_score"] = position_score
        records.append(rec)

    if not records:
        return pd.DataFrame()

    chip_df = pd.DataFrame(records)

    # 综合打分: Z-score(主力成本偏离度)*0.4 + Z-score(机构参与度)*0.3 + Z-score(压力支撑位置)*0.3
    inst_part = chip_df["inst_participation"].fillna(0).astype(float)
    chip_df["s_chip"] = (
        _zscore(chip_df["cost_score"]) * 0.4
        + _zscore(inst_part) * 0.3
        + _zscore(chip_df["position_score"]) * 0.3
    )

    print(f"    筹码打分完成: {len(chip_df)} 只")
    return chip_df


# ================================================================
#  4. 统一入口
# ================================================================

def enhance_candidates(df, name_map):
    """
    一站式增强: 输入候选 DataFrame, 输出添加了三个新因子列的 DataFrame
    - s_fund_flow: 资金流向得分
    - s_lhb: 龙虎榜得分
    - s_chip: 筹码/压力支撑得分

    每个模块独立 try-except, 失败不影响其他维度
    """
    print("\n  === 多维度增强因子 ===")
    codes = df["code"].tolist()

    # 构建价格映射
    price_map = {}
    for _, row in df.iterrows():
        price = row.get("price", row.get("latest_close"))
        if pd.notna(price):
            price_map[row["code"]] = float(price)

    # ---- 三个子模块并行执行 ----
    def _do_fund_flow():
        try:
            return scan_fund_flow_batch(codes)
        except Exception as e:
            print(f"    资金流向获取失败, 跳过: {e}")
            return pd.DataFrame()

    def _do_lhb():
        try:
            return scan_lhb_signals()
        except Exception as e:
            print(f"    龙虎榜获取失败, 跳过: {e}")
            return pd.DataFrame()

    def _do_chip():
        try:
            return scan_chip_and_support(codes, price_map=price_map)
        except Exception as e:
            print(f"    筹码分析失败, 跳过: {e}")
            return pd.DataFrame()

    pool = get_pool("enhance_factors", max_workers=3)
    fut_flow = pool.submit(_do_fund_flow)
    fut_lhb = pool.submit(_do_lhb)
    fut_chip = pool.submit(_do_chip)
    flow_df = fut_flow.result()
    lhb_df = fut_lhb.result()
    chip_df = fut_chip.result()

    # ---- 合并资金流向 ----
    if not flow_df.empty:
        df = df.merge(
            flow_df[["code", "s_fund_flow", "main_pct_1d", "consecutive_inflow"]],
            on="code", how="left"
        )
        df["s_fund_flow"] = df["s_fund_flow"].fillna(0)
        print(f"    资金流向: 匹配 {df['s_fund_flow'].ne(0).sum()} 只")
    else:
        df["s_fund_flow"] = 0
        df["main_pct_1d"] = np.nan
        df["consecutive_inflow"] = False

    # ---- 合并龙虎榜 ----
    if not lhb_df.empty:
        df = df.merge(
            lhb_df[["code", "s_lhb", "lhb_count", "inst_net_buy"]],
            on="code", how="left"
        )
        df["s_lhb"] = df["s_lhb"].fillna(0)
        print(f"    龙虎榜: 匹配 {df['s_lhb'].ne(0).sum()} 只")
    else:
        df["s_lhb"] = 0
        df["lhb_count"] = np.nan
        df["inst_net_buy"] = np.nan

    # ---- 合并筹码 ----
    if not chip_df.empty:
        df = df.merge(
            chip_df[["code", "s_chip", "main_cost", "inst_participation"]],
            on="code", how="left"
        )
        df["s_chip"] = df["s_chip"].fillna(0)
        print(f"    筹码分析: 匹配 {df['s_chip'].ne(0).sum()} 只")
    else:
        df["s_chip"] = 0
        df["main_cost"] = np.nan
        df["inst_participation"] = np.nan

    print("  === 增强因子完成 ===\n")
    return df


def format_enhanced_labels(row):
    """
    为单行数据生成增强因子标签字符串, 用于终端输出和微信推送

    返回 dict:
      fund_flow_label: "主力净流入+3.2%" 或 ""
      lhb_label: "近月上榜2次 机构净买入" 或 ""
      chip_label: "主力成本¥12.3 机构参与度68%" 或 ""
    """
    labels = {}

    # 资金流向标签
    fund_flow_label = ""
    main_pct = row.get("main_pct_1d")
    if pd.notna(main_pct) and main_pct != 0:
        if main_pct > 0:
            fund_flow_label = f"主力净流入{main_pct:+.1f}%"
        else:
            fund_flow_label = f"主力净流出{main_pct:+.1f}%"
        if row.get("consecutive_inflow"):
            fund_flow_label += " 连续流入"
    labels["fund_flow_label"] = fund_flow_label

    # 龙虎榜标签
    lhb_label = ""
    lhb_count = row.get("lhb_count")
    inst_net = row.get("inst_net_buy")
    if pd.notna(lhb_count) and lhb_count > 0:
        lhb_label = f"近月上榜{int(lhb_count)}次"
        if pd.notna(inst_net):
            if inst_net > 0:
                lhb_label += " 机构净买入"
            elif inst_net < 0:
                lhb_label += " 机构净卖出"
    labels["lhb_label"] = lhb_label

    # 筹码标签
    chip_label = ""
    main_cost = row.get("main_cost")
    inst_part = row.get("inst_participation")
    parts = []
    if pd.notna(main_cost) and main_cost > 0:
        parts.append(f"主力成本¥{main_cost:.2f}")
    if pd.notna(inst_part) and inst_part > 0:
        parts.append(f"机构参与度{inst_part:.0f}%")
    chip_label = " ".join(parts)
    labels["chip_label"] = chip_label

    return labels
