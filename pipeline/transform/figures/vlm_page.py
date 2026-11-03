"""W4 — 스캔·이미지 문서는 쪽 전체를 VLM으로 옮겨 OCR과 나란히(교차 확인용). 원본: eval_hard_parse.one_doc(is_scan 분기)·vlm_raw(P_PAGE).

P0 열쇠(2026-10-03 수정 — "같은 문서 + 같은 기술 스택이면 다시 안 돎" 원칙): **렌더한 쪽 이미지 bytes의 sha가 아니라**
(원본 파일 sha256 + 쪽 번호 + 렌더 매개변수(dpi·max_side) + 적용한 회전(도) + 모델 + prompt_id)의 결정적 열쇠를 쓴다 — PDF 렌더·이미지
재인코딩이 실행마다 바이트까지 같다는 보장이 없어서(prepare.py를 두 번 돌리면 렌더 바이트가 달라질 수 있음), 렌더 바이트 열쇠는 "다시 준비"만
해도 캐시가 깨진다. 원본 sha는 `prepare.py`가 회전 전 파일의 sha256을 `rotation.csv`(`orig_sha256` 열)에 남긴 것을 읽는다(없으면 —
rotation.csv가 옛 버전이거나 이 문서가 거기 없으면 — 렌더 바이트 sha로 떨어진다, 아래 `vlm_page` 대체 경로).
저장: `raw/vlm/<모델>/page-v1-<sha8>/det-<열쇠16>.json`(새 — 기본) · 읽기만: `raw/vlm/<모델>/page-v1-<sha8>/<렌더 바이트 sha12>.json`
(프로토타입의 기존 캐시 — 맞으면 쓰고 결정적 열쇠로도 복사해 다음부터는 그쪽만 봄)."""

import base64
import hashlib
import io
import json
import re
import time
import urllib.parse
from pathlib import Path

from common.ai import adk as A
from common.ai.agent_prompts import load as _load_prompt
from common.config.settings import cfg as ccfg  # common 칸 설정 객체(S7c)
from common.core import span as SP  # op-01 성능 span(풀 스레드 컨텍스트 전달)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.artifacts import prompt_id, raw_vlm_path
from pipeline.shared.postprocess import raw_root  # PARSE_RAW_ROOT(이중 raw/ 방지 포함, post/__init__.py)
from pipeline.transform.figures.vector import vector_regions  # 쪽 벡터 도형 군집 수(page_signals)

NOW = time.strftime("%Y-%m-%dT%H:%M:%S")

P_PAGE = _load_prompt("page_transcribe", "page")  # AD33 — 글자는 dev/agents/page_transcribe/prompts/page.md
PID_PAGE = prompt_id("page", "v1", P_PAGE)  # 프로토타입과 같은 글자 → 같은 id(기존 VLM 캐시 재사용)
DPI, MAX_SIDE = 150, 2000  # pages_of()·_png() 렌더 매개변수 — 결정적 열쇠에 들어감(바뀌면 새 열쇠)

# AD12·AD46(D2·D4·D6 공용 문서 검사 표) — 글자 PDF 안의 스캔 쪽 판정 기준값. 문서 단위 is_scan의 20자와 같은 값으로 보수적으로
# 맞춤(AD31 — 글자 PDF 안의 스캔 쪽 신호는 늘 봄).
PAGE_SCAN_CHARS = 20  # 글자층 "거의 없음"
PAGE_SCAN_AREA = 0.6  # 이미지 면적 비율(쪽 면적 대비) "큼"
# AD31 — 쓰레기·숨은 글자층 신호(garbage_ratio는 AD12부터 신호 표에 있었고, hidden_ratio는 이번에 추가). 이미지 면적
# 조건은 garbage_ratio 쪽은 그대로(PAGE_SCAN_AREA), 숨은 글자층 쪽은 완화(PAGE_HIDDEN_AREA) — 그림이 쪽 전체를
# 안 덮어도(숨은 글자가 그림과 무관하게 깔려 있으면) 스캔으로 본다.
PAGE_SCAN_GARBAGE = 0.5  # garbage_ratio "높음"
PAGE_HIDDEN_RATIO = 0.6  # 보이지 않는 글자(render mode 3·순백색) 비율 "높음"
PAGE_HIDDEN_AREA = 0.3  # 숨은 글자층 쪽의 완화된 이미지 면적 기준
# AD47 — 쪽 대부분은 정상 글자(hidden_ratio·image_area_ratio 둘 다 낮음)인데 값 하나만 그림 위에 숨은 글자로 깔린
# 경우(synth-mixedpdf textlayer_mismatch.pdf: 보이는 값은 그림 속 "430,000", 숨은 글자층은 틀린 "430.000") — 쪽 전체
# 비율로는 못 잡으니 국소 겹침(숨은 글자 상자 하나가 그림 bbox와 겹치는지)을 따로 본다. 문서당 상한
# PARSE_HIDDEN_OVERLAP_MAX(env, 기본 20) — 0이면 꺼짐(이 신호를 안 봄, scan_pages_detail이 이전과 바이트 동일).
PARSE_HIDDEN_OVERLAP_MAX_DEFAULT = "20"
# AD31(남은 것, 10-08) — 회전·벡터 도형 신호(규칙만, VLM 예/아니오 판단은 AG11 몫, 렌더 OCR≫글자층 신호는 pl-34 10-30에 지움). 둘 다
# 문서당 상한 env(0=꺼짐, 이 신호를 안 봄 — scan_pages_detail이 그 조건 자체를 안 보므로 바이트 동일)로 기본 켬(OP11).
PAGE_VECTORS_MIN = 3  # 쪽 안 벡터 도식 군집 수(post.vector.vector_regions) "많음" — 복잡한 도형·SmartArt류 페이지 후보
PARSE_VECTORS_MAX_DEFAULT = "20"
PARSE_ROTATED_MAX_DEFAULT = "20"  # prepare.py가 돌린(각도≠0) 쪽 — 회전 전 OCR 품질이 낮았을 수 있어 쪽 VLM 후보


