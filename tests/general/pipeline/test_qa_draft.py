"""pipeline.eval.qa_draft 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.qa_draft --selftest`."""

import csv
import json
from pathlib import Path

import pipeline.eval.qa_draft as M
from common.config import settings as C
from pipeline.eval.qa_draft import REVIEW_HDR, _value_labels, finalize, parse_items, run


def selftest():
    import tempfile

    # S9 — 옛 `global _VLM_SEM` → `M.<이름>`(모듈 전역 대입)
    M._VLM_SEM = None
    # 대역(stub)이 호출 순서로 쪽을 가리므로 자기점검은 순차로(병렬은 test_qa_draft.py) — S7c: 설정 객체에 겹쳐 씀(os.environ 안 건드림)
    with C.COMMON.env(VLM_CONCURRENCY="1"), tempfile.TemporaryDirectory() as t:
        _selftest_body(Path(t))
    print(
        "[selftest] QA1 qa_draft — 표 칸·그래프 값·흐름도 문항 초안·형식 검증(빈 칸·모르는 유형·중복 버림)·쪽당 상한·"
        "confidence low는 자동 채점 키워드 없음·실패 쪽·비대상 건너뜀·검수 줄 보존·finalize(reviewed만, 고친 답 반영)·"
        "GS3 docx(변환 PDF 쪽, 변환 실패는 건너뜀) 통과"
    )


