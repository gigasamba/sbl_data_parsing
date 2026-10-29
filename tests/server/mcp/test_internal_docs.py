"""mcp_server.services.search.internal_docs 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.internal_docs`."""

import io
import json
import time
from pathlib import Path

from mcp_server import config as mc
from mcp_server.config import CFG
from mcp_server.services.search import internal_docs as M
from mcp_server.services.search.internal_docs import (
    do_aggregate,
    do_evidence_image,
    do_list_documents,
    do_lookup_term,
    do_related,
)
from mcp_server.services.search.server_state import _STATE
from tests.server.mcp.test_server_state import _mk_bundle  # 옛 server_state._mk_bundle(자기 점검 공용 — S9에 server_state 시험 파일로 옮김)

ROOT = (
    Path(M.__file__).resolve().parents[3]
)  # 옛 main.py의 ROOT(= mcp_server/의 부모, 저장소 루트)와 같은 값 — selftest만 씀(옛 internal_docs.py의 줄 — `__file__`은 모듈 것으로)


class _FakeBody:
    """OP21 selftest 전용 — boto3 get_object()["Body"](StreamingBody) 자리. chunk(기본 1KB)씩만 돌려줘
    호출부가 요청한 크기(1MB)보다 작은 조각으로 여러 번 나눠 읽게 만든다(독립 보안 검토 10-09 — 스트리밍
    도중 상한 확인을 실제로 여러 루프에 걸쳐 시험하기 위함, 한 번에 다 읽히면 '첫 조각이 곧 전체'라 의미가 약함)."""

    def __init__(self, data, chunk=1024, delay=0.0):
        self._data, self._chunk, self._delay, self._pos = data, chunk, delay, 0

    def read(self, n=None):
        if self._delay:
            time.sleep(self._delay)
        size = min(n or self._chunk, self._chunk)
        out = self._data[self._pos : self._pos + size]
        self._pos += len(out)
        return out

    def close(self):
        pass


class _FakeOSClient:
    """OP21 selftest 전용 — 가짜 Object Storage(boto3 S3 클라이언트 자리, 네트워크 없음). get_object만
    구현(do_evidence_image가 스트리밍으로 받음 — head_object·download_file은 더 안 씀)."""

    def __init__(self, objects, delay=0.0, chunk=1024):
        self.objects, self.delay, self.chunk = objects, delay, chunk

    def get_object(self, Bucket, Key):
        return {"Body": _FakeBody(self.objects[(Bucket, Key)], chunk=self.chunk, delay=self.delay)}


