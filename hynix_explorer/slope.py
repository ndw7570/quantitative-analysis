"""탭 6 "회귀 추세": 로그 종가를 날짜(0, 1, 2, ...)에 회귀한 기울기로 추세를 잰다. 기울기(하루 몇 % -> 연율 %)가 방향·속도,
t-값(기울기가 0 과 다르다는 확신. 보통 2 를 넘으면 추세로 본다)이 세기, R²(점들이 선에 얼마나 붙는가)가 곧음이다.

창 길이가 문제다. 두 가지 길을 둔다.
  자동(합의 길이): 창 WINS(20·40·60·120·250거래일) 다섯에 날마다 회귀를 돌린다. 20일 창의 기울기 방향과 같은 방향이 이어지는
    가장 긴 창이 그날의 창이다("20일부터 W일까지 전부 같은 방향 = 그 방향의 추세가 W일째"). 꺾인 직후에는 20일, 이어질수록 길어진다.
    처음에는 |t| 가 가장 큰 창을 고르려 했는데 t 는 같은 추세라도 창이 길수록 커져서(창 길이의 제곱근에 비례) 거의 늘 250일 창이
    뽑히고 코스피 7,445일 중 7,436일이 "상승"이 됐다. R² 가 가장 큰 창도 큰 상승 뒤 몇 달 동안 250일 창이 "가장 곧아" 급락 중에도
    상승으로 남았다(2026-11-27 실험). 최근성을 규칙에 직접 넣어야 했다.
  직접: 화면의 슬라이더로 W_MIN~W_MAX 아무 길이. 길이가 임의라 화면(template.html)이 같은 식을 자바스크립트로 계산한다.
그래서 계산의 기준 구현은 여기 두고, build.py 가 여기서 만든 기준값(마지막 날의 창별 값과 자동 창의 상태 일수)을 HTML 에 넣는다.
화면이 뜰 때 자기 계산과 견줘 다르면 오류를 던지고, check.py 의 화면 검사가 그 오류를 잡는다.

상태: 자동은 합의 길이가 L_MIN(40) 이상이고 그 창의 |t| >= T_IN 이면 그 방향, 들어간 뒤에는 길이가 L_MIN 아래로 떨어지거나 |t| < T_OUT 이거나
방향이 바뀌면 보합. 직접은 그 창의 t 로 같은 문턱(T_IN 에 들어가고 T_OUT 안쪽에서 나온다 - 탭 5 와 같은 히스테리시스).
그날까지의 종가만 쓴다. 예측이 아니다. 창 안이 직선이라고 보는 것이라 창 안에 꺾임이 있으면 기울기는 그 사이의 평균이다.
t 의 문턱 2 는 독립 표본의 기준이고 주가처럼 이어지는 자료에서는 실제보다 크게 나온다 - 긴 창은 거의 늘 2 를 넘는다. 직접 고르기에서
250일 창을 두면 그렇게 보인다. 세기의 '눈금'으로만 읽는다.
"""
import json

import numpy as np
import pandas as pd

from assets import ASSETS
from common import D
from trend import runs

WINS = [20, 40, 60, 120, 250]
W_MIN, W_MAX = 10, 250   # 슬라이더 범위. 10 아래는 자유도가 너무 적다
L_MIN = 40               # 자동: 합의 길이가 이만큼은 돼야 추세로 친다(20일 창 하나로는 너무 자주 뒤집힌다)
T_IN, T_OUT = 2.0, 1.0
YEAR = 252


