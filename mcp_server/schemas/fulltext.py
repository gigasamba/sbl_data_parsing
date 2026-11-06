"""원문 도구 응답 모양·한도(MCP 계약 — 운영 05 §6): list_doc_fulltext → get_doc_fulltext 두 단계.
바꾸면 계약이 바뀐다(등급 A). 운영과 다른 점: documents[]에 rep_engine 없음.
"""

LIST_TOP_KEYS = ("batch", "documents", "ms")
LIST_BATCH_KEYS = ("matched", "returned", "next_cursor", "files_total_bytes")
DOC_KEYS = ("file_name", "doc_key", "source_system", "doc_class", "sf_op_id", "created_at", "parse_date", "rep_uri", "status", "files")
FILE_KEYS = ("name", "size", "etag", "sfid")

GET_TOP_KEYS = ("batch", "files", "ms")
GET_BATCH_KEYS = ("requested", "ok", "skipped", "total_bytes", "truncated", "json_section")
SKIP_REASONS = ("bad_sfid", "missing", "too_large", "batch_full", "created_out_of_range", "download_failed")

DOCS_MAX = 200  # list docs=[…] 상한(넘으면 bad_request)
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 200  # 쪽 크기(넘으면 200으로 줄임)
GET_FILES_MAX = 20  # get 한 번에 sfid 수(0개·넘으면 bad_request)
FILE_MAX_BYTES = 16 * 1024 * 1024  # 파일 하나 원본 상한 — 넘으면 too_large
BATCH_MAX_BYTES = 24 * 1024 * 1024  # 한 번 합계 상한 — 차면 나머지 batch_full
FILE_TIMEOUT_SEC = 60  # 파일 하나 받기 시간 상한
