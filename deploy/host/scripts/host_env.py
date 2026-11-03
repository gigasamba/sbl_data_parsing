"""settings.yaml 호스트 칸 → 셸 env 줄(settings_env.sh load_settings가 부름) — 호스트 python은 PyYAML만 있으면 된다(사용자 11-02 — 옛 이미지 안 export 길 지움).
칸 목록·옛 env 이름·종류는 host_keys.tsv(설정 모델에서 자동 생성 — `PYTHONPATH=. python deploy/release/hostkeys.py`), 파일 배치 → 모델 배치는
common/config/layout.py(표준 라이브러리만 — run_docs.py와 같은 길)를 파일로 읽어 바꾼다. 값 검증은 하지 않는다(컨테이너 안 앱이 같은 파일을 읽어 검증).
YAML에 적은 값만 낸다(비운 칸·없는 칸은 안 냄 — compose·스크립트 기본값이 걸림). 비밀 칸은 표에 없다. 값은 찍지 않는다(요청한 줄만 표준 출력).
사용: python3 deploy/host/scripts/host_env.py [--format sh|env] [--file settings.yaml] [<절>...]   (절 예: pipeline.host common.host — 없으면 표 전부)
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # 배치 루트(PC 저장소 · 서버 live/)


def _layout():
    f = ROOT / "common" / "config" / "layout.py"  # 코드 폴더 = 저장소 트리(옛 app/deploy 배치는 11-03 지움)
    if f.is_file():
        spec = importlib.util.spec_from_file_location("settings_layout", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    raise SystemExit("[host_env] common/config/layout.py 없음 — 코드 폴더 안의 deploy/host/scripts에서 부를 것")


def _get(doc, path):
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
    if not s.strip() or s.strip() in (
        "~",
        "null",
        "Null",
        "NULL",
    ):  # 글자 로더라 YAML 널도 글자로 옴 — 앱처럼 "값 없음"(compose 기본값이 걸림)
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


def lines(doc, sections, fmt="sh"):
    out = []
    for row in (HERE / "host_keys.tsv").read_text(encoding="utf-8").splitlines():
        if not row or row.startswith("#"):
            continue
        path, name, kind, *const = row.split("\t")
        if sections and not any(path == s or path.startswith(s + ".") for s in sections):
            continue
        v = const[0] if kind == "const" else _get(doc, path)  # const = 컨테이너 안 약속 경로(settings.IMAGE_PATHS — 설정 파일과 무관)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("sections", nargs="*", help="모델 경로 절(없으면 표 전부 — 호스트 칸 모두)")
    ap.add_argument("--file", help="설정 파일(없으면 SETTINGS_FILE)")
    ap.add_argument("--format", choices=("env", "sh"), default="env")
    a = ap.parse_args(argv)
    path = a.file or os.environ.get("SETTINGS_FILE")  # env 남김 — 설정 파일 자리 신호(load_settings가 정함)
    if not path:
        print("[host_env] 설정 파일 없음 — --file 또는 SETTINGS_FILE", file=sys.stderr)
        return 2
    try:
        import yaml
    except ImportError:
        print("[host_env] 호스트 python에 PyYAML이 없음 — pip install pyyaml(refactor.md C-09)", file=sys.stderr)
        return 2
    lay = _layout()
    try:
        loader = lay.reject_dup_keys(type("Loader", (yaml.BaseLoader,), {}))  # 글자 그대로(0123이 83이 되지 않게) + 같은 칸 두 번 거부
        doc = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=loader) or {}
        if not isinstance(doc, dict):
            raise ValueError("맨 위는 절 사전이어야 함")
        out = lines(lay.to_model(doc, str(path)), a.sections, a.format)
    except (OSError, yaml.YAMLError, ValueError, lay.LayoutError) as e:
        why = e.strerror if isinstance(e, OSError) else (getattr(e, "problem", "") or "") if isinstance(e, yaml.YAMLError) else str(e)
        print(f"[host_env] 설정 파일을 읽지 못함({path}): {why}", file=sys.stderr)  # YAML 오류는 문제 이름만(값·줄 글자는 안 찍음)
        return 2
    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
