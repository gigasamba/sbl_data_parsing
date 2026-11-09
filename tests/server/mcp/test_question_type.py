"""mcp_server.services.search.question_type 시험."""

from mcp_server.services.search.question_type import AGGREGATE_RE


def test_main():
    for question, want in (
        ("고객별 계약 건수 합계는?", True),
        ("평균 배치 수는?", True),
        ("고객별 계약 건수는?", True),
        ("가장 큰 계약은?", True),
        ("몇 개월 걸리나?", False),  # 기간 — 건수 질문 아님
        ("현재 유효한 단가는?", False),
        ("로그 축 그래프에서 세포 수가 가장 높은 날은?", False),  # "가장 높은"은 안 걸림(큰/작은만)
        ("계약 체결일은?", False),
    ):
        assert bool(AGGREGATE_RE.search(question)) is want, (question, want)
