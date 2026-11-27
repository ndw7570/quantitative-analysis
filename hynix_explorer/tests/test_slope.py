"""탭 6 "회귀 추세"(slope.py). 회귀는 numpy 의 직접 계산과 대조하고, 창 고르기와 상태는 손으로 셀 수 있는 배열로 본다."""
import unittest
from pathlib import Path

import numpy as np

import slope

HERE = Path(__file__).parent.parent


class RollingOls(unittest.TestCase):
    def test_matches_a_direct_least_squares_fit(self):
        rng = np.random.default_rng(1)
        y = np.cumsum(rng.normal(0.001, 0.02, 300))
        b, t, r2 = slope.rolling_ols(y, 60)
        self.assertTrue(np.isnan(b[58]) and not np.isnan(b[59]))
        for i in (59, 150, 299):
            yy, x = y[i - 59:i + 1], np.arange(60.0)
            bb, aa = np.polyfit(x, yy, 1)
            res = yy - (aa + bb * x)
            sse, sst = (res ** 2).sum(), ((yy - yy.mean()) ** 2).sum()
            se = np.sqrt(sse / 58 / ((x - x.mean()) ** 2).sum())
            self.assertAlmostEqual(b[i], bb, 12)
            self.assertAlmostEqual(t[i], bb / se, 8)
            self.assertAlmostEqual(r2[i], 1 - sse / sst, 10)

    def test_perfect_line_has_r2_one_and_flat_line_has_zero_slope(self):
        b, t, r2 = slope.rolling_ols(np.arange(50) * 0.01, 20)
        self.assertAlmostEqual(b[-1], 0.01)
        self.assertAlmostEqual(r2[-1], 1.0)
        self.assertTrue(np.isinf(t[-1]))  # 잔차가 0 이라 불확실성이 0
        b, t, r2 = slope.rolling_ols(np.full(50, 3.0), 20)
        self.assertEqual((b[-1], t[-1], r2[-1]), (0.0, 0.0, 0.0))

    def test_too_short_series_is_all_nan(self):
        self.assertTrue(np.isnan(slope.rolling_ols(np.arange(5.0), 10)).all())


def fake_res(b_by_win, t_by_win=None):
    """창마다 (기울기, t, R²) 를 날마다 같은 값으로 - consensus 가 창을 고르는 규칙만 보려고."""
    n = len(next(iter(b_by_win.values())))
    return {w: np.array([b_by_win[w], (t_by_win or {}).get(w, [5.0] * n), [0.5] * n]) for w in slope.WINS}


class Consensus(unittest.TestCase):
    def test_picks_longest_window_agreeing_with_the_20_day_sign(self):
        # 하루 1: 20·40·60 이 양수, 120 이 음수 -> 60(자리 2). 하루 2: 20 만 양수 -> 20. 하루 3: 전부 음수 -> 250. 하루 0: 20 이 없음 -> None
        b = {20: [np.nan, 1, 1, -1], 40: [np.nan, 1, -1, -1], 60: [np.nan, 1, -1, -1], 120: [np.nan, -1, 1, -1], 250: [np.nan, 1, 1, -1]}
        pick, st = slope.consensus(fake_res(b))
        self.assertEqual(pick, [None, 2, 0, 4])
        self.assertEqual(st, [None, "up", "flat", "down"])  # 20일 창만 같은 방향이면 길이 20 < L_MIN 이라 보합

    def test_state_needs_t_and_leaves_on_weak_t_or_short_length(self):
        n = 5
        b = {w: [1] * n for w in slope.WINS}
        b[40] = [1, 1, 1, -1, -1]  # 넷째 날부터 40일 창이 반대 -> 합의 길이 20
        t = {250: [1.5, 2.5, 1.2, 9, 9]}
        pick, st = slope.consensus(fake_res(b, t))
        self.assertEqual(pick, [4, 4, 4, 0, 0])
        # 1.5 는 문턱 2 에 못 미침, 2.5 로 진입, 1.2 는 1 이상이라 유지, 길이 20 이 되면 보합
        self.assertEqual(st, ["flat", "up", "up", "flat", "flat"])

    def test_missing_longer_windows_are_ignored(self):
        b = {20: [1.0], 40: [1.0], 60: [np.nan], 120: [np.nan], 250: [np.nan]}
        pick, st = slope.consensus(fake_res(b))
        self.assertEqual((pick, st), ([1], ["up"]))


class SlopeStates(unittest.TestCase):
    def test_hysteresis_on_t(self):
        self.assertEqual(slope.slope_states([0, 2.5, 1.5, 0.5, -3, -1.1, -0.9, None]),
                         ["flat", "up", "up", "flat", "down", "down", "flat", None])


class SlopeOne(unittest.TestCase):
    def test_reference_values_have_the_shape_the_screen_checks(self):
        rng = np.random.default_rng(2)
        close = [None] * 7 + list(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 400))))
        r = slope.slope_one({"close": close})
        self.assertEqual((r["first"], r["n"]), (7, 400))
        self.assertEqual(set(r["last"]), {str(w) for w in slope.WINS})
        self.assertEqual(sum(r["auto"]["days"].values()), 400 - 19)  # 20일 창이 생기는 날부터 상태가 있다
        self.assertEqual(sum(r["auto"]["wins"].values()), 400 - 19)
        self.assertGreater(r["auto"]["runs"], 0)


class Layout(unittest.TestCase):
    def test_template_has_one_slope_slot_where_check_looks_for_it(self):
        html = (HERE / "template.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("__SLOPE__"), 1)
        self.assertIn("const SLOPES = __SLOPE__", html)
        self.assertIn('data-tab="slope"', html)
        self.assertIn("회귀 추세 자기 검사 실패", html)  # 화면의 자기 검사가 남아 있다

    def test_windows_and_slider_range_are_consistent(self):
        self.assertEqual(slope.WINS, sorted(slope.WINS))
        self.assertLessEqual(slope.WINS[-1], slope.W_MAX)
        self.assertIn(slope.L_MIN, slope.WINS)
        self.assertGreater(slope.T_IN, slope.T_OUT)


if __name__ == "__main__":
    unittest.main()
