#!/usr/bin/env python3
"""MCP 범위 축소 평가(2026-10-07 사용자 지시 — "질문→근거 수집·선별까지만") — 실제 MCP 서버(streamable http)의
search 도구만 호출해 hit@1·@5·@k·value_in_evidence@k(정답 값이 근거 원문에 있나)·근거 수·응답 바이트·지연 p50/p95·via 분포를 잰다.
재순위·질문 분해·그래프·용어 확장·답변 생성은 범위 밖(서버 쪽 env로 끔 — 이 도구는 끄지 않음, 호출만).

AD42 R3·R1 문턱 보정(근거 게이트·집계 경로는 서버에서 늘 켬):
  evidence_status 분포·근거별 low_score — 매 응답의 evidence(score·text 필드, 서버 env와 무관하게 항상 있음)로
    mcp_server.services.search.shaping.evidence_status()를 클라이언트에서 그대로 재계산(--min-score 문턱마다, 서버의 실제 게이트와 같은 함수) —
    서버 응답에 evidence_status가 이미 있어도 비교 가능하게 항상 재계산.
  negative 정탐·오탐 — 평가셋 자체 negative 문항은 실제로는 근거가 있어 반박하는 문항(synth-4clients, 옛 eval_research.py 주석)이라
    "정답 문서 없음" 판정에 안 맞음 → --negative-from <다른 세트>로 그 세트 질문 중 **지금 묶음에 없는 문서가 gold인 것만** 섞어
    "정답 문서 없는 질문" negative로 — found면 오탐, weak·none이면 정탐.
  집계 질문 hit — qa.json의 type이 aggregate·table_aggregate인 문항에서 evidence[0].via=="aggregate"
    ·gold_answer와 집계 answer 일치율.

채점 재사용(새로 안 만듦): _load_qa_items(gold_docs 추출 — S5에 model_matrix에서 이 파일로) · _score_4clients(synth-4clients 정답 포함 판정 — S5a에 옛
cli/eval_research.py에서 이 파일로 옮김) · src/tools/data/_synth_images_qa.score(answer_keywords·forbid_keywords) ·
_pool_v2_items·_remap_items·_raw_qa_items(풀 평가 때 문서 이름 치환 — S5에 stack_matrix에서 이 파일로) ·
mcp_server.services.search.shaping.evidence_status(R3 판정 — 서버와 같은 함수, 새로 안 만듦).

bge-m3 S 묶음·그 R 비교 결과는 메인 체크아웃(dev/out/store, --store-root)에서 읍 전용으로 찾는다(이 도구는 아무것도 쓰지 않음) —
parts.embed=="bge-m3"·parts.dataset(또는 pool=true)로 가장 최근 것을 고른다. 서버는 그 bundle을 MCP_BUNDLE로 가리키며 별도로
떠 있어야 한다(이 도구는 서버를 띄우지 않음 — mcp_smoke.py와 같은 순수 클라이언트).

사용:
  python cli/mcp_eval.py --show-bundle --set synth-terms-hard --store-root <dev/out/store>      # 서버에 줄 MCP_BUNDLE 경로만 출력
  python cli/mcp_eval.py --show-bundle --set synth-distractors-v2 --pool --store-root <...>      # 풀 묶음 + rename_map 경로
  python cli/mcp_eval.py --set synth-terms-hard --url http://127.0.0.1:18765/mcp --k 5 [--concurrency 8] [--store-root <...>]
  python cli/mcp_eval.py --set synth-terms-hard,synth-revisions-tune,synth-4clients,synth-distractors-v2 \
      --pool --url ... --store-root <...>     # 풀 묶음을 가리키는 서버에 여러 세트를 한 번에(문서 이름은 자동 치환)
  python cli/mcp_eval.py --set synth-4clients --negative-from synth-terms-hard --min-score none,0,0.02,0.05,0.1 \
      --url ... --store-root <...>            # R3 문턱 보정표 + negative 정탐·오탐 + synth-4clients 집계 문항 hit
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

from common.config import settings as C  # common 칸(SEARCH_RECENCY — S7e2 client_only_env)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, PROJ_ROOT  # 폴더 재편 뒤 이 상수들만 바뀌면 됨
from common.core.text import normalize_value  # --questions value_in_evidence 채점(값 비교, verify_key.py와 같은 함수)
from mcp_server import config as mc  # 설정 객체(S7d)
from mcp_server.services.search import shaping as M  # evidence_status(R3, 서버와 같은 함수 재사용 — S5부터 services/search/shaping.py)
from mcp_server.services.search.synth_score import score as synth_score  # answer_keywords·forbid_keywords 채점(재사용)
from mcp_server.services.search.synth_score import score_table as synth_score_table

HERE = Path(__file__).resolve().parent  # deploy/mcp_server/cli(S5 — 옛 deploy/common_tools/evaluation)
DEV = APP_ROOT  # output/ 등 런타임 경로용(오늘은 dev/, 단계 5·7 전)
PROJ = PROJ_ROOT

# ───────────────────────── 평가 세트·채점(S5a 10-26 — 옛 cli/eval_research.py에서 그대로 옮김) ─────────────────────────
# eval_research.py(research() 평가)는 research.py와 함께 지웠다(사용자 10-26). 문항 로더·synth-4clients 채점은
# 이 파일과 stack_matrix._answer_items·_answer_eval이 써서 여기로 옮겼다(함수 내용은 바이트 그대로 — 세트 목록 _sets·SETS는
# stack_matrix만 써서 S5에 그쪽으로 되돌림, VS5a R-2).


def _score_4clients(it):
    gold, typ = it.get("gold_answer"), it["type"]
    if it.get("gold_table"):  # BR20 — 표 문항(QA003 + 이전엔 UNSCORED였던 9건)도 행·합계 비교로 채점
        return lambda ans: synth_score_table(it["gold_table"], ans or "")
    if gold is None or typ == "negative":  # 그 외 서술형 부정 답은 단순 키워드로 못 잼 — answer 평가에서 제외
        return None
    if it.get("answer_keywords"):  # 있으면 우선 — _synth_images_qa.score와 같은 규칙(AND·'|'는 OR, c1bc27da cross_document·format_mixed)
        return lambda ans: synth_score(it, ans or "")
    norm = lambda s: re.sub(r"\s+", "", str(s)).lower()

    def fn(ans):
        return norm(gold) in norm(ans or "")

    return fn


def load_4clients(base, limit=None):
    man = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    f2 = {d["doc_id"]: Path(d["file"].replace("\\", "/")).name for docs in man["formats"].values() for d in docs}
    items = json.loads((base / "qa.json").read_text(encoding="utf-8"))["items"]
    out = []
    for q in items:
        want = {f2.get(e["doc_id"]) for e in (q.get("evidence") or [])} - {None}
        out.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "gold_docs": want,
                "negative": "negative" in q["type"],
                "score_fn": _score_4clients(q),
            }
        )
    return out[:limit] if limit else out


def load_images_like(base, limit=None):
    qa = json.loads((base / "qa.json").read_text(encoding="utf-8"))
    out = []
    for it in qa["items"]:
        docs = set()
        for e in it.get("evidence") or []:
            if e.get("doc"):
                docs.add(e["doc"])
            docs.update(e.get("alt_docs") or [])
        out.append(
            {
                "id": it["id"],
                "type": it["type"],
                "question": it["question"],
                "gold_docs": docs,
                "negative": "negative" in it["type"],
                "score_fn": lambda ans, raw=it: synth_score(raw, ans),
            }
        )
    return out[:limit] if limit else out


# ───────────────────────── 문항 로더(S5 10-26 — 코디네이터 답 Q4 c: stack_matrix·model_matrix에서 옮김) ─────────────────────────
# mcp_eval은 retrieval 이미지 도구인데 stack_matrix·model_matrix는 S6에 validation/e2e(이미지 밖)로 가서, 이 파일이 쓰던 문항 로더를
# 여기로 옮기고 두 PC 도구가 이 파일에서 늦게 import한다. 함수 내용은 그대로 — 옛 MM.VALID 글자만 이 파일의 VALID(같은 값)로(Q7 a).
VALID = PROJ_ROOT / "valid_env" / "unstructured"  # 옛 model_matrix.VALID와 같은 값(ROOT = PROJ_ROOT)
DISTRACTOR_V2_DS = "synth-distractors-v2"  # 데이터셋 이름 — stack_matrix.DISTRACTOR_V2_DS와 같은 값(그쪽은 풀 평가 곳곳에서 씀)


def _load_qa_items(ds):
    base = VALID / ds
    qa = json.loads((base / "qa.json").read_text(encoding="utf-8"))
    items = qa.get("items", [])
    out = []
    if ds == "synth-4clients":
        man = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        f2 = {d["doc_id"]: Path(d["file"].replace("\\", "/")).name for docs in man["formats"].values() for d in docs}
        for q in items:
            want = {f2.get(e["doc_id"]) for e in (q.get("evidence") or [])} - {None}
            out.append({"id": q["id"], "question": q["question"], "gold_docs": want})
    else:
        for it in items:
            docs = set()
            for e in it.get("evidence") or []:
                if e.get("doc"):
                    docs.add(e["doc"])
                docs.update(e.get("alt_docs") or [])
            out.append({"id": it["id"], "question": it["question"], "gold_docs": docs})
    return out


def _raw_qa_items(ds):
    """원본 qa.json 문항(id → 항목 그대로) — W20 references·expected_attachments 용(없는 데이터셋은 그 필드가 없을 뿐, 안전)."""
    f = VALID / ds / "qa.json"
    if not f.exists():
        return {}
    return {it["id"]: it for it in json.loads(f.read_text(encoding="utf-8")).get("items", [])}


def _remap_items(items, ds, rename_map):
    """일반 멤버 qa.json 문항의 gold_docs를 풀 안 문서명으로(충돌 접두 반영) — 다른 필드는 그대로."""
    return [{**it, "gold_docs": {rename_map.get((ds, d), d) for d in it["gold_docs"]}} for it in items]


def _pool_v2_qa():
    f = VALID / DISTRACTOR_V2_DS / "qa.json"
    return (json.loads(f.read_text(encoding="utf-8")).get("items") or []) if f.exists() else []


def _pool_v2_items(rename_map):
    """synth-distractors-v2 문항 → 공통 item 모양(id·question·gold_docs) + answer_keywords·forbid_keywords(답 평가·오인율용).
    gold = evidence[].dataset/doc(원본 데이터셋의 원본 문서) → rename_map으로 풀 안 문서명."""
    out = []
    for it in _pool_v2_qa():
        gold = {rename_map.get((e.get("dataset"), e["doc"]), e["doc"]) for e in (it.get("evidence") or []) if e.get("doc")}
        out.append(
            {
                "id": it["id"],
                "question": it["question"],
                "gold_docs": gold,
                "answer_keywords": it.get("answer_keywords") or [],
                "forbid_keywords": it.get("forbid_keywords") or [],
            }
        )
    return out


INDEX_ID = None  # AD41 --index-id — 주면 search에 index_id 인자(없으면 기본 색인, 요청도 전과 같음)
METHODS = ["vector", "bm25", "id"]  # 범위 축소(그래프·image·openviking·concept 제외) — 사용자 지시 2026-10-07
# GH1-16(10-11) — 아래 설정은 서버 프로세스가 읽는다(요청 인자 아님). 평가 클라이언트에 한 번 덮어 준 값(덮기 파일 overrides — 옛 "사용자가
# env로 준 값" 자리)은 서버엔 안 먹으므로 보고서에 "클라이언트에만 준 값"으로 남기고 경고한다 — 서버를 그 값으로 다시 띄웠는지 사람이/에이전트가
# 확인. 공유 settings.yaml(서버와 같은 파일 — run_tool mcp_eval)에 적힌 값은 서버도 읽으므로 넣지 않는다(VS7e2 R-11).
SERVER_ONLY_ENV = (
    "MCP_METHODS",
    "SEARCH_RECENCY",
)


def client_only_env():
    out = {}
    once = C.overridden()  # 지금 설정 파일(덮기 파일 사슬)의 overrides 이름
    for k in SERVER_ONLY_ENV:  # 클라이언트에 한 번 덮어 준 값(기본값·공유 settings.yaml 값 아님), 옛 env 글자 꼴로
        if k not in once:
            continue
        v = mc.given(k)
        v = C.given(k) if v is None else v
        if v is not None:
            out[k] = C.render(v)
        elif mc.dropped(k) or C.dropped(k):  # VS7e3 R-5 — local에서 형식이 틀려 버린 값(경고 뒤 기본값)은 비운 칸과 나눔
            out[k] = "(버림 — 형식 오류, 기본값)"
        else:
            out[k] = "(비움 — 기본값)"  # 덮기 파일로 비운 칸도 서버와 다를 수 있음(리뷰 S7e3)
    return out


OUT_DIR = DEV / "output" / "eval" / "mcp_eval"
AGG_TYPES = {"aggregate", "table_aggregate"}  # R1 — qa.json type이 이거면 집계 질문(synth-4clients에 있음)
DEFAULT_MIN_SCORES = "none,0,0.02,0.05,0.1"  # R3 문턱 후보(none=점수 문턱 없이 핵심어만, --min-score로 바꿈)
QUESTIONS_DS = "__questions__"  # --questions(auto_questions 산출 jsonl) 전용 가짜 ds — score_fn_for 분기 열쇠


def parse_min_scores(spec):
    return [None if tok.strip().lower() == "none" else float(tok) for tok in spec.split(",") if tok.strip()]


def _status_key(s):
    return "kw_only" if s is None else str(s)


def _norm_val(s):
    """집계 answer vs qa.json gold_answer 비교(공백·쉼표·대소문자 무시) — aggregate.py의 금액 표기(`_fmt`, 천단위 쉼표)와 맞춤."""
    return re.sub(r"[\s,]+", "", str(s if s is not None else "")).lower()


# ───────────────────────── 묶음·비교 결과 탐색(메인 체크아웃, 읍 전용) ─────────────────────────
def _manifests(store_root):
    for f in (Path(store_root) / "s").glob("*/*/_manifest.json"):
        try:
            yield f, json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue


S_PARTS_DEFAULT = {"chunker": "structure", "chunk_size": None, "summary": "lead"}


def _s_parts_want():
    """10-13 청크 크기 실험 — 같은 저장소에 청크 설정만 다른 S 묶음이 생기면 '가장 최근'이 실험 묶음이 돼 기본 측정이
    바뀌던 것을 막는다: 기본은 기준 설정(S_PARTS_DEFAULT)만, EVAL_S_PARTS(JSON, 예 {"chunk_size":256})로 덮어씀."""
    want = dict(S_PARTS_DEFAULT)
    mc.checked("EVAL_S_PARTS")  # 형식 틀린 JSON은 옛 json.loads처럼 여기서 실패(S7d — 설정 객체, 값은 안 찍음)
    _sp = mc.cfg().dev.eval_s_parts
    if _sp:  # 평가가 고를 S 묶음 설정(JSON, 예 {"chunk_size":256}) — 기본(비움)은 기준 설정 structure·기본 크기·lead만(evaluation/mcp_eval.resolve_bundle, 청크 크기 실험 묶음이 기본 측정에 끼지 않게)
        want.update(_sp)
    return want


def resolve_bundle(store_root, dataset, pool=False):
    """dataset(또는 pool=true) + embed=bge-m3 + 기준 청크 설정(_s_parts_want)인 S 묶음 중 가장 최근(created_at) 것. 없으면 None."""
    best = None
    want = _s_parts_want()
    for f, m in _manifests(store_root):
        parts = m.get("parts", {})
        if parts.get("embed") != "bge-m3":
            continue
        if any(parts.get(k) != v for k, v in want.items() if k in parts or v is not None):
            continue
        if pool != bool(parts.get("pool")):
            continue
        if not pool and parts.get("dataset") != dataset:
            continue
        cfg_dir = f.parent
        if not (cfg_dir / "bundle" / "meta.json").exists():
            continue
        created = m.get("created_at", "")
        if best is None or created > best[1]:
            best = (cfg_dir, created)
    if best is None:
        return None
    cfg_dir, created = best
    skey = cfg_dir.parent.name
    out = {"bundle": cfg_dir / "bundle", "skey": skey, "created_at": created, "dir": cfg_dir}
    if pool:
        out["rename_map"] = cfg_dir / "rename_map.json"
    return out


def find_r_compare(store_root, skey, dataset, pool=False):
    """같은 skey·methods(vector+bm25+id)·rerank off의 stack_matrix R 결과(recall_at 등) — 없으면 None."""
    rroot = Path(store_root) / "r" / skey
    if not rroot.exists():
        return None
    cands = [c for c in rroot.iterdir() if c.is_dir() and c.name.startswith("vector+bm25+id_") and ("+pool" in c.name) == pool]
    if not cands:
        return None

    def created(c):
        m = c / "_manifest.json"
        try:
            return json.loads(m.read_text(encoding="utf-8")).get("created_at", "")
        except (OSError, json.JSONDecodeError):
            return ""

    best = max(cands, key=created)
    f = best / ("pool.json" if pool else f"{dataset}.json")
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get(dataset) if pool else d


# ───────────────────────── 문항·채점 함수 로딩(기존 함수 재사용) ─────────────────────────
def load_rename_map(path):
    arr = json.loads(Path(path).read_text(encoding="utf-8"))
    return {(ds, orig): new for ds, orig, new in arr}


def load_items(ds, rename_map=None):
    """반환: (items[{"id","question","gold_docs",...}], raw_by_id) — raw는 value_in_evidence 채점에 필요한 원본 필드."""
    if ds == DISTRACTOR_V2_DS:
        items = _pool_v2_items(rename_map or {})
        return items, {it["id"]: it for it in items}
    items = _load_qa_items(ds)
    if rename_map:
        items = _remap_items(items, ds, rename_map)
    return items, _raw_qa_items(ds)


# count 유형(요건③) — gold_docs가 고객사의 계약 문서 전부(여러 개)에 흩어져 top-k 문서 일치가 의미 없고,
# answer(건수)도 근거 원문 한 곳엔 안 나옴 → hit·value_in_evidence 둘 다 제외(unverified_docs와 같은 취급).
QUESTIONS_EXCLUDE_CATS = {"count"}


def load_question_items(path):
    """auto_questions.py 산출 jsonl(cli/auto_questions.py) → (items, raw_by_id) — gold_docs는 gold_evidence[].file
    (기존 hit 채점의 file_name 일치 규칙 재사용, 새로 안 만듦) · 값은 raw_by_id로 score_fn_for(QUESTIONS_DS)가 읾음.
    제외(hit·value_in_evidence 둘 다 안 잼, row에 excluded=True로 표시): unverified_docs 있는 문항(E12 글자 깨짐 —
    집계 자체가 못 미더움) · count·sum 유형(여러 문서에 걸친 집계값·문서라 단일 근거 매칭이 안 맞음)."""
    rows = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    items, raw = [], {}
    for r in rows:
        excluded = r.get("category") in QUESTIONS_EXCLUDE_CATS or bool(r.get("unverified_docs"))
        gold_docs = set() if excluded else {e["file"] for e in (r.get("gold_evidence") or []) if e.get("file")}
        items.append({"id": r["id"], "question": r["question"], "gold_docs": gold_docs, "excluded": excluded})
        raw[r["id"]] = r
    return items, raw


def score_fn_for(ds, it, raw):
    """정답 값이 텍스트 안에 있나(bool) 채점 함수, 또는 못 재면 None(부정 문항·gold 없음·첨부 요구형)."""
    if ds == DISTRACTOR_V2_DS:
        kws = it.get("answer_keywords") or []
        if not kws:
            return None
        item = {"answer_keywords": kws, "forbid_keywords": it.get("forbid_keywords") or []}
        return lambda text: bool(synth_score(item, text))
    r = (raw or {}).get(it["id"])
    if r is None:
        return None
    if ds == QUESTIONS_DS:
        if it.get("excluded"):
            return None
        if r.get("answer_keywords"):  # --rfi로 합쳐진 문항(기존 schema)이면 그대로 재사용
            item = {"answer_keywords": r["answer_keywords"], "forbid_keywords": r.get("forbid_keywords") or []}
            return lambda text: bool(synth_score(item, text))
        val = r.get("answer") if r.get("answer") is not None else r.get("value")
        if val in (None, ""):
            return None
        vn = normalize_value(val)
        return lambda text, vn=vn: vn in normalize_value(text)
    if ds == "synth-4clients":
        fn = _score_4clients(r)
        return (lambda text, fn=fn: bool(fn(text))) if fn else None
    if not r.get("answer_keywords") or r.get("expected_attachments"):
        return None  # 첨부형은 근거 원문만으로 못 잼(이 도구는 attachments를 안 받음)
    return lambda text, r=r: bool(synth_score(r, text))


# ───────────────────────── 서버 호출(mcp_smoke.py와 같은 클라이언트 방식) ─────────────────────────
async def call_search(session, question, k):
    t0 = time.perf_counter()
    res = await session.call_tool(
        "search", {"question": question, "k": k, "methods": METHODS, "decompose": False, **({"index_id": INDEX_ID} if INDEX_ID else {})}
    )
    ms = (time.perf_counter() - t0) * 1000
    raw = res.content[0].text
    d = json.loads(raw)
    if "error" in d:  # AD41 — 모르는 색인 등은 빈 근거(미적중)가 아니라 오류로 셈
        raise RuntimeError(d["error"])
    return d, ms, len(raw.encode("utf-8"))


def _rank_of(files, gold_docs):
    """files 중 gold_docs에 있는 첫 file_name의 1-based 순위(없으면 None) — hit{k}·hit{k}_doc가 공용으로 쓴다."""
    return next((i + 1 for i, f in enumerate(files) if f in gold_docs), None)


def _rank_of_variants(ev, gold_docs):
    """R2-c 요건① 스코어링 변경 — _rank_of와 같은 생각이지만 사본 그룹 대표의 변형(evidence[i]["variants"])도
    그 자리의 적중으로 센다(gold가 대표 자신이거나 variants 중 하나면 적중) — hit{k}_variant·hit{k}_doc_variant 전용.
    기존 hit{k}(파일명만)는 그대로 둔다 — 전후 비교가 보고 요건(before=hit{k}, after=hit{k}_variant)."""
    for i, e in enumerate(ev):
        if e.get("file_name") in gold_docs or (gold_docs & set(e.get("variants") or ())):
            return i + 1
    return None


def _doc_files(ev, files, skip_via=("aggregate", "aggregate_llm")):
    """engine-qa BLOCK 3 — via=aggregate(R1)는 근거 맨 앞에 끼워 넣은 집계 결과(file_name 없음)라 그대로 두면 문서
    순위를 한 칸 밀어내린다(AD42 실측: hit@1 0.757→0.678). 그 근거를 건너뛴 file_name 목록(순서 유지)."""
    return [f for e, f in zip(ev, files) if e.get("via") not in skip_via]


def _ref_metrics(raw_it, ev, files, ks, kmax):
    """W20②③ — qa.json 원본 references(문서·절·image_id)·expected_attachments를 직접 봄(기존 hit{k}는 model_matrix가
    evidence[].doc에서 유도한 gold_docs 기준 — 같은 세트면 보통 같은 집합이지만, 여긴 references를 그대로 써서 새로
    분리된 지표로 보고). refs·attachments 없는 문항·데이터셋은 빈 dict(기존 지표·세트 영향 없음).
    ref_doc_hit{k}: references[].doc가 상위 k 근거에 있나(기존 hit{k}와 같은 틀, 다른 원천) ·
    ref_image_hit: references 중 image_id 있는 항목이 있으면 그 image_id가 상위 kmax 근거의 image_ids에 있나(문항에 image_id 없으면 None) ·
    attach_hit/attach_precision: expected_attachments(기대 image_id 집합) — 반환 근거 그림 중 하나라도 맞으면 hit,
    precision = 맞은 image_id 수 / 반환된 image_id 종류 수(반환 그림이 없으면 None — 분모 0 나눔 방지)."""
    out = {}
    refs = (raw_it or {}).get("references") or []
    if refs:
        ref_docs = {r["doc"] for r in refs if r.get("doc")}
        ref_images = {r["image_id"] for r in refs if r.get("image_id")}
        rank = _rank_of(_doc_files(ev, files), ref_docs) if ref_docs else None  # 검토 note 2 — 집계 근거 건너뜀(hit{k}_doc와 같은 순위)
        out.update({f"ref_doc_hit{k}": (rank is not None and rank <= k) for k in ks})
        if ref_images:
            seen = {img for e in ev[:kmax] for img in (e.get("image_ids") or [])}
            out["ref_image_hit"] = bool(ref_images & seen)
    atts = set((raw_it or {}).get("expected_attachments") or [])
    if atts:
        seen = {img for e in ev[:kmax] for img in (e.get("image_ids") or [])}
        out["attach_hit"] = bool(atts & seen)
        out["attach_precision"] = round(len(atts & seen) / len(seen), 4) if seen else None
    return out


async def eval_item(session, sem, ds, it, raw, ks, kmax, min_scores=None, negative=False):
    """negative=True: --negative-from 세트 문항(이 묶음에 없는 문서가 gold) — hit·value_in_evidence는 안 재고
    evidence_status(found면 오탐)만. min_scores: R3 문턱 후보마다 evidence_status를 클라이언트에서 재계산(status 딕셔너리).
    반환: (row, evidence) — evidence는 --xlsx(질문·근거 엑셀)용, row(기존 json/md/html)엔 안 들어감."""
    score_fn = None if negative else score_fn_for(ds, it, raw)
    async with sem:
        try:
            d, ms, nbytes = await call_search(session, it["question"], kmax)
        except Exception as ex:
            return {"id": it["id"], "negative": negative, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}, []
    ev = d.get("evidence") or []
    files = [e.get("file_name") for e in ev]
    has_gold = bool(it.get("gold_docs")) and not negative
    gold_rank = _rank_of(files, it["gold_docs"]) if has_gold else None
    hits = {f"hit{k}": (gold_rank is not None and gold_rank <= k) if has_gold else None for k in ks}
    doc_ev = [e for e, f in zip(ev, files) if e.get("via") not in ("aggregate", "aggregate_llm")]  # engine-qa BLOCK 3과 같은 제외
    gold_rank_doc = (
        _rank_of(_doc_files(ev, files), it["gold_docs"]) if has_gold else None
    )  # 집계 근거를 건너뛴 문서 순위(hit1_doc·hit5_doc·…)
    hits_doc = {f"hit{k}_doc": (gold_rank_doc is not None and gold_rank_doc <= k) if has_gold else None for k in ks}
    # R2-c 요건① 스코어링 변경 — 사본 그룹 variants도 적중으로 세는 새 정의(before=hit{k}·hit{k}_doc, after=아래 _variant)
    gold_rank_v = _rank_of_variants(ev, it["gold_docs"]) if has_gold else None
    hits_v = {f"hit{k}_variant": (gold_rank_v is not None and gold_rank_v <= k) if has_gold else None for k in ks}
    gold_rank_doc_v = _rank_of_variants(doc_ev, it["gold_docs"]) if has_gold else None
    hits_doc_v = {f"hit{k}_doc_variant": (gold_rank_doc_v is not None and gold_rank_doc_v <= k) if has_gold else None for k in ks}
    vie = None
    if score_fn is not None:
        text = "\n".join(e.get("text") or "" for e in ev[:kmax])
        vie = score_fn(text)
    via_all = "".join(e.get("via") or "" for e in ev)
    status = {_status_key(s): M.evidence_status(it["question"], ev, s)[0] for s in (min_scores or [])}
    out = {
        "id": it["id"],
        "negative": negative,
        "gold_rank": gold_rank,
        "gold_rank_doc": gold_rank_doc,
        **hits,
        **hits_doc,
        **hits_v,
        **hits_doc_v,
        "value_in_evidence": vie,
        "n_evidence": len(ev),
        "bytes": nbytes,
        "ms": round(ms, 1),
        "status": status,
        "vector_used": "v" in via_all,
        "via_v": via_all.count("v"),
        "via_k": via_all.count("k"),
        "via_i": via_all.count("i"),
    }
    raw_it = (raw or {}).get(it["id"]) if (raw and not negative) else None
    if raw_it and raw_it.get("type") in AGG_TYPES:  # R1 — 집계 문항만(synth-4clients aggregate·table_aggregate)
        agg_via = bool(ev) and ev[0].get("via") == "aggregate"
        gold_answer = raw_it.get("gold_answer")
        out.update(
            agg_type=raw_it["type"],
            agg_via=agg_via,
            agg_hit=(_norm_val(ev[0].get("answer")) == _norm_val(gold_answer)) if (agg_via and gold_answer is not None) else None,
        )
    out.update(_ref_metrics(raw_it, ev, files, ks, kmax))  # W20②③ — references·expected_attachments(있을 때만 칸 생김)
    return out, ev


def negative_items(store_root, ds, neg_ds, limit=None):
    """ds가 가리키는 묶음에 없는 문서가 gold인 neg_ds 질문 — '정답 문서 없는' negative(R3 보정, 평가셋 자체 negative 문항은
    실제로는 근거가 있어 반박하는 문항이라 이 용도에 안 맞음 — _sets() 주석과 옛 eval_research.py 설명 참조)."""
    if not store_root:
        return []
    b = resolve_bundle(store_root, ds)
    if not b:
        return []
    bundle_docs = {
        json.loads(ln)["file_name"] for ln in (b["bundle"] / "docs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()
    }
    items, _ = load_items(neg_ds)
    out = [it for it in items if it.get("gold_docs") and not (it["gold_docs"] & bundle_docs)]
    return out[:limit] if limit else out


def eval_ok(report):
    """GH1-09 — report의 모든 세트에 질의 오류(error 행)가 없고 평가한 문항이 1개 이상이면 True.
    e2e.py는 이 프로세스의 종료 코드만 보고 성공/실패를 판정(run_step의 일반 처리, mcp_eval 전용 코드 없음)."""
    n = sum(e["n"] for e in report["sets"].values())
    has_error = any(r.get("error") for e in report["sets"].values() for r in e["rows"])
    return n > 0 and not has_error


def _rate(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(1 for v in vals if v) / len(vals), 3) if vals else None


def _pctl(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    i = min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))
    return round(vals[i], 1)


def summarize(rows, ks, min_scores=None):
    ok = [r for r in rows if not r.get("error")]
    out = {"n": len(rows), "errors": len(rows) - len(ok)}
    for k in ks:
        out[f"hit{k}"] = _rate(ok, f"hit{k}")
        out[f"hit{k}_doc"] = _rate(ok, f"hit{k}_doc")  # engine-qa BLOCK 3 — via=aggregate 근거를 건너뛴 문서 순위 기준
        out[f"hit{k}_variant"] = _rate(ok, f"hit{k}_variant")  # R2-c — 사본 그룹 variants도 적중(before=hit{k})
        out[f"hit{k}_doc_variant"] = _rate(ok, f"hit{k}_doc_variant")
        out[f"ref_doc_hit{k}"] = _rate(ok, f"ref_doc_hit{k}")  # W20② — qa.json references 원본 기준(없으면 None)
    out["value_in_evidence"] = _rate(ok, "value_in_evidence")
    out["ref_image_hit"] = _rate(ok, "ref_image_hit")  # W20② — references의 image_id(있는 문항만)
    out["attach_hit"] = _rate(ok, "attach_hit")  # W20③ — expected_attachments 중 하나라도 반환됐나
    precs = [r["attach_precision"] for r in ok if r.get("attach_precision") is not None]
    out["attach_precision"] = round(statistics.mean(precs), 4) if precs else None  # W20③ — 반환 그림 중 기대 image_id 비율
    ms = [r["ms"] for r in ok if r.get("ms") is not None]
    out["n_evidence_avg"] = round(statistics.mean(r["n_evidence"] for r in ok), 1) if ok else None
    out["bytes_avg"] = round(statistics.mean(r["bytes"] for r in ok), 0) if ok else None
    out["ms_p50"] = _pctl(ms, 50)
    out["ms_p95"] = _pctl(ms, 95)
    out["vector_used_rate"] = _rate(ok, "vector_used")  # "벡터가 실제로 쓰인 질문 비율"(로컬 bge-m3 임베딩 성공)
    out["via_v"] = sum(r.get("via_v") or 0 for r in ok)
    out["via_k"] = sum(r.get("via_k") or 0 for r in ok)
    out["via_i"] = sum(r.get("via_i") or 0 for r in ok)
    out["evidence_status"] = {}  # R3 — 문턱마다 found/weak/none 분포(서술, 정탐·오탐은 negative 세트로)
    for s in min_scores or []:
        key = _status_key(s)
        vals = [r["status"][key] for r in ok if r.get("status", {}).get(key)]
        out["evidence_status"][key] = (
            {v: round(sum(1 for x in vals if x == v) / len(vals), 3) for v in ("found", "weak", "none")} if vals else None
        )
    agg_rows = [r for r in ok if r.get("agg_type")]
    if agg_rows:
        out["agg_n"] = len(agg_rows)
        out["agg_via_rate"] = round(sum(1 for r in agg_rows if r["agg_via"]) / len(agg_rows), 3)  # R1 — detect()가 집계로 가린 비율
        scored = [r for r in agg_rows if r.get("agg_hit") is not None]
        out["agg_hit_rate"] = round(sum(1 for r in scored if r["agg_hit"]) / len(scored), 3) if scored else None
    return out


def summarize_negative(rows, min_scores):
    """R3 negative 정탐(weak·none)·오탐(found) — negative_items()로 만든 '정답 문서 없는' 문항 전용."""
    ok = [r for r in rows if not r.get("error")]
    out = {"n": len(rows), "errors": len(rows) - len(ok)}
    for s in min_scores or []:
        key = _status_key(s)
        vals = [r["status"][key] for r in ok if r.get("status", {}).get(key)]
        out[f"false_positive@{key}"] = round(sum(1 for v in vals if v == "found") / len(vals), 3) if vals else None
        out[f"true_negative@{key}"] = round(sum(1 for v in vals if v in ("weak", "none")) / len(vals), 3) if vals else None
    return out


def ids_for(spec, ds):
    """--ids — 문항 id만 골라 평가(hard-core 목록 방식: 원래 말뭉치 안에서 그 문항만). spec = 쉼표 목록 · 줄 단위 txt ·
    manifest.json({"retrieval": {세트: [id…]}}). None이면 거르지 않음. manifest에 이 세트가 없으면 빈 집합(그 세트 건너뜀)."""
    if not spec:
        return None
    p = Path(spec)
    if p.suffix == ".json" and p.is_file():
        m = json.loads(p.read_text(encoding="utf-8"))
        return set((m.get("retrieval", m) or {}).get(ds, []))
    if p.is_file():
        return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return {x.strip() for x in spec.split(",") if x.strip()}


async def run_eval(
    url,
    token,
    sets,
    pool,
    store_root,
    k,
    limit,
    concurrency,
    min_scores=None,
    negative_from=None,
    negative_limit=None,
    want_evidence=False,
    questions_path=None,
    ids=None,
):
    """want_evidence=True(--xlsx): report(json/md/html, 바이트 불변)는 그대로 두고, 문항별 질문·근거 원문을 담은
    xlsx_data(별도 반환값, report에 안 섞음)를 함께 만든다.
    questions_path(--questions, --set과 동시 사용 금지): auto_questions.py 산출 jsonl 한 개 — sets는 그 파일 이름(stem)
    하나뿐인 가짜 세트 목록으로 취급(묶음·stack_matrix 비교·negative는 적용 안 됨, 서버가 가리키는 묶음은 호출자 책임)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    ks = sorted({1, 5, k})
    min_scores = min_scores if min_scores is not None else []
    rename_map = None
    if pool and store_root:
        b = resolve_bundle(store_root, None, pool=True)
        if b and b["rename_map"].exists():
            rename_map = load_rename_map(b["rename_map"])
    q_items, q_raw = load_question_items(questions_path) if questions_path else (None, None)
    hdr = {"X-MCP-Client": "mcp_eval"} | ({"Authorization": f"Bearer {token}"} if token else {})
    report = {
        "ts": time.strftime("%Y%m%d-%H%M%S"),
        "k": k,
        "ks": ks,
        "pool": pool,
        "limit": limit,
        "concurrency": concurrency,
        "methods": METHODS,
        "min_scores": [_status_key(s) for s in min_scores],
        "negative_from": negative_from,
        "questions": questions_path,
        "client_only_env": client_only_env(),
        "sets": {},
    }
    xlsx_data = {} if want_evidence else None
    sem = asyncio.Semaphore(max(1, concurrency))
    async with streamablehttp_client(url, headers=hdr) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            for ds in sets:
                score_ds = QUESTIONS_DS if questions_path else ds
                items, raw = (q_items, q_raw) if questions_path else load_items(ds, rename_map)
                keep = ids_for(ids, ds)
                if keep is not None:
                    items = [it for it in items if it["id"] in keep]
                if limit:
                    items = items[:limit]
                results = await asyncio.gather(*[eval_item(session, sem, score_ds, it, raw, ks, max(ks), min_scores) for it in items])
                rows = [r for r, _ in results]
                entry = {"n": len(rows), "summary": summarize(rows, ks, min_scores), "rows": rows}
                if store_root and not questions_path:
                    b = resolve_bundle(store_root, ds, pool=pool)
                    if b:
                        entry["bundle_skey"] = b["skey"]
                        cmp = find_r_compare(store_root, b["skey"], ds, pool=pool)
                        if cmp:
                            entry["stack_matrix_compare"] = {
                                "r5": cmp.get("r5"),
                                "r10": cmp.get("r10"),
                                "recall_at": cmp.get("recall_at"),
                                "mean_ms": cmp.get("mean_ms"),
                            }
                if negative_from:
                    neg_items = negative_items(store_root, ds, negative_from, negative_limit)
                    if neg_items:
                        neg_results = await asyncio.gather(
                            *[eval_item(session, sem, negative_from, it, None, ks, max(ks), min_scores, negative=True) for it in neg_items]
                        )
                        neg_rows = [r for r, _ in neg_results]
                        entry["negative"] = {
                            "source": negative_from,
                            "n": len(neg_rows),
                            "summary": summarize_negative(neg_rows, min_scores),
                            "rows": neg_rows,
                        }
                report["sets"][ds] = entry
                if want_evidence:

                    def _gold_answer(r):
                        return (
                            r.get("gold_answer")
                            if r.get("gold_answer") is not None
                            else (r.get("answer") if r.get("answer") is not None else r.get("value"))
                        )

                    xlsx_data[ds] = [
                        {
                            "id": it["id"],
                            "question": it["question"],
                            "gold_docs": it.get("gold_docs"),
                            "gold_answer": _gold_answer((raw or {}).get(it["id"]) or {}),
                            "row": row,
                            "evidence": ev,
                        }
                        for it, (row, ev) in zip(items, results)
                    ]
    return report, xlsx_data


