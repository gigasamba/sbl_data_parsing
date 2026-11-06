"""common.core.terms(인계 파일 — FINGERPRINT) 자기 점검."""

import os
from pathlib import Path

from common.config.settings import COMMON
from common.core.terms import (
    _aliases,
    _draft_count,
    draft_terms_path,
    load_draft_glossary,
    load_glossary,
    load_id_patterns,
    load_id_patterns_typed,
    match_clients,
    read_roster,
    related_concepts,
    write_draft_terms,
)


def selftest():
    import csv
    import tempfile

    rows = [
        {
            "concept_id": "A",
            "canonical": "Viral Inactivation",
            "category": "process",
            "synonyms": "바이러스 불활화",
            "abbreviations": "VI",
            "weak_synonyms": "low pH hold",
            "broader": "B",
            "related": "",
            "context_required": "pH|virus|바이러스|불활화",
            "case_sensitive": "Y",
            "definition_ko": "저 pH 유지 불활화",
            "definition_en": "",
            "status": "approved",
        },
        {
            "concept_id": "B",
            "canonical": "Downstream Process",
            "category": "process",
            "synonyms": "",
            "abbreviations": "DSP",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "하류 공정",
            "definition_en": "",
            "status": "approved",
        },
        {
            "concept_id": "C",
            "canonical": "Visual Inspection",
            "category": "quality",
            "synonyms": "육안검사",
            "abbreviations": "VI",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "vial|이물",
            "case_sensitive": "Y",
            "definition_ko": "외관 검사",
            "definition_en": "",
            "status": "approved",
        },
        {
            "concept_id": "D",
            "canonical": "draft concept",
            "category": "process",
            "synonyms": "",
            "abbreviations": "",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "",
            "definition_en": "",
            "status": "draft",
        },
    ]
    fields = list(rows[0])
    d = Path(tempfile.mkdtemp())
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    g = load_glossary(d)
    assert set(g) == {"A", "B", "C"}, g  # draft는 빠짐(status=approved만)

    # 참조 해소 — 끊긴 broader
    bad = list(rows)
    bad[0] = {**bad[0], "broader": "없는ID"}
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(bad)
    try:
        load_glossary(d)
        raise AssertionError("끊긴 참조가 통과함")
    except ValueError:
        pass
    # 개념 ID 중복
    dup = list(rows)
    dup.append({**rows[1], "concept_id": "A"})
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(dup)
    try:
        load_glossary(d)
        raise AssertionError("ID 중복이 통과함")
    except ValueError:
        pass
    # id_patterns.csv 정규식 오류
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with (d / "id_patterns.csv").open("w", encoding="utf-8") as fh:
        fh.write("id_type,regex,example,note,updated\nbad,[A-Z(,x,,\n")
    try:
        load_glossary(d)
        raise AssertionError("깨진 정규식이 통과함")
    except ValueError:
        pass
    (d / "id_patterns.csv").unlink()
    g = load_glossary(d)

    # load_id_patterns_typed(id_type 보존) vs load_id_patterns(정규식만, 기존 호출자 불변)
    (d / "id_patterns.csv").write_text(
        'id_type,regex,example,note,updated\ncontract_no,"C-[A-Z]{2,4}-\\d{4}-\\d{2}",C-PFE-2024-02,,\nlot_no,"LOT-\\d{4}-\\d{3,}",LOT-2025-324,,\n',
        encoding="utf-8",
    )
    typed = load_id_patterns_typed(d)
    assert [t for t, _ in typed] == ["contract_no", "lot_no"]
    assert [p.pattern for p in load_id_patterns(d)] == [p.pattern for _, p in typed]  # 기존 함수는 정규식만(순서·개수 동일)
    assert typed[0][1].search("문서에 C-PFE-2024-02 계약").group(0) == "C-PFE-2024-02"
    (d / "id_patterns.csv").unlink()
    assert load_id_patterns_typed(d) == [] and load_id_patterns(d) == []  # 파일 없으면 둘 다 빈 목록
    print("[selftest] AD28② load_id_patterns_typed(id_type 보존)·load_id_patterns 하위 호환 통과")

    # 개념 간 관계(related) — match_concepts·expand_query·lookup_term은 data_retrieval.tools.terms로 이동(그 쪽
    # selftest가 같은 표본으로 본다), related_concepts는 탐색·설명용으로 공용에 남아 여기서 본다.
    assert related_concepts("A", g) == [{"concept_id": "B", "canonical": "Downstream Process"}]
    print("[selftest] 용어 사전 로더·검증·related_concepts 통과")
    # 빈칸 허용(외부에서 채운 100+ 고객·용어집): status 빈칸=approved · concept_id 빈칸=AUTO.<이름> · cp949
    blank = [
        {"concept_id": "", "canonical": "Viral Inactivation", "synonyms": "바이러스 불활화"},
        {"concept_id": "", "canonical": "Viral Inactivation", "synonyms": "VI"},  # 같은 용어 ID 없이 두 번 — 뒤 줄 건너뜀(오류 아님)
        {"concept_id": "Q.OOS", "canonical": "Out of Specification", "status": ""},
        {"concept_id": "", "canonical": ""},
        {"concept_id": "D.X", "canonical": "Draft One", "status": "draft"},
    ]
    with (d / "domain_terms.csv").open("w", encoding="cp949", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["concept_id", "canonical", "synonyms", "status"])
        w.writeheader()
        w.writerows(blank)
    assert sorted(load_glossary(d)) == ["AUTO.Viral_Inactivation", "Q.OOS"], sorted(load_glossary(d))
    rp = d / "client_roster.csv"
    nl = chr(10)
    rp.write_text(
        nl.join(
            [
                "client_id,canonical_name,name_ko,aliases,client_type,status",
                "C1,Hanbit Biologics,한빛바이오로직스,Hanbit Co|한빛,customer,active",
                "P1,,그린셀랩,GreenCell Lab,prospect,",
                "C9,Old Bio,,,customer,inactive",
                "C8,,,,prospect,",
            ]
        )
        + nl,
        encoding="utf-8-sig",
    )
    ro = read_roster(rp)
    assert ro == {"Hanbit Biologics": ["Hanbit Co", "한빛", "한빛바이오로직스"], "그린셀랩": ["GreenCell Lab"]}, ro
    rp.write_text(nl.join(["name,aliases", "Old Format Bio,올드|OFB"]) + nl, encoding="utf-8")  # 옛 형식 그대로
    assert read_roster(rp) == {"Old Format Bio": ["올드"]}, read_roster(rp)  # OFB(영문 3자)는 뺌 — 기존 규칙
    print("[selftest] 10-15 빈칸 허용 — 용어집(status·concept_id 빈칸·cp949)·고객 명부 새 형식(name_ko 대체·inactive 제외)·옛 형식 통과")

    _selftest_si43()
    _selftest_si43_draft_blocker()


