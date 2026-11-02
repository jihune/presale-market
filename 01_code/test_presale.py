"""공고문 읽기·주소·시세 비교 함수 시험. 실행: python -m unittest discover -s 01_code"""

import datetime as dt
import unittest
from unittest import mock

import presale


def apt(addr, area_nm, regulated='N', dtl='01', secd='01'):
    return {'HOUSE_NM': '시험 단지', 'HSSPLY_ADRES': addr, 'SUBSCRPT_AREA_CODE_NM': area_nm,
            'SPECLT_RDN_EARTH_AT': regulated, 'MDAT_TRGET_AREA_SECD': regulated,
            'HOUSE_DTL_SECD': dtl, 'HOUSE_SECD': secd, 'PARCPRC_ULS_AT': 'N'}


class Address(unittest.TestCase):
    def test_split(self):
        self.assertEqual(presale.split_address('충청북도 청주시 흥덕구 오송읍 봉산리 100'), ('충청북도', '청주시 흥덕구', '오송읍'))
        self.assertEqual(presale.split_address('대구광역시 수성구 범어동 100'), ('대구광역시', '수성구', '범어동'))
        self.assertEqual(presale.split_address('경북 구미시 산동읍 1'), ('경상북도', '구미시', '산동읍'))
        self.assertEqual(presale.split_address('세종특별자치시 산울동 1'), ('세종특별자치시', '', '산울동'))
        self.assertEqual(presale.split_address('대구광역시 동구 동부로 12'), ('대구광역시', '동구', ''))
        self.assertEqual(presale.split_address('전남광주통합특별시 광산구 하산동 269번지 일원', '광주'), ('전남광주통합특별시', '광산구', '하산동'))

    def test_area(self):
        self.assertEqual(presale.area_of('084.9800A'), 84.98)
        self.assertEqual(presale.area_of('059.9900B'), 59.99)


def trade(umd, area, price, built=2022, date='2026-09-01', kind='매매'):
    return {'apt': '비교 단지', 'umd': umd, 'area': area, 'price': price, 'floor': '10', 'built': built, 'date': date, 'kind': kind}


