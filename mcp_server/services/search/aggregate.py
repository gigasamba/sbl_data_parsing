"""건수·합계·표 집계(검색 모듈) 질문 → 검색 대신 집계(SQL 데이터 + 규칙) — 근거 문서가 많아 상위 k 검색으로 다 못 가져오는 질문용. LLM 없음.

대상 데이터(bundle이 만듦 — 로컬 docs.jsonl·facts.jsonl만. pgvector 집계 pg()는 10-30에 지움 — doc_fact를 적재하지 않음,
숫자 질문은 query_edw로 — docs/prd/mcp.md#mc-12):
  문서 메타   client · contract_no · contract{product_code, modality, signed_on, unit_price, amount, currency, batches}
  표 사실     facts.jsonl(수량·용량 열 값)
  계약 기록   = 같은 계약 번호의 문서들을 합친 것(라벨로 뽑은 값·교차 확인 메타 우선)

질문 판별(규칙):
  지표   건수(건수·몇 건·how many·count) · 계약 금액(금액·규모·value) · 배치 수(배치·batch) · 표 수량(수량·용량 + 합계 — 예전 경로)
  범위   고객(이름·stack.json client_aliases 별칭) · 계약 번호 · 기간(최근/과거/지난 N년·N개월 · YYYY년 · 'YYYY-MM-DD ~ YYYY-MM-DD'
         · '전체 이력/not limited'는 제한 없음) · 모달리티(ADC·mAb·bispecific·vaccine)
  모양   값 하나 · 제품 종류별 표 · 고객별 표(통화별) · 계약별 목록(+합계) · 'N년 이상 전' 제외 구간 표
기준일 = AGG_TODAY(YYYY-MM-DD, 없으면 오늘). 금액은 통화를 섞어 더하지 않음.
결과: {"kind", "target", "answer", "unit", "evidence": [{file_path, contract_no, page, line, items, confirmed,
      client, amount, currency, batches(BR40 — table_text() 계약별 근거 행용, _apply()의 recs에 이미 있던 값)}], "note"}
      표면 + {"columns", "rows", "totals"} (answer = 사람이 읽는 한 줄 요약)

로컬 정형 저장소(X1, STRUCT_DB)가 있으면 '계약 ID 없이 연결된 문서' 같은 질문은 doc_link_list가 SQL로 답한다(doc_link_question으로 판별) —
저장소가 없으면 이 경로는 쓰이지 않고 위 집계가 그대로 동작(common/structdb.py만 공용, modules/load는 import 안 함).

struct_context(question, hits)(L3-6, W18)는 같은 저장소에서 (a) 검색된 문서에 연결된 계약 · (b) 질문에 적힌 계약ID·고객 별칭이 가리키는 계약 ·
(c) 집계(합계·건수·최댓값 등) 질문이면 계약 마스터 전체(상한 STRUCT_CONTEXT_MAX)를 표로 돌려줌 — LLM이 답을 계산하게 근거만 준다(SQL 계산 안 함).
(10-13 답변 경로 통일 2단계 — struct()·struct_context()·기존 집계를 한 목록으로 묶어 답변 프롬프트에 넘기던 answer_aggs()는
archive됨(그 호출부였던 cli/pipeline.py ask --llm·evaluation/stack_matrix.py _answer_eval LLM 분기가 archive — 답변은
서빙되는 Answer Agent rag_qa만, 중복 경로 제거). struct()·struct_context()·local()은 그대로(검색 MCP aggregate 도구가 씀).

route(question, docs, facts_of, aliases) — detect() 정규식으로 집계 질문을 가려 _apply()로 기존 집계 틀을 돈다(못 걸리면 None →
호출자가 검색으로 폴백). LLM 경계 분류(R1, SEARCH_AGG_LLM)는 op-08에 지움. local()이 이 경유를 씀.
"""

import datetime as dt
import json
import re
from pathlib import Path

from common.config import settings as C  # 설정 객체(common 칸 — STRUCT_BACKEND·STRUCT_DB, S7d)
from common.core.paths import RES_ROOT  # 폴더 재편 뒤 이 상수만 바뀌면 됨
from common.core.terms import (  # 고객·어휘 규칙(구조화와 같게, DT1 c1: 용어집 modality_code 우선)
    ID_LIKE,
    _aliases,
    match_clients,
    modalities,
    norm,
)
from common.store import structdb as SDB  # 로컬 정형 저장소 연결(X1, modules/load는 import 안 함 — 연결만 common 공용)
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)
from mcp_server.services.search import (
    clientscope as CS,  # BR50(D) 고객 범위 단일 규칙(local.py·pgsearch.py·retriever.py·mcp_server.py와 공용)
)
from mcp_server.services.search import supersede as SS  # AR4② 대체판 판정 단일 규칙
from mcp_server.services.search.structdb import find_table_row  # 10-14 함수별 분리로 이전

NOID_RE = re.compile(r"계약\s*(id|아이디|번호)(?=[^.?!]{0,20}(없|안\s|않))|no\s+contract\s+id", re.I)
# ↑ '계약 ID가 없는' 뿐 아니라 '계약 ID가 적혀 있지 않은'·'계약 번호를 안 적은'처럼 부정어가 뒤에 떨어져 나오는 표현도 잡음(AD45③, 창 20자) — 그 안에 '없/안 /않'이 없으면 안 걸림(오탐 방지)
LINKED_RE = re.compile(r"연결|이어진|매칭|link", re.I)


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
    """집계 지표 단서어(DT1 c1) — `resources/vocab/agg_vocab.json`(기본, git — S2) 또는 env `AGG_VOCAB_FILE`(서버 다른 경로,
    sources.py `sources_path()`와 같은 관례)에서 읽는다. 파일 없음·JSON 깨짐·키 없음·빈 목록이면 그 키는 코드 기본값
    (_AGG_VOCAB_DEFAULT, CDMO 예제)과 바이트 동일한 정규식 — 그 회사 업종에 '배치' 개념이 없으면(예: 'batches' 대신
    'shipments') 데이터 파일에 그 키만 바꿔 넣으면 됨."""
    default = dict(_AGG_VOCAB_DEFAULT)
    p = Path(mc.cfg().search.agg_vocab_file or (RES_ROOT / "vocab" / "agg_vocab.json"))  # S7d — 설정 객체
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

QTY_RE = re.compile("|".join(_AGG_VOCAB["qty"]), re.I)

AMOUNT_Q = re.compile("|".join(_AGG_VOCAB["amount"]), re.I)

