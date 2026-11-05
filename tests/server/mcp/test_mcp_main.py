"""mcp_server.main 시험.
10-29 정리 — 다른 시험 파일의 _selftest_* 28개를 다시 부르던 줄을 뺐다(각 파일 test_main이 이미 돎 — 중복). 여기는 main 자신의 점검만."""

import json

from mcp_server import config as mc
from mcp_server.main import _DEFAULT_MCP_INSTRUCTIONS, _mcp_instructions, build, check_bind
from mcp_server.services.search.evidence_shape import cap


def _selftest_transport_security():
    """L8 — 루프백은 FastMCP 자체 기본값(바이트 동일, 안 건드림) · 비루프백은 기본 ON(전엔 명시적으로 꺼둠) ·
    MCP_ALLOWED_HOSTS로 추가 호스트(리버스 프록시 등)를 더할 수 있음. 실제 421/403 거부는 dev_tools/unit_test/pipeline/
    test_mcp_server_transport_security.py(ASGI in-process 호출)가 확인."""
    ts_loop = build(host="127.0.0.1", port=8765).settings.transport_security
    assert ts_loop.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"], ts_loop.allowed_hosts
    ts_non = build(host="10.0.0.5", port=8765).settings.transport_security
    assert ts_non.enable_dns_rebinding_protection is True
    assert ts_non.allowed_hosts == ["10.0.0.5:*"] and "http://10.0.0.5:*" in ts_non.allowed_origins, ts_non
    with mc.senv(MCP_ALLOWED_HOSTS="proxy.local:9999, gw.local:*"):
        ts2 = build(host="10.0.0.5", port=8765).settings.transport_security
        assert "proxy.local:9999" in ts2.allowed_hosts and "gw.local:*" in ts2.allowed_hosts, ts2.allowed_hosts
        assert "http://proxy.local:9999" in ts2.allowed_origins and "https://gw.local:*" in ts2.allowed_origins, ts2.allowed_origins
    print("[selftest] L8 — 루프백 바이트 동일·비루프백 DNS 리바인딩 보호 기본 ON·MCP_ALLOWED_HOSTS 추가 반영 통과")


def selftest():
    o = {"evidence": [{"text": "가" * 5000}, {"text": "나" * 5000}]}
    assert len(json.dumps(cap(o, 3000), ensure_ascii=False)) <= 3000 and o["truncated"]
    for bad in ("0.0.0.0", "8.8.8.8"):
        try:
            check_bind(bad, "t")
            raise AssertionError(bad)
        except SystemExit:
            pass
    check_bind("127.0.0.1", "")
    check_bind("10.0.0.5", "tok")
    try:
        check_bind("10.0.0.5", "")
        raise AssertionError("토큰 없이 통과")
    except SystemExit:
        pass
    print("[selftest] 결과 크기 상한·바인딩·토큰 규칙 통과")
    _selftest_transport_security()
    assert _mcp_instructions() == _DEFAULT_MCP_INSTRUCTIONS  # DT1 c1 — 미설정이면 바이트 동일
    print("[selftest] MCP instructions — 코드 기본값 통과(DT1 c1)")


def test_main():  # 옛 `--selftest` 갈래(`selftest()` 뒤 `sys.exit(0)`)
    selftest()


def test_tool_names():
    """main.build()가 등록한 도구 이름·순서 = routers.TOOL_NAMES(mcp_smoke가 기대 목록으로 씀 — 0.2.0 6종)."""
    import asyncio

    from mcp_server.routers import TOOL_NAMES

    got = tuple(t.name for t in asyncio.run(build(host="127.0.0.1", port=8765).list_tools()))
    assert got == TOOL_NAMES, got
    from mcp_server.cli import mcp_smoke

    assert mcp_smoke.TOOLS == set(TOOL_NAMES)


def test_smoke_check():
    """mcp_smoke 판정 — 근거 칸은 계약(EVIDENCE_KEYS) 그대로 · 오류·0건·옛 칸(doc_key·source_uri)은 실패 · --source 필수."""
    from mcp_server.cli import mcp_smoke
    from mcp_server.schemas.evidence import EVIDENCE_KEYS

    ok = {k: None for k in EVIDENCE_KEYS} | {"chunk_key": "c1", "file_path": "SFDC/a.pdf"}
    old = {"doc_key": "d", "chunk_key": "c1", "source_uri": "s3://x"}
    for d, want_ok in [
        ({"evidence": [ok]}, True),
        ({"evidence": [ok | {"file_path": None}]}, False),
        ({"evidence": [old]}, False),
        ({"evidence": []}, False),
        ({"error": "source_system is required"}, False),
    ]:
        assert (mcp_smoke.check_search(d) == []) is want_ok, d
    try:
        mcp_smoke.main(["--url", "http://127.0.0.1:1/mcp"])
        raise AssertionError("--source 없이 통과")
    except SystemExit as e:
        assert e.code == 2, e.code
