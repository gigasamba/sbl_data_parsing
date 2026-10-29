"""판 표 2개 — 엔진 구성 `struct.stack_version`·원천 목록 `struct.source_version` 읽기·쓰기(S8b — D-031, 사용자 10-28 Q1~Q10 a).
· 서버(RUN_ENV dev·prd, 또는 이미지 배치): DB 활성 판(is_active) — 프로세스마다 한 번 읽어 캐시(active). DB·판 표에 못 붙거나 활성 판이
  없으면 시작 거부(종료 코드 4 — Q7). PC(paths.LOCAL_RUN): 파일(common.paths.stack_file·sources_file — 비우면 resources/ 아래).
· 판 행은 고치지 않는다 — 바꾸기 = 새 행 + 활성 옮기기(한 트랜잭션, put), 같은 body면 그 판을 다시 활성(activate). 활성 옮김은 activated_at·_by에.
· body_sha = 정규 JSON(키 정렬·공백 없음·UTF-8)의 sha256 — 같은 구성이면 서버·PC 같은 값.
· 층 파일은 이 모듈을 import하지 않는다(code_fp — D-030 ⑦·Q10): 진입점이 사본 파일을 만들어 넘긴다(pipeline/stackcfg.py).
· 값·비밀은 찍지 않는다(판 번호·이름·sha만 — 엔진 이름·원천 표 이름은 설정이라 찍음)."""

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

KINDS = {"stack": "stack_version", "sources": "source_version"}
SCHEMA = "struct"
EXIT_NO_DB = 4  # 모듈 종료 코드 규칙(4 = PostgreSQL 없음 — pipeline.cli)
_CACHE: dict = {}
_ENGINE: dict = {}


class ConfigUnavailable(SystemExit):
    """서버에서 판 표를 못 읽음 — 안내를 찍고 종료 코드 4(시작 거부 — Q7)."""

    def __init__(self, msg):
        print(f"[판 표] {msg}", file=sys.stderr, flush=True)
        super().__init__(EXIT_NO_DB)


@dataclass(frozen=True)
class Active:
    kind: str
    version_id: int | None  # PC 파일이면 None
    name: str
    body: object  # stack: dict · sources: list
    body_sha: str
    origin: str  # "db struct.stack_version" | 파일 경로

    def named(self):
        """body + name — 옛 stack.json 꼴(검색 MCP·ask가 읽는 사전)."""
        return {"name": self.name, **self.body}

    def label(self):
        return f"{self.kind} 판 {self.version_id if self.version_id is not None else '파일'} {self.name} · sha {self.body_sha[:12]} · {self.origin}"


def canon(body):
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(body):
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


def check_body(kind, body):
    """모양 검사(pydantic — schemas/config_body.py). 틀리면 ValueError(칸·이유)."""
    from pydantic import ValidationError

    from common.store.db.schemas import config_body as CB

    try:
        (CB.StackBody if kind == "stack" else CB.SourcesBody).model_validate(body)
    except ValidationError as e:
        raise ValueError(
            f"{KINDS[kind]} body 모양이 틀림: " + "; ".join(f"{'.'.join(map(str, x['loc'])) or '-'} {x['msg']}" for x in e.errors())
        ) from None
    return body


# ── PC 파일 ────────────────────────────────────────────────────────────
def pc_file(kind):
    from common.config.settings import cfg
    from common.core.paths import STACK_FILE
    from common.core.sources import DEFAULT_FILE

    p = cfg().paths
    return Path((p.stack_file if kind == "stack" else p.sources_file) or (STACK_FILE if kind == "stack" else DEFAULT_FILE))