def rolling_ols(y, w):
    """y(로그 종가, 빈 값 없음) 의 길이 w 창마다 (기울기/일, t-값, R²). 앞의 w-1 칸은 NaN.

    누적합으로 한 번에 센다(창마다 회귀를 다시 돌리면 7,400일 x 창 5개가 느리다). 자바스크립트도 같은 순서로 더해야 값이 맞는다.
    x 는 창 안의 자리 0..w-1 이라 Sxx = w(w²-1)/12 로 고정이다.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    out = np.full((3, n), np.nan)
    if n < w or w < 3:
        return out
    k = np.arange(n, dtype=float)
    p1, p2, pk = (np.concatenate([[0.0], np.cumsum(v)]) for v in (y, y * y, k * y))
    sxx = w * (w * w - 1) / 12.0
    for i in range(w - 1, n):
        s, e = i - w + 1, i + 1
        sy, syy, sky = p1[e] - p1[s], p2[e] - p2[s], pk[e] - pk[s]
        sxy = (sky - s * sy) - (w - 1) / 2.0 * sy  # Σ(x - x̄)·y 에서 x = k - s, x̄ = (w-1)/2
        sst = syy - sy * sy / w
        b = sxy / sxx
        sse = max(sst - b * sxy, 0.0)
        se = np.sqrt(sse / (w - 2) / sxx)
        out[0, i] = b
        out[1, i] = b / se if se > 0 else (0.0 if b == 0 else np.inf)
        out[2, i] = 1 - sse / sst if sst > 0 else 0.0
    return out


def annual(b):
    """하루 기울기(로그) -> 연율 %."""
    return (np.exp(b * YEAR) - 1) * 100


def consensus(res):
    """res: {창: rolling_ols 결과} -> (날마다 고른 창의 WINS 자리 또는 None, 상태 'up'/'flat'/'down'/None).

    20일 창의 기울기 방향과 같은 방향이 이어지는 가장 긴 창. 20일 창이 없는 날(앞의 19일)은 None.
    긴 창이 아직 없는 날(예: 40일째 전)은 있는 창까지만 본다.
    """
    n = len(res[WINS[0]][0])
    pick, st, cur = [], [], "flat"
    for i in range(n):
        b20 = res[WINS[0]][0][i]
        if np.isnan(b20):
            pick.append(None)
            st.append(None)
            continue
        sg, L = (1 if b20 > 0 else -1 if b20 < 0 else 0), 0
        for j, w in enumerate(WINS):
            b = res[w][0][i]
            if np.isnan(b) or (1 if b > 0 else -1 if b < 0 else 0) != sg:
                break
            L = j
        w, d = WINS[L], ("up" if sg > 0 else "down" if sg < 0 else "flat")
        t = res[w][1][i]
        if cur != "flat" and (w < L_MIN or abs(t) < T_OUT or cur != d):
            cur = "flat"
        if cur == "flat" and w >= L_MIN and abs(t) >= T_IN and d != "flat":
            cur = d
        pick.append(L)
        st.append(cur)
    return pick, st


def slope_states(t):
    """직접 고른 창 하나의 t-값 -> 'up'/'flat'/'down' (없으면 None). T_IN 을 넘어 들어가고 T_OUT 안쪽에서 나온다."""
    out, cur = [], "flat"
    for v in t:
        if v is None or np.isnan(v):
            out.append(None)
            continue
        if cur != "flat" and abs(v) < T_OUT:
            cur = "flat"
        if cur == "flat":
            cur = "up" if v >= T_IN else "down" if v <= -T_IN else "flat"
        out.append(cur)
    return out


def slope_one(series):
    """한 대상의 기준값: 마지막 날의 창별 값과, 자동 창의 상태 일수·구간 수·창별 선택 일수. 화면의 자기 검사가 이것과 견준다."""
    close = pd.Series(series["close"], dtype=float)
    first = int(close.first_valid_index())
    y = np.log(close.iloc[first:].to_numpy())
    res = {w: rolling_ols(y, w) for w in WINS}
    pick, st = consensus(res)
    return {"first": first, "n": len(y),
            "last": {str(w): {"slope": float(res[w][0][-1]), "t": float(res[w][1][-1]), "r2": float(res[w][2][-1])} for w in WINS},
            "auto": {"days": {k: sum(1 for s in st if s == k) for k in ("up", "flat", "down")}, "runs": len(runs(st)),
                     "wins": {str(w): sum(1 for j in pick if j is not None and WINS[j] == w) for w in WINS}}}


def slope_data():
    out = {"params": {"wins": WINS, "w_min": W_MIN, "w_max": W_MAX, "l_min": L_MIN, "t_in": T_IN, "t_out": T_OUT, "year": YEAR}, "ref": {}}
    for k in ASSETS:
        series = json.loads((D / f"result_{k}.json").read_text(encoding="utf-8"))["series"]
        out["ref"][k] = slope_one(series)
    return out


if __name__ == "__main__":
    d = slope_data()
    for k, r in d["ref"].items():
        print("=====", k, "자동 창 상태 일수", r["auto"]["days"], "구간", r["auto"]["runs"], "창 선택", r["auto"]["wins"])
        print("  마지막 날:", " · ".join(f"{w}일 {annual(v['slope']):+.1f}%/년 t {v['t']:+.1f} R² {v['r2']:.2f}" for w, v in r["last"].items()))
