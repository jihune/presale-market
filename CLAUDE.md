# presale-market 작업 규칙

공개 저장소다. 코드, 커밋, 이슈, Actions 실행 로그와 실행 요약을 GitHub 계정이 있는 누구나 본다.

## 1. 넣지 않는 것

- 사람에 관한 정보: 이름, 주소, 이메일, 소득, 청약 가점·통장·당첨 이력, 거주지, 세대 구성, 어떤 공고에 관심이 있는지. 신청 자격 판정과 손익 계산은 이 저장소 밖(비공개 저장소)이 한다. 여기 코드는 그런 값을 읽는 설정 파일이나 환경 변수를 두지 않는다.
- 카카오 로컬 API 결과(좌표, 주소, 장소 정보). 카카오 정책상 저장·캐시·정적 파일 공개가 금지라 실행 안에서만 쓰고 파일·캐시·커밋·로그에 남기지 않는다. 공개 결과에는 단지 이름(공공데이터)과 거기서 계산한 반올림 거리만 둔다.
- 도로명주소(juso.go.kr) 자료와 브이월드 자료. 도로명주소는 「국외로 반출할 수 없음」, 브이월드는 해외·클라우드 IP 접속 제한이라 해외에서 도는 GitHub 러너에서 쓰지 않는다.
- 인증키 값. 키는 저장소 Secret(`DATA_GO_KR_KEY`, `KAKAO_REST_API_KEY`)에만 두고, 키가 든 주소를 출력하지 않는다.
- 청약홈 공고 상세의 견본주택 전화번호(`MDHS_TELNO`)는 내보내지 않는다.

## 2. 배치

| 경로 | 내용 |
|---|---|
| `01_code/presale.py` | 공고 모으기, 공고문 읽기, 실거래 받기, 시세 계산, `collect`·`check`·`trades` 명령 |
| `01_code/v2.py`, `fit_v2c.py` | 시세 v2c(분양가 × 예상 웃돈)와 그 계수 맞추기 |
| `01_code/backtest.py`, `backtest_data.py` | 시세 백테스트와 반년마다 도는 자동 점검(판정 규칙은 `backtest.py` 머리), 지난 공고·실거래 받기 |
| `01_code/test_presale.py` | 시험(`test_v2.py`, `test_backtest.py`도). `python -m unittest discover -s 01_code` |
| `02_data/latest.json` | 매일 결과(Actions가 커밋) |
| `02_data/check.json` | 손으로 돌린 지난 공고 결과 |
| `02_data/notices/` | 공고마다 공고문에서 읽은 조건(다시 받지 않으려고 남김) |
| `03_notes/` | 시세 계산 설계, 백테스트 판정 규칙과 결과 |
| `.github/workflows/collect.yml` | 매일 모으기 |
| `.github/workflows/backtest.yml` | 시세 백테스트(손으로 돌림)와 자동 점검(매달 20일에 깨어 170일마다 돎). 결과는 `03_notes/backtest/`(검증 묶음은 `holdout/`, 자동 점검은 `auto/<날짜>/`와 `result.json`) |
| `.github/workflows/merge-session-branches.yml` | 세션 브랜치(`claude/…`, `ccr-…`)를 main에 합침 |

## 3. 작업 방식

- 세션은 지정 브랜치에만 push하고 합치기 워크플로가 main에 넣는다. 공개 저장소라 Actions 실행은 무료다.
- 공공데이터포털 요청은 1초 이상 띄운다(`_get`). 같은 사이트에 몰아 보내지 않는다.
- 정기 실행 cron 줄(`collect.yml`, `backtest.yml`의 `schedule`)은 사용자가 GitHub 웹 편집기로 고친다. 세션이 넣은 cron은 합치기 워크플로(봇의 GITHUB_TOKEN)가 main에 넣는데, 2026-11-03 `collect.yml`의 첫 예약(20:17 UTC)이 3시간 넘게 뜨지 않았다. 사용자가 웹에서 cron을 고친 advisor-db 청약 알림은 정기 실행이 된다. GitHub 문서는 「정기 실행 알림은 cron을 마지막으로 고친 사용자에게 간다」, 「GITHUB_TOKEN이 일으킨 이벤트는 workflow_dispatch·repository_dispatch 말고는 실행을 만들지 않는다」고 적는다(봇이 고친 cron이 돌지 않는다는 문장은 없어 원인은 추정이다). 세션이 cron을 바꿔야 하면 바꾼 뒤 사용자에게 그 줄을 웹에서 뜻이 같은 꼴로 한 번 고쳐 달라고 한다.
- 시세 계산을 바꾸면 `market_method` 문자열과 README 「시세 계산」을 같이 고친다. 읽는 쪽이 방식이 바뀐 것을 안다.
- 백테스트처럼 숫자로 결론을 내는 분석은 돌리기 전에 판정 규칙(대상, 오차 정의, 문턱, 대조, 출력 파일, 마지막 줄 `VERDICT`)을 스크립트 머리에 적어 먼저 커밋한다.
- 이 저장소에서 바뀐 결정과 그 근거는 `03_notes/`에 날짜와 함께 적는다.
