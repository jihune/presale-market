"""백테스트용 지난 공고와 실거래를 받는다(공공데이터만).

사용: python 01_code/backtest_data.py <출력 폴더>
  <출력 폴더>/notices.json            2023-01-01 ~ 2025-06-30 영남 민영 분양 공고(임대 제외)와 주택형
  <출력 폴더>/trades/<시군구코드>/<YYYYMM>.json   공고 12개월 전 ~ 18개월 뒤의 매매·분양권 실거래(오늘 이후 달은 받지 않음)
이미 있는 파일은 다시 받지 않는다. 환경 변수 DATA_GO_KR_KEY가 있어야 한다.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import presale

SIDOS = ('대구광역시', '경상북도', '부산광역시', '울산광역시', '경상남도')
SINCE, UNTIL = '2023-01-01', '2025-06-30'


def months_around(day, before=12, after=18):
    y, m = int(day[:4]), int(day[5:7])
    base = y * 12 + m - 1
    return [f'{k // 12}{k % 12 + 1:02d}' for k in range(base - before, base + after + 1)]


def main(out):
    out = Path(out)
    today = presale.today_kst()
    path = out / 'notices.json'
    if path.exists():
        notices = json.loads(path.read_text(encoding='utf-8'))
    else:
        rows = presale.applyhome('getAPTLttotPblancDetail', {'cond[RCRIT_PBLANC_DE::GTE]': SINCE, 'cond[RCRIT_PBLANC_DE::LTE]': UNTIL})
        notices = []
        for p in rows:
            sido, sgg, umd = presale.split_address(p.get('HSSPLY_ADRES', ''), p.get('SUBSCRPT_AREA_CODE_NM', ''))
            if sido not in SIDOS or str(p.get('RENT_SECD') or '0') != '0' or p.get('HOUSE_DTL_SECD') != '01':
                continue
            models = presale.applyhome('getAPTLttotPblancMdl', {'cond[HOUSE_MANAGE_NO::EQ]': p['HOUSE_MANAGE_NO'], 'cond[PBLANC_NO::EQ]': p['PBLANC_NO']})
            code = presale.sigungu_code(f'{sido} {sgg}'.strip())
            notices.append({'detail': {k: v for k, v in p.items() if k not in presale.DROP_FIELDS}, 'models': models,
                            'sido': sido, 'sigungu': sgg, 'umd': umd, 'code': code})
        out.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notices, ensure_ascii=False, indent=1), encoding='utf-8')
    need = sorted({(n['code'], ym) for n in notices if n['code'] for ym in months_around(n['detail']['RCRIT_PBLANC_DE'])
                   if ym <= f'{today.year}{today.month:02d}'})
    print(f'공고 {len(notices)}건, 받을 시·군·구-월 {len(need)}개')
    done = 0
    for code, ym in need:
        f = out / 'trades' / code / f'{ym}.json'
        if not f.exists():
            rows = presale.trades(code, ym) + presale.trades(code, ym, url=presale.SILV)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        done += 1
        if done % 100 == 0:
            print(f'{done}/{len(need)} {dt.datetime.now(dt.timezone.utc):%H:%M:%SZ}', flush=True)
    print(f'끝 {done}/{len(need)}')


if __name__ == '__main__':
    main(sys.argv[1])
