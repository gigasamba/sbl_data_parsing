#!/usr/bin/env python3
"""문서 폴더 × 엔진 일괄 파싱 → output/parse/<engine>/<문서>.json + output/parse/runs.jsonl(시간·오류).

사용: python -m pipeline.transform.parse.parse_engines [--src <원본 문서 폴더>] [--out output/parse] [--engines pdfplumber,pymupdf] [--limit N]
엔진 버전·캐시 열쇠(engine_version·engine_code_fp·p0_key)·중간 캐시 지우기(purge_caches)·형식 키(doc_types)도 여기.
자식(문서 1건 × 엔진 1개): python -m pipeline.transform.parse.parse_engines --one --engine <이름> [--profile tuned] [--fields baseline] <문서> <out.json>
엔진 목록: python -m pipeline.transform.parse.parse_engines --one --list
  --src 생략 시 DOC_DIR 필수(없으면 SystemExit) — common.core.paths.doc_dir.
  제한 시간: 문서×엔진 1건 = 쪽 수 × 쪽당 초 — 글자 엔진 text_page_sec(PARSE_TEXT_PAGE_SEC, 기본 10) ·
    VLM 엔진은 VLM 호출 1건 제한 common.models.vlm.timeout(기본 180) + 엔진의 첫 문서는 warmup_sec 하한 + 별도 프로세스 시작 여유 isolate_overhead.
    넘으면 같은 실행에서 제한을 두 배로 한 번 더, 그래도 넘으면 실패로 기록.
  문서마다 그 형식의 엔진(stack.json)을 **동시에**(엔진마다 별도 자식 프로세스 `--one` — 세그폴트가 전체를
    멈추지 않음). --workers N: 문서 N개를 동시에. --procs N: 문서를 N조각으로 나눠 프로세스 N개가 동시에(스레드는 코어 ÷ N).
  OCR 엔진(OCR_ENGINES — rapidocr_ko)은 파싱 엔진으로 돌지 않는다 — 이미지·스캔 문서는 VLM 엔진만.
    글자 PDF 안의 스캔 쪽은 여기서 OCR 엔진을 더하지 않고 대표 결과(doc_represent)의 쪽 VLM이 그 쪽만 채운다.
  진행 현황: 콘솔 큐 줄만.
  엔진 범위는 stack 하나: 문서마다 형식 키
    (.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록만 돈다. --engines는 그 안에서 더 좁힐 뿐(비교 실험은
    stack json을 고쳐서). stack.json에 그 키가 없으면 핵심 엔진 합집합으로 대체(누락 방지)+형식별 1회 로그.
  앞 실행 결과를 다시 쓰지 않는다(실행마다 새 작업 폴더): 요청한 문서×엔진은 늘 돈다. runs.jsonl은 이번 실행의
    시간·오류 기록(보고 도구가 읽음). 같은 내용 문서는 받은 뒤 중복 제외(candidate_ready)가 이미 하나만 남긴다.
  미설치·미설정(환경) 엔진은 이번 실행(프로세스) 안에서 처음 실패한 문서 뒤로 같은 엔진은 나머지 문서를 시도하지 않고
    runs.jsonl에 '건너뜀(환경 — 첫 실패 <문서>)'로 기록(문서마다 프로세스 기동·import 비용 반복 방지). 시간 초과·그 밖의 예외는 문서 탓일 수 있어 그대로 매 문서 시도.
    --procs 자식 프로세스끼리는 공유하지 않음(프로세스마다 다시 한 번 확인).
"""

import argparse
import functools
import importlib.metadata
import json
import os
import sys
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import settings as C
from common.core import span as SP  # 문서×엔진 span(run_id 없으면 아무 일도 안 함)
from common.core.console import utf8_stdout
from common.core.paths import (  # 폴더 재편 뒤 이 두 상수만 바뀌면 됨
    APP_ROOT,
    DEPLOY_ROOT,
    PARSING_ROOT,
    RES_ROOT,
    atomic_write_text,
    doc_dir,
)
from pipeline import config as pc
from pipeline.shared import runtrace
from pipeline.shared.env_error import is_env_error
from pipeline.shared.pdf_kind import doc_pages, pdf_kind
from pipeline.transform.parse.engines import registry

# engine → importlib.metadata 패키지 이름("|"는 여러 후보) — src/tools/qa/eval_hard_parse.py의 PKG를 단일 인터프리터용으로
# 옮긴 사본(그쪽은 kreuzberg 등을 별도 venv(ALT_PY)에서 확인 — 그 교차 venv 조회는 이 계약 함수 범위 밖, 호출 쪽이 알아서).
ENGINE_PKG = {
    "html_stdlib": None,
    "pymupdf": "pymupdf",
    "kreuzberg": "kreuzberg",
    "rapidocr_ko": "rapidocr|rapidocr_onnxruntime|rapidocr-onnxruntime",
    "pptx": "python-pptx",
    "office": None,
    "mhtml": None,
}


@functools.cache
def engine_version(engine):
    """엔진 이름 → 설치된 패키지 버전(importlib.metadata). 매핑에 없으면 엔진 이름을 패키지 이름으로 시도. 못 찾으면 "unknown".
    프로세스마다 엔진당 한 번(fp-perf B5 — 실행 중 설치 버전은 안 바뀜)."""
    pkg = ENGINE_PKG.get(engine, engine)
    if not pkg:
        return "stdlib"
    for name in pkg.split("|"):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown"


