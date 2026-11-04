"""설정 읽기 — settings.yaml 하나를 pydantic 모델(최상위 절 common·pipeline·mcp)로 읽는다. 파일 배치
(required·역할 절·tuning)는 common.config.layout이 모델 배치로 바꾼다(read_settings — 이 모듈 아래 설명의 "절"은 모델 배치).
앱은 자기 설정 객체 하나를 프로세스 시작 때 한 번 읽어 캐시한다 — pipeline/config.py(common + pipeline 절),
mcp_server/config.py(common + mcp 절). 이 파일은 common 절 모델과 두 앱이 함께 쓰는 읽기 함수를 둔다.

읽는 순서(높은 쪽이 이김): 시험이 넘긴 값(data=·Cache.env) > 덮기 파일의 overrides(put·child_env·overlay 도구 — 아래) > YAML > 모델 기본값.
  · env에서 읽는 것은 신호 둘(RUN_ENV·SETTINGS_FILE)뿐이다. 칸의 env 이름으로 env에 준 값은 읽지 않는다.
    엔진·인계 파일도 설정 객체로 읽는다.
  · 덮기 파일: 최상위 `base:`(다른 설정 파일 경로 — 먼저 읽음)와 `overrides:`({env 이름: 글자|null}, null = 그 칸 비움)만 든
    작은 yaml. 프로세스 안 put()·자식용 child_env()·PC 한 번 실행용 `python -m common.config.overrides`가 만들고 SETTINGS_FILE로 가리킨다(원본 비밀을
    복사하지 않음 — 원본은 base로 가리킴). overrides 값은 env 글자 꼴로 판정한다(켜기 칸 '1'·'0' 등).
  · 모델 기본값 None은 "읽는 코드가 정함"이다: 코드가 계산하는 기본값(경로·CPU 수 등) · 자리마다 다른 기본값 · 있고 없음을 코드가 가르는
    칸 · JSON 칸(없으면 안 붙임).
  · 비운 칸(YAML null·env 글자 `X=`)은 "설정 안 함"(모델 기본값). 빈 글자 ""도 기본값이 있는 칸(숫자·켜기·목록, 기본값 있는 글자)에서는
    "설정 안 함"이다. 기본값이 None인 글자 칸과 F(..., blank="keep") 칸에서만 ""이 빈 글자로 남는다.
    이 규칙은 Section._normalize 한 곳에 있고 YAML·env 이름(덮기 파일·시험)·시험 data=가 모두 거친다.
  · 글자 칸에 쓴 YAML 스칼라(yes·no·true·on·1·0·숫자)는 쓴 글자 그대로 글자로 받는다(env 줄에 같은 글자를 쓴 것과 같게).
    숫자·켜기·JSON 칸은 YAML이 푼 값 그대로.
파일 찾기: SETTINGS_FILE(env) > RUN_ENV가 없거나 local이면 저장소 루트 settings.yaml(있을 때만 — settings.sample.yaml 옆).
RUN_ENV: env RUN_ENV > YAML required.env.run_env. local·dev·prd. 없거나 dev·prd인데 파일이 없으면 거부.
앱 시작 관문 require_run_env() — pipeline.cli(selftest 빼고)·mcp_server.main·parse_service·컨테이너 boot가 맨 먼저 부른다. 서버(dev·prd)면
설정 파일을 못 읽거나 그 앱 절 검증에 실패해도 이유(칸 경로·오류 종류만)를 찍고 종료 2. 틀린 파일은 import common 때도
서버면 바로 실패(pin_env — STRICT), local이면 경고 뒤 기본값.
비밀 칸은 SecretStr — 출력·로그·검증 오류에 값이 나오지 않는다.
사용: python -m common.config.show [--file 경로]   # 읽어서 요약(비밀 가림) — 앱별 요약은 python -m pipeline.config · mcp_server.config
"""

import contextlib
import functools
import json
import os
import re
import sys
import weakref
from pathlib import Path
from typing import Annotated, Literal, get_args, get_origin
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.config import layout as L
from common.core import exitclean  # 맡은 덮기 파일은 프로세스가 끝날 때 지움

REPO_ROOT = Path(__file__).resolve().parents[2]  # PC = 저장소 루트 · 이미지 = /app/deploy
LOCAL_FILE = REPO_ROOT / "settings.yaml"  # RUN_ENV=local 기본 자리 — 저장소 루트, settings.sample.yaml 옆(git 밖 — .gitignore)
RUN_ENVS = ("local", "dev", "prd")  # 그 밖의 값은 시작 거부
SERVER_ENVS = ("dev", "prd")
MIN_SECRET_LENGTH = 8  # 서버 시작 관문만 적용; local 마스킹 경계 정책은 유지
SECTIONS = ("common", "pipeline", "mcp")
OVERLAY_KEYS = ("base", "overrides")  # 덮기 파일의 최상위 열쇠(위 모듈 설명)
STRICT = True  # RUN_ENV가 없으면 거부
IN_IMAGE = REPO_ROOT.name == "deploy"  # 코드가 이미지 배치(/app/deploy/<패키지>) — paths.LOCAL_RUN과 같은 판정
# ── 이미지 배치 약속 경로 — 코드에 둔 컨테이너 안 자리는 이 두 표에만(CLAUDE.md 경로 규칙의 예외) ──
# 이미지(Dockerfile·compose 마운트·entrypoint)가 만드는 자리라 서버 설정 값이 아니라 이미지와 함께 바뀐다.
IMAGE_PATHS = {
    # 컨테이너 안 약속 경로는 이 표 하나(두 이미지 공통). 호스트 쪽(compose·run_docs·스크립트)은 deploy/release/gen_host_keys.py가
    # 이 표로 만든 deploy/host/scripts/image_paths.json을 읽는다(호스트 python엔 pydantic이 없음 — load_settings.sh가 APP_* env로도 냄).
    "output_root": "/app/output",  # 결과 폴더를 붙이는 자리(compose RAG_OUT → 이 자리)
    "code_root": "/app/deploy",  # 코드 자리(PYTHONPATH — 실행 이미지는 서버 코드 폴더를 여기에 붙임)
    "image_env": "/app/docker/image_env.txt",  # 빌드 때 이미지 ENV를 적어 둔 파일(common.config.boot — 라이브러리 env가 이미지 값만 덮게)
    "docs_mount": "/data/docs",  # 원본 폴더를 읽기 전용으로 붙이는 자리(compose DOC_SRC → 이 자리 · pipeline DOC_DIR 기본값)
}
IMAGE_PATHS["prepared_out"] = IMAGE_PATHS["output_root"] + "/prepared"  # 원본 사본(prepare) 자리(pipeline DOC_DIR_PREPARED 기본값)
# 이미지 안 모델 기본값 — 규칙은 "settings.yaml > 코드 기본값" 하나라 Dockerfile ENV로 굽지 않고 여기 둔다.
# 이미지 신호 RAG_MODULE로 그 이미지 값만 고른다. PC·시험 하위 프로세스(RAG_MODULE 없음)는 PC 기본값.
_IMAGE_DEFAULTS = {
    "pipeline": {
        "DOC_DIR": IMAGE_PATHS["docs_mount"],
        "DOC_DIR_PREPARED": IMAGE_PATHS["prepared_out"],
        "PIPE_PROCS": "auto",
        "SOFFICE_BIN": "/usr/bin/soffice",
        "APPLOG_DB_ENABLED": True,  # 서버 로그는 Postgres(applog)
    },
    "mcp": {
        "EMBED_QUERY_CACHE": "/tmp/mcp_query_cache.sqlite",  # 질의 캐시
        "APPLOG_DB_ENABLED": True,  # 서버 로그는 Postgres(applog)
    },
}
IMAGE_DEFAULTS = _IMAGE_DEFAULTS.get(os.environ.get("RAG_MODULE", ""), {}) if IN_IMAGE else {}  # env 남김 — 이미지 신호


def image_default(env, pc=None):
    """칸 기본값 — 이 이미지의 기본값 표(_IMAGE_DEFAULTS)에 있으면 그 값, 아니면 pc(PC 기본값 — 코드 기본값)."""
    return IMAGE_DEFAULTS.get(env, pc)


# settings.yaml ops.runtime.lib_env로 줄 수 있는 라이브러리 env 이름(비밀 아님 — 이 목록 밖은 거부).
# 컨테이너 entrypoint(common.config.boot)가 시작 때 env로 낸다 — 사용자 env는 안 덮고, 이미지 ENV 값(/app/docker/image_env.txt)은 덮는다.
# 담은 것: 스레드·캐시·오프라인 신호(OMP_NUM_THREADS·HF_HUB_OFFLINE·TZ 등) + Dockerfile ENV(TZ·LANG·HF_*·DO_NOT_TRACK·
# SCARF_NO_ANALYTICS) + 코드가 자식·라이브러리에 넘기는 이름(OMP·MKL·OPENBLAS·NUMEXPR·TORCH, PIPELINE_VERSION, TESSDATA_PREFIX·HF_HOME).
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


