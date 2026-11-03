import itertools
import json
import statistics
import sys
from pathlib import Path

DATA = Path(sys.argv[1]); sys.path.insert(0, sys.argv[2])
import backtest
import presale

notices = json.loads((DATA / 'notices.json').read_text(encoding='utf-8'))
pts = []  # 주택형 단위 (v1/분양가 − 1, 정답/분양가 − 1, 분양가 만원)
nonly = []
for n in notices:
    if not n.get('code'):
        continue
    for m in n['models']:
        area = presale.area_of(m.get('HOUSE_TY')); price = int(str(m.get('LTTOT_TOP_AMOUNT') or 0).replace(',', '') or 0)
        if not area or not price:
            continue
        truth = backtest.truth_of(n, area, DATA)
        c = backtest.v1_of(n, area, price, DATA)
        if c:
            nonly.append(truth is not None)
        if truth is None or not c:
            continue
        p = price / area
        pts.append((c['per'] / p - 1, truth / p - 1, price))
print('v1 값이 있는 주택형', len(nonly), '그 가운데 정답(공고 뒤 분양권 3건 이상)이 있는 것', sum(nonly))
edges = [-1, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 10]
for lo, hi in itertools.pairwise(edges):
    sel = [p for p in pts if lo <= p[0] < hi]
    if sel:
        prem = [p[1] for p in sel]
        print(f'v1/분양가−1 [{lo:+.1f}, {hi:+.1f}): 주택형 {len(sel):3d}, 실제 웃돈 중간 {statistics.median(prem):+.3f}, 20% {sorted(prem)[int(0.2*len(prem))]:+.3f}, 80% {sorted(prem)[min(len(prem)-1,int(0.8*len(prem)))]:+.3f}, 웃돈 > 5% 비율 {sum(x > 0.05 for x in prem)/len(prem):.2f}')
gain = [p[1] * p[2] for p in pts]
print('실제 웃돈(만원) 중간', round(statistics.median(gain)), ' 1,000만원 넘는 주택형', sum(g > 1000 for g in gain), '/', len(gain), ' 3,000만원 넘는 것', sum(g > 3000 for g in gain))
