"""
自动优化器 + 自愈系统 单元测试
"""

import json
import os
import sys
import tempfile
import shutil
import pytest

# 确保可以导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """创建临时目录并 patch 文件路径"""
    # 创建 logs 子目录
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    # patch auto_optimizer 路径
    monkeypatch.setattr("auto_optimizer._DIR", str(tmp_path))
    monkeypatch.setattr("auto_optimizer._TUNABLE_PATH",
                        str(tmp_path / "tunable_params.json"))
    monkeypatch.setattr("auto_optimizer._EVOLUTION_PATH",
                        str(tmp_path / "evolution_history.json"))
    monkeypatch.setattr("auto_optimizer._SCORECARD_PATH",
                        str(tmp_path / "scorecard.json"))
    monkeypatch.setattr("auto_optimizer._VERIFICATION_PATH",
                        str(tmp_path / "optimization_verifications.json"))

    # patch self_healer 路径
    monkeypatch.setattr("self_healer._DIR", str(tmp_path))
    monkeypatch.setattr("self_healer._LOG_DIR", str(logs_dir))
    monkeypatch.setattr("self_healer._ERROR_PATTERNS_PATH",
                        str(tmp_path / "error_patterns.json"))
    monkeypatch.setattr("self_healer._HEAL_HISTORY_PATH",
                        str(tmp_path / "heal_history.json"))

    return tmp_path


@pytest.fixture
def sample_scorecard(tmp_dir):
    """写入样本记分卡数据"""
    from datetime import date, timedelta

    records = []
    today = date.today()
    for i in range(20):
        d = (today - timedelta(days=i)).isoformat()
        # 交替胜负
        net_return = 1.5 if i % 3 != 0 else -1.0
        records.append({
            "rec_date": d,
            "strategy": "放量突破选股",
            "code": f"00{1000 + i}",
            "name": f"测试股{i}",
            "entry_price": 10.0,
            "net_return_pct": net_return,
            "result": "win" if net_return > 0 else "loss",
        })

    from json_store import safe_save
    safe_save(str(tmp_dir / "scorecard.json"), records)
    return records


# ================================================================
#  auto_optimizer 测试
# ================================================================

class TestEvaluateStrategyHealth:
    """evaluate_strategy_health 测试"""

    def test_empty_data(self, tmp_dir):
        """空数据返回默认值"""
        from auto_optimizer import evaluate_strategy_health
        from json_store import safe_save
        safe_save(str(tmp_dir / "scorecard.json"), [])

        result = evaluate_strategy_health("breakout")
        assert result["score"] == 50
        assert result["sample_count"] == 0
        assert result["trend"] == "insufficient_data"

    def test_normal_data(self, tmp_dir, sample_scorecard):
        """正常数据返回合理的评分"""
        from auto_optimizer import evaluate_strategy_health

        result = evaluate_strategy_health("breakout", days=30)
        assert 0 <= result["score"] <= 100
        assert result["sample_count"] > 0
        assert result["win_rate"] > 0
        assert result["trend"] in ("improving", "stable", "declining", "insufficient_data")

    def test_trend_calculation(self, tmp_dir):
        """趋势计算: 前半段差后半段好 → improving"""
        from auto_optimizer import evaluate_strategy_health
        from json_store import safe_save
        from datetime import date, timedelta

        records = []
        today = date.today()
        # 前半段亏损
        for i in range(10, 20):
            records.append({
                "rec_date": (today - timedelta(days=i)).isoformat(),
                "strategy": "放量突破选股",
                "code": f"00{1000 + i}",
                "net_return_pct": -2.0,
                "result": "loss",
            })
        # 后半段盈利
        for i in range(0, 10):
            records.append({
                "rec_date": (today - timedelta(days=i)).isoformat(),
                "strategy": "放量突破选股",
                "code": f"00{2000 + i}",
                "net_return_pct": 3.0,
                "result": "win",
            })

        safe_save(str(tmp_dir / "scorecard.json"), records)
        result = evaluate_strategy_health("breakout", days=30)
        assert result["trend"] == "improving"


