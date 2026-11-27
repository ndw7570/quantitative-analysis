"""탭 5 "추세 상태": 종가 하나로 날마다 6가지 상태(상승·급상승·보합·요동·하락·급하락)를 매기고, 그 규칙이 과거에 얼마나 늦었고
그 뒤에 무엇이 왔는지를 센다. analyze.py 의 result_<대상>.json(종가)을 읽으므로 그 뒤에 돈다. build.py 가 trend_data() 를 HTML 에 넣고
check.py 가 같은 값인지 대조한다(탭 4 의 인상기 분석과 같은 길).

규칙(두 축):
  방향 = DIR_N 거래일 수익률. DIR_IN 을 넘으면 상승(하락)으로 들어가고, 들어간 뒤에는 DIR_OUT 안쪽으로 되돌아와야 보합으로 나온다.
         문턱 하나로 하면 그 언저리에서 날마다 상태가 바뀐다(히스테리시스 - 들어가는 문턱과 나오는 문턱을 다르게 둔다).
  세기 = VOL_N 거래일 변동성(일 수익률 표준편차)이 지난 VOL_REF 거래일 동안의 그 변동성 중위값의 VOL_IN 배를 넘으면 "급". 나올 때는 VOL_OUT 배.
  상승+급 = 급상승, 하락+급 = 급하락, 보합+급 = 요동(방향 없이 크게 흔들리는 때 - 2020년 3월 바닥 같은 때).
예측이 아니다. 그날까지의 종가만 쓰므로 "그날 알 수 있었던 상태"이고, 전환점보다 늦다. 얼마나 늦는지가 통계의 요점이다.
문턱값은 처음 정한 값이고 자료로 맞추지 않았다(맞추면 과거에만 맞는 값이 된다). 바꾸면 테스트와 README 의 숫자를 같이 바꾼다.
"""
import json

import numpy as np
import pandas as pd

from assets import ASSETS
from common import D

DIR_N, DIR_IN, DIR_OUT = 60, 8.0, 4.0
VOL_N, VOL_REF, VOL_IN, VOL_OUT = 20, 252, 1.5, 1.2
HI_N = 252          # "진입 때 고점(저점) 대비": 지난 1년의 최고(최저) 종가
FWD = (21, 63)      # 진입 뒤 수익률을 보는 거래일(약 1달, 3달)
STATES = ["surge", "up", "flat", "chop", "down", "crash"]
NAMES = {"surge": "급상승", "up": "상승", "flat": "보합", "chop": "요동", "down": "하락", "crash": "급하락"}
DIRS = {"surge": "up", "up": "up", "flat": "flat", "chop": "flat", "down": "down", "crash": "down"}


def direction(r):
    """수익률 배열 -> 'up'/'flat'/'down' (값이 없는 날은 None). 들어가는 문턱 DIR_IN, 나오는 문턱 DIR_OUT."""
    out, cur = [], "flat"
    for v in r:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
            continue
        if cur == "up" and v < DIR_OUT:
            cur = "flat"
        elif cur == "down" and v > -DIR_OUT:
            cur = "flat"
        if cur == "flat":
            cur = "up" if v >= DIR_IN else "down" if v <= -DIR_IN else "flat"
        out.append(cur)
    return out


def intensity(vol, ref):
    """변동성과 그 기준(중위값) 배열 -> 급(True)/아님(False). 값이 없는 날은 None."""
    out, hot = [], False
    for v, m in zip(vol, ref):
        if v is None or m is None or np.isnan(v) or np.isnan(m) or m <= 0:
            out.append(None)
            continue
        hot = v > m * VOL_IN if not hot else v > m * VOL_OUT
        out.append(hot)
    return out


def measures(close):
    """종가 -> (DIR_N 수익률 %, VOL_N 변동성 %, 변동성의 VOL_REF 중위값 %). 빈 날(상장 전)은 빼고 재서 되돌려 놓는다."""
    c = close.dropna()
    r = (c / c.shift(DIR_N) - 1) * 100
    vol = (np.log(c).diff() * 100).rolling(VOL_N).std()
    # 중위값은 그날을 빼고 그 전 VOL_REF 일로 잰다 - 오늘의 급등락이 오늘의 기준을 올리면 안 된다
    ref = vol.shift(1).rolling(VOL_REF).median()
    return [s.reindex(close.index) for s in (r, vol, ref)]


def states(close):
    """종가(빈 값 허용) -> 날마다 상태 코드(STATES) 또는 None."""
    r, vol, ref = measures(close)
    d, hot = direction(r.tolist()), intensity(vol.tolist(), ref.tolist())
    out = []
    for a, b in zip(d, hot):
        if a is None or b is None:
            out.append(None)
        elif b:
            out.append({"up": "surge", "flat": "chop", "down": "crash"}[a])
        else:
            out.append(a)
    return out


def runs(st):
    """상태 목록 -> [(시작 번호, 끝 번호, 상태)]. None 은 구간을 끊는다."""
    out, a = [], None
    for i, s in enumerate(list(st) + [None]):
        if a is not None and (s != st[a]):
            out.append((a, i - 1, st[a]))
            a = None
        if s is not None and a is None:
            a = i
    return out


