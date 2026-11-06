"""차트 값 정밀 추출 + 추세.

(a) 벡터 PDF 차트: page.get_drawings()(선·채운 사각형)+get_text("words")(눈금 글자)만으로 결정적 값 추출(VLM 없음).
    y축(가장 왼쪽 수직선)·x축(가장 아래쪽 수평선)을 찾고, y축 왼쪽의 숫자 글자(일반 숫자·%·"10^n")를 눈금으로
    최소제곱 피팅해 픽셀→값 변환을 만든다(눈금이 전부 10의 정수 거듭제곱이면 로그축). 채운 사각형(막대, 누적이면
    세그먼트별로)·꺾은선(여러 "l" 세그먼트로 이은 한 drawing)의 꼭짓점을 이 변환으로 값으로 바꾼다. 축 눈금이
    2개 미만(표·흐름도 등 숫자 눈금이 없는 그림)이면 빈 목록 — 값을 지어내지 않는다.
(b) 추세: compute_trend — 값이 있으면 상대변화 문턱으로 결정적 판정(ponytail: 단순 규칙, 실측 쌓이면 재조정).
"""

import math
import re
from pathlib import Path

POW10_RE = re.compile(r"^10\s*\^\s*(-?\d+)$")  # "^" 글자가 꼭 있어야(없으면 "100"을 10^0=1로 잘못 읽음)
_CURRENCY_CHARS = "₩$€£¥"
_SUFFIX_MULT = {"k": 1e3, "m": 1e6, "b": 1e9}
_SUFFIX_RE = re.compile(r"^(-?[\d,]+\.?\d*)\s*([kKmMbB])$")
_SCI_RE = re.compile(r"^-?\d+\.?\d*[eE][+-]?\d+$")
_PLAIN_RE = re.compile(r"^-?[\d,]+\.?\d*$")


def _to_number(s):
    """숫자 글자 → float, 못 읽으면 None. 지원 확장: 쉼표(1,200)·%(45%)·통화 기호
    (₩1,200·$45)·K/M/B 단위(1.2K·3M)·과학적 표기(1e6)·"10^n"(눈금 전용 표기)."""
    s = (s or "").strip()
    if not s:
        return None
    m = POW10_RE.match(s)
    if m:
        return 10.0 ** int(m.group(1))
    core = s
    for ch in _CURRENCY_CHARS:
        core = core.replace(ch, "")
    core = core.strip().rstrip("%").strip()
    if not core:
        return None
    m = _SUFFIX_RE.match(core)
    if m:
        try:
            return float(m.group(1).replace(",", "")) * _SUFFIX_MULT[m.group(2).lower()]
        except ValueError:
            return None
    if _SCI_RE.match(core):
        try:
            return float(core)
        except ValueError:
            return None
    if _PLAIN_RE.match(core):
        try:
            return float(core.replace(",", ""))
        except ValueError:
            return None
    return None


def _fmt_num(v):
    """추세 basis 표시용(정수면 소수점 없이)."""
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _is_log_axis(ticks_px_order):
    """눈금(픽셀 순서대로, _y_ticks가 이미 픽셀 오름차순 정렬해 넘김) → 로그축인지. 문자 그대로
    "10^n"이 아니어도(예: 2·20·200·2000) 연속 값의 비율이 거의 일정(기하수열)하면 로그축으로 본다(일반화,
    ratio>=3개 있을 때만 — 2개짜리는 비율 하나로는 기하/선형을 가를 수 없어 10^n 리터럴 폴백만)."""
    vals = [v for _, v in ticks_px_order]
    if len(vals) < 2 or any(v <= 0 for v in vals):
        return False
    if len(vals) >= 3:
        ratios = [vals[i + 1] / vals[i] for i in range(len(vals) - 1) if vals[i] != 0]
        if len(ratios) >= 2 and all(r > 0 for r in ratios):
            rmean = sum(ratios) / len(ratios)
            if rmean > 0 and abs(rmean - 1) > 0.05 and all(abs(r - rmean) / rmean < 0.08 for r in ratios):
                return True
    return all(abs(math.log10(v) - round(math.log10(v))) < 0.05 for v in vals) and len({round(math.log10(v)) for v in vals}) >= 2