class TestGenerateCandidates:
    """generate_candidates 测试"""

    def test_weight_normalization(self, tmp_dir):
        """候选权重归一化: 总和 = 1.0"""
        from auto_optimizer import generate_candidates

        weights = {
            "s_volume_breakout": 0.20,
            "s_ma_alignment": 0.15,
            "s_momentum": 0.10,
            "s_rsi": 0.08,
            "s_fundamental": 0.08,
            "s_hot": 0.07,
            "s_turnover": 0.04,
            "s_resistance_break": 0.03,
            "s_fund_flow": 0.10,
            "s_lhb": 0.08,
            "s_chip": 0.07,
        }

        candidates = generate_candidates("breakout", weights, n_candidates=5)
        assert len(candidates) > 0

        for c in candidates:
            total = sum(c["weights"].values())
            assert abs(total - 1.0) < 0.02, f"权重总和 {total} != 1.0"

    def test_weight_delta_limit(self, tmp_dir):
        """单次调整幅度不超过 max_weight_delta"""
        from auto_optimizer import generate_candidates
        from config import OPTIMIZATION_PARAMS

        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        max_delta = OPTIMIZATION_PARAMS["max_weight_delta"]

        candidates = generate_candidates("breakout", weights, n_candidates=10)
        for c in candidates:
            for key in weights:
                # 归一化后幅度可能略大, 留一定余量
                delta = abs(c["weights"][key] - weights[key])
                assert delta < max_delta + 0.05, \
                    f"权重 {key} 变化 {delta} 超过限制 {max_delta}"

    def test_positive_weights(self, tmp_dir):
        """所有权重 > 0"""
        from auto_optimizer import generate_candidates

        weights = {"a": 0.5, "b": 0.3, "c": 0.2}
        candidates = generate_candidates("breakout", weights, n_candidates=10)
        for c in candidates:
            for v in c["weights"].values():
                assert v > 0, f"权重不应 <= 0: {v}"


class TestGetTunableParams:
    """get_tunable_params 测试"""

    def test_default_weights(self, tmp_dir):
        """无覆盖文件时返回 config 默认值"""
        from auto_optimizer import get_tunable_params
        from config import BREAKOUT_PARAMS

        result = get_tunable_params("breakout")
        assert "weights" in result
        assert result["weights"] == BREAKOUT_PARAMS["weights"]

    def test_override_weights(self, tmp_dir):
        """有覆盖文件时返回覆盖值"""
        from auto_optimizer import get_tunable_params
        from json_store import safe_save

        override_weights = {"s_volume_breakout": 0.30, "s_ma_alignment": 0.70}
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {
                "weights": override_weights,
                "version": 1,
            }
        })

        result = get_tunable_params("breakout")
        assert result["weights"] == override_weights


class TestApplyAndRollback:
    """apply_optimization 和 rollback 测试"""

    def test_apply_creates_history(self, tmp_dir):
        """采纳新参数会创建演化历史"""
        from auto_optimizer import apply_optimization
        from json_store import safe_load

        apply_optimization("breakout", {"a": 0.5, "b": 0.5}, "test")

        history = safe_load(str(tmp_dir / "evolution_history.json"))
        assert len(history) == 1
        assert history[0]["action"] == "adopt"
        assert history[0]["strategy"] == "breakout"

        tunable = safe_load(str(tmp_dir / "tunable_params.json"), default={})
        assert tunable["breakout"]["version"] == 1

    def test_rollback(self, tmp_dir):
        """回滚恢复前一版本参数"""
        from auto_optimizer import apply_optimization, rollback_strategy
        from json_store import safe_load

        old_w = {"a": 0.4, "b": 0.6}
        new_w = {"a": 0.5, "b": 0.5}

        apply_optimization("breakout", old_w, "first")
        apply_optimization("breakout", new_w, "second")
        rollback_strategy("breakout", "test rollback")

        tunable = safe_load(str(tmp_dir / "tunable_params.json"), default={})
        assert tunable["breakout"]["weights"] == old_w


# ================================================================
#  self_healer 测试
# ================================================================

