"""v2c 계수 맞추기. 백테스트 자료(영남)에서 주택형마다 x = log(v1 ㎡당 ÷ 분양가 ㎡당)(−0.5 ~ 0.3에서 자름),
y = log(정답 ㎡당 ÷ 분양가 ㎡당)을 만들고, 절대 오차 합이 가장 작은 직선 y = a + b x(중앙값 회귀)와
x 없이 쓰는 a0(y의 중간값), 남는 차이의 20·80% 분위를 낸다. 같은 단지 거래로 낸 v1(조합원 취소분·무순위)은 v1을 그대로 쓰므로 뺀다.

사용: python 01_code/fit_v2c.py <자료 폴더>   결과를 표준 출력에 JSON으로 낸다(3회차는 v2.py의 V2C에 옮겨 적었다).
자동 점검(backtest.py auto)은 fit()을 불러 영남 창 자료로 새 계수를 맞춘다.
"""

import json
import math
import statistics
import sys
from pathlib import Path

import backtest
import presale
import v2


def points(data):
    notices = json.loads((data / 'notices.json').read_text(encoding='utf-8'))
    out = []
    for n in notices:
        if not n.get('code'):
            continue
        for m in n['models']:
            area = presale.area_of(m.get('HOUSE_TY'))
            price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
            if not area or not price:
                continue
            truth = backtest.truth_of(n, area, data)
            if truth is None:
                continue
            c = backtest.v1_of(n, area, price, data)
            if c and c.get('tier') == 0:
                continue
            p = price / area
            out.append((v2.gap(c['per'] if c else None, p), math.log(truth / p)))
    return out


def lad(xs, ys):
    """y = a + b x의 절대 오차 합 최소(b를 0.001 간격으로 −1 ~ 1에서 찾고, a는 그때 남는 차이의 중간값)."""
    best = None
    for k in range(-1000, 1001):
        b = k / 1000
        a = statistics.median(y - b * x for x, y in zip(xs, ys, strict=True))
        loss = sum(abs(y - a - b * x) for x, y in zip(xs, ys, strict=True))
        if best is None or loss < best[0]:
            best = (loss, a, b)
    return best[1], best[2]


def fit(data):
    """계수 dict(points, with_v1, a, b, q20, q80, a0, q20_0, q80_0). 주변 시세가 있는 주택형이 없으면 None(자동 점검도 쓴다)."""
    pts = points(Path(data))
    with_x = [(x, y) for x, y in pts if x is not None]
    if not with_x:
        return None
    a, b = lad([x for x, _ in with_x], [y for _, y in with_x])
    res = sorted(y - a - b * x for x, y in with_x)
    a0 = statistics.median(y for _, y in pts)
    res0 = sorted(y - a0 for _, y in pts)

    def q(s, p):
        return s[min(len(s) - 1, int(p * len(s)))]
    return {'points': len(pts), 'with_v1': len(with_x), 'a': round(a, 4), 'b': round(b, 3),
            'q20': round(q(res, 0.2), 4), 'q80': round(q(res, 0.8), 4),
            'a0': round(a0, 4), 'q20_0': round(q(res0, 0.2), 4), 'q80_0': round(q(res0, 0.8), 4)}


if __name__ == '__main__':
    print(json.dumps(fit(sys.argv[1]), ensure_ascii=False))
