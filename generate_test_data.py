"""
生成测试数据 - 让PWA立即可以体验完整功能
"""
import json
import os
from datetime import datetime, timedelta
import random

_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================
# 1. 生成信号数据
# ================================================================

signals = []
today = datetime.now().strftime("%Y-%m-%d")

# 强信号 (多策略共识)
strong_signals = [
    {
        "id": "sig_001",
        "code": "603306",
        "name": "江淮汽车",
        "strategy": "auction",
        "strategies": ["auction", "dip_buy", "trend"],
        "score": 0.85,
        "price": 8.52,
        "change_pct": 2.1,
        "high": 8.68,
        "low": 8.32,
        "volume": 12500000,
        "turnover": 3.2,
        "buy_price": 8.50,
        "stop_loss": 8.21,
        "target_price": 9.15,
        "risk_reward": 2.1,
        "timestamp": f"{today}T14:05:00",
        "consensus_count": 3,
        "factor_scores": {
            "s_vol": 0.15,
            "s_boll": 0.12,
            "s_rsi": 0.08,
            "s_ma": 0.10,
            "s_momentum": 0.08,
            "s_macd": 0.07,
            "s_flow_1d": 0.10,
            "s_flow_trend": 0.08,
            "s_turnover": 0.07,

        },
        "regime": "震荡市",
        "regime_score": 0.85
    },
    {
        "id": "sig_002",
        "code": "603588",
        "name": "高能环境",
        "strategy": "auction",
        "strategies": ["auction", "trend"],
        "score": 0.78,
        "price": 12.35,
        "change_pct": 1.8,
        "high": 12.50,
        "low": 12.20,
        "volume": 8500000,
        "turnover": 2.8,
        "buy_price": 12.30,
        "stop_loss": 11.95,
        "target_price": 13.20,
        "risk_reward": 2.5,
        "timestamp": f"{today}T13:50:00",
        "consensus_count": 2,
        "factor_scores": {
            "s_vol": 0.12,
            "s_boll": 0.10,
            "s_rsi": 0.09,
            "s_ma": 0.11,
            "s_momentum": 0.09,
            "s_macd": 0.08,
            "s_flow_1d": 0.09,
            "s_flow_trend": 0.07,
            "s_turnover": 0.06,

        },
        "regime": "震荡市",
        "regime_score": 0.82
    }
]

# 普通信号
normal_signals = [
    {
        "id": "sig_003",
        "code": "600519",
        "name": "贵州茅台",
        "strategy": "trend",
        "strategies": ["trend"],
        "score": 0.68,
        "price": 1580.00,
        "change_pct": 0.5,
        "high": 1590.00,
        "low": 1575.00,
        "volume": 2500000,
        "turnover": 1.2,
        "buy_price": 1575.00,
        "stop_loss": 1540.00,
        "target_price": 1706.00,
        "risk_reward": 3.7,
        "timestamp": f"{today}T10:20:00",
        "consensus_count": 1,
        "factor_scores": {
            "s_vol": 0.08,
            "s_boll": 0.09,
            "s_rsi": 0.07,
            "s_ma": 0.12,
            "s_momentum": 0.10,
            "s_macd": 0.09,
            "s_flow_1d": 0.06,
            "s_flow_trend": 0.05,
            "s_turnover": 0.04,

        },
        "regime": "震荡市",
        "regime_score": 0.75
    },
    {
        "id": "sig_004",
        "code": "000001",
        "name": "平安银行",
        "strategy": "dip_buy",
        "strategies": ["dip_buy"],
        "score": 0.65,
        "price": 10.20,
        "change_pct": 1.2,
        "high": 10.35,
        "low": 10.10,
        "volume": 15000000,
        "turnover": 4.5,
        "buy_price": 10.18,
        "stop_loss": 9.90,
        "target_price": 10.80,
        "risk_reward": 2.2,
        "timestamp": f"{today}T09:50:00",
        "consensus_count": 1,
        "factor_scores": {
            "s_vol": 0.10,
            "s_boll": 0.08,
            "s_rsi": 0.11,
            "s_ma": 0.07,
            "s_momentum": 0.06,
            "s_macd": 0.05,
            "s_flow_1d": 0.08,
            "s_flow_trend": 0.06,
            "s_turnover": 0.07,

        },
        "regime": "震荡市",
        "regime_score": 0.70
    }
]

signals = strong_signals + normal_signals

# 保存信号数据
signal_tracker_path = os.path.join(_DIR, "signal_tracker.json")
signal_tracker = {
    "signals": signals,
    "last_update": datetime.now().isoformat()
}
with open(signal_tracker_path, 'w', encoding='utf-8') as f:
    json.dump(signal_tracker, f, ensure_ascii=False, indent=2)

print(f"✅ 生成 {len(signals)} 条信号数据")

# ================================================================
# 2. 生成持仓数据
# ================================================================

