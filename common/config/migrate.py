"""settings.yaml 옮기기 — ① 옛 배치 settings.yaml(최상위 common·pipeline·mcp — op-08 전) → 새 배치(required·역할 절·tuning, common.config.layout),
② 옛 env 파일 → settings.yaml(S7a, refactor_plan 5-2 · D-015 — 결과는 새 배치). 서버 pipeline.env·etl.env·retrieval.env, PC .env.local·validation.env 등.
  · ①(파일 하나, .yaml·.yml): 값은 쓴 글자 그대로 옮긴다(1.10·0123·yes가 바뀌지 않게). 지운 칸(모델 REMOVED — op-08 등)은 "삭제됨",
    모델에 없는 칸은 "모름"으로 이름(옛 자리)만 알리고 새 파일에 넣지 않는다. 덮기 파일의 base·overrides는 그대로 둔다.
  · 여러 파일을 주면 뒤 파일이 앞 파일 값을 덮는다(지금 셸 `. a; . b`와 같음) — 단 틀의 자리표시는 앞 파일의 실제 값을 덮지 않는다(VS7a2 R-e).
  · 옛 env 이름 → YAML 경로는 앱 설정 모델의 칸 표(settings.walk)로 찾는다. LOCAL_RUN=1은 common.run_env: local로.
  · 같은 env 이름이 앱 칸과 호스트 칸 둘에 있으면(RAG_OUT·GOLD_DIR — T-21) 둘 다에 넣고 보고에 "확인" 표시. 단 HOST_ONLY 이름(GOLD_DIR)은
    서버 env 파일(RUN_ENV가 dev·prd — S7a부터 서버 필수)이면 호스트 칸에만 넣는다 — 옛 컨테이너는 그 값을 받지 않고 이미지 안 자리를 썼다
    (VS7e2 B-3). PC 파일이면 앱이 그 값을 바로 읽었으므로 두 칸 그대로. RUN_ENV가 없는 파일이면 두 칸에 넣되 "확인 필요"로 알린다
    (VS7e3 R-3 — 서버가 RUN_ENV를 셸·systemd로만 주었다면 파일에 RUN_ENV를 적고 다시 옮김, --compare도 확인 필요로 종료 1).
  · env로 남길 이름·스크립트 인자·삭제 후보·모르는 이름은 YAML에 넣지 않고 이름만 보고한다(값은 찍지 않음).
  · 틀의 자리표시 값(`<여기에 기입>`처럼 값 전체가 한글 설명이 든 <…>)은 비운 칸으로 보고 "자리표시"로 이름만 보고한다(빈 틀).
  · 빈 값(`X=`)·형식 변환은 앱 설정 모델 규칙 그대로(settings.Section._normalize — 기본값 있는 칸의 빈 값 = 설정 안 함).
  · 화면 출력은 비밀 칸을 "<가림>"으로 바꾼 YAML. --out으로 파일에 쓸 때만 실제 값이 들어가고 권한은 600(있으면 --force).
사용: python -m common.config.migrate <옛 settings.yaml> [--out <새 파일> [--force]] [--summary]
      python -m common.config.migrate <env 파일>... [--out settings.yaml [--force]] [--summary]
      python -m common.config.migrate --compare <옛 env 파일>... --settings <settings.yaml> [--no-catalog]
  · --compare(S7e1 — 서버 이관 확인, 사용자 10-27 Q7): 옛 실효 값(options.conf 카탈로그 setdefault — 예외 줄 빼고 + env 파일, 뒤 파일이 이김)과
    새 settings.yaml을 설정 모델로 칸마다 견줘 `같음·다름·옛에만·새에만`과 env 이름만 찍는다(값·비밀은 찍지 않음). 옛 값이 모델 기본값과 같고
    새 파일에 그 칸이 없으면 같은 결과라 같음으로 센다. 다름·옛에만이 있으면 종료 코드 1 — 옛 카탈로그 값(sample의 [서버 옛 값]) 옮김을
    놓치지 않게. 모델 밖 이름(env로 남김·삭제 후보·모름)은 settings.yaml로 못 옮기므로 이름만 따로 보고한다. compose 기본값은 전후 같아 넣지 않는다.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from common.config import layout as L
from common.config import settings as S
from common.config.keyscan import NOT_SETTINGS
from common.core.console import utf8_stdout

_KEY = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*=[ \t]*")
MASK = "<가림>"
_PLACEHOLDER = re.compile(r"^<.*[가-힣].*>$")  # 빈 틀의 자리표시(`<여기에 기입>`·`<원본 문서 폴더 절대경로>`) — 한글 설명이 든 <…>만
# 옛 별칭(C-35, 사용자 10-28) — 코드는 더 읽지 않는다. env 파일에서 만나면 새 칸 자리로 옮긴다(새 이름이 같은 파일들에 있으면 새 이름이 이김).
OLD_ALIASES: dict[str, str] = {}  # 10-29: QA_CHAT_DECOMPOSE(분해 삭제)·SYNTHETIC_TRUTH(둘째 잠금 삭제) 별칭 없음
# 서버 env 파일에서는 호스트 칸에만 옮기는 이름(VS7e2 B-3 — 코디네이터 10-28 "옛 실효 값과 같게"): 옛 run_tool.sh가 `-e GOLD_DIR=/data/gold`로
# env_file 값(호스트 경로)을 덮어 컨테이너 앱은 늘 /data/gold를 읽었다 — 앱 칸(pipeline.paths.gold_dir)은 비워 이미지 안 /data/gold 규칙
# (pipeline.config.gold_dir)이 걸리게 한다.
HOST_ONLY = ("GOLD_DIR",)
# RUN_ENV 없는 env 파일의 HOST_ONLY 이름 — 두 칸에 넣되 "확인 필요"로 알린다(VS7e3 R-3: 서버가 RUN_ENV를 셸·systemd로만 주었다면 그 파일은 서버
# 파일인데 판정이 PC로 감 → 파일에 RUN_ENV를 적고 다시 옮김, release-and-patch §5-4).
NO_RUN_ENV = "확인 필요(RUN_ENV 없는 파일 — 서버 파일이면 RUN_ENV를 적고 다시)"

# 서버 compose env_file 규칙(VS7e1 B-3 — 옛 서버 컨테이너가 받던 실효 값을 그대로 옮기려고). 출처: docker compose v2 =
# compose-spec/compose-go `dotenv/parser.go`(extractVarValue·expandEscapes) — 따옴표 없음: 줄 끝까지·` #` 뒤는 주석·뒤 공백 빼고·$ 치환 ·
# 작은따옴표: 글자 그대로(이스케이프·치환 없음, 여러 줄 가능) · 큰따옴표: 이스케이프(\a \b \f \n \r \t \v \" \\ \0nnn, `\$` = 글자 $)를 푼 뒤 $ 치환.
# podman-compose는 python-dotenv `dotenv_values`(같은 따옴표·이스케이프 규칙, 치환은 `${X}`·`${X:-d}`만 — `$X`는 글자 그대로)로 읽어 `$X` 꼴만 갈린다.
# $ 치환 값(같은 파일의 앞 키 또는 compose를 띄운 셸 env)은 이 도구가 확실히 알 수 없어, 이스케이프를 풀었거나 $가 든 값은 이름만 "확인 필요"로 낸다.
_ESC = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", '"': '"', "\\": "\\", "$": "$"}
_VAR = re.compile(r"\$(?:\$|\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?+])([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))")


def _unescape(s):
    """큰따옴표 안 이스케이프(compose-go expandEscapes) — 모르는 꼴(\\x 등)은 그대로. `\\$`는 치환하지 않는 $로 표시(\\0 글자)."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "0":
                m = re.match(r"0([0-7]{0,3})", s[i + 1 :])
                out.append(chr(int(m.group(1) or "0", 8)))
                i += 1 + len(m.group(0))
                continue
            if n in _ESC:
                out.append("\0" if n == "$" else _ESC[n])
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _expand(s, known):
    """$ 치환(compose-go expandVariables 꼴): `$$` → $, `${X}`·`$X` → 앞 키 값(없으면 빈 글자 — compose도 빈 글자로 치환),
    `${X:-d}`·`${X-d}` 기본값. 반환 (값, 모른 이름 목록)."""
    missing = []

    def sub(m):
        if m.group(0) == "$$":
            return "$"
        name = m.group(1) or m.group(4)
        op, word = m.group(2), m.group(3) or ""
        have = name in known
        val = known.get(name, "")
        if op in (":-", "-"):
            return val if (have and (val or op == "-")) else word
        if op in (":+", "+"):
            return word if (have and (val or op == "+")) else ""
        if not have:
            missing.append(name)
        return val

    return _VAR.sub(sub, s), missing