# 정리 대상은 순수 캐시만(재생성 경로가 있는 것만). server-runbook.md 'C7. 파싱 결과
# 원본·그림 보관 위치' 표의 보관 결정을 그대로 따른다 — **raw/**(VLM 원본 응답 raw/vlm·엔진별 원본 raw/<엔진>@<버전>,
# C7: "남음")와 **_images**(그림 조각 PNG + index.jsonl, C7: "남음" — get_image가 읽는
# 정본 색인이라 파일만 지우면 참조가 깨짐)는 서버가 원본을 즉시 지워 재생성 경로가 없으므로 **정리 대상이 아니다**(안 지움).
# 정리 대상은 재판독 중간 캐시 3종뿐 — 전부 "없으면 다시 OCR·VLM 호출만 더 들 뿐"이라 영구 보관 결정이 없는 것들:
#   _reread_p3/_vlm_cache(지운 P3 재판독 캐시 — 서버에 남은 폴더를 정리하려고 둠) · _agent/_vlm_cache(판단 세션 재판독 VLM 캐시) · signals(page_signals 쪽 신호).
# 엔진 원문 P0(output/parse/<엔진>/<문서>.json, p0_key)·대표 결과(_rep)·판단 세션 결정 기록(_agent/decisions)도 당연히 안 지움.
PURGE_CACHE_DIRS = ("_reread_p3/_vlm_cache", "_agent/_vlm_cache", "signals")


def _contained_dirs(root):
    """root(이미 resolve됨) 밑에 안전하게 들어갈 수 있는 디렉터리만 — 각 하위 디렉터리를 resolve()해서 여전히
    root 밑인지 다시 확인하고서야 스택에 넣는다. os.walk(followlinks=False)만으론 부족하다
    (os.walk은 심볼릭 링크는 걸러도 **Windows junction/mount point는 걸러내지 못함**, `os.path.islink()`가
    junction엔 False를 줘서 followlinks=False가 무력화되는 걸 실측으로 확인). 깊이 섞인 순서로 반환(정렬은 호출자)."""
    found = [root]
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=True):
                    rp = Path(e.path).resolve()
                    if (rp == root or root in rp.parents) and rp not in found:  # root 밑만(심링크·junction) · 자기 참조 링크 무한 순회 방지
                        found.append(rp)
                        stack.append(rp)
            except OSError:
                pass
    return found


def _iter_files(root):
    """root(resolve됨) 아래 파일만 — _contained_dirs로 확인된 디렉터리에서만 파일을 모은다. 파일 자체가 심링크면
    건너뜀(그 심링크가 가리키는 밖의 파일을 안 지움)."""
    for d in _contained_dirs(root):
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False):
                    yield Path(e.path)
            except OSError:
                pass


def purge_caches(parse_dir, max_gb=None, dirs=PURGE_CACHE_DIRS, log=print):
    """parse_dir(보통 output/parse) 아래 PURGE_CACHE_DIRS(재판독 중간 캐시 3종 — raw/·_images는 server-runbook.md C7
    표의 '원본 삭제 뒤에도 남음' 결정 때문에 대상 아님) 합계 용량이 PARSE_CACHE_MAX_GB(env, 기본 **5GB**·0=끔)를 넘으면
    가장 오래 안 쓴 파일(mtime)부터 지워 상한 밑으로 — 배치 시작 1회만 부른다(파싱 중간에는 안 지움, 그 배치가 막 쓴
    캐시까지 지우면 같은 배치 안에서 재계산이 생긴다). 지우는 파일은 parse_dir 아래로 resolve 확인(경로 탈출 방지) +
    심볼릭 링크·Windows junction 디렉터리는 안 들어감(_contained_dirs·_iter_files) — dirs에 없는 폴더(raw·_images·
    엔진 원문·_rep·_agent/decisions)는 절대 건드리지 않는다.
    ponytail: 폴더별 상한 대신 세 폴더 합계 하나(단순) — 폴더별로 따로 상한을 걸 필요가 생기면 dirs를 쪼개 각각 호출."""
    max_gb = float(pc.cfg().extract.cache.parse_cache_max_gb) if max_gb is None else float(max_gb)
    if not max_gb:
        return {"skipped": "PARSE_CACHE_MAX_GB=0"}
    root = Path(parse_dir).resolve()
    roots = []
    for d in dirs:
        p = (root / d).resolve()
        if root == p or root not in p.parents:  # 경로 탈출 방지(dirs는 상수라 정상적으로는 안 일어남)
            continue
        if p.exists() and not p.is_symlink():  # 캐시 루트 자체가 심링크면 건너뜀(루트 바꿔치기 방지)
            roots.append(p)
    entries = []
    for r in roots:
        for f in _iter_files(r):
            try:
                entries.append((f.stat().st_mtime, f.stat().st_size, f))
            except OSError:
                pass
    total_bytes = sum(sz for _, sz, _ in entries)
    total_gb = total_bytes / (1024**3)
    if total_gb <= max_gb:
        return {"total_gb": round(total_gb, 3), "removed": 0, "removed_gb": 0.0}
    entries.sort(key=lambda e: e[0])  # 오래된 mtime부터
    removed, removed_bytes = 0, 0
    for _, size, f in entries:
        if (total_bytes - removed_bytes) / (1024**3) <= max_gb:
            break
        try:
            f.unlink()
            removed += 1
            removed_bytes += size
        except OSError:
            pass
    for r in roots:  # 비게 된 폴더 정리(_contained_dirs — 깊은 것부터, 심링크·junction 디렉터리는 안 들어가 그 안은 안 봄)
        for d in sorted(_contained_dirs(r), key=lambda p: -len(str(p))):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
        # r 자신은 위에서 이미 지웠을 수 있음(흔한 경우 — 내부 폴더 없음) → 그 위 조상(dirs 항목이 "a/b"처럼
        # 중간 폴더일 때, 예: _reread_p3/_vlm_cache를 지운 뒤 비어버린 _reread_p3)도 비었으면 마저 지움
        d = r.parent if not r.exists() else r
        while d != root:
            try:
                if not d.exists() or d.is_symlink() or any(d.iterdir()):
                    break
                d.rmdir()
            except OSError:
                break
            d = d.parent
    log(f"[cache-purge] {total_gb:.2f}GB > 상한 {max_gb:g}GB — 오래된 캐시 파일 {removed}개({removed_bytes / 1024**3:.2f}GB) 지움 ({root})")
    return {"total_gb": round(total_gb, 3), "removed": removed, "removed_gb": round(removed_bytes / 1024**3, 3)}


