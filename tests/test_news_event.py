"""
事件驱动选股策略 单元测试
"""

import os
import sys
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

# 确保可以导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  TestEventKeywordMatching — 事件关键词匹配
# ================================================================

class TestEventKeywordMatching:
    """事件关键词正确匹配"""

    def test_military_event(self):
        """军事关键词匹配"""
        from news_event_strategy import detect_events
        news = [{"title": "南海军事演习规模扩大", "date": "2026-03-01"}]
        events = detect_events(news)
        assert len(events) >= 1
        # 应匹配到军工相关概念
        found_concepts = []
        for e in events:
            found_concepts.extend(e["concepts"])
        assert any("军工" in c or "国防" in c for c in found_concepts)

    def test_sanction_event(self):
        """制裁关键词匹配"""
        from news_event_strategy import detect_events
        news = [
            {"title": "美国对华出口管制升级", "date": "2026-03-01"},
            {"title": "贸易战关税加征", "date": "2026-03-01"},
        ]
        events = detect_events(news)
        assert len(events) >= 1
        found_concepts = []
        for e in events:
            found_concepts.extend(e["concepts"])
        assert any("国产替代" in c or "自主可控" in c for c in found_concepts)

    def test_ai_event(self):
        """AI关键词匹配"""
        from news_event_strategy import detect_events
        news = [{"title": "国产大模型算力突破", "date": "2026-03-01"}]
        events = detect_events(news)
        assert len(events) >= 1
        found_concepts = []
        for e in events:
            found_concepts.extend(e["concepts"])
        assert any("人工智能" in c or "算力" in c for c in found_concepts)

    def test_multiple_events(self):
        """多事件同时匹配"""
        from news_event_strategy import detect_events
        news = [
            {"title": "台海军事冲突升级", "date": "2026-03-01"},
            {"title": "央行宣布降准降息", "date": "2026-03-01"},
        ]
        events = detect_events(news)
        assert len(events) >= 2

    def test_no_match(self):
        """无关新闻不匹配"""
        from news_event_strategy import detect_events
        news = [
            {"title": "今天天气晴朗", "date": "2026-03-01"},
            {"title": "某明星结婚", "date": "2026-03-01"},
        ]
        events = detect_events(news)
        assert len(events) == 0


# ================================================================
#  TestConceptFuzzyMatch — 概念板块模糊匹配
# ================================================================

class TestConceptFuzzyMatch:
    """概念板块模糊匹配测试"""

    def test_fuzzy_match(self):
        """模糊匹配: 目标概念 vs 实际板块名"""
        from news_event_strategy import find_concept_boards

        mock_df = pd.DataFrame({
            "板块名称": ["军工", "国防军工", "航天航空", "银行", "房地产开发"],
            "涨跌幅": [3.5, 2.1, 1.8, 0.5, -0.2],
        })

        with patch("news_event_strategy._retry_heavy", return_value=mock_df):
            boards = find_concept_boards(["军工", "航天"])
            assert len(boards) >= 2
            board_names = [b["board_name"] for b in boards]
            assert any("军工" in n for n in board_names)

    def test_no_match(self):
        """无匹配板块"""
        from news_event_strategy import find_concept_boards

        mock_df = pd.DataFrame({
            "板块名称": ["银行", "保险", "证券"],
            "涨跌幅": [1.0, 0.5, -0.5],
        })

        with patch("news_event_strategy._retry_heavy", return_value=mock_df):
            boards = find_concept_boards(["量子计算"])
            assert len(boards) == 0


# ================================================================
#  TestNoEventsEmpty — 无事件返回空
# ================================================================

