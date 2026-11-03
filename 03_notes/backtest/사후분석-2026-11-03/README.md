# 2회차 뒤 사후 분석 스크립트 (2026-11-03)

3회차(v2c)를 정하기 전에 영남 백테스트 자료(Actions 캐시 `backtest-`를 `backtest.yml`의 `upload` 모드로 받은 것)로 돌린 탐색이다. 판정이 아니다. 결과는 `../README.md` 「2회차 사후 분석」과 `../../v2-설계.md` 「v2c」에 적었다.

| 파일 | 하는 일 |
|---|---|
| `evaluate.py`, `candidates.py` | 좌표 없이 행정구역만 쓰는 v1 변형(단지마다 한 표, 분양권 프리미엄 곱하기 등) 여섯 가지를 견준다. C0이 v1을 그대로 재현하는지가 대조다 |
| `tiers.py` | v1이 쓴 범위(같은 동 분양권 등)별 오차와, 분양가 ÷ 정답, v1 ÷ 분양가의 중간값 |
| `premium.py` | log(정답 ÷ 분양가)를 log(v1 ÷ 분양가)에 회귀(기울기, 상관), 분양가를 그대로 쓸 때의 오차 |
| `buckets.py` | v1 ÷ 분양가 구간별 실제 웃돈 분포 |

쓰는 법: `python3 <파일> <백테스트 자료 폴더> <presale-market 01_code 폴더>`(`evaluate.py`는 같은 폴더의 `candidates.py`를 읽는다). 이 스크립트들은 `backtest.py`의 `v1_of`, `truth_of`를 부른다.
