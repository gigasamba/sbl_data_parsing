"""대표 결과(_rep) 형식 읽기 — 표 행·원문 위치. 구조화(청크 위치)·평가 도구가 같은 해석을 써야 함."""
import re


NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

EMPTY = {"", "nan", "none", "null", "-", "—"}          # 빈 칸 표기(pandas NaN 등) — 값·셀로 안 씀


def table_rows(d):
    """표 행 [(행 라벨, 머리글 목록, 셀 목록)] — 구조 사실(facts의 머리글 행 + 데이터 행)과 텍스트의 '|' 표(마크다운·파이프 줄) 둘 다.
    행 라벨 = 첫 칸, 머리글·셀은 첫 칸 다음부터(같은 길이일 때만)."""
    out, header = [], None
    for f in d["facts"]:
        cells = [c for c in (f.get("cells") or []) if str(c).strip().lower() not in EMPTY]
        row = (f.get("context") or [""])[0]
        if len(cells) >= 2 and not any(NUM_RE.search(c or "") for c in cells):
            header = cells
        elif header and cells and len(cells) == len(header):
            out.append((row, header, cells))
    header = None
    for ln in d["text"].splitlines():
        if "|" not in ln:
            if ln.strip():
                header = None                            # 빈 줄은 표가 이어짐(PDF 파서가 행 사이에 빈 줄을 넣음 — 실측)
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue                                    # 마크다운 구분 줄
        if len(cells) >= 3 and not any(NUM_RE.search(c) for c in cells):
            header = cells[1:]
        elif header and len(cells) - 1 == len(header) and cells[0]:
            out.append((cells[0], header, cells[1:]))
    return out


_SECTION = re.compile(r"^(?:#{1,6}\s+\S.*|\[?(?:Sheet|시트|Slide|슬라이드)\s*[:：#]?\s*\S.*)$", re.M)


def locate(text, start, end):
    """원문(파싱 텍스트) 안 [start, end) 구간의 위치 메타 — 근거 제시용.
    page = 앞에 있는 쪽 나눔(\\f) 수 + 1(엔진이 쪽 나눔을 넣은 경우만, 아니면 None) · line = 1부터 · section = 앞의 가장 가까운 제목·시트 줄."""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    sec = None
    for m in _SECTION.finditer(text, 0, start + 1):
        sec = m.group().strip("#[] ")[:80]
    return {"page": text.count("\f", 0, start) + 1 if "\f" in text else None,
            "line": text.count("\n", 0, start) + 1, "line_end": text.count("\n", 0, end) + 1,
            "span": [start, end], "section": sec}
