"""호스트 칸 → 셸 env(사용자 11-02 — 호스트 python은 PyYAML만): deploy/host/scripts/host_env.py가 설정 모델 export(common.config.export)와
같은 줄을 내는지, host_keys.tsv가 설정 모델과 같은지. 임시 settings.yaml만 — 설정·docker 없음(PC 전용)."""

import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path

import yaml

from common.config import export as E
from common.config import layout as L
from common.core.paths import DEPLOY_ROOT


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, DEPLOY_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _load("hostkeys", "deploy/release/hostkeys.py")
SECTIONS = list(K.HOST_SECTIONS)


def _host_env():
    return _load("host_env", "deploy/host/scripts/host_env.py")


def _value(path, name, kind):
    if kind == "num":
        return 4.0 if name.endswith("CPUS") else 7  # 4.0 → "4"(compose cpus)
    if name == "RUN_ENV":
        return "dev"
    if name in ("NIGHTLY_TIME", "NIGHTLY_DEADLINE"):
        return "01:30" if name == "NIGHTLY_TIME" else "06:00"  # HH:MM 칸(#99)
    if name == "DOCKER":
        return "podman"
    return f"/srv/x/{name.lower()}" if "DIR" in name or name in ("DOC_SRC", "RAG_OUT", "PATCH_CODE") else f"v-{name.lower()}:0.2.0"


def test_host_env_matches_export():
    assert K.main(["--check"]) == 0, "host_keys.tsv가 설정 모델과 다름 — PYTHONPATH=. python deploy/release/hostkeys.py"
    rows = [r.split("\t") for r in K.HOST_TABLE.read_text(encoding="utf-8").splitlines() if r and not r.startswith("#")]
    model = {}
    for path, name, kind in rows:
        L.set_path(model, path, _value(path, name, kind))
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "settings.yaml"
        f.write_text(yaml.safe_dump(L.to_file(model), allow_unicode=True), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = E.main(["--format", "sh", "--file", str(f), *[a for s in SECTIONS for a in ("--section", s)]])
        assert rc == 0
        want = sorted(out.getvalue().splitlines())
        H = _host_env()
        doc = L.to_model(yaml.load(f.read_text(encoding="utf-8"), Loader=yaml.BaseLoader), str(f))
        got = sorted(H.lines(doc, SECTIONS, "sh"))
    assert got == want and len(got) == len(rows), (sorted(set(got) ^ set(want)), len(got), len(rows))
    cases = [  # (값, 종류, 기대)
        ("4.0", "num", "4"),
        ("2.5", "num", "2.5"),
        ("  ", "text", None),  # 비운 칸 = 설정 안 함
        ("~", "text", None),  # YAML 널(글자 로더) = 설정 안 함
        ("null", "num", None),
        ("true", "bool", "1"),
        (["a", "b"], "list", "a,b"),
        (["a", "b"], "words", "a b"),
    ]
    for v, kind, want_s in cases:
        assert H.render(v, kind) == want_s, (v, kind, H.render(v, kind))
    print(f"[시험] 호스트 칸 → 셸 env — PyYAML만으로 export와 같은 줄 {len(got)}개 · host_keys.tsv = 설정 모델 · 값 꼴 {len(cases)}개 통과")
