"""common.py - 받은 파일을 읽어 분석에 넘기는 부분. 손으로 계산할 수 있는 작은 표로 시험한다."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import common


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        p = mock.patch.object(common, "D", self.d)
        p.start()
        self.addCleanup(p.stop)

    def csv(self, name, rows, cols):
        df = pd.DataFrame([r[1:] for r in rows], index=pd.to_datetime([r[0] for r in rows]), columns=cols)
        df.index.name = "date"
        df.to_csv(self.d / name, encoding="utf-8-sig")


class Prices(Base):
    COLS = ["open", "high", "low", "close", "volume"]

    def test_stock_drops_halt_days_and_fills_zero_ohl(self):
        self.csv("naver_px_hynix.csv", [
            ("2026-01-05", 0, 0, 0, 100, 500),     # 상장 첫날: 거래는 있었는데 시가·고가·저가가 0 으로 온다
            ("2026-01-06", 100, 112, 99, 110, 700),
            ("2026-01-07", 0, 0, 0, 110, 0),       # 거래정지
            ("2026-01-08", 110, 125, 110, 121, 900),
        ], self.COLS)
        px = common.prices("hynix")
        self.assertEqual([d.strftime("%m-%d") for d in px.index], ["01-05", "01-06", "01-08"])
        self.assertEqual(px.loc["2026-01-05", ["open", "high", "low"]].tolist(), [100, 100, 100])
        self.assertAlmostEqual(px.loc["2026-01-06", "chg"], 10.0)
        self.assertAlmostEqual(px.loc["2026-01-08", "chg"], 10.0)  # 정지일을 건너뛰고 앞 거래일과 비교한다

    def test_index_keeps_all_days_and_has_no_volume(self):
        self.csv("naver_px_kospi.csv", [("2026-01-05", 1, 1, 1, 2000, 0), ("2026-01-06", 1, 1, 1, 2100, 5)], self.COLS)
        px = common.prices("kospi")
        self.assertEqual(len(px), 2)
        self.assertTrue(px["volume"].isna().all())
        self.assertAlmostEqual(px["chg"].iloc[1], 5.0)

    def test_us_reads_yahoo_columns(self):
        self.csv("yf_nvidia.csv", [("2026-01-05", 99, 10, 12, 9, 11, 300), ("2026-01-06", 99, 11, 13, 10, np.nan, 0)],
                 ["Adj Close", "Open", "High", "Low", "Close", "Volume"])
        px = common.prices("nvidia")
        self.assertEqual(list(px.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(len(px), 1)  # 종가가 빈 줄은 버린다
        self.assertEqual(px["close"].iloc[0], 11)  # 배당을 반영한 Adj Close 가 아니라 Close


class OnCalendar(unittest.TestCase):
    def setUp(self):
        # 한국 달력: 월 화 목 금 (수요일 휴장). 미국: 지난 금요일, 월, 수, 목, 금, 다음 월요일 (화요일 휴장)
        self.cal = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09"])
        rows = {"2026-01-02": (1, 1, 1, 1, 999), "2026-01-05": (10, 12, 9, 11, 100), "2026-01-07": (11, 20, 10, 18, 200),
                "2026-01-08": (18, 19, 5, 15, 300), "2026-01-09": (15, 16, 14, 16, 400), "2026-01-12": (7, 7, 7, 7, 777)}
        px = pd.DataFrame(rows, index=["open", "high", "low", "close", "volume"]).T
        px.index = pd.to_datetime(px.index)
        self.out = common.on_calendar(px, self.cal)

    def test_result_is_on_the_korean_calendar(self):
        self.assertTrue(self.out.index.equals(self.cal))

    def test_us_trade_on_korean_holiday_merges_into_next_korean_day(self):
        r = self.out.loc["2026-01-08"]
        self.assertEqual([r.open, r.high, r.low, r.close, r.volume], [11, 20, 5, 15, 500])

    def test_us_holiday_carries_the_close_with_zero_change(self):
        r = self.out.loc["2026-01-06"]
        self.assertEqual([r.open, r.high, r.low, r.close, r.volume, r.chg], [11, 11, 11, 11, 0, 0])

    def test_rows_outside_the_calendar_are_dropped(self):
        self.assertEqual(self.out.loc["2026-01-05", "volume"], 100)  # 달력 시작 전(01-02)이 첫날에 합쳐지지 않는다
        self.assertEqual(self.out.loc["2026-01-09", "close"], 16)    # 달력 끝 뒤(01-12)가 마지막 날에 섞이지 않는다

    def test_change_uses_calendar_neighbours(self):
        self.assertAlmostEqual(self.out.loc["2026-01-08", "chg"], (15 / 11 - 1) * 100)


class YearPaths(unittest.TestCase):
    def setUp(self):
        # 2023 은 기준(전년 말)만 주는 해, 2024 는 윤년이면서 끝난 해, 2025 는 받는 중인 마지막 해
        s = pd.Series({"2023-12-29": 100.0, "2024-02-28": 110.0, "2024-02-29": 120.0, "2024-03-04": 130.0, "2024-12-30": 150.0,
                       "2025-01-02": 165.0, "2025-01-03": 135.0})
        s.index = pd.to_datetime(s.index)
        self.out = common.year_paths(s)
        self.at = lambda y, md: self.out["years"][y][self.out["days"].index(md)]

    def test_every_year_has_the_same_366_slots(self):
        self.assertEqual(list(self.out["years"]), ["2024", "2025"])  # 첫 해는 전년 말 종가가 없다
        self.assertEqual([len(v) for v in self.out["years"].values()], [366, 366])
        self.assertNotIn("02-29", self.out["days"])
        self.assertEqual(self.out["end"], "2025-01-03")

    def test_return_is_measured_from_the_previous_year_end(self):
        self.assertEqual([self.at("2024", d) for d in ("전년 말", "01-01", "02-28", "12-30")], [0, 0, 10, 50])
        self.assertEqual(self.at("2025", "01-02"), 10)  # 150 -> 165
        self.assertEqual(self.at("2025", "01-03"), -10)

    def test_closed_days_carry_the_last_close(self):
        self.assertEqual(self.at("2024", "02-27"), 0)    # 첫 거래 전
        self.assertEqual(self.at("2024", "03-01"), 20)   # 2월 29일 종가(120)는 칸이 없어도 다음 휴장일로 이어진다
        self.assertEqual(self.at("2024", "03-04"), 30)
        self.assertEqual(self.at("2024", "12-31"), 50)   # 끝난 해는 12월 31일까지 채운다

    def test_last_year_is_empty_after_the_last_day(self):
        self.assertIsNone(self.at("2025", "01-04"))
        self.assertIsNone(self.at("2025", "12-31"))


class YearData(Base):
    def test_each_index_is_read_on_its_own_calendar_and_days_are_shared(self):
        # 미국 지수는 야후 파일(Close), 한국 지수는 네이버 파일(close)에서 읽는다. 시작 해가 달라도 된다
        self.csv("yf_spx.csv", [("2023-12-29", 100.0), ("2024-12-31", 120.0), ("2025-01-02", 132.0)], ["Close"])
        self.csv("naver_px_kosdaq.csv", [("2024-12-30", 1, 1, 1, 800.0, 5), ("2025-01-02", 1, 1, 1, 720.0, 5)],
                 ["open", "high", "low", "close", "volume"])
        ix = {"spx": {"name": "S&P500", "market": "us"}, "kosdaq": {"name": "코스닥", "market": "kr"}}
        with mock.patch.object(common, "YEAR_IX", ix):
            r = common.year_data()
        self.assertEqual(list(r), ["days", "idx"])
        self.assertEqual(len(r["days"]), 366)
        self.assertEqual(list(r["idx"]), ["spx", "kosdaq"])  # 화면 목록 순서는 assets.YEAR_IX 순서다
        spx, kq = r["idx"]["spx"], r["idx"]["kosdaq"]
        self.assertEqual((spx["name"], spx["market"], spx["end"]), ("S&P500", "us", "2025-01-02"))
        self.assertEqual(list(spx["years"]), ["2024", "2025"])
        self.assertEqual(list(kq["years"]), ["2025"])  # 받은 첫 해(2024)는 전년 말 종가가 없어 빠진다
        at = r["days"].index("01-02")
        self.assertEqual((spx["years"]["2025"][at], kq["years"]["2025"][at]), (10, -10))
        self.assertNotIn("days", spx)  # 달력 칸은 지수마다 싣지 않는다(파일만 커진다)


class Flows(Base):
    def test_stock_shares_are_rescaled_by_the_split_ratio(self):
        # 2026-01-07 에 50:1 분할. 수급 쪽 종가·주식 수는 분할 전 값 그대로, 가격 쪽은 수정주가다.
        self.csv("naver_flow_samsung.csv", [("2026-01-05", 100, -60, -40, 50.0, 2_500_000), ("2026-01-06", 10, 0, -10, 50.1, 2_600_000),
                                            ("2026-01-07", 5000, -5000, 0, 50.2, 53_000)],
                 ["foreign_net", "inst_net", "indiv_net", "foreign_ratio", "close"])
        px = pd.DataFrame({"close": [50_000.0, 52_000.0, 53_000.0]}, index=pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]))
        f = common.flows("samsung", px)
        self.assertEqual(f["adj"].tolist(), [50, 50, 1])
        self.assertEqual(f["foreign_sh"].tolist(), [5000, 500, 5000])
        self.assertEqual(f["close_adj"].tolist(), [50_000, 52_000, 53_000])
        self.assertAlmostEqual(f.loc["2026-01-05", "foreign_val"], 100 * 2_500_000 / 1e12)  # 금액은 분할과 무관하다
        self.assertEqual(f["foreign_ratio"].tolist(), [50.0, 50.1, 50.2])

    def test_index_is_money_only_in_trillion_won(self):
        self.csv("naver_flow_kospi.csv", [("2026-01-05", 12_000, -2_000, -10_000)], ["foreign_val", "inst_val", "indiv_val"])
        f = common.flows("kospi", None)
        self.assertEqual(f[["foreign_val", "inst_val", "indiv_val"]].iloc[0].tolist(), [1.2, -0.2, -1.0])  # 억원 -> 조원
        self.assertTrue(f["foreign_sh"].isna().all())

    def test_us_has_no_flows(self):
        px = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-01-05", "2026-01-06"]))
        f = common.flows("nvidia", px)
        self.assertTrue(f.index.equals(px.index))
        self.assertTrue(f.isna().all().all())


class RateSteps(unittest.TestCase):
    """정책금리를 "바뀐 날"로 줄이는 규칙. 틀려도 선은 그럴듯하게 그려지므로 손으로 셀 수 있는 표로 본다."""

    @staticmethod
    def wide(**cols):
        return pd.DataFrame({c: pd.Series({pd.Timestamp(d): v for d, v in rows.items()}) for c, rows in cols.items()}).sort_index()

    @staticmethod
    def daily(start, end, v):
        return {d.strftime("%Y-%m-%d"): v for d in pd.date_range(start, end)}

    def test_keeps_only_the_days_the_rate_changed(self):
        r = common.rate_steps(self.wide(A={**self.daily("2020-01-01", "2020-01-10", 1.0), **self.daily("2020-01-11", "2020-01-12", 1.5)}))
        self.assertEqual(r["areas"]["A"], {"last": "2020-01-12", "steps": [["2020-01-01", 1.0], ["2020-01-11", 1.5]]})

    def test_short_gap_carries_the_last_value(self):
        # 주말·연휴: 01-04 ~ 01-09 가 비어도 같은 금리가 이어진 것으로 본다
        r = common.rate_steps(self.wide(A={**self.daily("2020-01-01", "2020-01-03", 1.0), "2020-01-10": 1.0, "2020-01-11": 1.5}))
        self.assertEqual(r["areas"]["A"]["steps"], [["2020-01-01", 1.0], ["2020-01-11", 1.5]])

    def test_gap_is_filled_up_to_the_limit_and_left_empty_beyond_it(self):
        day = lambda n: (pd.Timestamp("2020-01-01") + pd.Timedelta(n, "D")).strftime("%Y-%m-%d")
        fill = common.rate_steps(self.wide(A={day(0): 1.0, day(common.RATE_FILL + 1): 0.5}))   # 빈 날이 딱 RATE_FILL 일
        self.assertEqual(fill["areas"]["A"]["steps"], [[day(0), 1.0], [day(common.RATE_FILL + 1), 0.5]])
        # 하루만 더 비어도 잇지 않는다. 정책금리가 없던 기간(일본)에 직전 금리를 그리면 안 된다
        hole = common.rate_steps(self.wide(A={day(0): 1.0, day(common.RATE_FILL + 2): 0.5}))
        self.assertEqual(hole["areas"]["A"]["steps"], [[day(0), 1.0], [day(1), None], [day(common.RATE_FILL + 2), 0.5]])

    def test_nothing_is_cut_at_the_front_and_start_is_the_earliest_country(self):
        # 전에는 1995-01-01 앞을 잘랐다. 이제 나라마다 받은 첫날부터 싣는다
        r = common.rate_steps(self.wide(A={**self.daily("1954-07-01", "1954-07-31", 7.0), **self.daily("1954-08-01", "1954-08-05", 6.0)},
                                        B=self.daily("1946-01-01", "1946-01-05", 3.0)))
        self.assertEqual(r["start"], "1946-01-01")
        self.assertEqual(r["areas"]["A"]["steps"], [["1954-07-01", 7.0], ["1954-08-01", 6.0]])

    def test_each_country_ends_on_its_own_last_day(self):
        # 늦게 오는 나라의 뒤를 메우지 않는다. 그 사이에 금리가 바뀌었을 수 있다
        r = common.rate_steps(self.wide(A=self.daily("2020-01-01", "2020-03-01", 1.0), B=self.daily("2020-01-05", "2020-02-01", 2.0)))
        self.assertEqual(r["end"], "2020-03-01")
        self.assertEqual(r["areas"]["B"], {"last": "2020-02-01", "steps": [["2020-01-05", 2.0]]})

    def test_country_without_values_is_left_out(self):
        w = self.wide(A=self.daily("2020-01-01", "2020-01-05", 1.0))
        w["B"] = np.nan
        self.assertEqual(list(common.rate_steps(w)["areas"]), ["A"])


class CpiMonths(unittest.TestCase):
    """물가를 화면에 싣는 모양. 달이 하나라도 밀리면 선 전체가 옆으로 어긋난다."""

    def test_runs_month_by_month_from_first_to_last_value_and_keeps_holes_empty(self):
        s = pd.Series({"2019-11": 9.0, "2019-12": None, "2020-01": None, "2020-02": 1.234, "2020-03": None, "2020-05": 2.0, "2020-06": None})
        got = common.cpi_months(s, "2020-01")  # 2020-04 는 줄 자체가 없다
        self.assertEqual(got, {"from": "2020-02", "v": [1.23, None, None, 2.0]})

    def test_nothing_to_show_is_none(self):
        self.assertIsNone(common.cpi_months(pd.Series({"2019-11": 9.0, "2020-01": None}), "2020-01"))


class RateData(Base):
    def test_attaches_screen_name_group_the_source_note_and_the_cpi(self):
        self.csv("bis_rates.csv", [("2020-01-01", 1.0, 9.0), ("2020-01-02", 1.25, 9.0)], ["US", "KR"])
        (self.d / "bis_rates_meta.json").write_text('{"US": "mid-point <of> the target"}', encoding="utf-8")
        # 달 색인은 글자다(2020-01). self.csv 는 날짜로 바꿔 쓰므로 직접 쓴다. 금리가 시작하는 달(2020-01) 앞의 물가는 싣지 않는다
        (self.d / "bis_cpi.csv").write_text("month,US,KR\n2019-12,2.0,\n2020-01,2.5,\n2020-02,2.3,\n", encoding="utf-8-sig")
        with mock.patch.object(common, "RATES", {"KR": ("한국", "주요"), "US": ("미국", "주요")}):
            r = common.rate_data()
        self.assertEqual(list(r["areas"]), ["KR", "US"])  # 화면 순서는 파일의 열 순서가 아니라 assets.RATES 순서다
        self.assertEqual(r["areas"]["US"], {"last": "2020-01-02", "steps": [["2020-01-01", 1.0], ["2020-01-02", 1.25]],
                                            "name": "미국", "group": "주요", "note": "mid-point <of> the target",
                                            "cpi": {"from": "2020-01", "v": [2.5, 2.3]}})
        self.assertEqual(r["areas"]["KR"]["note"], "")
        self.assertIsNone(r["areas"]["KR"]["cpi"])  # 물가가 없는 나라도 금리는 싣는다(검사는 check.py 가 한다)


if __name__ == "__main__":
    unittest.main()
