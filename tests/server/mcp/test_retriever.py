"""mcp_server.services.search.retriever 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.retriever`."""

import json
from pathlib import Path

from mcp_server import config as mc
from mcp_server.services.search.retriever import Retriever


def selftest():
    _env = mc.senv(
        GLOSSARY_DIR=None
    )  # 사전 없는 기본값을 먼저 확인(실행 환경 변수와 무관하게) — 인계 키라 senv가 os.environ에서도 지움(S7d), 끝나면 되돌림
    try:
        """임베딩 없는 작은 가짜 묶음으로 BM25 확장 경로(X3)가 이어지는지."""
        import tempfile

        import numpy as np

        d = Path(tempfile.mkdtemp())
        sha = "a" * 64
        (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
        (d / "docs.jsonl").write_text(
            json.dumps({"file_path": "a.txt", "file_name": "a.txt", "file_sha256": sha, "doc_format": ".txt"}) + "\n", encoding="utf-8"
        )
        chunks = [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "바이러스 불활화 공정 설명",
                "n_terms": 4,
                "bbox": None,
                "section": None,
            },
            {
                "doc": 0,
                "seq": 1,
                "page": 1,
                "line_start": 2,
                "line_end": 2,
                "chunk_text": "다른 내용 문서",
                "n_terms": 3,
                "bbox": None,
                "section": None,
            },
        ]
        (d / "chunks.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
        np.save(d / "vectors.npy", np.zeros((2, 0), dtype="float32"))
        R = Retriever(d)
        hits2, _ = R.search("아무 질문", 5, methods=["bm25"])  # 임베딩 없는 묶음에서도 BM25 경로(확장 연결)가 그대로 동작
        assert isinstance(hits2, list)
        print("[selftest] BM25 확장 연결(임베딩 없는 묶음) 통과")

        _selftest_recency()
        _selftest_client_hard()
    finally:
        _env.close()


def _selftest_recency():
    """L3-1 — 작은 묶음(embed none·BM25): 같은 family 2건(구판·최신본) + 무관 문서 1건 → 최신본이 먼저, 구판은 뒤로(안 지움).
    SEARCH_RECENCY=0이면 오늘 동작(순서 그대로) 그대로 재현. 메커니즘 점검이라 '늘' 모드(2)로(기본 1은 최신 질문만 — docmeta selftest)."""
    _env = mc.senv(SEARCH_RECENCY="2")  # S7d — 설정 객체 덮기(common 칸 — docmeta가 읽음)
    try:
        import tempfile

        import numpy as np

        d = Path(tempfile.mkdtemp())
        sha_old, sha_new, sha_other = "b" * 64, "c" * 64, "d" * 64
        docs = [
            {
                "file_path": "msa_old.docx",
                "file_name": "msa_old.docx",
                "file_sha256": sha_old,
                "doc_format": ".docx",
                "doc_date": "2024-01",
                "version": None,
                "superseded": True,
                "family": "msa",
            },
            {
                "file_path": "msa.docx",
                "file_name": "msa.docx",
                "file_sha256": sha_new,
                "doc_format": ".docx",
                "doc_date": "2026-05",
                "version": "2",
                "superseded": False,
                "family": "msa",
            },
            {
                "file_path": "nda.docx",
                "file_name": "nda.docx",
                "file_sha256": sha_other,
                "doc_format": ".docx",
                "doc_date": None,
                "version": None,
                "superseded": False,
                "family": "nda",
            },
        ]
        (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
        (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
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
            for i in range(3)
        ]
        (d / "chunks.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
        np.save(d / "vectors.npy", np.zeros((3, 0), dtype="float32"))
        R = Retriever(d)
        hits, _ = R.search("단가는?", 3, methods=["bm25"])
        assert [h["doc_key"] for h in hits] == [sha_new, sha_old, sha_other]  # 최신본 먼저, 구판은 최신본 바로 뒤(L4-8, 제외 아님)
        assert R.recency_note == "구판 1건 뒤로"
        assert hits[1]["superseded"] is True and hits[0]["doc_date"] == "2026-05"  # 근거 머리글용 날짜·구판 표시가 hit에 실림
        with mc.senv(SEARCH_RECENCY="0"):
            hits0, _ = R.search("단가는?", 3, methods=["bm25"])
            assert [h["doc_key"] for h in hits0] == [sha_old, sha_new, sha_other]  # 꺼짐 — 오늘 동작(순서 그대로) 재현
            assert R.recency_note is None
    finally:
        _env.close()
    print("[selftest] L3-1 최신성 순위(최신본 먼저·구판 뒤로, 안 지움) · SEARCH_RECENCY=0 오늘 동작 재현 통과")


def _selftest_client_hard():
    """AD38 — SEARCH_CLIENT_HARD=1 + client 인자(또는 질문에서 잡힌 고객): 저장소 질의 단계에서 진짜 제외(재순위 아님).
    문서 3건(Acme Co · Other Co · 고객 미상) 중 '단가는?'은 셋 다 똑같이 맞아 bm25 동점(인덱스 오름차순) — 섞이면 바로 드러남."""
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": "1" * 64, "doc_format": ".txt", "client": "Acme Co"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": "2" * 64, "doc_format": ".txt", "client": "Other Co"},
        {"file_path": "c.txt", "file_name": "c.txt", "file_sha256": "3" * 64, "doc_format": ".txt"},
    ]  # 고객 미상
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
        for i in range(3)
    ]
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((3, 0), dtype="float32"))
    R = Retriever(d)
    _env = mc.senv(SEARCH_CLIENT_HARD=None, SEARCH_CLIENT_STRICT=None)  # S7d — 설정 객체 덮기
    try:
        base, _, _ = R.search_ex("단가는?", 5, methods=["bm25"])  # client 인자 없음 — 끔 상태와 똑같이(바이트 동일 확인용 기준)
        assert [h["file_name"] for h in base] == ["a.txt", "b.txt", "c.txt"], base

        off, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # 끔(기본) — 예전처럼 앞으로만(그대로 다 있음)
        assert [h["file_name"] for h in off] == ["a.txt", "c.txt", "b.txt"], off  # Acme·미상 앞 · Other Co는 안 빠짐(소프트)

        _env.enter_context(mc.senv(SEARCH_CLIENT_HARD="1"))
        same, _, _ = R.search_ex("단가는?", 5, methods=["bm25"])  # client 인자 없음(질문에도 고객 없음) — 켜져도 영향 없음
        assert [h["file_name"] for h in same] == ["a.txt", "b.txt", "c.txt"], same

        hard, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # 켬 — Other Co는 후보에서 완전히 빠짐(미상은 포함)
        assert [h["file_name"] for h in hard] == ["a.txt", "c.txt"], hard

        _env.enter_context(mc.senv(SEARCH_CLIENT_STRICT="1"))
        strict, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co")  # 미상도 뺌
        assert [h["file_name"] for h in strict] == ["a.txt"], strict

        # BR50 E — client_strict=False 오버라이드: 전역 SEARCH_CLIENT_STRICT=1이어도 이 호출만 미상 문서를 포함
        # (BR43 FX 근거처럼 "범위는 같게, 미상은 항상 포함"이 필요할 때 — Other Co는 여전히 빠짐, 미상(c.txt)만 override로 살아남음)
        override, _, _ = R.search_ex("단가는?", 5, methods=["bm25"], client="Acme Co", client_strict=False)
        assert [h["file_name"] for h in override] == ["a.txt", "c.txt"], override
    finally:
        _env.close()
    print(
        "[selftest] AD38 SEARCH_CLIENT_HARD — 꺼짐(client 인자 없음) 바이트 동일 · 켜짐은 다른 고객 완전 제외(미상은 기본 포함, STRICT면 미상도 제외) ·"
        " BR50 client_strict=False 오버라이드로 전역 STRICT 무시하고 미상 포함 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
