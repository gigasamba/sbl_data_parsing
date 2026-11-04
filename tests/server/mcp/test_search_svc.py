"""mcp_server.services.search.search_svc 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.search_svc`."""

import json
from pathlib import Path
from unittest.mock import patch

from mcp_server import config as mc
from mcp_server.schemas.evidence import EVIDENCE_KEYS, SEARCH_TOP_KEYS
from mcp_server.services.search import search_svc as M
from mcp_server.services.search.evidence_shape import evidence_status
from mcp_server.services.search.server_state import _STATE
from tests.server.mcp import pgfix  # mc-01(11-01) — 검색은 PG 하나: 묶음을 SQLite 대역에 적재(임시 폴더, 실 PG 안 닿음)


def do_search(question=None, k=8, **filters):
    """시험 기본 원천 = Other(pgfix가 source_system 없는 문서를 other 스키마에 넣음 — pl-28) · source_system 없이 부르는 사례는 M.do_search로."""
    filters.setdefault("source_system", "Other")
    return M.do_search(question, k, **filters)


ROOT = (
    Path(M.__file__).resolve().parents[3]
)  # 옛 main.py의 ROOT(= mcp_server/의 부모, 저장소 루트)와 같은 값 — selftest만 씀(옛 search_svc.py의 줄 — `__file__`은 모듈 것으로)


def _selftest_copy_group():
    """R2-c 요건① — 같은 메일의 다른 형식(.eml/.msg)이 evidence 슬롯을 독점하지 않고 한 슬롯(대표) + variants로
    묶이는지."""

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
    _STATE.clear()
    _env = pgfix.use(d)
    try:
        out = do_search("단가는?", k=5)
        assert [e["file_name"] for e in out["evidence"]] == ["MAIL-X.eml"], out["evidence"]
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] R2-c 사본 그룹 — 한 슬롯 통과")


def _selftest_copy_group_rep_text():
    """engine-qa CONCERN(QA066) 재발 방지 — 최상위 순위가 이미지(OCR) 청크라 배치 수 문장이 빠진 실제 사례를
    재현: mailshot(.png)이 더 짧아 BM25 1위로 뽑혀도, 대표 슬롯(자리는 그대로 1위)의 내용은 형식이 더 믿을만한
    eml·msg 중에서 고르고(QA066에선 eml) 그 안에 빠진 문장(배치)이 있는지. 대표 자신의 파일명은 variants에
    없어야(요건②)."""

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
    _STATE.clear()
    _env = pgfix.use(d)
    try:
        out = do_search("단가는?", k=5)
        rep = out["evidence"][0]
        assert rep["file_name"] in ("MAIL-X.eml", "MAIL-X.msg"), rep  # ① 대표 텍스트는 형식 우선(이미지 아님)
        assert "배치" in rep["text"], rep["text"]  # ① 이미지에만 없던 문장이 대표 텍스트에 있음
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] R2-c 사본 대표 텍스트 — 형식 우선(QA066 재발 방지) 통과")


def _selftest_evidence_gate():
    """R3(AD42) — found/weak/none(핵심어가 근거 원문에 있는지)."""
    ev_found = [{"text": "계약 C-001 금액은 100 USD", "score": 0.9}]
    assert evidence_status("C-001 계약 금액은?", ev_found) == "found"
    ev_off_topic = [{"text": "관련 없는 내용", "score": 0.9}]  # 핵심어(C-001) 없음 → weak
    assert evidence_status("C-001 계약 금액은?", ev_off_topic) == "weak"
    assert evidence_status("C-001 계약 금액은?", []) == "none"
    assert evidence_status("아무 질문", ev_found) == "found"  # 핵심어 없는 질문

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
    _env = pgfix.use(d)  # 설정 객체 덮기(S7d)
    try:
        none = do_search("색인에 없는 XYZ999-계약은?", k=3)  # BM25 0건
        assert none["evidence_status"] == "none", none
    finally:
        _env.close()
        _STATE.clear()
    print("[selftest] R3 근거 게이트 — found/weak/none 통과")


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
    _env = pgfix.use(d, MCP_MANIFEST=str(man_path))  # 설정 객체 덮기(S7d)
    try:
        on = do_search("계약기준금액은?", k=5)
        by_name = {e["file_name"]: e for e in on["evidence"]}
        assert set(by_name) == {man_doc, other_doc}, by_name
        assert by_name[man_doc]["version"] == row["version"], by_name  # version은 manifest 값만(AD44)
        assert by_name[other_doc]["version"] is None and all(e["superseded"] is None for e in on["evidence"]), (
            by_name
        )  # mc-05 — 본문 추정값은 안 나감
        for e in on["evidence"]:
            assert tuple(e) == EVIDENCE_KEYS, e  # 근거는 13칸만(mc-16·pl-52 — manifest의 다른 칸은 계약 밖)
    finally:
        _STATE.clear()
        _env.close()
    print("[selftest] AD44 _evidence — manifest version 우선 · 근거 13칸 통과")


