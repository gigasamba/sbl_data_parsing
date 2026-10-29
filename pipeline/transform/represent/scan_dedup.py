"""AD39 — 스캔 문서에서 같은 쪽의 OCR 본문(base)과 쪽 VLM 전사가 둘 다 rep.text에 들어가 청크·BM25·임베딩에
두 번 색인되는 문제(AD37과 같은 부작용 — represent.apply_post가 base에 쪽 VLM 블록을 통째로 덧붙이던 설계).
PARSE_DEDUP_SCAN(환경변수, 기본 꺼짐) — 켜면 쪽마다 OCR·VLM 중 하나만 base에 남기고 다른 하나는 rep.post.page_alt
(교차 확인용)로 옮긴다. 기본 우선순위는 쪽 VLM(더 정돈된 글) — OCR 쪽 글자가 믿을 만하고(깨짐률 낮음) VLM이 그 쪽의
절반도 못 옮겼을 때만 OCR을 쓴다. 진 쪽에만 있는 숫자·ID는 이긴 쪽 글 끝에 덧붙여 값 재현율을 지킨다(조각별 정식
융합은 AD29가 할 일 — 여기는 그 전 단계의 최소 보존). 끄면(기본) apply_post가 이 모듈을 안 부른다 — rep.text 바이트 동일.
"""

from pathlib import Path

from common.core.text import id_terms, tokens
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.summarize import nums
from pipeline.shared.text import canon_symbols
from pipeline.transform.figures import vlm_page as vp_mod
from pipeline.transform.represent import parse_qa


def on(config=None):
    config = (
        pc.cfg().extract.dedup_scan if config is None else config
    )  # S7c — 설정 객체(bool 칸 → "true"/"false"로 아래 판정이 옛 글자 판정과 같음)
    return str(config).strip().lower() not in ("", "0", "none", "false")


def _doc_page_count(doc_path):
    """문서의 실제 쪽 수 — \\f(쪽 경계) 개수가 이것과 다르면 중간에 글자 0개(빈) 쪽이 있어 \\f로 나눈 쪽 번호를
    못 믿는다(독립 검토 MAJOR-1: `_ocr_out`은 박스가 있는 쪽 사이에서만 \\f를 찍어, 빈 쪽이 있으면 뒤 쪽 번호가 밀림).
    이미지 파일은 항상 1쪽. 못 세면(손상 등) None — 호출부가 안전하게(쪽 번호 확정 불가) 처리."""
    p = Path(doc_path)
    if p.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(p)))
    except Exception:
        return None


def _page_texts(base, doc_path, boxes):
    """base를 실제 쪽 번호별 글로 나눈다 — 독립 검토 MAJOR-1 반영:
    1) boxes(엔진 출력의 rep["boxes"] — OCR 엔진만, 박스마다 실제 "page" 번호) 있으면 그걸로 그룹화한다.
       글자 0개(박스 없는) 빈 쪽은 그냥 키가 없을 뿐이라 뒤 쪽 번호가 안 밀린다(\\f 세는 방식과 다름 — 이게 고친 점).
    2) boxes가 없으면(OCR 아닌 엔진) \\f로 나누되, \\f 개수가 문서의 실제 쪽 수와 같을 때만 믿는다(빈 쪽이 없다는
       뜻). 다르면 쪽 번호를 확정할 수 없음 → None(호출부가 그 문서는 dedup을 건너뛴다 — 틀린 쪽끼리 비교·치환하는
       것보다 안전한 쪽)."""
    if boxes:
        pages = {}
        for b in boxes:
            p = b.get("page")
            if p is None:
                continue
            pages.setdefault(p, []).append(b.get("text") or "")
        return {p: "\n".join(ts) for p, ts in pages.items()}
    if not base:
        return {}
    parts = base.split("\f")
    if len(parts) == 1:
        return {1: base}
    n_pages = _doc_page_count(doc_path)
    if n_pages is not None and len(parts) != n_pages:
        return None  # 쪽 번호 확정 불가 — dedup 건너뜀(MAJOR-1)
    return {i + 1: p for i, p in enumerate(parts)}


