"""검색 서비스 — do_search(하드 거르기 범위 안의 하이브리드 근거 검색·질의 기록). 계약 모양은 mcp_server/schemas/evidence.py.
S5(10-26)에 mcp_server/main.py에서 옮김 · 11-01(mc-16) 운영 계약으로 — question 필수(덤프 방식 지움), 거르기 14칸(attrs — pl-52), 맨 위 5칸·근거 13칸,
이름 있는 색인(index_id·AD41)·옛 입력(methods·decompose·limit)·옛 출력(subs·store·images·notes·ms) 지움.
"""

import functools
import json
from datetime import date, datetime, timedelta, timezone

from common.store import edw_chain as EC
from common.store.db.models import search_tables as ST
from mcp_server import config as mc  # mcp 설정 객체(S7d)
from mcp_server.config import CFG
from mcp_server.schemas.evidence import EVIDENCE_KEYS, K_MAX, SEARCH_FILTERS
from mcp_server.services.search.internal_docs import _manifest_by_name
from mcp_server.services.search.server_state import _retriever
from mcp_server.services.search.shaping import _evidence, cap, evidence_status

KST = timezone(timedelta(hours=9))  # 시간대 없는 등록 시각은 KST(운영 계약)
_SYSTEMS = tuple(s.upper() for s in ST.SOURCES)
NO_QUESTION = "question is required — 질문 없이 문서를 고르려면 list_doc_fulltext, 원천 값 조회는 query_edw"
NO_SOURCE = "source_system is required — exactly one of SFDC, CRMS, LAS, FAQ, Other(원천마다 따로 찾음 — 여러 원천은 여러 번 부름, G20)"


def chain():
    """검색이 쓰는 EDW 사슬(pl-52) — 설정 ops.paths.edw_chain(적재와 같은 칸), 비우면 기본 파일. 파일이 바뀌면(수정 시각) 다시 읽음.
    틀린 파일은 ValueError(common.store.edw_chain.load)."""
    p = EC.chain_path()
    try:
        t = p.stat().st_mtime_ns
    except OSError:
        t = None  # 없는 파일 — load가 오류 글로
    return _chain_at(str(p), t)


@functools.lru_cache(maxsize=4)
def _chain_at(path, _mtime):
    return EC.load(path)


def _vals(v):
    """거르기 값 → 목록(문자열 하나 또는 목록, 앞뒤 공백 뺌 — 적재 값과 같게(edw_meta._text), 빈 값 뺌)."""
    return [s for x in (v if isinstance(v, list | tuple) else [v]) if x is not None and (s := str(x).strip())]


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
        if name in ("client_like", "attrs"):  # attrs는 원천이 정해진 뒤(_norm_attrs)
            continue
        vs = _vals(v)
        if name == "source_system":
            vs = [x[: -len("-test")] if x.lower().endswith("-test") else x for x in vs]
        if vs:
            hard[name] = vs if isinstance(v, list | tuple) else vs[0]
    if hard.get("client") and args.get("client_like"):
        hard["client_like"] = True
    return hard


def _norm_attrs(raw, sysv, fmap):
    """attrs 거르기 {키: 값 또는 목록} → (정규화한 dict, 오류 글). 키는 그 원천 사슬의 거를 수 있는 키(fmap 값)만 — 모르는 키는 오류(조용한 0건 아님)."""
    if raw in (None, {}):
        return {}, None
    ok = sorted(set(fmap.values()))
    if not isinstance(raw, dict):
        return {}, f"attrs는 {{키: 값 또는 값 목록}} — {sysv}에서 거를 수 있는 키: {', '.join(ok) or '없음'}"
    bad = sorted(str(k) for k in raw if k not in ok)
    if bad:
        return (
            {},
            f"attrs 키 {', '.join(bad)}는 {sysv}에 없음 — 거를 수 있는 키: {', '.join(ok) or '없음'}(edw_meta 인자 없이 부르면 원천별 목록)",
        )
    out = {}
    for k, v in raw.items():
        vs = _vals(v)
        if vs:
            out[k] = vs if isinstance(v, list | tuple) else vs[0]
    return out, None


