"""MCP에 노출하지 않는 내부 조회 — 집계·하드 필터 문서 덤프(search 안쪽 경로). 문서 단건·그림·근거 이미지·용어·개념·문서 목록은
10-30 지움(요건 없음 — e2-18, 사용자 10-30).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

import time
from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)
from mcp_server.config import CFG
from mcp_server.services.search.server_state import _STATE, _retriever


def do_aggregate(question, client=None):
    """client(BR50 D) — do_search의 client 인자와 같은 범위: SEARCH_CLIENT_HARD=1이면 route() 전에 다른 고객
    문서를 뺀다(clientscope 공용 규칙, aggregate.local()·aggregate.pg()에서 — 집계가 '최상위 근거'로 다른 고객
    구조화 행을 돌려주던 구멍). client를 안 주면(기존 호출부 전부) 전과 바이트 동일.
    struct()(doc_link_list 등, X1/X1b 옵트인) 경로는 이번 범위 밖 — 남은 한계로 보고에 적음."""
    from mcp_server.services.search import aggregate as AG

    # OP1(독립 검토 BLOCK 반영) — 이미 떠 있는 Retriever가 있으면만 hidden을 건넴(_retriever()를 새로 만들지 않음 —
    # AG.struct()는 원래 Retriever·검색 묶음과 독립적으로 동작(정형 저장소 연결만 필요)이라 여기서 강제로 만들면
    # 묶음이 없는 상태(기동 직후·시험)에서도 쓸데없이 묶음 로딩을 시도해 죽는다, _selftest_aggregate_struct_fail).
    hidden = _STATE["R"].hidden if _STATE.get("R") is not None else None
    st = AG.struct(question, hidden=hidden)  # 정형 저장소 질문(X1/X1b) — ask·평가와 같은 한 곳(OP1 — hidden 적용, doc_link_list만)
    if st is not None:
        return st
    R = _retriever()
    from mcp_server.services.search import clientscope as CS

    allowed, strict, hard = CS.client_scope(question, client, R.clients())
    cl_kw = {"client": allowed, "client_strict": strict} if hard else {}
    llm_complete = _agg_llm_complete()  # R1(AD42·AD45②) — SEARCH_AGG_LLM=1이고 LLM 설정됐을 때만(아니면 None)
    r = (
        AG.pg(R.pg, question, llm_complete=llm_complete, hidden=R.hidden, **cl_kw)
        if R.pg
        else AG.local(_STATE["bundle"], question, llm_complete=llm_complete, hidden=R.hidden, **cl_kw)
    )  # OP1 — 숨김 문서는 집계(건수·합계·표)에서도 제외
    return r or {"note": "집계 질문으로 판별되지 않음(건수·합계·표) — search를 쓰세요"}


def _agg_llm_complete():
    """R1(AD42·AD45②) — SEARCH_AGG_LLM(기본 끔, =1로 켬 — AR3 10-12)이고 LLM이 설정돼 있을 때만 aggregate.route()에 줄 콜백을 만든다(아니면 None
    → route()가 조용히 regex 결과만 씀, 꺼짐이면 완전히 지금과 같음 · LLM 미설정이면 여기서 조용히 None — 외부 호출 없음).
    gamma 패키지 agg_llm_route 경유(GA2, agent= 필수) — decompose.split_question에 L.chat을 주입하는 것과 같은 방식(mcp_server.py do_search)."""
    from mcp_server.services.search.aggregate import agg_llm_on  # 단일 읽기 지점(aggregate.route()와 공용)

    if not agg_llm_on():
        return None
    from common.ai import llm as L

    if not L.configured():
        return None
    tmo = mc.cfg().search.agg.llm_timeout  # MCP p95 3초 목표(OP8) — 검색 경로라 짧게, 넘으면 검색으로 폴백(OP11 검토)
    return lambda p: L.chat(
        [{"role": "user", "content": p}], temperature=0.0, max_tokens=500, json_mode=True, agent="agg_llm_route", timeout=tmo
    )


def _manifest_by_name():
    """AD44 rdb 수집 manifest(output/parse/_source/manifest.jsonl) — doc_type·version·대체 문서·삭제 여부(RDB doc_location 메타)의
    가장 가까운 출처(AD45 완료 전까지 structdb에는 doc_location이 없음). 없으면 빈 dict — search 근거의 그 칸들은 None."""
    from common.core.contract import jl

    p = Path(mc.cfg().server.manifest or APP_ROOT / "output" / "parse" / "_source" / "manifest.jsonl")  # S7d — 설정 객체
    return {r["file_name"]: r for r in jl(p)} if p.exists() else {}


def do_filter_documents(client=None, source_system=None, project_id=None, division=None, service_type=None, limit=100, client_like=None):
    """하드 필터(2026-10-20) — PG v_chunk_source 뷰에서 조건에 정확히 맞는 문서 전부와 그 청크 전부를 점수·임베딩 없이 돌려준다.
    조건: client(고객명)·source_system(SFDC/CRMS/LAS)·project_id(프로젝트 코드)·division(DS/DP/CD/CM/AD/AS)·
    service_type(CMO DS/CMO DP/CDO/ADC/...). 안 준 조건은 무시(전체 대상) · 문서 수가 limit(기본 100, 0이면 무제한)을
    넘으면 잘리고 truncated=true · client는 sf_acc_name·clients(JSON 텍스트, clientscope.doc_clients로 해석) 정확 일치 —
    참고: 중첩 사본(data_retrieval/data_retrieval)의 초안은 SQL에 client = %s 컬럼을 썼지만 v_chunk_source에 그 칸이
    없어 UndefinedColumn으로 죽는다(2026-10-20 축소 스키마) — 여기서는 스키마에 맞게 고침.
    반환: {total_docs, total_chunks, truncated, docs: [{doc_id, file_name, source_system, sf_acc_name, division,
    service_type, project_code__c, chunks: [{chunk_id, page, seq, section, chunk_text, bbox, ...}]}]}
    청크 텍스트는 MAX_CHARS 상한으로 자를 수 있다. 로컬 묶음(비PG) 저장소면 {"error": ...}."""
    R = _retriever()
    if not R.pg:
        return {"error": "PG(pgvector) 연결 없음 — 로컬 묶음만으로는 이 도구를 못 씀"}
    from mcp_server.services.search import clientscope as CS

    s = R.pg.schema
    t0 = time.perf_counter()
    conds, vals = [], []
    if source_system:
        conds.append("(source_system = %s OR doc_source_system = %s)")
        vals += [source_system, source_system]
    if project_id:
        conds.append("project_code__c = %s")
        vals.append(project_id)
    if division:
        conds.append("division = %s")
        vals.append(division)
    if service_type:
        conds.append("service_type = %s")
        vals.append(service_type)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    try:
        rows = R.pg.q(f"SELECT * FROM {s}.v_chunk_source{where} ORDER BY doc_id, chunk_id", tuple(vals))
    except Exception as e:
        return {"error": f"필터 조회 실패: {e}"}
    if client:
        if client_like:  # 2026-10-22 사용자: client_like=true → 포함매칭 — Python 후치필터도 LIKE로

            def _hit(r):
                if client in (r.get("sf_acc_name") or ""):
                    return True
                names = CS.doc_clients(None, r.get("clients"))
                if isinstance(names, str):
                    return client in names
                return bool(names) and any(client in str(n) for n in names)
        else:  # 기본: 정확 일치

            def _hit(r):
                if r.get("sf_acc_name") == client:
                    return True
                names = CS.doc_clients(None, r.get("clients"))
                if isinstance(names, str):
                    return names == client
                return bool(names) and client in names

        rows = [r for r in rows if _hit(r)]
    docs = {}
    for r in rows:
        d = r["doc_id"]
        if d not in docs:
            docs[d] = {
                "doc_id": d,
                "file_name": r.get("file_name"),
                "source_system": r.get("doc_source_system") or r.get("source_system"),
                "sf_acc_name": r.get("sf_acc_name"),
                "division": r.get("division"),
                "service_type": r.get("service_type"),
                "project_code__c": r.get("project_code__c"),
                "chunks": [],
            }
        docs[d]["chunks"].append(
            {
                k: r.get(k)
                for k in (
                    "chunk_id",
                    "page",
                    "line_start",
                    "line_end",
                    "bbox",
                    "section",
                    "seq",
                    "chunk_text",
                    "summary",
                    "clients",
                    "chunk_source_system",
                    "sf_op_id",
                    "sf_op_name",
                    "contract_id",
                    "contract_date",
                    "prod_name",
                )
            }
        )
    out = [docs[k] for k in sorted(docs)]
    truncated = bool(limit) and len(out) > int(limit)
    if truncated:
        out = out[: int(limit)]
    lim = CFG.MAX_CHARS
    for d in out:
        for c in d["chunks"]:
            t = c.get("chunk_text") or ""
            if len(t) > lim:
                c["chunk_text"] = t[:lim]
                c["truncated"] = True
    return {
        "total_docs": len(out),
        "total_chunks": sum(len(d["chunks"]) for d in out),
        "truncated": truncated,
        "docs": out,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }
