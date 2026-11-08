"""C10(pl-12 · pl-32 · op-17) — 새 문서 후보 = FileStorageMap ∖ gold doc: 원천 스키마 어디든 gold `doc` 행이 있는 원본 키는 안 고르고,
없으면(새 문서·파싱·적재 실패) 고른다. 이름 ↔ 원본 키는 manifest.jsonl(없으면 이름 그대로). 받은 순서 그대로.
gold를 못 읽으면 서버(RUN_ENV dev)는 종료 4, PC는 받은 목록 그대로. gold는 실 pgvector의 임시 스키마(tests/server/common/pgcase — test_*, 시험 뒤 지움)."""

import json
import tempfile
from pathlib import Path

from common.config.settings import COMMON
from pipeline.extract import candidate_pick
from tests.server.common import pgcase
from tests.server.pipeline.goldseed import seed

# (이름, manifest 원본 키 | None, gold doc 행 있음, 고름?)
DOCS = [
    ("z_ok.pdf", "SFDC/a/z_ok.pdf", True, False),  # gold에 있음 — 안 고름
    ("part.pdf", "SFDC/a/part.pdf", True, False),  # 부분 성공(parse_status partial)도 gold에 있으면 끝난 것
    ("new.pdf", "SFDC/a/new.pdf", False, True),  # gold에 없음(새 문서 또는 실패) — 고름
    ("same.pdf", "SFDC/b/same.pdf", False, True),  # 같은 이름이 다른 키(SFDC/a/same.pdf)로 gold에 있음 — 키로 보므로 고름
    ("folder.pdf", None, True, False),  # manifest 없음(폴더 소스) — 이름이 곧 키
]
EXTRA_GOLD = ["SFDC/a/same.pdf"]
# (RUN_ENV, gold — seeded 행 있음 · empty 표 없는 스키마 · down PG에 못 붙음, 기대 — 이름 목록 또는 종료 코드)
CASES = [
    ("local", "seeded", [n for n, _, _, pick in DOCS if pick]),
    ("local", "empty", [n for n, *_ in DOCS]),  # gold 표 없음: 받은 목록 그대로
    ("local", "down", [n for n, *_ in DOCS]),  # PC — gold를 못 읽음: 받은 목록 그대로
    ("dev", "seeded", [n for n, _, _, pick in DOCS if pick]),
    ("dev", "down", 4),  # 서버 — gold를 못 읽으면 멈춤(전체 재파싱 안 함)
]
DOWN = {"PG_HOST": "127.0.0.1", "PG_PORT": "1", "PG_CONNECT_TIMEOUT": "1"}  # 닫힌 포트 — 바로 접속 거부


def _fixture(tmp):
    out = Path(tmp) / "out"
    (out / "parse" / "_source").mkdir(parents=True)
    (out / "parse" / "_source" / "manifest.jsonl").write_text(
        "".join(json.dumps({"file_name": n, "key": k}) + "\n" for n, k, _, _ in DOCS if k), encoding="utf-8"
    )
    with COMMON.env(RUN_ENV="local"):
        seed([{"file_path": k or n, "parse_status": "partial" if n == "part.pdf" else "ok"} for n, k, g, _ in DOCS if g])
        seed([{"file_path": k} for k in EXTRA_GOLD])
    return out


def test_c10_pick():
    names = [n for n, *_ in DOCS]
    with tempfile.TemporaryDirectory() as tmp, pgcase.schema() as gold:
        out = _fixture(tmp)
        empty = pgcase.new_name()  # 만들지 않은 스키마 — 표 없음
        for run_env, kind, want in CASES:
            names_ = {"seeded": {"PG_SCHEMA": gold}, "empty": {"PG_SCHEMA": empty}, "down": DOWN}[kind]
            with COMMON.env(RUN_ENV=run_env, **names_):
                try:
                    got = candidate_pick.unparsed(names, out)
                except SystemExit as e:
                    got = e.code
            assert got == want, (run_env, kind, got)
