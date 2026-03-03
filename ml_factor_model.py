"""
ML 因子选股模型
===============
用机器学习替代/增强规则打分:
  - 特征: 现有技术因子 (RSI, MA排列, 量比, 波动率, 回撤, 动量...)
  - 标签: 次日收益率 (回归) 或 涨跌方向 (分类)
  - 模型: GradientBoosting (可切换 XGBoost/LightGBM)
  - 验证: Walk-Forward 交叉验证, 防止过拟合
  - 输出: 预测得分, 可与规则打分融合

工作流:
  1. 从 trade_journal + scorecard 构建训练数据
  2. 特征工程 (从 factor_scores 提取)
  3. Walk-Forward 分窗训练+验证
  4. 实盘: 对候选股打分, 输出预测收益/概率
  5. 融合: ML分数 × 权重 + 规则分数 × (1-权重) = 最终分数

用法:
  python3 ml_factor_model.py train          # 训练模型
  python3 ml_factor_model.py evaluate       # 评估模型
  python3 ml_factor_model.py predict        # 预测 (需要候选数据)
"""

from __future__ import annotations

import os
import sys
import pickle
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_store import safe_load, safe_save
from log_config import get_logger

logger = get_logger("ml_factor")

_DIR = os.path.dirname(os.path.abspath(__file__))
_JOURNAL_PATH = os.path.join(_DIR, "trade_journal.json")
_SCORECARD_PATH = os.path.join(_DIR, "scorecard.json")
_SCORECARD_DEFAULT = _SCORECARD_PATH
_MODEL_DIR = os.path.join(_DIR, "models")
_ML_RESULTS_PATH = os.path.join(_DIR, "ml_model_results.json")

# 默认参数
ML_PARAMS = {
    "model_type": "gradient_boosting",     # gradient_boosting | xgboost | lightgbm
    "task": "regression",                   # regression | classification
    "n_estimators": 200,
    "max_depth": 5,
    "learning_rate": 0.05,
    "min_samples_leaf": 10,
    "subsample": 0.8,
    "ml_weight": 0.4,                      # ML得分在最终融合中的权重
    "min_training_samples": 50,
    "wf_train_days": 90,
    "wf_test_days": 30,
    "wf_n_windows": 3,
}

# 从 config.py 读取覆盖
try:
    from config import ML_PARAMS as _CFG_ML
    ML_PARAMS.update(_CFG_ML)
except ImportError:
    pass

# 特征列 (从 factor_scores + 上下文中提取)
FEATURE_COLUMNS = [
    "rsi", "volatility",
    "vol_ratio", "consecutive_vol", "pullback_5d", "pullback_20d",
    "ret_3d", "resistance_ratio", "pct_chg",
]

# 额外可用特征 (去掉零贡献: above_ma60, ma_aligned, s_ma_alignment, s_resistance_break)
EXTRA_FEATURES = [
    "s_volume_breakout", "s_momentum",
    "s_rsi", "s_volatility",
]


# ================================================================
#  数据构建
# ================================================================

