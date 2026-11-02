"""pl-29 — 적재 때 EDW 조인(pipeline/load/edw_meta.py): 원천별 사슬로 client_edw·원천 칸·등록 시각. 임시 SQLite EDW(가짜 데이터만,
스키마 AI·SFDC·CRMS·LAS를 ATTACH — 질의 글자는 서버 T-SQL과 같음) · 외부 접속 없음."""

import copy
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from pipeline.load import edw_meta as M

DDL = """
CREATE TABLE AI.FileStorageMap (s3_key TEXT, source_system TEXT, content_version_id TEXT, created_at TEXT);
CREATE TABLE AI.FileStorageMap_CRMS (s3_key TEXT, rm_contract_code TEXT, gate_code TEXT, gate_version TEXT, docu_seq INT);
CREATE TABLE AI.FileStorageMap_LAS (s3_key TEXT, manage_no TEXT, las_file_id TEXT, signed_date TEXT);
CREATE TABLE SFDC.ContentVersion (Id TEXT, ContentDocumentId TEXT, CreatedDate TEXT);
CREATE TABLE SFDC.ContentDocumentLink (ContentDocumentId TEXT, LinkedEntityId TEXT, IsDeleted INT);
CREATE TABLE SFDC.Task (Id TEXT, WhatId TEXT);
CREATE TABLE SFDC.Event (Id TEXT, WhatId TEXT);
CREATE TABLE SFDC.Opportunity (Id TEXT, Name TEXT, AccountId TEXT, Project_Code__c TEXT, Record_Type__c TEXT, X1st_Contract_Execution_Date__c TEXT);
CREATE TABLE SFDC.Account (Id TEXT, Name TEXT);
CREATE TABLE CRMS.RM_CM_PJTLIST (RM_CONTRACT_CODE TEXT, SF_ACC_NAME TEXT, DIVISION TEXT, RM_CONTRACT_NAME TEXT, INIT_DTTM TEXT);
CREATE TABLE CRMS.RM_CM_DOCU (RM_CONTRACT_CODE TEXT, GATE_CODE TEXT, GATE_VERSION TEXT, DOCU_SEQ INT, INIT_DTTM TEXT);
CREATE TABLE LAS.Contract (ManageNo TEXT, ContractID INT, IsActive INT, ContractDate TEXT, PartnerCorpName TEXT);
CREATE TABLE LAS.FileManager (FileID TEXT, CreateDate TEXT);
"""
QUOTE = "CREATE TABLE SFDC.Quote (Id TEXT, OpportunityId TEXT, AccountId TEXT);"

ROWS: dict[str, list[tuple]] = {  # 가짜 데이터 — 사슬 단계마다 문서 하나
    "AI.FileStorageMap": [
        ("SFDC/d1/opp.pdf", "SFDC", "cv1", "2025-01-01 00:00:00"),  # 006 직접
        ("SFDC/d2/task.pdf", "SFDC", "cv2", None),  # 00T → Task.WhatId 006
        ("SFDC/d3/event.pdf", "SFDC", "cv3", None),  # 00U → Event.WhatId 006
        ("SFDC/d4/quote.pdf", "SFDC", "cv4", None),  # 0Q0 → Quote.OpportunityId
        ("SFDC/d5/acc.pdf", "SFDC", "cv5", None),  # 기회 없음 — 001 계정 직접
        ("SFDC/d6/tie.pdf", "SFDC", "cv6", None),  # 006 둘 — 비움
        ("CRMS/c1/a.docx", "CRMS", None, "2025-02-01 00:00:00"),
        ("LAS/l1/m.pdf", "LAS", None, "2025-03-01 00:00:00"),
        ("FAQ/f1/q.xlsx", "FAQ", None, "2025-04-01 00:00:00"),
    ],
    "SFDC.ContentVersion": [(f"cv{i}", f"cd{i}", f"2024-12-0{i} 09:00:00") for i in range(1, 7)],
    "SFDC.ContentDocumentLink": [
        ("cd1", "006A", 0),
        ("cd1", "005USER", 0),  # 사용자 등 다른 접두는 무시
        ("cd2", "00TT1", 0),
        ("cd3", "00UE1", 0),
        ("cd4", "0Q0Q1", 0),
        ("cd5", "001ACC2", 0),
        ("cd6", "006A", 0),
        ("cd6", "006B", 0),
        ("cd6", "001ACC1", 0),  # 기회가 동률이면 계정 직접이 있어도 고객을 붙이지 않음
        ("cd1", "006B", 1),  # 지운 연결(IsDeleted=1)은 안 봄
    ],
    "SFDC.Task": [("00TT1", "006B")],
    "SFDC.Event": [("00UE1", "006A")],
    "SFDC.Opportunity": [
        ("006A", "Opp A", "001ACC1", "P001", "CDO", "2025-05-01"),
        ("006B", "Opp B", "001ACC2", "P002", "ADC", None),
    ],
    "SFDC.Account": [("001ACC1", "Acme"), ("001ACC2", "Beta")],
    "AI.FileStorageMap_CRMS": [("CRMS/c1/a.docx", "RC-9", "G1", "1", 3)],
    "CRMS.RM_CM_PJTLIST": [("RC-9", "Gamma", "DS", "Contract X", "2025-02-10")],
    "CRMS.RM_CM_DOCU": [("RC-9", "G1", "1", 3, "2025-02-11 08:00:00")],
    "AI.FileStorageMap_LAS": [("LAS/l1/m.pdf", "M-1", "F1", "2025-03-05")],
    "LAS.Contract": [("M-1", 1, 0, "2025-03-02", None), ("M-1", 2, 1, "2025-03-03", "")],  # 최신 판 = IsActive 1
    "LAS.FileManager": [("F1", "2025-03-04 10:00:00")],
}


