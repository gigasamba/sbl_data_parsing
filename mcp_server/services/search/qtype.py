"""질문 유형 라우터(AD1 1단계, AG2 Q1 계획자) — 규칙만(LLM 0회), 질문 글자만 보고 유형 하나 + 요건별 첫 도구·검색
설정을 고른다. 흩어져 있던 판별 조각을 재사용(새로 안 만듦): aggregate.py의 COUNT_RE·SUM_RE·MAXMIN_RE(건수·합계·
최대/최소) · LIST_RE(목록) · common/docmeta.py의 RE_LATEST_QUESTION(최신·현재·최근). 그림·비교·추이·용어는 이
코드베이스에 아직 단서가 없어 새로 둔다(TYPE_TABLE 한 곳).

TYPE_TABLE은 **우선순위 목록**(위가 더 구체적 — 하나만 고름, 첫 매치가 이김). 예: "몇 개인가"(count)와
"흐름도"(figure)가 같은 질문에 있으면 figure가 더 구체적(그림을 읽어야 답이 나옴)이라 위에 둔다.
ponytail: 정규식 하나로 유형을 가르는 1단계 규칙 — 겹치는 단서(최근 N년 추이를 "최신"으로, 총액이 들어간 비교
질문을 "집계"로 오분류하는 경우가 있음, 알려진 한계. resources/vocab/qtype_labels.json 혼동 행렬 참조)는 AD1 2단계
(작은 LLM, 확신 낮으면 하이브리드)가 나중에 보완한다.

AR4③ — aggregate.detect()도 따로 "집계 질문인가"를 본다(그 쪽이 실제로 집계 엔진을 돌릴지 정하는 권위 있는
결정). classify()의 AGGREGATE_RE가 그 단서 정규식(COUNT_RE·SUM_RE·MAXMIN_RE)을 그대로 쓰므로(위 문단) 단서는
합쳐져 있다 — 그래도 classify() 자체를 detect()로 바꾸지 않는 이유: classify()는 clients·contracts 없이
질문 글자만으로 값싼 라벨 하나를 매기고(호출자가 매 요청 클라이언트 명부 없이도 부를 수 있어야 함), detect()는
clients·contracts를 받아 단일 계약 속성 조회 제외·존재/진행 여부 질문 제외 같은 추가 규칙까지 본다(detect()
docstring 참고). 그래서 두 결과가 같은 질문에서 어긋날 수 있다(의도된 차이) — 집계 경로를 실제로 탈지는
항상 detect()만 본다.

호출자: modules/search/local.py weights()(G14 — bm25 가중 조정) · modules/search/rerank.py
(비교·최신 유형이면 재순위 게이트). 옛 호출자 research.py(RESEARCH_PLANNER=typed)·do_search의 notes 표시는 S5a·S5(10-26, D-025)에 지움.
정확도 점검: tests/server/mcp/test_qtype.py(resources/vocab/qtype_labels.json)
"""

import copy
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import json  # noqa: E402

from common.core.docmeta import RE_LATEST_QUESTION  # noqa: E402 — 최신판 질문 단서(L3-1과 같은 규칙)
from common.core.paths import RES_ROOT  # noqa: E402
from mcp_server import config as mc  # noqa: E402 — 설정 객체(mcp 칸)

# 집계·목록 단서(mc-04 10-31 — 집계 답 aggregate.py를 지우며 이 판별에 쓰던 정규식만 이리로, 글자 그대로)
_AGG_VOCAB_DEFAULT = {  # DT1 c1 — 지표 판별 단서어(CDMO 예제: 건수·합계·수량·금액·단가·배치) 코드 기본값
    "count": ["건수", r"몇\s*건", "개수", r"몇\s*개(?!월)", r"how\s+many", r"number\s+of", r"\bcount\b"],
    # ↑ "몇\s*개(?!월)" — RV-singlelookup: "계약 기간은 몇 개월"(몇 개월 = how many months, 집계 아님)이 "몇 개"
    #   부분 문자열로 걸려 건수 질문으로 오판되던 것(뒤에 "월"이 오면 안 걸리게, DT1 c1 커스텀 vocab에도 같게 적용)
    "sum": ["합계", "합", "총", "전체", r"모두\s*더", "total", "sum"],
    "qty": ["수량", "용량", "qty", "quantity", "capacity", "volume"],
    "amount": ["금액", "규모", r"contract\s*value", r"\bvalue\b", "amount"],
    "unit_price": ["단가", r"unit\s*price"],
    "batch": ["배치", "batch"],
}