def _selftest_contract():
    """mc-16·pl-28 — search 계약(사례 표 한 곳): question 필수 · source_system 필수·값 하나(원천 스키마 고르기, G20 — 운영과 다름) · k 상한 50 ·
    맨 위 5칸·근거 13칸 · 거르기(AND, 목록은 OR, -test 별칭, 등록 시각 KST·날짜만이면 그날 전체, 고객은 client_edw 정확 일치만) ·
    그 원천 스키마에 없는 칸 거르기는 0건 · 모르는 인자 무시 · 맞는 것 없으면 빈 결과."""
    docs = [
        {
            "file_path": "SFDC/u1/s1.txt",
            "client_edw": "Acme",
            "clients": ["Beta"],
            "source_system": "SFDC",
            "attrs": {"sf_op_id": "006A", "service_type": "CDO"},
            "doc_class": "RFP",
            "created_at": "2025-03-01T10:00:00+09:00",
        },
        {
            "file_path": "SFDC/u2/s2.txt",
            "source_system": "SFDC",
            "attrs": {"sf_op_id": "006B", "service_type": "ADC"},
            "doc_class": "RFI",
            "created_at": "2025-03-02T23:30:00+09:00",
        },
        {"file_path": "LAS/u3/l1.txt", "source_system": "LAS", "doc_class": "MSA", "attrs": {"contract_id": "M-1"}},
        {"file_path": "CRMS/u4/c1.txt", "source_system": "CRMS", "attrs": {"division": "DS", "contract_id": "C-9"}, "client_edw": "Acme"},
        {"file_path": "FAQ/u5/f.xlsx", "source_system": "FAQ"},
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
        for i in range(5)
    ]
    chunks[4]["faq_group"] = "DP"
    d = pgfix.mk_bundle(docs, chunks)
    _STATE.clear()
    _env = pgfix.use(d)
    names = lambda o: sorted(e["file_name"] for e in o["evidence"])
    cases = [  # (거르기, 기대 문서, 기대 scope_docs)
        ({"source_system": "SFDC"}, ["s1.txt", "s2.txt"], 2),
        ({"source_system": "SFDC-test"}, ["s1.txt", "s2.txt"], 2),  # G4 — -test 별칭
        ({"source_system": ["SFDC"]}, ["s1.txt", "s2.txt"], 2),  # 목록이어도 값 하나면 됨
        ({"source_system": "SFDC", "sf_op_id": ["006A", "006B"]}, ["s1.txt", "s2.txt"], 2),  # 목록 = OR
        ({"source_system": "SFDC", "service_type": "CDO", "doc_class": "RFP"}, ["s1.txt"], 1),  # 다른 거르기 = AND
        ({"source_system": "LAS", "doc_class": "RFP"}, [], 0),  # 분류는 제 원천 안에서만 — 엇갈리면 0건(오류 아님)
        ({"source_system": "LAS", "doc_class": "MSA", "contract_id": "M-1"}, ["l1.txt"], 1),
        ({"source_system": "CRMS", "division": "DS", "contract_id": "C-9"}, ["c1.txt"], 1),
        ({"source_system": "CRMS", "sf_op_id": "006A"}, [], 0),  # crms 스키마에 없는 칸 — 0건
        ({"source_system": "SFDC", "division": "DS"}, [], 0),  # division은 crms만
        ({"source_system": "SFDC", "created_since": "2025-03-02"}, ["s2.txt"], 1),  # 날짜만 = 그날 00:00 KST부터
        ({"source_system": "SFDC", "created_until": "2025-03-01"}, ["s1.txt"], 1),  # 날짜만 until = 그날 전체
        ({"source_system": "SFDC", "created_since": "2025-03-01T02:00:00Z"}, ["s2.txt"], 1),  # 다른 시간대 = 11:00 KST
        ({"source_system": "SFDC", "client": "Acme"}, ["s1.txt"], 1),  # client_edw 정확 일치
        ({"source_system": "SFDC", "client": "Beta"}, [], 0),  # 본문 고객 라벨(clients_doc)은 안 봄(C6)
        ({"source_system": "SFDC", "client": "A_me"}, [], 0),  # _는 와일드카드 아님
        ({"source_system": "SFDC", "client": "cm", "client_like": True}, ["s1.txt"], 1),
        ({"source_system": "CRMS", "client": "Acme"}, ["c1.txt"], 1),
        ({"source_system": "FAQ", "FAQ_group": "DP"}, ["f.xlsx"], 1),  # faq.chunk.faq_group
        ({"source_system": "FAQ", "FAQ_group": "DS"}, [], 0),
        ({"source_system": "Other"}, [], 0),
        ({"source_system": "SFDC", "year": 2025}, ["s1.txt", "s2.txt"], 2),  # 모르는 인자 무시
        ({"source_system": "SFDC", "attrs": {"service_type": "CDO"}}, ["s1.txt"], 1),  # pl-52 — attrs 키 그대로
        (
            {"source_system": "SFDC", "attrs": {"sf_op_id": ["006A", "006B"]}, "doc_class": "RFI"},
            ["s2.txt"],
            1,
        ),  # 목록 OR · 이름 거르기와 AND
        ({"source_system": "SFDC", "attrs": {"project_code__c": "P-1"}}, [], 0),  # 옛 이름 project_id의 키 — 값 없음 0건
        ({"source_system": "LAS", "attrs": {"contract_id": "M-1", "doc_class": "MSA"}}, ["l1.txt"], 1),  # doc_class도 attrs 키
        ({"source_system": "CRMS", "attrs": {"division": "XX"}}, [], 0),
        ({"source_system": "SFDC", "attrs": {}}, ["s1.txt", "s2.txt"], 2),  # 빈 attrs = 거르기 없음
        ({"source_system": "SFDC", "attrs": {"sf_op_id": " 006A  "}, "doc_class": " RFP "}, ["s1.txt"], 1),  # 앞뒤 공백 뺌(적재 값과 같게)
        ({"source_system": "SFDC", "attrs": {"sf_op_id": ["  ", "006B "]}}, ["s2.txt"], 1),  # 공백만 = 빈 값
    ]
    try:
        assert M.do_search("") == {"error": M.NO_QUESTION} and M.do_search("  ", source_system="SFDC") == {"error": M.NO_QUESTION}
        assert M.do_search("단가는?") == {"error": M.NO_SOURCE} and M.do_search("단가는?", source_system=["SFDC", "LAS"]) == {
            "error": M.NO_SOURCE
        }
        assert "error" in M.do_search("단가는?", source_system="SFDC", created_since="2025/03/01")  # 날짜 형식 틀림
        bad = [  # pl-52 — attrs 모르는 키·꼴 틀림은 오류(조용한 0건 아님) · 오류 글에 그 원천의 키 목록
            (
                {"source_system": "SFDC", "attrs": {"title": "x"}},
                ["title", "sf_op_id", "project_code__c", "doc_class"],
            ),  # 힌트 키는 거르기 아님
            ({"source_system": "CRMS", "attrs": {"sf_op_id": "006A"}}, ["sf_op_id", "division", "contract_id"]),  # 다른 원천의 키
            ({"source_system": "FAQ", "attrs": {"x": "1"}}, ["없음"]),
            ({"source_system": "SFDC", "attrs": "sf_op_id=006A"}, ["{키: 값"]),
        ]
        for filt, words in bad:
            err = M.do_search("단가는?", **filt).get("error") or ""
            assert all(w in err for w in words), (filt, err)
        with mc.senv(EDW_CHAIN_FILE=str(Path(pgfix.__file__).with_name("nowhere.yaml"))):  # 사슬 파일 설정 — 없는 파일은 오류
            assert "사슬 설정 파일을 못 읽음" in M.do_search("단가는?", source_system="SFDC").get("error", ""), "chain"
        for filt, want, scope in cases:
            o = M.do_search("단가는?", k=999, **filt)  # k 상한 50으로 줄임(오류 아님)
            assert names(o) == want, (filt, o)
            assert tuple(o) == SEARCH_TOP_KEYS[:3] + ("filter", "scope_docs") and o["scope_docs"] == scope, (filt, o)
            assert all(tuple(e) == EVIDENCE_KEYS for e in o["evidence"]), (filt, o["evidence"])
            assert want or o["evidence_status"] == "none", (filt, o)
        o = M.do_search("단가는?", k=1, source_system="SFDC-test", client="Acme")
        assert o["filter"] == {"source_system": "SFDC", "client": "Acme"}, o  # 정규화한 메아리
        e = o["evidence"][0]
        assert (
            e["line"]
            and e["chunk_key"] == f"{e['chunk_key'].split(':')[0]}:0"
            and e["file_path"] == "SFDC/u1/s1.txt"
            and e["client"] == "Acme"
        ), e
        none5 = dict.fromkeys(("sf_op_id", "sf_op_name", "project_code__c", "service_type", "contract_date"))
        assert e["attrs"] == {**none5, "sf_op_id": "006A", "service_type": "CDO"} and e["contract_no"] is None, (
            e
        )  # 근거 attrs = evidence 키
        o = M.do_search("단가는?", source_system="LAS", attrs={"contract_id": "M-1"})
        assert o["filter"] == {"source_system": "LAS", "attrs": {"contract_id": "M-1"}}, o
        e = o["evidence"][0]
        assert e["contract_no"] == "M-1" and e["attrs"] == {"contract_id": "M-1", "contract_date": None}, e  # contract_no = contract_id 키
        e = M.do_search("단가는?", source_system="FAQ")["evidence"][0]
        assert e["attrs"] is None and e["contract_no"] is None, e  # 근거 키가 없는 원천은 attrs null
    finally:
        _env.close()
        _STATE.clear()
    print(
        f"[selftest] mc-16·pl-28·pl-52 search 계약 — 사례 {len(cases)}개(원천 스키마·거르기·attrs·빈 결과·모르는 인자)·attrs 오류 {len(bad)}개·question·source_system 필수·5칸·13칸 통과"
    )


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
    _selftest_evidence_rdb_meta()
    _selftest_copy_group()
    _selftest_copy_group_rep_text()
    _selftest_search_attrs()


