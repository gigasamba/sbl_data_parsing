"""엔진 구성 파일 읽기 — 서버·PC 같은 길(DB 표 없이 파일만).
· 파일 자리: 설정 common.paths.stack_file — 비우면 resources/config/pipeline_stack.json(두 이미지에 다 있음).
  (원천은 폴더·rdb:csv로만 정한다.) 바꾸기 = 파일을 고쳐 오버레이 패치(코드 폴더) — 되돌리기는 git.
· 읽을 때 모양 검사(pydantic — 아래 StackFile). 못 읽거나 모양이 틀리면 한 줄 안내 + 종료 2(시작하지 않음).
· body_sha = 정규 JSON(키 정렬·공백 없음·UTF-8)의 sha256 — 같은 구성이면 서버·PC 같은 값.
· 층 파일은 이 모듈을 import하지 않는다(code_fp에 넣지 않으려고): 층은 pipeline.config.stack()으로 읽는다.
· 값·비밀은 찍지 않는다(이름·sha·파일 경로만)."""

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

STACK_BODY_KEYS = ("parse", "source", "embed", "chunk", "graph", "retrieve", "k")  # 파일 body 칸(name은 따로, 메모는 docs)


class StackBody(BaseModel):
    """엔진 구성 설정 칸 — parse = 형식(.pdf_text·.docx …) → 엔진 우선순위(비교 후보 candidates 칸은 0.2.0에 지움 — pl-46)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    parse: dict[str, list[str]]
    source: str | None = None
    embed: str
    chunk: str
    graph: str
    retrieve: str
    k: int

    @field_validator("parse")
    @classmethod
    def _parse(cls, v):
        if not v:
            raise ValueError("parse가 비어 있음 — 형식마다 엔진 목록")
        for fmt, engines in v.items():
            if not fmt.startswith(".") or not engines or not all(e.strip() for e in engines):
                raise ValueError(f"parse[{fmt!r}] — 형식은 '.'으로 시작, 엔진 목록은 비지 않은 이름")
        return v

    @field_validator("k")
    @classmethod
    def _k(cls, v):
        if v < 1:
            raise ValueError("k는 1 이상")
        return v


class StackFile(StackBody):
    """PC 파일 모양 — body 칸 + 이름 + 고친 시각 + client_aliases(인계 파일 terms.py가 파일에서만 읽음 —
    엔진 구성 body 밖)."""

    name: str
    updated: str | None = None
    client_aliases: dict[str, list[str]] | None = None


def stack_body(doc):
    """PC 파일 dict → (name, body) — body는 STACK_BODY_KEYS만(있는 것만, 파일 순서), 모양 검사 뒤."""
    StackFile.model_validate(doc)
    return doc["name"], {k: doc[k] for k in doc if k in STACK_BODY_KEYS}


KINDS = {"stack": "엔진 구성"}  # kind 인자 값 — 지금은 "stack" 하나
_CACHE: dict = {}


@dataclass(frozen=True)
class Active:
    kind: str
    name: str
    body: Any  # 엔진 구성 dict
    body_sha: str
    origin: str  # 파일 경로

    def named(self):
        """body + name — stack.json 꼴(검색 MCP·ask가 읽는 사전)."""
        return {"name": self.name, **self.body}

    def label(self):
        return f"{self.kind} {self.name} · sha {self.body_sha[:12]} · {self.origin}"


def canon(body):
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(body):
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


def _errors(e):
    return "; ".join(f"{'.'.join(map(str, x['loc'])) or '-'} {x['msg']}" for x in e.errors())


def file_of(kind="stack"):
    from common.config.settings import cfg
    from common.core.paths import STACK_FILE

    return Path(cfg().paths.stack_file or STACK_FILE)


def read_file(kind, path=None):
    """파일 → Active. 엔진 구성 파일 = body 칸 + name(+ updated·client_aliases)."""
    p = Path(path) if path else file_of(kind)
    doc = json.loads(p.read_text(encoding="utf-8"))
    from pydantic import ValidationError

    try:
        name, body = stack_body(doc)
    except ValidationError as e:  # 칸 이름·이유만(값은 안 찍음) — 메모 칸(storage·*_note)은 docs/architecture/resources.md로
        raise ValueError(
            f"{p}: 엔진 구성 파일 모양이 틀림 — {_errors(e)} · 메모 칸(storage·*_note)은 이 파일에 두지 않음(docs/architecture/resources.md)"
        ) from None
    return Active(kind, name, body, sha(body), str(p))


def active(kind, refresh=False):
    """지금 쓸 구성 — 프로세스마다 한 번 읽음(refresh=True면 다시 — 작업마다 읽는 서비스)."""
    if kind in _CACHE and not refresh:
        return _CACHE[kind]
    try:
        a = read_file(kind)
    except (OSError, ValueError) as e:  # 트레이스백 대신 한 줄 안내 + 종료 2
        print(f"[{KINDS[kind]}] 파일을 쓰지 못함 — {e}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    _CACHE[kind] = a
    return a
