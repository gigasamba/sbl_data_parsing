"""pl-33 분류(사용자 11-02) — 가짜 LLM으로 표 행 시험(네트워크·EDW·PG 없음). 라벨 읽기(운영 별칭·LAS 집합)·집합 밖은 실패·다시 묻지
않음·이미 있는 라벨 안 덮음·SFDC·LAS 말고는 건너뜀·운영과 같은 사용자 쪽 글(LAS 키워드 근거·SFDC 힌트 줄·제목 키워드 묶음), 그리고 적재(pgvector_load.load)가 gold doc_class를 넣고 실패한 문서는 넣지 않는지(SQLite 대역).
글 모양의 기대값은 운영 코드(extract_evidence·build_user_prompt·fams)로 만든 글과 바이트 대조한 것(11-02)."""

import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from common.config.settings import COMMON
from pipeline.load import classify as CL

ANSWERS = [  # (원천, 응답 글자, 기대 라벨)
    ("sfdc", '{"class": "Proposal", "confidence": 0.9}', "Proposal"),
    ("sfdc", '```json\n{"class": "rfp", "confidence": 0.8}\n```', "RFP"),  # 코드 울타리·소문자
    ("sfdc", '{"class": "RFP+RFI", "confidence": 0.6}', "RFI+RFP"),  # 별칭
    ("sfdc", '{"class": "RFI + RFP"}', "RFI+RFP"),  # 공백
    ("sfdc", 'reasoning first… {"doc_class": "Other", "confidence": 1}', "Other"),  # 앞 글 뒤 JSON · doc_class 키(운영과 같음)
    ("sfdc", '{"class": "Others"}', None),  # 집합 밖 — 실패(다시 묻지 않음)
    ("sfdc", '{"class": true}', None),
    ("sfdc", "not json", None),
    ("sfdc", "", None),
    ("las", '{"class": "Assignment Letter", "confidence": 0.9}', "Assignment Letter"),
    ("las", ' {"class": " QAG "}', "QAG"),  # 앞뒤 공백만 정리(운영 strip)
    ("las", '{"class": "assignment letter"}', None),  # 대소문자 바로잡지 않음(운영 LAS와 같음) — 집합 밖
    ("las", '{"class": "RFP"}', None),  # 다른 원천의 라벨
    ("las", '{"doc_class": "MSA"}', None),  # LAS는 class 키만(운영 parse_json)
]


def test_parse_answer_table():
    for src, text, want in ANSWERS:
        assert CL.parse_answer(text, src) == want, (src, text, CL.parse_answer(text, src))


def test_fams_table():
    rows = [  # (제목, 기대 묶음) — FAMILIES 순서, system이 있으면 system만
        ("RFP for proposal pricing", ["rfp", "proposal", "pricing"]),
        ("Log-2024 RFP", ["system"]),
        ("Bid evaluation tender", ["rfq"]),
        ("제안서 견적", ["proposal", "pricing"]),
        ("", []),
        (None, []),
    ]
    for title, want in rows:
        assert CL.fams(title) == want, (title, CL.fams(title))


H = "## Keyword Evidence (evaluate by Signal Priority ①→②→③→④)\n"


def test_las_evidence_table():
    rows = [  # (파일 이름, 본문, 기대 글 — 운영 extract_evidence와 바이트 같음)
        (
            "QAG_Amendment_No2.pdf",
            "THIS QUALITY AGREEMENT is made",
            H + "  Signal①(BODY OPENING): Document starts with 'QAG' self-identification\n"
            "  Signal②(BODY first-2000): QAG('QUALITY AGREEMEN')\n  Signal③(TITLE keywords): QAG(abbr:'QAG')\n"
            "  Signal④(AMENDMENT): YES — title contains amendment keyword\n\n⚠ Amendment keyword present — check parent\n"
            "  → SIGNALS CONFLICT — you MUST lower confidence to ≤0.80",
        ),
        (
            "decision_memo.pdf",
            "internal note",
            H + "  Signal①(BODY OPENING): 'internal note' (no clear self-ID in first line)\n  Signal②(BODY first-2000): (none)\n"
            "  Signal③(TITLE keywords): (none)\n\n⚠ Title reference keyword 'decision' — may be REPORT/MEMO context\n"
            "  → SIGNALS CONFLICT — you MUST lower confidence to ≤0.80",
        ),
        (
            "x.pdf",
            "",
            H
            + "  Signal①(BODY OPENING): '' (no clear self-ID in first line)\n  Signal②(BODY first-2000): (none)\n  Signal③(TITLE keywords): (none)",
        ),
    ]
    for fn, body, want in rows:
        assert CL.las_evidence(fn, body) == want, (fn, CL.las_evidence(fn, body))
    got = CL.las_evidence("PSA_v1.pdf", "Master Services Agreement and Product Specific Agreement")
    assert "⚠ MULTIPLE TYPE SIGNALS: MSA, PSA" in got, got  # 두 종류 — 충돌 경고


