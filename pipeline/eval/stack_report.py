#!/usr/bin/env python3
"""스택 조합 비교 HTML 보고서 — dev/cli/stack_matrix.py · dev/eval/stack_matrix.json을 **읽기만**(절대 안 건드림, 두 실험이 지금 돌고 있음).
설계: git 이력 docs/plans/comparison-report-structure-2026-10-03.md(탭(c4874dd0^) §1 · 순위 §2 · 형식 규칙 F1~F9 §9-1).

이 파일은 완전히 새로 추가된 산출물 생성기다 — stack_matrix.py의 report 서브커맨드(summary.md/json)는 그대로 두고,
그 옆에서 results.json·run_meta.json·layers_used.json·answers.json(있으면)·eval_set.json·doc_stats.json·
parity_*.json·기준선 qa_eval.json을 읽어 자기완결 HTML(탭·실패 탐색기·축별 기여·recall curve·answer-k)을 만든다.

사용:
  python dev/cli/stack_report.py --retrieval 20261003-121817 [--answers smoke-answer] --out docs/reviews/2026-10-03/stack-comparison.html
  python dev/cli/stack_report.py --retrieval loop1d-recall --answers loop1d-answer \
      --retrieval-distractors loop1d-recall-distractors --answers-distractors loop1d-answer-distractors \
      --out docs/reviews/2026-10-04/stack-comparison.html
  python dev/cli/stack_report.py --selftest
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import html
import json
import math
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # deploy/pipeline/eval(S4 — 옛 deploy/common_tools/evaluation)
from common.core.paths import APP_ROOT, E2E_ROOT, PKG_ROOT, PROJ_ROOT  # noqa: E402 — 폴더 재편 뒤 이 상수들만 바뀌면 됨

DEV = PKG_ROOT  # deploy/common/ (S6a — 옛 deploy/common_tools/와 같은 깊이 · 옛 dev/)
ROOT = PROJ_ROOT  # 저장소 루트
VALID = ROOT / "valid_env" / "unstructured"
RUN_ROOT = APP_ROOT / "output" / "eval" / "stack_matrix"
EVAL_SET_PATH = VALID / "eval_set.json"
STACK_CFG_PATH = (
    E2E_ROOT / "stack_matrix.json"
)  # 읽기만(그 파일도 안 건드림) — S6a부터 validation/e2e/(PC 전용 — 이미지에는 없어 빈 설정 {})
BASELINE_REF_PATH = APP_ROOT / "output" / "cache" / "hard_parse" / "runs" / "20261003-002255_qwen_qwen3.5-397b-a17b" / "qa_eval.json"

from common.core.paths import lookup_run_dir as _lookup_run_dir  # noqa: E402 — RV6, 아래 resolve_run_dir()이 감쌈

AXES = (
    "post",
    "chunker",
    "embed",
    "chunk_size",
    "summary",
    "methods",
    "rerank",
    "k",
)  # stack_matrix.py와 같은 축(읽기 전용 중복 — 그 파일은 안 건드림)
ANSWER_MIN_N = 10  # 정답률을 1차 순위 기준으로 쓰기 위한 최소 holdout 문항 수(미달이면 검색 전용 R@5로 대체, §2)
SAT_DIFF = 0.02  # 세트 안 최고-최저 차가 이 미만이면 포화(F6, 세트별 변별력 표시용)
SAT_MAX = 0.95  # 또는 최고값이 이 이상이면 포화
DISCRIM_SAT_FRAC = 0.8  # G3 — 조합의 이 비율 이상이 R@5=1.0이면 그 세트를 변별력 있는 세트 순위에서 뺀다

AXIS_LABEL = {
    "post": "후보정",
    "chunker": "청커",
    "embed": "임베딩",
    "chunk_size": "청크 크기",
    "summary": "요약",
    "methods": "검색 방법",
    "rerank": "재랭크",
    "k": "검색 k",
}
VALUE_LABEL = {
    ("post", "none"): "후보정 끔",
    ("post", "all"): "후보정 전부(기준)",
    ("methods", "vector"): "벡터만",
    ("methods", "bm25"): "BM25만",
    ("methods", "vector+bm25"): "벡터+BM25",
    ("chunker", "page"): "쪽 단위 청크",
    ("chunker", "fixed512"): "고정 512자 청크",
    ("chunker", "recursive"): "재귀 분할 청크",
    ("chunker", "sentence3"): "문장 3개 청크",
    ("chunker", "structure"): "구조 기반 청크(기준)",
    ("chunker", "structure_table"): "구조 기반 + 큰 표 행 묶음 분할 청크",
    ("embed", "bge-m3"): "bge-m3 임베딩(로컬)",
    ("embed", "qwen3-embedding-8b"): "qwen3-embedding-8b 임베딩(기준)",
    ("summary", "llm"): "LLM 요약",
    ("summary", "lead"): "첫 문장 요약(기준)",
    ("rerank", "off"): "재랭크 없음(기준)",
    ("rerank", "bge-reranker-v2-m3"): "bge-reranker-v2-m3 재랭크",
}
X1_PENDING = {"synth-edw": "구조 미구현(X1 전)"}  # I6 — X1(로컬 정형 저장소) 머지되면 이 줄만 지우면 됨.
POOL_V2_DS = "synth-distractors-v2"  # L3-2 — pool.json 안의 "최신 문서 기준" 가짜 데이터셋(evidence는 원본 데이터셋)
ABBR = [
    ("R@k", "검색 상위 k개 안에 정답 문서가 포함된 문항 비율"),
    ("MRR", "정답 문서가 처음 나온 순위의 역수를 문항 평균한 값(1에 가까우면 상위에 바로 나옴)"),
    ("McNemar p", "짝지은 두 조합에서 적중/실패가 갈린 문항만으로 차이를 검정한 양측 p값 — 0.05 미만이면 차이가 유의"),
    ("95% CI", "부트스트랩 2000회 재추출로 구한 차이(후보−기준 또는 1위−후보)의 95% 신뢰구간 — 0을 포함하면 구분 안 됨"),
    ("kw_in_context", "정답 키워드가 LLM에 넘긴 검색 근거 안에 있었는지(검색 성공 여부 — R1/G1 판정의 기준)"),
    ("p50/p90", "지연(ms) 분포의 50/90 백분위수"),
    ("gold_doc_coverage", "정답 근거 문서가 검색 묶음에 실제로 들어 있는 비율(0.95 미만이면 그 실행은 무효)"),
]


# ───────────────────────── 로딩(읽기 전용) ─────────────────────────
def _load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_run_dir(name):
    """RV6(10-09) — common/paths.lookup_run_dir로 옮김(동작 그대로, 읽기 전용)."""
    return _lookup_run_dir(RUN_ROOT, name)


def load_eval_set():
    return _load_json(EVAL_SET_PATH) or {}


def eval_set_commit():
    """I5 — eval_set.json의 git 커밋(짧은 해시). 실패하면(git 없음·추적 안 됨) None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", str(EVAL_SET_PATH)], cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        h = out.stdout.strip()
        return h or None
    except Exception:
        return None


def load_stack_cfg():
    return _load_json(STACK_CFG_PATH) or {}


def dataset_group_map(eval_set, stack_cfg=None):
    """데이터셋 → dev/holdout. model_matrix.py read_split()과 **같은 규칙**(G1 원인 중 하나 — 이전 버전은 eval_set.json의
    split 필드(7세트)만 읽어 synth-4clients가 dev로도 holdout으로도 안 잡혀 순위 풀에서 통째로 빠졌었다):
    1) dev/eval/stack_matrix.json의 datasets.dev/holdout을 기본값으로(synth-4clients가 여기 dev로 들어 있음),
    2) valid_env/unstructured/eval_set.json의 split이 있으면 그 값으로 덮어씀(새 세트 추가 시 여기만 갱신하면 자동 반영)."""
    stack_cfg = stack_cfg if stack_cfg is not None else load_stack_cfg()
    group = {}
    for g, names in (stack_cfg.get("datasets") or {}).items():
        gg = "holdout" if g in ("holdout", "held-out") else "dev"
        for ds in names:
            group[ds] = gg
    for ds, g in (eval_set.get("split") or {}).items():
        group[ds] = "holdout" if g in ("holdout", "held-out") else "dev"
    return group


def load_qa_text(ds):
    """질문 원문·정답(§5 실패 탐색기 표시용) — qa.json은 모든 세트에 question·gold_answer가 직접 있음(4clients 포함)."""
    p = VALID / ds / "qa.json"
    data = _load_json(p)
    if not data:
        return {}
    return {
        it["id"]: {"question": it.get("question"), "gold_answer": it.get("gold_answer"), "type": it.get("type")}
        for it in data.get("items", [])
    }


def load_gold_docs(ds):
    """질문 → 정답 근거 문서 파일명 집합(model_matrix.py _load_qa_items와 같은 규칙, 그 파일은 안 건드리고 여기 복제)."""
    base = VALID / ds
    qa = _load_json(base / "qa.json")
    if not qa:
        return {}
    out = {}
    if ds == "synth-4clients":
        man = _load_json(base / "manifest.json") or {}
        f2 = {d["doc_id"]: Path(d["file"].replace("\\", "/")).name for docs in man.get("formats", {}).values() for d in docs}
        for q in qa.get("items", []):
            out[q["id"]] = {f2.get(e["doc_id"]) for e in (q.get("evidence") or [])} - {None}
    else:
        for it in qa.get("items", []):
            docs = set()
            for e in it.get("evidence") or []:
                if e.get("doc"):
                    docs.add(e["doc"])
                docs.update(e.get("alt_docs") or [])
            out[it["id"]] = docs
    return out


def load_baseline_ref():
    return _load_json(BASELINE_REF_PATH)


def load_doc_stats():
    rows = []
    base = APP_ROOT / "output" / "store" / "p1"
    if not base.exists():
        return rows
    for p in base.glob("*/*/doc_stats.json"):
        data = _load_json(p)
        if not isinstance(data, list):
            continue
        post_cfg = p.parent.parent.name.split("@")[0]
        ds = p.parent.name.split("@")[0]
        for r in data:
            rows.append({**r, "_post_cfg": post_cfg, "_dataset": ds})
    return rows


def load_parity():
    out = {}
    base = APP_ROOT / "output" / "parity"
    if not base.exists():
        return out
    for p in base.glob("parity_synth-*.json"):
        data = _load_json(p)
        if data:
            out[p.stem.replace("parity_", "")] = data
    return out


def sibling_run_status():
    """F8 — 실행 폴더 중 비어 있는(전부 미완료) 것을 목록에서 구분."""
    out = []
    if not RUN_ROOT.exists():
        return out
    for d in sorted(RUN_ROOT.glob("*")):
        if not d.is_dir():
            continue
        has_results = (d / "results.json").exists() and bool(_load_json(d / "results.json"))
        has_answers = (d / "answers.json").exists() and bool(_load_json(d / "answers.json"))
        out.append({"name": d.name, "status": "있음" if (has_results or has_answers) else "미완료"})
    return out


# ───────────────────────── 통계(순수 함수 — stack_matrix.py/model_matrix.py와 알고리즘은 같지만
#   그 두 파일을 임포트하지 않고 이 보고서 전용으로 독립시킨다: 지금 실행 중인 실험 프로세스에 영향 0) ─────────────────────────
def mcnemar_p(pairs):
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if not x and y)
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    cdf = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * cdf)


def paired_diff_ci(pairs, resamples=2000, seed=0):
    """짝지은 (A 적중?, B 적중?) → (B−A) 적중률 차의 95% 부트스트랩 CI. 빈 목록이면 (None, None).
    K1 — 리샘플마다 문항 하나를 고르면 그 한 문항의 A·B 값을 **같은 인덱스**로 같이 뽑아야 짝이 유지된다
    (예전엔 A·B를 따로 뽑아 인덱스가 어긋나 — 모든 문항이 A==B(불일치 0)여도 가짜 CI가 나왔음). 전부 일치하면 [0,0]."""
    if not pairs:
        return None, None
    rng = random.Random(seed)
    n = len(pairs)
    diffs = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            a, b = pairs[rng.randrange(n)]  # 같은 문항의 A·B를 같이 뽑음(짝 유지)
            total += (1.0 if b else 0.0) - (1.0 if a else 0.0)
        diffs.append(total / n)
    diffs.sort()
    return diffs[int(0.025 * resamples)], diffs[min(resamples - 1, int(0.975 * resamples))]


# ───────────────────────── 서식(F1~F9) ─────────────────────────
def fmt_abs(v, digits=3):
    """절대값 — 부호 없음(F2)."""
    return "n/a" if v is None else f"{v:.{digits}f}"


def fmt_delta(v, digits=3):
    """차이 — 부호 있음(F2)."""
    return "n/a" if v is None else f"{v:+.{digits}f}"


def fmt_ms(v):
    """지연 — 정수 ms(F3)."""
    return "n/a" if v is None else f"{round(v):,}"


def fmt_p(v):
    return "n/a" if v is None else f"{v:.3f}"


def fmt_ci(ci):
    if not ci or ci[0] is None:
        return "n/a"
    lo, hi = ci[0] + 0.0, ci[1] + 0.0  # -0.0 → 0.0(표시용 — "-0.000"으로 헷갈리지 않게)
    return f"[{lo:+.3f}, {hi:+.3f}]"


def availability_note(n, valid=True, min_n=5):
    """F8 — 미실행/데이터 부족/무효를 하나의 'n/a'로 뭉치지 않는다."""
    if n is None or n == 0:
        return "미실행"
    if valid is False:
        return "무효(정답 문서 포함률<95%)"
    if n < min_n:
        return f"데이터 부족(n={n}<{min_n})"
    return None


def human_label(combo_name):
    """F9 — 콤보 기술 이름 옆 사람말 라벨."""
    if combo_name == "baseline":
        return "기준 조합"
    if "=" in combo_name:
        axis, val = combo_name.split("=", 1)
        lbl = VALUE_LABEL.get((axis, val))
        return lbl if lbl else f"{AXIS_LABEL.get(axis, axis)}={val}"
    return "추가 조합"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def dataset_tag(ds):
    """I6 — X1_PENDING에 있는 데이터셋 옆에 '구조 미구현(X1 전)' 꼬리표."""
    note = X1_PENDING.get(ds)
    return f" <span class='tag warn'>{esc(note)}</span>" if note else ""


# ───────────────────────── 지표 인덱스 ─────────────────────────
def combo_order(results):
    seen, order = set(), []
    for r in results:
        if r["combo"] not in seen:
            seen.add(r["combo"])
            order.append(r["combo"])
    return order


def index_retrieval(results):
    idx = {}
    for r in results:
        ret = r.get("retrieval")
        if not ret:
            continue
        idx[(r["combo"], r["dataset"])] = ret
    return idx


def index_answers_raw(answers):
    """(combo, dataset, k) → answer 결과(에러/미완료 포함). answers[]의 각 행에는 load_answer_runs()가 붙인
    `_run`(어느 실행에서 왔는지)·`_invalid`(--invalid-runs로 통째로 무효 처리됐는지)가 있다 — 여러 답 실행을 합칠 때
    같은 키가 겹치면 유효한 쪽을 우선하고(무효 vs 유효), 둘 다 같은 유효성이면 나중 실행(최신으로 간주)이 덮어쓴다(G7)."""
    idx = {}
    for r in answers:
        ans = r.get("answer") or {}
        key = (r["combo"], r["dataset"], r.get("k"))
        entry = {**ans, "_status": r.get("status"), "_group": r.get("group"), "_run": r.get("_run"), "_invalid": r.get("_invalid", False)}
        prev = idx.get(key)
        if prev is not None and prev.get("_invalid") is False and entry.get("_invalid") is True:
            continue  # 이미 유효한 데이터가 있는데 새로 온 게 무효면 덮어쓰지 않음
        idx[key] = entry
    return idx


def load_answer_runs(answer_dirs, invalid_run_names):
    """여러 답 실행 폴더(G7)를 합친다 — --invalid-runs에 이름이 있으면 그 실행에서 온 모든 행에 _invalid=True."""
    out = []
    for d in answer_dirs:
        rows = _load_json(Path(d) / "answers.json") or []
        is_invalid = Path(d).name in invalid_run_names
        for r in rows:
            out.append({**r, "_run": Path(d).name, "_invalid": is_invalid})
    return out


def flatten_answers(idx_ans_raw, preferred_k=10):
    """(combo, dataset) → 그 조합·세트에서 쓸 대표 k의 answer 결과(선호 k 없으면 있는 것 중 가장 작은 k).
    --invalid-runs로 무효 처리된 항목은 여기서 걷어낸다(없던 것처럼 — 유효한 k가 남아 있으면 그걸 씀)."""
    by_combo_ds = {}
    for (combo, ds, k), v in idx_ans_raw.items():
        if v.get("_invalid"):
            continue
        by_combo_ds.setdefault((combo, ds), {})[k] = v
    out = {}
    for key, by_k in by_combo_ds.items():
        k = preferred_k if preferred_k in by_k else sorted(by_k)[0]
        out[key] = {**by_k[k], "_k": k}
    return out


