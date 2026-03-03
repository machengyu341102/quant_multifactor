"""
新闻事件驱动选股策略
==================
开盘前扫描宏观新闻 → 识别重大事件 → 映射到受益概念板块 → 选股

用法:
  python3 news_event_strategy.py           # 完整运行 (扫描+选股)
  python3 news_event_strategy.py scan      # 仅扫描新闻, 不选股
"""

import re
import sys
import os
import time
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intraday_strategy import (
    _sina_batch_quote, filter_basics, score_and_rank,
    _retry_heavy,
)
from overnight_strategy import (
    fetch_fundamental_batch, calc_fundamental_scores,
    news_risk_screen,
)
from enhanced_factors import enhance_candidates, format_enhanced_labels
from config import NEWS_EVENT_PARAMS, TOP_N
from log_config import get_logger

logger = get_logger("news_event")


# ================================================================
#  1. 新闻扫描 — scan_macro_news()
# ================================================================

def scan_macro_news() -> list[dict]:
    """拉取 CCTV 新闻标题 (前一晚+当天早间)

    Returns:
        [{title: str, date: str}, ...]
    """
    news = []
    try:
        df = _retry_heavy(ak.news_cctv, date=datetime.now().strftime("%Y%m%d"))
        if df is not None and not df.empty:
            title_col = "title" if "title" in df.columns else df.columns[0]
            date_col = "date" if "date" in df.columns else (
                df.columns[1] if len(df.columns) > 1 else None
            )
            for _, row in df.iterrows():
                news.append({
                    "title": str(row[title_col]),
                    "date": str(row[date_col]) if date_col else "",
                })
    except Exception as e:
        logger.warning("CCTV新闻获取失败: %s", e)

    # 尝试昨日新闻 (补充前一晚)
    if len(news) < 3:
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = _retry_heavy(ak.news_cctv, date=yesterday)
            if df is not None and not df.empty:
                title_col = "title" if "title" in df.columns else df.columns[0]
                date_col = "date" if "date" in df.columns else (
                    df.columns[1] if len(df.columns) > 1 else None
                )
                for _, row in df.iterrows():
                    news.append({
                        "title": str(row[title_col]),
                        "date": str(row[date_col]) if date_col else "",
                    })
        except Exception:
            pass

    print(f"  新闻扫描: 获取 {len(news)} 条新闻标题")
    return news


# ================================================================
#  2. 事件识别 — detect_events()
# ================================================================

def detect_events(news: list[dict]) -> list[dict]:
    """关键词匹配, 识别事件类型 + 置信度

    Returns:
        [{event_type: str, keywords: str, matched_titles: [str],
          concepts: [str], confidence: float}, ...]
    """
    event_map = NEWS_EVENT_PARAMS.get("event_concept_map", {})
    min_confidence = NEWS_EVENT_PARAMS.get("min_event_confidence", 0.3)

    all_titles = " ".join(n.get("title", "") for n in news)
    events = []
    seen_types = set()

    for keywords_str, concepts in event_map.items():
        keywords = keywords_str.split("|")
        pattern = re.compile("|".join(re.escape(kw) for kw in keywords))

        matched_titles = []
        match_count = 0
        for n in news:
            title = n.get("title", "")
            if pattern.search(title):
                matched_titles.append(title)
                match_count += 1

        if match_count == 0:
            continue

        # 置信度: 基于匹配条数 / 总条数, 最高 0.95
        confidence = min(0.95, match_count / max(len(news), 1) * 3)

        if confidence < min_confidence:
            continue

        # 去重: 同类事件只保留一次
        event_key = keywords_str
        if event_key in seen_types:
            continue
        seen_types.add(event_key)

        events.append({
            "event_type": keywords_str,
            "keywords": keywords_str,
            "matched_titles": matched_titles[:3],
            "concepts": concepts,
            "confidence": round(confidence, 3),
        })

    # 按置信度排序
    events.sort(key=lambda x: x["confidence"], reverse=True)
    print(f"  事件识别: 发现 {len(events)} 类事件")
    for e in events:
        print(f"    [{e['confidence']:.2f}] {e['event_type'][:20]}... → {', '.join(e['concepts'])}")

    return events


