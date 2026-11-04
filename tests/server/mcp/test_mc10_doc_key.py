"""mc-10 — 축소 스키마 묶음(docs.jsonl에 doc_key만, file_sha256 없음)으로 Retriever를 만들고 검색한다.
전에는 서버(LOCAL_RUN 아님)에서 d["file_sha256"]로 읽어 KeyError — 검색 MCP의 search가 매번 실패했다.
mc-01(11-01) — 검색은 PG 하나라 SQLite 대역(pgfix)으로 돈다. PG 검색 결과의 doc_key는 늘 file_path다.
mc-19(11-03) — Retriever가 묶음 파일을 읽지 않아(BundleDocs·doc_meta·key_local 지움) 묶음 모양과 무관하게 같은 결과."""

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
    cases = [
        {"file_path": path, "doc_key": path},  # 새 묶음 — doc_key만(file_name·file_sha256 없음, build_bundle 그대로)
        {"file_path": path, "file_name": "a.txt", "file_sha256": "a" * 64},  # 옛 묶음 — file_sha256만
    ]
    for doc in cases:
        with pgfix.retriever(_bundle(doc)) as R:
            hits, _ = R.search("바이러스", 5, methods=["bm25"])
            assert hits and hits[0]["doc_key"] == path and hits[0]["chunk_key"] == f"{hits[0]['doc_id']}:0", (
                hits
            )  # 문서 키 = file_path · 청크 키 <doc_id>:<seq>(11-02)
            assert hits[0]["file_name"] == "a.txt", hits