class TestMatchErrorPattern:
    """match_error_pattern 测试"""

    def test_json_decode_error(self, tmp_dir):
        """JSONDecodeError 匹配"""
        from self_healer import match_error_pattern
        result = match_error_pattern("json.decoder.JSONDecodeError: Expecting value")
        assert result is not None
        assert result["action"] == "repair_json"

    def test_timeout_error(self, tmp_dir):
        """TimeoutError 匹配"""
        from self_healer import match_error_pattern
        result = match_error_pattern("requests.exceptions.ReadTimeout: timed out")
        assert result is not None
        assert result["action"] == "clear_cache"

    def test_connection_error(self, tmp_dir):
        """ConnectionError 匹配"""
        from self_healer import match_error_pattern
        result = match_error_pattern("ConnectionError: Failed to connect")
        assert result is not None
        assert result["action"] == "log_connection"

    def test_disk_space(self, tmp_dir):
        """磁盘空间不足匹配"""
        from self_healer import match_error_pattern
        result = match_error_pattern("OSError: No space left on device")
        assert result is not None
        assert result["action"] == "clean_logs"

    def test_unknown_error(self, tmp_dir):
        """未知错误返回 None"""
        from self_healer import match_error_pattern
        result = match_error_pattern("SomeRandomError: unknown issue")
        assert result is None


class TestRepairJson:
    """repair_json 测试"""

    def test_repair_from_bak(self, tmp_dir):
        """从 .bak 文件恢复"""
        from self_healer import repair_json

        filepath = str(tmp_dir / "test.json")
        bak_path = filepath + ".bak"

        # 写入坏的 json 和好的 bak
        with open(filepath, "w") as f:
            f.write("{broken json")
        with open(bak_path, "w") as f:
            json.dump({"valid": True}, f)

        result = repair_json(filepath)
        assert result is True

        with open(filepath, "r") as f:
            data = json.load(f)
        assert data["valid"] is True

    def test_repair_initialize_empty(self, tmp_dir):
        """无 .bak 时初始化为空"""
        from self_healer import repair_json

        filepath = str(tmp_dir / "positions.json")
        with open(filepath, "w") as f:
            f.write("not valid json!!")

        result = repair_json(filepath)
        assert result is True

        with open(filepath, "r") as f:
            data = json.load(f)
        assert data == []


class TestSmokeTest:
    """run_smoke_test 测试"""

    def test_returns_structure(self, tmp_dir):
        """冒烟测试返回正确的结构"""
        from self_healer import run_smoke_test

        result = run_smoke_test()
        assert "passed" in result
        assert "results" in result
        assert isinstance(result["results"], list)
        for r in result["results"]:
            assert "name" in r
            assert "passed" in r


class TestCleanOldLogs:
    """clean_old_logs 测试"""

    def test_clean_old_files(self, tmp_dir):
        """清理旧日志文件"""
        from self_healer import clean_old_logs
        import time

        logs_dir = tmp_dir / "logs"
        # 创建一个"旧"日志文件
        old_log = logs_dir / "old.log"
        old_log.write_text("old log content")
        # 修改 mtime 为 60 天前
        old_time = time.time() - 60 * 86400
        os.utime(str(old_log), (old_time, old_time))

        # 创建一个新日志文件
        new_log = logs_dir / "new.log"
        new_log.write_text("new log content")

        clean_old_logs(days=30)

        assert not old_log.exists(), "旧日志应被清理"
        assert new_log.exists(), "新日志不应被清理"


# ================================================================
#  集成测试
# ================================================================

class TestIntegration:
    """基本集成测试"""

    def test_optimizer_import(self):
        """auto_optimizer 可正常导入"""
        from auto_optimizer import (
            evaluate_strategy_health,
            generate_candidates,
            get_tunable_params,
            run_daily_optimization,
        )

    def test_healer_import(self):
        """self_healer 可正常导入"""
        from self_healer import (
            run_smoke_test,
            auto_heal,
            match_error_pattern,
            repair_json,
            generate_health_report,
        )

    def test_backtest_accepts_overrides(self):
        """backtest_strategy 接受 param_overrides 参数"""
        import inspect
        from backtest import backtest_strategy, _score_candidates

        sig1 = inspect.signature(backtest_strategy)
        assert "param_overrides" in sig1.parameters

        sig2 = inspect.signature(_score_candidates)
        assert "param_overrides" in sig2.parameters


