"""AD29 P3 — P2(`reread.py`)가 "unverified"로 남긴 자리만 더 본다(AD26 (d) "갈린 자리만 VLM 선택형 재판독").

P2는 글자층 bbox 둘레를 고정 여백(PAD_PT)만큼 넓힌 "줄 띠"만 다시 OCR한다 — 값이 글자층에서 ~40pt 안에 있으면
맞지만, 값이 **그림(삽입 이미지) 안에만** 있고 그 그림이 줄 띠보다 멀리 있으면(judge-conflicts numfmt-003·
numfmt-005, 글자층엔 일부러 틀린 "430.000"만 있고 "430,000"·"6배치"는 각각 딴 그림 두 장 안에만 있음) 못 찾는다.
줄 띠를 넓히면(PAD_PT를 70~90pt로) 그 그림까지는 담기지만, 줄 간격이 좁은 표(typos-006)에서는 바로 옆의 **다른**
값까지 같이 담겨 오탐이 생긴다(reread.py PAD_PT 주석 실측). 이 모듈은 줄 띠를 넓히는 대신, 쪽에 실제로 박힌
그림의 **경계**(pymupdf `get_image_info`)를 그대로 써서 그 조각 bbox에 가장 가까운 그림만 다시 OCR한다 — 표
간격과 무관(표엔 보통 삽입 그림이 없음)하고, 그림이 하나뿐이면 오탐 여지도 없다.

두 단계(P2가 unverified로 남긴 자리만, 문서당 상한 안에서):
  ① 그림 경계 OCR — 그 자리 bbox에 가장 가까운 그림(최대 `FUSE_REREAD_P3_IMG_MAX`장)을 HIGH_DPI로 다시 렌더해
     (P2와 같은 로컬 rapidocr 경로) 후보와 맞는지 본다(P2 `reread_matches`와 같은 판정 — 모델 호출 0). 그림 하나씩
     다 못 맞춰도 **그 쪽에 그림이 있으면**(이 가지의 전제 — 표는 보통 삽입 그림이 없어 안 탐) 쪽 전체를 한 번 더
     OCR해 본다(여전히 모델 호출 0) — 값이 그림 두 장에 나뉘어 있거나(numfmt-003·numfmt-005, 그림 한 장엔
     "430,000"만·다른 한 장엔 "6배치"만) 후보 글 자체가 머리말까지 묶어 읽은 긴 글이라 그림 한 장만으론 "자기만의
     토큰"을 다 못 채우는 경우를 잡는다. PAD_PT를 넓히는 것과 달리 "그림이 있는 쪽"일 때만 쪽 전체를 보므로
     이웃 표 칸을 잘못 담는 위험(typos-006류 빽빽한 표, PAD_PT 주석의 그 오탐)과는 무관하다(표엔 그림이 없음).
  ② VLM 선택형 — ①도 못 맞췄을 때만(그림이 없거나 OCR로도 모호함), 크롭(① 수집한 그림 중 첫 번째, 없으면 P2와
     같은 줄 띠 크롭) + 후보 목록을 내부 VLM(`dev/agents/value_choice`)에 보여 후보 중 하나를 고르게 한다(후보
     밖 답·NONE은 그대로 unverified). 문서당 `FUSE_VLM_MAX`(기본 작게)로 모델 호출 상한 — AD43 EXTERNAL_SCOPE·
     NO_PAID_CALLS·`common/guard` 내부망 가드는 `common/adk.complete()`가 집행(여기서 따로 안 함).

PARSE_FUSE_REREAD_P3(환경변수, 기본 켬, =0으로 끔, PARSE_FUSE_REREAD 전제 — 호출부 represent.py가 둘 다 확인) —
켜지면(기본) represent.py가 P2 다음에 `rereview_facts_p3()`를 불러 P2가 unverified로 남긴 facts만 더 본다.
꺼지면(=0) 안 불러 rep["fused"]가 P2까지만 켰을 때와 바이트 동일. VLM 단계(②)는 VLM_BASE_URL·VLM_MODEL 미설정
이면 빈 글자(=NONE 취급)로 조용히 건너뛴다(adk.complete가 ModelUnavailable을 집행, AD43) — 외부 유료 호출 없음.

범위 밖(이번엔 안 함): 쪽 전체 VLM 스캔(이미 특정 자리만 다루는 P2·P3 설계 밖) · 그림이 여러 장이고 전부 후보와
무관할 때의 "그림 설명" 재추출(figure_describe 몫, 여기는 값 선택형 1문항만).
"""

