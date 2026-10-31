"""common.config.show의 app_selftest — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 시험 도우미(test_ 함수 없음 — pipeline.config·mcp_server.config 시험이 `from tests.server.common.appcheck import app_selftest`로 부름). 옛 부르는 곳: 두 config 모듈의 자기 점검."""

from common.config import export as E
from common.config import layout as L
from common.config import settings as S
from common.config.layout import to_file
from common.config.show import main, summary


def app_selftest(app_cls, top):
    """앱 config 모듈 selftest 공용 — sample이 이 앱 모델로 검증되는지·칸 표·export·비밀 가림."""
    import tempfile
    from pathlib import Path

    from common.config import sample

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    rows = list(S.walk(app_cls))
    check(f"{top}: 칸 {len(rows)}개 — 모두 옛 env 이름·설명 있음", all(S.env_name(f) and f.description for _, f, _ in rows))
    envs = [S.env_name(f) for p, f, _ in rows if not S.is_host(p)]
    check(f"{top}: 앱 칸의 옛 env 이름 겹침 없음(호스트 절 빼고)", len(envs) == len(set(envs)))
    check(f"{top}: 읽는 절은 common + {top}뿐", set(app_cls.model_fields) == {"common", top})
    if sample.OUT.is_file():
        st = S.load(app_cls, file=sample.OUT, environ={}, strict=False)  # sample의 run_env는 빈 칸
        check(
            f"{top}: settings.sample.yaml이 이 모델로 검증됨(적힌 값 = 코드 기본값 — op-05)",
            all(S._get(st, p) == f.get_default(call_default_factory=True) for p, f, _ in rows if S._is_set(st, p)),
        )
    secret = "tok-" + "y" * 10
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "s.yaml"
        host_leaf = next(p for p, fi, _ in rows if p.startswith(top + ".host.") and S.type_label(fi.annotation) == "str")
        sec_leaf = next(p for p, fi, _ in rows if p.startswith(top + ".") and S.is_secret(fi))
        doc = {}
        L.set_path(doc, host_leaf, "v1")
        L.set_path(doc, sec_leaf, secret)
        L.set_path(doc, "common.run_env", "dev")
        import yaml

        f.write_text(yaml.safe_dump(to_file(doc)), encoding="utf-8")
        st = S.load(app_cls, file=f, environ={})
        out = E.lines(st, [f"{top}.host"]) + E.lines(st, [top])
        env_host = S.env_name(dict((p, fi) for p, fi, _ in rows)[host_leaf])
        check(f"{top}: export — 호스트 절 칸을 KEY=VALUE로", f"{env_host}=v1" in out)
        check(f"{top}: export — 비밀 칸은 내보내지 않음", not any(secret in line for line in out))
        check(f"{top}: 요약에 비밀 값 없음(이름만)", secret not in "\n".join(summary(st)) and sec_leaf in "\n".join(summary(st)))
        import contextlib
        import io

        codes = []
        other = "mcp" if top == "pipeline" else "pipeline"
        for argv in (
            ["--file"],
            ["export", "--file", str(f)],
            ["--file", str(f), "export", "--section", f"{top}.host", "--format", "sh"],
            ["export", "--section", f"{other}.host", "--file", str(f)],
        ):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    codes.append(main(app_cls, argv))
                except SystemExit as e:
                    codes.append(e.code)
        check(
            f"{top}: 확인 명령 인자 — 값 없는 --file·--section 없는 export·다른 앱 절은 안내 + rc 2(IndexError 아님), --file은 export 앞뒤 모두",
            codes == [2, 2, 0, 2],
        )
        # S7e2 — 다리 없음: 앱 설정 모듈을 common보다 먼저 import해도 설정 파일 값을 읽고, 앱 칸은 env로 나가지 않음(영구 다리는 엔진·인계 칸만) — 새 프로세스로
        import subprocess
        import sys

        app_leaf = next(
            p
            for p, fi, _ in rows
            if p.startswith(top + ".")
            and not S.is_host(p)
            and S.type_label(fi.annotation) == "str"
            and not S.is_secret(fi)
            and not S._extra(fi, "pinned")
        )
        env_app = S.env_name(dict((p, fi) for p, fi, _ in rows)[app_leaf])
        g = Path(td) / "app.yaml"
        doc = {}
        L.set_path(doc, app_leaf, "file-v")
        L.set_path(doc, "common.run_env", "local")
        g.write_text(yaml.safe_dump(to_file(doc)), encoding="utf-8")
        mod = {"pipeline": "pipeline.config", "mcp": "mcp_server.config"}[top]
        env = {k: v for k, v in __import__("os").environ.items() if k not in (env_app, "RUN_ENV")}
        env["SETTINGS_FILE"] = str(g)
        probe = f"import os, {mod} as m; from common.config import settings as S; print(S._get(m.SETTINGS.get(), '{app_leaf}'), os.environ.get('{env_app}'))"
        r = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, encoding="utf-8")
        check(
            f"{top}: {mod}를 먼저 import해도 설정 파일 값({app_leaf})을 읽고 앱 칸({env_app})은 env로 안 나감(다리 없음 — S7e2)",
            r.returncode == 0 and r.stdout.split() == ["file-v", "None"],
        )
    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)
