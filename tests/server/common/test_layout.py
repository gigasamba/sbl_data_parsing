"""op-08 ② — settings.yaml 새 배치(required·역할 절·tuning — common.config.layout).
칸 자리 ↔ 모델 경로가 1:1인지, PC에서 흔히 쓰는 꼴의 새 배치 파일이 두 앱에서 읽히는지, 같은 내용의 옛 배치 파일을 migrate가 같은 값으로
바꾸는지, 옛 배치·자리가 바뀐 칸은 migrate 안내와 함께 거부하는지 본다. 외부 접속 없음, 임시 폴더만(값은 시험용 가짜)."""

import tempfile
from pathlib import Path

from common.config import layout
from common.config.settings import SettingsError, app_classes, load, read_settings, walk

PC_NEW = """required:
  env:
    run_env: local
    run_mode: prod
  pg:
    host: 127.0.0.1
    port: 55433
    db: rag
    user: rag
    password: dummy-pg
    db_schema: rag_test
  embed:
    base_url: http://127.0.0.1:9/v1
    model: test-embed
    api_key: dummy-key
search:
  server:
    host: 127.0.0.1
    port: 8765
tuning:
  ops:
    runtime:
      cpu_max_load: 4
dev:
  models:
    guard:
      budget_usd: 1.5
  mcp:
    mcp_url: http://127.0.0.1:8765/mcp
"""
PC_OLD = """common:
  run_env: local
  connections:
    pg:
      host: 127.0.0.1
      port: 55433
      db: rag
      user: rag
      password: dummy-pg
      db_schema: rag_test
  models:
    guard:
      budget_usd: 1.5
    embed:
      base_url: http://127.0.0.1:9/v1
      model: test-embed
      api_key: dummy-key
  store:
    run_mode: prod
  runtime:
    cpu_max_load: 4
  paths:
    mcp_bundle: output/bundle
pipeline:
  transform:
    structure:
      embed: api
mcp:
  server:
    host: 127.0.0.1
    port: 8765
  dev:
    mcp_url: http://127.0.0.1:8765/mcp
"""


def _raises(fn, *needles):
    try:
        fn()
    except SettingsError as e:
        return all(n in str(e) for n in needles)
    return False


def test_layout_is_one_to_one():
    seen = {}
    for cls in app_classes().values():
        for p, _f, _ in walk(cls):
            y = layout.to_yaml(p)
            assert layout.to_model_path(y) == p, (p, y)
            assert seen.setdefault(y, p) == p, (y, p, seen[y])
    assert set(layout.SECTIONS) >= {y.split(".", 1)[0] for y in seen}


def test_pc_file_new_layout_and_migrate():
    classes = app_classes()
    with tempfile.TemporaryDirectory() as d:
        new = Path(d) / "settings.yaml"
        new.write_text(PC_NEW, encoding="utf-8")
        for name, cls in classes.items():
            st = load(cls, file=new, environ={})
            c = st.common
            assert c.run_env == "local" and c.store.run_mode == "prod" and c.connections.pg.port == 55433, name
            assert c.connections.pg.password.get_secret_value() == "dummy-pg" and c.models.embed.model == "test-embed", name
            assert c.models.guard.budget_usd == 1.5 and c.runtime.cpu_max_load == 4.0, name
            assert not hasattr(c.paths, "mcp_bundle"), name  # mc-19 — 지운 칸: 남아 있어도 경고만(시작은 함)
            if name == "mcp":
                assert st.mcp.server.port == 8765 and st.mcp.dev.mcp_url == "http://127.0.0.1:8765/mcp"
        gone = Path(d) / "gone.yaml"  # 11-03 지운 PC 비용 칸 5개 — 남아 있어도 경고만(시작은 함)
        gone.write_text(
            PC_NEW.replace(
                "      budget_usd: 1.5\n",
                "      budget_usd: 1.5\n      no_paid_calls: true\n      max_calls: 40\n      external_max_docs: 3\n      external_max_questions: 3\n      external_scope: x\n",
            ),
            encoding="utf-8",
        )
        g = load(next(iter(classes.values())), file=gone, environ={}).common.models.guard
        assert g.budget_usd == 1.5 and not any(hasattr(g, k) for k in ("no_paid_calls", "max_calls", "external_scope")), g
        moved = Path(d) / "moved.yaml"  # 11-04(op-05) — PC 전용 칸의 옛 자리(common.models.guard)도 경고 뒤 읽음
        moved.write_text("required:\n  env: {run_env: local}\ncommon:\n  models:\n    guard: {budget_usd: 1.5}\n", encoding="utf-8")
        assert load(next(iter(classes.values())), file=moved, environ={}).common.models.guard.budget_usd == 1.5
        moved.write_text(PC_NEW + "common:\n  models:\n    guard: {budget_usd: 2}\n", encoding="utf-8")
        assert _raises(lambda: load(next(iter(classes.values())), file=moved, environ={}), "두 자리", "dev.models.guard.budget_usd")
        moved.write_text("required:\n  env: {run_env: local}\ndev:\n  connections:\n    pg: {host: h}\n", encoding="utf-8")
        assert _raises(lambda: read_settings(moved), "dev.connections.pg.host → required.pg.host")  # dev 절은 PC 전용 칸만
        old = Path(d) / "old.yaml"
        old.write_text(PC_OLD, encoding="utf-8")
        assert _raises(lambda: load(next(iter(classes.values())), file=old, environ={}), "common.config.migrate")
        if {"pipeline", "mcp"} <= set(classes):  # migrate는 두 앱 모델이 다 있는 코드에서만(PC·코드 폴더)
            from common.config import migrate

            doc, report = migrate.convert_yaml(old, classes)
            out = Path(d) / "migrated.yaml"
            out.write_text(migrate.dump_yaml(doc), encoding="utf-8")
            assert (
                report["칸"] == 16
                and report["삭제됨"] == ["common.paths.mcp_bundle", "pipeline.transform.structure.embed"]
                and not report["모름"]
            ), report  # mc-19·op-05 지운 칸
            assert read_settings(out) == read_settings(new)


