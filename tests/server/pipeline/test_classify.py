"""pl-33 분류(사용자 11-02) — 가짜 LLM으로 표 행 시험(네트워크·EDW·PG 없음). 라벨 읽기·별칭·집합 밖은 실패·다시 묻지 않음·이미 있는
라벨 안 덮음·SFDC·LAS 말고는 건너뜀·LAS 키워드 근거·사용자 쪽 글 모양, 그리고 적재(pgvector_load.load)가 gold doc_class를 넣고
분류에 실패한 문서는 넣지 않는지(검색 스키마 SQLite 대역)."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from common.config.settings import COMMON
from pipeline.load import classify as CL

ANSWERS = [  # (원천, 응답 글자, 기대 라벨)
    ("sfdc", '{"class": "Proposal", "confidence": 0.9}', "Proposal"),
    ("sfdc", '```json\n{"class": "rfp", "confidence": 0.8}\n```', "RFP"),  # 코드 울타리·소문자
    ("sfdc", '{"class": "RFP+RFI", "confidence": 0.6}', "RFI+RFP"),  # 별칭
    ("sfdc", '{"class": "RFI + RFP"}', "RFI+RFP"),  # 공백
    ("sfdc", 'reasoning first… {"class": "Other", "confidence": 1}', "Other"),  # 앞 글 뒤 JSON
    ("sfdc", '{"class": "Others"}', None),  # 집합 밖 — NULL(다시 묻지 않음)
    ("sfdc", '{"class": true}', None),
    ("sfdc", "not json", None),
    ("sfdc", "", None),
    ("las", '{"class": "assignment letter"}', "Assignment Letter"),
    ("las", '{"class": "QAG"}', "QAG"),
    ("las", '{"class": "RFP"}', None),  # 다른 원천의 라벨
]


def test_parse_answer_table():
    for src, text, want in ANSWERS:
        assert CL.parse_answer(text, src) == want, (src, text, CL.parse_answer(text, src))


def test_las_signals_table():
    rows = [  # (파일 이름, 본문, 들어 있어야 할 글 조각들)
        (
            "QAG_Addendum_2.pdf",
            "THIS QUALITY AGREEMENT is made …",
            ["THIS QUALITY AGREEMENT", "② 본문 앞 2,000자의 계약 종류 이름: QAG", "③ 파일 이름 키워드: QAG"],
        ),
        ("MSA_draft.docx", "Master Services Agreement between …", ["③ 파일 이름 키워드: 없음", "MSA"]),  # MSA 약어는 파일 이름에서 안 셈
        ("LOI_amendment.pdf", "Letter of Intent … amendment", ["④ 파일 이름 변경 키워드: 있음", "두 종류 이상"]),
        ("decision_memo.pdf", "internal note", ["뚜렷한 자기 이름 없음", "보고서·메모처럼"]),
    ]
    for name, text, frags in rows:
        got = "\n".join(CL.las_signals(name, text))
        for f in frags:
            assert f in got, (name, f, got)


def test_user_message_blocks():
    doc = {"file_path": "SFDC/u1/RFP_answer.pdf", "original_filename": "RFP_answer.pdf"}
    m = CL.user_message("sfdc", doc, {"title": "Answer", "stage": "Proposal", "entities": "영업 기회"}, "x" * 9000)
    assert "## 문서 정보" in m and "- 제목: Answer" in m and "- 기회 단계: Proposal" in m and "## 키워드 근거" not in m
    assert m.endswith("x" * CL.TEXT_CHARS) and "x" * (CL.TEXT_CHARS + 1) not in m  # 본문은 앞 8,000자만
    m = CL.user_message("las", {"file_path": "LAS/u2/QAG.pdf"}, {"counterparty": "A사"}, "THIS QUALITY AGREEMENT")
    assert "- 상대방: A사" in m and "## 키워드 근거" in m and "- 파일 형식: pdf" in m


def test_apply_table():
    calls = []

    def fake(answer):
        def chat(messages, **kw):
            calls.append(kw.get("agent"))
            if answer is RuntimeError:
                raise RuntimeError("model down")
            return answer

        return chat

    rows = [  # (원천, 묶음 라벨, gold 라벨, 본문, 가짜 답, 기대 라벨, 부른 횟수, 실패)
        ("SFDC", None, None, "body", '{"class": "RFP"}', "RFP", 1, False),
        ("SFDC", None, None, "body", '{"class": "Unknown"}', None, 1, True),  # 집합 밖 — 실패, 한 번만 부름
        ("SFDC", None, None, "body", RuntimeError, None, 1, True),  # 모델 장애 — 실패, 다시 안 부름
        ("SFDC", None, "Proposal", "body", '{"class": "RFP"}', "Proposal", 0, False),  # gold 라벨 — 덮지 않음, 안 부름
        ("LAS", "MSA", None, "body", '{"class": "LOI"}', "MSA", 0, False),  # 묶음에 이미 라벨
        ("SFDC", None, None, "", '{"class": "RFP"}', None, 0, True),  # 본문 없음 — 실패, 안 부름
        ("CRMS", None, None, "body", '{"class": "RFP"}', None, 0, False),  # 대상 원천 아님
        ("LAS-test", None, None, "body", '{"class": "PSA"}', "PSA", 1, False),  # -test 표기도 LAS
    ]
    tmp = Path(tempfile.mkdtemp())
    try:
        for i, (sys_, bundle_lab, gold_lab, text, answer, want, n_calls, fail) in enumerate(rows):
            calls.clear()
            fp = f"{sys_}/u{i}/doc{i}.pdf"
            d = {"file_path": fp, "source_system": sys_, **({"doc_class": bundle_lab} if bundle_lab else {})}
            with patch.object(CL, "_system", lambda src: "system"):
                failed = CL.apply([d], {fp: text}, {}, {fp: gold_lab} if gold_lab else {}, audit_path=tmp / "a.jsonl", chat=fake(answer))
            assert d.get("doc_class") == want and len(calls) == n_calls and (fp in failed) == fail, (i, d, calls, failed)
        audit = [json.loads(x) for x in (tmp / "a.jsonl").read_text(encoding="utf-8").splitlines()]
        assert {a["error"] is None for a in audit} == {True, False} and "model" not in audit[0], audit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_load_labels_and_skips_failed():
    """적재(pgvector_load.load)가 SFDC 문서를 분류해 gold doc.doc_class에 넣는다. 분류에 실패한 문서는 그 문서의 적재 실패로 gold에 넣지
    않는다(다음 정상 실행이 다시 고름 — 사용자 11-02). 다시 적재(--replace)해도 이미 있는 라벨은 덮지 않는다. 검색 스키마는 SQLite 대역."""
    import numpy as np

    from common.store import pg_standin as PS
    from common.store.db.dbtool import standin_script
    from pipeline.load import pgvector_load as M

    S, dim = "orca_pl33_t", 4
    tmp = Path(tempfile.mkdtemp())

    def bundle(paths):
        d = Path(tempfile.mkdtemp(dir=tmp))
        (d / "meta.json").write_text(json.dumps({"dim": dim, "embed_model": "test"}), encoding="utf-8")
        docs, chunks = [], []
        for i, fp in enumerate(paths):
            docs.append({"file_path": fp, "source_system": "SFDC", "summary": "s", "full_text": f"Request for Proposal {fp}"})
            ch = {"doc": i, "seq": 0, "page": 1, "line_start": 1, "line_end": 1, "char_start": 0, "char_end": 3, "bbox": None}
            ch.update({"section": None, "chunk_text": "RFP", "n_chars": 3, "n_terms": 1})
            chunks.append(ch)
        (d / "docs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in docs), encoding="utf-8")
        (d / "chunks.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in chunks), encoding="utf-8")
        np.save(d / "vectors.npy", np.ones((len(paths), dim), dtype="float32"))
        return d

    def chat(messages, **kw):  # bad.pdf만 집합 밖 답(실패)
        return '{"class": "Others"}' if "bad.pdf" in messages[-1]["content"] else '{"class": "RFP"}'

    try:
        with COMMON.env(PG_STANDIN_DIR=str(tmp / "pg")):
            db = PS.StandinPG(S)
            sf = PS.StandinPG(f"{S}_sfdc")
            with sf.cn.cursor() as cur:
                cur.execute(standin_script(f"{S}_sfdc", dim))
            with patch.object(CL, "_system", lambda src: "system"), patch("common.ai.llm.chat", chat):
                counts = M.load(db, bundle(["SFDC/u/rfp.pdf", "SFDC/u/bad.pdf"]))
                with patch("common.ai.llm.chat", lambda *a, **k: '{"class": "Proposal"}'):
                    M.load(db, bundle(["SFDC/u/rfp.pdf"]), replace=True)
            rows = {r["file_path"]: r["doc_class"] for r in sf.q(f"SELECT file_path, doc_class FROM {S}_sfdc.doc")}
        assert rows == {"SFDC/u/rfp.pdf": "RFP"}, rows  # 실패한 bad.pdf는 안 들어감 · 두 번째 답(Proposal)으로 덮지 않음
        assert counts["by_source"]["sfdc"]["docs"] == 1, counts
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_classify_context_from_edw():
    """분류 근거는 문서마다 EDW에서(운영 10-21 고정 파일 대신 — 사용자 11-02). 가짜 EDW(SQL 글자로 답을 고름) — 칸이 없는 조회(Title·Subject·
    ApprovalName)는 그 근거만 빠지고 나머지는 그대로."""
    from pipeline.load import edw_meta as E

    class Fake:
        def __init__(self, broken=()):
            self.broken = broken

        def q_in(self, sql, values):
            if any(b in sql for b in self.broken):
                raise RuntimeError("no such column")
            table = {
                "FROM AI.FileStorageMap f LEFT JOIN SFDC.ContentVersion": [
                    {"s3_key": "SFDC/u/a.pdf", "content_version_id": "068A", "doc_id": "069A", "created_at": None, "cv_created": None}
                ],
                "SELECT Id, Title FROM SFDC.ContentVersion": [{"Id": "068A", "Title": "Bid package"}],
                "FROM SFDC.ContentDocumentLink": [
                    {"ContentDocumentId": "069A", "LinkedEntityId": "006X"},
                    {"ContentDocumentId": "069A", "LinkedEntityId": "00TY"},
                ],
                "SELECT Id, Subject FROM SFDC.Task": [{"Id": "00TY", "Subject": "Sent: proposal v2"}],
                "SELECT Id, WhatId FROM SFDC.Task": [{"Id": "00TY", "WhatId": "006X"}],
                "SELECT Id, Name, StageName FROM SFDC.Opportunity": [{"Id": "006X", "Name": "Opp X", "StageName": "Proposal"}],
                "FROM SFDC.Opportunity": [{"Id": "006X", "Name": "Opp X", "AccountId": None}],
                "FROM AI.FileStorageMap_LAS WHERE": [{"s3_key": "LAS/u/q.pdf", "manage_no": "M-1"}],
                "ApprovalName FROM LAS.Contract": [
                    {"ManageNo": "M-1", "ContractID": 1, "IsActive": 1, "PartnerCorpName": "A사", "ApprovalName": "QAG 승인"}
                ],
                "PartnerCorpName FROM LAS.Contract": [{"ManageNo": "M-1", "ContractID": 1, "IsActive": 1, "PartnerCorpName": "A사"}],
            }
            return next((rows for k, rows in table.items() if k in sql), [])

        def close(self):
            pass

    docs = [("SFDC", "SFDC/u/a.pdf"), ("LAS", "LAS/u/q.pdf")]
    got = E.classify_context(docs, Fake())
    assert got["SFDC/u/a.pdf"] == {
        "title": "Bid package",
        "entities": "Task, 영업 기회",
        "channel": "Task: Sent: proposal v2",
        "opportunity": "Opp X",
        "stage": "Proposal",
    }, got
    assert got["LAS/u/q.pdf"] == {"approval_name": "QAG 승인", "counterparty": "A사"}, got
    got = E.classify_context(docs, Fake(broken=("Title", "Subject", "ApprovalName")))  # 서버 EDW에 그 칸이 없을 때
    assert got["SFDC/u/a.pdf"] == {"entities": "Task, 영업 기회", "opportunity": "Opp X", "stage": "Proposal"}, got
    assert got["LAS/u/q.pdf"] == {"counterparty": "A사"}, got
