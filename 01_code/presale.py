"""청약홈 새 분양·무순위 공고를 모아 공고문 조건과 주택형별 주변 시세를 계산해 02_data/latest.json으로 낸다.
공공데이터만 쓰고 개인 정보는 다루지 않는다. 신청 자격 판정과 손익 계산은 이 파일을 읽는 쪽이 한다.

사용:
  python 01_code/presale.py collect            최근 공고를 모아 02_data/latest.json을 쓴다
  python 01_code/presale.py check "단지명, 단지명"   지난 공고를 이름으로 찾아 02_data/check.json을 쓴다
  python 01_code/presale.py trades "경상북도 구미시" 202610 [단지명]   실거래(매매·분양권) 조회

환경 변수: DATA_GO_KR_KEY(공공데이터포털 일반 인증키). 공고문을 읽으려면 pdftotext(poppler-utils, poppler-data)가 있어야 한다.
인증키가 든 주소는 출력하지 않는다.
"""

import datetime as dt
import html
import http.client
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '02_data'
NOTICES = DATA / 'notices'
CACHE = Path(os.environ.get('PRESALE_CACHE') or ROOT / 'cache')
KST = dt.timezone(dt.timedelta(hours=9))
LOOKBACK_DAYS = 14
MARKET_METHOD = 'v1: 행정구역 범위(같은 단지 → 같은 동 → 같은 시·군·구) 최근 10건 ㎡당 중간값'

APPLYHOME = 'https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/'
TRADE = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade'
SILV = 'https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade'
RENT = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent'
REGION = 'https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList'
# 청약홈 상세 화면과 첨부 PDF는 브라우저가 아닌 요청을 가끔 거른다
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'}

SIDO = {
    '서울': '서울특별시', '부산': '부산광역시', '대구': '대구광역시', '인천': '인천광역시',
    '광주': '광주광역시', '대전': '대전광역시', '울산': '울산광역시', '세종': '세종특별자치시',
    '경기': '경기도', '강원': '강원특별자치도', '충북': '충청북도', '충남': '충청남도',
    '전북': '전북특별자치도', '전남': '전라남도', '경북': '경상북도', '경남': '경상남도',
    '제주': '제주특별자치도',
}
CAPITAL = {'서울특별시', '인천광역시', '경기도'}
METRO = {'부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시'}
# 청약홈 공고 상세에서 내보내지 않는 칸(견본주택 전화번호)
DROP_FIELDS = {'MDHS_TELNO'}

KINDS = [('APT', 'getAPTLttotPblancDetail', 'getAPTLttotPblancMdl'),
         ('무순위', 'getRemndrLttotPblancDetail', 'getRemndrLttotPblancMdl')]


def today_kst():
    return dt.datetime.now(KST).date()


# ---------- 공공데이터포털 ----------

def _key():
    key = os.environ.get('DATA_GO_KR_KEY', '')
    # 포털이 주는 Encoding 키를 넣어도 되게 한 번 푼다.
    return urllib.parse.unquote(key) if '%' in key else key


# 공공데이터포털은 연결이 끊기거나(Connection reset, 시간초과), 5xx를 주거나, 200에 오류 XML·빈 본문을 주는 일이 잦다.
# 포털 쪽 문제로 사례가 많아(2026-11-03 사용자 확인) 늘어나는 간격으로 여러 번 다시 받는다. 합쳐 6분쯤까지 기다린다.
RETRY_WAITS = (5, 15, 45, 90, 180)
RETRY_HTTP = {408, 429, 500, 502, 503, 504}
# 다시 받아도 그날은 안 되는 포털 오류(키 미등록, 일일 한도 초과, 서비스 없음, 접근 거부). 나머지 오류는 다시 받는다
PERMANENT = ('SERVICE_KEY_IS_NOT_REGISTERED', 'LIMITED_NUMBER_OF_SERVICE_REQUESTS', 'NO_OPENAPI_SERVICE',
             'SERVICE_ACCESS_DENIED', 'DEADLINE_HAS_EXPIRED', 'UNREGISTERED_IP')