def _cap(name, default):
    return int(
        pc.by_env(name, default)
    )  # S7c — 설정 객체(옛 int(get(name, default)), ValueError면 int(default) — 객체는 ''·형식 틀림 = 칸 기본값)


def _hidden_overlap_cap():
    return _cap("PARSE_HIDDEN_OVERLAP_MAX", PARSE_HIDDEN_OVERLAP_MAX_DEFAULT)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def is_scan(p):
    """스캔·이미지 문서 판정(원본: eval_hard_parse.one_doc) — png·jpg류 또는 글자층 20자 미만 쪽만 있는 PDF."""
    p = Path(p)
    ext = p.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
        return True
    if ext != ".pdf":
        return False
    import fitz

    return all(len(pg.get_text().strip()) < 20 for pg in fitz.open(p))


PAGE_SIGNALS_VERSION = "v3"  # 독립 검토 A — 알고리즘·상수(PAGE_SCAN_*·image_area_ratio 계산법 등) 바뀌면 올려 캐시 무효화
# v2(AD31) — hidden_ratio 신호 추가 + garbage_ratio를 scan_pages 판정에 편입(판정 바뀜)
# v3(AD47) — hidden_over_image 필드 추가(새 필드, 옛 캐시엔 없어 무효화 필요)


def _signals_path(file_sha256):
    """쪽 신호 캐시 파일 — raw_root()/signals/page_signals@<버전>/<파일 sha256 앞 16자>.json(content-addressed,
    `<name>@<version>` 관례는 pipeline.shared.artifacts.raw_engine_path·raw_vlm_path와 같음 — 기존 VLM 캐시 원칙 그대로.
    tools/parse_agent_tools.inspect_document도 이걸 읽고/채운다, AD46 '한 번 계산해 저장, 판단들이 읽음')."""
    return Path(raw_root()) / "signals" / f"page_signals@{PAGE_SIGNALS_VERSION}" / f"{file_sha256[:16]}.json"


def _is_hidden_span(sp):
    """AD31·AD47 공용 — get_texttrace() span 하나가 '보이지 않는 글자'인지: type==3(invisible render mode)
    또는 color==(1,1,1)(흰 글자, 배경이 흰색이면 안 보임)."""
    return sp.get("type") == 3 or sp.get("color") == (1.0, 1.0, 1.0)


def _hidden_ratio(pg):
    """AD31 — 보이지 않는 글자 비율(쪽 전체) = _is_hidden_span인 글자 수 ÷ 전체 글자 수.
    예: OCR 뒤 숨겨 깔린 글자층(render_mode=3)이나 그림과 무관한 흰 글자 — 시각은 그림인데 글자 수만 차 있어
    chars 신호만으로는 .pdf_text(글자형)로 잘못 판정될 수 있다."""
    try:
        tt = pg.get_texttrace()
    except Exception:
        return 0.0
    hidden = total = 0
    for sp in tt:
        n = len(sp.get("chars") or [])
        total += n
        if _is_hidden_span(sp):
            hidden += n
    return round(hidden / total, 4) if total else 0.0


