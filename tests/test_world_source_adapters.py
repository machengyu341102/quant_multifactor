import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWorldSourceAdapters:
    def test_build_source_statuses_enriches_required_runtime_sources(self):
        from world_source_adapters import build_source_statuses

        statuses = build_source_statuses(
            [
                {
                    "key": "news_digest",
                    "label": "全球新闻摘要",
                    "updated_at": "2026-03-30T16:00:00",
                    "freshness_score": 84.0,
                    "reliability_score": 64.8,
                    "authority_score": 46.0,
                    "timeliness_score": 84.0,
                    "signal_count": 18,
                    "summary": "新闻摘要正常。",
                },
                {
                    "key": "official_ingest",
                    "label": "官方口径入库",
                    "updated_at": "2026-03-30T15:50:00",
                    "freshness_score": 80.0,
                    "reliability_score": 78.4,
                    "authority_score": 94.0,
                    "timeliness_score": 80.0,
                    "signal_count": 9,
                    "summary": "官方口径正常。",
                },
            ]
        )

        assert statuses
        first = next(item for item in statuses if item["key"] == "news_digest")
        official = next(item for item in statuses if item["key"] == "official_ingest")
        assert first["required"] is True
        assert first["external"] is True
        assert first["fetch_mode"] == "auto_digest"
        assert first["data_quality_score"] > 0
        assert official["authority_score"] >= 90
        assert official["required"] is True

    def test_build_source_statuses_marks_missing_required_source_unavailable(self):
        from world_source_adapters import build_source_status

        status = build_source_status(
            {
                "key": "execution_timeline",
                "label": "执行时间线",
                "updated_at": None,
                "signal_count": 0,
                "summary": "",
            }
        )

        assert status["required"] is True
        assert status["available"] is False
        assert status["stale"] is True
        assert status["freshness_label"] == "缺失"
