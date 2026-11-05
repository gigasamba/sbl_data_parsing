"""질문 유형 라우터 — 규칙만(LLM 0회), 질문 글자만 보고 유형 하나 + 첫 도구·검색 설정을 고른다.

TYPE_TABLE은 **우선순위 목록**(위가 더 구체적 — 하나만 고름, 첫 매치가 이김). 예: "몇 개인가"(count)와
"흐름도"(figure)가 같은 질문에 있으면 figure가 더 구체적(그림을 읽어야 답이 나옴)이라 위에 둔다.
ponytail: 정규식 하나로 유형을 가르는 규칙 — 겹치는 단서(최근 N년 추이를 "최신"으로, 총액이 들어간 비교 질문을
"집계"로)는 오분류할 수 있다(resources/vocab/qtype_labels.json 혼동 행렬). 더 정확해야 하면 작은 LLM 분류로.

호출자: rank_rules.py weights()(bm25 가중 조정).
정확도 점검: tests/server/mcp/test_question_type.py(resources/vocab/qtype_labels.json)
"""

import copy
import re

from common.core.docmeta import RE_LATEST_QUESTION  # 최신판 질문 단서

# 집계·목록 단서
_AGG_VOCAB_DEFAULT = {  # 지표 판별 단서어(건수·합계·수량·금액·단가·배치)
    "count": ["건수", r"몇\s*건", "개수", r"몇\s*개(?!월)", r"how\s+many", r"number\s+of", r"\bcount\b"],
    # ↑ "몇\s*개(?!월)" — "몇 개월"(기간)이 건수 질문으로 걸리지 않게
    "sum": ["합계", "합", "총", "전체", r"모두\s*더", "total", "sum"],
    "qty": ["수량", "용량", "qty", "quantity", "capacity", "volume"],
    "amount": ["금액", "규모", r"contract\s*value", r"\bvalue\b", "amount"],
    "unit_price": ["단가", r"unit\s*price"],
    "batch": ["배치", "batch"],
}


_AGG_VOCAB = _AGG_VOCAB_DEFAULT
COUNT_RE = re.compile("|".join(_AGG_VOCAB["count"]), re.I)
SUM_RE = re.compile("|".join(_AGG_VOCAB["sum"]), re.I)
LIST_RE = re.compile(r"각\s*계약|계약별|계약마다|of\s+each|each\s+contract|목록|\blist\b", re.I)
MAXMIN_RE = re.compile(r"가장\s*(많은|적은|큰|작은)|최대|최소|\bmax\b|\bmin\b|\bmost\b|\bleast\b", re.I)

_AVG_RE = re.compile(r"평균|average|\bavg\b", re.I)
_FIGURE_RE = re.compile(r"그림|그래프|도식|차트|흐름도|순서도|막대|flowchart|diagram|\bgraph\b|\bchart\b|\bfigure\b", re.I)
_COMPARE_RE = re.compile(r"비교|차이|대비|더\s*(?:큰|작은|많은|적은|높은|낮은)|\bcompare\b|\bdifference\b|\bvs\.?\b", re.I)
_TREND_RE = re.compile(r"추이|추세|연도별|연도\s*별|변화\s*추이|\btrend\b|year[- ]over[- ]year|\byoy\b", re.I)
_TERM_RE = re.compile(
    r"\b뜻\b|의미|정의\s*(?:가|는|를)?|무엇을\s*의미|란\s*(?:무엇|뜻)|\bdefinition\b|\bdefine\b|what\s+(?:is|does)\b", re.I
)
_ALL_RE = re.compile(r"모두|전부|빠짐없이|\ball\b", re.I)

AGGREGATE_RE = re.compile("|".join(p.pattern for p in (COUNT_RE, SUM_RE, MAXMIN_RE, _AVG_RE)), re.I)
LIST_TYPE_RE = re.compile("|".join(p.pattern for p in (LIST_RE, _ALL_RE)), re.I)

# 유형별 첫 도구·검색 설정 — 순서 = 우선순위(하나만 고름).
TYPE_TABLE = [
    ("aggregate", AGGREGATE_RE, {"first_tool": "aggregate", "search": {}}),
    ("latest", RE_LATEST_QUESTION, {"first_tool": "search", "search": {"recency": "2"}}),
    # 그림 설명은 이미 일반 청크로 색인돼 기본 검색이 찾음 — methods를 좁히지 않는다
    ("figure", _FIGURE_RE, {"first_tool": "search", "search": {}}),
    ("list", LIST_TYPE_RE, {"first_tool": "search", "search": {}}),
    ("compare", _COMPARE_RE, {"first_tool": "search", "search": {}}),
    ("trend", _TREND_RE, {"first_tool": "search", "search": {}}),
    ("term", _TERM_RE, {"first_tool": "lookup_term", "search": {}}),
]
DEFAULT_TYPE, DEFAULT_CONFIG = "general", {"first_tool": "search", "search": {}}


def classify(question):
    """질문 글자만 보고 유형 하나 + {"first_tool", "search"}(호출자가 복사해 씀 — TYPE_TABLE 항목을 직접 안 건드림)."""
    q = question or ""
    for qtype, rx, cfg in TYPE_TABLE:
        if rx.search(q):
            return qtype, copy.deepcopy(cfg)
    return DEFAULT_TYPE, copy.deepcopy(DEFAULT_CONFIG)