def _hidden_overlap_detail(pg, img_rects):
    """AD47 — 보이지 않는 글자 상자 중 삽입 그림(img_rects)과 겹치는 것만 [(bbox, text), ...]로.
    page_signals의 hidden_over_image(bool)와 represent.fill_scan_pages의 국소 일치도 확인(검토자 반영,
    10-08 CONCERN) 둘 다 이 함수를 쓴다 — 쪽 전체 비율(_hidden_ratio·image_area_ratio)로는 못 잡는 국소
    겹침(쪽 대부분은 정상 글자인데 값 하나만 그림 위에 숨음)을 찾는 것이 목적. img_rects가 비면 항상 []."""
    if not img_rects:
        return []
    try:
        tt = pg.get_texttrace()
    except Exception:
        return []
    import fitz

    out = []
    for sp in tt:
        if not _is_hidden_span(sp):
            continue
        bbox = sp.get("bbox")
        if not bbox:
            continue
        sr = fitz.Rect(bbox)
        if any(not (sr & r).is_empty for r in img_rects):
            text = "".join(chr(c[0]) for c in (sp.get("chars") or []))
            out.append((tuple(round(v, 2) for v in bbox), text))
    return out


def _hidden_image_overlap(pg, img_rects):
    """AD47 — page_signals용 bool(겹친 숨은 글자 상자가 하나라도 있나). 실제 text·bbox가 필요하면
    hidden_overlap_spans()(문서 경로로 다시 열어 계산)를 쓴다."""
    return bool(_hidden_overlap_detail(pg, img_rects))


def hidden_overlap_spans(path, page_no):
    """AD47 검토자 반영(10-08) — scan_pages_detail이 reason='hidden_overlap'로 고른 쪽의 실제 겹친 숨은
    글자 상자들(bbox·text) — represent.fill_scan_pages가 국소(쪽 전체가 아니라 그 상자 주변만) 일치도를
    보는 데 쓴다. page_signals 캐시는 bool만 들고 있어(내용을 캐시에 안 넣음) 그 쪽 하나만 다시 연다(문서
    전체를 다시 열거나 매 쪽을 다시 계산하지 않음 — reason='hidden_overlap' 쪽만, 상한 PARSE_HIDDEN_OVERLAP_MAX로
    이미 적은 수)."""
    import fitz

    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return []
    doc = fitz.open(p)
    try:
        if page_no < 1 or page_no > len(doc):
            return []
        pg = doc[page_no - 1]
        page_rect = pg.rect
        img_rects = []
        for x in pg.get_images(full=True):
            rects = pg.get_image_rects(x[0])
            if rects:
                r = fitz.Rect(rects[0]) & page_rect
                if not r.is_empty:
                    img_rects.append(r)
        return _hidden_overlap_detail(pg, img_rects)
    finally:
        doc.close()


