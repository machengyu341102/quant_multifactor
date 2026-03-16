"""
特征工程引擎
============
自动从原始因子生成交互特征, 提升 ML 模型的非线性捕捉能力:
  - 交互特征: 因子乘积 (A×B), 因子比率 (A/B)
  - 滞后特征: 因子的 T-1 值 (需历史数据)
  - 相关性剪枝: 去除冗余特征 (|corr| > threshold)
  - 动态发现: 自动检测 DataFrame 中所有 s_* 因子列

用法:
  from feature_engineer import expand_features, get_feature_config
  df_expanded = expand_features(df)           # 训练时
  X = apply_saved_features(candidates, cfg)   # 预测时
"""

from __future__ import annotations

import os
import sys
from itertools import combinations

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("feature_eng")

_DIR = os.path.dirname(os.path.abspath(__file__))
_FEATURE_CFG_PATH = os.path.join(_DIR, "feature_config.json")

# ================================================================
#  配置
# ================================================================

try:
    from config import FEATURE_ENGINEERING_PARAMS as _FE_PARAMS
except ImportError:
    _FE_PARAMS = {}

# 默认参数
DEFAULTS = {
    "enabled": True,
    "interaction_types": ["multiply", "ratio"],   # multiply: A*B, ratio: A/(B+eps)
    "max_interactions": 30,                        # 最多生成 N 个交互特征
    "top_k_factors": 8,                            # 只对方差最大的 top-K 因子做交互
    "corr_prune_threshold": 0.95,                  # 相关性 > 此值则剪枝
    "min_nonzero_ratio": 0.3,                      # 因子非零比例低于此值则跳过
    "ratio_epsilon": 1e-6,                         # 除法防零
}

def _cfg(key: str):
    return _FE_PARAMS.get(key, DEFAULTS[key])


# ================================================================
#  1. 发现因子列
# ================================================================

def discover_factor_columns(df: pd.DataFrame) -> list[str]:
    """自动检测 DataFrame 中所有 s_* 因子列 + 常用原始特征"""
    factor_cols = []
    for col in df.columns:
        if col.startswith("s_") and df[col].dtype in (np.float64, np.float32, np.int64, float, int):
            if df[col].notna().mean() >= _cfg("min_nonzero_ratio"):
                factor_cols.append(col)

    # 原始数值特征
    raw_features = [
        "rsi", "volatility", "vol_ratio", "pullback_5d", "pullback_20d",
        "ret_3d", "pct_chg", "resistance_ratio", "consecutive_vol",
        "total_score", "regime_score",
    ]
    for col in raw_features:
        if col in df.columns and df[col].notna().mean() >= _cfg("min_nonzero_ratio"):
            if col not in factor_cols:
                factor_cols.append(col)

    return factor_cols


def _select_top_factors(df: pd.DataFrame, factor_cols: list[str],
                        top_k: int) -> list[str]:
    """按方差排序, 选 top-K 因子用于交互"""
    if len(factor_cols) <= top_k:
        return factor_cols

    variances = {}
    for col in factor_cols:
        v = df[col].var()
        if pd.notna(v):
            variances[col] = v
    ranked = sorted(variances, key=variances.get, reverse=True)
    return ranked[:top_k]


# ================================================================
#  2. 生成交互特征
# ================================================================

def generate_interactions(df: pd.DataFrame,
                          factor_cols: list[str] | None = None,
                          ) -> tuple[pd.DataFrame, list[dict]]:
    """在 df 上生成交互特征列, 返回 (扩展后df, 交互配置列表)

    配置列表用于保存, 以便预测时复现相同交互.
    """
    if not _cfg("enabled"):
        return df, []

    if factor_cols is None:
        factor_cols = discover_factor_columns(df)

    top_k = _cfg("top_k_factors")
    top_factors = _select_top_factors(df, factor_cols, top_k)

    if len(top_factors) < 2:
        logger.info("[FE] 因子不足2个, 跳过交互特征")
        return df, []

    interaction_types = _cfg("interaction_types")
    max_n = _cfg("max_interactions")
    eps = _cfg("ratio_epsilon")

    interactions = []
    count = 0

    for a, b in combinations(top_factors, 2):
        if count >= max_n:
            break

        if "multiply" in interaction_types:
            col_name = f"ix_{a}_{b}_mul"
            df[col_name] = df[a].fillna(0) * df[b].fillna(0)
            interactions.append({"type": "multiply", "a": a, "b": b, "name": col_name})
            count += 1
            if count >= max_n:
                break

        if "ratio" in interaction_types:
            col_name = f"ix_{a}_{b}_rat"
            b_vals = df[b].fillna(0).abs() + eps
            df[col_name] = df[a].fillna(0) / b_vals
            # 裁剪极端值
            df[col_name] = df[col_name].clip(-10, 10)
            interactions.append({"type": "ratio", "a": a, "b": b, "name": col_name})
            count += 1

    logger.info("[FE] 生成 %d 个交互特征 (from %d 因子)", len(interactions), len(top_factors))
    return df, interactions