# ── (a) 벡터 PDF: 눈금 피팅 ──────────────────────────────────────────────
def _fit_axis(ticks):
    """[(pixel, value)](>=2) → (slope, intercept, log_axis) 또는 None(피팅 불가, 모든 픽셀이 같음).
    value = slope*pixel + intercept(선형) 또는 log10(value) = slope*pixel + intercept(로그).
    로그축 판정은 _is_log_axis (10^n 리터럴만이 아니라 일반 기하수열도 인식)."""
    raw = sorted(((p, v) for p, v in ticks), key=lambda t: t[0])  # 픽셀 오름차순(_is_log_axis가 기하수열 비율을 보려면 순서가 필요)
    log_axis = _is_log_axis(raw)
    vals = [v for _, v in raw]
    xs = [p for p, _ in raw]
    ys = [math.log10(v) for v in vals] if log_axis else vals
    n = len(xs)
    xm, ym = sum(xs) / n, sum(ys) / n
    denom = sum((x - xm) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / denom
    intercept = ym - slope * xm
    return slope, intercept, log_axis


def _px_to_value(px, fit):
    slope, intercept, log_axis = fit
    y = slope * px + intercept
    return 10**y if log_axis else y


def _value_for_zero(fit):
    """value==0이 되는 픽셀(음수 막대 판별용) — 로그축·slope 0은 None(0이 없거나 못 품)."""
    slope, intercept, log_axis = fit
    if log_axis or slope == 0:
        return None
    return (0 - intercept) / slope


def _touches(rect, region, pad=0.5):
    """region.intersects(rect)는 rect가 폭·높이 0(순수 수평·수직선, vector.py의 같은 함정)이면 늘 False —
    그런 '빈' rect는 살짝 부풀려서 검사(vector.py의 cr 보정과 같은 관례)."""
    if rect.is_empty:
        rect = rect + (-pad, -pad, pad, pad)
    return region.intersects(rect)


def _lines(drawings, region):
    """채움 없는 'l' 세그먼트만(stroke) — (p1, p2, 길이, 수평?/수직?) 목록, region에 걸치는 것만."""
    out = []
    for d in drawings:
        if d.get("fill") is not None:
            continue
        for it in d.get("items", ()):
            if it[0] != "l":
                continue
            p1, p2 = it[1], it[2]
            if not (region.contains(p1) or region.contains(p2)):
                continue
            out.append((p1, p2))
    return out


def _find_axes(drawings, region):
    """y축(가장 왼쪽의 충분히 긴 수직선)·x축(가장 아래쪽의 충분히 긴 수평선). 못 찾으면 (None, None)."""
    verts, horiz = [], []
    for p1, p2 in _lines(drawings, region):
        dx, dy = abs(p1.x - p2.x), abs(p1.y - p2.y)
        if dx < 1.5 and dy > 15:
            verts.append((min(p1.x, p2.x), min(p1.y, p2.y), max(p1.y, p2.y)))
        elif dy < 1.5 and dx > 15:
            horiz.append((max(p1.y, p2.y), min(p1.x, p2.x), max(p1.x, p2.x)))
    y_axis = min(verts, key=lambda t: t[0]) if verts else None  # (x, y_top, y_bot)
    x_axis = max(horiz, key=lambda t: t[0]) if horiz else None  # (y, x_left, x_right)
    return y_axis, x_axis


def _infer_axis_from_labels(words, vertical=True):
    """스파인(축 선)이 전혀 없는 차트(엑셀·파워포인트에서 그대로 내보낸 PDF 등) — 숫자 글자가
    세로로(vertical=True, y축) 또는 가로로(x축 폴백은 아직 안 씀, 자리만) 비슷한 위치에 늘어서 있고 ①값이
    단조(증가 또는 감소) ②픽셀 간격이 고르면(변동 35% 안) 진짜 눈금으로 보고 (ax, lo, hi) 근사를 돌려준다.
    표의 숫자 열은 보통 값이 들쭉날쭉하거나(비단조) 행 간격이 본문처럼 고르지 않아 자연히 걸러진다(완전한
    방어는 아님 — ponytail: 우연히 단조·등간격인 표 열은 못 거름, 반례 쌓이면 재조정).
    못 찾으면 None."""
    cands = []
    for w in words:
        x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
        v = _to_number(txt)
        if v is None:
            continue
        cands.append((x0, x1, (y0 + y1) / 2, v))
    if len(cands) < 3:
        return None
    # 오른쪽 끝(x1)으로 묶는다 — 실제 눈금 숫자는 보통 오른쪽 정렬(자릿수가 다르면 왼쪽 끝 x0은 들쭉날쭉해도
    # 오른쪽 끝은 가지런함, 실측에서 왼쪽 정렬 가정이 자릿수 다른 눈금에서 깨짐을 확인).
    cands.sort(key=lambda c: c[1])
    best = None
    i = 0
    while i < len(cands):
        j = i
        group = [cands[i]]
        while j + 1 < len(cands) and abs(cands[j + 1][1] - cands[i][1]) < 4:
            j += 1
            group.append(cands[j])
        if len(group) >= 3:
            ys = sorted(g[2] for g in group)
            gaps = [ys[k + 1] - ys[k] for k in range(len(ys) - 1)]
            gmean = sum(gaps) / len(gaps) if gaps else 0
            if gmean > 2 and all(abs(g - gmean) / gmean < 0.35 for g in gaps):
                by_y = sorted(group, key=lambda g: g[2])
                vals = [g[3] for g in by_y]
                monotonic = all(vals[k] <= vals[k + 1] for k in range(len(vals) - 1)) or all(
                    vals[k] >= vals[k + 1] for k in range(len(vals) - 1)
                )
                if monotonic and len(set(vals)) >= 2 and (best is None or len(group) > len(best)):
                    best = group
        i = j + 1
    if best is None:
        return None
    ax = max(g[1] for g in best) + 2  # 라벨 오른쪽 끝 바로 옆 — _y_ticks의 "ax-2 안쪽" 기준과 맞물리게
    ys = [g[2] for g in best]
    return ax, min(ys) - 10, max(ys) + 10


def _y_ticks(words, y_axis):
    """y축 왼쪽(가로 60pt 안)·축의 세로 범위(±8 여유) 안의 숫자 글자 → [(픽셀중심y, 값)] 중복 제거(가까운 픽셀 1개만)."""
    if y_axis is None:
        return []
    ax, ytop, ybot = y_axis
    out = []
    for w in words:
        x0, y0, _x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
        if not (ax - 90 <= x0 <= ax - 2):  # 글자 시작이 축보다 왼쪽(90pt 안)이어야(폭이 넓은 라벨도 걸리게 x1이 아니라 x0 기준)
            continue
        yc = (y0 + y1) / 2
        if yc < ytop - 8 or yc > ybot + 8:
            continue
        v = _to_number(txt)
        if v is not None:
            out.append((yc, v))
    out.sort()
    merged = []
    for yc, v in out:
        if merged and abs(merged[-1][0] - yc) < 3:
            continue
        merged.append((yc, v))
    return merged


def _x_ticks(words, x_axis, region=None, y_axis=None):
    """x축 아래(세로 20pt 안)의 글자(숫자 아니어도 됨 — 분기·연도 같은 범주 이름) → [(픽셀중심x, 글자)].
    x_axis가 없으면(스파인 없는 차트) region 하단 18%의 글자를 범주 라벨 후보로(회전된
    라벨도 bbox 중심은 대략 맞음 — 완전한 회전 보정은 아님, ponytail 한계) — y_axis(추론된 것 포함)가 있으면
    그 눈금 글자 열(x0 <= y_axis[0])은 제외한다(안 그러면 y축 맨 아래 눈금 글자가 하단 18%와 겹쳐 x 범주로
    잘못 섞여 들어감, 실측 log_axis_exported)."""
    if x_axis is not None:
        ay, xl, xr = x_axis
        out = []
        for w in words:
            x0, y0, x1, _y1, txt = w[0], w[1], w[2], w[3], w[4]
            if y0 < ay - 2 or y0 > ay + 70:  # 70pt — 세로로 회전된(rotate=90) 범주 라벨은 글자 수만큼 더 아래로 뻗음
                continue
            if x1 < xl - 10 or x0 > xr + 10:
                continue
            out.append(((x0 + x1) / 2, txt))
        out.sort()
        return out
    if region is None:
        return []
    cutoff = region.y1 - (region.y1 - region.y0) * 0.18
    y_cut = y_axis[0] if y_axis is not None else None
    out = [((w[0] + w[2]) / 2, w[4]) for w in words if w[1] >= cutoff and (y_cut is None or w[0] > y_cut)]
    out.sort()
    return out


def _nearest_label(x, labels):
    if not labels:
        return None
    return min(labels, key=lambda lv: abs(lv[0] - x))[1]


def _rect_key(r):
    return (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))


