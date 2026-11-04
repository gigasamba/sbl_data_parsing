"""층 코드 지문(code_fp): ① 결과를 바꾸는 transform 파일과 층 파일이 import하는 pipeline 파일은 모두 층에 들어 있다(빠지면 고쳐도 낡은 결과를 다시 씀),
② 기록·DB 표 정의처럼 결과와 무관한 common 파일은 지문을 바꾸지 않는다, 결과를 바꾸는 파일은 바꾼다. 임시 복사본에서 본다(실제 코드 수정 없음)."""

import shutil
import tempfile
from pathlib import Path

from common.core import artifacts as a
from common.core.paths import DEPLOY_ROOT


def test_every_transform_file_in_a_layer():
    own = {p.relative_to(DEPLOY_ROOT).as_posix() for layer in a.LAYER_CODE.values() for g in layer for p in DEPLOY_ROOT.glob(g)}
    files = {
        p.relative_to(DEPLOY_ROOT).as_posix()
        for p in (DEPLOY_ROOT / "pipeline" / "transform").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    missing = sorted(files - own - set(a.NOT_LAYER))
    assert not missing, f"층 목록(artifacts.LAYER_CODE)이나 NOT_LAYER에 적을 것: {missing}"


# 층 파일이 import해도 층에 넣지 않는 pipeline 파일 — 결과를 바꾸지 않음(실행 기록)
NOT_OUTPUT = {"pipeline/shared/runtrace.py"}


def _pipeline_imports(f):
    """파일이 import하는 pipeline 모듈 파일(deploy/ 기준 경로) — 점 이름을 뒤에서부터 줄여 .py나 패키지를 찾는다."""
    import ast

    def file_of(dotted):
        parts = dotted.split(".")
        for end in range(len(parts), 0, -1):
            p = DEPLOY_ROOT.joinpath(*parts[:end])
            for c in (p.with_suffix(".py"), p / "__init__.py"):
                if c.is_file():
                    return c.relative_to(DEPLOY_ROOT).as_posix()
        return None

    names = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "pipeline":
            names |= {f"{n.module}.{al.name}" for al in n.names}
        elif isinstance(n, ast.Import):
            names |= {al.name for al in n.names if al.name.split(".")[0] == "pipeline"}
    return {x for x in map(file_of, names) if x}


def test_layer_imports_in_layer():
    """층 파일이 import하는 pipeline 파일은 같은 층에 있다(엔진 코드는 p0) — 빠지면 그 파일을 고쳐도 지문이 안 바뀜."""
    if not (DEPLOY_ROOT / "pipeline" / "transform").is_dir():  # mcp-server 이미지
        return
    p0 = {p.relative_to(DEPLOY_ROOT).as_posix() for g in a.LAYER_CODE["p0"] for p in DEPLOY_ROOT.glob(g)}
    for layer, globs in a.LAYER_CODE.items():
        own = {p.relative_to(DEPLOY_ROOT).as_posix() for g in globs for p in DEPLOY_ROOT.glob(g) if p.is_file()}
        missing = sorted({m for f in own for m in _pipeline_imports(DEPLOY_ROOT / f)} - own - p0 - NOT_OUTPUT)
        assert not missing, f"층 {layer} 목록(artifacts.LAYER_CODE)에 적을 것: {missing}"


CASES = [  # (고칠 파일, 바뀌어야 하는 층)
    ("pipeline/transform/represent/text_normalize.py", {"p1"}),
    ("pipeline/shared/parse_run.py", {"p0", "p1"}),
    ("pipeline/transform/structure/client_roster.py", {"s"}),
    ("common/store/db/models/search_tables.py", set()),
    ("common/core/jsonlog.py", set()),
]


def test_code_fp_follows_output_code():
    if not (DEPLOY_ROOT / "pipeline" / "transform").is_dir():  # mcp-server 이미지 — pipeline은 cli·config만(층 파일 없음)
        print("[시험] pipeline 층 코드 없음(mcp-server 이미지) — 건너뜀")
        return
    with tempfile.TemporaryDirectory(prefix="orca_codefp_") as tmp:
        root = Path(tmp)
        for d in ("pipeline", "common", "mcp_server"):
            shutil.copytree(DEPLOY_ROOT / d, root / d, ignore=shutil.ignore_patterns("__pycache__"))
        fps = lambda: {layer: a.code_fp(layer, root) for layer in a.LAYER_CODE}
        base = fps()
        for rel, want in CASES:
            f = root / rel
            orig = f.read_bytes()
            f.write_bytes(orig + b"\n# x\n")
            now = fps()
            f.write_bytes(orig)
            got = {layer for layer in base if base[layer] != now[layer]}
            assert got == want, (rel, got, want)
