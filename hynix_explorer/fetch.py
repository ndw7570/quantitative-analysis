"""탐색기용 데이터 수집. 1년 보고서(hynix_report)와 폴더·데이터를 공유하지 않는다.

화면에는 1997년부터 보여 주지만 1994-01 부터 받는다. 매년 계수를 "직전 2년"으로 추정하므로
첫 해(1997)를 계산하려면 1995~1996 이 있어야 하고, 12개월 지표는 그보다 1년이 더 필요하다.

사용: python fetch.py              (전부)
      python fetch.py kr_price us  (고른 것만. 이름은 맨 아래 JOBS)
      python fetch.py flow --full  (종목 수급을 처음부터 다시 받는다. 평소에는 새로 생긴 날만 받는다)
      python fetch.py --today      (18시 전이라도 오늘 한국 장까지 받는다. 15:40 부터)
      python fetch.py rates cpi    (주요국 정책금리와 소비자물가만. 국제결제은행 BIS)
      python fetch.py sec          (미국 종목의 8-K 공시 목록만. SEC EDGAR)
      python fetch.py dart         (한국 종목의 공시 목록만. 전자공시 DART - 무료 키가 .env 나 환경변수 DART_API_KEY 에 있어야 한다. 없으면 건너뛴다)
보통은 직접 부르지 않고 update.py 가 부른다. 하나라도 실패하면 종료 코드 1 로 끝난다(update.py 가 거기서 멈춘다).
어디서 무엇을 받는지와 그 규칙은 프로젝트의 plan/specs/data-collection-policy.md 가 정한다(이 파일은 그것을 따른다).
로그인이 필요한 출처는 쓰지 않는다. 무료 키가 필요한 출처는 키를 환경변수에서만 읽는다(코드·문서·git 에 넣지 않는다).
"""
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from assets import ASSETS, BENCH, KR_BENCH, RATES

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
# 오늘 것은 받지 않는다. 장중에 돌리면 오늘 줄이 미완성 값(장중 가격, 집계 전 수급)으로 들어와
# 마지막 날의 모든 지표가 틀리고, 코스피 수급은 그 값이 파일에 남아 다음 실행에서도 안 고쳐진다.
# 다만 18시가 지나면 오늘 것도 받는다 - 한국 장(15:30)이 끝났고 수급 집계도 나왔다고 본다(집계 시각은 확인 안 함).
# --today 를 주면 18시 전이라도 오늘 것까지 받는다 - 장이 끝난 뒤 저녁까지 기다리지 않고 오늘 종가를 보려는 것이다.
# 그때 종목 수급은 아직 안 올라와 있고(15:48 에 확인), 검사가 "수급이 가격보다 뒤처졌다"고 알린다.
TODAY = date.today()
START, END = date(1994, 1, 1), TODAY if datetime.now().hour >= 18 or "--today" in sys.argv else TODAY - timedelta(days=1)
# 18시 전의 오늘 코스피 수급은 장 마감 직후 값이라 뒤에 바뀔 수 있는데, 한번 파일에 들어가면 다시 받지 않는다.
# 그래서 그 시각에는 오늘 것을 남기지 않는다. 18시 뒤의 실행이 받는다.
UNSETTLED = TODAY.strftime("%Y%m%d") if datetime.now().hour < 18 else None
S, E = START.strftime("%Y%m%d"), END.strftime("%Y%m%d")
# 네이버 증권의 코스피 투자자별 순매수는 2005-01-03 부터 있다. 그 앞 날짜는 오류 대신 0, 0, 0 이 온다(2026-11-25 확인).
KOSPI_FLOW_FROM = "20050101"
HEAD = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
NAVER = "https://m.stock.naver.com/api"
# 국제결제은행(BIS)의 중앙은행 정책금리 묶음 파일. 한 줄이 한 나라, 열이 날짜다(1945년부터 3만 열, 압축해서 0.3MB).
# 같은 자료를 주는 조회 주소(stats.bis.org/api)는 나라 둘에 5.6MB 가 와서 쓰지 않는다(2026-11-26 확인).
BIS = "https://data.bis.org/static/bulk/WS_CBPOL_csv_col.zip"
# BIS 의 소비자물가 묶음 파일. 한 줄이 (주기, 나라, 단위) 하나, 열이 달 또는 해다(1661년부터 1,730열, 압축해서 0.5MB).
# 단위는 둘이다: 771 = 전년 같은 때 대비 %, 628 = 지수(2010 = 100). 부호만 믿지 않고 옆 칸의 글도 같이 본다(cpi).
BIS_CPI = "https://data.bis.org/static/bulk/WS_LONG_CPI_csv_col.zip"
CPI_YOY = ("771", "Year-on-year changes, in per cent")
# SEC EDGAR 의 회사별 공시 목록(JSON). 최근 1,000건은 CIK<번호>.json 에, 그 앞은 같은 응답의 files 가 가리키는 파일들에 있다.
# SEC 는 User-Agent 가 없으면 403 을 준다. 연락처를 적으라고 하지만 개인정보라 넣지 않는다 - 이 이름만으로 받아졌다(2026-11-26 확인).
SEC = "https://data.sec.gov/submissions/"
SEC_HEAD = {"User-Agent": "hynix-explorer research tool", "Accept-Encoding": "gzip"}
SEC_FROM = "1997-01-01"  # 탐색기의 첫해
SEC_COLS = {"accessionNumber": "acc", "filingDate": "date", "reportDate": "report", "form": "form", "items": "items", "primaryDocument": "doc"}
# 전자공시(DART) 공개 API. 무료 키(하루 4만 건)가 있어야 한다. 키는 환경변수 DART_API_KEY 나 이 폴더의 .env 에서만 읽는다(git 에 안 넣는다 - .gitignore).
# corpCode.xml: 회사 번호(corp_code 8자리) <-> 종목 코드(6자리) 표 전체(zip, 3.6MB). list.json: 한 회사의 공시 목록(100건씩 쪽 넘김).
# pblntf_ty: B 주요사항보고(자기주식·유상증자·합병 등), I 거래소공시(잠정실적·배당·공급계약 등). A 정기공시(사업·분기보고서)는 사건이 아니라 받지 않는다.
DART = "https://opendart.fss.or.kr/api/"
DART_TYPES = ("B", "I")
DART_FROM = "19970101"
STOCKS = {k: a["code"] for k, a in ASSETS.items() if a["market"] == "kr" and a["kind"] == "stock"}
KR = {k: a["code"] for k, a in ASSETS.items() if a["market"] == "kr"}
US = {k: a["code"] for k, a in ASSETS.items() if a["market"] == "us"}
FULL = "--full" in sys.argv


