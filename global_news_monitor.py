"""
全球新闻雷达
============
多源新闻抓取 + LLM分析 + 行业影响热力图

��据源 (6个, 全免费, 周末可用):
  1. 财联社 (CLS) 快讯 - 24h更新
  2. 东方财富全球新闻 - 200条
  3. CCTV宏观新闻
  4. 新浪全球财经
  5. 同花顺全球新闻
  6. 财新头条

处理流程:
  抓取 → 标准化 → 去重 → 缓存检查 → LLM分析 → 关键词降级
  → 行业热力图 → 存储 → 推送 → 事件总线

用法:
  python3 global_news_monitor.py          # 立即扫描
  python3 global_news_monitor.py digest   # 查看最新摘要
  python3 global_news_monitor.py sources  # 测试各新闻源
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GLOBAL_NEWS_PARAMS
from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("global_news")

_DIR = os.path.dirname(os.path.abspath(__file__))
_DIGEST_PATH = os.path.join(_DIR, "news_digest.json")
_CACHE_PATH = os.path.join(_DIR, "news_cache.json")


# ================================================================
#  新闻源抓取 (6个)
# ================================================================

def _fetch_cls_news() -> list[dict]:
    """财联社快讯 (Tier 1)"""
    try:
        import akshare as ak
        df = ak.stock_info_global_cls()
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("标题", "")),
                "content": str(row.get("内容", "")),
                "source": "财联社",
                "timestamp": f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip(),
            })
        return news
    except Exception as e:
        logger.debug("CLS新闻获取失败: %s", e)
        return []


def _fetch_em_news() -> list[dict]:
    """东方财富全球新闻 (Tier 1)"""
    try:
        import akshare as ak
        df = ak.stock_info_global_em()
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("标题", "")),
                "content": str(row.get("摘要", "")),
                "source": "东方财富",
                "timestamp": str(row.get("发布时间", "")),
            })
        return news
    except Exception as e:
        logger.debug("东财新闻获取失败: %s", e)
        return []


def _fetch_cctv_news() -> list[dict]:
    """CCTV宏观新闻 (Tier 1)"""
    try:
        import akshare as ak
        today = datetime.now().strftime("%Y%m%d")
        df = ak.news_cctv(date=today)
        if df.empty:
            # 回退到昨天
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = ak.news_cctv(date=yesterday)
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("title", "")),
                "content": "",
                "source": "CCTV",
                "timestamp": str(row.get("date", "")),
            })
        return news
    except Exception as e:
        logger.debug("CCTV新闻获取失败: %s", e)
        return []


def _fetch_sina_news() -> list[dict]:
    """新浪全球财经 (Tier 2)"""
    try:
        import akshare as ak
        df = ak.stock_info_global_sina()
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("内容", ""))[:100],  # 新浪只有内容无标题
                "content": str(row.get("内容", "")),
                "source": "新浪",
                "timestamp": str(row.get("时间", "")),
            })
        return news
    except Exception as e:
        logger.debug("新浪新闻获取失败: %s", e)
        return []


def _fetch_ths_news() -> list[dict]:
    """同花顺全球新闻 (Tier 2)"""
    try:
        import akshare as ak
        df = ak.stock_info_global_ths()
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("标题", "")),
                "content": str(row.get("内容", "")),
                "source": "同花顺",
                "timestamp": str(row.get("发布时间", "")),
            })
        return news
    except Exception as e:
        logger.debug("同花顺新闻获取失败: %s", e)
        return []


def _fetch_caixin_news() -> list[dict]:
    """财新头条 (Tier 2)"""
    try:
        import akshare as ak
        df = ak.stock_news_main_cx()
        if df.empty:
            return []
        news = []
        for _, row in df.iterrows():
            news.append({
                "title": str(row.get("summary", "")),
                "content": "",
                "source": "财新",
                "timestamp": "",
            })
        return news
    except Exception as e:
        logger.debug("财新新闻获取失败: %s", e)
        return []


def _fetch_all_news() -> list[dict]:
    """从所有源抓取新闻"""
    sources_config = GLOBAL_NEWS_PARAMS.get("sources", {})
    all_news = []
    
    if sources_config.get("cls", True):
        all_news.extend(_fetch_cls_news())
    if sources_config.get("em", True):
        all_news.extend(_fetch_em_news())
    if sources_config.get("cctv", True):
        all_news.extend(_fetch_cctv_news())
    if sources_config.get("sina", True):
        all_news.extend(_fetch_sina_news())
    if sources_config.get("ths", True):
        all_news.extend(_fetch_ths_news())
    if sources_config.get("caixin", True):
        all_news.extend(_fetch_caixin_news())
    
    logger.info("抓取新闻: %d条", len(all_news))
    return all_news


# ================================================================
#  去重
# ================================================================

def _title_similarity(t1: str, t2: str) -> float:
    """计算标题相似度 (Jaccard on character bigrams)"""
    if not t1 or not t2:
        return 0.0
    
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s)-1))
    
    b1 = bigrams(t1)
    b2 = bigrams(t2)
    if not b1 or not b2:
        return 0.0
    
    intersection = len(b1 & b2)
    union = len(b1 | b2)
    return intersection / union if union > 0 else 0.0


def _dedup_news(news_list: list[dict]) -> list[dict]:
    """去重: 标题完全相同 or 相似度>阈值"""
    threshold = GLOBAL_NEWS_PARAMS.get("dedup_similarity_threshold", 0.6)
    seen_titles = {}
    deduped = []
    
    for item in news_list:
        title = item.get("title", "").strip()
        if not title or len(title) < 10:
            continue
        
        # 完全相同
        if title in seen_titles:
            continue
        
        # 相似度检查
        is_dup = False
        for existing_title in seen_titles:
            if _title_similarity(title, existing_title) > threshold:
                is_dup = True
                break
        
        if not is_dup:
            seen_titles[title] = True
            deduped.append(item)
    
    logger.info("去重后: %d条", len(deduped))
    return deduped


# ================================================================
#  缓存检查
# ================================================================

def _load_cache() -> dict:
    """加载缓存 {title_hash: timestamp}"""
    cache = safe_load(_CACHE_PATH, default={})
    if not isinstance(cache, dict):
        return {}
    # 清理过期缓存 (>24h)
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    cleaned = {}
    for k, v in cache.items():
        if isinstance(v, str) and v > cutoff:
            cleaned[k] = v
    return cleaned


def _save_cache(cache: dict):
    """保存缓存"""
    safe_save(_CACHE_PATH, cache)


def _filter_cached(news_list: list[dict]) -> list[dict]:
    """过滤已缓存的新闻"""
    cache_hours = GLOBAL_NEWS_PARAMS.get("cache_hours", 6)
    cache = _load_cache()
    cutoff = (datetime.now() - timedelta(hours=cache_hours)).isoformat()
    
    filtered = []
    for item in news_list:
        title = item.get("title", "")
        title_hash = hashlib.md5(title.encode()).hexdigest()
        
        cached_time = cache.get(title_hash)
        if cached_time and cached_time > cutoff:
            continue
        
        filtered.append(item)
        cache[title_hash] = datetime.now().isoformat()
    
    _save_cache(cache)
    logger.info("缓存过滤后: %d条新新闻", len(filtered))
    return filtered


# ================================================================
#  LLM分析
# ================================================================

_ANALYSIS_SYSTEM = """你是一个量化交易系统的全球新闻分析引擎。
你需要从新闻标题中识别对中国A股市场有影响的事件，并给出结构化分析。
聚焦政策、央行、行业规划、地缘冲突、大宗商品异动等有实质性市场影响的事件。
忽略日常社会新闻、体育、娱乐等无市场影响的内容。"""

_ANALYSIS_USER_TEMPLATE = """分析以下新闻标题，识别有市场影响的事件:

