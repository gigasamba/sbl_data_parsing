"""struct 스키마 기준판(S8a, 5-4 — 사용자 10-28 Q2 a): 옛 `common/store/structdb.py` 파이썬 문자열 DDL 글자 그대로 — SCHEMA(옛
ensure_schema)·REGISTRY_SCHEMA(옛 ensure_registry_schema)·TABLE_SCHEMA(옛 ensure_table_schema). 옛 코드가 실행 중 ALTER로 보강하던
doc_registry 7칸(rep_sha…fail_count)은 이 CREATE TABLE에 들어 있어 새 표에는 있고, 옛 서버 표는 옛 코드가 매번 보강해 이미 있다 — 그래도 빠진
표면 비교가 "칸 없음"(거부)으로 보이고 사람이 DB 담당과 정한다(이 판은 ALTER를 하지 않음 — 사용자 10-28 Q6). 옛 PgBackend처럼 search_path를 struct로 두고 돌린다. 표 10개를 한 판에(AD16·AD23 묶음별 게이트는 명시적 migrate로 대체).
이미 있는 스키마는 IF NOT EXISTS라 없는 표·색인만 생긴다(dbtool이 먼저 비교 — Q3). 한 번 배포한 판은 고치지 않는다."""

from alembic import context, op

revision = "0001_struct"
down_revision = None
branch_labels = ("struct",)
depends_on = None

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS contract_master (
         contract_id        TEXT PRIMARY KEY,
         company             TEXT NOT NULL,
         company_id          TEXT NOT NULL,
         product_code        TEXT NOT NULL,
         modality             TEXT NOT NULL,
         site                   TEXT NOT NULL,
         line_id               TEXT,
         batches_contracted  INTEGER NOT NULL,
         contract_value_usd  INTEGER NOT NULL,
         currency              TEXT NOT NULL,
         term_months          INTEGER NOT NULL,
         signed_on            TEXT NOT NULL,
         start_date           TEXT NOT NULL,
         end_date             TEXT NOT NULL,
         status                 TEXT NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS client_master (
         company_id TEXT PRIMARY KEY,
         company     TEXT NOT NULL,
         aliases      TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS prod_master (
         prod_code TEXT,
         division   TEXT,
         prod_name  TEXT,
         pjt_name   TEXT,
         client_code TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS doc_contract_link (
         doc_key              TEXT PRIMARY KEY,
         contract_id          TEXT,
         score                 INTEGER,
         how                    TEXT,
         status                 TEXT,
         evidence_chunk_keys  TEXT,
         created_at            TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS doc_location (
         doc_id              TEXT PRIMARY KEY,
         bucket               TEXT,
         object_key           TEXT,
         etag                  TEXT,
         size_bytes           INTEGER,
         content_type         TEXT,
         company_id           TEXT,
         doc_type              TEXT,
         contract_id          TEXT,
         version               INTEGER,
         supersedes_doc_id    TEXT,
         language              TEXT,
         received_at          TEXT,
         updated_at           TEXT,
         is_deleted           INTEGER
       )""",
)

REGISTRY_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS doc_registry (
         doc_key      TEXT PRIMARY KEY,                        -- 원본 내용 sha256(common/ids.py doc_key)
         names         TEXT,                                    -- 이 doc_key로 관측된 경로·파일명 전부(JSON 배열, 정렬)
         size           INTEGER,
         mtime          TEXT,                                    -- 원본 수정 시각(로컬 mtime) 또는 LastModified/updated_at(RDB·S3) — 그대로 문자열 보존
         etag           TEXT,
         status         TEXT,                                    -- seen(관측만) · parsed · failed · deleted — 가장 최근 build의 판정(AD17 전 — 파싱 결정에는 안 씀)
         source         TEXT,                                    -- local(dedup만 돈 원본) · rdb(manifest.jsonl에 doc_id 있음) · s3(그 밖 Object Storage)
         doc_id         TEXT,                                    -- RDB 원천 키(예: FileStorageMap.id), 있으면
         version        TEXT,                                    -- RDB 판(version · content_version_id), 있으면
         first_seen     TEXT NOT NULL,
         last_seen      TEXT NOT NULL,
         last_build     TEXT NOT NULL,                           -- 마지막으로 이 행을 손댄 build_id(doc_registry_seen과 연결)
         rep_sha        TEXT,                                    -- AD17②·AD15(10-08) — 대표 결과 본문(정규화, common.core.text.normalize_value) sha256.
                                                                    -- _rep 파일이 나중에(재파싱으로) 덮여도 '이전 판' 비교 재료로 남게 common/registry.py가 보존
         rep_pairs      TEXT,                                    -- AD17② — 그 판의 (라벨,값,쪽) 목록(JSON) — 숫자만 바뀐 판의 '바뀐 값' 재료(위와 같은 이유로 보존)
         edition_of     TEXT,                                    -- AD17② — 이 doc_key가 바이트는 다르지만 대표 글이 같거나(same) 숫자만 다른(changed_values)
                                                                    -- 전 판일 때 그 전 doc_key(NULL=독립 문서 또는 글 자체가 다른 새 판)
         content_group  TEXT,                                    -- AD15 — 대표 글이 같은(형식만 다른 .eml↔.msg·PDF↔Word 포함) doc_key 묶음 id(그룹 안 최초 문서의
                                                                    -- doc_key, NULL=미묶음) — 지우지 않음, 검색 중복 줄이기 표시용
         value_changes  TEXT,                                    -- AD17② — edition_of가 changed_values일 때 바뀐 값 목록(JSON [{label,before,after,page}])
         source_keys    TEXT,                                    -- AD17②(engine-qa MAJOR 10-08) — "names"(파일 이름만)와 달리 원본 전체 키·경로를
                                                                    -- 담은 JSON 배열("source_system::원본 전체 키", SI39 겹침 키와 같은 모양) —
                                                                    -- link_editions()가 전 판을 찾을 때 이름이 아니라 이 칸만 본다(다른 고객·폴더의
                                                                    -- 같은 이름 파일이 엉뚱하게 이어지는 것 방지)
         fail_count     INTEGER                                  -- DET1 Fix2 — 연속으로 파싱 실패한 야간 재시도 횟수(apply()가 매 build 갱신:
                                                                    -- status='parsed'면 0, changed면 새 시작으로 0, 그 밖(파싱 안 됨)이면 +1) —
                                                                    -- nightly_plan()이 REGISTRY_RETRY_MAX를 넘으면 그 doc_key를 재시도 대상에서 뺌
       )""",
    """CREATE TABLE IF NOT EXISTS doc_registry_seen (
         doc_key   TEXT NOT NULL,
         build_id  TEXT NOT NULL,
         names      TEXT,
         size       INTEGER,
         mtime      TEXT,
         etag       TEXT,
         status     TEXT,
         source     TEXT,
         seen_at    TEXT NOT NULL,
         PRIMARY KEY (doc_key, build_id)
       )""",
    """CREATE TABLE IF NOT EXISTS doc_hidden (
         doc_key   TEXT PRIMARY KEY,                           -- OP1 — 지금 숨김 상태만(이력은 안 쌓음 — ponytail: 여러 번 숨김/복구가
                                                                 -- 쌓이는 이력이 필요해지면 doc_registry_seen처럼 로그 표로 바꾸는 게 다음 단계)
         hidden     INTEGER NOT NULL,                           -- 1=숨김(검색 제외) · 0=복구
         reason     TEXT,                                       -- 왜(예: '원천에서 사라짐(자동 탐지)' · 사람이 적은 메모)
         by         TEXT,                                       -- 누가(예: 'registry:diff' · 사람 아이디) — 감사 기록
         at         TEXT NOT NULL                                -- 마지막 처리 시각(UTC)
       )""",
)

TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS doc_table (
         table_key      TEXT PRIMARY KEY,                        -- doc_key:표id(tables_std[i].id, 예 't0')
         doc_key          TEXT NOT NULL,
         table_id          TEXT NOT NULL,
         page               INTEGER,
         source_engine     TEXT,
         n_rows            INTEGER,
         n_cols            INTEGER,
         header_json       TEXT,                                   -- tables_std[].header 그대로(JSON 배열)
         merged_json       TEXT,                                   -- tables_std[].merged 그대로(JSON 배열)
         created_at        TEXT NOT NULL
       )""",
    """CREATE TABLE IF NOT EXISTS doc_cell (
         table_key  TEXT NOT NULL,                                -- doc_table.table_key
         row_idx     INTEGER NOT NULL,                             -- 0=머리글 행, 1..N=본문 행(header·rows 순서 그대로)
         col_idx     INTEGER NOT NULL,
         col_label   TEXT,                                          -- 그 칸의 머리글(header_json[col_idx], 머리글 행 자신은 자기 값)
         value        TEXT,
         value_norm  TEXT                                           -- common.core.text.normalize_value(value) — 조회용(공백·대소문자 무시)
       )""",
    "CREATE INDEX IF NOT EXISTS idx_doc_cell_table ON doc_cell(table_key)",
    "CREATE INDEX IF NOT EXISTS idx_doc_cell_value ON doc_cell(value_norm)",
)


def upgrade():
    s = context.config.attributes["schema"]
    bind = op.get_bind()
    bind.exec_driver_sql(
        f"SET LOCAL search_path TO {s}"
    )  # 옛 PgBackend: SET search_path TO struct 뒤 이름만 쓴 DDL(판 표는 스키마를 붙여 씀)
    for stmt in SCHEMA + REGISTRY_SCHEMA + TABLE_SCHEMA:
        bind.exec_driver_sql(stmt)


def downgrade():
    raise NotImplementedError("기준판은 되돌리지 않음 — 스키마를 지우려면 사람이(DB 담당 협의)")
