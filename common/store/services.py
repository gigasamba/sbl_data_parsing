#!/usr/bin/env python3
"""외부 서비스 연결 — Docker에 떠 있는 pgvector를 찾아 연결하는 것이 기본, 없으면 Docker 없이 로컬.
모델(LLM·VLM·OCR VLM·임베딩)은 OpenAI 호환 주소를 환경변수로 자유롭게 바꿔 끼움 — 회사 문서가 나가므로 **내부망 주소만**(DONT 13).

찾는 순서(설정이 있으면 설정 우선):
  pgvector   PG_HOST·PG_PORT를 직접 줬으면 그대로 · 아니면 `docker ps`에서 이미지·이름에 pgvector가 든 컨테이너(기본 `rag-postgres`, 이미지 pgvector/pgvector)의 5432 공개 포트 —
             'postgres'로 찾지 않는 이유: 같은 서버의 다른 PostgreSQL(Gitea 등, 벡터 확장 없음)을 잘못 잡지 않게
             → 접속 시험(PG_PASSWORD 또는 PG_CONN_FILE 필요 — 비밀번호는 컨테이너에서 읽지 않음) → 되면 pgvector, 안 되면 로컬 묶음
             docker 명령이 권한 오류·없음이면(SI26) 듣는 포트로 대체 탐지: 127.0.0.1(PG_HOST가 있으면 그 주소)의 5432·15432를
             TCP로 확인 + 자격 증명이 있으면 psycopg로 SELECT 1까지. 비밀값은 로그에 안 찍고 '포트 탐지'로만 표시.
모델 엔드포인트(접두어 LLM·VLM·EMBED): <접두어>_BASE_URL(…/v1) · <접두어>_MODEL · <접두어>_API_KEY(선택).
  외부 주소는 거부 — 개발 PC 실험에서만 <접두어>_ALLOW_EXTERNAL=1(RUN_ENV=local일 때만 — common/ai/guard.py).
사용: python common/services.py        → 연결 상태 표(비밀값은 출력 안 함)
"""

import json
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from common.ai.guard import external_allowed, is_internal, require_internal  # noqa: F401 — 내부망 가드는 common/guard.py 한 곳
from common.ai.guard import urlopen as guard_urlopen
from common.config.settings import COMMON, by_env, cfg, put, reveal  # S7b 설정 객체 · S7e2 put(덮기 파일)
from common.core.console import utf8_stdout

HERE = Path(__file__).resolve().parent

PORT_RE = re.compile(r"(?:(\d+\.\d+\.\d+\.\d+|\[::\]):)?(\d+)->(\d+)/tcp")
PG_FALLBACK_PORTS = ("5432", "15432")