def _selftest_evidence_image_fetch():
    """OP21(S78) — get_evidence_image: 원본이 이 서버 디스크에 없고 source_uri가 s3://면 원천에서 tmp로 받아
    자르고 바로 지움(디스크 잔여 0) · Object Storage 설정 없음은 명확한 '사용 불가' 코드 · 크기 상한을
    **스트리밍 도중**(여러 청크에 걸쳐) 확인해 중단·tmp 잔여 0(독립 보안 검토 10-09 — head_object 사전 확인만
    으로는 download_file 내부에서 상한이 안 걸리던 구멍) · 원본 위치도 모름 · 동시 요청 상한(둘 중 하나만
    통과) · 응답 error는 코드뿐(버킷·키·예외 원문 비노출)."""
    import tempfile
    import threading

    from PIL import Image as PI

    from common.store import objectstore as OS
    from mcp_server.services import objectstore_access as OSA

    buf = io.BytesIO()
    PI.new("RGB", (40, 30), "white").save(buf, "PNG")
    png_bytes = buf.getvalue()
    big_bytes = b"x" * 20000  # 상한보다 훨씬 큰 가짜 객체 — 1KB 청크로 여러 번 나눠 받다 중단돼야 함
    objs = {("testbkt", "orig/doc1.png"): png_bytes, ("testbkt", "orig/big.bin"): big_bytes}

    docs = [
        {
            "file_path": "nope/doc1.png",
            "file_name": "doc1.png",
            "file_sha256": "e" * 64,
            "doc_format": ".png",
            "source_uri": "s3://testbkt/orig/doc1.png",
        },
        {"file_path": "nope/doc2.png", "file_name": "doc2.png", "file_sha256": "f" * 64, "doc_format": ".png"},
        {
            "file_path": "nope/big.bin",
            "file_name": "big.bin",
            "file_sha256": "9" * 64,
            "doc_format": ".bin",
            "source_uri": "s3://testbkt/orig/big.bin",
        },
    ]
    chunks = [
        {"doc": i, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1, "bbox": None, "section": None}
        for i in range(3)
    ]
    d = _mk_bundle(docs, chunks)

    old_configured, old_client = OSA.configured, OS.client
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d))  # S7d — 설정 객체 덮기(옛 old_env 저장·복원 대신)
    try:
        # ① Object Storage 설정 없음 — 명확한 '사용 불가' 코드(크래시·빈 응답·상세 노출 아님)
        OSA.configured = lambda: False
        meta, png = do_evidence_image("doc1.png")
        assert png is None and meta.get("error") == "source_storage_unavailable", meta

        # ② 설정 있음 — 받아서 자르고 돌려줌, tmp 폴더까지 지워짐(디스크 잔여 0)
        OSA.configured = lambda: True
        OS.client = lambda timeout=None: _FakeOSClient(objs)
        before = sorted(Path(tempfile.gettempdir()).glob("mcp_evid_*"))
        meta, png = do_evidence_image("doc1.png")
        assert png and meta["w"] == 40 and meta["h"] == 30 and meta["file_path"] == "s3://testbkt/orig/doc1.png", meta
        after = sorted(Path(tempfile.gettempdir()).glob("mcp_evid_*"))
        assert after == before, (before, after)

        # ③ 크기 상한 — HEAD 없이 **스트리밍 도중**(1KB 청크 여러 번) 넘으면 중단, tmp 잔여 0(독립 보안 검토 10-09)
        with mc.senv(MCP_EVID_MAX_MB="0.005"):  # 5000바이트 — big_bytes(20000) 받다 두 번째~세 번째 청크에서 걸림
            tmp_before = sorted(Path(tempfile.gettempdir()).glob("mcp_evid_*"))
            meta2, png2 = do_evidence_image("big.bin")
            assert png2 is None and meta2.get("error") == "source_fetch_too_large", meta2
            tmp_after = sorted(Path(tempfile.gettempdir()).glob("mcp_evid_*"))
            assert tmp_after == tmp_before, (tmp_before, tmp_after)  # 부분 파일까지 지워져 잔여 0

        # ③b 시간 상한 — 같은 루프에서 확인(청크마다 느리게 오면 다 받기 전에 중단)
        with mc.senv(MCP_EVID_TIMEOUT_SEC="0.05"):
            OS.client = lambda timeout=None: _FakeOSClient(objs, delay=0.03)  # 청크 20개 × 0.03s > 0.05s
            meta2b, png2b = do_evidence_image("big.bin")
            assert png2b is None and meta2b.get("error") == "source_fetch_timeout", meta2b
        OS.client = lambda timeout=None: _FakeOSClient(objs)

        # ④ 원본 위치도 모름(source_uri 없음) — 로컬에도 없고 s3도 아님
        meta3, png3 = do_evidence_image("doc2.png")
        assert png3 is None and meta3.get("error") == "source_unknown", meta3

        # ⑤ 동시 요청 상한(MCP_EVID_MAX_CONCURRENCY=1) — 겹치면 하나만 통과
        _env.enter_context(mc.senv(MCP_EVID_MAX_CONCURRENCY="1"))  # 아래 finally의 _env.close()가 되돌림
        M._EVID_SEM = None
        holding = threading.Event()  # 첫 요청이 상한 자리를 잡고 원본을 읽는 중(클라이언트는 자리를 잡은 뒤에 만듦) — sleep 경쟁 대신

        def slow_client(timeout=None):
            holding.set()
            return _FakeOSClient(objs, delay=0.15)

        OS.client = slow_client
        results = []

        def call():
            results.append(do_evidence_image("doc1.png"))

        t1, t2 = threading.Thread(target=call), threading.Thread(target=call)
        t1.start()
        assert holding.wait(10), "첫 요청이 원본을 읽기 시작하지 않음"
        t2.start()
        t1.join()
        t2.join()
        oks = [m for m, p in results if p is not None]
        errs = [m for m, p in results if p is None]
        assert len(oks) == 1 and len(errs) == 1 and errs[0].get("error") == "source_fetch_busy", results
    finally:
        OSA.configured, OS.client = old_configured, old_client
        M._EVID_SEM = None
        _STATE.clear()
        _env.close()
    print(
        "[selftest] OP21 — get_evidence_image 원천 재접근: 받아서 자르고 바로 지움(디스크 잔여 0) · "
        "설정 없음 '사용 불가' 코드 · 크기·시간 상한을 스트리밍 도중 확인(tmp 잔여 0) · 원본 위치 모름 · "
        "동시 요청 상한(1건만 통과) · 응답 error는 코드뿐 통과"
    )


