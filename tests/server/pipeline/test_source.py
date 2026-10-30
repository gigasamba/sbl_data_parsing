"""pipeline.extract.source 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.extract.source --selftest`."""

import contextlib
import csv
import json
from contextlib import contextmanager
from pathlib import Path

import pipeline.extract.source as M
from common.config.settings import COMMON
from common.core.contract import jl
from pipeline import config as pc
from pipeline.extract.source import (
    ROOT,
    TABLE_ID_RE,
    _mssql_rows,
    _rdb_cols,
    _safe_join,
    _safe_name,
    finish,
    mark_done,
    plan,
    resolve,
    sample,
)
from tests.server.common.test_mssql import (
    FakeConnection,
)  # S9 — 옛 `mssql.FakeConnection`(그룹 A가 common.store.mssql에서 시험 파일로 옮김)


def selftest():
    names = [f"d{i}.pdf" for i in range(40)] + [f"x{i}.docx" for i in range(20)] + ["a.png"]
    with pc.PIPE.env(
        TEST_MIN_DOCS=None, TEST_PER_TYPE=None
    ):  # S7c — sample()이 설정 객체로 읽으므로 env 대신 객체를 덮어씀(os.environ은 안 바뀜)
        s = sample(names, "test")
        assert len(s) == 11 and sum(n.endswith(".pdf") for n in s) == 5 and "a.png" in s and sample(names, "test") == s
        assert sample(names, "prod") == sorted(names) and sample(names[:10], "test") == sorted(names[:10])  # 50건 미만이면 전부
    print("[selftest] 시험 모드 표본(형식별·늘 같은 표본·50건 미만은 전부) 통과")

    import tempfile

    src = Path(tempfile.mkdtemp())
    for n in ("a.txt", "b.txt"):
        (src / n).write_text(n, encoding="utf-8")
    out = Path(tempfile.mkdtemp())
    plan_names, fetch_one, state = plan(str(src), out, mode="prod")
    assert plan_names == ["a.txt", "b.txt"] and (src / "a.txt").exists()  # 폴더 원본은 그대로(목록만)
    dest = Path(tempfile.mkdtemp())
    got = fetch_one("a.txt", dest)
    assert got.read_text(encoding="utf-8") == "a.txt" and (src / "a.txt").exists()  # 복사 — 원본 저장소는 안 지움
    mark_done(state, plan_names, is_s3=False)
    assert not (state / "processed.jsonl").exists()  # 폴더는 추적할 상태가 없음(s3일 때만 기록)
    print("[selftest] X2 스트리밍 — plan(폴더)이 이름만 정하고 fetch_one이 복사 · mark_done은 s3에만 통과")

    # 독립 보안 검토 BLOCKER 2: S3 키의 `\`·`:`·`/`를 전부 지워 평면 이름으로 — 윈도 절대경로·상위 폴더 조작 방지
    cleaned = _safe_name(r"pre/fix/C:\Windows\doc.pdf", "pre/fix/")
    assert "\\" not in cleaned and ":" not in cleaned and cleaned.endswith("doc.pdf")  # 구분자·드라이브 표기 다 지움
    assert "/" not in _safe_name("pre/../../etc/passwd", "pre/")  # "/"를 전부 지워 실제 경로 구분자가 안 남음
    # 독립 검토 MAJOR: Windows 예약 장치 이름 — 대소문자 무시·확장자 있어도 적용
    assert _safe_name("docs/CON.pdf", "docs/") == "_CON.pdf"
    assert _safe_name("docs/con", "docs/") == "_con"
    assert _safe_name("docs/Com1.docx", "docs/") == "_Com1.docx"
    assert _safe_name("docs/contract.pdf", "docs/") == "contract.pdf"  # CON으로 시작해도 전체 이름이 다르면 그대로
    f = _safe_join(dest, "normal.pdf")
    assert f == dest / "normal.pdf"
    try:
        _safe_join(dest, "..")  # 정리돼도 만약을 대비한 마지막 방어선(해석 결과가 dest 밖이면 거부)
        raise AssertionError("범위 밖 이름을 받아들임")
    except ValueError:
        pass
    print("[selftest] X2 — S3 키 이름 정리(\\·:·/ 제거)·받는 폴더 밖 쓰기 거부 통과")

    _selftest_rdb()
    _selftest_rdb_doc_location_fields()
    _selftest_filestoragemap()
    _selftest_same_key_new_version()
    _selftest_mssql()
    _selftest_finish_keep()


