"""대표 결과(_rep) 형식 읽기 — 표 행·키-값 쌍·라벨 어휘(고객·공급사·계약 번호·단가·수량). 파싱(교차 확인)·구조화(고객·계약 번호·사실)·
평가 도구가 같은 해석을 써야 함.
10-14 함수별 분리(사용자) — data_parsing에서만 쓰는 doc_accuracy·GOLD는 data_parsing/tools/repfmt.py로 옮김
(로직 바이트 동일). _pick·extract_label_values는 pick·pairs_of(둘 다 여기 공용에 남음)가 직접 불러 그대로 남긴다."""
import re

from common.core.text import normalize_value  # noqa: F401 — pairs_of가 씀


CLIENT_RE = re.compile(r"고객|client|customer|거래처|발주처|구매처", re.I)

SUPPLIER_RE = re.compile(r"공급|supplier|vendor|제조사", re.I)

CONTRACT_RE = re.compile(r"계약\s*(번호|no|id)|contract\s*(no|number|#|id)|견적\s*번호|quote\s*(no|number)|주문\s*번호|po\s*(no|number)", re.I)

PRICE_RE = re.compile(r"단가|unit\s*price|금액|amount|price", re.I)

QTY_RE = re.compile(r"수량|qty|quantity|용량|capacity|volume", re.I)

NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

EMPTY = {"", "nan", "none", "null", "-", "—"}          # 빈 칸 표기(pandas NaN 등) — 값·셀로 안 씀

CONTRACT_FIRST = re.compile(r"계약|contract", re.I)  # 계약 번호가 있으면 견적·주문 번호보다 먼저

def nlabel(s):
    return re.sub(r"[\s·:：()\[\]]+", "", (s or "").lower())


# E16 — 첫 숫자 바로 뒤의 지수 표기: a×10^n(× x X * ·, 첨자는 표준화 뒤 ^n) · aE±n(부호 필수 — 제품코드 '2E1' 같은 ID 오인 방지).
# 첨자가 이미 붙어 버린 '3.2×106'은 원문에서 구분 불가라 그대로(파싱 단계 supsub로 살림).
SCI_TAIL = re.compile(r"\s*(?:[×xX*·]\s*10\s*\^\s*([+-]?\d+)|[eE]([+-]\d+))")


def num(s):
    s = str(s or "")
    m = NUM_RE.search(s)
    if not m:
        return None
    v = float(m.group().replace(",", ""))
    e = SCI_TAIL.match(s, m.end())
    return v * 10 ** int(e.group(1) or e.group(2)) if e else v


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


def pairs_of(d):
    """(라벨, 값) 후보 — '라벨: 값' 줄 + 표(머리글 행 뒤 데이터 행: '행 라벨 / 열 머리글' → 셀)."""
    out = list(extract_label_values(d["text"]))
    for ln in d["text"].splitlines():
        cells = [c.strip() for c in re.split(r"\s*\|\s*|\t", ln) if c.strip().lower() not in EMPTY]
        if len(cells) == 2 and not set(cells[1]) <= set("-: "):
            out.append((cells[0], cells[1]))
    for f in d["facts"]:
        cells = [c for c in (f.get("cells") or []) if str(c).strip().lower() not in EMPTY]
        row = (f.get("context") or [""])[0]
        if row and not f.get("cells") and str(f.get("value") or "").strip().lower() not in EMPTY:
            out.append((row, str(f["value"]).strip()))   # 셀 목록 없는 사실(calamine·kreuzberg) = 라벨 → 값
        elif row and len(cells) == 1 and cells[0]:
            out.append((row, cells[0]))          # 시트의 키-값 행(계약 번호 | D-…)
    out += [(f"{row} / {h}", c) for row, hdr, cells in table_rows(d) for h, c in zip(hdr, cells)
            if str(c).strip().lower() not in EMPTY]
    return out


def pick(pairs, rx, exclude=None):
    if rx is CONTRACT_RE:                                 # 계약 번호 우선, 없으면 견적·주문 번호
        return _pick(pairs, CONTRACT_FIRST, exclude) or _pick(pairs, rx, exclude)
    return _pick(pairs, rx, exclude)


def _pick(pairs, rx, exclude=None):
    for p in pairs:
        if rx.search(p["label"]) and not (exclude and exclude.search(p["label"])) and " / " not in p["label"]:   # ' / ' = 표 셀 라벨
            return p
    return None


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


RE_LABEL_LINE = re.compile(r"^\s*([^\n:：]{1,20})[:：]\s*(\S.*)$")


def extract_label_values(text):
    """'라벨: 값' 줄 목록 — 앵커 native/consensus 대용 추출 + graph table 모드용."""
    out = []
    for line in text.splitlines():
        m = RE_LABEL_LINE.match(line)
        if m:
            label, value = m.group(1).strip(), m.group(2).strip()
            if label and value and len(value) < 200:
                out.append((label, value))
    return out


