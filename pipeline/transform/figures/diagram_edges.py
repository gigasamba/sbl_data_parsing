"""흐름도 화살표 edges를 규칙으로(VLM 없음, 결정적) 찾는다. 겨냥한 증상: ① 비슷한 도식인데
"->" 류 화살표가 때론 텍스트로 들어오고 때론 안 들어옴(비결정적) ② 세로(위·아래) 화살표 인식이 약함 ③ 글자
작음·화살표 선 얇고 짧음·저해상도. 이 모듈은 두 가지 결정적 추출기를 둔다:

  vector_edges_from_page(page, bbox) — PDF 벡터 도식(vector_regions가 이미 "그림 영역"으로 고른 bbox) 안의
    get_drawings()만 다시 훑어 상자(둥근 모서리 포함 — 닫힌 l/c 경로의 둘러싼 면적이 bbox 면적의 상당 비율이면
    상자, re 기본 상자도 그대로)를 노드로, 선분·폴리라인(엘보 연결선 포함) 양 끝을 가장 가까운 상자에 붙이고,
    끝점 가까이 화살촉(① 작은 채운 다각형 또는 ② 선 끝에서 만나는 두 짧은 선분 — 열린 쉐브론)이 있는 쪽을
    head로 삼는다(가로·세로·대각선 모두 같은 규칙, ② 대응). **화살촉이 전혀 없으면 그 edge는 버린다**(읽는
    순서 대체 없음 — 화살표 없는 상자+직선류를 edge로 내면 눈금 있는 표·축차트·폼에서
    헛edge가 남는다). 또한 영역 안에 이름 붙은 상자가 2개 미만이거나 화살촉이 하나도 없으면 그 영역 전체에서
    deterministic edges를 내지 않는다(영역 보호장치 — 표·폼 오탐 방지). 상자 이름은 상자 안 글자가 비어 있으면
    테두리 아래·옆 가까운 글자줄로 대체(실제 도식 관례 — 라벨이 상자 밖에 있는 스타일). 문턱은 절대 pt가 아니라
    그 영역에서 찾은 상자 크기(중앙값)에 상대적으로 스케일(생성기 수치에만 맞춰 과적합하지 않게).
  glyph_edges(text) — 문서 글자(복사-붙임 가능한 텍스트) 안의 화살표 글자(→ ← ↑ ↓ -> <- => ⇐)로 이어진 노드
    이름 → edges(① 대응 — 글자가 있으면 항상 같은 모양으로 뽑는다).

merge_edges(sources) — figure_extract.build_records가 pptx_xml > vector > glyph > vlm 순으로 모아 **정규화한
무방향 (from,to) 짝**으로 중복을 제거해 하나로 합친다(방향 키로만 중복 제거하면 역방향
VLM edge가 결정적 edge 옆에 살아남는다 — 이제 같은 짝이면 우선순위가 더 높은 소스가 방향까지 이긴다).
순수 함수(파일·네트워크 없음) — vlm 쪽만 모델이 이미 부른 값을 받아 쓴다."""

import math
import re

from pipeline.transform.represent.text_normalize import canon_symbols

POINT_MERGE_TOL = 0.5  # 폴리라인 왕복(there-and-back)·닫힌 경로 끝점을 같은 점으로 볼 허용 오차(pt)
BOX_AREA_RATIO = 0.75  # 닫힌 l/c 경로의 둘러싼 면적 ÷ bbox 면적이 이보다 크면 "상자"(둥근 모서리 포함),
# 작으면(삼각형·화살촉 등) 상자가 아님 — 생성기 수치가 아니라 기하 비율이라 과적합 아님
_DEFAULT_SCALE = 40.0  # 영역에 상자가 하나도 없을 때(이론상 — 보통 보호장치에서 먼저 걸림) 쓰는 기본 스케일(pt)


def _item_start(it):
    return it[1]


def _item_end(it):
    return it[4] if it[0] == "c" else it[2]


