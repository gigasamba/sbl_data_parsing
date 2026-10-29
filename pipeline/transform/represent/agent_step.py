"""AG11 2단계 — 규칙 흐름이 '애매'로 넘긴 자리에서만 판단 세션(dev/agents/parse_decide)을 연다
(docs/architecture.md '2단계 설계' 표 — 트리거·입력·선택지·되돌이·예산·규칙 복귀·궤적).

규칙 흐름(represent.py: P1 융합 → P2 줄 띠 OCR → P3 그림 경계 OCR·VLM 선택형)은 그대로 기본 계획. 그 뒤에도
`fused.facts[].unverified`로 남은 조각(D9 트리거)만 세션 도구로 다시 읽는다 — 도구는 reread·reread_stage3의 지금 함수를
**호출만** 한다(fuse·figures·vlm_page·prepare 판정 로직 불변, 엔진 원문 P0 재실행 0).

PARSE_AGENT(환경변수) = off | shadow | apply, 기본 **shadow**(OP11 '새 기능 기본 켬'의 예외 — 파싱 결과를 바꾸는 LLM
판단은 PA7 지표가 지금 흐름 대비 같거나 나을 때 apply로 올린다):
  off    — 세션을 안 연다(지금과 바이트 동일).
  shadow — 세션은 rep["fused"]의 **사본**에서만, 결정·궤적은 <parse_dir>/_agent/decisions/<문서>.json에만(rep 바이트 동일).
  apply  — finish로 정상 종료한 세션만 rep["fused"]에 반영 + rep["agent"](기록). 그 밖(모델 없음·예산 초과·finish 없음·
           예외)은 세션 결정을 전부 버리고 규칙 결과 그대로(rep["agent"]에 사유만).
"on"은 옛 설계 이름이라 apply로, "0"·"false"·"none"·""은 off로 읽는다(env 관례 '=0 끔').

예산(문서당): parse_decide agent.json budget(LLM 8·도구 16, seconds 칸은 선언용 — 실제 시간 상한은 아래 env) +
PARSE_AGENT_SESSION_SEC(env, 기본 **180**, RV4 10-09 — 옛 기본 120은 실 GLM 7턴 ≈115초에 닿아 1건 시간 초과 실측,
턴 수(8)는 PA7 근거 정답률 그대로 두고 시간만 늘림, `_session_sec`) + PARSE_AGENT_TOKENS(24,000 — 둘 다 run_agentic 콜백, ADK2) +
PARSE_AGENT_VLM_MAX(3, 도구 층 VLM 장부) + 조각당 다시 읽기 2회(되돌이 상한) + PARSE_AGENT_FRAGS(3, 문서당 조각) +
PARSE_AGENT_MAX_DOCS(50, 프로세스당 세션 문서 수).
가짜 모델: PARSE_AGENT_FAKE=1 + LLM_FAKE=1이면 fake_policy(결정적 정책)로 run_agentic을 실제로 돈다(네트워크 0).
VLM은 vlm_fn 주입(시험·하네스) 또는 실제 adk.complete(VLM 미설정이면 그 판독만 '미설정' 오류 — 세션은 계속).

3단계(10-08, 설계 '3단계 설계' 절) — 같은 세션·같은 상한에 조각 종류 둘을 더한다(문서당 PARSE_AGENT_FRAGS 합계):
  (a) 근소 조각(PARSE_AGENT_NEAR, 기본 켬·=0 끔): unverified는 아니지만 P1이 보조 신호로만 가른 자리(conflicts의
      split=True·resolved_by="heuristic") 중 1·2위 점수 차 ≤ PARSE_AGENT_MARGIN(기본 = P2 FUSE_REREAD_MARGIN).
  (c) 그림 조각(PARSE_AGENT_FIG, 기본 켬·=0 끔): 그림 VLM 기록의 값이 본문 언급과 갈린 자리(figures value_check.conflict)
      — 다시 읽기는 그림 크롭 OCR·VLM. 결정은 기록(figure_checks)까지 — 그림 기록·본문 블록은 다시 쓰지 않는다.
  (b) PARSE_AGENT_MODEL=split|vlm(기본 split = LLM 판단 + VLM 판독) — vlm이면 이미지 있는 문서(vlm_session)의 판단
      세션도 VLM(parse_decide_vlm, AG6 M2 — 판단·판독 같은 모델, 맥락 누적). 이미지 없는 문서는 그대로 LLM.
"""

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

