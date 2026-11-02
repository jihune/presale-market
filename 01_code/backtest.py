"""시세 계산 백테스트. 공고 때 있던 자료로 낸 시세가 공고 뒤 그 단지 분양권 거래가와 얼마나 맞는지 잰다.

판정 규칙 (돌리기 전에 정해 커밋한다. 결과를 본 뒤 바꾸면 새 항목으로 적는다)
- 대상: backtest_data.py가 받은 2023-01-01 ~ 2025-06-30 영남(대구·경북·부산·울산·경남) 민영 분양 공고(임대 제외).
- 정답: 주택형마다, 공고일 180일 뒤부터 540일 뒤까지 같은 시·군·구 분양권·입주권 거래 가운데 단지명이 공고 단지와 같고
  (same_complex) 전용면적이 ±10%(최소 5㎡) 안인 거래가 3건 이상이면 그 ㎡당 중간값 × 전용면적. 3건 미만이면 정답 없음.
- 예측: 공고일 전 거래만 쓴다(같은 시·군·구, 거래일 < 공고일). v1은 presale.compare를 공고일 앞 6개월(모자라면 12개월) 거래로 부른다.
- 오차: 주택형마다 예측 ÷ 정답 − 1. 공고마다 그 공고 주택형 오차의 중간값 하나로 센다(주택형이 많은 공고가 더 세지 않게).
- 지표(방법마다): 정답이 있는 공고 수 N, 그 가운데 예측이 있는 비율(coverage), 절대 오차 중간값 MdAPE, 절대 오차 80% 분위 P80,
  부호 있는 오차 중간값(bias).
- 대조 1(섞기): 같은 시·도 안에서 예측 ㎡당 값을 다른 공고 것과 무작위로 바꿔 MdAPE를 200번 잰다(seed 20261103).
  관측 MdAPE 이하가 나온 비율을 낸다. 이 비율이 0.05를 넘으면 그 방법은 「신호 없음」이다.
- 대조 2(심은 결함): 예측을 모두 1.10배 한 사본의 MdAPE가 원래보다 커야 지표가 살아 있다. 아니면 CONTROL_FAIL.
- 판정:
  R1 v1 정밀도: v1 P80 ≤ 0.025(4억원 집에서 1,000만원, 지금 알림 「중」 기준)이면 V1_GRADES_OK, 아니면 V1_GRADES_NOT_OK.
  R2 v2 채택(v2 결과가 있을 때): v2 MdAPE ≤ v1 MdAPE − 0.02이고 v2 coverage ≥ v1 coverage − 0.10이면 ADOPT_V2, 아니면 KEEP_V1.
  R3 알림 문턱: 채택한 방법의 P80을 「등급을 줄 최소 차익(분양가 대비 비율)」로 result.json에 적는다.
- 출력: <출력 폴더>/<방법>-errors.tsv(공고마다), <출력 폴더>/result.json, 마지막 줄 `VERDICT ...`.

사용: python 01_code/backtest.py <자료 폴더> <출력 폴더>
  v2는 카카오 좌표가 필요해 환경 변수 KAKAO_REST_API_KEY가 있을 때만 잰다(Actions). v2도 v1과 같은 오차 정의(주택형마다)를 쓴다.
"""

import datetime as dt
import json
import random
import statistics
import sys
from pathlib import Path

import presale
import v2

SEED = 20261103
SHUFFLES = 200
P80_V1_OK = 0.025
V2_MARGIN, COVERAGE_SLACK = 0.02, 0.10


def load_rows(data, code, months):
    rows = []
    for ym in months:
        f = data / 'trades' / code / f'{ym}.json'
        if f.exists():
            rows += json.loads(f.read_text(encoding='utf-8'))
    return rows


def months_between(start, end):
    """start, end(date) 사이 달 YYYYMM 목록(양끝 포함)."""
    k, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    out = []
    while k <= last:
        out.append(f'{k // 12}{k % 12 + 1:02d}')
        k += 1
    return out


def near_area(t, area):
    return abs(t['area'] - area) <= max(area * 0.1, 5)


def truth_of(n, area, data):
    d = dt.date.fromisoformat(n['detail']['RCRIT_PBLANC_DE'])
    lo, hi = d + dt.timedelta(days=180), d + dt.timedelta(days=540)
    rows = [t for t in load_rows(data, n['code'], months_between(lo, hi))
            if t['kind'] != '매매' and lo.isoformat() <= t['date'] <= hi.isoformat()
            and presale.same_complex(t['apt'], n['detail'].get('HOUSE_NM', '')) and near_area(t, area)]
    if len(rows) < 3:
        return None
    return statistics.median(t['price'] / t['area'] for t in rows)


def v1_of(n, area, price, data):
    d = dt.date.fromisoformat(n['detail']['RCRIT_PBLANC_DE'])
    for back in (6, 12):
        start = d - dt.timedelta(days=31 * back)
        pool = [t for t in load_rows(data, n['code'], months_between(start, d)) if t['date'] < d.isoformat()
                and t['date'] >= start.isoformat()]
        c = presale.compare(area, price, pool, n['umd'], d.year, name=n['detail'].get('HOUSE_NM', ''))
        if c:
            return c['per']
    return None