def _closed_poly_points(items):
    """l/c 항목들에서 끝점만 모아 폴리곤 점 목록(곡선은 시작·끝점만 써서 둥근 모서리도 사각형에 가깝게 근사)."""
    pts = []
    for it in items:
        pts.append(_item_start(it))
        pts.append(_item_end(it))
    return pts


def _shoelace_area(pts):
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i].x, pts[i].y
        x2, y2 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _is_box(d, r):
    """노드 상자 판정 — ① vector.py와 같은 기본 기준(kinds==["re"], 채움 여부 안 봄) ② 그 밖엔 l/c로만 이뤄진
    **닫힌** 경로(둥근 모서리 상자 포함)이고 둘러싼 면적이 bbox 면적의 BOX_AREA_RATIO 넘게 차지하면 상자(삼각형
    화살촉은 이 비율이 한참 낮음 — 기하로 가르니 생성기 수치에 안 묶인다)."""
    kinds = [it[0] for it in d["items"]]
    if kinds == ["re"]:
        return True
    if len(kinds) < 3 or any(k not in ("l", "c") for k in kinds):
        return False
    items = d["items"]
    p0, pn = _item_start(items[0]), _item_end(items[-1])
    if abs(p0.x - pn.x) > POINT_MERGE_TOL * 4 or abs(p0.y - pn.y) > POINT_MERGE_TOL * 4:
        return False  # 열린 경로(연결선)는 상자가 아님
    bbox_area = r.width * r.height
    if bbox_area <= 0:
        return False
    return _shoelace_area(_closed_poly_points(items)) / bbox_area > BOX_AREA_RATIO


def _box_scale(boxes):
    """영역 안 상자들의 짧은 변 중앙값(pt) — 화살촉·쉐브론·라벨 문턱을 이 값에 상대적으로 스케일한다."""
    dims = sorted(min(r.width, r.height) for r in boxes if r.width > 0 and r.height > 0)
    if not dims:
        return _DEFAULT_SCALE
    return dims[len(dims) // 2]


def _chevron_apex(d, max_diag):
    """열린 쉐브론(화살촉 — 두 짧은 선분이 한 점(꼭짓점)에서 만남, 채움 없음, 상자보다 훨씬 작음) 판정 →
    꼭짓점(apex) 또는 None. 채운 작은 다각형 화살촉만 보던 것을 넓힘."""
    items = [it for it in d["items"] if it[0] == "l"]
    if len(items) != 2 or d.get("fill") is not None:
        return None
    r = d["rect"]
    if max(r.width, r.height) > max_diag or max(r.width, r.height) < 2:
        return None
    pts = [items[0][1], items[0][2], items[1][1], items[1][2]]
    tol = POINT_MERGE_TOL * 3
    for i in (0, 1):
        for j in (2, 3):
            if math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) < tol:
                a, b = pts[1 - i], pts[5 - j]  # 두 팔의 끝(꼭짓점 반대쪽)
                va, vb = (a.x - pts[i].x, a.y - pts[i].y), (b.x - pts[i].x, b.y - pts[i].y)
                la, lb = math.hypot(*va), math.hypot(*vb)
                if min(la, lb) < 1e-6 or max(la, lb) / min(la, lb) > 1.6:  # 팔 길이가 비슷해야(표 모서리·눈금 접합 배제)
                    return None
                ang = math.degrees(math.acos(max(-1.0, min(1.0, (va[0] * vb[0] + va[1] * vb[1]) / (la * lb)))))
                return pts[i] if 15 <= ang <= 100 else None
    return None


def _triangle_apex(p0, p1, p2):
    """삼각형 세 꼭짓점 중 **내각이 가장 작은(가장 뾰족한) 꼭짓점** = 화살촉 끝(apex). 변 길이로 가르면(가장
    긴 변의 반대쪽) 폭이 넓은 화살촉에선 맞아도 뾰족한(좁은 각) 화살촉에선 밑변이 가장 짧아져 틀린다 — 각도로
    가르면 밑변·옆변 비율에 안 묶인다."""

    def angle_at(b, a, c):
        v1, v2 = (a.x - b.x, a.y - b.y), (c.x - b.x, c.y - b.y)
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return math.pi
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        return math.acos(cos)

    pts = (p0, p1, p2)
    angles = [angle_at(p0, p1, p2), angle_at(p1, p0, p2), angle_at(p2, p0, p1)]
    return pts[angles.index(min(angles))]


