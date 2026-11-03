"""앱 설정 확인 명령 — `python -m pipeline.config`·`python -m mcp_server.config`가 부른다(S7a). common 절만: `python -m common.config.show`
(0.2.0 — 옛 `python -m common.config.settings` 입구를 settings.py 밖으로 옮김: settings.py가 모든 레이어의 code_fp 의존이라 이 파일·export가 같이 묶이지 않게, pl-46).
[--file 경로]                         설정을 읽어 요약 — 파일·RUN_ENV·절마다 채운 칸 수, 채운 비밀 칸은 이름만
[--file 경로] export --section … [--format env|sh]   그 절을 KEY=VALUE로(common.config.export와 같음 — 이 앱 모델로)
--file: 읽을 파일(없으면 SETTINGS_FILE·RUN_ENV 규칙) — export 앞·뒤 어디에 줘도 됨
"""

import argparse
import sys
from collections import Counter

from common.config import export as E
from common.config import settings as S


def summary(st):
    out = [f"설정 파일: {st._source or '(없음 — 기본값만)'} · RUN_ENV: {st.common.run_env or '(없음)'}"]
    filled, secrets = Counter(), []
    for path, f, _ in S.walk(type(st)):
        if S._is_set(st, path):
            filled[".".join(path.split(".")[:2])] += 1
            if S.is_secret(f):
                secrets.append(path)
    for sec, n in sorted(filled.items()):
        out.append(f"  {sec}: {n}칸")
    if secrets:
        out.append("  비밀 칸(값 가림): " + " ".join(secrets))
    return out


def _parser(prog):
    ap = argparse.ArgumentParser(prog=prog, description="앱 설정 확인 — 인자 없으면 요약(비밀 가림)")
    ap.add_argument("--file", help="설정 파일(없으면 SETTINGS_FILE·RUN_ENV 규칙)")
    sub = ap.add_subparsers(dest="cmd")
    E.add_args(sub.add_parser("export", help="절을 KEY=VALUE로(비밀 빼고)"), file_default=argparse.SUPPRESS)
    return ap, sub.choices["export"]


def main(app_cls, argv, prog=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap, ex = _parser(prog)
    a = ap.parse_args(argv)  # 인자 오류는 argparse가 안내 + 종료 코드 2(VS7a R-7 — 전에는 IndexError)
    if a.cmd == "export":
        E.check_sections(ex, a.section, [n for n in S.SECTIONS if n in app_cls.model_fields])
        return E.run(app_cls, a, tag="설정")
    try:
        print("\n".join(summary(S.load(app_cls, file=a.file))))
        return 0
    except S.SettingsError as e:
        print(f"[설정] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(S._TApp, sys.argv[1:], prog="python -m common.config.show"))