def build_training_data(lookback_days: int = 180,
                        strategy: str = None) -> pd.DataFrame:
    """从 trade_journal + scorecard 构建训练数据

    关联键: (date, code, strategy)
    特征: factor_scores 中的各因子
    标签: net_return_pct (次日收益率)

    Returns:
        DataFrame with columns: [features..., target, date, strategy]
    """
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    journal = safe_load(_JOURNAL_PATH, default=[])
    try:
        if _SCORECARD_PATH != _SCORECARD_DEFAULT:
            raise ImportError("test mode")
        from db_store import load_scorecard
        scorecard = load_scorecard(days=lookback_days)
    except Exception:
        scorecard = safe_load(_SCORECARD_PATH, default=[])
        scorecard = [r for r in scorecard if r.get("rec_date", "") >= cutoff]

    # 建 scorecard 索引
    sc_index = {}
    for rec in scorecard:
        key = (rec.get("rec_date", ""), rec.get("code", ""), rec.get("strategy", ""))
        sc_index[key] = rec

    rows = []
    for entry in journal:
        entry_date = entry.get("date", "")
        if entry_date < cutoff:
            continue
        strat = entry.get("strategy", "")
        if strategy and strat != strategy:
            continue

        regime = entry.get("regime", {})
        regime_score = regime.get("score", 0)
        regime_type = regime.get("regime", "unknown")

        for pick in entry.get("picks", []):
            code = pick.get("code", "")
            key = (entry_date, code, strat)
            sc_rec = sc_index.get(key)
            if sc_rec is None:
                continue

            target = sc_rec.get("net_return_pct", 0)
            factor_scores = pick.get("factor_scores", {})

            row = {
                "date": entry_date,
                "code": code,
                "strategy": strat,
                "target": target,
                "total_score": pick.get("total_score", 0),
                "regime_score": regime_score,
            }

            # 从 factor_scores 提取特征
            for col in FEATURE_COLUMNS + EXTRA_FEATURES:
                row[col] = factor_scores.get(col, np.nan)

            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # 编码布尔特征
    for col in ["above_ma60", "ma_aligned", "consecutive_vol"]:
        if col in df.columns:
            df[col] = df[col].astype(float)

    # 编码 regime
    regime_map = {"bear": -1, "neutral": 0, "bull": 1}
    if "regime_type" in df.columns:
        df["regime_encoded"] = df["regime_type"].map(regime_map).fillna(0)

    logger.info("[ML] 训练数据: %d 条 (%d 个策略)",
                len(df), df["strategy"].nunique())
    return df


def _get_feature_columns(df: pd.DataFrame) -> list[str]:
    """获取可用的特征列"""
    available = []
    all_possible = FEATURE_COLUMNS + EXTRA_FEATURES + ["total_score", "regime_score"]
    for col in all_possible:
        if col in df.columns and df[col].notna().sum() > len(df) * 0.3:
            available.append(col)
    return available


# ================================================================
#  模型训练
# ================================================================

def _create_model(task: str = "regression"):
    """创建模型实例"""
    model_type = ML_PARAMS.get("model_type", "gradient_boosting")

    if model_type == "xgboost":
        try:
            import xgboost as xgb
            if task == "classification":
                return xgb.XGBClassifier(
                    n_estimators=ML_PARAMS["n_estimators"],
                    max_depth=ML_PARAMS["max_depth"],
                    learning_rate=ML_PARAMS["learning_rate"],
                    subsample=ML_PARAMS["subsample"],
                    random_state=42,
                    verbosity=0,
                )
            return xgb.XGBRegressor(
                n_estimators=ML_PARAMS["n_estimators"],
                max_depth=ML_PARAMS["max_depth"],
                learning_rate=ML_PARAMS["learning_rate"],
                subsample=ML_PARAMS["subsample"],
                random_state=42,
                verbosity=0,
            )
        except ImportError:
            logger.info("[ML] XGBoost 不可用, 回退到 GradientBoosting")

    if model_type == "lightgbm":
        try:
            import lightgbm as lgb
            if task == "classification":
                return lgb.LGBMClassifier(
                    n_estimators=ML_PARAMS["n_estimators"],
                    max_depth=ML_PARAMS["max_depth"],
                    learning_rate=ML_PARAMS["learning_rate"],
                    subsample=ML_PARAMS["subsample"],
                    random_state=42,
                    verbose=-1,
                )
            return lgb.LGBMRegressor(
                n_estimators=ML_PARAMS["n_estimators"],
                max_depth=ML_PARAMS["max_depth"],
                learning_rate=ML_PARAMS["learning_rate"],
                subsample=ML_PARAMS["subsample"],
                random_state=42,
                verbose=-1,
            )
        except ImportError:
            logger.info("[ML] LightGBM 不可用, 回退到 GradientBoosting")

    # 默认: sklearn GradientBoosting
    from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
    if task == "classification":
        return GradientBoostingClassifier(
            n_estimators=ML_PARAMS["n_estimators"],
            max_depth=ML_PARAMS["max_depth"],
            learning_rate=ML_PARAMS["learning_rate"],
            min_samples_leaf=ML_PARAMS["min_samples_leaf"],
            subsample=ML_PARAMS["subsample"],
            random_state=42,
        )
    return GradientBoostingRegressor(
        n_estimators=ML_PARAMS["n_estimators"],
        max_depth=ML_PARAMS["max_depth"],
        learning_rate=ML_PARAMS["learning_rate"],
        min_samples_leaf=ML_PARAMS["min_samples_leaf"],
        subsample=ML_PARAMS["subsample"],
        random_state=42,
    )


