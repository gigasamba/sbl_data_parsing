"""상주 컨테이너 배치(규칙: rn-03·op-10): 컨테이너마다 compose 파일 하나 — compose.pipeline.yml = 일괄 data-pipeline,
compose.data-parsing.yml = parse_document 전용 mcp-data-parsing, compose.mcp-server.yml = mcp-server(코드 폴더 덧붙임도 파일마다 짝 하나),
전용 컨테이너가 CPU 나눔 비율이 더 높고 작업 서비스를 주 프로세스로 돌린다. 오버레이 패치 compose(compose.patch*.yml)는 없다."""

import re

import yaml

from common.core.paths import DEPLOY_ROOT

COMPOSE = DEPLOY_ROOT / "deploy" / "host" / "compose"


def _default(v):
    """`${X:-기본}` → 기본(숫자), 그냥 숫자면 그대로."""
    m = re.fullmatch(r"\$\{\w+:-(\d+)\}", str(v))
    return int(m.group(1)) if m else int(v)


FILES = {  # compose 파일 → (서비스, 컨테이너 이름 변수(load_settings — 밑 이름 + 벌 번호), 코드 폴더 짝)
    "compose.pipeline.yml": ("data-pipeline", "PIPELINE_CNAME", "compose.code.yml"),
    "compose.data-parsing.yml": ("mcp-data-parsing", "DATA_PARSING_CNAME", "compose.code.data-parsing.yml"),
    "compose.mcp-server.yml": ("mcp", "MCP_CNAME", "compose.code.mcp-server.yml"),
}


def render(text, env):
    """compose 치환 `${X}`·`${X:-기본}`·`${X:?안내}`만(시험용 — docker 없이). 없는 `:?` 변수는 KeyError."""

    def one(m):
        name, op, arg = m.group(1), m.group(2) or "", m.group(3) or ""
        if env.get(name):
            return env[name]
        if op == ":-":
            return arg
        if op == ":?":
            raise KeyError(name)
        return ""

    return re.sub(r"\$\{(\w+)(:[-?])?([^}]*)\}", one, text)


def _services(name):
    return yaml.safe_load((COMPOSE / name).read_text(encoding="utf-8"))["services"]


def test_resident_containers():
    svc = {}
    for f, (name, container, code) in FILES.items():
        s = _services(f)
        # 이름은 load_settings가 만든 변수 하나(밑 이름 ops.containers.* + 벌 번호 — 고정 글자 없음)
        assert set(s) == {name} and s[name]["container_name"].startswith("${" + container + ":?"), (f, set(s))
        assert set(_services(code)) == {name}, code  # 짝 파일은 그 컨테이너만 — 혼자 띄워도 됨
        svc[name] = s[name]
    assert svc["data-pipeline"]["command"] == ["idle"] and svc["mcp-data-parsing"]["command"] == ["run-mcp-parsing"]
    assert _default(svc["mcp-data-parsing"]["cpu_shares"]) > _default(svc["data-pipeline"]["cpu_shares"])
    up = (DEPLOY_ROOT / "deploy" / "host" / "scripts" / "mcp_keepalive.sh").read_text(encoding="utf-8")
    assert "host_ctl.sh base up -d" in up and "$UP mcp-data-parsing" in up  # 띄우기는 host_ctl.sh — 같은 compose 파일 묶음


def test_no_patch_overlay():
    assert not list(COMPOSE.glob("compose.patch*.yml"))
    entry = (DEPLOY_ROOT / "deploy" / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "  run-mcp-parsing)" in entry and "pipeline.run_mcp_parsing" in entry


def test_edw_chain_mount():
    """EDW 사슬 서버 사본 — 파일 하나를 data-pipeline(적재)·mcp-server(search attrs)에 읽기 전용(:ro,z)으로
    /etc/rag/edw_chain.yaml(settings.yaml과 같은 방식) — 원본은 EDW_CHAIN_SRC(ops.host.host_edw_chain_file). parse_document 전용 컨테이너는 안 씀."""
    for f, (name, _, _) in FILES.items():
        vols = [str(v) for v in _services(f)[name]["volumes"]]
        chain = [v for v in vols if "edw_chain.yaml" in v]
        if name in ("data-pipeline", "mcp"):
            assert (
                len(chain) == 1
                and render(chain[0], {"EDW_CHAIN_SRC": "/srv/a/chain.yaml"}) == "/srv/a/chain.yaml:/etc/rag/edw_chain.yaml:ro,z"
            ), chain
        else:
            assert not chain, (name, chain)
