"""
小盘短线隔夜策略 v5
====================
目标: 尾盘买入, T+1日卖出
选股池: 中证1000成分股 (天然小盘) — 全量扫描
信号体系:
  技术面: RSI超卖 / 布林下轨 / 缩量企稳 / 低波动 / 趋势回踩
  资金面: 主力净流入趋势 (新浪源个股资金流)
  热点面: 概念板块资金流排名 (新浪源概念资金流)
  基本面: 业绩报表 + 业绩预告硬过滤 + 评分 (v5新增)
  风控面: 新闻/政策风险排雷 (v5新增)
v4改进:
  全量扫描: 845只全扫, 不再随机抽样
  两阶段: 技术面全扫 → TOP40再扫资金流 (省时间)
  权重调优: RSI 15%→8%, 趋势 10%→20%, MA60下方整体降权
  收紧波动: 60%→45%
  资金流容错: 获取失败时权重自动再分配
v5改进:
  基本面硬过滤: 首亏/续亏/EPS<0/利润暴降 直接剔除
  基本面评分: 利润增长+ROE+业绩预告 (10%权重)
  新闻排雷: 关键词匹配检测政策/经营风险, 风险过高直接剔除
  新闻情绪: 正面关键词加分 (2%权重)
"""

import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import logging
import warnings

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

RETRY_TIMES = 3
REQUEST_DELAY = 0.2  # 全量扫描, 略微加快

# 新闻风险关键词及权重
RISK_KEYWORDS = {
    # 政策/监管风险
    "关税": -3, "加征关税": -5, "反倾销": -4, "制裁": -5,
    "处罚": -3, "罚款": -3, "立案": -4, "违规": -3, "整改": -2,
    # 经营风险
    "亏损": -3, "下滑": -2, "暴雷": -5, "爆雷": -5, "债务": -3,
    "减持": -2, "大幅减持": -4, "质押": -2, "冻结": -3,
    # 行业政策风险
    "限制": -2, "叫停": -4, "禁止": -4, "取消补贴": -3,
    "集采": -3, "降价": -2, "监管趋严": -3,
    # 其他
    "退市": -5, "ST": -5, "停牌": -3, "诉讼": -2,
}

POSITIVE_KEYWORDS = {
    "中标": 2, "签约": 2, "战略合作": 2, "业绩预增": 3,
    "回购": 2, "增持": 2, "突破": 1, "创新高": 1,
    "获批": 2, "专利": 1, "订单": 2,
}


def _retry(func, *args, **kwargs):
    """统一 API 调用入口 — 全部走 api_guard 限流+断路器+智能重试"""
    from api_guard import guarded_call
    return guarded_call(func, *args, source="akshare", retries=RETRY_TIMES, **kwargs)


def _tx_sym(code):
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def _sina_market(code):
    return "sh" if code.startswith(("6", "9")) else "sz"


# ================================================================
#  技术指标
# ================================================================

def calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = pd.Series(gains).rolling(period).mean().values
    avg_loss = pd.Series(losses).rolling(period).mean().values
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_bollinger(closes, period=20, num_std=2):
    s = pd.Series(closes)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    return mid.values, (mid + num_std * std).values, (mid - num_std * std).values


def calc_ma(closes, period):
    return pd.Series(closes).rolling(period).mean().values


# ================================================================
#  行业分类 (基于股票名称关键词)
# ================================================================

SECTOR_RULES = [
    ("医药", ["药", "医", "生物", "制药", "康", "健康", "诊断", "基因"]),
    ("科技", ["电子", "芯", "半导", "光电", "智能", "信息", "软件", "科技", "数据", "通信", "网络"]),
    ("金融", ["银行", "保险", "证券", "金融", "信托", "投资"]),
    ("消费", ["食品", "饮料", "酒", "乳", "农", "牧", "肉", "粮", "茶", "百货", "商业", "零售", "超市", "服饰", "家居"]),
    ("制造", ["机械", "设备", "汽车", "电机", "钢", "铝", "铜", "材料", "化工", "化学", "玻璃", "水泥"]),
    ("地产", ["地产", "置业", "房", "建设", "建工", "建筑"]),
    ("能源", ["能源", "电力", "电气", "石油", "燃气", "煤", "油", "风电", "光伏", "太阳", "新能"]),
    ("传媒", ["传媒", "文化", "影视", "游戏", "教育", "出版", "动漫"]),
]


def classify_sector(name):
    """根据股票名称关键词判断所属行业"""
    if not name:
        return "其他"
    for sector, keywords in SECTOR_RULES:
        for kw in keywords:
            if kw in name:
                return sector
    return "其他"


# ================================================================
#  数据获取
# ================================================================

def get_small_cap_pool():
    """中证1000成分股 — 全量返回"""
    print("[1/5] 获取中证1000成分股...")
    df = _retry(ak.index_stock_cons, symbol="000852")
    all_codes = df["品种代码"].tolist()
    name_map = dict(zip(df["品种代码"], df["品种名称"]))
    # 排除科创板(688)、北交所(8)、三板(4) — 腾讯源不支持; 去重
    all_codes = [c for c in all_codes if not c.startswith(("688", "8", "4"))]
    all_codes = list(dict.fromkeys(all_codes))  # 保序去重
    print(f"  全量股池: {len(all_codes)} 只 (已排除科创/北交)")
    return all_codes, name_map


