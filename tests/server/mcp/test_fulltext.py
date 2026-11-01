"""mc-17 — 원문 도구 list_doc_fulltext → get_doc_fulltext(운영 계약 05 §3). gold doc은 SQLite 대역, Object Storage는 가짜 클라이언트(외부 접속 없음)."""

import hashlib
import json
from unittest.mock import patch

from mcp_server import config as mc
from mcp_server.schemas import fulltext as FT
from mcp_server.services import fulltext as M
from mcp_server.services.search.server_state import _STATE
from tests.server.mcp import pgfix

B = "rag-publish"


class _NotFound(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    """list_objects_v2(페이지)·head_object·get_object만 — {키: 바이트}."""

    def __init__(self, objs):
        self.objs = objs

    def get_paginator(self, _name):
        objs = self.objs

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "Size": len(v), "ETag": f'"e{len(v)}"'} for k, v in objs.items() if k.startswith(Prefix)]}

        return P()

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise _NotFound()
        return {"ContentLength": len(self.objs[Key])}

    def get_object(self, Bucket, Key):
        if Key not in self.objs:
            raise _NotFound()
        return {"Body": _Body(self.objs[Key])}


class _Body:  # read(n) — boto3 StreamingBody처럼 최대 n바이트
    def __init__(self, b):
        self.b = b

    def read(self, n=None):
        return self.b if n is None else self.b[:n]


def _docs():
    return [
        {
            "file_path": "/app/output/prepared/A.pdf",
            "source_system": "SFDC",
            "doc_class": "RFP",
            "sf_op_id": "006A",
            "created_at": "2025-03-01T10:00:00+09:00",
            "parsed_at": "2025-04-01T09:00:00+09:00",
            "rep_bucket": B,
            "rep_key": "PR/SFDC/A/",
            "doc_key": "a" * 64,
        },
        {
            "file_path": "/app/output/prepared/B.docx",
            "source_system": "SFDC",
            "doc_class": "RFI",
            "created_at": "2025-03-05T10:00:00+09:00",
            "parsed_at": "2025-04-02T09:00:00+09:00",
            "rep_bucket": B,
            "rep_key": "PR/SFDC/B/",
            "doc_key": "b" * 64,
        },
        {"file_path": "/app/output/prepared/C.pdf", "source_system": "LAS", "rep_bucket": B, "rep_key": "PR/LAS/C/", "doc_key": "c" * 64},
        {"file_path": "/app/output/prepared/D.pdf", "source_system": "SFDC"},  # rep_key 없음 — 목록 대상 아님
        {
            "file_path": "/app/output/prepared/E.pdf",
            "source_system": "SFDC",
            "rep_bucket": B,
            "rep_key": "PR/SFDC/A",
        },  # 끝 '/' 없는 값 — 대상 아님
    ]


OBJS = {
    "PR/SFDC/A/A_2025-04-01_090000.md": b"# A old",
    "PR/SFDC/A/A_2025-04-02_090000.md": "# A 본문".encode(),
    "PR/SFDC/A/A_2025-04-02_090000.json": json.dumps({"text": "A", "tables": [1], "trace": "x"}).encode(),
    "PR/SFDC/A/source.json": b"{}",
    "PR/SFDC/A/engine/x_A.json": b"{}",
    "PR/SFDC/B/B_2025-04-02_090000.md": b"x" * (FT.FILE_MAX_BYTES + 1),
    # C: 폴더에 파일 없음 → no_files
}


def test_fulltext():
    chunk = {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1}
    d = pgfix.mk_bundle(_docs(), [chunk])
    _STATE.clear()
    s3 = FakeS3(dict(OBJS))
    with pgfix.use(d, MCP_BUNDLE=str(d)), patch.object(M, "_storage", return_value=s3):
        # 서명 키 없음 → not_configured
        with mc.senv(FULLTEXT_SIGN_SECRET=None):
            assert M.do_list(source_system="SFDC")["error"] == "not_configured"
        with mc.senv(FULLTEXT_SIGN_SECRET="k1"):
            _cases(s3)
            listed = M.do_list(docs=["A.pdf"])
        with mc.senv(FULLTEXT_SIGN_SECRET="k2"):  # 서명 키를 바꾸면 발급된 sfid는 무효
            sf = listed["documents"][0]["files"]["md"]["sfid"]
            assert M.do_get(files=[sf])["files"][0]["skip_reason"] == "bad_sfid"
    _STATE.clear()
    print("[시험] mc-17 원문 도구 — 목록 거르기·쪽 넘김·sfid·받기 한도·건너뜀 사유·등록 시각 가드 통과")


