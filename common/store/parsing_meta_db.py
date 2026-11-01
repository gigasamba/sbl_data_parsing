"""EDW `AI.ParsingMeta` 저장소 클래스(읽기·쓰기) — modules/load/parsing_meta.py(SI39 publish, 쓰기 쪽 사람·설계는
그 모듈 docstring)·modules/search/mcp_server.py(OP21 근거 '파싱 결과 경로' 조회, 읽기만) 공용. 모듈 경계 규칙①
(cli/check_modules.py — modules/<x>는 다른 modules/<y>를 import 못 함, 함께 쓸 것은 common/만)이라 여기로
승격했다 — modules/load/parsing_meta.py는 이 파일에서 그대로 다시 import해 쓴다(동작 바이트 동일, 이름만 공용
자리로 옮김). 표 DDL·열 순서 설계는 docs/architecture.md §2.
"""

import datetime
import re
import sqlite3
import sys

from common.config import layout as L
from common.config.settings import cfg

DEFAULT_TABLE = "AI.ParsingMeta"
TABLE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")  # source.py TABLE_ID_RE와 같은 규칙(SQL 삽입 방지)
# C10(사용자 10-31 · skipped_dup 11-01 — 완전 중복은 매일 밤 다시 안 고름) — 이 parse_status 행이 있으면 "파싱 끝난 문서"
# (not_parsed·skipped_disk_cap·실패는 다시 고름 · 통째 실패는 ParsingMeta에 안 씀 — C3)
DONE_STATUSES = ("ok", "partial", "skipped_dup")
# 열 순서 — EDW DDL docs/operations/parsing_meta_mssql.sql과 같음(parse_meta_id·parsed_at·source_key_hash는 표가 자동으로 채움, test_parsing_meta_ddl.py가 고정)
# PM2(10-15, 사용자) — 열·키를 최소로: doc_key(원본 sha256)만 필수, 그 밖은 전부 비어도 됨. engines_used·
# engines_summary는 맨 끝에 더함(기존 열 자리는 안 바꿔 디프를 작게).
COLUMNS = (
    "source_system",
    "source_key",
    "source_uri",
    "original_filename",
    "file_format",
    "file_size",
    "sha256",
    "rep_bucket",
    "rep_key",
    "rep_etag",
    "parse_status",
    "status_reason",
    "rep_engine",
    "rep_acc",
    "page_count",
    "doc_key",
    "parse_date",
    "pipeline_version",
    "status",
    "status_at",
    "engines_used",
    "engines_summary",
)
KEY = ("source_system", "source_key")  # SI39② — source_key가 있을 때의 겹침/건너뜀 키(이름이 아니라 원본 전체 키).
# PM2 — source_key가 없으면(요건 "최소 키") doc_key 하나로 대신(_insert_new_rows).
_SQLITE_TYPE = {"file_size": "INTEGER", "page_count": "INTEGER", "rep_acc": "REAL"}
# 독립 검토 CONCERN(10-15) — 필터(WHERE) 유일 색인이 있는 표에 쓰는 모든 세션은 이 7개 SET 옵션이 전부 DDL과
# 같은 값이어야 한다(하나라도 어긋나면 SQL Server가 INSERT/UPDATE를 거부) — parsing_meta_mssql.sql 맨 앞과
# 똑같은 값, 연결마다 한 번(MssqlStore.__init__, 그 밖 INSERT·SELECT보다 먼저).
SET_OPTIONS_SQL = (
    "SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON; SET ANSI_PADDING ON; SET ANSI_WARNINGS ON; "
    "SET CONCAT_NULL_YIELDS_NULL ON; SET ARITHABORT ON; SET NUMERIC_ROUNDABORT OFF;"
)


