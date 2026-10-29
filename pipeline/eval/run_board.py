#!/usr/bin/env python3
"""파싱 실행판 — 한 번 돌린 결과(output/)를 단계별 그림으로: 어디서 막혔나 · 개발 문제(설치·예외·시간 초과·결과 없음)인가
정확도 문제(돌았는데 점수 낮음)인가 · 정답이 있는 문서는 정답 대비 얼마나 맞았나. LLM 0회, 표준 라이브러리만(폐쇄망 서버 그대로).

읽는 것(없으면 그 단계는 '실행 안 함'으로 표시 — 오류 아님):
  dedup/groups.csv · prepared/skipped.jsonl · parse/runs.jsonl · parse/parse_summary.json · parse/_rep/index.json
  · edw/bundle/meta.json·docs.jsonl · eval/gold_score/score.json(score_gold.py --gold <정답 폴더>) · eval/mcp_eval/*.json(최신) · runlog.jsonl
분류 규칙: 정책 건너뜀 = 중복 자동 제외·DRM·암호(문제 아님) · 개발 = 환경(미설치·미설정)·예외 실패·시간 초과·결과 없음(성공 엔진 없음·색인 누락)
  · 정확도 = 교차 정확도 < criteria.json run.cross_acc_full(0.95, parse_qa FULL과 같은 값) 또는 정답 대비 값 재현율·글자 정확도 < --gold-min · 판정 불가 = 비교할 기준 없음.
  막힌 곳 = 순서상 처음으로 도구가 오류·중단으로 끝났거나, 앞 단계는 돌았는데 실행 안 한 단계.
산출: <out>/report/run_board.html 한 파일(외부 자원 없음). 문서 이름은 기본 해시(score_gold와 같은 doc-xxxxxxxx) — --plain-names면 원래 이름.
사용: python cli/run_board.py [--out out] [--gold-score output/eval/gold_score/score.json] [--plain-names]
      [--digest <폴더>] — 날짜·판 폴더(<폴더>/<YYYY-MM-DD>__<판>/)에 run_board.html + summary.json(phase별·전체 요약)을 두고
      <폴더>/INDEX.md에 한 줄 덧붙임 — 수집 서버 파싱이 끝나면 돌리고, 개발 서버가 그 폴더를 가져가 날짜·판으로 쌓음(사용자 10-08).
      python cli/run_board.py --selftest
"""

import argparse
import csv
import hashlib
import html
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from common.core.paths import CRITERIA_FILE  # 판정 문턱값 정본(S2 — resources/config/)
from pipeline import config as pc  # pipeline 칸(S7c — 설정 객체: REPORT_DIGEST_DIR)
from pipeline.shared.phase_report import FIX as ENGINE_FIX
from pipeline.shared.phase_report import (
    kind as err_kind,  # 오류 종류 · 연결 안 된 엔진 조치(옛 PHASE_REPORT C절을 실행판으로, 사용자 10-08)
)
from pipeline.shared.progress import status as run_status  # runs.jsonl 상태 규칙 한 곳(ok·env·timeout·fail)

RUN_CRIT = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))["run"]  # RB3 — 판정 문턱값 정본(코드에 박지 않음)
FULL, GOLD_MIN = RUN_CRIT["cross_acc_full"], RUN_CRIT["gold_min"]
ISSUES = [
    ("policy", "정책 건너뜀"),
    ("encrypted", "암호·DRM"),
    ("corrupt", "손상 의심"),
    ("unsupported", "미지원 형식"),
    ("env", "환경·설치"),
    ("fail", "예외 실패"),
    ("timeout", "시간 초과"),
    ("noout", "결과 없음"),
    ("acc", "정확도 낮음"),
    ("nojudge", "판정 불가"),
]
CLASS = {
    "policy": "policy",
    "encrypted": "src",
    "corrupt": "src",
    "unsupported": "src",
    "env": "dev",
    "fail": "dev",
    "timeout": "dev",
    "noout": "dev",
    "acc": "acc",
    "nojudge": "acc",
}
# 원본 문제(사람 조치 — 코드로 못 고침, 사용자 10-08): 엔진 오류 메시지 → 종류·원인. 문서의 실패 엔진이 '전부' 이 규칙에 걸릴 때만 원본 문제로 본다
# (엔진 하나만 손상이라 하면 그 엔진 문제일 수 있음). 같은 암호 문서도 엔진마다 다르게 말함 — kreuzberg 'workbook is password protected' ·
# calamine 'password error' · anydoc 'document is encrypted' · markitdown/office 'BadZipFile: File is not a zip file'(암호 OOXML은 OLE 컨테이너).
SRC_RULES = [
    (re.compile(r"password|encrypt|암호", re.I), "encrypted", "암호 걸린 문서"),
    (re.compile(r"not a zip file", re.I), "encrypted", "OOXML인데 zip이 아님(암호·DRM 의심)"),
    (
        re.compile(
            r"EOF marker|startxref|truncated|cannot identify image|invalid (?:pdf|header)|corrupt|damaged|bad magic|premature end|data format error|failed to load document",
            re.I,
        ),
        "corrupt",
        "원본 손상 의심",
    ),
]
SKIP_KIND = (
    ("encrypted", "encrypted", "암호 걸린 문서"),
    ("drm", "encrypted", "DRM 보호"),
    ("unsupported", "unsupported", "지원 안 하는 형식"),
    ("archive", "unsupported", "압축 파일(zip 등) — 파싱 대상 아님"),
)


def src_kind(msg):
    """오류 메시지 → (종류, 원인) 또는 None."""
    for rx, k, why in SRC_RULES:
        if rx.search(msg or ""):
            return k, why
    return None


def skip_kind(reason):
    """준비 단계 건너뜀 사유(skipped.jsonl reason) → (종류, 원인). 모르는 사유는 정책 건너뜀."""
    r = (reason or "").lower()
    for key, k, why in SKIP_KIND:
        if key in r:
            return k, f"{why} ({reason})"
    return "policy", reason or "건너뜀"


STAGES = [  # (키, 이름, runlog 도구, 만드는 명령)
    ("dedup", "중복 확인", "dedup", "python modules/parse/dedup.py"),
    ("prepare", "준비 · DRM · 회전", "prepare", "python modules/parse/prepare.py --only output/dedup/keep.txt"),
    ("parse", "엔진 파싱", "run_all", "python modules/parse/run_all.py --src output/prepared"),
    ("qa", "교차 대조", "parse_qa", "python modules/parse/parse_qa.py --src output/prepared"),
    ("rep", "대표 · 후보정", "represent", "python modules/parse/represent.py"),
    ("bundle", "묶음 · 청킹 · 임베딩", "bundle", "python modules/structure/build_bundle.py"),
    ("gold", "정답 대조", "score_gold", "python cli/score_gold.py --gold <정답 폴더>"),
    ("search", "근거 반환 평가", "mcp_eval", "python cli/mcp_eval.py"),
]
E = lambda s: html.escape(str(s))


