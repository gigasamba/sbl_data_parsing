"""Object Storage(S3 호환) 접속 — 파이프라인(수집·게시)과 검색 MCP(근거 이미지 원천 재접근)가 함께 쓰므로
common에 둔다(모듈 경계). 이미지에 있는 boto3만 쓴다.

접속 칸: settings.yaml required.object_storage(endpoint·access_key·secret_key·region 기본 us-east-1·verify_tls 기본 1, 사내 CA면
CA 파일 경로) — 비밀값은 settings.yaml에만."""

import sys

from common.config.settings import cfg, reveal

_tls_warned = False  # 프로세스당 한 번만 경고


def resolve_tls_verify():
    """OS_VERIFY_TLS(기본 1) → boto3 verify 인자. 끄면(0) 경고 1번(OS_ENDPOINT가 내부망이 아니면 더 크게) —
    client()·pipeline/load/publish_parse_result.py의 S3Store가 공용으로 부른다(가드는 한 곳)."""
    v = cfg().connections.object_storage.verify_tls  # 설정 객체(기본 '1', 빈 값 그대로 — blank=keep)
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


def client(timeout=None, retries=3, max_pool=None):
    """boto3 s3 클라이언트. timeout(초)이 있으면 connect·read 둘 다 그 값으로(근거 이미지 받기 시간 상한). retries = 실패 뒤 다시 보내는 횟수(첫 시도 빼고). max_pool = 연결 풀 크기(없으면 boto3 기본 10 — 동시에 부르는 스레드 수에 맞춤).
    PC(RUN_ENV=local)는 거부 — 칸을 비워도 boto3 기본값(AWS 주소·~/.aws 키)으로 실제 S3에 닿을 수 있어서(op-14). 모든 S3 접속이 여기를 거친다."""
    from common.config.settings import guard_run_env

    if guard_run_env() == "local":
        raise RuntimeError(
            "[objectstore] PC(RUN_ENV=local)는 Object Storage(S3)에 접속하지 않음 — 원본은 valid_env/object_storage 폴더, "
            "게시는 file:// 폴더를 쓴다(op-14). s3:// 원천은 개발 서버(dev)에서 돌린다."
        )
    import boto3
    from botocore.config import Config

    cfg_kwargs = {"retries": {"max_attempts": retries}}  # botocore legacy: max_attempts = 다시 보내는 횟수
    if timeout:
        cfg_kwargs.update(connect_timeout=timeout, read_timeout=timeout)
    if max_pool:
        cfg_kwargs["max_pool_connections"] = max_pool
    os_ = cfg().connections.object_storage
    return boto3.client(
        "s3",
        endpoint_url=os_.endpoint or None,
        region_name=os_.region or "us-east-1",
        aws_access_key_id=reveal(os_.access_key),
        aws_secret_access_key=reveal(os_.secret_key),
        verify=resolve_tls_verify(),
        config=Config(**cfg_kwargs),
    )
