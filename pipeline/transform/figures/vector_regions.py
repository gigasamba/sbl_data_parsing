"""벡터 도식 영역 찾기(글자는 드래그되지만 도형·화살표는 글자에 없음), 규칙 기반·VLM 없음.
그림 신호: 곡선(원·타원)·사선·작은 채운 다각형(화살촉)·채운 사각형 여러 개(막대). 표 신호: 축 정렬 선·빈 사각형만(격자) → 제외.
"상자(테두리만)+직선 연결"만의 흐름도는 위 신호가 전부 0이라 표 격자와 똑같이 보인다 — 글자 든 상자 ≥3개 + 상자들이
직선으로 ≥3개짜리 사슬(연결 요소)을 이루고 + 상자가 빈틈없이 격자로 맞물리지 않으면(표는 맞물림) 그림으로 본다. 폭이 0인
순수 직선은 intersects()가 "빈 사각형"으로 보고 아무것과도 안 묶으므로, 선분만 살짝 부풀려 한 번 더 묶어 본다.
라벨상자→값상자를 짧은 선 하나로만 잇는 서식(form) 표는 상자쌍 수(≥2)만 보면 쉽게 걸린다(각 행이 독립
쌍이라 쌍 수는 행 수만큼 늘지만 사슬은 길이 2에서 끝남) — _chain_len이 "서로 분리된 여러 쌍"과 "상자를 타고
이어지는 흐름"을 구분한다(최소 연결 요소 크기 3)."""