def _cases(s3):
    bad = [  # (인자, detail에 들어갈 말) — bad_request
        ({}, "조건"),
        ({"docs": ["x"] * (FT.DOCS_MAX + 1)}, "docs"),
        ({"since": "2025-04-01T00:00:00+09:00"}, "since"),  # 시간대 붙으면 거부
        ({"created_until": "2025/04/01"}, "created_until"),
        ({"source_system": "SFDC", "cursor": "abc"}, "cursor"),
        ({"source_system": "SFDC", "cursor": "²"}, "cursor"),
    ]
    for kw, word in bad:
        r = M.do_list(**kw)
        assert r["error"] == "bad_request" and word in r["detail"], (kw, r)
    cases = [  # (인자, 기대 file_name 목록, matched)
        ({"source_system": "SFDC"}, ["A.pdf", "B.docx"], 2),  # rep_key 없는 D는 빠짐
        ({"source_system": "SFDC-test"}, ["A.pdf", "B.docx"], 2),  # G4 별칭
        ({"docs": ["A.pdf", "c" * 64]}, ["A.pdf", "C.pdf"], 2),  # 이름·doc_key 섞어도 됨
        ({"docs": ["A"]}, [], 0),  # 확장자 없는 이름은 0건(오류 아님)
        ({"doc_class": "RFI"}, ["B.docx"], 1),
        ({"sf_op_id": "006A"}, ["A.pdf"], 1),
        ({"since": "2025-04-02"}, ["B.docx"], 1),  # 파싱 시각 축
        ({"until": "2025-04-01"}, ["A.pdf"], 1),  # 날짜만 until = 그날 전체
        ({"created_since": "2025-03-02 00:00:00"}, ["B.docx"], 1),  # 등록 시각 축 · created_at 없는 C는 빠짐
        ({"source_system": "FAQ"}, [], 0),
    ]
    for kw, want, n in cases:
        r = M.do_list(**kw)
        assert [x["file_name"] for x in r["documents"]] == want and r["batch"]["matched"] == n, (kw, r)
        assert tuple(r) == FT.LIST_TOP_KEYS and tuple(r["batch"]) == FT.LIST_BATCH_KEYS, r
        assert all(tuple(x) == FT.DOC_KEYS for x in r["documents"]), r
    # 쪽 넘김 — limit 1이면 next_cursor로 이어 받고 마지막 쪽은 null
    p1 = M.do_list(source_system="SFDC", limit=1)
    p2 = M.do_list(source_system="SFDC", limit=1, cursor=p1["batch"]["next_cursor"])
    assert [p1["documents"][0]["file_name"], p2["documents"][0]["file_name"]] == ["A.pdf", "B.docx"], (p1, p2)
    assert p1["batch"]["matched"] == p2["batch"]["matched"] == 2 and p2["batch"]["next_cursor"] is None, (p1, p2)
    # 문서 한 건의 모양 — 최신 parse_date의 md·json, engine/·source.json 제외
    a = M.do_list(docs=["a" * 64])["documents"][0]
    assert a["parse_date"] == "2025-04-02_090000" and a["status"] == "ok" and a["rep_uri"] == f"s3://{B}/PR/SFDC/A/", a
    assert a["files"]["md"]["name"] == "A_2025-04-02_090000.md" and tuple(a["files"]["md"]) == FT.FILE_KEYS, a
    assert a["created_at"] == "2025-03-01T10:00:00+09:00" and a["doc_class"] == "RFP", a
    c = M.do_list(docs=["C.pdf"])["documents"][0]
    assert c["status"] == "no_files" and c["files"] is None, c
    b = M.do_list(docs=["B.docx"])["documents"][0]
    assert b["files"]["json"] is None and b["files"]["md"]["size"] == FT.FILE_MAX_BYTES + 1, b
    # 받기
    md, js = a["files"]["md"]["sfid"], a["files"]["json"]["sfid"]
    assert M.do_get(files=[])["error"] == "bad_request" and M.do_get(files=[md] * (FT.GET_FILES_MAX + 1))["error"] == "bad_request"
    r = M.do_get(files=[md, js, "sf1.bad.sig", b["files"]["md"]["sfid"]], json_section="text,tables")
    assert tuple(r) == FT.GET_TOP_KEYS and tuple(r["batch"]) == FT.GET_BATCH_KEYS, r
    f_md, f_js, f_bad, f_big = r["files"]
    assert f_md["content"] == "# A 본문" and f_md["sha256"] == hashlib.sha256("# A 본문".encode()).hexdigest() and f_md["status"] == "ok", (
        f_md
    )
    assert f_js["kind"] == "json" and f_js["content"] == {"text": "A", "tables": [1]}, f_js  # json_section으로 줄임
    assert f_bad == {"sfid": "sf1.bad.sig", "skip_reason": "bad_sfid"}, f_bad
    assert M.do_get(files=["sf1.x.é"])["files"][0]["skip_reason"] == "bad_sfid"  # ASCII 아닌 서명 — 오류가 아니라 건너뜀
    assert f_big["skip_reason"] == "too_large" and f_big["name"].endswith(".md"), f_big
    assert r["batch"]["ok"] == 2 and r["batch"]["skipped"] == 2 and r["batch"]["truncated"] is False, r["batch"]
    # 깨진 JSON → 그 파일만 download_failed · head 뒤에 커진 파일 → too_large(상한까지만 읽음)
    s3.objs["PR/SFDC/A/A_2025-04-02_090000.json"] = b"{broken"
    assert M.do_get(files=[js, md])["files"][0]["skip_reason"] == "download_failed"
    with patch.object(FakeS3, "head_object", lambda self, Bucket, Key: {"ContentLength": 1}):
        s3.objs["PR/SFDC/A/A_2025-04-02_090000.md"] = b"y" * (FT.FILE_MAX_BYTES + 5)
        assert M.do_get(files=[md])["files"][0]["skip_reason"] == "too_large"
    s3.objs["PR/SFDC/A/A_2025-04-02_090000.md"] = "# A 본문".encode()
    # 사라진 파일 → missing · 등록 시각 가드 → created_out_of_range
    del s3.objs["PR/SFDC/A/A_2025-04-02_090000.json"]
    assert M.do_get(files=[js])["files"][0]["skip_reason"] == "missing"
    assert M.do_get(files=[md], created_since="2025-03-02")["files"][0]["skip_reason"] == "created_out_of_range"
    assert M.do_get(files=[md], created_until="2025-03-01")["files"][0]["status"] == "ok"
    assert M.do_get(files=[md], created_since="2025-03-02T00:00:00Z")["error"] == "bad_request"
    # 합계 24MB 상한 — 낮춰서 확인
    with patch.object(FT, "BATCH_MAX_BYTES", len("# A 본문".encode())):
        r = M.do_get(files=[md, md])
        assert [f.get("skip_reason") for f in r["files"]] == [None, "batch_full"] and r["batch"]["truncated"] is True, r
