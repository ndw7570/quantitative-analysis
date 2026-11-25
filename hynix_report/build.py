"""result.json + template.html -> 보고서 HTML 한 파일.

본문 숫자는 전부 result.json 에서 채운다. 글에 숫자를 손으로 적으면 데이터를 다시 받았을 때
차트와 글이 서로 다른 값을 말하게 된다.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
R = json.loads((HERE / "data" / "result.json").read_text(encoding="utf-8"))
S, SM = R["series"], R["summary"]
df = pd.DataFrame({k: v for k, v in S.items() if k != "p_regime"}).set_index("date")
df.index = pd.to_datetime(df.index)

# 수익률 축에서 두 범위를 비교하려고 가격 범위를 "전일 종가 대비 %"로 바꾼다.
prev = df["close"] / (1 + df["chg"] / 100)
for k in ("ar_lo", "ar_hi", "g_lo", "g_hi"):
    S[k + "_pct"] = [None if pd.isna(x) else round(float(x), 2) for x in (df[k] / prev - 1) * 100]

peak = pd.Timestamp(SM["peak_date"])
pre, post = df.loc[:peak], df.loc[peak:].iloc[1:]


def row(d, what, live):
    r = df.loc[d]
    return {"date": d.strftime("%Y-%m-%d"), "what": what, "close": float(r["close"]),
            "from_peak": round(float((r["close"] / SM["peak_close"] - 1) * 100), 1),
            # 고점 전 신호는 "고점 대비 -45%"라고 쓰면 하락한 것처럼 읽힌다. 그 뒤 얼마나 더 올랐는지로 적는다.
            "to_peak": round(float((SM["peak_close"] / r["close"] - 1) * 100), 1),
            "before": bool(d < peak), "live": live}


reg = df["regime"]
hv_start = reg[(reg == 2) & (reg.shift() != 2)].loc[:peak].index[-1]
cp_before = max(pd.Timestamp(c) for c in R["changepoints"] if pd.Timestamp(c) <= peak)
tr = post["trend"]
first_flat, first_down = tr[tr != "up"].index[0], tr[tr == "down"].index[0]
signals = [
    row(hv_start, "HMM 이 고변동 국면으로 분류하기 시작", False),
    row(cp_before, "변화점 탐지가 찾은 전환 시점", False),
    row(peak, "종가 고점", None),
    row(first_flat, "추세 규칙이 상승에서 보합으로 변경", True),
    row(first_down, "추세 규칙이 처음 하락으로 판정", True),
]

flow = pd.read_csv(HERE / "data" / "naver_flow.csv", index_col=0, parse_dates=True).loc[:SM["end_date"]]
dr = flow["foreign_ratio"].diff()
jumps = [{"date": d.strftime("%Y-%m-%d"), "dr": round(float(dr[d]), 2),
          "net": float(flow.loc[d, "foreign_net"]), "ratio": float(flow.loc[d, "foreign_ratio"])}
         for d in dr[dr.abs() > 1].loc[SM["start_date"]:].index]
fw = flow.loc[SM["start_date"]:]

R["extra"] = {
    "ar_band": round(1.96 * SM["ar_sigma"], 1),
    "trend_flips": int((df["trend"] != df["trend"].shift()).sum() - 1),
    "signals": signals, "jumps": jumps,
    "pre_days": int(len(pre)), "post_days": int(len(post)),
    "foreign_per_day_pre": round(float(pre["foreign_val"].sum() / len(pre)), 2),
    "foreign_per_day_post": round(float(post["foreign_val"].sum() / len(post)), 2),
    "foreign_shares_pre": round(float(fw.loc[:peak, "foreign_net"].sum() / 1e6), 1),
    "foreign_shares_post": round(float(fw.loc[peak:, "foreign_net"].iloc[1:].sum() / 1e6), 1),
    "foreign_shares_per_day_pre": round(float(fw.loc[:peak, "foreign_net"].mean() / 1e4), 1),
    "foreign_shares_per_day_post": round(float(fw.loc[peak:, "foreign_net"].iloc[1:].mean() / 1e4), 1),
    "events_samsung_worst": min(e["samsung"] for e in R["events"]),
    "events_samsung_best": max(e["samsung"] for e in R["events"]),
    "events_abn_worst": min(e["abn"] for e in R["events"]),
    "events_abn_best": max(e["abn"] for e in R["events"]),
    "events_foreign_sell": sum(1 for e in R["events"] if e["foreign"] < 0),
    "events_indiv_buy": sum(1 for e in R["events"] if e["indiv"] > 0),
    "events_sox_mild": sum(1 for e in R["events"] if e["sox"] > -3),
    "events_gz_over2": sum(1 for e in R["events"] if abs(e["gz"]) > 1.96),
    "regime2_share": round(R["regimes"][2]["days_win"] / SM["days"] * 100),
    "hv_days_before_peak": int(len(df.loc[hv_start:peak]) - 1),
    "flat_days_after_peak": int(len(df.loc[peak:first_flat]) - 1),
}

out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
html = (HERE / "template.html").read_text(encoding="utf-8")
assert html.count("__DATA__") == 1
# NaN 은 JSON 표준이 아니라 브라우저에서 파싱이 깨진다. 남아 있으면 여기서 멈춘다.
out.write_text(html.replace("__DATA__", json.dumps(R, ensure_ascii=False, allow_nan=False)), encoding="utf-8")
print(out, out.stat().st_size, "bytes")
print(json.dumps(R["extra"], ensure_ascii=False, indent=1))