class Transient(Exception):
    """다시 받으면 될 수 있는 응답(오류 XML, 깨진 본문)."""


def _pause(name, reason, wait):
    print(f'{name}: {reason}, {wait}초 뒤 다시', flush=True)  # 주소에 인증키가 있어 주소는 찍지 않는다
    time.sleep(wait + random.uniform(0, wait / 3))


def _open(req, name):
    for wait in (*RETRY_WAITS, None):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'ignore')[:200]
            if e.code not in RETRY_HTTP or wait is None:
                raise RuntimeError(f'{name}: HTTP {e.code} {body}') from None
            reason = f'HTTP {e.code}'
        # 응답 없이 닫거나(RemoteDisconnected) RST로 끊으면(ConnectionResetError) URLError로 감싸지지 않는다
        except (OSError, http.client.HTTPException) as e:
            if wait is None:
                raise RuntimeError(f'{name}: 연결 실패 {getattr(e, "reason", e)}') from None
            reason = f'연결 실패 {getattr(e, "reason", e)}'
        _pause(name, reason, wait)


def _get(url, params, name, parse=None):
    """요청하고 parse로 읽는다. parse가 Transient·ValueError·ParseError를 내면(오류 XML, 깨진 본문) 다시 받는다."""
    query = urllib.parse.urlencode({'serviceKey': _key(), **params})
    req = urllib.request.Request(f'{url}?{query}', headers={'User-Agent': 'presale-market'})
    for wait in (*RETRY_WAITS[:3], None):
        body = _open(req, name).decode('utf-8', 'ignore')
        time.sleep(1)  # 같은 사이트에 요청을 몰아 보내지 않는다
        if parse is None:
            return body
        try:
            return parse(body)
        except (Transient, ValueError, ET.ParseError) as ex:
            if wait is None:
                raise RuntimeError(f'{name}: 응답 이상 {str(ex)[:200]}') from None
            _pause(name, f'응답 이상 {str(ex)[:80]}', wait)


def _rtms(body):
    """실거래 API XML. 정상(resultCode 00·000)이면 root, 그날 안 되는 오류면 RuntimeError, 나머지 오류는 Transient."""
    root = ET.fromstring(body)
    code = root.findtext('.//resultCode') or root.findtext('.//returnReasonCode') or ''
    if code in ('00', '000'):
        return root
    msg = ' '.join(x for x in (root.findtext('.//resultMsg'), root.findtext('.//errMsg'), root.findtext('.//returnAuthMsg')) if x)
    if any(p in msg for p in PERMANENT):
        raise RuntimeError(f'{code} {msg}')
    raise Transient(f'{code} {msg}')


def applyhome(op, cond=None, per_page=100):
    rows, page = [], 1
    while True:
        params = {'page': page, 'perPage': per_page, 'returnType': 'JSON', **(cond or {})}
        data = _get(APPLYHOME + op, params, op, parse=json.loads)
        rows += data.get('data') or []
        if page * per_page >= data.get('matchCount', 0):
            return rows
        page += 1


def sigungu_code(name):
    body = _get(REGION, {'type': 'json', 'pageNo': 1, 'numOfRows': 10, 'flag': 'Y', 'locatadd_nm': name}, 'StanReginCd', parse=json.loads)
    data = body.get('StanReginCd') or []
    rows = [r for part in data for r in part.get('row', [])]
    exact = [r for r in rows if r.get('locatadd_nm') == name]
    return (exact or rows)[0]['region_cd'][:5] if rows else None


def _items(url, lawd_cd, yyyymm):
    """실거래 API 한 달치 item을 모두 받는다. 한 쪽 1,000건을 넘으면 다음 쪽을 받는다."""
    name, out, page = url.rsplit('/', 1)[1], [], 1
    while True:
        try:
            root = _get(url, {'LAWD_CD': lawd_cd, 'DEAL_YMD': yyyymm, 'numOfRows': 1000, 'pageNo': page}, name, parse=_rtms)
        except RuntimeError as ex:
            raise RuntimeError(f'{name}: {ex}') from None
        items = list(root.iter('item'))
        out += items
        if not items or page * 1000 >= int(root.findtext('.//totalCount') or 0):
            return out
        page += 1


