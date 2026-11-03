"""pl-29·pl-52 — 적재 때 EDW 조인(pipeline/load/edw_meta.py): 사슬 파일(steps·fields)로 client_edw·등록 시각·attrs. 임시 SQLite EDW(가짜 데이터만,
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
CREATE TABLE CRMS.RM_CM_PJTLIST (RM_CONTRACT_CODE TEXT COLLATE NOCASE, SF_ACC_NAME TEXT, DIVISION TEXT, RM_CONTRACT_NAME TEXT, INIT_DTTM TEXT);
CREATE TABLE CRMS.RM_CM_DOCU (RM_CONTRACT_CODE TEXT, GATE_CODE TEXT, GATE_VERSION TEXT, DOCU_SEQ INT, INIT_DTTM TEXT);
CREATE TABLE LAS.Contract (ManageNo TEXT, ContractID INT, IsActive INT, ContractDate TEXT, PartnerCorpName TEXT);
CREATE TABLE LAS.FileManager (FileID INT, CreateDate TEXT);
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
        ("CRMS/c2/b.docx", "CRMS", None, None),  # 열쇠 꼴(P1-2): CHAR 채움·소문자 — 서버 MSSQL(CI 정렬)과 같은 짝
        ("LAS/l2/n.pdf", "LAS", None, None),  # 열쇠 꼴: 채움 · int 칸(FileID)에 글자 열쇠
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
    "AI.FileStorageMap_CRMS": [("CRMS/c1/a.docx", "RC-9", "G1", "1", 3), ("CRMS/c2/b.docx", "rc-8   ", "G1", "1", 4)],
    "CRMS.RM_CM_PJTLIST": [("RC-9", "Gamma", "DS", "Contract X", "2025-02-10"), ("RC-8", "Delta  ", "CD", "Contract Y", "2025-02-12")],
    "CRMS.RM_CM_DOCU": [("RC-9", "G1", "1", 3, "2025-02-11 08:00:00")],
    "AI.FileStorageMap_LAS": [("LAS/l1/m.pdf", "M-1", "F1", "2025-03-05"), ("LAS/l2/n.pdf", "M-2   ", "7", None)],
    "LAS.Contract": [
        ("M-1", 1, 0, "2025-03-02", None),
        ("M-1", 2, 1, "2025-03-03", ""),  # 최신 판 = IsActive 1
        ("M-2", 9, 1, "2025-06-01", None),
        ("M-2", 10, 1, "2025-06-02", None),  # latest — ContractID 수로 비교(10 > 9, 글자면 "9"가 큼)
        ("M-2", 11, None, "2025-06-03", None),  # IsActive NULL — None은 가장 작음(TypeError 없음)
    ],
    "LAS.FileManager": [("F1", "2025-03-04 10:00:00"), (7, "2025-06-05 00:00:00")],
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


def _chain(quote=True):
    """기본 사슬(Quote 단계 없음 — 사용자 11-02) + (quote) Quote 단계를 켠 사본 — 설정 파일 주석대로 단계 한 줄 + 기회 열쇠 목록 끝에
    quote.OpportunityId."""
    c = copy.deepcopy(M.load_chain())
    if quote:
        steps = c["sfdc"]["steps"]
        at = next(i for i, s in enumerate(steps) if s["name"] == "opportunity")
        steps.insert(
            at, {"name": "quote", "table": "SFDC.Quote", "on": {"Id": "link.LinkedEntityId"}, "when": {"prefix": "0Q0"}, "optional": True}
        )
        steps[at + 1]["on"]["Id"].append("quote.OpportunityId")
    return c


def _flat(m):
    """fetch 결과 한 문서 → {created_at, client_edw, attrs 키…}(값 있는 것만)."""
    return {k: v for k, v in {"created_at": m["created_at"], "client_edw": m["client_edw"], **m["attrs"]}.items() if v not in (None, "")}


def _step(c, src, name):
    return next(s for s in c[src]["steps"] if s["name"] == name)


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
        ("CRMS/c2/b.docx", "client_edw", "Delta"),  # 'rc-8   ' ↔ 'RC-8' — 채움·대소문자 무시(값도 앞뒤 공백 뺌)
        ("CRMS/c2/b.docx", "contract_id", "rc-8"),
        ("LAS/l2/n.pdf", "contract_id", "M-2"),  # 채움 뺀 값
        ("LAS/l2/n.pdf", "contract_date", "2025-06-02"),  # latest(IsActive, ContractID) — 10 > 9, None 행은 뒤
        ("LAS/l2/n.pdf", "created_at", "2025-06-05 00:00:00"),  # FileID INT 7 ↔ 글자 '7'
    ]
    for key, col, want in cases:
        got = _flat(out[key]).get(col)
        assert (None if got is None else str(got)) == want, (key, col, out[key])
    assert missing == 0, missing
    assert "sf_op_id" not in base["SFDC/d4/quote.pdf"]["attrs"] and base["SFDC/d1/opp.pdf"] == out["SFDC/d1/opp.pdf"], base[
        "SFDC/d4/quote.pdf"
    ]
    assert str(M._date("20250210")) == "2025-02-10" and M._date("bad") is None and M._ts("20250211080000").hour == 8  # EDW 글자 꼴
    import json
    import uuid
    from decimal import Decimal

    u = uuid.UUID(int=1)
    values = [  # (EDW 값, 칸 꼴, 기대 attrs 값) — text는 늘 글자(JSON 수·Decimal 오류 없음 — P1-1)
        (123, {}, "123"),
        (Decimal("12.50"), {}, "12.50"),
        (u, {}, str(u)),
        ("  A  ", {}, "A"),
        ("   ", {}, None),
        (1234567, {"max": 3}, "123"),
        (True, {"type": "flag"}, "1"),
    ]
    for v, f, want in values:
        got = M._field({"s": [{"c": v}]}, "p", {"from": "s.c", **f})
        assert got == want and json.loads(json.dumps({"k": got})) == {"k": want}, (v, f, got)
    # Quote 표가 없는 EDW(서버 지금) — 그 단계만 건너뜀, 나머지는 그대로
    e2 = _edw(str(d / "edw2.sqlite"), quote=False)
    try:
        out2, _ = M.fetch(DOCS, e2, _chain())
    finally:
        e2.close()
    assert "sf_op_id" not in out2["SFDC/d4/quote.pdf"]["attrs"] and out2["SFDC/d1/opp.pdf"]["attrs"]["sf_op_id"] == "006A", out2
    # EDW를 못 엶 — 빈 결과와 전부 메타 없음(적재는 계속)
    with patch.object(M, "_Edw", side_effect=RuntimeError("no account")):
        assert M.fetch(DOCS) == ({}, len(DOCS))
    bad = [  # (설정 고치기, 오류 글자에 들어갈 말) — 이름은 SQL에 들어가므로 검사 · 참조·거르기 이름·형식(pl-52)
        (lambda c: _step(c, "sfdc", "opportunity").__setitem__("table", "SFDC.Opportunity; DROP"), "sfdc.steps[5].table"),
        (lambda c: _step(c, "crms", "docu").pop("on"), "crms.steps[3].on"),
        (lambda c: _step(c, "crms", "docu")["on"].__setitem__("DOCU_SEQ", "project.X"), "칸이 여럿이면"),
        (lambda c: _step(c, "sfdc", "link")["on"].__setitem__("ContentDocumentId", "nowhere.Id"), "앞에 없는 단계"),
        (lambda c: _step(c, "sfdc", "ent_task")["on"].__setitem__("Id", "entity.Name"), "칸 이름이 틀림"),  # sfdc_entity 칸은 Id·Type·Class
        (lambda c: _step(c, "sfdc", "task")["when"].__setitem__("prefix", "06"), "sfdc.steps[3].when"),
        (lambda c: c["sfdc"]["steps"][0]["on"].__setitem__("s3_key", "version.Id"), "첫 단계의 열쇠는 file"),
        (lambda c: c["crms"]["fields"]["division"].__setitem__("filter", "contract_id"), "겹침"),  # 원천 안 거르기 이름 하나
        (lambda c: c["crms"]["fields"]["division"].__setitem__("filter", "client"), "crms.fields.division.filter"),  # 고정 거르기
        (lambda c: c["las"]["fields"].__setitem__("doc_class", {"from": "map.manage_no"}), "attrs 키로 쓸 수 없는"),  # 분류가 쓰는 키
        (lambda c: c["crms"]["fields"].__setitem__("file_path", {"from": "map.s3_key"}), "attrs 키로 쓸 수 없는"),  # 고정 칸
        (lambda c: c["crms"]["fields"]["division"].__setitem__("type", "number"), "crms.fields.division.type"),
        (lambda c: c["crms"]["fields"]["division"].__setitem__("from", "project.DIVISION; --"), "칸 이름이 틀림"),
        (lambda c: c["las"].pop("created"), "las.created: 없음"),
        (lambda c: c.pop("faq"), "faq: 없음"),
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
        f"[시험] pl-29·pl-52 EDW 조인 — 사례 {len(cases)}개(SFDC 4단계·계정 직접·동률 비움·CRMS·LAS 최신 판·FAQ) · Quote 표 없음 · EDW 없음 · 기본 설정(Quote 없음) · 틀린 설정 {len(bad)}개 거부 통과"
    )


def test_chain_file_setting():
    """common.paths.edw_chain(= ops.paths.edw_chain — 적재·검색 MCP 같은 칸, 사용자 11-03) — 고친 사본을 쓰고, 없거나 틀린 파일은 기본 파일로 돌아가지 않고 거부 · --check는 파일만 봄."""
    import yaml

    from common.config.settings import COMMON

    d = Path(tempfile.mkdtemp())
    good, broken, notdict = d / "good.yaml", d / "broken.yaml", d / "list.yaml"
    good.write_text(yaml.safe_dump(_chain(quote=True), allow_unicode=True), encoding="utf-8")  # Quote 단계를 켠 사본
    broken.write_text("sfdc: [", encoding="utf-8")
    notdict.write_text("- a", encoding="utf-8")
    cases = [  # (설정 값, 기대 — SFDC 단계 수 또는 오류 글자)
        (None, 11),  # 비움 — 기본 파일(Quote 없음)
        (str(good), 12),  # 고친 사본이 쓰임
        (str(d / "none.yaml"), "못 읽음"),  # 없는 파일 — 조용히 기본으로 안 감
        (str(broken), "YAML 오류"),
        (str(notdict), "최상위가 사전"),
    ]
    for val, want in cases:
        with COMMON.env(EDW_CHAIN_FILE=val):
            try:
                got = len(M.load_chain()["sfdc"]["steps"])
            except ValueError as e:
                got = want if isinstance(want, str) and want in str(e) else str(e)
            rc, msg = M.check()
        assert got == want, (val, got)
        assert (rc == 0) == isinstance(want, int), (val, rc, msg)
    assert M.main(["--check", "--file", str(good)]) == 0 and M.main(["--check", "--file", str(broken)]) == 1
    print(f"[시험] pl-29 사슬 설정 파일 칸 — {len(cases)}개(기본·사본·없음·YAML 깨짐·사전 아님) · --check 통과")


HINT_SQL = """
ALTER TABLE SFDC.ContentVersion ADD COLUMN Title TEXT;
ALTER TABLE SFDC.Task ADD COLUMN Subject TEXT;
ALTER TABLE SFDC.Task ADD COLUMN Sent_Received__c TEXT;
ALTER TABLE SFDC.Event ADD COLUMN Subject TEXT;
ALTER TABLE SFDC.Event ADD COLUMN Sent_Received__c TEXT;
ALTER TABLE SFDC.Opportunity ADD COLUMN StageName TEXT;
ALTER TABLE SFDC.Opportunity ADD COLUMN Real_RFP__c INT;
ALTER TABLE SFDC.Opportunity ADD COLUMN RFP_Received_Start_Date__c TEXT;
ALTER TABLE SFDC.Opportunity ADD COLUMN RFP_Received_End_Date__c TEXT;
ALTER TABLE LAS.Contract ADD COLUMN ApprovalName TEXT;
UPDATE SFDC.ContentVersion SET Title = 'RFP reply' WHERE Id = 'cv2';
UPDATE SFDC.Task SET Subject = 'RE: ' || substr(hex(zeroblob(100)), 1, 196), Sent_Received__c = 'Received';
UPDATE SFDC.Opportunity SET StageName = 'RFP', Real_RFP__c = 1, RFP_Received_Start_Date__c = '2026-03-02' WHERE Id = '006A';
UPDATE LAS.Contract SET ApprovalName = 'QAG 승인' WHERE ContractID = 2;
INSERT INTO AI.FileStorageMap VALUES ('SFDC/d7/none.pdf', 'SFDC', 'cv7', NULL), ('SFDC/d8/user.pdf', 'SFDC', 'cv8', NULL),
    ('SFDC/d9/unk.pdf', 'SFDC', 'cv9', NULL);
