"""프로세스 종료 정리 한 곳(pl-27, 사용자 10-30) — 정상 종료·오류·SIGTERM 어느 쪽으로 끝나도
① 이 프로세스가 띄운 자식(track)을 끝내고 회수한다(wait — 좀비·고아를 남기지 않음, 손자는 프로세스 묶음째)
② 이 프로세스가 만든 임시 파일(remove_at_exit — 덮기 설정 파일·PID 기록)을 지운다(자식을 먼저 끝낸 뒤 — 자식이 끝까지 읽음).
SIGTERM은 파이썬 기본 동작이 바로 죽는 것이라 finally·atexit가 안 돈다 → 처음 쓸 때 SIGTERM을 SystemExit(143)으로 바꾼다
(이미 다른 처리기를 단 프로세스 — trigger_server 등 — 는 그대로 둠: 그쪽이 정상 종료하면 atexit가 돈다).
OS별 분기(POSIX 프로세스 묶음·Windows taskkill)는 이 파일에만 둔다(CLAUDE.md §2)."""

import atexit
import os
import signal
import subprocess
import threading

_LOCK = threading.Lock()
_FILES: set[str] = set()
_PROCS: list[subprocess.Popen] = []
_ARMED = [False]


def remove_at_exit(path):
    """path를 프로세스가 끝날 때 지운다(없으면 조용히). 반환: path 그대로."""
    _arm()
    with _LOCK:
        _FILES.add(str(path))
    return path


def track(p):
    """띄운 자식 p를 기억 — 프로세스가 끝날 때 아직 돌고 있으면 stop(p). 끝난 자식은 그때그때 목록에서 뺀다. 반환: p."""
    _arm()
    with _LOCK:
        _PROCS[:] = [q for q in _PROCS if q.poll() is None]
        _PROCS.append(p)
    return p


def group_kw():
    """POSIX — 자식을 새 프로세스 묶음(세션)으로 띄우는 Popen 인자(stop이 손자까지 끝내게). Windows는 없음(taskkill /T가 트리째)."""
    return {} if os.name == "nt" else {"start_new_session": True}


def stop(p, grace=10):
    """자식 p와 그 아래를 끝내고 회수(wait) — 자기 묶음의 맨 위(group_kw로 띄움)면 묶음째 SIGTERM → grace초 → SIGKILL,
    아니면 그 프로세스만. Windows는 taskkill /T /F(트리째). 이미 끝났으면 회수만."""
    if os.name == "nt":
        if p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        try:
            own_group = os.getpgid(p.pid) == p.pid
        except ProcessLookupError:
            own_group = False
        # 맨 위 자식이 먼저 끝나도 SIGTERM을 무시한 손자가 파이프를 붙잡지 않도록 묶음에는 늘 보냄(옛 kill_group과 같음)
        _signal(p, signal.SIGTERM, own_group)
        try:
            p.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        _signal(p, signal.SIGKILL, own_group)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass  # ponytail: SIGKILL 뒤에도 안 끝남(D 상태 등) — 더 할 수 있는 것이 없음


def _signal(p, sig, own_group):
    try:
        if own_group:
            os.killpg(p.pid, sig)
        elif p.poll() is None:
            p.send_signal(sig)
    except (ProcessLookupError, PermissionError):
        pass


def _arm():
    if _ARMED[0]:
        return
    _ARMED[0] = True
    atexit.register(_cleanup)
    try:
        if signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
            signal.signal(signal.SIGTERM, _on_term)
    except ValueError:
        pass  # ponytail: 처음 쓴 곳이 주 스레드가 아님 — SIGTERM은 기본(즉시 종료)대로, 정상·오류 종료 정리만


def _on_term(signum, _frame):
    raise SystemExit(128 + signum)


def _cleanup():
    with _LOCK:
        procs, files = list(_PROCS), sorted(_FILES)
        _PROCS.clear()
        _FILES.clear()
    for p in procs:  # 자식 먼저 — 자식이 읽는 덮기 파일을 그 뒤에 지움
        if p.poll() is None:
            stop(p)
    for f in files:
        try:
            os.unlink(f)
        except OSError:
            pass
