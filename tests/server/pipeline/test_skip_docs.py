"""op-17 — 적재되지 않은 문서 `applog.except_doc_info`: 영구 뺌(skip — 받기 전 rdb:csv 지원 안 하는 확장자·받은 뒤 거르기 DRM·암호·
지원 안 함·확장자 없음·내용 중복)과 실패(error — 파싱·적재)를 원본 키 + 종류당 한 행씩 upsert(처음·마지막 시각·횟수) → 대상 목록
`list --skip-done`이 skip 키만 뺀다(error는 다음 실행이 다시 고름). PC 대역 sqlite(임시 폴더)만 — 외부 접속 없음."""

import contextlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from common.store import pg as PGC
from pipeline import config as pc
from pipeline.extract import candidate_pick as CP
from pipeline.extract import candidate_ready as CR
from pipeline.extract import filter_and_rotate as FR
from pipeline.shared import except_docs as SD

# (원본 키, 파일 이름, 거르기 이유, skip 행 이유(None = 쓰지 않음))
REASONS = [
    ("SFDC/a/x.zip", "x.zip", "unsupported_archive", "unsupported_archive"),
    ("SFDC/b/x.exe", "x.exe", "unsupported_format", "unsupported_format"),
    ("CRMS/c/noext", "noext", "unsupported_format", "no_extension"),  # 확장자 없는 이름
    ("SFDC/d/d.pdf", "d.pdf", "drm_fasoo", "drm_fasoo"),
    ("SFDC/e/e.doc", "e.doc", "encrypted_doc", "encrypted_doc"),
    ("SFDC/h/h.txt", "h.txt", "duplicate_sha256", "duplicate_sha256"),  # 이번 실행의 다른 원본과 같은 내용(pl-59)
    ("SFDC/f/f.txt", "f.txt", "dup_batch", None),  # 영구 이유가 아님(중복은 candidate_ready가 duplicate_sha256으로 바꿔 씀)
    ("SFDC/g/g.pdf", "g.pdf", "fail", None),  # 파싱 실패는 다시 시도
]
# 판 0004 — (원본 키, 행의 file_size, 기대 (file_ext, file_size)): 확장자는 파일 이름에서(소문자, 점 없음), 크기 빈 칸·없음 = NULL
EXT_SIZE = [
    ("SFDC/a/x.zip", 1, ("zip", 1)),
    ("CRMS/c/noext", "3", (None, 3)),  # 문서 위치 표(csv) 값은 글자
    ("SFDC/d/d.pdf", "", ("pdf", None)),
    ("SFDC/e/e.doc", None, ("doc", None)),
]
# rdb:csv 한 줄 묶음(run_pipeline batch.csv) — 모두 받기 전에 걸러짐(지원 안 하는 확장자) → 받을 것 0건이어도 멈추지 않음
RDB_ROWS = [("1", "SFDC/u1/a.zip", "a.zip"), ("2", "SFDC/u2/b.7z", "b.7z")]  # 원천 칸 = dev-1(키 첫 마디와 달라도 그 값, 대문자로 — op-17)
# 원천 목록(extract.source.systems) → 건너뜀 기록 여부 — 목록 밖 행은 고르지도 기록하지도 않음(비우면 운영 5개 원천 — DEV 행은 밖, op-17 규칙 8)
RDB_SYSTEMS = [(None, False), ("DEV-1", True), ("dev-1,SFDC", True), ("SFDC", False)]


@contextlib.contextmanager
def standin(d):
    """PG 접속 없음(대역 sqlite를 임시 폴더에)."""
    with COMMON.env(PG_STANDIN_DIR=str(d), RUN_ENV="local"), mock.patch.object(PGC, "has_conn", return_value=False):
        yield


