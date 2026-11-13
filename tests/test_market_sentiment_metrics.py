# -*- coding: utf-8 -*-
"""Golden-fixture regression tests for market sentiment metrics (issue #1939 Wave 3).

Every expectation below was hand-computed from the plan §2 metric definitions
plus the Wave 1 probe conclusions (akshare 1.18.97 field layout):
- limit-up pool kept full-universe (ST/BSE/new stocks NOT removed; breakdown
  counts st_count/bse_count/new_stock_count attached);
- M12 close-based via previous_em '涨跌幅'; M13 auction block omitted with
  missing_reason='field_unavailable';
- zero denominators -> null + 'zero_denominator' (M2 ratio, M7 rate, M10 per
  board, M11 overall); empty pool -> null + 'empty_pool' (M8);
- never silently zero-filled.
"""

import unittest

import pandas as pd

from src.core.market_sentiment_metrics import (
    EMPTY_POOL,
    FIELD_UNAVAILABLE,
    MISSING_PREV,
    SOURCE_ERROR,
    ZERO_DENOMINATOR,
    compute_breadth,
    compute_broken_pool,
    compute_limit_up_section,
    compute_prev_feedback,
    compute_promotion,
    compute_sector_strength,
    compute_turnover,
    derive_metric_status,
)

TRADE_DATE = "2026-11-13"
PREV_TRADE_DATE = "2026-11-12"

ZT_POOL_COLUMNS = [
    "序号", "代码", "名称", "涨跌幅", "最新价", "成交额", "流通市值", "总市值",
    "换手率", "封板资金", "首次封板时间", "最后封板时间", "炸板次数", "涨停统计",
    "连板数", "所属行业",
]


def _zt_row(seq, code, name, boards, change_pct=9.99, seal_time="092500"):
    """One stock_zt_pool_em-shaped row (fields per probe1 column list)."""
    return {
        "序号": seq,
        "代码": code,
        "名称": name,
        "涨跌幅": change_pct,
        "最新价": 10.0,
        "成交额": 100000000,
        "流通市值": 2e9,
        "总市值": 2e9,
        "换手率": 5.0,
        "封板资金": 10000000,
        "首次封板时间": seal_time,
        "最后封板时间": seal_time,
        "炸板次数": 0,
        "涨停统计": "1/1",
        "连板数": boards,
        "所属行业": "化学制品",
    }


def _today_pool_df():
    """9 rows: boards 2,2,1,4,3(ST),1(BSE),2(N-new),1,5.

    Hand-computed expectations:
    count=9; max_boards=5; ladder={"2":3,"3":1,"4":1,"5":1};
    st_count=1; bse_count=1; new_stock_count=1.
    """
    rows = [
        _zt_row(1, "000001", "普通甲", 2),
        _zt_row(2, "000002", "普通乙", 2),
        _zt_row(3, "600003", "普通丙", 1),
        _zt_row(4, "600004", "高标丁", 4),
        _zt_row(5, "000005", "ST冠戊", 3),
        _zt_row(6, "830006", "北交己", 1),
        _zt_row(7, "000007", "N新庚", 2),
        _zt_row(8, "000008", "普通辛", 1),
        _zt_row(9, "600009", "五板壬", 5),
    ]
    return pd.DataFrame(rows, columns=ZT_POOL_COLUMNS)


def _prev_pool_df():
    """6 rows with yesterday board counts [1,1,1,1,2,3].

    Hand-computed promotion expectations:
    N=2: 3/4=0.75; N=3: 1/1=1.0; N=4: 1/1=1.0; N=5: 1/0 -> null+zero_denominator;
    overall: 6/6=1.0 (today boards>=2 count = 3+1+1+1 = 6).
    """
    rows = [
        _zt_row(1, "000101", "昨一", 1),
        _zt_row(2, "000102", "昨二", 1),
        _zt_row(3, "600103", "昨三", 1),
        _zt_row(4, "600104", "昨四", 1),
        _zt_row(5, "000105", "昨五", 2),
        _zt_row(6, "000106", "昨六", 3),
    ]
    return pd.DataFrame(rows, columns=ZT_POOL_COLUMNS)


