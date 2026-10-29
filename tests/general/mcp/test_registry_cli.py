"""mcp_server.cli.registry_cli 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.cli.registry_cli --selftest`."""

from tests.server.mcp import (
    test_search_registry as RREG,
)  # 옛 `RREG`(mcp_server.services.search.registry)의 selftest — S9에 그 모듈의 시험 파일로 옮김


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    RREG.selftest()  # 10-14 — show·report·hide·unhide(이 CLI 몫)만, build·scan 등은 common.store.registry 자신의 selftest가 돈다