def parse_env_text(text, known=None):
    """(값 사전, 확인 필요 {이름: 이유}) — 위 compose env_file 규칙. known = 치환에 쓸 앞 값(여러 파일이면 앞 파일들 — 셸 env는 넣지 않음).
    같은 키는 뒤 줄이 이김."""
    out, notes = {}, {}
    known = dict(known or {})
    i, n = 0, len(text)
    while i < n:
        j = text.find("\n", i)
        j = n if j < 0 else j
        line = text[i:j]
        if not line.strip() or line.lstrip().startswith("#"):
            i = j + 1
            continue
        m = _KEY.match(line)
        if not m:
            i = j + 1
            continue
        key, start = m.group(1), i + m.end()
        q = text[start : start + 1]
        why = []
        if q in ("'", '"'):
            k, esc = start + 1, False  # 닫는 따옴표까지(여러 줄 가능 — 앞에 \가 붙은 따옴표는 건너뜀)
            while k < n and (text[k] != q or esc):
                esc = (not esc) and text[k] == "\\"
                k += 1
            raw = text[start + 1 : k]
            nl = text.find("\n", k)
            i = n + 1 if nl < 0 else nl + 1
            if "\n" in raw:
                swallowed = [m.group(1) for m in (_KEY.match(ln) for ln in raw.split("\n")[1:]) if m]
                why.append(
                    "여러 줄" + (f"(값 안에 다음 줄 이름 {' '.join(swallowed)} — 닫는 따옴표가 빠졌거나 \\' 로 끝남?)" if swallowed else "")
                )
            if q == "'":
                val = raw
                if "\\" in raw:
                    why.append("작은따옴표 안 \\(글자 그대로 옮김)")
            else:
                val = _unescape(raw)
                if "\\" in raw:
                    why.append("큰따옴표 이스케이프를 풂")
                val, missing = _expand(val, known) if "$" in val else (val, [])
                if "$" in raw.replace("\\$", ""):
                    why.append("$ 치환" + (f"(모르는 이름 {' '.join(missing)} — compose는 셸 env 값)" if missing else ""))
                val = val.replace("\0", "$")
        else:
            val = line[m.end() :].split(" #", 1)[0].rstrip()
            i = j + 1
            if "$" in val:
                val, missing = _expand(val, known)
                why.append("$ 치환" + (f"(모르는 이름 {' '.join(missing)} — compose는 셸 env 값)" if missing else ""))
        if key == "TRIGGER_PORT":  # 리뷰 S7e2 — 옛 서버 compose가 상주 서비스마다 덮어 상주 컨테이너에는 안 걸리던 이름
            why.append(
                "옛 서버 compose는 서비스마다 TRIGGER_PARSE_PORT·TRIGGER_STRUCTURE_PORT로 덮었음 — 상주 서버 두 개면 parse_port·structure_port를 쓰고 이 칸은 비움 권장"
            )
        out[key] = known[key] = val
        if why:
            notes[key] = " · ".join(why)
        else:
            notes.pop(key, None)
    return out, notes