def _bar_ok(r, x_axis, region, legend_rects):
    """막대 후보 bbox 공용 필터 — 너무 작음·범례 상자(legend_rects, 위치로 x_axis 유무와 무관하게 늘 제외)·
    x축 가로 범위 밖·너무 아래는 제외. x_axis가 없으면(스파인 없는 차트) region 경계만으로(덜 엄격 — 뒤의
    공통 기준선 가드가 가짜를 추가로 거름). 범례 제외를 x_axis 유무에 기대지 않게 고침
    (스파인 없는 차트에서 범례 상자가 '누적 세그먼트'로 잘못 섞여 들어가 전체 탐지가 막히던 회귀)."""
    if r.width < 4 or r.height < 4 or r.width * r.height < 20:
        return False
    if _rect_key(r) in legend_rects:
        return False
    if x_axis is not None:
        return not (r.y0 > x_axis[0] + 30 or r.x0 < x_axis[1] - 2 or r.x1 > x_axis[2] + 2)
    return r.y1 <= region.y1 + 2


def _bars(drawings, region, x_axis, legend_rects=frozenset()):
    """채운 사각형(단일 're' 아이템짜리 drawing·같은 색 여러 막대를 한 shape로 묶은 drawing 둘 다) + 둥근 모서리
    등 're'가 아닌 닫힌 채움 경로(엑셀·파워포인트 차트가 흔히 이렇게 그림, 'c'·'l' 곡선/직선
    조합)는 drawing 전체 bbox를 막대 하나로. 범례 상자(legend_rects)·x축의 가로 범위 밖·너무 작은 사각형은 뺀다."""
    out = []
    for d in drawings:
        if d.get("fill") is None:
            continue
        items = d.get("items", ())
        got_re = False
        for it in items:
            if it[0] != "re":
                continue
            got_re = True
            r = it[1]
            if region.intersects(r) and _bar_ok(r, x_axis, region, legend_rects):
                out.append({"rect": r, "fill": tuple(round(c, 3) for c in d["fill"])})
        if not got_re and items:
            r = d["rect"]
            if region.intersects(r) and _bar_ok(r, x_axis, region, legend_rects):
                out.append({"rect": r, "fill": tuple(round(c, 3) for c in d["fill"])})
    return out


