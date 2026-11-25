"""fetch.py 의 받기 규칙을 가짜 서버로 시험한다. 실제 서버에는 요청을 보내지 않는다.

여기서 지키려는 것은 전부 한 번씩 틀렸거나 틀리면 조용히 값이 어긋나는 것이다:
- 수급 쪽 넘기기에서 하루도 빠지지 않는다 (10년판은 60거래일마다 하루가 빠져 있었다)
- 서버가 빈 응답·오류를 줘도 멀쩡한 파일을 덮어쓰지 않는다
- 집계 전 값("-", 0 0 0)을 순매수 0 으로 남기지 않는다
"""
import contextlib
import io
import math
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

import fetch


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.text = body if isinstance(body, str) else ""

    def json(self):
        return self.body


class FakeTrend:
    """네이버 종목 수급 쪽의 흉내. bizdate 로 부르면 "그날 앞" 60거래일을 최근 날짜부터 준다(2026-11-25 에 확인한 동작)."""

    def __init__(self, days):
        self.days, self.calls, self.fixed = sorted(days), [], {}

    def row(self, d):
        return {"bizdate": d, "foreignerPureBuyQuant": self.fixed.get(d, f"+{int(d[4:]):,}"), "organPureBuyQuant": "-2,000",
                "individualPureBuyQuant": "1,000", "foreignerHoldRatio": "50.12%", "closePrice": "100,000"}

    def get(self, url, **kw):
        biz = url.split("bizdate=")[1]
        self.calls.append(biz)
        return Resp([self.row(d) for d in reversed([d for d in self.days if d < biz][-60:])])


def days(start, end):
    return [d.strftime("%Y%m%d") for d in pd.bdate_range(start, end)]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        for p in (mock.patch.multiple(fetch, OUT=self.out, STOCKS={"hynix": "000660"}, KR={"hynix": "000660"},
                                      S="20250101", FULL=False),
                  mock.patch.object(fetch.time, "sleep", lambda s: None),
                  contextlib.redirect_stdout(io.StringIO())):
            p.__enter__()
            self.addCleanup(p.__exit__, None, None, None)

    def run_job(self, job, server, end):
        with mock.patch.object(fetch, "END", end), mock.patch.object(fetch.requests, "get", server.get):
            job()

    def saved(self, name):
        return pd.read_csv(self.out / name, index_col=0, parse_dates=True)


class Num(unittest.TestCase):
    def test_reads_signs_commas_percent(self):
        self.assertEqual(fetch.num("+1,234"), 1234)
        self.assertEqual(fetch.num("-1,000"), -1000)
        self.assertEqual(fetch.num("50.12%"), 50.12)

    def test_unposted_value_is_missing_not_zero(self):
        self.assertTrue(math.isnan(fetch.num("-")))
        self.assertTrue(math.isnan(fetch.num("")))


