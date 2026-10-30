"""op-05 — settings.sample.yaml(모든 칸 + 코드 기본값)을 그대로 복사한 settings.yaml로 서버(run_env: dev — STRICT)가 시작되고, 적힌 값은
코드 기본값과 같다(sample을 복사해도 동작이 바뀌지 않음). 외부 접속 없음, 임시 폴더만."""

import tempfile
from pathlib import Path

import yaml

from common.config import sample
from common.config.settings import CommonAppSettings, _section_type, app_classes, load


def _get(obj, path):
    for part in path.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else getattr(obj, part)
    return obj


def test_copied_sample_starts_with_defaults():
    text = sample.build().replace("\n  run_env:  #", "\n  run_env: dev  #", 1)
    tree = yaml.safe_load(text)
    assert tree["common"]["run_env"] == "dev"
    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "settings.yaml"
        y.write_text(text, encoding="utf-8")
        for cls in (CommonAppSettings, *app_classes().values()):
            st = load(cls, file=y, environ={})  # STRICT — 모르는 칸·틀린 값이면 SettingsError
            for top in cls.model_fields:
                for p, _ in sample._leaves(_section_type(cls.model_fields[top].annotation), top):
                    v = _get(tree, p)
                    if v is not None and p != "common.run_env":
                        assert _get(st, p) == v, (p, _get(st, p), v)
