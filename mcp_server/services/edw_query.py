"""Read-only EDW SQL query engine for the MCP tool `query_edw`. An LLM agent sends its own SELECT, this module runs it against EDW
(SQL Server in production, a SQLite stand-in on a dev PC) and returns raw rows for the agent to
post-process — no summarization or calculation happens here.

Security boundary:
 - read-only by construction: exactly one SELECT/WITH statement, no DML/DDL/exec keywords anywhere
   (see `validate()`), run through the EDW **read** account (common.connections.rdb.read — the search
   MCP never gets the write account; docs/prd/ops.md#op-03).
 - tables: every schema the read account can see (narrow it with DB grants); the sqlite
   stand-in is limited to DEFAULT_TABLES. System catalogs are always rejected.
 - limits: row count (EDW_QUERY_MAX_ROWS), wall-clock timeout (EDW_QUERY_TIMEOUT_SEC), response size
   (EDW_QUERY_MAX_BYTES), per-cell text length (2000 chars).

Known limitation: `validate()` is a regex-based
conservative parser, not a real SQL parser. It scans the *whole* statement text for FROM/JOIN targets
(so it also catches subqueries and CTEs' inner tables), checks every item in a comma-separated FROM
list (not just the first), and classifies table-valued function calls (`OPENJSON(...)`, `dbo.fn(...)`)
and `CROSS`/`OUTER APPLY` as rejected unless on the allowlist. It still cannot resolve every legal SQL
Server construct — dynamic pivoting or very unusual identifier quoting can be rejected as "can't be
determined" even when they would have been safe. That is the deliberate fail-closed side of a
conservative allowlist checker; loosening it needs a real parser, not more regex.

Guards against:
 1. T-SQL does not need `;` between statements, so a single call could smuggle a second statement
    (`SELECT 1 DECLARE @x INT = 0 WHILE ... SET @x = ...`). Closed two ways: every T-SQL batch/control
    keyword (DECLARE/SET/WHILE/BEGIN/IF/ELSE/GOTO/PRINT/RETURN/THROW/RAISERROR/TRY/CATCH/USE/GO) is now
    blocked, and any bare `@` outside a string literal is rejected (variables aren't needed for a
    read-only SELECT). Structurally, `validate()` also walks the statement at paren depth 0 and rejects
    a second top-level SELECT/WITH that isn't part of a UNION/INTERSECT/EXCEPT — that is the general
    case the keyword list alone wouldn't catch (e.g. `SELECT 1 SELECT 2`, no keyword involved at all).
 2. The row cap (`EDW_QUERY_MAX_ROWS`/max_rows) needs to be enforced *in the SQL sent to the database*,
    not just in Python after the fact — otherwise a CTE building a cartesian product still fully
    computes server-side before fetchmany ever gets a chance to stop it. See `_top_n()`.
 3. Table scope — see allowed_tables(): mssql = all schemas the read account can see, sqlite
    stand-in = DEFAULT_TABLES.
 4. The sqlite stand-in connection is now opened with SQLite's own `file:...?mode=ro` URI read-only
    flag, so even a SQL-text guard bypass could not write to it at the OS/driver level (`ATTACH` and
    `PRAGMA` were already blocked keywords for user-supplied SQL; `LOAD_EXTENSION` is now blocked too).
"""

import re
import sqlite3
import time
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal

from common.config import settings as C  # common 칸(connections.rdb — 접속·sqlite 대역)
from mcp_server import config as mc  # 호출마다 cfg()
from mcp_server.schemas.edw_result import ColumnMeta, QueryResult  # noqa: F401 — 출력 모양은 schemas/

DEFAULT_TABLES = "AI.FileStorageMap,AI.ParsingMeta,CRMS.RM_MAS_CLIENT,CRMS.RM_MAS_CLIENT_GENERAL,LAS.DIVISION_MAS,LAS.PROD_MAS,LAS.SERVICE_MAS,SFDC.Account,SFDC.Opportunity"  # PC stand-in tables (valid_env/edw — ops.md#op-03)
_CELL_MAX = 2000
_TRUNC_MARK = " …(truncated)"
_SYSTEM_SCHEMAS = ("sys", "information_schema")
_SYSTEM_BARE = ("sqlite_master",)