def _broken_pool_df():
    """3 broken rows -> failed_count=3."""
    rows = [
        _zt_row(1, "000201", "炸一", 0, change_pct=4.02),
        _zt_row(2, "000202", "炸二", 0, change_pct=-1.5),
        _zt_row(3, "000203", "炸三", 0, change_pct=2.0),
    ]
    df = pd.DataFrame(rows, columns=ZT_POOL_COLUMNS)
    return df.drop(columns=["连板数", "最后封板时间"])  # zbgc pool has no 连板数


def _limit_down_pool_df():
    """2 rows -> limit_down_count=2 (pool calibre)."""
    rows = [
        {
            "序号": 1, "代码": "600301", "名称": "跌一", "涨跌幅": -10.01,
            "最新价": 13.84, "成交额": 871693728, "流通市值": 4.7e9,
            "总市值": 4.7e9, "动态市盈率": -30.53, "换手率": 17.65,
            "封单资金": 18116, "最后封板时间": "150000", "板上成交额": 117167931,
            "连续跌停": 1, "开板次数": 6, "所属行业": "通用设备",
        },
        {
            "序号": 2, "代码": "000302", "名称": "跌二", "涨跌幅": -10.0,
            "最新价": 5.0, "成交额": 100000000, "流通市值": 3e9,
            "总市值": 3e9, "动态市盈率": 20.0, "换手率": 3.0,
            "封单资金": 5000, "最后封板时间": "145500", "板上成交额": 10000000,
            "连续跌停": 2, "开板次数": 1, "所属行业": "房地产开",
        },
    ]
    return pd.DataFrame(rows)


def _previous_pool_df():
    """7 rows of previous_em '涨跌幅': [1.5, -9.8851, 0.0, 2.5, -3.0, 4.0, 10.0].

    Hand-computed M12: avg=5.1149/7=0.7307; median=1.5;
    red_ratio=4/7≈0.571429 (1.5/2.5/4.0/10.0 > 0); sample_size=7.
    """
    change_pcts = [1.5, -9.8851, 0.0, 2.5, -3.0, 4.0, 10.0]
    rows = []
    for i, pct in enumerate(change_pcts, start=1):
        rows.append({
            "序号": i, "代码": f"00040{i:02d}", "名称": f"昨涨{i}", "涨跌幅": pct,
            "最新价": 10.0, "涨停价": 10.5, "成交额": 3e8, "流通市值": 2.4e9,
            "总市值": 2.5e9, "换手率": 14.49, "涨速": 0.0, "振幅": 17.24,
            "昨日封板时间": "092500", "昨日连板数": 1, "涨停统计": "2/1",
            "所属行业": "房地产开",
        })
    return pd.DataFrame(rows)


def _spot_stats():
    """Sina spot sample from probe4c: up/down/flat = 765/4747/58 (sum 5570)."""
    return {
        "up_count": 765,
        "down_count": 4747,
        "flat_count": 58,
        "limit_up_count": 61,
        "limit_down_count": 9,
        "total_amount": 16668.97,
    }


TOP_SECTORS = [
    {"name": "半导体", "change_pct": 4.2},
    {"name": "电子元件", "change_pct": 3.8},
    {"name": "通信设备", "change_pct": 3.1},
    {"name": "光伏设备", "change_pct": 2.6},
    {"name": "汽车零部", "change_pct": 2.2},
]
BOTTOM_SECTORS = [
    {"name": "房地产", "change_pct": -2.1},
    {"name": "旅游零售", "change_pct": -1.8},
    {"name": "贵金属", "change_pct": -1.5},
    {"name": "白酒", "change_pct": -1.2},
    {"name": "银行", "change_pct": -0.9},
]


