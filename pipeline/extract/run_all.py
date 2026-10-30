#!/usr/bin/env python3
"""문서 폴더 × 엔진 일괄 파싱 → output/parse/<engine>/<문서>.json + output/parse/runs.jsonl(시간·오류).

사용: python modules/parse/run_all.py [--src <원본 문서 폴더>] [--out output/parse] [--engines pdfplumber,pymupdf] [--limit N]
  --src 생략 시 DOC_DIR env 필수(없으면 SystemExit) — common/paths.py.doc_dir.
  제한 시간(사용자 10-29 — phase 없앰): 문서×엔진 1건 = 쪽 수 × 쪽당 초 — 글자 엔진 text_page_sec(PARSE_TEXT_PAGE_SEC, 기본 10) ·
    VLM 엔진 vlm_page_sec(PARSE_VLM_PAGE_SEC, 기본 120) + 엔진의 첫 문서는 warmup_sec 하한 + 별도 프로세스 시작 여유 isolate_overhead.
    넘으면 같은 실행에서 제한을 두 배로 한 번 더, 그래도 넘으면 실패로 기록.
  문서마다 그 형식의 엔진(stack.json — 형식당 최대 2개)을 **동시에**(엔진마다 별도 프로세스 parse/parse_one.py — 세그폴트가 전체를
    멈추지 않음). --workers N: 문서 N개를 동시에. --procs N: 문서를 N조각으로 나눠 프로세스 N개가 동시에(스레드는 코어 ÷ N).
  OCR 엔진(OCR_ENGINES — rapidocr·rapidocr_ko)은 ocr_engine(PARSE_OCR_ENGINE, 기본 끔)일 때만 돈다 — 이미지·스캔 문서는 VLM 엔진만.
    글자 PDF 안의 스캔 쪽은 여기서 OCR 엔진을 더하지 않고 대표 결과(represent)의 쪽 VLM이 그 쪽만 채운다.
  진행 현황: 1건 끝날 때마다 <out>/PROGRESS.md 갱신(형식별·엔진별 표·남은 시간) — 서버에서 `watch -n 30 cat output/parse/PROGRESS.md`.
  엔진 범위는 stack 하나(pl-03, 사용자 10-30 — 옛 PARSE_ENGINE_SCOPE all·--engines all 길은 지움): 문서마다 형식 키
    (.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록만 돈다. --engines는 그 안에서 더 좁힐 뿐(비교 실험은
    stack json을 고쳐서). stack.json에 그 키가 없으면 핵심 엔진 합집합으로 대체(누락 방지)+형식별 1회 로그.
  앞 실행 결과를 다시 쓰지 않는다(pl-32 사용자 10-30 — 실행마다 새 작업 폴더): 요청한 문서×엔진은 늘 돈다. runs.jsonl은 이번 실행의
    시간·오류 기록(보고 도구가 읽음). 같은 실행 안의 같은 내용 사본(sha 같음)은 한 번만 파싱해 복사(runs에 reused_from).
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
from pipeline.shared import artifacts as P0  # P0 열쇠(엔진 버전·코드 지문) — 결과 출처 기록(실험 저장소 계약과 같은 규칙)
from pipeline.shared.progress import (  # output/parse/PROGRESS.md 갱신 · 문서→형식 키(.pdf_text/.pdf_image, _types.json 캐시) · SI44③ 암호 오류 단서(한 곳)
    doc_types,
    write_progress,
)
from pipeline.stackcfg import MAX_PER_TYPE, over_limit  # 사용자 10-29 — 형식당 엔진 2개 상한(진입점 검사와 같은 함수)

_QUOTED = re.compile(r"""(['"])((?:(?!\1).){30,})\1""", re.S)


def redact(s):
    """오류 글자에 섞여 나올 수 있는 문서 내용(인용부호로 감싼 긴 조각)을 가림(백로그 X2 ⑤ — 로그·runs.jsonl에 본문 금지).
    ponytail: 완벽하지 않음(인용부호 없는 echo는 못 잡음) — 더 필요하면 강화."""
    return _QUOTED.sub(lambda m: m.group(1) + "…[가림]…" + m.group(1), s or "")


VLM_ENGINES = {"qwen_vlm"}  # docling_vlm·marker_llm은 10-30 지움(pl-31)
# 사용자 10-29 — OCR 엔진은 기본으로 안 돌림(ocr_engine 설정, 기본 끔). 엔진 코드는 남김(나중에 쪽 회전 판정에 씀) · stack 표는 그대로
OCR_ENGINES = {"rapidocr_ko"}  # rapidocr(1.x)는 10-30 지움(pl-31)


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


def engines_for_doc(doc, stack_parse, types, logged_missing):
    """문서 하나에 돌릴 엔진 후보(이후 --engines want로 더 좁혀짐) — PE1(2026-10-07) · pl-03(10-30, stack 하나). doc은 Path.
    문서 형식 키(.pdf_text/.pdf_image/확장자, stack.json과 같은 키)의 stack.json parse 목록으로 좁힌다.
    그 키가 stack.json에 없으면 그대로(핵심 엔진 합집합으로 대체, 누락 방지) + 형식별 1회만 로그.
    사용자 10-29 — .pdf_text 안 스캔 쪽 때문에 .pdf_image 엔진을 합치지 않음(대표 결과의 쪽 VLM이 그 쪽만 채움) ·
    OCR 엔진은 ocr_engine 설정이 켜졌을 때만."""
    suffix = doc.suffix
    cands = registry.engines_for(suffix)
    if not pc.cfg().extract.ocr_engine:
        cands = [e for e in cands if e not in OCR_ENGINES]
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
        help="엔진 구성 파일(PC 실험·시험용 — 비우면 판: STACK_VERSION > PC 파일, pl-32 · pl-03 represent·build_bundle과 같음)",
    )
    a = ap.parse_args()
    from common.core import resources
    from pipeline.extract import resources as presources  # 10-14 — resolve_procs·thread_env는 common.core.resources에서 옮김(P만 씀)

    a.procs = 1 if a.shard else presources.resolve_procs(a.procs)  # --shard = run_procs가 띄운 하위 → 다시 나누지 않음
    # OC2(사용자 10-15) — 실제 동시 수로 CPU를 나눔(thread_share). 조각은 이 값을 setdefault로 물려받음. OC1 rapidocr 스레드도 OMP_NUM_THREADS를 따름.
    # 10-29 — 동시 글자 엔진 자식 = 조각 × min(문서 workers × 형식당 엔진 2, 코어 ÷ 조각) — VLM 엔진(API 대기)은 이 상한 밖
    slots = min(max(1, a.workers) * MAX_PER_TYPE, presources.text_slots(resources.cpus(), a.procs))
    thr = C.cfg().runtime.pipe_threads  # S7c — 설정 객체(float, auto·빈 값 = None — 옛 `int(get or 계산)`: "0"은 0이라 None일 때만 계산)
    for k, v in presources.thread_env(int(thr) if thr is not None else presources.thread_share(resources.cpus(), a.procs, slots)).items():
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
    # pl-32(사용자 10-30) — 앞 실행의 runs.jsonl로 건너뛰거나 결과를 복사하지 않는다(실행마다 새 작업 폴더 — runs.jsonl은 이번 실행 기록만).
    # 같은 실행 안의 같은 내용 사본은 한 번만 파싱 후 복사(planned·deferred).
    jobs, skip, planned, deferred = [], Counter(), {}, []
    # pl-03(사용자 10-30) — 엔진 범위는 stack 하나: 문서 형식별 stack.json 목록만
    stack = (
        json.loads(Path(a.stack).read_text(encoding="utf-8")) if a.stack else pc.stack()
    )  # pl-32 — 진입점이 정한 판(PC는 파일) · --stack은 시험·실험용 파일
    stack_parse = stack.get("parse") or {}
    bad = over_limit({"parse": stack_parse})  # 사용자 10-29 — 형식당 엔진 2개 넘으면 설정 오류(진입점 resolve도 같은 검사)
    if bad:
        raise SystemExit(f"[엔진 구성] 판 {stack.get('version_id') or '파일'} — " + " · ".join(bad))
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
            if (eng, sha) in planned:  # 같은 실행 안의 같은 내용 사본 — 먼저 도는 것 결과를 끝나고 복사
                deferred.append((doc, eng, dst, sha, planned[(eng, sha)]))
                continue
            planned[(eng, sha)] = dst
            jobs.append((doc, eng, dst, sha))
    if deferred:
        skip["같은 내용 사본(1번만 파싱 후 복사)"] += len(deferred)
    # pl-03 — 범위는 stack 하나: 명시 --engines 중 stack 형식별 목록 밖(또는 이 문서들 형식에 없음)은 안 돎 — 조용히 빠지지 않게 1줄
    idle = sorted(set(want or ()) - {e for _, e, _, _ in jobs} - {e for _, e, _, _, _ in deferred})
    if idle:
        print(f"[engine-scope] stack 목록 밖이라 안 돎(비교하려면 stack json을 고침): {', '.join(idle)}", flush=True)
    if skip:
        print("건너뜀: " + " · ".join(f"{k} {v}" for k, v in skip.items()), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    log, lock = RunLog(out / "runs.jsonl"), threading.Lock()
    try:
        write_progress(src, out, a.engines)
    except Exception as ex:
        print(f"(PROGRESS.md 갱신 실패: {type(ex).__name__}: {ex})", flush=True)
    print(f"진행 현황: {out / 'PROGRESS.md'} (1건마다 갱신) · 이번 실행 {len(jobs)}건", flush=True)

    done, tally, last_w = [0], Counter(), [0.0]

    warmed = set()
    text_sem = threading.BoundedSemaphore(slots)  # 10-29 — 글자(CPU) 엔진 자식 동시 수 상한(VLM 엔진은 --workers만큼)
    vlm_env = _vlm_child_env()  # M3 — VLM 엔진 자식의 VLM 호출 제한 = min(models.vlm.timeout, vlm_page_sec)
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
        if eng in VLM_ENGINES:
            err, tmo = _run_with_retry(eng, doc, dst, a.profile, tmo, unset, vlm_env)
        else:
            with text_sem:
                err, tmo = _run_with_retry(eng, doc, dst, a.profile, tmo, unset, None)
        ever = P0.engine_version(eng)
        pkey = p0_key(eng, sha, ever)  # P0 열쇠(결과 출처 기록 — provenance·runs.jsonl)
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

    _run_docs(jobs, run_job, a.workers)
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
            print(f"조각 {i}/{k} 비정상 종료({rc}) — 이 조각은 다시 돌려야 함(앞 실행 결과를 건너뛰지 않음 — pl-32)", flush=True)

    with ThreadPoolExecutor(max_workers=k) as ex:
        list(ex.map(one, range(k)))
    write_progress(Path(a.src), Path(a.out), a.engines)


def _run_docs(jobs, run_job, workers):
    """사용자 10-29 — 문서 workers개를 동시에, 한 문서의 엔진들(형식당 최대 2개)도 동시에(엔진마다 별도 프로세스 — run_job).
    ponytail: scope=all(실험 경로)은 엔진이 2개보다 많을 수 있어 문서 안 동시 수만 MAX_PER_TYPE으로 묶음."""
    by_doc = {}
    for job in jobs:
        by_doc.setdefault(job[0], []).append(job)

    def run_doc(doc_jobs):
        if len(doc_jobs) == 1:
            return run_job(doc_jobs[0])
        with ThreadPoolExecutor(max_workers=min(len(doc_jobs), MAX_PER_TYPE)) as pool:
            list(pool.map(run_job, doc_jobs))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(run_doc, by_doc.values()))


def _run_with_retry(eng, doc, dst, profile, tmo, unset, env):
    """문서×엔진 1건 — 시간 초과면 같은 실행에서 제한 두 배로 한 번 더(사용자 10-29), 그래도 넘으면 실패. 반환: (오류 글자 또는 None, 마지막 제한)."""
    for attempt in range(2):
        err = None
        try:
            if unset:
                raise LookupError("환경변수 미설정: " + ", ".join(unset))
            _isolated(eng, doc, dst, profile, tmo, env=env)
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
    return err, tmo


def _vlm_child_env():
    """VLM 엔진 자식 env — 엔진의 쪽당 VLM 호출 제한(VLM_TIMEOUT, 엔진이 env로 읽는 칸)을 min(models.vlm.timeout, vlm_page_sec)로(M3, 10-29 —
    한 쪽 호출이 문서×엔진 쪽당 제한보다 길게 기다리지 않게. 엔진 코드는 그대로, 값만). 같으면 덮지 않음(None = child_env 기본)."""
    from common.core.paths import child_env

    cur, lim = C.cfg().models.vlm.timeout, pc.cfg().extract.vlm_page_sec
    if cur is None or lim is None or float(lim) >= float(cur):
        return None
    return C.child_env(child_env(), VLM_TIMEOUT=str(max(1, int(lim))))


def _with_run_id(rec, run_id):
    """SI23 — runs.jsonl 줄에 이번 실행 run_id(env PARSE_RUN_ID)를 달아 run_board가 이번 실행만 거를 수 있게.
    env 없으면 그대로(run_id 칸 없음 — 옛 형식과 호환, run_board는 그때 지금처럼 마지막 기록 기준으로 폴백)."""
    return {**rec, "run_id": run_id} if run_id else rec


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
    """P0 열쇠 하나로(결과 출처 기록) = (원본 sha · 엔진 설치 버전 · 엔진 코드 지문).
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


def _isolated(eng, doc, dst, profile, tmo, py=None, env=None):
    py = py or sys.executable
    retries = int(
        pc.cfg().extract.engine_retry
    )  # S7c — 설정 객체(기본 1) · 비정상 종료만 바로 다시(10-14 rapidocr ResizeImgError 1회성 — 단독 재실행은 성공)
    for attempt in range(retries + 1):
        try:
            return _isolated_once(eng, doc, dst, profile, tmo, py, env)
        except RuntimeError:
            if attempt == retries:
                raise


def _isolated_once(eng, doc, dst, profile, tmo, py, env=None):
    import subprocess

    from common.core import resources as RS
    from common.core.paths import child_env
    from pipeline.extract import resources as PR  # 우선순위 OS 분기 한 곳

    low = bool(pc.cfg().extract.low_priority)  # 10-29 — 일괄 파싱은 낮은 우선순위(parse MCP 서비스는 끔 — 요청이 CPU를 먼저)
    # PADDLE_PYTHON은 별도 venv(.venv-paddle)라 cwd 상속에 의존하지 않고 child_env()의 PYTHONPATH(deploy/)로 `-m pipeline.extract.parse_one`을 찾게 함
    pr = RS.gated_popen(
        [py, "-m", "pipeline.extract.parse_one", "--engine", eng, "--profile", profile, str(doc), str(dst)],
        env=env if env is not None else child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **PR.low_priority_kw(low),
    )
    PR.renice_low(pr.pid, low)
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
