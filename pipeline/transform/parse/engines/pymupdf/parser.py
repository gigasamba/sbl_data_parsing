"""PyMuPDF (AGPL-3.0)

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine pymupdf <문서> <out.json>
"""

from pipeline.transform.parse.engines._common.contract import _mk_table, _facts_with_review, _fill_merged, fill_merged_on


def parse_pymupdf(path, profile="default"):
    """tuned: 읽기 순서 정렬(sort) + 표 감지 lines→text 전략 폴백.
    TB6 — find_tables().extract()의 covered 칸(rowspan·colspan으로 실제 칸 경계가 없는 자리)은 None으로
    나온다(진짜 빈칸은 "") — PARSE_FILL_MERGED(기본 켬)면 그 None을 origin 값으로 채운다(_fill_merged,
    pymupdf 자체의 Table.to_markdown(fill_empty=True)와 같은 규칙)."""
    import fitz
    fill_on = fill_merged_on()
    doc = fitz.open(path)
    texts, tables, weak_flags, table_pages, fallback_pages = [], [], [], [], 0
    for pno, pg in enumerate(doc, start=1):
        texts.append(pg.get_text(sort=(profile == "tuned")))
        found = [t.extract() for t in pg.find_tables().tables]
        weak = False
        if not found and profile == "tuned":
            found = [t.extract() for t in pg.find_tables(strategy="text").tables]
            fallback_pages += bool(found)
            weak = True
        if fill_on:
            found = [_fill_merged(t) for t in found]
        tables += found
        table_pages += [pno] * len(found)         # AD23 — tables_std page 칸(쪽 번호, 1-base)
        weak_flags += [weak] * len(found)
    mk = [_mk_table(t) for t in tables]
    for mt, pno in zip(mk, table_pages):
        mt["page"] = pno
    out = {"text": "\n\f".join(texts),   # 쪽 사이 \f — 근거의 쪽 번호(common_tools.evaluation.stages.locate)
           "tables": mk, "chunks": None,
           "trace": {"engine": f"pymupdf[{profile}]", "tables_found": len(tables),
                     "text_strategy_pages": fallback_pages}}
    out.update(_facts_with_review(tables, weak_flags))   # 엔진 간 동일한 strict·검수 가드
    return out


ENGINES = {"pymupdf": parse_pymupdf}
FORMATS = {"pymupdf": ('.pdf',)}
REQUIRES = {"modules": ['fitz'], "tools": []}
PROFILED = {'pymupdf'}
UNVERIFIED = set()
