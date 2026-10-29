#!/usr/bin/env python3
"""OP26 — 원천 병렬 파이프라인(문서 단위, backlog docs/backlog/server.md OP26). 문서마다
받기(PARSE_TMP) → 파싱(prepare·run_all·parse_qa·represent) → 게시(대표 결과 업로드 + EDW AI.ParsingMeta 행,
cli/publish_parse.py가 쓰는 공용 함수 재사용) → 받은 파일·중간 결과 삭제를 한 단위 작업으로 묶어 작업자
N명이 동시에 — 지금(PARSE_STREAM)은 받기가 묶음 단위 순차·파싱만 내부 병렬(resources.plan() 자동)·게시는
파싱이 전부 끝난 뒤 별도 단계였다.

cli/에 두는 이유 — 게시(pipeline.load.parsing_meta)를 쓰려면 모듈 경계상 parse/ 안에는 못 둔다
(rag-parse(parse)↔rag-core(structure·load·search) 직접 import 금지, cli/check_modules.py ① — cli/는 둘 다
import할 수 있는 자리, cli/publish_parse.py와 같은 위치). 무거운 파싱 자체는 전부 기존처럼 서브프로세스로
부른다(parse/stream.py와 같은 패턴 — 모델·엔진 의존을 오케스트레이터 프로세스에 들이지 않음).

PARSE_PARALLEL_PIPELINE=1(기본 0) — cli/pipeline.py parse_module()이 --source와 함께 이 값이면 PARSE_STREAM
대신 이 경로. 기본 꺼짐인 이유: 데이터 쓰기·삭제 경로(원본 삭제·Object Storage 업로드·EDW INSERT)를 바꾸는
변경이라 '새 기능 기본 켬' 원칙의 예외(독립 검토 통과 전까지 OFF) — 보고서에 판단 근거 기록.
PARSE_PARALLEL_WORKERS(기본 common/resources.py plan()의 procs, --procs로 override 가능) — CPU 동시 문서 수.
PARSE_PARALLEL_IO_WORKERS(기본 workers*2) — 받기·게시까지 포함한 전체 파이프라인 동시 진행 수(≥ workers).

지킬 것(server.md OP26 "지킬 것" — 기존 메커니즘을 그대로 재사용, 새로 안 만듦):
  · PARSE_TMP 용량 상한(PARSE_TMP_MAX_GB) — stream.wait_for_space 재사용.
  · 같은 폴더 잠금 — stream._acquire_lock_or_refuse·cleanup_startup 재사용(한 PARSE_TMP에 이 모드·stream
    둘 중 하나만 동시에 — 서로 다른 PARSE_TMP를 쓰면 같이 돌 수 있음, 기본값은 서로 다른 하위 폴더라 안전).
  · 이름 겹치면 건너뜀 — source.plan()이 이미 이름을 de-dup해서 줌(parallel.py는 손대지 않음).
  · 실패해도 임시 파일 삭제(finally) — 문서마다 자기 작업 폴더를 통째로(stream.safe_rmtree).
  · EDW INSERT 멱등 — load.parsing_meta.apply()의 기존 키(출처+원본 전체 키) 중복 방지를 그대로(문서 1건짜리
    plan()/apply() 호출로) — 같은 문서를 두 번 게시해도 Object Storage head() 적중·EDW insert_new 건너뜀.
  · VLM 호출 상한 — common.resources.vlm_page_concurrency(워커 수, ...).

동시성 모델(문서마다 한 일):
  대기(PARSE_TMP_MAX_GB) → 받기(전역 잠금 1개로 직렬 — source.py의 manifest.jsonl이 읽기→수정→쓰기 전체를
  한 번에 다시 쓰는 방식이라 동시 호출 2개가 서로의 기록을 덮어쓸 수 있음; ponytail: 참 동시 다운로드가
  필요해지면 source.py의 manifest 쓰기 자체를 버킷·락 단위로 바꿔야 한다 — 지금은 네트워크 I/O가 파싱·VLM
  보다 훨씬 짧아 그 쪽 동시성 손실의 실익이 적다고 보고 보류) → 파싱(cpu_sem으로 동시 실행 수를 workers로
  제한) → 게시+공유 상태 합치기(단일 스레드 전용 — SQLite 연결의 스레드 제약(sqlite3 기본 check_same_thread)
  + Object Storage·EDW 쓰기 직렬화, I/O 자체는 가벼워 병목이 아님) → 삭제(그 문서의 작업 폴더 전체, finally).

  파싱 단계는 문서마다 완전히 자기 전용 폴더(PARSE_TMP/doc<N>/parse)에서 돌아 qa.json·index.json·
  engines.csv·sources.jsonl·conflicts.jsonl·runs.jsonl·PROGRESS.md·PHASE_REPORT.md(모두 --parse-dir 밑)을
  둘 이상의 서브프로세스가 동시에 덮어쓰는 경합이 없다(stream.py도 배치 1건마다 이 파일들을 통째로 다시
  쓴다 — 배치=1문서가 이미 기본값, 이 모듈은 그 '배치 1건'을 여러 개 동시에 돌리는 것뿐). P0 원본 엔진·VLM
  캐시(output/parse/raw/**)·그림 PNG(output/parse/_images/**)는 PARSE_RAW_ROOT·PARSE_IMAGES_ROOT를 건드리지 않아
  그대로 전역 공유(raw_root()·images_root()가 그 env만 보고 --parse-dir과는 무관 — represent.py·figures.py).

  대표 결과(`_rep/<문서>.json`)·`_rep/index.json`만 게시 스레드가 공유 폴더로 합친다(atomic_write — 그 밖
  사람이 보는 engines.csv·conflicts.jsonl·runs.jsonl·PROGRESS.md는 합치지 않음 — 구조화·적재·게시 어느 것도
  읽지 않는 보고용 파일이라 범위 밖, ponytail: 필요해지면 merge 추가). sources.jsonl(검색이 doc_key↔원본
  위치 조회에 씀)은 가벼워 같이 합친다.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
from common.config import settings as C  # noqa: E402 — S7e2 put(덮기 파일)
from common.core import resources as RS  # noqa: E402
from common.core.contract import jl  # noqa: E402
from common.core.paths import (  # noqa: E402
    APP_ROOT,
    atomic_write_text,
    child_env,
)
from pipeline import config as pc  # noqa: E402 — pipeline 칸(S7c — 설정 객체)
from pipeline import stream as STREAM  # noqa: E402 — 잠금·시작 시 청소·용량 대기·안전 삭제·경로 검증 재사용(새로 안 만듦)
from pipeline.extract import resources as PRS  # noqa: E402 — resolve_procs(10-14 common.core.resources에서 옮김, P만 씀)
from pipeline.extract import source as SRC  # noqa: E402

PY = sys.executable
ROOT = APP_ROOT
_PM = None  # pipeline.load.parsing_meta — 지연 import(아래 _load_pm) 뒤 캐시


def _load_pm():
    """게시(Object Storage 업로드·EDW AI.ParsingMeta 기록)에 쓰는 pipeline.load.parsing_meta — **지연
    import**(독립 검토 BLOCKER) — rag-parse 전용 이미지(Dockerfile parse 타깃, 수집 서버용)는 common/·parse/만
    들어있고 load/는 없다(rag-core 몫). 모듈 상단에서 바로 import하면 그 이미지에서 이 파일을 import하는
    순간(PARSE_PARALLEL_PIPELINE=0이어도, cli/pipeline.py가 import만 하는 경로가 생기면) ModuleNotFoundError로
    죽는다. 여기서는 run()이 맨 처음(문서 1건도 안 받은 시점)에 한 번 불러 — import가 안 되면 받기·파싱·
    삭제를 전혀 시작하지 않고 분명한 메시지로 바로 멈춘다(받고 지우고 게시 못하는 '반쪽 실행' 금지)."""
    global _PM
    if _PM is None:
        try:
            from pipeline.load import parsing_meta as PM
        except ImportError as ex:
            raise SystemExit(
                "[parallel] pipeline을 못 불러옴 — 게시(Object Storage 업로드·EDW 기록) 모듈이 이 "
                "이미지엔 없음(rag-parse 전용 이미지는 Dockerfile parse 타깃 — parse/·common/만 들어있고 load/는 "
                "rag-core 몫). PARSE_PARALLEL_PIPELINE=0으로 끄거나 rag-core·전체(rag-all) 이미지에서 돌려야 함 "
                f"— 원인: {type(ex).__name__}: {ex}"
            ) from ex
        _PM = PM
    return _PM


def tmp_root():
    """PARSE_TMP(없으면 output/_tmp_parse/parallel — stream.py 기본값 "stream"과 다른 하위 폴더라 둘이 기본값으로는
    안 겹침) — stream._validate_under_out 재사용(root를 인자로 받음, OP26 독립 검토 MINOR — 복사 안 둠)."""
    return STREAM._validate_under_out(pc.cfg().paths.parse_tmp or (ROOT / "output" / "_tmp_parse" / "parallel"), ROOT)


def _run(module, args, env):
    """pipeline.* 서브프로세스 — stream._run과 같은 패턴(gated_popen — 메모리·CPU 문 공유)."""
    cmd = [PY, "-m", module, *map(str, args)]
    rc = RS.gated_popen(cmd, cwd=ROOT, env=env).wait()
    if rc:
        raise RuntimeError(f"[parallel] 실패({rc}): {' '.join(cmd)}")


def _phase_args(ph):
    return ["--phase", str(ph).rstrip("r")] + (["--rescue"] if str(ph).endswith("r") else [])


def _merge_index(shared_rep_dir, doc_entry):
    """문서 1건의 _rep/index.json 항목을 공유 index.json에 합침(같은 문서 재처리면 옛 항목 교체) — 호출자가
    이미 publish 전용 스레드(단일)에서만 부르므로 파일 쓰기 경합이 없다(락은 호출부, 여기선 안 둠)."""
    idx_path = shared_rep_dir / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {"stack": None, "docs": []}
    data["docs"] = [d for d in data["docs"] if d["doc"] != doc_entry["doc"]] + [doc_entry]
    atomic_write_text(idx_path, json.dumps(data, ensure_ascii=False, indent=1))


def _merge_sources(shared_rep_dir, doc_entry, name):
    """sources.jsonl(검색이 doc_key↔원본 위치 조회에 씀)에 이 문서 한 줄 합침 — index.json과 같은 자리(단일
    publish 스레드)에서만 불림."""
    doc_key = doc_entry.get("doc_key")
    if not doc_key:
        return
    p = shared_rep_dir / "sources.jsonl"
    rows = {r["doc_key"]: r for r in jl(p)} if p.exists() else {}
    rows[doc_key] = {"doc_key": doc_key, "uri": doc_entry.get("uri"), "file_name": name, "engine": doc_entry.get("engine")}
    atomic_write_text(p, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows.values()))


def _record_fingerprint(source_dir, manifest_path, source_id=None, etag=None, updated_at=None):
    """O3(백로그 server.md) — 원본이 지워지기 전에(이 함수를 부르는 _publish_one이 끝나야 호출자가 지움)
    **최소** 지문(source_id·updated_at·etag·size·sha256)만 output/dedup/manifest.jsonl에 남긴다(2026-10-14
    재설계 — 근사 중복은 뺐다). parse/stream.py._record_fingerprints와 같은 함수(dedup.record_fingerprint)를
    쓴다 — 이 모듈은 문서 1건짜리 doc_dir/raw/ 안 파일 전부(보통 1개)를 돈다.
    source_id·etag·updated_at — 호출부가 manifest_row(원천의 진짜 URI·etag·updated_at, _manifest_row() 참고)
    에서 그대로 넘긴다 — load_manifest()가 file_name만으로 서로 다른 경로·접두의 같은 이름 문서를 뭉개지
    않게(독립 검토 #3 재검토).
    PARSE_STREAM_FINGERPRINT(기본 켬, =0으로 끔, stream.py와 같은 스위치) — 끄면 이전 동작과 바이트 동일.
    코디네이터 메모(10-14) — 게시(_publish_one)는 publish_exec(단일 스레드)에서만 불려 이 호출 자체는
    같은 프로세스 안에서 경합이 없다. append_manifest의 파일 잠금은 '서로 다른 프로세스' 대비용."""
    if not pc.cfg().extract.stream.fingerprint or not source_dir.exists():
        return
    from pipeline.extract import dedup as DEDUP

    for p in source_dir.iterdir():
        if p.is_file():
            DEDUP.record_fingerprint(p, manifest_path, source_id=source_id, etag=etag, updated_at=updated_at)


def _publish_one(name, doc_dir, manifest_row, rep_entry, skipped, OUT, pm_ctx):
    """게시 — cli/publish_parse.py가 쓰는 것과 같은 공용 함수(load.parsing_meta.plan/apply)를 문서 1건짜리
    batch로 호출해 SI39의 기존 키(출처+원본 전체 키) 중복 방지를 그대로 받는다(= 멱등). 호출자가 publish
    전용 단일 스레드에서만 부른다(이 함수 자신은 스레드 안전을 가정하지 않음 — PM.make_db()의 SQLite 연결이
    만든 스레드에서만 써야 해서, 또 Object Storage head→put이 같은 rep_key로 경합하면 안 돼서)."""
    PM = pm_ctx["pm"]
    shared_rep_dir = OUT / "parse" / "_rep"
    shared_rep_dir.mkdir(parents=True, exist_ok=True)
    rep_src = doc_dir / "parse" / "_rep" / f"{name}.json"
    if rep_src.exists():
        atomic_write_text(shared_rep_dir / f"{name}.json", rep_src.read_text(encoding="utf-8"))
    _merge_index(shared_rep_dir, rep_entry)
    _merge_sources(shared_rep_dir, rep_entry, name)
    PM.check_bucket_overlap(pm_ctx["bucket"], [manifest_row])  # SI39⑤ — 원천 원본 버킷과 같으면 거부(문서마다, 실제 URI 기준)
    source_dir = doc_dir / "raw"  # 게시가 아직 안 지운 원본(PM.plan()이 여기서 sha256·크기를 직접 잼) — 이 함수가 끝나야 호출자가 지운다
    rows, missing = PM.plan(
        [manifest_row],
        source_dir,
        shared_rep_dir,
        {name: rep_entry},
        {},
        skipped,
        None,
        pm_ctx["version"],
        pm_ctx["bucket"],
        pm_ctx["prefix"],
        pm_ctx["source_system"],
        pm_ctx["upload_statuses"],
        pm_ctx["parse_date"],
        None,
    )
    result = PM.apply(rows, pm_ctx["storage"], pm_ctx["db"], doc_dir, pm_ctx["prefix"]) if rows else {}
    # 독립 검토(10-14 재검토) — 지문은 게시(PM.plan·PM.apply)가 예외 없이 끝난 뒤에만 남긴다. 그보다
    # 먼저 남기면(예: PM.apply 실패) 이 문서가 매니페스트에 "원본"으로 영구히 자리 잡아, 같은 내용의
    # 다른(진짜 게시 가능한) 사본이 영영 중복으로 건너뛰어지는데 이 문서 쪽은 끝내 안 publish된다.
    _record_fingerprint(
        source_dir,
        OUT / "dedup" / "manifest.jsonl",
        source_id=manifest_row.get("uri"),
        etag=manifest_row.get("etag"),
        updated_at=manifest_row.get("updated_at"),
    )  # O3 — 게시 성공 뒤 지문(게시 전용 단일 스레드, 경합 없음)
    return result, missing


def _rep_entry_of(doc_parse_rep_dir, name):
    idx = json.loads((doc_parse_rep_dir / "index.json").read_text(encoding="utf-8"))["docs"]
    for r in idx:
        if r["doc"] == name:
            return r
    return None


def _manifest_row(name, source_root, state, is_remote, source_system):
    """게시에 쓸 manifest 행 — 원격 원본(s3://·rdb:)이면 source.py가 전역 state/manifest.jsonl에 쓴 진짜 행
    (키·uri·etag 등, SI39②) · 폴더 원본이면 source.py가 manifest을 전혀 안 쓰므로(추적할 상태가 없음, 기존
    동작) 이 자리에서 직접 구성(file_name=key=이름, uri=file://<원본 폴더>/<이름>) — cli/publish_parse.py도
    폴더 소스는 범위 밖으로 두지만(manifest 없으면 SystemExit) 이 모듈은 entries를 직접 만들어 그 제약을
    안 받는다. uri는 **원본 폴더(source_root = a.source)** 기준이어야 한다(독립 검토 CONCERN) — doc_dir(받은
    사본이 들어있는 PARSE_TMP 자리)을 가리키면 그 문서가 끝나는 즉시 safe_rmtree로 지워져 EDW에 영원히
    못 여는 경로가 남는다; 원본 폴더는 파싱이 끝나도 안 지운다(폴더 소스는 "읽기만", source.py 기존 동작)."""
    if is_remote:
        rows = [r for r in jl(state / "manifest.jsonl") if r["file_name"] == name]
        if rows:
            return rows[0]
    return {
        "file_name": name,
        "key": name,
        "uri": (Path(source_root) / name).resolve().as_uri(),
        "original_filename": name,
        "source_system": source_system,
    }


def _skipped_of(doc_dir):
    p = doc_dir / "prepared" / "skipped.jsonl"
    return {r["file"]: r["reason"] for r in jl(p)} if p.exists() else {}


def _process_one(
    i,
    name,
    fetch_one,
    state,
    tmp,
    out_parse_shared,
    engines,
    phases,
    procs,
    max_gb,
    fetch_lock,
    cpu_sem,
    publish_exec,
    pm_ctx,
    env_base,
    is_remote,
    source_system,
    source_root,
):
    """문서 1건 — 받기 → 파싱(prepare·run_all×phase·parse_qa·represent, 이 문서 전용 폴더) → 게시(단일
    스레드로 위임) → 삭제(finally, 성공·실패 모두). 실패해도 예외를 밖으로 던지지 않고 (False, 사유)를
    돌려준다 — 문서 1건의 실패가 다른 N-1건의 동시 작업을 막지 않게(에러는 삼키지 않고 호출자가 집계·출력)."""
    doc_dir = tmp / f"doc{i:04d}"
    raw_dir, prep_dir, parse_dir = doc_dir / "raw", doc_dir / "prepared", doc_dir / "parse"
    try:
        STREAM.wait_for_space(tmp, max_gb)
        with fetch_lock:  # source.py manifest.jsonl 읽기-수정-쓰기 경합 방지(모듈 docstring '동시성 모델')
            fetch_one(name, raw_dir)
        if pc.cfg().dev.parallel_test_crash and i == 0:
            os._exit(17)  # 시험용 강제 종료(try/finally도 못 도는 진짜 kill) — 재시작 뒤 cleanup_startup이 치움
        only = doc_dir / "only.txt"
        only.parent.mkdir(parents=True, exist_ok=True)
        only.write_text(name + "\n", encoding="utf-8")
        with cpu_sem:  # CPU 동시 실행 수 = workers(common/resources.plan() 그대로)
            _run("pipeline.extract.prepare", ["--src", raw_dir, "--out", prep_dir, "--only", only], env_base)
            for ph in phases:
                args = [
                    "--src",
                    prep_dir,
                    "--out",
                    parse_dir,
                    "--procs",
                    procs,
                    *_phase_args(ph),
                    "--engines",
                    engines,
                    "--docs-from",
                    only,
                ]
                if str(ph).startswith("3"):
                    args += ["--vlm-all", "--workers", "1"]  # 이 호출은 늘 문서 1건 — 문서 동시 수는 workers(바깥)가 맡음
                _run("pipeline.extract.run_all", args, env_base)
            _run("pipeline.transform.represent.parse_qa", ["--parse", parse_dir, "--src", prep_dir], env_base)
            from pipeline import stackcfg

            stack_path = stackcfg.current(out_parse_shared.parent)[0]  # S8b — 엔진 구성 활성 판의 사본(진입점이 만든 것)
            _run("pipeline.transform.represent.represent", ["--stack", stack_path, "--parse-dir", parse_dir, "--src", prep_dir], env_base)
        rep_entry = _rep_entry_of(parse_dir / "_rep", name)
        if rep_entry is None:
            return False, "represent 결과 없음(알 수 없는 오류)"
        manifest_row = _manifest_row(name, source_root, state, is_remote, source_system)
        skipped = _skipped_of(doc_dir)
        result, missing = publish_exec.submit(
            _publish_one, name, doc_dir, manifest_row, rep_entry, skipped, out_parse_shared.parent, pm_ctx
        ).result()
        if rep_entry.get("engine"):
            with (
                fetch_lock
            ):  # source.py state 파일(append)도 fetch_one의 manifest.jsonl과 같은 가족 — 같은 락으로 직렬화(독립 검토 CONCERN)
                SRC.mark_done(state, [name], is_remote)  # 원격 원본만 기록(폴더는 추적할 상태가 없음, 기존 동작과 동일)
        return True, {"engine": rep_entry.get("engine"), "publish": result}
    except Exception as ex:  # 문서 1건의 실패를 밖으로 던지지 않음(그 밖 N-1건은 계속) — 사유는 호출자가 출력
        return False, f"{type(ex).__name__}: {str(ex)[:300]}"
    finally:
        STREAM.safe_rmtree(doc_dir, tmp)  # 성공·실패 모두 — 받은 원본·회전 사본·엔진별 중간 결과·이 문서의 qa.json 등 전부


def run(a, engines):
    """cli/pipeline.py parse_module()이 PARSE_PARALLEL_PIPELINE=1 · --source일 때 부른다. a는 argparse 결과
    (parse 서브커맨드 — PARSE_STREAM 경로와 같은 a). PM을 제일 먼저(잠금·폴더·받기보다 앞에) 불러 — 게시
    모듈이 이 이미지에 없으면 문서를 하나도 안 받고·안 지우고 바로 멈춘다(독립 검토 BLOCKER, _load_pm 참고)."""
    PM = _load_pm()
    tmp = tmp_root()
    tmp.mkdir(parents=True, exist_ok=True)
    lock = STREAM._lock_path(tmp)
    STREAM._acquire_lock_or_refuse(lock)
    try:
        STREAM.cleanup_startup(tmp, keep={lock})
        return _run_all_docs(a, engines, tmp, PM)
    finally:
        lock.unlink(missing_ok=True)


def _run_all_docs(a, engines, tmp, PM):
    OUT = ROOT / "output"  # 모듈 전역 ROOT와 같은 기준(tmp_root()와 일관 — 시험이 둘 다 한 번에 바꿔 끼울 수 있게, stream.py와 같은 관례)
    out_parse = OUT / "parse"
    out_parse.mkdir(parents=True, exist_ok=True)
    is_remote = SRC.is_remote(a.source)
    if not is_remote:
        C.put(
            DOC_DIR=str(Path(a.source).resolve())
        )  # S7e2 — 덮기 파일 + 인계 키라 env에도 · 원본 위치 주소 = 이 폴더(비원격 소스, parse_module()과 같은 규칙)
    names, fetch_one, state = SRC.plan(a.source, OUT, a.source_limit, a.mode)  # 메타 조회 1번(요구사항)
    if not names:
        print("[parallel] 새로 처리할 문서 없음", flush=True)
        return
    par = pc.cfg().extract.parallel  # S7c — 설정 객체(PARSE_PARALLEL_WORKERS·IO_WORKERS 기본 None = 계산값 · "0"도 준 값이라 or 안 씀)
    workers = max(1, par.workers if par.workers is not None else PRS.resolve_procs(a.procs))
    io_workers = max(workers, par.io_workers if par.io_workers is not None else workers * 2)
    ph = getattr(a, "phases", None)
    phases = [x.strip() for x in str(ph).split(",") if x.strip()] if ph else list(pc.cfg().extract.phases)
    pc.checked("PARSE_TMP_MAX_GB")  # 디스크 상한 — 형식 틀리면 옛 float()처럼 실패(조용히 '제한 없음'이 되지 않게 — S7c1 리뷰)
    max_gb = pc.cfg().extract.cache.parse_tmp_max_gb
    vlm_conc = RS.vlm_page_concurrency(workers, a.vlm_concurrency)  # 동시 문서 수(workers) × 쪽 동시 수가 VLM_MAX_CONCURRENCY를 안 넘게
    env_base = C.child_env(
        child_env(), VLM_CONCURRENCY=str(vlm_conc), LLM_BASE_URL=None
    )  # 파싱 모듈은 LLM을 부르지 않음(기존 비병렬 경로와 같게) — 덮기 파일(S7e3 B-1)

    pub = pc.cfg().load.publish  # S7c — 설정 객체(PM_*)
    source_system = pub.source_system
    pm_ctx = {
        "pm": PM,
        "version": PM.pipeline_version(),
        "bucket": pub.bucket,
        "prefix": pub.prefix or "",
        "source_system": source_system,
        "parse_date": pub.parse_date or PM.today(),
        "upload_statuses": PM.parse_upload_statuses(",".join(pub.upload_statuses)),
    }

    fetch_lock = threading.Lock()
    cpu_sem = threading.BoundedSemaphore(workers)
    publish_exec = ThreadPoolExecutor(max_workers=1)  # SQLite 스레드 제약 + EDW·Object Storage 쓰기 직렬화(모듈 docstring)
    # SQLite 연결은 만든 스레드에서만 써야 하므로(기본 check_same_thread) make_storage()·make_db()도 publish_exec의
    # 그 유일한 스레드 안에서(이후 모든 _publish_one도 같은 스레드에서 돈다 — ThreadPoolExecutor(max_workers=1)은 수명 내내 같은 스레드 하나)
    pm_ctx["storage"], pm_ctx["db"] = publish_exec.submit(lambda: (PM.make_storage(), PM.make_db("write"))).result()
    ok = fail = 0
    errors = []
    try:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=io_workers) as pool:
            futs = {
                pool.submit(
                    _process_one,
                    i,
                    name,
                    fetch_one,
                    state,
                    tmp,
                    out_parse,
                    engines,
                    phases,
                    "1",
                    max_gb,
                    fetch_lock,
                    cpu_sem,
                    publish_exec,
                    pm_ctx,
                    env_base,
                    is_remote,
                    source_system,
                    a.source,
                ): name
                for i, name in enumerate(sorted(names))
            }
            for fut in futs:
                good, info = fut.result()
                if good:
                    ok += 1
                else:
                    fail += 1
                    errors.append((futs[fut], info))
        print(
            f"[parallel] 끝 — 대상 {len(names)}개 중 대표 결과 {ok}건 · 실패 {fail}건"
            f" · {time.time() - t0:.1f}초(워커 {workers}·io {io_workers})",
            flush=True,
        )
        for n, e in errors:
            print(f"[parallel] 실패 — {n}: {e}", flush=True)
    finally:
        if hasattr(pm_ctx["db"], "close"):
            publish_exec.submit(pm_ctx["db"].close).result()  # 만든 스레드(publish_exec)에서 닫음(sqlite3 스레드 제약)
        publish_exec.shutdown(wait=True)
    STREAM.storage_report(out_parse)


if __name__ == "__main__":
    utf8_stdout()
    print("[parse_parallel] CLI 없음 — cli/pipeline.py parse(--source ... , env PARSE_PARALLEL_PIPELINE=1)로 부른다")