def _filled_arrow_apex(d):
    """화살촉으로 분류된 채운 작은 다각형(보통 삼각형)의 뾰족한 끝(apex) — 꼭짓점이 정확히 3개일 때만(그 밖엔
    None, 호출부가 bbox 중심으로 대체). bbox 중심은 밑변 쪽으로 치우쳐(연결선 끝점보다 뒤쪽) 방향 판정에
    쓰면 안 맞는다(실측, flow_mixed_vector_style 디버그로 찾음) — apex는 늘 연결선이 나아가는 쪽에 있다."""
    pts = []
    for it in d["items"]:
        if it[0] == "l":
            pts.extend([it[1], it[2]])
    uniq = []
    for p in pts:
        if not uniq or math.hypot(p.x - uniq[-1].x, p.y - uniq[-1].y) > POINT_MERGE_TOL:
            uniq.append(p)
    if len(uniq) > 1 and math.hypot(uniq[0].x - uniq[-1].x, uniq[0].y - uniq[-1].y) < POINT_MERGE_TOL:
        uniq = uniq[:-1]
    if len(uniq) != 3:
        return None
    return _triangle_apex(*uniq)


def _rect_dist(r, x, y):
    return math.hypot(max(r.x0 - x, 0, x - r.x1), max(r.y0 - y, 0, y - r.y1))


