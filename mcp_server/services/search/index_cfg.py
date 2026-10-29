"""검색 MCP(mcp_server) 전용 색인 입력 경고(10-14 함수별 분리 — common/core/index_cfg.py에서 이전, 로직 바이트 동일).
MCP가 색인을 열 때만 쓴다(빌더 cli/index.py 쪽 설정 계약은 pipeline/load/index_cfg.py)."""

from common.core.index_cfg import glossary_fp, roster_fp


def input_drift(info_d, env=None):
    """MCP가 색인을 열 때 — 색인을 만든 사전·명부와 지금 프로세스 env의 사전·명부가 다르면 경고 문장(거부 아님), 같거나 기록 없으면 None.
    질의 확장(X3)·고객 거르기(G12)는 MCP 쪽 사전·명부를 쓰므로 색인 쪽 고객 태그·개념과 어긋날 수 있음."""
    rec = (info_d or {}).get("inputs") or {}
    diff = [k for k, cur in (("glossary", glossary_fp(env)), ("roster", roster_fp(env))) if k in rec and rec[k] != cur]
    if not diff:
        return None
    return (
        f"색인 {info_d.get('index_id')}을 만든 "
        + "·".join({"glossary": "용어 사전", "roster": "고객 명부"}[k] for k in diff)
        + "이 이 MCP의 env와 다름 — 고객 태그·개념이 질의 쪽과 어긋날 수 있음(같은 env로 다시 빌드 권장)"
    )