def get_hot_concepts():
    """获取今日热点概念板块 (新浪源, 按资金净流入排名)

    缓存1小时避免API不稳定导致全0; 扩大领涨股范围到top30
    """
    print("[2/5] 获取今日热点概念...")

    # 缓存: 1小时内复用
    from api_guard import _global_cache
    cache_key = "hot_concepts_snapshot"
    cached = _global_cache.get(cache_key)
    if cached is not None:
        hot_names = set(cached.get("hot_names", []))
        hot_leaders = cached.get("hot_leaders", {})
        top_inflow = pd.DataFrame(cached.get("top_inflow", []))
        top_chg = pd.DataFrame(cached.get("top_chg", []))
        print(f"  热点概念: 缓存命中 ({len(hot_names)} 个, {len(hot_leaders)} 领涨股)")
        return hot_names, hot_leaders, top_inflow, top_chg

    try:
        df = _retry(ak.stock_fund_flow_concept)
        df["净额"] = pd.to_numeric(df["净额"], errors="coerce")
        df = df.sort_values("净额", ascending=False)
        top_inflow = df.head(30)  # 扩大到30
        df_by_chg = df.sort_values("行业-涨跌幅", ascending=False)
        top_chg = df_by_chg.head(30)  # 扩大到30
        hot_names = set(top_inflow["行业"].tolist() + top_chg["行业"].tolist())
        hot_leaders = {}
        for _, row in pd.concat([top_inflow, top_chg]).drop_duplicates("行业").iterrows():
            leader = str(row.get("领涨股", ""))
            if leader and leader != "nan":
                hot_leaders[leader] = row["行业"]

        # 补充: 行业资金流领涨股
        try:
            ind_df = _retry(ak.stock_fund_flow_industry)
            if ind_df is not None and not ind_df.empty:
                ind_df["净额"] = pd.to_numeric(ind_df["净额"], errors="coerce")
                top_ind = ind_df.nlargest(20, "净额")
                for _, row in top_ind.iterrows():
                    leader = str(row.get("领涨股", ""))
                    sector = str(row.get("行业", ""))
                    if leader and leader != "nan":
                        hot_leaders[leader] = sector
                        hot_names.add(sector)
                print(f"  行业资金流补充: {len(top_ind)} 个行业领涨股")
        except Exception:
            pass  # 行业补充是可选的

        print(f"  热点概念: {len(hot_names)} 个, {len(hot_leaders)} 领涨股")
        print(f"  资金净流入TOP5: {', '.join(top_inflow['行业'].head(5).tolist())}")
        print(f"  涨幅TOP5: {', '.join(top_chg['行业'].head(5).tolist())}")

        # 写入缓存 (1小时)
        try:
            _global_cache.set(cache_key, {
                "hot_names": list(hot_names),
                "hot_leaders": hot_leaders,
                "top_inflow": top_inflow.to_dict(orient="records"),
                "top_chg": top_chg.to_dict(orient="records"),
            }, 3600)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        return hot_names, hot_leaders, top_inflow, top_chg
    except Exception as e:
        print(f"  获取失败: {e}")
        return set(), {}, pd.DataFrame(), pd.DataFrame()


def _scan_one_signal(code, start_date, end_date):
    """单只股票技术信号扫描 (供线程池调用)"""
    try:
        df = _retry(
            ak.stock_zh_a_hist_tx,
            symbol=_tx_sym(code),
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        if df.empty or len(df) < 60:
            return None

        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float)
        volumes = df["amount"].values.astype(float)

        # forge 因子缓存
        try:
            from factor_forge import cache_klines_for_forge
            cache_klines_for_forge(code, df)
        except ImportError:
            pass

        rsi_vals = calc_rsi(closes, 14)
        rsi_now = rsi_vals[-1] if not np.isnan(rsi_vals[-1]) else 50

        rsi_low_days = 0
        for rv in reversed(rsi_vals):
            if not np.isnan(rv) and rv < 40:
                rsi_low_days += 1
            else:
                break

        _, boll_up, boll_low = calc_bollinger(closes, 20, 2)
        boll_width = boll_up[-1] - boll_low[-1]
        boll_pos = (closes[-1] - boll_low[-1]) / boll_width if boll_width > 0 else 0.5

        ma60 = calc_ma(closes, 60)
        above_ma60 = closes[-1] > ma60[-1] if not np.isnan(ma60[-1]) else False

        vol_5avg = np.mean(volumes[-5:])
        vol_ratio = volumes[-1] / vol_5avg if vol_5avg > 0 else 1.0

        daily_ret = np.diff(closes[-21:]) / closes[-21:-1]
        volatility = np.std(daily_ret) * np.sqrt(252) if len(daily_ret) >= 10 else 999

        high_5d = np.max(highs[-5:])
        pullback_5d = closes[-1] / high_5d - 1
        high_20d = np.max(highs[-20:])
        pullback_20d = closes[-1] / high_20d - 1

        overnight_rets = (closes[1:] - closes[:-1]) / closes[:-1]
        overnight_win_rate = np.mean(overnight_rets[-20:] > 0) if len(overnight_rets) >= 20 else 0.5

        ret_3d = closes[-1] / closes[-3] - 1 if len(closes) >= 3 else 0

        return {
            "code": code,
            "latest_close": closes[-1],
            "rsi": rsi_now,
            "rsi_low_days": rsi_low_days,
            "boll_pos": boll_pos,
            "vol_ratio": vol_ratio,
            "above_ma60": above_ma60,
            "volatility": volatility,
            "pullback_5d": pullback_5d,
            "pullback_20d": pullback_20d,
            "overnight_win_rate": overnight_win_rate,
            "ret_3d": ret_3d,
        }
    except Exception:
        return "FAIL"


