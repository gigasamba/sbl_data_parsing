"""pipeline.eval.gold_draft 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.gold_draft --selftest`."""

import json
from pathlib import Path

import pipeline.eval.gold_draft as M
from common.config import settings as C
from pipeline import config as pc
from pipeline.eval.gold_draft import parse_mermaid, reconcile_mermaid, render_mermaid_png, run, verify_mermaid


def selftest():
    import tempfile

    # S9 — 옛 `global _VLM_SEM` → `M.<이름>`(모듈 전역 대입)
    M._VLM_SEM = None
    # 대역(stub)이 호출 순서로 쪽을 가리므로 자기점검은 순차로(병렬은 test_qa_draft.py) — S7c: 설정 객체에 겹쳐 씀(os.environ 안 건드림)
    with C.COMMON.env(VLM_CONCURRENCY="1"), tempfile.TemporaryDirectory() as t:
        _selftest_body(Path(t))
    print(
        "[selftest] GS1·GS2 gold_draft — 쪽별 VLM 초안(파싱 참고 글은 참고용으로만, 베끼지 않음)·병합 칸 전부 채움·"
        "Mermaid 흐름도·확인할 곳(숫자·표 칸·줄) check.csv·쪽 상한·실패 쪽 기록·비대상 건너뜀·values.csv 보존·review.csv·"
        "GS3 docx(변환 PDF 쪽 + 원문 글자 참고, 변환 실패는 사유와 함께 건너뜀) 통과"
    )


