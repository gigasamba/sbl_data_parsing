"""원문 도구 2개 등록 — 서비스(do_list·do_get)를 스레드 창구(_bg)로 부르기만.
함수 이름·독스트링·서명은 MCP 도구 계약(tools/list 바이트)이다.
"""

from mcp_server.services.fulltext_svc import do_get, do_list
from mcp_server.services.tool_runner import _bg


def register(m):
    @m.tool()
    async def list_doc_fulltext(
        docs: list[str] | None = None,
        source_system: str | None = None,
        doc_class: str | None = None,
        sf_op_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        created_since: str | None = None,
        created_until: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """Stage 1 of 2: list each document's representative parse-result files (.md/.json) and issue signed handles (sfid).
        At least one condition (AND): docs (<=200 original file names with extension, or 64-hex doc_key), source_system
        (SFDC/CRMS/LAS/FAQ; '-test' suffix accepted) (개발 서버: DEV-<숫자>), doc_class, sf_op_id, since/until (parse time), created_since/created_until
        (source registration time). Dates: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS without time zone (KST); date-only until includes
        that whole day. limit default 50, max 200; cursor = previous batch.next_cursor.
        Returns {batch:{matched, returned, next_cursor, files_total_bytes}, documents:[{file_name, doc_key, source_system,
        doc_class, sf_op_id, created_at, parse_date, rep_uri, status (ok/no_files), files:{md, json} each {name, size, etag, sfid}
        or null}], ms}. No match = empty frame. Errors: bad_request (with detail), not_configured, source_storage_unavailable."""
        return await _bg(
            do_list,
            docs=docs,
            source_system=source_system,
            doc_class=doc_class,
            sf_op_id=sf_op_id,
            since=since,
            until=until,
            created_since=created_since,
            created_until=created_until,
            limit=limit,
            cursor=cursor,
        )

    @m.tool()
    async def get_doc_fulltext(
        files: list[str],
        json_section: str | None = None,
        created_since: str | None = None,
        created_until: str | None = None,
    ) -> dict:
        """Stage 2 of 2: download files by sfid (1-20, verbatim from list_doc_fulltext). md -> raw UTF-8 text, json -> parsed
        object (json_section = comma-separated top-level keys to keep, e.g. "text,tables"). Limits: 16 MB per file (too_large),
        24 MB per call (rest batch_full, batch.truncated=true). created_since/created_until: optional guard on the document's
        registration time (out of range -> created_out_of_range). Returns {batch:{requested, ok, skipped, total_bytes, truncated,
        json_section}, files:[{sfid, name, kind, size, sha256, status:"ok", content} or {sfid, skip_reason, name, kind}], ms}.
        Skip reasons: bad_sfid, missing, too_large, batch_full, created_out_of_range, download_failed."""
        return await _bg(do_get, files=files, json_section=json_section, created_since=created_since, created_until=created_until)
