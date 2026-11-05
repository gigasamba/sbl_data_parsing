"""pipeline.transform.represent.parse_scoring 시험."""

import json
import tempfile
from pathlib import Path

from pipeline.transform.represent.parse_scoring import clean_commas, norm_nows, run, value_recall


def selftest():
    """작은 픽스처(문서 2개 · 가짜 엔진 3개: 정상·빈 출력·수치 환각)로 채점 로직을 검증한다."""
    mail = clean_commas(norm_nows("Date: Sun, 5 Mar 2026 14:30:00 +0900"))  # C2 — RFC 2822 날짜 ↔ ISO 정답
    assert value_recall(["2026-03-05 14:30", "2026-03-05"], mail) == 1.0
    assert value_recall(["2026-03-06 14:30"], mail) == 0.0 and value_recall(["2026-13-05"], mail) == 0.0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        parse_dir, src_dir = td / "parse", td / "src"
        parse_dir.mkdir(), src_dir.mkdir()
        truth_text = "이름: 홍길동\n금액: 1,234원\n날짜: 2024-01-01\n항목 값\n금액 1234\n세금 100"
        halluc_text = truth_text + "\n" + ("채움 " * 150) + " 9999"
        docs = {
            "doc1.txt": {"good": truth_text, "empty": "", "halluc": halluc_text},
            "doc2.txt": {"good": "합계: 42", "halluc": "총계 42 추가 9999", "empty": "합계 42 원"},
        }
        runs = []
        for doc, engs in docs.items():
            (src_dir / doc).write_text("dummy", encoding="utf-8")
            for eng, text in engs.items():
                (parse_dir / eng).mkdir(exist_ok=True)
                (parse_dir / eng / (doc + ".json")).write_text(
                    json.dumps({"text": text, "tables": []}, ensure_ascii=False), encoding="utf-8"
                )
                runs.append({"doc": doc, "engine": eng, "sec": 0.1, "error": None})
        (parse_dir / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs), encoding="utf-8")
        # C3 — 구조 보존 엔진(tables[].grid, 행×열) 전용: 본문에는 표 내용이 줄로 안 들어있고 tables[]로만 존재
        (parse_dir / "structured").mkdir(exist_ok=True)
        doc3_text = "표는 별도 구조로 보존됨(본문에는 행 내용 없음)"
        doc3_tables = [{"rows": 2, "cols": 2, "text": "항목 값 금액 500", "grid": [["항목", "값"], ["금액", "500"]]}]
        (parse_dir / "structured" / "doc3.txt.json").write_text(
            json.dumps({"text": doc3_text, "tables": doc3_tables}, ensure_ascii=False), encoding="utf-8"
        )
        runs.append({"doc": "doc3.txt", "engine": "structured", "sec": 0.1, "error": None})
        (parse_dir / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs), encoding="utf-8")
        (src_dir / "doc3.txt").write_text("dummy", encoding="utf-8")
        truth = {
            "doc1.txt": {
                "text": truth_text,
                "values": [{"label": "금액", "value": "1234", "kind": "number"}, {"label": "이름", "value": "홍길동", "kind": "text"}],
                "tables": [[["항목", "값"], ["금액", "1234"], ["세금", "100"]]],
            },
            "doc3.txt": {"text": doc3_text, "values": [], "tables": [[["항목", "값"], ["금액", "500"]]]},
        }
        truth_path = td / "truth.json"
        truth_path.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

        qa, route = run(parse_dir, src_dir, truth_path, None)
        d1 = qa["docs"]["doc1.txt"]["engines"]
        assert d1["good"]["cer"] == 0.0, d1["good"]
        assert d1["good"]["value_recall"] == 1.0, d1["good"]
        assert d1["good"]["table_row_recall"] == 1.0 and d1["good"]["table_cell_recall"] == 1.0, d1["good"]
        d3 = qa["docs"]["doc3.txt"]["engines"]["structured"]
        assert d3["table_row_recall"] == 1.0, d3  # C3: 본문 줄엔 없지만 tables[].grid로 행 재현 인정
        assert d1["halluc"]["num_halluc"] > 0, d1["halluc"]
        assert d1["empty"]["ok"] is False
        assert qa["docs"]["doc2.txt"]["ref"] == "consensus", qa["docs"]["doc2.txt"]["ref"]
        assert route[".txt"][0] == "good" and route[".txt"][-1] == "empty", route
        print(
            "selftest OK —",
            json.dumps(
                {
                    "route": route,
                    "doc1_good_cer": d1["good"]["cer"],
                    "doc1_halluc_num_halluc": d1["halluc"]["num_halluc"],
                    "doc2_ref": qa["docs"]["doc2.txt"]["ref"],
                },
                ensure_ascii=False,
            ),
        )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
