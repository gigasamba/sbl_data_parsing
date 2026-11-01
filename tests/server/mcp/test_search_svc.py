"""mcp_server.services.search.search_svc 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.search_svc`."""

import json
import time
from pathlib import Path
from unittest.mock import patch

from mcp_server import config as mc
from mcp_server.schemas.evidence import EVIDENCE_KEYS, SEARCH_TOP_KEYS
from mcp_server.services.search import search_svc as M
from mcp_server.services.search.search_svc import do_search
from mcp_server.services.search.server_state import _STATE, CALLER
from mcp_server.services.search.shaping import evidence_status
from tests.server.mcp import pgfix  # mc-01(11-01) — 검색은 PG 하나: 묶음을 SQLite 대역에 적재(임시 폴더, 실 PG 안 닿음)

ROOT = (
    Path(M.__file__).resolve().parents[3]
)  # 옛 main.py의 ROOT(= mcp_server/의 부모, 저장소 루트)와 같은 값 — selftest만 씀(옛 search_svc.py의 줄 — `__file__`은 모듈 것으로)


def _selftest_copy_group():
    """R2-c 요건① — 같은 메일의 다른 형식(.eml/.msg)이 evidence 슬롯을 독점하지 않고 한 슬롯(대표) + variants로
    묶이는지."""
    from mcp_server.services.search import retriever as RT

    body = "MRH-MAB-01 기술이전 관련 문의드립니다 1차 트랜스퍼 배치 완료 추가 배치 3회 계획 단가 434000000 KRW"
    docs = [
        {"file_path": "MAIL-X.eml", "file_name": "MAIL-X.eml", "file_sha256": "1" * 64, "doc_format": ".eml"},
        {"file_path": "MAIL-X.msg", "file_name": "MAIL-X.msg", "file_sha256": "2" * 64, "doc_format": ".msg"},
    ]
    chunks = [
        {"doc": 0, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": body, "n_terms": 10, "bbox": None, "section": None},
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "Date: 2025-04-08\n" + body,
            "n_terms": 10,
            "bbox": None,
            "section": None,
        },
    ]
    d = pgfix.mk_bundle(docs, chunks)
    old = {k: _STATE.get(k) for k in ("R", "bundle", "checked_at")}
    _env = pgfix.use(d)
    try:
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = RT.Retriever(d), d, time.time()
        out = do_search("단가는?", k=5)
        assert [e["file_name"] for e in out["evidence"]] == ["MAIL-X.eml"], out["evidence"]
    finally:
        _env.close()
        _STATE.clear()
        _STATE.update({k: v for k, v in old.items() if v is not None})
    print("[selftest] R2-c 사본 그룹 — 한 슬롯 통과")


def _selftest_copy_group_rep_text():
    """engine-qa CONCERN(QA066) 재발 방지 — 최상위 순위가 이미지(OCR) 청크라 배치 수 문장이 빠진 실제 사례를
    재현: mailshot(.png)이 더 짧아 BM25 1위로 뽑혀도, 대표 슬롯(자리는 그대로 1위)의 내용은 형식이 더 믿을만한
    eml·msg 중에서 고르고(QA066에선 eml) 그 안에 빠진 문장(배치)이 있는지. 대표 자신의 파일명은 variants에
    없어야(요건②)."""
    from mcp_server.services.search import retriever as RT

    docs = [
        {"file_path": "mailshot_MAIL-X.png", "file_name": "mailshot_MAIL-X.png", "file_sha256": "1" * 64, "doc_format": ".png"},
        {"file_path": "MAIL-X.eml", "file_name": "MAIL-X.eml", "file_sha256": "2" * 64, "doc_format": ".eml"},
        {"file_path": "MAIL-X.msg", "file_name": "MAIL-X.msg", "file_sha256": "3" * 64, "doc_format": ".msg"},
    ]
    full_body = (
        "From 박지아 To 김서윤 Subject MRH-MAB-01 기술이전 일정 공유 단가는 434000000 KRW 입니다 "
        "1차 트랜스퍼 배치 완료 추가 배치 3회 계획입니다 첨부 일정표 확인 부탁드립니다"
    )
    png_text = "From 박지아 To 김서윤 Subject MRH-MAB-01 기술이전 일정 공유 단가는 434000000 KRW 입니다 첨부 일정표 확인 부탁드립니다"  # OCR — 배치 문장 빠짐
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": png_text,
            "n_terms": len(png_text.split()),
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": full_body,
            "n_terms": len(full_body.split()),
            "bbox": None,
            "section": None,
        },
        {
            "doc": 2,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": full_body,
            "n_terms": len(full_body.split()),
            "bbox": None,
            "section": None,
        },
    ]
    d = pgfix.mk_bundle(docs, chunks)
    old = {k: _STATE.get(k) for k in ("R", "bundle", "checked_at")}
    _env = pgfix.use(d)
    try:
        _STATE["R"], _STATE["bundle"], _STATE["checked_at"] = RT.Retriever(d), d, time.time()
        out = do_search("단가는?", k=5)
        rep = out["evidence"][0]
        assert rep["file_name"] in ("MAIL-X.eml", "MAIL-X.msg"), rep  # ① 대표 텍스트는 형식 우선(이미지 아님)
        assert "배치" in rep["text"], rep["text"]  # ① 이미지에만 없던 문장이 대표 텍스트에 있음
    finally:
        _env.close()
        _STATE.clear()
        _STATE.update({k: v for k, v in old.items() if v is not None})
    print("[selftest] R2-c 사본 대표 텍스트 — 형식 우선(QA066 재발 방지) 통과")


