"""표 인라인 — 표로 인식한 모든 엔진의 grid를 모아 표 자리마다 하나를 고르고, 대표 본문의 그 자리에 마크다운 표로 넣는다.
대표 엔진이 표 구조를 잃은 글(예: pymupdf의 '한 칸 한 줄')을 내도 청크·검색 근거·.md에 표가 제자리에 한 번만 들어가게 한다.
represent()가 한 번 부른다:
  (a) 후보 = 시도한 ok 엔진 전부의 grid 있는 표.
  (b) group_tables(): 같은 쪽(둘 다 쪽을 알 때) 또는 칸 글자 겹침으로 같은 표 자리끼리 묶음.
  (c) choose_grid(): 묶음마다 비지 않은 칸 비율 + 다른 grid와 칸 글자 일치로 하나 고름(동점은 엔진 순서).
  (d) find_span(): 대표 엔진 본문에서 칸 글자를 순서대로 찾아 (거의) 다 찾으면 그 구간이 표 자리 — 아니면 손대지 않음.
  (e) 그 구간을 table_std.to_markdown 표로 바꾼다.
  (f) rep["tables_std"]를 고른 grid로 다시 만들고 "inline" 표시 — render_md()가 끝에 또 붙이지 않게.
병합 칸: 엔진이 덮인 칸을 원래 값으로 채워 넘긴다. merges 목록이 없는 엔진도 있어 reading_order_cells()는 위치로 채움 중복을 찾는다."""

from collections import Counter

from common.core.text import normalize_value
from pipeline.transform.represent import table_standard as table_std

GROUP_JACCARD_MIN = 0.5  # ponytail: 쪽으로 못 가를 때 '같은 표' 내용 겹침 고정 임계값 — 잘못 묶인 실례가 나오면 조정
MATCH_MIN_CELLS = 3  # 칸이 이보다 적으면 본문 아무 데서나 우연히 '찾아진다'
MATCH_MIN_RATIO = 0.9  # (거의) 모든 칸 — 추측하느니 본문을 그대로 둔다
GAP_MAX_CHARS = 20  # 받아들인 두 칸 사이 최대 간격 — 짧은 칸 글자(예 "장비")가 앞 문장에도 나오면, 이 상한 없이는
# 그 미끼에서 실제 표까지 사이 단락을 통째로 삼켰다. 실제 표의 칸은 붙어 있다.
SPAN_SLACK_CHARS = 200  # 칸 길이 예산에 더하는 고정 여유 — 칸 한두 개를 건너뛴 짧은 표도 통과하게
SPAN_SLACK_RATIO = 4  # 구간이 찾은 칸 글자 길이의 이 배수를 넘으면 거부 — 주변 단락을 삼키지 않게


def _cell_str(c):
    return str(c if c is not None else "").strip()


def reading_order_cells(grid):
    """행 순서로 비지 않은 칸 글자 — 병합 채움(_fill_merged) 중복은 뺀다: 바로 왼쪽(colspan 채움)이나 바로 위
    (rowspan 채움) 칸과 같으면 채움 중복으로 본다(merges 목록 없이도 동작).
    우연히 이웃과 같은 실제 칸은 빠질 수 있으나 find_span 대상이 하나 줄 뿐, 잘못 바꾸지는 않는다."""
    out = []
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            s = _cell_str(cell)
            if not s:
                continue
            left = _cell_str(row[c - 1]) if c > 0 else ""
            above = _cell_str(grid[r - 1][c]) if r > 0 and c < len(grid[r - 1]) else ""
            if s == left or s == above:
                continue
            out.append(s)
    return out


def _token_set(grid):
    return {t for t in (normalize_value(_cell_str(c)) for row in grid for c in row) if t}


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group_tables(candidates):
    """candidates: [{"engine", "table", "grid"(채운 것), "tokens", "page"}, ...] → 묶음 목록.
    쪽이 같거나(둘 다 알 때) 한쪽이 쪽을 모르고, 칸 글자 집합 Jaccard >= GROUP_JACCARD_MIN이면 같은 묶음.
    ponytail: 묶음 첫 표와만 비교하는 단순 탐욕 — 거의 같은 표가 수백 개인 문서용은 아님."""
    groups = []
    for cand in candidates:
        placed = False
        for g in groups:
            head = g[0]
            same_page = head["page"] is not None and cand["page"] is not None and head["page"] == cand["page"]
            page_unknown = head["page"] is None or cand["page"] is None
            if (same_page or page_unknown) and _jaccard(cand["tokens"], head["tokens"]) >= GROUP_JACCARD_MIN:
                g.append(cand)
                placed = True
                break
        if not placed:
            groups.append([cand])
    return groups