def repo_path(v):
    """경로 칸(F repo=True)의 상대 경로를 저장소 루트(paths.PROJ_ROOT) 기준 절대 경로로 — 한 곳(op-14). 앞머리 `file://`·`rdb:csv:`는
    두고 뒤 경로만 푼다(`file://valid_env/x` → `file://<루트>/valid_env/x`). 절대 경로·다른 주소(s3:// 등)·sqlite `:memory:`·빈 값은 그대로 — 서버는 작업
    폴더가 /app(= PROJ_ROOT)라 결과가 같다."""
    pre = next((p for p in ("file://", "rdb:csv:") if v.startswith(p)), "")
    rest = v[len(pre) :]
    if not rest or "://" in rest or rest.startswith(("/", "\\", "rdb:", ":")) or Path(rest).is_absolute():
        return v
    from common.core.paths import PROJ_ROOT  # 늦게 — paths가 import 때 settings를 부름

    return pre + (PROJ_ROOT / rest).as_posix()


class SettingsError(RuntimeError):
    """설정 파일을 못 찾거나 형식이 틀림 — 메시지에 비밀 값은 넣지 않는다."""


def F(default, env, desc, *, blank="", on=(), off=(), fold="", unset=(), repo=False, **kw):
    """설정 칸 하나 — env: 칸의 env 이름(덮기 파일 overrides·시험·export·keyscan 대조에 씀), desc: sample·문서에 나가는 설명,
    blank="keep": 기본값이 있어도 빈 값을 그대로 둠 — `X=`을 ''로 두는 글자 칸·빈 목록으로 두는 목록 칸.
    켜기 칸의 판정 꼴(키마다 정함): on=("1",) — 글자가 그중 하나일 때만 켜짐(`== "1"`),
    off=("0",) — 그중 하나일 때만 꺼짐(`!= "0"`), fold="lower" — 견주기 전에 strip().lower(),
    fold="strip" — strip()만, fold="" — 글자 그대로(모드 이름처럼).
    빈 글자 ''도 이 꼴로 판정한다. 판정 꼴이 없는 켜기 칸은 pydantic 기본 해석.
    unset: 이 글자면 "설정 안 함"(모델 기본값 — 읽는 코드가 계산) — ("auto",)는 None·""·"auto"를 설정 안 함으로,
    "nondigit"는 strip() 뒤 숫자가 아니면 무시(OCR_THREADS). repo=True: 저장소 루트 기준 상대 경로를 받는 칸(repo_path),
    repo="file://": 그 앞머리로 시작할 때만 경로(게시 버킷 — 그 밖은 버킷 이름)."""
    extra = {"env": env}
    if repo:
        extra["repo"] = repo
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
# 검증 오류(yes가 판정 꼴 =="1"로 조용히 꺼지지 않게). env 글자는 칸의 판정 꼴 그대로.
YAML_BOOL_WORDS = ("true", "false")


def judge(field, v, name=""):
    """켜기 칸 값 → bool(판정 꼴, 위 F 설명). 판정 꼴이 없거나 글자가 아니면 v 그대로. YAML 값은 위 표기만(아니면 ValueError — 칸 이름만)."""
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


CsvList = Annotated[list[str], BeforeValidator(_csv)]  # env 글자 "a,b" 또는 YAML 목록
WordList = Annotated[list[str], BeforeValidator(_words)]  # env 글자 "a b"(셸 for 단어 — NIGHTLY_MODULES) 또는 YAML 목록
JsonValue = Annotated[dict | list, BeforeValidator(_json)]  # env JSON 글자 또는 YAML 사전·목록


def _csv_text(v):
    """쉼표 목록 글자 칸 — 글자는 쓴 그대로(공백·빈 항목까지), YAML 목록은 ','로 이은 글자(결과 파일에 원문 글자를 적는 칸)."""
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return v


CsvText = Annotated[str, BeforeValidator(_csv_text)]  # 원문 글자를 지켜야 하는 쉼표 목록(PARSE_POST — rep.post.config에 그대로 적음)


def _auto_word(v):
    """auto 표기 — 대소문자·앞뒤 공백 무시, 공백만인 글자도 auto(strip().lower()로 견줌). 빈 글자는 여기 안 옴(_normalize가 설정 안 함으로)."""
    return "auto" if isinstance(v, str) and v.strip().lower() in ("auto", "") else v


AutoWord = Annotated[Literal["auto"], BeforeValidator(_auto_word)]  # 숫자 | auto 칸의 auto(PIPE_PROCS)


def _port(v):
    """접속·듣기 포트 — 정수만. 글자는 int(글자)와 같게(앞뒤 공백·부호 허용) — '5.0'·'8766x'는 형식 오류,
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
    """라이브러리 env 사전 — 이름은 LIB_ENV_NAMES 안만, 값은 한 줄 글자만(YAML 스칼라는 쓴 글자 그대로). 오류에는 이름만(값 없음)."""
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
    """YAML 스칼라 — 쓴 글자(str 자체)와 푼 값(.value)을 함께 든다. 켜기·숫자·날짜로 풀린 것(yes·true·1·0.5·2026-10-27 등)과
    글자(env 글자와 가르려고: 판정 꼴 켜기 칸은 YAML 표기를 좁게 받음)를 모두 이것으로 읽는다.
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
        ("timestamp", C.construct_yaml_timestamp),  # 2026-10-27 같은 날짜도(날짜를 적는 글자 칸)
        ("str", C.construct_yaml_str),
    ):  # 글자도 — env 글자와 가름(judge)
        Loader.add_constructor("tag:yaml.org,2002:" + tag, keep(base))
    return L.reject_dup_keys(Loader)


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
    """글자 칸에 온 값 → 글자. YAML 스칼라는 쓴 글자 그대로, 파이썬 켜기(시험 data=)는 env 꼴 '1'·'0', 숫자는 str()."""
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

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if not isinstance(data, dict):
            return data
        out = {}
        for k, v in data.items():
            if v is None:
                continue
            f = cls.model_fields.get(k)
            if f is None or _section_type(f.annotation) is not None:
                out[k] = v  # 모르는 칸(거부는 pydantic이)·하위 절(그 절의 _normalize가)
                continue
            kind = field_kind(f.annotation)
            if is_unset(f, v):
                continue  # auto 등 — 설정 안 함(읽는 코드가 계산)
            if kind == "text":
                v = [_text(x) for x in v] if isinstance(v, list) else _text(v)  # 목록은 CsvText만(그 밖 글자 칸은 pydantic이 거부)
            elif kind == "list":
                v = [_text(x) for x in v] if isinstance(v, list) else _text(v)  # phases: 3 → '3'(env PARSE_PHASES=3과 같게)
                if v in ("", []):  # 빈 목록 — 보통은 기본값, blank="keep" 칸이면 빈 목록
                    if keeps_blank(f):
                        out[k] = []
                    continue
            elif kind == "map":
                pass  # 라이브러리 env 사전 — 값은 쓴 글자 그대로(_lib_env가 봄)
            elif _extra(f, "truth"):
                v = judge(f, v, k)  # 켜기 칸 — env 글자는 빈 글자도 판정 꼴로, YAML은 true·false·0·1만
            else:
                v = _plain(v)
            if v == "" and _extra(f, "env") in IMAGE_DEFAULTS:
                out[k] = "" if kind == "text" else None  # 이미지 기본값 칸의 빈 글자 = 정말 비움(이미지 기본값으로 채우지 않음)
                continue
            if v == "" and (kind != "text" or (f.default is not None and not keeps_blank(f))):
                continue  # 빈 글자 = 설정 안 함 — 기본값 None·blank="keep" 글자 칸만 ""로 남음
            out[k] = v
        return out

    @model_validator(mode="after")
    def _repo_paths(self):
        for name, f in type(self).model_fields.items():
            v = getattr(self, name)
            want = _extra(f, "repo")
            if want and isinstance(v, str) and (want is True or v.startswith(want)) and repo_path(v) != v:
                object.__setattr__(self, name, repo_path(v))  # 값만 바꿈(설정한 칸 표시는 그대로)
        return self


class AppSettings(BaseSettings):
    """앱 설정 뿌리 — 다른 앱 절(pipeline이면 mcp)은 무시한다. pydantic-settings의 env 자동 읽기는 끄고(env에서 설정을
    읽지 않음) load()가 순서대로 합친 값만 받는다."""

    model_config = SettingsConfigDict(extra="ignore")
    _source: str = PrivateAttr("")  # 읽은 설정 파일(없으면 "")
    _dropped: frozenset = PrivateAttr(frozenset())  # 형식이 틀려 버린 칸의 env 이름(경고 뒤 기본값 — dropped())
    _unknown_run_env: str | None = PrivateAttr(None)  # lenient_run_env로 없음 처리한 모르는 RUN_ENV 글자(가드가 서버로 봄 — guard_run_env)

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings,)


# ── 칸 목록 걷기 — export·sample·keyscan 대조가 함께 씀 ──────────────────────────
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
    """호스트(compose·systemd·셸) 절 — 앱 프로세스 안에서는 쓰지 않음(호스트 스크립트가 export로 받음)."""
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


def env_map(model_cls, *, hosts=False):
    """env 이름 → 경로(호스트 절은 hosts=True일 때만 — 같은 env 이름이 앱·호스트 두 칸에 있음). 사본을 돌려준다."""
    return dict(_env_map(model_cls, hosts))


@functools.cache
def _env_map(model_cls, hosts):
    """env_map 캐시(부를 때마다 모델을 다시 걷지 않게). 고치지 말고 읽기만."""
    out = {}
    for path, f, _ in walk(model_cls):
        e = env_name(f)
        if e and is_host(path) == hosts:
            out.setdefault(e, path)
    return out


