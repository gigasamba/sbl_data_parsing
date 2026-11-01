#!/usr/bin/env python3
"""모델 조합 실험 하네스(LLM·VLM·embed) — 서버 구성(docs/engine)에 맞춘 후보를 개발 PC에서는 OpenRouter로 비교한다.
모델 이름·env 변수·재사용 묶음 경로는 전부 eval/model_matrix.json에만 — 이 파일에 모델 이름을 적지 않는다.

설계(design=ofat, eval/model_matrix.json): 역할(llm·vlm·embed)마다 기준값만 하나 바꾼 조합 + 선택적 extra 조합.
  embed 역할만 바뀌면 검색 묶음(bundle)을 다시 지어야 하고, llm·vlm 역할은 기존 기준 묶음을 그대로 쓴다
  (vlm은 그림 검토(eval_figure_review.py)·연구 답변(eval_research.py)에서 env로만 바뀜 — "VLM 파싱 엔진"(phase 3) 자체를
  다른 VLM으로 다시 돌리는 조합은 이 harness 범위 밖: vlm_parse_variant_bundles에 기존 기준 VLM 결과만 참고로 남겨 둠).

prepare 구현 경로(둘 다 읽고 고름 — valid_env/docker/compose.test.yml parse+structure job vs 호스트 cli/pipeline.py):
  **호스트에서 modules/structure/bundle.py를 직접 실행**하는 쪽을 쓴다. 이유: 이 세션이 비교할 데이터셋은 이미
  scratch(reuse_bundles)에 parse 산출물(output/parse 모양 그대로 — _rep 포함)이 있어, structure만 다시 돌리면 되는데
  bundle.py는 --parse-dir·--src·--embed·--out만 받는 순수 CLI라 컨테이너 기동 비용 없이 그대로 재사용할 수 있다.
  새 데이터셋을 처음 파싱해야 하면(지문이 바뀌었거나 reuse_bundles에 없으면) docker compose.test.yml의 parse 잡이
  더 안전(원본 폐쇄망 가드·엔진 전체가 이미지 안에 고정)하므로 그 경로는 _docker_parse_cmd()에 **명령만 구성**해 두고
  (스펙의 ip_build.sh 패턴과 동일) 이 세션에서는 실행하지 않는다(비용 — 사용자 지시).

사용:
  python cli/model_matrix.py plan                                   # 조합·예상 호출수·시간(오프라인)
  python cli/model_matrix.py prepare [--datasets a,b] [--run-dir D] # 데이터셋 폴더 지문 확인 + embed별 묶음 준비
  python cli/model_matrix.py run --env <.env 파일> [--combos ...] [--datasets ...] [--workers 2] [--limit 3]
  python cli/model_matrix.py report --run-dir output/eval/model_matrix/<ts>
  python cli/model_matrix.py selftest                                # 오프라인 자기 점검
"""

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

from common.config import settings as S  # S7e2: 설정은 settings.yaml(자식 실행에는 덮기 파일 — child_env)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, E2E_ROOT, PKG_ROOT, PROJ_ROOT, STACK_FILE  # 폴더 재편 뒤 이 상수들만 바뀌면 됨

DEV = PKG_ROOT  # deploy/common/ (S6a — 옛 deploy/common_tools/와 같은 깊이 · 옛 dev/)
ROOT = PROJ_ROOT  # 저장소 루트
VALID = ROOT / "valid_env" / "unstructured"
CONFIG_PATH = E2E_ROOT / "model_matrix.json"  # eval/ -> evaluation/ 이동 뒤 이 파일과 같은 폴더
RUN_ROOT = APP_ROOT / "output" / "eval" / "model_matrix"
NON_DOC_FILES = {"qa.json", "qa_rephrase.json", "spec.json", "rfi_spec.json", "manifest.json", "README.md"}
PY = sys.executable
_SECRET_RE = re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)[A-Z0-9_]*)\s*=\s*\S+")

from common.core.paths import resolve_run_dir as _resolve_run_dir  # noqa: E402 — RV6, 아래 resolve_run_dir()이 감쌈


def _scrub(s):
    """로그에 비밀값이 섞여 나가지 않게 — *KEY*/*TOKEN*/*PASSWORD*/*SECRET* 이름의 값만 가림(이름 자체는 남김)."""
    return _SECRET_RE.sub(r"\1=<redacted>", s or "")


# ───────────────────────── 설정 ─────────────────────────
def stack_file(config):
    """엔진 구성 파일(--stack) — config `stack_json`의 상대 경로는 STACK_FILE 폴더(resources/config/) 기준, 비었으면 STACK_FILE.
    S2b(10-26) — S2에서 엔진 구성이 resources/config/로 옮겨 옛 `DEV / stack_json`(common_tools/pipeline_stack.json)은 없는 파일(VS2 B-1)."""
    v = config.get("stack_json")
    if not v:
        return STACK_FILE
    p = Path(v)
    return p if p.is_absolute() else STACK_FILE.parent / p


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def role_candidates(config, role):
    r = config["roles"][role]
    return r["baseline"], {c["id"]: c for c in r["candidates"]}


def _local_embed_available(cand):
    """bge-m3만 이 harness가 아는 로컬 임베딩(스펙 범위) — 패키지 설치 + HF 캐시 존재만 확인(모델 로드 안 함, 오프라인·빠름)."""
    if cand["id"] != "bge-m3":
        return False
    try:
        import importlib

        importlib.import_module("sentence_transformers")
    except ImportError:
        return False
    home = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))  # env 남김 — 라이브러리(huggingface 캐시 자리)
    return any(home.glob("hub/models--BAAI--bge-m3"))


def usable_candidates(config, role):
    """server_only 제외. 로컬 종류는 설치 확인해서 없으면 빠짐(스펙 "없으면 unavailable로 표시하고 건너뜀")."""
    baseline, cands = role_candidates(config, role)
    out = {}
    for cid, c in cands.items():
        if c.get("server_only"):
            continue
        if c.get("kind") == "local" and not _local_embed_available(c):
            continue
        out[cid] = c
    return baseline, out


def read_split(config):
    """데이터셋 → dev/holdout. valid_env/unstructured/eval_set.json의 split 필드가 있으면 그 값 우선(스펙) —
    거기 있는 데이터셋은 config datasets에 없어도(새로 추가된 것도) 그대로 들어온다("앞으로 늘어도 자동으로 잡힘").
    split에 없는 데이터셋(아직 split에 안 올라간 것)만 config datasets 기본값.
    S6a2(10-27) — 상대 `eval_set_path`는 저장소 루트(ROOT) 기준. 옛 `DEV`(common/) 기준 '../../valid_env/…'는 deploy/ 단이
    없는 이 저장소에서 저장소 밖을 가리켜 split이 조용히 빠졌다(리팩터링 전부터)."""
    group = {ds: g for g, names in config["datasets"].items() for ds in names}
    p = Path(config["eval_set_path"])
    p = p if p.is_absolute() else (ROOT / p).resolve()
    if p.exists():
        split = json.loads(p.read_text(encoding="utf-8")).get("split") or {}
        for ds, g in split.items():
            group[ds] = "holdout" if g in ("holdout", "held-out") else "dev"
    return group


def all_datasets(config):
    """retrieval 대상 전체 — read_split() 순서(결정적): config datasets에 먼저 적힌 순서 + eval_set.json에만 있는
    새 데이터셋(이름 순). research_sets·figure_sets는 eval_research.py·eval_figure_review.py가 아는 것만(그 도구를
    안 고치는 제약상 고정) — 거기 없는 새 데이터셋은 retrieval만 돈다."""
    group = read_split(config)
    cfg_order = config["datasets"].get("dev", []) + config["datasets"].get("holdout", [])
    return cfg_order + sorted(d for d in group if d not in cfg_order)