def doc_types(docs, out):
    """문서 → 타입(.pdf는 .pdf_text / .pdf_image — 쪽당 글자 레이어 20자 기준). 판정은 <out>/_types.json에 캐시(크기·수정 시각)."""
    cache_f = Path(out) / "_types.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    res, dirty = {}, False
    for d in docs:
        if d.suffix.lower() != ".pdf":
            res[d.name] = d.suffix.lower()
            continue
        st = d.stat()
        key = f"{d.name}|{st.st_size}|{int(st.st_mtime)}"
        if key not in cache:
            cache[key], dirty = "." + pdf_kind(d)[0], True
        res[d.name] = cache[key]
    if dirty:
        Path(out).mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return res


def redact(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림(백로그 X2 ⑤ — 로그·runs.jsonl에 본문 금지).
    구현은 span.redact_text 한 곳. 성능 기록(pipe_event.err)은 이 함수가 아니라 span.safe_err(allowlist)를 쓴다."""
    return SP.redact_text(s)


VLM_ENGINES = {"qwen_vlm"}
# OCR 엔진은 파싱 엔진으로 안 돌림. 엔진 코드는 남김(filter_and_rotate 회전 판정·figures가 씀)
OCR_ENGINES = {"rapidocr_ko"}


def page_timeout(eng, pages, first=False):
    """문서×엔진 1건 제한(초) = 쪽 수 × 쪽당 초(VLM 엔진 common.models.vlm.timeout · 그 밖 text_page_sec) · 엔진의 첫 문서는
    warmup_sec 하한(import·모델 적재) · 별도 프로세스 시작 여유 isolate_overhead를 더함. 시간 초과면 호출자가 두 배로 한 번 더."""
    x = pc.cfg().extract
    tmo = max(1, pages) * float(C.cfg().models.vlm.timeout if eng in VLM_ENGINES else x.text_page_sec)
    if first:
        tmo = max(tmo, float(x.warmup_sec))
    return round(tmo + float(x.isolate_overhead), 2)


IDLE_MARK = "[engine-scope] stack 목록 밖이라 안 돎"  # 명시 --engines 중 일부가 안 돎(알림 — 거의 매 실행)
NO_JOB_MARK = "[engine-scope] 돌 엔진 없음"  # 명시 --engines가 하나도 못 돎 — run_mcp_parsing이 이 줄로 스캔 PDF를 가름


def engines_for_doc(doc, stack_parse, types, logged_missing):
    """문서 하나에 돌릴 엔진 후보(이후 --engines want로 더 좁혀짐). doc은 Path.
    문서 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록으로 좁힌다.
    그 키가 stack.json에 없으면 그대로(핵심 엔진 합집합으로 대체, 누락 방지) + 형식별 1회만 로그.
    .pdf_text 안 스캔 쪽 때문에 .pdf_image 엔진을 합치지 않음(대표 결과의 쪽 VLM이 그 쪽만 채움) ·
    OCR 엔진은 돌리지 않음(형식 키가 구성에 없어 합집합으로 대체할 때도)."""
    suffix = doc.suffix
    cands = [e for e in registry.engines_for(suffix) if e not in OCR_ENGINES]
    key = types.get(doc.name, suffix.lower())
    stack_eng = stack_parse.get(key)
    if stack_eng is None:
        if key not in logged_missing:
            print(f"[engine-scope] stack.json에 '{key}' 형식 없음 — 핵심 엔진 합집합으로 대체", flush=True)
            logged_missing.add(key)
        return cands
    return [e for e in cands if e in stack_eng]


def _drop_uninstalled(want):
    """`--engines`를 명시하면
    registry.select()는 설치 여부를 안 거른다(의도적 — ImportError로 바로 알려줌, registry.py select() 설명).
    배치 실행에서는 문서마다·--isolate 서브프로세스마다 ImportError를 반복해 겪는 대신,
    이번 실행 시작 시 한 번만 설치·등록 여부를 확인해 빼고 로그 1줄로 알린다(env_failed는 '처음 실패 뒤'
    문서 단위 — 이 함수는 그 전에 시도 자체를 0으로 줄인다). 등록 안 된 이름(예: 스택 후보 목록에
    남은 archive 이동 엔진)도 여기서 같이 거름 — registry.installed()는 등록된 이름만 받는다."""
    known = registry.engines()
    bad = sorted(e for e in want if e not in known or not registry.installed(e))
    if bad:
        print(f"[engine-check] 설치·등록 안 됨 — 이번 실행에서 건너뜀(시작 시 1회 확인): {', '.join(bad)}", flush=True)
    return want - set(bad)


class RunLog:
    """runs.jsonl 덧붙이기 — --procs 자식 프로세스 여러 개가 같은 파일에 쓰므로 한 줄씩 프로세스 간 잠금(runs.jsonl.lock)으로.
    잠금 없이 덧붙이면 줄이 섞여 JSON이 깨지고 run-stack이 중단됐다(개발 PC --procs 2, 백로그 E11)."""

    def __init__(self, path):
        self.path, self._lf = Path(path), open(str(path) + ".lock", "a+b")

    def _lock(self, on):
        if os.name == "nt":
            import msvcrt

            self._lf.seek(0)
            msvcrt.locking(self._lf.fileno(), msvcrt.LK_LOCK if on else msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._lf, fcntl.LOCK_EX if on else fcntl.LOCK_UN)

    def write(self, s):
        self._lock(True)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(s)
        finally:
            self._lock(False)

    def flush(self):
        pass


def vlm_doc_concurrency(a, lim):
    """엔진 자식의 문서당 VLM 동시 수(파싱 입구 pipeline.cli parse가 이 모듈을 띄우기 전에 부름 — a = parse 인자, lim = --docs-from 인자) — common.models.vlm.concurrency를 동시 문서 수(= min(문서 수, 조각 × --workers))로
    max_concurrency를 나눈 몫까지 줄인다(문서 1건 실행이면 max 그대로)."""
    from common.core import resources as RS

    src = Path(a.src)
    docs = (
        [n for n in Path(lim[1]).read_text(encoding="utf-8").splitlines() if n.strip()]
        if lim
        else [f for f in src.iterdir() if f.is_file()]
        if src.is_dir()
        else []
    )
    at_once = min(max(1, len(docs)), RS.resolve_procs(a.procs) * max(1, int(a.workers)))
    return RS.vlm_page_concurrency(at_once, C.cfg().models.vlm.concurrency)


def _default_procs():
    """--procs 기본 — runtime.pipe_procs: auto → "auto", 없음·빈 값 → "1", 숫자는 그 글자."""
    procs = C.cfg().runtime.pipe_procs
    return C.render(procs) if procs is not None else "1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src", default=None, help="원본 문서 폴더(기본 DOC_DIR env — --help·import 때는 안 풀어야 하므로 여기서는 default=None)"
    )
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "parse"))
    ap.add_argument(
        "--engines",
        default="",
        help="비우면 핵심 16종(registry.CORE, 10-30 docling·unstructured_auto 지움 — pl-31 · 사용자 10-07: paddleocr·docling_ocr 제외 · openviking_import·cognee_import는 SI33로 어댑터 자체 삭제) · all = 전부 · a,b = 그것만",
    )
    ap.add_argument("--profile", default="default", choices=["default", "tuned"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--docs-from", default="", help="이 목록(파일 이름 한 줄씩)에 있는 문서만 — 파싱 모듈의 밤당 상한(PARSE_MAX_NEW)이 씀")
    ap.add_argument("--isolate", action="store_true", help="(옛 호환 — 이제 늘 문서×엔진마다 별도 프로세스)")
    ap.add_argument("--workers", type=int, default=1, help="동시에 처리할 문서 수(문서 안 엔진들은 늘 동시에)")
    ap.add_argument(
        "--procs",
        default=_default_procs(),
        help="문서를 N조각으로 나눠 프로세스 N개로 동시에 · auto = CPU·메모리(cgroup) 기준(common/resources.py)",
    )
    ap.add_argument("--shard", default="", help="i/k — 문서 목록의 i번째 조각만(--procs가 씀)")
    ap.add_argument(
        "--stack",
        default=None,
        help="엔진 구성 파일(PC 실험·시험용 — 비우면 설정 common.paths.stack_file · pl-03 represent·gold_bundle과 같음)",
    )
    a = ap.parse_args()
    from common.core import resources
    from common.core import resources as presources

    a.procs = 1 if a.shard else presources.resolve_procs(a.procs)  # --shard = run_procs가 띄운 하위 → 다시 나누지 않음
    # 실제 동시 수로 CPU를 나눔(thread_share). 조각은 이 값을 setdefault로 물려받음. rapidocr 스레드도 OMP_NUM_THREADS를 따름.
    if a.src is None:
        a.src = str(doc_dir())
    src, out = Path(a.src), Path(a.out)
    if not a.shard:  # 배치 시작 1회(--shard로 포크된 자식은 건너뜀), p0_key·_rep·결정 기록은 안 지움
        purge_caches(out)
    # 평면 · filter_and_rotate 기록 제외 · 처리 엔진 없는 확장자는 거르기(filter_and_rotate)가 이미 뺌 — 남아도 엔진 후보가 없어 작업 0건
    docs = sorted(p for p in src.iterdir() if p.is_file() and p.name not in (".gitkeep", "rotation.csv"))
    pc.checked("MAX_FILE_MB")  # 파일 크기 상한 — 형식 틀리면 실패(조용히 '제한 없음'이 되지 않게)
    max_mb = float(pc.cfg().extract.max_file_mb)  # 기본 0 · 큰 파일(수백 MB 스캔 PDF 등)은 메모리·시간 폭주 원인 — 0이면 제한 없음
    if max_mb:
        big = [p for p in docs if p.stat().st_size > max_mb * 1024 * 1024]
        if big:
            print(f"건너뜀(MAX_FILE_MB {max_mb:g} 초과) {len(big)}개: " + ", ".join(p.name for p in big[:10]), flush=True)
            big_set = set(big)
            docs = [p for p in docs if p not in big_set]
    docs = docs[: a.limit] if a.limit else docs
    if a.docs_from:
        names = set(Path(a.docs_from).read_text(encoding="utf-8").splitlines())
        docs = [d for d in docs if d.name in names]
    if a.shard:
        i, k = map(int, a.shard.split("/"))
        docs = [d for d in docs if int(_sha(d), 16) % k == i]  # 내용 sha로 나눔(조각 사이 겹침 없음)
    want = registry.select(a.engines)  # 비우면 핵심 엔진(registry.CORE) · all이면 전부
    want_before_drop = want
    want = _drop_uninstalled(
        want
    )  # L11 — 미설치·미등록 엔진은 실행 시작 시 1회만 확인해 빼고 로그 1줄(문서마다 다시 시도 않음, select()가 안 거르는 명시 --engines 경로도 포함)
    if want_before_drop and not want:
        # want가 빈 집합이면 아래 engines_for_doc·run_procs의 `if want and eng not in want: continue`가
        # "제한 없음"(want가 기본 그대로 비어 있을 때 쓰는 신호)으로 잘못 읽어 형식별 등록 엔진 전부를 돈다
        # (--procs 자식이 엔진 하나만 받았는데 그게 전부 걸러지면 생기는 경우, L11 회귀 발견) — 할 일이 없으면
        # 여기서 바로 끝낸다(0건 종료, 엔진 전부 돌리는 쪽으로 새지 않음).
        print("[engine-check] 요청한 엔진이 전부 설치·등록 안 됨 — 이번 실행 종료(0건)", flush=True)
        return
    if a.procs > 1 and len(docs) > 1:  # 문서 조각 — 문서 1건이면 이 프로세스에서 바로
        return run_procs(a, docs)
    unverified = {e for e, (_, m) in registry.engines().items() if e in m.UNVERIFIED}
    run_id = os.environ.get("PARSE_RUN_ID") or None  # env 남김 — 내부 신호 · pipeline.cli가 넘기는 이번 실행 id(없으면 run_id 칸 없이 기록)
    # 앞 실행의 runs.jsonl로 건너뛰거나 결과를 복사하지 않는다(실행마다 새 작업 폴더 — runs.jsonl은 이번 실행 기록만).
    jobs = []
    with SP.span("extract.plan", docs=len(docs)) as plan_sp:  # 계획 단계 시간과 결정 요약을 span 1행으로(문서×엔진마다 행을 만들지 않음)
        # 엔진 범위는 stack 하나: 문서 형식별 stack.json 목록만
        stack = (
            json.loads(Path(a.stack).read_text(encoding="utf-8")) if a.stack else pc.stack()
        )  # 엔진 구성 파일(서버·PC 같음) · --stack은 시험·실험용 파일
        stack_parse = stack.get("parse") or {}
        # 동시 글자 엔진 자식 = 조각 × min(문서 workers × 문서당 엔진 수, 코어 ÷ 조각) — VLM 엔진(API 대기)은 이 상한 밖.
        # 문서당 엔진 수 = 구성에서 형식당 가장 많은 엔진 수
        per_doc = max((len(v) for v in stack_parse.values()), default=1)
        slots = min(max(1, a.workers) * per_doc, presources.text_slots(resources.cpus(), a.procs))
        thr = C.cfg().runtime.pipe_threads  # float, auto·빈 값 = None — "0"은 0이라 None일 때만 계산
        for k, v in presources.thread_env(
            int(thr) if thr is not None else presources.thread_share(resources.cpus(), a.procs, slots)
        ).items():
            os.environ.setdefault(k, v)  # env 남김 — 라이브러리(5-3 H) · 단일 프로세스도 수치 라이브러리 스레드를 컨테이너 CPU 한도에 맞춤
        types = doc_types(docs, out) if stack_parse else {}
        logged_missing = set()
        for doc in docs:
            sha = _sha(doc)
            cand = engines_for_doc(doc, stack_parse, types, logged_missing)
            for eng in cand:
                if want and eng not in want:
                    continue
                dst = out / eng / (doc.name + ".json")
                dst.parent.mkdir(parents=True, exist_ok=True)
                jobs.append((doc, eng, dst, sha))
        plan_sp.add(jobs=len(jobs))
    # 범위는 stack 하나: 명시 --engines 중 stack 형식별 목록 밖(또는 이 문서들 형식에 없음)은 안 돎 — 조용히 빠지지 않게 1줄
    idle = sorted(set(want or ()) - {e for _, e, _, _ in jobs})
    if idle:
        print(f"{IDLE_MARK}(비교하려면 stack json을 고침): {', '.join(idle)}", flush=True)
    if want and not jobs:
        print(NO_JOB_MARK, flush=True)
    out.mkdir(parents=True, exist_ok=True)
    log, lock = RunLog(out / "runs.jsonl"), threading.Lock()
    print(f"이번 실행 {len(jobs)}건", flush=True)

    done, tally = [0], Counter()

    warmed = set()
    text_sem = threading.BoundedSemaphore(slots)  # 글자(CPU) 엔진 자식 동시 수 상한(VLM 엔진은 --workers만큼)
    env_failed = {}  # 엔진 → 첫 env 실패 문서 이름. 이 실행(프로세스) 안에서만 기억(--procs 자식마다 별도 프로세스라 공유 안 됨 —
    # ponytail: 프로세스 간 공유가 필요해지면(--procs가 같은 엔진을 여러 조각으로 쪼갤 때) 파일 기반 공유로 올림)

    def run_job(job):
        """문서×엔진 1건 = extract.parse span 1행(대기·재시도·자식 자원 사용은 metrics/열로)."""
        doc, eng = job[0], job[1]
        with SP.span(
            "extract.parse", doc_id=doc.name, engine=eng, ext=doc.suffix.lower(), file_bytes=doc.stat().st_size, total=len(jobs)
        ) as sp:
            run_job_body(job, sp)

    def run_job_body(job, sp):
        doc, eng, dst, sha = job
        with lock:
            first_fail = env_failed.get(eng)
        if first_fail is not None:  # 이 엔진은 이번 실행에서 이미 env 실패 확인됨: 프로세스·import 비용 없이 바로 건너뜀
            rec = _with_run_id(
                {
                    "doc": doc.name,
                    "engine": eng,
                    "sec": 0,
                    "error": f"건너뜀(환경 — 첫 실패 {first_fail})",
                    "skipped_env": True,
                    "sha": sha,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "chars": 0,
                },
                run_id,
            )
            sp.result("skip", "env", SP.safe(rec["error"]))
            with lock:
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log.flush()
                done[0] += 1
                sp.set(seq=done[0])
                tally["환경"] += 1
                print(f"SKIP {eng:18s} {rec['sec']:>7}s  {doc.name}  건너뜀(환경 — 첫 실패 {first_fail})", flush=True)
                print(
                    f"  [큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] " + " · ".join(f"{k} {v}" for k, v in tally.items()),
                    flush=True,
                )
            return
        t0, err = time.perf_counter(), None
        unset = registry.missing_env(eng)
        with lock:
            first = eng not in warmed
            warmed.add(eng)
        ever = engine_version(eng)
        pkey = p0_key(eng, sha, ever)  # P0 열쇠(결과 출처 기록 — provenance·runs.jsonl)
        prov = {"engine": eng, "engine_version": ever, "p0_key": pkey, "params": {"profile": a.profile}}  # 자식이 결과에 넣어 씀(C4)
        pages = doc_pages(doc) or 1
        tmo = page_timeout(eng, pages, first)
        sp.add(pages=pages, limit_s=tmo, first_of_engine=first)
        if eng in VLM_ENGINES:
            err, tmo = _run_with_retry(eng, doc, dst, a.profile, tmo, unset, None, prov)
        else:
            t_slot = time.monotonic()
            with text_sem:
                sp.add(wait_slot_ms=int((time.monotonic() - t_slot) * 1000))  # 글자 엔진 동시 수 상한(text_sem) 대기 — 작업 시간과 분리
                err, tmo = _run_with_retry(eng, doc, dst, a.profile, tmo, unset, None, prov)
        if err:
            sp.result(
                "timeout" if "Timeout" in err else "fail", "timeout" if "Timeout" in err else "env" if is_env_error(err) else "doc", err
            )
        if err and dst.exists():
            # 실패·시간 초과면 그 자리의 결과 파일은 이번 내용의 결과가 아님(내용이 바뀐 문서의 이전 결과 등) — 지움.
            dst.unlink(missing_ok=True)
        if err and is_env_error(err):  # 미설치·미설정(env) 실패만 기억(시간 초과·그 밖의 예외는 문서 탓일 수 있어 제외)
            with lock:
                env_failed.setdefault(eng, doc.name)
        rec = _with_run_id(
            {
                "doc": doc.name,
                "engine": eng,
                "sec": round(time.perf_counter() - t0, 2),
                "error": err,
                "unverified": eng in unverified,
                "timeout": tmo,
                "limit": tmo,
                "sha": sha,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "chars": _chars(dst) if not err else 0,
                "engine_version": ever,
                "p0_key": pkey,
                "p0_code": engine_code_fp(eng),
            },
            run_id,
        )
        with lock:
            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.flush()
            done[0] += 1
            sp.set(seq=done[0])
            tally["시간 초과" if err and "Timeout" in err else "환경" if err and is_env_error(err) else "실패" if err else "성공"] += 1
            tag = "FAIL " if err else "ok   "
            print(tag + f"{eng:18s} {rec['sec']:>7}s  {doc.name}" + (f"  {err[:120]}" if err else ""), flush=True)
            print(
                f"  [큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] " + " · ".join(f"{k} {v}" for k, v in tally.items()),
                flush=True,
            )  # 큐 진행(콘솔)

    with runtrace.Progress(total=len(jobs), done=lambda: done[0], unit="doc_engine"):  # 60초마다 run.progress
        _run_pipeline(jobs, run_job, a.workers)


def run_procs(a, docs):
    """문서를 N조각(내용 sha 기준)으로 나눠 프로세스 N개가 동시에(엔진 묶음이 아니라 문서 조각).
    조각마다 문서 안 엔진들은 동시에·엔진마다 별도 프로세스(run_job)라 조각 프로세스 자체는 세그폴트로 죽지 않는다."""
    from common.core import resources

    k = max(1, min(a.procs, len(docs)))
    thr = C.cfg().runtime.pipe_threads  # auto·빈 값 = None, "0"은 0 — None일 때만 계산
    threads = str(int(thr) if thr is not None else max(1, resources.cpus() // k))  # cgroup 한도 기준(os.cpu_count()는 호스트 코어)
    # env 남김 — 하위 프로세스·엔진에 넘김(엔진 파일은 env를 직접 읽음)
    env = dict(
        os.environ,
        OMP_NUM_THREADS=threads,
        MKL_NUM_THREADS=threads,
        OPENBLAS_NUM_THREADS=threads,
        NUMEXPR_NUM_THREADS=threads,
        TORCH_NUM_THREADS=threads,
    )
    base, skip_next = [sys.executable, "-m", "pipeline.transform.parse.parse_engines"], False
    for x in sys.argv[1:]:  # --procs·--shard만 빼고 같은 인자
        if skip_next:
            skip_next = False
            continue
        if x in ("--procs", "--shard"):
            skip_next = True
            continue
        if not x.startswith(("--procs=", "--shard=")):
            base.append(x)
    print(f"프로세스 {k}개(문서 조각) · 프로세스당 스레드 {threads} · 문서 {len(docs)}개", flush=True)

    def one(i):
        # 하위는 항상 --procs 1(PIPE_PROCS 설정으로 하위가 또 프로세스를 띄우는 연쇄 방지)
        with SP.span("extract.shard", seq=i, total=k) as sp:  # 조각 프로세스 1개(자식의 span이 이 밑에 붙음)
            rc = resources.gated_popen(base + ["--shard", f"{i}/{k}", "--procs", "1"], env=env).wait()
            sp.add(rc=rc)
            if rc != 0:
                sp.result("fail", None, SP.safe(f"종료 코드 {rc}"))
                print(f"조각 {i}/{k} 비정상 종료({rc}) — 이 조각은 다시 돌려야 함(앞 실행 결과를 건너뛰지 않음 — pl-32)", flush=True)

    with ThreadPoolExecutor(max_workers=k) as ex:
        list(ex.map(SP.carry(one), range(k)))


def _run_pipeline(jobs, run_job, workers):
    """문서 workers개를 동시에, 한 문서의 엔진들도 모두 동시에(엔진마다 별도 프로세스 — run_job)."""
    by_doc = {}
    for job in jobs:
        by_doc.setdefault(job[0], []).append(job)
    run_job = SP.carry(run_job)  # 풀 스레드는 contextvars를 안 물려받으므로 run/span ID를 실어 보냄

    def run_doc(doc_jobs):
        if len(doc_jobs) == 1:
            return run_job(doc_jobs[0])
        with ThreadPoolExecutor(max_workers=len(doc_jobs)) as pool:
            list(pool.map(run_job, doc_jobs))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(SP.carry(run_doc), by_doc.values()))


def _run_with_retry(eng, doc, dst, profile, tmo, unset, env, prov=None):
    """문서×엔진 1건 — 시간 초과면 같은 실행에서 제한 두 배로 한 번 더, 그래도 넘으면 실패. 반환: (오류 글자 또는 None, 마지막 제한)."""
    for attempt in range(2):
        err = None
        sp = SP.current()
        if sp is not None:  # 몇 번째 시도인지(시간 초과로 다시 돌면 2)
            sp.set(attempt=attempt + 1)
        try:
            if unset:
                raise LookupError("환경변수 미설정: " + ", ".join(unset))
            _isolated(eng, doc, dst, profile, tmo, env=env, **({"prov": prov} if prov else {}))
        except Exception as ex:
            err = redact(f"{type(ex).__name__}: {str(ex)[:300]}")
            if isinstance(ex, ImportError):
                err += " (미설치)"
            elif not isinstance(ex, TimeoutError) and (not isinstance(ex, LookupError) or not unset):
                traceback.print_exc(limit=1)
        if attempt or not (err and "Timeout" in err):
            break
        tmo = round(tmo * 2, 2)
        SP.add_current(timeout_retries=1)
        print(f"RETRY {eng:18s} {doc.name}  시간 초과 — 제한 {tmo}초로 한 번 더", flush=True)
    return err, tmo


def _with_run_id(rec, run_id):
    """runs.jsonl 줄에 이번 실행 run_id(env PARSE_RUN_ID)를 달아 run_board가 이번 실행만 거를 수 있게.
    env 없으면 그대로(run_id 칸 없음 — run_board는 그때 지금처럼 마지막 기록 기준으로 폴백)."""
    return {**rec, "run_id": run_id} if run_id else rec


def _chars(dst):
    try:
        return len((json.loads(Path(dst).read_text(encoding="utf-8")).get("text") or "").strip())
    except (OSError, ValueError):
        return 0


def _sha(p):
    from common.core.contract import file_hash  # fp-perf C2 — 한 곳(같은 프로세스 안에서는 파일당 한 번 읽음)

    return file_hash(p)[:16]


@functools.cache  # 엔진 폴더 해시는 프로세스마다 엔진당 한 번(실행 중 코드는 안 바뀜)
def engine_code_fp(eng):
    """원문 파싱 결과를 정하는 코드 = 그 엔진 폴더(transform/parse/engines/<엔진>)만 — common·parse_engines(실행 관리)가 바뀌어도 결과는 같으므로 넣지 않음."""
    import hashlib

    h = hashlib.sha256()
    # 엔진 폴더 + 엔진 공용 도우미(engines/_common — 표·사실 추출)
    # 엔진 이름 ≠ 폴더 이름인 엔진이 있음(office → office_stdlib · rapidocr_ko → rapidocr …) — 등록부의 스택 폴더로
    stack = registry.engines().get(eng, (eng, None))[0]
    files = sorted(set((PARSING_ROOT / "engines" / stack).glob("**/*.py")) | set((PARSING_ROOT / "engines" / "_common").glob("**/*.py")))
    for p in files:
        h.update(("parse/" + p.relative_to(PARSING_ROOT).as_posix()).encode("utf-8"))
        h.update(p.read_bytes())
    if eng in VLM_ENGINES:  # VLM 엔진 결과는 공용 쪽 옮기기 코드·지시문(page_transcribe)에도 달림
        for p in [
            DEPLOY_ROOT / "pipeline" / "shared" / "vlmcall.py",
            *sorted((RES_ROOT / "prompts" / "common" / "page_transcribe").glob("*")),
        ]:
            h.update(p.relative_to(DEPLOY_ROOT).as_posix().encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def p0_key(eng, sha, ver=None):
    """P0 열쇠 하나로(결과 출처 기록) = (원본 sha · 엔진 설치 버전 · 엔진 코드 지문).
    비교와 기록이 같은 열쇠를 써야 한다."""
    import hashlib

    parts = json.dumps(
        {"eng": eng, "sha": sha, "ver": ver if ver is not None else engine_version(eng), "code": engine_code_fp(eng)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _isolated(eng, doc, dst, profile, tmo, py=None, env=None, prov=None):
    py = py or sys.executable
    retries = int(pc.cfg().extract.engine_retry)  # 기본 1 · 비정상 종료만 바로 다시(1회성 오류 — 단독 재실행은 성공)
    for attempt in range(retries + 1):
        try:
            return _isolated_once(eng, doc, dst, profile, tmo, py, env, prov)
        except RuntimeError:
            if attempt == retries:
                raise
            SP.add_current(proc_retries=1)


def _isolated_once(eng, doc, dst, profile, tmo, py, env=None, prov=None):
    import subprocess

    from common.core import resources as RS  # 우선순위 OS 분기 한 곳
    from common.core.paths import child_env

    low = bool(pc.cfg().extract.low_priority)  # 일괄 파싱은 낮은 우선순위(parse MCP 서비스는 끔 — 요청이 CPU를 먼저)
    # cwd 상속에 기대지 않고 child_env()의 PYTHONPATH(deploy/)로 이 모듈을 찾게 함
    pr = RS.gated_popen(
        [py, "-m", "pipeline.transform.parse.parse_engines", "--one", "--engine", eng, "--profile", profile]
        + (["--provenance", json.dumps(prov, ensure_ascii=False)] if prov else [])
        + [str(doc), str(dst)],
        env=env if env is not None else child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **RS.low_priority_kw(low),
    )
    RS.renice_low(pr.pid, low)
    try:
        out, err = pr.communicate(timeout=tmo)
    except subprocess.TimeoutExpired as tmo_err:
        pr.kill()
        pr.communicate()
        dst.unlink(missing_ok=True)  # 쓰다 만 결과를 남기지 않음
        raise TimeoutError(f"문서×엔진 시간 제한 초과({tmo}초)") from tmo_err
    sp = SP.current()  # 자식(--one)이 stdout 끝에 남긴 자원 사용(cpu·최대 메모리)을 이 문서×엔진 span에
    if sp is not None:
        sp.set(**SP.read_usage(out))
    if pr.returncode != 0:
        dst.unlink(missing_ok=True)
        last = (err.strip().splitlines() or [f"exit {pr.returncode}"])[-1]
        raise RuntimeError(
            f"하위 프로세스 종료 코드 {pr.returncode}"
            + (" (세그폴트 등 비정상 종료)" if pr.returncode < 0 or pr.returncode > 1 else "")
            + f": {last[:200]}"
        )


def one_main(argv):
    """자식 모드 `--one` — 문서 1건 × 엔진 1개를 이 프로세스에서 파싱해 out.json으로(부모 _isolated_once가 띄움)."""
    ap = argparse.ArgumentParser(prog="parse_engines --one")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--engine")
    ap.add_argument("--profile", default="default", choices=["default", "tuned"])
    ap.add_argument(
        "--fields",
        default="normalized",
        choices=["normalized", "baseline"],
        help="normalized=fields.py 정규화 · baseline=fact의 number/unit만",
    )
    ap.add_argument("--provenance", default=None, help="출처 블록 JSON(engine·engine_version·p0_key·params) — 결과에 넣어 한 번에 씀")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    a = ap.parse_args(argv)
    if a.list:
        for e, (s, m) in registry.engines().items():
            print(f"{e:18s} {s:15s} {' '.join(registry.formats(e))}" + ("  (미실측)" if e in m.UNVERIFIED else ""))
        return
    if not (a.engine and a.input and a.output):
        ap.error("--engine, 입력, 출력 필요")
    out = registry.run(a.engine, a.input, a.profile, a.fields)
    if a.provenance:
        stamp(out, json.loads(a.provenance))
    atomic_write_text(Path(a.output), json.dumps(out, ensure_ascii=False))  # 끊겨도 반쪽 파일 없음
    print(SP.usage_line(), flush=True)  # 이 프로세스의 cpu·최대 메모리 한 줄(부모의 extract.parse span이 읽음)


def stamp(out, prov):
    """엔진 결과에 provenance 블록 — engine·engine_version·p0_key·params·created_at(쓰기 전에 한 번에)."""
    out["provenance"] = {**prov, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return out


if __name__ == "__main__":
    utf8_stdout()
    if sys.argv[1:2] == ["--one"]:
        one_main(sys.argv[2:])
    else:
        with runtrace.run("run_all", sys.argv[1:]):  # 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
            main()