def render(value, *, secrets=False, sep=","):
    """env 글자로 — 켜기 1/0, 목록은 sep(쉼표 — WordList 칸은 공백), 사전은 JSON. 비밀은 secrets=True일 때만(아니면 None)."""
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value() if secrets else None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # 4.0 → "4"(compose cpus 글자와 같게)
    if isinstance(value, (list, tuple)):
        return sep.join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def list_sep(field):
    """목록 칸을 env 한 줄로 낼 때 구분자 — WordList(셸 for 단어)는 공백, 그 밖은 쉼표."""
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
    """[(env 이름, 글자, 경로)] — export 명령이 씀. only_set이면 기본값은 빼고(읽는 코드의 기본값이 그대로 돌게).
    hosts: False = 앱 칸만 · True = 호스트 칸만 · None = 둘 다(export — 절 이름으로 고름)."""
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
        dup = getattr(e, "problem", "") or ""
        what = f" — {dup}" if dup.startswith(L.DUP_KEY) else ""  # 우리 메시지만(다른 problem은 값 글자를 담을 수 있음)
        raise SettingsError(f"설정 파일 YAML 형식 오류: {p}{where}{what}") from None
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise SettingsError(f"설정 파일 맨 위는 절(required·common·extract … tuning) 사전이어야 함: {p}")
    return doc


def read_settings(path, _depth=0):
    """설정 파일 → (모델 배치 절 사전 {common·pipeline·mcp}, overrides {env 이름: 글자|None}). 파일은 파일 배치(common.config.layout)
    이고 여기서 모델 배치로 바꾼다(모르는 칸·자리가 다른 칸은 거부). 덮기 파일이면 base를 먼저 읽고 그 위에 이 파일의 절·overrides를
    겹친다(위 모듈 설명 — base는 상대 경로면 이 파일 폴더 기준, 5단까지)."""
    doc = read_yaml(path)
    base, over = doc.pop("base", None), doc.pop("overrides", None)
    try:
        doc = L.to_model(doc, str(path))
    except L.LayoutError as e:
        raise SettingsError(str(e)) from None
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
    """덮기 파일 overrides 값 하나 → load()가 칸에 얹을 값. 따옴표 글자(overlay_file이 쓰는 꼴)는 env 글자 꼴로 판정하고(켜기 '1'·'0' 등),
    손으로 쓴 따옴표 없는 YAML 값(true·false·숫자)은 절 안에 쓴 것과 같은 규칙으로 판정한다(YamlScalar 그대로 — 글자 'true'로
    보면 켜기 칸이 꺼져 버림). 켜기 낱말은 true·false만(yes·on 등은 거부 — 펼쳐 쓸 때 바뀌지 않게)."""
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
    """칸 경로·오류 종류만 — 입력값은 찍지 않는다(비밀 칸 이름을 틀리면 비밀 칸으로 알아볼 수 없음)."""

    def where(loc):  # 모델 경로 → 파일 자리
        p = ".".join(str(x) for x in loc)
        try:
            return L.to_yaml(p)
        except L.LayoutError:
            return p

    lines = [f"  {where(e['loc'])}: {e['msg']} [{e['type']}]" for e in err.errors(include_url=False, include_input=False)]
    return f"설정 검증 실패({source}) — {len(lines)}건\n" + "\n".join(lines)


def _leaf_of(loc, paths):
    """오류 위치 → 칸 경로. int | "auto" 같은 합집합 칸은 pydantic이 뒤에 형식 이름(pipe_procs.int·pipe_procs.literal['auto'])을
    붙이므로, paths(이름으로 덮은 칸) 중 앞부분이 같은 것으로 줄인다."""
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
    names={env 이름: 글자|None} — 시험(Cache.env)이 env 이름으로 덮는 값(None = 그 칸 비움). 덮기 파일의 overrides 위에 얹는다.
    names·overrides 값의 형식이 틀리면 그 칸만 버리고 경고(이름만 — dropped()·checked()가 읽는 자리에서 알림). environ에서는 신호
    RUN_ENV·SETTINGS_FILE만 본다. lenient_run_env=True면 모르는 RUN_ENV 글자를 경고 뒤 없음으로(거부는 앱 시작 관문 — 가드는 서버로 봄).
    _read=(절 사전, overrides) — 이미 읽은 파일 내용."""
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
    file_run = env_run if env_run is not None else _peek(doc, "common.run_env")
    server = (
        unknown_run_env is not None or (str(file_run) if file_run is not None else None) in SERVER_ENVS
    )  # 덮기 파일 거부 판정(모르는 RUN_ENV 글자는 가드처럼 서버로)
    # 앱 설정 모듈이 import 중이면(pipeline.config를 먼저 import → import common → pin_env → 다른 앱 설정 모듈의 CFG) 그 앱 칸 이름을 아직
    # 모름 — 이름 검사를 건너뛴다(import 순서와 무관하게). 그 앱의 cfg()가 읽을 때(이름 다 앎) 다시 검사한다.
    unknown = sorted(n for n in over if n not in emap and n not in _all_names()) if over and not _names_loading() else []
    if unknown:  # 덮기 파일의 모르는 이름(오타·호스트 칸) — 서버는 거부, local은 경고(이름만)
        msg = f"덮기 파일 overrides에 설정 칸이 없는 이름: {' '.join(unknown)}"
        if server:
            raise SettingsError(f"{msg} — {path}")
        _warn_once(f"[settings] {msg} — 무시(local)")
    from_file = set()  # 덮기 파일 overrides 값이 마지막으로 얹힌 칸(시험 names가 덮으면 빠짐)
    for name, value in {**over, **(names or {})}.items():
        p = emap.get(name)
        if p is None or name == "RUN_ENV":
            continue
        if p not in before:
            before[p] = _peek(merged, p)
        if value is None:
            _drop_path(merged, p)
        else:
            L.set_path(merged, p, value)
        from_names[p] = name
        from_file.discard(p)
        if name in over and name not in (names or {}):
            from_file.add(p)
    if env_run is not None:
        L.set_path(merged, "common.run_env", env_run)
    elif unknown_run_env is not None:
        _drop_path(merged, "common.run_env")  # 모르는 env 글자가 YAML 값을 이김(없음 — 가드는 그 글자를 서버로 봄, 관문은 거부)
    _merge(merged, data or {})
    try:
        settings = app_cls(**merged)
    except ValidationError as e:
        bad = {_leaf_of(err["loc"], from_names) for err in e.errors()}
        if not bad or not bad <= set(from_names) or (server and bad & from_file):
            raise SettingsError(_format_errors(e, path or "설정 없음")) from None  # 서버 — 덮기 파일 값 형식 오류도 거부
        # 이름으로 덮은 값(시험·덮기 파일)만 틀림 — 그 칸만 버리고(파일 값으로 되돌림) 시작, 읽는 자리의 checked()가 알림. 값은 찍지 않는다.
        _warn_once(f"[settings] 덮은 값 형식이 맞지 않아 무시(기본값·파일 값): {' '.join(sorted(from_names[b] for b in bad))}")
        for b in bad:
            if before[b] is None:
                _drop_path(merged, b)
            else:
                L.set_path(merged, b, before[b])
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
        raise SettingsError(f"RUN_ENV 없음 — local·dev·prd 중 하나를 env RUN_ENV나 settings.yaml {L.to_yaml('common.run_env')}로")
    settings._source = str(path) if path else ""
    return settings


def resolve_run_env(environ=None, file=None):
    """RUN_ENV 값 — env RUN_ENV, 없으면 설정 파일(file — 없으면 SETTINGS_FILE·저장소 루트 settings.yaml)의 common.run_env(파일 자리 required.env.run_env). 없으면 None,
    모르는 값이면 SettingsError(env·파일 같은 규칙 — 덮기 파일 도구도 이것으로). 파일은 읽지만 설정 모델로 검증하지 않는다."""
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
    """앱 시작 관문 — RUN_ENV가 없거나 모르는 값이면 안내를 찍고 종료 코드 2. 값을 돌려준다.
    설정 파일을 읽고 sections(앱 절 — 없으면 이 이미지 절, image_sections)를 검증한다 — 모르는 칸·자리가 다른 칸·형식 오류면 이유(칸 경로·
    오류 종류만, 값 없음)를 찍고 종료 2. 서버(dev·prd)는 파일이 없어도 거부하고 비밀 칸 길이·가짜 LLM·여러 벌도 본다, local은 실제 접속 칸을 거부."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    tag = f"[설정] {app + ': ' if app else ''}"
    try:
        value = resolve_run_env(environ)
    except SettingsError as e:
        print(f"{tag}{e}", file=sys.stderr)
        raise SystemExit(2) from None
    if value is None:
        print(
            f"{tag}RUN_ENV 없음 — local(PC)·dev·prd 중 하나를 env RUN_ENV로 주거나 settings.yaml {L.to_yaml('common.run_env')}에 적음"
            "(PC: 저장소 루트 settings.yaml · 서버: settings.yaml — refactor.md C-34)",
            file=sys.stderr,
        )
        raise SystemExit(2)
    names = image_sections(environ) if sections is None else ("common", *sections)
    if value == "local":
        try:
            real = pc_real_targets(load(section_class(names)[0], environ=environ))
        except SettingsError as e:  # 모르는 칸·자리가 다른 칸 등 — 칸 자리만 알림
            print(f"{tag}설정을 읽지 못해 시작하지 않음: {e}", file=sys.stderr)
            raise SystemExit(2) from None
        if real:
            print(
                f"{tag}PC(RUN_ENV=local)는 가짜 대상만 — 실제 접속 칸이 적혀 있어 시작하지 않음: {', '.join(map(L.to_yaml, real))}. "
                f"PC는 저장소 루트 기준 상대 경로로 적는다 — {L.to_yaml('common.connections.rdb.sqlite')}: valid_env/edw/edw.sqlite 사본, "
                f"{L.to_yaml('pipeline.load.publish.bucket')}: file://output/object_storage/silver",
                file=sys.stderr,
            )
            raise SystemExit(2)
    if value in SERVER_ENVS:
        try:
            st = load(section_class(names)[0], environ=environ, require_file=True)
            invalid = []
            for path in _secret_paths(type(st)):
                secret = _get(st, path)
                if isinstance(secret, SecretStr):
                    for suffix, raw in secret_parts(secret.get_secret_value(), json_options=path.endswith(".connect_kwargs")).items():
                        if raw and len(raw) < MIN_SECRET_LENGTH:
                            invalid.append(path + suffix)
            if invalid:
                raise SettingsError("비밀 설정 정책 위반: " + ", ".join(sorted(invalid)))
        except SettingsError as e:
            print(f"{tag}서버(RUN_ENV={value}) — 설정을 읽지 못해 시작하지 않음: {e}", file=sys.stderr)
            raise SystemExit(2) from None
        if st.common.dev.llm_fake:  # 가짜 LLM 응답은 local에서만, 서버는 시작 거부
            print(f"{tag}서버(RUN_ENV={value}) — {L.to_yaml('common.dev.llm_fake')}가 켜져 있어 시작하지 않음(local 전용)", file=sys.stderr)
            raise SystemExit(2)
        bad = instance_problems(st)
        if bad:
            print(f"{tag}서버(RUN_ENV={value}) — 여러 벌 설정이 맞지 않아 시작하지 않음: {'; '.join(bad)}", file=sys.stderr)
            raise SystemExit(2)
    return value


