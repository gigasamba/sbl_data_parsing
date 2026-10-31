"""common.store.structdb 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.store.structdb`."""

from pathlib import Path

from common.config.settings import COMMON, cfg
from common.store.structdb import (
    PROD_DBS,
    SCHEMA,
    TABLE_SCHEMA,
    SqliteBackend,
    StructDBError,
    _pg_sql,
    ensure_schema,
    ensure_table_schema,
    guard_not_prod,
    open_backend,
)


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    import tempfile

    # pl-12 C10(10-31) — 문서 대장·숨김(doc_registry·doc_hidden)은 코드째 지움 — 다시 생기지 않는다.
    assert not any("doc_registry" in stmt or "doc_hidden" in stmt for stmt in SCHEMA + TABLE_SCHEMA), "doc_registry·doc_hidden이 되살아남"

    # AD23 — 같은 패턴: doc_table·doc_cell은 SCHEMA가 아니라 TABLE_SCHEMA(ensure_table_schema 전용)에만.
    assert not any("doc_table" in stmt or "doc_cell" in stmt for stmt in SCHEMA), "doc_table·doc_cell이 SCHEMA에 섞임 — TABLE_SCHEMA로"
    assert any("doc_table" in stmt for stmt in TABLE_SCHEMA) and any("doc_cell" in stmt for stmt in TABLE_SCHEMA)
    print("[selftest] AD23 — doc_table·doc_cell은 SCHEMA가 아닌 TABLE_SCHEMA에만(ensure_schema 무영향) 통과")

    # _pg_sql() 문자열 번역(? → %s · INSERT OR REPLACE → ON CONFLICT · % 이스케이프) — PG 없이도 도는 오프라인 검증(X1b 리뷰)
    assert _pg_sql("SELECT * FROM doc_contract_link WHERE how != ?") == "SELECT * FROM doc_contract_link WHERE how != %s"
    assert _pg_sql("INSERT OR REPLACE INTO contract_master (contract_id,company) VALUES (?,?)") == (
        "INSERT INTO contract_master (contract_id,company) VALUES (%s,%s) ON CONFLICT (contract_id) DO UPDATE SET company=EXCLUDED.company"
    )
    assert _pg_sql("INSERT OR REPLACE INTO doc_contract_link (doc_key, contract_id, score) VALUES (?,?,?)") == (
        "INSERT INTO doc_contract_link (doc_key, contract_id, score) VALUES (%s,%s,%s) "
        "ON CONFLICT (doc_key) DO UPDATE SET contract_id=EXCLUDED.contract_id, score=EXCLUDED.score"
    )
    assert _pg_sql("SELECT '50%' AS pct") == "SELECT '50%%' AS pct"  # 리터럴 %는 psycopg %-치환이 깨지지 않게 %%로
    print("[selftest] _pg_sql 번역(? · INSERT OR REPLACE · % 이스케이프) 통과")

    # RUN_MODE=prod + PG 실패 → StructDBError(RuntimeError) — SystemExit이 아니라 mcp_server 같은 장수 프로세스를 안 죽임(X1b 리뷰)
    with COMMON.env(RUN_MODE="prod", STRUCT_BACKEND="pg", PG_PASSWORD=None, PG_CONN_FILE=None):
        try:
            open_backend()
            raise AssertionError("RUN_MODE=prod면 PG 실패 시 StructDBError가 나야 함")
        except StructDBError:
            pass  # SystemExit이 아님 — 여기서 잡혔으니 프로세스는 계속 살아 있음
    print("[selftest] RUN_MODE=prod + PG 실패 → StructDBError(SystemExit 아님) 통과")

    tmp = Path(tempfile.mkdtemp()) / "t.sqlite"
    db = open_backend(str(tmp))  # 기본 STRUCT_BACKEND=pg — PG 없으면 여기서 자동 SQLite 대체(X1b)
    requested_pg = cfg().store.struct_backend == "pg"
    ensure_schema(db)
    if isinstance(db, SqliteBackend):
        tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "doc_table" not in tables and "doc_cell" not in tables, tables  # AD23 — 같은 게이트(ensure_table_schema 전용)
        ensure_table_schema(db)
        tables2 = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "doc_table" in tables2 and "doc_cell" in tables2, tables2
        print("[selftest] AD23 — ensure_schema()는 doc_table·doc_cell을 안 만들고, ensure_table_schema()를 불러야 생김 통과")
    db.execute("INSERT INTO client_master (company_id, company, aliases) VALUES (?,?,?)", ("CL-1", "Acme", "A|B"))
    db.execute("INSERT OR REPLACE INTO client_master (company_id, company, aliases) VALUES (?,?,?)", ("CL-1", "Acme", "A|B|C"))
    db.commit()
    assert db.query("SELECT * FROM client_master")[0]["aliases"] == "A|B|C"  # INSERT OR REPLACE(PG는 ON CONFLICT 번역) 둘 다 통과
    if requested_pg and isinstance(db, SqliteBackend):
        assert db.notes and "SQLite 대체" in db.notes[0], db.notes
    print(f"[selftest] 백엔드={type(db).__name__}" + (" notes=" + str(db.notes) if db.notes else ""))
    db.close()
    try:
        guard_not_prod(next(iter(PROD_DBS)))
        raise AssertionError("운영 DB 가드가 걸려야 함")
    except SystemExit:
        pass
    print("[selftest] 로컬 정형 저장소 연결·스키마·INSERT OR REPLACE·운영 DB 가드·PG 없을 때 SQLite 대체 통과")