def page_signals(path):
    """AD12·AD46(D2 글자층·D4 이미지 섞임·D6 쪽 VLM이 같은 표를 읽음) — PDF 쪽마다
    [{page, chars(글자층 글자 수), image_area_ratio(삽입 이미지 면적 ÷ 쪽 면적), figures(삽입 그림 수),
    vectors(벡터 도형 군집 수 — post.vector.vector_regions), garbage_ratio, hidden_ratio(AD31 — 보이지 않는 글자 비율),
    hidden_over_image(AD47 — 보이지 않는 글자 상자 하나가 그림과 겹치는지, 국소 신호)}]. PDF가 아니면 [].
    (렌더 OCR 글자 수 ocr_chars는 pl-34 10-30에 지움 — 옛 캐시에 남은 ocr_chars 칸은 읽지 않음)
    원본 파일 sha256로 한 번 계산해 _signals_path 캐시에 저장 — 다시 부르면 그 파일을 읽어 같은 쪽을 다시 안 연다."""
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return []
    cache = _signals_path(sha(p.read_bytes()))
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import fitz

    from pipeline.transform.represent.parse_qa import garbage_ratio

    out = []
    for i, pg in enumerate(fitz.open(p), 1):
        text = pg.get_text()
        page_rect = pg.rect
        page_area = page_rect.width * page_rect.height
        imgs = pg.get_images(full=True)
        img_area = 0.0
        img_rects = []
        for x in imgs:
            rects = pg.get_image_rects(x[0])
            if rects:
                r = fitz.Rect(rects[0]) & page_rect  # 독립 검토 C — 쪽 밖으로 나간 bbox는 쪽 안쪽만 셈
                if not r.is_empty:
                    img_area += r.width * r.height
                    img_rects.append(r)  # AD47 — 숨은 글자 겹침 판정에 재사용(쪽 안쪽으로 자른 뒤)
        # 독립 검토 C — 여러 이미지가 겹치면 각자 면적의 합이 쪽 면적을 넘을 수 있어 1.0 상한(겹침 합집합의 근사)
        rec = {
            "page": i,
            "chars": len(text.strip()),
            "image_area_ratio": round(min(1.0, img_area / page_area), 4) if page_area else 0.0,
            "figures": len(imgs),
            "vectors": len(vector_regions(pg)),
            "garbage_ratio": garbage_ratio(text),
            "hidden_ratio": _hidden_ratio(pg),
            "hidden_over_image": _hidden_image_overlap(pg, img_rects),
        }
        out.append(rec)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def scan_pages_detail(path):
    """AD12·AD31 — 글자 PDF 안의 스캔 쪽(쪽 번호 1부터) → 걸린 이유(쪽마다 하나, 먼저 맞는 것):
    'chars'  = 글자층 거의 없음(< PAGE_SCAN_CHARS) + 이미지 면적 큼(>= PAGE_SCAN_AREA) — 원래 AD12 조건
    'hidden' = 숨은 글자층 비율 높음(>= PAGE_HIDDEN_RATIO) + 이미지 면적(완화, >= PAGE_HIDDEN_AREA) — 그림은 정상인데
               보이지 않는 글자(render mode 3·흰 글자)가 깔린 쪽(AD31, 쓰레기/숨은 글자층 신호). **독립 검토 MAJOR(10-07)**:
               숨은 글자층이 그림과 '무관'한지 안 가린다 — 이미지와 같은 내용의 양질 OCR 글자층(검색 가능 스캔 PDF)도
               hidden_ratio·image_area_ratio가 똑같이 높아 여기 걸린다. 지금은 **일부러 보수적으로 스캔 후보에 넣음**
               (OCR 엔진이 대조 재료로 다시 읽어도 손해 없음 — AD12 `_ocr_fallback_needed`는 후보만 넓히고 대표 선택은
               안 바꿈) — 숨은 층이 기존 OCR과 '일치'하면 원래 글을 유지할지는 reason='hidden'을 읽는 다음 단계(대표
               결과 선택, represent.py) 몫. 이 함수는 이유만 남기고 그 판단은 안 한다.
    'garbage' = 글자층 깨짐 비율 높음(>= PAGE_SCAN_GARBAGE) + 이미지 면적 큼(>= PAGE_SCAN_AREA)
    'hidden_overlap' = AD47 — 위 둘 다 쪽 전체 비율이라 못 잡는 국소 사례: 쪽 대부분은 정상 글자인데 숨은 글자
               상자 하나가 그림과 겹친다(hidden_over_image). 'hidden'과 달리 **_page_agreement로 "원래 글 유지"
               판단을 거치지 않고** represent.fill_scan_pages가 그 쪽을 곧바로 OCR 글로 바꾼다 — 숨은 글자층과
               보이는 값이 쉼표/마침표만 다르면(430.000 vs 430,000) _page_agreement의 정규화가 그 차이를 지워
               버려 "일치"로 오판(원래 틀린 글을 유지)하기 때문(synth-mixedpdf textlayer_mismatch.pdf로 확인). 문서당
               상한 PARSE_HIDDEN_OVERLAP_MAX(env, 기본 20, 0=꺼짐 — 이 조건 자체를 안 봐 이전과 바이트 동일).
    'rotated' = AD31(10-08) — prepare.py가 돌린 쪽(rotation.csv의 angle≠0, rotation_info 재사용) — 회전 전
               OCR 점수로 방향을 골랐어도 회전 자체가 쪽의 글자층 추출 신뢰도를 낮출 수 있어 쪽 VLM 후보로 넓힌다.
               상한 PARSE_ROTATED_MAX(env, 기본 20, 0=꺼짐 — rotation.csv를 안 읽음).
    'vectors' = AD31(10-08) — 쪽 안 벡터 도식 군집 수(vectors, post.vector.vector_regions)가 PAGE_VECTORS_MIN
               (기본 3) 이상 — 도형·SmartArt류가 많아 글자층만으로는 구조를 못 담는 페이지. 상한
               PARSE_VECTORS_MAX(env, 기본 20, 0=꺼짐). (규칙 신호만 — VLM에 보일지 말지의 '가벼운 판단'은 AG11 몫)
    문서 전체가 스캔(is_scan)이면 page_text가 이 함수를 안 부른다(전체 쪽 경로 그대로)."""
    cap = _hidden_overlap_cap()
    vec_cap, rot_cap = (
        _cap("PARSE_VECTORS_MAX", PARSE_VECTORS_MAX_DEFAULT),
        _cap("PARSE_ROTATED_MAX", PARSE_ROTATED_MAX_DEFAULT),
    )
    rot = rotation_info(path) if rot_cap else {}  # rot_cap==0이면 rotation.csv를 안 읽음(이전과 바이트 동일)
    n_overlap = n_rot = n_vec = 0
    out = {}
    for r in page_signals(path):
        area = r["image_area_ratio"]
        if r["chars"] < PAGE_SCAN_CHARS and area >= PAGE_SCAN_AREA:
            out[r["page"]] = "chars"
        elif r.get("hidden_ratio", 0.0) >= PAGE_HIDDEN_RATIO and area >= PAGE_HIDDEN_AREA:
            out[r["page"]] = "hidden"
        elif r.get("hidden_over_image") and n_overlap < cap:
            out[r["page"]] = "hidden_overlap"
            n_overlap += 1
        elif r.get("garbage_ratio", 0.0) >= PAGE_SCAN_GARBAGE and area >= PAGE_SCAN_AREA:
            out[r["page"]] = "garbage"
        elif (rot.get(r["page"], {}).get("angle") or 0) != 0 and n_rot < rot_cap:
            out[r["page"]] = "rotated"
            n_rot += 1
        elif r.get("vectors", 0) >= PAGE_VECTORS_MIN and n_vec < vec_cap:
            out[r["page"]] = "vectors"
            n_vec += 1
    return out


