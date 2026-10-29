"""AD29 P2 — 확인 안 된/갈린 조각을 좌표로 찾아 다시 읽기(AD19·AD29 ③, 이 단계는 OCR만 — VLM 없음).

P1(`fuse.py`)의 조각별 투표는 **엔진 수**로 신뢰도를 더한다(같은 자리를 읽는 엔진이 실은 같은 글자층을 베껴
쓰는 것이라도 엔진 이름이 다르면 각자 표를 더함) — 그래서 "글자층 3개(같은 자리를 다른 라이브러리로 읽었을
뿐) vs OCR 1개"처럼 **수는 많지만 실은 교차 확인이 아닌** 자리에서 틀린 쪽이 이길 수 있다(`judge-conflicts`
numfmt-003·numfmt-005 — 글자층에 일부러 잘못된 값을 심어 둔 합성 시험 문서, 보이는 값은 OCR만 맞다).

이 모듈은 그런 자리(승자가 전부 같은 인식 계열뿐이거나, 승자-패자 점수차가 근소한 자리)만 골라 **그 좌표
영역을 고해상도로 다시 렌더 → OCR로 다시 읽어서** 확인한다(모델 호출 0, rapidocr 재사용). 확인되면(표기까지
정확히 맞는 후보가 유일하면) 그 후보를 새 승자로 채택(AD19 "확인되면 채택") — 틀렸던 다수결을 뒤집을 수
있는 건 재판독이 "엔진 수를 세는" 것이 아니라 "그 자리를 직접 보는" 독립 증거이기 때문(합의가 아니라 확인).
아무 것도 안 맞으면 `unverified` 표시만 하고 기존 값은 지우지 않는다.

PARSE_FUSE_REREAD(환경변수, 기본 켬, =0으로 끔, PARSE_FUSE 전제) — 켜지면(기본) represent.py가 fuse 다음에 이
모듈을 불러 rep["fused"]에 reread 통계·조각별 "reread" 꼬리표를 더한다. 꺼지면(=0) 안 불러 바이트 동일.

범위 밖(이번엔 안 함, P3·VLM 몫): 사전·그래프 타당성(④) · VLM 선택형 재판독 · 줄(자유 문장) 단위 자리 맞추기.
"""

import re
import time
import uuid
from pathlib import Path

from common.core.meaning import tokens as _toks  # tokens()는 교차 재현율과 같은 유의미 토큰
from common.core.paths import APP_ROOT  # 폴더 재편 뒤 이 상수만 바뀌면 됨
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

# 기준(쉼표 제거·공백 무시, 마침표는 유지 — AD25) 재사용
from pipeline.shared.meaning import canon_num_key
from pipeline.transform.represent.fuse import _fact_key, engine_kind, norm_key, vote_fragment

MAX_PER_DOC = pc.cfg().transform.represent.reread.max  # S7c — 설정 객체(모듈 상수 — import 때 한 번) · 문서당 재판독 상한(AD29 ③)
MARGIN = pc.cfg().transform.represent.reread.margin  # S7c · 승자-최선 패자 점수차가 이 값 이하면 "근소"(AD29 (a))
HIGH_DPI = pc.cfg().transform.represent.reread.dpi  # S7c · 재판독 전용 고해상도(엔진 기본 OCR_DPI 200의 2배)
PAD_PT = pc.cfg().transform.represent.reread.pad_pt  # S7c · bbox 둘레 여백(pt) — 같은 줄·바로 위아래 줄까지 담김
# **안전 쪽으로 보수적**(실측 10-08, judge-conflicts 7건):
# 더 넓히면(약 70~90pt) 글자층에 없는 그림 속 값(numfmt-005
# "6배치", 자리에서 ~75pt 떨어짐)까지 잡히지만, 줄 간격이
# 좁은 표(typos-006, 줄 간격 13pt)에서는 70pt만 넘어도
# 바로 옆의 **다른** 값(820,000)을 같이 담아 엉뚱하게 뒤집는
# 오탐이 생긴다 — 안 뒤집는 게(미확인) 잘못 뒤집는 것보다
# 낫다는 원칙(AD19 "지우지 않음")대로 안전한 값을 기본으로.
# ponytail: 레이아웃을 보고 이웃 칸을 찾는 게 아니라 고정 여백
# 이다(천장) — 멀리 있는 값은 기본값으론 못 담는다, 문서별로
# 늘리려면 FUSE_REREAD_PAD_PT(위험 감수) · 제대로 하려면 P3
# (이미지 경계 인식 또는 VLM 선택형 재판독)
_ENGINE_NAME = "rapidocr_ko"
_TMP_DIR = (
    APP_ROOT / "output" / "_reread_tmp"
)  # 쓰기는 output/만(C4, dev/out = 컨테이너 /app/output 볼륨) — 크롭 PNG를 parser.py 계약(파일 경로)에 맞춰 잠깐 씀


