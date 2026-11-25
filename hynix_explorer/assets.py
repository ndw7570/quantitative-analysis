"""분석 대상 목록. 종목을 늘릴 때 여기만 고치면 fetch/analyze/signals/build 가 따라온다.

market: kr = 한국거래소 종목·지수, us = 미국 종목·지수. 미국 대상은 수급(투자자별 순매수) 자료가 없고,
  한국 달력에 얹어서 쓴다(common.on_calendar). 화면의 두 창이 같은 날짜 번호를 써야 하기 때문이다.
code: kr 종목은 종목코드, us 는 야후 파이낸스 티커.
reg: 시장모형("고유분")에서 이 대상을 설명하는 데 쓰는 두 변수.
  - 자기 자신이 큰 비중을 차지하는 지수는 쓰지 않는다(하이닉스·삼성전자를 코스피로 설명하면 자기로 자기를 설명하게 된다).
    삼성전기는 코스피에서 차지하는 몫이 작다고 보고 코스피를 썼다(비중은 확인 안 함).
  - 한국 대상에 붙는 미국 값은 한국 장이 열리기 전 마지막 종가, 미국 대상에 붙는 미국 값은 같은 날 종가다(analyze.py).
group: 화면의 대상 고르기 목록에서 묶어 보여 주는 이름.
cmp: "첫날 = 100 비교" 차트에서 자기 자신 옆에 그리는 비교선 3개. 8개를 다 그리면 읽을 수 없어서 대상마다 고른다.
  자기 자신은 검은 굵은 선이고 비교선만 대상별 고정색을 쓴다(template.html 의 ENT). 한 차트에 같이 나오는 색끼리
  구별되는지 색 검사기로 확인한 조합이라, 조합을 바꾸면 다시 검사해야 한다(예: 엔비디아 창에 SOX 를 넣으면 나스닥·마이크론과 색이 붙는다).
"""
ASSETS = {
    "hynix": {"group": "한국 반도체·지수", "name": "SK하이닉스", "market": "kr", "kind": "stock", "code": "000660",
              "reg": ["samsung", "sox"], "cmp": ["samsung", "sox", "kospi"]},
    "samsung": {"group": "한국 반도체·지수", "name": "삼성전자", "market": "kr", "kind": "stock", "code": "005930",
                "reg": ["hynix", "sox"], "cmp": ["hynix", "sox", "kospi"]},
    "semco": {"group": "한국 반도체·지수", "name": "삼성전기", "market": "kr", "kind": "stock", "code": "009150",
              "reg": ["kospi", "sox"], "cmp": ["samsung", "sox", "kospi"]},
    "kospi": {"group": "한국 반도체·지수", "name": "코스피", "market": "kr", "kind": "index", "code": "KOSPI",
              "reg": ["spx", "sox"], "cmp": ["hynix", "samsung", "sox"]},
    "nvidia": {"group": "미국 반도체·지수", "name": "엔비디아", "market": "us", "kind": "stock", "code": "NVDA",
               "reg": ["spx", "sox"], "cmp": ["nasdaq", "micron", "hynix"]},
    "micron": {"group": "미국 반도체·지수", "name": "마이크론", "market": "us", "kind": "stock", "code": "MU",
               "reg": ["spx", "sox"], "cmp": ["hynix", "samsung", "sox"]},
    "nasdaq": {"group": "미국 반도체·지수", "name": "나스닥 종합", "market": "us", "kind": "index", "code": "^IXIC",
               "reg": ["spx", "sox"], "cmp": ["nvidia", "sox", "kospi"]},
    # 조선·방산·원전: 반도체와 상관이 없어 SOX 대신 코스피·S&P500 으로 설명한다(각 종목의 코스피 비중은 확인 안 함).
    # 10년판을 만들 때 2014년 이전에 상장했고 긴 거래정지가 없는 종목만 골랐다. 그래서 HD현대중공업(2021 상장),
    # LIG넥스원(2015 상장), 한화오션(2016~2017 거래정지)은 뺐다. 30년판부터는 대상마다 시작 연도가 달라도 되므로
    # (analyze.py 의 MIN_TRAIN) 상장이 늦은 종목도 넣을 수 있다. 긴 거래정지는 여전히 국면·변화점을 흐린다.
    "ksoe": {"group": "한국 조선·방산·원전", "name": "HD한국조선해양", "market": "kr", "kind": "stock", "code": "009540",
             "reg": ["kospi", "spx"], "cmp": ["hynix", "sox", "kospi"]},
    "shi": {"group": "한국 조선·방산·원전", "name": "삼성중공업", "market": "kr", "kind": "stock", "code": "010140",
            "reg": ["kospi", "spx"], "cmp": ["hynix", "sox", "kospi"]},
    "hanwha": {"group": "한국 조선·방산·원전", "name": "한화에어로스페이스", "market": "kr", "kind": "stock", "code": "012450",
               "reg": ["kospi", "spx"], "cmp": ["hynix", "sox", "kospi"]},
    "rotem": {"group": "한국 조선·방산·원전", "name": "현대로템", "market": "kr", "kind": "stock", "code": "064350",
              "reg": ["kospi", "spx"], "cmp": ["hynix", "sox", "kospi"]},
    "doosan": {"group": "한국 조선·방산·원전", "name": "두산에너빌리티", "market": "kr", "kind": "stock", "code": "034020",
               "reg": ["kospi", "spx"], "cmp": ["hynix", "sox", "kospi"]},
    # 미국 헬스케어: 제약·의료기기·보험에서 시가총액이 큰 것 하나씩(순위는 확인 안 함).
    "lilly": {"group": "미국 헬스케어", "name": "일라이 릴리", "market": "us", "kind": "stock", "code": "LLY",
              "reg": ["spx", "nasdaq"], "cmp": ["nasdaq", "nvidia", "kospi"]},
    "jnj": {"group": "미국 헬스케어", "name": "존슨앤드존슨", "market": "us", "kind": "stock", "code": "JNJ",
            "reg": ["spx", "nasdaq"], "cmp": ["nasdaq", "nvidia", "kospi"]},
    "unh": {"group": "미국 헬스케어", "name": "유나이티드헬스", "market": "us", "kind": "stock", "code": "UNH",
            "reg": ["spx", "nasdaq"], "cmp": ["nasdaq", "nvidia", "kospi"]},
}
# 비교선·팝업의 "상대 비교" 줄에 나오는 것들. template.html 의 ENT 와 같은 목록이어야 한다.
# 대상 전부를 넣으면 대상마다 열이 대상 수만큼 붙어 파일이 대상 수의 제곱으로 커진다.
CMP_ENT = ["hynix", "samsung", "semco", "kospi", "nvidia", "micron", "nasdaq", "sox"]
# 대상은 아니고 설명 변수·비교선으로만 쓰는 미국 지수
BENCH = {"sox": "^SOX", "spx": "^GSPC"}
NAMES = {**{k: a["name"] for k, a in ASSETS.items()}, "sox": "SOX", "spx": "S&P500"}


def dec(key):
    """저장할 때 남기는 소수 자릿수. 원화 종목은 정수, 지수는 둘째 자리까지가 원래 값이다.
    달러 종목은 넷째 자리까지 둔다 - 분할을 반영한 과거 가격이 1달러 아래라서 둘째 자리에서 끊으면 하루 등락이 뭉개진다."""
    a = ASSETS.get(key)
    if a is None or a["kind"] == "index":
        return 2
    return 0 if a["market"] == "kr" else 4
