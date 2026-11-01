"""common.core.docmeta 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.docmeta`."""

from common.core.docmeta import (
    _format_tier,
    copy_groups,
    copy_key,
    copy_representative,
    extract_date,
    extract_version,
    family_key,
    is_superseded,
    pin_from_question,
    recency_rerank,
)


def selftest():
    import contextlib

    from common.config.settings import COMMON  # S7b — SEARCH_RECENCY 조작은 env 대신 설정 객체를 덮어씀

    _rec = contextlib.ExitStack()
    _rec.enter_context(
        COMMON.env(SEARCH_RECENCY="2")
    )  # 아래 순위 점검은 '늘' 모드로 메커니즘을 봄 — 기본(1, 최신 질문만) 게이트는 맨 끝에서 따로
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

    # family — 같은 문서군은 날짜·개정·복사본 토큰 차이만
    assert family_key("msa_v2.docx") == family_key("msa_v3.docx") == family_key("msa.docx")
    assert family_key("report_2026-05-01_old.pdf") == family_key("report_2025-04-01(1).pdf") == family_key("report.pdf")
    assert family_key("msa_amendment_1.pdf") == family_key("msa_amendment_2.pdf") == family_key("msa_amendment_3.pdf")
    assert family_key("sop_qc014_rev1.docx") == family_key("sop_qc014_rev2.docx")
    assert family_key("price_list_2024.xlsx") == family_key("price_list_2026.xlsx")
    assert family_key("msa.docx") != family_key("nda.docx")
    # 알려진 한계(ponytail — 과잉 병합 방지를 택함): "_real"처럼 날짜·개정·복사본 범주 밖의 낱말은 다른 family로 남음
    assert family_key("spec_final.docx") == family_key("spec_final_v2.docx") != family_key("spec_final_real.docx")
    print("[selftest] family 키 통과(알려진 한계: 범주 밖 낱말은 안 지움)")

    # L4-7 — GLOSSARY_DIR 없으면 오늘 동작 그대로(과병합, 알려진 한계) · 있으면 id_patterns.csv(contract_no)로 연도가
    # ID의 일부인 계약 번호는 안 지움(4clients C-PFE-2022-01 vs C-PFE-2024-03 실측 패턴)
    with COMMON.env(GLOSSARY_DIR=None):  # 설정 파일 값과 무관하게(사전 없음 → 있음 순서로 확인 — op-09 설정 객체)
        assert family_key("C-PFE-2022-01.pdf") == family_key("C-PFE-2024-03.pdf")
    from common.core.paths import GLOSSARY_ROOT

    with COMMON.env(GLOSSARY_DIR=str(GLOSSARY_ROOT)):
        assert family_key("C-PFE-2022-01.pdf") != family_key("C-PFE-2024-03.pdf")
        assert family_key("C-PFE-2024-02.pdf") == family_key("C-PFE-2024-02_v2.pdf")  # 같은 계약의 개정은 여전히 한 family
    print("[selftest] family 키 — id_patterns.csv로 계약 번호 과병합 방지(L4-7) 통과")

    # 최신성 순위 — 같은 family ≥2건이면 최신만 원 자리, 옛 것은 뒤로(지우지 않음)
    doc_of = {
        "a": {"doc_date": "2025-04", "version": "1", "superseded": False, "family": "msa"},
        "b": {"doc_date": "2026-05", "version": "2", "superseded": False, "family": "msa"},
        "c": {"doc_date": "2024-01", "version": None, "superseded": False, "family": "nda"},
    }
    hits = [
        {"doc_key": "a", "rank": 1, "text": "옛 msa"},
        {"doc_key": "b", "rank": 2, "text": "새 msa"},
        {"doc_key": "c", "rank": 3, "text": "nda"},
    ]
    out, note = recency_rerank(hits, doc_of, "단가는?")
    assert [h["doc_key"] for h in out] == ["b", "a", "c"] and note == "구판 1건 뒤로"  # L4-8: 옛 판은 최신본 바로 뒤
    out2, note2 = recency_rerank(hits, doc_of, None)  # family 2건 미만(c)이면 손 안 댐 — 단일 family(msa)만 적용
    assert note2 == note
    with COMMON.env(SEARCH_RECENCY="0"):  # 빠져나오면 다시 '늘' 모드로 이어짐
        out3, note3 = recency_rerank(hits, doc_of, "단가는?")
        assert out3 == hits and note3 is None  # 꺼짐 — 그대로
    print("[selftest] 최신성 순위(demote, 안 지움) · SEARCH_RECENCY=0 통과")

    # 최신 질문 — 여전히 지우지 않음(개정 3엔 없는 항목이 개정 2에만 있을 수 있음, holdout 실측)
    out4, note4 = recency_rerank(hits, doc_of, "msa 최신 기준 단가는?")
    assert [h["doc_key"] for h in out4] == ["b", "a", "c"] and note4.startswith("최신 질문 — ")
    # 특정 개정 지목 — 그 버전은 밀지 않음(지정 버전 유지) — a0(개정 0, 안 지목)는 밀리고 a(개정 1, 지목)는 그대로
    doc_of2 = {
        "a0": {"doc_date": "2023-01", "version": "0", "superseded": False, "family": "msa"},
        "a": {"doc_date": "2025-04", "version": "1", "superseded": False, "family": "msa"},
        "b": {"doc_date": "2026-05", "version": "2", "superseded": False, "family": "msa"},
    }
    hits2 = [{"doc_key": "a0", "rank": 1}, {"doc_key": "a", "rank": 2}, {"doc_key": "b", "rank": 3}]
    out5, note5 = recency_rerank(hits2, doc_of2, "msa Rev.1 기준 단가는?")
    assert [h["doc_key"] for h in out5] == ["a", "a0", "b"] and "지정 버전 유지" in note5
    # BR33(QA095 실측) — 같은 family에서 최신판이 청크 여러 개로 흩어져 kept에 있을 때, 옛 판은 최신판의
    # '마지막' occurrence 뒤로(첫 occurrence 뒤에 끼우면 최신판의 더 적합한 뒤쪽 청크가 옛 판보다 아래로 밀림).
    doc_of3 = {
        "new": {"doc_date": "2026-06", "version": "2", "superseded": False, "family": "rfp"},
        "old": {"doc_date": "2025", "version": "1", "superseded": False, "family": "rfp"},
    }
    hits3 = [
        {"doc_key": "new", "chunk": "weak"},
        {"doc_key": "old", "chunk": "strong(옛 판)"},
        {"doc_key": "new", "chunk": "strong(최신판 정답 청크)"},
        {"doc_key": "old", "chunk": "weak(옛 판)"},
    ]
    out7, note7 = recency_rerank(hits3, doc_of3, "최신 RFP 기준은?")
    assert [h["chunk"] for h in out7] == ["weak", "strong(최신판 정답 청크)", "strong(옛 판)", "weak(옛 판)"], out7
    print("[selftest] BR33 — 같은 문서의 흩어진 청크(최신판 여러 개)는 옛 판보다 전부 위, 삽입은 최신판 마지막 occurrence 뒤 통과")
    # 연도 지목 — 닻말("기준")이 연도 바로 뒤가 아니어도(중간에 낱말) 됨 · 닻말 없으면 평서문으로 보고 지목 아님
    assert pin_from_question("2025년 가격표 기준 단가는?") == (None, "2025")
    assert pin_from_question("2025년에 체결된 계약은?") == (None, None)
    assert pin_from_question("2025년 목록에서 Orion Media 상태는?") == (None, "2025")  # 연도+문서 명사(dev RD009)
    print("[selftest] 최신 질문(여전히 안 지움)·특정 버전·연도 지목(밀지 않음) 통과")
    # 10-05 회귀 — 날짜·개정 둘 다 없는 같은 이름 사본(동률)은 밀지 않음(set max로 실행마다 다르게 강등되던 결함), 엄격히 오래된 것만 뒤로
    tie = {"a": {"family": "x"}, "b": {"family": "x"}, "o": {"family": "y", "doc_date": "2024"}, "n": {"family": "y", "doc_date": "2025"}}
    out6, _ = recency_rerank([{"doc_key": k} for k in ("o", "a", "b", "n")], tie, "단가는?")
    assert [h["doc_key"] for h in out6] == ["a", "b", "n", "o"], out6
    print("[selftest] 동률은 그대로·엄격히 오래된 것만 뒤로(결정적) 통과")
    _rec.enter_context(
        COMMON.env(SEARCH_RECENCY="1")
    )  # 기본 — 최신을 묻지 않는 질문은 순위 그대로(4clients 연도별 다른 계약 오강등 방지, 10-05)
    same, n1 = recency_rerank([{"doc_key": k} for k in ("o", "a", "b", "n")], tie, "o 계약의 단가는?")
    lat, n2 = recency_rerank([{"doc_key": k} for k in ("o", "a", "b", "n")], tie, "최신 단가는?")
    assert [h["doc_key"] for h in same] == ["o", "a", "b", "n"] and n1 is None and [h["doc_key"] for h in lat][-1] == "o"
    _rec.close()  # SEARCH_RECENCY 덮어쓰기 모두 해제
    print("[selftest] 기본 모드: 최신 질문에서만 순위 조정 통과")

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