# ================================================================
#  3. 概念板块模糊匹配 — find_concept_boards()
# ================================================================

def find_concept_boards(target_concepts: list[str]) -> list[dict]:
    """从东财概念板块中模糊匹配目标概念

    Returns:
        [{board_name: str, pct: float, target: str}, ...]
    """
    try:
        df = _retry_heavy(ak.stock_board_concept_name_em)
        if df is None or df.empty:
            return []
    except Exception as e:
        logger.warning("概念板块获取失败: %s", e)
        return []

    # 找列名
    name_col = None
    for c in ["板块名称", "名称"]:
        if c in df.columns:
            name_col = c
            break
    if not name_col:
        name_col = df.columns[0]

    pct_col = None
    for c in ["涨跌幅", "最新涨跌幅"]:
        if c in df.columns:
            pct_col = c
            break
    if not pct_col and len(df.columns) > 1:
        pct_col = df.columns[1]

    if pct_col:
        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")

    board_names = df[name_col].tolist()

    matched = []
    seen = set()
    for target in target_concepts:
        for i, bn in enumerate(board_names):
            bn_str = str(bn)
            if target in bn_str or bn_str in target:
                if bn_str in seen:
                    continue
                seen.add(bn_str)
                pct = float(df.iloc[i][pct_col]) if pct_col else 0.0
                matched.append({
                    "board_name": bn_str,
                    "pct": pct,
                    "target": target,
                })

    # 按涨幅排序
    matched.sort(key=lambda x: x["pct"], reverse=True)

    max_boards = NEWS_EVENT_PARAMS.get("max_concept_boards", 5)
    matched = matched[:max_boards]

    print(f"  概念匹配: {len(matched)} 个板块")
    for m in matched:
        print(f"    {m['board_name']} (涨幅 {m['pct']:+.2f}%, 目标: {m['target']})")

    return matched


# ================================================================
#  4. 获取板块成分股 — get_concept_stocks()
# ================================================================

def get_concept_stocks(board_name: str) -> tuple[list[str], dict]:
    """获取概念板块成分股, 过滤 ST/科创/北交

    Returns:
        (codes_list, name_map)
    """
    try:
        df = _retry_heavy(ak.stock_board_concept_cons_em, symbol=board_name)
        if df is None or df.empty:
            return [], {}
    except Exception as e:
        logger.debug("板块成分获取失败(%s): %s", board_name, e)
        return [], {}

    code_col = "代码" if "代码" in df.columns else df.columns[0]
    name_col = "名称" if "名称" in df.columns else (
        df.columns[1] if len(df.columns) > 1 else None
    )

    codes = df[code_col].astype(str).str.zfill(6).tolist()
    name_map = {}
    if name_col:
        for _, row in df.iterrows():
            c = str(row[code_col]).zfill(6)
            name_map[c] = str(row[name_col])

    # 过滤: ST / 688(科创) / 8xx(北交) / 4xx(三板)
    filtered = []
    for c in codes:
        if c.startswith(("688", "8", "4")):
            continue
        n = name_map.get(c, "")
        if "ST" in n or "*ST" in n:
            continue
        filtered.append(c)

    return filtered, name_map


# ================================================================
#  5. 主入口 — get_news_event_recommendations()
# ================================================================

