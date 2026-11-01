"""common.core.sources 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m common.core.sources --selftest`."""

import json
from pathlib import Path

from common.core.sources import DEFAULT_FILE, enabled_sources, load_sources, sources_origin, sources_path


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    p = d / "sources.json"
    p.write_text(
        json.dumps(
            [
                {
                    "name": "FileStorageMap",
                    "table": "AI.FileStorageMap",
                    "bucket": "rag-src",
                    "enabled": True,
                    "columns": {"doc_id": "id", "key": "s3_key", "filename": "original_filename", "size": "file_size", "increment": "id"},
                },
                {
                    "name": "FileStorageMap_CRMS",
                    "table": "AI.FileStorageMap_CRMS",
                    "bucket": "rag-src",
                    "enabled": False,
                    "columns": {
                        "doc_id": "file_id",
                        "key": "object_path",
                        "filename": "file_name",
                        "size": "size_bytes",
                        "increment": "mod_seq",
                    },
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    srcs = load_sources(p)
    assert set(srcs) == {"FileStorageMap", "FileStorageMap_CRMS"}
    assert set(enabled_sources(p)) == {"FileStorageMap"}
    assert srcs["FileStorageMap"]["bucket"] == "rag-src"

    from common.config.settings import COMMON  # S7b — 시험이 env 대신 설정 객체를 덮어씀
    from common.core import paths

    keep_local = paths.LOCAL_RUN
    paths.LOCAL_RUN = True  # PC 길(이미지 selftest에서도 — S8b)
    with COMMON.env(SOURCES_FILE=str(p)):
        assert sources_path() == p
        assert set(load_sources()) == {"FileStorageMap", "FileStorageMap_CRMS"}  # PC 파일 칸이 기본값보다 우선

    assert load_sources(d / "없음.json") == {}  # 파일 없으면 빈 dict(레거시 그대로 동작)

    with COMMON.env(SOURCES_FILE=None):
        assert sources_path() == DEFAULT_FILE  # S8b — 서버 덮어쓰기($SERVER_ENV_DIR/sources.json) 없앰

    try:  # 사용자 11-01 — 서버 길도 같은 파일(판 표 없음)
        paths.LOCAL_RUN = False
        with COMMON.env(SOURCES_FILE=str(p)):
            assert set(enabled_sources()) == {"FileStorageMap"} and sources_origin() == str(p)
    finally:
        paths.LOCAL_RUN = keep_local

    p2 = d / "nobucket.json"
    p2.write_text(
        json.dumps(
            [
                {
                    "name": "NoBkt",
                    "table": "AI.NoBkt",
                    "columns": {"doc_id": "id", "key": "k", "filename": "f", "size": "s", "increment": "id"},
                }
            ]
        ),
        encoding="utf-8",
    )
    assert load_sources(p2)["NoBkt"]["bucket"] == ""  # bucket 생략 가능(서버마다 다르면 비워 둠 — env RDB_BUCKET·s3:// 접두로 대체)

    def _bad(entries, msg_part):
        bp = d / "bad.json"
        bp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        try:
            load_sources(bp)
            raise AssertionError(f"검증을 통과함(실패해야 함): {entries}")
        except ValueError as e:
            assert msg_part in str(e), e

    _bad([{"table": "AI.X", "bucket": "b", "columns": {}}], "name")  # name 없음
    _bad([{"name": "x", "table": "AI.X;DROP", "bucket": "b", "columns": {}}], "table")  # 식별자 아님
    _bad([{"name": "x", "table": "AI.X", "bucket": 1, "columns": {}}], "bucket")  # bucket이 문자열 아님
    _bad([{"name": "x", "table": "AI.X", "bucket": "b", "columns": {"doc_id": "id"}}], "필수 열 빠짐")  # 필수 열 부족
    _bad(
        [
            {
                "name": "x",
                "table": "AI.X",
                "bucket": "b",
                "columns": {"doc_id": "id", "key": "k", "filename": "f", "size": "s", "increment": "i", "oops": "y"},
            }
        ],
        "알 수 없는 키",
    )
    _bad(
        [
            {
                "name": "x",
                "table": "AI.X",
                "bucket": "b",
                "columns": {"doc_id": "id;x", "key": "k", "filename": "f", "size": "s", "increment": "i"},
            }
        ],
        "columns.doc_id",
    )
    _bad(
        [
            {
                "name": "x",
                "table": "AI.X",
                "bucket": "b",
                "enabled": True,
                "zzz": 1,
                "columns": {"doc_id": "id", "key": "k", "filename": "f", "size": "s", "increment": "i"},
            }
        ],
        "알 수 없는 키",
    )
    _bad(
        [
            {
                "name": "dup",
                "table": "AI.X",
                "bucket": "b",
                "columns": {"doc_id": "id", "key": "k", "filename": "f", "size": "s", "increment": "i"},
            },
            {
                "name": "dup",
                "table": "AI.Y",
                "bucket": "b",
                "columns": {"doc_id": "id", "key": "k", "filename": "f", "size": "s", "increment": "i"},
            },
        ],
        "name 중복",
    )
    print(
        "[selftest] SI41 — sources.json 로드·검증(필수 열·알 수 없는 키·식별자 화이트리스트·이름 중복)·"
        "enabled 필터·SOURCES_FILE(PC 파일)·서버 = 판 표 활성 판(S8b)·파일 없으면 빈 dict 통과"
    )


def test_main():  # 옛 `if __name__ == "__main__":` 의 --selftest 갈래
    selftest()
