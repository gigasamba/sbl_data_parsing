"""Rule-based EDW table/column metadata lookup for the MCP tool `edw_meta`. Serves a *pre-built static dataset* (catalog.json + columns.jsonl,
built by table_meta/scripts/build_mcp_dataset.py from the 209 column-metadata CSVs + the 1021
inventory, PII-sanitized at build time) — no live DB, no vector search, no embedding, no LLM call.

Rules:
 - 3-level hierarchy only: no args → schema summary · `schema` only → ALL tables of that schema
   (column list excluded) · `schema`+`table` → table meta + FULL column list with Korean
   descriptions. `column_filter` (case-insensitive substring on the column name) narrows wide
   tables (Account 182 cols). No single-column view and no keyword search (decided — do not add).
 - sample_values are NEVER sent in any response — the dataset keeps the
   sanitized values for future reuse, this tool just doesn't read them.
 - fail-soft: a missing module or dataset must never break the other three tools —
   mcp_server imports this module lazily inside do_edw_meta and turns NotConfigured into a
   {"error": ...} dict, the query_edw `not_configured` pattern.

Operational notes:
 - EDW_META_DIR (default <runtime root>/config/edw_meta, i.e. /app/config/edw_meta in the image — glossary-mount convention) holds catalog.json +
   columns.jsonl (~2.3MB, about zero-cost to load). First call loads; after that the file mtimes
   are re-checked at most once per MCP_RELOAD_CHECK_SEC (default 30) like _retriever(), so a
   rebuilt dataset propagates within 30s without a restart. A failed re-check keeps serving the
   stale copy and retries later — a mid-ship `docker cp` never 500s a live call.
 - tools run in _bg threads so the load/update path is lock-guarded (non-blocking check →
   single loader, same shape as mcp_server._retriever); lookups themselves are plain dict reads.
 - response budget: EDW_META_MAX_BYTES (default 200_000) tail-caps oversized responses the
   query_edw._cap_bytes way (tail drop + truncated:true + guidance) — the widest table
   (SFDC.Account, 182 columns) fits in ~30KB.
"""

import difflib
import json
import sys
import threading
import time
from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc

_DIR_DEFAULT = str(APP_ROOT / "config" / "edw_meta")  # 이미지 안 /app/config/edw_meta(I4 — 런타임 루트 기준, C4: env로 덮음)
_MAX_BYTES = int(mc.cfg().edw_meta.max_bytes)  # import 때 한 번(기본 200000)
_RELOAD_SEC = float(mc.cfg().server.reload_check_sec)  # _retriever()와 같은 값을 재사용 — 별도 env 안 만듦
_STATE: dict = {}  # {"d": dataset, ...} — 첫 호출 때 적재, 이후 mtime 확인 재적재
_LOCK = threading.Lock()


class NotConfigured(Exception):
    """EDW_META_DIR에 dataset이 없다 — do_edw_meta가 {"error": ...}로 바꾼다(서버는 계속)."""


def _dir():
    return Path(mc.cfg().edw_meta.dir or _DIR_DEFAULT)  # 호출마다


def _norm(x):
    """조회 키 정규화 — strip+lower. 'BSCM.MST_STOCK_MGT ' 후행 공백·'crms' 대소문자 모두 허용(§4.2)."""
    return (x or "").strip().lower()


def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


# ── dataset load / reload ────────────────────────────────────────────────────


