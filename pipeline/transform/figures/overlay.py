"""F12(사용자 10-14) — 그림 위에 다른 그림·글상자·도형·화살표가 겹치면(겹침 또는 포함) 한 묶음으로 찾는다.
이 모듈은 좌표만 다룬다(순수 함수 — 테스트하기 쉽게): 실제 렌더(soffice·fitz clip)·크롭·VLM 호출·레코드 조립은
호출부(parse/postprocess/figures.py) 몫. cluster_overlaps()가 핵심(연결 요소, Union-Find) — 그림(kind="picture")
1개 이상 + 그 외(kind="other", 글상자·도형·화살표) 1개 이상을 포함하는 묶음만 돌려준다(그림끼리만 겹치거나
글상자끼리만 겹치는 건 이 기능 대상이 아님). 독립 검토(10-14) — 전면 배경 사진·워터마크처럼 쪽 넓이의
OVERLAY_BG_AREA_RATIO(40%, 사용자 결정 10-14)를 넘는 개체는 호출부가 page_area를 주면 묶음 후보에서 아예
빠진다(과다 결합 가드 — 안 빼면 쪽의 모든 개체가 그 배경을 통해 한 거대 묶음으로 뭉친다). 겹침 판정 자체는
여유(tolerance) 없이 엄격한 겹침·포함만(사용자 결정 10-14 — 안 닿은 근처 콜아웃은 F10 near 목록 몫, 이 모듈
대상 아님).

형식별 좌표 추출:
  - pdf_page_objects(pg, pic_objs) — fitz Page, 그림은 호출부가 이미 찾은 rect를 그대로 받고 글자 블록(get_text
    "blocks")·그리기(get_drawings, 쪽의 OVERLAY_BG_AREA_RATIO 넘는 배경 도형은 뺌)를 'other'로 더한다.
  - pptx_slide_objects(s, pic_shapes, pic_ids) — python-pptx Slide, 그림은 호출부가 이미 찾은 shape·id 순서쌍을
    그대로 받고 글자 있는 도형·연결선(cxnSp)을 'other'로 더한다(EMU 절대좌표 — 슬라이드 안에서 그대로 비교 가능).
  - docx_float_objects(doc_path) — word/document.xml을 직접 읽어 플로팅(wp:anchor) 그림·글상자의 EMU bbox.
    ponytail: relativeFrom="page"만 가정(margin·column 상대는 다음 버전) — 틀리면 그 좌표가 섞여 묶음을 못 찾을
    뿐(거짓 양성 없음, 좌표 자체가 이상해 보이면 clusters가 그냥 비게 된다).
  - xlsx(시트 도형)는 이번 버전 범위 밖(YAGNI) — openpyxl이 textbox shape의 신뢰할 bbox를 안 줌, 타겟 세트에도
    xlsx 겹침 샘플이 없음. 실 사례가 나오면 drawing XML(xdr:sp) 직접 파싱으로 docx_float_objects와 같은 자리에 추가."""


