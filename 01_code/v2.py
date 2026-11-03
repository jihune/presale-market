"""시세 계산 v2c: 새 단지 분양권이 공고 뒤 거래될 값을 「분양가 × (1 + 예상 웃돈)」으로 낸다.

예상 웃돈은 v1 주변 시세가 분양가보다 높고 낮은 정도(로그)에 비례하고, 계수는 01_code/fit_v2c.py가 영남 2023 ~ 2025 공고의
공고 뒤 6 ~ 18개월 분양권 거래로 맞췄다. 백테스트 3회차(03_notes/backtest/README.md)가 검증 묶음에서 채택했다.
1회차 v2a(거리)와 2회차 v2b(연식·세대수·시공사·거리 회귀, 카카오 좌표)는 기각돼 지웠다(코드는 커밋 218531e).
"""

import math

GAP_RANGE = (-0.5, 0.3)  # x = log(주변 시세 ÷ 분양가)를 이 안에서 자른다


def gap(per, p):
    """주변 시세(v1 ㎡당) ÷ 분양가(㎡당)의 로그를 GAP_RANGE에서 자른 값. 주변 시세가 없으면 None."""
    if not per:
        return None
    return max(GAP_RANGE[0], min(GAP_RANGE[1], math.log(per / p)))


# v2c 계수: 01_code/fit_v2c.py를 영남 2023-01 ~ 2025-06 공고 백테스트 자료(주택형 348개, 2026-11-03)에 돌린 값. 3회차 판정은 검증 묶음에서 한다
V2C = {'a': 0.0287, 'b': 0.098, 'q20': -0.075, 'q80': 0.0316, 'a0': 0.0131, 'q20_0': -0.0861, 'q80_0': 0.0301}
METHOD_C = ('v2c: 분양가 × (1 + 예상 웃돈). 예상 웃돈의 로그 = 0.0287 + 0.098 × log(v1 주변 시세 ÷ 분양가, −0.5 ~ 0.3에서 자름)이고 '
            '주변 시세가 없으면 0.0131. 계수는 영남 2023 ~ 2025 공고의 공고 뒤 6 ~ 18개월 분양권 거래로 맞췄다. 같은 단지 거래가 있으면 v1')
METHOD_0 = ('v0: 분양가 × (1 + 예상 웃돈). 예상 웃돈의 로그 = 0.0131(주변 시세를 쓰지 않음). 계수는 영남 2023 ~ 2025 공고의 '
            '공고 뒤 6 ~ 18개월 분양권 거래로 맞췄다. 같은 단지 거래가 있으면 v1')


def estimate_c(v1, area, price, slope=True):
    """v2c 예상 분양권 거래가. v1: 같은 공고 주택형의 v1 결과(없으면 None). slope=False면 v0(분양가 × 평균 웃돈, 주변 시세를 쓰지 않음)."""
    p = price / area
    x = gap(v1['per'] if v1 else None, p) if slope else None
    k = V2C
    lp, lo, hi = (k['a'] + k['b'] * x, k['q20'], k['q80']) if x is not None else (k['a0'], k['q20_0'], k['q80_0'])
    per = p * math.exp(lp)
    market = round(per * area)
    return {'method': 'v2c' if slope else 'v0', 'per': per, 'market': market, 'gain': market - price, 'rate': (market - price) / price,
            'scope': f'분양가 × 예상 웃돈 {math.exp(lp) - 1:+.1%}' + (f'(주변 시세 ÷ 분양가 {math.exp(x) - 1:+.0%})' if x is not None else '(주변 시세 없음)'),
            'range': (round(per * math.exp(lo) * area), round(per * math.exp(hi) * area)), 'gap': x,
            'v1': {key: v1[key] for key in ('scope', 'market', 'rate')} if v1 else None}


def pick(v1, new):
    """같은 단지 거래로 낸 v1(조합원 취소분·무순위)이 가장 정확하다. 그다음 새 방법, 그것이 없으면 v1."""
    if v1 and v1.get('tier') == 0:
        return v1
    return new or v1
