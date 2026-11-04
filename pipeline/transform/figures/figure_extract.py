"""W1·W9 — 내장 그림을 형식과 무관하게 모두 찾아 VLM 기록(+ 위치·근처 글자). 원본: eval_hard_parse.figures()·vlm_raw().
PDF 래스터·벡터 군집(post.vector)·docx(본문·표 칸)·xlsx(모든 시트·셀 위)·pptx·eml 본문 이미지(cid) → 그림 1개 = 기록 1개.
VLM은 pipeline.shared.vlmcall.ask(내부망 가드·추론 끄기는 common.models.vlm.extra_body)·P0 원본 층 캐시(pipeline.shared.parse_run.raw_vlm_path, PARSE_RAW_ROOT로 저장소 바꿀 수 있음).
산출: output/parse/_images/index.jsonl(설계 git 이력 docs/plans/image-parsing-2026-10-01.md(c4874dd0^) §3 계약 + W11 필드) + <doc>/<image_id>.png."""

import email
import html
import io
import json
import re
import time
import uuid
from email import policy
from pathlib import Path

from common.ai import llm as A  # 모델 호출(0.2.0 — 옛 common.ai.adk, pl-46)
from common.ai.agent_prompts import load as _load_prompt
from common.config.settings import cfg as ccfg  # common 칸 설정 객체(S7c)
from common.core import span as SP  # op-01 성능 span(풀 스레드 컨텍스트 전달·OCR 지표)
from common.core.paths import (
    APP_ROOT,  # 폴더 재편 뒤 이 상수만 바뀌면 됨
)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared import vlmcall as V  # VLM 호출 한 길(ask)·렌더 해상도(dpi) — 11-04
from pipeline.shared.ext_groups import IMG_EXTS
from pipeline.shared.parse_run import prompt_id, raw_vlm_path
from pipeline.shared.post_config import raw_root  # PARSE_RAW_ROOT(이중 raw/ 방지, post/__init__.py)
from pipeline.shared.vlmcall import sha
from pipeline.transform.figures import chart_values as CV  # F14(a)·(c) 벡터 차트 결정적 값·추세
from pipeline.transform.figures import diagram_edges as diag_edges  # F13, PDF 벡터·텍스트 글자 화살표 결정적 edges
from pipeline.transform.figures.nested_figures import find_children  # F7, page_render 안의 자식 그림 찾기·자르기
from pipeline.transform.figures.overlay_groups import (  # F12 — 겹친 개체(그림+글상자/도형/화살표) 한 묶음 찾기
    cluster_overlaps,
    docx_float_objects,
    pdf_page_objects,
    pptx_slide_objects,
)
from pipeline.transform.figures.pptx_edges import PPTX_SHAPES_MIN, picture_arrow_edges, pptx_edges
from pipeline.transform.figures.vector_regions import vector_regions
from pipeline.transform.represent import figure_context as C

NOW = time.strftime("%Y-%m-%dT%H:%M:%S")


def _qlabel(s):
    return '"' + str(s).replace('"', "'").replace("\n", " ") + '"'


def to_mermaid(edges):
    """edges[{from,to,label}] → "flowchart LR" 글자. edges 없거나 from·to 없는 것뿐이면 빈 문자열."""
    if not edges:
        return ""
    ids, lines = {}, []

    def nid(name):
        if name not in ids:
            ids[name] = f"n{len(ids)}"
        return ids[name]

    for e in edges:
        frm, to = e.get("from"), e.get("to")
        if not frm or not to:
            continue
        a, b = nid(frm), nid(to)
        label = e.get("label")
        arrow = f"-->|{_qlabel(label)}|" if label else "-->"
        lines.append(f"    {a}[{_qlabel(frm)}] {arrow} {b}[{_qlabel(to)}]")
    return "flowchart LR\n" + "\n".join(lines) if lines else ""


def _lines(s):
    return [x.strip() for x in re.split(r"\n+", s or "") if x.strip()]


def _pptx_shape_figure(doc_path, pr, si, title, texts):
    """F7 — 그림(picture shape)이 전혀 없이 네이티브 도형(상자·화살표·연결선)으로만 그린 슬라이드는 지금까지
    그림 기록이 0건이었다(qc_workflow.pptx 2쪽류 — 첨부 요청 문항 IQ046이 get_image를 못 찾던 원인). 도형
    수가 PPTX_SHAPES_MIN(AD20 candidate_slides와 같은 문턱) 이상이면 슬라이드 전체를 렌더해 그림 1건으로
    기록한다 — **중첩이 아니다**(depth 0): 이 슬라이드의 유일한 그림이라 평범한 picture와 같은 `#i<n>` 번호를
    그대로 쓴다(이 슬라이드엔 pics가 이미 없어 번호 충돌 없음). soffice 없음·변환 실패면 조용히 빈 목록
    (LibreOffice 없이도 그 밖 파싱은 그대로 — image-patch-process.md 관례와 같음)."""
    from pipeline.transform.figures.pptx_render import render_slides

    rendered = render_slides(doc_path, [si])
    png = rendered.get(si)
    if png is None:
        return []
    name = Path(doc_path).name
    return [
        {
            "image_id": f"{name}#p{si}#i1",
            "loc": {"slide": si, "page_vlm": False, "rendered": True},
            "bbox": [0, 0, pr.slide_width, pr.slide_height],
            "bytes": png,
            "before": [],
            "after": ([f"슬라이드 제목: {title}"] if title else []) + [t for t in texts if t != title],
            "near": [],
            "area_ratio": 1.0,
        }
    ]


def _office_shape_figures(doc_path):
    """AD14 — Word·Excel 도형 도식(텍스트 상자·연결선·SmartArt, 삽입 이미지 없음)을 pptx 쪽 렌더(F7
    _pptx_shape_figure)와 같은 방식으로 통째 렌더해 그림 1건씩 기록한다(쪽 전체 = 그림, depth 0 — page_render
    관례와 같은 image_id `<doc>#p<쪽>#page`, soffice가 만든 PDF 쪽 번호 그대로라 docx 쪽 번호·xlsx 시트 번호와
    꼭 같지 않을 수 있음 — ponytail: 백로그가 허용한 근사, 정확한 시트 매핑이 필요해지면 xl/worksheets 관계로
    승급). cheap 문턱(shape_detect)·soffice 없음·변환 실패는 모두
    shape_render_pages()가 조용히 빈 묶음으로 처리(바이트 영향 0, pptx와 같은 관례)."""
    from pipeline.transform.figures.pptx_render import shape_render_pages

    name = Path(doc_path).name
    out = []
    for page, png in sorted(shape_render_pages(doc_path).items()):
        out.append(
            {
                "image_id": f"{name}#p{page}#page",
                "loc": {"page": page, "page_vlm": False, "page_render": True, "shape_render": True},
                "bbox": None,
                "bytes": png,
                "before": [],
                "after": [],
                "near": [],
                "area_ratio": 1.0,
            }
        )
    return out


def _nested_children(parent_id, parent_bytes, page, dims):
    """F7 — 부모(page_render) 안의 자식 그림을 nested.find_children()으로 찾아 figures() 모양의 dict 목록으로.
    find_children의 0~1 비율 bbox를 dims(원본 쪽의 실제 단위 — PDF는 점, PNG는 px)로 곱해 '원본 쪽 좌표'로
    바꾼다(설계 §3 — "항상 원본 쪽 좌표로 환산"). build_records가 loc.parent_image_id·depth를 읽어 기록 필드를
    채우고, 이 함수가 돌려준 그림은 일반 그림과 똑같이 select_figures→vlm_fig를 거친다(내용·값 추출, 중복 방지
    불필요 — page_vlm 표시가 없는 '새' 그림이라 build_records의 기존 skip 로직과 안 겹침)."""
    w, h = dims
    out = []
    for child in find_children(parent_bytes):
        parent_local = child["parent_local"]
        pid = f"{parent_id}.{parent_local}" if parent_local else parent_id
        cid = f"{parent_id}.{child['local_id']}"
        x0, y0, x1, y1 = child["bbox_frac"]
        bbox = [round(x0 * w, 1), round(y0 * h, 1), round(x1 * w, 1), round(y1 * h, 1)]
        out.append(
            {
                "image_id": cid,
                "loc": {"page": page, "parent_image_id": pid, "depth": child["depth"], "kind_hint": child["kind"]},
                "bbox": bbox,
                "bytes": child["bytes"],
                "before": [],
                "after": [],
                "near": [],
            }
        )
    return out


