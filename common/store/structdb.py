"""로컬 정형 저장소(RDB) 연결 — EDW 대신 개발 PC·개발 서버에서 계약 연결 검토(X1/X1b, 요건 S37).
표: contract_master · client_master(열 이름 valid_env/unstructured/synth-edw/edw/edw_schema.sql과 동일) ·
   doc_contract_link(doc_key, contract_id, score, how, status 후보|확정, evidence_chunk_keys, created_at) ·
   doc_registry·doc_registry_seen(AD16 — 문서 대장. doc_key별 경로·이름·크기·수정 시각·ETag·처음/마지막 본 날·
   처리 상태·판 이력. common/registry.py가 기존 산출물(중복 확인 캐시·원본 위치 manifest·대표 결과 색인)을
   읽기만 해서 채운다 — 쓰기는 거기서만, 이 파일은 표만 선언).
접속: STRUCT_BACKEND=pg(기본 — 운영과 같은 PostgreSQL+pgvector 안 별도 스키마 struct, common/pg.py 재사용)
      |sqlite(PG 연결 안 되면 자동 대체, STRUCT_DB 기본 output/structured/edw_local.sqlite)
      |tsql(스텁 — 서버 EDW 추출본 연결 시 구현).
적재(modules/load/structured.py)·집계(modules/search/aggregate.py)가 함께 쓰는 연결·스키마만 — 업무 로직(CSV 파싱·연결 점수)은 없음.
10-14 함수별 분리(사용자) — 검색 MCP(mcp_server/services/search/aggregate.py)에서만 쓰는 find_table_row는 mcp_server/services/search/structdb.py로
옮김(로직 바이트 동일, find_table_cells·open_backend·StructDBError 등은 그대로 여기)."""

import re
import sqlite3
import sys
from pathlib import Path

from common.config.settings import cfg
from common.core.paths import LOCAL_RUN

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # deploy/common/(S3 — 옛 deploy/common_tools/, 깊이 같음) — CT1(10-16) store/ 한 단 더 깊어져 HERE.parent로(10-14 분리 — 옛 HERE.parent=deploy/data_pipeline/)
REPO_ROOT = (
    ROOT.parent if LOCAL_RUN else ROOT.parent.parent
)  # 저장소 루트(운영 DB 가드용) — 로컬 배치(paths.LOCAL_RUN — RUN_ENV=local, S7b 전 env LOCAL_RUN=1 · deploy/ 단 없음)면 한 단 덜 올라감
# FS5(10-08): data/ -> valid_env/sim — 다른 파이프라인의 운영 정본, 둘 다 열지도 쓰지도 않음(전환기 동안 구 경로도 같이 막음).
# 10-13: valid_env/sim/ -> valid_env/ (sim/ 단계 제거) — 새 위치 추가, 옛 두 경로도 계속 막음.
PROD_DBS = {
    (REPO_ROOT / "valid_env" / "structured" / "sales.sqlite").resolve(),
    (REPO_ROOT / "valid_env" / "sim" / "structured" / "sales.sqlite").resolve(),
    (REPO_ROOT / "data" / "structured" / "sales.sqlite").resolve(),
}

HOW_ID_WRITTEN = "계약 ID 기입"  # 문서에 계약 번호가 그대로 적혀 있던 경우(가장 강한 근거) — link·aggregate 공용
HOW_RDB_LOCATION = "RDB 문서 위치(doc_location)"  # doc_location.contract_id가 적힌 경우(본문보다 우선, AD45④) — link·aggregate 공용


def guard_not_prod(path):
    """운영 정본(valid_env/sim/structured/sales.sqlite, 구 data/ — 다른 파이프라인의 CLAUDE.md 가드 대상)은 절대 열지도 쓰지도 않는다."""
    if Path(path).resolve() in PROD_DBS:
        raise SystemExit(f"운영 DB 접근 금지: {Path(path).resolve()} — STRUCT_DB로 로컬 경로를 쓰세요")


