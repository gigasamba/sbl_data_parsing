#!/usr/bin/env python3
"""검색 CLI — 질문 → 근거(ask)·문항 세트 검색 시험(test-stack). S5(10-26, T-15 — D-021 ④)에 파이프라인 진입점
(pipeline/cli.py)에서 옮김: 파이프라인 CLI가 검색 코드(mcp_server)를 import하지 않게(refactor_plan 2-2 — pipeline ↔ mcp_server
import 금지). 함수 내용은 그대로 옮겼다(옛 pipeline/cli.py의 ask·_ask_mcp·_ask_edw(지금 _ask_cosine)·test_stack·Retriever·table_md, 그리고 이
파일이 함께 쓰는 sh·connect 사본 — sh·connect는 파이프라인 명령도 써서 pipeline/cli.py에도 남음).

  ask         질문 → 근거 청크 + 원본 경로·쪽·줄·쪽 안 위치(bbox)·요약 — 로컬 묶음 또는 pgvector. 답변은
              검색만(10-13 답변 경로 통일 1단계 — 답변은 서빙되는 Answer Agent(rag_qa — valid_env/answer_test/rag_qa, 점검 validation/e2e/answer_gen.py)만, 중복 경로 제거).
              기본(로컬·pgvector 하이브리드)은 mcp_server.services.search.search_svc.do_search()에 위임(AR10) — MCP와 같은 결과,
              --retrieve cosine만 예전 경로(EDW 벡터 --edw·--edw-client는 10-29 삭제 — ops.md#op-03)
  test-stack  문항(자동 생성 또는 --questions)으로 ask 전체 → 정답 포함·출처 일치·지연 → output/stack_test.md
사용: python -m mcp_server.cli.ask ask --pg --bundle output/<이름>/bundle --k 3 --q "<질문>"
      python -m mcp_server.cli.ask test-stack [--questions output/eval/questions.jsonl]
(이미지 안: 엔트리포인트 명령 ask·test-stack이 이 모듈을 부름 — deploy/docker/entrypoint.sh)
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from common.config import settings as C  # 설정 객체(S7d)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT

PY = sys.executable


def _stack():
    """엔진 구성 활성 판(S8b — 서버 = 판 표 struct.stack_version, PC = 파일) → body + name(옛 stack.json 꼴)."""
    from common.store.db import cfgtables

    cur = cfgtables.active("stack")
    return cur.named()


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


def Retriever(*args, **kw):
    """검색(모듈 ④) — 쓸 때만 불러옴(파싱 이미지에는 검색 모듈이 없음)."""
    from mcp_server.services.search.retriever import Retriever as R

    return R(*args, **kw)


def table_md(g):
    """표 집계 결과 → 마크다운 표(+ 합계 줄)."""
    rows = ["| " + " | ".join(g["columns"]) + " |", "|" + "---|" * len(g["columns"])]
    rows += ["| " + " | ".join("—" if c is None else str(c) for c in r) + " |" for r in g["rows"]]
    if g.get("totals"):
        rows.append("합계: " + " · ".join(f"{k} {v}" for k, v in g["totals"].items()))
    return "\n".join(rows)


def connect(a):
    """연결 기본값(백로그 E6 · 사용자 2026-10-01): --pg·--local 지정이 없으면 Docker에 떠 있는 pgvector에 연결,
    없으면 로컬 묶음. → common/services.py"""
    from common.store import services

    services.connect(a)


def ask(a):
    """질문 → 근거(파일·쪽·줄·bbox·점수·via) · 집계 포함. 기본(로컬 묶음·pgvector 하이브리드)은
    AR10(구조 리뷰 10-12 round4 QA095) — MCP search/mcp_server.do_search()에 그대로 위임한다(두 경로가
    같은 질문에 다른 순위를 주던 분기 제거). --retrieve cosine은 do_search에 없어 예전 R.search 경로를 그대로 둔다."""
    if a.retrieve == "cosine":
        return _ask_cosine(a)
    return _ask_mcp(a)


def _ask_mcp(a):
    """기본 경로 — MCP_STORE·MCP_BUNDLE만 ask()의 --pg/--local/--bundle에 맞춰 세팅하고 do_search()를 그대로 부름
    (mcp_server._build_retriever가 이 둘로 저장소를 고름 — modules/search/mcp_server.py ~L105-130). 질의 기록은
    do_search() 안 _log()가 이미 함(qa_log.append + PG qa_log INSERT) — 여기서 다시 넣지 않음(중복 기록 방지)."""
    st = _stack()
    C.put(MCP_STORE="local" if a.local else ("pg" if a.pg else ""), MCP_BUNDLE=str(a.bundle))  # S7e2 — 덮기 파일(이 프로세스·하위 프로세스)
    from mcp_server.services.search import search_svc as MCP

    k = a.k or st.get("k", 8)
    methods = None
    res = MCP.do_search(a.q, k, methods=methods)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(f"질문: {res['question']}  ({res.get('store')} · 방법 {','.join(res.get('methods') or [])}, 검색 {res['ms']:.1f} ms)")
    for i, s in enumerate(res.get("subs") or [], 1):
        print(f"  하위 질문 {i}: {s}")
    for n in res.get("notes") or []:
        print(f"  note: {n}")
    for e in res.get("evidence") or []:
        if e.get("kind"):  # 집계(aggregate·aggregate_llm) — AG.table_text가 표·합계를 text에 이미 붙여 둠
            print(f"\n집계({e['kind']}): {e.get('answer')} {e.get('unit') or ''}".rstrip())
            print(e.get("text") or "")
            print()
        else:
            rank = f"[{e['rank']}]" if e.get("rank") is not None else "   "
            print(
                f"{rank} {e.get('file_path')}  p.{e.get('page')} L.{e.get('line')}"
                + (f"  bbox={e['bbox']}" if e.get("bbox") else "")
                + (f"  ({e['via']})" if e.get("via") else "")
                + (f"  §{e['section']}" if e.get("section") else "")
            )
            print("    " + (e.get("text") or "").replace("\n", " ")[:220])
    if res.get("evidence_status"):
        print(f"\n근거 상태: {res['evidence_status']}")


def _ask_cosine(a):
    """예전 경로(그대로) — --retrieve cosine만(do_search에 없음)."""
    connect(a)
    st = _stack()
    R = Retriever(a.bundle, a.retrieve or st.get("retrieve", "hybrid"), a.pg)
    k = a.k or st.get("k", 8)
    hits, ms = R.search(a.q, k)
    from mcp_server.services.search import aggregate as AG

    agg_of = lambda q: AG.struct(q) or (AG.pg(R.pg, q) if R.pg else AG.local(a.bundle, q))  # 정형 저장소 질문 먼저(X1, MCP와 같은 규칙)
    agg = agg_of(a.q)  # 건수·합계 질문이면 SQL 집계(검색 결과는 함께 보여 줌)
    subs, sub_aggs = [], []  # 질문 분해는 10-29에 지움(응답 칸은 유지)
    res = {
        "question": a.q,
        "subs": subs,
        "aggregate": agg,
        "sub_aggregates": sub_aggs,
        "source": "pgvector" if a.pg else "local",
        "retrieve": R.retrieve,
        "ms": round(ms, 1),
        "hits": hits,
    }
    if a.pg:  # 개발 서버 질의 기록(qa_log)
        R.pg.q(
            f"INSERT INTO {R.pg.schema}.qa_log(question, stack_name, k, hits, answer, search_ms, asked_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                a.q,
                st.get("name"),
                len(hits),
                json.dumps([{"chunk_id": h["chunk_ref"], "rank": h["rank"], "score": h.get("score")} for h in hits]),
                res.get("answer"),
                res["ms"],
                os.environ.get("USERNAME") or os.environ.get("USER"),
            ),
        )  # env 남김 — OS 값
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(f"질문: {a.q}  ({res['source']} · {R.retrieve}, 검색 {ms:.1f} ms)")
    for i, s in enumerate(subs, 1):
        print(f"  하위 질문 {i}: {s}")
    for g in [agg] + sub_aggs if agg else sub_aggs:
        print(
            f"\n집계({g['kind']} · {g['target']}"
            + (f" · 하위 질문 {g['sub']}" if g.get("sub") else "")
            + f"): {g['answer']} {g['unit']}"
            + (f"  ※ {g['note']}" if g["note"] else "")
        )
        if g.get("columns"):
            print(table_md(g))
        for e in g["evidence"]:
            print(
                f"  - {e['contract_no']}: {e['file_path']}"
                + (f" p.{e['page']} L.{e['line']}" if e.get("line") else "")
                + (f" · 표 행 {e['items']}" if e.get("items") else "")
            )
        print()
    for h in hits:
        print(
            f"[{h['rank']}] {h['file_path']}  p.{h['page']} L.{h['line']}"
            + (f"  bbox={h['bbox']}" if h["bbox"] else "")
            + (f"  ({h['via']})" if h.get("via") else "")
            + (f"  §{h['section']}" if h.get("section") else "")
        )
        print("    " + h["text"].replace("\n", " ")[:220])


def test_stack(a):
    connect(a)
    from common.core import text as S

    qpath = Path(a.questions)
    if not qpath.exists():
        sh("pipeline.eval.auto_questions", "--src", a.src, "--out", qpath)
    qs = [json.loads(x) for x in qpath.read_text(encoding="utf-8").splitlines() if x.strip()][: a.limit]
    st0 = _stack()
    R = Retriever(a.bundle, a.retrieve or st0.get("retrieve", "hybrid"), a.pg)
    rows, ms = [], []
    for q in qs:
        hits, t = R.search(q.get("query") or q["question"], a.k)
        ms.append(t)
        gold = S.normalize_value(str(q.get("answer", "")))
        ev = {(Path(e.get("file", "")).name, e.get("page")) for e in q.get("gold_evidence") or []}
        agg_ok = None
        if q.get("category") in ("count", "sum"):
            from mcp_server.services.search import aggregate as AG

            ag = AG.pg(R.pg, q["question"]) if R.pg else AG.local(a.bundle, q["question"])
            try:
                g = float(q.get("answer"))
                agg_ok = bool(ag) and abs(float(ag["answer"]) - g) <= max(1e-9, abs(g) * (q.get("tolerance") or 0))
            except (TypeError, ValueError):
                agg_ok = False
            # 건수·합계의 답은 문서에 그대로 적혀 있지 않음 → 근거 문서(gold_evidence 파일)를 상위 k가 전부 가져왔나
            files = {f for f, _ in ev}
            ranks = {Path(h["file_path"]).name: h["rank"] for h in reversed(hits)}
            hit = {"rank": max(ranks[f] for f in files)} if files and files <= set(ranks) else None
        else:
            hit = next((h for h in hits if gold and gold in S.normalize_value(h["text"])), None)
        src_ok = (
            any(Path(h["file_path"]).name == f and (p is None or h["page"] is None or p == h["page"]) for h in hits for f, p in ev)
            if ev
            else None
        )  # 쪽은 둘 다 있을 때만 비교
        rows.append(
            {
                "id": q["id"],
                "category": q.get("category"),
                "question": q["question"],
                "gold": q.get("answer"),
                "found": bool(hit),
                "rank": hit["rank"] if hit else None,
                "source_match": src_ok,
                "agg_ok": agg_ok,
                "top": [{k: h[k] for k in ("file_path", "page", "line", "bbox")} for h in hits[:3]],
                "ms": round(t, 1),
            }
        )
    by = {}
    for r in rows:
        by.setdefault(r["category"], []).append(r)
    pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else 0
    st = _stack()
    lines = [
        f"# 고정 스택 기본 테스트 — {st.get('name', '')} ({time.strftime('%Y-%m-%d %H:%M')}, "
        f"{'pgvector' if a.pg else '로컬'} · 검색 {R.retrieve})",
        "",
        f"문항 {len(rows)} · 상위 k={a.k} · 검색 p50 {pct(ms, 0.5):.1f} ms · p95 {pct(ms, 0.95):.1f} ms(질의 임베딩 제외)",
        "",
        "| 유형 | 문항 | 정답 근거 찾음(값: 상위 k에 정답 값 · 건수·합계: 근거 문서 전부 상위 k) | 평균 순위 | 출처(파일·쪽) 일치 | 집계(SQL) 정답 |",
        "|---|---|---|---|---|---|",
    ]
    for cat, rs in sorted(by.items(), key=lambda x: str(x[0])):
        f = [r for r in rs if r["found"]]
        sm = [r for r in rs if r["source_match"] is not None]
        ag = [r for r in rs if r.get("agg_ok") is not None]
        agc = f"{sum(r['agg_ok'] for r in ag)}/{len(ag)}" if ag else "—"
        lines.append(
            f"| {cat} | {len(rs)} | {len(f)}/{len(rs)} | {statistics.mean(r['rank'] for r in f):.1f} | "
            + (f"{sum(r['source_match'] for r in sm)}/{len(sm)}" if sm else "—")
            + f" | {agc} |"
            if f
            else f"| {cat} | {len(rs)} | 0/{len(rs)} | — | — | {agc} |"
        )
    miss = [r for r in rows if not r["found"]][:15]
    if miss:
        lines += ["", "## 근거를 못 찾은 문항(상위 15)", ""] + [
            f"- {r['id']}: {r['question']} (정답 {r['gold']}) → 1위 {r['top'][0]['file_path'] if r['top'] else '—'}" for r in miss
        ]
    Path("output").mkdir(exist_ok=True)
    Path("output/stack_test.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path("output/stack_test.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print("\n".join(lines))
    from common.core.runlog import note

    note(f"고정 스택 테스트: 정답 근거 {sum(r['found'] for r in rows)}/{len(rows)} · p50 {pct(ms, 0.5):.1f} ms → output/stack_test.md")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    src = C.cfg().paths.doc_dir_prepared or "output/prepared"  # S7d — 설정 객체
    for name in ("ask", "test-stack"):
        p = sub.add_parser(name)
        p.add_argument("--bundle", default="output/edw/bundle")
        p.add_argument("--pg", action="store_true", help="pgvector에서 검색(지정 없어도 Docker pgvector가 떠 있으면 기본)")
        p.add_argument("--local", action="store_true", help="로컬 묶음(output/edw/bundle)에서 검색 — PG 설정이 있어도")
        p.add_argument("--retrieve", choices=["cosine", "hybrid"], help="기본 = stack.json retrieve(없으면 hybrid)")
        p.add_argument("--k", type=int, default=8, help="근거 수 — MCP search 기본과 같게 8(AR5 측정: k=8이 k=10과 같거나 나음, 잘림 적음)")
        if name == "ask":
            p.add_argument("--q", required=True)
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--questions", default="output/eval/questions.jsonl")
            p.add_argument("--src", default=src)
            p.add_argument("--limit", type=int, default=200)
    a = ap.parse_args(argv)
    {"ask": ask, "test-stack": test_stack}[a.cmd](a)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("pipeline"):  # 옛 pipeline/cli.py와 같은 실행 기록 이름(output/logs/<시각>_pipeline.log)
        main()