def on(config=None):
    """PARSE_FUSE_REREAD(기본 켬, =0으로 끔)."""
    config = (
        pc.cfg().transform.represent.fuse_reread if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def eligible(winner, losers):
    """AD29 P2 재판독 대상 판정 — winner/losers는 `fuse.vote_fragment()` 반환 그대로(engines·score·text).
    (a) 승자-최선 패자 점수차가 MARGIN 이하(근소한 승부, 동점 깨기 수준) (b) 승자 엔진이 전부 같은 인식 계열
    (`engine_kind` — text/vlm/ocr) 하나뿐(패자가 다른 계열이면, 엔진 수만 많을 뿐 교차 확인이 아니었다는
    신호 — AD26이 지적한 바로 그 상황, 점수 차가 커도 재확인 가치가 있다). 패자가 없으면(갈리지 않음) 둘 다
    해당 없음. 반환: (bool, reason 문자열 또는 None)."""
    if not losers:
        return False, None
    margin = winner["score"] - max(lo["score"] for lo in losers)
    if margin <= MARGIN:
        return True, "small_margin"
    if len({engine_kind(e) for e in winner["engines"]}) == 1:
        return True, "single_kind_winner"
    return False, None


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _nk(s):
    """norm_key(공용, fuse.py) 앞에 거짓 줄바꿈 기호(judge-conflicts items.jsonl의 "⏎" — 긴 둘레 글 안 여러 줄을
    한 줄 snippet으로 사람이 읽기 좋게 적어 둔 표시, 실제 문서 facts에는 안 나옴)를 공백으로 바꾼다. 실제 재판독
    OCR 글은 줄바꿈이 진짜 공백(_default_ocr이 \\n·\\f를 공백으로 바꿔 둠)이라 "⏎"가 남아 있으면 포함 비교가
    글자 하나 때문에 영영 안 걸린다(실측 10-08 — judge-conflicts numfmt-003 재현)."""
    return norm_key((s or "").replace("⏎", " "))


def _page_words(doc, pno, words_cache=None):
    """쪽 단어 목록(doc.get_text("words")) — words_cache(문서 단위 dict)가 주어지면 같은 쪽을 다시 스캔하지
    않고 재사용한다(BR1 — 조각마다 전체 쪽을 처음부터 다시 훑던 비용 제거, 문서당 한 번만 스캔)."""
    if words_cache is not None and pno in words_cache:
        return words_cache[pno]
    words = doc[pno].get_text("words")
    if words_cache is not None:
        words_cache[pno] = words
    return words


def locate_region(doc_path, candidate_texts, doc=None, words_cache=None):
    """pymupdf 글자층 단어 bbox로 조각의 쪽·자리를 찾는다 — **숫자(구분자 무시)부터** 비교한다('430,000' 후보도
    글자층의 '430.000' 단어 자리로 찾을 수 있게 — 바로 그 자리가 쟁점인 경우의 핵심이자, 숫자가 글 전체에서
    가장 특정적인 조각이라 "가상"·"예시" 같은 흔한 머리말 단어에 먼저 걸려 엉뚱한 자리(문서 맨 위)를 집는 것을
    막는다 — 실측 10-08, judge-conflicts 후보가 머리말 문구를 통째로 담은 긴 둘레 글이라 글자 그대로 비교를
    먼저 하면 "(가상)" 한 단어에 바로 걸렸다). 숫자가 없거나 숫자로 못 찾으면 후보 글(표기 그대로) 중 어느
    것이든 포함하는 단어로 보조 비교. 문서 전 쪽을 본다(합성·소량 문서 전제 — 큰 문서는 호출부 FUSE_REREAD_MAX로
    전체 재판독 횟수가 막힌다). 반환: (page_idx0, [x0,y0,x1,y1]pt) 또는 못 찾으면 (0, None)(0쪽 전체 — "좌표
    없으면 쪽 단위" 폴백, AD19 설계안 그대로).
    doc가 주어지면(이미 연 fitz.Document, 문서당 1회 재사용 — BR1) 그 핸들을 쓰고 닫지 않는다(호출부 책임),
    없으면 doc_path로 새로 열고 끝나면 닫는다(기존 동작, 단독 호출·셀프테스트와 그대로 호환). words_cache를
    주면 쪽별 단어 목록을 같은 문서의 다른 호출과 공유한다."""
    import fitz

    digits = [d for d in (_digits(t) for t in candidate_texts) if len(d) >= 2]
    normed = [n for n in (_nk(t) for t in candidate_texts) if n]
    _doc = doc if doc is not None else fitz.open(str(doc_path))
    try:
        if _doc.page_count == 0:
            return 0, None
        if digits:
            for pno in range(_doc.page_count):
                for w in _page_words(_doc, pno, words_cache):
                    wd = _digits(w[4])
                    if wd and len(wd) >= 2 and any(wd in d for d in digits):
                        return pno, list(w[:4])
        for pno in range(_doc.page_count):
            for w in _page_words(_doc, pno, words_cache):
                wn = _nk(w[4])
                if wn and len(wn) >= 2 and any(wn in n for n in normed):
                    return pno, list(w[:4])
        return 0, None
    finally:
        if doc is None:
            _doc.close()


def render_crop(doc_path, page_idx, bbox, doc=None):
    """쪽(또는 bbox 둘레 '줄 띠')을 HIGH_DPI PNG bytes로 렌더 — bbox가 있으면 그 쪽 세로 위치 둘레를
    PAD_PT만큼 위아래로 넓힌 가로 띠(전체 폭)를 자른다(가로 위치는 안 가림 — 같은 줄의 다른 값도 함께 담겨야
    "그 자리"가 좌우로 살짝 벗어나 있어도 놓치지 않는다), bbox가 없으면 쪽 전체(AD19 "좌표 없으면 쪽 단위").
    doc가 주어지면(이미 연 핸들 — BR1) 재사용하고 닫지 않는다, 없으면 doc_path로 열고 닫는다(기존 동작)."""
    import fitz

    _doc = doc if doc is not None else fitz.open(str(doc_path))
    try:
        pg = _doc[page_idx]
        clip = None
        if bbox:
            y0, y1 = bbox[1], bbox[3]
            r = fitz.Rect(pg.rect.x0, y0 - PAD_PT, pg.rect.x1, y1 + PAD_PT) & pg.rect
            clip = r
        pix = pg.get_pixmap(dpi=HIGH_DPI, clip=clip)
        return pix.tobytes("png")
    finally:
        if doc is None:
            _doc.close()


def _default_ocr(png_bytes):
    """크롭 PNG → 글자(공백 join) — tools/engines/rapidocr/parser.py의 운영 OCR 경로(parse_rapidocr_ko, 한국어
    PP-OCRv5 모델)를 그대로 재사용한다(모델 설정 중복 방지, 결정적 — 같은 PNG면 같은 모델·같은 글자). 그 함수가
    파일 경로를 전제하는 공용 계약이라 크롭을 output/ 밑 임시 PNG로 한 번 썼다 바로 지운다(C4 — output/ 밖에 안 씀)."""
    from pipeline.extract.engines.rapidocr.parser import parse_rapidocr_ko

    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _TMP_DIR / f"{uuid.uuid4().hex}.png"
    tmp.write_bytes(png_bytes)
    try:
        out = parse_rapidocr_ko(str(tmp))
        return (out.get("text") or "").replace("\n", " ").replace("\f", " ").strip()
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _own_tokens(cand_tok, shared):
    """후보 토큰 집합 중 다른 후보와 안 겹치는("자기만의") 것만 — 공통 머리말·문맥은 구분에 쓸모없다(짧은 값
    후보끼리는 보통 shared가 비어 cand_tok 그대로). 자기만의 토큰이 하나도 없으면(= 값 자체가 겹치는 후보,
    생겨선 안 되는 edge) 폴백으로 원래 토큰 전부를 쓴다."""
    return (cand_tok - shared) or cand_tok


def reread_matches(reread_text, winner, losers):
    """재판독 글이 후보(승자 1 + 패자 여러) 중 정확히 하나와 맞는지 — 유의미 토큰(common.core.meaning.tokens, 표기까지
    구분: 쉼표는 지워지지만 마침표는 유지돼 430,000과 430.000이 계속 다른 토큰) 집합으로 비교한다. 후보 전체
    토큰이 아니라 **다른 후보와 안 겹치는 "자기만의" 토큰**만 보는 이유 — judge-conflicts 항목처럼 후보가 긴
    둘레 글(머리말·문맥 포함)일 때 공통 문구가 비교에 끼면 어느 쪽인지 구분이 안 된다(실측 10-08). 자기만의
    토큰이 재판독 토큰 집합에 전부 들어 있는 후보가 유일하면 채택, 둘 이상이면(토큰 집합이 서로의 부분집합)
    더 구체적인(토큰 수 많은) 쪽이 유일하게 많을 때만 채택 — 그래도 모호하면 숫자만 canon_num_key로 보조
    비교(자리 구분자가 재판독 글에서 깨졌을 때의 안전망, 역시 유일할 때만). 반환: 맞은 후보 dict 또는 None."""
    cands = [winner] + list(losers)
    rr_tok = _toks((reread_text or "").replace("⏎", " "))
    if not rr_tok:
        return None
    cand_tok = [_toks((c["text"] or "").replace("⏎", " ")) for c in cands]
    shared = set.intersection(*cand_tok) if len(cand_tok) > 1 else set()
    pairs = [(c, _own_tokens(ct, shared)) for c, ct in zip(cands, cand_tok)]
    hits = [(c, ot) for c, ot in pairs if ot and ot <= rr_tok]
    if len(hits) == 1:
        return hits[0][0]
    if len(hits) > 1:
        hits.sort(key=lambda p: -len(p[1]))
        if len(hits[0][1]) > len(hits[1][1]):
            return hits[0][0]
        return None
    rr_num = canon_num_key((reread_text or "").strip())
    if rr_num:
        num_hits = [c for c in cands if canon_num_key(str(c["text"]).strip()) == rr_num]
        if len(num_hits) == 1:
            return num_hits[0]
    return None


def _fallback_best(winner, losers, engine_rank):
    """2026-10-22 사용자 지정 — P2 재판독으로도 못 가릴 때 따라갈 후보: engine_rank(산출 정확도 높은 순,
    앞이 최고 — represent가 엔진 원본 산출 풍부도로 계산해 넘김)에서 제일 먼저 나오는 후보(승자든 패자든).
    rank가 없거나 후보 어느 쪽에도 rank 엔진이 없으면 None(종래 동작 — unverified 표시만, 값 유지)."""
    if not engine_rank:
        return None
    cands = [winner] + list(losers)
    for eng in engine_rank:
        for c in cands:
            if eng in (c.get("engines") or []):
                return c
    return None


def reread_once(doc_path, winner, losers, ocr_fn=None, doc=None, words_cache=None):
    """조각 하나 재판독 — locate → crop(줄 띠) → 고해상도 재판독 → match 한 번. 반환: {"engine","page"(1-base),
    "bbox","text","matched":bool,"match":매치된 후보 또는 None} · 렌더·OCR을 못 하면 {"error": 사유}(크래시
    대신 — 전체 파이프라인을 막지 않고 이 자리만 건너뛴다, 호출부가 기록).
    doc·words_cache는 선택(기본 None) — `rereview_facts`가 문서당 한 번 연 핸들·쪽 단어 캐시를 넘기면 그대로
    재사용한다(BR1), 안 주면(단독 호출) 기존처럼 doc_path로 매번 새로 연다."""
    try:
        page, bbox = locate_region(doc_path, [winner["text"]] + [lo["text"] for lo in losers], doc=doc, words_cache=words_cache)
        png = render_crop(doc_path, page, bbox, doc=doc)
        text = (ocr_fn or _default_ocr)(png)
    except Exception as e:  # 재판독 1건 실패가 문서 전체를 막지 않게
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    match = reread_matches(text, winner, losers)
    return {"engine": _ENGINE_NAME, "page": page + 1, "bbox": bbox, "text": text, "matched": match is not None, "match": match}


def rereview_facts(engine_docs, fused, rep_engine, doc_path, tie_bonus=0.5, max_n=None, ocr_fn=None, engine_rank=None):
    """AD29 P2 — `fused`(= `fuse.fuse()`의 반환, "facts"·"conflicts")에 좌표 재판독을 더해 제자리에서 바꾼다.
    engine_docs는 `fuse_facts`에 넘긴 것과 같은 입력({엔진: {"facts":[...]}}) — 같은 `_fact_key`·
    `vote_fragment`로 그룹을 다시 계산해(결정적, fuse_facts와 같은 값) eligible()인 자리만 재판독한다.
    doc_path가 PDF가 아니거나 없으면 전부 건너뛰고 이유만 남긴다(이 단계는 OCR·PDF 글자층 전용 — 이미지
    전용 포맷·스캔 전용 글자층 없는 포맷은 범위 밖, locate_region이 pymupdf 글자층을 전제하기 때문).
    확인(= reread_matches가 유일하게 맞힘)되면: 그 후보가 승자와 같으면 "확인"만 기록, 다르면 승자를 그
    후보로 바꾸고(AD19 "확인되면 채택") conflicts의 그 자리도 승자·패자를 맞바꿔 기록한다. 아무 것도 못
    맞히면 `unverified: True`만 붙이고 값은 그대로 둔다(AD19 "지우지 않음"). 반환: fused(제자리 변경 +
    "reread" 통계 칸 추가).
    BR1 — 문서당 fitz 핸들 1개만 열어(쪽마다 재열지 않음) 모든 조각의 locate_region·render_crop이 재사용하고,
    쪽 단어 목록도 문서 단위 dict(words_cache)로 캐싱해 조각마다 전체 쪽을 다시 스캔하지 않는다. 출력(facts·
    conflicts·reread 통계)은 이전과 동일 — 바뀌는 건 내부 fitz 호출 횟수뿐."""
    max_n = MAX_PER_DOC if max_n is None else max_n
    stats = {
        "attempted": 0,
        "confirmed_winner": 0,
        "flipped": 0,
        "unverified": 0,
        "errors": 0,
        "fallback_best": 0,
        "fallback_kept": 0,
        "error_reasons": {},
        "max": max_n,
        "time_sec": 0.0,
    }
    fused["reread"] = stats
    if not doc_path or Path(doc_path).suffix.lower() != ".pdf" or not Path(doc_path).exists():
        stats["skip_reason"] = "no_pdf"
        return fused
    by_key = {}
    for eng, d in engine_docs.items():
        for f in (d or {}).get("facts") or []:
            by_key.setdefault(_fact_key(f), []).append({"engine": eng, "text": f.get("value") or ""})
    conflicts_by_label = {c["label"]: c for c in fused.get("conflicts") or []}
    t0 = time.time()
    budget = max_n
    import fitz

    try:
        doc = fitz.open(str(doc_path))
    except Exception as e:  # 못 열어도 크래시 대신 이유만 남김(no_pdf와 같은 결)
        stats["skip_reason"] = f"open_failed: {type(e).__name__}"
        return fused
    words_cache = {}
    try:
        for key in sorted(by_key, key=lambda kk: kk[1]):
            if budget <= 0:
                break
            result = vote_fragment(by_key[key], rep_engine, tie_bonus)
            if not result:
                continue
            ok, reason = eligible(result, result["losers"])
            if not ok:
                continue
            label = key[1] if key[0] == "row" else None
            fact = (
                next((f for f in fused.get("facts") or [] if (f.get("context") or [None])[0] == label), None)
                if label
                else next((f for f in fused.get("facts") or [] if f.get("value") == result["text"]), None)
            )
            if fact is None:
                continue
            budget -= 1
            stats["attempted"] += 1
            rr = reread_once(doc_path, result, result["losers"], ocr_fn, doc=doc, words_cache=words_cache)
            if "error" in rr:
                stats["errors"] += 1
                stats["error_reasons"][rr["error"]] = stats["error_reasons"].get(rr["error"], 0) + 1
                fact["reread"] = {"matched": False, "error": rr["error"]}
                continue
            rr_info = {"engine": rr["engine"], "page": rr["page"], "bbox": rr["bbox"], "text": rr["text"]}
            if rr["match"] is None:
                fb = _fallback_best(result, result["losers"], engine_rank)
                if fb is not None:  # 2026-10-22 사용자 지정 — P2도 못 가리면 산출 정확도 최고 엔진의 후보로
                    if fb["text"] == result["text"]:  # 승자가 이미 최고 엔진의 값 — 교체 없이 근거만 기록
                        fact["reread"] = {**rr_info, "matched": False, "fallback": "best_engine"}
                        stats["fallback_kept"] += 1
                    else:  # 최고 엔진의 후보로 교체(좌표 확인 아님 — 정책 선택임을 표시)
                        fact["value"], fact["engines"], fact["score"] = fb["text"], fb["engines"], fb["score"]
                        fact["reread"] = {**rr_info, "matched": False, "fallback": "best_engine", "was": result["text"]}
                        stats["fallback_best"] += 1
                        if label in conflicts_by_label:  # conflicts 보고도 같은 자리를 맞바꿔 둔다
                            c = conflicts_by_label[label]
                            new_losers = [{"engines": result["engines"], "text": result["text"], "score": result["score"]}]
                            new_losers += [lo for lo in result["losers"] if lo["text"] != fb["text"]]
                            c["winner"], c["winner_engines"], c["losers"] = fb["text"], fb["engines"], new_losers
                            c["reread"] = {**rr_info, "fallback": "best_engine"}
                else:
                    fact["unverified"] = True
                    fact["reread"] = {**rr_info, "matched": False}
                    stats["unverified"] += 1
            elif rr["match"]["text"] == result["text"]:
                fact["reread"] = {**rr_info, "matched": True, "confirmed": "winner"}
                stats["confirmed_winner"] += 1
            else:
                match = rr["match"]
                fact["value"], fact["engines"], fact["score"] = match["text"], match["engines"], match["score"]
                fact["reread"] = {**rr_info, "matched": True, "confirmed": "loser", "was": result["text"]}
                stats["flipped"] += 1
                if label in conflicts_by_label:
                    c = conflicts_by_label[label]
                    new_losers = [{"engines": result["engines"], "text": result["text"], "score": result["score"]}]
                    new_losers += [lo for lo in result["losers"] if lo["text"] != match["text"]]
                    c["winner"], c["winner_engines"], c["losers"], c["reread"] = match["text"], match["engines"], new_losers, rr_info
                    if (
                        "split" in c
                    ):  # PARSE_FUSE_SIGNALS 꺼져 있던 자리엔 애초에 이 키가 없음(스키마 바이트 동일 원칙) — 새로 만들지 않는다
                        c["split"] = (
                            False  # AD26 — 좌표 재판독(독립 증거)으로 확인됐으니 P1의 '갈림' 표시는 해소(점수 동점이 아니라 직접 확인)
                        )
    finally:
        doc.close()
    stats["time_sec"] = round(time.time() - t0, 3)
    return fused