def _load():
    d = _dir()
    cat_p, col_p = d / "catalog.json", d / "columns.jsonl"
    if not (cat_p.is_file() and col_p.is_file()):
        raise NotConfigured(f"edw_meta 데이터셋 미구성 — {d}에 catalog.json/columns.jsonl이 없다 (마운트 또는 docker cp 후 재시도)")
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    tables = cat.get("tables") or []
    cols = {}
    with open(col_p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            cols.setdefault((c["schema"].lower(), _norm(c["table"])), []).append(c)  # 이미 정렬키 순서로 기록됨(§3.1)
    by_key, by_tnorm, schemas_lower = {}, {}, {}
    for t in tables:
        s_n, t_n = t["schema"].lower(), _norm(t["table"])
        by_key[(s_n, t_n)] = t
        by_tnorm.setdefault(t_n, []).append(t)
        schemas_lower.setdefault(s_n, t["schema"])
    return {
        "meta": cat.get("meta") or {},
        "tables": tables,
        "cols": cols,
        "by_key": by_key,
        "by_tnorm": by_tnorm,
        "schemas_lower": schemas_lower,
        "as_of": (cat.get("meta") or {}).get("as_of"),
        "checked": time.monotonic(),
        "ver": (cat_p.stat().st_mtime_ns, col_p.stat().st_mtime_ns),
    }


def _data():
    st = _STATE.get("d")
    if st is None:
        with _LOCK:
            st = _STATE.get("d")
            if st is None:
                _STATE["d"] = _load()  # 첫 적재 실패(NotConfigured 포함)는 호출자에게 — 아직 쓸 데이터가 없다
                return _STATE["d"]
    if time.monotonic() - st["checked"] < _RELOAD_SEC:
        return st
    with _LOCK:  # 재적재 검사는 잠금 안에서 한 번만 — 조회는 기존 데이터로 바로 돌아감
        st = _STATE.get("d")
        if st is None or time.monotonic() - st["checked"] < _RELOAD_SEC:
            return st
        try:
            fresh = _load()
        except Exception as e:  # cp 도중 반쪽 파일 등 — 있던 데이터 그대로 두고 다음 확인에 재시도
            print(f"[mcp] edw_meta 재적재 실패(옛 데이터 유지): {type(e).__name__}: {str(e)[:100]}", file=sys.stderr, flush=True)
            st["checked"] = time.monotonic()
            return st
        if fresh["ver"] == st["ver"]:
            st["checked"] = fresh["checked"]
            return st
        _STATE["d"] = fresh  # 외부 파일 교체(mtime) — 30초 안 반영(비-RAG, 재시작 불필요)
        return fresh


# ── response builders ────────────────────────────────────────────────────────


def _col_row(c):
    key = None
    if c.get("primary_key"):
        key = "PK"
    elif c.get("foreign_key"):
        key = ("FK→" + c["fk_reference"]) if c.get("fk_reference") else "FK"
    return {
        "ordinal_position": c.get("ordinal_position"),
        "column": c.get("column_name"),
        "type": c.get("data_type"),
        "nullable": c.get("nullable"),
        "key": key,
        "desc_ko": c.get("description_ko"),
        "domain_tags": c.get("domain_tags") or [],
    }
    # sample_values·samples_suspect는 어떤 응답에도 실리지 않는다(§3.4 v1 미표시 방침).


def _schemas_view(d):
    schemas = []
    for s_orig, m in sorted((d["meta"].get("schemas") or {}).items()):
        schemas.append(
            {
                "schema": s_orig,
                "system_ko": m.get("system"),
                "tables": m.get("tables"),
                "columns": m.get("columns"),
                "tables_with_columns": m.get("columns_available_tables"),
            }
        )
    return {"kind": "schemas", "as_of": d["as_of"], "schemas": schemas, "excluded": d["meta"].get("excluded") or {}}


def _tables_view(d, s_n):
    entries = [t for t in d["tables"] if t["schema"].lower() == s_n]  # catalog가 (schema, table)순 정렬(§3.1)
    return {
        "kind": "tables",
        "schema": d["schemas_lower"][s_n],
        "as_of": d["as_of"],
        "table_count": len(entries),
        "tables": [
            {
                "table": t.get("table"),
                "qualified_name": t.get("qualified_name"),
                "desc_ko": t.get("table_desc_ko"),
                "row_count": t.get("row_count"),
                "data_period": t.get("data_period"),
                "data_shape": t.get("data_shape"),
                "column_count": t.get("column_count"),
            }
            for t in entries
        ],
    }


def _table_view(d, entry, column_filter=None):
    out = {
        "kind": "table",
        "schema": entry["schema"],
        "table": entry.get("table"),
        "qualified_name": entry.get("qualified_name"),
        "desc_ko": entry.get("table_desc_ko"),
        "source_system": entry.get("source_system"),
        "row_count": entry.get("row_count"),
        "data_period": entry.get("data_period"),
        "data_shape": entry.get("data_shape"),
        "columns_available": entry.get("columns_available", True),
    }
    if not out["columns_available"]:
        out["column_total"] = 0
        out["columns"] = []
        out["notes"] = ["컬럼 메타데이터 미생성(table_meta 파이프라인 gap) — 인벤토리 통계만 있다"]
        return out
    cols = d["cols"].get((entry["schema"].lower(), _norm(entry["table"])), [])
    out["column_total"] = len(cols)
    if column_filter is not None:
        cf = _norm(column_filter)
        cols = [c for c in cols if cf in (c.get("column_name") or "").lower()]
        out["column_filter"] = column_filter
    out["columns"] = [_col_row(c) for c in cols]
    return out


def _suggest_tables(d, t_n, limit=3):
    names = list(d["by_tnorm"])
    close = difflib.get_close_matches(t_n, names, n=limit, cutoff=0.5)
    out = []
    for n in close:
        out += [f"{t['schema']}.{t['table']}" for t in d["by_tnorm"][n][:1]]
    return out[:limit]


def _cap(obj):
    """query_edw._cap_bytes 방식 — 꼬리 절단 + truncated 표기(§4.2). 목록 없는 응답(schemas)은 통과."""
    if _size(obj) <= _MAX_BYTES:
        return obj
    for k in ("columns", "tables"):
        if isinstance(obj.get(k), list):
            while obj[k] and _size(obj) > _MAX_BYTES:
                obj[k].pop()
                obj["truncated"] = True
            if obj.get("truncated"):
                obj.setdefault("notes", []).append(
                    "응답 크기 상한(EDW_META_MAX_BYTES) 초과로 목록 꼬리를 잘랐다"
                    + (" — column_filter로 좁혀서 다시 조회" if k == "columns" else " — 범위를 나눠 조회")
                )
            return obj
    return obj


# ── entry point (do_edw_meta에서 호출) ───────────────────────────────────────


def lookup(schema=None, table=None, column_filter=None):
    """3단 계층 조회 — 정규화된 키 매칭(dict 순회)만 한다. NotConfigured는 호출자(do_edw_meta)가 {"error": ...}로."""
    d = _data()
    s_n, t_n = _norm(schema), _norm(table)
    if not s_n and not t_n:
        if column_filter is not None:
            return {"error": "column_filter는 schema+table 조회에서만 쓴다(컬럼 목록을 좁히는 인자)"}
        return _cap(_schemas_view(d))
    if t_n:
        if s_n and s_n not in d["schemas_lower"]:
            return {
                "error": f"스키마 없음: {schema}",
                "suggestions": [x.upper() for x in difflib.get_close_matches(s_n, list(d["schemas_lower"]), n=3, cutoff=0.5)],
            }
        if s_n:  # schema 지정 — 그 스키마에서 정확히 그 테이블
            entry = d["by_key"].get((s_n, t_n))
            if entry is None:
                return {"error": f"테이블 없음: {schema}.{table}", "suggestions": _suggest_tables(d, t_n)}
            return _cap(_table_view(d, entry, column_filter))
        all_entries = d["by_tnorm"].get(t_n, [])  # schema 생략 — 전 스키마에서 이름으로
        if not all_entries:
            return {"error": f"테이블 없음: {table}", "suggestions": _suggest_tables(d, t_n)}
        if len(all_entries) > 1:
            return {
                "error": "같은 이름의 테이블이 여러 스키마에 있다 — schema를 지정해서 다시 조회",
                "candidates": [f"{t['schema']}.{t['table']}" for t in all_entries],
            }
        return _cap(_table_view(d, all_entries[0], column_filter))
    # schema만 — 그 스키마 전체 테이블 메타(컬럼 제외)
    if s_n not in d["schemas_lower"]:
        return {
            "error": f"스키마 없음: {schema}",
            "suggestions": [x.upper() for x in difflib.get_close_matches(s_n, list(d["schemas_lower"]), n=3, cutoff=0.5)],
        }
    return _cap(_tables_view(d, s_n))