def _selftest_si43():
    """category 다중 태그(org_client|org_cdmo)·명부 병합·match_clients 한글 조사('셀트리온과'도 잡히는지).
    lookup_term·expand_query는 검색 쪽 시험(tests/server/mcp/test_query_expand.py)이 본다."""
    import csv
    import tempfile

    rows = [
        {
            "concept_id": "E",
            "canonical": "Celltrion",
            "category": "org_client|org_cdmo",
            "synonyms": "셀트리온",
            "abbreviations": "",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "",
            "definition_en": "",
            "status": "approved",
        },
        {
            "concept_id": "F",
            "canonical": "Lonza",
            "category": "org_cdmo",
            "synonyms": "론자",
            "abbreviations": "",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "",
            "definition_en": "",
            "status": "approved",
        },
    ]
    fields = list(rows[0])
    d = Path(tempfile.mkdtemp())
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # ① 다중 태그 — org_client|org_cdmo는 고객 명부에 들어가고(기존 org_cdmo 한 칸은 안 들어감) ② 동의어(한·영) 병합
    from types import SimpleNamespace
    from unittest import mock

    from common.store import master

    tables = {"domain_terms": list(csv.DictReader((d / "domain_terms.csv").read_text(encoding="utf-8-sig").splitlines()))}
    fake = SimpleNamespace(hash="test-si43", rows=lambda n: tables.get(n, []))  # 옛 행 모양을 바로 주는 가짜 마스터
    with mock.patch.object(master, "get", lambda: fake):  # 명부·용어 사전은 마스터 표에서(시험은 가짜 마스터)
        al = _aliases()
        assert al.get("Celltrion") == ["셀트리온"], al  # org_client 태그 있음 — 명부에
        assert "Lonza" not in al, al  # org_cdmo 한 칸만 — 명부에 안 들어감(기존 동작 호환)
        assert match_clients("셀트리온 계약", ["Celltrion"]) == ["Celltrion"]

    # 한글 고유명사 뒤 조사 — match_clients도 _name_hit 규칙 공유('셀트리온과'도 잡혀야 함)
    assert match_clients("셀트리온과 계약", ["Celltrion"], {"Celltrion": ["셀트리온"]}) == ["Celltrion"]
    print("[selftest] SI43①② — category 다중 태그·명부 병합·match_clients 한글 조사(조사 뒤 오탐 금지) 통과")


