"""mc-10 — 축소 스키마 묶음(docs.jsonl에 doc_key만, file_sha256 없음)으로 Retriever를 만들고 검색한다.
전에는 서버(LOCAL_RUN 아님)에서 d["file_sha256"]로 읽어 KeyError — 검색 MCP의 search가 매번 실패했다.
mc-01(11-01) — 검색은 PG 하나라 SQLite 대역(pgfix)으로 돈다. PG 검색 결과의 doc_key는 늘 file_path다."""

from tests.server.mcp import pgfix


def _bundle(doc):
    c = {
        "doc": 0,
        "seq": 0,
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "chunk_text": "바이러스 불활화 공정",
        "n_terms": 3,
        "bbox": None,
        "section": None,
    }
    return pgfix.mk_bundle([doc], [c])


def test_doc_key_bundle():
    path = "/data/docs/a.txt"
    cases = [  # (묶음 docs.jsonl 행, 묶음 doc_meta 키)
        ({"file_path": path, "doc_key": path}, path),  # 새 묶음 — doc_key만(file_name·file_sha256 없음, build_bundle 그대로)
        ({"file_path": path, "file_name": "a.txt", "file_sha256": "a" * 64}, "a" * 64),  # 옛 묶음 — file_sha256만
    ]
    for doc, want in cases:
        with pgfix.retriever(_bundle(doc)) as R:
            assert list(R.doc_meta) == [want] and list(R.key_local) == [f"{want}:0"]
            hits, _ = R.search("바이러스", 5, methods=["bm25"])
            assert hits and hits[0]["doc_key"] == path and hits[0]["chunk_key"] == f"{hits[0]['doc_id']}:0", (
                hits
            )  # 문서 키 = file_path · 청크 키 <doc_id>:<seq>(11-02)
            assert hits[0]["file_name"] == "a.txt", hits


def test_local_doc_fill():
    """BundleDocs가 묶음 문서에 doc_key·file_name을 채움 — Windows 경로(역슬래시)는 doc_name을 파일 이름으로, 서버 경로는 마지막 '/' 뒤.
    (이 dict를 읽던 internal_docs 목록·조회는 10-30 지움 — e2-18.)"""
    win = r"C:\docs\b.txt"  # PC(Windows) — build_bundle이 str(orig.resolve())를 file_path로 씀
    srv = "/data/docs/c.txt"
    with pgfix.retriever(_bundle({"file_path": win, "doc_key": win, "doc_name": "b.txt"})) as R:
        a = R.local.docs[0]
    with pgfix.retriever(_bundle({"file_path": srv, "doc_key": srv})) as R:
        b = R.local.docs[0]
    assert (a["doc_key"], a["file_name"]) == (win, "b.txt"), a
    assert (b["doc_key"], b["file_name"]) == (srv, "c.txt"), b