def instance_problems(st):
    """여러 벌(ops.host.instance) 시작 거부 사유 — prd에 벌 이름, 벌 이름이 있는데 포트가 코드 기본값(다른 벌과 겹침)."""
    c = st.common
    if not c.host.instance:
        return []
    if c.run_env == "prd":
        return [f"{L.to_yaml('common.host.instance')}는 개발 서버(dev)에서만 — 운영(prd)은 한 벌"]
    ports = [("common.runtime.data_parsing_port", c.runtime, "data_parsing_port")]
    mcp = getattr(st, "mcp", None)
    if mcp is not None:
        ports.append(("mcp.server.port", mcp.server, "port"))
    return [
        f"{L.to_yaml(p)}가 기본값 그대로 — 벌마다 다른 포트를 적음"
        for p, sec, name in ports
        if getattr(sec, name) == type(sec).model_fields[name].default
    ]


def publish_prefix(prefix):
    """게시 경로 접두 — 개발 서버(dev)에 벌 이름이 있으면 `<접두>/<벌>`(벌마다 게시 자리가 갈림), 그 밖은 그대로."""
    c = cfg()
    inst = c.host.instance
    if c.run_env != "dev" or not inst:
        return prefix
    return f"{prefix.rstrip('/')}/{inst}" if prefix else inst


def pc_real_targets(st):
    """PC(local)가 거부하는 실제 외부 대상 칸(점 경로 목록) — 가짜/실제 판정은 이 한 곳(op-14). 가짜 = EDW sqlite 파일
    (connections.rdb.sqlite)·file:// 게시 폴더. 실제 = EDW 호스트·Object Storage 엔드포인트·원천 버킷·file://가 아닌 게시 버킷."""
    c = st.common.connections
    found = {"common.connections.rdb.host": c.rdb.host, "common.connections.object_storage.endpoint": c.object_storage.endpoint}
    pipe = getattr(st, "pipeline", None)
    if pipe is not None:
        bucket = pipe.load.publish.bucket or ""
        found["pipeline.connections.rdb.bucket"] = pipe.connections.rdb.bucket
        found["pipeline.load.publish.bucket"] = "" if bucket.startswith("file://") else bucket
    return [k for k, v in found.items() if v]


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
    """이 컨테이너가 읽는 절 — common + 자기 앱 절만: RAG_MODULE pipeline → common·pipeline, mcp → common·mcp,
    없음(PC — 빈 글자 포함) → 셋 다. 그 밖 글자(옛 이미지 이름 parse·structure·retrieval·오타·앞뒤 공백)는 빈 묶음. 이미지 안
    빈 글자 `RAG_MODULE=`도 빈 묶음. import 때 점검(pin_env)·시작 관문(require_run_env)이 쓴다 — 관계없는 앱 절은 검증하지 않는다."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    in_image = IN_IMAGE if in_image is None else in_image
    mod = environ.get("RAG_MODULE")  # env 남김 — 내부 신호
    if mod is None or (mod == "" and not in_image):
        return SECTIONS
    if mod in ("parse", "structure", "retrieval"):  # 옛 이미지 이름 — 이름만 알림
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


def pin_env(environ=None):
    """import common 때 한 번(common/__init__.py가 부름): 설정 파일을 읽어 본다 — 서버(dev·prd)에서 못 읽거나 형식이 틀리면
    SettingsError(시작 실패 — STRICT), local은 경고 뒤 계속. 반환: 0(호출부 호환)."""
    environ = os.environ if environ is None else environ  # env 남김 — RUN_ENV 신호
    allowed = image_sections(environ)
    run = environ.get("RUN_ENV") or None
    path = find_file(environ, run if run in RUN_ENVS else None)
    if not allowed:
        if path is not None:
            _warn_once("[설정] RAG_MODULE 모름(pipeline·mcp가 아님 — 이미지 안 빈 글자 포함) — 설정 파일 점검 건너뜀")
        return 0
    if path is not None:
        try:
            read_settings(path)  # 파일을 읽을 수 있는지만(칸 검증은 앱 설정 객체·시작 관문 — 호스트 export가 다른 앱 절 오타로 멈추지 않게)
        except SettingsError as e:
            if (
                _server_env(environ, path) and environ.get("SETTINGS_LENIENT") != "1"
            ):  # 내부 신호 — entrypoint가 점검 명령(check·selftest 등)에만 줌
                raise
            _warn_once(f"[설정] 설정 파일을 쓰지 않음(local 또는 점검 명령 — 기본값으로) — {e}")
    return 0


def external_models_allowed(run_env):
    """RUN_ENV 기준 외부 모델 허용 — 정확히 local일 때만 지금 가드(외부 허용 스위치·지출 상한)대로. 없음(env·설정 파일 모두 —
    이미지 selftest·관문 면제 점검 명령·관문 없는 스크립트)·dev·prd·모르는 글자(prod·PRD·' local' 등)는 서버로 보고 거부
    (안전한 쪽). guard.py가 guard_run_env()(모르는 글자 그대로)로 부른다."""
    return run_env == "local"


APP_MODULES = {"pipeline": ("pipeline.config", "PipelineAppSettings"), "mcp": ("mcp_server.config", "McpAppSettings")}


def _module_loading(mod, attr):
    """그 앱 설정 모듈이 지금 import 중인가(sys.modules에 있지만 뿌리 클래스가 아직 없음 — 순환)."""
    loading = sys.modules.get(mod)
    return loading is not None and not hasattr(loading, attr)


def _names_loading():
    """앱 설정 모듈 하나라도 import 중인가 — 그동안 _all_names()는 그 앱 칸 이름이 빠진 묶음이다."""
    return any(_module_loading(mod, attr) for mod, attr in APP_MODULES.values())


def app_classes(names=("pipeline", "mcp")):
    """앱 설정 뿌리 클래스 — 두 앱을 함께 보는 도구(export·keyscan 대조·덮기 파일)만 쓴다. common은 앱 코드를 정적으로
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


# ── 덮기 파일 — 같은 프로세스(put)·자식(child_env)·PC 한 번 실행(common.config.overrides) ─────────────
_GEN = [0]  # put()이 올림 — 모든 Cache가 다음 get()에서 다시 읽음
_EDW_READ_ONLY = [False]  # edw_read_only() — 이 프로세스는 EDW 읽기 계정만(CommonConnectionsRdb가 봄)


def edw_read_only(on=True):
    """이 프로세스는 EDW 읽기 계정만 본다 — 공용 settings.yaml에 쓰기 계정이 있어도 설정 객체에서 비운다(검색 MCP
    시작 때 부름 — 규칙: PRD docs/prd/ops.md#op-03). 파일은 바꾸지 않고, 모든 설정 캐시가 다음 읽기에서 다시 읽는다."""
    _EDW_READ_ONLY[0] = on
    _GEN[0] += 1


def _all_names():
    """{env 이름} — common + 이 이미지에 있는 앱 칸(호스트 칸 빼고). 앱 모듈 묶음마다 한 번만 걷는다."""
    classes = app_classes()
    key = tuple(sorted(classes))
    if key not in _ALL_NAMES:
        _ALL_NAMES[key] = _walk_names((CommonAppSettings, *classes.values()))
    return _ALL_NAMES[key]