# ── F12 — 겹친 개체(그림+글상자/도형/화살표) 한 묶음 렌더 ───────────────────
def _pdf_overlay_records(name, pi, pg, pic_objs, page_vlm):
    """pic_objs: [{"id","rect"(fitz.Rect),"rec"(이 쪽 out 안의 그 그림 dict)}] → 겹친 묶음 figure dict 목록
    (clip pixmap으로 union bbox를 한 번에 자름, 원본 좌표계 그대로라 페이지/쪽 대응 문제가 없음)."""
    import fitz

    page_area = pg.rect.width * pg.rect.height  # F12 독립 검토(10-14) — 전면 배경·워터마크 과다 결합 가드(overlay.OVERLAY_BG_AREA_RATIO)
    clusters = cluster_overlaps(pdf_page_objects(pg, [{"id": o["id"], "rect": o["rect"]} for o in pic_objs]), page_area=page_area)
    if not clusters:
        return []
    rec_by_id = {o["id"]: o["rec"] for o in pic_objs}
    out = []
    for ci, cl in enumerate(clusters, 1):
        x0, y0, x1, y1 = cl["bbox"]
        clip = (fitz.Rect(x0, y0, x1, y1) + (-4, -4, 4, 4)) & pg.rect
        crop_bytes = pg.get_pixmap(dpi=V.dpi(), clip=clip).tobytes("png")
        cluster_id = f"{name}#p{pi}#overlay{ci}"
        texts = [t for t in cl["texts"] if t]
        out.append(
            {
                "image_id": cluster_id,
                "loc": {"page": pi, "page_vlm": page_vlm},
                "bbox": [round(v, 1) for v in clip],
                "bytes": crop_bytes,
                "before": [],
                "after": [],
                "near": texts,
                "overlay": {"members": cl["members"], "texts": texts},
            }
        )
        for pid_ in cl["picture_ids"]:
            if pid_ in rec_by_id:
                rec_by_id[pid_]["loc"]["cluster_id"] = cluster_id
    return out


def _pptx_overlay_records(name, doc_path, si, pr, s, pic_shapes, pic_recs, page_vlm):
    """pic_recs — pic_shapes와 같은 순서의 이 슬라이드 out 안 그림 dict. render_slides(soffice)로 슬라이드
    전체를 한 번 렌더해 EMU→px 비율로 union bbox만 자른다(쪽마다 변환 1번, F7 render_slides와 같은 재사용)."""
    pic_ids = [r["image_id"] for r in pic_recs]
    slide_area = pr.slide_width * pr.slide_height  # F12 독립 검토(10-14) — 전면 배경 그림 과다 결합 가드
    clusters = cluster_overlaps(pptx_slide_objects(s, pic_shapes, pic_ids), page_area=slide_area)
    if not clusters:
        return []
    from pipeline.transform.figures.pptx_render import render_slides

    rendered = render_slides(doc_path, [si])
    png = rendered.get(si)
    if png is None:  # soffice 없음·변환 실패 — 조용히 건너뜀(그림마다 따로 기록하던 이전 동작 그대로)
        return []
    from PIL import Image

    im = Image.open(io.BytesIO(png))
    rec_by_id = dict(zip(pic_ids, pic_recs))
    out = []
    for ci, cl in enumerate(clusters, 1):
        x0, y0, x1, y1 = cl["bbox"]
        px0 = max(0, int(x0 / pr.slide_width * im.width))
        py0 = max(0, int(y0 / pr.slide_height * im.height))
        px1 = min(im.width, int(x1 / pr.slide_width * im.width) + 1)
        py1 = min(im.height, int(y1 / pr.slide_height * im.height) + 1)
        buf = io.BytesIO()
        im.crop((px0, py0, px1, py1)).save(buf, "PNG")
        cluster_id = f"{name}#p{si}#overlay{ci}"
        texts = [t for t in cl["texts"] if t]
        out.append(
            {
                "image_id": cluster_id,
                "loc": {"slide": si, "page_vlm": page_vlm},
                "bbox": [round(v, 1) for v in cl["bbox"]],
                "bytes": buf.getvalue(),
                "before": [],
                "after": [],
                "near": texts,
                "overlay": {"members": cl["members"], "texts": texts},
            }
        )
        for pid_ in cl["picture_ids"]:
            if pid_ in rec_by_id:
                rec_by_id[pid_]["loc"]["cluster_id"] = cluster_id
    return out


def _docx_overlay_records(name, doc_path, doc, pic_objs, text_boxes):
    """pic_objs: [{"id","bbox"(EMU),"rec"}] · text_boxes: docx_float_objects()의 두 번째 값. ponytail: 쪽 1만
    가정(docx 플로팅 앵커는 쪽 번호를 안 담고 있어 soffice 레이아웃이 실제로 몇 쪽에 놓을지 모름 — 다쪽 문서에서
    묶음이 1쪽 밖에 있으면 못 찾을 뿐, 거짓 양성은 없음) — 실 사례가 쌓이면 렌더된 각 쪽에서 그림 crop을 원본과
    대조(해시·크기)해 쪽을 추정하는 식으로 올릴 자리."""
    sect = doc.sections[0]
    page_w, page_h = sect.page_width, sect.page_height
    if not page_w or not page_h:
        return []
    objs = [{"id": o["id"], "kind": "picture", "bbox": o["bbox"]} for o in pic_objs]
    objs += [{"id": f"_tb{j}", "kind": "other", "bbox": tb["bbox"], "text": tb["text"]} for j, tb in enumerate(text_boxes)]
    clusters = cluster_overlaps(objs, page_area=page_w * page_h)  # F12 독립 검토(10-14) — 전면 배경 그림 과다 결합 가드
    if not clusters:
        return []
    from pipeline.transform.figures.pptx_render import render_office_pages

    rendered = render_office_pages(doc_path, [1])
    png = rendered.get(1)
    if png is None:
        return []
    from PIL import Image

    im = Image.open(io.BytesIO(png))
    rec_by_id = {o["id"]: o["rec"] for o in pic_objs}
    out = []
    for ci, cl in enumerate(clusters, 1):
        x0, y0, x1, y1 = cl["bbox"]
        px0 = max(0, int(x0 / page_w * im.width))
        py0 = max(0, int(y0 / page_h * im.height))
        px1 = min(im.width, int(x1 / page_w * im.width) + 1)
        py1 = min(im.height, int(y1 / page_h * im.height) + 1)
        buf = io.BytesIO()
        im.crop((px0, py0, px1, py1)).save(buf, "PNG")
        cluster_id = f"{name}#p0#overlay{ci}"
        texts = [t for t in cl["texts"] if t]
        out.append(
            {
                "image_id": cluster_id,
                "loc": {"order": -1},
                "bbox": [round(v, 1) for v in cl["bbox"]],
                "bytes": buf.getvalue(),
                "before": [],
                "after": [],
                "near": texts,
                "overlay": {"members": cl["members"], "texts": texts},
            }
        )
        for pid_ in cl["picture_ids"]:
            if pid_ in rec_by_id:
                rec_by_id[pid_]["loc"]["cluster_id"] = cluster_id
    return out


