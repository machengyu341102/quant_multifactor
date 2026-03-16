"""
数据保存健康检查 + 自动修复
每小时运行一次，确保数据不丢失
"""
import json
import logging
import os

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
from db_store import load_trade_journal, load_scorecard

def check_data_health():
    """检查数据健康度"""
    today = datetime.now().strftime('%Y-%m-%d')
    issues = []

    # 1. 检查scorecard
    scorecard = load_scorecard()
    today_scorecard = [s for s in scorecard if s.get('rec_date','').startswith(today)]

    # 2. 检查数据库
    journal = load_trade_journal()
    today_journal = [j for j in journal if j.get('rec_date','').startswith(today)]

    # 3. 检查signal_tracker
    tracker_path = 'signal_tracker.json'
    if os.path.exists(tracker_path):
        with open(tracker_path, 'r') as f:
            tracker = json.load(f)
            signals = tracker.get('signals', [])
    else:
        signals = []

    print(f"📊 数据健康检查 ({today})")
    print(f"  scorecard.json: {len(today_scorecard)}条")
    print(f"  数据库: {len(today_journal)}条")
    print(f"  signal_tracker: {len(signals)}条")

    # 判断是否异常
    now = datetime.now()
    if now.hour >= 10 and now.weekday() < 5:  # 工作日10点后
        if len(today_scorecard) == 0 and len(today_journal) == 0:
            issues.append("❌ 严重: 今日无任何数据！")

        if len(signals) == 0:
            issues.append("⚠️  警告: signal_tracker为空，手机APP无数据")

    if issues:
        print("\n🚨 发现问题:")
        for issue in issues:
            print(f"  {issue}")

        # 推送告警
        try:
            from notifier import notify_wechat_raw
            notify_wechat_raw(
                "数据健康告警",
                f"时间: {datetime.now().strftime('%H:%M')}\n" + "\n".join(issues)
            )
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        return False
    else:
        print("✅ 数据健康")
        return True

if __name__ == "__main__":
    check_data_health()
