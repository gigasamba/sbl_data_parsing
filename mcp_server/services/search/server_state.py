"""검색 MCP 상태 — 리트리버(저장소 연결·재적재 확인)·예열·/health 본문."""

import sys
import threading
import time
import types

from common.store.db.models import search_tables as ST
from common.store.pg import PGPool, _standin_schema, _warn_standin, conf, has_conn  # 시험이 has_conn을 바꿔 끼움
from mcp_server import config as mc

_STATE: dict = {}


_RELOAD_LOCK = threading.Lock()


def _version_of(dbs):
    """적재 버전 표식(load 뒤 다시 읽기 확인) — 원천 스키마마다 (MAX(doc_id), COUNT(*)).
    --replace는 문서를 지우고 다시 넣어 새(더 큰) doc_id를 받으므로 개수가 같아도 MAX가 바뀐다. 표가 없거나 접속이 흔들리면 그 원천은 None
    (바뀜으로 보지 않음)."""
    out = []
    for src in sorted(dbs):
        db = dbs[src]
        try:
            r = db.q(f"SELECT COALESCE(MAX(doc_id), 0) AS m, COUNT(*) AS n FROM {db.schema}.doc")
            out.append((src, r[0]["m"], r[0]["n"]) if r else (src, None, None))
        except Exception:
            out.append((src, None, None))
    return tuple(out)


def _close_pool_later(pool, delay=5):
    """재적재로 교체된 이전 PGPool을 늦게 닫음 — 이미 시작된 요청이 끝날 시간을 줌.
    ponytail: 완벽한 보장은 아님(그 사이 두 번째 .q() 호출이 있으면 실패 가능) — 재적재 간격(기본 30초)에 비해 요청은 보통 짧아 실무 위험은 낮음."""

    def _close():
        time.sleep(delay)
        try:
            pool.pool.close()
        except Exception:
            pass

    threading.Thread(target=_close, daemon=True).start()


def check_store():
    """서버(dev·prd)에서 PG 접속 칸이 비면 SystemExit(채울 자리를 적음 — common.store.pg.conf). 검색 저장소는 PG 하나(
    저장소 종류 칸 mcp.server.store는 11-01에 없앰), PC는 칸이 비면 SQLite 대역. main이 시작 때 부른다(예열 스레드·요청 안에서는
    SystemExit가 조용히 스레드만 죽이므로)."""
    from common.core import paths

    if paths.LOCAL_RUN:
        return
    conf()


def _build_retriever():
    from common.store import pg as PGC
    from mcp_server.services.search import retriever as RT

    old = _STATE.get("Rs")
    try:
        check_store()  # 시작 때 이미 확인(main) — 설정이 그 뒤 바뀐 경우만 여기서 걸림
        from common.store import master

        master.reset()  # 마스터 표(용어집·고객 명부)를 여기서 미리 읽음: 비었거나 권한이 없으면 검색기를 안 만들고 오류로
        master.get()  # (요청 처리 중 처음 읽다 SystemExit로 예열 스레드만 조용히 죽지 않게)
    except SystemExit as e:  # 스레드·요청 안에서는 오류로(조용히 스레드만 죽지 않게)
        raise RuntimeError(str(e)) from None
    a = types.SimpleNamespace(pg=False, local=False, edw=False, edw_client=False)
    PGC.connect(a)  # PC — Docker pgvector 주소 찾기(못 찾으면 SQLite 대역 — 검색은 PG 하나)
    dbs = connect_sources()  # 원천 스키마 5벌 + 있는 DEV 원천 — 실 PG는 풀 하나를 함께 씀
    Rs, bad = {}, set()
    for src, db in list(dbs.items()):  # 색인 정보는 원천마다 PG에서
        R = _dev_retriever(src, db) if ST.is_dev(src) else RT.Retriever(pg=db)
        if R is None:  # 깨진 DEV 스키마는 싣지 않음 — 5벌은 그대로
            dbs.pop(src)
            bad.add(src)
        else:
            Rs[src] = R
    _STATE["bad_dev"] = bad
    _STATE["Rs"], _STATE["dbs"] = Rs, dbs
    _STATE["version"], _STATE["checked_at"] = _version_of(dbs), time.time()
    old_pool, _STATE["pool"] = _STATE.get("pool"), getattr(next(iter(dbs.values())), "pool_obj", None)
    if old is not None and old_pool is not None and old_pool is not _STATE["pool"]:
        _close_pool_later(old_pool)  # 실 PG 풀(대역은 None)


