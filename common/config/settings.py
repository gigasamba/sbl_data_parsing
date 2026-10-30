"""설정 읽기 — settings.yaml 하나(최상위 절 common·pipeline·mcp)를 pydantic 모델로 읽는다(S7a, refactor_plan 5-2 · D-015).
앱은 자기 설정 객체 하나를 프로세스 시작 때 한 번 읽어 캐시한다 — pipeline/config.py(common + pipeline 절),
mcp_server/config.py(common + mcp 절). 이 파일은 common 절 모델과 두 앱이 함께 쓰는 읽기 함수를 둔다.

읽는 순서(높은 쪽이 이김): 시험이 넘긴 값(data=·Cache.env) > 덮기 파일의 overrides(put·child_env·overlay 도구 — 아래) > YAML > 모델 기본값.
  · env에서 읽는 것은 신호 둘(RUN_ENV·SETTINGS_FILE)뿐이다(S7e2 — 전환 다리 없앰, D-028 ④). 옛 env 이름으로 준 값은 읽지 않는다(시작 때 이름만
    한 번 경고). 엔진·인계 파일이 env로 읽는 28키(pinned)만 import common 때 pin_env()가 env로 내준다(영구 다리 — D-028 ⑤).
  · 덮기 파일(S7e2, 사용자 10-28): 최상위 `base:`(다른 설정 파일 경로 — 먼저 읽음)와 `overrides:`({옛 env 이름: 글자|null}, null = 그 칸 비움)만 든
    작은 yaml. 프로세스 안 put()·자식용 child_env()·PC 한 번 실행용 `python -m common.config.overrides`가 만들고 SETTINGS_FILE로 가리킨다(원본 비밀을
    복사하지 않음 — 원본은 base로 가리킴). overrides 값은 옛 env 글자 꼴로 판정한다(켜기 칸 '1'·'0' 등).
  · 모델 기본값은 지금 코드의 `os.environ.get(X) or 기본값`과 같은 값이다 — 목록 칸도(PARSE_PHASES 1,2,3r 등, 코드가 빈 목록이면 []).
    None은 "읽는 코드가 정함"이다: 코드가 계산하는 기본값(경로·CPU 수 등) · 자리마다 다른 기본값 · 있고 없음을 코드가 가르는
    칸(PG_HOST·PG_PORT — 둘 다 없으면 docker 자동 탐지) · JSON 칸(없으면 안 붙임). 대조표는 refactor_plan 부록 D.
  · 비운 칸(YAML null·옛 env `X=`)은 "설정 안 함"(모델 기본값). 빈 글자 ""도 기본값이 있는 칸(숫자·켜기·목록, 기본값 있는 글자)에서는
    "설정 안 함"이다 — 옛 `os.environ.get(X) or 기본값`과 같음. 기본값이 None인 글자 칸, 그리고 옛 코드가 `os.environ.get(X, 기본값)`
    (or 없음)으로 읽어 `X=`이 ''였던 글자 칸(F(..., blank="keep") — 17칸, S7a2)에서만 ""이 빈 글자로 남는다.
    이 규칙은 Section._normalize 한 곳에 있고 YAML·옛 env(전환 다리)·migrate·시험 data=가 모두 거친다(VS7a R-4).
  · 글자 칸에 쓴 YAML 스칼라(yes·no·true·on·1·0·숫자)는 쓴 글자 그대로 글자로 받는다 — 옛 env 줄에 같은 글자를 쓴 것과 같게(VS7a R-3).
    숫자·켜기·JSON 칸은 YAML이 푼 값 그대로.
파일 찾기: SETTINGS_FILE(env) > RUN_ENV가 없거나 local이면 저장소 루트 settings.yaml(있을 때만 — settings.sample.yaml 옆).
RUN_ENV: env RUN_ENV > YAML common.run_env. local·dev·prd. 없거나 dev·prd인데 파일이 없으면 거부(D-028 ②).
앱 시작 관문 require_run_env() — pipeline.cli(selftest 빼고)·mcp_server.main·trigger_server·mcp_parse_service가 맨 먼저 부른다. 서버(dev·prd)면
설정 파일을 못 읽거나 그 앱 절 검증에 실패해도 이유(칸 경로·오류 종류만)를 찍고 종료 2(VS7e1 U-1 — 사용자 10-28). 틀린 파일은 import common 때도
서버면 바로 실패(pin_env — STRICT, S7b c안), local이면 경고 뒤 기본값.
비밀 칸은 SecretStr — 출력·로그·검증 오류에 값이 나오지 않는다.
사용: python -m common.config.settings [--file 경로] [--app pipeline|mcp]   # 읽어서 요약(비밀 가림)
"""

import contextlib
import functools
import json
import os
import sys
from pathlib import Path
from typing import Annotated, ClassVar, Literal, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.core import exitclean  # pl-27 — 맡은 덮기 파일은 프로세스가 끝날 때 지움
from common.core.console import utf8_stdout

REPO_ROOT = Path(__file__).resolve().parents[2]  # PC = 저장소 루트 · 이미지 = /app/deploy
LOCAL_FILE = (
    REPO_ROOT / "settings.yaml"
)  # RUN_ENV=local 기본 자리 — 저장소 루트, settings.sample.yaml 옆(git 밖 — .gitignore · 사용자 10-29)
RUN_ENVS = ("local", "dev", "prd")  # 사용자 10-29(op-02) — stage 삭제(동작이 prd와 같았음), 입력도 거부
SERVER_ENVS = ("dev", "prd")
SECTIONS = ("common", "pipeline", "mcp")
OVERLAY_KEYS = ("base", "overrides")  # 덮기 파일의 최상위 열쇠(위 모듈 설명 — S7e2)
STRICT = True  # RUN_ENV가 없으면 거부(사용자 10-27, D-028 ②)
IN_IMAGE = REPO_ROOT.name == "deploy"  # 코드가 이미지 배치(/app/deploy/<패키지>) — paths.LOCAL_RUN과 같은 판정
# ── 이미지 배치 약속 경로 — 코드에 둔 컨테이너 안 자리는 이 두 표에만(CLAUDE.md 3절 경로 규칙의 예외, 사용자 10-28 — VS7e2 R-12 · D-029) ──
# 이미지(Dockerfile·compose 마운트·entrypoint)가 만드는 자리라 서버 설정 값이 아니라 이미지와 함께 바뀐다. 동작은 S7e2와 같음.
IMAGE_PATHS = {
    "gold_mount": "/data/gold",  # run_tool.sh가 사람 정답 폴더를 붙이는 자리(pipeline.config.gold_dir — 옛 `-e GOLD_DIR=/data/gold`)
    "image_env": "/app/docker/image_env.txt",  # 빌드 때 이미지 ENV를 적어 둔 파일(common.config.boot — 라이브러리 env가 이미지 값만 덮게)
}
# VS7e1 B-2(사용자 10-28 ①) — 옛 Dockerfile ENV로 굽던 값은 이미지 안 모델 기본값으로(규칙은 "settings.yaml > 코드 기본값" 하나 — 옛 ENV는
# 다리가 사용자 env로 봐 settings.yaml이 못 덮었음). 이미지 신호 RAG_MODULE(5-3 H)로 그 이미지가 굽던 것만. PC·시험 하위 프로세스(RAG_MODULE 없음)는 PC 기본값.
_IMAGE_DEFAULTS = {
    "pipeline": {
        "DOC_DIR": "/data/docs",
        "DOC_DIR_PREPARED": "/app/output/prepared",
        "PIPE_EMBED": "api",
        "PIPE_PROCS": "auto",
        "SOFFICE_BIN": "/usr/bin/soffice",
    },
    "mcp": {"PIPE_EMBED": "api", "MCP_QUERY_CACHE": "/tmp/mcp_query_cache.sqlite"},  # MCP_QUERY_CACHE — 옛 compose 기본(S7e2)
}
IMAGE_DEFAULTS = _IMAGE_DEFAULTS.get(os.environ.get("RAG_MODULE", ""), {}) if IN_IMAGE else {}  # env 남김 — 이미지 신호(5-3 H)


def image_default(env, pc=None):
    """칸 기본값 — 이 이미지가 옛 Dockerfile ENV로 굽던 칸이면 그 값, 아니면 pc(PC 기본값 — 지금 코드 기본값)."""
    return IMAGE_DEFAULTS.get(env, pc)


# VS7e1 C-45 ⑤(사용자 10-28) — settings.yaml common.runtime.lib_env로 줄 수 있는 라이브러리 env 이름(비밀 아님 — 이 목록 밖은 거부).
# 컨테이너 entrypoint(common.config.boot)가 시작 때 env로 낸다 — 사용자 env는 안 덮고, 이미지 ENV 값(/app/docker/image_env.txt)은 덮는다(B-2와 같은 원칙).
# 출처: migrate --compare "모델 밖" 줄(OMP_NUM_THREADS·HF_HUB_OFFLINE·TZ·LITELLM_LOCAL_MODEL_COST_MAP) + Dockerfile ENV(TZ·LANG·HF_*·DO_NOT_TRACK·
# SCARF_NO_ANALYTICS) + 코드가 자식·라이브러리에 넘기는 이름(run_all OMP·MKL·OPENBLAS·NUMEXPR·TORCH, PIPELINE_VERSION, TESSDATA_PREFIX·HF_HOME).
# 이미지 바탕(PYTHONPATH·HOME·PYTHONUTF8 등)·내부 신호(RAG_MODULE·RUN_ENV·SETTINGS_FILE)는 넣지 않는다.
LIB_ENV_NAMES = (
    "TZ",
    "LANG",
    "LC_ALL",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "TORCH_NUM_THREADS",
    "HF_HOME",
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "TESSDATA_PREFIX",
    "LITELLM_LOCAL_MODEL_COST_MAP",
    "PIPELINE_VERSION",
    "DO_NOT_TRACK",
    "SCARF_NO_ANALYTICS",
)


class SettingsError(RuntimeError):
    """설정 파일을 못 찾거나 형식이 틀림 — 메시지에 비밀 값은 넣지 않는다."""


def F(default, env, desc, *, pinned="", blank="", on=(), off=(), fold="", unset=(), **kw):
    """설정 칸 하나 — env: 옛 환경변수 이름(옮기기·전환 다리·keyscan 대조에 씀), desc: sample·문서에 나가는 설명,
    pinned: 지문이 걸린 파일이 읽는 칸("engine" 엔진 파일·"handoff" 인계 파일 — 그 파일은 env를 그대로 읽어 다리가 늘 내줌),
    blank="keep": 기본값이 있어도 빈 값을 그대로 둠 — 옛 코드가 `os.environ.get(X, 기본값)`(or 없음)으로 읽어 `X=`이 ''였던
    글자 칸(S7a2 — 코디네이터 10-27 (b), 동작 불변)·목록 칸(빈 목록 — VS7a2 R-a).
    켜기 칸의 옛 판정 꼴(VS7a2 R-c — 코디네이터: 키마다 옛 꼴 그대로): on=("1",) — 글자가 그중 하나일 때만 켜짐(옛 `== "1"`),
    off=("0",) — 그중 하나일 때만 꺼짐(옛 `!= "0"`), fold="lower" — 견주기 전에 strip().lower()(옛 `str(v).strip().lower() in (…)`),
    fold="strip" — strip()만(옛 `.strip() in (…)` — GOLD_DRAFT_MERMAID_CHECK, S7c2), fold="" — 글자 그대로(VS7c2 R-9 — 모드 이름으로).
    빈 글자 ''도 이 꼴로 판정한다(옛 코드가 `X=`을 읽던 대로). 판정 꼴이 없는 켜기 칸은 pydantic 기본 해석(아직 객체로 읽는 코드 없음).
    unset: 이 글자면 "설정 안 함"(모델 기본값 — 읽는 코드가 계산) — ("auto",)는 옛 `v not in (None, "", "auto")`(resources._f),
    "nondigit"는 옛 `v.strip().isdigit()`가 아니면 무시(OCR_THREADS)."""
    extra = {"env": env}
    if pinned:
        extra["pinned"] = pinned
    if blank:
        extra["blank"] = blank
    if fold not in ("", "lower", "strip"):
        raise ValueError(f"{env}: fold는 ''·'lower'·'strip'만")
    if on or off:
        extra["truth"] = {"on": list(on), "off": list(off), "fold": fold}
    if unset:
        extra["unset"] = unset if isinstance(unset, str) else list(unset)
    return Field(default, description=desc, json_schema_extra=extra, **kw)


def _extra(field, key):
    extra = field.json_schema_extra or {}
    return extra.get(key) if isinstance(extra, dict) else None


def keeps_blank(field):
    return _extra(field, "blank") == "keep"


# 판정 꼴이 있는 켜기 칸에 YAML로 쓸 수 있는 표기 — true·false(대소문자 무관)·0·1('0'·'1' 포함). 그 밖(yes·no·on·off 등)은
# 검증 오류(코디네이터 10-27 — 안전 스위치 NO_PAID_CALLS: yes가 옛 판정(=="1")으로 조용히 꺼지지 않게). env 글자는 옛 판정 꼴 그대로(VS7a2 R-c).
YAML_BOOL_WORDS = ("true", "false")