def _today_date():
    """PM2 — parse_date 기본값(처리 시각) — pipeline.load.parsing_meta.today()와 같은 글자 형식
    ('YYYY-MM-DD_HHMMSS', 파일 이름에도 쓰여 콜론 없음). 그 모듈을 여기서 import하면 common→pipeline
    역방향 import가 돼 모듈 경계를 어기므로 같은 한 줄 형식을 이 안에 둔다(중복은 이 한 줄뿐)."""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _insert_new_rows(cur, table, ph, rows, integrity_error, columns=None):
    """rows 전부를 같은 트랜잭션 안에서 — KEY(source_system, source_key)가 이미 있으면(또는 PM2 — source_key가
    없으면 doc_key 하나) 그 행은 건너뜀(SI39④: UPDATE·MERGE 없음, INSERT만) — 단, row["_reparse"]가 참이면
    (사람이 명시한 재파싱) 이 사전 확인을 건너뛰어 새 parse_date로 그대로 INSERT한다(그 행의 rep_key·parse_date는
    apply()가 이미 새 날짜로 바꿔 둠).
    동시 실행 경합으로 그 사이 다른 프로세스가 같은 키(+parse_date)를 먼저 넣었으면 INSERT 자체가 UNIQUE
    위반(integrity_error)으로 실패할 수 있다 — 그것도 "건너뜀"으로 세고 배치 전체는 중단하지 않는다(독립 검토
    MAJOR-2 선례). 테이블·열 이름은 상수·화이트리스트만 SQL에 끼워 넣고 값은 전부 파라미터 바인딩.
    columns — 실제 INSERT에 쓸 열 목록(None=COLUMNS 전부). MssqlStore가 옛 표(PM2 DDL을 아직 안 돌린 EDW)에
    새 열이 없으면 이 목록을 줄여 와 그 열 없이도 INSERT가 깨지지 않게(요건 "DDL 미실행이어도 안 죽음")."""
    cols_list = list(columns) if columns is not None else list(COLUMNS)
    inserted = skipped = 0
    for row in rows:
        row = {
            **row,
            "source_system": row.get("source_system") or "unknown",  # PM2 요건(a) — 빈 값은 'unknown'
            "parse_date": row.get("parse_date") or _today_date(),
        }  # PM2 요건(a) — 비었으면 처리 시각
        if not row.get("_reparse"):
            if row.get("source_key") is not None:
                cur.execute(f"SELECT 1 FROM {table} WHERE source_system={ph} AND source_key={ph}", tuple(row[k] for k in KEY))
            else:  # PM2 — source_key 없음(최소 키) → doc_key로 대신 확인
                cur.execute(f"SELECT 1 FROM {table} WHERE doc_key={ph} AND source_key IS NULL", (row["doc_key"],))
            if cur.fetchone() is not None:
                skipped += 1
                continue
        cols = ",".join(cols_list)
        phs = ",".join([ph] * len(cols_list))
        try:
            cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({phs})", tuple(row.get(c) for c in cols_list))
        except integrity_error:
            skipped += 1  # 동시 실행 경합 — SELECT 뒤·INSERT 전 사이에 다른 프로세스가 같은 키를 먼저 넣음
            continue
        inserted += 1
    return inserted, skipped


