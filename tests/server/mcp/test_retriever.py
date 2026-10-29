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
        """임베딩 없는 작은 가짜 묶음으로 BM25 확장 경로(X3)·개념 검색(X4 concept_hits)이 이어지는지."""
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
        (d / "concept_chunk.jsonl").write_text(
            json.dumps({"concept_id": "PROC.VI", "chunk_key": f"{sha}:0", "count": 3}) + "\n", encoding="utf-8"
        )
        R = Retriever(d)
        assert R.concept_hits("VI 공정 바이러스 불활화 질문") == []  # GLOSSARY_DIR 미설정 — 사전 없이 안전한 기본값(확장 없음)
        g = {
            "PROC.VI": {
                "concept_id": "PROC.VI",
                "canonical": "Viral Inactivation",
                "synonyms": "바이러스 불활화",
                "abbreviations": "VI",
                "weak_synonyms": "",
                "broader": "",
                "related": "",
                "context_required": "",
                "case_sensitive": "Y",
                "status": "approved",
            }
        }
        hits = R.concept_hits("바이러스 불활화 관련 문서", glossary=g)
        assert hits and hits[0]["chunk_key"] == f"{sha}:0" and hits[0]["score"] == 3
        hits2, _ = R.search("아무 질문", 5, methods=["bm25"])  # 임베딩 없는 묶음에서도 BM25 경로(확장 연결)가 그대로 동작
        assert isinstance(hits2, list)
        print("[selftest] concept_hits(X4)·BM25 확장 연결(임베딩 없는 묶음) 통과")

        _selftest_recency()
        _selftest_graph()
        _selftest_client_hard()
        _selftest_concept_hits_client()
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