def _selftest_evidence_image_local_folder():
    """폴더 저장소 환경 시험(사용자 결정 10-08) — get_evidence_image: source_uri가 file://<경로>이고
    MCP_EVID_LOCAL_ROOTS(콤마 목록)가 그 경로의 상위 폴더를 허용하면 받기·삭제 없이 바로 그 파일에서
    잘라 돌려준다(원본은 읽기만, 그대로 남음) · env 없음(기본)은 지금과 바이트 동일(source_unknown, s3://가
    아니면 전부 거부) · 허용 루트 밖 경로·'../' 탈출(resolve 후 대조)은 거부(경로 원문 노출 없음, 코드만) ·
    크기 상한(MCP_EVID_MAX_MB)도 로컬 읽기에 같이 적용."""
    import shutil
    import tempfile

    from PIL import Image as PI

    tmproot = Path(tempfile.mkdtemp())
    allowed, outside = tmproot / "allowed", tmproot / "outside"
    allowed.mkdir()
    outside.mkdir()
    img_path = allowed / "orig.png"
    PI.new("RGB", (40, 30), "white").save(img_path, "PNG")
    outside_img = outside / "orig.png"
    PI.new("RGB", (10, 10), "white").save(outside_img, "PNG")

    docs = [
        {
            "file_path": "nope/local1.png",
            "file_name": "local1.png",
            "file_sha256": "1" * 64,
            "doc_format": ".png",
            "source_uri": f"file://{img_path}",
        },
        {
            "file_path": "nope/local2.png",
            "file_name": "local2.png",
            "file_sha256": "2" * 64,
            "doc_format": ".png",
            "source_uri": f"file://{outside_img}",
        },
        {
            "file_path": "nope/local3.png",
            "file_name": "local3.png",
            "file_sha256": "3" * 64,
            "doc_format": ".png",
            "source_uri": f"file://{allowed}/../outside/orig.png",
        },
    ]  # '../' 탈출 — resolve 후 outside로 감
    chunks = [
        {"doc": i, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1, "bbox": None, "section": None}
        for i in range(3)
    ]
    d = _mk_bundle(docs, chunks)

    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_EVID_LOCAL_ROOTS=None, MCP_EVID_MAX_MB=None)  # S7d — 설정 객체 덮기
    try:
        # ① env 없음(기본) — file://는 거부, 지금(병합 전)과 바이트 동일
        meta, png = do_evidence_image("local1.png")
        assert png is None and meta.get("error") == "source_unknown", meta

        # ② MCP_EVID_LOCAL_ROOTS로 allowed 폴더를 허용 — 받기·삭제 없이 바로 자름, 원본 그대로
        _env.enter_context(mc.senv(MCP_EVID_LOCAL_ROOTS=str(allowed)))
        meta2, png2 = do_evidence_image("local1.png")
        assert png2 and meta2["w"] == 40 and meta2["h"] == 30 and meta2["file_path"] == str(img_path.resolve()), meta2
        assert img_path.exists(), "원본이 지워짐(file:// 로컬 읽기는 받기·삭제가 없어야 함)"

        # ③ 허용 루트 밖 경로 — 거부(에러에 경로 원문 없음)
        meta3, png3 = do_evidence_image("local2.png")
        assert png3 is None and meta3.get("error") == "source_unknown" and "outside" not in json.dumps(meta3), meta3

        # ④ '../' 경로 탈출 — resolve 후에도 허용 루트 밖이면 거부
        meta4, png4 = do_evidence_image("local3.png")
        assert png4 is None and meta4.get("error") == "source_unknown", meta4

        # ⑤ 크기 상한(MCP_EVID_MAX_MB) — 실제 파일 크기보다 작은 상한을 주면 거부
        real_size = img_path.stat().st_size
        _env.enter_context(mc.senv(MCP_EVID_MAX_MB=str(real_size / 1e6 / 2)))
        meta5, png5 = do_evidence_image("local1.png")
        assert png5 is None and meta5.get("error") == "source_fetch_too_large", meta5
    finally:
        _STATE.clear()
        _env.close()
        shutil.rmtree(tmproot, ignore_errors=True)
    print(
        "[selftest] 폴더 저장소 — get_evidence_image file:// 로컬 재접근: MCP_EVID_LOCAL_ROOTS 허용 루트 "
        "아래만 받기·삭제 없이 바로 자름(원본 보존) · env 없음(기본) 바이트 동일 · 허용 밖·'../' 탈출 거부 "
        "(경로 원문 비노출) · 크기 상한 적용 통과"
    )