# ================================================================
#  验证闭环测试
# ================================================================

class TestScheduleVerification:
    """schedule_verification 测试"""

    def test_creates_pending_entry(self, tmp_dir):
        """采纳后创建 pending 验证条目"""
        from auto_optimizer import schedule_verification
        from json_store import safe_load, safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        schedule_verification("breakout", {"a": 0.5}, "测试")

        vlist = safe_load(str(tmp_dir / "optimization_verifications.json"))
        assert len(vlist) == 1
        assert vlist[0]["status"] == "pending"
        assert vlist[0]["strategy"] == "breakout"
        assert vlist[0]["pre_score"] == 50  # empty scorecard → default

    def test_apply_auto_schedules(self, tmp_dir):
        """apply_optimization 自动调度验证"""
        from auto_optimizer import apply_optimization
        from json_store import safe_load, safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        apply_optimization("breakout", {"a": 0.5, "b": 0.5}, "test")

        vlist = safe_load(str(tmp_dir / "optimization_verifications.json"), default=[])
        assert len(vlist) == 1
        assert vlist[0]["status"] == "pending"


class TestCheckPendingVerifications:
    """check_pending_verifications 测试"""

    def test_not_due_yet(self, tmp_dir):
        """验证期未到, 不执行"""
        from auto_optimizer import check_pending_verifications
        from json_store import safe_save
        from datetime import date

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "optimization_verifications.json"), [{
            "strategy": "breakout",
            "change_date": date.today().isoformat(),
            "pre_score": 60,
            "verify_after_days": 5,
            "status": "pending",
        }])

        results = check_pending_verifications()
        assert len(results) == 0

    def test_verified_ok(self, tmp_dir, sample_scorecard):
        """验证通过 (得分未大幅下降)"""
        from auto_optimizer import check_pending_verifications
        from json_store import safe_save, safe_load
        from datetime import date, timedelta

        # 设置 change_date 为 6 天前 (超过 5 天验证窗口)
        safe_save(str(tmp_dir / "optimization_verifications.json"), [{
            "strategy": "breakout",
            "change_date": (date.today() - timedelta(days=6)).isoformat(),
            "pre_score": 40,  # 低分 → 当前分数不太可能比这个低更多
            "verify_after_days": 5,
            "status": "pending",
        }])

        results = check_pending_verifications()
        assert len(results) == 1
        assert results[0]["verdict"] == "verified_ok"

    def test_auto_rollback(self, tmp_dir, sample_scorecard):
        """验证失败 → 自动回滚"""
        from auto_optimizer import check_pending_verifications, apply_optimization
        from json_store import safe_save, safe_load
        from datetime import date, timedelta

        # 先写入一组参数, 确保回滚有数据
        apply_optimization("breakout", {"a": 0.6, "b": 0.4}, "original")
        apply_optimization("breakout", {"a": 0.8, "b": 0.2}, "should_rollback")

        # 设置验证条目: pre_score 很高 (100), 实际得分必然低很多 → 触发回滚
        safe_save(str(tmp_dir / "optimization_verifications.json"), [{
            "strategy": "breakout",
            "change_date": (date.today() - timedelta(days=6)).isoformat(),
            "pre_score": 100,
            "verify_after_days": 5,
            "status": "pending",
        }])

        results = check_pending_verifications()
        assert len(results) == 1
        assert results[0]["verdict"] == "rolled_back"

        # 验证已回滚到前一版本
        tunable = safe_load(str(tmp_dir / "tunable_params.json"), default={})
        assert tunable["breakout"]["weights"] == {"a": 0.6, "b": 0.4}

    def test_extend_on_insufficient_data(self, tmp_dir):
        """样本不足时延长验证窗口"""
        from auto_optimizer import check_pending_verifications
        from json_store import safe_save, safe_load
        from datetime import date, timedelta

        safe_save(str(tmp_dir / "scorecard.json"), [])  # 空 → 样本不足
        safe_save(str(tmp_dir / "optimization_verifications.json"), [{
            "strategy": "breakout",
            "change_date": (date.today() - timedelta(days=6)).isoformat(),
            "pre_score": 60,
            "verify_after_days": 5,
            "status": "pending",
        }])

        results = check_pending_verifications()
        assert len(results) == 0  # 没有完成验证

        # 验证窗口已延长
        vlist = safe_load(str(tmp_dir / "optimization_verifications.json"))
        assert vlist[0]["verify_after_days"] == 8  # 5 + 3

    def test_skip_completed(self, tmp_dir):
        """跳过已完成的验证"""
        from auto_optimizer import check_pending_verifications
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "optimization_verifications.json"), [{
            "strategy": "breakout",
            "change_date": "2020-01-01",
            "pre_score": 60,
            "verify_after_days": 5,
            "status": "verified_ok",
        }])

        results = check_pending_verifications()
        assert len(results) == 0