def _selftest_body(t):
    # S9 — 옛 `global _vlm_gold` → `M.<이름>`(모듈 전역 대입)
    import fitz

    from common.ai.agent_prompts import template
    from pipeline.transform.figures.mermaid import to_mermaid

    src, out, parse_dir = t / "src", t / "output", t / "parse"
    src.mkdir()
    doc = fitz.open()
    for k in range(3):
        doc.new_page().insert_text((72, 72), f"page {k + 1}")
    doc.save(src / "a.pdf")
    (src / "b.xlsx").write_bytes(b"x")

    # GS2 참고 글(_rep, 쪽 나눔 \f) — 1쪽은 초안과 숫자가 같고, 2쪽은 다름(④ 확인할 곳 시험용)
    (parse_dir / "_rep").mkdir(parents=True)
    (parse_dir / "_rep" / "a.pdf.json").write_text(json.dumps({"text": "page 1 unit price 430,000\f단가 429,000원\f"}), encoding="utf-8")

    edges = [{"from": "접수", "to": "검토", "label": None}, {"from": "검토", "to": "완료", "label": "승인"}]
    mermaid_block = "```mermaid\n" + to_mermaid(edges) + "\n```"
    page_out = {
        1: "| 항목 | 값 |\n|---|---|\n| 배치 | B-1 |\n| 배치 | B-1 |\n단가 430,000",  # TB6 규칙 — 병합 칸(배치) 두 줄 모두 채움
        2: "단가 999,999\n" + mermaid_block,  # 참고 글(429,000)과 다른 숫자 + 흐름도
    }
    calls = []

    def stub(img, ref):
        calls.append(ref)
        page_no = len(calls)
        if page_no == 3:  # 다시 실행한 1쪽 — 실패 쪽 시험(원 GS1 동작 유지)
            return "", {"model": "stub-vlm"}
        return page_out.get(((page_no - 1) % 2) + 1, ""), {"model": "stub-vlm"}

    orig, M._vlm_gold = M._vlm_gold, stub
    try:
        rows = run(src, out, max_pages=2, parse_dir=parse_dir)
    finally:
        M._vlm_gold = orig

    assert [r[:5] for r in rows] == [["a.pdf", "draft", 2, "stub-vlm", ""], ["b.xlsx", "skipped", 0, "", ""]], rows
    assert calls[0] == "page 1 unit price 430,000" and calls[1] == "단가 429,000원"  # ① 쪽마다 맞는 참고 글(쪽 나눔 \f)

    md = (out / "a.pdf.md").read_text(encoding="utf-8")
    assert "| 배치 | B-1 |\n| 배치 | B-1 |" in md  # ② 병합 칸 값 — 덮인 칸 전부(TB6 규칙, 원문 그대로 보존)
    assert "```mermaid\nflowchart LR" in md and to_mermaid(edges) in md  # ③ Mermaid — to_mermaid()와 같은 표기(F13)

    check = (out / "a.pdf.check.csv").read_text(encoding="utf-8-sig")
    assert "999999" in check and "숫자" in check  # ④ 참고 글과 다른 숫자 → 확인할 곳
    assert "429000" not in check  # 참고 글 쪽 숫자 자체는 안 올라옴(초안 기준)

    p_gold = template("gold_draft", "draft")
    assert "병합" in p_gold and "Mermaid" in p_gold and "추측 금지" in p_gold  # ①②③ 지시문 글자 확인

    (out / "values.csv").write_text("문서,라벨,값\na.pdf,단가,430000\n", encoding="utf-8-sig")
    orig, M._vlm_gold = M._vlm_gold, stub
    try:
        rows = run(src, out, max_pages=2, parse_dir=parse_dir)
    finally:
        M._vlm_gold = orig
    assert rows[0][4] == "1", rows  # 셋째 호출(다시 실행한 1쪽)이 빈 답 → 실패 쪽 1
    assert "430000" in (out / "values.csv").read_text(encoding="utf-8-sig")  # 다시 실행해도 검수자 값 유지
    hdr = (out / "review.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert hdr == "문서,상태,쪽 수,모델,실패 쪽,메모,검수자", hdr

    # 사용자 10-14 — Mermaid 2차 점검(블라인드 질문) + 렌더
    first = [
        {"from": "접수", "to": "검토", "label": None},
        {"from": "검토", "to": "승인", "label": None},
        {"from": "승인", "to": "완료", "label": None},
        {"from": "완료", "to": "접수", "label": None},
    ]
    assert parse_mermaid(to_mermaid(first)) == first  # to_mermaid의 역
    assert parse_mermaid("flowchart LR\n  A(시작) --> B{판정}\n  B -->|예| C[끝]") == [
        {"from": "시작", "to": "판정", "label": None},
        {"from": "판정", "to": "끝", "label": "예"},
    ]  # VLM이 흔히 쓰는 모양
    blind = {
        "is_flowchart": True,
        "next": {
            "접수": [{"to": "검토"}],
            "검토 ": [{"to": "승인"}, {"to": "반려", "label": "부적합"}],
            "승인": [{"to": "완료"}],
            "완료": [],
            "반려": [{"to": "검토"}],
        },
    }
    final, notes = reconcile_mermaid(first, blind)
    got = {(e["from"], e["to"]) for e in final}
    assert ("완료", "접수") not in got  # 1차에만 있고 2차가 '완료' 답에서 안 냄 → 뺌
    assert {("검토", "반려"), ("반려", "검토")} <= got  # 2차에서만 보인 갈림길·되돌림 → 추가
    assert [e for e in final if e["to"] == "반려"][0]["label"] == "부적합"
    assert notes[0].startswith("Mermaid 2차 점검: 1차 화살표 4개 중 3개 일치 · 추가 2 · 뺌 1"), notes
    assert reconcile_mermaid(first, {"is_flowchart": False}) == (None, ["흐름도 아님(2차 점검) → Mermaid 뺌"])
    assert reconcile_mermaid(first, None) == (first, [])  # 점검 못 하면 1차 그대로
    kept, _ = reconcile_mermaid(first, {"is_flowchart": True, "next": {"접수": [{"to": "검토"}]}})
    assert len(kept) == 4  # 답 안 한 출발 단계의 1차 화살표는 유지

    # S9 — 옛 `global _vlm_check_mermaid` → `M.<이름>`(모듈 전역 대입)
    page_md = "본문\n```mermaid\n" + to_mermaid(first) + "\n```\n"
    orig, M._vlm_check_mermaid = M._vlm_check_mermaid, lambda img, nodes: (blind, {"model": "stub"})
    try:
        with pc.PIPE.env(GOLD_DRAFT_MERMAID_CHECK=None):  # S7c — 설정 객체(안 준 상태 = 켬)
            fixed, notes, finals = verify_mermaid(b"img", page_md)
            assert "반려" in fixed and len(finals) == 1 and fixed.startswith("본문")
            M._vlm_check_mermaid = lambda img, nodes: ({"is_flowchart": False}, {"model": "stub"})
            fixed, notes, finals = verify_mermaid(b"img", page_md)
            assert "```mermaid" not in fixed and finals == []  # 흐름도 아님 → 블록 뺌
        with pc.PIPE.env(GOLD_DRAFT_MERMAID_CHECK="0"):
            assert verify_mermaid(b"img", page_md) == (page_md, [], [])  # 끄면 그대로
    finally:
        M._vlm_check_mermaid = orig
    png = render_mermaid_png(final, t / "flow.png")
    assert png and png.stat().st_size > 1000 and render_mermaid_png([], t / "none.png") is None

    # GS3 — docx: rendered to PDF (fake converter here), the page reference is the document's own text, not our parser's
    # S9 — 옛 `global office_pdf` → `M.<이름>`(모듈 전역 대입)
    src3, out3 = t / "src3", t / "out3"
    src3.mkdir()
    (src3 / "c.docx").write_bytes(b"docx bytes")
    (src3 / "d.docx").write_bytes(b"broken")
    fake_pdf = t / "c_render.pdf"
    d = fitz.open()
    d.new_page().insert_text((72, 72), "unit price 430,000")
    d.save(fake_pdf)
    seen = []

    def stub3(img, ref, source=False):
        seen.append((ref, source))
        return "unit price 431,000", {"model": "stub-vlm"}

    orig_pdf, M.office_pdf = M.office_pdf, lambda p, work: fake_pdf if p.name == "c.docx" else None
    orig, M._vlm_gold = M._vlm_gold, stub3
    try:
        rows = run(src3, out3, max_pages=5, parse_dir=parse_dir)
    finally:
        M.office_pdf, M._vlm_gold = orig_pdf, orig
    assert [r[:3] for r in rows] == [["c.docx", "draft", 1], ["d.docx", "skipped", 0]], rows
    assert "soffice" in rows[1][5], rows  # conversion failed → clear reason
    assert seen == [("unit price 430,000\n", True)], seen  # the doc's own text, flagged as source
    assert (out3 / "c.docx.md").exists() and "431000" in (out3 / "c.docx.check.csv").read_text(encoding="utf-8-sig")


def test_main():  # 옛 `if a.selftest:` 갈래(main() 안)
    selftest()