# Word-bounded, case-insensitive: any DML/DDL/admin keyword, or an xp_/sp_ prefixed identifier
# (catches system/extended stored procedures like xp_cmdshell, sp_executesql). APPLY (CROSS/OUTER APPLY)
# is here too — its target is a correlated subquery/table-valued function our FROM/JOIN-anchored scanner
# below structurally never sees (APPLY isn't FROM or JOIN), so the only safe move is to reject it outright
# rather than try to validate whatever follows it. The batch/control-flow keywords (DECLARE..GO) close
# the statement-smuggling path T-SQL's optional `;` opens up (security review round 2): none of them can
# appear in a legitimate single read-only SELECT/WITH, so blocking them word-bounded has ~zero false-
# positive risk (all reserved words, can't be unquoted identifiers either). LOAD_EXTENSION is blocked
# even though the sqlite3 driver already disables it by default (`enable_load_extension` is never
# called) — defense in depth, and it costs nothing since it's not a legitimate SELECT term either.
_BLOCKED_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|DENY|EXEC|EXECUTE|INTO|"
    r"OPENROWSET|OPENQUERY|OPENDATASOURCE|BULK|BACKUP|RESTORE|SHUTDOWN|KILL|DBCC|WAITFOR|ATTACH|DETACH|"
    r"PRAGMA|APPLY|DECLARE|SET|WHILE|BEGIN|IF|GOTO|PRINT|RETURN|THROW|RAISERROR|TRY|CATCH|USE|GO|"
    r"LOAD_EXTENSION)\b|\b(?:xp|sp)_\w*",
    re.IGNORECASE,
)
# END and ELSE are deliberately NOT in _BLOCKED_RE, unlike the rest of this round's batch-keyword list
# (fb review named both DECLARE..GO and END/ELSE as candidates, with an explicit "careful" about END):
# `CASE WHEN ... THEN ... ELSE ... END` is ordinary, extremely common SELECT syntax, and both words also
# only ever appear in T-SQL as part of either a CASE expression or an IF...ELSE/BEGIN...END control-flow
# statement — and IF and BEGIN are both already blocked, so the control-flow use is already closed
# without needing END/ELSE themselves (blocking them too would only add false positives on plain CASE).
_FIRST_KEYWORD_RE = re.compile(r"^\s*(?:SELECT|WITH)\b", re.IGNORECASE)
_FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\b", re.IGNORECASE)
_CTE_RE = re.compile(r"(?:\bWITH\s+|,\s*)([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE)
_WS_RE = re.compile(r"\s*")
_IDENT = r"\[?[A-Za-z_][\w$#]*\]?"
_IDENT_RE = re.compile(_IDENT)
_QUALNAME_RE = re.compile(rf"{_IDENT}(?:\s*\.\s*{_IDENT})?")
_AS_RE = re.compile(r"AS\s+", re.IGNORECASE)
# Bare-alias stop words: a word right after a table ref that must NOT be swallowed as an un-prefixed
# alias, because it is actually the next clause — otherwise "FROM a WHERE ..." could misread WHERE as
# a's alias and keep scanning past it. Only matters for the common "table [AS] alias" case we keep
# parsing past; anything else (subquery/function/unknown) rejects immediately (see validate()), so
# imperfect alias recovery after those is harmless.
_ALIAS_STOPWORDS = {
    "where",
    "group",
    "order",
    "having",
    "union",
    "intersect",
    "except",
    "join",
    "inner",
    "left",
    "right",
    "full",
    "cross",
    "outer",
    "on",
    "with",
    "for",
}
_WORD_RE = re.compile(r"[A-Za-z_]\w*")
_STMT_WORDS = {"SELECT", "WITH", "UNION", "INTERSECT", "EXCEPT", "ALL"}
_TOP_AFTER_SELECT_RE = re.compile(r"\s*TOP\s*\(?\s*(\d+)\s*\)?", re.IGNORECASE)


# ── env / backend selection ─────────────────────────────────────────────────


def allowed_tables(kind=None):
    """제한 없음(전 스키마 허용) — None을 돌려주면 validate가 허용 목록 검사를 건너뛴다.
    시스템 테이블 차단(sys·INFORMATION_SCHEMA 등)·읽기 전용 키워드 검사는 그대로 유지된다. sqlite 스탠드인은 실 EDW가
    아니므로 동봉 샘플 범위(DEFAULT_TABLES)로 둔다."""
    if kind == "sqlite":
        return {t.strip().lower() for t in DEFAULT_TABLES.split(",") if t.strip()}
    return None


def _mssql_conf():
    """EDW read-account connection args (common.connections.rdb + .read — never the write account).
    Returns None (not SystemExit) when required keys are missing — the caller turns that into a
    clean `not_configured` response instead of crashing the server."""
    from common.store import mssql

    if not C.cfg().connections.rdb.host:
        return None
    try:
        kw, miss = mssql.login("read")
    except ValueError:  # malformed port — same clean not_configured instead of a crash
        return None
    return None if miss else kw


def backend():
    """Backend selection order (spec): RDB_SQLITE (the one PC stand-in);
    then the EDW read account (common.connections.rdb, pymssql); otherwise not configured.
    Returns ("sqlite", path) | ("mssql", conf_dict) | (None, None)."""
    from common.store import mssql

    sqlite_path = mssql.standin_path()
    if sqlite_path:
        return "sqlite", sqlite_path
    conf = _mssql_conf()
    if conf is not None:
        return "mssql", conf
    return None, None


def dialect_of(kind):
    return "sqlite" if kind == "sqlite" else "tsql"


# ── SQL guard ────────────────────────────────────────────────────────────


def _scan(sql):
    """Strip `--` line comments and `/* */` block comments, tracking single-quoted string literals and
    [bracketed] identifiers so a comment marker *inside* one of those is left alone. Also records the
    positions of `;` that are outside any string/bracket (used by `validate()` to allow exactly one
    trailing statement separator). Raises ValueError on an unterminated string, bracket, or block
    comment — those are rejected rather than guessed at."""
    out = []
    semis = []
    i, n = 0, len(sql)
    in_squote = False
    in_bracket = False
    while i < n:
        c = sql[i]
        if in_squote:
            out.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":  # doubled '' = escaped quote inside the literal
                    out.append(sql[i + 1])
                    i += 2
                    continue
                in_squote = False
            i += 1
            continue
        if in_bracket:
            out.append(c)
            if c == "]":
                in_bracket = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_bracket = True
            out.append(c)
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated_comment")
            i = j + 2
            out.append(" ")
            continue
        if c == ";":
            semis.append(len(out))
        out.append(c)
        i += 1
    if in_squote:
        raise ValueError("unterminated_string")
    if in_bracket:
        raise ValueError("unterminated_bracket")
    return "".join(out), semis


def _normalize_ref(raw):
    return re.sub(r"\s*\.\s*", ".", raw).replace("[", "").replace("]", "").lower()


def _scan_from_list(text, pos):
    """fb review fix — parse the comma-separated target list right after a FROM/JOIN keyword (`pos` is
    the index just past the keyword). A plain `FROM a` is a one-item list; `FROM a, b, c` is the real
    target of this fix (the old single-match regex only ever checked `a`, letting `b`/`c` through
    unchecked). Splits on commas at paren/quote depth 0 only.

    Returns a list of (kind, name) items, kind in {"table", "function", "subquery", "unknown"}:
      - "table": a plain (optionally schema-qualified) identifier, not immediately followed by '('.
      - "function": identifier immediately followed by '(' — a table-valued function call
        (`OPENJSON(...)`, `dbo.fn(...)`) — checked against the same allowlist as tables, per the review
        ("reject ... table-valued functions ... unless they are on the allowlist").
      - "subquery": the item starts with '(' (a derived table) — validate() rejects this unconditionally
        without looking inside (existing, deliberately kept behavior — a real parser would be needed to
        safely inspect it).
      - "unknown": couldn't even match an identifier — validate() rejects it ("cannot determine").
    Stops at the first clause keyword it is not safe to consume as a bare alias (WHERE/JOIN/ON/...), at
    a derived-table/function item (classification alone is enough for validate() to decide — this
    function does not need to parse accurately past one), or at end of text.
    """
    n = len(text)
    items = []
    while True:
        pos = _WS_RE.match(text, pos).end()
        if pos >= n:
            break
        if text[pos] == "(":
            items.append(("subquery", None))
            break  # validate() rejects on sight — no need to keep parsing this list
        m = _QUALNAME_RE.match(text, pos)
        if not m:
            items.append(("unknown", None))
            break
        if any(p.startswith("[") != p.endswith("]") for p in re.split(r"\s*\.\s*", m.group(0))):
            # "[AI.client]" is ONE table literally named "AI.client" in the default
            # schema for SQL Server, not schema AI + table client; a '.' inside brackets is never accepted.
            items.append(("unknown", None))
            break
        name = _normalize_ref(m.group(0))
        pos = m.end()
        fpos = _WS_RE.match(text, pos).end()
        if fpos < n and text[fpos] == ".":
            # A 3/4-part name (db.schema.table, linked server) whose first two
            # parts match an allowlisted entry must not pass as that entry; only schema.table is ever allowed.
            items.append(("unknown", None))
            break
        if fpos < n and text[fpos] == "(":
            items.append(("function", name))
            break  # same reasoning — a TVF call is classified, that's enough
        items.append(("table", name))
        # optional alias, only to find the next comma (harmless if this guesses wrong — worst case we
        # stop the list a little early, which only makes validate() look at fewer items, never more)
        pos = _WS_RE.match(text, pos).end()
        m2 = _AS_RE.match(text, pos)
        if m2:
            pos = m2.end()
            m3 = _IDENT_RE.match(text, pos)
            if m3:
                pos = m3.end()
        else:
            m3 = _IDENT_RE.match(text, pos)
            if m3 and m3.group(0).strip("[]").lower() not in _ALIAS_STOPWORDS:
                pos = m3.end()
        pos = _WS_RE.match(text, pos).end()
        if pos < n and text[pos] == ",":
            pos += 1
            continue
        break
    return items


def _at_outside_strings(text, chars="@"):
    """Security review round 2, fix 1 — True if `text` has a bare `@` anywhere outside a string literal
    or [bracketed] identifier. A read-only single SELECT/WITH never legitimately needs a T-SQL local
    variable (`@x`) or a parameter marker used that way; rejecting any `@` closes that smuggling path
    regardless of which batch keyword (if any) it's paired with."""
    i, n = 0, len(text)
    in_squote = False
    in_bracket = False
    while i < n:
        c = text[i]
        if in_squote:
            if c == "'":
                if i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                in_squote = False
            i += 1
            continue
        if in_bracket:
            if c == "]":
                in_bracket = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            i += 1
            continue
        if c == "[":
            in_bracket = True
            i += 1
            continue
        if c in chars:
            return True
        i += 1
    return False


def _depth0_tokens(text):
    """Security review round 2, fix 1 (structural half) — scan `text` once (comment-stripped already,
    quote/bracket-aware) and collect every SELECT/WITH/UNION/INTERSECT/EXCEPT/ALL keyword that occurs at
    paren depth 0 — i.e. not inside a subquery, CTE body, or function-call argument list. Returns a list
    of (start, end, WORD_UPPER) in text order. `validate()` uses this to tell a legitimate UNION branch
    apart from a second, unrelated statement smuggled in without a `;` (T-SQL doesn't require one), and
    `_cap_cte_tsql()` reuses it to find a WITH query's single top-level SELECT to inject TOP into."""
    out = []
    n = len(text)
    i = 0
    depth = 0
    in_squote = False
    in_bracket = False
    while i < n:
        c = text[i]
        if in_squote:
            if c == "'":
                if i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                in_squote = False
            i += 1
            continue
        if in_bracket:
            if c == "]":
                in_bracket = False
            i += 1
            continue
        if c == "'":
            in_squote = True
            i += 1
            continue
        if c == "[":
            in_bracket = True
            i += 1
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and (c.isalpha() or c == "_"):
            m = _WORD_RE.match(text, i)
            word = m.group(0)
            if word.upper() in _STMT_WORDS:
                out.append((m.start(), m.end(), word.upper()))
            i = m.end()
            continue
        i += 1
    return out


def _check_single_top_level_statement(core):
    """Security review round 2, fix 1 (structural half) — reject a second top-level SELECT/WITH that
    isn't part of a UNION/INTERSECT/EXCEPT of the main query (e.g. `SELECT 1 SELECT 2`, no semicolon,
    no batch keyword — the keyword blocklist alone wouldn't catch this). A WITH query's own single
    top-level SELECT (the one right after its CTE definitions) is not a "second statement" — see the
    `start_i` special case below. Returns an error code or None."""
    tokens = _depth0_tokens(core)
    start_i = 1
    if tokens and tokens[0][2] == "WITH" and len(tokens) > 1 and tokens[1][2] == "SELECT":
        start_i = 2  # the CTE statement's own main query, not a smuggled second statement
    for i in range(start_i, len(tokens)):
        word = tokens[i][2]
        if word not in ("SELECT", "WITH"):
            continue
        prev = tokens[i - 1][2]
        prev2 = tokens[i - 2][2] if i >= 2 else None
        is_setop_continuation = prev in ("UNION", "INTERSECT", "EXCEPT") or (prev == "ALL" and prev2 in ("UNION", "INTERSECT", "EXCEPT"))
        if not is_setop_continuation:
            return "multi_statement"
    return None


def validate(sql, allowed):
    """Clean + reject-list check. Returns (clean_sql, None) on success or (None, error_code) on
    rejection. error_code is one of: unterminated_string · unterminated_bracket · unterminated_comment ·
    empty · multi_statement · first_keyword · keyword:<KW> · keyword:@ · table_undetermined ·
    table_system · table:<name> · function:<name>."""
    try:
        cleaned, _semis = _scan(sql)
    except ValueError as e:
        return None, str(e)
    body = cleaned.strip()
    if not body:
        return None, "empty"
    core = body[:-1].rstrip() if body.endswith(";") else body  # allow exactly one trailing ';'
    if ";" in core:
        return None, "multi_statement"
    if not _FIRST_KEYWORD_RE.match(core):
        return None, "first_keyword"
    m = _BLOCKED_RE.search(core)
    if m:
        return None, f"keyword:{m.group(0).strip().upper()}"
    if _at_outside_strings(core):
        return None, "keyword:@"
    if _at_outside_strings(core, '"'):
        # The scanners only know '...' and [...]; a "quoted" identifier holding a
        # single quote would make them treat the rest as a string. Use [brackets] for identifiers instead.
        return None, "double_quote"
    stmt_err = _check_single_top_level_statement(core)
    if stmt_err:
        return None, stmt_err
    cte_names = {m.group(1).lower() for m in _CTE_RE.finditer(core)}
    for kw_m in _FROM_JOIN_RE.finditer(core):
        for kind, name in _scan_from_list(core, kw_m.end()):
            if kind in ("subquery", "unknown"):
                return None, "table_undetermined"
            if kind == "function":
                if allowed is not None and name not in allowed:
                    return None, f"function:{name}"
                continue
            schema, _, bare = name.rpartition(".")
            if schema in _SYSTEM_SCHEMAS or (not schema and bare in _SYSTEM_BARE) or bare in _SYSTEM_BARE:
                return None, "table_system"
            if not schema and bare in cte_names:
                continue  # a CTE's own name, not a real table
            if allowed is not None and name not in allowed:  # 기본 전 스키마 허용(None) — 시스템 테이블 차단은 위에서 이미 끝남
                return None, f"table:{name}"
    return core, None


# ── value conversion (JSON safety) ──────────────────────────────────────


def _json_safe_cell(v):
    """Decimal -> int when it has no fractional part (exact), else str (never float — money/precision
    rule, rules/code.md). date/datetime/time -> ISO string. bytes -> a marker (omitted, not sent raw).
    Long text is clipped to _CELL_MAX chars with a marker."""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else str(v)
    if isinstance(v, (datetime, date, dt_time)):
        return v.isoformat()
    if isinstance(v, bytes):
        return f"<binary omitted, {len(v)} bytes>"
    s = v if isinstance(v, str) else str(v)
    return s[:_CELL_MAX] + _TRUNC_MARK if len(s) > _CELL_MAX else s


_TYPE_NAMES = (
    (bool, "bool"),
    (int, "int"),
    (float, "float"),
    (Decimal, "decimal"),
    (datetime, "datetime"),
    (date, "date"),
    (dt_time, "time"),
    (bytes, "binary"),
    (str, "str"),
)


def _col_type(raw_rows, i):
    """Column type for the agent, taken from the first non-null RAW driver value (before JSON conversion), so
    a fractional DECIMAL (sent as an exact string like "12.50") is still typed "decimal" and the agent knows to
    parse it as a number. Order matters: bool before int, datetime before date. Unknown driver types -> "str"."""
    for r in raw_rows:
        v = r[i] if i < len(r) else None
        if v is not None:
            return next((name for t, name in _TYPE_NAMES if isinstance(v, t)), "str")
    return "unknown"


# ── connections ──────────────────────────────────────────────────────────


def _connect_sqlite(path, timeout):
    """Security review round 2, fix 4 — open the PC stand-in through SQLite's own `file:...?mode=ro`
    URI read-only flag (`uri=True` is required for the `?mode=ro` query string to be recognized at
    all). This means even a SQL-text guard bypass could not write: sqlite3 raises OperationalError
    ("attempt to write a readonly database") at the driver/OS level, independent of `validate()`.
    ATTACH/PRAGMA are already blocked keywords for user-supplied SQL (see `_BLOCKED_RE`) — this is
    about the connection's OWN internal self-attach (used so `AI.client` resolves exactly like it
    would in T-SQL), which now goes through the same read-only URI so that path can't write either."""
    from common.store import mssql

    conn = mssql.standin(
        path, readonly=True, timeout=min(timeout, 5)
    )  # one stand-in file ATTACHed per schema (AI·CRMS·LAS·SFDC), all ?mode=ro
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
    return conn


def _connect_mssql(conf, timeout):
    """SQLAlchemy가 연 DBAPI 연결(접속 인자 그대로). 질의 코드는 SQLite 대역과 같은 DBAPI 커서 꼴이라 그대로(도구 출력 같음)."""
    from common.store import mssql

    # conf = mssql.login("read") — 포트 형식은 거기서 이미 검사(_mssql_conf) · 시간 상한·문자셋은 이 도구 값이 이김
    return mssql.raw(**{**conf, "port": int(conf["port"]), "timeout": timeout, "login_timeout": min(timeout, 10), "charset": "UTF-8"})


def _connect(kind, conf, timeout):
    return _connect_sqlite(conf, timeout) if kind == "sqlite" else _connect_mssql(conf, timeout)


def _cap_cte_tsql(sql, n):
    """Security review round 2, fix 2 — a WITH (CTE) query can't be capped by wrapping it as a derived
    table in T-SQL (`SELECT TOP(n+1) * FROM (WITH ...) AS _q` is not valid — WITH must start its own
    statement). Instead, inject `TOP (n+1)` into the query's own single top-level SELECT: the one right
    after its CTE definitions, found the same way `_check_single_top_level_statement()` finds it (not a
    "second statement").
    Returns (rewritten_sql, None) on success or (sql, error_code) when it can't be safely capped:
      - "cte_union_not_capped": more than one top-level SELECT (a UNION/INTERSECT/EXCEPT) — TOP on a
        single branch would not cap the combined result, and wrapping the whole thing hits the same
        derived-table/ORDER BY restriction a plain wrap would. query() rejects rather than running it
        with only fetchmany+timeout to fall back on.
      - "cte_top_too_high": the final SELECT already has an explicit TOP greater than n — we do not
        lower someone else's explicit TOP ourselves (that changes which rows come back — a correctness
        question, not a safety one); the caller should lower it.
    An explicit TOP already <= n is left alone (already safely capped, no rewrite needed)."""
    tokens = _depth0_tokens(sql)
    selects = [t for t in tokens if t[2] == "SELECT"]
    if len(selects) != 1:
        return sql, "cte_union_not_capped"
    start, end, _ = selects[0]
    dm = re.match(r"\s+(?:DISTINCT|ALL)\b", sql[end:], re.IGNORECASE)  # TOP goes after DISTINCT/ALL
    if dm:
        end += dm.end()
    after = sql[end:]
    m = _TOP_AFTER_SELECT_RE.match(after)
    if m:
        pct = _top_percent_risk(after, m)  # TOP n PERCENT: plain 경로와 같은 거부(양쪽 같은 규칙)
        if pct:
            return sql, pct
        return (sql, None) if int(m.group(1)) <= n else (sql, "cte_top_too_high")
    return sql[:end] + f" TOP ({n + 1})" + after, None


def _top_percent_risk(after, m):
    """`TOP n PERCENT` (explicit TOP, CTE or plain): a percentage needs the *whole* input
    counted/materialized server-side, which is exactly the compute this row cap exists to bound
    (fetchmany only stops the reading). Rejected fail-closed in both T-SQL paths."""
    if re.match(r"\s*PERCENT\b", after[m.end() :], re.IGNORECASE):
        return "top_percent"
    return None


def _cap_plain_tsql(sql, n):
    """Plain-SELECT row cap, same policy as `_cap_cte_tsql` (never produce `SELECT TOP (n+1) TOP n …`):
    - explicit TOP <= n: left alone (already safely capped, no rewrite needed).
    - explicit TOP > n: "plain_top_too_high" — we do not lower someone else's explicit TOP ourselves (the
      CTE counterpart's rationale — a correctness question); the caller lowers the TOP or raises max_rows.
    - `TOP n PERCENT`: rejected ("top_percent" — see `_top_percent_risk`).
    - no TOP: inject `TOP (n+1)` after SELECT/DISTINCT/ALL."""
    m = re.match(r"^\s*SELECT(\s+(?:DISTINCT|ALL)\b)?", sql, re.IGNORECASE)
    end = m.end()  # _top_n() prefilters the first keyword — this can't miss
    after = sql[end:]
    t = _TOP_AFTER_SELECT_RE.match(after)
    if t:
        pct = _top_percent_risk(after, t)
        if pct:
            return sql, pct
        return (sql, None) if int(t.group(1)) <= n else (sql, "plain_top_too_high")
    return sql[:end] + f" TOP ({n + 1})" + after, None


def _top_n(sql, n, dialect):
    """Security review round 2, fix 2 — cap the query at the DB side (defense in depth on top of
    fetchmany: without this, a cartesian-product CTE/cross-join still fully computes server-side
    before fetchmany ever gets a chance to stop it — confirmed by hand: an uncapped 40^5-row cross
    join against the bundled sample hangs, the same query wrapped with an outer LIMIT returns in under
    a millisecond, because SQLite pushes the LIMIT into the nested-loop evaluation).
    sqlite: wraps the whole statement uniformly (`SELECT * FROM (<q>) AS _q LIMIT n+1`) — this works for
    both plain SELECT and WITH alike, since SQLite (unlike SQL Server) allows a WITH clause inside a
    derived table and has no "ORDER BY needs TOP/OFFSET in a subquery" restriction.
    tsql: a plain SELECT is delegated to `_cap_plain_tsql()` (explicit TOP/PERCENT aware);
    a WITH query is delegated to `_cap_cte_tsql()` (see its docstring for the union/explicit-TOP edge cases
    it rejects on).
    Returns (rewritten_sql, None) on success or (original_sql, error_code) when it can't be
    safely capped — callers must check the error before executing."""
    if dialect == "sqlite":
        return f"SELECT * FROM ({sql}) AS _q LIMIT {n + 1}", None
    if re.match(r"^\s*WITH\b", sql, re.IGNORECASE):
        return _cap_cte_tsql(sql, n)
    if re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        return _cap_plain_tsql(sql, n)
    return sql, None  # unreachable given validate()'s first_keyword gate (SELECT/WITH only)


# ── query_edw ────────────────────────────────────────────────────────────


def _row_budget(max_rows):
    """실효 상한 = max(1, min(max_rows, EDW_QUERY_MAX_ROWS)). 기본 1000행(운영 서버와 같게 도구 기본과 설정 기본이 같음). 0은 1행."""
    return max(1, min(int(max_rows), int(mc.cfg().edw_query.max_rows)))


def query(sql, max_rows=1000):
    """Run one read-only SELECT/WITH against EDW and return a JSON-safe result (see QueryResult).
    The call (SQL in args, result) is recorded by the MCP audit log applog.mcp_log, not here."""
    t0 = time.monotonic()
    kind, conf = backend()
    if kind is None:
        return _finish("tsql", "none", "not_configured", "EDW query backend not configured", t0)
    dialect = dialect_of(kind)
    allowed = allowed_tables(kind)
    if allowed is not None and not allowed:
        return _finish(dialect, kind, "not_configured_tables", "no tables are allowlisted for this backend", t0)
    cap_rows = _row_budget(max_rows)
    clean, err = validate(sql, allowed)
    if err:
        return _finish(dialect, kind, f"rejected:{err}", "query rejected by the read-only SQL guard", t0)
    capped_sql, cap_err = _top_n(clean, cap_rows, dialect)
    if cap_err:
        return _finish(dialect, kind, f"rejected:{cap_err}", "query rejected by the read-only SQL guard", t0)
    q = mc.cfg().edw_query  # 한 번에 묶어 읽음(S7d)
    timeout = float(q.timeout_sec)
    max_bytes = int(q.max_bytes)
    try:
        conn = _connect(kind, conf, timeout)
    except Exception as e:
        print(f"[mcp] edw_query connect failed ({kind}): {type(e).__name__}: {e}", flush=True)
        return _finish(dialect, kind, "connect_failed", "could not connect to EDW", t0)
    try:
        cur = conn.cursor()
        try:
            cur.execute(capped_sql)
            cols = [d[0] for d in (cur.description or [])]
            raw_rows = cur.fetchmany(cap_rows + 1)
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                print(f"[mcp] edw_query timeout after {time.monotonic() - t0:.1f}s: {sql[:200]!r}", flush=True)
                return _finish(dialect, kind, "timeout", "query exceeded the time limit", t0)
            raise
        except Exception as e:
            elapsed = time.monotonic() - t0
            code = "timeout" if elapsed >= timeout else "query_failed"
            print(f"[mcp] edw_query execute failed ({code}): {type(e).__name__}: {e} — sql={sql[:200]!r}", flush=True)
            return _finish(dialect, kind, code, "query failed" if code == "query_failed" else "query exceeded the time limit", t0)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    truncated_rows = len(raw_rows) > cap_rows
    raw_rows = raw_rows[:cap_rows]
    rows = [[_json_safe_cell(v) for v in r] for r in raw_rows]
    columns = [{"name": c, "type": _col_type(raw_rows, i)} for i, c in enumerate(cols)]
    rows, size_truncated = _cap_bytes(rows, max_bytes, columns)
    result = {
        "ok": True,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated_rows or size_truncated,
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        "dialect": dialect,
        "source": kind,
        "error": None,
    }
    return result


def _cap_bytes(rows, max_bytes, columns):
    """Drop rows from the tail until the JSON-encoded rows (+columns, a fixed small overhead) fit
    max_bytes. Simpler than mcp_server.cap()'s rank-aware shrink — query_edw rows have no rank to
    protect, so trimming the tail is enough."""
    import json

    truncated = False
    while rows and len(json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False).encode("utf-8")) > max_bytes:
        rows.pop()
        truncated = True
    return rows, truncated