def _selftest_query_log():
    """OP6 — do_search가 output/qa_log/qa_log.jsonl(여기선 임시 폴더)에 호출자·질문·근거 id·지연을 남기는지(PG 없는
    로컬 묶음도) · MCP_QUERY_LOG=0이면 아무것도 안 남는지(바이트 동일 — 파일 자체가 생기지 않음)."""
    import tempfile

    from mcp_server.services.search import qa_log

    d = pgfix.mk_bundle(
        [{"file_path": "x.txt", "file_name": "x.txt", "file_sha256": "8" * 64, "doc_format": ".txt"}],
        [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "단가는 100 USD",
                "n_terms": 3,
                "bbox": None,
                "section": None,
            }
        ],
    )
    logdir = Path(tempfile.mkdtemp())
    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d), MCP_QUERY_LOG_DIR=str(logdir))  # 설정 객체 덮기(S7d)
    tok = CALLER.set("mcp:selftest")
    try:
        do_search("단가는?", k=3)
        recs = [json.loads(x) for x in qa_log.log_path().read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 1 and recs[0]["question"] == "단가는?" and recs[0]["asked_by"] == "mcp:selftest", recs
        assert recs[0]["hits"] and recs[0]["hits"][0]["via"] == "k", recs[0]["hits"]  # 근거 via(검색 방법) 남음

        with mc.senv(MCP_QUERY_LOG="0"):
            do_search("단가는?", k=3)
            recs2 = qa_log.log_path().read_text(encoding="utf-8").splitlines()
            assert len(recs2) == 1, recs2  # 끔 — 더 안 늘어남(새 줄 없음)
    finally:
        CALLER.reset(tok)
        _env.close()
        _STATE.clear()
    print("[selftest] OP6 — 질의 기록(output/qa_log, 호출자·질문·근거 id·지연) · MCP_QUERY_LOG=0이면 기록 없음 통과")


def _selftest_evidence_gate():
    """R3(AD42) — found/weak/none·근거별 low_score 계산·표시."""
    ev_found = [{"text": "계약 C-001 금액은 100 USD", "score": 0.9}]
    assert evidence_status("C-001 계약 금액은?", ev_found, min_score=0.1) == ("found", [False])
    ev_off_topic = [{"text": "관련 없는 내용", "score": 0.9}]  # 핵심어(C-001) 없음 → weak
    assert evidence_status("C-001 계약 금액은?", ev_off_topic, min_score=0.1) == ("weak", [False])
    ev_low = [{"text": "계약 C-001 금액은 100 USD", "score": 0.01}]  # 점수 문턱 미달 → weak·low_score
    assert evidence_status("C-001 계약 금액은?", ev_low, min_score=0.1) == ("weak", [True])
    assert evidence_status("C-001 계약 금액은?", [], min_score=0.1) == ("none", [])
    assert evidence_status("아무 질문", ev_found, min_score=None) == ("found", [None])  # 문턱 없으면 low_score 안 매김

    sha = "9" * 64
    d = pgfix.mk_bundle(
        [{"file_path": "x.txt", "file_name": "x.txt", "file_sha256": sha, "doc_format": ".txt"}],
        [
            {
                "doc": 0,
                "seq": 0,
                "page": 1,
                "line_start": 1,
                "line_end": 1,
                "chunk_text": "단가는 100 USD",
                "n_terms": 3,
                "bbox": None,
                "section": None,
            }
        ],
    )
    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        none = do_search("색인에 없는 XYZ999-계약은?", k=3)  # BM25 0건
        assert none["evidence_status"] == "none", none

        with mc.senv(SEARCH_MIN_SCORE="99999"):  # 무조건 문턱 미달
            weak = do_search("단가는?", k=3)
            assert weak["evidence_status"] == "weak", weak
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] R3 근거 게이트 — found/weak/none·근거별 low_score 통과")