def scan_pages(path):
    """AD12·AD31 — 글자 PDF 안의 스캔 쪽 번호 목록(판정은 scan_pages_detail과 같음, 이유 없이 쪽 번호만 — 기존 호출부 호환)."""
    return list(scan_pages_detail(path).keys())


def pages_of(p):
    """쪽 이미지 bytes 목록 — PDF는 150dpi 렌더(프로토타입과 같은 dpi라 쪽 이미지 sha가 맞음), 그 외는 원본 파일 그대로."""
    p = Path(p)
    if p.suffix.lower() == ".pdf":
        import fitz

        return [pg.get_pixmap(dpi=DPI).tobytes("png") for pg in fitz.open(p)]
    return [p.read_bytes()]


def rotation_info(doc_path):
    """`<doc_path 폴더>/rotation.csv`에서 이 문서의 {쪽 번호: {angle, orig_sha256}} — prepare.py가 남김. 없으면 빈 묶음(아래서 대체 경로)."""
    doc_path = Path(doc_path)
    f = doc_path.parent / "rotation.csv"
    out = {}
    if not f.exists():
        return out
    import csv

    with f.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("file") == doc_path.name:
                try:
                    out[int(row["page"])] = {"angle": int(row.get("angle") or 0), "orig_sha256": row.get("orig_sha256") or None}
                except (TypeError, ValueError):
                    pass
    return out


def det_key(source_sha256, page_idx, dpi, max_side, rotation_deg, model, prompt_id_):
    """결정적 P0 열쇠(16자) — 렌더 바이트가 아니라 원본·쪽·매개변수·모델로. 부분이 하나라도 바뀌면 다른 열쇠."""
    parts = {
        "source_sha256": source_sha256,
        "page": page_idx,
        "dpi": dpi,
        "max_side": max_side,
        "rotation_deg": rotation_deg,
        "model": model,
        "prompt_id": prompt_id_,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def det_path(store, model_dir, name, version, prompt_text, key16):
    """raw_vlm_path와 같은 폴더(raw/vlm/<모델>/<prompt_id>/)에 파일 이름만 'det-<열쇠>'로 — 렌더 sha(12자 hex)와 안 겹침."""
    return Path(store) / "raw" / "vlm" / model_dir / prompt_id(name, version, prompt_text) / f"det-{key16}.json"


def _model_dir(model):
    """프로토타입(eval_hard_parse.vlm_raw)과 같은 폴더 이름 정리 규칙 — '/'가 든 모델 이름도 기존 캐시와 같은 폴더로."""
    return re.sub(r"[^\w.-]+", "_", model or "unset")


def _png(img, max_side=2000):
    from PIL import Image

    im = Image.open(io.BytesIO(img))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), f"{im.width}x{im.height}"


