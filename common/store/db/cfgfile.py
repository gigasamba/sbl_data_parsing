"""엔진 구성 파일 읽기 — 서버·PC 같은 길(사용자 11-01: struct 판 표 없앰, 파일만 — D-031·pl-08).
· 파일 자리: 설정 common.paths.stack_file — 비우면 resources/config/pipeline_stack.json(두 이미지에 다 있음).
  (원천 목록 sources.json은 11-01에 지움 — 원천은 폴더·rdb:csv만.) 바꾸기 = 파일을 고쳐 오버레이 패치(코드 폴더) — 되돌리기는 git.
· 읽을 때 모양 검사(pydantic — schemas/config_body.py). 못 읽거나 모양이 틀리면 한 줄 안내 + 종료 2(시작하지 않음).
· body_sha = 정규 JSON(키 정렬·공백 없음·UTF-8)의 sha256 — 같은 구성이면 서버·PC 같은 값.
· 층 파일은 이 모듈을 import하지 않는다(code_fp — D-030 ⑦): 층은 pipeline.config.stack()으로 읽는다.
· 값·비밀은 찍지 않는다(이름·sha·파일 경로만)."""

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KINDS = {"stack": "엔진 구성"}  # kind 인자는 옛 호출 호환(지금은 "stack" 하나)
_CACHE: dict = {}


@dataclass(frozen=True)
class Active:
    kind: str
    name: str
    body: Any  # 엔진 구성 dict
    body_sha: str
    origin: str  # 파일 경로

    def named(self):
        """body + name — 옛 stack.json 꼴(검색 MCP·ask가 읽는 사전)."""
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
    from common.store.db.schemas import config_body as CB

    p = Path(path) if path else file_of(kind)
    doc = json.loads(p.read_text(encoding="utf-8"))
    from pydantic import ValidationError

    try:
        name, body = CB.stack_body(doc)
    except ValidationError as e:  # 칸 이름·이유만(값은 안 찍음) — 메모 칸(storage·*_note)은 docs/architecture/pipeline_stack.md로
        raise ValueError(
            f"{p}: 엔진 구성 파일 모양이 틀림 — {_errors(e)} · 메모 칸(storage·*_note)은 이 파일에 두지 않음(docs/architecture/pipeline_stack.md)"
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
