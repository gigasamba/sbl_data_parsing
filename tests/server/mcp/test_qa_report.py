"""mcp_server.cli.qa_report 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.cli.qa_report --selftest`."""

import hashlib
import json
import tempfile
from pathlib import Path

from mcp_server.cli.qa_report import build, load_mcp_index, load_qa_raw, render_html, write_xlsx


def selftest():
    with tempfile.TemporaryDirectory() as td:
        eval_root = Path(td) / "eval_sets"
        (eval_root / "demo").mkdir(parents=True)
        (eval_root / "demo" / "qa.json").write_text(
            json.dumps(
                {
                    "items": [
                        {"id": "QA1", "gold_answer": "42"},
                        {"id": "QA2", "answer_keywords": ["foo", "bar"]},
                        {"id": "QA3", "gold_table": {"columns": ["x"]}},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        rows = [
            {
                "dataset": "demo",
                "id": "QA1",
                "type": "value",
                "question": "값?",
                "gold_docs": ["a.pdf"],
                "files5": ["a.pdf", "b.pdf"],
                "answer": "정답은 42입니다 [1]",
                "cls": "OK",
            },
            {
                "dataset": "demo",
                "id": "QA2",
                "type": "value",
                "question": "키워드?",
                "gold_docs": ["c.pdf"],
                "files5": ["d.pdf", "e.pdf"],
                "answer": "모른다고 답함",
                "cls": "A-ABSTAIN",
            },
            {
                "dataset": "demo",
                "id": "QA3",
                "type": "table_aggregate",
                "question": "표?",
                "gold_docs": ["f.pdf"],
                "files5": ["f.pdf", "g.pdf"],
                "answer": "표: ...",
                "cls": "UNSCORED",
            },
            {
                "dataset": "demo",
                "id": "QA4",
                "type": "value",
                "question": "틀림?",
                "gold_docs": ["h.pdf"],
                "files5": ["i.pdf", "j.pdf"],
                "answer": "오답 [2]",
                "cls": "A-MISS",
                "subcause": "confused_by_distractor",
            },
            {
                "dataset": "demo",
                "id": "QA5",
                "type": "value",
                "question": "검색 실패?",
                "gold_docs": ["k.pdf"],
                "files5": ["m.pdf"],
                "answer": "",
                "cls": "R-MISS",
            },
        ]
        mcp_report = {"sets": {"demo": {"rows": [{"id": "QA1", "hit1": True, "hit5": True}]}}}
        mcp_path = Path(td) / "mcp.json"
        mcp_path.write_text(json.dumps(mcp_report, ensure_ascii=False), encoding="utf-8")

        mcp_idx = load_mcp_index(str(mcp_path))
        assert mcp_idx[("demo", "QA1")] == {"hit1": True, "hit5": True}
        assert load_mcp_index(None) == {}  # 조인 안 줘도 오류 없음

        qa_get = load_qa_raw(str(eval_root))
        out_rows, summary = build(rows, mcp_idx, qa_get, plain=False)
        assert summary["n"] == 5 and summary["classification"] == {"OK": 1, "A-ABSTAIN": 1, "UNSCORED": 1, "A-MISS": 1, "R-MISS": 1}, (
            summary
        )
        # 오답·기권이 OK보다 먼저(사람이 먼저 봐야 할 순서)
        order = [r["cls"] for r in out_rows]
        assert order.index("A-MISS") < order.index("OK") and order.index("A-ABSTAIN") < order.index("OK"), order
        by_id = {r["id"]: r for r in out_rows}
        assert by_id["QA1"]["gold_answer"] == "42" and "그 중 하나" in by_id["QA2"]["gold_answer"]
        assert by_id["QA3"]["gold_answer"] == "[표 정답 — qa.json의 gold_table 참고]"
        assert by_id["QA1"]["cited"] == ["doc-" + hashlib.sha256(b"a.pdf").hexdigest()[:8]]  # [1] -> files5[0] = a.pdf(해시 이름)
        assert by_id["QA4"]["cited"] == ["doc-" + hashlib.sha256(b"j.pdf").hexdigest()[:8]]  # [2] -> files5[1] = j.pdf
        assert by_id["QA1"]["retrieved"][0][1] is True and by_id["QA1"]["retrieved"][1][1] is False  # a.pdf=gold, b.pdf 아님
        assert "hit@1=True" in by_id["QA1"]["verdict"]  # mcp_eval 조인이 판정 칸에 붙음

        out_rows_plain, _ = build(rows, {}, qa_get, plain=True)
        assert any(d == "a.pdf" for d, _ in {r["id"]: r for r in out_rows_plain}["QA1"]["retrieved"]), "plain-names 원래 이름"

        h = render_html(out_rows, summary, "selftest")
        assert "Q&A 결과 보고서" in h and "doc-" in h and "★" in h and "pill-A-MISS" in h
        assert h.index('class="pill pill-A-MISS"') < h.index('class="pill pill-OK"')  # 오답이 표에서도 먼저

        xlsx_path = write_xlsx(out_rows, Path(td) / "output" / "qa_report_selftest.xlsx")
        if xlsx_path is not None:  # openpyxl 없는 환경(서버 이미지에 빠졌을 때)도 실패하지 않음 — 그때는 건너뜀만 확인
            from openpyxl import load_workbook

            wb = load_workbook(xlsx_path)
            ws = wb.active
            assert ws["A1"].value == "세트" and ws.freeze_panes == "A2" and ws.auto_filter.ref
            assert ws.cell(row=2, column=2).value == "QA1" or ws.cell(row=2, column=2).value == "QA4"  # A-MISS/A-ABSTAIN 먼저 정렬돼 있음
    print(
        "[selftest] qa_report — mcp_eval 조인·qa.json 정답 보강(best-effort)·오답/기권 우선 정렬·인용 추출([n]→files5)·"
        "해시/원래 이름·HTML 열 순서·xlsx 줄바꿈/고정/필터 통과"
    )


def test_main():  # 옛 `--selftest` 갈래(main()의 `if a.selftest: return selftest()`)
    selftest()
