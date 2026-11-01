"""검색 MCP 상태 — 리트리버(저장소 연결·재적재 확인·이름 있는 색인)·예열·/health 본문·호출자(CALLER) · 시험용 묶음 만들기.
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
"""

import contextvars
import sys
import threading
import time
import types
from pathlib import Path

from common.config import settings as C  # common 칸(S7e1 — MCP_BUNDLE)
from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(S7d)

CALLER = contextvars.ContextVar("caller", default="mcp:stdio")


_STATE: dict = {}


_RELOAD_LOCK = threading.Lock()


def _version_of(pg, bundle):
    """현재 적재 버전 표식 — PG면 ai.load_run 최신 id, 로컬이면 묶음 meta.json mtime(S12, load 뒤 재적재 확인용)."""
    if pg is not None:
        try:
            r = pg.q(f"SELECT COALESCE(MAX(run_id), 0) AS r FROM {pg.schema}.load_run")
            return ("pg", r[0]["r"] if r else None)
        except Exception:
            return ("pg", None)  # 표가 없거나 접속 흔들림 — 버전 모름(바뀜으로 보지 않음)
    p = Path(bundle) / "meta.json"
    return ("local", p.stat().st_mtime if p.exists() else None)


def _close_pool_later(pool, delay=5):
    """재적재로 교체된 옛 PGPool을 늦게 닫음(S12 권고) — 이미 시작된 요청이 끝날 시간을 줌.
    ponytail: 완벽한 보장은 아님(그 사이 두 번째 .q() 호출이 있으면 실패 가능) — 재적재 간격(기본 30초)에 비해 요청은 보통 짧아 실무 위험은 낮음."""

    def _close():
        time.sleep(delay)
        try:
            pool.pool.close()
        except Exception:
            pass

    threading.Thread(target=_close, daemon=True).start()


def check_store():
    """op-09 — 서버(dev·prd)에서 PG 접속 칸이 비면 SystemExit(채울 자리를 적음 — common.store.pg.conf). 검색 저장소는 PG 하나(mc-01 —
    저장소 종류 칸 mcp.server.store는 11-01에 없앰), PC는 칸이 비면 SQLite 대역. main이 시작 때 부른다(예열 스레드·요청 안에서는
    SystemExit가 조용히 스레드만 죽이므로 — 리뷰 10-31)."""
    from common.core import paths

    if paths.LOCAL_RUN:
        return
    from common.store.pg import conf

    conf()


def _build_retriever():
    from common.store import services
    from mcp_server.services.search import retriever as RT

    old = _STATE.get("R")
    try:
        check_store()  # 시작 때 이미 확인(main) — 설정이 그 뒤 바뀐 경우만 여기서 걸림
    except SystemExit as e:  # 스레드·요청 안에서는 오류로(조용히 스레드만 죽지 않게)
        raise RuntimeError(str(e)) from None
    a = types.SimpleNamespace(pg=False, local=False, edw=False, edw_client=False)
    services.connect(a)  # PC — Docker pgvector 주소 찾기(못 찾으면 SQLite 대역 — 검색은 PG 하나, mc-01)
    from common.store.db import cfgfile

    cur = cfgfile.active("stack")  # 엔진 구성 파일(서버·PC 같음 — 프로세스 시작 때 읽은 것, 사용자 11-01)
    st = cur.named()
    bundle = C.cfg().paths.mcp_bundle or str(APP_ROOT / "output" / "edw" / "bundle")  # S7e1 — common 칸(옛 mcp.server.bundle)
    R = RT.Retriever(bundle, st.get("retrieve", "hybrid"))
    _STATE["R"], _STATE["bundle"], _STATE["stack"] = R, bundle, st
    _STATE["version"], _STATE["checked_at"] = _version_of(R.pg, bundle), time.time()
    if old is not None and old.pg is not None and old.pg is not R.pg:
        _close_pool_later(old.pg)


def _retriever():
    """저장소 연결(PG 하나 — mc-01)·Retriever — 처음엔 만들고, 이후엔 최소 MCP_RELOAD_CHECK_SEC(기본 30초)
    간격으로 적재 버전이 바뀌었는지만 확인해 바뀌었으면 다시 만든다(S12, load 재실행 뒤 새 데이터가 안 보이던 문제).
    재생성 중인 동시 요청은 기다리지 않고 기존 객체로 바로 응답(비차단 잠금)."""
    if "R" not in _STATE:
        with _RELOAD_LOCK:
            if "R" not in _STATE:
                _build_retriever()
        return _STATE["R"]
    if "bundle" not in _STATE:  # 호출자가 Retriever를 직접 넣은 경우(stack_matrix·eval 도구) — 재적재 대상 아님
        return _STATE["R"]
    interval = mc.cfg().server.reload_check_sec
    if time.time() - _STATE.get("checked_at", 0) >= interval and _RELOAD_LOCK.acquire(blocking=False):
        try:
            _STATE["checked_at"] = time.time()
            if _version_of(_STATE["R"].pg, _STATE["bundle"]) != _STATE.get("version"):
                _build_retriever()
        finally:
            _RELOAD_LOCK.release()
    return _STATE["R"]


def _warmup(R):
    """MC1 — 첫 요청 묶음 p95 20.7초(검색기·질의 임베딩 지연 로드) → 기동 때 검색 1회로 미리 로드. MCP_WARMUP=0이면 끔.
    실패해도 기동은 계속(임베딩 API가 잠깐 안 될 때 서버가 안 뜨면 더 나쁨) — 경고 한 줄."""
    if not mc.cfg().server.warmup:
        return None
    t0 = time.time()
    try:
        R.search("예열 warmup", 1)
        print(f"[mcp] 예열 {time.time() - t0:.1f}초", file=sys.stderr, flush=True)
        return True
    except Exception as e:  # 예열 실패는 첫 요청에서 다시 드러남
        print(f"[mcp] 예열 실패(기동은 계속): {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return False


def _warmup_bg():
    """MC1 — 백그라운드 스레드에서 예열(색인 로드 `_retriever()` + 질의 1회 `_warmup()`), 그 사이 `/health`는
    503 'warming'을 돌려줘 메인 스레드는 uvicorn을 바로 띄울 수 있다(첫 요청이 콜드스타트를 안 치르면 된다 — 서버
    자체가 안 뜨는 건 더 나쁘다). 색인 로드 자체가 실패해도(예: 임베딩 API 잠깐 다운) 예외를 올리지 않고
    기록만 — `/health`는 ready=True + warning 플래그로 계속 뜬다."""
    ok = None
    try:
        ok = _warmup(_retriever())
    except Exception as e:  # 색인 로드 실패도 기동은 계속(첫 실제 요청에서 다시 드러남)
        print(f"[mcp] 예열 중 색인 로드 실패(기동은 계속): {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        ok = False
    finally:
        _STATE["warmup_ok"], _STATE["warmup_done"] = ok, True


def _health():
    """가벼운 상태만(권고 — bundle 내부 경로는 안 보여줌). MC1 — 예열 스레드가 아직 안 끝났으면
    warming=True(ready=False, 라우트가 503) · 끝났는데 실패했으면 ready=True + warning(서버는 계속 뜸).
    코디네이터 10-14 — store="pgvector"일 때 db: "standin"(sqlite, common/pg_standin.py) | "pg"(진짜 PG) —
    서버에서 PG_PASSWORD를 빠뜨려 조용히 스탠드인으로 떨어진 경우를 /health만 보고도 알 수 있게."""
    R = _STATE.get("R")
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