# ───────────────────────── OFAT 조합 ─────────────────────────
def ofat_combos(config):
    roles = ("llm", "vlm", "embed")
    baseline, usable = {}, {}
    for role in roles:
        b, cands = usable_candidates(config, role)
        baseline[role], usable[role] = b, cands
    combos = [{"name": "baseline", **baseline}]
    seen = {tuple(baseline[r] for r in roles)}
    for role in roles:
        for cid in sorted(usable[role]):  # 결정적 순서(해시 순서 의존 회피)
            if cid == baseline[role]:
                continue
            combo = dict(baseline)
            combo[role] = cid
            key = tuple(combo[r] for r in roles)
            if key in seen:
                continue
            seen.add(key)
            combos.append({"name": f"{role}={cid}", **combo})
    for i, triple in enumerate(config.get("extra") or []):
        combo = dict(zip(roles, triple))
        key = tuple(combo[r] for r in roles)
        if key in seen:
            continue
        seen.add(key)
        combos.append({"name": f"extra{i + 1}", **combo})
    return combos


def design_combos(config):
    design = config.get("design", "ofat")
    if design not in ("ofat", "staged"):
        raise SystemExit(f"[model_matrix] design={design!r} 미구현(ofat·staged만)")
    return ofat_combos(config)


# ───────────────────────── staged 조합(1단계 embed A/B → 2단계 llm×vlm 2x2) ─────────────────────────
def stage1_combos(config):
    """1단계 — embed만 바꾼 조합(llm·vlm은 기준 고정) · retrieval만 돈다(결정적)."""
    base_llm, _ = role_candidates(config, "llm")
    base_vlm, _ = role_candidates(config, "vlm")
    _, embed_cands = usable_candidates(config, "embed")
    return [{"name": f"embed={eid}", "llm": base_llm, "vlm": base_vlm, "embed": eid} for eid in sorted(embed_cands)]


def stage2_combos(config, embed_id):
    """2단계 — embed는 1단계 승자로 고정, llm×vlm 전체 곱(2x2)."""
    _, llm_cands = usable_candidates(config, "llm")
    _, vlm_cands = usable_candidates(config, "vlm")
    return [
        {"name": f"llm={lid}+vlm={vid}", "llm": lid, "vlm": vid, "embed": embed_id}
        for lid in sorted(llm_cands)
        for vid in sorted(vlm_cands)
    ]


def stage2_parts(config, combo):
    """(research를 돌릴지, figure_review를 돌릴지). split(기본): 지금 파이프라인은 VLM 결과가 검색 색인에 거의 안 들어가
    (대표 결과가 VLM인 문서 0~1건, 백로그 L1) research는 LLM에만, 그림 검토는 VLM에만 달림 → research는 기준 VLM 조합에서만,
    그림 검토는 기준 LLM 조합에서만(비용 절반). L1 반영 뒤에는 stage2_mode=factorial로 2x2 전부."""
    if config.get("stage2_mode", "split") == "factorial":
        return True, True
    base_llm, _ = role_candidates(config, "llm")
    base_vlm, _ = role_candidates(config, "vlm")
    return combo["vlm"] == base_vlm, combo["llm"] == base_llm


def _pick_stage1_winner(combos, results, group):
    """승자 = held-out 평균 R@5가 가장 높은 embed(동률이면 dev 평균 R@5) — 스펙 "Stage 1" 기준."""
    by_combo = {}
    for r in results:
        ret = r.get("retrieval") or {}
        if ret.get("r5") is not None:
            by_combo.setdefault(r["combo"], {})[r["dataset"]] = ret["r5"]
    scores = {}
    for c in combos:
        per_ds = by_combo.get(c["name"], {})
        dev_vals = [v for ds, v in per_ds.items() if group.get(ds) == "dev"]
        hold_vals = [v for ds, v in per_ds.items() if group.get(ds) == "holdout"]
        scores[c["name"]] = {
            "embed": c["embed"],
            "dev_r5": (sum(dev_vals) / len(dev_vals)) if dev_vals else None,
            "holdout_r5": (sum(hold_vals) / len(hold_vals)) if hold_vals else None,
        }

    def sort_key(name):
        s = scores[name]
        return (s["holdout_r5"] if s["holdout_r5"] is not None else -1.0, s["dev_r5"] if s["dev_r5"] is not None else -1.0)

    winner_name = max(scores, key=sort_key)
    return scores[winner_name]["embed"], scores


# ───────────────────────── 통계(McNemar 정확검정·부트스트랩 CI, stdlib만) ─────────────────────────
def mcnemar_p(pairs):
    """짝지은 (기준 적중?, 후보 적중?) 목록 → 양측 정확 McNemar p. 불일치 쌍(b≠c 셀)만 쓴다 — 둘 다 같은 문항은 버림.
    불일치가 0건이면 None(차이를 말할 수 없음)."""
    b = sum(1 for base, cand in pairs if base and not cand)
    c = sum(1 for base, cand in pairs if not base and cand)
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    cdf = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * cdf)


def bootstrap_ci(values, resamples=2000, seed=0):
    """0/1(또는 실수) 목록의 평균 95% 부트스트랩 CI — 시드 고정(결정적, code.md). 표본 없으면 (None, None)."""
    if not values:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    return means[int(0.025 * resamples)], means[min(resamples - 1, int(0.975 * resamples))]


# ───────────────────────── 데이터셋 지문·건수 ─────────────────────────
def dataset_doc_files(ds, root=None):
    base = Path(root) if root else VALID / ds
    scan = base / "docs" if (base / "docs").exists() else base
    if not scan.exists():
        return []
    return sorted(p for p in scan.rglob("*") if p.is_file() and p.name not in NON_DOC_FILES)


def dataset_fingerprint(ds, root=None):
    """파일 목록(상대경로)·크기의 sha — 샘플 데이터가 바뀌면(내용 같은 크기로 바뀌어도 이름 추가·삭제면) 달라짐."""
    base = Path(root) if root else VALID / ds
    h = hashlib.sha256()
    for p in dataset_doc_files(ds, root):
        h.update(f"{p.relative_to(base).as_posix()}:{p.stat().st_size}\n".encode())
    return h.hexdigest()[:16]


def dataset_counts(ds):
    base = VALID / ds
    n_q = 0
    try:
        n_q = len(json.loads((base / "qa.json").read_text(encoding="utf-8")).get("items", []))
    except Exception:
        pass
    n_fig = 0
    try:
        docs = json.loads((base / "spec.json").read_text(encoding="utf-8")).get("documents") or []
        n_fig = sum(len(d.get("images") or []) + len(d.get("figures") or []) for d in docs)
    except Exception:
        pass
    return n_q, n_fig


# ───────────────────────── qa.json 로더(검색 전용 — eval_research.py 안 건드리고 같은 스키마만 읽음) ─────────────────────────


# ───────────────────────── plan ─────────────────────────
def cmd_plan(config, a):
    if config.get("design", "ofat") == "staged":
        return cmd_plan_staged(config, a)
    return cmd_plan_ofat(config, a)


