"""v2c 후보(행정구역만, 좌표 없음). fn(pool12, pool6, area, umd, year, name) → ㎡당 값 또는 None(v1을 쓴다)."""

import statistics


def near(pool, area):
    return [t for t in pool if abs(t['area'] - area) <= max(area * 0.1, 5)]


def first(s):
    return (s.split() or [''])[0]


def groups(trades):
    g = {}
    for t in trades:
        g.setdefault((t['apt'], t['umd'], t.get('jibun', '')), []).append(t)
    return g


def vote_per(trades):
    """단지마다 ㎡당 중간값, 그 중간값들의 중간값(단지마다 한 표)."""
    g = groups(trades)
    return statistics.median(statistics.median(t['price'] / t['area'] for t in ts) for ts in g.values()), len(g)


def parts(pool, area, umd, year, new_years=5):
    nr = near(pool, area)
    dong = [t for t in nr if umd and first(t['umd']) == umd]
    pre = [t for t in nr if t['kind'] != '매매']
    new = [t for t in nr if t['kind'] == '매매' and t['built'] >= year - new_years]
    return {'dong_pre': [t for t in pre if t in dong], 'dong_new': [t for t in new if t in dong],
            'sgg_pre': pre, 'sgg_new': new, 'dong_any': dong}


def ratio(pool, area, year, lo=0.8, hi=1.6):
    """시·군·구의 분양권 단지 ㎡당 중간값 ÷ 5년 이내 매매 단지 ㎡당 중간값(각 2곳 이상). 없으면 None."""
    p = parts(pool, area, '', year)
    if len(groups(p['sgg_pre'])) < 2 or len(groups(p['sgg_new'])) < 2:
        return None
    r = vote_per(p['sgg_pre'])[0] / vote_per(p['sgg_new'])[0]
    return max(lo, min(hi, r))


ORDER = ('dong_pre', 'dong_new', 'sgg_pre', 'sgg_new', 'dong_any')


def tiered(pool12, pool6, area, umd, year, per_complex, premium, order=ORDER, need=3):
    for pool in (pool6, pool12):
        p = parts(pool, area, umd, year)
        for k in order:
            ts = p[k]
            if len(ts) < need:
                continue
            if per_complex:
                per = vote_per(ts)[0]
            else:
                per = statistics.median(t['price'] / t['area'] for t in sorted(ts, key=lambda t: t['date'], reverse=True)[:10])
            if premium and not k.endswith('pre'):
                r = ratio(pool12, area, year)
                if r:
                    per *= r
            return per
    return None


CANDIDATES = {
    'C0 v1 재현(같은 단지 뺀 순서)': lambda a, b, area, umd, year, name: tiered(a, b, area, umd, year, False, False),
    'C1 단지마다 한 표': lambda a, b, area, umd, year, name: tiered(a, b, area, umd, year, True, False),
    'C2 분양권 프리미엄 곱하기': lambda a, b, area, umd, year, name: tiered(a, b, area, umd, year, False, True),
    'C3 단지마다 한 표 + 프리미엄': lambda a, b, area, umd, year, name: tiered(a, b, area, umd, year, True, True),
    'C4 분양권 먼저(동 → 시군구) + 프리미엄': lambda a, b, area, umd, year, name: tiered(
        a, b, area, umd, year, False, True, order=('dong_pre', 'sgg_pre', 'dong_new', 'sgg_new', 'dong_any')),
    'C5 분양권 먼저 + 한 표 + 프리미엄': lambda a, b, area, umd, year, name: tiered(
        a, b, area, umd, year, True, True, order=('dong_pre', 'sgg_pre', 'dong_new', 'sgg_new', 'dong_any')),
}
