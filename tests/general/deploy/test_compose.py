"""서버 compose 파일(op-18·op-19·op-20): 환경마다 하나(compose-<run_env>.yml). dev·prd에 PG·Redis(프로필 db).
dev = 개발자 벌 1~4만(벌 N = data_pipeline-N/{app,home} → /app·/root). prd·local = 번호 없는 컨테이너 3개.
비밀번호(SSH root·PG·Redis)는 compose 파일의 null 칸 — 서버 사본에서만 채우고 저장소에는 null만.
옛 덧붙임 파일(compose.*.yml)·EDW 사슬 사본 마운트는 없다(사슬은 코드 폴더·이미지 안 edw_chain.yaml)."""

import yaml

from common.core.paths import DEPLOY_ROOT

COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"
HEALTH = ["CMD", "python", "-m", "pipeline.run_mcp_parsing", "--health"]
JOBS = ":/app/output/_mcp_parse/jobs:z"  # parse_document 업로드·결과(검색 MCP는 결과가 읽기 전용이라 이 폴더만 쓰기)
MCP_CMD = ["devbox", "mcp", "--set", "MCP_PORT=8051"]

DB = {"pgvector": ("pgvector/pgvector:pg16", None, ["0.0.0.0:5433:5432"]), "redis": ("redis:7.4.8-alpine", None, ["0.0.0.0:8010:6379"])}
ROOT_PW = [{"source": "root_pw", "target": "/run/secrets/root_pw", "mode": 0o400}]
# 파일 → (묶음 이름, 재시작 정책(None = 없음), {서비스: (이미지 앞부분, 명령, 포트)})
# 서버(dev·prd)는 포트 칸 대신 SSH_PORT(문자열, SSH 없으면 None) — SSH 작업 공간은 bridge, 검색 MCP·작업 컨테이너는 network_mode: host
FILES = {
    "compose-local.yml": (
        "sbl-local",
        None,
        {
            "data-pipeline": ("data-pipeline-runtime:", ["idle"], None),
            "mcp-server": ("mcp-server-runtime:", ["mcp", "--set", "MCP_PORT=8051", "--set", "MCP_HOST=auto"], ["0.0.0.0:8051:8051"]),
            "mcp-data-parsing": ("data-pipeline-runtime:", ["run-mcp-parsing"], None),
        },
    ),
    "compose-dev.yml": (
        "docker-dev",
        "unless-stopped",
        {f"data-pipeline-{n}": ("data-pipeline-runtime:", ["devbox"], f"802{n}") for n in range(1, 5)} | DB,
    ),
    "compose-prd.yml": (
        "sbl-prd",
        "always",
        {
            "data-pipeline": ("data-pipeline:", ["devbox"], "8020"),
            "mcp-server": ("mcp-server:", MCP_CMD, "8050"),
            "mcp-data-parsing": ("data-pipeline:", ["run-mcp-parsing"], None),
        }
        | DB,
    ),
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
            env = s.get("environment", {})
            assert s["image"].startswith(image) and s["container_name"] == name, (f, name)
            if name in DB:  # 서버 하나에 하나 — 늘 always, 따로 켬(벌·묶음을 내려도 그대로)
                assert s["restart"] == "always" and s["profiles"] == ["db"] and s["ports"] == ports, (f, s)
                continue
            assert (cmd is None or s.get("command") == cmd) and s.get("restart") == restart, (f, name)
            if f in ("compose-dev.yml", "compose-prd.yml"):
                if name.startswith("data-pipeline"):  # SSH 작업 공간은 bridge — 컨테이너마다 opencode 서버(127.0.0.1:4096)
                    assert "network_mode" not in s and s["ports"] == [f"0.0.0.0:{ports}:{ports}"], (f, name)
                else:  # 검색 MCP(<서버 IP>:8051 바인드)·파싱 worker는 서버 네트워크 그대로
                    assert s["network_mode"] == "host" and "ports" not in s, (f, name)
                assert env.get("SSH_PORT") == ports, (f, name)
                assert s.get("configs") == (ROOT_PW if ports else None), (f, name)  # SSH 컨테이너만
                assert doc["configs"]["root_pw"] == {"content": None} and "secrets" not in doc, f
            else:
                assert s.get("ports") == ports, (f, name)
            assert not any("edw_chain" in v or "root_pw" in v or "redis_pw" in v for v in vols), (f, name, vols)
            # 폴더는 한 자리씩 — 옛 /app/root·/app/deploy·DEV_HOME 없음
            assert not any(":/app/root" in v or "/app/deploy" in v for v in vols) and "DEV_HOME" not in env, (f, name, vols)
            if name.startswith(("data-pipeline", "mcp-")):
                assert s["user"] == "0" and "RUN_ENV" not in env, (f, name)  # root · 환경은 settings.yaml
            if name == "mcp-data-parsing":
                assert s["healthcheck"]["test"] == HEALTH and s["cpu_shares"] == 4096 and "ports" not in s, (f, s)
                assert s.get("entrypoint") is None and "SSH_PORT" not in env, f  # SSH 없음 — 이미지 시작 그대로
            if name == "mcp-server":
                assert any(v.endswith(JOBS) for v in vols), (f, vols)
            if f == "compose-dev.yml":  # 벌 N 폴더 = 코드·settings.yaml·output(/app) + root 홈(/root)
                n = name.rsplit("-", 1)[1]
                assert any(v.endswith(f"/data_pipeline-{n}/app:/app:z") for v in vols), vols
                assert any(v.endswith(f"/data_pipeline-{n}/home:/root:z") for v in vols), vols
            if f == "compose-prd.yml":
                assert not any(":/app:" in v for v in vols), (name, vols)  # 코드는 이미지 안(결과만 /app/output에)
                if name != "mcp-data-parsing":  # 구운 이미지 ENTRYPOINT를 작업 공간(SSH)으로
                    assert s["entrypoint"][-1] == "/etc/devbox/dev_entry.sh" and env["APP_ENTRY"] == "/opt/sbl/docker/entrypoint.sh"
                    assert any(v.endswith(":/root:z") for v in vols), (name, vols)


def test_password_slots():
    """비밀번호 칸은 저장소에서 null(서버 사본에서 채움) — Redis는 env 칸 하나를 명령·상태 확인이 함께 씀."""
    for f in ("compose-dev.yml", "compose-prd.yml"):
        svc = _load(f)["services"]
        assert all(svc["pgvector"]["environment"][k] is None for k in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")), f
        redis = svc["redis"]
        assert redis["environment"] == {"REDIS_PASSWORD": None}, f
        assert '--requirepass "$$REDIS_PASSWORD"' in redis["command"][2] and "$$REDIS_PASSWORD" in redis["healthcheck"]["test"][1], f
        assert redis["command"][2].startswith('[ -n "$$REDIS_PASSWORD" ] ||'), f  # 칸이 비면 비밀번호 없이 뜨지 않고 멈춤
        assert "exec docker-entrypoint.sh redis-server " in redis["command"][2], f  # 이미지 입구가 root → redis 사용자로 바꿈


def test_entry_commands():
    entry = (DEPLOY_ROOT / "deploy" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "  run-mcp-parsing)" in entry and "pipeline.run_mcp_parsing" in entry