def cmd_plan_ofat(config, a):
    combos = design_combos(config)
    group = read_split(config)
    lat = config["latency"]
    baseline_embed, _ = role_candidates(config, "embed")
    datasets = all_datasets(config)
    counts = {d: dataset_counts(d) for d in datasets}
    print(f"# model_matrix plan — design={config.get('design', 'ofat')} · 콤보 {len(combos)}개 · 데이터셋 {len(datasets)}개\n")
    total_lo = total_hi = 0.0
    for combo in combos:
        needs_bundle = combo["embed"] != baseline_embed
        print(
            f"## {combo['name']}  (llm={combo['llm']} · vlm={combo['vlm']} · embed={combo['embed']}"
            + (" · 새 묶음 필요(prepare)" if needs_bundle else " · 기준 묶음 재사용")
            + ")"
        )
        for ds in datasets:
            nq, nfig = counts[ds]
            parts = [f"retrieval {nq}문항×{lat['query_embed_sec']}s"]
            lo = hi = nq * lat["query_embed_sec"]
            if ds in config["research_sets"]:
                rl = min(nq, config["research_limit"]) if config["research_limit"] else nq
                calls = rl * lat["research_calls_per_question"]
                rlo, rhi = calls * lat["research_sec_per_call_min"], calls * lat["research_sec_per_call_max"]
                lo += rlo
                hi += rhi
                parts.append(f"research {rl}문항({rlo / 60:.0f}~{rhi / 60:.0f}분)")
            if ds in config["figure_sets"]:
                fl = min(nfig, config["figure_review_limit"]) if config["figure_review_limit"] else nfig
                clo, chi = fl * lat["figure_calls_per_figure_min"], fl * lat["figure_calls_per_figure_max"]
                flo, fhi = clo * lat["figure_sec_per_call_min"], chi * lat["figure_sec_per_call_max"]
                lo += flo
                hi += fhi
                parts.append(f"figure_review {fl}그림({flo / 60:.0f}~{fhi / 60:.0f}분)")
            total_lo += lo
            total_hi += hi
            print(f"  - {ds}({group.get(ds, '?')}): " + " · ".join(parts) + f" → 계 {lo / 60:.0f}~{hi / 60:.0f}분")
    print(f"\n합계 예상 시간: {total_lo / 3600:.1f}~{total_hi / 3600:.1f}시간(API 호출 기준 — 이 plan은 오프라인, 아무것도 호출 안 함)")


def cmd_plan_staged(config, a):
    read_split(config)  # 설정 검사(그룹 나누기 오류면 여기서 멈춤) — 값은 안 씀
    lat = config["latency"]
    datasets = all_datasets(config)
    counts = {d: dataset_counts(d) for d in datasets}
    s1 = stage1_combos(config)
    print(f"# model_matrix plan — design=staged · 1단계(embed) {len(s1)}개 · 데이터셋 {len(datasets)}개\n")

    print("## 1단계 — embed A/B, retrieval만(결정적, 전 데이터셋) — 목표 <1시간")
    nq_total = sum(counts[d][0] for d in datasets)
    s1_total = len(s1) * nq_total * lat["query_embed_sec"]
    for combo in s1:
        print(f"  - {combo['name']}: {nq_total}문항×{lat['query_embed_sec']}s → {nq_total * lat['query_embed_sec'] / 60:.1f}분")
    flag = "" if s1_total <= 3600 else " — 목표(1시간) 초과, embed 후보·데이터셋을 줄이는 걸 고려"
    print(f"  1단계 합계: {s1_total / 60:.1f}분{flag}")

    base_embed, _ = role_candidates(config, "embed")
    s2 = stage2_combos(config, base_embed)  # 승자는 1단계 실행 전엔 모름 — embed는 비용에 안 들어가니 기준 embed로 추정해도 같음
    limit, repeats = config["stage2_limit"], config["repeats"]
    print(f"\n## 2단계 — llm×vlm 2x2(embed=1단계 승자 고정) · stage2_limit={limit}문항/데이터셋 · repeats={repeats} — 목표: 몇 시간")
    s2_lo = s2_hi = 0.0
    for combo in s2:
        do_r, do_f = stage2_parts(config, combo)
        for ds in datasets:
            nq, nfig = counts[ds]
            if do_r and ds in config["research_sets"]:
                rl = min(nq, limit)
                calls = rl * lat["research_calls_per_question"] * repeats
                s2_lo += calls * lat["research_sec_per_call_min"]
                s2_hi += calls * lat["research_sec_per_call_max"]
            if do_f and ds in config["figure_sets"]:
                fl = min(nfig, config["figure_review_limit"])
                s2_lo += fl * lat["figure_calls_per_figure_min"] * repeats * lat["figure_sec_per_call_min"]
                s2_hi += fl * lat["figure_calls_per_figure_max"] * repeats * lat["figure_sec_per_call_max"]
    w = max(1, config.get("workers", 2))
    s2_lo, s2_hi = s2_lo / w, s2_hi / w  # 작업 병렬(workers) — API 분당 상한에 걸리면 이보다 느림
    flag2 = (
        ""
        if s2_hi <= 4 * 3600
        else (
            " — 목표(몇 시간) 초과: research 문항당 5.5콜(문항당 36~60초 실측)이 지배적(2x2×데이터셋 수×stage2_limit×repeats가 "
            "곱으로 커짐) — stage2_limit·repeats·연구 대상 데이터셋 수 중 하나를 줄이는 걸 고려"
        )
    )
    print(
        f"  2단계 합계: {s2_lo / 3600:.1f}~{s2_hi / 3600:.1f}시간{flag2} (콤보 {len(s2)}개 × 데이터셋 {len(datasets)}개 × repeats {repeats} · {config.get('stage2_mode', 'split')} · workers {w})"
    )
    print(
        f"\n전체(1+2단계) 예상: {(s1_total + s2_lo) / 3600:.2f}~{(s1_total + s2_hi) / 3600:.2f}시간 "
        f"(design=ofat 전체 매트릭스보다 훨씬 작음 — embed는 결정적 1회, llm·vlm은 stage2_limit로 자름)"
    )
    print(
        "\n참고: repeats는 온도를 못 바꾼다(research()가 온도 0.0 고정 호출 — modules/** 수정 범위 밖) — "
        "LLM_CACHE_DIR을 반복마다 새로 둬 캐시만 비우는 방식(cache-bypass)으로 대신한다."
    )


# ───────────────────────── prepare ─────────────────────────
def resolve_run_dir(a, new=True):
    """RV6(10-09) — common/paths.resolve_run_dir로 옮김(동작·문구 그대로)."""
    return _resolve_run_dir(RUN_ROOT, getattr(a, "run_dir", None), new=new, label="model_matrix", rel_hint="output/eval/model_matrix")


def dataset_bundle(config, run_dir, ds, embed_id):
    """이 (데이터셋, embed) 조합의 묶음 경로 — config reuse_bundles 우선, 없으면 이 run이 지은 것(out_dir)."""
    reuse = config.get("reuse_bundles", {}).get(ds, {}).get(embed_id)
    if reuse:
        return reuse
    local = run_dir / "bundles" / ds / embed_id
    if (local / "bundle" / "meta.json").exists():
        return {"bundle": str(local / "bundle"), "cache": str(local / "embed_cache.sqlite")}
    return None