def get_news_event_recommendations(top_n=None) -> list[dict]:
    """事件驱动选股主入口

    流程:
    1. 扫描新闻 → 识别事件
    2. 映射概念板块 → 获取成分股
    3. 实时行情 + 评分排名
    4. 新闻排雷
    5. 返回推荐
    """
    if top_n is None:
        top_n = TOP_N

    print("\n" + "=" * 60)
    print("  事件驱动选股")
    print("=" * 60)

    params = NEWS_EVENT_PARAMS
    picks_per_board = params.get("picks_per_board", 2)

    # 1. 扫描新闻
    news = scan_macro_news()
    if not news:
        # 备源: 用概念板块异动
        print("  无新闻数据, 尝试概念板块异动作为隐性信号...")
        return _fallback_concept_movers(top_n)

    # 2. 识别事件
    events = detect_events(news)
    if not events:
        print("  未识别到重大事件, 返回空列表")
        return []

    # 3. 汇总所有目标概念
    all_concepts = []
    event_concept_set = {}  # concept → event_types
    for ev in events:
        for c in ev["concepts"]:
            all_concepts.append(c)
            event_concept_set.setdefault(c, []).append(ev["event_type"])

    # 4. 模糊匹配概念板块
    boards = find_concept_boards(all_concepts)
    if not boards:
        print("  未匹配到概念板块, 返回空列表")
        return []

    # 5. 获取各板块成分股 + 实时行情
    all_candidates = []
    global_name_map = {}

    for board_info in boards:
        board_name = board_info["board_name"]
        codes, nm = get_concept_stocks(board_name)
        global_name_map.update(nm)

        if not codes:
            continue

        time.sleep(0.3)
        spot_df = _sina_batch_quote(codes)
        if spot_df is None or spot_df.empty:
            continue

        # 更新 name_map
        for _, row in spot_df.iterrows():
            global_name_map[row["code"]] = row["name"]

        # 基础过滤
        df = spot_df.copy()
        df["pct_chg"] = (df["price"] - df["prev_close"]) / df["prev_close"] * 100
        df = df[df["price"] > 0].copy()
        df = df[~df["name"].str.contains("ST|\\*ST", na=False)].copy()
        df = df[df["pct_chg"].abs() < 9.8].copy()  # 排除涨跌停

        if df.empty:
            continue

        # 附加板块信息
        df["board_name"] = board_name
        df["board_pct"] = board_info["pct"]
        df["board_target"] = board_info["target"]

        # 计算事件关联度: 该股所属概念出现在几个事件中
        target = board_info["target"]
        event_count = len(event_concept_set.get(target, []))
        df["event_count"] = event_count

        all_candidates.append(df)

    if not all_candidates:
        print("  无候选标的")
        return []

    combined = pd.concat(all_candidates, ignore_index=True)

    # 去重 (同一只股可能出现在多个板块)
    combined = combined.drop_duplicates(subset=["code"], keep="first")
    print(f"  合并候选: {len(combined)} 只 (来自 {len(boards)} 个概念板块)")

    # 6. 评分
    scored = _score_news_event(combined, global_name_map)
    if scored.empty:
        return []

    # 7. 排名 (每板块限选)
    weights = params["weights"]
    scored["total_score"] = 0
    for col, w in weights.items():
        if col in scored.columns:
            scored["total_score"] += scored[col].fillna(0) * w

    scored = scored.sort_values("total_score", ascending=False)

    # 每板块限选
    selected_rows = []
    board_picks = {}
    for _, row in scored.iterrows():
        bn = row.get("board_name", "")
        cnt = board_picks.get(bn, 0)
        if cnt < picks_per_board:
            selected_rows.append(row)
            board_picks[bn] = cnt + 1
        if len(selected_rows) >= top_n * 2:
            break

    if not selected_rows:
        return []

    selected = pd.DataFrame(selected_rows)

    # 8. 新闻排雷
    try:
        risky = news_risk_screen(selected["code"].tolist(), global_name_map)
        if risky:
            print(f"  新闻排雷: 排除 {len(risky)} 只")
            selected = selected[~selected["code"].isin(risky)]
    except Exception as e:
        print(f"  [新闻排雷异常] {e}")

    selected = selected.head(top_n)

    # 9. 格式化输出
    results = []
    for _, row in selected.iterrows():
        code = row["code"]
        name = row.get("name", global_name_map.get(code, ""))
        price = float(row.get("price", 0))
        score = float(row.get("total_score", 0))

        labels = [f"事件:{row.get('board_target', '')}"]
        labels.append(f"概念:{row.get('board_name', '')}")
        labels.append(f"板块涨{row.get('board_pct', 0):+.1f}%")
        labels.append(f"个股涨{row.get('pct_chg', 0):+.1f}%")
        try:
            labels.extend(format_enhanced_labels(row))
        except Exception:
            pass

        results.append({
            "code": code,
            "name": name,
            "price": price,
            "score": score,
            "reason": " | ".join(labels),
            "atr": 0,
        })

    print(f"\n  事件驱动推荐: {len(results)} 只")
    return results


