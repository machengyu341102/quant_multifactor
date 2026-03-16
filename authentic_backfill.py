import sqlite3
import json
import time
import pandas as pd
import akshare as ak

_DB = "quant_data.db"

def compute_strict_factors(df):
    """
    严格基于历史时间序列的因子计算（无前瞻偏差）
    """
    # 1. T+1 真实收益率 (Label)
    # df['收盘'].shift(-1) 表示下一天的收盘价
    df['next_close'] = df['收盘'].shift(-1)
    df['net_return_pct'] = (df['next_close'] - df['收盘']) / df['收盘']
    
    # 2. 计算 RSI (基于 T 日及以前)
    delta = df['收盘'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    # 转化为策略期望的 s_rsi_oversold (越低越超卖，分越高)
    df['s_rsi_oversold'] = ((30 - rsi) / 30).clip(lower=0, upper=1).fillna(0)

    # 3. 计算缩量指标 s_volume_shrink
    vol_ma5 = df['成交量'].rolling(5).mean()
    vol_ma20 = df['成交量'].rolling(20).mean()
    vol_ratio = vol_ma5 / vol_ma20
    df['s_volume_shrink'] = (1 - vol_ratio).clip(lower=0, upper=1).fillna(0)

    # 4. 计算均线偏离 s_ma_distance (替代趋势)
    ma20 = df['收盘'].rolling(20).mean()
    df['s_ma_distance'] = ((df['收盘'] - ma20) / ma20).clip(lower=-0.1, upper=0.1) * 5 + 0.5
    
    return df

def run_authentic_backfill():
    print("🛡️ 开启 100% 纯净历史回测引擎 (严格消除 Look-ahead Bias)...")
    conn = sqlite3.connect(_DB)
    c = conn.cursor()
    
    try:
        df_pool = ak.index_stock_cons(symbol="000852")
        codes = df_pool["品种代码"].tolist()
    except:
        codes = ["000001", "600036", "300303", "000767", "603220", "002594", "600519", "601318"]
    
    # 我们为 8 个策略均衡分配真实样本
    strats = ["集合竞价选股", "放量突破选股", "均值回归选股", "趋势跟踪选股", 
              "板块轮动选股", "低吸回调选股", "缩量整理选股", "尾盘短线选股"]
    
    total_added = 0
    # 选前 200 只股票，获取过去一年的真实日线
    for i, code in enumerate(codes[:200]):
        try:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20240101", adjust="qfq")
            if df is None or len(df) < 30: continue
            
            # 严格计算
            df = compute_strict_factors(df)
            
            # 抛弃最后一天 (因为没有 T+1 收益) 和最前面的 NaN 数据
            valid_df = df.dropna(subset=['net_return_pct', 's_ma_distance', 's_rsi_oversold']).iloc[20:-1]
            if valid_df.empty: continue
            
            data = []
            for _, row in valid_df.iterrows():
                f_scores = {
                    "s_rsi_oversold": round(row['s_rsi_oversold'], 4),
                    "s_volume_shrink": round(row['s_volume_shrink'], 4),
                    "s_ma_distance": round(row['s_ma_distance'], 4),
                    "s_volatility": round(row.get('振幅', 2) / 100.0, 4)
                }
                # 分配给策略，让模型有真实的饭吃
                strat = strats[int(row.name) % 8] 
                ret = float(row['net_return_pct'])
                
                data.append((row['日期'], code, "AUTH_BACKFILL", strat, 0.5, json.dumps(f_scores), ret))
            
            c.executemany("INSERT OR IGNORE INTO scorecard (rec_date, code, name, strategy, score, factor_scores, net_return_pct) VALUES (?,?,?,?,?,?,?)", data)
            conn.commit()
            total_added += len(data)
            
            if i % 10 == 0:
                print(f"  ✅ 真实进度: {i}/200股 | 新增样本: {total_added} | 收益率标准差: {valid_df['net_return_pct'].std():.2%}")
                
        except Exception as e:
            print(f"  ❌ 处理股票 {code} 时出错: {e}")
            continue
            
    print(f"\n🏁 纯净数据注入完成！共新增 {total_added} 条真实样本。")
    conn.close()

if __name__ == "__main__":
    run_authentic_backfill()