def notice_rows(notices, data, predict):
    """공고마다 (key, 시·도, 예측 ㎡당, 정답 ㎡당, 오차, 주택형 수). 정답이 없는 공고는 뺀다."""
    out = []
    for n in notices:
        if not n.get('code'):
            continue
        errs, preds, truths = [], [], []
        for m in n['models']:
            area = presale.area_of(m.get('HOUSE_TY'))
            price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
            if not area or not price:
                continue
            truth = truth_of(n, area, data)
            if truth is None:
                continue
            pred = predict(n, area, price)
            truths.append(truth)
            if pred is not None:
                preds.append(pred)
                errs.append(pred / truth - 1)
        if truths:
            key = f"{n['detail']['HOUSE_MANAGE_NO']}:{n['detail']['PBLANC_NO']}"
            out.append({'key': key, 'name': n['detail'].get('HOUSE_NM', ''), 'sido': n['sido'], 'date': n['detail']['RCRIT_PBLANC_DE'],
                        'pred': statistics.median(preds) if preds else None, 'truth': statistics.median(truths),
                        'err': statistics.median(errs) if errs else None, 'types': len(truths)})
    return out


def metrics(rows):
    errs = [r['err'] for r in rows if r['err'] is not None]
    abs_errs = sorted(abs(e) for e in errs)
    return {'N': len(rows), 'predicted': len(errs), 'coverage': len(errs) / len(rows) if rows else 0,
            'MdAPE': statistics.median(abs_errs) if abs_errs else None,
            'P80': abs_errs[min(len(abs_errs) - 1, int(0.8 * len(abs_errs)))] if abs_errs else None,
            'bias': statistics.median(errs) if errs else None}


def shuffle_share(rows, observed):
    rng = random.Random(SEED)
    rated = [r for r in rows if r['err'] is not None]
    hits = 0
    for _ in range(SHUFFLES):
        errs = []
        for sido in {r['sido'] for r in rated}:
            group = [r for r in rated if r['sido'] == sido]
            preds = [r['pred'] for r in group]
            rng.shuffle(preds)
            errs += [abs(p / r['truth'] - 1) for p, r in zip(preds, group, strict=True)]
        hits += statistics.median(errs) <= observed
    return hits / SHUFFLES


def write_tsv(path, rows):
    cols = ['key', 'name', 'sido', 'date', 'types', 'pred', 'truth', 'err']
    lines = ['\t'.join(cols)] + ['\t'.join('' if r[c] is None else str(r[c]) for c in cols) for r in rows]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def v2_of(n, area, price, data, geocode):
    d = dt.date.fromisoformat(n['detail']['RCRIT_PBLANC_DE'])
    start = d - dt.timedelta(days=365)
    pool = [t for t in load_rows(data, n['code'], months_between(start, d)) if start.isoformat() <= t['date'] < d.isoformat()]
    got = v2.estimate(n['detail'].get('HSSPLY_ADRES', ''), area, price, pool, d.year, f"{n['sido']} {n['sigungu']}".strip(), geocode)
    return got['per'] if got else None


def main(data, out):
    data, out = Path(data), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    notices = json.loads((data / 'notices.json').read_text(encoding='utf-8'))
    result, verdict = {}, []
    v1 = notice_rows(notices, data, lambda n, area, price: v1_of(n, area, price, data))
    write_tsv(out / 'v1-errors.tsv', v1)
    m1 = metrics(v1)
    m1['shuffle_share'] = shuffle_share(v1, m1['MdAPE'])
    defect = [{**r, 'err': None if r['err'] is None else (1 + r['err']) * 1.10 - 1} for r in v1]
    m1['seeded_defect_MdAPE'] = metrics(defect)['MdAPE']
    result['v1'] = m1
    control_ok = m1['seeded_defect_MdAPE'] > m1['MdAPE']
    verdict.append('CONTROL_OK' if control_ok else 'CONTROL_FAIL')
    if m1['shuffle_share'] > 0.05:
        verdict.append('V1_NO_SIGNAL')
    verdict.append('V1_GRADES_OK' if m1['P80'] <= P80_V1_OK else 'V1_GRADES_NOT_OK')
    adopted = m1
    geocode = v2.Geocoder()
    if geocode.key:
        rows2 = notice_rows(notices, data, lambda n, area, price: v2_of(n, area, price, data, geocode))
        write_tsv(out / 'v2-errors.tsv', rows2)
        m2 = metrics(rows2)
        m2['geocode_calls'], m2['geocode_misses'] = geocode.calls, geocode.misses
        m2['shuffle_share'] = shuffle_share(rows2, m2['MdAPE']) if m2['MdAPE'] is not None else None
        result['v2'] = m2
        adopt = m2['MdAPE'] is not None and m2['MdAPE'] <= m1['MdAPE'] - V2_MARGIN and m2['coverage'] >= m1['coverage'] - COVERAGE_SLACK
        verdict.append('ADOPT_V2' if adopt else 'KEEP_V1')
        adopted = m2 if adopt else m1
    result['alert_min_gap_ratio'] = adopted['P80']
    result['verdict'] = verdict
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    for name, m in result.items():
        if isinstance(m, dict):
            print(name, json.dumps(m, ensure_ascii=False))
    print('VERDICT ' + ' '.join(verdict))


if __name__ == '__main__':
    main(*sys.argv[1:])
