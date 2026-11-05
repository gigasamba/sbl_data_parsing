"""pl-02 — 파싱 전 extract `candidate_ready.stage_batch`: 받기 → 중복 제외(받은 파일 sha256 — 같은 묶음 · ParsingMeta에 끝난 다른 원본)
→ 거르기(filter_and_rotate — DRM·암호·지원 안 함). 건너뛴 문서는 문서마다 extract.skip span 1행. ParsingMeta는 임시 SQLite EDW 대역 — 외부 접속 없음."""

import hashlib
import sys
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from common.core import jsonlog, span
from common.store.parsing_meta_db import SqliteStore
from pipeline.extract import candidate_ready as CR
from pipeline.extract import filter_and_rotate as FR

sha = lambda body: hashlib.sha256(body).hexdigest()
DONE_KEY = "SFDC/x/old.txt"  # ParsingMeta에 끝난(ok) 다른 원본 키 — old.txt와 같은 내용
# (파일, 내용, 기대 이유(None = 파싱 대상으로 남음), 기대 dup_of)
CASES = [
    ("a.txt", b"same", None, None),  # 보통 문서 · 같은 묶음 중복의 대표(이름에 사본 표시 없음)
    ("a(1).txt", b"same", "dup_batch", "a.txt"),  # 같은 묶음 안 같은 내용
    ("old.txt", b"old", "dup_done", DONE_KEY),  # ParsingMeta에 끝난 다른 원본과 같은 sha256
    ("drm.pdf", b"<## FASOO header", "drm_fasoo", None),  # DRM — 표시하고 건너뜀
    ("z.zip", b"PK\x03\x04zip", "unsupported_archive", None),  # 지원 안 함(압축)
    ("n.txt", b"normal", None, None),  # ParsingMeta에 같은 원본 키(n.txt)로 끝남 — 그 문서의 재처리라 남음
    ("f.txt", b"failed", None, None),  # ParsingMeta에 다른 키로 있지만 실패(끝난 상태 아님) — 남음
]
# ParsingMeta 행 (원본 키, 내용, parse_status, gold_version 있음?)
PM = [(DONE_KEY, b"old", "ok", True), ("n.txt", b"normal", "ok", True), ("SFDC/y/f.txt", b"failed", "failed", False)]


def _filter(args):
    """run_step 대신 — filter_and_rotate를 같은 프로세스에서(운영은 자식 프로세스로 같은 인자)."""
    assert args[0] == "pipeline.extract.filter_and_rotate"
    with mock.patch.object(sys, "argv", ["filter_and_rotate", *map(str, args[1:])]):
        FR.main()
    return 0


def test_stage_batch_order_and_skip_log():
    rows = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = SqliteStore(str(root / "edw.sqlite"))
        db.insert_new(
            [{"source_system": "SFDC", "source_key": k, "doc_key": sha(b), "sha256": sha(b), "parse_status": st} for k, b, st, _ in PM]
        )
        db.cn.executemany("UPDATE ParsingMeta SET gold_version = '0.2.0' WHERE source_key = ?", [(k,) for k, _, _, g in PM if g])
        db.cn.commit()
        db.close()
        with (
            COMMON.env(RUN_ENV="local", RDB_SQLITE=str(root / "edw.sqlite")),
            mock.patch.object(span, "_emit", lambda row, level=None: rows.append(row)),
            jsonlog.context(run_id=str(uuid.uuid4())),
        ):
            _, left, only, keep_txt = _run(root)
    want_left = [n for n, _, reason, _ in CASES if reason is None]
    assert sorted(left) == sorted(want_left) and only == left, left
    assert "old.txt" not in keep_txt and "a(1).txt" not in keep_txt and "drm.pdf" in keep_txt  # 게시가 중복을 skipped_dup로 씀
    skips = {r["doc_id"]: r for r in rows if r["stage"] == "extract.skip"}
    assert set(skips) == {n for n, _, reason, _ in CASES if reason}, skips
    for name, _, reason, dup_of in CASES:
        if reason is None:
            continue
        r = skips[name]
        assert (r["status"], r["err_kind"], r["err"], r["metrics"]["reason"]) == ("skip", "doc", reason, reason), r
        assert r["metrics"].get("dup_of") == dup_of, r


def _run(root):
    src, prepared = root / "src", root / "prepared"
    src.mkdir()
    for name, body, _, _ in CASES:
        (src / name).write_bytes(body)
    local, left, _, only = CR.stage_batch(str(src), root / "out", prepared, 0, _filter)
    keep_txt = (root / "out" / "dedup" / "keep.txt").read_text(encoding="utf-8").split()
    return local, left, only.read_text(encoding="utf-8").split(), keep_txt
