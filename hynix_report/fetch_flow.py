"""외국인·기관·개인 일별 순매매(수급) 수집 - 네이버 증권 공개 JSON.

KRX 는 로그인 없이는 수급·공매도를 주지 않는다. 계정 정보를 코드에 넣지 않으려고
로그인이 필요 없는 공개 경로를 쓴다. 공매도는 이 경로에 없어서 수집하지 않는다.
"""
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).parent / "data"
URL = "https://m.stock.naver.com/api/stock/000660/trend?pageSize=60&bizdate={}"
HEAD = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
TARGET_ROWS = 420  # 1년(약 245거래일) + 60일 z-score·누적 계산용 여유


def num(s):
    s = str(s).replace(",", "").replace("%", "").replace("+", "").strip()
    # 값이 아직 집계되지 않은 날은 "-" 로 온다. 0 으로 채우면 순매수 0 으로 오독되므로 결측으로 둔다.
    return float("nan") if s in ("", "-") else float(s)


rows, cursor = {}, datetime.today().strftime("%Y%m%d")
while len(rows) < TARGET_ROWS:
    r = requests.get(URL.format(cursor), headers=HEAD, timeout=15)
    r.raise_for_status()
    page = r.json()
    if not page:
        break
    before = len(rows)
    for it in page:
        rows[it["bizdate"]] = {
            "foreign_net": num(it["foreignerPureBuyQuant"]),
            "inst_net": num(it["organPureBuyQuant"]),
            "indiv_net": num(it["individualPureBuyQuant"]),
            "foreign_ratio": num(it["foreignerHoldRatio"]),
            "close": num(it["closePrice"]),
            "volume": num(it["accumulatedTradingVolume"]),
        }
    if len(rows) == before:  # 같은 쪽이 반복되면 더 과거가 없다는 뜻
        break
    oldest = min(d["bizdate"] for d in page)
    cursor = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    time.sleep(0.3)  # 공개 서버에 부담을 주지 않으려고 간격을 둔다

df = pd.DataFrame.from_dict(rows, orient="index")
df.index = pd.to_datetime(df.index, format="%Y%m%d")
df = df.sort_index()
df.index.name = "date"
df.to_csv(OUT / "naver_flow.csv", encoding="utf-8-sig")
print(len(df), df.index.min().date(), "~", df.index.max().date())
print(df.tail(3).to_string())

# 코스피 지수: KRX 지수 조회도 로그인에 막혀서 같은 공개 경로에서 받는다.
KOSPI = "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=60&page={}"
krows = {}
for p in range(1, 14):  # 60일 x 13쪽 = 약 3년. 시장모형 계수를 분석 구간 이전 데이터로 추정하려면 필요하다
    page = requests.get(KOSPI.format(p), headers=HEAD, timeout=15).json()
    if not page:
        break
    for it in page:
        krows[it["localTradedAt"][:10]] = num(it["closePrice"])
    time.sleep(0.3)
ks = pd.Series(krows, name="close")
ks.index = pd.to_datetime(ks.index)
ks = ks.sort_index()
ks.index.name = "date"
ks.to_csv(OUT / "naver_kospi.csv", encoding="utf-8-sig")
print("kospi", len(ks), ks.index.min().date(), "~", ks.index.max().date(), ks.iloc[-1])