class ComputeBreadthTests(unittest.TestCase):
    def test_golden_stats(self):
        section = compute_breadth(_spot_stats())
        self.assertEqual(section["up_count"], 765)
        self.assertEqual(section["down_count"], 4747)
        self.assertEqual(section["flat_count"], 58)
        self.assertEqual(section["sample_size"], 5570)  # 765+4747+58
        self.assertEqual(section["advance_decline_diff"], -3982)  # 765-4747
        self.assertAlmostEqual(section["advance_decline_ratio"], 765 / 4747, places=9)
        self.assertIsNone(section["advance_decline_ratio_missing_reason"])
        # price-rule calibre recorded for cross-check (not the pool calibre)
        self.assertEqual(section["limit_up_count_by_price"], 61)
        self.assertEqual(section["limit_down_count_by_price"], 9)
        self.assertIsNone(section["missing_reason"])

    def test_zero_denominator_down_zero(self):
        stats = _spot_stats()
        stats.update(up_count=100, down_count=0, flat_count=5)
        section = compute_breadth(stats)
        self.assertEqual(section["advance_decline_diff"], 100)
        self.assertIsNone(section["advance_decline_ratio"])
        self.assertEqual(section["advance_decline_ratio_missing_reason"], ZERO_DENOMINATOR)
        self.assertIsNone(section["missing_reason"])

    def test_none_stats_marks_source_error(self):
        section = compute_breadth(None)
        for key in ("up_count", "down_count", "flat_count", "sample_size",
                    "advance_decline_diff", "advance_decline_ratio",
                    "limit_up_count_by_price", "limit_down_count_by_price"):
            self.assertIsNone(section[key], key)
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class ComputeLimitUpSectionTests(unittest.TestCase):
    def test_golden_pool(self):
        section = compute_limit_up_section(
            _today_pool_df(), _limit_down_pool_df(), _spot_stats())
        self.assertEqual(section["count"], 9)
        self.assertEqual(section["pool_sample_size"], 9)
        self.assertEqual(section["max_boards"], 5)
        self.assertIsNone(section["max_boards_missing_reason"])
        self.assertEqual(section["ladder"], {"2": 3, "3": 1, "4": 1, "5": 1})
        self.assertEqual(section["limit_down_count"], 2)
        self.assertEqual(section["limit_down_source"], "pool")
        self.assertIsNone(section["limit_down_missing_reason"])
        # W1 full-universe calibre: keep all, attach breakdown
        self.assertEqual(section["st_count"], 1)
        self.assertEqual(section["bse_count"], 1)
        self.assertEqual(section["new_stock_count"], 1)
        self.assertIsNone(section["missing_reason"])

    def test_limit_down_pool_missing_falls_back_to_price_rule(self):
        section = compute_limit_up_section(_today_pool_df(), None, _spot_stats())
        self.assertEqual(section["limit_down_count"], 9)  # price-rule cross-check value
        self.assertEqual(section["limit_down_source"], "price_rule")
        self.assertIsNone(section["limit_down_missing_reason"])

    def test_limit_down_both_calibres_missing(self):
        section = compute_limit_up_section(_today_pool_df(), None, None)
        self.assertIsNone(section["limit_down_count"])
        self.assertIsNone(section["limit_down_source"])
        self.assertEqual(section["limit_down_missing_reason"], SOURCE_ERROR)

    def test_empty_pool_today(self):
        empty = pd.DataFrame(columns=ZT_POOL_COLUMNS)
        section = compute_limit_up_section(empty, _limit_down_pool_df(), _spot_stats())
        self.assertEqual(section["count"], 0)
        self.assertEqual(section["pool_sample_size"], 0)
        self.assertIsNone(section["max_boards"])
        self.assertEqual(section["max_boards_missing_reason"], EMPTY_POOL)
        self.assertEqual(section["ladder"], {})
        self.assertEqual(section["st_count"], 0)
        self.assertEqual(section["bse_count"], 0)
        self.assertEqual(section["new_stock_count"], 0)
        self.assertIsNone(section["missing_reason"])

    def test_today_pool_none_marks_source_error(self):
        section = compute_limit_up_section(None, _limit_down_pool_df(), _spot_stats())
        self.assertIsNone(section["count"])
        self.assertIsNone(section["max_boards"])
        self.assertEqual(section["ladder"], {})
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)

    def test_empty_limit_down_pool_is_zero_not_missing(self):
        empty = pd.DataFrame(columns=["序号", "代码", "名称"])
        section = compute_limit_up_section(_today_pool_df(), empty, _spot_stats())
        self.assertEqual(section["limit_down_count"], 0)
        self.assertEqual(section["limit_down_source"], "pool")