def _text(it, tag):
    return (it.findtext(tag) or '').strip()


def _date(it):
    return f"{_text(it, 'dealYear')}-{int(_text(it, 'dealMonth')):02d}-{int(_text(it, 'dealDay')):02d}"


def trades(lawd_cd, yyyymm, url=TRADE):
    """아파트 매매(TRADE) 또는 분양권·입주권 전매(SILV) 실거래. 분양권은 준공 전이라 준공연도를 거래연도로 둔다."""
    out = []
    for it in _items(url, lawd_cd, yyyymm):
        if _text(it, 'cdealType'):  # 해제된 거래
            continue
        out.append({
            'apt': _text(it, 'aptNm'), 'umd': _text(it, 'umdNm'), 'jibun': _text(it, 'jibun'),
            'area': float(_text(it, 'excluUseAr') or 0),
            'price': int(_text(it, 'dealAmount').replace(',', '') or 0), 'floor': _text(it, 'floor'),
            'built': int(_text(it, 'buildYear') or _text(it, 'dealYear') or 0),
            # 분양권 API는 구분 칸을 빈칸으로 줄 때가 있다. API로 가른다
            'kind': _text(it, 'ownershipGbn') or ('분양권' if url == SILV else '매매'),
            'date': _date(it),
        })
    return out


def rents(lawd_cd, yyyymm):
    """아파트 전월세 실거래. 보증금·월세는 만원, kind는 계약 구분(신규·갱신, 빈칸이면 모름)."""
    return [{
        'apt': _text(it, 'aptNm'), 'umd': _text(it, 'umdNm'), 'area': float(_text(it, 'excluUseAr') or 0),
        'deposit': int(_text(it, 'deposit').replace(',', '') or 0), 'monthly': int(_text(it, 'monthlyRent').replace(',', '') or 0),
        'built': int(_text(it, 'buildYear') or 0), 'kind': _text(it, 'contractType'), 'floor': _text(it, 'floor'), 'date': _date(it),
    } for it in _items(RENT, lawd_cd, yyyymm)]


def settled(yyyymm, today):
    """실거래 신고 기한(계약 뒤 30일)이 넉넉히 지나 다시 받을 일이 없는 달인지. 지난달까지는 신고가 더 들어온다."""
    y, m = today.year, today.month - 2
    if m < 1:
        y, m = y - 1, m + 12
    return yyyymm <= f'{y}{m:02d}'


def month_rows(kind, code, yyyymm, today):
    """한 시·군·구 한 달 실거래. 신고가 끝난 달은 cache/에 두고 다시 받지 않는다(Actions cache가 실행 사이에 이어 준다)."""
    path = CACHE / kind / code / f'{yyyymm}.json'
    if settled(yyyymm, today) and path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    rows = trades(code, yyyymm) + trades(code, yyyymm, url=SILV) if kind == 'trade' else rents(code, yyyymm)
    if settled(yyyymm, today):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    return rows


# ---------- 주소 ----------

def split_address(addr, area_nm=''):
    """공급위치를 (시도, 시군구, 읍면동 첫 낱말)로 나눈다. 찾지 못한 칸은 ''."""
    tokens = addr.split()
    sido = ''
    # 「전남광주통합특별시」처럼 표에 없는 새 시·도도 이름 끝으로 떼어 낸다
    if tokens and (tokens[0] in SIDO.values() or tokens[0] in SIDO or re.search(r'.{2,}(특별시|광역시|특별자치시|특별자치도|도)$', tokens[0])):
        sido = SIDO.get(tokens[0], tokens[0])
        tokens = tokens[1:]
    elif area_nm in SIDO:
        sido = SIDO[area_nm]
    sgg = []
    if tokens and re.search(r'[시군구]$', tokens[0]):
        sgg.append(tokens.pop(0))
        if tokens and sgg[0].endswith('시') and tokens[0].endswith('구'):
            sgg.append(tokens.pop(0))
    umd = tokens[0] if tokens and re.search(r'(동|가|읍|면|리)$', tokens[0]) and not re.search(r'(로|길)$', tokens[0]) else ''
    return sido, ' '.join(sgg), umd


