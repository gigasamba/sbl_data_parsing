"""PC 가짜 대상(op-14): 경로 칸은 저장소 루트 기준 상대 경로를 받고, local은 서버 전용 칸(EDW 주소·Object Storage 주소·서버 게시 버킷)을
비우고 경고(칸 자리만) 뒤 시작한다(dev는 그대로)."""

import contextlib
import io
import tempfile
from pathlib import Path
from unittest import mock

import yaml

from common.config import layout, settings
from common.core import paths


def test_pc_targets():
    root = paths.PROJ_ROOT.as_posix()
    local_bucket = f"file://{root}/valid_env/object_storage/Parsing_Result"
    with tempfile.TemporaryDirectory() as directory, mock.patch.object(settings, "_warned", set()):
        path = Path(directory) / "settings.yaml"
        absolute = (Path(directory) / "edw.sqlite").resolve().as_posix()
        # (run_env, common.connections, 서버 게시 버킷, (볼 칸, 기대 값), 경고에 나와야 하는 칸 자리)
        for run, connections, publish, want, ignored in (
            ("local", {"rdb": {"sqlite": "valid_env/edw/edw.sqlite"}}, None, ("sqlite", f"{root}/valid_env/edw/edw.sqlite"), None),
            ("local", {"rdb": {"sqlite": absolute}}, None, ("sqlite", absolute), None),
            ("local", {}, "file://output/os/silver", ("bucket", local_bucket), "required.publish.publish_bucket"),
            ("local", {}, "rag-silver", ("bucket", local_bucket), "required.publish.publish_bucket"),
            ("local", {"rdb": {"host": "edw.corp.local"}}, None, ("host", None), "required.edw.edw_host"),
            ("dev", {"rdb": {"host": "edw.corp.local"}}, "rag-silver", ("bucket", "rag-silver"), None),
        ):
            doc = {"common": {"run_env": run, "connections": connections}, "pipeline": {"load": {"publish": {"bucket": publish}}}}
            path.write_text(yaml.safe_dump(layout.to_file(doc)), encoding="utf-8")
            environ = {"SETTINGS_FILE": str(path)}
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                st = settings.load(settings.section_class(("common", "pipeline"))[0], environ=environ)
                assert settings.require_run_env(environ=environ, sections=("pipeline",)) == run  # local도 거부하지 않음
            pipe = getattr(st, "pipeline", None)
            got = {
                "sqlite": st.common.connections.rdb.sqlite,
                "host": st.common.connections.rdb.host,
                "bucket": pipe.load.publish.bucket if pipe else want[1],
            }[want[0]]
            assert got == want[1], (run, want, got)
            assert (ignored in errors.getvalue()) if ignored else ("무시" not in errors.getvalue()), (run, errors.getvalue())
            assert "edw.corp.local" not in errors.getvalue() and "rag-silver" not in errors.getvalue()
            settings._warned.clear()
