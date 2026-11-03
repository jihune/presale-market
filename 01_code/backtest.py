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

판정 규칙 2회차 (2026-11-03, v2b를 짜고 돌리기 전에 커밋한다. 1회차 항목은 위에 그대로 두고 2회차 실행은 이 항목을 따른다)
- 대상, 정답, 예측에 쓰는 자료(공고일 전 거래만), 오차, 지표: 1회차와 같다.
- 방법: v1(1회차와 같다)과 v2b(v2.py의 연식·세대수·시공사·분양권·거리 보정). v2a는 1회차에 기각돼 다시 재지 않는다.
  v2b가 값을 내지 못하는 주택형(공고 단지 좌표 실패, 비교 단지 부족)은 v1 값을 쓰고 그 주택형 수를 fallback으로 적는다.
  그 주택형도 v2b 예측으로 센다(알림에서도 같은 식으로 쓰기 때문이다).
- 대조 1(섞기): 1회차와 같고 방법마다 잰다.
- 대조 2(심은 결함, 1회차 것을 고침): 방법마다 예측을 모두 1.10배 한 사본과 0.90배 한 사본의 MdAPE를 잰다. 둘 가운데 적어도 하나가
  원래 MdAPE보다 커야 그 방법의 지표가 살아 있다. v1과 v2b가 모두 살아 있으면 CONTROL_OK, 아니면 CONTROL_FAIL.
- 판정:
  R1: 1회차와 같다.
  R2b v2b 채택: v2b MdAPE ≤ v1 MdAPE − 0.02이고 v2b coverage ≥ v1 coverage − 0.10이면 ADOPT_V2B, 아니면 KEEP_V1.
      v2b 섞기 비율이 0.05를 넘으면 V2B_NO_SIGNAL을 더하고 채택하지 않는다.
  R3: 채택한 방법의 P80을 alert_min_gap_ratio로, MdAPE와 함께 result.json에 적는다. 알림 쪽은 시세 × (1 − P80)으로 출구 손익을 계산한다.
- 판정에 쓰지 않고 함께 적는 숫자: v2b 범위(보정한 비교 단지 값의 가중 20·80% 분위)가 정답을 품은 공고 비율, 좌표 호출·결과 없음·오류 수,
  K-apt 기본정보 호출 수와 세대수를 모르는 비교 단지 수, 회귀를 세운 주택형 수.
- 출력: 1회차와 같은 파일에 v2b-errors.tsv를 더한다(v2-errors.tsv는 1회차 v2a 결과로 남긴다). 마지막 줄 `VERDICT ...`.

판정 규칙 3회차 (2026-11-03, 검증 묶음 결과를 보기 전에 커밋한다. 2회차 결과 KEEP_V1 뒤 사용자가 3회차를 골랐다)
- 까닭: 2회차 뒤 영남 자료를 세션이 직접 보니 정답(공고 뒤 분양권 거래가)이 분양가와 거의 같았고(분양가 ÷ 정답 − 1의 중간값 −1.0%),
  주변 시세 ÷ 분양가는 실제 웃돈을 조금만 설명했다(공고 단위 기울기 0.055, 상관 0.14). 그래서 시세를 「분양가 × (1 + 예상 웃돈)」으로 낸다.
- 방법: v1(그대로), v0(분양가 × e^a0, 주변 시세를 쓰지 않는 기준), v2c(분양가 × e^(a + b·x), x = log(v1 ÷ 분양가)를 −0.5 ~ 0.3에서 자름,
  v1이 없으면 v0). v0·v2c도 같은 단지 거래로 낸 v1(조합원 취소분·무순위)이 있으면 그것을 쓴다. 계수는 fit_v2c.py로 영남 자료에서 맞춰
  v2.py의 V2C에 고정했다(이 커밋). 영남은 계수를 맞춘 자료라 결과를 적기만 하고 판정에 쓰지 않는다.
- 판정 묶음: 검증 묶음(backtest_data.py 「검증」: 대전·세종·충북·충남·광주·전남·전북·강원, 2023-01-01 ~ 2025-06-30 민영 분양).
  대상·정답·예측 자료·오차·지표는 1회차와 같다.
- 대조: 방법마다 섞기(1회차와 같음, 0.05 이하)와 심은 결함(2회차와 같음, ×1.10·×0.90 가운데 하나라도 MdAPE가 커짐). 모두 통과해야 CONTROL_OK.
- 판정(검증 묶음에서):
  R2c-1 후보 고르기: v2c MdAPE < v0 MdAPE이면 v2c, 아니면 v0(같으면 단순한 v0).
  R2c-2 채택: 고른 후보의 MdAPE ≤ v1 MdAPE − 0.02, coverage ≥ v1 coverage − 0.10, 섞기 비율 ≤ 0.05, 심은 결함 대조 통과면 ADOPT_V2C 또는 ADOPT_V0,
        아니면 KEEP_V1.
  R3: 채택한 방법의 검증 묶음 P80을 alert_min_gap_ratio로, MdAPE·N과 함께 adopted에 적는다(알림 쪽은 시세 × (1 − P80)).
- 출력: <출력 폴더>(영남)와 <출력 폴더>/holdout(검증)에 방법마다 <방법>-errors.tsv, <출력 폴더>/result.json에 두 묶음 지표와 판정. 마지막 줄 `VERDICT ...`.

