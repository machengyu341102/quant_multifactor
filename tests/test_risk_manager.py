"""
risk_manager 单元测试
=====================
测试: 风控过滤, 熔断检查, 黑名单, 仓位计算, 行业分类
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

# 确保能导入项目模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from risk_manager import (
    classify_sector,
    filter_recommendations,
    check_daily_circuit_breaker,
    get_position_sizing,
)


class TestClassifySector(unittest.TestCase):
    """行业分类测试"""

    def test_medical(self):
        self.assertEqual(classify_sector("恒瑞医药"), "医药")
        self.assertEqual(classify_sector("长春生物"), "医药")

    def test_tech(self):
        self.assertEqual(classify_sector("中芯国际"), "科技")
        self.assertEqual(classify_sector("浪潮软件"), "科技")

    def test_finance(self):
        self.assertEqual(classify_sector("平安银行"), "金融")
        self.assertEqual(classify_sector("中信证券"), "金融")

    def test_consumer(self):
        self.assertEqual(classify_sector("五粮液酒"), "消费")
        self.assertEqual(classify_sector("三只松鼠食品"), "消费")

    def test_manufacturing(self):
        self.assertEqual(classify_sector("三一重工机械"), "制造")
        self.assertEqual(classify_sector("宝钢股份"), "制造")

    def test_energy(self):
        self.assertEqual(classify_sector("中国石油"), "能源")
        self.assertEqual(classify_sector("隆基光伏"), "能源")

    def test_other(self):
        self.assertEqual(classify_sector("某某公司"), "其他")
        self.assertEqual(classify_sector(""), "其他")
        self.assertEqual(classify_sector(None), "其他")


class TestPositionSizing(unittest.TestCase):
    """仓位计算测试"""

    def test_basic_sizing(self):
        items = [
            {"code": "000001", "name": "平安银行", "price": 10.0},
            {"code": "600036", "name": "招商银行", "price": 50.0},
        ]
        result = get_position_sizing(100000, items)

        for it in result:
            self.assertIn("suggested_shares", it)
            self.assertIn("suggested_amount", it)
            # 股数应是100的整数倍
            self.assertEqual(it["suggested_shares"] % 100, 0)

    def test_single_position_cap(self):
        """单只仓位不超过 single_position_pct"""
        items = [{"code": "000001", "name": "平安银行", "price": 10.0}]
        result = get_position_sizing(100000, items)
        # 15% of 100000 = 15000
        self.assertLessEqual(result[0]["suggested_amount"], 15000 + 1000)

    def test_zero_price(self):
        items = [{"code": "000001", "name": "平安银行", "price": 0}]
        result = get_position_sizing(100000, items)
        self.assertNotIn("suggested_shares", result[0])

    def test_zero_capital(self):
        items = [{"code": "000001", "name": "平安银行", "price": 10.0}]
        result = get_position_sizing(0, items)
        self.assertEqual(result, items)

    def test_min_100_shares(self):
        """最少100股"""
        items = [{"code": "000001", "name": "某股", "price": 500.0}]
        result = get_position_sizing(1000, items)  # 资金很少
        self.assertEqual(result[0]["suggested_shares"], 100)


class TestFilterRecommendations(unittest.TestCase):
    """风控过滤测试"""

    def setUp(self):
        self.items = [
            {"code": "000001", "name": "平安银行", "price": 10.0},
            {"code": "600036", "name": "招商银行", "price": 50.0},
            {"code": "000002", "name": "万科地产", "price": 15.0},
        ]

    @patch("risk_manager.safe_load")
    def test_empty_items(self, mock_load):
        result = filter_recommendations("测试策略", [])
        self.assertEqual(result, [])

    @patch("risk_manager.safe_load")
    def test_blacklist_filter(self, mock_load):
        """黑名单过滤"""
        today = date.today().isoformat()
        future = (date.today() + timedelta(days=30)).isoformat()

        def side_effect(path, *args, **kwargs):
            if "blacklist" in path:
                return [{"code": "000001", "until": future}]
            return []  # positions empty

        mock_load.side_effect = side_effect

        result = filter_recommendations("测试策略", self.items)
        codes = [it["code"] for it in result]
        self.assertNotIn("000001", codes)
        self.assertIn("600036", codes)

    @patch("risk_manager.safe_load")
    def test_sector_concentration(self, mock_load):
        """行业集中度: 金融已有2只, 不应再加"""
        items = [
            {"code": "601398", "name": "工商银行", "price": 5.0},
        ]

        def side_effect(path, *args, **kwargs):
            if "blacklist" in path:
                return []
            # 持仓中已有2只金融
            return [
                {"code": "000001", "name": "平安银行", "status": "holding",
                 "entry_date": "2020-01-01"},
                {"code": "600036", "name": "招商银行", "status": "holding",
                 "entry_date": "2020-01-01"},
            ]

        mock_load.side_effect = side_effect

        result = filter_recommendations("测试策略", items)
        self.assertEqual(len(result), 0)

    @patch("risk_manager.safe_load")
    def test_max_positions(self, mock_load):
        """持仓上限检查"""
        def side_effect(path, *args, **kwargs):
            if "blacklist" in path:
                return []
            # 已有9只持仓 (达到上限)
            return [
                {"code": f"00000{i}", "name": f"股票{i}", "status": "holding",
                 "entry_date": "2020-01-01"}
                for i in range(9)
            ]

        mock_load.side_effect = side_effect

        result = filter_recommendations("测试策略", self.items)
        self.assertEqual(len(result), 0)


class TestCircuitBreaker(unittest.TestCase):
    """熔断检查测试"""

    @patch("risk_manager.safe_load")
    def test_no_exits_no_breaker(self, mock_load):
        mock_load.return_value = []
        self.assertFalse(check_daily_circuit_breaker())

    @patch("notifier.notify_wechat_raw")
    @patch("risk_manager.safe_load")
    def test_breaker_triggered(self, mock_load, mock_wechat):
        """平均亏损超过-5%触发熔断"""
        today = date.today().isoformat()
        mock_load.return_value = [
            {"status": "exited", "exit_date": today, "pnl_pct": -6.0},
            {"status": "exited", "exit_date": today, "pnl_pct": -7.0},
        ]
        self.assertTrue(check_daily_circuit_breaker())

    @patch("risk_manager.safe_load")
    def test_no_breaker_normal_loss(self, mock_load):
        """平均亏损未超过-5%, 不触发"""
        today = date.today().isoformat()
        mock_load.return_value = [
            {"status": "exited", "exit_date": today, "pnl_pct": -2.0},
            {"status": "exited", "exit_date": today, "pnl_pct": -1.0},
        ]
        self.assertFalse(check_daily_circuit_breaker())


class TestJsonStore(unittest.TestCase):
    """JSON 安全存储测试"""

    def test_safe_load_save(self):
        from json_store import safe_load, safe_save

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            # 文件不存在时返回默认值
            self.assertEqual(safe_load(path), [])

            # 写入并读取
            data = [{"code": "000001", "name": "测试"}]
            safe_save(path, data)
            loaded = safe_load(path)
            self.assertEqual(loaded, data)

            # dict 类型
            data_dict = {"key": "value", "count": 42}
            safe_save(path, data_dict)
            loaded = safe_load(path)
            self.assertEqual(loaded, data_dict)
        finally:
            os.unlink(path)

    def test_atomic_write(self):
        """写入中断不会损坏原文件"""
        from json_store import safe_load, safe_save

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            original = [{"code": "000001"}]
            safe_save(path, original)

            # 验证 .tmp 文件不应残留
            self.assertFalse(os.path.exists(path + ".tmp"))

            # 原文件完好
            loaded = safe_load(path)
            self.assertEqual(loaded, original)
        finally:
            os.unlink(path)


class TestEquityCurve(unittest.TestCase):
    """资金曲线测试"""

    @patch("scorecard._SCORECARD_PATH", "/tmp/_test_sc.json")
    @patch("scorecard.safe_load_strict")
    def test_empty_records(self, mock_load):
        from scorecard import calc_equity_curve
        mock_load.return_value = []
        result = calc_equity_curve()
        self.assertEqual(result["total_return"], 0)
        self.assertEqual(result["nav_series"], [])

    @patch("scorecard._SCORECARD_PATH", "/tmp/_test_sc.json")
    @patch("scorecard.safe_load_strict")
    def test_basic_curve(self, mock_load):
        from scorecard import calc_equity_curve
        mock_load.return_value = [
            {"rec_date": "2026-02-25", "net_return_pct": 2.0, "result": "win"},
            {"rec_date": "2026-02-26", "net_return_pct": -1.0, "result": "loss"},
            {"rec_date": "2026-02-27", "net_return_pct": 3.0, "result": "win"},
        ]
        result = calc_equity_curve()
        self.assertGreater(result["total_return"], 0)
        self.assertEqual(len(result["nav_series"]), 3)
        # 净值应递增 (整体上涨)
        final_nav = result["nav_series"][-1][1]
        self.assertGreater(final_nav, 1.0)

    @patch("scorecard._SCORECARD_PATH", "/tmp/_test_sc.json")
    @patch("scorecard.safe_load_strict")
    def test_max_drawdown(self, mock_load):
        from scorecard import calc_equity_curve
        mock_load.return_value = [
            {"rec_date": "2026-02-25", "net_return_pct": 5.0, "result": "win"},
            {"rec_date": "2026-02-26", "net_return_pct": -3.0, "result": "loss"},
            {"rec_date": "2026-02-27", "net_return_pct": -2.0, "result": "loss"},
        ]
        result = calc_equity_curve()
        self.assertGreater(result["max_drawdown"], 0)


if __name__ == "__main__":
    unittest.main()
