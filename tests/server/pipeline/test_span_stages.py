"""op-01: 임베딩·적재 단계의 span 지표 — 외부 접속 없이(임베딩 호출은 patch.object, 적재는 가짜 DB 커서). 운영 경로엔 가짜 코드 없음."""

import json
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

import numpy as np

from common.ai import embed
from common.config import settings
from common.core import jsonlog, span
from pipeline.load import edw_doc_meta as edw_meta
from pipeline.load import pgvector_load
from pipeline.transform.structure import build_bundle


def _capture():
    rows = []
    return rows, mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row))


def test_warm_span_counts():
    from pipeline.extract import fetch_docs as source

    class Client:
        def head_object(self, **kw):
            return {"ContentLength": 1}

        def download_file(self, bucket, key, dest):
            if key.endswith("bad"):
                raise OSError("down")
            Path(dest).write_bytes(b"x")

    rows, patched = _capture()
    with tempfile.TemporaryDirectory() as tmp, patched, jsonlog.context(run_id=str(uuid.uuid4())):
        batch = Path(tmp) / "batch.csv"
        cols = {"size": "size", "filename": "name"}
        batch.write_text("size,name,key\n1,a,ok\n1,b,bad\n", encoding="utf-8")
        with (
            mock.patch.object(source, "_warm_dir", lambda: Path(tmp)),
            mock.patch.object(source, "_rdb_cols", lambda: cols),
            mock.patch.object(source, "_rdb_bucket_and_key", lambda c, r: ("b", r["key"])),
            mock.patch.object(source, "_s3", Client),
        ):
            assert source._warm_cmd(["--csv", str(batch), "--workers", "1"]) == 0
    row = next(r for r in rows if r["stage"] == "extract.warm")
    assert row["layer"] == "extract" and row["total"] == 2 and row["metrics"] == {"done": 1, "failed": 1}


def test_parse_attempt_column():
    from pipeline.extract import run_engines as run_all

    def run(side_effect):
        rows, patched = _capture()
        with patched, jsonlog.context(run_id=str(uuid.uuid4())):
            with mock.patch.object(run_all, "_isolated", mock.Mock(side_effect=side_effect)):
                with span.span("extract.parse"):
                    run_all._run_with_retry("pymupdf", Path("a.pdf"), Path("a.json"), "default", 20.0, [], None)
        return rows[0]["attempt"]

    assert run([None]) == 1
    assert run([TimeoutError("시간 제한 초과"), None]) == 2  # 시간 초과로 한 번 더


def test_embed_span_cache_batches_retries():
    calls = []

    def fake_api(texts, kind="passage"):
        calls.append(len(texts))
        if len(calls) == 2:  # 두 번째 호출은 서버 일시 오류 — 다시 보낸다
            raise OSError("busy")
        return np.tile(np.arange(1, 5, dtype=np.float32), (len(texts), 1))

    texts = [f"청크 본문 {i}" for i in range(5)]
    rows, patched = _capture()
    with tempfile.TemporaryDirectory() as tmp, patched, jsonlog.context(run_id=str(uuid.uuid4())):
        cache = str(Path(tmp) / "cache.sqlite")
        with settings.isolated(EMBED_BASE_URL="http://127.0.0.1:9/v1", EMBED_MODEL="m"):
            with mock.patch.object(embed, "_embed_api", fake_api), mock.patch.object(time, "sleep", lambda s: None):
                with span.span("embed.bundle", "embed", model="api") as sp:
                    first = build_bundle.embed_all("api", texts, batch=2, cache=cache)
                    sp.add(chunks=len(texts))
                with span.span("embed.bundle", "embed", model="api"):
                    second = build_bundle.embed_all("api", texts, batch=2, cache=cache)
    assert first.shape == second.shape == (5, 4) and np.allclose(first, second)
    embeds = [r for r in rows if r["stage"] == "embed.bundle"]
    cold, warm = (r["metrics"] for r in embeds)
    progress = [r for r in rows if r["stage"] == "run.progress"]  # 호출이 있던 첫 번째만 — 캐시만 쓴 두 번째는 없음
    assert len(progress) == 1 and progress[0]["seq"] == progress[0]["total"] == 5 and progress[0]["metrics"]["unit"] == "chunk"
    assert (cold["cache_hit"], cold["cache_miss"], cold["batches"], cold["embed_retries"]) == (0, 5, 3, 1)
    assert cold["embed_calls"] == 3 and cold["embed_call_ms_n"] == 3 and cold["chunks"] == 5  # 실패한 호출은 지연에 안 셈
    assert embeds[0]["ext_call_ms"] >= 0 and embeds[0]["model"] == "api" and embeds[0]["layer"] == "embed"
    assert (warm["cache_hit"], warm["cache_miss"], warm["batches"]) == (5, 0, 0) and "embed_calls" not in warm  # 두 번째는 전부 캐시


