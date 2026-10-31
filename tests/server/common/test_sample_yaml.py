"""op-05 — settings.sample.yaml(모든 칸 + 코드 기본값)을 그대로 복사한 settings.yaml로 서버(run_env: dev — STRICT)가 시작되고, 적힌 값은
코드 기본값과 같다(sample을 복사해도 동작이 바뀌지 않음). 적었는지로 동작이 갈리는 칸(given()·_f·own·pinned)은 sample에 적지 않는다.
외부 접속 없음, 임시 폴더만."""

import re
import tempfile
from pathlib import Path

import yaml

from common.config import layout, sample
from common.config.settings import CommonAppSettings, _is_set, app_classes, env_map, load, walk
from common.core.paths import DEPLOY_ROOT

_SET_READ = re.compile(r"\b(?:given|_given|_f|own|setting)\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']")


def _get(obj, path):
    for part in path.split("."):
        obj = (obj or {}).get(part) if isinstance(obj, dict) or obj is None else getattr(obj, part)
    return obj


def _set_read_names():
    """코드에서 '준 값만' 읽는 이름(given("X")·resources._f("X")·model_matrix.own("X") 등) — 이 이미지에 있는 폴더만.
    코드 루트는 DEPLOY_ROOT(PC = 저장소 루트, 이미지 = /app/deploy — PROJ_ROOT는 이미지에서 /app이라 코드가 없음, 이미지 관문 10-30)."""
    out = set()
    for top in ("common", "pipeline", "mcp_server", "validation"):
        for f in (DEPLOY_ROOT / top).rglob("*.py") if (DEPLOY_ROOT / top).is_dir() else ():
            out |= set(_SET_READ.findall(f.read_text(encoding="utf-8")))
    return out


def test_copied_sample_starts_with_defaults():
    text = sample.build().replace("\n    run_env:  #", "\n    run_env: dev  #", 1)
    tree = yaml.safe_load(text)
    assert tree["required"]["env"]["run_env"] == "dev"
    names = _set_read_names()
    assert "STRUCT_BACKEND" in names  # 검색이 코드를 실제로 찾았는지
    with tempfile.TemporaryDirectory() as d:
        y = Path(d) / "settings.yaml"
        y.write_text(text, encoding="utf-8")
        for cls in (CommonAppSettings, *app_classes().values()):
            st = load(cls, file=y, environ={})  # STRICT — 모르는 칸·틀린 값이면 SettingsError
            for top in cls.model_fields:
                for p in (p for p, _, _ in walk(cls) if p.split(".")[0] == top):
                    v = _get(tree, layout.to_yaml(p))
                    if v is not None and p != "common.run_env":
                        assert _get(st, p) == v, (p, _get(st, p), v)
            for name, p in env_map(cls).items():
                if name in names and p != "common.run_env":
                    assert not _is_set(st, p), (name, p, "적었는지로 동작이 갈리는 칸 — sample.SET_MATTERS에 더함")