# ---------- 공고문 ----------

def notice_text(p):
    """청약홈 공고 상세 화면의 첨부 PDF(입주자모집공고)를 받아 (첫 두 쪽 -layout 글, 전체 글, PDF 주소)를 낸다. 공고 주소나 pdftotext가 없으면 None.
    상세 화면에 이 공고 번호나 첨부 주소가 없거나 받은 것이 PDF가 아니면 RuntimeError(받기 실패)."""
    url = p.get('PBLANC_URL') or ''
    if not url or not shutil.which('pdftotext'):
        return None
    page = _open(urllib.request.Request(url, headers=BROWSER), '청약홈 공고').decode('utf-8', 'ignore')
    if str(p.get('HOUSE_MANAGE_NO') or '') not in page:
        raise RuntimeError('청약홈 공고: 상세 화면 대신 다른 응답')
    m = re.search(r'https?://static\.applyhome\.co\.kr/ai/aia/getAtchmnfl\.do[^"\'\s<>]+', page)
    if not m:
        raise RuntimeError('청약홈 공고: 상세 화면에 공고문 첨부 주소가 없다')
    time.sleep(1)
    pdf_url = html.unescape(m.group())
    pdf = _open(urllib.request.Request(pdf_url, headers=BROWSER), '청약홈 공고문 PDF')
    time.sleep(1)
    if not pdf.startswith(b'%PDF'):
        raise RuntimeError(f'청약홈 공고문 PDF: PDF 대신 다른 응답({len(pdf)} B)')
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(pdf)
        f.flush()

        def text(*opts):
            return subprocess.run(['pdftotext', *opts, f.name, '-'], capture_output=True, encoding='utf-8', timeout=120, check=False).stdout
        return text('-layout', '-f', '1', '-l', '2'), text(), pdf_url


BOX_LABELS = ('주택유형', '해당지역', '기타경기', '기타지역', '규제지역여부', '재당첨제한', '전매제한', '거주의무기간', '분양가상한제', '택지유형')


def _cells(line):
    """두 칸 이상 공백으로 나눈 조각과 그 가운데 열(한글은 두 칸으로 센다)."""
    def width(s):
        return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)
    return [(width(line[:m.start()]) + width(m.group()) / 2, m.group()) for m in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)', line)]


def parse_box(text):
    """공고문 첫 쪽 「단지 주요정보」 표(pdftotext -layout 글)를 {칸 이름: 값}으로 읽는다. 표가 없으면 None.
    이름 줄 아래 줄의 조각을 가운데 열이 가장 가까운 이름에 붙인다(값이 두 줄이면 이어 붙인다)."""
    lines = text.split('\n')
    start = next((i for i, line in enumerate(lines) if '재당첨제한' in line and '전매제한' in line), None)
    if start is None:
        return None
    lines, got, i = lines[max(0, start - 8):start + 12], {}, 0
    while i < len(lines):
        names = _cells(lines[i])
        if len(names) < 2 or not all(t in BOX_LABELS for _, t in names):
            i += 1
            continue
        i += 1
        while i < len(lines):
            row = _cells(lines[i])
            if any(t in BOX_LABELS or t.startswith(('구분', '■')) for _, t in row):
                break
            for mid, t in row:
                name = min(names, key=lambda c: abs(c[0] - mid))[1]
                got[name] = (got.get(name, '') + ' ' + t).strip()[:120]
            i += 1
    return got or None


def months_of(value):
    """「6개월」「1년」「없음」 → 개월 수. 읽지 못하면 None."""
    m = re.match(r'\s*(없음|-|(\d+)\s*(개월|년))', value or '')
    if not m:
        return None
    return int(m.group(2)) * (12 if m.group(3) == '년' else 1) if m.group(2) else 0