def judge(field, v, name=""):
    """켜기 칸 값 → bool(옛 판정 꼴, 위 F 설명). 판정 꼴이 없거나 글자가 아니면 v 그대로. YAML 값은 위 표기만(아니면 ValueError — 칸 이름만)."""
    t = _extra(field, "truth")
    if not t:
        return v
    if isinstance(v, YamlScalar):
        word = str(v).strip()
        if isinstance(v.value, bool) and word.lower() in YAML_BOOL_WORDS:
            return v.value
        if word not in ("0", "1"):
            raise ValueError(f"{name or '켜기 칸'}: YAML 켜기 값은 true·false·0·1만(옛 env 꼴 표기는 env로)")
        v = word
    if not isinstance(v, str):
        return v
    fold = t["fold"]
    s = v.strip().lower() if fold == "lower" else v.strip() if fold == "strip" else v
    return s in t["on"] if t["on"] else s not in t["off"]


def is_unset(field, v):
    """unset 글자인가(위 F 설명) — YAML 스칼라는 쓴 글자로 본다."""
    u = _extra(field, "unset")
    if not u or not isinstance(v, str):
        return False
    if u == "nondigit":
        return not v.strip().isdigit()
    return v in u


def _csv(v):
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return v


def _words(v):
    if isinstance(v, str):
        return v.replace(",", " ").split()
    return v


def _json(v):
    if isinstance(v, str):
        try:
            return json.loads(v) if v.strip() else None
        except ValueError:
            raise ValueError("JSON 형식이 아님") from None
    return v


CsvList = Annotated[list[str], BeforeValidator(_csv)]  # 옛 env "a,b" 또는 YAML 목록
WordList = Annotated[list[str], BeforeValidator(_words)]  # 옛 env "a b"(셸 for 단어 — NIGHTLY_MODULES) 또는 YAML 목록
JsonValue = Annotated[dict | list, BeforeValidator(_json)]  # 옛 env JSON 글자 또는 YAML 사전·목록


def _csv_text(v):
    """쉼표 목록 글자 칸 — 글자는 쓴 그대로(공백·빈 항목까지), YAML 목록은 ','로 이은 글자(S7c2 — 결과 파일에 원문 글자를 적는 칸)."""
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return v


CsvText = Annotated[str, BeforeValidator(_csv_text)]  # 원문 글자를 지켜야 하는 쉼표 목록(PARSE_POST — rep.post.config에 그대로 적음)


def _auto_word(v):
    """auto 표기 — 대소문자·앞뒤 공백 무시, 공백만인 글자도 auto(옛 resolve_procs의 strip().lower() — VS7c1 R-1). 빈 글자는 여기 안 옴(_normalize가 설정 안 함으로)."""
    return "auto" if isinstance(v, str) and v.strip().lower() in ("auto", "") else v


AutoWord = Annotated[Literal["auto"], BeforeValidator(_auto_word)]  # 숫자 | auto 칸의 auto(PIPE_PROCS)


def _port(v):
    """접속·듣기 포트 — 정수만(VS7d U-2, 사용자 10-27). 글자는 옛 int(글자)와 같게(앞뒤 공백·부호 허용) — '5.0'·'8766x'는 형식 오류,
    YAML 5.0·true도 형식 오류(일반 int 칸은 '5.0'을 5로 받지만 포트는 받지 않음 — 읽는 자리의 checked가 실패시킴)."""
    if isinstance(v, bool) or isinstance(v, float):
        raise ValueError("포트는 정수만")
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            raise ValueError("포트는 정수만") from None
    return v


Port = Annotated[int, BeforeValidator(_port)]  # 포트 칸(*_PORT) — 정수 글자만


def _lib_env(v):
    """라이브러리 env 사전(C-45 ⑤) — 이름은 LIB_ENV_NAMES 안만, 값은 한 줄 글자만(YAML 스칼라는 쓴 글자 그대로). 오류에는 이름만(값 없음)."""
    if isinstance(v, str):
        v = _json(v)
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("이름: 값 사전이어야 함")
    out = {}
    for k, x in v.items():
        name = str(k)
        if name not in LIB_ENV_NAMES:
            raise ValueError(f"라이브러리 env 허용 목록 밖 이름: {name}")
        if x is None or isinstance(x, (dict, list)):
            raise ValueError(f"{name}: 한 줄 글자 값만")
        s = str(x) if isinstance(x, str) else _text(x)
        if "\n" in s:
            raise ValueError(f"{name}: 한 줄 글자 값만")
        out[name] = s
    return out


LibEnv = Annotated[dict[str, str], BeforeValidator(_lib_env)]  # 라이브러리 env 사전(common.runtime.lib_env)


class YamlScalar(str):
    """YAML 스칼라 — 쓴 글자(str 자체)와 푼 값(.value)을 함께 든다(VS7a R-3). 켜기·숫자·날짜로 풀린 것(yes·true·1·0.5·2026-10-27 등)과
    글자(S7b — env 글자와 가르려고: 판정 꼴 켜기 칸은 YAML 표기를 좁게 받음)를 모두 이것으로 읽는다.
    글자 칸은 쓴 글자로, 그 밖 칸은 푼 값으로 받는다(Section._normalize)."""

    value = None


@functools.cache
def _yaml_loader():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def keep(base):
        def construct(loader, node):
            s = YamlScalar(node.value)
            s.value = base(loader, node)
            return s

        return construct

    C = yaml.constructor.SafeConstructor
    for tag, base in (
        ("bool", C.construct_yaml_bool),
        ("int", C.construct_yaml_int),
        ("float", C.construct_yaml_float),
        ("timestamp", C.construct_yaml_timestamp),  # 2026-10-27 같은 날짜도(PM_PARSE_DATE 등 글자 칸)
        ("str", C.construct_yaml_str),
    ):  # 글자도 — env 글자와 가름(S7b, judge)
        Loader.add_constructor("tag:yaml.org,2002:" + tag, keep(base))
    return Loader