def _json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonl(p):
    try:
        lines = Path(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _csv(p):
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return None


def load(out, gold_score=None):
    out = Path(out)
    mcp = sorted(
        (out / "eval" / "mcp_eval").glob("[0-9]*.json")
    )  # 시각 이름만 — rca_items_*.json(목록)이 이름순 뒤에 와 board가 죽던 것(e2e baseline_snapshot과 같은 수정)
    done = _json(out / "parse" / "_rep" / "_DONE.json")  # SI23 — 이번 실행 run_id(파싱 모듈 끝 표시) · env가 있으면 그걸 우선
    return {
        "run_id": os.environ.get("PARSE_RUN_ID") or (done or {}).get("run_id"),  # env 남김 — 내부 신호(5-3 H)
        "groups": _csv(out / "dedup" / "groups.csv"),
        "skipped": _jsonl(out / "prepared" / "skipped.jsonl"),
        "runs": _jsonl(out / "parse" / "runs.jsonl"),
        "summary": _json(out / "parse" / "parse_summary.json"),
        "rep": _json(out / "parse" / "_rep" / "index.json"),
        "bundle": _json(out / "edw" / "bundle" / "meta.json"),
        "bdocs": _jsonl(out / "edw" / "bundle" / "docs.jsonl"),
        "gold": _json(gold_score or out / "eval" / "gold_score" / "score.json"),
        "mcp": _json(mcp[-1]) if mcp else None,
        "mcp_file": mcp[-1].name if mcp else None,
        "runlog": _jsonl(out / "runlog.jsonl") or [],
        "e2e": _json(out / "report" / "e2e_summary.json"),
        "prepared": (out / "prepared" / "rotation.csv").exists(),
    }


def analyze(d, gold_min=GOLD_MIN, all_runs=False):
    """문서별 첫 문제(단계·종류·사유)와 단계별 집계."""
    phases, phase_sec = {}, Counter()
    if d["runs"]:
        runs = d["runs"]
        # SI23 — runs.jsonl에 run_id 칸이 있고(엔진 범위가 바뀐 실행도) 이번 run_id(_DONE.json·env)를 알면 그 줄만.
        # run_id 칸이 하나도 없으면(옛 형식) 지금처럼 폴백: 문서×엔진마다 마지막 기록만.
        if not all_runs and d.get("run_id") and any(r.get("run_id") for r in runs):
            runs = [r for r in runs if r.get("run_id") == d["run_id"]]
        for r in runs:  # phase별(같은 문서×엔진이 phase마다 다시 돌 수 있어 거르기 전에 셈)
            ph = f"phase {r.get('phase') or '-'}"
            phases.setdefault(ph, Counter())[run_status(r)] += 1
            phase_sec[ph] += r.get("sec") or 0
        d = {**d, "runs": list({(r.get("doc"), r.get("engine")): r for r in runs}.values())}
    docs, issue = set(), {}  # issue[doc] = (단계, 종류, 사유) — 처음 걸린 것만

    def mark(doc, stage, kind, why):
        docs.add(doc)
        issue.setdefault(doc, (stage, kind, why))

    cnt = {k: Counter() for k, *_ in STAGES}
    for r in d["groups"] or []:
        docs.add(r.get("file"))
        dec = r.get("decision") or ""
        if "중복" in dec:
            mark(r["file"], "dedup", "policy", "중복 자동 제외")
        cnt["dedup"]["policy" if "중복" in dec else "ok"] += 1
        if "확인" in dec:  # 거의 같은 문서 — 파싱은 계속, 사람이 판 구분(문제 아님·건너뜀 아님)
            cnt["dedup"]["review"] += 1
    for r in d["skipped"] or []:
        k, why = skip_kind(r.get("reason"))
        mark(r.get("file"), "prepare", k, why)
        cnt["prepare"]["policy"] += 1  # 단계 지도는 '건너뜀' 한 칸(문서 목록·이슈 표에서 종류 구분)
    cnt["prepare"]["ok"] = max(0, cnt["dedup"]["ok"] - cnt["prepare"]["policy"])
    errs = Counter()
    by_doc = {}
    doc_errs = {}
    for r in d["runs"] or []:
        by_doc.setdefault(r["doc"], []).append(run_status(r))
        if r.get("error") and (
            run_status(r) != "env" or src_kind(r["error"])
        ):  # 손상 메시지가 env로 잘못 분류돼도("EOF marker not found") 원본 판정엔 포함
            doc_errs.setdefault(r["doc"], []).append((r.get("engine"), r["error"]))
        if r.get("error"):
            errs[(r.get("engine"), err_kind(r["error"]) if run_status(r) != "timeout" else "시간 초과", r["error"][:140])] += 1
    eng = {}
    for r in d["runs"] or []:
        eng.setdefault(r.get("engine"), Counter())[run_status(r)] += 1
    for doc, sts in by_doc.items():
        docs.add(doc)
        if "ok" in sts:
            cnt["parse"]["ok"] += 1
            continue
        errs_d = doc_errs.get(doc) or []
        kinds = [src_kind(m) for _, m in errs_d]
        if errs_d and all(kinds):  # 실패 엔진 전부가 원본 문제라고 말함 → 사람 조치(개발 문제 아님)
            k, why = (
                ("encrypted", next(w for kk, w in kinds if kk == "encrypted")) if any(kk == "encrypted" for kk, _ in kinds) else kinds[0]
            )
            cnt["parse"][k] += 1
            cnt["parse"]["policy"] += 1  # 단계 지도 "건너뜀" 칸에 같이(원본 문제 — 개발 문제 아님)
            mark(doc, "parse", k, why + " — " + " · ".join(f"{e}: {m[:60]}" for e, m in errs_d[:3]))
            continue
        c_ = Counter(sts)  # 가장 많은 실패 종류(동률이면 예외 > 시간 초과 > 환경)
        k = max(("env", "timeout", "fail"), key=lambda x: (c_[x], ("env", "timeout", "fail").index(x)))
        cnt["parse"][k] += 1
        mark(doc, "parse", k, f"성공한 엔진 없음({', '.join(f'{s} {n}' for s, n in Counter(sts).items())})")
    s = d["summary"] or {}
    for t in (s.get("types") or {}).values():
        for doc in t.get("partial") or []:
            mark(doc, "qa", "acc", f"교차 정확도 < {FULL}")
            cnt["qa"]["acc"] += 1
        for doc in t.get("unjudged") or []:
            mark(doc, "qa", "nojudge", "비교 기준 없음")
            cnt["qa"]["nojudge"] += 1
        cnt["qa"]["ok"] += max(0, (t.get("full") or 0))
    rep = d["rep"]
    rep_rows = rep if isinstance(rep, list) else (rep.get("docs") or list(rep.values())) if isinstance(rep, dict) else []
    rep_ok = set()
    for r in rep_rows:
        if not isinstance(r, dict):
            continue
        if r.get("engine"):
            rep_ok.add(r.get("doc"))
            cnt["rep"]["ok"] += 1
        else:
            mark(r.get("doc"), "rep", "noout", r.get("reason") or "대표 결과 없음")
            cnt["rep"]["noout"] += 1
    if d["bdocs"] is not None:
        bset = {r.get("doc") or r.get("file_name") or r.get("name") for r in d["bdocs"]} - {
            None
        }  # 실제 묶음 docs.jsonl은 file_name(structure/build_bundle.py)
        cnt["bundle"]["ok"] = len(bset)
        for doc in sorted(rep_ok - bset):
            mark(doc, "bundle", "noout", "색인에 없음")
            cnt["bundle"]["noout"] += 1
    gold_rows = []
    for doc, r in ((d["gold"] or {}).get("docs") or {}).items():
        rp = r.get("rep") or {}
        vals = {k: rp.get(k) for k in ("value_recall", "char_acc", "table_cell_recall")}
        gold_rows.append((doc, vals, rp.get("engine"), r.get("best_engine"), r.get("rep_is_best")))
        low = [k for k in ("value_recall", "char_acc") if vals[k] is not None and vals[k] < gold_min]
        if not rp:
            mark(doc, "gold", "noout", "대표 결과 없음")
            cnt["gold"]["noout"] += 1
        elif low:
            mark(doc, "gold", "acc", "정답 대비 " + " · ".join(f"{k} {vals[k]:.2f}" for k in low))
            cnt["gold"]["acc"] += 1
        else:
            cnt["gold"]["ok"] += 1
    if d["mcp"]:
        for _name, st in (d["mcp"].get("sets") or {}).items():
            sm = st.get("summary") or {}
            cnt["search"]["fail"] += sm.get("errors") or 0
            cnt["search"]["ok"] += (sm.get("n") or 0) - (sm.get("errors") or 0)
    # 단계 상태
    last = {}
    for r in d["runlog"]:
        last[r.get("tool")] = r
    present = {
        "dedup": d["groups"] is not None,
        "prepare": d["skipped"] is not None or d["prepared"],
        "parse": d["runs"] is not None,
        "qa": d["summary"] is not None,
        "rep": d["rep"] is not None,
        "bundle": d["bundle"] is not None,
        "gold": d["gold"] is not None,
        "search": d["mcp"] is not None,
    }
    stages, blocked, seen = [], None, False
    for key, name, tool, cmd in STAGES:
        c, lr = cnt[key], last.get(tool)
        tool_bad = lr is not None and lr.get("status") not in (None, "성공")
        dev = sum(c[k] for k in ("env", "fail", "timeout", "noout"))
        st = "notrun" if not present[key] else "dev" if (tool_bad or dev) else "acc" if (c["acc"] or c["nojudge"]) else "ok"
        if blocked is None and ((present[key] and tool_bad) or (not present[key] and seen and key not in ("gold", "search"))):
            blocked = key
        seen = seen or present[key]
        stages.append({"key": key, "name": name, "cmd": cmd, "st": st, "c": c, "log": lr})
    funnel = [
        ("받은 문서", len(docs) or len(by_doc)),
        ("중복 뺀 뒤", (len(docs) or len(by_doc)) - sum(1 for v in issue.values() if v[0] == "dedup")),
        ("DRM·암호 뺀 뒤", (len(docs) or len(by_doc)) - sum(1 for v in issue.values() if v[0] in ("dedup", "prepare"))),
        ("엔진 하나 이상 성공", cnt["parse"]["ok"]),
        ("대표 결과", len(rep_ok)),
        ("색인", cnt["bundle"]["ok"]),
        (f"그중 교차 정확도 ≥ {FULL}", cnt["qa"]["ok"]),
    ]
    # 소요 시간 — 단계(e2e 요약이 있으면 그것, 없으면 runlog 단계별 마지막 실행) · 엔진(문서×엔진 합) · 느린 문서
    E2E_NAME = {
        "preflight": "외부 서비스 사전 점검",
        "parse": "파싱(엔진·대조·대표)",
        "structure": "구조화(청킹·임베딩)",
        "load": "적재",
        "gold": "정답 대조",
        "search": "검색 평가",
        "board": "실행판",
    }
    if d.get("e2e"):
        t_steps = [(E2E_NAME.get(r["key"], r["key"]), r.get("sec") or 0) for r in d["e2e"]["steps"]]
    else:
        t_steps = [(s["name"], float((s["log"] or {}).get("sec") or 0)) for s in stages if s["log"]]
    t_eng, t_doc = Counter(), Counter()
    for r in d["runs"] or []:
        t_eng[r.get("engine")] += r.get("sec") or 0
        t_doc[(r["doc"], r.get("engine"))] += r.get("sec") or 0
    n_eng = Counter(r.get("engine") for r in d["runs"] or [])
    timing = {"steps": t_steps, "eng": [(e, sec, n_eng[e]) for e, sec in t_eng.most_common(10)], "slow": t_doc.most_common(5)}
    pending = Counter(
        r.get("engine") for r in d["runs"] or [] if run_status(r) == "timeout" and (r.get("phase") or 3) < 3
    )  # 다음 phase 대기(옛 PHASE_REPORT B)
    env_eng = {}
    for r in d["runs"] or []:
        if run_status(r) == "env":
            e = env_eng.setdefault(r.get("engine"), {"n": 0, "err": r.get("error") or ""})
            e["n"] += 1
    return {
        "stages": stages,
        "blocked": blocked,
        "issue": issue,
        "errs": errs,
        "eng": eng,
        "funnel": funnel,
        "gold": gold_rows,
        "gold_avg": (d["gold"] or {}).get("rep") or {},
        "docs": docs,
        "timing": timing,
        "phases": dict(sorted(phases.items())),
        "phase_sec": phase_sec,
        "rep_ok": len(rep_ok),
        "pending": pending,
        "env_eng": env_eng,
        "types": (d["summary"] or {}).get("types") or {},
    }


# ── 그림(SVG — 색은 CSS 변수라 밝은/어두운 화면 모두) ──────────────────────────
ST_LABEL = {"ok": "정상", "acc": "정확도 문제", "dev": "개발 문제", "notrun": "실행 안 함"}


def svg_stages(stages, blocked):
    W, bw, bh, gx, gy = 1120, 245, 118, 40, 54
    o = [
        f'<svg viewBox="0 0 {W} {2 * bh + gy + 24}" role="img" aria-label="단계 지도 — 단계별 상태">',
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" class="f-muted"/></marker></defs>',
    ]
    for i, s in enumerate(stages):
        r, c = divmod(i, 4)
        x, y = 10 + c * (bw + gx), 12 + r * (bh + gy)
        c_ = s["c"]
        dev = sum(c_[k] for k in ("env", "fail", "timeout", "noout"))
        if c < 3:
            o.append(f'<path d="M{x + bw + 4},{y + bh / 2} L{x + bw + gx - 6},{y + bh / 2}" class="ln" marker-end="url(#ah)"/>')
        elif r == 0:
            o.append(
                f'<path d="M{x + bw / 2},{y + bh + 4} L{x + bw / 2},{y + bh + gy / 2} L{10 + bw / 2},{y + bh + gy / 2} L{10 + bw / 2},{y + bh + gy - 6}" class="ln" marker-end="url(#ah)"/>'
            )
        thick = ' stroke-width="4"' if s["key"] == blocked else ""
        o.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="10" class="card s-{s["st"]}"{thick}/>')
        o.append(f'<rect x="{x}" y="{y}" width="8" height="{bh}" rx="4" class="bar-{s["st"]}"/>')
        o.append(f'<text x="{x + 22}" y="{y + 28}" class="t-h">{i + 1}. {E(s["name"])}</text>')
        o.append(
            f'<text x="{x + 22}" y="{y + 50}" class="t-st c-{s["st"]}">{ST_LABEL[s["st"]]}{" · 막힌 곳" if s["key"] == blocked else ""}{f" · 사람 확인 {s['c']['review']}" if s["c"]["review"] else ""}</text>'
        )
        if s["st"] != "notrun":
            nums = [
                ("성공", c_["ok"], "ok"),
                ("개발", dev, "dev"),
                ("정확도", c_["acc"] + c_["nojudge"], "acc"),
                ("건너뜀", c_["policy"], "policy"),
            ]
            xx = x + 22
            for lb, n, k in nums:
                o.append(
                    f'<text x="{xx}" y="{y + 82}" class="t-n c-{k if n else "muted"}">{n}</text><text x="{xx}" y="{y + 100}" class="t-s">{lb}</text>'
                )
                xx += 56
        else:
            o.append(
                f'<text x="{x + 22}" y="{y + 84}" class="t-s">결과 파일 없음</text><text x="{x + 22}" y="{y + 102}" class="t-code">{E(s["cmd"][:34])}</text>'
            )
    o.append("</svg>")
    return "".join(o)


def svg_funnel(funnel):
    top = max([n for _, n in funnel] + [1])
    W, rh, lw = 520, 34, 150
    o = [f'<svg viewBox="0 0 {W} {len(funnel) * rh + 30}" role="img" aria-label="문서 깔때기">']
    prev = None
    for i, (lb, n) in enumerate(funnel):
        y = 8 + i * rh
        w = (W - lw - 70) * n / top
        o.append(f'<text x="{lw - 10}" y="{y + 19}" class="t-s" text-anchor="end">{E(lb)}</text>')
        o.append(f'<rect x="{lw}" y="{y + 4}" width="{max(w, 1.5):.1f}" height="22" rx="3" class="bar-accent"/>')
        drop = f' <tspan class="c-dev">−{prev - n}</tspan>' if prev is not None and prev > n else ""
        o.append(f'<text x="{lw + w + 8:.1f}" y="{y + 20}" class="t-v">{n}{drop}</text>')
        prev = n
    o.append(f'<line x1="{lw}" y1="4" x2="{lw}" y2="{len(funnel) * rh + 12}" class="ln"/></svg>')
    return "".join(o)


def svg_heat(issue):
    m = Counter((st, k) for st, k, _ in issue.values())
    top = max(m.values() or [1])
    cw, rh, lw = 78, 30, 150
    W = lw + cw * len(ISSUES) + 10
    o = [f'<svg viewBox="0 0 {W} {rh * len(STAGES) + 56}" role="img" aria-label="단계 × 문제 종류 문서 수">']
    for j, (_k, lb) in enumerate(ISSUES):
        o.append(f'<text x="{lw + j * cw + cw / 2}" y="18" class="t-s" text-anchor="middle">{lb}</text>')
    for i, (key, name, *_) in enumerate(STAGES):
        y = 28 + i * rh
        o.append(f'<text x="{lw - 10}" y="{y + 19}" class="t-s" text-anchor="end">{i + 1}. {E(name)}</text>')
        for j, (k, _) in enumerate(ISSUES):
            n = m.get((key, k), 0)
            op = 0.15 + 0.85 * n / top if n else 0
            o.append(f'<rect x="{lw + j * cw + 2}" y="{y + 2}" width="{cw - 4}" height="{rh - 4}" rx="4" class="cell"/>')
            if n:
                o.append(
                    f'<rect x="{lw + j * cw + 2}" y="{y + 2}" width="{cw - 4}" height="{rh - 4}" rx="4" class="bar-{CLASS[k]}" fill-opacity="{op:.2f}"/>'
                    f'<text x="{lw + j * cw + cw / 2}" y="{y + 20}" class="t-v" text-anchor="middle">{n}</text>'
                )
    o.append("</svg>")
    return "".join(o)


def svg_bars(rows, label, unit="초"):
    """가로 막대(값 큰 것 = 병목, 진하게) — rows = [(이름, 값, 덧붙임)]."""
    rows = [r for r in rows if r[1]]
    if not rows:
        return ""
    top, tot = max(r[1] for r in rows), sum(r[1] for r in rows)
    W, rh, lw = 1120, 28, 220
    o = [f'<svg viewBox="0 0 {W} {len(rows) * rh + 12}" role="img" aria-label="{E(label)}">']
    for i, (n, v, extra) in enumerate(rows):
        y, w = 6 + i * rh, (W - lw - 360) * v / top
        o.append(f'<text x="{lw - 10}" y="{y + 17}" class="t-s" text-anchor="end">{E(n)}</text>')
        o.append(f'<rect x="{lw}" y="{y + 4}" width="{max(w, 1.5):.1f}" height="18" rx="3" class="bar-{"dev" if v == top else "accent"}"/>')
        o.append(
            f'<text x="{lw + w + 8:.1f}" y="{y + 18}" class="t-v">{v:,.0f}{unit} · {v / tot:.0%}{" · " + E(extra) if extra else ""}{" · 병목" if v == top else ""}</text>'
        )
    o.append("</svg>")
    return "".join(o)


def svg_engines(eng, keep_order=False):
    if not eng:
        return ""
    rows = list(eng.items()) if keep_order else sorted(eng.items(), key=lambda kv: -sum(kv[1].values()))
    top = max(sum(c.values()) for _, c in rows)
    W, rh, lw = 1120, 26, 170
    o = [f'<svg viewBox="0 0 {W} {len(rows) * rh + 34}" role="img" aria-label="엔진별 문서 결과">']
    for i, (e, c) in enumerate(rows):
        y, x = 6 + i * rh, lw
        o.append(f'<text x="{lw - 10}" y="{y + 16}" class="t-s" text-anchor="end">{E(e)}</text>')
        for k, cls in (("ok", "ok"), ("env", "dev"), ("fail", "dev"), ("timeout", "dev")):
            w = (W - lw - 120) * c[k] / top
            if w:
                pat = ' fill-opacity="0.55"' if k == "env" else ' fill-opacity="0.8"' if k == "timeout" else ""
                o.append(
                    f'<rect x="{x:.1f}" y="{y + 3}" width="{w:.1f}" height="18" class="bar-{cls}"{pat}><title>{E(e)} {k} {c[k]}</title></rect>'
                )
                x += w
        o.append(f'<text x="{x + 8:.1f}" y="{y + 16}" class="t-v">{c["ok"]}/{sum(c.values())}</text>')
    o.append("</svg>")
    return "".join(o)


def svg_gold(rows, name, gold_min):
    if not rows:
        return ""
    W, rh, lw, x0 = 1120, 28, 190, 0.5  # 0.5~1.0 확대(낮으면 왼쪽 끝에 붙임)
    pw = W - lw - 90
    X = lambda v: lw + pw * (max(v, x0) - x0) / (1 - x0)
    rows = sorted(rows, key=lambda r: r[1].get("value_recall") if r[1].get("value_recall") is not None else 2)
    H = len(rows) * rh + 50
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="정답 대비 문서별 정확도">']
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        o.append(
            f'<line x1="{X(t):.1f}" y1="22" x2="{X(t):.1f}" y2="{H - 24}" class="grid"/><text x="{X(t):.1f}" y="{H - 8}" class="t-s" text-anchor="middle">{t:.1f}</text>'
        )
    o.append(
        f'<line x1="{X(gold_min):.1f}" y1="16" x2="{X(gold_min):.1f}" y2="{H - 24}" class="thr"/><text x="{X(gold_min) + 4:.1f}" y="14" class="t-s c-acc">기준 {gold_min}</text>'
    )
    for i, (doc, v, eng, best, is_best) in enumerate(rows):
        y = 30 + i * rh + rh / 2
        o.append(f'<text x="{lw - 10}" y="{y + 5}" class="t-s" text-anchor="end">{E(name(doc))}</text>')
        o.append(f'<line x1="{lw}" y1="{y}" x2="{lw + pw}" y2="{y}" class="grid"/>')
        for k, cls, shape in (("table_cell_recall", "m3", "s"), ("char_acc", "m2", "d"), ("value_recall", "m1", "c")):
            if v.get(k) is None:
                continue
            cx = X(v[k])
            tip = f"<title>{E(name(doc))} {k} {v[k]:.3f} · 대표 {E(eng)} · 정답 최고 {E(best)}</title>"
            if shape == "c":
                o.append(f'<circle cx="{cx:.1f}" cy="{y}" r="6.5" class="{cls}">{tip}</circle>')
            elif shape == "d":
                o.append(f'<path d="M{cx:.1f},{y - 7} L{cx + 7:.1f},{y} L{cx:.1f},{y + 7} L{cx - 7:.1f},{y}z" class="{cls}">{tip}</path>')
            else:
                o.append(f'<rect x="{cx - 5.5:.1f}" y="{y - 5.5}" width="11" height="11" class="{cls}">{tip}</rect>')
        if is_best is False:
            o.append(f'<text x="{lw + pw + 6}" y="{y + 5}" class="t-s c-acc">선택≠최고</text>')
    o.append("</svg>")
    return "".join(o)


CSS = """
:root{--paper:#F5F7FA;--surface:#FFFFFF;--ink:#1B2430;--muted:#5B6675;--line:#D3DAE3;--accent:#2B5FA8;
--ok:#2E7D32;--acc:#B26A00;--dev:#C62828;--policy:#6B7A90;--src:#7B4BB7;--notrun:#A3ACB8;--m1:#2B5FA8;--m2:#7B4BB7;--m3:#00897B}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--paper:#11161D;--surface:#19202A;--ink:#E5E9EF;--muted:#9AA6B5;--line:#2C3643;--accent:#7FA7E6;
--ok:#6CC070;--acc:#F0A84A;--dev:#EF6B6B;--policy:#9AA8C0;--src:#B794E8;--notrun:#5B6573;--m1:#7FA7E6;--m2:#B794E8;--m3:#4DB6AC}}
:root[data-theme="dark"]{color-scheme:dark;--paper:#11161D;--surface:#19202A;--ink:#E5E9EF;--muted:#9AA6B5;--line:#2C3643;--accent:#7FA7E6;
--ok:#6CC070;--acc:#F0A84A;--dev:#EF6B6B;--policy:#9AA8C0;--src:#B794E8;--notrun:#5B6573;--m1:#7FA7E6;--m2:#B794E8;--m3:#4DB6AC}
body{background:var(--paper);color:var(--ink);font:14px/1.55 "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif;margin:0}
.wrap{max-width:1160px;margin:0 auto;padding-block:24px 56px;padding-inline:16px;display:grid;gap:22px}
h1{font-size:24px;margin:0;text-wrap:balance}h2{font-size:16px;margin:0 0 8px;letter-spacing:.02em}
.meta{color:var(--muted);font-size:12.5px}.meta code,.t-code,code{font-family:Consolas,"D2Coding",monospace}
.verdict{border-left:6px solid var(--v);background:var(--surface);padding:12px 16px;border-radius:6px;font-size:16px;font-weight:700}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}@media (max-width:820px){.two{grid-template-columns:1fr}}
.fig{overflow-x:auto}.fig svg{display:block;width:100%;min-width:640px;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--muted);font-size:12.5px;margin-top:6px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.tiles{display:flex;flex-wrap:wrap;gap:18px;margin:4px 0 10px}.keys{margin:6px 0 0;padding-left:18px}.keys li{margin:2px 0}.tile b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}details summary{cursor:pointer;font-weight:700}details summary:focus-visible{outline:2px solid var(--accent)}
.pill{display:inline-block;padding:0 8px;border-radius:9px;font-size:12px;color:#fff;background:var(--k)}
svg text{fill:var(--ink)}.t-h{font-size:16px;font-weight:700}.t-st{font-size:13px;font-weight:700}.t-n{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.t-s{font-size:12px;fill:var(--muted)}.t-v{font-size:12.5px;font-weight:700;font-variant-numeric:tabular-nums}.t-code{font-size:11px;fill:var(--muted)}
.card{fill:var(--surface);stroke:var(--line);stroke-width:1.5}.card.s-dev{stroke:var(--dev)}.card.s-acc{stroke:var(--acc)}.card.s-ok{stroke:var(--ok)}.card.s-notrun{stroke-dasharray:6 4}
.bar-ok{fill:var(--ok)}.bar-acc{fill:var(--acc)}.bar-dev{fill:var(--dev)}.bar-policy{fill:var(--policy)}.bar-src{fill:var(--src)}.bar-notrun{fill:var(--notrun)}.bar-accent{fill:var(--accent)}
.c-ok{fill:var(--ok)}.c-acc{fill:var(--acc)}.c-dev{fill:var(--dev)}.c-policy{fill:var(--policy)}.c-src{fill:var(--src)}.c-muted,.c-notrun{fill:var(--muted)}
.ln{stroke:var(--muted);stroke-width:1.6;fill:none}.f-muted{fill:var(--muted)}.cell{fill:var(--paper);stroke:var(--line)}
.grid{stroke:var(--line);stroke-width:1}.thr{stroke:var(--acc);stroke-width:2;stroke-dasharray:5 4}
.demo{background:var(--acc);color:#fff;font-weight:700;padding:6px 12px;border-radius:6px}.m1{fill:var(--m1)}.m2{fill:var(--m2)}.m3{fill:var(--m3)}
"""


def render(d, a, out_label, plain=False, gold_min=GOLD_MIN):
    name = (lambda x: x) if plain else (lambda x: "doc-" + hashlib.sha256(str(x).encode()).hexdigest()[:8])
    st = {s["key"]: s for s in a["stages"]}
    dev_docs = [x for x, v in a["issue"].items() if CLASS[v[1]] == "dev"]
    acc_docs = [x for x, v in a["issue"].items() if CLASS[v[1]] == "acc"]
    detail = ""  # 엔지니어용 원문(오류 종류·다음 명령)은 접어 둠 — 페르소나 리뷰 10-08
    if a["blocked"]:
        b = st[a["blocked"]]
        top = Counter(k for _, k, _ in a["errs"]).most_common(1)
        v_col, verdict = (
            "var(--dev)",
            f"{b['name']} 단계에서 막힘 — 그 뒤 단계는 돌지 않았습니다. 아래 '자세히'의 명령으로 이 단계부터 다시 실행하세요",
        )
        detail = (f"가장 많은 오류: {top[0][0]} · " if top else "") + f"다음 명령: {b['cmd']}"
    elif dev_docs:
        v_col, verdict = (
            "var(--dev)",
            f"끝까지 돌았지만 문서 {len(dev_docs)}건이 빠졌습니다 — 엔진 설치·설정 확인 필요(정확도 문제는 {len(acc_docs)}건 따로)",
        )
        top = a["errs"].most_common(1)
        detail = "빠진 이유: 설치·예외·시간 초과·결과 없음" + (
            f" · 가장 많은 오류: {top[0][0][0]} {top[0][0][1]} {top[0][1]}건" if top else ""
        )
    elif acc_docs:
        v_col, verdict = "var(--acc)", f"개발 문제 없음 — 정확도 문제 {len(acc_docs)}건(교차 정확도 < {FULL} 또는 정답 대비 < {gold_min})"
    elif any(s["st"] != "notrun" for s in a["stages"]):
        v_col, verdict = "var(--ok)", "돌린 단계 모두 정상"
    else:
        v_col, verdict = "var(--notrun)", "읽을 결과가 없음 — --out에 실행 결과 폴더를 지정"
    lg = lambda items: (
        '<div class="legend">' + "".join(f'<span><i style="background:var(--{k})"></i>{t}</span>' for k, t in items) + "</div>"
    )
    p = [
        f'<head><meta charset="utf-8"></head><title>파싱 실행판</title><style>{CSS}</style>',
        '<main class="wrap">',
        f'<header><h1>파싱 실행판</h1><div class="meta">결과 폴더 <code>{E(out_label)}</code> · 만든 시각 {datetime.now():%Y-%m-%d %H:%M}'
        f" · 문서 {len(a['docs'])}건 · 이름 {'원래' if plain else '해시(doc-xxxxxxxx)'}</div></header>",
        f'<div class="verdict" style="--v:{v_col}">{E(verdict)}</div>'
        + (f'<details class="meta"><summary>자세히(엔지니어)</summary><code>{E(detail)}</code></details>' if detail else ""),
        key_block(a, name),
        '<section class="panel"><h2>단계 지도</h2><div class="fig">'
        + svg_stages(a["stages"], a["blocked"])
        + "</div>"
        + lg(
            [
                ("ok", "정상"),
                ("acc", "정확도 문제"),
                ("dev", "개발 문제"),
                ("src", "원본 문제(암호·손상·미지원 — 사람 조치)"),
                ("policy", "정책 건너뜀(중복)"),
                ("notrun", "실행 안 함"),
            ]
        )
        + "</section>",
    ]
    if a["phases"]:
        p.append(
            '<section class="panel"><h2>phase별 — 문서×엔진 시도 결과 · 소요 시간</h2><div class="fig">'
            + svg_engines(a["phases"], keep_order=True)
            + '</div><div class="fig">'
            + svg_bars([(k, a["phase_sec"][k], "") for k in a["phases"]], "phase별 소요 시간")
            + "</div></section>"
        )
    p.append(
        '<div class="two"><section class="panel"><h2>문서 깔때기</h2><div class="meta">문서 단위(한 문서 = 1) — 단계 지도·엔진 칸은 문서×엔진 시도 단위라 합이 다릅니다</div><div class="fig">'
        + svg_funnel(a["funnel"])
        + "</div></section>"
        '<section class="panel"><h2>빠진 곳 — 단계 × 문제 종류</h2><div class="fig">' + svg_heat(a["issue"]) + "</div></section></div>"
    )
    t = a["timing"]
    if t["steps"] or t["eng"]:
        tot = sum(v for _, v in t["steps"])
        p.append(
            f'<section class="panel"><h2>소요 시간 — 어디가 병목인가{f" (전체 {tot:,.0f}초)" if tot else ""}</h2>'
            + (
                '<div class="meta">단계별(이번 실행)</div><div class="fig">'
                + svg_bars([(n, v, "") for n, v in t["steps"]], "단계별 소요 시간")
                + "</div>"
                if t["steps"]
                else ""
            )
            + (
                '<div class="meta">엔진별 — 문서×엔진 시도 시간 합(같은 엔진 평균은 괄호)</div><div class="fig">'
                + svg_bars([(e, v, f"{n}건 · 평균 {v / max(n, 1):.1f}초") for e, v, n in t["eng"]], "엔진별 소요 시간")
                + "</div>"
                if t["eng"]
                else ""
            )
            + (
                '<div class="meta">가장 느린 문서×엔진: '
                + " · ".join(f"{E(name(dc))} {E(en)} {v:.0f}초" for (dc, en), v in t["slow"])
                + "</div>"
                if t["slow"]
                else ""
            )
            + "</section>"
        )
    if a["eng"]:
        p.append(
            '<section class="panel"><h2>엔진별 결과 — 문서×엔진 시도</h2><div class="fig">'
            + svg_engines(a["eng"])
            + "</div>"
            + lg([("ok", "성공"), ("dev", "실패·시간 초과·환경(옅을수록 환경 문제)")])
            + "</section>"
        )
    if a["gold"]:
        g = a["gold_avg"]
        tiles = "".join(
            f'<div class="tile"><b>{g[k]:.3f}</b><span>{lb}</span></div>'
            for k, lb in (
                ("value_recall", "값 재현율"),
                ("char_acc", "글자 정확도"),
                ("table_cell_recall", "표 칸 재현율"),
                ("selection_match", "대표 선택 일치"),
            )
            if g.get(k) is not None
        )
        p.append(
            f'<section class="panel"><h2>정답 대비 정확도 — 정답이 있는 문서 {len(a["gold"])}건(대표 결과 기준)</h2><div class="tiles">{tiles}</div>'
            '<div class="meta">문서 평균 · 값 재현율 = 정답의 값(숫자·ID·이름) 중 대표 결과에 그대로 있는 비율 · 글자 정확도 = 1 − 글자 오류율(기호·공백 빼고) · 표 칸 재현율 = 정답 표 칸 중 찾은 비율(기호 포함) — 계산 <code>cli/score_gold.py</code></div>'
            '<div class="fig">'
            + svg_gold(a["gold"], name, gold_min)
            + "</div>"
            + '<div class="legend"><span><i style="background:var(--m1);border-radius:6px"></i>값 재현율</span><span><i style="background:var(--m2);transform:rotate(45deg)"></i>글자 정확도</span>'
            '<span><i style="background:var(--m3)"></i>표 칸 재현율</span><span>낮은 문서가 위</span></div></section>'
        )
    elif st["gold"]["st"] == "notrun":
        p.append(
            '<section class="panel"><h2>정답 대비 정확도</h2><div class="meta">채점 안 함 — <code>python cli/score_gold.py --gold &lt;정답 폴더&gt;</code></div></section>'
        )
    if d["mcp"]:
        rows = "".join(
            f'<tr><td>{E(n)}</td><td class="n">{(s.get("summary") or {}).get("n", "")}</td>'
            + "".join(
                f'<td class="n">{(s.get("summary") or {}).get(k, "—")}</td>'
                for k in ("hit1", "hit5", "value_in_evidence", "errors", "ms_p95")
            )
            + "</tr>"
            for n, s in (d["mcp"].get("sets") or {}).items()
        )
        p.append(
            f'<section class="panel"><h2>근거 반환 평가 <span class="meta">{E(d["mcp_file"])}</span></h2><table><thead><tr><th>세트</th><th>질문</th><th>hit@1</th><th>hit@5</th><th>근거 안 값</th><th>오류</th><th>p95 ms</th></tr></thead><tbody>{rows}</tbody></table></section>'
        )
    if a["types"]:  # 옛 PHASE_REPORT·phase*-report의 형식별 판정(사용자 10-08 — 실행판에 합침)
        rows = "".join(
            f'<tr><td><code>{E(k)}</code></td><td class="n">{v.get("docs", "")}</td><td class="n">{v.get("full", 0)}</td><td class="n">{len(v.get("partial") or [])}</td>'
            f'<td class="n">{len(v.get("unjudged") or [])}</td><td class="n">{len(v.get("low_n") or [])}</td><td class="n">{v.get("mean_acc") if v.get("mean_acc") is not None else "—"}</td></tr>'
            for k, v in sorted(a["types"].items())
        )
        p.append(
            '<details class="panel"><summary>형식별 교차 판정 — 엔진끼리 값이 맞는 정도</summary><table><thead><tr><th>형식</th><th>문서</th><th>성공(≥'
            + str(FULL)
            + ")</th>"
            f"<th>부분</th><th>판정 불가</th><th>계열 부족</th><th>평균 정확도</th></tr></thead><tbody>{rows}</tbody></table>"
            '<div class="meta">계열 부족 = 성공한 엔진 계열이 하나뿐이라 교차 확인 못 함 — 정답 대조(GOLD_DIR)로 보완.</div></details>'
        )
    if a["env_eng"]:
        rows = "".join(
            f'<tr><td><code>{E(e)}</code></td><td class="n">{v["n"]}</td><td><code>{E(v["err"][:120])}</code></td><td>{E(ENGINE_FIX.get(e, "엔진 설치·설정 확인(stack.json에서 빼도 됨)"))}</td></tr>'
            for e, v in sorted(a["env_eng"].items(), key=lambda kv: -kv[1]["n"])
        )
        p.append(
            f'<details class="panel"><summary>연결 안 된 엔진 {len(a["env_eng"])}개 — 원인·조치</summary><table><thead><tr><th>엔진</th><th>건</th><th>오류</th><th>조치</th></tr></thead><tbody>{rows}</tbody></table></details>'
        )
    if a["pending"]:
        rows = "".join(f'<tr><td><code>{E(e)}</code></td><td class="n">{n}</td></tr>' for e, n in a["pending"].most_common())
        p.append(
            f'<details class="panel"><summary>다음 phase 대기 {sum(a["pending"].values())}건 — 시간 초과로 더 긴 제한 phase로 넘어간 문서×엔진</summary><table><thead><tr><th>엔진</th><th>문서×엔진</th></tr></thead><tbody>{rows}</tbody></table></details>'
        )
    src_rows = issue_files(a, out_label)
    if src_rows:
        rows = "".join(
            f'<tr><td>{E(name(f))}</td><td><span class="pill" style="--k:var(--src)">{E(k)}</span></td><td>{E(why)}</td></tr>'
            for f, _key, _st, k, why in src_rows
        )
        p.append(
            f'<details class="panel" open><summary>원본 문제 문서 {len(src_rows)}건 — 사람 조치(암호 풀기·원본 다시 받기·형식 변환) · 원본 키까지 <code>report/issue_files.csv</code></summary>'
            f"<table><thead><tr><th>문서</th><th>종류</th><th>원인</th></tr></thead><tbody>{rows}</tbody></table></details>"
        )
    if a["issue"]:
        rows = "".join(
            f'<tr><td>{E(name(x))}</td><td>{E(st[v[0]]["name"])}</td><td><span class="pill" style="--k:var(--{CLASS[v[1]]})">{dict(ISSUES)[v[1]]}</span></td><td>{E(v[2])}</td></tr>'
            for x, v in sorted(a["issue"].items(), key=lambda kv: ([k for k, *_ in STAGES].index(kv[1][0]), kv[1][1]))
        )
        p.append(
            f'<details class="panel"><summary>문제 문서 {len(a["issue"])}건 — 처음 걸린 단계·사유</summary><table><thead><tr><th>문서</th><th>단계</th><th>종류</th><th>사유</th></tr></thead><tbody>{rows}</tbody></table></details>'
        )
    if a["errs"]:
        rows = "".join(
            f'<tr><td>{E(e)}</td><td>{E(k)}</td><td class="n">{n}</td><td><code>{E(m)}</code></td></tr>'
            for (e, k, m), n in a["errs"].most_common(30)
        )
        p.append(
            f'<details class="panel"><summary>오류 메시지 상위 {min(30, len(a["errs"]))}개 — 엔진·종류별</summary><table><thead><tr><th>엔진</th><th>종류</th><th>건</th><th>메시지(문서 원문은 가림)</th></tr></thead><tbody>{rows}</tbody></table></details>'
        )
    logs = "".join(
        f'<tr><td>{E(s["name"])}</td><td>{E((s["log"] or {}).get("status", "—"))}</td><td>{E((s["log"] or {}).get("time", ""))}</td><td class="n">{E((s["log"] or {}).get("sec", ""))}</td><td><code>{E((s["log"] or {}).get("log") or s["cmd"])}</code></td></tr>'
        for s in a["stages"]
    )
    p.append(
        f'<details class="panel"><summary>단계별 마지막 실행 기록(runlog)</summary><table><thead><tr><th>단계</th><th>상태</th><th>시각</th><th>초</th><th>로그 · 없으면 실행 명령</th></tr></thead><tbody>{logs}</tbody></table></details>'
    )
    p.append("</main>")
    return "\n".join(p)


def issue_files(a, out=None):
    """원본 문제 문서 목록(사람 조치) — [(파일, 원본 키, 단계, 종류, 원인)]. 원본 키는 parse/_source/manifest.jsonl(있으면).
    서버 안에서 쓰는 목록이라 원래 이름(요약 summary.json·밖으로 가져가는 그림은 해시) — 서버 밖 반출 금지."""
    keys = {}
    mf = Path(out) / "parse" / "_source" / "manifest.jsonl" if out else None
    for r in (_jsonl(mf) or []) if mf else []:
        keys[r.get("file_name")] = r.get("uri") or r.get("key")
    stage_name = {k: n for k, n, *_ in STAGES}
    return [
        (doc, keys.get(doc, ""), stage_name.get(v[0], v[0]), dict(ISSUES)[v[1]], v[2])
        for doc, v in sorted(a["issue"].items(), key=lambda kv: (kv[1][1], str(kv[0])))
        if CLASS[v[1]] == "src"
    ]


def write_issue_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["파일", "원본 키", "단계", "종류", "원인"])
        w.writerows(rows)
    return path