class Flow(Base):
    END = date(2026, 11, 24)

    def test_first_run_gets_every_day_including_the_last(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-24"))
        self.run_job(fetch.flow, srv, self.END)
        got = [d.strftime("%Y%m%d") for d in self.saved("naver_flow_hynix.csv").index]
        self.assertEqual(got, srv.days)  # 쪽 경계에서도, 마지막 날도 빠지지 않는다
        self.assertEqual(srv.calls[0], "20261125")  # 끝 날 다음 날로 불러야 끝 날이 온다
        self.assertEqual(len(srv.calls), self.pages(srv))

    @staticmethod
    def pages(srv):
        """처음부터 받을 때의 호출 수. 마지막에 빈 쪽을 한 번 받아야 더 과거가 없는 줄 안다."""
        return math.ceil(len(srv.days) / 60) + 1

    def test_next_run_stops_at_what_it_already_has(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-17"))
        self.run_job(fetch.flow, srv, date(2026, 11, 17))
        srv.days, srv.calls = days("2025-01-02", "2026-11-24"), []
        self.run_job(fetch.flow, srv, self.END)
        self.assertEqual(len(srv.calls), 1)
        self.assertEqual([d.strftime("%Y%m%d") for d in self.saved("naver_flow_hynix.csv").index], srv.days)

    def test_long_gap_is_filled_without_holes(self):
        srv = FakeTrend(days("2025-01-02", "2026-06-30"))
        self.run_job(fetch.flow, srv, date(2026, 6, 30))
        srv.days, srv.calls = days("2025-01-02", "2026-11-24"), []  # 104거래일이 새로 생겼다 = 두 쪽
        self.run_job(fetch.flow, srv, self.END)
        self.assertEqual(len(srv.calls), 2)
        self.assertEqual([d.strftime("%Y%m%d") for d in self.saved("naver_flow_hynix.csv").index], srv.days)

    def test_recent_page_is_refetched_so_corrected_values_arrive(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-24"))
        srv.fixed["20261120"] = "-"  # 처음 받을 때는 집계 전이었다
        self.run_job(fetch.flow, srv, self.END)
        self.assertTrue(math.isnan(self.saved("naver_flow_hynix.csv").loc["2026-11-20", "foreign_net"]))
        srv.fixed["20261120"] = "7,777"
        self.run_job(fetch.flow, srv, self.END)
        self.assertEqual(self.saved("naver_flow_hynix.csv").loc["2026-11-20", "foreign_net"], 7777)

    def test_full_refetches_from_the_start(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-24"))
        self.run_job(fetch.flow, srv, self.END)
        srv.calls = []
        with mock.patch.object(fetch, "FULL", True):
            self.run_job(fetch.flow, srv, self.END)
        self.assertEqual(len(srv.calls), self.pages(srv))

    def test_server_repeating_a_page_does_not_loop_forever(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-24"))
        page = [srv.row(d) for d in reversed(srv.days[-60:])]
        calls = []

        class Stuck:
            def get(self, url, **kw):
                calls.append(url)
                if len(calls) > 5:
                    raise AssertionError("같은 쪽을 계속 받고 있다")
                return Resp(page)
        self.run_job(fetch.flow, Stuck(), self.END)
        self.assertEqual(len(calls), 2)

    def test_error_status_raises_and_keeps_the_file(self):
        srv = FakeTrend(days("2025-01-02", "2026-11-24"))
        self.run_job(fetch.flow, srv, self.END)
        before = (self.out / "naver_flow_hynix.csv").read_bytes()

        class Down:
            def get(self, url, **kw):
                return Resp([], status=503)
        with self.assertRaises(RuntimeError):
            self.run_job(fetch.flow, Down(), self.END)
        self.assertEqual((self.out / "naver_flow_hynix.csv").read_bytes(), before)


class KrPrice(Base):
    def text(self, n):
        return "[" + ",\n".join(f'["{d}", 100, 110, 90, {100 + i}, 1000, 50.0]' for i, d in enumerate(days("2025-01-02", "2026-11-24")[:n])) + "]"

    def test_short_answer_raises_and_keeps_the_file(self):
        f = self.out / "naver_px_hynix.csv"
        f.write_text("멀쩡한 파일", encoding="utf-8")
        srv = mock.Mock(get=lambda url, **kw: Resp(self.text(50)))
        with self.assertRaises(RuntimeError):
            self.run_job(fetch.kr_price, srv, date(2026, 11, 24))
        self.assertEqual(f.read_text(encoding="utf-8"), "멀쩡한 파일")

    def test_saves_rows_in_date_order(self):
        srv = mock.Mock(get=lambda url, **kw: Resp(self.text(150)))
        self.run_job(fetch.kr_price, srv, date(2026, 11, 24))
        df = self.saved("naver_px_hynix.csv")
        self.assertEqual(len(df), 150)
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(df["close"].iloc[-1], 249)


class Us(Base):
    def run_us(self, last_close):
        idx = pd.bdate_range("2026-01-02", "2026-11-20")  # 아침 7시 전에 돌려도 잘리지 않는 날까지
        df = pd.DataFrame({"Adj Close": 1.0, "Close": [100.0] * (len(idx) - 1) + [last_close], "High": 2.0, "Low": 1.0,
                           "Open": 1.0, "Volume": 10}, index=idx)
        yf = mock.Mock(download=lambda *a, **kw: df)
        with mock.patch.dict("sys.modules", yfinance=yf), \
                mock.patch.multiple(fetch, BENCH={}, US={"jnj": "JNJ"}, TODAY=date(2026, 11, 25)):
            fetch.us()

    def test_last_day_without_a_close_raises_and_keeps_the_file(self):
        f = self.out / "yf_jnj.csv"
        f.write_text("멀쩡한 파일", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.run_us(float("nan"))
        self.assertEqual(f.read_text(encoding="utf-8"), "멀쩡한 파일")

    def test_saves_when_the_last_day_has_a_close(self):
        self.run_us(101.0)
        self.assertEqual(self.saved("yf_jnj.csv")["Close"].iloc[-1], 101.0)


class KospiFlow(Base):
    def setUp(self):
        super().setUp()
        self.days = days("2026-11-16", "2026-11-24")
        pd.DataFrame({"close": 1.0}, index=pd.to_datetime(self.days)).to_csv(self.out / "naver_px_kospi.csv")
        self.calls, self.unposted, self.absent = [], {"20261124"}, {"20261119"}

    def get(self, url, **kw):
        d = url.split("bizdate=")[1]
        self.calls.append(d)
        if d in self.absent:  # 그날 자료가 없으면 다른 날짜가 돌아온다
            return Resp({"bizdate": "20261118", "foreignValue": "9", "institutionalValue": "9", "personalValue": "9"})
        if d in self.unposted:
            return Resp({"bizdate": d, "foreignValue": "0", "institutionalValue": "0", "personalValue": "0"})
        return Resp({"bizdate": d, "foreignValue": "+1,234", "institutionalValue": "-234", "personalValue": "-1,000"})

    def test_skips_unposted_and_absent_days_then_fetches_only_those_again(self):
        self.run_job(fetch.kospi_flow, self, date(2026, 11, 24))
        df = self.saved("naver_flow_kospi.csv")
        self.assertEqual(sorted(self.calls), self.days)
        self.assertEqual(len(df), len(self.days) - 2)  # 0 0 0 인 날과 다른 날짜가 돌아온 날은 남기지 않는다
        self.assertEqual(df.loc["2026-11-23"].tolist(), [1234, -234, -1000])
        self.calls, self.unposted = [], set()
        self.run_job(fetch.kospi_flow, self, date(2026, 11, 24))
        self.assertEqual(sorted(self.calls), ["20261119", "20261124"])  # 받은 날은 다시 부르지 않는다
        self.assertIn(pd.Timestamp("2026-11-24"), self.saved("naver_flow_kospi.csv").index)

    def test_does_not_keep_todays_value_before_it_settles(self):
        self.unposted = set()  # 서버는 오늘 값을 주지만(장 마감 직후 값) 한번 남기면 다시 받지 않으므로 부르지 않는다
        with mock.patch.object(fetch, "UNSETTLED", "20261124"):
            self.run_job(fetch.kospi_flow, self, date(2026, 11, 24))
        self.assertNotIn("20261124", self.calls)
        self.assertNotIn(pd.Timestamp("2026-11-24"), self.saved("naver_flow_kospi.csv").index)


if __name__ == "__main__":
    unittest.main()