positions = [
    {
        "code": "603306",
        "name": "江淮汽车",
        "quantity": 1000,
        "cost_price": 10.00,
        "current_price": 10.52,
        "market_value": 10520,
        "profit_loss": 520,
        "profit_loss_pct": 5.2,
        "stop_loss": 9.75,
        "take_profit": 10.80,
        "hold_days": 2,
        "strategy": "auction",
        "buy_time": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "high_price": 10.68,
        "low_price": 9.85,
        "trailing_stop": True,
        "trailing_trigger_price": 10.48,
        "trades": [
            {
                "time": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 14:05:00"),
                "type": "buy",
                "price": 10.00,
                "quantity": 1000,
                "reason": "集合竞价信号 (得分0.78)"
            }
        ]
    },
    {
        "code": "603588",
        "name": "高能环境",
        "quantity": 800,
        "cost_price": 12.50,
        "current_price": 12.98,
        "market_value": 10384,
        "profit_loss": 384,
        "profit_loss_pct": 3.8,
        "stop_loss": 12.15,
        "take_profit": 13.50,
        "hold_days": 1,
        "strategy": "auction",
        "buy_time": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "high_price": 13.05,
        "low_price": 12.40,
        "trailing_stop": False,
        "trailing_trigger_price": 0,
        "trades": [
            {
                "time": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 13:50:00"),
                "type": "buy",
                "price": 12.50,
                "quantity": 800,
                "reason": "集合竞价信号 (得分0.72)"
            }
        ]
    },
    {
        "code": "600519",
        "name": "贵州茅台",
        "quantity": 6,
        "cost_price": 1580.00,
        "current_price": 1585.00,
        "market_value": 9510,
        "profit_loss": 30,
        "profit_loss_pct": 0.3,
        "stop_loss": 1540.00,
        "take_profit": 1706.00,
        "hold_days": 3,
        "strategy": "trend",
        "buy_time": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "high_price": 1595.00,
        "low_price": 1570.00,
        "trailing_stop": False,
        "trailing_trigger_price": 0,
        "trades": [
            {
                "time": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d 10:20:00"),
                "type": "buy",
                "price": 1580.00,
                "quantity": 6,
                "reason": "趋势跟踪信号 (得分0.68)"
            }
        ]
    },
    {
        "code": "000001",
        "name": "平安银行",
        "quantity": 1000,
        "cost_price": 10.00,
        "current_price": 9.82,
        "market_value": 9820,
        "profit_loss": -180,
        "profit_loss_pct": -1.8,
        "stop_loss": 9.75,
        "take_profit": 10.80,
        "hold_days": 1,
        "strategy": "dip_buy",
        "buy_time": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "high_price": 10.15,
        "low_price": 9.80,
        "trailing_stop": False,
        "trailing_trigger_price": 0,
        "trades": [
            {
                "time": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 09:50:00"),
                "type": "buy",
                "price": 10.00,
                "quantity": 1000,
                "reason": "低吸回调信号 (得分0.65)"
            }
        ]
    }
]

paper_positions_path = os.path.join(_DIR, "paper_positions.json")
paper_data = {
    "positions": positions,
    "cash": 59786,
    "total_assets": 100000,
    "last_update": datetime.now().isoformat()
}
with open(paper_positions_path, 'w', encoding='utf-8') as f:
    json.dump(paper_data, f, ensure_ascii=False, indent=2)

print(f"✅ 生成 {len(positions)} 个持仓数据")

# ================================================================
# 3. 更新系统状态
# ================================================================

agent_memory_path = os.path.join(_DIR, "agent_memory.json")
if os.path.exists(agent_memory_path):
    with open(agent_memory_path, 'r', encoding='utf-8') as f:
        memory = json.load(f)
else:
    memory = {}

memory["system_start_time"] = (datetime.now() - timedelta(days=18, hours=3)).isoformat()
memory["health_score"] = 85
memory["ooda_cycles"] = 1247
memory["decision_accuracy"] = 0.68

with open(agent_memory_path, 'w', encoding='utf-8') as f:
    json.dump(memory, f, ensure_ascii=False, indent=2)

print("✅ 更新系统状态")

# ================================================================
# 4. 生成学习进度数据
# ================================================================

learning_state_path = os.path.join(_DIR, "learning_state.json")
learning_data = {
    "today_cycles": 3,
    "factor_adjustments": 18,
    "online_updates": 12,
    "experiments_running": 2,
    "new_factors_deployed": 2,
    "decision_accuracy": 0.68,
    "last_update": datetime.now().isoformat()
}
with open(learning_state_path, 'w', encoding='utf-8') as f:
    json.dump(learning_data, f, ensure_ascii=False, indent=2)

print("✅ 生成学习进度数据")

print("\n🎉 测试数据生成完成！")
print("\n📱 现在刷新手机页面，可以看到:")
print("  - 信号中心: 4条信号 (2强信号 + 2普通信号)")
print("  - 持仓管理: 4个持仓 (3盈1亏)")
print("  - 学习进度: 完整学习统计")
print("  - 首页: 系统运行18天3小时")