def _columns_look_like_bars(cols, tol=3):
    """여러 막대가 한 '열'로 묶였으면(_group_columns, x 구간이 겹치거나 가까움) 진짜 누적 막대인지 — 위→아래로
    세그먼트가 서로 맞닿아야(이전 세그먼트 바닥 ≈ 다음 세그먼트 위) 한다. Gantt류 수평 막대가
    x 구간이 겹쳐 한 열로 묶여도(서로 다른 행이라 y가 제각각·안 맞닿음) 누적 막대로 오인하지 않게."""
    for c in cols:
        items = sorted(c["items"], key=lambda b: b["rect"].y0)
        if len(items) < 2:
            continue
        if not all(abs(items[k]["rect"].y1 - items[k + 1]["rect"].y0) <= tol for k in range(len(items) - 1)):
            return False
    return True


def _shares_baseline(bars, tol=3):
    """단일 막대(누적 아님)들 대부분이 같은 픽셀에서 '쉬는'(resting) 모서리를 공유하는지 — Gantt류(행마다 세로 위치·가로 시작점이 제각각인 수평 막대)를 세로 막대그래프로 오인하지 않게 막는 가드.
    진짜 세로 막대그래프는 전부 같은 플롯 바닥(또는 0선)에서 자란다 — 공유 모서리가 없으면 False."""
    if len(bars) < 2:
        return True
    from collections import Counter

    edges = Counter(round(b["rect"].y0, 0) for b in bars) + Counter(round(b["rect"].y1, 0) for b in bars)
    if not edges:
        return False
    common = edges.most_common(1)[0][0]
    matching = sum(1 for b in bars if min(abs(b["rect"].y0 - common), abs(b["rect"].y1 - common)) <= tol)
    return matching / len(bars) >= 0.6


