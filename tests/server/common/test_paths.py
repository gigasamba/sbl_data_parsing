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
    resolve_agent_dir,
)


def _demo():
    import tempfile

    from common.config.settings import COMMON

    assert DEPLOY_ROOT == (PROJ_ROOT if LOCAL_RUN else PROJ_ROOT / "deploy") and PKG_ROOT == DEPLOY_ROOT / "common"
    assert APP_ROOT == PROJ_ROOT
    env = child_env({"X_DEMO": "1"})
    assert env["X_DEMO"] == "1" and str(PKG_ROOT.parent) in env["PYTHONPATH"].split(os.pathsep)
    assert env is not os.environ  # env 남김 — 시험 · 원본 os.environ을 안 바꿈
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
    assert STACK_FILE.is_file() and (GLOSSARY_ROOT / "glossary.csv").is_file()
    if (PROJ_ROOT / "valid_env").is_dir():  # 저장소 체크아웃에서만(이미지엔 valid_env 없음)
        assert resolve_agent_dir("rag_qa") == PROJ_ROOT / "valid_env" / "answer_test" / "rag_qa"
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