import base64
import hashlib
import json
from pathlib import Path

from common.ai.agent_prompts import tail as _tail_prompt
from common.ai.agent_prompts import template as _load_template
from common.config import settings as C  # common 칸 설정 객체(S7c)
from common.core.paths import (
    APP_ROOT,  # 폴더 재편 뒤 이 상수만 바뀌면 됨
    atomic_write_text,  # RV6, tmp+os.replace 공용
)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.transform.represent import reread as reread_mod  # P2(render_crop·_default_ocr·reread_matches 재사용)
from pipeline.transform.represent.fuse import _fact_key, vote_fragment

IMG_MAX_PER_FRAG = (
    pc.cfg().transform.represent.reread.p3_img_max
)  # S7c — 설정 객체(모듈 상수 — import 때 한 번) · 조각 하나당 다시 볼 그림 상한(결정적 — 가까운 순)
VLM_MAX = pc.cfg().transform.represent.reread.vlm_max  # S7c · 문서당 VLM 호출 상한(AD43 비용 가드)
_VLM_CACHE_DIR = APP_ROOT / "output" / "parse" / "_reread_p3" / "_vlm_cache"  # 쓰기는 output/만(C4) — (크롭 sha·후보) 키 캐시
# 후보 글자를 문자열로 이어붙이는 호출부라 load()(템플릿+꼬리) 대신 template()(꼬리 없음)을 쓰고, 공용 꼬리(ADK14
# P1)는 아래 _default_vlm_call에서 후보 뒤(샌드위치 — 자료 다음에 꼬리)에 직접 붙인다.
P_CHOOSE = _load_template("value_choice", "choose")
P_CHOOSE_TAIL = _tail_prompt("value_choice")