def _group_columns(bars, gap=6):
    """x 구간이 겹치거나 가까운 막대끼리 한 '열'(누적 막대 후보)로 묶음."""
    cols = []
    for b in sorted(bars, key=lambda b: b["rect"].x0):
        r = b["rect"]
        placed = False
        for c in cols:
            cx0, cx1 = c["x0"], c["x1"]
            if not (r.x1 + gap < cx0 or r.x0 - gap > cx1):
                c["items"].append(b)
                c["x0"], c["x1"] = min(cx0, r.x0), max(cx1, r.x1)
                placed = True
                break
        if not placed:
            cols.append({"x0": r.x0, "x1": r.x1, "items": [b]})
    return cols


def _legend(drawings, words, region):
    """작은 채운 사각형(범례 상자) + 바로 오른쪽 글자 → ({fill색: 이름}, {범례 상자 rect 키 집합}). 뒤엣것은
    _bars()가 범례 상자를 막대 후보에서 빼는 데 쓴다(x_axis 유무와 무관하게 늘 제외해야
    스파인 없는 차트에서 범례가 '누적 세그먼트'로 섞여 들어가지 않음)."""
    colors, rects = {}, set()
    for d in drawings:
        if d.get("fill") is None:
            continue
        items = d.get("items", ())
        if [it[0] for it in items] != ["re"]:
            continue
        r = d["rect"]
        if r.width * r.height >= 20 and r.width < 40 and r.height < 40:
            near = [w[4] for w in words if r.y0 - 4 <= (w[1] + w[3]) / 2 <= r.y1 + 4 and r.x1 - 2 <= w[0] <= r.x1 + 90]
            if near:
                colors[tuple(round(c, 3) for c in d["fill"])] = " ".join(near)
                rects.add(_rect_key(r))
    return colors, rects