from common.config import settings as C  # common 칸 설정 객체(S7c)
from common.core.paths import (
    APP_ROOT,  # 폴더 재편 뒤 이 상수만 바뀌면 됨
    atomic_write_text,  # RV6, tmp+os.replace 공용
)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.transform.represent import reread as reread_mod  # P2 함수(render_crop·reread_once·reread_matches·_default_ocr)
from pipeline.transform.represent import reread_stage3 as p3_mod  # P3 함수(p3_once·_candidate_groups·_parse_answer·_default_vlm_call)
from pipeline.transform.represent.fuse import _fact_key

AGENT_ID = "parse_decide"
MODES = ("off", "shadow", "apply")
METHODS = ("vlm_context", "ocr_page", "vlm_choice", "ocr_images", "ocr_band")  # fake_policy가 고르는 순서이기도 함
FIG_METHODS = ("ocr_figure", "vlm_context", "vlm_choice", "ocr_page")  # 그림 조각(3단계 c) — 모델 0인 크롭 OCR 먼저
VLM_METHODS = {"vlm_choice", "vlm_context"}
REREAD_MAX = 2  # 조각당 다시 읽기(되돌이) 상한
FRAGS_MAX = pc.cfg().transform.agent.frags  # S7c — 설정 객체(아래 모듈 상수 — import 때 한 번)
VLM_MAX = pc.cfg().transform.agent.vlm_max
MAX_DOCS = pc.cfg().transform.agent.max_docs
BATCH_SEC = pc.cfg().transform.agent.batch_sec  # 프로세스(배치) 하나의 판단 세션 시간 합 상한(engine-qa 10-08)
TOKENS_MAX = pc.cfg().transform.agent.tokens  # 세션당 LLM 토큰(입력+출력) — run_agentic 콜백이 강제(ADK2)
NEAR_ON = pc.cfg().transform.agent.near  # 3단계 (a) — 기본 켬(사용자 결정 1 '확대')
_margin = pc.cfg().transform.agent.margin  # 기본값 None 칸 — 없음·'' = 아래에서 reread_mod.MARGIN(옛 `or`와 같음, "0"은 0.0)
NEAR_MARGIN = _margin if _margin is not None else reread_mod.MARGIN
FIG_ON = pc.cfg().transform.agent.fig  # 3단계 (c) — 기본 켬
CTX_HEAD, CTX_MAX = 600, 1200  # VLM 맥락: 대표 본문 앞 600자 + 앞선 판독 누적, 전체 1,200자
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
_VLM_CACHE_DIR = APP_ROOT / "output" / "parse" / "_agent" / "_vlm_cache"  # 쓰기는 output/만(C4)
_docs_used = 0
_batch_spent = 0.0  # 이 프로세스에서 판단 세션에 쓴 초(BATCH_SEC와 비교)


def mode(config=None):
    """PARSE_AGENT → off|shadow|apply(기본 shadow). 모르는 값은 조용히 넘기지 않고 ValueError."""
    if config is None:  # S7c — 설정 객체(기본값 None 글자 칸: 없음 = "shadow", 빈 글자는 '' 그대로 → off — 옛 get(X, "shadow")과 같음)
        config = pc.cfg().transform.agent.enabled
        config = "shadow" if config is None else config
    v = str(config).strip().lower()
    if v in ("", "0", "false", "none"):
        return "off"
    if v == "on":
        return "apply"
    if v not in MODES:
        raise ValueError(f"PARSE_AGENT={v!r} — off|shadow|apply 중 하나")
    return v


def model_mode(config=None):
    """PARSE_AGENT_MODEL → split(기본, 판단 LLM + 판독 VLM) | vlm(이미지 문서는 판단도 VLM — AG6 M2). 모르는 값은 ValueError."""
    v = (
        (pc.cfg().transform.agent.model or "split") if config is None else str(config)
    ).strip().lower() or "split"  # S7c — 설정 객체(글자 칸 — '' = 기본 split)
    if v not in ("split", "vlm"):
        raise ValueError(f"PARSE_AGENT_MODEL={v!r} — split|vlm 중 하나")
    return v


def has_image(rep, doc_path):
    """문서별 VLM 세션 트리거(규칙): 이미지가 하나라도 — 그림 기록·쪽 VLM·쪽 신호 이미지 면적·이미지 형식."""
    post = rep.get("post") or {}
    if (post.get("figures") or 0) > 0 or (post.get("vlm_page_calls") or 0) > 0:
        return True
    if any((p.get("image_area_ratio") or 0) > 0 for p in (rep.get("context") or {}).get("page") or []):
        return True
    return bool(doc_path) and Path(doc_path).suffix.lower() in _IMAGE_EXT


