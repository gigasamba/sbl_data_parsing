"""pipeline.load.pgvector_load 시험."""

import pipeline.load.pgvector_load as M
from pipeline.load.pgvector_load import _OUR_TABLES, _tbl, deploy, load


class _FakeCur:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sink.append(sql)


class _FakeDB:
    """가짜 커서/연결 — 실제 PG 없이 deploy()·load()의 가드 분기만 확인(XS3)."""

    def __init__(self, schema, has_vector, has_marker, schema_exists=False, has_other_tables=False, create_ext_outcome="install"):
        self.schema, self.has_vector, self.has_marker = schema, has_vector, has_marker
        self.schema_exists = schema_exists or has_marker or has_other_tables
        self.has_other_tables = has_other_tables or has_marker
        self.create_ext_outcome = create_ext_outcome  # "install"(성공) · "fail"(권한 없음 등)
        self.executed, self.q_calls = [], []
        self.cn = self

    def cursor(self):
        return _FakeCur(self.executed)

    def q(self, sql, params=None):
        self.q_calls.append(sql)
        low = sql.lower()
        if "create extension" in low:
            if self.create_ext_outcome == "fail":
                raise RuntimeError('permission denied to create extension "vector"')
            self.has_vector = True
            return []
        if "pg_extension" in low and "vector" in low:
            return [{"x": 1}] if self.has_vector else []
        if "information_schema.schemata" in low:
            return [{"x": 1}] if self.schema_exists else []
        if "information_schema.tables" in low and "alembic_version" in sql:
            return [{"x": 1}] if self.has_marker else []
        if "information_schema.tables" in low:
            return [{"x": 1}] if self.has_other_tables else []
        return []


def _n_create_ext(db):
    return sum(1 for q in db.q_calls if "create extension" in q.lower())


def _selftest():
    """실제 PG 없이 가짜 커서/연결로(XS3): 확장 없음 → deploy 멈춤(기본, CREATE EXTENSION 미호출) · --create-extension 옵트인(성공·실패) ·
    표식 없는 스키마에 --replace 거부 · 우리 스키마면 허용 · deploy 자체의 남의 스키마 거부(표 있음·표식 없음) · 표 화이트리스트.
    S8a — 판 올리기(_upgrade — migrate up)는 가짜로 바꿔 부른 것만 본다(실 PG 비교·pg_dump 대조는 output/orca/S8a-impl.md 하네스)."""
    # S9 — 옛 `global _upgrade` → `M.<이름>`(모듈 전역 대입)
    real, ups = M._upgrade, []
    M._upgrade = lambda schema, dim: ups.append((schema, dim))
    try:
        _selftest_deploy(ups)
    finally:
        M._upgrade = real


def _selftest_deploy(ups):
    db1 = _FakeDB("ai", has_vector=False, has_marker=False)
    try:
        deploy(db1, 768)
        raise AssertionError("확장 없이 deploy가 멈추지 않음")
    except SystemExit as e:
        assert "관리자 설치" in str(e), str(e)
    assert not ups and _n_create_ext(db1) == 0, "확장 없을 때 판 올리기·CREATE EXTENSION 실행 흔적"

    db2 = _FakeDB("ai", has_vector=True, has_marker=False)
    idx = deploy(db2, 768)
    assert ups == [("ai", 768)] and _n_create_ext(db2) == 0  # 확장 있음 — 판 올리기만(S8a — 옛 schema.sql 실행 자리)
    assert idx == "HNSW 코사인", idx

    db3 = _FakeDB("ai", has_vector=True, has_marker=False)  # 확장은 있지만 표식(판 표 alembic_version) 없는 기존 스키마
    try:
        load(db3, "no-such-bundle", replace=True)
        raise AssertionError("표식 없는 스키마에서 --replace가 거부되지 않음")
    except SystemExit as e:
        assert "표식" in str(e), str(e)

    db4 = _FakeDB("ai", has_vector=True, has_marker=True)  # 우리가 만든 스키마(판 표 있음)
    try:
        load(db4, "no-such-bundle", replace=True)
        raise AssertionError("번들이 없는데 통과함")
    except SystemExit as err:
        raise AssertionError("표식 있는 우리 스키마인데 --replace가 거부됨") from err
    except FileNotFoundError:
        pass  # 표식 검사는 통과 — 그다음 번들 파일이 없어 실패(가드가 아니라 입력 문제)

    try:
        _tbl("ai", "pg_user")
        raise AssertionError("화이트리스트 밖 표가 통과함")
    except SystemExit:
        pass

    # 옵트인 없음 — 확장 없으면 CREATE EXTENSION 없이 멈춤
    db5 = _FakeDB("ai", has_vector=False, has_marker=False)
    try:
        deploy(db5, 768)
        raise AssertionError("옵트인 꺼짐인데 확장 없이 deploy가 멈추지 않음")
    except SystemExit:
        pass
    assert _n_create_ext(db5) == 0, "옵트인 꺼짐인데 CREATE EXTENSION 호출됨"
    assert len(ups) == 1, "확장 없음 거부인데 판 올리기가 돎(확인이 판 올리기보다 먼저 — S8a)"

    # 직접 생성 옵트인(dbtool up --create-extension) — 켜면 성공·실패 각각
    from common.store.db import dbtool

    db6 = _FakeDB("ai", has_vector=False, has_marker=False, create_ext_outcome="install")
    dbtool.precheck_search(db6.q, "ai", 768, True)
    assert _n_create_ext(db6) == 1, "옵트인 켜짐인데 CREATE EXTENSION 호출 안 됨"

    db7 = _FakeDB("ai", has_vector=False, has_marker=False, create_ext_outcome="fail")
    try:
        dbtool.precheck_search(db7.q, "ai", 768, True)
        raise AssertionError("확장 설치 실패인데 멈추지 않음")
    except SystemExit as e:
        assert "설치 실패" in str(e) or "관리자 설치" in str(e), str(e)
    assert _n_create_ext(db7) == 1 and len(ups) == 1

    # deploy 자체의 남의 스키마 거부(보강 3) — 표가 있고 표식 없으면 거부, 빈 스키마·표식 있는 스키마는 통과
    db8 = _FakeDB("ai", has_vector=True, has_marker=False, schema_exists=True, has_other_tables=True)
    try:
        deploy(db8, 768)
        raise AssertionError("표 있고 표식 없는 남의 스키마인데 deploy가 거부되지 않음")
    except SystemExit as e:
        assert "남의 기존 스키마" in str(e), str(e)
    assert len(ups) == 1, "남의 스키마 거부인데 판 올리기가 돎"

    db9 = _FakeDB("ai", has_vector=True, has_marker=False, schema_exists=True, has_other_tables=False)  # 있지만 빈 스키마
    idx9 = deploy(db9, 768)
    assert idx9 == "HNSW 코사인"

    db10 = _FakeDB("ai", has_vector=True, has_marker=True, schema_exists=True, has_other_tables=True)  # 우리가 만든 스키마(재배포)
    n = len(ups)
    idx10 = deploy(db10, 768)
    assert idx10.startswith("HNSW 코사인(확인 안 함"), idx10
    assert len(ups) == n, "판 기록 없는 기존 스키마인데 deploy가 판 올리기를 돎(경고 뒤 계속이어야 — S8a Q5·코디네이터 10-28 a)"

    print(
        "[selftest] pgstore — 확장 없음 멈춤(기본)·--create-extension 옵트인(성공·실패)·표식 없는 스키마 --replace 거부·"
        "deploy 자체 남의 스키마 거부·우리 스키마 허용·표 화이트리스트 통과"
    )

    assert not ({"kg_node", "doc_fact", "doc_image"} & _OUR_TABLES)  # 2026-10-20 축소 — 삭제된 표가 화이트리스트에 없는지


