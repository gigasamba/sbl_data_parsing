"""mcp_server.services.search.internal_docs 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.internal_docs`."""

from pathlib import Path

from mcp_server import config as mc
from mcp_server.services.search import internal_docs as M
from mcp_server.services.search.internal_docs import do_aggregate

ROOT = (
    Path(M.__file__).resolve().parents[3]
)  # 옛 main.py의 ROOT(= mcp_server/의 부모, 저장소 루트)와 같은 값 — selftest만 씀(옛 internal_docs.py의 줄 — `__file__`은 모듈 것으로)


def _selftest_aggregate_struct_fail():
    """RUN_MODE=prod + PG 실패(X1b) — do_aggregate가 StructDBError로 죽지 않고 note로 알림(서버 생존 확인)."""
    with mc.senv(RUN_MODE="prod", STRUCT_BACKEND="pg", STRUCT_DB=None, PG_PASSWORD=None, PG_CONN_FILE=None):  # S7d — 설정 객체 덮기
        r = do_aggregate("계약 ID 없는 RFI 중 계약으로 이어진 것은?")  # doc_link_question에 걸리는 질문 — structdb 경로를 탐
        assert "정형 저장소 연결 실패" in (r.get("note") or ""), r
    print("[selftest] RUN_MODE=prod + PG 실패 — do_aggregate가 안 죽고 note로 알림 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — internal_docs.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgtables

    cfgtables._CACHE.setdefault(
        "stack", cfgtables.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    _selftest_aggregate_struct_fail()
