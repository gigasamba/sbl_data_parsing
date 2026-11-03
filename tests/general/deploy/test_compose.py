"""상주 컨테이너 배치(사용자 11-03 — rn-03·op-10): 컨테이너마다 compose 파일 하나 — compose.pipeline.yml = 일괄 data-pipeline,
compose.pipeline-mcp.yml = parse_document 전용 data-pipeline-mcp, compose.mcp-server.yml = mcp-server(코드 폴더 덧붙임도 파일마다 짝 하나),
전용 컨테이너가 CPU 나눔 비율이 더 높고 작업 서비스를 주 프로세스로 돌린다. 오버레이 패치 compose(compose.patch*.yml)는 없다."""

import re

import yaml

from common.core.paths import DEPLOY_ROOT

COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"


def _default(v):
    """`${X:-기본}` → 기본(숫자), 그냥 숫자면 그대로."""
    m = re.fullmatch(r"\$\{\w+:-(\d+)\}", str(v))
    return int(m.group(1)) if m else int(v)


FILES = {  # compose 파일 → (서비스, 컨테이너 이름, 코드 폴더 짝)
    "compose.pipeline.yml": ("data-pipeline", "data-pipeline", "compose.code.yml"),
    "compose.pipeline-mcp.yml": ("data-pipeline-mcp", "data-pipeline-mcp", "compose.code.pipeline-mcp.yml"),
    "compose.mcp-server.yml": ("mcp", "mcp-server", "compose.code.mcp-server.yml"),
}


def _services(name):
    return yaml.safe_load((COMPOSE / name).read_text(encoding="utf-8"))["services"]


def test_resident_containers():
    svc = {}
    for f, (name, container, code) in FILES.items():
        s = _services(f)
        assert set(s) == {name} and s[name]["container_name"] == container, (f, set(s))
        assert set(_services(code)) == {name}, code  # 짝 파일은 그 컨테이너만 — 혼자 띄워도 됨
        svc[name] = s[name]
    assert svc["data-pipeline"]["command"] == ["idle"] and svc["data-pipeline-mcp"]["command"] == ["parse-service"]
    assert _default(svc["data-pipeline-mcp"]["cpu_shares"]) > _default(svc["data-pipeline"]["cpu_shares"])
    up = (DEPLOY_ROOT / "deploy" / "host" / "scripts" / "mcp_up.sh").read_text(encoding="utf-8")
    assert "compose.pipeline-mcp.yml" in up and "compose.code.pipeline-mcp.yml" in up


def test_no_patch_overlay():
    assert not list(COMPOSE.glob("compose.patch*.yml"))
    entry = (DEPLOY_ROOT / "deploy" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "  parse-service)" in entry and "pipeline.mcp_parse_service" in entry


def test_env_mount():
    """서버 설정 폴더(EDW 사슬 사본 등 — 사용자 11-03)는 적재가 도는 data-pipeline에만 읽기 전용(:ro,z — RHEL SELinux)으로 /etc/rag/env."""
    for f, (name, _, _) in FILES.items():
        vols = [str(v) for v in _services(f)[name]["volumes"]]
        env = [v for v in vols if v.startswith("${SETTINGS_DIR")]  # settings.yaml이 실제로 있는 폴더(load_settings)
        if name == "data-pipeline":
            assert len(env) == 1 and env[0].endswith(":/etc/rag/env:ro,z"), env
        else:
            assert not env, (name, env)