class _FakeS3:
    """가짜 Object Storage(selftest 전용) — {(bucket,key): (etag, bytes)}만 앎. 실제 네트워크·boto3 없이 head_object·
    download_file만. head_object는 ETag·ContentLength(= bytes 길이) 둘 다 돌려줌 — etag 열이 없는 표의 크기 대조 시험용."""

    def __init__(self, objs):
        self.objs = objs

    def head_object(self, Bucket, Key):
        etag, content = self.objs[(Bucket, Key)]
        return {"ETag": f'"{etag}"', "ContentLength": len(content)}

    def download_file(self, Bucket, Key, path):
        _, content = self.objs[(Bucket, Key)]
        Path(path).write_bytes(content)


@contextmanager
def _legacy_rdb_cols():
    """옛 synth 표(doc_location.csv: doc_id·bucket·object_key·etag·size_bytes·content_type·company_id·doc_type·
    contract_id·updated_at·version·supersedes_doc_id·is_deleted) 열 이름 — 기본 매핑이 AI.FileStorageMap으로
    바뀐 뒤에도 이 시험들은 RDB_COL_*로 옛 열에 맞춰서 돈다(요건 — 새 표 기본값은 그대로, 옛 표는 env로)."""
    mapping = {
        "RDB_COL_DOC_ID": "doc_id",
        "RDB_COL_KEY": "object_key",
        "RDB_COL_SIZE": "size_bytes",
        "RDB_COL_BUCKET": "bucket",
        "RDB_COL_ETAG": "etag",
        "RDB_COL_CONTENT_TYPE": "content_type",
        "RDB_COL_COMPANY": "company_id",
        "RDB_COL_DOC_TYPE": "doc_type",
        "RDB_COL_CONTRACT": "contract_id",
        "RDB_COL_UPDATED": "updated_at",
        "RDB_COL_VERSION": "version",
        "RDB_COL_SUPERSEDES": "supersedes_doc_id",
        "RDB_COL_IS_DELETED": "is_deleted",
    }
    with pc.PIPE.env(
        **mapping
    ):  # S7c — _rdb_cols가 설정 객체로 읽으므로 env 대신 객체를 덮어씀(os.environ은 안 바뀜 — 저장·복원 코드 불필요)
        yield


