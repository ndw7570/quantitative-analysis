"""data/result_*.json + data/signals_*.json + template.html -> 탐색기 HTML 한 파일 (데이터 내장)."""
import json
import sys
from pathlib import Path

from assets import ASSETS
from common import hike_data, rate_data, year_data
from events import load_events
from slope import slope_data
from trend import trend_data

HERE = Path(__file__).parent
load = lambda name: json.loads((HERE / "data" / name).read_text(encoding="utf-8"))
data = {k: {"R": load(f"result_{k}.json"), "G": load(f"signals_{k}.json")} for k in ASSETS}
# 화면은 두 창이 같은 날짜 번호를 쓴다고 가정한다. 대상마다 달력이 다르면 조용히 틀린 날을 비교하게 된다.
dates = [d["R"]["series"]["date"] for d in data.values()]
assert all(x == dates[0] for x in dates), "대상별 날짜 목록이 다르다"

html = (HERE / "template.html").read_text(encoding="utf-8")
assert all(html.count(s) == 1 for s in ("__DATA__", "__YIX__", "__RATES__", "__HIKE__", "__EVENTS__", "__TREND__", "__SLOPE__"))
# 탭 3 은 지수마다 자기 시장의 달력 그대로 쓴다. 한국 달력에 얹은 값(result)으로는 미국의 한 해를 날짜대로 그릴 수 없다.
html = html.replace("__YIX__", json.dumps(year_data(), ensure_ascii=False, separators=(",", ":")))
# 탭 4 의 금리 설명은 BIS 가 쓴 글이다. 그 안에 "</script>" 가 있으면 페이지가 거기서 잘리므로 "</" 를 풀어 쓴다(JSON 으로는 같은 글자다).
rates = rate_data()
html = html.replace("__RATES__", json.dumps(rates, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
# 탭 4 의 인상기 분석(정책금리에서 계산)과 탭 1 툴팁의 날짜별 이슈(events/events.csv - 손으로 적은 글이 섞여 있어 "</" 를 같이 푼다)
html = html.replace("__HIKE__", json.dumps(hike_data(rates), ensure_ascii=False, separators=(",", ":")))
html = html.replace("__EVENTS__", json.dumps(load_events(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
# 탭 5 의 추세 상태(result_*.json 의 종가에서 규칙으로 매긴 것. 2초 안쪽이라 따로 단계를 두지 않고 여기서 계산한다)
html = html.replace("__TREND__", json.dumps(trend_data(), ensure_ascii=False, separators=(",", ":")))
# 탭 6 의 회귀 추세는 화면이 계산한다. 여기서는 자기 검사용 기준값만 넣는다(slope.py)
html = html.replace("__SLOPE__", json.dumps(slope_data(), ensure_ascii=False, separators=(",", ":"), allow_nan=False))
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))), encoding="utf-8")
print(out, out.stat().st_size, "bytes")