def on(config=None):
    """PARSE_FUSE_REREAD_P3(기본 켬, =0으로 끔)."""
    config = (
        pc.cfg().transform.represent.fuse_reread_p3 if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def nearby_page_images(doc_path, page_idx0, bbox, max_n=None):
    """그 쪽(0-base)의 삽입 그림 중 조각 bbox(둘레 세로 위치)에 가장 가까운 것부터 최대 max_n장 —
    [([x0,y0,x1,y1]pt, png bytes), ...]. bbox가 없으면(P2가 쪽 전체로 폴백한 경우) 쪽에서 가장 큰 그림부터.
    결정적: 거리 같으면 xref(그림이 쪽에 삽입된 순서, pymupdf가 매기는 고정 정수) 오름차순으로 동점을 깬다."""
    import fitz

    max_n = IMG_MAX_PER_FRAG if max_n is None else max_n
    doc = fitz.open(str(doc_path))
    try:
        if page_idx0 < 0 or page_idx0 >= doc.page_count:
            return []
        pg = doc[page_idx0]
        infos = pg.get_image_info(xrefs=True)
        if not infos:
            return []
        if bbox:
            band0, band1 = bbox[1], bbox[3]
            mid = (band0 + band1) / 2

            def _dist(info):
                r = fitz.Rect(info["bbox"])
                if r.y1 >= band0 and r.y0 <= band1:  # 세로로 겹침 — 가장 가까움(0)
                    return 0.0
                return min(abs(r.y0 - mid), abs(r.y1 - mid))

            ranked = sorted(infos, key=lambda info: (_dist(info), info.get("xref", 0)))
        else:
            ranked = sorted(infos, key=lambda info: (-info["width"] * info["height"], info.get("xref", 0)))
        out = []
        for info in ranked[:max_n]:
            r = fitz.Rect(info["bbox"]) & pg.rect
            if r.is_empty:
                continue
            pix = pg.get_pixmap(dpi=reread_mod.HIGH_DPI, clip=r)
            out.append(([round(v, 1) for v in r], pix.tobytes("png")))
        return out
    finally:
        doc.close()


def _parse_answer(text):
    """VLM 응답 JSON({"answer": "..."})에서 답만 — 코드펜스·군더더기 있어도(figure_review._parse_json과 같은 관용)."""
    import re

    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return ""
    try:
        return str(json.loads(m.group(0)).get("answer") or "").strip()
    except ValueError:
        return ""


def _vlm_cache_path(img_sha, cand_texts):
    key = hashlib.sha256(json.dumps([img_sha, cand_texts], ensure_ascii=False).encode()).hexdigest()
    return _VLM_CACHE_DIR / f"{key}.json"


def _default_vlm_call(png_bytes, cand_texts):
    """실제 내부 VLM 호출(common/adk.complete, role="vlm", agent="value_choice") — 가드·내부망·NO_PAID_CALLS는
    adk.complete가 집행(여기서 따로 안 함, AD43). VLM_BASE_URL·VLM_MODEL 미설정·GuardBlocked(ModelUnavailable)는
    **아직 못 물어본 것**이라 None(캐시하지 않음 — 버그 수정, 나중에 설정·가드 해제되면 다시 물어야 한다).
    실제로 불러서(재시도 2번 포함) 모델이 진짜로 빈 글자를 답했을 때만 빈 문자열("")을 돌려준다 — 그건 모델이
    낸 답이니 캐시해도 된다(재질문해도 또 빈 답일 뿐)."""
    from common.ai import adk as A

    base, model = (
        C.cfg().models.vlm.base_url,
        C.cfg().models.vlm.model,
    )  # S7c — 설정 객체(common 칸 — 글자 그대로, 없음·'' 모두 아래 `not (base and model)`로 같음)
    if not (base and model):
        return None
    prompt = P_CHOOSE + "\n\n후보: " + json.dumps(cand_texts, ensure_ascii=False) + P_CHOOSE_TAIL
    extra = {"reasoning": {"enabled": False}} if "openrouter" in base else {"chat_template_kwargs": {"enable_thinking": False}}
    deadline = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png_bytes).decode()}},
            ],
        }
    ]
    text = ""
    for _ in range(2):  # 빈 답이면 1번만 다시 — 생각 토큰이 상한을 다 써 빈 응답(OpenRouter 실험 10-08: 가벼운 VLM 2/6 빈 답)
        try:
            text, _u = A.complete(
                "vlm",
                msgs,
                temperature=0,
                max_tokens=pc.cfg().transform.represent.reread.vlm_max_tokens,  # S7c — 설정 객체
                extra=extra,
                timeout=deadline,
                agent="value_choice",
            )
        except A.ModelUnavailable:  # GuardBlocked(외부 차단·NO_PAID_CALLS) 포함 — 아직 못 물어본 것, None
            return None
        if (text or "").strip():
            break
    return text


def vlm_choose(png_bytes, candidates, vlm_fn=None):
    """크롭 + 후보(winner·losers 모양, "text" 있으면 됨) → 답이 후보 중 하나와 글자 그대로 같으면 그 후보 dict,
    NONE·후보 밖 답·호출 실패는 None(= unverified 유지, 값을 지어내지 않음). 캐시 키 = (크롭 sha256, 후보 글 목록)
    — 같은 자리를 다시 봐도 재호출 0(output/ 아래, 다른 VLM 캐시와 같은 자리 원칙). vlm_fn(또는 기본
    `_default_vlm_call`)이 **None**을 돌려주면(미설정·GuardBlocked·호출 실패 — 아직 못 물어본 것) 캐시에
    쓰지 않고 그대로 None 반환 — 나중에 VLM을 설정하거나 가드가 풀리면 같은 자리를 다시 묻는다(버그 수정,
    예전엔 빈 답("")으로 캐시해 영영 다시 안 물었다). 모델이 실제로 응답한 빈 글자·NONE만 캐시한다."""
    cand_texts = [c["text"] for c in candidates]
    img_sha = hashlib.sha256(png_bytes).hexdigest()
    cp = _vlm_cache_path(img_sha, cand_texts)
    if cp.exists():
        answer = json.loads(cp.read_text(encoding="utf-8"))["answer"]
    else:
        text = (vlm_fn or _default_vlm_call)(png_bytes, cand_texts)
        if text is None:  # 미설정·가드 차단·호출 실패 — 못 물어본 것, 캐시하지 않고 그대로 미확인
            return None
        answer = _parse_answer(text)
        cp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cp, json.dumps({"answer": answer}, ensure_ascii=False))
    if not answer or answer == "NONE":
        return None
    hits = [c for c in candidates if c["text"] == answer]
    return hits[0] if len(hits) == 1 else None  # 후보 밖 답이거나(hits==0) 후보 두 개가 같은 글자(edge)면 모호 — None


