#!/usr/bin/env python3
"""실행 기록 — pipeline(P) 전용 "다음 할 일" 등록(10-14 common.core.runlog에서 옮김 — run_all.py만 쓴다).
session()·note()·_write_entry() 등 공용 핵심(output/RUNLOG.md·runlog.jsonl 작성)은 common.core.runlog에 남아
있고, next_step()은 그 모듈의 _state(같은 세션의 "다음 할 일" 목록)를 그대로 공유해 덧붙인다."""

from common.core.runlog import _state


def next_step(cmd):
    _state["next"].append(str(cmd))