def parse_payment(text):
    """공고문 전체 글에서 계약금 비율, 중도금 이자 방식, 중도금 대출 알선 문구를 찾는다.
    한 공고에 5%·10%·20%가 함께 나오는 일이 많다(1·2차 계약금, 옵션·확장 표). 「분양대금은 계약금(n%)」 문장이 있으면 그 값,
    없으면 처음 나오는 값(대개 공급금액표 머리글)을 쓴다. 20%를 넘는 값은 분양대금 계약금이 아니라 버린다(규칙 제60조 ②).
    「이자후불」이 한 번이라도 있으면 이자후불로 본다(보수적으로)."""
    lead = re.search(r'분양대금[^\n]{0,30}?계약금\s*\(?\s*(\d+)\s*%', text)
    rates = [int(x) for x in ([lead.group(1)] if lead else []) + re.findall(r'계약금\s*\(\s*(\d+)\s*%\s*\)', text) if int(x) <= 20]
    return {'deposit': rates[0] / 100 if rates else None,
            'mid_interest': '이자후불' if '이자후불' in text else '무이자' if '무이자' in text else None,
            'mid_loan': bool(re.search(r'(중도금\s*(대출|융자)|융자)[^\n]{0,60}(알선|협약)', text))}


def fallback_resale(p, sido):
    """공고문을 못 읽을 때의 전매제한 개월(주택법 시행령 별표 3). 규제지역·분양가상한제·공공주택지구는 수도권 3년·그 밖 1년,
    그 밖의 민간택지는 수도권·광역시 6개월(수도권 과밀억제권역 1년은 가르지 않는다), 나머지 없음."""
    capital = sido in CAPITAL
    if any(p.get(k) == 'Y' for k in ('SPECLT_RDN_EARTH_AT', 'MDAT_TRGET_AREA_SECD', 'PARCPRC_ULS_AT', 'PUBLIC_HOUSE_EARTH_AT')):
        return 36 if capital else 12
    return 6 if capital or sido in METRO else 0


def movein_months(p):
    """당첨자 발표 달부터 입주예정월까지 개월 수(0 아래는 0). 읽지 못하면 None."""
    ym = str(p.get('MVN_PREARNGE_YM') or '')
    base = str(p.get('PRZWNER_PRESNATN_DE') or p.get('RCRIT_PBLANC_DE') or '')
    if not re.fullmatch(r'\d{6}', ym) or not re.match(r'\d{4}-\d{2}', base):
        return None
    return max(0, (int(ym[:4]) - int(base[:4])) * 12 + int(ym[4:]) - int(base[5:7]))


def read_notice(p, sido):
    """공고문에서 조건을 읽는다. 못 읽은 칸은 None으로 두고(읽는 쪽이 자기 기본값을 쓴다), 전매제한만 법령 표 값을 따로 준다."""
    got, error = None, ''
    # 해외 러너에서 공고문 받기가 하루 한두 건씩 실패한다. 30초 뒤 한 번 더 받는다
    for wait in (30, None):
        try:
            got = notice_text(p)
            error = ''
            break
        except (RuntimeError, OSError, subprocess.SubprocessError) as ex:
            error = str(ex)
            if wait is not None:
                time.sleep(wait)
    box = (parse_box(got[0]) if got else None) or {}
    pay = parse_payment(got[1]) if got else {}
    return {
        'read': bool(box), 'fetch_error': error, 'box': box,
        'resale_months': months_of(box.get('전매제한', '')),
        'resale_fallback_months': fallback_resale(p, sido),
        'residence_months': months_of(box.get('거주의무기간', '')),
        'movein_months': movein_months(p),
        'deposit': pay.get('deposit'),
        'deposit_found': sorted(set(re.findall(r'계약금\s*\(\s*(\d+)\s*%\s*\)', got[1]))) if got else [],
        'mid_interest': pay.get('mid_interest'),
        'mid_loan': pay.get('mid_loan', False),
        'regulated': any(w in box.get('규제지역여부', '') for w in ('투기', '조정', '과열'))
        or p.get('SPECLT_RDN_EARTH_AT') == 'Y' or p.get('MDAT_TRGET_AREA_SECD') == 'Y',
        'region_text': ' '.join(box.get(k, '') for k in ('해당지역', '기타경기', '기타지역')).strip(),
        'pdf_url': got[2] if got else '',
    }


# ---------- 시세 비교 (v1) ----------

