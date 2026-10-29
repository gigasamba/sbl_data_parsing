"""SI41 — 원천 표 목록(비밀 없음, git) — `.env`는 접속 정보(RDB_HOST 등)·크리덴셜만, **어느 표·어느 열**은 여기.

자리(S8b — D-031, 사용자 10-28): 서버(RUN_ENV dev·stage·prd · 이미지 배치)는 판 표 `struct.source_version`의 활성 판(common.store.db.cfgtables —
못 읽으면 시작 거부, 종료 4), PC(paths.LOCAL_RUN)는 파일 `common.paths.sources_file`(비우면 `resources/mappings/sources.json`). 옛 서버 덮어쓰기
`$SERVER_ENV_DIR/sources.json`(호스트 python만 봄)은 없앰 — 그 내용은 `set-sources --file`로 판을 넣는다(refactor.md C-12).

모양(목록):
  [{"name": "FileStorageMap", "table": "AI.FileStorageMap", "bucket": "<버킷>", "enabled": true,
    "columns": {"doc_id": "id", "key": "s3_key", "filename": "original_filename", "size": "file_size",
                "increment": "id", …선택(content_version·etag·content_type·company·doc_type·contract·version·
                supersedes·is_deleted·bucket)}}, …]
name = modules/parse/source.py가 `rdb:<name>`으로 고르는 이름(파일 이름에도 쓰여 영문·숫자·_ 만). table·columns 값은
SQL에 식별자로 그대로 들어가므로(mssql 대괄호·pg Identifier) 같은 화이트리스트(TABLE_ID_RE·COL_ID_RE)로 검증— 가짓수
적은 명확한 오류로 실패(사람이 sources.json을 고치게)."""

import json
import re
from pathlib import Path

from common.core.paths import RES_ROOT

TABLE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")  # 표 이름(스키마.표도 허용)
COL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # 열 이름·원천 이름(같은 화이트리스트)

REQUIRED_COLUMNS = ("doc_id", "key", "filename", "size", "increment")
OPTIONAL_COLUMNS = (
    "content_version",
    "etag",
    "content_type",
    "company",
    "doc_type",
    "contract",
    "version",
    "supersedes",
    "is_deleted",
    "bucket",
)
ALLOWED_COLUMNS = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
ALLOWED_SOURCE_KEYS = {"name", "table", "bucket", "columns", "enabled"}

DEFAULT_FILE = RES_ROOT / "mappings" / "sources.json"  # S2 — 옛 common_tools/runtime/sources.json(D-017: S8에 DB 판 표의 시드·PC 대체)


def sources_path():
    """PC 원천 목록 파일 — common.paths.sources_file(비우면 기본 파일, git). 서버는 판 표(sources_origin)."""
    from common.store.db import cfgtables  # S8b — PC 파일 자리 규칙 한 곳(엔진 구성 파일과 같은 꼴)

    return cfgtables.pc_file("sources")


def sources_origin():
    """안내 글자용 — 지금 읽는 자리(PC 파일 경로 · 서버 판 표)."""
    from common.core import paths

    return str(sources_path()) if paths.LOCAL_RUN else "struct.source_version 활성 판"


def _validate_entry(entry, path, index):
    if not isinstance(entry, dict):
        raise ValueError(f"[sources] {path}[{index}] — 객체(dict)여야 함")
    bad_keys = set(entry) - ALLOWED_SOURCE_KEYS
    if bad_keys:
        raise ValueError(f"[sources] {path}[{index}] — 알 수 없는 키: {sorted(bad_keys)}")
    name = entry.get("name")
    if not name or not isinstance(name, str) or not COL_ID_RE.match(name):
        raise ValueError(f"[sources] {path}[{index}] — name이 올바르지 않음(영문·숫자·_ 만, 비어 있지 않음): {name!r}")
    table = entry.get("table")
    if not table or not isinstance(table, str) or not (table.startswith("csv:") or TABLE_ID_RE.match(table)):
        raise ValueError(
            f"[sources] {path}[{name}] — table이 올바르지 않음(영문·숫자·_, 스키마.표만 · 시험용 csv:<경로>만 예외): {table!r}"
        )
    bucket = entry.get("bucket", "")
    if not isinstance(bucket, str):
        raise ValueError(
            f"[sources] {path}[{name}] — bucket은 문자열이어야 함(버킷 이름, 서버마다 다르면 "
            "비워 두고 env RDB_BUCKET 또는 key의 s3://버킷/… 접두로 대체 가능)"
        )
    cols = entry.get("columns")
    if not isinstance(cols, dict):
        raise ValueError(f"[sources] {path}[{name}] — columns(객체) 필요")
    missing = set(REQUIRED_COLUMNS) - set(cols)
    if missing:
        raise ValueError(f"[sources] {path}[{name}] — columns에 필수 열 빠짐: {sorted(missing)}")
    bad_col_keys = set(cols) - ALLOWED_COLUMNS
    if bad_col_keys:
        raise ValueError(f"[sources] {path}[{name}] — columns에 알 수 없는 키: {sorted(bad_col_keys)}")
    for k, v in cols.items():
        if not isinstance(v, str) or not COL_ID_RE.match(v):
            raise ValueError(f"[sources] {path}[{name}] — columns.{k} 값이 올바르지 않음(영문·숫자·_ 만): {v!r}")
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"[sources] {path}[{name}] — enabled는 true/false")
    return {"name": name, "table": table, "bucket": bucket, "columns": dict(cols), "enabled": enabled}


def load_sources(path=None):
    """→ {name: entry} 전부(켜짐·꺼짐 모두). path를 주면 그 파일, 아니면 서버 = 판 표 활성 판(S8b) · PC = sources_path().
    파일이 없으면 빈 dict(레거시 `rdb:<표>` 직접 지정은 그대로 동작)."""
    if path is None:
        from common.core import paths

        if not paths.LOCAL_RUN:
            from common.store.db import cfgtables

            a = cfgtables.active("sources")
            return _by_name(a.body, a.origin)
    p = Path(path) if path else sources_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"[sources] {p} JSON 파싱 실패: {e}") from e
    return _by_name(raw, p)


def _by_name(raw, where):
    if not isinstance(raw, list):
        raise ValueError(f"[sources] {where} — 목록([...])이어야 함")
    by_name = {}
    for i, entry in enumerate(raw):
        v = _validate_entry(entry, where, i)
        if v["name"] in by_name:
            raise ValueError(f"[sources] {where} — name 중복: {v['name']}")
        by_name[v["name"]] = v
    return by_name


def enabled_sources(path=None):
    return {n: e for n, e in load_sources(path).items() if e["enabled"]}
