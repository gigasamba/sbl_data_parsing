"""mcp_server.services.edw_meta 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.edw_meta`."""

import tempfile

from mcp_server import config as mc
from mcp_server.services.edw_meta import _STATE, NotConfigured, lookup

# ── selftest (EQ1 관례: 데이터 파일이 없는 환경에서도 임베디드 fixture로만 통과) ──

_DEMO_CATALOG = """{
  "meta": {"as_of": "2026-10-21",
           "schemas": {"AI": {"system": "AI/ML 처리 메타데이터", "tables": 2, "columns_available_tables": 1, "columns": 2},
                       "BSCM": {"system": "Biologics Supply Chain Management (생산계획)", "tables": 1, "columns_available_tables": 1, "columns": 1}},
           "excluded": {"BCMS": "EDW 조회 계정에 SELECT 권한 없음"}},
  "tables": [
    {"schema": "AI", "table": "ParsingMeta", "qualified_name": "[AI].[ParsingMeta]",
     "table_desc_ko": "파싱 결과 메타", "source_system": "AI", "row_count": 5, "data_period": null,
     "volume": "0.01 MB", "data_shape": "정형", "data_character": "메타데이터", "column_count": 2, "columns_available": true},
    {"schema": "AI", "table": "FileStorageMap_LAS", "qualified_name": "[AI].[FileStorageMap_LAS]",
     "table_desc_ko": "LAS 파일 경로 매핑", "source_system": "AI", "row_count": 2, "data_period": null,
     "volume": "0.01 MB", "data_shape": "정형", "data_character": "메타데이터", "column_count": null, "columns_available": false},
    {"schema": "BSCM", "table": "MST_STOCK_MGT", "qualified_name": "[BSCM].[MST_STOCK_MGT ]",
     "table_desc_ko": "재고 관리 마스터", "source_system": "BSCM", "row_count": 10, "data_period": "2026-01-01 ~ 2026-10-01",
     "volume": "1.00 MB", "data_shape": "정형", "data_character": "", "column_count": 1, "columns_available": true}
  ]
}"""
_DEMO_COLUMNS = (
    '{"schema":"AI","table":"ParsingMeta","ordinal_position":1,"column_name":"SRN","data_type":"nvarchar(400)",'
    '"nullable":false,"primary_key":true,"foreign_key":false,"fk_reference":null,"description_ko":'
    '"SRN(고유 요청 번호)","domain_tags":["identifier"],"sample_values":["PWC-0001"],"samples_suspect":false}\n'
    '{"schema":"AI","table":"ParsingMeta","ordinal_position":2,"column_name":"FILE_NM","data_type":"nvarchar(500)",'
    '"nullable":true,"primary_key":false,"foreign_key":false,"fk_reference":null,"description_ko":"파일명",'
    '"domain_tags":["identifier"],"sample_values":["a.pdf"],"samples_suspect":false}\n'
    '{"schema":"BSCM","table":"MST_STOCK_MGT","ordinal_position":1,"column_name":"STOCK_QTY","data_type":"numeric(18,0)",'
    '"nullable":false,"primary_key":true,"foreign_key":false,"fk_reference":null,"description_ko":'
    '"재고 수량","domain_tags":["quantity"],"sample_values":["5"],"samples_suspect":false}\n'
)


def _demo():
    tmp = tempfile.mkdtemp(prefix="edw_meta_demo_")
    _env = None  # EDW_META_DIR 덮기(S7d — mc.senv, finally에서 닫음)
    try:
        from pathlib import Path as _P

        (_P(tmp) / "catalog.json").write_text(_DEMO_CATALOG, encoding="utf-8")
        (_P(tmp) / "columns.jsonl").write_text(_DEMO_COLUMNS, encoding="utf-8")
        _env = mc.senv(EDW_META_DIR=tmp)
        _STATE.pop("d", None)

        r = lookup()  # ① 스키마 요약
        assert r["kind"] == "schemas" and len(r["schemas"]) == 2 and r["excluded"]["BCMS"], r
        assert r["schemas"][0]["schema"] == "AI" and r["schemas"][0]["tables_with_columns"] == 1

        r = lookup(schema="bscm")  # ② 스키마의 전체 테이블(컬럼 제외) — 소문자 인자 허용
        assert r["kind"] == "tables" and r["schema"] == "BSCM" and r["table_count"] == 1, r
        assert "columns" not in r["tables"][0]

        r = lookup(schema="BSCM", table="mst_stock_mgt ")  # 후행 공백 허용(EDW 실제 이름 재현)
        assert r["kind"] == "table" and r["qualified_name"] == "[BSCM].[MST_STOCK_MGT ]", r
        assert r["column_total"] == 1 and r["columns"][0]["key"] == "PK"
        assert "sample_values" not in r["columns"][0]  # 미표시 방침(§3.4) — 어떤 컬럼 row에도 샘플 없음

        r = lookup(schema="AI", table="FileStorageMap_LAS")  # ③ gap 테이블 — 인벤토리만
        assert r["columns_available"] is False and r["columns"] == [] and r["notes"], r

        r = lookup(table="ParsingMeta")  # schema 생략 — 유일하면 그대로 조회
        assert r["kind"] == "table" and r["table"] == "ParsingMeta" and r["column_total"] == 2, r
        assert r["columns"][0]["nullable"] is False and r["columns"][0]["desc_ko"] == "SRN(고유 요청 번호)"

        r = lookup(table="ParsingMeta", column_filter="file")  # 대소문자 무시 컬럼 좁히기
        assert [c["column"] for c in r["columns"]] == ["FILE_NM"] and r["column_filter"] == "file", r

        r = lookup(schema="AI", table="parsing_meta")  # 유사명 — 오타 제안(difflib)
        assert r["error"].startswith("테이블 없음") and r["suggestions"] == ["AI.ParsingMeta"], r

        r = lookup(schema="A1")  # 없는 스키마 — 유사명 제안(difflib)
        assert "스키마 없음" in r["error"] and r["suggestions"] == ["AI"], r

        r = lookup(column_filter="SRN")  # column_filter 단독 — 안내 오류
        assert "column_filter는 schema+table" in r["error"], r

        _env.close()
        _env = mc.senv(EDW_META_DIR=tempfile.mkdtemp(prefix="edw_meta_empty_"))  # 빈 디렉터리 → fail-soft
        _STATE.pop("d", None)
        try:
            lookup()
            raise SystemExit("NotConfigured가 나와야 한다")
        except NotConfigured:
            pass
        print("[selftest] edw_meta — 3단 계층·정규화·제안·미표시·fail-soft OK")
    finally:
        if _env is not None:
            _env.close()
        _STATE.pop("d", None)  # 데모 상태가 실 서버 상태를 오염시키지 않게


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _demo()
