"""settings.yaml 호스트 칸 → 셸 env 줄(load_settings.sh load_settings가 부름) — 호스트 python은 PyYAML만 있으면 된다.
칸 목록·옛 env 이름·종류는 host_settings.tsv(설정 모델에서 자동 생성 — `PYTHONPATH=. python deploy/release/gen_host_keys.py`), 파일 배치 → 모델 배치는
common/config/layout.py(표준 라이브러리만)를 파일로 읽어 바꾼다. run_pipeline.py도 이 파일을 파일로 읽어 같은 함수(layout·get·table_rows·load_model)를 쓴다. 값 검증은 하지 않는다(컨테이너 안 앱이 같은 파일을 읽어 검증).
YAML에 적은 값만 낸다(비운 칸·없는 칸은 안 냄 — compose·스크립트 기본값이 걸림). 비밀 칸은 표에 없다. 값은 찍지 않는다(요청한 줄만 표준 출력).
사용: python3 deploy/host/scripts/settings_to_env.py [--format sh|env] [--file settings.yaml] [<절>...]   (절 예: pipeline.host common.host — 없으면 표 전부)
"""

import argparse
import functools
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # 코드 폴더(PC 저장소 · 서버 sbl_data_parsing-<판>)
TABLE = HERE / "host_settings.tsv"


class NotSections(ValueError):
    """settings.yaml 맨 위가 절 사전이 아님(부르는 쪽이 자기 안내로 바꿈)."""


@functools.cache
def layout():
    f = ROOT / "common" / "config" / "layout.py"  # 코드 폴더 = 저장소 트리
    if f.is_file():
        spec = importlib.util.spec_from_file_location("settings_layout", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise SystemExit("[settings_to_env] common/config/layout.py 없음 — 코드 폴더 안의 deploy/host/scripts에서 부를 것")


def get(doc, path):
    for k in path.split("."):
        doc = doc.get(k) if isinstance(doc, dict) else None
    return doc


def render(value, kind):
    """옛 env 글자 — export.render와 같은 규칙(켜기 1/0, 4.0 → 4, 목록은 쉼표·공백). 비운 글자는 None(설정 안 함)."""
    if isinstance(value, (list, tuple)):
        if kind == "json":
            return json.dumps(value, ensure_ascii=False)
        return (" " if kind == "words" else ",").join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    s = str(value)
    if not s.strip() or s.strip() in _NULL:  # 비운 글자·YAML 널 — 앱처럼 "값 없음"(compose 기본값이 걸림)
        return None
    if kind == "bool":
        b = s.strip().lower()
        if b in ("1", "true", "yes", "on"):
            return "1"
        if b in ("0", "false", "no", "off"):
            return "0"
        raise ValueError("켜기 칸은 true·false")
    if kind == "num" and re.fullmatch(r"\s*-?\d+\.0+\s*", s):
        return s.strip().split(".")[0]  # 4.0 → 4(compose cpus·옛 env 글자와 같게)
    return s


def table_rows(table=TABLE):
    """호스트 칸 표의 줄 — [모델 경로, 옛 env 이름, 종류, (const면) 값]. 빈 줄·# 줄은 뺀다."""
    return [row.split("\t") for row in Path(table).read_text(encoding="utf-8").splitlines() if row and not row.startswith("#")]


def load_model(path):
    """settings.yaml을 쓴 글자 그대로 읽어(BaseLoader — 0123이 83이 되지 않게 + 같은 칸 두 번 거부) 모델 배치 사전으로 바꾼다.
    오류는 그대로 올린다 — ImportError(PyYAML 없음)·OSError·yaml.YAMLError·NotSections·layout().LayoutError."""
    import yaml

    lay = layout()
    loader = lay.reject_dup_keys(type("Loader", (yaml.BaseLoader,), {}))
    doc = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=loader) or {}
    if not isinstance(doc, dict):
        raise NotSections("맨 위는 절 사전이어야 함")
    return lay.to_model(_nulls(doc), str(path))


_NULL = ("~", "null", "Null", "NULL")


