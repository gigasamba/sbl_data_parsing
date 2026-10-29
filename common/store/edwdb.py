"""EDW(SQL Server) 연결 — 적재(pipeline/load/edw_insert.py, EDW_LOAD=1일 때만)·검색(mcp_server/services/search/edw_search.py)이 같이 쓰는 것만
(접속 설정 conf·연결 DB·벡터 표 확인 vec_table). 적재 전용(caps·NATIVE_MAX)은 edw_insert로(사용자 10-14 모듈별 분리).
접속: EDW_CONN_FILE 또는 EDW_SERVER · EDW_PORT · EDW_DATABASE · EDW_USER · EDW_PASSWORD · EDW_SCHEMA · EDW_DRIVER — 비밀번호는 파일·환경변수에만."""

import re
from pathlib import Path

from common.config.settings import cfg, checked, given, reveal


def conf():
    c = {}
    st = cfg().connections.edw  # S7b — 설정 객체(옛 os.environ.get)
    f = st.conn_file
    if f and Path(f).exists():
        for ln in Path(f).read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                c[k.strip()] = v.strip()
    # 옛 `if os.environ.get(k): c[k] = os.environ[k]` — env로 실제 준(비지 않은) 값만 파일 값을 덮음. 기본값 있는 칸(driver·port·
    # schema·encrypt 등)이 기본값으로 덮지 않게 given()(준 값만 — 빈 값·기본값은 None). 값은 옛처럼 글자(포트도 str)
    checked("EDW_PORT")  # 형식 틀린 포트는 옛처럼 실패(VS7b R-7 — 파일·기본 포트로 조용히 붙지 않게)
    for k in (
        "EDW_SERVER",
        "EDW_PORT",
        "EDW_DATABASE",
        "EDW_USER",
        "EDW_PASSWORD",
        "EDW_SCHEMA",
        "EDW_DRIVER",
        "EDW_ODBC_DRIVER",
        "EDW_ENCRYPT",
        "EDW_TRUST_CERT",
    ):
        v = given(k)
        if v is not None:
            c[k] = str(reveal(v))
    c.setdefault("EDW_PORT", "1433")
    c.setdefault("EDW_SCHEMA", "AI")
    c.setdefault("EDW_DRIVER", "pymssql")
    miss = [
        k for k in ("EDW_SERVER", "EDW_DATABASE", "EDW_USER", "EDW_PASSWORD") if not c.get(k)
    ]  # S7e2(VS7e1 R-10, D-028 ⑨) — 계정도 설정 필수(옛 코드 기본 계정 이름 없앰)
    if miss:
        raise SystemExit(f"EDW 접속 정보 없음: {', '.join(miss)} — settings.yaml common.connections.edw 또는 EDW_CONN_FILE(S7e2)")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", c["EDW_SCHEMA"]):
        raise SystemExit("EDW_SCHEMA는 영문·숫자·_ 만")
    return c


class DB:
    def __init__(self, c):
        self.schema = c["EDW_SCHEMA"]
        if c["EDW_DRIVER"] == "pyodbc":
            import pyodbc

            cs = (
                f"DRIVER={{{c.get('EDW_ODBC_DRIVER', 'ODBC Driver 18 for SQL Server')}}};SERVER={c['EDW_SERVER']},{c['EDW_PORT']};"
                f"DATABASE={c['EDW_DATABASE']};UID={c['EDW_USER']};PWD={c['EDW_PASSWORD']};"
                f"Encrypt={c.get('EDW_ENCRYPT', 'yes')};TrustServerCertificate={c.get('EDW_TRUST_CERT', 'yes')}"
            )
            self.cn = pyodbc.connect(cs, autocommit=True)
            self.ph = "?"
        else:
            from common.store import (
                mssql,
            )  # S8b(5-4) — SQLAlchemy가 연 연결(인자 그대로) · q·run_file은 여러 결과 집합을 읽어 DBAPI 커서 그대로

            self.cn = mssql.raw(
                server=c["EDW_SERVER"],
                port=int(c["EDW_PORT"]),
                user=c["EDW_USER"],
                password=c["EDW_PASSWORD"],
                database=c["EDW_DATABASE"],
                autocommit=True,
                charset="UTF-8",
            )
            self.ph = "%s"

    def close(self):
        """연결 닫기(VS8b R-7 — S8b부터 풀 프록시라 닫지 않고 버리면 GC 때 경고가 날 수 있음). 두 번 불러도 됨."""
        cn, self.cn = getattr(self, "cn", None), None
        if cn is not None:
            cn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def q(self, sql, params=(), fetch=True):
        cur = self.cn.cursor()
        cur.execute(sql.replace("%s", self.ph) if self.ph != "%s" else sql, params)
        rows = []
        if fetch:
            while True:  # 프로시저가 여러 결과 집합을 낼 때 마지막 것
                try:
                    if cur.description:
                        cols = [d[0] for d in cur.description]
                        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                except Exception:
                    pass
                if not cur.nextset():
                    break
        cur.close()
        return rows

    def run_file(self, name, **fmt):
        text = Path(name).read_text(encoding="utf-8").replace("{S}", self.schema)
        for k, v in fmt.items():
            text = text.replace("{" + k + "}", str(v))
        for batch in re.split(r"^\s*GO\s*$", text, flags=re.M | re.I):
            if batch.strip():
                self.q(batch, fetch=False)


def vec_table(db):
    """→ ('native', 'chunk_vec') · ('narrow', 'chunk_vec_n') · (None, None)."""
    r = db.q(f"""SELECT CASE WHEN OBJECT_ID(N'[{db.schema}].[chunk_vec]') IS NOT NULL THEN 'native'
                        WHEN OBJECT_ID(N'[{db.schema}].[chunk_vec_n]') IS NOT NULL THEN 'narrow' END AS m""")[0]["m"]
    return r, {"native": "chunk_vec", "narrow": "chunk_vec_n"}.get(r)
