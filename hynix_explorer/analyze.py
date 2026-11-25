"""30년 분석 (탭 1 "기간 비교"용) - assets.py 의 모든 대상에 같은 모델을 적용해 data/result_<대상>.json 을 만든다.

모델은 1년 보고서(hynix_report/analyze.py)와 같다. 다른 점은 계수를 "분석 구간 직전 2년으로 한 번" 추정하던 것을
"매년 1월, 직전 2년으로 다시" 추정한다는 것이다(ARIMA, GARCH, 시장모형 민감도).
30년을 한 벌의 계수로 덮으면 1997년 계수로 2026년을 재게 되기 때문이다.
대상마다 상장일이 달라서 시작 연도가 다르다 - 직전 2년 자료가 MIN_TRAIN 거래일 이상 있는 첫 해부터 계산한다.
그날 알 수 있었던 정보만 쓴다는 원칙은 같다. HMM 과 변화점은 사후 계산이다.
"""
import json
import warnings

import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.api as sm
from arch import arch_model
from hmmlearn.hmm import GaussianHMM
from statsmodels.tsa.arima.model import ARIMA

from assets import ASSETS, BENCH, CMP_ENT, NAMES, dec
from common import D, flows, on_calendar, prices, us

warnings.filterwarnings("ignore")
SHOW_FROM = "1997-01-01"  # 화면에 보여 주는 첫날. 그 앞은 계수 추정용
TRAIN_YEARS = 2
# 직전 2년에 이만큼 거래일이 없으면 그 해는 계산하지 않는다(상장한 지 얼마 안 된 해).
# 2년은 490~590거래일이다(1998년까지는 토요일에도 장이 열렸다). 1년 남짓한 자료로 추정한 계수를 2년치와 섞지 않으려는 기준이다.
MIN_TRAIN = 400

# ---------- 공통 달력과 비교용 가격 ----------
KR = [k for k, a in ASSETS.items() if a["market"] == "kr"]
US = [k for k, a in ASSETS.items() if a["market"] == "us"]
PX = {k: prices(k) for k in KR}
# 모든 대상이 같은 달력(코스피가 열린 날)을 쓴다. 상장 전인 날은 그 대상만 빈 값이다.
# 화면에서 왼쪽·오른쪽 창이 서로 다른 대상을 같은 날짜 번호로 다루기 때문이다.
# 한 종목이 거래정지된 날(삼성전자 2018년 액면분할 때 3일)은 빼지 않고 전날 종가를 이어 붙인다.
# 그날을 달력에서 빼면 다른 대상의 결과까지 바뀐다.
cal = PX["kospi"].index
cal.name = "date"
for k in US:
    PX[k] = on_calendar(prices(k), cal)
kr_lv = pd.DataFrame({k: PX[k]["close"].reindex(cal).ffill() for k in KR})


def us_close(name, same_day):
    sx = us(name).rename(name).rename_axis("us_date").reset_index()
    m = pd.merge_asof(pd.DataFrame({"date": cal}), sx, left_on="date", right_on="us_date", allow_exact_matches=same_day)
    return m[name].values


# 미국 값을 어느 날짜에 붙이느냐가 보는 쪽에 따라 다르다. 그래서 가격표를 두 벌 만든다.
#  kr: 한국 대상용. 미국 장은 한국 장이 끝난 뒤 열리므로, 한국 t일에 영향을 주는 것은 "t일 이전 마지막" 미국 종가다.
#  us: 미국 대상용. 같은 날짜의 미국 종가. 한국 t일 종가는 미국 t일 장이 열리기 전에 이미 나와 있으므로 한국 값도 같은 날짜다.
LV = {m: kr_lv.assign(**{n: us_close(n, m == "us") for n in [*BENCH, *US]}) for m in ("kr", "us")}
LRET = {m: np.log(LV[m]).diff() * 100 for m in LV}


