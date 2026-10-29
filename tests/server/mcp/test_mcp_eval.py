"""mcp_server.cli.mcp_eval 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m mcp_server.cli.mcp_eval --selftest`."""

import json
from pathlib import Path

from mcp_server.cli.mcp_eval import (
    _EVIDENCE_META_COLS,
    _XLSX_NOTICE,
    QUESTIONS_DS,
    _doc_files,
    _norm_val,
    _rank_of,
    _rank_of_variants,
    _ref_metrics,
    _score_4clients,
    ids_for,
    load_question_items,
    parse_min_scores,
    render_markdown,
    score_fn_for,
    summarize,
    summarize_negative,
    write_xlsx,
)
from mcp_server.services.search import shaping as M
from mcp_server.services.search.synth_score import score as synth_score


def selftest():
    import tempfile

    assert ids_for("", "x") is None and ids_for("QA1, QA2", "x") == {"QA1", "QA2"}
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "manifest.json"
        mp.write_text(json.dumps({"retrieval": {"synth-4clients": ["QA015"]}}), encoding="utf-8")
        assert ids_for(str(mp), "synth-4clients") == {"QA015"} and ids_for(str(mp), "synth-xling") == set()
    fn = _score_4clients({"gold_answer": "4%", "type": "latest_version"})
    assert fn("the price adjustment cap is 4% per annum") is True
    assert fn("no relevant info") is False
    assert _score_4clients({"gold_answer": "x", "type": "negative"}) is None
    kw_it = {
        "gold_answer": "491,000,000 KRW (C-MRH-2023-03, contract governs over negotiation email)",
        "type": "cross_document",
        "answer_keywords": ["491,000,000", "C-MRH-2023-03"],
    }
    fn_kw = _score_4clients(kw_it)  # answer_keywords 있으면 우선(c1bc27da) — 전체 gold 문장이 아니라 AND만(QA099 실측)
    assert fn_kw("최종 계약(C-MRH-2023-03) 단가 491,000,000 KRW가 유효합니다.") is True
    assert fn_kw("491,000,000 KRW만 언급") is False  # C-MRH-2023-03 빠짐 — AND 느슨해지면 안 됨
    item = {"answer_keywords": ["10일"], "forbid_keywords": ["16일"]}
    assert synth_score(item, "VI 단계 보관 기간은 10일입니다") is True
    assert synth_score(item, "VI 단계 보관 기간은 16일입니다") is False
    assert synth_score(item, "모르겠습니다") is False
    rows = [
        {
            "hit5": True,
            "value_in_evidence": True,
            "ms": 10,
            "n_evidence": 5,
            "bytes": 100,
            "vector_used": True,
            "via_v": 3,
            "via_k": 2,
            "via_i": 0,
        },
        {
            "hit5": False,
            "value_in_evidence": None,
            "ms": 20,
            "n_evidence": 3,
            "bytes": 80,
            "vector_used": False,
            "via_v": 0,
            "via_k": 3,
            "via_i": 1,
        },
    ]
    s = summarize(rows, [1, 5])
    assert s["hit5"] == 0.5 and s["value_in_evidence"] == 1.0 and s["vector_used_rate"] == 0.5, s
    print("[selftest] 채점 재사용(_score_4clients·_synth_images_qa.score) · summarize 통과")

    # R3 — evidence_status 재계산·summarize 분포(서버 호출 없이, mcp_server.services.search.shaping.evidence_status 그대로 재사용)
    assert parse_min_scores("none,0,0.1") == [None, 0.0, 0.1]
    mins = [None, 0.1]
    ev_found = [{"text": "계약 C-001 금액은 100 USD", "score": 0.9}]
    ev_none = []
    rows2 = [
        {
            "id": "Q1",
            "status": {k: M.evidence_status("C-001 계약 금액은?", ev_found, s)[0] for k, s in zip(("kw_only", "0.1"), mins)},
            "n_evidence": 1,
            "bytes": 10,
            "ms": 1,
            "vector_used": True,
            "via_v": 1,
            "via_k": 0,
            "via_i": 0,
        },
        {
            "id": "Q2",
            "status": {k: M.evidence_status("C-001 계약 금액은?", ev_none, s)[0] for k, s in zip(("kw_only", "0.1"), mins)},
            "n_evidence": 0,
            "bytes": 5,
            "ms": 1,
            "vector_used": False,
            "via_v": 0,
            "via_k": 0,
            "via_i": 0,
        },
    ]
    s2 = summarize(rows2, [1], mins)
    assert s2["evidence_status"]["kw_only"]["found"] == 0.5 and s2["evidence_status"]["kw_only"]["none"] == 0.5, s2
    sneg = summarize_negative(rows2, mins)
    assert sneg["false_positive@kw_only"] == 0.5 and sneg["true_negative@kw_only"] == 0.5, sneg  # Q1=found(오탐)·Q2=none(정탐)

    # R1 — 집계 문항(aggregate 경로 감지·answer 일치) 요약
    rows3 = [
        {
            "id": "QA072",
            "agg_type": "aggregate",
            "agg_via": True,
            "agg_hit": True,
            "n_evidence": 1,
            "bytes": 1,
            "ms": 1,
            "vector_used": False,
        },
        {
            "id": "QA021",
            "agg_type": "aggregate",
            "agg_via": False,
            "agg_hit": None,
            "n_evidence": 1,
            "bytes": 1,
            "ms": 1,
            "vector_used": False,
        },
    ]
    s3 = summarize(rows3, [1])
    assert s3["agg_n"] == 2 and s3["agg_via_rate"] == 0.5 and s3["agg_hit_rate"] == 1.0, s3  # agg_hit=None(안 감지)은 정답률 분모에서 빠짐
    assert _norm_val("10,150,000 USD") == _norm_val("10150000 usd")
    print("[selftest] R3 evidence_status 재계산·negative 정탐·오탐 · R1 집계 문항 summarize 통과")

    # engine-qa BLOCK 3 — via=aggregate 근거가 맨 앞이면 hit1(위치 그대로)은 깨지지만 hit1_doc(집계 건너뜀)은 안 깨짐(AD42 재현)
    ev_agg = [{"via": "aggregate", "text": "[집계] 2"}, {"file_name": "gold.pdf", "via": "k"}, {"file_name": "other.pdf", "via": "v"}]
    files_agg = [e.get("file_name") for e in ev_agg]
    gold = {"gold.pdf"}
    assert _rank_of(files_agg, gold) == 2, files_agg  # 집계 근거 때문에 문서 순위가 한 칸 밀림(옛 hit1 — 그대로 유지)
    assert _rank_of(_doc_files(ev_agg, files_agg), gold) == 1  # hit1_doc — 집계 근거를 건너뛰면 실제 1위

    # R2-c 요건① 스코어링 변경 — gold가 사본 그룹의 variants 안에만 있어도 대표 슬롯에서 적중(before=_rank_of는 못 찾음)
    ev_var = [{"file_name": "rep.eml", "variants": ["rep.msg"], "via": "k"}, {"file_name": "other.pdf", "via": "v"}]
    gold_variant = {"rep.msg"}
    assert _rank_of([e.get("file_name") for e in ev_var], gold_variant) is None  # before — variants는 안 봄(miss)
    assert _rank_of_variants(ev_var, gold_variant) == 1  # after — 대표의 variants로 1위 적중
    assert _rank_of_variants(ev_var, {"rep.eml"}) == 1  # 대표 자신도 그대로 적중
    assert _rank_of_variants(ev_var, {"없는.pdf"}) is None
    print("[selftest] R2-c 스코어링 변경 — hit{k}_variant(사본 그룹 variants 포함 적중) 전후 비교 통과")
    rows4 = [
        {
            "id": "QA1",
            "hit1": False,
            "hit1_doc": True,
            "hit5": True,
            "hit5_doc": True,
            "n_evidence": 3,
            "bytes": 1,
            "ms": 1,
            "vector_used": True,
        }
    ]
    s4 = summarize(rows4, [1, 5])
    assert s4["hit1"] == 0.0 and s4["hit1_doc"] == 1.0 and s4["hit5"] == 1.0 and s4["hit5_doc"] == 1.0, s4
    print("[selftest] engine-qa BLOCK 3 — hit1_doc·hit5_doc(집계 근거 건너뛴 문서 순위) 통과")

    import importlib.util as _ilu

    if _ilu.find_spec("openpyxl") is None:  # 10-15 — openpyxl은 PC 보고서용(이미지에 없음)
        print("[selftest] --xlsx 부분 건너뜀 — openpyxl 없음(이미지)")
    else:
        # --xlsx — 시트 2개('요약'·'근거')·칸(질문·근거 원문·AD44 RDB 메타) 확인(서버 없이, write_xlsx만)
        import tempfile

        from openpyxl import load_workbook

        xlsx_data = {
            "synth-demo": [
                {
                    "id": "Q1",
                    "question": "C-001 계약 금액은?",
                    "gold_docs": {"a.pdf"},
                    "gold_answer": "100 USD",
                    "row": {"hit1": True, "hit5": True, "value_in_evidence": True, "status": {"kw_only": "found"}},
                    "evidence": [
                        {
                            "rank": 1,
                            "file_name": "a.pdf",
                            "page": 2,
                            "line": 10,
                            "source_uri": "s3://x/a.pdf",
                            "doc_key": "k1",
                            "chunk_key": "k1:0",
                            "client": "Acme",
                            "contract_no": "C-001",
                            "score": 0.9,
                            "via": "v",
                            "text": "계약 C-001 금액은 100 USD" * 20,  # 제어문자 포함 — xlsx에서 지우고 저장되는지
                            "doc_type": "CONTRACT",
                            "version": "1",
                            "supersedes_doc_id": None,
                            "is_deleted": False,
                            "contract_id": "C-RDB-1",
                            "updated_at": "2025-01-01",
                            "company": "CL-1",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "t.xlsx"
            write_xlsx(xlsx_data, out)
            wb = load_workbook(out)
            assert wb.sheetnames == ["요약", "근거"], wb.sheetnames
            s, e = wb["요약"], wb["근거"]
            assert s["A1"].value == _XLSX_NOTICE and e["A1"].value == _XLSX_NOTICE
            assert [c.value for c in next(s.iter_rows(min_row=2, max_row=2))] == [
                "세트",
                "문항 ID",
                "질문",
                "정답 문서",
                "정답 값",
                "hit@1",
                "hit@5",
                "value_in_evidence",
                "evidence_status",
            ]
            srow = [c.value for c in next(s.iter_rows(min_row=3, max_row=3))]
            assert srow[:5] == ["synth-demo", "Q1", "C-001 계약 금액은?", "a.pdf", "100 USD"] and srow[5:7] == [True, True], srow
            ehead = [c.value for c in next(e.iter_rows(min_row=2, max_row=2))]
            assert ehead[-7:] == _EVIDENCE_META_COLS, ehead
            erow = [c.value for c in next(e.iter_rows(min_row=3, max_row=3))]
            assert (
                erow[2] == 1
                and erow[3] == "a.pdf"
                and 0 < len(erow[13]) <= 200
                and not any(ord(ch) < 32 for ch in erow[13])
                and erow[-7:] == ["CONTRACT", "1", None, False, "C-RDB-1", "2025-01-01", "CL-1"]
            ), erow
        print("[selftest] --xlsx write_xlsx — 시트 2개('요약'·'근거')·반출 금지 표시·AD44 메타 칸 통과")

    # --questions — auto_questions.py 산출 jsonl 3문항(value·client·미확인 count) → gold_docs·채점 함수·제외 규칙(요건①)
    import tempfile as _tf

    rows_q = [
        {
            "id": "auto-value::0",
            "category": "value",
            "question": "D-1 문서에서 '단가'의 값은 얼마입니까?",
            "answer": "USD 10 / g",
            "gold_evidence": [{"file": "d1.pdf", "page": 1, "line": 3}],
        },
        {
            "id": "auto-client::0",
            "category": "client",
            "question": "고객사 가나바이오의 계약(번호 D-1) 단가은(는) 얼마입니까?",
            "answer": "USD 10 / g",
            "gold_evidence": [{"file": "d1.pdf", "page": 1, "line": 3}],
        },
        {
            "id": "auto-count::0",
            "category": "count",
            "client": "가나바이오",
            "question": "고객사 가나바이오와 맺은 서로 다른 계약 건수는 몇 건입니까?",
            "answer": 2,
            "unverified_docs": ["bad.eml"],
            "gold_evidence": [{"file": "d1.pdf"}, {"file": "d2.pdf"}],
        },
    ]
    with _tf.TemporaryDirectory() as td:
        qpath = Path(td) / "questions.jsonl"
        qpath.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows_q), encoding="utf-8")
        items, raw = load_question_items(qpath)
        by_id = {it["id"]: it for it in items}
        assert by_id["auto-value::0"]["gold_docs"] == {"d1.pdf"} and not by_id["auto-value::0"]["excluded"]
        assert by_id["auto-count::0"]["gold_docs"] == set() and by_id["auto-count::0"]["excluded"], by_id[
            "auto-count::0"
        ]  # count+미확인 문서 → 제외
        fn_v = score_fn_for(QUESTIONS_DS, by_id["auto-value::0"], raw)
        assert fn_v("D-1 문서 단가: USD 10 / g") is True and fn_v("관련 없음") is False
        assert score_fn_for(QUESTIONS_DS, by_id["auto-count::0"], raw) is None  # 제외 문항은 채점 함수 없음
    print("[selftest] --questions load_question_items·score_fn_for — gold_docs(gold_evidence.file)·값 채점·count+미확인 제외 통과")

    # W20②③ — qa.json references(문서·image_id)·expected_attachments를 원본 그대로(gold_docs 유도와 별개) 채점
    ev_w20 = [
        {"file_name": "other.pdf", "image_ids": ["other.pdf#p1#i1"]},
        {"file_name": "edx_2023_lotB09.pdf", "image_ids": ["edx_2023_lotB09.pdf#p1#i1"]},
    ]
    files_w20 = [e["file_name"] for e in ev_w20]
    raw_ref = {"references": [{"doc": "edx_2023_lotB09.pdf", "path": "x", "where": "1쪽 그림", "image_id": "edx_2023_lotB09.pdf#p1#i1"}]}
    m_ref = _ref_metrics(raw_ref, ev_w20, files_w20, [1, 5], 5)
    assert m_ref["ref_doc_hit1"] is False and m_ref["ref_doc_hit5"] is True and m_ref["ref_image_hit"] is True, m_ref
    raw_ref_miss = {"references": [{"doc": "edx_2023_lotB09.pdf", "image_id": "없는#i9"}]}
    m_ref_miss = _ref_metrics(raw_ref_miss, ev_w20, files_w20, [1, 5], 5)
    assert m_ref_miss["ref_doc_hit5"] is True and m_ref_miss["ref_image_hit"] is False, m_ref_miss  # 문서는 맞고 그림은 틀림
    assert _ref_metrics({}, ev_w20, files_w20, [1, 5], 5) == {}  # references·attachments 둘 다 없으면 빈 dict(기존 세트 영향 없음)
    raw_att = {"expected_attachments": ["edx_2023_lotB09.pdf#p1#i1", "없는#i9"]}
    m_att = _ref_metrics(raw_att, ev_w20, files_w20, [1, 5], 5)
    assert m_att["attach_hit"] is True and m_att["attach_precision"] == 0.5, m_att  # 반환 그림 2개 중 1개만 기대 image_id
    assert _ref_metrics({"expected_attachments": ["없는#i9"]}, [], [], [1, 5], 5)["attach_hit"] is False
    assert (
        _ref_metrics({"expected_attachments": ["없는#i9"]}, [], [], [1, 5], 5)["attach_precision"] is None
    )  # 반환 그림 자체가 없음(분모 0)
    rows4b = [
        {
            "ref_doc_hit1": False,
            "ref_doc_hit5": True,
            "ref_image_hit": True,
            "attach_hit": True,
            "attach_precision": 0.5,
            "n_evidence": 2,
            "bytes": 1,
            "ms": 1,
            "vector_used": True,
        },
        {
            "ref_doc_hit1": True,
            "ref_doc_hit5": True,
            "ref_image_hit": False,
            "attach_hit": False,
            "attach_precision": None,
            "n_evidence": 2,
            "bytes": 1,
            "ms": 1,
            "vector_used": True,
        },
    ]
    s4b = summarize(rows4b, [1, 5])
    assert s4b["ref_doc_hit1"] == 0.5 and s4b["ref_doc_hit5"] == 1.0 and s4b["ref_image_hit"] == 0.5, s4b
    assert s4b["attach_hit"] == 0.5 and s4b["attach_precision"] == 0.5, s4b  # None인 attach_precision은 평균에서 빠짐
    md_w20 = render_markdown(
        {
            "ts": "t",
            "k": 5,
            "methods": ["vector"],
            "pool": False,
            "concurrency": 1,
            "ks": [1, 5],
            "sets": {"synth-confuse": {"n": 2, "summary": s4b}},
        }
    )
    assert "ref_doc_hit@1" in md_w20 and "attach_precision" in md_w20
    print("[selftest] W20②③ — references(ref_doc_hit{k}·ref_image_hit)·expected_attachments(attach_hit·attach_precision) 통과")


def test_main():  # 옛 `--selftest` 갈래(main()의 `if a.selftest: selftest()`)
    selftest()
