#!/usr/bin/env python3
"""문서 대장(registry) CLI — AD16 1단계. 기존 파싱 산출물(중복 확인 캐시·원본 위치 manifest·대표 결과 색인)을
읽기만 해서 doc_registry(로컬 SQLite 또는 PostgreSQL, common/structdb.py와 같은 접속)를 새로 고친다. 파싱이
new/changed/deleted를 정하는 방식은 안 바꾼다(AD17 다음 단계).

DOC_REGISTRY(기본 켬, =0으로 끔) — =0이면 아무 파일도 안 읽고 안 쓰고 끝(--force로 무시, 시험용).
접속: common/structdb.py와 같음 — STRUCT_BACKEND(기본 pg, 연결 안 되면 자동 SQLite 대체)·STRUCT_DB(SQLite 경로)·
PG_*(공용 PostgreSQL). 표는 doc_contract_link·doc_location과 같은 PG_SCHEMA(struct)에 doc_registry·doc_registry_seen으로 생김.

사용: python cli/registry.py build [--out out] [--db 경로] [--build-id ID]
      python cli/registry.py show <doc_key>
      python cli/registry.py diff [--out out]
      python cli/registry.py hide <doc_key> --by <누가> [--reason <왜>]     (OP1 — 검색 제외, 색인 행은 안 지움)
      python cli/registry.py unhide <doc_key> --by <누가> [--reason <왜>]   (복구 — deleted는 build()가 자동 hide, 그 밖엔 사람이 명시)
      python cli/registry.py report --since YYYY-MM-DD [--until YYYY-MM-DD] [--plain-names] [--out <md 경로>]
                                                                             (DET1 Fix3 — 날짜별 변경 보고, 읽기만)
"""

import argparse
import hashlib
import json
from pathlib import Path

from common.config.settings import cfg  # 설정 객체(S7d — common 칸)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from common.store import registry as REG  # noqa: E402
from common.store.structdb import StructDBError, ensure_registry_schema, open_backend  # noqa: E402
from mcp_server.services.search import registry as RREG  # noqa: E402 — show·report·unhide(10-14 common.store.registry에서 옮김, R만 씀)


def rag_out():
    """RAG_OUT(없으면 dev/out) — tools/parse_agent_tools.rag_out()과 같은 관례(이 파일은 rag-core에도 들어가므로
    rag-parse 전용 tools/를 import하지 않고 그대로 재선언 — C3 이미지 경계)."""
    base = cfg().paths.output_root  # S7d — 설정 객체(글자 그대로 — 없음·''은 아래 `if base`로 같음)
    return Path(base) if base else ROOT / "output"


def _print_diff(diff):
    # AD17① — touched(원본 바이트는 같고 날짜만 바뀜)는 건수만(목록 없음) · "changed"는 새 판·재파싱 후보만(요건 절)
    print(
        f"[registry] 새 {len(diff['new'])} · 날짜만 바뀜(touched) {len(diff.get('touched') or [])} · "
        f"바뀜 {len(diff['changed'])} · 그대로 {len(diff['unchanged'])} · 사라짐 {len(diff['deleted'])}"
    )
    for label in ("new", "changed", "deleted"):
        for k in diff[label][:20]:
            print(f"  {label}: {k[:16]}…")
        if len(diff[label]) > 20:
            print(f"  … {label} {len(diff[label]) - 20}건 더")
    editions = diff.get("editions") or {}  # AD17②(10-08) — diff["new"] 중 전 판과 이름이 같아 대표 글을 비교한 것만
    if editions:
        from collections import Counter

        c = Counter(editions.values())
        print(
            f"[registry] 판 비교(AD17②): 같음(same, 새 판 아님) {c.get('same', 0)} · "
            f"값만 바뀜(changed_values) {c.get('changed_values', 0)} · 글이 다름(different) {c.get('different', 0)}"
        )


def _doc_label(d, plain):
    """§3 공통 규칙(run_board.py와 같은 해시 — doc-xxxxxxxx) — 기본은 이름(names, 없으면 doc_key
    앞 16자) 해시, --plain-names면 원래 이름 그대로."""
    names = d.get("names") or []
    label = ",".join(names) if names else d["doc_key"][:16] + "…"
    return label if plain else "doc-" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:8]


def _print_report(rep, plain=False):
    print(
        f"[registry] 보고 {rep['since']}~{rep['until']} — 새 {rep['new']} · 바뀜 {rep['changed']} · "
        f"날짜만 바뀜(touched) {rep['touched']}(과거 이력 추적 대상 아님 — registry.py report_by_date 참고) · "
        f"사라짐 {rep['deleted']}"
    )
    for d in rep["docs"]:
        print(f"  {d['event']}: {_doc_label(d, plain)} ({d['seen_at']})")