사용: python 01_code/backtest.py <영남 자료 폴더> <출력 폴더> [검증 자료 폴더]
  3회차 코드다. 1회차(v2a)·2회차(v2b)를 다시 재려면 그 회차 커밋(bf6f06b, 218531e)의 이 파일을 쓴다.
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
            return c
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
                errs.append(pred['per'] / truth - 1)
        if truths:
            key = f"{n['detail']['HOUSE_MANAGE_NO']}:{n['detail']['PBLANC_NO']}"
            ranged = [p for p in preds if p.get('lo') is not None]
            out.append({'key': key, 'name': n['detail'].get('HOUSE_NM', ''), 'sido': n['sido'], 'date': n['detail']['RCRIT_PBLANC_DE'],
                        'pred': statistics.median(p['per'] for p in preds) if preds else None, 'truth': statistics.median(truths),
                        'err': statistics.median(errs) if errs else None, 'types': len(truths),
                        'lo': statistics.median(p['lo'] for p in ranged) if ranged else None,
                        'hi': statistics.median(p['hi'] for p in ranged) if ranged else None,
                        'fallback': sum(bool(p.get('fallback')) for p in preds)})
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
    cols = ['key', 'name', 'sido', 'date', 'types', 'pred', 'truth', 'err', 'lo', 'hi', 'fallback']
    lines = ['\t'.join(cols)] + ['\t'.join('' if r[c] is None else str(r[c]) for c in cols) for r in rows]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def v2c_of(n, area, price, data, slope=True):
    """v2c(slope=True)·v0 예측(㎡당과 범위). 같은 단지 거래로 낸 v1이 있으면 그것을 쓴다."""
    one = v1_of(n, area, price, data)
    if one and one.get('tier') == 0:
        return {'per': one['per'], 'fallback': True}
    c = v2.estimate_c(one, area, price, slope=slope)
    return {'per': c['per'], 'lo': c['range'][0] / area, 'hi': c['range'][1] / area}


def defect_mdape(rows, factor):
    return metrics([{**r, 'err': None if r['err'] is None else (1 + r['err']) * factor - 1} for r in rows])['MdAPE']


def measure(rows):
    """지표, 섞기 대조, 심은 결함 대조(×1.10·×0.90 가운데 하나라도 MdAPE가 커져야 산다)."""
    m = metrics(rows)
    m['shuffle_share'] = shuffle_share(rows, m['MdAPE']) if m['MdAPE'] is not None else None
    m['seeded_defect_MdAPE'] = {'x1.10': defect_mdape(rows, 1.10), 'x0.90': defect_mdape(rows, 0.90)}
    m['defect_alive'] = m['MdAPE'] is not None and any(v > m['MdAPE'] for v in m['seeded_defect_MdAPE'].values())
    return m


def evaluate(notices, data, out):
    """한 묶음에서 v1·v0·v2c를 재고 방법마다 TSV를 쓴다."""
    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for name, predict in (('v1', lambda n, area, price: v1_of(n, area, price, data)),
                          ('v0', lambda n, area, price: v2c_of(n, area, price, data, slope=False)),
                          ('v2c', lambda n, area, price: v2c_of(n, area, price, data))):
        rows = notice_rows(notices, data, predict)
        write_tsv(out / f'{name}-errors.tsv', rows)
        m = measure(rows)
        ranged = [r for r in rows if r['lo'] is not None]
        m['range_hit'] = sum(r['lo'] <= r['truth'] <= r['hi'] for r in ranged) / len(ranged) if ranged else None
        m['fallback_types'] = sum(r['fallback'] for r in rows)
        got[name] = m
    return got


def main(data, out, holdout=None):
    data, out = Path(data), Path(out)
    result = {'yeongnam_fit': evaluate(json.loads((data / 'notices.json').read_text(encoding='utf-8')), data, out)}
    verdict = []
    if holdout:
        holdout = Path(holdout)
        h = result['holdout'] = evaluate(json.loads((holdout / 'notices.json').read_text(encoding='utf-8')), holdout, out / 'holdout')
        alive = all(m['defect_alive'] and m['shuffle_share'] is not None and m['shuffle_share'] <= 0.05 for m in h.values())
        verdict.append('CONTROL_OK' if alive else 'CONTROL_FAIL')
        best = 'v2c' if h['v2c']['MdAPE'] < h['v0']['MdAPE'] else 'v0'
        b, one = h[best], h['v1']
        adopt = (b['MdAPE'] <= one['MdAPE'] - V2_MARGIN and b['coverage'] >= one['coverage'] - COVERAGE_SLACK
                 and b['shuffle_share'] <= 0.05 and b['defect_alive'])
        verdict.append(f'ADOPT_{best.upper()}' if adopt else 'KEEP_V1')
        name = best if adopt else 'v1'
        result['adopted'] = {'method': name, 'MdAPE': h[name]['MdAPE'], 'P80': h[name]['P80'], 'N': h[name]['N'], 'set': '검증'}
        result['alert_min_gap_ratio'] = h[name]['P80']
    result['verdict'] = verdict
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    for region in ('yeongnam_fit', 'holdout'):
        for name, m in result.get(region, {}).items():
            print(region, name, json.dumps(m, ensure_ascii=False))
    print('VERDICT ' + ' '.join(verdict))


if __name__ == '__main__':
    main(*sys.argv[1:])
