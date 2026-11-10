"""서버 compose 파일(op-18·op-19·op-20): 환경마다 하나(compose-<run_env>.yml) + 따로 띄우는 PG·Redis.
이름·이미지·포트·재시작 정책은 파일에 직접 적혀 있다(설정 칸 없음). parse_document 작업 컨테이너는 세 환경 모두에 있다.
옛 덧붙임 파일(compose.*.yml)·EDW 사슬 사본 마운트·root_pw 마운트는 없다(사슬은 코드 폴더·이미지 안 edw_chain.yaml)."""

import yaml

from common.core.paths import DEPLOY_ROOT

COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"
HEALTH = ["CMD", "python", "-m", "pipeline.run_mcp_parsing", "--health"]
JOBS = ":/app/output/_mcp_parse/jobs:z"  # parse_document 업로드·결과(검색 MCP는 결과가 읽기 전용이라 이 폴더만 쓰기)

# 파일 → (묶음 이름, 재시작 정책(None = 없음), {서비스: (이미지 앞부분, 명령, 포트)})
# 서버(dev·prd)는 서버 네트워크 그대로(network_mode: host) — 포트 칸 대신 SSH_PORT(문자열, SSH 없으면 None)
FILES = {
    "compose-local.yml": (
        "sbl-local",
        None,
        {
            "data-pipeline-0": ("data-pipeline-runtime:", ["idle"], None),
            "mcp-server-0": ("mcp-server-runtime:", ["mcp", "--set", "MCP_PORT=8051", "--set", "MCP_HOST=auto"], ["0.0.0.0:8051:8051"]),
            "mcp-data-parsing-0": ("data-pipeline-runtime:", ["run-mcp-parsing"], None),
        },
    ),
    "compose-dev.yml": (
        "docker-dev",
        "unless-stopped",
        {
            **{f"data-pipeline-{n}": ("data-pipeline-runtime:", ["devbox"], f"802{n}") for n in range(5)},
            "mcp-server-0": ("mcp-server-runtime:", ["devbox", "mcp", "--set", "MCP_PORT=8051"], "8050"),
            "mcp-data-parsing-0": ("data-pipeline-runtime:", ["run-mcp-parsing"], None),
        },
    ),
    "compose-prd.yml": (
        "sbl-prd",
        "always",
        {
            "data-pipeline-0": ("data-pipeline:", ["devbox"], "8020"),
            "mcp-server-0": ("mcp-server:", ["devbox", "mcp", "--set", "MCP_PORT=8051"], "8050"),
            "mcp-data-parsing-0": ("data-pipeline:", ["run-mcp-parsing"], None),
        },
    ),
    "compose-pgvector.yml": ("sbl-pgvector", "always", {"pgvector": ("pgvector/pgvector:pg16", None, ["0.0.0.0:5433:5432"])}),
    "compose-redis.yml": ("sbl-redis", "always", {"redis": ("redis:7.4.8-alpine", None, ["0.0.0.0:8010:6379"])}),
}


def _load(name):
    return yaml.safe_load((COMPOSE / name).read_text(encoding="utf-8"))


def test_compose_files():
    assert sorted(p.name for p in COMPOSE.glob("*.yml")) == sorted(FILES)  # 옛 덧붙임 파일 없음
    for f, (project, restart, services) in FILES.items():
        doc = _load(f)
        assert doc["name"] == project and set(doc["services"]) == set(services), f
        for name, (image, cmd, ports) in services.items():
            s = doc["services"][name]
            vols = [str(v) for v in s.get("volumes", [])]
            assert s["image"].startswith(image) and s["container_name"] == name, (f, name)
            assert (cmd is None or s.get("command") == cmd) and s.get("restart") == restart, (f, name)
            if f in ("compose-dev.yml", "compose-prd.yml"):
                assert s["network_mode"] == "host" and "ports" not in s, (f, name)
                assert s.get("environment", {}).get("SSH_PORT") == ports, (f, name)
            else:
                assert s.get("ports") == ports, (f, name)
            assert not any("edw_chain" in v or "root_pw" in v or "redis_pw" in v for v in vols), (f, name, vols)
            if name.startswith(("data-pipeline", "mcp-")):
                assert s["user"] == "0" and "RUN_ENV" not in s.get("environment", {}), (f, name)  # root · 환경은 settings.yaml
            if name == "mcp-data-parsing-0":
                assert s["healthcheck"]["test"] == HEALTH and s["cpu_shares"] == 4096 and "ports" not in s, (f, s)
                assert s.get("entrypoint") is None, f  # SSH 없음 — 이미지 entrypoint.sh 그대로
            if name == "mcp-server-0":
                assert any(v.endswith(JOBS) for v in vols), (f, vols)
            if f == "compose-prd.yml" and name != "mcp-data-parsing-0":  # 구운 이미지 ENTRYPOINT를 작업 공간(SSH)으로
                assert s["entrypoint"][-1] == "/etc/devbox/dev_entry.sh" and s["environment"]["APP_ENTRY"] == "/app/docker/entrypoint.sh"
            if f == "compose-prd.yml":
                assert not any(":/app/deploy" in v for v in vols), (name, vols)  # 코드는 이미지 안


def test_secret_env():
    """PG·Redis 비밀번호는 코드 폴더 맨 위 .env(사람이 적음)에서만 — 비어 있으면 compose가 멈춤(:?), 파일 붙임 없음."""
    pg = _load("compose-pgvector.yml")["services"]["pgvector"]
    env = pg["environment"]
    assert env["POSTGRES_PASSWORD"] == "${PG_PASSWORD:?.env에 PG_PASSWORD 필요}" and "POSTGRES_PASSWORD_FILE" not in env, env
    assert env["POSTGRES_USER"].startswith("${PG_USER:?") and env["POSTGRES_DB"].startswith("${PG_DB:?"), env
    assert not any(isinstance(v, dict) or "secrets" in str(v) for v in pg["volumes"]), pg["volumes"]
    redis = _load("compose-redis.yml")["services"]["redis"]
    assert redis["command"][:3] == ["redis-server", "--requirepass", "${REDIS_PASSWORD:?.env에 REDIS_PASSWORD 필요}"], redis["command"]
    assert redis["volumes"] == ["${REDIS_DATA:-/data/redis}:/data:z"] and "environment" not in redis, redis
    # 상태 확인은 비밀번호로 PONG(틀린 비밀번호면 unhealthy) — 값은 .env에서 compose가 채움(env로 넘기지 않음)
    assert redis["healthcheck"]["test"][1] == "REDISCLI_AUTH='${REDIS_PASSWORD}' redis-cli --no-auth-warning ping | grep -q PONG"


def test_entry_commands():
    entry = (DEPLOY_ROOT / "deploy" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "  run-mcp-parsing)" in entry and "pipeline.run_mcp_parsing" in entry
