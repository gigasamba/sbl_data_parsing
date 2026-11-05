"""common.core.paths 자기 점검."""

import os
from pathlib import Path

from common.core.paths import (
    APP_ROOT,
    CRITERIA_FILE,
    DEPLOY_ROOT,
    GLOSSARY_ROOT,
    LOCAL_RUN,
    PKG_ROOT,
    PROJ_ROOT,
    RES_ROOT,
    STACK_FILE,
    atomic_write_bytes,
    atomic_write_text,
    child_env,
    doc_dir,
    lookup_run_dir,
    resolve_agent_dir,
    resolve_run_dir,
)


def _demo():
    import tempfile

    from common.config.settings import COMMON

    assert DEPLOY_ROOT == (PROJ_ROOT if LOCAL_RUN else PROJ_ROOT / "deploy") and PKG_ROOT == DEPLOY_ROOT / "common"
    assert APP_ROOT == PROJ_ROOT
    env = child_env({"X_DEMO": "1"})
    assert env["X_DEMO"] == "1" and str(PKG_ROOT.parent) in env["PYTHONPATH"].split(os.pathsep)
    assert env is not os.environ  # env 남김 — 시험 · 원본 os.environ을 안 바꿈
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        d1 = resolve_run_dir(root, None, new=True)
        assert d1.parent == root and d1.exists()
        explicit = root / "explicit"
        d2 = resolve_run_dir(root, explicit, new=True)  # run_dir은 run_root와 무관하게 그대로 쓰임(호출자가 경로를 줌)
        assert d2 == explicit and d2.exists()
        d3 = resolve_run_dir(root, None, new=False)
        assert d3 in (d1, d2)  # 가장 최근(사전식 정렬) 중 하나
        empty = Path(t) / "empty_root"
        try:
            resolve_run_dir(empty, None, new=False, label="x", rel_hint="output/eval/x")
            raise AssertionError("빈 폴더에서 new=False면 SystemExit이어야 함")
        except SystemExit as e:
            assert "[x] output/eval/x 아래 이전 run 없음" == str(e)
        assert lookup_run_dir(root, None) is None
        assert lookup_run_dir(root, "explicit") == d2
        assert lookup_run_dir(root, "no-such") is None
    fake_dir = Path("some") / "doc" / "dir"
    with COMMON.env(DOC_DIR=str(fake_dir)):
        assert doc_dir() == PROJ_ROOT / fake_dir  # 상대 경로는 저장소 루트 기준
    with COMMON.env(DOC_DIR=""):  # 빈 글자 = 정말 비움(None은 기본값이라 pipeline 이미지에서는 /data/docs)
        assert doc_dir(required=False) is None
        try:
            doc_dir()
            raise AssertionError("DOC_DIR 없으면 SystemExit이어야 함")
        except SystemExit as e:
            assert "ops.paths.source_docs_dir" in str(e)
    # resources/prompts/는 모든 이미지에 폴더째 있으므로 앱별 묶음도 이미지 구분 없이 확인
    assert resolve_agent_dir("page_transcribe") == RES_ROOT / "prompts" / "common" / "page_transcribe"
    assert resolve_agent_dir("nested_figure") == RES_ROOT / "prompts" / "pipeline" / "nested_figure"
    assert (RES_ROOT / "prompts" / "common" / "_common" / "tail.md").is_file() and CRITERIA_FILE.is_file()
    assert STACK_FILE.is_file() and (GLOSSARY_ROOT / "domain_terms.csv").is_file()
    if (PROJ_ROOT / "dev_tools").is_dir():  # 저장소 체크아웃에서만(이미지엔 dev_tools 없음)
        assert resolve_agent_dir("example_agentic") == PROJ_ROOT / "dev_tools" / "unit_test" / "fixtures" / "example_agentic"
    try:
        resolve_agent_dir("_no_such_agent_")
        raise AssertionError("없는 agent_id면 FileNotFoundError여야 함")
    except FileNotFoundError:
        pass
    print("common/core/paths self-check OK")

    # 원자적 쓰기: 임시 파일 안 남고, 덮어쓰기도 원자적
    with tempfile.TemporaryDirectory() as t:
        dst = Path(t) / "out.txt"
        atomic_write_text(dst, "hello")
        assert dst.read_text(encoding="utf-8") == "hello"
        assert not list(Path(t).glob("*.tmp"))  # 임시 파일이 안 남음
        atomic_write_text(dst, "world2")  # 덮어쓰기도 원자적으로
        assert dst.read_text(encoding="utf-8") == "world2"
        dstb = Path(t) / "out.bin"
        atomic_write_bytes(dstb, b"\x00\x01binary")
        assert dstb.read_bytes() == b"\x00\x01binary"
    print("common/core/paths atomic self-check OK")


def test_main():
    _demo()