# ───────────────────────── 출력(md·html) ─────────────────────────
def render_markdown(report):
    lines = [
        f"# MCP search 범위 축소 평가 — {report['ts']}",
        f"k={report['k']} · methods={'+'.join(report['methods'])} · pool={report['pool']} · concurrency={report['concurrency']}",
        "",
    ]
    if report.get("client_only_env"):
        lines += [
            f"> ⚠ 클라이언트에만 준 서버 설정 {report['client_only_env']} — 서버 프로세스에는 적용되지 않음. "
            "서버를 이 값으로 다시 띄운 경우에만 그 설정의 결과로 읽을 것(GH1-16).",
            "",
        ]
    for ds, e in report["sets"].items():
        s = e["summary"]
        lines.append(f"## {ds} (n={e['n']})")
        hit_str = " · ".join(f"hit@{k} {s.get(f'hit{k}')}" for k in report["ks"])
        lines.append(f"- {hit_str} · value_in_evidence@{report['k']} {s['value_in_evidence']}")
        hit_doc_str = " · ".join(
            f"hit@{k}_doc {s.get(f'hit{k}_doc')}" for k in report["ks"]
        )  # engine-qa BLOCK 3 — 집계 근거 건너뛴 문서 순위
        lines.append(f"- (집계 근거 제외) {hit_doc_str}")
        lines.append(
            f"- 근거 수 평균 {s['n_evidence_avg']} · 응답 바이트 평균 {s['bytes_avg']} · 지연 p50 {s['ms_p50']}ms · p95 {s['ms_p95']}ms"
        )
        lines.append(
            f"- 로컬 임베딩(벡터) 사용 비율 {s['vector_used_rate']} · via v={s['via_v']} k={s['via_k']} i={s['via_i']} · 오류 {s['errors']}"
        )
        cmp = e.get("stack_matrix_compare")
        if cmp:
            lines.append(f"- stack_matrix R 비교(같은 묶음·방법): r5={cmp['r5']} r10={cmp['r10']} recall_at={cmp['recall_at']}")
        elif "bundle_skey" in e:
            lines.append("- stack_matrix R 비교: 없음(같은 설정의 저장본 못 찾음)")
        if s.get("evidence_status"):  # R3 — 문턱마다 found/weak/none 분포
            for key, dist in s["evidence_status"].items():
                lines.append(f"- evidence_status@{key}: {dist}")
        if "agg_n" in s:  # R1 — 집계 문항(aggregate·table_aggregate) hit
            lines.append(f"- 집계 문항 {s['agg_n']}개 · aggregate 경로 감지율 {s['agg_via_rate']} · 정답률 {s['agg_hit_rate']}")
        if any(s.get(f"ref_doc_hit{k}") is not None for k in report["ks"]):  # W20② — qa.json references(문서·image_id) 기준
            ref_str = " · ".join(f"ref_doc_hit@{k} {s.get(f'ref_doc_hit{k}')}" for k in report["ks"])
            lines.append(f"- (W20 참조 적중) {ref_str} · ref_image_hit {s.get('ref_image_hit')}")
        if s.get("attach_hit") is not None:  # W20③ — expected_attachments(기대 첨부 image_id)
            lines.append(f"- (W20 첨부) attach_hit {s['attach_hit']} · attach_precision {s['attach_precision']}")
        neg = e.get("negative")
        if neg:
            lines.append(f"- negative({neg['source']}, n={neg['n']}, '{report.get('negative_from')}' 묶음에 없는 문서가 gold):")
            for key in report.get("min_scores") or []:
                fp, tn = neg["summary"].get(f"false_positive@{key}"), neg["summary"].get(f"true_negative@{key}")
                lines.append(f"  - {key}: 오탐(found) {fp} · 정탐(weak·none) {tn}")
        lines.append("")
    return "\n".join(lines)


