#!/usr/bin/env python3
"""실행 자원 — pipeline(S) 전용 점검(10-14 common.core.resources에서 옮김 — common.check.checker env(TOOL_IMAGE
"structure")·dev_tools/pipeline_e2e_test/e2e.py만 쓴다). CPU·메모리 감지·plan() 등 공용 핵심은 common.core.resources에
그대로 남아 있다.

py_env_problem(want) — SI29, 서버에 python 버전이 섞여 시스템 python으로 돌면 패키지 누락이 반복됨을 미리 잡는다."""

import os
import sys


def py_env_problem(want=(3, 12)):
    """SI29 — 서버에 python 3.13·3.12가 섞여 시스템 python으로 돌면 패키지 누락이 반복됨.
    문제 없으면 None, 있으면 한 줄 설명. 컨테이너(/.dockerenv·podman /run/.containerenv)는 venv 없이도 정상."""
    ver = sys.version_info[:2]
    in_venv = sys.prefix != sys.base_prefix
    in_box = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    if ver == tuple(want) and (in_venv or in_box):
        return None
    return (
        f"python {sys.version.split()[0]}({sys.executable}) · venv {'안' if in_venv else '밖'}"
        f" — {want[0]}.{want[1]} venv 또는 이미지 안에서 돌려야 함"
    )