def read_file(kind, path=None):
    """파일 → Active(판 번호 없음). stack 파일 = body 칸 + name(+ updated·client_aliases), sources 파일 = 목록."""
    from common.store.db.schemas import config_body as CB

    p = Path(path) if path else pc_file(kind)
    doc = json.loads(p.read_text(encoding="utf-8"))
    if kind == "stack":
        from pydantic import ValidationError

        try:
            name, body = CB.stack_body(doc)
        except (
            ValidationError
        ) as e:  # 칸 이름·이유만(값은 안 찍음) — 옛 꼴 메모 칸(storage·*_note)은 S8b부터 docs/architecture/pipeline_stack.md로(VS8b R-4)
            raise ValueError(
                f"{p}: 엔진 구성 파일 모양이 틀림 — "
                + "; ".join(f"{'.'.join(map(str, x['loc'])) or '-'} {x['msg']}" for x in e.errors())
                + " · 메모 칸(storage·*_note)은 S8b부터 이 파일에 두지 않음(docs/architecture/pipeline_stack.md)"
            ) from None
    else:
        name, body = p.stem, check_body(kind, doc)
    return Active(kind, None, name, body, sha(body), str(p))


# ── DB ───────────────────────────────────────────────────────────────
def _rows(conn, sql, params=None):
    res = conn.exec_driver_sql(sql, params or {})
    return [dict(r._mapping) for r in res.fetchall()] if res.returns_rows else []


def _table(conn, kind):
    t = f"{SCHEMA}.{KINDS[kind]}"
    if not _rows(conn, f"SELECT 1 AS x WHERE to_regclass('{t}') IS NOT NULL"):
        raise ConfigUnavailable(
            f"{t} 표 없음 — struct 판을 올려야 함(migrate up --target struct, docs/operations/release-and-patch.md §5-5)"
        )
    return t


def read_db(kind, conn):
    t = _table(conn, kind)
    r = _rows(conn, f"SELECT version_id, name, body, body_sha FROM {t} WHERE is_active")
    if not r:
        raise ConfigUnavailable(f"{t}에 활성 판 없음 — set-{'stack' if kind == 'stack' else 'sources'} --activate <판 번호>")
    r = r[0]
    body = r["body"] if not isinstance(r["body"], str) else json.loads(r["body"])
    if sha(body) != r["body_sha"]:
        raise ConfigUnavailable(f"{t} 판 {r['version_id']}: body_sha가 body와 다름 — 판 행이 바뀜(사람 확인)")
    check_body(kind, body)
    return Active(kind, r["version_id"], r["name"], body, r["body_sha"], f"db {t}")


def connect():
    """판 표 연결(settings.yaml PG 접속 — dbtool.engine). 실패는 ConfigUnavailable(종료 4)."""
    from common.store.db import dbtool
    from common.store.pg import has_conn

    if not has_conn():
        raise ConfigUnavailable(
            "PostgreSQL 접속 정보 없음(settings.yaml common.connections.pg) — 서버는 판 표에서 엔진 구성·원천 목록을 읽음"
        )
    try:
        from common.store.pg import conf

        key = hashlib.sha256(repr(sorted(conf().items())).encode("utf-8")).hexdigest()  # 접속 값마다 엔진 하나(값은 해시로만)
        if key not in _ENGINE:  # 연결은 NullPool — 매번 새로, 방언 첫 연결 준비만 한 번
            _ENGINE[key] = dbtool.engine()
        conn = _ENGINE[key].connect()
    except Exception as e:
        raise ConfigUnavailable(f"PostgreSQL에 못 붙음({type(e).__name__}) — 판 표를 읽지 못해 시작하지 않음") from None
    return conn


def active(kind, refresh=False):
    """지금 쓸 판 — PC는 파일, 서버는 DB 활성 판(프로세스마다 한 번 — refresh=True면 다시 읽음: 작업마다 읽는 서비스)."""
    from common.core import paths

    if kind in _CACHE and not refresh:
        return _CACHE[kind]
    if paths.LOCAL_RUN:
        try:
            a = read_file(kind)
        except (OSError, ValueError) as e:  # 트레이스백 대신 한 줄 안내 + 종료 2(VS8b R-4)
            print(f"[판 표] PC {KINDS[kind]} 파일을 쓰지 못함 — {e}", file=sys.stderr, flush=True)
            raise SystemExit(2) from None
    else:
        with connect() as conn:
            try:
                a = read_db(kind, conn)
            except SystemExit:
                raise
            except Exception as e:  # 모양 검사 실패(ValueError)·권한 없음 등 DB 오류도 시작 거부(Q7 — 종료 4)
                raise ConfigUnavailable(
                    f"{SCHEMA}.{KINDS[kind]} 활성 판을 쓰지 못함 — {type(e).__name__}: {str(e).splitlines()[0][:200]}"
                ) from None
            finally:
                try:
                    conn.rollback()
                except Exception:  # 끊긴 연결 — rollback 오류가 위 종료 4(ConfigUnavailable)를 덮지 않게(VS8b R-5)
                    pass
    _CACHE[kind] = a
    return a