def _pct(c, i, j):
    return None if i < 0 or j >= len(c) or pd.isna(c[i]) or pd.isna(c[j]) or not c[i] else float(c[j] / c[i] - 1) * 100


def _r(v, n=1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


def _agg(vals):
    v = [x for x in vals if x is not None]
    return {"n": len(v), "mean": _r(np.mean(v)) if v else None, "med": _r(np.median(v)) if v else None,
            "pos": _r(np.mean([x > 0 for x in v]) * 100, 0) if v else None}


def trend_stats(close, st):
    """상태마다: 일수, 구간 수, 지속 일수 중위값, 진입(구간 첫날) 기준 FWD 거래일 뒤 수익률, 진입 때 지난 1년 고점(저점) 대비,
    진입 뒤 63일 안의 최저(최고). "그 신호를 보고 움직였으면"을 재는 것이라 구간 첫날만 센다."""
    c = close.to_numpy(dtype=float)
    hi = pd.Series(c).rolling(HI_N, min_periods=1).max().to_numpy()
    lo = pd.Series(c).rolling(HI_N, min_periods=1).min().to_numpy()
    rs = runs(st)
    total = sum(1 for s in st if s is not None)
    out = {}
    for code in STATES:
        mine = [r for r in rs if r[2] == code]
        days = sum(b - a + 1 for a, b, _ in mine)
        ent = [a for a, _, _ in mine if a > 0]
        fwd = {str(n): _agg([_pct(c, a, a + n) for a in ent]) for n in FWD}
        # 하락 쪽은 "고점에서 얼마나 내려온 뒤에 신호가 켜졌나", 상승 쪽은 저점 대비. 보합·요동은 둘 다 뜻이 약해 고점 대비만 적는다
        base = lo if DIRS[code] == "up" else hi
        late = [None if np.isnan(c[a]) or not base[a] else float(c[a] / base[a] - 1) * 100 for a in ent]
        # 신호 뒤 63일 안에 더 간 폭: 하락 쪽은 최저까지, 상승 쪽은 최고까지(그 뒤 얼마나 더 남아 있었나)
        more = []
        for a in ent:
            w = c[a + 1:a + FWD[-1] + 1]
            w = w[~np.isnan(w)]
            if len(w) and c[a]:
                more.append(float((w.min() if DIRS[code] == "down" else w.max()) / c[a] - 1) * 100)
        out[code] = {"days": days, "share": _r(days / total * 100) if total else None, "runs": len(mine),
                     "med_len": _r(np.median([b - a + 1 for a, b, _ in mine]), 0) if mine else None,
                     "fwd": fwd, "late": _agg(late), "more": _agg(more)}
    return out


def agreement(st, trend, regime):
    """analyze.py 의 이동평균 추세(up/flat/down)·HMM 국면(0~2)과 얼마나 같은 말을 하나. 둘 다 있는 날만."""
    both = [(a, b) for a, b in zip(st, trend) if a is not None and b is not None]
    hv = [a for a, g in zip(st, regime) if a is not None and g == 2]
    return {"ma": _r(np.mean([DIRS[a] == b for a, b in both]) * 100) if both else None,
            "hv": _r(np.mean([a in ("surge", "chop", "crash") for a in hv]) * 100) if hv else None}


def trend_one(series):
    close = pd.Series(series["close"], index=pd.to_datetime(series["date"]), dtype=float)
    r, vol, ref = measures(close)
    st = states(close)
    return {"state": [None if s is None else STATES.index(s) for s in st],
            "r": [_r(v) for v in r], "vol": [_r(v, 2) for v in vol], "ref": [_r(v, 2) for v in ref],
            "stats": trend_stats(close, st), "agree": agreement(st, series["trend"], series["regime"])}


def trend_data():
    out = {"params": {"dir_n": DIR_N, "dir_in": DIR_IN, "dir_out": DIR_OUT, "vol_n": VOL_N, "vol_ref": VOL_REF,
                      "vol_in": VOL_IN, "vol_out": VOL_OUT, "hi_n": HI_N, "fwd": list(FWD)},
           "states": STATES, "names": NAMES, "assets": {}}
    for k in ASSETS:
        series = json.loads((D / f"result_{k}.json").read_text(encoding="utf-8"))["series"]
        out["assets"][k] = trend_one(series)
    return out


if __name__ == "__main__":
    t = trend_data()
    for k, a in t["assets"].items():
        print("=====", k, "일치: 이동평균 추세", a["agree"]["ma"], "% · HMM 고변동일 중 급", a["agree"]["hv"], "%")
        rows = []
        for code in STATES:
            s = a["stats"][code]
            rows.append({"상태": NAMES[code], "일수": s["days"], "비율%": s["share"], "구간": s["runs"], "중위지속": s["med_len"],
                         "21일뒤 평균": s["fwd"]["21"]["mean"], "21일뒤 상승%": s["fwd"]["21"]["pos"],
                         "63일뒤 평균": s["fwd"]["63"]["mean"], "63일뒤 상승%": s["fwd"]["63"]["pos"],
                         "진입때 고/저점대비": s["late"]["med"], "63일안 더감(중위)": s["more"]["med"]})
        print(pd.DataFrame(rows).to_string(index=False))