def _build_bundle_host(config, baseline_info, out_dir, embed_arg):
    """호스트에서 modules/structure/build_bundle.py 직접 실행 — 기준 embed로 이미 파싱된 산출물을 재사용(파싱은 다시 안 함)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = child_env(Names(EMBED_CACHE=str(out_dir / "embed_cache.sqlite")))
    args = [
        PY,
        "-m",
        "pipeline.transform.structure.build_bundle",
        "--parse-dir",
        baseline_info["parse_dir"],
        "--src",
        baseline_info.get("prepared_dir") or baseline_info["parse_dir"],
        "--embed",
        embed_arg,
        "--stack",
        str(stack_file(config)),
        "--summary",
        "lead",
        "--out",
        str(out_dir / "bundle"),
    ]
    r = subprocess.run(args, cwd=APP_ROOT, env=env, capture_output=True, text=True)  # 10-13 — env 상대경로·tools/ 모듈이 루트 기준
    return r.returncode == 0, _scrub(r.stderr[-2000:])


def _docker_parse_cmd(config, env_file, doc_src, rag_out, truth):
    """새 데이터셋 최초 parse(스펙 ip_build.sh 패턴) — 이 세션은 구성만, 실행 안 함(비용).
    외부 모델 가드 — VLM·임베딩은 *_ALLOW_EXTERNAL=1 + RUN_ENV=local이어야 외부(OpenRouter) 호출이 열린다(합성 문서 선언 잠금은
    사용자 10-29에 삭제). 정답 truth.json은 채점용으로 RAG_OUT/corpus/에 복사한다 — 설정은 compose.test.yml의
    parse·structure job 안에서 요구(VLM 파싱·API 임베딩이 거기서 바로 호출됨). S7e1 — compose.test.yml은 env 파일 대신 설정 파일(SMOKE_SETTINGS)을
    붙여 읽으므로 env 파일 사본(위 세 줄 포함)을 migrate로 settings.yaml로 옮긴다 — 키가 든 파일이라 RAG_OUT(결과 폴더) 밖 임시 폴더에 600으로
    (migrate --out이 600으로 씀, VS7e1 R-6). Linux Docker면 컨테이너 사용자(UID 10001)가 읽게 주인을 10001로(Docker Desktop은 그대로 읽음)."""
    return (
        f"cp {truth} {rag_out}/corpus/truth.json  # 가상 코퍼스 정답(채점용) — RAG_OUT/corpus/ 먼저 만들 것\n"
        f"# env 파일 사본에 VLM_ALLOW_EXTERNAL=1 · EMBED_ALLOW_EXTERNAL=1 · RUN_ENV=local을 더한 뒤:\n"
        f'S=$(mktemp -d)/smoke_settings.yaml && python -m common.config.migrate {env_file} --out "$S"   # 600 · RAG_OUT 밖(R-6)\n'
        f'export SMOKE_SETTINGS="$S" SMOKE_PG_PASSWORD=<시험용 PG 비밀번호> DATA_PIPELINE_IMAGE=data-pipeline:test '  # S6b — 저장소 루트에서, 합친 파이프라인 이미지
        f"MCP_SERVER_IMAGE=mcp-server:test DOC_SRC={doc_src} RAG_OUT={rag_out}\n"
        f"docker compose -f valid_env/docker/compose.test.yml run --rm parse parse "
        f"&& docker compose -f valid_env/docker/compose.test.yml run --rm structure structure"
    )


def cmd_prepare(config, a):
    run_dir = resolve_run_dir(a)
    datasets = a.datasets.split(",") if a.datasets else all_datasets(config)
    combos = design_combos(config)
    embeds_needed = sorted({c["embed"] for c in combos})
    baseline_embed, usable_embed = usable_candidates(config, "embed")
    report = {}
    for ds in datasets:
        report[ds] = {"fingerprint": dataset_fingerprint(ds)}
        baseline_info = config.get("reuse_bundles", {}).get(ds, {}).get(baseline_embed)
        for embed_id in embeds_needed:
            info = dataset_bundle(config, run_dir, ds, embed_id)
            if info:
                report[ds][embed_id] = {"status": "reused", "bundle": info["bundle"]}
                continue
            if embed_id not in usable_embed:
                report[ds][embed_id] = {"status": "skipped", "reason": "후보 unavailable(server_only 또는 로컬 설치 없음)"}
                continue
            if not baseline_info:
                cmd = _docker_parse_cmd(config, "<env파일>", f"<{ds} 원본>", f"<{ds} out>", _any_truth(config) or "<truth.json>")
                report[ds][embed_id] = {
                    "status": "needs_parse",
                    "reason": "이 데이터셋은 기존 파싱 산출물 없음 — 먼저 parse 필요(docker, 이 세션은 실행 안 함)",
                    "docker_cmd": cmd,
                }
                continue
            cand = usable_embed[embed_id]
            if cand.get("kind") != "local":
                report[ds][embed_id] = {
                    "status": "skipped",
                    "reason": "api embed 재구성은 토큰 비용 — --build-api로만(이 세션 기본 실행 안 함)",
                }
                continue
            if not a.build:
                report[ds][embed_id] = {"status": "pending", "reason": "--build 없이는 실제로 안 지음(계획만)"}
                continue
            out_dir = run_dir / "bundles" / ds / embed_id
            ok, err = _build_bundle_host(config, baseline_info, out_dir, cand["bundle_embed_arg"])
            report[ds][embed_id] = {"status": "built" if ok else "failed", "bundle": str(out_dir / "bundle"), "error": None if ok else err}
    (run_dir / "prepare_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\n→ {run_dir / 'prepare_report.json'}")


# ───────────────────────── run ─────────────────────────
# S7e2(사용자 10-28) — 설정은 settings.yaml로만: 자식 실행(_retrieve·build_bundle·figure_review)이 읽을 원본 설정은 --env(settings yaml —
# 덮기 파일 가능, 없으면 지금 SETTINGS_FILE·저장소 루트 settings.yaml)이고, 콤보마다 바꾸는 값은 옛 env 이름 사전(names)으로 모아
# 자식에게 덮기 파일(settings.child_env)로 넘긴다. 옛 KEY=VALUE env 파일은 읽지 않는다(migrate 안내 뒤 종료 2).
_BASE = [None]  # --env 설정 파일(절대 경로) — 없으면 지금 설정


def _load_env_file(path):
    """--env(settings yaml) → 자식 실행의 원본 설정으로 잡고, 콤보마다 덮을 칸 사전(빈 사전)을 돌려준다. 값은 출력 안 함."""
    if path:
        p = Path(path).resolve()
        try:
            S.read_settings(p)
        except S.SettingsError as e:
            raise SystemExit(
                f"[e2e] --env는 settings.yaml(S7e2) — 옛 KEY=VALUE env 파일이면 "
                f"python -m common.config.migrate {path} --out <settings.yaml>로 옮긴 뒤 그 파일을 줌 ({str(e).splitlines()[0]})"
            ) from e
        _BASE[0] = p
    return Names()


class Names(dict):
    """자식 실행에 덮을 칸 사전(옛 env 이름 → 글자) — get·setdefault는 사전에 없으면 --env 원본 설정에 준 값을 본다(옛 `dict(os.environ)` +
    env 파일 사본처럼 읽히게). copy()는 같은 꼴로."""

    def get(self, k, default=None):
        if k in self:
            return self[k]
        v = setting(k)
        return default if v is None else v

    def setdefault(self, k, v=None):
        if k not in self and setting(k) is None:
            self[k] = v
        return self.get(k)

    def copy(self):
        return Names(self)


def child_env(names):
    """덮을 칸 사전 → 자식 프로세스 env(--env 원본 위에 덮기 파일 — settings.child_env). 설정 칸이 아닌 이름(PYTHONUTF8 등)은 env에 그대로.
    값은 출력 안 함."""
    base = dict(os.environ)  # env 남김 — 하위 프로세스(자식 env 바탕 — 설정은 SETTINGS_FILE 덮기 파일로)
    if _BASE[0] is not None:
        base["SETTINGS_FILE"] = str(_BASE[0])
    known = S._all_names()
    base.update({k: v for k, v in names.items() if k not in known and v is not None})
    return S.child_env(base, **{k: v for k, v in names.items() if k in known})


def own(name, default=None):
    """이 프로세스 설정(SETTINGS_FILE·로컬 파일 — --env 아님)에 준 옛 env 이름 칸 값(글자 — 비밀 포함, 찍지 말 것), 없으면 default.
    옛 os.environ.get(X) 자리(실험 열쇠·저장소 자리 등 — S7e2)."""
    cls = S.section_class(S.SECTIONS)[0]
    st = _base_settings(cls, None)
    p = S.env_map(cls).get(name)
    if p is None or not S._is_set(st, p):
        return default
    v = S.render(S._get(st, p), secrets=True)
    return default if v is None else v


def setting(name, names=None):
    """옛 env 이름 칸 값(글자, 비밀 포함 — 화면에 찍지 말 것) — names(덮을 칸)에 있으면 그것, 아니면 --env 원본 설정에 준 값, 없으면 None."""
    if names and name in names:
        return names[name]
    cls = S.section_class(S.SECTIONS)[0]
    st = _base_settings(cls, _BASE[0])
    p = S.env_map(cls).get(name)
    if p is None or not S._is_set(st, p):
        return None
    return S.render(S._get(st, p), secrets=True)


_SETTINGS_CACHE: dict = {}


def _base_settings(cls, path):
    """path(None = 지금 설정 — SETTINGS_FILE 신호·put 판에 따라 다시 읽음)로 읽은 설정(캐시)."""
    sig = (
        (os.environ.get("SETTINGS_FILE"), os.environ.get("RUN_ENV"), S._GEN[0]) if path is None else None
    )  # env 남김 — 설정 파일 자리 신호
    key = (cls.__name__, str(path), sig)
    if key not in _SETTINGS_CACHE:
        _SETTINGS_CACHE[key] = S.load(cls, file=path, strict=False, require_file=False, lenient_run_env=True)
    return _SETTINGS_CACHE[key]


def combo_env(config, base_env, combo):
    env = dict(base_env)
    for role in ("llm", "vlm", "embed"):
        _, cands = role_candidates(config, role)
        cand = cands[combo[role]]
        env[config["roles"][role]["env"]["model"]] = cand["model"]
    return env


def _any_truth(config):
    for ds in config.get("reuse_bundles", {}).values():
        for info in ds.values() if isinstance(ds, dict) else ():  # "_주석" 같은 글자 값은 건너뜀
            if isinstance(info, dict) and info.get("truth"):
                return info["truth"]
    return None


def _retrieve_eval(ds, k=10, limit=None):
    from mcp_server.cli import mcp_eval as ME  # S5(Q4 c) — 문항 로더는 mcp_eval로 옮김
    from mcp_server.services.search import search_svc as M  # S5 — do_search는 services/search/search_svc.py(옛 mcp_server.py)

    items = [it for it in ME._load_qa_items(ds) if it["gold_docs"]]
    if limit:
        items = items[:limit]
    rows = []
    for it in items:
        res = M.do_search(it["question"], k, ["vector", "bm25", "id"], False)
        files = {e.get("file_name") for e in (res.get("evidence") or [])[:k]}
        files5 = {e.get("file_name") for e in (res.get("evidence") or [])[:5]}
        rows.append({"id": it["id"], "hit5": bool(it["gold_docs"] & files5), "hit10": bool(it["gold_docs"] & files), "ms": res.get("ms")})
    n = len(rows)
    lat = [r["ms"] for r in rows if r.get("ms") is not None]
    return {
        "dataset": ds,
        "n": n,
        "r5": (sum(r["hit5"] for r in rows) / n) if n else None,
        "r10": (sum(r["hit10"] for r in rows) / n) if n else None,
        "mean_ms": statistics.mean(lat) if lat else None,
        "p90_ms": sorted(lat)[max(0, int(0.9 * len(lat)) - 1)] if lat else None,
        "rows": rows,
    }


def cmd_retrieve_worker(config, a):
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_retrieve_eval(a.dataset, a.k, a.limit), ensure_ascii=False, indent=1), encoding="utf-8")


def _run_retrieval(env, ds, out_path, limit=None):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [PY, "-m", "validation.e2e.model_matrix", "_retrieve", "--dataset", ds, "--out", str(out_path), "--k", "10"]
    if limit:
        args += ["--limit", str(limit)]
    r = subprocess.run(
        args, cwd=APP_ROOT, env=child_env(env), capture_output=True, text=True
    )  # 10-13 — env 상대경로·tools/ 모듈이 루트 기준 · S7e2 덮기 파일
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    return {"error": _scrub(r.stderr[-500:])}


def _run_research(env, ds, out_dir, limit, k):
    """archive됨(S5a 10-26 — 사용자 결정으로 data_retrieval/research.py·cli/eval_research.py 삭제). 예전에는
    eval_research.py를 subprocess로 돌려 요건 재현·근거 적중(research_req_recall·research_evidence_hit)을 냈다.
    예외를 던지면 같은 work의 retrieval·figure_review 결과까지 잃으므로 report=None을 돌려준다 — 아래 집계가
    report None을 건너뛰어 llm 축 research 지표만 빈 값이 된다(검색·그림 검토 축은 그대로)."""
    return {"rc": None, "archived": "eval_research.py 삭제(S5a, 사용자 10-26) — research 지표 없음", "report": None}


def _run_figure_review(env, group, out_dir, limit):
    fr_dir = DEV / "output" / "eval" / "figure_review"
    fr_dir.mkdir(parents=True, exist_ok=True)
    before = set(fr_dir.glob("*.json"))
    args = [PY, "-m", "dev_tools.pipeline_e2e_test.eval_figure_review", "--sets", group, "--limit", str(limit)]
    r = subprocess.run(
        args, cwd=APP_ROOT, env=child_env(env), capture_output=True, text=True
    )  # 10-13 — env 상대경로·tools/ 모듈이 루트 기준 · S7e2 덮기 파일
    new = sorted(set(fr_dir.glob("*.json")) - before)
    report = None
    if new:
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / new[-1].name
        shutil.move(str(new[-1]), str(dest))
        report = json.loads(dest.read_text(encoding="utf-8"))
    return {"rc": r.returncode, "stderr_tail": _scrub(r.stderr[-1000:]) if r.returncode else None, "report": report}


def _changed_datasets(prev_dir, datasets):
    old = {}
    if prev_dir and (prev_dir / "fingerprints.json").exists():
        old = json.loads((prev_dir / "fingerprints.json").read_text(encoding="utf-8"))
    return [d for d in datasets if dataset_fingerprint(d) != old.get(d)]


def _last_run_dir(exclude):
    existing = sorted(p for p in RUN_ROOT.glob("*") if p.is_dir() and p != exclude)
    return existing[-1] if existing else None


def cmd_run(config, a):
    if config.get("design", "ofat") == "staged":
        return cmd_run_staged(config, a)
    return cmd_run_ofat(config, a)


def cmd_run_ofat(config, a):
    run_dir = resolve_run_dir(a, new=True)
    base_env = _load_env_file(a.env)  # S7e2 — 덮을 칸 사전(원본은 --env settings yaml)
    combos = design_combos(config)
    if a.combos:
        want = set(a.combos.split(","))
        combos = [c for c in combos if c["name"] in want]
    datasets = a.datasets.split(",") if a.datasets else all_datasets(config)
    if a.changed_only:
        prev = _last_run_dir(run_dir)
        datasets = _changed_datasets(prev, datasets)
        if not datasets:
            print("[model_matrix run] 지문이 안 바뀐 데이터셋뿐 — 할 일 없음")
            return
        print(f"[model_matrix run] --changed-only: {', '.join(datasets)}만 다시 돈다")
    group = read_split(config)
    research_limit = a.limit if a.limit is not None else config["research_limit"]
    figure_limit = a.limit if a.limit is not None else config["figure_review_limit"]
    from common.ai.guard import check_scope  # AD43 — 조합(combo) 2개 이상 + 외부 주소는 거부(스택 조합별 성능 비교는 서버 내부 모델로)

    check_scope([setting("LLM_BASE_URL"), setting("VLM_BASE_URL"), setting("EMBED_BASE_URL")], n_combos=len(combos))

    def work(combo, ds):
        bi = dataset_bundle(config, run_dir, ds, combo["embed"])
        if not bi:
            return {"combo": combo["name"], "dataset": ds, "status": "skipped", "reason": "묶음 없음 — prepare 먼저"}
        env = combo_env(config, base_env, combo)
        env["MCP_BUNDLE"] = bi["bundle"]  # mc-01 — 저장소는 PG 하나(옛 mcp_store 칸 없음)
        if bi.get("cache"):
            env["EMBED_CACHE"] = bi["cache"]
        env.setdefault(
            "LLM_ALLOW_EXTERNAL", setting("LLM_ALLOW_EXTERNAL") or "1"
        )  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
        env.setdefault(
            "VLM_ALLOW_EXTERNAL", setting("VLM_ALLOW_EXTERNAL") or "1"
        )  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
        env.setdefault(
            "EMBED_ALLOW_EXTERNAL", setting("EMBED_ALLOW_EXTERNAL") or "1"
        )  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
        if bi.get("roster"):
            env["CLIENT_ROSTER"] = bi["roster"]
        env["LLM_CACHE_DIR"] = str(run_dir / "llm_cache" / combo["name"])
        out_base = run_dir / "raw" / combo["name"] / ds
        result = {"combo": combo["name"], "dataset": ds}
        result["retrieval"] = _run_retrieval(env, ds, out_base / "retrieval.json", a.limit)
        if ds in config["research_sets"]:
            result["research"] = _run_research(env, ds, out_base / "research", research_limit, config["research_k"])
        if ds in config["figure_sets"]:
            result["figure_review"] = _run_figure_review(env, group.get(ds, "dev"), out_base / "figure_review", figure_limit)
        return result

    tasks = [(c, d) for c in combos for d in datasets]
    results = []
    workers = a.workers or config.get("workers", 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(work, c, d) for c, d in tasks]
        for fut in concurrent.futures.as_completed(futs):
            results.append(fut.result())
    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "fingerprints.json").write_text(
        json.dumps({d: dataset_fingerprint(d) for d in all_datasets(config)}, indent=1), encoding="utf-8"
    )
    print(f"[model_matrix run] {len(results)}건 → {run_dir}")


def _combo_work_env(config, base_env, run_dir, combo, ds):
    """콤보×데이터셋 공통 env 조립 — ofat·staged 둘 다 씀(묶음 없으면 None)."""
    bi = dataset_bundle(config, run_dir, ds, combo["embed"])
    if not bi:
        return None, None
    env = combo_env(config, base_env, combo)
    env["MCP_BUNDLE"] = bi["bundle"]  # mc-01 — 저장소는 PG 하나
    if bi.get("cache"):
        env["EMBED_CACHE"] = bi["cache"]
    env.setdefault("LLM_ALLOW_EXTERNAL", setting("LLM_ALLOW_EXTERNAL") or "1")  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
    env.setdefault("VLM_ALLOW_EXTERNAL", setting("VLM_ALLOW_EXTERNAL") or "1")  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
    env.setdefault(
        "EMBED_ALLOW_EXTERNAL", setting("EMBED_ALLOW_EXTERNAL") or "1"
    )  # S7e2 — 원본 설정에 준 값이 있으면 그것(옛 env setdefault)
    if bi.get("roster"):
        env["CLIENT_ROSTER"] = bi["roster"]
    return env, bi


def cmd_run_staged(config, a):
    run_dir = resolve_run_dir(a, new=True)
    base_env = _load_env_file(a.env)  # S7e2 — 덮을 칸 사전(원본은 --env settings yaml)
    datasets = a.datasets.split(",") if a.datasets else all_datasets(config)
    group = read_split(config)
    workers = max(1, a.workers or config.get("workers", 2))

    # ── 1단계: embed A/B, retrieval만 ──
    s1_combos = stage1_combos(config)

    def s1_work(combo, ds):
        env, bi = _combo_work_env(config, base_env, run_dir, combo, ds)
        if env is None:
            return {"combo": combo["name"], "dataset": ds, "status": "skipped", "reason": "묶음 없음 — prepare 먼저"}
        out = {"combo": combo["name"], "dataset": ds}
        out["retrieval"] = _run_retrieval(env, ds, run_dir / "raw" / "stage1" / combo["name"] / ds / "retrieval.json", a.limit)
        return out

    tasks1 = [(c, d) for c in s1_combos for d in datasets]
    s1_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(s1_work, c, d) for c, d in tasks1]
        for fut in concurrent.futures.as_completed(futs):
            s1_results.append(fut.result())
    (run_dir / "stage1_results.json").write_text(json.dumps(s1_results, ensure_ascii=False, indent=1), encoding="utf-8")
    winner_embed, winner_scores = _pick_stage1_winner(s1_combos, s1_results, group)
    (run_dir / "stage1_winner.json").write_text(
        json.dumps({"winner": winner_embed, "scores": winner_scores}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[model_matrix run] 1단계 끝 — 승자 embed={winner_embed}")
    for name, s in winner_scores.items():
        print(f"    {name}: dev R@5={s['dev_r5']} · held-out R@5={s['holdout_r5']}")

    if getattr(a, "stage1_only", False):
        (run_dir / "fingerprints.json").write_text(
            json.dumps({d: dataset_fingerprint(d) for d in all_datasets(config)}, indent=1), encoding="utf-8"
        )
        print(f"[model_matrix run] --stage1-only → 2단계 생략. → {run_dir}")
        return

    # ── 2단계: embed=승자 고정, llm×vlm 2x2, repeats(캐시 비움으로 대신) ──
    s2_combos = stage2_combos(config, winner_embed)
    if a.combos:
        want = set(a.combos.split(","))
        filtered = [c for c in s2_combos if c["name"] in want]
        s2_combos = filtered or s2_combos
    stage2_limit = a.limit if a.limit is not None else config["stage2_limit"]
    figure_limit = a.limit if a.limit is not None else config["figure_review_limit"]
    repeats = config["repeats"]
    _, vlm_cands = usable_candidates(config, "vlm")
    from common.ai.guard import check_scope  # AD43 — 2단계 조합(llm×vlm) 2개 이상 + 외부 주소는 거부

    check_scope([setting("LLM_BASE_URL"), setting("VLM_BASE_URL"), setting("EMBED_BASE_URL")], n_combos=len(s2_combos))

    def s2_work(combo, ds, rep):
        env, bi = _combo_work_env(config, base_env, run_dir, combo, ds)
        if env is None:
            return {"combo": combo["name"], "dataset": ds, "repeat": rep, "status": "skipped", "reason": "묶음 없음"}
        # repeats: research()가 온도 0.0 고정 호출(modules/** 밖 — 못 바꿈) → 캐시만 반복마다 새로 둬 재호출되게(cache-bypass, plan 참고)
        env["LLM_CACHE_DIR"] = str(run_dir / "llm_cache" / combo["name"] / f"rep{rep}")
        out_base = run_dir / "raw" / "stage2" / combo["name"] / ds / f"rep{rep}"
        result = {"combo": combo["name"], "dataset": ds, "repeat": rep}
        do_r, do_f = stage2_parts(config, combo)
        if do_r and ds in config["research_sets"]:
            result["research"] = _run_research(env, ds, out_base / "research", stage2_limit, config["research_k"])
        if do_f and ds in config["figure_sets"]:
            result["figure_review"] = _run_figure_review(env, group.get(ds, "dev"), out_base / "figure_review", figure_limit)
        return result

    tasks2 = [(c, d, r) for c in s2_combos for d in datasets for r in range(repeats)]
    s2_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(s2_work, c, d, r) for c, d, r in tasks2]
        for fut in concurrent.futures.as_completed(futs):
            s2_results.append(fut.result())
    (run_dir / "results.json").write_text(json.dumps(s2_results, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "fingerprints.json").write_text(
        json.dumps({d: dataset_fingerprint(d) for d in all_datasets(config)}, indent=1), encoding="utf-8"
    )
    print(f"[model_matrix run] 2단계 끝 — {len(s2_results)}건(repeats={repeats}) → {run_dir}")


# ───────────────────────── report ─────────────────────────
def _extract_metrics(results):
    out = {}
    for r in results:
        combo, ds = r["combo"], r["dataset"]
        m = {}
        ret = r.get("retrieval") or {}
        if ret.get("r5") is not None:
            m["retrieval_r5"], m["retrieval_r10"], m["mean_ms"] = ret.get("r5"), ret.get("r10"), ret.get("mean_ms")
        res = ((r.get("research") or {}).get("report") or {}).get("sets", {}).get(ds)
        if res and "summary" in res:
            sm = res["summary"]
            m["research_req_recall"], m["research_evidence_hit"] = sm.get("req_recall"), sm.get("evidence_hit")
            # research_answer_hit(옛 eval_research --answer 키워드 적중)는 10-13 답변 경로 통일 3단계로 드롭 —
            # 답변 품질은 이제 dev_tools/perform_test/answer_stage/run.py(rag_qa)로, 이 하네스가 대신 받을 때까지 ROLE_METRIC
            # "llm"은 research_evidence_hit(근거 적중)를 임시 대체 지표로 쓴다(약한 proxy — 답 품질이 아니라 검색 품질).
            lats = [it["ms"] for it in (res.get("items") or []) if it.get("ms") is not None]
            if lats:
                m["research_mean_ms"] = statistics.mean(lats)
        fig = (r.get("figure_review") or {}).get("report") or {}
        inj = (fig.get("injection") or {}).get("summary", {}).get(ds)
        if inj:
            m["figure_detection_rate"], m["figure_false_alarm"] = inj.get("detection_rate"), inj.get("false_alarm_rate")
        out[(combo, ds)] = m
    return out


def _role_delta_row(config, role, cand_id, metrics, group, metric, latency_key, combo_name=None, baseline_name="baseline"):
    """combo_name·baseline_name을 안 주면 OFAT 이름("역할=후보")·"baseline" — staged 2단계는 호출 쪽에서 복합 이름
    ("llm=X+vlm=Y")을 넘긴다(같은 델타·갭 계산을 공유)."""
    combo_name = combo_name or f"{role}={cand_id}"

    def avg(combo, g, key):
        vals = [
            metrics[(combo, ds)][key]
            for ds, grp in group.items()
            if grp == g and (combo, ds) in metrics and metrics[(combo, ds)].get(key) is not None
        ]
        return sum(vals) / len(vals) if vals else None

    base_dev, base_hold = avg(baseline_name, "dev", metric), avg(baseline_name, "holdout", metric)
    cand_dev, cand_hold = avg(combo_name, "dev", metric), avg(combo_name, "holdout", metric)
    dev_delta = (cand_dev - base_dev) if (cand_dev is not None and base_dev is not None) else None
    hold_delta = (cand_hold - base_hold) if (cand_hold is not None and base_hold is not None) else None
    gap = (hold_delta - dev_delta) if (dev_delta is not None and hold_delta is not None) else None
    cand_lat, base_lat = avg(combo_name, "dev", latency_key), avg(baseline_name, "dev", latency_key)
    return {
        "role": role,
        "candidate": cand_id,
        "metric": metric,
        "dev_delta": dev_delta,
        "holdout_delta": hold_delta,
        "gap": gap,
        "candidate_latency_ms": cand_lat,
        "baseline_latency_ms": base_lat,
    }


def _recommend(row, epsilon=0.02, gap_floor=-0.10):
    """휴리스틱(스펙 "품질 먼저, 그다음 지연"): 품질이 dev·held-out 모두 기준보다 epsilon 넘게 안 떨어지고
    held-out 갭이 gap_floor보다 낮지 않으면 후보. 품질이 뚜렷이 좋으면(>epsilon) 채택, 동률이면 평균 지연이 더 짧을 때만 채택."""
    dd, hd, gap = row["dev_delta"], row["holdout_delta"], row["gap"]
    if dd is None or hd is None:
        return "데이터 부족 — 보류"
    if dd < -epsilon or hd < -epsilon or (gap is not None and gap < gap_floor):
        return "기준 유지(품질 저하 또는 held-out 갭 과다)"
    if dd > epsilon or hd > epsilon:
        return "채택 후보(품질 우위)"
    lat_c, lat_b = row.get("candidate_latency_ms"), row.get("baseline_latency_ms")
    if lat_c is not None and lat_b is not None and lat_c < lat_b:
        return "채택 후보(품질 동률 · 지연 더 짧음)"
    return "동률 — 기준 유지(지연 이점 없음)"


ROLE_METRIC = {
    "llm": ("research_evidence_hit", "research_mean_ms"),
    "vlm": ("figure_detection_rate", "mean_ms"),
    "embed": ("retrieval_r5", "mean_ms"),
}


def _fmt(v):
    return "n/a" if v is None else f"{v:+.3f}"


def cmd_report(config, a):
    run_dir = resolve_run_dir(a, new=False)
    if (run_dir / "stage1_winner.json").exists():
        return cmd_report_staged(config, a, run_dir)
    return cmd_report_ofat(config, a, run_dir)


def cmd_report_ofat(config, a, run_dir):
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    group = read_split(config)
    metrics = _extract_metrics(results)
    rows = []
    for role in ("llm", "vlm", "embed"):
        baseline_id, cands = usable_candidates(config, role)
        metric, lat_key = ROLE_METRIC[role]
        for cid in sorted(cands):
            if cid == baseline_id:
                continue
            row = _role_delta_row(config, role, cid, metrics, group, metric, lat_key)
            row["recommendation"] = _recommend(row)
            rows.append(row)
    _write_report(run_dir, rows, header=f"# 모델 조합 비교(ofat) — {run_dir.name}")


def _merge_stage2(results):
    """repeats를 (combo, dataset)별로 합친다 — 연구 items는 이어붙이고(McNemar용 원본 보존), figure_review 검출률은
    반복 평균. ponytail: 같은 문항의 반복은 독립 표본이 아니다(의사 반복) — 분산·p값은 근사치, 정밀 추정이 아니다."""
    merged = {}
    for r in results:
        key = (r["combo"], r["dataset"])
        m = merged.setdefault(key, {"research_items": [], "fig_rates": []})
        res = ((r.get("research") or {}).get("report") or {}).get("sets", {}).get(r["dataset"])
        if res and res.get("items"):
            m["research_items"] += res["items"]
        fig = (r.get("figure_review") or {}).get("report") or {}
        inj = (fig.get("injection") or {}).get("summary", {}).get(r["dataset"])
        if inj and inj.get("detection_rate") is not None:
            m["fig_rates"].append(inj["detection_rate"])
    return merged


def _stage2_metrics(merged):
    out = {}
    for key, m in merged.items():
        mm = {}
        items = m["research_items"]
        if items:

            def rate(k):
                vals = [it.get(k) for it in items if it.get(k) is not None]  # noqa: B023 — rate는 같은 반복 안에서만 부름
                return sum(1 for v in vals if v) / len(vals) if vals else None

            mm["research_req_recall"] = rate("req_recall")
            mm["research_evidence_hit"] = rate("evidence_hit")
            lats = [it["ms"] for it in items if it.get("ms") is not None]
            if lats:
                mm["research_mean_ms"] = statistics.mean(lats)
        if m["fig_rates"]:
            mm["figure_detection_rate"] = statistics.mean(m["fig_rates"])
            mm["mean_ms"] = None
        out[key] = mm
    return out


def _paired_hits(items_a, items_b, key):
    """같은 id의 (a적중?, b적중?) 쌍 — repeats로 같은 id가 여러 번 있으면 평균 후 0.5 기준 이진화(근사, _merge_stage2와 같은 단순화)."""

    def agg(items):
        by_id = {}
        for it in items:
            v = it.get(key)
            if v is None:
                continue
            by_id.setdefault(it["id"], []).append(bool(v))
        return {k: (sum(v) / len(v)) >= 0.5 for k, v in by_id.items()}

    a, b = agg(items_a), agg(items_b)
    ids = sorted(set(a) & set(b))
    return [(a[i], b[i]) for i in ids]


def cmd_report_staged(config, a, run_dir):
    rf = run_dir / "results.json"
    results = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else []  # --stage1-only면 2단계 결과 없음
    winner = json.loads((run_dir / "stage1_winner.json").read_text(encoding="utf-8"))
    group = read_split(config)
    base_llm, llm_cands = usable_candidates(config, "llm")
    base_vlm, vlm_cands = usable_candidates(config, "vlm")
    base_name = f"llm={base_llm}+vlm={base_vlm}"
    merged = _merge_stage2(results)
    metrics = _stage2_metrics(merged)
    rows = []
    for role, cands, _other_fixed, metric in (
        ("llm", llm_cands, base_vlm, "research_evidence_hit"),
        ("vlm", vlm_cands, base_llm, "figure_detection_rate"),
    ):
        base_id = base_llm if role == "llm" else base_vlm
        for cid in sorted(cands):
            if cid == base_id:
                continue
            cand_name = f"llm={cid}+vlm={base_vlm}" if role == "llm" else f"llm={base_llm}+vlm={cid}"
            row = _role_delta_row(
                config, role, cid, metrics, group, metric, "research_mean_ms", combo_name=cand_name, baseline_name=base_name
            )
            if role == "llm":  # McNemar·CI는 문항 단위 쌍이 있는 research만(figure_review는 데이터셋당 비율 하나)
                # 10-13 답변 경로 통일 3단계 — keyword_hit(답 정확도)는 answer=True archive로 더는 안 나옴,
                # evidence_hit(근거 적중)로 같은 통계(약한 proxy, 답 품질 아님 — rag_qa 벤치가 대체할 때까지).
                pvals, ci_lo, ci_hi = [], [], []
                for ds in all_datasets(config):
                    ia, ib = merged.get((cand_name, ds), {}).get("research_items"), merged.get((base_name, ds), {}).get("research_items")
                    if not ia or not ib:
                        continue
                    pairs = _paired_hits(ib, ia, "evidence_hit")
                    p = mcnemar_p(pairs)
                    if p is not None:
                        pvals.append(p)
                    cand_vals = [1.0 if v else 0.0 for v in [x.get("evidence_hit") for x in ia] if v is not None]
                    lo, hi = bootstrap_ci(cand_vals)
                    if lo is not None:
                        ci_lo.append(lo)
                        ci_hi.append(hi)
                row["mcnemar_p"] = min(pvals) if pvals else None  # 데이터셋 중 가장 뚜렷한 값(참고용 — 다중비교 보정 없음)
                row["ci95"] = (round(statistics.mean(ci_lo), 3), round(statistics.mean(ci_hi), 3)) if ci_lo else None
            row["recommendation"] = _recommend(row)
            rows.append(row)
    header = f"# 모델 조합 비교(staged) — {run_dir.name} · 1단계 승자 embed={winner['winner']}"
    _write_report(run_dir, rows, header=header, stats=True)


def _write_report(run_dir, rows, header, stats=False):
    (run_dir / "summary.json").write_text(json.dumps({"ts": run_dir.name, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["역할", "후보", "지표", "dev 델타", "held-out 델타", "갭(held-out−dev)"] + (["McNemar p", "95% CI"] if stats else []) + ["추천"]
    md = [header, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in rows:
        cells = [row["role"], row["candidate"], row["metric"], _fmt(row["dev_delta"]), _fmt(row["holdout_delta"]), _fmt(row["gap"])]
        if stats:
            p = row.get("mcnemar_p")
            cells += [("n/a" if p is None else f"{p:.3f}"), ("n/a" if not row.get("ci95") else f"[{row['ci95'][0]},{row['ci95'][1]}]")]
        cells.append(row["recommendation"])
        md.append("| " + " | ".join(cells) + " |")
    w = run_dir / "stage1_winner.json"
    if w.exists():  # 1단계(embed A/B) 표 — 승자는 held-out R@5, 동률이면 dev R@5
        win = json.loads(w.read_text(encoding="utf-8"))
        md += ["", f"## 1단계 embed A/B — 승자 {win.get('winner')}", "", "| embed | dev R@5 | held-out R@5 |", "|---|---|---|"]
        val = lambda x: "n/a" if x is None else f"{x:.3f}"  # 델타가 아니라 값(부호 없음)
        md += [f"| {v.get('embed')} | {val(v.get('dev_r5'))} | {val(v.get('holdout_r5'))} |" for v in (win.get("scores") or {}).values()]
    (run_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\n→ {run_dir / 'summary.json'}")


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")

    sp = sub.add_parser("prepare")
    sp.add_argument("--datasets")
    sp.add_argument("--run-dir")
    sp.add_argument("--build", action="store_true", help="로컬 embed(bge-m3) 묶음을 실제로 지음(없으면 계획만 보여줌)")

    sp = sub.add_parser("run")
    sp.add_argument("--env", help="자식 실행의 원본 settings.yaml(키 포함 — 값은 출력 안 함, S7e2: 옛 KEY=VALUE env 파일은 migrate로 옮김)")
    sp.add_argument("--datasets")
    sp.add_argument("--combos", help="콤보 이름 콤마 목록(기본 전체) — 예: baseline,llm=glm-5.3")
    sp.add_argument("--workers", type=int, default=None)
    sp.add_argument("--run-dir")
    sp.add_argument("--changed-only", action="store_true")
    sp.add_argument("--limit", type=int, default=None, help="research·figure_review·retrieval 문항/그림 수 한도(시험용)")
    sp.add_argument("--stage1-only", action="store_true", help="design=staged일 때 1단계(embed A/B)만 돌리고 끝")

    sp = sub.add_parser("report")
    sp.add_argument("--run-dir")

    sp = sub.add_parser("_retrieve")
    sp.add_argument("--dataset", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--k", type=int, default=10)
    sp.add_argument("--limit", type=int, default=None)

    a = ap.parse_args()
    config = load_config(a.config)
    {"plan": cmd_plan, "prepare": cmd_prepare, "run": cmd_run, "report": cmd_report, "_retrieve": cmd_retrieve_worker}[a.cmd](config, a)


if __name__ == "__main__":
    utf8_stdout()
    main()