def _scope_sql(hard, src, fmap):
    """정규화한 거르기 → (WHERE 글자, 값) — 원천 스키마 src의 v_chunk_source 칸에서. 다른 거르기는 AND, 같은 거르기의 목록은 OR, 모두 정확 일치
    (client_like만 부분 일치). 이름 있는 거르기는 fmap(사슬의 filter → attrs 키, pl-52)으로 doc.attrs 키에 — 그 원천에 이어진 키가 없는 거르기
    (예: crms에서 sf_op_id)는 0건(오류 아님). attrs 거르기는 키 그대로(_norm_attrs가 검사한 키만). 고객은 client_edw만(C6, 사용자 11-02)."""
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
        elif name == "FAQ_group":  # 청크 칸(faq만 — C4)
            any_of("faq_group = %s", vs, lambda x: [x]) if "faq_group" in have else conds.append("1 = 0")
        elif name in ("created_since", "created_until"):
            op, t = _when(v, name == "created_until")
            conds.append(f"created_at {op} %s")  # created_at이 없는 문서는 빠짐
            vals.append(t)
        elif name == "attrs":  # 담김(@>) — GIN(jsonb_ops) 색인을 탐(->> 비교는 못 탐). 값은 글자(attrs는 늘 글자 — P1-1)
            for key, xs in v.items():
                any_of("attrs @> %s::jsonb", _vals(xs), lambda x, key=key: [json.dumps({key: str(x)})])
        elif fmap.get(name):  # 옛 이름 → 사슬의 attrs 키
            any_of("attrs @> %s::jsonb", vs, lambda x, key=fmap[name]: [json.dumps({key: str(x)})])
        else:  # 이 원천에 이어진 키가 없음
            conds.append("1 = 0")
    return (" WHERE " + " AND ".join(conds)) if conds else "", vals


def _hard_filter_scope(hard, src, fmap):
    """하드 거르기에 정확히 맞는 문서 file_path 집합과 문서 수 — 검색 범위(원천 스키마 src 안). SQL 실패는 그대로 올림."""
    R = _retriever(src)
    where, vals = _scope_sql(hard, src, fmap)
    rows = R.pg.q(f"SELECT DISTINCT file_path FROM {R.pg.schema}.v_chunk_source{where}", tuple(vals))
    return {r["file_path"] for r in rows}, len(rows)


def _doc_attrs(src, paths):
    """근거 문서 file_path → doc.attrs dict(pl-52 — PG는 dict, SQLite 대역은 JSON 글자)."""
    paths = sorted(p for p in paths if p)
    if not paths:
        return {}
    R = _retriever(src)
    rows = R.pg.q(f"SELECT file_path, attrs FROM {R.pg.schema}.doc WHERE file_path = ANY(%s)", (paths,))
    return {r["file_path"]: json.loads(r["attrs"]) if isinstance(r["attrs"], str) else r["attrs"] for r in rows}


def _source_docs(src):
    """원천 스키마의 문서 수(source_system만 줬을 때의 scope_docs)."""
    R = _retriever(src)
    r = R.pg.q(f"SELECT COUNT(*) AS n FROM {R.pg.schema}.doc")
    return int(r[0]["n"]) if r else 0


def _out(question, evidence, status, hard, scope_docs):
    """계약 모양으로 — 근거는 13칸만, 맨 위 5칸(filter·scope_docs도 늘 — source_system 필수). cap이 줄이면 근거 글·개수만 줄고 표시 칸은 뺀다(계약 밖)."""
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

    src = ST.source_of(sysv)
    try:
        ch = chain()
    except ValueError as bad:  # 틀린 사슬 파일 — 거르기·근거 attrs를 정할 수 없음
        return {"error": str(bad)}
    fmap = EC.filters(ch, src)
    attrs, bad_attrs = _norm_attrs(filters.get("attrs"), sysv, fmap)
    if bad_attrs:
        return {"error": bad_attrs}
    if attrs:
        hard["attrs"] = attrs
    k, scope, scope_docs = user_k, None, None
    if len(hard) > 1:  # source_system 말고 거르기가 있을 때만 범위를 구함(원천 스키마 전체면 범위 없이)
        try:
            scope, scope_docs = _hard_filter_scope(hard, src, fmap)
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
    # 근거 attrs = evidence: true 키 · contract_no = contract_id 거르기의 키 값 — 문서 attrs는 여기서 한 번에 읽음(검색 층 r 코드는 그대로)
    ev_keys, cno, by_doc = EC.evidence(ch, src), fmap.get("contract_id"), _doc_attrs(src, {e.get("file_path") for e in evidence})
    for i, e in enumerate(evidence):
        e["rank"] = i + 1
        a = by_doc.get(e.get("file_path")) or {}
        e["attrs"] = {x: a.get(x) for x in ev_keys} if ev_keys else None  # 근거 키가 없는 원천(FAQ·Other)은 null
        e["contract_no"] = a.get(cno) if cno else None
    status, _ = evidence_status(question, evidence, mc.cfg().search.min_score)  # R3(AD42) — 표시만, 근거 목록은 안 줄임
    return _out(question, evidence, status, hard, scope_docs)
