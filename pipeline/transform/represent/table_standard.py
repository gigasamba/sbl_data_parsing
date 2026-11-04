"""AD23·SI20③ — 산출 쪽 표 표준 형식: 대표 결과(_rep)의 표를 엔진과 무관하게 한 형식(id·page·source_engine·
header·rows·merged)으로 정규화해 rep["tables_std"]에 둔다(기존 tables·facts는 그대로 — 새 칸 추가뿐).

입력은 rep["tables"][i]가 이미 들고 있는 grid(2D 칸, pipeline.extract.engines._common.contract._mk_table이 모든 엔진
공통으로 채움) — 그리드가 없는(과거 캐시) 표는 건너뛴다. 병합 칸 펼침(같은 값 채우기)·범위 기록(merges)은
엔진이 미리 해 둔다(office_stdlib — docx gridSpan·vMerge, xlsx mergeCells); table_std는 그 결과를
header(첫 행)·rows(나머지)·merged로 그대로 옮기고, 칸 글자에 standardize_text(기호 맵·첨자 표기)를 적용한다.

TB5 — 머리글 행 2~3단(병합 머리글, 예 "2026년"→"상반기/하반기"→"1~4분기"): header_depth()가 그리드 맨 위부터
몇 행이 머리글인지 추정한다 — merges가 맨 위(r==0)부터 닿아 1행을 넘게 덮거나(rowspan>1 또는 colspan>1),
이미 확정된 머리글 범위(r < depth) 안에서 시작해 그 범위를 늘리는 경우만(데이터 행 한가운데서 시작하는
병합, 예 '비고' 칸이 데이터 행 여러 개를 덮음·전체 폭 구분 행은 r>=depth라 평생 무시, 최대 3행·데이터 행
1개 이상 남김). 병합 증거가 없는 엔진(merges=None/[])은 depth 1(= 기존 동작과 바이트 동일) — 숫자/비숫자
행만 보고 머리글 경계를 추정하는 규칙은 두 번째 재검토(블록 acc829ab)에서 완전히 뺐다(중간 전체-폭 비고
행이 숫자 행 바로 위에 있다는 이유만으로 머리글로 삼켜지는 오탐이 있었음 — merges 없는 표는 항상 depth 1).
단일 머리글 표(흔한 경우, depth==1)는 기존과 바이트 동일(header=첫 행, header_rows 칸 자체가 안 생김).
다단이면 header는 칸별 "위 / 아래" 평펴 라벨(값 손실 없음, 연속 중복은 한 번만)이 되고, 원본 머리글 행
전부는 header_rows에 그대로 남는다 — rows는 그 뒤부터(데이터 행만).

BR36 — 쪽 경계 표 이어 붙이기: 머리행이 반복되는 여러 쪽 표(예: longtable.pdf — 쪽1 머리글+행, 쪽2 같은
머리글+나머지 행)가 tables_std에서 쪽마다 별개 표로 쪼개져 있던 것을, 쪽 번호가 이웃(N→N+1)이고 머리행이
완전히 같은 경우에만 하나로 합치고(뒤 표의 반복 머리행은 버림) build_tables()가 반환하기 직전에 적용한다.
머리행·칸 수가 다르거나 쪽 번호가 없는(엔진이 page를 안 남김) 표는 안 합친다(오합 방지)."""

from pipeline.transform.represent.text_normalize import standardize_text


def _cell(c):
    return standardize_text(str(c if c is not None else ""))


def _pad(grid):
    """행마다 칸 수가 다른 그리드(pymupdf·pdfplumber 류 — 병합 메타 없이 셀 누락)를 가장 긴 행 기준으로 빈 칸("")
    채워 네모로 만든다 — to_markdown()의 구분선(|---|) 칸 수가 모든 행과 맞아야 마크다운 표로 유효하다(독립 검토)."""
    width = max((len(r) for r in grid), default=0)
    return [list(r) + [""] * (width - len(r)) for r in grid]


def _merge_header_depth(merges, cap):
    """A등급 리뷰 반영(블록 2a2dafc7) — 병합이 '맨 위에 닿아있는' 경우만 머리글 증거로 센다. row0부터
    시작하는 병합만 첫 증거가 되고, 그 뒤로는 '이미 머리글로 확정된 범위(r < depth) 안에서 시작해 그 범위를
    늘리는' 병합만 추가로 센다 — 데이터 행 한가운데서 시작하는 병합(예: '비고' 칸이 데이터 행 여러 개를
    덮음, 전체 폭 구분 행)은 r >= depth라 평생 무시된다(머리글을 데이터 쪽으로 잘못 늘리지 않음)."""
    if not merges:
        return 1
    depth, grown = 1, True
    while grown and depth < cap:
        grown = False
        for m in merges:
            r = m.get("r", 0) or 0
            rowspan, colspan = m.get("rowspan", 1) or 1, m.get("colspan", 1) or 1
            if (rowspan > 1 or colspan > 1) and r < depth:
                reach = min(r + rowspan, cap)
                if reach > depth:
                    depth, grown = reach, True
    return depth