# ── 그림 찾기(형식별) ────────────────────────────────────────────────────
def figures(p, page_covered=False):
    """[{image_id, loc, bbox, bytes, before[], after[], near[], text_layer?}] — 근처 글자는 캡션·본문 언급 후보(W11가 씀)."""
    p = Path(p)
    ext, name, out = p.suffix.lower(), p.name, []
    if ext == ".pdf":
        import fitz

        d = fitz.open(p)
        from pipeline.transform.figures.scan_page_vlm import page_targets  # 독립 검토 반영(10-11, AD31/AD20 BLOCK) — scan_pages()만 보던

        # 10-29 C — page_covered(이미지·스캔 문서를 VLM 엔진이 이미 쪽마다 옮김)면 모든 쪽을 '옮긴 쪽'으로(쪽 전체 그림 VLM 생략)
        skip_pages = (
            set(range(1, len(d) + 1)) if page_covered else page_targets(p)
        )  # 자리를 page_targets()로: VLM_PAGE_MAX==0·cap 절단·PARSE_POST에
        # vlm_page 없음까지 접은 "실제로 쪽 VLM이 불릴 쪽"을 안다 — BR56: 그 쪽도 그림 기록 자체는 남긴다(get_image가
        # 찾을 수 있게), loc["page_vlm"]=True만 남겨 build_records가 그 그림의 VLM만 생략(쪽 VLM과 중복 호출 방지,
        # 기록을 통째로 지우던 옛 동작이 버그 — AD31/AD20은 "VLM 재호출 금지"였지 "기록 금지"가 아니었다).
        if all(len(pg.get_text().strip()) < 20 for pg in d):  # 스캔·이미지 PDF — 쪽 전체를 page_render 부모로 기록(F7, 중첩)
            for pi, pg in enumerate(d, 1):  # + VLM이 실제로 불릴 쪽(skip_pages — page_targets 재사용, 상한
                page_bytes = pg.get_pixmap(dpi=V.dpi()).tobytes("png")  # 그대로)만 안의 자식 그림도 찾는다(VLM 미설정·꺼짐이면 부모만)
                parent_id = f"{name}#p{pi}#page"
                out.append(
                    {
                        "image_id": parent_id,
                        "loc": {"page": pi, "page_vlm": pi in skip_pages, "page_render": True},
                        "bbox": [0, 0, round(pg.rect.width, 1), round(pg.rect.height, 1)],
                        "bytes": page_bytes,
                        "before": [],
                        "after": [],
                        "near": [],
                    }
                )
                if pi in skip_pages:
                    out.extend(_nested_children(parent_id, page_bytes, pi, (pg.rect.width, pg.rect.height)))
            return out
        for pi, pg in enumerate(d, 1):
            page_vlm = pi in skip_pages
            blocks = [(b[1], b[3], b[4]) for b in pg.get_text("blocks") if b[4].strip()]
            page_area = pg.rect.width * pg.rect.height  # AD9 — bbox 면적 ÷ 쪽 면적(선별용, area_ratio)
            page_pics = []  # F12 — 이 쪽 그림 dict 참조(겹침 묶음이 loc.cluster_id를 직접 씀)
            for n, x in enumerate(pg.get_images(full=True), 1):
                rects = pg.get_image_rects(x[0])
                r = rects[0] if rects else fitz.Rect(0, 0, 0, 0)
                above = sorted([b for b in blocks if b[1] <= r.y0 + 2], key=lambda b: r.y0 - b[1])[:2]
                below = sorted([b for b in blocks if b[0] >= r.y1 - 2], key=lambda b: b[0] - r.y1)[:2]
                pic_rec = {
                    "image_id": f"{name}#p{pi}#i{n}",
                    "loc": {"page": pi, "page_vlm": page_vlm},
                    "bbox": [round(v, 1) for v in r],
                    "bytes": d.extract_image(x[0])["image"],
                    "before": [b[2].strip() for b in above],
                    "after": [b[2].strip() for b in below],
                    "near": [],
                    "area_ratio": (r.width * r.height) / page_area if page_area else None,
                }
                out.append(pic_rec)
                page_pics.append({"id": pic_rec["image_id"], "rect": r, "rec": pic_rec})
            rasters = [fitz.Rect(o["bbox"]) for o in out if o["loc"].get("page") == pi]
            for k, vr in enumerate([v for v in vector_regions(pg) if not any(fitz.Rect(v["bbox"]).intersects(rr) for rr in rasters)], 1):
                r = fitz.Rect(vr["bbox"])  # 벡터 도식 영역 캡처(스냅샷) — 쪽 전체 VLM 대신 이 영역만(W12)
                above = sorted([b for b in blocks if b[1] <= r.y0 + 2], key=lambda b: r.y0 - b[1])[:2]
                below = sorted([b for b in blocks if b[0] >= r.y1 - 2], key=lambda b: b[0] - r.y1)[:2]
                out.append(
                    {
                        "image_id": f"{name}#p{pi}#v{k}",
                        "loc": {"page": pi, "origin": "vector", "signals": vr["signals"], "page_vlm": page_vlm},
                        "bbox": vr["bbox"],
                        "bytes": pg.get_pixmap(dpi=V.dpi(), clip=r).tobytes("png"),
                        "before": [b[2].strip() for b in above],
                        "after": [b[2].strip() for b in below],
                        "near": [],
                        "text_layer": vr["text_layer"],
                        "area_ratio": (r.width * r.height) / page_area if page_area else None,
                    }
                )
            if page_pics:  # F12 — 그림 위에 글자/도형이 겹치면 한 묶음으로
                out.extend(_pdf_overlay_records(name, pi, pg, page_pics, page_vlm))
    elif ext == ".docx":
        import docx as _docx

        doc = _docx.Document(p)
        rels = {
            k: v.target_part.blob for k, v in doc.part.rels.items() if "image" in v.reltype and not v.is_external
        }  # 2026-10-23 — 외부 링크 이미지(External rel)는 target_part가 없어 죽지 않게 건너뜀
        body = doc.element.body
        seq = []  # 문서 순서대로 (글자 | 그림)
        for el in body.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                txt = "".join(t.text or "" for t in el.iter() if t.tag.endswith("}t"))
                emb = [
                    b.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    for b in el.iter()
                    if b.tag.endswith("}blip")
                ]
                row = next((a for a in el.iterancestors() if a.tag.endswith("}tr")), None)
                rowtxt = (
                    []
                    if row is None
                    else ["".join(t.text or "" for t in c.iter() if t.tag.endswith("}t")) for c in row if c.tag.endswith("}tc")]
                )
                if txt.strip():
                    seq.append(("t", txt.strip()))
                for e in emb:
                    if e in rels:
                        seq.append(
                            ("i", rels[e], [x for x in rowtxt if x.strip()], e)
                        )  # F12 — 4번째(e, 관계id)로 겹침 묶음이 플로팅 anchor 좌표(rId)와 이음
        pos_by_rid, text_boxes = docx_float_objects(p)  # F12 — 본문 순회 전에 한 번만(비용 적음)
        n, pic_objs = 0, []
        for k, it in enumerate(seq):
            if it[0] != "i":
                continue
            n += 1
            before = [x[1] for x in reversed(seq[:k]) if x[0] == "t"][:2]
            after = [x[1] for x in seq[k + 1 :] if x[0] == "t"][:2]
            rec = {
                "image_id": f"{name}#p0#i{n}",
                "loc": {"order": k},
                "bbox": None,
                "bytes": it[1],
                "before": before,
                "after": after,
                "near": it[2],
            }
            out.append(rec)
            if it[3] in pos_by_rid:
                pic_objs.append({"id": rec["image_id"], "bbox": pos_by_rid[it[3]], "rec": rec})
        if n == 0:  # AD14 — 삽입 그림이 전혀 없는 문서만(그림이 있으면 도형은 그 그림의 캡션·장식일 수 있어 보수적으로 거름)
            out.extend(_office_shape_figures(p))
        elif pic_objs and text_boxes:  # F12 — 플로팅 그림 위에 겹친 플로팅 글상자가 있을 때만(둘 다 있어야 묶음 후보)
            out.extend(_docx_overlay_records(name, p, doc, pic_objs, text_boxes))
    elif ext == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(p)
        for ws in wb.worksheets:
            for n, im in enumerate(ws._images, 1):
                a = im.anchor._from
                row, col = a.row + 1, a.col + 1
                near = [
                    str(c.value) for r_ in ws.iter_rows(min_row=max(1, row - 3), max_row=row + 4, max_col=col + 6) for c in r_ if c.value
                ]
                head = [
                    str(c.value) for r_ in ws.iter_rows(min_row=1, max_row=2) for c in r_ if c.value
                ]  # 시트 첫 줄 제목 — 그림이 멀리 있어도 캡션 후보
                out.append(
                    {
                        "image_id": f"{name}#s{ws.title}#i{n}",
                        "loc": {"sheet": ws.title, "cell": f"{a.col}:{row}"},
                        "bbox": None,
                        "bytes": im._data(),
                        "before": [],
                        "after": [],
                        "near": near + [f"시트 제목: {h}" for h in head if h not in near] + [f"시트 {ws.title}"],
                    }
                )
        out.extend(_office_shape_figures(p))  # AD14 — 삽입 그림 없이 도형(텍스트 상자·연결선·SmartArt)으로만 그린 시트
    elif ext == ".pptx":
        from pptx import Presentation

        from pipeline.transform.figures.pptx_render import (
            target_slides,
        )  # AD20 후속 — 쪽 VLM이 이미 다루는 슬라이드는 그 슬라이드 그림의 VLM만 생략(BR56: 기록은 유지)

        skip_slides = target_slides(p)
        pr = Presentation(p)
        slide_area = pr.slide_width * pr.slide_height  # AD9 — bbox 면적 ÷ 슬라이드 면적(선별용, area_ratio)
        for si, s in enumerate(pr.slides, 1):
            page_vlm = si in skip_slides
            texts = [sh.text_frame.text.strip() for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            title = s.shapes.title.text_frame.text.strip() if s.shapes.title is not None else ""
            pics = [sh for sh in s.shapes if sh.shape_type == 13]
            arrow_edges = picture_arrow_edges(s) if pics else []  # F10 — 그림 위에 겹친 화살표가 가리키는 점(콜아웃 글자 + 상대 위치)
            pic_recs = []  # F12 — 이 슬라이드 그림 dict 참조(겹침 묶음이 loc.cluster_id를 직접 씀)
            for n, sh in enumerate(pics, 1):
                anns = [{"text": e["from"], "point": e["point"], "kind": e["kind"]} for e in arrow_edges if e["to"] == f"image#{n}"]
                near = ([f"슬라이드 제목: {title}"] if title else []) + [t for t in texts if t != title]
                if anns:  # F10 — 화살표 겹침이 있을 때만 "callout: ..." 글자 추가(없으면 기록이 이전과 바이트 동일)
                    near = near + [
                        f"callout: {a['text']} → ({a['point'][0] * 100:.0f}%, {a['point'][1] * 100:.0f}%)" for a in anns if a["text"]
                    ]
                rec = {
                    "image_id": f"{name}#p{si}#i{n}",
                    "loc": {"slide": si, "page_vlm": page_vlm},
                    "bbox": [sh.left, sh.top, sh.width, sh.height],
                    "bytes": sh.image.blob,
                    "before": [],
                    "after": [],
                    "near": near,
                    "area_ratio": (sh.width * sh.height) / slide_area if slide_area else None,
                }
                if anns:
                    rec["annotations"] = anns
                out.append(rec)
                pic_recs.append(rec)
            if not pics and len(list(s.shapes)) >= PPTX_SHAPES_MIN:  # F7 — 삽입 그림 없이 네이티브 도형으로만 그린 슬라이드
                out.extend(_pptx_shape_figure(p, pr, si, title, texts))  # (qc_workflow.pptx 2쪽류, IQ046) — 쪽 렌더를 그림 1건으로
            if pics:  # F12 — 그림 위에 글상자/연결선(화살표)이 겹치면 한 묶음으로
                out.extend(_pptx_overlay_records(name, p, si, pr, s, pics, pic_recs, page_vlm))
    # BR56 — 단독 이미지 문서 자체(위 분기들과 달리 지금까지 아무 분기도 없어 기록이 0건이었음, AD31/AD20과 무관한 기존 공백)
    elif ext in IMG_EXTS:
        from pipeline.transform.figures.scan_page_vlm import (
            page_targets,
        )  # 문서 전체가 쪽 VLM(page_text) 대상이면(기본 — is_scan) 그림 VLM은 생략(중복 방지)

        page_bytes = p.read_bytes()
        page_vlm = page_covered or 1 in page_targets(p)
        parent_id = f"{name}#p1#page"  # F7 — 단독 이미지 전체 = page_render 부모(설계 §3 "#p<쪽>#page")
        out.append(
            {
                "image_id": parent_id,
                "loc": {"page": 1, "page_vlm": page_vlm, "page_render": True},
                "bbox": None,
                "bytes": page_bytes,
                "before": [],
                "after": [],
                "near": [],
            }
        )
        if page_vlm:  # VLM이 실제로 안 불릴 때는(꺼짐·미설정) 자식 찾기도 생략(graceful)
            from PIL import Image

            w, h = Image.open(io.BytesIO(page_bytes)).size
            out.extend(_nested_children(parent_id, page_bytes, 1, (w, h)))
    elif ext == ".eml":
        from pipeline.extract.engines.mhtml.parser import decode_mail_text  # SI42 — get_content()(선언 charset 그대로)는 EUC-KR 본문이 깨짐

        m = email.message_from_bytes(p.read_bytes(), policy=policy.default)
        imgs = {
            str(part.get("Content-ID", "")).strip("<>"): part.get_content() for part in m.walk() if part.get_content_maintype() == "image"
        }
        htm_part = next((part for part in m.walk() if part.get_content_type() == "text/html"), None)
        htm_raw = htm_part.get_payload(decode=True) if htm_part is not None else None
        htm = (
            decode_mail_text(htm_raw, htm_part.get_content_charset())
            if htm_raw is not None
            else (htm_part.get_content() if htm_part is not None else "")
        )
        subj = str(m.get("Subject", ""))
        for n, (cid, data) in enumerate(imgs.items(), 1):
            pos = htm.find(f"cid:{cid}")
            before = html.unescape(re.sub(r"<[^>]+>", "\n", htm[:pos])) if pos >= 0 else ""
            after = html.unescape(re.sub(r"<[^>]+>", "\n", htm[pos:])) if pos >= 0 else ""
            out.append(
                {
                    "image_id": f"{name}#p0#i{n}",
                    "loc": {"cid": cid},
                    "bbox": None,
                    "bytes": data,
                    "before": list(reversed(_lines(before)))[:2],
                    "after": _lines(after)[1:3],
                    "near": [f"메일 제목: {subj}"],
                }
            )
    # ponytail: F7의 _pptx_shape_figure·page_render 렌더 PNG도 이 문턱을 그대로 통과해야 함 — 아주 단순한(흰 배경·
    # 선 몇 개뿐) 도식은 PNG 압축이 좋아 3000바이트 밑으로 떨어져 기록이 조용히 빠질 수 있다(표본 문서는 통과 확인,
    # 더 단순한 슬라이드가 나오면 렌더 결과만 문턱을 낮추거나 따로 둘지 재검토).
    # 독립 검토(10-13) — F7 중첩 자식(loc.parent_image_id 있음)은 이 바이트 문턱에서 뺀다: nested.py의 bbox_regions
    # (실제 VLM 호출, 유료)가 이미 면적(MIN_AREA_RATIO) 기준으로 걸러낸 뒤 자른 크롭이라 "장식·로고"(이 문턱의
    # 원래 대상 — W11 원본 추출 그림)가 아니다. 단순한 선 몇 개짜리 도면(661x247 흰 배경)은 PNG 압축이 좋아 2~3KB로
    # 떨어져(실측) 이 문턱에 걸려 조용히 사라졌다 — 유료 VLM 호출로 찾은 자식을 바로 뒤에서 버리는 모양이라 돈만
    # 쓰고 기록은 0건.
    # F12 — 겹친 묶음 crop(f["overlay"] 있음)도 이 문턱에서 뺀다: 멤버 그림이 이미 loc.cluster_id로 이 기록을
    # 가리키고 있어(build_records의 overlay_cluster skip) 여기서 걸러지면 그 그림의 VLM 경로가 통째로 사라진다
    # (F7 parent_image_id 예외와 같은 이유).
    return [f for f in out if len(f["bytes"]) > 3000 or (f.get("loc") or {}).get("parent_image_id") or f.get("overlay")]


# ── VLM 그림 기록(JSON) ──────────────────────────────────────────────────
P_FIGJ = _load_prompt("figure_describe", "figjson")  # AD33 — 글자는 dev/agents/figure_describe/prompts/figjson.md
PID_FIG = prompt_id("figjson", "v2-nothink", P_FIGJ)  # 프로토타입과 같은 글자 → 같은 id(기존 VLM 캐시 재사용)
P_FIGOVERLAY = _load_prompt("figure_overlay", "overlay")  # F12 — 글자는 prompts/figure_overlay/prompt.md(새 파일, 기존 이름 안 건드림)


# ── AD10 — 그림 종류 가늠(모델 호출 없이, 이미 계산된 레코드 필드만) ─────────
# 함정(설계 메모 10-08): P_FIGJ를 종류별로 쪼개면 prompt_id(위)가 바뀌어 기존 VLM 캐시가 전부 무효화된다.
# 1단계는 지시문 글자를 그대로 두고 분량(출력 상한)만 조절한다 — vlm_fig(max_tokens=)는 캐시 경로에 안 들어가
# 종류가 달라도 같은 그림이면 기존 캐시를 그대로 재사용(아래 셀프체크·보고서에서 확인).
_FV = pc.cfg().transform.vlm  # S7c — 설정 객체(아래 모듈 상수 5개는 옛처럼 import 때 한 번 읽음, 옛 int(get(X) or 기본))
TEXT_IMAGE_OCR_CHARS = int(
    _FV.fig_text_ocr_min if _FV.fig_text_ocr_min is not None else 200
)  # crop OCR 글자 수(공백 제외) 이상 → text_image
# 실측(10-08, synth-charts·synth-images 래스터 차트·흐름도 7건): 축·범례·노드 라벨만으로도 40~150자가 나와 40은
# 차트·흐름도를 text_image로 오판(값·연결 추출을 VLM 생략으로 잃음) — 관측 상한(146자) 위로 200 — ponytail: 실측
# 값 하나로 고정한 문턱(천장), text_image 샘플이 생기면(현재 처리 가능 세트엔 없음) 재보정
PHOTO_OCR_CHARS_MAX = int(_FV.fig_photo_ocr_max if _FV.fig_photo_ocr_max is not None else 5)  # 이하 + 면적 어느 정도 있으면 → photo
PHOTO_AREA_RATIO_MIN = float(_FV.fig_photo_area_min if _FV.fig_photo_area_min is not None else 0.03)
PHOTO_MAX_TOKENS = int(
    _FV.fig_photo_max_tokens if _FV.fig_photo_max_tokens is not None else 300
)  # 사진류는 "한 줄 요약"만 필요 — 출력 상한을 낮춰 유도
VLM_FIG_OCR_MAX = int(_FV.fig_ocr_max if _FV.fig_ocr_max is not None else 8)  # crop OCR은 비용 큼(모델 로드·추론) — 문서당 상한
# OP11(10-11) — 글자 쪽 안에 박힌 그림(스캔 라벨 등)은 그림 경로로만 가는데, VLM 응답이 빈 경우(미설정·오류·빈 응답)
# 값이 그대로 사라진다(P-ROUTE 실측 2건 — hidden_term.pdf·mixed_pages.pdf) — 같은 crop OCR 글자로 채운다(_ocr_fallback).


def classify_figure_kind(fig):
    """AD10 — 종류 가늠(모델 호출 없이, 레코드 필드만) → text_image|photo|chart|flow|other.
    벡터 신호(loc.signals — vector_regions.py vector_regions, PDF 벡터 군집 그림에만 있음)가 있으면 그걸로 먼저:
    막대 신호 위주(bars>=3, bars>=curve_diag_arrow) → chart, 곡선·사선·화살표 위주(curve_diag_arrow>=3) → flow.
    래스터 그림(벡터 신호 없음)은 fig["ocr_chars"](crop OCR 글자 수, 호출부가 상한 안에서 미리 채움·없으면 None=
    모름)·area_ratio로 text_image(글자 많음)·photo(글자 거의 없음+어느 정도 면적) 가늠, 그 외(모름 포함)는 other
    (지금처럼 범용 VLM 그대로 — 과분류로 정보를 잃지 않는 안전한 기본값)."""
    sig = (fig.get("loc") or {}).get("signals")
    if sig:
        bars, curve = sig.get("bars", 0), sig.get("curve_diag_arrow", 0)
        if bars >= 3 and bars >= curve:
            return "chart"
        if curve >= 3 or sig.get("box_diagram"):  # AD13 — 상자+직선 도식(곡선·사선·화살촉 없음)도 flow
            return "flow"
        return "other"
    chars = fig.get("ocr_chars")
    if chars is not None and chars >= TEXT_IMAGE_OCR_CHARS:
        return "text_image"
    ratio = fig.get("area_ratio")
    if chars is not None and chars <= PHOTO_OCR_CHARS_MAX and (ratio is None or ratio >= PHOTO_AREA_RATIO_MIN):
        return "photo"
    return "other"


_TMP_DIR = (
    APP_ROOT / "output" / "_reread_tmp"
)  # 쓰기는 output/만(C4, dev/out = 컨테이너 /app/output 볼륨) — 크롭 PNG를 parser.py 계약(파일 경로)에 맞춰 잠깐 씀
# (pl-34 10-30 — 재판독 reread.py를 지우며 _default_ocr와 함께 이리로 옮김, 폴더 이름·로직 그대로)


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


def _crop_ocr(img_bytes):
    """그림 crop OCR(글자 그대로) — _default_ocr(rapidocr_ko, 결정적, 모델 설정 중복 방지).
    비용 큼(모델 로드·추론) — 호출부(build_records)가 문서당 상한을 건다."""
    return _default_ocr(img_bytes) or ""


FIG_OCR_FALLBACK_MIN_CHARS_DEFAULT = 10  # engine-qa CONCERN(10-11) ① — 로고·워터마크·스크린샷 머리글("# Outlook" 등)
# 1~2글자 조각이 VLM 미설정 문서마다 그대로 색인에 섞이는 문제. 실측(10-11, 이 기능이 살려낸 값들의 "의미 있는 글자"
# 수 — 한글·영문·숫자만 세고 공백·기호 제외): hidden_term velorimab 36자 · mixed_pages MX-W11 37자·MX-W12 19자(가장
# 짧음) · chart_production 29자 · chart_stability 32자. 가장 짧은 실측값(19자)에 10을 두면 거의 2배 여유로 다
# 살리면서, "# Outlook"(7자)·로고 약자(2~3자) 같은 조각은 10 미만이라 걸러진다 — ponytail: 실측 5건 기준, 표본이
# 늘면(특히 10~19자 사이 진짜 값이 나오면) 재조정.


def _meaningful_chars(s):
    """한글·영문·숫자만 센 길이(공백·기호 제외) — OCR 대체 글자의 '의미 있는 글자 수' 문턱 판정용."""
    return len(re.findall(r"[0-9A-Za-z가-힣]", s or ""))


def _ocr_fallback(f, prov, ocr_fn, ocr_budget):
    """OP11 — VLM 결과가 빈 경우(미설정·오류·빈 응답)만 호출. 같은 crop의
    AD10 분류 OCR(build_records가 이미 돌렸으면 f['ocr_text'])을 재사용 — 다시 OCR을 돌리지 않는다. 그 OCR이
    아직 안 돈 경우(벡터 그림·상한 소진)만 여기서 한 번 돌리되, 상한(ocr_budget, AD9
    선별로 작은/반복/못 엶은 이미 빠진 그림만 이 함수에 옴)을 같이 쓴다. 글자가 안 나오거나(ocr_text 빈 문자열)
    engine-qa CONCERN(10-11) ① — 의미 있는 글자 수가 문턱(FIG_OCR_FALLBACK_MIN_CHARS, 기본 10) 미만이면(로고·
    워터마크·짧은 머리글 조각) 쓰지 않고 VLM 실패 기록을 그대로 돌려줘 문서는 계속. ② — error는 지우지 않고
    원래 VLM 실패 사유를 그대로 둔다(ocr_fallback=True·model=ocr:rapidocr_ko로 대체 경로만 표시)."""
    ocr_text, ms = f.get("ocr_text"), None
    if ocr_text is None:
        if ocr_budget[0] <= 0:
            return "", prov
        t0 = time.perf_counter()
        try:
            ocr_text = (ocr_fn or _crop_ocr)(f["bytes"])
        except Exception:  # OCR 실패 1건이 문서를 막지 않게(engine-qa BLOCK ③과 같은 관례)
            ocr_text = ""
        ms = round((time.perf_counter() - t0) * 1000)
        ocr_budget[0] -= 1
    _mc = pc.cfg().transform.figures.ocr_fallback_min_chars  # S7c — 설정 객체(옛 int(get(X) or 기본))
    min_chars = int(_mc if _mc is not None else FIG_OCR_FALLBACK_MIN_CHARS_DEFAULT)
    if not ocr_text or _meaningful_chars(ocr_text) < min_chars:
        return "", prov
    rec = {"kind": None, "text": ocr_text, "summary": None, "values": [], "edges": [], "table_md": ""}
    new_prov = {
        **prov,
        "model": "ocr:rapidocr_ko",
        "ocr_fallback": True,
        "ocr_chars": len(re.sub(r"\s+", "", ocr_text)),
    }  # error는 그대로(**prov가 이미 들고 있음) — VLM 실패 사유를 안 지움
    if ms is not None:
        new_prov["ocr_ms"] = ms
    return json.dumps(rec, ensure_ascii=False), new_prov


def _png(img, max_side=2000):
    from PIL import Image

    im = Image.open(io.BytesIO(img))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), f"{im.width}x{im.height}"