# ================================================================
#  因子评分
# ================================================================

def _score_news_event(df: pd.DataFrame, name_map: dict) -> pd.DataFrame:
    """事件驱动因子评分"""
    if df.empty:
        return df

    # --- s_event_relevance: 事件关联度 ---
    max_events = max(df["event_count"].max(), 1)
    df["s_event_relevance"] = (df["event_count"] / max_events).clip(0, 1)

    # --- s_concept_momentum: 概念板块涨幅 ---
    df["s_concept_momentum"] = (df["board_pct"] / 5).clip(0, 1)

    # --- s_leader_score: 龙头评分 (涨幅 + 量比) ---
    if "amount" in df.columns and df["amount"].sum() > 0:
        amt_rank = df["amount"].rank(pct=True)
    else:
        amt_rank = 0.5

    pct_rank = df["pct_chg"].rank(pct=True)
    df["s_leader_score"] = pct_rank * 0.6 + amt_rank * 0.4

    # --- s_trend: 趋势 (价格vs前收) ---
    df["s_trend"] = ((df["pct_chg"] + 5) / 10).clip(0, 1)

    # --- s_volume_confirm: 量价配合 ---
    if "volume_ratio" in df.columns:
        df["s_volume_confirm"] = (df["volume_ratio"] / 5).clip(0, 1)
    elif "amount" in df.columns:
        df["s_volume_confirm"] = df["amount"].rank(pct=True)
    else:
        df["s_volume_confirm"] = 0.5

    # --- s_fundamental: 基本面 ---
    try:
        fund_df = fetch_fundamental_batch(df["code"].tolist())
        if fund_df is not None and not fund_df.empty:
            fund_scores = calc_fundamental_scores(fund_df)
            df = df.merge(fund_scores[["code", "s_fundamental"]], on="code", how="left")
        else:
            df["s_fundamental"] = 0.5
    except Exception:
        df["s_fundamental"] = 0.5
    df["s_fundamental"] = df["s_fundamental"].fillna(0.5)

    # --- 增强因子 (资金流向 + 筹码) ---
    try:
        df = enhance_candidates(df, name_map)
    except Exception as e:
        print(f"  [增强因子异常] {e}")
        df["s_fund_flow"] = 0.5
        df["s_chip"] = 0.5

    for col in ["s_fund_flow", "s_chip"]:
        if col not in df.columns:
            df[col] = 0.5

    return df


# ================================================================
#  备源: 概念板块异动
# ================================================================

