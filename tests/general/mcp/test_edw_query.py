"""mcp_server.services.edw_query 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.edw_query`."""

from mcp_server import config as mc
from mcp_server.services.edw_query import (
    _TRUNC_MARK,
    DEFAULT_TABLES,
    _cap_cte_tsql,
    _json_safe_cell,
    _row_budget,
    _top_n,
    allowed_tables,
    validate,
)


def _demo():
    """ponytail — minimal self-check for the SQL guard + conversion helpers (no DB connection needed)."""
    allowed = {"ai.client", "ai.contract"}
    ok, err = validate("SELECT * FROM AI.client", allowed)
    assert err is None and ok.strip() == "SELECT * FROM AI.client"
    ok, err = validate("SELECT * FROM AI.client;", allowed)
    assert err is None and ";" not in ok
    assert validate("SELECT 1; DROP TABLE x", allowed)[1] == "multi_statement"
    assert validate("DELETE FROM AI.client", allowed)[1] == "first_keyword"  # DELETE also fails the first-keyword gate
    assert validate("SELECT * FROM AI.client; DELETE FROM AI.client", allowed)[1] is not None
    assert validate("SELECT * FROM AI.client -- DROP TABLE x\nWHERE 1=1", allowed)[1] is None
    assert validate("SELECT * /* ; DROP TABLE x */ FROM AI.client", allowed)[1] is None
    assert validate("SELECT * FROM AI.client /* unterminated", allowed)[1] == "unterminated_comment"
    assert validate("SELECT 'unterminated", allowed)[1] == "unterminated_string"
    assert validate("SELECT * FROM other.table", allowed)[1] == "table:other.table"
    assert validate("SELECT * FROM sys.tables", allowed)[1] == "table_system"
    assert validate("SELECT * FROM INFORMATION_SCHEMA.COLUMNS", allowed)[1] == "table_system"
    assert validate("UPDATE AI.client SET name='x'", allowed)[1] is not None
    assert validate("SELECT * INTO newtable FROM AI.client", allowed)[1] == "keyword:INTO"  # starts with SELECT, blocked mid-statement
    assert validate("SELECT * FROM (SELECT 1) t", allowed)[1] == "table_undetermined"
    ok, err = validate("WITH recent AS (SELECT * FROM AI.contract) SELECT * FROM recent", allowed)
    assert err is None, err  # CTE's own name is not checked against the table allowlist
    assert validate("exec xp_cmdshell 'dir'", allowed)[1] is not None
    # fb review fix — comma-separated FROM lists, table-valued functions, APPLY
    assert validate("SELECT * FROM AI.client, AI.contract", allowed)[1] is None  # all-allowed list passes
    assert validate("SELECT * FROM AI.client, dbo.secret_table", allowed)[1] == "table:dbo.secret_table"  # 2nd item checked
    assert (
        validate("SELECT * FROM AI.client a, AI.contract k, dbo.secret_table s", allowed)[1] == "table:dbo.secret_table"
    )  # 3rd item, with aliases
    assert validate("SELECT * FROM OPENJSON('[]')", allowed)[1] == "function:openjson"
    assert validate("SELECT * FROM dbo.fn(1,2)", allowed)[1] == "function:dbo.fn"
    assert validate("SELECT * FROM AI.client a CROSS APPLY dbo.fn(a.id) AS t", allowed)[1] == "keyword:APPLY"
    assert validate("SELECT * FROM AI.client a OUTER APPLY dbo.fn(a.id) AS t", allowed)[1] == "keyword:APPLY"
    assert validate("SELECT * FROM (SELECT * FROM dbo.secret_table) t", allowed)[1] == "table_undetermined"  # nested subquery kept rejected
    # security review round 2, fix 1 — statement smuggling (batch keywords, @, second top-level statement)
    smuggle = "SELECT 1 DECLARE @x INT = 0 WHILE @x < 100000000 BEGIN SET @x = @x + 1 END SELECT @x"
    assert validate(smuggle, allowed)[1] is not None
    assert validate("SELECT @@VERSION", allowed)[1] == "keyword:@"
    assert validate("SELECT CASE WHEN 1=1 THEN 'a' ELSE 'b' END FROM AI.client", allowed)[1] is None  # CASE...ELSE...END is fine
    assert validate("SELECT CASE WHEN 1=1 THEN 'a' END FROM AI.client", allowed)[1] is None  # CASE...END without ELSE too
    assert validate("IF 1=1 BEGIN SELECT 1 END ELSE BEGIN SELECT 2 END", allowed)[1] is not None  # control-flow IF/BEGIN still blocked
    assert validate("SELECT 1 SELECT 2", allowed)[1] == "multi_statement"  # no semicolon, no batch keyword — structural catch
    ok, err = validate("SELECT 1 FROM AI.client UNION SELECT 2 FROM AI.contract", allowed)
    assert err is None, err  # UNION still allowed
    ok, err = validate("SELECT 1 FROM AI.client UNION ALL SELECT 2 FROM AI.contract", allowed)
    assert err is None, err  # UNION ALL too
    ok, err = validate("WITH recent AS (SELECT * FROM AI.contract) SELECT * FROM recent SELECT 1", allowed)
    assert err == "multi_statement", err  # a CTE query's main SELECT is fine, but a 2nd one after it is not
    # security review round 2, fix 2 — row cap at the SQL level (CTE cartesian)
    import sqlite3 as _sq

    _mem = _sq.connect(":memory:")
    _mem.execute("CREATE TABLE t(x)")
    _mem.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(40)])
    cte_q = "WITH recent AS (SELECT * FROM t) SELECT * FROM recent a, recent b, recent c"  # 40^3 = 64000 rows
    wrapped, cap_err = _top_n(cte_q, 5, "sqlite")
    assert cap_err is None
    assert len(_mem.execute(wrapped).fetchall()) == 6  # n+1, so query() can detect truncation
    # 2026-10-22, live-measured (docs/mcp-retrieval-access-guide.md TOP queries) — plain SELECT explicit TOP
    ok_p, err_p = _top_n("SELECT TOP 3 * FROM AI.client", 5, "tsql")
    assert err_p is None and ok_p == "SELECT TOP 3 * FROM AI.client"  # already capped — left alone (was double-TOP death)
    ok_p, err_p = _top_n("SELECT TOP (3) * FROM AI.client", 5, "tsql")  # parenthesized form equally fine
    assert err_p is None and ok_p == "SELECT TOP (3) * FROM AI.client"
    ok_p, err_p = _top_n("SELECT DISTINCT TOP 3 * FROM AI.client", 5, "tsql")  # explicit TOP after DISTINCT too
    assert err_p is None and ok_p == "SELECT DISTINCT TOP 3 * FROM AI.client"
    assert _top_n("SELECT TOP 99 * FROM AI.client", 5, "tsql")[1] == "plain_top_too_high"  # never lower someone else's TOP
    assert _top_n("SELECT TOP 50 PERCENT * FROM AI.client", 100, "tsql")[1] == "top_percent"  # rows unbounded — fail closed
    assert _cap_cte_tsql("WITH c AS (SELECT 1 x) SELECT TOP 50 PERCENT * FROM c", 5)[1] == "top_percent"  # CTE same rule
    # 사용자 11-03(기본 1000행 — 운영 서버와 같음) — 실효 상한: 설정 우선, 기본 1000, 0은 무제한이 아니라 1행
    with mc.senv(EDW_QUERY_MAX_ROWS="1500"):
        assert _row_budget(9999) == 1500  # env override wins
    with mc.senv(EDW_QUERY_MAX_ROWS=None):  # 옛 시험은 env를 지운 채(del) 이어 감 — 기본값(1000) 확인
        assert _row_budget(5000) == 1000 and _row_budget(1000) == 1000 and _row_budget(100) == 100
        assert _row_budget(0) == 1  # max(1, …) — 0은 무제한 아님
    ok_p, err_p = _top_n("SELECT * FROM AI.client", 5, "tsql")  # no TOP — old injection, byte-identical
    assert err_p is None and ok_p == "SELECT TOP (6) * FROM AI.client"
    ok_p, err_p = _top_n("SELECT DISTINCT x FROM AI.client", 5, "tsql")
    assert err_p is None and ok_p == "SELECT DISTINCT TOP (6) x FROM AI.client"
    capped, cerr = _cap_cte_tsql("WITH c AS (SELECT 1 x) SELECT * FROM c", 5)
    assert cerr is None and "TOP (6)" in capped
    assert _cap_cte_tsql("WITH c AS (SELECT 1 x) SELECT TOP (3) * FROM c", 5)[1] is None  # already capped tighter — left alone
    assert _cap_cte_tsql("WITH c AS (SELECT 1 x) SELECT TOP (3) * FROM c", 2)[1] == "cte_top_too_high"
    assert _cap_cte_tsql("WITH c AS (SELECT 1 x) SELECT * FROM c UNION SELECT * FROM c", 5)[1] == "cte_union_not_capped"
    # security review round 2, fix 3 — empty allowlist is deny-all(이 규칙은 STRICT 조합으로 보존); 2026-10-21
    # 사용자 결정(전 스키마 허용) 뒤 기본 동작이 바뀐 것을 이 데모 단언에도 반영 — 기본 unset의 mssql은 None=제한 없음.
    assert allowed_tables("sqlite") == set(t.lower() for t in DEFAULT_TABLES.split(","))  # unset -> sample default (sqlite only)
    assert allowed_tables("mssql") is None  # unset -> all schemas allowed (2026-10-21) — None is the "no allowlist check" sentinel
    with mc.senv(EDW_QUERY_TABLES_STRICT="1", EDW_QUERY_TABLES=""):
        assert allowed_tables("sqlite") == set()  # explicit empty string -> deny-all even for sqlite
        assert allowed_tables("mssql") == set()  # ...and for mssql — round 2 rule lives on under STRICT
    from decimal import Decimal as D

    assert _json_safe_cell(D("10")) == 10
    assert _json_safe_cell(D("10.5")) == "10.5"
    assert _json_safe_cell(b"abc") == "<binary omitted, 3 bytes>"
    assert _json_safe_cell("x" * 2100).endswith(_TRUNC_MARK)
    print("[selftest] edw_query — SQL guard + JSON-safety OK")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _demo()