def _render_report_md(rep, plain=False):
    lines = [
        f"# 문서 대장 변경 보고 — {rep['since']}~{rep['until']}",
        "",
        f"- 새 {rep['new']} · 바뀜 {rep['changed']} · 날짜만 바뀜(touched) {rep['touched']}(과거 이력 추적 대상 아님) · "
        f"사라짐 {rep['deleted']}",
        "",
        "| 문서 | 사건 | 날짜 |",
        "|---|---|---|",
    ]
    for d in rep["docs"]:
        lines.append(f"| {_doc_label(d, plain)} | {d['event']} | {d['seen_at']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "show", "diff", "hide", "unhide", "report"])
    ap.add_argument("doc_key", nargs="?", default=None)
    ap.add_argument(
        "--out", default=None, help="build·diff — 산출물 루트(기본 RAG_OUT·output/) · report — 보고 markdown 경로(선택, 없으면 stdout만)"
    )
    ap.add_argument("--db", default=None, help="STRUCT_BACKEND=sqlite일 때 SQLite 경로(기본 STRUCT_DB)")
    ap.add_argument("--build-id", default=None, help="생략하면 UTC 초 단위 타임스탬프")
    ap.add_argument("--by", default=None, help="hide·unhide — 누가(사람 아이디 등, 감사 기록)")
    ap.add_argument("--reason", default=None, help="hide·unhide — 왜(감사 기록)")
    ap.add_argument("--since", default=None, help="report — YYYY-MM-DD(필수)")
    ap.add_argument("--until", default=None, help="report — YYYY-MM-DD(생략하면 --since와 같음, 그 날 하루)")
    ap.add_argument("--plain-names", action="store_true", help="report — 문서 이름을 해시 대신 원래 이름으로")
    ap.add_argument("--force", action="store_true", help="DOC_REGISTRY=0이어도 실행(시험용)")
    a = ap.parse_args(argv)
    if not (a.force or cfg().store.doc_registry):  # S7d — 켜기 칸(옛 strip·lower 뒤 "", 0, none, false이면 끔과 같은 판정)
        print("[registry] DOC_REGISTRY=0 — 아무것도 안 함(--force로 무시)")
        return
    out_dir = Path(a.out) if a.out else rag_out()
    db = open_backend(a.db)
    try:
        if a.cmd in ("build", "hide", "unhide"):  # S8a — 쓰기 전 struct 판 확인(PostgreSQL만 — 판 기록 없음은 경고 뒤 계속)
            from common.store.db import dbtool

            dbtool.require_struct(db)
        ensure_registry_schema(
            db
        )  # SCHEMA(ensure_schema) 전체가 아니라 doc_registry·doc_registry_seen만(독립 검토 BLOCK 10-08) — S8a: PG는 표가 있는지만
    except StructDBError as e:
        db.close()
        raise SystemExit(f"[registry] {e}") from e
    try:
        if a.cmd == "show":
            if not a.doc_key:
                raise SystemExit("show에는 doc_key 필요")
            row, seen = RREG.history(db, a.doc_key)
            if not row:
                print(f"[registry] 없음 — {a.doc_key}")
                return
            print(json.dumps(row, ensure_ascii=False, indent=1))
            print(f"-- 판 이력 {len(seen)}건 --")
            for s in seen:
                print(json.dumps(s, ensure_ascii=False))
        elif a.cmd == "diff":
            observed = REG.scan(out_dir)
            _print_diff(REG.nightly_plan(db, observed))  # diff_against() 결과(+ 이번 밤 파싱 대상)
        elif a.cmd == "report":
            if not a.since:
                raise SystemExit("report에는 --since YYYY-MM-DD 필요")
            rep = RREG.report_by_date(db, a.since, a.until)
            _print_report(rep, plain=a.plain_names)
            if a.out:
                Path(a.out).parent.mkdir(parents=True, exist_ok=True)
                Path(a.out).write_text(_render_report_md(rep, plain=a.plain_names), encoding="utf-8")
                print(f"[registry] 씀: {a.out}")
        elif a.cmd in ("hide", "unhide"):
            if not a.doc_key:
                raise SystemExit(f"{a.cmd}에는 doc_key 필요")
            if not a.by:
                raise SystemExit(f"{a.cmd}에는 --by 필요(감사 기록 — 누가)")
            (REG.hide if a.cmd == "hide" else RREG.unhide)(db, a.doc_key, by=a.by, reason=a.reason)
            db.commit()
            print(f"[registry] {a.cmd} — {a.doc_key[:16]}… (by={a.by})")
        else:
            diff, build_id = REG.build(out_dir, db, build_id=a.build_id)
            print(f"[registry] build {build_id} · out={out_dir}")
            _print_diff(diff)
    finally:
        db.close()


if __name__ == "__main__":
    utf8_stdout()
    main()