def _selftest_body(t):
    # S9 — 옛 `global _vlm_qa` → `M.<이름>`(모듈 전역 대입)
    import fitz

    from common.ai.agent_prompts import template

    src, out = t / "src", t / "output"
    src.mkdir()
    doc = fitz.open()
    for k in range(3):
        doc.new_page().insert_text((72, 72), f"page {k + 1}")
    doc.save(src / "a.pdf")
    (src / "b.xlsx").write_bytes(b"x")

    page1 = {
        "items": [
            {
                "type": "table_cell",
                "question": "2024년 2분기 B 공장의 생산량은?",
                "answer": "1,250 kg",
                "object": "분기별 공장 생산량 표",
                "evidence": {"row": "B 공장", "col": "2024 Q2", "x": ""},
                "snippet": "1,250",
                "confidence": "high",
            },
            {
                "type": "chart_value",
                "question": "월별 수율 그래프에서 3월 A 라인 수율은?",
                "answer": "약 82~84%",
                "object": "월별 수율",
                "evidence": {"x": "3월", "series": "A 라인"},
                "confidence": "low",
            },
            {
                "type": "chart_value",
                "question": "월별 수율 그래프에서 4월 A 라인 수율은?",
                "answer": "48.75%",
                "object": "월별 수율",
                "evidence": {"x": "4월", "series": "A 라인"},
                "snippet": "",
                "confidence": "high",
            },  # 라벨 없이 high → low로 내림
            {
                "type": "chart_value",
                "question": "월별 수율 그래프에서 5월 A 라인 수율은?",
                "answer": "1,250",
                "object": "월별 수율",
                "evidence": {"x": "5월", "series": "A 라인"},
                "snippet": "1250",
                "confidence": "high",
            },  # 라벨 보임 → high 유지
            {"type": "nonsense", "question": "버려질 문항", "answer": "x"},
            {"type": "table_cell", "question": "", "answer": "빈 질문"},
            {"type": "table_cell", "question": "2024년 2분기 B 공장의 생산량은?", "answer": "중복"},
            {"type": "flow_order", "question": "Fed-batch와 Harvest 사이 단계는?", "answer": "Harvest"},  # 답이 질문에 있음 → 버림
            {
                "type": "flow_order",
                "question": "월별 수율 그래프에서 3월 다음 단계는?",
                "answer": "4월",
                "object": "월별 수율",
            },  # 그래프 대상 → 버림
        ]
    }
    page2 = {
        "items": [
            {
                "type": "flow_input",
                "question": "세포 배양 공정에서 2단계 배양(N-1)에 투입되는 배지는?",
                "answer": "CD-CHO 배지",
                "object": "세포 배양 공정 흐름도",
                "evidence": {"step": "N-1 배양", "related": ["CD-CHO 배지", "37℃"]},
                "confidence": "high",
            },
            {"type": "flow_next", "question": "세포 배양 공정에서 생산 배양 다음 단계는?", "answer": "원심분리", "confidence": "high"},
        ]
    }
    replies = ["```json\n" + json.dumps(page1, ensure_ascii=False) + "\n```", json.dumps(page2, ensure_ascii=False), ""]
    calls = []

    def stub(img, max_items):
        calls.append(max_items)
        return replies[(len(calls) - 1) % 3], {"model": "stub-vlm"}

    orig, M._vlm_qa = M._vlm_qa, stub
    try:
        qrows, summary = run(src, out, max_pages=3, max_items=4)
    finally:
        M._vlm_qa = orig

    assert calls == [4, 4, 4] and summary == [("a.pdf", 3, 6, [3])], (calls, summary)  # 3쪽 빈 답 = 실패 쪽 · xlsx 건너뜀
    by_q = {r["question"]: r for r in qrows}
    tc = by_q["2024년 2분기 B 공장의 생산량은?"]
    assert tc["answer"] == "1,250 kg" and tc["answer_keywords"] == ["1,250 kg"] and tc["category"] == "table_cell"
    assert tc["evidence"] == {"row": "B 공장", "col": "2024 Q2"} and tc["gold_evidence"][0]["page"] == 1  # 빈 x 칸은 버림
    cv = by_q["월별 수율 그래프에서 3월 A 라인 수율은?"]
    assert cv["confidence"] == "low" and cv["answer_keywords"] == []  # 어림 값 → 자동 채점 안 함(사람이 확정)
    fi = by_q["세포 배양 공정에서 2단계 배양(N-1)에 투입되는 배지는?"]
    assert fi["evidence"]["related"] == ["CD-CHO 배지", "37℃"] and fi["gold_evidence"][0]["page"] == 2
    assert "버려질 문항" not in by_q and "중복" not in [r["answer"] for r in qrows] and len(qrows) == 6
    assert by_q["월별 수율 그래프에서 4월 A 라인 수율은?"]["confidence"] == "low"  # 라벨 없이 high → low(자동 채점 안 함)
    assert by_q["월별 수율 그래프에서 5월 A 라인 수율은?"]["confidence"] == "high"  # 이미지에 적힌 숫자(snippet 1250 = 답 1,250)

    # 평가 도구(mcp_eval.load_question_items)가 그대로 읽는지는 dev_tools/unit_test/pipeline/test_qa_draft.py(모듈 경계 — parse는 evaluation을 import 안 함)

    rv = (out / "review.csv").read_text(encoding="utf-8-sig").splitlines()
    assert rv[0] == ",".join(REVIEW_HDR) and len(rv) == 7, rv
    with open(out / "review.csv", encoding="utf-8-sig", newline="") as fh:  # 검수: 그래프 문항 답 확정·reviewed, 흐름 하나 rejected
        rows = list(csv.DictReader(fh))
    for r in rows:
        if r["질문"] == "월별 수율 그래프에서 3월 A 라인 수율은?":
            r["답"], r["상태"] = "83%", "reviewed"
        elif r["유형"] == "table_cell":
            r["상태"] = "reviewed"
        elif r["유형"] == "flow_next":
            r["상태"] = "rejected"
    with open(out / "review.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_HDR)
        w.writeheader()
        w.writerows(rows)

    orig, M._vlm_qa = M._vlm_qa, stub  # 다시 실행해도 검수한 줄은 그대로
    calls.clear()
    try:
        run(src, out, max_pages=3, max_items=4)
    finally:
        M._vlm_qa = orig
    kept = finalize(out)
    assert sorted((k["category"], k["answer"]) for k in kept) == [("chart_value", "83%"), ("table_cell", "1,250 kg")], kept
    assert all(k["status"] == "reviewed" and k["answer_keywords"] == [k["answer"]] for k in kept)

    # GS3 — docx goes through the soffice PDF (fake converter here); ids and evidence keep the docx name
    from pipeline.eval import gold_draft as G

    src3, out3 = t / "src3", t / "out3"
    src3.mkdir()
    (src3 / "c.docx").write_bytes(b"docx bytes")
    (src3 / "d.docx").write_bytes(b"broken")
    d = fitz.open()
    d.new_page().insert_text((72, 72), "page one")
    d.save(t / "c_render.pdf")
    orig_pdf, G.office_pdf = G.office_pdf, lambda p, work: t / "c_render.pdf" if p.name == "c.docx" else None
    orig, M._vlm_qa = M._vlm_qa, lambda img, max_items: (json.dumps(page2, ensure_ascii=False), {"model": "stub-vlm"})
    try:
        q3, s3 = run(src3, out3, max_pages=3, max_items=4)
    finally:
        G.office_pdf, M._vlm_qa = orig_pdf, orig
    assert s3 == [("c.docx", 1, 2, [])] and {r["doc"] for r in q3} == {"c.docx"}, s3
    assert q3[0]["id"].startswith("qa-draft::c.docx::p1::") and q3[0]["gold_evidence"][0]["file"] == "c.docx"

    p = template("qa_draft", "qa")
    assert "{max_items}" in p and "추측 금지" in p and "table_cell" in p and "flow_input" in p  # 지시문 글자 확인
    assert parse_items("설명만 있고 JSON 없음", 5) == [] and parse_items('{"items": "x"}', 5) == []
    fake = json.dumps(
        {"items": [{"type": "chart_value", "question": "Q2 막대 값은?", "answer": "48.75", "snippet": "48.75", "confidence": "high"}]}
    )
    ticks = [(37, y, 55, y + 9, t) for y, t in ((374, "0"), (296, "16.25"), (219, "32.5"), (141, "48.75"))]  # 왼쪽 세로줄 = y축 눈금
    assert _value_labels(ticks) == "" and _value_labels(ticks + [(120, 150, 135, 159, "47")]) == "47"
    axis_text = ""  # 글자층은 있는데 값 라벨이 없음(눈금뿐) — 모델이 snippet에 48.75를 지어내도 → low
    assert parse_items(fake, 5, axis_text)[0]["confidence"] == "low" and parse_items(fake, 5)[0]["confidence"] == "high"
    assert parse_items(fake.replace("48.75", "47"), 5, "41 47 39 52")[0]["confidence"] == "high"  # 막대 위 값 라벨 있음


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
