#!/usr/bin/env python3
"""층별 결과 저장·재사용 + 조합 비교 실험 하네스(docs/testing.md) — P1(후보정) × S(구조화) × R(검색) × A(선택, LLM답변).
model_matrix.py와 같은 틀(OFAT: 기준 + 축마다 하나씩 바꾼 조합 + extra) — 모델 이름이 아니라 파이프라인 설정이 축.
모든 모델 이름·경로는 eval/stack_matrix.json에만(이 파일에 적지 않음). 열쇠·코드 지문은 common/artifacts.py(계약).

저장소(EXP_STORE, 기본 dev/out/store): p1/<post cfg>@<fp8>/<데이터셋>/_rep/ · s/<s열쇠8>/<구조 설정>@<fp8>/bundle/ ·
  r/<s열쇠8>/<검색 설정>@<fp8>/<데이터셋>.json — 저장본마다 _manifest.json(parts·code_fp·git commit·생성 시각).
원본 parse_dir(스크래치패드)은 절대 안 건드림 — P1은 미러(하드링크, 안 되면 복사)에서 represent.py를 돌린다.

사용:
  python cli/stack_matrix.py plan                                        # 조합·재사용/빌드·시간 추정(오프라인)
  python cli/stack_matrix.py build [--datasets a,b] [--combos ...] [--with-distractors]   # P1 → S, 없는·낡은 것만
  python cli/stack_matrix.py run --env <.env> [--combos ...] [--limit N] [--allow-stale] [--with-distractors]
  python cli/stack_matrix.py report [--run-dir output/eval/stack_matrix/<ts>]
  python cli/stack_matrix.py audit [--allow-stale]
  python cli/stack_matrix.py selftest

비용 관문(2026-10, OpenRouter 85% 소진 — 유료 호출 전 반드시 이 순서):
  python cli/stack_matrix.py answer --context-only --ks 5,10,15,20,30,50 ...   # LLM 0건 — kw_in_context@k 곡선
  python cli/stack_matrix.py answer --estimate --ks ... --combos ... ...       # LLM_FAKE=1(네트워크 0) — 호출 수·추정 USD
  python cli/stack_matrix.py preflight --env <.env> --combos ... --ks ...      # 문항 3개 드라이런 PASS/FAIL + 추정(위와 같음)
  python cli/stack_matrix.py answer --env <.env> --combos ... --ks ...         # 승인 후 실제 실행(LLM_BUDGET_USD로 상한)

--with-distractors(V11, 백로그): 데이터셋 X의 P1·S 묶음에 source_dataset==X인 방해 문서(valid_env/unstructured/synth-distractors)를
더한다 — 다른 층 열쇠(distractors·distractor_fp)로 저장되어 평소 저장본과 안 섞임. run은 unique_under_distractors==true 문항만
채점하고 방해 문서 오인율(distractor_confusion_rate)을 같이 낸다.

--pool <pool.json>(V11 백로그, valid_env/unstructured/synth-distractors-v2/pool.json): build·run·answer 모두에 — 여러 데이터셋(평가셋
전체 + synth-distractors v1·v2)을 한 S 묶음으로(이름 겹치면 <데이터셋>__ 접두). run은 qa.json 있는 멤버마다 오늘과 같은 모양의 결과 +
synth-distractors-v2 가짜 데이터셋(evidence는 원본 데이터셋) 한 행, 전부에 distractor_confusion(v1)·oldver_confusion(v2, 구판 문서가
정답보다 먼저거나 top10에 낌)을 같이 낸다. answer는 oldver_value_in_answer(구판 금지어가 답에 그대로)도.
"""

import argparse
import contextlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent  # validation/e2e(S6a — 옛 deploy/common_tools/evaluation)
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.core.paths import APP_ROOT, EVAL_SETS_DIR, PROJ_ROOT  # noqa: E402 — 폴더 재편 뒤 이 상수들만 바뀌면 됨 · EVAL_SETS_DIR은 _sets(S5)

CONFIG_PATH = HERE / "stack_matrix.json"  # eval/ -> evaluation/ 이동 뒤 이 파일과 같은 폴더
RUN_ROOT = APP_ROOT / "output" / "eval" / "stack_matrix"
PARSE_RAW_ROOT_DEFAULT = (
    APP_ROOT / "output" / "cache" / "hard_parse"
)  # 아래에 raw/vlm/...가 이미 있음 — .../raw까지 주면 이중 raw/(pipeline/shared/postprocess.py)
PY = sys.executable

from common.config import settings as S  # noqa: E402 — S7e2: 설정은 settings.yaml(이 프로세스 MM.own · 자식은 덮기 파일 MM.child_env)
from common.core import artifacts as A  # noqa: E402
from common.core import resources as RS  # noqa: E402 — CPU·메모리 기준 병렬 수 자동(plan_experiment)
from common.core.paths import resolve_run_dir as _resolve_run_dir  # noqa: E402 — RV6, 아래 resolve_run_dir()이 감쌈
from common.core.text import no_digit_boundary_hit, normalize_value  # noqa: E402 — W20b: score_gold.must_not_hits와 같은 금지 값 경계 검사(공용 규칙 한 곳)
from validation.e2e import model_matrix as MM  # noqa: E402 — env 로딩(비밀값 가림)·eval_set split 읽기·McNemar·부트스트랩 재사용(중복 금지)

AXES = ("post", "chunker", "embed", "chunk_size", "summary", "methods", "rerank", "k")
RECALL_KS = (1, 3, 5, 10, 20, 30, 50)  # 검색 평가는 이 k 전부를 한 번에(최대 = MCP MAX_K 50)
DISTRACTOR_DS = "synth-distractors"  # V11 — targets.json·방해 문서 원본 reuse_bundles 키
DISTRACTOR_V2_DS = "synth-distractors-v2"  # V11 백로그(2026-10-04) — 구판 방해 문서 + "최신 문서 기준" qa.json(evidence는 원본 데이터셋)


def _src(*fns):
    import inspect

    return "".join(inspect.getsource(f) for f in fns)


def eval_fp():
    """평가 코드 지문 — 검색 평가 함수(채점·지표)가 바뀌면 R 열쇠가 바뀌어 다시(10-03 이중 확인: 평가 방식 변경이 저장본에 미반영되던 구멍).
    10-04: 파일 전체 대신 평가 함수 소스만 — 병렬·로그 같은 실행 관리 수정으로 저장된 결과를 다 버리지 않게."""
    import hashlib

    from mcp_server.cli import mcp_eval as ME  # S5(Q4 c) — _raw_qa_items는 mcp_eval로 옮김(함수 안 늦은 import)

    return hashlib.sha256(_src(_retrieve_eval, ME._raw_qa_items, distractor_unique_ids, cmd_retrieve_worker).encode("utf-8")).hexdigest()[
        :8
    ]


def _sub(args, env):
    """하위 프로세스 실행 — 공용 메모리 문(common/resources.gated_popen: 85% 상한, 상한 근처에서만 settle)을 거쳐 띄움(사용자 10-04)."""
    from common.core import resources as RS

    # 10-13 — cwd=APP_ROOT(런타임 루트): env의 상대경로(LLM_SPEND_FILE 등)가
    # 부모와 같은 곳을 가리키게. NM1 뒤 DEV(deploy/common_tools)에서 띄우면 합성 정답을 못 찾아 VLM이 전부 내부망 가드에 막혔음.
    env = MM.child_env(env)  # S7e2 — 덮을 칸 사전 → 자식 env(덮기 파일)
    pr = RS.gated_popen(
        args, cwd=APP_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace"
    )
    out, err = pr.communicate()
    return subprocess.CompletedProcess(args, pr.returncode, out, err)


def qa_fp(ds):
    """채점용 qa.json 지문 — 바뀌면(키워드·동의어 추가 등) 저장된 적중 판정(R·A)을 다시(코디네이터 2026-10-04 지시)."""
    import hashlib

    f = MM.VALID / ds / "qa.json"
    return hashlib.sha256(f.read_bytes()).hexdigest()[:8] if f.exists() else "noqa"


_distractor_cache: dict = {}


def distractor_targets():
    """V11 — synth-distractors/targets.json(문서 source_dataset·질문 unique_under_distractors) 1회 로드 캐시.
    S6a2(10-27) — 상대 `distractors.targets`는 저장소 루트(PROJ_ROOT) 기준(옛 `DEV`(common/) 기준은 저장소 밖이라 늘 빈 값)."""
    if "t" not in _distractor_cache:
        p = PROJ_ROOT / ((_CFG.get("distractors") or {}).get("targets") or "")
        _distractor_cache["t"] = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"documents": [], "questions": []}
    return _distractor_cache["t"]


def distractor_files_for(ds):
    """데이터셋 ds의 방해 문서 파일명(= source_dataset == ds인 targets.json documents[].file)."""
    return {d["file"] for d in distractor_targets()["documents"] if d.get("source_dataset") == ds}


def distractor_unique_ids(ds):
    """방해 문서를 섞어도 정답이 하나로 정해지는 문항 id만(채점 대상 — 나머지는 targets.json에서 이미 빼기로 함)."""
    return {q["id"] for q in distractor_targets()["questions"] if q.get("dataset") == ds and q.get("unique_under_distractors")}


def pool_distractor_files(rename_map):
    """BR42 — 풀(pool.json) 안의 방해 문서 파일명 전체(v1 synth-distractors + v2 구판, 풀 접두 반영) — rename_map의
    키 데이터셋이 DISTRACTOR_DS·DISTRACTOR_V2_DS인 값만 모은다. distractor_files_for(ds)는 ds가 targets.json의
    source_dataset(원 데이터셋, 예 synth-plant)일 때만 맞는 lookup이라 — measure.py의 distractors-v2 풀 행처럼
    ds가 풀 자신의 이름(synth-distractors-v2)이면 늘 빈 집합이 됐다(BR42: frac_distractor_above_gold5 n=0).
    이 함수는 질문의 원 데이터셋과 무관하게 풀 전체 기준(_pool_retrieve_eval의 distractor_confusion·oldver_confusion과
    같은 재료)이라 — 호출부에서 ds를 고를 필요가 없다."""
    return {n for (d, _o), n in (rename_map or {}).items() if d in (DISTRACTOR_DS, DISTRACTOR_V2_DS)}


def distractor_fp(ds=DISTRACTOR_DS):
    """방해 문서 원본 묶음(synth-distractors·기본, v2도 같은 방식) 지문 — src_fp(ds)와 같은 방식, 다시 만들면 바뀜."""
    import hashlib

    reuse = (_CFG.get("reuse_bundles") or {}).get(ds) or {}
    f = Path(reuse.get("parse_dir") or "") / "runs.jsonl"
    return hashlib.sha256(f.read_bytes()).hexdigest()[:8] if f.exists() else "nosrc"


# ───────────────────────── 설정 ─────────────────────────
_CFG: dict = {}
P1_LAYOUT = 4  # P1 저장 형식 — 2(10-03): _images(그림 기록)도 P1에 둠(1은 _rep만이라 그림 청크 0건) · 3: VLM env를 넘겨 다시(2는 VLM 없이 빈 그림 기록)
# · 4(10-04): 미러를 매번 비움(3은 옛 미러의 runs·qa로 represent — 입력 열쇠는 같은데 내용이 틀린 P1이 생겼음)


_REUSE_PATH_KEYS = ("parse_dir", "prepared_dir", "truth", "roster")


def _resolve_reuse_paths(c):
    """D2 — reuse_bundles 경로를 APP_ROOT(런타임 루트, output/이 있는 곳) 기준 절대경로로(상대면 합침, 이미 절대면 그대로 —
    리눅스 절대경로도 그대로 통과). NM1(10-13) 뒤 DEV(=PKG_ROOT, deploy/common_tools)로 풀면 output/store/src가 패키지 안으로 갔음."""
    for entry in (c.get("reuse_bundles") or {}).values():
        if not isinstance(entry, dict):
            continue
        for key in _REUSE_PATH_KEYS:
            v = entry.get(key)
            if v and not Path(v).is_absolute():
                entry[key] = str(APP_ROOT / v)


def load_config(path=CONFIG_PATH):
    c = json.loads(Path(path).read_text(encoding="utf-8"))
    _resolve_reuse_paths(c)
    _CFG.clear()
    _CFG.update(c)
    return c


def src_fp(ds):
    """P1 입력 지문 = 원본 parse_dir의 runs.jsonl 내용(문서×엔진 시도·sha·P0 열쇠 전부) 해시 — 다시 파싱하면 바뀜.
    (10-03 이중 확인: 열쇠에 입력이 없어 3문서짜리 옛 P1을 '재사용'으로 잡던 결함)"""
    import hashlib

    reuse = (_CFG.get("reuse_bundles") or {}).get(ds) or {}
    pd = Path(reuse.get("parse_dir") or "")
    if not (pd / "runs.jsonl").exists():
        return "nosrc"
    h = hashlib.sha256()
    for name in ("runs.jsonl", "qa.json", "route.json", "selection.json"):  # represent가 읽는 입력 전부(parse_qa 결과 qa.json 포함, 10-04)
        f = pd / name
        if f.exists():
            h.update(name.encode() + f.read_bytes())
    return h.hexdigest()[:8]


def store_root(config):
    return Path(MM.own("EXP_STORE") or (APP_ROOT / config.get("store", "output/store"))).resolve()


def _local_embed_available(cand):
    """bge-m3만(스펙 범위) — 패키지 설치 + HF 캐시 존재만 확인(모델 로드 안 함, model_matrix.py와 같은 판정)."""
    if cand["id"] != "bge-m3":
        return False
    try:
        import importlib

        importlib.import_module("sentence_transformers")
    except ImportError:
        return False
    home = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))  # env 남김 — 라이브러리(huggingface 캐시 자리)
    return any(home.glob("hub/models--BAAI--bge-m3"))


def usable_embeds(config):
    out = {}
    for c in config["structure"]["embed_candidates"]:
        if c.get("kind") == "local" and not _local_embed_available(c):
            continue
        out[c["id"]] = c
    return config["structure"]["baseline"]["embed"], out


def store_availability(config):
    """S 저장소(local·pgvector·openviking·lightrag) 가용성 — Docker·패키지 탐지, 설치는 안 함(스펙)."""
    out = {"local": (True, "")}
    try:
        from common.store import services as SV

        ok, why = SV.detect_pg()
    except Exception as ex:
        ok, why = False, f"{type(ex).__name__}: {ex}"
    out["pgvector"] = (ok, "" if ok else (why or config["structure"]["stores"]["pgvector"]["reason_if_unavailable"]))
    try:
        from common.store import services as SV

        ok, why = SV.detect_ov()
    except Exception as ex:
        ok, why = False, f"{type(ex).__name__}: {ex}"
    out["openviking"] = (ok, "" if ok else (why or config["structure"]["stores"]["openviking"]["reason_if_unavailable"]))
    import importlib.util

    has_lr = importlib.util.find_spec("lightrag") is not None
    out["lightrag"] = (has_lr, "" if has_lr else config["structure"]["stores"]["lightrag"]["reason_if_unavailable"])
    return out


# ───────────────────────── OFAT 조합(P1×S×R 축 하나로) ─────────────────────────
def baseline_combo(config):
    s, r = config["structure"]["baseline"], config["retrieve"]["baseline"]
    return {
        "post": config["post"]["baseline"],
        "chunker": s["chunker"],
        "embed": s["embed"],
        "chunk_size": s["chunk_size"],
        "summary": s["summary"],
        "methods": tuple(r["methods"]),
        "rerank": r["rerank"],
        "k": r["k"],
    }


def axis_candidates(config):
    _, embed_usable = usable_embeds(config)
    return {
        "post": [c["id"] for c in config["post"]["candidates"]],
        "chunker": config["structure"]["chunker_candidates"],
        "embed": sorted(embed_usable),
        "chunk_size": config["structure"]["chunk_size_candidates"],
        "summary": config["structure"]["summary_candidates"],
        "methods": [tuple(m) for m in config["retrieve"]["method_candidates"]],
        "rerank": config["retrieve"]["rerank_candidates"],
        "k": config["retrieve"]["k_candidates"],
    }


def _name_val(v):
    return "+".join(v) if isinstance(v, (list, tuple)) else str(v)


