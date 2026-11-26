"""날짜별 경제 이슈 표 events/events.csv (P014-013). 탭 1 "기간 비교"의 종가 차트에 마우스를 올리면 그날 이슈가 나온다.

    python events.py              자동 줄(미국·한국 정책금리 변경일 - BIS, 미국 종목의 8-K 공시 - SEC, 한국 종목의 공시 - DART)을 다시 뽑아 쓴다. 조사해 온 줄은 그대로 둔다
                                  단, 조사해 온 실적 발표 줄은 같은 날 같은 종목의 8-K 실적 공시(자동)가 있으면 지운다 - 공시가 확인된 날짜다
    python events.py add <csv>    조사해 온 줄(같은 열)을 합친다. 날짜·나라·종목·제목이 빠졌거나 종목 키가 없는 줄은 받지 않고 알린다. 같은 (날짜, 종목, 제목)은 한 번만

열: date(YYYY-MM-DD), country(US/KR), asset(assets.py 의 종목 키. 빈칸이면 그 나라 전체의 일), category, title, summary, source(주소), checked
category: rate 금리 / earnings 실적 / shareholder 주주환원·배당·자사주 / business 투자·계약·제품 / policy 정책·규제 / incident 사고·소송 / people 경영진 / other
- checked 가 "auto" 인 줄은 이 스크립트가 만든 것이고 돌릴 때마다 새로 쓴다. 그 밖의 값("yes" = 출처를 직접 열어 봄, 빈칸 = 안 봄)은 사람이 적은 줄이다.
- 이 파일은 받은 자료가 아니라 우리가 만든 표라 저장소에 싣는다(data/ 와 다르다). 뒤에 서버를 만들면 이 표가 그대로 DB 의 한 표가 된다.
- 받은 자료(BIS)에서 뽑은 값은 숫자뿐이고, 글은 여기서 만든다.
"""
import csv
import json
import sys
from pathlib import Path

from assets import ASSETS
from common import D, HIKE_IX, rate_changes, rate_data

HERE = Path(__file__).parent
EV = HERE / "events" / "events.csv"
COLS = ["date", "country", "asset", "category", "title", "summary", "source", "checked"]
CATS = ("rate", "earnings", "shareholder", "business", "policy", "incident", "people", "other")
EV_FROM = "1997-01-01"  # 탐색기의 첫해. 그 앞의 금리 변경은 탭 1 에 날짜가 없어 보일 자리가 없다
BANK = {"US": "미국 연준", "KR": "한국은행"}
# 8-K 항목 번호 -> (분류, 이름). 앞에 있는 것이 우선이다(한 공시에 항목이 여럿). 여기 없는 항목만 있는 공시(7.01 보도자료, 8.01 기타, 9.01 첨부)는 싣지 않는다 - 너무 잦고 뜻이 없다.
SEC_ITEMS = [("2.02", "earnings", "실적 발표"), ("5.02", "people", "임원·이사 변경"), ("1.01", "business", "중요 계약 체결"),
             ("2.01", "business", "자산 취득·처분 완료"), ("1.02", "business", "중요 계약 종료"), ("2.05", "business", "구조조정 비용"),
             ("2.06", "business", "자산 손상"), ("4.02", "incident", "재무제표 신뢰 불가"), ("4.01", "incident", "감사인 변경"),
             ("5.01", "people", "지배권 변경"), ("5.07", "shareholder", "주주총회 결과"), ("3.03", "shareholder", "주주 권리 변경")]
SEC_NAMES = {"1.01": "중요 계약 체결", "1.02": "계약 종료", "2.01": "자산 취득·처분 완료", "2.02": "실적 발표", "2.03": "채무 발생", "2.04": "채무 조기 상환 사유",
             "2.05": "구조조정 비용", "2.06": "자산 손상", "3.01": "상장 관련 통지", "3.02": "비등록 증권 발행", "3.03": "주주 권리 변경", "4.01": "감사인 변경",
             "4.02": "재무제표 신뢰 불가", "5.01": "지배권 변경", "5.02": "임원·이사 변경", "5.03": "정관 변경", "5.05": "윤리 규정 변경", "5.07": "주주총회 결과",
             "5.08": "주주 추천", "7.01": "보도자료(Reg FD)", "8.01": "기타", "9.01": "첨부"}


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


