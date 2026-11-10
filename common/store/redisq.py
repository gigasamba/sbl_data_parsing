"""parse_document Redis 연결·키·작업 전달 계약(두 앱 공용, 파싱 엔진 의존 없음)."""

import json
import re
import time
from typing import Any

from common.config.settings import SERVER_ENVS, cfg, resolve_run_env, reveal
from common.core.paths import APP_ROOT

SERVICE_DIR = APP_ROOT / "output" / "_mcp_parse"
JOBS_DIR = SERVICE_DIR / "jobs"
FULL_MESSAGE = "작업 대기열 가득 — 잠시 뒤 재시도"


class QueueFull(RuntimeError):
    """active 작업 수가 상한에 닿음."""


class RedisConfigError(RuntimeError):
    """서버 Redis 인증 설정 누락."""


def require_password():
    if resolve_run_env() in SERVER_ENVS and not (reveal(cfg().connections.redis.redis_password) or "").strip():
        raise RedisConfigError("Redis 비밀번호 없음 — 서버(dev·prd)는 settings.yaml common.connections.redis.redis_password 필수")


def client(*, wait_timeout=5):
    """BLPOP 대기보다 긴 socket timeout. 테스트는 반환 클라이언트만 바꿔 외부 접속 없이 실행."""
    require_password()
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


def is_redis_error(exc):
    """redis-py 없는 시험에서도 Redis 예외와 소켓 오류를 식별."""
    return isinstance(exc, (OSError, RedisConfigError)) or any(cls.__module__ == "redis.exceptions" for cls in type(exc).__mro__)


def redact(value):
    secret = reveal(cfg().connections.redis.redis_password)
    return str(value).replace(secret, "[비밀값]") if secret else str(value)


def connection_error(exc):
    """인증 실패에도 비밀번호·연결 URL은 출력하지 않는다."""
    s = cfg().connections.redis
    detail = redact(exc)
    return f"parse 서비스 연결 실패(Redis {s.redis_host}:{s.redis_port}) — redis 컨테이너 기동·설정 확인: {type(exc).__name__}: {detail}"


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


def publish_policy(r, exts, roots, max_mb):
    """worker 정책 스냅샷 — 짧은 TTL로 중단된 worker의 정책을 지움."""
    with r.pipeline(transaction=True) as tx:
        tx.multi()
        tx.hset(key("policy"), mapping={"exts": json.dumps(sorted(exts)), "roots": json.dumps([str(p) for p in roots]), "max_mb": max_mb})
        tx.expire(key("policy"), 120)
        tx.execute()


def read_policy(r):
    policy = r.hgetall(key("policy"))
    return {**policy, "exts": json.loads(policy["exts"]), "roots": json.loads(policy["roots"])} if policy else None


def claim(r, job_id, consumer, attempts, picked_at, queue_wait_s):
    """종료 확인과 실행 소유권 변경을 같은 WATCH 트랜잭션으로 묶음."""
    while True:
        with r.pipeline(transaction=True) as tx:
            try:
                tx.watch(key("job", job_id))
                job = tx.hgetall(key("job", job_id))
                if not job or job.get("status") in ("done", "failed", "rejected"):
                    return None
                values = dict(status="running", picked_at=picked_at, worker=consumer, attempts=attempts, queue_wait_s=queue_wait_s)
                tx.multi()
                tx.hset(key("job", job_id), mapping=values)
                tx.execute()
                return {**job, **values}
            except Exception as exc:
                if type(exc).__name__ != "WatchError":
                    raise


def reclaim_dead(r, consumer, missing_since, *, now=None):
    """heartbeat 부재를 연속 30초 관찰한 소비자의 pending을 한 건씩 회수."""
    now = time.monotonic() if now is None else now
    consumers = r.xinfo_consumers(key("queue"), group())
    names = {item["name"] for item in consumers if item["name"] != consumer}
    for name in list(missing_since):
        if name not in names:
            del missing_since[name]
    for item in consumers:
        name = item["name"]
        if name == consumer:
            continue
        if r.exists(key("worker", name)):
            missing_since.pop(name, None)
            continue
        first_missing = missing_since.setdefault(name, now)
        # TTL 30초·갱신 10초: Redis 재기동 뒤 heartbeat가 복구될 유예 + idle 60초를 함께 확인.
        if now - first_missing < 30 or item["idle"] <= 60000:
            continue
        if not item["pending"]:
            r.xgroup_delconsumer(key("queue"), group(), name)
            missing_since.pop(name, None)
            continue
        pending = r.xpending_range(key("queue"), group(), "-", "+", 1, consumername=name)
        if pending:
            rows = r.xclaim(key("queue"), group(), consumer, min_idle_time=60000, message_ids=[pending[0]["message_id"]])
            if rows:
                return rows[0]
    return None


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