def near(fused):
    """3단계 (a) — 규칙이 '확인'으로 넘겼지만 근소한 조각: unverified 아님 · 같은 라벨 conflicts가 split=True·
    resolved_by="heuristic"(기본 점수 동점을 보조 신호만으로 가름) · 1위 점수 − 최선 패자 점수 ≤ NEAR_MARGIN."""
    if not NEAR_ON:
        return []
    conf = {c["label"]: c for c in (fused or {}).get("conflicts") or [] if c.get("label")}
    out = []
    for f in (fused or {}).get("facts") or []:
        c = conf.get((f.get("context") or [None])[0])
        if f.get("unverified") or not c or not c.get("split") or c.get("resolved_by") != "heuristic" or not c.get("losers"):
            continue
        if f.get("score") is not None and f["score"] - max(lo["score"] for lo in c["losers"]) <= NEAR_MARGIN:
            out.append(f)
    return out


def pending(fused):
    """D9 트리거 — P1→P2→P3 뒤에도 unverified이고 P2가 쪽을 찾은 조각 먼저, 그다음 근소 조각(near), 합쳐 앞 FRAGS_MAX개."""
    unv = [f for f in (fused or {}).get("facts") or [] if f.get("unverified") and (f.get("reread") or {}).get("page")]
    return (unv + near(fused))[:FRAGS_MAX]


def figure_pending(fig_records):
    """3단계 (c) — 그림 VLM 기록 값이 본문 언급과 갈린 자리(value_check.conflict) → [{image_id, page, png_path, label,
    figure, body}] (그림 id·라벨 순, 결정적). fig_records = represent.apply_post(fig_sink=)가 모은 갈림 그림만."""
    if not FIG_ON:
        return []
    out = []
    for r in sorted(fig_records or [], key=lambda r: r["image_id"]):
        for label, v in sorted((r.get("conflict") or {}).items()):
            out.append(
                {
                    "image_id": r["image_id"],
                    "page": r.get("page"),
                    "png_path": r.get("png_path"),
                    "label": label,
                    "figure": str(v["그림"]),
                    "body": str(v["본문"]),
                }
            )
    return out


def _vlm_configured():
    vm = C.cfg().models.vlm  # S7c — 설정 객체(common 칸 — 한 번 읽어 묶음, VS7c2 R-10)
    return bool(vm.base_url and vm.model)


def _ctx_vlm_call(png_bytes, cand_texts, context):
    """value_choice_ctx(맥락 포함 새 prompt_id) — 가드·내부망·NO_PAID_CALLS는 adk.complete가 집행."""
    import base64

    from common.ai import adk as A
    from common.ai.agent_prompts import tail, template

    prompt = (
        template("value_choice_ctx", "choose_ctx")
        + "\n\n"
        + context
        + "\n후보: "
        + json.dumps(cand_texts, ensure_ascii=False)
        + tail("value_choice_ctx")
    )
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png_bytes).decode()}},
            ],
        }
    ]
    try:
        text, _u = A.complete(
            "vlm",
            msgs,
            temperature=0,
            max_tokens=pc.cfg().transform.represent.reread.vlm_max_tokens,  # S7c — 설정 객체
            timeout=pc.cfg().transform.vlm.deadline,
            agent="value_choice_ctx",
        )
    except A.ModelUnavailable:  # GuardBlocked 포함 — 이 판독만 NONE
        return ""
    return text


def _vlm_pick(png, cands, method, context, vlm_fn):
    """VLM 선택형 1회 → (맞은 후보 dict 또는 None, cached). vlm_fn(png, cand_texts, context) 주입이면 캐시 안 씀
    (가짜 답이 실제 캐시에 섞이지 않게). 실제 경로는 (prompt·크롭 sha·후보·맥락) 열쇠로 output/ 캐시."""
    texts = [c["text"] for c in cands]
    cached = False
    if vlm_fn is not None:
        answer = p3_mod._parse_answer(vlm_fn(png, texts, context))
    else:
        key = hashlib.sha256(json.dumps([method, hashlib.sha256(png).hexdigest(), texts, context], ensure_ascii=False).encode()).hexdigest()
        cp = _VLM_CACHE_DIR / f"{key}.json"
        if cp.exists():
            answer, cached = json.loads(cp.read_text(encoding="utf-8"))["answer"], True
        else:
            raw = _ctx_vlm_call(png, texts, context) if method == "vlm_context" else p3_mod._default_vlm_call(png, texts)
            answer = p3_mod._parse_answer(raw)
            if raw:  # 빈 응답(실패·차단)은 캐시에 안 남김 — 다음에 다시 물을 수 있게
                cp.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(cp, json.dumps({"answer": answer}, ensure_ascii=False))
    hits = [c for c in cands if answer and answer != "NONE" and c["text"] == answer]
    return (hits[0] if len(hits) == 1 else None), cached


