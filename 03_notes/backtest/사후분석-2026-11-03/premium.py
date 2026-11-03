import json
import math
import statistics
import sys
from pathlib import Path

DATA = Path(sys.argv[1]); sys.path.insert(0, sys.argv[2])
import backtest
import presale

notices = json.loads((DATA / 'notices.json').read_text(encoding='utf-8'))
xs, ys, rows = [], [], []
for n in notices:
    if not n.get('code'):
        continue
    nx, ny = [], []
    for m in n['models']:
        area = presale.area_of(m.get('HOUSE_TY')); price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
        if not area or not price:
            continue
        truth = backtest.truth_of(n, area, DATA)
        if truth is None:
            continue
        c = backtest.v1_of(n, area, price, DATA)
        if not c:
            continue
        p = price / area
        nx.append(math.log(c['per'] / p)); ny.append(math.log(truth / p))
    if nx:
        rows.append((n['detail']['RCRIT_PBLANC_DE'], n['sido'], statistics.median(nx), statistics.median(ny)))
xs = [r[2] for r in rows]; ys = [r[3] for r in rows]
mx, my = statistics.fmean(xs), statistics.fmean(ys)
b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
a = my - b * mx
r = statistics.correlation(xs, ys)
print(f'공고 {len(rows)}: log(정답/분양가) = {a:+.4f} + {b:.4f} × log(v1/분양가), 상관 {r:.3f}')
def mdape(errs):
    s = sorted(abs(e) for e in errs); return round(statistics.median(s), 4), round(s[min(len(s)-1, int(0.8*len(s)))], 4)
print('분양가를 그대로 예측:', mdape([math.exp(-y) - 1 for y in ys]))
print('v1:', mdape([math.exp(x - y) - 1 for x, y in zip(xs, ys)]))
print('표본 안 보정(a + b x, 과적합 상한):', mdape([math.exp(a + b * x - y) - 1 for x, y in zip(xs, ys)]))
# 시간 순서를 지키는 보정: 앞 공고들로만 a, b를 맞춰 다음 공고를 예측(정답 창이 끝난 공고만, 공고일 + 540일 < 이 공고일)
import datetime as dt

errs, used = [], 0
for i, (d, s, x, y) in enumerate(rows):
    dd = dt.date.fromisoformat(d)
    past = [(xx, yy) for (d2, s2, xx, yy) in rows if dt.date.fromisoformat(d2) + dt.timedelta(days=540) < dd]
    if len(past) >= 10:
        px = [p[0] for p in past]; py = [p[1] for p in past]
        mxx, myy = statistics.fmean(px), statistics.fmean(py)
        bb = sum((u - mxx) * (v - myy) for u, v in past) / sum((u - mxx) ** 2 for u in px)
        aa = myy - bb * mxx
        errs.append(math.exp(aa + bb * x - y) - 1); used += 1
print('시간 순서 보정(앞 공고 10건 이상일 때만):', used, '건', mdape(errs) if errs else None)
# 시도별 premium
by = {}
for d, s, x, y in rows: by.setdefault(s, []).append(y)
print({s: (len(v), round(statistics.median(v), 3)) for s, v in by.items()})
by = {}
for d, s, x, y in rows: by.setdefault(d[:4], []).append(y)
print('연도별 log(정답/분양가) 중간', {s: (len(v), round(statistics.median(v), 3)) for s, v in sorted(by.items())})