def _selftest_search_client_arg():
    """AD38 — do_search(client=...)가 검색에 전달되는지(MCP 계층 통합 확인). PG 저장소(mc-01 — 저장소는 PG 하나)에서
    client는 하드 필터 범위(2026-10-20 통합 search, _hard_filter_scope)라 SEARCH_CLIENT_HARD와 무관하게 다른 고객은 근거에서
    완전히 빠진다(옛 '꺼짐이면 둘 다 나옴'은 범위를 못 정하던 로컬 묶음 저장소만의 동작)."""
    docs = [
        {"file_path": "a.txt", "file_name": "a.txt", "file_sha256": "a" * 64, "doc_format": ".txt", "client": "Acme Co"},
        {"file_path": "b.txt", "file_name": "b.txt", "file_sha256": "b" * 64, "doc_format": ".txt", "client": "Other Co"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가는 100 USD",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    d = pgfix.mk_bundle(docs, chunks)
    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        with mc.senv(SEARCH_CLIENT_HARD=None):
            off = do_search("단가는?", k=5, client="Acme Co")
            assert {e["file_name"] for e in off["evidence"]} == {"a.txt"}, off["evidence"]  # 꺼짐도 하드 필터 범위(PG)
            assert off["filter"] == {"client": "Acme Co"} and off["scope_docs"] == 1, off

        with mc.senv(SEARCH_CLIENT_HARD="1"):
            on = do_search("단가는?", k=5, client="Acme Co")
            assert {e["file_name"] for e in on["evidence"]} == {"a.txt"}, on["evidence"]  # 켬 — Other Co는 완전히 빠짐
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] AD38 do_search(client=) — PG 하드 필터 범위로 다른 고객 제외(SEARCH_CLIENT_HARD 꺼짐/켬 둘 다) 통과")


def _selftest_entity_split():
    """BR23 — 비교 질문(고객 2명이 같이 나옴)에서 한쪽 고객 문서 3개가 점수를 다 차지해 다른 쪽 고객 문서 1개가
    top-k 밖으로 밀리는 재현(a1~a3=Acme Co, b1=Beta Inc, 질문 용어는 a쪽과 더 많이 겹침).
    고객별 하위 검색(search_svc._gather)이 b1을 끌어와 근거에 포함."""
    docs = [
        {"file_path": f"a{i}.txt", "file_name": f"a{i}.txt", "file_sha256": str(i) * 64, "doc_format": ".txt", "client": "Acme Co"}
        for i in range(1, 4)
    ] + [{"file_path": "b1.txt", "file_name": "b1.txt", "file_sha256": "b" * 64, "doc_format": ".txt", "client": "Beta Inc"}]
    chunks = [
        {
            "doc": i - 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "단가 비교 안내",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(1, 4)
    ] + [{"doc": 3, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "chunk_text": "단가", "n_terms": 1, "bbox": None, "section": None}]
    d = pgfix.mk_bundle(docs, chunks)
    q = "Acme Co와 Beta Inc 중 단가 비교 안내 문서를 찾아줘."  # '문서를 찾아'(FIND_DOC_RE) — 집계 경로로 안 새게(aggregate.py 기존 규칙)
    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d))  # 설정 객체 덮기(S7d)
    try:
        on = do_search(q, k=2)
        assert "b1.txt" in {e["file_name"] for e in on["evidence"]}, on["evidence"]  # Beta Inc 근거가 끌려옴
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] BR23 엔티티 분해 — 고객 2명 비교 질문의 한쪽 고객 누락을 하위 검색으로 보정 통과")


