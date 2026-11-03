"""search 응답 모양(MCP 계약 — 운영 05 §2.3·§2.4, mc-16 11-01·pl-52 11-03): 맨 위 5칸·근거 13칸·거르기 이름. 바꾸면 계약이 바뀐다(등급 A).
S5(10-26)에 mcp_server/main.py에서 옮김 · 11-01(mc-16) 운영 계약으로 줄임 — 옛 근거 칸(chunk_id·doc_key·source_uri·bbox·score·via·
rank·image_ids·doc_summary·AD44 manifest 칸·rep_uri)과 맨 위 subs·store·methods·images·notes·ms·index_id를 뺐다.
"""

# 맨 위 — filter·scope_docs는 거르기를 하나라도 줬을 때만
SEARCH_TOP_KEYS = ("question", "evidence", "evidence_status", "filter", "scope_docs")

# 근거 한 건 — 늘 13칸 모두(값이 없으면 null). attrs = 원천 메타 {키: 값}(사슬 파일에서 evidence: true인 키 모두 — 없으면 null, pl-52)
EVIDENCE_KEYS = (
    "text",
    "file_name",
    "file_path",
    "page",
    "line",
    "section",
    "client",
    "contract_no",
    "doc_date",
    "version",
    "superseded",
    "chunk_key",
    "attrs",
)

# 거르기 14칸(운영 이름 그대로 — FAQ_group 대문자 포함). client_like는 client와 함께만 뜻이 있다. attrs = {attrs 키: 값 또는 목록}(pl-52 —
# 원천마다 사슬 파일의 filter 있는 키 · 모르는 키는 오류). 옛 이름(project_id…contract_id)은 사슬의 filter로 attrs 키에 이어짐.
SEARCH_FILTERS = (
    "source_system",
    "client",
    "client_like",
    "project_id",
    "division",
    "service_type",
    "FAQ_group",
    "doc_class",
    "sf_op_id",
    "sf_op_name",
    "contract_id",
    "created_since",
    "created_until",
    "attrs",
)

K_DEFAULT, K_MAX = 8, 50  # k 기본·상한(넘으면 50으로 줄임 — 오류 아님)
