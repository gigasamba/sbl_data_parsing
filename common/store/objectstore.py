"""Object Storage(S3 호환) 접속 — pipeline/extract/fetch_docs.py(수집, rag-parse)·modules/search/mcp_server.py(근거 이미지
원천 재접근, rag-core, OP21) 공용. rag-core↔rag-parse 사이 직접 import가 금지라 여기(common/)로 승격(이미지에
있는 boto3만 씀, 새 패키지 없음).

접속: OS_ENDPOINT · OS_ACCESS_KEY · OS_SECRET_KEY · OS_REGION(기본 us-east-1) · OS_VERIFY_TLS(기본 1, 사내 CA면
경로) — 비밀값은 env 파일에만."""

import sys

from common.config.settings import cfg, reveal

_tls_warned = False  # L8b — 프로세스당 한 번만 경고


def resolve_tls_verify():
    """OS_VERIFY_TLS(기본 1) → boto3 verify 인자. 끄면(0) 경고 1번(OS_ENDPOINT가 내부망이 아니면 더 크게) —
    client()·pipeline/load/publish_parse_result.py의 S3Store가 공용으로 부른다(가드는 한 곳)."""
    v = cfg().connections.object_storage.verify_tls  # S7b — 설정 객체(기본 '1', 빈 값 그대로 — blank=keep)
    verify = False if v == "0" else True if v == "1" else v
    if verify is False:
        _warn_tls_off()
    return verify


def _warn_tls_off():
    global _tls_warned
    if _tls_warned:
        return
    _tls_warned = True
    ep = cfg().connections.object_storage.endpoint
    endpoint = ep or "(미설정)"
    loud = ""
    try:
        from common.ai.guard import is_internal

        if ep and not is_internal(ep):
            loud = " — 내부망 주소가 아님, 더 위험(중간자 공격에 그대로 노출)"
    except Exception:
        pass
    print(
        f"[objectstore] 경고: OS_VERIFY_TLS=0 — TLS 인증서 검증이 꺼져 있음(엔드포인트: {endpoint}){loud}. "
        "사내 CA 등 확실한 이유가 아니면 켜세요.",
        file=sys.stderr,
        flush=True,
    )


def client(timeout=None):
    """boto3 s3 클라이언트. timeout(초)이 있으면 connect·read 둘 다 그 값으로(OP21 근거 이미지 받기 시간 상한)."""
    import boto3
    from botocore.config import Config

    cfg_kwargs = {"retries": {"max_attempts": 3}}
    if timeout:
        cfg_kwargs.update(connect_timeout=timeout, read_timeout=timeout)
    os_ = cfg().connections.object_storage  # S7b — 설정 객체
    return boto3.client(
        "s3",
        endpoint_url=os_.endpoint or None,
        region_name=os_.region or "us-east-1",
        aws_access_key_id=reveal(os_.access_key),
        aws_secret_access_key=reveal(os_.secret_key),
        verify=resolve_tls_verify(),
        config=Config(**cfg_kwargs),
    )
