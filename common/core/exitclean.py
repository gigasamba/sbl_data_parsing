"""프로세스 종료 정리 한 곳 — 정상 종료·오류·SIGTERM 어느 쪽으로 끝나도
① 이 프로세스가 띄운 자식(track)을 끝내고 회수한다(wait — 좀비를 남기지 않음)
② 이 프로세스가 맡은 임시 파일(remove_at_exit — 덮기 설정 파일·PID 기록)을 지운다(자식을 먼저 끝낸 뒤 — 자식이 끝까지 읽음).
SIGTERM은 파이썬 기본 동작이 바로 죽는 것이라 finally·atexit가 안 돈다 → import 때(주 스레드) SIGTERM 처리기를 단다: 처리기 안에서
바로 정리하고(작업 스레드 join보다 먼저 — 바깥 kill_group이 10초 뒤 SIGKILL하기 전에) SystemExit(143). 이미 다른 처리기를 단
프로세스(trigger_server 등)는 그쪽이 덮어쓰고, 그쪽이 정상 종료하면 atexit가 정리한다.
OS별 분기(POSIX 프로세스 묶음·Windows taskkill)는 stop()에만 둔다."""

import atexit
import os
import signal
import subprocess
import threading
import time

GRACE = 10  # SIGTERM 뒤 SIGKILL까지(초) — kill_group과 같음
_LOCK = threading.Lock()
_FILES: set[str] = set()
_PROCS: list[tuple[subprocess.Popen, bool]] = []  # (자식, 묶음째 끝낼지)
_FLUSHERS: list = []
_CLOSING = threading.Event()  # 정리를 시작한 뒤 띄운 자식은 바로 끝냄(데몬 작업 스레드가 정리 중에 새 자식을 띄우는 경우)


def on_exit(callback, *, timeout, priority=0):
    """멱등 flush 등록. 공유 deadline을 받으며 낮은 priority부터 실행."""
    with _LOCK:
        if not any(item[0] == callback for item in _FLUSHERS):
            _FLUSHERS.append((callback, timeout, priority))


def remove_at_exit(path):
    """path를 이 프로세스가 끝날 때 지운다(없으면 조용히). 반환: path 그대로."""
    with _LOCK:
        _FILES.add(str(path))
    return path


def track(p, group=False):
    """띄운 자식 p를 기억 — 프로세스가 끝날 때 아직 돌면 stop(p, group). group=True는 p를 새 프로세스 묶음(세션)으로 띄웠을 때만.
    끝난 자식은 returncode로만 거른다(poll()로 남의 스레드 자식을 대신 회수하지 않음). 정리 중이면 바로 끝낸다. 반환: p."""
    if _CLOSING.is_set():
        stop(p, group)
        return p
    with _LOCK:
        _PROCS[:] = [(q, g) for q, g in _PROCS if q.returncode is None]
        _PROCS.append((p, group))
    return p


def stop(p, group=False, grace=GRACE):
    """자식 p를 끝내고 회수(wait). group=True(새 묶음으로 띄움)면 POSIX는 묶음째 SIGTERM → grace초 → SIGKILL(맨 위가 먼저 끝나도
    SIGTERM을 무시한 손자가 파이프를 붙잡지 않도록 묶음에는 늘 보냄 — kill_group과 같음), 아니면 그 프로세스만. Windows는 taskkill /T /F."""
    _send(p, signal.SIGTERM, group)
    if os.name != "nt":
        _wait(p, grace)
        _send(p, signal.SIGKILL, group)
    _wait(p, grace)


def _send(p, sig, group):
    try:
        if os.name == "nt":
            if p.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        elif group:
            os.killpg(p.pid, sig)
        elif p.poll() is None:
            p.send_signal(sig)
    except (ProcessLookupError, PermissionError):
        pass


def _wait(p, sec):
    try:
        p.wait(timeout=max(0.0, sec))
    except subprocess.TimeoutExpired:
        pass  # ponytail: SIGKILL 뒤에도 안 끝남(D 상태 등) — 더 할 수 있는 것이 없음


def _cleanup(lock_timeout=-1):
    """자식 전부에 SIGTERM → 한 마감(GRACE초)까지 기다림 → 남은 것 SIGKILL·회수 → 파일 지움. 두 번 불려도 안전(두 번째는 빈 목록).
    lock_timeout(초) 안에 목록 잠금을 못 잡으면 아무것도 안 하고 False — SIGTERM 처리기용: 처리기는 주 스레드에서 돌므로 주 스레드가
    track·remove_at_exit 도중(잠금을 쥔 채)이면 기다려도 안 풀림(교착). 그때는 SystemExit로 그 블록을 풀고 atexit가 다시 부른다."""
    _CLOSING.set()
    if not _LOCK.acquire(timeout=lock_timeout):
        return False
    try:
        procs, files, flushers = list(_PROCS), sorted(_FILES), list(_FLUSHERS)
        _FLUSHERS.clear()
        _PROCS.clear()
        _FILES.clear()
    finally:
        _LOCK.release()
    live = [(p, g) for p, g in procs if p.poll() is None]
    end = time.monotonic() + GRACE
    for p, g in live:
        _send(p, signal.SIGTERM, g)
    flush_deadline = min(end, time.monotonic() + min((timeout for _, timeout, _ in flushers), default=GRACE))
    for flush, timeout, priority in sorted(flushers, key=lambda item: item[2]):
        try:
            if flush(deadline=flush_deadline) is False:  # SIGTERM이 호출자의 잠금 안에 끼어들면 atexit에서 재시도
                on_exit(flush, timeout=timeout, priority=priority)
        except Exception:
            pass  # 종료 정리 하나의 실패가 나머지를 막지 않음
    if os.name != "nt":
        for p, _ in live:
            _wait(p, end - time.monotonic())
        for p, g in live:
            _send(p, signal.SIGKILL, g)
    for p, _ in live:
        _wait(p, GRACE)
    for f in files:  # 자식을 먼저 끝낸 뒤 — 자식이 읽는 덮기 파일
        try:
            os.unlink(f)
        except OSError:
            pass
    return True


def _on_term(signum, _frame):
    if _CLOSING.is_set():
        return  # 정리가 이미 도는 중(정상 종료의 atexit 포함) — SystemExit로 끊지 않고 끝까지 하게
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # 정리 중 두 번째 SIGTERM이 정리를 끊지 않게
    except ValueError:
        pass
    _cleanup(lock_timeout=1.0)  # 못 잡으면(주 스레드가 쥔 채 신호를 받음) 정리는 atexit에서 — 잠금이 풀린 뒤
    raise SystemExit(128 + signum)


atexit.register(_cleanup)
try:
    if signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
        signal.signal(signal.SIGTERM, _on_term)
except ValueError:
    pass  # ponytail: 주 스레드가 아닌 곳에서 처음 import — SIGTERM은 기본(즉시 종료)대로, 정상·오류 종료 정리만
