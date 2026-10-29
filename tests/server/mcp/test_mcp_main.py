"""mcp_server.main 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.main --selftest`."""

import json

from mcp_server import config as mc
from mcp_server.main import _DEFAULT_MCP_INSTRUCTIONS, _mcp_instructions, build, check_bind
from mcp_server.services.search.shaping import cap
from tests.server.mcp.test_dispatch import _selftest_concurrency, _selftest_overload
from tests.server.mcp.test_internal_docs import (
    _selftest_aggregate_struct_fail,
    _selftest_evidence_image_fetch,
    _selftest_evidence_image_local_folder,
    _selftest_evidence_image_office_and_bbox,
    _selftest_list_documents,
    _selftest_list_documents_latest_only_doc_id,
    _selftest_lookup_term,
)
from tests.server.mcp.test_search_svc import (
    _selftest_agg_fx,
    _selftest_agg_route,
    _selftest_agg_table_text,
    _selftest_br50_client_scope,
    _selftest_copy_group,
    _selftest_copy_group_rep_text,
    _selftest_entity_split,
    _selftest_evidence_gate,
    _selftest_evidence_rdb_meta,
    _selftest_evidence_rep_path,
    _selftest_graph_client_restrict,
    _selftest_index_id,
    _selftest_query_log,
    _selftest_search_client_arg,
    _selftest_search_notes_no_race,
)
from tests.server.mcp.test_server_state import (
    _selftest_reload,
    _selftest_warmup_bg_failure_keeps_server_up,
    _selftest_warmup_health,
)
from tests.server.mcp.test_shaping import _selftest_cap_fuzz, _selftest_cap_ranked


def _selftest_transport_security():
    """L8 — 루프백은 FastMCP 자체 기본값(바이트 동일, 안 건드림) · 비루프백은 기본 ON(전엔 명시적으로 꺼둠) ·
    MCP_ALLOWED_HOSTS로 추가 호스트(리버스 프록시 등)를 더할 수 있음. 실제 421/403 거부는 dev_tools/unit_test/pipeline/
    test_mcp_server_transport_security.py(ASGI in-process 호출)가 확인."""
    ts_loop = build(host="127.0.0.1").settings.transport_security
    assert ts_loop.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"], ts_loop.allowed_hosts
    ts_non = build(host="10.0.0.5").settings.transport_security
    assert ts_non.enable_dns_rebinding_protection is True
    assert ts_non.allowed_hosts == ["10.0.0.5:*"] and "http://10.0.0.5:*" in ts_non.allowed_origins, ts_non
    with mc.senv(MCP_ALLOWED_HOSTS="proxy.local:9999, gw.local:*"):
        ts2 = build(host="10.0.0.5").settings.transport_security
        assert "proxy.local:9999" in ts2.allowed_hosts and "gw.local:*" in ts2.allowed_hosts, ts2.allowed_hosts
        assert "http://proxy.local:9999" in ts2.allowed_origins and "https://gw.local:*" in ts2.allowed_origins, ts2.allowed_origins
    print("[selftest] L8 — 루프백 바이트 동일·비루프백 DNS 리바인딩 보호 기본 ON·MCP_ALLOWED_HOSTS 추가 반영 통과")


def selftest():
    from common.core.paths import STACK_FILE
    from common.store.db import cfgtables

    cfgtables._CACHE.setdefault(
        "stack", cfgtables.read_file("stack", STACK_FILE)
    )  # S8b — 시험은 판 표 대신 파일(이미지 selftest엔 PG가 없음)
    o = {"evidence": [{"text": "가" * 5000}, {"text": "나" * 5000}]}
    assert len(json.dumps(cap(o, 3000), ensure_ascii=False)) <= 3000 and o["truncated"]
    _selftest_cap_ranked()
    _selftest_cap_fuzz()
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
    with mc.senv(MCP_INSTRUCTIONS="가짜회사 반도체 설비 문서 검색"):  # 가짜 회사 예시
        assert _mcp_instructions() == "가짜회사 반도체 설비 문서 검색"
    assert _mcp_instructions() == _DEFAULT_MCP_INSTRUCTIONS
    print("[selftest] MCP_INSTRUCTIONS — 미설정 바이트 동일·가짜 회사 예시 반영 통과(DT1 c1)")
    _selftest_aggregate_struct_fail()
    _selftest_lookup_term()
    _selftest_concurrency()
    _selftest_overload()
    _selftest_reload()
    _selftest_search_notes_no_race()
    _selftest_evidence_gate()
    _selftest_agg_route()
    _selftest_agg_table_text()
    _selftest_agg_fx()
    _selftest_search_client_arg()
    _selftest_entity_split()
    _selftest_graph_client_restrict()
    _selftest_br50_client_scope()
    _selftest_list_documents()
    _selftest_list_documents_latest_only_doc_id()
    _selftest_evidence_rdb_meta()
    _selftest_query_log()
    _selftest_evidence_rep_path()
    _selftest_evidence_image_fetch()
    _selftest_index_id()
    _selftest_evidence_image_local_folder()
    _selftest_evidence_image_office_and_bbox()
    _selftest_copy_group()
    _selftest_copy_group_rep_text()
    _selftest_warmup_health()
    _selftest_warmup_bg_failure_keeps_server_up()


def test_main():  # 옛 `--selftest` 갈래(`selftest()` 뒤 `sys.exit(0)`)
    selftest()