def read_files(files, notes=None):
    """(env, holders) — 파일마다 자리표시 값을 먼저 걸러 내고 합친다(뒤 파일이 이김). 서버 env + 틀을 함께 넣어도 틀의
    `<…>`가 앞 파일의 실제 값을 지우지 않게(VS7a2 R-e). holders = 끝까지 실제 값이 없는 자리표시 이름.
    notes(사전)를 주면 확인 필요 이름·이유를 채운다(B-3 — 값은 담지 않음)."""
    env, holders = {}, set()
    for f in files:
        vals, why = parse_env_text(Path(f).read_text(encoding="utf-8"), env)
        for key, val in vals.items():
            if _PLACEHOLDER.match(val):
                if key not in env:
                    holders.add(key)
                continue
            env[key] = val
            holders.discard(key)
            if notes is not None:
                if key in why:
                    notes[key] = why[key]
                else:
                    notes.pop(key, None)
    return env, holders


def convert(env, classes, holders=()):
    """(doc, report) — doc은 {common:…, pipeline:…, mcp:…} 글자 값, report는 {분류: [이름…]}. holders: 자리표시만 있던 이름."""
    app_map, host_map = {}, {}
    for cls in classes.values():
        for k, v in S.env_map(cls).items():
            app_map.setdefault(k, set()).add(v)
        for k, v in S.env_map(cls, hosts=True).items():
            host_map.setdefault(k, set()).add(v)
    doc = {}
    report = {
        "yaml": [],
        "확인(앱·호스트 두 칸)": [],
        "호스트 칸만": [],
        NO_RUN_ENV: [],
        "자리표시(비움)": sorted(holders),
        "옛 이름 옮김": [],
        "라이브러리 env": [],
        "env로 남김": [],
        "인자": [],
        "삭제 후보": [],
        "모름": [],
    }
    server_file = (
        env.get("RUN_ENV") in S.SERVER_ENVS
    )  # HOST_ONLY 판정 — 서버 env 파일은 RUN_ENV=dev·prd(S7a부터 필수, C-34) · 그 밖(PC·RUN_ENV 없는 조각 파일)은 앱이 그 값을 바로 읽음
    for key in sorted(env):
        val = env[key]
        if key in OLD_ALIASES:  # C-35 — 옛 별칭은 새 칸 자리로(새 이름이 있으면 새 이름 값)
            new = OLD_ALIASES[key]
            report["옛 이름 옮김"].append(f"{key}→{new}" + ("(새 이름이 있어 버림)" if new in env else ""))
            if new in env:
                continue
            key = new
        if key in S.LIB_ENV_NAMES:  # C-45 ⑤ — 라이브러리 env는 common.runtime.lib_env 사전으로(컨테이너 entrypoint가 env로 냄)
            lib = S._peek(doc, "common.runtime.lib_env") or {}
            lib[key] = val
            L.set_path(doc, "common.runtime.lib_env", lib)
            report["라이브러리 env"].append(key)
            continue
        if key == "LOCAL_RUN":
            if val == "1":
                L.set_path(doc, "common.run_env", "local")
            report["env로 남김"].append(key + "(→ common.run_env)")
            continue
        if key in HOST_ONLY and server_file and host_map.get(key):
            for p in sorted(host_map[key]):
                L.set_path(doc, p, val)
            report["호스트 칸만"].append(key)
            continue
        paths = sorted(app_map.get(key, set()) | host_map.get(key, set()))
        if key in HOST_ONLY and not env.get("RUN_ENV") and host_map.get(key):
            report[NO_RUN_ENV].append(key)  # VS7e3 R-3 — 서버 파일인지 모름(RUN_ENV를 셸·systemd로만 준 서버면 호스트 칸만이어야 함)
        if paths:
            for p in paths:
                L.set_path(doc, p, val)
            report["확인(앱·호스트 두 칸)" if len(paths) > 1 else "yaml"].append(key)
            continue
        kind = NOT_SETTINGS.get(key, ("모름", ""))[0]
        report.get(kind, report["모름"]).append(key)
    return doc, report


