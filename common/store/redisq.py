"""parse_document Redis 연결·키·작업 전달 계약(두 앱 공용, 파싱 엔진 의존 없음)."""

import json
import re
from typing import Any

from common.config.settings import cfg, reveal
from common.core.paths import APP_ROOT

SERVICE_DIR = APP_ROOT / "output" / "_mcp_parse"
JOBS_DIR = SERVICE_DIR / "jobs"
FULL_MESSAGE = "작업 대기열 가득 — 잠시 뒤 재시도"


class QueueFull(RuntimeError):
    """active 작업 수가 상한에 닿음."""


def client(*, wait_timeout=5):
    """BLPOP 대기보다 긴 socket timeout. 테스트는 반환 클라이언트만 바꿔 외부 접속 없이 실행."""
    import redis

    s = cfg().connections.redis
    return redis.Redis(
        host=s.redis_host,
        port=s.redis_port,
        password=reveal(s.redis_password),
        db=s.redis_db,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=max(10, wait_timeout + 5),
        health_check_interval=15,
    )


def prefix():
    return cfg().connections.redis.redis_key_prefix


def key(kind, ident=None):
    return f"{prefix()}:{kind}" + (f":{ident}" if ident is not None else "")


def group():
    return key("workers")


def ensure_group(r):
    try:
        r.xgroup_create(key("queue"), group(), id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def filename(value):
    """업로드 파일명 — 옛 작업 서비스 _submit의 정리 규칙."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", str(value or ""))
    if not name or name.startswith("."):
        raise ValueError("content_b64와 함께 filename 필요")
    return name


def connection_error(exc):
    """인증 실패에도 비밀번호·연결 URL은 출력하지 않는다."""
    s = cfg().connections.redis
    detail = str(exc)
    secret = reveal(s.redis_password)
    if secret:
        detail = detail.replace(secret, "[비밀값]")
    return f"parse 서비스 연결 실패(Redis {s.redis_host}:{s.redis_port}) — mcp-redis 기동·설정 확인: {type(exc).__name__}: {detail}"


def submit(r, job_id, meta, queue_max):
    """active를 WATCH해 동시 제출도 상한·순번을 지킴. HASH·SET·STREAM은 같은 EXEC에 기록."""
    while True:
        with r.pipeline(transaction=True) as tx:
            try:
                tx.watch(key("active"))
                ahead = tx.scard(key("active"))
                if ahead >= queue_max:
                    raise QueueFull(FULL_MESSAGE)
                tx.multi()
                tx.hset(key("job", job_id), mapping={**meta, "job_id": job_id, "status": "queued", "queue_position": ahead, "attempts": 0})
                tx.sadd(key("active"), job_id)
                tx.xadd(key("queue"), {"job_id": job_id})
                tx.execute()
                return ahead
            except Exception as exc:
                # redis-py는 연결할 때만 import — 서버 테스트는 redis 패키지 없이 가짜 클라이언트로 실행.
                if type(exc).__name__ != "WatchError":
                    raise


def finish(r, message_id, job_id, status, *, worker=None, attempts=None, **values):
    """종료 상태·완료 알림·TTL·active 해제·ACK를 원자적으로 기록. 회수 전 worker의 늦은 쓰기는 거부."""
    while True:
        with r.pipeline(transaction=True) as tx:
            try:
                tx.watch(key("job", job_id))
                job = tx.hgetall(key("job", job_id))
                if job.get("status") in ("done", "failed", "rejected"):
                    return False
                if worker is not None and (job.get("worker") != worker or int(job.get("attempts", 0)) != attempts):
                    return False
                ttl = cfg().parse_queue.mcp_parse_result_ttl_sec
                tx.multi()
                tx.hset(key("job", job_id), mapping={"status": status, **values})
                tx.lpush(key("done", job_id), json.dumps({"status": status, "error": values.get("error")}, ensure_ascii=False))
                tx.expire(key("job", job_id), ttl)
                tx.expire(key("done", job_id), ttl)
                tx.srem(key("active"), job_id)
                tx.xack(key("queue"), group(), message_id)
                tx.xdel(key("queue"), message_id)
                tx.execute()
                return True
            except Exception as exc:
                if type(exc).__name__ != "WatchError":
                    raise


def decode_job(job: dict[str, Any]):
    """Redis HASH의 수치 필드를 앱 값으로 복원."""
    out = dict(job)
    for field in ("bytes", "queue_position", "attempts"):
        if field in out:
            out[field] = int(out[field])
    for field in ("submitted_at", "picked_at", "finished_at", "elapsed_ms", "queue_wait_s"):
        if field in out:
            out[field] = float(out[field])
    return out