def header_depth(grid, merges):
    """TB5 — 그리드 맨 위부터 몇 행이 머리글인지: merges가 맨 위에 닿아(r==0 또는 이미 확정된 머리글
    범위 안) 1행 넘게 덮으면(rowspan>1 또는 colspan>1) 그 범위(_merge_header_depth)뿐이다 — 숫자/비숫자
    행 추정(옛 rule-b)은 재검토(블록 acc829ab)에서 완전히 제거했다: 병합 정보가 없는 엔진은 숫자든
    아니든 depth 1(= 기존 동작과 바이트 동일, '전체 특이사항 없음' 같은 중간 전체-폭 비고 행이 숫자 행
    위에 있다는 이유만으로 머리글로 삼켜지는 오탐을 원천 차단). 최대 3행, 데이터 행 1개 이상은 남긴다."""
    n = len(grid)
    if n < 2:
        return 1
    cap = min(3, n - 1)
    return _merge_header_depth(merges, cap)


def _flatten_header(header_rows):
    """다단 머리글 → 칸별 "위 / 아래" 평펴 라벨(위→아래 순, 연속 중복 값은 한 번만) — 값 손실 없음(원본은
    header_rows에 그대로 남음)."""
    width = max((len(r) for r in header_rows), default=0)
    out = []
    for ci in range(width):
        parts = []
        for row in header_rows:
            v = row[ci] if ci < len(row) else ""
            if not parts or parts[-1] != v:
                parts.append(v)
        out.append(" / ".join(p for p in parts if p != "") or (parts[-1] if parts else ""))
    return out


def stitch_tables(entries):
    """BR36 — 쪽 경계에서 쪼개진 표 이어 붙이기. entries는 build_tables()가 만든 목록(쪽 순서 그대로)이라고
    가정 — 이웃한 두 표의 쪽 번호가 1 차이(N→N+1)이고 머리행이 완전히 같으면(칸 수·글자 전부) 하나로 합치고
    뒤 표의 반복 머리행은 버린다(rows만 이어붙임). 쪽 정보가 없거나(엔진이 page를 안 남김) 머리행이 다르면
    안 합친다(오합 방지) — 합친 표는 앞 표의 id를 쓰고 page는 이어붙인 마지막 쪽으로 갱신."""
    out = []
    for t in entries:
        if out:
            prev = out[-1]
            if prev["page"] is not None and t["page"] is not None and t["page"] == prev["page"] + 1 and prev["header"] == t["header"]:
                prev["rows"] = prev["rows"] + t["rows"]
                prev["merged"] = prev["merged"] + t["merged"]
                prev["page"] = t["page"]
                continue
        out.append(dict(t))
    return out


def build_tables(tables, source_engine):
    """rep["tables"] → tables_std 목록. 표마다 {id, page, source_engine, header, rows, merged}
    (+ 다단 머리글이면 header_rows, TB5).
    grid 없는 표(그리드를 안 남기는 옛 _rep 캐시 재사용 경로·엔진 오류 등)는 건너뛴다 — 틀린 구조를 만드는 것보다 안전.
    반환 전에 stitch_tables()로 쪽 경계 표를 이어 붙인다(BR36)."""
    out = []
    for i, t in enumerate(tables or []):
        grid = t.get("grid")
        if not grid:
            continue
        padded = _pad(grid)
        depth = header_depth(padded, t.get("merges"))
        rows = [[_cell(c) for c in row] for row in padded]
        header_rows = rows[:depth]
        entry = {
            "id": f"t{i}",
            "page": t.get("page"),
            "source_engine": source_engine,
            "header": header_rows[0] if depth == 1 else _flatten_header(header_rows),
            "rows": rows[depth:],
            "merged": [dict(m) for m in (t.get("merges") or [])],
        }
        if depth > 1:
            entry["header_rows"] = header_rows  # 원본 머리글 행 전부(값 손실 없이) — 평펴 header는 요약용
        out.append(entry)
    return stitch_tables(out)


def to_markdown(entry):
    """tables_std 표 하나 → 마크다운(`| a | b |`) — 칸 안 `|`는 `\\|`로 escape(마크다운 왕복 selftest용)."""

    def esc(c):
        return str(c).replace("|", "\\|")

    sep = "|" + "|".join(["---"] * max(len(entry["header"]), 1)) + "|"
    lines = ["| " + " | ".join(esc(c) for c in entry["header"]) + " |", sep]
    for r in entry["rows"]:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(lines)
