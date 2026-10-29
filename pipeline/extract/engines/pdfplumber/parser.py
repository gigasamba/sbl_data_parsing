"""pdfplumber (MIT) — 좌표 기반 텍스트·표

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine pdfplumber <문서> <out.json>
"""

from pipeline.extract.engines._common.contract import _mk_table, _facts_with_review, _fill_merged, fill_merged_on


def parse_pdfplumber(path, profile="default"):
    """tuned: 선 기반 표 감지 실패 시 텍스트 정렬 기반 전략으로 폴백(선 없는 표 대응).
    TB6 — extract_tables()의 covered 칸(rowspan·colspan으로 실제 칸 경계가 없는 자리)은 None으로 나온다
    (진짜 빈칸은 "") — PARSE_FILL_MERGED(기본 켬)면 그 None을 origin 값으로 채운다(_fill_merged)."""
    import pdfplumber
    fill_on = fill_merged_on()
    texts, tables, weak_flags, fallback_pages = [], [], [], 0
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            texts.append(pg.extract_text() or "")
            found = [t for t in pg.extract_tables() if t]
            weak = False
            if not found and profile == "tuned":
                found = [t for t in pg.extract_tables(
                    {"vertical_strategy": "text", "horizontal_strategy": "text"}) if t]
                fallback_pages += bool(found)
                weak = True
            if fill_on:
                found = [_fill_merged(t) for t in found]
            tables += found
            weak_flags += [weak] * len(found)
    out = {"text": "\n\f".join(texts),   # 쪽 사이 \f — 근거의 쪽 번호(common_tools.evaluation.stages.locate)
           "tables": [_mk_table(t) for t in tables], "chunks": None,
           "trace": {"engine": f"pdfplumber[{profile}]", "tables_found": len(tables),
                     "text_strategy_pages": fallback_pages}}
    out.update(_facts_with_review(tables, weak_flags))
    return out


ENGINES = {"pdfplumber": parse_pdfplumber}
FORMATS = {"pdfplumber": ('.pdf',)}
REQUIRES = {"modules": ['pdfplumber'], "tools": []}
PROFILED = {'pdfplumber'}
UNVERIFIED = set()
