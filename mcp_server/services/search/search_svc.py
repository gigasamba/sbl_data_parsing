"""검색 서비스 — do_search(하드 거르기 범위 안의 하이브리드 근거 검색·질의 기록). 계약 모양은 mcp_server/schemas/evidence.py.
S5(10-26)에 mcp_server/main.py에서 옮김 · 11-01(mc-16) 운영 계약으로 — question 필수(덤프 방식 지움), 거르기 13칸, 맨 위 5칸·근거 12칸,
이름 있는 색인(index_id·AD41)·옛 입력(methods·decompose·limit)·옛 출력(subs·store·images·notes·ms) 지움.
"""

import time
from datetime import date, datetime, timedelta, timezone

from mcp_server import config as mc  # mcp 설정 객체(S7d)
from mcp_server.config import CFG
from mcp_server.schemas.evidence import EVIDENCE_KEYS, K_MAX, SEARCH_FILTERS
from mcp_server.services.search.internal_docs import _manifest_by_name
from mcp_server.services.search.server_state import _STATE, CALLER, _retriever
from mcp_server.services.search.shaping import _evidence, cap, evidence_status

KST = timezone(timedelta(hours=9))  # 시간대 없는 등록 시각은 KST(운영 계약)
# 정확 일치 거르기 → v_chunk_source 칸
_EXACT_COLS = {
    "project_id": "project_code__c",
    "division": "division",
    "service_type": "service_type",
    "doc_class": "doc_class",
    "sf_op_id": "sf_op_id",
    "sf_op_name": "sf_op_name",
    "contract_id": "contract_id",
    "FAQ_group": "faq_group",  # faq.chunk만(C4)
}
NO_QUESTION = "question is required — 질문 없이 문서를 고르려면 list_doc_fulltext, 원천 값 조회는 query_edw"
_SYSTEMS = ("SFDC", "CRMS", "LAS", "FAQ", "OTHER")
NO_SOURCE = "source_system is required — exactly one of SFDC, CRMS, LAS, FAQ, Other(원천마다 따로 찾음 — 여러 원천은 여러 번 부름, G20)"


def _log(question, evidence, ms):
    """질의 기록 — qa_log.jsonl 파일만(mc-13, 사용자 10-30: PG qa_log 표는 만들지 않음 — 그 INSERT는 늘 실패해 삼켜졌음)."""
    from mcp_server.services.search import qa_log

    try:  # engine-qa BLOCK 1 — qa_log.append 안에서도 쓰기 실패를 잡지만, do_search를 절대 죽이지 않게 여기서도 한 번 더
        qa_log.append(question, evidence, ms, CALLER.get(), stack_name=_STATE.get("stack", {}).get("name"))  # OP6
    except Exception:
        pass


def _vals(v):
    """거르기 값 → 목록(문자열 하나 또는 목록, 빈 값 뺌)."""
    return [str(x) for x in (v if isinstance(v, list | tuple) else [v]) if x not in (None, "")]


def _when(v, upper):
    """created_since/created_until 글자 → (비교 연산자, 시각). 날짜만이면 since = 그날 00:00 KST, until = 다음 날 00:00 미만(그날 전체).
    시간대 없는 시각은 KST. 형식이 틀리면 ValueError."""
    s = str(v).strip()
    try:
        day = date.fromisoformat(s)  # 날짜만(2025-03-01·20250301)
    except ValueError:
        day = None
    if day is not None:
        d = datetime.combine(day, datetime.min.time(), KST)
        return ("<", (d + timedelta(days=1)).isoformat()) if upper else (">=", d.isoformat())
    t = datetime.fromisoformat(s)
    # KST로 맞춰 글자로 — 적재 값(pgvector_load._kst)과 같은 시간대 표기라 SQLite 대역의 글자 비교도 맞음(PG는 시각으로 비교)
    return ("<=" if upper else ">="), (t if t.tzinfo else t.replace(tzinfo=KST)).astimezone(KST).isoformat()