def _find_by_source_rows(cur, table, ph, source_key):
    """원본 키(source_key = 원본 전체 경로)의 EDW 행 — 읽기만(SELECT). 적재가 gold doc에 대표 결과 위치를 복사할 때 쓴다(C8 — mc-15)."""
    cur.execute(
        f"SELECT source_system, source_key, parse_date, status, rep_bucket, rep_key, parsed_at FROM {table} WHERE source_key={ph}",
        (source_key,),
    )
    cols = ["source_system", "source_key", "parse_date", "status", "rep_bucket", "rep_key", "parsed_at"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _done_keys_rows(cur, table):
    """C10(pl-12, 사용자 10-31) — 파싱이 끝난 원본 키(source_key) 집합 — parse_status가 DONE_STATUSES(ok·partial·skipped_dup — 사용자 11-01)인 행만.
    파싱 입구(pipeline.cli `_unparsed`)가 "FileStorageMap ∖ ParsingMeta"로 새 문서를 고를 때 쓴다(읽기만, SELECT).
    상수 글자만 SQL에 끼우고(DONE_STATUSES는 코드 상수) 값 바인딩은 없음."""
    done = ", ".join(f"'{v}'" for v in DONE_STATUSES)
    cur.execute(f"SELECT DISTINCT source_key FROM {table} WHERE source_key IS NOT NULL AND parse_status IN ({done})")
    return {r[0] for r in cur.fetchall()}


def find_rep(db, source_system, source_key):
    """C8(mc-15, 11-01) — 적재 때 gold doc에 복사할 대표 결과 위치: {rep_bucket, rep_key, parsed_at} 또는 None.
    연결 키는 source_system + source_key(사용자 11-01). 같은 원본이 재파싱으로 여러 행이면 status='active'인 것 중(없으면 전체 중)
    parse_date가 가장 늦은 행. source_system이 맞는 행이 없으면 source_key만 맞는 행(게시가 원천 이름을 다르게 적은 옛 행) — ponytail:
    원천 표기가 하나로 정리되면(pl-28) 이 대체를 뺀다. rep_bucket·rep_key가 비면 None. 조회 예외는 호출부가 처리."""
    rows = db.find_by_source(source_key)
    same = [r for r in rows if r.get("source_system") == source_system]
    rows = same or (rows if len({r.get("source_system") for r in rows}) == 1 else [])  # 다른 원천끼리 이름이 겹치면 대체하지 않음
    if not rows:
        return None
    active = [r for r in rows if r.get("status") == "active"]
    pick = max(active or rows, key=lambda r: r.get("parse_date") or "")
    if not pick.get("rep_bucket") or not pick.get("rep_key"):
        return None
    return {"rep_bucket": pick["rep_bucket"], "rep_key": pick["rep_key"], "parsed_at": pick.get("parsed_at")}


class MssqlStore:
    """실제 EDW 쓰기(PM1 결정 뒤) — PM_TABLE은 화이트리스트 확인(스키마.표만), 열 이름은 고정 상수, 값은 전부 %s
    파라미터. 접속은 common.connections.rdb — 게시는 쓰기 계정, 조회(검색 MCP)는 읽기 계정(role, 사용자 10-29 ops.md#op-03). 한 실행 = 한 트랜잭션(커밋 전엔 아무것도 안 남음).
    KEY(source_system, source_key)가 이미 있으면(PM2 — 없으면 doc_key) 그 행은 건너뜀(INSERT만 — UPDATE 없음, C10 10-31에
    문서 대장과 함께 상태 열 UPDATE 길도 지움).
    PM2 하위 호환 — DBA가 새 DDL을 아직 안 돌려 옛 표(engines_used·engines_summary 없음, 그 밖은 PM1 그대로)에
    쓰게 되더라도 INSERT가 죽지 않게: 첫 호출에서 INFORMATION_SCHEMA.COLUMNS로 실제 있는 열만 추려 그 열만
    INSERT하고(없는 열은 조용히 비움), 한 번 경고를 남긴다(요건 "DDL 미실행이어도 안 죽음").
    독립 검토 CONCERN(10-15) — 필터 유일 색인이 있는 표라 연결 직후(그 밖 어떤 INSERT·SELECT보다 먼저) SET_OPTIONS_SQL을
    이 세션에 실행한다(parsing_meta_mssql.sql 맨 앞과 같은 7개 옵션) — 안 하면 SQL Server가 그 뒤 모든 쓰기를 거부한다."""

    def __init__(self, table, role):
        if not TABLE_ID_RE.match(table):
            raise ValueError(f"[parsing_meta] PM_TABLE 값이 올바르지 않음(영문·숫자·_, 스키마.표만) — {table!r}")
        self.ident = ".".join(f"[{p}]" for p in table.split("."))
        self.schema, self.table_name = table.split(".", 1) if "." in table else (None, table)
        self._cols = None  # 지연 조회(_available_columns) — 연결하자마자 바로 안 봄, 첫 insert_new에서만
        from common.store import (
            mssql,
        )  # S8b(5-4) — SQLAlchemy가 연 연결(인자 그대로) · 쓰기 도우미가 SQLite 대역과 같은 DBAPI 커서 코드라 커서 그대로

        kw, miss = mssql.login(role)
        if miss:  # 옛 os.environ[name] — 없으면 KeyError
            raise KeyError(miss[0])
        # 독립 검토 CONCERN — SET_OPTIONS_SQL은 이 세션의 첫 실행문(INSERT·SELECT보다 먼저, commit) — mssql.engine의 연결 생성 자리에서
        self.cn = mssql.raw(SET_OPTIONS_SQL, autocommit=False, **kw)

    def _available_columns(self, cur):
        """PM2 — COLUMNS 중 지금 EDW 표에 실제 있는 것만(한 연결에 한 번만 조회, 결과 캐시). 없는 열이 있으면
        한 번 경고(어떤 열이 빠졌는지)만 찍고 그 열 없이 INSERT를 계속한다 — 표를 바꾸거나 죽지 않음."""
        if self._cols is None:
            if self.schema:
                cur.execute(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (self.schema, self.table_name),
                )
            else:
                cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=%s", (self.table_name,))
            found = {r[0] for r in cur.fetchall()}
            self._cols = [c for c in COLUMNS if c in found]
            missing = [c for c in COLUMNS if c not in found]
            if missing:
                print(f"[parsing_meta] 경고 — EDW 표에 없는 열(PM2 새 DDL 미실행?) {missing} — 그 열은 비우고 INSERT", file=sys.stderr)
        return self._cols

    def insert_new(self, rows):
        import pymssql

        cur = self.cn.cursor()
        try:
            cols = self._available_columns(cur)
            counts = _insert_new_rows(cur, self.ident, "%s", rows, pymssql.IntegrityError, columns=cols)
            self.cn.commit()
            return counts
        except Exception:
            self.cn.rollback()
            raise

    def find_by_source(self, source_key):
        return _find_by_source_rows(self.cn.cursor(), self.ident, "%s", source_key)

    def done_source_keys(self):
        return _done_keys_rows(self.cn.cursor(), self.ident)

    def close(self):
        self.cn.close()


class SqliteStore:
    """가짜 EDW(RDB_SQLITE=<경로> — common.connections.rdb.sqlite) — L2 시험용. 실제 표와 같은 열(설계 §2) · 표 이름은 고정 ParsingMeta(시험 전용이라
    PM_TABLE 임의값을 SQLite 식별자로 안 씀). KEY(source_system, source_key)가 이미 있으면(PM2 — 없으면 doc_key)
    그 행은 건너뜀(INSERT만). PM2 — doc_key만 필수(NOT NULL), 그 밖은 전부 NULL 허용 · 고유 키는 MSSQL DDL과
    같은 두 필터 색인(source_key 있으면 (source_system, source_key, parse_date), 없으면 (doc_key, parse_date))."""

    def __init__(self, path, table="ParsingMeta", readonly=False):
        self.table = table
        if readonly:  # 검색 MCP 조회(role "read") — ?mode=ro로 열고 표·색인을 만들지 않음(대역 파일을 바꾸지 않게 — 독립 검토 10-29)
            from common.store import mssql

            self.cn = mssql.standin(path)
            return
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)  # RDB_SQLITE=/app/output/pm_test/edw.sqlite처럼 새 폴더여도(샘플 세션 10-08)
        self.cn = sqlite3.connect(path)
        cols_sql = ", ".join(f"{c} {_SQLITE_TYPE.get(c, 'TEXT')}" + (" NOT NULL" if c == "doc_key" else "") for c in COLUMNS)
        self.cn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (parse_meta_id INTEGER PRIMARY KEY AUTOINCREMENT, {cols_sql}, "
            f"parsed_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        self.cn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_key ON {table}(source_system, source_key, parse_date) "
            f"WHERE source_key IS NOT NULL"
        )
        self.cn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_dockey ON {table}(doc_key, parse_date) WHERE source_key IS NULL")

    def insert_new(self, rows):
        cur = self.cn.cursor()
        counts = _insert_new_rows(cur, self.table, "?", rows, sqlite3.IntegrityError)
        self.cn.commit()
        return counts

    def find_by_source(self, source_key):
        return _find_by_source_rows(self.cn.cursor(), self.table, "?", source_key)

    def done_source_keys(self):
        return _done_keys_rows(self.cn.cursor(), self.table)

    def count(self):
        return self.cn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0]

    def close(self):
        self.cn.close()


def make_db(role):
    """ParsingMeta 저장소 — role: 게시(파이프라인)는 "write", 조회(검색 MCP)는 "read"(사용자 10-29 — ops.md#op-03)."""
    from common.store import mssql

    sqlite_path = mssql.standin_path()
    if sqlite_path:
        return SqliteStore(sqlite_path, readonly=role == "read")
    table = cfg().connections.parsing_meta.table  # 기본 'AI.ParsingMeta'(DEFAULT_TABLE과 같음) · 빈 값 그대로(blank=keep)
    _, miss = mssql.login(role, extra=False)
    if miss:
        raise SystemExit(
            f"[parsing_meta] EDW 접속 정보 없음: {', '.join(miss)}(settings.yaml {L.to_yaml('common.connections.rdb.host').rsplit('.', 1)[0]}.*) 또는 RDB_SQLITE(시험)"
        )
    return MssqlStore(table, role)