def _selftest_evidence_image_office_and_bbox():
    """BR55 — get_evidence_image: (a) bbox를 do_get_image 메타가 돌려주는 그대로(list)·문자열 둘 다 받아 같은
    결과(전에는 list면 AttributeError로 죽음) · (b) 형식이 안 맞는 bbox(그 밖 타입·개수)는 크래시 대신 error ·
    (c) Office 원본(.docx/.xlsx/.pptx, PIL이 못 엶)은 같은 문서의 그림 파싱 결과(저장된 PNG)로 대신 돌려주고,
    맞는 그림이 없으면(전에는 PIL.UnidentifiedImageError로 죽음) 명확한 error만."""
    import shutil
    import tempfile

    from PIL import Image as PI

    tmproot = Path(tempfile.mkdtemp())
    png_path = tmproot / "orig.png"
    PI.new("RGB", (40, 30), "white").save(png_path, "PNG")

    docs = [
        {"file_path": str(png_path), "file_name": "doc1.png", "file_sha256": "1" * 64, "doc_format": ".png"},
        {"file_path": str(tmproot / "no-such.docx"), "file_name": "sel.docx", "file_sha256": "2" * 64, "doc_format": ".docx"},
        {"file_path": str(tmproot / "no-such2.docx"), "file_name": "empty.docx", "file_sha256": "3" * 64, "doc_format": ".docx"},
    ]
    chunks = [
        {"doc": i, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "x", "n_terms": 1, "bbox": None, "section": None}
        for i in range(3)
    ]
    d = _mk_bundle(docs, chunks)

    images_dir = tmproot / "_images"
    fig_dir = images_dir / "sel.docx"
    fig_dir.mkdir(parents=True)
    PI.new("RGB", (60, 50), "red").save(fig_dir / "fig1.png", "PNG")
    index = images_dir / "index.jsonl"
    index.write_text(
        json.dumps({"image_id": "sel.docx#p1#i1", "doc": "sel.docx", "page": 1, "png": "_images/sel.docx/fig1.png"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_IMAGES=str(index))  # S7d — 설정 객체 덮기
    try:
        # ① list bbox == string bbox(같은 출력, 전에는 list면 AttributeError)
        meta_s, png_s = do_evidence_image("doc1.png", bbox="5,5,20,20")
        meta_l, png_l = do_evidence_image("doc1.png", bbox=[5, 5, 20, 20])
        assert "error" not in meta_s and "error" not in meta_l, (meta_s, meta_l)
        assert meta_s == meta_l and png_s == png_l, (meta_s, meta_l)

        # ② 형식이 안 맞는 bbox(그 밖 타입·개수) — 크래시 대신 error
        meta_bad, png_bad = do_evidence_image("doc1.png", bbox="garbage")
        assert png_bad is None and "error" in meta_bad, meta_bad
        meta_bad2, png_bad2 = do_evidence_image("doc1.png", bbox=[1, 2, 3])
        assert png_bad2 is None and "error" in meta_bad2, meta_bad2
        meta_bad3, png_bad3 = do_evidence_image("doc1.png", bbox=123)
        assert png_bad3 is None and "error" in meta_bad3, meta_bad3

        # ③ Office 원본 — 같은 문서·쪽의 저장된 그림이 있으면 그 PNG로(크래시 대신)
        meta_o, png_o = do_evidence_image("sel.docx")
        assert png_o is not None and "error" not in meta_o and meta_o.get("image_id") == "sel.docx#p1#i1", meta_o

        # ④ Office 원본 — 맞는 그림이 없으면 명확한 error(크래시 대신, 전에는 UnidentifiedImageError)
        meta_e, png_e = do_evidence_image("empty.docx")
        assert png_e is None and "쪽 렌더 불가" in meta_e.get("error", ""), meta_e
    finally:
        _STATE.clear()
        _env.close()
        shutil.rmtree(tmproot, ignore_errors=True)
    print(
        "[selftest] BR55 — get_evidence_image: bbox str·list 같은 결과 · 형식 오류 bbox는 error(크래시 없음) · "
        "Office 원본은 그림 파싱 결과 PNG로 대신(없으면 명확한 error) 통과"
    )


def _selftest_list_documents():
    """AD38 — list_documents, 실제 synth-meta-rdb 표(valid_env/edw/meta_rdb)로: 고객 필터 때 다른 고객 0 ·
    반환된 contract_no로 추리면 '계약 C-RDB-2025-005 문서 목록' 4/4(다른 세션 실측: 검색 상위10은 2/4) ·
    최신판만(대체 구판 제외)·is_deleted 제외가 기본값대로 동작하는지."""
    import csv
    import hashlib
    import tempfile

    base = ROOT / "valid_env" / "edw" / "meta_rdb"
    doc_loc, client_m = base / "doc_location.csv", base / "client_master.csv"
    if not (
        doc_loc.exists() and client_m.exists()
    ):  # 이미지에는 deploy/만 — 예시 데이터(valid_env) 없음 → 운영자 selftest에선 건너뜀(10-14)
        print(f"[selftest] AD38 list_documents 건너뜀 — 예시 표 없음({base})")
        return
    with open(client_m, encoding="utf-8-sig", newline="") as f:
        company = {r["company_id"]: r["company"] for r in csv.DictReader(f)}
    state = Path(tempfile.mkdtemp())
    with open(doc_loc, encoding="utf-8-sig", newline="") as f:  # 표를 직접 읽음(pipeline import는 모듈 경계 위반 — check_modules)
        rows = list(csv.DictReader(f))
    man_path = state / "manifest.jsonl"
    man_path.write_text(
        "".join(
            json.dumps(
                {
                    "file_name": r["doc_id"],
                    "doc_id": r["doc_id"],
                    "doc_type": r["doc_type"],
                    "version": r["version"],
                    "supersedes_doc_id": r["supersedes_doc_id"],
                    "is_deleted": r["is_deleted"].strip().lower() in ("1", "true", "t"),
                    "updated_at": r["updated_at"],
                    "contract_id": r["contract_id"],
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in rows
        ),
        encoding="utf-8",
    )
    docs = [
        {
            "file_path": f"{r['doc_id']}.txt",
            "file_name": r["doc_id"],
            "file_sha256": hashlib.sha256(r["doc_id"].encode()).hexdigest(),
            "doc_format": ".txt",
            "client": company.get(r["company_id"]),
        }
        for r in rows
    ]
    d = _mk_bundle(docs, [])
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_MANIFEST=str(man_path))  # S7d — 설정 객체 덮기
    try:
        sjm = "선진메디팜(주)"
        out = do_list_documents(client=sjm)  # 기본: latest_only=True·include_deleted=False
        assert out["count"] == 10, out["count"]
        assert {x["client"] for x in out["documents"]} == {sjm}, out["documents"]  # 다른 고객 0
        c5 = sorted(x["file_name"] for x in out["documents"] if x["contract_no"] == "C-RDB-2025-005")
        assert c5 == sorted(["rfp_sjm_mab_2025", "contract_sjm_mab_2025", "quote_sjm_mab_2025", "mail_sjm_negotiation_2025"]), c5  # 4/4

        rfi = do_list_documents(client=sjm, doc_type="RFI_ANSWER")
        assert sorted(x["file_name"] for x in rfi["documents"]) == sorted(
            ["rfi_answer_sjm_2023_v2", "rfi_answer_sjm_2024", "rfi_answer_sjm_2026"]
        ), rfi["documents"]  # v1 대체·2025 삭제 제외

        with_old = do_list_documents(client=sjm, latest_only=False)
        assert with_old["count"] == 11 and any(x["file_name"] == "rfi_answer_sjm_2023_v1" for x in with_old["documents"]), with_old

        with_deleted = do_list_documents(client=sjm, include_deleted=True)
        assert with_deleted["count"] == 11 and any(x["file_name"] == "rfi_answer_sjm_2025" for x in with_deleted["documents"]), with_deleted

        all_docs = do_list_documents()  # client 없음 — 전체(기본 필터만)
        assert all_docs["count"] == 26, all_docs["count"]  # 28건 - v1(대체) - 2025(삭제)
        old_cap = CFG.LIST_DOCS_MAX
        try:
            CFG.LIST_DOCS_MAX = 5
            capped = do_list_documents()
            assert capped["count"] == 26 and len(capped["documents"]) == 5 and capped["truncated"] is True  # count는 전체, documents만 잘림
            assert "21건" in capped["note"], capped["note"]  # 26 - 5
            CFG.LIST_DOCS_MAX = 0
            uncapped = do_list_documents()
            assert uncapped["count"] == 26 and len(uncapped["documents"]) == 26 and "truncated" not in uncapped  # 0 = 무제한(OP11)
        finally:
            CFG.LIST_DOCS_MAX = old_cap
    finally:
        _STATE.clear()
        _env.close()
    print(
        "[selftest] AD38 list_documents — synth-meta-rdb: 고객 필터 다른 고객 0 · 계약 문서 목록 4/4 · 최신판만·삭제 제외 기본값 통과 ·"
        " 결과 크기 상한(기본 200)·=0 무제한 통과"
    )


def _selftest_list_documents_latest_only_doc_id():
    """GH1-15 — 최신판 필터가 파일 이름과 manifest doc_id(RDB 원천 키)를 비교하던 버그. file_name과 doc_id가
    다른 값인 합성 manifest(v2가 v1을 supersedes_doc_id로 가리킴)로 재현: 파일 이름끼리 비교하면(버그) v1이
    전혀 안 걸러짐 — 이 시험은 manifest의 자기 doc_id로 비교하는지(수정 후) 확인한다."""
    docs = [
        {"file_path": "contract_v1.pdf", "file_name": "contract_v1.pdf", "file_sha256": "1" * 64, "doc_format": ".pdf"},
        {"file_path": "contract_v2.pdf", "file_name": "contract_v2.pdf", "file_sha256": "2" * 64, "doc_format": ".pdf"},
    ]
    d = _mk_bundle(docs, [])
    man_path = d / "manifest.jsonl"
    man_path.write_text(
        json.dumps({"file_name": "contract_v1.pdf", "doc_id": "DOC-1", "doc_type": "CONTRACT", "version": "1"}, ensure_ascii=False)
        + "\n"
        + json.dumps(
            {"file_name": "contract_v2.pdf", "doc_id": "DOC-2", "doc_type": "CONTRACT", "version": "2", "supersedes_doc_id": "DOC-1"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _STATE.clear()
    _env = mc.senv(MCP_STORE="local", MCP_BUNDLE=str(d), MCP_MANIFEST=str(man_path))  # S7d — 설정 객체 덮기
    try:
        default_on = do_list_documents()  # latest_only=True(기본)
        assert {x["file_name"] for x in default_on["documents"]} == {"contract_v2.pdf"}, default_on["documents"]  # v1 빠짐

        with_old = do_list_documents(latest_only=False)
        assert {x["file_name"] for x in with_old["documents"]} == {"contract_v1.pdf", "contract_v2.pdf"}, with_old["documents"]
    finally:
        _STATE.clear()
        _env.close()
    print("[selftest] GH1-15 list_documents latest_only — file_name≠doc_id manifest에서도 구판(v1) 제외·latest_only=False면 포함 통과")


def _selftest_aggregate_struct_fail():
    """RUN_MODE=prod + PG 실패(X1b) — do_aggregate가 StructDBError로 죽지 않고 note로 알림(서버 생존 확인)."""
    with mc.senv(RUN_MODE="prod", STRUCT_BACKEND="pg", STRUCT_DB=None, PG_PASSWORD=None, PG_CONN_FILE=None):  # S7d — 설정 객체 덮기
        r = do_aggregate("계약 ID 없는 RFI 중 계약으로 이어진 것은?")  # doc_link_question에 걸리는 질문 — structdb 경로를 탐
        assert "정형 저장소 연결 실패" in (r.get("note") or ""), r
    print("[selftest] RUN_MODE=prod + PG 실패 — do_aggregate가 안 죽고 note로 알림 통과")


def _selftest_lookup_term():
    """lookup_term·related(X4) — _STATE에 가짜 로컬 묶음 Retriever를 주입(services.connect 우회)."""
    import csv
    import tempfile

    import numpy as np

    from mcp_server.services.search.retriever import Retriever

    d, sha = Path(tempfile.mkdtemp()), "b" * 64
    (d / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
    (d / "docs.jsonl").write_text(
        json.dumps({"file_path": "b.txt", "file_name": "b.txt", "file_sha256": sha, "doc_format": ".txt"}) + "\n", encoding="utf-8"
    )
    c = {
        "doc": 0,
        "seq": 0,
        "page": 1,
        "line_start": 1,
        "line_end": 1,
        "chunk_text": "DSP 수율 설명",
        "n_terms": 3,
        "bbox": None,
        "section": None,
    }
    (d / "chunks.jsonl").write_text(json.dumps(c, ensure_ascii=False) + "\n", encoding="utf-8")
    np.save(d / "vectors.npy", np.zeros((1, 0), dtype="float32"))
    (d / "concept_chunk.jsonl").write_text(json.dumps({"concept_id": "B", "chunk_key": f"{sha}:0", "count": 2}) + "\n", encoding="utf-8")
    gdir = d / "glossary"
    gdir.mkdir()
    fields = [
        "concept_id",
        "canonical",
        "category",
        "synonyms",
        "abbreviations",
        "weak_synonyms",
        "broader",
        "related",
        "context_required",
        "case_sensitive",
        "definition_ko",
        "definition_en",
        "source",
        "owner",
        "status",
        "updated",
    ]
    with (gdir / "domain_terms.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerow(
            {
                "concept_id": "B",
                "canonical": "Downstream Process",
                "category": "process",
                "synonyms": "",
                "abbreviations": "DSP",
                "weak_synonyms": "",
                "broader": "",
                "related": "",
                "context_required": "",
                "case_sensitive": "Y",
                "definition_ko": "하류 공정",
                "definition_en": "",
                "source": "",
                "owner": "",
                "status": "approved",
                "updated": "",
            }
        )
    _env = mc.senv(GLOSSARY_DIR=str(gdir))  # 인계 키 — senv가 os.environ에도 씀(terms.py가 env로 읽음), close()가 되돌림
    try:
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = (
            Retriever(d),
            d,
            time.time(),
        )  # _build_retriever()를 거치지 않고 직접 주입 — 재적재 확인에 필요한 키도 같이
        info = do_lookup_term("DSP")
        assert info["concept_id"] == "B" and info["docs"] == ["b.txt"], info
        assert do_related("B") == {"concept_id": "B", "related": []}
        assert do_lookup_term("없는말") == {"error": "사전에 없음: 없는말"}
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] lookup_term·related(X4) 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — internal_docs.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgtables

    cfgtables._CACHE.setdefault(
        "stack", cfgtables.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    _selftest_aggregate_struct_fail()
    _selftest_lookup_term()
    _selftest_list_documents()
    _selftest_list_documents_latest_only_doc_id()
    _selftest_evidence_image_fetch()
    _selftest_evidence_image_local_folder()
    _selftest_evidence_image_office_and_bbox()
