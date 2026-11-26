"""update.py 와 check.py 의 작은 판단들. 전체 실행은 update.py 를 실제로 돌려서 본다(여기서는 돌리지 않는다)."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import check
import update
from assets import ASSETS

HERE = Path(__file__).parent.parent


class DefaultOut(unittest.TestCase):
    def test_finds_the_project_folder_at_any_depth(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "deck" / "report").mkdir(parents=True)
            for depth in ("development/source/hynix_explorer", "development/source/repo/hynix_explorer"):
                here = root / depth
                here.mkdir(parents=True)
                self.assertEqual(update.default_out(here), root / update.REPORT)

    def test_falls_back_inside_the_repo_when_there_is_no_project_folder(self):
        with tempfile.TemporaryDirectory() as t:
            here = Path(t) / "repo" / "hynix_explorer"
            here.mkdir(parents=True)
            self.assertEqual(update.default_out(here), Path(t) / "repo" / "out" / "index.html")


class TempOut(unittest.TestCase):
    def test_sits_next_to_the_output_and_still_ends_in_html(self):
        out = Path("a") / "b" / "index.html"
        new = update.temp_out(out)
        self.assertEqual(new.parent, out.parent)
        self.assertNotEqual(new, out)
        self.assertEqual(new.suffix, ".html")  # 아니면 브라우저가 페이지로 읽지 않는다


class LastDay(unittest.TestCase):
    def test_reads_the_last_line_and_ignores_the_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "a.csv"
            f.write_text("date,close\n2026-11-23,1\n2026-11-24,2\n", encoding="utf-8-sig")
            self.assertEqual(update.last_day(f), "2026-11-24")
            f.write_text("date,close\n", encoding="utf-8-sig")
            self.assertIsNone(update.last_day(f))


class MissingFlowDays(unittest.TestCase):
    def days(self, *d):
        return pd.to_datetime(list(d))

    def test_separates_holes_from_days_not_posted_yet(self):
        px = self.days("2004-12-30", "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24")
        flow = self.days("2026-11-19", "2026-11-23")
        lost, late = check.missing_flow_days(px, flow)
        self.assertEqual(lost, [pd.Timestamp("2026-11-20")])  # 가운데가 빠졌다 = 수집 오류
        self.assertEqual(late, [pd.Timestamp("2026-11-24")])  # 뒤가 덜 왔다 = 아직 안 올라옴
        # 수급 자료가 시작되기 전(2004)은 빠진 것으로 치지 않는다

    def test_nothing_missing(self):
        px = self.days("2026-11-23", "2026-11-24")
        self.assertEqual(check.missing_flow_days(px, px), ([], []))

    def test_empty_flow_file_counts_every_day_as_lost(self):
        px = self.days("2026-11-23", "2026-11-24")
        self.assertEqual(check.missing_flow_days(px, pd.DatetimeIndex([])), (list(px), []))


class Layout(unittest.TestCase):
    """코드끼리 말없이 맞춰 둔 약속. 한쪽만 고치면 실행은 되는데 결과가 틀린다."""

    def test_template_has_one_data_slot_where_check_looks_for_it(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("__DATA__"), 1)
        self.assertIn("const ALL = __DATA__", html)  # check.py 가 이 표시 뒤에서 데이터를 읽는다

    def test_every_asset_names_known_regressors_and_comparisons(self):
        from assets import BENCH
        known = set(ASSETS) | set(BENCH)
        for k, a in ASSETS.items():
            self.assertEqual(len(a["reg"]), 2, k)
            self.assertTrue(set(a["reg"]) | set(a["cmp"]) <= known, k)
            self.assertNotIn(k, a["reg"], k)  # 자기로 자기를 설명하지 않는다
            self.assertIn((a["market"], a["kind"]), check.BIG_MOVE, k)


class YearsLayout(unittest.TestCase):
    def test_template_has_one_years_slot_where_check_looks_for_it(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("__YIX__"), 1)
        self.assertIn("const YIX = __YIX__", html)  # check.py 가 이 표시 뒤에서 탭 3 자료를 읽는다

    def test_every_index_of_tab3_is_something_fetch_downloads(self):
        # 목록에만 넣고 받는 쪽에 안 넣으면 파일이 없어 build 가 죽는다
        from assets import BENCH, KR_BENCH, YEAR_IX
        got = {"us": set(BENCH) | {k for k, a in ASSETS.items() if a["market"] == "us"},
               "kr": set(KR_BENCH) | {k for k, a in ASSETS.items() if a["market"] == "kr"}}
        for k, a in YEAR_IX.items():
            self.assertIn(k, got[a["market"]], k)
        self.assertEqual(list(YEAR_IX), ["spx", "nasdaq", "kospi", "kosdaq"])  # 전에 쓰던 주소(#year-2018)는 첫 지수로 열린다


class CheckYears(unittest.TestCase):
    """탭 3 값은 틀려도 선이 그려진다. 지수 기준이 중간에 바뀐 자료(코스닥은 2004년에 100 -> 1,000)를 걸러야 한다."""

    def run_check(self, closes):
        import common
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        df = pd.DataFrame({"close": list(closes.values())}, index=pd.to_datetime(list(closes)))
        df.to_csv(d / "naver_px_kosdaq.csv", encoding="utf-8-sig")
        ix = {"kosdaq": {"name": "코스닥", "market": "kr"}}
        with mock.patch.object(check, "D", d), mock.patch.object(common, "D", d), mock.patch.object(check, "errors", []), \
                mock.patch.object(check, "YEAR_IX", ix), mock.patch.object(common, "YEAR_IX", ix), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            check.check_years()
            return list(check.errors), out.getvalue()

    def test_ordinary_years_pass(self):
        errors, out = self.run_check({"2023-12-28": 800.0, "2024-06-03": 880.0, "2024-12-30": 790.0, "2025-01-02": 710.0})
        self.assertEqual((errors, out), ([], ""))

    def test_tenfold_jump_inside_a_year_is_an_error_and_a_warning(self):
        errors, out = self.run_check({"2023-12-28": 80.0, "2024-06-03": 82.0, "2024-06-04": 820.0, "2025-01-02": 830.0})
        self.assertEqual(len(errors), 1)
        self.assertIn("2024년", errors[0])
        self.assertIn("[주의] 탭 3 코스닥: 하루 등락률", out)

    def test_missing_file_is_an_error_not_a_crash(self):
        import common
        with tempfile.TemporaryDirectory() as t, mock.patch.object(check, "D", Path(t)), mock.patch.object(common, "D", Path(t)), \
                mock.patch.object(check, "errors", []), contextlib.redirect_stdout(io.StringIO()):
            check.check_years()
            self.assertEqual(len(check.errors), 1)
            self.assertIn("naver_px_kosdaq.csv", check.errors[0])


class RatesLayout(unittest.TestCase):
    def test_template_has_one_rates_slot_where_check_looks_for_it(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("__RATES__"), 1)
        self.assertIn("const RATES = __RATES__", html)  # check.py 가 이 표시 뒤에서 정책금리를 읽는다

    def test_first_group_of_rates_is_the_main_six_button(self):
        from assets import RATES
        first = next(iter(RATES.values()))[1]
        self.assertEqual([c for c, (_, g) in RATES.items() if g == first], ["US", "KR", "XM", "JP", "GB", "CN"])
        self.assertIn('<button id="r_main">주요 6개</button>', (HERE / "template.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
