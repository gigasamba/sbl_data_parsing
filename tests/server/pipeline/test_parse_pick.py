"""C10(pl-12 · pl-32, 사용자 10-31) — 새 문서 후보 = FileStorageMap ∖ ParsingMeta: ParsingMeta에 ok·partial(gold_version도 있음 — 사용자 11-02)·skipped_dup 행이(사용자 11-01) 있는 원본 키는 안 고르고,
행이 없거나(새 문서·통째 실패) 다른 상태(not_parsed·skipped_disk_cap 등)면 고른다. 이름 ↔ 원본 키는 manifest.jsonl(없으면 이름 그대로). 받은 순서 그대로.
EDW를 못 읽으면 서버(run_mode prod·RUN_ENV dev)는 종료 4, PC는 받은 목록 그대로. 임시 SQLite EDW 대역만 — 외부 접속 없음."""

import json
import tempfile
from pathlib import Path
from unittest import mock

from common.config.settings import COMMON
from common.store.parsing_meta_db import SqliteStore
from pipeline import cli

# (이름, manifest 원본 키 | None, ParsingMeta parse_status | None, 고름?)
DOCS = [
    ("z_ok.pdf", "SFDC/a/z_ok.pdf", "ok", False),  # 성공·gold에도 올림 — 안 고름
    ("nogold.pdf", "SFDC/a/nogold.pdf", "ok", True),  # silver만 있고 gold_version 없음(적재·분류 실패) — 다시 고름(사용자 11-02)
    ("part.pdf", "SFDC/a/part.pdf", "partial", False),  # 부분 성공도 끝난 것
    ("new.pdf", "SFDC/a/new.pdf", None, True),  # ParsingMeta에 없음(새 문서 또는 통째 실패) — 고름
    ("np.pdf", "SFDC/a/np.pdf", "not_parsed", True),  # 행은 있지만 성공 아님 — 고름
    ("dup.pdf", "SFDC/a/dup.pdf", "skipped_dup", False),  # 완전 중복 — 끝난 것(사용자 11-01)
    ("cap.pdf", "SFDC/a/cap.pdf", "skipped_disk_cap", True),  # 디스크 상한으로 건너뜀 — 다시 고름
    ("same.pdf", "SFDC/b/same.pdf", None, True),  # 같은 이름이 다른 키(SFDC/a/same.pdf)로 성공 — 키로 보므로 고름
    ("folder.pdf", None, "ok", False),  # manifest 없음(폴더 소스) — 이름이 곧 키
]
EXTRA_ROWS = [("SFDC/a/same.pdf", "ok")]
NO_GOLD = {"SFDC/a/nogold.pdf"}  # 나머지 ok·partial 행은 gold_version을 채움
# (RUN_ENV, RUN_MODE, EDW 대역 있음, 기대 — 이름 목록 또는 종료 코드)
CASES = [
    ("local", None, True, [n for n, _, _, pick in DOCS if pick]),
    ("local", "prod", True, [n for n, _, _, pick in DOCS if pick]),
    ("local", None, False, [n for n, *_ in DOCS]),  # PC — EDW 못 읽음: 받은 목록 그대로
    ("local", "prod", False, 4),  # run_mode prod — 멈춤
    ("dev", None, True, 4),  # 서버 — 대역은 거부되고(RDB_SQLITE는 PC 전용) 멈춤
]


def _fixture(tmp):
    out = Path(tmp) / "out"
    (out / "parse" / "_source").mkdir(parents=True)
    (out / "parse" / "_source" / "manifest.jsonl").write_text(
        "".join(json.dumps({"file_name": n, "key": k}) + "\n" for n, k, _, _ in DOCS if k), encoding="utf-8"
    )
    edw = Path(tmp) / "edw.sqlite"
    rows = [(k or n, st) for n, k, st, _ in DOCS if st] + EXTRA_ROWS
    db = SqliteStore(str(edw))
    db.insert_new([{"source_system": "SFDC", "source_key": k, "doc_key": f"d{i}", "parse_status": st} for i, (k, st) in enumerate(rows)])
    db.cn.executemany("UPDATE ParsingMeta SET gold_version = '0.2.0' WHERE source_key = ?", [(k,) for k, _ in rows if k not in NO_GOLD])
    db.cn.commit()
    db.close()
    return out, edw


def test_c10_pick():
    names = [n for n, *_ in DOCS]
    with tempfile.TemporaryDirectory() as tmp:
        out, edw = _fixture(tmp)
        for run_env, mode, has_edw, want in CASES:
            path = str(edw if has_edw else Path(tmp) / "none" / "edw.sqlite")
            with COMMON.env(RUN_ENV=run_env, RUN_MODE=mode, RDB_SQLITE=path), mock.patch.object(cli, "OUT", out):
                try:
                    got = cli._unparsed(names)
                except SystemExit as e:
                    got = e.code
            assert got == want, (run_env, mode, has_edw, got)
