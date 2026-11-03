"""v2b 시세 계산과 공동주택 단지 붙이기 시험. 카카오·공공데이터포털을 부르지 않고 가짜 좌표와 가짜 응답을 쓴다."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import presale
import v2


def trade(apt, jibun, per, area=84.9, built=2022, kind='매매', umd='가동', n=1):
    return [{'apt': apt, 'umd': umd, 'jibun': jibun, 'area': area, 'price': round(per * area), 'built': built, 'kind': kind,
             'date': '2026-09-01'}] * n


def spots(count, step_km=0.4):
    """공고 단지 (36.0, 128.0)에서 북쪽으로 step_km씩 떨어진 지번 1 ~ count. 위도 0.009도 ≈ 1km."""
    out = {'시 구 대상동 1': (36.0, 128.0)}
    for i in range(1, count + 1):
        out[f'시 구 가동 {i}'] = (36.0 + 0.009 * step_km * i, 128.0)
    return out


class Estimate(unittest.TestCase):
    def test_age_and_presale_adjusted_toward_new_presale(self):
        # ㎡당 값이 연식마다 3% 내리고 분양권이 1,000인 시장. 가까운 비교 단지는 모두 6 ~ 10년 차라 보정하지 않으면 낮게 나온다
        pool = []
        for i, age in enumerate([6, 8, 10, 1, 2, 3, 4, 5, 7, 9], start=1):
            pool += trade(f'단지{i}', str(i), 1000 * math.exp(-0.03 * age), built=2026 - age)
        pool += trade('분양권1', '11', 1000, kind='분양권') + trade('분양권2', '12', 1000, kind='분양권')
        raw = [1000 * math.exp(-0.03 * a) for a in (6, 8, 10)]
        got = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots(12).get, umd='대상동')
        self.assertEqual(got['method'], 'v2b')
        self.assertLess(statistics_median(raw), 850)
        self.assertGreater(got['per'], 960)
        self.assertLess(got['per'], 1040)
        self.assertLess(got['model']['coef']['age'], 0)
        self.assertLessEqual(got['range'][0], got['market'])
        self.assertGreaterEqual(got['range'][1], got['market'])

    def test_households_and_top_builder_from_lookup(self):
        # 대단지(1,000세대)가 10% 비싸다. 공고 단지가 대단지면 작은 단지 값을 올린다
        pool, info = [], {}
        for i in range(1, 11):
            big = i % 2 == 0
            pool += trade(f'단지{i}', str(i), 1100 if big else 1000, built=2024)
            info[str(i)] = {'households': 1000 if big else 100, 'builder': ''}
        lookup = mock.Mock(side_effect=lambda apt, umd, jibun, built: info[jibun])
        small = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots(10).get, lookup=lookup, households=100)
        large = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots(10).get, lookup=lookup, households=1000)
        self.assertGreater(large['per'], small['per'] * 1.05)
        self.assertEqual(small['model']['hh_known'], 10)
        lookup.assert_called_with('단지10', '가동', '10', 2024)

    def test_lookup_not_called_for_presale(self):
        pool = []
        for i in range(1, 10):
            pool += trade(f'분양권{i}', str(i), 1000, kind='분양권')
        lookup = mock.Mock(return_value=None)
        v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots(9).get, lookup=lookup)
        lookup.assert_not_called()

    def test_none_when_too_few_or_old_or_far(self):
        few = [x for i in range(1, 6) for x in trade(f'단지{i}', str(i), 1000)]
        self.assertIsNone(v2.estimate('시 구 대상동 1', 84.9, 80000, few, 2026, '시 구', spots(5).get))
        old = [x for i in range(1, 11) for x in trade(f'단지{i}', str(i), 1000, built=2000)]
        self.assertIsNone(v2.estimate('시 구 대상동 1', 84.9, 80000, old, 2026, '시 구', spots(10).get))
        far = [x for i in range(1, 11) for x in trade(f'단지{i}', str(i), 1000)]
        self.assertIsNone(v2.estimate('시 구 대상동 1', 84.9, 80000, far, 2026, '시 구', spots(10, step_km=6).get))

    def test_same_dong_counts_beyond_radius(self):
        pool = [x for i in range(1, 11) for x in trade(f'단지{i}', str(i), 1000, umd='대상동' if i <= 3 else '가동')]
        far = {**spots(10, step_km=6), **{f'시 구 대상동 {i}': (36.06 + 0.001 * i, 128.0) for i in range(1, 4)}}
        got = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', far.get, umd='대상동')
        self.assertEqual({c['apt'] for c in got['comps']}, {'단지1', '단지2', '단지3'})

    def test_one_vote_per_complex(self):
        # 거래 9건인 단지도 한 표다(가중치는 거래 수 5건까지의 제곱근 ÷ (0.5 + 거리)). 1.2km의 큰단지가 0.4·0.8km 두 단지를 누르지 않는다
        pool = trade('큰단지', '3', 2000, n=9)
        for i in (1, 2, 4, 5, 6, 7, 8, 9):
            pool += trade(f'단지{i}', str(i), 1000)
        got = v2.estimate('시 구 대상동 1', 84.9, 80000, pool, 2026, '시 구', spots(9).get)
        self.assertEqual(sum(c['apt'] == '큰단지' for c in got['comps']), 1)
        self.assertLess(got['per'], 1500)

    def test_pick(self):
        same = {'tier': 0, 'per': 1}
        near = {'tier': 3, 'per': 2}
        b = {'method': 'v2b', 'per': 3}
        self.assertIs(v2.pick(same, b), same)
        self.assertIs(v2.pick(near, b), b)
        self.assertIs(v2.pick(near, None), near)
        self.assertIsNone(v2.pick(None, None))

    def test_is_top(self):
        with mock.patch.object(v2, 'TOP_BUILDERS', ('아이파크', '현대산업개발', 'e편한세상')):
            self.assertTrue(v2.is_top('구미아이파크더샵', ''))
            self.assertTrue(v2.is_top('형곡동신', 'HDC 현대산업개발(주)'))
            self.assertTrue(v2.is_top('E-편한세상 구미', ''))
            self.assertFalse(v2.is_top('형곡 센트럴 아테라', '금호건설'))

    def test_clean_address(self):
        self.assertEqual(v2.clean_address('경상북도 구미시 형곡동 141-11번지 외 3필지'), '경상북도 구미시 형곡동 141-11')
        self.assertEqual(v2.clean_address('부산광역시 강서구 명지동 3238-1 일원'), '부산광역시 강서구 명지동 3238-1')


def statistics_median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


class Geocode(unittest.TestCase):
    def test_geocoder_retries_and_does_not_remember_failures(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"documents": [{"y": "36.1", "x": "128.3"}]}'
        g = v2.Geocoder(key='k')
        with mock.patch.object(v2.time, 'sleep'), \
                mock.patch.object(v2.urllib.request, 'urlopen', side_effect=[ConnectionResetError(104, 'reset'), ok]):
            self.assertEqual(g('주소'), (36.1, 128.3))
        g2 = v2.Geocoder(key='k')
        with mock.patch.object(v2.time, 'sleep'), \
                mock.patch.object(v2.urllib.request, 'urlopen', side_effect=ConnectionResetError(104, 'reset')):
            self.assertIsNone(g2('주소'))
        self.assertEqual((g2.errors, g2.misses, '주소' in g2.memo), (1, 0, False))

    def test_no_key_means_no_estimate(self):
        g = v2.Geocoder(key='')
        self.assertIsNone(g('경상북도 구미시 형곡동 141-11'))
        self.assertEqual(g.calls, 0)


LIST = {'response': {'header': {'resultCode': '00', 'resultMsg': 'NORMAL SERVICE.'}, 'body': {'totalCount': '4', 'items': [
    {'kaptCode': 'A1', 'kaptName': '구미 아이파크 더샵 아파트', 'as3': '원평동', 'as4': None},
    {'kaptCode': 'A2', 'kaptName': '형곡금호어울림포레1차', 'as3': '형곡동', 'as4': None},
    {'kaptCode': 'A3', 'kaptName': '형곡금호어울림포레', 'as3': '형곡동', 'as4': None},
    {'kaptCode': 'A4', 'kaptName': '교리e편한세상', 'as3': '선산읍', 'as4': '교리'}]}}}


def basis(code, addr, hh, builder, use):
    return {'response': {'header': {'resultCode': '00', 'resultMsg': 'NORMAL SERVICE.'}, 'body': {'item': {
        'kaptCode': code, 'kaptName': '이름', 'kaptAddr': addr, 'kaptdaCnt': hh, 'hoCnt': 0, 'kaptBcompany': builder,
        'kaptUsedate': use, 'kaptTel': '0540000000', 'kaptFax': '0540000001', 'kaptUrl': 'http://example.com',
        'doroJuso': '경상북도 구미시 어딘가로 1'}}}}


BASIS = {'A1': basis('A1', '경상북도 구미시 원평동 1134 구미 아이파크 더샵 아파트', 1611.0, '현대산업개발,포스코', '20231128'),
         'A2': basis('A2', '경상북도 구미시 형곡동 100 형곡금호어울림포레1차', 500.0, '금호산업', '20170601'),
         'A3': basis('A3', '경상북도 구미시 형곡동 200 형곡금호어울림포레', 300.0, '금호산업', '20170601'),
         'A4': basis('A4', '경상북도 구미시 선산읍 교리 50 교리e편한세상', 0, '대림산업', '20200101')}


class Complexes(unittest.TestCase):
    def fake_get(self, url, params, name, parse=None):
        self.urls.append(url)
        body = LIST if url == presale.KAPT_LIST else BASIS[params['kaptCode']]
        return parse(json.dumps(body, ensure_ascii=False))

    def setUp(self):
        self.urls = []
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(presale, '_get', side_effect=self.fake_get)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.c = presale.Complexes(root=self.dir.name, today=presale.dt.date(2026, 11, 3), limit=10)

    def test_match_by_dong_and_name(self):
        self.assertEqual(self.c.lookup('47190', '구미아이파크더샵', '원평동', '1134', 2023), {'households': 1611, 'builder': '현대산업개발,포스코'})

    def test_eup_ri_dong_and_hocnt_zero(self):
        # 읍·면은 실거래 umdNm이 「선산읍 교리」다. 세대수 칸이 0이고 호수도 0이면 0
        self.assertEqual(self.c.lookup('47190', '교리e편한세상', '선산읍 교리', '50', 2020)['builder'], '대림산업')

    def test_several_candidates_pick_by_jibun(self):
        self.assertEqual(self.c.lookup('47190', '형곡금호어울림포레', '형곡동', '200', 2017)['households'], 300)
        self.assertEqual(self.c.lookup('47190', '형곡금호어울림포레', '형곡동', '100-3', 2017)['households'], 500)

    def test_year_mismatch_and_other_dong_rejected(self):
        self.assertIsNone(self.c.lookup('47190', '구미아이파크더샵', '원평동', '1134', 2015))
        self.assertIsNone(self.c.lookup('47190', '구미아이파크더샵', '형곡동', '1134', 2023))

    def test_saved_without_contact_fields_and_not_called_again(self):
        self.c.lookup('47190', '구미아이파크더샵', '원평동', '1134', 2023)
        saved = Path(self.dir.name, '47190.json').read_text(encoding='utf-8')
        for word in ('0540000000', '0540000001', 'example.com', '어딘가로'):
            self.assertNotIn(word, saved)
        again = presale.Complexes(root=self.dir.name, today=presale.dt.date(2026, 11, 3), limit=10)
        again.lookup('47190', '구미아이파크더샵', '원평동', '1134', 2023)
        self.assertEqual((len(self.urls), again.calls), (2, 0))

    def test_limit_and_quota_stop(self):
        c = presale.Complexes(root=self.dir.name, today=presale.dt.date(2026, 11, 3), limit=0)
        self.assertIsNone(c.lookup('47190', '구미아이파크더샵', '원평동', '1134', 2023))
        self.assertEqual(self.urls, [presale.KAPT_LIST])
        with self.assertRaises(RuntimeError):
            presale._kapt('<OpenAPI_ServiceResponse><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg></OpenAPI_ServiceResponse>')
        with self.assertRaises(presale.Transient):
            presale._kapt('<OpenAPI_ServiceResponse><returnAuthMsg>HTTP ROUTING ERROR</returnAuthMsg></OpenAPI_ServiceResponse>')
        self.assertEqual(presale._kapt('{"response": {"header": {"resultCode": "03", "resultMsg": "NODATA_ERROR"}}}'), {})


if __name__ == '__main__':
    unittest.main()
