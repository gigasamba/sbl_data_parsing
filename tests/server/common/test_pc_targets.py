"""PC 가짜 대상(op-14): 경로 칸은 저장소 루트 기준 상대 경로를 받고, local에서 실제 EDW·Object Storage 칸은 시작 거부."""

import contextlib
import io
import tempfile
from pathlib import Path

import yaml

from common.config import layout, settings
from common.core import paths


def test_pc_targets():
    root = paths.PROJ_ROOT.as_posix()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "settings.yaml"
        absolute = (Path(directory) / "edw.sqlite").resolve().as_posix()
        for run, connections, publish, want, refused in (
            ("local", {"rdb": {"sqlite": "valid_env/edw/edw.sqlite"}}, None, ("sqlite", f"{root}/valid_env/edw/edw.sqlite"), None),
            ("local", {}, "file://output/os/silver", ("bucket", f"file://{root}/output/os/silver"), None),
            ("local", {"rdb": {"sqlite": absolute}}, None, ("sqlite", absolute), None),
            ("local", {}, "rag-silver", ("bucket", "rag-silver"), "pipeline.load.publish.bucket"),
            ("local", {"rdb": {"host": "edw.corp.local"}}, None, None, "common.connections.rdb.host"),
            ("dev", {"rdb": {"host": "edw.corp.local"}}, "rag-silver", ("bucket", "rag-silver"), None),
        ):
            doc = {"common": {"run_env": run, "connections": connections}, "pipeline": {"load": {"publish": {"bucket": publish}}}}
            path.write_text(yaml.safe_dump(layout.to_file(doc)), encoding="utf-8")
            environ = {"SETTINGS_FILE": str(path)}
            if want:
                st = settings.load(settings.section_class(("common", "pipeline"))[0], environ=environ)
                got = st.common.connections.rdb.sqlite if want[0] == "sqlite" else st.pipeline.load.publish.bucket
                assert got == want[1], (run, got)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                try:
                    actual = settings.require_run_env(environ=environ, sections=("pipeline",))
                except SystemExit as exc:
                    assert exc.code == 2 and refused and refused.rsplit(".", 1)[1] in errors.getvalue(), (run, errors.getvalue())
                else:
                    assert actual == run and not refused, (run, connections, publish)
