#!/usr/bin/env python3
"""파이프라인 진입점 — 두 단계를 나눠 부른다(요청 문장 → 명령 대응표는 AGENTS.md "요청 → 명령").

단계 1 · 비교(기술 스택 고르기)
  compare-parse   여러 파싱 엔진 비교: run_all → parse_qa → 보고서(엔진 × 형식·선정 후보)
  compare-all     파싱 + 데이터 구조화(청킹·임베딩·그래프) + 검색까지 전체 조합 비교 → 보고서·문항 탐색기(답변 비교 단계는
                  10-13 답변 경로 통일 4단계로 archive — 답변 품질은 dev_tools/perform_test/answer_stage/run.py, rag_qa만)
단계 2 · 고정 스택(정해진 기술로 실제 파이프라인 + 기본 테스트)
  set-stack       엔진 구성 바꾸기(--from-selection = 단계 1 선정 결과 그대로 · --parse ".pdf_text=pymupdf,pdfplumber;.docx=office" 직접 ·
                  --activate N 되돌리기) — 서버 = 판 표 struct.stack_version 새 판·활성(--reason 필수), PC = 파일(S8b — docs/architecture/pipeline_stack.md)
  show-stack      지금 엔진 구성(서버 = 활성 판 + 최근 판)
  set-sources · show-sources  원천 목록(서버 = 판 표 struct.source_version, PC = 파일) — --file·--activate·--check-columns
  run-stack       스택 엔진만 파싱 → 대표 파싱(문서마다 하나, modules/parse/represent.py) → 구조화·벡터화·그래프(modules/structure/build_bundle.py)
  parse · structure · load  모듈 1회 실행(트리거) — 앞 모듈 끝 표시(_DONE.json)를 보고 이어 받음, 새 입력 없으면 건너뜀(docs/architecture.md)
  (ask · test-stack — 검색 명령은 S5(10-26, T-15)에 python -m mcp_server.cli.ask로 옮김: 파이프라인 CLI가 검색 코드를 import하지 않게)
산출 위치: output/parse(파싱) · output/parse/_rep(대표) · output/edw/bundle(구조화) · output/report(보고서) · output/stack_test.md · output/RUNLOG.md(명령 요약)
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.config import settings as C  # common 칸(S7c — 설정 객체 · cfg()·given()·render())
from common.core.paths import APP_ROOT, PKG_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체 · cfg()·given())

HERE = Path(__file__).resolve().parent

ROOT = PKG_ROOT  # common/(S6a — 옛 common_tools/와 같은 깊이) — 하위 프로세스 cwd·저장소 문서 찾기용(ROOT.parent = deploy/)
OUT = Path(
    pc.cfg().paths.out_root or (APP_ROOT / "output")
)  # S7c — 설정 객체(import 때 한 번) · D2 — 격리 빌드(stack_matrix.py sources)가 데이터셋마다 다른 out을 쓰게
PY = sys.executable
_STACK: dict = {}


def _stack():
    """엔진 구성(사전) — 프로세스마다 한 번(pipeline/stackcfg.py: 서버 = 판 표 활성 판·PC = 파일 → 이미지에 없는 엔진 거부 → 판 번호를
    STACK_VERSION 칸으로 자식에 넘김 — 이미 받았으면 그 판, pl-32). 서버에서 판 표를 못 읽으면 종료 4, 없는 엔진이면 종료 2."""
    if "v" not in _STACK:
        from pipeline import stackcfg

        stackcfg.current()
        _STACK["v"] = pc.stack()
    return _STACK["v"]


def _stack_arg():
    """represent·build_bundle에 넘길 판 번호 인자(PC 파일이면 없음 — 자식도 파일을 읽음)."""
    v = _stack().get("version_id")
    return [] if v is None else ["--stack-version", str(v)]


def sh(module, *args, check=True):
    cmd = [PY, "-m", module, *map(str, args)]
    print("$ " + " ".join(cmd), flush=True)
    from common.core import resources as RS
    from common.core.paths import child_env

    rc = RS.gated_popen(
        cmd, cwd=APP_ROOT, env=child_env()
    ).wait()  # child_env() — PYTHONPATH(deploy/)로 `-m data_pipeline.x.y` 해석 보장 · cwd=APP_ROOT(런타임 루트) — ROOT(data_pipeline/ 코드 루트)로 하면 --src 상대경로가 거기 기준으로 풀려 못 찾음(FS v4 회귀)
    if check and rc:
        raise SystemExit(f"실패({rc}): {' '.join(cmd)}")
    return rc


def _set_engine_scope_default(explicit_engines):
    """PARSE_ENGINE_SCOPE 기본값 — 이미 설정돼 있으면(사용자) 그대로. 없으면: --engines를 명시했으면 all(명시 엔진
    존중 — 형식별로 더 좁히지 않음, 독립 검토 BLOCK 2), 비웠으면(생산 기본 트리거) stack(무거움 해소, 2026-10-07)."""
    if pc.cfg().extract.engine_scope is None:  # S7e2 — 설정에 없을 때만(옛 env setdefault) · put = 덮기 파일(이 프로세스·하위 프로세스)
        C.put(PARSE_ENGINE_SCOPE="all" if explicit_engines else "stack")


def parse_docs(src, engines, procs):
    sh("pipeline.extract.run_all", "--src", src, "--procs", procs, *(["--engines", engines] if engines else []))


# ── 야간 배치(새벽 파싱 — GPU가 비는 시간, LLM 호출 없음) ─────────
def _until(deadline):
    """'HH:MM'(오늘, 이미 지났으면 내일) → 남은 초."""
    import datetime as dt

    now = dt.datetime.now()
    h, m = map(int, deadline.split(":"))
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if end <= now:
        end += dt.timedelta(days=1)
    return (end - now).total_seconds()


def _run_until(args, env, sec):
    """마감까지만 실행 — 넘으면 프로세스 묶음(--procs 자식 포함)을 끝냄. 다음 밤은 문서 대장에 파싱 성공 행이 없는 문서를 다시 고른다(pl-32 — 마감에 걸린 밤의 문서는 PR 4 전까지 반복될 수 있음).
    args[0] = 모듈 점 표기(예: pipeline.extract.run_all)."""
    cmd = [PY, "-m", str(args[0]), *map(str, args[1:])]
    print("$ " + " ".join(cmd), flush=True)
    from common.core import resources as RS
    from pipeline.extract import resources as PR  # 프로세스 묶음(OS 분기 한 곳)

    p = RS.gated_popen(cmd, cwd=APP_ROOT, env=env, **PR.group_kw())  # cwd=APP_ROOT(런타임 루트) — sh()와 같은 이유
    try:
        return p.wait(timeout=max(1, sec))
    except subprocess.TimeoutExpired:
        PR.kill_group(p)
        return None


def night(a):
    """새벽 배치: 파싱 → 대표 파싱 → publish(OS+EDW) → 구조화·임베딩 → PG 적재.
    --no-structure면 파싱+publish만. --no-publish로 OS+EDW publish 건너뜀.
    GPU 모델은 API로만(VLM_*·EMBED_*), LLM(LLM_*)은 부르지 않는다 — 요약은 발췌만. 마감(--deadline)을 넘으면 멈춤 — 다음 밤은 문서 대장 기준(성공 행 없는 문서)으로 다시 고름(pl-32).
    RV5(10-09): deploy/host/scripts/trigger.sh night(OP13 정본, compose 여러 컨테이너용)와는 배포 모양이 달라 따로 둠 — 이 함수는
    단일 컨테이너·Docker 밖 직접 실행(AGENTS.md 지시표·requirements.md S8 cron 예시)에서 쓰임, 호출처 있음(삭제 대상 아님)."""
    connect(a)
    st = _stack()
    engines = a.engines or ",".join(_engines_of(st))
    _set_engine_scope_default(a.engines)  # PE1 — night도 생산 경로(서버 entrypoint full)라 같은 기본
    from common.core import resources as RS

    vlm_conc = RS.vlm_page_concurrency(a.workers, a.vlm_concurrency)  # 문서 동시 수 × 쪽 동시 수가 VLM_MAX_CONCURRENCY를 넘지 않게
    from common.core.paths import child_env

    night_names = dict(
        VLM_CONCURRENCY=str(vlm_conc), EDW_SUMMARY_LLM="0", LLM_BASE_URL=None
    )  # 야간 배치에서는 LLM 호출 차단(그래프·요약·답변 모두)
    env = C.child_env(child_env(), **night_names)  # 설정 이름은 덮기 파일로(S7e3 B-1 — env dict의 설정 이름은 자식이 안 읽음)
    log, t0 = [], time.time()
    stopped = None
    source = getattr(a, "source", None)
    if source:
        from pipeline.extract import source as SRC

        local, names, state = SRC.resolve(source, OUT, getattr(a, "source_limit", 0), getattr(a, "mode", "prod"))
        env = C.child_env(child_env(), **night_names)  # SOURCE_MANIFEST가 설정된 후 재생성
        sel = OUT / "parse" / "_source" / "selected.txt"
        sel.write_text("\n".join(names) + "\n", encoding="utf-8")
        _run_until(["pipeline.extract.dedup", "--src", local, "--out", OUT / "dedup"], env, _until(a.deadline) - 120)
        keep = set((OUT / "dedup" / "keep.txt").read_text(encoding="utf-8").splitlines())
        only = OUT / "parse" / "_source" / "only.txt"
        only.write_text("\n".join(n for n in names if n in keep) + "\n", encoding="utf-8")
        _run_until(["pipeline.extract.prepare", "--src", local, "--out", a.src, "--only", only], env, _until(a.deadline) - 120)
        a.docs_from = only
    else:
        a.docs_from = None
    left = _until(a.deadline)
    if left < 300:
        stopped = f"파싱 시작 전 마감 {a.deadline} 도달"
    else:
        args = ["pipeline.extract.run_all", "--src", a.src, "--procs", a.procs, "--workers", a.workers, "--engines", engines]
        if a.docs_from:
            args += ["--docs-from", str(a.docs_from)]
        rc = _run_until(args, env, left - 120)
        log.append("파싱: " + ("완료" if rc == 0 else "마감으로 중단" if rc is None else f"종료 코드 {rc}"))
        if rc is None:
            stopped = f"파싱 도중 마감 {a.deadline}"
    if not a.no_structure and not stopped:
        for args in (
            ["pipeline.transform.represent.parse_qa", "--src", a.src],
            ["pipeline.transform.represent.represent", *_stack_arg(), "--src", a.src],
        ):
            left = _until(a.deadline)
            rc = _run_until(args, env, left - 60) if left > 120 else None
            log.append(f"{args[0]}: " + ("완료" if rc == 0 else "마감으로 중단" if rc is None else f"종료 코드 {rc}"))
            if rc != 0:
                stopped = stopped or f"{args[0]}에서 멈춤"
                break
            if args[0] == "pipeline.transform.represent.represent":
                write_mark("parse", src=str(a.src), engines=engines.split(","), by="night")
        if source and not stopped:
            from pipeline.extract import source as SRC

            if SRC.is_remote(source):
                SRC.finish(state, local, OUT / "parse" / "_rep" / "index.json")
        if not stopped and not getattr(a, "no_publish", False):
            left = _until(a.deadline)
            rc = _run_until(["pipeline.load.publish_parse_result", "--apply", "--out", str(OUT)], env, left - 60) if left > 60 else None
            log.append("publish: " + ("완료" if rc == 0 else "마감으로 중단" if rc is None else f"종료 코드 {rc} — 구조화는 계속"))
        if not stopped:
            left = _until(a.deadline)
            args = [
                "pipeline.transform.structure.build_bundle",
                "--src",
                a.src,
                "--embed",
                pc.cfg().transform.structure.embed or st.get("embed", "api"),
                *_stack_arg(),
                "--summary",
                "auto",
            ]
            rc = _run_until(args, env, left - 60) if left > 60 else None
            log.append("build_bundle: " + ("완료" if rc == 0 else "마감으로 중단" if rc is None else f"종료 코드 {rc}"))
            if rc != 0:
                stopped = stopped or "build_bundle에서 멈춤"
            else:
                pm = read_mark("parse") or {}
                write_mark("structure", from_run=pm.get("run_id"), by="night")
                load_tables_db(env)
        targets = [("pipeline.load.pgvector_load", "deploy"), ("pipeline.load.pgvector_load", "load")] if a.pg else []
        if targets and not stopped:
            for args in map(list, targets):
                rc = _run_until(args, env, max(60, _until(a.deadline) - 30))
                log.append(f"{' '.join(args)}: " + ("완료" if rc == 0 else f"멈춤({rc})"))
                if rc != 0:
                    break
    md = [
        f"# 야간 배치 {time.strftime('%Y-%m-%d %H:%M')} — {(time.time() - t0) / 60:.0f}분",
        "",
        f"엔진: {engines}",
        f"VLM 동시 쪽 {vlm_conc}(요청 {a.vlm_concurrency}) · 동시 문서 {a.workers} · CPU 프로세스 {a.procs} · 마감 {a.deadline} · LLM 호출 없음",
        "",
    ]
    md += [f"- {x}" for x in log] + (
        [
            f"- **멈춤: {stopped}** — 다음 밤은 문서 대장에 성공 행이 없는 문서를 다시 고름(PR 4 전에는 이 밤의 문서가 반복될 수 있음 — pl-32)"
        ]
        if stopped
        else ["- 전부 끝남"]
    )
    md += ["", "진행·결과: output/parse/PROGRESS.md · output/RUNLOG.md"]
    Path("output").mkdir(exist_ok=True)
    Path("output/NIGHT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    from common.core.runlog import note

    note("야간 배치: " + " · ".join(log) + (f" · 멈춤: {stopped}" if stopped else " · 전부 끝남"))


# ── 단계 1 ───────────────────────────────────────────────────
def compare_parse(a):
    engines = a.engines
    if engines == "candidates":  # 스택의 선정 엔진 + 사용자 후보 목록(stack.json candidates)
        st = _stack()
        engines = ",".join(_engines_of(st))
        print(f"비교 엔진: {engines}")
    if not a.skip_parse:
        parse_docs(a.src, engines, a.procs)
    sh("pipeline.transform.represent.parse_qa", "--src", a.src)
    sh("pipeline.eval.report")
    print("→ output/report/report.html(파싱 결과 탭: 엔진 × 형식 · 최종 엔진 조합 후보) · output/parse/selection.json")


def compare_all(a):
    compare_parse(a)
    sh("pipeline.eval.auto_questions", "--src", a.src, check=False)
    sh("pipeline.eval.run_combo", "--parse-dir", "output/parse", "--src", a.src)
    # 10-13 답변 경로 통일 4단계 — run_answers·verify_key(옛 §3-6 답변 평가 CLI) archive, 답변 품질은
    # dev_tools/perform_test/answer_stage/run.py(서빙되는 Answer Agent rag_qa)로.
    sh("pipeline.eval.report")
    sh("pipeline.eval.explorer")
    print("→ output/report/report.html(조합 순위) · output/report/explorer.html(문항별 결과)")


# ── 단계 2 ───────────────────────────────────────────────────
def _server():
    from common.core import paths

    return not paths.LOCAL_RUN


def _by(a):
    """누가 — --by(서버 절차는 늘 줌 — 컨테이너 안 OS 사용자는 이미지 계정이라 사람을 가리지 못함)."""
    import getpass

    return a.by or getpass.getuser()


def _engines_of(st):
    """parse ∪ candidates 엔진(정렬) — stackcfg.engines_of 하나로(VS8b R-8)."""
    from pipeline.stackcfg import engines_of

    return engines_of(st)


def _need_reason(a):
    if not a.reason:
        raise SystemExit("[판 표] 서버에서 판을 바꿀 때는 --reason <이유> 필수(판 행에 남음 — 누가는 --by, 없으면 OS 사용자)")


def _put_or_activate(kind, a, name=None, body=None, check=None, based_on=None):
    """서버: 새 판 + 활성(같은 body면 그 판) 또는 --activate N — 한 트랜잭션. check(body)는 활성으로 만들기 전 검사(엔진·열).
    based_on — body를 만들 때 읽은 활성 판 번호(set-stack은 지금 판을 고쳐 새 판을 만듦): 쓰기 트랜잭션에서 활성 판을 잠그고 다시 봐서 그사이
    다른 사람이 판을 바꿨으면 덮지 않고 종료 2(VS8b R-1 — 읽기-고치기-쓰기). 동시에 넣다 진 쪽(활성 하나·같은 body 제약)도 같은 안내로 종료 2."""
    from sqlalchemy.exc import IntegrityError

    from common.store.db import cfgtables as CT

    _need_reason(a)
    race = (
        f"[판 표] 다른 사람이 방금 {CT.KINDS[kind]} 판을 바꿈 — 이번 변경은 넣지 않음. "
        f"show-{'stack' if kind == 'stack' else 'sources'}로 지금 판을 본 뒤 다시"
    )
    try:
        with CT.connect() as conn:
            with conn.begin():
                if based_on is not None and CT.lock_active(kind, conn) != based_on:
                    print(race, file=sys.stderr, flush=True)
                    raise SystemExit(2)
                if a.activate is not None:
                    body = CT.version_body(kind, a.activate, conn)
                    if body is None:
                        raise SystemExit(f"[판 표] {CT.KINDS[kind]}에 판 {a.activate} 없음")
                    if check:
                        check(body)
                    v, new = CT.activate(kind, a.activate, _by(a), conn), False
                else:
                    v, new = CT.put(kind, name, body, _by(a), a.reason, conn)
    except IntegrityError as e:
        if not any(
            c in str(e.orig) for c in ("_active", "body_sha")
        ):  # 활성 하나·같은 body 제약만 동시 변경(리뷰 S9) — 그 밖 제약은 원래 오류
            raise
        print(race, file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    msg = (
        f"[판 표] {CT.KINDS[kind]} 판 {v} 활성"
        + (" (새 판)" if new else " (있던 판 — 같은 body: 판 행의 이름·이유는 그대로, 이번 이유는 실행 기록에만)")
        + f" · {_by(a)} · 이유: {a.reason}"
    )
    print(msg)
    from common.core.runlog import note

    note(msg)  # 활성 옮김 이유는 실행 기록에(판 행은 고치지 않음 — activated_at·_by만)


def set_stack(a):
    """엔진 구성 바꾸기(S8b — D-031): 서버 = 판 표 struct.stack_version에 새 판 + 활성(같은 body면 그 판을 활성으로, 한 트랜잭션 — --reason
    필수) · --activate N = 그 판을 다시 활성(되돌리기) · PC = 파일(common.paths.stack_file — 지금처럼). 이미지에 없는 엔진은 거부(종료 2)."""
    import importlib.util

    from common.store.db import cfgtables as CT

    if importlib.util.find_spec("pipeline.extract.engines") is None:
        raise SystemExit(
            "[set-stack] 이 이미지에는 엔진 등록부가 없어 엔진을 검사할 수 없음 — data-pipeline 이미지에서(이 이미지는 show-stack만)"
        )
    from pipeline import stackcfg

    if a.activate is not None:
        if not _server():
            raise SystemExit("[set-stack] PC는 파일 — 판 번호 없음(되돌리기는 git으로)")
        _put_or_activate("stack", a, check=lambda body: stackcfg.require_engines(body, f"판 {a.activate}"))
        return show_stack(a)
    if _server() or CT.pc_file("stack").exists():
        cur = CT.active("stack")
        st, name = dict(cur.body), a.name or cur.name
    else:  # PC 파일이 아직 없음 — 옛처럼 새로 만듦
        st, name = {}, a.name or time.strftime("stack-%Y%m%d")
    if a.from_selection:
        sel = json.loads((OUT / "parse" / "selection.json").read_text(encoding="utf-8"))
        st["parse"] = {f: es for f, es in (sel.get("final") or {}).items() if es}
        st["source"] = "selection.json(단계 1 최종 엔진 조합)"
    if a.parse:
        st["parse"] = dict(st.get("parse") or {})
        for part in a.parse.split(";"):
            if "=" in part:
                f, es = part.split("=", 1)
                st["parse"][f.strip()] = [e.strip() for e in es.split(",") if e.strip()]
        st["source"] = "직접 지정"
    for k in ("chunk", "embed", "graph", "retrieve"):
        if getattr(a, k):
            st[k] = getattr(a, k)
    if a.k:
        st["k"] = a.k
    st.setdefault("chunk", "structure")
    st.setdefault("embed", "api" if C.cfg().models.embed.base_url else "bge-m3")
    st.setdefault("graph", "table+entity")
    st.setdefault("retrieve", "hybrid")  # 기본 하이브리드(코사인 + BM25 + 드문 ID, 사용자 결정 2026-10-01 — 코사인만은 수치·ID 질문에 약함)
    st.setdefault("k", 10)
    if not st.get("parse"):
        raise SystemExit("파싱 엔진이 비어 있음 — --from-selection 또는 --parse 지정")
    try:
        CT.check_body("stack", st)
    except ValueError as e:
        raise SystemExit(f"[set-stack] {e}") from None
    stackcfg.require_engines(st, "set-stack")
    if _server():
        _put_or_activate("stack", a, name, st, based_on=cur.version_id)  # VS8b R-1 — 읽은 판 위에서만 바꿈
    else:
        f = CT.pc_file("stack")
        doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        doc = {**{k: v for k, v in doc.items() if k not in st}, **st, "name": name, "updated": time.strftime("%Y-%m-%d %H:%M")}
        f.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        CT._CACHE.pop("stack", None)
    show_stack(a)


def _history(kind, n):
    from common.store.db import cfgtables as CT

    with CT.connect() as conn:
        rows = CT.history(kind, conn, n)
        conn.rollback()
    print(f"-- 최근 판 {len(rows)}개(판 · 활성 · 이름 · sha · 넣은 때·사람 · 이유 · 마지막 활성 때·사람) --")
    for r in rows:
        made = f"{r['created_at']:%Y-%m-%d %H:%M} {r['created_by'] or ''}"
        act = f"{r['activated_at']:%Y-%m-%d %H:%M} {r['activated_by'] or ''}" if r["activated_at"] else ""
        print(
            f"  {r['version_id']} {'*' if r['is_active'] else ' '} {r['name']} · {r['body_sha'][:12]} · {made} · {r['reason'] or ''} · {act}"
        )


def show_stack(a=None):
    """지금 엔진 구성 — 서버 = 판 표 활성 판(+ 최근 판 --history N), PC = 파일. mcp-server 이미지에서도 됨(등록부 안 씀)."""
    from common.store.db import cfgtables as CT

    cur = CT.active("stack", refresh=True)
    st = cur.body
    print(f"스택 {cur.name} ({st.get('source', '')}) · {cur.label()}")
    print("| 형식 | 파싱 엔진(우선순위) |\n|---|---|")
    for f, es in sorted(st["parse"].items()):
        print(f"| {f} | {' → '.join(es)} |")
    print(
        f"청킹 {st['chunk']} · 임베딩 {st['embed']} · 그래프 {st['graph']} · 검색 {st['retrieve']} · 상위 k {st['k']}"
        + (f" · 비교 후보 {', '.join(st['candidates'])}" if st.get("candidates") else "")
    )
    if _server() and getattr(a, "history", 0):
        _history("stack", a.history)


def set_sources(a):
    """원천 목록 바꾸기(S8b — D-031): --file <json>(목록 — 모양은 sources.py 검사 그대로) → 서버 = 판 표 struct.source_version 새 판 + 활성
    (--reason 필수) · PC = 파일(common.paths.sources_file) · --activate N 되돌리기 · --check-columns = 회사 DB INFORMATION_SCHEMA로 표·열 이름이
    있는지(값 안 읽음 — 선택, Q9)."""
    from common.store.db import cfgtables as CT

    check = None
    if a.check_columns:
        from pipeline.extract import rdb_discover

        def check(body):
            bad = rdb_discover.column_problems(body)
            if bad:
                raise SystemExit("[set-sources] 원천 표·열 확인 실패: " + " · ".join(bad))
            print(f"[set-sources] 원천 표·열 확인 — {len(body)}개 원천 모두 있음")

    if a.activate is not None:
        if not _server():
            raise SystemExit("[set-sources] PC는 파일 — 판 번호 없음")
        _put_or_activate("sources", a, check=check)
        return show_sources(a)
    if not a.file:
        raise SystemExit("[set-sources] --file <원천 목록 json> 또는 --activate <판 번호>")
    body = json.loads(Path(a.file).read_text(encoding="utf-8"))
    try:
        CT.check_body("sources", body)
    except ValueError as e:
        raise SystemExit(f"[set-sources] {e}") from None
    if check:
        check(body)
    if _server():
        _put_or_activate("sources", a, a.name or Path(a.file).stem, body)
    else:
        CT.pc_file("sources").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        CT._CACHE.pop("sources", None)
    show_sources(a)


def show_sources(a=None):
    from common.store.db import cfgtables as CT

    cur = CT.active("sources", refresh=True)
    print(f"원천 목록 {cur.label()}")
    for e in cur.body:
        print(f"  {'켜짐' if e.get('enabled', True) else '꺼짐'} {e['name']} · {e['table']} · 열 {len(e['columns'])}개")
    if _server() and getattr(a, "history", 0):
        _history("sources", a.history)


# ── 모듈(트리거 실행 — docs/architecture.md) ──────────────────────
# 파싱 → 구조화 → 적재를 따로 부른다(각 Docker 컨테이너 1회 실행). 앞 모듈의 끝 표시(_DONE.json)를 보고 시작하고,
# 앞 결과가 바뀌지 않았으면 아무것도 안 하고 끝낸다(트리거·나중의 새벽 배치가 여러 번 불러도 안전).
# pl-32(10-30) — 이것은 한 새벽 배치·트리거 실행 안에서 모듈 사이 인계(앞 모듈이 이번에 낸 결과가 있나)이지 문서 결과 재사용이 아니다 — 남김.
from common import CONTRACT, FINGERPRINT  # noqa: E402 — 인계 형식 버전 · common 코드 지문(이미지 버전 어긋남 확인)

MARK = {
    "parse": OUT / "parse" / "_rep" / "_DONE.json",
    "structure": OUT / "edw" / "bundle" / "_DONE.json",
    "load": OUT / "edw" / "_LOADED.json",
}


def read_mark(name):
    f = MARK[name]
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def write_mark(name, **kw):
    m = {
        "module": name,
        "contract": CONTRACT,
        "common": FINGERPRINT,
        "run_id": time.strftime("%Y%m%d-%H%M%S"),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **kw,
    }
    MARK[name].parent.mkdir(parents=True, exist_ok=True)
    MARK[name].write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{name}] 끝 표시 → {MARK[name]} (run_id {m['run_id']})", flush=True)


def load_tables_db(env=None):
    """AD23 leftover — 구조화 뒤 _rep의 tables_std를 doc_table·doc_cell로(modules/load/structured.py tables 명령,
    find_table_cells·aggregate.table_cell_list가 쓸 데이터). X1(로컬 정형 저장소) 옵트인이라 STRUCT_BACKEND·
    STRUCT_DB 둘 다 없으면 건너뜀(기존과 바이트 동일 — 그 둘을 안 쓰면 do_aggregate().struct()도 안 돌아 표 칸
    질문 라우팅 자체가 꺼져 있음). PARSE_TABLE_DB=0이면 꺼짐(기본 켬, OP11). _rep가 아직 없으면 건너뜀.
    재실행 안전(structured.py load_tables_docs가 같은 table_key를 지우고 다시 씀) — 보조 기능(X1처럼, 서버
    runbook의 load·link와 같은 결합도)이라 실패해도 로그만 남기고 삼킨다(engine-qa BLOCK① — structure·night·
    run-stack 전체를 절대 막지 않음, 값은 안 돌려줌)."""
    if not pc.cfg().transform.represent.table_db or not (
        C.given("STRUCT_BACKEND") or C.given("STRUCT_DB")
    ):  # S7c — given: 준 값만(STRUCT_BACKEND 기본 pg는 준 값이 아님)
        return
    rep = OUT / "parse" / "_rep"
    if not rep.exists():
        return
    try:
        from common.core import resources as RS
        from common.core.paths import child_env

        rc = RS.gated_popen(
            [PY, "-m", "pipeline.load.structured", "tables", "--rep", str(rep)], cwd=APP_ROOT, env=env or child_env()
        ).wait()  # child_env() — PYTHONPATH(deploy/) 보장(env=None 기본 호출 포함) · cwd=APP_ROOT — 위 sh()와 같은 이유
        print(
            f"[tables] doc_table·doc_cell 적재(AD23) — 종료 코드 {rc}" + ("" if rc == 0 else " (집계·검색은 그대로, 표 칸 질문만 영향)"),
            flush=True,
        )
    except Exception as e:
        print(
            f"[tables] doc_table·doc_cell 적재 실패(무시 — 집계·검색·structure·night·run-stack은 계속) {type(e).__name__}: {e}", flush=True
        )
    return


def need(prev, name, force, extra=None):
    """앞 모듈 끝 표시 확인 → 이번 모듈이 할 일이 있는지. 없으면 종료 코드 3(앞 모듈 먼저), 이미 처리했으면 None(건너뜀).
    extra(GH1-06) — 대상·설정 지문(host:port/db/schema·code_fp 등, 비밀값은 안 들어감): run_id가 같아도
    저장된 값과 다르면 다시 처리한다(조용히 다른 대상에 빈 적재·바뀐 설정을 건너뛰어 성공처럼 보이는 일 방지)."""
    m = read_mark(prev)
    if not m:
        print(f"[{name}] {prev} 결과(끝 표시 {MARK[prev]})가 없음 — {prev} 모듈을 먼저 실행", flush=True)
        raise SystemExit(3)
    if m.get("contract") != CONTRACT:
        print(
            f"[{name}] {prev} 결과의 계약 버전 {m.get('contract')} ≠ {CONTRACT}(그 결과 run_id {m.get('run_id')}·{m.get('finished_at')}) — "
            "두 모듈 이미지를 같은 커밋 판으로(SI31: 서버에 옛 판이 남았으면 `podman images | grep rag-`로 태그 확인) 또는 앞 모듈 다시 실행",
            flush=True,
        )
        raise SystemExit(3)
    if m.get("common") and m["common"] != FINGERPRINT and not pc.cfg().dev.allow_common_mismatch:
        # 토큰·임베딩 호출·ID 규칙(common/)이 다른 커밋의 이미지 — 색인과 검색 규칙이 조용히 어긋나지 않게 멈춤
        print(
            f"[{name}] {prev} 모듈의 공통 코드 지문 {m['common']} ≠ 이 이미지 {FINGERPRINT}(그 결과 run_id {m.get('run_id')}) — 두 이미지를 같은 커밋으로 빌드"
            "하거나 덧씌우기(compose.patch.yml)를 두 모듈에 같이 연결 · 덧씌우기로 common/이 바뀌었으면 앞 모듈 다시 실행(확실하면 ALLOW_COMMON_MISMATCH=1)",
            flush=True,
        )
        raise SystemExit(3)
    mine = read_mark(name)
    if mine and mine.get("from_run") == m["run_id"] and mine.get("extra") == extra and not force:
        print(f"[{name}] 새 {prev} 결과 없음(run_id {m['run_id']} 이미 처리, 대상·설정도 그대로) — 건너뜀(다시 하려면 --force)", flush=True)
        return None
    return m


def _left(a):
    return _until(a.deadline) if getattr(a, "deadline", None) else 10**7


def _registry_new_names(out_dir, names):
    """OP9 — 문서 대장(이미 있는 doc_registry, 지난 build 결과)과 비교해 이번 밤 파싱할 이름만(REG.nightly_plan —
    독립 검토 BLOCK 반영 10-08: new(처음 보는 doc_key) + unchanged·touched(AD17① — 원본 바이트는 같고 날짜만
    바뀜)인데 아직 성공 못한 doc_key(status != 'parsed' — 반복 실패·'seen' 모두 매일 재시도) · 성공해서 안 바뀐
    문서는 뺌(다시 할 필요 없음, touched도 포함 — 원본 바이트가 안 바뀌었으니 재파싱 대상이 아님) · changed는
    기본 전부 빠짐(자동 재파싱 안 함, OP1) · deleted는 observed에 없어 자동으로 빠짐).
    OP14 — env `AUTO_REPARSE_CHANGED=1`이면 changed 전체를 REG.nightly_plan의 reparse_keys로 넘겨 다음 배치
    대상에 포함(새 run_id로 재파싱 — 결과는 run_id별로 쌓여 옛 결과·이력이 그대로 남음). 기본(0)은 전과 동일(탐지·보고만).
    문서 대장을 못 열면 _no_registry()(서버 run_mode prod = 종료 4, 그 밖 = None — 필터 없음, pl-32 10-30)."""
    from common.store import registry as REG

    db = REG.try_open_db()
    if db is None:
        return _no_registry()
    try:
        observed = REG.scan(out_dir)
        auto_reparse = pc.cfg().extract.auto_reparse_changed
        reparse_keys = set(REG.diff_against(db, observed)["changed"]) if auto_reparse else None
        new_names = set(REG.nightly_plan(db, observed, reparse_keys=reparse_keys)["parse_names"])
    except Exception:
        return None
    finally:
        db.close()
    return {n for n in names if n in new_names}


def _no_registry():
    """문서 대장을 못 열 때(pl-32 사용자 10-30 — 실행을 넘는 문서 고르기는 문서 대장 하나만): run_mode prod(서버)는 종료 4(인프라 없음 —
    전체를 다시 파싱하지 않음), 그 밖(PC·DOC_REGISTRY=0)은 이력 없이 받은 목록 그대로(None) + 로그 한 줄."""
    if C.cfg().store.run_mode == "prod":
        print("[parse] 문서 대장(doc_registry)을 열지 못함 — run_mode prod는 멈춤(종료 4, 전체 재파싱 안 함)", file=sys.stderr, flush=True)
        raise SystemExit(4)
    print("[parse] 문서 대장 없음(DOC_REGISTRY=0 또는 연결 안 됨) — 이력 없이 받은 목록 그대로 처리", flush=True)
    return None


def _registry_unparsed(names):
    """문서 대장에 파싱 성공 행(status parsed)이 없는 이름만 — 순서: 대장에 없거나 아직 시도 전(seen)인 문서(이름순) 먼저, 그다음 실패 문서
    (마지막 시도가 오래된 것부터). --max-new로 앞에서 자르므로 늘 실패하는 문서가 새 문서 자리를 막지 않는다(PR #49 리뷰) — 실패 문서도
    자리가 남으면 매번 다시(pl-32). 대장을 못 열면 _no_registry()대로(None이면 받은 목록 그대로). 앞 실행 runs.jsonl은 보지 않는다."""
    from common.store import registry as REG

    db = REG.try_open_db()
    if db is None:
        _no_registry()
        return list(names)
    try:
        rows = db.query("SELECT names, status, last_seen FROM doc_registry")
    finally:
        db.close()
    state = {}  # 이름 → (status, last_seen)
    for r in rows:
        for n in json.loads(r["names"] or "[]"):
            state[n] = (r["status"], r["last_seen"] or "")
    fresh = [n for n in names if state.get(n, ("seen", ""))[0] == "seen"]
    failed = sorted((n for n in names if state.get(n, ("seen", ""))[0] not in ("seen", "parsed")), key=lambda n: (state[n][1], n))
    return fresh + failed


_T_STEP: dict = {}


def _tstep(name):
    _T_STEP[name] = time.time()


def _tdone():
    if not _T_STEP:
        return ""
    keys = list(_T_STEP)
    parts, prev = [], keys[0]
    for k in keys[1:]:
        parts.append(f"{prev.replace('t_', '')}={_T_STEP[k] - _T_STEP[prev]:.1f}s")
        prev = k
    _T_STEP.clear()
    return " · ".join(parts)


def parse_module(a):
    """파싱 모듈: (--source면) 가져오기·시험 표본 → 중복 확인 → 방향 보정 → 파싱 → 채점 → 대표 결과 → 끝 표시 → (s3) 원본 정리.
    임베딩·DB 연결 없음 — 수집 서버에 이것만 보낼 수 있음. --source 없으면 --src(이미 준비된 폴더)를 그대로."""
    from common.core.paths import child_env

    _tstep("t_start")
    run_id = os.environ.get("PARSE_RUN_ID") or time.strftime(
        "%Y%m%d-%H%M%S"
    )  # env 남김 — 내부 신호(5-3 H) · SI23 — run_all·_DONE.json이 같은 id를 쓰게(run_board가 이번 실행만 거르는 기준)
    os.environ["PARSE_RUN_ID"] = (
        run_id  # env 남김 — 하위 프로세스·엔진에 넘김 · 이후 모든 하위 호출(dedup·prepare·run_all·streaming)이 os.environ 상속으로 받음
    )
    st = _stack()
    engines = a.engines or ",".join(_engines_of(st))
    _set_engine_scope_default(a.engines)  # PE1(2026-10-07) — 생산 기본 stack(무거움 해소), 명시 --engines·실험 경로는 영향 없음
    parallel = bool(a.source) and pc.cfg().extract.parallel.pipeline  # OP26 — 문서 단위 받기→파싱→게시→삭제를 N명이 동시에
    streaming = bool(a.source) and not parallel and pc.cfg().extract.stream.stream  # 백로그 X2 — 묶음(기본 1건)씩 받아 처리 후 즉시 지움
    lim, src_info = [], None
    if parallel:
        from pipeline import parse_parallel as PARALLEL

        PARALLEL.run(a, engines)  # 원본·중간 결과는 문서마다 이미 지움(try/finally) · 게시도 문서마다 이미 끝남
    elif streaming:
        from pipeline import stream as STREAM

        STREAM.run(a, engines)  # 원본·사본·엔진별 중간 결과는 묶음마다 이미 지움(try/finally)
    elif a.source:  # 문서 위치: 같은 서버 폴더 → Object Storage 몇 건 → 전체(사용자 10-02)
        from pipeline.extract import source as SRC

        local, names, state = SRC.resolve(a.source, OUT, a.source_limit, a.mode)
        src_info = (state, local)
        _tstep("t_resolve")
        if not SRC.is_remote(a.source):
            C.put(
                DOC_DIR=str(Path(local).resolve())
            )  # S7e2 — 덮기 파일 + 인계 키라 env에도(contract.py) · 원본 위치 주소 = 이 폴더의 file:///
        sel = OUT / "parse" / "_source" / "selected.txt"
        sel.write_text("\n".join(names) + "\n", encoding="utf-8")
        rc = _run_until(["pipeline.extract.dedup", "--src", local, "--out", OUT / "dedup"], child_env(), _left(a) - 120)
        _tstep("t_dedup")
        if rc != 0:
            raise SystemExit(75 if rc is None else rc)
        keep = set((OUT / "dedup" / "keep.txt").read_text(encoding="utf-8").splitlines())
        reg_new = _registry_new_names(
            OUT, names
        )  # OP9 — 문서 대장이 있으면 새 doc_key만(changed·deleted는 빠짐) · 없으면 None(필터 없음, 전과 동일)
        if reg_new is not None:
            keep &= reg_new
        only = OUT / "parse" / "_source" / "only.txt"
        only.write_text("\n".join(n for n in names if n in keep) + "\n", encoding="utf-8")
        rc = _run_until(["pipeline.extract.prepare", "--src", local, "--out", a.src, "--only", only], child_env(), _left(a) - 120)
        _tstep("t_prepare")
        if rc != 0:
            raise SystemExit(75 if rc is None else rc)
        lim = ["--docs-from", only]
    if not streaming and not parallel:
        from common.core import resources as RS

        vlm_conc = RS.vlm_page_concurrency(a.workers, a.vlm_concurrency)  # 문서 동시 수 × 쪽 동시 수가 VLM_MAX_CONCURRENCY를 넘지 않게
        from common.core.paths import child_env

        env = C.child_env(
            child_env(), VLM_CONCURRENCY=str(vlm_conc), LLM_BASE_URL=None
        )  # 파싱 모듈은 LLM을 부르지 않음 — 덮기 파일(S7e3 B-1)
        if a.max_new:  # 밤당 새 문서 상한(GH1-10: test 모드도 적용) — 밀린 문서가 많아도 매일 밤 대표 결과·구조화·적재까지 끝나게
            names = sorted(p.name for p in Path(a.src).iterdir() if p.is_file())
            new = _registry_unparsed(names)  # pl-32 — 문서 대장에 성공 행 없는 문서(새 + 실패)만 · 앞 실행 runs.jsonl은 안 봄
            pick = new[: a.max_new]
            f = OUT / "parse" / "_batch_docs.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            if lim:  # --source 선택과 겹치는 것만
                sel_names = set(Path(lim[1]).read_text(encoding="utf-8").splitlines())
                pick = [n for n in pick if n in sel_names]
            f.write_text("\n".join(pick) + "\n", encoding="utf-8")
            lim = ["--docs-from", f]
            print(
                f"[parse] 새·실패 문서 {min(len(new), a.max_new)}/{len(new)}개(PARSE_MAX_NEW {a.max_new}) — 나머지는 다음 실행", flush=True
            )
        args = [
            "pipeline.extract.run_all",
            "--src",
            a.src,
            "--out",
            OUT / "parse",
            "--procs",
            a.procs,
            "--workers",
            a.workers,
            "--engines",
            engines,
            *lim,
        ]
        if _run_until(args, env, _left(a) - 120) is None:
            raise SystemExit(75)  # 마감 — 끝 표시 안 바꿈, 다음 실행이 이어 감
        _tstep("t_parse")
        for args in (
            ["pipeline.transform.represent.parse_qa", "--src", a.src, "--parse", OUT / "parse", "--truth", OUT / "corpus" / "truth.json"],
            ["pipeline.transform.represent.represent", *_stack_arg(), "--src", a.src, "--parse-dir", OUT / "parse"],
        ):
            rc = _run_until(args, env, _left(a) - 60)
            _tstep("t_" + args[0].rsplit(".", 1)[-1])  # 2026-10-22 — qa·represent 분리 계측(docflow 기타 분해)
            if rc != 0:
                raise SystemExit(75 if rc is None else rc)
    import hashlib

    print(f"[docflow-step] {_tdone()}", flush=True)  # 2026-10-22 — resolve~represent까지 docflow 기타 분해 로그
    idx = json.loads((OUT / "parse" / "_rep" / "index.json").read_text(encoding="utf-8"))["docs"]
    core = [{k: v for k, v in r.items() if k != "tried"} for r in idx]  # 시도 기록(시각)은 빼고 대표 결과만 비교
    content = []  # GH1-05 — core는 chars·facts_added(길이·개수)만 있어 길이·개수가 같은 내용 교체를 못 잡음 → 본문·facts 자체의 sha256
    for r in idx:
        if not r.get("engine"):
            continue
        rep = json.loads((OUT / "parse" / "_rep" / f"{r['doc']}.json").read_text(encoding="utf-8"))
        content.append(
            {
                "doc": r["doc"],
                "text_sha": hashlib.sha256((rep.get("text") or "").encode("utf-8")).hexdigest(),
                "facts_sha": hashlib.sha256(
                    json.dumps(rep.get("facts") or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
            }
        )
    digest = hashlib.sha256(json.dumps({"core": core, "content": content}, sort_keys=True).encode()).hexdigest()[:16]
    old = read_mark("parse") or {}
    if old.get("digest") == digest and old.get("contract") == CONTRACT:
        print(f"[parse] 대표 결과 변화 없음 — 끝 표시 그대로(run_id {old['run_id']}), 구조화는 건너뛰게 됨", flush=True)
        return
    write_mark(
        "parse",
        src=str(a.src),
        source=str(a.source or a.src),
        mode=a.mode,
        engines=engines.split(","),
        docs=len(idx),
        digest=digest,
        rep_ok=sum(1 for r in idx if r.get("engine")),
        run_id=run_id,
    )
    if not streaming and not parallel and src_info:  # 스트리밍·병렬은 문서/묶음마다 이미 지웠음(SRC.mark_done)
        from pipeline.extract import source as SRC

        if SRC.is_remote(a.source):
            SRC.finish(src_info[0], src_info[1], OUT / "parse" / "_rep" / "index.json")


def _structure_extra(embed):
    """GH1-06 — 구조화 결과를 좌우하는 대상·설정 지문: 임베딩 목적지(EMBED_BASE_URL, 비밀값 아님)·방식 + 구조화 코드
    지문(common/artifacts.code_fp, 이미 있는 실험 저장소 계약 재사용) — 바뀌면 parse run_id가 같아도 다시 구조화."""
    from common.core import artifacts as P0

    return {"embed": embed, "embed_url": C.cfg().models.embed.base_url or "", "code": P0.code_fp("s")}


def _structure_pg_indexed(a, index_conf):
    """INDEX_CONF — AD41 색인 모듈(cli/index.py build)로 설정별 색인(pg-a·pg-b, 예 청크
    크기가 다른 두 설정)을 만든다. index.py가 자기 입력 지문(_rep·사전·명부·stack·코드)으로 재빌드를 판정하고
    같은 index_id 동시 빌드는 잠금으로 막으므로, 여기서 need()/write_mark로 다시 게이트하지 않는다(이중 판정
    이 서로 어긋나는 것을 피함) — --pg로 PostgreSQL 스키마 <PG_SCHEMA>_<index_id>까지 적재.
    index.py의 종료 코드(2 설정 오류·3 계약 위반·5 임베딩·75 빌드 중)를 그대로 돌려준다(sh()의 기본 check=True는
    원래 코드를 묻고 메시지만 남겨 트리거 서버가 75=재시도를 못 가림)."""
    rc = sh(
        "pipeline.load.index",
        "build",
        "--conf",
        index_conf,
        "--parse-dir",
        OUT / "parse",
        "--src",
        a.src,
        "--pg",  # 엔진 구성 판은 넘겨받은 STACK_VERSION 칸으로(index는 --stack-version 인자가 없음 — pl-32 리뷰)
        *(["--path-prefix", a.path_prefix] if a.path_prefix else []),
        check=False,
    )
    if rc:
        raise SystemExit(rc)


def structure_module(a):
    """구조화 모듈: 대표 결과(_rep)만 읽어 청킹·사실·고객·그래프·임베딩(API·캐시) → 묶음(output/edw/bundle) → 끝 표시. 원본이 없어도 됨.
    INDEX_CONF가 있으면 AD41 색인 빌더로 대신(아래 분기) — 없으면 기본 색인."""
    index_conf = pc.cfg().paths.index_conf
    if index_conf:
        return _structure_pg_indexed(a, index_conf)
    st = _stack()
    embed = pc.cfg().transform.structure.embed or st.get("embed", "api")
    m = need("parse", "structure", a.force, extra=_structure_extra(embed))
    if not m:
        return
    if embed == "api" and not C.cfg().models.embed.base_url:
        print(
            "[structure] 임베딩 연결 없음(EMBED_BASE_URL) — 임베딩 서버에 닿는 곳(개발 서버)에서 실행하거나, "
            "PIPE_EMBED=none(키워드·ID 검색만, PostgreSQL 적재 안 함)",
            flush=True,
        )
        raise SystemExit(5)
    from common.core import contract

    bad = contract.check_parse(
        OUT / "parse" / "_rep", sample=500
    )  # 앞 500건만 열어 봄(대량 폴더 빠르게) — 전체는 python -m common.core.contract
    if bad:
        print("[structure] 파싱 인계 폴더가 계약과 다름 — " + " · ".join(bad[:5]), flush=True)
        raise SystemExit(3)
    from common.core.paths import child_env

    env = C.child_env(
        child_env(), **({"EDW_SUMMARY_LLM": "0"} if a.deadline else {})
    )  # 새벽 배치(마감 지정)면 LLM 요약 안 함 — night와 같게(덮기 파일 — S7e3 B-1)
    args = [
        "pipeline.transform.structure.build_bundle",
        "--src",
        a.src,
        "--embed",
        embed,
        *_stack_arg(),
        "--summary",
        "auto",
        *(["--path-prefix", a.path_prefix] if a.path_prefix else []),
    ]
    rc = _run_until(args, env, _left(a) - 60)
    if rc != 0:
        raise SystemExit(75 if rc is None else rc)
    meta = json.loads((OUT / "edw" / "bundle" / "meta.json").read_text(encoding="utf-8"))
    write_mark(
        "structure",
        from_run=m["run_id"],
        docs=meta["docs"],
        chunks=meta["chunks"],
        dim=meta["dim"],
        embed_model=meta.get("embed_model"),
        extra=_structure_extra(embed),
    )
    load_tables_db(env)


def _pg_dest_fp():
    """GH1-06 — host:port/db/schema(비밀값·사용자명 제외) 지문. 바뀌면 같은 parse·structure run_id라도 다시
    적재한다(조용히 다른 대상에 빈 적재가 되는 일 방지) — common/pg.conf()가 PG_CONN_FILE·env·기본값을 이미 합친 값.
    GH1-06b — 라이브 연결 없이 **설정만**으로 계산(need()를 connect() 앞에 두려고, 건너뛰는 경우엔 접속 자체가
    필요 없게). PG_HOST·PG_PORT·PG_CONN_FILE이 전부 비어 있으면(Docker 자동탐지에 맡기는 경우) conf()의 기본값
    (127.0.0.1:5432)을 쓰지 않는다 — 그 기본값을 그대로 지문에 넣으면 실제 자동탐지된 host(예: 컨테이너 IP)와
    달라서 같은 대상인데도 매번 '대상이 바뀜'으로 오판해 다시 적재하게 된다.
    GH1-06c — 'auto-discovered' 상수로 고정하면 반대 방향 결함이 생긴다: Docker 재기동으로 컨테이너 IP가 실제로
    바뀌어도 상수는 안 바뀌어 대상 변경을 못 잡는다. common/services.docker_ps()(docker ps 파싱만, PG 접속·TCP
    확인 없음 — 06b가 지키는 "건너뛰는 경로엔 라이브 연결 없음"을 그대로 유지)로 pgvector 컨테이너의 실제
    host:port를 찾아 지문에 넣는다 — Docker를 못 쓰면(권한·미설치) 그 식별(여기선 reason)만 상수 대신 넣어
    GH1-06 이전보다 나빠지지 않는 선에서 구분한다(서버는 PG_HOST를 명시하므로 이 자동탐지 분기 자체를 안 탐)."""
    from common.store.pg import conf

    auto = all(C.given(k) is None for k in ("PG_HOST", "PG_PORT", "PG_CONN_FILE"))  # S7c — 준 값이 하나도 없을 때(옛 "있고 없음" 판정)
    c = conf()
    if auto:
        from common.store import services

        rows, reason = services.docker_ps()  # 라이브 PG 연결 없음 — docker ps만(06b 유지)
        hit = services._find(rows, "pgvector", "5432")
        host, port = (hit[1], hit[2]) if hit else ("auto-discovered", reason or "no-container")
    else:
        host, port = c["PG_HOST"], c["PG_PORT"]
    return f"{host}:{port}/{c['PG_DB']}/{c['PG_SCHEMA']}"


def load_module(a):
    """적재 모듈: 묶음 → PostgreSQL(pgvector) 배포·적재(옛 기록 정리) → 끝 표시. PostgreSQL을 못 찾으면 종료 코드 4.
    GH1-06b — need()를 먼저 확인하고(설정만으로 만든 지문, 라이브 연결 없이), 할 일이 있을 때만 connect()로
    실제 접속을 확인한다 — 건너뛰는 경우(PG가 잠깐 내려가 있어도) Docker 탐지·PG 접속 시도 없이 조용히 끝남
    (수정 전엔 connect()가 need() 앞에 있어 건너뛰는 경우에도 접속을 시도해 PG가 내려가 있으면 SystemExit(4))."""
    dest_fp = _pg_dest_fp()
    m = need("structure", "load", a.force, extra=dest_fp)
    if not m:
        return
    a.pg, a.local = True, False  # 적재 모듈은 PostgreSQL 필수 — 못 붙으면 services.connect가 거부
    connect(a)
    if not a.pg:
        print("[load] PostgreSQL(pgvector)을 찾지 못함 — PG_HOST·PG_PORT·PG_PASSWORD 또는 Docker pgvector", flush=True)
        raise SystemExit(4)
    from common.core import contract

    bad = contract.check_bundle(OUT / "edw" / "bundle")
    if bad:
        print("[load] 묶음이 계약과 다름 — " + " · ".join(bad[:5]), flush=True)
        raise SystemExit(3)
    if not m.get("dim"):
        print("[load] 임베딩 없는 묶음(PIPE_EMBED=none) — PostgreSQL에는 적재 안 함(로컬 묶음으로 키워드·ID 검색만)", flush=True)
        raise SystemExit(5)
    sh("pipeline.load.pgvector_load", "deploy")
    sh("pipeline.load.pgvector_load", "load", *(["--replace"] if a.replace else []))  # 더하고 고치기만(pl-13 — 지우지 않음)
    write_mark("load", from_run=m["run_id"], docs=m.get("docs"), chunks=m.get("chunks"), extra=dest_fp)


def run_stack(a):
    connect(a)
    st = _stack()
    engines = ",".join(sorted({e for es in st["parse"].values() for e in es}))
    if not a.skip_parse:
        parse_docs(a.src, engines, a.procs)  # 이미 파싱된 문서×엔진은 다시 안 함(sha)
    sh("pipeline.transform.represent.parse_qa", "--src", a.src)  # 대표 고르기용 정확도(교차 재현율)
    sh("pipeline.transform.represent.represent", *_stack_arg(), "--src", a.src)
    sh(
        "pipeline.transform.structure.build_bundle",
        "--src",
        a.src,
        "--embed",
        pc.cfg().transform.structure.embed or st["embed"],
        *_stack_arg(),
        *(["--path-prefix", a.path_prefix] if a.path_prefix else []),
    )
    load_tables_db()
    if a.pg:
        sh("pipeline.load.pgvector_load", "deploy")
        sh("pipeline.load.pgvector_load", "load", *(["--replace"] if a.replace else []))  # 더하고 고치기만(pl-13 — 지우지 않음)
    summ = json.loads((OUT / "edw" / "bundle" / "meta.json").read_text(encoding="utf-8")).get("summary") or {}
    print(
        "→ 대표 파싱 output/parse/_rep · 구조화 output/edw/bundle"
        + (" · pgvector 적재 완료" if a.pg else " · PostgreSQL 없음 — 로컬 묶음만")
        + " · EDW 적재 안 함"
        + " · 요약 출처 "
        + " · ".join(f"{k} {v}" for k, v in summ.items())
        + " — 이제 ask / test-stack"
    )


def connect(a):
    """연결 기본값(백로그 E6 · 사용자 2026-10-01): --pg·--local 지정이 없으면 Docker에 떠 있는 pgvector에 연결,
    없으면 로컬 묶음. → common/services.py"""
    from common.store import services

    services.connect(a)


# ── 운영자 자기 점검(selftest) ──────────────────────────────────
# S9(D-018, 사용자 10-28) — 자기 점검은 모두 저장소 루트 tests/로 옮겼다. 이미지 명령 `selftest`는 서버 반입 시험 tests/server/<앱>/test_*.py를
# 파일마다 자식 프로세스(python -m tests.runner <시험 모듈>)로 돌려 PASS/FAIL 표를 낸다 — 반입 판정은 deploy/release/selftest_gate.sh(알려진 FAIL은
# known_fail.txt, 사례 이름 = 시험 모듈 이름). 폴더가 곧 이미지: common = 두 이미지 · pipeline = data-pipeline · mcp = mcp-server(RAG_MODULE).
# PC 일반 시험(tests/general — PC 전용·느린 것·PG·Docker)은 pytest로만(`python -m pytest tests/` — tests/conftest.py가 같은 자식 프로세스·같은 env로).
# 옛 사례 이름(모듈 이름) → 새 시험 모듈 대응표는 output/orca/S9-impl.md.
TESTS_ROOT = Path(__file__).resolve().parents[1] / "tests"  # 저장소 루트 tests/ · 이미지 /app/deploy/tests(PYTHONPATH와 같은 뿌리)
IMAGE_DIRS = {"common": None, "pipeline": "pipeline", "mcp": "mcp"}  # tests/server/<폴더> → 도는 이미지(None = 둘 다)
_FAKE_LLM_CASES = frozenset({"tests.server.mcp.test_mcp_main"})  # LLM_FAKE를 켜는 사례(질문 분해 — 옛 mcp_server.main 사례)
# PC에서 개발자 루트 settings.yaml(실 PG)을 그대로 읽어야 판정되는 사례(실 PG에서만 C-54 ① 재현) — 그 밖 PC 사례는 시험 전용 바탕 설정(case_env, 10-29)
_PC_SETTINGS_CASES = frozenset({"tests.general.pipeline.test_pub_registry"})


def server_cases():
    """[(시험 모듈, 이미지|None)] — tests/server/<폴더>/test_*.py(이름순). 모르는 폴더는 사례로 넣지 않고 FAIL 사례로(오타·새 앱을 놓치지 않게)."""
    out = []
    for p in sorted((TESTS_ROOT / "server").glob("*/test_*.py")):
        out.append((f"tests.server.{p.parent.name}.{p.stem}", IMAGE_DIRS.get(p.parent.name, "?")))
    return out


_CASE_ENVS: dict = {}


def case_env(mod):
    """사례 자식 env(새 dict) — 유료 호출 잠금·모델 주소 비움·LLM_FAKE(_FAKE_LLM_CASES만)는 덮기 파일로(S7e3 B-1 — env dict의 설정 이름은 자식이
    안 읽음). 두 벌만 만든다(임시 파일 수 — R-4). PC pytest(tests/conftest.py)도 이것을 쓴다 — 이미지 selftest와 같은 env."""
    from common.core.paths import child_env

    fake = mod in _FAKE_LLM_CASES
    own = not C.IN_IMAGE and mod not in _PC_SETTINGS_CASES  # PC 시험은 시험 전용 바탕 설정(아래 _case_settings)
    if (fake, own) not in _CASE_ENVS:
        blank = dict.fromkeys(("LLM_BASE_URL", "VLM_BASE_URL", "EMBED_BASE_URL", "LLM_BUDGET_USD"))
        base = child_env({"PYTHONUTF8": "1"})
        if own:  # PC — 개발자 루트 settings.yaml(실 PG·모델 키) 대신 시험 전용 최소 설정 위에 덮음(10-29 — 시험 격리)
            base["SETTINGS_FILE"] = _case_settings()
        _CASE_ENVS[(fake, own)] = C.child_env(base, NO_PAID_CALLS="1", LLM_FAKE="1" if fake else None, **blank)
    return dict(_CASE_ENVS[(fake, own)])


def _case_settings():
    """PC 시험 사례의 바탕 설정 파일 — run_env: local만(접속·키 없음 → 정형 저장소는 SQLite, 모델 호출 없음). 한 번 만든다."""
    if "file" not in _CASE_ENVS:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="case_settings_", suffix=".yaml")
        os.write(fd, b"common:\n  run_env: local\n")
        os.close(fd)
        _CASE_ENVS["file"] = path
    return _CASE_ENVS["file"]


# 단계 4 도구 16개(S4 — 옛 공용 cli/·evaluation/에서 pipeline/로 옮김). S9 전에는 "공용" 사례였고 mcp 이미지에서는 모듈이 없어 SKIP이었다 —
# S9부터 그 시험은 tests/server/pipeline(mcp 이미지에서 "다른 이미지 사례" SKIP — 결과 같음). 여기서는 두 손 목록 확인만(check_modules.MOVED_TOOLS).
# S6a — 목록은 전에 경계 점검의 LEGACY_TOOLS(파일 경로 → 옛 자리)에서 읽었다. 경계 판정에 더 안 쓰여 그 표를 지우고 여기 둔다(같은 16개).
_STAGE4_TOOLS = frozenset(
    {
        "pipeline.cli",
        "pipeline.check_env",
        "pipeline.parse_parallel",
        "pipeline.trigger_server",
        "pipeline.extract.rdb_discover",
        "pipeline.transform.structure.gen_roster",
        "pipeline.transform.structure.glossary_suggest",
        *(
            f"pipeline.eval.{n}"
            for n in (
                "make_questions",
                "run_combo",
                "report",
                "server_checks",
                "anchors",
                "auto_questions",
                "stages",
            )
        ),
    }
)


def _tool_list_check():
    """PC 전용 — 단계 4 도구 두 손 목록(맨 이름 check_modules.MOVED_TOOLS['etl'] · 모듈 이름 _STAGE4_TOOLS)이 같은 16개인지
    (S6a 리뷰 — 옛 cli/pipeline.py는 맨 이름 pipeline). 어긋난 것 목록."""
    from common.check.check_modules import MOVED_TOOLS

    names = {m.rsplit(".", 1)[1] for m in _STAGE4_TOOLS} - {"cli"} | {"pipeline"}
    return (
        []
        if names == MOVED_TOOLS["etl"]
        else [f"_STAGE4_TOOLS ↔ check_modules.MOVED_TOOLS['etl'] 어긋남: {sorted(names ^ MOVED_TOOLS['etl'])}"]
    )


def _spec_missing(mod):
    """이 이미지에 없는 모듈인지 — 중간 패키지가 없으면 find_spec이 ModuleNotFoundError를 던지므로 그것도 없음으로."""
    import importlib.util

    try:
        return importlib.util.find_spec(mod) is None
    except ModuleNotFoundError:
        return True


def _image_lacks(top):
    """이 이미지에 그 앱 코드가 아예 없는지(최상위 이름 pipeline·mcp_server) — pipeline은 mcp 이미지에 명령용 cli.py·config.py만
    들어가므로(S4·S7c1) 단계 코드(pipeline.extract)로, mcp_server는 pipeline 이미지에 설정 모델 config.py만 들어가므로(S7e1) 검색 코드(mcp_server.services)로
    본다(VS7e1 R-8). 하위 모듈 이름 하나가 없는 것(오타·빠진 COPY)은 SKIP이 아니라 FAIL로 남긴다."""
    return _spec_missing("pipeline.extract" if top == "pipeline" else "mcp_server.services")


def _selftest_workers():
    """selftest 동시 사례 수 — 이 프로세스가 쓸 수 있는 CPU 수(컨테이너 CPU 고정 반영 — sched_getaffinity), 많아도 8."""
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return max(1, min(8, cpus))


def selftest(a):
    """`docker run … IMG selftest` — 서버 반입 시험(tests/server)을 파일마다 자식 프로세스로(네트워크 0 · case_env) 돌려 PASS/FAIL 표. 하나라도
    FAIL이면 종료 코드 1. 이미지 안(RAG_MODULE=pipeline·mcp)에서는 다른 이미지 폴더의 사례를 SKIP, RAG_MODULE이 비면(PC) 전부. 공용(common) 사례가
    이 이미지에 없는 앱 모듈 때문에만 실패하면 SKIP(진짜 오류는 FAIL) · 서드파티 패키지가 없어 실패한 것은 FAIL(I2c). 시험 폴더가 없거나 사례가 0개면
    FAIL(이미지 COPY 누락). --only <이름 조각>(여러 번) — 그 사례만."""
    import re

    image = os.environ.get("RAG_MODULE", "").strip()  # env 남김 — 내부 신호(5-3 H)
    image = image if image in ("pipeline", "mcp") else ""
    split_bad = None if image else _tool_list_check()
    if not image:  # PC에서만 — 두 손 목록 어긋남은 종료 코드 1(아래)
        print("도구 목록(단계 4): " + ("맞음" if not split_bad else "어긋남 — " + ", ".join(split_bad)))
    cases = server_cases()
    only = getattr(a, "only", None) or []
    if only:
        cases = [c for c in cases if any(o in c[0] for o in only)]
    rows = []
    if not cases:
        rows.append((str(TESTS_ROOT / "server"), "FAIL", "서버 반입 시험이 없음(tests/server — 이미지 COPY·--only 확인)"))

    def run_case(case):
        mod, img = case
        if img == "?":
            return (mod, "FAIL", "모르는 시험 폴더(tests/server/{common,pipeline,mcp}만)")
        if image and img not in (None, image):
            return (mod, "SKIP", f"다른 이미지 사례({img})")
        r = subprocess.run(
            [PY, "-m", "tests.runner", mod],
            cwd=ROOT,
            env=case_env(mod),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        out = r.stdout + r.stderr
        # 공용 사례가 이 이미지에 없는 앱 모듈 때문에만 실패했으면 SKIP(mcp 이미지에는 pipeline/ 중 cli.py·config.py만 — _image_lacks)
        miss = re.findall(r"ModuleNotFoundError: No module named '(pipeline|mcp_server)['.]", out)
        if r.returncode != 0 and miss and all(_image_lacks(m) for m in set(miss)):
            return (mod, "SKIP", f"다른 이미지 모듈 필요({', '.join(sorted(set(miss)))})")
        return (mod, "PASS" if r.returncode == 0 else "FAIL", "" if r.returncode == 0 else out[-1500:])

    # 사례는 서로 다른 자식 프로세스라 함께 돌림(쓸 수 있는 CPU 수, 많아도 8개) — map은 순서를 지켜 표는 그대로
    for mod, _ in cases:  # 덮기 파일 캐시(_CASE_ENVS)를 먼저 채움 — 스레드가 같은 파일을 두 번 만들지 않게
        case_env(mod)
    with ThreadPoolExecutor(max_workers=_selftest_workers()) as pool:
        rows += pool.map(run_case, cases)
    fails = [name for name, status, _ in rows if status == "FAIL"]
    skips = sum(1 for _, status, _ in rows if status == "SKIP")
    for name, status, detail in rows:
        print(f"{status:4} {name}" + (f"  ({detail})" if status == "SKIP" else ""))
        if status == "FAIL":
            print("     " + detail.replace("\n", "\n     "))
    print(
        f"\n{len(rows) - len(fails) - skips}/{len(rows) - skips} 통과"
        + (f" · SKIP {skips}" if skips else "")
        + (f" · FAIL {len(fails)}: {', '.join(fails)}" if fails else "")
    )
    if fails or split_bad:
        raise SystemExit(1)


# 10-14 요건 — selftest는 가짜 모듈 자기 점검만(실문서 모양 없음). smoke는 --src(기본 DOC_DIR) 폴더의 실문서를
# 이 이미지에 있는 것만(find_spec, selftest와 같은 감지) 실제로 돌려 사람이 읽는 요약을 남긴다 — "실문서 전에
# 와이어링 점검"(샘플은 이미지 안에 안 넣는다, 운영자가 서버에서 폴더를 직접 줌). 지금은 parse만 실제로 문서를
# 읽는다(structure·load·search는 대표 파싱 결과(_rep)가 있어야 돌아 raw 문서만으로는 못 함 — 이미 있는 그
# 모듈들의 시험(tests/)이 와이어링은 따로 확인) → skipped: structure·load·search의 파일별 처리, 필요해지면
# parse로 만든 _rep를 같은 실행에서 이어 쓰게(예: --src가 parse 이미지의 output/parse/_rep를 가리킬 때) 확장.
def _parse_engine_needs_endpoint(engine):
    """registry.missing_env와 같은 자리(REQUIRES_ENV)를 보되, 지금 비어 있는지가 아니라 "애초에 모델 엔드포인트가
    필요한 엔진인지"만 — smoke 기본(오프라인)은 설정 여부와 무관하게 이런 엔진을 건너뛰고 --real-models일 때만 쓴다."""
    from pipeline.extract.engines import registry

    _, m = registry.engines()[engine]
    return bool(getattr(m, "REQUIRES_ENV", {}).get(engine))


def _smoke_parse_file(f, real_models):
    """문서 1건 → (status, engine, detail, rec) — registry.run()으로 엔진 하나만(run_all의 다중 엔진·dedup·phase 없음,
    가벼운 와이어링 점검이 목적)."""
    from pipeline.extract.engines import registry

    all_engines = registry.engines_for(f.suffix)
    if not all_engines:
        return "SKIP", None, f"확장자 {f.suffix or '(없음)'} 처리 엔진 없음(이 이미지에)", {}
    installed = [e for e in all_engines if registry.installed(e)]
    if not installed:
        return "FAIL", None, f"설치된 엔진 없음(의존성 누락): {','.join(all_engines)}", {}
    local = [e for e in installed if not _parse_engine_needs_endpoint(e)]
    usable = installed if real_models else local
    if not usable:
        return "SKIP", None, f"모델 엔드포인트 필요({','.join(installed)}) — --real-models로", {}
    eng = usable[0]
    try:
        out = registry.run(eng, f)
    except Exception as e:  # 문서 하나가 터져도 나머지는 계속 — 와이어링 점검이 목적, 어디서·무엇을·왜
        return "FAIL", eng, f"{type(e).__name__}: {e}", {}
    text = out.get("text") or ""
    tables = out.get("tables") or []
    rec = {
        "engine": eng,
        "pages": text.count("\f") + 1 if text else 0,
        "tables": len(tables),
        "merged_cell": any(t.get("merges") for t in tables),
        "figures": out.get("trace", {}).get("images"),
    }
    return "PASS", eng, "", {**rec, "_text": text}


def _check_expected(rec, want):
    """expected.json[name]에 있는 키만 대조(없는 키는 건너뜀) → (통과?, 상세 문장 목록)."""
    text = rec.pop("_text", "")
    checks = []
    if "engine" in want:
        ok_list = want["engine"] if isinstance(want["engine"], list) else [want["engine"]]
        checks.append((rec.get("engine") in ok_list, f"engine {rec.get('engine')} in {ok_list}"))
    if "min_pages" in want:
        checks.append(((rec.get("pages") or 0) >= want["min_pages"], f"pages {rec.get('pages')} >= {want['min_pages']}"))
    if "tables" in want:
        checks.append(((rec.get("tables") or 0) >= want["tables"], f"tables {rec.get('tables')} >= {want['tables']}"))
    if "merged_cell" in want:
        checks.append(
            (bool(rec.get("merged_cell")) == bool(want["merged_cell"]), f"merged_cell {rec.get('merged_cell')} == {want['merged_cell']}")
        )
    if "contains" in want:
        miss = [s for s in want["contains"] if s not in text]
        checks.append((not miss, "contains 전부 있음" if not miss else f"contains 빠짐: {miss}"))
    return all(ok for ok, _ in checks), checks


def smoke(a):
    """`docker run … IMG smoke [--src <실문서 폴더>] [--real-models]` — 이 이미지에 있는 모듈만(find_spec) --src
    (기본 DOC_DIR)의 실문서에 돌려 사람이 읽는 요약(PASS/SKIP/FAIL 표)을 stdout + output/smoke/<시각>/summary.json에
    남긴다. --src에 expected.json이 있으면(선택 — 없어도 그냥 보고만) 파일별 최소 기대값(engine·min_pages·tables·
    merged_cell·contains)을 대조해 PASS/FAIL도 같이 찍는다. 기본은 오프라인(모델 엔드포인트가 필요한 엔진은
    건너뜀) — --real-models면 pipeline.env에 이미 설정된 내부망 엔드포인트로(외부·유료 호출 없음 — NO_PAID_CALLS
    가드는 항상 켬, common/guard.py가 그 값을 보고 막는다)."""

    if (
        not C.cfg().models.guard.no_paid_calls
    ):  # S7e2 — 덮기 파일(이 프로세스·하위 프로세스) · 이 가드는 smoke에서 항상 켬 — --real-models도 내부망 엔드포인트만
        C.put(NO_PAID_CALLS="1")
    src = Path(a.src or C.cfg().paths.doc_dir or "")
    if not src.is_dir():
        print(f"[smoke] 문서 폴더 없음: {src or '(지정 안 함, DOC_DIR도 없음)'} — --src 또는 DOC_DIR로 폴더 지정", flush=True)
        raise SystemExit(2)

    def has(mod):
        return not _spec_missing(mod)

    pkg = {
        "parse": "pipeline.extract",
        "structure": "pipeline.transform.structure",
        "load": "pipeline.load",
        "search": "mcp_server",
    }  # 10-14 이미지별 폴더 분리 · I2 data_etl(S4부터 pipeline) 단계 폴더 · S5 data_retrieval → mcp_server
    stages = {s: has(p) for s, p in pkg.items()}
    files = sorted(p for p in src.iterdir() if p.is_file() and p.name != "expected.json")
    expected_file = src / "expected.json"
    expected = json.loads(expected_file.read_text(encoding="utf-8")) if expected_file.exists() else {}

    rows = []
    for f in files:
        if not stages["parse"]:
            rows.append({"file": f.name, "status": "SKIP", "detail": "이 이미지엔 parse 모듈 없음"})
            continue
        status, eng, detail, rec = _smoke_parse_file(f, a.real_models)
        row = {"file": f.name, "status": status, "engine": eng, **{k: v for k, v in rec.items() if k != "_text"}}
        if status == "PASS" and f.name in expected:
            ok, checks = _check_expected(rec, expected[f.name])
            row["status"] = "PASS" if ok else "FAIL"
            row["expected_checks"] = [{"ok": c_ok, "detail": c_detail} for c_ok, c_detail in checks]
        row["detail"] = detail
        rows.append(row)

    ts = time.strftime("%Y%m%d-%H%M%S")
    outdir = OUT / "smoke" / ts
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {"ts": ts, "src": str(src), "real_models": bool(a.real_models), "stages": stages, "files": rows}
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(
        f"[smoke] 이 이미지 — parse={stages['parse']} structure={stages['structure']} load={stages['load']} search={stages['search']}"
        + (
            " (structure·load·search는 대표 파싱 결과가 있어야 함 — 이 경량 점검은 parse만 실문서를 읽음)"
            if any(stages[s] for s in ("structure", "load", "search"))
            else ""
        ),
        flush=True,
    )
    for r in rows:
        extra = " · ".join(f"{k}={r[k]}" for k in ("engine", "pages", "tables", "merged_cell", "figures") if r.get(k) is not None)
        print(
            f"{r['status']:4} {r['file']}" + (f"  {extra}" if extra else "") + (f"  ({r['detail']})" if r.get("detail") else ""), flush=True
        )
        for c in r.get("expected_checks") or []:
            print(("     ✓ " if c["ok"] else "     ✗ ") + c["detail"], flush=True)
    fails = sum(1 for r in rows if r["status"] == "FAIL")
    skips = sum(1 for r in rows if r["status"] == "SKIP")
    print(
        f"\n{len(rows) - fails - skips}/{len(rows) - skips} 통과"
        + (f" · SKIP {skips}" if skips else "")
        + (f" · FAIL {fails}" if fails else "")
        + f" · 요약 → {outdir / 'summary.json'}",
        flush=True,
    )
    if fails:
        raise SystemExit(1)


def _default_procs():
    """--procs 기본 — PIPE_PROCS(설정 객체, auto·빈 값 = None) 글자로, 없으면 "auto"(S7c — 받는 쪽 resolve_procs가 같은 글자를 읽음)."""
    v = C.cfg().runtime.pipe_procs
    return C.render(v) if v is not None else "auto"


def _default_workers():
    """--workers 기본 — NIGHT_WORKERS → PIPE_WORKERS 중 준 값(설정 객체) 글자로, 없으면 "4"(S7c — 옛 `get(N) or get(P) or "4"`)."""
    v = pc.given("NIGHT_WORKERS")
    if v is None:
        v = C.given("PIPE_WORKERS")
    return C.render(v) if v is not None else "4"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    src = C.cfg().paths.doc_dir_prepared or "output/prepared"
    for name in ("compare-parse", "compare-all", "run-stack"):
        p = sub.add_parser(name)
        p.add_argument("--src", default=src)
        p.add_argument("--procs", default=_default_procs(), help="CPU 엔진 프로세스 수 · auto = CPU·메모리(cgroup) 기준")
        p.add_argument("--skip-parse", action="store_true", help="파싱은 이미 했으면 건너뜀")
        if name != "run-stack":
            p.add_argument("--engines", default="", help="비우면 핵심 엔진(registry.CORE) · all = 전부 · candidates = stack.json 선정+후보")
            p.add_argument("--top", default="4")
        else:
            p.add_argument("--pg", action="store_true", help="pgvector에 배포·적재까지(지정 없어도 Docker pgvector가 떠 있으면 기본)")
            p.add_argument("--local", action="store_true", help="pgvector가 떠 있어도 로컬 묶음까지만")
            p.add_argument("--replace", action="store_true")
            p.add_argument("--no-prune", action="store_true", help=argparse.SUPPRESS)  # pl-13 호환 — 무시
            p.add_argument("--path-prefix", default=pc.cfg().load.edw_path_prefix)
    p = sub.add_parser("night", help="새벽 파싱 배치(GPU 모델 API만, LLM 없음, 마감 시각에 멈춤 — 다음 밤은 문서 대장 기준으로 다시 고름)")
    p.add_argument("--src", default=src)
    p.add_argument(
        "--source",
        default=pc.cfg().extract.input_source or None,
        help="파싱할 원본 위치 — 폴더·s3://버킷/접두·rdb:csv:<경로>·rdb:<표> (parse 모듈과 같음)",
    )
    p.add_argument("--source-limit", type=int, default=pc.cfg().extract.source_limit, help="원본 몇 건만")
    p.add_argument("--mode", default=C.cfg().store.run_mode or "prod", choices=["prod", "test"])
    p.add_argument("--engines", default="", help="비우면 stack.json 선정 엔진 + 후보(candidates)")
    p.add_argument("--deadline", default=pc.cfg().night.deadline)
    p.add_argument("--procs", default=_default_procs(), help="CPU 엔진 프로세스 수 · auto = CPU·메모리(cgroup) 기준(common/resources.py)")
    p.add_argument("--workers", default=_default_workers(), help="동시 처리 문서 수(문서 안 엔진들은 늘 동시에)")
    p.add_argument("--vlm-concurrency", type=int, default=pc.cfg().night.vlm_concurrency, help="문서 하나의 쪽 동시 요청 수")
    p.add_argument(
        "--no-structure",
        action="store_true",
        help="파싱+publish만(기본은 파싱 뒤 대표 파싱·publish·구조화·임베딩(API) → PostgreSQL 적재까지)",
    )
    p.add_argument("--no-publish", action="store_true", help="OS+EDW publish 건너뜀 (기본: 대표 파싱 직후 실행)")
    p.add_argument("--pg", action="store_true", help="구조화 뒤 pgvector 적재까지(지정 없어도 Docker pgvector가 떠 있으면 기본)")
    p.add_argument("--local", action="store_true", help="pgvector가 떠 있어도 로컬 묶음까지만")
    p.add_argument("--no-prune", action="store_true", help=argparse.SUPPRESS)  # pl-13 호환 — 무시
    for name, hlp in (
        ("parse", "파싱 모듈 1회(트리거): 파싱 → 채점 → 대표 결과 → 끝 표시 · 임베딩·DB 없음"),
        ("structure", "구조화 모듈 1회(트리거): 대표 결과 → 청킹·임베딩·그래프 묶음 · 새 파싱 결과 없으면 건너뜀"),
        ("load", "적재 모듈 1회(트리거): 묶음 → PostgreSQL(pgvector) · 새 묶음 없으면 건너뜀"),
    ):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--src", default=src)
        p.add_argument("--force", action="store_true", help="앞 모듈 결과가 그대로여도 다시")
        p.add_argument("--deadline", default=None, help="HH:MM — 넘으면 멈춤(종료 코드 75, 다음 실행이 이어 감). 새벽 배치용")
        if name == "parse":
            p.add_argument(
                "--source",
                default=pc.cfg().extract.input_source or None,
                help="파싱할 원본 위치 — 폴더(같은 서버 샘플) · s3://버킷/접두(Object Storage) · rdb:<표>(RDB 문서 위치 메타로 질의, AD44) · "
                "rdb:*(common/sources.json의 enabled 원천 전부, SI41) · rdb:<이름>(sources.json에 등록된 원천 하나). "
                "주면 가져오기·중복 확인·방향 보정부터",
            )
            p.add_argument("--source-limit", type=int, default=pc.cfg().extract.source_limit, help="원본 몇 건만(Object Storage 시험)")
            p.add_argument(
                "--mode",
                default=C.cfg().store.run_mode or "prod",
                choices=["prod", "test"],
                help="test = 대상이 50건 이상이면 파일 형식별 5건씩만(TEST_MIN_DOCS·TEST_PER_TYPE) · prod = 전부",
            )
            p.add_argument("--engines", default="")
            p.add_argument("--procs", default=_default_procs())
            p.add_argument("--workers", default=_default_workers())
            p.add_argument("--vlm-concurrency", type=int, default=pc.cfg().night.vlm_concurrency)
            p.add_argument(
                "--max-new",
                type=lambda x: int(x or 0),
                default=pc.cfg().extract.max_new,
                help="이번 실행에서 처음 파싱할 문서 수 상한(0 = 제한 없음)",
            )
        if name == "structure":
            p.add_argument("--path-prefix", default=pc.cfg().load.edw_path_prefix)
        if name == "load":
            p.add_argument("--replace", action="store_true")
            p.add_argument("--no-prune", action="store_true", help=argparse.SUPPRESS)  # pl-13 호환 — 무시
    p = sub.add_parser("set-stack")
    p.add_argument("--from-selection", action="store_true")
    p.add_argument("--parse", help='".pdf_text=pymupdf,pdfplumber;.docx=office;…"')
    for k in ("name", "chunk", "embed", "graph", "retrieve"):
        p.add_argument(f"--{k}")
    p.add_argument("--k", type=int)
    p.add_argument("--activate", type=int, metavar="N", help="서버 — 판 N을 다시 활성으로(되돌리기)")
    p.add_argument("--reason", help="서버 — 바꾸는 이유(필수, 판 행·실행 기록에 남음)")
    p.add_argument("--by", help="서버 — 누가(없으면 OS 사용자)")
    p = sub.add_parser("show-stack")
    p.add_argument("--history", type=int, default=5, metavar="N", help="서버 — 최근 판 N개(0 = 안 보임)")
    p = sub.add_parser("set-sources", help="원천 목록 바꾸기 — 서버 = 판 표 struct.source_version 새 판·활성, PC = 파일(S8b)")
    p.add_argument("--file", help="원천 목록 json(목록 — resources/mappings/sources.json 모양)")
    p.add_argument("--name", help="서버 — 판 이름(없으면 파일 이름)")
    p.add_argument("--activate", type=int, metavar="N", help="서버 — 판 N을 다시 활성으로(되돌리기)")
    p.add_argument("--check-columns", action="store_true", help="회사 DB INFORMATION_SCHEMA로 표·열 이름이 있는지(값 안 읽음 — 선택)")
    p.add_argument("--reason", help="서버 — 바꾸는 이유(필수)")
    p.add_argument("--by", help="서버 — 누가(없으면 OS 사용자)")
    p = sub.add_parser("show-sources")
    p.add_argument("--history", type=int, default=5, metavar="N", help="서버 — 최근 판 N개(0 = 안 보임)")
    p = sub.add_parser(
        "selftest", help="서버 반입 시험(tests/server — 이 이미지 폴더 + common)을 파일마다 — PASS/FAIL 표, 실패 있으면 종료 코드 1"
    )
    p.add_argument("--only", action="append", metavar="이름 조각", help="이름에 이 조각이 든 사례만(여러 번)")
    p = sub.add_parser(
        "smoke",
        help="--src(기본 DOC_DIR) 실문서 폴더를 이 이미지에 있는 모듈로 — 사람이 읽는 요약(+ expected.json 있으면 PASS/FAIL), 실문서 전 와이어링 점검",
    )
    p.add_argument("--src", default=None, help="실문서 폴더(기본 DOC_DIR env)")
    p.add_argument(
        "--real-models",
        action="store_true",
        help="pipeline.env의 내부망 모델 엔드포인트로(기본은 모델 필요 엔진을 건너뜀 — 외부·유료 호출은 항상 차단)",
    )
    a = ap.parse_args(argv)
    if a.cmd != "selftest":  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(selftest는 시험이라 뺌)
        from common.config.settings import require_run_env

        require_run_env("pipeline.cli", sections=("pipeline",))  # 서버면 설정 검증 실패도 거부(S7e2 U-1)
    {
        "compare-parse": compare_parse,
        "compare-all": compare_all,
        "set-stack": set_stack,
        "show-stack": show_stack,
        "set-sources": set_sources,
        "show-sources": show_sources,
        "night": night,
        "run-stack": run_stack,
        "selftest": selftest,
        "smoke": smoke,
        "parse": parse_module,
        "structure": structure_module,
        "load": load_module,
    }[a.cmd](a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 한 번 실행 덮기, 서버 포함 · 호스트 run_docs.py 문서별 파싱이 결과 폴더 등을 넘김)
    utf8_stdout()
    from common.core.runlog import session

    with session("pipeline"):
        main()
