"""pipeline.load.structured 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.load.structured --selftest`."""

from pathlib import Path

from common.store import structdb as SDB
from pipeline.load.structured import CONFIRM_TH, _norm_code, link_docs, load_csv


# ── 자체 검증 ────────────────────────────────────────────────────
def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "contract_master.csv").write_text(
        "_synthetic,contract_id,company,company_id,product_code,modality,site,line_id,batches_contracted,"
        "contract_value_usd,currency,term_months,signed_on,start_date,end_date,status\n"
        "[T],C-1,Acme Biologics,CL-1,ACM-mAb-01,mAb,Plant1,BR-1,6,1000000,USD,24,2024-01-01,2024-02-01,2026-01-31,active\n"
        "[T],C-2,Acme Biologics,CL-1,ACM-ADC-02,ADC,Plant2,BR-2,4,800000,USD,12,2025-01-01,2025-02-01,2026-01-31,active\n",
        encoding="utf-8",
    )
    (d / "client_master.csv").write_text("_synthetic,company_id,company,aliases\n[T],CL-1,Acme Biologics,Acme|에이크미\n", encoding="utf-8")
    db = SDB.open_backend(str(d / "t.sqlite"))
    SDB.ensure_schema(db)
    n = load_csv(db, d)
    assert n == {"contract_master": 2, "client_master": 1}, n
    row = db.query("SELECT * FROM contract_master WHERE contract_id='C-1'")[0]
    assert row["batches_contracted"] == 6 and row["contract_value_usd"] == 1000000, row

    docs = [
        {"doc_key": "h1", "text": "계약 번호 C-1에 따라 원료를 공급합니다.", "file_name": "a"},
        {"doc_key": "h2", "text": "Acme 고객의 ACM ADC-02 제품, 4배치, 2025년 2월 착수 예정 RFI.", "file_name": "b"},
        {"doc_key": "h3", "text": "Acme 고객 문의, 이번 건은 타사 선정으로 미체결 처리됨.", "file_name": "c"},
        {"doc_key": "h4", "text": "관련 없는 다른 고객 문서.", "file_name": "d"},
        {"doc_key": "h5", "text": "Acme 고객 RFI, 제품 종류만 mAb로 언급(배치·시기 없음).", "file_name": "e"},
    ]
    rows = link_docs(db, docs)
    by_key = {r[0]: r for r in rows}
    assert by_key["h1"][1:4] == ("C-1", CONFIRM_TH, SDB.HOW_ID_WRITTEN) and by_key["h1"][4] == "확정"
    assert by_key["h2"][1] == "C-2" and by_key["h2"][4] == "확정", by_key["h2"]  # 별칭+제품코드+배치+시기
    assert "h3" not in by_key  # 실주·미체결 → 연결 없음
    assert "h4" not in by_key  # 고객 없음 → 연결 없음
    assert by_key["h5"][4] == "후보", by_key["h5"]  # 제품 종류만 → 저신뢰 후보

    assert _norm_code("KST ADC-02") == _norm_code("KST-ADC-02") == "kstadc02"
    try:
        SDB.guard_not_prod(next(iter(SDB.PROD_DBS)))
        raise AssertionError("운영 DB 가드가 걸려야 함")
    except SystemExit:
        pass
    db.close()
    print("[selftest] CSV 적재·문서↔계약 연결(확정·후보·실주·고객없음)·제품코드 정규화·운영 DB 가드 통과")

    # AD45④(V21) — doc_location이 그 문서를 알면 본문 규칙보다 우선: contract_id 있으면 그 계약, 명시 NULL이면 본문 후보 연결 안 함
    d2 = Path(tempfile.mkdtemp())
    (d2 / "contract_master.csv").write_text(
        "_synthetic,contract_id,company,company_id,product_code,modality,site,line_id,batches_contracted,"
        "contract_value_usd,currency,term_months,signed_on,start_date,end_date,status\n"
        "[T],C-1,Acme Biologics,CL-1,ACM-mAb-01,mAb,Plant1,BR-1,6,1000000,USD,24,2024-01-01,2024-02-01,2026-01-31,active\n",
        encoding="utf-8",
    )
    (d2 / "client_master.csv").write_text(
        "_synthetic,company_id,company,aliases\n[T],CL-1,Acme Biologics,Acme|에이크미\n", encoding="utf-8"
    )
    (d2 / "doc_location.csv").write_text(
        "_synthetic,doc_id,bucket,object_key,etag,size_bytes,content_type,company_id,doc_type,contract_id,version,"
        "supersedes_doc_id,language,received_at,updated_at,is_deleted\n"
        "[T],rfi_g,b,k,e,1,t,CL-1,RFI_ANSWER,,1,,ko,2026-01-01,2026-01-01T00:00:00Z,0\n"  # 계약 없음 명시(contract_id NULL)
        "[T],mail_h,b,k,e,1,t,CL-1,MAIL,C-1,1,,ko,2026-01-01,2026-01-01T00:00:00Z,0\n"  # contract_id 있음(RDB 우선값)
        "[T],typo_j,b,k,e,1,t,CL-1,MAIL,C-999-TYPO,1,,ko,2026-01-01,2026-01-01T00:00:00Z,0\n",  # contract_master에 없는 ID(오타·삭제) → 확정 아님(독립 검토 MAJOR)
        encoding="utf-8",
    )
    db2 = SDB.open_backend(str(d2 / "t2.sqlite"))
    SDB.ensure_schema(db2)
    load_csv(db2, d2)
    docs2 = [
        {
            "doc_key": "g",
            "text": "Acme 고객 RFI, ACM ADC-02 제품, 4배치, 2025년 2월 착수 예정.",
            "file_name": "rfi_g.docx",
        },  # 본문만 보면 후보 연결될 글(제품코드는 다른 계약 것이라 실제론 무관)
        {
            "doc_key": "h",
            "text": "메일 본문에는 계약 이야기가 없음.",
            "file_name": "mail_h.eml",
        },  # 본문만 보면 '고객 없음'(연결 안 됨)이지만 RDB가 C-1을 앎
        {
            "doc_key": "i",
            "text": "계약 번호 C-1에 따라 원료를 공급합니다.",
            "file_name": "unlisted_i.txt",
        },  # doc_location에 없음 → 본문 규칙 그대로
        {
            "doc_key": "j",
            "text": "메일 본문에는 계약 이야기가 없음.",
            "file_name": "typo_j.eml",
        },  # RDB contract_id가 contract_master에 없음(오타·삭제) → 확정 아님
    ]
    rows2 = link_docs(db2, docs2)
    by_key2 = {r[0]: r for r in rows2}
    assert "g" not in by_key2, by_key2.get("g")  # RDB 명시 '계약 없음' → 본문 후보 연결 시도 안 함
    assert by_key2["h"][1:4] == ("C-1", CONFIRM_TH, SDB.HOW_RDB_LOCATION) and by_key2["h"][4] == "확정", by_key2["h"]  # RDB 우선값
    assert by_key2["i"][1:4] == ("C-1", CONFIRM_TH, SDB.HOW_ID_WRITTEN) and by_key2["i"][4] == "확정", by_key2[
        "i"
    ]  # doc_location에 없는 문서 → 본문 규칙 그대로
    assert by_key2["j"][1] == "C-999-TYPO" and by_key2["j"][4] == "후보" and "계약 마스터에 없음" in by_key2["j"][3], by_key2[
        "j"
    ]  # 독립 검토 MAJOR — 존재 검증 없이 확정 금지
    db2.close()
    print(
        "[selftest] AD45④(V21) — doc_location이 문서를 알면 우선(계약 있음=확정·명시 NULL=연결 안 함) · 모르는 문서는 본문 규칙 그대로"
        " · contract_master에 없는 RDB contract_id는 확정 아님(후보로 강등, 독립 검토 MAJOR) 통과"
    )


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