class Compare(unittest.TestCase):
    def test_same_dong_first(self):
        pool = [trade('범어동', 84.9, 100000)] * 3 + [trade('만촌동', 84.9, 50000)] * 5
        c = presale.compare(84.9, 70000, pool, '범어동', 2026)
        self.assertEqual(c['scope'], '같은 읍·면·동, 5년 이내 단지')
        self.assertEqual((c['market'], c['gain']), (100000, 30000))

    def test_falls_back_to_sigungu(self):
        pool = [trade('만촌동', 84.9, 90000)] * 3
        self.assertEqual(presale.compare(84.9, 70000, pool, '범어동', 2026)['scope'], '같은 시·군·구, 5년 이내 단지')

    def test_presale_before_old_resale(self):
        pool = [trade('범어동', 84.9, 40000, built=2017)] * 6 + [trade('범어동', 84.9, 56000, built=2026, kind='분')] * 3
        c = presale.compare(84.9, 55000, pool, '범어동', 2026)
        self.assertEqual((c['scope'], c['market']), ('같은 읍·면·동 분양권·입주권', 56000))

    def test_ignores_far_area_and_too_few(self):
        pool = [trade('범어동', 59.9, 60000)] * 5 + [trade('범어동', 84.9, 90000)] * 2
        self.assertIsNone(presale.compare(84.9, 70000, pool, '범어동', 2026))

    def test_same_complex_first(self):
        own = [{**trade('광안동', 84.96, 81950, kind='분양권', date='2026-05-13'), 'apt': '광안센텀 비스타동원'},
               {**trade('광안동', 84.94, 82000, kind='분양권', date='2025-11-07'), 'apt': '광안센텀 비스타동원'}]
        big = [{**trade('광안동', 84.9, 119000, kind='분양권'), 'apt': '드파인 광안'}] * 10
        c = presale.compare(84.94, 86700, own + big, '광안동', 2026, name='광안센텀 비스타동원(조합원 취소분)')
        self.assertEqual((c['scope'], c['tier']), ('같은 단지', 0))
        self.assertLess(c['gain'], 0)
        self.assertEqual(presale.compare(84.94, 86700, own + big, '광안동', 2026)['scope'], '같은 읍·면·동 분양권·입주권')
        self.assertIsNone(presale.compare(84.94, 86700, own[:1] + big, '광안동', 2026, tier=0, name='광안센텀 비스타동원'))
        self.assertTrue(presale.same_complex('광안센텀 비스타동원', '광안센텀 비스타동원(조합원 취소분)'))
        self.assertFalse(presale.same_complex('트리븐센텀 1단지', '트리븐센텀 2단지'))
        self.assertFalse(presale.same_complex('', '광안센텀 비스타동원'))

    def test_align_types_uses_closest_scope(self):
        near = presale.compare(84.9, 77000, [trade('우동', 84.9, 64000, built=2023)] * 3, '우동', 2026)
        far = presale.compare(115.0, 102000, [trade('재송동', 115.0, 200000, built=2023)] * 3, '우동', 2026)
        types = [{'area': 84.9, 'price': 77000, 'cmp': near}, {'area': 115.0, 'price': 102000, 'cmp': far}]
        presale.align_types(types)
        self.assertEqual(types[1]['cmp']['market'], round(64000 / 84.9 * 115.0))

    def test_presale_api_rows_are_presale(self):
        # 분양권 API는 구분 칸(ownershipGbn)을 빈칸으로 준다. 매매로 분류하면 안 된다
        body = ('<response><header><resultCode>000</resultCode></header><body><items><item>'
                '<aptNm>시험</aptNm><umdNm>대잠동</umdNm><jibun>1</jibun><excluUseAr>84.5</excluUseAr><dealAmount>57,772</dealAmount>'
                '<floor>25</floor><dealYear>2026</dealYear><dealMonth>9</dealMonth><dealDay>15</dealDay>'
                '<ownershipGbn> </ownershipGbn><cdealType> </cdealType></item></items></body></response>')
        with mock.patch.object(presale, '_get', return_value=body):
            self.assertEqual(presale.trades('47111', '202609', url=presale.SILV)[0]['kind'], '분양권')
            self.assertEqual(presale.trades('47111', '202609')[0]['kind'], '매매')

    def test_settled_months(self):
        today = dt.date(2026, 11, 3)
        self.assertTrue(presale.settled('202609', today))
        self.assertFalse(presale.settled('202610', today))
        self.assertTrue(presale.settled('202511', dt.date(2026, 1, 5)))
        self.assertFalse(presale.settled('202512', dt.date(2026, 1, 5)))


# 공고문 첫 쪽 「단지 주요정보」를 pdftotext -layout으로 뽑은 글(2026-10-17 청약홈 첨부 PDF에서 그대로 옮김)
BOX_DAEGU = chr(10).join((
    '      주택유형                            해당지역                                             기타지역                                           규제지역여부',
    '',
    '       민영                         대구광역시 거주자                                          경상북도 거주자                                          비규제지역',
    '',
    '         재당첨제한                             전매제한                         거주의무기간                              분양가상한제                               택지유형',
    '',
    '            없음                              6개월                               없음                               미적용                               민간택지',
    '',
))
BOX_JINJU = chr(10).join((
    '            주택유형                                  해당지역                                                   기타지역                                                                 규제지역여부',
    '                                      경상남도 진주시 1년이상 거주자                                           경상남도 진주시 1년미만 거주자',
    '              민영                                                                                                                                                              비규제지역',
    '                                      (2025.09.18. 이전부터 계속 거주)                                 및 경상남도, 부산광역시, 울산광역시 거주자',
    '           재당첨제한                                  전매제한                                       거주의무기간               분양가상한제                                                       택지유형',
    '              없음                                    없음                                         없음                                       미적용                                    민간택지',
    '',
    ' 구분      입주자모집공고일           견본주택 오픈일                특별공급 접수일              일반공급 1순위 접수일 일반공급 2순위 접수일                          당첨자발표일                   서류접수                         계약체결',
))