def analyze(key):
    a = ASSETS[key]
    lv, lret = LV[a["market"]], LRET[a["market"]]
    df = PX[key].reindex(cal).copy()
    df["close"] = df["close"].ffill()
    for c in ("open", "high", "low"):  # 거래정지일: 가격은 전날 종가, 등락률 0
        df[c] = df[c].fillna(df["close"])
    df["chg"] = df["chg"].fillna(0)
    df["ret"] = lret[key]
    x1, x2 = a["reg"]
    df["x1_ret"], df["x2_ret"] = lret[x1], lret[x2]
    # 설명 변수가 없는 날은 버리지 않는다. 버리면 삼성전자가 SK하이닉스 상장(1996-12) 전을 통째로 잃는다.
    # 그런 해는 고유분만 비워 두고 나머지 모델은 계산한다.
    df = df.dropna(subset=["ret"])

    # ---------- 추세 ----------
    for n in (20, 60, 120):
        df[f"ma{n}"] = df["close"].rolling(n).mean()
    score = (np.sign(df["close"] - df["ma20"]) + np.sign(df["ma20"] - df["ma60"])
             + np.sign(df["ma60"] - df["ma60"].shift(10)))
    df["trend"] = np.select([score >= 3, score <= -3], ["up", "down"], "flat")

    # ---------- 매년 다시 추정: ARIMA, GARCH, 시장모형 ----------
    logp = np.log(df["close"])
    for c in ("ar_lo", "ar_hi", "gvol", "gz", "g_lo", "g_hi", "abn"):
        df[c] = np.nan
    coef, first = [], None
    for year in range(int(SHOW_FROM[:4]), df.index.max().year + 1):
        tr = df.loc[f"{year - TRAIN_YEARS}-01-01":f"{year - 1}-12-31"]
        ap = df.loc[f"{year - TRAIN_YEARS}-01-01":f"{year}-12-31"]  # 추정 구간 + 적용 연도. 필터가 이어지도록 붙여서 돌린다
        yr = ap.loc[f"{year}-01-01":].index
        if len(yr) == 0 or len(tr) < MIN_TRAIN:
            continue
        first = first or yr[0]

        ar = ARIMA(logp.loc[tr.index].values, order=(1, 1, 1)).fit()
        pred = ar.apply(logp.loc[ap.index].values).get_prediction(start=1)
        ci = pd.DataFrame(pred.conf_int(alpha=0.05), index=ap.index[1:])
        df.loc[yr, "ar_lo"], df.loc[yr, "ar_hi"] = np.exp(ci.loc[yr, 0]), np.exp(ci.loc[yr, 1])

        gp = arch_model(tr["ret"], mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t").fit(disp="off").params
        gv = arch_model(ap["ret"], mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t").fix(gp).conditional_volatility
        df.loc[yr, "gvol"] = gv.loc[yr]
        df.loc[yr, "gz"] = (df.loc[yr, "ret"] - gp["mu"]) / gv.loc[yr]
        prev = df["close"].shift(1).loc[yr]
        df.loc[yr, "g_lo"] = prev * np.exp((gp["mu"] - 1.96 * gv.loc[yr]) / 100)
        df.loc[yr, "g_hi"] = prev * np.exp((gp["mu"] + 1.96 * gv.loc[yr]) / 100)

        trx = tr.dropna(subset=["x1_ret", "x2_ret"])
        b1 = b2 = r2 = None
        if len(trx) >= MIN_TRAIN:
            ols = sm.OLS(trx["ret"], sm.add_constant(trx[["x1_ret", "x2_ret"]])).fit()
            b1, b2, r2 = (round(float(v), 2) for v in (ols.params["x1_ret"], ols.params["x2_ret"], ols.rsquared))
            df.loc[yr, "abn"] = (df.loc[yr, "ret"] - ols.params["x1_ret"] * df.loc[yr, "x1_ret"]
                                 - ols.params["x2_ret"] * df.loc[yr, "x2_ret"])
        coef.append({
            "year": year, "train": f"{tr.index[0].date()} ~ {tr.index[-1].date()}", "n": int(len(tr)),
            "ar_sigma": round(float(np.sqrt(ar.params[-1]) * 100), 2),
            "g_alpha": round(float(gp["alpha[1]"]), 3), "g_gamma": round(float(gp["gamma[1]"]), 3),
            "g_beta": round(float(gp["beta[1]"]), 3),
            "b1": b1, "b2": b2, "r2": r2,
        })
    df["ar_out"] = (df["close"] < df["ar_lo"]) | (df["close"] > df["ar_hi"])
    df["g_out"] = df["gz"].abs() > 1.96

    # ---------- HMM (전체 기간, 사후) ----------
    df["rv10"] = df["ret"].rolling(10).std()
    feat = df[["ret", "rv10"]].dropna()
    # 거래정지가 10거래일 넘게 이어지면(HD한국조선해양 2017년 분할 때 25일) 등락률이 계속 0 이라 rv10 이 0 이 되고
    # 로그가 음의 무한대가 된다. 그 날들은 거래가 없었으니 국면을 매기지 않고 비워 둔다.
    feat = feat[feat["rv10"] > 0]
    X = np.column_stack([feat["ret"], np.log(feat["rv10"])])
    X = (X - X.mean(0)) / X.std(0)
    best = None
    for seed in range(10):  # EM 은 시작점에 따라 다른 답에 멈춘다. 여러 번 돌려 가장 잘 맞은 것을 쓴다
        h = GaussianHMM(n_components=3, covariance_type="full", n_iter=500, random_state=seed).fit(X)
        if best is None or h.score(X) > best[0]:
            best = (h.score(X), h)
    states = pd.Series(best[1].predict(X), index=feat.index)
    order = feat.groupby(states)["rv10"].mean().sort_values().index.tolist()  # 변동폭 순으로 번호를 고정
    df["regime"] = states.map({old: new for new, old in enumerate(order)})

    # ---------- 수급 ----------
    f = flows(key, PX[key]).reindex(df.index)
    for c in ("foreign_sh", "inst_sh", "indiv_sh", "foreign_val", "inst_val", "indiv_val", "foreign_ratio"):
        df[c] = f[c]
    ent = list(dict.fromkeys([*CMP_ENT, key]))  # 비교선 후보 + 자기 자신(검은 선)
    for c in ent:
        df["c_" + c] = lv[c]

    # ---------- 화면 구간으로 자르고 변화점 (사후) ----------
    w = df.loc[first:].copy()  # 이 대상의 첫 계산 연도부터
    # jump=1: 기본값(5)은 5거래일 간격으로만 경계 후보를 본다. 그러면 시작일이 달라질 때 결과가 달라져서
    # 1년만 돌린 것과 10년을 돌린 것이 서로 다른 날짜를 낸다(실제로 그랬다). 하루 단위로 보면 둘이 일치한다.
    bk = rpt.Pelt(model="normal", min_size=15, jump=1).fit(w["ret"].values.reshape(-1, 1)).predict(pen=12)
    w["cp"] = False
    w.iloc[[i for i in bk[:-1]], w.columns.get_loc("cp")] = True

    p = dec(key)
    num = {"open": p, "high": p, "low": p, "close": p, "chg": 2, "ma20": p, "ma60": p, "ma120": p,
           "ar_lo": p, "ar_hi": p, "g_lo": p, "g_hi": p, "gvol": 2, "gz": 2, "abn": 2, "regime": 0,
           "foreign_sh": 0, "inst_sh": 0, "indiv_sh": 0, "foreign_val": 3, "inst_val": 3, "indiv_val": 3,
           "foreign_ratio": 2, **{"c_" + c: dec(c) for c in ent}, "x1_ret": 2, "ret": 3}
    # 화면은 모든 대상이 같은 날짜 목록을 쓴다. 이 대상이 시작하기 전의 날은 빈 값으로 채워 길이를 맞춘다.
    full = w.reindex(cal[cal >= SHOW_FROM])
    series = {"date": [d.strftime("%Y-%m-%d") for d in full.index]}
    for c, nd in num.items():
        series[c] = [None if pd.isna(x) else (int(round(x)) if nd == 0 else round(float(x), nd)) for x in full[c]]
    series["trend"] = [None if pd.isna(x) else x for x in full["trend"]]
    for c in ("ar_out", "g_out", "cp"):
        series[c] = [int(x) for x in full[c].fillna(False).astype(bool)]

    out = {"series": series, "coef": coef, "meta": {
        "key": key, "name": a["name"], "kind": a["kind"], "market": a["market"], "group": a["group"], "reg": [NAMES[x1], NAMES[x2]],
        # 화면 표기: 단위와 보여 줄 소수 자릿수. 수급 자료가 없는 대상은 차트·팝업에서 0 이 아니라 "자료 없음"으로 보여야 한다.
        "unit": "" if a["kind"] == "index" else ("원" if a["market"] == "kr" else "달러"), "dec": min(p, 2),
        "has_flow": a["market"] == "kr", "cmp": a["cmp"],
        # start: 이 대상의 값이 있는 첫날. 날짜 목록(series.date)은 그보다 앞에서 시작할 수 있다.
        "start": w.index[0].strftime("%Y-%m-%d"), "end": series["date"][-1], "days": len(w),
        "train_years": TRAIN_YEARS, "changepoints": int(w["cp"].sum())}}
    (D / f"result_{key}.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    print("=====", key, out["meta"])
    print(pd.DataFrame(coef).to_string(index=False))
    print("결측 수", {c: int(w[c].isna().sum()) for c in num if w[c].isna().sum()})
    y = w.groupby(w.index.year)
    print(pd.DataFrame({
        "days": y.size(), "ret%": y["close"].last() / y["open"].first() * 100 - 100,
        "std": y["ret"].std(), "ar_out%": y["ar_out"].mean() * 100, "g_out%": y["g_out"].mean() * 100,
        "gvol": y["gvol"].mean(), "hv_days": y["regime"].apply(lambda s: (s == 2).sum()),
        "cp": y["cp"].sum(), "foreign조": y["foreign_val"].sum(), "abn": y["abn"].sum()}).round(1).to_string())


for k in ASSETS:
    analyze(k)
