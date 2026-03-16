"""
策略执行监控 - 确保策略真的运行并保存了数据
"""
import json
from datetime import datetime
from notifier import notify_wechat_raw

def monitor_strategy_execution():
    """监控策略执行情况"""

    # 读取scheduler日志最后100行
    with open('scheduler.log', 'r') as f:
        lines = f.readlines()[-100:]

    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now()

    # 检查今天应该运行的策略
    checks = []

    if now.hour >= 9 and now.minute >= 30:
        # 检查集合竞价 (09:25)
        auction_ran = any('集合竞价' in line and today in line for line in lines)
        checks.append(('集合竞价', '09:25', auction_ran))

    if now.hour >= 10:
        # 检查低吸回调 (09:50)
        dip_ran = any('低吸回调' in line and today in line for line in lines)
        checks.append(('低吸回调', '09:50', dip_ran))

    if now.hour >= 15 and now.minute >= 15:
        # 检查隔夜选股 (15:10)
        overnight_ran = any('隔夜' in line and today in line for line in lines)
        checks.append(('隔夜选股', '15:10', overnight_ran))

    # 报告
    failed = [c for c in checks if not c[2]]

    if failed:
        msg = f"策略执行异常 ({today})\n\n"
        for name, time, _ in failed:
            msg += f"❌ {name} ({time}) 未执行\n"

        notify_wechat_raw("策略执行告警", msg)
        print(msg)
        return False
    else:
        print(f"✅ 策略执行正常 ({len(checks)}个已检查)")
        return True

if __name__ == "__main__":
    monitor_strategy_execution()
