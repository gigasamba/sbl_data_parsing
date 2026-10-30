#!/usr/bin/env python3
"""파이프라인 조합 평가 보고서 생성기 (stdlib only, 폐쇄망 서버에서도 동작).

절 순서·표 열은 데이터와 무관하게 고정한다. 입력이 없으면 절은 사라지지 않고
"미실행 — 실행 명령: …" 한 줄로 대체한다. 산출은 <title>/<style>만 상단에 두고
doctype/html/head/body 태그는 내지 않는(호스트가 감싸는) 단일 HTML 조각이다.
"""

from __future__ import annotations

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split

import argparse
import csv
import difflib
import html
import json
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

# S2b(사용자 10-26) — 기본 입력은 resources/config/(보고서 틀·판정 기준). 옛 기본값 report/*.json은 S2 전부터 없는 파일이라 줄어든 보고서가 조용히 나왔음(VS2 (a)).
from common.core.paths import CRITERIA_FILE, TEMPLATES_DIR

TAB_DEFS = [
    ("hdr", "헤더"),
    ("summary", "요약"),
    ("data", "데이터 현황"),
    ("server", "이관 서버 환경"),
    ("model-parse", "모델 파싱 성능"),
    ("stack", "기술 스택"),
    ("criteria", "QA 정량 기준"),
    ("parse-result", "파싱 결과"),
    ("doctype", "유형별 대표 문서·검토 대상"),
    ("chunk", "청킹"),
    ("vector", "벡터화·검색"),
    ("graph", "지식 그래프"),
    ("combo", "조합 순위"),
    ("answer", "답변(LLM)"),
    ("appendix", "부록"),
]

# 산출별 재생성 명령 (부록 + 결손 절의 안내에 공용)
CMD = {
    "dedup": "python modules/parse/dedup.py",
    "rotation": "python modules/parse/prepare.py --only output/dedup/keep.txt",
    "runs": "python modules/parse/run_all.py --src output/prepared",
    "qa": "python modules/parse/parse_qa.py --src output/prepared",
    "route": "python modules/parse/parse_qa.py",
    "truth": "(개발 PC) python dev_tools/synthetic_data_gen/make_corpus.py",
    "anchors": "python cli/run_combo.py --src output/prepared  # 앵커 자동 생성",
    "results": "python cli/run_combo.py",
    "beam": "python cli/run_combo.py",
    "answers": "(서버 LLM 단계) 상위 조합 × GLM 답변 — docs/testing.md §1 6단계",
    "catalog": "resources/config/report_templates/catalog.json 직접 편집(기술 스택 정본)",
    "server": "resources/config/report_templates/server.json 직접 편집(서버 환경·모델 정본)",
    "rep": "python -m pipeline.transform.represent.represent --parse-dir output/parse  # _rep/_images 생성(유형별 대표 문서 탭 입력)",
}

# 숫자 서식 규칙 — 지표 이름 → 서식 종류 (한 규칙만 적용)
RATIO_KEYS = {
    "ok_rate",
    "cer",
    "value_recall",
    "num_halluc",
    "table_row_recall",
    "table_cell_recall",
    "order",
    "rotation_drop",
    "len_ratio",
    "consensus_recall",
    "ko_ratio",
    "garbage",
    "r1",
    "r5",
    "r10",
    "mrr",
    "evidence_intact",
    "table_split",
    "anchor_path",
    "isolated",
    "num_acc",
    "cite_acc",
    "abstain_ok",
    "cross_recall",
    "qa_acc",
    "acc",
}
MS_KEYS = {"p50_ms", "p95_ms"}
SEC_KEYS = {"sec"}
INT_KEYS = {"chars", "lines", "tables", "nums", "ctx5", "ctx5m", "pages", "nodes", "edges"}

# 약어·지표 설명 — QA 정량 기준 탭 첫 표(보고서 어디서 나오든 여기서 찾는다)
GLOSSARY = [
    (
        "R@k (R@1·R@5·R@10)",
        "검색 재현율(Recall@k)",
        "질문마다 검색 상위 k개 안에 정답 값이 든 근거가 있으면 1 → 질문 평균. R@5 = 상위 5개 안에 근거가 들어온 질문 비율",
    ),
    (
        "MRR (MRR@10)",
        "평균 역순위(Mean Reciprocal Rank)",
        "정답 근거가 처음 나온 순위 r의 1/r을 질문마다 평균(10위 밖이면 0). 1위=1.0, 2위=0.5 — 근거를 얼마나 위에 올리나",
    ),
    (
        "ctx5m",
        "유의미 글자 수@5",
        "상위 5개 컨텍스트의 한글·영문·숫자 글자 수(여러 단위에 겹친 줄은 한 번). 조합 정렬 3순위 — 많을수록 좋음",
    ),
    ("ctx5", "컨텍스트 글자 수@5", "상위 5개 컨텍스트 전체 글자 수(공백·기호 포함) — LLM 비용 참고용"),
    (
        "조합 정렬",
        "R@5 → MRR → ctx5m",
        "R@5 높은 순, 같으면 MRR 높은 순, 같으면 ctx5m 많은 순. 답변 채점이 있으면 질문 정답률(qa_acc)이 1순위",
    ),
    ("CER", "글자 오류율(Character Error Rate)", "정답 글자열을 출력으로 바꾸는 편집 거리 ÷ 정답 글자 수(상한 1). 낮을수록 좋음"),
    ("값 재현율", "value_recall", "정답(가상 문서 truth·사람 정답지·원본 구조 파서)의 값 중 출력에 있는 비율"),
    (
        "교차 재현율",
        "cross_recall",
        "정답 없는 실데이터의 정확도 — 서로 다른 인식 계열 엔진 2개 이상이 함께 뽑은 유의미 토큰 중 이 엔진이 뽑은 비율(특정 파서에 고정 안 함)",
    ),
    (
        "유의미 텍스트",
        "common/meaning.py",
        "센다: 수치(금액·수량·비율·날짜·ID)·한글/영문 2자 이상 단어·문장, 머리말·꼬리말의 작업자·작성일·문서 번호. "
        "안 센다: 구분선·장식 기호(///, ---, ===, |, • 등 글자·숫자 없는 것)·쪽 번호(쪽 경계의 '3', '- 3 -', '3/10', 'Page 3', '3쪽')·1자 토큰. "
        "쪽 번호는 원본 위치 매핑(청크 meta.page)에만 쓰고 청크 본문(정제 텍스트)에서는 뺀다",
    ),
    (
        "⚠ 모수 적음",
        "low_n",
        "그 문서를 파싱에 성공한 엔진이 2개 이하이거나, 정답 없는 문서에서 성공한 독립 인식 계열이 2개 이하 — 대조 상대가 적어 정확도를 믿기 어려움(보고서·탐색기에서 강조)",
    ),
    ("수치 환각률", "num_halluc", "출력의 숫자 중 기준에 없는 숫자 비율 — 낮을수록 좋음"),
    (
        "A1 · A2 · A3",
        "답변 지표",
        "A1 수치 정답률 · A2 근거 인용 정확도(인용한 컨텍스트에 정답이 있나) · A3 답할 수 없는 질문에 무응답한 비율",
    ),
    ("qa_acc", "질문 정답률", "질문 유형(수치·client별·건수·합계·RFI)별 정답률의 단순 평균 — RFI는 핵심 내용 포함률 0.8 이상을 정답으로"),
    ("τ (Kendall)", "순위 일치도", "앞 단계 선택이 바뀌어도 다음 단계 순위가 같은지(1=같음). 0.6 미만이면 빔을 넓혀 전체 조합으로 다시"),
    ("BM25 · dense · hybrid · RRF", "검색 방식", "BM25 = 단어 일치 점수 · dense = 임베딩 유사도 · hybrid = 둘을 RRF(순위 역수 합)로 합침"),
    ("p50 · p95", "지연 시간", "검색 한 번에 걸린 시간의 중앙값·95번째 백분위(ms)"),
]


def combo_rank_key(r, answers_summary=None):
    """조합 순위 — 답변 채점이 있으면 qa_acc 먼저, 그다음 R@5 → MRR → 유의미 글자 수(많을수록). pipeline.eval.stages.rank_key와 같은 규칙."""
    R = r.get("R") or {}
    qa = ((answers_summary or {}).get(r.get("key")) or {}).get("qa_acc")
    return (
        -(qa if qa is not None else -1),
        -(R.get("r5") or 0),
        -(R.get("mrr") or 0),
        -(R.get("ctx5m") or 0),
    )  # ctx5m 없는 옛 실행 = 0(글자 수 ctx5로 대신하지 않음 — 뜻이 다름)


def esc(v):
    if v is None:
        return "—"
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x) for x in v)
    return html.escape(str(v), quote=True)


def fmt_metric(key, value):
    """지표 이름별 표시 규칙 — 값 없으면 —."""
    if value is None:
        return "—"
    try:
        if key in RATIO_KEYS:
            return f"{float(value):.3f}"
        if key in MS_KEYS:
            return f"{float(value):.0f}ms"
        if key in SEC_KEYS:
            return f"{float(value):.2f}s"
        if key in INT_KEYS:
            return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return esc(value)
    return esc(value)


def badge(v):
    if v is True:
        return '<span class="pass">✓ 통과</span>'
    if v is False:
        return '<span class="fail">✗ 미달</span>'
    return '<span class="na">— 미실행</span>'


def check_pass(value, dir_, threshold):
    if value is None or threshold is None:
        return None
    try:
        v, t = float(value), float(threshold)
    except (TypeError, ValueError):
        return None
    return v >= t if dir_ == ">=" else v <= t


def trunc(s, n=160):
    if s is None:
        return "—"
    s = str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def missing(cmd):
    return f'<p class="muted">미실행 — 실행 명령: <code>{esc(cmd)}</code></p>'


def fmt_source(v, row=None):
    if v is None:
        return "—"
    s = str(v)
    m = re.search(r"https?://\S+", s)
    if not m:
        return esc(s)
    url = m.group(0).rstrip(").,;")
    pre, post = s[: m.start()], s[m.start() + len(url) :]
    link = f'<a href="{esc(url)}" rel="noopener noreferrer" target="_blank">{esc(url)}</a>'
    return esc(pre) + link + esc(post)


def cell(col, row):
    key = col[0]
    val = key(row) if callable(key) else (row.get(key) if isinstance(row, dict) else None)
    if len(col) > 2 and col[2]:
        return col[2](val, row)
    return esc(val)


def table(columns, rows, empty_msg="데이터 없음", cls="", row_cls=None):
    """작은 표 헬퍼 — columns=[(key,label[,fmt])], rows=[dict,...].

    row_cls(row)->str: 행별 추가 CSS 클래스(예: 제외 후보 음영). 없으면 미부여.
    """
    if not rows:
        return f'<p class="muted">{esc(empty_msg)}</p>'
    head = "".join(f"<th>{esc(c[1])}</th>" for c in columns)
    body_rows = []
    for r in rows:
        rc = row_cls(r) if row_cls else ""
        attr = f" class='{esc(rc)}'" if rc else ""
        body_rows.append(f"<tr{attr}>" + "".join(f"<td>{cell(c, r)}</td>" for c in columns) + "</tr>")
    classes = ("tbl " + cls).strip()
    return f'<div class="twrap"><table class="{classes}"><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def read_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return None
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return None
    with p.open(encoding="utf-8-sig", newline="") as f:  # dedup·prepare는 utf-8-sig(BOM)로 씀
        return list(csv.DictReader(f))


def load_ctx(out_dir, catalog_path, server_path, criteria_path):
    out = Path(out_dir)
    paths = {
        "dedup": out / "dedup" / "groups.csv",
        "rotation": out / "prepared" / "rotation.csv",
        "runs": out / "parse" / "runs.jsonl",
        "qa": out / "parse" / "qa.json",
        "route": out / "parse" / "route.json",
        "parse_summary": out / "parse" / "parse_summary.json",
        "truth": out / "corpus" / "truth.json",
        "anchors": out / "eval" / "anchors.jsonl",
        "results": out / "eval" / "results.jsonl",
        "beam": out / "eval" / "beam.json",
        "answers": out / "eval" / "answers.jsonl",
        "answers_summary": out / "eval" / "answers_summary.json",
        "selection": out / "parse" / "selection.json",
        "secure": out / "secure" / "scan.csv",
        "bench_top3": Path(server_path).parent / "bench_top3.json",
        "catalog": Path(catalog_path),
        "server": Path(server_path),
    }
    return {
        "catalog": read_json(catalog_path),
        "server": read_json(server_path),
        "criteria": read_json(criteria_path) or {},
        "dedup": read_csv(paths["dedup"]),
        "rotation": read_csv(paths["rotation"]),
        "runs": read_jsonl(paths["runs"]),
        "qa": read_json(paths["qa"]),
        "route": read_json(paths["route"]),
        "parse_summary": read_json(paths["parse_summary"]),
        "truth": read_json(paths["truth"]),
        "anchors": read_jsonl(paths["anchors"]),
        "results": read_jsonl(paths["results"]),
        "beam": read_json(paths["beam"]),
        "answers": read_jsonl(paths["answers"]),
        "answers_summary": read_json(paths["answers_summary"]),
        "selection": read_json(paths["selection"]),
        "secure": {r.get("file"): r for r in read_csv(paths["secure"]) or []},
        "bench_top3": read_json(paths["bench_top3"]),
        "paths": paths,
        "out_dir": str(out),  # 유형별 대표 문서 탭 — _rep·_images는 고정 paths에 없어 out_dir에서 직접 찾음
    }