def _load_agg_vocab():
    """단서어 사전 — `resources/vocab/agg_vocab.json`(기본) 또는 설정 `search.agg_vocab_file`. 파일 없음·깨짐·빈 목록이면 그 키는 코드 기본값."""
    default = dict(_AGG_VOCAB_DEFAULT)
    p = Path(mc.cfg().search.agg_vocab_file or (RES_ROOT / "vocab" / "agg_vocab.json"))
    if not p.exists():
        return default
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    out = dict(default)
    for k, v in (data or {}).items():
        if k in default and isinstance(v, list) and v:
            out[k] = v
    return out


_AGG_VOCAB = _load_agg_vocab()
COUNT_RE = re.compile("|".join(_AGG_VOCAB["count"]), re.I)
SUM_RE = re.compile("|".join(_AGG_VOCAB["sum"]), re.I)
LIST_RE = re.compile(r"각\s*계약|계약별|계약마다|of\s+each|each\s+contract|목록|\blist\b", re.I)
MAXMIN_RE = re.compile(r"가장\s*(많은|적은|큰|작은)|최대|최소|\bmax\b|\bmin\b|\bmost\b|\bleast\b", re.I)

_AVG_RE = re.compile(r"평균|average|\bavg\b", re.I)  # AD1 aggregate(평균)은 기존 조각에 없어 새로 둠
_FIGURE_RE = re.compile(r"그림|그래프|도식|차트|흐름도|순서도|막대|flowchart|diagram|\bgraph\b|\bchart\b|\bfigure\b", re.I)
_COMPARE_RE = re.compile(r"비교|차이|대비|더\s*(?:큰|작은|많은|적은|높은|낮은)|\bcompare\b|\bdifference\b|\bvs\.?\b", re.I)
_TREND_RE = re.compile(r"추이|추세|연도별|연도\s*별|변화\s*추이|\btrend\b|year[- ]over[- ]year|\byoy\b", re.I)
_TERM_RE = re.compile(
    r"\b뜻\b|의미|정의\s*(?:가|는|를)?|무엇을\s*의미|란\s*(?:무엇|뜻)|\bdefinition\b|\bdefine\b|what\s+(?:is|does)\b", re.I
)
_ALL_RE = re.compile(r"모두|전부|빠짐없이|\ball\b", re.I)

AGGREGATE_RE = re.compile("|".join(p.pattern for p in (COUNT_RE, SUM_RE, MAXMIN_RE, _AVG_RE)), re.I)
LIST_TYPE_RE = re.compile("|".join(p.pattern for p in (LIST_RE, _ALL_RE)), re.I)

# 유형별 첫 도구·검색 설정(코드 상수 1곳, AG2) — 순서 = 우선순위(하나만 고름).
# search 설정(methods·recency)은 옛 research.py가 검색에 건네던 값(S5a에 지움 — 표는 rerank 게이트·selftest가 씀).
TYPE_TABLE = [
    ("aggregate", AGGREGATE_RE, {"first_tool": "aggregate", "search": {}}),
    ("latest", RE_LATEST_QUESTION, {"first_tool": "search", "search": {"recency": "2"}}),
    # ponytail: 그림 설명은 이미 일반 청크로 색인돼 기본 검색이 찾음 — image 결과는 do_search의 images 칸에만 담겨 research가 안 읽고
    # methods를 좁히면 id·graph를 잃음(독립 검토 10-06). 그림 근거 우선(가중)은 그림 청크 boost가 생길 때(BL3·AD11)
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