def _rows(d, kind="skip"):
    cn = sqlite3.connect(Path(d) / "applog.sqlite")
    try:
        return {
            r[0]: r[1:]
            for r in cn.execute(
                "SELECT source_key, source_system, reason, level, count, first_seen, last_seen FROM except_doc_info WHERE except_type = ?",
                (kind,),
            )
        }
    finally:
        cn.close()


def _ext_size(d, kind="skip"):
    cn = sqlite3.connect(Path(d) / "applog.sqlite")
    try:
        return {
            r[0]: r[1:] for r in cn.execute("SELECT source_key, file_ext, file_size FROM except_doc_info WHERE except_type = ?", (kind,))
        }
    finally:
        cn.close()


def test_record_upsert():
    with tempfile.TemporaryDirectory() as d, standin(d):
        size = {k: s for k, s, _ in EXT_SIZE}
        rows = [
            {"source_key": k, "source_system": k.split("/", 1)[0], "file_name": n, "file_size": size.get(k), "reason": r}
            for k, n, r, _ in REASONS
        ]
        want = {k: w for k, _, _, w in REASONS if w}
        assert SD.record(rows) == len(want)
        got = _rows(d)
        assert {k: v[1] for k, v in got.items()} == want, got
        assert all(v[2] == "error" and v[3] == 1 for v in got.values()), got
        assert got["SFDC/a/x.zip"][0] == "SFDC" and got["CRMS/c/noext"][0] == "CRMS"
        sizes = _ext_size(d)
        assert {k: sizes[k] for k, _, _ in EXT_SIZE} == {k: w for k, _, w in EXT_SIZE}, sizes
        SD.record(rows[:1])  # 다시 봄 — 횟수만 늘고 처음 시각은 그대로
        again = _rows(d)["SFDC/a/x.zip"]
        assert again[3] == 2 and again[4] == got["SFDC/a/x.zip"][4], again
        assert SD.skipped_keys() == set(want)
        err = [{"source_key": "SFDC/d/d.pdf", "source_system": "SFDC", "file_name": "d.pdf", "reason": "load_failed"}]
        assert SD.record_error(err) == 1 and SD.record_error(err) == 1  # 실패 — skip 행과 따로(같은 키라도 종류가 다르면 다른 행)
        e = _rows(d, "error")["SFDC/d/d.pdf"]
        assert e[1] == "load_failed" and e[3] == 2, e
        assert SD.skipped_keys() == set(want) and _rows(d)["SFDC/d/d.pdf"][3] == 1  # error는 빼는 키가 아님 · skip 행은 그대로


def test_rdb_all_unsupported():
    """받기 전 거름(rdb_pick) — 모두 지원 안 함이면 받을 것 0건으로 끝나고(빈 _source_files) 문서마다 except_doc_info skip·extract.skip 행.
    원천 목록 밖 행은 고르지 않는다(기록도 없음)."""
    for systems, picked in RDB_SYSTEMS:
        _rdb_unsupported(systems, picked)


def _rdb_unsupported(systems, picked):
    with tempfile.TemporaryDirectory() as d, standin(Path(d) / "pg"):
        root = Path(d)
        csv_f = root / "batch.csv"
        csv_f.write_text(
            "id,s3_key,original_filename,file_size,source_system\n" + "".join(f"{i},{k},{n},3,dev-1\n" for i, k, n in RDB_ROWS),
            encoding="utf-8",
        )
        events = []
        with (
            pc.PIPE.env(RDB_BUCKET="b", SOURCE_STAGING=str(root / "staging"), SOURCE_SYSTEMS=systems),
            mock.patch.object(CP, "done_by_sha", lambda shas: {}),
            mock.patch("pipeline.shared.runtrace.skip_event", lambda name, reason, src=None, **m: events.append((name, reason, src))),
        ):
            _, left, _, only = CR.stage_batch(f"rdb:csv:{csv_f}", root / "out", root / "prepared", 0, _filter)
        assert left == [] and only.read_text(encoding="utf-8").split() == []
        want = [("a.zip", "unsupported_archive", "DEV-1"), ("b.7z", "unsupported_archive", "DEV-1")] if picked else []
        assert sorted(events) == want, (systems, events)
        got = {k: v[:2] + _ext_size(root / "pg")[k] for k, v in _rows(root / "pg").items()} if picked else {}
        want = {k: ("DEV-1", "unsupported_archive", Path(n).suffix[1:], 3) for _, k, n in RDB_ROWS}  # 크기 = 표의 file_size
        assert got == (want if picked else {}), (systems, got)


