import sqlite3
import json

_DB = "quant_data.db"

def align():
    print("💎 开始特征基因对齐 (V5.0)...")
    conn = sqlite3.connect(_DB)
    c = conn.cursor()
    
    rows = c.execute("SELECT id, factor_scores FROM scorecard").fetchall()
    total = len(rows)
    count = 0
    
    for r_id, fs_raw in rows:
        try:
            if not fs_raw: continue
            f = json.loads(fs_raw)
            # 建立映射：将简化名对齐为实盘策略名
            new_f = {
                "s_rsi_oversold": f.get("s_rsi", 0.5),
                "s_volume_shrink": f.get("s_vol", 0.5),
                "s_ma_distance": f.get("s_trend", 0.5),
                "s_fundamental": f.get("s_fundamental", 0.5),
                "s_fund_flow": f.get("s_fund_flow", 0.5),
                "s_momentum": f.get("s_rsi", 0.5), # 辅助对齐
                "s_volatility": f.get("s_volatility", 0.02)
            }
            c.execute("UPDATE scorecard SET factor_scores=? WHERE id=?", (json.dumps(new_f), r_id))
            count += 1
            if count % 10000 == 0:
                print(f"  ⚡ 进度: {count}/{total} 对齐完成")
        except:
            continue
            
    conn.commit()
    conn.close()
    print(f"🏆 大功告成！共对齐 {count} 条样本基因。")

if __name__ == "__main__":
    align()
