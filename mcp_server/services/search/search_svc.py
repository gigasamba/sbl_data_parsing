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
}
NO_QUESTION = "question is required — 질문 없이 문서를 고르려면 list_doc_fulltext, 원천 값 조회는 query_edw"


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


def _scope_sql(hard):
    """정규화한 거르기 → (WHERE 글자, 값). 다른 거르기는 AND, 같은 거르기의 목록은 OR. 모두 정확 일치(client_like만 부분 일치)."""
    conds, vals = [], []

    def any_of(tmpl, vs, per):
        conds.append("(" + " OR ".join([tmpl] * len(vs)) + ")")
        for x in vs:
            vals.extend(per(x))

    for name, v in hard.items():
        vs = _vals(v)
        if name == "client":
            if hard.get("client_like"):
                any_of("(sf_acc_name LIKE %s ESCAPE '!' OR clients LIKE %s ESCAPE '!')", vs, lambda x: [f"%{_like(x)}%"] * 2)
            else:  # 계정 이름 정확 일치 또는 문서 고객 라벨(JSON 글자) 안 정확 일치
                any_of("(sf_acc_name = %s OR clients LIKE %s ESCAPE '!')", vs, lambda x: [x, f'%"{_like(x)}"%'])
        elif name == "source_system":
            any_of("(source_system = %s OR doc_source_system = %s)", vs, lambda x: [x, x])
        elif name in _EXACT_COLS:
            any_of(f"{_EXACT_COLS[name]} = %s", vs, lambda x: [x])
        elif name == "FAQ_group":
            # ponytail: 한 벌 표에는 faq_group 칸이 없고 FAQ를 아직 적재하지 않음(pl-39) — 늘 0건. 스키마를 나눌 때(pl-28) faq.chunk.faq_group으로
            conds.append("1 = 0")
        elif name in ("created_since", "created_until"):
            op, t = _when(v, name == "created_until")
            conds.append(f"created_at {op} %s")  # created_at이 없는 문서는 빠짐
            vals.append(t)
    return " WHERE " + " AND ".join(conds), vals


def _hard_filter_scope(hard):
    """하드 거르기에 정확히 맞는 문서 file_path 집합과 문서 수 — 검색 범위. SQL 실패는 그대로 올림(범위를 모르고 전체 검색으로 새는 것보다 낫다)."""
    R = _retriever()
    where, vals = _scope_sql(hard)
    rows = R.pg.q(f"SELECT DISTINCT file_path FROM {R.pg.schema}.v_chunk_source{where}", tuple(vals))
    return {r["file_path"] for r in rows}, len(rows)


def _gather(question, subs, search, base, per):
    """원 질문은 search(q, base), 하위 검색(고객별)은 search(q, per)로 찾아 라운드로빈으로 합친다(중복 제거) — 원 질문 근거
    개수는 그대로, 어느 하위 검색도 0개로 밀려나지 않게. 반환: [(키, 출처 번호 0=원 질문)]. 옛 decompose.gather(10-29 이동)."""
    lists = [search(question, base)] + [search(q, per) for q in subs]
    out, seen = [], set()
    for rank in range(max(base, per)):
        for qi, lst in enumerate(lists):
            if rank < len(lst) and lst[rank] not in seen:
                seen.add(lst[rank])
                out.append((lst[rank], qi))
    return out


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
    BR23 — 질문에 고객 2명 이상이면 고객별 하위 검색을 섞고, R2-c — 같은 사건의 사본은 한 자리로 묶는다(응답 모양은 같음)."""
    t0 = time.perf_counter()
    question = question.strip() if isinstance(question, str) else None
    if not question:
        return {"error": NO_QUESTION}
    try:
        user_k = max(1, min(int(k), K_MAX))
    except (TypeError, ValueError):
        user_k = 8
    hard = _norm_filters(filters)
    k, scope, scope_docs = user_k, None, None
    if hard:
        try:
            scope, scope_docs = _hard_filter_scope(hard)
        except ValueError as bad:  # created_since/until 형식 틀림
            return {"error": f"created_since/created_until 형식 — YYYY-MM-DD 또는 ISO 8601 시각: {bad}"}
        if scope_docs == 0:  # 조건에 맞는 문서가 없음 — 검색할 범위 자체가 없다
            return _out(question, [], "none", hard, 0)
        k = min(K_MAX, max(user_k * 3, 30))  # 범위 거르기 뒤에도 근거 k개가 남게 — 풀을 넉넉히
    client = hard.get("client")
    R = _retriever()
    core = [m.lower() for m in CFG.DEFAULT_METHODS if m.lower() in CFG.CORE]  # 검색 길은 서버 설정만(호출 인자로 못 바꿈)
    hits = []
    if core:
        hits, _, _ = R.search_ex(question, k, core, client=client, scope=scope)
        from common.core.terms import match_clients  # BR23 — 비교 질문(고객 2명 이상)이 한쪽 고객에 몰려 슬롯을 뺏기지 않게

        ents = match_clients(question, R.clients())[:4]  # [:4]는 호출 수 상한
        if len(ents) >= 2:
            pool = {h["chunk_ref"]: h for h in hits}

            def srch(q, n):
                if q == question:
                    return [h["chunk_ref"] for h in hits[:n]]
                hs, _, _ = R.search_ex(question, n, core, client=q, client_only=True, scope=scope)  # q=고객명(엔티티별 하위 검색)
                for h in hs:
                    pool.setdefault(h["chunk_ref"], h)
                return [h["chunk_ref"] for h in hs]

            items = _gather(question, ents, srch, base=k, per=max(3, k // 2))
            hits = [
                {**pool[c], "rank": i + 1, "via": (pool[c].get("via") or "") + ("" if qi == 0 else f"·ent{qi}")}
                for i, (c, qi) in enumerate(items)
            ]
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