def area_of(house_ty):
    m = re.match(r'0*(\d+(?:\.\d+)?)', str(house_ty or ''))
    return float(m.group(1)) if m else 0.0


def first(text):
    return (text.split() or [''])[0]


def same_complex(apt, name):
    """실거래 단지명이 공고 단지명과 같은 단지인지. 괄호(「조합원 취소분」 등)와 띄어쓰기를 빼고 한쪽이 다른 쪽을 품으면 같다고 본다."""
    def norm(s):
        return re.sub(r'\(.*?\)|\s', '', s or '')
    a, n = norm(apt), norm(name)
    return len(a) >= 4 and len(n) >= 4 and (a in n or n in a)


def compare(area, price, pool, umd, this_year, tier=None, name=''):
    """분양가(만원)를 비슷한 전용면적의 최근 실거래와 비교한다. 비교할 거래가 3건(같은 단지는 2건) 미만이면 None. tier를 주면 그 범위만 본다."""
    # 이미 짓고 있는 단지의 조합원 취소분·무순위는 그 단지 거래가 가장 정확하다. 그다음이 근처 분양권·입주권, 5년 이내 신축 매매다.
    near = [t for t in pool if abs(t['area'] - area) <= max(area * 0.1, 5)]
    dong = [t for t in near if umd and first(t['umd']) == umd]
    presale = [t for t in near if t['kind'] != '매매']
    newish = [t for t in near if t['kind'] == '매매' and t['built'] >= this_year - 5]
    tiers = [
        ('같은 단지', [t for t in dong if same_complex(t.get('apt'), name)]),
        ('같은 읍·면·동 분양권·입주권', [t for t in presale if t in dong]),
        ('같은 읍·면·동, 5년 이내 단지', [t for t in newish if t in dong]),
        ('같은 시·군·구 분양권·입주권', presale),
        ('같은 시·군·구, 5년 이내 단지', newish),
        ('같은 읍·면·동, 연식 무관', dong),
    ]
    for i, (scope, picked) in enumerate(tiers):
        if tier is not None and i != tier:
            continue
        if len(picked) >= (2 if i == 0 else 3):
            picked = sorted(picked, key=lambda t: t['date'], reverse=True)[:10]
            pers = [t['price'] / t['area'] for t in picked]
            q = statistics.quantiles(pers, n=4)
            return priced(statistics.median(pers), area, price, {'scope': scope, 'trades': picked, 'tier': i, 'q': (q[0], q[2])})
    return None


def priced(per, area, price, extra):
    market = round(per * area)
    return {**extra, 'per': per, 'market': market, 'gain': market - price, 'rate': (market - price) / price}


def align_types(types):
    """같은 공고 안에서 더 넓은 범위로 비교된 주택형은 가장 가까운 범위로 비교된 주택형의 평단을 쓴다."""
    rated = [t for t in types if t['cmp']]
    if not rated:
        return
    anchor = min(rated, key=lambda t: (t['cmp']['tier'], -len(t['cmp']['trades'])))['cmp']
    for t in rated:
        if t['cmp']['tier'] > anchor['tier']:
            t['cmp'] = priced(anchor['per'], t['area'], t['price'], {
                'scope': f"{anchor['scope']}(다른 주택형 평단 적용)", 'trades': anchor['trades'], 'tier': anchor['tier'],
                'q': anchor['q'], 'months': anchor.get('months'), 'borrowed': True})


def jeonse(area, pool, umd, this_year):
    """같은 범위 5년 이내 단지의 전세(월세 0, 갱신 제외) 평단 중위값 × 전용면적. 3건 미만이면 None."""
    near = [t for t in pool if t['monthly'] == 0 and t['kind'] != '갱신' and t['built'] >= this_year - 5
            and abs(t['area'] - area) <= max(area * 0.1, 5)]
    for scope, picked in (('같은 읍·면·동', [t for t in near if umd and first(t['umd']) == umd]), ('같은 시·군·구', near)):
        if len(picked) >= 3:
            return {'deposit': round(statistics.median(t['deposit'] / t['area'] for t in picked) * area), 'n': len(picked), 'scope': scope}
    return None


