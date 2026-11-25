"""data/result_*.json + data/signals_*.json + template.html -> 탐색기 HTML 한 파일 (데이터 내장)."""
import json
import sys
from pathlib import Path

from assets import ASSETS

HERE = Path(__file__).parent
load = lambda name: json.loads((HERE / "data" / name).read_text(encoding="utf-8"))
data = {k: {"R": load(f"result_{k}.json"), "G": load(f"signals_{k}.json")} for k in ASSETS}
# 화면은 두 창이 같은 날짜 번호를 쓴다고 가정한다. 대상마다 달력이 다르면 조용히 틀린 날을 비교하게 된다.
dates = [d["R"]["series"]["date"] for d in data.values()]
assert all(x == dates[0] for x in dates), "대상별 날짜 목록이 다르다"

html = (HERE / "template.html").read_text(encoding="utf-8")
assert html.count("__DATA__") == 1
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))), encoding="utf-8")
print(out, out.stat().st_size, "bytes")