def _fallback_concept_movers(top_n: int) -> list[dict]:
    """当新闻源不可用时, 用概念板块涨幅异动作为隐性事件信号"""
    try:
        df = _retry_heavy(ak.stock_board_concept_name_em)
        if df is None or df.empty:
            return []
    except Exception:
        return []

    name_col = None
    for c in ["板块名称", "名称"]:
        if c in df.columns:
            name_col = c
            break
    if not name_col:
        name_col = df.columns[0]

    pct_col = None
    for c in ["涨跌幅", "最新涨跌幅"]:
        if c in df.columns:
            pct_col = c
            break
    if not pct_col:
        return []

    df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
    df = df.dropna(subset=[pct_col])
    df = df.sort_values(pct_col, ascending=False)

    # 取涨幅前3的概念板块
    top_boards = []
    for _, row in df.head(3).iterrows():
        top_boards.append({
            "board_name": str(row[name_col]),
            "pct": float(row[pct_col]),
            "target": str(row[name_col]),
        })

    if not top_boards:
        return []

    print(f"  备源: TOP 3 异动概念板块")
    for b in top_boards:
        print(f"    {b['board_name']} 涨{b['pct']:+.2f}%")

    # 仅当涨幅 > 3% 才认为有事件信号
    top_boards = [b for b in top_boards if b["pct"] > 3.0]
    if not top_boards:
        print("  备源: 涨幅未超3%, 无明显事件信号")
        return []

    # 获取成分股并简单排序
    all_candidates = []
    global_name_map = {}

    for board_info in top_boards:
        codes, nm = get_concept_stocks(board_info["board_name"])
        global_name_map.update(nm)
        if not codes:
            continue

        time.sleep(0.3)
        spot_df = _sina_batch_quote(codes)
        if spot_df is None or spot_df.empty:
            continue

        for _, row in spot_df.iterrows():
            global_name_map[row["code"]] = row["name"]

        df_s = spot_df.copy()
        df_s["pct_chg"] = (df_s["price"] - df_s["prev_close"]) / df_s["prev_close"] * 100
        df_s = df_s[df_s["price"] > 0].copy()
        df_s = df_s[~df_s["name"].str.contains("ST|\\*ST", na=False)].copy()
        df_s = df_s[df_s["pct_chg"].abs() < 9.8].copy()

        if df_s.empty:
            continue

        df_s["board_name"] = board_info["board_name"]
        df_s["board_pct"] = board_info["pct"]
        df_s["board_target"] = board_info["target"]
        df_s["event_count"] = 1

        all_candidates.append(df_s)

    if not all_candidates:
        return []

    combined = pd.concat(all_candidates, ignore_index=True)
    combined = combined.drop_duplicates(subset=["code"], keep="first")

    scored = _score_news_event(combined, global_name_map)
    if scored.empty:
        return []

    weights = NEWS_EVENT_PARAMS["weights"]
    scored["total_score"] = 0
    for col, w in weights.items():
        if col in scored.columns:
            scored["total_score"] += scored[col].fillna(0) * w

    scored = scored.sort_values("total_score", ascending=False).head(top_n)

    results = []
    for _, row in scored.iterrows():
        code = row["code"]
        name = row.get("name", global_name_map.get(code, ""))
        results.append({
            "code": code,
            "name": name,
            "price": float(row.get("price", 0)),
            "score": float(row.get("total_score", 0)),
            "reason": f"板块异动:{row.get('board_name', '')} | 涨{row.get('board_pct', 0):+.1f}%",
            "atr": 0,
        })

    print(f"\n  备源推荐: {len(results)} 只")
    return results


# ================================================================
#  辅助: 获取今日事件摘要 (供早报使用)
# ================================================================

def get_event_summary() -> str:
    """扫描新闻并返回事件摘要字符串, 无事件返回空字符串"""
    try:
        news = scan_macro_news()
        if not news:
            return ""
        events = detect_events(news)
        if not events:
            return ""

        parts = []
        for ev in events[:3]:
            concepts_str = "/".join(ev["concepts"][:2])
            # 提取关键词的第一个
            first_kw = ev["keywords"].split("|")[0]
            parts.append(f"{first_kw} → {concepts_str}")

        return " | ".join(parts)
    except Exception:
        return ""


# ================================================================
#  CLI 入口
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"

    if mode == "run":
        items = get_news_event_recommendations()
        if items:
            for it in items:
                print(f"  {it['code']} {it['name']} \u00a5{it['price']:.2f} "
                      f"得分:{it['score']:+.3f} {it['reason']}")
        else:
            print("  无事件驱动推荐 (未检测到重大事件)")
    elif mode == "scan":
        news = scan_macro_news()
        events = detect_events(news)
        if events:
            print("\n=== 今日事件 ===")
            for e in events:
                print(f"  [{e['confidence']:.2f}] {e['event_type']}")
                print(f"    → 概念: {', '.join(e['concepts'])}")
                for t in e['matched_titles']:
                    print(f"    | {t}")
        else:
            print("  未检测到重大事件")
    else:
        print("用法:")
        print("  python3 news_event_strategy.py        # 完整运行")
        print("  python3 news_event_strategy.py scan   # 仅扫描新闻")
        sys.exit(1)
