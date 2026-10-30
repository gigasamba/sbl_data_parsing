"""검색 서비스 — do_search(하이브리드 근거 검색·하드 필터·집계 근거·질의 기록).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

import time

from mcp_server import config as mc  # mcp 설정 객체(S7d)
from mcp_server.config import CFG
from mcp_server.services.search.internal_docs import _manifest_by_name, do_aggregate, do_filter_documents
from mcp_server.services.search.server_state import _STATE, CALLER, _index_retriever, _retriever
from mcp_server.services.search.shaping import _evidence, cap, evidence_status


def _log(question, evidence, ms):
    """질의 기록 — qa_log.jsonl 파일만(mc-13, 사용자 10-30: PG qa_log 표는 만들지 않음 — 그 INSERT는 늘 실패해 삼켜졌음)."""
    from mcp_server.services.search import qa_log

    try:  # engine-qa BLOCK 1 — qa_log.append 안에서도 쓰기 실패를 잡지만, do_search를 절대 죽이지 않게 여기서도 한 번 더
        qa_log.append(question, evidence, ms, CALLER.get(), stack_name=_STATE.get("stack", {}).get("name"))  # OP6
    except Exception:
        pass


def _hard_filter_scope(hard):
    """(2026-10-20 통합) 하드 필터 조건에 정확히 맞는 문서 file_path 집합 — question+필터 검색의 범위.
    client는 sf_acc_name 정확 일치 또는 clients(JSON 텍스트) 안 라벨 포함 — do_filter_documents와 같은 뜻(여기는
    문서 집합만 구하면 되므로 SQL 한 번으로). PG 적재 저장소일 때만 가능 — 로컬 묶음이면 (None, None), 호출부가 안내.
    SQL 실패는 조용히 넘기지 않고 그대로 올림(범위를 모르고 전체 검색으로 새는 것보다 오류가 낫다)."""
    R = _retriever()
    if not R.pg:
        return None, None
    conds, vals = [], []
    if hard.get("client"):
        if hard.get("client_like"):
            conds.append(
                "(sf_acc_name LIKE %s OR clients LIKE %s)"
            )  # 2026-10-22: client_like=true → 포함매칭 — 'Daiichi'로 'Daiichi Sankyo Co Ltd'도 찾음
            vals += [f"%{hard['client']}%", f"%{hard['client']}%"]
        else:
            conds.append("(sf_acc_name = %s OR clients LIKE '%%\"' || %s || '\"%%')")  # 기본: 정확 일치
            vals += [hard["client"], hard["client"]]
    if hard.get("source_system"):
        conds.append("(source_system = %s OR doc_source_system = %s)")
        vals += [hard["source_system"], hard["source_system"]]
    if hard.get("project_id"):
        conds.append("project_code__c = %s")
        vals.append(hard["project_id"])
    if hard.get("division"):
        conds.append("division = %s")
        vals.append(hard["division"])
    if hard.get("service_type"):
        conds.append("service_type = %s")
        vals.append(hard["service_type"])
    where = " WHERE " + " AND ".join(conds)
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


def do_search(
    question,
    k=10,
    methods=None,
    decompose=None,
    client=None,
    index_id=None,
    source_system=None,
    project_id=None,
    division=None,
    service_type=None,
    limit=100,
    client_like=None,
):
    """client(AD38): 질문에서 못 잡아도 강제할 고객 — SEARCH_CLIENT_HARD=1이면 저장소 질의 단계에서 다른 고객은 뺌(미상은 기본 포함).
    (2026-10-20 통합) question 없이 하드 필터 조건만 주면 do_filter_documents 덤프를 그대로 돌려주고(문서 수 상한 limit 기본 100),
    question과 조건을 함께 주면 조건에 정확히 맞는 문서 범위 안에서만 검색한다(_hard_filter_scope 후치 필터 — 헤더 docstring 참고).
    조건 문구·limit 의미는 do_filter_documents와 동일(정확 일치)."""
    t0 = time.perf_counter()
    question = question.strip() if isinstance(question, str) else (question or None)
    user_k = max(1, min(int(k), CFG.MAX_K))
    hard = {
        c: v
        for c, v in (
            ("client", client),
            ("source_system", source_system),
            ("project_id", project_id),
            ("division", division),
            ("service_type", service_type),
        )
        if v
    }
    if client and client_like:
        hard["client_like"] = True
    if not question:
        if not hard:
            return {"error": "question 또는 하드 필터 조건(client·source_system·project_id·division·service_type) 중 하나는 필요"}
        return do_filter_documents(
            client=client,
            source_system=source_system,
            project_id=project_id,
            division=division,
            service_type=service_type,
            limit=limit,
            client_like=client_like,
        )
    k = user_k
    scope, scope_docs = None, None
    if hard:
        scope, scope_docs = _hard_filter_scope(hard)
        if scope_docs == 0:  # 조건에 맞는 문서가 없음 — 검색할 범위 자체가 없다(빠른 반환)
            ms = (time.perf_counter() - t0) * 1000
            return cap(
                {
                    "question": question,
                    "store": "pgvector" if _retriever().pg else "local",
                    "methods": [],
                    "filter": hard,
                    "scope_docs": 0,
                    "evidence": [],
                    "images": [],
                    "notes": ["하드 필터에 맞는 문서 0건 — 근거 없음"],
                    "evidence_status": "none",
                    "ms": round(ms, 1),
                }
            )
        if scope:  # 범위 필터 뒤에도 근거 k개가 남게 — 풀을 넉넉히(상한 MAX_K)
            k = min(CFG.MAX_K, max(user_k * 3, 30))
    methods = [m.lower() for m in (methods or CFG.DEFAULT_METHODS)]
    unknown = [m for m in methods if m not in CFG.CORE]  # graph·concept·image·openviking은 10-29에 지움
    if index_id:  # AD41 — 이름 있는 색인(없으면 기본 색인, 응답도 전과 같음)
        R, err, warn = _index_retriever(index_id)
        if err:
            return err
    else:
        R, warn = _retriever(), None
    notes = [warn] if warn else []
    if hard and scope is None:  # (2026-10-20 통합) 로컬 묶음 저장소 — 범위 산정 불가, 솔직히 알림
        notes.append("하드 필터는 PG 적재 저장소에서만 동작 — 이 요청은 필터 없이 전체 검색")
    if unknown:
        notes.append(f"모르는 방법 무시: {unknown}")
    core = [m for m in methods if m in CFG.CORE]
    subs = []  # 응답 모양 유지(질문 분해는 10-29에 지움 — 늘 빈 목록)
    agg, agg_ex_note = None, None
    # BR23 — 집계로 갈 질문인지 먼저 판별(아래 엔티티 분해 게이트용) ·
    try:  # do_aggregate는 여기서 한 번만 부르고 결과를 재사용(§ 아래 재사용, DB 중복 질의 없음)
        agg = do_aggregate(question, client=client)  # BR50 D — 집계도 같은 client 범위(하드 격리면 다른 고객 구조화 행이 안 섞임)
    except Exception as ex:  # do_aggregate 자체가 올리는 StructDBError 등 — search는 계속
        agg, agg_ex_note = None, f"집계 경로 오류 — 검색만: {type(ex).__name__}: {str(ex)[:120]}"
    agg_hit = agg is not None and "kind" in agg  # kind 있음 = aggregate.detect()(또는 struct() 연결 판별)가 집계로 판별
    hits, r_notes = [], {}
    if core:
        hits, _, r_notes = R.search_ex(
            question, k, core, client=client, scope=scope
        )  # S12: search_ex — note류를 반환값으로(공유 R을 여러 스레드가 써도 안 섞임)
        if not agg_hit:  # BR23 — 비교 질문(고객 2명 이상 동시 언급)이
            from common.core.terms import match_clients  # 한쪽 고객에 몰려 슬롯을 뺏기는 문제. R2-c 요건③(client+ID_LIKE)은

            ents = match_clients(question, R.clients())[:4]  # 94/115건 과다발동 p95+511ms로 기각됨 — 여기선 trigger를 "고객명
            if len(ents) >= 2:  # 2개 이상 실제 일치 + 집계 경로로 안 빠짐"으로 좁혀 재시도.
                # agg_hit 제외 — 집계 비교(계약 건수·합계)는 구조화 집계가
                # 답을 내고 전문 검색 근거는 참고용이라 분해해도 doc_hit·evid_cov
                # 효과가 없다(synth-4clients-cmp 실측, [:4]는 호출 수 상한).
                pool = {h["chunk_ref"]: h for h in hits}

                def srch(q, n):
                    nonlocal r_notes
                    if q == question:
                        return [h["chunk_ref"] for h in hits[:n]]
                    hs, _, r_notes = R.search_ex(
                        question, n, core, client=q, client_only=True, scope=scope
                    )  # q=고객명(엔티티별 하위 검색, 다른 고객 자동매칭 무시)
                    for h in hs:
                        pool.setdefault(h["chunk_ref"], h)
                    return [h["chunk_ref"] for h in hs]

                items = _gather(question, ents, srch, base=k, per=max(3, k // 2))
                hits = [
                    {**pool[c], "rank": i + 1, "via": (pool[c].get("via") or "") + ("" if qi == 0 else f"·ent{qi}")}
                    for i, (c, qi) in enumerate(items)
                ]
                notes.append(f"엔티티 분해(BR23, 고객 {len(ents)}명)")
    man = _manifest_by_name()  # AD44 — 있을 때만 근거에 RDB 문서 메타(doc_type 등) 더 붙음
    rep_cache = {}  # OP21(S78) — 이 요청 안에서 문서별 AI.ParsingMeta 조회 1회만
    evidence = [_evidence(h, man, rep_cache) for h in hits]
    if evidence:  # R2-c 요건① — 같은 사건의 사본(형식·재명명)이 슬롯을 독점하는 문제
        from common.core.docmeta import copy_groups, copy_representative

        groups = copy_groups([{"file_name": e.get("file_name"), "text": e.get("text")} for e in evidence])
        if groups:
            drop = set()
            for rep_i, dup_is in groups.items():
                members_i = [rep_i] + dup_is  # 슬롯 자리는 rep_i(최상위 순위)로 그대로 — 내용만 아래서 바꿈
                names = [evidence[i]["file_name"] for i in members_i]
                best_i = members_i[
                    copy_representative([evidence[i] for i in members_i])
                ]  # engine-qa CONCERN(QA066) — 형식·본문 길이로 대표 텍스트 고름
                rank = evidence[rep_i].get("rank")
                evidence[rep_i] = {
                    **evidence[best_i],
                    "rank": rank,
                    "variants": list(dict.fromkeys(n for n in names if n != evidence[best_i]["file_name"])),
                }  # 대표 자신 이름은 variants에서 뺌(중복 제거)
                drop |= set(members_i) - {rep_i}
            evidence = [e for i, e in enumerate(evidence) if i not in drop]
            notes.append(f"사본 그룹 {len(groups)}개 묶음({sum(len(v) for v in groups.values())}건)")
    # R1(AD42) — 집계 질문이면 집계 결과(기존 정해진 함수만)를 맨 앞에
    if agg_ex_note:  # BR23 — agg는 위(엔티티 분해 게이트용)에서 이미 한 번 구해둔 값 재사용(DB 중복 질의 없음)
        notes.append(agg_ex_note)
    if agg_hit and hard:  # (2026-10-20 통합) 집계 근거는 전체 구조화 집계라 하드 필터 범위와 안 맞음 — 생략
        notes.append("집계 경로 감지 — 하드 필터 범위 밖 집계라 근거 삽입 생략")
    if not hard and agg_hit:  # kind 있음 = aggregate.detect()(또는 struct() 연결 판별)가 집계로 판별
        via = agg.get("via") or "aggregate"  # R1(AD42·AD45②) — LLM 경로만 aggregate.route()가 via="aggregate_llm"을 심음
        from mcp_server.services.search import (
            aggregate as AG,
        )  # RV-aggtext — table_text(합계 뒤에 고객별·제품 종류별 표 행을 text에 붙임)

        text = f"[집계] {agg.get('answer')}" + (f" {agg['unit']}" if agg.get("unit") else "")
        rows_text = AG.table_text(agg)
        if rows_text:
            text += "\n" + rows_text
        if AG.mixed_currencies(agg):  # BR43 — 통화 2개 이상 섞인 집계만
            # BR50 E — client=None이던 것을 호출 범위(client)로(하드 격리면 다른 고객 전용 청크가 안 섞임) ·
            # client_strict=False로 강제(일반 환율표는 고객 미상이 보통이라 항상 포함, clientscope 공용 규칙)
            fx_hits, _, _ = R.search_ex(AG.FX_QUERY, 1, ["bm25", "id"], recency=None, client=client, client_strict=False)
            fx_text = AG.fx_evidence_text(_evidence(fx_hits[0], man, rep_cache)) if fx_hits else None
            if fx_text:
                text += "\n" + fx_text
                notes.append("환율 근거 추가(SEARCH_AGG_FX)")
        evidence.insert(
            0,
            {
                "via": via,
                "text": text,
                "answer": agg.get("answer"),
                "unit": agg.get("unit"),
                "kind": agg.get("kind"),
                "columns": agg.get("columns"),
                "rows": agg.get("rows"),
                "totals": agg.get("totals"),
            },
        )
        notes.append(
            "집계 경로 사용(SEARCH_AGG_ROUTE)"
            + (" · R1 LLM 경계 분류" if via == "aggregate_llm" else "")
            + (f" · {agg['note']}" if agg.get("note") else "")
        )
    if r_notes.get("note"):  # 질의 임베딩 장애·임베딩 없는 묶음 → 키워드·ID만(G11)
        notes.append(r_notes["note"])
    exn = r_notes.get("expand_notes")  # X3 — BM25 질의 확장(용어 사전)이 적용됐으면 표시
    if exn:
        notes.append("용어 확장: " + "; ".join(exn))
    if r_notes.get("recency_note"):  # L3-1 — 같은 문서군 최신성 순위가 적용됐으면 표시
        notes.append(r_notes["recency_note"])
    images = []  # 응답 모양 유지(그림 검색 image는 10-29에 지움)
    if hard and scope:  # (2026-10-20 통합) 하드 필터 범위 안 문서만 남기고 다시 1..n 순위 — 요청한 k개로
        kept_agg = evidence[0] if evidence and evidence[0].get("via") in ("aggregate", "aggregate_llm") else None
        scoped = [e for e in evidence if e is not kept_agg and (e.get("file_path") or "") in scope]
        for i, e in enumerate(scoped):
            e["rank"] = i + 1
        evidence = ([kept_agg] if kept_agg else []) + scoped[:user_k]
        notes.append(f"하드 필터 — 조건에 정확히 맞는 {scope_docs}문서 범위에서 검색")
    # R3(AD42) — 근거가 있나(표시만, 근거 목록은 안 줄임)
    min_score = mc.cfg().search.min_score  # 옛 `float(raw) if raw else None`(형식 틀림·빈 글자 = None) — 칸이 같게 처리(S7d)
    status, low = evidence_status(question, evidence, min_score)
    for e, lv in zip(evidence, low):
        if lv is not None:
            e["low_score"] = lv
    gate = {"evidence_status": status}
    ms = (time.perf_counter() - t0) * 1000
    _log(question, evidence, ms)
    return cap(
        {
            "question": question,
            "subs": subs,
            "store": "pgvector" if R.pg else "local",
            "methods": methods,
            "evidence": evidence,
            "images": images,
            "notes": notes,
            "ms": round(ms, 1),
            **gate,
            **({"index_id": index_id} if index_id else {}),
            **({"filter": hard, "scope_docs": scope_docs} if hard else {}),
        }
    )
