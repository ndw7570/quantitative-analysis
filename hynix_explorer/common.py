"""analyze.py 와 signals.py 가 같이 쓰는 데이터 읽기. 같은 파일을 두 군데서 다르게 읽으면 탭마다 값이 어긋난다."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from assets import ASSETS, RATES, YEAR_IX

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


def year_close(key):
    """탭 3 에서 고르는 지수(assets.YEAR_IX)의 종가. 그 시장의 달력 그대로다 - 한국 달력에 얹지 않는다.
    얹으면 미국의 한 해를 날짜대로 그릴 수 없다(한국이 쉰 날의 미국 종가가 다음 날로 밀린다)."""
    if YEAR_IX[key]["market"] == "us":
        return us(key)
    return pd.read_csv(D / f"naver_px_{key}.csv", index_col=0, parse_dates=True)["close"].dropna()


def year_data():
    """탭 3 에 싣는 것 전부: 지수마다 year_paths. 달력 칸(days)은 모든 지수가 같아서 한 번만 싣는다.
    build.py 와 check.py 가 같이 쓴다 - 따로 만들면 "HTML 에 든 값이 자료와 같은가"를 비교할 수 없다.
    지수마다 첫 해와 마지막 날(end)이 다르다. 코스닥은 1996-07 부터 있어 1997년이 첫 해다."""
    idx = {}
    for k, a in YEAR_IX.items():
        p = year_paths(year_close(k))
        idx[k] = {"name": a["name"], "market": a["market"], "end": p["end"], "years": p["years"]}
    return {"days": YEAR_DAYS, "idx": idx}


RATE_FILL = 31  # 이 날수까지 빈 곳은 직전 값을 잇는다. 받은 자료에서 연휴로 빈 가장 긴 곳이 15일이었다(태국 2020-11, 2026-11-26 확인)


def rate_steps(wide):
    """나라마다 정책금리가 "바뀐 날"만 남긴다(탭 4 "주요국 정책금리"). 화면이 이것을 하루 칸으로 다시 편다.

    정책금리는 계단 모양이라 하루 값 1만여 개 대신 바뀐 날 수십~수백 개면 같은 그림이 나온다.
    wide: 날짜가 줄, 나라 부호가 열인 일별 표(fetch.rates 가 만든 bis_rates.csv).
    - 주말·연휴처럼 짧게 빈 곳(RATE_FILL 일까지)은 직전 값을 잇는다.
    - 그보다 길게 빈 곳은 통째로 비운다. 일본은 몇 해씩 비어 있는 기간이 세 번 있고 BIS 가 그중 2013-04 ~ 2016-09 를 "no policy rate"로 적어 두었다. 이으면 없던 금리를 그리게 된다.
    - 나라마다 마지막 날이 달라도 뒤를 메우지 않는다. 그 사이에 금리가 바뀌었을 수 있다. 선은 받은 날(last)에서 끝난다.
    - 앞도 자르지 않는다. 나라마다 받은 첫날부터 싣는다(전에는 1995년부터만 실었다). start 는 가장 이른 나라의 첫날이고 화면의 가로축이 거기서 시작한다.
    steps: [[날짜, 값], ...]. 그날부터 다음 단계 전날(마지막 단계는 last)까지 그 값이다. 값이 None 이면 그 동안 정책금리가 없다.
    """
    areas = {}
    for c in wide.columns:
        have = wide[c].dropna()
        if have.empty:
            continue
        s = wide[c].reindex(pd.date_range(have.index[0], have.index[-1]))
        run = s.isna().groupby(s.notna().cumsum()).transform("sum")  # 각 날이 속한 빈 구간의 길이
        s = s.ffill().where(s.notna() | (run <= RATE_FILL)).round(4)
        prev = s.shift()
        turn = s.ne(prev) & ~(s.isna() & prev.isna())  # NaN 은 자기 자신과도 다르다고 나와서 따로 뺀다
        areas[c] = {"last": have.index[-1].strftime("%Y-%m-%d"),
                    "steps": [[d.strftime("%Y-%m-%d"), None if pd.isna(v) else float(v)] for d, v in s[turn].items()]}
    return {"start": min(a["steps"][0][0] for a in areas.values()), "end": max(a["last"] for a in areas.values()), "areas": areas}


def cpi_months(s, start):
    """한 나라의 소비자물가 상승률을 화면에 싣는 모양으로: {"from": 첫 달, "v": [달마다 값]}. 실을 값이 없으면 None.

    s: 달(YYYY-MM)이 색인인 값(fetch.cpi 가 만든 bis_cpi.csv 의 한 열). start(YYYY-MM) 앞은 버린다 - 화면의 가로축이 정책금리의 첫날에서 시작한다.
    첫 값이 있는 달부터 마지막 값이 있는 달까지 한 달도 빼지 않고 싣는다(v 의 k 번째가 from 에서 k 달 뒤다).
    빈 달은 None 으로 두고 메우지 않는다 - 금리와 달리 직전 값이 이어진다고 볼 근거가 없다. 화면이 빈 달의 앞뒤를 곧게 잇는다.
    """
    s = s.loc[start:].dropna()
    if s.empty:
        return None
    months = pd.period_range(s.index[0], s.index[-1], freq="M").strftime("%Y-%m")
    return {"from": months[0], "v": [None if pd.isna(v) else float(v) for v in s.reindex(months).round(2)]}


def rate_data():
    """탭 4 에 싣는 것 전부: rate_steps 에 화면 이름·묶음(assets.RATES), BIS 의 금리 설명, 같은 나라의 소비자물가 상승률(cpi)을 붙인다.
    물가를 따로 싣지 않고 나라 안에 넣은 것은 화면이 나라를 고르면 금리와 물가를 같이 그리기 때문이다.
    build.py 와 check.py 가 같이 쓴다 - 따로 만들면 "HTML 에 든 값이 자료와 같은가"를 비교할 수 없다."""
    out = rate_steps(pd.read_csv(D / "bis_rates.csv", index_col=0, parse_dates=True)[list(RATES)])
    notes = json.loads((D / "bis_rates_meta.json").read_text(encoding="utf-8"))
    cpi = pd.read_csv(D / "bis_cpi.csv", index_col=0)
    cpi.index = cpi.index.astype(str)
    for c, a in out["areas"].items():
        a["name"], a["group"] = RATES[c]
        a["note"] = notes.get(c, "")
        a["cpi"] = cpi_months(cpi[c], out["start"][:7]) if c in cpi.columns else None
    return out


# ---------- 탭 4 "인상기 분석" (P014-012) ----------
HIKE_MIN = 3  # 사이에 인하 없이 이 횟수 이상 연속으로 올리면 "인상기"로 센다. 물어본 것이 "3회 연속 인상이면"이었다
HIKE_FROM = "1990-01-01"  # 미국은 1985-12 까지 시장 금리(날마다 움직임)라 그 시절은 횟수를 셀 수 없다. 자료가 1954년부터인 미국만 걸린다
HIKE_IX = {"US": "spx", "KR": "kospi"}  # 나라 -> 정점 뒤 수익률을 잴 지수(assets.YEAR_IX 의 키)
HIKE_AFTER = (91, 182, 365)  # 정점 뒤 며칠 뒤의 수익률을 보나(석 달·여섯 달·한 해)
HIKE_DROP = -10.0  # 인상기 중 지수가 이보다 내려가면 신호
REAL_WINDOW = 12  # 실질금리가 이 달수 안에 0 을 넘어왔으면 "양수 전환"


def rate_changes(steps, start=HIKE_FROM):
    """정책금리가 바뀐 날: [(날짜, 바뀐 뒤 값, 변화폭 %p)]. start 앞은 뺀다. 값이 없는 기간(None)의 앞뒤는 변화로 치지 않는다."""
    out, prev = [], None
    for d, v in steps:
        if v is None:
            prev = None
            continue
        if prev is not None and d >= start and v != prev:
            out.append((d, v, round(v - prev, 4)))
        prev = v
    return out


def rate_on(steps, date):
    """그날의 정책금리(그날까지의 마지막 단계 값). 자료 앞이면 None."""
    v = None
    for d, x in steps:
        if d > date:
            break
        v = x
    return v


def _pct(close, t0, days=0):
    """t0 이후 첫 종가에서 t0 + days 이후 첫 종가까지의 수익률(%). 어느 쪽이든 없으면 None."""
    a = close[close.index >= t0]
    b = close[close.index >= pd.Timestamp(t0) + pd.Timedelta(days, "D")] if days else a
    if a.empty or b.empty:
        return None
    return round(float(b.iloc[0] / a.iloc[0] - 1) * 100, 1)


def hike_cycles(changes, close):
    """연속 인상기: [{n, first, peak, rate, low, cut, hold, ix_hike, after: {일수: 수익률}, mdd}].
    - n: 인상 횟수, first·peak: 첫·마지막 인상일, rate: 정점 금리, low: 첫 인상 전 금리, cut: 정점 뒤 첫 인하일(아직 없으면 None), hold: 정점 ~ 첫 인하 일수
    - ix_hike: 첫 인상일 -> 정점의 지수 수익률, after: 정점 뒤 HIKE_AFTER 일의 수익률, mdd: 정점 뒤 182일 안 최저 종가까지의 하락률
    지수는 그 시장의 달력 그대로라 "그 날 이후 첫 종가"로 잰다.
    """
    out, cur = [], []

    def done(cur, cut):
        (f, v0, dv0), (p, vp, _) = cur[0], cur[-1]
        win = close[(close.index >= p) & (close.index <= pd.Timestamp(p) + pd.Timedelta(182, "D"))]
        out.append({"n": len(cur), "first": f, "peak": p, "rate": vp, "low": round(v0 - dv0, 4), "cut": cut,
                    "hold": (pd.Timestamp(cut) - pd.Timestamp(p)).days if cut else None,
                    "ix_hike": _pct(close, f, (pd.Timestamp(p) - pd.Timestamp(f)).days) if p != f else 0.0,
                    "after": {str(k): _pct(close, p, k) for k in HIKE_AFTER},
                    "mdd": round(float(win.min() / win.iloc[0] - 1) * 100, 1) if len(win) else None})

    for d, v, dv in changes:
        if dv > 0:
            cur.append((d, v, dv))
            continue
        if len(cur) >= HIKE_MIN:
            done(cur, d)
        cur = []
    if len(cur) >= HIKE_MIN:
        done(cur, None)
    return out


def hike_board(steps, last, cpi, close, cycles):
    """신호판 4개. 예측이 아니라 "지금이 과거 인상기의 어느 자리인가"다. 켜짐(on)과 그 근거 숫자를 같이 준다.
    s1 인상기 진입: 끝에서부터 연속 인상이 HIKE_MIN 회 이상.
    s2 정점 미확인: 마지막 변경이 인상이고, 그 뒤 지난 날수가 과거 인상기의 가장 짧은 정점 유지(hold)보다 짧다.
    s3 실질금리 양수 전환: 금리 - 물가 상승률이 REAL_WINDOW 달 안에 0 이하에서 0 위로 넘어왔다.
    s4 인상기 중 지수 하락: 지금 연속 인상의 첫 인상일 뒤 지수가 HIKE_DROP % 아래.
    """
    ch = rate_changes(steps)
    streak = 0
    while streak < len(ch) and ch[-1 - streak][2] > 0:
        streak += 1
    lastc = ch[-1] if ch else None
    since = (pd.Timestamp(last) - pd.Timestamp(lastc[0])).days if lastc else None
    holds = [c["hold"] for c in cycles if c["hold"] is not None]
    s1 = {"on": streak >= HIKE_MIN, "streak": streak, "from": ch[-streak][0] if streak else None,
          "last": lastc[0] if lastc else None, "delta": lastc[2] if lastc else None, "rate": rate_on(steps, last)}
    s2 = {"on": bool(streak and holds and since < min(holds)), "since": since, "min_hold": min(holds) if holds else None}
    # 실질금리: 달마다 그 달 마지막 날의 금리 - 그 달의 물가 상승률. 0 이하 -> 0 위로 넘어온 마지막 달을 찾는다
    s3 = {"on": False, "real": None, "cpi": None, "month": None, "up": None}
    if cpi:
        months = pd.period_range(cpi["from"], periods=len(cpi["v"]), freq="M")
        real = []
        for m, v in zip(months, cpi["v"]):
            r = rate_on(steps, min(m.end_time.strftime("%Y-%m-%d"), last))
            if v is not None and r is not None:
                real.append((m.strftime("%Y-%m"), round(r - v, 3), v))
        if real:
            s3["month"], s3["real"], s3["cpi"] = real[-1]
            up = None
            for k in range(1, len(real)):
                if real[k - 1][1] <= 0 < real[k][1]:
                    up = real[k][0]
            if s3["real"] > 0 and up:
                s3["up"] = up
                s3["on"] = (pd.Period(s3["month"], "M") - pd.Period(up, "M")).n < REAL_WINDOW
    ix = _pct(close, s1["from"], (close.index[-1] - pd.Timestamp(s1["from"])).days) if streak else None
    s4 = {"on": bool(streak and ix is not None and ix < HIKE_DROP), "ret": ix}
    return {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "count": sum(s["on"] for s in (s1, s2, s3, s4))}


def hike_data(rates):
    """탭 4 "인상기 분석"에 싣는 것 전부. rates 는 rate_data() 의 결과(같은 것을 두 번 계산하지 않으려고 받는다).
    build.py 와 check.py 가 같이 쓴다."""
    out = {"min": HIKE_MIN, "from": HIKE_FROM, "after": list(HIKE_AFTER), "drop": HIKE_DROP, "window": REAL_WINDOW, "areas": {}}
    for c, ix in HIKE_IX.items():
        a = rates["areas"][c]
        close = year_close(ix)
        cycles = hike_cycles(rate_changes(a["steps"]), close)
        out["areas"][c] = {"name": a["name"], "ix": YEAR_IX[ix]["name"], "ix_end": close.index[-1].strftime("%Y-%m-%d"),
                           "cycles": cycles, "board": hike_board(a["steps"], a["last"], a.get("cpi"), close, cycles)}
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
