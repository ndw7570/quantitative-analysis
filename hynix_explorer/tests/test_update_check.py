"""update.py 와 check.py 의 작은 판단들. 전체 실행은 update.py 를 실제로 돌려서 본다(여기서는 돌리지 않는다)."""
import tempfile
import unittest
from pathlib import Path

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
