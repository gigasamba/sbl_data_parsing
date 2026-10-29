#!/usr/bin/env python3
"""문서 폴더 × 엔진 일괄 파싱 → output/parse/<engine>/<문서>.json + output/parse/runs.jsonl(시간·오류).

사용: python modules/parse/run_all.py [--src <원본 문서 폴더>] [--out output/parse] [--engines pdfplumber,docling] [--limit N]
  --src 생략 시 DOC_DIR env 필수(없으면 SystemExit) — common/paths.py.doc_dir.
  --timeout 초: 문서×엔진 1건 제한(리눅스 SIGALRM, 기본 600). 넘으면 TimeoutError로 기록하고 다음으로.
    VLM 엔진(qwen_vlm·ocr_vlm·docling_vlm·marker_llm)은 쪽 수에 비례해 늘린다:
    max(--timeout, ⌈쪽 수 ÷ VLM_CONCURRENCY⌉ × VLM_TIMEOUT × (VLM_RETRY+1) + 60)
  처리 가능한 엔진이 없는 확장자는 건너뛰고 끝에 목록 출력.
  --isolate: 문서×엔진마다 별도 프로세스(parse/parse_one.py) — C 확장 세그폴트가 전체를 멈추지 않고, Windows에서도 --timeout 적용.
  --workers N: 문서×엔진 N건을 동시에(자동으로 --isolate). VLM처럼 API를 부르는 엔진에 — CPU 엔진은 1 권장.
  --need-vlm: VLM이 필요한 문서만 — 글자 레이어·원본 구조 파서 결과가 쪽당 100자 미만(이미지·스캔)인 문서. 2단계 실행용:
    ① python modules/parse/run_all.py --isolate                                   (CPU 엔진 전부)
    ② python modules/parse/run_all.py --engines qwen_vlm,ocr_vlm --need-vlm --workers 4   (VLM이 필요한 문서만 병렬 API)
  --procs N: **엔진 묶음 병렬(CPU)** — 엔진을 N묶음으로 나눠 프로세스 N개가 동시에(각 프로세스는 모델을 한 번만 올리고 문서를 차례로).
    스레드는 코어 ÷ N으로 나눔(OMP·MKL·OpenBLAS·torch). 한 묶음이 세그폴트로 죽으면 그 묶음만 --isolate로 이어서(끝낸 건은 건너뜀).
    메모리: 무거운 엔진(docling·marker·easyocr·paddle·unstructured hi_res)은 프로세스당 약 2~4 GB — 여유 메모리 ÷ 4 GB를 N 상한으로.
  --phase N(1·2·3): **제한 시간을 단계로** — 1 = VLM·LLM 없는 엔진만, 쪽당 0.1초 / 2 = phase 1 시간 초과분, 쪽당 1초 /
    3 = phase 2 시간 초과분(기본 --timeout) + VLM 엔진(쪽 수 비례·병렬). 넘으면 그 문서×엔진만 다음 phase로. 끝날 때마다
    output/parse/PHASE_REPORT.md(phase별 결과·대기 목록·연결 안 되는 엔진·기준점·사람 검토) 자동 갱신. --phase-sec로 0.1·1 조정.
  진행 현황: 1건 끝날 때마다 <out>/PROGRESS.md 갱신(형식별·엔진별 표·남은 시간) — 서버에서 `watch -n 30 cat output/parse/PROGRESS.md`.
  --engines 생략 시 형식별로 등록된 엔진 전부(tools/engines/<스택>/parser.py의 FORMATS).
  PARSE_ENGINE_SCOPE(환경변수, 기본 all) — stack: 문서마다 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)에
    해당하는 stack.json parse 목록으로만 좁힌다(생산 서버에서 PDF 1건에 OCR·VLM까지 9개+ 전부 도는 무거움 해소, 2026-10-07).
    stack.json에 그 키가 없으면 지금처럼 그대로(핵심 엔진 합집합, 누락 방지)+1회 로그. all(기본) = 지금 동작 그대로
    (--engines 명시 호출·compare-parse 등 실험 경로는 이 env를 안 건드리므로 영향 없음).
  다시 돌리지 않는 규칙(파일 내용 sha256 기준 — runs.jsonl에 기록):
    · 같은 내용이 그 엔진으로 이미 성공 → 건너뜀 (이름만 다른 같은 내용이면 결과를 복사해 씀, runs에 reused_from)
    · 원본 내용이 바뀜(sha 다름) → 다시 파싱
    · 실패·시간 초과 → 건너뜀(--retry-failed로 다시) · 미설치·미설정(환경) → 매번 다시 시도(환경을 고쳤을 수 있음)
    · --force: 전부 다시
  RB3② — 미설치·미설정(환경) 엔진은 이번 실행(프로세스) 안에서 처음 실패한 문서 뒤로 같은 엔진은 나머지 문서를 시도하지 않고
    runs.jsonl에 '건너뜀(환경 — 첫 실패 <문서>)'로 기록(문서마다 프로세스 기동·import 비용 반복 방지). 시간 초과·그 밖의 예외는 문서 탓일 수 있어 그대로 매 문서 시도.
    --procs 자식 프로세스끼리는 공유하지 않음(프로세스마다 다시 한 번 확인).
"""

import argparse
import functools
import json
import math
import os
import re
import signal
import sys
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import settings as C  # S7c: 설정 객체(common 칸 — VLM_*·PIPE_THREADS·RUN_MODE)
from common.core.console import utf8_stdout
from common.core.paths import (  # 폴더 재편 뒤 이 두 상수만 바뀌면 됨
    APP_ROOT,
    PARSING_ROOT,
    atomic_write_text,  # RV6, tmp+os.replace 공용(아래 _write_atomic이 감쌈)
    doc_dir,
)
from pipeline import config as pc  # S7c: 설정 객체(pipeline 칸)
from pipeline.extract.engines import registry
from pipeline.shared import artifacts as P0  # P0 열쇠(엔진 버전·코드 지문)로 재사용 판단(실험 저장소 계약과 같은 규칙)
from pipeline.shared.progress import (  # output/parse/PROGRESS.md 갱신 · 문서→형식 키(.pdf_text/.pdf_image, _types.json 캐시) · SI44③ 암호 오류 단서(한 곳)
    doc_types,
    is_encrypted_error,
    write_progress,
)

_QUOTED = re.compile(r"""(['"])((?:(?!\1).){30,})\1""", re.S)


