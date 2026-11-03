"""시세 계산 v2a: 공고 단지에서 가까운 신축·분양권 단지를 단지마다 한 표로 세어 거리 가중 중간값과 범위를 낸다.

위치는 카카오 로컬 주소 검색으로 실행 안에서만 얻는다. 카카오 정책상 좌표·주소 결과를 저장할 수 없어
이 모듈은 좌표를 메모리에만 두고 파일·로그에 쓰지 않는다. 결과에는 단지 이름과 0.1km로 반올림한 거리만 남긴다.
환경 변수: KAKAO_REST_API_KEY.
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
RADII = (1.5, 3.0, 5.0)  # km. 비교 단지가 3곳이 될 때까지 넓힌다
NEW_YEARS = 10  # 이 햇수 안에 준공한 단지와 분양권만 비교한다
VERY_NEW_YEARS = 3  # 이 안의 신축·분양권이 3곳 이상이면 그것만 쓴다
METHOD = 'v2a: 1.5·3·5km 안 10년 이내 단지·분양권, 단지마다 한 표, 거리 가중 중간값과 20·80% 범위'


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


def votes(pool, area, year):
    """비슷한 면적 거래를 단지(이름, 법정동, 지번)마다 묶는다. 10년 이내 준공이거나 분양권·입주권인 단지만."""
    groups = {}
    for t in pool:
        if not near_area(t, area):
            continue
        presale = t['kind'] != '매매'
        if not presale and t['built'] < year - NEW_YEARS:
            continue
        groups.setdefault((t['apt'], t['umd'], t.get('jibun', '')), []).append(t)
    out = []
    for (apt, umd, jibun), ts in groups.items():
        out.append({'apt': apt, 'umd': umd, 'jibun': jibun, 'n': len(ts), 'built': max(t['built'] for t in ts),
                    'presale': any(t['kind'] != '매매' for t in ts),
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


def estimate(target, area, price, pool, year, prefix, geocode):
    """target: 공고 단지 주소. prefix: 거래 주소 앞부분(「시도 시군구」). 비교 단지가 3곳 미만이면 None."""
    here = geocode(clean_address(target))
    if not here:
        return None
    cands = []
    for c in votes(pool, area, year):
        spot = geocode(f"{prefix} {c['umd']} {c['jibun']}".strip()) if c['jibun'] else None
        if spot:
            cands.append({**c, 'km': km(here, spot)})
    for radius in RADII:
        picked = [c for c in cands if c['km'] <= radius]
        if len(picked) >= 3:
            break
    else:
        return None
    newest = [c for c in picked if c['presale'] or c['built'] >= year - VERY_NEW_YEARS]
    if len(newest) >= 3:
        picked = newest
    pairs = [(c['per'], math.sqrt(min(c['n'], 5)) / (0.5 + c['km'])) for c in picked]
    per = weighted_quantile(pairs, 0.5)
    market = round(per * area)
    return {'scope': f'{radius:g}km 안 {len(picked)}개 단지', 'per': per, 'market': market,
            'gain': market - price, 'rate': (market - price) / price,
            'range': (round(weighted_quantile(pairs, 0.2) * area), round(weighted_quantile(pairs, 0.8) * area)),
            'comps': [{'apt': c['apt'], 'km': round(c['km'], 1), 'built': c['built'], 'presale': c['presale'],
                       'n': c['n'], 'per': round(c['per'], 1)} for c in sorted(picked, key=lambda c: c['km'])]}
