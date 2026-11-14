# -*- coding: utf-8 -*-
"""Regression tests for A-share volume unit (lots vs shares) normalization.

Eastmoney daily K-lines report volume in lots (手, 100 shares) while realtime
quotes and the project's daily contract use shares. Mixing them inflated the
"volume vs yesterday" ratio 100x (0.62x shrink reported as 61.7x expansion).
"""

import unittest

import pandas as pd

from data_provider.base import normalize_daily_volume_to_shares
from data_provider.efinance_fetcher import EfinanceFetcher
from data_provider.realtime_types import (
    compute_volume_change_ratio,
    infer_lot_volume_multiplier,
)


class InferLotVolumeMultiplierTestCase(unittest.TestCase):
    def test_lots_detected_from_amount(self):
        # 300170 on 2026-11-13: 438,765 lots, 6.28e8 CNY, close 14.04
        self.assertEqual(infer_lot_volume_multiplier(438765, 627692400, 14.04), 100)

    def test_shares_kept(self):
        self.assertEqual(infer_lot_volume_multiplier(43876500, 627692400, 14.04), 1)

    def test_star_market_shares_kept(self):
        # 688691 realtime volume is already in shares
        self.assertEqual(infer_lot_volume_multiplier(10931723, 1327404280, 122.70), 1)

    def test_missing_inputs_undecidable(self):
        self.assertIsNone(infer_lot_volume_multiplier(438765, None, 14.04))
        self.assertIsNone(infer_lot_volume_multiplier(438765, 627692400, 0))
        self.assertIsNone(infer_lot_volume_multiplier(0, 627692400, 14.04))


class ComputeVolumeChangeRatioTestCase(unittest.TestCase):
    def test_realtime_shares_vs_cached_lots(self):
        # Exact failure from the 2026-11-14 report: realtime shares / daily lots
        ratio = compute_volume_change_ratio(
            43876500, 627692400, 14.04,
            711114, 1070713000, 14.47,
        )
        self.assertEqual(ratio, 0.62)

    def test_same_unit_unchanged(self):
        ratio = compute_volume_change_ratio(2000000, None, 15.7, 1000000, None, 14.5)
        self.assertEqual(ratio, 2.0)

    def test_invalid_previous_volume(self):
        self.assertIsNone(compute_volume_change_ratio(100, None, None, 0, None, None))
        self.assertIsNone(compute_volume_change_ratio(100, None, None, None, None, None))


class NormalizeDailyVolumeTestCase(unittest.TestCase):
    def _frame(self, volumes, amounts, closes):
        return pd.DataFrame({
            'date': [f'2026-11-{10 + i}' for i in range(len(volumes))],
            'close': closes,
            'volume': volumes,
            'amount': amounts,
        })

    def test_lots_converted_to_shares(self):
        df = self._frame([711114, 438765], [1070713000, 627692400], [14.47, 14.04])
        out = normalize_daily_volume_to_shares(df, '300170')
        self.assertEqual(out['volume'].tolist(), [71111400, 43876500])

    def test_shares_left_untouched(self):
        df = self._frame([71111400, 43876500], [1070713000, 627692400], [14.47, 14.04])
        out = normalize_daily_volume_to_shares(df, '300170')
        self.assertIs(out, df)

    def test_undecidable_rows_follow_majority(self):
        df = self._frame([711114, 438765], [1070713000, None], [14.47, 14.04])
        out = normalize_daily_volume_to_shares(df, '300170')
        self.assertEqual(out['volume'].tolist(), [71111400, 43876500])

    def test_default_multiplier_when_nothing_decidable(self):
        df = self._frame([711114], [None], [14.47])
        self.assertEqual(
            normalize_daily_volume_to_shares(df, '300170', default_multiplier=100)['volume'].tolist(),
            [71111400],
        )
        self.assertEqual(
            normalize_daily_volume_to_shares(df, '300170')['volume'].tolist(),
            [711114],
        )

    def test_registered_index_skipped(self):
        # Index prices are points, so amount / close cannot infer shares
        df = self._frame([300000000], [450000000000], [3634.35])
        out = normalize_daily_volume_to_shares(df, 'sh000001')
        self.assertIs(out, df)


class EfinanceNormalizeVolumeTestCase(unittest.TestCase):
    def test_efinance_daily_volume_in_shares(self):
        raw = pd.DataFrame({
            '股票名称': ['汉得信息', '汉得信息'],
            '股票代码': ['300170', '300170'],
            '日期': ['2026-11-12', '2026-11-13'],
            '开盘': [15.25, 14.43],
            '收盘': [14.47, 14.04],
            '最高': [15.51, 14.67],
            '最低': [14.46, 14.00],
            '成交量': [711114, 438765],
            '成交额': [1070713000.0, 627692400.0],
            '涨跌幅': [-2.49, -2.97],
        })
        out = EfinanceFetcher.__new__(EfinanceFetcher)._normalize_data(raw, '300170')
        self.assertEqual(out['volume'].tolist(), [71111400, 43876500])


if __name__ == '__main__':
    unittest.main()
