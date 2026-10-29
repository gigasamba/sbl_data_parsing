"""검색 스키마 행 모델(pydantic — S8a, 5-4). 칸은 models/search_tables.py와 같은 이름·순서. SERIAL 키·기본값 있는 칸은 넣을 때 비워 둠(None).
벡터는 글자 '[…]'가 아니라 숫자 목록, JSON 칸(params·counts)은 파이썬 값. doc.clients는 JSON 인코딩 TEXT(지금 적재 그대로)."""

import datetime as _dt
from typing import Any

from pydantic import BaseModel


class LoadRun(BaseModel):
    run_id: int | None = None
    started_at: _dt.datetime | None = None
    finished_at: _dt.datetime | None = None
    params: Any = None
    counts: Any = None


class Doc(BaseModel):
    doc_id: int | None = None
    file_path: str
    clients: str | None = None
    summary: str | None = None
    source_system: str | None = None
    sf_acc_name: str | None = None
    sf_op_id: str | None = None
    sf_op_name: str | None = None
    project_code__c: str | None = None
    contract_id: str | None = None
    contract_date: _dt.date | None = None
    prod_name: str | None = None
    division: str | None = None
    service_type: str | None = None
    run_id: int | None = None


class Chunk(BaseModel):
    chunk_id: int | None = None
    doc_id: int
    seq: int
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    bbox: str | None = None
    section: str | None = None
    chunk_text: str
    n_chars: int
    n_terms: int
    embed_model: str | None = None
    embedding: list[float] | None = None
    clients: list[str] | None = None
    source_system: str | None = None


class ChunkTerm(BaseModel):
    term: str
    chunk_id: int
    tf: int


class TermStat(BaseModel):
    term: str
    df: int


class CorpusStat(BaseModel):
    id: int | None = None
    n_chunks: int
    avg_len: float
    dim: int


ROWS = {"load_run": LoadRun, "doc": Doc, "chunk": Chunk, "chunk_term": ChunkTerm, "term_stat": TermStat, "corpus_stat": CorpusStat}