def _nulls(v):
    """글자 로더라 YAML 널(`null`·`~`)과 빈 칸(`이름:` — BaseLoader는 '')도 글자로 온다 — 앱처럼 None(비움)으로 바꾼다
    (sample의 null·빈 칸을 그대로 복사해도 비운 것과 같게). 글자 로더는 `''`와 빈 칸을 가르지 못해 `''`도 비움이다."""
    if isinstance(v, dict):
        return {k: _nulls(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_nulls(x) for x in v]
    return None if isinstance(v, str) and (not v.strip() or v.strip() in _NULL) else v


def load_or_error(path):
    """(모델 배치 사전, None) 또는 ({}, 안내 글자) — 값·줄 글자는 안내에 넣지 않는다(YAML 오류는 문제 이름만)."""
    try:
        import yaml
    except ImportError:
        return {}, "호스트 python에 PyYAML이 없음 — pip install pyyaml(refactor.md C-09)"
    lay = layout()
    try:
        return load_model(path), None
    except OSError as e:
        return {}, f"설정 파일을 읽지 못함: {path} ({e.strerror})"
    except yaml.YAMLError as e:
        dup = getattr(e, "problem", "") or ""
        return {}, f"설정 파일 YAML 형식 오류: {path}" + (f" — {dup}" if dup.startswith(lay.DUP_KEY) else "")
    except NotSections:
        return {}, f"설정 파일 맨 위는 절(required·common·… tuning) 사전이어야 함: {path}"
    except lay.LayoutError as e:
        return {}, str(e)


def lines(doc, sections, fmt="sh"):
    out = []
    for path, name, kind, *const in table_rows():
        if sections and not any(path == s or path.startswith(s + ".") for s in sections):
            continue
        v = const[0] if kind == "const" else get(doc, path)  # const = 컨테이너 안 약속 경로(settings.IMAGE_PATHS — 설정 파일과 무관)
        if v is None:
            continue
        try:
            s = render(v, kind)
        except ValueError as e:
            raise ValueError(f"{name}: {e}") from None
        if s is None:
            continue
        if "\n" in s:
            raise ValueError(f"{name}: 여러 줄 값은 env 줄로 낼 수 없음")
        if fmt == "sh":
            out.append(f"export {name}='" + s.replace("'", "'\\''") + "'")
        elif "$" in s:
            raise ValueError(f"{name}: 값에 $가 있어 compose env 파일 줄로 낼 수 없음(compose가 다시 치환) — --format sh로 셸 env에")
        else:
            out.append(f"{name}={s}")
    return out


ENV_PAIRS = (  # .env(compose-redis.yml·compose-pgvector.yml) 이름 → settings.yaml 모델 경로 — 둘이 같아야 앱이 붙음
    ("REDIS_PASSWORD", "common.connections.redis.redis_password"),
    ("PG_USER", "common.connections.pg.user"),
    ("PG_DB", "common.connections.pg.db"),
    ("PG_PASSWORD", "common.connections.pg.password"),
)


def env_mismatch(doc, env_file):
    """.env와 settings.yaml이 다른(또는 빈) 이름 목록 — 값은 돌려주지 않는다."""
    env = {}
    for line in Path(env_file).read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and not k.lstrip().startswith("#"):
            env[k.strip()] = v.strip()
    return [n for n, p in ENV_PAIRS if not env.get(n) or env.get(n) != str(get(doc, p) or "")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("sections", nargs="*", help="모델 경로 절(없으면 표 전부 — 호스트 칸 모두)")
    ap.add_argument("--file", help="설정 파일(없으면 SETTINGS_FILE)")
    ap.add_argument("--format", choices=("env", "sh"), default="env")
    ap.add_argument("--check-env", help=".env가 settings.yaml과 같은지만 확인(다른 이름만 찍음 — host_ctl.sh check)")
    a = ap.parse_args(argv)
    path = a.file or os.environ.get("SETTINGS_FILE")  # env 남김 — 설정 파일 자리 신호(load_settings가 정함)
    if not path:
        print("[settings_to_env] 설정 파일 없음 — --file 또는 SETTINGS_FILE", file=sys.stderr)
        return 2
    doc, err = load_or_error(path)
    if not err and a.check_env:
        try:
            bad = env_mismatch(doc, a.check_env)
        except OSError:
            print(f"[settings_to_env] .env를 읽지 못함: {a.check_env}", file=sys.stderr)
            return 2
        if bad:
            print("[settings_to_env] .env가 settings.yaml과 다름(또는 빔): " + " ".join(bad), file=sys.stderr)
            return 1
        print("[settings_to_env] .env = settings.yaml(" + " ".join(n for n, _ in ENV_PAIRS) + ")")
        return 0
    try:
        out = [] if err else lines(doc, a.sections, a.format)
    except ValueError as e:
        err = f"설정 파일 값 오류({path}): {e}"
    if err:
        print(f"[settings_to_env] {err}", file=sys.stderr)
        return 2
    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