_ALL_NAMES: dict = {}


def _walk_names(classes):
    return frozenset(env_name(f) for cls in classes for p, f, _ in walk(cls) if env_name(f) and not is_host(p))


def _check_names(names):
    known = _all_names()
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise KeyError(f"설정 칸이 없는 이름 {unknown}")
    return known


def overridden(environ=None):
    """지금 설정 파일(SETTINGS_FILE 덮기 파일 사슬)의 overrides에 든 이름 — 공유 settings.yaml 위에 한 번 덮은 값
    (mcp_eval client_only_env가 씀). 덮기 파일이 아니거나 못 읽으면 빈 묶음."""
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
    """덮기 파일을 만든다 — base(설정 파일 — 없으면 지금 SETTINGS_FILE·로컬 파일)를 가리키고 names({env 이름: 값|None})를 overrides로 든
    yaml을 임시 파일(mktemp — 권한 600)로 쓴다. 원본 내용(비밀)은 복사하지 않는다(base로 가리킴). base가 덮기 파일이면
    그 base·overrides를 이어받아 한 단으로. 지우는 것은 부른 쪽 몫 — put·child_env는 이 프로세스가 끝날 때(exitclean, 자식을 먼저
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
            # 이어받은 값: 따옴표 글자는 글자로, 손으로 쓴 YAML 값(true·false·숫자)은 그 꼴 그대로 다시 씀(읽는 규칙이 펼치기 전과 같게)
            over = {k: _Raw.of(v) if isinstance(v, YamlScalar) else v for k, v in inherited.items()}
            nb = Path(str(raw["base"])) if raw.get("base") else None
            base = (
                (nb if nb.is_absolute() else base.parent / nb).absolute() if nb is not None else None
            )  # 상대 base는 그 덮기 파일 폴더 기준(read_settings와 같게)
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
    다시 읽으면 같은 YamlScalar)."""

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


def put(**names):
    """이 프로세스의 설정 값을 바꾼다(`os.environ[X] = v` 대신): 덮기 파일을 만들어 SETTINGS_FILE을 그것으로 바꾸고(뒤에 띄우는
    자식도 같은 값을 받음), 모든 설정 캐시가 다음 읽기에서 다시 읽게 한다. None = 그 칸 비움(기본값).
    칸이 없는 이름은 KeyError. 반환: 덮기 파일 경로."""
    _check_names(names)
    p = exitclean.remove_at_exit(overlay_file(names))  # 이 프로세스가 끝날 때 지움
    os.environ["SETTINGS_FILE"] = str(p)  # env 남김 — 설정 파일 자리 신호
    _GEN[0] += 1
    return p


def child_env(base=None, **names):
    """자식 프로세스에 줄 env(`dict(os.environ, X=v)` 대신): base env(없으면 os.environ) 사본에, names를 덮은 덮기 파일을
    SETTINGS_FILE로 넣는다(부모 값은 그대로). names가 없으면 사본만."""
    env = dict(os.environ if base is None else base)  # env 남김 — 하위 프로세스
    if names:
        _check_names(names)
        env["SETTINGS_FILE"] = str(exitclean.remove_at_exit(overlay_file(names, environ=env)))  # 이 프로세스가 끝날 때 지움
    from common.core.jsonlog import get_context

    env["APPLOG_CONTEXT"] = json.dumps(get_context())  # env 남김 — 내부 신호(상관 ID, 설정 아님)
    return env


@contextlib.contextmanager
def isolated(**names):
    """시험용 — 지금 설정 위에 names를 덮은 덮기 파일로 바꿔 끼우고(그 안에서 부른 put()까지 그 동안만), 끝나면 SETTINGS_FILE을
    되돌린다(os.environ 저장·복원 대신). None = 그 칸 비움."""
    _check_names(names)
    keep = os.environ.get("SETTINGS_FILE")  # env 남김 — 시험
    p = overlay_file(names)
    os.environ["SETTINGS_FILE"] = str(p)  # env 남김 — 설정 파일 자리 신호(시험 — 끝나면 되돌림)
    _GEN[0] += 1
    try:
        yield
    finally:
        p.unlink(missing_ok=True)  # 블록 안에서만 쓰는 파일
        os.environ.pop("SETTINGS_FILE", None) if keep is None else os.environ.__setitem__(
            "SETTINGS_FILE", keep
        )  # env 남김 — 시험: 신호 되돌림
        _GEN[0] += 1


def _load_app(cls):
    """설정 캐시가 읽는 길 — 파일이 틀리면 서버는 실패(STRICT), local은 경고 뒤 기본값."""
    try:
        return load(cls, strict=False, require_file=False, lenient_run_env=True)
    except SettingsError as e:
        if (
            _server_env(os.environ, find_file(os.environ, None)) and os.environ.get("SETTINGS_LENIENT") != "1"
        ):  # env 남김 — RUN_ENV 신호 · 내부 신호(점검 명령)
            raise
        why = "점검 명령" if os.environ.get("SETTINGS_LENIENT") == "1" else "local"  # env 남김 — 내부 신호(점검 명령)
        _warn_once(f"[설정] 설정 파일을 쓰지 않음({why} — 기본값으로): {e}")  # 서버 점검 명령을 local로 적지 않게
        return load(cls, use_file=False, strict=False, require_file=False, lenient_run_env=True)


class Cache:
    """앱 설정 캐시 — get()은 처음 한 번 읽고, 신호(SETTINGS_FILE·RUN_ENV)가 바뀌거나 put()이 부르면 다시 읽는다. override()·env()는
    시험 동안만 바꿔 끼운다(os.environ은 건드리지 않음)."""

    _instances: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, app_cls):
        self.app_cls = app_cls
        self._value = None
        self._key = None
        self._fixed = False
        self._names = None
        self._instances.add(self)

    def get(self):
        if self._fixed:
            return self._value
        key = (
            os.environ.get("SETTINGS_FILE"),
            os.environ.get("RUN_ENV"),
            _GEN[0],  # env 남김 — 설정 파일 자리 신호
        )
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
        """with COMMON.env(LLM_MODEL="mock", LLM_BUDGET_USD=None): — 시험용. 설정 파일 위에 env 이름 값을 덮어(None = 그 칸 비움 — 기본값,
        겹쳐 쓰면 바깥 env() 값 포함, 값은 env 글자 꼴로 판정) 만든 객체를 그동안 바꿔 끼운다. RUN_ENV는 신호로 덮는다.
        os.environ은 건드리지 않는다(이 객체를 읽는 코드만 바뀜)."""
        base = dict(self._names or {})
        base.update({k: _env_text(v) for k, v in names.items()})
        environ = dict(os.environ)  # env 남김 — 시험
        data = None
        if "RUN_ENV" in base:
            environ.pop("RUN_ENV", None) if base["RUN_ENV"] is None else environ.__setitem__("RUN_ENV", base["RUN_ENV"])
            if base["RUN_ENV"] is None:
                data = {"common": {"run_env": None}}  # 없음 = 설정 파일의 common.run_env도 비움
        saved = self._names
        self._names = base
        try:
            with self.override(names=base, data=data, environ=environ, strict=False, require_file=False, lenient_run_env=True) as st:
                yield st
        finally:
            self._names = saved


@functools.cache
def _secret_paths(model_cls):
    return tuple(path for path, field, _ in walk(model_cls) if is_secret(field))


def secret_parts(value, *, json_options=True):
    """비밀 칸의 검사/마스킹 대상(상대 경로→값). 반환값은 출력하지 않는다.

    JSON은 비밀 라벨 문자열만, URL DSN은 디코딩한 password만 검사한다.
    일반 비밀 칸은 전체 값, ODBC 연결 문자열은 password/pwd 부분을 검사한다.
    """
    from common.core.runlog import _LABEL

    label = re.compile(r"(?:" + _LABEL + r")$", re.IGNORECASE)
    if json_options and value.lstrip().startswith(("{", "[")):
        try:
            pending, parts = [("", json.loads(value))], {}
            while pending:
                path, item = pending.pop()
                if isinstance(item, dict):
                    for key, child in item.items():
                        child_path = path + "." + key
                        if isinstance(child, str) and label.search(key):
                            parts[child_path] = child
                        elif isinstance(child, (dict, list)):
                            pending.append((child_path, child))
                elif isinstance(item, list):
                    pending.extend((f"{path}[{i}]", child) for i, child in enumerate(item) if isinstance(child, (dict, list)))
            return parts
        except (ValueError, TypeError):
            pass
    if "://" in value:
        try:
            password = urlsplit(value).password
            if password is not None:
                return {".password": unquote(password)}
        except ValueError:
            pass
    passwords = list(re.finditer(r"(?i)(?:password|pwd)\s*=\s*([^;]+)", value))
    if passwords:
        return {f".password[{i}]": match.group(1).strip("\"'{}") for i, match in enumerate(passwords)}
    return {"": value}


