"""DB 시험 도우미(e2-22) — 배포 판정 시험의 DB 사례는 진짜 pgvector(settings.yaml required.pg)에 붙는다(sqlite 대역 없음).
- schema(): 임시 기준 스키마 `test_<무작위>`를 만들 이름으로 주고(설정 PG_SCHEMA도 그 이름 — 자식 프로세스까지) 끝나면 그 이름과
  그 이름으로 시작하는 스키마(원천 `_sfdc`…·`_master`·`_applog`)를 지운다. 지우기 전에 이름이 test_로 시작하는지 다시 본다.
- db_write_allowed(): local·dev만 True — prd(운영 DB)는 읽기 시험만, 쓰는 사례는 SKIP(need_write).
- PG 접속 정보가 없거나 닿지 않으면 사례는 FAIL(AssertionError — 까닭을 적음). 조용히 통과하지 않는다.

    with pgcase.schema() as s:      # 쓰는 사례 — prd면 SKIP
        ...                          # s = test_xxxxxxxx, cfg().connections.pg.db_schema == s
"""

import atexit
import secrets
import unittest
from contextlib import contextmanager

from common.config import settings as S

_LEFT: set[str] = set()  # 아직 안 지운 임시 스키마 — 시험이 중간에 죽어도 프로세스 끝에서 지움


def db_write_allowed():
    return S.guard_run_env() in ("local", "dev")


def need_write():
    if not db_write_allowed():
        raise unittest.SkipTest(f"RUN_ENV={S.guard_run_env()} — 운영 DB에는 쓰지 않음(읽기 시험만 — e2-22)")


def connect(schema=None):
    """설정의 PG에 붙은 PG 객체(schema = PG_SCHEMA 덮기). 접속 정보가 없거나 못 붙으면 AssertionError(까닭만 — 비밀값 없음)."""
    from common.store.pg import PG, conf

    try:
        c = conf()
    except SystemExit as e:
        raise AssertionError(f"DB 시험 — PG 접속 정보 없음({e}) · 판정 명령에 설정 파일(required.pg)이 있어야 함") from None
    for tries in (1, 0):
        try:
            return PG({**c, "PG_SCHEMA": schema or c["PG_SCHEMA"]})
        except Exception as e:
            if tries and _start_local_pg(c):
                continue
            raise AssertionError(
                f"DB 시험 — PG {c['PG_HOST']}:{c['PG_PORT']}에 붙지 못함({type(e).__name__}) · 판정 명령이 PG에 닿아야 함(host 네트워크)"
            ) from None
    raise AssertionError("unreachable")


def _start_local_pg(c):
    """PC(local)만 — 시험 pgvector 컨테이너(required.deploy.pg_container_name)가 멈춰 있으면 docker start, 없으면 docker run
    (settings.yaml required.pg의 포트·DB·계정·비밀번호로 — 1 GB·2 CPU), 그다음 pg_isready를 60초까지 기다린다. 띄웠으면 True."""
    import subprocess
    import time

    from common.config.settings import cfg
    from common.core import paths

    name = cfg().host.pg_container
    if not paths.LOCAL_RUN or not name:
        return False
    try:
        st = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Status}}"], capture_output=True, text=True)
    except OSError:  # docker 명령이 없음(FileNotFoundError) — 뒤의 docker 호출은 이 첫 호출이 된 뒤에만
        return False
    if st.returncode:
        return False  # docker 데몬 없음
    if not st.stdout.strip():
        env = S.child_env(None)
        env["POSTGRES_PASSWORD"] = c["PG_PASSWORD"]  # env 남김 — 하위 프로세스(docker run -e 이름만 — 값은 명령 줄에 안 보임)
        # fmt: off
        cmd = ["docker", "run", "-d", "--name", name, "--restart", "no", "--memory", "1g", "--cpus", "2",
               "-p", f"127.0.0.1:{c['PG_PORT']}:5432", "-v", "sbl_mcp_pgdata:/var/lib/postgresql/data",
               "-e", f"POSTGRES_DB={c['PG_DB']}", "-e", f"POSTGRES_USER={c['PG_USER']}", "-e", "POSTGRES_PASSWORD",
               cfg().dev.docker.pg_image]  # 이미지가 없으면 내려받음(폐쇄망 PC는 먼저 docker load -i <pgvector tar>)
        # fmt: on
        ok = subprocess.run(cmd, env=env, capture_output=True).returncode == 0
    elif not st.stdout.startswith("Up"):
        ok = subprocess.run(["docker", "start", name], capture_output=True).returncode == 0
    else:
        return False  # 이미 떠 있는데 못 붙음 — 접속 정보 문제
    for _ in range(60):
        if (
            ok
            and subprocess.run(  # -h: TCP로 물음 — 처음 만들 때의 초기화용 서버(소켓만)는 준비됨으로 보지 않음
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", c["PG_USER"], "-d", c["PG_DB"]], capture_output=True
            ).returncode
            == 0
        ):
            return True
        time.sleep(1)
    return False


def drop(name):
    """name과 `name_*` 스키마를 지운다 — test_로 시작하는 이름만."""
    assert name.startswith("test_") and len(name) > len("test_"), name
    db = connect()
    try:
        for r in db.q("SELECT schema_name AS s FROM information_schema.schemata"):
            s = r["s"]
            if (s == name or s.startswith(name + "_")) and s.startswith("test_"):
                db.q(f'DROP SCHEMA "{s}" CASCADE')
    finally:
        db.cn.close()
    _LEFT.discard(name)


@atexit.register
def _drop_left():
    for name in list(_LEFT):
        drop(name)


def new_name():
    """쓰는 사례용 임시 스키마 이름(prd면 SKIP). 지우기는 drop(name) — 안 부르면 프로세스 끝에서."""
    need_write()
    connect().cn.close()  # 접속 확인 먼저(못 붙으면 FAIL)
    name = f"test_{secrets.token_hex(4)}"
    _LEFT.add(name)
    return name


def fill_master(base):
    """`<base>_master` 판 올리기 + git glossary.csv로 채움(PC·서버 모두 같은 CSV — 검색·구조화가 읽는 마스터)."""
    from common.store import master
    from common.store.db import dbtool

    s = dbtool.schema_of("master", base)
    assert s.startswith("test_"), s
    dbtool.upgrade("master", s)
    db = connect(s)
    try:
        master.load(db)
    finally:
        db.cn.close()
    master.reset()


@contextmanager
def schema(**names):
    """임시 기준 스키마 이름 — 그동안 설정 PG_SCHEMA(+ names)를 덮고(S.isolated — 자식 프로세스도), 끝나면 지움."""
    name = new_name()
    try:
        with S.isolated(PG_SCHEMA=name, **names):
            yield name
    finally:
        drop(name)


@contextmanager
def with_master(**names):
    """schema() + 그 마스터 표를 git CSV로 채움 — 용어집·고객 명부를 읽는 사례(구조화·검색)."""
    with schema(**names) as name:
        fill_master(name)
        try:
            yield name
        finally:
            from common.store import master

            master.reset()
