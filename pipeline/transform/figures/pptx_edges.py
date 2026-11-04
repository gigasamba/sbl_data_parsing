"""pptx 슬라이드 XML의 연결선(connector, p:cxnSp의 a:stCxn·a:endCxn) → edges[{from,to,label}], 슬라이드별.
VLM이 읽은 edges보다 우선(실측: 다른 세션, git 이력 docs/plans/comparison-report-structure-2026-10-03.md(c4874dd0^) §6 — 연결 F1 1.0/1.0/1.0/0.83).

AD20(남은 것, 10-08) — 슬라이드 렌더 쪽 VLM 대상 조건(규칙 신호만, VLM에 보일지 '가벼운 판단'은 AG11 몫):
`candidate_slides()`가 연결선·네이티브 차트 XML로 안 잡히는 구조(상자·화살표 모양 도형이 연결선 없이 배치만 된
도식·SmartArt)의 슬라이드 번호를 고른다. 실제 슬라이드 렌더(LibreOffice)·VLM 호출 연동은 범위 밖(다음 단계) —
여기선 후보만 고른다."""

from pathlib import Path

from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
# AD20 — "도형이 많은데 연결선이 없다"의 "많다" 문턱(최상위 도형 수, 그룹은 1개로 셈). 상한은 문서당(이 경우 슬라이드당 아님 — 문서 전체 슬라이드 수) env(0=꺼짐).
PPTX_SHAPES_MIN = 4
PARSE_PPTX_SHAPES_MAX_DEFAULT = "20"
PARSE_PPTX_SMARTART_MAX_DEFAULT = "20"


def _cap(name, default):
    return int(
        pc.by_env(name, default)
    )  # S7c — 설정 객체(옛 int(get(name, default)), ValueError면 int(default) — 객체는 ''·형식 틀림 = 칸 기본값)


def _is_smartart(sh):
    """SmartArt graphicFrame — python-pptx의 shape_type 자동 판별이 최소 XML에서는 안 먹혀(관찰, relIds 없는 등)
    graphicData uri에 diagram 네임스페이스가 있는지 원본 XML에서 직접 찾는다(안전 쪽 — 오탐 없음, false 가능)."""
    try:
        return "drawingml/2006/diagram" in sh._element.xml
    except Exception:
        return False


def slide_signals(p):
    """AD20 — 슬라이드마다 도형 신호: [{slide, shapes(최상위 도형 수), connectors(유효한 연결선 수, pptx_edges와
    같은 판정), smartart(diagram graphicFrame 있나)}]."""
    from pptx import Presentation

    pr = Presentation(Path(p))
    out = []
    for si, s in enumerate(pr.slides, 1):
        shapes = list(s.shapes)
        connectors = 0
        for sh in shapes:
            if not sh._element.tag.endswith("}cxnSp"):
                continue
            st = sh._element.find(".//a:stCxn", NS)
            en = sh._element.find(".//a:endCxn", NS)
            if st is not None and en is not None:
                connectors += 1
        out.append({"slide": si, "shapes": len(shapes), "connectors": connectors, "smartart": any(_is_smartart(sh) for sh in shapes)})
    return out


def candidate_slides(p):
    """AD20 — 연결선·네이티브 차트로 못 잡는 슬라이드 구조 후보 {슬라이드 번호: 이유}(먼저 맞는 것 하나):
    'smartart' = graphicFrame에 diagram 데이터 있음 · 'shapes_no_connector' = 도형이 PPTX_SHAPES_MIN(기본 4)개
    이상인데 연결선(pptx_edges 기준)이 0개 — 상자·화살표가 연결선 없이 배치만 된 도식(사용자 2026-10-06 지적
    사례). 상한 PARSE_PPTX_SMARTART_MAX·PARSE_PPTX_SHAPES_MAX(env, 기본 20, 0=꺼짐 — 그 이유 자체를 안 봄)."""
    sa_cap, sh_cap = (
        _cap("PARSE_PPTX_SMARTART_MAX", PARSE_PPTX_SMARTART_MAX_DEFAULT),
        _cap("PARSE_PPTX_SHAPES_MAX", PARSE_PPTX_SHAPES_MAX_DEFAULT),
    )
    out, n_sa, n_sh = {}, 0, 0
    for r in slide_signals(p):
        if r["smartart"] and n_sa < sa_cap:
            out[r["slide"]] = "smartart"
            n_sa += 1
        elif r["connectors"] == 0 and r["shapes"] >= PPTX_SHAPES_MIN and n_sh < sh_cap:
            out[r["slide"]] = "shapes_no_connector"
            n_sh += 1
    return out


