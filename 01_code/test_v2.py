"""v2a 시세 계산 시험. 카카오를 부르지 않고 가짜 좌표를 쓴다."""

import unittest

import v2


def trade(apt, jibun, price, area=84.9, built=2022, kind='매매', umd='가동'):
    return {'apt': apt, 'umd': umd, 'jibun': jibun, 'area': area, 'price': price, 'built': built, 'kind': kind, 'date': '2026-09-01'}


# 위도 0.009도 ≈ 1km. 공고 단지는 (36.0, 128.0)
SPOTS = {'시 구 대상동 1': (36.0, 128.0), '시 구 가동 1': (36.0045, 128.0), '시 구 가동 2': (36.009, 128.0),
         '시 구 가동 3': (36.0126, 128.0), '시 구 가동 9': (36.045, 128.0)}


class V2(unittest.TestCase):
    def test_clean_address(self):
        self.assertEqual(v2.clean_address('경상북도 구미시 형곡동 141-11번지 외 3필지'), '경상북도 구미시 형곡동 141-11')
        self.assertEqual(v2.clean_address('부산광역시 강서구 명지동 3238-1 일원'), '부산광역시 강서구 명지동 3238-1')

    def test_one_vote_per_complex(self):
        # 1.4km 떨어진 대단지(9건)가 가까운 두 단지를 누르지 않는다. 가중치는 거래 수(5건까지)의 제곱근 ÷ (0.5 + 거리)
        pool = [trade('큰단지', '3', 84900)] * 9 + [trade('작은단지', '1', 50940)] + [trade('작은단지2', '2', 42450)]
        got = v2.estimate('시 구 대상동 1', 84.9, 40000, pool, 2026, '시 구', SPOTS.get)
        self.assertEqual(len(got['comps']), 3)
        self.assertEqual(got['market'], 50940)

    def test_far_and_old_excluded(self):
        pool = [trade('먼단지', '9', 200000)] * 3 + [trade('낡은단지', '1', 30000, built=2005)] * 3
        self.assertIsNone(v2.estimate('시 구 대상동 1', 84.9, 40000, pool, 2026, '시 구', SPOTS.get))

    def test_newest_preferred(self):
        pool = [trade('신축', '1', 90000, built=2025), trade('분양권', '2', 95000, kind='분양권'), trade('신축2', '3', 88000, built=2024),
                trade('8년차', '1', 60000, built=2018, umd='나동')]
        spots = {**SPOTS, '시 구 나동 1': (36.001, 128.0)}
        got = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots.get)
        self.assertEqual({c['apt'] for c in got['comps']}, {'신축', '분양권', '신축2'})

    def test_no_key_means_no_estimate(self):
        g = v2.Geocoder(key='')
        self.assertIsNone(g('경상북도 구미시 형곡동 141-11'))
        self.assertEqual(g.calls, 0)


if __name__ == '__main__':
    unittest.main()
