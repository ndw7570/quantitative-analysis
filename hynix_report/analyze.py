"""하이닉스 최근 1년 분석 - 추세, ARIMA, GARCH, HMM, 변화점, 수급, 상대 수익률.

원칙: 모델의 계수는 가능하면 분석 구간 "이전" 데이터로만 추정한다(ARIMA, GARCH, 시장모형).
분석 구간 데이터로 계수를 맞추면 "그날 이미 알 수 있었던 것"과 "지나고 나서 안 것"이 섞인다.
그렇게 못 한 것(HMM, 변화점)은 결과에 insample=True 로 표시해 보고서에 그대로 적는다.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import ruptures as rpt
import statsmodels.api as sm
from arch import arch_model
from hmmlearn.hmm import GaussianHMM
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import acf

warnings.filterwarnings("ignore")
D = Path(__file__).parent / "data"
WIN_START = "2025-11-20"  # 분석 구간 시작. 이 날짜 앞은 계수 추정용


def yf(name):
    return pd.read_csv(D / f"yf_{name}.csv", index_col=0, parse_dates=True)["Close"].dropna()


# ---------- 데이터 ----------
px = pd.read_csv(D / "krx_ohlcv.csv", index_col=0, parse_dates=True)
px.columns = ["open", "high", "low", "close", "volume", "chg"]
px = px[px["volume"] > 0]
flow = pd.read_csv(D / "naver_flow.csv", index_col=0, parse_dates=True)
sox = yf("sox")
# 한국 쪽은 야후를 쓰지 않는다: 하이닉스 종가가 KRX 와 52일 어긋났고 마지막 날이 비어 있었다.
kospi = pd.read_csv(D / "naver_kospi.csv", index_col=0, parse_dates=True)["close"]
samsung = pd.read_csv(D / "krx_samsung.csv", index_col=0, parse_dates=True)["종가"]

df = px.copy()
df["ret"] = np.log(df["close"]).diff() * 100  # 로그수익률(%). 더해도 되는 수익률이라 누적 계산이 쉽다
df["kospi"] = kospi.reindex(df.index).ffill()
df["samsung"] = samsung.reindex(df.index).ffill()
# 미국 장은 한국 장이 끝난 뒤 열린다. 한국 t일에 영향을 주는 것은 "t일 이전 마지막" 미국 종가다.
sox_df = sox.rename("sox").reset_index().rename(columns={"Date": "us_date", "index": "us_date"})
sox_df.columns = ["us_date", "sox"]
m = pd.merge_asof(df.reset_index().rename(columns={df.index.name: "date"})[["date"]],
                  sox_df, left_on="date", right_on="us_date", allow_exact_matches=False)
df["sox"] = m["sox"].values
for c in ("kospi", "samsung", "sox"):
    df[c + "_ret"] = np.log(df[c]).diff() * 100
df = df.dropna(subset=["ret"])
pre, win = df.loc[:WIN_START].iloc[:-1], df.loc[WIN_START:]
W = win.index

# ---------- 1. 추세 ----------
for n in (20, 60, 120):
    df[f"ma{n}"] = df["close"].rolling(n).mean()
# 세 가지 질문에 각각 +1/-1: 가격이 단기선 위인가, 단기선이 중기선 위인가, 중기선이 오르는 중인가
score = (np.sign(df["close"] - df["ma20"]) + np.sign(df["ma20"] - df["ma60"])
         + np.sign(df["ma60"] - df["ma60"].shift(10)))
df["trend"] = np.select([score >= 3, score <= -3], ["up", "down"], "flat")
df["dd"] = (df["close"] / df["close"].loc[WIN_START:].cummax() - 1) * 100

# ---------- 자기상관: 왜 수익률은 ARIMA 가 약한가 ----------
def ac(s):
    s = s.dropna()
    a = acf(s, nlags=5)
    lb = acorr_ljungbox(s, lags=[5])["lb_pvalue"].iloc[0]
    return {"lag1": round(float(a[1]), 3), "lag5": round(float(a[5]), 3), "lb_p": float(lb)}


w = df.loc[W]
acf_tbl = {
    "ret": ac(w["ret"]),
    "abs_ret": ac(w["ret"].abs()),
    "log_vol": ac(np.log(w["volume"])),
}

# ---------- 2. ARIMA: 정상 범위 ----------
logp = np.log(df["close"])
arima = ARIMA(logp.loc[pre.index], order=(1, 1, 1)).fit()
ar_all = arima.apply(logp)  # 계수는 과거 구간 것으로 고정하고 전체에 한 걸음씩 적용
pred = ar_all.get_prediction(start=1)
ci = pred.conf_int(alpha=0.05)
df["ar_mid"] = np.exp(pred.predicted_mean)
df["ar_lo"], df["ar_hi"] = np.exp(ci.iloc[:, 0]), np.exp(ci.iloc[:, 1])
df["ar_out"] = (df["close"] < df["ar_lo"]) | (df["close"] > df["ar_hi"])
ar_sigma = float(np.sqrt(arima.params["sigma2"]) * 100)

# ---------- 3. GARCH: 변동성 ----------
gm_pre = arch_model(pre["ret"], mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t").fit(disp="off")
gm = arch_model(df["ret"], mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t").fix(gm_pre.params)
df["gvol"] = gm.conditional_volatility  # 그날 아침 기준 예상 일간 변동성(%)
df["gz"] = (df["ret"] - gm_pre.params["mu"]) / df["gvol"]  # 예상 변동성 대비 실제 움직임이 몇 배였나
df["g_out"] = df["gz"].abs() > 1.96
df["g_lo"] = df["close"].shift(1) * np.exp((gm_pre.params["mu"] - 1.96 * df["gvol"]) / 100)
df["g_hi"] = df["close"].shift(1) * np.exp((gm_pre.params["mu"] + 1.96 * df["gvol"]) / 100)

# ---------- 4. HMM: 국면 ----------
df["rv10"] = df["ret"].rolling(10).std()
feat = df[["ret", "rv10"]].dropna()
X = np.column_stack([feat["ret"], np.log(feat["rv10"])])
X = (X - X.mean(0)) / X.std(0)
best = None
for seed in range(10):  # EM 은 시작점에 따라 다른 답에 멈춘다. 여러 번 돌려 가장 잘 맞은 것을 쓴다
    h = GaussianHMM(n_components=3, covariance_type="full", n_iter=500, random_state=seed).fit(X)
    s = h.score(X)
    if best is None or s > best[0]:
        best = (s, h)
hmm = best[1]
states = pd.Series(hmm.predict(X), index=feat.index)
# 국면 번호는 실행마다 임의로 붙는다. 평균 변동성 순으로 다시 이름을 붙여 고정한다
order = feat.groupby(states)["rv10"].mean().sort_values().index.tolist()
remap = {old: new for new, old in enumerate(order)}
df["regime"] = states.map(remap)
probs = pd.DataFrame(hmm.predict_proba(X)[:, order], index=feat.index)
reg_tbl = []
for k in range(3):
    r = df.loc[W][df.loc[W, "regime"] == k]
    allr = df[df["regime"] == k]
    reg_tbl.append({
        "k": k, "days_win": int(len(r)), "days_all": int(len(allr)),
        "mean": round(float(allr["ret"].mean()), 2), "std": round(float(allr["ret"].std()), 2),
    })
trans = hmm.transmat_[np.ix_(order, order)]

# ---------- 5. 변화점 ----------
sig = df.loc[W, "ret"].values.reshape(-1, 1)
bk = rpt.Pelt(model="normal", min_size=15).fit(sig).predict(pen=12)
cps = [W[i].strftime("%Y-%m-%d") for i in bk[:-1]]
seg_tbl, a = [], 0
for b in bk:
    seg = df.loc[W].iloc[a:b]
    seg_tbl.append({
        "start": seg.index[0].strftime("%Y-%m-%d"), "end": seg.index[-1].strftime("%Y-%m-%d"),
        "days": int(len(seg)), "mean": round(float(seg["ret"].mean()), 2),
        "std": round(float(seg["ret"].std()), 2),
        "cum": round(float((seg["close"].iloc[-1] / seg["open"].iloc[0] - 1) * 100), 1),
    })
    a = b

# ---------- 6. 수급 ----------
f = flow.reindex(df.index)
for who in ("foreign", "inst", "indiv"):
    val = f[f"{who}_net"] * df["close"] / 1e12  # 주식 수 x 종가 = 금액 근사(조원). 실제 체결가와는 다르다
    df[f"{who}_val"] = val
    df[f"{who}_cum"] = val.loc[W].cumsum()
    # 수급 값이 빈 날이 3일 있다. min_periods 없이 돌리면 그 하루 때문에 앞뒤 20일이 통째로 비게 된다.
    r20 = val.rolling(20, min_periods=15).sum()
    df[f"{who}_20"] = r20
    df[f"{who}_z"] = (r20 - r20.rolling(120, min_periods=80).mean()) / r20.rolling(120, min_periods=80).std()
df["foreign_ratio"] = f["foreign_ratio"]
df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean().shift(1)

# ---------- 7. 상대 수익률: 종목 탓인가 시장 탓인가 ----------
# 코스피는 기준으로 쓰지 않는다. 하이닉스가 코스피의 큰 부분이라 "코스피가 빠져서 하이닉스가 빠졌다"는
# 자기 자신으로 자기를 설명하는 꼴이 된다. 하이닉스가 들어 있지 않은 삼성전자와 미국 반도체지수를 쓴다.
p2 = df.loc[pre.index].dropna(subset=["samsung_ret", "sox_ret"])
ols = sm.OLS(p2["ret"], sm.add_constant(p2[["samsung_ret", "sox_ret"]])).fit()
expl = ols.params["samsung_ret"] * df["samsung_ret"] + ols.params["sox_ret"] * df["sox_ret"]
df["abn"] = df["ret"] - expl  # 시장·업종 움직임으로 설명되지 않는 부분. 절편은 뺐다(과거 평균 초과수익을 기대로 삼지 않으려고)
df["abn_cum"] = df["abn"].loc[W].cumsum()
base = df.loc[W].iloc[0]
for c in ("close", "kospi", "sox", "samsung"):
    df[c + "_idx"] = df[c] / base[c] * 100

# ---------- 8. 급락일 ----------
w = df.loc[W]
ev = []
for d, r in w.nsmallest(10, "chg").sort_index().iterrows():
    ev.append({
        "date": d.strftime("%Y-%m-%d"), "chg": round(float(r["chg"]), 1), "gz": round(float(r["gz"]), 2),
        "vol_ratio": round(float(r["vol_ratio"]), 2),
        "foreign": round(float(r["foreign_val"]), 2), "inst": round(float(r["inst_val"]), 2),
        "indiv": round(float(r["indiv_val"]), 2),
        "kospi": round(float(np.expm1(r["kospi_ret"] / 100) * 100), 1),
        "samsung": round(float(np.expm1(r["samsung_ret"] / 100) * 100), 1),
        "sox": round(float(np.expm1(r["sox_ret"] / 100) * 100), 1),
        "abn": round(float(r["abn"]), 1), "trend": r["trend"], "regime": int(r["regime"]),
    })

# ---------- 요약 ----------
last, peak_d = w.iloc[-1], w["close"].idxmax()
after = w.loc[peak_d:].iloc[1:]
summary = {
    "start_date": W[0].strftime("%Y-%m-%d"), "end_date": W[-1].strftime("%Y-%m-%d"), "days": int(len(w)),
    "start_close": float(w["close"].iloc[0]), "end_close": float(last["close"]),
    "peak_close": float(w["close"].max()), "peak_date": peak_d.strftime("%Y-%m-%d"),
    "low_close": float(w["close"].min()), "low_date": w["close"].idxmin().strftime("%Y-%m-%d"),
    "ret_1y": round(float((last["close"] / w["close"].iloc[0] - 1) * 100), 1),
    "dd_now": round(float(last["dd"]), 1),
    "daily_std": round(float(w["ret"].std()), 2), "daily_std_pre": round(float(pre["ret"].std()), 2),
    "trend_now": last["trend"], "regime_now": int(last["regime"]),
    "trend_days": {k: int(v) for k, v in w["trend"].value_counts().items()},
    "ma20": float(last["ma20"]), "ma60": float(last["ma60"]), "ma120": float(last["ma120"]),
    "ar_out_n": int(w["ar_out"].sum()), "ar_out_pct": round(float(w["ar_out"].mean() * 100), 1),
    "g_out_n": int(w["g_out"].sum()), "g_out_pct": round(float(w["g_out"].mean() * 100), 1),
    "ar_sigma": round(ar_sigma, 2), "ar_params": {k: round(float(v), 4) for k, v in arima.params.items()},
    "garch_params": {k: round(float(v), 4) for k, v in gm_pre.params.items()},
    "gvol_now": round(float(last["gvol"]), 2), "gvol_max": round(float(w["gvol"].max()), 2),
    "gvol_max_date": w["gvol"].idxmax().strftime("%Y-%m-%d"), "gvol_min": round(float(w["gvol"].min()), 2),
    "beta_samsung": round(float(ols.params["samsung_ret"]), 2), "beta_sox": round(float(ols.params["sox_ret"]), 2),
    "ols_r2": round(float(ols.rsquared), 2),
    "abn_cum_end": round(float(last["abn_cum"]), 1),
    "abn_cum_peak": round(float(w.loc[peak_d, "abn_cum"]), 1),
    "idx_end": {c: round(float(last[c + "_idx"]), 1) for c in ("close", "kospi", "sox", "samsung")},
    "flow_cum_end": {k: round(float(last[f"{k}_cum"]), 2) for k in ("foreign", "inst", "indiv")},
    "flow_cum_peak": {k: round(float(w.loc[peak_d, f"{k}_cum"]), 2) for k in ("foreign", "inst", "indiv")},
    "flow_after_peak": {k: round(float(after[f"{k}_val"].sum()), 2) for k in ("foreign", "inst", "indiv")},
    "flow_z_now": {k: round(float(w[f"{k}_z"].dropna().iloc[-1]), 2) for k in ("foreign", "inst", "indiv")},
    "flow_20_now": {k: round(float(w[f"{k}_20"].dropna().iloc[-1]), 2) for k in ("foreign", "inst", "indiv")},
    "foreign_sell_days_after_peak": int((after["foreign_val"] < 0).sum()), "days_after_peak": int(len(after)),
    "abn_after_peak": round(float(after["abn"].sum()), 1),
    "ret_after_peak": round(float((last["close"] / w["close"].max() - 1) * 100), 1),
    "samsung_after_peak": round(float((last["samsung"] / w.loc[peak_d, "samsung"] - 1) * 100), 1),
    "sox_after_peak": round(float((last["sox"] / w.loc[peak_d, "sox"] - 1) * 100), 1),
    "kospi_after_peak": round(float((last["kospi"] / w.loc[peak_d, "kospi"] - 1) * 100), 1),
    "foreign_ratio_start": float(w["foreign_ratio"].dropna().iloc[0]),
    "foreign_ratio_peak": float(w["foreign_ratio"].loc[:peak_d].dropna().iloc[-1]),
    "foreign_ratio_max": float(w["foreign_ratio"].max()),
    "foreign_ratio_max_date": w["foreign_ratio"].idxmax().strftime("%Y-%m-%d"),
    "foreign_ratio_end": float(w["foreign_ratio"].dropna().iloc[-1]),
    "trans": [[round(float(x), 3) for x in row] for row in trans],
}

cols = ["open", "high", "low", "close", "volume", "chg", "ma20", "ma60", "ma120", "trend", "dd",
        "ar_mid", "ar_lo", "ar_hi", "ar_out", "gvol", "gz", "g_out", "g_lo", "g_hi", "regime",
        "foreign_val", "inst_val", "indiv_val", "foreign_cum", "inst_cum", "indiv_cum",
        "foreign_20", "inst_20", "indiv_20", "foreign_z", "inst_z", "indiv_z", "foreign_ratio",
        "vol_ratio", "abn", "abn_cum", "close_idx", "kospi_idx", "sox_idx", "samsung_idx"]
w = df.loc[W, cols]
series = {"date": [d.strftime("%Y-%m-%d") for d in W]}
for c in cols:
    v = w[c]
    if v.dtype == bool or v.dtype == object:
        series[c] = [x if isinstance(x, str) else bool(x) for x in v]
    else:
        series[c] = [None if pd.isna(x) else round(float(x), 3) for x in v]
series["p_regime"] = [[round(float(x), 3) for x in probs.loc[d]] for d in W]

out = {"summary": summary, "acf": acf_tbl, "regimes": reg_tbl, "changepoints": cps,
       "segments": seg_tbl, "events": ev, "series": series}
(D / "result.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

print(json.dumps(summary, ensure_ascii=False, indent=1))
print("ACF", json.dumps(acf_tbl))
print("REG", reg_tbl)
print("CP", cps)
for s_ in seg_tbl:
    print(s_)
for e in ev:
    print(e)
tr = df.loc[W, "trend"]
chg = tr[tr != tr.shift()]
print("TREND CHANGES", [(d.strftime("%m-%d"), t) for d, t in chg.items()])
rg = df.loc[W, "regime"]
chg = rg[rg != rg.shift()]
print("REGIME CHANGES", [(d.strftime("%m-%d"), int(t)) for d, t in chg.items()])
print("NaN counts", {c: int(w[c].isna().sum()) for c in cols if w[c].isna().sum() > 0})
