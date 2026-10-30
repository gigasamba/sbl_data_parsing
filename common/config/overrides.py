"""덮기 파일 만들기 — settings.yaml 몇 칸만 바꿔 한 번 돌릴 때(옛 `export X=…`·`X=값 python …` 자리 — S7e2, 사용자 10-28). **PC 전용.**
사용: SETTINGS_FILE=$(python -m common.config.overrides PIPE_OUT_ROOT=$PWD/output/x PG_CREATE_EXTENSION=1) python -m pipeline.cli parse …
  · 서버(RUN_ENV — env 또는 원본 설정 파일의 common.run_env — 가 dev·prd)에서는 만들지 않고 안내 뒤 종료 2: 서버는 바꿀 값이 있으면
    settings.yaml을 직접 고친다(사용자 10-28 — VS7e2 B-2: compose는 덮기 파일만 붙여 base가 컨테이너에 없음, refactor.md C-47 ⑥). 코드가 프로세스
    안에서 자식에 값을 넘기는 덮기 파일(settings.put·child_env — 컨테이너 안 /tmp, base는 컨테이너 안 경로)은 이 막기와 무관하게 그대로 쓴다.
  · 이름은 설정 칸의 옛 env 이름(sample의 env=), 값은 옛 env 글자 꼴(켜기 1·0). `X=`(빈 값)은 빈 글자, `X`(= 없음)는 그 칸 비움(기본값).
  · 원본은 --base(없으면 지금 SETTINGS_FILE·저장소 루트 settings.yaml)를 가리킬 뿐 복사하지 않는다(base·overrides만 든 작은 yaml —
    common.config.settings.overlay_file). 권한 600, OS 임시 폴더(지우지 않음 — OS가 정리). 표준 출력에는 만든 경로만(값은 찍지 않음).
  · 칸이 없는 이름은 거부(이름만 찍고 종료 2).
"""

import argparse
import sys

from common.config import settings as S
from common.core.console import utf8_stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("pairs", nargs="+", metavar="이름=값")
    ap.add_argument("--base", help="원본 설정 파일(없으면 SETTINGS_FILE·RUN_ENV 규칙)")
    a = ap.parse_args(argv)
    names = {}
    for pair in a.pairs:
        name, eq, value = pair.partition("=")
        names[name] = value if eq else None
    try:
        run = server_run_env(a.base)
    except S.SettingsError as e:
        print(f"[overrides] {e}", file=sys.stderr)
        return 2
    if run is not None:
        print(
            f"[overrides] 서버(RUN_ENV={run})에서는 덮기 파일을 만들지 않음 — 바꿀 값은 settings.yaml을 직접 고친다(PC 전용 도구 — "
            "사용자 10-28, refactor.md C-47 ⑥ · docs/operations/env-guide.md)",
            file=sys.stderr,
        )
        return 2
    try:
        S._check_names(names)
    except KeyError as e:
        print(f"[overrides] {e.args[0]}", file=sys.stderr)
        return 2
    print(S.overlay_file(names, base=a.base))
    return 0


def server_run_env(base=None, environ=None):
    """서버(dev·prd)면 그 글자, 아니면 None — settings.resolve_run_env와 같은 규칙(env RUN_ENV, 없으면 원본 설정 파일 --base·SETTINGS_FILE·
    로컬 파일의 common.run_env). 모르는 글자는 env·파일 어느 쪽이든 SettingsError(만들지 않음 — 가드는 서버로 봄)."""
    run = S.resolve_run_env(environ, file=base)
    return run if run in S.SERVER_ENVS else None


if __name__ == "__main__":
    utf8_stdout(errors=None)
    raise SystemExit(main())
