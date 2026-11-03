"""EDW 조인 사슬 파일 읽기·검사(pl-29·pl-52 — 사용자 11-02·11-03) — 두 앱이 함께 쓴다: 적재(pipeline/load/edw_meta.py — 사슬을 따라 EDW를
읽음)와 검색 MCP(거르기 이름 → attrs 키, 근거 키). 파일 꼴은 resources/config/edw_chain.yaml 머리 주석(모든 원천이 같은 꼴 — steps·fields·
client_edw·created). 이름은 SQL 글자에 들어가므로 여기서 검사하고, 값은 늘 바인딩한다. 틀리면 ValueError(어디가 왜 틀렸는지 모두)."""

import re
from pathlib import Path

from common.core.paths import RES_ROOT
from common.store.db.models import search_tables as ST

CHAIN_FILE = RES_ROOT / "config" / "edw_chain.yaml"
FILE = "file"  # 열쇠 — 문서 원본 경로(FileStorageMap.s3_key = gold doc.file_path)
ENTITY_COLS = ("Id", "Type", "Class")  # sfdc_entity 단계가 내는 칸
TYPES = ("text", "date", "flag")
# 검색 거르기 이름 중 사슬이 쓸 수 없는 것 — 고정 거르기·doc_class(적재가 쓰는 attrs 키 — LOAD_ATTRS)
RESERVED_FILTERS = ("source_system", "client", "client_like", "created_since", "created_until", "FAQ_group", "attrs", "question", "k")
_FIXED = set(ST.doc_columns("other")) - {ST.ATTRS}  # attrs 키로 쓸 수 없는 이름(고정 칸)
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")
_PREFIX = re.compile(r"[0-9A-Za-z]{3}")
_STEP_KEYS = {"name", "table", "on", "when", "where", "latest", "optional", "tz", "sfdc_entity"}
_FIELD_KEYS = {"from", "filter", "evidence", "type", "max"}


def load(path=None):
    """사슬 파일 읽기 + 검사 → dict. path 없으면 기본 CHAIN_FILE. 파일이 없거나 YAML이 깨져도 ValueError(기본 파일로 조용히 돌아가지 않음)."""
    import yaml

    class Loader(yaml.SafeLoader):  # YAML 1.1의 on/off/yes/no 참거짓 읽기를 끔(`on:` 칸이 True가 되지 않게) — true/false만
        yaml_implicit_resolvers = {
            k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"] for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }

    Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))
    path = Path(path) if path else CHAIN_FILE
    try:
        c = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)  # SafeLoader 바탕(참거짓 규칙만 좁힘)
    except OSError as e:
        raise ValueError(
            f"[edw_chain] 사슬 설정 파일을 못 읽음({path}): {type(e).__name__} — 설정의 edw_chain 경로를 확인(비우면 기본 파일)"
        ) from e
    except yaml.YAMLError as e:
        raise ValueError(f"[edw_chain] 사슬 설정 YAML 오류({path}): {e}") from e
    errs = check(c)
    if errs:
        raise ValueError(f"[edw_chain] 사슬 설정 오류({path}): " + "; ".join(errs))
    return c


def refs(r):
    """열쇠 하나(글자) 또는 목록(안쪽 목록 = 한 자리로 합침) → 평평한 열쇠 글자 목록."""
    return [x for a in (r if isinstance(r, list) else [r]) for x in (a if isinstance(a, list) else [a])]


def filters(chain, src):
    """원천의 검색 거르기 이름 → attrs 키(사슬 fields의 filter + 적재가 쓰는 doc_class)."""
    f = {v["filter"]: k for k, v in (chain[src].get("fields") or {}).items() if v.get("filter")}
    return {**f, **{k: k for k in ST.LOAD_ATTRS.get(src, ())}}


def evidence(chain, src):
    """근거 attrs에 내는 키(사슬에서 evidence: true) — 파일 순서."""
    return [k for k, v in (chain[src].get("fields") or {}).items() if v.get("evidence")]


