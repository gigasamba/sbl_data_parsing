"""struct 스키마 행 모델(pydantic — S8a, 5-4). 칸은 models/struct_tables.py와 같은 이름·순서. 판 표 두 개(stack_version·source_version — S8b)만
남음(나머지는 판 0003이 지움 — pl-08). 시각 칸은 TIMESTAMPTZ라 datetime, body 모양은 schemas/config_body.py."""

import datetime

from pydantic import BaseModel, JsonValue


class ConfigVersion(BaseModel):
    """stack_version·source_version 한 행(두 표 같은 모양 — S8b)."""

    version_id: int | None = None
    name: str
    body: JsonValue
    body_sha: str
    is_active: bool | None = None
    created_at: datetime.datetime | None = None
    created_by: str | None = None
    reason: str | None = None
    activated_at: datetime.datetime | None = None
    activated_by: str | None = None


ROWS = {
    "stack_version": ConfigVersion,
    "source_version": ConfigVersion,
}