def _selftest_br50_client_scope():
    """BR50 — 고객 범위 단일 규칙(clientscope.py) 종단 점검. 합성 2고객 묶음(Acme Co·Beta Inc)으로:
    꺼짐(기본, SEARCH_CLIENT_HARD 미설정)이면 client 인자를 줘도 core 검색·개념(concept)·그림(image)·집계(aggregate)·
    키 기반 단건 조회(get_document·get_image·lookup_term) 전부 바이트 동일(둘 다 그대로 나옴, 알려진 한계 — I류 도구는
    client를 안 줘도 바이트 동일) · SEARCH_CLIENT_HARD=1 + client="Acme Co" 명시면 다른 고객(Beta Inc) 근거·그림·
    구조화 집계 행이 전부 빠지고, 키 조회는 거부(error)된다."""
    import csv

    sha_a, sha_b = "a" * 64, "b" * 64
    docs = [
        {
            "file_path": "a.txt",
            "file_name": "a.txt",
            "file_sha256": sha_a,
            "doc_format": ".txt",
            "client": "Acme Co",
            "contract_no": "C-A01",
            "meta_confirmed": True,
            "contract": {"amount": 1000, "currency": "USD"},
        },
        {
            "file_path": "b.txt",
            "file_name": "b.txt",
            "file_sha256": sha_b,
            "doc_format": ".txt",
            "client": "Beta Inc",
            "contract_no": "C-B01",
            "meta_confirmed": True,
            "contract": {"amount": 500, "currency": "USD"},
        },
    ]
    chunks = [
        {
            "doc": 0,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정 Acme 전용",
            "n_terms": 5,
            "bbox": None,
            "section": None,
        },
        {
            "doc": 1,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "바이러스 불활화 공정 Beta 전용",
            "n_terms": 5,
            "bbox": None,
            "section": None,
        },
    ]
    d = pgfix.mk_bundle(docs, chunks)
    (d / "concept_chunk.jsonl").write_text(
        "\n".join(
            json.dumps(x)
            for x in [
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_a}:0", "count": 3},
                {"concept_id": "PROC.VI", "chunk_key": f"{sha_b}:0", "count": 2},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
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
                "concept_id": "PROC.VI",
                "canonical": "Viral Inactivation",
                "category": "process",
                "synonyms": "바이러스 불활화",
                "abbreviations": "VI",
                "weak_synonyms": "",
                "broader": "",
                "related": "",
                "context_required": "",
                "case_sensitive": "Y",
                "definition_ko": "",
                "definition_en": "",
                "source": "",
                "owner": "",
                "status": "approved",
                "updated": "",
            }
        )

    _STATE.clear()
    # 설정 객체 덮기(S7d) — GLOSSARY_DIR도 설정 객체(op-09) · SEARCH_CLIENT_HARD=None은 옛 pop
    _env = pgfix.use(d, MCP_BUNDLE=str(d), GLOSSARY_DIR=str(gdir), SEARCH_CLIENT_HARD=None)
    _hard = None
    try:
        # client 없음 — 두 고객 근거 다 나옴 · client 명시는 PG에서 하드 필터 범위(꺼짐이어도 Beta Inc 빠짐 — 2026-10-20 통합 search)
        both = do_search("바이러스 불활화 공정", k=5)
        assert {e.get("file_name") for e in both["evidence"] if e.get("file_name")} >= {"a.txt", "b.txt"}, both["evidence"]
        off = do_search("바이러스 불활화 공정", k=5, client="Acme Co")
        assert {e.get("file_name") for e in off["evidence"] if e.get("file_name")} == {"a.txt"}, off["evidence"]

        # 켬 — SEARCH_CLIENT_HARD=1 + client="Acme Co" 명시
        _hard = mc.senv(SEARCH_CLIENT_HARD="1")
        on = do_search("바이러스 불활화 공정", k=5, client="Acme Co")
        assert "b.txt" not in {e.get("file_name") for e in on["evidence"]}, on["evidence"]  # core·concept 둘 다 빠짐(F)
        assert "a.txt" in {e.get("file_name") for e in on["evidence"]}, on["evidence"]  # 자기 고객 근거는 그대로

    finally:
        if _hard is not None:
            _hard.close()
        _env.close()
        _STATE.clear()
    print(
        "[selftest] BR50 — clientscope 종단 점검: 꺼짐(client만 줘도) 바이트 동일(core·concept·image·"
        "get_document·get_image·lookup_term) · SEARCH_CLIENT_HARD=1+client 명시면 다른 고객 근거·그림·구조화 집계 "
        "전부 제외, 키 조회는 거부 · client 안 주면(I류) 알려진 한계로 그대로 통과"
    )