{headlines}

对每个有影响的事件，返回JSON数组，格式:
[
  {{
    "title": "新闻标题",
    "category": "policy|monetary|fiscal|industry|geopolitical|commodity|trade|tech",
    "impact_direction": "bullish|bearish|neutral",
    "impact_magnitude": 1-5,
    "affected_sectors": ["银行", "房地产"],
    "sector_impacts": {{"银行": 3, "房地产": 2}},
    "strategy_implications": "策略建议",
    "urgency": "critical|urgent|normal|low",
    "confidence": 0.0-1.0
  }}
]

如果没有有影响的事件，返回空数组 []。"""


def _llm_analyze_batch(headlines: list[str]) -> list[dict]:
    """LLM批量分析新闻"""
    try:
        from llm_advisor import _call_llm, _check_daily_limit
        
        if not _check_daily_limit():
            logger.warning("LLM每日配额已用完")
            return []
        
        prompt = _ANALYSIS_USER_TEMPLATE.format(
            headlines="\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
        )
        
        response = _call_llm(prompt, system=_ANALYSIS_SYSTEM)
        if not response:
            return []
        
        # 提取JSON
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if not match:
            return []
        
        events = json.loads(match.group(0))
        return events if isinstance(events, list) else []
    
    except Exception as e:
        logger.error("LLM分析失败: %s", e)
        return []


def _keyword_fallback_analyze(news_list: list[dict]) -> list[dict]:
    """关键词降级分析"""
    keywords = GLOBAL_NEWS_PARAMS.get("fallback_keywords", {})
    sector_map = GLOBAL_NEWS_PARAMS.get("sector_keyword_map", {})
    
    events = []
    for item in news_list:
        title = item.get("title", "") + " " + item.get("content", "")
        
        # 判断方向
        direction = "neutral"
        for word in keywords.get("bullish", []):
            if word in title:
                direction = "bullish"
                break
        for word in keywords.get("bearish", []):
            if word in title:
                direction = "bearish"
                break
        
        if direction == "neutral":
            continue
        
        # 匹配行业
        affected = []
        impacts = {}
        for pattern, sectors in sector_map.items():
            if re.search(pattern, title):
                affected.extend(sectors)
                for s in sectors:
                    impacts[s] = 2 if direction == "bullish" else -2
        
        if not affected:
            continue
        
        events.append({
            "title": item.get("title", ""),
            "category": "policy",
            "impact_direction": direction,
            "impact_magnitude": 2,
            "affected_sectors": list(set(affected)),
            "sector_impacts": impacts,
            "strategy_implications": f"关注{'利好' if direction == 'bullish' else '利空'}板块",
            "urgency": "normal",
            "confidence": 0.5,
            "source": item.get("source", ""),
            "timestamp": item.get("timestamp", ""),
        })
    
    return events


def analyze_news(news_list: list[dict]) -> list[dict]:
    """分析新闻 (LLM + 关键词降级)"""
    if not news_list:
        return []
    
    max_llm_calls = GLOBAL_NEWS_PARAMS.get("max_llm_calls_per_scan", 3)
    max_per_batch = GLOBAL_NEWS_PARAMS.get("max_headlines_per_batch", 20)
    
    # LLM分析 (分批)
    events = []
    headlines = [n.get("title", "") for n in news_list if n.get("title")]
    
    for i in range(0, min(len(headlines), max_llm_calls * max_per_batch), max_per_batch):
        batch = headlines[i:i+max_per_batch]
        batch_events = _llm_analyze_batch(batch)
        events.extend(batch_events)
        time.sleep(1)  # 避免过快
    
    # 关键词降级 (LLM未覆盖的)
    if len(events) < 3:
        fallback_events = _keyword_fallback_analyze(news_list)
        events.extend(fallback_events)
    
    # 过滤低影响
    min_magnitude = GLOBAL_NEWS_PARAMS.get("min_impact_magnitude", 2)
    events = [e for e in events if e.get("impact_magnitude", 0) >= min_magnitude]
    
    logger.info("分析完成: %d个事件", len(events))
    return events


# ================================================================
#  行业热力图
# ================================================================

def generate_sector_heatmap(events: list[dict]) -> dict:
    """生成行业影响热力图"""
    sector_scores = Counter()
    
    for event in events:
        impacts = event.get("sector_impacts", {})
        for sector, score in impacts.items():
            sector_scores[sector] += score
    
    # 排序取top 8
    top_sectors = sector_scores.most_common(8)
    
    # 计算综合情绪
    total_score = sum(sector_scores.values())
    sentiment = total_score / len(sector_scores) if sector_scores else 0
    sentiment_normalized = max(-1, min(1, sentiment / 3))  # 归一化到[-1, 1]
    
    return {
        "sectors": dict(top_sectors),
        "sentiment": sentiment_normalized,
        "sentiment_label": "整体偏多" if sentiment_normalized > 0.2 else 
                          "整体偏空" if sentiment_normalized < -0.2 else "中性",
    }


# ================================================================
#  推送
# ================================================================

def _format_push_message(events: list[dict], heatmap: dict) -> tuple[str, str]:
    """格式化推送消息"""
    max_events = GLOBAL_NEWS_PARAMS.get("push_max_events", 8)
    
    # 按紧急度+影响度排序
    urgency_order = {"critical": 0, "urgent": 1, "normal": 2, "low": 3}
    events_sorted = sorted(
        events,
        key=lambda e: (urgency_order.get(e.get("urgency", "normal"), 2),
                      -e.get("impact_magnitude", 0))
    )[:max_events]
    
    lines = ["重大事件:", ""]
    for i, e in enumerate(events_sorted, 1):
        direction_icon = {"bullish": "[利好]", "bearish": "[利空]", "neutral": "[中性]"}.get(
            e.get("impact_direction", "neutral"), ""
        )
        
        lines.append(f"{i}. {direction_icon} {e.get('title', '')}")
        
        # 影响行业
        sectors = e.get("affected_sectors", [])[:5]
        impacts = e.get("sector_impacts", {})
        sector_str = " ".join(
            f"{s}({'↑' * min(abs(impacts.get(s, 0)), 3) if impacts.get(s, 0) > 0 else '↓' * min(abs(impacts.get(s, 0)), 3)})"
            for s in sectors
        )
        if sector_str:
            lines.append(f"   影响行业: {sector_str}")
        
        # 策略建议
        impl = e.get("strategy_implications", "")
        if impl:
            lines.append(f"   策略建议: {impl}")
        
        lines.append("")
    
    # 热力图
    lines.append("行业影响热力图:")
    sectors_dict = heatmap.get("sectors", {})
    if sectors_dict:
        sector_strs = []
        for sector, score in list(sectors_dict.items())[:8]:
            arrow = "↑" * min(abs(score), 3) if score > 0 else "↓" * min(abs(score), 3)
            sector_strs.append(f"{sector} {arrow}")
        lines.append("  " + " | ".join(sector_strs))
    
    lines.append("")
    lines.append(f"综合情绪: {heatmap.get('sentiment_label', '中性')} ({heatmap.get('sentiment', 0):.2f})")
    
    title = "🌐 全球新闻雷达"
    body = "\n".join(lines)
    
    return title, body


def push_news_alert(events: list[dict], heatmap: dict):
    """推送新闻告警"""
    if not events:
        logger.info("无重大事件, 跳过推送")
        return
    
    try:
        from notifier import notify_wechat_raw
        title, body = _format_push_message(events, heatmap)
        notify_wechat_raw(title, body)
        logger.info("新闻告警已推送")
    except Exception as e:
        logger.error("推送失败: %s", e)


# ================================================================
#  事件总线
# ================================================================

def emit_critical_events(events: list[dict]):
    """发送critical/urgent事件到事件总线"""
    try:
        from event_bus import EventBus, Priority
        bus = EventBus()
        
        for e in events:
            urgency = e.get("urgency", "normal")
            if urgency not in ("critical", "urgent"):
                continue
            
            priority = Priority.CRITICAL if urgency == "critical" else Priority.URGENT
            
            bus.emit(
                source="global_news",
                priority=priority,
                event_type="news_alert",
                category="market",
                payload={
                    "title": e.get("title", ""),
                    "direction": e.get("impact_direction", "neutral"),
                    "magnitude": e.get("impact_magnitude", 0),
                    "sectors": e.get("affected_sectors", []),
                },
            )
        
        logger.info("事件总线: 发送%d个紧急事件", 
                   sum(1 for e in events if e.get("urgency") in ("critical", "urgent")))
    except Exception as e:
        logger.error("事件总线发送失败: %s", e)


# ================================================================
#  持久化
# ================================================================

def save_digest(events: list[dict], heatmap: dict):
    """保存新闻摘要"""
    digest = {
        "timestamp": datetime.now().isoformat(),
        "events": events,
        "heatmap": heatmap,
        "event_count": len(events),
    }
    safe_save(_DIGEST_PATH, digest)
    logger.info("新闻摘要已保存")


def get_latest_digest() -> dict:
    """获取最新摘要 (供其他模块调用)"""
    return safe_load(_DIGEST_PATH, default={})


# ================================================================
#  主流程
# ================================================================

def scan_global_news() -> dict:
    """扫描全球新闻 (主入口)"""
    if not GLOBAL_NEWS_PARAMS.get("enabled", True):
        logger.info("全球新闻监控已禁用")
        return {}
    
    logger.info("=" * 60)
    logger.info("全球新闻雷达启动")
    logger.info("=" * 60)
    
    # 1. 抓取
    all_news = _fetch_all_news()
    if not all_news:
        logger.warning("未抓取到任何新闻")
        return {}
    
    # 2. 去重
    deduped = _dedup_news(all_news)
    
    # 3. 缓存过滤
    new_news = _filter_cached(deduped)
    if not new_news:
        logger.info("无新新闻")
        return {}
    
    # 4. 分析
    events = analyze_news(new_news)
    if not events:
        logger.info("无重大事件")
        return {}
    
    # 5. 热力图
    heatmap = generate_sector_heatmap(events)
    
    # 6. 保存
    save_digest(events, heatmap)
    
    # 7. 推送
    push_news_alert(events, heatmap)
    
    # 8. 事件总线
    emit_critical_events(events)
    
    logger.info("=" * 60)
    logger.info("扫描完成: %d个事件", len(events))
    logger.info("=" * 60)
    
    return {"events": events, "heatmap": heatmap}


# ================================================================
#  CLI
# ================================================================

def show_digest():
    """显示最新摘要"""
    digest = get_latest_digest()
    if not digest:
        print("暂无新闻摘要")
        return
    
    print(f"\n最新摘要 ({digest.get('timestamp', '未知')})")
    print(f"事件数: {digest.get('event_count', 0)}")
    
    events = digest.get("events", [])
    if events:
        print("\n重大事件:")
        for i, e in enumerate(events[:5], 1):
            print(f"  {i}. [{e.get('impact_direction', '')}] {e.get('title', '')}")
            print(f"     影响: {', '.join(e.get('affected_sectors', [])[:3])}")
    
    heatmap = digest.get("heatmap", {})
    if heatmap:
        print(f"\n综合情绪: {heatmap.get('sentiment_label', '未知')} ({heatmap.get('sentiment', 0):.2f})")


def test_sources():
    """测试各新闻源"""
    sources = [
        ("财联社", _fetch_cls_news),
        ("东方财富", _fetch_em_news),
        ("CCTV", _fetch_cctv_news),
        ("新浪", _fetch_sina_news),
        ("同花顺", _fetch_ths_news),
        ("财新", _fetch_caixin_news),
    ]
    
    print("\n测试新闻源:")
    for name, func in sources:
        try:
            news = func()
            print(f"  {name}: {len(news)}条")
            if news:
                print(f"    示例: {news[0].get('title', '')[:50]}")
        except Exception as e:
            print(f"  {name}: 失败 ({e})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    
    if cmd == "digest":
        show_digest()
    elif cmd == "sources":
        test_sources()
    else:
        scan_global_news()
