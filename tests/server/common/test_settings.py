"""common.config.settings 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.config.settings --selftest`."""

import contextlib
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from common.config.layout import to_file
from common.config.settings import (
    COMMON,
    IMAGE_DEFAULTS,
    IN_IMAGE,
    REPO_ROOT,
    SECTIONS,
    SERVER_ENVS,
    Cache,
    CommonAppSettings,
    CommonConnectionsPg,
    CommonRuntime,
    CommonSettings,
    CsvList,
    F,
    Port,
    Section,
    SettingsError,
    WordList,
    _get,
    _is_set,
    _peek,
    _pinned,
    _raw_dumper,
    _TApp,
    _warned,
    _yaml_loader,
    app_classes,
    cfg,
    checked,
    child_env,
    env_items,
    env_name,
    external_models_allowed,
    given,
    guard_run_env,
    image_sections,
    is_host,
    list_sep,
    load,
    overlay_file,
    overridden,
    pin_env,
    put,
    read_yaml,
    render,
    require_run_env,
    resolve_run_env,
    section_class,
    walk,
)


def _new(text):
    """옛 배치(모델 경로) YAML 글자 → 새 배치(op-08 ② — layout.to_file) 글자. 쓴 글자·꼴(yes·0123·1.10)은 그대로(migrate._raw)."""
    import yaml

    from common.config import migrate

    doc = yaml.load(text, Loader=_yaml_loader())
    return yaml.dump(to_file(migrate._raw(doc)), Dumper=_raw_dumper(), allow_unicode=True, sort_keys=False)


def selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    def raises(fn, *needles):
        try:
            fn()
        except SettingsError as e:
            return all(n in str(e) for n in needles), str(e)
        return False, ""

    secret = "s3cr3t-" + "x" * 8
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        good = d / "settings.yaml"
        good.write_text(
            _new(
                "common:\n  run_env: local\n  connections:\n    pg:\n      host: 127.0.0.1\n      port: '55433'\n"
                f"      password: {secret}\n  runtime:\n    cpu_max_load: ''\n  paths:\n    glossary_dir: ''\n"
                "pipeline:\n  extract:\n    anything: 1\n"
            ),
            encoding="utf-8",
        )
        st = load(_TApp, file=good, environ={})
        check("파일 읽기: 값·형식 변환(port '55433' → 55433)", st.common.connections.pg.port == 55433)
        check("파일 읽기: RUN_ENV는 YAML common.run_env", st.common.run_env == "local")
        check("다른 앱 절(pipeline)은 무시", not hasattr(st, "pipeline"))
        check("빈 값: 숫자 칸 ''은 기본값(cpu_max_load 0.9)", st.common.runtime.cpu_max_load == 0.9)
        check("빈 값: 글자 칸 ''은 빈 글자로 남음", st.common.paths.glossary_dir == "")
        check(
            "비밀: SecretStr로 읽고 repr·model_dump_json에 값 없음",
            st.common.connections.pg.password.get_secret_value() == secret
            and secret not in repr(st)
            and secret not in st.model_dump_json(),
        )
        check("채운 칸만 set(기본값과 구별)", _is_set(st, "common.connections.pg.host") and not _is_set(st, "common.connections.pg.db"))
        # S7e2 — env의 옛 이름은 읽지 않음 · 시험 names= > 덮기 파일 overrides > YAML · RUN_ENV는 env 신호가 YAML을 이김
        env = {"PG_HOST": "10.0.0.9", "PG_PORT": "1", "RUN_ENV": "dev"}
        st2 = load(_TApp, file=good, environ=env)
        check(
            "S7e2: env의 옛 이름(PG_HOST)은 읽지 않음(YAML 값 그대로) · RUN_ENV 신호는 YAML을 이김",
            st2.common.connections.pg.host == "127.0.0.1" and st2.common.connections.pg.port == 55433 and st2.common.run_env == "dev",
        )
        st4 = load(_TApp, file=good, environ={}, names={"PG_PORT": "not-a-port", "PG_HOST": "h"})
        check(
            "names=(시험 덮기): 이름으로 준 값이 YAML을 이김 · 형식이 틀린 값은 그 칸만 버리고 시작(YAML 값 — dropped)",
            st4.common.connections.pg.port == 55433 and st4.common.connections.pg.host == "h" and st4._dropped == {"PG_PORT"},
        )
        ov = d / "ov.yaml"
        ov.write_text(f"base: {good.name}\noverrides:\n  PG_HOST: 10.9.9.9\n  PG_PASSWORD: null\n  CPU_MAX_LOAD: '3'\n", encoding="utf-8")
        so = load(_TApp, file=ov, environ={})
        check(
            "덮기 파일: base(상대 경로 = 이 파일 폴더)를 먼저 읽고 overrides(옛 env 이름 — null = 비움)를 겹침",
            so.common.connections.pg.host == "10.9.9.9"
            and so.common.connections.pg.password is None
            and so.common.connections.pg.port == 55433
            and so.common.runtime.cpu_max_load == 3.0
            and so.common.run_env == "local",
        )
        # 오류 — 메시지에 경로는 있고 비밀 값은 없음
        bad = d / "bad.yaml"
        bad.write_text(
            _new(f"common:\n  connections:\n    pg:\n      port: abc\n      password: [{secret}]\n      hots: x\n"), encoding="utf-8"
        )
        ok, msg = raises(lambda: load(_TApp, file=bad, environ={}), "required.pg.port", "common.connections.pg.hots")
        check("검증 오류: 칸 경로·오타 칸을 알림", ok)
        check("검증 오류: 비밀 칸 값은 메시지에 없음", ok and secret not in msg)
        (d / "empty.yaml").write_text("", encoding="utf-8")
        # R-1 — 입력값은 어떤 칸에서도 찍지 않음: 비밀 칸 이름을 틀린 값(extra_forbidden)·형식 틀린 글자 값
        typo = d / "typo.yaml"
        typo.write_text(_new(f"common:\n  connections:\n    pg:\n      pasword: {secret}\n      port: wrong-{secret}\n"), encoding="utf-8")
        ok, msg = raises(lambda: load(_TApp, file=typo, environ={}), "pg.pasword", "extra_forbidden", "pg.port")
        check(
            "검증 오류(R-1): 비밀 칸 오타·형식 오류에서도 입력값 없음(경로·오류 종류만)", ok and secret not in msg and "wrong-" not in msg
        )
        # R-3 — YAML 스칼라: 글자 칸은 쓴 글자 그대로, 켜기·숫자·JSON 칸은 YAML이 푼 값
        y = d / "scalars.yaml"
        y.write_text(
            _new(
                "common:\n  run_env: local\n  connections:\n"
                "    object_storage:\n      verify_tls: 1\n      region: yes\n    pg:\n      password: 1234\n      db: True\n      host: no\n"
                "    rdb:\n      sqlite: 2026-10-27\n"
                "  models:\n    embed:\n      allow_external: true\n    vlm:\n      allow_external: '1'\n"
                "    guard:\n      internal_host_suffixes: [corp, 10]\n"
                "      internal_ip_ranges: 10\n"
                "    llm:\n      extra_body: {reasoning: {enabled: no}, n: 1}\n  runtime:\n    cpu_max_load: 5\n"
            ),
            encoding="utf-8",
        )
        sy = load(_TApp, file=y, environ={})
        c = sy.common.connections
        check(
            "YAML 스칼라(R-3): 글자 칸 yes·no·1·True → 쓴 글자 'yes'·'no'·'1'·'True'(옛 env 줄과 같은 글자)",
            (c.object_storage.region, c.pg.host, c.object_storage.verify_tls, c.pg.db) == ("yes", "no", "1", "True")
            and type(c.object_storage.region) is str,
        )
        check(
            "YAML 스칼라(R-3): 비밀 칸 숫자 1234 → 글자 '1234' · 날짜 2026-10-27 → 글자 그대로",
            c.pg.password.get_secret_value() == "1234" and c.rdb.sqlite == "2026-10-27",
        )
        check(
            "목록 칸에 스칼라 하나(internal_ip_ranges: 10) → ['10'](옛 env 한 값과 같게)",
            sy.common.models.guard.internal_ip_ranges == ["10"],
        )
        check(
            "YAML 켜기 칸(VS7a2 R-c): true → True · '1' → True · 숫자 칸 5 → 5.0 · 목록 [corp, 10] → 글자",
            sy.common.models.embed.allow_external is True
            and sy.common.models.vlm.allow_external is True
            and sy.common.runtime.cpu_max_load == 5.0
            and sy.common.models.guard.internal_host_suffixes == ["corp", "10"],
        )
        yb = d / "yesno.yaml"
        bad_y = []
        for word in ("yes", "off", "on", "no", "'yes'", "Y"):
            yb.write_text(_new(f"common:\n  run_env: local\n  models:\n    guard:\n      no_paid_calls: {word}\n"), encoding="utf-8")
            ok_y, msg_y = raises(lambda: load(_TApp, file=yb, environ={}), "no_paid_calls", "true·false·0·1")
            if not ok_y or "Value error" not in msg_y and "value_error" not in msg_y:
                bad_y.append(word)
        good_y = []
        for word, want in (("true", True), ("False", False), ("1", True), ("0", False), ("'1'", True), ('"0"', False)):
            yb.write_text(_new(f"common:\n  run_env: local\n  models:\n    guard:\n      no_paid_calls: {word}\n"), encoding="utf-8")
            good_y.append(load(_TApp, file=yb, environ={}).common.models.guard.no_paid_calls is want)
        check(
            "YAML 판정 꼴 켜기 칸(코디네이터 10-27): yes·on·off·no 등은 검증 오류(칸 이름만) · true·false·0·1('1' 포함)만 받음 · env 글자는 옛 판정"
            + (" 실패: " + " ".join(bad_y) if bad_y else ""),
            not bad_y and all(good_y),
        )
        check(
            "YAML 스칼라(R-3): JSON 칸은 푼 값(enabled: no → False, n: 1 → 1)",
            sy.common.models.llm.extra_body == {"reasoning": {"enabled": False}, "n": 1},
        )
        with Cache(_TApp).override(
            data={"common": {"connections": {"object_storage": {"region": True}}}}, file=d / "empty.yaml", environ={"RUN_ENV": "local"}
        ) as so:
            check("시험 data=: 글자 칸에 파이썬 True → 옛 env 꼴 '1'", so.common.connections.object_storage.region == "1")
        # R-4 — 빈 글자: 기본값 있는 칸은 설정 안 함(옛 `get(X) or 기본값`), 기본값 None인 글자 칸만 '' 유지 · 옛 env·migrate도 같은 규칙
        bl = load(
            _TApp,
            file=d / "empty.yaml",
            environ={"RUN_ENV": "local"},
            names={"OS_REGION": "", "PG_HOST": "", "EMBED_TIMEOUT": "", "INTERNAL_IP_RANGES": ""},
        )
        check(
            "빈 글자(R-4): 기본값 있는 글자 칸(OS_REGION)의 ''은 기본값, 설정 안 한 칸으로 봄",
            bl.common.connections.object_storage.region == "us-east-1" and not _is_set(bl, "common.connections.object_storage.region"),
        )
        check(
            "빈 글자(R-4): 기본값 None 글자 칸(PG_HOST)은 '' 유지 · 숫자·목록 칸 ''은 기본값",
            bl.common.connections.pg.host == ""
            and bl.common.models.embed.timeout == 60
            and bl.common.models.guard.internal_ip_ranges == [],
        )
        bk = load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"OS_VERIFY_TLS": "", "EXTERNAL_SCOPE": ""})
        check(
            "빈 글자: blank=keep 칸(옛 os.environ.get(X, 기본) — OS_VERIFY_TLS·EXTERNAL_SCOPE)은 '' 유지(S7a2 (b))",
            (bk.common.connections.object_storage.verify_tls, bk.common.models.guard.external_scope) == ("", ""),
        )
        check(
            "PG_HOST·PG_PORT 기본값 None(필수 칸 — 비면 pg.conf가 거부, op-09)",
            bl.common.connections.pg.port is None and CommonConnectionsPg().host is None,
        )
        # R-2 — int | "auto"
        au = load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"PIPE_PROCS": "auto", "PIPE_THREADS": "3"})
        bx = load(
            _TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"PIPE_PROCS": "x", "PIPE_THREADS": "many", "PG_HOST": "h"}
        )
        check(
            "auto 칸의 형식 틀린 옛 env 값도 그 칸만 버리고 시작(기본값 — PC None·이미지 auto)",
            bx.common.runtime.pipe_procs == CommonRuntime().pipe_procs
            and bx.common.runtime.pipe_threads is None
            and bx.common.connections.pg.host == "h",
        )
        f25 = load(
            _TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"PIPE_PROCS": "2.5", "PIPE_MAX_PROCS": "auto"}
        ).common.runtime
        bl_p = load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"PIPE_PROCS": ""}).common.runtime.pipe_procs
        check(
            "PIPE_PROCS(VS7a2 R-d · S7c1 답 ①b): auto는 'auto'로 기억·빈 값은 None(run_all이 가름), 숫자는 옛 float()처럼 소수도(2.5), 그 밖 _f 칸 auto = 기본값",
            au.common.runtime.pipe_procs == "auto"
            and bl_p is None
            and au.common.runtime.pipe_threads == 3.0
            and CommonRuntime().pipe_procs == IMAGE_DEFAULTS.get("PIPE_PROCS")
            and f25.pipe_procs == 2.5
            and f25.pipe_max_procs == 8,
        )
        saved_img = dict(IMAGE_DEFAULTS)
        try:  # B-2 — 이미지 기본값 칸의 빈 글자는 정말 비움(옛 env_file `X=`이 이미지 ENV를 덮던 것) — 이미지 흉내(표만 바꿈)
            IMAGE_DEFAULTS.update(DOC_DIR="/data/docs", PIPE_PROCS="auto")
            ib = load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"DOC_DIR": "", "PIPE_PROCS": ""}).common
            img_blank = (ib.paths.doc_dir, ib.runtime.pipe_procs) == ("", None)
        finally:
            IMAGE_DEFAULTS.clear()
            IMAGE_DEFAULTS.update(saved_img)
        check("이미지 기본값 칸(B-2): 빈 글자 = 정말 비움 — 글자 칸 '' · 숫자 칸 None(이미지 기본값 /data/docs·auto가 아님)", img_blank)
        aw = {
            raw: load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"PIPE_PROCS": raw}).common.runtime.pipe_procs
            for raw in ("AUTO", "Auto", "auto ", " ", " 5")
        }
        check(
            "PIPE_PROCS auto(VS7c1 R-1): 대소문자·앞뒤 공백 무시·공백만도 auto(옛 resolve_procs strip·lower) · ' 5'는 5",
            aw == {"AUTO": "auto", "Auto": "auto", "auto ": "auto", " ": "auto", " 5": 5.0},
        )
        # VS7a2 R-c — 켜기 칸은 키마다 옛 판정 꼴(env 글자 그대로 · 빈 글자 포함)
        cases = [
            (
                "NO_PAID_CALLS",
                "models.guard.no_paid_calls",
                {"1": True, "yes": False, "true": False, "on": False, "": False, "0": False, " 1": False},
            ),
            (
                "DOC_REGISTRY",
                "store.doc_registry",
                {"0": False, " False ": False, "none": False, "": False, "no": True, "off": True, "1": True},
            ),
        ]
        bad_j = []
        for env_n, path_n, table in cases:
            for raw, want in table.items():
                got = _get(load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={env_n: raw}).common, path_n)
                if got is not want:
                    bad_j.append(f"{env_n}={raw!r}→{got}")
        check(
            "켜기 칸 옛 판정 꼴(R-c): =='1'·!='0'·strip().lower() not in ('','0','none','false') — yes·true·on·빈 글자까지 옛 결과와 같음 "
            + " ".join(bad_j),
            not bad_j,
        )

        # VS7a2 R-a — 기본값 있는 목록 칸의 빈 값([]·'')은 옛 `or 기본`처럼 기본값, blank=keep 목록은 빈 목록
        class _TL(Section):
            phases: CsvList | None = F(["1", "2"], "X_PH", "시험")
            tables: CsvList | None = F(None, "X_TB", "시험", blank="keep")

        check(
            "빈 목록(R-a): or 칸 [] · '' → 기본값, keep 칸 '' · [] → []",
            _TL(phases=[]).phases == ["1", "2"]
            and _TL(phases="").phases == ["1", "2"]
            and _TL(tables="").tables == []
            and _TL(tables=[]).tables == []
            and _TL().tables is None,
        )

        class _TD(Section):
            threads: int | None = F(None, "X_TH", "시험", unset="nondigit")

        check(
            "unset=nondigit(OCR_THREADS 옛 isdigit): auto·-1·2.5 → 설정 안 함, '05' → 5",
            _TD(threads="auto").threads is None
            and _TD(threads="-1").threads is None
            and _TD(threads="2.5").threads is None
            and _TD(threads="05").threads == 5,
        )
        # 설정 캐시(S7e2) — 파일 기반: 신호(SETTINGS_FILE)가 바뀌거나 put()이면 다시 읽음 · env()는 os.environ 안 건드림 · 옛 env 이름은 안 읽음
        cc = Cache(CommonAppSettings)
        tf = d / "cache.yaml"
        tf.write_text(_new("common:\n  run_env: local\n  models:\n    embed:\n      timeout: 7\n"), encoding="utf-8")
        saved = {k: os.environ.get(k) for k in ("SETTINGS_FILE", "EMBED_TIMEOUT")}  # env 남김 — 시험
        try:
            os.environ["SETTINGS_FILE"] = str(tf)  # env 남김 — 시험
            a1 = cc.get().common.models.embed.timeout
            same = cc.get() is cc.get()
            os.environ["EMBED_TIMEOUT"] = "8"  # env 남김 — 시험 · 옛 env 이름 — 읽지 않음
            a2 = cc.get().common.models.embed.timeout
            pp = put(EMBED_TIMEOUT="9", PIPE_PROCS="3")
            a3 = (
                cc.get().common.models.embed.timeout,
                cc.get().common.runtime.pipe_procs,
                os.environ["SETTINGS_FILE"] == str(pp),
            )  # env 남김 — 시험
            import yaml as _y

            ov_doc = _y.safe_load(pp.read_text(encoding="utf-8"))
            secret_free = set(ov_doc) == {"base", "overrides"} and Path(ov_doc["base"]).resolve() == tf.resolve()
            rel_dir = d / "rel" / "sub"
            rel_dir.mkdir(parents=True)
            (rel_dir / "ov.yaml").write_text("base: ../../cache.yaml\noverrides:\n  PG_HOST: relhost\n", encoding="utf-8")
            flat = overlay_file({"PG_PORT": "5"}, base=rel_dir / "ov.yaml")
            rel_ok = (
                load(CommonAppSettings, file=flat, environ={}).common.connections.pg.host == "relhost"
                and load(CommonAppSettings, file=flat, environ={}).common.models.embed.timeout == 7
            )  # 상대 base(리뷰 S7e2)
            ce = child_env(EMBED_TIMEOUT="11")
            child_ok = ce["SETTINGS_FILE"] != os.environ["SETTINGS_FILE"] and cc.get().common.models.embed.timeout == 9  # env 남김 — 시험
            child_ok = (
                child_ok
                and load(CommonAppSettings, environ=ce).common.models.embed.timeout == 11
                and load(CommonAppSettings, environ=ce).common.runtime.pipe_procs == 3.0
            )  # 앞 put 값도 이어받음(한 단 — base는 원본)
            with cc.env(EMBED_TIMEOUT="12", PIPE_PROCS=None) as e1:
                with cc.env(LLM_TIMEOUT="5"):
                    inner = cc.get().common.models
                    nest = (inner.embed.timeout, inner.llm.timeout)
                in_env = cc.get() is e1 and e1.common.runtime.pipe_procs == CommonRuntime().pipe_procs  # None = 비움(기본값 — 이미지 auto)
            after = cc.get().common.models.embed.timeout
            try:
                put(NOT_A_SETTING_X="1")
                unknown_put = False
            except KeyError:
                unknown_put = True
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)  # env 남김 — 시험
        check("설정 캐시: 파일 값 · 같은 객체 · env의 옛 이름(EMBED_TIMEOUT)은 안 읽음", a1 == 7 and same and a2 == 7)
        check(
            "put(): 덮기 파일(base = 원본 경로 + overrides만 — 원본 비밀 복사 없음)로 SETTINGS_FILE을 바꾸고 캐시가 다시 읽음 · 칸 없는 이름은 KeyError",
            a3 == (9, 3.0, True) and secret_free and unknown_put,
        )
        check("child_env(): 자식 env만 새 덮기 파일(부모 값 그대로) · 앞 put 값 이어받음", child_ok)
        check("덮기 파일 이어받기: 상대 base는 그 덮기 파일 폴더 기준(임시 폴더로 옮겨도 원본을 찾음)", rel_ok)
        # S7e3 — VS7e2 B-2(서버는 overrides 도구 막음·코드 안 child_env는 그대로)·R-2(손으로 쓴 YAML 값)·R-3(서버 거부)·R-5·R-11
        from common.config import overrides as OV

        srv = d / "srv"
        srv.mkdir()
        (srv / "settings.yaml").write_text(_new("common:\n  run_env: dev\n  models:\n    embed:\n      timeout: 7\n"), encoding="utf-8")
        blocked = (
            OV.server_run_env(environ={"RUN_ENV": "dev"}) == "dev"
            and OV.server_run_env(environ={"SETTINGS_FILE": str(srv / "settings.yaml")}) == "dev"
            and OV.server_run_env(base=srv / "settings.yaml", environ={}) == "dev"
            and OV.server_run_env(environ={"RUN_ENV": "local", "SETTINGS_FILE": str(srv / "settings.yaml")}) is None
            and raises(lambda: OV.server_run_env(environ={"RUN_ENV": "prod"}), "RUN_ENV")[0]
        )
        (srv / "typo.yaml").write_text(_new("common:\n  run_env: prod\n"), encoding="utf-8")
        blocked = (
            blocked and raises(lambda: OV.server_run_env(base=srv / "typo.yaml", environ={}), "RUN_ENV")[0]
        )  # --base도 같은 규칙(리뷰 S7e3)
        senv = {"RUN_ENV": "dev", "SETTINGS_FILE": str(srv / "settings.yaml")}  # 컨테이너 안 꼴(env RUN_ENV·SETTINGS_FILE = 붙인 파일)
        ce_srv = child_env(senv, EMBED_TIMEOUT="13", PIPE_PROCS=None)
        ce_doc = read_yaml(ce_srv["SETTINGS_FILE"])
        srv_child = (
            load(CommonAppSettings, environ=ce_srv).common.models.embed.timeout == 13
            and Path(str(ce_doc["base"])) == (srv / "settings.yaml").absolute()
            and ce_srv["RUN_ENV"] == "dev"
        )
        check(
            "덮기 파일 도구는 서버(env·원본 파일 run_env가 dev·prd, 모르는 글자)면 막음 · 코드 안 child_env는 서버에서도 그대로(base = 붙인 파일 경로)",
            blocked and srv_child,
        )
        (d / "ovb.yaml").write_text(
            f"base: {tf}\noverrides:\n  NO_PAID_CALLS: true\n  EMBED_TIMEOUT: 9\n  LLM_MODEL: true\n  VLM_MODEL: 1.10\n  PM_PREFIX: 0123\n",
            encoding="utf-8",
        )
        ovb = load(CommonAppSettings, file=d / "ovb.yaml", environ={})
        ovb_flat = load(CommonAppSettings, file=overlay_file({"LLM_TIMEOUT": "5"}, base=d / "ovb.yaml"), environ={})
        same_rule = [
            (o.common.models.guard.no_paid_calls, o.common.models.embed.timeout, o.common.models.llm.model, o.common.models.vlm.model)
            for o in (ovb, ovb_flat)
        ]
        (d / "ovy.yaml").write_text(f"base: {tf}\noverrides:\n  NO_PAID_CALLS: yes\n", encoding="utf-8")
        check(
            "덮기 파일 손으로 쓴 YAML 값(R-2): 절 안과 같은 규칙(true → 켬·글자 칸은 쓴 글자) — 직접 읽기·펼쳐 쓰기 같음 · yes·on은 거부",
            same_rule == [(True, 9, "true", "1.10")] * 2
            and raises(lambda: load(CommonAppSettings, file=d / "ovy.yaml", environ={}), "true·false")[0],
        )
        (d / "ovs.yaml").write_text(f"base: {srv / 'settings.yaml'}\noverrides:\n  PG_HSOT: x\n", encoding="utf-8")
        (d / "ovf.yaml").write_text(f"base: {srv / 'settings.yaml'}\noverrides:\n  PG_PORT: 54x32\n", encoding="utf-8")
        (d / "ovl.yaml").write_text(f"base: {tf}\noverrides:\n  PG_HSOT: x\n  PG_PORT: 54x32\n", encoding="utf-8")
        loc = load(CommonAppSettings, file=d / "ovl.yaml", environ={})
        check(
            "덮기 파일 모르는 이름·형식 오류(R-3): 서버는 거부(이름·칸 경로만) · local은 경고 뒤 그 칸 버림",
            raises(lambda: load(CommonAppSettings, file=d / "ovs.yaml", environ={}), "PG_HSOT")[0]
            and (lambda r: r[0] and "54x32" not in r[1])(
                raises(lambda: load(CommonAppSettings, file=d / "ovf.yaml", environ={}), "pg.port")
            )
            and loc.common.connections.pg.port is None
            and loc._dropped == {"PG_PORT"}
            and raises(
                lambda: load(CommonAppSettings, file=d / "ovl.yaml", environ={"RUN_ENV": "production"}, lenient_run_env=True), "PG_HSOT"
            )[0],
        )  # 모르는 RUN_ENV 글자는 가드처럼 서버로(리뷰 S7e3)
        envw = {"SETTINGS_FILE": str(tf), "SERVER_ENV_DIR": "/srv/rag/env", "PIPE_PROCS": "2"}
        _warned.clear()
        import io as _io

        buf, saved_err = _io.StringIO(), sys.stderr
        sys.stderr = buf
        try:
            pin_env(envw)
        finally:
            sys.stderr = saved_err
        check(
            "옛 이름 경고(R-5): 셸이 늘 export하는 SERVER_ENV_DIR는 빼고 알림",
            "PIPE_PROCS" in buf.getvalue() and "SERVER_ENV_DIR" not in buf.getvalue(),
        )
        check(
            "overridden()(R-11): 지금 덮기 파일의 overrides 이름만(공유 settings.yaml 값은 아님)",
            overridden({"SETTINGS_FILE": str(d / "ovb.yaml")}) == {"NO_PAID_CALLS", "EMBED_TIMEOUT", "LLM_MODEL", "VLM_MODEL", "PM_PREFIX"}
            and overridden({"SETTINGS_FILE": str(tf)}) == frozenset(),
        )
        check(
            "dropped(): 형식 틀려 버린 옛 env 이름을 알림",
            load(_TApp, file=d / "empty.yaml", environ={"RUN_ENV": "local"}, names={"LOG_RETENTION_DAYS": "x"})._dropped
            == {"LOG_RETENTION_DAYS"},
        )
        with COMMON.env(LLM_BUDGET_USD="abc", LLM_MAX_CALLS="5"):
            try:
                checked("LLM_BUDGET_USD")
                chk = False
            except ValueError as e:
                chk = "LLM_BUDGET_USD" in str(e) and "abc" not in str(e)
            checked("LLM_MAX_CALLS")
            ok_other = cfg().runtime.cpu_max_load is not None  # 다른 칸 읽기는 그대로
        check("checked(): 형식 틀린 지출 상한은 읽는 자리에서 ValueError(이름만) · 다른 칸·맞는 값은 그대로", chk and ok_other)
        check(
            "Cache.env(): 겹쳐 쓰기·None = 비움(기본값)·os.environ 안 건드림·끝나면 파일 기반으로",
            nest == (12, 5) and in_env and after == 9,
        )
        # 영구 다리(pin_env — D-028 ⑤): 엔진·인계 칸만 env로, env에 이미 있으면 그대로, 그 밖 칸은 안 냄
        bf = d / "pin.yaml"
        bf.write_text(
            _new(
                "common:\n  run_env: local\n  paths:\n    glossary_dir: /g\n  models:\n    embed:\n      timeout: 11\n    vlm:\n      model: m\n"
            ),
            encoding="utf-8",
        )
        env_b = {"SETTINGS_FILE": str(bf), "VLM_MODEL": "user"}
        n_b = pin_env(env_b)
        check(
            "영구 다리: 인계 칸(GLOSSARY_DIR)을 env로 · env에 있던 엔진 칸(VLM_MODEL)은 그대로 · 그 밖 칸(EMBED_TIMEOUT)은 안 냄",
            env_b.get("GLOSSARY_DIR") == "/g" and env_b["VLM_MODEL"] == "user" and "EMBED_TIMEOUT" not in env_b and n_b >= 1,
        )
        check(
            "영구 다리: 설정 파일 없으면 이미지 기본값만(PC는 아무것도)",
            pin_env({"RUN_ENV": "dev"}) == len([n for n in IMAGE_DEFAULTS if n in _pinned(section_class(SECTIONS)[0]).values()]),
        )
        # VS7a2 R-e — migrate 여러 파일: 틀의 자리표시가 앞 파일의 실제 값을 덮지 않음
        from common.config import migrate

        (d / "a.env").write_text("MCP_TOKEN=real\nRUN_ENV=dev\n", encoding="utf-8")
        (d / "b.env").write_text("MCP_TOKEN=<여기에 기입>\nRUN_ENV=<실행 환경>\nPG_DB=<DB 이름>\n", encoding="utf-8")
        env_m, holders = migrate.read_files([d / "a.env", d / "b.env"])
        check(
            "migrate 여러 파일(R-e): 자리표시는 앞 파일 값을 안 덮음 · 끝까지 값 없는 것만 자리표시로 보고",
            env_m == {"MCP_TOKEN": "real", "RUN_ENV": "dev"} and holders == {"PG_DB"},
        )
        (d / "syntax.yaml").write_text("common:\n  a: [1\n", encoding="utf-8")
        check("YAML 형식 오류: 행 번호", raises(lambda: load(_TApp, file=d / "syntax.yaml", environ={}), "형식 오류", "행")[0])
        (d / "top.yaml").write_text("commn:\n  x: 1\n", encoding="utf-8")
        check("모르는 최상위 절 거부", raises(lambda: load(_TApp, file=d / "top.yaml", environ={}), "commn")[0])
        check("파일 없음: 알림", raises(lambda: load(_TApp, file=d / "none.yaml", environ={}), "읽지 못함")[0])
        check("RUN_ENV 모르는 값 거부", raises(lambda: load(_TApp, file=good, environ={"RUN_ENV": "prod"}), "RUN_ENV")[0])
        check("RUN_ENV=prd인데 파일 없음 → 거부", raises(lambda: load(_TApp, environ={"RUN_ENV": "prd"}), "서버는 설정 파일")[0])
        check(
            "RUN_ENV 없음: 거부(STRICT — D-028 ②), strict=False면 시작",
            raises(lambda: load(_TApp, file=d / "empty.yaml", environ={}), "RUN_ENV 없음")[0]
            and load(_TApp, file=d / "empty.yaml", environ={}, strict=False).common.run_env is None,
        )
        check(
            "resolve_run_env: env > 파일 common.run_env · 둘 다 없으면 None",
            resolve_run_env({"RUN_ENV": "dev", "SETTINGS_FILE": str(good)}) == "dev"
            and resolve_run_env({"SETTINGS_FILE": str(good)}) == "local"
            and resolve_run_env({"SETTINGS_FILE": str(d / "empty.yaml")}) is None,
        )
        check(
            "RUN_ENV=stage 거부(op-02 — 사용자 10-29, local·dev·prd만)",
            raises(lambda: resolve_run_env({"RUN_ENV": "stage"}), "local·dev·prd")[0],
        )
        # op-02 — LLM_FAKE는 local 전용: 서버(dev·prd)에서 켜져 있으면 시작 관문이 종료 2, 꺼져 있으면 통과
        (d / "srv_fake.yaml").write_text(_new("common:\n  run_env: dev\n  dev: {llm_fake: true}\n"), encoding="utf-8")
        (d / "srv_ok.yaml").write_text(_new("common:\n  run_env: prd\n"), encoding="utf-8")
        try:
            require_run_env("시험", {"SETTINGS_FILE": str(d / "srv_fake.yaml")}, sections=())
            fake_gate = False
        except SystemExit as e:
            fake_gate = e.code == 2
        check(
            "require_run_env: 서버에서 llm_fake 켜면 종료 2 · 끄면 통과 · local은 켜도 통과",
            fake_gate
            and require_run_env("시험", {"SETTINGS_FILE": str(d / "srv_ok.yaml")}, sections=()) == "prd"
            and require_run_env("시험", {"RUN_ENV": "local"}) == "local",
        )
        try:
            require_run_env("시험", {"SETTINGS_FILE": str(d / "empty.yaml")})
            gate = False
        except SystemExit as e:
            gate = e.code == 2
        check("require_run_env: 없으면 종료 코드 2", gate and require_run_env("시험", {"RUN_ENV": "local"}) == "local")
        check("SETTINGS_FILE env로 파일 찾기", load(_TApp, environ={"SETTINGS_FILE": str(good)}).common.run_env == "local")
        # 내보내기 — 켜기 1/0, 목록 쉼표, 비밀은 secrets=True일 때만, 채운 칸만
        st3 = load(
            _TApp,
            file=d / "empty.yaml",
            environ={"RUN_ENV": "local"},
            data={
                "common": {
                    "models": {"guard": {"no_paid_calls": True, "internal_ip_ranges": ["10.1.0.0/16", "10.2.0.0/16"]}},
                    "connections": {"pg": {"password": secret}},
                }
            },
        )
        items = {k: v for k, v, _ in env_items(st3)}
        check(
            "env_items: 켜기 → '1', 목록 → 쉼표",
            items.get("NO_PAID_CALLS") == "1" and items.get("INTERNAL_IP_RANGES") == "10.1.0.0/16,10.2.0.0/16",
        )
        check("env_items: 비밀은 기본으로 안 냄 · 기본값 칸은 안 냄", "PG_PASSWORD" not in items and "PG_PORT" not in items)
        cache = Cache(_TApp)
        with cache.override(file=d / "empty.yaml", data={"common": {"runtime": {"cpu_max_load": 5}}}, environ={"RUN_ENV": "local"}) as s:
            check("Cache.override: 시험 동안 바꿔 끼움", cache.get() is s and s.common.runtime.cpu_max_load == 5.0)
        check("Cache.override: 끝나면 되돌림", cache._value is None)
        # VS7b 처리(S7c1)
        with COMMON.env(PG_PASSWORD="", PG_HOST="h", EDW_PASSWORD=""):
            blank_secret = given("PG_PASSWORD") is None and given("EDW_PASSWORD") is None and given("PG_HOST") == "h"
        check("given(BLOCK-1): 빈 비밀(PG_PASSWORD=·EDW_PASSWORD= — SecretStr(''))은 준 값 아님(접속 파일 값을 덮지 않음)", blank_secret)
        bad_b = []
        for raw in ("nan", "inf", "-inf", "NaN"):
            with COMMON.env(LLM_BUDGET_USD=raw):
                try:
                    checked("LLM_BUDGET_USD")
                    bad_b.append(raw)
                except ValueError:
                    pass
        check(
            "LLM_BUDGET_USD nan·inf(R-12)는 형식 오류 — 읽는 자리에서 실패(상한 없음으로 열리지 않음)"
            + (" 실패: " + " ".join(bad_b) if bad_b else ""),
            not bad_b,
        )
        with COMMON.env(LLM_TIMEOUT="90.5", STRUCT_BACKEND=None):
            tm = cfg().models.llm.timeout
            sb = cfg().store.struct_backend
        with COMMON.env(STRUCT_BACKEND=""):
            sb_blank = cfg().store.struct_backend
        check(
            "LLM_TIMEOUT float(R-1 — 옛 float()): '90.5' → 90.5 · STRUCT_BACKEND 기본 'pg', ''은 ''(R-11 blank keep)",
            tm == 90.5 and sb == "pg" and sb_blank == "",
        )
        with COMMON.env(RUN_ENV="prod"):
            unk = guard_run_env()
        with COMMON.env(RUN_ENV="dev"):
            known = guard_run_env()
        check(
            "guard_run_env(U-1): 모르는 RUN_ENV 글자(prod)는 그대로(가드가 서버로 봄) · 아는 값은 그 값", unk == "prod" and known == "dev"
        )
        # STRICT(S7b c안 · VS7e1 U-1 — 사용자 10-28): 틀린 설정 파일이면 서버는 import common(영구 다리)에서 바로 실패, local은 경고 뒤 계속
        import subprocess

        badf = d / "strict_bad.yaml"
        badf.write_text("common:\n  paths:\n    glossary_dir: [1\n", encoding="utf-8")
        base_env = {
            k: v for k, v in os.environ.items() if k not in ("SETTINGS_FILE", "RAG_MODULE", "GLOSSARY_DIR", "SETTINGS_LENIENT")
        }  # env 남김 — 시험 · RAG_MODULE 빼고 — 세 절(U-a)
        base_env.update(PYTHONPATH=str(REPO_ROOT))
        rcs = {
            run: subprocess.run(
                [sys.executable, "-c", "import common"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=td,
                env={**base_env, "RUN_ENV": run, "SETTINGS_FILE": str(badf)},
            ).returncode
            for run in ("dev", "local")
        }
        check(f"STRICT: 틀린 설정 파일 — 서버(dev)는 import common 실패 · local은 계속 {rcs}", rcs["dev"] != 0 and rcs["local"] == 0)
        try:
            require_run_env("시험", {"RUN_ENV": "prd", "SETTINGS_FILE": str(d / "none.yaml")})
            gate_u1 = False
        except SystemExit as e:
            gate_u1 = e.code == 2
        gb = d / "gate_bad.yaml"
        gb.write_text(_new("common:\n  connections:\n    pg:\n      port: abc\n"), encoding="utf-8")
        try:
            require_run_env("시험", {"RUN_ENV": "dev", "SETTINGS_FILE": str(gb)}, sections=())
            gate_u1b = False
        except SystemExit as e:
            gate_u1b = e.code == 2
        check(
            "시작 관문(U-1): 서버면 설정 파일을 못 읽거나(없음) 검증 실패면 종료 2 · local은 검증 안 함",
            gate_u1 and gate_u1b and require_run_env("시험", {"RUN_ENV": "local", "SETTINGS_FILE": str(gb)}) == "local",
        )
        if "mcp" in app_classes(("mcp",)):  # VS7d R-1 — import common 먼저여도 mcp CFG(시작 상수)가 settings.yaml 값을 봄(mcp 이미지·PC)
            cf = d / "cfg.yaml"
            cf.write_text(_new("mcp:\n  output:\n    max_chars: 12345\n"), encoding="utf-8")
            got = [
                subprocess.run(
                    [sys.executable, "-c", f"{o}; print(CFG.MAX_CHARS)"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=td,
                    env={**base_env, "SETTINGS_FILE": str(cf)},
                ).stdout.split()[-1:]
                for o in ("import common; from mcp_server.config import CFG", "from mcp_server.config import CFG; import common")
            ]
            check(f"VS7d R-1: import 순서와 무관하게 mcp CFG가 설정 파일 값 {got}", got == [["12345"], ["12345"]])
        # U-a(사용자 10-27) — 영구 다리는 이미지마다 common + 자기 앱 절의 엔진·인계 칸만(RAG_MODULE), 관계없는 앱 절은 내지도 검증하지도 않음
        ua = d / "ua.yaml"
        ua.write_text(
            _new(
                "common:\n  paths:\n    glossary_dir: /g\npipeline:\n  extract:\n    ocr:\n      dpi: 150\n  connections:\n    secure_doc:\n      password: dummy-ua\n"
                "mcp:\n  search:\n    weights:\n      id: 7\n"
            ),
            encoding="utf-8",
        )
        ua_bad = d / "ua_bad.yaml"
        ua_bad.write_text(
            _new("common:\n  paths:\n    glossary_dir: /g\npipeline:\n  extract:\n    ocr:\n      dpi: abc\n"), encoding="utf-8"
        )
        has_p = "pipeline" in app_classes(("pipeline",))
        seen = {}
        for mod, f in (("mcp", ua), ("pipeline", ua), ("", ua), ("mcp", ua_bad), ("parse", ua), (" mcp", ua)):
            env_e = {"SETTINGS_FILE": str(f), "RAG_MODULE": mod, "RUN_ENV": "dev"}
            try:
                pin_env(env_e)
                seen[(mod, f.name)] = (
                    env_e.get("GLOSSARY_DIR"),
                    env_e.get("OCR_DPI"),
                    "SECURE_DOC_PASSWORD" in env_e or "SEARCH_W_ID" in env_e,
                )
            except SettingsError:
                seen[(mod, f.name)] = "거부"
        ocr = "150" if has_p else None
        check(
            f"영구 다리(U-a): mcp 이미지 = common 칸만(pipeline 엔진 칸 OCR_DPI 없음) · pipeline 이미지 = common·pipeline · 비밀·그 밖 칸은 안 냄 · "
            f"mcp 이미지는 틀린 pipeline 절이어도 성공 · 모르는 RAG_MODULE은 아무것도 안 냄 {seen}",
            seen[("mcp", "ua.yaml")] == ("/g", None, False)
            and seen[("pipeline", "ua.yaml")] == ("/g", ocr, False)
            and seen[("", "ua.yaml")] == ((None, None, False) if IN_IMAGE else ("/g", ocr, False))
            and seen[("mcp", "ua_bad.yaml")] == ("/g", None, False)
            and all(seen[(m, "ua.yaml")] == (None, None, False) for m in ("parse", " mcp")),
        )
    check(
        "이미지 절(VS7d R-6): RAG_MODULE 없음 = 셋(PC·이미지) · 빈 글자 = PC 셋 / 이미지 안 아무것도 · pipeline·mcp = 자기 절",
        image_sections({}, in_image=True) == SECTIONS
        and image_sections({"RAG_MODULE": ""}, in_image=False) == SECTIONS
        and image_sections({"RAG_MODULE": ""}, in_image=True) == ()
        and image_sections({"RAG_MODULE": "mcp"}, in_image=True) == ("common", "mcp")
        and image_sections({"RAG_MODULE": "pipeline"}, in_image=False) == ("common", "pipeline"),
    )
    check(
        "RUN_ENV 외부 모델: 정확히 local만 허용(지금 가드) — 없음·dev·prd·모르는 글자(prod·PRD·' local')는 거부(VS7b U-1 b)",
        not any(external_models_allowed(e) for e in (None, *SERVER_ENVS, "prod", "PRD", " local", "Local"))
        and external_models_allowed("local"),
    )
    envs = [env_name(f) for p, f, _ in walk(CommonSettings) if not is_host("common." + p)]
    check("common 칸마다 옛 env 이름 있음·(호스트 절 빼고) 겹침 없음", all(envs) and len(envs) == len(set(envs)))
    check("호스트 절 판정: 절 이름 host만(잎 칸 host는 아님)", is_host("pipeline.host.image") and not is_host("common.connections.pg.host"))

    class _TW(Section):
        mods: WordList | None = F(["a", "b"], "X_MODS", "시험")
        csv: CsvList | None = F(["x"], "X_CSV", "시험")

    tw = _TW(mods="parse  publish,load", csv="p, q")
    check(
        "WordList: 옛 env 공백(·쉼표) 목록 → 목록, 옛 env로는 공백으로 냄 · CsvList는 쉼표",
        tw.mods == ["parse", "publish", "load"]
        and render(tw.mods, sep=list_sep(_TW.model_fields["mods"])) == "parse publish load"
        and render(tw.csv, sep=list_sep(_TW.model_fields["csv"])) == "p,q"
        and _TW().mods == ["a", "b"],
    )

    if {"pipeline", "mcp"} <= set(
        app_classes()
    ):  # S7e1 — export(호스트 스크립트 다리)·migrate --compare(서버 이관 확인) — 두 앱 모델이 있는 곳(PC·두 이미지)
        import io

        from common.config import export as E
        from common.config import migrate as M

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            f = d / "s.yaml"
            f.write_text(
                _new(
                    "common:\n  run_env: dev\npipeline:\n  host:\n    image: 'p:1'\n  service:\n    trigger:\n      host: 10.1.1.1\n"
                    "mcp:\n  host:\n    image: 'm:$x'\n  server:\n    host: 10.2.2.2\n    max_concurrency: abc\n    token: dummy-s7e1\n"
                ),
                encoding="utf-8",
            )

            def run(*argv):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = E.main(["--file", str(f), *argv])
                return rc, out.getvalue(), err.getvalue()

            rc1, o1, _ = run(
                "--format",
                "sh",
                "--section",
                "pipeline.host",
                "--section",
                "pipeline.service.trigger.host",
                "--section",
                "mcp.server.host",
                "--section",
                "common.run_env",
            )
            rc2, o2, e2 = run("--section", "mcp.host")
            rc3, _, e3 = run("--section", "mcp.server")
            check(
                "export(S7e1): 잎 칸 이름이 host인 앱 칸(TRIGGER_HOST·MCP_HOST)도 냄 · 고른 칸만 검증(mcp 절 오타가 다른 칸을 막지 않음) · "
                "env 꼴은 $ 값 거부(이름만) · 고른 절이 틀리면 거부 · 비밀 없음",
                rc1 == 0
                and "export TRIGGER_HOST='10.1.1.1'" in o1
                and "export MCP_HOST='10.2.2.2'" in o1
                and "export RUN_ENV='dev'" in o1
                and rc2 == 2
                and "MCP_SERVER_IMAGE" in e2
                and "$x" not in e2
                and rc3 == 2
                and "dummy" not in o1 + o2 + e2 + e3,
            )
            old = d / "old.env"
            old.write_text(
                "RUN_ENV=dev\nDATA_PIPELINE_IMAGE=p:1\nCHUNK_SIZE=800\nPG_PASSWORD=dummy-a\nOMP_NUM_THREADS=2\n", encoding="utf-8"
            )
            new = d / "new.yaml"
            new.write_text(
                _new("common:\n  run_env: dev\n  connections:\n    pg:\n      password: dummy-b\npipeline:\n  host:\n    image: 'p:1'\n"),
                encoding="utf-8",
            )
            old.write_text(
                "RUN_ENV=dev\nDATA_PIPELINE_IMAGE=p:1\nCHUNK_SIZE=800\nPG_PASSWORD=dummy-a\nOMP_NUM_THREADS=2\nNETWORK_HOST=1\n",
                encoding="utf-8",
            )
            res, outside, _ = M.compare([old], new, app_classes(), catalog=False)
            got = {k: sorted(n for n, _ in v) for k, v in res.items() if k != "같음"}
            check(
                f"migrate --compare(S7e1·S7e2): 같음·다름(비밀도 값 없이)·옛에만·라이브러리 env 칸·모델 밖 이름 {got} {outside}",
                got == {"다름": ["PG_PASSWORD"], "옛에만": ["CHUNK_SIZE", "common.runtime.lib_env.OMP_NUM_THREADS"], "새에만": []}
                and outside == ["NETWORK_HOST"]
                and ("DATA_PIPELINE_IMAGE", "pipeline.host.image") in res["같음"],
            )
            # VS7e1 B-3 — compose env_file 규칙(compose-go dotenv): 큰따옴표 이스케이프·$ 치환, 작은따옴표 글자 그대로 · 확인 필요는 이름만
            vals, why = M.parse_env_text(
                'A=x #c\nB="a\\nb"\nC=\'l\\n\'\nD=$A-y\nE="${A}z"\nF="\\$A"\nG="${NOPE:-d}"\nH=$$q\nM="two\nlines"\nP=plain\n'
            )
            check(
                f"migrate B-3: compose env_file 규칙 {sorted(why)}",
                vals
                == {
                    "A": "x",
                    "B": "a\nb",
                    "C": "l\\n",
                    "D": "x-y",
                    "E": "xz",
                    "F": "$A",
                    "G": "d",
                    "H": "$q",
                    "M": "two\nlines",
                    "P": "plain",
                }
                and set(why) == {"B", "C", "D", "E", "F", "G", "H", "M"}
                and "x" not in " ".join(why.values()),
            )
            # C-45 ⑤ — 라이브러리 env는 lib_env로, 목록 밖은 모델 밖
            doc_m, rep_m = M.convert(
                {
                    "TZ": "Asia/Seoul",
                    "OMP_NUM_THREADS": "2",
                },
                app_classes(),
            )
            check(
                f"migrate C-35·C-45 ⑤: 옛 별칭 옮김·라이브러리 env {rep_m['옛 이름 옮김']} {rep_m['라이브러리 env']}",
                _peek(doc_m, "common.runtime.lib_env") == {"OMP_NUM_THREADS": "2", "TZ": "Asia/Seoul"}
                and not rep_m["옛 이름 옮김"],  # 10-29: 옛 별칭(QA_CHAT_DECOMPOSE·SYNTHETIC_TRUTH)은 기능과 함께 지움
            )
            # 사용자 10-29 — 지운 칸 synthetic_truth(옛 migrate C-35가 서버 파일에 옮겨 둠)는 경고만 하고 무시 · 다른 모르는 칸은 그대로 거부
            from common.config.settings import CommonModelsGuard

            _g = CommonModelsGuard.model_validate({"synthetic_truth": "/t.json", "budget_usd": 0.1})
            try:
                CommonModelsGuard.model_validate({"synthetic_truthx": "/t.json"})
                _typo_rejected = False
            except ValueError:
                _typo_rejected = True
            check("지운 칸 synthetic_truth: 시작 거부 대신 무시 · 오타 칸은 거부", _g.budget_usd == 0.1 and _typo_rejected)
            # 사용자 10-29 — 기능 삭제(OpenViking·재순위·질문 분해·graph 검색·파싱 판단 에이전트 등)로 지운 칸·절도 옛 파일에 남아 있으면 무시
            _old = {
                "common": {"connections": {"openviking": {"url": "http://x:1933"}}, "models": {"rerank": {"model": "m"}}},
            }
            if "pipeline" in app_classes():
                _old["pipeline"] = {
                    "paths": {"mineru_bin": "mineru", "paddle_python": "/p", "soffice_candidates": ["a"]},
                    "transform": {"agent": {"enabled": "shadow"}},
                    "load": {"structure_target": "pg"},
                    "eval": {"phase_report_legacy": False},
                    "dev": {"parse_agent_fake": False},
                    "connections": {"openviking": {"root": "r"}, "graphiti": {"neo4j_uri": "bolt://x"}},
                }
            if "mcp" in app_classes():
                _old["mcp"] = {
                    "output": {"list_docs_max": 200},
                    "search": {
                        "rerank": {"mode": "off"},
                        "graph": {"concept_per": 1},
                        "decompose": True,
                        "decompose_llm": True,
                        "ov_search_path": "/x",
                    },
                }
            _of = d / "old_removed.yaml"
            import yaml as _yaml

            from common.config import settings as _S

            _of.write_text(_yaml.safe_dump(to_file(_old), allow_unicode=True), encoding="utf-8")
            _loaded = [_S.load(cls, file=_of, environ={}, strict=False) for cls in app_classes().values()]
            check("10-29 지운 칸·절 17개: 옛 설정 파일에 남아도 앱마다 읽힘(경고만)", len(_loaded) == len(app_classes()))
            if (
                "pipeline" in app_classes()
            ):  # B-3(VS7e2) — 서버 env 파일의 GOLD_DIR는 호스트 칸에만(앱 칸 비움 → 이미지 안 /data/gold), PC 파일은 두 칸
                gs, gr = M.convert({"RUN_ENV": "dev", "GOLD_DIR": "/srv/gold"}, app_classes())
                gp, _ = M.convert({"RUN_ENV": "local", "GOLD_DIR": "/pc/gold"}, app_classes())
                check(
                    "migrate B-3: 서버 env 파일 GOLD_DIR → pipeline.host.gold_dir만 · PC 파일은 앱·호스트 두 칸",
                    _peek(gs, "pipeline.host.gold_dir") == "/srv/gold"
                    and _peek(gs, "pipeline.paths.gold_dir") is None
                    and gr["호스트 칸만"] == ["GOLD_DIR"]
                    and _peek(gp, "pipeline.paths.gold_dir") == "/pc/gold",
                )
            lb = d / "lib.yaml"
            lb.write_text(
                _new("common:\n  runtime:\n    lib_env:\n      TZ: Asia/Seoul\n      HF_HUB_OFFLINE: 1\n      OMP_NUM_THREADS: 02\n"),
                encoding="utf-8",
            )
            lbad = d / "libbad.yaml"
            lbad.write_text(_new("common:\n  runtime:\n    lib_env:\n      PG_PASSWORD: dummy-lib\n"), encoding="utf-8")
            ok_l, msg_l = raises(lambda: load(_TApp, file=lbad, environ={}, strict=False), "허용 목록 밖", "PG_PASSWORD")
            check(
                "lib_env(C-45 ⑤): 쓴 글자 그대로(1·02) · 허용 목록 밖 이름은 거부(이름만, 값 없음)",
                load(_TApp, file=lb, environ={}, strict=False).common.runtime.lib_env
                == {"TZ": "Asia/Seoul", "HF_HUB_OFFLINE": "1", "OMP_NUM_THREADS": "02"}
                and ok_l
                and "dummy-lib" not in msg_l,
            )

    class _TP(Section):
        port: Port | None = F(8765, "X_PORT", "시험")

    def _tp(v):
        try:
            return _TP(port=v).port
        except ValidationError:
            return "오류"

    tp = {v: _tp(v) for v in ("8765", " 8766", "-1", "5.0", "8766x", " ")}
    import yaml

    ty = {v: _tp(yaml.load(f"port: {v}", Loader=_yaml_loader())["port"]) for v in ("8765", "5.0", "true", "'8765'")}
    check(
        f"포트 칸(VS7d U-2): 정수 글자만(앞뒤 공백·부호는 옛 int()처럼) — '5.0'·'8766x'·공백·YAML 5.0·true는 형식 오류 {tp} {ty}",
        tp == {"8765": 8765, " 8766": 8766, "-1": -1, "5.0": "오류", "8766x": "오류", " ": "오류"}
        and ty == {"8765": 8765, "5.0": "오류", "true": "오류", "'8765'": 8765},
    )
    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래(`_S.selftest()`)
    selftest()