def _like(x):
    """LIKE 안에서 글자 그대로 — 값의 %·_는 와일드카드가 아님(ESCAPE '!')."""
    return x.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _norm_filters(args):
    """받은 거르기 → 정규화한 메아리(dict — 응답 filter 칸). 빈 값은 뺌 · source_system의 `-test` 붙은 값은 같은 뜻(G4) ·
    client_like는 client가 있을 때만."""
    hard = {}
    for name in SEARCH_FILTERS:
        v = args.get(name)
        if name == "client_like":
            continue
        vs = _vals(v)
        if name == "source_system":
            vs = [x[: -len("-test")] if x.lower().endswith("-test") else x for x in vs]
        if vs:
            hard[name] = vs if isinstance(v, list | tuple) else vs[0]
    if hard.get("client") and args.get("client_like"):
        hard["client_like"] = True
    return hard


def _scope_sql(hard, src):
    """정규화한 거르기 → (WHERE 글자, 값) — 원천 스키마 src의 v_chunk_source 칸에서. 다른 거르기는 AND, 같은 거르기의 목록은 OR, 모두 정확 일치
    (client_like만 부분 일치). 그 원천 스키마에 칸이 없는 거르기(예: crms에서 sf_op_id)는 0건(오류 아님). 고객은 client_edw만(C6, 사용자 11-02)."""
    from common.store.db.models import search_tables as ST

    have = set(ST.view_columns(src))
    conds, vals = [], []

    def any_of(tmpl, vs, per):
        conds.append("(" + " OR ".join([tmpl] * len(vs)) + ")")
        for x in vs:
            vals.extend(per(x))

    for name, v in hard.items():
        vs = _vals(v)
        if name in ("source_system", "client_like"):
            continue  # source_system은 스키마 고르기(위) · client_like는 client 안에서
        if name == "client":
            if hard.get("client_like"):
                any_of("client_edw LIKE %s ESCAPE '!'", vs, lambda x: [f"%{_like(x)}%"])
            else:
                any_of("client_edw = %s", vs, lambda x: [x])
        elif name in _EXACT_COLS:
            col = _EXACT_COLS[name]
            if col in have:
                any_of(f"{col} = %s", vs, lambda x: [x])
            else:
                conds.append("1 = 0")
        elif name in ("created_since", "created_until"):
            op, t = _when(v, name == "created_until")
            conds.append(f"created_at {op} %s")  # created_at이 없는 문서는 빠짐
            vals.append(t)
    return (" WHERE " + " AND ".join(conds)) if conds else "", vals


def _hard_filter_scope(hard, src):
    """하드 거르기에 정확히 맞는 문서 file_path 집합과 문서 수 — 검색 범위(원천 스키마 src 안). SQL 실패는 그대로 올림."""
    R = _retriever(src)
    where, vals = _scope_sql(hard, src)
    rows = R.pg.q(f"SELECT DISTINCT file_path FROM {R.pg.schema}.v_chunk_source{where}", tuple(vals))
    return {r["file_path"] for r in rows}, len(rows)


def _source_docs(src):
    """원천 스키마의 문서 수(source_system만 줬을 때의 scope_docs)."""
    R = _retriever(src)
    r = R.pg.q(f"SELECT COUNT(*) AS n FROM {R.pg.schema}.doc")
    return int(r[0]["n"]) if r else 0


def _out(question, evidence, status, hard, scope_docs):
    """계약 모양으로 — 근거는 12칸만, 맨 위 5칸(filter·scope_docs는 거르기를 줬을 때만). cap이 줄이면 근거 글·개수만 줄고 표시 칸은 뺀다(계약 밖)."""
    obj = {
        "question": question,
        "evidence": [{k: e.get(k) for k in EVIDENCE_KEYS} for e in evidence],
        "evidence_status": status,
        **({"filter": hard, "scope_docs": scope_docs} if hard else {}),
    }
    obj = cap(obj)
    obj.pop("truncated", None)
    obj.pop("truncation", None)
    return obj