def _plain(v):
    """YamlScalar 표시를 벗겨 푼 값으로(사전 열쇠·목록 안까지)."""
    if isinstance(v, YamlScalar):
        return v.value
    if isinstance(v, dict):
        return {_plain(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def _text(v):
    """글자 칸에 온 값 → 글자. YAML 스칼라는 쓴 글자 그대로, 파이썬 켜기(시험 data=)는 옛 env 꼴 '1'·'0', 숫자는 str()."""
    if isinstance(v, YamlScalar):
        return str(v)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    return v


def _args(annotation):
    return [a for a in (get_args(annotation) or (annotation,)) if a is not type(None)]


def field_kind(annotation):
    """칸 종류 — "text"(글자·비밀·글자 Literal), "list"(목록), "json", "other"(숫자·켜기·int|"auto" 등)."""
    args = _args(annotation)
    if any(a is CsvList or a is WordList for a in args):
        return "list"
    if any(a is JsonValue for a in args):
        return "json"
    if any(a is LibEnv for a in args):
        return "map"
    if any(a is str or a is SecretStr or a is CsvText for a in args) or (
        args and all(get_origin(a) is Literal and all(isinstance(x, str) for x in get_args(a)) for a in args)
    ):
        return "text"
    return "other"


class Section(BaseModel):
    """설정 절 공통 — 모르는 칸은 거부(오타 잡기), 비운 칸은 기본값, YAML 스칼라는 칸 종류에 맞게(위 모듈 설명)."""

    model_config = ConfigDict(extra="forbid", validate_default=False)
    REMOVED: ClassVar[frozenset[str]] = frozenset()  # 지운 칸 — 옛 설정 파일에 남아 있어도 경고만 하고 무시(한 판 동안 — 시작 거부 막기)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if not isinstance(data, dict):
            return data
        out = {}
        for k, v in data.items():
            if v is None:
                continue
            if k in cls.REMOVED:
                sys.stderr.write(f"[settings] 지운 칸 무시: {k} — 설정 파일에서 지울 것(값은 출력 안 함)\n")
                continue
            f = cls.model_fields.get(k)
            if f is None or _section_type(f.annotation) is not None:
                out[k] = v  # 모르는 칸(거부는 pydantic이)·하위 절(그 절의 _normalize가)
                continue
            kind = field_kind(f.annotation)
            if is_unset(f, v):
                continue  # auto 등 — 설정 안 함(읽는 코드가 계산, VS7a2 R-d)
            if kind == "text":
                v = [_text(x) for x in v] if isinstance(v, list) else _text(v)  # 목록은 CsvText만(그 밖 글자 칸은 pydantic이 거부)
            elif kind == "list":
                v = [_text(x) for x in v] if isinstance(v, list) else _text(v)  # phases: 3 → '3'(옛 env PARSE_PHASES=3과 같게)
                if v in ("", []):  # 빈 목록 — 옛 `get(X) or 기본`이면 기본값, `get(X, 기본)`(keep)이면 빈 목록(VS7a2 R-a)
                    if keeps_blank(f):
                        out[k] = []
                    continue
            elif kind == "map":
                pass  # 라이브러리 env 사전 — 값은 쓴 글자 그대로(_lib_env가 봄)
            elif _extra(f, "truth"):
                v = judge(f, v, k)  # 켜기 칸 — env 글자는 빈 글자도 옛 판정 꼴로(VS7a2 R-c), YAML은 true·false·0·1만
            else:
                v = _plain(v)
            if v == "" and _extra(f, "env") in IMAGE_DEFAULTS:
                out[k] = (
                    "" if kind == "text" else None
                )  # 이미지 기본값 칸의 빈 글자 = 정말 비움(옛 env_file `X=`이 이미지 ENV를 ''로 덮던 것 — B-2)
                continue
            if v == "" and (kind != "text" or (f.default is not None and not keeps_blank(f))):
                continue  # 빈 글자 = 설정 안 함(R-4) — 기본값 None·blank="keep" 글자 칸만 ""로 남음
            out[k] = v
        return out


class AppSettings(BaseSettings):
    """앱 설정 뿌리 — 다른 앱 절(pipeline이면 mcp)은 무시한다. pydantic-settings의 env 자동 읽기는 끄고(이름이 옛 env와
    달라 섞이면 안 됨) load()가 순서대로 합친 값만 받는다."""

    model_config = SettingsConfigDict(extra="ignore")
    _source: str = PrivateAttr("")  # 읽은 설정 파일(없으면 "")
    _dropped: frozenset = PrivateAttr(frozenset())  # 형식이 틀려 버린 옛 env 이름(경고 뒤 기본값 — dropped())
    _unknown_run_env: str | None = PrivateAttr(None)  # lenient_run_env로 없음 처리한 모르는 RUN_ENV 글자(가드가 서버로 봄 — guard_run_env)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings,)


# ── 칸 목록 걷기 — 옮기기 도구·export·전환 다리·sample·keyscan 대조가 함께 씀 ──────────────────────────
def _section_type(annotation):
    for a in get_args(annotation) or (annotation,):
        if isinstance(a, type) and issubclass(a, BaseModel):
            return a
    return None


def walk(model_cls, prefix=""):
    """(경로, FieldInfo, 칸이 속한 클래스) — 잎 칸만, 선언 순서."""
    for name, f in model_cls.model_fields.items():
        path = f"{prefix}{name}"
        sub = _section_type(f.annotation)
        if sub is not None:
            yield from walk(sub, path + ".")
        else:
            yield path, f, model_cls


def env_name(field):
    extra = field.json_schema_extra or {}
    return extra.get("env") if isinstance(extra, dict) else None


def is_secret(field):
    return any(a is SecretStr for a in (get_args(field.annotation) or (field.annotation,)))


def is_host(path):
    """호스트(compose·systemd·셸) 절 — 앱 프로세스 안에서는 쓰지 않음(옛 env를 앱 칸으로만 받음)."""
    return "host" in path.split(".")[:-1]


def type_label(annotation):
    names = []
    for a in _args(annotation):
        if a is CsvList:
            names.append("목록(쉼표 또는 YAML 목록)")
        elif a is CsvText:
            names.append("글자(쉼표 목록 — 원문 그대로, YAML 목록은 쉼표로 이음)")
        elif a is WordList:
            names.append("목록(공백 또는 YAML 목록)")
        elif a is JsonValue:
            names.append("JSON(사전·목록)")
        elif a is AutoWord:
            names.append("auto")
        elif a is Port:
            names.append("int(포트 — 정수만)")
        elif a is LibEnv:
            names.append("사전(라이브러리 env 이름: 글자)")
        elif get_origin(a) is Literal:
            names.append("|".join(map(str, get_args(a))))
        elif get_origin(a) in (list, dict):
            names.append(get_origin(a).__name__)
        else:
            names.append(getattr(a, "__name__", str(a)))
    return " | ".join(names)


def fields_table(model_cls):
    """[{path, env, type, default, desc, secret}] — sample·부록 D·keyscan 대조용."""
    rows = []
    for path, f, _ in walk(model_cls):
        rows.append(
            dict(
                path=path, env=env_name(f), type=type_label(f.annotation), default=f.default, desc=f.description or "", secret=is_secret(f)
            )
        )
    return rows


def env_map(model_cls, *, hosts=False):
    """옛 env 이름 → 경로(호스트 절은 hosts=True일 때만 — 같은 env 이름이 앱·호스트 두 칸에 있음, T-21). 사본을 돌려준다."""
    return dict(_env_map(model_cls, hosts))


@functools.cache
def _env_map(model_cls, hosts):
    """env_map 캐시(VS7b R-4 — 전환 기간 env 기반 객체가 env가 바뀔 때마다 모델을 다시 걷지 않게). 고치지 말고 읽기만."""
    out = {}
    for path, f, _ in walk(model_cls):
        e = env_name(f)
        if e and is_host(path) == hosts:
            out.setdefault(e, path)
    return out


def render(value, *, secrets=False, sep=","):
    """옛 env 글자로 — 켜기 1/0, 목록은 sep(쉼표 — WordList 칸은 공백), 사전은 JSON. 비밀은 secrets=True일 때만(아니면 None)."""
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value() if secrets else None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 4.0 → "4"(compose cpus·옛 env 글자와 같게)
    if isinstance(value, (list, tuple)):
        return sep.join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def list_sep(field):
    """목록 칸을 옛 env 한 줄로 낼 때 구분자 — WordList(셸 for 단어)는 공백, 그 밖은 쉼표."""
    return " " if any(a is WordList for a in _args(field.annotation)) else ","


def _get(obj, path):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _is_set(obj, path):
    """경로의 모든 단계가 YAML·env·시험 값으로 실제로 채워졌는지(model_fields_set) — 기본값과 구별."""
    parts = path.split(".")
    for part in parts:
        if part not in obj.model_fields_set:
            return False
        obj = getattr(obj, part)
    return True


def env_items(settings, *, section=None, hosts=False, secrets=False, only_set=True):
    """[(옛 env 이름, 글자, 경로)] — export 명령·전환 다리가 씀. only_set이면 기본값은 빼고(읽는 코드의 기본값이 그대로 돌게).
    hosts: False = 앱 칸만 · True = 호스트 칸만 · None = 둘 다(export — 절 이름으로 고름, S7e1)."""
    out = []
    for path, f, _ in walk(type(settings)):
        e = env_name(f)
        if not e or (section and not (path == section or path.startswith(section + "."))):
            continue
        if hosts is not None and is_host(path) != hosts:
            continue
        if only_set and not _is_set(settings, path):
            continue
        s = render(_get(settings, path), secrets=secrets, sep=list_sep(f))
        if s is not None:
            out.append((e, s, path))
    return out


# ── 읽기 ────────────────────────────────────────────────────────────────────────────────
def _set_path(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = cur[p] = {}
        cur = nxt
    cur[parts[-1]] = value


def _peek(doc, path):
    for p in path.split("."):
        doc = doc.get(p) if isinstance(doc, dict) else None
        if doc is None:
            return None
    return doc


def _drop_path(doc, path):
    parts = path.split(".")
    for p in parts[:-1]:
        doc = doc.get(p) if isinstance(doc, dict) else None
        if doc is None:
            return
    if isinstance(doc, dict):
        doc.pop(parts[-1], None)


def _merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def read_yaml(path):
    import yaml

    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SettingsError(f"설정 파일을 읽지 못함: {p} ({e.strerror})") from None
    try:
        doc = yaml.load(text, Loader=_yaml_loader())  # SafeLoader 하위(스칼라 글자만 더 듦)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" {mark.line + 1}행" if mark else ""
        raise SettingsError(f"설정 파일 YAML 형식 오류: {p}{where}") from None
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise SettingsError(f"설정 파일 맨 위는 절(common·pipeline·mcp) 사전이어야 함: {p}")
    unknown = sorted(set(doc) - set(SECTIONS) - set(OVERLAY_KEYS))
    if unknown:
        raise SettingsError(f"설정 파일에 모르는 최상위 절 {unknown} — common·pipeline·mcp만(덮기 파일은 base·overrides): {p}")
    return doc


def read_settings(path, _depth=0):
    """설정 파일 → (절 사전, overrides {옛 env 이름: 글자|None}). 덮기 파일이면 base를 먼저 읽고 그 위에 이 파일의 절·overrides를 겹친다
    (위 모듈 설명 — base는 상대 경로면 이 파일 폴더 기준, 5단까지)."""
    doc = read_yaml(path)
    base, over = doc.pop("base", None), doc.pop("overrides", None)
    names = {}
    if base is not None:
        if _depth >= 5:
            raise SettingsError(f"덮기 파일 base가 5단을 넘음: {path}")
        bp = Path(str(base))
        if not bp.is_absolute():
            bp = Path(path).parent / bp
        bdoc, names = read_settings(bp, _depth + 1)
        doc = _merge(bdoc, doc)
    if over is not None:
        if not isinstance(over, dict):
            raise SettingsError(f"overrides는 {{옛 env 이름: 글자}} 사전이어야 함: {path}")
        for k, v in over.items():
            names[str(k)] = _override_value(k, v, path)
    return doc, names


def _override_value(k, v, path):
    """덮기 파일 overrides 값 하나 → load()가 칸에 얹을 값. 따옴표 글자(overlay_file이 쓰는 꼴)는 옛 env 글자 꼴로 판정하고(켜기 '1'·'0' 등),
    손으로 쓴 따옴표 없는 YAML 값(true·false·숫자)은 절 안에 쓴 것과 같은 규칙으로 판정한다(YamlScalar 그대로 — VS7e2 R-2: 옛 판은
    `NO_PAID_CALLS: true`를 글자 'true'로 봐 꺼짐, 펼쳐 쓰면 켜짐). 켜기 낱말은 true·false만(yes·on 등은 거부 — 펼쳐 쓸 때 바뀌지 않게)."""
    if isinstance(v, (dict, list)):
        raise SettingsError(f"overrides {k}: 한 줄 값만: {path}")
    if v is None:
        return None
    if isinstance(v, YamlScalar) and not isinstance(v.value, str):
        if isinstance(v.value, bool) and str(v).strip().lower() not in YAML_BOOL_WORDS:
            raise SettingsError(f"overrides {k}: 켜기 값은 true·false(옛 env 글자 꼴은 따옴표 — '1'·'0'): {path}")
        return v
    return str(v)


def find_file(environ, run_env):
    """SETTINGS_FILE > (RUN_ENV 없음·local이면) 저장소 루트 settings.yaml. 없으면 None."""
    explicit = environ.get("SETTINGS_FILE")
    if explicit:
        return Path(explicit)
    if run_env in (None, "local") and LOCAL_FILE.is_file():
        return LOCAL_FILE
    return None


def _format_errors(err, source):
    """칸 경로·오류 종류만 — 입력값은 찍지 않는다(비밀 칸 이름을 틀리면 비밀 칸으로 알아볼 수 없음 — VS7a R-1)."""
    lines = [
        f"  {'.'.join(str(x) for x in e['loc'])}: {e['msg']} [{e['type']}]" for e in err.errors(include_url=False, include_input=False)
    ]
    return f"설정 검증 실패({source}) — {len(lines)}건\n" + "\n".join(lines)


def _leaf_of(loc, paths):
    """오류 위치 → 칸 경로. int | "auto" 같은 합집합 칸은 pydantic이 뒤에 형식 이름(pipe_procs.int·pipe_procs.literal['auto'])을
    붙이므로, paths(이름으로 덮은 칸) 중 앞부분이 같은 것으로 줄인다(리뷰 S7a2)."""
    parts = [str(x) for x in loc]
    for n in range(len(parts), 0, -1):
        cand = ".".join(parts[:n])
        if cand in paths:
            return cand
    return ".".join(parts)


_warned: set = set()  # 같은 경고를 한 번만


def _warn_once(msg):
    if msg not in _warned:
        _warned.add(msg)
        print(msg, file=sys.stderr)


def load(
    app_cls,
    *,
    file=None,
    data=None,
    names=None,
    environ=None,
    strict=None,
    use_file=True,
    require_file=True,
    lenient_run_env=False,
    _read=None,
):
    """설정 한 번 읽기(캐시 없음 — Cache가 캐시). file=None이면 find_file. data=시험이 직접 넘기는 값(YAML 꼴).
    names={옛 env 이름: 글자|None} — 시험(Cache.env)이 옛 env 이름으로 덮는 값(None = 그 칸 비움). 덮기 파일의 overrides 위에 얹는다.
    names·overrides 값의 형식이 틀리면 그 칸만 버리고 경고(이름만 — dropped()·checked()가 읽는 자리에서 알림). environ에서는 신호
    RUN_ENV·SETTINGS_FILE만 본다. lenient_run_env=True면 모르는 RUN_ENV 글자를 경고 뒤 없음으로(거부는 앱 시작 관문 — 가드는 서버로 봄).
    _read=(절 사전, overrides) — 이미 읽은 파일 내용(pin_env)."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    strict = STRICT if strict is None else strict
    env_run = environ.get("RUN_ENV") or None
    unknown_run_env = None
    if env_run is not None and env_run not in RUN_ENVS:
        if not lenient_run_env:
            raise SettingsError(f"RUN_ENV={env_run!r} — {'·'.join(RUN_ENVS)} 중 하나")
        _warn_once(
            f"[settings] RUN_ENV={env_run!r} — {'·'.join(RUN_ENVS)} 중 하나가 아니라 없음으로 봄(앱 시작 관문이 거부, 가드는 서버로 봄)"
        )
        unknown_run_env, env_run = env_run, None
    path = (Path(file) if file else find_file(environ, env_run)) if use_file else None
    if _read is not None:
        doc, over = _read
    else:
        doc, over = read_settings(path) if path else ({}, {})
    wanted = set(app_cls.model_fields)
    merged = {k: v for k, v in doc.items() if k in wanted}
    from_names, before = {}, {}
    emap = _env_map(app_cls, False)
    pinned_env = {
        n: environ[n] for n in _pinned_names(app_cls) if n in environ
    }  # 영구 다리 칸은 env가 산 값(엔진·인계 파일과 같은 값 — pin_env·put이 맞춰 씀)
    file_run = env_run if env_run is not None else _peek(doc, "common.run_env")
    server = (
        unknown_run_env is not None or (str(file_run) if file_run is not None else None) in SERVER_ENVS
    )  # 덮기 파일 거부 판정(VS7e2 R-3 — U-1과 같게, 모르는 RUN_ENV 글자는 가드처럼 서버로)
    # 앱 설정 모듈이 import 중이면(pipeline.config를 먼저 import → import common → pin_env → 다른 앱 설정 모듈의 CFG) 그 앱 칸 이름을 아직
    # 모름 — 이름 검사를 건너뛴다(import 순서와 무관하게, VS7e3 R-1). 그 앱의 cfg()가 읽을 때(이름 다 앎) 다시 검사한다.
    unknown = sorted(n for n in over if n not in emap and n not in _all_names()) if over and not _names_loading() else []
    if unknown:  # 덮기 파일의 모르는 이름(오타·호스트 칸) — 서버는 거부, local은 경고(이름만)
        msg = f"덮기 파일 overrides에 설정 칸이 없는 이름: {' '.join(unknown)}"
        if server:
            raise SettingsError(f"{msg} — {path}")
        _warn_once(f"[settings] {msg} — 무시(local)")
    from_file = set()  # 덮기 파일 overrides 값이 마지막으로 얹힌 칸(시험 names·영구 다리 env가 덮으면 빠짐)
    for name, value in {**over, **pinned_env, **(names or {})}.items():
        p = emap.get(name)
        if p is None or name == "RUN_ENV":
            continue
        if p not in before:
            before[p] = _peek(merged, p)
        if value is None:
            _drop_path(merged, p)
        else:
            _set_path(merged, p, value)
        from_names[p] = name
        from_file.discard(p)
        if name in over and name not in pinned_env and name not in (names or {}):
            from_file.add(p)
    if env_run is not None:
        _set_path(merged, "common.run_env", env_run)
    elif unknown_run_env is not None:
        _drop_path(merged, "common.run_env")  # 모르는 env 글자가 YAML 값을 이김(없음 — 가드는 그 글자를 서버로 봄, 관문은 거부)
    _merge(merged, data or {})
    try:
        settings = app_cls(**merged)
    except ValidationError as e:
        bad = {_leaf_of(err["loc"], from_names) for err in e.errors()}
        if not bad or not bad <= set(from_names) or (server and bad & from_file):
            raise SettingsError(
                _format_errors(e, path or "설정 없음")
            ) from None  # 서버 — 덮기 파일 값 형식 오류도 거부(VS7e2 R-3, U-1과 같게)
        # 이름으로 덮은 값(시험·덮기 파일)만 틀림 — 그 칸만 버리고(파일 값으로 되돌림) 시작, 읽는 자리의 checked()가 알림. 값은 찍지 않는다.
        _warn_once(f"[settings] 덮은 값 형식이 맞지 않아 무시(기본값·파일 값): {' '.join(sorted(from_names[b] for b in bad))}")
        for b in bad:
            if before[b] is None:
                _drop_path(merged, b)
            else:
                _set_path(merged, b, before[b])
        try:
            settings = app_cls(**merged)
        except ValidationError as e2:
            raise SettingsError(_format_errors(e2, path or "설정 없음")) from None
        settings._dropped = frozenset(from_names[b] for b in bad)
    settings._unknown_run_env = unknown_run_env
    common = getattr(settings, "common", None)  # 앱 절만 든 뿌리(PIPE·MCP)는 common 절이 없음
    run_env = common.run_env if common is not None else env_run
    if run_env in SERVER_ENVS and path is None and require_file:
        raise SettingsError(f"RUN_ENV={run_env} — 서버는 설정 파일이 있어야 함(SETTINGS_FILE)")
    if run_env is None and strict:
        raise SettingsError("RUN_ENV 없음 — local·dev·prd 중 하나를 env RUN_ENV나 settings.yaml common.run_env로")
    settings._source = str(path) if path else ""
    return settings


def resolve_run_env(environ=None, file=None):
    """RUN_ENV 값 — env RUN_ENV, 없으면 설정 파일(file — 없으면 SETTINGS_FILE·저장소 루트 settings.yaml)의 common.run_env. 없으면 None,
    모르는 값이면 SettingsError(env·파일 같은 규칙 — 덮기 파일 도구도 이것으로, 리뷰 S7e3). 설정 모델 전체를 읽지 않는다."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    value = environ.get("RUN_ENV") or None
    if value is None:
        path = Path(file) if file is not None else find_file(environ, None)
        if path is not None:
            common = read_settings(path)[0].get("common") or {}
            value = common.get("run_env") if isinstance(common, dict) else None
    if value is not None and value not in RUN_ENVS:
        raise SettingsError(f"RUN_ENV={value!r} — {'·'.join(RUN_ENVS)} 중 하나")
    return value


def require_run_env(app="", environ=None, sections=None):
    """앱 시작 관문(D-028 ②) — RUN_ENV가 없거나 모르는 값이면 안내를 찍고 종료 코드 2. 값을 돌려준다.
    서버(dev·prd)면 설정 파일을 읽고 sections(앱 절 — 없으면 이 이미지 절, image_sections)를 끝까지 검증한다 — 파일이 없거나 못 읽거나
    검증에 실패하면 이유(칸 경로·오류 종류만, 값 없음)를 찍고 종료 2(VS7e1 U-1, 사용자 10-28 — 옛 env_file처럼 시작 거부). local은 검증하지
    않는다(설정 객체가 경고 뒤 기본값 — 지금처럼)."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    tag = f"[설정] {app + ': ' if app else ''}"
    try:
        value = resolve_run_env(environ)
    except SettingsError as e:
        print(f"{tag}{e}", file=sys.stderr)
        raise SystemExit(2) from None
    if value is None:
        print(
            f"{tag}RUN_ENV 없음 — local(PC)·dev·prd 중 하나를 env RUN_ENV로 주거나 settings.yaml common.run_env에 적음"
            "(PC: 저장소 루트 settings.yaml · 서버: settings.yaml — refactor.md C-34)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if value in SERVER_ENVS:
        names = image_sections(environ) if sections is None else ("common", *sections)
        try:
            st = load(section_class(names)[0], environ=environ, require_file=True)
        except SettingsError as e:
            print(f"{tag}서버(RUN_ENV={value}) — 설정을 읽지 못해 시작하지 않음: {e}", file=sys.stderr)
            raise SystemExit(2) from None
        if st.common.dev.llm_fake:  # op-02(사용자 10-29) — 가짜 LLM 응답은 local에서만, 서버는 시작 거부
            print(f"{tag}서버(RUN_ENV={value}) — common.dev.llm_fake가 켜져 있어 시작하지 않음(local 전용)", file=sys.stderr)
            raise SystemExit(2)
    return value


def section_class(names):
    """names 절(common + 앱 절)만 든 뿌리 — 이 이미지에 없는 앱 모듈은 건너뜀. (클래스, 실제로 든 절)."""
    from pydantic import create_model

    apps = app_classes(tuple(n for n in names if n != "common"))
    fields = {"common": (CommonSettings, Field(default_factory=CommonSettings))}  # 늘 — load()가 common.run_env를 봄
    for name, cls in apps.items():
        sub = cls.model_fields[name].annotation
        fields[name] = (sub, Field(default_factory=sub))
    return create_model("SectionSettings", __base__=AppSettings, **fields), {"common", *apps} & set(names)


IMAGE_SECTIONS = {"pipeline": ("common", "pipeline"), "mcp": ("common", "mcp")}  # RAG_MODULE(이미지 신호) → 이 컨테이너가 읽는 절


def image_sections(environ=None, in_image=None):
    """이 컨테이너가 읽는 절 — common + 자기 앱 절만(사용자 10-27 U-a): RAG_MODULE pipeline → common·pipeline, mcp → common·mcp,
    없음(PC — 빈 글자 포함) → 셋 다. 그 밖 글자(옛 이름 parse·structure·retrieval·오타·앞뒤 공백)는 빈 묶음(사용자 10-27 Q2). 이미지 안
    빈 글자 `RAG_MODULE=`도 빈 묶음(VS7d R-6). 영구 다리(pin_env)·시작 관문(require_run_env)이 쓴다 — 관계없는 앱 절은 검증하지 않는다."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    in_image = IN_IMAGE if in_image is None else in_image
    mod = environ.get("RAG_MODULE")  # env 남김 — 내부 신호(5-3 H)
    if mod is None or (mod == "" and not in_image):
        return SECTIONS
    if mod in ("parse", "structure", "retrieval"):  # VS6b R-12 — 옛 이미지 이름(S6b 전 RAG_MODULE) — 이름만 알림
        _warn_once(
            f"[설정] RAG_MODULE={mod} — S6b 전 옛 이미지 이름(지금은 pipeline·mcp). 새 이미지 판으로 바꿔야 함(이 이미지 절을 읽지 않음)"
        )
    return IMAGE_SECTIONS.get(mod, ())


def _server_env(environ, path):
    """서버(dev·prd)로 도는가 — env RUN_ENV, 없으면 설정 파일의 common.run_env(못 읽으면 모름 = local처럼)."""
    run = environ.get("RUN_ENV") or None
    if run is None and path is not None:
        try:
            run = resolve_run_env(environ)
        except SettingsError:
            return False
    return run in SERVER_ENVS


def _pinned(cls):
    """{경로: env 이름} — 엔진·인계 파일이 env로 읽는 칸(pinned)."""
    return {p: env_name(f) for p, f, _ in walk(cls) if _extra(f, "pinned")}


@functools.cache
def _pinned_names(cls):
    return tuple(_pinned(cls).values())


def pin_env(environ=None):
    """영구 다리(D-028 ⑤ — import common 때 한 번, common/__init__.py가 부름): 엔진·인계 파일이 env로 읽는 칸(pinned 28키)을 설정 파일 값
    (+ 이 이미지 기본값 — B-2)으로 env에 낸다. env에 이미 있는 이름은 그대로(부모 프로세스·put()이 넘긴 값). 이 이미지 절만(U-a), pinned
    칸만 검증한다(다른 칸 오타는 그 앱 설정 객체·시작 관문이 알림 — 호스트 export가 다른 앱 절 오타로 멈추지 않게). 파일을 못 읽거나 pinned
    칸이 틀리면 서버(dev·prd)는 SettingsError(시작 실패 — STRICT, S7b c안), local은 경고 뒤 계속. 옛 env 이름(설정 칸 — pinned·호스트
    칸 빼고)이 env에 있으면 읽지 않고 이름만 한 번 알린다. 반환: 낸 이름 수."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    allowed = image_sections(environ)
    run = environ.get("RUN_ENV") or None
    path = find_file(environ, run if run in RUN_ENVS else None)
    if not allowed:
        if path is not None:
            _warn_once("[설정] RAG_MODULE 모름(pipeline·mcp가 아님 — 이미지 안 빈 글자 포함) — 영구 다리 건너뜀(env로 아무 값도 안 냄)")
        return 0
    cls, _ = section_class(allowed)
    pins = _pinned(cls)
    legacy = sorted(n for n in _env_map(cls, False) if n in environ and n not in pins.values() and n != "RUN_ENV") if environ else []
    legacy = [
        n for n in legacy if n not in _env_map(cls, True) and n not in SHELL_EXPORTS
    ]  # 호스트 칸 이름(load_settings가 셸에 냄)·셸 export 이름은 빼고 — 이 이미지 절만(다른 앱 설정 모듈 import 안 함, U-a)
    if legacy:
        _warn_once(f"[설정] env의 옛 설정 이름은 읽지 않음(S7e2 — settings.yaml 칸·덮기 파일로): {' '.join(legacy)}")
    st = None
    if path is not None:
        try:
            doc, over = read_settings(path)
            sub = {}
            for p in pins:
                v = _peek(doc, p)
                if v is not None:
                    _set_path(sub, p, v)
            run = _peek(
                doc, "common.run_env"
            )  # VS7e3 R-2 — 파일에만 run_env를 둔 서버도 덮기 파일 pinned 값 형식 오류를 거부하게(load()의 서버 판정)
            if run is not None and str(run) in RUN_ENVS:  # 모르는 글자는 넣지 않음(전처럼 — 앱 설정 객체·시작 관문이 거부)
                _set_path(sub, "common.run_env", run)
            over = {k: v for k, v in over.items() if k in pins.values()}
            st = load(cls, file=path, environ=environ, strict=False, require_file=False, lenient_run_env=True, _read=(sub, over))
        except SettingsError as e:
            if (
                _server_env(environ, path) and environ.get("SETTINGS_LENIENT") != "1"
            ):  # 내부 신호 — entrypoint가 점검 명령(check·selftest 등)에만 줌
                raise
            _warn_once(f"[설정] 영구 다리 건너뜀(엔진·인계 칸은 기본값 — local 또는 점검 명령) — {e}")
            st = None
    fields = {p: f for p, f, _ in walk(cls)}
    n = 0
    for p, name in pins.items():
        if name in environ:
            continue
        v = _get(st, p) if st is not None and _is_set(st, p) else None
        if v is None:
            v = IMAGE_DEFAULTS.get(name)
        s = render(v, secrets=True, sep=list_sep(fields[p]))
        if s is not None:
            environ[name] = s  # env 남김 — 영구 다리(엔진·인계 파일이 env로 읽음, D-028 ⑤)
            if environ is os.environ:  # env 남김 — 영구 다리
                PINNED.add(name)
            n += 1
    return n


PINNED: set = set()  # 이 프로세스에서 pin_env가 env에 낸 이름(사용자 env와 가름 — common.config.boot)
# 호스트 셸이 늘 export하는 설정 이름(settings_env.sh load_settings·systemd Environment=) — 앱 설정 칸과 이름이 같지만 셸 자신이 쓰는 값이라
# "env의 옛 설정 이름" 경고에서 뺀다(VS7e2 R-5 — 운영자에게 매번 거짓 경고). 앱은 그 칸도 settings.yaml에서만 읽는다.
SHELL_EXPORTS = ("SERVER_ENV_DIR",)


def external_models_allowed(run_env):
    """RUN_ENV 기준 외부 모델 허용 — 정확히 local일 때만 지금 가드(외부 허용 스위치·NO_PAID_CALLS·상한)대로. 없음(env·설정 파일 모두 —
    이미지 selftest·관문 면제 점검 명령·관문 없는 스크립트)·dev·prd·모르는 글자(prod·PRD·' local' 등)는 서버로 보고 거부
    (VS7b U-1 — 코디네이터 답 b, 안전한 쪽). guard.py가 guard_run_env()(모르는 글자 그대로)로 부른다(S7b·S7c1)."""
    return run_env == "local"


APP_MODULES = {"pipeline": ("pipeline.config", "PipelineAppSettings"), "mcp": ("mcp_server.config", "McpAppSettings")}


def _module_loading(mod, attr):
    """그 앱 설정 모듈이 지금 import 중인가(sys.modules에 있지만 뿌리 클래스가 아직 없음 — 순환)."""
    loading = sys.modules.get(mod)
    return loading is not None and not hasattr(loading, attr)


def _names_loading():
    """앱 설정 모듈 하나라도 import 중인가 — 그동안 _all_names()는 그 앱 칸 이름이 빠진 묶음이다(VS7e3 R-1)."""
    return any(_module_loading(mod, attr) for mod, attr in APP_MODULES.values())


def app_classes(names=("pipeline", "mcp")):
    """앱 설정 뿌리 클래스 — 두 앱을 함께 보는 도구(export·migrate·keyscan 대조·덮기 파일)만 쓴다. common은 앱 코드를 정적으로
    import하지 않으므로(check_modules ②) 문자열로 부르고, 이 이미지에 없는 앱(mcp 이미지의 pipeline 등)은 건너뛴다."""
    import importlib

    out = {}
    for n in names:
        mod, attr = APP_MODULES[n]
        if _module_loading(mod, attr):
            continue
        try:
            out[n] = getattr(importlib.import_module(mod), attr)
        except ImportError:
            continue
    return out


# ── 덮기 파일 — 같은 프로세스(put)·자식(child_env)·PC 한 번 실행(common.config.overrides) (S7e2, 사용자 10-28) ─────────────
_GEN = [0]  # put()이 올림 — 모든 Cache가 다음 get()에서 다시 읽음
_EDW_READ_ONLY = [False]  # edw_read_only() — 이 프로세스는 EDW 읽기 계정만(CommonConnectionsRdb가 봄)


def edw_read_only(on=True):
    """이 프로세스는 EDW 읽기 계정만 본다 — 공용 settings.yaml에 쓰기 계정이 있어도 설정 객체에서 비운다(사용자 10-29 "정해진
    항목만" — 검색 MCP 시작 때 부름, docs/prd/ops.md#op-03). 파일은 바꾸지 않고, 모든 설정 캐시가 다음 읽기에서 다시 읽는다."""
    _EDW_READ_ONLY[0] = on
    _GEN[0] += 1


def _all_names():
    """{옛 env 이름: pinned 여부} — common + 이 이미지에 있는 앱 칸(호스트 칸 빼고). 앱 모듈 묶음마다 한 번만 걷는다(리뷰 S7e2)."""
    classes = app_classes()
    key = tuple(sorted(classes))
    if key not in _ALL_NAMES:
        _ALL_NAMES[key] = _walk_names((CommonAppSettings, *classes.values()))
    return _ALL_NAMES[key]


_ALL_NAMES: dict = {}


def _walk_names(classes):
    out = {}
    for cls in classes:
        for p, f, _ in walk(cls):
            e = env_name(f)
            if e and not is_host(p):
                out[e] = out.get(e, False) or bool(_extra(f, "pinned"))
    return out


def _check_names(names):
    known = _all_names()
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise KeyError(f"설정 칸이 없는 이름 {unknown}")
    return known


def overridden(environ=None):
    """지금 설정 파일(SETTINGS_FILE 덮기 파일 사슬)의 overrides에 든 이름 — 공유 settings.yaml 위에 한 번 덮은 값(옛 "사용자가 env로 준 값"
    자리 — mcp_eval client_only_env, VS7e2 R-11). 덮기 파일이 아니거나 못 읽으면 빈 묶음."""
    environ = os.environ if environ is None else environ  # env 남김 — 설정 파일 자리 신호
    run = environ.get("RUN_ENV") or None
    path = find_file(environ, run if run in RUN_ENVS else None)
    if path is None:
        return frozenset()
    try:
        return frozenset(read_settings(path)[1])
    except SettingsError:
        return frozenset()


def _env_text(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def overlay_file(names, base=None, environ=None):
    """덮기 파일을 만든다 — base(설정 파일 — 없으면 지금 SETTINGS_FILE·로컬 파일)를 가리키고 names({옛 env 이름: 값|None})를 overrides로 든
    yaml을 임시 파일(mktemp — 권한 600)로 쓴다. 원본 내용(비밀)은 복사하지 않는다(base로 가리킴 — refactor.md C-46). base가 덮기 파일이면
    그 base·overrides를 이어받아 한 단으로. 지우는 것은 부른 쪽 몫 — put·child_env는 이 프로세스가 끝날 때(pl-27 exitclean, 자식을 먼저
    끝낸 뒤), isolated는 블록이 끝날 때, overrides 도구(경로를 다른 프로세스에 넘김)는 안 지움. 반환: 경로."""
    import tempfile

    import yaml

    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    if base is None:
        run = environ.get("RUN_ENV") or None
        base = find_file(environ, run if run in RUN_ENVS else None)
    over = {}
    if base is not None:
        base = Path(base).absolute()  # resolve 아님 — 컨테이너 안 경로(/etc/rag/…)를 호스트 심볼릭 링크(/private/etc)로 바꾸지 않게
        try:
            raw = read_yaml(base)
            inherited = (
                {str(k): _override_value(k, v, base) for k, v in (raw.get("overrides") or {}).items()}
                if raw and set(raw) <= set(OVERLAY_KEYS)
                else None
            )
        except SettingsError:
            raw = inherited = None  # 읽기·형식 오류는 그 파일을 base로 두어 읽는 쪽(load)이 알림
        if inherited is not None:
            # 이어받은 값: 따옴표 글자는 글자로, 손으로 쓴 YAML 값(true·false·숫자)은 그 꼴 그대로 다시 씀(읽는 규칙이 펼치기 전과 같게 — VS7e2 R-2)
            over = {k: _Raw.of(v) if isinstance(v, YamlScalar) else v for k, v in inherited.items()}
            nb = Path(str(raw["base"])) if raw.get("base") else None
            base = (
                (nb if nb.is_absolute() else base.parent / nb).absolute() if nb is not None else None
            )  # 상대 base는 그 덮기 파일 폴더 기준(read_settings와 같게 — 리뷰 S7e2)
    over.update({k: _env_text(v) for k, v in names.items()})
    doc = ({"base": str(base)} if base is not None else {}) | {"overrides": over}
    fd, p = tempfile.mkstemp(prefix="settings-", suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("# 덮기 파일(common.config.settings.overlay_file — S7e2) — base 위에 overrides를 겹쳐 읽음\n")
        fh.write(yaml.dump(doc, Dumper=_raw_dumper(), allow_unicode=True, sort_keys=False))
    os.chmod(p, 0o600)
    return Path(p)


class _Raw(str):
    """손으로 쓴 따옴표 없는 YAML 값을 펼쳐 쓸 때 쓴 글자·꼴 그대로 다시 쓰기(1.10·0123·true를 푼 값 1.1·83·True로 바꿔 쓰지 않게 —
    다시 읽으면 같은 YamlScalar, 리뷰 S7e3)."""

    tag = None
    _TAGS = ((bool, "bool"), (int, "int"), (float, "float"))

    @classmethod
    def of(cls, v):
        r = cls(str(v))
        r.tag = "tag:yaml.org,2002:" + next((n for t, n in cls._TAGS if isinstance(v.value, t)), "timestamp")
        return r


@functools.cache
def _raw_dumper():
    import yaml

    class Dumper(yaml.SafeDumper):
        pass

    Dumper.add_representer(_Raw, lambda d, v: d.represent_scalar(v.tag, str(v)))
    return Dumper


def _pin_names(env, names, known):
    for k, v in names.items():
        if known.get(k):  # 엔진·인계 칸 — 그 파일들은 env를 읽음(영구 다리)
            if v is None:
                env.pop(k, None)
            else:
                env[k] = _env_text(v)


def put(**names):
    """이 프로세스의 설정 값을 바꾼다(옛 `os.environ[X] = v` 자리 — S7e2): 덮기 파일을 만들어 SETTINGS_FILE을 그것으로 바꾸고(뒤에 띄우는
    자식도 같은 값을 받음), 모든 설정 캐시가 다음 읽기에서 다시 읽게 한다. 엔진·인계 칸은 env에도 쓴다. None = 그 칸 비움(기본값).
    칸이 없는 이름은 KeyError. 반환: 덮기 파일 경로."""
    known = _check_names(names)
    p = exitclean.remove_at_exit(overlay_file(names))  # pl-27 — 이 프로세스가 끝날 때 지움
    os.environ["SETTINGS_FILE"] = str(p)  # env 남김 — 설정 파일 자리 신호(5-2)
    _pin_names(os.environ, names, known)  # env 남김 — 영구 다리
    _GEN[0] += 1
    return p


def child_env(base=None, **names):
    """자식 프로세스에 줄 env(옛 `dict(os.environ, X=v)` 자리 — S7e2): base env(없으면 os.environ) 사본에, names를 덮은 덮기 파일을
    SETTINGS_FILE로 넣는다(부모 값은 그대로). 엔진·인계 칸은 env에도. names가 없으면 사본만."""
    env = dict(os.environ if base is None else base)  # env 남김 — 하위 프로세스
    if names:
        known = _check_names(names)
        env["SETTINGS_FILE"] = str(exitclean.remove_at_exit(overlay_file(names, environ=env)))  # pl-27 — 이 프로세스가 끝날 때 지움
        _pin_names(env, names, known)
    return env


@contextlib.contextmanager
def isolated(**names):
    """시험용 — 지금 설정 위에 names를 덮은 덮기 파일로 바꿔 끼우고(그 안에서 부른 put()까지 그 동안만), 끝나면 SETTINGS_FILE·엔진/인계 env를
    되돌린다(옛 시험의 os.environ 저장·복원 자리 — S7e2). None = 그 칸 비움."""
    known = _check_names(names)
    keep = {k: os.environ.get(k) for k in ("SETTINGS_FILE", *(n for n, pin in known.items() if pin))}  # env 남김 — 시험
    p = overlay_file(names)
    os.environ["SETTINGS_FILE"] = str(p)  # env 남김 — 설정 파일 자리 신호(시험 — 끝나면 되돌림)
    _pin_names(os.environ, names, known)  # env 남김 — 영구 다리
    _GEN[0] += 1
    try:
        yield
    finally:
        p.unlink(missing_ok=True)  # pl-27 — 블록 안에서만 쓰는 파일
        for k, v in keep.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)  # env 남김 — 시험: 신호·엔진/인계 env 되돌림
        _GEN[0] += 1


def _load_app(cls):
    """설정 캐시가 읽는 길 — 파일이 틀리면 서버는 실패(STRICT), local은 경고 뒤 기본값(VS7e1 U-1 — 사용자 10-28: local은 지금처럼)."""
    try:
        return load(cls, strict=False, require_file=False, lenient_run_env=True)
    except SettingsError as e:
        if (
            _server_env(os.environ, find_file(os.environ, None)) and os.environ.get("SETTINGS_LENIENT") != "1"
        ):  # env 남김 — RUN_ENV 신호 · 내부 신호(점검 명령)
            raise
        why = "점검 명령" if os.environ.get("SETTINGS_LENIENT") == "1" else "local"  # env 남김 — 내부 신호(점검 명령)
        _warn_once(f"[설정] 설정 파일을 쓰지 않음({why} — 기본값으로): {e}")  # VS7e2 R-9 — 서버 점검 명령을 local로 적지 않게
        return load(cls, use_file=False, strict=False, require_file=False, lenient_run_env=True)


class Cache:
    """앱 설정 캐시 — get()은 처음 한 번 읽고, 신호(SETTINGS_FILE·RUN_ENV)가 바뀌거나 put()이 부르면 다시 읽는다. override()·env()는
    시험 동안만 바꿔 끼운다(os.environ은 건드리지 않음)."""

    def __init__(self, app_cls):
        self.app_cls = app_cls
        self._value = None
        self._key = None
        self._fixed = False
        self._names = None

    def get(self):
        if self._fixed:
            return self._value
        key = (
            os.environ.get("SETTINGS_FILE"),
            os.environ.get("RUN_ENV"),
            _GEN[0],  # env 남김 — 설정 파일 자리 신호 · 신호(5-2)
            tuple(os.environ.get(n) for n in _pinned_names(self.app_cls)),
        )  # env 남김 — 영구 다리(엔진·인계 칸 env가 바뀌면 다시 읽음)
        if self._value is None or key != self._key:
            self._value, self._key = _load_app(self.app_cls), key
        return self._value

    def reset(self):
        self._value = None
        self._fixed = False

    @contextlib.contextmanager
    def override(self, settings=None, **load_kw):
        """with CFG.override(data={...}) — 시험 동안 바꿔 끼움(load_kw는 load() 인자, settings=이미 만든 객체)."""
        saved = self._value, self._fixed, self._key
        self._value = settings if settings is not None else load(self.app_cls, **load_kw)
        self._fixed = True
        try:
            yield self._value
        finally:
            self._value, self._fixed, self._key = saved

    @contextlib.contextmanager
    def env(self, **names):
        """with COMMON.env(LLM_MODEL="mock", NO_PAID_CALLS=None): — 시험용. 설정 파일 위에 옛 env 이름 값을 덮어(None = 그 칸 비움 — 기본값,
        겹쳐 쓰면 바깥 env() 값 포함, 값은 옛 env 글자 꼴로 판정) 만든 객체를 그동안 바꿔 끼운다. RUN_ENV는 신호로 덮는다.
        os.environ은 건드리지 않는다(이 객체를 읽는 코드만 바뀜)."""
        base = dict(self._names or {})
        base.update({k: _env_text(v) for k, v in names.items()})
        environ = dict(os.environ)  # env 남김 — 시험
        data = None
        if "RUN_ENV" in base:
            environ.pop("RUN_ENV", None) if base["RUN_ENV"] is None else environ.__setitem__("RUN_ENV", base["RUN_ENV"])
            if base["RUN_ENV"] is None:
                data = {"common": {"run_env": None}}  # 없음 = 설정 파일의 common.run_env도 비움(옛 env 기반 시험과 같은 뜻)
        saved = self._names
        self._names = base
        try:
            with self.override(names=base, data=data, environ=environ, strict=False, require_file=False, lenient_run_env=True) as st:
                yield st
        finally:
            self._names = saved


# ── common 절 모델 ─────────────────────────────────────────────────────────────────────────
# (S7a-MODELS) — 아래는 부록 D 분류표로 만든 칸 목록. 칸을 더하거나 옮기면 refactor_plan 부록 D·settings.sample.yaml을 함께 고친다.


class CommonConnectionsObjectStorage(Section):
    access_key: SecretStr | None = F(None, "OS_ACCESS_KEY", "Object Storage(S3) 액세스 키")
    endpoint: str | None = F(None, "OS_ENDPOINT", "Object Storage(S3 호환) 엔드포인트 URL — 비면 boto3 기본")
    region: str | None = F("us-east-1", "OS_REGION", "Object Storage 리전 이름")
    secret_key: SecretStr | None = F(None, "OS_SECRET_KEY", "Object Storage(S3) 시크릿 키")
    verify_tls: str | None = F("1", "OS_VERIFY_TLS", "TLS 인증서 검증(1=검증, 0=끔, 그 밖 문자열=CA 파일 경로)", blank="keep")


class CommonConnectionsParsingMeta(Section):
    REMOVED = frozenset(
        {"connect_kwargs", "database", "host", "password", "port", "sqlite", "user"}
    )  # 사용자 10-29 — 접속은 common.connections.rdb(ops.md#op-03)
    table: str | None = F("AI.ParsingMeta", "PM_TABLE", "parsing-meta를 쓸 EDW 표 이름(스키마.표, 영문·숫자·_)", blank="keep")


class CommonConnectionsRdbRead(Section):
    password: SecretStr | None = F(None, "RDB_READ_PASSWORD", "EDW 읽기 계정 비밀번호")
    user: str | None = F(
        None, "RDB_READ_USER", "EDW 읽기 계정 이름 — 원천 목록·FileStorageMap·ParsingMeta 조회·query_edw(검색 MCP는 이 계정만)"
    )


class CommonConnectionsRdbWrite(Section):
    password: SecretStr | None = F(None, "RDB_WRITE_PASSWORD", "EDW 쓰기 계정 비밀번호")
    user: str | None = F(None, "RDB_WRITE_USER", "EDW 쓰기 계정 이름 — ParsingMeta 게시(INSERT·UPDATE)만")


class CommonConnectionsRdb(Section):
    """EDW(SQL Server) 접속 하나 — 서버·DB는 하나, 계정은 읽기·쓰기 둘(사용자 10-29, docs/prd/ops.md#op-03)."""

    connect_kwargs: SecretStr | None = F(None, "RDB_CONNECT_KWARGS", "EDW pymssql 연결에 더할 추가 인자(JSON 객체 — TLS·로그인 시간 등)")
    database: str | None = F(None, "RDB_DATABASE", "EDW 데이터베이스 이름")
    host: str | None = F(None, "RDB_HOST", "EDW 서버 주소(호스트)")
    port: Port | None = F(1433, "RDB_PORT", "EDW 포트")
    sqlite: str | None = F(
        None,
        "RDB_SQLITE",
        "시험용 가짜 EDW(SQLite 파일 하나 — 모든 표) — 있으면 실제 EDW 대신 씀 · PC(RUN_ENV=local) 전용, 서버에서는 시작 거부",
    )
    read: CommonConnectionsRdbRead = Field(default_factory=CommonConnectionsRdbRead)
    write: CommonConnectionsRdbWrite = Field(default_factory=CommonConnectionsRdbWrite)

    @model_validator(mode="after")
    def _read_only_process(self):
        """검색 MCP 프로세스(edw_read_only())는 쓰기 계정 칸을 보지 않는다 — 공용 settings.yaml에 있어도 설정 객체에서 비움(사용자 10-29)."""
        if _EDW_READ_ONLY[0]:
            self.write = CommonConnectionsRdbWrite()
        return self


class CommonConnectionsPg(Section):
    conn_file: str | None = F(None, "PG_CONN_FILE", "PostgreSQL 접속 정보를 KEY=VALUE로 담은 파일 경로(환경변수가 덮음)")
    connect_timeout: int | None = F(10, "PG_CONNECT_TIMEOUT", "PostgreSQL 연결 시도 제한 시간")
    db: str | None = F("rag", "PG_DB", "PostgreSQL 데이터베이스 이름")
    host: str | None = F(
        None,
        "PG_HOST",
        "PostgreSQL 서버 주소 — PG_HOST·PG_PORT·PG_CONN_FILE이 모두 비면 docker ps로 pgvector를 자동 탐지, 그래도 없으면 127.0.0.1(common/store/pg.py)",
    )
    password: SecretStr | None = F(None, "PG_PASSWORD", "PostgreSQL 비밀번호")
    pool_max: int | None = F(8, "PG_POOL_MAX", "검색 MCP PostgreSQL 연결 풀 최대 연결 수")
    port: Port | None = F(None, "PG_PORT", "PostgreSQL 포트 — 비면 자동 탐지(PG_HOST 설명), 그래도 없으면 5432")
    db_schema: str | None = F(None, "PG_SCHEMA", "pgvector 기본 스키마 이름(소문자·숫자·_)")
    standin_dir: str | None = F(None, "PG_STANDIN_DIR", "PG 접속 정보가 없을 때 쓰는 로컬 대체 DB(sqlite) 폴더")
    user: str | None = F("rag", "PG_USER", "PostgreSQL 접속 계정 이름")


class CommonDevDocker(Section):
    mcp_publish_port: Port | None = F(18765, "MCP_PUBLISH_PORT", "시험 compose에서 MCP를 호스트에 게시할 포트")
    minio_image: str | None = F("bitnamilegacy/minio:latest", "MINIO_IMAGE", "시험용 minio 이미지")
    minio_publish_port: Port | None = F(19000, "MINIO_PUBLISH_PORT", "시험 minio를 호스트에 게시할 포트")
    pg_bind: str | None = F("127.0.0.1", "PG_BIND", "시험 PostgreSQL 컨테이너를 호스트에 게시할 바인드 주소")
    pg_effective_cache: str | None = F("12GB", "PG_EFFECTIVE_CACHE", "시험 PG effective_cache_size")
    pg_image: str | None = F("pgvector/pgvector:pg16", "PG_IMAGE", "시험 PostgreSQL(pgvector) 이미지")
    pg_maint_mem: str | None = F("2GB", "PG_MAINT_MEM", "시험 PG maintenance_work_mem(HNSW 생성)")
    pg_max_conn: int | None = F(50, "PG_MAX_CONN", "시험 PG max_connections")
    pg_mem_limit: str | None = F(None, "PG_MEM_LIMIT", "시험 PG 컨테이너 메모리 상한")
    pg_parallel: int | None = F(2, "PG_PARALLEL", "시험 PG 병렬 작업자 수(maintenance·gather 둘 다)")
    pg_shared_buffers: str | None = F("4GB", "PG_SHARED_BUFFERS", "시험 PG shared_buffers")
    pg_shm: str | None = F("3g", "PG_SHM", "시험 PG 컨테이너 공유 메모리(shm_size)")
    pg_work_mem: str | None = F("64MB", "PG_WORK_MEM", "시험 PG work_mem")
    postgres_db: str | None = F("rag", "POSTGRES_DB", "PG 컨테이너 안에서 healthcheck가 쓰는 DB 이름(compose가 PG_DB로 채움)")
    postgres_user: str | None = F("rag", "POSTGRES_USER", "PG 컨테이너 안에서 healthcheck가 쓰는 계정(compose가 PG_USER로 채움)")
    smoke_settings: str | None = F(
        None,
        "SMOKE_SETTINGS",
        "스모크 시험 컨테이너가 붙여 읽는 설정 파일(settings.yaml) 경로 — MCP 토큰·임베딩·Object Storage 키 등(S7e1 — 옛 SMOKE_ENV env 파일)",
    )
    smoke_keep: bool | None = F(False, "SMOKE_KEEP", "1이면 시험 끝나도 pg·minio 컨테이너를 남김")
    smoke_limit: int | None = F(0, "SMOKE_LIMIT", "시험에서 파싱할 문서 수 상한(0이면 제한 없음)")
    smoke_mode: str | None = F("prod", "SMOKE_MODE", "시험 파싱 모드(prod|test — test는 형식별 표본)")
    smoke_nightly: bool | None = F(False, "SMOKE_NIGHTLY", "1이면 자정 배치 모양(parse·publish만, pg·구조화·적재·MCP 생략)")
    smoke_pg_password: SecretStr | None = F(
        None, "SMOKE_PG_PASSWORD", "시험 PostgreSQL 비밀번호(compose.test.yml이 컨테이너 PG_PASSWORD로 넘김 — S7e1)"
    )
    smoke_pm_bucket: str | None = F("rag-publish", "SMOKE_PM_BUCKET", "시험 결과 게시용 minio 버킷 이름")
    smoke_source: str | None = F("/data/docs", "SMOKE_SOURCE", "시험 원천 위치(/data/docs 또는 s3://버킷/접두)")


class CommonModelsEmbed(Section):
    allow_external: bool | None = F(False, "EMBED_ALLOW_EXTERNAL", "임베딩 외부 주소 허용(=1이면 열림, RUN_ENV=local일 때만)", on=("1",))
    api_key: SecretStr | None = F(None, "EMBED_API_KEY", "임베딩 엔드포인트 API 키(있을 때만 Authorization 헤더로 보냄)")
    base_url: str | None = F(None, "EMBED_BASE_URL", "임베딩 엔드포인트 주소(OpenAI 호환 …/v1)")
    dim: int | None = F(4096, "EMBED_DIM", "ping_models 점검에서 기대하는 임베딩 차원 수")
    est_usd: float | None = F(0.001, "EMBED_EST_USD", "임베딩 호출 1건당 예상 비용($) — 예산 선차감용")
    model: str | None = F(None, "EMBED_MODEL", "임베딩 모델 이름(색인과 같아야 함 — 질의 임베딩·캐시 열쇠에도 씀)")
    query_cache: str | None = F(None, "EMBED_QUERY_CACHE", "질의 임베딩 캐시 sqlite 경로(0이면 캐시 끔)")
    query_cache_max: int | None = F(20000, "EMBED_QUERY_CACHE_MAX", "질의 임베딩 캐시 최대 행 수(넘으면 오래된 것부터 삭제, 0이면 무제한)")
    query_prefix: str | None = F(None, "EMBED_QUERY_PREFIX", "질의 임베딩 앞에 붙이는 지시 문구(예: 'Instruct: …/nQuery: ')")
    timeout: int | None = F(60, "EMBED_TIMEOUT", "임베딩 API 호출 제한 시간(초)")


class CommonModelsGuard(Section):
    REMOVED = frozenset({"synthetic_truth"})  # 사용자 10-29 — 합성 문서 선언 잠금 삭제(옛 migrate C-35가 옮겨 둔 서버 파일 보호)
    budget_usd: float | None = F(
        None,
        "LLM_BUDGET_USD",
        "유료(외부) 모델 호출 누적 비용 상한($) — 넘으면 호출 안 함, 비우면 상한 없음(nan·inf는 형식 오류)",
        allow_inf_nan=False,
    )
    external_max_docs: int | None = F(10, "EXTERNAL_MAX_DOCS", "외부 모델 사용 시(scope=func) 허용 문서 수 상한(개)")
    external_max_questions: int | None = F(20, "EXTERNAL_MAX_QUESTIONS", "외부 모델 사용 시(scope=func) 허용 질문 수 상한(개)")
    external_scope: str | None = F(
        "func", "EXTERNAL_SCOPE", "외부 모델 사용 범위 — 'e2e'가 아니면 전부 func(기능 시험, 문서·질문 수 상한 적용)", blank="keep"
    )
    internal_host_suffixes: CsvList | None = F(
        [], "INTERNAL_HOST_SUFFIXES", "내부망으로 인정할 호스트 이름 접미사 목록(쉼표 구분, 실제 주소가 사설일 때만)"
    )
    internal_ip_ranges: CsvList | None = F([], "INTERNAL_IP_RANGES", "사설(RFC1918) 밖의 사내 IP 대역 CIDR 목록(쉼표 구분)")
    max_calls: int | None = F(0, "LLM_MAX_CALLS", "LLM 호출 수 상한(개) — 0이면 무제한")
    no_paid_calls: bool | None = F(False, "NO_PAID_CALLS", "=1이면 외부(유료) 주소 호출 자체를 거부", on=("1",))
    spend_file: str | None = F(None, "LLM_SPEND_FILE", "지출 장부 파일 경로(호출마다 금액 한 줄 — 프로세스·실행 전체가 공유)")


class CommonModelsLlm(Section):
    allow_external: bool | None = F(False, "LLM_ALLOW_EXTERNAL", "LLM 외부 주소 허용(=1, RUN_ENV=local일 때만)", on=("1",))
    api_key: SecretStr | None = F(None, "LLM_API_KEY", "LLM 엔드포인트 API 키(있을 때만 사용)")
    base_url: str | None = F(None, "LLM_BASE_URL", "LLM 엔드포인트 주소(OpenAI 호환 …/v1)")
    cache_dir: str | None = F(None, "LLM_CACHE_DIR", "LLM 응답 캐시 폴더(요청 해시별 json)")
    empty_retry: bool | None = F(
        True, "LLM_EMPTY_RETRY", "빈 응답(생각이 토큰 소진) 안전망 — =0이면 끔, 그 밖이면 max_tokens×4로 1회 재요청", off=("0",)
    )
    empty_retry_max: int | None = F(8000, "LLM_EMPTY_RETRY_MAX", "빈 응답 재요청 때 max_tokens 상한(토큰)")
    est_usd: float | None = F(0.01, "LLM_EST_USD", "LLM 한 턴(run_agent)당 예상 비용($) — 예산 선차감용")
    extra_body: JsonValue | None = F(
        None, "LLM_EXTRA_BODY", "LLM 요청 본문에 합칠 JSON 객체(예: 생각 끄기 {'reasoning':{'enabled':false}})"
    )
    max_concurrency: float | None = F(
        8, "LLM_MAX_CONCURRENCY", "LLM 동시 요청 총량(실험 도구 answer의 workers×inner_workers 상한)", unset=("auto",)
    )
    model: str | None = F(None, "LLM_MODEL", "LLM 모델 이름")
    price_in: float | None = F(None, "LLM_PRICE_IN", "LLM 입력 단가($/백만 토큰) — 내장 가격표보다 우선")
    price_out: float | None = F(None, "LLM_PRICE_OUT", "LLM 출력 단가($/백만 토큰) — 내장 가격표보다 우선")
    rpm: int | None = F(0, "LLM_RPM", "LLM 분당 호출 상한(건) — 0이면 무제한")
    timeout: float | None = F(120.0, "LLM_TIMEOUT", "LLM 호출 제한 시간(초) — 호출자가 timeout을 주면 그 값이 우선")


class CommonModelsOcrvlm(Section):
    allow_external: bool | None = F(False, "OCRVLM_ALLOW_EXTERNAL", "OCR 전용 VLM 외부 주소 허용(=1, RUN_ENV=local일 때만)", on=("1",))
    api_key: SecretStr | None = F(None, "OCRVLM_API_KEY", "OCR 전용 VLM 엔드포인트 API 키(있을 때만)")
    base_url: str | None = F(None, "OCRVLM_BASE_URL", "OCR 전용 VLM 엔드포인트 주소(OpenAI 호환 …/v1)")
    est_usd: float | None = F(0.01, "OCRVLM_EST_USD", "OCR 전용 VLM 호출 1건당 예상 비용($) — 예산 선차감용")
    model: str | None = F(None, "OCRVLM_MODEL", "OCR 전용 VLM 모델 이름(0.9B급 GLM-OCR·PaddleOCR-VL 등)", pinned="engine")


class CommonModelsTransport(Section):
    connect_timeout: float | None = F(10.0, "MODEL_CONNECT_TIMEOUT", "모델 서버 연결(connect) 전용 제한 시간(초) — 0 이하면 끔")
    down_after: int | None = F(3, "MODEL_DOWN_AFTER", "연속 연결 실패 몇 번이면 그 주소를 '다운'으로 보는가(회)")
    down_cooldown: float | None = F(300.0, "MODEL_DOWN_COOLDOWN", "'다운' 판정 뒤 네트워크를 보내지 않고 즉시 거부하는 시간(초)")
    ping_timeout: int | None = F(60, "PING_TIMEOUT", "ping_models 점검의 호출 제한 시간(초)")
    transport: str | None = F("adk", "MODEL_TRANSPORT", "모델 호출 전송 방식 — adk(기본) 또는 http(urllib 롤백 경로)")


class CommonModelsVlm(Section):
    allow_external: bool | None = F(False, "VLM_ALLOW_EXTERNAL", "VLM 외부 주소 허용(=1, RUN_ENV=local일 때만)", on=("1",))
    api_key: SecretStr | None = F(None, "VLM_API_KEY", "VLM 엔드포인트 API 키(있을 때만)", pinned="engine")
    base_url: str | None = F(None, "VLM_BASE_URL", "VLM 엔드포인트 주소(OpenAI 호환 …/v1)", pinned="engine")
    concurrency: int | None = F(4, "VLM_CONCURRENCY", "한 문서의 쪽(그림) VLM 동시 요청 수(개)", pinned="engine")
    est_usd: float | None = F(0.02, "VLM_EST_USD", "VLM 호출 1건당 예상 비용($) — 예산 선차감용")
    extra_body: JsonValue | None = F(
        None, "VLM_EXTRA_BODY", "VLM(·OCRVLM) 요청 본문에 합칠 JSON 객체(예: chat_template_kwargs로 생각 끄기)"
    )
    max_concurrency: float | None = F(
        8, "VLM_MAX_CONCURRENCY", "공유 VLM 서버 동시 요청 총량 상한(문서 동시 수 × 쪽 동시 수가 이 값을 못 넘게 줄임)", unset=("auto",)
    )
    model: str | None = F(None, "VLM_MODEL", "VLM 모델 이름", pinned="engine")
    model_alt: str | None = F(None, "VLM_MODEL_ALT", "그림 검토 판정용 VLM 모델 이름(없으면 VLM_MODEL과 같음)")
    retry: int | None = F(1, "VLM_RETRY", "VLM 쪽 호출 시간 초과·연결 오류 때 재시도 횟수(회)", pinned="engine")
    timeout: int | None = F(180, "VLM_TIMEOUT", "VLM 쪽당 호출 제한 시간(초)", pinned="engine")


class CommonDev(Section):
    exp_store: str | None = F(None, "EXP_STORE", "PC 평가(stack_matrix) 결과 저장소 폴더")
    llm_est_in_tokens: int | None = F(1500, "LLM_EST_IN_TOKENS", "stack_matrix 비용 추정에서 질문당 입력 토큰 가정")
    llm_est_out_tokens: int | None = F(None, "LLM_EST_OUT_TOKENS", "stack_matrix 비용 추정에서 질문당 출력 토큰 가정")
    llm_fake: bool | None = F(False, "LLM_FAKE", "1이면 LLM 호출을 네트워크·캐시 없는 모의 응답으로 대체(시험·비용 추정용)", on=("1",))
    min_gold_coverage: float | None = F(0.95, "MIN_GOLD_COVERAGE", "stack_matrix에서 정답 문서 포함률이 이 값 이상이어야 valid")
    docker: CommonDevDocker = Field(default_factory=CommonDevDocker)


class CommonHost(Section):
    doc_src: str | None = F(None, "DOC_SRC", "원본 문서 폴더(DOC_DIR의 옛 별칭) — compose에선 /data/docs로 마운트할 호스트 폴더")
    docker: str | None = F("docker", "DOCKER", "호스트 스크립트가 쓸 컨테이너 명령(docker|podman 등)")
    image_stage_dir: str | None = F(None, "IMAGE_STAGE_DIR", "prune_old.sh가 정리할 이미지 조각·tar 폴더(--stage-dir 기본값)")
    output_root: str | None = F(
        None,
        "RAG_OUT",
        "호스트의 결과(output) 폴더(서버 경로) — compose가 컨테이너 /app/output으로 마운트하는 원본(T-21 — 코드가 읽는 칸은 common.paths.output_root)",
    )
    patch_code: str | None = F(
        "/srv/rag/code/live", "PATCH_CODE", "덧씌우기 코드 폴더(호스트) — compose.patch*.yml이 컨테이너 /app/deploy/*로 마운트"
    )
    pg_container: str | None = F(
        None,
        "PG_CONTAINER",
        "호스트에서 psql을 docker exec할 PostgreSQL(pgvector) 컨테이너 이름 — run_docs.py 문서 수 세기(S7e1 — 옛 코드 고정값)",
    )
    prune_keep: int | None = F(2, "PRUNE_KEEP", "prune_old.sh가 남길 이미지 판 수(지금 판 포함, --keep 기본값)")


class CommonPaths(Section):
    client_roster: str | None = F(
        None, "CLIENT_ROSTER", "고객 명부 파일 경로(JSON {이름:[별칭]} 또는 CSV) — 용어·별칭에 합침", pinned="handoff"
    )
    config_dir: str | None = F(
        None,
        "SERVER_ENV_DIR",
        "서버 설정 폴더(코드 폴더 밖) — 호스트 스크립트가 settings.yaml을 여기서 찾음(원천 목록 sources.json 덮어쓰기는 S8b에 없앰 — 서버는 판 표)",
    )
    criteria_file: str | None = F(None, "CRITERIA_FILE", "판정 문턱값 파일 경로(criteria.json)")
    doc_dir: str | None = F(
        image_default("DOC_DIR"),
        "DOC_DIR",
        "원본 문서 폴더 — 원본 위치 주소·파싱 입력의 기준(pipeline 이미지 안 기본 /data/docs — 옛 Dockerfile ENV, B-2)",
        pinned="handoff",
    )
    doc_dir_prepared: str | None = F(
        image_default("DOC_DIR_PREPARED"),
        "DOC_DIR_PREPARED",
        "준비(dedup·회전) 끝난 문서 폴더 — 파싱의 --src 기본값(pipeline 이미지 안 기본 /app/output/prepared — 옛 Dockerfile ENV, B-2)",
    )
    draft_terms_out: str | None = F(None, "DRAFT_TERMS_OUT", "용어 자동 초안 CSV 경로", pinned="handoff")
    eval_sets_dir: str | None = F(None, "EVAL_SETS_DIR", "평가 세트(합성 E2E·정답률 측정) 저장소 폴더")
    glossary_dir: str | None = F(None, "GLOSSARY_DIR", "용어 사전 폴더(domain_terms.csv·id_patterns.csv 등)", pinned="handoff")
    index_root: str | None = F(None, "INDEX_ROOT", "이름 있는 색인 폴더 루트(<index_id>/bundle)")
    korean_font: str | None = F(None, "KOREAN_FONT", "한글 글꼴 파일 경로(그림 렌더·점검용)")
    mcp_bundle: str | None = F(
        None,
        "MCP_BUNDLE",
        "검색할 로컬 묶음(bundle) 폴더 경로 — 검색 MCP 로컬 저장소·평가(server_checks)가 읽음(S7e1 — 두 앱이 읽어 common, 옛 mcp.server.bundle)",
    )
    output_root: str | None = F(
        None,
        "RAG_OUT",
        "결과(output) 폴더 — 코드가 이 아래를 읽고 씀(컨테이너 안 경로 — 서버는 /app/output, 비우면 코드 기본. 마운트 원본은 common.host.output_root — T-21)",
    )
    runlog_dir: str | None = F(None, "RUNLOG_DIR", "실행 기록(output/logs) 루트 폴더")
    source_manifest: str | None = F(
        None, "SOURCE_MANIFEST", "원본 manifest.jsonl 경로(Object Storage/rdb에서 받은 문서 → s3:// 주소 대응)", pinned="handoff"
    )
    sources_file: str | None = F(
        None,
        "SOURCES_FILE",
        "PC(RUN_ENV=local) 원천 목록 파일 경로(비우면 resources/mappings/sources.json) — 서버는 판 표 struct.source_version 활성 판(S8b)",
    )
    stack_file: str | None = F(
        None,
        "PIPELINE_STACK_FILE",
        "PC(RUN_ENV=local) 엔진 구성 파일 경로(비우면 resources/config/pipeline_stack.json) — 서버는 판 표 struct.stack_version 활성 판(S8b)",
    )


class CommonRuntime(Section):
    cpu_max_load: float | None = F(0.9, "CPU_MAX_LOAD", "새 하위 프로세스를 띄우는 CPU 부하 상한(1분 부하 평균 ÷ 코어 수)", unset=("auto",))
    draft_terms_lock_timeout: float | None = F(
        5.0, "DRAFT_TERMS_LOCK_TIMEOUT", "용어 초안 CSV 쓰기 잠금 대기 시간(초) — 못 얻으면 이번엔 포기", pinned="handoff"
    )
    exp_max_workers: float | None = F(8, "EXP_MAX_WORKERS", "실험 도구(stack_matrix) 병렬 작업 수 상한(개)", unset=("auto",))
    exp_proc_gb_answer: float | None = F(
        0.5,
        "EXP_PROC_GB_ANSWER",
        "실험 answer 작업 1개당 메모리 가정(GB)(S7b — resources.plan_experiment가 cmd로 이름을 지어 읽음)",
        unset=("auto",),
    )
    exp_proc_gb_build: float | None = F(1.5, "EXP_PROC_GB_BUILD", "실험 build 작업 1개당 메모리 가정(GB)", unset=("auto",))
    exp_proc_gb_run: float | None = F(0.5, "EXP_PROC_GB_RUN", "실험 run(·answer) 작업 1개당 메모리 가정(GB)", unset=("auto",))
    exp_reserve_gb: float | None = F(4.0, "EXP_RESERVE_GB", "실험 병렬 수를 정할 때 남겨 둘 메모리(GB)", unset=("auto",))
    lib_env: LibEnv | None = F(
        {},
        "LIB_ENV",
        "라이브러리 env(이름: 글자 — TZ·OMP_NUM_THREADS·HF_HUB_OFFLINE 등 허용 목록만, 비밀 아님) — 컨테이너 시작 때 entrypoint가 env로 냄(사용자 env는 안 덮고 이미지 ENV는 덮음 — C-45 ⑤, S7e2)",
    )
    log_retention_days: int | None = F(30, "LOG_RETENTION_DAYS", "output/logs/*.log 보존 일수 — 지난 로그 삭제, 0 이하면 삭제 안 함")
    mem_max_pct: float | None = F(90.0, "MEM_MAX_PCT", "생산 파싱이 새 프로세스를 띄우는 메모리 사용률 상한(%)", unset=("auto",))
    mem_settle_margin: float | None = F(
        5.0, "MEM_SETTLE_MARGIN", "상한(MEM_MAX_PCT) 이만큼(%p) 아래부터 프로세스 띄운 뒤 잠깐 쉼", unset=("auto",)
    )
    mem_settle_sec: float | None = F(2.0, "MEM_SETTLE_SEC", "메모리가 상한 근처일 때 프로세스 띄운 뒤 쉬는 시간(초)", unset=("auto",))
    mem_start_pct: float | None = F(
        90.0, "MEM_START_PCT", "wait_mem 기본 상한 — 실험 도구가 새 프로세스를 띄우는 메모리 사용률(%)", unset=("auto",)
    )
    pipe_max_procs: float | None = F(8, "PIPE_MAX_PROCS", "파싱 엔진 프로세스 수 자동 결정의 상한(개)", unset=("auto",))
    pipe_proc_gb: float | None = F(3.0, "PIPE_PROC_GB", "엔진 프로세스 1개당 메모리 가정(GB) — 자동 프로세스 수 계산용", unset=("auto",))
    pipe_procs: float | AutoWord | None = F(
        image_default("PIPE_PROCS"),
        "PIPE_PROCS",
        "CPU 엔진 프로세스 수 — 비우거나 auto면 CPU·메모리로 계산(소수는 버림) · auto는 글자로 기억(run_all --procs 기본: auto → auto, 비움 → 1 — S7c1) · auto는 대소문자·앞뒤 공백 무시 · pipeline 이미지 안 기본 auto(옛 Dockerfile ENV, B-2)",
    )
    pipe_reserve_cpus: float | None = F(1, "PIPE_RESERVE_CPUS", "자동 프로세스 수 계산 때 남겨 둘 CPU 코어 수(개)", unset=("auto",))
    pipe_reserve_gb: float | None = F(4.0, "PIPE_RESERVE_GB", "자동 프로세스 수 계산 때 남겨 둘 메모리(GB)", unset=("auto",))
    pipe_threads: float | None = F(
        None,
        "PIPE_THREADS",
        "프로세스 1개당 수치 라이브러리 스레드 수(OMP·MKL·onnx) — 비우거나 auto면 CPU ÷ 프로세스 수(소수는 버림)",
        unset=("auto",),
    )
    pipe_workers: float | None = F(4, "PIPE_WORKERS", "VLM API 동시 처리 문서 수(개) — GPU 서버 한도 기준", unset=("auto",))


class CommonStore(Section):
    doc_registry: bool | None = F(
        True, "DOC_REGISTRY", "문서 대장(doc_registry) 사용 — =0이면 끄고 필터 없이 동작", off=("", "0", "none", "false"), fold="lower"
    )
    registry_editions: bool | None = F(
        True,
        "REGISTRY_EDITIONS",
        "대장 '판 비교'(지문 기록·판 연결·내용 그룹) — =0이면 끄고 이전 동작",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    registry_etag_md5: bool | None = F(
        True,
        "REGISTRY_ETAG_MD5",
        "ETag가 MD5 형식이면 그것만으로 '날짜만 바뀜'으로 확정 — =0이면 항상 원본 바이트 대조",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    registry_retry_max: int | None = F(7, "REGISTRY_RETRY_MAX", "실패 문서 재시도 허용 기간(일) — 0이면 무제한")
    run_mode: str | None = F(
        None, "RUN_MODE", "실행 모드 prod|test — pipeline --mode 기본, prod이면 PG 실패 시 SQLite 대체 금지·VLM 시간 완화"
    )
    struct_backend: str | None = F("pg", "STRUCT_BACKEND", "정형 저장소 종류 pg|sqlite|tsql", blank="keep")
    struct_db: str | None = F(None, "STRUCT_DB", "정형 저장소 SQLite 파일 경로(STRUCT_BACKEND=sqlite일 때·PG 대체 시)")


class CommonText(Section):
    draft_terms_max: int | None = F(
        500, "DRAFT_TERMS_MAX", "용어 자동 초안 파일 행 수 상한(개) — 넘으면 가장 빈번한 것만 유지", pinned="handoff"
    )
    parse_token_norm: bool | None = F(
        True,
        "PARSE_TOKEN_NORM",
        "파싱 결과 비교의 숫자 표기 정규화(AD25) — =0이면 끄고 이전 동작",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    search_recency: str | None = F(
        "1",
        "SEARCH_RECENCY",
        "같은 문서군의 최신 판 우선 모드 — 0 끔·1 최신을 묻는 질문에서만·2 항상(common/core/docmeta.py — S7b에 mcp.search에서 옮김)",
        blank="keep",
    )
    search_en_stem: bool | None = F(
        True, "SEARCH_EN_STEM", "검색 토큰의 영어 복수→단수 정규화(G16, 가산만) — =0이면 끔", pinned="handoff", off=("0",)
    )
    source_uri_prefix: str | None = F(
        None, "SOURCE_URI_PREFIX", "원본 위치 주소의 접두어(예: s3://버킷/접두 · file:///srv/rag/docs)", pinned="handoff"
    )
    token_num_norm: bool | None = F(
        True,
        "TOKEN_NUM_NORM",
        "검색 토큰의 숫자·단위 정규화(T1) — =0이면 끄고 이전 동작",
        pinned="handoff",
        off=("", "0", "none", "false"),
        fold="lower",
    )


class CommonConnections(Section):
    REMOVED = frozenset(
        {"openviking", "edw"}
    )  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안) · edw = EDW 벡터 경로(ops.md#op-03)
    object_storage: CommonConnectionsObjectStorage = Field(default_factory=CommonConnectionsObjectStorage)
    parsing_meta: CommonConnectionsParsingMeta = Field(default_factory=CommonConnectionsParsingMeta)
    pg: CommonConnectionsPg = Field(default_factory=CommonConnectionsPg)
    rdb: CommonConnectionsRdb = Field(default_factory=CommonConnectionsRdb)


class CommonModels(Section):
    REMOVED = frozenset({"rerank"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    embed: CommonModelsEmbed = Field(default_factory=CommonModelsEmbed)
    guard: CommonModelsGuard = Field(default_factory=CommonModelsGuard)
    llm: CommonModelsLlm = Field(default_factory=CommonModelsLlm)
    ocrvlm: CommonModelsOcrvlm = Field(default_factory=CommonModelsOcrvlm)
    transport: CommonModelsTransport = Field(default_factory=CommonModelsTransport)
    vlm: CommonModelsVlm = Field(default_factory=CommonModelsVlm)


class CommonSettings(Section):
    run_env: Literal["local", "dev", "prd"] | None = F(
        None, "RUN_ENV", "실행 환경 — local(PC·valid_env 기준)·dev·prd(서버, 외부 모델 거부). env RUN_ENV가 이 값을 이김"
    )
    connections: CommonConnections = Field(default_factory=CommonConnections)
    dev: CommonDev = Field(default_factory=CommonDev)
    host: CommonHost = Field(default_factory=CommonHost)
    models: CommonModels = Field(default_factory=CommonModels)
    paths: CommonPaths = Field(default_factory=CommonPaths)
    runtime: CommonRuntime = Field(default_factory=CommonRuntime)
    store: CommonStore = Field(default_factory=CommonStore)
    text: CommonText = Field(default_factory=CommonText)


class CommonAppSettings(AppSettings):
    """common 절만 — common 코드가 읽는 뿌리(COMMON)."""

    common: CommonSettings = Field(default_factory=CommonSettings)


# common 코드가 읽는 설정 객체 — 설정 파일(SETTINGS_FILE·로컬 파일)에서, 신호가 바뀌거나 put()이 부르면 다시 읽는다(Cache 설명 — S7e2).
COMMON = Cache(CommonAppSettings)


class EnvView:
    """설정 캐시(Cache)의 한 절을 읽는 창 — common(아래 cfg·by_env·given·dropped·checked)·pipeline(pipeline/config.py)·mcp(mcp_server/config.py)가
    같은 꼴로 쓴다."""

    def __init__(self, cache, section):
        self.cache, self.section = cache, section

    def cfg(self):
        return getattr(self.cache.get(), self.section)

    @functools.cached_property
    def _paths(self):
        cut = len(self.section) + 1
        return {e: p[cut:] for e, p in _env_map(self.cache.app_cls, False).items() if p.startswith(self.section + ".")}

    def by_env(self, name, default=None):
        path = self._paths.get(name)
        if path is None:
            return default
        v = _get(self.cfg(), path)
        return default if v is None else v

    def given(self, name):
        path = self._paths.get(name)
        if path is None:
            return None
        st = self.cfg()
        if not _is_set(st, path):
            return None
        v = _get(st, path)
        return None if v is None or reveal(v) == "" else v  # 비밀 칸 SecretStr('')도 빈 값(VS7b BLOCK-1 — SecretStr('') != '')

    def dropped(self, name):
        return name in self.cache.get()._dropped

    def checked(self, name):
        if self.dropped(name):
            raise ValueError(f"{name} 값 형식이 틀림(값은 안 찍음) — 고치기 전에는 이 값을 쓰는 호출을 하지 않음")


_COMMON_VIEW = EnvView(COMMON, "common")


def cfg():
    """common 절 설정 객체(CommonSettings) — `from common.config.settings import cfg; cfg().models.llm.timeout`."""
    return COMMON.get().common


def by_env(name, default=None):
    """옛 env 이름으로 common 칸 값(형식 있는 값 — 비밀은 SecretStr) — 이름을 글자로 짓는 자리(`f"{prefix}_BASE_URL"`·모델 프로필의
    key_env)만 쓴다. 칸이 없거나(시험의 가짜 접두 ZZ_·X_) 값이 None이면 default."""
    return _COMMON_VIEW.by_env(name, default)


def given(name):
    """옛 env 이름 칸에 값을 실제로 줬으면(env·YAML·시험 — 모델 기본값이 아니고 None·빈 글자도 아님 — 비밀 칸의 빈 값 포함) 그 값
    (비밀은 SecretStr), 아니면 None. 옛 `if os.environ.get(X): …`처럼 "준 값만" 쓰는 자리(pg·edwdb conf의 접속 파일 덮기,
    resources._f의 호출자 기본값)용(S7b)."""
    return _COMMON_VIEW.given(name)


def dropped(name):
    """옛 env 이름 값이 형식이 틀려 객체에서 버려졌나(경고 뒤 기본값) — 옛 코드가 그 값에서 실패해 일을 건너뛰던 자리가 같게
    건너뛸 때(runlog 로그 지우기 등)."""
    return _COMMON_VIEW.dropped(name)


def checked(name):
    """형식이 틀려 버린 값을 읽는 자리에서 옛 코드처럼 실패(ValueError — 이름만, 값은 안 찍음). 기본값이 '제한 없음'이라 조용히
    넘어가면 위험한 칸(지출 상한 LLM_BUDGET_USD·LLM_MAX_CALLS)·요청 모양이 바뀌는 칸(*_EXTRA_BODY)·접속 포트(VS7b R-7)를
    읽기 바로 앞에서 부른다(S7b)."""
    _COMMON_VIEW.checked(name)


def guard_run_env():
    """가드가 볼 RUN_ENV — 모르는 글자(prod·PRD 등 — 객체에서는 없음으로 처리)는 그 글자 그대로(서버로 봄 — VS7b U-1)."""
    st = COMMON.get()
    return st.common.run_env or st._unknown_run_env


def token_text(v):
    """토큰 칸 값(SecretStr·글자·None) → 글자, 없거나 공백만이면 ""(토큰 없음 — 사용자 10-27, C-42·C-44: PARSE_MCP_TOKEN·TRIGGER_TOKEN·
    MCP_TOKEN·PARSE_SERVICE_TOKEN 같은 규칙). 공백이 섞인 토큰은 옛처럼 그대로 쓴다. 값은 출력하지 않는다."""
    t = reveal(v) or ""
    return t if t.strip() else ""


def reveal(v):
    """비밀 칸 값 → 글자(SecretStr이 아니면 그대로) — 접속·헤더에 넘길 때만."""
    return v.get_secret_value() if isinstance(v, SecretStr) else v


_TApp = CommonAppSettings


if __name__ == "__main__":
    # import common이 이미 부른 모듈(common.config.settings)로 돌림 — 이 __main__ 사본의 COMMON·_CountingEnviron은 쓰지 않음(S7d — 두 사본이 판 번호를 나누지 않게)
    from common.config import settings as _S

    utf8_stdout()
    from common.config import show

    sys.exit(show.main(_S._TApp, sys.argv[1:]))