UNITPRICE_Q = re.compile("|".join(_AGG_VOCAB["unit_price"]), re.I)
COMPARE_WORD_RE = re.compile(
    r"비교|대비|\bvs\b|중\s*(어느|어디|누가|무엇|더)|어느|어디|더\s*(높|낮)|차이|highest|lowest|higher|lower|\bcompare\b", re.I
)
AGG_SCOPE_CUE_RE = re.compile(
    r"합계|총|전체|모두|각|건수|몇\s*건|평균|비교|\btotal\b|\bsum\b|\ball\b|\beach\b|how\s+many\s+contracts", re.I
)
# ↑ RV-singlelookup(2026-10-11) — detect() 단일 계약 제외 게이트 전용 단서어(AGG_CUE_RE·AGG_VOCAB의 "숫자·몇·얼마·count" 같은
#   넓은 단서와 다름 — "~는 얼마야?" 같은 흔한 단일 값 질문 표현까지 걸리면 안 돼서 좁게: 집계(여러 계약 합·건수·비교)를
#   명시하는 단어만).
FIND_DOC_RE = re.compile(r"(문서|메일|이메일)[^.?!]{0,15}(찾아|찾기|보여\s*줘)|\b(find|show)\b[^.?!]{0,20}\b(document|mail|email)\b", re.I)
EXISTENCE_RE = re.compile(
    r"정해지지\s*않|있나요|있습니까|끝났나요|끝났습니까|진행\s*(중인가요|되었나요|되고\s*있나요)|여부(가|는)?\s*(있|궁금)", re.I
)
# ↑ R1 보강(AD42·AD45④) — '고객 2곳 비교'(예 'A와 B 중 단가 높은') **명시적 비교어**가 있을 때만 금액 질문으로 인정
#   (detect()에서 len(cls)>=2 조건과 함께). 원칙(재검 MAJOR, 10-07) — **애매하면 검색**(집계로 가로채지 않음, 검색은
#   근거를 그대로 돌려줘 놓쳐도 덜 해로움): (a) '중' 단독은 비교로 안 침 — 'A와 B 중 (어느|어디|누가|무엇|더)'처럼
#   선택 의문이 바로 붙을 때만(그냥 '…중 단가가…' 같은 문장은 비교어 아님) (b) 명시 비교어가 있으면 검색 의도어보다
#   우선이지만, '…한 문서/메일을 찾아·보여줘'(찾을 대상이 문서·메일 자체, FIND_DOC_RE)면 그래도 검색(예 '단가 비교한
#   문서를 찾아줘') (c) '정해지지 않은·있나요·끝났나요' 같은 존재·진행 여부 질문(EXISTENCE_RE)은 집계 아님(예
#   '단가가 아직 정해지지 않은 계약이 있나요?' → None). 단일 계약 단가 질문(예 '메일 제안 단가 vs 계약 단가 중
#   유효한 것은?', synth-4clients cross_document)은 len(cls)<2라 애초에 안 걸림(오탐 방지, 실측 확인).

BATCH_Q = re.compile("|".join(_AGG_VOCAB["batch"]), re.I)

GROUP_MOD = re.compile(
    r"(제품\s*)?종류별|모달리티별|by\s+(product\s+)?modality|per\s+(product\s+)?modality|each\s+modality|제품\s*종류", re.I
)

GROUP_CLIENT = re.compile(r"고객별|각각|each\s+(client|customer)|per\s+(client|customer)|by\s+client", re.I)

PRODUCT_COUNT = re.compile(r"제품\s*수|생산\s*(중인\s*)?제품|how\s+many\s+products|number\s+of\s+products", re.I)

LIST_RE = re.compile(r"각\s*계약|계약별|계약마다|of\s+each|each\s+contract|목록|\blist\b", re.I)

EXCL_RE = re.compile(r"more\s+than\s+(\d+)\s+years?\s+ago|(\d+)\s*년\s*이상\s*(전|이전)", re.I)

NO_WINDOW = re.compile(r"not\s+limited|전체\s*(계약\s*)?(이력|기간)|all\s+of\s+.*contracts\s+on\s+file|across\s+all|모든\s*계약", re.I)

RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:~|–|to)\s*(\d{4}-\d{2}-\d{2})")

YEARS_RE = re.compile(r"(?:과거|최근|지난)\s*(\d+)\s*년|(?:past|last)\s+(\d+)\s+years?", re.I)

MONTHS_RE = re.compile(r"(?:과거|최근|지난)\s*(\d+)\s*개월|(?:past|last)\s+(\d+)\s+months?", re.I)

YEAR_RE = re.compile(r"(20\d{2})\s*년(?!\s*이상)|\bin\s+(20\d{2})\b", re.I)

SINCE_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*(?:이후|부터)|since\s+(\d{4}-\d{2}-\d{2})", re.I
)  # R1 보강(AD42·AD45④) — '조건부 집계'(예 '2024년 이후')는 열린 구간(끝=오늘)
SINCE_YEAR_RE = re.compile(
    r"(20\d{2})\s*년\s*(?:이후|부터)|since\s+(20\d{2})\b", re.I
)  # YEAR_RE(그 해 1~12월만)보다 먼저 봐야 함 — window()에서 순서 고정

MAXMIN_RE = re.compile(
    r"가장\s*(많은|적은|큰|작은)|최대|최소|\bmax\b|\bmin\b|\bmost\b|\bleast\b", re.I
)  # struct_context (c) 집계 질문 판별용

CONTRACT_WORD_RE = re.compile(r"계약|contract", re.I)

STRUCT_CONTEXT_MAX = mc.cfg().search.struct_context_max  # struct_context (c)에서 계약 마스터 전체를 넘길 때 상한


def _jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(p).exists() else []


def _today():
    v = mc.cfg().search.agg_today  # S7d — 설정 객체
    return dt.date.fromisoformat(v) if v else dt.date.today()


def _shift(d, years=0, months=0):
    y, m = divmod(d.year * 12 + d.month - 1 - years * 12 - months, 12)
    import calendar

    return dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def window(question):
    """→ (시작, 끝) ISO 또는 None(제한 없음)."""
    if NO_WINDOW.search(question):
        return None
    m = RANGE_RE.search(question)
    if m:
        return m.group(1), m.group(2)
    t = _today()
    m = YEARS_RE.search(question)
    if m:
        return (_shift(t, years=int(m.group(1) or m.group(2))) + dt.timedelta(days=1)).isoformat(), t.isoformat()
    m = MONTHS_RE.search(question)
    if m:
        return (_shift(t, months=int(m.group(1) or m.group(2))) + dt.timedelta(days=1)).isoformat(), t.isoformat()
    m = SINCE_DATE_RE.search(question)
    if m:
        return (m.group(1) or m.group(2)), t.isoformat()
    m = SINCE_YEAR_RE.search(question)
    if m:
        return f"{m.group(1) or m.group(2)}-01-01", t.isoformat()
    m = YEAR_RE.search(question)
    if m:
        y = m.group(1) or m.group(2)
        return f"{y}-01-01", f"{y}-12-31"
    return None