def ofat_combos(config):
    base = baseline_combo(config)
    cands = axis_candidates(config)
    combos = [{"name": "baseline", **base}]
    seen = {tuple(base[a] for a in AXES)}
    for axis in AXES:
        for val in cands[axis]:  # 결정적 순서(config에 적힌 순서 그대로 — 해시 순서 의존 없음)
            if val == base[axis]:
                continue
            combo = dict(base)
            combo[axis] = val
            key = tuple(combo[a] for a in AXES)
            if key in seen:
                continue
            seen.add(key)
            combos.append({"name": f"{axis}={_name_val(val)}", **combo})
    for i, patch in enumerate(config.get("extra") or []):
        combo = dict(base)
        combo.update(patch)
        if "methods" in patch:
            combo["methods"] = tuple(patch["methods"])
        key = tuple(combo[a] for a in AXES)
        if key in seen:
            continue
        seen.add(key)
        combos.append({"name": f"extra{i + 1}", **combo})
    return combos


# ───────────────────────── P1: 미러 + represent.py(원본 parse_dir은 안 건드림) ─────────────────────────
def _link_or_copy(src, dst):
    """미러에 복사(하드링크 안 씀) — 10-04 결함: 하드링크한 미러의 runs.jsonl·qa.json에 방해 문서를 덧붙이자 같은 inode인
    원본(dev/out/store/src)까지 오염됨(6세트). 실험이 원본을 절대 바꾸지 못하게 늘 복사(합성 세트라 용량 작음)."""
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def mirror_parse_dir(src, dst):
    """원본 parse_dir(스크래치패드)을 읽기 전용으로 미러(하드링크, 다른 드라이브 등 안 되면 복사).
    represent.py가 쓰는 _rep는 미러 쪽에만 생기고, 원본에는 아무 파일도 더해지지 않는다."""
    src = Path(src)
    for name in ("qa.json", "runs.jsonl", "route.json", "selection.json"):
        f = src / name
        if f.exists():
            _link_or_copy(f, dst / name)
    for d in src.iterdir():
        if d.is_dir() and d.name != "_rep":
            for fp in d.rglob("*"):
                if fp.is_file():
                    _link_or_copy(fp, dst / fp.relative_to(src))


def mirror_distractor_docs(ds, mirror):
    """V11 — 방해 문서(source_dataset==ds) 엔진 결과만 미러에 더하고 qa.json·runs.jsonl에 그 문서 항목을 병합한다
    (X 원본 파일은 안 덮음 — _link_or_copy는 있으면 건너뜀). 멱등: 이미 병합했으면(.distractors_merged) 다시 안 함."""
    marker = mirror / ".distractors_merged"
    if marker.exists():
        return json.loads(marker.read_text(encoding="utf-8"))
    reuse_d = (_CFG.get("reuse_bundles") or {}).get(DISTRACTOR_DS)
    files = distractor_files_for(ds)
    src = Path(reuse_d["parse_dir"]) if reuse_d else None
    if not files or not src or not (src / "qa.json").exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("[]", encoding="utf-8")
        return []
    for d in src.iterdir():  # 엔진 폴더 한 단계만(방해 문서 파싱은 평평한 <엔진>/<파일>.json 구조)
        if d.is_dir() and d.name != "_rep":
            for fp in d.iterdir():
                if fp.is_file() and fp.stem in files:
                    _link_or_copy(fp, mirror / fp.relative_to(src))
    qa_x = json.loads((mirror / "qa.json").read_text(encoding="utf-8"))
    qa_d = json.loads((src / "qa.json").read_text(encoding="utf-8"))
    for doc, dd in qa_d.get("docs", {}).items():
        if doc in files:
            qa_x["docs"][doc] = dd
    (mirror / "qa.json").write_text(json.dumps(qa_x, ensure_ascii=False), encoding="utf-8")
    runs_d = src / "runs.jsonl"
    if runs_d.exists():
        with (mirror / "runs.jsonl").open("a", encoding="utf-8") as f:
            for ln in runs_d.read_text(encoding="utf-8").splitlines():
                if ln.strip() and json.loads(ln).get("doc") in files:
                    f.write(ln + "\n")
    merged = sorted(files)
    marker.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return merged


def vlm_fp():
    """D6 — VLM 모델(+코드에 박힌 지시문 id) 지문 — switch_parts·terms_fp와 같은 방식(이 프로세스 설정만 — S7e2 MM.own, 옛 os.environ).
    PC(OpenRouter)·서버(내부망) 모델이 다르면 P1 경로도 달라져 다른 모델 결과를 조용히 재사용하지 않는다."""
    model = MM.own("VLM_MODEL") or ""
    # 10-13 — 주소·유료 차단도 열쇠에: 막힌 주소(127.0.0.1:0)나 NO_PAID_CALLS=1로 VLM이 다 실패해 그림·쪽이 빈 P1이
    # 같은 모델 이름이라는 이유로 진짜 VLM P1 자리에 재사용되던 것(10-13 재파싱 실측 — 그림 청크 0·스캔 쪽 빈칸).
    reach = f"{MM.own('VLM_BASE_URL') or ''}|nopaid={MM.own('NO_PAID_CALLS') or '0'}"
    try:
        from pipeline.transform.figures.figures import PID_FIG
        from pipeline.transform.figures.vlm_page import PID_PAGE

        prompt = f"{PID_FIG}|{PID_PAGE}"  # 지시문 글자 자체는 code_fp("p1")가 이미 잡지만, id도 명시
    except ImportError:
        prompt = ""
    return A.sha8(f"{model}|{reach}|{prompt}") if (model or prompt) else ""


def p1_dir(store, post_cfg, ds, distractors=False):
    fp8 = A.code_fp("p1")[:8]
    vlm = vlm_fp()
    name = f"{ds}@{src_fp(ds)}"
    if distractors:  # V11 — 다른 열쇠(평소 저장본과 안 섞임), P1_LAYOUT은 안 바꿈
        name += f"+distractors@{distractor_fp()[:8]}"
    cfg_name = f"{post_cfg['id']}@{fp8}L{P1_LAYOUT}" + (f"+vlm{vlm}" if vlm else "")
    return store / "p1" / cfg_name / name


def p1_status(p1t):
    if not (p1t / "_rep" / "index.json").exists():
        return "missing", None
    stale, reason = A.is_stale(p1t)
    return ("stale" if stale else "reused"), reason


def _dataset_source_files(ds):
    """D2 — valid_env/unstructured/<ds> 원본 문서 목록(.json·.md 제외, 폴더는 안 들어감).
    특례: synth-4clients는 manifest.json의 성공(status=ok) 파일 경로만 · docs/ 폴더가 있으면(방해 문서 묶음 등) 그 폴더 그대로."""
    base = MM.VALID / ds
    if ds == "synth-4clients":
        m = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        files = [
            base / it["file"].replace("\\", "/")
            for items in m.get("formats", {}).values()
            for it in items
            if it.get("status") == "ok" and it.get("file")
        ]
        return [f for f in files if f.is_file()]
    docs_dir = base / "docs"
    if docs_dir.is_dir():
        # 10-13 — rglob: docs/ 밑에 포맷별 하위폴더(docs/pdf/·docs/scan_pdf/ 등, synth-4clients-cmp)가 있어도
        # 전부 줍는다. iterdir()은 하위폴더 자체는 집지만 is_file()이 걸러 그 안 파일이 통째로 빠졌었음.
        return sorted(p for p in docs_dir.rglob("*") if p.is_file())
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() not in (".json", ".md"))


