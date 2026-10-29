#!/usr/bin/env python3
"""수집 서버 상주 트리거 서버 — 웹앱 등에서 "문서 1건 올라왔음, 파싱 시작" 트리거를 받아 야간 배치와 같은
코드 경로(cli/pipeline.py parse·structure·load)를 돈다(10-14 요건). stdlib만(http.server
ThreadingHTTPServer) — 새 패키지 없음. 이미지당 하나(parse 전용 또는 structure+load 전용) — 이 모듈은
어느 쪽이든 pipeline(parse·structure·load)·mcp_server(search — S5 전 data_retrieval)를 전혀 import하지 않는다(cli/pipeline.py를
하위 프로세스로만 부름 — 이미지 경계 안전).

실행:
  PYTHONPATH=<repo>/deploy python -m pipeline.trigger_server --module parse
  PYTHONPATH=<repo>/deploy python -m pipeline.trigger_server --module structure
  (자기 점검) python -m pipeline.trigger_server --selftest

  (운영자 셸 — curl 인용 없이) stdlib 클라이언트, 토큰은 env TRIGGER_TOKEN:
    python -m pipeline.trigger_server client --url http://127.0.0.1:8770 submit --source s3://bucket/key.pdf
    python -m pipeline.trigger_server client --url http://127.0.0.1:8770 status <job_id>
    python -m pipeline.trigger_server client --url http://127.0.0.1:8770 wait <job_id>
  curl로 같은 일(submit):
    curl -X POST http://127.0.0.1:8770/jobs -H "Authorization: Bearer $TRIGGER_TOKEN" \
         -H "Content-Type: application/json" -d '{"source": "s3://bucket/key.pdf"}'

env:
  TRIGGER_TOKEN            필수(Bearer 토큰) — 없으면 거부, PC에서만 TRIGGER_ALLOW_NO_TOKEN=1로 무인증 허용(경고 출력).
                           client 서브커맨드도 같은 env에서 토큰을 읽음
  TRIGGER_HOST             기본 127.0.0.1(빈 값도 — 모든 인터페이스는 0.0.0.0 명시, C-37)
  TRIGGER_PORT             기본 parse=8770 · structure=8771
  TRIGGER_QUEUE_MAX        대기 중 작업 상한(기본 100) — 넘으면 429
  TRIGGER_UPLOAD_MAX_MB    /upload 본문 상한 MB(기본 50)
  TRIGGER_SOCKET_TIMEOUT_SEC    연결당 소켓 read 상한(초, 기본 30) — 느린 클라이언트가 스레드를 안 붙잡게
  TRIGGER_SHUTDOWN_TIMEOUT_SEC  SIGTERM 뒤 실행 중 작업을 기다리는 한도(초, 기본 300)
  CHAIN_STRUCTURE_URL      parse 작업 성공 뒤 이 URL들(structure 서버, **콤마로 여러 개** — 같은 이미지를
                           STRUCTURE_TARGET/INDEX_CONF 다른 값으로 띄운 구조화 인스턴스 여러 대, AD49)에
                           같은 토큰으로 독립적으로 후속 작업을 올림 — 하나가 실패해도 나머지는 그대로 올라가고,
                           결과는 각각 job record의 "chain"(목록, 대상마다 {url, ok, error?})에 남음

API:
  GET  /health                       인증 불필요 → {"ready", "module", "running", "queued"}
  POST /jobs       {"source", "docs"?, "args"?} → 202 {"job_id"} · 대기열 가득 → 429
  GET  /jobs/<id>                     → 상태(queued|running|done|failed)·종료코드·로그 경로·chain(대상별 결과) 등
  GET  /jobs?limit=N                  → 최근 작업 목록
  POST /upload     (본문 원본 + X-Filename) → output/inbox/<날짜>/ 에 저장 뒤 parse 작업으로 큐에 넣음(parse 서버만)

Object Storage 업로드가 기본 경로 — 웹앱은 보통 Object Storage에 올린 뒤 그 키로 POST /jobs 를 부르는 쪽을
쓴다(/upload는 작은 파일용 보조). source는 ① s3://·rdb: 로 시작하는 객체 참조(문자 집합만 검증) ② 그 밖엔
로컬 경로 — 반드시 설정된 source root(output/ 아래) 밑으로 resolve 되어야 함(경로 탈출 거부).

체이닝 payload는 공유 output/ 볼륨에서 이번 parse 결과를 찾는 데 쓸 run_id(cli/pipeline.py parse_module의
PARSE_RUN_ID, 로그에서 추출)와 대표 결과가 나온 doc 목록(output/parse/_rep/index.json)을 함께 보낸다 — 참고용
메타(ponytail): structure_module()은 지금도 공유 볼륨의 최신 끝 표시(_DONE.json)를 스스로 읽어 돌아서 이
값 없이도 동작한다. 특정 run_id를 받는 쪽이 필요해지면 그때 structure 서브커맨드에 공개 플래그를 추가.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import argparse
import hmac
import json
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common.config.settings import IN_IMAGE, reveal  # S7c — 비밀 칸(TRIGGER_TOKEN) 꺼내기 · 이미지 배치 판정(VS7e2 R-1)
from pipeline import config as pc  # S7c — pipeline 칸(설정 객체 · cfg()·by_env()·checked())

PY = sys.executable
_SENTINEL = object()
JOBS_MAX_BYTES = 1_000_000  # /jobs 본문 상한(작은 JSON — 업로드 자체는 /upload)
_MODULE_STAGES = {
    "parse": ["parse"],
    "structure": ["structure", "load"],
}  # structure 서버 = structure+load(S6b — data-pipeline 이미지, 컨테이너 data-pipeline-structure)

# args 허용 목록(GH1-06류 — 값이 있는 플래그는 문자 집합까지 검증, 그 밖은 토큰 전체 거부). 더 늘릴 땐 여기만.
STAGE_ARG_SPECS = {
    "parse": {"--mode": r"^(prod|test)$"},
    "structure": {"--force": None, "--path-prefix": r"^[A-Za-z0-9_\-./]{1,200}$"},
    "load": {"--force": None, "--replace": None, "--no-prune": None},
}


_RUN_ID_RE = re.compile(r"run_id ([0-9]{8}-[0-9]{6})")  # cli/pipeline.py write_mark()의 로그 줄에서 추출


class _BadRequest(ValueError):
    pass


class _TooLarge(Exception):
    pass


class QueueFullError(Exception):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _has_dotdot(value):
    """ ".." 경로 세그먼트 여부(구분자 \\·/ 둘 다) — validate_source·--path-prefix가 같이 쓰는 방어적 검사."""
    return any(part == ".." for part in re.split(r"[\\/]", value))


def validate_source(source, source_root):
    """object key(s3://·rdb:, 문자 집합만) 또는 source_root 아래로 resolve 되는 로컬 경로만 허용 — 신뢰 경계
    입력 검증(경로 탈출 거부, code.md §경계·보안)."""
    if not isinstance(source, str) or not source:
        raise ValueError("source가 비어 있음")
    if len(source) > 1024 or any(ord(c) < 0x20 for c in source):
        raise ValueError("source 형식이 올바르지 않음(길이·제어 문자)")
    if _has_dotdot(source):  # 객체 키·로컬 경로 둘 다 "..' 세그먼트 거부(방어적)
        raise ValueError("source에 '..' 경로 세그먼트 — 거부")
    if source.startswith("s3://") or source.startswith("rdb:"):
        rest = source.split("://", 1)[-1] if "://" in source else source.split(":", 1)[-1]
        if not re.match(r"^[A-Za-z0-9*][A-Za-z0-9._\-/:*]{0,500}$", rest):
            raise ValueError("source(객체 키) 문자 집합 위반")
        return source
    root = Path(source_root).resolve()
    p = Path(source)
    cand = p if p.is_absolute() else (root / source)
    resolved = cand.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as err:
        raise ValueError(f"source 경로가 허용 루트({root}) 밖임") from err
    if not resolved.exists():
        raise ValueError("source 경로가 없음")
    return str(resolved)


def _validate_docs(docs):
    if docs is None:
        return []
    if not isinstance(docs, list) or not all(isinstance(d, str) for d in docs):
        raise ValueError("docs는 문자열 리스트여야 함")
    if len(docs) > 500:
        raise ValueError("docs 500개 초과")
    for d in docs:
        if len(d) > 300 or any(ord(c) < 0x20 for c in d):
            raise ValueError("docs 항목 형식이 올바르지 않음")
    return docs


def _validate_args(module, args):
    """args 허용 목록만(GH1-06) — [("--force",) , ("--mode","test")] 형태(list of lists, JSON 직렬화용)로
    돌려줌. 모르는 토큰이 하나라도 있으면 작업 전체를 거부(400) — 일부만 적용하지 않음."""
    if args is None:
        return []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("args는 문자열 리스트여야 함")
    union = {}
    for stage in _MODULE_STAGES[module]:
        union.update(STAGE_ARG_SPECS.get(stage, {}))
    out, i = [], 0
    while i < len(args):
        tok = args[i]
        if tok not in union:
            raise ValueError(f"허용되지 않은 args 토큰: {tok}")
        pat = union[tok]
        if pat is None:
            out.append([tok])
            i += 1
        else:
            if i + 1 >= len(args) or not re.match(pat, args[i + 1]):
                raise ValueError(f"{tok} 값이 올바르지 않음")
            if tok == "--path-prefix" and _has_dotdot(args[i + 1]):  # validate_source와 같은 방어(보안 검토 3)
                raise ValueError(f"{tok} 값에 '..' 경로 세그먼트 — 거부")
            out.append([tok, args[i + 1]])
            i += 2
    return out


def _stage_args(stage, parsed_args):
    spec = STAGE_ARG_SPECS.get(stage, {})
    out = []
    for item in parsed_args:
        if item[0] in spec:
            out.extend(item)
    return out


def _sanitize_filename(name):
    name = Path((name or "").strip()).name  # 디렉터리 부분 전부 제거(경로 탈출 차단)
    if not name or name in (".", ".."):
        raise ValueError("X-Filename이 비어 있거나 올바르지 않음")
    if not re.match(r"^[A-Za-z0-9._\- ]{1,200}$", name):
        raise ValueError("파일 이름 문자 집합 위반")
    return name


def _default_cmd_builder(stage, job):
    cmd = [PY, "-m", "pipeline.cli", stage]
    if stage == "parse":
        cmd += ["--source", job["source"]]
    cmd += _stage_args(stage, job.get("args_parsed") or [])
    return cmd


def _run_subprocess(cmd, cwd):
    """child_env()로 PYTHONPATH 보장 + gated_popen(메모리·CPU 문)으로 자식 하나 — 크래시해도 서버는 안 죽음
    (예외는 호출자가 잡아 종료 코드 1로 취급)."""
    from common.core import resources as RS
    from common.core.paths import child_env

    pr = RS.gated_popen([str(c) for c in cmd], cwd=cwd, env=child_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = pr.communicate()
    text = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else (out or "")
    return pr.returncode, text


class JobManager:
    """작업 큐 + 기록(output/trigger/jobs.jsonl, 재시작 복구) + 작업자 스레드(서버당 동시 1개)."""

    def __init__(self, module, app_root, cmd_builder=None, queue_max=None):
        self.module = module
        self.app_root = Path(app_root)
        self.out_dir = self.app_root / "output"
        self.state_dir = self.out_dir / "trigger"
        self.logs_dir = self.state_dir / "logs"
        self.jobs_path = self.state_dir / "jobs.jsonl"
        self.source_root = self.out_dir
        self.cmd_builder = cmd_builder or _default_cmd_builder
        self.lock = threading.Lock()
        self.jobs = {}
        self.order = []
        self.seq = 0
        self.current = None
        self._stopping = threading.Event()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.queue = queue.Queue(maxsize=queue_max or pc.cfg().service.trigger.queue_max)
        self._load()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    @property
    def stopping(self):
        return self._stopping.is_set()

    def _load(self):
        if not self.jobs_path.exists():
            return
        rows = []
        for line in self.jobs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        rows.sort(key=lambda r: r.get("seq", 0))
        requeue = []
        for r in rows:
            if r.get("status") == "running":
                r["status"] = "failed (restarted)"
                r["ended_at"] = _now()
                r["error"] = "서버 재시작으로 중단"
            self.jobs[r["id"]] = r
            self.order.append(r["id"])
            self.seq = max(self.seq, r.get("seq", 0) + 1)
            if r.get("status") == "queued":
                requeue.append(r["id"])
        self._save()
        for jid in requeue:
            try:
                self.queue.put_nowait(jid)
            except queue.Full:
                self.jobs[jid]["status"] = "failed"
                self.jobs[jid]["error"] = "재시작 복구 시 대기열 가득 참"
        if requeue:
            self._save()

    def _save(self):
        """자체 self.lock으로 직렬화 — common/atomic.py의 임시 파일 이름은 PID 기준(여러 프로세스 전제)이라
        같은 프로세스 안의 두 스레드(제출 스레드·작업자 스레드)가 동시에 쓰면 같은 임시 파일을 밟아
        os.replace가 FileNotFoundError를 낼 수 있음 — snapshot부터 쓰기까지 통째로 lock 밖으로 안 내보냄."""
        from common.core.paths import atomic_write_text

        with self.lock:
            rows = [self.jobs[jid] for jid in self.order if jid in self.jobs]
            # ponytail: 뒤 2000건만 남김(무제한 증가 방지) — 더 긴 보존이 필요하면 로테이션 파일로
            text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[-2000:])
            atomic_write_text(self.jobs_path, text)

    def submit(self, source, docs, args_parsed):
        job_id = uuid.uuid4().hex[:16]
        with self.lock:
            seq = self.seq
            self.seq += 1
            job = {
                "id": job_id,
                "seq": seq,
                "module": self.module,
                "status": "queued",
                "source": source,
                "docs": docs or [],
                "args_parsed": args_parsed or [],
                "created_at": _now(),
                "started_at": None,
                "ended_at": None,
                "exit_code": None,
                "error": None,
                "log_path": None,
                "retries": 0,
                "chain": None,
            }
            self.jobs[job_id] = job
            self.order.append(job_id)
        try:
            self.queue.put_nowait(job_id)
        except queue.Full as err:
            with self.lock:
                del self.jobs[job_id]
                self.order.remove(job_id)
            raise QueueFullError() from err
        self._save()
        return job_id

    def get(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id)
            return dict(j) if j else None

    def list(self, limit=50):
        with self.lock:
            ids = list(reversed(self.order))[:limit]
            return [dict(self.jobs[i]) for i in ids if i in self.jobs]

    def health(self):
        return {"ready": not self.stopping, "module": self.module, "running": self.current, "queued": self.queue.qsize()}

    def stop_accepting(self):
        self._stopping.set()

    def wait_idle(self, timeout):
        deadline = time.time() + timeout
        while self.current is not None and time.time() < deadline:
            time.sleep(0.1)
        return self.current is None

    def close(self, timeout=5):
        """시험·selftest용 — 작업자 스레드를 끝까지 비우지 않고 끊음(배경 스레드 남기지 않기)."""
        self._stopping.set()
        try:
            self.queue.put(_SENTINEL, timeout=timeout)
        except queue.Full:
            pass
        self.worker.join(timeout=timeout)

    def _work(self):
        while True:
            job_id = self.queue.get()
            if job_id is _SENTINEL:
                return
            with self.lock:
                job = self.jobs.get(job_id)
            if job is None:
                continue
            self.current = job_id
            try:
                self._run(job)
            finally:
                self.current = None

    def _run(self, job):
        job["status"] = "running"
        job["started_at"] = _now()
        self._save()
        log_parts = []
        rc_final = 0
        for stage in _MODULE_STAGES[self.module]:
            cmd = self.cmd_builder(stage, job)
            log_parts.append("$ " + " ".join(str(c) for c in cmd) + "\n")
            try:
                rc, out = _run_subprocess(cmd, self.app_root)
            except (
                Exception
            ) as e:  # 하위 프로세스를 못 띄웠어도 서버는 계속(code.md — 내부 에러를 삼키지 않되 여긴 외부 경계: 작업 실패로 기록)
                rc, out = 1, f"{type(e).__name__}: {e}"
            log_parts.append(out + "\n")
            rc_final = rc
            if rc != 0:
                break
        from common.core.paths import atomic_write_text

        log_text = "".join(log_parts)
        log_path = self.logs_dir / f"{job['id']}.log"
        atomic_write_text(log_path, log_text)
        job["log_path"] = str(log_path)
        if rc_final == 0:
            job["status"], job["exit_code"] = "done", 0
        elif rc_final == 75:  # 바쁨(기존 모듈 락·마감 — cli/pipeline.py SystemExit(75)) → 다시 큐에
            job["retries"] += 1
            if job["retries"] > 5:
                job["status"], job["exit_code"], job["error"] = "failed", 75, "바쁨 재시도 초과(5회)"
                job["ended_at"] = _now()
            else:
                job["status"] = "queued"
                try:
                    self.queue.put_nowait(job["id"])
                except queue.Full:
                    job["status"], job["error"] = "failed", "재시도 중 대기열 가득 참"
                    job["ended_at"] = _now()
                self._save()
                return
        else:
            job["status"], job["exit_code"] = "failed", rc_final
        job["ended_at"] = _now()
        self._save()
        if job["status"] == "done" and self.module == "parse":
            self._chain(job, log_text)

    def _parse_output_meta(self, log_text):
        """체이닝 payload용 참고 메타 — run_id(cli/pipeline.py write_mark 로그 줄) + 대표 결과가 나온 doc
        목록(공유 output/ 볼륨의 _rep/index.json). 둘 다 못 구해도 빈 값으로 보냄(필수 아님 — 위 docstring 참조)."""
        m = _RUN_ID_RE.search(log_text or "")
        run_id = m.group(1) if m else None
        docs = []
        try:
            idx = json.loads((self.out_dir / "parse" / "_rep" / "index.json").read_text(encoding="utf-8"))
            docs = [r["doc"] for r in idx.get("docs", []) if r.get("engine")]
        except Exception:
            pass
        return {"run_id": run_id, "docs": docs}

    def _chain(self, job, log_text=""):
        """parse 성공 → CHAIN_STRUCTURE_URL(콤마로 여러 대상, AD49 — 같은 이미지를 다른 STRUCTURE_TARGET/
        INDEX_CONF로 띄운 구조화 인스턴스들)에 각각 독립적으로 structure 작업을 올림 — 하나가 실패해도
        나머지는 계속 보내고, 대상별 결과를 job["chain"](목록)에 남긴다(실패해도 이 parse 작업 자체는
        이미 done — 과업 설명대로 체이닝 실패는 기록만, 안 멈춤)."""
        urls = list(pc.cfg().service.trigger.chain_structure_url)  # S7c — 설정 객체(쉼표 목록 — strip·빈 것 버림)
        if not urls:
            return
        token = reveal(pc.cfg().service.trigger.token) or ""  # S7c — 설정 객체(비밀)
        meta = self._parse_output_meta(log_text)
        body = json.dumps(meta).encode()
        results = []
        for url in urls:
            try:
                req = urllib.request.Request(
                    url.rstrip("/") + "/jobs",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    ok = 200 <= resp.status < 300
                results.append({"url": url, "ok": ok})
            except Exception as e:  # 이 대상만 실패 기록 — 다음 대상은 그대로 시도(요건: 서로 독립)
                results.append({"url": url, "ok": False, "error": f"{type(e).__name__}: {e}"})
        job["chain"] = results
        self._save()


class Handler(BaseHTTPRequestHandler):
    server_version = "TriggerServer/1"

    def log_message(self, fmt, *args):
        pass  # 토큰·문서 내용을 담을 수 있는 요청 로그를 아예 안 남김(code.md 경계·보안)

    def _check_auth(self):
        if self.server.allow_no_token and not self.server.token:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        supplied = header[len("Bearer ") :]
        return hmac.compare_digest(supplied.encode("utf-8"), (self.server.token or "").encode("utf-8"))

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self, max_bytes, required=False):
        length = self.headers.get("Content-Length")
        if length is None:
            if required:
                raise _BadRequest("Content-Length 필요")
            return b""
        try:
            n = int(length)
        except ValueError as err:
            raise _BadRequest("Content-Length 형식이 올바르지 않음") from err
        if n < 0:  # 보안 검토(10-14) — 음수면 rfile.read(-1)이 "전부 읽기"로 상한을 건너뜀
            raise _BadRequest("Content-Length가 음수")
        if n > max_bytes:
            raise _TooLarge()
        return self.rfile.read(n)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            self._json(200, self.server.job_manager.health())
            return
        if not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        if path == "/jobs":
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                limit = max(1, min(500, int(qs.get("limit", ["50"])[0])))
            except ValueError:
                limit = 50
            self._json(200, {"jobs": self.server.job_manager.list(limit)})
            return
        if path.startswith("/jobs/"):
            job = self.server.job_manager.get(path[len("/jobs/") :])
            self._json(200, job) if job else self._json(404, {"error": "no such job"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        jm = self.server.job_manager
        if jm.stopping and path in ("/jobs", "/upload"):
            self._json(503, {"error": "종료 중 — 새 작업 안 받음"})
            return
        if path == "/jobs":
            self._handle_submit()
        elif path == "/upload":
            self._handle_upload()
        else:
            self._json(404, {"error": "not found"})

    def _handle_submit(self):
        jm = self.server.job_manager
        try:
            raw = self._read_body(JOBS_MAX_BYTES) or b"{}"
        except _TooLarge:
            self._json(413, {"error": "본문이 너무 큼"})
            return
        except _BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("json object 필요")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
            self._json(400, {"error": f"잘못된 요청: {e}"})
            return
        try:
            source = payload.get("source")
            if jm.module == "parse":
                if not source:
                    raise ValueError("parse 작업은 source 필요")
                source = validate_source(source, jm.source_root)
            # ponytail: docs는 검증·기록만(job record에 보여줌) — cli/pipeline.py parse 서브커맨드에 특정
            # 문서 목록만 골라 받는 공개 플래그가 아직 없어 하위 프로세스에는 안 넘김(그 필요가 생기면
            # --docs-from 공개 플래그를 pipeline.py에 추가하고 여기서 연결).
            docs = _validate_docs(payload.get("docs"))
            args_parsed = _validate_args(jm.module, payload.get("args"))
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        try:
            job_id = jm.submit(source, docs, args_parsed)
        except QueueFullError:
            self._json(429, {"error": "대기열 가득 참"})
            return
        self._json(202, {"job_id": job_id})

    def _handle_upload(self):
        jm = self.server.job_manager
        if jm.module != "parse":
            self._json(400, {"error": "upload은 parse 서버에서만 받음"})
            return
        try:
            name = _sanitize_filename(self.headers.get("X-Filename"))
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        try:
            body = self._read_body(self.server.upload_max_bytes, required=True)
        except _TooLarge:
            self._json(413, {"error": "업로드가 너무 큼"})
            return
        except _BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        if not body:
            self._json(400, {"error": "본문이 비어 있음"})
            return
        dest_dir = jm.out_dir / "inbox" / time.strftime("%Y-%m-%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        from common.core.paths import atomic_write_bytes

        atomic_write_bytes(dest, body)
        try:
            source = validate_source(str(dest), jm.source_root)
            job_id = jm.submit(source, [], [])
        except QueueFullError:
            self._json(429, {"error": "대기열 가득 참"})
            return
        except ValueError as e:
            self._json(400, {"error": str(e)})
            return
        self._json(202, {"job_id": job_id, "saved": str(dest.relative_to(jm.app_root))})


def make_server(
    module, app_root, host, port, token, allow_no_token, cmd_builder=None, queue_max=None, upload_max_mb=None, socket_timeout_sec=None
):
    jm = JobManager(module, app_root, cmd_builder=cmd_builder, queue_max=queue_max)
    # 보안 검토(10-14) — 느린 클라이언트가 스레드를 계속 붙잡지 못하게 소켓 read 상한(StreamRequestHandler.setup()이
    # timeout 클래스 속성을 보면 connection.settimeout()을 건다). Handler(모듈 전역)를 직접 바꾸지 않고 이 서버
    # 인스턴스만의 서브클래스로 — 같은 프로세스에 여러 make_server()(시험)가 있어도 서로 안 건드림.
    timeout = socket_timeout_sec if socket_timeout_sec is not None else pc.cfg().service.trigger.socket_timeout_sec
    handler_cls = type("TriggerHandler", (Handler,), {"timeout": timeout})
    httpd = ThreadingHTTPServer((host, port), handler_cls)
    httpd.daemon_threads = True
    httpd.job_manager = jm
    httpd.token = token
    httpd.allow_no_token = allow_no_token
    httpd.upload_max_bytes = (upload_max_mb or pc.cfg().service.trigger.upload_max_mb) * 1024 * 1024
    return httpd, jm


def _serve(httpd, jm, timeout_env="TRIGGER_SHUTDOWN_TIMEOUT_SEC", default_timeout=300.0):
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    except Exception:
        pass
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    print(f"[trigger_server] module={jm.module} http://{host}:{port} 대기열 상한 {jm.queue.maxsize}", flush=True)
    try:
        while not stop_event.wait(0.5):
            pass
    finally:
        jm.stop_accepting()
        jm.wait_idle(float(pc.by_env(timeout_env, default_timeout)))  # S7c — 설정 객체(timeout_env는 pipeline 칸 이름)
        httpd.shutdown()
        th.join(timeout=5)
        print("[trigger_server] 종료", flush=True)


def _client_request(base, method, path, token, payload, timeout):
    """client 서브커맨드 공용 호출 — 토큰은 호출부가 넘김(여기서 env를 직접 안 읽음, 시험이 가짜 토큰을 넣기 쉽게)."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"error": str(e)}
        return e.code, body


def _client_main(argv):
    """`trigger_server client --url <base> submit|status|wait` — curl 인용 없이 운영자 셸에서 쓰는 stdlib
    클라이언트. 토큰은 TRIGGER_TOKEN env(모듈 docstring 참조)."""
    ap = argparse.ArgumentParser(prog="trigger_server client")
    ap.add_argument("--url", required=True)
    ap.add_argument("--timeout", type=float, default=pc.cfg().service.trigger.client_timeout)
    sub = ap.add_subparsers(dest="action", required=True)
    s1 = sub.add_parser("submit")
    s1.add_argument("--source", required=True)
    s1.add_argument("--docs", nargs="*", default=None)
    s1.add_argument("--arg", dest="args_", action="append", default=None, help="허용 목록 args 토큰 하나(여러 번 지정 가능)")
    s2 = sub.add_parser("status")
    s2.add_argument("job_id")
    s3 = sub.add_parser("wait")
    s3.add_argument("job_id")
    s3.add_argument("--poll", type=float, default=1.0)
    s3.add_argument("--wait-timeout", type=float, default=300.0)
    a = ap.parse_args(argv)
    token = reveal(pc.cfg().service.trigger.token) or ""  # S7c — 설정 객체(비밀)
    if a.action == "submit":
        payload = {"source": a.source}
        if a.docs:
            payload["docs"] = a.docs
        if a.args_:
            payload["args"] = a.args_
        code, body = _client_request(a.url, "POST", "/jobs", token, payload, a.timeout)
        print(json.dumps(body, ensure_ascii=False))
        return 0 if code == 202 else 1
    if a.action == "status":
        code, body = _client_request(a.url, "GET", f"/jobs/{a.job_id}", token, None, a.timeout)
        print(json.dumps(body, ensure_ascii=False))
        return 0 if code == 200 else 1
    # wait
    end = time.time() + a.wait_timeout
    body = None
    while time.time() < end:
        code, body = _client_request(a.url, "GET", f"/jobs/{a.job_id}", token, None, a.timeout)
        if code == 200 and str(body.get("status", "")).startswith(("done", "failed")):
            print(json.dumps(body, ensure_ascii=False))
            return 0 if body["status"] == "done" else 1
        time.sleep(a.poll)
    print(json.dumps(body if body is not None else {"error": "job 상태 기다리던 중 시간 초과"}, ensure_ascii=False))
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "client":
        raise SystemExit(_client_main(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", choices=["parse", "structure"])
    a = ap.parse_args(argv)
    if not a.module:
        raise SystemExit("--module parse|structure 필요")
    from common.config.settings import require_run_env

    require_run_env(
        "trigger_server", sections=("pipeline",)
    )  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    trg = pc.cfg().service.trigger  # S7c — 설정 객체(TRIGGER_*)
    token = reveal(trg.token) or ""
    if not token.strip():
        token = (
            ""  # 공백만인 토큰은 토큰 없음(VS7c1 R-2, 사용자 10-27) — 아래에서 시작 거부(PC는 TRIGGER_ALLOW_NO_TOKEN=1이면 경고 뒤 무인증)
        )
    allow_no_token = trg.allow_no_token
    if not token and not allow_no_token:
        raise SystemExit("[trigger_server] TRIGGER_TOKEN 없음 — 설정하거나(운영) PC 전용 TRIGGER_ALLOW_NO_TOKEN=1(인증 없이 시작, 경고)")
    if not token:
        print(
            "[trigger_server] 경고: TRIGGER_TOKEN 없이 시작(TRIGGER_ALLOW_NO_TOKEN=1) — 모든 요청이 인증 없이 허용됨(PC 전용)", flush=True
        )
    host = trg.host
    for name in ("TRIGGER_PORT", "TRIGGER_PARSE_PORT", "TRIGGER_STRUCTURE_PORT"):
        pc.checked(name)  # 형식 틀린 포트는 옛처럼 실패(조용히 기본 포트로 뜨지 않게)
    # 모듈별 포트(S7e2 — 옛 compose가 서비스마다 TRIGGER_PORT=${TRIGGER_PARSE_PORT}/${TRIGGER_STRUCTURE_PORT}로 넘기던 것을 settings.yaml 칸으로, 사용자 10-28):
    # 그 모듈 칸(parse_port·structure_port)을 준 값 > 공통 TRIGGER_PORT를 준 값 > 모듈 기본(8770·8771) — 공통 칸 하나만 있어도 두 상주 서버가
    # 같은 포트를 잡지 않게 모듈 칸이 먼저(리뷰 S7e2 — 옛 compose는 서비스마다 덮어 공통 값이 상주 컨테이너에 안 걸렸음)
    # 이미지 안(상주 컨테이너 data-pipeline-parse·structure)에서는 공통 칸을 쓰지 않는다(VS7e2 R-1 — 옛 compose가 서비스마다 TRIGGER_PORT를
    # 덮어 env 파일의 공통 값이 상주 컨테이너에 걸린 적이 없음 · healthcheck도 모듈 포트를 봄). PC(직접 실행)는 옛처럼 공통 칸도.
    own = pc.given("TRIGGER_PARSE_PORT" if a.module == "parse" else "TRIGGER_STRUCTURE_PORT")
    module_port = trg.parse_port if a.module == "parse" else trg.structure_port
    if own is None and trg.port is not None and IN_IMAGE:
        print(
            "[trigger_server] 공통 pipeline.service.trigger.port는 상주 컨테이너에서 쓰지 않음 — parse_port·structure_port로(옛 compose와 같음)",
            flush=True,
        )
    port = own if own is not None else (trg.port if trg.port is not None and not IN_IMAGE else module_port)
    from common.core.paths import APP_ROOT

    httpd, jm = make_server(a.module, APP_ROOT, host, port, token, allow_no_token)
    _serve(httpd, jm)


if __name__ == "__main__":
    main()
