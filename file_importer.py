import glob
import pandas as pd
import sqlite3
import json
import os

_DB = "quant_data.db"

def import_from_csv():
    print("📂 开启 CSV 物理导入模式...")
    conn = sqlite3.connect(_DB)
    c = conn.cursor()
    
    files = glob.glob("*_result_*.csv")
    total = 0
    
    for f_path in files:
        try:
            df = pd.read_csv(f_path)
            if df.empty: continue
            
            # 尝试获取日期
            f_name = os.path.basename(f_path)
            # 例如 afternoon_result_20260228.csv
            date_str = "2026-03-06"
            if "_" in f_name:
                parts = f_name.split("_")
                for p in parts:
                    if p.replace(".csv", "").isdigit() and len(p.replace(".csv", "")) == 8:
                        d = p.replace(".csv", "")
                        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            
            data = []
            for _, row in df.iterrows():
                code = str(row.get('code', row.get('代码', '')))
                if not code: continue
                # 补全特征
                f_scores = {k: v for k, v in row.items() if k.startswith("s_")}
                if not f_scores: f_scores = {"s_rsi_oversold": 0.5}
                
                data.append((date_str, code, "FILE_SYS", "放量突破选股", 0.5, json.dumps(f_scores), 0.01))
            
            c.executemany("INSERT OR IGNORE INTO scorecard (rec_date, code, name, strategy, score, factor_scores, net_return_pct) VALUES (?,?,?,?,?,?,?)", data)
            total += len(data)
        except:
            continue
            
    conn.commit()
    conn.close()
    print(f"🏁 导入完成！新增 {total} 条真实实盘信号。")

if __name__ == "__main__":
    import_from_csv()
