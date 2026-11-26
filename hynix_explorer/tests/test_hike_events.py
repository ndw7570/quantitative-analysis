"""탭 4 "인상기 분석"(common.hike_*)과 날짜별 이슈 표(events.py). 손으로 셀 수 있는 작은 표로 본다."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import common
import events

HERE = Path(__file__).parent.parent


def close(start, days, step=1.0, base=100.0):
    """날마다 step 씩 오르는 종가(주말 없음 - 달력 그대로)."""
    idx = pd.date_range(start, periods=days)
    return pd.Series([base + step * i for i in range(days)], index=idx)


# 3회 연속 인상(01-10, 02-10, 03-10) 뒤 06-10 에 인하, 그 뒤 다시 2회 인상
STEPS = [["2019-12-01", 1.0], ["2020-01-10", 1.25], ["2020-02-10", 1.5], ["2020-03-10", 1.75], ["2020-06-10", 1.5],
         ["2021-01-05", 1.75], ["2021-02-05", 2.0]]


class RateChanges(unittest.TestCase):
    def test_lists_only_changes_after_start_and_skips_gaps(self):
        steps = [["2019-12-01", 1.0], ["2020-01-10", 1.25], ["2020-02-01", None], ["2020-03-01", 2.0], ["2020-04-01", 2.5]]
        # None 의 앞뒤(1.25 -> 없음 -> 2.0)는 변화로 치지 않는다. 값이 없던 기간을 건너 "올렸다"고 세면 안 된다
        self.assertEqual(common.rate_changes(steps, "2020-01-01"), [("2020-01-10", 1.25, 0.25), ("2020-04-01", 2.5, 0.5)])
        self.assertEqual(common.rate_changes(steps, "2020-03-15"), [("2020-04-01", 2.5, 0.5)])

    def test_rate_on_a_day(self):
        self.assertEqual(common.rate_on(STEPS, "2020-02-15"), 1.5)
        self.assertEqual(common.rate_on(STEPS, "2020-01-10"), 1.25)  # 바뀐 날 당일은 새 값
        self.assertIsNone(common.rate_on(STEPS, "2019-01-01"))


class HikeCycles(unittest.TestCase):
    def test_counts_a_run_of_three_hikes_and_measures_the_index_after_the_peak(self):
        px = close("2020-01-01", 500, step=1.0)  # 03-10 종가 169, 91일 뒤(06-09) 260
        cyc = common.hike_cycles(common.rate_changes(STEPS, "2020-01-01"), px)
        self.assertEqual(len(cyc), 1)  # 2021 년의 2회는 HIKE_MIN 에 못 미친다
        c = cyc[0]
        self.assertEqual((c["n"], c["first"], c["peak"], c["rate"], c["low"], c["cut"], c["hold"]), (3, "2020-01-10", "2020-03-10", 1.75, 1.0, "2020-06-10", 92))
        self.assertEqual(c["after"]["91"], round((260 / 169 - 1) * 100, 1))
        self.assertEqual(c["ix_hike"], round((169 / 109 - 1) * 100, 1))  # 01-10 종가 109 -> 03-10 종가 169
        self.assertEqual(c["mdd"], 0.0)  # 오르기만 한 지수

    def test_ongoing_cycle_has_no_cut_and_missing_future_returns_are_none(self):
        steps = STEPS[:4]  # 인하 없이 끝
        px = close("2020-01-01", 100)  # 04-09 까지만 있다
        c = common.hike_cycles(common.rate_changes(steps, "2020-01-01"), px)[0]
        self.assertIsNone(c["cut"]); self.assertIsNone(c["hold"])
        self.assertEqual(c["after"], {"91": None, "182": None, "365": None})


class HikeBoard(unittest.TestCase):
    CPI = {"from": "2020-01", "v": [2.0, 2.0, 1.5, 1.5, 1.5, 1.5]}  # 1월 ~ 6월

    def board(self, steps, last, px):
        return common.hike_board(steps, last, self.CPI, px, common.hike_cycles(common.rate_changes(steps, "2020-01-01"), px))

    def test_streak_and_signals_while_hiking(self):
        steps = STEPS[:4]  # 3회 인상 뒤 2020-04-01 이 마지막 자료
        b = self.board(steps, "2020-04-01", close("2020-01-01", 92, step=-1.0, base=200))  # 떨어지는 지수
        self.assertEqual((b["s1"]["on"], b["s1"]["streak"], b["s1"]["from"], b["s1"]["rate"]), (True, 3, "2020-01-10", 1.75))
        self.assertFalse(b["s2"]["on"])  # 과거 인상기(끝난 것)가 없어 "가장 짧은 정점 유지"를 모른다
        self.assertEqual(b["s2"]["since"], 22)
        # 실질금리: 1월 1.25-2.0 < 0, 2월 1.5-2.0 < 0, 3월 1.75-1.5 > 0 -> 03 에 양수 전환. 자료 마지막 달은 06 이지만 금리 자료가 04-01 까지라 그 값으로 센다
        self.assertEqual((b["s3"]["on"], b["s3"]["up"], b["s3"]["month"], b["s3"]["real"]), (True, "2020-03", "2020-06", 0.25))
        # 01-10 종가 191 -> 마지막 109: -42.9%
        self.assertTrue(b["s4"]["on"]); self.assertEqual(b["s4"]["ret"], round((109 / 191 - 1) * 100, 1))
        self.assertEqual(b["count"], 3)

    def test_after_a_cut_nothing_is_on(self):
        b = self.board(STEPS[:5], "2020-07-01", close("2020-01-01", 200))
        self.assertEqual((b["s1"]["streak"], b["s1"]["last"], b["s1"]["delta"]), (0, "2020-06-10", -0.25))
        self.assertFalse(b["s2"]["on"]); self.assertFalse(b["s4"]["on"]); self.assertIsNone(b["s4"]["ret"])
        self.assertEqual(b["s3"]["real"], 0.0)  # 6월: 금리 1.5 - 물가 1.5. 0 은 양수가 아니다
        self.assertEqual(b["count"], 0)

    def test_real_rate_turned_positive_long_ago_is_not_a_signal(self):
        cpi = {"from": "2018-01", "v": [0.5] * 30}  # 2018-01 ~ 2020-06, 금리는 늘 물가 위
        b = common.hike_board(STEPS[:4], "2020-04-01", cpi, close("2020-01-01", 10), [])
        self.assertFalse(b["s3"]["on"]); self.assertIsNone(b["s3"]["up"])  # 한 번도 0 아래였던 적이 없다


class Events(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(events, "EV", Path(tmp.name) / "events.csv")
        p.start()
        self.addCleanup(p.stop)

    def test_auto_rows_are_rate_changes_with_a_korean_title(self):
        rates = {"areas": {"US": {"steps": [["1996-12-01", 5.25], ["1997-03-25", 5.5], ["1998-09-29", 5.25]]},
                           "KR": {"steps": [["1999-05-06", 4.75], ["2000-02-10", 5.0]]}}}
        rows = events.auto_rows(rates)
        self.assertEqual([(r["date"], r["country"]) for r in rows], [("1997-03-25", "US"), ("1998-09-29", "US"), ("2000-02-10", "KR")])
        self.assertEqual(rows[0]["title"], "미국 연준 정책금리 인상 +0.25%p -> 5.5%")
        self.assertEqual((rows[0]["asset"], rows[0]["category"], rows[0]["source"], rows[0]["checked"]), ("", "rate", "BIS", "auto"))

    def test_merge_keeps_well_formed_new_rows_once_and_reports_the_rest(self):
        rows = [{"date": "2024-01-25", "country": "KR", "asset": "hynix", "category": "earnings", "title": "4분기 실적", "summary": "", "source": "", "checked": "yes"}]
        new = [{"date": "2024-01-25", "country": "KR", "asset": "hynix", "category": "earnings", "title": "4분기 실적"},  # 이미 있다
               {"date": "2024-04-25", "country": "KR", "asset": "hynix", "category": "earnings", "title": " 1분기 실적 ", "source": "https://x"},
               {"date": "2024-4-25", "country": "KR", "asset": "hynix", "category": "earnings", "title": "날짜 틀림"},
               {"date": "2024-05-01", "country": "KR", "asset": "nope", "category": "earnings", "title": "없는 종목"},
               {"date": "2024-05-02", "country": "KR", "asset": "", "category": "news", "title": "분류 틀림"},
               {"date": "2024-05-03", "country": "KR", "asset": "", "category": "policy", "title": ""}]
        added, bad = events.merge_rows(rows, new)
        self.assertEqual(added, 1)
        self.assertEqual([r["title"] for r in rows], ["4분기 실적", "1분기 실적"])  # 앞뒤 공백을 지운다
        self.assertEqual([w.split(":")[0] for _, w in bad], ["날짜 모양이 아니다", "없는 종목 키", "분류가 목록에 없다", "제목이 없다"])

    def test_rewriting_keeps_hand_written_rows_and_replaces_auto_rows(self):
        events.write_events([{"date": "2020-01-02", "country": "KR", "category": "policy", "title": "손으로 적음", "summary": "", "source": "", "checked": "yes"},
                             {"date": "2019-01-01", "country": "US", "category": "rate", "title": "옛 자동 줄", "summary": "", "source": "BIS", "checked": "auto"}])
        rates = {"areas": {"US": {"steps": [["2019-12-01", 1.5], ["2020-03-03", 1.0]]}, "KR": {"steps": [["2019-12-01", 1.25]]}}}
        with mock.patch.object(events, "rate_data", lambda: rates), mock.patch.object(events, "load_sec", dict), \
                mock.patch.object(events, "load_dart", dict):  # 공시 없이
            events.main()
        rows = events.load_events()
        self.assertEqual([(r["date"], r["title"], r["checked"]) for r in rows],
                         [("2020-01-02", "손으로 적음", "yes"), ("2020-03-03", "미국 연준 정책금리 인하 -0.50%p -> 1%", "auto")])

    def test_missing_file_is_an_empty_list(self):
        self.assertEqual(events.load_events(), [])

    SEC = {"nvidia": [{"acc": "0001045810-26-000090", "date": "2026-11-23", "report": "2026-11-22", "form": "8-K", "items": "5.02,9.01", "doc": "a.htm"},
                      {"acc": "0001045810-26-000080", "date": "2026-11-17", "report": "2026-11-17", "form": "8-K", "items": "2.02,9.01", "doc": "b.htm"},
                      {"acc": "0001045810-26-000070", "date": "2026-09-03", "report": "", "form": "8-K", "items": "7.01,9.01", "doc": "c.htm"}]}

    def test_sec_rows_classify_by_item_and_skip_press_release_only_filings(self):
        rows = events.sec_rows(self.SEC)
        self.assertEqual([(r["date"], r["category"]) for r in rows], [("2026-11-23", "people"), ("2026-11-17", "earnings")])
        self.assertEqual(rows[1]["title"], "엔비디아 공시(8-K): 실적 발표")
        self.assertEqual(rows[1]["source"], "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000080/b.htm")
        self.assertEqual((rows[1]["asset"], rows[1]["country"], rows[1]["checked"]), ("nvidia", "US", "auto"))

    def test_dart_rows_classify_by_title_words_and_skip_the_rest(self):
        dart = {"hynix": [{"date": "2026-10-28", "no": "20261028000001", "name": "연결재무제표기준영업(잠정)실적(공정공시)", "ty": "I"},
                          {"date": "2026-10-28", "no": "20261028000002", "name": "주요사항보고서(자기주식취득결정)", "ty": "B"},
                          {"date": "2026-10-14", "no": "20261014000003", "name": "기업설명회(IR)개최(안내공시)", "ty": "I"}]}
        rows = events.dart_rows(dart)
        self.assertEqual([(r["category"], r["title"]) for r in rows],
                         [("earnings", "SK하이닉스 공시: 연결재무제표기준영업(잠정)실적(공정공시)"), ("shareholder", "SK하이닉스 공시: 주요사항보고서(자기주식취득결정)")])
        self.assertEqual(rows[0]["source"], "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261028000001")
        self.assertEqual((rows[0]["country"], rows[0]["asset"], rows[0]["checked"]), ("KR", "hynix", "auto"))

    def test_rewrite_drops_researched_earnings_rows_that_a_filing_covers(self):
        events.write_events([{"date": "2026-11-17", "country": "US", "asset": "nvidia", "category": "earnings", "title": "조사한 실적", "checked": ""},
                             {"date": "2026-11-17", "country": "US", "asset": "nvidia", "category": "business", "title": "같은 날 다른 사건", "checked": ""},
                             {"date": "2026-08-26", "country": "US", "asset": "nvidia", "category": "earnings", "title": "공시가 없는 날의 실적", "checked": ""}])
        rates = {"areas": {"US": {"steps": [["2019-12-01", 1.5]]}, "KR": {"steps": [["2019-12-01", 1.25]]}}}
        with mock.patch.object(events, "rate_data", lambda: rates), mock.patch.object(events, "load_sec", lambda: self.SEC), \
                mock.patch.object(events, "load_dart", dict):
            events.main()
        self.assertEqual([(r["date"], r["title"]) for r in events.load_events()],
                         [("2026-08-26", "공시가 없는 날의 실적"), ("2026-11-17", "같은 날 다른 사건"), ("2026-11-17", "엔비디아 공시(8-K): 실적 발표"),
                          ("2026-11-23", "엔비디아 공시(8-K): 임원·이사 변경")])


class Layout(unittest.TestCase):
    def test_template_has_one_slot_each_where_build_and_check_look(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        for slot, mark in (("__HIKE__", "const HIKE = __HIKE__"), ("__EVENTS__", "const EVENTS = __EVENTS__")):
            self.assertEqual(html.count(slot), 1)
            self.assertIn(mark, html)
        self.assertIn('id="r_hike"', html)

    def test_every_hike_country_has_an_index_fetch_downloads(self):
        from assets import RATES, YEAR_IX
        for c, ix in common.HIKE_IX.items():
            self.assertIn(c, RATES); self.assertIn(ix, YEAR_IX)


if __name__ == "__main__":
    unittest.main()