def test_misplaced_and_unknown_keys():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.yaml"
        f.write_text("required:\n  env: {run_env: local}\ncommon:\n  connections:\n    pg: {host: h}\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "common.connections.pg.host → required.pg.host", "migrate")
        f.write_text("required:\n  env: {run_env: local}\n  pg: {hots: h}\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "모르는 칸", "required.pg.hots")
        f.write_text("required:\n  env: {run_env: local}\nextract:\n", encoding="utf-8")
        assert read_settings(f)[0] == {"common": {"run_env": "local"}}  # 빈 절 머리는 괜찮음
        f.write_text("required:\n  env: {run_env: local}\n  deploy: {mcp_store: pg}\n", encoding="utf-8")
        assert read_settings(f)[0] == {"common": {"run_env": "local"}}  # 지운 자리(RETIRED — mc-01 11-01)는 경고만, 거부 안 함
        # 11-04 — tuning으로 옮긴 칸(TUNING_RARE)의 옛 역할 자리도 읽음 · 새 자리와 둘 다 적으면 거부
        f.write_text("required:\n  env: {run_env: local}\nsearch:\n  weights: {bm25: 3}\n", encoding="utf-8")
        assert read_settings(f)[0]["mcp"]["search"]["weights"]["bm25"] == "3"
        f.write_text(
            "required:\n  env: {run_env: local}\nsearch:\n  weights: {bm25: 3}\ntuning:\n  search:\n    weights: {bm25: 4}\n",
            encoding="utf-8",
        )
        assert _raises(lambda: read_settings(f), "두 자리", "tuning.search.weights.bm25")
    classes = app_classes()
    if "pipeline" in classes:  # 11-04 합친 칸 — 옛 자리(역할·tuning)에 남아도 경고만(시작은 함)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "s.yaml"
            f.write_text(
                "required:\n  env: {run_env: local}\nextract:\n  prefetch_workers: 3\ntuning:\n  ops:\n    nightly_run: {workers: 5}\n",
                encoding="utf-8",
            )
            st = load(classes["pipeline"], file=f, environ={})
            assert not hasattr(st.pipeline.extract, "prefetch_workers") and not hasattr(st.pipeline.night, "workers")


def test_duplicate_key_rejected():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.yaml"
        f.write_text(
            "search:\n  server: {port: 1}\nrequired:\n  env: {run_env: local}\nsearch:\n  output: {max_chars: 2}\n", encoding="utf-8"
        )
        assert _raises(lambda: read_settings(f), "같은 칸 두 번: search", "5행")
        f.write_text("required:\n  env: {run_env: local, run_env: dev}\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "같은 칸 두 번: run_env")
        f.write_text("required:\n  env: {run_env: local}\ndev:\n  mcp:\n    <<: {ui_port: 1}\n", encoding="utf-8")
        assert read_settings(f)[0]["mcp"]["dev"]["ui_port"] == "1"  # 병합 열쇠는 거부하지 않음
        f.write_text("required:\n  env: {run_env: local}\n? [a]\n: 1\n", encoding="utf-8")
        assert _raises(lambda: read_settings(f), "YAML 형식 오류")  # 못 쓰는 열쇠도 TypeError가 아닌 설정 오류


def test_removed_warned_once():
    """F7(11-03 PC 시험) — 지운 칸 경고는 프로세스마다 이름 하나에 한 번(설정을 여러 번 읽어도)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        for _ in range(3):
            layout.warn_removed("test.once.key")
    assert buf.getvalue().count("지운 칸 무시: test.once.key") == 1, buf.getvalue()