def _selftest_graph():
    """AD28 — graph() 묶음 파일 경로(로컬) vs PG 경로가 같은 kg 데이터면 같은 결과(순서 포함)인지.
    실제 PG 없이: PG 행은 같은 nodes/edges/chunks/docs에서 직접 계산한 스텁(db.q, id는 로컬과 일부러 다르게 매김)으로 —
    가짜 연결 팩토리·SQLite 흉내 대신. PG 질의 1회(N+1 금지)·PG 실패 시 묶음 파일로 조용히 안 돌아가고 바로 올리는지도 확인."""
    import tempfile

    import numpy as np

    from mcp_server.services.search import pgsearch

    d = Path(tempfile.mkdtemp())
    sha0, sha1 = "e" * 64, "f" * 64
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": sha0, "doc_format": ".txt"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": sha1, "doc_format": ".txt"},
    ]
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "제품 BIS-402 설명",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "BIS-402 가격 안내",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        },
    ]
    nodes = [
        {"id": 0, "kind": "chunk", "node_key": f"{sha0}:0", "label": "a.txt #0", "doc": 0, "chunk": 0},
        {"id": 1, "kind": "chunk", "node_key": f"{sha1}:0", "label": "b.txt #0", "doc": 1, "chunk": 1},
        {"id": 2, "kind": "entity", "node_key": "bis-402", "label": "BIS-402"},
    ]
    edges = [{"src": 0, "dst": 2, "rel": "mentions", "chunk": 0}, {"src": 1, "dst": 2, "rel": "mentions", "chunk": 1}]
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    (d / "kg_nodes.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in nodes) + "\n", encoding="utf-8")
    (d / "kg_edges.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in edges) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((2, 0), dtype="float32"))

    R = Retriever(d)
    hits = [{"chunk_key": f"{sha0}:0"}]
    local_res = R.graph(hits)
    assert local_res == [{"via": "entity:BIS-402", "file_path": "b.txt", "page": 1, "line": 1, "text": "BIS-402 가격 안내"}], local_res

    chunk_pg_id = {0: 507, 1: 520}  # 로컬 ci → pg chunk_id(일부러 다른 수 — id 일치에 의존하지 않는지 확인)
    calls = []

    class FakeDB:  # 같은 kg 데이터를 PG 행 형태로 — 가짜 연결·SQLite 아니라 db.q() 결과만 흉내
        schema = "ai"

        def q(self, sql, params=None):
            calls.append(sql)
            seed_ids = set(params[0])
            rows = []
            for e1 in edges:
                cn = nodes[e1["src"]]
                if cn["kind"] != "chunk" or chunk_pg_id.get(cn["chunk"]) not in seed_ids:
                    continue
                mid = nodes[e1["dst"]]
                if mid["kind"] not in ("entity", "label", "value"):
                    continue
                for e2 in edges:
                    if e2["dst"] != e1["dst"] or e2["chunk"] is None or nodes[e2["src"]]["kind"] != "chunk":
                        continue
                    c, dc = chunks[e2["chunk"]], docs[chunks[e2["chunk"]]["doc"]]
                    rows.append(
                        {
                            "seed_chunk_id": chunk_pg_id[cn["chunk"]],
                            "mid_kind": mid["kind"],
                            "mid_label": mid["label"],
                            "mid_key": mid["node_key"],
                            "file_path": dc["file_path"],
                            "page": c["page"],
                            "line_start": c["line_start"],
                            "chunk_text": c["chunk_text"],
                            "file_sha256": dc["file_sha256"],
                            "seq": c["seq"],
                        }
                    )
            rows.sort(key=lambda r: (r["seed_chunk_id"], r["mid_key"], r["mid_kind"], r["file_sha256"], r["seq"]))
            return rows

    R.pg, R.pgmod, R.key_pg = FakeDB(), pgsearch, {f"{sha0}:0": chunk_pg_id[0], f"{sha1}:0": chunk_pg_id[1]}
    pg_res = R.graph(hits)
    assert pg_res == local_res, (pg_res, local_res)
    assert len(calls) == 1, f"PG 질의 {len(calls)}회 — 1회(N+1 금지) 기대"

    class FailDB:
        schema = "ai"

        def q(self, sql, params=None):
            raise RuntimeError("PG 연결 끊김")

    R.pg = FailDB()
    try:
        R.graph(hits)
    except RuntimeError:
        pass
    else:
        raise AssertionError("PG 실패를 삼키고 조용히 묶음 파일로 대체되면 안 됨 — 바로 올려야(RUN_MODE=prod와 같은 규칙)")
    print("[selftest] AD28 그래프 확장 — 묶음 파일·PG(스텁) 같은 결과(순서 포함) · PG 질의 1회 · PG 실패는 바로 올림 통과")

    _selftest_graph_biz_concept()


def _selftest_graph_biz_concept():
    """AD28②③ — 로컬 경로: ② 업무 개체(kind=client 등)도 MID_KINDS에 들어 1홉 확장에 그대로 쓰임 ·
    ③ 개념(concept) 1홉 + broader 2홉(개념→개념→청크, 기존 결과 뒤에 낮은 가중치로 붙음) ·
    SEARCH_GRAPH_CONCEPT_EXPAND=0이면 2홉 생략(1홉까지만, 기존 동작과 바이트 동일)."""
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    sha0, sha1, sha2 = "1" * 64, "2" * 64, "3" * 64
    docs = [
        {"file_path": "0.txt", "file_name": "0.txt", "file_sha256": sha0, "doc_format": ".txt"},
        {"file_path": "1.txt", "file_name": "1.txt", "file_sha256": sha1, "doc_format": ".txt"},
        {"file_path": "2.txt", "file_name": "2.txt", "file_sha256": sha2, "doc_format": ".txt"},
    ]
    chunks = [
        {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "씨앗", "n_terms": 1, "bbox": None, "section": None},
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "A 개념 직접 멘션",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 2,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "B 개념만 멘션(A와 직접 연결 없음)",
            "n_terms": 4,
            "bbox": None,
            "section": None,
        },
    ]
    nodes = [
        {"id": 0, "kind": "chunk", "node_key": f"{sha0}:0", "label": "0.txt #0", "doc": 0, "chunk": 0},
        {"id": 1, "kind": "chunk", "node_key": f"{sha1}:0", "label": "1.txt #0", "doc": 1, "chunk": 1},
        {"id": 2, "kind": "chunk", "node_key": f"{sha2}:0", "label": "2.txt #0", "doc": 2, "chunk": 2},
        {"id": 3, "kind": "concept", "node_key": "CON.A", "label": "Concept A"},
        {"id": 4, "kind": "concept", "node_key": "CON.B", "label": "Concept B"},
    ]
    edges = [
        {"src": 0, "dst": 3, "rel": "concept_chunk", "chunk": 0},  # 씨앗 청크 → A(1홉 중간 노드)
        {"src": 1, "dst": 3, "rel": "concept_chunk", "chunk": 1},  # doc1 → A(1홉으로 바로 찾는 이웃)
        {"src": 3, "dst": 4, "rel": "broader", "chunk": None},  # A의 상위 개념 B(chunk=None, 개념 간 구조 엣지)
        {"src": 2, "dst": 4, "rel": "concept_chunk", "chunk": 2},
    ]  # doc2 → B(2홉으로만 닿음, A와 직접 연결 없음)
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    (d / "kg_nodes.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in nodes) + "\n", encoding="utf-8")
    (d / "kg_edges.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in edges) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((3, 0), dtype="float32"))

    R = Retriever(d)
    hits = [{"chunk_key": f"{sha0}:0"}]
    res = R.graph(hits)
    assert res[0] == {"via": "concept:Concept A", "file_path": "1.txt", "page": 1, "line": 1, "text": "A 개념 직접 멘션"}  # 1홉
    assert res[1] == {
        "via": "concept-broader:CON.A",
        "file_path": "2.txt",
        "page": 1,
        "line": 1,  # 2홉(낮은 가중치, 뒤에 붙음)
        "text": "B 개념만 멘션(A와 직접 연결 없음)",
    }, res
    assert len(res) == 2

    with mc.senv(SEARCH_GRAPH_CONCEPT_EXPAND="0"):  # S7d — 설정 객체 덮기
        res_off = R.graph(hits)
    assert res_off == [res[0]]  # 2홉 생략 — 1홉까지만(기존 동작과 바이트 동일)
    print(
        "[selftest] AD28②③ 로컬 경로 — 업무 개체 1홉(MID_KINDS)·개념 broader 2홉(낮은 가중치, 뒤에 붙음)·"
        "SEARCH_GRAPH_CONCEPT_EXPAND=0 생략 통과"
    )

    # engine-qa MINOR(10-08) — 2홉 씨앗 개념 수 상한(SEARCH_GRAPH_CONCEPT_SEEDS, 기본 per): 씨앗 청크가 개념을 여럿
    # 걸면(C·D) 기본은 둘 다 2홉(E·F 둘 다) 찾지만, 상한을 1로 주면 정렬상 먼저인 개념(C)만 2홉을 탐
    d2 = Path(tempfile.mkdtemp())
    sha_s, sha_e, sha_f = "4" * 64, "5" * 64, "6" * 64
    docs2 = [
        {"file_path": "s.txt", "file_name": "s.txt", "file_sha256": sha_s, "doc_format": ".txt"},
        {"file_path": "e.txt", "file_name": "e.txt", "file_sha256": sha_e, "doc_format": ".txt"},
        {"file_path": "f.txt", "file_name": "f.txt", "file_sha256": sha_f, "doc_format": ".txt"},
    ]
    chunks2 = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "C·D 둘 다 멘션",
            "n_terms": 1,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "E 전용",
            "n_terms": 1,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 2,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "F 전용",
            "n_terms": 1,
            "bbox": None,
            "section": None,
        },
    ]
    nodes2 = [
        {"id": 0, "kind": "chunk", "node_key": f"{sha_s}:0", "label": "s.txt #0", "doc": 0, "chunk": 0},
        {"id": 1, "kind": "chunk", "node_key": f"{sha_e}:0", "label": "e.txt #0", "doc": 1, "chunk": 1},
        {"id": 2, "kind": "chunk", "node_key": f"{sha_f}:0", "label": "f.txt #0", "doc": 2, "chunk": 2},
        {"id": 3, "kind": "concept", "node_key": "CON.C", "label": "Concept C"},
        {"id": 4, "kind": "concept", "node_key": "CON.D", "label": "Concept D"},
        {"id": 5, "kind": "concept", "node_key": "CON.E", "label": "Concept E"},
        {"id": 6, "kind": "concept", "node_key": "CON.F", "label": "Concept F"},
    ]
    edges2 = [
        {"src": 0, "dst": 3, "rel": "concept_chunk", "chunk": 0},
        {"src": 0, "dst": 4, "rel": "concept_chunk", "chunk": 0},
        {"src": 3, "dst": 5, "rel": "broader", "chunk": None},
        {"src": 4, "dst": 6, "rel": "broader", "chunk": None},
        {"src": 1, "dst": 5, "rel": "concept_chunk", "chunk": 1},
        {"src": 2, "dst": 6, "rel": "concept_chunk", "chunk": 2},
    ]
    (d2 / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d2 / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs2) + "\n", encoding="utf-8")
    (d2 / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks2) + "\n", encoding="utf-8")
    (d2 / "kg_nodes.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in nodes2) + "\n", encoding="utf-8")
    (d2 / "kg_edges.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in edges2) + "\n", encoding="utf-8")
    np.save(d2 / "vectors.npy", np.zeros((3, 0), dtype="float32"))
    R2 = Retriever(d2)
    hits2 = [{"chunk_key": f"{sha_s}:0"}]
    res2_default = R2.graph(hits2)
    assert {r["via"] for r in res2_default} == {"concept-broader:CON.C", "concept-broader:CON.D"}, (
        res2_default
    )  # 상한 없음(기본 per=3) — 둘 다
    with mc.senv(SEARCH_GRAPH_CONCEPT_SEEDS="1"):
        res2_capped = R2.graph(hits2)
    assert [r["via"] for r in res2_capped] == ["concept-broader:CON.C"], res2_capped  # 상한 1 — 정렬상 먼저인 C만
    print("[selftest] engine-qa MINOR — SEARCH_GRAPH_CONCEPT_SEEDS로 2홉 씨앗 개념 수 상한 통과")


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


def _selftest_concept_hits_client():
    """BR50(F) — concept_hits(client=...) + SEARCH_CLIENT_HARD=1이면 다른 고객 문서의 개념 근거는 빠짐(clientscope 공용
    규칙) · client 인자 없거나 꺼짐이면 바이트 동일(둘 다 나옴)."""
    import tempfile

    import numpy as np

    d = Path(tempfile.mkdtemp())
    sha_a, sha_b = "7" * 64, "8" * 64
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": sha_a, "doc_format": ".txt", "client": "Acme Co"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": sha_b, "doc_format": ".txt", "client": "Other Co"},
    ]
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정(Acme)",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정(Other)",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        },
    ]
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in docs) + "\n", encoding="utf-8")
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in chunks) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((2, 0), dtype="float32"))
    (d / "concept_chunk.jsonl").write_text(
        "\n".join(
            json.dumps(x)
            for x in [
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_a}:0", "count": 3},
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_b}:0", "count": 2},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    g = {
        "PROC.VI": {
            "concept_id": "PROC.VI",
            "canonical": "Viral Inactivation",
            "synonyms": "바이러스 불활화",
            "abbreviations": "VI",
            "weak_synonyms": "",
            "broader": "",
            "related": "",
            "context_required": "",
            "case_sensitive": "Y",
            "status": "approved",
        }
    }
    R = Retriever(d)
    _env = mc.senv(SEARCH_CLIENT_HARD=None)  # S7d — 설정 객체 덮기
    try:
        off = R.concept_hits("바이러스 불활화 관련 문서", glossary=g, client="Acme Co")  # 꺼짐 — client 줘도 영향 없음(바이트 동일)
        assert {h["file_name"] for h in off} == {"a.txt", "b.txt"}, off

        _env.enter_context(mc.senv(SEARCH_CLIENT_HARD="1"))
        on = R.concept_hits("바이러스 불활화 관련 문서", glossary=g, client="Acme Co")
        assert {h["file_name"] for h in on} == {"a.txt"}, on  # 켬 — Other Co 개념 근거는 빠짐
    finally:
        _env.close()
    print("[selftest] BR50(F) concept_hits(client=) — 꺼짐 바이트 동일 · SEARCH_CLIENT_HARD=1이면 다른 고객 개념 근거 제외 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
