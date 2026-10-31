"""PC 시험(pytest — S9, D-018): `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/`(서버 반입 시험 + 일반 시험) · `pytest tests/general`(일반만).
시험 파일(test_*.py)은 파일마다 자식 프로세스 `python -m tests.runner <시험 모듈>`로 돈다 — 이미지 명령 selftest와 같은 길·같은 env
(pipeline.cli.case_env: 유료 호출 잠금·모델 주소 비움). 옛 자기 점검은 모듈마다 따로 프로세스였고 설정·env·캐시를 바꾸므로 한 프로세스에 섞지
않는다. 파일 안에 `INPROCESS = True` 줄이 있는 시험만 pytest가 그대로 모은다(함수마다 결과 — 상태를 바꾸지 않는 시험)."""

import functools
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# 알려진 FAIL(옮기기 전 모듈 자기 점검에서도 같은 단언으로 실패하던 것) — 실패하면 xfail, 통과하면 PASS + 경고 요약의 "XPASS …"로 알림(목록에서 지울 수 있음).
#   판정은 파일 단위(자식 프로세스 하나) — 알려진 FAIL 파일 안의 새 실패도 xfail로 가려진다(옛 모듈 단위 판정·이미지 selftest_gate와 같음, VS9 R-4).
#   서버 반입 시험은 반입 판정 목록 deploy/release/known_fail.txt를 그대로 읽는다. 일반 시험은 여기(이유와 함께 — 새 줄은 리팩토링 전부터 있던 것만).
GENERAL_KNOWN_FAIL = {
    "tests.general.pipeline.test_pub_registry": "PG에서 문서 대장 upsert(여러 줄 INSERT OR REPLACE)가 번역되지 않음(pre-refactor 서버 코드부터 — refactor.md C-54 ①, 사용자 10-28: 이번 판에서 안 고침)",
}


@functools.cache  # 시험마다 부름(통과해도 — XPASS 알림) → 파일은 한 번만 읽음(S9b 리뷰)
def _known_fail():
    f = ROOT / "deploy" / "release" / "known_fail.txt"
    names = {ln.split("#")[0].strip() for ln in f.read_text(encoding="utf-8").splitlines()} - {""}
    return {n: "deploy/release/known_fail.txt" for n in names} | GENERAL_KNOWN_FAIL


def _inprocess(path):
    return "\nINPROCESS = True" in Path(path).read_text(encoding="utf-8")


def pytest_pycollect_makemodule(module_path, parent):
    if Path(module_path).name.startswith("test_") and not _inprocess(module_path):
        return RunnerFile.from_parent(parent, path=Path(module_path))
    return None


class RunnerFile(pytest.File):
    def collect(self):
        mod = ".".join(self.path.resolve().relative_to(ROOT).with_suffix("").parts)
        yield RunnerItem.from_parent(self, name=mod)


class RunnerFailed(Exception):
    pass


class RunnerItem(pytest.Item):
    def runtest(self):
        from pipeline.cli import ROOT as CWD  # 이미지 selftest와 같은 작업 폴더·env
        from pipeline.cli import case_env

        r = subprocess.run(
            [sys.executable, "-m", "tests.runner", self.name],
            cwd=CWD,
            env=case_env(self.name),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        reason = _known_fail().get(self.name)
        if r.returncode != 0:
            if reason:
                pytest.xfail(f"알려진 FAIL — {reason}")
            raise RunnerFailed((r.stdout + r.stderr)[-4000:])
        if (
            reason
        ):  # VS9 R-4 — 알려진 FAIL이 통과: PASS로 두되 경고 요약에 알림(목록에서 지울 수 있음 — 이미지 selftest_gate.sh와 같은 신호)
            warnings.warn(
                pytest.PytestWarning(f"XPASS {self.name} — 알려진 FAIL 목록({reason})에 있는데 통과함: 목록에서 지울 수 있음"), stacklevel=1
            )

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, RunnerFailed):
            return str(excinfo.value)
        return super().repr_failure(excinfo, style)

    def reportinfo(self):
        return self.path, 0, self.name