def key_issues(a, name):
    """핵심 이슈 최대 3줄 — 개발 문제(가장 많은 오류) · 정확도 문제(가장 낮은 문서) · 대표 선택≠최고."""
    out = []
    dev = [x for x, v in a["issue"].items() if CLASS[v[1]] == "dev"]
    acc = [x for x, v in a["issue"].items() if CLASS[v[1]] == "acc"]
    if dev:
        top = a["errs"].most_common(1)
        out.append(f"개발 문제 {len(dev)}건" + (f" — 가장 많은 오류: {top[0][0][0]} {top[0][0][1]} {top[0][1]}건" if top else ""))
    src = Counter(v[1] for v in a["issue"].values() if CLASS[v[1]] == "src")
    if src:
        out.append(
            f"원본 문제 {sum(src.values())}건(사람 조치) — "
            + " · ".join(f"{dict(ISSUES)[k]} {n}" for k, n in src.most_common())
            + " · 목록 issue_files.csv"
        )
    if acc:
        low = min(
            ((dc, v.get("value_recall")) for dc, v, *_ in a["gold"] if v.get("value_recall") is not None), key=lambda x: x[1], default=None
        )
        out.append(f"정확도 문제 {len(acc)}건" + (f" — 가장 낮은 문서 {name(low[0])} 값 재현율 {low[1]:.2f}" if low else ""))
    notbest = [dc for dc, _v, _e, _b, best in a["gold"] if best is False]
    if notbest:
        out.append(f"대표 선택이 정답 기준 최고 엔진과 다름 {len(notbest)}건(D10 대표 고르기)")
    return out[:3]