def session_tools(doc_path, fused, groups, *, doc_head="", vlm_session=False, vlm_fn=None, ocr_fn=None, fig_frags=()):
    """문서 1건의 판단 세션 도구 4개 + 세션 상태 S(조각·재판독 이력·근거·VLM 장부·맥락 누적·결정). fused는 호출자가
    준 것(shadow면 사본)을 제자리에서 바꾼다 — decide_fragment(adopt|human|keep)만 바꾼다. 조각 종류: "text"(fused 조각 —
    unverified·근소) · "figure"(3단계 c — 그림 VLM 값 vs 본문, figure_pending 결과; 결정은 S["figure_checks"]에만)."""
    frags = []
    p3_ran = "p3" in ((fused or {}).get("reread") or {}) and not (fused["reread"]["p3"] or {}).get("skip_reason")
    is_pdf = bool(doc_path) and Path(doc_path).suffix.lower() == ".pdf"
    for f in pending(fused):
        g = (groups or {}).get(_fact_key(f))
        rr = f.get("reread") or {}
        if not g or not (rr.get("page") or is_pdf):
            continue
        if rr.get("page"):
            page, bbox = rr["page"], rr.get("bbox")
        else:  # 근소 조각인데 P2가 쪽을 못 남긴 자리 — P2와 같은 규칙으로 자리 찾기(모델 0)
            pidx, bbox = reread_mod.locate_region(doc_path, [g["text"]] + [lo["text"] for lo in g["losers"]])
            page = pidx + 1
        tried = (["ocr_band"] if rr else []) + (["ocr_images"] if f.get("unverified") and p3_ran else [])
        frags.append(
            {
                "kind": "text",
                "fact": f,
                "group": g,
                "page": page,
                "bbox": bbox,
                "tried": tried,
                "label": (f.get("context") or [None])[0],
                "cands": [g] + list(g["losers"]),
            }
        )
    for ff in list(fig_frags)[: max(0, FRAGS_MAX - len(frags))]:
        frags.append(
            {
                "kind": "figure",
                "fig": ff,
                "page": ff.get("page"),
                "bbox": None,
                "tried": ["figure_vlm"],
                "label": ff["label"],  # 후보 글 = "라벨 값" — 값만(짧은 숫자)이면 쪽 번호처럼 토큰에서 빠져 재판독이 못 맞힘
                "cands": [
                    {"text": f"{ff['label']} {ff['body']}", "value": ff["body"], "engines": ["본문"]},
                    {"text": f"{ff['label']} {ff['figure']}", "value": ff["figure"], "engines": ["그림 VLM"]},
                ],
            }
        )
    S = {
        "n": len(frags),
        "rereads": {},
        "evidence": {},
        "decisions": {},
        "vlm_calls": 0,
        "ctx_answers": [],
        "finished": None,
        "figure_checks": [],
        "closed": False,
        "deadline": None,
    }
    # 세션 상태 잠금(engine-qa 10-08 MAJOR) — ADK는 한 모델 응답의 tool_call 여러 개를 동시에 돌린다(google.adk.flows.
    # llm_flows._batch_tool_executor._gather_or_cancel = asyncio.gather) + 도구는 _off_loop로 to_thread → 스레드 여럿이
    # S를 동시에 고칠 수 있다. 규칙: S를 읽고 쓰는 구간·예산 차감은 전부 lock 안, 렌더·OCR·VLM(느린 I/O)은 lock 밖.
    # reread는 lock 안에서 '예약'(이력 자리·VLM 차감) → lock 밖 I/O → lock 안에서 '확정'(closed면 버림) 순서.
    lock = threading.Lock()

    def _frag(fid):
        try:
            return frags[int(fid)]
        except (ValueError, TypeError, IndexError):
            return None

    def _methods(fr):
        return list(FIG_METHODS if fr["kind"] == "figure" else METHODS)

    def _late():
        """세션이 닫혔거나(step이 끝냄) 시간 상한을 넘김 — lock 안에서 부른다."""
        if S["closed"]:
            return "세션 종료 뒤 호출(버림)"
        if S["deadline"] is not None and time.monotonic() >= S["deadline"]:
            return "세션 시간 상한 — finish 하세요"
        return None

    def list_fragments():
        """확인 못 한 조각 목록 — 종류(text·figure)·라벨·후보(글자·엔진·점수)·쪽·이미 해 본 방법·고를 수 있는 방법·남은 VLM 예산."""
        with lock:
            return _list_locked()

    def _list_locked():
        return {
            "fragments": [
                {
                    "id": i,
                    "kind": fr["kind"],
                    "label": fr["label"],
                    "candidates": [{"text": c["text"], "engines": c.get("engines"), "score": c.get("score")} for c in fr["cands"]],
                    "page": fr["page"],
                    "tried": fr["tried"],
                    "methods": _methods(fr),
                }
                for i, fr in enumerate(frags)
            ],
            "vlm_left": VLM_MAX - S["vlm_calls"],
            "vlm_session": vlm_session,
        }

    def reread_fragment(fragment_id: int, method: str):
        """조각 하나를 method(list_fragments가 준 그 조각의 methods 중 하나)로 다시 읽어 후보 중 맞은 것을 돌려줌."""
        fr = _frag(fragment_id)
        with lock:  # ① 예약 — 검사·이력 자리·VLM 차감을 한 번에(경합 없음)
            out = {"fragment_id": fragment_id, "method": method, "vlm_left": VLM_MAX - S["vlm_calls"]}
            if fr is None:
                return {**out, "error": f"조각 {fragment_id} 없음(0..{len(frags) - 1})"}
            fid = int(fragment_id)
            late = _late()
            if late:
                return {**out, "error": late}
            if method not in _methods(fr):
                return {**out, "error": f"이 조각에 안 맞는 method — {_methods(fr)} 중 하나"}
            hist = S["rereads"].setdefault(fid, [])
            prev = next((h for h in hist if h["method"] == method), None)
            if prev is not None:  # 같은 방법 재호출 — 앞 결과 재사용(비용 0, 횟수 안 셈)
                if prev.get("pending"):
                    return {**out, "error": "같은 방법이 아직 읽는 중(동시 호출)"}
                return {**out, "matched": prev["matched"], "repeat": True}
            if len(hist) >= REREAD_MAX:
                return {**out, "error": f"되돌이 상한 — 조각당 다시 읽기 {REREAD_MAX}회"}
            if method == "ocr_page" and not (is_pdf and fr["page"]):
                return {**out, "error": "ocr_page는 쪽을 아는 PDF만"}
            if method in VLM_METHODS:
                if S["vlm_calls"] >= VLM_MAX:
                    return {**out, "error": f"VLM 예산 소진(문서당 {VLM_MAX})"}
                if vlm_fn is None and not _vlm_configured():
                    return {**out, "error": "VLM 미설정(VLM_BASE_URL·VLM_MODEL)"}
                S["vlm_calls"] += 1  # 호출 전에 차감(실패해도 셈 — 2단계와 같음)
            slot = {"method": method, "matched": None, "pending": True}
            hist.append(slot)
            ctx_answers = list(S["ctx_answers"])
        cands, label = fr["cands"], fr["label"] or ""
        win, losers = cands[0], cands[1:]
        info = {}
        try:  # ② I/O — lock 밖(렌더·OCR·VLM은 느림)
            if method == "ocr_band":
                rr = reread_mod.reread_once(doc_path, win, losers, ocr_fn)
                if "error" in rr:
                    raise RuntimeError(rr["error"])
                match = rr["match"]
            elif method == "ocr_images":
                res = p3_mod.p3_once(doc_path, fr["page"], fr["bbox"], win, losers, ocr_fn=ocr_fn, vlm_allowed=False)
                match = res["img_match"]
            elif method == "ocr_page":
                text = (ocr_fn or reread_mod._default_ocr)(reread_mod.render_crop(doc_path, fr["page"] - 1, None))
                match = reread_mod.reread_matches(text, win, losers)
            elif method == "ocr_figure":  # 그림 VLM이 본 바로 그 그림 이미지를 OCR — 모델 0
                match = reread_mod.reread_matches(
                    (ocr_fn or reread_mod._default_ocr)(Path(fr["fig"]["png_path"]).read_bytes()), win, losers
                )
            else:
                if fr["kind"] == "figure":
                    png = Path(fr["fig"]["png_path"]).read_bytes()
                elif method == "vlm_context":  # 문서별 VLM 세션 — 쪽 전체 + 맥락
                    png = reread_mod.render_crop(doc_path, fr["page"] - 1, None)
                else:  # P3와 같은 줄 띠 크롭, 맥락 없음
                    png = reread_mod.render_crop(doc_path, fr["page"] - 1, fr["bbox"])
                context = ""
                if method == "vlm_context":  # 맥락: 대표 본문 앞부분(+이미지 문서면 앞선 판독 누적)
                    ctx = "[문서 맥락] " + doc_head[:CTX_HEAD]
                    if vlm_session and ctx_answers:
                        ctx += "\n앞서 확인: " + "; ".join(ctx_answers)
                    context = ctx[:CTX_MAX] + f"\n항목: {label}"
                match, cached = _vlm_pick(png, cands, method, context, vlm_fn)
                info = {"context_chars": len(context), "cached": cached}
        except Exception as ex:  # 렌더·OCR 실패는 이 판독만(크래시 대신 기록)
            with lock:
                hist.remove(slot)  # 실패는 되돌이 횟수에 안 셈(2단계와 같음)
            return {**out, "error": f"{type(ex).__name__}: {ex}"[:200]}
        with lock:  # ③ 확정 — 닫힌 세션이면 늦은 결과 버림
            if S["closed"]:
                hist.remove(slot)
                return {**out, "error": "세션 종료 뒤 결과(버림)"}
            matched = match["text"] if match else None
            slot.pop("pending")
            slot.update(matched=matched, **info)
            if matched is not None:
                S["evidence"].setdefault(fid, {})[matched] = method
                if method in VLM_METHODS and vlm_session:
                    S["ctx_answers"].append(f"{label}={matched}")
            return {**out, "matched": matched, "vlm_left": VLM_MAX - S["vlm_calls"], **info}

    def decide_fragment(fragment_id: int, action: str, value: str = ""):
        """adopt(이 세션 재판독이 맞힌 후보만) · keep(규칙 값 유지) · human(사람 확인 꼬리표)."""
        with lock:  # 결정은 I/O 없음 — 통째로 lock(fused 제자리 변경 포함)
            if S["closed"]:
                return {"ok": False, "fragment_id": fragment_id, "error": "세션 종료 뒤 호출(버림)"}
            return _decide_locked(fragment_id, action, value)

    def _decide_locked(fragment_id, action, value):
        fr = _frag(fragment_id)
        if fr is None:
            return {"ok": False, "fragment_id": fragment_id, "error": "조각 없음"}
        fid = int(fragment_id)
        if fid in S["decisions"]:
            return {"ok": False, "fragment_id": fid, "error": "이미 결정함"}
        if action not in ("adopt", "keep", "human"):
            return {"ok": False, "fragment_id": fid, "error": "action은 adopt|keep|human"}
        method = (S["evidence"].get(fid) or {}).get(value) if action == "adopt" else None
        if action == "adopt" and method is None:
            return {"ok": False, "fragment_id": fid, "error": "근거 없음 — 이 세션 재판독이 맞힌 후보만 adopt"}
        if fr["kind"] == "figure":  # 그림 조각 — 기록만(그림 기록·본문 블록은 안 바꿈)
            ff = fr["fig"]
            picked = next((c["value"] for c in fr["cands"] if c["text"] == value), None) if action == "adopt" else None
            S["figure_checks"].append(
                {
                    "image_id": ff["image_id"],
                    "label": ff["label"],
                    "figure": ff["figure"],
                    "body": ff["body"],
                    "decision": action,
                    "value": picked,
                    "method": method,
                    "needs_review": action == "human",
                }
            )
        elif action == "adopt":
            fact = fr["fact"]
            cand = next(c for c in fr["cands"] if c["text"] == value)
            was = fact["value"]
            fact["value"], fact["engines"], fact["score"] = value, cand.get("engines"), cand.get("score", fact.get("score"))
            fact["unverified"] = False
            fact["agent"] = {"decision": "adopt", "method": method, "was": was}
            if value != was:  # conflicts의 그 자리 승자·패자 맞바꿈(reread_stage3._apply_p3_match와 같은 취지)
                for c in fused.get("conflicts") or []:
                    if c.get("label") == fr["label"]:
                        c["losers"] = [{"engines": fr["group"]["engines"], "text": was, "score": fr["group"]["score"]}] + [
                            lo for lo in c.get("losers") or [] if lo["text"] != value
                        ]
                        c["winner"], c["winner_engines"] = value, cand.get("engines")
        elif action == "human":
            fr["fact"]["needs_review"] = True
            fr["fact"]["agent"] = {"decision": "human"}
        else:
            fr["fact"]["agent"] = {"decision": "keep"}
        S["decisions"][fid] = {"action": action, "value": value if action == "adopt" else None, "label": fr["label"], "kind": fr["kind"]}
        return {"ok": True, "fragment_id": fid, "action": action}

    def finish(reason: str = ""):
        """세션 끝(D11) — 반드시 마지막에 한 번. 안 부르면 결정은 버려진다."""
        with lock:
            if S["closed"]:
                return {"ok": False, "error": "세션 종료 뒤 호출(버림)"}
            S["finished"] = {"reason": str(reason)[:200], "undecided": len(frags) - len(S["decisions"])}
            return {"ok": True, **S["finished"]}

    def close():
        """step이 세션을 끝낼 때 — 이후 도구 호출·늦게 끝난 I/O 결과는 전부 버림(lock 안에서 표시)."""
        with lock:
            S["closed"] = True

    S["close"] = close
    return {fn.__name__: fn for fn in (list_fragments, reread_fragment, decide_fragment, finish)}, S