def train_model(strategy: str = None,
                lookback_days: int = 180) -> dict:
    """训练 ML 模型

    Args:
        strategy: 指定策略 (None=全策略混合)
        lookback_days: 训练数据回望天数

    Returns:
        {model, feature_columns, metrics, feature_importance}
    """
    df = build_training_data(lookback_days, strategy)
    min_samples = ML_PARAMS.get("min_training_samples", 50)

    if len(df) < min_samples:
        logger.warning("[ML] 训练数据不足: %d 条 (需要 %d)", len(df), min_samples)
        return {"error": "insufficient_data", "samples": len(df)}

    feature_cols = _get_feature_columns(df)
    if len(feature_cols) < 3:
        return {"error": "insufficient_features", "features": len(feature_cols)}

    X = df[feature_cols].fillna(0).values
    y = df["target"].values

    task = ML_PARAMS.get("task", "regression")
    if task == "classification":
        y = (y > 0).astype(int)

    # 训练
    model = _create_model(task)
    model.fit(X, y)

    # 训练集指标
    from sklearn.metrics import mean_squared_error, r2_score, accuracy_score
    y_pred = model.predict(X)

    if task == "regression":
        mse = float(mean_squared_error(y, y_pred))
        r2 = float(r2_score(y, y_pred))
        metrics = {"mse": round(mse, 4), "rmse": round(mse ** 0.5, 4), "r2": round(r2, 4)}
    else:
        acc = float(accuracy_score(y, y_pred))
        metrics = {"accuracy": round(acc, 4)}

    # 特征重要性
    importance = {}
    if hasattr(model, "feature_importances_"):
        for col, imp in zip(feature_cols, model.feature_importances_):
            importance[col] = round(float(imp), 4)

    # 保存模型
    os.makedirs(_MODEL_DIR, exist_ok=True)
    model_name = strategy or "all"
    model_path = os.path.join(_MODEL_DIR, f"ml_{model_name}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "features": feature_cols, "task": task}, f)

    result = {
        "strategy": strategy or "all",
        "timestamp": datetime.now().isoformat(),
        "training_samples": len(df),
        "features": feature_cols,
        "metrics": metrics,
        "feature_importance": importance,
        "model_path": model_path,
    }

    logger.info("[ML] 训练完成: %d 条, %d 特征, %s",
                len(df), len(feature_cols), metrics)

    return result


# ================================================================
#  Walk-Forward 评估
# ================================================================

def evaluate_walk_forward(strategy: str = None,
                          lookback_days: int = 180) -> dict:
    """Walk-Forward 交叉验证评估

    在每个窗口:
      训练集 → 拟合模型 → 测试集预测 → 计算指标

    Returns:
        {windows: [...], summary: {avg_is_r2, avg_oos_r2, ...}}
    """
    df = build_training_data(lookback_days, strategy)
    min_samples = ML_PARAMS.get("min_training_samples", 50)

    if len(df) < min_samples:
        return {"error": "insufficient_data", "samples": len(df)}

    feature_cols = _get_feature_columns(df)
    if len(feature_cols) < 3:
        return {"error": "insufficient_features"}

    # 按日期排序
    df = df.sort_values("date").reset_index(drop=True)
    dates = sorted(df["date"].unique())

    n_windows = ML_PARAMS.get("wf_n_windows", 3)
    train_days = ML_PARAMS.get("wf_train_days", 90)
    test_days = ML_PARAMS.get("wf_test_days", 30)

    task = ML_PARAMS.get("task", "regression")

    windows = []
    for w in range(n_windows):
        # 从后往前切窗口
        test_end_idx = len(dates) - w * test_days
        test_start_idx = max(0, test_end_idx - test_days)
        train_end_idx = test_start_idx
        train_start_idx = max(0, train_end_idx - train_days)

        if train_start_idx >= train_end_idx or test_start_idx >= test_end_idx:
            break
        if test_end_idx > len(dates):
            break

        train_dates = set(dates[train_start_idx:train_end_idx])
        test_dates = set(dates[test_start_idx:test_end_idx])

        train_df = df[df["date"].isin(train_dates)]
        test_df = df[df["date"].isin(test_dates)]

        if len(train_df) < 20 or len(test_df) < 5:
            continue

        X_train = train_df[feature_cols].fillna(0).values
        X_test = test_df[feature_cols].fillna(0).values
        y_train = train_df["target"].values
        y_test = test_df["target"].values

        if task == "classification":
            y_train = (y_train > 0).astype(int)
            y_test = (y_test > 0).astype(int)

        model = _create_model(task)
        model.fit(X_train, y_train)

        y_train_pred = model.predict(X_train)
        y_test_pred = model.predict(X_test)

        from sklearn.metrics import mean_squared_error, r2_score, accuracy_score

        if task == "regression":
            is_r2 = float(r2_score(y_train, y_train_pred))
            oos_r2 = float(r2_score(y_test, y_test_pred))
            is_rmse = float(mean_squared_error(y_train, y_train_pred) ** 0.5)
            oos_rmse = float(mean_squared_error(y_test, y_test_pred) ** 0.5)

            # 方向准确率: 预测涨跌方向是否正确
            is_dir = float(np.mean((y_train_pred > 0) == (y_train > 0)))
            oos_dir = float(np.mean((y_test_pred > 0) == (y_test > 0)))

            window_data = {
                "window": w + 1,
                "train_samples": len(train_df),
                "test_samples": len(test_df),
                "is_r2": round(is_r2, 4),
                "oos_r2": round(oos_r2, 4),
                "is_rmse": round(is_rmse, 4),
                "oos_rmse": round(oos_rmse, 4),
                "is_direction_acc": round(is_dir, 4),
                "oos_direction_acc": round(oos_dir, 4),
            }
        else:
            is_acc = float(accuracy_score(y_train, y_train_pred))
            oos_acc = float(accuracy_score(y_test, y_test_pred))
            window_data = {
                "window": w + 1,
                "train_samples": len(train_df),
                "test_samples": len(test_df),
                "is_accuracy": round(is_acc, 4),
                "oos_accuracy": round(oos_acc, 4),
            }

        windows.append(window_data)

    # 汇总
    summary = _calc_ml_summary(windows, task)

    result = {
        "strategy": strategy or "all",
        "timestamp": datetime.now().isoformat(),
        "task": task,
        "n_windows": len(windows),
        "windows": windows,
        "summary": summary,
    }

    # 持久化
    _save_ml_results(result)

    return result


def _calc_ml_summary(windows: list, task: str) -> dict:
    """计算 ML 评估汇总"""
    if not windows:
        return {"error": "no_valid_windows"}

    if task == "regression":
        is_r2s = [w["is_r2"] for w in windows]
        oos_r2s = [w["oos_r2"] for w in windows]
        is_dirs = [w.get("is_direction_acc", 0) for w in windows]
        oos_dirs = [w.get("oos_direction_acc", 0) for w in windows]

        return {
            "avg_is_r2": round(float(np.mean(is_r2s)), 4),
            "avg_oos_r2": round(float(np.mean(oos_r2s)), 4),
            "avg_is_direction_acc": round(float(np.mean(is_dirs)), 4),
            "avg_oos_direction_acc": round(float(np.mean(oos_dirs)), 4),
            "r2_decay": round(float(np.mean(is_r2s) - np.mean(oos_r2s)), 4),
            "model_useful": float(np.mean(oos_dirs)) > 0.52,  # 方向准确率 > 52%
        }
    else:
        is_accs = [w["is_accuracy"] for w in windows]
        oos_accs = [w["oos_accuracy"] for w in windows]
        return {
            "avg_is_accuracy": round(float(np.mean(is_accs)), 4),
            "avg_oos_accuracy": round(float(np.mean(oos_accs)), 4),
            "accuracy_decay": round(float(np.mean(is_accs) - np.mean(oos_accs)), 4),
            "model_useful": float(np.mean(oos_accs)) > 0.52,
        }


# ================================================================
#  预测 (实盘使用)
# ================================================================

def predict_scores(candidates: list[dict],
                   strategy: str = None) -> list[dict]:
    """对候选股生成 ML 预测得分

    Args:
        candidates: [{factor_scores: {rsi, vol_ratio, ...}, code, ...}]
        strategy: 策略名

    Returns:
        candidates 列表, 每项新增 ml_score 字段
    """
    model_name = strategy or "all"
    model_path = os.path.join(_MODEL_DIR, f"ml_{model_name}.pkl")

    if not os.path.exists(model_path):
        # 没有模型, 返回原始数据
        for c in candidates:
            c["ml_score"] = 0
        return candidates

    with open(model_path, "rb") as f:
        saved = pickle.load(f)

    model = saved["model"]
    feature_cols = saved["features"]
    task = saved.get("task", "regression")

    for c in candidates:
        fs = c.get("factor_scores", {})
        # 构建特征向量
        features = []
        for col in feature_cols:
            val = fs.get(col, c.get(col, 0))
            if isinstance(val, bool):
                val = float(val)
            features.append(float(val) if val is not None else 0.0)

        x = np.array([features])

        try:
            if task == "classification":
                proba = model.predict_proba(x)[0]
                c["ml_score"] = round(float(proba[1]) if len(proba) > 1 else 0.5, 4)
            else:
                pred = model.predict(x)[0]
                c["ml_score"] = round(float(pred), 4)
        except Exception:
            c["ml_score"] = 0

    return candidates


def fuse_scores(candidates: list[dict],
                ml_weight: float = None) -> list[dict]:
    """融合 ML 分数和规则分数

    最终分数 = ml_weight * ml_score + (1 - ml_weight) * rule_score

    Args:
        candidates: predict_scores() 的输出
        ml_weight: ML 权重 (0-1)

    Returns:
        candidates, 每项新增 fused_score 字段
    """
    if ml_weight is None:
        ml_weight = ML_PARAMS.get("ml_weight", 0.4)

    for c in candidates:
        ml_s = c.get("ml_score", 0)
        rule_s = c.get("total_score", c.get("score", 0))

        # 归一化 ML 分数到 [0, 1] 区间 (如果是回归预测值)
        # 简单映射: 预测收益 > 0 → 正分
        if ML_PARAMS.get("task") == "regression":
            ml_normalized = max(0, min(1, (ml_s + 5) / 10))  # [-5, 5] → [0, 1]
        else:
            ml_normalized = ml_s  # 分类概率已经是 [0, 1]

        c["fused_score"] = round(
            ml_weight * ml_normalized + (1 - ml_weight) * rule_s, 4)

    return candidates


# ================================================================
#  报告
# ================================================================

def generate_ml_report(eval_result: dict = None) -> str:
    """生成 ML 模型评估报告"""
    if eval_result is None:
        eval_result = evaluate_walk_forward()

    summary = eval_result.get("summary", {})
    windows = eval_result.get("windows", [])
    task = eval_result.get("task", "regression")

    lines = [
        f"## ML 因子模型评估",
        f"策略: {eval_result.get('strategy', '?')}",
        f"时间: {eval_result.get('timestamp', '?')[:19]}",
        f"任务: {task} | 窗口: {eval_result.get('n_windows', 0)}",
        "",
    ]

    if summary.get("error"):
        lines.append(f"**错误:** {summary['error']}")
        return "\n".join(lines)

    useful = summary.get("model_useful", False)
    lines.append(f"### 模型{'有效 ✅' if useful else '无效 ❌'}")
    lines.append("")

    if task == "regression":
        lines.append("| 指标 | IS | OOS | 衰减 |")
        lines.append("|------|-----|-----|------|")
        lines.append(
            f"| R² | {summary.get('avg_is_r2', 0):.4f}"
            f" | {summary.get('avg_oos_r2', 0):.4f}"
            f" | {summary.get('r2_decay', 0):+.4f} |"
        )
        lines.append(
            f"| 方向准确率 | {summary.get('avg_is_direction_acc', 0):.1%}"
            f" | {summary.get('avg_oos_direction_acc', 0):.1%}"
            f" | - |"
        )
    else:
        lines.append(
            f"- IS准确率: {summary.get('avg_is_accuracy', 0):.1%}"
        )
        lines.append(
            f"- OOS准确率: {summary.get('avg_oos_accuracy', 0):.1%}"
        )
        lines.append(
            f"- 衰减: {summary.get('accuracy_decay', 0):+.1%}"
        )

    if windows:
        lines.append("")
        lines.append("### 窗口明细")
        if task == "regression":
            lines.append("| # | 训练 | 测试 | IS R² | OOS R² | IS方向 | OOS方向 |")
            lines.append("|---|------|------|-------|--------|--------|---------|")
            for w in windows:
                lines.append(
                    f"| {w['window']} | {w['train_samples']} | {w['test_samples']}"
                    f" | {w.get('is_r2', 0):.4f} | {w.get('oos_r2', 0):.4f}"
                    f" | {w.get('is_direction_acc', 0):.1%}"
                    f" | {w.get('oos_direction_acc', 0):.1%} |"
                )

    return "\n".join(lines)


# ================================================================
#  持久化
# ================================================================

def _save_ml_results(result: dict):
    history = safe_load(_ML_RESULTS_PATH, default=[])
    if not isinstance(history, list):
        history = []
    history.append(result)
    if len(history) > 30:
        history = history[-30:]
    safe_save(_ML_RESULTS_PATH, history)


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "train"

    if mode == "train":
        result = train_model()
        if "error" in result:
            print(f"训练失败: {result['error']}")
        else:
            print(f"训练完成: {result['training_samples']} 条")
            print(f"特征: {result['features']}")
            print(f"指标: {result['metrics']}")
            print(f"\n特征重要性:")
            for f, imp in sorted(result.get("feature_importance", {}).items(),
                                  key=lambda x: x[1], reverse=True):
                bar = "█" * int(imp * 50)
                print(f"  {f:>20}: {imp:.4f} {bar}")

    elif mode == "evaluate":
        result = evaluate_walk_forward()
        print(generate_ml_report(result))

    elif mode == "report":
        history = safe_load(_ML_RESULTS_PATH, default=[])
        if history:
            print(generate_ml_report(history[-1]))
        else:
            print("暂无评估结果, 请先运行 evaluate")

    else:
        print("用法:")
        print("  python3 ml_factor_model.py train      # 训练模型")
        print("  python3 ml_factor_model.py evaluate    # Walk-Forward 评估")
        print("  python3 ml_factor_model.py report      # 查看报告")
        sys.exit(1)
