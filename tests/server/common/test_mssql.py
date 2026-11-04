"""common.store.mssql 자기 점검."""

from common.store.mssql import _ENGINES, clear, connect, raw, rows


class FakeConnection:
    """시험용 pymssql 연결 — handler(sql, params) → (칸 이름들, 행 튜플들). 방언의 첫 연결 카탈로그 질의는 여기서 대답한다(실제 접속 없음)."""

    _CATALOG: tuple = (
        ("@@version", ("v",), [("Microsoft SQL Server 2019 (RTM) - 15.0.2000.5",)]),
        ("schema_name()", ("s",), [("dbo",)]),
        ("sys.system_views", ("n",), [("dm_exec_sessions",)]),
        ("transaction_isolation_level", ("l",), [("READ COMMITTED",)]),
        ("nvarchar(max)", ("x",), [("test max support",)]),
        ("fn_listextendedproperty", ("x",), []),
    )

    def __init__(self, handler, log=None):
        self.handler, self.log, self.closed, self.commits = handler, (log if log is not None else []), False, 0

    def cursor(self, *a, **k):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class _FakeCursor:
    def __init__(self, cn):
        self.cn, self.description, self._rows, self.rowcount = cn, None, [], -1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        low = " ".join(str(sql).split()).lower()
        hit = next((c for c in FakeConnection._CATALOG if c[0] in low), None)
        if hit is None:
            self.cn.log.append((sql, params))
        cols, rows = (hit[1], hit[2]) if hit else self.cn.handler(sql, params)
        self.description = [(c, None, None, None, None, None, None) for c in cols] if cols else None
        self._rows = list(rows)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        r, self._rows = self._rows, []
        return r

    def fetchmany(self, n=1):
        r, self._rows = self._rows[:n], self._rows[n:]
        return r

    def nextset(self):
        return None

    def close(self):
        pass


def selftest():
    import pymssql

    log, made = [], []
    real = pymssql.connect
    pymssql.connect = lambda **kw: made.append(FakeConnection(lambda s, p: (("id", "name"), [(1, "a"), (2, "b")]), log)) or made[-1]
    try:
        clear()
        with connect(server="h", user="u", password="p", database="d") as c:
            got = rows(c, "SELECT [id], [name] FROM [AI].[T] WHERE [id] >= %s", (1,))
        assert got == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], got
        assert log == [("SELECT [id], [name] FROM [AI].[T] WHERE [id] >= %s", (1,))], log  # SQL 글자·자리 그대로
        assert made[0].closed
        n = len(made)
        with connect(server="h", user="u", password="p", database="d") as c:
            rows(c, "SELECT 1 AS x")
        assert len(_ENGINES) == 1 and len(made) == n + 1  # 같은 인자 → 같은 엔진(카탈로그 질의는 첫 연결만)
        sess = "SET ANSI_NULLS ON;"
        cn = raw(sess, server="h", user="u", password="p", database="d")
        assert made[-1].commits == 1 and len(_ENGINES) == 2  # 세션 옵션 = 첫 실행문(commit) · 다른 엔진
        cur = cn.cursor()
        cur.execute("SELECT 1")
        cn.close()
        assert made[-1].closed
    finally:
        pymssql.connect = real
        clear()
    print(
        "[selftest] mssql — SQLAlchemy mssql+pymssql(가짜 연결): SQL 글자·%s 자리 그대로·dict 행·닫힘·접속 인자마다 엔진 하나·세션 옵션 첫 실행문 통과"
    )
    return 0


def test_main():
    raise SystemExit(selftest())
