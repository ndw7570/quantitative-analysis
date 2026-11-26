"""날짜별 경제 이슈 표 events/events.csv (P014-013). 탭 1 "기간 비교"의 종가 차트에 마우스를 올리면 그날 이슈가 나온다.

    python events.py              미국·한국 정책금리 변경일을 BIS 자료에서 다시 뽑아 쓴다. 손으로 적은 줄은 그대로 둔다
    python events.py add <csv>    조사해 온 줄(같은 열)을 합친다. 날짜·나라·종목·제목이 빠졌거나 종목 키가 없는 줄은 받지 않고 알린다. 같은 (날짜, 종목, 제목)은 한 번만

열: date(YYYY-MM-DD), country(US/KR), asset(assets.py 의 종목 키. 빈칸이면 그 나라 전체의 일), category, title, summary, source(주소), checked
category: rate 금리 / earnings 실적 / shareholder 주주환원·배당·자사주 / business 투자·계약·제품 / policy 정책·규제 / incident 사고·소송 / people 경영진 / other
- checked 가 "auto" 인 줄은 이 스크립트가 만든 것이고 돌릴 때마다 새로 쓴다. 그 밖의 값("yes" = 출처를 직접 열어 봄, 빈칸 = 안 봄)은 사람이 적은 줄이다.
- 이 파일은 받은 자료가 아니라 우리가 만든 표라 저장소에 싣는다(data/ 와 다르다). 뒤에 서버를 만들면 이 표가 그대로 DB 의 한 표가 된다.
- 받은 자료(BIS)에서 뽑은 값은 숫자뿐이고, 글은 여기서 만든다.
"""
import csv
import sys
from pathlib import Path

from assets import ASSETS
from common import HIKE_IX, rate_changes, rate_data

HERE = Path(__file__).parent
EV = HERE / "events" / "events.csv"
COLS = ["date", "country", "asset", "category", "title", "summary", "source", "checked"]
CATS = ("rate", "earnings", "shareholder", "business", "policy", "incident", "people", "other")
EV_FROM = "1997-01-01"  # 탐색기의 첫해. 그 앞의 금리 변경은 탭 1 에 날짜가 없어 보일 자리가 없다
BANK = {"US": "미국 연준", "KR": "한국은행"}


def fmt(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") + "%"


def auto_rows(rates):
    """금리 변경일 한 줄씩. 나라 순서는 HIKE_IX(미국, 한국), 그 안에서 날짜 순이다."""
    rows = []
    for c in HIKE_IX:
        a = rates["areas"][c]
        for d, v, dv in rate_changes(a["steps"], EV_FROM):
            rows.append({"date": d, "country": c, "asset": "", "category": "rate",
                         "title": f"{BANK[c]} 정책금리 {'인상' if dv > 0 else '인하'} {dv:+.2f}%p -> {fmt(v)}",
                         "summary": f"{fmt(v - dv)} -> {fmt(v)}. BIS 일별 정책금리 자료에서 값이 바뀐 날", "source": "BIS", "checked": "auto"})
    return sorted(rows, key=lambda r: (r["date"], r["country"]))


def load_events():
    """csv 전체를 날짜 순으로. 파일이 없으면 빈 목록(처음 돌리기 전)."""
    if not EV.exists():
        return []
    with EV.open(encoding="utf-8-sig", newline="") as f:
        rows = [{k: (r.get(k) or "").strip() for k in COLS} for r in csv.DictReader(f)]
    return sorted(rows, key=lambda r: (r["date"], r["country"]))


def bad_reason(r):
    """받지 않을 줄이면 그 이유, 아니면 None. 조사해 온 줄은 남이 쓴 글이라 모양을 먼저 본다."""
    d = r["date"]
    if len(d) != 10 or d[4] != "-" or d[7] != "-" or not (d[:4] + d[5:7] + d[8:]).isdigit():
        return f"날짜 모양이 아니다: {d!r}"
    if r["country"] not in ("US", "KR"):
        return f"나라가 US/KR 이 아니다: {r['country']!r}"
    if r["asset"] and r["asset"] not in ASSETS:
        return f"없는 종목 키: {r['asset']!r}"
    if not r["title"]:
        return "제목이 없다"
    if r["category"] not in CATS:
        return f"분류가 목록에 없다: {r['category']!r}"
    return None


def merge_rows(rows, new):
    """new 를 rows 에 더한다. 같은 (날짜, 종목, 제목)이 있으면 넣지 않는다. (더한 줄 수, 받지 않은 [(줄, 이유)])."""
    seen = {(r["date"], r["asset"], r["title"]) for r in rows}
    added, bad = 0, []
    for r in new:
        r = {k: (r.get(k) or "").strip() for k in COLS}
        why = bad_reason(r)
        if why:
            bad.append((r, why))
            continue
        if (r["date"], r["asset"], r["title"]) in seen:
            continue
        seen.add((r["date"], r["asset"], r["title"]))
        rows.append(r)
        added += 1
    return added, bad


def write_events(rows):
    EV.parent.mkdir(exist_ok=True)
    with EV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def main():
    if sys.argv[1:2] == ["add"]:
        rows = load_events()
        with open(sys.argv[2], encoding="utf-8-sig", newline="") as f:
            new = list(csv.DictReader(f))
        added, bad = merge_rows(rows, new)
        write_events(sorted(rows, key=lambda r: (r["date"], r["country"])))
        for r, why in bad:
            print(f"  [받지 않음] {r['date']} {r['asset']} {r['title'][:40]!r}: {why}")
        print(f"{sys.argv[2]}: {len(new)}줄 중 {added}줄 더함, {len(bad)}줄 받지 않음, 나머지는 이미 있던 줄 -> 전체 {len(rows)}줄")
        return
    manual = [r for r in load_events() if r["checked"] != "auto"]
    auto = auto_rows(rate_data())
    write_events(sorted(manual + auto, key=lambda r: (r["date"], r["country"])))
    print(f"{EV}: 자동 {len(auto)}줄(금리 변경일 {EV_FROM} 부터) + 손으로 적은 {len(manual)}줄")


if __name__ == "__main__":
    main()
