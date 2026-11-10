"""settings.yaml의 절을 KEY=VALUE 줄로 내보내기 — YAML을 직접 못 읽는 셸·compose·systemd용 다리.
  · env 이름으로 낸다(셸·compose 파일이 쓰는 ${X} 그대로).
  · 비밀 칸은 내보내지 않는다 — 컨테이너 안 앱이 붙인 설정 파일에서 직접 읽는다. YAML에 적은 값만 낸다(기본값은 스크립트·compose 쪽 기본값).
  · --format sh(호스트 스크립트 — deploy/host/scripts/load_settings.sh의 load_settings): `export KEY='VALUE'`(bash 3.2·4·5 — eval)
  · --format env(기본 — 사람이 compose `--env-file <(…)`로 줄 때): `KEY=VALUE` — compose가 env 파일 값의 `$`를 다시 치환하므로 값에 `$`가
    있으면 거부한다(오류에는 이름만). 셸 env로 넘기는 sh 꼴은 다시 치환되지 않는다.
사용: python -m common.config.export --section pipeline.host [--section common.host] [--section mcp.server.port] [--file settings.yaml] [--format sh]
      호스트 절(common.host·pipeline.host·pipeline.host.nightly·common.dev.docker)이 주 용도. 앱 칸도 낼 수 있음(비밀 빼고 —
      compose가 앱 칸을 덮는 MCP_HOST·TRIGGER_HOST 등). pipeline·mcp 절을 한 번에 줘도 된다(앱마다 읽어 이름 겹침 없이 합침).
"""

import argparse
import sys

from common.config import layout as L
from common.config import settings as S
from common.core.console import utf8_stdout


def lines(settings, sections, fmt="env", seen=None):
    out, seen = [], set() if seen is None else seen
    for sec in sections:
        # 칸마다 호스트·앱을 가리지 않고 고른 절(또는 칸) 아래 전부 — 잎 칸 이름이 host인 앱 칸(mcp.server.host·pipeline.service.trigger.host)도
        # 그 칸 하나로 고를 수 있게
        for name, value, _ in S.env_items(settings, section=sec, hosts=None, secrets=False):
            if name in seen:
                continue
            seen.add(name)
            if "\n" in value:
                raise S.SettingsError(f"{name}: 여러 줄 값은 env 줄로 낼 수 없음")
            if fmt == "sh":
                out.append(f"export {name}='" + value.replace("'", "'\\''") + "'")
            else:
                if "$" in value:
                    raise S.SettingsError(
                        f"{name}: 값에 $가 있어 compose env 파일 줄로 낼 수 없음(compose가 다시 치환) — --format sh로 셸 env에"
                    )
                out.append(f"{name}={value}")
    return out


def add_args(ap, *, file_default=None):
    """export 인자 — 이 명령과 앱 확인 명령(`python -m pipeline.config export …`, show.py)이 함께 씀. file_default=argparse.SUPPRESS면
    하위 명령의 --file이 위 명령의 --file 값을 지우지 않는다."""
    ap.add_argument("--section", action="append", required=True)
    ap.add_argument("--file", default=file_default, help="설정 파일(없으면 SETTINGS_FILE·RUN_ENV 규칙)")
    ap.add_argument("--format", choices=("env", "sh"), default="env")
    return ap


def check_sections(ap, sections, tops_ok, one_app=True):
    tops = {s.split(".", 1)[0] for s in sections}
    if not tops <= set(tops_ok):
        ap.error(f"절 이름은 {'·'.join(tops_ok)}로 시작")
    if one_app and {"pipeline", "mcp"} <= tops:
        ap.error("pipeline·mcp 절은 한 번에 하나씩")
    return tops


def run(cls, a, tag="export"):
    try:
        st = S.load(cls, file=a.file)
        for line in lines(st, a.section, a.format):
            print(line)
    except S.SettingsError as e:
        print(f"[{tag}] {e}", file=sys.stderr)
        return 2
    return 0


def _requested(file, sections):
    """설정 파일을 한 번 읽어 고른 절(칸)과 common.run_env만 남긴 사전 — 고르지 않은 칸은 검증하지 않는다(mcp 절의 오타가
    pipeline 호스트 스크립트(nightly_batch.sh·새벽 배치)를 멈추지 않게). 파일 자리는 load()와 같은 규칙(SETTINGS_FILE·RUN_ENV)."""
    import os

    run = os.environ.get("RUN_ENV") or None  # env 남김 — RUN_ENV 신호
    path = S.Path(file) if file else S.find_file(os.environ, run if run in S.RUN_ENVS else None)  # env 남김 — 설정 파일 자리 신호
    full, over = S.read_settings(path) if path else ({}, {})  # 덮기 파일(base·overrides)도
    doc = {}
    for sec in [*sections, "common.run_env"]:
        v = S._peek(full, sec)
        if v is not None:
            L.set_path(doc, sec, v)
    return doc, path, over


def main(argv=None):
    ap = add_args(argparse.ArgumentParser(description=__doc__.split("\n", 1)[0]))
    a = ap.parse_args(argv)
    tops = check_sections(ap, a.section, S.SECTIONS, one_app=False)
    apps = [t for t in ("pipeline", "mcp") if t in tops]
    classes = S.app_classes()
    missing = [t for t in apps if t not in classes]
    if not classes or missing:
        print(f"[export] 이 코드에 {'·'.join(missing) or '앱'} 설정 모델이 없음", file=sys.stderr)
        return 2
    out, seen = [], set()
    try:
        doc, source, over = _requested(a.file, a.section)
        for app in apps or [next(iter(classes))]:  # common 절만이면 있는 앱 아무거나(common 칸은 같음)
            st = S.load(classes[app], use_file=False, require_file=False, _read=(doc, over))
            out += lines(st, [s for s in a.section if s.split(".", 1)[0] in ("common", app)], a.format, seen)
    except S.SettingsError as e:
        print(f"[export] {e}", file=sys.stderr)
        return 2
    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    utf8_stdout(errors=None)
    raise SystemExit(main())