class TradeCache:
    def __init__(self, today):
        self.today, self.codes, self.months = today, {}, {}

    def pool(self, sido, sgg, months, skip=0, kind='trade'):
        """최근 months개월(skip개월 앞부터) 실거래. kind='trade'는 매매와 분양권, 'rent'는 전월세."""
        name = f'{sido} {sgg}'.strip()
        if name not in self.codes:
            self.codes[name] = sigungu_code(name)
        code = self.codes[name]
        if not code:
            return None, name
        out = []
        y, m = self.today.year, self.today.month
        for i in range(skip + months):
            key = (kind, code, f'{y}{m:02d}')
            if i >= skip:
                if key not in self.months:
                    self.months[key] = month_rows(*key, self.today)
                out += self.months[key]
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return out, name

    def rents(self, sido, sgg, months):
        """전월세 실거래. 조회가 실패하면 None이라 전세 값만 빠진다."""
        try:
            return self.pool(sido, sgg, months, kind='rent')[0]
        except RuntimeError as ex:
            print(f'{sido} {sgg}: 전월세 조회 실패 {ex}')
            return None


def market_types(p, models, sido, sgg, umd, today, cache, notes):
    """주택형마다 분양가와 v1 시세 비교, 전세 추정, 이전 6개월 대비 흐름."""
    pool, name = cache.pool(sido, sgg, 6)
    if pool is None:
        notes.append(f'법정동코드 「{name}」 미확인: 실거래 비교 불가')
        return []
    rent_pool = cache.rents(sido, sgg, 6)
    if rent_pool is None:
        notes.append('전월세 실거래 조회 실패: 전세 추정 없음')
    house = p.get('HOUSE_NM', '')
    # 최근 6개월에 같은 단지 거래가 한 건이라도 있으면 이미 거래되는 단지라, 같은 단지 거래는 12개월까지 넓혀 먼저 찾는다
    known = any(same_complex(t.get('apt'), house) and umd and first(t['umd']) == umd for t in pool)
    types = []
    for m in models:
        area = area_of(m.get('HOUSE_TY'))
        price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
        if not area or not price:
            continue
        c = compare(area, price, pool, umd, today.year, name=house)
        if c:
            c['months'] = 6
        if known and (not c or c['tier'] > 0):
            same = compare(area, price, cache.pool(sido, sgg, 12)[0], umd, today.year, tier=0, name=house)
            if same:
                c = {**same, 'months': 12}
        if not c:  # 6개월로 모자라면 12개월로 넓힌다
            c = compare(area, price, cache.pool(sido, sgg, 12)[0], umd, today.year, name=house)
            if c:
                c['months'] = 12
        gen, spe = int(m.get('SUPLY_HSHLDCO') or 0), int(m.get('SPSPLY_HSHLDCO') or 0)
        types.append({'ty': m.get('HOUSE_TY'), 'area': area, 'price': price, 'cmp': c, 'gen': gen, 'total': gen + spe,
                      'first': int(m.get('LFE_FRST_HSHLDCO') or 0), 'supply': float(m.get('SUPLY_AR') or 0)})
    align_types(types)
    old_pool = []
    if any(t['cmp'] for t in types):
        try:  # 시세 흐름은 참고 숫자라 조회가 실패해도 계속한다
            old_pool = cache.pool(sido, sgg, 6, skip=6)[0] or []
        except RuntimeError as ex:
            notes.append(f'이전 6개월 실거래 조회 실패: 시세 흐름 미산출({ex})')
    for t in types:
        c = t['cmp']
        t['jeonse'] = jeonse(t['area'], rent_pool, umd, today.year) if rent_pool is not None else None
        if not c:
            continue
        old = compare(t['area'], t['price'], old_pool, umd, today.year, tier=c['tier'], name=house) \
            if c.get('months') == 6 and not c.get('borrowed') else None
        c['trend'] = c['per'] / old['per'] - 1 if old else None
    return types


# ---------- 모으기 ----------

def key_of(p, kind):
    return f"{kind}:{p['HOUSE_MANAGE_NO']}:{p['PBLANC_NO']}"


