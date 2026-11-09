"""쪽 VLM 대상 고르기 — PDF 쪽 신호(page_signals)로 글자 PDF 안의 스캔 쪽을 찾고(scan_pages_detail), 실제로 VLM에
보낼 쪽(page_targets)을 정해 shared/vlmcall.transcribe로 옮긴다. 쪽 캐시 열쇠 = 원본 sha256(rotation.csv의 회전 전 orig_sha256)
+ 쪽 번호 + 렌더 매개변수(dpi·긴 변) + 회전 각도 + 모델 + 지시서 id — 렌더 바이트는 실행마다 다를 수 있어 열쇠로 쓰지 않는다."""

import json
from pathlib import Path

from pipeline import config as pc
from pipeline.shared.ext_groups import IMG_EXTS
from pipeline.shared.pdf_kind import pdf_kind
from pipeline.shared.raw_cache import raw_root
from pipeline.shared.vlmcall import (  # 쪽 VLM 호출·캐시(엔진 qwen_vlm과 같은 함수)
    page_count,
    page_max,
    rotation_info,
    sha,
    transcribe,
)
from pipeline.transform.figures.vector_regions import vector_regions  # 쪽 벡터 도형 군집 수(page_signals)

# 글자 PDF 안의 스캔 쪽 판정 기준값(문서 단위 pdf_kind의 쪽당 20자와 같은 값)
PAGE_SCAN_CHARS = 20  # 글자층 "거의 없음"
PAGE_SCAN_AREA = 0.6  # 이미지 면적 비율(쪽 면적 대비) "큼"
# 숨은 글자층은 그림이 쪽 전체를 안 덮어도 스캔으로 보도록 면적 기준을 낮춘다(PAGE_HIDDEN_AREA)
PAGE_SCAN_GARBAGE = 0.5  # garbage_ratio "높음"
PAGE_HIDDEN_RATIO = 0.6  # 보이지 않는 글자(render mode 3·순백색) 비율 "높음"
PAGE_HIDDEN_AREA = 0.3  # 숨은 글자층 쪽의 완화된 이미지 면적 기준
# 쪽 대부분은 정상 글자인데 값 하나만 그림 위 숨은 글자로 깔린 경우 — 쪽 전체 비율로 못 잡아 국소 겹침을 따로 본다.
# 숨은 글자 겹침·회전·벡터 도형 신호는 문서당 상한이 있다(설정 — 0 = 이 신호를 안 봄).
PAGE_VECTORS_MIN = 3  # 쪽 안 벡터 도식 군집 수 "많음" — 복잡한 도형·SmartArt류 쪽 후보


def is_scan(p):
    """스캔·이미지 문서인지 — 이미지 파일이거나 pdf_kind가 pdf_image인 PDF."""
    p = Path(p)
    ext = p.suffix.lower()
    if ext in IMG_EXTS:
        return True
    return ext == ".pdf" and pdf_kind(p)[0] == "pdf_image"


PAGE_SIGNALS_VERSION = "v3"  # 신호 계산법·칸이 바뀌면 올려 쪽 신호 캐시를 무효화


def _signals_path(file_sha256):
    """쪽 신호 캐시 파일 — raw_root()/signals/page_signals@<버전>/<파일 sha256 앞 16자>.json(내용 주소)."""
    return Path(raw_root()) / "signals" / f"page_signals@{PAGE_SIGNALS_VERSION}" / f"{file_sha256[:16]}.json"


def _is_hidden_span(sp):
    """get_texttrace() span 하나가 '보이지 않는 글자'인지: type==3(invisible render mode)
    또는 color==(1,1,1)(흰 글자, 배경이 흰색이면 안 보임)."""
    return sp.get("type") == 3 or sp.get("color") == (1.0, 1.0, 1.0)


