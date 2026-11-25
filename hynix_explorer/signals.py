"""극단값 신호표(탭 2)용 지표 시계열 -> data/signals_<대상>.json.

방송 화면의 표(코스피 지표별 과거 극단값 비교 및 이후 수익률)와 같은 구성을 assets.py 의 대상마다 만든다.
여기서는 지표의 일별 값만 만든다. "극단 사례"를 고르고 표를 채우는 일은 화면(template.html)에서 한다.
기준일을 바꿔 가며 "그날까지의 정보만으로" 표를 다시 만들 수 있어야 하기 때문이다.
analyze.py 가 만든 result_<대상>.json 을 읽으므로 그 뒤에 돌린다.
"""
import json

import numpy as np
import pandas as pd

from assets import ASSETS, dec
from common import D, flows, on_calendar, prices

NOW = json.loads((D / "naver_now.json").read_text(encoding="utf-8"))

for key, a in ASSETS.items():
    px = prices(key)
    stock, kr = a["kind"] == "stock", a["market"] == "kr"
    if not kr:
        # 탭 1과 같은 종가를 쓰려고 미국 대상도 한국 달력에 얹는다. 탭 2는 12개월 지표 때문에 받은 달력 전체(1994-01~)를 쓴다.
        px = on_calendar(px, prices("kospi").index)
    fl = flows(key, px)
    close = px["close"]
    ret = np.log(close).diff()

    def roll12(s):
        """수급이 시작된 날부터 252거래일 합. 그 사이에 값이 없는 날(거래정지 등)은 0 으로 본다.

        수급이 시작되기 전(2005년 이전)은 0 이 아니라 빈 값이어야 한다 - 0 으로 채우면 "순매수 0"인 이력이 생긴다.
        """
        days = close.index[close.index >= s.first_valid_index()]
        return s.reindex(days).fillna(0).rolling(252).sum().reindex(close.index)

    ind = pd.DataFrame(index=close.index)
    if stock:
        # 일별 상장주식수 이력을 받을 경로가 없다(한국거래소 로그인 필요). 오늘의 주식 수(fetch.py now)를 전 기간에 쓴다.
        # 자사주 소각·증자가 있었던 과거에는 그만큼 어긋난다. 비율 지표의 분모로만 쓴다.
        shares = NOW[key]["shares"]
        if kr:
            ind["f12"] = roll12(fl["foreign_sh"]) / shares * 100
            # 가격만 수정주가이고 거래량은 분할 전 주식 수 그대로다(삼성전자 2018년 이전이 1/50로 나온다).
            # 분할 배수는 수급 자료가 있는 2005년부터만 잴 수 있어서 그 앞의 회전율은 비워 둔다
            # (SK하이닉스는 2003년 21:1 감자 전 거래량이 하루 3억 주로 온다 - 지금 주식 수로 나누면 뜻이 없다).
            vol = px["volume"] * fl["adj"].reindex(px.index).ffill()
        else:
            ind["f12"] = np.nan  # 미국 종목은 투자자별 수급을 받을 경로가 없다
            vol = px["volume"]  # 야후 거래량은 분할이 이미 반영돼 있다
        ind["turn"] = (vol.rolling(20).mean() / shares * 100).reindex(close.index)
    else:
        shares = None
        # 지수는 시가총액 이력이 없어 비율로 못 만든다. 코스피는 금액(조원) 그대로 둔다 - 시장이 커진 만큼 최근 값이 크게 나온다.
        ind["f12"] = roll12(fl["foreign_val"]) if kr else np.nan
        ind["turn"] = np.nan
    ind["dd"] = (close / close.rolling(252).max() - 1) * 100
    ind["vol12"] = ret.rolling(252).std() * np.sqrt(252) * 100
    ind["gap60"] = (close / close.rolling(60).mean() - 1) * 100

    r = json.loads((D / f"result_{key}.json").read_text(encoding="utf-8"))["series"]
    m = pd.DataFrame({"gvol": r["gvol"], "abn": r["abn"]}, index=pd.to_datetime(r["date"])).astype(float)
    ind["gvol"] = m["gvol"].reindex(close.index)
    ind["abn20"] = m["abn"].rolling(20).sum().reindex(close.index)

    # 12개월 낙폭이 채워진 날부터 보여 준다. 수급 지표(2006년~)와 모델 값은 그보다 늦게 시작하고 그 앞은 빈 값이다.
    ind = ind.loc[ind["dd"].first_valid_index():]
    close = close.loc[ind.index]
    out = {
        "date": [d.strftime("%Y-%m-%d") for d in ind.index],
        "close": [round(float(x), dec(key)) for x in close],
        "ind": {c: [None if pd.isna(x) else round(float(x), 3) for x in ind[c]] for c in ind.columns},
        "fund": {k: NOW[key].get(k) for k in ("pbr", "per", "div")} if stock else None,
        "shares": shares, "f12_unit": None if not kr else ("pct" if stock else "jo"),
    }
    (D / f"signals_{key}.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("=====", key, out["date"][0], "~", out["date"][-1], len(ind), "일", "주식수", shares and round(shares / 1e8, 2), "억")
    print(ind.describe().round(2).to_string())
    print(ind.tail(1).round(2).to_string())