def _selftest_rdb():
    """AD44 — RDB(csv:) 질의 → 가짜 버킷으로 받기. 임시 합성 표 10건(고객 필터 3건 + 나머지 7건)을 만들고
    옛 열 이름(RDB_COL_*)으로 맞춘다(_legacy_rdb_cols — 기본값은 지금 AI.FileStorageMap)."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3
    with _legacy_rdb_cols():
        state_root = Path(tempfile.mkdtemp())
        csv_path = state_root / "doc_location.csv"
        fields = (
            "doc_id",
            "bucket",
            "object_key",
            "etag",
            "size_bytes",
            "content_type",
            "company_id",
            "doc_type",
            "contract_id",
            "updated_at",
        )
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i in range(10):
                doc_id = f"doc_{i:02d}"
                writer.writerow(
                    {
                        "doc_id": doc_id,
                        "bucket": "rag-docs",
                        "object_key": f"clients/{doc_id}.pdf",
                        "etag": f"{i + 1:032x}",
                        "size_bytes": len(f"content:{doc_id}".encode()),
                        "content_type": "application/pdf",
                        "company_id": "CL-1001" if i < 3 else "CL-1002",
                        "doc_type": "RFP",
                        "contract_id": "",
                        "updated_at": "2026-03-01T00:00:00Z",
                    }
                )
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 10
        objs = {(r["bucket"], r["object_key"]): (r["etag"].strip('"'), f"content:{r['doc_id']}".encode()) for r in rows}
        M._s3 = lambda: _FakeS3(objs)  # 전역 _s3() 교체(try/finally로 복원), 실제 네트워크·boto3 없이 시험
        env = contextlib.ExitStack()  # S7c — RDB_COMPANY 덮어쓰기(설정 객체) — 끝에서 한꺼번에 되돌림
        try:
            table = f"csv:{csv_path}"

            # ① 고객 필터(CL-1001, 3건) — 목록 질의 → 받기
            env.enter_context(pc.PIPE.env(RDB_COMPANY="CL-1001"))
            local_dir, names1, state = resolve(f"rdb:{table}", state_root, mode="prod")
            assert len(names1) == 3, names1
            from common.core import contract as ids

            man1 = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
            for n in names1:
                uri = ids.make_source_uri(n, local_dir / n)
                assert uri == man1[n]["uri"] and uri.startswith("s3://rag-docs/"), uri
            mark_done(state, names1, is_s3=True)

            # ② 2회차 — 같은 필터는 이미 처리한 3건뿐이라 0건
            local_dir2, names2, _ = resolve(f"rdb:{table}", state_root, mode="prod")
            assert names2 == [], names2
            print("[selftest] AD44 — RDB 고객 필터(CL-1001) 3건 → 2회차 0건 통과")

            # ③ 필터 없이 전체 — 나머지 7건(이미 처리한 3건은 빠짐), 누적 10건 전부 source_uri = s3://rag-docs/<키>
            env.enter_context(pc.PIPE.env(RDB_COMPANY=None))  # 필터 없음
            local_dir3, names3, state3 = resolve(f"rdb:{table}", state_root, mode="prod")
            assert len(names3) == 7, names3
            mark_done(state3, names3, is_s3=True)
            man = {r["file_name"]: r for r in jl(state3 / "manifest.jsonl")}
            assert len(man) == 10
            assert all(r["uri"].startswith("s3://rag-docs/") for r in man.values())
            assert {r["key"] for r in man.values()} == {r["object_key"] for r in rows}  # RDB 키와 1:1
            print("[selftest] AD44 — RDB 전체 10건, source_uri 10/10 s3://rag-docs/… 와 RDB 키 1:1 통과")

            # ④ 묶음 중 ETag 불일치 1건 — resolve()를 그대로 불러(fetch_one을 직접 안 부름) 그 문서만 거부·기록, 나머지는 받음
            # (독립 검토 BLOCK 1 — 전에는 ValueError가 resolve()의 fetch 루프에서 안 잡혀 전체가 크래시했음)
            mixed_csv = state_root / "mixed.csv"
            mixed_csv.write_text(
                "doc_id,bucket,object_key,etag,size_bytes,content_type,company_id,doc_type,contract_id,updated_at\n"
                "doc_good,rag-docs,clients/good.pdf,aa11aa11aa11aa11aa11aa11aa11aa11,5,application/pdf,CL-9999,RFP,,2026-03-01T00:00:00Z\n"
                "doc_bad,rag-docs,clients/bad.pdf,ff00ff00ff00ff00ff00ff00ff00ff00,10,application/pdf,CL-9999,RFP,,2026-03-01T00:00:00Z\n",
                encoding="utf-8",
            )
            M._s3 = lambda: _FakeS3(
                {
                    ("rag-docs", "clients/good.pdf"): ("aa11aa11aa11aa11aa11aa11aa11aa11", b"good"),
                    ("rag-docs", "clients/bad.pdf"): ("00aa00aa00aa00aa00aa00aa00aa00aa", b"x"),
                }
            )
            state4 = state_root / "run4"
            state4.mkdir()
            local4, names4, state4s = resolve(f"rdb:csv:{mixed_csv}", state4, mode="prod")
            assert names4 == ["doc_good"], names4  # doc_bad는 거부돼 빠짐, 크래시 안 하고 doc_good은 받음
            assert (local4 / "doc_good").exists() and not (local4 / "doc_bad").exists()
            rej = jl(state4s / "rejected.jsonl")
            assert len(rej) == 1 and rej[0]["doc_id"] == "doc_bad" and rej[0]["etag_rdb"] != rej[0]["etag_store"]
            print("[selftest] AD44 — resolve(): 묶음 중 ETag 불일치 1건 거부해도 나머지 계속 받음(크래시 안 함) 통과")

            # ⑤ watermark — 같은 updated_at 행 중 하나만 실패(ETag 불일치)해도 since가 그 행을 앞지르지 않음(독립 검토 BLOCK 2).
            # 성공분이 watermark를 올려 버리면(예: 성공분의 updated_at을 바로 since로 쓰면) 실패분이 다음 질의의 since
            # 필터(같은 updated_at이라 `>` 비교에 걸림)에 영영 안 보이게 된다 — 둘이 같은 updated_at일 때 재현.
            wm_csv = state_root / "wm.csv"
            wm_objs = {
                ("rag-docs", "clients/wx.pdf"): ("e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1", b"x"),
                ("rag-docs", "clients/wy.pdf"): ("WRONG00000000000000000000000000", b"y"),
            }  # wy는 처음엔 불일치
            wm_csv.write_text(
                "doc_id,bucket,object_key,etag,size_bytes,content_type,company_id,doc_type,contract_id,updated_at\n"
                "doc_wx,rag-docs,clients/wx.pdf,e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1,1,application/pdf,CL-1,RFP,,2026-05-01T00:00:00Z\n"
                "doc_wy,rag-docs,clients/wy.pdf,e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2,1,application/pdf,CL-1,RFP,,2026-05-01T00:00:00Z\n",
                encoding="utf-8",
            )
            M._s3 = lambda: _FakeS3(wm_objs)
            state5 = state_root / "run5"
            state5.mkdir()
            local5, names5a, state5s = resolve(f"rdb:csv:{wm_csv}", state5, mode="prod")
            assert names5a == ["doc_wx"], names5a  # wy 거부, wx만 받음 — 둘 다 updated_at 같음
            mark_done(state5s, names5a, is_s3=True)

            wm_objs[("rag-docs", "clients/wy.pdf")] = ("e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2e2", b"y")  # wy가 이제 고쳐짐(ETag 일치)
            # 2회차 — BLOCK 2가 있었다면 wx의 updated_at으로 since가 전진해 "같은 updated_at"인 wy가 질의 후보에도 안 들어
            # 0건이 됨(고쳐졌어도 영영 못 받음). 고친 지금은 since가 그대로(None)라 wy가 다시 후보로 나와 이번엔 받아진다.
            local5b, names5b, state5b = resolve(f"rdb:csv:{wm_csv}", state5, mode="prod")
            assert names5b == ["doc_wy"], names5b
            mark_done(state5b, names5b, is_s3=True)

            # 둘 다 끝났으니 이제 since가 전진 — 3회차는 0건
            _, names5c, _ = resolve(f"rdb:csv:{wm_csv}", state5, mode="prod")
            assert names5c == [], names5c
            print("[selftest] AD44 — watermark: 같은 updated_at 중 실패분이 영영 안 가려짐(해결되면 전진) 통과")
        finally:
            M._s3 = real_s3
            env.close()


def _selftest_rdb_doc_location_fields():
    """AD38 — doc_location의 version·supersedes_doc_id·is_deleted가 manifest에 그대로 실리는지(list_documents 출처).
    실제 합성 표(valid_env/edw/meta_rdb/doc_location.csv)로 — 옛 열 이름이라 _legacy_rdb_cols로 맞춤."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3
    with _legacy_rdb_cols():
        csv_path = ROOT / "valid_env" / "edw" / "meta_rdb" / "doc_location.csv"
        if not csv_path.exists():  # 10-15 — valid_env는 이미지에 없음(PC 시험 전용) → 이 부분만 건너뜀
            print(f"[selftest] RDB doc_location 실표 확인 건너뜀 — 합성 표 없음({csv_path.name}, 이미지)")
            return
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        objs = {(r["bucket"], r["object_key"]): (r["etag"].strip('"'), f"content:{r['doc_id']}".encode()) for r in rows}
        M._s3 = lambda: _FakeS3(objs)
        try:
            state_root = Path(tempfile.mkdtemp())
            local_dir, names, state = resolve(f"rdb:csv:{csv_path}", state_root, mode="prod")
            assert len(names) == len(rows), (len(names), len(rows))  # synth-meta-rdb는 전부 받아지는 ETag(가짜 저장소도 그대로 생성)
            man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
            v2 = man["rfi_answer_sjm_2023_v2"]
            assert v2["version"] == "2" and v2["supersedes_doc_id"] == "rfi_answer_sjm_2023_v1", v2
            assert man["rfi_answer_sjm_2023_v1"]["version"] == "1" and man["rfi_answer_sjm_2023_v1"]["supersedes_doc_id"] is None
            deleted = man["rfi_answer_sjm_2025"]
            assert deleted["is_deleted"] is True, deleted
            kept = man["rfp_veridian_mab_2023"]
            assert kept["is_deleted"] is False and kept["version"] == "1" and kept["supersedes_doc_id"] is None, kept
            print("[selftest] AD38 — doc_location 버전·대체 문서·삭제 여부가 manifest에 실림(synth-meta-rdb) 통과")
        finally:
            M._s3 = real_s3