def key_block(a, name):
    """요약 맨 위 — 핵심 숫자 타일 + 핵심 이슈(텍스트 최소, 사용자 10-08)."""
    t, g = a["timing"], a["gold_avg"]
    tot = sum(v for _, v in t["steps"])
    slow = max(t["steps"], key=lambda r: r[1])[0] if t["steps"] else None
    tiles = [(f"{len(a['docs'])}", "문서"), (f"{a['rep_ok']}/{len(a['docs'])}", "대표 결과")]
    if g.get("value_recall") is not None:
        tiles.append((f"{g['value_recall']:.3f}", f"정답 값 재현율(정답 있는 문서 {g.get('n_docs') or len(a['gold'])}/{len(a['docs'])})"))
    if tot:
        tiles.append((f"{tot:,.0f}초", f"전체 · 병목 {slow}"))
    iss = key_issues(a, name)
    return (
        '<section class="panel"><div class="tiles">'
        + "".join(f'<div class="tile"><b>{E(v)}</b><span>{E(k)}</span></div>' for v, k in tiles)
        + "</div>"
        + ('<ul class="keys">' + "".join(f"<li>{E(x)}</li>" for x in iss) + "</ul>" if iss else "")
        + "</section>"
    )


def version():
    """버전 — common.pipeline_version()(저장소 루트 VERSION·오버레이 패치 PATCH_VERSION 중 높은 것 — D-036)."""
    from common import pipeline_version

    return pipeline_version()