def _finish(dialect, source, error_code, message, t0):
    elapsed = round((time.monotonic() - t0) * 1000, 1)
    return {
        "ok": False,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "elapsed_ms": elapsed,
        "dialect": dialect,
        "source": source,
        "error": f"{error_code}: {message}",
    }


# ── describe_edw ─────────────────────────────────────────────────────────


def _describe_table_sqlite(conn, table):
    bare = table.rpartition(".")[-1]
    info = conn.execute(f"PRAGMA AI.table_info('{bare}')").fetchall()  # bare is allowlist-checked by the caller
    cols = [{"name": r[1], "type": r[2] or "unknown", "nullable": not r[3]} for r in info]
    try:
        row_count = conn.execute(f"SELECT COUNT(*) FROM AI.{bare}").fetchone()[0]
    except Exception:
        row_count = None
    sample = conn.execute(f"SELECT * FROM AI.{bare} LIMIT 3").fetchall()
    sample_cols = [d[0] for d in conn.execute(f"SELECT * FROM AI.{bare} LIMIT 0").description]
    return cols, row_count, [dict(zip(sample_cols, (_json_safe_cell(v) for v in r))) for r in sample]


def _describe_table_mssql(conn, schema, bare):
    cur = conn.cursor()
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
        (schema, bare),
    )
    cols = [{"name": r[0], "type": r[1], "nullable": r[2] == "YES"} for r in cur.fetchall()]
    try:
        cur.execute(
            "SELECT SUM(p.rows) FROM sys.partitions p JOIN sys.tables t ON t.object_id=p.object_id "
            "JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=%s AND t.name=%s AND p.index_id IN (0,1)",
            (schema, bare),
        )
        row = cur.fetchone()
        row_count = int(row[0]) if row and row[0] is not None else None
    except Exception:
        row_count = None
    cur.execute(f"SELECT TOP 3 * FROM [{schema}].[{bare}]")
    sample_cols = [d[0] for d in cur.description]
    sample = [dict(zip(sample_cols, (_json_safe_cell(v) for v in r))) for r in cur.fetchall()]
    return cols, row_count, sample


