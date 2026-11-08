"""청킹(구조화 모듈) — 대표 결과 본문 → 청크(구조 청커) + 위치(쪽·줄·문자 범위·절)."""

import re
from pathlib import Path

from common.core.meaning import strip_page_numbers
from common.core.repfmt import locate  # 쪽·줄 위치 규칙(파싱 결과 형식)
from pipeline import config as pc  # pipeline 칸 CHUNK_*


def rep_text(d):
    """대표 결과(_rep/<문서>.json 내용) → 청킹할 본문(본문에 없는 표 글은 뒤에 붙임)."""
    text = d.get("text") or ""
    for t in d.get("tables") or []:
        tt = t.get("text") or ""
        if tt and tt not in text:
            text = text + "\n" + tt
    return text


_HEADING = re.compile(r"^#{1,6}\s+\S")


def _is_table_line(line):
    return "|" in line or "\t" in line


_SEP_ROW = re.compile(r"^[\s|:-]+$")  # 마크다운 표 구분 줄("| --- | --- |")
_NUM_LINE = re.compile(r"\d")


def _cells(line):
    """표 줄 → 칸 목록('|' 표는 그걸로, 탭 표는 탭으로) — 표 행 쪼개기·이어붙이기용."""
    return [c.strip() for c in (line.strip().strip("|").split("|") if "|" in line else line.split("\t"))]


def _table_header(tbl):
    """표 블록 머리글 줄(마크다운이면 머리글+구분 줄 최대 2줄) — 숫자가 있는 첫 줄(쪽 넘김 이어지는 조각)은
    머리글로 안 봄(ponytail: 숫자 없는 첫 줄 = 머리글 휴리스틱, 숫자 든 머리글은 못 잡음)."""
    if not tbl or _NUM_LINE.search(tbl[0]):
        return []
    head = [tbl[0]]
    if len(tbl) > 1 and _SEP_ROW.match(tbl[1]):
        head.append(tbl[1])
    return head


def _row_kv(header_line, row_line):
    """행 1개 → '머리글: 값' 쌍 한 줄(BM25·ID 검색용)."""
    hs, rs = _cells(header_line), _cells(row_line)
    return " · ".join(f"{h}: {v}" for h, v in zip(hs, rs) if h and v)


def _fig_mask(lines):
    """그림 블록([그림 …] ~ 빈 줄, post/context.py render 형식) 줄 표시 — 표 쪼개기·이어붙이기 대상에서 뺀다
    (그림 기록 속 표(table_md)는 자르지 않음)."""
    mask, on = [], False
    for ln in lines:
        if ln.startswith("[그림 "):
            on = True
        elif not ln.strip():
            on = False
        mask.append(on)
    return mask


def chunk_structure(doc, text):
    """제목(마크다운 heading) 경계 + 표 블록(연속된 '|'·탭 줄)은 통째로 한 청크.
    목표 길이 = CHUNK_SIZE(없으면 800). CHUNK_TABLE=rows면 표가 CHUNK_TABLE_ROWS(기본 25)행보다
    크면 머리글(+구분 줄)을 반복하며 행 묶음으로 쪼개고 행마다 '머리글: 값' 쌍을 덧붙인다(BM25·ID 검색용) ·
    머리글 없이 이어지는 다음 조각(쪽 넘김 — 빈 줄 뒤 열 수가 같은 표)은 쪼개기 전에 앞 표 몸통에 합친다 ·
    그림 블록은 절대 안 쪼갬. 표 청크의 meta(제목·시트·쪽)는 chunk_all의 locate()가 위치로 그대로 채움."""
    st = pc.cfg().transform.structure
    target = int(st.chunk_size if st.chunk_size is not None else 800)
    if not text:
        return []
    lines = text.split("\n")
    starts = [0] * (len(lines) + 1)  # starts[i] = lines[:i] 합친 글자 수
    for k, ln in enumerate(lines):
        starts[k + 1] = starts[k] + len(ln) + 1
    split_tables = st.chunk_table == "rows"
    rows_per = int(st.chunk_table_rows)  # 기본 25
    fig = _fig_mask(lines) if split_tables else None
    out, n, buf, buf_start, i = [], 0, [], 0, 0

    def is_tbl(k):
        return k < len(lines) and _is_table_line(lines[k]) and not (fig and fig[k])

    def flush():
        nonlocal buf, n
        t = "\n".join(buf).strip()
        if t:
            out.append({"id": f"{doc}::structure::{n}", "doc": doc, "text": t, "pos": buf_start})
            n += 1
        buf = []

    def push(txt, pos):
        nonlocal n
        t = txt.strip()
        if t:
            out.append({"id": f"{doc}::structure::{n}", "doc": doc, "text": t, "pos": pos})
            n += 1

    while i < len(lines):
        if is_tbl(i):
            flush()
            j = i
            while is_tbl(j):
                j += 1
            tbl, pos0 = lines[i:j], starts[i]
            head = _table_header(tbl)
            body, body_pos = tbl[len(head) :], starts[i + len(head) : j]
            if split_tables and head:
                while True:  # 쪽 넘김: 빈 줄 뒤 머리글 없는(숫자 첫 줄) 같은 열 수 조각은 합쳐서 묶는다
                    m = j
                    while m < len(lines) and not lines[m].strip():
                        m += 1
                    if m >= len(lines) or not is_tbl(m) or not _NUM_LINE.search(lines[m]):
                        break
                    e = m
                    while is_tbl(e):
                        e += 1
                    # ponytail: 열 수(±1)만 봄 — 빈 줄 하나 끼고 열 수가 같은 무관한 표가 붙어 있으면 한 표로 합칠 수 있음.
                    # 실문서에서 오합침이 보이면 첫 칸 값 형식(번호·날짜)·쪽 경계(\f) 일치까지 확인하도록
                    if abs(len(_cells(lines[m])) - len(_cells(head[-1]))) > 1:
                        break
                    body += lines[m:e]
                    body_pos += starts[m:e]
                    j = e
            i = j
            if split_tables and len(head) + len(body) > rows_per:
                for g in range(0, len(body), rows_per):
                    grp, gpos = body[g : g + rows_per], body_pos[g : g + rows_per]
                    kv = [x for x in (_row_kv(head[-1], r) for r in grp) if x] if head else []
                    push("\n".join(head + grp + kv), gpos[0] if gpos else pos0)
            else:
                push("\n".join(head + body), pos0)
            continue
        line = lines[i]
        if _HEADING.match(line) and buf:
            flush()
        if not buf:
            buf_start = starts[i]
        buf.append(line)
        if sum(len(b) for b in buf) > target:
            flush()
        i += 1
    flush()
    return out


