#!/usr/bin/env python3
"""문서 1건 × 엔진 1개.

run_all --isolate·--workers>1·PADDLE_PYTHON·세그폴트 복구가 자식 프로세스로 띄우는 실행 단위라 deploy/ 안에 둔다
(10-14 — dev_tools/pipeline_e2e_test에 있을 때 이미지(deploy/만 들어감)에서 'No module named tools'로 격리 경로가 깨졌음).
사용: python -m pipeline.extract.parse_one --engine <이름> [--profile tuned] [--fields baseline] <문서> <out.json>
엔진 목록: python -m pipeline.extract.parse_one --list
"""

import argparse
import json
import sys
from pathlib import Path

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
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    a = ap.parse_args()
    if a.list:
        for e, (s, m) in registry.engines().items():
            print(f"{e:18s} {s:15s} {' '.join(m.FORMATS[e])}" + ("  (미실측)" if e in m.UNVERIFIED else ""))
        return
    if not (a.engine and a.input and a.output):
        ap.error("--engine, 입력, 출력 필요")
    out = registry.run(a.engine, a.input, a.profile, a.fields)
    Path(a.output).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # 실제는 TextIOWrapper
    main()