# ================================================================
#  因子生命周期测试
# ================================================================

class TestDeweightFactor:
    """deweight_factor 测试"""

    def test_basic_deweight(self, tmp_dir):
        """降权一个因子, 其他因子等比例吸收"""
        from auto_optimizer import deweight_factor, get_tunable_params
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {
                "weights": {"a": 0.50, "b": 0.30, "c": 0.20},
                "version": 1,
            }
        })

        result = deweight_factor("breakout", "c", reason="测试降权")
        assert result is True

        params = get_tunable_params("breakout")
        # c 应被减半 (0.20 → 0.10), 然后归一化
        assert params["weights"]["c"] < 0.15
        # 其他因子应增加
        assert params["weights"]["a"] > 0.50
        # 总和为1
        total = sum(params["weights"].values())
        assert abs(total - 1.0) < 0.01

    def test_skip_already_minimal(self, tmp_dir):
        """权重已经很低 (<=0.02) 时不再降权"""
        from auto_optimizer import deweight_factor
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {
                "weights": {"a": 0.50, "b": 0.48, "c": 0.02},
                "version": 1,
            }
        })

        result = deweight_factor("breakout", "c")
        assert result is False

    def test_unknown_factor(self, tmp_dir):
        """未知因子名返回 False"""
        from auto_optimizer import deweight_factor
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {"weights": {"a": 0.5, "b": 0.5}, "version": 1}
        })

        result = deweight_factor("breakout", "nonexistent")
        assert result is False


class TestCheckFactorLifecycle:
    """check_factor_lifecycle 测试"""

    def test_no_dying_factors(self, tmp_dir):
        """所有因子健康, 不做操作"""
        from auto_optimizer import check_factor_lifecycle
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        # 所有权重都 >= 0.03
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {"weights": {"a": 0.5, "b": 0.5}, "version": 1},
            "auction": {"weights": {"a": 0.5, "b": 0.5}, "version": 1},
            "afternoon": {"weights": {"a": 0.5, "b": 0.5}, "version": 1},
        })

        results = check_factor_lifecycle()
        assert len(results) == 0

    def test_deweight_dying_factor(self, tmp_dir):
        """权重低于阈值的因子被降权"""
        from auto_optimizer import check_factor_lifecycle
        from json_store import safe_save

        safe_save(str(tmp_dir / "scorecard.json"), [])
        safe_save(str(tmp_dir / "tunable_params.json"), {
            "breakout": {
                "weights": {"a": 0.50, "b": 0.48, "c": 0.025},  # c < 0.03
                "version": 1,
            },
            "auction": {"weights": {"a": 0.5, "b": 0.5}, "version": 1},
            "afternoon": {"weights": {"a": 0.5, "b": 0.5}, "version": 1},
        })

        results = check_factor_lifecycle()
        assert len(results) == 1
        assert results[0]["strategy"] == "breakout"
        assert results[0]["factor"] == "c"
        assert results[0]["action"] == "deweighted"
