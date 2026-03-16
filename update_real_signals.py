"""
从overnight_result_v5.csv读取真实数据，更新到signal_tracker.json
"""
import json
import csv
from datetime import datetime

# 读取CSV
signals = []
with open('overnight_result_v5.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 3:  # 只取TOP3
            break

        code = row['code']
        name = row['name']
        price = float(row['latest_close'])
        score = float(row['total_score'])

        signals.append({
            "id": f"sig_real_{i+1}",
            "code": code,
            "name": name,
            "strategy": "overnight",
            "strategies": ["overnight"],
            "score": score,
            "price": price,
            "change_pct": 0,
            "high": price * 1.02,
            "low": price * 0.98,
            "volume": 0,
            "turnover": 0,
            "buy_price": round(price * 0.997, 2),
            "stop_loss": round(price * 0.97, 2),
            "target_price": round(price * 1.08, 2),
            "risk_reward": 2.5,
            "timestamp": datetime.now().isoformat(),
            "consensus_count": 1,
            "factor_scores": {
                "s_rsi": float(row.get('s_rsi', 0)),
                "s_boll": float(row.get('s_boll', 0)),
                "s_vol": float(row.get('s_vol', 0)),
                "s_volatility": float(row.get('s_volatility', 0)),
                "s_trend": float(row.get('s_trend', 0)),
                "s_flow_1d": float(row.get('s_flow_1d', 0)),
                "s_flow_trend": float(row.get('s_flow_trend', 0)),
                "s_overnight": float(row.get('s_overnight', 0)),
                "s_hot": float(row.get('s_hot', 0)),
                "s_fundamental": float(row.get('s_fundamental', 0))
            },
            "regime": "震荡市",
            "regime_score": 0.75
        })

# 保存
with open('signal_tracker.json', 'w', encoding='utf-8') as f:
    json.dump({
        "signals": signals,
        "last_update": datetime.now().isoformat()
    }, f, ensure_ascii=False, indent=2)

print(f"✅ 已更新 {len(signals)} 条真实信号到 signal_tracker.json")
for i, s in enumerate(signals, 1):
    print(f"  {i}. {s['code']} {s['name']} ¥{s['price']} (得分{s['score']:.3f})")