def keys(chain, src):
    """원천의 attrs 키 전부(사슬 fields + 적재가 쓰는 키) — 정렬."""
    return sorted({*(chain[src].get("fields") or {}), *ST.LOAD_ATTRS.get(src, ())})


def check(c):
    """사슬 dict → 오류 글 목록(비면 통과)."""
    if not isinstance(c, dict):
        return ["최상위가 사전(원천: …)이 아님"]
    errs = [f"{s}: 없음" for s in ST.SOURCES if s not in c]
    errs += [f"{s}: 모르는 원천(허용 {', '.join(ST.SOURCES)})" for s in c if s not in ST.SOURCES]
    for src in ST.SOURCES:
        if isinstance(c.get(src), dict):
            errs += _check_src(src, c[src])
        elif src in c:
            errs.append(f"{src}: steps·fields·created 사전이어야 함")
    return errs


def _check_src(src, s):
    errs = [f"{src}.{k}: 모르는 칸(steps·fields·client_edw·created)" for k in s if k not in ("steps", "fields", "client_edw", "created")]
    steps = s.get("steps")
    if not isinstance(steps, list) or not steps:
        return errs + [f"{src}.steps: 단계 목록이 비었거나 목록이 아님"]
    seen = {}  # 앞 단계 이름 → 낼 수 있는 칸(None = 표 — 칸 이름만 검사)
    for i, st in enumerate(steps):
        w = f"{src}.steps[{i}]"
        if not isinstance(st, dict):
            errs.append(f"{w}: 사전이어야 함")
            continue
        errs += [f"{w}.{k}: 모르는 칸" for k in st if k not in _STEP_KEYS]
        name = st.get("name")
        if not isinstance(name, str) or not _ID.fullmatch(name):
            errs.append(f"{w}.name: {name!r} — 영문·숫자·_ 이름")
        elif name in seen:
            errs.append(f"{w}.name: {name} 이름이 겹침")
        if ("table" in st) == ("sfdc_entity" in st):
            errs.append(f"{w}: table 또는 sfdc_entity 중 하나만")
        if "sfdc_entity" in st:
            errs += _ref(st["sfdc_entity"], seen, f"{w}.sfdc_entity", multi=False)
        if "table" in st:
            errs += _check_table(st, w, seen, first=i == 0)
        if isinstance(name, str):
            seen[name] = ENTITY_COLS if "sfdc_entity" in st else None
    fields = s.get("fields") or {}
    if not isinstance(fields, dict):
        return errs + [f"{src}.fields: {{attrs 키: {{from: …}}}} 꼴이어야 함"]
    names = {}
    for k, f in fields.items():
        w = f"{src}.fields.{k}"
        if not isinstance(k, str) or not _ID.fullmatch(k) or k in _FIXED or k == ST.ATTRS or k in ST.LOAD_ATTRS.get(src, ()):
            errs.append(f"{w}: attrs 키로 쓸 수 없는 이름(고정 칸·{', '.join(ST.LOAD_ATTRS.get(src, ())) or '적재 키'} 빼고 영문·숫자·_)")
        if not isinstance(f, dict) or "from" not in f:
            errs.append(f"{w}: {{from: <단계>.<칸>}}이 있어야 함")
            continue
        errs += [f"{w}.{x}: 모르는 칸(from·filter·evidence·type·max)" for x in f if x not in _FIELD_KEYS]
        errs += _ref(f["from"], seen, f"{w}.from", multi=False)
        fl = f.get("filter")
        if fl is not None:
            if not isinstance(fl, str) or not _ID.fullmatch(fl) or fl in RESERVED_FILTERS or fl == "doc_class":
                errs.append(f"{w}.filter: {fl!r} — 영문·숫자·_ 이름(고정 거르기 {', '.join(RESERVED_FILTERS)}·doc_class 빼고)")
            elif fl in names:
                errs.append(f"{w}.filter: {fl} — {src}에서 {names[fl]}와 겹침(원천마다 하나)")
            names.setdefault(fl, k)
        if "evidence" in f and not isinstance(f["evidence"], bool):
            errs.append(f"{w}.evidence: true 또는 false")
        if f.get("type", "text") not in TYPES:
            errs.append(f"{w}.type: {f.get('type')!r} — {'|'.join(TYPES)}")
        if "max" in f and (f.get("type", "text") != "text" or not isinstance(f["max"], int) or isinstance(f["max"], bool) or f["max"] < 1):
            errs.append(f"{w}.max: 양의 정수(type text만)")
    for k in ("client_edw", "created"):
        if k in s:
            errs += _ref(s[k], seen, f"{src}.{k}", multi=False)
        elif k == "created":
            errs.append(f"{src}.created: 없음(등록 시각 — 예 file.created_at)")
    return errs