def render_html(report, md):
    import html as H

    rows_html = []
    for ds, e in report["sets"].items():
        s = e["summary"]
        hit_cells = "".join(f"<td>{s.get(f'hit{k}')}</td>" for k in report["ks"])
        cmp = e.get("stack_matrix_compare")
        cmp_s = f"r5={cmp['r5']} r10={cmp['r10']}" if cmp else "-"
        rows_html.append(
            f"<tr><td>{H.escape(ds)}</td><td>{e['n']}</td>{hit_cells}"
            f"<td>{s['value_in_evidence']}</td><td>{s['n_evidence_avg']}</td><td>{s['bytes_avg']}</td>"
            f"<td>{s['ms_p50']}</td><td>{s['ms_p95']}</td><td>{s['vector_used_rate']}</td>"
            f"<td>v{s['via_v']}/k{s['via_k']}/i{s['via_i']}</td><td>{cmp_s}</td></tr>"
        )
    hit_heads = "".join(f"<th>hit@{k}</th>" for k in report["ks"])
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>MCP search 범위 축소 평가 — {report["ts"]}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px 10px;text-align:center;font-size:13px}}th{{background:#f0f0f0}}
h1{{font-size:18px}}p{{color:#444}}</style></head><body>
<h1>MCP search 범위 축소 평가 — {report["ts"]}</h1>
<p>k={report["k"]} · methods={"+".join(report["methods"])} · pool={report["pool"]} · concurrency={report["concurrency"]}
· 범위: 하이브리드 수집(vector·bm25·id) → 선별(점수 합산·상위 k) — 재순위·질문 분해·그래프·용어 확장·답 생성 없음</p>
<table><thead><tr><th>세트</th><th>n</th>{hit_heads}<th>value_in_evidence@{report["k"]}</th>
<th>근거 수</th><th>바이트</th><th>p50ms</th><th>p95ms</th><th>벡터 사용률</th><th>via</th><th>stack_matrix 비교</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody></table>
<pre style="margin-top:24px;white-space:pre-wrap">{H.escape(md)}</pre>
</body></html>"""


_EVIDENCE_META_COLS = ["doc_type", "version", "supersedes_doc_id", "is_deleted", "contract_id", "updated_at", "company"]  # AD44(b)
_XLSX_NOTICE = "원문 포함 — 서버 밖 반출 금지"


def write_xlsx(xlsx_data, path):
    """--xlsx: 문항-근거 엑셀(원문 포함, server-result-reading.md 반출 규칙과 맞춤) — 시트 2개: '요약'(문항 1행)·'근거'(문항×순위 1행)."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE  # 실문서 원문의 제어문자(0x00-0x1F)는 openpyxl이 거부 — 지우고 씀(검토 10-07)

    def add(ws, vals):
        ws.append([ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in vals])

    wb = Workbook()
    s = wb.active
    s.title = "요약"
    add(s, [_XLSX_NOTICE])
    add(s, ["세트", "문항 ID", "질문", "정답 문서", "정답 값", "hit@1", "hit@5", "value_in_evidence", "evidence_status"])
    e = wb.create_sheet("근거")
    add(e, [_XLSX_NOTICE])
    add(
        e,
        [
            "세트",
            "문항 ID",
            "순위",
            "file_name",
            "page",
            "line",
            "source_uri",
            "doc_key",
            "chunk_key",
            "client",
            "contract_no",
            "score",
            "via",
            "원문(앞 200자)",
        ]
        + _EVIDENCE_META_COLS,
    )
    for ds, items in xlsx_data.items():
        for it in items:
            row = it["row"]
            gold_docs = ", ".join(sorted(it["gold_docs"])) if it.get("gold_docs") else ""
            status = row.get("status") or {}
            add(
                s,
                [
                    ds,
                    it["id"],
                    it["question"],
                    gold_docs,
                    it.get("gold_answer"),
                    row.get("hit1"),
                    row.get("hit5"),
                    row.get("value_in_evidence"),
                    json.dumps(status, ensure_ascii=False) if status else "",
                ],
            )
            for i, ev in enumerate(it["evidence"]):
                add(
                    e,
                    [
                        ds,
                        it["id"],
                        ev.get("rank") or (i + 1),
                        ev.get("file_name"),
                        ev.get("page"),
                        ev.get("line"),
                        ev.get("source_uri"),
                        ev.get("doc_key"),
                        ev.get("chunk_key"),
                        ev.get("client"),
                        ev.get("contract_no"),
                        ev.get("score"),
                        ev.get("via"),
                        (ev.get("text") or "")[:200],
                    ]
                    + [ev.get(c) for c in _EVIDENCE_META_COLS],
                )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ───────────────────────── CLI ─────────────────────────
def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-bundle", action="store_true", help="평가 대신 서버에 줄 MCP_BUNDLE 경로(+pool rename_map)만 출력")
    ap.add_argument(
        "--set", default="", help="데이터셋 이름(쉼표) — --pool이면 여러 개(한 서버=한 풀 묶음), 아니면 보통 하나(한 서버=한 묶음)"
    )
    ap.add_argument(
        "--questions",
        default="",
        help="auto_questions.py 산출 jsonl(실문서 질문) — --set과 동시 사용 금지. "
        "gold_docs=gold_evidence[].file · 값=answer/value · count 유형·미확인 문서는 채점 제외",
    )
    ap.add_argument("--pool", action="store_true", help="서버가 풀(synth-distractors-v2 묶음)을 가리킴 — gold_docs를 rename_map으로 치환")
    ap.add_argument("--url", default="http://127.0.0.1:18765/mcp")
    ap.add_argument("--token", default="")
    ap.add_argument("--store-root", default="", help="메인 체크아웃 output/store(읍 전용) — 묶음 탐색·stack_matrix 비교용")
    ap.add_argument("--index-id", default="", help="AD41 — 고를 색인(cli/index.py가 만든 index_id) · 비우면 기본 색인")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--ids", default="", help="문항 id만(쉼표·줄 단위 txt·hard-core manifest.json의 retrieval.<세트>) — 원래 묶음 그대로 그 문항만 평가"
    )
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--min-score",
        default="",
        help=f"R3 evidence_status 문턱 후보(쉼표, 'none'=점수 문턱 없이 핵심어만) — 비우면 계산 안 함(기본). 보정표는 '{DEFAULT_MIN_SCORES}'",
    )
    ap.add_argument(
        "--negative-from", default="", help="R3 negative(정답 문서 없는 질문) — 이 세트 문항 중 --set 묶음에 없는 문서가 gold인 것만 섞음"
    )
    ap.add_argument("--negative-limit", type=int, default=None)
    ap.add_argument(
        "--xlsx",
        action="store_true",
        help="문항별 질문·근거(원문 포함) 엑셀도 저장 — 서버 밖 반출 금지(기본 꺼짐, 켜도 json/md/html은 그대로)",
    )
    a = ap.parse_args()
    global INDEX_ID
    INDEX_ID = a.index_id or None

    sets = [s.strip() for s in a.set.split(",") if s.strip()]
    if sets and a.questions:
        ap.error("--set과 --questions는 동시 사용 금지(둘 중 하나)")
    if not sets and not a.questions:
        ap.error("--set 또는 --questions 필요")
    if a.show_bundle:
        if not sets:
            ap.error("--show-bundle은 --set과 함께만")
        for ds in sets:
            b = resolve_bundle(a.store_root, ds, pool=a.pool)
            print(
                json.dumps({"set": ds, **({k: str(v) for k, v in b.items()} if b else {"error": "묶음 없음(bge-m3)"})}, ensure_ascii=False)
            )
        return

    sets = sets or [Path(a.questions).stem]
    min_scores = parse_min_scores(a.min_score) if a.min_score else []
    report, xlsx_data = asyncio.run(
        run_eval(
            a.url,
            a.token,
            sets,
            a.pool,
            a.store_root,
            a.k,
            a.limit,
            a.concurrency,
            min_scores,
            a.negative_from or None,
            a.negative_limit,
            want_evidence=a.xlsx,
            questions_path=a.questions or None,
            ids=a.ids or None,
        )
    )
    md = render_markdown(report)
    print(md)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{report['ts']}_{'+'.join(sets)[:60]}"
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / f"{stem}.md").write_text(md, encoding="utf-8")
    (OUT_DIR / f"{stem}.html").write_text(render_html(report, md), encoding="utf-8")
    if a.xlsx:
        write_xlsx(xlsx_data, OUT_DIR / f"{stem}.xlsx")
        print(f"(엑셀: {OUT_DIR / stem}.xlsx — {_XLSX_NOTICE})")
    print(f"(저장: {OUT_DIR / stem}.{{json,md,html}})")
    # GH1-09 — 보고서는 그대로 쓰고(위), 질의 오류가 있거나 평가 문항이 0건이면 실패로 종료(e2e가 "성공"으로 오인하지 않게)
    if not eval_ok(report):
        sys.exit(1)


if __name__ == "__main__":
    main()