def _log_failed_page_vlm(model, ms, reason):
    """2026-10-22 — 실패(취소·타임아웃·빈 응답)한 페이지 VLM 호출의 대기 시간을 raw/vlm/<model>/_failures.jsonl에 append.
    성공 provenance는 원래 캐시 파일로 남지만 실패는 안 남아 집계에서 빠졌었다 — 이제 실패 ms도 집계 가능."""
    try:
        from pipeline.shared.postprocess.rawstore import raw_vlm_path  # 있으면 사용, 없으면 아래 폴백
    except ImportError:
        raw_vlm_path = None
    try:
        _b = ccfg().models.vlm.base_url  # S7c — 설정 객체(옛 get(X, "") — 캐시 열쇠 글자 그대로)
        base = raw_vlm_path(_b if _b is not None else "", model, "page", "fail") if raw_vlm_path else None
        if base is None:
            base = _rawdir_default(model)
        base.parent.mkdir(parents=True, exist_ok=True)
        with (base.parent / "_failures.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ms": ms, "error": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rawdir_default(model):
    """raw_vlm_path가 없을 때 — RAG_OUT(없으면 런타임 루트 output/ — 이미지 안 /app/output)/parse/raw/vlm/<model>/page/ 기본 경로."""
    from pathlib import Path

    from common.core.paths import APP_ROOT

    m = (model or "unknown").replace("/", "_")
    _o = ccfg().paths.output_root  # S7c — 설정 객체(옛 get("RAG_OUT", 기본) — 빈 글자도 그대로)
    return Path(_o if _o is not None else str(APP_ROOT / "output")) / "parse" / "raw" / "vlm" / m / "page" / "fail"


def _host(url):
    return urllib.parse.urlparse(url).hostname or url


def vlm_page(img_bytes, det=None):
    """쪽 1장 → (마크다운 글자, provenance). P0 — det(= {"source_sha256","page","rotation_deg"})가 있으면 결정적 열쇠로 찾는다(렌더
    바이트가 달라도 재사용) · 없으면(det None — 원본 sha를 못 구함) 렌더 바이트 sha로(예전 동작, 재준비하면 캐시가 깨질 수 있음).
    det가 있어도 결정적 캐시가 비었으면 렌더 sha(프로토타입 캐시) 경로를 읽기만 시도 — 맞으면 결정적 열쇠로도 복사해 다음부터 안 읽게.
    실패·빈 답은 저장 안 함. 프로토타입은 쪽 옮기기에서 추론을 끄지 않는다(그림 JSON과 달리 출력 상한을 넉넉히 써도 됨 — 실측 캐시에
    reasoning 끈 흔적 없음) — 여기도 같게 둔다."""
    base, model = ccfg().models.vlm.base_url, ccfg().models.vlm.model  # S7c — 설정 객체
    model_dir = _model_dir(model)
    render_sha = sha(img_bytes)
    legacy = raw_vlm_path(raw_root(), model_dir, "page", "v1", P_PAGE, render_sha)
    dpath = None
    if det and det.get("source_sha256"):
        k16 = det_key(
            det["source_sha256"], det["page"], DPI if det.get("is_pdf") else None, MAX_SIDE, det.get("rotation_deg") or 0, model, PID_PAGE
        )
        dpath = det_path(raw_root(), model_dir, "page", "v1", P_PAGE, k16)
        if dpath.exists():
            rec = json.loads(dpath.read_text(encoding="utf-8"))
            return rec["text"], {**rec["provenance"], "cached": True, "via": "det"}
    if legacy.exists():  # 읽기 대체 경로 — 프로토타입(또는 예전 운영) 캐시가 맞으면 그대로 쓰고 승격
        rec = json.loads(legacy.read_text(encoding="utf-8"))
        if dpath is not None:
            dpath.parent.mkdir(parents=True, exist_ok=True)
            dpath.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")  # 결정적 열쇠로 복사 — 다음부터 렌더 sha 안 봐도 됨
        return rec["text"], {**rec["provenance"], "cached": True, "via": "legacy_image_sha"}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 쪽 옮기기 없이 OCR만", "cached": False}
    data, px = _png(img_bytes)
    _dl = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체(옛 float(get(X) or 360))
    deadline = float(_dl if _dl is not None else 360)
    t0 = time.perf_counter()
    try:
        from pipeline.transform.figures.vgate import (
            slot as _vgate_slot,
        )  # 전역 VLM in-flight 게이트(합 VLM_GLOBAL_CONCURRENCY — 2026-10-22)

        with _vgate_slot():
            text, u = A.complete(
                "vlm",
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": P_PAGE},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                        ],
                    }
                ],
                temperature=0,
                max_tokens=None,
                timeout=deadline,
                agent="page_transcribe",
            )
    except A.ModelUnavailable as ex:
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"unavailable: {str(ex)[:120]}")
        return "", {"error": str(ex)[:200], "ms": _ms, "cached": False}
    except Exception as ex:  # 2026-10-22 — 취소·타임아웃 등 기타 예외도 시간 기록
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"{type(ex).__name__}: {str(ex)[:120]}")
        raise
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        _log_failed_page_vlm(model, ms, "빈 응답")
        return "", {"error": "빈 읭", "ms": ms, "cached": False}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
    prov = {
        "model": model,
        "endpoint_host": _host(base),
        "prompt_id": PID_PAGE,
        "image_sha256": render_sha,
        "px": px,
        "params": {"temperature": 0, "max_side": MAX_SIDE},
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
        "created_at": NOW,
        "cached": False,
    }  # image_sha256 = 렌더 바이트 sha(추적용, 열쇠 아님)
    rec = {"text": text, "provenance": {k: v for k, v in prov.items() if k != "cached"}}
    # 결정적 열쇠가 있으면 그쪽에 저장(앞으로 재사용), 없으면 예전처럼 렌더 sha 경로에(대체 경로)
    dest = dpath if dpath is not None else legacy
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return text, prov