def _page_rect(doc_path, page_idx0):
    import fitz

    doc = fitz.open(str(doc_path))
    try:
        return [round(v, 1) for v in doc[page_idx0].rect]
    finally:
        doc.close()


def _other_pages_with_images(doc_path, skip_page_idx0):
    """P2가 짚은 쪽(`skip_page_idx0`)에 그림이 하나도 없을 때만 쓰는 추가 폴백 — 문서의 **다른** 쪽 중 그림이
    있는 쪽을 쪽 번호 순으로(결정적) 돈다. AD29 스캔 쪽 함정(judge-conflicts mixedpdf-*): 글자층 엔진들이
    가리키는 자리가 전부 **다른 쪽**(글자 쪽)의 진짜 문장이라서(그 쪽 자체는 멀쩡한 매치) locate_region이
    그 쪽에 자신 있게 멈추지만, 다툼이 된 실제 값은 애초에 글자층이 없는 스캔 쪽의 그림 안에만 있다 — "이
    쪽엔 그림이 없다"가 바로 "이 쪽은 이 조각의 출처가 아니다"라는 신호(그림이 있는 쪽은 보통 이미 ①에서
    봄, 범위 밖). 반환: 쪽 번호(0-base) 목록(합성·소량 문서 전제, locate_region과 같은 "문서 전 쪽을 본다")."""
    import fitz

    doc = fitz.open(str(doc_path))
    try:
        return [pno for pno in range(doc.page_count) if pno != skip_page_idx0 and doc[pno].get_image_info()]
    finally:
        doc.close()


