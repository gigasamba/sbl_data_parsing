#!/usr/bin/env python3
"""점검기 하나(0.2.0 — pl-46: 옛 pipeline/check_env.py·common/store/services.py·common/check/ping_models.py를 합침).
  python -m common.check.checker env        설치·스택·문서 폴더·경로 묶음·PG 스키마 권한·requirements 대조(옛 check_env — data-pipeline 이미지)
  python -m common.check.checker services   PG·모델 연결 표(옛 services — /models만, 기본)
  python -m common.check.checker ping       LLM·VLM·EMBED 실호출 1건씩(옛 ping_models — 실패가 있으면 종료 코드 1)
pipeline 앱 칸은 importlib 문자열로 늦게 읽는다(common은 앱을 정적으로 import하지 않음 — check_modules ②, mcp-server 이미지엔 pipeline 없음).
비밀값·키는 출력하지 않는다. 회사 데이터는 보내지 않는다(ping은 "ping"·1×1 PNG만).
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서

# isort: split
import base64
import importlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from collections import Counter
from pathlib import Path

from common.ai import guard
from common.ai import llm as A  # 모델 호출(0.2.0 — 옛 common.ai.adk, pl-46)
from common.ai.guard import external_allowed, is_internal
from common.config import settings as C  # common 칸(S7c — 설정 객체 · cfg()·given()·reveal()·COMMON.env())
from common.config.settings import by_env, cfg, reveal  # S7b — 설정 객체(이름을 글자로 짓는 칸은 by_env)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, doc_dir  # output/·requirements·문서 폴더 등 런타임 경로용(C2, 독립 검토 10-13)
from common.store.pg import detect_pg


def _pc():
    """pipeline 칸 설정 모듈(pipeline.config) — 없으면(mcp-server 이미지) None."""
    try:
        return importlib.import_module("pipeline.config")
    except ImportError:
        return None


# pipeline.extract.engines는 함수 안에서 늦게 import(rag-core 이미지엔 parse/가 없음 — 프리즈 전 감사 10-16,
# 여기서 top-level import하면 rag-core에서 check_env 자체가 크래시한다).

ROOT = APP_ROOT
DOCKER_DIR = ROOT / "deploy" / "docker"  # requirements-core.txt·requirements-image.txt·네이티브 requirements.txt가 있는 곳

# 이미지(Docker)에만 있어도 되는 패키지 — 근거를 반드시 주석에 적는다(SI28). 지금은 없음(diff가 나오면
# 네이티브에 추가할지/여기에 올릴지는 사람 판단 — "차이=버그"로 단정하지 않는다).
REQ_IMAGE_ONLY_ALLOW: set = set()

# 과거 두 번(rapidfuzz SI1·psycopg SI28) requirements에서 빠진 채 커밋된 적이 있어 실제 import까지 확인한다.
CRITICAL_MODULES = ("psycopg", "psycopg_pool", "rapidfuzz", "pymssql", "openpyxl")


def line(ok, name, detail=""):
    print(f"  [{'OK ' if ok else '-- '}] {name}" + (f" — {detail}" if detail else ""))


def _parse_requirements(path):
    """requirements 파일 → {패키지명(소문자, extras 제거): 버전 또는 None}. 파일 없으면 {}."""
    out = {}
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln or ln.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(==\s*([^\s;]+))?", ln)
        if not m or not m.group(1):
            continue
        out[m.group(1).lower().replace("_", "-")] = m.group(4)
    return out


def check_requirements(native_path=None, docker_paths=None):
    """네이티브(dev/requirements.txt) ↔ Docker(requirements-core.txt + requirements-image.txt) 패키지·버전 차이(SI28).
    → (행 리스트[(패키지, 이미지 버전, 네이티브 버전, 사유)], bad=차이 있으면 True — REQ_IMAGE_ONLY_ALLOW는 제외)."""
    native_path = native_path or (DOCKER_DIR / "requirements.txt")
    docker_paths = docker_paths or [DOCKER_DIR / "requirements-core.txt", DOCKER_DIR / "requirements-image.txt"]
    native = _parse_requirements(native_path)
    docker = {}
    for p in docker_paths:
        docker.update(_parse_requirements(p))
    rows, bad = [], False
    for name in sorted(docker):
        if name in REQ_IMAGE_ONLY_ALLOW:
            continue
        img_ver = docker[name] or "(미지정)"
        if name not in native:
            rows.append((name, img_ver, "없음", "이미지에만 있음"))
            bad = True
        elif native[name] != docker[name]:
            rows.append((name, img_ver, native[name] or "(미지정)", "버전 다름"))
            bad = True
    return rows, bad


def check_critical_imports():
    """CRITICAL_MODULES가 지금 이 인터프리터에서 실제 import 가능한지(requirements에 있어도 미설치일 수 있음)."""
    return [(m, importlib.util.find_spec(m) is not None) for m in CRITICAL_MODULES]


# OP15(c1) — env-guide 1-2 경로 묶음(서버 LLM이 바꿀 곳). 각 항목: (이름, 값→실제 경로 또는 None(형식 검사만)).
# 값 없으면 '미설정(선택)'(오류 아님) · 값이 있는데 경로가 없으면 경고만(line(False, …)) — 실패 종료 아님(req_bad에 안 섞음).
def _parse_source_path(v):
    return None if v.startswith("rdb:") else Path(v)  # rdb:csv는 형식만(파일 경로 아님) · s3://는 11-01에 지움(경로로 보고 없으면 경고)


PATH_BUNDLE = [
    ("GOLD_DIR", Path),
    ("SOURCES_FILE", Path),
    ("PARSE_SOURCE", _parse_source_path),
]


def _bundle_value(name):
    """PATH_BUNDLE 이름의 준 값(없거나 빈 값이면 None) — 칸이 pipeline 절(GOLD_DIR 등)에 있거나 common 절에 있음(S7c — 설정 객체 · GLOSSARY_DIR은 pl-38에 지움 — 마스터 표)."""
    if name == "GOLD_DIR":
        return _pc().gold_dir() or None  # S7e2 — 이미지 안 /data/gold 마운트 기본(pc.gold_dir)
    v = _pc().given(name)
    return v if v is not None else C.given(name)


def check_path_bundle(dump_dir=None):
    """env-guide 1-2 경로 묶음이 실제로 있는지 보고 — 미설정은 '미설정(선택)', 있는데 경로가 없으면 경고만
    (둘 다 check_env 종료 코드에 안 섞음, 정보성). GOLD_DIR은 추가로 문서 폴더(dump_dir)와 이름 짝(파일 이름
    stem 일치)까지 — 사람 정답 폴더가 실제 문서를 가리키는지(OP15 c1)."""
    print("\n== 경로 묶음 (env-guide 1-2 — 서버 LLM이 .env만 바꿔 맞추는 곳) ==")
    for name, resolve in PATH_BUNDLE:
        v = _bundle_value(name)
        if not v:
            line(True, name, "미설정(선택)")
            continue
        p = resolve(v)
        if p is None:  # 형식만 있는 값(auto·rdb:*·s3://) — 경로 존재를 안 봄
            line(True, name, v)
        else:
            line(p.exists(), name, str(p) if str(p) != v else v)

    gold_dir = _bundle_value("GOLD_DIR")
    if gold_dir and Path(gold_dir).exists() and dump_dir is not None:
        golds = {f.stem.lower() for f in Path(gold_dir).iterdir() if f.is_file() and f.suffix.lower() in (".txt", ".md")}
        docs = {p.stem.lower() for p in dump_dir.iterdir() if p.is_file() and p.name != ".gitkeep"} if dump_dir.exists() else set()
        if docs:
            matched = golds & docs
            line(bool(matched), "GOLD_DIR 이름 짝", f"문서 {len(docs)}건 중 정답 짝 {len(matched)}건(정답 파일 {len(golds)}개)")

    try:  # pl-38 — 용어집·고객 명부는 PG 마스터 표(<PG_SCHEMA>_master)
        from common.store import master

        m = master.get()
        line(True, "마스터 표", f"해시 {m.hash[:8]} · " + " · ".join(f"{n} {len(r)}행" for n, r in m.tables.items()))
    except SystemExit as ex:
        line(False, "마스터 표", str(ex))


def check_pg_schema():
    """OP22 — 개발 서버 검증대(ai_test 등 별도 PG_SCHEMA)에 붙을 때 그 스키마를 만들거나 쓸 권한이 있는지
    읽기 전용으로 확인(has_schema_privilege·has_database_privilege(CREATE) — 실제 CREATE SCHEMA는 안 함,
    쓰기 0). PG 설정이 없거나(PG_PASSWORD 등) 연결이 안 되면 '건너뜀'(오류 아님 — check_env는 정보성)."""
    print("\n== PostgreSQL 스키마 권한 (OP22 — PG_SCHEMA 쓰기 전 확인) ==")
    try:
        from common.store import pg as PG
    except Exception as ex:
        line(True, "PG_SCHEMA 권한", f"건너뜀({type(ex).__name__})")
        return
    line(
        True,
        "AD41 모드",
        "실 PG(연결 정보 있음)"
        if PG.has_conn()
        else "스탠드인(sqlite, output/pg_standin) — PG_PASSWORD·PG_CONN_FILE 채우면 코드 변경 없이 실 PG로",
    )
    try:
        c = PG.conf()
    except (SystemExit, ValueError) as ex:  # ValueError — 형식 틀린 PG_PORT(S7c1 · VS7b R-7: conf()가 읽는 자리에서 실패, 값은 안 찍음)
        line(True, "PG_SCHEMA 권한", f"건너뜀 — {ex}")
        return
    try:
        conn = PG.PG(c)
    except Exception as ex:
        line(True, "PG_SCHEMA 권한", f"건너뜀 — 연결 안 됨({type(ex).__name__})")
        return
    schema = c["PG_SCHEMA"]
    try:
        exists = bool(conn.q("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)))
        if exists:
            r = conn.q(
                "SELECT has_schema_privilege(current_user, %s, 'USAGE') AS usage_ok, "
                "has_schema_privilege(current_user, %s, 'CREATE') AS create_ok",
                (schema, schema),
            )[0]
            line(bool(r["usage_ok"]), f"스키마 {schema} USAGE 권한")
            line(bool(r["create_ok"]), f"스키마 {schema} 안 CREATE 권한(표 만들기)")
        else:
            r = conn.q("SELECT has_database_privilege(current_user, current_database(), 'CREATE') AS create_db")[0]
            line(bool(r["create_db"]), f"스키마 {schema} 없음 — DB에 새 스키마 만들 권한")
    except Exception as ex:
        line(False, f"스키마 {schema} 권한 조회 실패", f"{type(ex).__name__} — 조회만 했는데 거부됨, 계정 권한 확인")
    finally:
        try:
            conn.cn.close()
        except Exception:
            pass


def env_main():
    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    if _pc() is None:  # mcp-server 이미지 — pipeline 앱이 없음(설치·스택 점검은 data-pipeline 이미지에서)
        print("  pipeline 앱 없음 — env 점검은 data-pipeline 이미지에서(이 이미지는 services·ping)")
        return 0
    py_env_problem = importlib.import_module("pipeline.tools.resources").py_env_problem  # 10-14 — common.core.resources에서 옮김

    if bad := py_env_problem():  # SI29 — 시스템 python이면 아래 '누락'이 거짓 경보라 먼저 멈춤
        print(f"  [-- ] {bad}\n  → 멈춤: 다른 python으로는 패키지 점검 결과가 틀림(CHECK_ENV_ANY_PY=1이면 계속)")
        if not _pc().cfg().dev.check_env_any_py:  # S7c — 설정 객체(=1 계속)
            return 2
    print("\n== 시스템 도구 ==")
    for tool, why in [
        ("java", "OpenDataLoader"),
        ("tesseract", "Tesseract OCR"),
        ("soffice", "LibreOffice — doc/ppt/hwp 변환"),
        ("gs", "Ghostscript — camelot 선택"),
        ("mineru", "MinerU CLI"),
        ("nvidia-smi", "GPU(선택)"),
    ]:
        line(bool(shutil.which(tool)), tool, why)
    if shutil.which("tesseract"):
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
        line("kor" in langs, "tesseract kor 언어팩")

    print("\n== 스택 (pipeline/extract/engines/<스택>) ==")
    try:
        registry = importlib.import_module("pipeline.extract.engines.registry")  # mcp-server 이미지엔 pipeline이 없음
    except ImportError:
        line(True, "parse 없음(rag-core)", "이 이미지엔 parse/engines가 없음 — 스택 점검 건너뜀")
    else:
        ok_n = 0
        for stack, m in registry.stacks().items():
            tools = m.REQUIRES["tools"]
            miss = [x for x in m.REQUIRES["modules"] if importlib.util.find_spec(x) is None] + [t for t in tools if not shutil.which(t)]
            for e in m.ENGINES:
                miss += [f"{e}: ${v}" for v in registry.missing_env(e)]
            ok_n += not miss
            line(not miss, f"{stack:15s} [{', '.join(m.ENGINES)}]", ("없음: " + ", ".join(miss)) if miss else "")
        print(f"  사용 가능 {ok_n}/{len(registry.stacks())} 스택")
        from common.core.runlog import note

        note(f"사용 가능 스택 {ok_n}/{len(registry.stacks())}")

    dump = doc_dir(required=False)
    print(f"\n== 문서 폴더 {dump or ''} ==")
    if dump is None:
        line(False, "DOC_DIR 미설정", "settings.yaml ops.paths.doc_dir에 경로를 넣거나 --src로 지정")
    else:
        c = Counter(p.suffix.lower() or "(없음)" for p in (dump.iterdir() if dump.exists() else []) if p.is_file() and p.name != ".gitkeep")
        print("  " + (", ".join(f"{k} {v}" for k, v in c.most_common()) or "비어 있음"))

    check_path_bundle(dump)
    check_pg_schema()

    print("\n== 폐쇄망 캐시 (prefetch_models.py로 미리 받은 것) ==")
    home = Path.home()  # HF 임베딩 모델 캐시 점검은 0.2.0에 지움(로컬 임베딩 길 — pl-46)
    for label, p in [
        ("EasyOCR ko+en", home / ".EasyOCR"),
        ("PaddleX (PaddleOCR 한국어)", home / ".paddlex"),
    ]:
        line(p.exists() and any(p.iterdir()), label, str(p))
    line(
        os.environ.get("HF_HUB_OFFLINE") == "1", "HF_HUB_OFFLINE=1", "폐쇄망이면 켜야 모델 다운로드를 시도하지 않음"
    )  # env 남김 — 라이브러리(5-3 H)
    fonts = (
        subprocess.run(["fc-list", ":lang=ko", "family"], capture_output=True, text=True).stdout.strip().splitlines()
        if shutil.which("fc-list")
        else []
    )
    line(
        bool(fonts) or Path("C:/Windows/Fonts/malgun.ttf").exists(),
        "한국어 글꼴(RHEL: google-noto-sans-cjk-ttc-fonts)",
        ", ".join(sorted(set(fonts))[:4]) or "없으면 한글 PDF 렌더·자체 점검(selftest_ocr·make_corpus) 이미지가 깨짐",
    )

    print(f"\n디스크 여유 {shutil.disk_usage(ROOT).free / 1e9:.0f}GB")
    print("\n== VLM (qwen_vlm) ==")
    vlm = C.cfg().models.vlm  # S7c — 설정 객체(VLM_BASE_URL·VLM_MODEL·VLM_API_KEY)
    url = vlm.base_url
    if not url:
        line(False, "VLM_BASE_URL", "미설정 — VLM 엔진(qwen_vlm)은 건너뜀")
    else:
        try:
            req = urllib.request.Request(url.rstrip("/") + "/models")
            key = C.reveal(vlm.api_key)
            if key:
                req.add_header("Authorization", "Bearer " + key)
            with urllib.request.urlopen(req, timeout=5) as r:
                ids = [m.get("id") for m in json.load(r).get("data", [])]
            line(vlm.model in ids, "VLM 엔드포인트", f"{url} · 모델 {ids} · VLM_MODEL={vlm.model}")
        except Exception as ex:
            line(False, "VLM 엔드포인트", f"{url} {type(ex).__name__}")

    print("\n== requirements 대조 — 네이티브 ↔ Docker(core+image) (SI28) ==")
    req_rows, req_bad = check_requirements()
    if not req_rows:
        line(True, "차이 없음")
    else:
        print("  | 패키지 | 이미지 버전 | 네이티브 버전 | 사유 |", "  |---|---|---|---|", sep="\n")
        for name, img_ver, nat_ver, why in req_rows:
            print(f"  | {name} | {img_ver} | {nat_ver} | {why} |")
    print("\n== 핵심 의존성 설치 확인 (SI28 — rapidfuzz·psycopg 두 번 빠졌던 사례) ==")
    for mod, ok in check_critical_imports():
        line(ok, mod)
    return req_bad


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
    try:
        ids = _list_model_ids(prefix, base, 5, internal_only=False)  # 상태 표는 짧게(5초) · 허용된 외부(PC)도 봄 — 옛 동작 그대로
        reach = "응답" + ("" if not model else (" · 모델 있음" if model in ids else f" · 모델 없음(서버: {', '.join(ids[:3])})"))
    except Exception as e:
        reach = f"응답 없음({type(e).__name__})"
    return internal, model or "(모델 미설정)", reach


def services_main():
    print("| 항목 | 연결 |", "|---|---|", sep="\n")
    try:
        ok, why = detect_pg()
    except SystemExit as e:  # 접속 칸이 빔 — 표에는 채울 자리를 적음
        ok, why = False, str(e)
    print(f"| pgvector | {'✓ ' if ok else '✗ '}{why} |")
    print("\n| 모델 | 주소 구분 | 모델 | 상태 |", "|---|---|---|---|", sep="\n")
    for p, label in (("LLM", "LLM(답변·분해·그래프)"), ("VLM", "VLM(이미지 파싱)"), ("EMBED", "임베딩")):
        print(f"| {label} | " + " | ".join(model_status(p)) + " |")


def png_1x1():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


def payload(prefix, model):
    if prefix == "EMBED":
        return "/embeddings", {"model": model, "input": ["ping"]}
    content = "ping"
    if prefix == "VLM":
        url = "data:image/png;base64," + base64.b64encode(png_1x1()).decode()
        content = [{"type": "text", "text": "ping"}, {"type": "image_url", "image_url": {"url": url}}]
    return "/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 1}


_NOT_FOUND_RE = ("404", "not found", "model_not_found")
_NAME_HINTS = ("glm", "qwen", "vl", "embed")  # SI10 — 이름에 이것이 들어 있으면 역할별(LLM·VLM·EMBED) 후보로 추정


def model_not_found(why):
    w = (why or "").lower()
    return any(k in w for k in _NOT_FOUND_RE)


def _list_model_ids(prefix, base, timeout=None, internal_only=True):
    """그 서버 /v1/models의 모델 id 목록(리다이렉트 가드 경유, internal_only면 내부망 가드도 — 키는 헤더로만, 출력 안 함). 시간 상한 기본 PING_TIMEOUT."""
    if internal_only:
        guard.require_internal(base, prefix)
    req = urllib.request.Request(base.rstrip("/") + "/models")
    key = reveal(by_env(f"{prefix}_API_KEY"))
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with guard.urlopen(req, timeout or cfg().models.transport.ping_timeout, prefix) as r:
        return [m.get("id") for m in json.load(r).get("data", []) if m.get("id")]


def candidates(prefix, base):
    """FAIL이 '모델 없음'일 때 그 서버의 /v1/models에서 이름 힌트가 든 후보 — [(id, 일치 힌트)] (내부망 가드 경유, 키 출력 없음)."""
    try:
        ids = _list_model_ids(prefix, base)
    except Exception:
        return []
    out = []
    for i in ids:
        hits = [h for h in _NAME_HINTS if h in i.lower()]
        if hits:
            out.append((i, "·".join(hits)))
    return out


def ping(prefix):
    base, model = by_env(f"{prefix}_BASE_URL"), by_env(f"{prefix}_MODEL")
    if not base:
        return None
    if prefix in ("LLM", "VLM"):  # common.ai.llm.complete() 경유(가드·재시도 공용) — EMBED은 따로
        try:
            _, body = payload(prefix, model)
            t = time.perf_counter()
            A.complete(prefix.lower(), body["messages"], max_tokens=1, timeout=cfg().models.transport.ping_timeout)
            return True, int((time.perf_counter() - t) * 1000), model, ""
        except Exception as e:
            return False, 0, model or "", f"{type(e).__name__}: {str(e)[:120]}"
    try:
        guard.require_internal(base, prefix)
        path, body = payload(prefix, model)
        req = urllib.request.Request(base.rstrip("/") + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        key = reveal(by_env(f"{prefix}_API_KEY"))
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        t = time.perf_counter()
        with guard.urlopen(req, cfg().models.transport.ping_timeout, prefix) as r:
            d = json.load(r)
        ms = int((time.perf_counter() - t) * 1000)
        extra = ""
        if prefix == "EMBED":
            extra = f"dim {len(d['data'][0]['embedding'])}"  # 기대값 비교 없음(op-08 — 적재·검색은 받은 벡터 길이를 씀)
        return True, ms, d.get("model", model), extra
    except Exception as e:  # 오류 본문에 키가 섞일 수 있어 유형·짧은 메시지만
        return False, 0, model or "", f"{type(e).__name__}: {str(e)[:120]}"


def ping_main():
    fail = 0
    print("| 접두어 | 결과 | ms | 응답 모델 | 비고 |", "|---|---|---|---|---|", sep="\n")
    not_found = []
    for p in ("LLM", "VLM", "EMBED"):
        r = ping(p)
        if r is None:
            print(f"| {p} | 미설정 | | | |")
            continue
        ok, ms, m, extra = r
        fail += not ok
        print(f"| {p} | {'OK' if ok else 'FAIL'} | {ms} | {m} | {extra} |")
        if not ok and model_not_found(extra):
            not_found.append(p)
    for p in not_found:  # SI10 — 모델 없음(404 등)이면 그 서버에서 연결 가능한 후보를 재탐색
        base = by_env(f"{p}_BASE_URL")
        cands = candidates(p, base)
        print(f"\n{p}: 모델 없음 — {base}의 /v1/models 후보(이름 힌트 일치, 키는 출력 안 함):")
        if cands:
            print("| 모델 id | 일치 힌트 |", "|---|---|", sep="\n")
            for i, hits in cands:
                print(f"| {i} | {hits} |")
        else:
            print("(후보 없음 — /v1/models 응답 확인 또는 내부망 가드 거부)")
    return 1 if fail else 0


CMDS = {"env": env_main, "services": services_main, "ping": ping_main}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "services"
    if cmd not in CMDS or argv[1:]:
        raise SystemExit(f"사용: python -m common.check.checker [{'|'.join(CMDS)}] — 인자는 명령 하나만(기본 services)")
    if cmd != "env":
        return CMDS[cmd]() or 0
    from common.core.runlog import session

    with session("check_env"):
        req_bad = env_main()
    return (
        2 if req_bad == 2 and req_bad is not True else 1 if req_bad else 0
    )  # 2 = 잘못된 python(SI29) · requirements 차이만 종료 코드에(SI28)


if __name__ == "__main__":
    utf8_stdout()
    sys.exit(main())
