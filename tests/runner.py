"""시험 실행기(S9 — D-018): 시험 파일 하나(모듈 이름)의 test_* 함수를 정의 순서대로 부르고 함수마다 PASS/FAIL을 찍는다. 하나라도 실패하면
종료 코드 1. unittest.SkipTest를 던진 시험은 SKIP 줄(FAIL 아님). pytest가 없는 이미지 안(이미지 명령 selftest — pipeline.cli selftest가 파일마다 자식 프로세스로)과 PC pytest(tests/conftest.py가
파일마다 이 실행기를 자식 프로세스로)가 같은 길로 돈다 — 시험 파일은 pytest 꼴(맨 함수 test_* + assert, 픽스처 없음).
  python -m tests.runner tests.server.pipeline.test_overlay"""

import importlib
import inspect
import sys
import traceback
import unittest

from common.core.console import utf8_stdout


def tests_of(mod):
    """(이름, 함수) — 모듈에 정의된 순서(이름이 test_로 시작하는 함수)."""
    return [(n, f) for n, f in vars(mod).items() if n.startswith("test_") and inspect.isfunction(f)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("사용: python -m tests.runner <시험 모듈>(예 tests.server.pipeline.test_overlay)", file=sys.stderr)
        return 2
    utf8_stdout()
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # 실패 출력(traceback)도 한글 — utf8_stdout은 stdout만
    mod = importlib.import_module(argv[0])
    found = tests_of(mod)
    if not found:
        print(f"[시험] FAIL {argv[0]} — test_ 함수가 없음")
        return 1
    fails = 0
    for name, fn in found:
        ok = True
        try:
            fn()
        except (
            unittest.SkipTest
        ) as e:  # 이 환경에서 돌리지 않는 사례(운영 서버의 DB 쓰기 — tests/server/common/pgcase.py) — FAIL 아님, 요약에 SKIP으로
            print(f"[시험] SKIP {argv[0]}.{name} — {e}", flush=True)
            continue
        except SystemExit as e:  # 옛 자기 점검이 sys.exit(0)·raise SystemExit(selftest())로 끝나는 꼴 — 0·None만 통과
            if e.code not in (0, None):
                ok = False
                print(f"[시험] {name}: 종료 코드 {e.code}", flush=True)
        except Exception:  # 시험 하나의 실패는 다음 시험을 막지 않음(KeyboardInterrupt는 그대로)
            ok = False
            traceback.print_exc()
        fails += not ok
        print(f"[시험] {'PASS' if ok else 'FAIL'} {argv[0]}.{name}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