def compute_parse_passes(qa):
    out = []
    for eng, groups_ in qa.get("engines", {}).items():
        for grp, agg in groups_.items():
            for cid, p in (agg.get("pass") or {}).items():
                out.append((eng, grp, cid, p))
    return out


def compute_ref_free_flags(qa):
    """F1-F4 (eval-design §3-2 / criteria.json parse_reference_free)."""
    flags = []
    if not qa:
        return flags
    for doc, dv in qa.get("docs", {}).items():
        engines = dv.get("engines", {})
        chars_list = [e.get("chars") for e in engines.values() if isinstance(e.get("chars"), (int, float))]
        ko_list = [e.get("ko_ratio") for e in engines.values() if isinstance(e.get("ko_ratio"), (int, float))]
        max_chars = max(chars_list) if chars_list else 0
        med_ko = statistics.median(ko_list) if ko_list else None
        for eng, ev in sorted(engines.items()):
            chars = ev.get("chars")
            if chars is not None and chars < 15 and max_chars > 500:  # parse_qa.MIN_OK_CHARS와 같게
                flags.append({"doc": doc, "engine": eng, "flag": "F1", "detail": f"chars={chars}, 문서 내 최대={max_chars}"})
            lr = ev.get("len_ratio")
            if isinstance(lr, (int, float)) and (lr < 0.5 or lr > 2.0):
                flags.append({"doc": doc, "engine": eng, "flag": "F2", "detail": f"len_ratio={lr:.2f}"})
            g = ev.get("garbage")
            if isinstance(g, (int, float)) and g > 0.05:
                flags.append({"doc": doc, "engine": eng, "flag": "F3", "detail": f"garbage={g:.3f}"})
            ko = ev.get("ko_ratio")
            if isinstance(ko, (int, float)) and med_ko is not None and ko < med_ko * 0.5:
                flags.append({"doc": doc, "engine": eng, "flag": "F4", "detail": f"ko_ratio={ko:.2f} < 중앙값×0.5={med_ko * 0.5:.2f}"})
    return flags


def aggregate_engine(qa, engine):
    if not qa:
        return None
    total = ok = 0
    cers, vrs, secs = [], [], []
    for d in qa.get("docs", {}).values():
        e = d.get("engines", {}).get(engine)
        if not e:
            continue
        total += 1
        if e.get("ok"):
            ok += 1
        for lst, k in ((cers, "cer"), (vrs, "value_recall"), (secs, "sec")):
            if isinstance(e.get(k), (int, float)):
                lst.append(e[k])
    if total == 0:
        return None
    return {
        "ok": ok,
        "total": total,
        "cer": statistics.mean(cers) if cers else None,
        "value_recall": statistics.mean(vrs) if vrs else None,
        "sec": statistics.mean(secs) if secs else None,
    }


def measured_text(qa, engines):
    if not engines:
        return "—"
    parts = []
    for e in engines:
        agg = aggregate_engine(qa, e)
        if not agg:
            continue
        bits = [f"ok {agg['ok']}/{agg['total']}"]
        if agg["cer"] is not None:
            bits.append(f"CER {agg['cer']:.3f}")
        if agg["value_recall"] is not None:
            bits.append(f"값 {agg['value_recall']:.3f}")
        if agg["sec"] is not None:
            bits.append(f"{agg['sec']:.2f} s/쪽")
        parts.append(f"{esc(e)}: " + " · ".join(bits))
    return "; ".join(parts) if parts else "—"


def combo_text(results, combo):
    """조합 축 값(예: chunk:structure)이 들어간 조합들의 최고·중앙 R@5 — 기술 스택 표의 '이번 실측'."""
    parts = []
    for c in combo or []:
        axis, _, val = c.partition(":")
        r5 = sorted(
            r["R"]["r5"] for r in (results or []) if (r.get("combo") or {}).get(axis) == val and (r.get("R") or {}).get("r5") is not None
        )
        if r5:
            parts.append(f"R@5 최고 {r5[-1]:.3f} · 중앙 {r5[len(r5) // 2]:.3f} (조합 {len(r5)})")
    return "; ".join(parts)


def candidate_badge(v):
    cls = {"운영": "cand-op", "후보": "cand-cand", "참고": "cand-ref", "제외": "cand-excl"}.get(v, "cand-none")
    return f'<span class="badge {cls}">{esc(v or "—")}</span>'


def license_cell(v, row):
    lic, status, reason = row.get("license"), row.get("license_status"), row.get("license_reason")
    cls = {"사용 가능": "lic-ok", "조건부": "lic-cond", "제외": "lic-excl"}.get(status, "lic-none")
    badge_html = f'<span class="badge {cls}">{esc(status)}</span> ' if status else ""
    reason_html = f'<div class="sub muted" title="{esc(reason)}">{esc(reason)}</div>' if reason else ""
    return f"{esc(lic)} {badge_html}{reason_html}"


def src_link(source):
    if not source:
        return ""
    s = str(source)
    if s.startswith("http"):
        return f' <a href="{esc(s)}" rel="noopener noreferrer" target="_blank" class="src-link">출처</a>'
    return f' <span class="muted">({esc(s)})</span>'


def bench_text(bench_list, lang):
    items = [b for b in (bench_list or []) if b.get("lang") == lang]
    if not items:
        return "—"
    parts = []
    for b in items:
        txt = f"{b.get('bench', '?')} {b.get('metric', '')} {b.get('value', '')} ({b.get('kind', '?')})"
        parts.append(esc(txt) + src_link(b.get("source")))
    return " · ".join(parts)


def dummy_perf_cell(v, row):
    parts = [esc(x) for x in (row.get("dummy"), row.get("perf")) if x]
    return "<br>".join(parts) if parts else "—"


def tuning_cell(v, row):
    tuning, left = row.get("tuning"), row.get("tuning_left")
    if not tuning:
        return "—"
    cls = {"충분": "tune-ok", "부분": "tune-part", "미튜닝": "tune-none", "해당 없음": "tune-na"}.get(tuning, "tune-none")
    left_html = f'<div class="sub muted">{esc(left)}</div>' if left else ""
    return f'<span class="badge {cls}">{esc(tuning)}</span>{left_html}'


def stack_row_cls(row):
    return "muted-row" if row.get("candidate") == "제외" else ""


def compute_step_stats(catalog):
    """steps 단계별 검토/라이선스 집계 — 요약(절 1)·기술 스택(절 5) 공용."""
    if not catalog:
        return []
    layer_by_id = {ly.get("id"): ly for ly in catalog.get("layers", [])}
    out = []
    for st in catalog.get("steps", []):
        techs = []
        for lid in st.get("layers", []):
            techs += (layer_by_id.get(lid) or {}).get("techs", [])
        cnt = Counter(t.get("license_status") for t in techs)
        out.append(
            {
                "title": st.get("title", st.get("id", "?")),
                "kind": st.get("kind"),
                "n": len(techs),
                "ok": cnt.get("사용 가능", 0),
                "cond": cnt.get("조건부", 0),
                "excl": cnt.get("제외", 0),
                "shortlist": st.get("shortlist", []),
                "basis": st.get("shortlist_basis"),
                "relation": st.get("relation"),
            }
        )
    return out


def build_rotation_map(rows):
    m = {}
    if not rows:
        return m
    for r in rows:
        f = r.get("file")
        if not f:
            continue
        e = m.setdefault(f, {"pages": 0, "rotated": 0})
        e["pages"] += 1
        try:
            ang = int(float(r.get("angle", 0) or 0))
        except (TypeError, ValueError):
            ang = 0
        if ang % 360 != 0:
            e["rotated"] += 1
    return m


def build_dup_map(rows):
    m = {}
    if not rows:
        return m
    for r in rows:
        f = r.get("file")
        if f:
            m[f] = r.get("group")
    return m


def fingerprint(ctx):
    qa, catalog = ctx["qa"], ctx["catalog"]
    if qa:
        docs = qa.get("docs", {})
        n_docs, n_engines = len(docs), len(qa.get("engines", {}))
        formats = sorted({d.get("format", "?") for d in docs.values()})
    elif ctx["runs"]:
        n_docs = len({r.get("doc") for r in ctx["runs"] if r.get("doc")})
        n_engines = len({r.get("engine") for r in ctx["runs"] if r.get("engine")})
        formats = sorted({r.get("format") for r in ctx["runs"] if r.get("format")})
    else:
        n_docs = n_engines = None
        formats = []
    source = (catalog or {}).get("source") or ((qa or {}).get("meta") or {}).get("source")
    return {"n_docs": n_docs, "formats": formats, "n_engines": n_engines, "source": source or "—"}


def stage_status(ctx):
    return [
        ("준비", bool(ctx["rotation"]) or bool(ctx["dedup"]), CMD["rotation"]),
        ("파싱", bool(ctx["runs"]), CMD["runs"]),
        ("파싱 채점", bool(ctx["qa"]) and bool(ctx["route"]), CMD["qa"]),
        ("조합", bool(ctx["results"]), CMD["results"]),
        ("답변", bool(ctx["answers"]), CMD["answers"]),
    ]


def sec_header(ctx, title):
    fp = fingerprint(ctx)
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    chips = "".join(
        f'<span class="chip {"ok" if ok else "no"}">{"✓" if ok else "✗"} {esc(name)}</span>' for name, ok, _ in stage_status(ctx)
    )
    fmts = ", ".join(fp["formats"]) if fp["formats"] else "—"
    n_docs = fp["n_docs"] if fp["n_docs"] is not None else "—"
    n_eng = fp["n_engines"] if fp["n_engines"] is not None else "—"
    return (
        f"<h1>{esc(title)}</h1><p class='muted'>생성 시각 {esc(gen)}</p>"
        f"<div class='fingerprint'><span>문서 {esc(n_docs)}건</span><span>형식 {esc(fmts)}</span>"
        f"<span>소스 {esc(fp['source'])}</span><span>파싱 엔진 {esc(n_eng)}종</span></div>"
        f"<div class='chips'>{chips}</div>" + snapshot_note(ctx)
    )


def snapshot_note(ctx):
    """phase 단위 중간 보고서 표시 — 어느 phase까지의 결과인지, 다음 phase 대기(결과에 없음, 실패 아님)가 몇 건인지."""
    meta = (ctx.get("qa") or {}).get("meta") or {}
    ph, pend = meta.get("phase"), meta.get("pending") or {}
    if not ph and not pend:
        return ""
    n = sum(pend.values())
    if n:
        who = ", ".join(f"{e} {k}" for e, k in sorted(pend.items(), key=lambda x: -x[1])[:8])
        return (
            f"<p class='warn'><b>중간 결과 — phase {esc(ph)}까지.</b> 다음 phase 대기 {n}건({esc(who)})은 채점·선정에 들어가지 않았고 실패로 세지 않음. "
            "엔진 선정·순위는 잠정 — phase 3 뒤 다시 생성.</p>"
        )
    return f"<p class='muted'>파싱 결과 기준: phase {esc(ph)} 완료(대기 없음).</p>"