def _max_pages():
    """VLM_PAGE_MAX — 비었으면 전부, '0'이면 꺼짐(이 기능 호출 자체를 안 함), N이면 문서당 앞 N쪽만."""
    pc.checked("VLM_PAGE_MAX")  # 형식이 틀리면 옛 int(v)처럼 여기서 실패(기본값이 '제한 없음'이라 조용히 넘기지 않음)
    v = pc.cfg().transform.vlm.page_max  # S7c — 설정 객체(int 칸: 없음·빈 값 = None)
    if v is None:
        return None
    return int(v)


def page_targets(doc_path):
    """독립 검토 반영(10-11, AD31/AD20 BLOCK) — 이 문서에서 **실제로** 쪽 VLM이 호출될 쪽 번호 집합 — 한 곳에서
    계산해 page_text_pages()·figures.py 둘 다 이 함수만 본다(pptx_render.target_slides와 같은 패턴, 따로 추정 안 함).
    접는 조건(먼저 맞는 것이 빈 집합):
      - PARSE_POST에 'vlm_page'가 없음(represent.apply_post가 쪽 VLM 자체를 안 부름 — active_features() 그대로 읽음.
        독립 검토가 지적한 원래 버그: figures.py가 scan_pages()만 보고 이 조건을 몰라, 쪽 VLM이 안 도는데도 그림을 건너뛰어 내용 손실)
      - VLM_PAGE_MAX=='0'(비용·시간 가드로 꺼짐)
      - PDF도 아니고 문서 전체 스캔(is_scan)도 아님 — 쪽 VLM 대상 자체가 없음
      - 글자 PDF인데 스캔 신호 쪽이 하나도 없음(scan_pages 빈 목록)
    남는 경우: 문서 전체가 스캔(이미지 파일 또는 스캔 PDF)이면 전체 쪽, 아니면 scan_pages() 결과 — 거기에
    VLM_PAGE_MAX(cap) 절단까지 적용한 뒤 집합으로(독립 검토가 지적한 둘째 버그: cap으로 잘려 실제로 안 불릴
    쪽까지 figures.py가 건너뛰던 것 — 여기서 자른 뒤 돌려주므로 호출자가 또 자를 필요 없음)."""
    from pipeline.shared.postprocess import active_features

    if "vlm_page" not in active_features():
        return set()
    cap = _max_pages()
    if cap == 0:
        return set()
    p = Path(doc_path)
    if is_scan(p):
        return pick_pages(len(pages_of(p)), True, [], cap)
    if p.suffix.lower() != ".pdf":
        return set()
    # AD12·AD31 — 글자 PDF 안의 스캔 쪽만(쓰레기·숨은 글자층·OCR≫글자층·회전·벡터 도식 신호 — scan_pages_detail 참고)
    return pick_pages(0, False, scan_pages(p), cap)


def pick_pages(n_pages, whole_scan, scan, cap):
    """쪽 VLM 대상 쪽(순수 함수, 10-29) — 문서 전체가 스캔이면 1..n_pages 전부, 아니면 스캔 신호 쪽(scan)만 · cap(None = 제한 없음)으로
    앞에서 자른 집합. 글자 PDF 안의 스캔 쪽만 쪽 VLM을 부르고(병렬 — page_text_pages) 대표 결과가 그 쪽을 VLM 글로 채운다."""
    targets = list(range(1, n_pages + 1)) if whole_scan else list(scan)
    return set(targets if cap is None else targets[:cap])


