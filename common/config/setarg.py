"""명령 인자 `--set 이름=값`(여러 번) — 한 번 실행에만 설정 칸 몇 개를 바꿔 돌린다. 서버에서도 쓴다(S9 Step A — VS8b U-1, 사용자 10-28).
옛 `X=값 python -m …`·`docker exec … bash -c 'X=값 python …'`(S7e2부터 env의 옛 이름은 읽지 않아 효과 없음) 자리다. 덮기 파일 도구
`common.config.overrides`는 그대로 PC 전용이다.

  python -m pipeline.cli --set PIPE_OUT_ROOT=/app/output/docflow/7 --set PARSE_POST=supsub,charts parse --source …

  · 이름은 설정 칸의 옛 env 이름(settings.sample.yaml의 env=), 값은 옛 env 글자 꼴(켜기 1·0). `X=`(빈 값)는 빈 글자(읽기 규칙대로 기본값).
    같은 이름이 여러 번 나오면 뒤 값이 이긴다(옛 bash `A=1 … A=2`와 같음). 인자 자리는 어디든 된다(하위 명령 앞뒤).
  · 모르는 이름·호스트 칸(compose·셸 값)·비밀 칸은 모든 환경에서 거부한다(이름만 찍고 종료 2). 비밀 칸을 막는 이유: 명령 줄은 ps·로그·
    진행 기록에 남는다 — 비밀은 settings.yaml에만.
  · 값 형식 오류는 덮기 파일과 같은 규칙: 서버(dev·prd)는 거부(종료 2 — 칸 이름만), local은 경고 뒤 그 칸만 기본값.
  · 적용: settings.child_env로 덮기 파일(지금 설정 파일을 base로 — 비밀 복사 없음)을 만들고 같은 모듈을 새 프로세스로 다시 띄운다(import 때
    읽는 값까지 새 값으로 — 그 뒤 자식 프로세스도 SETTINGS_FILE로 같은 값을 받음). 엔진·인계 칸은 env에도(영구 다리 — put과 같음).
쓰는 법: 진입 모듈의 `if __name__ == "__main__":` 첫 줄에서 `setarg.apply()`. `--set`이 없으면 아무것도 안 한다."""

import os
import subprocess
import sys

from common.config import settings as S

FLAG = "--set"


class SetError(ValueError):
    """--set 인자가 틀림 — 이름만 든 안내(값은 넣지 않음)."""


def split(argv):
    """argv → ({이름: 값}, 남은 argv). `--set A=1`·`--set=A=1` 둘 다. 뒤 값이 이김."""
    names, rest, i = {}, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == FLAG:
            if i + 1 >= len(argv):
                raise SetError(f"{FLAG} 뒤에 이름=값이 없음")
            pair, i = argv[i + 1], i + 2
        elif arg.startswith(FLAG + "="):
            pair, i = arg[len(FLAG) + 1 :], i + 1
        else:
            rest.append(arg)
            i += 1
            continue
        name, eq, value = pair.partition("=")
        if not eq or not name:
            raise SetError(f"{FLAG} {name or '?'} — 이름=값 꼴이어야 함")
        names.pop(name, None)  # 뒤 값이 이기고 순서도 뒤로
        names[name] = value
    return names, rest


def _fields():
    """{옛 env 이름: (칸 경로, 비밀 여부)} — common + 이 이미지에 있는 앱(호스트 칸 포함 — 거부 안내용)."""
    out = {}
    for cls in (S.CommonAppSettings, *S.app_classes().values()):
        for path, field, _ in S.walk(cls):
            name = S.env_name(field)
            if name and (
                name not in out or S.is_host(out[name][0])
            ):  # 같은 이름이 호스트 칸·앱 칸 둘 다면 앱 칸(GOLD_DIR·RAG_OUT — 리뷰 S9)
                out[name] = (path, S.is_secret(field))
    return out