def notice_of(p, kind, sido):
    """공고문 읽은 결과. 받은 공고문은 02_data/notices/에 두고 다시 받지 않는다(받기 실패는 두지 않아 다음 실행이 다시 받는다)."""
    path = NOTICES / (key_of(p, kind).replace(':', '_') + '.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    got = read_notice(p, sido)
    if not got['fetch_error'] and got['pdf_url']:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding='utf-8')
    return got


def build(p, kind, mdl, today, cache):
    """공고 한 건의 공개 자료 묶음. 신청 자격은 판정하지 않는다."""
    sido, sgg, umd = split_address(p.get('HSSPLY_ADRES', ''), p.get('SUBSCRPT_AREA_CODE_NM', ''))
    end = p.get('SUBSCRPT_RCEPT_ENDDE' if kind == '무순위' else 'RCEPT_ENDDE')
    rent = str(p.get('RENT_SECD') or '0') != '0'
    models = applyhome(mdl, {'cond[HOUSE_MANAGE_NO::EQ]': p['HOUSE_MANAGE_NO'], 'cond[PBLANC_NO::EQ]': p['PBLANC_NO']})
    out = {'key': key_of(p, kind), 'kind': kind, 'detail': {k: v for k, v in p.items() if k not in DROP_FIELDS},
           'models': models, 'sido': sido, 'sigungu': sgg, 'umd': umd,
           'closed': bool(end) and str(end) < today.isoformat(), 'rent': rent, 'notes': [], 'types': []}
    # 공공임대의 공급금액은 분양가가 아니라 임대보증금이라 시세와 견주지 않는다
    if rent:
        out['notes'].append('임대 공고: 시세 비교 안 함')
        return out
    out['notice'] = notice_of(p, kind, sido)
    try:
        out['types'] = market_types(p, models, sido, sgg, umd, today, cache, out['notes'])
    except RuntimeError as ex:
        out['notes'].append(f'실거래 조회 실패: {ex}')
    return out


def write(path, notices, today, errors):
    doc = {'schema': 1, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
           'today': today.isoformat(), 'lookback_days': LOOKBACK_DAYS, 'market_method': MARKET_METHOD,
           'notices': notices, 'errors': errors}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')


def collect(found, today, path):
    cache, notices, errors = TradeCache(today), [], []
    for p, kind, mdl in found:
        try:
            notices.append(build(p, kind, mdl, today, cache))
        except RuntimeError as ex:
            errors.append(f"{p.get('HOUSE_NM')}: {ex}")
            print(f"{p.get('HOUSE_NM')}: 조회 실패 {ex}")
    write(path, notices, today, errors)
    print(f'공고 {len(notices)}건, 실패 {len(errors)}건 → {path.relative_to(ROOT)}')


def cmd_collect():
    today = today_kst()
    since = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    found = [(p, kind, mdl) for kind, op, mdl in KINDS for p in applyhome(op, {'cond[RCRIT_PBLANC_DE::GTE]': since})]
    collect(found, today, DATA / 'latest.json')


def cmd_check(names):
    """지난 공고를 이름으로 찾아 같은 묶음을 02_data/check.json에 쓴다(받는 쪽의 미리보기와 대조용)."""
    names = [n.strip() for a in names for n in a.split(',') if n.strip()]
    found = [(p, kind, mdl) for name in names for kind, op, mdl in KINDS
             for p in applyhome(op, {'cond[HOUSE_NM::LIKE]': name})]
    collect(found, today_kst(), DATA / 'check.json')


def cmd_trades(args):
    code = sigungu_code(args[0])
    for url in (TRADE, SILV):
        for t in trades(code, args[1], url=url):
            if len(args) < 3 or args[2] in t['apt']:
                print(f"{t['date']} {t['kind']} {t['apt']} ({t['umd']} {t['jibun']}, {t['built']}년) {t['floor']}층 전용 {t['area']}㎡ {t['price']:,}만원")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'collect':
        cmd_collect()
    elif cmd == 'check':
        cmd_check(argv[2:] or [os.environ.get('NAMES', '')])
    elif cmd == 'trades':
        cmd_trades(argv[2:])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