def _selftest_evidence_rdb_meta():
    """AD44 — do_search 근거(_evidence)에 RDB manifest 메타(doc_type·supersedes_doc_id·is_deleted·contract_id·updated_at·
    company, version은 있으면 우선) 붙는지 — 실제 synth-meta-rdb 표(contract_sjm_mab_2025 행, pipeline import 안 함).
    manifest가 그 문서를 모르면(두 번째 문서) 칸 자체가 없고, manifest가 아예 없으면 바이트 동일(새 칸 0개)."""
    import csv

    base = ROOT / "valid_env" / "edw" / "meta_rdb" / "doc_location.csv"
    if not base.exists():  # 이미지에는 예시 데이터 없음 → 건너뜀(10-14)
        print(f"[selftest] AD44 근거 RDB 메타 건너뜀 — 예시 표 없음({base})")
        return
    with open(base, encoding="utf-8-sig", newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["doc_id"] == "contract_sjm_mab_2025")

    man_doc = "contract_sjm_mab_2025"
    other_doc = "no_manifest_doc"
    docs = [
        {"file_path": man_doc, "file_name": man_doc, "file_sha256": "c" * 64, "doc_format": ".txt"},
        {"file_path": other_doc, "file_name": other_doc, "file_sha256": "d" * 64, "doc_format": ".txt"},
    ]  # PG 근거의 file_name은 file_path의 마지막 조각(v_chunk_source) — manifest 키(file_name)와 맞게 확장자 없이
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 1,
            "chunk_text": "계약기준금액 안내",
            "n_terms": 2,
            "bbox": None,
            "section": None,
        }
        for i in range(2)
    ]
    d = pgfix.mk_bundle(docs, chunks)

    man_path = d / "manifest.jsonl"
    man_path.write_text(
        json.dumps(
            {
                "file_name": man_doc,
                "doc_type": row["doc_type"],
                "version": row["version"],
                "supersedes_doc_id": row["supersedes_doc_id"],
                "contract_id": row["contract_id"],
                "updated_at": row["updated_at"],
                "company_id": row["company_id"],
                "is_deleted": row["is_deleted"].strip().lower() in ("1", "true", "t"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d), MCP_MANIFEST=str(man_path))  # 설정 객체 덮기(S7d)
    try:
        on = do_search("계약기준금액은?", k=5)
        by_name = {e["file_name"]: e for e in on["evidence"]}
        assert set(by_name) == {man_doc, other_doc}, by_name
        assert by_name[man_doc]["version"] == row["version"], by_name  # version은 manifest 값만(AD44)
        assert by_name[other_doc]["version"] is None and all(e["superseded"] is None for e in on["evidence"]), (
            by_name
        )  # mc-05 — 본문 추정값은 안 나감
        for e in on["evidence"]:
            assert tuple(e) == EVIDENCE_KEYS, e  # 근거는 12칸만(mc-16 — manifest의 다른 칸은 계약 밖)
    finally:
        _STATE.clear()
        _env.close()
    print("[selftest] AD44 _evidence — manifest version 우선 · 근거 12칸 통과")


def _selftest_contract():
    """mc-16 — 운영 search 계약(사례 표 한 곳): question 필수 · k 상한 50 · 맨 위 5칸·근거 12칸 · 거르기(AND, 목록은 OR,
    -test 별칭, 등록 시각 KST·날짜만이면 그날 전체, FAQ_group은 FAQ 적재 전 늘 0건) · 모르는 인자 무시 · 맞는 것 없으면 빈 결과."""
    docs = [
        {
            "file_path": "s1.txt",
            "client": "Acme",
            "source_system": "SFDC",
            "sf_op_id": "006A",
            "doc_class": "RFP",
            "division": "DS",
            "created_at": "2025-03-01T10:00:00+09:00",
        },
        {
            "file_path": "s2.txt",
            "source_system": "SFDC",
            "sf_op_id": "006B",
            "doc_class": "RFI",
            "division": "DP",
            "created_at": "2025-03-02T23:30:00+09:00",
        },
        {"file_path": "l1.txt", "source_system": "LAS", "doc_class": "MSA", "division": "DS"},
    ]
    chunks = [
        {
            "doc": i,
            "seq": 0,
            "page": 1,
            "line_start": 1,
            "line_end": 2,
            "chunk_text": "단가는 100 USD",
            "n_terms": 3,
            "bbox": None,
            "section": None,
        }
        for i in range(3)
    ]
    d = pgfix.mk_bundle(docs, chunks)
    _STATE.clear()
    _env = pgfix.use(d, MCP_BUNDLE=str(d))
    names = lambda o: sorted(e["file_name"] for e in o["evidence"])
    cases = [  # (거르기, 기대 문서, 기대 scope_docs)
        ({}, ["l1.txt", "s1.txt", "s2.txt"], None),
        ({"source_system": "SFDC"}, ["s1.txt", "s2.txt"], 2),
        ({"source_system": "SFDC-test"}, ["s1.txt", "s2.txt"], 2),  # G4 — -test 별칭
        ({"sf_op_id": ["006A", "006B"]}, ["s1.txt", "s2.txt"], 2),  # 목록 = OR
        ({"source_system": "SFDC", "division": "DS"}, ["s1.txt"], 1),  # 다른 거르기 = AND
        ({"source_system": "LAS", "doc_class": "RFP"}, [], 0),  # 분류는 제 원천 안에서만 — 엇갈리면 0건(오류 아님)
        ({"doc_class": "MSA"}, ["l1.txt"], 1),
        ({"division": "D"}, [], 0),  # 부분 값은 0건(정확 일치)
        ({"created_since": "2025-03-02"}, ["s2.txt"], 1),  # 날짜만 = 그날 00:00 KST부터
        ({"created_until": "2025-03-01"}, ["s1.txt"], 1),  # 날짜만 until = 그날 전체(created_at 없는 l1은 빠짐)
        ({"created_since": "2025-03-01T11:00:00+09:00"}, ["s2.txt"], 1),
        ({"created_since": "2025-03-01T02:00:00Z"}, ["s2.txt"], 1),  # 다른 시간대 = 11:00 KST
        ({"created_until": "20250301"}, ["s1.txt"], 1),  # 날짜만(기본 꼴) — 그날 전체
        ({"client": "Acme"}, ["s1.txt"], 1),
        ({"client": "A_me"}, [], 0),  # _는 와일드카드 아님(정확 일치)
        ({"client": "cm", "client_like": True}, ["s1.txt"], 1),
        ({"FAQ_group": "DP"}, [], 0),
        ({"year": 2025}, ["l1.txt", "s1.txt", "s2.txt"], None),  # 모르는 인자 무시
    ]
    try:
        assert do_search("") == {"error": M.NO_QUESTION} and do_search("  ") == {"error": M.NO_QUESTION} and do_search(None)["error"]
        assert "error" in do_search("단가는?", created_since="2025/03/01")  # 날짜 형식 틀림
        for filt, want, scope in cases:
            o = do_search("단가는?", k=999, **filt)  # k 상한 50으로 줄임(오류 아님)
            assert names(o) == want, (filt, o)
            keys = ("question", "evidence", "evidence_status") + (("filter", "scope_docs") if scope is not None else ())
            assert tuple(o) == keys and set(keys) <= set(SEARCH_TOP_KEYS), (filt, list(o))
            assert all(tuple(e) == EVIDENCE_KEYS for e in o["evidence"]), (filt, o["evidence"])
            assert scope is None or o["scope_docs"] == scope, (filt, o)
            assert want or o["evidence_status"] == "none", (filt, o)
        o = do_search("단가는?", k=1, source_system="SFDC-test")
        assert len(o["evidence"]) == 1 and o["filter"] == {"source_system": "SFDC"}, o  # 정규화한 메아리
        e = o["evidence"][0]
        assert e["line"] and e["chunk_key"] and e["file_path"].endswith(".txt") and e["text"], e
    finally:
        _env.close()
        _STATE.clear()
    print(f"[selftest] mc-16 search 계약 — 사례 {len(cases)}개(거르기·빈 결과·모르는 인자)·question 필수·k 상한·5칸·12칸 통과")


def test_main():  # 옛 main.py selftest가 부르던 순서(이 모듈 몫만) — search_svc.py엔 __main__이 없었음
    from common.core.paths import STACK_FILE
    from common.store.db import cfgfile

    cfgfile._CACHE.setdefault(
        "stack", cfgfile.read_file("stack", STACK_FILE)
    )  # test_mcp_main과 같은 준비(S8b — 이미지 selftest엔 PG가 없어 판 표 대신 파일, S9 따로 사례가 되며 더함)
    with patch.object(M.CFG, "DEFAULT_METHODS", ["bm25"]):  # 검색 길은 서버 설정만(mc-16) — 시험은 임베딩 없이 bm25
        _cases()


def _cases():
    _selftest_contract()
    _selftest_evidence_gate()
    _selftest_search_client_arg()
    _selftest_entity_split()
    _selftest_br50_client_scope()
    _selftest_evidence_rdb_meta()
    _selftest_query_log()
    _selftest_copy_group()
    _selftest_copy_group_rep_text()
