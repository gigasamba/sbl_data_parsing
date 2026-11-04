"""parse_document 파일 크기 상한 — 검색 MCP(프록시)와 파싱 작업 서비스가 같은 칸(ops.runtime.parse_max_mb)을 같은 식으로 쓴다."""

from common.config.settings import cfg

MB = 1048576


def max_bytes():
    """파일 1건 크기 상한(바이트) — 부를 때마다 설정에서 읽는다(기본 100MB)."""
    return int(cfg().runtime.parse_max_mb * MB)


def body_cap():
    """HTTP 요청 본문 상한 — base64는 파일의 4/3배라 1.5배 + 1MiB. 상한을 조금 넘는 파일도 본문에서 막히지 않고 크기 안내를 받는다."""
    return max_bytes() * 3 // 2 + MB


def too_big(n):
    """n바이트가 상한을 넘으면 안내 글자(크기·상한 MB), 아니면 None."""
    if n > max_bytes():
        return f"파일이 크기 상한({cfg().runtime.parse_max_mb:g}MB)보다 큼({n / MB:.1f}MB) — ops.runtime.parse_max_mb"
    return None