def choose_grid(group):
    """묶음마다 grid 하나 — 점수 = 0.5×완결성(비지 않은 칸 비율) + 0.5×일치도(묶음 안 다른 grid와 칸 글자
    Jaccard 평균). 동점은 묶음 원래 순서(엔진 순서). 반환: (고른 후보, 점수 기록)."""
    scored = []
    for cand in group:
        total = sum(len(row) for row in cand["grid"])
        nonempty = sum(1 for row in cand["grid"] for c in row if _cell_str(c))
        completeness = (nonempty / total) if total else 0.0
        others = [o["tokens"] for o in group if o is not cand]
        agreement = (sum(_jaccard(cand["tokens"], o) for o in others) / len(others)) if others else 1.0
        score = round(0.5 * completeness + 0.5 * agreement, 4)
        scored.append({"engine": cand["engine"], "score": score, "completeness": round(completeness, 4), "agreement": round(agreement, 4)})
    best_i = max(range(len(group)), key=lambda i: scored[i]["score"])
    return group[best_i], {"chosen": scored[best_i]["engine"], "candidates": scored}


def _page_slice(text, page):
    """text를 1부터 세는 page 쪽으로 좁힌다(\\f로 나눔) — 쪽을 모르거나 범위 밖이면 전체(경계를 추측하지 않음).
    반환: (offset, 조각)."""
    if page is None:
        return 0, text
    pages = text.split("\f")
    if page < 1 or page > len(pages):
        return 0, text
    offset = sum(len(p) + 1 for p in pages[: page - 1])
    return offset, pages[page - 1]


MAX_ANCHOR_TRIES = 50  # ponytail: 첫 칸 출현 위치를 시작점으로 시도하는 상한 — 같은 글자가 수백 번 나오는 문서 대비


def _walk(hay, cells, anchor):
    """anchor에서 찾은 cells[0]부터 나머지 칸을 순서대로 찾는다 — 마지막으로 받아들인 칸에서 GAP_MAX_CHARS를
    넘게 떨어진 칸은 못 찾은 것으로 친다. 반환: (찾은 수, 찾은 글자 길이, start, end, bounds) — bounds는
    받아들인 칸마다 (start, end)로, find_span이 칸 사이 실제 글을 되살리는 데 쓴다."""
    pos = anchor + len(cells[0])
    start, end, matched, matched_len = anchor, pos, 1, len(cells[0])
    bounds = [(anchor, pos)]
    for cell in cells[1:]:
        idx = hay.find(cell, pos)
        if idx == -1:
            continue
        if idx - end > GAP_MAX_CHARS:
            continue  # 마지막 칸에서 너무 멂 — 이 표가 아니라 미끼일 가능성
        matched += 1
        matched_len += len(cell)
        end = idx + len(cell)
        pos = end
        bounds.append((idx, end))
    return matched, matched_len, start, end, bounds


_TABLE_PUNCT = set(" \t\r\n|-–—·•:")  # 공백 + 표 장식 구분자 — 찾은 두 칸 사이 글이 실제 내용(각주)인지 볼 때 무시


def _gap_residues(hay, bounds):
    """바꿀 구간 안 칸 사이 간격(최대 GAP_MAX_CHARS)의 글 — 대개 공백이지만 짧은 캡션·각주면 지우면 안 된다.
    _TABLE_PUNCT만으로 된 것이 아닌 간격 글을 원래 순서로 돌려준다(호출 쪽이 보존)."""
    out = []
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:]):
        gap = hay[prev_end:next_start].strip()
        if gap and (set(gap) - _TABLE_PUNCT):
            out.append(gap)
    return out


