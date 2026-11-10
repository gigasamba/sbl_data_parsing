"""parse_document — 공유 작업 폴더 + Redis Streams 제출, 완료 LIST에서 즉시 깨어남."""

import base64
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from common.config.settings import cfg
from common.core import parse_limit
from common.store import redisq
from mcp_server.services.tool_runner import PARSE_MAX_SEC


class RedisFailure(RuntimeError):
    """클라이언트 명령에서 발생한 Redis/소켓 오류(파일 I/O와 구분)."""

    def __init__(self, error):
        self.error = error
        super().__init__(str(error))


class JobFileError(RuntimeError):
    """작업 폴더를 준비하지 못함 — 제출 함수가 아직 반환하지 않았어도 job_id를 보존."""

    def __init__(self, error, job_id):
        self.error, self.job_id = error, job_id
        super().__init__(str(error))


def _redis_call(command, *args, **kwargs):
    """redis-py를 import하지 않고 RedisError 계열과 클라이언트 소켓 오류만 가름."""
    try:
        return command(*args, **kwargs)
    except Exception as exc:
        if redisq.is_redis_error(exc):
            raise RedisFailure(exc) from exc
        raise


def _file_error(exc, job_id=None):
    return {"error": f"parse 작업 파일 오류: {type(exc).__name__}: {exc}", **({"job_id": job_id} if job_id else {})}


def _parse_shaped(j, max_chars):
    """완료 응답 다듬기 — text가 max_chars(기본 200000자)를 넘으면 잘리고 text_truncated 표시(전체는 rep_path 파일).
    완료 응답에도 status:"done"을 심는다(호출자가 폴링 마감 조건으로 쓰게 — 2026-10-21 실사 중 빠진 게 튀어 나와 붙임)."""
    if j.get("status") != "done":
        return {k: j.get(k) for k in ("job_id", "filename", "status", "error", "elapsed_ms") if j.get(k) is not None}
    res = dict(j.get("result") or {})
    res["status"] = "done"
    t = res.get("text") or ""
    if max_chars and len(t) > int(max_chars):
        res["text"], res["text_truncated"] = t[: int(max_chars)], True
    return res


def _submit(source, r):
    """업로드 파일·작업 메타를 공유 폴더에 쓴 뒤 Redis에 원자적 제출. path 검사는 worker가 함."""
    path, b64 = source.get("path"), source.get("content_b64")
    if not path and not b64:
        raise ValueError("path 또는 content_b64(+filename) 필요")
    raw = None
    if b64:
        fname = redisq.filename(source.get("filename"))
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception as exc:
            raise ValueError(f"base64 디코딩 실패: {exc}") from exc
        if msg := parse_limit.too_big(len(raw)):
            raise ValueError(msg)
        meta = {"filename": fname, "mode": "base64", "bytes": len(raw)}
    else:
        fname = Path(path).name
        meta = {"filename": fname, "mode": "path", "path": str(path), "bytes": 0}
    job_id = time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:12]
    ws = redisq.JOBS_DIR / job_id
    try:
        try:
            (ws / "in").mkdir(parents=True, exist_ok=True)
            if raw is not None:
                (ws / "in" / fname).write_bytes(raw)
            meta["submitted_at"] = time.time()
            (ws / "job.json").write_text(json.dumps({"job_id": job_id, **meta}, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            raise JobFileError(exc, job_id) from exc
        ahead = _redis_call(redisq.submit, r, job_id, meta, cfg().parse_queue.queue_max)
    except Exception:
        shutil.rmtree(ws, ignore_errors=True)
        raise
    return job_id, ahead


def do_parse_document(path=None, content_b64=None, filename=None, time_out_threshold=300, max_chars=200000):
    """비정형 파일 1건 → 기존 도구 응답. 제한 시간이 지나도 서버 작업은 계속 진행."""
    if not path and not content_b64:
        return {"error": "path 또는 content_b64(+filename) 필요"}
    if content_b64:
        n = (len(content_b64) - sum(map(content_b64.count, ("\r", "\n", " ", "\t", "=")))) * 3 // 4
        if msg := parse_limit.too_big(n):
            return {"error": msg}
    t0 = time.monotonic()
    thr = min(max(2.0, float(time_out_threshold or 0)), PARSE_MAX_SEC)
    r, job_id = None, None
    try:
        r = _redis_call(redisq.client, wait_timeout=thr)
        job_id, ahead = _submit({"path": path, "content_b64": content_b64, "filename": filename}, r)
        remaining = thr - (time.monotonic() - t0)
        if remaining > 0 and _redis_call(r.blpop, redisq.key("done", job_id), timeout=remaining):
            job = redisq.decode_job(_redis_call(r.hgetall, redisq.key("job", job_id)))
            if job.get("status") == "rejected":
                return {"error": job.get("error")}
            if job.get("status") == "done":
                try:
                    name = job.get("result_file", "")
                    if not re.fullmatch(r"result-[0-9]+\.json", name):
                        raise FileNotFoundError("완료 결과 파일 이름 없음 또는 잘못됨")
                    job["result"] = json.loads((redisq.JOBS_DIR / job_id / name).read_text(encoding="utf-8"))
                except Exception as exc:
                    return _file_error(exc, job_id)
            return _parse_shaped(job, max_chars)
    except RedisFailure as exc:
        return {"error": redisq.connection_error(exc.error)}
    except JobFileError as exc:
        return _file_error(exc.error, exc.job_id)
    except (ValueError, redisq.QueueFull) as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"parse 작업 오류: {type(exc).__name__}: {exc}", **({"job_id": job_id} if job_id else {})}
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
    return {
        "error": f"시간 안에 수행 못했습니다 — time_out_threshold({int(thr)}초) 내 파싱 미완료",
        "job_id": job_id,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "queue_position_at_submit": ahead,
        "note": f"작업은 수집 서버에서 계속 진행(대기열 {ahead}건 뒤) — 결과는 _mcp_parse/jobs/<job_id>/ 아래에 만들어진다(수집 서버 담당자 확인)",
    }
