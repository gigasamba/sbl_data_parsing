"""common.config.setarg(명령 인자 `--set 이름=값` — D-032) 시험 — S9b(VS9 R-1)에 새로. env는 dict로만 넘김(os.environ 안 건드림)."""

import tempfile
from pathlib import Path

from common.config import setarg


def test_split():
    names, rest = setarg.split(
        ["parse", "--set", "PIPE_PROCS=2", "--set=PARSE_POST=a=b", "--src", "x", "--set", "PIPE_PROCS=3", "--set", "VLM_PAGE_MAX="]
    )
    assert rest == ["parse", "--src", "x"], rest
    assert names == {"PARSE_POST": "a=b", "PIPE_PROCS": "3", "VLM_PAGE_MAX": ""}, names  # 뒤 값이 이김·값 안 '='·빈 값
    for bad in (["--set"], ["--set", "NOEQ"], ["--set", "=1"]):
        try:
            setarg.split(bad)
            raise AssertionError(bad)
        except setarg.SetError:
            pass


def test_check():
    assert setarg.check({"PIPE_PROCS": "2"}) == []
    probs = " ".join(setarg.check({"NO_SUCH_NAME": "1", "RUN_ENV": "dev", "PG_PASSWORD": "zz-not-shown-zz"}))
    assert "NO_SUCH_NAME" in probs and "RUN_ENV" in probs and "비밀 칸" in probs, probs
    assert "zz-not-shown-zz" not in probs  # 안내에 값은 안 넣음(이름만)


def test_server_needs_file():  # VS9 R-1 — 서버에서 SETTINGS_FILE 없이 --set을 주면 base 없는 덮기 파일로 "설정 파일 필수" 관문을 지나가던 것
    for run in ("dev", "prd"):
        try:
            setarg.child({"PIPE_PROCS": "2"}, environ={"RUN_ENV": run})  # env 남김 — 시험: --set 이름 사전(child가 덮기 파일로 넘김)
            raise AssertionError(f"{run}: 설정 파일 없이 통과함")
        except setarg.SetError as e:
            assert "설정 파일" in str(e), e


def test_local_overlay():
    d = Path(tempfile.mkdtemp())
    base = d / "settings.yaml"
    base.write_text("common:\n  run_env: local\n", encoding="utf-8")
    env = setarg.child(
        {"PIPE_PROCS": "2"}, environ={"SETTINGS_FILE": str(base)}
    )  # env 남김 — 시험: --set 이름 사전(child가 덮기 파일로 넘김)
    over = Path(env["SETTINGS_FILE"])
    assert over != base and over.is_file(), env["SETTINGS_FILE"]
    text = over.read_text(encoding="utf-8")
    assert str(base) in text and "PIPE_PROCS" in text, text  # base: 원본 파일 + overrides: 바뀐 칸만