def secret_values(*, named=False):
    """로깅 마스킹 전용: 등록된 설정 객체의 비밀 칸 값. 반환값은 출력/저장하지 않는다.

    앱을 import하지 않으며 Cache.get()으로 덮기/시험 설정 변경도 반영한다.
    named=True는 경고용 설정 경로→값 사전이며 값은 출력하지 않는다.
    """
    values, names = set(), {}
    for cache in list(Cache._instances):
        model = cache.get()
        for path in _secret_paths(cache.app_cls):
            value = _get(model, path)
            if isinstance(value, SecretStr):
                raw = value.get_secret_value()
                values.add(raw)
                names[f"{cache.app_cls.__module__}.{path}"] = raw
    return names if named else values


# ── common 절 모델 ─────────────────────────────────────────────────────────────────────────
# 칸을 더하거나 옮기면 settings.sample.yaml을 다시 만든다(python -m common.config.sample).


class CommonConnectionsObjectStorage(Section):
    access_key: SecretStr | None = F(None, "OS_ACCESS_KEY", "Object Storage(S3) 액세스 키")
    endpoint: str | None = F(None, "OS_ENDPOINT", "Object Storage(S3 호환) 엔드포인트 URL — 비면 boto3 기본")
    region: str | None = F("us-east-1", "OS_REGION", "Object Storage 리전 이름")
    secret_key: SecretStr | None = F(None, "OS_SECRET_KEY", "Object Storage(S3) 시크릿 키")
    verify_tls: str | None = F("1", "OS_VERIFY_TLS", "TLS 인증서 검증(1=검증, 0=끔, 그 밖 문자열=CA 파일 경로)", blank="keep")


class CommonConnectionsParsingMeta(Section):
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
    """EDW(SQL Server) 접속 하나 — 서버·DB는 하나, 계정은 읽기·쓰기 둘(규칙: PRD docs/prd/ops.md#op-03)."""

    connect_kwargs: SecretStr | None = F(None, "RDB_CONNECT_KWARGS", "EDW pymssql 연결에 더할 추가 인자(JSON 객체 — TLS·로그인 시간 등)")
    database: str | None = F(None, "RDB_DATABASE", "EDW 데이터베이스 이름")
    host: str | None = F(None, "RDB_HOST", "EDW 서버 주소(호스트)")
    port: Port | None = F(1433, "RDB_PORT", "EDW 포트")
    sqlite: str | None = F(
        None,
        "RDB_SQLITE",
        "시험용 가짜 EDW(SQLite 파일 하나 — 모든 표) — 있으면 실제 EDW 대신 씀 · PC(RUN_ENV=local) 전용, 서버에서는 시작 거부",
        repo=True,
    )
    read: CommonConnectionsRdbRead = Field(default_factory=CommonConnectionsRdbRead)
    write: CommonConnectionsRdbWrite = Field(default_factory=CommonConnectionsRdbWrite)

    @model_validator(mode="after")
    def _read_only_process(self):
        """검색 MCP 프로세스(edw_read_only())는 쓰기 계정 칸을 보지 않는다 — 공용 settings.yaml에 있어도 설정 객체에서 비움."""
        if _EDW_READ_ONLY[0]:
            self.write = CommonConnectionsRdbWrite()
        return self


class CommonConnectionsPg(Section):
    connect_timeout: int | None = F(10, "PG_CONNECT_TIMEOUT", "PostgreSQL 연결 시도 제한 시간")
    db: str | None = F(None, "PG_DB", "PostgreSQL 데이터베이스 이름(필수 — op-09)")
    host: str | None = F(None, "PG_HOST", "PostgreSQL 서버 호스트 — 필수(자동 탐지·코드 기본값 없음, op-09)")
    password: SecretStr | None = F(None, "PG_PASSWORD", "PostgreSQL 비밀번호")
    pool_max: int | None = F(8, "PG_POOL_MAX", "검색 MCP PostgreSQL 연결 풀 최대 연결 수")
    port: Port | None = F(None, "PG_PORT", "PostgreSQL 포트(필수 — op-09)")
    db_schema: str | None = F(None, "PG_SCHEMA", "pgvector 기본 스키마 이름(소문자·숫자·_ — 필수, op-09)")
    standin_dir: str | None = F(None, "PG_STANDIN_DIR", "PG 접속 정보가 없을 때 쓰는 로컬 대체 DB(sqlite) 폴더", repo=True)
    standin_schema: str | None = F("ai", "PG_STANDIN_SCHEMA", "로컬 대체 DB(sqlite)의 스키마 이름 — PG_SCHEMA가 비었을 때(PC 전용, op-09)")
    user: str | None = F(None, "PG_USER", "PostgreSQL 접속 계정 이름(필수 — op-09)")


class CommonDevDocker(Section):
    mcp_publish_port: Port | None = F(18765, "MCP_PUBLISH_PORT", "시험 compose에서 MCP를 호스트에 게시할 포트")
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
    smoke_settings: str | None = F(
        None,
        "SMOKE_SETTINGS",
        "스모크 시험 컨테이너가 붙여 읽는 설정 파일(settings.yaml) 경로 — MCP 토큰·임베딩·Object Storage 키 등(S7e1 — 옛 SMOKE_ENV env 파일)",
    )
    smoke_keep: bool | None = F(False, "SMOKE_KEEP", "1이면 시험 끝나도 pg 컨테이너를 남김")
    smoke_limit: int | None = F(0, "SMOKE_LIMIT", "시험에서 파싱할 문서 수 상한(0이면 제한 없음)")
    smoke_pg_password: SecretStr | None = F(
        None, "SMOKE_PG_PASSWORD", "시험 PostgreSQL 비밀번호(compose.test.yml이 컨테이너 PG_PASSWORD로 넘김 — S7e1)"
    )


class CommonModelsEmbed(Section):
    allow_external: bool | None = F(
        False, "EMBED_ALLOW_EXTERNAL", "임베딩 외부 주소 허용(=1이면 열림, RUN_ENV=local일 때만 — 내부망 서버 시험·운영은 0)", on=("1",)
    )
    api_key: SecretStr | None = F(None, "EMBED_API_KEY", "임베딩 엔드포인트 API 키(있을 때만 Authorization 헤더로 보냄)")
    base_url: str | None = F(None, "EMBED_BASE_URL", "임베딩 엔드포인트 주소(OpenAI 호환 …/v1)")
    est_usd: float | None = F(0.001, "EMBED_EST_USD", "임베딩 호출 1건당 예상 비용($) — 예산 선차감용")
    model: str | None = F(None, "EMBED_MODEL", "임베딩 모델 이름(색인과 같아야 함 — 질의 임베딩·캐시 열쇠에도 씀)")
    query_cache: str | None = F(
        image_default("EMBED_QUERY_CACHE"),
        "EMBED_QUERY_CACHE",
        "질의 임베딩 캐시 sqlite 경로(0이면 캐시 끔 — mcp 이미지 안 기본 /tmp/mcp_query_cache.sqlite: 결과 폴더가 읽기 전용)",
    )
    query_cache_max: int | None = F(20000, "EMBED_QUERY_CACHE_MAX", "질의 임베딩 캐시 최대 행 수(넘으면 오래된 것부터 삭제, 0이면 무제한)")
    query_prefix: str | None = F(None, "EMBED_QUERY_PREFIX", "질의 임베딩 앞에 붙이는 지시 문구(예: 'Instruct: …\\nQuery: ')")
    timeout: int | None = F(60, "EMBED_TIMEOUT", "임베딩 API 호출 제한 시간(초)")


class CommonModelsGuard(Section):
    budget_usd: float | None = F(
        0.1,
        "LLM_BUDGET_USD",
        "외부 모델 호출 하루(현지 날짜·PC 사용자마다) 지출 상한($), 넘으면 호출 안 함 — 사용자 11-03, 비우면 기본 0.1, nan·inf는 형식 오류",
        allow_inf_nan=False,
    )
    internal_host_suffixes: CsvList | None = F(
        [], "INTERNAL_HOST_SUFFIXES", "내부망으로 인정할 호스트 이름 접미사 목록(쉼표 구분, 실제 주소가 사설일 때만)"
    )
    internal_ip_ranges: CsvList | None = F([], "INTERNAL_IP_RANGES", "사설(RFC1918) 밖의 사내 IP 대역 CIDR 목록(쉼표 구분)")
    spend_file: str | None = F(
        None,
        "LLM_SPEND_FILE",
        "지출 장부 파일 경로(이름 뒤에 날짜를 붙여 하루마다 새 파일) — 호출마다 금액 한 줄, 프로세스 전체가 공유",
    )


class CommonModelsLlm(Section):
    allow_external: bool | None = F(
        False, "LLM_ALLOW_EXTERNAL", "LLM(분류 등) 외부 주소 허용(=1, RUN_ENV=local일 때만 — 내부망 서버 시험·운영은 0)", on=("1",)
    )
    api_key: SecretStr | None = F(None, "LLM_API_KEY", "LLM 엔드포인트 API 키(있을 때만 사용)")
    base_url: str | None = F(None, "LLM_BASE_URL", "LLM 엔드포인트 주소(OpenAI 호환 …/v1)")
    cache_dir: str | None = F(None, "LLM_CACHE_DIR", "LLM 응답 캐시 폴더(요청 해시별 json)")
    empty_retry_max: int | None = F(8000, "LLM_EMPTY_RETRY_MAX", "빈 응답 재요청 때 max_tokens 상한(토큰)")
    est_usd: float | None = F(0.01, "LLM_EST_USD", "외부 LLM 도구 왕복 한 턴(admit_turn)당 예상 비용($) — 예산 선차감용")
    extra_body: JsonValue | None = F(
        None, "LLM_EXTRA_BODY", "LLM 요청 본문에 합칠 JSON 객체(예: 생각 끄기 {'reasoning':{'enabled':false}})"
    )
    model: str | None = F(None, "LLM_MODEL", "LLM 모델 이름")
    price_in: float | None = F(None, "LLM_PRICE_IN", "LLM 입력 단가($/백만 토큰) — 내장 가격표보다 우선")
    price_out: float | None = F(None, "LLM_PRICE_OUT", "LLM 출력 단가($/백만 토큰) — 내장 가격표보다 우선")
    rpm: int | None = F(0, "LLM_RPM", "LLM 분당 호출 상한(건) — 0이면 무제한")
    timeout: float | None = F(120.0, "LLM_TIMEOUT", "LLM 호출 제한 시간(초) — 호출자가 timeout을 주면 그 값이 우선")