def test_main():  # 옛 main()의 `if "--selftest" in args:` 갈래
    _selftest()


def test_require_vectors():
    """pl-16 — 임베딩 없는 묶음은 적재·배포 시작 거부(종료 코드 2 — 글자 메시지), 벡터가 있으면 통과."""
    from pipeline.load.pgvector_load import require_vectors

    cases = [  # (meta, 거부?)
        ({"dim": 0, "embed": "none"}, True),
        ({"dim": 1024, "embed": "none"}, True),
        ({"embed": "api", "chunks": 3}, True),  # 청크는 있는데 dim 없음
        ({"embed": "api", "dim": 0, "chunks": 0}, False),  # 청크 0건 문서(빈·스캔만) — 문서 행만 적재(run_pipeline 문서별 흐름)
        ({"dim": 1024, "embed": "api"}, False),
        ({"dim": 4, "embed_model": "test"}, False),  # 옛 묶음(embed 칸 없음)
    ]
    for meta, refused in cases:
        try:
            require_vectors(meta)
            got = False
        except SystemExit as e:
            got = True
            assert e.code == 2, e.code
        assert got == refused, (meta, got)


def test_embed_guard():
    """pl-51 — 묶음 임베딩 모델이 검색 스키마의 기존 문서 모델과 다르면 적재 거부(종료 2 · 아무것도 안 씀 · pipe_event 한 행).
    SQLite 대역 · 임시 폴더만(외부 접속 없음). 첫 적재는 모델 m-A로 문서 a."""
    import json
    import shutil
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from common.config.settings import COMMON
    from common.store import logsink
    from common.store import pg_standin as PS
    from common.store.db.dbtool import standin_script
    from tests.server.pipeline.test_pl13_no_prune import DIM, _bundle

    def bundle(path, model, tmp):
        d = _bundle([path], tmp)
        (d / "meta.json").write_text(json.dumps({"dim": DIM, "embed": "api", "embed_model": model}), encoding="utf-8")
        return d

    cases = [  # (경우, 묶음 모델, 거부?)
        ("같은 모델 — 적재", "m-A", False),
        ("같은 모델 다른 표기(openai/ 앞붙이) — 적재", "openai/m-A", False),
        ("다른 모델 — 거부", "m-B", True),
    ]
    S, tmp = "orca_pl51_t", Path(tempfile.mkdtemp())
    try:
        with COMMON.env(PG_STANDIN_DIR=str(tmp / "pg")):
            db, sf = PS.StandinPG(S), PS.StandinPG(f"{S}_sfdc")
            with sf.cn.cursor() as cur:
                cur.execute(standin_script(f"{S}_sfdc", DIM))
            M.load(db, bundle("SFDC/u/a.txt", "m-A", tmp))
            for i, (case, model, refused) in enumerate(cases):
                path = f"SFDC/u/n{i}.txt"
                with patch.object(logsink, "emit") as emit:
                    try:
                        M.load(db, bundle(path, model, tmp))
                        got = False
                    except SystemExit as e:
                        got = True
                        assert e.code == 2, (case, e.code)
                there = bool(sf.q(f"SELECT 1 AS o FROM {S}_sfdc.doc WHERE file_path = %s", (path,)))
                assert got == refused and there != refused, (case, got, there)
                assert emit.call_count == int(refused), (case, emit.call_args_list)
                if refused:
                    table, row = emit.call_args.args
                    assert table == "pipe_event" and row["status"] == "fail" and row["err_kind"] == "env", row
                    assert "embed_model_mismatch" in row["err"] and "m-A" in row["err"] and "m-B" in row["err"], row
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