def _filter(args):
    with mock.patch.object(sys, "argv", ["filter_and_rotate", *map(str, args[1:])]):
        FR.main()
    return 0


def test_list_excludes_skipped():
    """대상 목록 --skip-done — except_doc_info skip 키를 빼서 --max-docs가 새 문서를 고름(error 키는 빼지 않음). --skip-done이 없으면 그대로."""
    fsm = [
        (1, "SFDC/a/rfp_drm.pdf", "rfp_drm.pdf", 10, "SFDC"),
        (2, "SFDC/b/rfp_new.pdf", "rfp_new.pdf", 20, "SFDC"),
        (3, "SFDC/c/rfp_z.pdf", "rfp_z.pdf", 30, "SFDC"),
    ]
    with tempfile.TemporaryDirectory() as d, standin(Path(d) / "pg"):
        edw = Path(d) / "edw.sqlite"
        cn = sqlite3.connect(edw)
        cn.execute("CREATE TABLE FileStorageMap (id INTEGER, s3_key TEXT, original_filename TEXT, file_size INTEGER, source_system TEXT)")
        cn.executemany("INSERT INTO FileStorageMap VALUES (?, ?, ?, ?, ?)", fsm)
        cn.commit()
        cn.close()
        SD.record([{"source_key": "SFDC/a/rfp_drm.pdf", "source_system": "SFDC", "file_name": "rfp_drm.pdf", "reason": "drm_fasoo"}])
        SD.record_error(
            [{"source_key": "SFDC/b/rfp_new.pdf", "source_system": "SFDC", "file_name": "rfp_new.pdf", "reason": "parse_failed"}]
        )
        out = Path(d) / "targets.json"
        (Path(d) / CP.RUN_SEEN).mkdir()  # 앞 실행이 받은 sha256 표지 — 목록을 새로 만들면 비움(pl-59)
        for args, want in ((["--skip-done", "--max-docs", "1"], ["SFDC/b/rfp_new.pdf"]), (["--max-docs", "1"], ["SFDC/a/rfp_drm.pdf"])):
            with COMMON.env(RDB_SQLITE=str(edw)):
                assert CP._list_cmd([*args, "--filter", "rfp", "--out", str(out)]) == 0
            assert [r["s3_key"] for r in json.loads(out.read_text(encoding="utf-8"))["docs"]] == want, args
            assert not (Path(d) / CP.RUN_SEEN).exists()


def test_old_standin_gets_new_columns():
    """판 0004 전에 만든 대역 파일(file_ext·file_size 칸 없음)도 그대로 씀 — 없는 칸을 더한다."""
    with tempfile.TemporaryDirectory() as d, standin(d):
        cn = sqlite3.connect(Path(d) / "applog.sqlite")
        cn.execute(
            "CREATE TABLE except_doc_info (source_key TEXT, except_type TEXT, source_system TEXT, file_name TEXT, reason TEXT, "
            "level TEXT, first_seen TEXT, last_seen TEXT, count INTEGER, PRIMARY KEY (source_key, except_type))"
        )
        cn.commit()
        cn.close()
        assert SD.record_error([{"source_key": "SFDC/a/a.PDF", "file_name": "a.PDF", "file_size": "4", "reason": "parse_failed"}]) == 1
        assert _ext_size(d, "error") == {"SFDC/a/a.PDF": ("pdf", 4)}
