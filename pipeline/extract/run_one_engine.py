#!/usr/bin/env python3
"""문서 1건 × 엔진 1개.

run_all --isolate·--workers>1·PADDLE_PYTHON·세그폴트 복구가 자식 프로세스로 띄우는 실행 단위라 deploy/ 안에 둔다
(10-14 — dev_tools/pipeline_e2e_test에 있을 때 이미지(deploy/만 들어감)에서 'No module named tools'로 격리 경로가 깨졌음).
사용: python -m pipeline.extract.run_one_engine --engine <이름> [--profile tuned] [--fields baseline] <문서> <out.json>
엔진 목록: python -m pipeline.extract.run_one_engine --list
"""

import argparse
import json
import sys
import time
from pathlib import Path

from common.core import span as SP
from common.core.paths import atomic_write_text
from pipeline.extract.engines import registry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--engine")
    ap.add_argument("--profile", default="default", choices=["default", "tuned"])
    ap.add_argument(
        "--fields",
        default="normalized",
        choices=["normalized", "baseline"],
        help="normalized=fields.py 정규화 · baseline=fact의 number/unit만",
    )
    ap.add_argument(
        "--provenance",
        default=None,
        help="출처 블록 JSON(engine·engine_version·p0_key·params) — run_all이 줌, 결과에 넣어 한 번에 씀(fp-perf C4)",
    )
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    a = ap.parse_args()
    if a.list:
        for e, (s, m) in registry.engines().items():
            print(f"{e:18s} {s:15s} {' '.join(registry.formats(e))}" + ("  (미실측)" if e in m.UNVERIFIED else ""))
        return
    if not (a.engine and a.input and a.output):
        ap.error("--engine, 입력, 출력 필요")
    out = registry.run(a.engine, a.input, a.profile, a.fields)
    if a.provenance:
        stamp(out, json.loads(a.provenance))
    atomic_write_text(Path(a.output), json.dumps(out, ensure_ascii=False))  # 끊겨도 반쪽 파일 없음(옛 run_all._write_atomic 다시 쓰기 대신)
    print(SP.usage_line(), flush=True)  # op-01 — 이 프로세스의 cpu·최대 메모리 한 줄(부모 run_all의 extract.parse span이 읽음)


def stamp(out, prov):
    """엔진 결과에 provenance 블록(W8) — engine·engine_version·p0_key·params·created_at. 옛 run_all._stamp_provenance가 결과를 다시 읽고
    다시 쓰던 것을 쓰기 전에 한 번에(fp-perf C4)."""
    out["provenance"] = {**prov, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # 실제는 TextIOWrapper
    main()