def chunk_all(corpus, used=None):
    """청크마다 meta = {file, engine, page, line, line_end, span, section} — 청크·그래프·검색 단위가 원본 위치를 들고 다닌다.
    used = load_corpus가 채운 {문서: 파싱 엔진}(없으면 engine None)."""
    out = []
    for doc, text in sorted(corpus.items()):
        for c in chunk_structure(doc, text):
            pos = c.get("pos") or 0
            i = text.find(c["text"][:40], max(0, pos - 5)) if c["text"] else -1  # 공백 정리로 pos가 조금 어긋나는 청커 보정
            s = i if i >= 0 else pos
            c["meta"] = {"file": doc, "engine": (used or {}).get(doc), **locate(text, s, s + len(c["text"]))}
            # 정제: 쪽 번호 줄·쪽 나눔 문자는 위치 매핑(meta.page)에만 쓰고 청크 본문에서는 뺀다(common/meaning.py)
            c["text"] = strip_page_numbers(c["text"]).replace("\f", "\n")
            out.append(c)
    return out


# FAQ 머리글 → 칸(수정일 칸은 gold에 자리가 없어 읽지 않음)
FAQ_HEAD = {"type": "type", "client question": "question", "question": "question", "answer": "answer"}


def faq_rows(path):
    """FAQ 엑셀 → 행마다 {group(시트 이름), type, question, answer, row(엑셀 행 번호)}.
    시트의 첫 비지 않은 행이 머리글 — 질문·답 머리글이 없는 시트는 건너뛰고 경고. 빈 칸은 None(행은 남김),
    질문·답이 모두 빈 행은 건너뜀. 엑셀이 아니거나 못 열거나 남는 행이 없으면 None(일반 문서처럼 청킹)."""
    if Path(path).suffix.lower() not in (".xlsx", ".xlsm"):
        return None
    from openpyxl import load_workbook

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # 암호·깨진 파일 — 이 문서만 일반 청킹(묶음 전체를 멈추지 않음)
        print(f"[faq] 경고: 엑셀을 못 열어 일반 청킹 — {path}: {type(e).__name__}", flush=True)
        return None
    out = []
    try:
        for sh in book:
            cols = None
            for n, vals in enumerate(sh.iter_rows(values_only=True), 1):
                cells = [(str(v).strip() or None) if v is not None else None for v in vals]
                if not any(cells):
                    continue
                if cols is None:
                    names = [FAQ_HEAD.get(re.sub(r"[\s_]+", " ", (c or "").lower())) for c in cells]
                    if not {"question", "answer"} <= set(names):
                        print(f"[faq] 경고: 시트 {sh.title!r}에 질문·답 머리글이 없어 건너뜀 — {path}", flush=True)
                        break
                    cols = {k: i for i, k in reversed(list(enumerate(names))) if k}  # 같은 머리글이 둘이면 앞의 것
                    continue
                row = {k: (cells[cols[k]] if k in cols and cols[k] < len(cells) else None) for k in ("type", "question", "answer")}
                if row["question"] or row["answer"]:  # 유형만 있는 구분 행은 청크로 만들지 않음
                    out.append({"group": sh.title, **row, "row": n})
    finally:
        book.close()
    return out or None
