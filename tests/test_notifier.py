"""
notifier.py 测试
================
覆盖: 微信推送镜像到 APP 消息中心
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAppMessageMirror:
    def test_record_app_message_persists_payload(self, tmp_path, monkeypatch):
        import notifier

        center_path = str(tmp_path / "app_message_center.json")
        monkeypatch.setattr(notifier, "_APP_MESSAGE_CENTER", center_path)

        notifier._record_app_message("学习健康告警", "## 学习健康告警\n\n在线学习 48h 未活跃")

        payload = json.load(open(center_path, "r", encoding="utf-8"))
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["title"] == "学习健康告警"
        assert item["channel"] == "wechat_mirror"
        assert item["preview"]

    def test_record_app_message_deduplicates_latest_same_payload(self, tmp_path, monkeypatch):
        import notifier

        center_path = str(tmp_path / "app_message_center.json")
        monkeypatch.setattr(notifier, "_APP_MESSAGE_CENTER", center_path)

        notifier._record_app_message("夜班完工报告", "夜班完工报告")
        notifier._record_app_message("夜班完工报告", "夜班完工报告")

        payload = json.load(open(center_path, "r", encoding="utf-8"))
        assert len(payload["items"]) == 1
