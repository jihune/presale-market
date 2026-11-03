"""v2c 후보를 영남 백테스트 자료로 견준다(세션 안 탐색용, 판정이 아님). 오차 정의는 backtest.py와 같다.

사용: python3 evaluate.py <자료 폴더(notices.json, trades/)> <presale-market 01_code 폴더>
"""

import datetime as dt
import json
import statistics
import sys
from pathlib import Path

DATA, CODE = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, CODE)
import backtest
import presale

import candidates

notices = json.loads((DATA / 'notices.json').read_text(encoding='utf-8'))


def pool_of(n, months):
    d = dt.date.fromisoformat(n['detail']['RCRIT_PBLANC_DE'])
    start = d - dt.timedelta(days=31 * months)
    return [t for t in backtest.load_rows(DATA, n['code'], backtest.months_between(start, d))
            if start.isoformat() <= t['date'] < d.isoformat()]


def run(predict):
    rows = []
    for n in notices:
        if not n.get('code'):
            continue
        errs, truths = [], []
        for m in n['models']:
            area = presale.area_of(m.get('HOUSE_TY'))
            price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
            if not area or not price:
                continue
            truth = backtest.truth_of(n, area, DATA)
            if truth is None:
                continue
            truths.append(truth)
            pred = predict(n, area, price)
            if pred is not None:
                errs.append(pred / truth - 1)
        if truths:
            rows.append({'sido': n['sido'], 'err': statistics.median(errs) if errs else None})
    errs = [r['err'] for r in rows if r['err'] is not None]
    a = sorted(abs(e) for e in errs)
    return {'N': len(rows), 'cov': round(len(errs) / len(rows), 3), 'MdAPE': round(statistics.median(a), 4),
            'P80': round(a[min(len(a) - 1, int(0.8 * len(a)))], 4), 'bias': round(statistics.median(errs), 4)}


def v1(n, area, price):
    c = backtest.v1_of(n, area, price, DATA)
    return c['per'] if c else None


print('v1', run(v1), flush=True)
for name, fn in candidates.CANDIDATES.items():
    def predict(n, area, price, fn=fn):
        d = dt.date.fromisoformat(n['detail']['RCRIT_PBLANC_DE'])
        c = backtest.v1_of(n, area, price, DATA)
        if c and c.get('tier') == 0:
            return c['per']
        got = fn(pool_of(n, 12), pool_of(n, 6), area, n['umd'], d.year, n['detail'].get('HOUSE_NM', ''))
        return got if got is not None else (c['per'] if c else None)
    print(name, run(predict), flush=True)