def test_user_message_shapes():
    text = "y" * 9000
    rep = {"text": text, "format": "pdf", "engine": "docling"}
    doc = {
        "file_path": "SFDC/u1/RFP_answer.pdf",
        "title": "RFP answer pricing",
        "entity_type": "Opportunity",
        "entity_class": "opportunity",
        "entity_id": "006A",
        "stagename": "Proposal",
        "real_rfp__c": "1",
        "rfp_received_start_date__c": date(2026, 3, 2),
    }
    m = CL.sfdc_user(doc, rep)
    assert m.startswith(
        "## Document metadata\n- Title: RFP answer pricing\n- Original filename: RFP_answer.pdf\n"
        "- File format: pdf (representative parse engine: docling)\n- SFDC entity: type=Opportunity class=opportunity id=006A\n"
        "- Opportunity: stage=Proposal, Real_RFP__c=1, rfp_window=2026-03-02~\n- Title keyword families: rfp|pricing\n\n"
        "## Document text (first 8000 chars of parsed Markdown)\n"
    ), m[:600]
    assert m.endswith("y" * CL.TEXT_CHARS) and "y" * (CL.TEXT_CHARS + 1) not in m  # 본문은 앞 8,000자만
    m = CL.sfdc_user(
        {
            "file_path": "SFDC/u2/Bid v1.pdf",
            "entity_class": "task",
            "entity_type": "Task",
            "sent_received__c": "Sent",
            "subject": "s" * 400,
        },
        rep,
    )
    assert "- Title: Bid v1.pdf\n" in m and f"- Communication channel: direction=Sent, subject={'s' * 300}\n" in m, m[
        :700
    ]  # 제목 없음 → 파일 이름
    assert "- Title keyword families: rfq\n" in m and "- Opportunity:" not in m
    m = CL.sfdc_user({"file_path": "SFDC/u3/a.pdf"}, rep)  # EDW 사슬 없음 — 힌트 줄 없음(운영의 FEATURES 행 없음)
    assert "- SFDC entity" not in m and "keyword families" not in m
    m = CL.las_user(
        {"file_path": "LAS/u4/QAG_v1.pdf", "approvalname": "QAG 승인", "client_edw": "A사"},
        {"text": "THIS QUALITY AGREEMENT", "format": "pdf"},
    )
    assert m.startswith(
        "## Document metadata\n- Original filename: QAG_v1.pdf\n- File format: pdf\n- Approval title: QAG 승인\n- Counterparty: A사\n\n" + H
    ), m
    assert "\n## Document text (first 8000 chars)\nTHIS QUALITY AGREEMENT" in m


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
                failed = CL.apply(
                    [d], {fp: {"text": text}}, {fp: gold_lab} if gold_lab else {}, audit_path=tmp / "a.jsonl", chat=fake(answer)
                )
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
                calls = []
                with patch("common.ai.llm.chat", lambda *a, **k: calls.append(1) or '{"class": "RFP"}'):
                    M.load(db, bundle(["SFDC/u/rfp.pdf"]))  # --replace 없이 이미 저장된 문서 — 적재가 건너뛰므로 부르지 않음
                assert calls == [], calls
            rows = {r["file_path"]: r["doc_class"] for r in sf.q(f"SELECT file_path, doc_class FROM {S}_sfdc.doc")}
        assert rows == {"SFDC/u/rfp.pdf": "RFP"}, rows  # 실패한 bad.pdf는 안 들어감 · 두 번째 답(Proposal)으로 덮지 않음
        assert counts["by_source"]["sfdc"]["docs"] == 1, counts
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_fake_llm_placeholder():
    """PC 가짜 LLM(local) — 모델을 부르지 않고 자리 라벨 Other(두 집합 모두에 있음)로 SFDC·LAS가 적재되게. 서버 RUN_ENV에서는 가짜 LLM 거부 그대로."""
    assert all(CL.FAKE_LABEL in labs for labs in CL.LABELS.values())
    for run_env, want in ((None, "ok"), ("local", "ok"), ("dev", "refuse"), ("prd", "refuse")):
        with COMMON.env(LLM_FAKE="1", RUN_ENV=run_env), patch.object(CL, "_system", lambda src: "system"):
            for src in ("sfdc", "las"):
                lab, note = CL.classify_one(src, {"file_path": "x"}, {"text": "body"})
                if lab == CL.FAKE_LABEL and "가짜 LLM" in (note or ""):
                    got = "ok"
                else:  # 서버 — 가짜 LLM 거부는 그 문서만 실패(적재 전체를 멈추지 않음)
                    got = "refuse" if lab is None and (note or "").startswith("RuntimeError") else f"label {lab}"
                assert got == want, (run_env, src, got, note)