def _in_rect(x, y, l, t, w, h):  # noqa: E741 — 좌·위·폭·높이(pptx 도형 좌표 관례)
    """F10 — 점(x,y)이 사각형(l,t,w,h) 안(경계 포함)인가."""
    return l <= x <= l + w and t <= y <= t + h


def picture_arrow_edges(s, exclude_ids=()):
    """F10 — stCxn/endCxn 앵커 없는 자유 배치 connector(화살표/선)가 그림(shape_type 13) 위 한 점을 가리키는
    경우만 뽑는다: 한쪽 끝이 그림 사각형 안, 반대쪽 끝은 밖 — 밖쪽 끝에 겹치는 글상자 글자가 있으면 "from"으로.
    pptx_edges()·figure_extract.py 공용(계산은 여기 한 곳에만 둔다). "to"는 그림 순번(그 슬라이드 내 picture shape
    순서, figures.py의 pics 열거와 같은 기준) — 그림마다 image_id가 따로 있어 실제 image_id는 호출 쪽이 안다."""
    pics = [sh for sh in s.shapes if sh.shape_type == 13]  # MSO_SHAPE_TYPE.PICTURE
    if not pics:
        return []
    boxes = [sh for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    conns = [sh for sh in s.shapes if sh._element.tag.endswith("}cxnSp") and sh.shape_id not in exclude_ids]
    out = []
    for pic_i, pic in enumerate(pics, 1):
        l, t, w, h = pic.left, pic.top, pic.width, pic.height  # noqa: E741 — 좌·위·폭·높이(위 _in_rect와 같은 관례)
        for c in conns:
            try:
                bx, by, ex, ey = c.begin_x, c.begin_y, c.end_x, c.end_y
            except AttributeError:  # 앵커 connector(stCxn/endCxn)는 begin_x 등이 없을 수 있음 — 안전하게 건너뜀
                continue
            b_in, e_in = _in_rect(bx, by, l, t, w, h), _in_rect(ex, ey, l, t, w, h)
            if b_in == e_in:  # 둘 다 안·둘 다 밖 — 그림 가장자리를 가리키는 화살표가 아님
                continue
            point, outside = ((ex, ey), (bx, by)) if e_in else ((bx, by), (ex, ey))
            text = next(
                (b.text_frame.text.strip() for b in boxes if _in_rect(outside[0], outside[1], b.left, b.top, b.width, b.height)), None
            )
            rx = round((point[0] - l) / w, 4) if w else 0.0
            ry = round((point[1] - t) / h, 4) if h else 0.0
            out.append({"from": text, "to": f"image#{pic_i}", "label": None, "point": [rx, ry], "kind": "arrow"})
    return out


def pptx_edges(p):
    """{슬라이드 번호(1부터): [{"from","to","label"}, ...]} — 연결선 없는 슬라이드는 빠짐. 보통 연결선(stCxn/
    endCxn 앵커) 외에 F10: 그림 위에 겹친 자유 배치 화살표도 picture_arrow_edges()로 섞여 들어간다(추가
    키 "point"·"kind":"arrow", "to"는 "image#<순번>")."""
    from pptx import Presentation

    pr = Presentation(Path(p))
    out = {}
    for si, s in enumerate(pr.slides, 1):
        id_text = {sh.shape_id: (sh.text_frame.text.strip() if sh.has_text_frame else "") for sh in s.shapes}
        edges = []
        anchored_ids = set()
        for sh in s.shapes:
            if not sh._element.tag.endswith("}cxnSp"):
                continue
            st = sh._element.find(".//a:stCxn", NS)
            en = sh._element.find(".//a:endCxn", NS)
            if st is None or en is None:
                continue
            anchored_ids.add(sh.shape_id)
            frm, to = id_text.get(int(st.get("id"))), id_text.get(int(en.get("id")))
            if not (frm and to):
                continue
            label = "".join(t.text or "" for t in sh._element.findall(".//a:t", NS)).strip()  # 연결선 자체 글자(있으면 라벨)
            edges.append({"from": frm, "to": to, "label": label or None})
        edges.extend(picture_arrow_edges(s, anchored_ids))
        if edges:
            out[si] = edges
    return out