def p3_once(doc_path, page, bbox, winner, losers, ocr_fn=None, vlm_fn=None, vlm_allowed=True, img_max=None):
    """조각 하나의 P3 — page(1-base)·bbox는 P2 `reread.reread_once()`가 이미 찾은 그 자리(먼저 거기서 찾되,
    다시 안 찾는 건 아님 — 아래 ①b). ① 그림 경계 OCR(모델 호출 0, 그 쪽에 그림이 없으면 ①b 다른 쪽까지)
    → ② 그래도 못 맞추고 vlm_allowed면 VLM 선택형(모델 호출 최대 1).
    반환: {"n_images", "img_matched", "img_match", "img_bbox", "img_text", "page"(실제 맞은 쪽, 1-base),
           "vlm_called", "vlm_matched", "vlm_match", "vlm_bbox", "vlm_answer"} — 호출부가 ①·② 결과를 각각
    따로 볼 수 있게(채점 — "그림 OCR만" vs "+VLM"을 나눠 비교, AD29 측정 요건)."""
    page_idx0 = page - 1
    imgs = nearby_page_images(doc_path, page_idx0, bbox, img_max)
    img_match, img_bbox, img_text, match_page_idx0 = None, None, None, page_idx0
    for rect, png in imgs:
        text = (ocr_fn or reread_mod._default_ocr)(png)
        match = reread_mod.reread_matches(text, winner, losers)
        if match is not None:
            img_match, img_bbox, img_text = match, rect, text
            break
    if img_match is None and imgs:
        # 그림 하나씩은 못 맞춰도(그림마다 값이 나뉘어 있는 경우 — numfmt-003·numfmt-005: 그림 한 장엔 "430,000"만,
        # 다른 한 장엔 "6배치"만 보이고 후보 글 자체가 두 값을 한 자리(OCR 전 과정에서 둘레까지 묶어 읽은 글)로
        # 합친 모양이라 그림 한 장만으론 후보의 "자기만의 토큰"을 다 못 채운다) 이 쪽에 그림이 있을 때만(=표가
        # 아닐 가능성↑, typos-006류 빽빽한 표는 보통 삽입 그림이 없어 imgs가 비어 이 경로를 아예 안 탐) 쪽 전체를
        # 한 번 더 OCR(여전히 모델 호출 0) — PAD_PT를 넓히는 것과 달리 "그림이 있는 쪽"으로 한정돼 이웃 표 칸을
        # 잘못 담는 위험이 reread.py PAD_PT 주석의 그 오탐과는 다르다(실측 10-08: 이 경로로 typos-006은 안 건드림).
        page_png = reread_mod.render_crop(doc_path, page_idx0, None)
        text = (ocr_fn or reread_mod._default_ocr)(page_png)
        match = reread_mod.reread_matches(text, winner, losers)
        if match is not None:
            img_match, img_bbox, img_text = match, _page_rect(doc_path, page_idx0), text
    if img_match is None and not imgs:
        # ①b — P2가 짚은 쪽에 그림이 전혀 없다(AD29 스캔 쪽 함정, `_other_pages_with_images` 참고) — 문서의
        # 다른 쪽 중 그림이 있는 쪽을 쪽 순서로 돌며 그 쪽의 그림(들)로 다시 본다. 각 쪽에서 맞는 그림이 하나도
        # 없으면 그 쪽 전체도 한 번 더 OCR(같은 "그림이 있는 쪽만" 원칙).
        for other_pno in _other_pages_with_images(doc_path, page_idx0):
            other_imgs = nearby_page_images(doc_path, other_pno, None, img_max)
            for rect, png in other_imgs:
                text = (ocr_fn or reread_mod._default_ocr)(png)
                match = reread_mod.reread_matches(text, winner, losers)
                if match is not None:
                    img_match, img_bbox, img_text, match_page_idx0 = match, rect, text, other_pno
                    break
            if img_match is None:
                page_png = reread_mod.render_crop(doc_path, other_pno, None)
                text = (ocr_fn or reread_mod._default_ocr)(page_png)
                match = reread_mod.reread_matches(text, winner, losers)
                if match is not None:
                    img_match, img_bbox, img_text, match_page_idx0 = match, _page_rect(doc_path, other_pno), text, other_pno
            if img_match is not None:
                break
    out = {
        "n_images": len(imgs),
        "img_matched": img_match is not None,
        "img_match": img_match,
        "img_bbox": img_bbox,
        "img_text": img_text,
        "page": match_page_idx0 + 1,
        "vlm_called": False,
        "vlm_matched": False,
        "vlm_match": None,
        "vlm_bbox": None,
        "vlm_answer": None,
    }
    if img_match is not None or not vlm_allowed:
        return out
    if imgs:
        vlm_bbox, vlm_png = imgs[0]
    else:
        vlm_bbox, vlm_png = bbox, reread_mod.render_crop(doc_path, page_idx0, bbox)
    candidates = [winner] + list(losers)
    match = vlm_choose(vlm_png, candidates, vlm_fn)
    out.update(
        {
            "vlm_called": True,
            "vlm_matched": match is not None,
            "vlm_match": match,
            "vlm_bbox": vlm_bbox,
            "vlm_answer": match["text"] if match else None,
        }
    )
    return out


def _candidate_groups(engine_docs, rep_engine, tie_bonus=0.5):
    """fact 자리 키 → `fuse.vote_fragment()` 결과(winner+losers) — P2 `rereview_facts`와 같은 그룹 계산 규칙을
    독립적으로 다시 한다(reread.py는 안 건드림 — P1·P2 동작·바이트 동일성에 영향 0, 결정적이라 같은 engine_docs면
    같은 그룹)."""
    by_key = {}
    for eng, d in engine_docs.items():
        for f in (d or {}).get("facts") or []:
            by_key.setdefault(_fact_key(f), []).append({"engine": eng, "text": f.get("value") or ""})
    out = {}
    for key, cands in by_key.items():
        result = vote_fragment(cands, rep_engine, tie_bonus)
        if result:
            out[key] = result
    return out