def default_db():
    from common.core.paths import APP_ROOT

    return cfg().store.struct_db or str(APP_ROOT / "output" / "structured" / "edw_local.sqlite")


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
       )""",  # AD45①·④ — RDB 문서 위치 메타(valid_env/unstructured/synth-meta-rdb·synth-edw doc_location.csv와 같은 열)
)

# AD16 — 문서 대장. SCHEMA(위)와 일부러 분리: modules/load/structured.py의 load·link(와 그 selftest)가
# ensure_schema(SCHEMA)를 아무 게이트 없이 돈다 — 독립 검토 BLOCK(10-08) 지적대로, 거기 두면 STRUCT_BACKEND=pg
# 기본값(운영과 같은 PostgreSQL, 별도 struct 스키마)에서 흔한 적재 작업만으로 이 표 2개가 승인 없이 조용히
# 생긴다. doc_registry·doc_registry_seen은 ensure_registry_schema()로만 만들어지고, 그건 common/registry.py·
# DOC_REGISTRY(기본 켬, =0으로 끔)으로 게이트된 cli/registry.py에서만 부른다(아래 selftest가 SCHEMA에 이 표가 안 섞였는지 확인).
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
       )""",  # AD16 — 문서 대장(읽기 집계만, common/registry.py)
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
       )""",  # AD16 — doc_registry 판 이력(스냅숏이 전 build와 달랐을 때만 한 행 — "그 doc_key 역사" 조회용)
    """CREATE TABLE IF NOT EXISTS doc_hidden (
         doc_key   TEXT PRIMARY KEY,                           -- OP1 — 지금 숨김 상태만(이력은 안 쌓음 — ponytail: 여러 번 숨김/복구가
                                                                 -- 쌓이는 이력이 필요해지면 doc_registry_seen처럼 로그 표로 바꾸는 게 다음 단계)
         hidden     INTEGER NOT NULL,                           -- 1=숨김(검색 제외) · 0=복구
         reason     TEXT,                                       -- 왜(예: '원천에서 사라짐(자동 탐지)' · 사람이 적은 메모)
         by         TEXT,                                       -- 누가(예: 'registry:diff' · 사람 아이디) — 감사 기록
         at         TEXT NOT NULL                                -- 마지막 처리 시각(UTC)
       )""",  # OP1 — 숨김·복구(common/registry.py hide·unhide·hidden_set), 색인 행 삭제 없이 되돌릴 수 있게
)


# AD23 — 표 전 칸 DB 적재(doc_table·doc_cell). SCHEMA(위)와 일부러 분리 — REGISTRY_SCHEMA와 같은 이유(AD16 BLOCK
# 10-08 이력): modules/load/structured.py의 load·link(와 그 selftest)가 ensure_schema(SCHEMA)를 아무 게이트 없이
# 돈다 — 거기 두면 STRUCT_BACKEND=pg 기본값에서 흔한 적재 작업만으로 이 표 2개가 승인 없이 조용히 생긴다.
# ensure_table_schema()로만 만들어지고, 그건 modules/load/structured.py의 `tables` 명령(새 표 전용, load·link와
# 분리)에서만 부른다.
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


class SqliteBackend:
    """표준 라이브러리 sqlite3 — PG 연결이 안 될 때의 대체 백엔드(X1b)."""

    def __init__(self, path=None):
        path = path or default_db()
        guard_not_prod(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.cn = sqlite3.connect(path)
        self.cn.row_factory = sqlite3.Row
        self.path = path
        self.notes = []

    def execute(self, sql, params=()):
        self.cn.execute(sql, params)

    def executemany(self, sql, seq):
        if seq:
            self.cn.executemany(sql, seq)

    def query(self, sql, params=()):
        return [dict(r) for r in self.cn.execute(sql, params).fetchall()]

    def commit(self):
        self.cn.commit()

    def close(self):
        self.cn.close()


STRUCT_SCHEMA = "struct"  # 정형 표 전용 스키마명(고정) — 벡터용 PG_SCHEMA(기본 ai)와 분리
TABLE_PK = {
    "contract_master": "contract_id",
    "client_master": "company_id",
    "doc_contract_link": "doc_key",
    "doc_location": "doc_id",
    "doc_registry": "doc_key",
    "doc_hidden": "doc_key",
    "doc_table": "table_key",
}
# doc_registry_seen·doc_cell은 복합키(또는 키 없음) — INSERT OR REPLACE를 안 씀(doc_cell은 DELETE 뒤 평범한 INSERT, modules/load/structured.py)
_REPLACE_RE = re.compile(r"^INSERT OR REPLACE INTO (\w+) \(([^)]+)\)")


def _pg_sql(sql):
    """호출자(modules/load·search)는 sqlite 문법(? · INSERT OR REPLACE)을 그대로 쓴다 — PG 백엔드에서만 여기서 번역한다
    (? → %s · INSERT OR REPLACE → INSERT ... ON CONFLICT(기본키) DO UPDATE · 리터럴 %는 %%로 이스케이프). 호출자 쪽은 바꾸지 않음(X1b).
    ponytail: 문자열 리터럴을 구분하지 않는 전역 치환(토큰 파서 아님) — 지금 호출자 SQL엔 리터럴 ?·%가 없다는 전제. 생기면 sqlglot 등으로."""
    m = _REPLACE_RE.match(sql)
    if m:
        table, cols = m.group(1), [c.strip() for c in m.group(2).split(",")]
        pk = TABLE_PK[table]
        set_cols = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
        sql = _REPLACE_RE.sub(f"INSERT INTO {table} ({m.group(2)})", sql, count=1) + f" ON CONFLICT ({pk}) DO UPDATE SET {set_cols}"
    return sql.replace("%", "%%").replace("?", "%s")


class PgBackend:
    """PostgreSQL+pgvector(운영과 같은 DB, 별도 스키마 struct) — 기본 백엔드(X1b, 요건 S37). common/pg.py 접속 재사용.
    PG_SCHEMA는 벡터용(기본 ai)과 분리해 struct로 고정 — 표 이름은 그대로 두고 search_path로 스키마를 해석한다.
    commit()까지는 autocommit을 끄고 한 트랜잭션으로 묶는다(execute·executemany 여러 번 호출 뒤 commit() 한 번 —
    SqliteBackend·load_csv의 '여러 표 적재 후 한 번 commit' 패턴과 원자성을 맞춤, X1b 리뷰)."""

    def __init__(self, path=None):
        from common.store.pg import PG
        from common.store.pg import conf as pg_conf

        c = dict(pg_conf())
        c["PG_SCHEMA"] = STRUCT_SCHEMA
        self.db = PG(c)
        self.cn = self.db.cn
        try:
            with (
                self.cn.cursor() as cur
            ):  # S8a — CREATE SCHEMA 없앰(스키마·표는 migrate가 만듦 — 5-4, 사용자 10-28 Q6). 없으면 ensure_*가 알림
                cur.execute(f"SET search_path TO {STRUCT_SCHEMA}")
        except Exception:
            self.cn.close()  # 초기화 중간에 실패하면 연결을 남기지 않음(X1b 리뷰)
            raise
        self.notes = []

    def _begin(self):
        if self.cn.autocommit:
            self.cn.autocommit = False  # commit()·rollback() 전까지 한 트랜잭션

    def execute(self, sql, params=()):
        self._begin()
        with self.cn.cursor() as cur:
            cur.execute(_pg_sql(sql), params)

    def executemany(self, sql, seq):
        if seq:
            self._begin()
            with self.cn.cursor() as cur:
                cur.executemany(_pg_sql(sql), seq)

    def query(self, sql, params=()):
        with self.cn.cursor() as cur:
            cur.execute(_pg_sql(sql), params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def commit(self):
        if not self.cn.autocommit:
            self.cn.commit()
            self.cn.autocommit = True  # 다음 execute까지는 다시 기본값(읽기 전용 호출과 같게)

    def close(self):
        if not self.cn.autocommit:
            self.cn.rollback()  # commit() 안 한 변경은 버림(SQLite close-without-commit과 같게)
        self.cn.close()


class TsqlBackend:
    """T-SQL(EDW) 백엔드 스텁 — common/edwdb.py의 DB·conf()를 재사용해 연결하고 SCHEMA를 T-SQL 문법으로 바꾸면 된다
    (서버에 EDW 추출본이 연결되는 시점에 구현). 지금은 미구현 — sqlite만 지원."""

    def __init__(self, *a, **k):
        raise NotImplementedError("STRUCT_BACKEND=tsql 미구현 — common/edwdb.py 재사용 예정(서버 EDW 연결 시)")


MIGRATE_HINT = (
    "struct 표는 migrate로 만든다(S8a — 실행 중 DDL 없음): 이미지 `migrate up --target struct` · "
    "PC `python -m common.store.db.dbtool up --target struct`"
)


def _ddl_tables(stmts):
    """DDL 글자 묶음 → 표 이름들(순서대로)."""
    return [m.group(1) for s in stmts for m in [re.match(r"\s*CREATE TABLE IF NOT EXISTS (\w+)", s)] if m]


def _require_tables(db, stmts):
    """PostgreSQL — DDL 없이 표가 있는지만(S8a, 사용자 10-28 Q6). 없으면 StructDBError(호출자의 지금 실패 처리 그대로 — CLI는 종료 코드,
    publish는 문서 대장만 건너뜀, load_tables_db는 삼킴)."""
    have = {r["table_name"] for r in db.query("SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (STRUCT_SCHEMA,))}
    missing = [t for t in _ddl_tables(stmts) if t not in have]
    if missing:
        raise StructDBError(f"{STRUCT_SCHEMA} 스키마에 표 없음: {', '.join(missing)} — {MIGRATE_HINT}")


def ensure_schema(db):
    """PostgreSQL은 표가 있는지만 본다(S8a — 만드는 것은 migrate). SQLite 대체는 지금처럼 이 DDL로 만든다(5-4 — 판 관리 밖)."""
    if isinstance(db, PgBackend):
        return _require_tables(db, SCHEMA)
    for stmt in SCHEMA:
        db.execute(stmt)
    db.commit()


_REGISTRY_NEW_COLS = (
    ("rep_sha", "TEXT"),
    ("rep_pairs", "TEXT"),
    ("edition_of", "TEXT"),
    ("content_group", "TEXT"),
    ("value_changes", "TEXT"),
    ("source_keys", "TEXT"),
    ("fail_count", "INTEGER"),
)  # AD17②·AD15(10-08) · source_keys는
# engine-qa MAJOR 반영(10-08 2차) · fail_count는 DET1 Fix2(10-12) — 기존 doc_registry(이미
# 있는 DB 파일)엔 CREATE TABLE이 안 돌아 없으므로 ALTER TABLE로 보강


def _registry_has_col(db, col):
    """ALTER TABLE 전 열이 이미 있는지 먼저 물어보기만(ALTER를 실행해 예외로 판단하지 않음) — PG는 실패한 ALTER가
    트랜잭션을 abort 상태로 만들어 그 뒤 commit()까지 모든 execute가 깨진다(SQLite는 영향 없지만 PG 기준으로 안전한
    쪽을 고름). 조회 자체가 실패하면(권한 등) False — 그 열을 추가하려다 실패해도 ensure_registry_schema()는 멈추지 않음."""
    try:
        if isinstance(db, SqliteBackend):
            return any(r["name"] == col for r in db.query("PRAGMA table_info(doc_registry)"))
        return bool(db.query(f"SELECT column_name FROM information_schema.columns WHERE table_name='doc_registry' AND column_name='{col}'"))
    except Exception:
        return False


def ensure_registry_schema(db):
    """AD16/OP1 — doc_registry·doc_registry_seen·doc_hidden만. ensure_schema()와 따로 불러야 함(독립 검토 BLOCK
    10-08) — 호출자는 common/registry.py(build())·DOC_REGISTRY(기본 켬, =0으로 끔)으로 게이트된 cli/registry.py
    (hide·unhide·build·show·diff)·cli/publish_parse.py(--apply에서 registry.build() 전에)뿐, modules/load/
    structured.py는 안 부름.
    AD17②·AD15(10-08) — rep_sha·rep_pairs·edition_of·content_group·value_changes·source_keys는 CREATE TABLE(위)에
    이미 있지만, 이 기능 전에 만들어진 기존 doc_registry(이미 존재하는 DB 파일)엔 없다 — 먼저 있는지 물어보고
    없는 것만 ALTER TABLE로 보강(_registry_has_col — 실패한 ALTER로 판단하면 PG 트랜잭션이 깨짐).
    S8a(사용자 10-28 Q6) — PostgreSQL은 표가 있는지만 본다(만들기·칸 보강은 migrate 기준판 — 7칸은 CREATE TABLE에 이미 있음). ALTER 보강은
    SQLite 옛 파일에만 남는다."""
    if isinstance(db, PgBackend):
        return _require_tables(db, REGISTRY_SCHEMA)
    for stmt in REGISTRY_SCHEMA:
        db.execute(stmt)
    for col, typ in _REGISTRY_NEW_COLS:
        if not _registry_has_col(db, col):
            try:
                db.execute(f"ALTER TABLE doc_registry ADD COLUMN {col} {typ}")
            except Exception:
                pass
    db.commit()


def ensure_table_schema(db):
    """AD23 — doc_table·doc_cell만(REGISTRY_SCHEMA와 같은 패턴). ensure_schema()와 따로 불러야 함 —
    호출자는 modules/load/structured.py의 `tables` 명령뿐, load·link는 안 부름(아래 selftest가 SCHEMA에
    이 표가 안 섞였는지 확인). S8a — PostgreSQL은 표가 있는지만(만들기는 migrate)."""
    if isinstance(db, PgBackend):
        return _require_tables(db, TABLE_SCHEMA)
    for stmt in TABLE_SCHEMA:
        db.execute(stmt)
    db.commit()


def find_table_cells(db, text, limit=20):
    """AD23 leftover — 표 칸 조회 1개, modules/load(적재)·modules/search(집계) 공용(모듈 경계 ①상 서로
    import 못 해 연결·스키마가 모인 이 파일에 둠, structdb.py 모듈 docstring과 같은 이유). 값 또는 머리글이
    text와 정규화 후 정확히 같은 칸을 표·문서와 함께 돌려준다(안정 정렬: doc_key·table_id·row_idx·col_idx).
    engine-qa BLOCK②(10-11) — 전엔 LIKE %text%(부분 일치)라 다른 문서의 우연히 겹치는 부분 글자에도 걸려
    aggregate.table_cell_list()가 틀린 문서를 답으로 돌려줄 위험이 있었음 → 정확히 같을 때만(부분 일치 없음).
    doc_table·doc_cell이 없으면(tables 명령을 아직 안 돌림) 빈 목록(에러 아님 — doc_contract_link 없음과 같은 패턴)."""
    from common.core.text import normalize_value

    needle = normalize_value(text)
    if not needle:
        return []
    try:
        rows = db.query(
            "SELECT c.table_key, c.row_idx, c.col_idx, c.col_label, c.value, t.doc_key, t.table_id, t.page "
            "FROM doc_cell c JOIN doc_table t ON c.table_key = t.table_key "
            "WHERE c.value_norm = ?",
            (needle,),
        )
    except Exception:
        return []
    rows.sort(key=lambda r: (r["doc_key"], r["table_id"], r["row_idx"], r["col_idx"]))
    return rows[:limit]


class StructDBError(RuntimeError):
    """정형 저장소 연결 실패 — SystemExit과 달리 서버 프로세스(mcp_server 등 장수 프로세스)를 죽이지 않는다(X1b 리뷰).
    CLI(structured.py --selftest 아닌 load·link 등)만 이걸 받아 종료 코드로 바꾼다."""


def open_backend(db_path=None):
    """STRUCT_BACKEND=pg(기본)|sqlite|tsql → 연결 객체(쓰기는 commit() 필요).
    pg 연결이 안 되면(PG_PASSWORD 없음·연결 거부 등) SQLite(db_path 또는 STRUCT_DB)로 자동 대체하고 db.notes에 표시(X1b) —
    단 RUN_MODE=prod(cli/pipeline.py와 같은 환경변수)면 대체하지 않고 StructDBError로 알린다(운영에서 조용히 SQLite로
    떨어지면 안 됨 — SystemExit이 아닌 이유는 mcp_server 같은 장수 프로세스를 호출자가 죽이지 않고 잡아 처리할 수 있어야 해서)."""
    st = cfg().store  # S7b — 설정 객체
    backend = st.struct_backend  # 옛 get("STRUCT_BACKEND", "pg") — 칸 기본 'pg', ''이면 ''(blank keep — 알 수 없음 오류, VS7b R-11)
    if backend == "sqlite":
        return SqliteBackend(db_path)
    if backend == "tsql":
        return TsqlBackend()
    if backend == "pg":
        try:
            return PgBackend()
        except (
            Exception,
            SystemExit,
        ) as e:  # common/pg.py conf()는 PG_PASSWORD 없음 등을 SystemExit로 알림 — 여기선 StructDBError로 바꿔 처리
            if cfg().store.run_mode == "prod":
                raise StructDBError(f"RUN_MODE=prod — PG 연결 실패 시 SQLite로 조용히 대체하지 않음: {type(e).__name__}: {e}") from e
            note = "정형 저장소: PG 연결 안 됨 → SQLite 대체"
            sys.stderr.write(f"[structdb] {note}({type(e).__name__}: {e})\n")
            db = SqliteBackend(db_path)
            db.notes = [note]
            return db
    raise StructDBError(f"STRUCT_BACKEND 알 수 없음: {backend}(pg|sqlite|tsql)")
