"""
llm_advisor 单元测试
====================
覆盖: API key 缺失降级/调用限额/增强早报/chat 上下文/异常安全
所有测试 mock Claude API, 无网络依赖
"""

import json
import os
import sys
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """将 llm_advisor 的文件路径重定向到临时目录"""
    import llm_advisor
    usage_path = str(tmp_path / "llm_usage.json")
    monkeypatch.setattr(llm_advisor, "_USAGE_PATH", usage_path)
    # 重置 client 状态
    llm_advisor.reset_client()
    return tmp_path


@pytest.fixture
def mock_client():
    """创建 mock Anthropic client"""
    client = MagicMock()
    block = MagicMock()
    block.text = "这是 LLM 的回复"
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    return client


# ================================================================
#  TestGetClient
# ================================================================

class TestGetClient:
    def test_no_api_key(self, tmp_dir, monkeypatch):
        """无 API key 应返回 None"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        client = llm_advisor._get_client()
        assert client is None

    def test_disabled(self, tmp_dir, monkeypatch):
        """禁用时返回 None"""
        import llm_advisor
        monkeypatch.setattr(
            "llm_advisor.LLM_ADVISOR_PARAMS",
            {**llm_advisor.LLM_ADVISOR_PARAMS, "enabled": False}
        )
        llm_advisor.reset_client()
        client = llm_advisor._get_client()
        assert client is None

    def test_client_cached(self, tmp_dir, monkeypatch):
        """client 应被缓存 (延迟初始化只执行一次)"""
        import llm_advisor
        llm_advisor.reset_client()
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        c1 = llm_advisor._get_client()
        c2 = llm_advisor._get_client()
        assert c1 is c2  # 都是 None, 但只初始化了一次


# ================================================================
#  TestDailyLimit
# ================================================================

class TestDailyLimit:
    def test_under_limit(self, tmp_dir):
        """未超限应返回 True"""
        import llm_advisor
        assert llm_advisor._check_daily_limit() is True

    def test_at_limit(self, tmp_dir):
        """达到上限应返回 False"""
        import llm_advisor
        _write_json(llm_advisor._USAGE_PATH, {
            "date": date.today().isoformat(),
            "count": 20,
        })
        assert llm_advisor._check_daily_limit() is False

    def test_next_day_resets(self, tmp_dir):
        """跨天应重置"""
        import llm_advisor
        _write_json(llm_advisor._USAGE_PATH, {
            "date": "2020-01-01",
            "count": 100,
        })
        assert llm_advisor._check_daily_limit() is True

    def test_increment_usage(self, tmp_dir):
        """增量计数"""
        import llm_advisor
        llm_advisor._increment_usage()
        llm_advisor._increment_usage()
        usage = llm_advisor.get_usage_today()
        assert usage["count"] == 2

    def test_get_usage_today(self, tmp_dir):
        """获取今日使用量"""
        import llm_advisor
        usage = llm_advisor.get_usage_today()
        assert usage["date"] == date.today().isoformat()
        assert usage["count"] == 0
        assert usage["max"] == 20


# ================================================================
#  TestCallLLM
# ================================================================

class TestCallLLM:
    def test_no_client_returns_empty(self, tmp_dir, monkeypatch):
        """client 为 None 时返回空字符串"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        result = llm_advisor._call_llm("test prompt")
        assert result == ""

    def test_successful_call(self, tmp_dir, mock_client, monkeypatch):
        """成功调用应返回文本"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        result = llm_advisor._call_llm("test prompt")
        assert result == "这是 LLM 的回复"
        mock_client.messages.create.assert_called_once()

    def test_exception_returns_empty(self, tmp_dir, monkeypatch):
        """调用异常应返回空字符串"""
        import llm_advisor
        llm_advisor.reset_client()
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        result = llm_advisor._call_llm("test prompt")
        assert result == ""

    def test_limit_exceeded_returns_empty(self, tmp_dir, mock_client, monkeypatch):
        """超限时返回空字符串"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        _write_json(llm_advisor._USAGE_PATH, {
            "date": date.today().isoformat(),
            "count": 20,
        })
        result = llm_advisor._call_llm("test prompt")
        assert result == ""

    def test_increments_counter(self, tmp_dir, mock_client, monkeypatch):
        """成功调用应递增计数"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        llm_advisor._call_llm("test")
        usage = llm_advisor.get_usage_today()
        assert usage["count"] == 1


# ================================================================
#  TestEnhanceMorningBriefing
# ================================================================

class TestEnhanceMorningBriefing:
    def test_fallback_when_no_client(self, tmp_dir, monkeypatch):
        """LLM 不可用时返回原始文本"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        raw = "## 今日交易简报\n\ntest"
        result = llm_advisor.enhance_morning_briefing(raw)
        assert result == raw

    def test_enhanced_with_client(self, tmp_dir, mock_client, monkeypatch):
        """LLM 可用时返回增强文本"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        raw = "## 今日交易简报\n\ntest"
        result = llm_advisor.enhance_morning_briefing(raw)
        assert result == "这是 LLM 的回复"


# ================================================================
#  TestEnhanceEveningSummary
# ================================================================

class TestEnhanceEveningSummary:
    def test_fallback_when_no_client(self, tmp_dir, monkeypatch):
        """LLM 不可用时返回原始文本"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        raw = "## Agent 今日洞察\n\ntest"
        result = llm_advisor.enhance_evening_summary(raw)
        assert result == raw

    def test_enhanced_with_decisions(self, tmp_dir, mock_client, monkeypatch):
        """含决策列表的增强晚报"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        raw = "## Agent 今日洞察"
        decisions = [{
            "finding": {"severity": "critical", "message": "test"},
            "action": "pause_strategy",
            "execute": True,
        }]
        result = llm_advisor.enhance_evening_summary(raw, decisions=decisions)
        assert result == "这是 LLM 的回复"


# ================================================================
#  TestAdviseOnFindings
# ================================================================

class TestAdviseOnFindings:
    def test_no_client_passthrough(self, tmp_dir, monkeypatch):
        """LLM 不可用时原样返回 findings"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        findings = [{"severity": "warning", "confidence": 0.5,
                      "message": "test", "suggested_action": "log_insight"}]
        result = llm_advisor.advise_on_findings(findings)
        assert result == findings
        assert "llm_advice" not in result[0]

    def test_advice_added(self, tmp_dir, mock_client, monkeypatch):
        """LLM 可用时应添加 llm_advice 字段"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        findings = [
            {"severity": "warning", "confidence": 0.5,
             "message": "胜率下降", "suggested_action": "log_insight"},
        ]
        result = llm_advisor.advise_on_findings(findings)
        assert result[0].get("llm_advice") is not None

    def test_skip_high_confidence(self, tmp_dir, mock_client, monkeypatch):
        """高置信度 findings 不请求 LLM 建议"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        findings = [
            {"severity": "critical", "confidence": 0.95,
             "message": "test", "suggested_action": "pause_strategy"},
        ]
        result = llm_advisor.advise_on_findings(findings)
        # 不应添加 llm_advice (高置信度不在 0.4-0.7 范围)
        assert "llm_advice" not in result[0]
        mock_client.messages.create.assert_not_called()