def num(s):
    s = str(s).replace(",", "").replace("%", "").replace("+", "").strip()
    # 집계 전인 값은 "-" 로 온다. 0 으로 채우면 순매수 0 으로 오독되므로 결측으로 둔다.
    return float("nan") if s in ("", "-") else float(s)


def kr_price():
    """한국 종목·코스피·코스닥의 일별 시가·고가·저가·종가·거래량. 네이버 증권 siseJson.

    코스닥(assets.KR_BENCH)은 대상이 아니라 탭 3 만 쓴다. 1996-07-02 부터 온다(2026-11-26 확인, 첫날 1,001.7).

    종목 가격은 수정주가다(삼성전자 2018년 50:1 분할 이전이 5만 원대로 온다). 거래량은 그때 주식 수 그대로다.
    전에는 pykrx 를 썼는데 한 종목에 3,000거래일까지만 와서 2014-08 이전을 받을 수 없었다.
    겹치는 2,999일은 두 출처의 시가·종가·거래량이 한 줄도 다르지 않았다(2026-11-25, 하이닉스·삼성전자·삼성전기).
    매번 전체를 다시 받는다 - 분할이 생기면 과거 가격이 통째로 바뀌므로 이어 붙이면 안 된다.
    """
    for name, code in {**KR, **KR_BENCH}.items():
        url = (f"https://api.finance.naver.com/siseJson.naver?symbol={code}&requestType=1"
               f"&startTime={S}&endTime={E}&timeframe=day")
        text = requests.get(url, headers=HEAD, timeout=30).text
        rows = re.findall(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', text)
        if len(rows) < 100:
            raise RuntimeError(f"{name}: siseJson 이 {len(rows)}줄만 돌려줬다")
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"]).set_index("date").astype(float)
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df[~df.index.duplicated()].sort_index()
        df.to_csv(OUT / f"naver_px_{name}.csv", encoding="utf-8-sig")
        print(f"naver_px_{name}", len(df), df.index.min().date(), "~", df.index.max().date())
        time.sleep(0.2)  # 공개 서버에 부담을 주지 않으려고 간격을 둔다


def us():
    """미국 지수·종목 일별 시가·고가·저가·종가·거래량. 야후 파이낸스, yfinance 경유.

    Close 와 Volume 은 주식분할이 반영된 값이다(엔비디아 2021년 4:1, 2024년 10:1). 배당은 반영하지 않은 Close 를 쓴다
    - 한국 쪽 가격도 배당을 반영하지 않기 때문이다.
    """
    import yfinance as yf
    # 어제(한국 날짜) 미국 장은 한국 시각 오늘 아침에 끝난다. 그 전에 돌리면 어제 줄이 장중 값이라 하루 더 뺀다.
    # 오늘 날짜의 미국 장은 아직 안 끝났으므로 한국 쪽이 오늘까지 받아도 미국은 어제까지다.
    last = TODAY - timedelta(days=1 if datetime.now().hour >= 7 else 2)
    for name, tk in {**BENCH, **US}.items():
        df = yf.download(tk, start=START.isoformat(), end=(last + timedelta(days=1)).isoformat(),
                         auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[df.index <= pd.Timestamp(last)]
        if len(df) < 100:  # 야후는 막혔을 때 오류 대신 빈 표를 준다. 그대로 저장하면 멀쩡한 파일을 덮어쓴다
            raise RuntimeError(f"{name}({tk}): 야후가 {len(df)}줄만 돌려줬다")
        # 야후가 마지막 날을 고가·저가만 채우고 종가는 비운 채 줄 때가 있다(2026-11-25 에 종목 5개가 그랬다).
        # 그대로 저장하면 종가가 들어 있던 파일을 덮어쓰고, 화면에는 전날 종가가 그날 값처럼 이어진다.
        if pd.isna(df["Close"].iloc[-1]):
            raise RuntimeError(f"{name}({tk}): 야후가 {df.index[-1].date()} 종가를 비운 채 돌려줬다. 있던 파일은 그대로 뒀다")
        df.to_csv(OUT / f"yf_{name}.csv", encoding="utf-8-sig")
        print(f"yf_{name}", len(df), df.index.min().date(), "~", df.index.max().date())


def flow():
    """종목 투자자별 순매수(주식 수), 외국인 지분율, 종가(수정 전). 네이버 증권. 2005-01 부터 있다(그 앞은 빈 쪽이 온다).

    최근에서 과거로 60일씩 넘겨 받는다. 30년이면 종목당 90번을 불러야 해서, 받은 날은 파일에 남기고
    다음 실행에서는 파일의 마지막 날에 닿을 때까지만 받는다. 마지막 한 쪽은 겹쳐 받는다 - 나중에 고쳐진 값이 그 사이 반영된다.

    bizdate 는 "그날 앞까지"다 - 20261124 로 부르면 11-23 부터 온다(2026-11-25 확인). 그래서 끝 날 다음 날로 부르고,
    다음 쪽은 받은 가장 옛 날짜 그대로 부른다. 전에는 끝 날로 부르고 하루를 더 빼서, 마지막 날과 60일마다 하루씩이 빠졌다.
    """
    for name, code in STOCKS.items():
        f = OUT / f"naver_flow_{name}.csv"
        have = pd.read_csv(f, index_col=0, parse_dates=True) if f.exists() and not FULL else pd.DataFrame()
        rows = {d.strftime("%Y%m%d"): r.to_dict() for d, r in have.iterrows()}
        until = max(rows) if rows else S
        url = NAVER + f"/stock/{code}/trend?pageSize=60&bizdate={{}}"
        cursor, pages = (END + timedelta(days=1)).strftime("%Y%m%d"), 0
        while cursor > S:
            r = requests.get(url.format(cursor), headers=HEAD, timeout=15)
            if r.status_code != 200:
                raise RuntimeError(f"{name}: 수급 조회 상태 {r.status_code} ({cursor})")
            page = r.json()
            if not page:  # 더 과거가 없다
                break
            pages += 1
            for it in page:
                rows[it["bizdate"]] = {
                    "foreign_net": num(it["foreignerPureBuyQuant"]), "inst_net": num(it["organPureBuyQuant"]),
                    "indiv_net": num(it["individualPureBuyQuant"]), "foreign_ratio": num(it["foreignerHoldRatio"]),
                    "close": num(it["closePrice"]),
                }
            oldest = min(d["bizdate"] for d in page)
            if oldest <= until or oldest >= cursor:  # 뒤쪽 조건: 같은 쪽이 되돌아오면 끝없이 돌지 않게
                break
            cursor = oldest
            time.sleep(0.2)
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.sort_index().loc[pd.Timestamp(START):pd.Timestamp(END)]
        df.index.name = "date"
        df.to_csv(f, encoding="utf-8-sig")
        print(f"naver_flow_{name}", len(df), df.index.min().date(), "~", df.index.max().date(),
              f"({pages}쪽 받음, 전에 있던 {len(have)}일)", "결측", df.isna().sum().to_dict(), flush=True)


def kospi_flow():
    """코스피 시장 투자자별 순매수(억원). 네이버 증권. 하루에 한 번씩만 조회되어 처음에는 5천 번 넘게 부른다.

    그래서 받은 날은 파일에 남기고 다음 실행에서는 빠진 날만 받는다.
    """
    f = OUT / "naver_flow_kospi.csv"
    days = pd.read_csv(OUT / "naver_px_kospi.csv", index_col=0, parse_dates=True).index
    have = pd.read_csv(f, index_col=0, parse_dates=True) if f.exists() else pd.DataFrame()
    rows = {d.strftime("%Y%m%d"): r.to_dict() for d, r in have.iterrows()}
    todo = [d for d in (x.strftime("%Y%m%d") for x in days) if d >= KOSPI_FLOW_FROM and d not in rows and d != UNSETTLED]

    def save():
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.sort_index()
        df.index.name = "date"
        df.to_csv(f, encoding="utf-8-sig")
        return df

    def one(d):
        try:
            j = requests.get(NAVER + f"/index/KOSPI/trend?bizdate={d}", headers=HEAD, timeout=15).json()
        except Exception:  # noqa: BLE001 - 못 받은 날은 다음 실행에서 다시 받는다
            return d, None
        if j.get("bizdate") != d:  # 다른 날짜가 돌아오면 그날 자료가 없다는 뜻이라 버린다
            return d, None
        row = {"foreign_val": num(j["foreignValue"]), "inst_val": num(j["institutionalValue"]),
               "indiv_val": num(j["personalValue"])}
        # 셋 다 0 이면 집계가 안 올라온 날이다(자료가 없는 옛 날짜도 이렇게 온다). 남기면 순매수 0 으로 읽힌다.
        return d, (row if any(v != 0 for v in row.values()) else None)

    # 한 번에 0.7초쯤 걸려 순서대로 받으면 한 시간이 든다. 동시에 3개까지만 보낸다(공개 서버에 부담을 주지 않을 만큼).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        for i, (d, row) in enumerate(ex.map(one, todo)):
            if row:
                rows[d] = row
            if i % 300 == 299:
                save()  # 중간에 끊겨도 받은 만큼은 남긴다
                print("  kospi_flow", i + 1, "/", len(todo), flush=True)
    df = save()
    print("naver_flow_kospi", len(df), df.index.min().date(), "~", df.index.max().date(),
          "새로 받음", len(df) - len(have), "/ 받으려던", len(todo))


def now():
    """오늘 기준 한 줄 값: 상장주식수, PBR·추정PER·배당수익률. 한국 종목은 네이버 증권, 미국 종목은 야후. 이력은 없다."""
    out = {}
    for name, code in STOCKS.items():
        j = requests.get(NAVER + f"/stock/{code}/integration", headers=HEAD, timeout=15).json()
        t = {x["key"]: x["value"] for x in j["totalInfos"]}
        jo, _, uk = t["시총"].partition("조")
        cap = num(jo) * 1e12 + (num(uk.replace("억", "")) * 1e8 if uk.strip() else 0)
        # 시가총액은 "지금 가격" 기준으로 온다. 받아 둔 마지막 종가로 나누면 장중에 돌렸을 때 오늘 등락만큼 주식 수가 틀린다.
        # 같은 순간의 현재가를 따로 받아서 나눈다.
        price = num(requests.get(NAVER + f"/stock/{code}/basic", headers=HEAD, timeout=15).json()["closePrice"])
        out[name] = {"shares": cap / price, "cap": cap, "pbr": t.get("PBR"), "per": t.get("추정PER"),
                     "div": t.get("배당수익률"), "fetched": date.today().isoformat()}
    import yfinance as yf
    for name, tk in US.items():
        if ASSETS[name]["kind"] != "stock":
            continue
        t = yf.Ticker(tk)
        row = {"shares": float(t.fast_info["shares"]), "cap": None, "pbr": None, "per": None, "div": None,
               "fetched": date.today().isoformat()}
        try:  # 재무 요약은 야후가 자주 막는다. 못 받으면 표에 "-" 로 나오게 비워 둔다
            i = t.info
            if i.get("priceToBook"):
                row["pbr"] = f"{i['priceToBook']:.2f}배"
            if i.get("forwardPE"):
                row["per"] = f"{i['forwardPE']:.2f}배"
            # dividendYield 는 yfinance 판마다 단위(비율/퍼센트)가 달라서 쓰지 않고 직접 나눈다
            if i.get("dividendRate") and i.get("currentPrice"):
                row["div"] = f"{i['dividendRate'] / i['currentPrice'] * 100:.2f}%"
        except Exception as ex:  # noqa: BLE001
            print("  now", name, "재무 요약 실패:", type(ex).__name__)
        out[name] = row
    (OUT / "naver_now.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("naver_now", {k: round(v["shares"] / 1e8, 2) for k, v in out.items()}, "(억 주)")


def bis_table(url, what):
    """BIS 묶음 파일(zip 안에 CSV 하나)을 표로 읽는다. 한 줄이 한 계열이고 열이 날짜다."""
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"BIS {what} 파일 상태 {r.status_code}")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return pd.read_csv(z.open(z.namelist()[0]), low_memory=False)


def rates():
    """주요국 중앙은행 정책금리(일별, %). 국제결제은행(BIS)이 각국 중앙은행 값을 모아 내는 파일 하나를 받는다.

    일별(FREQ=D) 줄에서 assets.RATES 의 나라만 뽑아, 날짜를 줄로 돌려 bis_rates.csv 에 둔다.
    주가(1994년부터)와 달리 BIS 가 가진 첫날부터 전부 받는다 - "30년으로는 부족하다"는 요청이 있었다.
    가장 이른 나라는 1946-01-01(일본·영국·스위스·덴마크·인도), 미국은 1954-07-01 부터다(2026-11-26 확인).
    매번 전체를 다시 받는다 - 작고, BIS 가 과거 값을 고쳐 내면 그대로 따라간다.
    빈 날은 여기서 메우지 않는다. 주말·연휴는 나라마다 비어 있고 일본은 정책금리가 없던 몇 해가 통째로 비어 있어서,
    어디까지 이을지는 common.rate_steps 한 군데서 정한다. 나라마다 마지막 날도 다르다(2026-11-26 에 한국은 11-02, 미국은 11-17 까지 왔다).
    BIS 가 적어 둔 "이 나라는 무엇을 정책금리로 보는가"(COMPILATION, 영어)는 bis_rates_meta.json 에 따로 둔다 - 화면에 원문 그대로 보여 준다.
    """
    df = bis_table(BIS, "정책금리")
    df = df[df["FREQ"] == "D"].drop_duplicates("REF_AREA").set_index("REF_AREA")
    lost = [c for c in RATES if c not in df.index]
    if lost:  # 나라가 빠진 채 저장하면 화면에서 그 나라가 말없이 사라진다
        raise RuntimeError(f"BIS 파일에 일별 정책금리가 없는 나라: {lost}")
    days = [c for c in df.columns if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)]
    out = df.loc[list(RATES), days].T.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if len(out) < 1000:
        raise RuntimeError(f"BIS 정책금리가 {len(out)}일치만 왔다")
    out.index = pd.to_datetime(out.index)
    out.index.name = "date"
    out.to_csv(OUT / "bis_rates.csv", encoding="utf-8-sig")
    notes = {c: "" if pd.isna(df.loc[c, "COMPILATION"]) else str(df.loc[c, "COMPILATION"]).strip() for c in RATES}
    (OUT / "bis_rates_meta.json").write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    ends = out.apply(lambda s: s.last_valid_index())
    print("bis_rates", len(out), out.index.min().date(), "~", out.index.max().date(), f"({len(RATES)}개 나라)",
          "가장 늦게 온 나라", ends.idxmin(), ends.min().date())


def cpi():
    """주요국 소비자물가 상승률(월별, 전년 같은 달 대비 %). 정책금리와 같은 곳(BIS)의 다른 묶음 파일 하나를 받는다.

    월별(FREQ=M)·상승률(단위 771) 줄에서 assets.RATES 의 나라만 뽑아, 달(YYYY-MM)을 줄로 돌려 bis_cpi.csv 에 둔다.
    정책금리와 나라 목록을 같이 쓴다 - 탭 4 가 같은 나라의 금리와 물가를 위아래로 그린다.
    매번 전체를 다시 받는다 - 작고, 물가는 뒤에 고쳐 발표되는 값이라 BIS 가 고치면 그대로 따라간다.
    빈 달은 메우지 않는다. 미국 2025-10 은 값이 없고, 스웨덴·홍콩의 옛 자료는 석 달에 한 값만 있다(2026-11-26 확인).
    호주·뉴질랜드는 분기에 한 번 나오는 값이 석 달 동안 같은 값으로 들어 있다 - BIS 파일이 그렇게 온다.
    """
    df = bis_table(BIS_CPI, "소비자물가")
    df = df[(df["FREQ"] == "M") & (df["UNIT_MEASURE"].astype(str) == CPI_YOY[0])]
    odd = sorted(set(df["Unit of measure"]) - {CPI_YOY[1]})
    if odd:  # 부호의 뜻이 바뀌면 지수(100 안팎)를 상승률로 그리게 된다
        raise RuntimeError(f"BIS 소비자물가의 단위 {CPI_YOY[0]} 이 상승률이 아니다: {odd}")
    df = df.drop_duplicates("REF_AREA").set_index("REF_AREA")
    lost = [c for c in RATES if c not in df.index]
    if lost:  # 나라가 빠진 채 저장하면 화면에서 그 나라의 물가 선이 말없이 사라진다
        raise RuntimeError(f"BIS 파일에 월별 소비자물가 상승률이 없는 나라: {lost}")
    months = [c for c in df.columns if re.fullmatch(r"\d{4}-\d{2}", c)]
    out = df.loc[list(RATES), months].T.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if len(out) < 240:
        raise RuntimeError(f"BIS 소비자물가가 {len(out)}달치만 왔다")
    out.index.name = "month"
    out.to_csv(OUT / "bis_cpi.csv", encoding="utf-8-sig")
    ends = out.apply(lambda s: s.last_valid_index())
    print("bis_cpi", len(out), out.index.min(), "~", out.index.max(), f"({len(RATES)}개 나라)", "가장 늦게 온 나라", ends.idxmin(), ends.min())


def dart_key():
    """환경변수가 먼저, 없으면 이 폴더의 .env 의 DART_API_KEY= 줄. 둘 다 없으면 None(받기를 건너뛴다)."""
    if os.environ.get("DART_API_KEY"):
        return os.environ["DART_API_KEY"].strip()
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DART_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def dart_get(path, key, **params):
    r = requests.get(DART + path, params={"crtfc_key": key, **params}, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"DART {path} 상태 {r.status_code}")
    time.sleep(0.2)
    return r


def dart_corps(key):
    """종목 코드(6자리) -> DART 회사 번호(8자리). 상장사만(종목 코드가 있는 줄만)."""
    r = dart_get("corpCode.xml", key)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    xml = z.read(z.namelist()[0]).decode("utf-8")
    found = re.findall(r"<corp_code>(\d+)</corp_code>\s*<corp_name>[^<]*</corp_name>(?:\s*<corp_eng_name>[^<]*</corp_eng_name>)?\s*<stock_code>(\d{6})</stock_code>", xml)
    if len(found) < 1000:  # 상장사는 2천 곳이 넘는다. 적게 왔으면 모양이 바뀐 것이다
        raise RuntimeError(f"DART 회사 목록에서 상장사가 {len(found)}곳만 읽혔다")
    return {stock: corp for corp, stock in found}


def dart():
    """한국 종목의 공시 목록(전자공시 DART). 주요사항보고(B)와 거래소공시(I)를 DART_FROM 뒤로 전부 받아 dart_list.json 에 둔다(종목 키 -> 줄 목록, 날짜 순).

    키가 없으면 [건너뜀] 만 찍고 끝낸다 - 키가 없는 PC 에서도 update.py 가 돌아야 한다. 그러면 사건 표에 한국 공시 줄이 없다(check.py 가 알린다).
    [기재정정] 등 정정 공시는 같은 사건이 두 번 되므로 받지 않는다. 공시의 글은 받지 않고 제목·날짜·접수번호만 받는다.
    매번 전체를 다시 받는다 - 종목당 요청 10개 남짓, 전부 1MB 안쪽(2026-11-26 에 하이닉스는 B 410건, I 713건).
    """
    key = dart_key()
    if not key:
        print("[건너뜀] DART_API_KEY 가 없어 한국 종목의 공시 목록은 받지 않았다(.env 나 환경변수에 넣는다)", flush=True)
        return
    corps = dart_corps(key)
    out = {}
    for k, code in STOCKS.items():
        corp = corps.get(code)
        if not corp:
            raise RuntimeError(f"DART 회사 목록에 종목 코드 {code}({k})가 없다")
        rows = []
        for ty in DART_TYPES:
            page = 1
            while True:
                j = dart_get("list.json", key, corp_code=corp, bgn_de=DART_FROM, end_de=TODAY.strftime("%Y%m%d"), pblntf_ty=ty, page_count=100, page_no=page).json()
                if j.get("status") not in ("000", "013"):  # 013 = 조회된 데이터가 없음
                    raise RuntimeError(f"DART list {k} {ty}: {j.get('status')} {j.get('message')}")
                for it in j.get("list", []):
                    name = it["report_nm"].strip()
                    if name.startswith("["):  # [기재정정], [첨부추가] 등 정정·보완
                        continue
                    rows.append({"date": f"{it['rcept_dt'][:4]}-{it['rcept_dt'][4:6]}-{it['rcept_dt'][6:]}", "no": it["rcept_no"], "name": name, "ty": ty})
                if page >= int(j.get("total_page") or 0):
                    break
                page += 1
        if not rows:
            raise RuntimeError(f"DART {k}: 공시가 하나도 안 왔다")
        out[k] = sorted(rows, key=lambda r: (r["date"], r["no"]))
    (OUT / "dart_list.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print("dart_list", {k: f"{len(v)}건 ~{v[-1]['date']}" for k, v in out.items()})


def sec_page(url):
    r = requests.get(url, headers=SEC_HEAD, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"SEC {url.rsplit('/', 1)[-1]} 상태 {r.status_code}")
    time.sleep(0.2)  # SEC 는 초당 10건까지라고 적어 두었다(원칙 4)
    return r.json()


def sec_rows(rec):
    """공시 목록 한 덩어리(열마다 배열)를 줄 목록으로. 필요한 열이 빠져 있으면 모양이 바뀐 것이라 멈춘다."""
    lost = [c for c in SEC_COLS if c not in rec]
    if lost:
        raise RuntimeError(f"SEC 공시 목록에 열이 없다: {lost}")
    return [dict(zip(SEC_COLS.values(), vals)) for vals in zip(*(rec[c] for c in SEC_COLS))]


def sec():
    """미국 종목의 8-K 공시 목록(SEC EDGAR). 8-K 는 수시 공시다 - 항목 번호로 무엇인지 안다(2.02 실적 발표, 5.02 임원 변경, 1.01 중요 계약 ...).

    assets.ASSETS 에 cik 가 있는 종목마다 전체 목록을 받아 8-K 만, SEC_FROM 뒤만 남겨 sec_8k.json 에 둔다(종목 키 -> 줄 목록, 날짜 순).
    매번 전체를 다시 받는다 - 종목당 요청 2~3개, 전부 1MB 남짓이다. events.py 가 이 파일로 사건 표의 자동 줄을 만든다.
    공시의 글은 받지 않는다. 항목 번호와 날짜, 문서 주소만 받는다.
    """
    out = {}
    for key, a in ASSETS.items():
        if not a.get("cik"):
            continue
        j = sec_page(f"{SEC}CIK{a['cik']:010d}.json")
        rows = sec_rows(j["filings"]["recent"])
        for f in j["filings"].get("files", []):
            rows += sec_rows(sec_page(SEC + f["name"]))
        rows = sorted((r for r in rows if r["form"] == "8-K" and r["date"] >= SEC_FROM), key=lambda r: r["date"])
        if not rows:  # 8-K 가 하나도 없는 상장사는 없다. 빈 채 저장하면 그 종목의 사건이 말없이 사라진다
            raise RuntimeError(f"SEC {a['name']}: 8-K 공시가 하나도 안 왔다")
        out[key] = rows
    (OUT / "sec_8k.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print("sec_8k", {k: f"{len(v)}건 ~{v[-1]['date']}" for k, v in out.items()})


JOBS = {f.__name__: f for f in (kr_price, us, flow, kospi_flow, now, rates, cpi, sec, dart)}
if __name__ == "__main__":  # 테스트가 이 파일을 불러올 때는 받지 않는다
    if "--today" in sys.argv and datetime.now().strftime("%H:%M") < "15:40":
        # 장중 가격이 오늘 종가인 것처럼 저장된다. 15:30 마감 뒤 종가가 올라올 틈을 두고 받는다
        print("[FAIL] --today 는 한국 장이 끝난 뒤(15:40 부터)에만 쓴다", flush=True)
        sys.exit(1)
    failed = []
    for name in ([a for a in sys.argv[1:] if not a.startswith("--")] or JOBS):
        try:
            JOBS[name]()
        except Exception as ex:  # noqa: BLE001 - 소스 하나가 막혀도 나머지 결과는 봐야 한다
            failed.append(name)
            print(f"[FAIL] {name}: {type(ex).__name__}: {str(ex)[:300]}", flush=True)
    if failed:
        sys.exit(1)
