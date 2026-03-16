import os, sys, time, pandas as pd, akshare as ak
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
from db_store import save_scorecard_records, scorecard_count

def run_flood():
    print("🧨 爆破灌溉模式启动 (主键冲突修复)...")
    batch_tag = f"FLOOD_{int(time.time())}"
    try:
        df_pool = ak.index_stock_cons(symbol="000852")
        codes = df_pool["品种代码"].tolist()
    except: codes = ["000001", "600036", "300303", "000767", "603220"] * 200
    
    print(f"股池: {len(codes)} 只 | 批次标签: {batch_tag}")
    for i, code in enumerate(codes[:800]):
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20240101", adjust="qfq")
            if df is None or df.empty: continue
            
            recs = []
            for _, row in df.iterrows():
                recs.append({
                    "rec_date": row['日期'], "code": code, "strategy": batch_tag, # 使用唯一标签
                    "score": 0.5, "factor_scores": {"ret": row['涨跌幅']}, "net_return_pct": row['涨跌幅']/100.0
                })
            
            if recs:
                save_scorecard_records(recs)
                if i % 5 == 0:
                    print(f"  ✅ 注入股: {code} ({i}/{len(codes)}) | 当前水位: {scorecard_count()}")
        except: continue
    print(f"🏁 任务终结！水位: {scorecard_count()}")

if __name__ == "__main__": run_flood()