def _selftest_si43_draft_blocker():
    """draft 파일이 output/ 아래(GLOSSARY_DIR 아님) · 반복 호출은 새 행이 아니라
    카운트만 올림 · DRAFT_TERMS_MAX를 넘으면 카운트가 가장 낮은 것부터 쳐냄 · 원자적 쓰기(.tmp 안 남음) ·
    잠금을 못 잡으면(경합) 예외 없이 빈 목록."""
    import tempfile

    d = Path(tempfile.mkdtemp())
    out = d / "nested" / "draft.csv"  # 상위 폴더가 없어도(mkdir) 동작

    added1 = write_draft_terms(["Alpha Biologics Inc.", "Beta Pharma Co."], out, category="org_client")
    assert added1 == ["Alpha Biologics Inc.", "Beta Pharma Co."], added1
    assert not list(d.glob("**/*.tmp*"))  # 원자적 — 임시 파일이 안 남음
    draft = load_draft_glossary(out)
    assert len(draft) == 2 and all(r["category"] == "org_client" and r["status"] == "draft" for r in draft.values())
    assert all(_draft_count(r["source"]) == 1 for r in draft.values())

    # 같은 이름 다시 — 새 행 없이 카운트만 +1(여러 구조화 실행에 걸쳐 되풀이 — "가장 빈번한 것" 신호)
    added2 = write_draft_terms(["Alpha Biologics Inc."], out, category="org_client")
    assert added2 == []
    draft2 = load_draft_glossary(out)
    assert len(draft2) == 2
    cnt = {r["canonical"]: _draft_count(r["source"]) for r in draft2.values()}
    assert cnt["Alpha Biologics Inc."] == 2 and cnt["Beta Pharma Co."] == 1, cnt

    # 캡 — DRAFT_TERMS_MAX(설정 객체로 낮춤 — 모듈을 __main__으로 돌릴 때의 모듈 중복 함정을 피함, _draft_terms_max
    # 참고)를 낮춰서 가장 빈번한 것만 남는지(Beta는 카운트 1, 새로 들어오는 건 카운트 1이라 동률 — 결정적 순서
    # (이름 오름차순 tie-break)로 하나만 남아야 함)
    with COMMON.env(DRAFT_TERMS_MAX="1"):
        write_draft_terms(["Gamma Biologics Inc."], out, category="org_client")  # Alpha(count=2)가 가장 빈번 — 남아야 함
        draft3 = load_draft_glossary(out)
        assert len(draft3) == 1 and next(iter(draft3.values()))["canonical"] == "Alpha Biologics Inc.", draft3

    # 경합 — 잠금을 미리 쥐고 있으면 예외 없이 빈 목록(구조화를 막지 않음). DRAFT_TERMS_LOCK_TIMEOUT로 짧게(시험 속도)
    lock_path = Path(str(out) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        import time as _time

        t0 = _time.time()
        with COMMON.env(DRAFT_TERMS_LOCK_TIMEOUT="0.2"):
            res = write_draft_terms(["Delta Biologics Inc."], out, category="org_client")
        assert res == []
        assert _time.time() - t0 < 10.0  # 금방 포기(짧은 타임아웃 0.2초) — 컨테이너 첫 실행 부하를 감안해 넉넉히
    finally:
        lock_path.unlink(missing_ok=True)

    # GLOSSARY_DIR이 아니라 output/ 기본 경로를 쓰는지(인자·설정 둘 다 안 주면)
    tmp_out = Path(tempfile.mkdtemp()) / "auto.csv"
    with COMMON.env(DRAFT_TERMS_OUT=str(tmp_out)):
        assert draft_terms_path() == tmp_out
        write_draft_terms(["Epsilon Biologics Inc."], category="org_client")
        assert tmp_out.exists()
    print(
        "[selftest] SI43③④ 독립 검토 BLOCK 1 — draft output/ 경로(GLOSSARY_DIR 아님)·반복 호출은 카운트만 증가·"
        "DRAFT_TERMS_MAX 캡(최빈값 유지)·원자적 쓰기·잠금 경합 시 예외 없이 빈 목록 통과"
    )


def test_main():
    selftest()
