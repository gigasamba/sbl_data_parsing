#!/usr/bin/env python3
"""파싱 시작 점검 — 서버 안 샘플 폴더 또는 Object Storage 문서로 파싱을 트리거하고 끝날 때까지 본다(사용자 10-14).
서버 코드 폴더 루트에서 네이티브로 실행 — 이미지에는 안 들어감, 새 패키지 없음(stdlib). S6b — 자리 deploy/host/scripts/(옛 저장소 루트·deploy/).

두 길(같은 파싱 코드 — cli/pipeline.py parse):
  기본   deploy/host/scripts/trigger.sh parse(1회 job, compose.pipeline.yml) — 폴더는 DOC_SRC로 /data/docs에 읽기 전용 연결.
         --chain이면 이어서 structure·load까지.
  --url  상주 트리거 서버(data-pipeline-parse 컨테이너 — 옛 data-parsing, POST /jobs) — Object Storage(s3://·rdb:)만, --limit 없이. 서버 폴더 경로는 트리거 서버가
         output/ 밖이라 거부하므로 기본 길로. 체인(structure·load)은 서버의 CHAIN_STRUCTURE_URL이 맡음.

  python deploy/host/scripts/parse_trigger_test.py --source /srv/rag/samples                       # 서버 샘플 폴더
  python deploy/host/scripts/parse_trigger_test.py --source s3://버킷/접두 --limit 5 [--chain]     # Object Storage 몇 건
  TRIGGER_TOKEN=… python deploy/host/scripts/parse_trigger_test.py --source s3://버킷/접두 --url http://127.0.0.1:8770
설정: DATA_PIPELINE_IMAGE·RAG_OUT 등은 trigger.sh와 같음(settings.yaml — S7e1, 옛 /srv/rag/env/pipeline.env). TRIGGER_TOKEN(--url 길)은 부르는 사람이 env로 준다
      (호스트 클라이언트 — 서버 쪽 토큰은 settings.yaml required.tokens.trigger).
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent  # deploy/host/scripts/ — trigger.sh가 같은 폴더(S6b)
REMOTE = ("s3://", "rdb:")


def via_trigger_sh(a):
    env = dict(os.environ)  # env 남김 — 하위 프로세스
    source = a.source
    if not source.startswith(REMOTE):  # 서버 폴더 → 컨테이너 /data/docs(compose의 DOC_SRC)
        env["DOC_SRC"] = str(Path(source).resolve())
        source = "/data/docs"
    args = ["--source", source] + (["--source-limit", str(a.limit)] if a.limit else [])
    rc = subprocess.call(["bash", str(SCRIPTS / "trigger.sh"), "parse", *args], env=env)
    for mod in ("structure", "load") if a.chain and rc == 0 else ():
        rc = subprocess.call(["bash", str(SCRIPTS / "trigger.sh"), mod], env=env)
        if rc:
            break
    return rc


def via_server(a):
    from pipeline.trigger_server import _client_request

    if not a.source.startswith(REMOTE):
        raise SystemExit("--url(상주 트리거 서버)은 s3://·rdb: 만 — 서버 폴더는 --url 없이(trigger.sh 길)")
    token = os.environ.get("TRIGGER_TOKEN", "")  # env 남김 — 호스트 도구(호스트 도구 인자 성격)
    if a.limit:  # 트리거 서버 args 허용 목록에 --source-limit 없음(parse는 --mode만) — 몇 건 시험은 trigger.sh 길로
        raise SystemExit("--limit는 --url 없이(trigger.sh 길)만")
    code, body = _client_request(a.url, "POST", "/jobs", token, {"source": a.source}, 10)
    if code != 202:
        print(f"[거부] {code} {body}")
        return 1
    jid = body["job_id"]
    print(f"[제출] job {jid}")
    end = time.time() + a.wait
    while time.time() < end:
        code, body = _client_request(a.url, "GET", f"/jobs/{jid}", token, None, 10)
        st = str(body.get("status", ""))
        if st.startswith(("done", "failed")):
            print(f"[{st}] {body}")
            return 0 if st == "done" else 1
        time.sleep(5)
    print(f"[시간 초과] {a.wait}s — 마지막 상태 {body}")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="서버 폴더 또는 s3://버킷/접두 · rdb:<원천>")
    ap.add_argument("--limit", type=int, default=0, help="Object Storage 몇 건만(--source-limit)")
    ap.add_argument("--chain", action="store_true", help="trigger.sh 길에서 parse 뒤 structure·load까지")
    ap.add_argument("--url", help="상주 트리거 서버(예 http://127.0.0.1:8770) — 주면 그쪽으로")
    ap.add_argument("--wait", type=float, default=3600, help="--url 길에서 끝날 때까지 기다릴 초")
    a = ap.parse_args()
    sys.exit(via_server(a) if a.url else via_trigger_sh(a))


if __name__ == "__main__":
    main()