def _extra_values(loser, winner):
    """진 쪽 글에만 있는 숫자·ID 토큰 — 값 재현율 보존용(공용 숫자 추출 summarize.nums·ID 모양 common.core.text.id_terms
    재사용, 새 정규식 안 만듦). 비교 전 canon_symbols(전각→반각·대시 종류 등)로 정규화해 표기만 다른 같은 값을
    "진 쪽에만 있다"고 잘못 보고 중복 덧붙이지 않는다(독립 검토 MINOR). ID는 토큰화(common.core.text.tokens)로
    소문자·구두점 경계를 맞춘 뒤 비교."""
    lw, ww = canon_symbols(loser), canon_symbols(winner)
    lost_nums = nums({"text": lw}) - nums({"text": ww})
    win_toks = set(tokens(ww))
    lost_ids = {t for t in id_terms(tokens(lw)) if t not in win_toks}
    return sorted(lost_nums | lost_ids)


def pick(ocr_text, vlm_text):
    """한 쪽의 OCR·VLM 글 중 색인용 하나 선택.
    기본 쪽 VLM 우선 — OCR 신뢰도(1 − 깨짐률)가 0.9 이상이고 VLM 글자 수가 OCR의 절반도 안 될 때만 OCR을 쓴다.
    (문턱값 0.9·0.5는 잠정값 — 합성 구조 시험으로 고른 것이라 서버 실 VLM 개발 세트로 다시 맞춰야 한다, 독립 검토 MAJOR-2.)
    반환: (채택 글(진 쪽에만 있던 숫자·ID를 끝에 덧붙인 것), 진 쪽 글(그대로, 비교용), 채택 출처 'ocr'|'vlm')."""
    ocr_conf = 1 - parse_qa.garbage_ratio(ocr_text)
    weak_vlm = len(vlm_text.strip()) < 0.5 * max(1, len(ocr_text.strip()))
    use_ocr = bool(ocr_text.strip()) and ocr_conf >= 0.9 and weak_vlm
    winner, loser, src = (ocr_text, vlm_text, "ocr") if use_ocr else (vlm_text, ocr_text, "vlm")
    extra = _extra_values(loser, winner)
    if extra:
        winner = winner.rstrip() + "\n" + " ".join(extra)
    return winner, loser, src


def dedup(base, doc_path, boxes=None, pages=None):
    """apply_post가 "vlm_page" 기능 중 PARSE_DEDUP_SCAN=1일 때 부른다 — 쪽마다 OCR(base)·VLM 글 중 하나만
    base에 남기고 나머지는 page_alt로. OCR이 그 쪽을 전혀 못 읽었으면(빈 글) 중복이 아니라 보강이므로 그대로
    VLM으로 채운다(기존 vlm_page 동작과 같은 효과 — 잃는 쪽 없음). boxes(rep["boxes"], OCR 엔진만)를 주면 실제
    쪽 번호로 맞춘다 — 없고 \\f로도 쪽 번호를 확정할 수 없으면(독립 검토 MAJOR-1) 이 문서는 건너뛰고 이유를 남긴다.
    반환: (바뀐 base, page_alt{쪽 번호: {from, text}}, [쪽별 provenance], 중복 제거한 쪽 수, 건너뜀 이유 또는 None)."""
    if pages is None:  # represent가 이미 부른 결과가 있으면 그대로(10-29 M4 — 같은 쪽 VLM을 다시 안 부름)
        pages = vp_mod.page_text_pages(doc_path)
    if not pages:
        return base, {}, [], 0, None
    base_pages = _page_texts(base, doc_path, boxes)
    if base_pages is None:
        return base, {}, [pv for _, _, pv in pages], 0, "쪽 번호 확정 불가(\\f 개수 ≠ 문서 쪽 수, boxes 없음) — dedup 건너뜀"
    alt, provs, changed = {}, [], 0
    for page, vtext, prov in pages:
        provs.append(prov)
        if not vtext.strip():
            continue
        otext = base_pages.get(page, "")
        if not otext.strip():  # OCR이 못 읽은 쪽 — 중복 아님, 그대로 채움
            base_pages[page] = vtext
            continue
        winner, loser, src = pick(otext, vtext)
        base_pages[page] = winner
        alt[page] = {"from": ("vlm" if src == "ocr" else "ocr"), "text": loser}
        changed += 1
    if not base_pages:
        return base, {}, provs, 0, None
    new_base = "\f".join(base_pages.get(i, "") for i in range(1, max(base_pages) + 1))
    return new_base, alt, provs, changed, None