def _hidden_ratio(pg):
    """보이지 않는 글자 비율(쪽 전체) = _is_hidden_span인 글자 수 ÷ 전체 글자 수.
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
    """보이지 않는 글자 상자 중 삽입 그림(img_rects)과 겹치는 것만 [(bbox, text), ...]로 — 쪽 전체 비율로는 못 잡는 국소
    겹침(쪽 대부분은 정상 글자인데 값 하나만 그림 위에 숨음)을 찾는다. img_rects가 비면 항상 []."""
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
    """page_signals용 bool(겹친 숨은 글자 상자가 하나라도 있나)."""
    return bool(_hidden_overlap_detail(pg, img_rects))


def page_signals(path):
    """PDF 쪽마다 [{page, chars(글자층 글자 수), image_area_ratio(삽입 이미지 면적 ÷ 쪽 면적), figures(삽입 그림 수),
    vectors(벡터 도형 군집 수 — vector_regions), garbage_ratio, hidden_ratio(보이지 않는 글자 비율),
    hidden_over_image(보이지 않는 글자 상자 하나가 그림과 겹치는지)}]. PDF가 아니면 [].
    원본 파일 sha256로 한 번 계산해 _signals_path 캐시에 저장 — 다시 부르면 그 파일을 읽어 같은 쪽을 다시 안 연다."""
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return []
    cache = _signals_path(sha(p.read_bytes()))
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import fitz

    from pipeline.transform.represent.parse_scoring import garbage_ratio

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
                r = fitz.Rect(rects[0]) & page_rect  # 쪽 밖으로 나간 bbox는 쪽 안쪽만 셈
                if not r.is_empty:
                    img_area += r.width * r.height
                    img_rects.append(r)  # 숨은 글자 겹침 판정에 재사용
        # 여러 이미지가 겹치면 각자 면적의 합이 쪽 면적을 넘을 수 있어 1.0 상한(겹침 합집합의 근사)
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
    """글자 PDF 안의 스캔 쪽(쪽 번호 1부터) → 걸린 이유(쪽마다 하나, 먼저 맞는 것):
    'chars'  = 글자층 거의 없음(< PAGE_SCAN_CHARS) + 이미지 면적 큼(>= PAGE_SCAN_AREA)
    'hidden' = 숨은 글자층 비율 높음(>= PAGE_HIDDEN_RATIO) + 이미지 면적(>= PAGE_HIDDEN_AREA). 그림과 같은 내용의 양질 OCR
               글자층(검색 가능 스캔 PDF)도 걸리지만 일부러 후보에 넣는다 — 원래 글을 둘지는 대표 결과(doc_represent)가 정한다.
    'garbage' = 글자층 깨짐 비율 높음(>= PAGE_SCAN_GARBAGE) + 이미지 면적 큼(>= PAGE_SCAN_AREA)
    'hidden_overlap' = 숨은 글자 상자 하나가 그림과 겹침(hidden_over_image) — 쪽 VLM 후보로 넓히되, 쪽 VLM은 글자 상자가
               없어 국소 확인을 못 하므로 doc_represent.fill_scan_pages는 원래 글을 유지한다. 상한 PARSE_HIDDEN_OVERLAP_MAX(0=끔).
    'rotated' = filter_and_rotate가 돌린 쪽(rotation.csv angle≠0) — 회전이 글자층 신뢰도를 낮출 수 있다. 상한 PARSE_ROTATED_MAX(0=끔).
    'vectors' = 쪽 안 벡터 도식 군집 수가 PAGE_VECTORS_MIN 이상 — 글자층만으로 구조를 못 담는 쪽. 상한 PARSE_VECTORS_MAX(0=끔).
    문서 전체가 스캔(is_scan)이면 이 함수를 부르지 않는다."""
    cap = int(pc.by_env("PARSE_HIDDEN_OVERLAP_MAX"))
    vec_cap, rot_cap = (
        int(pc.by_env("PARSE_VECTORS_MAX")),
        int(pc.by_env("PARSE_ROTATED_MAX")),
    )
    rot = rotation_info(path) if rot_cap else {}  # rot_cap==0이면 rotation.csv를 안 읽음
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
    """글자 PDF 안의 스캔 쪽 번호 목록(scan_pages_detail의 쪽 번호만)."""
    return list(scan_pages_detail(path).keys())


def page_targets(doc_path):
    """이 문서에서 실제로 쪽 VLM이 호출될 쪽 번호 집합 — page_text_pages()와 figure_extract가 둘 다 이것만 본다
    (따로 추정하면 쪽 VLM이 안 도는 쪽의 그림까지 건너뛰어 내용을 잃는다). 빈 집합인 경우(먼저 맞는 것):
      - PARSE_POST에 'vlm_page'가 없음
      - VLM_PAGE_MAX=0
      - PDF도 아니고 문서 전체 스캔(is_scan)도 아님
      - 글자 PDF인데 스캔 신호 쪽이 없음
    그 밖: 문서 전체가 스캔이면 전체 쪽, 아니면 scan_pages() — VLM_PAGE_MAX로 자른 뒤 돌려준다(호출자가 또 자르지 않음)."""
    from pipeline.config import active_features

    if "vlm_page" not in active_features():
        return set()
    cap = page_max()
    if cap == 0:
        return set()
    p = Path(doc_path)
    if is_scan(p):
        return pick_pages(page_count(p), True, [], cap)
    if p.suffix.lower() != ".pdf":
        return set()
    # 글자 PDF 안의 스캔 쪽만(scan_pages_detail)
    return pick_pages(0, False, scan_pages(p), cap)


def pick_pages(n_pages, whole_scan, scan, cap):
    """쪽 VLM 대상 쪽(순수 함수) — 문서 전체가 스캔이면 1..n_pages 전부, 아니면 스캔 신호 쪽(scan)만 · cap(None = 제한 없음)으로
    앞에서 자른 집합. 글자 PDF 안의 스캔 쪽만 쪽 VLM을 부르고(병렬 — page_text_pages) 대표 결과가 그 쪽을 VLM 글로 채운다."""
    targets = list(range(1, n_pages + 1)) if whole_scan else list(scan)
    return set(targets if cap is None else targets[:cap])


LOOP_LINES_MAX = 50  # 같은 줄이 연달아 이보다 많으면 VLM 되풀이 고장(예: 빈 표 줄 수천 개)으로 본다 — 빈 서식 표(20~30줄)는 남게
# ponytail: 연속 같은 줄만 본다 — 두세 줄이 번갈아 되풀이되는 고장은 못 잡음(pl-62)


def _looped(text):
    """빈 줄을 빼고 같은 줄이 LOOP_LINES_MAX번 넘게 연달아 나오는지."""
    run, prev = 0, None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        run = run + 1 if s == prev else 1
        prev = s
        if run > LOOP_LINES_MAX:
            return True
    return False


def page_text_pages(doc_path):
    """page_targets() 쪽을 쪽 VLM으로 옮김 → [(쪽 번호, 글, provenance), ...](scan_fill이 그 쪽만 채우게 쪽 번호와 함께).
    되풀이 고장(_looped) 쪽은 글을 비운다 — 빈 글은 scan_fill·apply_post 둘 다 안 쓰므로 원래 글자층이 남는다."""
    return [
        (i, "", {**pv, "looped": True}) if _looped(t or "") else (i, t, pv) for i, t, pv in transcribe(doc_path, page_targets(doc_path))
    ]