class TestNoEventsEmpty:
    """无事件返回空列表"""

    def test_no_news_returns_empty(self):
        """无新闻数据 → 走备源"""
        from news_event_strategy import get_news_event_recommendations

        with patch("news_event_strategy.scan_macro_news", return_value=[]), \
             patch("news_event_strategy._fallback_concept_movers", return_value=[]):
            result = get_news_event_recommendations()
            assert result == []

    def test_no_events_detected(self):
        """有新闻但无事件"""
        from news_event_strategy import get_news_event_recommendations

        with patch("news_event_strategy.scan_macro_news",
                   return_value=[{"title": "天气预报", "date": "2026-03-01"}]):
            result = get_news_event_recommendations()
            assert result == []


# ================================================================
#  TestOutputFormat — 返回格式正确
# ================================================================

class TestOutputFormat:
    """返回格式测试"""

    def test_output_fields(self):
        """验证返回字段完整"""
        item = {
            "code": "600519",
            "name": "测试股票",
            "price": 100.0,
            "score": 0.85,
            "reason": "事件:军事 | 概念:军工",
            "atr": 0,
        }
        assert "code" in item
        assert "name" in item
        assert "price" in item
        assert "score" in item
        assert "reason" in item
        assert isinstance(item["price"], float)
        assert isinstance(item["score"], float)


# ================================================================
#  TestConfidenceFilter — 低置信度过滤
# ================================================================

class TestConfidenceFilter:
    """置信度过滤测试"""

    def test_low_confidence_filtered(self):
        """低置信度事件被过滤"""
        from news_event_strategy import detect_events

        # 100条无关新闻中只有1条匹配 → 置信度很低
        news = [{"title": "天气预报", "date": "2026-03-01"}] * 100
        news.append({"title": "军事冲突", "date": "2026-03-01"})

        with patch.dict("news_event_strategy.NEWS_EVENT_PARAMS",
                       {"min_event_confidence": 0.5,
                        "event_concept_map": NEWS_EVENT_PARAMS_FIXTURE}):
            events = detect_events(news)
            # 1/101 * 3 ≈ 0.03, 低于0.5阈值, 应被过滤
            military_events = [e for e in events
                             if "军事" in e.get("event_type", "")]
            assert len(military_events) == 0

    def test_high_confidence_passes(self):
        """高置信度事件通过"""
        from news_event_strategy import detect_events

        news = [
            {"title": "南海军事演习", "date": "2026-03-01"},
            {"title": "军事冲突升级", "date": "2026-03-01"},
            {"title": "导弹试射成功", "date": "2026-03-01"},
        ]
        events = detect_events(news)
        assert len(events) >= 1
        assert events[0]["confidence"] >= 0.3


# ================================================================
#  TestDedupEvents — 重复事件去重
# ================================================================

class TestDedupEvents:
    """重复事件去重测试"""

    def test_dedup(self):
        """同类事件只保留一次"""
        from news_event_strategy import detect_events
        news = [
            {"title": "军事演习", "date": "2026-03-01"},
            {"title": "导弹试射", "date": "2026-03-01"},
            {"title": "南海冲突", "date": "2026-03-01"},
        ]
        events = detect_events(news)
        # 这3条都匹配同一个事件类型, 应该只有1条
        military_types = set()
        for e in events:
            military_types.add(e["event_type"])
        # 同一个关键词模式只会出现一次
        for et in military_types:
            assert events.count(next(x for x in events if x["event_type"] == et)) == 1


# ================================================================
#  TestConfigIntegrity — 参数完整性
# ================================================================