def test_embed_hook_is_free_without_span():
    rows, patched = _capture()
    with patched, mock.patch.object(embed, "_embed_api", lambda texts, kind="passage": np.ones((len(texts), 2), dtype=np.float32)):
        assert embed._embed_uncached("api", ["a"], "passage").shape == (1, 2)
    assert rows == []


class _Cur:
    def __init__(self, log):
        self.log, self.n, self.last = log, 0, ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.last = " ".join(sql.split())
        self.log.append(self.last)

    def fetchone(self):
        self.n += 1
        return (True,) if "NOT EXISTS" in self.last else (self.n,)

    def fetchall(self):
        return []

    def copy(self, sql):
        return _Copy(self.log)


class _Copy:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write_row(self, row):
        self.log.append("ROW")


class _Tx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _DB:
    schema = "t"
    is_standin = False

    def __init__(self):
        self.log = []
        self.cn = self

    def transaction(self):
        return _Tx()

    def cursor(self):
        return _Cur(self.log)

    def q(self, sql, params=None):  # 원천 스키마 조회(_elsewhere) — 다른 원천에 같은 문서 없음
        return []


def test_load_table_spans():
    # Windows는 load()가 mmap으로 연 vectors.npy를 지우지 못함 — 정리 실패는 무시
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        bundle = Path(tmp)
        docs = [{"file_path": "a.txt", "summary": "s"}, {"file_path": "b.txt", "summary": "s"}]
        chunks = [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "char_start": 0,
                "char_end": 5,
                "bbox": None,
                "section": None,
                "chunk_text": "alpha beta",
                "n_chars": 10,
                "n_terms": 2,
            },
            {
                "doc": 1,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "char_start": 0,
                "char_end": 5,
                "bbox": None,
                "section": None,
                "chunk_text": "gamma",
                "n_chars": 5,
                "n_terms": 1,
            },
        ]
        (bundle / "docs.jsonl").write_text("\n".join(json.dumps(d) for d in docs), encoding="utf-8")
        (bundle / "chunks.jsonl").write_text("\n".join(json.dumps(c) for c in chunks), encoding="utf-8")
        (bundle / "meta.json").write_text(json.dumps({"dim": 3, "embed_model": "m"}), encoding="utf-8")
        np.save(bundle / "vectors.npy", np.ones((2, 3), dtype=np.float32))
        rows, patched = _capture()
        db = _DB()
        no_edw = mock.patch.object(edw_meta, "fetch", lambda docs: ({}, 0))  # EDW 조인·ParsingMeta 쓰기는 이 시험 밖(pl-29)
        no_pm = mock.patch.object(pgvector_load, "_mark_loaded", lambda loaded, kept=(), version=None: 0)
        with patched, no_edw, no_pm, jsonlog.context(run_id=str(uuid.uuid4())):
            with span.span("load.pgvector", "load") as top:
                counts = pgvector_load.load(db, bundle)
    assert counts["docs"] == 2 and counts["chunks"] == 2
    by_stage = {r["stage"]: r for r in rows}
    assert set(by_stage) == {"load.doc", "load.chunk", "load.chunk_term", "load.stats", "load.pgvector"}
    assert by_stage["load.doc"]["metrics"]["rows"] == 2 and by_stage["load.doc"]["metrics"]["rows_per_sec"] > 0
    assert by_stage["load.chunk"]["metrics"]["rows"] == 2 and by_stage["load.chunk"]["metrics"]["chars"] == 15
    assert by_stage["load.chunk_term"]["metrics"]["rows"] == 3  # alpha·beta·gamma
    assert all(by_stage[s]["parent_id"] == top.span_id for s in ("load.doc", "load.chunk", "load.chunk_term", "load.stats"))
    assert all(r["layer"] == "load" and r["status"] == "ok" for r in rows)
