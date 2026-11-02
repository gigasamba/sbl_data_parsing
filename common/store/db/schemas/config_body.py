"""엔진 구성 파일 모양(pydantic — S8b, D-031): resources/config/pipeline_stack.json. 서버·PC가 파일을 읽을 때
(common.store.db.cfgfile) 이 검사를 쓴다(사용자 11-01 — 판 표 없앰 · 원천 목록 sources.json 모양 SourcesBody는 11-01에 지움)."""

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