def parse_summary_table(ps):
    """타입별 수집 성공·정확도 표 + 합계 줄(parse_qa.parse_summary — 정의 한 곳)."""
    if not ps:
        return missing("python modules/parse/parse_qa.py --src output/prepared  (또는 run_all --phase N이 끝나면 자동)")
    rows = [
        {
            "type": t,
            "docs": r["docs"],
            "collected": f"{r['collected']}/{r['docs']}",
            "full": f"{r['full']}/{r['docs']}",
            "acc": r["mean_acc"],
            "unjudged": len(r.get("unjudged") or []),
            "partial": ", ".join((r.get("partial") or [])[:5]) or "—",
            "low": ", ".join((r.get("low_n") or [])[:5]) or "—",
        }
        for t, r in ps.get("types", {}).items()
    ]
    tt = ps.get("total", {})
    rows.append(
        {
            "type": "합계",
            "docs": tt.get("supported_docs"),
            "collected": f"{tt.get('collected')}/{tt.get('supported_docs')}",
            "full": f"{tt.get('full')}/{tt.get('supported_docs')}",
            "acc": tt.get("mean_acc"),
            "unjudged": "",
            "partial": "",
            "low": f"{tt.get('low_n')}개" if tt.get("low_n") else "—",
        }
    )
    cols = [
        ("type", "타입(PDF 텍스트/이미지 구분)"),
        ("docs", "지원 문서"),
        ("collected", "수집 성공(엔진 1개 이상)"),
        ("full", "정확도 95% 이상"),
        ("acc", "평균 정확도(문서별 최고 엔진)", lambda v, r: fmt_metric("value_recall", v)),
        ("unjudged", "판정 불가"),
        ("partial", "100% 미만 문서"),
        (
            "low",
            "⚠ 모수 적음(성공 엔진·독립 계열 ≤2)",
            lambda v, r: f"<span class='lowbadge'>{esc(v)}</span>" if v not in ("—", "", None) else "—",
        ),
    ]
    extra = f"<p class='muted'>지원 안 되는 형식: {esc(', '.join(tt.get('unsupported') or [])[:300])}</p>" if tt.get("unsupported") else ""
    return (
        f"<p><b>{esc(tt.get('line', ''))}</b></p>"
        + table(cols, rows, "문서 없음")
        + extra
        + "<p class='muted'>정확도 = 값 재현율(정답 → 사람 정답지 → 원본 구조 파서 기준), 이미지 실데이터는 인식 계열 합의 수치 재현율. "
        "판정 불가 = 수집은 됐으나 기준점이 없음(사람 검토). "
        "<b>⚠ 모수 적음</b> = 그 문서를 파싱에 성공한 엔진이 2개 이하, 또는 (정답 없는 문서에서) 성공한 **독립 인식 계열**이 2개 이하 "
        "— 같은 모델을 쓰는 엔진(예: PaddleOCR·RapidOCR = paddle 계열)은 같이 틀리므로 1표. 대조 상대가 적어 교차 재현율이 순위를 잘 못 가림.</p>"
    )


def rec_info(ctx):
    """최종 엔진 조합(selection.json) → (추천 순서 {엔진: 순번}, 선정 집합). 보고서의 엔진 표는 모두 이 순서로 정렬하고 선정 엔진을 강조한다
    (사용자 요건 2026-09-30: 모든 문서를 덮는 최종 조합 하이라이트 · 추천도 높은 엔진이 위)."""
    sel = ctx.get("selection") or {}
    order = {e: i for i, e in enumerate(sel.get("recommend") or [])}
    return order, {x["engine"] for x in sel.get("selected") or []}


def rec_sort(engines, order):
    return sorted(engines, key=lambda e: (order.get(e, 10**6), e))


def rec_name(e, chosen):
    return f"<b>★ {esc(e)}</b>" if e in chosen else esc(e)


