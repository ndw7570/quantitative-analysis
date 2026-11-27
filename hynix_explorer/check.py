"""결과 검사. update.py 가 분석 뒤와 HTML 을 만든 뒤에 한 번씩 부른다.

    python check.py              data/ 의 결과(result_*.json, signals_*.json)를 받은 원자료와 대조한다
    python check.py html <경로>  HTML 에 든 값이 data/ 와 같은지, 브라우저에서 오류 없이 그려지는지 본다

[오류]가 하나라도 있으면 종료 코드 1 로 끝난다. 그러면 update.py 가 멈추고 보고 있던 HTML 은 바뀌지 않는다.
[주의]는 멈추지 않는다 - 틀린 것은 아니지만 읽을 때 알아야 하는 것이다(수급이 아직 안 올라온 날 등).
분석 단계는 끝까지 돌아도 값이 틀릴 수 있어서 둔다. 2026-11-25 에 찾은 수급 누락(60거래일마다 하루)이 그런 경우였다.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from assets import ASSETS, KR_BENCH, RATES, YEAR_IX
from common import D, hike_data, prices, rate_data, year_close, year_data
from events import auto_rows_all, bad_reason, load_dart, load_events, load_sec
from slope import slope_data
from trend import trend_data

FLOW_FROM = pd.Timestamp("2005-01-03")  # 네이버 증권의 투자자별 수급이 시작되는 날
SHOW_FROM = "1997-01-01"
# 하루 등락률이 이보다 크면 알린다. 한국 종목은 가격제한폭(지금 30%)을 넘을 수 없으므로 넘었다면 수정주가가 튄 것이다.
BIG_MOVE = {("kr", "stock"): 30.5, ("kr", "index"): 15, ("us", "stock"): 60, ("us", "index"): 15}
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
# 처음 열었을 때 그려지는 차트 수. 화면 구성을 바꾸면 같이 고친다.
# 탭 1 이 15개(2026-11-25 에 센 값), 탭 3 이 1개, 탭 4 가 1개(정책금리와 소비자물가를 한 차트에. 숨겨진 채로도 한 번 그린다 - template.html 의 yearRender, rateRender).
MIN_CHARTS = 23
# 탭 3 의 한 해 수익률이 이 범위를 벗어나면 단위가 바뀌었거나 지수 기준이 중간에 달라진 것으로 본다.
# 받은 자료의 최고는 코스닥 1999년 +240.7%, 최저는 코스닥 2000년 -79.5% 다(2026-11-26 확인).
YEAR_RANGE = (-90, 400)
RATE_LATE = 45  # 정책금리가 이 날수 넘게 뒤처진 나라는 알린다. BIS 는 나라마다 며칠에서 몇 주 늦게 싣는다
CPI_LATE = 4  # 소비자물가가 이 달수 넘게 뒤처진 나라는 알린다. 호주는 분기에 한 번 와서 석 달까지 늦는다
# 탭 4 의 범위는 이 날 뒤의 값만 본다. 그 앞에는 진짜로 수백 % 를 넘긴 때가 있어 한 줄로 자를 수 없다
# (받은 자료: 정책금리 브라질 1990-02 790,799%, 스웨덴 1992-09 500%, 뉴질랜드 1985-03 265%, 러시아 1993-10 210%,
#  물가 브라질 1990-04 6,821%, 폴란드 1990-02 1,367%, 일본 1947-11 194% - 2026-11-26 확인. 중앙은행 발표와 대조하지는 않았다).
# 이 날 뒤로 받은 자료는 정책금리 -0.75(스위스·덴마크) ~ 57%(튀르키예 2002), 물가 -5.3(홍콩 2000년대 초) ~ 85.5%(튀르키예 2022)다.
RANGE_FROM, RATE_RANGE, CPI_RANGE = "2000-01", (-5, 100), (-10, 150)
# 지수(2010 = 100) 줄을 상승률로 잘못 읽으면 값이 100 안팎이라 위 범위에 걸리지 않는다. 그래서 가운데 값도 본다.
# 이 날 뒤 물가 상승률의 중앙값은 나라마다 0.2(일본) ~ 10.9%(튀르키예)다(2026-11-26 확인). 지수라면 중앙값이 수십을 넘는다.
CPI_MID = 30
errors = []


def err(msg):
    errors.append(msg)
    print("[오류]", msg, flush=True)


def warn(msg):
    print("[주의]", msg, flush=True)


def load(name):
    return json.loads((D / name).read_text(encoding="utf-8"))


def missing_flow_days(px_days, flow_days):
    """(가운데가 빠진 날, 뒤가 덜 온 날). 가격은 있는데 수급 줄이 없는 날을 둘로 가른다.

    가운데가 빠진 것은 수집 오류다. 뒤가 덜 온 것은 수급이 가격보다 늦게 올라오는 것이라 다음 실행에서 채워진다.
    """
    px_days = px_days[px_days >= FLOW_FROM]
    if len(flow_days) == 0:
        return list(px_days), []
    lost = px_days[px_days <= flow_days.max()].difference(flow_days)
    late = px_days[px_days > flow_days.max()]
    return list(lost), list(late)


def check_data():
    for k in ASSETS:
        for kind in ("result", "signals"):
            if not (D / f"{kind}_{k}.json").exists():
                err(f"{k}: {kind}_{k}.json 이 없다")
    if errors:
        return
    res = {k: load(f"result_{k}.json") for k in ASSETS}
    dates = res["kospi"]["series"]["date"]
    cal_end = pd.read_csv(D / "naver_px_kospi.csv", index_col=0, parse_dates=True).index.max().strftime("%Y-%m-%d")
    if dates != sorted(set(dates)) or dates[0] < SHOW_FROM:
        err(f"날짜 목록이 오름차순이 아니거나 겹치거나 {SHOW_FROM} 보다 앞에서 시작한다")
    if dates[-1] != cal_end:
        err(f"결과의 마지막 날 {dates[-1]} 이 받은 코스피 가격의 마지막 날 {cal_end} 과 다르다(분석이 옛 자료로 돌았다)")

    for k, r in res.items():
        s, m, a = r["series"], r["meta"], ASSETS[k]
        name = m["name"]
        if s["date"] != dates:  # 화면의 두 창은 같은 날짜 번호를 쓴다
            err(f"{name}: 날짜 목록이 코스피와 다르다")
            continue
        close = s["close"]
        i0 = next((i for i, v in enumerate(close) if v is not None), None)
        if i0 is None or dates[i0] != m["start"]:
            err(f"{name}: 첫 값이 있는 날과 meta.start({m['start']}) 가 다르다")
            continue
        if any(v is None or v <= 0 for v in close[i0:]):
            err(f"{name}: 시작일 뒤에 종가가 비었거나 0 이하인 날이 있다")
        for c in ("ar_lo", "ar_hi", "gvol", "gz", "g_lo", "g_hi", "ma20", "regime"):
            # 이동평균은 달력 첫날(1994)부터 계산돼 있어 화면 시작일에는 이미 채워져 있다.
            # 국면은 거래정지가 길었던 날만 비운다(analyze.py) - 그 수가 많으면 알린다.
            n = sum(v is None for v in s[c][i0:])
            if n and c != "regime":
                err(f"{name}: 시작일 뒤에 {c} 가 빈 날이 {n}일 있다")
            elif n > 60:
                warn(f"{name}: 국면(regime)이 빈 날이 {n}일 있다(거래정지가 길었던 기간)")
        for lo, hi in (("ar_lo", "ar_hi"), ("g_lo", "g_hi")):
            if any(x is not None and y is not None and x > y for x, y in zip(s[lo], s[hi])):
                err(f"{name}: {lo} 가 {hi} 보다 큰 날이 있다")
        years = [c["year"] for c in r["coef"]]
        if years != list(range(int(m["start"][:4]), int(dates[-1][:4]) + 1)):
            err(f"{name}: 계수를 추정한 연도가 시작 연도부터 올해까지 이어지지 않는다 {years[:3]}..{years[-3:]}")
        out = [v for v in s["g_out"][i0:]]
        rate = sum(out) / len(out) * 100
        if not 2 <= rate <= 10:  # 95% 범위이므로 5% 안팎이어야 한다
            warn(f"{name}: GARCH 95% 범위를 벗어난 날이 {rate:.1f}% 다(기대 5% 안팎)")
        lim = BIG_MOVE[(a["market"], a["kind"])]
        big = [(d, v) for d, v in zip(dates, s["chg"]) if v is not None and abs(v) > lim]
        if big:
            warn(f"{name}: 하루 등락률이 {lim}% 를 넘는 날 {len(big)}일 - " + ", ".join(f"{d} {v:+.1f}%" for d, v in big[:6])
                 + (" ..." if len(big) > 6 else ""))

        g = load(f"signals_{k}.json")
        if g["date"][-1] != dates[-1]:
            err(f"{name}: 탭 2 지표의 마지막 날 {g['date'][-1]} 이 탭 1({dates[-1]})과 다르다")
        if any(len(v) != len(g["date"]) for v in g["ind"].values()) or len(g["close"]) != len(g["date"]):
            err(f"{name}: 탭 2 지표의 길이가 날짜 수와 다르다")

    # ---------- 받은 원자료 ----------
    kr = [k for k, a in ASSETS.items() if a["market"] == "kr"]
    # 코스닥(KR_BENCH)은 대상이 아니라 수급이 없다. 가격의 마지막 날만 같이 본다.
    ends = {k: pd.read_csv(D / f"naver_px_{k}.csv", index_col=0, parse_dates=True).index.max()
            for k in [*kr, *KR_BENCH] if (D / f"naver_px_{k}.csv").exists()}
    if len(set(ends.values())) > 1:
        # 거래정지 중인 종목도 줄은 온다(거래량 0). 마지막 날이 다르면 그 종목만 덜 받은 것이다.
        err(f"한국 가격 파일의 마지막 날이 서로 다르다 {({k: str(v.date()) for k, v in ends.items()})}")
    for k in kr:
        px_days = prices(k).index
        flow_days = pd.read_csv(D / f"naver_flow_{k}.csv", index_col=0, parse_dates=True).index
        lost, late = missing_flow_days(px_days, flow_days)
        first = px_days[px_days >= FLOW_FROM][0]
        if flow_days.min() > first:
            err(f"{ASSETS[k]['name']}: 수급이 {flow_days.min().date()} 부터 있다({first.date()} 부터 있어야 한다)")
        if lost:
            err(f"{ASSETS[k]['name']}: 가격은 있는데 수급이 빠진 날 {len(lost)}일 - "
                + ", ".join(str(d.date()) for d in lost[:6]) + (" ..." if len(lost) > 6 else ""))
        if late:
            warn(f"{ASSETS[k]['name']}: 수급이 {flow_days.max().date()} 까지만 왔다(가격은 {px_days.max().date()} 까지). "
                 "화면의 마지막 날 수급이 비어 있다. 저녁에 다시 돌리면 채워진다")
    # 종가가 있는 마지막 날로 본다. 줄은 있는데 종가가 빈 날은 분석이 전날 값을 이어 쓰므로 "받은 날"이 아니다
    us_ends = {p.stem: pd.read_csv(p, index_col=0, parse_dates=True)["Close"].dropna().index.max()
               for p in sorted(D.glob("yf_*.csv"))}
    if len(set(us_ends.values())) > 1:
        err(f"미국 가격 파일의 마지막 날이 서로 다르다 {({k: str(v.date()) for k, v in us_ends.items()})}")
    gap = (max(ends.values()) - max(us_ends.values())).days
    if gap > 4:  # 주말·연휴를 끼면 며칠은 벌어진다
        warn(f"미국 가격이 한국 가격보다 {gap}일 뒤처져 있다")


def check_years():
    """탭 3 의 지수별 연초부터 수익률. 값이 틀려도 선은 멀쩡히 그려지므로 해가 이어지는지와 값의 범위를 본다."""
    files = {k: D / (f"yf_{k}.csv" if a["market"] == "us" else f"naver_px_{k}.csv") for k, a in YEAR_IX.items()}
    lost = [p.name for p in files.values() if not p.exists()]
    if lost:
        err(f"탭 3 에 쓸 지수 파일이 없다: {lost} (fetch.py kr_price us 로 받는다)")
        return
    for k, a in year_data()["idx"].items():
        yrs, name = list(a["years"]), a["name"]
        if yrs != [str(y) for y in range(int(yrs[0]), int(a["end"][:4]) + 1)]:
            err(f"탭 3 {name}: 해가 이어지지 않는다 {yrs[:3]}..{yrs[-3:]}")
        for y, v in a["years"].items():
            have = [x for x in v if x is not None]
            if y != a["end"][:4] and len(have) != len(v):
                err(f"탭 3 {name}: 끝난 해 {y}년에 빈 칸이 {len(v) - len(have)}개 있다")
            if min(have) < YEAR_RANGE[0] or max(have) > YEAR_RANGE[1]:
                err(f"탭 3 {name}: {y}년 수익률이 {min(have)} ~ {max(have)} % 다(단위나 지수 기준이 중간에 바뀌었다)")
        if k in ASSETS:
            continue  # 대상인 지수(코스피·나스닥)의 하루 등락은 check_data 가 이미 본다
        chg = year_close(k).pct_change() * 100
        big = chg[chg.abs() > BIG_MOVE[(a["market"], "index")]]
        if len(big):
            warn(f"탭 3 {name}: 하루 등락률이 {BIG_MOVE[(a['market'], 'index')]}% 를 넘는 날 {len(big)}일 - "
                 + ", ".join(f"{d.date()} {v:+.1f}%" for d, v in big.iloc[:6].items()) + (" ..." if len(big) > 6 else ""))


def check_rates():
    """탭 4 의 정책금리와 소비자물가. 값이 틀려도 화면은 멀쩡히 그려지므로 범위와 날짜를 본다."""
    lost = [f for f in ("bis_rates.csv", "bis_cpi.csv") if not (D / f).exists()]
    if lost:
        err(f"탭 4 에 쓸 파일이 없다: {lost} (fetch.py rates cpi 로 받는다)")
        return
    r = rate_data()

    def off(vals, lim):
        return bool(vals) and (min(vals) < lim[0] or max(vals) > lim[1])

    cpi_end = {}
    for c, (name, _) in RATES.items():
        a = r["areas"].get(c)
        if a is None:
            err(f"정책금리 {name}: 값이 하나도 없다")
            continue
        vals = [v for d, v in a["steps"] if v is not None and d >= RANGE_FROM]
        if off(vals, RATE_RANGE):
            err(f"정책금리 {name}: {RANGE_FROM} 뒤의 값이 {min(vals)} ~ {max(vals)} % 다(단위가 바뀌었거나 다른 줄을 읽었다)")
        late = (pd.Timestamp(r["end"]) - pd.Timestamp(a["last"])).days
        if late > RATE_LATE:
            warn(f"정책금리 {name}: {a['last']} 까지만 왔다(가장 늦게까지 온 나라는 {r['end']}). 그 뒤에 바뀐 금리는 화면에 없다")
        p = a.get("cpi")
        if not p:
            err(f"소비자물가 {name}: 값이 하나도 없다")
            continue
        months = pd.period_range(p["from"], periods=len(p["v"]), freq="M").strftime("%Y-%m")
        cpi_end[name] = months[-1]
        vals = [v for m, v in zip(months, p["v"]) if v is not None and m >= RANGE_FROM]
        if off(vals, CPI_RANGE) or (vals and sorted(vals)[len(vals) // 2] > CPI_MID):
            err(f"소비자물가 {name}: {RANGE_FROM} 뒤의 상승률이 {min(vals)} ~ {max(vals)} %, 가운데 값 {sorted(vals)[len(vals) // 2]} % 다(단위가 바뀌었거나 다른 줄을 읽었다)")
    for name, m in cpi_end.items():
        if (pd.Period(max(cpi_end.values()), "M") - pd.Period(m, "M")).n > CPI_LATE:
            warn(f"소비자물가 {name}: {m} 까지만 왔다(가장 늦게까지 온 나라는 {max(cpi_end.values())})")


def check_events():
    """events/events.csv 의 자동 줄(금리 변경일)이 지금 BIS 자료와 같은지. 다르면 events.py 를 안 돌린 것이다."""
    rows = load_events()
    want = auto_rows_all(rate_data(), load_sec(), load_dart())
    have = [r for r in rows if r["checked"] == "auto"]
    if have != want:
        err(f"events/events.csv 의 자동 줄({len(have)}개)이 BIS·SEC·DART 자료로 다시 만든 것({len(want)}개)과 다르다 - python events.py 를 돌린다")
    if not load_dart():
        warn("data/dart_list.json 이 없다 - 한국 종목의 공시 줄이 사건 표에 없다(DART 키를 .env 에 넣고 fetch.py dart 로 받는다)")
    if not load_sec():
        warn("data/sec_8k.json 이 없다 - 미국 종목의 공시 줄이 사건 표에 없다(fetch.py sec 로 받는다)")
    bad = [(r, bad_reason(r)) for r in rows if r["checked"] != "auto"]
    bad = [(r, w) for r, w in bad if w]
    if bad:
        err(f"events/events.csv 에 모양이 틀린 줄 {len(bad)}개: " + "; ".join(f"{r['date']} {r['title'][:30]!r} - {w}" for r, w in bad[:3]))


def check_html(path):
    path = Path(path).resolve()
    html = path.read_text(encoding="utf-8")
    mark = "const ALL = "
    if html.count("__DATA__") or mark not in html:
        err("HTML 에 데이터가 들어가지 않았다")
        return
    ALL, _ = json.JSONDecoder().raw_decode(html, html.index(mark) + len(mark))
    if list(ALL) != list(ASSETS):
        err(f"HTML 에 든 대상이 assets.py 와 다르다: {list(ALL)}")
        return
    for k in ASSETS:
        if ALL[k]["R"] != load(f"result_{k}.json") or ALL[k]["G"] != load(f"signals_{k}.json"):
            err(f"{k}: HTML 에 든 값이 data/ 의 결과와 다르다")
    mark3 = "const YIX = "
    if mark3 not in html or json.JSONDecoder().raw_decode(html, html.index(mark3) + len(mark3))[0] != year_data():
        err("HTML 에 든 지수별 연도 값(탭 3)이 data/ 의 종가로 다시 계산한 값과 다르다")
    mark4 = "const RATES = "
    if mark4 not in html or json.JSONDecoder().raw_decode(html, html.index(mark4) + len(mark4))[0] != rate_data():
        err("HTML 에 든 정책금리·소비자물가(탭 4)가 data/ 의 bis_rates.csv, bis_cpi.csv 로 다시 계산한 값과 다르다")
    rates = rate_data()
    mark5 = "const HIKE = "
    if mark5 not in html or json.JSONDecoder().raw_decode(html, html.index(mark5) + len(mark5))[0] != hike_data(rates):
        err("HTML 에 든 인상기 분석(탭 4)이 정책금리·지수로 다시 계산한 값과 다르다")
    mark6 = "const EVENTS = "
    if mark6 not in html or json.JSONDecoder().raw_decode(html, html.index(mark6) + len(mark6))[0] != load_events():
        err("HTML 에 든 날짜별 이슈(탭 1 툴팁)가 events/events.csv 와 다르다")
    mark7 = "const TRENDS = "
    if mark7 not in html or json.JSONDecoder().raw_decode(html, html.index(mark7) + len(mark7))[0] != trend_data():
        err("HTML 에 든 추세 상태(탭 5)가 data/ 의 종가로 다시 매긴 값과 다르다")
    mark8 = "const SLOPES = "
    if mark8 not in html or json.JSONDecoder().raw_decode(html, html.index(mark8) + len(mark8))[0] != slope_data():
        err("HTML 에 든 회귀 추세의 기준값(탭 6)이 data/ 의 종가로 다시 계산한 값과 다르다")
    if not errors:
        print("HTML 에 든 값이 data/ 와 같다:", len(ALL), "대상,", ALL["kospi"]["R"]["series"]["date"][-1], "까지")

    # 실제 브라우저로 한 번 그려 본다. 값이 맞아도 화면 코드가 중간에 죽으면 빈 화면이 된다.
    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    if not browser:
        print("[건너뜀] 크롬·엣지를 못 찾아 화면 그리기는 확인하지 않았다")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--window-size=1600,1200", "--virtual-time-budget=15000",
                            "--enable-logging=stderr", "--v=0", f"--user-data-dir={prof}", "--dump-dom", path.as_uri()],
                           capture_output=True, timeout=300)
    dom, log = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    dom = dom[:dom.find(mark)] + dom[dom.find("</script>", dom.find(mark)):]  # 내장 데이터는 빼고 그려진 것만 본다
    uncaught = [ln[-300:] for ln in log.splitlines() if "Uncaught" in ln]
    charts = dom.count("<svg")
    if uncaught:
        err("브라우저에서 스크립트 오류: " + " | ".join(uncaught[:3]))
    if charts < MIN_CHARTS:
        err(f"브라우저에서 차트가 {charts}개만 그려졌다({MIN_CHARTS}개 이상이어야 한다)")
    print(f"브라우저로 그려 봄: 차트 {charts}개, 스크립트 오류 {len(uncaught)}건")


if __name__ == "__main__":
    if sys.argv[1:2] == ["html"]:
        check_html(sys.argv[2])
    else:
        check_data()
        check_years()
        check_rates()
        check_events()
    print(f"검사 끝: 오류 {len(errors)}건")
    sys.exit(1 if errors else 0)
