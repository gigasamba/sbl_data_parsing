"""mcp_server.services.search.aggregate 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.services.search.aggregate`."""

import json
import re
from pathlib import Path

from common.core.paths import GLOSSARY_ROOT
from common.core.terms import _aliases
from common.store import structdb as SDB
from mcp_server import config as mc
from mcp_server.services.search.aggregate import (
    _AGG_VOCAB_DEFAULT,
    BATCH_Q,
    _load_agg_vocab,
    _table_cell_tokens,
    detect,
    doc_link_list,
    doc_link_question,
    fx_evidence_text,
    mixed_currencies,
    run,
    struct,
    struct_context,
    table_cell_question,
    table_text,
)


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    _env_today = mc.senv(AGG_TODAY="2026-09-30")  # S7d — 설정 객체 덮기(os.environ 안 건드림), 끝에서 close()(실패하면 프로세스째 끝남)
    assert detect("고객사 Contoso Pharma와 맺은 서로 다른 계약 건수는 몇 건입니까?", {"Contoso Pharma"}, set())["kind"] == "count"
    assert detect("계약번호 D-2024-190의 품목 수량을 모두 더하면 총 수량(L)은?", set(), {"D-2024-190"})["kind"] == "sum"
    assert detect("계약 D-2024-190의 단가는?", {"Contoso Pharma"}, {"D-2024-190"}) is None
    al = {"Pfizer Inc.": ["화이자"]}
    p = detect(
        "우리가 준비한 화이자가 과거 3년 동안 계약한 계약 건수와 제품 종류, 제품 종류별 계약 배치 수를 정리해줘", {"Pfizer Inc."}, set(), al
    )
    assert p["kind"] == "table" and p["group"] == "modality" and p["window"] == ("2023-10-01", "2026-09-30")
    assert (
        detect(
            "Across all of Pfizer's contracts on file (not limited to the past 3 years), contract count per modality?",
            {"Pfizer Inc."},
            set(),
            al,
        )["window"]
        is None
    )
    assert detect("화이자가 최근 1년(2025-10-01~2026-09-30) 동안 체결한 계약 건수는?", {"Pfizer Inc."}, set(), al)["window"] == (
        "2025-10-01",
        "2026-09-30",
    )
    docs = [
        {
            "file_path": "a",
            "client": "Pfizer Inc.",
            "contract_no": "C-1",
            "meta_confirmed": True,
            "contract": {"modality": "mAb", "signed_on": "2024-01-01", "amount": 100.0, "currency": "USD", "batches": 2},
        },
        {
            "file_path": "b",
            "client": "Pfizer Inc.",
            "contract_no": "C-2",
            "meta_confirmed": True,
            "contract": {"modality": "ADC", "signed_on": "2021-01-01", "amount": 50.0, "currency": "USD", "batches": 1},
        },
        {"file_path": "q", "client": "Pfizer Inc.", "contract_no": "C-1", "meta_confirmed": False, "contract": {}},
    ]
    t = run("화이자의 제품 종류별 계약 건수·배치 수 합계·계약 금액 합계를 표로", docs, aliases=al)
    assert t["rows"] == [["ADC", 1, "1", "50 USD"], ["mAb", 1, "2", "100 USD"]] and t["totals"]["계약 건수"] == 2, t
    tt = table_text(t)  # BR40 — 제품 종류별 합계 행만으론 계약별 금액(C-1 100 USD·C-2 50 USD)이 안 보여 계약별 근거 행을 덧붙임
    assert "계약별 근거:" in tt and "C-1 | Pfizer Inc. | 100 USD | a" in tt and "C-2 | Pfizer Inc. | 50 USD | b" in tt, tt
    assert run("화이자 전체 계약 금액 합계는?", docs, aliases=al)["answer"] == "150 USD"
    lt = run("화이자가 최근 3년 동안 체결한 계약 건수와 총 계약 규모는?", docs, aliases=al)
    assert lt["rows"][0][0] == "C-1" and lt["totals"]["계약 건수"] == 1 and lt["totals"]["계약 금액 합계"] == "100 USD", lt
    assert "계약별 근거:" not in table_text(lt), table_text(
        lt
    )  # BR40 — 계약별 목록 표(columns[0]=="계약ID")는 이미 계약별이라 중복 안 붙임
    assert run("화이자가 최근 3년 체결한 계약 건수는?", docs, aliases=al)["answer"] == 1
    assert mixed_currencies(t) == set()  # BR43 — t는 통화가 전부 USD(단일) → no-op
    mixed_docs = docs + [
        {
            "file_path": "c",
            "client": "Beta Inc",
            "contract_no": "C-3",
            "meta_confirmed": True,
            "contract": {"modality": "mAb", "signed_on": "2024-01-01", "amount": 500000.0, "currency": "KRW", "batches": 1},
        }
    ]
    both = run("화이자와 Beta Inc 중 전체 계약 금액 합계가 더 큰 곳은?", mixed_docs, aliases=al)
    assert mixed_currencies(both) == {"USD", "KRW"}, both
    assert fx_evidence_text({"file_name": "fx.txt", "text": "환율 exchange rate: 1 USD = 1,350 KRW"}) is not None
    assert fx_evidence_text({"file_name": "x.txt", "text": "환율 리스크 관리 정책 — 수치 없음"}) is None  # '환율'만 있고 숫자 없음 → 거절
    assert fx_evidence_text({"file_name": "y.txt", "text": "단가는 100 USD"}) is None  # 환율 패턴 자체가 없음
    assert fx_evidence_text(None) is None and fx_evidence_text({}) is None
    assert detect("How many products does Pfizer Inc. have in production?", {"Pfizer Inc."}, set(), al) is None
    assert detect("화이자가 과거 3년 동안 계약한 계약 건수는?", {"Pfizer Inc."}, {"3", "Question"}, al)["target"] == {
        "client": "Pfizer Inc."
    }
    b = run("Excluding Pfizer contracts signed more than 3 years ago, how many contracts remain?", docs, aliases=al)
    assert b["rows"] == [["최근 3년 이내", 1], ["제외(2023-10-01 이전 체결)", 1]], b
    import tempfile

    f = Path(tempfile.mkdtemp()) / "roster.csv"
    f.write_text("name,aliases\n미르하제약(주),미르하;MIRHA\n", encoding="utf-8")
    with mc.senv(CLIENT_ROSTER=str(f)):  # 인계 파일(terms.py)도 설정 객체로 읽음(op-09)
        assert _aliases()["미르하제약(주)"] == ["MIRHA", "미르하"]  # 고객 명부 파일(CSV) 병합
    with mc.senv(GLOSSARY_DIR=str(GLOSSARY_ROOT)):
        al = _aliases()
        assert "화이자" in al["Pfizer Inc."] and "PFE" not in al["Pfizer Inc."]  # 사전 org_client 별칭 · 짧은 영문 약어 제외
    assert doc_link_question("계약 ID 없는 RFI 중 계약으로 이어진 것은?") and not doc_link_question("화이자 계약 건수는?")
    assert (
        "doc_contract_link 없음" in doc_link_list(SDB.open_backend(str(Path(tempfile.mkdtemp()) / "t.sqlite")))["note"]
    )  # PG 없으면 앞에 대체 note가 붙음(X1b)
    print("[selftest] 집계 질문 판별·계약 사실 추출·표 집계·로컬 저장소 연결 질문 판별 통과")

    # struct_context(L3-6, W18) — (a) 연결된 계약·연결 없음 · (b) 고객 별칭 언급 · (c) 집계 질문 → 전체 마스터 · 저장소 꺼지면 None(기존과 동일)
    assert struct_context("Acme 전체 계약 금액 합계는?", []) is None  # STRUCT_BACKEND·STRUCT_DB 둘 다 없음 → 변화 없음
    tdb = Path(tempfile.mkdtemp()) / "ctx.sqlite"
    _env = mc.senv(STRUCT_DB=str(tdb), STRUCT_BACKEND="sqlite")
    cdb = SDB.open_backend(str(tdb))
    SDB.ensure_schema(cdb)
    cdb.executemany(
        "INSERT INTO contract_master (contract_id,company,company_id,product_code,modality,site,line_id,"
        "batches_contracted,contract_value_usd,currency,term_months,signed_on,start_date,end_date,status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "C-1",
                "Acme Biologics",
                "CL-1",
                "ACM-mAb-01",
                "mAb",
                "Plant1",
                "BR-1",
                6,
                1000000,
                "USD",
                24,
                "2024-01-01",
                "2024-02-01",
                "2026-01-31",
                "active",
            ),
            (
                "C-2",
                "Acme Biologics",
                "CL-1",
                "ACM-ADC-02",
                "ADC",
                "Plant2",
                "BR-2",
                4,
                800000,
                "USD",
                12,
                "2025-01-01",
                "2025-02-01",
                "2026-01-31",
                "active",
            ),
            (
                "C-3",
                "Beta Inc",
                "CL-2",
                "BETA-01",
                "mAb",
                "Plant3",
                "BR-3",
                2,
                300000,
                "USD",
                12,
                "2025-03-01",
                "2025-04-01",
                "2026-03-31",
                "active",
            ),
        ],
    )
    cdb.execute("INSERT INTO client_master (company_id, company, aliases) VALUES (?,?,?)", ("CL-1", "Acme Biologics", "Acme|에이크미"))
    cdb.execute(
        "INSERT INTO doc_contract_link (doc_key, contract_id, score, how, status, evidence_chunk_keys, created_at) VALUES (?,?,?,?,?,?,?)",
        ("h1", "C-1", 3, SDB.HOW_ID_WRITTEN, "확정", "[]", "2026-01-01T00:00:00"),
    )
    cdb.execute(
        "INSERT INTO doc_contract_link (doc_key, contract_id, score, how, status, evidence_chunk_keys, created_at) VALUES (?,?,?,?,?,?,?)",
        ("h2", "C-3", 3, SDB.HOW_ID_WRITTEN, "확정", "[]", "2026-01-01T00:00:00"),
    )
    cdb.commit()
    cdb.close()
    hits = [{"file_path": "/d/doc_a.pdf", "doc_key": "h1"}, {"file_path": "/d/doc_b.pdf", "doc_key": "h9"}]
    ctx = struct_context("Acme의 ACM-ADC-02 제품은 몇 배치인가?", hits)
    by_src = {r[0]: r for r in ctx["rows"]}
    link_src = f"연결: {SDB.HOW_ID_WRITTEN}(확정)"
    assert by_src[link_src][1] == "doc_a.pdf" and by_src[link_src][2] == "C-1"  # (a) 연결된 계약
    assert any(r[0] == "연결 없음" and r[1] == "doc_b.pdf" and r[2] == "계약 없음" for r in ctx["rows"])  # (a) 연결 없는 문서
    assert any(r[0] == "질문 언급(고객)" and r[2] == "C-2" for r in ctx["rows"])  # (b) 고객 별칭(Acme) 언급
    agg_ctx = struct_context("전체 계약 금액 합계는?", [])
    assert sorted(r[2] for r in agg_ctx["rows"]) == ["C-1", "C-2", "C-3"] and all(
        r[0] == "전체 계약" for r in agg_ctx["rows"]
    )  # (c) client 없음 — 전체 마스터(바이트 동일)
    # BR52 — client="Acme Biologics"면 Beta Inc 계약(C-3)이 (a)(b)(c) 전부에서 빠진다 — 다른 고객 문서(doc_c.pdf)가
    # Beta 계약(h2)에 연결돼 있어도 "연결 없음"으로만 보임(다른 고객 계약 번호·금액이 새지 않음)
    hits_leak = hits + [{"file_path": "/d/doc_c.pdf", "doc_key": "h2"}]
    ctx_cl = struct_context("Acme의 ACM-ADC-02 제품은 몇 배치인가?", hits_leak, client={"Acme Biologics"})
    dump_cl = json.dumps(ctx_cl, ensure_ascii=False)
    assert "C-3" not in dump_cl and "Beta Inc" not in dump_cl and "300000" not in dump_cl, ctx_cl
    assert any(r[0] == "연결 없음" and r[1] == "doc_c.pdf" for r in ctx_cl["rows"]), ctx_cl  # 범위 밖 계약은 "연결 없음"으로
    agg_ctx_cl = struct_context("전체 계약 금액 합계는?", [], client={"Acme Biologics"})
    assert sorted(r[2] for r in agg_ctx_cl["rows"]) == ["C-1", "C-2"]  # (c)도 Beta 제외
    _env.close()
    print(
        "[selftest] struct_context(연결된 계약·연결 없음·고객 별칭 언급·집계 질문 전체 마스터·저장소 꺼지면 None · "
        "BR52 client 범위면 다른 고객 계약 전부 제외) 통과"
    )

    # AD45③ — NOID_RE: '계약 ID가 적혀 있지 않은'처럼 부정어가 뒤에 떨어진 표현도 걸림(검색 대신 SQL 목록 경로로 감, 오탐 방지도 확인)
    assert doc_link_question("계약 ID가 적혀 있지 않은 RFI 중 계약으로 이어진 것은?")
    assert doc_link_question("계약 번호를 안 적은 문서 중 연결된 건?")
    assert not doc_link_question("계약 번호가 있는 문서 중 연결된 것은?")  # 부정어 없음 → 안 걸림(오탐 방지)
    print("[selftest] AD45③ NOID_RE(부정어가 뒤에 떨어진 표현) 통과")

    # AD42·AD45④ R1 보강 — '2024년 이후'(열린 구간, 끝=오늘) · 고객 2곳 비교(단가, 계약별 목록으로) · 단일 계약 단가 대조는 오탐 아님
    since = detect("화이자가 2024년 이후 체결한 계약 건수는?", {"Pfizer Inc."}, set(), al)
    assert since and since["window"] == ("2024-01-01", "2026-09-30"), since
    cls2 = {"Pfizer Inc.", "Samsung Biologics"}
    cmp_q = detect("Pfizer Inc.와 Samsung Biologics 중 단가가 더 높은 계약은 어디인가?", cls2, set(), al)
    assert cmp_q and cmp_q["kind"] == "table" and cmp_q["listing"] and not cmp_q["group"], cmp_q
    assert sorted(cmp_q["target"]["clients"]) == sorted(cls2), cmp_q
    assert (
        detect("이메일에서 제안한 단가와 최종 계약(C-1) 단가 중 유효한 것은?", set(), {"C-1"}, al) is None
    )  # 단일 계약 단가 대조(cross_document)는 집계 아님(오탐 방지, 실측 확인)
    assert (
        detect("Pfizer Inc.의 ACM-mAb-01 제품 단가는?", {"Pfizer Inc."}, set(), al) is None
    )  # 고객 1곳 + 단가만으로는 집계 트리거 안 함(오탐 방지)
    assert (
        detect("Pfizer Inc.와 Samsung Biologics 각각 단가가 적힌 메일을 찾아줘", cls2, set(), al) is None
    )  # 독립 검토 MAJOR(10-07) — 비교어 없이 '찾아줘·메일'(검색 의도)이면 고객 2곳이어도 집계 아님
    assert detect("Pfizer Inc.와 Samsung Biologics 단가가 적힌 문서를 보여줘", cls2, set(), al) is None
    # 재검 MAJOR(이슈2 양방향, 10-07) — (a) '중' 단독 제거 (b) 비교어 > 검색 의도어, 단 '문서/메일을 찾아·보여줘'는 검색 (c) 존재·진행 여부는 집계 아님
    assert detect("Pfizer Inc.와 Samsung Biologics 중 단가가 아직 정해지지 않은 계약이 있나요?", cls2, set(), al) is None  # (c) 존재 질문
    assert detect("Pfizer Inc.와 Samsung Biologics의 단가 협상이 끝났나요?", cls2, set(), al) is None  # (c) 진행 여부 질문
    assert (
        detect("Pfizer Inc.와 Samsung Biologics 중 단가 비교한 문서를 찾아줘", cls2, set(), al) is None
    )  # (b) 찾을 대상이 문서 자체 → 검색
    cmp_mail = detect("Pfizer Inc.와 Samsung Biologics의 메일 기준으로 단가를 비교해줘", cls2, set(), al)
    assert cmp_mail and cmp_mail["kind"] == "table" and cmp_mail["listing"], cmp_mail  # (b) '메일' 언급돼도 찾는 대상이 아니면 비교 집계
    print(
        "[selftest] R1 보강(AD42·AD45④) — 열린 구간('…이후')·고객 2곳 단가 비교(명시적 비교어만, 목록)"
        " · 단일 계약·고객 1곳 단가·검색 의도(찾아줘·메일·문서)·'중' 단독·존재·진행 여부 질문은 오탐 없음 통과"
    )

    # AD45① — 데이터 카탈로그 + doc_location SQL(문서 목록·건수·최근 판, AD38 list_documents와 같은 원천)
    rdb_d = Path(tempfile.mkdtemp())
    rdb_db = SDB.open_backend(str(rdb_d / "rdb.sqlite"))
    SDB.ensure_schema(rdb_db)
    rdb_db.execute(
        "INSERT INTO client_master (company_id, company, aliases) VALUES (?,?,?)", ("CL-2002", "선진메디팜(주)", "선진메디팜|SJM")
    )
    rdb_db.executemany(
        "INSERT INTO doc_location (doc_id,bucket,object_key,etag,size_bytes,content_type,company_id,doc_type,"
        "contract_id,version,supersedes_doc_id,language,received_at,updated_at,is_deleted) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "rfi_answer_sjm_2023_v1",
                "b",
                "k",
                "e",
                1,
                "t",
                "CL-2002",
                "RFI_ANSWER",
                None,
                1,
                None,
                "ko",
                "2023-09-01",
                "x",
                0,
            ),  # 대체된 구판 → 제외
            (
                "rfi_answer_sjm_2023_v2",
                "b",
                "k",
                "e",
                1,
                "t",
                "CL-2002",
                "RFI_ANSWER",
                None,
                2,
                "rfi_answer_sjm_2023_v1",
                "ko",
                "2023-09-20",
                "x",
                0,
            ),
            ("rfi_answer_sjm_2024", "b", "k", "e", 1, "t", "CL-2002", "RFI_ANSWER", None, 1, None, "ko", "2024-06-10", "x", 0),
            (
                "rfi_answer_sjm_2025",
                "b",
                "k",
                "e",
                1,
                "t",
                "CL-2002",
                "RFI_ANSWER",
                None,
                1,
                None,
                "ko",
                "2025-02-01",
                "x",
                1,
            ),  # 삭제 → 제외
            ("rfi_answer_sjm_2026", "b", "k", "e", 1, "t", "CL-2002", "RFI_ANSWER", None, 1, None, "ko", "2026-01-15", "x", 0),
            ("rfp_sjm_mab_2025", "b", "k", "e", 1, "t", "CL-2002", "RFP", "C-RDB-2025-005", 1, None, "ko", "2025-02-20", "x", 0),
            ("contract_sjm_mab_2025", "b", "k", "e", 1, "t", "CL-2002", "CONTRACT", "C-RDB-2025-005", 1, None, "ko", "2025-05-01", "x", 0),
            ("quote_sjm_mab_2025", "b", "k", "e", 1, "t", "CL-2002", "QUOTE", "C-RDB-2025-005", 1, None, "ko", "2025-03-10", "x", 0),
            ("mail_sjm_negotiation_2025", "b", "k", "e", 1, "t", "CL-2002", "MAIL", "C-RDB-2025-005", 1, None, "ko", "2025-03-25", "x", 0),
            ("rfp_marwick_vaccine_2025", "b", "k", "e", 1, "t", "CL-2005", "RFP", None, 1, None, "en", "2025-11-01", "x", 0),
        ],
    )
    rdb_db.commit()
    rdb_db.close()
    _env = mc.senv(STRUCT_DB=str(rdb_d / "rdb.sqlite"), STRUCT_BACKEND="sqlite")
    r1 = struct("선진메디팜 과거 RFI 답변서 전부 보여줘")  # MQ001
    assert [row[0] for row in r1["rows"]] == ["rfi_answer_sjm_2023_v2", "rfi_answer_sjm_2024", "rfi_answer_sjm_2026"], r1
    r2 = struct("계약 C-RDB-2025-005 관련 문서 목록은?")  # MQ003
    assert {row[0] for row in r2["rows"]} == {
        "rfp_sjm_mab_2025",
        "contract_sjm_mab_2025",
        "quote_sjm_mab_2025",
        "mail_sjm_negotiation_2025",
    }, r2
    r3 = struct("선진메디팜 2023년 RFI 답변서 중 가장 최근 판은?")  # MQ004
    assert [row[0] for row in r3["rows"]] == ["rfi_answer_sjm_2023_v2"], r3
    r4 = struct("2025년에 받은 RFP는 몇 건인가?")  # MQ005
    assert {row[0] for row in r4["rows"]} == {"rfp_sjm_mab_2025", "rfp_marwick_vaccine_2025"}, r4
    assert struct("선진메디팜 계약 건수는?") is None  # 문서 종류·계약ID 단서 없는 일반 계약 질문은 doc_location 경로로 안 감(오탐 방지)
    cat_path = rdb_d / "catalog.json"
    cat_path.write_text(
        json.dumps(
            {
                "rows": [
                    {"table_name": "doc_location", "column_name": None, "description": "문서 위치 메타"},
                    {
                        "table_name": "doc_location",
                        "column_name": "doc_type",
                        "description": "문서 종류",
                        "allowed_values": "RFI_ANSWER|RFP",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    assert "카탈로그" not in struct("계약 C-RDB-2025-005 관련 문서 목록은?")["note"]  # DATA_CATALOG 없으면 지금 그대로
    with mc.senv(DATA_CATALOG=str(cat_path)):
        assert "[doc_location 카탈로그] 문서 위치 메타" in struct("계약 C-RDB-2025-005 관련 문서 목록은?")["note"]
    _env.close()
    print("[selftest] AD45① doc_location SQL(문서 목록·건수·최근 판) 4/4 · 데이터 카탈로그(있으면 note 동봉·없으면 그대로) 통과")

    # DT1 c1 — 집계 지표 단서어(agg_vocab.json). 기본 파일(dev/common/agg_vocab.json)이 코드 기본값과 바이트 동일한지 ·
    # AGG_VOCAB_FILE로 가짜 회사 예시(배치 대신 'lots')를 넣으면 BATCH_Q가 바로 반영되는지.
    assert _load_agg_vocab() == _AGG_VOCAB_DEFAULT, _load_agg_vocab()  # 기본 파일 = 코드 기본값(바이트 동일)
    assert BATCH_Q.search("이번 분기 배치 수는?") and not BATCH_Q.search("이번 분기 lots 수는?")
    fake_vocab = Path(tempfile.mkdtemp()) / "agg_vocab.json"
    fake_vocab.write_text(json.dumps({"batch": ["lots", "랏"]}, ensure_ascii=False), encoding="utf-8")
    _env = mc.senv(AGG_VOCAB_FILE=str(fake_vocab))
    try:
        v = _load_agg_vocab()
        assert v["batch"] == ["lots", "랏"] and v["count"] == _AGG_VOCAB_DEFAULT["count"]  # 바꾼 키만 반영, 나머지는 기본값
        fake_batch_re = re.compile("|".join(v["batch"]), re.I)
        assert fake_batch_re.search("이번 분기 랏 수는?") and not fake_batch_re.search("이번 분기 배치 수는?")
    finally:
        _env.close()
    assert _load_agg_vocab() == _AGG_VOCAB_DEFAULT  # env 지우면 다시 기본값(바이트 동일)
    print("[selftest] agg_vocab.json — 기본 파일 바이트 동일·AGG_VOCAB_FILE 가짜 회사 예시 반영·부분 교체 통과(DT1 c1)")

    # RV-singlelookup(2026-10-11, OpenRouter run2 묶음D + 글로서리 켬 misfire 측정 round3) — 계약 하나(고객 1곳
    # 이하)의 배치·단가 속성 조회는 집계 신호(AGG_SCOPE_CUE_RE) 없이는 None(검색 폴백). synth-xling 실측 misfire 6건
    # (지시된 3건 + 같은 유형 3건) 전부 포함.
    al1 = {"Pfizer Inc.": ["화이자"]}
    for q in [
        "화이자 공급 계약의 배치당 단가는 얼마야?",  # 지시된 3건
        "화이자 공급 계약의 계약 기간은 몇 개월이야?",
        "What is the batch count in Pfizer's Korea-branch supply agreement?",
        "화이자와 맺은 공급 계약의 배치 수는?",  # 같은 유형(측정으로 발견)
        "미르하 견적서의 배치당 가격은?",
        "What is the unit price per batch in the Cheongram Bio quote?",
    ]:
        assert detect(q, {"Pfizer Inc.", "미르하제약(주)", "청람바이오(주)"}, set(), al1) is None, q
    # 근처 집계 질문(건수·전체·각·합계·all·total·each 같은 집계 신호가 있으면 배치·단가가 같이 있어도 그대로 집계 — 실측
    # synth-4clients QA003·QA005·QA029·QA092·QA098과 같은 모양, misfire 측정 전후 missed_fires 변화 없음 확인됨)
    for q in [
        "화이자 전체 계약 이력에서 bispecific·vaccine 계약은 각각 몇 건이며, 배치 수 합계와 계약 금액 합계는 얼마인가?",
        "화이자가 과거 3년 동안 mAb 제품으로 체결한 계약은 몇 건이며, 계약별 배치 수·단가와 계약 규모 합계는 얼마인가?",
        "우리가 준비한 화이자가 과거 3년 동안 계약한 계약 건수와 제품 종류, 제품 종류별 계약 배치 수를 정리해줘.",
        "How many ADC contracts has Pfizer signed in the past 3 years, and what is the batch volume, "
        "unit price, and contract value of each?",
        "Across all of Pfizer's contracts on file (not limited to the past 3 years), what is the contract "
        "count and total batch volume and contract value per product modality?",
    ]:
        assert detect(q, {"Pfizer Inc."}, set(), al1) is not None, q
    print(
        "[selftest] RV-singlelookup — 단일 계약 배치·단가 속성 조회(집계 신호 없음) 6건 None · 근처 집계 질문(건수·전체·"
        "각·합계·all/total/each) 5건은 그대로 집계 통과"
    )

    # AD23 leftover — table_cell_question·table_cell_list·struct() 라우팅(doc_table·doc_cell, find_table_cells 연결)
    from common.core.text import normalize_value as _nv

    tcd = Path(tempfile.mkdtemp())
    tcdb = SDB.open_backend(str(tcd / "tc.sqlite"))
    SDB.ensure_table_schema(tcdb)
    tcdb.execute(
        "INSERT INTO doc_table (table_key,doc_key,table_id,page,source_engine,n_rows,n_cols,header_json,merged_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("docT:t0", "docT", "t0", 3, "office", 2, 2, json.dumps(["배치", "수량"], ensure_ascii=False), "[]", "2026-01-01T00:00:00"),
    )
    cells = [
        ("docT:t0", 0, 0, "배치", "배치", _nv("배치")),
        ("docT:t0", 0, 1, "수량", "수량", _nv("수량")),
        ("docT:t0", 1, 0, "배치", "BT-0137", _nv("BT-0137")),
        ("docT:t0", 1, 1, "수량", "100", _nv("100")),
        ("docT:t0", 2, 0, "배치", "BT-0200", _nv("BT-0200")),
        ("docT:t0", 2, 1, "수량", "50", _nv("50")),
    ]
    tcdb.executemany("INSERT INTO doc_cell (table_key,row_idx,col_idx,col_label,value,value_norm) VALUES (?,?,?,?,?,?)", cells)
    tcdb.commit()
    tcdb.close()
    _env = mc.senv(STRUCT_DB=str(tcd / "tc.sqlite"), STRUCT_BACKEND="sqlite")
    assert table_cell_question("big_table.xlsx에서 배치 BT-0137의 수량은?")
    assert not table_cell_question("화이자 전체 계약 금액 합계는?")  # ID 모양 토큰 없음
    r = struct("big_table.xlsx에서 배치 BT-0137의 수량은?")
    assert r is not None and r["kind"] == "table_cell", r
    assert ["docT", "t0", 3, "수량", "100"] in r["rows"] and ["docT", "t0", 3, "배치", "BT-0137"] in r["rows"], (
        r
    )  # 같은 행 전체(머리글 포함)
    assert struct("배치 BT-9999의 수량은?") is None  # 토큰이 doc_cell에 없음 — 집계·검색으로 폴백(None, misfire 방지)
    assert struct("화이자 전체 계약 금액 합계는?") is None  # ID 모양 토큰 자체가 없음 — 기존 집계 경로 영향 없음(바이트 동일)
    _env.close()
    print(
        "[selftest] AD23 leftover — table_cell_question·table_cell_list·struct() 라우팅(doc_cell에 실제로 있는 토큰일 때만 답,"
        " 없으면 None — 기존 집계·doc_link·doc_list 경로와 안 겹침) 통과"
    )

    # engine-qa BLOCK②(10-11) — (a) 날짜·순수 숫자+하이픈은 표 칸 후보에서 제외 (b) find_table_cells 정확 일치
    # (c) 계약/고객이 특정되면 그 문서로만 좁힘, 모르면 토큰이 문서 둘 이상에 걸치면 그 토큰은 버림(동음이의 위험)
    assert _table_cell_tokens("2024-01-15 이후 계약은?") == []  # 날짜 모양만 — 글자 없음
    assert _table_cell_tokens("2026-05에 채취한 시료는?") == []  # 순수 숫자+하이픈
    assert _table_cell_tokens("배치 BT-0137의 수량은?") == ["BT-0137"]  # 글자+숫자는 그대로 후보
    d2 = Path(tempfile.mkdtemp())
    db2 = SDB.open_backend(str(d2 / "cross.sqlite"))
    SDB.ensure_schema(db2)  # contract_master·client_master·doc_contract_link(스코프 판별용)
    SDB.ensure_table_schema(db2)  # doc_table·doc_cell
    db2.executemany(
        "INSERT INTO contract_master (contract_id,company,company_id,product_code,modality,site,line_id,"
        "batches_contracted,contract_value_usd,currency,term_months,signed_on,start_date,end_date,status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "C-A",
                "Acme Biologics",
                "CL-A",
                "ACM-01",
                "mAb",
                "P1",
                "BR-1",
                1,
                1,
                "USD",
                1,
                "2024-01-01",
                "2024-01-01",
                "2026-01-01",
                "active",
            ),
            ("C-B", "Beta Labs", "CL-B", "BET-01", "mAb", "P2", "BR-2", 1, 1, "USD", 1, "2024-01-01", "2024-01-01", "2026-01-01", "active"),
        ],
    )
    db2.execute(
        "INSERT INTO doc_contract_link (doc_key,contract_id,score,how,status,evidence_chunk_keys,created_at) VALUES (?,?,?,?,?,?,?)",
        ("docA", "C-A", 3, SDB.HOW_ID_WRITTEN, "확정", "[]", "2026-01-01T00:00:00"),
    )
    db2.execute(
        "INSERT INTO doc_contract_link (doc_key,contract_id,score,how,status,evidence_chunk_keys,created_at) VALUES (?,?,?,?,?,?,?)",
        ("docB", "C-B", 3, SDB.HOW_ID_WRITTEN, "확정", "[]", "2026-01-01T00:00:00"),
    )
    for tk, dk, qty in (("docA:t0", "docA", "100"), ("docB:t0", "docB", "999")):  # 두 문서 표에 같은 배치 토큰이 우연히 겹침
        db2.execute(
            "INSERT INTO doc_table (table_key,doc_key,table_id,page,source_engine,n_rows,n_cols,header_json,merged_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tk, dk, "t0", 1, "office", 1, 2, json.dumps(["배치", "수량"], ensure_ascii=False), "[]", "2026-01-01T00:00:00"),
        )
        db2.executemany(
            "INSERT INTO doc_cell (table_key,row_idx,col_idx,col_label,value,value_norm) VALUES (?,?,?,?,?,?)",
            [
                (tk, 0, 0, "배치", "배치", _nv("배치")),
                (tk, 0, 1, "수량", "수량", _nv("수량")),
                (tk, 1, 0, "배치", "BT-0137", _nv("BT-0137")),
                (tk, 1, 1, "수량", qty, _nv(qty)),
            ],
        )
    db2.commit()
    db2.close()
    _env = mc.senv(STRUCT_DB=str(d2 / "cross.sqlite"), STRUCT_BACKEND="sqlite")
    ambiguous = struct("배치 BT-0137의 수량은?")  # 계약·고객 언급 없음 + 두 문서에 걸침 → 답 안 함(동음이의 위험)
    assert ambiguous is None, ambiguous
    scoped = struct("Acme Biologics 계약의 배치 BT-0137 수량은?")  # 고객으로 docA만 특정됨
    assert scoped is not None and scoped["kind"] == "table_cell", scoped
    assert all(r[0] == "docA" for r in scoped["rows"]), scoped  # docB(999)는 안 섞임
    assert ["docA", "t0", 1, "수량", "100"] in scoped["rows"], scoped
    _env.close()
    print(
        "[selftest] engine-qa BLOCK②(10-11) — 날짜·순수 숫자+하이픈 제외 · find_table_cells 정확 일치 ·"
        " 계약/고객 특정되면 그 문서로만 좁힘 · 모르면 문서 둘 이상 걸친 토큰은 버림(오답 방지) 통과"
    )

    # BR34(10-11, 측정 후 종결 — 코드 변경 없음) — QA049류('OO의 생산 제품 수는 몇 개인가?')는 detect()가 집계로 안
    # 잡는다(PRODUCT_COUNT, L196). 측정 결과(dev_tools/perform_test/retrieval/measure.py): synth-4clients QA020·034·049·096
    # 전부 이미 search만으로 doc_hit5=1.0·evid_cov5=1.0·strict_hit5=True(보도자료 문서가 상위 5에 그대로 잡힘) ·
    # 4개 세트(4clients·4clients-cmp·r2·xling) 전체에서 detect()가 놓치는 다른 집계형 질문은 없음(agg_type 40행
    # 전수 확인) · 이 네 질문을 억지로 집계로 보내면(가상 실험) 검색 지표는 그대로지만 _apply()는 계약 건수를 세어
    # (제품 수가 아님) 답이 틀릴 위험만 생기고 측정 이득은 0 → 벡터 확장 안 함, 기존 가드만 회귀 고정.
    assert detect("미르하제약(주)의 생산 제품 수는 몇 개인가?", {"미르하제약(주)"}, set()) is None
    assert detect("청람바이오(주)의 생산 제품 수는 몇 개인가?", {"청람바이오(주)"}, set()) is None
    print("[selftest] BR34(측정 후 종결) — '생산 제품 수' 한글 변형도 영어와 같게 집계 아님(검색으로 이미 충분) 통과")

    # BR44(10-11, 측정 후 종결 — 코드 변경 없음) — 비교·집계 질문의 "계약별 근거" 행(table_text(), BR40)이 비교
    # 대상 밖 고객으로 새는지 측정(4개 세트 225행 + QA111 20행 전수 확인, 누출 0) — _apply()가 recs를 target
    # 고객/계약으로 먼저 거른 뒤에만 _ev()를 부르는 게 유일한 경로라 구조적으로 못 샌다. 회귀 가드만 굳힘.
    leak_docs = mixed_docs + [
        {
            "file_path": "g",
            "client": "Gamma Inc",
            "contract_no": "C-G",
            "meta_confirmed": True,
            "contract": {"modality": "mAb", "signed_on": "2024-01-01", "amount": 999.0, "currency": "USD", "batches": 1},
        }
    ]
    cmp2 = run("화이자와 Beta Inc 중 전체 계약 금액 합계가 더 큰 곳은?", leak_docs, aliases=al)
    assert {e.get("client") for e in cmp2["evidence"]} == {"Pfizer Inc.", "Beta Inc"}, cmp2  # Gamma Inc(비교 대상 아님) 안 섞임
    print("[selftest] BR44(측정 후 종결) — 비교 질문 근거에 비교 대상 밖 고객 섞임 없음(실측 225+20행 누출 0 — 회귀 가드) 통과")
    _env_today.close()