def extract_vector(page, bbox):
    """fitz.Page, bbox([x0,y0,x1,y1], vector.py의 그림 영역) → ([{series,x,value,unit,label}], meta).
    눈금 숫자가 2개 미만이면 ([], {"axis": None}) — 표·흐름도는 조용히 값 0건(값을 지어내지 않음).
    도형(막대·축·선)은 bbox 그대로(vector_regions가 VLM 크롭용으로 이미 14~18pt만 여유를 둔 영역)로 자르지만,
    눈금 글자는 그보다 훨씬 넓게(축 왼쪽 100pt·위아래 20~60pt) 찾는다 — vector_regions의 bbox는 '도형'만 보고
    계산돼(get_drawings) 글자 폭·범주 라벨 위치는 모르므로, 자릿수가 긴 눈금(예: "43.2")이 14pt 여유를 넘어가면
    도형 bbox 안에서는 잘려 눈금을 못 찾던 회귀(실측 stacked_bar_hard) · x축 범주 라벨(D0·D2…)이 도형
    bbox 아래 40pt를 살짝 넘어가 아예 빠지던 회귀(실측 log_axis_exported — 스파인 없는 차트는 범주
    라벨이 도형보다 한참 아래)도 같은 이유. 폭을 넓혀도 안전한 건 _y_ticks·_x_ticks가 이미 찾아낸 축 위치
    기준으로 다시 한번 가까운지 확인하기 때문(먼 글자가 섞여 들어오지 않음)."""
    import fitz

    region = fitz.Rect(bbox)
    word_region = region + (-100, -20, 20, 60)
    drawings = [d for d in page.get_drawings() if _touches(d["rect"], region)]
    words = [w for w in page.get_text("words") if word_region.intersects(fitz.Rect(w[:4]))]
    y_axis, x_axis = _find_axes(drawings, region)
    used_fallback_axis = y_axis is None  # 스파인(축 선) 없는 "내보내기" 스타일 차트
    if y_axis is None:
        y_axis = _infer_axis_from_labels(words)
    y_ticks = _y_ticks(words, y_axis)
    if len(y_ticks) < 2:
        return [], {"axis": None}
    fit = _fit_axis(y_ticks)
    if fit is None:
        return [], {"axis": None}
    zero_px = _value_for_zero(fit)
    x_labels = _x_ticks(words, x_axis, region if x_axis is None else None, y_axis)
    if used_fallback_axis and not x_labels:
        # 스파인도 없고 범주 라벨도 없음 — 진짜 차트라는 증거가 약함(표의 세로 숫자 열 등과 구분 안 됨),
        # 값을 지어내지 않는다(과탐지 방지).
        return [], {"axis": None}
    legend, legend_rects = _legend(drawings, words, region)

    values = []
    bars = _bars(drawings, region, x_axis, legend_rects)
    anchors = [p for p in (x_axis[0] if x_axis else None, zero_px) if p is not None]  # 막대가 '쉬는' 기준선 후보(플롯 바닥·0선)
    cols0 = _group_columns(bars) if bars else []
    single_bars = [b for col in cols0 for b in col["items"] if len(col["items"]) == 1]
    if bars and ((single_bars and not _shares_baseline(single_bars)) or not _columns_look_like_bars(cols0)):
        # 공통 기준선이 없는 단일 막대들(Gantt류 수평 막대) 또는 서로 안 맞닿는 '누적'
        # 세그먼트(x 구간만 겹칠 뿐 다른 행) → 진짜 막대그래프가 아니라고 보고 막대 경로를 건너뛴다(값을 지어내지 않음).
        bars = []
    if bars:
        for col in _group_columns(bars):
            items = sorted(col["items"], key=lambda b: b["rect"].y0)  # 위→아래(누적이면 위가 맨 위 세그먼트)
            x_center = (col["x0"] + col["x1"]) / 2
            x_label = _nearest_label(x_center, x_labels) or f"{x_center:.0f}"
            for b in items:
                r = b["rect"]
                if len(items) == 1:
                    # 막대 1개(누적 아님) — 두 모서리 중 기준선(플롯 바닥 또는 0선)에 더 가까운 쪽이 '쉬는' 모서리,
                    # 반대쪽('자유' 모서리)이 값 — 축이 0부터 안 시작해도·음수 막대가 0선 아래로 뻗어도 그대로 맞음
                    # (차이 계산이 아니라 자유 모서리 1점만 변환 — 기준선이 어떤 값을 나타내는지 몰라도 된다).
                    rest_is_y0 = anchors and min(abs(r.y0 - a) for a in anchors) < min(abs(r.y1 - a) for a in anchors)
                    free_px = r.y1 if rest_is_y0 else r.y0
                    magnitude = _px_to_value(free_px, fit)
                else:
                    magnitude = abs(_px_to_value(r.y0, fit) - _px_to_value(r.y1, fit))  # 누적 세그먼트 — 두 모서리 값의 차
                series = legend.get(b["fill"])
                values.append(
                    {
                        "series": series,
                        "x": x_label,
                        "value": round(magnitude, 4),
                        "unit": None,
                        "label": x_label if series is None else f"{series} {x_label}",
                    }
                )
        return values, {
            "axis": "log" if fit[2] else "linear",
            "chart_type": "stacked_bar" if any(len(c["items"]) > 1 for c in _group_columns(bars)) else "bar",
        }

    # 막대가 없으면 꺾은선(채움 없는 'l' 체인) 후보. 축·눈금 표시·격자선을 한 shape(한 drawing)로 묶어 그린
    # PDF도 흔해(vector_regions()가 그림으로 잡으려면 12pt 안에서 뭉쳐 있어야 해서 실제로 그렇게들 그림) —
    # 그런 drawing은 항목들이 끝점→다음 시작점으로 안 이어진다(축 두 선+직각 눈금 표시가 뒤섞임, 진짜 꺾은선은
    # 한 경로로 쭉 이어짐) → 체인이 아니면 통째로 제외. 세그먼트 1개짜리(따로 그린 축·격자선)만 위치로 추가 확인.
    grid_ys = {round(x_axis[0], 1)} if x_axis else set()
    grid_ys |= {round(yc, 1) for yc, _ in y_ticks}
    for d in drawings:
        if d.get("fill") is not None:
            continue
        items = [it for it in d.get("items", ()) if it[0] == "l"]
        if not items or not _touches(d["rect"], region):
            continue
        if len(items) > 1 and not all(
            abs(items[i][2].x - items[i + 1][1].x) < 0.5 and abs(items[i][2].y - items[i + 1][1].y) < 0.5 for i in range(len(items) - 1)
        ):
            continue  # 안 이어진 묶음(축+눈금+격자선을 한 shape로 그린 경우) — 진짜 꺾은선이 아님
        if len(items) == 1:
            p1, p2 = items[0][1], items[0][2]
            if y_axis is not None and abs(p1.x - y_axis[0]) < 3 and abs(p2.x - y_axis[0]) < 3:
                continue  # y축 선 그 자체
            if abs(p1.y - p2.y) < 1.5 and any(abs(p1.y - gy) < 2 for gy in grid_ys):
                continue  # x축 선 그 자체이거나 눈금 위치의 가로 격자선(따로 그린 경우)
        path_len = sum(math.hypot(it[2].x - it[1].x, it[2].y - it[1].y) for it in items)
        if path_len < 15:
            continue
        # 다계열 꺾은선: 선 색(stroke, d["color"])을 범례 상자 색(_legend는 채움 색 기준)과
        # 맞춰 series를 채운다(범례 상자의 채움 색을 선과 같은 색으로 그리는 게 일반적인 관례).
        series = legend.get(tuple(round(c, 3) for c in (d.get("color") or ())))
        pts = [items[0][1]] + [it[2] for it in items]
        for pt in pts:
            x_label = _nearest_label(pt.x, x_labels) or f"{pt.x:.0f}"
            v = round(_px_to_value(pt.y, fit), 4)
            values.append(
                {"series": series, "x": x_label, "value": v, "unit": None, "label": x_label if series is None else f"{series} {x_label}"}
            )
    if values:
        return values, {"axis": "log" if fit[2] else "linear", "chart_type": "line"}
    return [], {"axis": "log" if fit[2] else "linear", "chart_type": None}


