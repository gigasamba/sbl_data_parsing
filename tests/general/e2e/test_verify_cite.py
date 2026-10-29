"""rag_qa verify_citations(valid_env/answer_test/rag_qa — 10-29) 자기 점검(파일 이름은 20자 규칙으로 줄임) — S10(D-033 꼴)에 모듈의 `_demo()`에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python verify_citations.py`."""

import json

from validation.e2e.answer_gen import _verify_citations

verify_citations = _verify_citations()


def test_demo():  # 옛 _demo()
    covered = json.dumps(
        {
            "answer": "계약은 3건이다.",
            "status": "found",
            "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "계약 건수 3건"}],
        }
    )
    assert verify_citations(covered)["ok"] is True
    uncovered = json.dumps(
        {
            "answer": "계약은 5건이다.",
            "status": "found",
            "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "계약 건수 3건"}],
        }
    )
    assert verify_citations(uncovered)["ok"] is False
    no_citation = json.dumps({"answer": "확인됨", "status": "found", "citations": []})
    assert verify_citations(no_citation)["ok"] is False
    not_found = json.dumps({"answer": "", "status": "not_found", "citations": []})
    assert verify_citations(not_found)["ok"] is True
    spelled = json.dumps(
        {
            "answer": "there were three inspections.",
            "status": "found",
            "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "3 inspections recorded"}],
        }
    )
    assert verify_citations(spelled)["ok"] is True
    agg = json.dumps(
        {
            "answer": "4건",
            "status": "found",
            "citations": [
                {"doc_key": None, "chunk_key": None, "page": None, "kind": "aggregate", "quote": "고객 | 계약 건수\nSolvantis | 4"}
            ],
        }
    )
    assert verify_citations(agg)["ok"] is True  # RV-aggtext — 집계 근거는 doc/chunk/page 없이도 통과

    # R2-d — evidence가 주어지면 quote가 실제로 거기 있는지도 본다(지어낸 quote는 수치 커버만으론 못 걸렀다).
    ev = [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "text": "계약 건수 3건"}]
    assert verify_citations(covered, ev)["ok"] is True  # 실제 근거 text에 있음
    fabricated = json.dumps(
        {
            "answer": "계약은 3건이다.",
            "status": "found",
            "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "계약 건수 3건이라고 적혀있음"}],
        }
    )
    assert verify_citations(fabricated, ev)["ok"] is False  # ev에 없는 말을 지어냄
    assert verify_citations(agg, [{"kind": "aggregate", "text": "고객 | 계약 건수\nSolvantis | 4"}])["ok"] is True
    assert (
        verify_citations(agg, [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "text": "고객 | 계약 건수\nSolvantis | 4"}])["ok"] is False
    )  # 집계 아닌 근거로는 안 통과

    # be-qa 10-11 ② — 6자 미만 조각은 토큰 경계까지("1"이 "15" 속에서 안 걸림)
    short = json.dumps({"answer": "1", "status": "found", "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "1"}]})
    assert verify_citations(short, [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "text": "계약 15건 처리"}])["ok"] is False
    assert verify_citations(short, [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "text": "확인된 수량은 1"}])["ok"] is True

    # be-qa 10-11 ③ — "…" 조각은 순서대로(뒤 조각이 앞 조각보다 나중 위치)만 통과
    ord_ev = [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "text": "앞부분 내용 … 뒷부분 내용"}]
    forward = json.dumps(
        {"answer": "확인", "status": "found", "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "앞부분 …뒷부분"}]}
    )
    assert verify_citations(forward, ord_ev)["ok"] is True
    backward = json.dumps(
        {"answer": "확인", "status": "found", "citations": [{"doc_key": "d", "chunk_key": "d:0", "page": 1, "quote": "뒷부분 …앞부분"}]}
    )
    assert verify_citations(backward, ord_ev)["ok"] is False

    print(
        "[demo] verify_citations: 수치 커버·found 무인용 거부·영문 철자 수·집계(kind=aggregate)·"
        "evidence 교차검증(R2-d)·토큰 경계(②)·조각 순서(③) 통과"
    )