def digest(root, html_text, a, d, out_label, when=None):
    """<root>/<YYYY-MM-DD>__<판>/{run_board.html, summary.json} + <root>/INDEX.md 한 줄 — 같은 날·같은 판이면 덮어씀(INDEX는 새 줄)."""
    import re

    when = when or datetime.now()
    ver = version()
    folder = Path(root) / f"{when:%Y-%m-%d}__{re.sub(r'[^A-Za-z0-9._+-]', '_', ver)}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run_board.html").write_text(html_text, encoding="utf-8")
    g, t = a["gold_avg"], a["timing"]
    hname = lambda x: "doc-" + hashlib.sha256(str(x).encode()).hexdigest()[:8]  # 요약은 늘 해시 이름(밖으로 가져감)
    summ = {
        "date": f"{when:%Y-%m-%d %H:%M}",
        "version": ver,
        "run_id": d.get("run_id"),
        "out": out_label,
        "docs": len(a["docs"]),
        "rep_ok": a["rep_ok"],
        "blocked": a["blocked"],
        "stages": {s["key"]: s["st"] for s in a["stages"]},
        "phases": {k: {**dict(c), "sec": round(a["phase_sec"][k], 1)} for k, c in a["phases"].items()},
        "gold": {k: g.get(k) for k in ("value_recall", "char_acc", "table_cell_recall", "selection_match") if g.get(k) is not None},
        "total_sec": round(sum(v for _, v in t["steps"]), 1),
        "bottleneck": max(t["steps"], key=lambda r: r[1])[0] if t["steps"] else None,
        "issues": key_issues(a, hname),
        "issue_counts": dict(Counter(CLASS[v[1]] for v in a["issue"].values())),
    }
    src_rows = issue_files(a, out_label)
    summ["source_issues"] = dict(Counter(k for *_, k, _w in src_rows))
    write_issue_csv(src_rows, folder / "issue_files.csv")  # 원본 문제 목록(원래 이름 — 서버 안에서만)
    (folder / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    idx = Path(root) / "INDEX.md"
    if not idx.exists():
        idx.write_text(
            "# 파싱 결과 요약 — 날짜·판별(run_board --digest)\n\n"
            "| 날짜 | 판 | run_id | 문서 | 대표 | 값 재현율 | 막힌 곳 | 이슈 | 폴더 |\n|---|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    gv = f"{g['value_recall']:.3f}" if g.get("value_recall") is not None else "—"
    with idx.open("a", encoding="utf-8") as f:
        f.write(
            f"| {summ['date']} | {ver} | {summ['run_id'] or '—'} | {summ['docs']} | {summ['rep_ok']} | {gv} | {summ['blocked'] or '—'} | "
            f"{' · '.join(summ['issues']) or '없음'} | [{folder.name}]({folder.name}/run_board.html) |\n"
        )
    return folder


def build(out, gold_score=None, plain=False, gold_min=GOLD_MIN, all_runs=False):
    d = load(out, gold_score)
    a = analyze(d, gold_min, all_runs)
    return render(d, a, str(out), plain, gold_min), a, d


def _fixture(tmp):
    """견본 실행 결과 — 문서 12건: 중복 1·DRM 1·환경 오류 1·시간 초과 1·정확도 낮음 2·색인 누락 1."""
    t = Path(tmp)
    for sub in ("dedup", "prepared", "parse/_rep", "edw/bundle", "eval/gold_score", "eval/mcp_eval"):
        (t / sub).mkdir(parents=True, exist_ok=True)
    docs = [f"견적서_{i:02d}.pdf" for i in range(1, 11)] + ["계약서_A.docx", "계약서_A_사본.docx"]
    with open(t / "dedup/groups.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "file", "representative", "reasons", "sha256", "size", "decision"])
        for i, x in enumerate(docs):
            w.writerow(
                [i, x, docs[10] if i == 11 else x, "", "", 1, "중복(자동 제외)" if i == 11 else "확인 필요" if i == 2 else "해시 대표"]
            )
    (t / "prepared/skipped.jsonl").write_text(
        json.dumps({"file": "견적서_10.pdf", "reason": "drm_fasoo"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"file": "자료모음.zip", "reason": "unsupported_archive"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    runs = []
    for x in docs[:9] + ["계약서_A.docx"]:
        for e in ("pymupdf", "docling", "paddleocr"):
            err = None
            if e == "paddleocr":
                err = "ModuleNotFoundError: paddleocr 미설치"
            if x == "견적서_09.pdf":
                err = "TimeoutError: Timeout 600s" if e != "paddleocr" else err
            if x == "견적서_08.pdf":
                err = "RuntimeError: docling 변환 실패" if e == "docling" else "ValueError: 빈 결과" if e == "pymupdf" else err
            runs.append({"doc": x, "engine": e, "sec": {"pymupdf": 0.4, "docling": 6.5, "paddleocr": 2.0}[e], "error": err, "phase": 2})
    for e, m in (
        ("kreuzberg", "ParsingError: workbook is password protected"),
        ("calamine", "CalamineError: password error"),
        ("anydoc", "ValueError: document is encrypted"),
        ("markitdown", "BadZipFile: File is not a zip file"),
    ):
        runs.append({"doc": "단가표_보호.xlsx", "engine": e, "sec": 0.2, "error": m, "phase": 1})
    runs.append(
        {"doc": "단가표_보호.xlsx", "engine": "docling", "sec": 0.0, "error": "ModuleNotFoundError: docling 미설치", "phase": 1}
    )  # 환경 오류는 판정에서 뺌
    for e in ("pymupdf", "pdfplumber"):
        runs.append({"doc": "스캔본_깨짐.pdf", "engine": e, "sec": 0.1, "error": "PdfReadError: EOF marker not found", "phase": 1})
    runs.append({"doc": "이상한.pdf", "engine": "pymupdf", "sec": 0.1, "error": "PdfReadError: EOF marker not found", "phase": 1})
    runs.append(
        {"doc": "이상한.pdf", "engine": "pdfplumber", "sec": 0.1, "error": "RuntimeError: 엔진 내부 오류", "phase": 1}
    )  # 하나라도 원본 규칙 밖 → 개발 문제
    (t / "parse/runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
    (t / "parse/parse_summary.json").write_text(
        json.dumps(
            {
                "types": {
                    ".pdf": {"docs": 8, "full": 5, "partial": ["견적서_03.pdf", "견적서_05.pdf"], "unjudged": []},
                    ".docx": {"docs": 1, "full": 0, "partial": [], "unjudged": ["계약서_A.docx"]},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rep = [
        {"doc": x, "engine": None if x in ("견적서_08.pdf", "견적서_09.pdf") else "pymupdf", "reason": "성공한 엔진 없음"}
        for x in docs[:9] + ["계약서_A.docx"]
    ]
    (t / "parse/_rep/index.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    (t / "edw/bundle/meta.json").write_text(json.dumps({"docs": 7, "chunks": 140}), encoding="utf-8")
    (t / "edw/bundle/docs.jsonl").write_text(
        "\n".join(json.dumps({"file_name": x}, ensure_ascii=False) for x in docs[:6] + ["계약서_A.docx"]) + "\n", encoding="utf-8"
    )
    gold = {
        "docs": {
            "견적서_01.pdf": {
                "rep": {"engine": "pymupdf", "value_recall": 0.98, "char_acc": 0.96, "table_cell_recall": 0.91},
                "best_engine": "pymupdf",
                "rep_is_best": True,
            },
            "견적서_03.pdf": {
                "rep": {"engine": "pymupdf", "value_recall": 0.71, "char_acc": 0.93, "table_cell_recall": 0.62},
                "best_engine": "docling",
                "rep_is_best": False,
            },
            "견적서_05.pdf": {
                "rep": {"engine": "pymupdf", "value_recall": 0.86, "char_acc": 0.81, "table_cell_recall": 0.77},
                "best_engine": "pymupdf",
                "rep_is_best": True,
            },
        },
        "rep": {"value_recall": 0.85, "char_acc": 0.9, "table_cell_recall": 0.767, "selection_match": 0.667, "n_docs": 3},
    }
    (t / "eval/gold_score/score.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
    (t / "eval/mcp_eval/20261007-120000_synth.json").write_text(
        json.dumps(
            {"sets": {"synth": {"summary": {"n": 40, "errors": 0, "hit1": 0.8, "hit5": 0.93, "value_in_evidence": 0.7, "ms_p95": 1400}}}}
        ),
        encoding="utf-8",
    )
    log = [
        {"time": "2026-10-07 10:00:00", "tool": k, "status": "성공", "sec": 12, "log": f"output/logs/x_{k}.log"}
        for k in ("dedup", "prepare", "run_all", "parse_qa", "represent", "bundle", "score_gold", "mcp_eval")
    ]
    (t / "report").mkdir(exist_ok=True)
    (t / "report/e2e_summary.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"key": k, "sec": v, "status": "성공"}
                    for k, v in (("parse", 81), ("structure", 24), ("gold", 6), ("search", 9), ("board", 1))
                ]
            }
        ),
        encoding="utf-8",
    )
    (t / "runlog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in log) + "\n", encoding="utf-8")
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="output", help="실행 결과 루트(parse/·prepared/·edw/·eval/·runlog.jsonl)")
    ap.add_argument("--gold-score", help="score_gold.py 산출 score.json(기본 <out>/eval/gold_score/score.json)")
    ap.add_argument("--gold-min", type=float, default=GOLD_MIN, help="정답 대비 값 재현율·글자 정확도 기준(미만 = 정확도 문제)")
    ap.add_argument("--plain-names", action="store_true", help="원래 문서 이름으로(기본 해시 — 밖으로 가져가도 되게)")
    ap.add_argument("--html", help="저장 경로(기본 <out>/report/run_board.html)")
    ap.add_argument("--demo", action="store_true", help="견본 결과로 그림(서버 결과 없이 모양 확인)")
    ap.add_argument(
        "--all-runs", action="store_true", help="이번 run_id로 거르지 않고 runs.jsonl 전체(문서×엔진마다 마지막 기록만 — SI23 전의 동작)"
    )
    ap.add_argument(
        "--digest",
        default=pc.cfg().paths.report_digest_dir or None,  # S7c — 설정 객체
        help="날짜·판 요약 폴더 루트(<루트>/<YYYY-MM-DD>__<판>/ + INDEX.md) — 수집 서버 파싱 끝에, 개발 서버가 가져감",
    )
    a = ap.parse_args(argv)
    if a.demo:
        with tempfile.TemporaryDirectory() as td:
            h, ra, rd = build(_fixture(td), plain=True, gold_min=a.gold_min, all_runs=a.all_runs)
            h = h.replace(str(Path(td)), "견본(--demo)")
            h = h.replace(
                '<div class="verdict"',
                '<div class="demo">견본 데이터(--demo) — 실제 실행 결과가 아닙니다. 모양 확인용</div><div class="verdict"',
                1,
            )
    else:
        h, ra, rd = build(Path(a.out), a.gold_score, a.plain_names, a.gold_min, a.all_runs)
    dst = Path(a.html) if a.html else Path(a.out) / "report" / "run_board.html"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(h, encoding="utf-8")
    print(f"저장: {dst}")
    if not a.demo:
        rows = issue_files(ra, a.out)
        print(f"원본 문제 목록: {write_issue_csv(rows, Path(a.out) / 'report' / 'issue_files.csv')} ({len(rows)}건)")
    if a.digest:
        print(f"요약: {digest(a.digest, h, ra, rd, a.out)}")


if __name__ == "__main__":
    try:
        from common.core.runlog import session
    except ImportError:
        main()
    else:
        with session("run_board"):
            main()