def _selftest_filestoragemap():
    """AD44(c) — 실 EDW 표 AI.FileStorageMap 꼴(id·content_version_id·s3_key·original_filename·file_size, etag·
    bucket 열 없음) 합성 csv로: 받기(이름 충돌 구분 포함) → 2회차 0건 → 크기 불일치 거부 → source_uri 형식 ·
    company 열 없는 표에 RDB_COMPANY를 줘도 경고만 하고 필터 없이 진행 · TABLE_ID_RE가 AI.FileStorageMap(대소문자
    섞인 스키마.표)을 통과하는지."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3

    assert TABLE_ID_RE.match("AI.FileStorageMap")  # 요건 ⑥ — 대소문자 섞인 스키마.표도 화이트리스트 통과

    state_root = Path(tempfile.mkdtemp())
    csv_path = state_root / "file_storage_map.csv"
    # 5행 — id=1·4는 같은 original_filename(report.pdf, 이름 충돌 구분 시험)
    rows = [
        ("1", "101", "docs/a.pdf", "report.pdf", "4"),
        ("2", "102", "docs/b.pdf", "summary.pdf", "4"),
        ("3", "103", "docs/c.pdf", "contract.pdf", "4"),
        ("4", "104", "docs/d.pdf", "report.pdf", "4"),
        ("5", "105", "docs/e.pdf", "notes.pdf", "4"),
    ]
    csv_path.write_text(
        "id,content_version_id,s3_key,original_filename,file_size\n" + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8"
    )
    objs = {("fsm-bucket", f"docs/{c}.pdf"): (f"etag-unused-{c}", b"docA") for c in "abcde"}  # 4바이트 = file_size와 일치
    M._s3 = lambda: _FakeS3(objs)
    env = contextlib.ExitStack()
    env.enter_context(
        pc.PIPE.env(RDB_BUCKET="fsm-bucket", RDB_COMPANY="ignored-co")
    )  # S7c — 설정 객체 덮어쓰기(os.environ은 안 바뀜) · 이 표엔 company 열이 없음 — 경고 후 필터 없이 진행돼야 함(요건 ⑦)
    try:
        table = f"csv:{csv_path}"
        local_dir, names1, state = resolve(f"rdb:{table}", state_root, mode="prod")
        assert len(names1) == 5, names1  # company 필터가 조용히 걸리지 않고 무시됨 — 전부 받음
        assert {"1__report.pdf", "4__report.pdf"} <= set(names1), names1  # 이름 충돌 — doc_id 접두로 구분
        assert "summary.pdf" in names1 and "contract.pdf" in names1 and "notes.pdf" in names1
        from common.core import contract as ids

        man1 = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
        for n in names1:
            uri = ids.make_source_uri(n, local_dir / n)
            assert uri == man1[n]["uri"] and uri == f"s3://fsm-bucket/{man1[n]['key']}", uri  # 요건 ⑤ source_uri 형식
            assert man1[n]["original_filename"] and man1[n]["content_version_id"], man1[n]  # 요건 ⑦ — 있는 칸은 그대로
        mark_done(state, names1, is_s3=True)

        # 2회차 — 전부 처리 기록됐으니 0건(ETag 없는 표라도 _rdb_is_done이 키 존재만으로 판정)
        _, names2, _ = resolve(f"rdb:{table}", state_root, mode="prod")
        assert names2 == [], names2
        print("[selftest] AD44(c) — FileStorageMap: company 열 없음 경고·전부 받기(이름 충돌 구분)·2회차 0건·source_uri 통과")

        # 크기 불일치 — 별도 소규모 표(etag 열도 없음 → 크기 대조 경로)
        state2 = state_root / "mismatch"
        state2.mkdir()
        bad_csv = state_root / "mismatch.csv"
        bad_csv.write_text(
            "id,content_version_id,s3_key,original_filename,file_size\n10,201,docs/good.pdf,good.pdf,4\n11,202,docs/bad.pdf,bad.pdf,999\n",
            encoding="utf-8",
        )
        M._s3 = lambda: _FakeS3(
            {("fsm-bucket", "docs/good.pdf"): ("x", b"good"), ("fsm-bucket", "docs/bad.pdf"): ("x", b"bad!")}
        )  # 실제 길이 4 ≠ RDB 999
        local3, names3, state3 = resolve(f"rdb:csv:{bad_csv}", state2, mode="prod")
        assert names3 == ["bad.pdf", "good.pdf"], (
            names3
        )  # 2026-10-15(운영) — 크기 불일치는 참고 기록만 남기고 그대로 받음(식별은 key·sha256, 옛 거부 동작 폐지)
        mm = jl(state3 / "size_mismatch.log")
        assert len(mm) == 1 and mm[0]["size_rdb"] == 999 and mm[0]["size_store"] == 4, mm
        print(
            "[selftest] AD44(c) — FileStorageMap: etag 열 없어 크기(ContentLength) 대조 → 불일치는 참고 기록(size_mismatch.log)·다운로드 진행 통과"
        )
    finally:
        M._s3 = real_s3
        env.close()


def _selftest_same_key_new_version():
    """AD44(c) — 독립 검토 BLOCK: etag 없는 표에서 같은 s3_key에 새 id(새 content_version_id)가 들어오면(같은 경로에
    새 파일을 올리는 EDW 흐름) 키만 보고 "이미 처리됨"으로 오판해 영영 못 받던 버그. id=1(key=a) 처리 → id=2 같은
    key(새 판) 추가 → 2회차에 1건(id=2) 받음 → 3회차 0건(둘 다 처리 기록됐으니 since 전진)."""
    import tempfile

    # S9 — 옛 `global _s3` → `M._s3`(모듈 전역 대입)
    real_s3 = M._s3

    state_root = Path(tempfile.mkdtemp())
    csv_path = state_root / "versions.csv"
    header = "id,content_version_id,s3_key,original_filename,file_size\n"
    csv_path.write_text(header + "1,101,docs/same.pdf,same.pdf,4\n", encoding="utf-8")
    objs = {("fsm-bucket", "docs/same.pdf"): ("etag-unused", b"docA")}  # 4바이트 = file_size
    M._s3 = lambda: _FakeS3(objs)
    env = contextlib.ExitStack()
    env.enter_context(pc.PIPE.env(RDB_BUCKET="fsm-bucket"))  # S7c — 설정 객체 덮어쓰기(os.environ은 안 바뀜)
    try:
        table = f"csv:{csv_path}"
        _, names1, state = resolve(f"rdb:{table}", state_root, mode="prod")
        assert names1 == ["same.pdf"], names1
        mark_done(state, names1, is_s3=True)

        # id=2 — 같은 s3_key에 새 content_version_id(새 판) 추가(원본 object는 새 내용으로 덮였다고 가정, 길이는 같음)
        csv_path.write_text(header + "1,101,docs/same.pdf,same.pdf,4\n2,102,docs/same.pdf,same.pdf,4\n", encoding="utf-8")
        _, names2, state2 = resolve(f"rdb:{table}", state_root, mode="prod")
        assert names2 == ["same.pdf"], names2  # 키만 보면 0건이 돼야 하지만 새 판(id=2)이므로 1건 받아야 함
        mark_done(state2, names2, is_s3=True)

        _, names3, _ = resolve(f"rdb:{table}", state_root, mode="prod")
        assert names3 == [], names3  # 둘 다 처리 기록됐으니 since가 2까지 전진 — 3회차는 0건
        print("[selftest] AD44(c) — 같은 s3_key에 새 id(새 판): 키만으론 영구 누락됐을 것 → 2회차 1건 받음·3회차 0건 통과")
    finally:
        M._s3 = real_s3
        env.close()


def _selftest_mssql():
    """RDB_ENGINE=mssql(기본, 2026-10-07 EDW=Azure SQL/SQL Server 확정) — 실제 pymssql 연결 없이 pymssql.connect만
    가짜로 바꿔(monkeypatch) 쿼리 조립(대괄호 식별자·id 증분 WHERE·ORDER BY)과 dict 행 처리만 확인. 실제 설치·
    접속 시험 아님(사용자 10-07: 로컬 시험은 가짜 연결로)."""
    import pymssql

    from common.store import mssql  # S8b — 연결이 SQLAlchemy라 가짜 연결도 방언의 첫 연결 카탈로그 질의에 대답(mssql.FakeConnection)

    calls = []

    all_rows = [
        {"id": 1, "content_version_id": 101, "s3_key": "docs/a.pdf", "original_filename": "a.pdf", "file_size": 4},
        {"id": 2, "content_version_id": 102, "s3_key": "docs/b.pdf", "original_filename": "b.pdf", "file_size": 4},
    ]
    conns = []
    real_connect = pymssql.connect
    cols_of = list(all_rows[0])
    pymssql.connect = lambda **kw: (
        conns.append(FakeConnection(lambda sql, params: (cols_of, [tuple(r[c] for c in cols_of) for r in all_rows]), calls)) or conns[-1]
    )
    mssql.clear()
    env = contextlib.ExitStack()
    env.enter_context(
        COMMON.env(RDB_HOST="h", RDB_READ_USER="u", RDB_READ_PASSWORD="p", RDB_DATABASE="d")
    )  # 설정 객체 덮어쓰기(os.environ은 안 바뀜) — 원천 읽기는 읽기 계정(ops.md#op-03)
    try:
        cols = _rdb_cols()
        rows = _mssql_rows("AI.FileStorageMap", cols, None, None, "id", None)
        assert rows == all_rows, rows
        sql, params = calls[0]
        assert "[AI].[FileStorageMap]" in sql and "[id]" in sql and "ORDER BY [id]" in sql and "WHERE" not in sql, sql
        assert not params, params
        assert conns[0].closed  # 연결은 늘 닫힘(finally)

        calls.clear()
        _mssql_rows("AI.FileStorageMap", cols, None, None, "id", 1)
        sql2, params2 = calls[0]
        assert "WHERE [id] >= %s" in sql2 and params2 == (1,), (sql2, params2)  # DET1 — 엄격한 > 아님
        print(
            "[selftest] AD44(c) — RDB_ENGINE=mssql(기본): 대괄호 식별자·id 증분 WHERE·dict 행 처리(가짜 연결 — SQLAlchemy mssql+pymssql, S8b) 통과"
        )
    finally:
        pymssql.connect = real_connect
        mssql.clear()
        env.close()


def _selftest_finish_keep():
    """SI39 요건⑧(2026-10-08) — 즉시 삭제가 기본(원본 업로드가 없어져 publish_parse가 기다릴 이유가 없음,
    PARSE_KEEP_ORIGINALS 폐지). KEEP_LOCAL_ORIGINALS=1(디버그·샘플 작업 전용)만 보존. 지우기 전에 sha256을 항상
    manifest에 남겨(generic 'sha256' 필드 — PARSE_KEEP_MAX_GB 전용 'disk_cap_sha256'와 별개) publish_parse가 로컬
    없이도 EDW 행을 쓸 수 있게 한다."""
    import tempfile

    from common.core.contract import file_hash

    def _case(env_name):
        d = Path(tempfile.mkdtemp())
        state, local = d / "state", d / "local"
        state.mkdir()
        local.mkdir()
        (local / "a.txt").write_text("x", encoding="utf-8")
        (state / "manifest.jsonl").write_text(
            json.dumps({"file_name": "a.txt", "key": "k1", "etag": "e1", "updated_at": None}) + chr(10), encoding="utf-8"
        )
        rep = d / "index.json"
        rep.write_text(json.dumps({"docs": [{"doc": "a.txt", "engine": "eng1"}]}), encoding="utf-8")
        with pc.PIPE.env(**({env_name: "1"} if env_name else {})):  # S7c — finish()가 설정 객체로 읽으므로 env 대신 객체를 덮어씀
            finish(state, local, rep)
        man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
        return local / "a.txt", man["a.txt"]

    p, _man = _case("KEEP_LOCAL_ORIGINALS")
    assert p.exists(), "KEEP_LOCAL_ORIGINALS=1인데 원본이 지워짐"

    p2, man2 = _case(None)
    assert not p2.exists(), "SI39 요건⑧ — 기본인데 원본이 즉시 지워지지 않음"
    assert man2.get("sha256"), "지우기 전에 sha256을 manifest에 안 남김(publish_parse가 로컬 없이 EDW 행을 못 씀)"
    print("[selftest] SI39 요건⑧ — KEEP_LOCAL_ORIGINALS=1만 보존(디버그 전용)·기본은 파싱 끝나면 즉시 삭제 + sha256 기록 통과")

    # PARSE_KEEP_MAX_GB 상한 — KEEP_LOCAL_ORIGINALS=1(보존)인데 폴더가 상한을 넘으면 경고 뒤 보존 포기·즉시 삭제
    d = Path(tempfile.mkdtemp())
    state, local = d / "state", d / "local"
    state.mkdir()
    local.mkdir()
    (local / "a.txt").write_text("x" * 1024, encoding="utf-8")  # 1KB — 상한을 거의 0으로 두면 바로 넘음
    (state / "manifest.jsonl").write_text(
        json.dumps({"file_name": "a.txt", "key": "k1", "etag": "e1", "updated_at": None}) + chr(10), encoding="utf-8"
    )
    rep = d / "index.json"
    rep.write_text(json.dumps({"docs": [{"doc": "a.txt", "engine": "eng1"}]}), encoding="utf-8")
    expect_sha = file_hash(local / "a.txt")
    with pc.PIPE.env(KEEP_LOCAL_ORIGINALS="1", PARSE_KEEP_MAX_GB="0.0000001"):  # S7c — 설정 객체 덮어쓰기(1KB보다 작은 상한 — 바로 넘음)
        finish(state, local, rep)
    assert not (local / "a.txt").exists(), "PARSE_KEEP_MAX_GB 넘었는데 그대로 보존됨(디스크 보호 안 됨)"
    man = {r["file_name"]: r for r in jl(state / "manifest.jsonl")}
    assert man["a.txt"].get("disk_cap_sha256") == expect_sha, "상한으로 지우기 전에 sha256을 manifest에 안 남김(publish_parse가 행을 못 씀)"
    print("[selftest] PARSE_KEEP_MAX_GB — KEEP_LOCAL_ORIGINALS=1이어도 상한 넘으면 보존 포기·즉시 삭제 + sha256 기록(disk_cap_sha256) 통과")


def test_main():  # 옛 `if "--selftest" in sys.argv:` 갈래
    selftest()
