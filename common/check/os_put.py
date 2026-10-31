#!/usr/bin/env python3
"""폴더 → Object Storage(S3 호환) 올리기 — 시험용(개발 서버 MinIO 모의 저장소 · 백로그 O6). 접속 값·비밀은 settings.yaml required.object_storage.
사용(저장소·이미지 루트에서 — S7b부터 설정 객체를 읽어 PYTHONPATH와 pydantic이 있어야 함, VS7b R-10 · S7e2부터 env OS_*는 읽지 않음):
  SETTINGS_FILE=$(python -m common.config.overrides --base <settings.yaml> OS_ENDPOINT=http://127.0.0.1:19000) PYTHONPATH=. \
    python -m common.check.os_put <폴더> s3://버킷/접두        (PC — 덮기 파일 도구는 PC 전용, valid_env/docker/smoke_test.sh — VS7e2 R-7)"""

import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    src, uri = Path(sys.argv[1]), sys.argv[2]
    bucket, _, prefix = uri[5:].partition("/")
    import boto3

    from common.config.settings import cfg, reveal  # S7b — 설정 객체(옛 OS_* env 이름 그대로 칸이 됨)

    os_cfg = cfg().connections.object_storage
    cli = boto3.client(
        "s3",
        endpoint_url=os_cfg.endpoint or None,
        region_name=os_cfg.region or "us-east-1",
        aws_access_key_id=reveal(os_cfg.access_key),
        aws_secret_access_key=reveal(os_cfg.secret_key),
    )
    if bucket not in {b["Name"] for b in cli.list_buckets().get("Buckets", [])}:
        cli.create_bucket(Bucket=bucket)
    files = [p for p in sorted(src.iterdir()) if p.is_file()]
    for p in files:
        cli.upload_file(str(p), bucket, f"{prefix.rstrip('/')}/{p.name}".lstrip("/"))
    print(f"올림 {len(files)}개 → {uri}")


if __name__ == "__main__":
    main()