def page_text_pages(doc_path):
    """문서 전체(또는 AD12·AD31 — 글자 PDF 안의 스캔 쪽만) 쪽 VLM 옮기기 —
    쪽 단위로 [(쪽 번호, 글, provenance), ...] (scan_fill이 그 쪽만 채우려면 page_text처럼
    합친 글이 아니라 쪽 번호가 필요). 대상 쪽 계산은 page_targets()(단일 진본, figures.py와 공유) — 여기선 그
    번호로 실제 렌더·VLM 호출만 한다."""
    # 2026-10-22 — 쪽 전사를 순차→병렬로: 15쪽 × 26초 순차=390초 wall → 병렬(min(N,병렬)배치=wall 최소화), 품질 무변
    idxs = sorted(page_targets(doc_path))
    if not idxs:
        return []
    p = Path(doc_path)
    pages = pages_of(p)
    rot = rotation_info(p)
    is_pdf = p.suffix.lower() == ".pdf"

    def _one(i):
        img = pages[i - 1]
        info = rot.get(i) or {}
        det = (
            {"source_sha256": info.get("orig_sha256"), "page": i, "rotation_deg": info.get("angle") or 0, "is_pdf": is_pdf}
            if info.get("orig_sha256")
            else None
        )
        text, prov = vlm_page(img, det)
        return (i, text, prov)

    # 2026-10-22 — 적응적 병렬: 느린 VLM 응답 시 워커 수 절반으로, 빠르면 유지
    # VLM_PAGE_SLOW(기본 60초) 이상 걸린 call이 있으면 다음 배치의 워커를 절반으로 → GPU 포화 자동 완화
    _tv = pc.cfg().transform.vlm  # S7c — 설정 객체(옛 get(A) or get(B) or 4 — 0도 참 글자라 is None 사슬)
    _n = _tv.page_concurrency if _tv.page_concurrency is not None else ccfg().models.vlm.concurrency
    n_max = max(1, int(_n if _n is not None else 4))
    n_min = int(_tv.page_min_concurrency if _tv.page_min_concurrency is not None else 2)
    _slow = float(_tv.page_slow if _tv.page_slow is not None else 60)  # 콜이 이 시간(초) 초과면 병렬 수 축소
    n = min(n_max, len(idxs))
    if n <= 1 or len(idxs) <= 1:
        return [_one(i) for i in idxs]

    import concurrent.futures
    from itertools import islice

    it = iter(idxs)
    out = []
    while True:
        batch = list(islice(it, n))
        if not batch:
            break
        if len(batch) == 1:
            out.append(_one(batch[0]))
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as ex:
            batch_out = list(ex.map(SP.carry(_one), batch))  # ex.map은 입력 순서 보존 · op-01 — run/span ID를 풀 스레드에 실음
        out.extend(batch_out)
        # 적응적: 이 배치에서 가장 느린 call이 _slow를 넘었으면 워커 수 절반 (최소 n_min)
        slowest = 0.0
        for _, _, pv in batch_out:
            if isinstance(pv, dict) and pv.get("ms"):
                slowest = max(slowest, float(pv["ms"]))
        if slowest > _slow * 1000 and n > n_min:
            n = max(n_min, n // 2)
            print(f"[vlm_page] VLM 응답 {slowest / 1000:.0f}초 > {_slow:.0f}초 → 병렬 수 {n * 2}→{n} 감소 (GPU02 부하 완화)", flush=True)
        elif slowest < _slow * 1000 // 2 and n < n_max:
            n = min(n_max, n * 2)  # 반대로 빠르면 회복
    return out


def page_text(doc_path):
    """문서 전체(또는 AD12·AD31 — 글자 PDF 안의 스캔 쪽만) 쪽 VLM 옮기기 — 둘 다 아니면 빈 문자열
    (호출 0) · VLM_PAGE_MAX=0이면 꺼짐. 반환: (쪽마다 옮긴 글자를 합친 것, [쪽별 provenance]). 결정적 열쇠(det)는
    rotation.csv의 orig_sha256·angle로 — 없으면 렌더 바이트 sha로 대체(옛 rotation.csv·목록에 없는 문서)."""
    pages = page_text_pages(doc_path)
    return "\n".join(t for _, t, _ in pages if t), [pv for _, _, pv in pages]
