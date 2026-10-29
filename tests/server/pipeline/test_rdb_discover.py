"""pipeline.extract.rdb_discover 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.rdb_discover --selftest`."""

from pathlib import Path

from common.core.sources import TABLE_ID_RE
from pipeline.extract.rdb_discover import REQUIRED_COLUMNS, _from_csv, column_problems


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    csv_path = d / "FileStorageMap.csv"
    csv_path.write_text("id,content_version_id,s3_key,original_filename,file_size\n1,1,a,a.pdf,4\n", encoding="utf-8")
    drafts = _from_csv(csv_path, "AI.FileStorageMap")
    assert len(drafts) == 1, drafts
    d0 = drafts[0]
    assert d0["name"] == "FileStorageMap" and d0["table"] == "AI.FileStorageMap" and d0["enabled"] is False and d0["bucket"] == ""
    assert d0["columns"] == {"doc_id": "id", "key": "s3_key", "filename": "original_filename", "size": "file_size", "increment": "id"}, d0[
        "columns"
    ]
    assert "_missing_columns" not in d0, d0  # 필수 열 전부 맞춰짐
    body = [{**d0, "table": f"csv:{csv_path}"}]  # S8b — set-sources --check-columns(csv 표)
    assert column_problems(body) == [], column_problems(body)
    bad = [
        {**d0, "table": f"csv:{csv_path}", "columns": {**d0["columns"], "size": "no_such_col"}},
        {**d0, "name": "x", "table": f"csv:{d / 'none.csv'}"},
    ]
    probs = column_problems(bad)
    assert len(probs) == 2 and "size=no_such_col" in probs[0] and "없음" in probs[1], probs

    csv2 = d / "FileStorageMap_CRMS.csv"
    csv2.write_text("file_id,object_path,file_name,size_bytes,mod_seq\nR-1,a,a.pdf,4,1\n", encoding="utf-8")
    d1 = _from_csv(csv2, "AI.FileStorageMap_CRMS")[0]
    assert d1["columns"] == {
        "doc_id": "file_id",
        "key": "object_path",
        "filename": "file_name",
        "size": "size_bytes",
        "increment": "mod_seq",
    }, d1["columns"]

    csv3 = d / "Weird.csv"
    csv3.write_text("foo,bar\n1,2\n", encoding="utf-8")  # 이름 규칙에 하나도 안 걸림 — 필수 열 전부 빠짐
    d2 = _from_csv(csv3, "AI.Weird")[0]
    assert sorted(d2["_missing_columns"]) == sorted(REQUIRED_COLUMNS), d2

    assert TABLE_ID_RE.match("AI.FileStorageMap")  # 식별자 화이트리스트 재사용 확인(공용 1곳)
    print(
        "[selftest] SI41 — rdb_discover: 이름 규칙 매핑(실 EDW 열 이름·CRMS 다른 이름)·필수 열 못 맞추면 "
        "_missing_columns·bucket/enabled는 늘 빈 값/false 통과"
    )


def test_main():  # 옛 `if a.selftest:` 갈래(main() 안)
    selftest()
