"""analyze.py 와 signals.py 가 같이 쓰는 데이터 읽기. 같은 파일을 두 군데서 다르게 읽으면 탭마다 값이 어긋난다."""
from pathlib import Path

import numpy as np
import pandas as pd

from assets import ASSETS

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
