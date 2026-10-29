#!/usr/bin/env python3
"""문서 폴더 × 엔진 일괄 파싱 → output/parse/<engine>/<문서>.json + output/parse/runs.jsonl(시간·오류).

사용: python modules/parse/run_all.py [--src <원본 문서 폴더>] [--out output/parse] [--engines pdfplumber,docling] [--limit N]
  --src 생략 시 DOC_DIR env 필수(없으면 SystemExit) — common/paths.py.doc_dir.
  제한 시간(사용자 10-29 — phase 없앰): 문서×엔진 1건 = 쪽 수 × 쪽당 초 — 글자 엔진 text_page_sec(PARSE_TEXT_PAGE_SEC, 기본 10) ·
    VLM 엔진 vlm_page_sec(PARSE_VLM_PAGE_SEC, 기본 120) + 엔진의 첫 문서는 warmup_sec 하한 + 별도 프로세스 시작 여유 isolate_overhead.
    넘으면 같은 실행에서 제한을 두 배로 한 번 더, 그래도 넘으면 실패로 기록(다음 실행은 --retry-failed로만 다시).
  문서마다 그 형식의 엔진(stack.json — 형식당 최대 2개)을 **동시에**(엔진마다 별도 프로세스 parse/parse_one.py — 세그폴트가 전체를
    멈추지 않음). --workers N: 문서 N개를 동시에. --procs N: 문서를 N조각으로 나눠 프로세스 N개가 동시에(스레드는 코어 ÷ N).
  OCR 엔진(OCR_ENGINES — rapidocr·rapidocr_ko)은 ocr_engine(PARSE_OCR_ENGINE, 기본 끔)일 때만 돈다 — 이미지·스캔 문서는 VLM 엔진만.
    글자 PDF 안의 스캔 쪽은 여기서 OCR 엔진을 더하지 않고 대표 결과(represent)의 쪽 VLM이 그 쪽만 채운다.
  진행 현황: 1건 끝날 때마다 <out>/PROGRESS.md 갱신(형식별·엔진별 표·남은 시간) — 서버에서 `watch -n 30 cat output/parse/PROGRESS.md`.
  --engines 생략 시 형식별로 등록된 엔진 전부(tools/engines/<스택>/parser.py의 FORMATS).
  PARSE_ENGINE_SCOPE(환경변수, 기본 all) — stack: 문서마다 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)에
    해당하는 stack.json parse 목록으로만 좁힌다(생산 서버에서 PDF 1건에 OCR·VLM까지 9개+ 전부 도는 무거움 해소, 2026-10-07).
    stack.json에 그 키가 없으면 지금처럼 그대로(핵심 엔진 합집합, 누락 방지)+1회 로그. all(기본) = 지금 동작 그대로
    (--engines 명시 호출·compare-parse 등 실험 경로는 이 env를 안 건드리므로 영향 없음).
  다시 돌리지 않는 규칙(파일 내용 sha256 기준 — runs.jsonl에 기록):
    · 같은 내용이 그 엔진으로 이미 성공 → 건너뜀 (이름만 다른 같은 내용이면 결과를 복사해 씀, runs에 reused_from)
    · 원본 내용이 바뀜(sha 다름) → 다시 파싱
    · 실패·시간 초과 → 건너뜀(--retry-failed로 다시 — phase 시절의 옛 시간 초과 기록(phase 칸 있음)은 다시 시도) · 미설치·미설정(환경) → 매번 다시 시도(환경을 고쳤을 수 있음)
    · --force: 전부 다시
  RB3② — 미설치·미설정(환경) 엔진은 이번 실행(프로세스) 안에서 처음 실패한 문서 뒤로 같은 엔진은 나머지 문서를 시도하지 않고
    runs.jsonl에 '건너뜀(환경 — 첫 실패 <문서>)'로 기록(문서마다 프로세스 기동·import 비용 반복 방지). 시간 초과·그 밖의 예외는 문서 탓일 수 있어 그대로 매 문서 시도.
    --procs 자식 프로세스끼리는 공유하지 않음(프로세스마다 다시 한 번 확인).
"""

import argparse
import json
import os
import re
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
from pipeline.stackcfg import MAX_PER_TYPE, over_limit  # 사용자 10-29 — 형식당 엔진 2개 상한(진입점 검사와 같은 함수)

_QUOTED = re.compile(r"""(['"])((?:(?!\1).){30,})\1""", re.S)


