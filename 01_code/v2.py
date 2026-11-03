"""시세 계산 v2b: 공고 단지 가까운 단지들을 단지마다 한 표로 세고, 연식·분양권·세대수·상위 시공사·거리 차이를 보정해
거리 가중 중간값과 20·80% 범위를 낸다.

보정 계수는 공고 단지 시·군·구의 같은 면적대 단지(준공 15년 이내와 분양권)로 ㎡당 가격의 로그를 위 특성에 회귀해 얻는다.
비교 단지 값을 공고 단지 조건(분양권, 신축, 공고 세대수, 공고 시공사, 거리 0)으로 옮긴 뒤 모은다.

위치는 카카오 로컬 주소 검색으로 실행 안에서만 얻는다. 카카오 정책상 좌표·주소 결과를 저장할 수 없어
이 모듈은 좌표를 메모리에만 두고 파일·로그에 쓰지 않는다. 결과에는 단지 이름과 0.1km로 반올림한 거리만 남긴다.
환경 변수: KAKAO_REST_API_KEY. 단지 세대수·시공사(공동주택 기본정보)는 부르는 쪽이 lookup으로 넘긴다(presale.Complexes).
"""

import json
import math
import os
import re
import statistics
import time
import urllib.parse
import urllib.request

KAKAO = 'https://dapi.kakao.com/v2/local/search/address.json'
RADII = (1.5, 3.0, 5.0)  # km. 같은 동 단지와 합쳐 비교 단지가 3곳이 될 때까지 넓힌다
MAX_AGE = 15  # 준공 뒤 이 햇수 안의 단지와 분양권만 회귀와 비교에 쓴다
MIN_FIT = 8  # 회귀에 쓸 단지가 이보다 적으면 v2b 값을 내지 않는다(부르는 쪽이 v1을 쓴다)
RIDGE = 1.0  # 표준화한 특성의 능선 벌점. 단지 수가 적을 때 계수가 튀지 않게 한다
CLIP = 0.4  # 한 비교 단지의 보정 폭(로그) 상한. e^0.4 ≈ 1.49배
KM_CAP = 10.0  # 거리 특성은 10km에서 자른다
FEATURES = ('age', 'presale', 'log_hh', 'top', 'km')
METHOD = ('v2b: 같은 동과 1.5·3·5km 안 단지(15년 이내·분양권, 단지마다 한 표)를 시·군·구 단지 회귀로 연식·분양권·세대수·'
          '상위 10 시공사·거리 보정, 거리 가중 중간값과 20·80% 범위. 같은 단지 거래가 있거나 값을 못 내면 v1')

# 상위 시공사: 국토교통부 「'26년도 건설업체 시공능력평가 결과」(2026-07-30 보도자료 참고 2, 토목건축 상위 10곳. 같은 표의
# 2025년 상위 10곳도 같은 회사)의 회사 이름(옛 이름 포함)과 아파트 브랜드. 띄어쓰기·「-」를 빼고 소문자로 쓴다. 출처는 03_notes/v2-설계.md 「v2b」
# 「써밋」은 호반써밋과 겹쳐 넣지 않는다(대우건설 단지는 「푸르지오써밋」으로 잡힌다).
TOP_BUILDERS = (
    '삼성물산', '래미안',
    '현대건설', '힐스테이트', '디에이치',
    'gs건설', '지에스건설', 'lg건설', '엘지건설', '자이',
    '현대엔지니어링', '현대엠코',
    '대우건설', '푸르지오',
    'dl이앤씨', '디엘이앤씨', '대림산업', 'e편한세상', '이편한세상', '아크로',
    '롯데건설', '롯데캐슬', '르엘',
    '포스코', '더샵', '오티에르',
    'sk에코플랜트', '에스케이에코플랜트', 'sk건설', '에스케이건설', 'sk뷰', 'skview', '드파인',
    '현대산업개발', '아이파크',
)


