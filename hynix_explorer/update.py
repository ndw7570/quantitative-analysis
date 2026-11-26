"""최신본을 한 번에 만든다: 받기(fetch) -> 분석(analyze) -> 지표(signals) -> 검사(check) -> HTML(build) -> 검사(check html).

쓰는 법 (이 폴더에서):
    ../.venv/Scripts/python.exe update.py              # 새 날짜만 받아서 다시 만든다
    ../.venv/Scripts/python.exe update.py --full       # 수급을 2005년부터 전부 다시 받는다(약 15분)
    ../.venv/Scripts/python.exe update.py --today      # 18시 전이라도 오늘 한국 장까지 받는다(15:40 부터. 오늘 수급은 빈다)
    ../.venv/Scripts/python.exe update.py --no-fetch  # 받지 않고 지금 있는 자료로 다시 만든다(화면만 고쳤을 때)
    ../.venv/Scripts/python.exe update.py --out 경로   # 다른 곳에 만든다

단계를 손으로 따로 돌리면 한 단계를 빼먹거나 실패한 단계 뒤를 그대로 이어 돌리게 된다.
여기서는 한 단계가 실패하면 멈추고, 끝나면 자료가 며칠까지 들어왔는지와 지난번과 달라진 점을 보여 준다.
HTML 은 옆에 임시 파일로 만들어 검사를 통과한 뒤에만 제자리로 옮긴다 - 어디서 멈추든 보고 있던 HTML 은 그대로다.
작동 방식 설명은 프로젝트의 plan/specs/explorer-architecture.md 에 있다.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
DATA, LOGS = HERE / "data", HERE / "logs"
REPORT = Path("deck") / "report" / "2026-11-25-explorer-30y" / "index.html"
LAST = DATA / "last_run.json"


def default_out(here=HERE):
    """최신본은 늘 같은 파일에 덮어쓴다. 날짜별로 따로 남기려면 --out 으로 다른 경로를 준다.

    프로젝트 폴더(deck/report 가 있는 곳)를 위로 올라가며 찾는다. 몇 단계 위인지를 숫자로 박아 두었다가
    코드 폴더를 한 단계 옮겼을 때 엉뚱한 곳에 HTML 을 만든 적이 있다(2026-11-25).
    이 저장소만 따로 받은 PC 에는 프로젝트 폴더가 없으므로 저장소 안 out/ 에 만든다.
    """
    for p in here.parents:
        if (p / "deck" / "report").is_dir():
            return p / REPORT
    return here.parent / "out" / "index.html"


def temp_out(out):
    """검사를 통과하기 전까지 새 판을 두는 자리. 같은 폴더여야 마지막 옮기기가 한 번에 끝난다.

    이름이 .html 로 끝나야 한다. index.html.new 로 두었더니 브라우저가 페이지로 읽지 않아
    화면 검사가 "차트 0개"로 실패했다(2026-11-25).
    """
    return out.with_name(out.stem + ".new" + out.suffix)


def step(name, *args, log=None):
    """한 단계를 돌리고 출력은 logs/<name>.log 에 둔다. 실패하면 로그 끝을 보여 주고 전체를 멈춘다."""
    log = LOGS / f"{log or name}.log"
    t0 = time.time()
    print(f"[{name}] 시작", flush=True)
    with open(log, "w", encoding="utf-8") as f:
        # 자식 프로세스의 한글 출력이 Windows 기본 인코딩(cp949)으로 나가면 로그가 깨진다
        code = subprocess.run([sys.executable, "-u", f"{name}.py", *args], cwd=HERE, stdout=f, stderr=subprocess.STDOUT,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode
    sec = time.time() - t0
    if code != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
        print(f"[{name}] 실패 (종료 코드 {code}, {sec:.0f}초). 로그 끝부분:\n" + "\n".join(tail))
        print(f"전체 로그: {log}\n앞 단계까지의 결과는 남아 있지만 HTML 은 바꾸지 않았습니다.")
        sys.exit(code)
    print(f"[{name}] 끝 ({sec:.0f}초)", flush=True)
    # 검사의 [주의]는 멈추지 않지만 로그 파일에만 있으면 아무도 안 본다
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("[주의]", "[건너뜀]")):
            print("  " + line, flush=True)


def last_day(path):
    """CSV 의 마지막 줄 날짜. 파일을 통째로 해석하지 않고 끝만 본다."""
    lines = path.read_text(encoding="utf-8-sig").rstrip().splitlines()
    return lines[-1].split(",")[0][:10] if len(lines) > 1 else None


def freshness():
    """자료가 며칠까지 들어왔는지. 가격보다 수급이 뒤처져 있으면 화면의 마지막 날 수급이 비어 있게 된다."""
    kinds = {"한국 가격": "naver_px_*.csv", "미국 가격": "yf_*.csv", "한국 수급": "naver_flow_*.csv",
             "정책금리": "bis_rates.csv", "소비자물가": "bis_cpi.csv"}  # 둘 다 가장 늦게까지 온 나라의 날짜(물가는 달)다. 나라별로는 check.py 가 본다
    days = {label: {p.stem: last_day(p) for p in sorted(DATA.glob(pat))} for label, pat in kinds.items()}
    print("\n자료의 마지막 날")
    for label, d in days.items():
        vals = sorted(set(d.values()), key=str)
        print(f"  {label}: {' / '.join(map(str, vals))}" + ("" if len(vals) == 1 else f"  <- 파일마다 다름: {d}"))
    px_end = max(days["한국 가격"].values())
    late = {k: v for k, v in days["한국 수급"].items() if v != px_end}
    if late:
        print(f"  [주의] 수급이 가격({px_end})보다 뒤처진 파일: {late}\n"
              "         장이 끝난 직후에는 수급이 아직 안 올라왔을 수 있습니다. 저녁에 다시 돌리면 채워집니다.")
    return px_end


def summary():
    """이번 결과를 요약하고 지난번과 비교한다.

    지난번 마지막 날의 종가가 이번에 받은 값과 다르면 둘 중 하나다.
    - 수정주가가 다시 계산됐다(액면분할·감자 등). 과거 값이 통째로 바뀌므로 지난번 화면과 숫자가 달라도 오류가 아니다.
    - 미국 대상: 지난번에는 그날 미국 종가가 아직 없어서 전날 값이 이어져 있었고(common.on_calendar), 이번에 진짜 값이 들어왔다.
    어느 쪽인지는 여기서 가리지 못한다. 처음에는 앞의 것으로만 단정해 적었다가 2026-11-25 에 뒤의 경우를 잘못 설명했다.
    """
    now = {}
    for p in sorted(DATA.glob("result_*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        s, m = r["series"], r["meta"]
        now[m["key"]] = {"name": m["name"], "start": m["start"], "end": m["end"], "cp": m["changepoints"],
                         "close": dict(zip(s["date"][-400:], s["close"][-400:]))}
    old = json.loads(LAST.read_text(encoding="utf-8")) if LAST.exists() else None
    end = max(v["end"] for v in now.values())
    print(f"\n화면의 마지막 날: {end}")
    by_year = {}
    for v in sorted(now.values(), key=lambda v: v["start"]):
        by_year.setdefault(v["start"][:4], []).append(v["name"])
    print("대상별 시작 연도: " + " / ".join(f"{y}년 {'·'.join(n)}" for y, n in by_year.items()))
    if old:
        print(f"지난번 실행: 마지막 날 {old['end']}" + (" (같은 날 - 새로 들어온 날이 없습니다)" if old["end"] == end else ""))
        for k, v in now.items():
            o = old["assets"].get(k)
            if not o:
                print(f"  {v['name']}: 새로 들어온 대상")
                continue
            was, cur = o["last_close"], v["close"].get(old["end"])
            if cur is not None and was and abs(cur / was - 1) > 1e-4:
                print(f"  [주의] {v['name']}: {old['end']} 종가가 지난번 {was} -> 이번 {cur}. "
                      "수정주가가 다시 계산됐거나(과거 값 전체가 바뀜), 미국 대상이면 그날 종가가 한쪽 실행에서 비어 전날 값이 이어진 것입니다.")
            if o["cp"] != v["cp"]:
                # 변화점은 전체 기간을 보고 정하는 사후 계산이라 날이 늘면 개수가 바뀔 수 있다
                print(f"  {v['name']}: 변화점 {o['cp']}개 -> {v['cp']}개")
    else:
        print("지난번 실행 기록이 없습니다(처음 돌림).")
    LAST.write_text(json.dumps({"end": end, "run_at": time.strftime("%Y-%m-%d %H:%M"), "assets": {
        k: {"last_close": v["close"][v["end"]], "cp": v["cp"], "start": v["start"]} for k, v in now.items()}},
        ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    args = sys.argv[1:]
    out = Path(args[args.index("--out") + 1]).resolve() if "--out" in args else default_out()
    LOGS.mkdir(exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if "--no-fetch" not in args:
        step("fetch", *[a for a in ("--full", "--today") if a in args])
    px_end = freshness()
    step("analyze")
    step("signals")
    step("check")
    new = temp_out(out)
    step("build", str(new))
    step("check", "html", str(new), log="check_html")
    os.replace(new, out)
    summary()
    print(f"\n자료 기준일 {px_end} · 전체 {time.time() - t0:.0f}초 · {out.stat().st_size / 1e6:.1f}MB")
    print(out.as_uri())


if __name__ == "__main__":
    main()