def cmd_sources(config, a):
    """D2 — 117 MB P1 원본 저장소(dev/out/store/src) 없이, valid_env/unstructured에서 reuse_bundles 데이터셋을 네이티브로 다시 파싱해 채운다
    (서버는 store/src만 복사 안 받고 이 명령으로 재구성). PARSE_POST=none(원본 엔진 결과만 — 후보정은 stack_matrix가 P1 빌드 때 입힘)."""
    reuse_all = config.get("reuse_bundles") or {}
    names = [d.strip() for d in a.datasets.split(",")] if getattr(a, "datasets", None) else sorted(reuse_all.keys())
    for ds in names:
        reuse = reuse_all.get(ds)
        if not reuse or not isinstance(reuse, dict) or not reuse.get("parse_dir"):
            print(f"  - {ds}: reuse_bundles에 없음 — 건너뜀")
            continue
        parse_dir = Path(reuse["parse_dir"])
        idx = parse_dir / "_rep" / "index.json"
        if idx.exists() and not a.force:
            print(f"  - {ds}: 이미 있음({idx}) — 건너뜀(--force로 다시)")
            continue
        files = _dataset_source_files(ds)
        if not files:
            print(f"  - {ds}: valid_env/unstructured/{ds} 원본 없음 — 건너뜀")
            continue
        out_root = parse_dir.parent  # output/store/src/<ds>/output
        docs_dir = out_root.parent / "docs"  # output/store/src/<ds>/docs
        shutil.rmtree(docs_dir, ignore_errors=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, docs_dir / f.name)
        prepared_dir = Path(reuse.get("prepared_dir") or (out_root / "prepared"))
        env = MM.Names(PARSE_POST="none", PIPE_OUT_ROOT=str(out_root))  # D2 — out 격리(cli/pipeline.py) · S7e2 자식은 덮기 파일
        args = [PY, "-m", "pipeline.cli", "parse", "--source", str(docs_dir), "--src", str(prepared_dir)]
        print(f"[sources] {ds}: {len(files)}개 문서 네이티브 파싱 → {out_root}", flush=True)
        r = _sub(args, env)
        if r.returncode != 0 or not idx.exists():
            print(f"  - {ds}: 실패 — {MM._scrub(((r.stderr or r.stdout) or '')[-2000:])}")
            continue
        truth_path = out_root / "corpus" / "truth.json"
        truth_path.parent.mkdir(parents=True, exist_ok=True)
        truth_path.write_text(
            json.dumps({"_meta": {"synthetic": f"valid_env/unstructured/{ds} — 합성 데이터(외부 모델 시험 허용)"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  - {ds}: 완료 ({idx})")


def build_p1(store, config, post_cfg, ds, mirror_root, base_env=None, distractors=False):
    reuse = config.get("reuse_bundles", {}).get(ds)
    if not reuse or not (Path(reuse["parse_dir"]) / "qa.json").exists():
        return None, "parse 산출물 없음(reuse_bundles에 없음·아직 안 파싱됨) — 건너뜀"
    target = p1_dir(store, post_cfg, ds, distractors)
    status, _ = p1_status(target)
    if status == "reused":
        return target, "reused"
    mirror = mirror_root / "p1" / post_cfg["id"] / (ds + ("+distractors" if distractors else "")) / "parse"
    shutil.rmtree(
        mirror, ignore_errors=True
    )  # 매번 비우고 새로 — 10-04 결함: 이전 빌드의 미러가 남아(있는 파일은 건너뜀) 원본이 바뀌어도 옛 runs·qa로 represent
    mirror.mkdir(parents=True, exist_ok=True)
    mirror_parse_dir(reuse["parse_dir"], mirror)
    if distractors:
        mirror_distractor_docs(ds, mirror)
    env = (
        base_env or MM.Names()
    ).copy()  # --env(VLM 연결)를 그대로 — 10-03 os.environ만 넘겨 VLM 없이 돌아 그림 기록·쪽 옮기기가 빈 채였음(S7e2 — 덮을 칸 사전)
    env.update(post_cfg.get("env") or {})
    uses_vlm = (env.get("PARSE_POST") or "all") != "none"
    if uses_vlm and not (env.get("VLM_BASE_URL") and env.get("VLM_MODEL")):
        return None, "VLM 미설정 — 후보정(그림 기록·쪽 옮기기)이 빈 채로 만들어짐 · --env에 VLM_* 필요(조용한 축소 금지)"
    env.setdefault("PARSE_RAW_ROOT", str(MM.own("PARSE_RAW_ROOT") or PARSE_RAW_ROOT_DEFAULT))
    imgs = mirror / "_images"  # 그림 기록을 이 P1 전용 폴더에(기본 dev/out/parse/_images는 모든 실험이 함께 쓰는 운영 위치)
    shutil.rmtree(imgs, ignore_errors=True)
    env["PARSE_IMAGES_ROOT"] = str(imgs)
    vlm = config.get("post", {}).get("vlm_limits") or {}
    if vlm.get("figures_max") is not None:
        env.setdefault("VLM_FIGURES_MAX", str(vlm["figures_max"]))
    if vlm.get("page_max") is not None:
        env.setdefault("VLM_PAGE_MAX", str(vlm["page_max"]))
    args = [
        PY,
        "-m",
        "pipeline.transform.represent.represent",
        "--parse-dir",
        str(mirror),
        "--src",
        reuse.get("prepared_dir") or reuse["parse_dir"],
        "--stack",
        str(MM.stack_file(config)),
    ]
    r = _sub(args, env)
    rep = mirror / "_rep"
    if r.returncode != 0 or not (rep / "index.json").exists():
        return None, MM._scrub(((r.stderr or r.stdout) or "")[-2000:])
    target.mkdir(parents=True, exist_ok=True)
    rep_target = target / "_rep"
    shutil.rmtree(rep_target, ignore_errors=True)
    shutil.copytree(rep, rep_target)
    img_target = target / "_images"
    shutil.rmtree(img_target, ignore_errors=True)
    if imgs.exists():
        shutil.copytree(imgs, img_target)  # bundle.py는 --parse-dir/_images를 읽음(L1 그림 청크)
    if uses_vlm and (img_target / "index.jsonl").exists():  # 이중 확인 — 그림 기록이 있는데 VLM 내용이 전부 비면 실패로(조용한 축소 금지)
        recs = [json.loads(ln) for ln in (img_target / "index.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        # 10-13 — skipped="page_vlm"은 쪽 VLM이 그 쪽 전체를 옮기도록 넘긴 그림(내용은 _rep 본문에 있음)이라 채워진 것으로 셈 —
        # 전엔 이것만 있는 데이터셋(synth-r2 mail_notice.png)을 실패로 오판해 P1을 버리고 옛 S를 재사용했음.
        # ponytail: 쪽 VLM 자체의 실패는 여기서 안 봄(본문 길이로만 드러남) — 필요하면 _rep post의 vlm_page 오류 수를 같이 확인.
        filled = sum(
            1 for r in recs if (r.get("vlm") or {}).get("summary") or (r.get("vlm") or {}).get("text") or r.get("skipped") == "page_vlm"
        )
        if recs and filled == 0:
            return None, f"그림 기록 {len(recs)}건이 모두 VLM 내용 없음 — VLM 호출 실패·가드 거부 확인(represent 로그)"
    _write_doc_stats(rep_target, target, ds)
    parts = {"post": post_cfg["id"], "env": post_cfg.get("env") or {}, "dataset": ds, "distractors": distractors}
    if distractors:
        parts["distractor_fp"] = distractor_fp()
    A.manifest(target, "p1", parts)
    return target, "built"


def _must_not_violations(ds, rep_dir):
    """W20 — spec.json must_not(그 문서에 없어야 할 값: 다른 문서 값 섞임·VLM 지어냄 흔적)이 P1 대표 글자에 나오면 위반.
    must_not 없는 문서·데이터셋은 그냥 빈 dict(기존 데이터셋은 영향 없음). W20b — score_gold.must_not_hits와 같은
    no_digit_boundary_hit로 판정(예전엔 raw `v in text`라 긴 숫자 안에 짧은 숫자가 끼면 거짓 양성이었음, 독립 검토)."""
    spec_path = MM.VALID / ds / "spec.json"
    if not spec_path.exists():
        return {}
    out = {}
    for d in (json.loads(spec_path.read_text(encoding="utf-8")).get("documents")) or []:
        musts = d.get("must_not") or []
        f = rep_dir / f"{d.get('file')}.json"
        if not musts or not f.exists():
            continue
        text = normalize_value(json.loads(f.read_text(encoding="utf-8")).get("text") or "")
        hit = [m["kw"] for m in musts if any(no_digit_boundary_hit(normalize_value(v), text) for v in m["kw"].split("|"))]
        if hit:
            out[d["file"]] = hit
    return out


def _write_doc_stats(rep_dir, target, ds):
    """문서 × 엔진 × 후보정 설정(git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §8) — represent.py의 index.json을 그대로 옮김.
    fact_hits는 그 자리에 없음(원본 정답 채점은 src/tools/qa/eval_hard_parse.py 몫) — 대표 엔진의 정확도(acc, 교차 재현율 proxy)로 대신.
    W20: spec.json must_not 위반이 있으면 문서 행에 must_not_violations."""
    idx = json.loads((rep_dir / "index.json").read_text(encoding="utf-8"))
    violations = _must_not_violations(ds, rep_dir)
    rows = [
        {
            "doc": r["doc"],
            "format": r.get("format"),
            "engine": r.get("engine"),
            "fact_hits_proxy": r.get("acc"),
            "must_not_violations": violations.get(r["doc"], []),
            "fallback": r.get("fallback"),
            "low_n": r.get("low_n"),
            "errors": [
                {"engine": e, "status": t.get("status"), "error": t.get("error")}
                for e, t in (r.get("tried") or {}).items()
                if t.get("status") != "성공"
            ],
            "ms": {e: round((t.get("sec") or 0) * 1000) for e, t in (r.get("tried") or {}).items()},
        }
        for r in idx.get("docs", [])
    ]
    (target / "doc_stats.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


# ───────────────────────── S: build_bundle.py(공유 embed 캐시) ─────────────────────────
def struct_cfg_name(combo):
    return f"{combo['chunker']}-{combo['embed']}-{combo['chunk_size'] or 'def'}-{combo['summary']}"


def terms_fp():
    """용어 사전(GLOSSARY_DIR) 지문 — 묶음의 개념→청크 역색인(X4)·질문 확장(X3)이 사전에 따라 달라지므로 S·R 열쇠에 넣는다(10-04).
    사전 없음 = "none"(기존 열쇠와 다르지만 의미는 같음 — 한 번만 다시)."""
    import hashlib

    d = MM.own("GLOSSARY_DIR")
    if not d or not Path(d).is_dir():
        return "none"
    h = hashlib.sha256()
    for f in sorted(Path(d).glob("*.csv")):
        h.update(f.name.encode("utf-8") + f.read_bytes())
    return h.hexdigest()[:8]


def _load_env(a):
    """--env(settings yaml — 자식 실행의 원본, S7e2) + 덮을 칸 사전 — 단 비용 관문 스위치(LLM_FAKE·NO_PAID_CALLS·지출 장부·상한)는 이 프로세스
    설정이 이김(10-05 독립 검토: env 파일의 LLM_FAKE= 줄이 강제한 가짜 모드를 조용히 풀 수 있었음)."""
    env = MM._load_env_file(getattr(a, "env", None))
    for k in ("LLM_FAKE", "NO_PAID_CALLS", "LLM_SPEND_FILE", "LLM_BUDGET_USD"):
        if MM.own(k):
            env[k] = MM.own(k)
    return env


def switch_parts():
    """검색·답에 영향을 주는 켬/끔 스위치 — R 열쇠(따로 색인·pool 모두)가 이 한 곳을 씀(10-05 결함: pool 열쇠에 SEARCH_RECENCY가 빠져
    최신본 끔 실행이 켬 결과를 재사용). 새 스위치는 여기에만 추가."""
    return {
        "terms": terms_fp(),
        "query_expand": MM.own("QUERY_EXPAND", "1"),  # X3 질문 확장(10-04) · S7e2 — 이 프로세스 설정(옛 os.environ)
        "recency": MM.own("SEARCH_RECENCY", "1"),  # L3-1 최신본 우선(10-05)
        "struct": MM.own("STRUCT_DB") or MM.own("STRUCT_BACKEND") or "",
    }  # L3-6 정형 저장소 문맥


def s_parts(post_cfg, ds, combo, distractors=False):
    parts = {
        "post": post_cfg["id"],
        "p1_code": A.code_fp("p1")[:8],
        "p1_layout": P1_LAYOUT,
        "src": src_fp(ds),
        "dataset": ds,
        "chunker": combo["chunker"],
        "embed": combo["embed"],
        "chunk_size": combo["chunk_size"],
        "summary": combo["summary"],
        "terms": terms_fp(),
        # D6 — 실제 임베딩 모델·백엔드(이 프로세스 설정만 — MM.own, switch_parts·terms_fp와 같은 방식) — combo["embed"]는 config의 후보 id(예: qwen3-embedding-8b)일
        # 뿐 실제 호출 모델 이름이 아니라서, PC(OpenRouter)·서버(내부망) 모델이 달라도 같은 id면 조용히 재사용되던 것을 막는다.
        "embed_model": MM.own("EMBED_MODEL") or "",
        "pipe_embed": MM.own("PIPE_EMBED") or "",
        "vlm": vlm_fp(),
    }  # 10-13 — P1 경로처럼 S도 VLM 조건별로(빈 VLM P1로 지은 S 재사용 방지)
    if distractors:  # V11 — 평소 저장본과 다른 열쇠
        parts["distractors"], parts["distractor_fp"] = True, distractor_fp()
    return parts


def s_dir(store, post_cfg, ds, combo, distractors=False):
    skey = A.key("s", s_parts(post_cfg, ds, combo, distractors))
    name = struct_cfg_name(combo) + ("+distractors" if distractors else "")
    return store / "s" / skey[:8] / name, skey


def build_s(store, config, p1_target, post_cfg, ds, combo, embed_cands, base_env=None, distractors=False):
    target, skey = s_dir(store, post_cfg, ds, combo, distractors)
    bundle_out = target / "bundle"
    if (bundle_out / "meta.json").exists():
        stale, reason = A.is_stale(target)
        # 10-13 — S 열쇠는 P1 '설정'만 담고 P1 '내용'은 안 담는다: 같은 설정으로 P1을 다시 지었으면(예: VLM 실패분 재빌드)
        # 그보다 오래된 S를 재사용하지 않게 P1 manifest가 더 새로우면 다시.
        p1_man = Path(p1_target) / "_manifest.json"
        if p1_man.exists() and p1_man.stat().st_mtime > (bundle_out / "meta.json").stat().st_mtime:
            stale = True
        if not stale:
            return target, "reused", skey
    cand = embed_cands[combo["embed"]]
    env = (base_env or MM.Names()).copy()
    if combo["chunk_size"]:
        env["CHUNK_SIZE"] = str(combo["chunk_size"])
    env["EMBED_CACHE"] = str(store / "embed_cache.sqlite")  # S 빌드 전체가 공유 — 같은 모델·본문이면 API 재호출 안 함
    reuse = config["reuse_bundles"][ds]
    t0 = time.time()
    args = [
        PY,
        "-m",
        "pipeline.transform.structure.build_bundle",
        "--parse-dir",
        str(p1_target),
        "--src",
        reuse.get("prepared_dir") or reuse["parse_dir"],
        "--embed",
        cand["bundle_embed_arg"],
        "--chunk",
        combo["chunker"],
        "--summary",
        combo["summary"],
        "--stack",
        str(MM.stack_file(config)),
        "--out",
        str(bundle_out),
    ]
    r = _sub(args, env)
    sec = round(time.time() - t0, 1)
    if r.returncode != 0 or not (bundle_out / "meta.json").exists():
        return None, MM._scrub(((r.stderr or r.stdout) or "")[-2000:]), skey
    meta = json.loads((bundle_out / "meta.json").read_text(encoding="utf-8"))
    miss = re.search(r"새로 (\d+)", r.stdout or "")
    stats = {"chunks": meta.get("chunks"), "build_sec": sec, "embed_new_calls": int(miss.group(1)) if miss else None}
    (target / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    A.manifest(target, "s", s_parts(post_cfg, ds, combo, distractors))
    return target, "built", skey


# ───────────────────────── pool: 여러 데이터셋을 한 묶음으로 색인(V11 백로그, distractors-v2) ─────────────────────────
# build --pool <pool.json> · run --pool <pool.json> · answer --pool <pool.json>. pool.json(valid_env/unstructured/synth-distractors-v2/
# pool.json)의 "datasets"가 멤버 — 평가셋(qa.json 있음) + synth-distractors(v1, qa 없음) + synth-distractors-v2(qa 있음, "최신 문서
# 기준" 문항·evidence는 원본 데이터셋). 멤버의 대표 파싱(P1 _rep)을 다시 안 만들고 그대로 모아 S 묶음 하나만 새로 짓는다.
def load_pool(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pool_members(pool):
    return list(pool.get("datasets") or [])


def _pool_member_rep_dir(store, config, post_cfg, ds):
    """멤버의 P1 _rep 폴더 — 방해 문서 가짜 데이터셋(v1·v2)은 reuse_bundles parse_dir의 _rep를 바로 쓰고(이미 PARSE_POST=none으로
    따로 떠 있음 — 다른 세션이 Docker로 만듦), 그 외 평가셋은 보통 p1_dir(post_cfg) 대표 결과. 없으면 None(분명한 건너뜀)."""
    if ds in (DISTRACTOR_DS, DISTRACTOR_V2_DS):
        reuse = (config.get("reuse_bundles") or {}).get(ds) or {}
        d = Path(reuse.get("parse_dir") or "") / "_rep"
    else:
        d = p1_dir(store, post_cfg, ds) / "_rep"
    return d if (d / "index.json").exists() else None


def pool_members_status(store, config, post_cfg, pool):
    present, missing = [], []
    for ds in pool_members(pool):
        (present if _pool_member_rep_dir(store, config, post_cfg, ds) else missing).append(ds)
    return present, missing


def pool_fp(pool_path, post_cfg, members):
    """pool.json 내용 + 정렬된 멤버 P1 열쇠(sha) — pool.json이 바뀌거나 멤버 P1(코드·원본)이 바뀌면 다른 지문.
    방해 문서 가짜 데이터셋(v1·v2)은 reuse_bundles parse_dir 지문(distractor_fp)으로(post_cfg·src_fp가 의미 없음)."""
    import hashlib

    h = hashlib.sha256()
    h.update(Path(pool_path).read_bytes())
    for ds in sorted(members):
        if ds in (DISTRACTOR_DS, DISTRACTOR_V2_DS):
            p1k = distractor_fp(ds)
        else:
            p1k = A.key(
                "p1",
                {
                    "post": post_cfg["id"],
                    "env": post_cfg.get("env") or {},
                    "dataset": ds,
                    "src": src_fp(ds),
                    "layout": P1_LAYOUT,
                    "vlm": vlm_fp(),
                },
            )
        h.update(f"{ds}:{p1k}".encode())
    return h.hexdigest()[:8]


def mirror_pool(store, config, post_cfg, pool, mirror):
    """풀 멤버의 P1 _rep·_images를 한 미러로 합친다(대표 파싱을 다시 안 돌림) — 파일명이 둘 이상 멤버에 겹치면 그 이름을 쓰는
    모든 멤버에서 <데이터셋>__<파일> 접두(대응 표 rename_map으로 정답 문서 추적 유지). 돌려줌: (있는 멤버, 없는 멤버, rename_map)."""
    members = pool_members(pool)
    rep_dirs, present, missing = {}, [], []
    for ds in members:
        d = _pool_member_rep_dir(store, config, post_cfg, ds)
        (present if d else missing).append(ds)
        if d:
            rep_dirs[ds] = d
    member_idx = {ds: (json.loads((rep_dirs[ds] / "index.json").read_text(encoding="utf-8")).get("docs") or []) for ds in present}
    name_owners = {}
    for ds in present:
        for ent in member_idx[ds]:
            name_owners.setdefault(ent["doc"], set()).add(ds)
    collide = {name for name, owners in name_owners.items() if len(owners) > 1}
    shutil.rmtree(mirror, ignore_errors=True)
    rep_out = mirror / "_rep"
    rep_out.mkdir(parents=True, exist_ok=True)
    all_entries, img_lines, rename_map = [], [], {}
    for ds in present:
        rep_dir = rep_dirs[ds]
        img_by = {}
        imgf = rep_dir.parent / "_images" / "index.jsonl"  # bundle.py가 --parse-dir/_images를 읽음(P1 레이아웃과 같은 자리)
        if imgf.exists():
            for ln in imgf.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    img_by.setdefault(r["doc"], []).append(r)
        for ent in member_idx[ds]:
            orig = ent["doc"]
            name = f"{ds}__{orig}" if orig in collide else orig
            rename_map[(ds, orig)] = name
            all_entries.append({**ent, "doc": name})
            src_f = rep_dir / f"{orig}.json"
            if src_f.exists():
                shutil.copy2(src_f, rep_out / f"{name}.json")
            for r in img_by.get(orig, []):
                img_lines.append(json.dumps({**r, "doc": name}, ensure_ascii=False))
    (rep_out / "index.json").write_text(json.dumps({"stack": None, "docs": all_entries}, ensure_ascii=False, indent=1), encoding="utf-8")
    if img_lines:
        img_out = mirror / "_images"
        img_out.mkdir(parents=True, exist_ok=True)
        (img_out / "index.jsonl").write_text("\n".join(img_lines) + "\n", encoding="utf-8")
    return present, missing, rename_map


def load_rename_map_file(path):
    p = Path(path)
    if not p.exists():
        return {}
    return {(d, o): n for d, o, n in json.loads(p.read_text(encoding="utf-8"))}


def pool_s_parts(post_cfg, pool_path, members, combo):
    return {
        "post": post_cfg["id"],
        "p1_code": A.code_fp("p1")[:8],
        "p1_layout": P1_LAYOUT,
        "pool": True,
        "pool_fp": pool_fp(pool_path, post_cfg, members),
        "chunker": combo["chunker"],
        "embed": combo["embed"],
        "chunk_size": combo["chunk_size"],
        "summary": combo["summary"],
        "terms": terms_fp(),
        "vlm": vlm_fp(),
    }


def pool_s_dir(store, post_cfg, pool_path, members, combo):
    skey = A.key("s", pool_s_parts(post_cfg, pool_path, members, combo))
    name = struct_cfg_name(combo) + "+pool"
    return store / "s" / skey[:8] / name, skey


def build_pool_s(store, config, post_cfg, pool, pool_path, combo, embed_cands, base_env=None):
    members = pool_members(pool)
    target, skey = pool_s_dir(store, post_cfg, pool_path, members, combo)
    bundle_out = target / "bundle"
    if (bundle_out / "meta.json").exists():
        stale, reason = A.is_stale(target)
        # 10-14 — build_s와 같은 규칙: 멤버 P1 중 하나라도 이 풀 묶음보다 새로 지어졌으면 다시(실패했던 멤버를 고쳐 다시
        # 지었는데 반쪽 P1로 만든 풀을 재사용하던 것 — synth-distractors-v2 PermissionError 뒤 재빌드에서 실측).
        built_at = (bundle_out / "meta.json").stat().st_mtime
        if any(
            (p1_dir(store, post_cfg, ds) / "_manifest.json").exists()
            and (p1_dir(store, post_cfg, ds) / "_manifest.json").stat().st_mtime > built_at
            for ds in pool_members(pool)
        ):
            stale = True
        if not stale:
            present, missing = pool_members_status(store, config, post_cfg, pool)
            return target, "reused", skey, present, missing
    mirror = store / "_mirror" / "pool" / post_cfg["id"]
    present, missing, rename_map = mirror_pool(store, config, post_cfg, pool, mirror)
    if not present:
        return None, "풀 멤버 전부 P1 없음 — build 먼저(Docker 파싱 대기 포함)", skey, present, missing
    cand = embed_cands[combo["embed"]]
    env = (base_env or MM.Names()).copy()
    if combo["chunk_size"]:
        env["CHUNK_SIZE"] = str(combo["chunk_size"])
    env["EMBED_CACHE"] = str(store / "embed_cache.sqlite")
    empty_src = store / "_mirror" / "pool" / "_src_empty"  # --src는 쓰지 않음(각 멤버 rep.source가 원본 경로·sha를 이미 가짐)
    empty_src.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    args = [
        PY,
        "-m",
        "pipeline.transform.structure.build_bundle",
        "--parse-dir",
        str(mirror),
        "--src",
        str(empty_src),
        "--embed",
        cand["bundle_embed_arg"],
        "--chunk",
        combo["chunker"],
        "--summary",
        combo["summary"],
        "--stack",
        str(MM.stack_file(config)),
        "--out",
        str(bundle_out),
    ]
    r = _sub(args, env)
    sec = round(time.time() - t0, 1)
    if r.returncode != 0 or not (bundle_out / "meta.json").exists():
        return None, MM._scrub(((r.stderr or r.stdout) or "")[-2000:]), skey, present, missing
    meta = json.loads((bundle_out / "meta.json").read_text(encoding="utf-8"))
    miss = re.search(r"새로 (\d+)", r.stdout or "")
    stats = {
        "chunks": meta.get("chunks"),
        "build_sec": sec,
        "embed_new_calls": int(miss.group(1)) if miss else None,
        "members_present": present,
        "members_missing": missing,
    }
    (target / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    (target / "rename_map.json").write_text(
        json.dumps([[d, o, n] for (d, o), n in rename_map.items()], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    A.manifest(target, "s", pool_s_parts(post_cfg, pool_path, members, combo))
    return target, "built", skey, present, missing


# ───────────────────────── R: 검색 평가(별도 프로세스 — MCP 싱글턴이 env를 한 번만 읽음) ─────────────────────────
def r_parts(skey, combo, ds):
    return {
        "s_key": skey,
        "methods": list(combo["methods"]),
        "rerank": combo["rerank"],
        "k": combo["k"],
        "eval": eval_fp(),
        "qa_fp": qa_fp(ds),
        **switch_parts(),
    }


def r_dir(store, skey, combo, ds):
    rkey = A.key("r", r_parts(skey, combo, ds))
    return store / "r" / skey[:8] / f"{'+'.join(combo['methods'])}_{combo['rerank']}_k{combo['k']}@{rkey[:8]}"


def _rank_confusion(ev, cand_files, gold_rank):
    """V11 — 근거 목록(ev, file_name 키)에서 cand_files(방해·구판 문서) 중 가장 앞 순위와, 정답보다 먼저거나
    top10에 끼는지(오인) — distractor_confusion(v1)·oldver_confusion(v2)이 같은 식으로 쓴다."""
    files10 = {e.get("file_name") for e in ev[:10]}
    rank = next((i + 1 for i, e in enumerate(ev) if e.get("file_name") in cand_files), None)
    confusion = bool(rank is not None and (gold_rank is None or rank < gold_rank)) or bool(cand_files & files10)
    return rank, confusion


def _retrieve_eval(ds, methods, limit=None, distractor_files=None, unique_ids=None, items=None, oldver_files=None):
    """R@5·R@10·지연(ms) — do_search(k=10)로 한 번 불러 5·10을 같이 본다(k 축은 manifest에만, 지표는 항상 5·10).
    V11(distractor_files 있으면 unique_ids로 문항을 거르고 방해 문서 오인율을 같이 냄) ·
    W20(문항의 references·expected_attachments가 있으면 근거 적중 ref_hit·attach_hit) ·
    pool(V11 백로그, 2026-10-04): items를 주면(풀 run) ds 자신의 qa.json 대신 그 문항으로(gold_docs는 풀 문서명으로 이미 바뀜) ·
    oldver_files(구판 v2 문서 집합)가 있으면 distractor_confusion과 같은 식으로 oldver_confusion도 같이 냄."""
    from mcp_server.cli import mcp_eval as ME  # S5(Q4 c) — 문항 로더는 mcp_eval로 옮김
    from mcp_server.services.search import search_svc as M  # S5 — do_search는 services/search/search_svc.py(옛 mcp_server.py)

    if items is None:
        items = [it for it in ME._load_qa_items(ds) if it["gold_docs"]]
        if unique_ids is not None:
            items = [it for it in items if it["id"] in unique_ids]
    else:
        items = [it for it in items if it.get("gold_docs")]
    if limit:
        items = items[:limit]
    raw_qa = ME._raw_qa_items(ds)
    # 실험 유효성 점검(10-03 — 원본이 지워진 S3 실행 산출물로 묶음이 3문서뿐이라 R@5 0.15가 나왔던 일): 정답 근거 문서가 묶음에 있는지
    bundle = Path(MM.own("MCP_BUNDLE") or "")
    have = (
        {json.loads(ln).get("file_name") for ln in (bundle / "docs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()}
        if (bundle / "docs.jsonl").exists()
        else set()
    )
    gold = set().union(*[it["gold_docs"] for it in items]) if items else set()
    coverage = (len(gold & have) / len(gold)) if gold else None
    n_fig = (
        sum(1 for ln in (bundle / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip() and '"image_id"' in ln)
        if (bundle / "chunks.jsonl").exists()
        else 0
    )  # 그림 청크 수(후보정 그림 기록이 색인까지 왔는지 — 10-03 0건이었던 일)
    rows = []
    for it in items:
        # 상위 k를 넓게(사용자 10-03): 한 번에 RECALL_KS 최대(기본 50 = MCP_MAX_K)까지 받아 정답 문서 첫 순위를 남기고 R@1·3·5·10·20·30·50을 같이 계산
        res = M.do_search(it["question"], max(RECALL_KS), methods, False)
        ev = res.get("evidence") or []
        files10 = {e.get("file_name") for e in ev[:10]}
        files5 = {e.get("file_name") for e in ev[:5]}
        gold_rank = next((i + 1 for i, e in enumerate(ev) if e.get("file_name") in it["gold_docs"]), None)
        # 비교 보고서(git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §8) — 검색 전용 실행은 hit·top-k 청크 id만 남긴다
        top_chunks = [{"doc": e.get("file_name"), "chunk": e.get("chunk_id")} for e in ev[:10]]
        rr_fallback = any(
            "fallback" in str(x) for x in (res.get("notes") or []) if "재순위" in str(x)
        )  # 리랭크가 대체(시간 초과 등)됐으면 표시
        row = {
            "id": it["id"],
            "gold_rank": gold_rank,
            "n_ev": len(ev),
            "rerank_fallback": rr_fallback,
            "hit5": bool(it["gold_docs"] & files5),
            "hit10": bool(it["gold_docs"] & files10),
            "ms": res.get("ms"),
            "top_chunk_ids": top_chunks,
        }
        if distractor_files:  # V11 — 방해 문서가 모든 정답보다 먼저 나오거나 넘겨준 근거(top10)에 끼면 오인
            row["distractor_rank"], row["distractor_confusion"] = _rank_confusion(ev, distractor_files, gold_rank)
        if oldver_files:  # pool(V11 백로그) — 구판(v2) 문서가 정답보다 먼저거나 top10에 끼면 오인
            row["oldver_rank"], row["oldver_confusion"] = _rank_confusion(ev, oldver_files, gold_rank)
        raw = raw_qa.get(it["id"])
        if raw:  # W20 — 참조 문서·image_id가 top10 근거에 있었나
            ev_images = {img for e in ev[:10] for img in (e.get("image_ids") or [])}
            refs = raw.get("references") or []
            ref_docs = {r["doc"] for r in refs if r.get("doc")}
            ref_images = {r["image_id"] for r in refs if r.get("image_id")}
            ref_hit = bool(ref_docs & files10) if ref_docs else None
            if ref_hit is not None and ref_images:
                ref_hit = ref_hit and bool(ref_images & ev_images)
            row["ref_hit"] = ref_hit
            atts = set(raw.get("expected_attachments") or [])
            row["attach_hit"] = bool(atts & ev_images) if atts else None
        rows.append(row)
    n = len(rows)
    lat = [r["ms"] for r in rows if r.get("ms") is not None]
    out = {
        "dataset": ds,
        "n": n,
        "gold_doc_coverage": coverage,
        "figure_chunks": n_fig,
        "missing_gold_docs": sorted(gold - have)[:20],
        "valid": coverage is not None and coverage >= float(MM.own("MIN_GOLD_COVERAGE") or 0.95),
        "r5": (sum(r["hit5"] for r in rows) / n) if n else None,
        "r10": (sum(r["hit10"] for r in rows) / n) if n else None,
        "recall_at": {str(k): (sum(1 for r in rows if r["gold_rank"] and r["gold_rank"] <= k) / n) if n else None for k in RECALL_KS},
        "mrr": (sum(1 / r["gold_rank"] for r in rows if r["gold_rank"]) / n) if n else None,
        "rerank_fallbacks": sum(1 for r in rows if r.get("rerank_fallback")),
        "mean_ms": statistics.mean(lat) if lat else None,
        "p90_ms": sorted(lat)[max(0, int(0.9 * len(lat)) - 1)] if lat else None,
        "rows": rows,
    }
    if distractor_files is not None:
        conf = [r["distractor_confusion"] for r in rows if "distractor_confusion" in r]
        out["distractor_confusion_rate"] = (sum(conf) / len(conf)) if conf else None
        out["n_distractor_docs"] = len(distractor_files)
    if oldver_files is not None:
        conf2 = [r["oldver_confusion"] for r in rows if "oldver_confusion" in r]
        out["oldver_confusion_rate"] = (sum(conf2) / len(conf2)) if conf2 else None
        out["n_oldver_docs"] = len(oldver_files)
    ref_rows = [r["ref_hit"] for r in rows if r.get("ref_hit") is not None]
    if ref_rows:
        out["ref_hit_rate"] = sum(ref_rows) / len(ref_rows)
    att_rows = [r["attach_hit"] for r in rows if r.get("attach_hit") is not None]
    if att_rows:
        out["attach_hit_rate"] = sum(att_rows) / len(att_rows)
    return out


def cmd_retrieve_worker(config, a):
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    methods = a.methods.split(",")
    distractor_files = distractor_files_for(a.dataset) if a.with_distractors else None
    unique_ids = distractor_unique_ids(a.dataset) if a.with_distractors else None
    out.write_text(
        json.dumps(_retrieve_eval(a.dataset, methods, a.limit, distractor_files, unique_ids), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def _run_retrieval(env, ds, methods, out_path, limit=None, distractors=False):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [PY, "-m", "validation.e2e.stack_matrix", "_retrieve", "--dataset", ds, "--methods", ",".join(methods), "--out", str(out_path)]
    if limit:
        args += ["--limit", str(limit)]
    if distractors:
        args += ["--with-distractors"]
    r = _sub(args, env)
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    return {"error": MM._scrub(((r.stderr or r.stdout) or "")[-500:])}


def run_r(store, config, post_cfg, ds, combo, base_env, s_target, skey, limit=None, distractors=False):
    target = r_dir(store, skey, combo, ds)
    out_file = target / f"{ds}.json"
    if out_file.exists():
        stale, reason = A.is_stale(target)
        if not stale:
            return json.loads(out_file.read_text(encoding="utf-8")), "reused"
    env = base_env.copy()
    env["MCP_BUNDLE"], env["MCP_STORE"] = str(s_target / "bundle"), config.get("mcp_store", "local")
    env["SEARCH_RERANK"] = combo["rerank"]
    env["RERANK_TOP_N"] = str(config["retrieve"].get("rerank_top_n", 30))
    env["RERANK_TIMEOUT_MS"] = str(
        config["retrieve"].get("rerank_timeout_ms", 120000)
    )  # 실험은 넉넉히(CPU 7초/질의 — 3초 기본이면 전부 대체돼 비교 무효였음, 10-03)
    reuse = config.get("reuse_bundles", {}).get(ds) or {}
    if reuse.get("roster"):
        env["CLIENT_ROSTER"] = reuse["roster"]
    result = _run_retrieval(env, ds, list(combo["methods"]), out_file, limit, distractors)
    p1t = p1_dir(store, post_cfg, ds, distractors)  # W20 — must_not 위반을 R 결과에도(파싱 오염이 검색까지 왔는지 한눈에)
    mnv_file = p1t / "doc_stats.json"
    if mnv_file.exists():
        result["must_not_violations"] = {
            r["doc"]: r["must_not_violations"] for r in json.loads(mnv_file.read_text(encoding="utf-8")) if r.get("must_not_violations")
        }
    target.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    A.manifest(target, "r", r_parts(skey, combo, ds))
    return result, "built"


def _pool_retrieve_eval(members, rename_map, methods, limit=None):
    """풀 전체 검색 평가 — qa.json 있는 멤버마다 오늘과 같은 모양의 결과 한 행 + synth-distractors-v2 가짜 데이터셋 한 행
    (evidence는 원본 데이터셋 — gold_docs를 rename_map으로 풀 문서명으로). 전부에 distractor_confusion(v1)·oldver_confusion(v2)을
    풀 안 전체 v1·v2 문서 집합 기준으로 같이 잰다."""
    distractor_files = {n for (d, _o), n in rename_map.items() if d == DISTRACTOR_DS} or None
    oldver_files = {n for (d, _o), n in rename_map.items() if d == DISTRACTOR_V2_DS} or None
    from mcp_server.cli import mcp_eval as ME  # S5(Q4 c) — 문항 로더는 mcp_eval로 옮김

    out = {}
    for ds in members:
        if ds in (DISTRACTOR_DS, DISTRACTOR_V2_DS) or not (MM.VALID / ds / "qa.json").exists():
            continue
        items = ME._remap_items(ME._load_qa_items(ds), ds, rename_map)
        out[ds] = _retrieve_eval(ds, methods, limit, distractor_files, None, items=items, oldver_files=oldver_files)
    if (MM.VALID / DISTRACTOR_V2_DS / "qa.json").exists():
        out[DISTRACTOR_V2_DS] = _retrieve_eval(
            DISTRACTOR_V2_DS, methods, limit, distractor_files, None, items=ME._pool_v2_items(rename_map), oldver_files=oldver_files
        )
    return out


def cmd_retrieve_pool_worker(config, a):
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pool = load_pool(a.pool)
    rename_map = load_rename_map_file(a.rename_map)
    res = _pool_retrieve_eval(pool_members(pool), rename_map, a.methods.split(","), a.limit)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def pool_qa_fp(members):
    """풀 멤버의 qa.json 지문 합(v2 qa.json도 포함) — 채점 기준이 바뀌면(키워드 추가 등) 다시."""
    import hashlib

    h = hashlib.sha256()
    for ds in sorted(set(members) | {DISTRACTOR_V2_DS}):
        f = MM.VALID / ds / "qa.json"
        if f.exists():
            h.update(ds.encode("utf-8") + f.read_bytes())
    return h.hexdigest()[:8]


def pool_r_parts(skey, combo, members):
    return {
        "s_key": skey,
        "pool": True,
        "methods": list(combo["methods"]),
        "rerank": combo["rerank"],
        "k": combo["k"],
        "eval": eval_fp(),
        "pool_qa_fp": pool_qa_fp(members),
        **switch_parts(),
    }


def pool_r_dir(store, skey, combo, members):
    rkey = A.key("r", pool_r_parts(skey, combo, members))
    return store / "r" / skey[:8] / f"{'+'.join(combo['methods'])}_{combo['rerank']}_k{combo['k']}+pool@{rkey[:8]}", rkey


def run_pool_r(store, skey, combo, env, pool_path, members, rename_map_file, limit=None):
    target, rkey = pool_r_dir(store, skey, combo, members)
    out_file = target / "pool.json"
    if out_file.exists():
        stale, _ = A.is_stale(target)
        if not stale:
            return json.loads(out_file.read_text(encoding="utf-8")), "reused", rkey, target
    out_file.parent.mkdir(parents=True, exist_ok=True)
    args = [
        PY,
        "-m",
        "validation.e2e.stack_matrix",
        "_retrieve_pool",
        "--pool",
        str(pool_path),
        "--rename-map",
        str(rename_map_file),
        "--methods",
        ",".join(combo["methods"]),
        "--out",
        str(out_file),
    ]
    if limit:
        args += ["--limit", str(limit)]
    r = _sub(args, env)
    if not out_file.exists():
        return {"error": MM._scrub(((r.stderr or r.stdout) or "")[-500:])}, "error", rkey, target
    res = json.loads(out_file.read_text(encoding="utf-8"))
    A.manifest(target, "r", pool_r_parts(skey, combo, members))
    return res, "built", rkey, target


# ───────────────────────── A: 답 평가(선택, tools/eval_research.py 재사용) ─────────────────────────
def a_parts(rkey, config):
    return {"r_key": rkey, "research_limit": config["llm"]["research_limit"], "research_k": config["llm"]["research_k"]}


def a_dir(store, rkey, config):
    akey = A.key("a", a_parts(rkey, config))
    return store / "a" / rkey[:8] / f"research@{akey[:8]}"


def run_a(store, config, rkey, ds, env, limit=None):
    """archive됨(10-13 답변 경로 통일 3단계) — eval_research.py --answer(이 함수의 유일한 재료)가 archive돼 더는
    답변 채점 행을 못 만든다. `--with-llm`(이 함수의 유일한 호출 경로, cmd_run_pool do_llm)은 이제 바로 거부한다 —
    답변 품질은 dev_tools/perform_test/answer_stage/run.py --real(서빙되는 Answer Agent rag_qa)로 잰다."""
    raise RuntimeError(
        "stack_matrix run --with-llm archive됨(10-13 답변 경로 통일 3단계 — eval_research.py --answer 삭제). "
        "답변 품질은 dev_tools/perform_test/answer_stage/run.py --real(rag_qa, 서빙되는 Answer Agent)로."
    )


# ───────────────────────── plan ─────────────────────────
def cmd_plan_pool(config, a):
    store = store_root(config)
    pool = load_pool(a.pool)
    members = pool_members(pool)
    combos = ofat_combos(config)
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    print(f"# stack_matrix plan --pool {a.pool} — 멤버 {len(members)}개 · 콤보 {len(combos)}개\n")
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        print(f"## {combo['name']}")
        present, _missing = pool_members_status(store, config, post_cfg, pool)
        for ds in members:
            if ds in present:
                note = "P1 있음"
            elif ds == DISTRACTOR_V2_DS:
                note = "P1 없음 — Docker 파싱 대기(reuse_bundles parse_dir에 _rep 없음, 다른 세션 몫)"
            else:
                note = "P1 없음 — build 먼저"
            print(f"  - {ds}: {note}")
        target, _skey = pool_s_dir(store, post_cfg, a.pool, members, combo)
        s_exists = (target / "bundle" / "meta.json").exists()
        print(f"  → 풀 S: {'재사용' if s_exists else '빌드 필요'} ({target})\n")


def cmd_plan(config, a):
    if getattr(a, "pool", None):
        return cmd_plan_pool(config, a)
    store = store_root(config)
    combos = ofat_combos(config)
    group = MM.read_split(config)
    datasets = MM.all_datasets(config)
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    print(f"# stack_matrix plan — 콤보 {len(combos)}개 · 데이터셋 {len(datasets)}개 · EXP_STORE={store}\n")
    print("## S 저장소 가용성(local 고정 + 탐지)")
    for sid, (ok, why) in store_availability(config).items():
        print(f"  - {sid}: {'가능' if ok else '불가 — ' + why}")
    counts = {"p1": {"reused": 0, "build": 0, "stale": 0, "skip": 0}, "s": {"reused": 0, "build": 0, "stale": 0, "skip": 0}}
    print()
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        print(
            f"## {combo['name']}  (post={combo['post']} · chunker={combo['chunker']} · embed={combo['embed']} · "
            f"chunk_size={combo['chunk_size']} · summary={combo['summary']} · methods={'+'.join(combo['methods'])} · "
            f"rerank={combo['rerank']} · k={combo['k']})"
        )
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                print(f"  - {ds}({group.get(ds, '?')}): parse 산출물 없음(reuse_bundles) — 건너뜀")
                continue
            p1t = p1_dir(store, post_cfg, ds)
            p1s, p1reason = p1_status(p1t)
            counts["p1"][{"missing": "build", "stale": "stale", "reused": "reused"}[p1s]] += 1
            st, _ = s_dir(store, post_cfg, ds, combo)
            if (st / "bundle" / "meta.json").exists():
                stale, sreason = A.is_stale(st)
                ss = "stale" if stale else "reused"
            else:
                ss, sreason = "missing", None
            counts["s"][{"missing": "build", "stale": "stale", "reused": "reused"}[ss]] += 1
            print(
                f"  - {ds}({group.get(ds, '?')}): p1={p1s}"
                + (f"({p1reason})" if p1reason else "")
                + f" · s={ss}"
                + (f"({sreason})" if sreason else "")
            )
    lat = config.get("latency", {"p1_sec_per_doc": 2, "s_sec_per_doc": 3, "r_sec_per_query": 0.6})
    n_docs_est = 5  # ponytail: 정확한 문서 수는 build 전엔 qa.json을 열어야 앎 — plan은 대략치(데이터셋당 평균 5문서)만
    p1_sec = counts["p1"]["build"] * n_docs_est * lat.get("p1_sec_per_doc", 2)
    s_sec = counts["s"]["build"] * n_docs_est * lat.get("s_sec_per_doc", 3)
    print(
        f"\n빌드 필요: P1 {counts['p1']['build']}개(낡음 {counts['p1']['stale']}·재사용 {counts['p1']['reused']}) · "
        f"S {counts['s']['build']}개(낡음 {counts['s']['stale']}·재사용 {counts['s']['reused']}) · "
        f"대략 {round((p1_sec + s_sec) / 60, 1)}분(문서당 추정치, API 지연 제외 — 이 plan은 오프라인)"
    )


# ───────────────────────── build ─────────────────────────
def cmd_build_pool(config, a):
    store = store_root(config)
    base_env = _load_env(a)
    pool = load_pool(a.pool)
    combos = ofat_combos(config)
    if a.combos:
        want = set(a.combos.split(","))
        combos = [c for c in combos if c["name"] in want]
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    _, embed_cands = usable_embeds(config)
    report = {}
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        if combo["embed"] not in embed_cands:
            report[combo["name"]] = f"embed {combo['embed']} unavailable"
            print(f"[build --pool] {combo['name']}: embed {combo['embed']} unavailable", flush=True)
            continue
        target, status, skey, present, missing = build_pool_s(store, config, post_cfg, pool, a.pool, combo, embed_cands, base_env)
        report[combo["name"]] = {"status": status, "members_present": present, "members_missing": missing}
        print(f"[build --pool] {combo['name']}: {status} · 있음 {len(present)} · 없음 {missing}", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def cmd_build(config, a):
    if getattr(a, "pool", None):
        return cmd_build_pool(config, a)
    store = store_root(config)
    base_env = _load_env(a)
    combos = ofat_combos(config)
    if a.combos:
        want = set(a.combos.split(","))
        combos = [c for c in combos if c["name"] in want]
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    _, embed_cands = usable_embeds(config)
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    mirror_root = store / "_mirror"
    with_distractors = bool(getattr(a, "with_distractors", False))
    report = {}
    import concurrent.futures

    workers = RS.resolve_workers("build", getattr(a, "workers", "auto") or "auto")
    # 병렬(10-04) — P1(후보정, VLM API 대기)을 (post×데이터셋)마다 먼저, 다 끝나면 S(구조화·임베딩)를 (조합×데이터셋)마다. 메모리 문은 _sub가 지킴
    p1_tasks = [
        (post_by_id[pid], ds) for pid in sorted({c["post"] for c in combos}) for ds in datasets if ds in config.get("reuse_bundles", {})
    ]

    def p1_one(t):
        post_cfg, ds = t
        return ds, post_cfg["id"], build_p1(store, config, post_cfg, ds, mirror_root, base_env, with_distractors)[1]

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for ds, pid, status in ex.map(p1_one, p1_tasks):
            report.setdefault(ds, {})[f"p1:{pid}"] = status
            print(f"[build] p1:{pid} · {ds}: {status}", flush=True)
    heavy = threading.Semaphore(1)  # 로컬 모델(bge-m3 CPU 임베딩)을 올리는 조합은 한 번에 하나만 — 프로세스마다 수 GB

    def s_one(t):
        combo, ds = t
        post_cfg = post_by_id[combo["post"]]
        p1t = p1_dir(store, post_cfg, ds, with_distractors)
        if not (p1t / "_rep" / "index.json").exists():
            return ds, combo["name"], "p1 없음 — 건너뜀"
        if combo["embed"] not in embed_cands:
            return ds, combo["name"], f"embed {combo['embed']} unavailable"
        with heavy if _heavy(combo) else contextlib.nullcontext():
            return ds, combo["name"], build_s(store, config, p1t, post_cfg, ds, combo, embed_cands, base_env, with_distractors)[1]

    s_tasks = [(c, ds) for c in combos for ds in datasets if ds in config.get("reuse_bundles", {})]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for ds, name, status in ex.map(s_one, s_tasks):
            report.setdefault(ds, {})[f"s:{name}"] = status
            print(f"[build] s:{name} · {ds}: {status}", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def _heavy(combo):
    """로컬 모델을 프로세스에 올리는 조합(bge-m3 임베딩·재랭크) — 동시에 여러 개 띄우면 메모리 급증."""
    return combo.get("embed") == "bge-m3" or combo.get("rerank", "off") != "off"


# ───────────────────────── run ─────────────────────────
def resolve_run_dir(a):
    """RV6(10-09) — common/paths.resolve_run_dir로 옮김(동작 그대로, 이 쪽은 늘 new=True)."""
    return _resolve_run_dir(RUN_ROOT, getattr(a, "run_dir", None), new=True)


def _run_meta_row(config, post_cfg, ds, combo, skey, base_env, with_llm):
    """비교 보고서(git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §8) — 층 열쇠·코드 지문·git·모델·데이터셋 지문·split."""
    p1k = A.key("p1", {"post": post_cfg["id"], "env": post_cfg.get("env") or {}, "dataset": ds, "vlm": vlm_fp()})
    rk = A.key("r", r_parts(skey, combo, ds))
    row = {
        "combo": combo["name"],
        "dataset": ds,
        "p1_key": p1k,
        "s_key": skey,
        "r_key": rk,
        "code_fp": {"p1": A.code_fp("p1"), "s": A.code_fp("s"), "r": A.code_fp("r")},
        "git_commit": A._git_commit(),
        "embed_model": base_env.get("EMBED_MODEL") if combo["embed"] != "bge-m3" else "bge-m3",
        "rerank_model": combo["rerank"],
        "dataset_fingerprint": MM.dataset_fingerprint(ds),
        "split": MM.read_split(config).get(ds, "dev"),
    }
    if with_llm:
        row["code_fp"]["a"] = A.code_fp("a")
        row["llm_model"] = base_env.get("LLM_MODEL")
        row["prompt_id"] = None  # modules/search/research.py 프롬프트는 이름 붙은 버전이 아님 — code_fp.a가 바뀌면 지시문이 바뀐 것
    return row


def cmd_run_pool(config, a):
    store = store_root(config)
    base_env = _load_env(a)
    base_env.setdefault("EMBED_QUERY_CACHE", str(store_root(config) / "query_cache.sqlite"))  # 같은 질문 임베딩 재사용(10-04)
    pool = load_pool(a.pool)
    members = pool_members(pool)
    combos = ofat_combos(config)
    if a.combos:
        want = set(a.combos.split(","))
        combos = [c for c in combos if c["name"] in want]
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    run_dir = resolve_run_dir(a)
    from common.ai.guard import check_scope  # AD43 — cmd_run과 같은 가드(풀 조합 비교도 같은 위험)

    check_scope(
        [base_env.get("LLM_BASE_URL"), base_env.get("VLM_BASE_URL"), base_env.get("EMBED_BASE_URL"), base_env.get("RERANK_BASE_URL")],
        n_combos=len(combos),
    )
    results, layers_used, run_meta = [], [], []
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        target, skey = pool_s_dir(store, post_cfg, a.pool, members, combo)
        if not (target / "bundle" / "meta.json").exists():
            results.append({"combo": combo["name"], "pool": True, "status": "skipped", "reason": "풀 S 없음 — build --pool 먼저"})
            continue
        stale, reason = A.is_stale(target)
        if stale and not a.allow_stale:
            raise SystemExit(
                f"[stack_matrix run --pool] {combo['name']}: 풀 S 저장본이 낡음({reason}) — build --pool로 다시 짓거나 --allow-stale"
            )
        layers_used.append({"layer": "s", "dir": str(target), "stale": stale})
        env = base_env.copy()
        env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
        env["SEARCH_RERANK"] = combo["rerank"]
        env["RERANK_TOP_N"] = str(config["retrieve"].get("rerank_top_n", 30))
        env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
        res, status, rkey, r_target = run_pool_r(store, skey, combo, env, a.pool, members, target / "rename_map.json", a.limit)
        layers_used.append({"layer": "r", "dir": str(r_target), "stale": False})
        if isinstance(res, dict) and "error" in res and "retrieval" not in res:
            results.append({"combo": combo["name"], "pool": True, "status": status, "error": res["error"]})
        else:
            for ds, ret in res.items():
                results.append({"combo": combo["name"], "dataset": ds, "pool": True, "status": status, "retrieval": ret})
        run_meta.append(
            {
                "combo": combo["name"],
                "pool": True,
                "pool_path": str(a.pool),
                "s_key": skey,
                "r_key": rkey,
                "code_fp": {"s": A.code_fp("s"), "r": A.code_fp("r")},
                "git_commit": A._git_commit(),
            }
        )
        print(f"[run --pool] {combo['name']}: {status}", flush=True)
    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "layers_used.json").write_text(json.dumps(layers_used, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[stack_matrix run --pool] {len(results)}건 → {run_dir}")


def cmd_run(config, a):
    if getattr(a, "pool", None):
        return cmd_run_pool(config, a)
    store = store_root(config)
    base_env = _load_env(a)
    base_env.setdefault("EMBED_QUERY_CACHE", str(store_root(config) / "query_cache.sqlite"))  # 같은 질문 임베딩 재사용(10-04)
    combos = ofat_combos(config)
    if a.combos:
        want = set(a.combos.split(","))
        combos = [c for c in combos if c["name"] in want]
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    group = MM.read_split(config)
    run_dir = resolve_run_dir(a)
    do_llm = bool(a.with_llm or config["llm"].get("enabled"))
    # AD43 — 축(LLM·post=VLM·embed·rerank) 무관, 이번 실행이 쓰는 외부 주소 전부 + 조합 수로 한 번에(보안 검토 10-07:
    # do_llm만 보면 VLM·EMBED가 외부인 post·embed 축 비교가 새 나감). 전부 내부면 바로 통과.
    from common.ai.guard import check_scope

    check_scope(
        [base_env.get("LLM_BASE_URL"), base_env.get("VLM_BASE_URL"), base_env.get("EMBED_BASE_URL"), base_env.get("RERANK_BASE_URL")],
        n_combos=len(combos),
    )
    with_distractors = bool(getattr(a, "with_distractors", False))
    results, layers_used, run_meta, tasks = [], [], [], []
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                continue
            target, skey = s_dir(store, post_cfg, ds, combo, with_distractors)
            if not (target / "bundle" / "meta.json").exists():
                results.append(
                    {
                        "combo": combo["name"],
                        "dataset": ds,
                        "status": "skipped",
                        "reason": "S 없음 — build 먼저" + (" --with-distractors" if with_distractors else ""),
                    }
                )
                continue
            stale, reason = A.is_stale(target)
            if stale and not a.allow_stale:
                raise SystemExit(f"[stack_matrix run] {combo['name']}/{ds}: S 저장본이 낡음({reason}) — build로 다시 짓거나 --allow-stale")
            layers_used.append({"layer": "s", "dir": str(target), "stale": stale})
            tasks.append((combo, post_cfg, ds, target, skey))

    heavy = threading.Semaphore(1)

    def one(t):
        # (조합 × 데이터셋)마다 별도 프로세스 — 시간 대부분이 API 대기라 병렬로(10-04, 메모리 문은 _sub가 지킴 · 로컬 모델 조합은 한 번에 하나)
        combo, post_cfg, ds, target, skey = t
        out = []
        with heavy if _heavy(combo) else contextlib.nullcontext():
            res, status = run_r(store, config, post_cfg, ds, combo, base_env, target, skey, a.limit, with_distractors)
        row = {"combo": combo["name"], "dataset": ds, "group": group.get(ds, "dev"), "status": status, "retrieval": res}
        if with_distractors:
            row["distractors"] = True
        ds_llm = do_llm and ds in config.get("research_sets", [])
        if ds_llm:
            env = base_env.copy()
            env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
            env["SEARCH_RERANK"] = combo["rerank"]
            env["RERANK_TOP_N"] = str(config["retrieve"].get("rerank_top_n", 30))
            env["RERANK_TIMEOUT_MS"] = str(
                config["retrieve"].get("rerank_timeout_ms", 120000)
            )  # 실험은 넉넉히(CPU 7초/질의 — 3초 기본이면 전부 대체돼 비교 무효였음, 10-03)
            rk = A.key("r", r_parts(skey, combo, ds))
            a_res, a_status = run_a(store, config, rk, ds, env, a.limit)
            row["answer"] = a_res
            out.append({"layer": "a", "dir": str(a_dir(store, rk, config)), "stale": False})
        print(f"[run] {combo['name']} · {ds}: {status} · R@5 {(res or {}).get('r5')}", flush=True)
        return row, _run_meta_row(config, post_cfg, ds, combo, skey, base_env, ds_llm), out

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=RS.resolve_workers("run", a.workers)) as ex:
        for row, meta, used in ex.map(one, tasks):
            results.append(row)
            run_meta.append(meta)
            layers_used += used
    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "layers_used.json").write_text(json.dumps(layers_used, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[stack_matrix run] {len(results)}건 → {run_dir}")


# ───────────────────────── report ─────────────────────────
def _row_metrics(results):
    out = {}
    for r in results:
        ret = r.get("retrieval") or {}
        if ret.get("r5") is not None and ret.get("valid", True):  # 정답 문서가 묶음에 95% 미만이면 순위에서 뺌(무효 — report에 따로 표시)
            out[(r["combo"], r["dataset"])] = {
                "r5": ret["r5"],
                "r10": ret.get("r10"),
                "mean_ms": ret.get("mean_ms"),
                "rows": ret.get("rows") or [],
            }
    return out


def _avg(metrics, combo, ds_group, group, key):
    vals = [
        metrics[(combo, ds)][key]
        for ds, g in group.items()
        if g == ds_group and (combo, ds) in metrics and metrics[(combo, ds)].get(key) is not None
    ]
    return sum(vals) / len(vals) if vals else None


def _paired(metrics, base_combo, cand_combo, group, ds_group, hit_key):
    pairs = []
    for ds, g in group.items():
        if g != ds_group or (base_combo, ds) not in metrics or (cand_combo, ds) not in metrics:
            continue
        b_rows = {r["id"]: r[hit_key] for r in metrics[(base_combo, ds)]["rows"]}
        c_rows = {r["id"]: r[hit_key] for r in metrics[(cand_combo, ds)]["rows"]}
        for qid in sorted(set(b_rows) & set(c_rows)):
            pairs.append((b_rows[qid], c_rows[qid]))
    return pairs


def _diff_ci(pairs, resamples=2000, seed=0):
    """짝지은 (기준 적중?, 후보 적중?) → 적중률 차(후보−기준)의 95% 부트스트랩 CI — 같은 재추출 인덱스로 짝을 지킨다(MM.bootstrap_ci는 단일 목록용, 이건 짝 차용이라 새로 둠)."""
    if not pairs:
        return None, None
    import random

    rng = random.Random(seed)
    n = len(pairs)
    diffs = sorted(
        sum((1.0 if pairs[rng.randrange(n)][1] else 0.0) - (1.0 if pairs[rng.randrange(n)][0] else 0.0) for _ in range(n)) / n
        for _ in range(resamples)
    )
    return diffs[int(0.025 * resamples)], diffs[min(resamples - 1, int(0.975 * resamples))]


def _ranking(metrics, group, combos):
    """순위(git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §2) — 1차 holdout R@5, 동률 dev R@5. 1위와 McNemar p≥0.05 이고
    적중률 차 95% CI가 0을 포함하면 '1위와 통계적으로 구분 안 됨' → Top3는 그대로, 그 뒤는 동급일 때만 Top10까지."""
    scored = []
    for c in combos:
        dev, hold = _avg(metrics, c["name"], "dev", group, "r5"), _avg(metrics, c["name"], "holdout", group, "r5")
        scored.append(
            {"combo": c["name"], "dev_r5": dev, "holdout_r5": hold, "latency_ms": _avg(metrics, c["name"], "dev", group, "mean_ms")}
        )
    scored.sort(
        key=lambda r: (r["holdout_r5"] if r["holdout_r5"] is not None else -1, r["dev_r5"] if r["dev_r5"] is not None else -1), reverse=True
    )
    if not scored:
        return []
    top_name = scored[0]["combo"]
    out = []
    for i, row in enumerate(scored):
        if row["combo"] == top_name:
            p, ci, equiv = 1.0, (0.0, 0.0), True
        else:
            pairs = _paired(metrics, top_name, row["combo"], group, "dev", "hit5") + _paired(
                metrics, top_name, row["combo"], group, "holdout", "hit5"
            )
            p = MM.mcnemar_p(pairs) if pairs else None
            ci = _diff_ci(pairs)
            equiv = bool(pairs) and p is not None and p >= 0.05 and ci[0] is not None and ci[0] <= 0 <= ci[1]
        out.append(
            {
                "rank": i + 1,
                **row,
                "mcnemar_p_vs_top": p,
                "ci95_diff_vs_top": (round(ci[0], 3), round(ci[1], 3)) if ci and ci[0] is not None else None,
                "equivalent_to_top": equiv,
            }
        )
    kept = out[:3]
    for row in out[3:10]:
        if not row["equivalent_to_top"]:
            break
        kept.append(row)
    return kept


def cmd_report(config, a):
    run_dir = Path(a.run_dir) if a.run_dir else sorted(RUN_ROOT.glob("*"))[-1]
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    layers_used = json.loads((run_dir / "layers_used.json").read_text(encoding="utf-8")) if (run_dir / "layers_used.json").exists() else []
    run_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8")) if (run_dir / "run_meta.json").exists() else []
    group = MM.read_split(config)
    metrics = _row_metrics(results)
    ranking = _ranking(metrics, group, ofat_combos(config))
    rows = []
    for axis in AXES:
        for combo in ofat_combos(config):
            if not combo["name"].startswith(f"{axis}="):
                continue
            base_dev, cand_dev = _avg(metrics, "baseline", "dev", group, "r5"), _avg(metrics, combo["name"], "dev", group, "r5")
            base_hold, cand_hold = _avg(metrics, "baseline", "holdout", group, "r5"), _avg(metrics, combo["name"], "holdout", group, "r5")
            dev_delta = (cand_dev - base_dev) if (cand_dev is not None and base_dev is not None) else None
            hold_delta = (cand_hold - base_hold) if (cand_hold is not None and base_hold is not None) else None
            pairs = _paired(metrics, "baseline", combo["name"], group, "dev", "hit5") + _paired(
                metrics, "baseline", combo["name"], group, "holdout", "hit5"
            )
            p = MM.mcnemar_p(pairs) if pairs else None
            cand_vals = [1.0 if v else 0.0 for _, v in pairs]
            ci = MM.bootstrap_ci(cand_vals) if cand_vals else (None, None)
            rows.append(
                {
                    "axis": axis,
                    "combo": combo["name"],
                    "metric": "r5",
                    "dev_delta": dev_delta,
                    "holdout_delta": hold_delta,
                    "mcnemar_p": p,
                    "ci95": (round(ci[0], 3), round(ci[1], 3)) if ci[0] is not None else None,
                    "candidate_latency_ms": _avg(metrics, combo["name"], "dev", group, "mean_ms"),
                    "baseline_latency_ms": _avg(metrics, "baseline", "dev", group, "mean_ms"),
                }
            )
    stale_layers = [u for u in layers_used if u.get("stale")]
    fmt = lambda v: "n/a" if v is None else (f"{v:+.3f}" if isinstance(v, float) and abs(v) < 2 else f"{v}")
    header = [
        f"# stack_matrix 비교 — {run_dir.name}",
        "",
        f"층 열쇠 사용: {len(layers_used)}개" + (f" · **낡은 저장본 {len(stale_layers)}개 사용됨**" if stale_layers else ""),
    ]
    rcols = ["순위", "콤보", "holdout R@5", "dev R@5", "1위 대비 McNemar p", "1위 대비 차 95% CI", "지연ms", "1위와 동급"]
    md = header + [
        "",
        "## 순위(Top3, 1위와 통계적으로 구분 안 되면 Top10까지)",
        "",
        "| " + " | ".join(rcols) + " |",
        "|" + "---|" * len(rcols),
    ]
    for row in ranking:
        md.append(
            "| "
            + " | ".join(
                [
                    str(row["rank"]),
                    row["combo"],
                    fmt(row["holdout_r5"]),
                    fmt(row["dev_r5"]),
                    ("n/a" if row["mcnemar_p_vs_top"] is None else f"{row['mcnemar_p_vs_top']:.3f}"),
                    ("n/a" if not row["ci95_diff_vs_top"] else f"[{row['ci95_diff_vs_top'][0]},{row['ci95_diff_vs_top'][1]}]"),
                    fmt(row["latency_ms"]),
                    ("예" if row["equivalent_to_top"] else ""),
                ]
            )
            + " |"
        )
    cols = ["축", "콤보", "지표", "dev 델타", "held-out 델타", "McNemar p", "95% CI", "후보 지연ms", "기준 지연ms"]
    md += ["", "## 축별 기여(기준 대비 하나씩 바꾼 차)", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in rows:
        md.append(
            "| "
            + " | ".join(
                [
                    row["axis"],
                    row["combo"],
                    row["metric"],
                    fmt(row["dev_delta"]),
                    fmt(row["holdout_delta"]),
                    ("n/a" if row["mcnemar_p"] is None else f"{row['mcnemar_p']:.3f}"),
                    ("n/a" if not row["ci95"] else f"[{row['ci95'][0]},{row['ci95'][1]}]"),
                    fmt(row["candidate_latency_ms"]),
                    fmt(row["baseline_latency_ms"]),
                ]
            )
            + " |"
        )
    if stale_layers:
        md += ["", "## 낡은 저장본으로 만든 결과"] + [f"- {u['dir']}" for u in stale_layers]
    invalid = [
        {
            "combo": r["combo"],
            "dataset": r["dataset"],
            "coverage": (r.get("retrieval") or {}).get("gold_doc_coverage"),
            "missing": (r.get("retrieval") or {}).get("missing_gold_docs"),
        }
        for r in results
        if (r.get("retrieval") or {}).get("valid") is False
    ]
    if invalid:  # 이중 확인 — 묶음에 정답 문서가 빠진 실행은 순위에서 빠졌음을 드러냄
        md += ["", "## 무효(정답 근거 문서가 묶음에 95% 미만 — 순위에서 제외)"] + [
            f"- {x['combo']} · {x['dataset']} · 포함 {x['coverage']} · 빠진 예 {x['missing'][:3]}" for x in invalid
        ]
    (run_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(
            {"ranking": ranking, "rows": rows, "stale_layers": stale_layers, "run_meta": run_meta, "invalid": invalid},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("\n".join(md))
    print(f"\n→ {run_dir / 'summary.json'}")


# ───────────────────────── audit ─────────────────────────
def _leaf_dirs(base):
    for d in base.rglob("*"):
        if d.is_dir() and d.name not in ("bundle", "_rep") and not any(c.is_dir() for c in d.iterdir()):
            yield d


def cmd_audit(config, a):
    store = store_root(config)
    print(f"# stack_matrix audit — {store}\n")
    for layer in ("p0", "p1", "s", "r", "a"):
        base = store / layer
        if not base.exists():
            continue
        for mf in sorted(base.rglob("_manifest.json")):
            d = mf.parent
            stale, reason = A.is_stale(d)
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            print(f"  [{'낡음' if stale else '최신'}] {layer} {d} ({size / 1e6:.1f}MB)" + (f" — {reason}" if stale else ""))
        orphans = [d for d in _leaf_dirs(base) if not (d / "_manifest.json").exists()]
        for d in orphans:
            print(f"  [고아] {layer} {d} — _manifest.json 없음")
    runs = sorted(RUN_ROOT.glob("*")) if RUN_ROOT.exists() else []
    stale_used = False
    if runs:
        lu = runs[-1] / "layers_used.json"
        if lu.exists():
            used = json.loads(lu.read_text(encoding="utf-8"))
            stale_used = any(u.get("stale") for u in used)
            if stale_used:
                print(f"\n최근 run({runs[-1].name})이 낡은 저장본을 씀 — report·run을 --allow-stale 없이 다시 돌려 거부되는지 확인:")
                for u in used:
                    if u.get("stale"):
                        print(f"  - {u['dir']}")
    if stale_used and not a.allow_stale:
        sys.exit(1)


# ───────────────────────── 답 평가(운영 ask 경로: 검색 k개 → LLM 1회) ─────────────────────────
# 평가 세트 목록(S5 10-26 — VS5a R-2·코디네이터 답 Q8 a: 이 파일만 써서 mcp_eval에서 바이트 그대로 되돌림, 원래 S5a에 옛 cli/eval_research.py에서 옮긴 것)
def _sets():
    """평가 세트 = synth-4clients(dev, 고유 형식) + valid_env/unstructured/eval_set.json의 split(dev·holdout) — 새 세트가 추가되면 자동으로(10-03)."""
    sets = {"synth-4clients": {"base": EVAL_SETS_DIR / "synth-4clients", "kind": "4clients", "group": "dev"}}
    f = EVAL_SETS_DIR / "eval_set.json"
    split = json.loads(f.read_text(encoding="utf-8")).get("split", {}) if f.exists() else {}
    for name, grp in split.items():
        sets[name] = {"base": EVAL_SETS_DIR / name, "kind": "images", "group": "held-out" if grp == "holdout" else "dev"}
    return sets


SETS = _sets()


# 조합 비교 보고서(git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §2)의 1차 기준 = 질문 단위 정답률.
# research(요건 분해 루프)는 문항당 LLM 5~6회라 비교 실험에는 운영 질의(cli/pipeline.py ask)와 같은 1회 답변을 쓴다(옆 세션 기준선과 같은 방식).
def _answer_items(ds):
    from mcp_server.cli import mcp_eval as ME  # 질문·정답 근거·채점 함수(읽기 전용 재사용 — S5a에 옛 cli/eval_research.py에서 옮김)

    meta = SETS.get(ds)
    if not meta:
        return [], None, None
    raw = {q["id"]: q for q in json.loads((meta["base"] / "qa.json").read_text(encoding="utf-8")).get("items", [])}
    items = (ME.load_4clients if meta["kind"] == "4clients" else ME.load_images_like)(meta["base"], None)
    return items, raw, meta["kind"]


def _answer_eval(ds, methods, ks, limit=None, workers=4, with_distractors=False, items_override=None, score_mode=None, context_only=False):
    """질문마다 운영 Retriever.search(q, k) → kw_in_context@k(잘린 근거에 정답이 있나) — k 곡선을 공짜로(LLM 호출 0).
    비용 관문(2026-10): ks(목록) 전부를 질문당 검색 1회로 — R.search(q, max(ks))를 한 번만 부르고 그 결과를 각 k로 자른다
    (검색 결과는 상위부터 순서가 고정이라 max(ks) 결과의 앞 k개 = k로 직접 부른 결과, rerank 꺼짐 기준 — cli/stack_matrix.py selftest).
    기존처럼 k마다 R.search를 다시 부르던 것(임베딩·검색 중복)을 없앰. 반환은 {str(k): 결과, ...}.
    context_only는 항상 True로 다룬다 — 10-13 답변 경로 통일 2단계로 LLM 답변 채점 분기(pipeline.answer_prompt →
    L.chat(agent="answer_compose"))를 archive로 보냈다(답변 품질은 이제 dev_tools/perform_test/answer_stage/run.py --real,
    서빙되는 Answer Agent rag_qa로만 잰다 — 중복 경로 제거). context_only=False로 부르면 바로 거부한다(아래).
    코디네이터 수정(2026-10-04): synth-images류(kind=="images")는 score_fn이 아니라 _synth_images_qa.score를 attachments와
    함께 직접 불러 채점한다 — expected_attachments가 있는 문항이 첨부 없이 늘 오답으로 나오던 문제(score_fn(ans)만 쓰면
    attachments=() 고정이라 못 맞춤). attachments = 근거로 준 그림 청크의 image_id(bundle chunks.jsonl에서 chunk_ref로 찾음).
    V11: with_distractors면 unique_under_distractors 문항만.
    pool(V11 백로그, 2026-10-04): items_override를 주면(synth-distractors-v2 가짜 데이터셋) _answer_items(ds) 대신 그 문항을 쓰고
    score_mode="pool_kw"면 _synth_images_qa.score(item, answer)로 채점(answer_keywords·forbid_keywords)."""
    import concurrent.futures

    from common.core.contract import jl as _jl
    from mcp_server.cli import mcp_eval as ME
    from mcp_server.services.search import server_state as M  # S5 — _retriever는 services/search/server_state.py

    if not context_only:
        raise RuntimeError(
            "_answer_eval(context_only=False) archive됨(10-13 답변 경로 통일 2단계 — pipeline.answer_prompt·"
            'aggregate.answer_aggs·agent="answer_compose" 삭제). 답변 품질은 dev_tools/perform_test/answer_stage/run.py '
            "--real(rag_qa, 서빙되는 Answer Agent)로 — 이 함수는 context_only=True(kw_in_context@k)만 지원한다."
        )
    ks = sorted(set(ks))
    max_k = max(ks)
    if items_override is not None:
        items, raw_by_id, kind = items_override, {it["id"]: it for it in items_override}, score_mode
    else:
        items, raw_by_id, kind = _answer_items(ds)
        items = [it for it in items if it.get("score_fn")]
        if with_distractors:
            uniq = distractor_unique_ids(ds)
            items = [it for it in items if it["id"] in uniq]
    items = items[: limit or None]
    R = M._retriever()
    bundle = MM.own("MCP_BUNDLE")
    chunks = _jl(Path(bundle) / "chunks.jsonl") if bundle and (Path(bundle) / "chunks.jsonl").exists() else []

    def one(it):
        hits_all, _ms = R.search(it["question"], max_k, methods)  # 질문당 검색 1회 — 아래에서 k마다 앞부분만 자름
        by_k = {}
        for k in ks:
            hits = hits_all[:k]
            ctx = "\n".join(h.get("text") or "" for h in hits)
            files = [Path(h.get("file_path") or "").name for h in hits]
            atts = sorted(
                {
                    chunks[h["chunk_ref"]]["image_id"]
                    for h in hits
                    if h.get("chunk_ref") is not None and 0 <= h["chunk_ref"] < len(chunks) and chunks[h["chunk_ref"]].get("image_id")
                }
            )
            raw_it = raw_by_id.get(it["id"]) if raw_by_id else None
            if kind == "pool_kw":  # pool — synth-distractors-v2(answer_keywords·forbid_keywords)
                kw_in_context = bool(ME.synth_score(it, ctx))
            elif kind == "images" and raw_it is not None:
                kw_in_context = bool(ME.synth_score(raw_it, ctx, atts))
            else:
                kw_in_context = bool(it["score_fn"](ctx))  # 넣어 준 근거에 정답이 있었나(R1 검색 실패 vs G1 답변 실패 가름)
            row = {
                "id": it["id"],
                "kw_in_context": kw_in_context,
                "evidence_hit": bool(it["gold_docs"] & set(files)) if it.get("gold_docs") else None,
            }
            by_k[k] = row  # context_only만 지원(위 가드) — LLM 답변 채점 분기는 archive됨
        return by_k

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        per_item = list(ex.map(one, items))
    result = {}
    for k in ks:
        rows = [by_k[k] for by_k in per_item]
        n = len(rows)
        acc = lambda key: (sum(1 for r in rows if r[key]) / n) if n else None  # noqa: B023 — 같은 반복 안에서만 부름
        result[str(k)] = {"dataset": ds, "k": k, "n": n, "kw_in_context": acc("kw_in_context"), "rows": rows}
    return result


def cmd_answer_worker(config, a):
    from common.ai import llm as L

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ks = [int(x) for x in a.ks.split(",")]
    if getattr(a, "pool_v2", False):  # pool — synth-distractors-v2 가짜 데이터셋(_answer_items의 ME.SETS에 없음)
        from mcp_server.cli import mcp_eval as ME  # S5(Q4 c) — _pool_v2_items는 mcp_eval로 옮김

        rename_map = load_rename_map_file(a.rename_map) if a.rename_map else {}
        by_k = _answer_eval(
            a.dataset,
            a.methods.split(","),
            ks,
            a.limit,
            a.workers,
            items_override=ME._pool_v2_items(rename_map),
            score_mode="pool_kw",
            context_only=a.context_only,
        )
    else:
        by_k = _answer_eval(a.dataset, a.methods.split(","), ks, a.limit, a.workers, a.with_distractors, context_only=a.context_only)
    out.write_text(json.dumps({"usage": L.usage(), "by_k": by_k}, ensure_ascii=False, indent=1), encoding="utf-8")


def answer_fp():
    """답 평가 지문 = 답변 프롬프트(cli/pipeline.py answer_prompt)·이 파일 — 프롬프트가 바뀌면 다시."""
    import hashlib

    # pipeline.py는 파일 통째로(answer_prompt가 쓰는 상수·도우미까지 확실히) · 이 파일은 답 평가 함수만
    return hashlib.sha256(
        (HERE / "pipeline.py").read_bytes() + _src(_answer_eval, _answer_items, cmd_answer_worker).encode("utf-8")
    ).hexdigest()[:8]


def cmd_answer_pool(config, a):
    """풀 S로 답 평가 — qa.json 있는 멤버마다 기존 _answer worker 그대로(풀 bundle을 가리키게 env만 바꿔서) +
    synth-distractors-v2는 --pool-v2로 answer_keywords·forbid_keywords 채점(oldver_value_in_answer 포함). 저장소 캐시는 안 함(풀은 ad-hoc)."""
    store = store_root(config)
    base_env = _load_env(a)
    base_env.setdefault("EMBED_QUERY_CACHE", str(store_root(config) / "query_cache.sqlite"))  # 같은 질문 임베딩 재사용(10-04)
    base_env.setdefault("LLM_ALLOW_EXTERNAL", "1" if a.allow_external else base_env.get("LLM_ALLOW_EXTERNAL", ""))
    pool = load_pool(a.pool)
    members = pool_members(pool)
    combos = ofat_combos(config)
    want = (a.combos or "baseline,post=none").split(",")
    combos = [c for c in combos if c["name"] in want]
    ks = [int(x) for x in a.ks.split(",")] if a.ks else config.get("answer", {}).get("k_candidates", [10])
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    run_dir = resolve_run_dir(a)
    results = []
    for combo in combos:
        post_cfg = post_by_id[combo["post"]]
        target, _skey = pool_s_dir(store, post_cfg, a.pool, members, combo)
        if not (target / "bundle" / "meta.json").exists():
            print(f"[answer --pool] {combo['name']}: 풀 S 없음 — build --pool 먼저")
            continue
        stale, reason = A.is_stale(target)
        if stale and not a.allow_stale:
            raise SystemExit(f"[answer --pool] {combo['name']}: 풀 S 낡음({reason})")
        rename_map_file = target / "rename_map.json"
        env = base_env.copy()
        env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
        env["SEARCH_RERANK"] = combo["rerank"]
        env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
        env["LLM_CACHE_DIR"] = str(store / "llm_cache")
        ds_list = [ds for ds in members if ds not in (DISTRACTOR_DS, DISTRACTOR_V2_DS) and (MM.VALID / ds / "qa.json").exists()]
        if (MM.VALID / DISTRACTOR_V2_DS / "qa.json").exists():
            ds_list = ds_list + [DISTRACTOR_V2_DS]
        for ds in ds_list:  # 비용 관문: ds당 ks 전부를 한 서브프로세스(검색 1회/문항)로
            tmp = run_dir / "raw" / "answer_pool" / combo["name"] / f"{ds}.json"
            args = [
                PY,
                "-m",
                "validation.e2e.stack_matrix",
                "_answer",
                "--dataset",
                ds,
                "--methods",
                ",".join(combo["methods"]),
                "--ks",
                ",".join(map(str, ks)),
                "--out",
                str(tmp),
                "--workers",
                str(a.inner_workers),
            ]
            if a.limit:
                args += ["--limit", str(a.limit)]
            if ds == DISTRACTOR_V2_DS:
                args += ["--pool-v2", "--rename-map", str(rename_map_file)]
            r = _sub(args, env)
            payload = json.loads(tmp.read_text(encoding="utf-8")) if tmp.exists() else None
            for k in ks:
                res = (payload.get("by_k", {}).get(str(k)) if payload else None) or {
                    "error": MM._scrub(((r.stderr or r.stdout) or "")[-500:])
                }
                results.append({"combo": combo["name"], "dataset": ds, "pool": True, "k": k, "answer": res})
                print(
                    f"[answer --pool] {combo['name']} · k={k} · {ds}: 정답률 {res.get('accuracy')}"
                    + (f" · 구판값 유출률 {res.get('oldver_value_in_answer_rate')}" if ds == DISTRACTOR_V2_DS else ""),
                    flush=True,
                )
    (run_dir / "answers.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[answer --pool] {len(results)}건 → {run_dir / 'answers.json'}")
    if getattr(a, "estimate", False):  # pool 추정 — 보수적(캐시 재사용 0 가정): 문항 수 × (입력 LLM_EST_IN_TOKENS + 출력 보정값)
        from common.ai import llm as L

        calls = sum(len((r["answer"] or {}).get("rows") or []) for r in results)
        in_tok = int(MM.own("LLM_EST_IN_TOKENS") or 1500)
        out_tok = int(MM.own("LLM_EST_OUT_TOKENS") or _calibrate_out_tokens(store / "llm_cache") or 1200)
        model = base_env.get("LLM_MODEL")
        pi, po = L.price(model)
        usd = calls * (in_tok * pi + out_tok * po) / 1e6 if pi is not None else float("nan")
        est = {"pool": True, "calls": calls, "assumed_in_tokens": in_tok, "assumed_out_tokens": out_tok, "model": model, "est_usd": usd}
        (run_dir / "estimate.json").write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
        print(
            f"[estimate --pool] 호출 {calls}건(보수적 — 캐시 재사용 0 가정) · 입력 {in_tok}·출력 {out_tok} 토큰/호출({model}) · 추정 비용 ${usd:.2f}",
            flush=True,
        )


def cmd_answer_context_only(config, a):
    """kw_in_context@k 곡선 — LLM 호출 0건(근거를 k로 잘라 기존 채점 함수를 본문에만 적용). store/ans에 안 씀(공짜라 캐시 불필요).
    비용 관문(2026-10): --ks로 넓게(예: 5,10,15,20,30,50) 줘도 검색은 질문당 1회(_answer_eval의 재사용)."""
    store = store_root(config)
    base_env = _load_env(a)
    base_env.setdefault("EMBED_QUERY_CACHE", str(store / "query_cache.sqlite"))
    combos = ofat_combos(config)
    want = (a.combos or "baseline,post=none").split(",")
    combos = [c for c in combos if c["name"] in want]
    ks = [int(x) for x in a.ks.split(",")] if a.ks else list(RECALL_KS)
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    run_dir = resolve_run_dir(a)
    results = []
    for combo in combos:
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                continue
            target, skey = s_dir(store, post_by_id[combo["post"]], ds, combo, False)
            if not (target / "bundle" / "meta.json").exists():
                print(f"[answer --context-only] {combo['name']}/{ds}: S 없음 — build 먼저")
                continue
            env = base_env.copy()
            env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
            env["SEARCH_RERANK"] = combo["rerank"]
            env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
            tmp = run_dir / "raw" / "context" / combo["name"] / f"{ds}.json"
            args = [
                PY,
                "-m",
                "validation.e2e.stack_matrix",
                "_answer",
                "--dataset",
                ds,
                "--methods",
                ",".join(combo["methods"]),
                "--ks",
                ",".join(map(str, ks)),
                "--out",
                str(tmp),
                "--workers",
                str(a.inner_workers),
                "--context-only",
            ]
            if a.limit:
                args += ["--limit", str(a.limit)]
            r = _sub(args, env)
            if not tmp.exists():
                print(f"[answer --context-only] {combo['name']}/{ds}: 실패 — {MM._scrub(((r.stderr or r.stdout) or '')[-300:])}")
                continue
            by_k = json.loads(tmp.read_text(encoding="utf-8")).get("by_k", {})
            for k in ks:
                res = by_k.get(str(k)) or {}
                results.append(
                    {"combo": combo["name"], "dataset": ds, "k": k, "kw_in_context": res.get("kw_in_context"), "n": res.get("n")}
                )
                print(f"[answer --context-only] {combo['name']} · k={k} · {ds}: kw_in_context {res.get('kw_in_context')}", flush=True)
    (run_dir / "context.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[answer --context-only] {len(results)}건(LLM 호출 0) → {run_dir / 'context.json'}")
    return results


def _calibrate_out_tokens(cache_dir):
    """llm_cache의 completion_tokens 평균 — LLM_EST_OUT_TOKENS 기본값(1200) 보정 기준. 읽기만, 실패·없음이면 None(호출부가 기본값).
    ponytail: 저장본 전체를 매번 훑음 — store가 아주 커지면 느려질 수 있음, 그때 샘플링으로."""
    vals = []
    d = Path(cache_dir)
    if d.exists():
        for f in d.glob("*/*.json"):
            try:
                u = (json.loads(f.read_text(encoding="utf-8")) or {}).get("usage") or {}
            except (OSError, ValueError):
                continue
            if u.get("completion_tokens"):
                vals.append(u["completion_tokens"])
    return round(statistics.mean(vals)) if vals else None


def cmd_answer_estimate(config, a):
    """비용 추정 — LLM_FAKE=1로 실제 답변 경로를 돌려(네트워크 0건) 호출 수·캐시 여부·프롬프트 글자 수를 모으고 단가를 곱한다.
    비용 관문(2026-10): run·preflight로 유료 호출을 내기 전에 먼저 이걸로 규모를 본다."""
    from common.ai import llm as L

    store = store_root(config)
    base_env = _load_env(a)
    base_env["LLM_FAKE"] = "1"
    base_env["NO_PAID_CALLS"] = "1"  # llm.chat 밖 외부 유료 호출(임베딩·VLM)도 차단
    base_env.setdefault("EMBED_QUERY_CACHE", str(store / "query_cache.sqlite"))
    base_env["LLM_CACHE_DIR"] = str(store / "llm_cache")
    combos = ofat_combos(config)
    want = (a.combos or "baseline,post=none").split(",")
    combos = [c for c in combos if c["name"] in want]
    ks = [int(x) for x in a.ks.split(",")] if a.ks else config.get("answer", {}).get("k_candidates", [10])
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    model = base_env.get("LLM_MODEL")
    out_tok = int(MM.own("LLM_EST_OUT_TOKENS") or _calibrate_out_tokens(store / "llm_cache") or 1200)
    price_in, price_out = L.price(model)
    if price_in is None:  # 단가 미상이면 $0으로 보이지 않게(10-05 결함)
        print(f"[estimate] 경고: 모델 {model} 단가 미상 — LLM_PRICE_IN·LLM_PRICE_OUT을 지정해야 비용이 계산됨", flush=True)
        price_in = price_out = float("nan")
    totals = {"calls": 0, "cached": 0, "uncached": 0, "uncached_prompt_chars": 0}
    run_dir = resolve_run_dir(a)
    details = []
    for combo in combos:
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                continue
            target, skey = s_dir(store, post_by_id[combo["post"]], ds, combo, False)
            if not (target / "bundle" / "meta.json").exists():
                print(f"[estimate] {combo['name']}/{ds}: S 없음 — build 먼저")
                continue
            env = base_env.copy()
            env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
            env["SEARCH_RERANK"] = combo["rerank"]
            env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
            tmp = run_dir / "raw" / "estimate" / combo["name"] / f"{ds}.json"
            args = [
                PY,
                "-m",
                "validation.e2e.stack_matrix",
                "_answer",
                "--dataset",
                ds,
                "--methods",
                ",".join(combo["methods"]),
                "--ks",
                ",".join(map(str, ks)),
                "--out",
                str(tmp),
                "--workers",
                str(a.inner_workers),
            ]
            if a.limit:
                args += ["--limit", str(a.limit)]
            r = _sub(args, env)
            if not tmp.exists():
                print(f"[estimate] {combo['name']}/{ds}: 실패 — {MM._scrub(((r.stderr or r.stdout) or '')[-300:])}")
                continue
            payload = json.loads(tmp.read_text(encoding="utf-8"))
            for k in ks:
                res = payload.get("by_k", {}).get(str(k)) or {}
                n, cached = res.get("n") or 0, res.get("cached") or 0
                totals["calls"] += n
                totals["cached"] += cached
                totals["uncached"] += n - cached
                totals["uncached_prompt_chars"] += res.get("uncached_prompt_chars") or 0
                details.append({"combo": combo["name"], "dataset": ds, "k": k, "n": n, "cached": cached})
    est_in_tokens = round(totals["uncached_prompt_chars"] / 3)
    est_usd = (est_in_tokens * price_in + totals["uncached"] * out_tok * price_out) / 1e6
    report = {
        "model": model,
        "price_in_per_m": price_in,
        "price_out_per_m": price_out,
        "assumed_out_tokens": out_tok,
        "calls": totals["calls"],
        "cached": totals["cached"],
        "uncached": totals["uncached"],
        "est_input_tokens": est_in_tokens,
        "est_usd": round(est_usd, 4),
        "details": details,
    }
    (run_dir / "estimate.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"[estimate] 호출 {totals['calls']}건(캐시 {totals['cached']}·유료 예정 {totals['uncached']}) · "
        f"추정 입력 토큰 {est_in_tokens} · 가정 출력 토큰/호출 {out_tok}({model}) · 추정 비용 ${est_usd:.2f} → {run_dir / 'estimate.json'}"
    )
    return report


def cmd_answer(config, a):
    """조합 × 답변 근거 수 k × 데이터셋 — S가 지어져 있어야 함(build 먼저). 결과는 저장소 ans/에 열쇠별로(같으면 재사용).
    비용 관문(2026-10): --context-only(LLM 0건)·--estimate(네트워크 0건, 실행 전 추정) 먼저 보고 --ks 전부를 실제로 돌린다.
    같은 (조합·데이터셋)의 ks는 캐시에 없는 것만 모아 한 서브프로세스로(검색은 질문당 1회, k마다 다시 안 부름)."""
    a.workers = RS.resolve_workers("answer", getattr(a, "workers", "auto") or "auto")
    a.inner_workers = RS.resolve_inner_workers(
        getattr(a, "inner_workers", "auto") or "auto", a.workers
    )  # auto면 LLM_MAX_CONCURRENCY ÷ workers — 총 동시 LLM 요청이 상한 안
    if getattr(a, "estimate", False) or getattr(a, "context_only", False):
        # 비용 관문 안전장치 — 어떤 분기(pool 포함)로 가도 유료 호출 0(10-05 결함: --pool이 먼저 분기돼 --estimate·--context-only가
        # 무시되고 실제 답 평가가 돌았음 — 잔액 0이라 402로 막혔을 뿐). 자식 프로세스도 환경으로 물려받음.
        S.put(
            LLM_FAKE="1", NO_PAID_CALLS="1"
        )  # 임베딩·VLM 등 llm.chat 밖 외부 호출도 차단(guard.urlopen) · S7e2 덮기 파일(이 프로세스·자식)
    if getattr(a, "pool", None):
        return cmd_answer_pool(config, a)
    if getattr(a, "context_only", False):
        return cmd_answer_context_only(config, a)
    if getattr(a, "estimate", False):
        return cmd_answer_estimate(config, a)
    store = store_root(config)
    base_env = _load_env(a)
    base_env.setdefault("EMBED_QUERY_CACHE", str(store_root(config) / "query_cache.sqlite"))  # 같은 질문 임베딩 재사용(10-04)
    base_env.setdefault("LLM_ALLOW_EXTERNAL", "1" if a.allow_external else base_env.get("LLM_ALLOW_EXTERNAL", ""))
    combos = ofat_combos(config)
    want = (a.combos or "baseline,post=none").split(",")
    combos = [c for c in combos if c["name"] in want]
    ks = [int(x) for x in a.ks.split(",")] if a.ks else config.get("answer", {}).get("k_candidates", [10])
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    group = MM.read_split(config)
    run_dir = resolve_run_dir(a)
    model = base_env.get("LLM_MODEL")
    with_distractors = bool(getattr(a, "with_distractors", False))
    tasks = []
    for combo in combos:
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                continue
            target, skey = s_dir(store, post_by_id[combo["post"]], ds, combo, with_distractors)
            if not (target / "bundle" / "meta.json").exists():
                print(f"[answer] {combo['name']}/{ds}: S 없음 — build 먼저" + (" --with-distractors" if with_distractors else ""))
                continue
            stale, reason = A.is_stale(target)
            if stale and not a.allow_stale:
                raise SystemExit(f"[answer] {combo['name']}/{ds}: S 낡음({reason})")
            per_k = []
            for k in ks:
                parts = {**r_parts(skey, combo, ds), "answer_k": k, "llm": model, "answer_fp": answer_fp()}
                if with_distractors:
                    parts["distractors"] = True
                per_k.append((k, A.key("a", parts), parts))
            tasks.append((combo, ds, target, per_k))

    def work(t):
        combo, ds, target, per_k = t
        results = {}
        need = []
        for k, akey, parts in per_k:
            out = store / "ans" / akey[:8] / f"{ds}.json"
            if out.exists() and not A.is_stale(out.parent)[0] and not a.limit:
                results[k] = (json.loads(out.read_text(encoding="utf-8")), "reused")
            else:
                need.append((k, akey, parts, out))
        if need:
            env = base_env.copy()
            env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
            env["SEARCH_RERANK"] = combo["rerank"]
            env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
            reuse = config.get("reuse_bundles", {}).get(ds) or {}
            if reuse.get("roster"):
                env["CLIENT_ROSTER"] = reuse["roster"]
            env["LLM_CACHE_DIR"] = str(store / "llm_cache")  # 같은 질문·근거·모델이면 다시 부르지 않음
            need_ks = [k for k, *_ in need]
            tmp = run_dir / "raw" / "answer" / combo["name"] / ds / (",".join(map(str, need_ks)) + ".json")
            args = [
                PY,
                "-m",
                "validation.e2e.stack_matrix",
                "_answer",
                "--dataset",
                ds,
                "--methods",
                ",".join(combo["methods"]),
                "--ks",
                ",".join(map(str, need_ks)),
                "--out",
                str(tmp),
                "--workers",
                str(a.inner_workers),
            ]
            if a.limit:
                args += ["--limit", str(a.limit)]
            if with_distractors:
                args += ["--with-distractors"]
            r = _sub(args, env)
            fake = env.get("LLM_FAKE") == "1"
            payload = json.loads(tmp.read_text(encoding="utf-8")) if tmp.exists() else None
            for k, _akey, parts, out in need:
                if payload is None:
                    results[k] = ({"error": MM._scrub(((r.stderr or r.stdout) or "")[-500:])}, "error")
                    continue
                res = payload.get("by_k", {}).get(str(k)) or {"error": "_answer 결과에 k 없음"}
                if fake:
                    res = {**res, "fake": True}
                # 일부 문항만 돈 결과·호출 오류가 낀 결과·모의 호출 결과는 저장소에 넣지 않음(다음 실행이 다시 — 10-04 오류 결과가 재사용되던 구멍)
                if not a.limit and not res.get("errors") and not fake:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
                    A.manifest(out.parent, "a", parts)
                results[k] = (res, "built")
        return combo["name"], ds, results

    import concurrent.futures

    results_list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for name, ds, results in ex.map(work, tasks):
            for k, (res, status) in sorted(results.items()):
                results_list.append({"combo": name, "dataset": ds, "group": group.get(ds, "dev"), "k": k, "status": status, "answer": res})
                print(f"[answer] {name} · k={k} · {ds}: {status} · 정답률 {res.get('accuracy')}", flush=True)
    (run_dir / "answers.json").write_text(json.dumps(results_list, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[answer] {len(results_list)}건 → {run_dir / 'answers.json'}")


# ───────────────────────── preflight(비용 관문) ─────────────────────────
def cmd_preflight(config, a):
    """비용 관문 — 실제 돈을 쓰기 전 마지막 확인: 조합×데이터셋마다 LLM_FAKE=1로 문항 3개만 전체 답변 경로를 돌려
    (묶음 있음·검색 예외 없음·근거 있음)을 확인하고, 하나라도 FAIL이면 종료 코드 1(실행을 막음). 모두 PASS면
    cmd_answer_estimate로 실제 실행(전체 문항) 비용을 바로 보여 준다."""
    store = store_root(config)
    base_env = _load_env(a)
    base_env["LLM_FAKE"] = "1"
    base_env["NO_PAID_CALLS"] = "1"  # llm.chat 밖 외부 유료 호출(임베딩·VLM)도 차단
    base_env.setdefault("EMBED_QUERY_CACHE", str(store / "query_cache.sqlite"))
    base_env["LLM_CACHE_DIR"] = str(store / "llm_cache")
    combos = ofat_combos(config)
    want = (a.combos or "baseline,post=none").split(",")
    combos = [c for c in combos if c["name"] in want]
    ks = [int(x) for x in a.ks.split(",")] if a.ks else config.get("answer", {}).get("k_candidates", [10])
    post_by_id = {c["id"]: c for c in config["post"]["candidates"]}
    datasets = a.datasets.split(",") if a.datasets else MM.all_datasets(config)
    run_dir = resolve_run_dir(a)
    failures = []
    for combo in combos:
        for ds in datasets:
            if ds not in config.get("reuse_bundles", {}):
                continue
            label = f"{combo['name']}/{ds}"
            target, skey = s_dir(store, post_by_id[combo["post"]], ds, combo, False)
            if not (target / "bundle" / "meta.json").exists():
                print(f"FAIL {label}: S 묶음 없음 — build 먼저")
                failures.append(label)
                continue
            env = base_env.copy()
            env["MCP_BUNDLE"], env["MCP_STORE"] = str(target / "bundle"), config.get("mcp_store", "local")
            env["SEARCH_RERANK"] = combo["rerank"]
            env["RERANK_TIMEOUT_MS"] = str(config["retrieve"].get("rerank_timeout_ms", 120000))
            tmp = run_dir / "raw" / "preflight" / combo["name"] / f"{ds}.json"
            args = [
                PY,
                "-m",
                "validation.e2e.stack_matrix",
                "_answer",
                "--dataset",
                ds,
                "--methods",
                ",".join(combo["methods"]),
                "--ks",
                ",".join(map(str, ks)),
                "--out",
                str(tmp),
                "--workers",
                "2",
                "--limit",
                "3",
            ]
            r = _sub(args, env)
            if not tmp.exists():
                print(f"FAIL {label}: 실행 오류 — {MM._scrub(((r.stderr or r.stdout) or '')[-300:])}")
                failures.append(label)
                continue
            by_k = json.loads(tmp.read_text(encoding="utf-8")).get("by_k", {})
            bad = []
            for k in ks:
                res = by_k.get(str(k)) or {}
                if res.get("errors"):
                    bad.append(f"k{k} 예외 {res['errors']}건")
                no_ev = sum(1 for row in (res.get("rows") or []) if not row.get("evidence"))
                if no_ev:
                    bad.append(f"k{k} 근거 없음 {no_ev}건")
            if bad:
                print(f"FAIL {label}: " + " · ".join(bad))
                failures.append(label)
            else:
                print(f"PASS {label}")
    if failures:
        print(f"\npreflight: {len(failures)}건 FAIL — 먼저 고칠 것: {', '.join(failures)}(실제 실행 추정은 건너뜀)")
        raise SystemExit(1)
    print("\npreflight: 모두 PASS — 실제 실행(전체 문항) 비용 추정")
    return cmd_answer_estimate(config, a)


# ───────────────────────── CLI ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(CONFIG_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan")
    sp.add_argument("--pool", help="pool.json(valid_env/unstructured/synth-distractors-v2/pool.json) — 멤버별 P1 상태 + 풀 S 재사용 여부")

    sp = sub.add_parser(
        "sources", help="D2 — valid_env/unstructured에서 reuse_bundles 데이터셋을 네이티브로 다시 파싱(서버가 117 MB store/src 없이)"
    )
    sp.add_argument("--datasets", help="콤마(기본 reuse_bundles 전부)")
    sp.add_argument("--force", action="store_true", help="_rep/index.json이 있어도 다시")

    sp = sub.add_parser("build")
    sp.add_argument(
        "--workers",
        default="auto",
        help="동시 빌드 수(P1·S 각각) — 띄울 때마다 메모리 문 · auto = CPU·메모리 기준(common/resources.plan_experiment)",
    )
    sp.add_argument("--datasets")
    sp.add_argument("--combos")
    sp.add_argument("--env", help="api embed 등 키가 든 env 파일(KEY=VALUE) — 값은 출력 안 함")
    sp.add_argument("--with-distractors", action="store_true", help="V11 — X의 P1·S를 X+방해 문서(source_dataset==X) 묶음으로")
    sp.add_argument("--pool", help="pool.json — 멤버 P1 _rep를 합쳐 S 묶음 하나(+pool)만 지음")

    sp = sub.add_parser("run")
    sp.add_argument(
        "--workers",
        default="auto",
        help="동시 (조합·데이터셋) 검색 작업 수 — 띄울 때마다 메모리 문(MEM_START_PCT) · auto = CPU·메모리 기준",
    )
    sp.add_argument("--env")
    sp.add_argument("--datasets")
    sp.add_argument("--combos")
    sp.add_argument("--run-dir")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--allow-stale", action="store_true")
    sp.add_argument(
        "--with-llm",
        action="store_true",
        help="A(답 평가, eval_research.py --answer 재사용) 추가 실행 — 기본 꺼짐(config llm.enabled로도 켤 수 있음)",
    )
    sp.add_argument(
        "--with-distractors", action="store_true", help="V11 — X+방해 문서 묶음의 S로 검색 평가(unique_under_distractors만 채점 + 오인율)"
    )
    sp.add_argument(
        "--pool",
        help="pool.json — 풀 S로 멤버마다 자기 qa.json 문항 + v2 '최신 문서' 문항을 채점(distractor_confusion·oldver_confusion 포함)",
    )

    sp = sub.add_parser("report")
    sp.add_argument("--run-dir")

    sp = sub.add_parser("audit")
    sp.add_argument("--allow-stale", action="store_true")

    sp = sub.add_parser("_retrieve")
    sp.add_argument("--dataset", required=True)
    sp.add_argument("--methods", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--with-distractors", action="store_true")

    sp = sub.add_parser("_retrieve_pool")
    sp.add_argument("--pool", required=True)
    sp.add_argument("--rename-map", required=True, help="풀 build가 쓴 <s 저장본>/rename_map.json")
    sp.add_argument("--methods", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--limit", type=int, default=None)

    sp = sub.add_parser(
        "answer",
        help="답 평가 — 조합 × 근거 수 k × 데이터셋 · --context-only만 지원(LLM 답변 채점은 10-13 archive"
        " — dev_tools/perform_test/answer_stage/run.py --real로, 서빙되는 Answer Agent rag_qa)",
    )
    sp.add_argument("--env")
    sp.add_argument("--datasets")
    sp.add_argument("--combos", help="콤마(기본 baseline,post=none)")
    sp.add_argument("--ks", help="콤마(기본 config answer.k_candidates)")
    sp.add_argument("--run-dir")
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--workers", default="auto", help="동시 (조합·k·데이터셋) 작업 수 — 띄울 때마다 메모리 문 · auto = CPU·메모리 기준")
    sp.add_argument(
        "--inner-workers",
        default="auto",
        help="작업 안 동시 질문 수(스레드 — API 대기라 메모리 거의 안 듦) · auto = LLM_MAX_CONCURRENCY ÷ workers",
    )
    sp.add_argument("--allow-stale", action="store_true")
    sp.add_argument("--allow-external", action="store_true", help="합성 데이터 실험 — 외부 LLM(두 겹 잠금의 한 겹)")
    sp.add_argument("--with-distractors", action="store_true", help="V11 — X+방해 문서 묶음의 S로 답 평가")
    sp.add_argument("--pool", help="pool.json — 풀 S로 답 평가, synth-distractors-v2는 oldver_value_in_answer도")
    sp.add_argument("--context-only", action="store_true", help="비용 관문 — LLM 호출 0, kw_in_context@k 곡선만(검색은 질문당 1회)")
    sp.add_argument("--estimate", action="store_true", help="비용 관문 — LLM_FAKE=1(네트워크 0)로 돌려 호출 수·캐시 비율·추정 USD만 보고")

    sp = sub.add_parser("_answer")
    sp.add_argument("--dataset", required=True)
    sp.add_argument("--methods", required=True)
    sp.add_argument("--ks", required=True, help="콤마 — k마다 by_k에 결과(검색은 질문당 max(ks) 1회, k로 자름)")
    sp.add_argument("--out", required=True)
    sp.add_argument("--limit", type=int, default=None)
    sp.add_argument("--workers", type=int, default=4)
    sp.add_argument("--with-distractors", action="store_true")
    sp.add_argument("--pool-v2", action="store_true", help="pool — synth-distractors-v2를 _answer_items(ds) 대신 _pool_v2_items로")
    sp.add_argument("--rename-map", help="--pool-v2일 때 <s 저장본>/rename_map.json")
    sp.add_argument("--context-only", action="store_true", help="LLM 호출 없이 kw_in_context@k만")

    sp = sub.add_parser("preflight", help="비용 관문 — LLM_FAKE=1로 조합×데이터셋마다 문항 3개 드라이런 + 통과하면 실제 실행 비용 추정")
    sp.add_argument("--env")
    sp.add_argument("--datasets")
    sp.add_argument("--combos", help="콤마(기본 baseline,post=none)")
    sp.add_argument("--ks", help="콤마(기본 config answer.k_candidates)")
    sp.add_argument(
        "--limit", type=int, default=None, help="통과 후 비용 추정에 쓸 실제 실행 문항 상한(기본 전체) — 드라이런 자체는 항상 3문항"
    )
    sp.add_argument("--run-dir")
    sp.add_argument("--inner-workers", type=int, default=8)

    a = ap.parse_args()
    if not a.cmd.startswith(
        "_"
    ):  # 실행 전체(하위 프로세스 포함)가 같이 쓰는 지출 장부 — LLM_BUDGET_USD가 실행 단위로 지켜지게(10-05 재검증: 빠져 있었음)
        if MM.own("LLM_SPEND_FILE") is None:  # 옛 os.environ.setdefault — S7e2 덮기 파일(이 프로세스·자식)
            S.put(LLM_SPEND_FILE=str(Path(tempfile.mkdtemp(prefix="llm_spend_")) / "spend.txt"))
    config = load_config(a.config)
    {
        "plan": cmd_plan,
        "sources": cmd_sources,
        "build": cmd_build,
        "run": cmd_run,
        "report": cmd_report,
        "audit": cmd_audit,
        "_retrieve": cmd_retrieve_worker,
        "_retrieve_pool": cmd_retrieve_pool_worker,
        "answer": cmd_answer,
        "preflight": cmd_preflight,
        "_answer": cmd_answer_worker,
    }[a.cmd](config, a)


if __name__ == "__main__":
    utf8_stdout()
    main()
