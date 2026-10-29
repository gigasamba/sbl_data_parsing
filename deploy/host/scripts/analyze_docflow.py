#!/usr/bin/env python3
"""docflow 단계별 소요·큐 대기 분석 — 2026-10-22 사용자 지정.

원본: <run_docs 작업 폴더>/batch_progress/doc_stats.jsonl(단계 이벤트) + doc_<seq>.log(파싱 내부 상세) — 작업 폴더는 run_docs.py와 같게
      settings.yaml pipeline.host.run_docs_dir(SETTINGS_FILE 또는 $SERVER_ENV_DIR/settings.yaml — 호스트 PyYAML 있을 때), 없으면 이 스크립트 옆 test_space/(S7e1)
출력: 문서별 — 파싱 wall · 엔진 Σ(엔진별 상세) · represent 내부(load/merge/fuse/scanfill/post/table/agent + post[figures·charts·dedup·supsub])
      · 나머지(prepare+qa+기동) · 구조화 대기(queue_wait) · 구조·pub 소요 · 대기열 여부
사용: python3 analyze_docflow.py [세부표:--detail]
"""

import json
import re
import sys
from collections import defaultdict

import run_docs  # 같은 폴더(sys.path[0]) — 작업 폴더 규칙을 run_docs.py와 하나로(S7e1 — import에 접속·부수 효과 없음)

_doc, _err = run_docs.read_settings()
if _err:
    print(f"[안내] {_err} — 작업 폴더는 스크립트 옆 test_space/", file=sys.stderr)
PROG = run_docs.work_dir(_doc) / "batch_progress"
DET = "--detail" in sys.argv

ev: defaultdict = defaultdict(dict)
try:
    for ln in open(PROG / "doc_stats.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        ev[r["seq"]][r["event"]] = r
except FileNotFoundError:
    print("doc_stats.jsonl 없음")
    sys.exit(1)

ENG_RE = re.compile(r"^ok\s+(\S+)\s+([\d.]+)s\s+(.*)$")
REP_RE = re.compile(
    r"\[represent\] (\S+).*?(?:load|load \|)=(\S+) merge=(\S+) fuse=(\S+) scanfill=(\S+) post=(\S+) table=(\S+) agent=(\S+)"
)
POST_RE = re.compile(r"post\[(.+)\]")

hdr = f"{'seq':>5} {'wall':>6} {'engΣ':>6} {'.rep':>6} {'기타':>6} | {'구조대기':>8} {'구조':>5} {'pub':>5} |(max VLM콜:슬로우 처리는 엔진별 상세 참고)"
print(hdr)
print("-" * len(hdr) * 2)
tot = {"wall": 0.0, "eng": 0.0, "rep": 0.0, "etc": 0.0, "wait": 0.0, "struct": 0.0, "pub": 0.0}
n_done = n_eng = n_rep = 0
for seq in sorted(ev):
    e = ev[seq]
    if "parse_end" not in e:
        continue
    wall = e["parse_end"].get("sec") or 0
    eng = rep = 0.0
    detail_rows = []
    p = PROG / f"doc_{seq}.log"
    if p.exists():
        eng_times: defaultdict = defaultdict(float)
        rep_line = None
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = ENG_RE.match(ln)
            if m:
                eng_times[m.group(1)] += float(m.group(2))
            elif ln.startswith("[represent]") and "merge=" in ln:
                rep_line = ln
        eng = sum(eng_times.values())
        n_eng += 1
        detail_rows.append(
            "엔진: " + " · ".join(f"{k.replace('_ko', '')}{v:.0f}s" for k, v in sorted(eng_times.items(), key=lambda x: -x[1]))
        )
        if rep_line:
            m = re.search(
                r"load\S*\s*=?\s*([\d.]+)s.*merge=([\d.]+)s fuse=([\d.]+)s scanfill=([\d.]+)s post=([\d.]+)s table=([\d.]+)s agent=([\d.]+)s",
                rep_line,
            )
            if m:
                stages = {
                    k: float(m.group(i))
                    for k, i in (("load", 1), ("merge", 2), ("fuse", 3), ("scanfill", 4), ("post", 5), ("table", 6), ("agent", 7))
                }
                sub = {}
                pm = POST_RE.search(rep_line)
                if pm:
                    for kv in pm.group(1).split():
                        k, _, v = kv.partition("=")
                        sub[k] = float(v)
                rep = sum(stages.values())
                n_rep += 1
                detail_rows.append("represent: " + " · ".join(f"{k}={v:.1f}s" for k, v in stages.items() if v > 0.05))
                if sub:
                    detail_rows.append("post내부: " + " · ".join(f"{k}={v:.1f}s" for k, v in sub.items() if v > 0.05))
    etc = max(wall - eng - rep, 0)
    wait = e.get("struct_start", {}).get("queue_wait") or 0
    st = e.get("struct_end", {}).get("sec") or 0
    pub = e.get("pub_end", {}).get("sec") or 0
    print(
        f"{seq:>5} {wall / 60:5.1f}분 {eng / 60:5.1f}분 {rep / 60:5.1f}분 {etc / 60:5.1f}분 | "
        f"{wait:7.0f}s {st / 60:4.1f}분 {pub / 60:4.1f}분" + (" *파싱FAIL" if not e["parse_end"].get("ok") else "")
    )
    if DET:
        for d in detail_rows:
            print(f"        {d}")
    tot["wall"] += wall
    tot["eng"] += eng
    tot["rep"] += rep
    tot["etc"] += etc
    tot["wait"] += wait
    tot["struct"] += st
    tot["pub"] += pub
    if "pub_end" in e:
        n_done += 1

if n_eng:
    print("-" * 90)
    print(
        f"평균({n_eng}건 파싱완료 기준): wall {tot['wall'] / 60 / n_eng:.1f}분 = 엔진 {tot['eng'] / 60 / n_eng:.1f}분"
        f" + represent {tot['rep'] / 60 / n_eng:.1f}분 + 기타(prepare·qa) {tot['etc'] / 60 / n_eng:.1f}분"
        + (
            f" · 구조대기 {tot['wait'] / n_done:.0f}s · 구조 {tot['struct'] / 60 / n_done:.1f}분 · pub {tot['pub'] / 60 / n_done:.1f}분"
            if n_done
            else ""
        )
    )