def describe(table=None):
    """No table: every allowed table with its columns + row_count (best-effort/cheap — sys.partitions
    metadata on SQL Server, a plain COUNT(*) on the tiny SQLite sample). With a table: that table's
    columns + 3 sample rows. Always carries `dialect` so the caller knows TOP vs LIMIT."""
    kind, conf = backend()
    if kind is None:
        return {"ok": False, "dialect": "tsql", "error": "not_configured: EDW query backend not configured"}
    dialect = dialect_of(kind)
    allowed = allowed_tables(kind)  # 기본 None = 전 스키마 허용
    if allowed is None:
        return {
            "ok": False,
            "dialect": dialect,
            "error": "전 스키마 허용 모드(describe_edw 미지원) — 필요한 테이블·열은 직접 SELECT 로 확인",
        }
    allowed = sorted(allowed)
    if not allowed:
        return {"ok": False, "dialect": dialect, "error": "not_configured_tables: no tables are allowlisted for this backend"}
    if table is not None and table.lower() not in allowed:
        return {"ok": False, "dialect": dialect, "error": f"rejected:table:{table}: not on the allowlist"}
    timeout = float(mc.cfg().edw_query.timeout_sec)
    try:
        conn = _connect(kind, conf, timeout)
    except Exception as e:
        print(f"[mcp] edw_query describe connect failed ({kind}): {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "dialect": dialect, "error": "connect_failed: could not connect to EDW"}
    try:
        targets = [table.lower()] if table is not None else allowed
        tables = []
        for t in targets:
            schema, _, bare = t.rpartition(".")
            try:
                if kind == "sqlite":
                    cols, row_count, sample = _describe_table_sqlite(conn, t)
                else:
                    cols, row_count, sample = _describe_table_mssql(conn, schema, bare)
            except Exception as e:
                print(f"[mcp] edw_query describe failed for {t}: {type(e).__name__}: {e}", flush=True)
                continue
            tables.append({"name": t, "columns": cols, "row_count": row_count, "sample_rows": sample if table is not None else None})
        if table is not None:
            if not tables:
                return {"ok": False, "dialect": dialect, "error": f"query_failed:{table}: could not read that table"}
            t = tables[0]
            return {
                "ok": True,
                "dialect": dialect,
                "table": {"name": t["name"], "columns": t["columns"], "row_count": t["row_count"]},
                "sample_rows": t["sample_rows"],
            }
        return {
            "ok": True,
            "dialect": dialect,
            "tables": [{"name": t["name"], "columns": t["columns"], "row_count": t["row_count"]} for t in tables],
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
