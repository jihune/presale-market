"""백테스트용 지난 공고와 실거래를 받는다(공공데이터만).

사용: python 01_code/backtest_data.py <출력 폴더> [영남|검증] [auto]
  <출력 폴더>/notices.json            2023-01-01 ~ 2025-06-30 민영 분양 공고(임대 제외)와 주택형. 영남(기본)은 대구·경북·부산·울산·경남,
                                      검증은 3회차의 새 검증 묶음(충청·호남·강원과 대전·세종·광주).
                                      auto면 자동 점검 창(auto_window: 오늘 − 585일까지 912일)의 공고
  <출력 폴더>/window.txt              받은 공고 창 「SINCE UNTIL」. 창이 바뀌면 공고 목록을 다시 받는다
  <출력 폴더>/trades/<시군구코드>/<YYYYMM>.json   공고 12개월 전 ~ 18개월 뒤의 매매·분양권 실거래(오늘 이후 달은 받지 않음)
이미 있는 파일은 다시 받지 않는다. 환경 변수 DATA_GO_KR_KEY가 있어야 한다.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import presale

REGIONS = {
    '영남': ('대구광역시', '경상북도', '부산광역시', '울산광역시', '경상남도'),
    # 2023 ~ 2024에 이름이 바뀐 시·도(강원도 → 강원특별자치도 2023-06-11, 전라북도 → 전북특별자치도 2024-01-18)는 옛 이름도 받는다
    '검증': ('대전광역시', '세종특별자치시', '충청북도', '충청남도', '광주광역시', '전라남도', '전라북도', '전북특별자치도',
           '강원도', '강원특별자치도'),
}
# 법정동코드 API는 지금 이름으로 찾는다
NEW_NAMES = {'전라북도': '전북특별자치도', '강원도': '강원특별자치도'}
SINCE, UNTIL = '2023-01-01', '2025-06-30'
AUTO_LAG_DAYS, AUTO_SPAN_DAYS = 585, 912  # 자동 점검 창(판정 규칙은 backtest.py 머리)


def auto_window(today):
    until = today - dt.timedelta(days=AUTO_LAG_DAYS)
    return (until - dt.timedelta(days=AUTO_SPAN_DAYS)).isoformat(), until.isoformat()


def months_around(day, before=12, after=18):
    y, m = int(day[:4]), int(day[5:7])
    base = y * 12 + m - 1
    return [f'{k // 12}{k % 12 + 1:02d}' for k in range(base - before, base + after + 1)]


def main(out, region='영남', window=None):
    out, sidos = Path(out), REGIONS[region]
    today = presale.today_kst()
    since, until = auto_window(today) if window == 'auto' else (SINCE, UNTIL)
    path, mark = out / 'notices.json', out / 'window.txt'
    # 창 기록이 없는 옛 폴더(1 ~ 3회차 캐시)는 기본 창으로 본다
    old = mark.read_text(encoding='utf-8').strip() if mark.exists() else f'{SINCE} {UNTIL}'
    if path.exists() and old == f'{since} {until}':
        notices = json.loads(path.read_text(encoding='utf-8'))
    else:
        rows = presale.applyhome('getAPTLttotPblancDetail', {'cond[RCRIT_PBLANC_DE::GTE]': since, 'cond[RCRIT_PBLANC_DE::LTE]': until})
        notices = []
        for p in rows:
            sido, sgg, umd = presale.split_address(p.get('HSSPLY_ADRES', ''), p.get('SUBSCRPT_AREA_CODE_NM', ''))
            sido = NEW_NAMES.get(sido, sido) if sido in sidos else sido
            if sido not in sidos or str(p.get('RENT_SECD') or '0') != '0' or p.get('HOUSE_DTL_SECD') != '01':
                continue
            models = presale.applyhome('getAPTLttotPblancMdl', {'cond[HOUSE_MANAGE_NO::EQ]': p['HOUSE_MANAGE_NO'], 'cond[PBLANC_NO::EQ]': p['PBLANC_NO']})
            notices.append({'detail': {k: v for k, v in p.items() if k not in presale.DROP_FIELDS}, 'models': models,
                            'sido': sido, 'sigungu': sgg, 'umd': umd, 'code': None})
    # 연결이 끊겨 시·군·구 코드를 못 받은 공고는 다음 실행이 다시 받는다
    failed = 0
    for n in notices:
        if not n['code']:
            try:
                n['code'] = presale.sigungu_code(f"{n['sido']} {n['sigungu']}".strip())
            except RuntimeError as ex:
                failed += 1
                print(f"{n['detail'].get('HOUSE_NM')}: 시·군·구 코드 실패 {ex}")
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notices, ensure_ascii=False, indent=1), encoding='utf-8')
    mark.write_text(f'{since} {until}\n', encoding='utf-8')
    need = sorted({(n['code'], ym) for n in notices if n['code'] for ym in months_around(n['detail']['RCRIT_PBLANC_DE'])
                   if ym <= f'{today.year}{today.month:02d}'})
    print(f'공고 {len(notices)}건({since} ~ {until}, 코드 실패 {failed}), 받을 시·군·구-월 {len(need)}개')
    done = 0
    for code, ym in need:
        f = out / 'trades' / code / f'{ym}.json'
        if not f.exists():
            try:
                rows = presale.trades(code, ym) + presale.trades(code, ym, url=presale.SILV)
            except RuntimeError as ex:  # 다음 실행이 다시 받는다
                failed += 1
                print(f'{code} {ym}: 실패 {ex}')
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        done += 1
        if done % 100 == 0:
            print(f'{done}/{len(need)} {dt.datetime.now(dt.timezone.utc):%H:%M:%SZ}', flush=True)
    print(f'끝: 받은 것 {done}/{len(need)}, 실패 {failed}')


if __name__ == '__main__':
    main(*sys.argv[1:])