def version_body(kind, version_id, conn):
    """그 판의 body(없으면 None) — 되돌리기(--activate) 전 검사용."""
    r = _rows(conn, f"SELECT body FROM {_table(conn, kind)} WHERE version_id = %(v)s", {"v": int(version_id)})
    return r[0]["body"] if r else None


def lock_active(kind, conn):
    """쓰기 트랜잭션 안에서 활성 판을 잠그고 그 번호(없으면 None) — 동시에 바꾸는 쪽은 앞 트랜잭션이 끝날 때까지 기다린 뒤 바뀐 활성을 본다."""
    r = _rows(conn, f"SELECT version_id FROM {_table(conn, kind)} WHERE is_active FOR UPDATE")
    return r[0]["version_id"] if r else None


def history(kind, conn, n=10):
    t = _table(conn, kind)
    return _rows(
        conn,
        f"SELECT version_id, name, body_sha, is_active, created_at, created_by, reason, activated_at, activated_by "
        f"FROM {t} ORDER BY version_id DESC LIMIT {int(n)}",
    )


def activate(kind, version_id, by, conn):
    """그 판을 활성으로(지금 활성은 끔) — 호출자 트랜잭션 안에서. 없는 판이면 ValueError."""
    t = _table(conn, kind)
    if not _rows(conn, f"SELECT 1 AS x FROM {t} WHERE version_id = %(v)s", {"v": int(version_id)}):
        raise ValueError(f"{t}에 판 {version_id} 없음")
    conn.exec_driver_sql(f"UPDATE {t} SET is_active = false WHERE is_active AND version_id <> %(v)s", {"v": int(version_id)})
    conn.exec_driver_sql(
        f"UPDATE {t} SET is_active = true, activated_at = now(), activated_by = %(by)s WHERE version_id = %(v)s AND NOT is_active",
        {"v": int(version_id), "by": by},
    )
    _CACHE.pop(kind, None)
    return int(version_id)


def put(kind, name, body, by, reason, conn):
    """새 판을 넣고 활성으로(호출자 트랜잭션 — 한 번에). 같은 body(sha)가 이미 있으면 새 행 대신 그 판을 활성으로.
    반환: (판 번호, 새로 넣었나)."""
    t = _table(conn, kind)
    check_body(kind, body)
    s = sha(body)
    have = _rows(conn, f"SELECT version_id FROM {t} WHERE body_sha = %(s)s", {"s": s})
    if have:
        return activate(kind, have[0]["version_id"], by, conn), False
    v = _rows(
        conn,
        f"INSERT INTO {t} (name, body, body_sha, created_by, reason) VALUES (%(n)s, %(b)s::jsonb, %(s)s, %(by)s, %(r)s) "
        f"RETURNING version_id",
        {"n": name, "b": json.dumps(body, ensure_ascii=False), "s": s, "by": by, "r": reason},
    )[0]["version_id"]
    return activate(kind, v, by, conn), True


def seed(kind):
    """판 0002가 넣는 시드(resources/sql/0002_*_seed.json — 한 번 배포하면 고치지 않음) → (name, reason, body)."""
    from common.core.paths import RES_ROOT

    doc = json.loads((RES_ROOT / "sql" / f"0002_{kind}_seed.json").read_text(encoding="utf-8"))
    return doc["name"], doc["reason"], check_body(kind, doc["body"])