def do_search(question=None, k=8, **filters):
    """운영 search 계약(mc-16). question 필수(비면 {"error"}) · k 기본 8·상한 50 · 거르기(SEARCH_FILTERS)는 모두 AND, 같은 거르기의 목록은 OR ·
    모르는 인자는 무시 · 맞는 문서가 없으면 오류가 아니라 빈 결과(scope_docs 0, evidence_status none).
    source_system은 필수·값 하나(G20 — 그 원천 스키마만 찾음, 사용자 11-02 — 운영과 다름). R2-c — 같은 사건의 사본은 한 자리로 묶는다(응답 모양은 같음).
    본문 고객 라벨로 앞으로 올리던 길(AD38)·고객별 하위 검색(BR23)은 11-02에 지움 — 고객은 client_edw 거르기만(C6)."""
    t0 = time.perf_counter()
    question = question.strip() if isinstance(question, str) else None
    if not question:
        return {"error": NO_QUESTION}
    try:
        user_k = max(1, min(int(k), K_MAX))
    except (TypeError, ValueError):
        user_k = 8
    hard = _norm_filters(filters)
    sysv = hard.get("source_system")
    if not sysv or isinstance(sysv, list) and len(sysv) != 1:  # G20(사용자 11-02) — 원천 하나 필수(운영과 다름)
        return {"error": NO_SOURCE}
    if isinstance(sysv, list):
        hard["source_system"] = sysv = sysv[0]
    if str(sysv).upper() not in _SYSTEMS:  # 다섯 값 밖은 거부(조용히 other로 찾지 않음)
        return {"error": NO_SOURCE}
    from common.store.db.models import search_tables as ST

    src = ST.source_of(sysv)
    k, scope, scope_docs = user_k, None, None
    if len(hard) > 1:  # source_system 말고 거르기가 있을 때만 범위를 구함(원천 스키마 전체면 범위 없이)
        try:
            scope, scope_docs = _hard_filter_scope(hard, src)
        except ValueError as bad:  # created_since/until 형식 틀림
            return {"error": f"created_since/created_until 형식 — YYYY-MM-DD 또는 ISO 8601 시각: {bad}"}
        if scope_docs == 0:  # 조건에 맞는 문서가 없음 — 검색할 범위 자체가 없다
            return _out(question, [], "none", hard, 0)
        k = min(K_MAX, max(user_k * 3, 30))  # 범위 거르기 뒤에도 근거 k개가 남게 — 풀을 넉넉히
    else:
        scope_docs = _source_docs(src)
    R = _retriever(src)
    core = [m.lower() for m in CFG.DEFAULT_METHODS if m.lower() in CFG.CORE]  # 검색 길은 서버 설정만(호출 인자로 못 바꿈)
    hits = []
    if core:
        hits, _, _ = R.search_ex(question, k, core, scope=scope)
    man = _manifest_by_name()  # AD44 — 있으면 근거 version을 RDB 값으로
    evidence = [_evidence(h, man) for h in hits]
    if evidence:  # R2-c 요건① — 같은 사건의 사본(형식·재명명)이 슬롯을 독점하는 문제
        from common.core.docmeta import copy_groups, copy_representative

        groups = copy_groups([{"file_name": e.get("file_name"), "text": e.get("text")} for e in evidence])
        drop = set()
        for rep_i, dup_is in groups.items():
            members_i = [rep_i] + dup_is  # 슬롯 자리는 rep_i(최상위 순위) 그대로 — 내용만 대표로
            best_i = members_i[copy_representative([evidence[i] for i in members_i])]  # 형식·본문 길이로 대표 텍스트 고름
            evidence[rep_i] = {**evidence[best_i], "rank": evidence[rep_i].get("rank")}
            drop |= set(members_i) - {rep_i}
        evidence = [e for i, e in enumerate(evidence) if i not in drop]
    if scope is not None:  # 하드 거르기 범위 안 문서만 남기고 다시 1..n — 요청한 k개로
        evidence = [e for e in evidence if (e.get("file_path") or "") in scope]
    evidence = evidence[:user_k]
    for i, e in enumerate(evidence):
        e["rank"] = i + 1
    status, _ = evidence_status(question, evidence, mc.cfg().search.min_score)  # R3(AD42) — 표시만, 근거 목록은 안 줄임
    _log(question, evidence, (time.perf_counter() - t0) * 1000)
    return _out(question, evidence, status, hard, scope_docs)