def scan_signals(stock_list, days=120):
    """全量扫描技术信号 (20线程并行)"""
    from concurrent.futures import as_completed
    from resource_manager import get_pool
    total = len(stock_list)
    print(f"[3/5] 全量扫描技术信号 ({total} 只, 20线程并行)...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    results = []
    fail_count = 0
    done_count = 0

    pool = get_pool("overnight_scan_signals", max_workers=20)
    futures = {pool.submit(_scan_one_signal, code, start_date, end_date): code
               for code in stock_list}
    for fut in as_completed(futures):
        done_count += 1
        r = fut.result()
        if r is None:
            continue
        elif r == "FAIL":
            fail_count += 1
        else:
            results.append(r)
        if done_count % 50 == 0:
            print(f"  进度: {done_count}/{total}  有效: {len(results)}  失败: {fail_count}")

    print(f"  扫描完成: {len(results)} 只有效, {fail_count} 只失败")
    return pd.DataFrame(results)


def _scan_one_fund_flow(code):
    """单只股票资金流向 (供线程池调用)"""
    try:
        market = _sina_market(code)
        df = _retry(ak.stock_individual_fund_flow, stock=code, market=market)
        if df.empty or len(df) < 3:
            return None
        recent = df.tail(5)
        main_pct_1d = float(recent["主力净流入-净占比"].iloc[-1])
        main_pct_3d = recent["主力净流入-净占比"].tail(3).astype(float).mean()
        main_pct_5d = recent["主力净流入-净占比"].astype(float).mean()
        main_vals = recent["主力净流入-净占比"].tail(3).astype(float).values
        flow_trend = main_vals[-1] - main_vals[0]
        return {
            "code": code,
            "main_pct_1d": main_pct_1d,
            "main_pct_3d": main_pct_3d,
            "main_pct_5d": main_pct_5d,
            "flow_trend": flow_trend,
        }
    except Exception:
        return None


def scan_fund_flow(stock_list):
    """获取个股资金流向 (20线程并行)"""
    from concurrent.futures import as_completed
    from resource_manager import get_pool
    total = len(stock_list)
    print(f"[4/5] 扫描候选股资金流向 ({total} 只, 20线程并行)...")
    records = []
    done_count = 0

    pool = get_pool("overnight_fund_flow", max_workers=20)
    futures = {pool.submit(_scan_one_fund_flow, code): code for code in stock_list}
    for fut in as_completed(futures):
        done_count += 1
        r = fut.result()
        if r is not None:
            records.append(r)
        if done_count % 10 == 0:
            print(f"  资金流进度: {done_count}/{total}, 有效: {len(records)}")

    print(f"  获取到 {len(records)} 只股票的资金流向")
    return pd.DataFrame(records)


# ================================================================
#  基本面数据 & 新闻风控 (v5新增)
# ================================================================

def fetch_fundamental_batch():
    """批量获取基本面数据: 业绩报表 + 业绩预告

    持久化缓存: api_guard.DataCache, key=fundamental_snapshot, TTL=当日有效(6h)
    当日多策略调用只拉取一次 API, 消除冗余请求
    """
    from api_guard import _global_cache

    # 持久化缓存: 当日仅拉取一次 (TTL 6小时, 覆盖全天所有策略)
    cache_key = "fundamental_snapshot"
    cached = _global_cache.get(cache_key)
    if cached is not None:
        fund_df = pd.DataFrame(cached)
        print(f"\n[v5] 基本面数据: 缓存命中 ({len(fund_df)} 条)")
        return fund_df

    print("\n[v5] 获取基本面数据...")
    fund_df = pd.DataFrame()

    # 自动选最新报告期: 依次尝试最近几个季度
    from datetime import datetime as _dt
    _now = _dt.now()
    _quarters = []
    for _y in range(_now.year, _now.year - 2, -1):
        for _q in ["1231", "0930", "0630", "0331"]:
            _quarters.append(f"{_y}{_q}")
    _quarters = [q for q in _quarters if q <= _now.strftime("%Y%m%d")][:4]

    # 业绩报表 (EPS, 营收增长, 利润增长, ROE等)
    try:
        yjbb = None
        for _qdate in _quarters:
            try:
                yjbb = _retry(ak.stock_yjbb_em, date=_qdate)
                if yjbb is not None and len(yjbb) > 500:
                    print(f"  业绩报表: 使用报告期 {_qdate}")
                    break
                yjbb = None
            except Exception:
                continue
        if yjbb is None:
            raise ValueError("所有报告期均无数据")
        yjbb = yjbb.rename(columns={
            "股票代码": "code",
            "每股收益": "eps",
            "营业收入-同比增长": "revenue_growth",
            "净利润-同比增长": "profit_growth",
            "净资产收益率": "roe",
            "销售毛利率": "gross_margin",
        })
        cols_keep = ["code", "eps", "revenue_growth", "profit_growth", "roe", "gross_margin"]
        cols_exist = [c for c in cols_keep if c in yjbb.columns]
        yjbb = yjbb[cols_exist].copy()
        for col in cols_exist:
            if col != "code":
                yjbb[col] = pd.to_numeric(yjbb[col], errors="coerce")
        print(f"  业绩报表: {len(yjbb)} 条记录")
        fund_df = yjbb
    except Exception as e:
        print(f"  警告: 业绩报表获取失败: {e}")

    # 业绩预告 (预增/首亏/续亏等)
    try:
        yjyg = None
        for _qdate in _quarters:
            try:
                yjyg = _retry(ak.stock_yjyg_em, date=_qdate)
                if yjyg is not None and len(yjyg) > 100:
                    print(f"  业绩预告: 使用报告期 {_qdate}")
                    break
                yjyg = None
            except Exception:
                continue
        if yjyg is None:
            raise ValueError("所有报告期均无业绩预告")
        yjyg = yjyg
        yjyg = yjyg.rename(columns={
            "股票代码": "code",
            "预告类型": "forecast_type",
        })
        yjyg = yjyg[["code", "forecast_type"]].drop_duplicates(subset="code", keep="first")
        print(f"  业绩预告: {len(yjyg)} 条记录")
        if fund_df.empty:
            fund_df = yjyg
        else:
            fund_df = fund_df.merge(yjyg, on="code", how="outer")
    except Exception as e:
        print(f"  警告: 业绩预告获取失败: {e}")

    if fund_df.empty:
        print("  警告: 基本面数据全部获取失败, 将跳过基本面过滤和评分")
        # 负缓存: 失败后5分钟不重试, 避免频繁请求
        try:
            _global_cache.set(cache_key, [], 300)
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
    else:
        print(f"  基本面数据合并完成: {len(fund_df)} 条记录")
        # 写入持久化缓存 (TTL 6小时 = 21600s, 覆盖全天所有策略)
        try:
            _global_cache.set(cache_key, fund_df.to_dict(orient="records"), 21600)
        except Exception:
            pass  # 缓存写入失败不影响主流程
    return fund_df


def apply_fundamental_filters(df, fund_df):
    """基本面硬过滤: 首亏/续亏/EPS<0/利润暴降 直接剔除"""
    if fund_df.empty:
        print("  基本面数据为空, 跳过基本面硬过滤")
        return df

    merged = df.merge(fund_df, on="code", how="left")

    # 1. 首亏/续亏剔除
    before = len(merged)
    if "forecast_type" in merged.columns:
        bad_forecast = merged["forecast_type"].str.contains("首亏|续亏", na=False)
        removed_forecast = merged[bad_forecast][["code", "name", "forecast_type"]].copy()
        merged = merged[~bad_forecast].copy()
        n_removed = before - len(merged)
        print(f"  基本面过滤 - 首亏/续亏剔除: {n_removed} 只")
        if len(removed_forecast) > 0:
            samples = [f"{r['code']}({r['name']},{r['forecast_type']})"
                       for _, r in removed_forecast.head(5).iterrows()]
            print(f"    样例: {', '.join(samples)}")

    # 2. EPS<0剔除
    before = len(merged)
    if "eps" in merged.columns:
        eps_bad = merged["eps"].fillna(0) < 0
        removed_eps = merged[eps_bad][["code", "name", "eps"]].copy()
        merged = merged[~eps_bad].copy()
        n_removed = before - len(merged)
        print(f"  基本面过滤 - EPS<0剔除: {n_removed} 只")
        if len(removed_eps) > 0:
            samples = [f"{r['code']}({r['name']},EPS={r['eps']:.2f})"
                       for _, r in removed_eps.head(5).iterrows()]
            print(f"    样例: {', '.join(samples)}")

    # 3. 利润暴降剔除 (净利润同比增长率 < -50%)
    before = len(merged)
    if "profit_growth" in merged.columns:
        profit_bad = merged["profit_growth"].fillna(0) < -50
        removed_profit = merged[profit_bad][["code", "name", "profit_growth"]].copy()
        merged = merged[~profit_bad].copy()
        n_removed = before - len(merged)
        print(f"  基本面过滤 - 利润暴降(<-50%)剔除: {n_removed} 只")
        if len(removed_profit) > 0:
            samples = [f"{r['code']}({r['name']},{r['profit_growth']:+.1f}%)"
                       for _, r in removed_profit.head(5).iterrows()]
            print(f"    样例: {', '.join(samples)}")

    print(f"  基本面过滤后剩余: {len(merged)} 只")
    return merged


def calc_fundamental_scores(df, fund_df):
    """基本面评分: 利润增长(5%) + ROE(3%) + 业绩预告(2%)"""
    if fund_df.empty:
        df["s_fundamental"] = 0
        return df

    def zscore(s):
        std = s.std()
        return (s - s.mean()) / std if std > 0 else s * 0

    # 确保基本面字段存在 (apply_fundamental_filters已merge过)
    if "profit_growth" not in df.columns:
        df = df.merge(fund_df[["code"] + [c for c in ["profit_growth", "roe", "forecast_type"] if c in fund_df.columns]],
                      on="code", how="left", suffixes=("", "_fund"))

    # 利润增长得分 — 仅对有数据的股票zscore, 无数据给中性0
    s_profit = pd.Series(0.0, index=df.index)
    if "profit_growth" in df.columns:
        _mask = df["profit_growth"].notna()
        if _mask.sum() > 5:
            s_profit[_mask] = zscore(df.loc[_mask, "profit_growth"].clip(-100, 500))

    # ROE得分 — 同上
    s_roe = pd.Series(0.0, index=df.index)
    if "roe" in df.columns:
        _mask = df["roe"].notna()
        if _mask.sum() > 5:
            s_roe[_mask] = zscore(df.loc[_mask, "roe"].clip(-50, 100))

    # 业绩预告得分
    if "forecast_type" in df.columns:
        forecast_map = {
            "预增": 1.0, "略增": 1.0, "扭亏": 0.5,
            "续盈": 0.3, "略减": -0.5, "预减": -1.0,
            "首亏": -1.0, "续亏": -1.0,  # 理论上已被过滤
        }
        df["s_forecast"] = df["forecast_type"].map(forecast_map).fillna(0)
    else:
        df["s_forecast"] = 0

    # 合成基本面得分 (内部按5:3:2比例)
    df["s_fundamental"] = (
        (s_profit * 0.5 if isinstance(s_profit, pd.Series) else 0) +
        (s_roe * 0.3 if isinstance(s_roe, pd.Series) else 0) +
        df["s_forecast"] * 0.2
    )

    return df


def _screen_one_news(code, name_map):
    """单只股票新闻排雷 (供线程池调用)"""
    risk_score = 0
    positive_score = 0
    risk_kws = []
    positive_kws = []
    try:
        news_df = _retry(ak.stock_news_em, symbol=code)
        if news_df is not None and not news_df.empty:
            news_texts = news_df.head(10)
            col_title = "新闻标题" if "新闻标题" in news_df.columns else news_df.columns[0]
            col_content = "新闻内容" if "新闻内容" in news_df.columns else (news_df.columns[1] if len(news_df.columns) > 1 else col_title)
            all_text = " ".join(
                news_texts[col_title].fillna("").astype(str).tolist() +
                news_texts[col_content].fillna("").astype(str).tolist()
            )

            for kw, weight in RISK_KEYWORDS.items():
                count = all_text.count(kw)
                if count > 0:
                    risk_score += weight * count
                    risk_kws.append(f"{kw}({count}次)")

            for kw, weight in POSITIVE_KEYWORDS.items():
                count = all_text.count(kw)
                if count > 0:
                    positive_score += weight * count
                    positive_kws.append(f"{kw}({count}次)")
    except Exception as _exc:
        logger.warning("Suppressed exception: %s", _exc)

    return {
        "code": code,
        "risk_score": risk_score,
        "positive_score": positive_score,
        "risk_keywords": risk_kws,
        "positive_keywords": positive_kws,
    }


def news_risk_screen(codes, name_map):
    """
    新闻/政策风险排雷 (20线程并行)
    返回: (safe_codes, risk_info, news_scores)
    """
    from concurrent.futures import as_completed
    from resource_manager import get_pool
    print(f"\n[v5] 新闻风险排雷 ({len(codes)} 只候选, 20线程并行)...")
    risk_info = {}
    news_scores = {}

    pool = get_pool("overnight_news_screen", max_workers=20)
    futures = {pool.submit(_screen_one_news, code, name_map): code for code in codes}
    for fut in as_completed(futures):
        r = fut.result()
        code = r["code"]
        risk_info[code] = r
        news_scores[code] = (r["positive_score"] + r["risk_score"]) / 10.0

        name = name_map.get(code, "")
        if r["risk_keywords"]:
            print(f"  {code} {name}: 风险={r['risk_score']} [{', '.join(r['risk_keywords'])}]"
                  + (f" | 正面=[{', '.join(r['positive_keywords'])}]" if r["positive_keywords"] else ""))
        elif r["positive_keywords"]:
            print(f"  {code} {name}: 正面=[{', '.join(r['positive_keywords'])}]")

    # 剔除高风险
    safe_codes = []
    removed = []
    for code in codes:
        info = risk_info[code]
        if info["risk_score"] < -4:
            removed.append(f"{code}({name_map.get(code, '')},风险={info['risk_score']},"
                           f"关键词=[{','.join(info['risk_keywords'])}])")
        else:
            safe_codes.append(code)

    if removed:
        print(f"\n  新闻排雷剔除: {len(removed)} 只")
        for r in removed:
            print(f"    {r}")
    print(f"  新闻排雷后剩余: {len(safe_codes)} 只")

    return safe_codes, risk_info, news_scores


# ================================================================
#  选股打分
# ================================================================

def score_and_select(df, fund_df=None, top_n=10):
    """
    综合打分 v5 (基本面+新闻风控)

      技术面 49%:
        1. RSI超卖            6%
        2. 布林带下轨          6%
        3. 缩量企稳            7%
        4. 低波动率           13%
        5. 趋势 (MA60)       17%
      资金面 20%:
        6. 主力净流入(今日)    8%
        7. 主力资金趋势(3日)   12%
      情绪面 11%:
        8. 隔夜历史胜率         6%
        9. 热点概念加分         5%
      基本面 10%:
        10. 基本面综合         10%
      新闻情绪 2%:
        11. 新闻情绪得分        2% (在news_risk_screen后加入)
    """
    print("[5/5] 综合打分...")

    # --- 硬性过滤 ---
    before = len(df)
    df = df[df["volatility"] < 0.60].copy()  # 放宽: 45%→60% (学习需要更多数据)
    print(f"  过滤高波动(>60%): 剔除 {before - len(df)} 只")

    before = len(df)
    df = df[df["pullback_20d"] > -0.35].copy()  # 放宽: -25%→-35%
    print(f"  过滤暴跌股(20日回撤>35%): 剔除 {before - len(df)} 只")

    before = len(df)
    df = df[df["ret_3d"] < 0.12].copy()  # 放宽: 8%→12%
    print(f"  过滤近3日已大涨(>12%): 剔除 {before - len(df)} 只")

    # --- 阴跌过滤 (慢性失血) ---
    before = len(df)
    chronic_mask = (~df["above_ma60"]) & (df["rsi_low_days"] >= 5)
    chronic_removed = df[chronic_mask][["code", "name", "rsi", "rsi_low_days"]].copy()
    df = df[~chronic_mask].copy()
    print(f"  过滤阴跌慢性失血(MA60下方+RSI<40连续≥5天): 剔除 {before - len(df)} 只")
    if len(chronic_removed) > 0:
        samples = [f"{r['code']}({r['name']},RSI低{r['rsi_low_days']}天)"
                   for _, r in chronic_removed.head(5).iterrows()]
        print(f"    剔除样例: {', '.join(samples)}")

    print(f"  技术面过滤后剩余: {len(df)} 只")

    # --- 基本面硬过滤 (v5新增) ---
    if fund_df is not None and not fund_df.empty:
        df = apply_fundamental_filters(df, fund_df)
    else:
        print("  跳过基本面硬过滤 (无数据)")

    if len(df) == 0:
        print("  警告: 过滤后无股票, 请检查参数")
        return df, df

    def zscore(s):
        std = s.std()
        return (s - s.mean()) / std if std > 0 else s * 0

    # ---- 技术面打分 ----
    df["s_rsi"] = -zscore(df["rsi"].clip(10, 90))
    df["s_boll"] = -zscore(df["boll_pos"].clip(0, 1))
    df["s_vol"] = -zscore(df["vol_ratio"].clip(0.1, 3))
    df["s_volatility"] = -zscore(df["volatility"])

    # 趋势得分: MA60上方=强正, 下方=负; 5日回踩3%-15%加分
    trend_raw = np.where(df["above_ma60"], 1.0, -0.5)
    pull_bonus = np.where(
        (df["pullback_5d"] < -0.03) & (df["pullback_5d"] > -0.15), 1.0,
        np.where(df["pullback_5d"] < -0.15, -0.5, 0)
    )
    df["s_trend"] = zscore(pd.Series(trend_raw + pull_bonus, index=df.index))

    # ---- 资金面打分 ----
    has_flow = "main_pct_1d" in df.columns and df["main_pct_1d"].notna().sum() > 5
    if has_flow:
        df["s_flow_1d"] = zscore(df["main_pct_1d"].fillna(0))
        df["s_flow_trend"] = zscore(df["flow_trend"].fillna(0))
        w_flow_1d, w_flow_trend = 0.08, 0.12
    else:
        # 资金流缺失: 20%权重再分配给趋势(+12%)和波动率(+8%)
        df["s_flow_1d"] = 0
        df["s_flow_trend"] = 0
        w_flow_1d, w_flow_trend = 0, 0
        print("  ⚠ 资金流数据缺失, 权重再分配: 趋势+12%, 波动率+8%")

    # ---- 情绪面打分 ----
    df["s_overnight"] = zscore(df["overnight_win_rate"])
    if "hot_score" in df.columns:
        df["s_hot"] = zscore(df["hot_score"])
    else:
        df["s_hot"] = 0

    # ---- 基本面打分 (v5新增) ----
    if fund_df is not None and not fund_df.empty:
        df = calc_fundamental_scores(df, fund_df)
    else:
        df["s_fundamental"] = 0

    # ---- 加权合成 (v7: 从tunable_params读取, 支持学习引擎在线调权) ----
    try:
        from auto_optimizer import get_tunable_params
        tp = get_tunable_params("overnight")
        weights = tp.get("weights", {})
    except Exception:
        weights = {}

    if not weights:
        from config import OVERNIGHT_PARAMS
        weights = OVERNIGHT_PARAMS["weights"].copy()

    w_rsi = weights.get("s_rsi", 0.08)
    w_boll = weights.get("s_boll", 0.15)
    w_vol = weights.get("s_vol", 0.18)
    w_volatility = weights.get("s_volatility", 0.10)
    w_trend = weights.get("s_trend", 0.10)
    w_overnight = weights.get("s_overnight", 0.15)
    w_hot = weights.get("s_hot", 0.02)
    w_fundamental = weights.get("s_fundamental", 0.02)

    # 资金流缺失时再分配给有效因子 (vol+boll)
    if not has_flow:
        w_vol += 0.10
        w_boll += 0.10

    df["total_score"] = (
        df["s_rsi"] * w_rsi +
        df["s_boll"] * w_boll +
        df["s_vol"] * w_vol +
        df["s_volatility"] * w_volatility +
        df["s_trend"] * w_trend +
        df["s_flow_1d"] * w_flow_1d +
        df["s_flow_trend"] * w_flow_trend +
        df["s_overnight"] * w_overnight +
        df["s_hot"] * w_hot +
        df["s_fundamental"] * w_fundamental
    )

    # forge 因子钩子: 注入 s_forge_* 列 + 叠加得分
    try:
        from factor_forge import compute_forge_factors, get_forge_weights
        df = compute_forge_factors(df)
        forge_w = get_forge_weights()
        for col, w in forge_w.items():
            if col in df.columns:
                df["total_score"] += df[col].fillna(0) * w
    except ImportError:
        pass

    # 跨市场 regime 调整: Risk Off 降权, Risk On 略加分
    try:
        from cross_asset_factor import get_risk_multiplier
        risk_mult = get_risk_multiplier()
        if abs(risk_mult - 1.0) > 0.001:
            df["total_score"] *= risk_mult
            label = "RiskOn加分" if risk_mult > 1.0 else "RiskOff降权"
            print(f"  跨市场regime调整(x{risk_mult:.2f}): {label}")
    except ImportError:
        pass

    # ---- MA60下方整体降权 ----
    # 不在MA60上方的, 总分打8折
    below_ma60_mask = ~df["above_ma60"]
    df.loc[below_ma60_mask, "total_score"] *= 0.8
    below_count = below_ma60_mask.sum()
    if below_count > 0:
        print(f"  MA60下方降权(×0.8): 影响 {below_count} 只")

    # ML 融合: 规则分 + ML预测 → fused_score
    try:
        from ml_factor_model import predict_scores, fuse_scores
        candidates = []
        for _, row in df.iterrows():
            fs = {c: float(row[c]) for c in row.index
                  if c.startswith("s_") and pd.notna(row.get(c))}
            candidates.append({
                "code": row.get("code", ""),
                "factor_scores": fs,
                "total_score": float(row.get("total_score", 0)),
            })
        candidates = predict_scores(candidates, strategy="隔夜选股")
        candidates = fuse_scores(candidates)
        ml_scores = {c["code"]: c for c in candidates if c.get("code")}
        for idx, row in df.iterrows():
            info = ml_scores.get(row.get("code", ""), {})
            if info.get("fused_score") is not None:
                df.at[idx, "total_score"] = info["fused_score"]
        ml_active = sum(1 for c in candidates if abs(c.get("ml_score", 0)) > 0.001)
        if ml_active > 0:
            print(f"  [ML融合] {ml_active}/{len(candidates)} 只获得ML预测 (策略: 隔夜选股)")
    except ImportError:
        pass
    except Exception as e:
        print(f"  [ML融合跳过] {e}")

    df = df.sort_values("total_score", ascending=False)

    # ---- 得分阈值过滤: 剔除低分垃圾信号 ----
    min_score_threshold = 0.30  # 数据分析显示: <0.2得分的信号胜率仅40.9%, -0.47%均收益
    df = df[df["total_score"] >= min_score_threshold]
    if len(df) == 0:
        print(f"  ⚠️ 得分阈值{min_score_threshold}过滤后无候选, 返回空")
        return pd.DataFrame(), pd.DataFrame()
    print(f"  得分阈值过滤: ≥{min_score_threshold} 保留 {len(df)} 只")

    # ---- 行业分散约束: 同行业最多2只 ----
    df["sector"] = df["name"].apply(classify_sector)
    sector_count = {}
    selected_idx = []
    skipped_sector = []
    for idx, row in df.iterrows():
        sec = row["sector"]
        cnt = sector_count.get(sec, 0)
        if cnt < 2:
            selected_idx.append(idx)
            sector_count[sec] = cnt + 1
        else:
            skipped_sector.append(f"{row['code']}({row['name']},{sec})")
        if len(selected_idx) >= top_n:
            break
    selected = df.loc[selected_idx]
    if skipped_sector:
        print(f"  行业分散: 跳过 {len(skipped_sector)} 只(行业已满2只)")
        print(f"    跳过样例: {', '.join(skipped_sector[:5])}")
    sec_dist = selected["sector"].value_counts()
    print(f"  最终行业分布: {dict(sec_dist)}")

    # 全量候选写入缓冲区 (实盘数据采集, 同 score_and_rank)
    try:
        import intraday_strategy as _is
        _is._scored_buffer = []
        for _, row in df.iterrows():
            fs = {c: float(row[c]) for c in row.index
                  if c.startswith("s_") and pd.notna(row.get(c))}
            if not fs:
                continue
            _is._scored_buffer.append({
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "price": float(row.get("close", row.get("price", 0))),
                "score": float(row.get("total_score", 0)),
                "factor_scores": fs,
            })
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return selected, df


# ================================================================
#  回测
# ================================================================

def _backtest_one(code, name_map, start_date, end_date, lookback):
    """单只股票回测 (供并行调用)"""
    try:
        df = _retry(
            ak.stock_zh_a_hist_tx,
            symbol=_tx_sym(code), start_date=start_date, end_date=end_date, adjust="qfq"
        )
        if len(df) < lookback + 1:
            return None
        closes = df["close"].values[-lookback - 1:]
        daily_rets = (closes[1:] - closes[:-1]) / closes[:-1]
        return {
            "code": code,
            "name": name_map.get(code, ""),
            "avg_daily_ret": np.mean(daily_rets),
            "win_rate": np.mean(daily_rets > 0),
            "max_single_loss": np.min(daily_rets),
            "cumulative": np.prod(1 + daily_rets) - 1,
        }
    except Exception:
        return None


def backtest_overnight(selected_codes, name_map, lookback=10):
    print(f"\n[回测] 过去 {lookback} 个交易日隔夜持有模拟...")
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=lookback * 3)).strftime("%Y%m%d")

    from concurrent.futures import as_completed
    from resource_manager import get_pool
    all_overnight = []
    pool = get_pool("overnight_backtest", max_workers=10)
    futures = {
        pool.submit(_backtest_one, code, name_map, start_date, end_date, lookback): code
        for code in selected_codes
    }
    for fut in as_completed(futures):
        result = fut.result()
        if result is not None:
            all_overnight.append(result)

    if not all_overnight:
        print("  无有效回测数据")
        return None

    ret_df = pd.DataFrame(all_overnight)
    return {
        "日均收益": f"{ret_df['avg_daily_ret'].mean():.2%}",
        "平均胜率": f"{ret_df['win_rate'].mean():.0%}",
        f"{lookback}日累计收益": f"{ret_df['cumulative'].mean():.2%}",
        "单日最大亏损": f"{ret_df['max_single_loss'].min():.2%}",
        "持仓数量": len(ret_df),
        "个股明细": ret_df.sort_values("cumulative", ascending=False),
    }