# ================================================================
#  TestChat
# ================================================================

class TestChat:
    def test_no_client_fallback(self, tmp_dir, monkeypatch):
        """LLM 不可用时返回降级提示"""
        import llm_advisor
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        llm_advisor.reset_client()
        result = llm_advisor.chat("最近表现如何")
        assert "不可用" in result

    def test_chat_with_client(self, tmp_dir, mock_client, monkeypatch):
        """LLM 可用时返回回复"""
        import llm_advisor
        llm_advisor.reset_client()
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        result = llm_advisor.chat("最近表现如何")
        assert result == "这是 LLM 的回复"

    def test_chat_failure(self, tmp_dir, monkeypatch):
        """LLM 调用失败时返回重试提示"""
        import llm_advisor
        llm_advisor.reset_client()
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("timeout")
        llm_advisor._client = mock_client
        llm_advisor._client_init_attempted = True

        result = llm_advisor.chat("test")
        assert "失败" in result or "重试" in result


# ================================================================
#  TestBuildSystemContext
# ================================================================

class TestBuildSystemContext:
    def test_basic_context(self, tmp_dir):
        """系统上下文应包含基本信息"""
        import llm_advisor
        # Mock all external calls to avoid network
        with patch("llm_advisor.calc_cumulative_stats",
                   side_effect=ImportError("mock"), create=True), \
             patch("llm_advisor.calc_equity_curve",
                   side_effect=ImportError("mock"), create=True):
            context = llm_advisor._build_system_context()
        assert "量化交易系统" in context
        assert "总经理" in context or "AI" in context
