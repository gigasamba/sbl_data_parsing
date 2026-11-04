"""common.core.docmeta 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.docmeta`."""

from common.core.docmeta import (
    _format_tier,
    copy_groups,
    copy_key,
    copy_representative,
    extract_date,
    extract_version,
    is_superseded,
)


def selftest():
    # 날짜 — 한글·영문, 파일명·본문, 전체·연월·연도만
    assert extract_date("report_2026-05-01.pdf", "") == "2026-05-01"
    assert extract_date("report.pdf", "작성일 2026년 5월 1일 발행") == "2026-05-01"
    assert extract_date("report.pdf", "Effective Date: May 1, 2026 — draft") == "2026-05-01"
    assert extract_date("report.pdf", "Date: Wed, 19 Feb 2025 09:00:00 +1030") == "2025-02-19"
    assert extract_date("spec_2026.05.docx", "") == "2026-05"
    assert extract_date("spec.docx", "개정일 2026년 5월 — 내용") == "2026-05"
    assert extract_date("spec.docx", "Rev. May 2026") == "2026-05"
    assert extract_date("spec_2026.docx", "") == "2026"
    assert extract_date("spec.docx", "본 문서는 2026년 작성됨") == "2026"
    assert extract_date("faq.xlsx", "commercial perfusion is planned for 2027. | 46236 |") is None  # F6 — 본문 맨 연도는 날짜 아님
    assert extract_date("plan_2027.xlsx", "planned for 2030") == "2027"  # 파일명의 연도는 그대로
    assert extract_date("spec.docx", "") is None
    # 본문 우선(파일명이 속일 수 있음 — holdout 실측 패턴)
    assert extract_date("final_v2.docx", "작성일 2025-09-01") == "2025-09-01"
    assert extract_date("final_real.docx", "작성일 2025-06-01") == "2025-06-01"
    print("[selftest] 날짜 추출(한글·영문·본문 우선) 통과")

    # 개정·버전
    assert extract_version("msa_v2.docx", "") == "2"
    assert extract_version("msa.docx", "Rev.2 2026-05-01 개정") == "2"
    assert extract_version("msa.docx", "개정 3차 변경사항") == "3"
    assert extract_version("msa.docx", "Version 1.2 draft") == "1.2"
    assert extract_version("msa_amendment_2.pdf", "") == "2"
    assert extract_version("plain.docx", "no version info") is None
    print("[selftest] 개정·버전 추출 통과")

    # 구판 표지
    assert is_superseded("[구판] 이전 개정판(최신본 아님)\n본문") is True
    assert is_superseded("This document is SUPERSEDED by rev 3") is True
    assert is_superseded("정상 문서 본문") is False
    print("[selftest] 구판 표지 통과")

    # family 키·최신성 순위(recency_rerank)·연도 지목은 pl-38(사용자 11-03)에 지움 — 잠재 문제는 PRD pl-38

    # R2-c 요건① — 사본 그룹(실 코퍼스 실측 수치로 보정한 임계값): 같은 메일 다른 형식은 묶고, 다른 계약서는 안 묶음
    body = "MRH-MAB-01 기술이전 관련 문의드립니다. 1차 트랜스퍼 배치 완료, 추가 배치 3회 계획입니다. 제안 단가 434,000,000 KRW/batch"
    items = [
        {"file_name": "MAIL-MRH-02.eml", "text": f"From: a\nTo: b\nSubject: x\n{body}"},
        {"file_name": "MAIL-MRH-02.msg", "text": f"From: a\nTo: b\nDate: 2025-04-08\nSubject: x\n{body}"},
        {"file_name": "mailshot_MAIL-MRH-02.png", "text": f"Gmail\nx\na\nto b\n2025-04-08\n{body}\n\n# x\n{body[:40]}"},
        {"file_name": "C-MRH-2020-05.pdf", "text": "계약 번호 C-MRH-2020-05 단가 및 조건이 전혀 다른 본문입니다 " * 5},
    ]
    groups = copy_groups(items)
    assert groups == {0: [1, 2]}, groups  # 대표는 원래 순위 0번(가장 앞), eml·msg·mailshot만 묶임 · 계약서는 별개
    assert copy_key("mailshot_MAIL-MRH-02.png") == copy_key("MAIL-MRH-02.eml") == "mail-mrh-02"
    assert copy_groups([{"file_name": "a.pdf", "text": "x"}]) == {}  # 1건이면 그룹 없음
    print("[selftest] 사본 그룹(copy_key 후보 + 본문 유사도) 통과")

    # engine-qa CONCERN(QA066) — 대표 텍스트는 순위가 아니라 형식(eml>msg>htm/mht>docx/pdf류>이미지)·본문 길이로
    assert (
        _format_tier("x.eml")
        > _format_tier("x.msg")
        > _format_tier("x.htm")
        > _format_tier("x.pdf")
        > _format_tier("x.png")
        > _format_tier("x.xyz")
    )
    members = [
        {"file_name": "mailshot_MAIL-MRH-02.png", "text": "짧은 OCR 조각(배치 문장 없음)"},  # 0번 — 순위 1위지만 이미지
        {"file_name": "MAIL-MRH-02.eml", "text": "...1차 배치 완료, 추가 배치 3회 계획..."},  # 1번 — eml, 배치 문장 있음
        {"file_name": "MAIL-MRH-02.msg", "text": "...1차 배치 완료, 추가 배치 3회 계획..."},
    ]  # 2번 — msg, 배치 문장 있음
    best = copy_representative(members)
    assert members[best]["file_name"] == "MAIL-MRH-02.eml" and "배치" in members[best]["text"], members[
        best
    ]  # eml(형식 우선, msg와 동일 길이면 먼저 나온 쪽)
    tie_len = [{"file_name": "x.pdf", "text": "aaaaa"}, {"file_name": "y.docx", "text": "bb"}]
    assert copy_representative(tie_len) == 0  # 같은 형식 등급이면 본문이 더 긴 쪽
    print("[selftest] 사본 대표 선택(형식 우선·동률이면 긴 본문, QA066 재발 방지) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