# ================================================================
#  主流程
# ================================================================

def run(top_n=10, fund_flow_top=100):
    print("=" * 65)
    print("  小盘短线隔夜策略 v5 (基本面+新闻风控+全量扫描+行业分散)")
    print(f"  运行日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)

    # 第1步: 全量股池
    stock_list, name_map = get_small_cap_pool()

    # 第2步: 热点概念
    hot_names, hot_leaders, top_inflow_df, top_chg_df = get_hot_concepts()

    # 第3步: 全量技术信号扫描
    signals_df = scan_signals(stock_list)
    signals_df["name"] = signals_df["code"].map(name_map)

    # 热点概念加分
    signals_df["is_hot_leader"] = signals_df["name"].isin(hot_leaders.keys())
    signals_df["hot_concept"] = signals_df["name"].map(hot_leaders).fillna("")
    signals_df["hot_score"] = np.where(signals_df["is_hot_leader"], 2.0, 0)

    # 第4步: 两阶段 — 先粗筛再精扫资金流
    temp_df = signals_df.copy()
    temp_df = temp_df[temp_df["volatility"] < 0.60]
    temp_df = temp_df[temp_df["pullback_20d"] > -0.35]
    temp_df = temp_df[temp_df["ret_3d"] < 0.12]
    temp_df["_rough"] = (
        -temp_df["rsi"] * 0.3 +
        temp_df["above_ma60"].astype(float) * 30 +
        -temp_df["volatility"] * 20 +
        temp_df["overnight_win_rate"] * 10
    )
    temp_df = temp_df.sort_values("_rough", ascending=False)
    candidates = temp_df.head(fund_flow_top)["code"].tolist()
    print(f"\n  技术面粗筛TOP{fund_flow_top}: {len(candidates)} 只进入资金流扫描")

    # 扫描资金流 (只扫候选)
    flow_df = scan_fund_flow(candidates)

    # 合并资金流
    if flow_df.empty:
        df = signals_df.copy()
    else:
        df = signals_df.merge(flow_df, on="code", how="left")
    df = df.drop_duplicates(subset="code", keep="first")

    # 额外: 主力资金连续3日净流入加分
    if "main_pct_3d" in df.columns:
        df["hot_score"] += np.where(df["main_pct_3d"] > 3, 1.0, 0)

    # [v5新增] 批量获取基本面数据
    fund_df = fetch_fundamental_batch()

    # 第5步: 综合打分选股 (含基本面硬过滤+评分)
    selected, full_df = score_and_select(df, fund_df=fund_df, top_n=top_n)

    if len(selected) == 0:
        print("\n  无法选出股票, 请检查市场数据")
        return None

    # [v5新增] 新闻风险排雷 — 对打分后TOP20执行
    news_candidates_n = min(20, len(full_df))
    news_candidate_codes = full_df.head(news_candidates_n)["code"].tolist()
    safe_codes, risk_info, news_scores = news_risk_screen(news_candidate_codes, name_map)

    # 将新闻情绪得分加入total_score (2%权重)
    w_news = 0.02
    full_df["s_news"] = full_df["code"].map(news_scores).fillna(0)
    full_df["total_score"] = full_df["total_score"] + full_df["s_news"] * w_news

    # 从安全列表中按得分排名选取最终TOP N (行业分散)
    safe_df = full_df[full_df["code"].isin(safe_codes)].sort_values("total_score", ascending=False)
    sector_count = {}
    final_idx = []
    for idx, row in safe_df.iterrows():
        sec = row.get("sector", "其他")
        cnt = sector_count.get(sec, 0)
        if cnt < 2:
            final_idx.append(idx)
            sector_count[sec] = cnt + 1
        if len(final_idx) >= top_n:
            break
    selected = safe_df.loc[final_idx] if final_idx else safe_df.head(top_n)

    if len(selected) < top_n:
        print(f"\n  注意: 新闻排雷后仅剩 {len(selected)} 只 (不足{top_n}只)")

    # ---- 输出: 热点概念 ----
    print("\n" + "=" * 65)
    print("  今日市场热点概念 (资金净流入TOP10)")
    print("=" * 65)
    if not top_inflow_df.empty:
        for _, row in top_inflow_df.head(10).iterrows():
            print(f"    {row['行业']:　<8} 净流入: {row['净额']:>7.1f}亿  "
                  f"涨幅: {row['行业-涨跌幅']:>+5.2f}%  领涨: {row['领涨股']}")

    # ---- 输出: 选股结果 ----
    print("\n" + "=" * 65)
    print(f"  今日隔夜候选 TOP {len(selected)}  (全量{len(signals_df)}只中选出)")
    print("=" * 65)

    for rank, (_, row) in enumerate(selected.iterrows(), 1):
        rsi_tag = "超卖" if row["rsi"] < 30 else "偏弱" if row["rsi"] < 40 else "中性" if row["rsi"] < 55 else "偏强"
        trend_tag = "趋势↑" if row["above_ma60"] else "趋势↓"
        vol_tag = f"缩量{1-row['vol_ratio']:.0%}" if row["vol_ratio"] < 1 else f"放量{row['vol_ratio']-1:.0%}"

        flow_1d = row.get("main_pct_1d", 0) or 0
        flow_3d = row.get("main_pct_3d", 0) or 0
        flow_tag = "主力流入" if flow_1d > 0 else "主力流出"
        flow_trend_tag = "资金好转↑" if (row.get("flow_trend", 0) or 0) > 0 else "资金恶化↓"

        hot_tag = f"[热点:{row['hot_concept']}]" if row.get("hot_concept") else ""
        sector_tag = f"[{row.get('sector', '其他')}]"
        chronic_tag = f" RSI低{row['rsi_low_days']}天" if row.get("rsi_low_days", 0) > 0 else ""

        # 基本面标签 (v5新增)
        fund_tags = []
        if "profit_growth" in row.index and pd.notna(row.get("profit_growth")):
            fund_tags.append(f"利润增长={row['profit_growth']:+.1f}%")
        if "roe" in row.index and pd.notna(row.get("roe")):
            fund_tags.append(f"ROE={row['roe']:.1f}%")
        if "forecast_type" in row.index and pd.notna(row.get("forecast_type")) and row.get("forecast_type"):
            fund_tags.append(f"预告:{row['forecast_type']}")
        fund_label = "  ".join(fund_tags) if fund_tags else "无数据"

        # 新闻风险标签 (v5新增)
        code = row["code"]
        news_tag = ""
        if code in risk_info:
            info = risk_info[code]
            if info["risk_keywords"]:
                news_tag = f" ⚠风险:[{','.join(info['risk_keywords'])}]"
            if info["positive_keywords"]:
                news_tag += f" ✓正面:[{','.join(info['positive_keywords'])}]"

        print(f"""
  {rank:>2}. {row['code']} {row.get('name',''):　<8} {sector_tag} | 得分: {row['total_score']:+.3f} | 价格: {row['latest_close']:.2f} {hot_tag}
      技术: RSI={row['rsi']:.1f}({rsi_tag})  布林={row['boll_pos']:.0%}  {vol_tag}  波动={row['volatility']:.0%}  {trend_tag}{chronic_tag}
      资金: 今日{flow_tag}({flow_1d:+.1f}%)  3日均({flow_3d:+.1f}%)  {flow_trend_tag}
      基本面: {fund_label}
      风控: 5日回调={row['pullback_5d']:.1%}  隔夜胜率={row['overnight_win_rate']:.0%}{news_tag}""")

    # ---- 回测 ----
    result = backtest_overnight(selected["code"].tolist(), name_map, lookback=10)
    if result:
        print("\n" + "-" * 55)
        print("  过去10个交易日隔夜持有回测")
        print("-" * 55)
        detail = result.pop("个股明细")
        for k, v in result.items():
            print(f"  {k}: {v}")
        print("\n  个股回测明细:")
        for _, r in detail.iterrows():
            print(f"    {r['code']} {r.get('name',''):　<8} "
                  f"日均={r['avg_daily_ret']:+.2%}  胜率={r['win_rate']:.0%}  "
                  f"累计={r['cumulative']:+.2%}  最大亏={r['max_single_loss']:+.2%}")

    # 保存
    output = "overnight_result_v5.csv"
    full_df.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n完整排名已保存至: {output}")
    return selected


if __name__ == "__main__":
    selected = run(top_n=10, fund_flow_top=40)
