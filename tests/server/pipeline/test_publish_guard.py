"""publish source.json 방어선 시험 — S9b(refactor.md C-54 ②, 사용자 10-28 — 기록만)에 test_publish_parse에서 뺀 단언. **알려진 FAIL**(deploy/release/known_fail.txt).
서버 사본이 source.json을 안 올려(pre-refactor parsing_meta.py — "source.json 업로드 생략 — 내부용") `apply()`의 sidecar 대조(독립 검토 BLOCK 10-09)가
늘 sidecar를 못 찾음 → 같은 문서를 다시 publish하면 매번 다시 올리고(skip_exists 0), 서로 다른 원본이 같은 결과 키로 접혀도 거부(error_key_collision)되지 않음.
서버가 source.json 올리기를 되살리면 통과 — 그때 known_fail에서 지운다(문서 대장 갱신 C-54 ①은 C10 10-31에 문서 대장째 지움).
S10(VS9b R-4): 문서 대장이 SQLite로 대체될 때(PG 없음 — 이미지·PG 꺼진 PC) 개발자 기본 대장이 아닌 시험 폴더 STRUCT_DB에 쓰게."""

from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.load.publish_parse_result import run
from tests.server.pipeline.test_publish_parse import make_fixture


def test_sidecar_guard():  # 옛 test_publish_parse의 r2·r3 업로드 단언(+ 그 전제 source.json)
    d, out, a = make_fixture()
    os_dir, db_path = d / "os", d / "edw.sqlite"
    with pc.PIPE.env(PM_BUCKET=f"file://{os_dir}"), COMMON.env(RDB_SQLITE=str(db_path), STRUCT_DB=str(d / "struct.sqlite")):
        a.apply = True
        run(a)
        folder = next(os_dir.rglob("a_2026-10-08.md")).parent
        assert (folder / "source.json").exists(), "source.json을 안 올림 — sidecar 방어선이 꺼짐(C-54 ②)"
        r2 = run(a)  # 같은 걸 재실행 — a는 업로드도 skip_exists
        assert r2["result"]["uploaded"] == 0 and r2["result"]["skip_exists"] == 1, r2
        a.version = "v2"  # 판이 달라도 KEY(출처+원본 키)가 같으면 그대로 건너뜀
        r3 = run(a)
        assert r3["result"]["uploaded"] == 0 and r3["result"]["inserted"] == 0, r3
