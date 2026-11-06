"""C10(pl-12 · pl-32 · op-17) — 새 문서 후보 = FileStorageMap ∖ gold doc: 원천 스키마 어디든 gold `doc` 행이 있는 원본 키는 안 고르고,
없으면(새 문서·파싱·적재 실패) 고른다. 이름 ↔ 원본 키는 manifest.jsonl(없으면 이름 그대로). 받은 순서 그대로.
gold를 못 읽으면 서버(RUN_ENV dev)는 종료 4, PC는 받은 목록 그대로. PC gold 대역(임시 폴더)만 — 외부 접속 없음."""

import json
import tempfile
from pathlib import Path

from common.config.settings import COMMON
from pipeline.extract import candidate_pick
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
# (RUN_ENV, gold 대역 있음, 기대 — 이름 목록 또는 종료 코드)
CASES = [
    ("local", True, [n for n, _, _, pick in DOCS if pick]),
    ("local", False, [n for n, *_ in DOCS]),  # PC — gold 표 없음: 받은 목록 그대로
    ("dev", True, 4),  # 서버 — 대역은 거부되고 멈춤
]


def _fixture(tmp):
    out = Path(tmp) / "out"
    (out / "parse" / "_source").mkdir(parents=True)
    (out / "parse" / "_source" / "manifest.jsonl").write_text(
        "".join(json.dumps({"file_name": n, "key": k}) + "\n" for n, k, _, _ in DOCS if k), encoding="utf-8"
    )
    with COMMON.env(RUN_ENV="local", PG_STANDIN_DIR=str(Path(tmp) / "pg")):
        seed([{"file_path": k or n, "parse_status": "partial" if n == "part.pdf" else "ok"} for n, k, g, _ in DOCS if g])
        seed([{"file_path": k} for k in EXTRA_GOLD])
    return out


def test_c10_pick():
    names = [n for n, *_ in DOCS]
    with tempfile.TemporaryDirectory() as tmp:
        out = _fixture(tmp)
        for run_env, has_gold, want in CASES:
            pg = Path(tmp) / ("pg" if has_gold else "none")
            with COMMON.env(RUN_ENV=run_env, PG_STANDIN_DIR=str(pg)):
                try:
                    got = candidate_pick.unparsed(names, out)
                except SystemExit as e:
                    got = e.code
            assert got == want, (run_env, has_gold, got)