def redact(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림(백로그 X2 ⑤ — 로그·runs.jsonl에 본문 금지).
    ponytail: 완벽하지 않음(인용부호 없는 echo는 못 잡음) — 더 필요하면 강화."""
    return _QUOTED.sub(lambda m: m.group(1) + "…[가림]…" + m.group(1), s or "")


VLM_ENGINES = {"qwen_vlm", "ocr_vlm", "docling_vlm", "marker_llm"}
OCR_ENGINES = {
    "paddleocr",
    "rapidocr",
    "rapidocr_ko",
    "easyocr",
    "tesseract",
    "docling_ocr",
    "unstructured_ocr",
    "kreuzberg_ocr",
    "paddleocr_vl",
    "ppstructure",
    "mineru",
    "marker",
}  # 이미지를 읽는 엔진(글자 레이어 판정에서 제외)
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}  # SI9 — 실문서(RUN_MODE=prod)에서 VLM 쪽당 시간 제한 면제 대상
# (스캔 PDF는 suffix가 아니라 _is_scan_pdf()로 같은 면제)


def n_pages(doc):
    if doc.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(doc)))
    except Exception:
        return 1


def job_timeout(eng, doc, base):
    if eng not in VLM_ENGINES:
        return base
    vlm = C.cfg().models.vlm  # S7c — 설정 객체(기본 4·180·1 — 빈 글자도 기본값, 옛 `int(get or 기본)`)
    conc = int(vlm.concurrency)
    per = int(vlm.timeout) * (int(vlm.retry) + 1)
    return max(base, math.ceil(n_pages(doc) / conc) * per + 60)


@functools.lru_cache(maxsize=4096)  # SI9 검토 — VLM 엔진마다 같은 PDF를 다시 열지 않게(실행 1회 안에서만, 경로 기준)
def _is_scan_pdf(doc):
    """SI9 — 스캔 PDF(AD12 vlm_page.is_scan 재사용, 전체 쪽 글자층 20자 미만 또는 이미지류)도 이미지 파일처럼
    VLM 쪽 수 비례 시간 상한 대상. 신호 계산 실패 시 안전하게 False(기존 동작 — 이미지 파일만 면제)."""
    try:
        from pipeline.transform.figures.vlm_page import is_scan

        return is_scan(doc)
    except Exception:
        return False


def _ocr_fallback_needed(doc_path):
    """AD12 page_signals(pipeline.transform.figures.vlm_page.scan_pages) 재사용 — .pdf_text로 판정된 문서 안에
    글자층이 거의 없는 쪽(스캔 쪽)이 있으면 True. pdf_kind(parse_qa.py)는 문서 평균(총 글자 < 20×쪽수)만 보므로
    글자 쪽이 많은 문서에 스캔 쪽 1장이 섞이면 .pdf_text로 판정돼 그 쪽만 안 읽힐 수 있다(독립 검토 BLOCK 1,
    2026-10-07) — 신호 계산 자체가 실패해도(이미지가 아님·못 엶 등) 안전하게 True(OCR 포함).
    AD47(2026-10-08, 재사용 확인만 — 코드 변경 없음) — scan_pages가 reason='hidden_overlap'(쪽 전체는 정상 글자인데
    값 하나만 그림과 겹친 숨은 글자)도 돌려주게 넓어지면서 그런 문서도 여기 걸려 .pdf_image 엔진(OCR)이 자동으로
    합쳐진다 — synth-mixedpdf textlayer_mismatch.pdf 확인."""
    try:
        from pipeline.transform.figures.vlm_page import scan_pages

        return bool(scan_pages(doc_path))
    except Exception:
        return True


def engines_for_doc(doc, scope, stack_parse, types, logged_missing):
    """문서 하나에 돌릴 엔진 후보(이후 --engines want로 더 좁혀짐) — PE1(2026-10-07, PARSE_ENGINE_SCOPE). doc은 Path.
    scope != "stack"(기본 all) → registry.engines_for(suffix) 그대로(지금 동작·실험 경로·명시 --engines 영향 없음).
    scope == "stack" → 문서 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록으로 좁힌다.
    그 키가 stack.json에 없으면 그대로(핵심 엔진 합집합으로 대체, 누락 방지) + 형식별 1회만 로그.
    안전판(독립 검토 BLOCK 1) — key가 ".pdf_text"인데 안에 스캔 쪽이 있으면(또는 신호 계산 실패) ".pdf_image" 엔진도 합친다."""
    suffix = doc.suffix
    cands = registry.engines_for(suffix)
    if scope != "stack":
        return cands
    key = types.get(doc.name, suffix.lower())
    stack_eng = stack_parse.get(key)
    if stack_eng is None:
        if key not in logged_missing:
            print(f"[engine-scope] stack.json에 '{key}' 형식 없음 — 핵심 엔진 합집합으로 대체", flush=True)
            logged_missing.add(key)
        return cands
    allow = set(stack_eng)
    if key == ".pdf_text":
        extra = stack_parse.get(".pdf_image") or []
        if extra and _ocr_fallback_needed(doc):
            print(
                f"[engine-scope] {doc.name} — .pdf_text 안 스캔 쪽 감지(또는 신호 계산 실패) → .pdf_image 엔진 합침: " + ",".join(extra),
                flush=True,
            )
            allow |= set(extra)
    return [e for e in cands if e in allow]


def _drop_uninstalled(want):
    """L11 — `--engines`를 명시(예: compare-parse의 `candidates` = stack.json 선정 + 후보 목록)하면
    registry.select()는 설치 여부를 안 거른다(의도적 — ImportError로 바로 알려줌, registry.py select() 설명).
    배치 실행(run_all)에서는 문서마다·--isolate 서브프로세스마다 ImportError를 반복해 겪는 대신,
    이번 실행 시작 시 한 번만 설치·등록 여부를 확인해 빼고 로그 1줄로 알린다(RB3②는 같은 걸 '처음 실패 뒤'
    문서 단위로 하던 것 — 이 함수는 그 전에, 시도 자체를 0으로 줄인다). 등록 안 된 이름(예: 스택 후보 목록에
    남은 archive 이동 엔진)도 여기서 같이 거름 — registry.installed()는 등록된 이름만 받는다."""
    known = registry.engines()
    bad = sorted(e for e in want if e not in known or not registry.installed(e))
    if bad:
        print(f"[engine-check] 설치·등록 안 됨 — 이번 실행에서 건너뜀(시작 시 1회 확인): {', '.join(bad)}", flush=True)
    return want - set(bad)


def need_vlm(docs, out):
    """글자 레이어·원본 구조 파서(OCR·VLM 아닌 엔진) 출력 중 가장 긴 것이 쪽당 100자 미만인 문서 = 이미지·스캔(결과 없음 포함)."""
    keep = []
    for doc in docs:
        best = 0
        for f in out.glob(f"*/{doc.name}.json"):
            if f.parent.name not in VLM_ENGINES | OCR_ENGINES and not f.parent.name.startswith("cognee_"):
                try:
                    best = max(best, len((json.loads(f.read_text(encoding="utf-8")).get("text") or "").strip()))
                except (OSError, ValueError):
                    pass
        if best < 100 * n_pages(doc):
            keep.append(doc)
    return keep


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


def _default_procs():
    """--procs 기본 — S7c1 설정 객체(옛 `os.environ.get("PIPE_PROCS") or "1"`: auto → "auto"(이미지 ENV), 없음·빈 값 → "1", 숫자는 그 글자 —
    칸이 'auto'를 글자로 기억, 코디네이터 답 ①b)."""
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
        help="비우면 핵심 19종(registry.CORE, 사용자 10-07: paddleocr·docling_ocr 제외 · openviking_import·cognee_import는 SI33로 어댑터 자체 삭제) · all = 전부 · a,b = 그것만",
    )
    ap.add_argument("--profile", default="default", choices=["default", "tuned"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--docs-from", default="", help="이 목록(파일 이름 한 줄씩)에 있는 문서만 — 파싱 모듈의 밤당 상한(PARSE_MAX_NEW)이 씀")
    ap.add_argument("--force", action="store_true", help="이미 한 것도 전부 다시")
    ap.add_argument("--retry-failed", action="store_true", help="실패·시간 초과했던 문서×엔진을 다시")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--isolate", action="store_true", help="문서×엔진마다 별도 프로세스(세그폴트·Windows 시간 제한 대비)")
    ap.add_argument("--workers", type=int, default=1, help="동시 실행 건수(>1이면 --isolate). API 엔진용")
    ap.add_argument(
        "--procs",
        default=_default_procs(),
        help="엔진 묶음 N개를 프로세스 N개로 동시에(CPU 병렬, 모델은 프로세스당 한 번) · auto = CPU·메모리(cgroup) 기준(common/resources.py)",
    )
    ap.add_argument("--shard", default="", help="i/k — 문서 목록의 i번째 조각만(--procs가 씀)")
    ap.add_argument("--phase", type=int, default=0, choices=[0, 1, 2, 3], help="단계 실행(1: 쪽당 0.1초 · 2: 1초 · 3: 나머지+VLM 쪽당 1초)")
    ap.add_argument(
        "--phase-sec",
        default=",".join(pc.cfg().extract.phase_sec),  # S7c — 설정 객체(기본 0.1,1,1 — 목록 칸을 글자로)
        help="phase 1·2·3의 쪽당 제한 초 — 3은 VLM 포함, 넘으면 그 문서×엔진은 넘김(사용자 10-02: 쪽당 1초 넘으면 넘기기)",
    )
    ap.add_argument(
        "--rescue", action="store_true", help="phase 3을 성공한 엔진이 하나도 없는 문서에만(매일 기본 — 스캔 계약서 등이 빠지지 않게)"
    )
    ap.add_argument("--truth", default="", help="(개발 PC) 정답 truth.json — phase 리포트 기준점")
    ap.add_argument(
        "--vlm-all",
        action="store_true",
        help="phase 3에서 VLM을 모든 PDF·이미지에(기본: 글자 레이어·원본 파서로 못 읽은 이미지·스캔 문서만)",
    )
    ap.add_argument("--need-vlm", action="store_true", help="비VLM 결과가 쪽당 100자 미만인 문서만")
    ap.add_argument(
        "--refresh-unknown",
        action="store_true",
        help="P0 열쇠(엔진 버전·코드 지문) 없는 옛 기록('버전 미상')도 다시 돈다(기본은 그대로 건너뜀 — 야간 배치 안전)",
    )
    a = ap.parse_args()
    from common.core import resources
    from pipeline.extract import resources as presources  # 10-14 — resolve_procs·thread_env는 common.core.resources에서 옮김(P만 씀)

    a.procs = 1 if a.shard else presources.resolve_procs(a.procs)  # --shard = run_procs가 띄운 하위 → 다시 나누지 않음
    # OC2(사용자 10-15) — 실제 동시 수(조각 procs × 조각마다 workers)로 CPU를 나눔(thread_share). 조각은 이 값을 setdefault로 물려받음.
    # OC1 rapidocr 스레드도 이 OMP_NUM_THREADS를 따름.
    thr = C.cfg().runtime.pipe_threads  # S7c — 설정 객체(float, auto·빈 값 = None — 옛 `int(get or 계산)`: "0"은 0이라 None일 때만 계산)
    for k, v in presources.thread_env(
        int(thr) if thr is not None else presources.thread_share(resources.cpus(), a.procs, a.workers)
    ).items():
        os.environ.setdefault(k, v)  # env 남김 — 라이브러리(5-3 H) · 단일 프로세스도 수치 라이브러리 스레드를 컨테이너 CPU 한도에 맞춤
    a.isolate = (
        a.isolate or a.workers > 1 or not hasattr(signal, "SIGALRM")
    )  # Windows는 제한 시간을 하위 프로세스로(시작 1초+ — 쪽당 0.1초는 Linux용)
    if a.src is None:
        a.src = str(doc_dir())
    src, out = Path(a.src), Path(a.out)
    if not a.shard:  # RV3 — 배치 시작 1회(--shard로 포크된 자식은 건너뜀), p0_key·_rep·결정 기록은 안 지움(common/artifacts.py)
        P0.purge_caches(out)
    files = sorted(p for p in src.iterdir() if p.is_file() and p.name not in (".gitkeep", "rotation.csv"))  # 평면 · prepare 기록 제외
    docs = [p for p in files if registry.engines_for(p.suffix)]
    skipped = Counter(p.suffix.lower() or "(없음)" for p in files if p not in docs)
    pc.checked("MAX_FILE_MB")  # 파일 크기 상한 — 형식 틀리면 옛 float()처럼 실패(조용히 '제한 없음'이 되지 않게 — S7c1 리뷰)
    max_mb = float(
        pc.cfg().extract.max_file_mb
    )  # S7c — 설정 객체(기본 0) · 큰 파일(수백 MB 스캔 PDF 등)은 메모리·시간 폭주 원인 — 0이면 제한 없음
    if max_mb:
        big = [p for p in docs if p.stat().st_size > max_mb * 1024 * 1024]
        if big:
            print(f"건너뜀(MAX_FILE_MB {max_mb:g} 초과) {len(big)}개: " + ", ".join(p.name for p in big[:10]), flush=True)
            docs = [p for p in docs if p not in big]
    docs = docs[: a.limit] if a.limit else docs
    if a.docs_from:
        names = set(Path(a.docs_from).read_text(encoding="utf-8").splitlines())
        docs = [d for d in docs if d.name in names]
    if a.shard:
        i, k = map(int, a.shard.split("/"))
        docs = [d for d in docs if int(_sha(d), 16) % k == i]  # 같은 내용 사본은 같은 조각 → 1번만 파싱 후 복사
    if a.rescue:  # 성공한 엔진이 하나도 없는 문서만(runs.jsonl 기준)
        # 엔진별 마지막 기록 + 지금 내용(sha)과 같은 기록만 성공으로 — 10-04 결함: 내용이 바뀐 스캔 10건의 옛 내용 성공 기록 때문에 구제 대상 0개
        last_rec = {}
        for ln in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines() if (out / "runs.jsonl").exists() else []:
            if ln.strip():
                r = json.loads(ln)
                last_rec[(r["doc"], r["engine"])] = r
        cur_sha = {d.name: _sha(d) for d in docs}
        ok_docs = {
            doc
            for (doc, _), r in last_rec.items()
            if not r.get("error")
            and r.get("chars", 1)  # 글자 0개 '성공'(스캔 PDF의 텍스트 엔진)은 성공 아님 — 10-02 실측 3건 누락
            and r.get("sha") in (None, cur_sha.get(doc))
        }
        docs = [d for d in docs if d.name not in ok_docs]
        print(f"[rescue] 성공 엔진 없는 문서 {len(docs)}개만 phase {a.phase}", flush=True)
    if a.need_vlm:
        docs = need_vlm(docs, out)
        print(f"VLM 필요 문서 {len(docs)}개: " + ", ".join(d.name for d in docs[:20]) + (" …" if len(docs) > 20 else ""))
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
    if a.procs > 1:
        return run_procs(a, docs, want)
    unverified = {e for e, (_, m) in registry.engines().items() if e in m.UNVERIFIED}
    run_id = (
        os.environ.get("PARSE_RUN_ID") or None
    )  # env 남김 — 내부 신호(5-3 H) · SI23 — pipeline.py가 넘기는 이번 실행 id(없으면 run_id 칸 없이 기록)
    last, ok_by_sha = {}, {}  # (문서, 엔진) → 마지막 기록 · (엔진, sha) → 성공한 문서 이름
    if (out / "runs.jsonl").exists():
        for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[(r["doc"], r["engine"])] = r
                if not r.get("error") and r.get("sha"):
                    ok_by_sha[(r["engine"], r["sha"])] = r["doc"]
    jobs, skip, reuse, planned, deferred = [], Counter(), [], {}, []
    vlm_docs = set(need_vlm(docs, out)) if a.phase == 3 and not a.vlm_all else set()
    scope = pc.cfg().extract.engine_scope  # S7c — 설정 객체(옛 `get(X, "all")`: 없음 → all, 빈 글자는 그대로)
    scope = scope if scope is not None else "all"  # PE1 — stack: 문서 형식별 stack.json 목록만(생산 기본), all(기본): 지금 동작 그대로
    stack_parse = {}
    if scope == "stack":
        try:
            stack = pc.stack_path()  # S8b — 진입점이 만든 판 사본(PC는 파일)
            stack_parse = (json.loads(stack.read_text(encoding="utf-8")).get("parse") or {}) if stack.exists() else {}
        except (OSError, ValueError):
            stack_parse = {}
    types = doc_types(docs, out) if stack_parse else {}
    logged_missing = set()
    skipped_log = src / "skipped.jsonl"  # SI44③ — prepare 단계와 같은 파일(누적)
    encrypted_detected = set()  # 이미 encrypted_detected로 기록된 문서(여러 phase 호출에 중복 기록 방지)
    if a.phase and a.phase >= 2 and skipped_log.exists():
        for ln in skipped_log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("reason") == "encrypted_detected":
                encrypted_detected.add(r.get("file"))
    for doc in docs:
        sha = _sha(doc)
        cand = engines_for_doc(doc, scope, stack_parse, types, logged_missing)
        if a.phase and a.phase >= 2 and not a.retry_failed:  # SI44③ — phase 1(이후) 실패 엔진 전부가 암호 오류면 다음 phase 재시도 안 함
            if doc.name not in encrypted_detected:
                tried = [r for r in (last.get((doc.name, e)) for e in cand) if r]
                if tried and all(r.get("error") and is_encrypted_error(r["error"]) for r in tried):
                    with skipped_log.open("a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(
                                {"file": doc.name, "reason": "encrypted_detected", "sha": sha, "time": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                    encrypted_detected.add(doc.name)
            if doc.name in encrypted_detected:
                skip["암호 감지(phase 1에서 전부 암호 오류 — encrypted_detected, 다음 phase 재시도 안 함)"] += len(cand)
                continue
        for eng in cand:
            if want and eng not in want:
                continue
            dst, prev = out / eng / (doc.name + ".json"), last.get((doc.name, eng))
            if a.phase in (1, 2) and eng in VLM_ENGINES:
                continue  # VLM·LLM은 phase 3에서(쪽당 1초 안에 끝나기 어려움)
            if a.phase == 3 and eng in VLM_ENGINES and not a.vlm_all and doc not in vlm_docs:
                skip["VLM 불필요(글자 레이어·원본 파서로 읽힘 — --vlm-all로 전부)"] += 1
                continue
            if (
                a.phase and prev and _is_timeout(prev) and (prev.get("phase") or 0) < a.phase
            ):  # 시간 초과 뒤 남은 결과 파일은 옛 내용 결과 — 있어도 다시(10-04)
                dst.parent.mkdir(parents=True, exist_ok=True)
                jobs.append((doc, eng, dst, _sha(doc)))  # 앞 phase에서 시간 초과 → 이번 phase에서 더 긴 제한으로
                continue
            if a.phase >= 2 and prev and prev.get("error") and _env_error(prev["error"]) and not a.retry_failed:
                skip["연결 안 되는 엔진(phase 1에서 확인 — PHASE_REPORT C)"] += 1
                continue
            if a.phase and prev and _is_timeout(prev) and not a.retry_failed:
                skip[
                    f"phase {prev.get('phase')} 시간 초과"
                    + ("(다음 phase 대상)" if (prev.get("phase") or 3) < 3 else "(마지막 phase — --timeout 늘려 --retry-failed)")
                ] += 1
                continue
            if not a.force:
                same = prev is not None and prev.get("sha") in (None, sha)  # sha 없는 옛 기록은 같은 내용으로 봄
                pst = p0_status(prev, eng, sha)[0] if same else None  # P0(엔진 버전·코드 지문) 비교 — 결과 없으면 None
                refresh_p0 = pst == "stale" or (pst == "unknown" and a.refresh_unknown)
                if dst.exists() and same and not (prev or {}).get("error") and not refresh_p0:
                    skip["이미 성공" if pst == "ok" else "이미 성공(버전 미상 — --refresh-unknown으로 다시)"] += 1
                    if pst == "ok" and not prev.get(
                        "p0_code"
                    ):  # 옛 형식 기록을 새 열쇠로 덧씀(다시 파싱 없음) — 다음 엔진 코드 변경부터 잡히게(독립 검토 10-04)
                        ver = P0.engine_version(eng)
                        reuse.append(
                            _with_run_id(
                                {
                                    **prev,
                                    "p0_key": p0_key(eng, sha, ver),
                                    "p0_code": engine_code_fp(eng),
                                    "engine_version": ver,
                                    "backfill": True,
                                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                },
                                run_id,
                            )
                        )
                    continue
                src_doc = ok_by_sha.get((eng, sha))
                src_rec = (
                    last.get((src_doc, eng)) if src_doc else None
                )  # GH1-03 — src_doc 결과가 이번 sha·엔진 버전(P0)과 아직 맞는지 same 분기와 같은 검사로 확인(안 맞으면 다시 파싱)
                if (
                    src_doc
                    and src_doc != doc.name
                    and src_rec
                    and src_rec.get("sha") == sha
                    and p0_status(src_rec, eng, sha)[0] == "ok"
                    and (out / eng / (src_doc + ".json")).exists()
                ):
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes((out / eng / (src_doc + ".json")).read_bytes())
                    last[(doc.name, eng)] = _with_run_id(
                        {"doc": doc.name, "engine": eng, "sec": 0, "error": None, "sha": sha, "reused_from": src_doc}, run_id
                    )
                    reuse.append(last[(doc.name, eng)])
                    skip["같은 내용 결과 복사"] += 1
                    continue
                if same and prev.get("error") and not _env_error(prev["error"]) and not a.retry_failed:
                    skip["이전 실패(--retry-failed로 다시)"] += 1
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if (eng, sha) in planned:  # 같은 실행 안의 같은 내용 사본 — 먼저 도는 것 결과를 끝나고 복사
                deferred.append((doc, eng, dst, sha, planned[(eng, sha)]))
                continue
            planned[(eng, sha)] = dst
            jobs.append((doc, eng, dst, sha))
    if deferred:
        skip["같은 내용 사본(1번만 파싱 후 복사)"] += len(deferred)
    if skip:
        print("건너뜀: " + " · ".join(f"{k} {v}" for k, v in skip.items()), flush=True)
    if a.phase:
        print(f"[phase {a.phase}] 대상 {len(jobs)}건 · 제한 쪽당 {_phase_sec(a)}초", flush=True)
    alarm = hasattr(signal, "SIGALRM") and not a.isolate
    if alarm:
        signal.signal(signal.SIGALRM, _timeout)
    out.mkdir(parents=True, exist_ok=True)
    log, lock = RunLog(out / "runs.jsonl"), threading.Lock()
    for r in reuse:
        log.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.flush()
    try:
        write_progress(src, out, a.engines)
    except Exception as ex:
        print(f"(PROGRESS.md 갱신 실패: {type(ex).__name__}: {ex})", flush=True)
    print(f"진행 현황: {out / 'PROGRESS.md'} (1건마다 갱신) · 이번 실행 {len(jobs)}건", flush=True)

    done, tally, last_w = [0], Counter(), [0.0]

    warmed = set()
    env_failed = {}  # RB3② — 엔진 → 첫 env 실패 문서 이름. 이 실행(프로세스) 안에서만 기억(--procs 자식마다 별도 프로세스라 공유 안 됨 —
    # ponytail: 프로세스 간 공유가 필요해지면(--procs가 같은 엔진을 여러 조각으로 쪼갤 때) 파일 기반 공유로 올림)

    def run_job(job):
        doc, eng, dst, sha = job
        with lock:
            first_fail = env_failed.get(eng)
        if first_fail is not None:  # RB3② — 이 엔진은 이번 실행에서 이미 env 실패 확인됨: 프로세스·import 비용 없이 바로 건너뜀
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
            with lock:
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log.flush()
                done[0] += 1
                tally["환경"] += 1
                print(f"SKIP {eng:18s} {rec['sec']:>7}s  {doc.name}  건너뜀(환경 — 첫 실패 {first_fail})", flush=True)
                print(
                    f"  [phase {a.phase or '-'} 큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] "
                    + " · ".join(f"{k} {v}" for k, v in tally.items()),
                    flush=True,
                )
                try:
                    if time.monotonic() - last_w[0] >= 2 or done[0] == len(jobs):
                        write_progress(src, out, a.engines)
                        last_w[0] = time.monotonic()
                except Exception as ex:
                    print(f"(PROGRESS.md 갱신 실패: {type(ex).__name__}: {ex})", flush=True)
            return
        t0, err = time.perf_counter(), None
        unset = registry.missing_env(eng)
        tmo = round(max(1, n_pages(doc)) * _phase_sec(a), 2) if a.phase in (1, 2, 3) else job_timeout(eng, doc, a.timeout)
        if (
            eng in VLM_ENGINES
            and C.cfg().store.run_mode == "prod"
            and (doc.suffix.lower() in IMG_EXT or (doc.suffix.lower() == ".pdf" and _is_scan_pdf(doc)))
        ):
            tmo = max(
                tmo, job_timeout(eng, doc, a.timeout)
            )  # SI9: 실문서(RUN_MODE=prod)에서 이미지 파일·스캔 PDF는 쪽당 1초 시험 제한 대신 VLM 쪽 수 비례 상한
        with lock:
            first = eng not in warmed
            warmed.add(eng)
        if first and a.phase in (1, 2, 3):
            # 엔진의 첫 문서는 라이브러리 import(pandas·모델 적재 등)가 들어 있어 쪽당 0.1~1초 제한이 import 도중에 끊으면
            # 반쯤 초기화된 모듈이 남아 같은 엔진의 나머지 문서가 전부 실패(Linux 컨테이너 실측 10-02, markitdown 136건) — 첫 문서만 넉넉히
            tmo = max(tmo, float(pc.cfg().extract.warmup_sec))  # S7c — 설정 객체(기본 60)
        if a.phase in (1, 2, 3) and a.isolate:
            # 별도 프로세스(VLM 동시 실행·Windows)는 시작·import 시간이 제한에 들어감 — 쪽당 제한은 '파싱 시간'에만(시작 여유 더함)
            # 10초: 컨테이너 실측(10-02) rapidocr·pymupdf4llm OCR 1쪽 스캔이 별도 프로세스에서 모델 적재 포함 4.3~6.2초(5초면 절반 실패)
            tmo += float(pc.cfg().extract.isolate_overhead)  # S7c — 설정 객체(기본 10)
        _FIRED[0] = False
        try:
            if unset:
                raise LookupError("환경변수 미설정: " + ", ".join(unset))
            if alarm:
                signal.setitimer(signal.ITIMER_REAL, tmo)  # 소수 초(쪽당 0.1초)도 가능
            if a.isolate:
                _isolated(eng, doc, dst, a.profile, tmo)
            else:
                _write_atomic(dst, json.dumps(registry.run(eng, doc, a.profile), ensure_ascii=False))
        except Exception as ex:  # ponytail: SIGALRM은 C 확장 안에서 멈추면 못 끊음 — 그런 엔진은 --isolate
            err = redact(f"{type(ex).__name__}: {str(ex)[:300]}")
            if _FIRED[0] and not isinstance(ex, TimeoutError):
                # Linux 컨테이너 실측: rapidocr_ko가 쪽당 제한에 걸리면 ONNXRuntimeError로 감싸여 '실패'로 남고 phase 3로 안 넘어갔음
                err, ex = f"TimeoutError: 문서×엔진 시간 제한 초과(감싼 예외 {type(ex).__name__})", TimeoutError()
            if _FIRED[0]:
                _drop_half_imported()  # 시간 제한이 라이브러리 import 도중에 끊으면 다음 문서부터 계속 실패 — 지움
            if isinstance(ex, ImportError):
                err += " (미설치)"
            elif not isinstance(ex, TimeoutError) and (not isinstance(ex, LookupError) or not unset):
                traceback.print_exc(limit=1)
        finally:
            if alarm:
                signal.setitimer(signal.ITIMER_REAL, 0)
        ever = P0.engine_version(eng)
        pkey = p0_key(eng, sha, ever)  # P0 열쇠(다음 실행의 재사용 판단용) — p0_status와 같은 함수
        if not err and dst.exists():
            _stamp_provenance(dst, eng, ever, pkey, a.profile)
        elif err and dst.exists():
            # 실패·시간 초과면 그 자리의 결과 파일은 이번 내용의 결과가 아님(내용이 바뀐 문서의 옛 결과 등) — 지움.
            # 10-04 결함: 옛 결과 파일이 남아 '이미 결과 있음'으로 보여 다음 phase 재시도에서 빠지고 대표에 옛 결과가 쓰일 수 있었음
            dst.unlink(missing_ok=True)
        if err and _env_error(err):  # RB3② — 미설치·미설정(env) 실패만 기억(시간 초과·그 밖의 예외는 문서 탓일 수 있어 제외)
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
                "phase": a.phase or None,
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
            tally["다음 phase로" if err and "Timeout" in err else "환경" if err and _env_error(err) else "실패" if err else "성공"] += 1
            tag = "NEXT " if err and "Timeout" in err and a.phase and a.phase < 3 else ("FAIL " if err else "ok   ")
            print(tag + f"{eng:18s} {rec['sec']:>7}s  {doc.name}" + (f"  {err[:120]}" if err else ""), flush=True)
            print(
                f"  [phase {a.phase or '-'} 큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] "
                + " · ".join(f"{k} {v}" for k, v in tally.items()),
                flush=True,
            )  # 큐 진행(콘솔)
            try:
                if time.monotonic() - last_w[0] >= 2 or done[0] == len(
                    jobs
                ):  # 1건마다 호출하되 2초 간격으로(문서×엔진이 많을 때 갱신 비용 억제)
                    write_progress(src, out, a.engines)
                    last_w[0] = time.monotonic()
            except Exception as ex:  # 현황 파일 실패가 파싱을 멈추면 안 됨
                print(f"(PROGRESS.md 갱신 실패: {type(ex).__name__}: {ex})", flush=True)

    def safe(job):
        try:
            run_job(job)
        except TimeoutError:  # 끝나는 순간 타이머가 울림(finally 안) — 결과는 썼고 기록만 빠짐, 다음 실행에서 다시 판단
            if alarm:
                signal.setitimer(signal.ITIMER_REAL, 0)
            print(f"(경합: {job[1]} {job[0].name} 기록 누락 — 다음 실행에서 다시 판단)", flush=True)

    if a.workers > 1:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            list(pool.map(safe, jobs))
    else:
        for job in jobs:
            safe(job)
    for doc, eng, dst, sha, first in deferred:  # 사본: 먼저 돈 결과가 성공이면 복사, 아니면 사본은 기록 안 함(다음 실행에서 다시 판단)
        if first.exists():
            dst.write_bytes(first.read_bytes())
            rec = _with_run_id(
                {"doc": doc.name, "engine": eng, "sec": 0, "error": None, "sha": sha, "reused_from": first.name[:-5], "chars": _chars(dst)},
                run_id,
            )
            with lock:
                log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                log.flush()
                print(f"copy {eng:18s}          {doc.name}  ← {first.name[:-5]}", flush=True)
    if deferred:
        write_progress(src, out, a.engines)
    if a.phase and not a.shard:  # --procs 자식(shard)은 부모가 끝에 한 번
        _phase_done(a, src, out)
    from common.core.runlog import note

    note(
        f"문서 {len(docs)}개 · 문서×엔진 {len(jobs)}건 실행"
        + (f" · {' · '.join(f'{k} {v}' for k, v in tally.items())}" if tally else "")
        + (f" · 건너뜀 {sum(skip.values())}" if skip else "")
        + (f" · phase {a.phase}" if a.phase else "")
    )
    if skipped:
        print("건너뜀(처리 엔진 없음):", ", ".join(f"{k} {v}" for k, v in skipped.most_common()))


HEAVY = {
    "docling",
    "docling_ocr",
    "marker",
    "easyocr",
    "paddleocr",
    "ppstructure",
    "paddleocr_vl",
    "unstructured",
    "unstructured_ocr",
    "mineru",
    "rapidocr",
    "rapidocr_ko",
    "tesseract",
    "kreuzberg_ocr",
    "pymupdf4llm",
}  # 모델·OCR로 오래 걸리는 엔진 — 묶음마다 고르게


def run_procs(a, docs, want):
    """엔진 × 문서 조각을 작업 단위로, 프로세스 N개 풀에서 오래 걸리는 것부터(LPT). 조각마다 모델은 한 번 올림.
    작업량 추정 = 문서 수 × 이전 실행의 엔진 평균 초(없으면 무거운 엔진 10초 · 가벼운 1초). 한 엔진이 전체의 1/N보다 크면 문서를 쪼갬.
    자식이 비정상 종료(세그폴트)하면 그 단위만 --isolate로 한 번 더(끝낸 건은 건너뜀)."""
    from concurrent.futures import ThreadPoolExecutor

    acc = {}
    log = Path(a.out) / "runs.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("error") and r.get("sec"):
                    acc.setdefault(r["engine"], []).append(r["sec"])
    mean = {e: sum(v) / len(v) for e, v in acc.items()}
    cost = {}
    for d in docs:
        for e in registry.engines_for(d.suffix):
            if not want or e in want:
                cost[e] = cost.get(e, 0) + mean.get(e, 10 if e in HEAVY else 1)
    total = sum(cost.values()) or 1
    units = []
    for e, c in cost.items():
        k = max(1, min(a.procs, math.ceil(c / (total / a.procs))))
        units += [(c / k, e, f"{i}/{k}") for i in range(k)]
    units.sort(reverse=True)
    from common.core import resources

    thr = C.cfg().runtime.pipe_threads  # S7c — 설정 객체(auto·빈 값 = None, "0"은 0 — None일 때만 계산)
    threads = str(int(thr) if thr is not None else max(1, resources.cpus() // a.procs))  # cgroup 한도 기준(os.cpu_count()는 호스트 코어)
    # env 남김 — 하위 프로세스·엔진에 넘김(엔진 파일은 env를 직접 읽음)
    env = dict(
        os.environ,
        RUNLOG_CHILD="1",
        OMP_NUM_THREADS=threads,
        MKL_NUM_THREADS=threads,
        OPENBLAS_NUM_THREADS=threads,
        NUMEXPR_NUM_THREADS=threads,
        TORCH_NUM_THREADS=threads,
    )
    base, skip_next = [sys.executable, "-m", "pipeline.extract.run_all"], False
    for x in sys.argv[1:]:  # --procs·--engines·--shard만 빼고 같은 인자
        if skip_next:
            skip_next = False
            continue
        if x in ("--procs", "--engines", "--shard"):
            skip_next = True
            continue
        if not x.startswith(("--procs=", "--engines=", "--shard=")):
            base.append(x)
    print(
        f"프로세스 {a.procs}개 · 프로세스당 스레드 {threads} · 작업 단위 {len(units)}개(엔진 × 문서 조각) · "
        f"순차 기준 추정 {total / 60:.0f}분",
        flush=True,
    )

    def one(u):
        _, e, shard = u
        cmd = base + [
            "--engines",
            e,
            "--shard",
            shard,
            "--procs",
            "1",
        ]  # 하위는 항상 1(PIPE_PROCS 환경변수로 하위가 또 프로세스를 띄우는 연쇄 방지)
        if resources.gated_popen(cmd, env=env).wait() != 0:
            print(f"비정상 종료 → --isolate로 이어서: {e} {shard}", flush=True)
            resources.gated_popen(cmd + ["--isolate"], env=env).wait()

    with ThreadPoolExecutor(max_workers=a.procs) as ex:
        list(ex.map(one, units))
    write_progress(Path(a.src), Path(a.out), a.engines)
    if a.phase:
        _phase_done(a, Path(a.src), Path(a.out))


def phase2_failed(src, out):
    """phase 1·2에서 실패·시간 초과한 문서×엔진 → output/parse/PHASE2_FAILED.csv·.md(phase 3를 나중에 돌릴 대상).
    성공한 엔진이 하나도 없는 문서는 따로 표시 — 그 문서는 대표 파싱·검색에서 빠짐."""
    import csv

    from pipeline.transform.represent.represent import last_runs, status

    last = last_runs(out)
    docs = sorted(p.name for p in Path(src).iterdir() if p.is_file() and p.suffix.lower() != ".csv")
    rows = [(d, e, status(r), r) for (d, e), r in sorted(last.items()) if d in docs and (r.get("phase") or 0) <= 2 and r.get("error")]
    env = Counter(e for d, e, st, _ in rows if st == "환경")  # 미설치·미설정 엔진 — 문서 문제가 아님(목록에서 빼고 엔진별 수만)
    rows = [x for x in rows if x[2] != "환경"]
    ok = {d for (d, e), r in last.items() if not r.get("error")}
    none = [d for d in docs if d not in ok]
    with (out / "PHASE2_FAILED.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["문서", "엔진", "상태", "phase", "제한초", "걸린초", "시각", "성공 엔진 있음", "오류"])
        for d, e, st, r in rows:
            w.writerow(
                [
                    d,
                    e,
                    st,
                    r.get("phase"),
                    r.get("limit"),
                    r.get("sec"),
                    r.get("at"),
                    "예" if d in ok else "아니오",
                    (r.get("error") or "")[:200],
                ]
            )
    c = Counter(st for _, _, st, _ in rows)
    md = [
        f"# phase 2까지 실패한 문서×엔진 — {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- 문서×엔진 {len(rows)}건: " + " · ".join(f"{k} {v}" for k, v in c.most_common()) + f" (문서 {len({d for d, *_ in rows})}개)",
        f"- **성공한 엔진이 하나도 없는 문서 {len(none)}개** — 대표 파싱·검색에서 빠짐. phase 3(긴 제한·VLM)는 시간 날 때: "
        "`python cli/pipeline.py parse --phases 3`(모듈) 또는 `night --phases 3`",
        "- 목록: `PHASE2_FAILED.csv`(문서·엔진·상태·제한·오류) · 문서×엔진 전체 시도 표: `_rep/engines.csv`",
        "- 목록에서 뺀 환경 문제(미설치·미설정 엔진 — 문서 탓 아님): " + (" · ".join(f"{e} {v}" for e, v in env.most_common()) or "없음"),
        "",
    ]
    md += [f"- {d}" for d in none[:200]] + ([f"- … 외 {len(none) - 200}개(CSV)"] if len(none) > 200 else [])
    (out / "PHASE2_FAILED.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"phase 2까지 실패 {len(rows)}건 · 성공 엔진 없는 문서 {len(none)}개 → {out / 'PHASE2_FAILED.md'}", flush=True)


def _phase_done(a, src, out):

    from pipeline.shared.phase_report import write_phase_report

    if a.phase == 2:
        phase2_failed(src, out)
    # OP23(사용자 10-08) — 옛 PHASE_REPORT.md·phase<N>-report.html 자동 생성은 기본 끔(실행판 run_board가 대신), 10-29 PHASE_REPORT_LEGACY 칸 삭제로 늘 끔
    try:
        p = write_phase_report(src, out, a.engines, a.phase, a.truth or None, text_only=True)
    except Exception as ex:
        print(f"(phase 결과 계산 실패: {type(ex).__name__}: {ex} — python modules/parse/phase_report.py로 다시)", flush=True)
        return
    txt = p
    print(
        "\n" + txt.split("## C.")[0].strip() + f"\n\n(실행판: python cli/run_board.py --out {out.parent.as_posix()})",
        flush=True,
    )
    from common.core.runlog import note
    from pipeline.shared.runlog import next_step  # 10-14 — common.core.runlog에서 옮김(P만 씀)

    for line in txt.splitlines():
        if line.startswith(f"| {a.phase} |"):
            c = [x.strip() for x in line.strip("|").split("|")]
            note(f"phase {a.phase} 결과: 시도 {c[1]} · 성공 {c[2]} · 다음 phase로 {c[3]} · 실패 {c[4]} · 환경 {c[5]} · {c[6]}")
        elif line.startswith(("## B.", "## C.")):
            note(line.lstrip("# ").strip())
        elif line.startswith("문서 ") and "사람 검토" in line:
            note(line.split("기준점 =")[0].strip().rstrip("."))
        elif line.startswith("**성공 문서 합계"):
            note(line.strip("*"))
        elif line.startswith("다음 할 일:") and "`" in line:
            next_step(line.split("`")[1])
    note(f"리포트: {p}")


def _phase_sec(a):
    """phase의 쪽당 제한 초(--phase-sec 'p1,p2,p3', 예전 두 값이면 3은 1초)."""
    v = (a.phase_sec.split(",") + ["1"])[:3]
    return float(v[a.phase - 1])


def _drop_half_imported():
    """시간 제한 신호가 라이브러리 import 도중에 걸리면 그 모듈이 sys.modules에 '반쯤 초기화'로 남아, 같은 엔진의 다음 문서가 전부
    `partially initialized module` 오류로 실패한다(Linux 컨테이너 실측 10-02: phase 1 쪽당 0.1초에 markitdown→pandas 136건·pymupdf4llm→yaml 16건).
    → 초기화 중 표시가 남은 모듈을 지워 다음 import가 처음부터 다시 하게."""
    tops = {name.split(".")[0] for name, m in list(sys.modules.items()) if getattr(getattr(m, "__spec__", None), "_initializing", False)}
    tops -= {"modules", "common", "tools", "__main__"}  # 우리 코드는 그대로(끊긴 것은 외부 라이브러리)
    for name in [
        n for n in list(sys.modules) if n.split(".")[0] in tops
    ]:  # 하위 모듈만 끊겨도 부모에 속성이 빠짐(pymupdf4llm.helpers) — 패키지째
        sys.modules.pop(name, None)


def _with_run_id(rec, run_id):
    """SI23 — runs.jsonl 줄에 이번 실행 run_id(env PARSE_RUN_ID)를 달아 run_board가 이번 실행만 거를 수 있게.
    env 없으면 그대로(run_id 칸 없음 — 옛 형식과 호환, run_board는 그때 지금처럼 마지막 기록 기준으로 폴백)."""
    return {**rec, "run_id": run_id} if run_id else rec


def _is_timeout(r):
    return bool(r.get("error")) and "Timeout" in r["error"]


def _write_atomic(dst, text):
    """임시 파일에 다 쓰고 이름 바꿈 — 중간에 끊겨도 0바이트·반쪽 결과가 남지 않게(10-04 실측: 끊긴 실행이 0바이트 6건을 남겨 parse_qa가 죽음).
    RV6(10-09) — common/atomic.atomic_write_text로 옮김(동작 그대로)."""
    atomic_write_text(dst, text)


def _stamp_provenance(dst, eng, engine_version, p0_key, profile):
    """엔진 결과 JSON에 provenance 블록을 더함(W8) — engine·engine_version·p0_key·params·created_at. 실패해도 파싱 결과는 그대로 둠."""
    try:
        d = json.loads(dst.read_text(encoding="utf-8"))
        d["provenance"] = {
            "engine": eng,
            "engine_version": engine_version,
            "p0_key": p0_key,
            "params": {"profile": profile},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write_atomic(dst, json.dumps(d, ensure_ascii=False))
    except (OSError, ValueError):
        pass


def _chars(dst):
    try:
        return len((json.loads(Path(dst).read_text(encoding="utf-8")).get("text") or "").strip())
    except (OSError, ValueError):
        return 0


def _sha(p):
    import hashlib

    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def p0_status(prev, eng, sha):
    """P0 열쇠(엔진 버전·코드 지문, pipeline.shared.artifacts) 비교 → ("ok"|"stale"|"unknown", 지금 열쇠).
    열쇠 없는 옛 기록(provenance 이전) = "버전 미상"(unknown) — 기본은 그대로 건너뜀, --refresh-unknown일 때만 다시."""
    ver = P0.engine_version(eng)
    cur = p0_key(eng, sha, ver)
    prev_key = (prev or {}).get("p0_key")
    if not prev_key:
        return "unknown", cur
    if prev_key == cur:
        return "ok", cur
    # 옛 기록(10-03 — 열쇠에 common/*.py·run_all.py까지 들어가 검색 토크나이저만 바꿔도 낡음이 되던 형식):
    # 엔진 코드 지문(p0_code)이 기록에 없으면, 같은 내용(sha)·같은 엔진 설치 버전이면 같은 결과로 봄(원문 재파싱 방지 — 사용자 원칙)
    if not (prev or {}).get("p0_code") and (prev or {}).get("engine_version") == ver and (prev or {}).get("sha") in (None, sha):
        return "ok", cur
    return "stale", cur


def engine_code_fp(eng):
    """원문 파싱 결과를 정하는 코드 = 그 엔진 폴더(parse/engines/<엔진>)만 — common·run_all(실행 관리)이 바뀌어도 결과는 같으므로 넣지 않음."""
    import hashlib

    h = hashlib.sha256()
    # 엔진 폴더 + 엔진 공용 도우미(parse/engines/_common — 표·사실 추출을 엔진 31개 중 30개가 씀, 독립 검토 10-04)
    # 엔진 이름 ≠ 폴더 이름인 엔진이 있음(office → office_stdlib · rapidocr_ko → rapidocr …) — 등록부의 스택 폴더로(10-05 결함: 이름 폴더가 없어
    # _common만 해시 → 엔진 코드를 고쳐도 원문 결과가 낡음으로 안 잡혔음)
    stack = registry.engines().get(eng, (eng, None))[0]
    files = sorted(set((PARSING_ROOT / "engines" / stack).glob("**/*.py")) | set((PARSING_ROOT / "engines" / "_common").glob("**/*.py")))
    from common import legacy_names  # 10-14 폴더 분리 — 옛 경로(parse/engines/…)·옛 import 이름으로 해시(전 문서 재파싱 방지)

    for p in files:
        h.update(("parse/" + p.relative_to(PARSING_ROOT).as_posix()).encode("utf-8"))
        h.update(legacy_names(p.read_bytes()))
    return h.hexdigest()[:12]


def p0_key(eng, sha, ver=None):
    """P0 열쇠 하나로 — 기록(run_job)과 비교(p0_status)가 같은 함수를 씀 = (원본 sha · 엔진 설치 버전 · 엔진 코드 지문).
    (10-04 결함: 비교는 버전 포함·기록은 버전 없이 만들어 늘 '낡음' → 바뀌지 않은 문서도 전부 다시 파싱하던 일)"""
    import hashlib

    parts = json.dumps(
        {"eng": eng, "sha": sha, "ver": ver if ver is not None else P0.engine_version(eng), "code": engine_code_fp(eng)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _env_error(err):
    from pipeline.shared.progress import is_env_error  # 환경 실패 단서 한 곳(SI45 — 손상 PDF 'EOF marker not found'를 env로 보던 것)

    return is_env_error(err)


def _isolated(eng, doc, dst, profile, tmo, py=None):
    py = py or sys.executable
    retries = int(
        pc.cfg().extract.engine_retry
    )  # S7c — 설정 객체(기본 1) · 비정상 종료만 바로 다시(10-14 rapidocr ResizeImgError 1회성 — 단독 재실행은 성공)
    for attempt in range(retries + 1):
        try:
            return _isolated_once(eng, doc, dst, profile, tmo, py)
        except RuntimeError:
            if attempt == retries:
                raise


def _isolated_once(eng, doc, dst, profile, tmo, py):
    import subprocess

    from common.core import resources as RS
    from common.core.paths import child_env

    # PADDLE_PYTHON은 별도 venv(.venv-paddle)라 cwd 상속에 의존하지 않고 child_env()의 PYTHONPATH(deploy/)로 `-m pipeline.extract.parse_one`을 찾게 함
    pr = RS.gated_popen(
        [py, "-m", "pipeline.extract.parse_one", "--engine", eng, "--profile", profile, str(doc), str(dst)],
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _, err = pr.communicate(timeout=tmo)
    except subprocess.TimeoutExpired as tmo_err:
        pr.kill()
        pr.communicate()
        dst.unlink(missing_ok=True)  # 쓰다 만 결과를 남기지 않음
        raise TimeoutError(f"문서×엔진 시간 제한 초과({tmo}초)") from tmo_err
    if pr.returncode != 0:
        dst.unlink(missing_ok=True)
        last = (err.strip().splitlines() or [f"exit {pr.returncode}"])[-1]
        raise RuntimeError(
            f"하위 프로세스 종료 코드 {pr.returncode}"
            + (" (세그폴트 등 비정상 종료)" if pr.returncode < 0 or pr.returncode > 1 else "")
            + f": {last[:200]}"
        )


_FIRED = [False]  # 시간 제한 신호가 울렸는지 — C 확장(onnxruntime 등) 안에서 울리면 TimeoutError가 그 라이브러리 예외로 감싸여 나옴


def _timeout(signum, frame):
    _FIRED[0] = True
    raise TimeoutError("문서×엔진 시간 제한 초과")


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("run_all"):
        main()
