"""하이닉스(000660) 최근 1년 데이터 수집.

소스마다 막히는 경우가 잦아서(KRX 는 로그인 요구로 자주 실패) 소스별로 따로 시도하고
무엇이 성공했는지 그대로 출력한다. 실패를 숨기면 보고서가 빈 데이터로 그려진다.
"""
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

TICKER = "000660"
END = date.today()
# 이동평균 120일·HMM 학습에 앞쪽 여유가 필요해서 1년보다 넉넉히 받는다. 보고서는 최근 1년만 그린다.
START = END - timedelta(days=365 * 3)
S, E = START.strftime("%Y%m%d"), END.strftime("%Y%m%d")


def attempt(name, fn):
    try:
        df = fn()
        if df is None or len(df) == 0:
            print(f"[EMPTY] {name}")
            return
        df.to_csv(OUT / f"{name}.csv", encoding="utf-8-sig")
        print(f"[OK] {name}: {len(df)} rows, {df.index.min()} ~ {df.index.max()}")
        print("     cols:", list(df.columns)[:12])
    except Exception as ex:  # noqa: BLE001 - 소스별 실패 원인을 그대로 보려고 넓게 잡는다
        print(f"[FAIL] {name}: {type(ex).__name__}: {str(ex)[:200]}")
        if "-v" in sys.argv:
            traceback.print_exc()


def yf_one(sym):
    import yfinance as yf

    df = yf.download(sym, start=START.isoformat(), end=(END + timedelta(days=1)).isoformat(),
                     auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


from pykrx import stock  # noqa: E402

attempt("krx_ohlcv", lambda: stock.get_market_ohlcv(S, E, TICKER))
# 야후의 한국 종목 값은 KRX 와 52일 어긋났고 마지막 날이 비어 있었다. 종목 가격은 KRX 것을 쓴다.
attempt("krx_samsung", lambda: stock.get_market_ohlcv(S, E, "005930"))
attempt("krx_investor_value", lambda: stock.get_market_trading_value_by_date(S, E, TICKER))
attempt("krx_short_volume", lambda: stock.get_shorting_volume_by_date(S, E, TICKER))
attempt("krx_short_balance", lambda: stock.get_shorting_balance_by_date(S, E, TICKER))
attempt("krx_foreign_hold", lambda: stock.get_exhaustion_rates_of_foreign_investment(S, E, TICKER))
attempt("krx_fundamental", lambda: stock.get_market_fundamental(S, E, TICKER))
attempt("krx_kospi", lambda: stock.get_index_ohlcv(S, E, "1001"))

attempt("yf_hynix", lambda: yf_one("000660.KS"))
attempt("yf_kospi", lambda: yf_one("^KS11"))
attempt("yf_sox", lambda: yf_one("^SOX"))
attempt("yf_nasdaq", lambda: yf_one("^IXIC"))
attempt("yf_samsung", lambda: yf_one("005930.KS"))
attempt("yf_usdkrw", lambda: yf_one("KRW=X"))