def find_span(text, page, cells):
    """cells(reading_order_cells)를 (쪽으로 좁힌) text에서 순서대로 보수적으로 찾는다.
    첫 칸이 앞 제목에도 나오는 흔한 글자일 수 있어(예: 제목 "Equipment Checklist"와 표 첫 칸 "Equipment"),
    cells[0]의 모든 출현을 시작점으로 시도해(MAX_ANCHOR_TRIES까지) 가장 많이 맞는 곳을 고른다.
    반환: (start, end, residues) — text 기준 절대 위치와 보존할 간격 글(_gap_residues).
    찾은 칸이 너무 적거나(비율·개수) 구간이 지나치게 느슨하면 None."""
    if len(cells) < MATCH_MIN_CELLS:
        return None
    offset, hay = _page_slice(text, page)
    best, search_from, tries = None, 0, 0
    while tries < MAX_ANCHOR_TRIES:
        anchor = hay.find(cells[0], search_from)
        if anchor == -1:
            break
        tries += 1
        result = _walk(hay, cells, anchor)
        if best is None or result[0] > best[0]:
            best = result
        search_from = anchor + 1
    if best is None:
        return None
    matched, matched_len, start, end, bounds = best
    if matched < MATCH_MIN_CELLS or matched / len(cells) < MATCH_MIN_RATIO:
        return None
    if (end - start) > matched_len * SPAN_SLACK_RATIO + SPAN_SLACK_CHARS:
        return None
    return offset + start, offset + end, _gap_residues(hay, bounds)


def _build_candidates(rep, best_engine, other_docs):
    cands = []
    for engine, doc in [(best_engine, rep), *other_docs.items()]:
        for t in doc.get("tables") or []:
            grid = t.get("grid")
            if not grid:
                continue  # 구조가 없어 묶기·채점·인라인 불가 — table_std와 같은 규칙
            padded = table_std._pad(grid)
            cands.append({"engine": engine, "table": t, "grid": padded, "tokens": _token_set(padded), "page": t.get("page")})
    return cands


def inline_tables(rep, best_engine, other_docs):
    """진입점(represent()가 부름) — rep["text"]의 표 구간만 바꾸고 rep["tables_std"]를 채운다.
    반환: rep["rep"]["table_inline"] 정보.
    구간 안 칸 사이의 짧은 캡션·각주는 버리지 않고 마크다운 표 바로 뒤에 원래 순서로 붙인다(결정적인 유일한 자리)."""
    candidates = _build_candidates(rep, best_engine, other_docs)
    if not candidates:
        return {"on": True, "groups": 0, "inlined": 0, "unmatched": 0, "sources": {}, "residue": 0}

    text = rep.get("text") or ""
    groups = group_tables(candidates)
    replacements, built, sources, unmatched, residue_n = [], [], Counter(), 0, 0
    taken = []  # 이미 차지한 (start, end) — 두 묶음이 같은 글을 두고 겹치지 않게
    for group in groups:
        chosen, _score = choose_grid(group)
        sources[chosen["engine"]] += 1
        match_cand = next((c for c in group if c["engine"] == best_engine), chosen)
        cells = reading_order_cells(match_cand["grid"])
        span = find_span(text, match_cand["table"].get("page"), cells)
        if span and any(not (span[1] <= s or span[0] >= e) for s, e in taken):
            span = None  # 이미 넣은 표와 겹침 — 손대지 않음
        entry = table_std.build_tables([chosen["table"]], chosen["engine"])
        entry = entry[0] if entry else None
        inline_ok = bool(span and entry)
        if inline_ok:
            start, end, residues = span
            known = {normalize_value(c) for row in ([entry["header"]] + entry["rows"]) for c in row}
            # 병합 중복 제거가 실제로 반복된 칸(예: 두 번 나오는 배치 번호)을 빠뜨려 간격 글로 남길 수 있다 —
            # 표에 이미 있는 칸이라 버리고, 표 칸과 안 맞는 글(실제 캡션·각주)만 남긴다.
            residues = [r for r in residues if normalize_value(r) not in known]
            md = table_std.to_markdown(entry)
            if residues:
                md = md + "\n\n" + "\n".join(residues)  # 빈 줄 필수 — GFM은 빈 줄 전까지를 표 행으로 읽는다
                residue_n += len(residues)
            replacements.append((start, end, md))
            taken.append((start, end))
        else:
            unmatched += 1
        if entry is not None:
            entry["inline"] = inline_ok
            built.append(entry)

    for start, end, md in sorted(replacements, key=lambda r: -r[0]):
        text = text[:start] + md + text[end:]
    rep["text"] = text
    for i, entry in enumerate(built):
        entry["id"] = f"t{i}"
    rep["tables_std"] = built

    return {
        "on": True,
        "groups": len(groups),
        "inlined": len(groups) - unmatched,
        "unmatched": unmatched,
        "sources": dict(sources),
        "residue": residue_n,
    }
