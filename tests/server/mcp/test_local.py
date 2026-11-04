"""mcp_server.services.search.local 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.local`."""

from mcp_server import config as mc
from mcp_server.services.search.local import IndexMismatch, embed_query, entity_hints, tie_break, weights


def selftest():
    """local.py의 남은 도우미(weights·tie_break·entity_hints·embed_query) — Local 검색 엔진은 mc-01(11-01)에 지움
    (그 BM25 가중·BR32 ID 문턱·OP1 숨김 시험은 PG 경로로 test_retriever에 옮김)."""
    # G14 — weights(question) 질문 유형별 가중치(SEARCH_W_BM25_TABLE)
    with mc.senv(SEARCH_W_BM25_TABLE=None, SEARCH_W_BM25=None):  # 설정 객체 덮기(S7d — 끝나면 되돌림)
        w0 = weights()
        assert w0 == {"vector": 1.0, "bm25": 1.0, "id": 2.0}, w0  # 기본값(BR58 1.3은 10-12 되돌림) — question 없음
        assert weights(None) == w0  # question 없으면(아무 데서나 호출) 그대로
        assert weights("단가는 얼마인가요?") == w0  # 집계형 아닌 질문 — 그대로
        w_table = weights("고객별 계약 건수 합계는?")  # 집계형(qtype.classify()=="aggregate") — bm25만 낮춤
        assert w_table["vector"] == 1.0 and w_table["id"] == 2.0 and w_table["bm25"] == 0.2, w_table
        with mc.senv(SEARCH_W_BM25_TABLE="0.05"):
            assert weights("몇 건입니까?")["bm25"] == 0.05  # env로 값 바꿈
    print("[selftest] G14 weights(question) 질문 유형별 가중치(SEARCH_W_BM25_TABLE) 통과")

    _selftest_tie_break()
    _selftest_index_mismatch()


def _selftest_tie_break():
    """BR41 — tie_break()·entity_hints() 단위 점검(DB 없이, 순수 함수).
    동점 구간(상대 오차 TIE_EPS_REL 안) + 질문에 나온 고객 엔티티가 한쪽 문서(B)에만 맞으면 B가 앞으로(A는
    동점이 아닌 C는 그대로 — 안정 정렬, 구간 밖은 안 건드림) · 질문에 엔티티 없음·동점 아님
    이면 셋 다 바이트 동일(그대로)."""
    ordered = [1, 2, 3]  # A(1) 1위, B(2)·C(3)는 A와 거의 동점
    scores = {1: 1.0, 2: 0.9995, 3: 0.3}  # 1↔2 상대 오차 5e-4 < 1e-3(동점) · 3은 멀어 동점 아님
    docmeta = {1: ("a.txt", "Acme", None, None), 2: ("b.txt", "Beta Co", None, None), 3: ("c.txt", "Acme", None, None)}
    out = tie_break(ordered, scores, docmeta, "Beta Co 계약은?")
    assert out == [2, 1, 3], out  # 질문이 Beta Co를 가리킴 — 동점 구간(1·2)만 B가 앞으로, C(동점 아님)는 그대로

    same = tie_break(ordered, scores, docmeta, "아무 질문")  # 질문에 Acme·Beta Co 둘 다 안 나옴 — 바이트 동일
    assert same == ordered, same
    none_ent = tie_break(ordered, scores, docmeta, "")  # 질문 없음 — 바이트 동일
    assert none_ent == ordered, none_ent

    not_tied = tie_break(
        [1, 2], {1: 1.0, 2: 0.5}, {1: ("a.txt", "Acme", None, None), 2: ("b.txt", "Beta Co", None, None)}, "Beta Co 계약은?"
    )
    assert not_tied == [1, 2], not_tied  # 상대 오차 5e-1 — 동점 범위 밖(eps=1e-3)이면 안 건드림

    # 실측 회귀(QA093·R2Q005) 재현 방지 — 질문의 제품코드가 다른 문서의 파일명에 그대로 적혀 있어도(구조화
    # product_code 필드가 그 값이 아니면) 안 끌려옴. 구조화 필드 정확 일치만(파일명 부분 일치 없음).
    # id_patterns(product_code 정규식)는 마스터 표(pl-38 — PC는 git CSV로 채운 SQLite 대역)에서 load_id_patterns_typed가 읽음.
    fn_trap = tie_break(
        [10, 11],
        {10: 1.0, 11: 0.9995},
        {10: ("hub_data.xlsx", None, None, None), 11: ("hub_report_LUX-VAC-03.docx", None, None, None)},
        "LUX-VAC-03 제품의 배치 수는?",
    )
    assert fn_trap == [10, 11], fn_trap  # 파일명에 코드가 있어도 product_code 필드가 비어 있으면 그대로(안 끌림)
    fn_real = tie_break(
        [10, 11],
        {10: 1.0, 11: 0.9995},
        {10: ("hub_data.xlsx", None, None, None), 11: ("hub_report_LUX-VAC-03.docx", None, None, "LUX-VAC-03")},
        "LUX-VAC-03 제품의 배치 수는?",
    )
    assert fn_real == [11, 10], fn_real  # product_code 필드가 실제로 맞으면(구조화 메타) 앞으로

    # entity_hints — 계약번호·제품코드(id_patterns.csv)도 질문 문자열에서 그대로 집음(사전 있는 환경에서만, 없으면 빈 집합)
    m_cl, mi = entity_hints("C-PFE-2024-02 계약 배치 수는?", [])
    assert m_cl == set() and (mi == {"C-PFE-2024-02"} or mi == set()), (
        m_cl,
        mi,
    )  # GLOSSARY_DIR 미설정이면 mi도 빈 집합(사전 선택 장치 — load_glossary와 같은 원칙)
    print(
        "[selftest] BR41 tie_break·entity_hints — 동점 구간만·질문 엔티티 맞는 문서 앞으로·동점 아니면 안 건드림·"
        "구조화 필드 정확 일치만(파일명 부분 일치 없음, QA093·R2Q005 회귀 재현 방지) 통과"
    )


def _selftest_index_mismatch():
    """AD41 — api 색인의 embed_model과 이 프로세스 EMBED_MODEL이 다르면 임베딩 호출 전에 IndexMismatch(ValueError)."""
    with mc.senv(EMBED_MODEL="m-b"):  # 설정 객체 덮기(S7d — 끝나면 되돌림)
        try:
            embed_query({"embed": "api", "embed_model": "m-a", "dim": 4}, "q")
            raise AssertionError("불일치인데 통과")
        except IndexMismatch as e:
            assert "m-a" in str(e) and not isinstance(e, (RuntimeError, OSError))
        with mc.senv(EMBED_MODEL=None):
            try:
                embed_query({"embed": "api", "embed_model": "m-a", "dim": 4}, "q")
                raise AssertionError("EMBED_MODEL 없음인데 통과")
            except IndexMismatch:
                pass
    print("[selftest] AD41 — 질의 임베딩 모델 ≠ 색인 meta면 거부(키워드 검색으로 조용히 안 떨어짐) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
