"""common.core.runlog 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.runlog --selftest`."""

import json
from pathlib import Path

import common.core.runlog as M
from common.core.runlog import ROOT, _state, note, session


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래(`if a.selftest:` 몸통)
    import tempfile

    M.OUT = Path(tempfile.mkdtemp())  # S7b — OUT은 import 때 정해진 모듈 상수라 env를 거치지 않고 바로 바꿈
    with session("demo"):
        print("작업 출력 1줄")
        note("핵심: 성공 3 · 실패 0")
        _state["next"].append(
            "python cli/demo.py --next"
        )  # next_step()과 같은 동작(그 함수는 pipeline.shared.runlog로 옮김, 10-14 — P만 씀)
    try:
        with session("demo_fail"):
            raise ValueError("일부러")
    except ValueError:
        pass
    recs = [json.loads(x) for x in (M.OUT / "runlog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs[0]["status"] == "성공" and recs[0]["notes"] == ["핵심: 성공 3 · 실패 0"] and recs[1]["status"] == "오류", recs
    lp = Path(recs[0]["log"])
    assert "작업 출력 1줄" in (lp if lp.is_absolute() else ROOT / lp).read_text(encoding="utf-8")
    assert "## " in (M.OUT / "RUNLOG.md").read_text(encoding="utf-8")
    print("runlog self-check OK")