def flatten_answers_at_k(idx_ans_raw, k):
    """정확히 그 k로 기록된 (combo,dataset)만(flatten_answers의 선호-k 폴백 없음) — k별 순위·운영 k 결정용.
    --invalid-runs로 무효 처리된 항목은 없던 것처럼 뺀다(flatten_answers와 같은 규칙)."""
    out = {}
    for (combo, ds, kk), v in idx_ans_raw.items():
        if kk != k or v.get("_invalid"):
            continue
        out[(combo, ds)] = {**v, "_k": kk}
    return out


def determine_operating_k(idx_ans_raw, grp_map, idx_retr, ks):
    """운영 k = baseline 조합의 holdout 정답률(question-pooled)이 가장 높은 k(동률이면 작은 k, 결정성 tie-break).
    baseline에 holdout 정답률 데이터가 전혀 없으면(값이 모두 None) 가장 큰 k로 대체(가장 많은 근거를 준 k를 기본으로)."""
    best_k, best_rate = None, -1.0
    for k in sorted(ks):
        rate, _n = pooled_rate(flatten_answers_at_k(idx_ans_raw, k), "baseline", grp_map, "holdout", "correct", idx_retr)
        if rate is not None and rate > best_rate:
            best_rate, best_k = rate, k
    return best_k if best_k is not None else (max(ks) if ks else None)


def dataset_valid(idx_retr, combo, ds):
    """G1 — 정답 근거 문서 포함률<95%인 (조합,세트)는 무효(stack_matrix.py의 valid 필드 그대로 — synth-edw가 대표 사례).
    해당 조합의 검색 기록이 없으면(알 수 없음) 막지 않는다."""
    e = idx_retr.get((combo, ds))
    if not e:
        return True
    return bool(e.get("valid", True))


def pooled_rate(rows_idx, combo, grp_map, want_group, hit_key, idx_retr, datasets_filter=None):
    """G1 — 문항 단위로 풀어서(question-pooled) 비율을 낸다: 세트별 비율을 평균하는 게 아니라
    전체 적중 수/전체 문항 수로 한 번에 계산 — 세트마다 문항 수가 다를 때(예: synth-ops 21 vs synth-plant 38)
    세트 평균은 작은 세트에 과대 가중을 준다. 무효 데이터셋(coverage<95%)은 제외."""
    hits = n = 0
    for ds, g in grp_map.items():
        if g != want_group:
            continue
        if datasets_filter is not None and ds not in datasets_filter:
            continue
        if not dataset_valid(idx_retr, combo, ds):
            continue
        entry = rows_idx.get((combo, ds))
        if not entry:
            continue
        for row in entry.get("rows") or []:
            v = row.get(hit_key)
            if v is None:
                continue
            n += 1
            hits += 1 if v else 0
    return (hits / n if n else None), n


def pooled_mean(rows_idx, combo, grp_map, want_group, value_key, idx_retr, datasets_filter=None):
    """J1 — MRR 등 연속값의 question-pooled 평균(불리언 비율이 아니라 합/n) — pooled_rate와 같은 풀링 단위·무효 세트 제외."""
    total = n = 0
    for ds, g in grp_map.items():
        if g != want_group:
            continue
        if datasets_filter is not None and ds not in datasets_filter:
            continue
        if not dataset_valid(idx_retr, combo, ds):
            continue
        entry = rows_idx.get((combo, ds))
        if not entry:
            continue
        for row in entry.get("rows") or []:
            v = row.get(value_key)
            if v is None:
                continue
            n += 1
            total += v
    return (total / n) if n else None