def _retriever(src):
    """원천(sfdc·crms·las·faq·other·있는 dev_<n>)의 Retriever. 처음엔 만들고, 이후엔 최소 MCP_RELOAD_CHECK_SEC(기본 30초) 간격으로 적재 버전이
    바뀌었는지만 확인해 바뀌었으면 다시 만든다. 재생성 중인 동시 요청은 기다리지 않고 기존 객체로 바로 응답(비차단 잠금)."""
    if "Rs" not in _STATE:
        with _RELOAD_LOCK:
            if "Rs" not in _STATE:
                _build_retriever()
        return _STATE["Rs"][src]
    if "dbs" not in _STATE:  # 시험이 Retriever를 직접 넣은 경우 — 재적재 대상 아님
        return _STATE["Rs"][src]
    interval = mc.cfg().server.reload_check_sec
    if time.time() - _STATE.get("checked_at", 0) >= interval and _RELOAD_LOCK.acquire(blocking=False):
        try:
            _STATE["checked_at"] = time.time()
            if _version_of(_STATE["dbs"]) != _STATE.get("version"):
                _build_retriever()  # 마스터 표도 다시 읽음(`dbtool master load` 뒤 반영)
        finally:
            _RELOAD_LOCK.release()
    return _STATE["Rs"][src]


