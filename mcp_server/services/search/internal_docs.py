"""MCP에 노출하지 않는 내부 조회 — 하드 필터 문서 덤프(집계는 mc-04 10-31에 지움)(search 안쪽 경로). 문서 단건·그림·근거 이미지·용어·개념·문서 목록은
10-30 지움(요건 없음 — e2-18, 사용자 10-30).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

import time
from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)
from mcp_server.config import CFG
from mcp_server.services.search.server_state import _retriever


def _manifest_by_name():
    """AD44 rdb 수집 manifest(output/parse/_source/manifest.jsonl) — doc_type·version·대체 문서·삭제 여부(RDB doc_location 메타)의
    가장 가까운 출처. 없으면 빈 dict — search 근거의 그 칸들은 None."""
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
