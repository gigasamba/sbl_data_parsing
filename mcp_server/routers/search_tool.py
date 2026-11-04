"""search 도구 등록 — 입력을 받아 서비스(do_search)를 스레드 창구(_bg)로 부르기만.
함수 이름·독스트링·서명·반환 형식은 MCP 도구 계약(🔒 CLAUDE.md §4 — tools/list 바이트)이다. 11-01(mc-16, 등급 A) 운영 계약으로 바꿈 —
question 필수, 거르기 13칸(운영 이름 그대로) + attrs(pl-52 11-03, 등급 A), 옛 입력 methods·decompose·limit·index_id 지움.
"""

from mcp_server.routers.dispatch import _bg
from mcp_server.services.search.search_svc import do_search


def register(m):
    @m.tool()
    async def search(
        question: str,
        k: int = 8,
        source_system: str | list[str] | None = None,
        client: str | list[str] | None = None,
        client_like: bool | None = None,
        project_id: str | list[str] | None = None,
        division: str | list[str] | None = None,
        service_type: str | list[str] | None = None,
        FAQ_group: str | list[str] | None = None,  # 운영 계약의 인자 이름 그대로(대문자)
        doc_class: str | list[str] | None = None,
        sf_op_id: str | list[str] | None = None,
        sf_op_name: str | list[str] | None = None,
        contract_id: str | list[str] | None = None,
        created_since: str | None = None,
        created_until: str | None = None,
        attrs: dict[str, str | list[str]] | None = None,
    ) -> dict:
        """Natural-language top-k evidence search inside hard filters (vector + bm25 + id, fused server-side).
        question is required (empty -> {"error"}). k: default 8, max 50 (larger is clamped).
        source_system is required: exactly one of SFDC/CRMS/LAS/FAQ/Other ('-test' suffix accepted); each call searches that one
        source only (call again for another source; missing -> {"error"}). Other filters are optional; different filters AND
        together, a list inside one filter is OR, all exact match: client (account name; client_like=true -> substring),
        project_id, division, service_type, FAQ_group, doc_class (within its source system's taxonomy), sf_op_id, sf_op_name,
        contract_id, created_since/created_until (source registration time; YYYY-MM-DD or ISO 8601, no time zone = KST,
        date-only until includes that whole day; docs without created_at are excluded).
        attrs: {key: value or list} on the source's metadata keys (keys differ per source_system; an unknown key returns
        {"error"} listing the valid keys — edw_meta with no arguments lists them). project_id, division, service_type,
        doc_class, sf_op_id, sf_op_name and contract_id are named shortcuts for attrs keys of that source.
        A filter that matches nothing returns an empty result (scope_docs 0, evidence_status "none"), not an error.
        Returns {question, evidence[], evidence_status (found/weak/none), filter, scope_docs}. Each evidence item has exactly: text, file_name, file_path, page, line, section, client, contract_no,
        doc_date, version, superseded, chunk_key, attrs (missing values are null; attrs holds the source's evidence keys, null if it has none)."""
        return await _bg(
            do_search,
            question,
            k,
            source_system=source_system,
            client=client,
            client_like=client_like,
            project_id=project_id,
            division=division,
            service_type=service_type,
            FAQ_group=FAQ_group,
            doc_class=doc_class,
            sf_op_id=sf_op_id,
            sf_op_name=sf_op_name,
            contract_id=contract_id,
            created_since=created_since,
            created_until=created_until,
            attrs=attrs,
        )