def _dev_retriever(src, db):
    """DEV 원천 하나의 Retriever — 표가 없는 등 깨진 스키마면 경고 한 줄 + None(그 원천만 안 실음, op-17)."""
    from mcp_server.services.search import retriever as RT

    try:
        return RT.Retriever(pg=db)
    except Exception as e:
        print(f"[mcp] DEV 원천 스키마 {db.schema} 못 실음(그 원천만 뺌): {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return None


def dev_served():
    """지금 검색하는 DEV 원천(번호 순) — "어떤 DEV 원천이 있나"의 답은 여기 하나(search·원문 도구·edw_meta). 처음이면 검색기를 만들고,
    부를 때마다 DB(PC는 대역 폴더)를 한 번 찾아 그사이 생긴 스키마(dbtool up)는 그 원천만 더하고 사라진 것은 뺀다 — 재시작 없이.
    prd는 ST.dev_sources가 빈 목록(DEV 없음). 깨진 스키마는 한 번 경고하고 다음 전체 재생성까지 다시 시도하지 않는다."""
    _retriever("other")  # 처음이면 만듦 · 재적재 확인
    if "dbs" not in _STATE:  # 시험이 Retriever를 직접 넣은 경우
        return [s for s in _STATE["Rs"] if ST.is_dev(s)]
    other = _STATE["dbs"]["other"]
    standin = getattr(other, "is_standin", False)
    found = ST.dev_sources(ST.split_schema(other.schema)[0], None if standin else other.q)
    gone = [s for s in _STATE["Rs"] if ST.is_dev(s) and s not in found]
    new = {}
    for src in found:
        if src not in _STATE["Rs"] and src not in _STATE.get("bad_dev", ()):
            schema = ST.src_schema(ST.split_schema(other.schema)[0], src)
            if standin:
                from common.store.pg_standin import StandinPG

                db = StandinPG(schema)
            else:
                db = SchemaView(other.pool_obj, schema)
            new[src] = (db, _dev_retriever(src, db))
    if gone or new:
        ver = dict((v[0], v) for v in _version_of({s: db for s, (db, R) in new.items() if R}))
        with _RELOAD_LOCK:  # 바꿔 끼우기만(질의는 위에서) — 다른 요청이 도는 dict는 고치지 않고 새 dict로
            Rs = {s: R for s, R in _STATE["Rs"].items() if s not in gone}
            dbs = {s: db for s, db in _STATE["dbs"].items() if s not in gone}
            for src, (db, R) in new.items():
                if R is None:
                    _STATE["bad_dev"] = {*_STATE.get("bad_dev", ()), src}
                else:
                    Rs[src], dbs[src] = R, db
            old = {v[0]: v for v in _STATE.get("version") or () if v[0] not in gone}
            _STATE["Rs"], _STATE["dbs"], _STATE["version"] = Rs, dbs, tuple(sorted({**old, **ver}.values()))
    return [s for s in found if s in _STATE["Rs"]]


def dev_hint(found):
    """원천 값 오류 글 꼬리 — 있는 DEV 원천을 알림(없으면 빈 글자 — prd는 늘 비어 모르는 값과 같은 오류)."""
    return f" — 개발 서버 원천: {', '.join(map(ST.label, found))}" if found else ""


def _warmup(R):
    """첫 요청이 느리지 않게 기동 때 검색 1회로 검색기·질의 임베딩을 미리 로드한다.
    실패해도 기동은 계속(임베딩 API가 잠깐 안 될 때 서버가 안 뜨면 더 나쁨) — 경고 한 줄."""
    t0 = time.time()
    try:
        R.search("예열 warmup", 1)
        print(f"[mcp] 예열 {time.time() - t0:.1f}초", file=sys.stderr, flush=True)
        return True
    except Exception as e:  # 예열 실패는 첫 요청에서 다시 드러남
        print(f"[mcp] 예열 실패(기동은 계속): {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return False


def _warmup_bg():
    """백그라운드 스레드에서 예열(색인 로드 `_retriever()` + 질의 1회 `_warmup()`), 그 사이 `/health`는
    503 'warming'을 돌려줘 메인 스레드는 uvicorn을 바로 띄울 수 있다(첫 요청이 콜드스타트를 안 치르면 된다 — 서버
    자체가 안 뜨는 건 더 나쁘다). 색인 로드 자체가 실패해도(예: 임베딩 API 잠깐 다운) 예외를 올리지 않고
    기록만 — `/health`는 ready=True + warning 플래그로 계속 뜬다."""
    ok = None
    try:
        ok = _warmup(_retriever("sfdc"))  # 예열은 한 원천으로 충분(질의 임베딩·연결이 함께 데워짐)
    except Exception as e:  # 색인 로드 실패도 기동은 계속(첫 실제 요청에서 다시 드러남)
        print(f"[mcp] 예열 중 색인 로드 실패(기동은 계속): {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        ok = False
    finally:
        _STATE["warmup_ok"], _STATE["warmup_done"] = ok, True


def health_body():
    """가벼운 상태만(내부 경로는 안 보여줌). 예열 스레드가 아직 안 끝났으면
    warming=True(ready=False, 라우트가 503) · 끝났는데 실패했으면 ready=True + warning(서버는 계속 뜸).
    store="pgvector"일 때 db: "standin"(sqlite, common/pg_standin.py) | "pg"(진짜 PG) —
    서버에서 PG_PASSWORD를 빠뜨려 조용히 스탠드인으로 떨어진 경우를 /health만 보고도 알 수 있게."""
    Rs = _STATE.get("Rs") or {}
    R = next(iter(Rs.values()), None)
    done = _STATE.get("warmup_done", False)
    out = {
        "ok": True,
        "ready": bool(R is not None and done),
        "store": "pgvector" if R else None,
        "data_version": _STATE.get("version"),
    }
    if R is not None and R.pg:
        out["db"] = "standin" if getattr(R.pg, "is_standin", False) else "pg"
    if not done:
        out["warming"] = True
    elif _STATE.get("warmup_ok") is False:
        out["warning"] = "warmup_failed"
    return out


class SchemaView:
    """연결 풀 하나로 원천 스키마 하나를 가리킴(5벌이 풀 하나를 함께 씀, 스키마 이름만 다름). q·scope는 풀 그대로."""

    def __init__(self, pool, schema):
        self.pool_obj, self.schema = pool, schema
        self.q, self.scope = pool.q, pool.scope


def connect_sources():
    """원천 이름 → 그 원천 스키마 연결(`<PG_SCHEMA>_<원천>`) — 5벌 + 있는 DEV 원천(op-17 — prd는 5벌만). 실 PG는 풀 하나 + SchemaView,
    대역은 스키마마다 파일 하나(StandinPG)."""
    if has_conn():
        pool = PGPool(conf())
        return {src: SchemaView(pool, ST.src_schema(pool.schema, src)) for src in ST.all_sources(pool.schema, pool.q)}
    _warn_standin()
    from common.store.pg_standin import StandinPG

    base = _standin_schema(None)
    return {src: StandinPG(ST.src_schema(base, src)) for src in ST.all_sources(base)}
