# quantitative-analysis

퀀트 투자 학습용 시제품 코드(P014). 주가·수급·정책금리 자료를 받아 모델 값을 계산하고, 인터넷 없이 열리는 HTML 한 파일을 만든다.
생성된 코드다. 결과를 믿고 쓰기 전에 사람이 검토하고 시험한다. 투자 판단의 근거로 쓰는 물건이 아니다.

| 폴더 | 내용 | 상태 |
|---|---|---|
| `hynix_explorer/` | 30년 탐색기 (주식·지수 15개 1997년~, 정책금리 26개 나라 1995년~) | 쓰는 중. `update.py` 한 줄로 최신본을 만든다 |
| `hynix_report/` | SK하이닉스 1년 보고서 (2026-11-21) | 보관. 그때 만든 그대로이고 고치지 않는다(수급 누락 오류가 남아 있다) |

## 문서는 여기 없다

정책과 구조 문서는 이 저장소가 아니라 프로젝트의 기획 폴더에 둔다(이 저장소만 받은 경우에는 없다).

| 알고 싶은 것 | 문서 (프로젝트 폴더 기준) |
|---|---|
| 어디서 무엇을 받는가, 받을 때의 규칙 | `plan/specs/data-collection-policy.md` |
| 스크립트가 어떻게 도는가, 가공 방법, 화면 구조 | `plan/specs/explorer-architecture.md` |

## 처음 한 번

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

로그인·API 키는 필요 없다. 계정 정보를 코드나 설정 파일에 넣지 않는다.

## 최신본 만들기

```
cd hynix_explorer
..\.venv\Scripts\python update.py              새 날짜만 받아서 다시 만든다 (보통 이것, 6~10분)
..\.venv\Scripts\python update.py --today      18시 전이라도 오늘 한국 장까지 받는다 (15:40 부터. 오늘 수급은 빈다)
..\.venv\Scripts\python update.py --no-fetch   받지 않고 다시 만든다 (화면만 고쳤을 때)
..\.venv\Scripts\python update.py --full       종목 수급을 2005년부터 전부 다시 받는다
..\.venv\Scripts\python update.py --out <경로> 다른 곳에 만든다
```

결과는 프로젝트 폴더의 `deck/report/2026-11-25-explorer-30y/index.html` 에 덮어쓴다. 프로젝트 폴더가 없으면 `out/index.html`.
받은 자료(`hynix_explorer/data/`)는 저장소에 없다. 처음 돌리면 전부 새로 받는다(30분쯤으로 어림한다. 처음부터 끝까지 재 본 적은 없다).

## 시험

```
cd hynix_explorer
..\.venv\Scripts\python -m unittest discover -s tests   받기·읽기 규칙 (가짜 서버, 1초 안쪽)
..\.venv\Scripts\python check.py                        지금 data/ 의 결과를 원자료와 대조
```

`update.py` 는 `check.py` 를 스스로 부른다. 검사에서 오류가 나오면 HTML 을 바꾸지 않고 멈춘다.