def _box_name(r, words, label_near, boxes=()):
    """상자 r의 이름 — 안의 글자 토큰을 읽는 순서(위→아래, 왼쪽→오른쪽)로 이어 붙인다. 안이 비어 있으면
    테두리 아래·옆 label_near(pt) 안의 가장 가까운 글자줄로 대체(실제 도식 관례 — 라벨이 상자 밖에 있는 스타일).
    다른 상자에 더 가깝거나 다른 상자 안에 있는 글자는 이 상자 이름으로 안 씀."""
    toks = sorted((w for w in words if r.contains(((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))), key=lambda w: (round(w[1], 1), w[0]))
    name = " ".join(w[4] for w in toks).strip()
    if name:
        return name
    cands = []
    for w in words:
        wx0, wy0, wx1, wy1 = w[:4]
        wcx, wcy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        if r.contains((wcx, wcy)):
            continue
        if any(o is not r and _rect_dist(o, wcx, wcy) < _rect_dist(r, wcx, wcy) for o in boxes):
            continue
        below = wy0 >= r.y1 - 1 and (wy0 - r.y1) <= label_near and wx1 >= r.x0 - label_near and wx0 <= r.x1 + label_near
        gap = min(abs(wx0 - r.x1), abs(wx1 - r.x0))
        beside = (wx0 >= r.x1 - 1 or wx1 <= r.x0 + 1) and gap <= label_near and wy1 >= r.y0 - label_near and wy0 <= r.y1 + label_near
        if below or beside:
            dist = (wy0 - r.y1) if below else gap
            cands.append((dist, round(wy0, 1), wx0, w))
    if not cands:
        return ""
    cands.sort()
    near_y = cands[0][1]
    line_toks = sorted((c[3] for c in cands if abs(c[1] - near_y) < 3), key=lambda c: c[0])
    return " ".join(w[4] for w in line_toks).strip()


def _best_head(pt, outward, heads, head_near):
    """pt(선분 끝점)에서 head_near(pt) 안, outward(바깥쪽 단위 벡터) 방향(코사인 0.3 이상 — 완전히 반대·수직은
    제외)에 있는 화살촉 중 가장 가까운 것 → (거리, (x,y)) 또는 (None, None). 상자 모서리에 여러 연결선이 모이면
    거리만으론 남의 화살촉을 집는다(실측, flow_mixed_vector_style 디버그) — 방향까지 맞아야 후보로 본다."""
    best = None
    for h in heads:
        vx, vy = h[0] - pt.x, h[1] - pt.y
        dist = math.hypot(vx, vy)
        if dist >= head_near:
            continue
        cos = (vx * outward[0] + vy * outward[1]) / dist if dist > 1e-6 else 1.0
        if cos < 0.3:
            continue
        if best is None or dist < best[0]:
            best = (dist, h)
    return best if best else (None, None)


def _nearest_box(pt, boxes, pad):
    for r in boxes:
        if (r + (-pad, -pad, pad, pad)).contains(pt):
            return r
    return None


def _path_endpoints(line_items):
    """선분 1개 이상(엘보 포함, 순서대로) → (tail0, head0)(방향 미정 — 화살촉으로 나중에 정함). fitz
    Shape.finish()의 기본 closePath=True는 마지막 점을 첫 점으로 되돌리는 '닫기' 선분을 하나 더 붙인다(단순
    직선도 예외 없음, 실측 — selftest 참고) — 마지막 선분의 끝점이 첫 선분의 시작점과 거의 같으면(POINT_MERGE_TOL)
    그 닫기 선분을 떼어내고 나머지의 첫 점·마지막 점을 쓴다. 실제로 열린 경로(closePath=False로 그린 연결선)는
    이 조건이 안 걸려 그대로 첫·마지막 점을 쓴다."""
    items = list(line_items)
    if len(items) > 1:
        p0, pn = items[0][1], items[-1][2]
        if abs(p0.x - pn.x) < POINT_MERGE_TOL and abs(p0.y - pn.y) < POINT_MERGE_TOL:
            items = items[:-1]
    if not items:
        return None
    return items[0][1], items[-1][2]


def _unit(p, q):
    dx, dy = p[0] - q[0], p[1] - q[1]
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d


def _path_outward_dirs(line_items):
    """_path_endpoints와 같은 닫기-선분 제거 뒤, 양 끝에서 **바깥쪽(경로를 계속 그으면 나아갈 방향)** 단위
    벡터 — p1쪽은 경로를 거슬러(뒤로), p2쪽은 경로를 따라(앞으로). 화살촉이 "이 끝에 붙어 있다"고 보려면
    화살촉이 거리만 가까운 게 아니라 이 방향에 있어야 한다(상자 모서리에 여러 연결선이 모이면 거리만으론
    남의 화살촉을 집는다 — 실측, flow_mixed_vector_style 디버그로 찾음)."""
    items = list(line_items)
    if len(items) > 1:
        p0, pn = items[0][1], items[-1][2]
        if abs(p0.x - pn.x) < POINT_MERGE_TOL and abs(p0.y - pn.y) < POINT_MERGE_TOL:
            items = items[:-1]
    if not items:
        return None
    p1, p1n = items[0][1], items[0][2]
    pm, p2 = items[-1][1], items[-1][2]
    back1 = _unit((p1.x, p1.y), (p1n.x, p1n.y))
    fwd2 = _unit((p2.x, p2.y), (pm.x, pm.y))
    return back1, fwd2


def vector_edges_from_page(page, bbox):
    """page(fitz.Page)·bbox(fitz.Rect 호환 4값 — 보통 vector_regions.py vector_regions()가 고른 그림 영역) 안의
    get_drawings()만 다시 훑어 edges[{from,to,label}]를 돌려준다(VLM 없음, 결정적). bbox 밖 상자·선은 안 봄.
    화살촉이 없는 연결선은 버리고(읽는 순서 대체 없음), 영역에 이름 붙은 상자가 2개 미만이거나 화살촉이 하나도
    없으면 빈 목록([])을 돌려준다(표·폼·축차트 오탐 방지)."""
    import fitz

    r_bbox = fitz.Rect(bbox)
    words = [w for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(r_bbox)]
    boxes, others = [], []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        rr = r if not r.is_empty else r + (-1, -1, 1, 1)  # vector_regions.py _near_groups와 같은 수(수평·수직 순수 직선은
        if not rr.intersects(r_bbox):  # 폭·높이가 정확히 0 → "빈 사각형"이라 intersects()가 늘 False)
            continue
        if _is_box(d, r):
            boxes.append(r)
        else:
            others.append((d, r))

    scale = _box_scale(boxes)
    arrow_max_area = max(30.0, 0.12 * scale * scale)  # 채운 작은 다각형 화살촉 — bbox 면적 상한
    chevron_max_diag = max(10.0, 0.5 * scale)  # 열린 쉐브론 화살촉 — bbox 대각 상한
    head_near = max(8.0, 0.3 * scale)  # 선분 끝점 ↔ 화살촉 위치 거리 상한
    box_pad = max(6.0, 0.25 * scale)  # 끝점이 상자 테두리에 딱 안 붙어도 붙은 것으로 볼 여유
    label_near = max(10.0, 0.6 * scale)  # 상자 밖 라벨 글자 찾는 거리 상한

    heads, polylines = [], []
    for d, r in others:
        kinds = [it[0] for it in d["items"]]
        if (
            d.get("fill") is not None
            and "re" not in kinds
            and kinds
            and all(k in ("l", "c") for k in kinds)
            and r.width * r.height < arrow_max_area
        ):
            apex = _filled_arrow_apex(d)  # 채운 작은 다각형 화살촉 — 뾰족한 끝(없으면 bbox 중심)
            heads.append((apex.x, apex.y) if apex else ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
            continue
        apex = _chevron_apex(d, chevron_max_diag)
        if apex is not None:
            heads.append((apex.x, apex.y))  # 열린 쉐브론 화살촉
            continue
        line_items = [it for it in d["items"] if it[0] == "l"]
        if line_items:
            polylines.append(line_items)

    box_names = [(_box_name(r, words, label_near, boxes), r) for r in boxes]
    if sum(1 for n, _ in box_names if n) < 2 or not heads:
        return []  # 영역 보호장치 — 이름 붙은 상자 2개 미만 또는 화살촉 전혀 없음(표·폼·축차트류)

    edges = []
    for line_items in polylines:
        ends = _path_endpoints(line_items)
        if ends is None:
            continue
        p1, p2 = ends
        dirs = _path_outward_dirs(line_items)
        back1, fwd2 = dirs if dirs else ((0.0, 0.0), (0.0, 0.0))
        # 상자 모서리에 여러 연결선이 모이면 거리만으로는 남의 화살촉을 집을 수 있다(실측, flow_mixed_vector_style
        # 디버그) — 화살촉은 **이 끝에서 경로가 나아가는 방향**(바깥쪽)에 있어야 후보로 본다(코사인 0.3 이상).
        # 대각선 화살표 두 개가 같은 상자의 같은 변 근처에서 만나면(이 끝·저 끝 둘 다 "화살촉 있음"으로 걸릴 수
        # 있음 — selftest의 삼각 사례) 있다/없다가 아니라 **어느 쪽이 화살촉에 더 가까운가**로 가른다.
        d1, h1 = _best_head(p1, back1, heads, head_near)
        d2, h2 = _best_head(p2, fwd2, heads, head_near)
        if d1 is None and d2 is None:
            continue  # 화살촉이 이 선분 어느 끝에도 안 붙어 있음 — 읽는 순서 대체 없이 버린다
        tail_pt, head_pt, head_xy = (p1, p2, h2) if (d2 is not None and (d1 is None or d2 <= d1)) else (p2, p1, h1)
        a = _nearest_box(tail_pt, boxes, box_pad)
        # head 쪽 상자는 먼저 선분 끝점으로 찾고(기존 동작 — 채운 삼각형은 선이 끝나는 자리가 이미 상자 턱밑),
        # 그 결과가 없거나 tail과 같은 상자(자기 자신 — 상자 사이 틈이 좁아 tail 쪽 여유가 head 끝점까지 번진
        # 경우)면 **화살촉 자체 위치**로 다시 찾는다(연결선이 상자 테두리 앞에서 뜨는 스타일 — gap). 둘 중
        # 하나만 맞아도 되니 생성기 특정 수치에 묶이지 않는다.
        b = _nearest_box(head_pt, boxes, box_pad)
        if (b is None or b == a) and head_xy:
            b2 = _nearest_box(head_xy, boxes, box_pad)
            if b2 is not None and b2 != a:
                b = b2
        if a is None or b is None or a == b:
            continue
        na = next(n for n, r in box_names if r == a)
        nb = next(n for n, r in box_names if r == b)
        if na and nb and na != nb:
            edges.append({"from": na, "to": nb, "label": None})
    seen, out = set(), []
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# ── 텍스트 층 화살표 글자(①) ─────────────────────────────────────────────
_ARROW_FWD = ("→", "->", "=>", "↓", "⇒")  # 왼쪽 토큰 → 오른쪽 토큰
_ARROW_BACK = ("←", "<-", "↑", "⇐")  # 오른쪽 토큰 → 왼쪽 토큰(역방향)
_ARROW_RE = re.compile("(" + "|".join(re.escape(a) for a in _ARROW_FWD + _ARROW_BACK) + ")")


def glyph_edges(text):
    """줄마다 화살표 글자(→ ← ↑ ↓ -> <- => ⇐)로 이어진 노드 이름 → edges[{from,to,label}](결정적, 모델 호출
    없음). 한 줄에 화살표가 여러 번(사슬, "A -> B -> C")이면 이어 붙여 edge마다 하나씩. ←·<-·↑·⇐ 는 역방향
    (오른쪽 토큰이 from)."""
    out = []
    for line in (text or "").splitlines():
        if not _ARROW_RE.search(line):
            continue
        parts = _ARROW_RE.split(line)
        if len(parts) < 3:
            continue
        nodes = [parts[0].strip()]
        arrows = []
        for i in range(1, len(parts), 2):
            arrows.append(parts[i])
            nodes.append(parts[i + 1].strip())
        for i, arr in enumerate(arrows):
            a, b = nodes[i], nodes[i + 1]
            if not a or not b:
                continue
            if arr in _ARROW_BACK:
                a, b = b, a
            out.append({"from": a, "to": b, "label": None})
    return out


# ── 소스 합치기(pptx_xml > vector > glyph > vlm) ────────────────────────
def norm_node(s):
    """노드 이름 정규화(공개 — evaluation/diagram_edges_score.py도 '같은 노드인가' 판정에 재사용) — 공백 정리·
    기호 정규화(canon_symbols)·소문자. 저장되는 edge의 from·to 글자 자체는 그대로(원문 보존), 이 정규화는 비교에만."""
    return re.sub(r"\s+", " ", canon_symbols(str(s or ""))).strip().lower()


def merge_edges(sources):
    """sources = [(이름, edges), ...] 우선순위 순(앞이 우선). 중복 제거는 **정규화한 무방향 (from,to) 짝**
    기준 — 같은 상자 짝이 여러 소스에 있으면(방향이 반대라도) 먼저 나온(우선순위 높은) 소스가 방향까지 이긴다
    (방향 키로만 거르면 역방향 VLM edge가 결정적 edge 옆에 살아남는다).
    → (합친 edges, 실제로 기여한 소스 이름 목록 — 우선순위 순, 이미 다른 소스가 다 차지해 하나도 못 넣은 소스는
    빠진다)."""
    chosen, order, used = {}, [], []
    for name, es in sources:
        added = False
        for e in es or []:
            frm, to = e.get("from"), e.get("to")
            if not frm or not to:
                continue
            na, nb = norm_node(frm), norm_node(to)
            if na == nb:
                continue
            key = frozenset((na, nb))
            if key in chosen:
                continue
            chosen[key] = e
            order.append(key)
            added = True
        if added:
            used.append(name)
    return [chosen[k] for k in order], used
