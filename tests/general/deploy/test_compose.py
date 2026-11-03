"""상주 컨테이너 배치(사용자 11-03 — rn-03·op-10): compose.pipeline.yml은 일괄 data-pipeline + parse_document 전용 data-pipeline-mcp 둘,
전용 컨테이너가 CPU 나눔 비율이 더 높고 작업 서비스를 주 프로세스로 돌린다. 오버레이 패치 compose(compose.patch*.yml)는 없다."""

import re

import yaml

from common.core.paths import DEPLOY_ROOT

COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"


def _default(v):
    """`${X:-기본}` → 기본(숫자), 그냥 숫자면 그대로."""
    m = re.fullmatch(r"\$\{\w+:-(\d+)\}", str(v))
    return int(m.group(1)) if m else int(v)


def test_resident_containers():
    svc = yaml.safe_load((COMPOSE / "compose.pipeline.yml").read_text(encoding="utf-8"))["services"]
    assert set(svc) == {"data-pipeline", "data-pipeline-mcp"}
    assert {s["container_name"] for s in svc.values()} == set(svc)
    assert svc["data-pipeline"]["command"] == ["idle"] and svc["data-pipeline-mcp"]["command"] == ["parse-service"]
    assert _default(svc["data-pipeline-mcp"]["cpu_shares"]) > _default(svc["data-pipeline"]["cpu_shares"])
    code = yaml.safe_load((COMPOSE / "compose.code.yml").read_text(encoding="utf-8"))["services"]
    assert set(code) == set(svc)  # 실행 이미지(코드 폴더)는 두 컨테이너 모두에 붙음


def test_no_patch_overlay():
    assert not list(COMPOSE.glob("compose.patch*.yml"))
    entry = (DEPLOY_ROOT / "deploy" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "  parse-service)" in entry and "pipeline.mcp_parse_service" in entry