def _removed(model, prefix=""):
    """지운 칸(Section.REMOVED)의 모델 경로 — 옛 파일에 남아 있으면 "삭제됨"으로 알린다."""
    out = {prefix + n for n in getattr(model, "REMOVED", ())}
    for name, f in model.model_fields.items():
        sub = S._section_type(f.annotation)
        if sub is not None:
            out |= _removed(sub, f"{prefix}{name}.")
    return out


def _raw(v):
    """YAML 값을 쓴 글자·꼴 그대로 다시 쓰게(settings._Raw) — 글자는 글자로, 숫자·켜기·날짜는 쓴 표기 그대로."""
    if isinstance(v, S.YamlScalar):
        return str(v) if isinstance(v.value, str) else S._Raw.of(v)
    if isinstance(v, dict):
        return {str(k): _raw(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_raw(x) for x in v]
    return v


def convert_yaml(path, classes, secrets=True):
    """옛 배치 settings.yaml → (새 배치 사전, 보고 {"삭제됨": [옛 자리], "모름": [옛 자리], "칸": n}). secrets=False면 비밀 값은 MASK."""
    raw = S.read_yaml(path)
    extra = {k: raw.pop(k) for k in S.OVERLAY_KEYS if k in raw}
    if raw and not L.is_old(raw):
        raise S.SettingsError(f"이미 새 배치(또는 옛 배치가 아님): {path}")
    leaves, removed = {}, set()
    for cls in classes.values():
        leaves.update({p: f for p, f, _ in S.walk(cls)})
        removed |= _removed(cls)
    doc, report = {}, {"삭제됨": [], "모름": [], "칸": 0}

    def walk(d, prefix):
        for k, v in d.items():
            p = f"{prefix}{k}"
            if p in leaves:
                if v is not None:
                    L.set_path(doc, p, v if secrets or not S.is_secret(leaves[p]) else MASK)
                    report["칸"] += 1
            elif p in removed:
                report["삭제됨"].append(p)
            elif isinstance(v, dict) and any(x.startswith(p + ".") for x in leaves):
                walk(v, p + ".")
            elif v is not None:
                report["모름"].append(p)

    walk(raw, "")
    return {**_raw(extra), **L.to_file(_raw(doc))}, report


def dump_yaml(doc, origin="옛 배치에서 새 배치(op-08 ②)로 바꿈"):
    import yaml

    head = f"# settings.yaml — common.config.migrate가 {origin}. 칸 설명은 저장소 settings.sample.yaml\n"
    return head + yaml.dump(doc, Dumper=S._raw_dumper(), allow_unicode=True, sort_keys=False, default_flow_style=False)


def run_yaml(a, classes):
    if not {"pipeline", "mcp"} <= set(classes):  # 이미지 하나엔 다른 앱 모델이 없어 그 칸을 "모름"으로 버림 — 코드 폴더(두 앱 다)에서만
        print("[migrate] pipeline·mcp 설정 모델이 다 있는 코드에서 실행(저장소·코드 폴더 — 이미지 하나 안에서는 안 됨)", file=sys.stderr)
        return 2
    try:
        doc, report = convert_yaml(a.files[0], classes, secrets=bool(a.out))
    except S.SettingsError as e:
        print(f"[migrate] {e}", file=sys.stderr)
        return 2
    print(f"[migrate] 옛 배치 → 새 배치(op-08 ②): 옮긴 칸 {report['칸']}개", file=sys.stderr)
    for kind in ("삭제됨", "모름"):
        if report[kind]:
            print(f"  {kind} {len(report[kind])}(새 파일에 넣지 않음): {' '.join(report[kind])}", file=sys.stderr)
    if a.out:
        write_private(a.out, dump_yaml(doc), a.force)
        print(f"[migrate] 씀: {a.out} (권한 600)", file=sys.stderr)
    elif not a.summary:
        print(dump_yaml(doc), end="")
    return 0


def typed(doc, classes):
    """글자 값을 모델로 검증해 형식 있는 값으로(숫자·켜기·목록) — 각 앱 뿌리로 따로 검증하고 합친다. 비밀은 SecretStr 그대로."""
    out = {}
    for name, cls in classes.items():
        part = {k: doc[k] for k in ("common", name) if k in doc}
        st = S.load(cls, file=os.devnull, data=part, environ={}, strict=False)
        for path, _f, _ in S.walk(cls):
            if path.split(".", 1)[0] in part and S._is_set(st, path):
                L.set_path(out, path, S._get(st, path))
    return out


def plain(doc, secrets):
    if isinstance(doc, dict):
        return {k: plain(v, secrets) for k, v in doc.items()}
    if isinstance(doc, S.SecretStr):
        return doc.get_secret_value() if secrets else MASK
    if isinstance(doc, Path):
        return str(doc)
    return doc


def dump(doc):
    return dump_yaml(L.to_file(doc), "옛 env 파일에서 만듦(새 배치 — op-08 ②)")


def write_private(path, text, force=False):
    """권한 600으로 새로 씀(있으면 force일 때만 — 덮기 전 지움)."""
    p = Path(path)
    if p.exists():
        if not force:
            raise FileExistsError(f"{p} 있음 — 덮으려면 --force")
        p.unlink()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if os.name != "nt":
        os.chmod(p, 0o600)


def catalog_values():
    """옛 옵션 카탈로그(options.conf — S7e2에 지움)가 서버 env에 채우던 값 중 모델 기본값과 결과가 다른 칸 — sample의 [서버 옛 값] 표
    (common.config.sample.CATALOG_VALUES — S7e1 Q6 a). 나머지 카탈로그 값은 모델 기본값과 결과가 같아 넣지 않아도 대조가 같다."""
    from common.config.sample import CATALOG_VALUES

    return dict(CATALOG_VALUES)


def _settings_doc(path, classes):
    """settings.yaml → {경로: 형식 있는 값} — 앱마다 그 앱 뿌리로 읽음(호스트 칸 포함, 적은 칸만)."""
    doc = {}
    for name, cls in classes.items():
        st = S.load(cls, file=path, environ={}, strict=False, require_file=False)
        for p, _f, _ in S.walk(cls):
            if p.split(".", 1)[0] in ("common", name) and S._is_set(st, p):
                doc[p] = S._get(st, p)
    return doc


def _flat(doc, prefix=""):
    out = {}
    for k, v in doc.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[prefix + k] = v
    return out


def compare(files, settings_path, classes, catalog=True, notes=None):
    """(결과 {분류: [(env 이름, 경로)]}, 모델 밖 이름) — 위 --compare 설명. 값은 돌려주지 않는다. notes(사전)를 주면 env 파일의
    확인 필요 이름(이스케이프·$ — B-3)을 채운다."""
    env = dict(catalog_values()) if catalog else {}
    files_env, _ = read_files(files, notes)
    env.update(files_env)
    old_doc, report = convert(env, classes)
    old = _flat(plain(typed(old_doc, classes), True))
    new = _flat(plain(_settings_doc(settings_path, classes), True))
    fields = {}
    for cls in classes.values():
        for p, f, _ in S.walk(cls):
            fields.setdefault(p, f)
    out = {"같음": [], "다름": [], "옛에만": [], "새에만": []}
    for p in sorted(set(old) | set(new)):
        f = fields.get(p)
        name = S.env_name(f) if f else p
        default = plain(f.default, True) if f is not None else None
        if p in old and p in new:
            kind = "같음" if old[p] == new[p] else "다름"
        elif p in old:
            from common.config.sample import blank_matters  # VS7e1 R-4 — ''가 비운 칸과 같은 결과인 칸은 같음

            kind = "같음" if old[p] == default or (old[p] == "" and f is not None and not blank_matters(f)) else "옛에만"
        else:
            kind = "같음" if new[p] == default else "새에만"
        out[kind].append((name, p))
    if notes is not None:
        for old_name, new_name in OLD_ALIASES.items():  # 옛 별칭의 확인 필요 표시는 새 이름으로(옮긴 칸 이름으로 보고)
            if old_name in notes and new_name not in files_env:
                notes[new_name] = notes.pop(old_name)
    if notes is not None:
        for name in report[NO_RUN_ENV]:
            notes[name] = "env 파일에 RUN_ENV 없음 — 서버 파일이면 RUN_ENV를 적고 다시 옮김(서버는 호스트 칸만, release-and-patch §5-4)"
    not_moved = {k.split("(", 1)[0] for kind in ("env로 남김", "인자", "삭제 후보", "모름") for k in report.get(kind, [])}
    return out, sorted(not_moved & set(files_env)), sorted(not_moved - set(files_env))


def run_compare(a, classes):
    notes = {}
    try:
        res, outside, cat_only = compare(a.files, a.settings, classes, catalog=not a.no_catalog, notes=notes)
    except S.SettingsError as e:
        print(f"[compare] {e}", file=sys.stderr)
        return 2
    n = {k: len(v) for k, v in res.items()}
    src = "options.conf 카탈로그 + " if not a.no_catalog else ""
    print(
        f"[compare] 옛({src}env 파일 {len(a.files)}개) ↔ 새(settings.yaml) — 같음 {n['같음']} · 다름 {n['다름']} · "
        f"옛에만 {n['옛에만']} · 새에만 {n['새에만']} (값은 찍지 않음)"
    )
    for kind in ("다름", "옛에만", "새에만"):
        if res[kind]:
            print(f"  {kind} {n[kind]}:")
            for name, p in res[kind]:
                print(f"    {name} ({p})")
    if outside:
        print(
            f"  모델 밖 — env 파일의 이름 중 settings.yaml로 옮기지 않는 것(env로 남김·인자·삭제 후보·모름) {len(outside)}: {' '.join(outside)}"
        )
    if cat_only:
        print(f"  모델 밖 — 옛 카탈로그만 채우던 이름 {len(cat_only)}(옮길 자리 없음 — 이미지 ENV·코드 기본값): {' '.join(cat_only)}")
    if notes:  # B-3 — 옛 compose env_file 규칙으로 읽은 값(이스케이프를 풂·$ 치환)은 옛 서버 컨테이너가 실제로 받은 값과 사람이 한 번 견줌
        print(
            f"  확인 필요 {len(notes)} — 옛 env 파일 값을 compose env_file 규칙(이스케이프·$ 치환)으로 읽음, 서버 컨테이너가 받던 값과 같은지 확인"
            "(docker compose v2와 podman-compose는 $X 꼴만 다름):"
        )
        for name in sorted(notes):
            print(f"    {name}: {notes[name]}")
    return 1 if n["다름"] or n["옛에만"] or notes else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--summary", action="store_true", help="YAML은 찍지 않고 수만")
    ap.add_argument("--compare", action="store_true", help="옛 env 파일(+options.conf)과 --settings 파일을 칸마다 견줌(값 안 찍음)")
    ap.add_argument("--settings", help="--compare의 새 settings.yaml")
    ap.add_argument("--no-catalog", action="store_true", help="--compare에서 옛 options.conf 값을 넣지 않음")
    a = ap.parse_args(argv)
    if a.compare:
        if not a.settings:
            ap.error("--compare에는 --settings <settings.yaml>")
        return run_compare(a, S.app_classes())
    classes = S.app_classes()
    if len(a.files) == 1 and a.files[0].endswith((".yaml", ".yml")):
        return run_yaml(a, classes)
    notes = {}
    env, holders = read_files(a.files, notes)
    doc, report = convert(env, classes, holders)
    try:
        doc = typed(doc, classes)
    except S.SettingsError as e:
        print(f"[migrate] {e}", file=sys.stderr)
        return 2
    print(f"[migrate] 읽은 키 {len(env)}개 — 앱 모델 {'·'.join(classes) or '없음'}", file=sys.stderr)
    if not (doc.get("common") or {}).get("run_env"):
        print("  [주의] RUN_ENV 없음 — 만든 파일의 required.env.run_env에 local·dev·prd를 적어야 앱이 시작함(D-028 ②)", file=sys.stderr)
    for kind, names in report.items():
        if names:
            shown = "" if kind == "yaml" else ": " + " ".join(names)
            print(f"  {kind} {len(names)}{shown}", file=sys.stderr)
    for name in sorted(notes):  # B-3 — 값은 찍지 않고 이름·이유만
        print(f"  확인 필요 {name}: {notes[name]} — 옛 서버 컨테이너가 받던 값과 같은지 --compare 뒤 확인", file=sys.stderr)
    if a.out:
        write_private(a.out, dump(plain(doc, True)), a.force)
        print(f"[migrate] 씀: {a.out} (권한 600)", file=sys.stderr)
    elif not a.summary:
        print(dump(plain(doc, False)), end="")
    return 0


if __name__ == "__main__":
    utf8_stdout(errors=None)
    raise SystemExit(main())
