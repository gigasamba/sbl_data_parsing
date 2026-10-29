"""pipeline.shared.runlog 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.shared.runlog`."""

from pipeline.shared.runlog import next_step


def selftest():
    import json
    import tempfile
    from pathlib import Path

    from common.core import runlog as R

    R.OUT = Path(tempfile.mkdtemp())  # S7c — common runlog는 OUT 모듈 상수만 읽음(RUNLOG_DIR env는 import 때 한 번) — env 안 씀
    with R.session("demo"):
        print("작업 출력 1줄")
        R.note("핵심: 성공 1")
        next_step("python pipeline.extract.run_all --phase 2")
    recs = [json.loads(x) for x in (R.OUT / "runlog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs[0]["next"] == ["python pipeline.extract.run_all --phase 2"], recs
    print("[selftest] next_step — common.core.runlog의 세션 상태(_state)에 '다음 할 일' 등록 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