def _selftest_search_attrs():
    """pl-52 — edw_meta 인자 없음의 search_attrs: 원천별 거르기 이름 → attrs 키·근거 키(사슬 파일 그대로) · 인자가 있으면 안 붙음."""
    from mcp_server.services import edw_calls

    sa = edw_calls.search_attrs()
    assert sorted(sa) == ["CRMS", "FAQ", "LAS", "Other", "SFDC"], sa
    assert sa["SFDC"]["filter"]["project_id"] == "project_code__c" and sa["SFDC"]["filter"]["doc_class"] == "doc_class", sa["SFDC"]
    assert sa["SFDC"]["evidence"] == ["sf_op_id", "sf_op_name", "project_code__c", "service_type", "contract_date"], sa["SFDC"]
    assert sa["CRMS"]["filter"] == {"contract_id": "contract_id", "division": "division"}, sa
    assert sa["CRMS"]["attrs"] == ["contract_id", "division"] and sa["FAQ"] == {"filter": {}, "attrs": [], "evidence": []}, sa
    assert "search_attrs" not in edw_calls.do_edw_meta(schema="NOPE")
    # P2-8 — 사슬의 filter 이름이 search 인자가 아니면 filter에 안 나오고 attrs 키로만
    from common.store import edw_chain as EC
    from mcp_server.services.search import search_svc

    ch = EC.load()
    ch["crms"]["fields"]["prod_name"]["filter"] = "product"
    with patch.object(search_svc, "chain", lambda: ch):
        c = edw_calls.search_attrs()["CRMS"]
    assert "product" not in c["filter"] and "prod_name" in c["attrs"], c
    # 사용자 11-04 — CRMS 영업 기회(sf_op_id)는 지금 사슬에 없어 0건 · 사슬에 filter 칸을 더하면 코드 수정 없이 이름 거르기·attrs·search_attrs가 함께 열림
    h = {"source_system": "CRMS", "sf_op_id": "OP1"}
    ch = EC.load()
    assert search_svc._scope_sql(h, "crms", EC.filters(ch, "crms")) == (" WHERE 1 = 0", [])
    ch["crms"]["fields"]["sf_op_id"] = {"from": "map.rm_contract_code", "filter": "sf_op_id", "evidence": True}
    fm = EC.filters(ch, "crms")
    assert search_svc._scope_sql(h, "crms", fm) == (" WHERE (attrs @> %s::jsonb)", ['{"sf_op_id": "OP1"}'])
    assert search_svc._norm_attrs({"sf_op_id": "OP1"}, "CRMS", fm) == ({"sf_op_id": "OP1"}, None)
    with patch.object(search_svc, "chain", lambda: ch):
        c = edw_calls.search_attrs()["CRMS"]
    assert c["filter"]["sf_op_id"] == "sf_op_id" and "sf_op_id" in c["attrs"] and "sf_op_id" in c["evidence"], c
    # 요약이 오류면 search_attrs를 붙이지 않음 · 성공이면 붙임
    from mcp_server.services import edw_meta as EM

    with patch.object(EM, "lookup", lambda *a: {"error": "x"}):
        assert edw_calls.do_edw_meta() == {"error": "x"}
    with patch.object(EM, "lookup", lambda *a: {"schemas": []}):
        assert edw_calls.do_edw_meta() == {"schemas": [], "search_attrs": sa}
