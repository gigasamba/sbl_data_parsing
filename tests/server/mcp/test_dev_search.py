"""op-17 — 검색 MCP의 DEV 원천(`DEV-<n>` — 개발 서버·PC만): 원천 목록 = 5벌 + 있는 `<기준>_dev_<n>`, search·list_doc_fulltext가
`DEV-<n>`을 받고(그 스키마가 있을 때) prd는 모르는 값처럼 거부. 뒤에 생긴 DEV 스키마는 그 값을 처음 부를 때 다시 찾아 잡는다.
실 pgvector의 임시 스키마(pgfix — test_*, 시험 뒤 지움) · 외부 모델 없음(묶음 차원 0 — bm25만)."""

import contextlib
import io
import shutil
from unittest.mock import patch

from common.store.db.models import search_tables as ST
from mcp_server import config as mc
from mcp_server.services import edw_calls
from mcp_server.services import fulltext_svc as FS
from mcp_server.services.search import search_svc as M
from mcp_server.services.search import server_state as SS
from tests.server.common import pgcase
from tests.server.mcp import pgfix
from tests.server.mcp.test_fulltext import FakeS3


def _chunk(doc, text):
    return {
        "doc": doc,
        "seq": 0,
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "chunk_text": text,
        "n_terms": 3,
        "bbox": None,
        "section": None,
    }


DOCS = [{"file_path": "SFDC/a.pdf", "source_system": "SFDC"}, {"file_path": "DEV-1/d.pdf", "source_system": "dev-1"}]
CHUNKS = [_chunk(0, "운영 문서 단가 안내"), _chunk(1, "개발 시험 문서 단가 안내")]


@contextlib.contextmanager
def _prd():
    """RUN_ENV=prd 흉내 — DEV 찾기(ST.dev_sources — prd 규칙은 거기 하나)만. 대역 연결은 local 그대로(서버는 대역을 거부하므로)."""
    with patch("common.config.settings.guard_run_env", return_value="prd"):
        yield


def _files(r):
    return [d["file_name"] for d in r.get("documents", [])]


def _ev(out):
    return [e["file_name"] for e in out["evidence"]] if "evidence" in out else None


# (이름, prd인가, search source_system, 기대 근거 파일 — None이면 오류, 오류 글에 들어갈 말)
SEARCH = [
    ("DEV-1 찾음", False, "DEV-1", ["d.pdf"], None),
    ("대소문자 무관", False, "dev-1", ["d.pdf"], None),
    ("-test 별칭", False, "DEV-1-test", ["d.pdf"], None),
    ("목록 값 하나", False, ["DEV-1"], ["d.pdf"], None),
    ("없는 DEV-7 — 분명한 거부", False, "DEV-7", None, "DEV-1"),  # 있는 DEV 원천을 알림
    ("빈 DEV-3 스키마 — 싣지 않고 거부", False, "DEV-3", None, "DEV-1"),
    ("빈 DEV 스키마가 있어도 5벌 그대로", False, "SFDC", ["a.pdf"], None),
    ("원천 없음 — 지금처럼 거부", False, None, None, "source_system is required"),
    ("prd DEV-1 — 모르는 값과 같은 거부", True, "DEV-1", None, None),
    ("prd SFDC 그대로", True, "SFDC", ["a.pdf"], None),
]
# (이름, prd인가, list_doc_fulltext source_system, 기대 파일 — None이면 bad_request)
FULLTEXT = [
    ("DEV-1 받음", False, "DEV-1", ["d.pdf"]),
    ("-test 별칭", False, "dev-1-test", ["d.pdf"]),
    ("없는 DEV-7 거부", False, "DEV-7", None),
    ("prd DEV-1 거부", True, "DEV-1", None),
    ("원천 없이(docs) — DEV도 봄", False, None, ["d.pdf"]),
]