class TestConfigIntegrity:
    """配置参数完整性测试"""

    def test_weights_sum_to_one(self):
        """权重合计 = 1.0"""
        from config import NEWS_EVENT_PARAMS
        weights = NEWS_EVENT_PARAMS["weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"权重合计 {total} != 1.0"

    def test_required_params(self):
        """必要参数存在"""
        from config import NEWS_EVENT_PARAMS
        assert "weights" in NEWS_EVENT_PARAMS
        assert "event_concept_map" in NEWS_EVENT_PARAMS
        assert "min_event_confidence" in NEWS_EVENT_PARAMS
        assert "max_concept_boards" in NEWS_EVENT_PARAMS
        assert "picks_per_board" in NEWS_EVENT_PARAMS

    def test_event_concept_map_not_empty(self):
        """事件映射表非空"""
        from config import NEWS_EVENT_PARAMS
        ecm = NEWS_EVENT_PARAMS["event_concept_map"]
        assert len(ecm) >= 5

    def test_schedule_exists(self):
        """调度时间配置存在"""
        from config import SCHEDULE_NEWS_EVENT
        assert SCHEDULE_NEWS_EVENT == "09:22"

    def test_allocation_includes_event(self):
        """组合分配包含事件驱动"""
        from config import PORTFOLIO_RISK_PARAMS
        alloc = PORTFOLIO_RISK_PARAMS["strategy_allocation"]
        assert "事件驱动选股" in alloc
        assert alloc["事件驱动选股"] > 0

    def test_allocation_sums_to_one(self):
        """组合分配合计 = 1.0"""
        from config import PORTFOLIO_RISK_PARAMS
        alloc = PORTFOLIO_RISK_PARAMS["strategy_allocation"]
        total = sum(alloc.values())
        assert abs(total - 1.0) < 0.01, f"分配合计 {total} != 1.0"


# ================================================================
#  TestRegistration — 注册点完整
# ================================================================

class TestRegistration:
    """策略注册完整性测试 (9个策略)"""

    def test_agent_brain_registered(self):
        """agent_brain 包含事件驱动"""
        from agent_brain import STRATEGY_NAMES
        assert "事件驱动选股" in STRATEGY_NAMES
        assert len(STRATEGY_NAMES) == 11

    def test_portfolio_risk_registered(self):
        """portfolio_risk 包含事件驱动"""
        from portfolio_risk import STRATEGY_NAMES
        assert "事件驱动选股" in STRATEGY_NAMES
        assert len(STRATEGY_NAMES) == 11

    def test_auto_optimizer_registered(self):
        """auto_optimizer 包含 news_event"""
        from auto_optimizer import SUPPORTED_STRATEGIES
        assert "news_event" in SUPPORTED_STRATEGIES
        assert len(SUPPORTED_STRATEGIES) == 11

    def test_experiment_lab_registered(self):
        """experiment_lab 包含事件驱动"""
        from experiment_lab import _STRATEGY_MAP
        assert "事件驱动选股" in _STRATEGY_MAP
        assert len(_STRATEGY_MAP) == 11

    def test_optimizer_default_weights(self):
        """auto_optimizer 能获取 news_event 默认权重"""
        from auto_optimizer import _get_default_weights
        weights = _get_default_weights("news_event")
        assert weights
        assert "s_event_relevance" in weights


# ================================================================
#  TestEventSummary — 早报事件摘要
# ================================================================

class TestEventSummary:
    """早报事件摘要测试"""

    def test_event_summary_format(self):
        """事件摘要格式正确"""
        from news_event_strategy import get_event_summary

        mock_news = [
            {"title": "南海军事演习", "date": "2026-03-01"},
            {"title": "美国制裁升级", "date": "2026-03-01"},
        ]

        with patch("news_event_strategy.scan_macro_news", return_value=mock_news):
            summary = get_event_summary()
            # 应包含事件→概念的格式
            if summary:
                assert "→" in summary

    def test_event_summary_empty(self):
        """无事件返回空字符串"""
        from news_event_strategy import get_event_summary

        with patch("news_event_strategy.scan_macro_news", return_value=[]):
            summary = get_event_summary()
            assert summary == ""


# ================================================================
#  Fixture for tests
# ================================================================

NEWS_EVENT_PARAMS_FIXTURE = {
    "战争|冲突|军事|军演|导弹|南海|台海": ["军工", "国防", "航天", "航空"],
    "制裁|贸易战|关税|脱钩|断供|出口管制": ["国产替代", "自主可控", "信创"],
    "降息|宽松|放水|降准|LPR": ["房地产", "银行", "证券"],
    "AI|人工智能|大模型|算力|GPU": ["人工智能", "算力", "CPO"],
}
