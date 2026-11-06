"""컨테이너 시작 설정 — deploy/docker/entrypoint.sh가 앱 명령마다 python 한 번으로 부른다.
  ① --gate: RUN_ENV 관문(require_run_env — 없거나 모르는 값이면 종료 2, 서버(dev·prd)면 이 이미지 절을 끝까지 검증해 못 읽거나 틀리면 이유만 찍고 종료 2)
  ② 셸 칸: 이 셸이 쓰는 칸(env 이름 — DOC_DIR·DOC_DIR_PREPARED·PARSE_SOURCE·PG_HOST)을 설정에서 꺼내 `N='값'` 줄로(export 아님 — 셸 변수만,
     앱 env에 설정 이름이 새지 않게). 비밀 칸은 거부. 이 이미지 절에 없는 이름(mcp 이미지의 PARSE_SOURCE)은 건너뜀. env에 이미 있으면 내지 않음(사용자 env).
     값이 없으면 내지 않음(셸 기본값).
  ③ 라이브러리 env(settings.yaml ops.runtime.library_env — 허용 목록만): `export N='값'` 줄 — 사용자 env는 안 덮고, 이미지 ENV 값(빌드 때 기록한
     --image-env 파일 /app/docker/image_env.txt의 값과 같으면 이미지 값)은 덮는다(B-2와 같은 원칙 — settings.yaml > 이미지 기본값).
표준 출력 = eval할 export 줄만(값은 셸 따옴표 — 출력은 entrypoint가 eval만 하고 찍지 않음). 안내·오류는 표준 오류(값 없음).
사용: python -m common.config.boot [--gate] [--image-env 파일] <셸 칸 이름>...
"""

import argparse
import os
import shlex
import sys
from pathlib import Path

from common.config import settings as S
from common.core.console import utf8_stdout


def _image_env(path):
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            k, eq, v = line.partition("=")
            if eq:
                out[k] = v
    except OSError:
        pass
    return out


def lines(names, image_env=None, environ=None):
    environ = os.environ if environ is None else environ  # env 남김 — 내부 신호
    cls, _ = S.section_class(S.image_sections(environ))
    st = S._load_app(cls)
    emap = S.env_map(cls)
    fields = {p: f for p, f, _ in S.walk(cls)}
    out = []
    for name in names:
        p = emap.get(name)
        if p is None:
            continue  # 이 이미지 절에 없는 칸 — 셸 기본값
        if S.is_secret(fields[p]):
            raise SystemExit(f"[boot] 비밀 칸은 셸 칸으로 내지 않음: {name}")
        if name in environ:  # 사용자 env
            continue
        s = S.render(S._get(st, p), sep=S.list_sep(fields[p]))
        if s is not None:
            out.append(f"{name}={shlex.quote(s)}")  # 셸 변수만(export 아님)
    image_env = image_env or {}
    for name, value in (st.common.runtime.lib_env or {}).items():
        if name in environ and environ[name] != image_env.get(name):
            continue  # 사용자 env(이미지 값과 다름) — 그대로
        out.append(f"export {name}={shlex.quote(value)}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--image-env", default=S.IMAGE_PATHS["image_env"])  # 이미지 약속 경로 — 표는 settings.IMAGE_PATHS 한 곳
    ap.add_argument("names", nargs="*")
    a = ap.parse_args(argv)
    if a.gate:
        S.require_run_env("entrypoint")
    try:
        out = lines(a.names, _image_env(a.image_env))
    except S.SettingsError as e:
        print(f"[설정] entrypoint: {e}", file=sys.stderr)
        return 2
    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    utf8_stdout(errors=None)
    raise SystemExit(main())
