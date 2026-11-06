"""끝난 문서 판정(op-17) — 처리 기록은 pgvector 원천 스키마(5벌 + 있는 DEV 원천 `_dev_<n>`)의 `doc` 표(판 0006)에 있다(EDW ParsingMeta 아님).
끝난 문서 = 원천 스키마 어디든 `doc` 행이 있는 원본 키(`file_path`) · 내용 중복 = 다른 원본 키의 `doc.sha256`이 같음.
고르기(candidate_pick·candidate_ready)와 게시(publish_parse_result — 이미 끝난 문서는 올리지 않음)가 읽는다(읽기만).
접속은 적재와 같다 — PG 접속 정보가 있으면 PG, 없으면 PC 대역 sqlite(서버는 대역을 쓰지 않고 멈춤 — SystemExit). 연결을 못 열면 예외."""

import sqlite3

from common.store.db.models import search_tables as ST

_MISSING = ("42P01", "42703")  # PG undefined_table·undefined_column


def _missing(ex):
    """표·칸이 아직 없음(판 0006 전·처음 적재 전) — 그 밖의 오류(접속·권한 등)는 아님."""
    if getattr(ex, "sqlstate", None) in _MISSING:
        return True
    return isinstance(ex, sqlite3.OperationalError) and str(ex).startswith(("no such table", "no such column"))


def _schemas():
    """(질의 함수, 원천 스키마 이름) — 5벌 + 있는 DEV 원천 스키마. 다 쓰면 연결을 닫는다."""
    from common.store.pg import PG, _standin_schema, _warn_standin, conf, has_conn

    if has_conn():
        db = PG(conf())
        try:
            for src in ST.all_sources(db.schema, db.q):
                yield db.q, ST.src_schema(db.schema, src)
        finally:
            db.cn.close()
        return
    _warn_standin()
    from common.store.pg_standin import StandinPG

    base = _standin_schema()
    for src in ST.all_sources(base):
        sdb = StandinPG(ST.src_schema(base, src))
        try:
            yield sdb.q, sdb.schema
        finally:
            sdb.sqlite.close()


def _rows(sql, params=None):
    """원천 스키마마다 sql(`{S}` = 스키마)의 행을 합침 — 표·칸이 아직 없는 스키마는 0건, 그 밖의 오류는 그대로 올림(서버 종료 4 — pl-12)."""
    out = []
    for q, s in _schemas():
        try:
            out += q(sql.replace("{S}", s), params)
        except Exception as ex:
            if not _missing(ex):
                raise
    return out


def done_keys(keys=None):
    """gold `doc` 행이 있는 원본 키(`file_path`) 집합 — keys를 주면 그 키 중에서만(게시가 올릴 문서만 묻게)."""
    if keys is None:
        return {r["file_path"] for r in _rows("SELECT file_path FROM {S}.doc")}
    keys = sorted(set(keys))
    return {r["file_path"] for r in _rows("SELECT file_path FROM {S}.doc WHERE file_path = ANY(%s)", (keys,))} if keys else set()


def done_by_sha(shas):
    """원본 sha256이 shas에 있는 gold 문서 → {sha256: (원본 키, parse_status)}(같은 sha가 여럿이면 처음 것)."""
    out: dict = {}
    if shas:
        for r in _rows("SELECT sha256, file_path, parse_status FROM {S}.doc WHERE sha256 = ANY(%s)", (sorted(set(shas)),)):
            out.setdefault(r["sha256"], (r["file_path"], r["parse_status"]))
    return out