def redact(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림(백로그 X2 ⑤ — 로그·runs.jsonl에 본문 금지).
    ponytail: 완벽하지 않음(인용부호 없는 echo는 못 잡음) — 더 필요하면 강화."""
    return _QUOTED.sub(lambda m: m.group(1) + "…[가림]…" + m.group(1), s or "")


VLM_ENGINES = {"qwen_vlm", "ocr_vlm", "docling_vlm", "marker_llm"}
# 사용자 10-29 — OCR 엔진은 기본으로 안 돌림(ocr_engine 설정, 기본 끔). 엔진 코드는 남김(나중에 쪽 회전 판정에 씀) · stack 표는 그대로
OCR_ENGINES = {"rapidocr", "rapidocr_ko"}


def n_pages(doc):
    if doc.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(doc)))
    except Exception:
        return 1


def page_timeout(eng, pages, first=False):
    """문서×엔진 1건 제한(초, 사용자 10-29) = 쪽 수 × 쪽당 초(VLM 엔진 vlm_page_sec · 그 밖 text_page_sec) · 엔진의 첫 문서는
    warmup_sec 하한(import·모델 적재) · 별도 프로세스 시작 여유 isolate_overhead를 더함. 시간 초과면 호출자가 두 배로 한 번 더."""
    x = pc.cfg().extract
    tmo = max(1, pages) * float(x.vlm_page_sec if eng in VLM_ENGINES else x.text_page_sec)
    if first:
        tmo = max(tmo, float(x.warmup_sec))
    return round(tmo + float(x.isolate_overhead), 2)


def engines_for_doc(doc, scope, stack_parse, types, logged_missing):
    """문서 하나에 돌릴 엔진 후보(이후 --engines want로 더 좁혀짐) — PE1(2026-10-07, PARSE_ENGINE_SCOPE). doc은 Path.
    scope != "stack"(기본 all) → registry.engines_for(suffix) 그대로(실험 경로·명시 --engines).
    scope == "stack" → 문서 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록으로 좁힌다.
    그 키가 stack.json에 없으면 그대로(핵심 엔진 합집합으로 대체, 누락 방지) + 형식별 1회만 로그.
    사용자 10-29 — .pdf_text 안 스캔 쪽 때문에 .pdf_image 엔진을 합치지 않음(대표 결과의 쪽 VLM이 그 쪽만 채움) ·
    OCR 엔진은 ocr_engine 설정이 켜졌을 때만(두 scope 모두)."""
    suffix = doc.suffix
    cands = registry.engines_for(suffix)
    if not pc.cfg().extract.ocr_engine:
        cands = [e for e in cands if e not in OCR_ENGINES]
    if scope != "stack":
        return cands
    key = types.get(doc.name, suffix.lower())
    stack_eng = stack_parse.get(key)
    if stack_eng is None:
        if key not in logged_missing:
            print(f"[engine-scope] stack.json에 '{key}' 형식 없음 — 핵심 엔진 합집합으로 대체", flush=True)
            logged_missing.add(key)
        return cands
    return [e for e in cands if e in stack_eng]


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
    ap.add_argument("--isolate", action="store_true", help="(옛 호환 — 이제 늘 문서×엔진마다 별도 프로세스)")
    ap.add_argument("--workers", type=int, default=1, help="동시에 처리할 문서 수(문서 안 엔진들은 늘 동시에)")
    ap.add_argument(
        "--procs",
        default=_default_procs(),
        help="문서를 N조각으로 나눠 프로세스 N개로 동시에 · auto = CPU·메모리(cgroup) 기준(common/resources.py)",
    )
    ap.add_argument("--shard", default="", help="i/k — 문서 목록의 i번째 조각만(--procs가 씀)")
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
    scope = pc.cfg().extract.engine_scope  # S7c — 설정 객체(옛 `get(X, "all")`: 없음 → all, 빈 글자는 그대로)
    scope = scope if scope is not None else "all"  # PE1 — stack: 문서 형식별 stack.json 목록만(생산 기본), all(기본): 지금 동작 그대로
    stack_parse = {}
    if scope == "stack":
        try:
            stack = pc.stack_path()  # S8b — 진입점이 만든 판 사본(PC는 파일)
            stack_parse = (json.loads(stack.read_text(encoding="utf-8")).get("parse") or {}) if stack.exists() else {}
        except (OSError, ValueError):
            stack_parse = {}
        bad = over_limit({"parse": stack_parse})  # 사용자 10-29 — 형식당 엔진 2개 넘으면 설정 오류(진입점 resolve도 같은 검사)
        if bad:
            raise SystemExit(f"[엔진 구성] {stack} — " + " · ".join(bad))
    types = doc_types(docs, out) if stack_parse else {}
    logged_missing = set()
    skipped_log = src / "skipped.jsonl"  # SI44③ — prepare 단계와 같은 파일(누적)
    encrypted_detected = set()  # 이미 encrypted_detected로 기록된 문서(여러 실행에 중복 기록 방지)
    if skipped_log.exists():
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
        if not a.retry_failed:  # SI44③ — 앞 실행에서 실패 엔진 전부가 암호 오류면 다시 시도 안 함
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
                skip["암호 감지(앞 실행에서 전부 암호 오류 — encrypted_detected, 다시 시도 안 함)"] += len(cand)
                continue
        for eng in cand:
            if want and eng not in want:
                continue
            dst, prev = out / eng / (doc.name + ".json"), last.get((doc.name, eng))
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
                if same and prev.get("error") and not _env_error(prev["error"]) and not a.retry_failed and not _old_phase_timeout(prev):
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
                    f"  [큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] " + " · ".join(f"{k} {v}" for k, v in tally.items()),
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
        with lock:
            first = eng not in warmed
            warmed.add(eng)
        tmo = page_timeout(eng, n_pages(doc), first)
        for attempt in range(2):  # 사용자 10-29 — 시간 초과면 같은 실행에서 제한 두 배로 한 번 더, 그래도 넘으면 실패로 기록
            err = None
            try:
                if unset:
                    raise LookupError("환경변수 미설정: " + ", ".join(unset))
                _isolated(eng, doc, dst, a.profile, tmo)
            except Exception as ex:
                err = redact(f"{type(ex).__name__}: {str(ex)[:300]}")
                if isinstance(ex, ImportError):
                    err += " (미설치)"
                elif not isinstance(ex, TimeoutError) and (not isinstance(ex, LookupError) or not unset):
                    traceback.print_exc(limit=1)
            if attempt or not (err and "Timeout" in err):
                break
            tmo = round(tmo * 2, 2)
            print(f"RETRY {eng:18s} {doc.name}  시간 초과 — 제한 {tmo}초로 한 번 더", flush=True)
        ever = P0.engine_version(eng)
        pkey = p0_key(eng, sha, ever)  # P0 열쇠(다음 실행의 재사용 판단용) — p0_status와 같은 함수
        if not err and dst.exists():
            _stamp_provenance(dst, eng, ever, pkey, a.profile)
        elif err and dst.exists():
            # 실패·시간 초과면 그 자리의 결과 파일은 이번 내용의 결과가 아님(내용이 바뀐 문서의 옛 결과 등) — 지움.
            # 10-04 결함: 옛 결과 파일이 남아 '이미 결과 있음'으로 보여 재시도에서 빠지고 대표에 옛 결과가 쓰일 수 있었음
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
            tally["시간 초과" if err and "Timeout" in err else "환경" if err and _env_error(err) else "실패" if err else "성공"] += 1
            tag = "FAIL " if err else "ok   "
            print(tag + f"{eng:18s} {rec['sec']:>7}s  {doc.name}" + (f"  {err[:120]}" if err else ""), flush=True)
            print(
                f"  [큐 {done[0]}/{len(jobs)} {done[0] / max(1, len(jobs)):.0%}] " + " · ".join(f"{k} {v}" for k, v in tally.items()),
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

    by_doc = {}
    for job in jobs:
        by_doc.setdefault(job[0], []).append(job)

    def run_doc(doc_jobs):  # 사용자 10-29 — 한 문서의 엔진들(형식당 최대 2개)은 동시에, 엔진마다 별도 프로세스
        if len(doc_jobs) == 1:
            return run_job(doc_jobs[0])
        # ponytail: scope=all(실험 경로)은 엔진이 2개보다 많을 수 있어 동시 수만 MAX_PER_TYPE으로 묶음
        with ThreadPoolExecutor(max_workers=min(len(doc_jobs), MAX_PER_TYPE)) as pool:
            list(pool.map(run_job, doc_jobs))

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        list(pool.map(run_doc, by_doc.values()))
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
    from common.core.runlog import note

    note(
        f"문서 {len(docs)}개 · 문서×엔진 {len(jobs)}건 실행"
        + (f" · {' · '.join(f'{k} {v}' for k, v in tally.items())}" if tally else "")
        + (f" · 건너뜀 {sum(skip.values())}" if skip else "")
    )
    if skipped:
        print("건너뜀(처리 엔진 없음):", ", ".join(f"{k} {v}" for k, v in skipped.most_common()))


def run_procs(a, docs):
    """문서를 N조각(내용 sha 기준 — 같은 내용 사본은 같은 조각)으로 나눠 프로세스 N개가 동시에(사용자 10-29 — 엔진 묶음이 아니라 문서 조각).
    조각마다 문서 안 엔진들은 동시에·엔진마다 별도 프로세스(run_job)라 조각 프로세스 자체는 세그폴트로 죽지 않는다."""
    from common.core import resources

    k = max(1, min(a.procs, len(docs)))
    thr = C.cfg().runtime.pipe_threads  # S7c — 설정 객체(auto·빈 값 = None, "0"은 0 — None일 때만 계산)
    threads = str(int(thr) if thr is not None else max(1, resources.cpus() // k))  # cgroup 한도 기준(os.cpu_count()는 호스트 코어)
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
        rc = resources.gated_popen(base + ["--shard", f"{i}/{k}", "--procs", "1"], env=env).wait()
        if rc != 0:
            print(f"조각 {i}/{k} 비정상 종료({rc}) — 끝낸 문서×엔진은 runs.jsonl에 남아 다음 실행에서 건너뜀", flush=True)

    with ThreadPoolExecutor(max_workers=k) as ex:
        list(ex.map(one, range(k)))
    write_progress(Path(a.src), Path(a.out), a.engines)


def _old_phase_timeout(r):
    """phase 시절(10-29 전)의 시간 초과 기록 — 그때 제한(쪽당 0.1~1초)이 지금보다 훨씬 짧았으므로 실패로 막지 않고 다시 시도."""
    return bool(r.get("phase")) and _is_timeout(r)


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


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("run_all"):
        main()