# DART 공시 제목의 낱말 -> 분류. 앞의 것이 우선. 어느 것에도 안 걸리는 공시(IR 안내, 풍문 해명, 주주총회 소집, 조회공시 등)는 싣지 않는다 - 잦고 뜻이 없다.
DART_WORDS = [("earnings", ("잠정)실적", "잠정실적", "영업실적")),
              ("shareholder", ("배당", "자기주식", "주식소각", "기업가치제고", "주주환원", "무상증자", "액면분할", "주식분할")),
              ("business", ("공급계약", "신규시설투자", "타법인주식", "유상증자", "합병", "분할", "영업양수", "영업양도", "해외증권시장", "전환사채", "교환사채", "신주인수권", "자산양수", "자산양도")),
              ("people", ("대표이사", "최대주주")),
              ("incident", ("소송", "영업정지", "화재", "제재", "행정처분", "거래정지", "회생"))]


# 이 낱말이 든 공시는 분류 전에 뺀다: 임원·대주주의 지분 변동 신고(1,392건), 대주주와의 부동산 임대, 자회사의 일(자회사 실적·계약은 모회사 사건이 아니다).
DART_SKIP = ("소유주식변동신고서", "부동산임대", "부동산임차", "자회사의 주요경영사항", "자회사의주요경영사항", "종속회사")


def load_dart():
    """fetch.py dart 가 받은 공시 목록. 키가 없어 안 받았으면 빈 것."""
    p = D / "dart_list.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def dart_rows(dart):
    """DART 공시 한 줄씩. 제목의 낱말로 분류한다(DART_WORDS). 출처는 DART 의 공시 열람 주소(접수번호)."""
    rows = []
    for key, filings in dart.items():
        a = ASSETS[key]
        for f in filings:
            if any(w in f["name"] for w in DART_SKIP):
                continue
            cat = next((c for c, words in DART_WORDS if any(w in f["name"] for w in words)), None)
            if not cat:
                continue
            rows.append({"date": f["date"], "country": "KR", "asset": key, "category": cat, "title": f"{a['name']} 공시: {f['name']}",
                         "summary": f"전자공시(DART) {'주요사항보고' if f['ty'] == 'B' else '거래소공시'} 접수번호 {f['no']}. 글은 출처에서 본다",
                         "source": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={f['no']}", "checked": "auto"})
    return rows


def load_sec():
    """fetch.py sec 가 받은 8-K 목록. 아직 안 받았으면 빈 것(그러면 자동 줄은 금리 변경일뿐이다)."""
    p = D / "sec_8k.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def sec_rows(sec):
    """8-K 공시 한 줄씩. 분류는 SEC_ITEMS 의 첫 번째로 맞는 항목이 정하고, 제목에는 항목 이름을 다 적는다."""
    rows = []
    for key, filings in sec.items():
        a = ASSETS[key]
        for f in filings:
            items = [x.strip() for x in f["items"].split(",") if x.strip()]
            hit = next(((cat, nm) for code, cat, nm in SEC_ITEMS if code in items), None)
            if not hit:
                continue
            names = " · ".join(SEC_NAMES.get(x, x) for x in items if x != "9.01")
            rows.append({"date": f["date"], "country": "US", "asset": key, "category": hit[0],
                         "title": f"{a['name']} 공시(8-K): {names}",
                         "summary": f"보고 기준일 {f['report'] or '-'}. 항목 {', '.join(items)}. SEC EDGAR 에 제출된 수시 공시이고 글은 출처에서 본다",
                         "source": f"https://www.sec.gov/Archives/edgar/data/{a['cik']}/{f['acc'].replace('-', '')}/{f['doc']}", "checked": "auto"})
    return rows


def auto_rows_all(rates, sec, dart):
    return sorted(auto_rows(rates) + sec_rows(sec) + dart_rows(dart), key=lambda r: (r["date"], r["country"], r["asset"]))


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
    auto = auto_rows_all(rate_data(), load_sec(), load_dart())
    # 조사해 온 실적 발표 줄은 공시가 같은 날 있으면 공시 쪽만 남긴다. 조사 줄은 기억에서 나온 날짜가 많고 공시는 확인된 날짜다
    known = {(r["asset"], r["date"]) for r in auto if r["category"] == "earnings"}
    kept = [r for r in manual if not (r["category"] == "earnings" and (r["asset"], r["date"]) in known)]
    write_events(sorted(kept + auto, key=lambda r: (r["date"], r["country"], r["asset"])))
    print(f"{EV}: 자동 {len(auto)}줄(금리 변경일 {EV_FROM} 부터 + 8-K 공시 + DART 공시) + 조사해 온 {len(kept)}줄"
          + (f" (실적 발표 {len(manual) - len(kept)}줄은 같은 날 공시가 있어 뺐다)" if len(kept) < len(manual) else ""))


if __name__ == "__main__":
    main()
