"""mcp_server.services.search.question_type 시험."""

import json

from common.core.paths import RES_ROOT
from mcp_server.services.search.question_type import classify


def eval_labels():
    """resources/vocab/qtype_labels.json(질문 글자만 보고 손으로 붙인 라벨) → (정확도, 혼동 행렬) — 10-30 앱 코드(question_type.py)에서 옮김(시험만 씀, e2-17)."""
    items = json.loads((RES_ROOT / "vocab" / "qtype_labels.json").read_text(encoding="utf-8"))
    confusion, correct = {}, 0
    for it in items:
        qtype, _ = classify(it["question"])
        confusion.setdefault(it["type"], {}).setdefault(qtype, 0)
        confusion[it["type"]][qtype] += 1
        correct += qtype == it["type"]
    return correct / len(items), confusion


def selftest():
    assert classify("고객별 계약 건수 합계는?")[0] == "aggregate"
    assert classify("평균 배치 수는?")[0] == "aggregate"
    assert classify("현재 유효한 단가는?")[0] == "latest"
    assert classify("공정 흐름도에서 다음 단계는?")[0] == "figure"
    assert classify("로그 축 그래프에서 세포 수가 가장 높은 날은?")[0] == "figure"  # 그래프 — "가장 높은"은 MAXMIN_RE에 안 걸림(큰/작은만)
    assert classify("계약 목록을 모두 보여줘")[0] == "list"
    assert classify("A 제품과 B 제품의 단가 차이는?")[0] == "compare"
    assert classify("연도별 매출 추이는?")[0] == "trend"
    assert classify("MTOP의 정의는?")[0] == "term"
    assert classify("DSP란 무엇인가?")[0] == "term"
    assert classify("계약 체결일은?")[0] == "general"
    t, cfg = classify("현재 유효한 단가는?")
    assert cfg["search"]["recency"] == "2" and cfg["first_tool"] == "search"
    t, cfg = classify("흐름도에서 다음 단계는?")
    assert t == "figure" and cfg["first_tool"] == "search" and cfg["search"] == {}  # 기본 검색(독립 검토 10-06)
    t, cfg = classify("고객별 계약 건수는?")
    assert cfg["first_tool"] == "aggregate"
    # TYPE_TABLE의 cfg를 호출자가 바꿔도 다음 classify()는 영향 안 받음(깊은 복사, dict·list 공유 금지)
    _, cfg2 = classify("현재 유효한 단가는?")
    cfg2["search"]["recency"] = "x"
    _, cfg3 = classify("현재 유효한 단가는?")
    assert cfg3["search"]["recency"] == "2"

    acc, confusion = eval_labels()
    assert acc >= 0.55, f"유형 라우터 정확도 낮음: {acc:.2f}\n{json.dumps(confusion, ensure_ascii=False, indent=1)}"
    print(f"[selftest] 질문 유형 라우터 — 고정 세트 정확도 {acc:.2%}, 혼동 행렬:\n{json.dumps(confusion, ensure_ascii=False, indent=1)}")
    print("[selftest] 질문 유형 라우터 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