def _edw(path, quote=True):
    cn = sqlite3.connect(":memory:")
    for s in ("AI", "SFDC", "CRMS", "LAS"):  # 스키마마다 파일 하나(같은 파일을 여러 번 붙이면 쓰기가 잠김)
        cn.execute(f"ATTACH DATABASE '{path}.{s}' AS {s}")
    cn.executescript(DDL + (QUOTE if quote else ""))
    for t, rows in ROWS.items():
        for r in rows:
            cn.execute(f"INSERT INTO {t} VALUES ({', '.join(['?'] * len(r))})", r)
    if quote:
        cn.execute("INSERT INTO SFDC.Quote VALUES ('0Q0Q1', '006A', '001ACC1')")
    cn.commit()
    e = object.__new__(M._Edw)
    e.cn, e.ph = cn, "?"
    return e


DOCS = [(r[1], r[0]) for r in ROWS["AI.FileStorageMap"]]
QUOTE_STEP = {"prefix": "0Q0", "table": "SFDC.Quote", "id": "Id", "value": "OpportunityId", "optional": True}  # 설정 파일의 주석 줄 그대로


def _chain(quote=True):
    c = copy.deepcopy(M.load_chain())  # 기본 설정 파일(Quote 단계 없음 — 사용자 11-02)
    if quote:
        c["sfdc"]["steps"].append(QUOTE_STEP)
    return c


