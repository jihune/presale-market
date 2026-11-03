import collections
import json
import statistics
import sys
from pathlib import Path

DATA = Path(sys.argv[1]); sys.path.insert(0, sys.argv[2])
import backtest
import presale

notices = json.loads((DATA / 'notices.json').read_text(encoding='utf-8'))
by = collections.defaultdict(list)
gaps = []
for n in notices:
    if not n.get('code'):
        continue
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
        e = c['per'] / truth - 1
        by[c['scope']].append(e)
        # 분양가 대비 정답(공고 뒤 분양권 프리미엄)과 분양가 대비 v1
        gaps.append((price / area / truth - 1, c['per'] / (price / area) - 1, e))
for k, es in sorted(by.items(), key=lambda kv: -len(kv[1])):
    print(f'{k}: 주택형 {len(es)}, 오차 중간 {statistics.median(es):+.3f}, 절대 중간 {statistics.median([abs(x) for x in es]):.3f}')
print('주택형', len(gaps))
print('분양가 ÷ 정답 − 1 중간', round(statistics.median(g[0] for g in gaps), 4), ' (음수면 분양권이 분양가보다 비싸게 거래)')
print('v1 ÷ 분양가 − 1 중간', round(statistics.median(g[1] for g in gaps), 4))
