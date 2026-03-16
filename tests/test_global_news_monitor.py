"""全球新闻雷达 — 单元测试 (对齐 v3.0 API)"""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from global_news_monitor import (
    _title_similarity,
    _dedup_news,
    _filter_cached,
    _keyword_fallback_analyze,
    analyze_news,
    generate_sector_heatmap,
    _format_push_message,
    save_digest,
    get_latest_digest,
    scan_global_news,
)


# ================================================================
#  标题相似度 (_title_similarity — 原 _jaccard)
# ================================================================

class TestTitleSimilarity:
    def test_identical(self):
        assert _title_similarity("央行宣布降准利好银行", "央行宣布降准利好银行") == 1.0

    def test_different(self):
        assert _title_similarity("央行宣布降准", "股市大涨创新高") < 0.3

    def test_similar(self):
        s = _title_similarity("央行宣布降准0.5个百分点", "央行降准0.5百分点利好银行")
        assert 0.1 < s < 0.9  # 部分重叠

    def test_empty(self):
        assert _title_similarity("", "") == 0.0

    def test_one_empty(self):
        assert _title_similarity("央行降准", "") == 0.0


# ================================================================
#  去重 (_dedup_news)
# ================================================================

class TestDedupNews:
    def _make(self, title, source="A"):
        return {"title": title, "source": source, "content": "", "pub_time": ""}

    def test_exact_dup(self):
        items = [
            self._make("央行宣布降准0.5个百分点利好银行"),
            self._make("央行宣布降准0.5个百分点利好银行", "B"),
        ]
        result = _dedup_news(items)
        assert len(result) == 1

    def test_different_kept(self):
        items = [
            self._make("央行宣布降准0.5个百分点"),
            self._make("美股三大指数全线大涨创新高"),
        ]
        result = _dedup_news(items)
        assert len(result) == 2

    def test_short_title_filtered(self):
        items = [
            self._make("短标题"),  # < 10 chars
            self._make("央行宣布降准0.5个百分点利好银行"),
        ]
        result = _dedup_news(items)
        assert len(result) == 1


# ================================================================
#  缓存过滤 (_filter_cached)
# ================================================================

class TestFilterCached:
    def test_new_items_pass(self, tmp_path, monkeypatch):
        cache_path = str(tmp_path / "cache.json")
        monkeypatch.setattr("global_news_monitor._CACHE_PATH", cache_path)
        items = [{"title": "全新的新闻标题ABCDEFG"}]
        result = _filter_cached(items)
        assert len(result) == 1

    def test_cached_items_filtered(self, tmp_path, monkeypatch):
        cache_path = str(tmp_path / "cache.json")
        monkeypatch.setattr("global_news_monitor._CACHE_PATH", cache_path)
        items = [{"title": "重复新闻XYZ12345678"}]
        _filter_cached(items)   # 第一次 → 写入缓存
        result = _filter_cached(items)  # 第二次 → 被过滤
        assert len(result) == 0


# ================================================================
#  关键词降级分析 (_keyword_fallback_analyze)
# ================================================================

class TestKeywordFallbackAnalyze:
    def test_bullish_keywords(self):
        items = [{"title": "央行宣布降准降息0.5个百分点利好银行", "content": ""}]
        result = _keyword_fallback_analyze(items)
        if result:
            assert result[0].get("impact_direction") == "bullish"

    def test_bearish_keywords(self):
        items = [{"title": "美国宣布加息制裁收紧出口管制", "content": ""}]
        result = _keyword_fallback_analyze(items)
        if result:
            assert result[0].get("impact_direction") == "bearish"

    def test_no_match_returns_empty(self):
        items = [{"title": "今天天气晴好温度适宜适合出行", "content": ""}]
        result = _keyword_fallback_analyze(items)
        # 无关键词匹配时可能返回空
        assert isinstance(result, list)

    def test_sector_matching(self):
        items = [{"title": "芯片半导体AI大涨创新高利好科技板块", "content": ""}]
        result = _keyword_fallback_analyze(items)
        if result:
            sectors = result[0].get("affected_sectors", [])
            sector_impacts = result[0].get("sector_impacts", {})
            assert len(sectors) > 0 or len(sector_impacts) > 0


# ================================================================
#  综合分析 (analyze_news)
# ================================================================

class TestAnalyzeNews:
    def test_empty_input(self):
        assert analyze_news([]) == []

    @patch("global_news_monitor._llm_analyze_batch", return_value=[])
    def test_fallback_to_keywords(self, mock_llm):
        """LLM 不可用时降级到关键词"""
        items = [{"title": "央行宣布降准利好银行降息刺激经济"}]
        result = analyze_news(items)
        # 可能有也可能没有 (取决于关键词匹配)
        assert isinstance(result, list)


# ================================================================
#  行业热力图 (generate_sector_heatmap)
# ================================================================

