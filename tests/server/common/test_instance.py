"""여러 벌(ops.host.instance_name) — 벌 이름 하나로 PG 스키마·EDW 기록 표·개발 서버 게시 경로가 갈리고, prd·기본 포트는 시작 거부."""

import contextlib
import io
import tempfile
from pathlib import Path

import yaml

from common.config import layout, settings

PORTS = {"common": {"runtime": {"data_parsing_port": 8776}}, "mcp": {"server": {"port": 8775}}}


def _doc(run, inst, schema="rag", table=None, ports=True):
    doc = {"common": {"run_env": run, "host": {"instance": inst}, "connections": {"pg": {"db_schema": schema}}}}
    if table:
        doc["common"]["connections"]["parsing_meta"] = {"table": table}
    if ports:
        doc["common"]["runtime"] = dict(PORTS["common"]["runtime"])
        doc["mcp"] = PORTS["mcp"]
    return doc


def test_instance_names():
    # (벌, db_schema, 표, 기대 스키마, 기대 표)
    for inst, schema, table, want_schema, want_table in (
        (None, "rag", None, "rag", "AI.ParsingMeta"),  # 한 벌 — 그대로
        ("hong", "rag", None, "rag_hong", "AI.ParsingMeta_hong"),
        ("hong", "rag_hong", "AI.ParsingMeta_hong", "rag_hong", "AI.ParsingMeta_hong"),  # 이미 붙어 있으면(따로 적은 값) 그대로
        ("kim-2", "rag", "X.PM", "rag_kim_2", "X.PM_kim_2"),  # `-`는 `_`로(스키마·표 이름 규칙)
    ):
        st = settings.CommonSettings(**_doc("dev", inst, schema, table)["common"])
        assert (st.connections.pg.db_schema, st.connections.parsing_meta.table) == (want_schema, want_table), inst


def test_dbtool_schema_suffix():
    """dbtool --schema로 직접 준 이름에도 설정과 같은 벌 접미(이미 붙어 있으면 그대로)."""
    from common.store.db import dbtool

    for inst, given, want in ((None, "demo", "demo"), ("kim-2", "demo", "demo_kim_2"), ("kim-2", "demo_kim_2", "demo_kim_2")):
        with settings.COMMON.override(
            data={"common": {"run_env": "dev", "host": {"instance": inst}}}, use_file=False, strict=False, require_file=False
        ):
            assert dbtool.schema_of("search", given) == want, (inst, given)


def test_publish_prefix():
    # (run_env, 벌, 접두, 기대)
    for run, inst, prefix, want in (
        ("dev", "hong", "parse", "parse/hong"),
        ("dev", "hong", "", "hong"),
        ("dev", None, "parse", "parse"),
        ("local", "hong", "parse", "parse"),  # 개발 서버에서만
    ):
        with settings.COMMON.override(
            data={"common": {"run_env": run, "host": {"instance": inst}}}, use_file=False, strict=False, require_file=False
        ):
            assert settings.publish_prefix(prefix) == want, (run, inst, prefix)


def test_instance_gate():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "settings.yaml"
        # (run_env, 벌, 포트 적음, 거부 문구 — None이면 시작)
        for run, inst, ports, refused in (
            ("dev", "hong", True, None),
            ("dev", None, False, None),  # 한 벌은 기본 포트 그대로
            ("dev", "hong", False, "port"),
            ("prd", "hong", True, "ops.host.instance_name"),
            ("dev", "Hong_1", True, "ops.host.instance_name"),  # 영소문자·숫자·-만(load_settings.sh와 같은 꼴)
            ("dev", "-a", True, "ops.host.instance_name"),
        ):
            path.write_text(yaml.safe_dump(layout.to_file(_doc(run, inst, ports=ports))), encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                try:
                    actual = settings.require_run_env(environ={"SETTINGS_FILE": str(path)}, sections=("mcp",))
                except SystemExit as exc:
                    assert exc.code == 2 and refused and refused in errors.getvalue(), (run, inst, errors.getvalue())
                else:
                    assert actual == run and not refused, (run, inst, ports)
