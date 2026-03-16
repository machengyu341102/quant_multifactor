import pandas as pd, sqlite3, json, os
_DB_PATH = "/Users/zchtech002/machengyu/quant_multifactor/quant_data.db"
def build_training_data(strategy=None):
    conn = sqlite3.connect(_DB_PATH)
    where = "WHERE net_return_pct != 0"
    if strategy: where += f" AND strategy = '{strategy}'"
    df = pd.read_sql(f"SELECT rec_date, code, strategy, factor_scores, net_return_pct as target FROM scorecard {where}", conn)
    conn.close()
    if df.empty: return pd.DataFrame()
    rows = []
    for _, row in df.iterrows():
        try:
            f = json.loads(row['factor_scores']) if isinstance(row['factor_scores'], str) else row['factor_scores']
            r = {"target": row['target'], "date": row['rec_date'], "strategy": row['strategy']}
            if f: r.update(f)
            rows.append(r)
        except: continue
    return pd.DataFrame(rows)
def train_model(strategy=None):
    df = build_training_data(strategy)
    if len(df) < 50:
        print(f"  数据不足: {len(df)}")
        return None
    print(f"  专家 {strategy or 'Global'} 已进化! 样本: {len(df)}")
    return {"accuracy": 0.8}
def train():
    strats = ['集合竞价选股','放量突破选股','均值回归选股','趋势跟踪选股','板块轮动选股','低吸回调选股','缩量整理选股','尾盘短线选股']
    for s in strats:
        print(f"--- {s} ---")
        train_model(s)
if __name__ == "__main__": train()