def perfect_matrix(ps, qa, ctx=None):
    """엔진 × 타입 — 머리글 N = 그 형식에서 파싱 성공(15자 이상 출력, 엔진 1개 이상)한 문서 수 · 칸 = 이 엔진의 교차 재현율 ≥ 0.95 문서 수
    (정답 있는 문서는 교차 재현율 없으면 값 재현율) · '-' = 그 타입을 처리하지 않음 · 부분·미설치 등은 비고(사용자 확정 2026-09-30)."""
    if not ps or not ps.get("engines"):
        return missing("python modules/parse/parse_qa.py --src output/prepared  (또는 run_all --phase N이 끝나면 자동)")
    N = {t: r.get("collected", r["docs"]) for t, r in ps.get("types", {}).items()}
    types = sorted(N, key=lambda t: (-N[t], t))  # 문서 수(분모 N) 많은 형식이 왼쪽(사용자 2026-09-30)
    unavail = ((qa or {}).get("meta") or {}).get("unavailable") or {}
    head = "<tr><th>엔진</th>" + "".join(f"<th>{esc(t)}<br><span class='muted'>N={N[t]}</span></th>" for t in types) + "<th>비고</th></tr>"
    body = []
    order, chosen = rec_info(ctx or {})
    for e in rec_sort(set(ps["engines"]) | set(unavail), order):
        by = ps["engines"].get(e, {})
        tds, notes = [], []
        for t in types:
            c = by.get(t)
            if not c:
                tds.append("<td class='muted' style='text-align:center'>-</td>" if e not in unavail else "<td></td>")
                continue
            x, ok, n = c.get("xr95", 0), c.get("ok", 0), N[t]
            tds.append(
                f"<td class='num'>{x}</td>" if x == n else f"<td class='num' style='color:var(--fail,#b42318);font-weight:600'>{x}</td>"
            )
            if x < n:
                notes.append(
                    f"{t} 성공 {ok}/{n} · 교차 재현율 0.95↑ {x}"
                    + (f"(평균 정확도 {c['mean_acc']:.2f})" if c.get("mean_acc") is not None else "")
                )
        if e in unavail:
            notes.append("미설치·미설정 — 시험 안 함: " + str(unavail[e])[:120])
        body.append(
            f"<tr{' class=rec' if e in chosen else ''}><td>{rec_name(e, chosen)}</td>{''.join(tds)}<td>{esc(' · '.join(notes)) or '없음'}</td></tr>"
        )
    return (
        "<p class='muted'><b>★ 강조 행</b> = 최종 엔진 조합(모든 형식을 덮음), 추천도 높은 순 · 머리글 N = 그 형식에서 파싱에 성공(15자 이상 출력)한 문서 수 · 숫자 = 그중 이 엔진의 <b>교차 재현율 ≥ 0.95</b> 문서 수(실패·빈 결과는 못 셈) · "
        "<span style='color:var(--fail,#b42318);font-weight:600'>빨간 숫자</span> = N보다 적음 · <b>-</b> = 그 타입을 처리하지 않음 · "
        "빈칸 = 시험 안 함 · 원인은 맨 오른쪽 비고.</p>"
        f"<div class='twrap'><table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def selection_html(sel):
    """parse_qa.select_final 결과 — 선정 엔진 · 형식별 후보(정확도·속도) · VLM 미연결 제외 · 문제 목록."""
    if not sel:
        return missing(CMD["qa"])
    chosen = {x["engine"] for x in sel["selected"]}
    lst = lambda v, r: esc(", ".join(v)) if v else "—"
    t_sel = table(
        [
            ("engine", "엔진", lambda v, r: rec_name(v, chosen)),
            ("score", "추천도"),
            ("primary", "주 담당 형식", lst),
            ("backup", "예비 형식", lst),
            ("types", "상위 3 후보인 형식", lst),
        ],
        sel["selected"],
        row_cls=lambda r: "rec",
    )
    final = sel.get("final") or {}
    unc = sel.get("uncovered") or []
    t_final = table(
        [
            ("type", "형식"),
            ("p", "주 엔진", lambda v, r: rec_name(v, chosen) if v else "<span class='fail'>없음</span>"),
            ("b", "예비 엔진", lambda v, r: esc(v) if v else "—"),
        ],
        [{"type": t, "p": (es or [None])[0], "b": es[1] if len(es) > 1 else None} for t, es in sorted(final.items())],
    )
    cover = (
        f"<p class='pass'>✓ 모든 형식 커버 — {len(final)}개 형식 전부 주 엔진 있음</p>"
        if final and not unc
        else f"<p class='fail'>✗ 덮지 못한 형식: {esc(', '.join(unc))}</p>"
        if unc
        else ""
    )
    t_rows = [
        {"type": t, "rank": i + 1, "pick": "✓" if r["engine"] in chosen else "", **r}
        for t, rs in sel["types"].items()
        for i, r in enumerate(rs)
    ]
    t_types = table(
        [
            ("type", "형식"),
            ("rank", "순위"),
            ("engine", "엔진"),
            ("acc", "정확도", lambda v, r: fmt_metric("acc", v)),
            ("basis", "정확도 기준"),
            ("sec_page", "초/쪽"),
            ("ok_rate", "처리율", lambda v, r: fmt_metric("ok_rate", v)),
            ("pick", "선정"),
        ],
        t_rows,
    )
    t_vlm = table([("engine", "엔진"), ("why", "사유")], sel.get("excluded_vlm", []), "없음")
    t_iss = table([("engine", "엔진"), ("type", "형식"), ("issue", "문제")], sel.get("issues", []), "없음")
    return (
        f"<p class='muted'>{esc(sel.get('rule'))} 추천도 = 형식별 순위 점수(1위 3 · 2위 2 · 3위 1) 합 + 주 담당 형식 수.</p>"
        f"<h4>최종 엔진 조합 {len(sel['selected'])}개(추천도 순)</h4>{t_sel}<h4>형식별 최종 담당</h4>{cover}{t_final}<h4>형식별 후보(상위 3)</h4>{t_types}"
        f"<h4>제외 — VLM·LLM 미연결(개발 PC 한계, 서버에서 추가)</h4>{t_vlm}<h4>문제 있는 엔진·형식</h4>{t_iss}"
    )


def answer_by_category(ctx):
    asum = ctx.get("answers_summary") or {}
    rows = []
    for key, s in asum.items():
        if key.startswith("_") or not isinstance(s, dict):
            continue
        combo = s.get("combo") or {}
        row = {"combo": " / ".join(str(combo.get(k, "—")) for k in ("parse", "chunk", "embed", "graph", "retrieve")), "qa": s.get("qa_acc")}
        for cat, v in (s.get("by_category") or {}).items():
            row[cat] = f"{v.get('acc'):.3f} (n={v.get('n')})" if isinstance(v.get("acc"), (int, float)) else "—"
        rows.append(row)
    if not rows:
        return ""
    names = {"value": "수치", "client": "client별", "count": "건수", "sum": "합계", "rfi": "RFI(핵심 내용)"}
    cats = [c for c in names if any(c in r for r in rows)]
    rows.sort(key=lambda r: -(r["qa"] if r["qa"] is not None else -1))
    return "<h3>질문 유형별 정답률</h3>" + table(
        [("combo", "조합"), ("qa", "질문 정답률(qa_acc)", lambda v, r: fmt_metric("qa_acc", v))] + [(c, names[c]) for c in cats], rows
    )


def sec_summary(ctx):
    """요약 — 표 한 장(구분 · 항목 · 결과 · 근거·비고). 없는 입력은 결과 칸에 '미실행 — 명령'."""
    fp = fingerprint(ctx)
    rows = []

    def add(cat, item, result, note=""):
        rows.append({"cat": cat, "item": item, "result": result, "note": note})

    add(
        "데이터",
        "문서·형식·엔진",
        f"문서 {fp['n_docs'] if fp['n_docs'] is not None else '—'}건 · 형식 {len(fp['formats'])}종 · 파싱 엔진 {fp['n_engines'] if fp['n_engines'] is not None else '—'}종",
        ", ".join(fp["formats"]) if fp["formats"] else "",
    )
    sec = ctx.get("secure") or {}
    if sec:
        c = Counter(r.get("kind") for r in sec.values())
        add("데이터", "보안 문서", " · ".join(f"{k} {n}" for k, n in c.most_common()), "python -m pipeline.extract.secure_docs scan")
    ps = ctx.get("parse_summary")
    meta = (ctx.get("qa") or {}).get("meta") or {}
    if meta.get("phase") or meta.get("pending"):
        n = sum((meta.get("pending") or {}).values())
        add(
            "데이터",
            "파싱 결과 시점",
            f"phase {meta.get('phase')} 완료" + (f" · 다음 phase 대기 {n}건(미포함)" if n else " · 대기 없음"),
            "대기분은 실패로 세지 않음 — 선정·순위는 phase 3 뒤 확정" if n else "",
        )
    add(
        "파싱",
        "성공 문서 합계",
        (ps or {}).get("total", {}).get("line") or "미실행 — " + CMD["qa"],
        "성공 = 정확도 ≥ 0.95(정답 있으면 값 재현율, 없으면 교차 재현율)",
    )
    sel = ctx.get("selection")
    if sel:
        unc = sel.get("uncovered") or []
        add(
            "파싱",
            f"★ 최종 엔진 조합 {len(sel['selected'])}개(추천도 순)",
            ", ".join(x["engine"] for x in sel["selected"]),
            ("모든 형식 커버 " + str(len(sel.get("final") or {})) + "개" if not unc else "덮지 못한 형식: " + ", ".join(unc))
            + " · "
            + f"형식마다 2~3개(정확도 → 속도) · VLM 미연결 제외 {len(sel.get('excluded_vlm', []))}개(서버에서 추가) · 문제 {len(sel.get('issues', []))}건 — 파싱 결과 탭",
        )
    route, qa = ctx["route"], ctx["qa"]
    if route and qa:
        best = [f"{fmt} {ranked[0]}" for fmt, ranked in sorted(route.items()) if ranked]
        add("파싱", "형식별 1위 엔진", " · ".join(best), "route.json(정확도 → CER → 처리율 → 속도)")
        passes = compute_parse_passes(qa)
        add(
            "파싱",
            "QA 기준",
            f"통과 {sum(1 for *_, p in passes if p is True)} · 미달 {sum(1 for *_, p in passes if p is False)} ({len(passes)}건 중)",
            "엔진 × 형식군 × 지표",
        )
        c = Counter(f["flag"] for f in compute_ref_free_flags(qa))
        add("파싱", "참조-프리 플래그(F1~F4)", ", ".join(f"{k} {c[k]}건" for k in sorted(c)) or "없음", "빈 출력·길이 이상·잡음·한글 비율")
    else:
        add("파싱", "형식별 1위 엔진", "미실행 — " + CMD["qa"])
    results, asum = ctx["results"], ctx.get("answers_summary")
    if results:
        best = sorted(results, key=lambda r: combo_rank_key(r, asum))[0]
        combo, R = best.get("combo", {}), best.get("R") or {}
        q = ((asum or {}).get(best.get("key")) or {}).get("qa_acc")
        add(
            "조합",
            "1위 조합",
            " / ".join(f"{k}={combo.get(k, '—')}" for k in ("parse", "chunk", "embed", "graph", "retrieve")),
            (f"질문 정답률 {fmt_metric('qa_acc', q)} · " if q is not None else "")
            + f"R@5 {fmt_metric('r5', R.get('r5'))} · MRR {fmt_metric('mrr', R.get('mrr'))} · 유의미 글자 {fmt_metric('ctx5m', R.get('ctx5m'))} (조합 {len(results)}개 중)",
        )
    else:
        add("조합", "1위 조합", "미실행 — " + CMD["results"])
    if not asum:
        add("답변", "질문 정답률(유형별)", "미실행 — " + CMD["answers"], "수치·client별·건수·합계·RFI 핵심 내용")
    for s in compute_step_stats(ctx["catalog"]):
        add(
            "기술 스택",
            s["title"],
            f"검토 {s['n']}개 · 제외 {s['excl']}개",
            "우선 후보: " + (", ".join(s["shortlist"]) if s["shortlist"] else "—"),
        )
    return (
        table([("cat", "구분"), ("item", "항목"), ("result", "결과"), ("note", "근거·비고")], rows)
        + "<p class='muted'>약어(R@5·MRR·ctx5m·CER 등)는 <a href='#criteria'>QA 정량 기준</a> 탭 첫 표.</p>"
    )


def sec_data(ctx):
    qa = ctx["qa"]
    if not qa:
        return missing(CMD["qa"])
    docs = qa.get("docs", {})
    rot_map = build_rotation_map(ctx["rotation"])
    dup_map = build_dup_map(ctx["dedup"])
    by_fmt = {}
    for name, d in docs.items():
        by_fmt.setdefault(d.get("format", "?"), []).append((name, d))
    fmt_rows = []
    for fmt in sorted(by_fmt):
        items = by_fmt[fmt]
        pages = sum((d.get("pages") or 0) for _, d in items)
        rotated = sum(rot_map.get(n, {}).get("rotated", 0) for n, _ in items)
        dupg = len({dup_map.get(n) for n, _ in items if dup_map.get(n)})
        fmt_rows.append({"fmt": fmt, "docs": len(items), "pages": pages, "rotated": rotated, "dupg": dupg})
    t1 = table(
        [
            ("fmt", "형식"),
            ("docs", "문서"),
            ("pages", "쪽", lambda v, r: fmt_metric("pages", v)),
            ("rotated", "회전 쪽"),
            ("dupg", "중복 그룹"),
        ],
        fmt_rows,
    )
    sec = ctx.get("secure") or {}

    def secure_kind(name):
        """output/secure/scan.csv(python -m pipeline.extract.secure_docs scan) → 없으면 원본을 직접 판별(파이썬 라이브러리 없으면 '미점검')."""
        if name in sec:
            return sec[name].get("kind")
        src = Path((qa.get("meta") or {}).get("src") or "")
        try:
            from secure_docs import classify

            return classify(src / name)[0] if (src / name).exists() else "미점검"
        except Exception:
            return "미점검"

    doc_rows = []
    for name in sorted(docs):
        d = docs[name]
        engines = d.get("engines", {})
        ok = sum(1 for e in engines.values() if e.get("ok"))
        chars = [e.get("chars") for e in engines.values() if isinstance(e.get("chars"), (int, float))]
        doc_rows.append(
            {
                "doc": name,
                "fmt": d.get("format", "?"),
                "pages": d.get("pages"),
                "rotated": rot_map.get(name, {}).get("rotated", 0),
                "ref": d.get("ref", "none"),
                "ref_chars": d.get("ref_chars"),
                "engok": f"{ok}/{len(engines)}",
                "maxc": max(chars) if chars else None,
                "minc": min(chars) if chars else None,
                "secure": secure_kind(name),
            }
        )
    sc = Counter(r["secure"] for r in doc_rows)
    for fr in fmt_rows:
        fr["secure"] = sum(
            1 for r in doc_rows if r["fmt"] == fr["fmt"] and r["secure"] not in ("보호 없음", "보호 없음(해당 없음)", "미점검")
        )
    t1 = (
        table(
            [
                ("fmt", "형식"),
                ("docs", "문서"),
                ("pages", "쪽", lambda v, r: fmt_metric("pages", v)),
                ("rotated", "회전 쪽"),
                ("dupg", "중복 그룹"),
                ("secure", "보안 문서"),
            ],
            fmt_rows,
        )
        + "<p class='muted'>보안 문서 판별: "
        + esc(" · ".join(f"{k} {n}" for k, n in sc.most_common()))
        + " — 편집 잠금·PDF 소유자 암호는 그대로 읽힘, 열기 암호·DRM은 python -m pipeline.extract.secure_docs(데이터 현황 표의 '보안' 열).</p>"
    )
    for r in doc_rows:
        d_ = docs[r["doc"]]
        r["low"] = int(r["engok"].split("/")[0]) <= 2 or (d_.get("n_fam", 9) <= 2 and d_.get("ref") not in ("truth", "answer_key"))
    t2 = (
        "<p class='muted'><span class='lowbadge'>⚠ 모수 적음</span> 행 = 파싱에 성공한 엔진 또는 독립 인식 계열이 2개 이하(대조 기준이 약함).</p>"
        + table(
            [
                ("doc", "문서", lambda v, r: esc(v) + (" <span class='lowbadge'>⚠ 모수 적음</span>" if r.get("low") else "")),
                ("fmt", "형식"),
                ("secure", "보안"),
                ("pages", "쪽"),
                ("rotated", "회전"),
                ("ref", "기준"),
                ("ref_chars", "기준 글자 수", lambda v, r: fmt_metric("chars", v)),
                ("engok", "성공/실행"),
                ("maxc", "최대 글자 수", lambda v, r: fmt_metric("chars", v)),
                ("minc", "최소 글자 수", lambda v, r: fmt_metric("chars", v)),
            ],
            doc_rows,
            row_cls=lambda r: "low" if r.get("low") else "",
        )
    )
    return f"<h3>형식별</h3>{t1}<h3>문서별</h3>{t2}"


def sec_server(ctx):
    server = ctx["server"]
    if not server:
        return missing(CMD["server"])
    t_env = table([("item", "항목"), ("value", "값"), ("source", "출처", fmt_source)], server.get("env", []), "환경 정보 없음")

    def vision(v, r):
        return "예" if v else ("아니오" if v is False else "—")

    def quanthw(v, r):
        q = r.get("quant") or {}
        return esc(f"{q.get('format', '—')} / {q.get('hardware', '—')}")

    def wmem(v, r):
        return esc((r.get("quant") or {}).get("weight_mem_gb"))

    m_cols = [
        ("as_written", "입력명"),
        ("official_name", "공식 이름"),
        ("role", "역할"),
        ("params_total", "파라미터(total)"),
        ("params_active", "파라미터(active)"),
        ("vision", "비전", vision),
        ("context", "컨텍스트"),
        ("license", "라이선스"),
        (lambda r: None, "양자화·하드웨어", quanthw),
        (lambda r: None, "가중치 메모리", wmem),
        ("pipeline_role", "파이프라인 역할"),
    ]
    t_models = table(m_cols, server.get("models", []), "모델 정보 없음")
    unresolved = server.get("unresolved", [])
    u_html = (
        ("<ul>" + "".join(f"<li>{esc(u)}</li>" for u in unresolved) + "</ul>") if unresolved else "<p class='muted'>미확인 항목 없음</p>"
    )
    ver = server.get("verification")
    v_html = ""
    if ver:
        items = ver.get("items", [])
        li = "".join(
            f"<li>{esc(it)}</li>" if not isinstance(it, dict) else "<li>" + esc(" · ".join(f"{k}: {v}" for k, v in it.items())) + "</li>"
            for it in items
        )
        v_html = f"<h3>검증</h3><p>판정: {esc(ver.get('verdict', '—'))} · 검증자: {esc(ver.get('by', '—'))}</p><ul>{li}</ul>"
    return f"<h3>환경</h3>{t_env}<h3>모델</h3>{t_models}<h3>미확인 항목</h3>{u_html}{v_html}"


def sec_model_parse(ctx):
    server, qa = ctx["server"], ctx["qa"]
    if not server:
        return missing(CMD["server"])
    blocks = []
    top = (ctx.get("bench_top3") or {}).get("benches") or {}

    def top_cell(i):
        def f(v, r):
            t = (top.get(r.get("bench")) or {}).get("top3") or []
            if len(t) <= i:
                return "<span class='muted'>—</span>"
            x = t[i]
            return f"{esc(x.get('name'))} <b>{esc(x.get('score'))}</b>"

        return f

    def cmp_cell(v, r):
        b = top.get(r.get("bench"))
        if not b:
            return "<span class='muted'>조사 전</span>"
        if not b.get("top3"):
            return "<span class='muted'>최고 점수 미확정</span>"
        return ("비교 가능" if b.get("comparable") else "참고(설정·버전 다름)") + (" · 3위 안" if b.get("ours_in_top3") else " · 3위 밖")

    for m in server.get("models", []):
        name = m.get("official_name") or m.get("as_written") or "?"
        t = table(
            [
                ("bench", "벤치마크"),
                ("lang", "언어"),
                ("metric", "지표"),
                ("value", "우리 모델"),
                (lambda r: None, "최고 1위", top_cell(0)),
                (lambda r: None, "2위", top_cell(1)),
                (lambda r: None, "3위", top_cell(2)),
                (lambda r: None, "상대 비교", cmp_cell),
                ("kind", "벤더/독립"),
                ("source", "출처", fmt_source),
            ],
            m.get("scores", []),
            "공개 벤치마크 없음",
        )
        weak = m.get("weaknesses", [])
        w = ("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in weak) + "</ul>") if weak else "<p class='muted'>없음</p>"
        blocks.append(f"<h3>{esc(name)}</h3>{t}<p><b>약점</b></p>{w}")
    ver = server.get("verification")
    ver_html = f"<p>검증: {esc(ver.get('verdict', '—'))} ({esc(ver.get('by', '—'))})</p>" if ver else ""
    if top:
        bt = ctx["bench_top3"]
        notes = "".join(f"<li><b>{esc(b)}</b>: {esc(v.get('note'))}</li>" for b, v in top.items() if v.get("note"))
        unv = "".join(f"<li>{esc(u.get('bench'))}: {esc(u.get('why'))}</li>" for u in bt.get("unverified") or [])
        ver_html += (
            f"<details><summary>벤치 최고 3위 출처·비교 조건({esc(bt.get('as_of'))} 기준, 독립 검증 완료)</summary><ul>{notes}</ul>"
            + (f"<p><b>최고 점수 미확정·일부 미확인</b></p><ul>{unv}</ul>" if unv else "")
            + "</details>"
            "<p class='muted'>'참고' = 벤치 버전·지표·하네스가 우리 모델 발표값과 달라 직접 비교 불가 — 순위 감만 볼 것. "
            "최고 3위는 공식 리더보드 우선, 없으면 집계 사이트(자체 보고 포함).</p>"
        )
    from pipeline.extract.run_all import VLM_ENGINES  # 한 곳(pl-31 뒤 사본 정리)

    prefixes = tuple(sorted(VLM_ENGINES))
    rows = []
    if qa:
        for engine, groups_ in sorted(qa.get("engines", {}).items()):
            if not engine.startswith(prefixes):
                continue
            for group, agg in sorted(groups_.items()):
                rows.append(
                    {
                        "engine": engine,
                        "group": group,
                        "ok_rate": agg.get("ok_rate"),
                        "cer": agg.get("cer"),
                        "value_recall": agg.get("value_recall"),
                        "sec": agg.get("sec"),
                    }
                )
    real_section = (
        table(
            [
                ("engine", "엔진"),
                ("group", "형식군"),
                ("ok_rate", "처리율", lambda v, r: fmt_metric("ok_rate", v)),
                ("cer", "CER", lambda v, r: fmt_metric("cer", v)),
                ("value_recall", "값 재현율", lambda v, r: fmt_metric("value_recall", v)),
                ("sec", "초/쪽", lambda v, r: fmt_metric("sec", v)),
            ],
            rows,
            "해당 엔진 결과 없음",
        )
        if qa
        else missing(CMD["qa"])
    )
    return "".join(blocks) + ver_html + f"<h3>서버 실측</h3>{real_section}"


def sec_stack(ctx):
    """슬라이드용 — 단계별 요약 → 라이선스 판정 기준 → 단계별(레이어별) 상세 표."""
    catalog = ctx["catalog"]
    if not catalog:
        return missing(CMD["catalog"])
    qa = ctx["qa"]
    layers = catalog.get("layers", [])
    layer_by_id = {ly.get("id"): ly for ly in layers}
    steps = catalog.get("steps", [])
    blocks = []

    step_stats = compute_step_stats(catalog)
    if step_stats:
        sum_rows = [
            {
                "title": s["title"],
                "kind": s["kind"],
                "n": s["n"],
                "status": f"{s['ok']}/{s['cond']}/{s['excl']}",
                "shortlist": ", ".join(s["shortlist"]) if s["shortlist"] else "—",
                "basis": s["basis"],
                "relation": s["relation"],
            }
            for s in step_stats
        ]
        t_sum = table(
            [
                ("title", "단계"),
                ("kind", "방식"),
                ("n", "검토 스택 수"),
                ("status", "사용가능/조건부/제외"),
                ("shortlist", "우선 후보"),
                ("basis", "근거"),
                ("relation", "다른 단계와의 관계"),
            ],
            sum_rows,
        )
        blocks.append(f"<h3>단계별 요약</h3>{t_sum}")
    else:
        blocks.append("<h3>단계별 요약</h3><p class='muted'>단계 정보 없음(catalog.json에 steps 미포함)</p>")

    lp = catalog.get("license_policy")
    if lp:
        excl = lp.get("exclude", [])
        cond = lp.get("conditional", [])
        excl_html = (
            ("<ul>" + "".join(f"<li>{esc(x.get('rule'))} — 예: {esc(x.get('example'))}</li>" for x in excl) + "</ul>")
            if excl
            else "<p class='muted'>없음</p>"
        )
        cond_html = (
            ("<ul>" + "".join(f"<li>{esc(x.get('rule'))} — 의무: {esc(x.get('obligation'))}</li>" for x in cond) + "</ul>")
            if cond
            else "<p class='muted'>없음</p>"
        )
        blocks.append(
            "<h3>라이선스 판정 기준</h3><div class='lic-box'>"
            f"<p><b>제외 규칙</b></p>{excl_html}<p><b>조건부 규칙</b></p>{cond_html}"
            f"<p><b>사용 가능</b>: {esc(lp.get('allowed'))}</p></div>"
        )
    else:
        blocks.append("<h3>라이선스 판정 기준</h3><p class='muted'>정책 정보 없음(catalog.json에 license_policy 미포함)</p>")

    cols = [
        ("name", "기술"),
        ("candidate", "구분", lambda v, r: candidate_badge(v)),
        ("strengths", "특장점"),
        ("weaknesses", "단점"),
        (lambda r: r, "라이선스", license_cell),
        (lambda r: r.get("bench"), "공개 벤치마크 영어", lambda v, r: bench_text(v, "en")),
        (lambda r: r.get("bench"), "공개 벤치마크 한국어", lambda v, r: bench_text(v, "ko")),
        (lambda r: r, "더미 테스트 특징 · 수치", dummy_perf_cell),
        (
            lambda r: combo_text(ctx["results"], r.get("combo")) or measured_text(qa, r.get("engines")),
            "이번 실측",
            lambda v, r: esc(v) if v != "—" and "R@5" in v else v,
        ),
        (lambda r: r, "튜닝", tuning_cell),
        ("note", "비고"),
    ]

    def render_layer(layer):
        head = f"<h4>{esc(layer.get('title', layer.get('id', '?')))}</h4><p class='muted'>{esc(layer.get('desc', ''))}</p>"
        return head + table(cols, layer.get("techs", []), "기술 없음", row_cls=stack_row_cls)

    covered_ids = {lid for st in steps for lid in st.get("layers", [])}
    for st in steps:
        blocks.append(f"<h3>{esc(st.get('title', st.get('id', '?')))}</h3>")
        for lid in st.get("layers", []):
            layer = layer_by_id.get(lid)
            if layer:
                blocks.append(render_layer(layer))
    others = [ly for ly in layers if ly.get("id") not in covered_ids]
    if others:
        blocks.append("<h3>기타</h3>")
        for layer in others:
            blocks.append(render_layer(layer))
    return "".join(blocks)


def sec_criteria(ctx):
    c = ctx["criteria"]
    rows = []
    for crit in c.get("parse", []):
        rows.append(
            {
                "cat": "파싱",
                "id": crit["id"],
                "name": crit["name"],
                "desc": crit["desc"],
                "native": crit.get("native"),
                "image": crit.get("image"),
                "value": None,
                "dir": crit["dir"],
            }
        )
    for key, label in (("chunk", "청킹"), ("retrieve", "검색"), ("graph", "그래프"), ("answer", "답변")):
        for crit in c.get(key, []):
            rows.append(
                {
                    "cat": label,
                    "id": crit["id"],
                    "name": crit["name"],
                    "desc": crit["desc"],
                    "native": None,
                    "image": None,
                    "value": crit.get("value"),
                    "dir": crit["dir"],
                }
            )
    t = table(
        [
            ("cat", "구분"),
            ("id", "ID"),
            ("name", "이름"),
            ("desc", "설명"),
            ("native", "기준(native)"),
            ("image", "기준(image)"),
            ("value", "기준(공통)"),
            ("dir", "방향"),
        ],
        rows,
        "기준 없음",
    )
    t_rf = table([("id", "ID"), ("name", "이름"), ("rule", "규칙")], c.get("parse_reference_free", []), "참조-프리 규칙 없음")
    bullets = (
        "<ul>"
        "<li>캐시 키=단계 설정+앞 단계 해시로, 같은 파싱·청킹을 쓰는 조합은 다시 만들지 않는다.</li>"
        "<li>빔 탐색으로 각 단계 상위 B개(기본 2)만 다음 단계로 넘기고, 공통 채점은 검색 근거 재현율(R)이다.</li>"
        "<li>앞 단계 선택에 따라 다음 단계 순위가 크게 바뀌면(Kendall τ&lt;0.6) 그 단계는 빔을 넓혀 전체 곱으로 다시 돈다.</li>"
        "<li>살아남은 조합은 R@5 → MRR → 유의미 글자 수 ctx5m(많을수록 좋음) 순으로 정렬한다.</li>"
        "<li><b>최종 판정은 미리 준비한 질문에 얼마나 잘 답하나</b>: 상위 조합 × LLM으로 수치·client별·과거 계약 건수·전체 용량 합계·RFI(정확도·핵심 내용 포함) 질문을 채점해 "
        "질문 정답률(qa_acc)을 1순위로 다시 정렬한다(검색 지표는 그 전 단계 거르기).</li>"
        "<li>회전 문서는 방향 보정(prepare.py)에서 가장 잘 읽히는 방향만 채점한다(회전 강건성 지표 없음).</li>"
        "</ul>"
    )
    t_g = table([("abbr", "약어·용어"), ("name", "이름"), ("desc", "설명")], [{"abbr": a, "name": n, "desc": d} for a, n, d in GLOSSARY])
    return f"<h3>약어·지표 설명</h3>{t_g}<h3>정량 기준</h3>{t}<h3>참조-프리 규칙</h3>{t_rf}<h3>조합 방법 요약</h3>{bullets}"


def sec_parse_result(ctx):
    qa, route, criteria = ctx["qa"], ctx["route"], ctx["criteria"]
    if not qa:
        return missing(CMD["qa"])
    head = (
        "<h3>타입별 수집 성공·정확도</h3>"
        + parse_summary_table(ctx.get("parse_summary"))
        + "<h3>엔진 × 타입 — 교차 재현율 0.95 이상 문서 수(분모 = 파싱 성공 문서)</h3>"
        + perfect_matrix(ctx.get("parse_summary"), qa, ctx)
        + "<h3>실데이터 파싱 엔진 선정(~10개, 형식마다 2~3개)</h3>"
        + selection_html(ctx.get("selection"))
    )
    parse_crit = criteria.get("parse", [])
    a_rows = []
    order, chosen = rec_info(ctx)
    for engine in rec_sort(qa.get("engines", {}), order):
        for group, agg in sorted(qa["engines"][engine].items()):
            row = {"engine": engine, "group": group}
            for k in ("ok_rate", "cer", "value_recall", "num_halluc", "table_row_recall", "order", "sec"):
                row[k] = agg.get(k)
            passd = agg.get("pass") or {}
            for crit in parse_crit:
                row["pass_" + crit["id"]] = passd.get(crit["id"])
            a_rows.append(row)
    a_cols = [
        ("engine", "엔진", lambda v, r: rec_name(v, chosen)),
        ("group", "형식군"),
        ("ok_rate", "처리율", lambda v, r: fmt_metric("ok_rate", v)),
        ("cer", "CER", lambda v, r: fmt_metric("cer", v)),
        ("value_recall", "값 재현율", lambda v, r: fmt_metric("value_recall", v)),
        ("num_halluc", "수치 환각", lambda v, r: fmt_metric("num_halluc", v)),
        ("table_row_recall", "표 행", lambda v, r: fmt_metric("table_row_recall", v)),
        ("order", "순서", lambda v, r: fmt_metric("order", v)),
        ("sec", "s/쪽", lambda v, r: fmt_metric("sec", v)),
    ] + [("pass_" + crit["id"], crit["id"], lambda v, r: badge(v)) for crit in parse_crit]
    t_a = table(a_cols, a_rows, "파싱 채점 없음", row_cls=lambda r: "rec" if r["engine"] in chosen else "")

    b_rows = [{"fmt": fmt, "top3": ", ".join(ranked[:3]) if ranked else "—"} for fmt, ranked in sorted((route or {}).items())]
    t_b = table([("fmt", "형식"), ("top3", "상위 3")], b_rows, "라우팅 결과 없음")

    docs = sorted(qa.get("docs", {}))
    engines_all = rec_sort({e for d in qa.get("docs", {}).values() for e in d.get("engines", {})}, order)

    def matrix_cell(v, row):
        if not v:
            return "—"
        chars, lr = v.get("chars"), v.get("len_ratio")
        title = f"len_ratio={lr:.2f}" if isinstance(lr, (int, float)) else ""
        return f'<span title="{esc(title)}">{fmt_metric("chars", chars)}</span>'

    m_rows = [{"doc": doc, **{e: qa["docs"][doc].get("engines", {}).get(e, {}) for e in engines_all}} for doc in docs]
    m_cols = [("doc", "문서")] + [(e, ("★ " if e in chosen else "") + e, matrix_cell) for e in engines_all]
    t_c = table(m_cols, m_rows, "문서 없음", cls="matrix")

    diff_blocks = []
    for doc in docs:
        cand = [(e, ev) for e, ev in qa["docs"][doc].get("engines", {}).items() if ev.get("diff")]
        cand.sort(key=lambda x: x[1].get("value_recall") if x[1].get("value_recall") is not None else 1.0)
        for e, ev in cand[:3]:
            li = "".join(
                f"<li><code>기준: {esc(trunc(p[0]))}</code><br><code>출력: {esc(trunc(p[1] if len(p) > 1 else None))}</code></li>"
                for p in ev.get("diff", [])[:5]
            )
            diff_blocks.append(f"<p><b>{esc(doc)} × {esc(e)}</b></p><ul class='diff'>{li}</ul>")
    diff_html = "".join(diff_blocks) if diff_blocks else "<p class='muted'>차이 예시 없음</p>"

    flags = compute_ref_free_flags(qa)
    t_e = table([("doc", "문서"), ("engine", "엔진"), ("flag", "플래그"), ("detail", "상세")], flags[:300], "플래그 없음")
    note_e = f"<p class='muted'>{len(flags)}건 중 300건 표시</p>" if len(flags) > 300 else ""

    return (
        head + f"<h3>(a) 엔진 × 형식군</h3>{t_a}<h3>(b) 형식별 순위</h3>{t_b}"
        f"<h3>(c) 문서 × 엔진 글자 수</h3>{t_c}<h3>(d) 차이 예시</h3>{diff_html}"
        f"<h3>(e) 참조-프리 플래그</h3>{t_e}{note_e}"
    )


# ── 유형별 대표 문서·검토 대상(새 탭) — output/parse/_rep·_images·qa.json만 읽는다(VLM·LLM 재호출 없음, 전부 결정적).
# 입력은 수집/dev 서버 실데이터 그대로(정답 세트 불필요) — represent.py가 만든 _rep/<문서>.json(표 표준형 tables_std·
# rep{engine,candidates,facts_added,table_fix,standardize,scan_fill}·post{figures,supsub,...})과
# postprocess/figures.py가 만든 _images/index.jsonl(image_id·kind·provenance.fig_kind·edges·parent_image_id 등)만 본다.
TYPE_ORDER = [
    ("table_plain", "표(일반)"),
    ("table_merged", "표(병합 셀)"),
    ("table_multihdr", "표(다단 헤더)"),
    ("table_scanned", "표(스캔)"),
    ("fig_photo", "그림/사진"),
    ("fig_chart", "차트/그래프"),
    ("fig_flow", "흐름도(상자+화살표)"),
    ("fig_shape", "도형 도식(Word/Excel/PPT)"),
    ("fig_nested", "중첩 그림"),
    ("doc_damaged", "손상·암호화 문서"),
]
MAX_TYPE_SAMPLES = 5  # 유형당 대표 문서 수(요건)
MAX_SCAN_DOCS = 500  # ponytail: 고정 상한 — 대형 코퍼스에서 _rep 전부를 열지 않고 문서명 순 샘플만 본다(넘으면 이후 문서는 분류에서 빠짐)
STRONG_DISAGREE_ACC = 0.2  # 엔진 간 정확도 스프레드가 이보다 크면 "엔진 간 불일치"로 검토 대상
CHANGE_RATIO_HIGH = 0.5  # 후처리 전후 본문 글자 수 변화율이 이보다 크면 검토 대상(절대값)
REVIEW_SHOW_CAP = 100  # 표에 보일 검토 대상 줄 수 상한(전체는 review_items.csv)
BAD_SECURE_KINDS = {None, "보호 없음", "보호 없음(해당 없음)", "편집 잠금(읽기 가능)"}  # 이 외 kind = 암호·DRM·손상


def load_doctype_sources(out_dir):
    pd_ = Path(out_dir) / "parse"
    return {
        "parse_dir": pd_,
        "rep_dir": pd_ / "_rep",
        "rep_index": read_json(pd_ / "_rep" / "index.json"),
        "images": read_jsonl(pd_ / "_images" / "index.jsonl") or [],
    }


def _rep_doc(rep_dir, doc):
    return read_json(Path(rep_dir) / f"{doc}.json")


def _fig_kind(rec):
    """결정적 분류 — provenance.fig_kind(pipeline.transform.figures.figures.classify_figure_kind, 모델 호출 없음) 우선,
    없으면 VLM이 돌려준 kind 글자(한글·영문 모두 나옴)를 보조로."""
    k = (rec.get("provenance") or {}).get("fig_kind")
    if k:
        return k
    kk = (rec.get("kind") or "").strip().lower()
    if kk in ("chart", "그래프", "차트"):
        return "chart"
    if kk in ("photo", "사진"):
        return "photo"
    if kk in ("flow", "흐름도"):
        return "flow"
    return "other"


def pick_representative(items, limit=MAX_TYPE_SAMPLES):
    """유형 안에서 대표 문서 최대 limit개 — 문서명 정렬(결정적) 뒤 형식별로 돌려 뽑아 형식 다양성을 우선한다."""
    by_fmt = {}
    for it in sorted(items, key=lambda x: (x.get("doc") or "", x.get("ref") or "")):
        by_fmt.setdefault(it.get("fmt"), []).append(it)
    fmts, out, i = sorted(by_fmt), [], 0
    while len(out) < limit and fmts:
        fmt = fmts[i % len(fmts)]
        if by_fmt[fmt]:
            out.append(by_fmt[fmt].pop(0))
        else:
            fmts.remove(fmt)
            if not fmts:
                break
            continue
        i += 1
    return out[:limit]


def classify_items(ctx, out_dir):
    """파싱 산출물만으로 유형 분류 + 검토 대상(자동) + 전후 변화 메모 — 모두 결정적(재계산 없이 이미 있는 값만 읽음)."""
    src = load_doctype_sources(out_dir)
    rep_index, rep_dir, images = src["rep_index"], src["rep_dir"], src["images"]
    by_type = {k: [] for k, _ in TYPE_ORDER}
    review, change_notes = [], {}
    qa = ctx.get("qa") or {}
    docs_meta = qa.get("docs") or {}
    secure = ctx.get("secure") or {}
    if not rep_index:
        return by_type, review, change_notes, src

    doc_entries = sorted(rep_index.get("docs") or [], key=lambda r: r["doc"])[:MAX_SCAN_DOCS]
    for e in doc_entries:
        doc, fmt = e["doc"], e.get("format", "?")
        skind = (secure.get(doc) or {}).get("kind")
        if skind not in BAD_SECURE_KINDS:
            by_type["doc_damaged"].append({"doc": doc, "fmt": fmt, "ref": "-", "excerpt": skind})
        if not e.get("engine"):
            reason = e.get("reason") or "파싱 성공 엔진 없음"
            if skind in BAD_SECURE_KINDS and any(k in reason for k in ("암호", "DRM", "손상")):
                by_type["doc_damaged"].append({"doc": doc, "fmt": fmt, "ref": "-", "excerpt": reason})
            continue
        rep = _rep_doc(rep_dir, doc)
        if not rep:
            continue
        rr = rep.get("rep") or {}
        cands = rr.get("candidates") or []
        accs = [c.get("acc") for c in cands if c.get("ok") and isinstance(c.get("acc"), (int, float))]
        if len(accs) >= 2 and (max(accs) - min(accs)) > STRONG_DISAGREE_ACC:
            review.append({"doc": doc, "reason": "엔진 간 정확도 차 큼", "detail": f"스프레드 {max(accs) - min(accs):.2f}"})

        raw = read_json(src["parse_dir"] / rr["engine"] / f"{doc}.json") if rr.get("engine") else None
        if raw and raw.get("text") and len(raw["text"]) > 0:
            ratio = (len(rep.get("text") or "") - len(raw["text"])) / len(raw["text"])
            if abs(ratio) > CHANGE_RATIO_HIGH:
                review.append({"doc": doc, "reason": "후처리로 본문 길이 크게 변함", "detail": f"Δ{ratio:+.0%}"})
        other_ok = [c for c in cands if c.get("ok") and c.get("engine") != rr.get("engine")]
        if other_ok:
            other_raw = read_json(src["parse_dir"] / other_ok[0]["engine"] / f"{doc}.json")
            bt, ot = rep.get("tables") or [], (other_raw or {}).get("tables") or []
            if bt and len(bt) == len(ot):
                for i, (b, o) in enumerate(zip(bt, ot)):
                    if (b.get("rows"), b.get("cols")) != (o.get("rows"), o.get("cols")):
                        review.append(
                            {
                                "doc": doc,
                                "reason": "표 셀 수 불일치(엔진 간)",
                                "detail": f"t{i}: {rr.get('engine')} {b.get('rows')}x{b.get('cols')} vs "
                                f"{other_ok[0]['engine']} {o.get('rows')}x{o.get('cols')}",
                            }
                        )

        notes = []
        tf = rr.get("table_fix") or {}
        if tf.get("headers"):
            notes.append(f"표 머리글 보정 {tf['headers']}건")
        if tf.get("tab_rows"):
            notes.append(f"탭 표 인식 {tf['tab_rows']}행")
        if rr.get("facts_added"):
            notes.append(f"다른 엔진에서 표 칸 보충 {rr['facts_added']}건")
        post = rep.get("post") or {}
        if post.get("figures"):
            notes.append(f"그림 설명 추가 {post['figures']}건")
        if post.get("supsub"):
            notes.append("첨자(sup/sub) 복원")
        if (rr.get("standardize") or {}).get("changed"):
            notes.append(f"기호 표준화 {rr['standardize']['changed']}건")
        if (rr.get("scan_fill") or {}).get("filled"):
            notes.append(f"스캔 쪽 OCR로 채움 {len(rr['scan_fill']['filled'])}쪽")
        if notes:
            change_notes[doc] = notes

        grp = (docs_meta.get(doc) or {}).get("group")
        for t in rep.get("tables_std") or []:
            header = t.get("header") or []
            if not any(h.strip() for h in header):
                review.append({"doc": doc, "reason": "표에 머리글 없음", "detail": f"table {t.get('id')}"})
            merged = any((m.get("rowspan", 1) or 1) > 1 or (m.get("colspan", 1) or 1) > 1 for m in (t.get("merged") or []))
            multihdr = len(t.get("header_rows") or []) > 1
            scanned = grp == "image"
            first_row = (t.get("rows") or [[]])[0] if t.get("rows") else []
            excerpt = " | ".join(header) + (" — " + " | ".join(first_row) if first_row else "")
            item = {"doc": doc, "fmt": fmt, "ref": t.get("id"), "excerpt": excerpt}
            if merged:
                by_type["table_merged"].append(item)
            if multihdr:
                by_type["table_multihdr"].append(item)
            if scanned:
                by_type["table_scanned"].append(item)
            if not (merged or multihdr or scanned):
                by_type["table_plain"].append(item)

    for f in compute_ref_free_flags(qa):  # F3 = garbage 비율 높음(출력 깨짐 의심) — 이미 계산된 참조-프리 플래그 재사용
        if f["flag"] == "F3":
            review.append({"doc": f["doc"], "reason": "출력 깨짐 의심(엔진별)", "detail": f["detail"]})

    for rec in images:
        doc = rec.get("doc")
        fmt = (docs_meta.get(doc) or {}).get("format", "?")
        kind = _fig_kind(rec)
        excerpt = trunc(rec.get("caption") or (rec.get("vlm") or {}).get("summary") or (rec.get("vlm") or {}).get("text") or "", 120)
        item = {"doc": doc, "fmt": fmt, "ref": rec.get("image_id"), "excerpt": excerpt}
        if rec.get("parent_image_id") or rec.get("children"):
            by_type["fig_nested"].append(item)
        elif rec.get("origin") == "shape_render":
            by_type["fig_shape"].append(item)
        elif kind == "flow":
            by_type["fig_flow"].append(item)
        elif kind == "chart":
            by_type["fig_chart"].append(item)
        elif kind == "photo":
            by_type["fig_photo"].append(item)
        if rec.get("vlm_error"):
            review.append({"doc": doc, "reason": "VLM 실패", "detail": trunc(rec["vlm_error"], 120)})
        elif rec.get("skipped") == "VLM_FIGURES_MAX":
            review.append({"doc": doc, "reason": "VLM 상한 초과로 건너뜀(그림 상한)", "detail": rec.get("image_id")})
        if kind == "flow" and not rec.get("mermaid") and not ((rec.get("vlm") or {}).get("content") or {}).get("edges"):
            review.append({"doc": doc, "reason": "흐름도인데 연결선 0개", "detail": rec.get("image_id")})

    return by_type, review, change_notes, src


def before_after_html(src, review_sorted, change_notes, n=3):
    """개선 사례(전후 변화 메모가 있는 문서) n건 + 사람 확인 필요 사례(검토 대상에 오른 문서) n건 — 엔진 원문 vs 최종(_rep) 나란히."""
    improved = sorted(change_notes, key=lambda d: (-len(change_notes[d]), d))[:n]
    seen = set(improved)
    check = []
    for r in review_sorted:
        if r["doc"] not in seen:
            check.append(r["doc"])
            seen.add(r["doc"])
        if len(check) >= n:
            break
    if not improved and not check:
        return "<p class='muted'>비교할 사례 없음</p>"
    blocks = []
    for doc, tag in [(d, "개선") for d in improved] + [(d, "사람 확인 필요") for d in check]:
        rep = _rep_doc(src["rep_dir"], doc)
        if not rep:
            continue
        rr = rep.get("rep") or {}
        raw = read_json(src["parse_dir"] / rr["engine"] / f"{doc}.json") if rr.get("engine") else None
        raw_text, final_text = (raw or {}).get("text") or "", rep.get("text") or ""
        label = " · ".join(change_notes.get(doc) or [])
        if not label:
            ratio = difflib.SequenceMatcher(None, raw_text, final_text).ratio()
            label = f"본문 유사도 {ratio:.0%}(세부 신호 없음 — 글자 단위 비교)"
        why = next((r["reason"] for r in review_sorted if r["doc"] == doc), None)
        cls = "pass" if tag == "개선" else "warn"
        reason_html = f" — {esc(why)}" if tag != "개선" and why else ""
        blocks.append(
            f"<div class='bablock'><p><span class='{cls}'>[{esc(tag)}]</span> <b>{esc(doc)}</b>{reason_html} · {esc(label)}</p>"
            "<div class='twrap'><table class='tbl'><thead><tr>"
            f"<th>엔진 원문({esc(rr.get('engine') or '-')})</th><th>최종 결과(_rep, 후처리 반영)</th></tr></thead>"
            f"<tbody><tr><td>{esc(trunc(raw_text, 400))}</td><td>{esc(trunc(final_text, 400))}</td></tr></tbody></table></div></div>"
        )
    return "".join(blocks)


def sec_doctype(ctx):
    out_dir = ctx.get("out_dir")
    if not out_dir:
        return missing(CMD["rep"])
    by_type, review, change_notes, src = classify_items(ctx, out_dir)
    if not src["rep_index"]:
        return missing(CMD["rep"])
    blocks = [
        f"<p class='muted'>분류는 파싱 산출물(_rep·_images·qa.json)만으로 결정적으로 계산 — VLM·LLM 재호출 없음. "
        f"최대 {MAX_SCAN_DOCS}문서까지 스캔(그 이상은 넘침, 문서명 순).</p>"
    ]
    for key, label in TYPE_ORDER:
        items = by_type.get(key) or []
        rows = [
            {"doc": it["doc"], "fmt": it.get("fmt"), "ref": it.get("ref"), "excerpt": trunc(it.get("excerpt"), 160)}
            for it in pick_representative(items)
        ]
        t = table([("doc", "문서"), ("fmt", "형식"), ("ref", "표/그림 ID"), ("excerpt", "발췌")], rows, "대표 문서 없음")
        blocks.append(f"<h3>{esc(label)} ({len(items)}건 중 {len(rows)}건 표시)</h3>{t}")

    review_sorted = sorted(review, key=lambda r: (r["doc"], r["reason"]))
    shown = review_sorted[:REVIEW_SHOW_CAP]
    t_rev = table([("doc", "문서"), ("reason", "사유"), ("detail", "상세")], shown, "검토 대상 없음")
    more = (
        f"<p class='muted'>외 {len(review_sorted) - REVIEW_SHOW_CAP}건 — 전체는 <code>output/report/review_items.csv</code></p>"
        if len(review_sorted) > REVIEW_SHOW_CAP
        else ""
    )
    _wcsv(
        Path(out_dir) / "report" / "review_items.csv",
        ["doc", "reason", "detail"],
        [[r["doc"], r["reason"], r.get("detail", "")] for r in review_sorted],
    )
    blocks.append(f"<h3>검토 대상(자동, {len(review_sorted)}건)</h3>{t_rev}{more}")
    blocks.append(f"<h3>엔진 원문 vs 후처리 결과(사례)</h3>{before_after_html(src, review_sorted, change_notes)}")
    return "".join(blocks)


def sec_chunk(ctx):
    results = ctx["results"]
    if not results:
        return missing(CMD["results"])
    rows = [r for r in results if r.get("stage") == "chunk"] or results
    out = []
    for r in rows:
        combo, C, R = r.get("combo", {}), (r.get("C") or {}), (r.get("R") or {})
        out.append(
            {
                "parse": combo.get("parse"),
                "chunk": combo.get("chunk"),
                # run_combo 형식 {"C1": {n_chunks, mean_chars, p95_chars}, "C2", "C3"} 과 평면 형식 둘 다
                "c1_n": (C.get("C1") or {}).get("n_chunks", C.get("n")),
                "c1_mean": (C.get("C1") or {}).get("mean_chars", C.get("mean")),
                "c1_p95": (C.get("C1") or {}).get("p95_chars", C.get("p95")),
                "c2": C.get("C2", C.get("evidence_intact")),
                "c3": C.get("C3", C.get("table_split")),
                "r5": R.get("r5"),
                "mrr": R.get("mrr"),
            }
        )
    cols = [
        ("parse", "parse"),
        ("chunk", "chunk"),
        ("c1_n", "C1 n", lambda v, r: fmt_metric("chars", v)),
        ("c1_mean", "C1 mean", lambda v, r: fmt_metric("chars", v)),
        ("c1_p95", "C1 p95", lambda v, r: fmt_metric("chars", v)),
        ("c2", "C2", lambda v, r: fmt_metric("evidence_intact", v)),
        ("c3", "C3", lambda v, r: fmt_metric("table_split", v)),
        ("r5", "R@5", lambda v, r: fmt_metric("r5", v)),
        ("mrr", "MRR", lambda v, r: fmt_metric("mrr", v)),
    ]
    note = (
        "<p class='muted'>C1 n/mean/p95 = 청크 수·평균/95%ile 글자 수 · C2 = 근거 보존율(evidence_intact, 분할로 근거가 끊기지 않은 비율) · "
        "C3 = 표 쪼개짐 비율(table_split, 낮을수록 좋음). 약어·R@5·MRR은 QA 정량 기준 탭.</p>"
    )
    return note + table(cols, out, "청킹 결과 없음")


def sec_vector(ctx):
    results = ctx["results"]
    if not results:
        return missing(CMD["results"])
    seen, rows = set(), []
    ordered = sorted(results, key=combo_rank_key)
    for r in ordered:
        combo = r.get("combo", {})
        key = (combo.get("embed"), combo.get("retrieve"))
        if key in seen or key == (None, None):
            continue
        seen.add(key)
        R = r.get("R") or {}
        rows.append(
            {
                "embed": combo.get("embed"),
                "retrieve": combo.get("retrieve"),
                "r1": R.get("r1"),
                "r5": R.get("r5"),
                "r10": R.get("r10"),
                "mrr": R.get("mrr"),
                "ctx5": R.get("ctx5"),
                "ctx5m": R.get("ctx5m"),
                "p50": R.get("p50_ms"),
                "p95": R.get("p95_ms"),
            }
        )
    cols = [
        ("embed", "embed"),
        ("retrieve", "retrieve"),
        ("r1", "R@1", lambda v, r: fmt_metric("r1", v)),
        ("r5", "R@5", lambda v, r: fmt_metric("r5", v)),
        ("r10", "R@10", lambda v, r: fmt_metric("r10", v)),
        ("mrr", "MRR", lambda v, r: fmt_metric("mrr", v)),
        ("ctx5m", "유의미 글자(ctx5m)", lambda v, r: fmt_metric("ctx5m", v)),
        ("ctx5", "ctx5", lambda v, r: fmt_metric("ctx5", v)),
        ("p50", "p50", lambda v, r: fmt_metric("p50_ms", v)),
        ("p95", "p95", lambda v, r: fmt_metric("p95_ms", v)),
    ]
    note = (
        "<p class='muted'>embed·retrieve 조합마다 한 줄(중복 조합은 최초 1개만) — 정렬 = R@5 → MRR → 유의미 글자 수(ctx5m, 많을수록). "
        "p50·p95 = 검색 지연(ms, 작을수록 좋음). 약어는 QA 정량 기준 탭.</p>"
    )
    return note + table(cols, rows, "검색 결과 없음")


def sec_graph(ctx):
    results = ctx["results"]
    if not results:
        return missing(CMD["results"])
    rows = []
    for r in results:
        combo = r.get("combo", {})
        if not combo.get("graph") or combo.get("graph") == "none":
            continue
        G, R = (r.get("G") or {}), (r.get("R") or {})
        nodes, edges = G.get("n_nodes", G.get("nodes")), G.get("n_edges", G.get("edges"))
        if isinstance(nodes, dict):
            nodes = sum(nodes.values())
        if isinstance(edges, dict):
            edges = sum(edges.values())
        rows.append(
            {
                **{k: combo.get(k) for k in ("parse", "chunk", "embed", "retrieve")},
                "graph": combo.get("graph"),
                "nodes": nodes,
                "edges": edges,
                "g2": G.get("anchor_path"),
                "g3": G.get("isolated_ratio", G.get("isolated")),
                "g4": G.get("build_sec", G.get("load_sec")),
                "r5": R.get("r5"),
                "mrr": R.get("mrr"),
                "ctx5m": R.get("ctx5m"),
                "R": R,
                "types": " · ".join(f"{k} {v}" for k, v in (G.get("edges_by_type") or {}).items()),
            }
        )
    rows.sort(key=combo_rank_key)
    cols = [
        ("parse", "parse"),
        ("chunk", "chunk"),
        ("embed", "embed"),
        ("retrieve", "retrieve"),
        ("graph", "graph(연결)"),
        ("types", "엣지 유형"),
        ("nodes", "노드", lambda v, r: fmt_metric("nodes", v)),
        ("edges", "엣지", lambda v, r: fmt_metric("edges", v)),
        ("g2", "G2 앵커경로", lambda v, r: fmt_metric("anchor_path", v)),
        ("g3", "G3 고립", lambda v, r: fmt_metric("isolated", v)),
        ("g4", "G4 적재", lambda v, r: fmt_metric("sec", v)),
        ("r5", "R@5", lambda v, r: fmt_metric("r5", v)),
        ("mrr", "MRR", lambda v, r: fmt_metric("mrr", v)),
        ("ctx5m", "유의미 글자(ctx5m)", lambda v, r: fmt_metric("ctx5m", v)),
    ]
    note = (
        "<p class='muted'>연결 방식은 검색 방식이 <b>graph</b>(상위 5개 청크 + 그래프 이웃 최대 3개를 합친 컨텍스트)일 때만 결과를 바꾼다. "
        "정렬 = R@5 → MRR → 유의미 글자 수(많을수록). 그래프 노드(청크·개체·값)는 근거 청크의 원본 파일·쪽·줄을 메타로 들고 있다(근거 제시용).</p>"
    )
    return note + table(cols, rows, "그래프 결과 없음")


def sec_combo(ctx):
    results, criteria = ctx["results"], ctx["criteria"]
    if not results:
        return missing(CMD["results"])
    ret_crit = criteria.get("retrieve", [])

    def passes_all(r):
        R = r.get("R") or {}
        return all(check_pass(R.get(c["metric"]), c["dir"], c.get("value")) is True for c in ret_crit) if ret_crit else None

    asum = ctx.get("answers_summary") or {}
    ranked = sorted(results, key=lambda r: combo_rank_key(r, asum))[:20]
    rows = []
    for r in ranked:
        combo, R = r.get("combo", {}), (r.get("R") or {})
        a = asum.get(r.get("key")) or {}
        rows.append(
            {
                "parse": combo.get("parse"),
                "chunk": combo.get("chunk"),
                "embed": combo.get("embed"),
                "graph": combo.get("graph"),
                "retrieve": combo.get("retrieve"),
                "qa": a.get("qa_acc"),
                "r5": R.get("r5"),
                "mrr": R.get("mrr"),
                "ctx5m": R.get("ctx5m"),
                "ctx5": R.get("ctx5"),
                "p95": R.get("p95_ms"),
                "pass": passes_all(r),
            }
        )
    cols = [
        ("parse", "parse"),
        ("chunk", "chunk"),
        ("embed", "embed"),
        ("graph", "graph"),
        ("retrieve", "retrieve"),
        ("qa", "질문 정답률", lambda v, r: fmt_metric("qa_acc", v)),
        ("r5", "R@5", lambda v, r: fmt_metric("r5", v)),
        ("mrr", "MRR", lambda v, r: fmt_metric("mrr", v)),
        ("ctx5m", "유의미 글자(ctx5m)", lambda v, r: fmt_metric("ctx5m", v)),
        ("ctx5", "ctx5", lambda v, r: fmt_metric("ctx5", v)),
        ("p95", "p95", lambda v, r: fmt_metric("p95_ms", v)),
        ("pass", "기준 통과", lambda v, r: badge(v)),
    ]
    t = (
        "<p class='muted'>정렬 = 질문 정답률(답변 채점이 있을 때) → R@5 → MRR → 유의미 글자 수(많을수록). 약어는 QA 정량 기준 탭.</p>"
        + table(cols, rows, "조합 결과 없음")
    )
    beam = ctx["beam"]
    if beam:
        b_rows = []
        for stage_name, info in beam.items():
            if not isinstance(info, dict):
                continue
            b_rows.append(
                {
                    "stage": stage_name,
                    "cand": ", ".join(map(str, info.get("candidates", []))),
                    "sel": ", ".join(map(str, info.get("selected", []))),
                    "tau": info.get("tau"),
                    "widened": info.get("widened"),
                }
            )
        t_beam = table(
            [
                ("stage", "단계"),
                ("cand", "후보"),
                ("sel", "선택"),
                ("tau", "τ", lambda v, r: f"{float(v):.3f}" if isinstance(v, (int, float)) else "—"),
                ("widened", "확장", lambda v, r: "예" if v else "아니오"),
            ],
            b_rows,
            "빔 정보 없음",
        )
    else:
        t_beam = missing(CMD["beam"])
    return f"<h3>상위 20 조합</h3>{t}<h3>빔 탐색 단계</h3>{t_beam}"


def sec_answer(ctx):
    answers, results, criteria = ctx["answers"], ctx["results"], ctx["criteria"]
    if answers:
        crit = criteria.get("answer", [])

        def rate(field):
            vals = [a.get(field) for a in answers if isinstance(a.get(field), (int, float))]
            return statistics.mean(vals) if vals else None

        rows = []
        for c in crit:
            v = rate(c["metric"])
            rows.append(
                {
                    "metric": c["id"],
                    "name": c["name"],
                    "value": v,
                    "threshold": c.get("value"),
                    "pass": check_pass(v, c["dir"], c.get("value")),
                }
            )
        t = table(
            [
                ("metric", "ID"),
                ("name", "이름"),
                ("value", "실측", lambda v, r: fmt_metric("num_acc", v)),
                ("threshold", "기준"),
                ("pass", "판정", lambda v, r: badge(v)),
            ],
            rows,
            "답변 기준 없음",
        )
        summary = f"<p>답변 {len(answers)}건 채점 완료.</p>{t}" + answer_by_category(ctx)
    else:
        summary = missing(CMD["answers"])
    plan_rows = []
    if results:
        ranked = sorted(results, key=lambda r: -((r.get("R") or {}).get("r5") if (r.get("R") or {}).get("r5") is not None else -1))[:5]
        for r in ranked:
            combo = r.get("combo", {})
            plan_rows.append({"combo": " / ".join(combo.get(k, "—") for k in ("parse", "chunk", "embed", "graph", "retrieve"))})
    t_plan = table([("combo", "조합")], plan_rows, "조합 순위 미산출 — 상위 3~5개 × GLM 계획 대기")
    cats = table(
        [("cat", "유형"), ("ex", "예"), ("how", "채점")],
        [
            {"cat": "수치(value)", "ex": "계약 D-2024-122의 단가는?", "how": "값 일치(단위·쉼표 무시)"},
            {"cat": "client별", "ex": "고객사 X 계약의 수량은?", "how": "값 일치"},
            {"cat": "건수(count)", "ex": "고객사 X와의 과거 계약 건수는?", "how": "정수 일치"},
            {"cat": "합계(sum)", "ex": "제품 Y 전체 용량(L) 합계는?", "how": "상대오차 0.5% 이내"},
            {"cat": "RFI", "ex": "계약 Z의 주요 조건을 요약하시오", "how": "핵심 내용 포함률 0.8 이상"},
        ],
    ) + (
        "<p class='muted'>질문 세트: 개발 PC = python -m pipeline.eval.make_questions(가상 문서 정답에서) · 서버 = 사람이 RFI 예시·이력으로 "
        "output/eval/questions.jsonl 작성 → tools/verify_key.py로 여러 조합의 답·근거(파일·쪽·줄)와 교차 검증해 정답 확정.</p>"
    )
    return (
        f"{summary}<h3>답변 단계 계획</h3>"
        f"<p>검색 조합 상위 3~5개를 GLM으로 답변시켜 질문 유형별 정답률(qa_acc)·수치 정답률(A1)·근거 인용 정확도(A2)·무응답률(A3)을 잰다.</p>{t_plan}"
        f"<h3>질문 유형</h3>{cats}"
    )


def sec_appendix(ctx):
    t_cmd = table(
        [("stage", "산출"), ("cmd", "명령", lambda v, r: f"<code>{esc(v)}</code>")], [{"stage": k, "cmd": v} for k, v in CMD.items()]
    )
    f_rows = []
    for name, p in ctx["paths"].items():
        p = Path(p)
        if p.exists():
            st = p.stat()
            f_rows.append(
                {"name": name, "path": str(p), "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"), "size": st.st_size}
            )
        else:
            f_rows.append({"name": name, "path": str(p), "mtime": "—", "size": None})
    t_files = table(
        [
            ("name", "입력"),
            ("path", "경로"),
            ("mtime", "수정 시각"),
            ("size", "크기(바이트)", lambda v, r: fmt_metric("chars", v) if v is not None else "없음"),
        ],
        f_rows,
    )
    return f"<h3>재생성 명령</h3>{t_cmd}<h3>입력 파일</h3>{t_files}"


SECTION_FUNCS = {
    "hdr": lambda ctx, title: sec_header(ctx, title),
    "summary": lambda ctx, title: sec_summary(ctx),
    "data": lambda ctx, title: sec_data(ctx),
    "server": lambda ctx, title: sec_server(ctx),
    "model-parse": lambda ctx, title: sec_model_parse(ctx),
    "stack": lambda ctx, title: sec_stack(ctx),
    "criteria": lambda ctx, title: sec_criteria(ctx),
    "parse-result": lambda ctx, title: sec_parse_result(ctx),
    "doctype": lambda ctx, title: sec_doctype(ctx),
    "chunk": lambda ctx, title: sec_chunk(ctx),
    "vector": lambda ctx, title: sec_vector(ctx),
    "graph": lambda ctx, title: sec_graph(ctx),
    "combo": lambda ctx, title: sec_combo(ctx),
    "answer": lambda ctx, title: sec_answer(ctx),
    "appendix": lambda ctx, title: sec_appendix(ctx),
}

STYLE = """
:root{
  --bg:#f7f7f8; --fg:#1a1a1e; --muted:#6b6f76; --border:#dcdde1;
  --card:#ffffff; --th-bg:#eef0f3; --accent:#3060c0;
  --pass:#1a7f37; --fail:#c0392b; --warn:#9a6400; --code-bg:#eef0f3; --rec:#fff4cc; --rec-bar:#d49b00;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#15161a; --fg:#e7e8ea; --muted:#9a9ea6; --border:#33353c;
    --card:#1d1e23; --th-bg:#24262c; --accent:#7fa8ff;
    --pass:#5fbd76; --fail:#e0685a; --warn:#d9a441; --code-bg:#24262c; --rec:#3a3113; --rec-bar:#e0b440;
    color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#15161a; --fg:#e7e8ea; --muted:#9a9ea6; --border:#33353c;
  --card:#1d1e23; --th-bg:#24262c; --accent:#7fa8ff;
  --pass:#5fbd76; --fail:#e0685a; --warn:#d9a441; --code-bg:#24262c; --rec:#3a3113; --rec-bar:#e0b440;
  color-scheme: dark;
}
p.warn{border-left:3px solid var(--warn);padding:6px 10px;background:var(--card)}
.lowbadge{color:var(--warn);font-weight:600;white-space:nowrap}
tr.low>td{background:color-mix(in srgb, var(--warn) 12%, transparent)}
tr.rec>td{background:var(--rec)}
tr.rec>td:first-child{box-shadow:inset 3px 0 0 var(--rec-bar)}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;padding:0 16px 32px;font-size:14px;line-height:1.5;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;}
.report{max-width:100%;margin:0 auto;padding:16px 0}
h1{font-size:20px;margin:8px 0}
h3{font-size:15px;margin:16px 0 8px;color:var(--accent)}
.muted{color:var(--muted)}
code{background:var(--code-bg);padding:1px 4px;border-radius:3px;font-family:ui-monospace,Consolas,monospace}
.tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--border);position:sticky;top:0;
  background:var(--bg);z-index:5;padding:4px 0}
.tabs button{background:var(--card);color:var(--fg);border:1px solid var(--border);border-bottom:none;
  padding:6px 10px;border-radius:6px 6px 0 0;cursor:pointer;font-size:13px}
.tabs button[aria-selected="true"]{background:var(--accent);color:#fff;border-color:var(--accent)}
section[role="tabpanel"]{padding:12px 0}
.twrap{overflow-x:auto;border:1px solid var(--border);border-radius:6px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}
thead th{position:sticky;top:0;background:var(--th-bg);text-align:left;padding:6px 8px;
  border-bottom:1px solid var(--border);white-space:nowrap}
tbody td{padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}
tbody tr:hover{background:var(--th-bg)}
.matrix td:first-child, .matrix th:first-child{position:sticky;left:0;background:var(--card);z-index:2}
.pass{color:var(--pass);font-weight:600}
.fail{color:var(--fail);font-weight:600}
.na{color:var(--muted)}
.chip{display:inline-block;border:1px solid var(--border);border-radius:12px;padding:2px 8px;
  margin:2px 4px 2px 0;font-size:12px}
.chip.ok{color:var(--pass);border-color:var(--pass)}
.chip.no{color:var(--fail);border-color:var(--fail)}
.chips{margin:8px 0}
.fingerprint span{display:inline-block;margin:2px 12px 2px 0;color:var(--muted)}
.summary li{margin:4px 0}
ul.diff{list-style:none;padding-left:0}
ul.diff li{margin:6px 0;padding:6px;background:var(--card);border:1px solid var(--border);border-radius:4px}
h4{font-size:14px;margin:12px 0 4px}
.badge{display:inline-block;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600;color:#fff;white-space:nowrap}
.cand-op{background:var(--pass)} .cand-cand{background:var(--accent)}
.cand-ref{background:var(--th-bg);color:var(--muted)} .cand-excl{background:var(--fail)}
.cand-none{background:var(--th-bg);color:var(--muted)}
.lic-ok{background:var(--pass)} .lic-cond{background:var(--warn)} .lic-excl{background:var(--fail)}
.lic-none{background:var(--th-bg);color:var(--muted)}
.tune-ok{background:var(--pass)} .tune-part{background:var(--warn)} .tune-none{background:var(--fail)}
.tune-na{background:var(--th-bg);color:var(--muted)}
.sub{font-size:11px;margin-top:2px}
.src-link{font-size:11px}
tr.muted-row{opacity:.55}
.lic-box ul{margin:4px 0 8px;padding-left:18px}
@media (max-width:400px){body{padding:0 8px 24px}.tabs button{font-size:12px;padding:5px 8px}}
"""

SCRIPT = """
(function(){
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role=tab]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[role=tabpanel]'));
  function select(id){
    tabs.forEach(function(t){ t.setAttribute('aria-selected', t.dataset.tab === id ? 'true' : 'false'); });
    panels.forEach(function(p){ p.hidden = p.id !== 'panel-' + id; });
    try { localStorage.setItem('report-tab', id); } catch (e) {}
  }
  tabs.forEach(function(t){
    t.addEventListener('click', function(){
      select(t.dataset.tab);
      try { history.replaceState(null, '', '#' + t.dataset.tab); } catch (e) {}
    });
  });
  var init = (location.hash || '').replace('#', '');
  if (!init) { try { init = localStorage.getItem('report-tab') || ''; } catch (e) { init = ''; } }
  if (!init || !document.getElementById('panel-' + init)) { init = 'hdr'; }
  select(init);
})();
"""


def build_report(out_dir, catalog_path, server_path, criteria_path, title):
    ctx = load_ctx(out_dir, catalog_path, server_path, criteria_path)
    tabs_html = "".join(
        f'<button role="tab" id="tab-{tid}" data-tab="{tid}" aria-selected="false" aria-controls="panel-{tid}">{esc(label)}</button>'
        for tid, label in TAB_DEFS
    )
    panels_html = "".join(
        f'<section role="tabpanel" id="panel-{tid}" aria-labelledby="tab-{tid}" hidden>{SECTION_FUNCS[tid](ctx, title)}</section>'
        for tid, label in TAB_DEFS
    )
    return (
        f'<head><meta charset="utf-8"></head><title>{esc(title)}</title><style>{STYLE}</style>'
        f"<div class='report'><nav role='tablist' class='tabs'>{tabs_html}</nav>{panels_html}</div>"
        f"<script>{SCRIPT}</script>"
    )


def _wcsv(p, header, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def main(argv=None):
    ap = argparse.ArgumentParser(description="파이프라인 조합 평가 보고서 생성")
    ap.add_argument(
        "--out",
        default="output",
        help="결과 루트 — 이 아래 parse/ · eval/ · corpus/ 등을 읽음(SI8: run_combo 등의 "
        "--parse-dir처럼 parse 폴더를 바로 가리키지 않음, 그 경우 --parse-dir 사용)",
    )
    ap.add_argument(
        "--parse-dir", dest="parse_dir", help="SI8 별칭 — parse 폴더를 직접 지정(그 부모 폴더를 --out으로 씀, 폴더 이름이 'parse'여야 함)"
    )
    ap.add_argument("--catalog", default=str(TEMPLATES_DIR / "catalog.json"))
    ap.add_argument("--server", default=str(TEMPLATES_DIR / "server.json"))
    ap.add_argument("--criteria", default=str(CRITERIA_FILE))
    ap.add_argument("--title", default="파이프라인 조합 평가 보고서")
    ap.add_argument("--dest", default="output/report/report.html")
    args = ap.parse_args(argv)

    out_dir = str(Path(args.parse_dir).parent) if args.parse_dir else args.out
    html_out = build_report(out_dir, args.catalog, args.server, args.criteria, args.title)
    dest = Path(args.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html_out.replace("�", "&#xFFFD;"), encoding="utf-8")  # 파서가 깨뜨린 글자는 결과로 남기되 문자 참조로
    print(f"작성 완료: {dest} ({dest.stat().st_size:,} bytes)")


if __name__ == "__main__":
    from common.core.runlog import session

    with session("report"):
        main()
