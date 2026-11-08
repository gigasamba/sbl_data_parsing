"""settings.yaml 배치(required·역할 절·tuning·dev — common.config.layout).
칸 자리 ↔ 모델 경로가 1:1인지, PC에서 흔히 쓰는 꼴의 파일이 두 앱에서 읽히는지, 옛 배치·옛 자리·모르는 칸은 칸 이름과 함께 거부하는지 본다.
외부 접속 없음, 임시 폴더만(값은 시험용 가짜)."""

import tempfile
from pathlib import Path

from common.config import layout
from common.config.settings import SettingsError, app_classes, load, read_settings, walk

PC_NEW = """required:
  env:
    run_env: local
  pg:
    pg_host: 127.0.0.1
    pg_port: 55433
    pg_database: rag
    pg_user: rag
    pg_password: dummy-pg
    pg_schema: rag_test
  models:
    embed_base_url: http://127.0.0.1:9/v1
    embed_model: test-embed
    embed_api_key: dummy-key
search:
  server:
    mcp_bind_host: 127.0.0.1
    mcp_port: 8765
tuning:
  ops:
    runtime:
      max_cpu_load: 4
dev:
  models:
    guard:
      daily_budget_usd: 1.5
  search_ui:
    search_ui_mcp_url: http://127.0.0.1:8765/mcp
"""

# 거부하는 칸 — (파일 본문, 읽는 앱, 오류에 나와야 하는 글자). 옛 자리는 새 자리를 알려 주고, 지운 칸·오타는 칸 이름만.
REFUSED = (
    ("common:\n  connections:\n    pg: {host: h}\n", "pipeline", "common.connections.pg.host → required.pg.pg_host"),
    ("common:\n  models:\n    guard: {spend_file: x}\n", "pipeline", "common.models.guard.spend_file → dev.models.guard.spend_ledger_file"),
    ("ops:\n  runtime: {pipe_procs: 2}\n", "pipeline", "ops.runtime.pipe_procs → ops.runtime.engine_processes"),  # 옛 이름 → 새 이름
    ("required:\n  llm: {llm_model: m}\n", "pipeline", "required.llm.llm_model"),  # 모델 접속은 required.models 한 곳
    (
        "common:\n  models:\n    embed: {allow_external: true}\n",
        "pipeline",
        "common.models.embed.allow_external → dev.models.embed.embed_allow_external",
    ),
    ("dev:\n  pg_standin: {pg_standin_dir: d}\n", "pipeline", "dev.pg_standin: Extra"),  # 지운 절(sqlite 대역 — e2-22)은 통째로 거부
    ("search:\n  weights: {bm25: 3}\n", "mcp", "search.weights.bm25 → tuning.search.weights.bm25_weight"),
    ("required:\n  source: {publish_bucket: b}\n", "pipeline", "required.source.publish_bucket"),
    ("required:\n  deploy: {mcp_store: pg}\n", "pipeline", "required.deploy.mcp_store"),
    ("required:\n  pg: {hots: h}\n", "pipeline", "required.pg.hots"),
    (  # 옮긴 required 칸(layout.MOVED) — 빈 줄이어도 새 자리를 알려 줌
        "required:\n  edw: {edw_local_sqlite_file: }\n",
        "pipeline",
        "required.edw.edw_local_sqlite_file → dev.local.local_edw_sqlite_file",
    ),
    ("required:\n  env: {run_mode: prod}\n", "pipeline", "required.env.run_mode"),
    ("required:\n  tokens: {parse_proxy: tok-123456}\n", "mcp", "required.tokens.parse_proxy"),
    ("search:\n  server: {warmup: false}\n", "mcp", "warmup"),
    ("dev:\n  models:\n    guard: {no_paid_calls: true}\n", "pipeline", "no_paid_calls"),
    ("ops:\n  paths: {mcp_bundle: x}\n", "pipeline", "mcp_bundle"),
    ("pipeline:\n  extract: {}\n", "pipeline", "pipeline"),  # 옛 배치(최상위 앱 절)
)


def _err(fn):
    try:
        fn()
    except SettingsError as e:
        return str(e)
    return ""


def _raises(fn, *needles):
    msg = _err(fn)
    return bool(msg) and all(n in msg for n in needles)


def test_layout_is_one_to_one():
    seen = {}
    for cls in app_classes().values():
        for p, _f, _ in walk(cls):
            y = layout.to_yaml(p)
            assert layout.to_model_path(y) == p, (p, y)
            assert seen.setdefault(y, p) == p, (y, p, seen[y])
    assert set(layout.SECTIONS) >= {y.split(".", 1)[0] for y in seen}


def test_pc_file_new_layout():
    classes = app_classes()
    with tempfile.TemporaryDirectory() as d:
        new = Path(d) / "settings.yaml"
        new.write_text(PC_NEW, encoding="utf-8")
        for name, cls in classes.items():
            st = load(cls, file=new, environ={})
            c = st.common
            assert c.run_env == "local" and c.connections.pg.port == 55433, name
            assert c.connections.pg.password.get_secret_value() == "dummy-pg" and c.models.embed.model == "test-embed", name
            assert c.models.guard.budget_usd == 1.5 and c.runtime.cpu_max_load == 4.0, name
            if name == "mcp":
                assert st.mcp.server.port == 8765 and st.mcp.dev.mcp_url == "http://127.0.0.1:8765/mcp"


def test_refused_keys():
    """모르는 칸·옛 자리·지운 칸은 시작 거부 — 오류에는 칸 자리만(값 없음)."""
    classes = app_classes()
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.yaml"
        for body, app, needle in REFUSED:
            if app not in classes:
                continue
            head = "" if body.startswith("required:") else "required:\n  env: {run_env: local}\n"
            f.write_text(head + body, encoding="utf-8")
            msg = _err(lambda: load(classes[app], file=f, environ={"RUN_ENV": "local"}))  # noqa: B023 — 바로 부름
            assert needle in msg and "tok-123456" not in msg, (body, msg)
        f.write_text("required:\n  env: {run_env: local}\nextract:\n", encoding="utf-8")
        assert read_settings(f)[0] == {"common": {"run_env": "local"}}  # 빈 절 머리는 괜찮음


def test_duplicate_key_rejected():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.yaml"
        f.write_text(
            "search:\n  server: {port: 1}\nrequired:\n  env: {run_env: local}\nsearch:\n  output: {max_chars: 2}\n", encoding="utf-8"
        )
        assert _raises(lambda: read_settings(f), "같은 칸 두 번: search", "5행")
        f.write_text("required:\n  env: {run_env: local, run_env: dev}\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "같은 칸 두 번: run_env")
        f.write_text("required:\n  env: {run_env: local}\ndev:\n  search_ui:\n    <<: {search_ui_port: 1}\n", encoding="utf-8")
        assert read_settings(f)[0]["mcp"]["dev"]["ui_port"] == "1"  # 병합 열쇠는 거부하지 않음
        f.write_text("required:\n  env: {run_env: local}\n? [a]\n: 1\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "YAML 형식 오류")  # 못 쓰는 열쇠도 TypeError가 아닌 설정 오류