def pooled_latency_p50(rows_idx, combo, grp_map, want_group, idx_retr, datasets_filter=None):
    """G5 — 평균(mean_ms)은 원격 임베딩/재랭크 API의 간헐적 느린 호출에 민감해 조합 간 차이를 왜곡한다.
    질문 단위 ms를 모두 모아(question-pooled, pooled_rate와 같은 풀링 단위) p50(중앙값)을 낸다."""
    ms_all = []
    for ds, g in grp_map.items():
        if g != want_group:
            continue
        if datasets_filter is not None and ds not in datasets_filter:
            continue
        if not dataset_valid(idx_retr, combo, ds):
            continue
        entry = rows_idx.get((combo, ds))
        if not entry:
            continue
        ms_all += [r["ms"] for r in (entry.get("rows") or []) if r.get("ms") is not None]
    if not ms_all:
        return None
    s = sorted(ms_all)
    return s[len(s) // 2]


def paired_rows(idx, combo_a, combo_b, grp_map, hit_key, idx_retr, groups=("dev", "holdout"), datasets_filter=None):
    """두 조합의 짝지은 (A 적중?, B 적중?) — rows[].id로 짝짓는다. 두 조합 중 하나라도 그 세트에서 무효면(G1)
    그 세트는 짝짓기에서 뺀다(한쪽만 걸러내면 짝이 안 맞음)."""
    pairs = []
    for ds, g in grp_map.items():
        if g not in groups or (combo_a, ds) not in idx or (combo_b, ds) not in idx:
            continue
        if datasets_filter is not None and ds not in datasets_filter:
            continue
        if not dataset_valid(idx_retr, combo_a, ds) or not dataset_valid(idx_retr, combo_b, ds):
            continue
        a_rows = {row["id"]: row.get(hit_key) for row in (idx[(combo_a, ds)].get("rows") or [])}
        b_rows = {row["id"]: row.get(hit_key) for row in (idx[(combo_b, ds)].get("rows") or [])}
        for qid in sorted(set(a_rows) & set(b_rows)):
            if a_rows[qid] is None or b_rows[qid] is None:
                continue
            pairs.append((bool(a_rows[qid]), bool(b_rows[qid])))
    return pairs


def is_post_axis(combo):
    return combo.startswith("post=")


# ───────────────────────── 순위(§2) — 문항 단위 풀링(G1), 무효 세트 제외(G1), post축 주석(G2), p50 지연(G5), n 표시(G4) ─────────────────────────
def compute_ranking(combos, idx_retr, flat_ans, grp_map, datasets_filter=None, pool_ctx=None):
    """정의: holdout/dev 비율은 각 조합에 대해 **valid=True인 데이터셋에 속한 문항을 모두 풀어(question-pooled)**
    총적중/총문항으로 계산한다(세트별 비율의 단순 평균이 아님 — 세트마다 문항 수가 달라 평균은 작은 세트에 과대 가중을 줌).
    datasets_filter가 있으면 그 데이터셋들만 풀에 넣는다(G3 — 변별력 있는 세트만 순위).
    pool_ctx(J1) — {"idx_hit1":, "idx_retr_pool":} 가 있고 답변 정답률 데이터가 없으면, 별도 색인 R@5(대부분 포화라
    변별력 없음) 대신 pool(합친 색인) R@1을 1차 기준으로, MRR을 동률 타이브레이크로 쓴다."""
    idx_valid = idx_retr  # pooled_rate/paired_rows의 valid(G1) 판정에 쓸 인덱스 — 분기별로 바뀜
    acc_by_combo = {}
    for combo in combos:
        rate, n = pooled_rate(flat_ans, combo, grp_map, "holdout", "correct", idx_retr, datasets_filter)
        if rate is not None and n >= ANSWER_MIN_N:
            acc_by_combo[combo] = (rate, n)

    if acc_by_combo:
        metric, hit_key, idx_used = "answer_accuracy", "correct", flat_ans
        reason = None
        scored = []
        for c in combos:
            hold, n_hold = acc_by_combo.get(c, (None, 0))
            dev, n_dev = pooled_rate(flat_ans, c, grp_map, "dev", "correct", idx_retr, datasets_filter)
            scored.append(
                {
                    "combo": c,
                    "holdout": hold,
                    "n_holdout": n_hold,
                    "dev": dev,
                    "n_dev": n_dev,
                    "mrr_holdout": None,
                    "latency_ms": pooled_latency_p50(flat_ans, c, grp_map, "dev", idx_retr, datasets_filter),
                    "is_post": is_post_axis(c),
                }
            )
    elif pool_ctx is not None:
        idx_valid = pool_ctx["idx_retr_pool"]
        metric, hit_key, idx_used = "pool_r1", "hit1", pool_ctx["idx_hit1"]
        reason = (
            "답변(A층) holdout 데이터가 없어(J1) 별도 색인 R@5는 세트 대부분(13/14)이 포화돼 변별력이 없음 — "
            "pool(합친 색인, 2-4 탭) R@1을 1차 기준으로, MRR을 동률 타이브레이크로 써서 대체(별도 색인 R@5는 참고용)."
        )
        scored = []
        for c in combos:
            hold, n_hold = pooled_rate(pool_ctx["idx_hit1"], c, grp_map, "holdout", "hit1", idx_valid, datasets_filter)
            dev, n_dev = pooled_rate(pool_ctx["idx_hit1"], c, grp_map, "dev", "hit1", idx_valid, datasets_filter)
            mrr_hold = pooled_mean(pool_ctx["idx_hit1"], c, grp_map, "holdout", "inv_rank", idx_valid, datasets_filter)
            scored.append(
                {
                    "combo": c,
                    "holdout": hold,
                    "n_holdout": n_hold,
                    "dev": dev,
                    "n_dev": n_dev,
                    "mrr_holdout": mrr_hold,
                    "latency_ms": pooled_latency_p50(pool_ctx["idx_hit1"], c, grp_map, "dev", idx_valid, datasets_filter),
                    "is_post": is_post_axis(c),
                }
            )
    else:
        metric, hit_key, idx_used = "retrieval_r5", "hit5", idx_retr
        _, n_ans_holdout = (
            pooled_rate(flat_ans, combos[0], grp_map, "holdout", "correct", idx_retr, datasets_filter) if combos else (None, 0)
        )
        reason = (
            f"답변(A층) holdout 데이터가 없거나 문항 수가 부족해(기준 n≥{ANSWER_MIN_N:d}) 정답률 순위를 계산할 수 없음 — "
            "검색 전용(R@5) 순위로 대체."
        )
        scored = []
        for c in combos:
            hold, n_hold = pooled_rate(idx_retr, c, grp_map, "holdout", "hit5", idx_retr, datasets_filter)
            dev, n_dev = pooled_rate(idx_retr, c, grp_map, "dev", "hit5", idx_retr, datasets_filter)
            scored.append(
                {
                    "combo": c,
                    "holdout": hold,
                    "n_holdout": n_hold,
                    "dev": dev,
                    "n_dev": n_dev,
                    "mrr_holdout": None,
                    "latency_ms": pooled_latency_p50(idx_retr, c, grp_map, "dev", idx_retr, datasets_filter),
                    "is_post": is_post_axis(c),
                }
            )

    scored.sort(
        key=lambda r: (
            r["holdout"] if r["holdout"] is not None else -1,
            r["mrr_holdout"] if r.get("mrr_holdout") is not None else -1,
            r["dev"] if r["dev"] is not None else -1,
        ),
        reverse=True,
    )
    if not scored:
        return metric, reason, []
    # I2 — 동률(holdout 비율·n이 정확히 같음) 처리: "동률이면 더 단순한 조합(baseline 우선)"으로 1위를 정한다.
    top_val = (scored[0]["holdout"], scored[0]["n_holdout"])
    tied = [r for r in scored if (r["holdout"], r["n_holdout"]) == top_val]
    is_tie = len(tied) > 1
    if is_tie and scored[0]["combo"] != "baseline" and any(r["combo"] == "baseline" for r in tied):
        base_row = next(r for r in tied if r["combo"] == "baseline")
        scored.remove(base_row)
        scored.insert(0, base_row)
    top_name = scored[0]["combo"]
    tied_others = [r["combo"] for r in tied if r["combo"] != top_name] if is_tie else []
    out = []
    for i, row in enumerate(scored):
        if row["combo"] == top_name:
            p, ci, equiv = None, (0.0, 0.0), True
        else:
            pairs = paired_rows(idx_used, top_name, row["combo"], grp_map, hit_key, idx_valid, datasets_filter=datasets_filter)
            p = mcnemar_p(pairs) if pairs else None
            ci = paired_diff_ci(pairs)
            equiv = bool(pairs) and p is not None and p >= 0.05 and ci[0] is not None and ci[0] <= 0 <= ci[1]
            # G2 — 검색 전용(R@5) 순위에서는 post축이 문서 적중 포화로 효과를 측정할 수 없어 '동급' 주장에서 뺀다(표에는 그대로 보임).
            if metric == "retrieval_r5" and row["is_post"]:
                equiv = False
        out.append(
            {
                "rank": i + 1,
                **row,
                "mcnemar_p_vs_top": p,
                "ci_vs_top": ci,
                "equivalent_to_top": equiv,
                "tie": is_tie if i == 0 else False,
                "tied_combos": tied_others if i == 0 else [],
            }
        )
    kept = out[:3]
    for row in out[3:10]:
        if not row["equivalent_to_top"]:
            break
        kept.append(row)
    return metric, reason, kept


# ───────────────────────── 축별 기여(§2, F4 — 기준 대비 '차'의 CI) ─────────────────────────
def compute_axis_table(all_combo_rows, idx_retr, grp_map):
    """R@5 기반(검색 축 비교 목적) — question-pooled(G1)·무효 세트 제외(G1)·p50 지연(G5)·post축은 측정 불가 주석(G2)."""
    rows = []
    for axis in AXES:
        for combo in all_combo_rows:
            if not combo.startswith(f"{axis}="):
                continue
            dev_b, n_dev_b = pooled_rate(idx_retr, "baseline", grp_map, "dev", "hit5", idx_retr)
            dev_c, n_dev_c = pooled_rate(idx_retr, combo, grp_map, "dev", "hit5", idx_retr)
            hold_b, n_hold_b = pooled_rate(idx_retr, "baseline", grp_map, "holdout", "hit5", idx_retr)
            hold_c, n_hold_c = pooled_rate(idx_retr, combo, grp_map, "holdout", "hit5", idx_retr)
            dev_delta = (dev_c - dev_b) if (dev_c is not None and dev_b is not None) else None
            hold_delta = (hold_c - hold_b) if (hold_c is not None and hold_b is not None) else None
            pairs = paired_rows(idx_retr, "baseline", combo, grp_map, "hit5", idx_retr)
            p = mcnemar_p(pairs) if pairs else None
            ci = paired_diff_ci(pairs) if pairs else (None, None)
            rows.append(
                {
                    "axis": axis,
                    "combo": combo,
                    "dev_delta": dev_delta,
                    "holdout_delta": hold_delta,
                    "n_dev": n_dev_c,
                    "n_holdout": n_hold_c,
                    "mcnemar_p": p,
                    "ci": ci,
                    "n_pairs": len(pairs),
                    "is_post": is_post_axis(combo),
                    "cand_ms": pooled_latency_p50(idx_retr, combo, grp_map, "dev", idx_retr),
                    "base_ms": pooled_latency_p50(idx_retr, "baseline", grp_map, "dev", idx_retr),
                }
            )
    return rows


# ───────────────────────── 포화 점검(F6/I1) ─────────────────────────
def saturation_by_dataset(idx_retr, datasets, flat_ans=None, grp_map=None, combos=None, use_accuracy=False):
    """I1 — 포화는 **결정에 쓰는 지표**로 판정한다: 순위가 정답률(answer_accuracy)이면 세트별 운영 k 정답률로,
    아니면(검색 전용 순위) R@5로. R@1·MRR 범위는 판정과 무관하게 참고용으로 항상 같이 낸다
    (9-1 — R@5가 포화돼도 R@1·MRR엔 변별력이 남을 수 있음)."""
    out = {}
    for ds in datasets:
        r5_vals = [v["r5"] for (c, d), v in idx_retr.items() if d == ds and v.get("r5") is not None]
        r1_vals = [
            (v.get("recall_at") or {}).get("1")
            for (c, d), v in idx_retr.items()
            if d == ds and (v.get("recall_at") or {}).get("1") is not None
        ]
        mrr_vals = [v["mrr"] for (c, d), v in idx_retr.items() if d == ds and v.get("mrr") is not None]
        if not r5_vals:
            continue
        acc_vals = []
        if use_accuracy and flat_ans is not None and grp_map is not None and combos is not None:
            g = grp_map.get(ds)
            acc_vals = [v for v in (pooled_rate(flat_ans, c, grp_map, g, "correct", idx_retr, {ds})[0] for c in combos) if v is not None]
        judge_vals = acc_vals if acc_vals else r5_vals
        lo, hi = min(judge_vals), max(judge_vals)
        out[ds] = {
            "min": lo,
            "max": hi,
            "spread": hi - lo,
            "saturated": (hi - lo) < SAT_DIFF or hi >= SAT_MAX,
            "n_combos": len(judge_vals),
            "metric": "answer_accuracy" if acc_vals else "retrieval_r5",
            "r1_min": (min(r1_vals) if r1_vals else None),
            "r1_max": (max(r1_vals) if r1_vals else None),
            "mrr_min": (min(mrr_vals) if mrr_vals else None),
            "mrr_max": (max(mrr_vals) if mrr_vals else None),
        }
    return out


def discriminating_datasets(idx_retr, datasets, combos):
    """G3 — 조합의 80% 이상이 R@5=1.0이면 그 세트는 변별력 있는 세트 순위에서 뺀다(F6의 포화 표시와는 다른,
    G3가 명시한 기준). 조합 데이터가 전혀 없는 세트는 포함하지 않는다(판단할 근거가 없음)."""
    keep = []
    for ds in datasets:
        vals = [idx_retr[(c, ds)]["r5"] for c in combos if (c, ds) in idx_retr and idx_retr[(c, ds)].get("r5") is not None]
        if not vals:
            continue
        frac_sat = sum(1 for v in vals if v >= 1.0) / len(vals)
        if frac_sat < DISCRIM_SAT_FRAC:
            keep.append(ds)
    return keep


# ───────────────────────── Recall curve(§8 실측 시) ─────────────────────────
RECALL_KS = (1, 3, 5, 10, 20, 30, 50)


def build_recall_curve(idx_retr, combos, grp_map):
    """G1 — question-pooled: gold_rank(새 형식 rows[])로 직접 적중/문항수를 세어 R@k를 낸다(세트 평균 아님).
    무효 세트(G1)는 뺀다. recall_at 필드가 있는 조합·세트만 '새 형식'으로 보고 집계(없으면 미실행)."""
    out, any_data = {}, False
    for combo in combos:
        per_group = {}
        for g in ("dev", "holdout"):
            n = 0
            hit_counts = {k: 0 for k in RECALL_KS}
            for ds, gg in grp_map.items():
                if gg != g or not dataset_valid(idx_retr, combo, ds):
                    continue
                entry = idx_retr.get((combo, ds))
                if not entry or not entry.get("recall_at"):
                    continue
                any_data = True
                for row in entry.get("rows") or []:
                    n += 1
                    gr = row.get("gold_rank")
                    for k in RECALL_KS:
                        if gr is not None and gr <= k:
                            hit_counts[k] += 1
            per_group[g] = {"n": n, "rate": {k: (hit_counts[k] / n if n else None) for k in RECALL_KS}}
        out[combo] = per_group
    return out, any_data


# ───────────────────────── answer-k(§8) ─────────────────────────
def build_answer_k(idx_ans_raw, grp_map, idx_retr):
    """G1 — question-pooled(세트 평균 아님), 무효 세트 제외, 무효 처리된 실행(_invalid) 제외."""
    combos = sorted({c for (c, ds, k) in idx_ans_raw})
    ks = sorted({k for (c, ds, k) in idx_ans_raw if k is not None})
    table = {}
    for c in combos:
        table[c] = {}
        for k in ks:
            table[c][k] = {}
            for g in ("dev", "holdout"):
                hits = n = 0
                for ds, gg in grp_map.items():
                    if gg != g or not dataset_valid(idx_retr, c, ds):
                        continue
                    entry = idx_ans_raw.get((c, ds, k))
                    if not entry or entry.get("_invalid"):
                        continue
                    for row in entry.get("rows") or []:
                        v = row.get("correct")
                        if v is None:
                            continue
                        n += 1
                        hits += 1 if v else 0
                table[c][k][g] = (hits / n if n else None, n)
    return combos, ks, table


# ───────────────────────── W20 — ref_hit·attach_hit(운영 k, 조합×데이터셋) ─────────────────────────
def build_ref_attach_table(flat_ans, idx_retr, grp_map, combos):
    """참조 문서(ref_hit)·첨부(attach_hit) 적중률 — 두 필드 다 해당 질문 유형이 있는 세트에서만 non-null이라
    pooled_rate가 자동으로 걸러 준다(값 없는 행은 n에 안 들어감). 행이 전혀 없는(n=0) 조합×세트는 뺀다."""
    ds_with_field = sorted(
        {
            ds
            for (_, ds), e in flat_ans.items()
            for row in (e.get("rows") or [])
            if row.get("ref_hit") is not None or row.get("attach_hit") is not None
        }
    )
    rows = []
    for combo in combos:
        for ds in ds_with_field:
            g = grp_map.get(ds)
            if not g:
                continue
            ref_rate, ref_n = pooled_rate(flat_ans, combo, grp_map, g, "ref_hit", idx_retr, {ds})
            att_rate, att_n = pooled_rate(flat_ans, combo, grp_map, g, "attach_hit", idx_retr, {ds})
            if not ref_n and not att_n:
                continue
            rows.append(
                {
                    "combo": combo,
                    "dataset": ds,
                    "group": g,
                    "ref_rate": ref_rate,
                    "ref_n": ref_n,
                    "attach_rate": att_rate,
                    "attach_n": att_n,
                }
            )
    return rows


# ───────────────────────── 데이터 품질 경고(보고서 맨 위) ─────────────────────────
def build_data_quality_warnings(idx_retr):
    """gold_doc_coverage<1 또는 valid=false인 세트 — baseline 콤보 값을 대표로 쓴다(파싱 산출물은 콤보 간 보통 공유).
    4clients·edw는 알려진 사례라 사람말 사유를 덧붙인다(다른 세트는 수치만)."""
    known_note = {
        "synth-4clients": "스캔 PDF 10건이 대표 파싱 없음 — 알려진 파싱 결함(커밋 9da854b에서 일부 수정), 재실행 대기.",
        "synth-edw": "valid=false(무효) 상태 — 원인 조사 전까지 이 세트의 조합 간 차이는 근거로 쓰지 말 것.",
    }
    out = []
    for (combo, ds), ret in idx_retr.items():
        if combo != "baseline":
            continue
        cov = ret.get("gold_doc_coverage")
        if ret.get("valid") is False or (cov is not None and cov < 1):
            out.append({"dataset": ds, "coverage": cov, "missing": ret.get("missing_gold_docs") or [], "note": known_note.get(ds, "")})
    return sorted(out, key=lambda r: r["dataset"])


# ───────────────────────── V11 — 방해 문서(distractors) 비교 ─────────────────────────
def distractor_status_map(results):
    """retrieval 키가 없는(skipped/실패) 행의 사유 — '미실행'을 그냥 비우지 않고 왜 비는지 보여주려고."""
    out = {}
    for r in results or []:
        if not r.get("retrieval"):
            out[(r.get("combo"), r.get("dataset"))] = r.get("reason") or r.get("status") or "미실행"
    return out


def build_distractor_comparison(idx_retr, idx_retr_dist, dist_status, idx_ans_raw, idx_ans_dist_raw, grp_map, operating_k, saturation):
    """데이터셋별 평문 vs 방해 문서 비교(§V11) — 평문 쪽은 운영 k의 정답률, 방해 문서 쪽은 (보통 k=10 하나뿐이라)
    있는 k 중 아무거나 쓰고 그 k를 같이 적는다. n은 파이프라인이 이미 unique_under_distractors로 거른 값(여기선 그대로 사용)."""
    rows = []
    for ds in sorted(grp_map):
        p_ret = idx_retr.get(("baseline", ds)) or {}
        d_ret = idx_retr_dist.get(("baseline", ds))
        p_ans = idx_ans_raw.get(("baseline", ds, operating_k)) if operating_k is not None else None
        d_ans_entry = next(((k, v) for (c, d, k), v in idx_ans_dist_raw.items() if c == "baseline" and d == ds), None)
        d_ans_k, d_ans = d_ans_entry if d_ans_entry else (None, None)
        sat = saturation.get(ds)
        p_r5 = p_ret.get("r5")
        relief = None
        if sat is not None and sat.get("saturated") and p_r5 is not None and p_r5 >= SAT_MAX:
            if d_ret and d_ret.get("r5") is not None:
                relief = "해소" if d_ret["r5"] < SAT_MAX else "유지"
            else:
                relief = "판정 불가(미실행)"
        rows.append(
            {
                "dataset": ds,
                "group": grp_map.get(ds),
                "plain": {
                    "n": p_ret.get("n"),
                    "r5": p_ret.get("r5"),
                    "r1": (p_ret.get("recall_at") or {}).get("1"),
                    "mrr": p_ret.get("mrr"),
                    "acc": (p_ans or {}).get("accuracy") if p_ans else None,
                },
                "dist": {
                    "n": (d_ret or {}).get("n") if d_ret else ((d_ans or {}).get("n") if d_ans else None),
                    "r5": (d_ret or {}).get("r5"),
                    "r1": ((d_ret or {}).get("recall_at") or {}).get("1") if d_ret else None,
                    "mrr": (d_ret or {}).get("mrr"),
                    "confusion": (d_ret or {}).get("distractor_confusion_rate"),
                    "acc": (d_ans or {}).get("accuracy") if d_ans else None,
                    "k": d_ans_k,
                    # retrieval_status는 검색 지표(R@5·R@1·MRR·오인율)에만 걸린다 — answer 정답률은 답 실행이
                    # 따로 성공했으면(흔한 경우, 검색 S는 못 빌드했어도 답은 다른 경로로 나올 수 있음) 그대로 보여준다.
                    "retrieval_status": None if d_ret else dist_status.get(("baseline", ds), "미실행"),
                },
                "saturated_plain": bool(sat and sat.get("saturated")),
                "relief": relief,
            }
        )
    return rows


# ───────────────────────── pool(합친 색인, L3-2) — 구판·방해 문서 오인율을 엄격/느슨으로 분리 ─────────────────────────
def rank_confusion_split(rows, rank_key, gold_key="gold_rank"):
    """L3-2 — results.json에 저장된 oldver_confusion/distractor_confusion은 '구판이 정답보다 먼저' OR 'top10에 낌'의 OR라
    근접 복제 세트에선 거의 항상 1.0에 가까워 변별이 안 됨. 여기서 행별 rank_key(그 문서 묶음 중 가장 앞 순위, 없으면 None)와
    gold_rank(정답 문서 중 가장 앞 순위)로 둘을 직접 다시 가른다: 엄격(strict, 주 지표)=그 순위가 모든 정답 문서보다 위
    (rank < gold_rank, 정답이 아예 없으면 무조건 위) · 느슨(loose, 참고용)=top10 안에 낌(rank<=10).
    rank_key 필드가 아예 없는 행(그 묶음을 안 잰 실행)은 n에서 뺀다."""
    n = strict_n = loose_n = 0
    for r in rows:
        if rank_key not in r:
            continue
        n += 1
        rank, gold_rank = r.get(rank_key), r.get(gold_key)
        if rank is not None and (gold_rank is None or rank < gold_rank):
            strict_n += 1
        if rank is not None and rank <= 10:
            loose_n += 1
    return (strict_n / n if n else None), (loose_n / n if n else None), n


def build_pool_retrieval(idx_retr_pool, idx_retr_main, grp_map, combos_pool):
    """데이터셋×콤보별 R@1·R@5·MRR + 별도 색인(idx_retr_main, 있으면) 대비 R@1 차 + 구판(v2)·방해 문서(v1) 오인율(엄격/느슨)."""
    rows = []
    for combo in combos_pool:
        for ds in sorted({d for (c, d) in idx_retr_pool if c == combo}):
            e = idx_retr_pool[(combo, ds)]
            r1 = (e.get("recall_at") or {}).get("1")
            sep = idx_retr_main.get((combo, ds)) if idx_retr_main else None
            sep_r1 = (sep.get("recall_at") or {}).get("1") if sep else None
            ev_rows = e.get("rows") or []
            ov_strict, ov_loose, n_ov = rank_confusion_split(ev_rows, "oldver_rank")
            dv_strict, dv_loose, n_dv = rank_confusion_split(ev_rows, "distractor_rank")
            rows.append(
                {
                    "combo": combo,
                    "dataset": ds,
                    "group": grp_map.get(ds) or "-",
                    "n": e.get("n"),
                    "r1": r1,
                    "r5": e.get("r5"),
                    "mrr": e.get("mrr"),
                    "r1_separate": sep_r1,
                    "r1_delta": (r1 - sep_r1) if (r1 is not None and sep_r1 is not None) else None,
                    "oldver_strict": ov_strict,
                    "oldver_loose": ov_loose,
                    "n_oldver": n_ov,
                    "distractor_strict": dv_strict,
                    "distractor_loose": dv_loose,
                    "n_distractor": n_dv,
                }
            )
    return rows


def build_pool_answers(idx_ans_raw_pool):
    """(콤보,데이터셋,k) → 정답률·n·구판값 유출률(oldver_value_in_answer_rate, synth-distractors-v2만 값 있음)."""
    return [
        {
            "combo": c,
            "dataset": ds,
            "k": k,
            "n": v.get("n"),
            "accuracy": v.get("accuracy"),
            "oldver_value_in_answer_rate": v.get("oldver_value_in_answer_rate"),
        }
        for (c, ds, k), v in sorted(idx_ans_raw_pool.items())
    ]


def build_pool_r1_index(idx_retr_pool):
    """J1 — pool 행의 gold_rank에서 hit1(R@1 — pooled_rate용)·inv_rank(MRR — pooled_mean용) 파생.
    gold_rank가 없으면(정답 문서를 못 찾음) hit1=False·inv_rank=0.0(MRR 정의상 못 찾으면 0 기여)."""
    idx = {}
    for key, e in idx_retr_pool.items():
        rows = []
        for r in e.get("rows") or []:
            gr = r.get("gold_rank")
            rows.append({"id": r.get("id"), "hit1": gr == 1, "inv_rank": (1.0 / gr) if gr else 0.0, "ms": r.get("ms")})
        idx[key] = {"rows": rows}
    return idx


# ───────────────────────── 개선 켬/끔(J2) — 데이터셋별 on/off R@1·MRR + 짝지은 McNemar p·부트스트랩 CI ─────────────────────────
def resolve_split_label(ds, grp_map):
    """K3 — grp_map에 없는(단일 세트가 아닌) 데이터셋은 문항별 evidence[0].dataset을 grp_map으로 매핑해
    원래 세트별 dev/holdout 문항 수를 센다(synth-distractors-v2처럼 여러 세트에서 문항을 모은 가짜 데이터셋).
    매핑 결과가 한 그룹뿐이면 그 그룹 이름만, 둘 이상이면 '혼합(dev N · holdout M)'. 알 수 없으면 '-'."""
    g = grp_map.get(ds)
    if g:
        return g
    qa = _load_json(VALID / ds / "qa.json")
    if not qa:
        return "-"
    counts = {}
    for it in qa.get("items") or []:
        ev = (it.get("evidence") or [{}])[0]
        src_g = grp_map.get(ev.get("dataset"))
        if src_g:
            counts[src_g] = counts.get(src_g, 0) + 1
    if not counts:
        return "-"
    if len(counts) == 1:
        return next(iter(counts))
    return "혼합(" + " · ".join(f"{g} {n}" for g, n in sorted(counts.items())) + ")"


def build_onoff_table(dir_a, dir_b, combo, grp_map):
    """두 실행 폴더(dir_a=끔/off, dir_b=켬/on)에서 같은 콤보의 공통 데이터셋만 비교한다.
    McNemar p·CI는 기존 mcnemar_p/paired_diff_ci를 재사용 — 짝은 두 실행 모두에 있는 질문 id의 hit1(gold_rank==1)."""
    results_a = _load_json(Path(dir_a) / "results.json") or []
    results_b = _load_json(Path(dir_b) / "results.json") or []
    idx_a, idx_b = index_retrieval(results_a), index_retrieval(results_b)
    datasets = sorted({d for (c, d) in idx_a if c == combo} & {d for (c, d) in idx_b if c == combo})
    rows = []
    for ds in datasets:
        ea, eb = idx_a[(combo, ds)], idx_b[(combo, ds)]
        rank_a = {r["id"]: r.get("gold_rank") for r in (ea.get("rows") or [])}
        rank_b = {r["id"]: r.get("gold_rank") for r in (eb.get("rows") or [])}
        shared_q = sorted(set(rank_a) & set(rank_b))  # 두 실행에 공통인 문항
        pairs = [(rank_a[qid] == 1, rank_b[qid] == 1) for qid in shared_q]
        rows.append(
            {
                "dataset": ds,
                "group": resolve_split_label(ds, grp_map),
                "n": len(shared_q),
                "r1_off": (ea.get("recall_at") or {}).get("1"),
                "r1_on": (eb.get("recall_at") or {}).get("1"),
                "mrr_off": ea.get("mrr"),
                "mrr_on": eb.get("mrr"),
                "n_discordant": sum(1 for a, b in pairs if a != b),  # K1 — p 칸에 "불일치 0" 구분 표시용
                "mcnemar_p": mcnemar_p(pairs) if pairs else None,
                "ci": paired_diff_ci(pairs) if pairs else (None, None),
            }
        )
    return rows


def build_onoff_tables(specs, grp_map):
    """J2 — --onoff 항목(이름·끔폴더·켬폴더·콤보)마다 build_onoff_table을 돌려 이름표가 붙은 표 목록을 만든다."""
    return [
        {
            "name": s["name"],
            "combo": s["combo"],
            "dir_a": Path(s["dir_a"]).name,
            "dir_b": Path(s["dir_b"]).name,
            "rows": build_onoff_table(s["dir_a"], s["dir_b"], s["combo"], grp_map),
        }
        for s in specs
    ]


def pool_overall_confusion(idx_retr_pool, combo, rank_key):
    """decision 요약용 — 한 콤보의 전체 pool 데이터셋을 풀어(question-pooled) 엄격/느슨 오인율."""
    all_rows = []
    for (c, _ds), e in idx_retr_pool.items():
        if c == combo:
            all_rows += e.get("rows") or []
    return rank_confusion_split(all_rows, rank_key)


def pool_v2_best_accuracy(idx_ans_raw_pool, combo="baseline"):
    """decision 요약용 — v2(최신 문서 기준) 데이터셋에서 그 콤보가 가진 k 중 정답률이 가장 높은 k."""
    accs = [
        (k, v.get("accuracy"))
        for (c, ds, k), v in idx_ans_raw_pool.items()
        if c == combo and ds == POOL_V2_DS and v.get("accuracy") is not None
    ]
    if not accs:
        return None, None
    return max(accs, key=lambda x: x[1])


# ───────────────────────── 실패 탐색기(§5) ─────────────────────────
def classify_cause(ans_row):
    """자동 판정(§5) — kw_in_context/correct/empty/retry만으로 가능한 것만. P1~P4·S1·M1·K1은 파싱·모델비교·용어사전 데이터가
    없어 '판정 보류'(요구사항: P1/P2는 파싱 정보 필요하므로 그대로 보류)."""
    if ans_row.get("empty_answer") or ans_row.get("retry"):
        return "G2", "출력 상한(빈 답·잘림)"
    if ans_row.get("kw_in_context") is False:
        return "R1", "검색 실패(근거에 정답 없음)"
    if not ans_row.get("correct"):
        return "G1", "답변 실패(근거엔 있음)"
    return None, None


def build_failure_explorer(idx_retr, flat_ans, combos, grp_map):
    """질문 단위로 조합마다 실패 여부·원인 코드를 모은다 — 답 평가가 있으면 그걸(원인 코드까지), 없으면 검색 hit5만(R1)."""
    rows_by_q = {}  # (ds, id) -> {"question":.., "gold":.., "combos": {combo: {"fail":bool, "cause":code, "label":str, "top3":[...], "answer":str}}}
    qa_cache = {}

    def qa_of(ds):
        if ds not in qa_cache:
            qa_cache[ds] = load_qa_text(ds)
        return qa_cache[ds]

    for combo in combos:
        for ds, _g in grp_map.items():
            ans = flat_ans.get((combo, ds))
            if ans and ans.get("rows"):
                qtext = qa_of(ds)
                for r in ans["rows"]:
                    key = (ds, r["id"])
                    info = rows_by_q.setdefault(
                        key,
                        {
                            "dataset": ds,
                            "id": r["id"],
                            "question": (qtext.get(r["id"]) or {}).get("question"),
                            "gold": (qtext.get(r["id"]) or {}).get("gold_answer"),
                            "combos": {},
                        },
                    )
                    code, label = classify_cause(r)
                    info["combos"][combo] = {
                        "fail": not r.get("correct"),
                        "cause": code,
                        "cause_label": label,
                        "top3": (r.get("evidence") or [])[:3],
                        "answer": (r.get("answer") or "")[:500],
                        "kw_in_context": r.get("kw_in_context"),
                        "source": "answer",
                    }
                continue
            ret = idx_retr.get((combo, ds))
            if ret and ret.get("rows"):
                qtext = qa_of(ds)
                for r in ret["rows"]:
                    key = (ds, r["id"])
                    if key in rows_by_q and combo in rows_by_q[key]["combos"]:
                        continue  # answer 데이터가 이미 이 조합·질문을 채웠으면 그걸 우선
                    info = rows_by_q.setdefault(
                        key,
                        {
                            "dataset": ds,
                            "id": r["id"],
                            "question": (qtext.get(r["id"]) or {}).get("question"),
                            "gold": (qtext.get(r["id"]) or {}).get("gold_answer"),
                            "combos": {},
                        },
                    )
                    fail = not r.get("hit5")
                    info["combos"][combo] = {
                        "fail": fail,
                        "cause": ("R1" if fail else None),
                        "cause_label": (
                            "검색 실패(상위 5 안에 정답 문서 없음 — kw_in_context 데이터 없는 검색 전용 실행)" if fail else None
                        ),
                        "top3": (r.get("top_chunk_ids") or [])[:3],
                        "answer": None,
                        "kw_in_context": None,
                        "source": "retrieval",
                    }

    out = []
    for (_ds, _qid), info in rows_by_q.items():
        fail_combos = [c for c, v in info["combos"].items() if v["fail"]]
        out.append({**info, "n_fail": len(fail_combos), "n_total": len(info["combos"]), "fail_combos": fail_combos})
    out.sort(key=lambda r: (-r["n_fail"], r["dataset"], r["id"]))
    return out


# ───────────────────────── 문서별 최우수(§3 — 검색 성공률 기반 근사, 사실 재현율 아님) ─────────────────────────
def build_doc_tab(eval_set, idx_retr, combos, grp_map):
    gold_cache = {}

    def gold_of(ds):
        if ds not in gold_cache:
            gold_cache[ds] = load_gold_docs(ds)
        return gold_cache[ds]

    docs = eval_set.get("documents") or []
    rows = []
    for d in docs:
        ds, fname = d.get("dataset"), d.get("file")
        gold = gold_of(ds)
        qids = [qid for qid, docs_ in gold.items() if fname in docs_]
        if not qids:
            rows.append({**d, "n_q": 0, "best": None, "ranked": [], "missed": []})
            continue
        scored = []
        for combo in combos:
            ret = idx_retr.get((combo, ds))
            if not ret:
                continue
            by_id = {r["id"]: r for r in (ret.get("rows") or [])}
            hits = [by_id[q]["hit5"] for q in qids if q in by_id]
            if not hits:
                continue
            rate = sum(hits) / len(hits)
            missed = [q for q in qids if q in by_id and not by_id[q]["hit5"]]
            scored.append({"combo": combo, "rate": rate, "n": len(hits), "ms": ret.get("mean_ms"), "missed": missed})
        scored.sort(key=lambda r: (r["rate"], -(r["ms"] or 0)), reverse=True)
        best = scored[0] if scored else None
        rows.append({**d, "n_q": len(qids), "best": best, "ranked": scored[:3], "missed": best["missed"] if best else []})
    return rows


# ───────────────────────── 파싱 세트(§4) ─────────────────────────
def build_parsing_tab(doc_stats, parity, eval_set):
    by_format_engine = {}
    for r in doc_stats:
        fmt = r.get("format") or "?"
        eng = r.get("engine") or "?"
        key = (fmt, eng)
        acc = r.get("fact_hits_proxy")
        slot = by_format_engine.setdefault(key, {"acc": [], "ms": [], "n": 0, "mnv_docs": 0, "mnv_total": 0})
        slot["n"] += 1
        if acc is not None:
            slot["acc"].append(acc)
        ms = (r.get("ms") or {}).get(eng)
        if ms is not None:
            slot["ms"].append(ms)
        mnv = r.get("must_not_violations") or []  # W20 — 금지 값(파싱 단계에서 나오면 안 될 값) 위반 목록
        if mnv:
            slot["mnv_docs"] += 1
            slot["mnv_total"] += len(mnv)
    format_rows = [
        {
            "format": fmt,
            "engine": eng,
            "n": v["n"],
            "acc_proxy": (sum(v["acc"]) / len(v["acc"])) if v["acc"] else None,
            "mean_ms": (sum(v["ms"]) / len(v["ms"])) if v["ms"] else None,
            "mnv_docs": v["mnv_docs"],
            "mnv_total": v["mnv_total"],
        }
        for (fmt, eng), v in sorted(by_format_engine.items())
    ]

    post_rows = []
    for ds, pdata in sorted(parity.items()):
        s = pdata.get("summary") or {}
        post_rows.append(
            {
                "dataset": ds,
                "docs": s.get("docs"),
                "facts": s.get("facts"),
                "none": s.get("none"),
                "all": s.get("all"),
                "figures": s.get("figures"),
                "connection_f1_mean": s.get("connection_f1_mean"),
                "figures_with_gold_edges": s.get("figures_with_gold_edges"),
            }
        )
    return format_rows, post_rows


# ───────────────────────── HTML 빌드 ─────────────────────────
CSS = """
:root{--fg:#1b1f23;--bg:#fff;--muted:#6a737d;--accent:#0969da;--border:#d0d7de;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--chip:#f6f8fa}
*{box-sizing:border-box}
body{font-family:"Malgun Gothic",-apple-system,Segoe UI,sans-serif;margin:0;background:var(--bg);color:var(--fg);font-size:14px;line-height:1.5}
header{padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10}
header h1{font-size:18px;margin:0 0 6px}
header .meta{color:var(--muted);font-size:12px}
nav{display:flex;flex-wrap:wrap;gap:4px;padding:8px 20px;border-bottom:1px solid var(--border);background:var(--chip)}
nav button{padding:6px 12px;border:1px solid var(--border);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}
nav button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
main{padding:16px 20px 60px}
.tab{display:none}
.tab.active{display:block}
h2{font-size:16px;border-bottom:2px solid var(--border);padding-bottom:4px;margin-top:28px}
h3{font-size:14px;margin-top:20px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th,td{border:1px solid var(--border);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--chip);position:sticky;top:0}
.num{text-align:right;font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.tag{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;border:1px solid var(--border)}
.tag.ok{color:var(--ok);border-color:var(--ok)}
.tag.bad{color:var(--bad);border-color:var(--bad)}
.tag.warn{color:var(--warn);border-color:var(--warn)}
.na{color:var(--muted);font-style:italic}
.note{background:var(--chip);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px}
.note.warn{border-color:var(--warn);color:var(--warn)}
details{margin:2px 0}
summary{cursor:pointer}
select{padding:4px 8px}
.row-hidden{display:none}
code{background:var(--chip);padding:0 4px;border-radius:4px}
.small{font-size:12px}
"""

JS = """
function showTab(id){
  document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active')});
  document.querySelectorAll('nav button').forEach(function(b){b.classList.remove('active')});
  document.getElementById(id).classList.add('active');
  document.getElementById('nav-'+id).classList.add('active');
}
function filterFailures(sel){
  var val = sel.value;
  document.querySelectorAll('#failure-table tbody tr').forEach(function(tr){
    var combos = (tr.getAttribute('data-combos')||'').split('|');
    tr.classList.toggle('row-hidden', val !== '__all__' && combos.indexOf(val) === -1);
  });
}
"""


def tag(ok_bool, ok_text, bad_text):
    cls = "ok" if ok_bool else "bad"
    return f'<span class="tag {cls}">{esc(ok_text if ok_bool else bad_text)}</span>'


def saturation_provisional(sat, distractor_rows):
    """H3/I3 — 세트 과반이 포화면 1위는 잠정. 방해 문서 실행이 있다는 사실만으로는 꼬리표를 빼지 않는다 —
    적어도 한 세트의 포화가 실제로 '해소'(relief=='해소')됐을 때만 뗀다."""
    if not sat:
        return False
    majority_saturated = sum(1 for v in sat.values() if v["saturated"]) * 2 > len(sat)
    relieved = bool(distractor_rows) and any(r.get("relief") == "해소" for r in distractor_rows)
    return majority_saturated and not relieved


def build_html(ctx):
    parts = []
    parts.append(
        f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>스택 조합 비교 보고서</title><style>{CSS}</style></head><body>"
    )
    parts.append(header_block(ctx))
    parts.append(data_quality_banner(ctx))  # 항상 눈에 띄는 맨 위(어느 탭이든 바로 보임)
    parts.append(nav_block())
    parts.append("<main>")
    parts.append(tab_decision(ctx))
    parts.append(tab_setup(ctx))
    parts.append(tab_ranking(ctx))
    parts.append(tab_recall_curve(ctx))
    parts.append(tab_answer_k(ctx))
    parts.append(tab_distractors(ctx))
    parts.append(tab_pool(ctx))
    parts.append(tab_onoff(ctx))
    parts.append(tab_docs(ctx))
    parts.append(tab_parsing(ctx))
    parts.append(tab_failures(ctx))
    parts.append(tab_figures(ctx))
    parts.append(tab_cause(ctx))
    parts.append(tab_appendix(ctx))
    parts.append("</main>")
    parts.append(f"<script>{JS}</script>")
    parts.append("</body></html>")
    return "\n".join(parts)


TABS = [
    ("decision", "0. 결정 요약"),
    ("setup", "1. 실험 설정·재현"),
    ("ranking", "2. 조합 순위"),
    ("recall", "2-1. Recall 곡선"),
    ("answerk", "2-2. Answer-k"),
    ("distractors", "2-3. 방해 문서(V11)"),
    ("pool", "2-4. 합친 색인(pool)"),
    ("onoff", "2-5. 개선 켬/끔"),
    ("docs", "3. 문서별 최우수"),
    ("parsing", "4. 파싱 세트"),
    ("failures", "5. 실패 사례"),
    ("figures", "6. 그림 산출물"),
    ("cause", "7. 원인 판정·개선"),
    ("appendix", "부록"),
]


def nav_block():
    """G6 — 실제 탭(버튼+JS로 전환). 첫 탭은 JS 로드 전에도 보이게 서버에서 바로 active를 찍어 둔다
    (DOMContentLoaded에만 맡기면 JS가 늦게 붙거나 막힌 뷰어에서 전부 안 보일 수 있음)."""
    btns = "".join(
        f'<button id="nav-{tid}" class="{"active" if i == 0 else ""}" onclick="showTab(\'{tid}\')">{esc(label)}</button>'
        for i, (tid, label) in enumerate(TABS)
    )
    return f"<nav>{btns}</nav>"


def header_block(ctx):
    meta = ctx["run_meta"][0] if ctx["run_meta"] else {}
    stale_n = sum(1 for u in ctx["layers_used"] if u.get("stale"))
    ans_names = ctx["answers_run_names"]
    ans_label = (" + 답:" + ",".join(esc(n) for n in ans_names)) if ans_names else ""
    scope = ctx["question_scope"]
    invalid_html = ""
    if ctx["invalid_run_notes"]:
        invalid_html = "".join(
            f"<div class='meta'><span class='tag bad'>무효 실행</span> {esc(n['run'])} — {esc(n['reason'])}</div>"
            for n in ctx["invalid_run_notes"]
        )
    return (
        f"<header><h1>스택 조합 비교 보고서 — {esc(ctx['run_name'])}{ans_label}</h1>"
        f"<div class='meta'>평가 문항 범위: {scope['total']}문항({len(scope['datasets'])}세트: {', '.join(esc(d) for d in scope['datasets'])}) · "
        f"git {esc(meta.get('git_commit'))} · eval_set 커밋 {esc(ctx['eval_set_commit'])} · 임베딩 {esc(meta.get('embed_model'))} · "
        f"층 재사용 {len(ctx['layers_used'])}개(낡음 {stale_n}개) · 생성 {esc(ctx['generated_at'])}</div>{invalid_html}</header>"
    )


def data_quality_banner(ctx):
    """보고서 맨 위 — gold_doc_coverage<1 또는 valid=false인 세트를 바로 보여준다(탭 속에 숨기지 않음)."""
    rows = ctx["data_quality_warnings"]
    if not rows:
        return ""
    items = []
    for w in rows:
        missing = w["missing"]
        preview = ", ".join(esc(m) for m in missing[:8]) + (f" 외 {len(missing) - 8}건" if len(missing) > 8 else "")
        note_html = f" — {esc(w['note'])}" if w["note"] else ""
        items.append(
            f"<li><code>{esc(w['dataset'])}</code> 정답 문서 포함률 {fmt_abs(w['coverage'])}{note_html}"
            + (f"<br><span class='small muted'>누락 문서({len(missing)}): {preview}</span>" if missing else "")
            + "</li>"
        )
    return (
        f"<div class='note warn' style='margin:0 20px 0'><b>데이터 품질 경고</b> — 아래 {len(rows)}개 세트는 정답 근거 문서 포함률"
        f"<100% 또는 무효 처리됨(결과 해석 시 주의):<ul>{''.join(items)}</ul></div>"
    )


def tab_decision(ctx):
    rk = ctx["ranking"]
    out = ["<section id='decision' class='tab active'>", "<h2>0. 결정 요약</h2>"]  # G6 — 첫 탭은 서버에서부터 보이게
    if ctx["operating_k"] is not None and rk["metric"] == "answer_accuracy":
        out.append(
            f"<p class='note'><b>운영 k={ctx['operating_k']} 기준</b> — baseline 조합의 holdout 정답률이 "
            f"k={', '.join(map(str, ctx['ks']))} 중 가장 높은 k를 이 결정 요약의 근거로 쓴다(2. 조합 순위 탭에 k별 표 전체).</p>"
        )
    if not rk["kept"]:
        out.append("<p class='note warn'>미실행 — 순위를 계산할 조합·데이터가 없음(results.json이 빈 실행).</p>")
    else:
        top = rk["kept"][0]
        metric_label = {"answer_accuracy": "정답률(holdout)", "pool_r1": "pool R@1(holdout)"}.get(rk["metric"], "R@5(holdout, 검색 전용)")
        sat = ctx["saturation"]
        provisional = saturation_provisional(sat, ctx["distractor_rows"])  # H3/I3
        # J3 — 답변(A층) 데이터가 아예 없어 대체된 경우(pool_r1/retrieval_r5)는 사유를 '방해 문서 재평가 전'이 아니라
        # 실제 원인(크레딧 소진으로 미측정·세트별 포화)으로 적는다. 답변이 있는데 세트가 포화된 경우만 기존 문구 유지.
        ptag_reason = "답변 미측정(크레딧)·세트별 포화" if rk["metric"] != "answer_accuracy" else "방해 문서 재평가 전"
        ptag = f" <span class='tag warn'>잠정({esc(ptag_reason)})</span>" if provisional else ""
        tie_tag = ""
        if top.get("tie"):
            tied_txt = ", ".join(esc(c) for c in top.get("tied_combos") or [])
            tie_tag = f" <span class='tag warn' title=\"동률: {tied_txt}\">동률</span>"
        out.append(
            f"<p><b>1위:</b> <code>{esc(top['combo'])}</code>({esc(human_label(top['combo']))}) — "
            f"{esc(metric_label)} {fmt_abs(top['holdout'])}(n={top['n_holdout']}){tie_tag}{ptag}</p>"
        )
        if top.get("tie"):
            out.append(
                "<p class='muted small'><b>동률 규칙:</b> holdout 비율·n이 정확히 같으면 더 단순한 조합(baseline 우선)을 "
                f"1위로 한다 — 동률: <code>{esc(top['combo'])}</code> = "
                + ", ".join(f"<code>{esc(c)}</code>" for c in top.get("tied_combos") or [])
                + ".</p>"
            )
        if rk["metric"] == "answer_accuracy":  # H2 — 채점 규칙 한 줄(W19)
            out.append(
                "<p class='muted small'><b>정답률 채점 규칙:</b> 정답 키워드(동의어 허용)가 모두 있고 <b>금지어(forbid_keywords)가 하나도 없고</b>, "
                "기대 첨부(expected_attachments)가 있는 문항은 근거 그림의 image_id가 맞아야 정답(src/tools/data/_synth_images_qa.py score). "
                "synth-4clients는 정답 문자열 포함(공백 무시)·표/부정 문항 제외.</p>"
            )
        if rk["reason"]:
            lead = "순위 기준이 pool R@1(합친 색인)로 대체됨" if rk["metric"] == "pool_r1" else "순위 기준이 검색 전용(R@5)으로 대체됨"
            out.append(f"<p class='note warn'>{esc(lead)} — {esc(rk['reason'])}</p>")
        # G2 — post축(후보정)은 검색(R@5) 지표로는 문서 적중이 포화돼 효과를 못 재므로 '동급' 서술에서 제외(표에는 그대로 남김).
        equiv = [r for r in rk["kept"] if r["equivalent_to_top"] and r["combo"] != top["combo"] and not r["is_post"]]
        if equiv:
            out.append(
                "<p><b>1위와 통계적으로 구분 안 되는 동급 묶음</b>(McNemar p≥0.05 이고 차 95% CI가 0 포함): "
                + ", ".join(f"<code>{esc(r['combo'])}</code>" for r in equiv)
                + "</p>"
            )
        post_rows = [r for r in rk["kept"] if r["is_post"]]
        if post_rows and rk["metric"] == "retrieval_r5":
            out.append(
                "<p class='note warn'>"
                + ", ".join(f"<code>{esc(r['combo'])}</code>" for r in post_rows)
                + " — 검색 지표로 측정 불가(문서 적중 포화) — 사실 재현율·답 정확도로 판단(4. 파싱 세트, G2).</p>"
            )
        runners = [r for r in rk["kept"][1:3] if r["holdout"] is not None]  # J1 — pool_r1에서 데이터 없는(n/a) 콤보는 "차순위"로 안 보임
        if runners:
            out.append(
                "<p><b>차순위 2·3위:</b> "
                + ", ".join(f"<code>{esc(r['combo'])}</code>({fmt_abs(r['holdout'])}, n={r['n_holdout']})" for r in runners)
                + "</p>"
            )
        out.append(
            "<p class='note'>후보(2~3개) 확정 선정은 조합·층별 튜닝 현황이 '충분'으로 확인된 뒤에 — "
            "이 데이터만으로는 튜닝 현황을 판정할 필드가 없어(§9-1) 통계적 순위만 제시하고 최종 채택은 보류한다.</p>"
        )
        dr = ctx["discrim_ranking"]
        if dr["kept"] and dr["kept"][0]["combo"] != top["combo"]:
            out.append(
                f"<p class='note'>변별력 있는 세트만(2-1 참조)으로 다시 매기면 1위가 <code>{esc(dr['kept'][0]['combo'])}</code>로 바뀜 — "
                "포화 세트가 전체 순위를 끌고 있었을 수 있음(G3).</p>"
            )
    pd = ctx.get("pool_data")
    if pd:
        s = pd["summary"]
        if s["v2_accuracy"] is not None:
            v2_txt = f"{fmt_abs(s['v2_accuracy'])}(k={s['v2_k']})"
        elif ctx.get("answers_missing_reason"):  # J4 — 다른 n/a 사유와 구분되는 전용 문구
            v2_txt = f"n/a(미측정: {ctx['answers_missing_reason']})"
        else:
            v2_txt = "n/a"
        out.append(
            f"<p class='note'><b>pool(2-4 탭):</b> 여러 세트를 합친 색인(baseline)에서 구판 오인(엄격, 구판이 모든 정답보다 "
            f"위) {fmt_rate_n(s['oldver_strict'], s['n_oldver'])} — top10 안에 낀 것까지 포함한 느슨 기준은 {fmt_abs(s['oldver_loose'])}로 "
            f'훨씬 높아 느슨 기준만 보면 변별이 안 됨 · synth-distractors-v2 "최신 문서 기준" 질문 정답률 {esc(v2_txt)}.</p>'
        )
    out.append("<h3>남은 위험</h3><ul>")
    risks = []
    if ctx["invalid_run_notes"]:
        risks.append(
            "답 실행 중 하네스 결함으로 무효 처리된 것이 있음 — " + ", ".join(n["run"] for n in ctx["invalid_run_notes"]) + "(재실행 대기)"
        )
    if not ctx["answers_run_names"] or not ctx.get("flat_ans"):
        risks.append("답(A층) 정답률 데이터가 없거나 미완료 — 검색만으로 순위를 매김(답변 품질 차는 못 봄)")
    sat = ctx["saturation"]
    sat_n = sum(1 for v in sat.values() if v["saturated"])
    if sat_n:
        # K4 — pool_r1로 순위를 매길 때는 "방해 문서로 재평가"가 아니라 이미 쓰고 있는 대체 기준(pool R@1)을 알린다.
        tail = (
            "세트별 색인 R@5는 포화(참고용) — 순위는 pool R@1"
            if rk["metric"] == "pool_r1"
            else "그 세트는 조합 간 차이를 근거로 못 씀(방해 문서 세트 §9-3로 재평가 필요)"
        )
        risks.append(f"{sat_n}/{len(sat)}개 세트가 포화(F6) — {tail}")
    stale_n = sum(1 for u in ctx["layers_used"] if u.get("stale"))
    if stale_n:
        risks.append(f"낡은 저장본 {stale_n}개를 사용한 실행 포함 — 재현 전 다시 빌드 권장")
    if not risks:
        risks.append("데이터로 식별된 위험 없음(그렇다고 없는 건 아님 — 튜닝 현황·그림 산출물 등 미실행 항목은 부록 참고)")
    for r in risks[:3]:
        out.append(f"<li>{esc(r)}</li>")
    out.append("</ul></section>")
    return "\n".join(out)


def tab_setup(ctx):
    out = ["<section id='setup' class='tab'>", "<h2>1. 실험 설정·재현</h2>"]
    ans_txt = ", ".join(esc(n) for n in ctx["answers_run_names"]) if ctx["answers_run_names"] else "미지정"
    out.append(f"<p>검색 실행: <code>{esc(ctx['run_name'])}</code> · 답 실행: {ans_txt}</p>")
    scope = ctx["question_scope"]
    out.append(
        f"<p>평가 문항 범위(이 실행에 실제로 있는 데이터셋 기준): <b>{scope['total']}문항</b>"
        f"({len(scope['datasets'])}세트 — {', '.join(esc(d) for d in scope['datasets'])}) · "
        f"eval_set.json 커밋: <code>{esc(ctx['eval_set_commit'])}</code></p>"
    )
    miss = ctx["missing_eval_datasets"]  # I5
    out.append(
        f"<p class='{'note warn' if miss else 'muted small'}'>eval_set.json에 있지만 이 실행에 없는 세트(미포함): "
        + (", ".join(esc(d) for d in miss) if miss else "없음")
        + "</p>"
    )
    if ctx.get("tuned_holdout"):  # J5 — 결과를 보고 세트를 고친 경우 holdout 해석에 주의하라는 표시(L4-5 결정 후 지워도 됨)
        txt = "·".join(f"{ds}({ticket})" if ticket else ds for ds, ticket in ctx["tuned_holdout"])
        out.append(f"<p class='note warn'>결과를 보고 고친 세트: {esc(txt)} — holdout 해석 주의</p>")
    if ctx["invalid_run_notes"]:
        out.append(
            "<table><tr><th>무효 처리된 실행</th><th>사유</th></tr>"
            + "".join(f"<tr><td><code>{esc(n['run'])}</code></td><td>{esc(n['reason'])}</td></tr>" for n in ctx["invalid_run_notes"])
            + "</table><p class='muted small'>--invalid-runs로 지정 — 이 실행에서 나온 데이터는 순위·축별 기여 계산에서 빠지고 "
            "답 실행 전체가 다른 유효한 실행으로 대체될 때까지 참고용으로만 표시된다.</p>"
        )
    meta = ctx["run_meta"]
    if meta:
        out.append("<h3>층 열쇠·코드 지문·모델(조합·데이터셋별, 앞 5개만 표시)</h3>")
        out.append(
            "<table><tr><th>콤보</th><th>데이터셋</th><th>split</th><th>git</th><th>임베딩</th><th>재랭크</th><th>데이터셋 지문</th></tr>"
        )
        for m in meta[:5]:
            out.append(
                f"<tr><td>{esc(m['combo'])}</td><td>{esc(m['dataset'])}</td><td>{esc(m['split'])}</td>"
                f"<td>{esc(m['git_commit'])}</td><td>{esc(m['embed_model'])}</td><td>{esc(m['rerank_model'])}</td>"
                f"<td>{esc(m['dataset_fingerprint'])}</td></tr>"
            )
        out.append(f"</table><p class='muted small'>전체 {len(meta)}행(조합×데이터셋) 중 5행만 표시.</p>")
    else:
        out.append("<p class='note warn'>미실행 — run_meta.json 없음.</p>")

    stale = [u for u in ctx["layers_used"] if u.get("stale")]
    out.append(
        f"<h3>층 재사용</h3><p>총 {len(ctx['layers_used'])}개 층 사용"
        + (f" · <span class='tag bad'>낡은 저장본 {len(stale)}개</span>" if stale else " · 낡은 저장본 없음")
        + "</p>"
    )
    if stale:
        out.append("<ul>" + "".join(f"<li class='small'>{esc(u['dir'])}</li>" for u in stale[:10]) + "</ul>")

    out.append("<h3>이 실행 폴더가 가진 데이터셋 · split</h3><table><tr><th>데이터셋</th><th>split</th></tr>")
    for ds, g in sorted(ctx["grp_map"].items()):
        out.append(f"<tr><td>{esc(ds)}</td><td>{esc(g)}</td></tr>")
    out.append("</table>")

    out.append("<h3>output/eval/stack_matrix 실행 폴더 현황(F8)</h3><table><tr><th>폴더</th><th>상태</th></tr>")
    for s in ctx["sibling_runs"]:
        cls = "ok" if s["status"] == "있음" else "bad"
        out.append(f"<tr><td>{esc(s['name'])}</td><td><span class='tag {cls}'>{esc(s['status'])}</span></td></tr>")
    out.append("</table>")

    bref = ctx["baseline_ref"]
    out.append("<h3>기준선(다른 세션, 191문항 7세트 기준 — 운영 밖 비교용)</h3>")
    if bref:
        for name, cfg in bref.get("configs", {}).items():
            out.append(f"<p><code>{esc(name)}</code>: 정답 {esc(cfg.get('correct'))} · 근거 적중 {fmt_abs(cfg.get('evidence_hit'))}</p>")
        out.append(
            "<p class='muted small'>이 보고서의 평가 문항 범위가 191문항(7세트)과 다르면(예: synth-confuse 추가 후) "
            "이 기준선과 직접 비교하지 말 것 — 위 '평가 문항 범위'를 먼저 확인.</p>"
        )
    else:
        out.append("<p class='note warn'>미실행 — 기준선 파일을 찾을 수 없음.</p>")
    out.append("</section>")
    return "\n".join(out)


def fmt_rate_n(rate, n):
    """G4 — 비율 옆에 항상 n을 보인다."""
    return f"{fmt_abs(rate)} (n={n})"


def render_ranking_table(kept, metric):
    rows = [
        "<table><tr><th>순위</th><th>콤보</th><th>사람말 라벨</th><th class='num'>holdout(n)</th>"
        "<th class='num'>dev(n)</th><th class='num'>1위 대비 McNemar p</th><th>1위 대비 차(1위−후보) 95% CI</th>"
        "<th class='num'>지연ms(dev, p50)</th><th>1위와 동급</th></tr>"
    ]
    for r in kept:
        inv_ci = None if not r["ci_vs_top"] or r["ci_vs_top"][0] is None else (-r["ci_vs_top"][1], -r["ci_vs_top"][0])
        equiv_cell = "예" if r["equivalent_to_top"] else ""
        if metric == "retrieval_r5" and r["is_post"]:
            equiv_cell = "<span class='tag warn'>측정불가(G2)</span>"
        # I2 — 1위가 동률이면 '동률' 표시 + 같이 동률인 조합 이름(제목으로).
        tie_cell = ""
        if r.get("tie") and r["rank"] == 1:
            tied_txt = ", ".join(esc(c) for c in r.get("tied_combos") or [])
            tie_cell = f" <span class='tag warn' title=\"동률: {tied_txt}\">동률</span>"
        rows.append(
            f"<tr><td class='num'>{r['rank']}{tie_cell}</td><td><code>{esc(r['combo'])}</code></td><td>{esc(human_label(r['combo']))}</td>"
            f"<td class='num'>{fmt_rate_n(r['holdout'], r['n_holdout'])}</td><td class='num'>{fmt_rate_n(r['dev'], r['n_dev'])}</td>"
            f"<td class='num'>{fmt_p(r['mcnemar_p_vs_top'])}</td><td>{fmt_ci(inv_ci)}</td>"
            f"<td class='num'>{fmt_ms(r['latency_ms'])}</td><td>{equiv_cell}</td></tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def tab_ranking(ctx):
    rk = ctx["ranking"]
    out = ["<section id='ranking' class='tab'>", "<h2>2. 조합 순위</h2>"]
    out.append(
        "<p class='muted small'><b>정의:</b> holdout/dev 비율 = 유효한(정답 문서 포함률≥95%) 데이터셋에 속한 문항을 전부 "
        "풀어(question-pooled) 적중수/문항수로 계산 — 세트별 비율의 평균이 아니다(세트마다 문항 수가 달라 평균은 편향됨, G1). "
        "McNemar p≥0.05 & 차 95% CI가 0 포함이면 '1위와 통계적으로 구분 안 됨'(동급) → Top3은 그대로 보이고, 동급이 "
        "이어지면 Top10까지 확장. <b>동률 규칙(I2):</b> holdout 비율·n이 정확히 같으면 더 단순한 조합(baseline 우선)을 "
        "1위로 하고 '동률' 표시를 남긴다. 지연은 p50(중앙값, G5).</p>"
    )
    if ctx["ks"]:
        out.append(
            f"<p><b>k별 순위</b> — answer 실행에 있는 k마다 따로 매긴다(동률 판정도 k별로 독립). "
            f"<b>운영 k={esc(ctx['operating_k'])}</b>(baseline holdout 정답률 최고) 표를 결정 요약(0번 탭)의 근거로 쓴다.</p>"
        )
        for k in ctx["ks"]:
            rbk = ctx["ranking_by_k"][k]
            is_op = k == ctx["operating_k"]
            out.append(
                f"<details {'open' if is_op else ''}><summary><b>k={k}</b>"
                f"{' — 운영 k' if is_op else ''} · 기준: "
                f"{esc('정답률(holdout 답변)' if rbk['metric'] == 'answer_accuracy' else 'R@5(검색 전용)')}</summary>"
            )
            if rbk["reason"]:
                out.append(f"<p class='note warn'>{esc(rbk['reason'])}</p>")
            out.append(render_ranking_table(rbk["kept"], rbk["metric"]) if rbk["kept"] else "<p class='na'>미실행 — 조합 데이터 없음.</p>")
            out.append("</details>")
    else:
        metric_label = {"pool_r1": "pool R@1(holdout, 합친 색인 — J1)"}.get(rk["metric"], "R@5(holdout, 검색 전용 — 정답률 데이터 부족)")
        out.append(f"<p><b>1차 기준:</b> {esc(metric_label)}(answer 실행 없음, k별 비교 불가).</p>")
        if rk["reason"]:
            out.append(f"<p class='note warn'>{esc(rk['reason'])}</p>")
        out.append(render_ranking_table(rk["kept"], rk["metric"]) if rk["kept"] else "<p class='na'>미실행 — 조합 데이터 없음.</p>")
        ref = ctx.get("ranking_r5_ref")  # J1 — pool 기준으로 대체됐을 때만 별도 색인 R@5를 '참고용'으로 같이 보인다.
        if rk["metric"] == "pool_r1" and ref:
            out.append("<h3>참고: 별도 색인 R@5 순위(결정에는 안 씀 — 세트 13/14 포화라 변별력 낮음, J1)</h3>")
            out.append(render_ranking_table(ref["kept"], ref["metric"]) if ref["kept"] else "<p class='na'>미실행.</p>")
    out.append(
        "<p class='muted small'>표에서 비는 열(다문서 정답률·그림 필요/불필요·문서당 VLM 호출·비용·튜닝 현황)은 "
        "results.json/answers.json에 해당 필드가 없어 계산 불가 — §8에 필요한 필드로 남김.</p>"
    )

    dr = ctx["discrim_ranking"]
    out.append("<h2>2-1. 변별력 있는 세트만의 순위(G3 — 조합의 80% 이상이 R@5=1.0인 세트 제외)</h2>")
    out.append(
        f"<p class='muted small'><b>정의:</b> 위 순위와 같은 방식(question-pooled)이지만 포함 세트를 "
        f"{', '.join(esc(d) for d in dr['included_datasets'])}로 제한한다. "
        f"제외된 세트({len(dr['excluded_datasets'])}개): {', '.join(esc(d) for d in dr['excluded_datasets']) or '없음'}.</p>"
    )
    if dr["reason"]:
        out.append(f"<p class='note warn'>{esc(dr['reason'])}</p>")
    if dr["kept"]:
        out.append(render_ranking_table(dr["kept"], dr["metric"]))
    else:
        out.append("<p class='na'>미실행 — 변별력 있는 세트가 없음(전부 포화 또는 데이터 없음).</p>")

    out.append("<h2>2-2. 세트별 변별력(F6/I1 — 포화 점검, 위 2-1과 다른 기준)</h2>")
    out.append(
        "<p class='muted small'><b>정의(I1):</b> 이 표의 '포화'는 <b>결정에 쓰는 지표</b>(순위가 정답률이면 세트별 운영 k "
        "정답률, 검색 전용 순위면 R@5)의 최고-최저 차<0.02 또는 최고값≥0.95다(F6, 요약용 — 2-1 랭킹에 쓰는 "
        "'조합의 80% 이상이 1.0'(G3) 기준과는 다르다). R@1·MRR 범위는 참고용(9-1 — R@5가 포화돼도 R@1·MRR엔 변별력이 "
        "남을 수 있음).</p>"
    )
    out.append(
        "<table><tr><th>데이터셋</th><th>판정 지표</th><th class='num'>최저</th>"
        "<th class='num'>최고</th><th class='num'>차</th><th>판정</th>"
        "<th class='num'>R@1 범위</th><th class='num'>MRR 범위</th></tr>"
    )
    for ds, v in sorted(ctx["saturation"].items()):
        verdict = tag(not v["saturated"], "변별력 있음", "변별력 없음(포화)")
        metric_label = "정답률(운영 k)" if v["metric"] == "answer_accuracy" else "R@5"
        r1_range = f"{fmt_abs(v['r1_min'])}~{fmt_abs(v['r1_max'])}" if v["r1_min"] is not None else "n/a"
        mrr_range = f"{fmt_abs(v['mrr_min'])}~{fmt_abs(v['mrr_max'])}" if v["mrr_min"] is not None else "n/a"
        out.append(
            f"<tr><td>{esc(ds)}{dataset_tag(ds)}</td><td>{esc(metric_label)}</td><td class='num'>{fmt_abs(v['min'])}</td>"
            f"<td class='num'>{fmt_abs(v['max'])}</td><td class='num'>{fmt_abs(v['spread'])}</td><td>{verdict}</td>"
            f"<td class='num'>{esc(r1_range)}</td><td class='num'>{esc(mrr_range)}</td></tr>"
        )
    out.append("</table>")

    out.append("<h2>축별 기여(기준 대비 하나씩 바꾼 차 — R@5, dev/holdout)</h2>")
    out.append(
        "<p class='muted small'><b>정의:</b> dev/holdout 델타는 question-pooled R@5(위 랭킹과 같은 방식, 무효 세트 제외)의 "
        "후보−기준 차(음수 = 후보가 기준보다 낮음). CI 열은 <b>기준 대비 차(후보−기준)</b>의 95% 부트스트랩 구간이다(F4 — 후보 자체 적중률 구간이 아님). "
        "같은 줄의 McNemar p와 같은 짝 비교에서 나온 값. 지연은 p50(G5).</p>"
    )
    out.append(
        "<table><tr><th>축</th><th>콤보</th><th>사람말 라벨</th><th class='num'>dev 델타(n)</th><th class='num'>holdout 델타(n)</th>"
        "<th class='num'>McNemar p</th><th>기준 대비 차(후보−기준) 95% CI</th><th class='num'>후보 지연ms(p50)</th>"
        "<th class='num'>기준 지연ms(p50)</th><th>비고</th></tr>"
    )
    for row in ctx["axis_rows"]:
        note = "검색 지표로 측정 불가 — 사실 재현율·답 정확도로 판단(G2)" if row["is_post"] else ""
        out.append(
            f"<tr><td>{esc(AXIS_LABEL.get(row['axis'], row['axis']))}</td><td><code>{esc(row['combo'])}</code></td>"
            f"<td>{esc(human_label(row['combo']))}</td><td class='num'>{fmt_delta(row['dev_delta'])}(n={row['n_dev']})</td>"
            f"<td class='num'>{fmt_delta(row['holdout_delta'])}(n={row['n_holdout']})</td><td class='num'>{fmt_p(row['mcnemar_p'])}</td>"
            f"<td>{fmt_ci(row['ci'])}</td><td class='num'>{fmt_ms(row['cand_ms'])}</td><td class='num'>{fmt_ms(row['base_ms'])}</td>"
            f"<td class='small'>{esc(note)}</td></tr>"
        )
    out.append("</table></section>")
    return "\n".join(out)


def tab_recall_curve(ctx):
    out = ["<section id='recall' class='tab'>", "<h2>2-1. Recall 곡선(R@k, k=1..50)</h2>"]
    curve, any_data = ctx["recall_curve"]
    if not any_data:
        out.append(
            f"<p class='note warn'>미실행 — 실행 <code>{esc(ctx['run_name'])}</code>에는 recall_at 있는 조합·세트가 없음"
            "(이전 형식은 R@5·R@10만 기록). recall_at이 있는 새 실행(예: recall-20261003c 완료 후)으로 다시 돌리면 채워짐.</p>"
        )
        out.append("</section>")
        return "\n".join(out)
    out.append(
        "<p class='muted small'><b>정의:</b> 세트 안 모든 문항의 gold_rank(정답 문서가 처음 나온 순위)를 풀어(question-pooled) "
        "적중수/문항수로 R@k를 계산 — 세트별 R@k의 평균이 아니다. 무효 세트는 제외.</p>"
    )
    out.append(
        "<table><tr><th>콤보</th><th>split</th><th class='num'>n</th>" + "".join(f"<th class='num'>R@{k}</th>" for k in RECALL_KS) + "</tr>"
    )
    for combo, groups in curve.items():
        for g in ("dev", "holdout"):
            gdata = groups.get(g) or {}
            if not gdata.get("n"):
                continue
            out.append(
                f"<tr><td><code>{esc(combo)}</code></td><td>{esc(g)}</td><td class='num'>{gdata['n']}</td>"
                + "".join(f"<td class='num'>{fmt_abs(gdata['rate'].get(k))}</td>" for k in RECALL_KS)
                + "</tr>"
            )
    out.append("</table></section>")
    return "\n".join(out)


def tab_answer_k(ctx):
    out = ["<section id='answerk' class='tab'>", "<h2>2-2. Answer-k(근거 수 k별 정답률)</h2>"]
    combos, ks, table = ctx["answer_k"]
    if not combos:
        out.append("<p class='note warn'>미실행 — 답 실행이 지정되지 않았거나 answers.json이 비어 있음.</p>")
        out.append("</section>")
        return "\n".join(out)
    out.append(
        "<p class='muted small'><b>정의:</b> dev/holdout 정답률 = question-pooled(세트 평균 아님, G1), 무효 세트·무효 처리된 "
        "실행(--invalid-runs) 제외.</p>"
    )
    wanted = [5, 10, 20]
    present = [k for k in wanted if k in ks] + [k for k in ks if k not in wanted]
    out.append(
        "<table><tr><th>콤보</th>"
        + "".join(f"<th class='num'>k={k} dev(n)</th><th class='num'>k={k} holdout(n)</th>" for k in present)
        + "</tr>"
    )
    for c in combos:
        cells = []
        for k in present:
            v = table[c].get(k, {})
            dev_rate, dev_n = v.get("dev", (None, 0))
            hold_rate, hold_n = v.get("holdout", (None, 0))
            cells.append(f"<td class='num'>{fmt_rate_n(dev_rate, dev_n)}</td><td class='num'>{fmt_rate_n(hold_rate, hold_n)}</td>")
        out.append(f"<tr><td><code>{esc(c)}</code></td>" + "".join(cells) + "</tr>")
    out.append("</table>")
    missing_ks = [k for k in wanted if k not in ks]
    if missing_ks:
        out.append(
            f"<p class='note warn'>미실행 — k={', '.join(map(str, missing_ks))}는 아직 answer 실행에 없음(요구 k 후보 5/10/20 중 일부만 돎).</p>"
        )

    out.append(f"<h3>W20 — ref_hit·attach_hit 적중률(운영 k={esc(ctx['operating_k'])})</h3>")
    out.append(
        "<p class='muted small'>ref_hit=참조 문서(문서 번호 등) 질문이 그 문서를 맞혔는지, attach_hit=첨부(이미지 등) 질문이 "
        "올바른 첨부를 가리켰는지 — 둘 다 해당 유형 질문이 있는 세트에서만 값이 있다(question-pooled, G1).</p>"
    )
    if not ctx["ref_attach"]:
        out.append("<p class='note warn'>미실행 — ref_hit·attach_hit 값이 있는 (조합,세트)가 없음.</p>")
    else:
        out.append(
            "<table><tr><th>콤보</th><th>데이터셋</th><th>split</th><th class='num'>ref_hit(n)</th><th class='num'>attach_hit(n)</th></tr>"
        )
        for r in ctx["ref_attach"]:
            out.append(
                f"<tr><td><code>{esc(r['combo'])}</code></td><td>{esc(r['dataset'])}</td><td>{esc(r['group'])}</td>"
                f"<td class='num'>{fmt_rate_n(r['ref_rate'], r['ref_n']) if r['ref_n'] else 'n/a'}</td>"
                f"<td class='num'>{fmt_rate_n(r['attach_rate'], r['attach_n']) if r['attach_n'] else 'n/a'}</td></tr>"
            )
        out.append("</table>")
    out.append("</section>")
    return "\n".join(out)


def tab_distractors(ctx):
    out = ["<section id='distractors' class='tab'>", "<h2>2-3. 방해 문서(V11) — 평문 vs 방해 문서</h2>"]
    names = ctx["distractor_run_names"]
    if not names["retrieval"]:
        out.append("<p class='note warn'>미실행 — --retrieval-distractors가 지정되지 않음.</p></section>")
        return "\n".join(out)
    ans_txt = ", ".join(esc(n) for n in names["answers"]) if names["answers"] else "미지정"
    out.append(f"<p>방해 문서 검색 실행: <code>{esc(names['retrieval'])}</code> · 방해 문서 답 실행: {ans_txt}</p>")
    out.append(
        "<p class='muted small'><b>정의:</b> 방해 문서 세트는 질문이 <code>unique_under_distractors</code>인 문항만 "
        "채점되게 파이프라인에서 이미 걸러져 있다(여기서는 그 n을 그대로 보임 — 추가 필터 없음). "
        "answer 실행이 k=10 하나만 있으면 평문 쪽 운영 k와 다를 수 있어 표에 k를 같이 적는다. "
        "distractor_confusion_rate=방해 문서가 정답보다 먼저 나오거나 top10에 낀 문항 비율.</p>"
    )
    rows = ctx["distractor_rows"]
    if not rows:
        out.append("<p class='note warn'>미실행 — 데이터셋이 없음.</p></section>")
        return "\n".join(out)
    # I4 — 오인율 0인 세트가 있으면(v1이 변별력을 못 만든 신호) 그 사실을 한 줄로 바로 보인다.
    if any(r["dist"].get("confusion") == 0.0 for r in rows):
        out.append(
            "<p class='note warn'>v1은 변별력을 못 만듦(정답이 하나로 정해지는 문항만 남겨 질문의 ID·고객명으로 쉽게 구분) "
            "— v2(같은 고객 다른 연도·개정판 + 표현 바꾼 질문) 준비 중</p>"
        )
    out.append(
        "<table><tr><th>데이터셋</th><th>split</th><th class='num'>평문 n</th><th class='num'>평문 R@5</th>"
        "<th class='num'>평문 R@1</th><th class='num'>평문 MRR</th><th class='num'>평문 정답률</th>"
        "<th class='num'>방해 n(고유)</th><th class='num'>방해 R@5</th><th class='num'>방해 R@1</th>"
        "<th class='num'>방해 MRR</th><th class='num'>오인율</th><th class='num'>방해 정답률(k)</th>"
        "<th>포화 해소(F6)</th></tr>"
    )
    for r in rows:
        p, d = r["plain"], r["dist"]
        # retrieval_status는 검색 지표(R@5·R@1·MRR·오인율)만 가린다 — 답 정답률은 검색 S가 없어도 답 실행이
        # 따로 있으면 그대로 보인다(실제 loop1d 데이터가 이 모양: 검색 미실행 + 답 실행은 됨).
        if d.get("retrieval_status"):
            retr_cells = f"<td class='na' colspan='4' title=\"{esc(d['retrieval_status'])}\">미실행(검색 S 없음)</td>"
        else:
            retr_cells = (
                f"<td class='num'>{fmt_abs(d['r5'])}</td><td class='num'>{fmt_abs(d['r1'])}</td>"
                f"<td class='num'>{fmt_abs(d['mrr'])}</td><td class='num'>{fmt_abs(d['confusion'])}</td>"
            )
        acc_cell = f"{fmt_abs(d['acc'])}(k={esc(d['k'])})" if d["acc"] is not None else "n/a"
        dist_cells = f"<td class='num'>{d['n'] if d['n'] is not None else 'n/a'}</td>{retr_cells}<td class='num'>{esc(acc_cell)}</td>"
        relief_cell = esc(r["relief"]) if r["relief"] else ("-" if not r["saturated_plain"] else "n/a")
        out.append(
            f"<tr><td>{esc(r['dataset'])}{dataset_tag(r['dataset'])}</td><td>{esc(r['group'])}</td>"
            f"<td class='num'>{p['n'] if p['n'] is not None else 'n/a'}</td><td class='num'>{fmt_abs(p['r5'])}</td>"
            f"<td class='num'>{fmt_abs(p['r1'])}</td><td class='num'>{fmt_abs(p['mrr'])}</td>"
            f"<td class='num'>{fmt_abs(p['acc'])}</td>{dist_cells}<td>{relief_cell}</td></tr>"
        )
    out.append("</table>")
    out.append(
        "<p class='muted small'>포화 해소(F6) — 2. 조합 순위 탭의 세트별 변별력 표에서 포화(변별력 없음)로 판정된 세트에 대해, "
        "방해 문서를 섞었을 때 baseline R@5가 포화 기준(0.95) 아래로 떨어지면 '해소', 그대로면 '유지'. "
        "포화로 판정되지 않은 세트는 '-'(비교 대상 아님).</p>"
    )
    out.append("</section>")
    return "\n".join(out)


def tab_pool(ctx):
    out = ["<section id='pool' class='tab'>", "<h2>2-4. 합친 색인(pool, L3-2)</h2>"]
    pd = ctx["pool_data"]
    if not pd:
        out.append("<p class='note warn'>미실행 — --retrieval-pool이 지정되지 않음.</p></section>")
        return "\n".join(out)
    ans_txt = ", ".join(esc(n) for n in pd["answers_run_names"]) if pd["answers_run_names"] else "미지정"
    out.append(f"<p>pool 검색 실행: <code>{esc(pd['run_name'])}</code> · pool 답 실행: {ans_txt}</p>")
    out.append(
        "<p class='muted small'><b>이 탭이 보여주는 것:</b> 여러 세트를 한 색인에 합치면(합친 색인, 세트별 별도 색인과 달리 "
        "서로의 문서가 방해물이 됨) 세트 내에서는 안 보이던 변별력이 드러나는지 — 그리고 synth-distractors-v2(같은 "
        '문서 계열의 구판·최신판이 섞인 "최신 기준" 질문) 정답률을 본다.</p>'
    )
    out.append(
        "<p class='muted small'><b>정의:</b> R@1/R@5/MRR은 question-pooled(해당 콤보·세트의 pool 행 그대로, 세트 평균 아님). "
        "별도 색인 R@1은 같은 콤보·세트가 일반(비-pool) 검색 실행에 있을 때만(없으면 n/a) — Δ=pool−별도(음수면 합친 색인이 "
        "더 어려움, 변별력이 생겼다는 신호). <b>구판 오인(엄격)</b>=구판(v2) 문서 중 가장 앞 순위가 정답 문서 전부보다 위인 "
        "문항 비율(주 지표) · <b>구판 오인(느슨, 참고)</b>=top10 안에만 끼어도 — 두 값이 크게 벌어지면 느슨 쪽은 단순히 "
        "'후보군이 커서 끼는' 신호일 뿐 실제 혼동과는 다름(L3-2, results.json 저장 필드는 이 둘의 OR라 느슨 쪽에 가깝게 치우침). "
        "방해 문서(v1)도 같은 식.</p>"
    )
    rows = pd["retrieval_rows"]
    if not rows:
        out.append("<p class='note warn'>미실행 — pool 검색 결과가 없음.</p>")
    else:
        out.append(
            "<table><tr><th>콤보</th><th>데이터셋</th><th>split</th><th class='num'>n</th>"
            "<th class='num'>R@1</th><th class='num'>별도색인 R@1</th><th class='num'>Δ(pool−별도)</th>"
            "<th class='num'>R@5</th><th class='num'>MRR</th>"
            "<th class='num'>구판 오인(엄격)</th><th class='num'>구판 오인(느슨,참고)</th>"
            "<th class='num'>방해문서 오인(엄격)</th><th class='num'>방해문서 오인(느슨,참고)</th></tr>"
        )
        for r in rows:
            out.append(
                f"<tr><td><code>{esc(r['combo'])}</code></td><td>{esc(r['dataset'])}{dataset_tag(r['dataset'])}</td>"
                f"<td>{esc(r['group'])}</td><td class='num'>{r['n'] if r['n'] is not None else 'n/a'}</td>"
                f"<td class='num'>{fmt_abs(r['r1'])}</td><td class='num'>{fmt_abs(r['r1_separate'])}</td>"
                f"<td class='num'>{fmt_delta(r['r1_delta'])}</td><td class='num'>{fmt_abs(r['r5'])}</td>"
                f"<td class='num'>{fmt_abs(r['mrr'])}</td>"
                f"<td class='num'>{fmt_rate_n(r['oldver_strict'], r['n_oldver'])}</td>"
                f"<td class='num'>{fmt_abs(r['oldver_loose'])}</td>"
                f"<td class='num'>{fmt_rate_n(r['distractor_strict'], r['n_distractor'])}</td>"
                f"<td class='num'>{fmt_abs(r['distractor_loose'])}</td></tr>"
            )
        out.append("</table>")
    out.append("<h3>pool 답 실행 — 정답률·구판값 유출률(k별)</h3>")
    out.append(
        "<p class='muted small'><b>정의:</b> 정답률=question-pooled 정답 비율. oldver_value_in_answer_rate="
        "구판 문서의 금지어(forbid_keywords)가 LLM 답에 그대로 나온 문항 비율(synth-distractors-v2만 값 있음 — "
        "그 외 데이터셋은 구판 개념이 없어 n/a).</p>"
    )
    ans_rows = pd["answer_rows"]
    if not ans_rows:
        out.append("<p class='note warn'>미실행 — pool 답 결과가 없음.</p>")
    else:
        out.append(
            "<table><tr><th>콤보</th><th>데이터셋</th><th class='num'>k</th><th class='num'>n</th>"
            "<th class='num'>정답률</th><th class='num'>구판값 유출률</th></tr>"
        )
        for r in ans_rows:
            out.append(
                f"<tr><td><code>{esc(r['combo'])}</code></td><td>{esc(r['dataset'])}{dataset_tag(r['dataset'])}</td>"
                f"<td class='num'>{esc(r['k'])}</td><td class='num'>{r['n'] if r['n'] is not None else 'n/a'}</td>"
                f"<td class='num'>{fmt_abs(r['accuracy'])}</td><td class='num'>{fmt_abs(r['oldver_value_in_answer_rate'])}</td></tr>"
            )
        out.append("</table>")
    out.append("</section>")
    return "\n".join(out)


def render_onoff_table(rows):
    # K2 — split 칸엔 dev/holdout(또는 K3의 혼합 표시)만, 안내문은 별도 '비고' 칸으로(전엔 데이터셋 칸에 붙여 중복처럼 보였음).
    out = [
        "<table><tr><th>데이터셋</th><th>split</th><th>비고</th><th class='num'>n</th>"
        "<th class='num'>R@1 off→on</th><th class='num'>MRR off→on</th>"
        "<th class='num'>McNemar p</th><th>95% CI(on−off)</th></tr>"
    ]
    for r in rows:
        remark = "<span class='tag warn'>holdout — 확인만, 튜닝 근거 아님</span>" if r["group"] == "holdout" else ""
        # K1 — 불일치(discordant) 0이면 McNemar가 정의상 계산 불가(n/a)인 이유를 "차이 없음"으로 명시.
        p_cell = "차이 없음(불일치 0)" if r.get("n_discordant") == 0 else fmt_p(r["mcnemar_p"])
        out.append(
            f"<tr><td>{esc(r['dataset'])}</td><td>{esc(r['group'])}</td><td>{remark}</td><td class='num'>{r['n']}</td>"
            f"<td class='num'>{fmt_abs(r['r1_off'], 2)}→{fmt_abs(r['r1_on'], 2)}</td>"
            f"<td class='num'>{fmt_abs(r['mrr_off'], 2)}→{fmt_abs(r['mrr_on'], 2)}</td>"
            f"<td class='num'>{esc(p_cell)}</td><td>{fmt_ci(r['ci'])}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def tab_onoff(ctx):
    out = ["<section id='onoff' class='tab'>", "<h2>2-5. 개선 켬/끔(J2)</h2>"]
    tables = ctx.get("onoff_tables") or []
    if not tables:
        out.append("<p class='note warn'>미실행 — --onoff가 지정되지 않음.</p></section>")
        return "\n".join(out)
    out.append(
        "<p class='muted small'><b>정의:</b> R@1·MRR은 question-pooled(해당 실행의 결과 그대로, off=끔 실행·on=켬 실행). "
        "McNemar p·95% CI는 두 실행 모두에 있는 질문 id의 hit@1(gold_rank==1) 적중 여부를 짝지어 비교한 값"
        "(기존 mcnemar_p·paired_diff_ci 재사용) — p<0.05면 차이가 유의, CI가 0을 포함하면 구분 안 됨.</p>"
    )
    for t in tables:
        # L4-7 후 재실측(로컬 bge-m3) — 이름에 _after가 들어간 항목만 구분 표시(새 CLI 플래그 없이 명명 규칙으로).
        prefix = "L4-7 후(로컬 bge-m3) — " if "_after" in t["name"] else ""
        out.append(
            f"<h3>{esc(prefix + t['name'])} — <code>{esc(t['combo'])}</code> "
            f"(끔=<code>{esc(t['dir_a'])}</code> → 켬=<code>{esc(t['dir_b'])}</code>)</h3>"
        )
        out.append(render_onoff_table(t["rows"]) if t["rows"] else "<p class='na'>미실행 — 두 실행의 공통 데이터셋이 없음.</p>")
    out.append("</section>")
    return "\n".join(out)


def tab_docs(ctx):
    out = ["<section id='docs' class='tab'>", "<h2>3. 문서별 최우수 조합</h2>"]
    out.append(
        "<p class='note'>이 탭의 '최우수'는 <b>문서 관련 질문의 검색 성공률(top5 안에 그 문서 포함)</b> 기준 근사치다 — "
        "사실 재현율(facts_n 단위 hit)은 results.json에 없어(§8 필요 필드) 계산할 수 없음. 파싱 엔진별 사실 재현율은 "
        "4. 파싱 세트 탭(doc_stats.json 기반 proxy)을 참고.</p>"
    )
    rows = ctx["doc_rows"]
    by_fmt = {}
    for r in rows:
        by_fmt.setdefault(r.get("format") or "?", []).append(r)
    out.append(f"<p>문서 {len(rows)}건(형식 {len(by_fmt)}종) — 형식별로 접어 보기.</p>")
    for fmt, docs in sorted(by_fmt.items()):
        out.append(
            f"<details><summary>{esc(fmt)} ({len(docs)}건)</summary><table><tr><th>데이터셋</th><th>파일</th>"
            "<th>split</th><th>이슈</th><th class='num'>관련 질문 수</th><th>최우수 조합</th><th class='num'>성공률</th>"
            "<th>이 문서에서 놓친 질문</th></tr>"
        )
        for d in docs:
            if d["n_q"] == 0:
                out.append(
                    f"<tr><td>{esc(d.get('dataset'))}</td><td>{esc(d.get('file'))}</td><td>{esc(d.get('split'))}</td>"
                    f"<td>{esc(','.join(d.get('issues') or []))}</td><td class='num'>0</td>"
                    "<td class='na'>미실행(관련 질문 없음 또는 매칭 실패)</td><td class='num'>n/a</td><td>-</td></tr>"
                )
                continue
            best = d["best"]
            out.append(
                f"<tr><td>{esc(d.get('dataset'))}</td><td>{esc(d.get('file'))}</td><td>{esc(d.get('split'))}</td>"
                f"<td>{esc(','.join(d.get('issues') or []))}</td><td class='num'>{d['n_q']}</td>"
                f"<td><code>{esc(best['combo']) if best else '미실행'}</code></td>"
                f"<td class='num'>{fmt_abs(best['rate']) if best else 'n/a'}</td>"
                f"<td class='small'>{esc(', '.join(d['missed'][:5]))}</td></tr>"
            )
        out.append("</table></details>")
    out.append("</section>")
    return "\n".join(out)


def tab_parsing(ctx):
    out = ["<section id='parsing' class='tab'>", "<h2>4. 파싱 세트</h2>"]
    fmt_rows, post_rows = ctx["parsing"]
    out.append("<h3>형식 × 엔진 — 사실 재현율 proxy(index.json의 acc, 대표 엔진 정확도)</h3>")
    if not fmt_rows:
        out.append("<p class='note warn'>미실행 — output/store/p1/*/*/doc_stats.json을 찾지 못함.</p>")
    else:
        out.append(
            "<table><tr><th>형식</th><th>엔진</th><th class='num'>문서 수</th><th class='num'>재현율 proxy</th>"
            "<th class='num'>평균 ms</th><th class='num'>금지 값 위반</th></tr>"
        )
        for r in fmt_rows:
            mnv_cell = f"{r['mnv_total']}건({r['mnv_docs']}문서)" if r["mnv_total"] else "0"
            out.append(
                f"<tr><td>{esc(r['format'])}</td><td>{esc(r['engine'])}</td><td class='num'>{r['n']}</td>"
                f"<td class='num'>{fmt_abs(r['acc_proxy'])}</td><td class='num'>{fmt_ms(r['mean_ms'])}</td>"
                f"<td class='num'>{esc(mnv_cell)}</td></tr>"
            )
        out.append("</table>")
        total_mnv = sum(r["mnv_total"] for r in fmt_rows)
        out.append(
            "<p class='muted small'>금지 값 위반(W20) — doc_stats.json의 must_not_violations(파싱 단계에서 "
            f"나오면 안 될 값이 나온 문서). {'이번 실행은 전부 0건(위반 없음).' if not total_mnv else f'총 {total_mnv}건 — 위 표에서 해당 형식·엔진 확인.'}</p>"
        )
    out.append("<h3>후보정 효과(parity_synth-*.json) — none vs all 사실 재현율</h3>")
    if not post_rows:
        out.append("<p class='note warn'>미실행 — output/parity/parity_synth-*.json 없음.</p>")
    else:
        out.append(
            "<table><tr><th>데이터셋</th><th class='num'>문서</th><th class='num'>사실 수</th>"
            "<th class='num'>후보정 끔</th><th class='num'>후보정 전부</th><th class='num'>그림 수</th>"
            "<th class='num'>연결 F1 평균</th></tr>"
        )
        for r in post_rows:
            out.append(
                f"<tr><td>{esc(r['dataset'])}</td><td class='num'>{r['docs']}</td><td class='num'>{r['facts']}</td>"
                f"<td>{esc(r['none'])}</td><td>{esc(r['all'])}</td><td class='num'>{r['figures']}</td>"
                f"<td class='num'>{fmt_abs(r['connection_f1_mean']) if r['connection_f1_mean'] is not None else 'n/a'}</td></tr>"
            )
        out.append("</table>")
    out.append(
        "<p class='muted small'>A(합집합)~F(근처 본문) 단계별 후보정 설정(§4)은 parity 파일에 설정별로 안 나뉘어 있어 "
        "none/all 두 값만 표시 — 단계별 분해는 미실행(옆 세션 parity 산출 확장 필요).</p>"
    )
    out.append("</section>")
    return "\n".join(out)


def tab_failures(ctx):
    rows = ctx["failures"]
    combos = ctx["combos"]
    out = ["<section id='failures' class='tab'>", "<h2>5. 실패 사례</h2>"]
    out.append("<p>실패 많은 순 정렬(모두 맞힌 문항은 아래). 조합을 골라 그 조합이 실패한 문항만 볼 수 있음.</p>")
    out.append(
        "<label>조합 필터: <select onchange='filterFailures(this)'><option value='__all__'>전체</option>"
        + "".join(f"<option value='{esc(c)}'>{esc(c)}</option>" for c in combos)
        + "</select></label>"
    )
    out.append(
        "<table id='failure-table'><thead><tr><th>데이터셋</th><th>질문ID</th><th class='num'>실패/전체</th><th>펼쳐 보기</th></tr></thead><tbody>"
    )
    for r in rows[:500]:
        combos_attr = "|".join(r["fail_combos"])
        detail = [
            f"<p><b>질문:</b> {esc(r['question'])}</p>",
            f"<p><b>정답:</b> {esc(r['gold'])}</p>",
            "<table><tr><th>콤보</th><th>결과</th><th>원인</th><th>근거 상위3</th><th>답(500자)</th></tr>",
        ]
        for c, v in sorted(r["combos"].items()):
            ev = ", ".join(e.get("doc", "") for e in (v.get("top3") or []))
            detail.append(
                f"<tr><td><code>{esc(c)}</code></td><td>{'실패' if v['fail'] else '성공'}</td>"
                f"<td>{esc(v['cause']) if v['cause'] else ('판정 보류' if v['fail'] else '-')}</td>"
                f"<td class='small'>{esc(ev)}</td><td class='small'>{esc(v.get('answer') or '-')}</td></tr>"
            )
        detail.append("</table>")
        out.append(
            f"<tr data-combos='{esc(combos_attr)}'><td>{esc(r['dataset'])}</td><td>{esc(r['id'])}</td>"
            f"<td class='num'>{r['n_fail']}/{r['n_total']}</td>"
            f"<td><details><summary>보기</summary>{''.join(detail)}</details></td></tr>"
        )
    out.append("</tbody></table>")
    if len(rows) > 500:
        out.append(f"<p class='muted small'>전체 {len(rows)}문항 중 실패 많은 상위 500개만 표시(HTML 크기 제한).</p>")
    out.append("</section>")
    return "\n".join(out)


def tab_figures(ctx):
    out = ["<section id='figures' class='tab'>", "<h2>6. 그림 산출물</h2>"]
    out.append(
        "<p class='note warn'>미실행 — 이번 검색/답 실행(results.json·answers.json)에는 그림 기록(.figures.json)·"
        "연결 F1·캡션 매핑 데이터가 없음. §6 예시(연결 F1 10개 중 9개 1.0 등)는 다른 세션의 별도 평가 산출물에서 "
        "나온 것으로, 이 보고서가 읽는 입력 경로(stack_matrix 실행 결과)에는 포함되지 않아 수치를 못 채움.</p>"
    )
    out.append("</section>")
    return "\n".join(out)


def tab_cause(ctx):
    out = ["<section id='cause' class='tab'>", "<h2>7. 원인 판정 · 개선</h2>"]
    counts = {}
    for r in ctx["failures"]:
        for _c, v in r["combos"].items():
            if v["fail"]:
                counts[v["cause"] or "판정 보류"] = counts.get(v["cause"] or "판정 보류", 0) + 1
    out.append("<table><tr><th>원인 코드</th><th class='num'>실패 수(조합×문항)</th><th>분류</th></tr>")
    group = {
        "R1": "파이프라인으로 고칠 것",
        "G1": "파이프라인으로 고칠 것",
        "G2": "파이프라인으로 고칠 것",
        "판정 보류": "데이터 부족 — 보류",
    }
    for code, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        out.append(f"<tr><td>{esc(code)}</td><td class='num'>{n}</td><td>{esc(group.get(code, '미분류'))}</td></tr>")
    out.append("</table>")
    out.append(
        "<p class='note warn'>미실행 — P1~P4(파싱)·M1(모델 한계)·K1(배경지식)·S1(채점 한계)은 파싱층 사실 단위 채점·"
        "모델 축 비교(model_matrix)·용어 사전 데이터가 이 실행에 없어 자동 판정 불가('판정 보류'로 뭉뚱그려 집계). "
        "개선 아이디어 → 예상 회복 수 → 백로그 ID 매핑도 같은 이유로 비움.</p>"
    )
    out.append("</section>")
    return "\n".join(out)


def tab_appendix(ctx):
    out = ["<section id='appendix' class='tab'>", "<h2>부록</h2>", "<h3>지표 정의·약어</h3><table><tr><th>약어</th><th>정의</th></tr>"]
    for k, v in ABBR:
        out.append(f"<tr><td><code>{esc(k)}</code></td><td>{esc(v)}</td></tr>")
    out.append("</table>")
    out.append(
        "<h3>통계 방법</h3><ul>"
        "<li>McNemar 정확 검정(양측) — 짝지은 두 조합의 불일치 쌍(한쪽만 맞힘)만으로 p값 계산.</li>"
        "<li>짝 부트스트랩 95% CI — 같은 질문 짝을 유지한 채 2000회 재추출, 후보−기준(또는 후보−1위) 적중률 차의 분포에서 2.5·97.5 백분위.</li>"
        "<li>동급 판정(§2) — McNemar p≥0.05 이고 차 95% CI가 0을 포함 → '1위와 통계적으로 구분 안 됨'.</li>"
        "<li>순위 = holdout 지표(정답률 있으면 그것, 없으면 R@5), 동률이면 dev. Top3은 동급 여부와 무관하게 항상 표시, 4~10위는 동급일 때만.</li>"
        "</ul>"
    )
    out.append(
        "<h3>미실행·미튜닝 목록</h3><ul>"
        "<li>Recall 곡선(k=1..50) — recall_at 필드가 있는 새 형식 실행(recall-20261003 등 완료 후)에서만 채워짐.</li>"
        "<li>Answer-k(5/10/20) — answer-20261003 실행이 끝나야 k별 비교 가능(현재 raw만 있음).</li>"
        "<li>그림 산출물(연결 F1·캡션 매핑) — 이번 입력 경로에 그림 기록 데이터 없음.</li>"
        "<li>원인 판정 P1~P4·M1·K1 — 파싱 사실 단위 채점·모델 축 비교·용어 사전 데이터 없음.</li>"
        "<li>튜닝 현황(충분/부분/미튜닝) — results.json/answers.json에 해당 필드 없음, 수동 입력 필요.</li>"
        "<li>비용·문서당 VLM 호출·다문서 정답률 — §8에서 요구하는 필드가 현재 results.json/answers.json에 없음.</li>"
        "</ul>"
    )
    out.append("</section>")
    return "\n".join(out)


def question_scope(idx_retr, grp_map):
    """헤더에 쓸 평가 문항 범위 — eval_set split에 속한 데이터셋 중 이번 실행에 실제로 있는 것만, 실측(하드코딩 아님).
    새 세트(synth-confuse 등)가 추가돼 있으면 자동으로 집계에 들어간다."""
    ds_present = sorted({ds for (_, ds) in idx_retr} & set(grp_map))
    total = 0
    for ds in ds_present:
        ids = set()
        for (_c, d), e in idx_retr.items():
            if d == ds:
                ids |= {r["id"] for r in (e.get("rows") or [])}
        total += len(ids)
    return total, ds_present


# ───────────────────────── 보고서 조립 ─────────────────────────
def build_context(
    retrieval_dir,
    answer_dirs,
    invalid_run_names=None,
    retr_dist_dir=None,
    answer_dist_dirs=None,
    pool_retr_dir=None,
    pool_answer_dirs=None,
    onoff_specs=None,
    answers_missing_reason=None,
    tuned_holdout=None,
):
    invalid_run_names = set(invalid_run_names or [])
    results = _load_json(Path(retrieval_dir) / "results.json") or []
    run_meta = _load_json(Path(retrieval_dir) / "run_meta.json") or []
    layers_used = _load_json(Path(retrieval_dir) / "layers_used.json") or []
    answers = load_answer_runs(answer_dirs or [], invalid_run_names)  # G7 — 여러 답 실행 지원

    eval_set = load_eval_set()
    stack_cfg = load_stack_cfg()
    grp_map = dataset_group_map(eval_set, stack_cfg)  # G1 — synth-4clients=dev 포함(§ dataset_group_map docstring)
    combos = combo_order(results)
    idx_retr = index_retrieval(results)
    idx_ans_raw = index_answers_raw(answers)
    datasets = sorted({ds for (_, ds) in idx_retr} | {ds for (_, ds, _) in idx_ans_raw})

    # L3-2/J1 — pool(합친 색인) 검색 결과를 먼저 읽어 둔다(지정됐을 때만) — J1 순위 폴백에도, 2-4 탭에도 재사용.
    idx_retr_pool, combos_pool, pool_ctx = None, [], None
    if pool_retr_dir is not None:
        pool_results = _load_json(Path(pool_retr_dir) / "results.json") or []
        idx_retr_pool = index_retrieval(pool_results)
        combos_pool = combo_order(pool_results)
        pool_ctx = {"idx_retr_pool": idx_retr_pool, "idx_hit1": build_pool_r1_index(idx_retr_pool)}

    # 운영 k(§1) — answer 실행에 실제로 있는 k들 중 baseline holdout 정답률이 가장 높은 k.
    ks = sorted({k for (_, _, k) in idx_ans_raw if k is not None})
    operating_k = determine_operating_k(idx_ans_raw, grp_map, idx_retr, ks) if ks else None
    flat_ans = flatten_answers_at_k(idx_ans_raw, operating_k) if operating_k is not None else flatten_answers(idx_ans_raw)

    ranking_by_k = {}
    for k in ks:
        m, rsn, kp = compute_ranking(combos, idx_retr, flatten_answers_at_k(idx_ans_raw, k), grp_map)
        ranking_by_k[k] = {"metric": m, "reason": rsn, "kept": kp}
    metric, reason, kept = (
        (ranking_by_k[operating_k]["metric"], ranking_by_k[operating_k]["reason"], ranking_by_k[operating_k]["kept"])
        if operating_k is not None and operating_k in ranking_by_k
        else compute_ranking(combos, idx_retr, flat_ans, grp_map, pool_ctx=pool_ctx)
    )
    # J1 — pool R@1로 대체된 경우에만 별도 색인 R@5를 '참고용' 보조 순위로 같이 계산해 둔다(결정에는 안 씀, 표시만).
    ranking_r5_ref = compute_ranking(combos, idx_retr, flat_ans, grp_map) if metric == "pool_r1" else None

    discrim_ds = discriminating_datasets(idx_retr, [d for d in datasets if grp_map.get(d)], combos)  # G3
    discrim_metric, discrim_reason, discrim_kept = compute_ranking(
        combos, idx_retr, flat_ans, grp_map, datasets_filter=set(discrim_ds), pool_ctx=pool_ctx
    )
    excluded_ds = sorted(set(d for d in datasets if grp_map.get(d)) - set(discrim_ds))
    axis_rows = compute_axis_table(combos, idx_retr, grp_map)
    saturation = saturation_by_dataset(
        idx_retr, datasets, flat_ans=flat_ans, grp_map=grp_map, combos=combos, use_accuracy=(metric == "answer_accuracy")
    )  # I1
    recall_curve = build_recall_curve(idx_retr, combos, grp_map)
    answer_k = build_answer_k(idx_ans_raw, grp_map, idx_retr)
    ref_attach = build_ref_attach_table(flat_ans, idx_retr, grp_map, combos)  # W20
    failures = build_failure_explorer(idx_retr, flat_ans, combos, grp_map)
    doc_rows = build_doc_tab(eval_set, idx_retr, combos, grp_map)
    parsing = build_parsing_tab(load_doc_stats(), load_parity(), eval_set)
    total_q, ds_present = question_scope(idx_retr, grp_map)
    data_quality_warnings = build_data_quality_warnings(idx_retr)
    eval_set_datasets = sorted(eval_set.get("split") or {})  # I5 — eval_set.json이 아는 전체 세트
    missing_eval_datasets = sorted(set(eval_set_datasets) - set(ds_present))  # I5 — 이번 결과에 없는 것

    # V11 — 방해 문서(distractors) 비교(지정됐을 때만).
    distractor_rows = None
    if retr_dist_dir is not None:
        dist_results = _load_json(Path(retr_dist_dir) / "results.json") or []
        dist_answers = load_answer_runs(answer_dist_dirs or [], set())
        idx_retr_dist = index_retrieval(dist_results)
        dist_status = distractor_status_map(dist_results)
        idx_ans_dist_raw = index_answers_raw(dist_answers)
        distractor_rows = build_distractor_comparison(
            idx_retr, idx_retr_dist, dist_status, idx_ans_raw, idx_ans_dist_raw, grp_map, operating_k, saturation
        )

    # L3-2 — pool(합친 색인) 비교(지정됐을 때만, idx_retr_pool은 위에서 이미 읽어 둠).
    pool_data = None
    if pool_retr_dir is not None:
        pool_answers = load_answer_runs(pool_answer_dirs or [], set())
        idx_ans_raw_pool = index_answers_raw(pool_answers)
        ov_strict, ov_loose, n_ov = pool_overall_confusion(idx_retr_pool, "baseline", "oldver_rank")
        v2_k, v2_acc = pool_v2_best_accuracy(idx_ans_raw_pool, "baseline")
        pool_data = {
            "run_name": Path(pool_retr_dir).name,
            "answers_run_names": [Path(d).name for d in (pool_answer_dirs or [])],
            "combos": combos_pool,
            "retrieval_rows": build_pool_retrieval(idx_retr_pool, idx_retr, grp_map, combos_pool),
            "answer_rows": build_pool_answers(idx_ans_raw_pool),
            "summary": {"oldver_strict": ov_strict, "oldver_loose": ov_loose, "n_oldver": n_ov, "v2_k": v2_k, "v2_accuracy": v2_acc},
        }

    onoff_tables = build_onoff_tables(onoff_specs or [], grp_map)  # J2

    invalid_run_notes = [{"run": name, "reason": "무효(그림 기록 비어 있음 — 하네스 결함, 재실행 중)"} for name in invalid_run_names]

    import datetime

    return {
        "run_name": Path(retrieval_dir).name,
        "answers_run_names": [Path(d).name for d in (answer_dirs or [])],
        "distractor_run_names": {
            "retrieval": Path(retr_dist_dir).name if retr_dist_dir else None,
            "answers": [Path(d).name for d in (answer_dist_dirs or [])],
        },
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "eval_set_commit": eval_set_commit(),  # I5
        "missing_eval_datasets": missing_eval_datasets,  # I5
        "question_scope": {"total": total_q, "datasets": ds_present},
        "invalid_run_notes": invalid_run_notes,
        "run_meta": run_meta,
        "layers_used": layers_used,
        "grp_map": grp_map,
        "combos": combos,
        "sibling_runs": sibling_run_status(),
        "baseline_ref": load_baseline_ref(),
        "operating_k": operating_k,
        "ks": ks,
        "ranking_by_k": ranking_by_k,
        "ranking": {"metric": metric, "reason": reason, "kept": kept},
        "ranking_r5_ref": (
            {"metric": ranking_r5_ref[0], "reason": ranking_r5_ref[1], "kept": ranking_r5_ref[2]} if ranking_r5_ref else None
        ),  # J1
        "discrim_ranking": {
            "metric": discrim_metric,
            "reason": discrim_reason,
            "kept": discrim_kept,
            "included_datasets": discrim_ds,
            "excluded_datasets": excluded_ds,
        },
        "axis_rows": axis_rows,
        "saturation": saturation,
        "recall_curve": recall_curve,
        "answer_k": answer_k,
        "ref_attach": ref_attach,
        "failures": failures,
        "doc_rows": doc_rows,
        "parsing": parsing,
        "flat_ans": flat_ans,
        "data_quality_warnings": data_quality_warnings,
        "distractor_rows": distractor_rows,
        "pool_data": pool_data,
        "onoff_tables": onoff_tables,
        "answers_missing_reason": answers_missing_reason,
        "tuned_holdout": tuned_holdout or [],  # J4/J5
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval", help="검색 실행 폴더 이름(output/eval/stack_matrix/<run>) 또는 절대경로")
    ap.add_argument("--answers", help="답 실행 폴더 이름(콤마로 여러 개, G7)")
    ap.add_argument(
        "--invalid-runs", help="하네스 결함 등으로 무효 처리할 실행 이름(콤마) — 해당 실행의 모든 데이터가 순위·축별 기여에서 빠짐"
    )
    ap.add_argument("--retrieval-distractors", help="방해 문서(V11) 검색 실행 폴더 이름")
    ap.add_argument("--answers-distractors", help="방해 문서(V11) 답 실행 폴더 이름(콤마로 여러 개)")
    ap.add_argument("--retrieval-pool", help="합친 색인(pool, L3-2) 검색 실행 폴더 이름")
    ap.add_argument("--answers-pool", help="합친 색인(pool, L3-2) 답 실행 폴더 이름(콤마로 여러 개)")
    ap.add_argument(
        "--onoff",
        action="append",
        help="개선 켬/끔 비교(J2, 반복 가능) — 'name=runA::runB[::combo]'(runA=끔/off, runB=켬/on, "
        "combo 생략시 baseline, 구분자는 ::  — Windows 절대경로의 드라이브 콜론과 겹치지 않게). "
        "예: --onoff recency_latest=loop4d-rec0::loop4d-rec1",
    )
    ap.add_argument("--answers-missing-reason", help="답변(A층) 데이터가 전혀 없을 때 n/a 대신 보일 사유(J4, 예: '크레딧 소진')")
    ap.add_argument(
        "--tuned-holdout", help="결과를 보고 고친 세트 표시(J5) — 'dataset:ticket,dataset2:ticket2' 형식, holdout 해석 주의 한 줄 추가"
    )
    ap.add_argument("--out", help="출력 HTML 경로")
    a = ap.parse_args()

    if not a.retrieval or not a.out:
        print("--retrieval과 --out은 필수(--selftest가 아니면)", file=sys.stderr)
        raise SystemExit(2)
    retr_dir = resolve_run_dir(a.retrieval)
    if not retr_dir:
        raise SystemExit(f"검색 실행 폴더를 찾을 수 없음: {a.retrieval}")
    ans_dirs = []
    for name in a.answers.split(",") if a.answers else []:
        d = resolve_run_dir(name.strip())
        if d:
            ans_dirs.append(d)
        else:
            print(f"[경고] 답 실행 폴더를 찾을 수 없음: {name} — 건너뜀", file=sys.stderr)
    invalid_names = {n.strip() for n in (a.invalid_runs.split(",") if a.invalid_runs else []) if n.strip()}

    retr_dist_dir = resolve_run_dir(a.retrieval_distractors) if a.retrieval_distractors else None
    if a.retrieval_distractors and not retr_dist_dir:
        print(f"[경고] 방해 문서 검색 실행 폴더를 찾을 수 없음: {a.retrieval_distractors} — V11 탭 비움", file=sys.stderr)
    ans_dist_dirs = []
    for name in a.answers_distractors.split(",") if a.answers_distractors else []:
        d = resolve_run_dir(name.strip())
        if d:
            ans_dist_dirs.append(d)
        else:
            print(f"[경고] 방해 문서 답 실행 폴더를 찾을 수 없음: {name} — 건너뜀", file=sys.stderr)

    pool_retr_dir = resolve_run_dir(a.retrieval_pool) if a.retrieval_pool else None
    if a.retrieval_pool and not pool_retr_dir:
        print(f"[경고] pool 검색 실행 폴더를 찾을 수 없음: {a.retrieval_pool} — pool 탭 비움", file=sys.stderr)
    pool_ans_dirs = []
    for name in a.answers_pool.split(",") if a.answers_pool else []:
        d = resolve_run_dir(name.strip())
        if d:
            pool_ans_dirs.append(d)
        else:
            print(f"[경고] pool 답 실행 폴더를 찾을 수 없음: {name} — 건너뜀", file=sys.stderr)

    onoff_specs = []
    for raw in a.onoff or []:
        if "=" not in raw or "::" not in raw.split("=", 1)[1]:
            print(f"[경고] --onoff 형식 오류('name=runA::runB[::combo]' 아님): {raw} — 건너뜀", file=sys.stderr)
            continue
        name, rest = raw.split("=", 1)
        parts = rest.split("::")
        dir_a, dir_b = resolve_run_dir(parts[0].strip()), resolve_run_dir(parts[1].strip())
        if not dir_a or not dir_b:
            print(f"[경고] --onoff 실행 폴더를 찾을 수 없음: {raw} — 건너뜀", file=sys.stderr)
            continue
        onoff_specs.append({"name": name, "dir_a": dir_a, "dir_b": dir_b, "combo": parts[2] if len(parts) > 2 else "baseline"})

    tuned_holdout = []
    for item in a.tuned_holdout.split(",") if a.tuned_holdout else []:
        item = item.strip()
        if not item:
            continue
        ds, _, ticket = item.partition(":")
        tuned_holdout.append((ds.strip(), ticket.strip()))

    ctx = build_context(
        retr_dir,
        ans_dirs,
        invalid_names,
        retr_dist_dir,
        ans_dist_dirs,
        pool_retr_dir,
        pool_ans_dirs,
        onoff_specs,
        a.answers_missing_reason,
        tuned_holdout,
    )
    out_html = build_html(ctx)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out_html, encoding="utf-8")
    size_mb = len(out_html.encode("utf-8")) / 1e6
    print(f"[stack_report] {out_path} ({size_mb:.2f}MB)")
    if size_mb >= 5:
        print("[경고] 5MB 이상 — 실패 탐색기 표시 행 수를 줄이거나 answer 길이를 더 트리밍하세요.", file=sys.stderr)


if __name__ == "__main__":
    utf8_stdout()
    main()