def detect(question, clients, contracts, aliases=None):
    """→ 계획 dict 또는 None. 예전 호출자 호환: plan['kind'] in (count, sum)·plan['target'].

    AR4③ — modules/search/qtype.classify()의 AGGREGATE_RE도 "집계 질문인가"를 본다. 둘은 **단서(cue) 정규식은
    공유**한다(qtype.py가 이 파일의 COUNT_RE·SUM_RE·MAXMIN_RE를 그대로 import해 AGGREGATE_RE를 만듦 — 새 단서
    집합을 따로 안 둠). 그래도 합치지 않는 이유: qtype.classify는 질문 글자만 보고 유형 하나를 고르는 값싼
    1차 라우터(검색 가중치·첫 도구 결정용, 호출자 local.py·rerank.py·research.py)이고, clients·contracts를
    못 받는다. detect()는 그 위에서 실제로 집계 엔진을 돌릴지 정하는 **권위 있는 결정**이라 clients·contracts
    인자로 고객/계약 특정 여부를 봐야 하고, 그 특정 여부에 따라 결과가 갈리는 추가 규칙(단일 계약 속성 조회
    제외 RV-singlelookup·존재/진행 여부 질문 제외 EXISTENCE_RE·문서 찾기 의도 제외 FIND_DOC_RE·고객 2곳
    비교 단가 UNITPRICE_Q 등)이 있다 — qtype 단계에는 clients·contracts가 없어 이 규칙들을 적용할 수 없다.
    그래서 qtype.classify의 "aggregate" 라벨과 detect()의 None/plan 판정이 같은 질문에서 어긋날 수 있다(의도된
    차이, 버그 아님) — 실제로 집계 결과를 근거로 쓸지는 항상 detect()(mcp_server.do_search의 agg_hit)만 본다."""
    if PRODUCT_COUNT.search(question) and not re.search(r"계약|contract", question, re.I):
        return None  # '생산 제품 수'는 보도자료 문장 — 계약 집계가 아니라 검색 질문
    cls = match_clients(question, clients, aliases)
    contract = next(
        (c for c in contracts if c and ID_LIKE.fullmatch(c) and norm(c) in norm(question)), None
    )  # ID 모양만('3'이 '과거 3년'에 걸리지 않게)
    if len(cls) <= 1 and not AGG_SCOPE_CUE_RE.search(question) and (BATCH_Q.search(question) or UNITPRICE_Q.search(question)):
        return None
    # ↑ RV-singlelookup(2026-10-11, OpenRouter run2 묶음D) — 계약 하나(고객 1곳 이하)의 배치·단가 같은 속성값 조회
    #   (예 "화이자 공급 계약의 배치당 단가는 얼마야?"·"배치 수는?"·"batch count in ... agreement")는 집계 신호
    #   (합계·총·건수·몇 건·평균·비교 등, AGG_SCOPE_CUE_RE) 없이는 계약 여러 건의 합·건수와 구분이 안 됨 — 검색으로
    #   폴백(집계는 "여러 계약을 더하거나 센다"는 전제라 1건짜리 속성에는 안 맞음, misfire 측정 round3 참고).
    want_amount, want_batch = bool(AMOUNT_Q.search(question)), bool(BATCH_Q.search(question))
    want_count = bool(COUNT_RE.search(question))
    want_unitprice = (
        len(cls) >= 2
        and bool(UNITPRICE_Q.search(question))
        and bool(COMPARE_WORD_RE.search(question))
        and not FIND_DOC_RE.search(question)
        and not EXISTENCE_RE.search(question)
    )
    # R1 보강(AD45④) — '고객 2곳 비교'(단가, 예 'A와 B 중 단가 높은') — 계약별 단가가 보여야 비교되므로 고객별 합계(group)가
    # 아니라 계약별 목록(listing)으로 보냄. 단일 계약 단가 질문과 구분은 UNITPRICE_Q 주석 참고.
    want_amount = want_amount or want_unitprice
    if SUM_RE.search(question) and QTY_RE.search(question) and not (want_amount or want_batch) and (contract or cls):
        return {"kind": "sum", "target": {"contract": contract} if contract else {"client": cls[0]}}  # 표 수량 합계(예전 경로)
    if not (cls or contract) or not (want_count or want_amount or want_batch):
        return None
    mods = [v for k, v in modalities().items() if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", question, re.I)]
    ex = EXCL_RE.search(question)
    p = {
        "clients": cls,
        "contract": contract,
        "window": window(question),
        "modalities": sorted(set(mods)),
        "count": want_count,
        "amount": want_amount,
        "batches": want_batch,
        "exclude_years": int(ex.group(1) or ex.group(2)) if ex else None,
        "group": (
            "modality"
            if (GROUP_MOD.search(question) or len(set(mods)) >= 2)
            else "client"
            if (len(cls) >= 2 and not want_unitprice)
            else None
        ),
        "listing": bool(LIST_RE.search(question))
        or want_unitprice
        or (want_count and want_amount and not GROUP_MOD.search(question) and len(cls) < 2),
    }  # 건수 + 금액(또는 단가 비교) → 계약별 목록 + 합계
    p["kind"] = (
        "buckets"
        if p["exclude_years"]
        else "table"
        if (p["group"] or p["listing"])
        else "amount"
        if want_amount and not want_count
        else "batches"
        if want_batch and not (want_count or want_amount)
        else "count"
    )
    p["target"] = {"contract": contract} if contract else ({"client": cls[0]} if len(cls) == 1 else {"clients": cls})
    return p


def records(docs):
    """같은 계약 번호의 문서들 → 계약 기록 1개(라벨 값·교차 확인 메타 문서 먼저 채움)."""
    by = {}
    for d in docs:
        if d.get("contract_no"):
            by.setdefault(norm(d["contract_no"]), []).append(d)
    out = []
    for ds in by.values():
        ds.sort(
            key=lambda d: (
                not (d.get("contract") or {}).get("amount"),
                (d.get("contract") or {}).get("values_from") != "label",
                not d.get("meta_confirmed"),
                d.get("file_path") or "",
            )
        )
        r = {"contract_no": ds[0]["contract_no"], "docs": ds}
        for d in ds:
            if d.get("client"):
                r.setdefault("client", d["client"])
            for k, v in (d.get("contract") or {}).items():
                r.setdefault(k, v)
        out.append(r)
    return out


def _fmt(v, cur=""):
    v = round(v, 3)
    s = f"{int(v):,}" if float(v).is_integer() else f"{v:,}"
    return f"{s} {cur}".strip()


def _sum_money(rs):
    tot = {}
    for r in rs:
        if r.get("amount") is not None:
            tot[r.get("currency") or ""] = tot.get(r.get("currency") or "", 0) + r["amount"]
    return " + ".join(_fmt(v, c) for c, v in sorted(tot.items())) or "—"


def _ev(rs, facts_of=None):
    ev = []
    for r in rs:
        d = r["docs"][0]
        fs = facts_of(d) if facts_of else []
        ev.append(
            {
                "file_path": d["file_path"],
                "contract_no": r["contract_no"],
                "page": fs[0].get("page") if fs else None,
                "line": fs[0].get("line") if fs else None,
                "items": len(fs),
                "confirmed": d.get("meta_confirmed"),
                "client": r.get("client"),
                "amount": r.get("amount"),
                "currency": r.get("currency"),
                "batches": r.get("batches"),
            }
        )  # BR40 — table_text()가 고객·금액·배치 수를 계약별 근거 행으로 쓸 수 있게(이미 recs에 있던 값, 새 조회 없음)
    return ev


AGG_TEXT_MAX_ROWS = mc.cfg().search.agg.text_max_rows  # RV-aggtext — do_search 근거 text에 붙는 표 행 상한(LLM 컨텍스트 비용)
AGG_TEXT_MAX_SRC_ROWS = mc.cfg().search.agg.text_max_src_rows  # BR40 — 계약별 근거 행 상한(위와 별도, 표 자체보다 계약 수가 많을 수 있어서)


def table_text(g, max_rows=None):
    """집계 결과 dict(columns/rows/totals/evidence)를 do_search 근거 text에 붙일 압축 표 글자로(사람·LLM 둘 다 읽게 "값 | 값" 한 줄씩).
    RV-aggtext(2026-10-11) — 집계 질문(고객별·제품 종류별 표)에서 text에 합계 한 줄만 들어가 답변 모델이 표를 못 보던 결함.
    rows 없으면 표 블록은 건너뜀. max_rows(기본 SEARCH_AGG_TEXT_MAX_ROWS=30) 넘으면 잘라내고 '외 N행'.

    BR40 — 비교·집계 질문(예 '고객 A와 B 중 계약 금액 합계가 큰 곳은?')은 group(고객별·제품 종류별) 합계 행만 보여서
    계약 하나하나의 금액(evidence_keywords가 요구하는 값)이 text에 없었다 — evidence(_ev(), 금액·고객·배치 수가 이미
    담겨 있음)로 "계약별 근거" 행 목록을 덧붙인다(상한 AGG_TEXT_MAX_SRC_ROWS=40, 넘으면 '외 N건', contract_no로 정렬
    — 결정적). 이미 계약별 목록 표(columns[0]=="계약ID")면 같은 값이 보이므로 중복으로 안 붙임. amount·batches·client가
    전혀 없는 evidence(doc_location_list·doc_link_list·table_cell_list — _ev()를 안 거침)는 전처럼 '출처: …' 한 줄만."""
    ev = g.get("evidence")
    has_table = bool(g.get("columns") and g.get("rows"))
    if not has_table and not ev:
        return ""
    lines = []
    already_percontract = False
    if has_table:
        n = AGG_TEXT_MAX_ROWS if max_rows is None else max_rows
        rows = g["rows"]
        lines.append(" | ".join(str(c) for c in g["columns"]))
        lines += [" | ".join("—" if c is None else str(c) for c in r) for r in rows[:n]]
        if len(rows) > n:
            lines.append(f"외 {len(rows) - n}행")
        if g.get("totals"):
            lines.append("합계: " + " · ".join(f"{k} {v}" for k, v in g["totals"].items()))
        already_percontract = g["columns"][0] == "계약ID"
    if ev and not already_percontract:
        src = [e for e in ev if e.get("amount") is not None or e.get("batches") is not None or e.get("client")]
        if src:
            src.sort(key=lambda e: e.get("contract_no") or "")
            lines.append("계약별 근거:")
            for e in src[:AGG_TEXT_MAX_SRC_ROWS]:
                amt = (
                    _fmt(e["amount"], e.get("currency") or "")
                    if e.get("amount") is not None
                    else (f"{_fmt(e['batches'])}배치" if e.get("batches") is not None else "—")
                )
                fname = Path(e["file_path"]).name if e.get("file_path") else "—"
                lines.append(f"{e.get('contract_no') or '—'} | {e.get('client') or '—'} | {amt} | {fname}")
            if len(src) > AGG_TEXT_MAX_SRC_ROWS:
                lines.append(f"외 {len(src) - AGG_TEXT_MAX_SRC_ROWS}건")
        else:
            docs = ", ".join(f"{e['contract_no']}({Path(e['file_path']).name})" for e in ev[:20] if e.get("file_path"))
            if docs:
                lines.append("출처: " + docs + (f" 외 {len(ev) - 20}건" if len(ev) > 20 else ""))
    return "\n".join(lines)


FX_QUERY = "환율 exchange rate USD KRW"  # BR43 — 통화 섞인 비교·집계에 붙일 환율 근거의 고정 질의(mcp_server.do_search가 bm25+id로 이 질의 1건만 추가 검색)
_FX_RATE_RE = re.compile(r"\d[\d,]*\s*(?:usd|krw|달러|원)\s*=\s*\d[\d,]*\s*(?:usd|krw|달러|원)", re.I)
_FX_WORD_RE = re.compile(r"환율|exchange\s*rate", re.I)


def mixed_currencies(g):
    """BR43 — 집계 결과(g["evidence"]의 계약별 통화, _ev()가 이미 담아 둠)에 통화가 2개 이상 섞여 있으면 그 집합을
    (아니면 빈 집합 — 단일 통화·통화 정보 없는 집계는 영향 없음). do_search가 환율 근거 추가 검색을 할지 고르는 신호."""
    cs = {e.get("currency") for e in (g.get("evidence") or []) if e.get("currency")}
    return cs if len(cs) >= 2 else set()


def fx_evidence_text(top_hit):
    """BR43 — top_hit(FX_QUERY 검색 1위 근거, {"file_name", "text"})가 진짜 환율 패턴('숫자 통화 = 숫자 통화' 또는
    '환율'/'exchange rate' + 숫자가 같은 글에 있음)을 담고 있을 때만 근거 줄 문자열을 돌려준다 — 아니면 None
    (아무것도 안 붙임, '환율'이라는 말만 있고 수치가 없는 글을 걸러낸다)."""
    text = (top_hit or {}).get("text") or ""
    if text and (_FX_RATE_RE.search(text) or (_FX_WORD_RE.search(text) and re.search(r"\d", text))):
        return f"환율 근거: {top_hit.get('file_name') or '—'}: {text.strip()[:300]}"
    return None


def run(question, docs, facts_of=None, aliases=None):
    """docs: [{file_path, client, contract_no, meta_confirmed, contract}] · facts_of(doc) → [{num, unit, page, line}] (표 수량 사실)."""
    p = detect(question, {d.get("client") for d in docs}, {d.get("contract_no") for d in docs}, aliases)
    if not p:
        return None
    return _apply(p, docs, facts_of)


def route(question, docs, facts_of=None, aliases=None):
    """detect() 정규식으로 집계 계획을 세워 _apply() — 못 걸리면 None(호출자가 검색으로 폴백)."""
    clients, contracts = {d.get("client") for d in docs}, {d.get("contract_no") for d in docs}
    p = detect(question, clients, contracts, aliases)
    return _apply(p, docs, facts_of) if p else None


def _apply(p, docs, facts_of=None):
    """detect()가 돌려준 plan dict p → 집계 결과(run()·route() 공용 엔진, 자유 SQL 없음)."""
    recs = records(docs)
    tgt = p["target"]
    if tgt.get("contract"):
        recs = [r for r in recs if norm(r["contract_no"]) == norm(tgt["contract"])]
    else:
        names = {norm(c) for c in ([tgt["client"]] if tgt.get("client") else tgt.get("clients", []))}
        recs = [r for r in recs if norm(r.get("client")) in names]
    if p["kind"] == "sum":  # 표 수량 합계(facts.jsonl)
        fs = [(r, f) for r in recs for f in (facts_of(r["docs"][0]) if facts_of else [])]
        total = sum(f["num"] for _, f in fs if f.get("num") is not None)
        unit = next((f["unit"] for _, f in fs if f.get("unit")), "")
        ev = _ev(recs, facts_of)
        return {
            "kind": "sum",
            "target": tgt,
            "answer": round(total, 3),
            "unit": unit,
            "evidence": ev,
            "note": f"수량 표 없는 계약 {sum(1 for e in ev if not e['items'])}건(0으로 셈)" if any(not e["items"] for e in ev) else "",
        }
    notes = []
    if p["window"] or p["modalities"] or p["group"] or p["listing"] or p["amount"] or p["batches"] or p["exclude_years"]:
        recs = [r for r in recs if r.get("amount") is not None or r.get("unit_price") is not None]  # 계약서 기록만(QBR·메일 인용 제외)
    if p["modalities"]:
        recs = [r for r in recs if r.get("modality") in p["modalities"]]
    if p["window"] and not p["exclude_years"]:
        lo, hi = p["window"]
        miss = [r for r in recs if not r.get("signed_on")]
        recs = [r for r in recs if r.get("signed_on") and lo <= r["signed_on"] <= hi]
        notes.append(f"기간 {lo}~{hi}" + (f" · 체결일 없는 계약 {len(miss)}건 제외" if miss else ""))
    recs.sort(key=lambda r: (r.get("signed_on") or "", r["contract_no"]))
    out = {"kind": p["kind"], "target": tgt, "evidence": _ev(recs, facts_of)}
    if p["kind"] == "count":
        out.update(answer=len(recs), unit="건")
    elif p["kind"] == "amount":
        out.update(answer=_sum_money(recs), unit="")
    elif p["kind"] == "batches":
        out.update(answer=_fmt(sum(r.get("batches") or 0 for r in recs)), unit="배치")
    elif p["kind"] == "buckets":
        cut = (_shift(_today(), years=p["exclude_years"]) + dt.timedelta(days=1)).isoformat()
        keep = [r for r in recs if (r.get("signed_on") or "") >= cut]
        out.update(
            columns=["구간", "계약 건수"],
            rows=[[f"최근 {p['exclude_years']}년 이내", len(keep)], [f"제외({cut} 이전 체결)", len(recs) - len(keep)]],
            totals={"전체 계약 건수": len(recs)},
            answer=f"남는 계약 {len(keep)}건 · 제외 {len(recs) - len(keep)}건",
            unit="",
        )
    else:
        metric_cols = (
            ["계약 건수"]
            + (["배치 수 합계"] if p["batches"] or not p["amount"] else [])
            + (["계약 금액 합계"] if p["amount"] or not p["batches"] else [])
        )
        if p["listing"] and not p["group"]:
            cols = ["계약ID", "제품", "제품 종류", "체결일", "배치 수", "단가", "계약 금액"]
            rows = [
                [
                    r["contract_no"],
                    r.get("product_code"),
                    r.get("modality"),
                    r.get("signed_on"),
                    None if r.get("batches") is None else _fmt(r["batches"]),
                    None if r.get("unit_price") is None else _fmt(r["unit_price"], r.get("currency")),
                    None if r.get("amount") is None else _fmt(r["amount"], r.get("currency")),
                ]
                for r in recs
            ]
        else:
            key = (
                (lambda r: r.get("modality") or "(미상)")
                if p["group"] == "modality"
                else (lambda r: (r.get("client") or "(미상)", r.get("currency") or ""))
            )
            groups = {}
            for r in recs:
                groups.setdefault(key(r), []).append(r)
            cols = (["제품 종류"] if p["group"] == "modality" else ["고객", "통화"]) + metric_cols
            rows = []
            for k, rs in sorted(groups.items(), key=lambda x: str(x[0])):
                row = [k] if p["group"] == "modality" else list(k)
                row.append(len(rs))
                if "배치 수 합계" in metric_cols:
                    row.append(_fmt(sum(r.get("batches") or 0 for r in rs)))
                if "계약 금액 합계" in metric_cols:
                    row.append(_sum_money(rs))
                rows.append(row)
        totals = {
            "계약 건수": len(recs),
            **({"배치 수 합계": _fmt(sum(r.get("batches") or 0 for r in recs))} if "배치 수 합계" in metric_cols or p["listing"] else {}),
            "계약 금액 합계": _sum_money(recs),
        }
        out.update(columns=cols, rows=rows, totals=totals, answer=f"계약 {len(recs)}건 · 금액 {totals['계약 금액 합계']}", unit="")
    missing = [r["contract_no"] for r in recs if p["amount"] and r.get("amount") is None]
    if missing:
        notes.append(f"계약 금액 못 읽은 계약 {len(missing)}건: {', '.join(missing[:5])}")
    if any(not r["docs"][0].get("meta_confirmed") for r in recs):
        notes.append(f"단일 엔진 메타 {sum(1 for r in recs if not r['docs'][0].get('meta_confirmed'))}건 포함")
    out["note"] = " · ".join(notes)
    return out


def local(bundle, question, hidden=None, client=None, client_strict=False):
    """로컬 묶음(docs.jsonl · facts.jsonl · chunks.jsonl)으로 집계.
    hidden(OP1, 독립 검토 BLOCK 반영) = 숨길 doc_key(file_sha256) 집합 — route()에 넘기기 전에 docs에서 뺌(건수·
    합계·표에서 공용 제외, None·빈 집합이면 전과 바이트 동일). facts의 "doc" 색인은 원래 docs.jsonl 순서 그대로라
    _i를 거르기 전에 매겨 둠(거른 뒤에도 by_doc 조회가 안 깨짐).
    client(BR50 D, 이미 계산된 허용 고객 집합 — mcp_server.do_aggregate가 clientscope.client_scope로 만듦) =
    주어지면 route() 전에 다른 고객 문서를 뺀다(clientscope.allows, client_strict로 미상 포함 여부) — detect()의
    clients 후보도 이 filtered docs에서만 뽑히므로 "다른 고객을 집계 대상으로 고르는" 것 자체가 막힌다.
    None(기본)이면 제한 없음 — 전과 바이트 동일."""
    B = Path(bundle)
    docs, facts, chunks = _jl(B / "docs.jsonl"), _jl(B / "facts.jsonl"), _jl(B / "chunks.jsonl")
    for i, d in enumerate(docs):
        d["_i"] = i
    if hidden:
        docs = [d for d in docs if d.get("file_sha256") not in hidden]
    if client:
        docs = [d for d in docs if CS.allows(CS.doc_clients(d.get("client"), d.get("clients")), client, client_strict)]
    by_doc = {}
    for f in facts:
        ch = chunks[f["chunk"]] if f.get("chunk") is not None else None
        by_doc.setdefault(f["doc"], []).append({**f, "page": ch and ch["page"], "line": ch and ch["line_start"]})
    return route(question, docs, lambda d: by_doc.get(d["_i"], []))


def doc_link_question(question):
    """'계약 ID 없는 RFI 중 계약으로 이어진 것' 같은 질문 — 로컬 정형 저장소 doc_contract_link로 답함(X1)."""
    return bool(NOID_RE.search(question) and LINKED_RE.search(question))


DOC_TYPE_PATTERNS = [  # AD45① — doc_location.doc_type 판별(문서 종류 단어, 길이순으로 먼저 걸리게 배열 순서 고정: RFI_ANSWER가 RFI보다 먼저)
    # \b 대신 (?<![A-Za-z])…(?![A-Za-z]) — 한글은 Python re에서 \w 취급이라 'RFP는'처럼 조사가 바로 붙으면 \b가 안 걸림
    (re.compile(r"rfi\s*(답변서|answer)", re.I), "RFI_ANSWER"),
    (re.compile(r"(?<![A-Za-z])rfi(?![A-Za-z])", re.I), "RFI"),
    (re.compile(r"(?<![A-Za-z])rfp(?![A-Za-z])", re.I), "RFP"),
    (re.compile(r"계약서|(?<![A-Za-z])contract(?![A-Za-z])", re.I), "CONTRACT"),
    (re.compile(r"견적서?|(?<![A-Za-z])quote(?![A-Za-z])", re.I), "QUOTE"),
    (re.compile(r"메일|이메일|(?<![A-Za-z])mail(?![A-Za-z])", re.I), "MAIL"),
    (re.compile(r"회의록|(?<![A-Za-z])minutes?(?![A-Za-z])", re.I), "MINUTES"),
]

DOC_LIST_HINT_RE = re.compile(r"목록|리스트|전부|모두|보여\s*줘|\blist\b|최근\s*판|최신\s*판|가장\s*최근|latest\s+version", re.I)


def doc_list_question(question):
    """'~ 문서 목록·전부·최근 판'·'~ 종류 문서 몇 건' — doc_location SQL로 답(AD45①, AD38 list_documents와 같은 원천).
    계약 집계(detect())와 달리 문서 종류 단어 또는 명시 계약ID가 걸려야 함(그냥 '계약 몇 건'은 detect() 쪽)."""
    if doc_link_question(question):
        return False
    has_doctype = any(p.search(question) for p, _ in DOC_TYPE_PATTERNS)
    has_contract_id = bool(ID_LIKE.search(question))
    if not (has_doctype or has_contract_id):
        return False
    return bool(DOC_LIST_HINT_RE.search(question) or (has_doctype and COUNT_RE.search(question)))


# engine-qa BLOCK②(AD23 leftover, 10-11) — ID_LIKE는 날짜(2024-01-15)·순수 숫자+하이픈(2026-05 등)도 잡는다
# (letter OR hyphen 조건이라 글자 없이 하이픈만 있어도 통과) — 표 칸 후보는 더 좁혀 글자+숫자가 둘 다 있는
# 토큰만(배치·로트·시료 번호 BT-0137·S-237·CL-03류). find_table_cells()가 이제 정확 일치라 날짜가 섞여도
# 실제로 틀린 답을 내진 않지만, 애초에 집계·search의 계약ID/날짜와 뒤섞여 DB를 불필요하게 치지 않게 1차 거름도 좁힌다.
_TABLE_CELL_TOKEN_RE = re.compile(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/.]{4,}")


def _table_cell_tokens(question):
    """순서 보존 중복 제거 — 날짜·순수 숫자+하이픈 토큰은 제외(위 _TABLE_CELL_TOKEN_RE)."""
    return list(dict.fromkeys(m.group() for m in _TABLE_CELL_TOKEN_RE.finditer(question)))


def _table_cell_scope_docs(db, question):
    """engine-qa BLOCK②(c) — 질문에 이미 적힌 계약ID·고객이 있으면 그 계약에 이어진 문서(doc_key)로만 표 칸
    검색을 좁힌다(다른 문서의 같은 토큰이 끼어들지 못하게) — struct_context()의 (a)(b) 판별과 같은 방식
    (contract_master·client_master·doc_contract_link, 이미 common 공용). contract_master가 없으면(표 DB만
    쓰고 EDW CSV는 안 올린 경우) None(범위 제한 없음 — 기존과 동일, 안전한 쪽으로 넓게 둠)."""
    try:
        contracts = db.query("SELECT contract_id, company FROM contract_master")
    except Exception:
        return None
    if not contracts:
        return None
    qn = norm(question)
    cids = {c["contract_id"] for c in contracts if c.get("contract_id") and norm(c["contract_id"]) in qn}
    if not cids:
        clients = {c["company"] for c in contracts if c.get("company")}
        hit = match_clients(question, clients, _struct_client_aliases(db))
        if hit:
            cids = {c["contract_id"] for c in contracts if c.get("company") in hit}
    if not cids:
        return None
    try:
        links = db.query("SELECT doc_key, contract_id FROM doc_contract_link")
    except Exception:
        links = []
    docs = {r["doc_key"] for r in links if r.get("contract_id") in cids}
    return docs or None


def table_cell_question(question):
    """AD23 leftover — 표 칸 질문(행 식별자 + 열 — '배치 BT-0137의 수량은?'류) 후보인가, 대략. 실제 판정은
    table_cell_list()가 find_table_cells()로 doc_cell에 그 토큰이 정확히 있는지 보고 내린다(여기선 _table_cell_tokens
    토큰이 하나라도 있는지만 — doc_list_question의 has_contract_id와 같은 넓은 1차 거름이지만 날짜·순수 숫자+
    하이픈은 미리 뺌, engine-qa BLOCK②(a)). BR16이 고친 집계 범위 규칙(AGG_SCOPE_CUE_RE)은 여기서 안 씀 — 그
    규칙은 detect()의 '계약 하나짜리 속성 조회는 집계 아님' 판별 전용, 표 칸 조회는 애초에 집계(여러 계약 합)가
    아니라 범위가 다름)."""
    return bool(_table_cell_tokens(question))


def table_cell_list(db, question, limit_per_token=10):
    """AD23 leftover — 질문 속 ID 모양 토큰(배치·로트·시료 번호 등, 날짜·순수 숫자+하이픈 제외)마다
    find_table_cells(SDB, 정확 일치)로 doc_cell을 찾아, 일치한 칸과 같은 행의 칸 전부(머리글 포함,
    find_table_row)를 근거로 돌려준다. engine-qa BLOCK②(c) — 질문에 계약ID·고객이 있으면 _table_cell_scope_docs가
    돌려준 문서만(다른 문서의 우연한 동일 토큰이 끼어들지 못하게). 범위를 모르는데(계약ID·고객이 질문에 없음)
    토큰이 문서 둘 이상에 정확히 걸치면 — 어느 쪽이 맞는지 알 수 없으므로 그 토큰은 통째로 버린다(엉뚱한 문서를
    답으로 섞어 내기보다 안전하게 빠짐). 토큰이 doc_cell 값과 정확히 같지 않으면(흔한 경우 — 계약ID·날짜 등
    표와 무관한 ID 모양) 조용히 빈 결과 → struct()가 None을 돌려 호출자가 기존 집계(_apply, detect())나
    검색으로 폴백(doc_link_list·doc_location_list와 같은 '없으면 빈 것' 관례 — 이쪽은 아예 None이라 집계 경로를
    덮어쓰지 않음, 기존 AGG_SCOPE_CUE_RE 범위 규칙과 무관)."""
    scope = _table_cell_scope_docs(db, question)
    seen_rows, rows_out, evidence = set(), [], []
    for tok in _table_cell_tokens(question):
        cells = SDB.find_table_cells(db, tok, limit=limit_per_token)
        if scope is not None:
            cells = [c for c in cells if c["doc_key"] in scope]
        elif len({c["doc_key"] for c in cells}) > 1:
            continue  # engine-qa BLOCK②(c) — 범위 모름 + 문서 둘 이상에 동일 토큰 → 동음이의 위험, 그 토큰 전체를 버림
        for c in cells:
            key = (c["table_key"], c["row_idx"])
            if key in seen_rows:
                continue
            seen_rows.add(key)
            row = find_table_row(db, c["table_key"], c["row_idx"])
            for rc in row:
                rows_out.append([c["doc_key"], c["table_id"], c["page"], rc["col_label"], rc["value"]])
            evidence.append(
                {
                    "file_path": c["doc_key"],
                    "contract_no": c["table_id"],
                    "page": c["page"],
                    "line": None,
                    "items": len(row),
                    "confirmed": True,
                }
            )
    if not rows_out:
        return None
    rows_out.sort(key=lambda r: (r[0], r[1], r[2] if r[2] is not None else -1, r[3] or ""))
    return {
        "kind": "table_cell",
        "target": {"filter": "표 칸 조회"},
        "answer": f"표 {len(evidence)}행 일치",
        "columns": ["문서", "표", "쪽", "열", "값"],
        "rows": rows_out,
        "evidence": evidence,
        "note": "표 칸 조회(doc_table·doc_cell, AD23)",
    }


def struct(question, hidden=None):
    """정형 저장소(X1/X1b) 질문이면 그 답, 아니면 None — 운영 ask·MCP aggregate·실험 답 평가가 모두 이 한 곳을 탐(10-05: ask·평가가 안 타서 synth-edw가 낮았음).
    옵트인 — STRUCT_BACKEND(pg 기본 포함)나 STRUCT_DB(sqlite 경로)를 명시했을 때만(기본 백엔드가 pg라 sqlite 파일 존재로는 판별 못 함).
    doc_link_question(계약 ID 없이 연결된 문서, X1) → doc_link_list(hidden 적용) · doc_list_question(문서 목록·건수, AD45①)
    → doc_location_list(hidden 미적용 — doc_location.doc_id는 file_sha256과 다른 namespace, 함수 docstring 참고) ·
    table_cell_question(표 칸 조회, AD23 leftover) → table_cell_list(doc_cell에 실제로 있는 토큰일 때만 답,
    없으면 None → 기존 집계(_apply)·검색으로 폴백 — 순서상 doc_link·doc_list 뒤, 집계(_apply)보다 앞)."""
    if not (C.given("STRUCT_BACKEND") or C.given("STRUCT_DB")):  # S7d — 준 값만(옛 있고 없음 판정)
        return None
    is_link, is_list = doc_link_question(question), doc_list_question(question)
    is_cell = not (is_link or is_list) and table_cell_question(question)
    if not (is_link or is_list or is_cell):
        return None
    try:
        db = SDB.open_backend(
            C.cfg().store.struct_db
        )  # S7d — 옛 get("STRUCT_DB")(없으면 None — 빈 글자 ''도 None(칸 기본값), open_backend는 둘 다 기본 파일)
    except SDB.StructDBError as e:  # 서버를 죽이지 않고 결과 note로만 알림(X1b 리뷰)
        return {"kind": "list", "answer": "0건", "columns": [], "rows": [], "evidence": [], "note": f"정형 저장소 연결 실패: {e}"}
    try:
        if is_link:
            return doc_link_list(db, hidden=hidden)
        if is_list:
            return doc_location_list(db, question)
        return table_cell_list(db, question)
    finally:
        db.close()


def doc_location_list(db, question):
    """문서 목록·건수·최근 판(doc_location SQL, AD45①·AD38 list_documents와 같은 원천) — 고정 질의 + 파이썬 필터만(자유 SQL 금지).
    기본(latest_only과 같음): 삭제(is_deleted)·대체된 구판(supersedes_doc_id, AR4② modules/search/supersede.py 공용 규칙) 제외.
    OP1(독립 검토 BLOCK 반영, 미해결로 명시) — doc_location.doc_id는 RDB 원천 키(FileStorageMap.id류)라 AD16
    문서 대장의 doc_key(file_sha256)와 바로 안 이어진다(이 표 자체에 file_sha256 열이 없음) — 문서 대장이 본
    deleted/hidden을 여기서는 못 거른다(doc_location의 is_deleted는 RDB manifest가 보낸 별도 플래그, OP1의
    hide와는 다른 신호). doc_id↔file_sha256 조인 경로(doc_registry나 매니페스트 교차)가 생기면 그때 더함."""
    try:
        rows = db.query("SELECT * FROM doc_location")
    except Exception:
        return {
            "kind": "list",
            "answer": "0건",
            "columns": [],
            "rows": [],
            "evidence": [],
            "note": "doc_location 없음 — modules/load/structured.py load(doc_location.csv) 먼저",
        }
    superseded = SS.superseded_set(rows)  # AR4② — 대체판 규칙(supersede.py)
    rows = [r for r in rows if not r.get("is_deleted") and not SS.is_superseded(r["doc_id"], superseded)]

    cids = {r["contract_id"] for r in rows if r.get("contract_id")}
    cid = next((c for c in cids if ID_LIKE.fullmatch(c) and norm(c) in norm(question)), None)
    if cid:
        rows = [r for r in rows if r.get("contract_id") == cid]
    else:
        name_by_id = {r["company_id"]: r["company"] for r in db.query("SELECT company_id, company FROM client_master")}
        hit = match_clients(question, set(name_by_id.values()), _struct_client_aliases(db))
        if hit:
            wanted = {cid_ for cid_, name in name_by_id.items() if name in hit}
            rows = [r for r in rows if r.get("company_id") in wanted]

    dtype = next((d for p, d in DOC_TYPE_PATTERNS if p.search(question)), None)
    if dtype:
        rows = [r for r in rows if r.get("doc_type") == dtype]
    yr = YEAR_RE.search(question)
    if yr:
        y = yr.group(1) or yr.group(2)
        rows = [r for r in rows if (r.get("received_at") or "").startswith(y)]

    rows.sort(key=lambda r: (r.get("received_at") or "", r["doc_id"]))
    cat_note = _catalog_note("doc_location", ["doc_id", "doc_type", "contract_id", "version", "received_at"])
    note = "doc_location(최신판만, 대체·삭제 제외)" + (" · " + cat_note if cat_note else "")
    return {
        "kind": "list",
        "target": {"filter": "문서 위치(doc_location)"},
        "answer": (f"{len(rows)}건: " + ", ".join(r["doc_id"] for r in rows)) if rows else "0건",
        "columns": ["문서", "종류", "계약ID", "판", "접수일"],
        "rows": [[r["doc_id"], r.get("doc_type"), r.get("contract_id"), r.get("version"), r.get("received_at")] for r in rows],
        "evidence": [
            {"file_path": r["doc_id"], "contract_no": r.get("contract_id"), "page": None, "line": None, "items": 0, "confirmed": True}
            for r in rows
        ],
        "note": note,
    }


def doc_link_list(db, hidden=None):
    """계약 ID가 안 적혀 있었는데(별칭·제품 코드 등으로) 계약에 이어진 문서 — doc_contract_link SQL(how != 계약 ID 기입).
    db.notes(X1b — PG 연결 안 돼 SQLite로 대체된 경우의 표시)는 note에 함께 보임.
    hidden(OP1, 독립 검토 BLOCK 반영) = 숨길 doc_key(file_sha256) 집합 — doc_contract_link.doc_key가 같은 값이라
    여기서 바로 뺄 수 있음(None·빈 집합이면 전과 바이트 동일)."""
    backend_notes = list(getattr(db, "notes", []))
    try:
        rows = db.query("SELECT doc_key, contract_id, score, how, status FROM doc_contract_link WHERE how != ?", (SDB.HOW_ID_WRITTEN,))
    except Exception:
        return {
            "kind": "list",
            "answer": "0건",
            "columns": [],
            "rows": [],
            "evidence": [],
            "note": " · ".join(backend_notes + ["doc_contract_link 없음 — modules/load/structured.py load·link 먼저"]),
        }
    if hidden:
        rows = [r for r in rows if r.get("doc_key") not in hidden]
    return {
        "kind": "list",
        "target": {"filter": "계약 ID 미기입 + 연결됨"},
        "answer": f"{len(rows)}건",
        "columns": ["문서", "계약ID", "점수", "근거", "상태"],
        "rows": [[r["doc_key"], r["contract_id"], r["score"], r["how"], r["status"]] for r in rows],
        "evidence": [
            {
                "file_path": r["doc_key"],
                "contract_no": r["contract_id"],
                "page": None,
                "line": None,
                "items": 0,
                "confirmed": r["status"] == "확정",
            }
            for r in rows
        ],
        "note": " · ".join(backend_notes),
    }


def _catalog():
    """데이터 카탈로그(AD45① — valid_env/unstructured/synth-meta-rdb/meta/data_catalog.json·synth-edw/edw/data_catalog.json 형식,
    표·열 설명) — env DATA_CATALOG 경로, 없으면(또는 파일 없으면) 빈 dict(카탈로그 없으면 지금 그대로, 호출자가 빈 결과로 분기).
    {table_name: {"desc": str, "cols": {column_name: "설명 요약(단위·허용값·answers 포함)"}}}."""
    p = mc.cfg().search.data_catalog  # S7d — 설정 객체
    if not p or not Path(p).exists():
        return {}
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in data.get("rows", []):
        t = out.setdefault(r.get("table_name"), {"desc": "", "cols": {}})
        if not r.get("column_name"):
            t["desc"] = r.get("description") or ""
            continue
        bits = [r.get("description") or ""]
        if r.get("unit"):
            bits.append(f"단위={r['unit']}")
        if r.get("allowed_values"):
            bits.append(f"값={r['allowed_values']}")
        if r.get("answers"):
            bits.append(f"답={r['answers']}")
        t["cols"][r["column_name"]] = " · ".join(b for b in bits if b)
    return out


def _catalog_note(table, cols):
    """struct_context·doc_location_list에 동봉할 열 설명 한 줄(카탈로그 없거나 그 표가 없으면 '')."""
    t = _catalog().get(table)
    if not t:
        return ""
    bits = [f"{c}: {t['cols'][c]}" for c in cols if t["cols"].get(c)]
    if not (t.get("desc") or bits):
        return ""
    return f"[{table} 카탈로그] " + (t.get("desc") or "") + ((" — " + " · ".join(bits)) if bits else "")


def _struct_client_aliases(db):
    """고객 명부 = common._aliases()(stack.json 등) + client_master.aliases 병합 — modules/load/structured.py의
    _client_aliases와 같은 규칙(여기선 import 안 하고 합침 — aggregate는 modules/load를 import 안 함, 모듈 docstring 참조)."""
    out = _aliases()
    for r in db.query("SELECT company, aliases FROM client_master"):
        al = [a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()]
        if al:
            out[r["company"]] = sorted(set(out.get(r["company"], [])) | set(al))
    return out


def struct_context(question, hits, client=None, client_strict=False):
    """정형 저장소(X1/X1b) 문맥 — answer_prompt(aggs=...)에 그대로 넣을 표 하나(또는 저장소 꺼지면 None, 기존과 동일):
      (a) 검색된 문서(hits)에 연결된 계약(doc_contract_link, doc_key = hit 'doc_key' 또는 파일명) — 연결 없는 문서는 '계약 없음' 행
      (b) 질문에 적힌 계약ID(그대로 포함) · 고객 별칭(client_master.aliases + common 명부)이 가리키는 계약
      (c) 합계·건수·최댓값 등 '계약' 집계 질문이면 계약 마스터 전체(상한 STRUCT_CONTEXT_MAX) — SQL 계산은 안 하고 LLM이 표에서 계산
    contract_id 기준으로 중복 제거(먼저 나온 근거를 유지: 연결 > 질문 언급 > 전체).
    client·client_strict(BR52, local()과 같은 규칙) — 주어지면 계약 마스터를 company로 먼저 거른다(clientscope.allows,
    research.py do_search와 같은 q 기준 scope를 그대로 넘겨받음) — (a)(b)(c) 전부 이 뒤에서 돈다(연결된 계약이 범위 밖이면
    '연결 없음'으로, (b)(c)의 다른 고객 계약은 후보에서 빠짐). None(기본, 안 주는 기존 호출부 전부)이면 전과 바이트 동일."""
    if not (C.given("STRUCT_BACKEND") or C.given("STRUCT_DB")):  # S7d — 준 값만(옛 있고 없음 판정)
        return None
    try:
        db = SDB.open_backend(
            C.cfg().store.struct_db
        )  # S7d — 옛 get("STRUCT_DB")(없으면 None — 빈 글자 ''도 None(칸 기본값), open_backend는 둘 다 기본 파일)
    except SDB.StructDBError as e:  # struct()와 같게 — 서버를 죽이지 않고 note로만 알림(X1b)
        return {
            "kind": "table",
            "target": {},
            "answer": "",
            "unit": "",
            "evidence": [],
            "columns": [],
            "rows": [],
            "note": f"정형 저장소(EDW) 연결 실패: {e}",
        }
    try:
        try:
            contracts = db.query("SELECT * FROM contract_master")
        except Exception:
            return None  # 아직 적재 전(load 안 함) — 집계 경로처럼 조용히 패스
        if not contracts:
            return None
        if client:  # BR52 — local()과 같은 필터(company 기준), 범위 밖이면 뒤의 (a)(b)(c) 전부 그 뒤 데이터로만
            contracts = [c for c in contracts if CS.allows(c.get("company"), client, client_strict)]
            if not contracts:
                return None
        cols = list(contracts[0].keys())
        by_id = {c["contract_id"]: c for c in contracts if c.get("contract_id")}
        try:
            links = {r["doc_key"]: r for r in db.query("SELECT doc_key, contract_id, how, status FROM doc_contract_link")}
        except Exception:
            links = {}
        rows, seen = [], set()

        def add(key, row):
            if key not in seen:
                seen.add(key)
                rows.append(row)

        for h in hits:  # (a) 연결된 계약(연결 없으면 '계약 없음')
            name = Path(h["file_path"]).name if h.get("file_path") else ""
            keys = {k for k in (h.get("doc_key"), name, Path(name).stem if name else None) if k}
            link = next((links[k] for k in keys if k in links), None)
            c = by_id.get(link["contract_id"]) if link else None
            if c:
                add(c["contract_id"], [f"연결: {link['how']}({link['status']})", name] + [c[k] for k in cols])
            else:
                add(f"__none__{h.get('doc_key') or name}", ["연결 없음", name, "계약 없음"] + [None] * (len(cols) - 1))

        qn = norm(question)  # (b) 질문에 적힌 계약ID
        for c in contracts:
            if c.get("contract_id") and norm(c["contract_id"]) in qn:
                add(c["contract_id"], ["질문 언급", ""] + [c[k] for k in cols])
        clients = {c["company"] for c in contracts if c.get("company")}  # (b) 질문에 적힌 고객(별칭 포함)
        for cl in match_clients(question, clients, _struct_client_aliases(db)):
            for c in contracts:
                if c.get("company") == cl:
                    add(c["contract_id"], ["질문 언급(고객)", ""] + [c[k] for k in cols])

        if CONTRACT_WORD_RE.search(question) and (SUM_RE.search(question) or COUNT_RE.search(question) or MAXMIN_RE.search(question)):
            for c in contracts[:STRUCT_CONTEXT_MAX]:  # (c) 집계 질문 — 전체 마스터(상한)
                add(c["contract_id"], ["전체 계약", ""] + [c[k] for k in cols])

        if not rows:
            return None
        note = "정형 저장소(EDW) — 문서↔계약 연결·계약 마스터"
        cat_note = _catalog_note("contract_master", cols)
        if cat_note:
            note += " · " + cat_note
        if db.notes:
            note += " · " + " · ".join(db.notes)
        return {
            "kind": "table",
            "target": {"filter": "문서↔계약 연결·계약 마스터"},
            "answer": "",
            "unit": "",
            "evidence": [],
            "columns": ["출처", "문서"] + cols,
            "rows": rows,
            "note": note,
        }
    finally:
        db.close()