def _box_has_text(r, words):
    return any(r.contains(((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)) for w in words)


def _chain_len(boxes, lines):
    """선분으로 이어진 상자들의 가장 큰 연결 요소 크기(Union-Find) — 표 칸이 테두리를 공유하는 것과 다름(표는 보통
    상자 신호 자체가 없음: 칸을 한 drawing에 몰아 그리거나 선만으로 그려 is_box 조건에 안 걸림, 혹시 걸려도 아래
    _tiles_as_grid가 한 번 더 막음). 라벨→값처럼 서로 분리된 1:1 쌍이 여러 개여도 사슬은 길이 2에서 끝나
    흐름도(상자 ≥3개가 한 줄기로 이어짐)와 구분된다."""
    pads = [r + (-3, -3, 3, 3) for r in boxes]
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    touched = set()
    for p1, p2 in lines:
        a = next((i for i, r in enumerate(pads) if r.contains(p1)), None)
        b = next((i for i, r in enumerate(pads) if r.contains(p2)), None)
        if a is not None and b is not None and a != b:
            touched.add(a)
            touched.add(b)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    if not touched:
        return 0
    counts = {}
    for i in touched:
        root = find(i)
        counts[root] = counts.get(root, 0) + 1
    return max(counts.values())


def _tiles_as_grid(boxes):
    """표 칸은 빈틈없이 맞물려 상자 면적 합이 전체 테두리 면적에 거의 맞먹는다 — 도식은 상자 사이에 선 그릴 틈이 있다.
    ponytail: 면적비 하나로만 가름(실제 표 모양 분석 아님) — 문턱(0.75) 밖 반례가 쌓이면 행·열 공유 경계 검사로 올릴 것."""
    if len(boxes) < 2:
        return False
    bbox = boxes[0]
    for r in boxes[1:]:
        bbox = bbox | r
    area = bbox.width * bbox.height
    if area <= 0:
        return False
    return sum(r.width * r.height for r in boxes) / area > 0.75


def _near_groups(entries, pad=12):
    """가까운 항목 병합(기본 vector_regions의 groups 병합과 같은 규칙) — 병합 판정은 it['cr'], bbox 합산은 it['r']
    (화살촉 없는 순수 직선은 cr만 살짝 부풀려 판정만 통과시키고 실제 bbox는 원래 선분 그대로 쓴다)."""
    import fitz

    groups = []
    for it in entries:
        g = {"r": fitz.Rect(it["r"]), "cr": fitz.Rect(it["cr"]), "items": [it]}
        merged = True
        while merged:
            merged = False
            for o in groups:
                if (o["cr"] + (-pad, -pad, pad, pad)).intersects(g["cr"]):
                    g["r"] |= o["r"]
                    g["cr"] |= o["cr"]
                    g["items"] += o["items"]
                    groups.remove(o)
                    merged = True
                    break
        groups.append(g)
    return groups


def vector_regions(pg, min_items=5):
    """쪽의 벡터 도형을 가까운 것끼리 묶어 '그림에 가까운' 영역만 고른다 → [{bbox, items, signals, words, text_layer}]."""
    import fitz

    area = pg.rect.width * pg.rect.height
    all_words = pg.get_text("words")
    items = []
    for d in pg.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.width * r.height > 0.6 * area or (r.width < 0.5 and r.height < 0.5):
            continue
        kinds = [it[0] for it in d["items"]]  # 도형 하나에 선분 여러 개가 묶일 수 있음 → 선분 단위로 셈
        diag = sum(1 for it in d["items"] if it[0] == "l" and abs(it[1].x - it[2].x) > 1.5 and abs(it[1].y - it[2].y) > 1.5)
        curve = sum(1 for k in kinds if k == "c")
        filled = d.get("fill") is not None
        lines = [(it[1], it[2]) for it in d["items"] if it[0] == "l"]  # 직선 연결 검사용 양끝점
        # 'l' 세그먼트 4개로 닫은 채운 사각형(엑셀·파워포인트 내보내기 차트)도 'bar'로 센다 — 're'만 보면 이런 차트를 놓친다.
        # 채워진 것만(선 색만인 흐름도 상자는 box_diagram 몫).
        closed_quad = (
            filled and kinds == ["l", "l", "l", "l"] and r.width * r.height >= 120 and lines and lines[-1][1].distance_to(lines[0][0]) < 1.0
        )
        items.append(
            {
                "r": r,
                "n": len(kinds),
                "diag": diag,
                "curve": curve,
                "arrow": int(filled and r.width * r.height < 120 and "re" not in kinds),
                "bar": (sum(1 for k in kinds if k == "re") if filled and r.width * r.height >= 120 else 0) + int(closed_quad),
                "is_box": kinds == ["re"],
                "lines": lines,
            }
        )
    groups = []  # 가까운 도형 묶기(12pt 여유) — 단순 반복 병합(기존 그대로, 손 안 댐)
    for it in items:
        g = {"r": fitz.Rect(it["r"]), "items": [it]}
        merged = True
        while merged:
            merged = False
            for o in groups:
                if (o["r"] + (-12, -12, 12, 12)).intersects(g["r"]):
                    g["r"] |= o["r"]
                    g["items"] += o["items"]
                    groups.remove(o)
                    merged = True
                    break
        groups.append(g)
    out = []
    for g in groups:
        its = g["items"]
        n = sum(i["n"] for i in its)
        sig = sum(i["curve"] for i in its) + sum(i["diag"] for i in its) + 2 * sum(i["arrow"] for i in its)
        bars = sum(i["bar"] for i in its)
        grid = sig == 0 and bars < 3  # 축 정렬 선·빈 사각형만 = 표 격자·밑줄
        box_diagram = False
        if grid and n >= min_items:  # 격자로 보일 때만 흐름도인지 확인
            boxes = [i["r"] for i in its if i["is_box"]]
            lines = [ln for i in its if not i["is_box"] for ln in i["lines"]]
            boxed_text = sum(1 for r in boxes if _box_has_text(r, all_words))
            box_diagram = boxed_text >= 3 and _chain_len(boxes, lines) >= 3 and not _tiles_as_grid(boxes)
        if n >= min_items and (not grid or box_diagram) and (sig >= 3 or bars >= 3 or box_diagram):
            r = g["r"] + (-14, -14, 14, 18)
            r &= pg.rect
            words = [w for w in all_words if fitz.Rect(w[:4]).intersects(r)]
            signals = {"curve_diag_arrow": sig, "bars": bars}
            if box_diagram:
                signals["box_diagram"] = True
            out.append(
                {
                    "bbox": [round(v, 1) for v in r],
                    "items": n,
                    "signals": signals,
                    "words": len(words),
                    "text_layer": " ".join(w[4] for w in words),
                }
            )
    # 둘째 묶기 — 화살촉 없는 순수 직선이 상자를 안 이어 위에서
    entries = [dict(it, cr=(it["r"] if not it["r"].is_empty else it["r"] + (-1, -1, 1, 1))) for it in items]
    for g in _near_groups(entries):  # min_items에도 못 미친 묶음을 선분만 살짝 부풀려 다시 묶어 본다
        its = g["items"]
        n = sum(i["n"] for i in its)
        sig = sum(i["curve"] for i in its) + sum(i["diag"] for i in its) + 2 * sum(i["arrow"] for i in its)
        bars = sum(i["bar"] for i in its)
        if n < min_items or sig != 0 or bars >= 3:  # 격자 모양(=기존 path가 이미 다루거나 다룰 자격이 없는 쪽)만
            continue
        boxes = [i["r"] for i in its if i["is_box"]]
        lines = [ln for i in its if not i["is_box"] for ln in i["lines"]]
        boxed_text = sum(1 for r in boxes if _box_has_text(r, all_words))
        if boxed_text < 3 or _chain_len(boxes, lines) < 3 or _tiles_as_grid(boxes):
            continue
        r = g["r"] + (-14, -14, 14, 18)
        r &= pg.rect
        if any(fitz.Rect(o["bbox"]).intersects(r) for o in out):
            continue  # 1단계가 이미 같은 자리에 냈으면 중복 금지
        words = [w for w in all_words if fitz.Rect(w[:4]).intersects(r)]
        out.append(
            {
                "bbox": [round(v, 1) for v in r],
                "items": n,
                "signals": {"curve_diag_arrow": sig, "bars": bars, "box_diagram": True},
                "words": len(words),
                "text_layer": " ".join(w[4] for w in words),
            }
        )
    return out