def test_dev_search():
    d = pgfix.mk_bundle(DOCS, CHUNKS)
    db = pgcase.connect()
    db.q(f"CREATE SCHEMA {pgfix.schema_of(d)}_dev_3")  # 표 없는 DEV 스키마(깨진 스키마)
    db.cn.close()
    SS._STATE.clear()
    try:
        with pgfix.use(d), mc.senv(FULLTEXT_SIGN_SECRET="k1"), patch.object(FS, "_storage", return_value=FakeS3({})):
            for name, prd, sysv, want, word in SEARCH:
                SS._STATE.clear()
                with _prd() if prd else contextlib.nullcontext():
                    out = M.do_search("단가", k=5, **({"source_system": sysv} if sysv else {}))
                    if prd:
                        assert SS.dev_served() == [] and "dev_1" not in SS._STATE["Rs"], name  # prd는 DEV 스키마를 싣지 않음
                        if want is None:  # prd — 모르는 값과 같은 오류
                            assert out == M.do_search("단가", k=5, source_system="XYZ"), (name, out)
                if want is None:
                    assert "error" in out and (word or "") in out["error"], (name, out)
                else:
                    assert _ev(out) == want, (name, out)
            assert M.do_search("단가", source_system="dev-1")["filter"]["source_system"] == "DEV-1"  # 메아리는 DEV-<n> 꼴
            for name, prd, sysv, want in FULLTEXT:
                SS._STATE.clear()
                with _prd() if prd else contextlib.nullcontext():
                    r = FS.do_list(source_system=sysv) if sysv else FS.do_list(docs=["d.pdf"])
                    if want is None:
                        assert r.get("error") == "bad_request", (name, r)
                        if prd:
                            assert r == FS.do_list(source_system="XYZ"), name  # prd — 모르는 값과 같은 오류
                    else:
                        assert _files(r) == want and r["documents"][0]["source_system"] == "DEV-1", (name, r)
            SS._STATE.clear()
            with patch.object(FS, "dev_served", side_effect=AssertionError("DB를 봄")):  # DEV 꼴이 아니면 DB를 보지 않음
                assert FS.do_list(source_system="XYZ")["error"] == "bad_request"
            _broken()
            _dropped()
            SS._STATE.clear()
            assert "DEV-1" in edw_calls.search_attrs()  # edw_meta — 예열 없이도
            _later(d)
    finally:
        SS._STATE.clear()
    print("[시험] op-17 검색 MCP DEV 원천 — search·원문 도구 DEV-<n>, prd 거부, 깨진·사라진·뒤에 생긴 스키마 통과")


def _broken():
    """표 없는 DEV-3 — 경고 한 줄(한 번만), 그 원천만 빠지고 나머지는 그대로."""
    SS._STATE.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert SS.dev_served() == ["dev_1"] and SS.dev_served() == ["dev_1"]
    assert err.getvalue().count("[mcp] DEV 원천 스키마") == 1, err.getvalue()


def _dropped():
    """달리는 중 사라진 DEV-1 스키마 — 예외 없이 보통 거부, 검색기에서도 빠짐."""
    assert "dev_1" in SS._STATE["Rs"]
    with patch.object(ST, "dev_sources", return_value=[]):
        out = M.do_search("단가", k=5, source_system="DEV-1")
        assert out == {"error": M.NO_SOURCE}, out
        assert FS.do_list(source_system="DEV-1")["error"] == "bad_request"
        assert "dev_1" not in SS._STATE["Rs"] and _ev(M.do_search("단가", k=5, source_system="SFDC")) == ["a.pdf"]


# (도구, DEV 번호) — 시작 뒤 생긴 스키마(dbtool up)를 그 도구가 처음 부를 때 재시작 없이 잡는다(그 원천만 더함)
LATER = [("search", 2), ("list_doc_fulltext", 4), ("edw_meta", 5)]


def _later(d):
    base = pgfix.schema_of(d)
    for tool, n in LATER:
        before = SS._STATE["Rs"]
        assert f"dev_{n}" not in before, tool
        b = pgfix.mk_bundle(
            [{"file_path": f"DEV-{n}/n{n}.pdf", "source_system": f"DEV-{n}"}], [_chunk(0, "새 개발 문서 단가")], load_pg=False
        )
        try:
            pgfix.load(b, base, fixed=False)  # 이 DEV 원천 스키마만 지금 생김(dbtool up)
        finally:
            shutil.rmtree(b, ignore_errors=True)
        if tool == "search":
            assert _ev(M.do_search("단가", k=5, source_system=f"DEV-{n}")) == [f"n{n}.pdf"], tool
        elif tool == "list_doc_fulltext":
            assert _files(FS.do_list(source_system=f"DEV-{n}")) == [f"n{n}.pdf"], tool
        else:
            assert f"DEV-{n}" in edw_calls.search_attrs(), tool
        assert SS._STATE["Rs"]["sfdc"] is before["sfdc"], tool  # 전체를 다시 만들지 않음