def generate_regime_interactions(df: pd.DataFrame,
                                  factor_cols: list[str] | None = None,
                                  ) -> tuple[pd.DataFrame, list[dict]]:
    """生成 Regime-Aware 交叉特征: regime_score × top因子

    让 ML 模型学习 "牛市中动量强≠熊市中动量强" 的非线性关系.
    """
    if "regime_score" not in df.columns:
        return df, []

    if factor_cols is None:
        factor_cols = discover_factor_columns(df)

    # 选最重要的因子做 regime 交叉
    top_k = min(_cfg("top_k_factors"), len(factor_cols))
    top_factors = _select_top_factors(df, factor_cols, top_k)

    # 排除 regime_score 本身
    top_factors = [f for f in top_factors if f != "regime_score"]

    interactions = []
    regime = df["regime_score"].fillna(0.5)

    for factor in top_factors[:6]:  # 最多6个regime交叉
        col_name = f"rx_{factor}_regime"
        df[col_name] = df[factor].fillna(0) * regime
        interactions.append({
            "type": "regime_cross",
            "a": factor,
            "b": "regime_score",
            "name": col_name,
        })

    if interactions:
        logger.info("[FE] 生成 %d 个 Regime-Aware 交叉特征", len(interactions))
    return df, interactions


def generate_temporal_features(df: pd.DataFrame, 
                                 history_df: pd.DataFrame | None = None,
                                 lookback: int = 5) -> tuple[pd.DataFrame, list[dict]]:
    """生成时序特征: 斜率, 5日波动率, 变化率
    
    让模型识别因子是在 "变强" 还是 "衰减".
    """
    if history_df is None or history_df.empty:
        return df, []
        
    factor_cols = discover_factor_columns(df)
    temporal_features = []
    
    # 仅处理数值型因子
    numeric_factors = [f for f in factor_cols if pd.api.types.is_numeric_dtype(df[f])]
    
    for f in numeric_factors[:10]: # 限制前10个核心因子，防止特征爆炸
        # 1. 变化率 (T vs T-1)
        # 假设 history_df 已经按日期排序，且包含 code 和因子
        try:
            # 简化版: 这里假设 df 是单日, history_df 是过去数据
            # 实际计算需要基于 code 进行 join 或 group
            col_name = f"t_slope_{f}"
            # 逻辑: (最新值 - 均值) / 标准差
            avg_val = history_df.groupby("code")[f].mean()
            std_val = history_df.groupby("code")[f].std().replace(0, 1)
            
            # 映射回当前 df
            df[col_name] = (df[f] - df["code"].map(avg_val)) / df["code"].map(std_val)
            
            temporal_features.append({
                "type": "temporal_slope", "factor": f, "name": col_name
            })
        except Exception:
            continue
            
    if temporal_features:
        logger.info(f"[FE] 生成 {len(temporal_features)} 个时序特征")
    return df, temporal_features

# ================================================================
#  3. 相关性剪枝
# ================================================================

def prune_correlated(df: pd.DataFrame,
                     feature_cols: list[str],
                     threshold: float | None = None,
                     ) -> list[str]:
    """移除高度相关的特征, 保留原始因子优先于交互因子"""
    if threshold is None:
        threshold = _cfg("corr_prune_threshold")

    valid_cols = [c for c in feature_cols if c in df.columns]
    if len(valid_cols) < 2:
        return valid_cols

    corr_matrix = df[valid_cols].corr().abs()
    to_drop = set()

    for i in range(len(valid_cols)):
        if valid_cols[i] in to_drop:
            continue
        for j in range(i + 1, len(valid_cols)):
            if valid_cols[j] in to_drop:
                continue
            if corr_matrix.iloc[i, j] > threshold:
                # 优先删除交互特征 (ix_ 前缀)
                if valid_cols[j].startswith("ix_"):
                    to_drop.add(valid_cols[j])
                elif valid_cols[i].startswith("ix_"):
                    to_drop.add(valid_cols[i])
                else:
                    # 都是原始因子, 删后者
                    to_drop.add(valid_cols[j])

    kept = [c for c in valid_cols if c not in to_drop]
    if to_drop:
        logger.info("[FE] 剪枝移除 %d 个冗余特征 (corr>%.2f): %s",
                    len(to_drop), threshold, list(to_drop)[:5])
    return kept


# ================================================================
#  4. 一站式接口 — 训练时
# ================================================================

