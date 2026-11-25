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


if __name__ == "__main__":
    unittest.main()