def _model_dir(model):
    """P0 폴더 이름 — 프로토타입(eval_hard_parse.vlm_raw)과 같은 정리 규칙(모델 이름의 '/' 등은 '_')이라야 기존 캐시를 그대로 재사용한다."""
    return re.sub(r"[^\w.-]+", "_", model or "unset")


def _open_image(data):
    """Pillow가 열 수 있으면 Image, 못 열면 None — SI30: Linux Pillow는 WMF/EMF(윈도 메타파일)를 못 엶(Windows는 엶),
    그 밖의 깨진 바이트도 같게 처리. 그림 1건만 영향(호출부가 skip 사유로 기록하고 문서는 계속)."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
    except (OSError, ValueError, SyntaxError):
        return None
    try:  # Image.open은 머리글만 읽음(지연 로드) — Linux Pillow는 WMF 머리글은 알아보고 성공을 돌려준 뒤 실제 디코드에서
        im.load()  # 'cannot find loader for this WMF file'로 터짐(SI30 재발 — MinIO 컨테이너 시험 10-08). 여기서 미리 디코드해 걸러냄
    except (OSError, ValueError, SyntaxError):
        im.close()
        return None
    return im


def _unconvertible_kind(data):
    """열 수 없는 그림의 형식 추정 — WMF(Placeable/표준 윈도 메타파일)·EMF 머리글이면 그걸로, 모르면 범용 'image'."""
    head = data[:4]
    if head == b"\xd7\xcd\xc6\x9a":  # Placeable WMF(APM) — Word가 삽입하는 그림 대부분
        return "wmf"
    if head[:2] == b"\x01\x00":
        return "emf" if data[40:44] == b" EMF" else "wmf"  # 표준 WMF(mtType=1)·EMF(iType=1, 40바이트째 서명)
    return "image"


def _px_size(data):
    """그림 bytes → (가로, 세로) px — 깨진 이미지·Pillow가 못 여는 형식(SI30)은 (0, 0)(크기 모름 → 작다고 보지 않음, AD9 선별)."""
    im = _open_image(data)
    if im is None:
        return (0, 0)
    with im:
        return im.size


def select_figures(figs, ctxs, min_px):
    """AD9·AD21②·SI30 — VLM 후보 선별. Pillow가 못 여는 그림(WMF/EMF 등)은 "unconvertible:<형식>"으로 빼고,
    작은 그림(쪽 면적 1% 미만 또는 짧은 변 < min_px)·반복 이미지(같은 sha, 로고)도 후보에서 빼고(기록은 남김,
    skip 사유만), 남은 그림은 **원래 그림(중첩 자식 아님) 먼저 → 캡션 있음 → 본문 언급 있음 → 면적(px) 큰 순**으로
    정렬(독립 검토 Minor(10-13) — F7 중첩 자식이 상한 VLM_FIGURES_MAX를 다 차지해 같은 문서의 원래 그림을 굶기지
    않게, loc.parent_image_id가 있는 그림을 뒤로 미룬다).
    반환: (order = 우선순위 순 인덱스 목록, skip = {인덱스: "small"|"duplicate"|"unconvertible:<형식>"})."""
    pxs = [_px_size(f["bytes"]) for f in figs]
    seen, skip, order = set(), {}, []
    for i, f in enumerate(figs):
        w, h = pxs[i]
        if (w, h) == (0, 0) and _open_image(f["bytes"]) is None:  # SI30 — 크기 0이 아니라 '못 엶'인지 구분
            skip[i] = f"unconvertible:{_unconvertible_kind(f['bytes'])}"
            continue
        ratio = f.get("area_ratio")
        if (ratio is not None and ratio < 0.01) or (min(w, h) if w and h else 0) < min_px:
            skip[i] = "small"
            continue
        s = sha(f["bytes"])
        if s in seen:
            skip[i] = "duplicate"
            continue
        seen.add(s)
        order.append(i)
    order.sort(
        key=lambda i: (
            0 if not (figs[i].get("loc") or {}).get("parent_image_id") else 1,
            0 if ctxs[i].get("caption") else 1,
            0 if ctxs[i].get("mentions") else 1,
            -(pxs[i][0] * pxs[i][1]),
            i,
        )
    )
    return order, skip


FULL_VERSION = "v2-nothink"  # 기본(전체 출력 상한) 캐시 버전 세그먼트 — 바뀌면 안 됨(기존 P0 캐시 전부가 이 이름 아래)


def vlm_fig(img_bytes, max_tokens=None, prompt_text=None, cache_name=None, agent="figure_describe"):
    """그림 1장 → (JSON 글자, provenance) — P0 캐시(model·prompt_id·그림 sha가 같으면 재사용, 호출 0). 실패·빈 답은 저장 안 함.
    SI30 — Pillow가 못 여는 그림(select_figures가 거른 뒤에도 여기서 한 번 더 가드)은 VLM을 부르지
    않고 "unconvertible:<형식>"만 돌려준다(그림 1건만 영향, 문서는 계속).
    AD10 — max_tokens(없으면 기본 1500=FULL_VERSION)가 기본과 다르면(예: photo의 300) 캐시 버전 세그먼트에
    `_mt<값>`을 붙여 **별도 캐시 키**를 쓴다(engine-qa BLOCK 10-08 ① 반영 — 잘린 답이 기본 캐시를 오염시키지
    않게). full 호출(max_tokens 없음)은 언제나 FULL_VERSION 경로만 보므로 `_mt` 캐시를 절대 안 읽는다(기존 캐시
    그대로 재사용). 축소 호출은 먼저 FULL_VERSION 캐시가 있는지 보고(있으면 완전한 답을 그대로 재사용 — 무해한
    방향), 없을 때만 자기 `_mt` 캐시를 본다.
    F12 — prompt_text·cache_name·agent(기본 전부 None/"figure_describe" → figure_describe 그대로, 바이트 동일)를
    주면 다른 지시문·캐시 이름·에이전트 패키지로 부른다(지금은 vlm_fig_overlay가 figure_overlay 전용으로 씀)."""
    if _open_image(img_bytes) is None:
        return "", {"skipped": f"unconvertible:{_unconvertible_kind(img_bytes)}"}
    base, model = ccfg().models.vlm.base_url, ccfg().models.vlm.model  # S7c — 설정 객체
    img_sha = sha(img_bytes)
    prompt_text = P_FIGJ if prompt_text is None else prompt_text
    cache_name = cache_name or "figjson"
    full_out = raw_vlm_path(raw_root(), _model_dir(model), cache_name, FULL_VERSION, prompt_text, img_sha)
    if full_out.exists():
        rec = json.loads(full_out.read_text(encoding="utf-8"))
        return rec["text"], {**rec["provenance"], "cached": True}
    mt = max_tokens or 1500
    version = FULL_VERSION if mt == 1500 else f"{FULL_VERSION}_mt{mt}"
    out = full_out if version == FULL_VERSION else raw_vlm_path(raw_root(), _model_dir(model), cache_name, version, prompt_text, img_sha)
    if out.exists():
        rec = json.loads(out.read_text(encoding="utf-8"))
        return rec["text"], {**rec["provenance"], "cached": True}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 그림 기록은 글자만(VLM 없음)"}
    data, px = _png(img_bytes)
    # 생각(추론) 모델은 출력 상한(max_tokens)을 추론에 다 써 빈 답이 될 수 있다(W16 실측 2026-10-02) — 끄기는 common.models.vlm.extra_body
    # (예 {"chat_template_kwargs": {"enable_thinking": false}} · OpenRouter {"reasoning": {"enabled": false}}, 11-04 — 코드 고정값 지움)
    t0 = time.perf_counter()
    try:
        text, u = V.ask(prompt_text, data, max_tokens=mt, agent=agent)
    except A.ModelUnavailable as ex:
        return "", {"error": str(ex)[:200], "ms": round((time.perf_counter() - t0) * 1000)}
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        return "", {"error": "빈 응답", "ms": ms}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
    pid = PID_FIG if (version == FULL_VERSION and cache_name == "figjson") else prompt_id(cache_name, version, prompt_text)
    prov = {
        "model": model,
        "endpoint_host": _host(base),
        "prompt_id": pid,
        "image_sha256": img_sha,
        "px": px,
        "params": {"temperature": 0, "max_side": 2000, "max_tokens": mt},
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
        "created_at": NOW,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"text": text, "provenance": prov}, ensure_ascii=False), encoding="utf-8")
    return text, prov


def vlm_fig_overlay(img_bytes):
    """F12 — 겹친 묶음 전용 VLM 호출(figure_overlay 지시문·캐시, 1장=1회 — 묶음에 든 그림들은 따로 안 부름)."""
    return vlm_fig(img_bytes, prompt_text=P_FIGOVERLAY, cache_name="figoverlay", agent="figure_overlay")


def _host(url):
    import urllib.parse

    return urllib.parse.urlparse(url).hostname or url


def parse_json(t):
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {"text": t}


# ── index.jsonl(설계 §3 계약) + PNG 저장 ────────────────────────────────
def images_root():
    _pp = pc.cfg().paths  # S7c — 설정 객체(옛 get(X) or … — 빈 글자 = 없음)
    return Path(
        _pp.images_root or ((Path(_pp.out_root or (APP_ROOT / "output"))) / "parse" / "_images")
    )  # 2026-10-23 — PIPE_OUT_ROOT 따라감(문서별 격리, 병렬 docflow의 index.jsonl 경합 방지)


def _save_png(data, dest):
    """SI30 — Pillow가 못 여는 그림(WMF/EMF 등)은 (None, None, 형식)으로, 이 그림 하나만 PNG 없이 건너뛰고
    문서(write_index)는 계속 진행한다 — 전엔 여기서 예외가 나 대표 결과 전체가 멈추고 _DONE.json이 안 생겼다."""
    im = _open_image(data)
    if im is None:
        return None, None, _unconvertible_kind(data)
    with im:
        if im.mode not in ("RGB", "L", "RGBA"):
            im = im.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, "PNG")
        return im.width, im.height, None


def _loc_fields(loc):
    """내부 loc(형식별로 다름) → 계약의 평평한 page·sheet·anchor(설계 §3)."""
    if "page" in loc:
        return loc["page"], None, None
    if "sheet" in loc:
        return None, loc["sheet"], loc.get("cell")
    if "slide" in loc:
        return loc["slide"], None, None
    if "order" in loc:
        return 0, None, f"order:{loc['order']}"
    if "cid" in loc:
        return 0, None, loc["cid"]
    return None, None, None


def _pick_edges(ext, page, px_edges, rec_edges):
    """pptx는 슬라이드 연결선(px_edges)이 있으면 그걸(edges_source=pptx_xml), 없으면 VLM edges(있으면 vlm) → (edges, source).
    F13 — PDF 벡터 도식 그림은 build_records가 이 결과에 vector·glyph 소스를 더 얹는다(_pick_edges_det)."""
    slide_edges = px_edges.get(page) if ext == ".pptx" else None
    if slide_edges:
        return slide_edges, "pptx_xml"
    return rec_edges, ("vlm" if rec_edges else None)


def _pick_edges_det(ext, page, px_edges, rec_edges, pdf_doc, f):
    """F13 — _pick_edges(위) 결과에 PDF 벡터 도식 그림(loc.origin=="vector")만 vector·glyph 소스를 더해 합친다
    (우선순위 pptx_xml > vector > glyph > vlm — pptx_xml이 이미 있으면 그대로, 벡터 그림이 아니면 손 안 댐).
    pdf_doc=None(벡터 그림 없는 문서)이면 이 조건에서 이미 걸러져 추가 비용 없음."""
    edges, edges_source = _pick_edges(ext, page, px_edges, rec_edges)
    if pdf_doc is None or (f.get("loc") or {}).get("origin") != "vector" or not f.get("bbox") or not page:
        return edges, edges_source
    if edges_source == "pptx_xml":  # pptx 경로는 ext==".pdf"에서 절대 안 나오지만 방어적으로 그대로
        return edges, edges_source
    v_edges = diag_edges.vector_edges_from_page(pdf_doc[page - 1], f["bbox"])
    g_edges = diag_edges.glyph_edges(f.get("text_layer") or "")
    merged, used = diag_edges.merge_edges([("vector", v_edges), ("glyph", g_edges), ("vlm", rec_edges)])
    return (merged, "+".join(used)) if merged else (edges, edges_source)  # F13 리뷰④ — edges_source는 항상 str|None


def build_records(doc_name, doc_path, doc_text, doc_sha256, run_id=0, ocr_fn=None, figures_max=None, page_covered=False):
    """문서 1건의 그림 기록 목록(설계 git 이력 docs/plans/image-parsing-2026-10-01.md(c4874dd0^) §3·§3-0 계약 — modules/search/mcp_server.py가 이 모양으로 읽음)
    + 렌더된 본문 블록(단순·보정) 목록 → (records, plain_blocks, enriched_blocks).
    AD9·AD21 — 작은 그림·반복 이미지는 VLM 후보에서 빼고(skipped: small/duplicate), 남는 그림은 캡션·본문 언급·면적 순으로
    상한(VLM_FIGURES_MAX) 안을 채운다. 상한에 걸려 건너뛴 그림은
    skipped: "VLM_FIGURES_MAX"로 기록에 남는다(문서별 capped.jsonl은 읽는 곳이 없어 0.2.0에 지움 — pl-46).
    AD10 — VLM 보낼 그림(send)마다 classify_figure_kind()로 종류를 가늠(모델 호출 없음): text_image는 기록만(VLM 그대로), photo는 max_tokens를 낮춰 한 줄 요약 유도,
    chart·flow·other(모름 포함)는 지금처럼 전체 P_FIGJ 호출 — 지시문 글자·prompt_id는 안 바꿔 기존 VLM 캐시 그대로
    재사용한다. ocr_fn — crop OCR 재사용 지점(없으면 _crop_ocr, 테스트는 가짜 OCR 주입).
    OP11 — VLM 응답이 빈 경우(미설정·오류·빈 응답)만 같은 crop의 OCR 글자로 채운다(_ocr_fallback). VLM 응답이
    있으면(비어 있지 않으면) 그대로.
    figures_max — 그림 상한을 이번 호출만 바꿈(None이면 설정 VLM_FIGURES_MAX — figures_resume이 상한을 올려 다시 돌 때, S7c2:
    전엔 env를 잠깐 바꿔 넘김)."""
    ext = Path(doc_path).suffix.lower()
    is_pdf = ext == ".pdf"
    px_edges = pptx_edges(doc_path) if ext == ".pptx" else {}  # 슬라이드 XML 연결선 — VLM edges보다 우선(있으면)
    figs = figures(doc_path, page_covered)
    pdf_doc = None  # F13 — PDF 벡터 도식 결정적 edges 추출용 fitz 문서(비PDF·벡터 그림 없는 문서는 안 엶, 비용 0)
    if is_pdf and any((f.get("loc") or {}).get("origin") == "vector" for f in figs):
        import fitz as _fitz

        pdf_doc = _fitz.open(doc_path)
    records, plain, enriched = [], [], []
    _fm = (
        figures_max if figures_max is not None else pc.cfg().transform.vlm.figures_max
    )  # S7c — 설정 객체(옛 int(get(X) or 20)) · 인자가 이김
    cap = int(_fm if _fm is not None else 20)  # 문서당 VLM에 보낼 그림 상한(야간 배치 비용·시간 가드, 독립 검토 10-03) — 0이면 VLM 안 부름
    sents = C.sentences(doc_text)  # 문서마다 한 번(fp-perf B4)
    ctxs = [C.link_context(f, doc_text, sents) for f in figs]
    _mp = pc.cfg().transform.vlm.fig_min_px  # S7c — 설정 객체(옛 int(get(X) or 64))
    min_px = int(_mp if _mp is not None else 64)
    order, skip_reason = select_figures(figs, ctxs, min_px)
    for i, f in enumerate(figs):  # BR56 — 쪽·슬라이드 VLM이 이미 다룬 그림(figures()의 loc.page_vlm)은 기록은 두고
        if (f.get("loc") or {}).get("page_vlm") and i not in skip_reason:  # 그림 VLM만 생략(이중 호출 방지)
            skip_reason[i] = "page_vlm"
        if (f.get("loc") or {}).get(
            "cluster_id"
        ) and i not in skip_reason:  # F12 — 겹친 묶음에 든 그림은 묶음 쪽에서 VLM 1회(이 그림은 생략, 기록은 유지)
            skip_reason[i] = "overlay_cluster"
    order = [i for i in order if i not in skip_reason]  # VLM_FIGURES_MAX 상한은 실제로 VLM이 필요한 그림끼리만 다툰다
    send = set(order[:cap])
    # engine-qa BLOCK(10-08) ② — classify_figure_kind는 provenance.fig_kind로 기록만 하고 text_image도 VLM을 부른다
    # (글자 이미지 VLM 생략 VLM_FIG_TEXT_SKIP은 op-08에 지움).
    ocr_budget = [VLM_FIG_OCR_MAX]  # 문서당 crop OCR 상한(공유 카운터, 리스트로 함수 밖에서도 줄임)
    _fitz_cache = {}

    def _chart_page(pn):  # 문서당 fitz.Document 1개만 열어 벡터 그림마다 재사용(쪽 번호로 바로 접근)
        if "doc" not in _fitz_cache:
            import fitz

            _fitz_cache["doc"] = fitz.open(doc_path)
        return _fitz_cache["doc"][pn - 1]

    # 2026-10-22 figures parallel: Phase A (OCR classify, parallel) then Phase B (VLM, parallel)
    import concurrent.futures as _fig_cf

    _need_ocr = [i for i in sorted(send) if not (figs[i].get("loc") or {}).get("signals")]
    _use_ocr = _need_ocr[: ocr_budget[0]]
    if _use_ocr:
        ocr_budget[0] -= len(_use_ocr)

    def _ocr_one(fi):
        f = figs[fi]
        t_ocr = time.monotonic()
        try:
            f["ocr_text"] = (ocr_fn or _crop_ocr)(f["bytes"])
            f["ocr_chars"] = len(re.sub(r"\s+", "", f["ocr_text"]))
            SP.observe_current("ocr_ms", (time.monotonic() - t_ocr) * 1000)  # op-01 — OCR 호출 수·지연
        except Exception as e:
            SP.add_current(ocr_fail=1)
            f["ocr_text"], f["ocr_chars"] = "", None
            f["ocr_error"] = str(type(e).__name__) + ": " + str(e)[:200]

    if _use_ocr:
        _op = pc.cfg().transform.figures.ocr_parallel  # S7c — 설정 객체(옛 int(get(X) or 3))
        _ocr_par = max(1, min(int(_op if _op is not None else 3), len(_use_ocr)))
        with _fig_cf.ThreadPoolExecutor(max_workers=_ocr_par) as _ex_a:
            list(_ex_a.map(SP.carry(_ocr_one), _use_ocr))  # op-01 — 풀 스레드에 run/span ID를 실음(VLM·OCR 지표가 이 문서 span에 쌓이게)
    _kinds = {}
    for i in sorted(send):
        _kinds[i] = classify_figure_kind(figs[i])
    _vlm_set = sorted(send)

    def _vlm_one(fi):
        f = figs[fi]
        kind = _kinds[fi]
        if f.get("overlay"):
            t, pv = vlm_fig_overlay(f["bytes"])
        else:
            t, pv = vlm_fig(f["bytes"], max_tokens=PHOTO_MAX_TOKENS if kind == "photo" else None)
        if not t.strip():
            t, pv = _ocr_fallback(f, pv, ocr_fn, ocr_budget)
        if kind:
            pv = dict(pv, fig_kind=kind)
        return (fi, t, pv)

    _vp = ccfg().models.vlm.concurrency  # 문서 하나 안 VLM 동시 수(쪽·그림 공통, 11-04)
    _vlm_par = max(1, min(int(_vp if _vp is not None else 4), max(len(_vlm_set), 1)))
    _vlm_dict = {}
    if _vlm_set:
        with _fig_cf.ThreadPoolExecutor(max_workers=_vlm_par) as _ex_b:
            for fi, t, pv in _ex_b.map(SP.carry(_vlm_one), _vlm_set):
                _vlm_dict[fi] = (t, pv)
    for i, f in enumerate(figs):
        if i in skip_reason:
            text, prov = "", {"skipped": skip_reason[i]}
        elif i in send:
            if i in _vlm_dict:
                text, prov = _vlm_dict[i]
            else:
                text, prov = "", {}
        else:
            text, prov = "", {"skipped": "VLM_FIGURES_MAX"}
        rec = parse_json(text) if text else {}
        ctx = ctxs[i]
        check = C.value_check(rec, ctx["mentions"] + ([ctx["caption"]] if ctx["caption"] else []))
        plain.append(C.render(f, rec))
        enriched.append(C.render(f, rec, ctx, check))
        page, sheet, anchor = _loc_fields(f["loc"])
        origin = (
            "shape_render"
            if f["loc"].get("shape_render")
            else "vector"
            if f["loc"].get("origin") == "vector"
            else ("raster" if is_pdf else "embedded")
        )
        edges, edges_source = _pick_edges_det(ext, page, px_edges, rec.get("edges"), pdf_doc, f)
        # F14(a) — PDF 벡터 그림(origin=="vector")만 결정적 값(VLM 없음)을 먼저 구해 같은 (계열, x)는 그 값이 이김
        # (merge_values) · 그 밖 그림은 content.values가 VLM 값 그대로.
        det_values = []
        if origin == "vector" and page:
            try:
                det_values, _cv_meta = CV.extract_vector(_chart_page(page), f["bbox"])
            except Exception:  # 결정적 추출 실패 1건이 그림 기록을 막지 않게(기존 VLM 경로 그대로)
                det_values = []
        merged_values = CV.merge_values(det_values, rec.get("values")) if origin == "vector" else rec.get("values")
        rec_out = {
            "image_id": f["image_id"],
            "doc": doc_name,
            "source_file": str(doc_path),
            "page": page,
            "sheet": sheet,
            "anchor": anchor,
            "bbox": f["bbox"],
            "origin": origin,
            "sha256": sha(f["bytes"]),
            "text_layer": f.get("text_layer") or "",
            "kind": rec.get("kind"),
            "vlm": {
                "model": prov.get("model"),
                "summary": rec.get("summary"),
                "text": rec.get("text"),
                "content": {"values": merged_values, "edges": edges, "table_md": rec.get("table_md")},
            },
            "edges_source": edges_source,
            "mermaid": to_mermaid(edges) if edges else "",
            "vlm_error": prov.get("error"),
            "skipped": prov.get("skipped"),
            "caption": ctx["caption"],
            "caption_source": ctx["caption_source"],
            "mentions": ctx["mentions"],
            "value_check": check,
            # F7 — parent_image_id·depth는 _nested_children(figures())가 loc에 남긴 값을 그대로(없으면 기본값
            # None·0 — 중첩 아닌 보통 그림), children은 아래서 이 문서 레코드를 한 번 더 훑어 채운다(설계 §3).
            "parent_image_id": f["loc"].get("parent_image_id"),
            "depth": f["loc"].get("depth") or 0,
            "children": [],
            "page_render": bool(f["loc"].get("page_render")),
            "overlay": f.get("overlay"),  # F12 — 겹친 묶음이면 {members, texts}, 아니면 None(바이트 영향 0)
            "doc_sha256": doc_sha256,
            "run_id": run_id,
            "provenance": {
                k: prov.get(k) for k in ("model", "endpoint_host", "prompt_id", "image_sha256", "created_at", "fig_kind", "ocr_fallback")
            },
            "_bytes": f["bytes"],
        }
        rec_out["trend"] = CV.compute_trend(det_values or merged_values) if merged_values else None  # F14(c)
        records.append(rec_out)
    if "doc" in _fitz_cache:
        _fitz_cache["doc"].close()
    by_parent = {}
    for r in records:  # F7 — children 역인덱스(부모 image_id → 자식 id 목록, 문서 안에서만)
        pid = r["parent_image_id"]
        if pid:
            by_parent.setdefault(pid, []).append(r["image_id"])
    for r in records:
        if r["image_id"] in by_parent:
            r["children"] = by_parent[r["image_id"]]
    if pdf_doc is not None:
        pdf_doc.close()
    return records, plain, enriched


def write_index(doc_name, records, out_images=None):
    """index.jsonl에 이 문서 기록을 upsert(같은 문서 옛 줄은 지우고 새로) + PNG 저장 → 결정적(같은 입력 = 같은 ID·sha)."""
    root = out_images or images_root()
    root.mkdir(parents=True, exist_ok=True)
    idx = root / "index.jsonl"
    rows = []
    if idx.exists():
        for ln in idx.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if r.get("doc") != doc_name:
                    rows.append(r)
    for r in records:
        safe = re.sub(r"[^\w.#-]+", "_", r["image_id"])
        png_path = root / doc_name / f"{safe}.png"
        data = r.pop("_bytes")
        w, h, unconv = _save_png(data, png_path)
        r["png"] = None if unconv else f"_images/{doc_name}/{safe}.png"
        if unconv and not r.get("skipped"):  # SI30 — build_records에서 이미 분류했으면 그 사유를 유지
            r["skipped"] = f"unconvertible:{unconv}"
        r["w"], r["h"] = w, h
        rows.append(r)
    rows.sort(key=lambda r: (r["doc"], r["image_id"]))
    idx.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return [r for r in rows if r["doc"] == doc_name]
