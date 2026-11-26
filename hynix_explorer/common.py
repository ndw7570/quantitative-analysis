"""analyze.py 와 signals.py 가 같이 쓰는 데이터 읽기. 같은 파일을 두 군데서 다르게 읽으면 탭마다 값이 어긋난다."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from assets import ASSETS, RATES

D = Path(__file__).parent / "data"
WHO = ("foreign", "inst", "indiv")


def prices(key):
    """일별 open/high/low/close/volume/chg. 코스피는 volume 을 쓰지 않는다(NaN).

    미국 대상은 미국 달력 그대로 돌려준다(chg 없음). 한국 달력에 얹으려면 on_calendar 를 거친다.
    """
    a = ASSETS[key]
    if a["market"] == "us":
        px = pd.read_csv(D / f"yf_{key}.csv", index_col=0, parse_dates=True).rename(columns=str.lower)
        return px[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    px = pd.read_csv(D / f"naver_px_{key}.csv", index_col=0, parse_dates=True)
    if a["kind"] == "stock":
        px = px[px["volume"] > 0].copy()  # 거래정지일은 거래량 0 에 시가·고가·저가가 0 으로 온다
        for c in ("open", "high", "low"):  # 거래가 있었는데 시가·고가·저가만 0 인 줄이 있다(상장 첫날). 종가로 메운다
            px[c] = px[c].where(px[c] > 0, px["close"])
    else:
        px["volume"] = np.nan  # 지수 거래량은 단위를 확인하지 않아 쓰지 않는다
    # 등락률은 수정주가 종가로 직접 계산한다. 이 출처에는 등락률 열이 없다.
    px["chg"] = px["close"].pct_change() * 100
    return px[["open", "high", "low", "close", "volume", "chg"]]


def us(name):
    return pd.read_csv(D / f"yf_{name}.csv", index_col=0, parse_dates=True)["Close"].dropna()


YEAR_DAYS = ["전년 말"] + [d.strftime("%m-%d") for d in pd.date_range("2025-01-01", "2025-12-31")]  # 평년 365일 + 기준 칸


def year_paths(close):
    """해마다 "전년 마지막 종가 = 0%"로 다시 잰 누적 수익률(%)을 달력 날짜 칸에 놓는다(탭 3 "여러 해 겹쳐 보기").

    칸은 YEAR_DAYS 366개로 모든 해가 같다. 거래일 번호로 맞추지 않는 이유: 해마다 휴장일이 달라 같은 번호가
    다른 날짜가 되고, 선거일처럼 날짜로 정해진 사건을 여러 해에 한 줄로 그을 수 없다.
    - 장이 쉰 날은 직전 종가를 잇는다(1월 1일은 늘 0%).
    - 2월 29일은 뺀다. 그날 종가는 다음 휴장일로 이어질 뿐 사라지지 않는다.
    - 마지막 해는 받은 날까지만 채우고 그 뒤는 비운다. 첫 해는 전년 말 종가가 없어 뺀다.
    """
    last = close.index[-1]
    years = {}
    for y in sorted(set(close.index.year))[1:]:
        cur = close[close.index.year == y]
        pct = (cur / close[close.index.year == y - 1].iloc[-1] - 1) * 100
        s = pct.reindex(pd.date_range(f"{y}-01-01", last if y == last.year else f"{y}-12-31")).ffill().fillna(0.0)
        s = s[~((s.index.month == 2) & (s.index.day == 29))]
        vals = [0.0] + [round(float(v), 2) for v in s]
        years[str(y)] = vals + [None] * (len(YEAR_DAYS) - len(vals))
    return {"end": last.strftime("%Y-%m-%d"), "days": YEAR_DAYS, "years": years}


RATE_FROM = "1995-01-01"  # 탭 3 과 같은 해부터 보여 준다
RATE_FILL = 31  # 이 날수까지 빈 곳은 직전 값을 잇는다. 받은 자료에서 연휴로 빈 가장 긴 곳이 15일이었다(태국 2020-11, 2026-11-26 확인)


def rate_steps(wide):
    """나라마다 정책금리가 "바뀐 날"만 남긴다(탭 4 "주요국 정책금리"). 화면이 이것을 하루 칸으로 다시 편다.

    정책금리는 계단 모양이라 하루 값 1만여 개 대신 바뀐 날 수십~수백 개면 같은 그림이 나온다.
    wide: 날짜가 줄, 나라 부호가 열인 일별 표(fetch.rates 가 만든 bis_rates.csv).
    - 주말·연휴처럼 짧게 빈 곳(RATE_FILL 일까지)은 직전 값을 잇는다.
    - 그보다 길게 빈 곳은 통째로 비운다. 일본은 몇 해씩 비어 있는 기간이 세 번 있고 BIS 가 그중 2013-04 ~ 2016-09 를 "no policy rate"로 적어 두었다. 이으면 없던 금리를 그리게 된다.
    - 나라마다 마지막 날이 달라도 뒤를 메우지 않는다. 그 사이에 금리가 바뀌었을 수 있다. 선은 받은 날(last)에서 끝난다.
    steps: [[날짜, 값], ...]. 그날부터 다음 단계 전날(마지막 단계는 last)까지 그 값이다. 값이 None 이면 그 동안 정책금리가 없다.
    """
    areas = {}
    for c in wide.columns:
        have = wide[c].dropna()
        if have.empty:
            continue
        s = wide[c].reindex(pd.date_range(have.index[0], have.index[-1]))
        run = s.isna().groupby(s.notna().cumsum()).transform("sum")  # 각 날이 속한 빈 구간의 길이
        s = s.ffill().where(s.notna() | (run <= RATE_FILL)).loc[RATE_FROM:].round(4)
        if s.dropna().empty:
            continue
        s = s.loc[s.first_valid_index():]
        prev = s.shift()
        turn = s.ne(prev) & ~(s.isna() & prev.isna())  # NaN 은 자기 자신과도 다르다고 나와서 따로 뺀다
        areas[c] = {"last": have.index[-1].strftime("%Y-%m-%d"),
                    "steps": [[d.strftime("%Y-%m-%d"), None if pd.isna(v) else float(v)] for d, v in s[turn].items()]}
    return {"start": RATE_FROM, "end": max(a["last"] for a in areas.values()), "areas": areas}


def rate_data():
    """탭 4 에 싣는 것 전부: rate_steps 에 화면 이름·묶음(assets.RATES)과 BIS 의 금리 설명을 붙인다.
    build.py 와 check.py 가 같이 쓴다 - 따로 만들면 "HTML 에 든 값이 자료와 같은가"를 비교할 수 없다."""
    out = rate_steps(pd.read_csv(D / "bis_rates.csv", index_col=0, parse_dates=True)[list(RATES)])
    notes = json.loads((D / "bis_rates_meta.json").read_text(encoding="utf-8"))
    for c, a in out["areas"].items():
        a["name"], a["group"] = RATES[c]
        a["note"] = notes.get(c, "")
    return out


def on_calendar(px, cal):
    """미국 일별 자료를 한국 달력(cal)에 얹는다. 날짜는 미국 날짜 그대로다(하루 늦추지 않는다).

    - 한국이 쉰 날의 미국 거래는 그 뒤 첫 한국 거래일에 합친다(시가는 첫날, 고가·저가는 묶음 전체, 종가는 마지막 날, 거래량은 합).
      버리면 그 사이의 등락이 사라지지는 않지만(종가는 이어진다) 고가·저가·거래량이 빠진다.
    - 미국이 쉰 날은 전날 종가를 잇고 등락률 0으로 둔다.
    """
    px = px[px.index >= cal[0]]  # 달력 시작 전 거래가 첫날 한 칸에 몽땅 합쳐지지 않게
    pos = cal.searchsorted(px.index)
    ok = pos < len(cal)
    out = px[ok].groupby(cal[pos[ok]]).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum")).reindex(cal)
    out["volume"] = out["volume"].fillna(0)
    out["close"] = out["close"].ffill()
    for c in ("open", "high", "low"):
        out[c] = out[c].fillna(out["close"])
    out["chg"] = out["close"].pct_change() * 100
    return out


def flows(key, px):
    """투자자별 순매수. 종목은 주식 수(*_sh, 수정주가 기준)와 금액 어림(*_val, 조원), 지수는 금액(조원)만.
    미국 대상은 받을 경로가 없어 전부 빈 값이다.

    adj: 네이버 수급의 종가·주식 수는 액면분할 전 값 그대로다(삼성전자 2018년 50:1).
    수정주가와의 비율로 분할 배수를 구해 주식 수를 지금 기준으로 맞춘다. 금액은 어느 쪽으로 곱해도 같다.
    수급은 2005년부터라 adj 도 그때부터만 있다. 그 앞의 분할 배수는 잴 방법이 없다.
    """
    cols = [f"{who}_{u}" for who in WHO for u in ("sh", "val")] + ["foreign_ratio", "adj", "close_adj"]
    if ASSETS[key]["market"] == "us":
        return pd.DataFrame(np.nan, index=px.index, columns=cols)
    f = pd.read_csv(D / f"naver_flow_{key}.csv", index_col=0, parse_dates=True)
    out = pd.DataFrame(index=f.index)
    if ASSETS[key]["kind"] == "index":
        for who in WHO:
            out[f"{who}_sh"] = np.nan
            out[f"{who}_val"] = f[f"{who}_val"] / 1e4  # 억원 -> 조원
        out["foreign_ratio"] = np.nan
        out["close_adj"] = np.nan
        return out
    adj = (f["close"] / px["close"].reindex(f.index)).round().ffill().bfill()
    for who in WHO:
        out[f"{who}_sh"] = f[f"{who}_net"] * adj
        out[f"{who}_val"] = f[f"{who}_net"] * f["close"] / 1e12
    out["foreign_ratio"] = f["foreign_ratio"]
    out["adj"] = adj
    out["close_adj"] = f["close"] / adj
    return out