class ComputeBrokenPoolTests(unittest.TestCase):
    def test_golden_rate(self):
        section = compute_broken_pool(_broken_pool_df(), today_limit_up_count=9)
        self.assertEqual(section["failed_count"], 3)
        self.assertEqual(section["denominator"], 12)  # 9 sealed + 3 broken
        self.assertAlmostEqual(section["failure_rate"], 3 / 12, places=9)
        self.assertIsNone(section["missing_reason"])

    def test_zero_denominator_when_no_seal_no_broken(self):
        empty = pd.DataFrame(columns=["代码", "名称", "涨跌幅"])
        section = compute_broken_pool(empty, today_limit_up_count=0)
        self.assertEqual(section["failed_count"], 0)
        self.assertEqual(section["denominator"], 0)
        self.assertIsNone(section["failure_rate"])
        self.assertEqual(section["missing_reason"], ZERO_DENOMINATOR)

    def test_broken_pool_none_marks_source_error(self):
        section = compute_broken_pool(None, today_limit_up_count=9)
        self.assertIsNone(section["failed_count"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)

    def test_today_count_none_marks_source_error(self):
        section = compute_broken_pool(_broken_pool_df(), today_limit_up_count=None)
        self.assertEqual(section["failed_count"], 3)
        self.assertIsNone(section["denominator"])
        self.assertIsNone(section["failure_rate"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class ComputePromotionTests(unittest.TestCase):
    def test_golden_by_board_and_overall(self):
        section = compute_promotion(
            _today_pool_df(), _prev_pool_df(), prev_pool_date=PREV_TRADE_DATE)
        by_board = section["by_board"]
        self.assertEqual(sorted(by_board.keys()), ["2", "3", "4", "5"])
        self.assertAlmostEqual(by_board["2"]["rate"], 0.75, places=9)
        self.assertEqual(by_board["2"]["numerator"], 3)
        self.assertEqual(by_board["2"]["denominator"], 4)
        self.assertIsNone(by_board["2"]["missing_reason"])
        self.assertAlmostEqual(by_board["3"]["rate"], 1.0, places=9)
        self.assertEqual(by_board["3"]["numerator"], 1)
        self.assertEqual(by_board["3"]["denominator"], 1)
        self.assertAlmostEqual(by_board["4"]["rate"], 1.0, places=9)
        self.assertEqual(by_board["4"]["numerator"], 1)
        self.assertEqual(by_board["4"]["denominator"], 1)
        # N=5: yesterday 4-board count = 0 -> null + zero_denominator
        self.assertIsNone(by_board["5"]["rate"])
        self.assertEqual(by_board["5"]["numerator"], 1)
        self.assertEqual(by_board["5"]["denominator"], 0)
        self.assertEqual(by_board["5"]["missing_reason"], ZERO_DENOMINATOR)
        # overall: today boards>=2 = 6, yesterday pool rows = 6
        overall = section["overall"]
        self.assertAlmostEqual(overall["rate"], 1.0, places=9)
        self.assertEqual(overall["numerator"], 6)
        self.assertEqual(overall["denominator"], 6)
        self.assertIsNone(overall["missing_reason"])
        self.assertEqual(section["prev_pool_date"], PREV_TRADE_DATE)
        self.assertIsNone(section["missing_reason"])

    def test_prev_pool_empty_overall_zero_denominator(self):
        empty = pd.DataFrame(columns=ZT_POOL_COLUMNS)
        section = compute_promotion(
            _today_pool_df(), empty, prev_pool_date=PREV_TRADE_DATE)
        self.assertEqual(section["overall"]["numerator"], 6)
        self.assertEqual(section["overall"]["denominator"], 0)
        self.assertIsNone(section["overall"]["rate"])
        self.assertEqual(section["overall"]["missing_reason"], ZERO_DENOMINATOR)
        for board in ("2", "3", "4", "5"):
            self.assertEqual(section["by_board"][board]["missing_reason"], ZERO_DENOMINATOR)

    def test_prev_pool_none_marks_source_error(self):
        section = compute_promotion(_today_pool_df(), None, prev_pool_date=None)
        self.assertEqual(section["by_board"], {})
        self.assertIsNone(section["overall"]["rate"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)
        self.assertIsNone(section["prev_pool_date"])

    def test_today_pool_none_marks_source_error(self):
        section = compute_promotion(None, _prev_pool_df(), prev_pool_date=PREV_TRADE_DATE)
        self.assertEqual(section["by_board"], {})
        self.assertIsNone(section["overall"]["rate"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class ComputeTurnoverTests(unittest.TestCase):
    def test_golden_mom(self):
        section = compute_turnover(_spot_stats(), prev_total_amount_yi=15000.0)
        self.assertAlmostEqual(section["total_amount_yi"], 16668.97, places=6)
        self.assertAlmostEqual(section["prev_total_amount_yi"], 15000.0, places=6)
        # (16668.97/15000 - 1) * 100 = 11.1264666...%
        self.assertAlmostEqual(section["mom_change_pct"], (16668.97 / 15000 - 1) * 100, places=9)
        self.assertIsNone(section["mom_missing_reason"])
        self.assertEqual(section["prev_source"], "snapshot_table")
        self.assertIsNone(section["missing_reason"])

    def test_missing_prev_cold_start(self):
        section = compute_turnover(_spot_stats(), prev_total_amount_yi=None)
        self.assertAlmostEqual(section["total_amount_yi"], 16668.97, places=6)
        self.assertIsNone(section["prev_total_amount_yi"])
        self.assertIsNone(section["mom_change_pct"])
        self.assertEqual(section["mom_missing_reason"], MISSING_PREV)
        self.assertIsNone(section["prev_source"])
        # cold start is expected, not a source failure
        self.assertIsNone(section["missing_reason"])

    def test_zero_prev_zero_denominator(self):
        section = compute_turnover(_spot_stats(), prev_total_amount_yi=0.0)
        self.assertIsNone(section["mom_change_pct"])
        self.assertEqual(section["mom_missing_reason"], ZERO_DENOMINATOR)

    def test_stats_none_marks_source_error(self):
        section = compute_turnover(None, prev_total_amount_yi=15000.0)
        self.assertIsNone(section["total_amount_yi"])
        self.assertIsNone(section["mom_change_pct"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class ComputePrevFeedbackTests(unittest.TestCase):
    def test_golden_close_based_feedback(self):
        section = compute_prev_feedback(_previous_pool_df())
        self.assertEqual(section["sample_size"], 7)
        self.assertAlmostEqual(section["avg_change_pct"], 5.1149 / 7, places=9)
        self.assertEqual(section["median_change_pct"], 1.5)
        self.assertAlmostEqual(section["red_ratio"], 4 / 7, places=9)
        self.assertIsNone(section["stats_missing_reason"])
        # W1 verdict: previous_em has no auction fields -> block omitted
        self.assertIsNone(section["auction"])
        self.assertEqual(section["auction_missing_reason"], FIELD_UNAVAILABLE)
        self.assertIsNone(section["missing_reason"])

    def test_empty_previous_pool(self):
        empty = pd.DataFrame(columns=["代码", "名称", "涨跌幅"])
        section = compute_prev_feedback(empty)
        self.assertEqual(section["sample_size"], 0)
        self.assertIsNone(section["avg_change_pct"])
        self.assertIsNone(section["median_change_pct"])
        self.assertIsNone(section["red_ratio"])
        self.assertEqual(section["stats_missing_reason"], EMPTY_POOL)
        self.assertEqual(section["auction_missing_reason"], FIELD_UNAVAILABLE)

    def test_none_marks_source_error(self):
        section = compute_prev_feedback(None)
        self.assertEqual(section["sample_size"], 0)
        self.assertIsNone(section["avg_change_pct"])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class ComputeSectorStrengthTests(unittest.TestCase):
    def test_golden_top_bottom(self):
        section = compute_sector_strength((TOP_SECTORS, BOTTOM_SECTORS))
        self.assertEqual(len(section["top5"]), 5)
        self.assertEqual(len(section["bottom5"]), 5)
        self.assertEqual(section["top5"][0], {"name": "半导体", "change_pct": 4.2})
        self.assertEqual(section["bottom5"][0], {"name": "房地产", "change_pct": -2.1})
        self.assertIsNone(section["missing_reason"])

    def test_none_marks_source_error(self):
        section = compute_sector_strength(None)
        self.assertEqual(section["top5"], [])
        self.assertEqual(section["bottom5"], [])
        self.assertEqual(section["missing_reason"], SOURCE_ERROR)


class DeriveMetricStatusTests(unittest.TestCase):
    def _ok_sections(self):
        today = _today_pool_df()
        return {
            "breadth": compute_breadth(_spot_stats()),
            "limit_up_pool": compute_limit_up_section(
                today, _limit_down_pool_df(), _spot_stats()),
            "broken_pool": compute_broken_pool(_broken_pool_df(), today_limit_up_count=9),
            "turnover": compute_turnover(_spot_stats(), prev_total_amount_yi=15000.0),
            "promotion": compute_promotion(today, _prev_pool_df(), PREV_TRADE_DATE),
            "prev_feedback": compute_prev_feedback(_previous_pool_df()),
            "sector": compute_sector_strength((TOP_SECTORS, BOTTOM_SECTORS)),
        }

    def test_all_ok(self):
        status = derive_metric_status(self._ok_sections())
        self.assertEqual(
            status,
            {
                "breadth": "ok",
                "limit_up_pool": "ok",
                "broken_pool": "ok",
                "turnover": "ok",
                "promotion": "ok",
                "prev_feedback": "ok",
                "sector": "ok",
            },
        )

    def test_zero_denominator_and_expected_missing_do_not_downgrade_group(self):
        sections = self._ok_sections()
        # M2 zero denominator (down=0): breadth still ok
        stats = _spot_stats()
        stats.update(down_count=0)
        sections["breadth"] = compute_breadth(stats)
        # M6 cold start (missing_prev): turnover still ok
        sections["turnover"] = compute_turnover(_spot_stats(), prev_total_amount_yi=None)
        # M10 zero-denominator board: promotion still ok
        status = derive_metric_status(sections)
        self.assertEqual(status["breadth"], "ok")
        self.assertEqual(status["turnover"], "ok")
        self.assertEqual(status["promotion"], "ok")

    def test_source_error_downgrades_only_its_group(self):
        sections = self._ok_sections()
        sections["promotion"] = compute_promotion(None, _prev_pool_df(), PREV_TRADE_DATE)
        status = derive_metric_status(sections)
        self.assertEqual(status["promotion"], "source_error")
        self.assertEqual(status["breadth"], "ok")
        self.assertEqual(status["prev_feedback"], "ok")

    def test_limit_down_both_calibres_missing_downgrades_limit_up_pool(self):
        sections = self._ok_sections()
        sections["limit_up_pool"] = compute_limit_up_section(
            _today_pool_df(), None, None)
        status = derive_metric_status(sections)
        self.assertEqual(status["limit_up_pool"], "source_error")
        self.assertEqual(status["broken_pool"], "ok")

    def test_price_rule_fallback_keeps_limit_up_pool_ok(self):
        sections = self._ok_sections()
        sections["limit_up_pool"] = compute_limit_up_section(
            _today_pool_df(), None, _spot_stats())
        status = derive_metric_status(sections)
        self.assertEqual(status["limit_up_pool"], "ok")


if __name__ == "__main__":
    unittest.main()
