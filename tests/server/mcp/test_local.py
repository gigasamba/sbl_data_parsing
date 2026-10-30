"""mcp_server.services.search.local 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.local`."""

from collections import Counter
from pathlib import Path

from common.core.paths import GLOSSARY_ROOT
from mcp_server import config as mc
from mcp_server.services.search.local import IndexMismatch, Local, embed_query, entity_hints, tie_break, weights


def selftest():
    """BM25 가중 질의어(X3) — Local 인스턴스 없이 bm25()만(self 자리에 필요한 속성만 둔 가짜 객체)."""
    import types

    fake = types.SimpleNamespace(
        n=3,
        avg=3.0,
        chunks=[{"n_terms": 3}, {"n_terms": 4}, {"n_terms": 2}],
        tf=[Counter({"a": 1, "b": 1}), Counter({"a": 2}), Counter({"b": 1})],
        df=Counter({"a": 2, "b": 2}),
    )
    r_list = Local.bm25(fake, ["a", "b"], 3)
    r_dict1 = Local.bm25(fake, {"a": 1.0, "b": 1.0}, 3)
    assert r_list == r_dict1 == [0, 1, 2], r_list  # 확장 없음(리스트=전부 1.0) — 기존 동작과 동일
    r_w = Local.bm25(fake, {"a": 1.0, "b": 10.0}, 3)
    assert r_w == [2, 0, 1] and r_w != r_list  # b 가중치를 올리면 b만 있는 청크(2)가 1위로(가중이 실제로 반영됨)
    print("[selftest] BM25 가중 질의어(확장 없으면 동일 · 가중 반영) 통과")

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

    _selftest_id_doc_level()
    _selftest_hidden()
    _selftest_tie_break()


def _selftest_tie_break():
    """BR41 — tie_break()·entity_hints() 단위 점검(DB·Local 인스턴스 없이, 순수 함수).
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
    # id_patterns.csv(product_code 정규식)는 실제 사전 폴더에서(GLOSSARY_DIR 임시로 — load_id_patterns_typed가 읽음).
    _env = mc.senv(
        GLOSSARY_DIR=str(GLOSSARY_ROOT)
    )  # 인계 파일(load_id_patterns_typed)이 env로 읽음 — senv가 os.environ에도 쓰고 되돌림(S7d)
    try:
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
    finally:
        _env.close()

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


def _selftest_id_doc_level():
    """BR32 — id 우선 검색의 ID_MAX_DF 문턱이 문서 단위인지(청크 단위면 한 문서가 여러 청크로 쪼개질 때 억울하게
    걸림 — 실측 QA074: 메일 스크린샷 OCR이 4조각으로 쪼개져 메일 ID가 청크 6개에 나타나 청크 기준 문턱(5)을 넘음).
    문서 1개가 청크 6개로 쪼개져도(ID_MAX_DF=5보다 많은 청크) 문서 기준 df=1 ≤ 5면 id 방법이 그 청크를 찾아야 함."""
    import json
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    docs = [{"file_path": "mail-x-01.msg", "file_name": "mail-x-01.msg", "file_sha256": "3" * 64, "doc_format": ".msg"}]
    chunks = [
        {
            "doc": 0,
            "seq": i,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "mail-x-01 단가 협상",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(6)
    ]  # 한 문서, 청크 6개(> ID_MAX_DF)
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((6, 0), dtype="float32"))
    L = Local(d)
    assert L.df["mail-x-01"] == 6  # 청크 기준 df는 문턱(5)을 넘음
    assert L.doc_df["mail-x-01"] == 1  # 문서 기준 df는 1(문서 1개)
    order, via, _ = L.search(None, ["mail-x-01"], 5, methods=["id"])
    assert order and via[order[0]] == "i", (order, via)  # id 방법이 실제로 찾음(청크 기준이면 못 찾았을 것)
    print("[selftest] BR32 — ID_MAX_DF 문턱이 문서 단위(한 문서가 청크 여러 개로 쪼개져도 안 걸림) 통과")


def _selftest_hidden():
    """OP1 — hidden(doc_key 집합)이 그 문서의 청크를 전부 뺀다(client와 같은 restrict 방식) · None·빈 집합이면
    전과 바이트 동일(기존 client_hard 선례와 같은 확인)."""
    import json
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": "1" * 64, "doc_format": ".txt"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": "2" * 64, "doc_format": ".txt"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가는 100 USD",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((2, 0), dtype="float32"))
    L = Local(d)
    order, _, _ = L.search(None, ["단가"], 5, methods=["bm25"])
    assert order == [0, 1]  # hidden 없음 — 전과 동일
    hidden_order, _, _ = L.search(None, ["단가"], 5, methods=["bm25"], hidden={"1" * 64})
    assert hidden_order == [1], hidden_order  # a(숨김) 완전 제외 — b만 남음(소프트 아님)
    none_order, _, _ = L.search(None, ["단가"], 5, methods=["bm25"], hidden=set())
    assert none_order == order  # 빈 집합 — 바이트 동일
    print("[selftest] OP1 — hidden 집합이 그 문서의 청크를 저장소 질의 단계에서 완전 제외(소프트 아님) · 없으면 바이트 동일 통과")
    _selftest_index_mismatch()


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