def _overlaps(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


OVERLAY_BG_AREA_RATIO = 0.4  # 사용자 결정(10-14) — 쪽/슬라이드 면적의 이 비율을 넘는 낱개(전면 배경 사진·
# 워터마크 등)는 묶음 후보에서 아예 뺀다 — pdf_page_objects의 그리기 배경 제외(옛 0.3)와 이 새 과다 결합 가드를
# 한 상수로 통일(단일 진입점, 집행: 이 모듈). 그런 개체는 쪽 위 사실상 전부와 bbox가 겹치므로, 빼지 않으면
# 그걸 통해 쪽의 모든 개체(그림·글상자 가리지 않고)가 한 거대 묶음으로 뭉친다(실측: 전면 배경 그림 1장 + 서로
# 안 겹치는 그림·글상자 여러 개 → 배경이 전부를 하나로 이어버림). 그림(kind="picture")에도 적용 — 배경 자체가
# 그림이라 이전엔 벡터 도형 쪽만 보던 옛 규칙이 안 걸렸다.


def cluster_overlaps(objs, page_area=None, max_area_ratio=OVERLAY_BG_AREA_RATIO):
    """objs: [{"id","kind"("picture"|"other"),"bbox":(x0,y0,x1,y1)[,"text"]}] → 묶음(겹침·포함 연결 요소,
    그림 1개 이상 + 그 외 1개 이상인 것만) [{"members":[id,...],"picture_ids":[...],"other_ids":[...],
    "texts":[...],"bbox":(x0,y0,x1,y1)}], members 기준 id 오름차순 정렬(결정적). 겹침 판정은 여유(tolerance)
    없이 엄격(경계가 실제로 겹치거나 한쪽이 다른 쪽을 포함할 때만 — 사용자 결정 10-14, _overlaps() 참고).
    page_area(쪽/슬라이드 전체 넓이, bbox와 같은 단위) — 주면 넓이가 max_area_ratio(기본 OVERLAY_BG_AREA_RATIO=
    0.4)를 넘는 객체는 처음부터 묶음 후보에서 뺀다(위 상수 설명 — 과다 결합 가드). 안 주면(None) 필터 없음
    (좌표 단위를 모르는 순수 좌표 시험 등)."""
    if page_area:
        objs = [o for o in objs if (o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]) <= max_area_ratio * page_area]
    n = len(objs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _overlaps(objs[i]["bbox"], objs[j]["bbox"]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    out = []
    for idxs in groups.values():
        pics = sorted((i for i in idxs if objs[i]["kind"] == "picture"), key=lambda i: objs[i]["id"])
        others = sorted((i for i in idxs if objs[i]["kind"] != "picture"), key=lambda i: objs[i]["id"])
        if not pics or not others:
            continue
        xs0 = min(objs[i]["bbox"][0] for i in idxs)
        ys0 = min(objs[i]["bbox"][1] for i in idxs)
        xs1 = max(objs[i]["bbox"][2] for i in idxs)
        ys1 = max(objs[i]["bbox"][3] for i in idxs)
        members = sorted(objs[i]["id"] for i in idxs)
        out.append(
            {
                "members": members,
                "picture_ids": [objs[i]["id"] for i in pics],
                "other_ids": [objs[i]["id"] for i in others],
                "texts": [objs[i]["text"] for i in others if objs[i].get("text")],
                "bbox": (xs0, ys0, xs1, ys1),
            }
        )
    out.sort(key=lambda c: c["members"][0])
    return out


def pdf_page_objects(pg, pic_objs):
    """pic_objs: [{"id","rect"}](rect — 4개 숫자로 반복 가능, fitz.Rect째로 줘도 됨) → cluster_overlaps() 입력."""
    objs = [{"id": o["id"], "kind": "picture", "bbox": tuple(o["rect"])} for o in pic_objs]
    page_area = pg.rect.width * pg.rect.height
    oid = 0
    for b in pg.get_text("blocks"):
        if not (b[4] or "").strip():
            continue
        oid += 1
        objs.append({"id": f"_text{oid}", "kind": "other", "bbox": tuple(b[:4]), "text": b[4].strip()})
    for d in pg.get_drawings():
        r = d["rect"]
        if r.is_empty or (page_area and r.width * r.height > OVERLAY_BG_AREA_RATIO * page_area):
            continue  # 쪽 전체급 배경 도형은 겹침 판정에서 뺌(모든 그림과 항상 '겹침'이 되어 의미가 없음) — cluster_overlaps와 같은 상수
        oid += 1
        objs.append({"id": f"_draw{oid}", "kind": "other", "bbox": tuple(r)})
    return objs


def pptx_slide_objects(s, pic_shapes, pic_ids):
    """pic_shapes — figures()가 이미 고른 picture shape 목록(shape_type==13), pic_ids — 같은 순서의 image_id.
    글상자(has_text_frame + 글자 있음)·연결선(cxnSp, 화살표 포함)을 'other'로 더한다."""
    objs = [
        {"id": pic_ids[i], "kind": "picture", "bbox": (sh.left, sh.top, sh.left + sh.width, sh.top + sh.height)}
        for i, sh in enumerate(pic_shapes)
    ]
    oid = 0
    for sh in s.shapes:
        if sh.shape_type == 13 or sh.is_placeholder:  # 그림 자신 · 제목/본문 placeholder(레이아웃 요소, 콜아웃 아님 — 실측
            continue  # synth-visual/log_axis.pptx: 제목이 그림과 1px 미만 겹쳐 오탐했던 사례)
        has_text = bool(sh.has_text_frame and sh.text_frame.text.strip())
        is_conn = sh._element.tag.endswith("}cxnSp")
        if not (has_text or is_conn):
            continue
        try:
            l, t, w, h = sh.left, sh.top, sh.width, sh.height  # noqa: E741 — 좌·위·폭·높이(pptx 도형 좌표 관례)
        except Exception:  # 위치 정보 없는 도형(그룹 내부 등) 1건이 전체를 막지 않게
            continue
        if None in (l, t, w, h):
            continue
        oid += 1
        objs.append(
            {"id": f"_shape{oid}", "kind": "other", "bbox": (l, t, l + w, t + h), "text": sh.text_frame.text.strip() if has_text else None}
        )
    return objs


_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_float_objects(doc_path):
    """word/document.xml의 wp:anchor(플로팅 그림·글상자)만 — wp:inline(흐름 속 그림, 절대좌표 없음)은 대상 밖.
    반환: (pos_by_rid: {그림 관계id → EMU bbox}, text_boxes: [{"bbox","text"}]) — figures()가 이미 매긴
    image_id·관계id(rId)로 둘을 잇는다(이 함수는 새 번호를 안 매김)."""
    import zipfile

    from lxml import etree

    with zipfile.ZipFile(doc_path) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)
    pos_by_rid, text_boxes = {}, []
    for anchor in root.iter(f"{_WP}anchor"):
        ph = anchor.find(f"{_WP}positionH/{_WP}posOffset")
        pv = anchor.find(f"{_WP}positionV/{_WP}posOffset")
        ext = anchor.find(f"{_WP}extent")
        if ph is None or pv is None or ext is None or not ph.text or not pv.text:
            continue
        x0, y0 = int(ph.text), int(pv.text)
        w, h = int(ext.get("cx")), int(ext.get("cy"))
        bbox = (x0, y0, x0 + w, y0 + h)
        blip = anchor.find(f".//{_A}blip")
        if blip is not None:
            rid = blip.get(f"{_R}embed")
            if rid:
                pos_by_rid[rid] = bbox
            continue
        texts = [t.text for t in anchor.iter(f"{_W}t") if t.text]
        if texts:
            text_boxes.append({"bbox": bbox, "text": "".join(texts).strip()})
    return pos_by_rid, text_boxes
