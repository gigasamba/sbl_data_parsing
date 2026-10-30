"""Kreuzberg (MIT, Rust 코어)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine kreuzberg <문서> <out.json>
"""

from pipeline.extract.engines._common.contract import _md_tables, _with_split_tables, split_tables


import os
import re

_SENT_END = re.compile(r"(\.|다\.|음\.|요\.|[.!?。])\s*$")


def _prose_grid(rows):
    """BR49(10-11) — kreuzberg가 번호 목록 평문을 표로 오인(long_320p.pdf 320쪽 중 221개 '표', 실제로는 한 문장이 칸 4개로
    쪼개진 것). 판정: 행 5개 이상 · 빈칸 없는 행이 대부분 · 행의 마지막 칸이 문장 끝(마침표)으로 끝나는 비율 80% 이상이면 평문.
    실제 표는 행마다 마침표로 끝나는 일이 드묾(값·단위·코드). KREUZBERG_PROSE_FILTER=0이면 끔."""
    if os.environ.get("KREUZBERG_PROSE_FILTER") == "0":
        return False
    body = [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if len(body) < 5:
        return False
    ends = sum(1 for r in body if _SENT_END.search(next((c for c in reversed(r) if c), "")))
    if ends / len(body) < 0.8:
        return False
    # 한 문장이 칸으로 쪼개진 것이면 가운데 칸들이 행마다 같은 글자('기록 문장-'·'특이 사항')로 되풀이된다 — 실제 표(RFI 질문 목록
    # 'Q1 | 질문 문장')는 질문 칸이 행마다 다름. 둘째 칸부터 서로 다른 값 비율 30% 이하인 칸이 2개 이상일 때만 평문으로 본다.
    ncol = max(len(r) for r in body)
    rep = 0
    for j in range(1, ncol):
        vals = [r[j] for r in body if j < len(r) and r[j]]
        if len(vals) >= 0.5 * len(body) and len(set(vals)) <= 0.3 * len(vals):   # 빈 칸만 있는 열은 '되풀이'로 안 셈
            rep += 1
    return rep >= 2


def parse_kreuzberg(path):
    """Kreuzberg(MIT, Rust 코어): 여러 형식 추출 + 표. OCR 끔(텍스트 PDF).
    ponytail(TB6 천장): kreuzberg의 cells·markdown 둘 다 rowspan·colspan 메타를 안 돌려준다 — covered 칸이
    진짜 빈칸인지 병합인지 구분할 신호가 없어 추측하지 않고 그대로 둔다(병합 칸 채우기는 신호 있는 엔진만)."""
    from kreuzberg import extract_file_sync, ExtractionConfig
    try:
        r = extract_file_sync(path, config=ExtractionConfig(force_ocr=False))
    except TypeError:
        r = extract_file_sync(path)
    groups = []
    for t in getattr(r, "tables", None) or []:
        cells = getattr(t, "cells", None) or (t.get("cells") if isinstance(t, dict) else None)
        if cells:
            if _prose_grid(cells):                                            # BR49 — 평문 번호 목록은 표로 넘기지 않음(글자는 content에 그대로)
                continue
            groups += split_tables([[str(c) for c in row] for row in cells])   # AD24② 시트 1개 = 표 1개로 합쳐지는 문제
        else:
            md = getattr(t, "markdown", None) or (t.get("markdown") if isinstance(t, dict) else "")
            for tb in _md_tables(md or ""):
                groups += split_tables(tb)
    return _with_split_tables(r.content, groups, "kreuzberg")


ENGINES = {"kreuzberg": parse_kreuzberg}
FORMATS = {"kreuzberg": ('.pdf', '.docx', '.xlsx', '.pptx', '.ppt', '.xls', '.txt', '.mht', '.mhtml', '.doc', '.html', '.htm', '.eml', '.msg', '.xlsm')}
REQUIRES = {"modules": ['kreuzberg'], "tools": []}
PROFILED = set()
UNVERIFIED = set()   # kreuzberg_ocr(Tesseract)는 10-30 지움 — pl-31
