"""백테스트 자동 점검 판정(decide), 때(due), 창(auto_window) 시험."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import backtest
import backtest_data


def m(mdape, n=60, alive=True, shuffle=0.0, coverage=1.0, p80=None):
    return {'N': n, 'MdAPE': mdape, 'P80': p80 or mdape * 2, 'coverage': coverage, 'shuffle_share': shuffle, 'defect_alive': alive}


class Decide(unittest.TestCase):
    def test_new_coef_when_it_beats_current(self):
        h = {'v1': m(0.15), 'v0': m(0.06), 'v2c': m(0.05), 'v0_new': m(0.04), 'v2c_new': m(0.03)}
        verdict, adopted, new = backtest.decide(h, {'a': 0})
        self.assertEqual((verdict, adopted['method'], adopted['P80'], new), (['NEW_COEF', 'ADOPT_V2C'], 'v2c', 0.06, True))

    def test_keep_coef_when_new_is_not_better(self):
        h = {'v1': m(0.15), 'v0': m(0.04), 'v2c': m(0.05), 'v0_new': m(0.03), 'v2c_new': m(0.05)}
        verdict, adopted, new = backtest.decide(h, {'a': 0})
        # 같으면 새 계수를 쓰지 않는다. 지금 계수에서는 v0가 v2c보다 낫다
        self.assertEqual((verdict, adopted['method'], new), (['KEEP_COEF', 'ADOPT_V0'], 'v0', False))
        self.assertEqual(backtest.decide({k: h[k] for k in ('v1', 'v0', 'v2c')}, None)[0], ['KEEP_COEF', 'ADOPT_V0'])

    def test_keep_v1_when_margin_coverage_or_shuffle_fail(self):
        for v2c in (m(0.14), m(0.05, coverage=0.8), m(0.05, shuffle=0.2)):
            verdict, adopted, _ = backtest.decide({'v1': m(0.15), 'v0': m(0.2), 'v2c': v2c}, None)
            self.assertEqual((verdict[-1], adopted['method'], adopted['P80']), ('KEEP_V1', 'v1', 0.3))

    def test_too_few_and_control_fail_change_nothing(self):
        h = {'v1': m(0.15, n=29), 'v0': m(0.06, n=29), 'v2c': m(0.05, n=29)}
        self.assertEqual(backtest.decide(h, None), (['TOO_FEW'], None, False))
        h = {'v1': m(0.15), 'v0': m(0.06), 'v2c': m(0.05, alive=False)}
        self.assertEqual(backtest.decide(h, None), (['CONTROL_FAIL'], None, False))


class When(unittest.TestCase):
    def test_due_after_170_days_or_never(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, 'result.json')
            path.write_text('{"adopted": {"method": "v2c"}}', encoding='utf-8')
            self.assertTrue(backtest.due(d, dt.date(2026, 11, 20)))
            path.write_text(json.dumps({'auto_runs': [{'date': '2026-11-04'}]}), encoding='utf-8')
            self.assertFalse(backtest.due(d, dt.date(2027, 4, 22)))  # 169일
            self.assertTrue(backtest.due(d, dt.date(2027, 4, 23)))  # 170일

    def test_auto_window_ends_585_days_back_and_spans_912(self):
        since, until = backtest_data.auto_window(dt.date(2027, 5, 21))
        self.assertEqual(until, (dt.date(2027, 5, 21) - dt.timedelta(days=585)).isoformat())
        self.assertEqual((dt.date.fromisoformat(until) - dt.date.fromisoformat(since)).days, 912)


if __name__ == '__main__':
    unittest.main()