class CommonModelsTransport(Section):
    connect_timeout: float | None = F(10.0, "MODEL_CONNECT_TIMEOUT", "모델 서버 연결(connect) 전용 제한 시간(초) — 0 이하면 끔")
    down_after: int | None = F(3, "MODEL_DOWN_AFTER", "연속 연결 실패 몇 번이면 그 주소를 '다운'으로 보는가(회)")
    down_cooldown: float | None = F(300.0, "MODEL_DOWN_COOLDOWN", "'다운' 판정 뒤 네트워크를 보내지 않고 즉시 거부하는 시간(초)")


class CommonModelsVlm(Section):
    allow_external: bool | None = F(
        False, "VLM_ALLOW_EXTERNAL", "VLM(그림·스캔 쪽) 외부 주소 허용(=1, RUN_ENV=local일 때만 — 내부망 서버 시험·운영은 0)", on=("1",)
    )
    api_key: SecretStr | None = F(None, "VLM_API_KEY", "VLM 엔드포인트 API 키(있을 때만)")
    base_url: str | None = F(None, "VLM_BASE_URL", "VLM 엔드포인트 주소(OpenAI 호환 …/v1)")
    concurrency: int | None = F(
        4,
        "VLM_CONCURRENCY",
        "문서 하나 안의 VLM 동시 요청 수(개, VLM 엔진 쪽·쪽 VLM·그림 VLM 공통 — 일괄 파싱은 max_concurrency ÷ 동시 문서 수까지 줄임)",
    )
    est_usd: float | None = F(0.02, "VLM_EST_USD", "VLM 호출 1건당 예상 비용($) — 예산 선차감용")
    extra_body: JsonValue | None = F(
        None,
        "VLM_EXTRA_BODY",
        "모든 VLM 요청 본문에 합칠 JSON 객체(엔진·쪽·그림 공통 — 생각 모델이면 생각 끄기 권장: 그림 VLM이 출력 상한을 추론에 다 써 빈 답이 될 수 있음)",
    )
    max_concurrency: float | None = F(
        8,
        "VLM_MAX_CONCURRENCY",
        "공유 VLM 서버 동시 요청 총량 상한(한 프로세스 안 모든 VLM 호출의 합 — 일괄 파싱은 동시 문서 수 × 문서당 동시 수가 이 값을 못 넘게 줄임)",
        unset=("auto",),
    )
    model: str | None = F(None, "VLM_MODEL", "VLM 모델 이름")
    retry: int | None = F(1, "VLM_RETRY", "VLM 호출 1건이 실패(시간 초과·연결 오류·429·5xx)할 때 재시도 횟수(회, 모든 VLM 호출 공통)")
    timeout: int | None = F(
        180, "VLM_TIMEOUT", "VLM 호출 1건 제한 시간(초, 모든 VLM 호출 공통 — VLM 엔진의 문서×엔진 제한 = 쪽 수 × 이 값)"
    )


class CommonDev(Section):
    llm_fake: bool | None = F(False, "LLM_FAKE", "1이면 LLM 호출을 네트워크·캐시 없는 모의 응답으로 대체(시험·비용 추정용)", on=("1",))
    docker: CommonDevDocker = Field(default_factory=CommonDevDocker)


class CommonHost(Section):
    doc_src: str | None = F(None, "DOC_SRC", "호스트 원본 문서 폴더 — compose가 컨테이너 /data/docs에 읽기 전용으로 붙임")
    docker: str | None = F(None, "DOCKER", "호스트 스크립트가 쓸 컨테이너 명령(docker|podman 등 — op-10)")
    instance: str | None = F(
        None,
        "INSTANCE",
        "한 서버에 여러 벌(개발자별 등) 띄울 때 이 루트의 이름(영소문자·숫자·-) — 컨테이너 이름·compose 묶음·systemd 타이머 이름 끝에 -<이름>으로 붙음."
        " 비우면 이름 그대로(한 벌). 적으면 PG 스키마·EDW 기록 표 끝에 _<이름>(-는 _로), 개발 서버(dev) 게시 경로에 <접두>/<이름>."
        " 포트(search.server.port · ops.runtime.data_parsing_port)는 벌마다 다르게(기본값 그대로면 시작 거부) · prd에서는 쓰지 않음(시작 거부)",
    )
    image_stage_dir: str | None = F(None, "IMAGE_STAGE_DIR", "prune_images.sh가 정리할 이미지 조각·tar 폴더(--stage-dir 기본값)")
    output_root: str | None = F(
        None,
        "RAG_OUT",
        "호스트의 결과(output) 폴더(서버 경로) — compose가 컨테이너 /app/output으로 마운트하는 원본. 비우면 <루트>/output",
    )
    pg_container: str | None = F(
        None,
        "PG_CONTAINER",
        "호스트에서 psql을 docker exec할 PostgreSQL(pgvector) 컨테이너 이름 — run_docs.py 문서 수 세기(S7e1 — 옛 코드 고정값)",
    )
    prune_keep: int | None = F(2, "PRUNE_KEEP", "prune_images.sh가 남길 이미지 판 수(지금 판 포함, --keep 기본값)")


class CommonPaths(Section):
    doc_dir: str | None = F(
        image_default("DOC_DIR"),
        "DOC_DIR",
        "원본 문서 폴더 — 원본 위치 주소·파싱 입력의 기준(pipeline 이미지 안 기본 /data/docs — 옛 Dockerfile ENV, B-2)",
        repo=True,
    )
    doc_dir_prepared: str | None = F(
        image_default("DOC_DIR_PREPARED"),
        "DOC_DIR_PREPARED",
        "준비(dedup·회전) 끝난 문서 폴더 — 파싱의 --src 기본값(pipeline 이미지 안 기본 /app/output/prepared — 옛 Dockerfile ENV, B-2)",
        repo=True,
    )
    draft_terms_out: str | None = F(None, "DRAFT_TERMS_OUT", "용어 자동 초안 CSV 경로")
    edw_chain: str | None = F(
        None,
        "EDW_CHAIN_FILE",
        "EDW 조인 사슬 파일 경로 — 적재(EDW 조인)와 검색 MCP(search attrs·edw_meta search_attrs)가 함께 읽음(pl-29·pl-52). 비우면 "
        "resources/config/edw_chain.yaml · 서버 사본은 컨테이너 안 /etc/rag/edw_chain.yaml(원본 <루트>/edw_chain.yaml — host_ctl.sh init이 "
        "없을 때만 복사, 적었을 때만 쓰임) · 점검: python -m pipeline.load.edw_doc_meta --check",
    )
    source_manifest: str | None = F(None, "SOURCE_MANIFEST", "원본 manifest.jsonl 경로(Object Storage/rdb에서 받은 문서 → s3:// 주소 대응)")
    stack_file: str | None = F(
        None,
        "PIPELINE_STACK_FILE",
        "엔진 구성 파일 경로(서버·PC 같음 — 사용자 11-01: 판 표 없앰)",
    )