def _check_table(st, w, seen, first):
    errs = []
    if not isinstance(st["table"], str) or not _TABLE.fullmatch(st["table"]):
        errs.append(f"{w}.table: {st['table']!r} — 스키마.표만")
    on = st.get("on")
    if not isinstance(on, dict) or not on:
        return errs + [f"{w}.on: {{이 표 칸: 열쇠}}이 있어야 함"]
    errs += [f"{w}.on.{k}: 영문·숫자·_ 칸 이름만" for k in on if not isinstance(k, str) or not _ID.fullmatch(k)]
    for k, r in on.items():
        errs += _ref(r, seen, f"{w}.on.{k}", multi=len(on) == 1)
    if first and any(x != FILE for r in on.values() for x in refs(r)):
        errs.append(f"{w}.on: 첫 단계의 열쇠는 file(문서 원본 경로)만")
    if len(on) > 1 and (any(isinstance(r, list) for r in on.values()) or len({str(r).split(".")[0] for r in on.values()}) != 1):
        errs.append(f"{w}.on: 칸이 여럿이면 열쇠가 모두 한 단계의 칸(목록 없이)")
    when = st.get("when")
    if when is not None and (not isinstance(when, dict) or set(when) != {"prefix"} or not _PREFIX.fullmatch(str(when["prefix"]))):
        errs.append(f'{w}.when: {{prefix: "3자"}}만')
    where = st.get("where")
    if where is not None and (
        not isinstance(where, dict) or any(not _ID.fullmatch(str(k)) or isinstance(v, (dict, list)) or v is None for k, v in where.items())
    ):
        errs.append(f"{w}.where: {{칸: 고정 값}}만")
    latest = st.get("latest")
    if latest is not None and (not isinstance(latest, list) or not latest or any(not _ID.fullmatch(str(x)) for x in latest)):
        errs.append(f"{w}.latest: 칸 이름 목록")
    if "optional" in st and not isinstance(st["optional"], bool):
        errs.append(f"{w}.optional: true 또는 false")
    if "tz" in st and st["tz"] != "UTC":
        errs.append(f"{w}.tz: UTC만(빼면 시간대 없는 값 = KST)")
    return errs


def _ref(r, seen, w, multi):
    """열쇠 검사 — file 또는 <앞 단계>.<칸>. multi면 목록(앞 자리부터 — 안쪽 목록 한 겹까지)도, 아니면 글자 또는 평평한 목록."""
    if isinstance(r, list):
        if not r or any(isinstance(a, list) and (not multi or not a or any(isinstance(x, list) for x in a)) for a in r):
            return [f"{w}: 열쇠 목록 꼴이 틀림(빈 목록·두 겹 목록)"]
        return [e for x in refs(r) for e in _ref(x, seen, w, multi=False)]
    if r == FILE:
        return []
    step, _, col = str(r).partition(".")
    if step not in seen:
        return [f"{w}: {r!r} — file 또는 <앞 단계>.<칸>(앞에 없는 단계 {step!r})"]
    cols = seen[step]
    if not _ID.fullmatch(col) or (cols is not None and col not in cols):
        return [f"{w}: {r!r} — 칸 이름이 틀림" + (f"(허용 {', '.join(cols)})" if cols else "")]
    return []
