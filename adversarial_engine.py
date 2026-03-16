import numpy as np
from log_config import get_logger

logger = get_logger("adversarial")

def get_adversarial_score(code, factor_scores):
    """
    博弈论分值计算 (V5.0)
    1. 拥挤度: 如果 RSI > 75 且 换手率 > 15%, 判定为过度拥挤, 风险值 +0.4
    2. 散户热度: 模拟散户情绪 (此处基于量价背离判定)
    3. 结论: 风险分越高, 越容易被主力反割
    """
    risk_score = 0.0
    
    # 逻辑 1: 拥挤度拦截 (防止追高量化抱团股)
    rsi = factor_scores.get('s_rsi', 0.5)
    vol = factor_scores.get('s_volatility', 0.5)
    
    if rsi > 0.75 and vol > 0.7:
        risk_score += 0.3
        
    # 逻辑 2: 压力位博弈 (寻找上方获利盘压力)
    # 此处假设 ret_1d 极高时, 潜在抛压大
    ret = factor_scores.get('ret_1d', 0)
    if ret > 0.07:
        risk_score += 0.2
        
    return risk_score

def apply_game_theory_filter(picks):
    """
    对选股结果应用博弈论对冲逻辑
    """
    safe_picks = []
    for p in picks:
        risk = get_adversarial_score(p['code'], p.get('factor_scores', {}))
        p['game_risk_score'] = risk
        if risk < 0.4: # 只有博弈环境健康的才允许进入实盘
            safe_picks.append(p)
        else:
            logger.warning(f"🚫 [博弈拦截] {p['code']} 风险过高({risk}), 怀疑为量化拥挤或散户热点, 已剔除")
            
    return safe_picks