class CommonRuntime(Section):
    cpu_max_load: float | None = F(0.9, "CPU_MAX_LOAD", "새 하위 프로세스를 띄우는 CPU 부하 상한(1분 부하 평균 ÷ 코어 수)", unset=("auto",))
    draft_terms_lock_timeout: float | None = F(
        5.0, "DRAFT_TERMS_LOCK_TIMEOUT", "용어 초안 CSV 쓰기 잠금 대기 시간(초) — 못 얻으면 이번엔 포기"
    )
    lib_env: LibEnv | None = F(
        {},
        "LIB_ENV",
        "라이브러리 env(이름: 글자 — TZ·OMP_NUM_THREADS·HF_HUB_OFFLINE 등 허용 목록만, 비밀 아님) — 컨테이너 시작 때 entrypoint가 env로 냄(사용자 env는 안 덮고 이미지 ENV는 덮음 — C-45 ⑤, S7e2)",
    )
    mem_max_pct: float | None = F(90.0, "MEM_MAX_PCT", "생산 파싱이 새 프로세스를 띄우는 메모리 사용률 상한(%)", unset=("auto",))
    mem_settle_margin: float | None = F(
        5.0, "MEM_SETTLE_MARGIN", "상한(MEM_MAX_PCT) 이만큼(%p) 아래부터 프로세스 띄운 뒤 잠깐 쉼", unset=("auto",)
    )
    mem_settle_sec: float | None = F(2.0, "MEM_SETTLE_SEC", "메모리가 상한 근처일 때 프로세스 띄운 뒤 쉬는 시간(초)", unset=("auto",))
    mem_start_pct: float | None = F(
        90.0, "MEM_START_PCT", "wait_mem 기본 상한 — 실험 도구가 새 프로세스를 띄우는 메모리 사용률(%)", unset=("auto",)
    )
    parse_max_mb: float = F(
        100.0,
        "DATA_PARSING_MAX_MB",
        "parse_document 파일 1건 크기 상한(MB = 1024×1024바이트) — 검색 MCP(content_b64)와 parse 서비스(path·content_b64)가 같은 값으로 거름(사용자 11-03)",
        gt=0,
    )
    data_parsing_port: Port = F(
        8766,
        "DATA_PARSING_PORT",
        "parse_document 작업 서비스 포트(127.0.0.1) — 작업 서비스가 듣고 검색 MCP가 부름. 여러 벌이면 벌마다 다르게(기본값이면 시작 거부)",
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


class CommonText(Section):
    draft_terms_max: int | None = F(500, "DRAFT_TERMS_MAX", "용어 자동 초안 파일 행 수 상한(개) — 넘으면 가장 빈번한 것만 유지")
    search_en_stem: bool | None = F(True, "SEARCH_EN_STEM", "검색 토큰의 영어 복수→단수 정규화(G16, 가산만) — =0이면 끔", off=("0",))
    source_uri_prefix: str | None = F(None, "SOURCE_URI_PREFIX", "원본 위치 주소의 접두어(예: s3://버킷/접두 · file:///<폴더>)")
    token_num_norm: bool | None = F(
        True,
        "TOKEN_NUM_NORM",
        "검색 토큰의 숫자·단위 정규화(T1) — =0이면 끄고 이전 동작",
        off=("", "0", "none", "false"),
        fold="lower",
    )


class CommonConnections(Section):
    object_storage: CommonConnectionsObjectStorage = Field(default_factory=CommonConnectionsObjectStorage)
    parsing_meta: CommonConnectionsParsingMeta = Field(default_factory=CommonConnectionsParsingMeta)
    pg: CommonConnectionsPg = Field(default_factory=CommonConnectionsPg)
    rdb: CommonConnectionsRdb = Field(default_factory=CommonConnectionsRdb)


class CommonModels(Section):
    embed: CommonModelsEmbed = Field(default_factory=CommonModelsEmbed)
    guard: CommonModelsGuard = Field(default_factory=CommonModelsGuard)
    llm: CommonModelsLlm = Field(default_factory=CommonModelsLlm)
    transport: CommonModelsTransport = Field(default_factory=CommonModelsTransport)
    vlm: CommonModelsVlm = Field(default_factory=CommonModelsVlm)


class CommonLog(Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = F("INFO", "LOG_LEVEL", "JSON 사건 기록 최소 수준")
    dir: str | None = F(None, "APPLOG_DIR", "JSON 로그 폴더 — 비우면 PC output/logs/, 서버 stdout")
    db_enabled: bool = F(
        image_default("APPLOG_DB_ENABLED", False),
        "APPLOG_DB_ENABLED",
        "applog DB 비동기 기록(서버 이미지 기본 켬, PC 기본 끔) — 서버 로그는 Postgres만, migrate up --target applog 먼저(op-13)",
    )
    fallback_dir: str | None = F(
        None, "APPLOG_FALLBACK_DIR", "DB 실패 시 JSON Lines 대체 기록 폴더(비우면 <앱 루트>/output/logs — 파일은 이 예비 한 곳, op-13)"
    )
    retention_days: int = F(90, "APPLOG_RETENTION_DAYS", "월 파티션 보존 일수(월 끝이 만료된 파티션만 DROP)", ge=1)
    queue_size: int = F(10000, "APPLOG_QUEUE_SIZE", "DB 기록 대기 큐 상한 — 넘으면 드롭 집계", ge=1)
    batch_size: int = F(200, "APPLOG_BATCH_SIZE", "DB INSERT 배치 최대 행 수", ge=1)
    flush_sec: float = F(1.0, "APPLOG_FLUSH_SEC", "DB 배치 기록 간격(초)", gt=0)
    db_timeout_sec: int = F(2, "APPLOG_DB_TIMEOUT_SEC", "로그 DB 연결/문장 제한(초)", ge=1)
    shutdown_sec: float = F(5.0, "APPLOG_SHUTDOWN_SEC", "종료 flush 전체 상한(초) — DB 대기+파일 기록, 초과 행은 dropped", ge=0)


class CommonTokens(Section):
    mcp: SecretStr | None = F(
        None,
        "MCP_TOKEN",
        "MCP 토큰 하나 — 검색 MCP Bearer(비루프백 바인드면 필수)·parse_document 프록시 → 작업 서비스 호출·작업 서비스 확인에 같이 씀",
    )


class CommonSettings(Section):
    run_env: Literal["local", "dev", "prd"] | None = F(
        None, "RUN_ENV", "실행 환경 — local(PC·valid_env 기준)·dev·prd(서버, 외부 모델 거부). env RUN_ENV가 이 값을 이김"
    )
    connections: CommonConnections = Field(default_factory=CommonConnections)
    dev: CommonDev = Field(default_factory=CommonDev)
    host: CommonHost = Field(default_factory=CommonHost)
    models: CommonModels = Field(default_factory=CommonModels)
    log: CommonLog = Field(default_factory=CommonLog)
    paths: CommonPaths = Field(default_factory=CommonPaths)
    runtime: CommonRuntime = Field(default_factory=CommonRuntime)
    text: CommonText = Field(default_factory=CommonText)
    tokens: CommonTokens = Field(default_factory=CommonTokens)

    @model_validator(mode="after")
    def _per_instance(self):
        """여러 벌 — 벌 이름이 있으면 PG 스키마·EDW 기록 표 끝에 `_<벌>`(`-`는 `_`로 — 읽는 곳 모두 이 값을 씀). 이름 꼴은 load_settings.sh와 같음."""
        inst = self.host.instance
        if inst and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", inst):
            raise ValueError(f"{L.to_yaml('common.host.instance')}는 영소문자·숫자·-만(앞은 글자·숫자)")
        if inst:
            pg, pm = self.connections.pg, self.connections.parsing_meta
            pg.db_schema = L.per_instance(pg.db_schema, inst)
            pm.table = L.per_instance(pm.table, inst)
        return self


class CommonAppSettings(AppSettings):
    """common 절만 — common 코드가 읽는 뿌리(COMMON)."""

    common: CommonSettings = Field(default_factory=CommonSettings)


# common 코드가 읽는 설정 객체 — 설정 파일(SETTINGS_FILE·로컬 파일)에서, 신호가 바뀌거나 put()이 부르면 다시 읽는다(Cache 설명).
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
        return None if v is None or reveal(v) == "" else v  # 비밀 칸 SecretStr('')도 빈 값(SecretStr('') != '')

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
    """env 이름으로 common 칸 값(형식 있는 값 — 비밀은 SecretStr) — 이름을 글자로 짓는 자리(`f"{prefix}_BASE_URL"`·모델 프로필의
    key_env)만 쓴다. 칸이 없거나(시험의 가짜 접두 ZZ_·X_) 값이 None이면 default."""
    return _COMMON_VIEW.by_env(name, default)


def given(name):
    """env 이름 칸에 값을 실제로 줬으면(env·YAML·시험 — 모델 기본값이 아니고 None·빈 글자도 아님 — 비밀 칸의 빈 값 포함) 그 값
    (비밀은 SecretStr), 아니면 None. "준 값만" 쓰는 자리(pg·edwdb conf의 접속 파일 덮기,
    resources._f의 호출자 기본값)용."""
    return _COMMON_VIEW.given(name)


def dropped(name):
    """env 이름 값이 형식이 틀려 객체에서 버려졌나(경고 뒤 기본값) — 그 값에서 실패해 일을 건너뛰어야 하는 자리가 같게
    건너뛸 때."""
    return _COMMON_VIEW.dropped(name)


def checked(name):
    """형식이 틀려 버린 값을 읽는 자리에서 실패(ValueError — 이름만, 값은 안 찍음). 기본값이 '제한 없음'이라 조용히
    넘어가면 위험한 칸(지출 상한 LLM_BUDGET_USD)·요청 모양이 바뀌는 칸(*_EXTRA_BODY)·접속 포트를
    읽기 바로 앞에서 부른다."""
    _COMMON_VIEW.checked(name)


def guard_run_env():
    """가드가 볼 RUN_ENV — 모르는 글자(prod·PRD 등 — 객체에서는 없음으로 처리)는 그 글자 그대로(서버로 봄)."""
    st = COMMON.get()
    return st.common.run_env or st._unknown_run_env


def token_text(v):
    """토큰 칸 값(SecretStr·글자·None) → 글자, 없거나 공백만이면 ""(토큰 없음). 공백이 섞인 토큰은 그대로 쓴다. 값은 출력하지 않는다."""
    t = reveal(v) or ""
    return t if t.strip() else ""


def reveal(v):
    """비밀 칸 값 → 글자(SecretStr이 아니면 그대로) — 접속·헤더에 넘길 때만."""
    return v.get_secret_value() if isinstance(v, SecretStr) else v


_TApp = CommonAppSettings
