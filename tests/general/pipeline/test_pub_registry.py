"""publish 문서 대장 갱신 시험 — S9b(refactor.md C-54 ①, 사용자 10-28 — 이번 판에서 안 고침). **알려진 FAIL**(일반 시험 — tests/conftest.py GENERAL_KNOWN_FAIL).
문서 대장(PG)이 있어야 판정되므로 일반 시험(PC 전용)에 둔다 — 이미지 안에는 PG가 없어 늘 "사용 안 함"으로 통과해 반입 판정에 뜻이 없음(S9b 리뷰).
PG 백엔드에서 doc_registry upsert(여러 줄 `INSERT OR REPLACE`)가 `structdb._pg_sql`에서 번역되지 않아 "문서 대장 갱신 실패 — SyntaxError" →
changed의 EDW status UPDATE·registry/report.md가 늘 건너뜀. pl-12(사용자 10-30)부터 deleted·자동 숨김 길은 없음(문서 대장·EDW 모두 deleted를 쓰지 않음) —
번역을 고치면(pl-12 ①) 통과할 것이고 그때 known_fail에서 지운다. 고친 뒤 PC에서 돌면 설정의 PG(전용 PG `rag` DB의 struct 스키마)에 대장 행을 쓴다 — 시험 DB로 가른다.
S10(VS9b R-4): PG가 꺼져 있으면 SQLite 대체로 upsert가 성공해 헛되이 통과(XPASS)하고 개발자 기본 SQLite 대장에 쓰던 것 — RUN_MODE=prod로
대체를 막고("사용 안 함"이면 실패 — PG 없이는 판정 못 함) STRUCT_DB는 시험 폴더로."""

from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.load.publish_parse_result import run
from tests.server.pipeline.test_publish_parse import make_fixture


def test_registry_update():  # publish --apply의 문서 대장 갱신이 실패하지 않아야 함
    d, out, a = make_fixture()
    with (
        pc.PIPE.env(PM_BUCKET=f"file://{d / 'os'}"),
        COMMON.env(RDB_SQLITE=str(d / "edw.sqlite"), RUN_MODE="prod", STRUCT_DB=str(d / "struct.sqlite")),
    ):
        a.apply = True
        note = (run(a).get("registry_status_update") or {}).get("note") or ""
    assert "사용 안 함" not in note, f"문서 대장을 못 엶 — PG가 있어야 판정(R-4): {note}"
    assert "갱신 실패" not in note, f"문서 대장 갱신 실패(C-54 ①): {note.splitlines()[0] if note else ''}"
    print(f"[시험] 문서 대장: {note or '갱신됨'}")