def expand_features(df: pd.DataFrame,
                    save_config: bool = True,
                    ) -> tuple[pd.DataFrame, list[str]]:
    """训练时调用: 自动发现因子 → 生成交互 → 剪枝 → 返回最终特征列

    Returns:
        (扩展后的 df, 最终特征列名列表)
    """
    if not _cfg("enabled"):
        cols = discover_factor_columns(df)
        return df, cols

    # 发现所有原始因子
    raw_factors = discover_factor_columns(df)
    if len(raw_factors) < 2:
        return df, raw_factors

    # 生成因子间交互
    df, interactions = generate_interactions(df, raw_factors)

    # 生成 Regime-Aware 交叉
    df, regime_ixs = generate_regime_interactions(df, raw_factors)
    interactions.extend(regime_ixs)

    # 合并所有候选特征
    interaction_names = [ix["name"] for ix in interactions]
    all_features = raw_factors + interaction_names

    # 剪枝
    final_features = prune_correlated(df, all_features)

    # 保存配置 (预测时复现)
    if save_config and interactions:
        cfg = {
            "raw_factors": raw_factors,
            "interactions": interactions,
            "final_features": final_features,
            "top_factors_used": list(_select_top_factors(df, raw_factors,
                                                         _cfg("top_k_factors"))),
        }
        safe_save(_FEATURE_CFG_PATH, cfg)
        logger.info("[FE] 特征配置已保存: %d 原始 + %d 交互 → %d 最终",
                    len(raw_factors), len(interactions), len(final_features))

    return df, final_features


# ================================================================
#  5. 一站式接口 — 预测时
# ================================================================

def apply_saved_features(candidates: list[dict],
                         feature_config: dict | None = None,
                         ) -> tuple[pd.DataFrame, list[str]]:
    """预测时调用: 从保存的配置复现交互特征

    Args:
        candidates: [{factor_scores: {s_rsi: ..., ...}, ...}]
        feature_config: 特征配置 (None=从文件加载)

    Returns:
        (特征 DataFrame, 特征列名)
    """
    if feature_config is None:
        feature_config = safe_load(_FEATURE_CFG_PATH, default={})

    if not feature_config:
        # 没有配置, 退化为直接提取原始特征
        return _candidates_to_df(candidates), []

    # 构建原始特征 DataFrame
    df = _candidates_to_df(candidates)

    # 复现交互特征
    eps = _cfg("ratio_epsilon")
    for ix in feature_config.get("interactions", []):
        a, b = ix["a"], ix["b"]
        col_name = ix["name"]

        if a not in df.columns or b not in df.columns:
            df[col_name] = 0.0
            continue

        if ix["type"] == "multiply" or ix["type"] == "regime_cross":
            df[col_name] = df[a].fillna(0) * df[b].fillna(0)
        elif ix["type"] == "ratio":
            b_vals = df[b].fillna(0).abs() + eps
            df[col_name] = (df[a].fillna(0) / b_vals).clip(-10, 10)

    final_features = feature_config.get("final_features", [])
    # 确保所有特征列存在
    for col in final_features:
        if col not in df.columns:
            df[col] = 0.0

    return df, final_features


def _candidates_to_df(candidates: list[dict]) -> pd.DataFrame:
    """将候选股列表转换为特征 DataFrame"""
    rows = []
    for c in candidates:
        row = {}
        fs = c.get("factor_scores", {})
        row.update(fs)
        # 额外字段
        for key in ["total_score", "regime_score", "rsi", "volatility",
                     "vol_ratio", "pullback_5d", "pullback_20d", "ret_3d",
                     "pct_chg", "resistance_ratio", "consecutive_vol"]:
            if key in c and key not in row:
                row[key] = c[key]
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ================================================================
#  6. 特征重要性追踪
# ================================================================

def update_feature_importance(importance: dict[str, float]):
    """持久化最新的特征重要性, 用于趋势追踪"""
    cfg = safe_load(_FEATURE_CFG_PATH, default={})
    history = cfg.get("importance_history", [])
    from datetime import date
    history.append({
        "date": date.today().isoformat(),
        "importance": importance,
    })
    # 保留最近30天
    if len(history) > 30:
        history = history[-30:]
    cfg["importance_history"] = history
    safe_save(_FEATURE_CFG_PATH, cfg)


def get_feature_trends(top_n: int = 10) -> list[dict]:
    """获取特征重要性趋势 (最近N天的排名变化)"""
    cfg = safe_load(_FEATURE_CFG_PATH, default={})
    history = cfg.get("importance_history", [])
    if not history:
        return []

    latest = history[-1].get("importance", {})
    sorted_features = sorted(latest.items(), key=lambda x: x[1], reverse=True)[:top_n]

    trends = []
    for feat_name, current_imp in sorted_features:
        # 查找7天前的重要性
        prev_imp = 0.0
        if len(history) >= 7:
            prev_imp = history[-7].get("importance", {}).get(feat_name, 0.0)

        trends.append({
            "feature": feat_name,
            "importance": round(current_imp, 4),
            "delta_7d": round(current_imp - prev_imp, 4),
            "is_interaction": feat_name.startswith("ix_"),
        })

    return trends