def check(names):
    """거부할 이름 안내 목록(빈 목록 = 통과) — 모르는 이름·호스트 칸·비밀 칸. 값은 넣지 않는다."""
    fields, probs = _fields(), []
    for name in names:
        path, secret = fields.get(name, (None, False))
        if path is None or name == "RUN_ENV":
            probs.append(
                f"{name}: 설정 칸이 없는 이름(settings.sample.yaml의 env= 이름)"
                if name != "RUN_ENV"
                else "RUN_ENV: 실행 환경은 --set으로 바꾸지 않음(env RUN_ENV·settings.yaml common.run_env)"
            )
        elif S.is_host(path):
            probs.append(f"{name}: 호스트 칸({path}) — 컨테이너 안 앱이 읽지 않음(settings.yaml·셸 env)")
        elif secret:
            probs.append(f"{name}: 비밀 칸({path}) — 명령 줄은 ps·로그에 남아 --set으로 받지 않음(settings.yaml에)")
    return probs


def child(names, environ=None):
    """--set 값을 덮은 자식 env — 서버면 형식까지 검사해 SetError(칸 이름만), local은 덮기 파일 규칙대로 경고 뒤 그 칸만 기본값."""
    probs = check(names)
    if probs:
        raise SetError("; ".join(probs))
    base = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호·설정 파일 자리 신호
    try:
        run0 = S.resolve_run_env(base)
    except S.SettingsError as e:
        raise SetError(str(e)) from None
    if run0 in S.SERVER_ENVS and S.find_file(base, run0) is None:  # VS9 R-1 — base 없는 덮기 파일이 "설정 파일 필수" 관문을 지나가지 않게
        raise SetError(f"서버(RUN_ENV={run0})는 설정 파일이 있어야 함(SETTINGS_FILE) — --set은 그 파일 위에 덮는다")
    env = S.child_env(environ, **names)
    try:
        run = S.resolve_run_env(env)
    except S.SettingsError as e:
        raise SetError(str(e)) from None
    if run in S.SERVER_ENVS:
        try:
            S.load(S.section_class(S.image_sections(env))[0], environ=env)
        except S.SettingsError as e:
            raise SetError(f"서버(RUN_ENV={run}) — --set 값을 읽지 못함: {e}") from None
    return env


_OWNED = "SETARG_OWNS_SETTINGS"  # 내부 신호 env 이름(설정 칸 아님 — pl-27)


def apply(argv=None, module=None):
    """__main__ 첫 줄 — argv(기본 sys.argv[1:])에 --set이 있으면 덮기 파일 env로 같은 모듈을 다시 띄우고 그 종료 코드로 끝낸다.
    없으면 그대로 돌아온다. 틀리면 안내(이름만) 뒤 종료 2."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if os.environ.pop(_OWNED, None):  # env 남김 — 내부 신호: execve로 다시 뜬 이 프로세스가 --set 덮기 파일을 맡음(pl-27 — 끝날 때 지움)
        from common.core import exitclean

        exitclean.remove_at_exit(os.environ["SETTINGS_FILE"])  # env 남김 — 설정 파일 자리 신호
    if not any(a == FLAG or a.startswith(FLAG + "=") for a in argv):
        return
    try:
        names, rest = split(argv)
        env = child(names)
    except SetError as e:
        print(f"[설정] {FLAG}: {e}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    if module is None:
        spec = getattr(sys.modules.get("__main__"), "__spec__", None)
        module = spec.name if spec is not None else None
    cmd = [sys.executable, "-m", module, *rest] if module else [sys.executable, sys.argv[0], *rest]
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "posix":
        env[_OWNED] = "1"  # env 남김 — 내부 신호: exec 뒤에는 atexit가 안 돌아 새 프로세스가 덮기 파일을 맡음(pl-27)
        os.execve(sys.executable, cmd, env)  # 같은 PID — docker exec·고아 정리(run_docs)가 보는 프로세스 그대로
    raise SystemExit(subprocess.call(cmd, env=env))  # Windows(PC) — exec가 새 프로세스라 기다려 종료 코드를 넘김