def _apply_p3_match(fact, out, fused):
    """매치된 후보를 채택(AD19 "확인되면 채택", P2 `rereview_facts`와 같은 취지) — fact·fused["conflicts"]를
    제자리에서 바꾼다. out은 p3_once() 반환(둘 중 먼저 맞은 쪽 — img 우선)."""
    method = "image_ocr" if out["img_matched"] else "vlm_choice"
    match = out["img_match"] if out["img_matched"] else out["vlm_match"]
    fact["reread"]["p3"] = {
        "method": method,
        "page": out.get("page"),
        "bbox": out["img_bbox"] if out["img_matched"] else out["vlm_bbox"],
        "answer": out["img_text"] if out["img_matched"] else out["vlm_answer"],
        "matched": True,
    }
    if match["text"] == fact["value"]:
        fact["unverified"] = False
        fact["reread"]["p3"]["confirmed"] = "winner"
        return
    label = (fact.get("context") or [None])[0]
    was, was_engines, was_score = fact["value"], fact.get("engines"), fact.get("score")  # P2가 unverified로 두면
    # fact는 여전히 그룹 투표 승자(winner) 그대로라 engines·score가 곧 그 승자의 것(fuse_facts가 처음 채운 값,
    # P2도 안 바꿈) — _candidate_groups를 다시 안 불러도 "맞바꾸기 전 승자" 정보를 그대로 쓸 수 있다.
    fact["value"], fact["engines"], fact["score"] = match["text"], match.get("engines", []), match.get("score", fact.get("score"))
    fact["unverified"] = False
    fact["reread"]["p3"]["confirmed"] = "loser"
    fact["reread"]["p3"]["was"] = was
    conflicts_by_label = {c["label"]: c for c in fused.get("conflicts") or []}
    if label in conflicts_by_label:
        c = conflicts_by_label[label]
        prev_losers = c.get("losers") or []
        new_losers = [{"engines": was_engines, "text": was, "score": was_score}]
        new_losers += [lo for lo in prev_losers if lo["text"] != match["text"]]
        c["winner"], c["winner_engines"], c["losers"] = match["text"], match.get("engines", []), new_losers
        if "split" in c:  # PARSE_FUSE_SIGNALS 꺼져 있던 자리엔 애초에 이 키가 없음(스키마 바이트 동일 원칙) — 새로 만들지 않는다
            c["split"] = False  # AD26 — 그림 OCR·VLM 선택형(독립 증거)으로 확인됐으니 P1의 '갈림' 표시는 해소


def rereview_facts_p3(engine_docs, fused, rep_engine, doc_path, tie_bonus=0.5, max_vlm=None, ocr_fn=None, vlm_fn=None):
    """AD29 P3 — `fused`(P2 `rereview_facts`를 거친 뒤의 반환)에서 `unverified: True`인 facts만 더 본다(P2가
    확인·뒤집은 자리는 손대지 않음). engine_docs는 P1·P2와 같은 입력(그룹을 독립적으로 다시 계산 — reread.py는
    안 건드림). doc_path가 PDF가 아니면(또는 없으면) 전부 건너뛰고 이유만 남긴다(P2와 같은 전제).
    반환: fused(제자리 변경 + "reread"["p3"] 통계 칸 추가)."""
    max_vlm = VLM_MAX if max_vlm is None else max_vlm
    stats = {"attempted": 0, "image_ocr_matched": 0, "vlm_calls": 0, "vlm_matched": 0, "still_unverified": 0, "max_vlm": max_vlm}
    fused.setdefault("reread", {})["p3"] = stats
    if not doc_path or Path(doc_path).suffix.lower() != ".pdf" or not Path(doc_path).exists():
        stats["skip_reason"] = "no_pdf"
        return fused
    groups = None
    vlm_budget = max_vlm
    for fact in fused.get("facts") or []:
        if not fact.get("unverified"):
            continue
        rr = fact.get("reread") or {}
        if rr.get("page") is None:
            continue
        if groups is None:
            groups = _candidate_groups(engine_docs, rep_engine, tie_bonus)
        result = groups.get(_fact_key(fact))
        if not result:
            continue
        stats["attempted"] += 1
        out = p3_once(
            doc_path, rr["page"], rr.get("bbox"), result, result["losers"], ocr_fn=ocr_fn, vlm_fn=vlm_fn, vlm_allowed=vlm_budget > 0
        )
        if out["vlm_called"]:
            stats["vlm_calls"] += 1
            vlm_budget -= 1
        if out["img_matched"]:
            stats["image_ocr_matched"] += 1
            _apply_p3_match(fact, out, fused)  # out["page"] = 실제 맞은 쪽(①b면 rr["page"]와 다를 수 있음)
        elif out["vlm_matched"]:
            stats["vlm_matched"] += 1
            _apply_p3_match(fact, out, fused)
        else:
            stats["still_unverified"] += 1
    return fused