def test_chains():
    d = Path(tempfile.mkdtemp())
    e = _edw(str(d / "edw.sqlite"))
    try:
        out, missing = M.fetch(DOCS, e, _chain())
        base, _ = M.fetch(DOCS, e)  # 기본 설정 — Quote 단계 없음
    finally:
        e.close()
    cases = [  # (원본 경로, 칸, 기대)
        ("SFDC/d1/opp.pdf", "sf_op_id", "006A"),
        ("SFDC/d1/opp.pdf", "client_edw", "Acme"),
        ("SFDC/d1/opp.pdf", "project_code__c", "P001"),
        ("SFDC/d1/opp.pdf", "service_type", "CDO"),
        ("SFDC/d1/opp.pdf", "contract_date", "2025-05-01"),
        ("SFDC/d1/opp.pdf", "created_at", "2024-12-01 09:00:00+00:00"),  # ContentVersion.CreatedDate(UTC)
        ("SFDC/d2/task.pdf", "sf_op_id", "006B"),
        ("SFDC/d2/task.pdf", "client_edw", "Beta"),
        ("SFDC/d3/event.pdf", "sf_op_id", "006A"),
        ("SFDC/d4/quote.pdf", "sf_op_id", "006A"),  # Quote 단계
        ("SFDC/d5/acc.pdf", "sf_op_id", None),
        ("SFDC/d5/acc.pdf", "client_edw", "Beta"),  # 계정 직접
        ("SFDC/d6/tie.pdf", "sf_op_id", None),  # 같은 단계 후보 둘 — 비움
        ("SFDC/d6/tie.pdf", "client_edw", None),
        ("CRMS/c1/a.docx", "client_edw", "Gamma"),
        ("CRMS/c1/a.docx", "division", "DS"),
        ("CRMS/c1/a.docx", "prod_name", "Contract X"),
        ("CRMS/c1/a.docx", "contract_id", "RC-9"),
        ("CRMS/c1/a.docx", "created_at", "2025-02-11 08:00:00"),  # RM_CM_DOCU 4 키
        ("LAS/l1/m.pdf", "contract_id", "M-1"),
        ("LAS/l1/m.pdf", "contract_date", "2025-03-03"),  # 최신 판
        ("LAS/l1/m.pdf", "client_edw", None),  # PartnerCorpName 비어 있음 — G2
        ("LAS/l1/m.pdf", "created_at", "2025-03-04 10:00:00"),  # FileManager.CreateDate
        ("FAQ/f1/q.xlsx", "created_at", "2025-04-01 00:00:00"),
    ]
    for key, col, want in cases:
        got = out[key].get(col)
        assert (None if got is None else str(got)) == want, (key, col, out[key])
    assert missing == 0, missing
    assert base["SFDC/d4/quote.pdf"]["sf_op_id"] is None and base["SFDC/d1/opp.pdf"] == out["SFDC/d1/opp.pdf"], base["SFDC/d4/quote.pdf"]
    assert str(M._date("20250210")) == "2025-02-10" and M._date("bad") is None and M._ts("20250211080000").hour == 8  # EDW 글자 꼴
    # Quote 표가 없는 EDW(서버 지금) — 그 단계만 건너뜀, 나머지는 그대로
    e2 = _edw(str(d / "edw2.sqlite"), quote=False)
    try:
        out2, _ = M.fetch(DOCS, e2, _chain())
    finally:
        e2.close()
    assert out2["SFDC/d4/quote.pdf"]["sf_op_id"] is None and out2["SFDC/d1/opp.pdf"]["sf_op_id"] == "006A", out2
    # EDW를 못 엶 — 빈 결과와 전부 메타 없음(적재는 계속)
    with patch.object(M, "_Edw", side_effect=RuntimeError("no account")):
        assert M.fetch(DOCS) == ({}, len(DOCS))
    bad = [  # (설정 고치기, 오류 글자에 들어갈 말) — 이름은 SQL에 들어가므로 검사
        (lambda c: c["sfdc"]["opportunity"].__setitem__("table", "SFDC.Opportunity; DROP"), "sfdc.opportunity.table"),
        (lambda c: c["crms"]["docu"].pop("created"), "crms.docu.created: 없음"),
        (lambda c: c["crms"]["project"]["out"].__setitem__("sf_op_id", "X"), "crms에서 설정으로 채울 수 없는 칸"),
        (lambda c: c["crms"]["project"]["out"].__setitem__("file_path", "X"), "crms에서 설정으로 채울 수 없는 칸"),  # 문서 키 덮어쓰기 막음
        (lambda c: c["sfdc"]["opportunity"]["out"].__setitem__("client_edw", "Name"), "sfdc에서 설정으로 채울 수 없는 칸"),
        (lambda c: c["sfdc"]["steps"].append({"prefix": "0Q0", "table": "SFDC.Quote"}), "sfdc.steps[3].id: 없음"),
        (lambda c: c["sfdc"].__setitem__("opp_prefix", "06"), "sfdc.opp_prefix"),
    ]
    import yaml

    for fix, want in bad:
        c = _chain(quote=False)
        fix(c)
        f = d / "chain.yaml"
        f.write_text(yaml.safe_dump(c, allow_unicode=True), encoding="utf-8")
        try:
            M.load_chain(f)
            raise AssertionError(f"틀린 설정이 받아짐: {want}")
        except ValueError as e:
            assert want in str(e), (want, str(e))
    print(
        f"[시험] pl-29 EDW 조인 — 사례 {len(cases)}개(SFDC 4단계·계정 직접·동률 비움·CRMS·LAS 최신 판·FAQ) · Quote 표 없음 · EDW 없음 · 기본 설정(Quote 없음) · 틀린 설정 {len(bad)}개 거부 통과"
    )
