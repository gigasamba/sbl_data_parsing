"""mcp_server.services.search.terms 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.terms`."""

from common.core.terms import load_glossary
from common.core.text import tokens
from mcp_server import config as mc
from mcp_server.services.search.terms import _exp_tokens, expand_query, match_concepts, vector_alias_text


def _selftest_glossary_rows():
    """match_concepts·expand_query·lookup_term 공용 작은 사전(common.core.terms 쪽 선택테스트와 같은 표본) — 이
    모듈 자체 selftest용으로 로컬 복제(공용 테스트 자산을 이미지 경계 너머로 끌어오지 않음)."""
    return {
        "A": {
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
        "B": {
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
        "C": {
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
    }


def selftest():
    g = _selftest_glossary_rows()

    # 질문 확장 — 동음이의 약어는 context_required 있을 때만, 가중치 1.0/0.8/0.3
    t, notes = expand_query("VI 공정에서 pH 조건은?", g)
    assert t.get("viral") == 1.0 and t.get("inactivation") == 1.0 and notes  # context(pH) 있어 A가 확장됨(abbreviation VI는 이미 base 토큰)
    t2, notes2 = expand_query("VI 결과 보고", g)  # context 단어 없음 — VI만으로는 어느 쪽인지 모름
    assert not notes2 and "viral" not in t2 and "육안검사" not in " ".join(t2)
    t3, notes3 = expand_query("vial 이물 VI 결과", g)
    assert any("Visual Inspection" in n for n in notes3)  # context(vial·이물) 있어 C가 확장됨
    t4, _ = expand_query("바이러스 불활화 공정", g)  # 동의어 매치 → 약어 VI는 0.8로 추가(canonical 1.0 함께)
    assert t4.get("vi") == 0.8 and t4.get("viral") == 1.0, t4
    t5, n5 = expand_query("DSP 수율", g)  # context_required 없는 보통 약어는 바로 확장
    assert n5 and t5.get("downstream") == 1.0
    with mc.senv(QUERY_EXPAND="0"):
        t6, n6 = expand_query("VI 공정에서 pH 조건은?", g)
        assert not n6 and set(t6) == set(tokens("VI 공정에서 pH 조건은?"))

    # 개념 조회
    assert match_concepts("바이러스 불활화", g) == ["A"]
    print("[selftest] 질문 확장(동음이의 문맥 조건)·match_concepts 통과")

    _selftest_legal_suffix()
    _selftest_alias_roster()
    _selftest_case_insensitive_glossary()
    _selftest_vector_alias_text()


def _selftest_legal_suffix():
    """BR58 — _exp_tokens가 glossary 문자열을 토큰화한 뒤 숫자가 아닌 한 글자 토큰("미르하제약(주)"의 "주" 류)만
    빼는지 · "Inc."(2자 이상)는 그대로 남는지(실측: 통째로 지우면 pfizer_global_supply_2026.txt vs
    화이자_한국지사_계약_2026.txt 쌍둥이 문서 분간 신호가 없어져 XL012·XL014가 새로 미스가 됐었다) ·
    QUERY_EXPAND_SHORTTOK=0이면 바이트 동일(옛 동작)."""
    assert "주" not in _exp_tokens("미르하제약(주)")
    assert "미르하제약" in _exp_tokens("미르하제약(주)")  # 긴 토큰은 그대로
    assert "inc." in _exp_tokens("Pfizer Inc.")  # 2자 이상 영문 접미는 안 건드림(분간 신호일 수 있음)
    assert "주" in tokens("미르하제약(주)")  # tokens() 자체는 안 바뀜(바이트 동일) — 거르기는 _exp_tokens에서만

    g = {
        "G": {
            "concept_id": "G",
            "canonical": "미르하제약(주)",
            "category": "org_client",
            "synonyms": "미르하",
            "abbreviations": "MRH",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "definition_ko": "",
            "definition_en": "",
            "status": "approved",
        }
    }
    t, notes = expand_query("미르하 견적서의 배치당 가격은?", g)
    assert "주" not in t and any("미르하" in n for n in notes), (t, notes)  # 법인 표기 괄호에서 나온 '주' 토큰 없음
    assert t.get("미르하제약") == 1.0 and t.get("mrh") == 0.8  # 그 외 토큰은 그대로

    with mc.senv(QUERY_EXPAND_SHORTTOK="0"):
        t_off, _ = expand_query("미르하 견적서의 배치당 가격은?", g)
        assert t_off.get("주") == 1.0  # 끔 — 옛 동작(한 글자 토큰도 그대로)과 바이트 동일
    print("[selftest] BR58 — _exp_tokens(글로서리 확장의 뜻 없는 한 글자 토큰만 거름, QUERY_EXPAND_SHORTTOK=0이면 바이트 동일) 통과")


def _selftest_alias_roster():
    """SI43⑥⑦ — lookup_term이 명부(roster) 별칭도 같이 줌(용어집 synonyms만이 아니라 stack.json·CLIENT_ROSTER
    병합분까지) · 한글 고유명사 뒤 조사(실측: '셀트리온과'가 안 잡힘) · 명부(roster)만 있는 별칭도 expand_query가
    쓰는지(XL008 — 용어집엔 없음). _aliases()는 glossary 인자가 아니라 GLOSSARY_DIR env를 보므로(공용 로더 한 곳),
    common.core.terms._selftest_si43()과 같은 환경(GLOSSARY_DIR·CLIENT_ROSTER)으로 맞춘다."""
    import csv
    import tempfile
    from pathlib import Path

    rows = [
        {
            "concept_id": "E",
            "canonical": "Celltrion",
            "category": "org_client",
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
        }
    ]
    d = Path(tempfile.mkdtemp())
    with (d / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    g = load_glossary(d)

    f = Path(tempfile.mkdtemp()) / "roster.csv"
    f.write_text("name,aliases\nCelltrion,CT Inc\n", encoding="utf-8")
    _env = mc.senv(
        GLOSSARY_DIR=str(d), CLIENT_ROSTER=str(f)
    )  # 인계 파일(common.core.terms)이 env로 읽음 — senv가 os.environ에도 쓰고 되돌림(S7d)
    try:
        # ⑦ 한글 고유명사 뒤 조사 — '셀트리온과'(명부·용어집 둘 다)
        t, n = expand_query("셀트리온과 맺은 공급 계약", g)
        assert t.get("celltrion") == 1.0 and any("Celltrion" in x for x in n), (t, n)
        t3, n3 = expand_query("셀트리온스타일 이야기", g)  # 뒤가 조사 아닌 한글 — 어간 불일치는 오탐 금지
        assert "celltrion" not in t3 and not any("Celltrion" in x for x in n3), (t3, n3)

        # 명부(roster)만 있는 별칭도 expand_query가 씀(XL008 — 용어집엔 없음)
        t4, n4 = expand_query("CT Inc와 맺은 계약", g)
        assert t4.get("셀트리온") == 1.0 and any("alias" in x for x in n4), (t4, n4)
    finally:
        _env.close()
    print("[selftest] SI43⑦ — 한글 조사(조사 뒤 오탐 금지)·roster 전용 별칭(XL008) expand_query 통과")


def _selftest_case_insensitive_glossary():
    """10-14 — 바이오/CDMO 용어 대소문자 무시 탐지(신규·확장 개념) + 짧은 약어(DS 등 3자 이하, 독립 검토①로
    2자→3자 확대 + weak_synonyms도 포함) 동음이의 방어(_entry_hit의 short-length 규칙) + CAPA(품질, 시정조치)·
    캐파/capa(사업, 생산능력)는 **대소문자로** 분리(독립 검토②③ — context_required로 분리하면 "CAPA 절차서의
    기록 보관 기간은?"처럼 문맥어가 없는 흔한 질문에서 QUAL.CAPA 확장이 빠져 synth-terms-hard evid_hit1·
    gold_top1 회귀(HQ-T011) — QUAL.CAPA는 그대로 case_sensitive=Y·context_required 없음(이 작업 전과 바이트
    동일), BIZ.CAPACITY만 소문자+문맥). 실제 기본 사전(glossary/domain_terms.csv)으로 검증 — 코드뿐 아니라 그
    CSV 데이터가 실제로 반영되는지까지 본다."""
    from common.core.paths import GLOSSARY_ROOT

    g = load_glossary(GLOSSARY_ROOT)

    # 전체 영문명·한/영 동의어 — 대소문자 섞여도(소문자·전체 대문자·한글) 잡힘
    for q in ("Drug substance 공정", "DRUG SUBSTANCE 생산", "원료의약품 생산"):
        assert match_concepts(q, g) == ["PROC.DS"], (q, match_concepts(q, g))
    for q in ("Drug product 충전", "DRUG PRODUCT 충전", "완제의약품 충전", "filled drug product 충전"):
        assert "PROC.DP" in match_concepts(q, g), (q, match_concepts(q, g))

    # 짧은 약어(DS, 2자) — 단어 중간(MSDS·words·adds)에서는 경계(\b) 때문에 안 걸림,
    # 소문자는 문맥(원료 등)이 있어야만, 문맥 없으면 대문자로 써도 기각(DS의 기존 context_required 그대로)
    assert "PROC.DS" not in match_concepts("MSDS 안전 자료", g)
    assert "PROC.DS" not in match_concepts("이 words 목록", g)
    assert "PROC.DS" not in match_concepts("adds 함수", g)
    assert "PROC.DS" in match_concepts("ds 원료 공정 확인", g)  # 소문자 + 문맥(원료)
    assert match_concepts("ds 결과 보고", g) == []  # 소문자·문맥 없음 — 기각
    assert match_concepts("DS 결과 보고", g) == []  # 대문자라도 문맥 없으면 기존 그대로 기각

    # CAPA(품질) vs 캐파/capa(사업, 생산능력) — 대소문자로 분리(문맥 아님): 대문자 "CAPA"는 QUAL.CAPA가 문맥
    # 무관하게 항상(이 작업 전과 바이트 동일 동작) · 소문자 "capa"/한글 "캐파"는 BIZ.CAPACITY가 문맥이 있을 때만
    assert match_concepts("CAPA 시정조치 완료", g) == ["QUAL.CAPA"]
    assert match_concepts("캐파 15,000 L 증설", g) == ["BIZ.CAPACITY"]
    assert match_concepts("capa 25만 리터 규모", g) == ["BIZ.CAPACITY"]
    assert match_concepts("CAPA 발행 완료", g) == ["QUAL.CAPA"]
    assert match_concepts("생산 capa 확대", g) == ["BIZ.CAPACITY"]
    assert match_concepts("설비 capa 증설", g) == ["BIZ.CAPACITY"]
    # 독립 검토③ 회귀 재현 방지(HQ-T011, synth-terms-hard) — 문맥어가 전혀 없는 흔한 "CAPA" 질문도
    # QUAL.CAPA가 여전히 걸려야 함(한때 context_required를 넣었다가 이 경우가 깨짐, 되돌림)
    assert match_concepts("CAPA 절차서의 기록 보관 기간은?", g) == ["QUAL.CAPA"]

    # 독립 검토①(10-14) — 3자 이하 약어(abbreviations·weak_synonyms 둘 다)의 소문자 잡음 방지:
    # "cmo"(BIZ.CDMO weak_synonym 경로로 새어나가던 것)·"cdo tranche"·"cro survey"·"dar window"는
    # 문맥 없이 매치되면 안 되고, 대문자 그대로("CMO 계약")는 그대로 걸려야 함
    for q in ("cmo", "cdo tranche", "cro survey", "dar window"):
        assert match_concepts(q, g) == [], (q, match_concepts(q, g))
    assert "BIZ.CMO" in match_concepts("CMO 계약", g)

    # expand_query — 한→영·영→한 양방향(新/확장 개념)
    t, notes = expand_query("원료의약품 수율", g)
    assert t.get("drug") == 1.0 and t.get("substance") == 1.0 and notes
    t2, notes2 = expand_query("drug substance yield", g)
    assert t2.get("원료의약품") == 1.0 and notes2

    # CDMO 확장 동의어(수탁개발생산 → CDMO)
    t3, notes3 = expand_query("수탁개발생산 업체", g)
    assert t3.get("cdmo") == 0.8 and notes3
    print(
        "[selftest] 10-14 — 바이오/CDMO 용어 대소문자 무시 탐지·짧은 약어(DS·CMO 등, 독립 검토①로 3자+"
        "weak_syn 확대) 동음이의 방어·CAPA(대문자, 품질)/캐파·capa(소문자, 사업) 대소문자 분리(독립 검토②③,"
        " 문맥 회귀 되돌림)·expand_query 양방향 통과"
    )


def _selftest_vector_alias_text():
    """SI43⑤ G17 — 벡터 질의 임베딩 입력에만 교차 문자 체계(한글↔라틴) 별칭을 덧붙이는지, 끔 스위치(=0)는
    바이트 동일인지."""
    aliases = {"Celltrion": ["셀트리온"]}
    aliases_q = "셀트리온과 맺은 공급 계약 조건은?"
    out = vector_alias_text(aliases_q, aliases)
    assert out == f"{aliases_q} (Celltrion)", out  # 셀트리온(ko) ↔ Celltrion(lat) — 교차언어라 덧붙음
    assert vector_alias_text("관련 없는 질문", aliases) == "관련 없는 질문"  # 매칭 없으면 그대로
    with mc.senv(SEARCH_VECTOR_ALIAS_EXPAND="0"):
        assert vector_alias_text(aliases_q, aliases) == aliases_q  # =0이면 꺼짐 — 바이트 동일
    print("[selftest] SI43⑤ G17 — vector_alias_text 교차 문자 체계 별칭 덧붙이기·끔 스위치 바이트 동일 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