INSERT INTO SFDC.ContentVersion (Id, ContentDocumentId, CreatedDate) VALUES ('cv7', 'cd7', NULL), ('cv8', 'cd8', NULL), ('cv9', 'cd9', NULL);
INSERT INTO SFDC.ContentDocumentLink VALUES ('cd8', '005USER', 0), ('cd9', 'a99X1', 0);
"""
HINT_KEYS = (
    "title",
    "entity_type",
    "entity_class",
    "entity_id",
    "sent_received__c",
    "subject",
    "stagename",
    "real_rfp__c",
    "rfp_received_start_date__c",
)


def test_hints():
    """분류 힌트 칸(pl-33, 운영 analyze_clues 규칙 — 사용자 11-02): 첫 User 아닌 연결(접두 순서 — User는 건너뜀) · 연결 없음 unlinked ·
    User만 user_only · 모르는 접두 Unknown:<접두>/other · Task 방향·제목 120자 · 연결 개체가 영업 기회일 때만 단계·RFP · LAS 품의 제목.
    힌트 칸이 없는 EDW(test_chains의 표)는 힌트만 비고 적재 메타는 그대로."""
    d = Path(tempfile.mkdtemp())
    e = _edw(str(d / "edw.sqlite"))
    try:
        e.cn.executescript(HINT_SQL)
        docs = [*DOCS, ("SFDC", "SFDC/d7/none.pdf"), ("SFDC", "SFDC/d8/user.pdf"), ("SFDC", "SFDC/d9/unk.pdf")]
        out, _ = M.fetch(docs, e, _chain())
    finally:
        e.close()
    subj = "RE: " + "0" * 116
    want = {  # (원본 경로) → HINT_KEYS 차례의 값
        "SFDC/d1/opp.pdf": (None, "Opportunity", "opportunity", "006A", None, None, "RFP", "1", "2026-03-02"),  # 005USER 건너뜀
        "SFDC/d2/task.pdf": ("RFP reply", "Task", "task", "00TT1", "Received", subj, None, None, None),
        "SFDC/d3/event.pdf": (None, "Event", "event", "00UE1", None, None, None, None, None),  # 빈 제목은 빼고 둠(pl-52 — 분류 글은 같음)
        "SFDC/d4/quote.pdf": (None, "Quote", "quote", "0Q0Q1", None, None, None, None, None),
        "SFDC/d6/tie.pdf": (None, "Account", "account", "001ACC1", None, None, None, None, None),  # 첫 연결(정렬) = 001
        "SFDC/d7/none.pdf": (None, None, "unlinked", None, None, None, None, None, None),
        "SFDC/d8/user.pdf": (None, None, "user_only", None, None, None, None, None, None),
        "SFDC/d9/unk.pdf": (None, "Unknown:a99", "other", "a99X1", None, None, None, None, None),
    }
    for key, vals in want.items():
        got = tuple(None if _flat(out[key]).get(k) is None else str(_flat(out[key]).get(k)) for k in HINT_KEYS)
        assert got == vals, (key, got)
    assert out["LAS/l1/m.pdf"]["attrs"]["approvalname"] == "QAG 승인" and out["SFDC/d1/opp.pdf"]["attrs"]["sf_op_id"] == "006A", out[
        "LAS/l1/m.pdf"
    ]
    e = _edw(str(d / "edw2.sqlite"))  # 힌트 칸 없는 EDW
    try:
        bare, _ = M.fetch(DOCS, e, _chain())
    finally:
        e.close()
    ta = bare["SFDC/d2/task.pdf"]["attrs"]
    assert ta["entity_class"] == "task" and "subject" not in ta, ta
    assert bare["SFDC/d1/opp.pdf"]["attrs"]["sf_op_id"] == "006A" and "approvalname" not in bare["LAS/l1/m.pdf"]["attrs"]