class NoticeText(unittest.TestCase):
    def test_box_daegu(self):
        b = presale.parse_box(BOX_DAEGU)
        self.assertEqual((b['전매제한'], b['거주의무기간'], b['분양가상한제'], b['규제지역여부']), ('6개월', '없음', '미적용', '비규제지역'))
        self.assertEqual(b['기타지역'], '경상북도 거주자')

    def test_box_two_line_cells(self):
        b = presale.parse_box(BOX_JINJU)
        self.assertEqual(b['해당지역'], '경상남도 진주시 1년이상 거주자 (2025.09.18. 이전부터 계속 거주)')
        self.assertEqual(b['기타지역'], '경상남도 진주시 1년미만 거주자 및 경상남도, 부산광역시, 울산광역시 거주자')
        self.assertEqual(b['전매제한'], '없음')

    def test_no_box(self):
        self.assertIsNone(presale.parse_box('힐스테이트 더샵 상생공원 2단지 입주자모집공고'))

    def test_months(self):
        self.assertEqual(presale.months_of('6개월'), 6)
        self.assertEqual(presale.months_of('1년'), 12)
        self.assertEqual(presale.months_of('없음'), 0)
        self.assertEqual(presale.months_of('3년 일반공급 1순위 접수일'), 36)
        self.assertIsNone(presale.months_of(''))

    def test_payment_terms(self):
        text = '계약금(5%) … 분양대금은 계약금(5%), 중도금(1~6회차 60%), 잔금(35%) … 계약금(10%) 이상 … 무이자 조건으로 … 융자 알선을 시행할 예정'
        t = presale.parse_payment(text)
        self.assertEqual(t['deposit'], 0.05)
        self.assertEqual(presale.parse_payment('공급금액표 계약금(10%) … 발코니 계약금(5%)')['deposit'], 0.10)
        self.assertEqual(t['mid_interest'], '무이자')
        self.assertTrue(t['mid_loan'])
        t = presale.parse_payment('계약금(30%) 무이자 … 발코니 이자후불')
        self.assertIsNone(t['deposit'])
        self.assertEqual(t['mid_interest'], '이자후불')

    def test_resale_fallback(self):
        self.assertEqual(presale.fallback_resale(apt('대구광역시 중구 동인동1가 9', '대구'), '대구광역시'), 6)
        self.assertEqual(presale.fallback_resale(apt('충청북도 청주시 흥덕구 복대동 1', '충북'), '충청북도'), 0)
        p = {**apt('부산광역시 강서구 명지동 1', '부산'), 'PARCPRC_ULS_AT': 'Y'}
        self.assertEqual(presale.fallback_resale(p, '부산광역시'), 12)
        self.assertEqual(presale.fallback_resale(apt('경기도 화성시 1', '경기', regulated='Y'), '경기도'), 36)

    def test_notice_fetch_failure(self):
        p = {**apt('부산광역시 수영구 광안동 971', '부산'), 'HOUSE_MANAGE_NO': '2026000507', 'PBLANC_URL': 'https://example.invalid/'}
        with mock.patch.object(presale, '_open', return_value='<title>청약홈</title>'.encode()), \
                mock.patch.object(presale.shutil, 'which', return_value='/usr/bin/pdftotext'), \
                self.assertRaises(RuntimeError):
            presale.notice_text(p)
        # 30초 뒤 한 번 더 받고, 두 번 다 실패해야 받기 실패다
        with mock.patch.object(presale.time, 'sleep'):
            with mock.patch.object(presale, 'notice_text', side_effect=RuntimeError('x')) as nt:
                got = presale.read_notice(p, '부산광역시')
            self.assertEqual(nt.call_count, 2)
            self.assertEqual(got['fetch_error'], 'x')
            self.assertEqual(got['resale_fallback_months'], 6)
            with mock.patch.object(presale, 'notice_text', side_effect=[RuntimeError('x'), (BOX_DAEGU, '', 'u')]):
                got = presale.read_notice(p, '부산광역시')
            self.assertEqual(got['fetch_error'], '')
            self.assertTrue(got['read'])
            self.assertEqual(got['resale_months'], 6)

    def test_movein_months(self):
        p = {'PRZWNER_PRESNATN_DE': '2024-02-15', 'MVN_PREARNGE_YM': '202709', 'RCRIT_PBLANC_DE': '2024-01-26'}
        self.assertEqual(presale.movein_months(p), 43)
        self.assertIsNone(presale.movein_months({'RCRIT_PBLANC_DE': '2026-10-01'}))
        self.assertEqual(presale.movein_months({'PRZWNER_PRESNATN_DE': '2026-10-20', 'MVN_PREARNGE_YM': '202609'}), 0)


if __name__ == '__main__':
    unittest.main()
