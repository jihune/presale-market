"""v2c 시세(분양가 × 예상 웃돈) 시험."""

import math
import unittest

import v2


class EstimateC(unittest.TestCase):
    def test_gap_is_clamped_log_ratio(self):
        self.assertAlmostEqual(v2.gap(1100, 1000), math.log(1.1))
        self.assertEqual(v2.gap(100, 1000), -0.5)
        self.assertEqual(v2.gap(5000, 1000), 0.3)
        self.assertIsNone(v2.gap(None, 1000))

    def test_v2c_uses_neighbor_gap(self):
        # 분양가 4억(84.9㎡), 주변 시세(v1)가 분양가와 같으면 예상 웃돈 e^0.0287 − 1, 범위는 남는 차이의 20·80% 분위
        k = v2.V2C
        same = v2.estimate_c({'per': 40000 / 84.9, 'scope': 's', 'market': 40000, 'rate': 0.0}, 84.9, 40000)
        self.assertEqual(same['method'], 'v2c')
        self.assertEqual(same['market'], round(40000 * math.exp(k['a'])))
        self.assertEqual(same['range'], (round(40000 * math.exp(k['a'] + k['q20'])), round(40000 * math.exp(k['a'] + k['q80']))))
        self.assertEqual(same['v1'], {'scope': 's', 'market': 40000, 'rate': 0.0})
        # 주변 시세가 높으면 예상 웃돈도 높지만 기울기 0.098만큼만 따라간다
        high = v2.estimate_c({'per': 40000 * 1.2 / 84.9, 'scope': 's', 'market': 48000, 'rate': 0.2}, 84.9, 40000)
        self.assertAlmostEqual(high['per'] / same['per'], math.exp(k['b'] * math.log(1.2)), places=9)

    def test_no_neighbors_and_v0_use_average_premium(self):
        k = v2.V2C
        for got in (v2.estimate_c(None, 84.9, 40000), v2.estimate_c({'per': 999, 'scope': 's', 'market': 1, 'rate': 0}, 84.9, 40000, slope=False)):
            self.assertEqual(got['market'], round(40000 * math.exp(k['a0'])))
            self.assertEqual(got['range'], (round(40000 * math.exp(k['a0'] + k['q20_0'])), round(40000 * math.exp(k['a0'] + k['q80_0']))))
        self.assertEqual(v2.estimate_c(None, 84.9, 40000)['method'], 'v2c')
        self.assertEqual(v2.estimate_c(None, 84.9, 40000, slope=False)['method'], 'v0')

    def test_pick(self):
        same = {'tier': 0, 'per': 1}
        near = {'tier': 3, 'per': 2}
        new = {'method': 'v2c', 'per': 3}
        self.assertIs(v2.pick(same, new), same)
        self.assertIs(v2.pick(near, new), new)
        self.assertIs(v2.pick(near, None), near)
        self.assertIsNone(v2.pick(None, None))


if __name__ == '__main__':
    unittest.main()
