"""날짜별 경제 이슈 표 events/events.csv (P014-013). 탭 1 "기간 비교"의 종가 차트에 마우스를 올리면 그날 이슈가 나온다.

    python events.py    미국·한국 정책금리 변경일을 BIS 자료에서 다시 뽑아 쓴다. 손으로 적은 줄은 그대로 둔다

열: date(YYYY-MM-DD), country(US/KR), category, title, summary, source, checked
- checked 가 "auto" 인 줄은 이 스크립트가 만든 것이고 돌릴 때마다 새로 쓴다. 그 밖의 값("yes" = 출처를 직접 열어 봄, 빈칸 = 안 봄)은 사람이 적은 줄이다.
- 이 파일은 받은 자료가 아니라 우리가 만든 표라 저장소에 싣는다(data/ 와 다르다). 뒤에 서버를 만들면 이 표가 그대로 DB 의 한 표가 된다.
- 받은 자료(BIS)에서 뽑은 값은 숫자뿐이고, 글은 여기서 만든다.
"""
import csv
from pathlib import Path

from common import HIKE_IX, rate_changes, rate_data

HERE = Path(__file__).parent
EV = HERE / "events" / "events.csv"
COLS = ["date", "country", "category", "title", "summary", "source", "checked"]
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
            rows.append({"date": d, "country": c, "category": "rate",
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


def write_events(rows):
    EV.parent.mkdir(exist_ok=True)
    with EV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def main():
    manual = [r for r in load_events() if r["checked"] != "auto"]
    auto = auto_rows(rate_data())
    write_events(sorted(manual + auto, key=lambda r: (r["date"], r["country"])))
    print(f"{EV}: 자동 {len(auto)}줄(금리 변경일 {EV_FROM} 부터) + 손으로 적은 {len(manual)}줄")


if __name__ == "__main__":
    main()