def fake_policy(results):
    """가짜 판단 모델(결정적) — 조각마다 그 조각 methods 순서(글자 조각 vlm_context 먼저 · 그림 조각 ocr_figure 먼저)로
    → 못 맞히면 다음 방법으로 되돌이(최대 2회) → 맞으면 adopt, 아니면 human → finish. results = [(도구 이름, 응답 dict), ...]."""
    if not results:
        return ("call", "list_fragments", {})
    names = [n for n, _ in results]
    if "finish" in names:
        done = sum(1 for n, r in results if n == "decide_fragment" and r.get("ok"))
        return ("text", json.dumps({"done": True, "decided": done}))
    frags = results[0][1].get("fragments") or []
    vlm_left = next((r["vlm_left"] for _n, r in reversed(results) if "vlm_left" in r), 0)
    for f in frags:
        fid = f["id"]
        if any(n == "decide_fragment" and r.get("ok") and r.get("fragment_id") == fid for n, r in results):
            continue
        rr = [r for n, r in results if n == "reread_fragment" and r.get("fragment_id") == fid]
        hit = next((r["matched"] for r in rr if r.get("matched")), None)
        if hit is not None:
            return ("call", "decide_fragment", {"fragment_id": fid, "action": "adopt", "value": hit})
        tried = set(f.get("tried") or []) | {r.get("method") for r in rr}
        if sum(1 for r in rr if not r.get("error")) < REREAD_MAX:
            for m in f.get("methods") or METHODS:
                if m not in tried and not (m in VLM_METHODS and vlm_left <= 0):
                    return ("call", "reread_fragment", {"fragment_id": fid, "method": m})
        return ("call", "decide_fragment", {"fragment_id": fid, "action": "human"})
    return ("call", "finish", {"reason": "조각 전부 결정"})


