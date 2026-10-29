"""판 표 body 모양(pydantic — S8b, D-031): 엔진 구성(stack_version.body · PC 파일 resources/config/pipeline_stack.json)·원천 목록
(source_version.body · PC 파일 resources/mappings/sources.json). 판 표·PC 파일·set-stack·set-sources가 같은 검사를 쓴다. 원천 항목 검사는
common/core/sources.py `_validate_entry` 한 곳(글자·규칙 그대로) — 여기서는 목록·이름 중복만 더한다."""

from pydantic import BaseModel, ConfigDict, RootModel, field_validator, model_validator

STACK_BODY_KEYS = ("parse", "source", "embed", "chunk", "graph", "retrieve", "k", "candidates")  # 판 표 body(name은 칸, 메모는 docs)


class StackBody(BaseModel):
    """엔진 구성 설정 칸 — parse = 형식(.pdf_text·.docx …) → 엔진 우선순위, candidates = 비교 후보(파싱 기본 엔진 = parse ∪ candidates)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    parse: dict[str, list[str]]
    source: str | None = None
    embed: str
    chunk: str
    graph: str
    retrieve: str
    k: int
    candidates: list[str] = []

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
    """PC 파일 모양 — body 칸 + 이름(판 표 name 칸) + 고친 시각(set-stack이 씀) + client_aliases(인계 파일 terms.py가 파일에서만 읽음 —
    판 표 밖)."""

    name: str
    updated: str | None = None
    client_aliases: dict[str, list[str]] | None = None


class SourcesBody(RootModel[list[dict]]):
    """원천 목록 — 항목마다 sources._validate_entry(옛 글자 그대로) + 이름 중복 거부."""

    @model_validator(mode="after")
    def _entries(self):
        from common.core.sources import _validate_entry

        seen = set()
        for i, entry in enumerate(self.root):
            v = _validate_entry(entry, "body", i)
            if v["name"] in seen:
                raise ValueError(f"[sources] body — name 중복: {v['name']}")
            seen.add(v["name"])
        return self


def stack_body(doc):
    """PC 파일 dict → (name, body) — body는 STACK_BODY_KEYS만(있는 것만, 파일 순서), 모양 검사 뒤."""
    StackFile.model_validate(doc)
    return doc["name"], {k: doc[k] for k in doc if k in STACK_BODY_KEYS}