# ── (b) 추세 ────────────────────────────────────────────────────────────
FLAT_REL = 0.05  # ponytail: 전체 범위가 최대 절댓값의 5% 안이면 "유지" — 실측 쌓이면 재조정
PEAK_REL = 0.10  # 중간 값이 양끝보다 이만큼(최대 절댓값 대비) 더 높아야 '정점'으로 본다(잡음과 구분)
NOISE_REL = 0.15  # 전체 중 이 비율 안의 반대 방향 변화는 잡음으로 보고 단조 증가·감소 판정을 안 깨뜨림


def _as_number(val):
    """det 값(float 그대로)·VLM 값(문자열, 확신 없으면 끝에 '?') 둘 다 → float|None."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return _to_number(val.rstrip("?").strip())
    return None


def compute_trend(values):
    """값 목록(등장 순서 = x축 순서, 같은 x는 series 합산 — 누적 막대 전체 크기) → {direction,period,basis} 또는
    None(계산할 값이 2개 미만). x 키가 없으면(VLM values[{label,value,unit}]) label을 x로 쓴다."""
    if not values:
        return None
    order, totals = [], {}
    for v in values:
        x = v.get("x") or v.get("label")
        val = _as_number(v.get("value"))
        if val is None or x is None:
            continue
        if x not in totals:
            order.append(x)
            totals[x] = 0.0
        totals[x] += val
    series_vals = [totals[x] for x in order]
    if len(series_vals) < 2:
        return None
    first, last = series_vals[0], series_vals[-1]
    diffs = [b - a for a, b in zip(series_vals, series_vals[1:])]
    peak_i = max(range(len(series_vals)), key=lambda i: series_vals[i])
    scale = max(abs(v) for v in series_vals) or 1.0  # 정규화 기준(절댓값 중 최대) — 범위 자체를 여기에 비교하면
    # 순환참조라(유지 판정에 쓰는 값 범위를 범위 자신으로 나눔) 값 크기를 기준으로 삼는다.
    noise = NOISE_REL * scale
    # 1) 정점(중간, 양끝보다 뚜렷이 높음) 후 전부 감소 — "유지"보다 먼저 본다(왕복 10→100→10이 처음=끝이라고
    # "유지"로 뭉개지지 않게).
    if 0 < peak_i < len(series_vals) - 1:
        rise_before = series_vals[peak_i] - min(series_vals[: peak_i + 1])
        if rise_before / scale > PEAK_REL and all(d <= noise for d in diffs[peak_i:]) and any(d > 0 for d in diffs[:peak_i]):
            basis = f"{order[0]} {_fmt_num(first)} → {order[-1]} {_fmt_num(last)}"
            return {"direction": "정점 후 감소", "period": f"{order[0]}–{order[-1]}", "basis": basis}
    # 2) 전체 범위가 작으면 유지(처음·끝만이 아니라 전체 값의 흩어진 정도로 — round-trip은 위 1)에서 이미 걸러짐)
    value_range = max(series_vals) - min(series_vals)
    if value_range / scale < FLAT_REL:
        direction = "유지"
    elif all(d >= -noise for d in diffs):  # 대체로 증가(작은 반대 방향 잡음은 허용)
        direction = "증가"
    elif all(d <= noise for d in diffs):  # 대체로 감소
        direction = "감소"
    else:
        direction = "변동"
    basis = f"{order[0]} {_fmt_num(first)} → {order[-1]} {_fmt_num(last)}"
    return {"direction": direction, "period": f"{order[0]}–{order[-1]}", "basis": basis}


def _norm_text(s):
    """공백·대소문자·전각/반각(NFKC) 차이를 지워 비교용 키로 — "Q1"·" q1 "·"Ｑ１"이 같은 지점으로 맞춰지게."""
    if s is None:
        return None
    import unicodedata

    s = unicodedata.normalize("NFKC", str(s)).strip().casefold()
    s = re.sub(r"\s+", " ", s)
    return s or None


def _match_key(v):
    """det 값({series,x,...})·VLM 값({label,...}, series/x 없음) 공용 중복 판정 키 — series는 없으면 None,
    x는 x 필드 없으면 label로 대신(VLM 스키마 보완). 라벨 문자열 그대로가 아니라 정규화해
    비교(서식만 다른 같은 지점을 다른 값으로 오인하지 않게)."""
    return (_norm_text(v.get("series")), _norm_text(v.get("x")) or _norm_text(v.get("label")))


def merge_values(det_values, vlm_values):
    """det(결정적, 우선)·vlm_values(figure_describe 등의 values[{label,value,unit}]) → 합친 목록. 같은
    (series,x)(정규화 비교 — 공백·대소문자·전각 차이 무시)는 det가 이김(겹치는 지점은 결정적 값만), vlm에만
    있는 지점은 그대로 보존(det가 못 찾은 점을 VLM이 보완)."""
    det_values = det_values or []
    seen = {_match_key(v) for v in det_values}
    out = list(det_values)
    for v in vlm_values or []:
        if _match_key(v) not in seen:
            out.append(v)
    return out


def chart_text(p):
    """오피스 내장 차트(charts/chart*.xml)의 제목·계열·값 캐시 → [차트] 줄."""
    import xml.etree.ElementTree as ET
    import zipfile

    p = Path(p)
    if p.suffix.lower() not in (".xlsx", ".pptx", ".docx"):
        return ""
    lines = []
    loc = lambda e: e.tag.rsplit("}", 1)[-1]
    kids = lambda e, name: [x for x in e.iter() if loc(x) == name]
    pts = lambda e: [v.text for pt in kids(e, "pt") for v in pt if loc(v) == "v"]
    with zipfile.ZipFile(p) as z:
        for n in sorted(x for x in z.namelist() if re.search(r"charts/chart\d+\.xml$", x)):
            root = ET.fromstring(z.read(n))
            for title in kids(root, "title")[:1]:
                lines.append("[차트] " + " ".join(x.text or "" for x in kids(title, "t")))
            for ser in kids(root, "ser"):
                name = " ".join(v.text or "" for tx in kids(ser, "tx")[:1] for v in kids(tx, "v"))
                cat = kids(ser, "cat")
                val = kids(ser, "val")
                lines.append(
                    f"계열 {name}: " + ", ".join(f"{c}={v}" for c, v in zip(pts(cat[0]) if cat else [], pts(val[0]) if val else []))
                )
    return "\n".join(lines)