def _off_loop(fn):
    """동기 도구 → 같은 이름·서명의 async 도구(본문은 asyncio.to_thread). ADK는 동기 도구를 이벤트 루프 스레드에서 바로
    부르는데, run_agent의 루프는 adk._loop() 공용 루프 하나라 도구 안의 실 VLM 호출(adk.complete → _run_async)이 같은
    루프에 일을 넣고 기다리면 영원히 멈춘다(10-08 기능 시험 ① 실측 — 가짜 VLM 주입 경로에선 안 드러남)."""
    import asyncio
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    return wrapper


def _session_sec(agent_id):
    """판단 세션 한 번의 시간 상한 — PARSE_AGENT_SESSION_SEC(env, 기본 **180**, RV4 10-09). 패키지 agent.json의
    budget.seconds(120, 옛 값)는 agentic 틀의 선언 계약(LLM·도구 호출 수)만 남기고 시간은 이 env가 덮는다 —
    실 GLM 7턴 ≈115초가 120초에 닿은 실측(parse-agent-design.md '3단계 설계') 때문에 운영 상한만 올림."""
    return pc.cfg().transform.agent.session_sec  # S7c — 설정 객체


def _run_session(msg, tools, policy, agent_id=AGENT_ID, role="llm", sec=None):
    from google.genai import types

    from common.ai import adk as A

    contents = types.Content(role="user", parts=[types.Part.from_text(text=msg)])
    if policy is None and pc.cfg().dev.parse_agent_fake:  # S7c — 설정 객체(on=("1",) = 옛 =="1")
        policy = fake_policy
    return A.run_agent(
        agent_id,
        contents,
        role=role,
        tools={k: _off_loop(f) for k, f in tools.items()},
        fake_policy=policy,
        token_budget=TOKENS_MAX,
        timeout=sec,
        soft_deadline=sec,
        per_turn_admit=True,
    )  # GH1-08b — run_all --procs가 문서마다 동시에 세션을 열 수 있어(겹치는 run_agent()) 턴 단위 공유 장부가 필요(옵트인, PARSE_AGENT 경로만)


