"""탭 5 "추세 상태"(trend.py). 손으로 셀 수 있는 작은 배열로 규칙과 통계를 본다."""
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import trend

HERE = Path(__file__).parent.parent


class Direction(unittest.TestCase):
    def test_enters_at_in_threshold_and_leaves_only_inside_out_threshold(self):
        # 8 을 넘어 상승, 6 은 4 보다 크니 그대로 상승, 3 에서 보합, -9 에서 하락, -5 는 그대로, -3 에서 보합
        self.assertEqual(trend.direction([0, 9, 6, 3, -9, -5, -3]), ["flat", "up", "up", "flat", "down", "down", "flat"])

    def test_missing_days_are_none_and_do_not_reset(self):
        self.assertEqual(trend.direction([9, None, float("nan"), 5]), ["up", None, None, "up"])

    def test_can_jump_from_up_straight_to_down(self):
        self.assertEqual(trend.direction([9, -9]), ["up", "down"])


class Intensity(unittest.TestCase):
    def test_hot_above_in_ratio_until_below_out_ratio(self):
        ref = [1.0] * 5
        # 1.6 > 1.5 로 급, 1.3 은 1.2 보다 크니 그대로, 1.1 에서 풀림, 1.4 는 1.5 를 못 넘어 그대로 아님
        self.assertEqual(trend.intensity([1.0, 1.6, 1.3, 1.1, 1.4], ref), [False, True, True, False, False])

    def test_missing_or_zero_reference_is_none(self):
        self.assertEqual(trend.intensity([1.0, 2.0, 2.0], [None, 0.0, float("nan")]), [None, None, None])


def closes(vals, start="2020-01-01"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals)), dtype=float)


class States(unittest.TestCase):
    def test_steady_rise_is_up_and_a_crash_is_crash(self):
        rng = np.random.default_rng(0)
        calm = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.005, 400)))  # 날마다 0.2% 씩, 변동성 0.5%
        crash = calm[-1] * np.exp(np.cumsum(rng.normal(-0.02, 0.03, 30)))  # 30일 동안 날마다 -2%, 변동성 3%
        st = trend.states(closes(np.concatenate([calm, crash])))
        self.assertIsNone(st[0])
        self.assertIsNone(st[trend.VOL_REF + trend.VOL_N - 2])  # 변동성 기준(1년 중위값)이 차기 전은 없음
        self.assertEqual(st[399], "up")
        self.assertEqual(st[-1], "crash")
        self.assertNotIn(None, st[400:])

    def test_leading_gaps_in_close_are_skipped_not_counted(self):
        vals = [None] * 50 + list(100 + np.arange(400) * 0.3)
        st = trend.states(closes(vals))
        self.assertEqual(st[:50], [None] * 50)
        self.assertEqual(st[-1], "up")
        self.assertEqual(len(st), 450)


class Runs(unittest.TestCase):
    def test_splits_on_change_and_on_missing(self):
        self.assertEqual(trend.runs([None, "a", "a", "b", None, "b"]), [(1, 2, "a"), (3, 3, "b"), (5, 5, "b")])
        self.assertEqual(trend.runs([]), [])
        self.assertEqual(trend.runs(["a"]), [(0, 0, "a")])


class Stats(unittest.TestCase):
    def test_counts_days_runs_and_forward_returns_from_run_starts(self):
        c = closes([100 + i for i in range(100)])  # 날마다 1 씩
        st = ["flat"] * 10 + ["up"] * 5 + ["flat"] * 5 + ["up"] * 80
        s = trend.trend_stats(c, st)
        self.assertEqual((s["up"]["days"], s["up"]["runs"], s["up"]["med_len"]), (85, 2, 42))
        self.assertEqual(s["up"]["share"], 85.0)
        # 진입일 10, 20 에서 21일 뒤: 131/110, 141/120
        self.assertEqual(s["up"]["fwd"]["21"]["n"], 2)
        self.assertAlmostEqual(s["up"]["fwd"]["21"]["mean"], round((131 / 110 - 1 + 141 / 120 - 1) / 2 * 100, 1))
        self.assertEqual(s["up"]["fwd"]["21"]["pos"], 100)
        # 상승 진입 때 저점 대비: 번호 10 의 지난 1년 최저는 100 -> +10%, 번호 20 은 +20% -> 중위 15
        self.assertEqual(s["up"]["late"]["med"], 15.0)
        # 더 간 폭: 63일 안 최고는 진입 뒤 63일째(계속 오름)
        self.assertEqual(s["up"]["more"]["n"], 2)
        self.assertEqual(s["surge"]["days"], 0)
        self.assertIsNone(s["surge"]["med_len"])

    def test_first_day_is_not_an_entry(self):
        c = closes([100.0] * 30)
        s = trend.trend_stats(c, ["down"] * 30)
        self.assertEqual((s["down"]["runs"], s["down"]["fwd"]["21"]["n"]), (1, 0))

    def test_agreement_compares_direction_with_ma_trend_and_hmm(self):
        st = ["surge", "up", "flat", "crash", None]
        self.assertEqual(trend.agreement(st, ["up", "down", "flat", "down", "up"], [2, 2, 0, 2, 2]), {"ma": 75.0, "hv": round(2 / 3 * 100, 1)})
        self.assertEqual(trend.agreement([None], ["up"], [2]), {"ma": None, "hv": None})


class Layout(unittest.TestCase):
    def test_template_has_one_trend_slot_where_check_looks_for_it(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("__TREND__"), 1)
        self.assertIn("const TRENDS = __TREND__", html)  # check.py 가 이 표시 뒤에서 탭 5 자료를 읽는다
        self.assertIn('data-tab="trend"', html)

    def test_state_codes_and_names_match(self):
        self.assertEqual(list(trend.NAMES), trend.STATES)
        self.assertEqual(set(trend.DIRS.values()), {"up", "flat", "down"})


if __name__ == "__main__":
    unittest.main()
