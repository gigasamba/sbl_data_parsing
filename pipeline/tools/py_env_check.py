#!/usr/bin/env python3
"""python 실행 환경 점검 — py_env_problem(want): 서버에 python 버전이 섞여 시스템 python으로 돌면
패키지 누락이 반복되므로 미리 잡는다(common.check.checker가 씀)."""

import os
import sys


def py_env_problem(want=(3, 12)):
    """서버에 python 3.13·3.12가 섞여 시스템 python으로 돌면 패키지 누락이 반복됨.
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