def step(
    rep,
    doc,
    doc_path,
    engine_docs,
    rep_engine,
    parse_dir,
    *,
    agent_mode=None,
    vlm_fn=None,
    ocr_fn=None,
    policy=None,
    fig_records=None,
    model=None,
):
    """represent()가 대표 결과를 쓰기 직전에 부른다. 트리거 없으면 None(아무것도 안 씀). 있으면 세션을 돌려 기록 dict를
    돌려주고, shadow면 <parse_dir>/_agent/decisions/<문서>.json에만 · apply면 rep["agent"](+정상 종료 시 rep["fused"]).
    fig_records = represent.apply_post(fig_sink=)가 모은 '그림 VLM 값 ↔ 본문 갈림' 그림(3단계 c) · model = PARSE_AGENT_MODEL."""
    global _docs_used, _batch_spent
    m = mode(agent_mode)
    if m == "off" or not doc_path:
        return None
    fused = rep.get("fused")
    text_frags = pending(fused) if fused and engine_docs else []
    fig_frags = figure_pending(fig_records)
    if not text_frags and not fig_frags:
        return None
    vlm_session = has_image(rep, doc_path)
    agent_id, role = ("parse_decide_vlm", "vlm") if model_mode(model) == "vlm" and vlm_session else (AGENT_ID, "llm")
    record = {
        "mode": m,
        "doc": doc,
        "agent": agent_id,
        "role": role,
        "trigger": {
            "d9_fragments": len(text_frags),
            "near": sum(1 for f in text_frags if not f.get("unverified")),
            "figure": len(fig_frags),
            "vlm_session": vlm_session,
        },
    }
    if _docs_used >= MAX_DOCS:
        record.update(status="skipped", reason=f"PARSE_AGENT_MAX_DOCS={MAX_DOCS} 도달", applied=False)
    elif _batch_spent >= BATCH_SEC:  # 배치 시간 예산 — 남은 문서는 세션 없이 규칙 결과(사유 기록)
        record.update(status="skipped", reason=f"PARSE_AGENT_BATCH_SEC={BATCH_SEC:g} 도달(쓴 {_batch_spent:.0f}초)", applied=False)
    else:
        work = copy.deepcopy(fused) if fused else None
        groups = p3_mod._candidate_groups(engine_docs, rep_engine) if text_frags else {}
        tools, S = session_tools(
            doc_path,
            work,
            groups,
            doc_head=(rep.get("text") or "")[:CTX_HEAD],
            vlm_session=vlm_session,
            vlm_fn=vlm_fn,
            ocr_fn=ocr_fn,
            fig_frags=fig_frags,
        )
        if S["n"] == 0:  # 후보 그룹·쪽을 못 맞춘 조각뿐 — 세션 열 거리 없음(모델 0회, 아무것도 안 씀)
            return None
        _docs_used += 1
        from common.ai.agent_prompts import tail, template

        msg = (
            template(AGENT_ID, "decide") + f"\n\n[문서 신호] doc={doc} format={(rep.get('rep') or {}).get('format')} "
            f"vlm_session={str(vlm_session).lower()} fragments={S['n']}" + tail(AGENT_ID)
        )
        sec = min(_session_sec(agent_id), BATCH_SEC - _batch_spent)  # 배치에 남은 시간보다 길게 안 엶
        record["session_sec"] = round(sec, 1)
        t0 = time.time()
        S["deadline"] = time.monotonic() + sec  # 도구도 상한 뒤엔 안 읽음(_late)
        try:
            text, trajectory, usage = _run_session(msg, tools, policy, agent_id, role, sec)
            status = (
                "finished"
                if S["finished"]
                else "budget"
                if text == "예산 초과"
                else "timeout"
                if text == "시간 상한"
                else "call_cap"
                if text == "공유 호출 상한"  # GH1-08b(독립 검토): 턴 단위 상한 거부를 no_finish와 구분
                else "no_finish"
            )
        except Exception as ex:  # 세션 경계: 모델 없음·가드·예산(PlatformError)·그 밖 전부 → 규칙 복귀(사유 기록)
            text, trajectory, usage = "", [], {}
            status = (
                "no_model"
                if type(ex).__name__ in ("ModelUnavailable", "GuardBlocked")
                else "timeout"
                if isinstance(ex, TimeoutError)  # agent.json budget.seconds(run_agentic)
                else "budget"
                if "budget exceeded" in str(ex)
                else "error"
            )  # 도구·토큰 예산(PlatformError)
            record["error"] = f"{type(ex).__name__}: {str(ex)[:200]}"
        S["close"]()  # 시간 초과로 버려진 도구 스레드(to_thread)가 늦게 끝나도 세션 상태를 안 바꾸게(lock 안)
        _batch_spent += time.time() - t0
        record.update(
            status=status,
            applied=(m == "apply" and status == "finished"),
            text=(text or "")[:500],
            trajectory=trajectory,
            usage=usage,
            vlm_calls=S["vlm_calls"],
            finish=S["finished"],
            rereads={str(k): v for k, v in S["rereads"].items()},
            decisions={str(k): v for k, v in S["decisions"].items()},
            figure_checks=S["figure_checks"],
            sec=round(time.time() - t0, 3),
        )
        if record["applied"] and work is not None:
            rep["fused"] = work
    if m == "apply":
        rep["agent"] = record
    else:
        out = Path(parse_dir) / "_agent" / "decisions" / f"{doc}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(record, ensure_ascii=False, indent=1))  # 원자적 쓰기(engine-qa 10-08 권고 — 다중 프로세스 대비)
    return record