def docker_ps():
    """→ (rows, reason). rows=[(이름, 이미지, [(호스트 IP, 호스트 포트, 컨테이너 포트)])], reason=None(정상)·'missing'(docker 없음/실행 실패)·
    'denied'(권한 오류, SI12) — detect_pg·detect_ov가 'missing'·'denied'일 때 포트로 대체 탐지(SI26). 환경변수(비밀값)는 읽지 않음."""
    exe = shutil.which("docker") or shutil.which("podman")
    if not exe:
        return [], "missing"
    try:
        r = subprocess.run([exe, "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Ports}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return [], "missing"
    if r.returncode != 0:
        if "permission denied" in (r.stderr or "").lower():  # SI12 — docker ps 권한 없음은 "컨테이너 없음"과 다른 문제라 따로 안내
            print(
                "[services] docker ps 권한 없음 — 실행 계정을 docker 그룹에 추가하거나, "
                "PG_HOST·PG_PORT(pgvector)를 직접 지정 — 듣는 포트로 대체 탐지 시도",
                file=sys.stderr,
                flush=True,
            )
            return [], "denied"
        return [], "missing"
    out = r.stdout
    rows = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) == 3:
            ports = [((ip if ip and ip not in ("0.0.0.0", "[::]") else "127.0.0.1"), hp, cp) for ip, hp, cp in PORT_RE.findall(p[2])]
            rows.append((p[0], p[1], ports))
    return rows, None


def _tcp_open(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _pg_capable(c):
    """이름이 아니라 붙어서 능력 확인(XS1): SELECT 1 + vector 확장 존재 + PG_SCHEMA 접근 가능(있음 또는 만들 권한).
    → (ok, 설명). 비밀값은 반환·로그에 내지 않는다."""
    from common.store.pg import PG

    db = PG(c)
    db.q("SELECT 1")
    if not db.q("SELECT 1 FROM pg_extension WHERE extname='vector'"):
        return False, "vector 확장 없음"
    if not db.q("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (c["PG_SCHEMA"],)):
        priv = db.q("SELECT has_database_privilege(current_user, current_database(), 'CREATE') p")
        if not (priv and priv[0].get("p")):
            return False, f"스키마 {c['PG_SCHEMA']} 없음·만들 권한 없음"
    return True, "능력 확인됨"


def _probe_pg_port(host, ports=PG_FALLBACK_PORTS):
    """docker 권한 없을 때 포트로 pgvector 대체 탐지(SI26) — TCP 연결 + 자격 증명 있으면 능력 확인(_pg_capable)까지.
    확장 없는 다른 PostgreSQL(Gitea 등)에 자격 증명이 통해도 능력 확인에서 걸러지고 다음 포트로 넘어간다(XS1).
    성공한 포트 문자열(str) 또는 못 찾으면 None. 비밀값은 읽기만 하고 반환·로그에 내지 않는다."""
    st = cfg().connections.pg  # S7b — 설정 객체
    has_cred = bool(reveal(st.password) or st.conn_file)
    for port in ports:
        if not _tcp_open(host, port):
            continue
        if not has_cred:
            return port  # 자격 증명 없음 — TCP 응답만으로 best-effort
        # 임시 덮기 — pg.conf()가 이 후보를 설정 객체로 읽게 이 블록 동안만 바꿔 끼움(S7e2 — 옛 os.environ 잠깐 쓰기·복원)
        try:
            from common.store.pg import conf

            with COMMON.env(PG_HOST=host, PG_PORT=port):
                ok, _why = _pg_capable(conf())
            if ok:
                return port
            continue  # 능력 확인 실패(벡터 확장 없음 등) — 이 후보는 건너뛰고 다음 포트로
        except (Exception, SystemExit):
            continue
    return None


def _find(rows, word, cport=None):
    for name, image, ports in rows:
        if word in name.lower() or word in image.lower():
            for ip, hp, cp in ports:
                if cport is None or cp == cport:
                    return name, ip, hp
    return None


def detect_pg(docker=None):
    """docker: (rows, reason) — docker_ps()와 같은 꼴, None이면 새로 조회. → (ok, 설명).
    성공하면 설정 PG_HOST·PG_PORT를 채운다(settings.put — 이 프로세스·뒤에 띄우는 자식 pgstore도 같은 값, S7e2)."""
    rows, reason = docker if docker is not None else docker_ps()
    src = "설정"
    st = cfg().connections.pg  # S7b — 설정 객체(PG_PORT는 옛 글자 truthy와 같게 None 여부로)
    if not (st.host or st.port is not None or st.conn_file):
        hit = _find(rows, "pgvector", "5432")
        if hit:
            name, ip, hp = hit
            put(PG_HOST=ip, PG_PORT=hp)  # S7e2 — 덮기 파일(이 프로세스·자식)
            src = f"docker {name}"
        elif reason:  # docker 권한 오류·없음(SI26) — 듣는 포트로 대체 탐지
            host = st.host or "127.0.0.1"
            port = _probe_pg_port(host)
            if not port:
                return False, f"pgvector 컨테이너 없음(docker {reason} — 포트 {'·'.join(PG_FALLBACK_PORTS)}도 응답 없음)"
            put(PG_HOST=host, PG_PORT=port)  # S7e2 — 덮기 파일(이 프로세스·자식)
            src = "포트 탐지"
        else:
            return False, "pgvector 컨테이너 없음"
    st = cfg().connections.pg  # 위에서 put했으면 새 객체
    if not (reveal(st.password) or st.conn_file):
        return False, f"{src}: PG_PASSWORD(.env) 없음"
    try:
        from common.store.pg import conf

        c = conf()
        ok, why = _pg_capable(c)  # 이름이 아니라 붙어서 확인(vector 확장·스키마) — XS1
        if not ok:
            return False, f"{src} {c['PG_HOST']}:{c['PG_PORT']}: {why}"
        return True, f"{src} {c['PG_HOST']}:{c['PG_PORT']}"
    except Exception as e:
        return False, f"{src}: 접속 실패({type(e).__name__})"


def connect(a):
    """명령 인자 a(--pg·--local)에 저장소 기본값을 채움: 지정이 없으면 Docker pgvector → 없으면 로컬. 한 줄로 알림."""
    docker = docker_ps()
    msg = []
    if not getattr(a, "local", False):
        ok, why = detect_pg(docker)  # --pg를 줘도 주소(PG_HOST·PG_PORT)는 찾음 — 안 그러면 기본 5432로만 붙음
        if a.pg and not ok:
            raise SystemExit(f"[연결] --pg(또는 MCP_STORE=pg)를 지정했지만 PostgreSQL에 붙지 못함: {why}")
        a.pg = ok
        msg.append(f"저장소: {'pgvector(' + why + ')' if ok else '로컬 묶음 — ' + why}")
    print("[연결] " + " · ".join(msg), flush=True)


def model_status(prefix):
    base, model = by_env(f"{prefix}_BASE_URL"), by_env(f"{prefix}_MODEL")  # S7b — 설정 객체(이름을 글자로 지음)
    if not base:
        return "미설정", "", ""
    internal = (
        "내부"
        if is_internal(base)
        else ("외부(허용 — 개발 PC)" if external_allowed(prefix) else "외부 — 거부됨(ALLOW_EXTERNAL=1 + RUN_ENV=local 필요)")
    )
    if internal.startswith("외부 — 거부"):  # 막힌 외부 주소에는 /models도 안 보냄(키가 헤더로 나감 — 재검증 10-02)
        return internal, model or "(모델 미설정)", "확인 안 함(외부 거부)"
    req = urllib.request.Request(base.rstrip("/") + "/models")
    key = reveal(by_env(f"{prefix}_API_KEY"))
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with guard_urlopen(req, 5, prefix) as r:
            ids = [m.get("id") for m in json.load(r).get("data", [])]
        reach = "응답" + ("" if not model else (" · 모델 있음" if model in ids else f" · 모델 없음(서버: {', '.join(ids[:3])})"))
    except Exception as e:
        reach = f"응답 없음({type(e).__name__})"
    return internal, model or "(모델 미설정)", reach


def status():
    docker = docker_ps()
    rows, reason = docker
    print("| 항목 | 연결 |", "|---|---|", sep="\n")
    print(
        f"| Docker 컨테이너 | {', '.join(n for n, _, _ in rows) or ('없음(또는 Docker 없음)' if not reason else f'docker {reason} — 포트로 대체 탐지')} |"
    )
    for label, f in (("pgvector", detect_pg),):
        ok, why = f(docker)
        print(f"| {label} | {'✓ ' if ok else '✗ '}{why} |")
    print("\n| 모델 | 주소 구분 | 모델 | 상태 |", "|---|---|---|---|", sep="\n")
    for p, label in (("LLM", "LLM(답변·분해·그래프)"), ("VLM", "VLM(이미지 파싱)"), ("EMBED", "임베딩")):
        print(f"| {label} | " + " | ".join(model_status(p)) + " |")


if __name__ == "__main__":
    utf8_stdout()
    status()