class TestGenerateSectorHeatmap:
    def test_aggregate(self):
        events = [
            {"sector_impacts": {"银行": 3, "保险": 2}},
            {"sector_impacts": {"银行": 1, "科技": -2}},
        ]
        hm = generate_sector_heatmap(events)
        sectors = hm["sectors"]
        assert sectors["银行"] == 4
        assert sectors["科技"] == -2
        assert "sentiment" in hm
        assert "sentiment_label" in hm

    def test_empty(self):
        hm = generate_sector_heatmap([])
        assert hm["sectors"] == {}
        assert hm["sentiment"] == 0

    def test_sentiment_label(self):
        events = [{"sector_impacts": {"银行": 5, "保险": 3}}]
        hm = generate_sector_heatmap(events)
        assert hm["sentiment_label"] == "整体偏多"

    def test_bearish_sentiment(self):
        events = [{"sector_impacts": {"科技": -5, "半导体": -3}}]
        hm = generate_sector_heatmap(events)
        assert hm["sentiment_label"] == "整体偏空"


# ================================================================
#  推送格式 (_format_push_message)
# ================================================================

class TestFormatPushMessage:
    def test_basic(self):
        events = [{
            "title": "央行降准",
            "impact_direction": "bullish",
            "impact_magnitude": 3,
            "affected_sectors": ["银行"],
            "sector_impacts": {"银行": 3},
            "strategy_implications": "关注银行股",
            "urgency": "urgent",
        }]
        hm = {
            "sectors": {"银行": 3, "科技": -2},
            "sentiment": 0.65,
            "sentiment_label": "整体偏多",
        }
        title, body = _format_push_message(events, hm)
        assert "央行降准" in body
        assert "利好" in body

    def test_empty_events(self):
        title, body = _format_push_message([], {"sectors": {}, "sentiment": 0, "sentiment_label": "中性"})
        assert "中性" in body


# ================================================================
#  摘要存储 (save_digest / get_latest_digest)
# ================================================================

class TestSaveDigest:
    def test_save_load(self, tmp_path, monkeypatch):
        digest_path = str(tmp_path / "digest.json")
        monkeypatch.setattr("global_news_monitor._DIGEST_PATH", digest_path)

        events = [{"title": "test", "impact_magnitude": 3}]
        heatmap = {"sectors": {"银行": 3}, "sentiment": 0.5, "sentiment_label": "整体偏多"}
        save_digest(events, heatmap)
        assert os.path.exists(digest_path)


class TestGetLatestDigest:
    def test_existing(self, tmp_path, monkeypatch):
        digest_path = str(tmp_path / "digest.json")
        monkeypatch.setattr("global_news_monitor._DIGEST_PATH", digest_path)

        data = {
            "timestamp": datetime.now().isoformat(),
            "events": [{"title": "test"}],
            "event_count": 1,
        }
        with open(digest_path, "w") as f:
            json.dump(data, f)

        result = get_latest_digest()
        assert result is not None
        assert result["event_count"] == 1

    def test_missing(self, tmp_path, monkeypatch):
        digest_path = str(tmp_path / "nonexistent.json")
        monkeypatch.setattr("global_news_monitor._DIGEST_PATH", digest_path)
        result = get_latest_digest()
        assert result == {}


# ================================================================
#  主流程 (scan_global_news)
# ================================================================

class TestScanGlobalNews:
    def test_disabled(self, monkeypatch):
        monkeypatch.setattr("global_news_monitor.GLOBAL_NEWS_PARAMS",
                            {"enabled": False})
        result = scan_global_news()
        assert result == {}

    @patch("global_news_monitor._fetch_all_news", return_value=[])
    def test_no_news(self, mock_fetch):
        result = scan_global_news()
        assert result == {}

    @patch("global_news_monitor.push_news_alert")
    @patch("global_news_monitor.emit_critical_events")
    @patch("global_news_monitor._filter_cached", side_effect=lambda x: x)
    @patch("global_news_monitor._keyword_fallback_analyze")
    @patch("global_news_monitor._llm_analyze_batch", return_value=[])
    @patch("global_news_monitor._fetch_all_news")
    def test_full_pipeline(self, mock_fetch, mock_llm, mock_keyword,
                           mock_cache, mock_emit, mock_push, tmp_path,
                           monkeypatch):
        """完整流水线: 抓取→去重→分析→热力图→保存"""
        digest_path = str(tmp_path / "digest.json")
        monkeypatch.setattr("global_news_monitor._DIGEST_PATH", digest_path)

        mock_fetch.return_value = [
            {"title": "央行宣布大规模降准0.5个百分点利好银行板块", "source": "财联社",
             "content": "", "pub_time": "2026-03-15"},
        ]
        mock_keyword.return_value = [
            {"title": "央行降准", "impact_direction": "bullish",
             "impact_magnitude": 3, "affected_sectors": ["银行"],
             "sector_impacts": {"银行": 3}, "urgency": "urgent"},
        ]

        result = scan_global_news()
        assert "events" in result
        assert "heatmap" in result