class Geocoder:
    """주소 → (위도, 경도). 같은 실행 안에서만 기억한다(파일에 쓰지 않는다)."""

    def __init__(self, key=None):
        self.key = key if key is not None else os.environ.get('KAKAO_REST_API_KEY', '')
        self.memo, self.calls, self.misses, self.errors = {}, 0, 0, 0

    def __call__(self, address):
        if not self.key or not address:
            return None
        if address not in self.memo:
            req = urllib.request.Request(f'{KAKAO}?{urllib.parse.urlencode({"query": address, "size": 1})}',
                                         headers={'Authorization': f'KakaoAK {self.key}'})
            for wait in (1, 5, None):  # 연결 끊김·429·5xx는 두 번 더. 실패는 기억하지 않아 다음에 같은 주소를 다시 부른다
                self.calls += 1
                time.sleep(0.1)
                try:
                    with urllib.request.urlopen(req, timeout=20) as r:
                        docs = json.loads(r.read()).get('documents') or []
                    break
                except (OSError, ValueError) as ex:
                    code = getattr(ex, 'code', None)
                    if wait is None or (code is not None and code not in (429, 500, 502, 503, 504)):
                        self.errors += 1
                        return None
                    time.sleep(wait)
            self.memo[address] = (float(docs[0]['y']), float(docs[0]['x'])) if docs else None
            self.misses += not docs
        return self.memo[address]


def clean_address(addr):
    """공고 공급위치(「… 141-11번지 외 3필지」, 「… 일원」)를 주소 검색이 받는 꼴로 줄인다."""
    addr = re.sub(r'\(.*?\)', ' ', addr or '')
    addr = re.sub(r'번지.*$|\s외\s*\d+\s*필지.*$|\s(일원|일대|일원\s*외).*$', '', addr)
    return re.sub(r'\s+', ' ', addr).strip()


def km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def near_area(t, area):
    return abs(t['area'] - area) <= max(area * 0.1, 5)


def is_top(*texts):
    """단지 이름·시공사 글에 상위 시공사 이름이나 브랜드가 있는지(띄어쓰기·대소문자·「-」 무시)."""
    text = re.sub(r'[\s\-·.,()]', '', ' '.join(t or '' for t in texts)).lower()
    return any(w in text for w in TOP_BUILDERS)


def votes(pool, area, year, max_age=MAX_AGE):
    """비슷한 면적 거래를 단지(이름, 법정동, 지번)마다 묶는다. max_age년 안 준공 단지이거나 분양권·입주권인 단지만."""
    groups = {}
    for t in pool:
        if not near_area(t, area):
            continue
        if t['kind'] == '매매' and t['built'] < year - max_age:
            continue
        groups.setdefault((t['apt'], t['umd'], t.get('jibun', '')), []).append(t)
    out = []
    for (apt, umd, jibun), ts in groups.items():
        presale = any(t['kind'] != '매매' for t in ts)
        out.append({'apt': apt, 'umd': umd, 'jibun': jibun, 'n': len(ts), 'presale': presale,
                    'built': None if presale else max(t['built'] for t in ts),
                    'per': statistics.median(t['price'] / t['area'] for t in ts)})
    return out


def weighted_quantile(pairs, q):
    """(값, 가중치) 목록의 가중 분위."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


def solve(a, b):
    """연립방정식 a x = b(가우스 소거, 부분 피벗)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def fit(rows, ys, lam=RIDGE):
    """특성 행(rows)과 log ㎡당 값(ys)으로 표준화 능선 회귀(절편은 벌하지 않음). 원래 단위의 계수를 낸다(값이 같은 특성은 0)."""
    k = len(rows[0])
    means = [statistics.fmean(r[j] for r in rows) for j in range(k)]
    sds = [statistics.pstdev([r[j] for r in rows]) for j in range(k)]
    use = [j for j in range(k) if sds[j] > 1e-9]
    xs = [[1.0] + [(r[j] - means[j]) / sds[j] for j in use] for r in rows]
    p = len(use) + 1
    a = [[sum(x[i] * x[j] for x in xs) + (lam if i == j and i else 0.0) for j in range(p)] for i in range(p)]
    beta = solve(a, [sum(x[i] * y for x, y in zip(xs, ys, strict=True)) for i in range(p)])
    coef = [0.0] * k
    for i, j in enumerate(use):
        coef[j] = beta[i + 1] / sds[j]
    return coef


