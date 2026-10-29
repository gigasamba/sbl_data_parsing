"""struct 스키마 행 모델(pydantic — S8a, 5-4). 칸은 models/struct_tables.py와 같은 이름·순서(시각 칸은 지금처럼 글자 — ISO 문자열).
S8b 판 표 두 개(stack_version·source_version)는 시각 칸이 TIMESTAMPTZ라 datetime, body 모양은 schemas/config_body.py."""

import datetime

from pydantic import BaseModel, JsonValue


class ContractMaster(BaseModel):
    contract_id: str
    company: str
    company_id: str
    product_code: str
    modality: str
    site: str
    line_id: str | None = None
    batches_contracted: int
    contract_value_usd: int
    currency: str
    term_months: int
    signed_on: str
    start_date: str
    end_date: str
    status: str


class ClientMaster(BaseModel):
    company_id: str
    company: str
    aliases: str | None = None


class ProdMaster(BaseModel):
    prod_code: str | None = None
    division: str | None = None
    prod_name: str | None = None
    pjt_name: str | None = None
    client_code: str | None = None


class DocContractLink(BaseModel):
    doc_key: str
    contract_id: str | None = None
    score: int | None = None
    how: str | None = None
    status: str | None = None
    evidence_chunk_keys: str | None = None
    created_at: str | None = None


class DocLocation(BaseModel):
    doc_id: str
    bucket: str | None = None
    object_key: str | None = None
    etag: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    company_id: str | None = None
    doc_type: str | None = None
    contract_id: str | None = None
    version: int | None = None
    supersedes_doc_id: str | None = None
    language: str | None = None
    received_at: str | None = None
    updated_at: str | None = None
    is_deleted: int | None = None


class DocRegistry(BaseModel):
    doc_key: str
    names: str | None = None
    size: int | None = None
    mtime: str | None = None
    etag: str | None = None
    status: str | None = None
    source: str | None = None
    doc_id: str | None = None
    version: str | None = None
    first_seen: str
    last_seen: str
    last_build: str
    rep_sha: str | None = None
    rep_pairs: str | None = None
    edition_of: str | None = None
    content_group: str | None = None
    value_changes: str | None = None
    source_keys: str | None = None
    fail_count: int | None = None


class DocRegistrySeen(BaseModel):
    doc_key: str
    build_id: str
    names: str | None = None
    size: int | None = None
    mtime: str | None = None
    etag: str | None = None
    status: str | None = None
    source: str | None = None
    seen_at: str


class DocHidden(BaseModel):
    doc_key: str
    hidden: int
    reason: str | None = None
    by: str | None = None
    at: str


class DocTable(BaseModel):
    table_key: str
    doc_key: str
    table_id: str
    page: int | None = None
    source_engine: str | None = None
    n_rows: int | None = None
    n_cols: int | None = None
    header_json: str | None = None
    merged_json: str | None = None
    created_at: str


class DocCell(BaseModel):
    table_key: str
    row_idx: int
    col_idx: int
    col_label: str | None = None
    value: str | None = None
    value_norm: str | None = None


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
    "contract_master": ContractMaster,
    "client_master": ClientMaster,
    "prod_master": ProdMaster,
    "doc_contract_link": DocContractLink,
    "doc_location": DocLocation,
    "doc_registry": DocRegistry,
    "doc_registry_seen": DocRegistrySeen,
    "doc_hidden": DocHidden,
    "doc_table": DocTable,
    "doc_cell": DocCell,
    "stack_version": ConfigVersion,
    "source_version": ConfigVersion,
}