def estimate(target, area, price, pool, year, prefix, geocode, lookup=None, umd='', households=0, top=False):
    """v2b 시세. target: 공고 단지 주소, prefix: 거래 주소 앞부분(「시도 시군구」), umd: 공고 단지 읍·면·동,
    lookup(apt, umd, jibun, built): 단지 세대수·시공사 {'households', 'builder'} 또는 None, households·top: 공고 단지 세대수와 상위 시공사 여부.
    공고 단지 좌표가 없거나, 회귀할 단지가 MIN_FIT 미만이거나, 비교 단지가 3곳 미만이면 None."""
    here = geocode(clean_address(target))
    if not here:
        return None
    cands = []
    for c in votes(pool, area, year):
        spot = geocode(f"{prefix} {c['umd']} {c['jibun']}".strip()) if c['jibun'] else None
        if not spot:
            continue
        info = lookup(c['apt'], c['umd'], c['jibun'], c['built']) if lookup and not c['presale'] else None
        hh = (info or {}).get('households') or 0
        cands.append({**c, 'km': km(here, spot), 'households': hh or None,
                      'top': is_top(c['apt'], (info or {}).get('builder', ''))})
    if len(cands) < MIN_FIT:
        return None
    known = [math.log(c['households']) for c in cands if c['households']]
    mid_hh = statistics.median(known) if known else 0.0

    def feats(c):
        return [0 if c['presale'] else max(0, year - c['built']), float(c['presale']),
                math.log(c['households']) if c['households'] else mid_hh, float(c['top']), min(c['km'], KM_CAP)]
    coef = fit([feats(c) for c in cands], [math.log(c['per']) for c in cands])
    goal = [0, 1.0, math.log(households) if households else mid_hh, float(top), 0.0]
    clipped = 0
    for c in cands:
        shift = sum(b * (g - x) for b, g, x in zip(coef, goal, feats(c), strict=True))
        clipped += abs(shift) > CLIP
        c['adj'] = c['per'] * math.exp(max(-CLIP, min(CLIP, shift)))
    for radius in RADII:
        picked = [c for c in cands if c['km'] <= radius or (umd and c['umd'].split(' ')[0] == umd)]
        if len(picked) >= 3:
            break
    else:
        return None
    pairs = [(c['adj'], math.sqrt(min(c['n'], 5)) / (0.5 + c['km'])) for c in picked]
    per = weighted_quantile(pairs, 0.5)
    market = round(per * area)
    return {'method': 'v2b', 'scope': f'같은 동과 {radius:g}km 안 {len(picked)}개 단지(보정)', 'per': per, 'market': market,
            'gain': market - price, 'rate': (market - price) / price,
            'range': (round(weighted_quantile(pairs, 0.2) * area), round(weighted_quantile(pairs, 0.8) * area)),
            'model': {'n': len(cands), 'hh_known': len(known), 'clipped': clipped,
                      'coef': {f: round(b, 4) for f, b in zip(FEATURES, coef, strict=True)}},
            'comps': [{'apt': c['apt'], 'km': round(c['km'], 1), 'built': c['built'], 'presale': c['presale'],
                       'households': c['households'], 'top': c['top'], 'n': c['n'], 'per': round(c['per'], 1),
                       'adj': round(c['adj'], 1)} for c in sorted(picked, key=lambda c: c['km'])]}


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


def pick(v1, v2b):
    """같은 단지 거래로 낸 v1(조합원 취소분·무순위)이 가장 정확하다. 그다음 v2b, v2b가 없으면 v1."""
    if v1 and v1.get('tier') == 0:
        return v1
    return v2b or v1
