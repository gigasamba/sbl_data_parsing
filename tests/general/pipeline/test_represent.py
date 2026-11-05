"""pipeline.transform.represent.doc_represent 시험."""

import json
from pathlib import Path

from common.config.settings import COMMON
from common.core.contract import source_record
from pipeline import config as pc
from pipeline.transform.represent.doc_represent import (
    apply_post,
    fill_scan_pages,
    fix_tables,
    represent,
    row_key,
    standardize_rep,
    status,
)


def selftest():
    r = {
        "tables": [{"cols": 3, "text": "항목 단가 수량(L) A-1 USD 1 500 B-2 USD 2 1,000"}],
        "facts": [{"context": ["A-1"], "cells": ["USD 1", "500"]}, {"context": ["B-2"], "cells": ["USD 2", "1,000"]}],
    }
    assert fix_tables(r) == {"headers": 1, "tab_rows": 0} and r["facts"][0]["cells"] == ["단가", "수량(L)"]
    r = {
        "tables": [{"cols": 3, "text": "Item Unit Price Qty (L) A-1 USD 1 500"}],
        "facts": [{"context": ["A-1"], "cells": ["USD 1", "500"]}],
    }
    assert fix_tables(r, ["| Item | Unit Price | Qty (L) |"])["headers"] == 1 and r["facts"][0]["cells"] == ["Unit Price", "Qty (L)"]
    r = {"text": "머리말\n항목\t단가\t수량(L)\t\tA-1\tUSD 1\t500\t\tB-2\tUSD 2\t1,000\t\t", "facts": []}
    assert fix_tables(r) == {"headers": 0, "tab_rows": 2} and r["facts"][2]["cells"] == ["USD 2", "1,000"]
    from common.core.repfmt import table_rows

    assert [(a, c[1]) for a, _, c in table_rows({"text": "", "facts": r["facts"]})] == [("A-1", "500"), ("B-2", "1,000")]
    keys = {row_key({"context": ["A-1"], "cells": ["1,000"]})}  # E2: 표기만 다른 같은 행은 보충하지 않음
    assert row_key({"context": ["A-1 "], "cells": ["1000"]}) in keys and row_key({"context": ["a-1"]}) in keys
    assert row_key({"context": ["B-2"], "cells": ["1,000"]}) not in keys
    assert status({"error": None}) == "성공" and status({"error": "TimeoutError: x"}) == "시간 초과"
    assert status({"error": "ImportError: x (미설치)"}) == "환경" and status({"error": "ValueError: x"}) == "실패"
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "a.pdf").write_bytes(b"x")
    with COMMON.env(SOURCE_URI_PREFIX="s3://bucket/raw/", SOURCE_MANIFEST=None):  # op-09 — 인계 파일(contract.py)도 설정 객체로 읽음
        s = source_record(d, "a.pdf")
    assert s["uri"] == "s3://bucket/raw/a.pdf" and s["doc_key"] == s["sha256"] and len(s["doc_key"]) == 64  # 원본 위치(나중 Object Storage)
    with COMMON.env(SOURCE_URI_PREFIX=None, SOURCE_MANIFEST=None):
        assert source_record(d, "a.pdf")["uri"].startswith("file:///")
    print("[selftest] 표 머리글 보정 · 시도 상태 분류 · 원본 위치 주소 통과")

    rep0 = {"text": "본문"}
    info_none = apply_post(dict(rep0), "a.docx", d / "a.docx", frozenset())  # PARSE_POST=none → rep["text"] 불변
    assert info_none["features"] == [] and dict(rep0) == rep0
    import zipfile as _zf

    docx = d / "b.docx"
    xml = (
        '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>k</w:t></w:r>'
        '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>2</w:t></w:r></w:p></w:body></w:document>'
    )
    with _zf.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", xml)
    rep1 = {"text": "본문", "rep": {"source": None}}
    info = apply_post(
        rep1, "b.docx", docx, {"supsub"}
    )  # base와 전혀 다른 글자 — 줄 맞추기 실패 → base 그대로(독립 검토 MAJOR 1: 못 맞추면 안 붙임)
    assert info["features"] == ["supsub"] and rep1["text"] == "본문" and info["supsub_unmatched"] == 1
    assert info["supsub"] == "k^2"  # 첨자 표기본 전체는 rep.post에 따로(색인 안 들어감, AD37)

    rep2 = {"text": "k2", "rep": {"source": None}}  # base가 첨자 표기본과 맞는 줄 — 그 줄만 바뀌고 길이는 그대로(AD37)
    info2 = apply_post(rep2, "b.docx", docx, {"supsub"})
    assert rep2["text"] == "k^2" and len(rep2["text"]) <= len("k2") + 1
    print("[selftest] PARSE_POST=none 불변 · supsub 후보정 — 첨자 있는 줄만 치환(본문 중복 안 생김, AD37) 통과")

    png = d / "scan.png"
    from PIL import Image

    Image.new("RGB", (40, 40), "white").save(png)
    rep2 = {"text": "OCR 본문", "rep": {"source": None}}
    with COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None):  # S7c — 설정 객체만 바꿔 끼움(VLM 미설정)
        info2 = apply_post(rep2, "scan.png", png, {"vlm_page"})
    assert info2["vlm_page_calls"] == 1 and info2["vlm_page_cached"] == 0 and rep2["text"] == "OCR 본문"  # VLM 미설정 → 빈 답, 본문 불변
    print("[selftest] vlm_page — VLM 미설정 시 본문 불변·호출 집계 통과")

    # 쪽 VLM 전사는 OCR 본문 뒤에 덧붙임(AD39 PARSE_DEDUP_SCAN·scan_dedup은 pl-34 10-30에 지움).
    from pipeline.shared import vlmcall as _vc  # 쪽 VLM 호출·캐시(11-04 — 엔진과 같은 함수)

    _orig_vlm_page = _vc.vlm_page
    try:
        _vc.vlm_page = lambda img, det=None: ("쪽 VLM 전사 D-2024-999", {"cached": False})
        rep3 = {"text": "OCR 본문 저품질", "rep": {"source": None}}
        info3 = apply_post(rep3, "scan.png", png, {"vlm_page"})  # 덧붙이기
        assert "page_alt" not in info3 and rep3["text"] == "OCR 본문 저품질\n\n쪽 VLM 전사 D-2024-999"
    finally:
        _vc.vlm_page = _orig_vlm_page
    print("[selftest] vlm_page — 쪽 VLM 전사를 OCR 본문 뒤에 덧붙임(page_alt 없음) 통과")

    # X2(원본 즉시 삭제 — 스트리밍) + 독립 보안 검토 MAJOR 3: 엔진별 중간 결과를 지운 뒤 다시 돌리면 sha가 같을 때만
    # 기존 대표 결과를 보존하고(이미 만든 결과를 "성공한 엔진 없음"으로 덮지 않음), sha가 다르면(같은 이름의 다른
    # 내용 — 문서가 바뀜) 보존하지 않고 진짜 실패로 처리한다(오래된 결과를 바뀐 문서에 그대로 쓰지 않게).
    pd2 = Path(tempfile.mkdtemp()) / "parse"
    rep_dir2 = pd2 / "_rep"
    rep_dir2.mkdir(parents=True)
    sha_full = "ab" * 32  # 64자(source.sha256과 같은 길이)
    (rep_dir2 / "a.txt.json").write_text(
        json.dumps({"text": "본문 내용", "rep": {"engine": "eng1", "source": {"sha256": sha_full}}}), encoding="utf-8"
    )
    (pd2 / "runs.jsonl").write_text(
        json.dumps({"doc": "a.txt", "engine": "eng1", "sha": sha_full[:16], "error": None, "at": "2026-01-01 00:00:00"}) + "\n",
        encoding="utf-8",
    )
    qa2 = {"docs": {"a.txt": {"format": ".txt", "engines": {"eng1": {"ok": False}}, "ref": None, "pages": None}}}
    (pd2 / "qa.json").write_text(json.dumps(qa2), encoding="utf-8")
    stack2 = {"name": "t", "parse": {".txt": ["eng1"]}}
    idx1 = represent(stack2, pd2)  # sha 같음(runs.jsonl 기록 = 저장된 대표 결과) → 보존
    assert idx1[0]["engine"] == "eng1" and idx1[0].get("reason") is None
    assert json.loads((rep_dir2 / "a.txt.json").read_text(encoding="utf-8"))["text"] == "본문 내용"

    (pd2 / "runs.jsonl").write_text(
        json.dumps({"doc": "a.txt", "engine": "eng1", "sha": "f" * 16, "error": None, "at": "2026-01-01 00:00:01"}) + "\n", encoding="utf-8"
    )  # 다른 내용으로 다시 받음(같은 이름)
    idx2 = represent(stack2, pd2)  # sha 다름 → 보존 안 함(성공한 엔진 없음)
    assert idx2[0]["engine"] is None and idx2[0].get("reason") == "성공한 엔진 없음"
    print("[selftest] X2 — 엔진별 중간 결과를 지운 뒤 sha 같으면 대표 결과 보존 · sha 다르면(바뀐 문서) 보존 안 함 통과")

    # SI20·AD46⑤ — 산출 표준화(늘 켬): 기호 맵(canon_symbols) + 첨자 표기 통일을 본문·facts·표 칸에
    raw3 = {
        "text": " 1.0×10⁶ B–1",
        "tables": [{"cols": 1, "text": " 95％"}],
        "facts": [{"value": " 95％", "context": ["B–1"], "cells": [" 95％"]}],
    }
    r3 = json.loads(json.dumps(raw3, ensure_ascii=False))  # standardize_rep은 제자리 변경 — 원본(raw3)과 별도 복사본에 적용
    n3 = standardize_rep(r3)
    assert n3 >= 2 and r3["text"] == "≥ 1.0×10^6 B-1" and r3["tables"][0]["text"] == "≥ 95%"
    assert r3["facts"][0]["value"] == "≥ 95%" and r3["facts"][0]["context"] == ["B-1"] and r3["facts"][0]["cells"] == ["≥ 95%"]
    print("[selftest] SI20 — standardize_rep(기호 맵·첨자 표기) 통과")

    pd3 = Path(tempfile.mkdtemp()) / "parse"
    (pd3 / "eng1").mkdir(parents=True)
    (pd3 / "_rep").mkdir()
    doc3 = "c.txt"
    (pd3 / "eng1" / f"{doc3}.json").write_text(json.dumps(raw3, ensure_ascii=False), encoding="utf-8")
    (pd3 / "qa.json").write_text(
        json.dumps({"docs": {doc3: {"format": ".txt", "engines": {"eng1": {"ok": True}}, "ref": None, "pages": None}}}), encoding="utf-8"
    )
    stack3 = {"name": "t3", "parse": {".txt": ["eng1"]}}
    represent(stack3, pd3)
    saved3b = json.loads((pd3 / "_rep" / f"{doc3}.json").read_text(encoding="utf-8"))
    assert (
        saved3b["text"] == "≥ 1.0×10^6 B-1" and saved3b["rep"]["standardize"]["on"] is True and saved3b["rep"]["standardize"]["changed"] > 0
    )
    print("[selftest] SI20 — represent()가 표준화 적용(rep.rep.standardize 기록) 통과")

    # AD23·SI20③·TA1 — grid 있는 표(엔진 산출 흉내)가 있으면 table_inline이 tables_std를 만들고 rep.rep.table_inline을 남긴다.
    raw4 = {"text": "표 문서", "tables": [{"rows": 2, "cols": 2, "text": "a b 1 2", "grid": [["a", "b"], ["1", "2"]]}], "facts": []}
    pd4b = Path(tempfile.mkdtemp()) / "parse"
    (pd4b / "eng1").mkdir(parents=True)
    (pd4b / "_rep").mkdir()
    doc4b = "d.txt"
    (pd4b / "eng1" / f"{doc4b}.json").write_text(json.dumps(raw4, ensure_ascii=False), encoding="utf-8")
    (pd4b / "qa.json").write_text(
        json.dumps({"docs": {doc4b: {"format": ".txt", "engines": {"eng1": {"ok": True}}, "ref": None, "pages": None}}}), encoding="utf-8"
    )
    stack4b = {"name": "t4b", "parse": {".txt": ["eng1"]}}
    represent(stack4b, pd4b)
    saved4c = json.loads((pd4b / "_rep" / f"{doc4b}.json").read_text(encoding="utf-8"))
    assert "table_inline" in saved4c["rep"], saved4c["rep"]
    t0 = saved4c["tables_std"][0]
    assert t0["source_engine"] == "eng1" and t0["header"] == ["a", "b"] and t0["rows"] == [["1", "2"]] and "inline" in t0, t0
    print("[selftest] AD23·TA1 — represent가 table_inline으로 tables_std 생성(rep.rep.table_inline 기록) 통과")

    # AD25(b)(c) — 같은 표 행(자리) "금액"에서 값은 같은데 표기(쉼표·마침표)가 갈린 엔진 둘 → fuse_mod가 찾은
    # 충돌(행 라벨·엔진별 원문 표기·승자)이 문서(_rep/<문서>.json)뿐 아니라 _rep/conflicts.jsonl에도 모인다.
    raw5a = {"text": "계약서 금액 거래", "tables": [], "facts": [{"context": ["금액"], "value": "430,000"}]}
    raw5b = {"text": "계약서 금액 거래", "tables": [], "facts": [{"context": ["금액"], "value": "430.000"}]}
    pd5 = Path(tempfile.mkdtemp()) / "parse"
    (pd5 / "eng1").mkdir(parents=True)
    (pd5 / "eng2").mkdir(parents=True)
    (pd5 / "_rep").mkdir()
    doc5 = "e.txt"
    (pd5 / "eng1" / f"{doc5}.json").write_text(json.dumps(raw5a, ensure_ascii=False), encoding="utf-8")
    (pd5 / "eng2" / f"{doc5}.json").write_text(json.dumps(raw5b, ensure_ascii=False), encoding="utf-8")
    (pd5 / "qa.json").write_text(
        json.dumps(
            {"docs": {doc5: {"format": ".txt", "engines": {"eng1": {"ok": True}, "eng2": {"ok": True}}, "ref": None, "pages": None}}}
        ),
        encoding="utf-8",
    )
    represent({"name": "t5", "parse": {".txt": ["eng1", "eng2"]}}, pd5)
    conf = [json.loads(ln) for ln in (pd5 / "_rep" / "conflicts.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(conf) == 1 and conf[0]["doc"] == doc5, conf
    c0 = conf[0]["conflicts"][0]
    assert c0["label"] == "금액" and c0["winner"] == "430,000" and c0["losers"][0]["text"] == "430.000", c0
    print("[selftest] AD25(b)(c) — fuse 충돌(행 라벨 자리) → _rep/conflicts.jsonl 통과")

    # PE1 후속(2026-10-07) — 스캔 쪽 채움: fill_scan_pages() 단위 — 혼합 3쪽(.pdf_text) 중 스캔 쪽(2쪽)만
    # 쪽 VLM 글로 채움(글자층 쪽은 그대로). 0.2.0(pl-46) — 옛 OCR 엔진(.pdf_image) 대체 길은 지움.
    import io as _io
    import tempfile as _tf

    import fitz as _fitz

    from pipeline.shared import vlmcall as _vc  # 쪽 VLM 호출·캐시(11-04 — 엔진과 같은 함수)
    from pipeline.transform.figures import scan_page_vlm as _vp

    d4 = Path(_tf.mkdtemp())
    pd4 = d4 / "parse"
    (pd4 / "pymupdf").mkdir(parents=True)
    doc4 = "mixed.pdf"
    pdf4 = d4 / doc4
    mdoc4 = _fitz.open()
    mdoc4.new_page(width=200, height=200).insert_text((10, 10), "1쪽 글자층 문서 본문 text layer long enough")  # 혼합(평균 20자 넘음)
    mdoc4.new_page(width=200, height=200)  # 2쪽 — 글자층 없음(스캔)
    mdoc4.new_page(width=200, height=200).insert_text((10, 10), "3쪽 글자층 문서 본문 text layer long enough")
    mdoc4.save(pdf4)
    mdoc4.close()
    base_rep4 = {"text": "1쪽 글자\f\f3쪽 글자", "facts": [], "tables": []}  # 2쪽은 스캔이라 글자층이 비어 있음
    (pd4 / "pymupdf" / f"{doc4}.json").write_text(json.dumps(base_rep4, ensure_ascii=False), encoding="utf-8")
    dd4 = {"format": ".pdf_text", "engines": {"pymupdf": {"ok": True}}, "ref": None}
    stack4 = {"parse": {".pdf_text": ["pymupdf"]}}
    vl = lambda t2: lambda p: [(2, t2, {"cached": True})]  # 쪽 VLM 가짜(2쪽 글, 모델 호출 없음)
    orig_scan_pages_detail = _vp.scan_pages_detail
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}  # 2쪽만 스캔(page_signals 재계산 생략, 신호만 가짜로)
        rep4 = dict(base_rep4)
        fill4 = fill_scan_pages(rep4, dd4, pdf4, page_vlm=vl("VLM 2쪽 스캔 글"))
        assert fill4 == {"filled": {"2": "vlm_page"}, "skip": None}, fill4
        assert rep4["text"] == "1쪽 글자\fVLM 2쪽 스캔 글\f3쪽 글자", rep4["text"]  # 글자 쪽(1·3)은 그대로, 스캔 쪽(2)만

        # 쪽 번호 불명(대표 쪽 \f 개수 ≠ 실제 쪽 수, boxes 없음) → 건너뜀(원문 그대로, 기록만)
        rep4b = {"text": "1쪽 글자\f3쪽 글자", "facts": [], "tables": []}  # \f 1개(2조각) — 실제는 3쪽
        fill4b = fill_scan_pages(rep4b, dd4, pdf4, page_vlm=vl("VLM 2쪽 스캔 글"))
        assert fill4b["skip"] and "확정 불가" in fill4b["skip"] and rep4b["text"] == "1쪽 글자\f3쪽 글자"

        # 쪽 VLM 글이 없으면(꺼짐·빈 글) 채울 것 없음 — 건너뜀 기록(옛 OCR 대체 길 없음)
        for pv in (None, vl("")):
            rep4c = dict(base_rep4)
            assert fill_scan_pages(rep4c, dd4, pdf4, page_vlm=pv) == {"filled": {}, "skip": "쪽 VLM 글 없음"}
            assert rep4c["text"] == base_rep4["text"]

        # 형식이 .pdf_text 아니면(이미 VLM이 대표) 호출 대상 없음 — None
        assert fill_scan_pages(dict(base_rep4), {**dd4, "format": ".pdf_image"}, pdf4, page_vlm=vl("x")) is None

        # 쪽 단위 품질 검사 — 그 쪽 글이 깨져 있으면(garbage_ratio > 0.1) 덮지 않고 원래 글 유지 + page_skip에 기록
        rep4d = dict(base_rep4)
        fill4d = fill_scan_pages(rep4d, dd4, pdf4, page_vlm=vl("\ufffd" * 30))
        assert fill4d == {"filled": {}, "skip": None, "page_skip": {"2": "쪽 VLM 글 품질 낮음(garbage_ratio > 0.1) — 원래 글 유지"}}, fill4d
        assert rep4d["text"] == base_rep4["text"]

        # AD31 — reason='hidden'인 쪽만: 원래 글(숨은 층)과 쪽 VLM 글의 일치도(_page_agreement, 정규화 후 글자 2-gram Jaccard)
        _vp.scan_pages_detail = lambda p: {2: "hidden"}
        hidden_a = "창고 코드 MX-H99 입고량 500개 단가 430,000원 입고일 2026-10-02"
        cases = [  # (원래 2쪽 글, 쪽 VLM 2쪽 글, 채움?, page_skip에 들어갈 말)
            (hidden_a, "창고코드 MX-H99 입고량 500개 단가 430.000원 입고일 2026-10-02", False, "hidden-agree"),  # 표기만 다름
            (hidden_a, "창고코드 MX-H99 입고량 508개 단가 430.000원 입고일 2026-10-02", False, "hidden-agree"),  # 1~2자 다름
            (
                "잡음 글자층 임의 문자열 QZV204 XK930 깨짐 테스트 무관함 완전 다른 내용",
                "점검 ID MX-Q21의 결과는 재검토이며 측정값은 5.8 mg/L이다",
                True,
                None,
            ),  # 무관한 숨은 층 → 채움
            ("MX-H1", "완전히 다른 긴 내용의 텍스트인데 짧은 쪽 기준으로 판단 불가라서 원래 글 유지되어야 함", False, "판단 불가"),
        ]
        for orig, vtext, fills, why in cases:
            rep_h = {"text": f"1쪽 글자\f{orig}\f3쪽 글자", "facts": [], "tables": []}
            fill_h = fill_scan_pages(rep_h, dd4, pdf4, page_vlm=vl(vtext))
            if fills:
                assert fill_h == {"filled": {"2": "vlm_page"}, "skip": None} and vtext in rep_h["text"], fill_h
            else:
                assert fill_h["filled"] == {} and why in (fill_h.get("page_skip") or {}).get("2", ""), fill_h
                assert rep_h["text"] == f"1쪽 글자\f{orig}\f3쪽 글자"

        # AD47 — reason='hidden_overlap'은 쪽 VLM에 글자 상자가 없어 국소 확인을 못 하므로 원래 글 유지(옛 OCR 국소 충돌 확인은 지움)
        _vp.scan_pages_detail = lambda p: {2: "hidden_overlap"}
        rep_ho = {"text": "1쪽 글자\f분기 정산 메모 430.000\f3쪽 글자", "facts": [], "tables": []}
        fill_ho = fill_scan_pages(rep_ho, dd4, pdf4, page_vlm=vl("분기 정산 메모 430,000"))
        assert fill_ho["filled"] == {} and "hidden-overlap" in (fill_ho.get("page_skip") or {}).get("2", ""), fill_ho
        assert "430.000" in rep_ho["text"]
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
    print(
        "[selftest] PE1 후속 — fill_scan_pages(): 스캔 쪽만 쪽 VLM 글로 채움·쪽 번호 불명 건너뜀·VLM 글 없으면 건너뜀·.pdf_text 아니면 대상 없음·깨진 글 건너뜀(page_skip)·AD31 reason='hidden' 일치도 — 표기만 다름·오타 1~2자는 유지·무관한 내용은 채움·짧으면 판단 불가로 유지·hidden_overlap은 유지 통과"
    )

    # 통합 — represent() 안에서 스캔 쪽 채움이 .pdf_text 대표에 적용됨
    qa4 = {"docs": {doc4: {"format": ".pdf_text", "engines": {"pymupdf": {"ok": True}}, "ref": None, "pages": 3}}}
    (pd4 / "qa.json").write_text(json.dumps(qa4, ensure_ascii=False), encoding="utf-8")
    (pd4 / "_rep").mkdir(exist_ok=True)
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        with pc.PIPE.env(PARSE_POST="none"):  # 쪽 VLM 꺼짐 — 채울 글 없음(옛 OCR 대체 길 없음, pl-46)
            represent(stack4, pd4, src=d4)
        on4 = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert on4["text"] == "1쪽 글자\f\f3쪽 글자" and on4["rep"]["scan_fill"] == {"filled": {}, "skip": "쪽 VLM 글 없음"}
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
    print("[selftest] PE1 후속 — represent(): 쪽 VLM 꺼짐이면 채우지 않음(rep.rep.scan_fill 기록) 통과")

    # 독립 검토 보강 — 스캔 쪽 채움 × 쪽 VLM(vlm_page): 스캔 쪽을 채운 뒤 apply_post가 같은 쪽을 다시 봐도
    # 쪽 번호가 안 섞이고 값이 안 없어진다(옛 PARSE_DEDUP_SCAN 조합 시험 — dedup은 pl-34 10-30에 지움).
    orig_vlm_page = _vc.vlm_page
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        _vc.vlm_page = lambda img, det=None: ("정돈된 VLM 글 설명(OCR과 다른 표현)", {"cached": False})
        # page_text_pages가 스캔 쪽(2쪽)만 VLM 호출 · PARSE_POST=vlm_page: vlm_page 기능만(supsub 등 다른 후보정이 \f를 흔드는 것과 분리)
        with pc.PIPE.env(PARSE_POST="vlm_page"):
            represent(stack4, pd4, src=d4)
        combo = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert combo["rep"]["scan_fill"] == {"filled": {"2": "vlm_page"}, "skip": None}  # 10-29 — 쪽 VLM 글이 있으면 그것으로 채움
        parts = combo["text"].split("\f")
        assert len(parts) == 3 and parts[0] == "1쪽 글자" and parts[2] == "3쪽 글자"  # 쪽 번호 안 섞임(1·3쪽 그대로)
        assert "정돈된 VLM 글" in combo["text"]  # 2쪽 글이 남음(값 손실 없음)
        assert "page_alt" not in combo["post"]
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        _vc.vlm_page = orig_vlm_page
    print("[selftest] PE1 후속 — 스캔 쪽 채움 × 쪽 VLM: 쪽 번호 안 섞임·값 손실 없음 통과")

    # 10-29 — apply_post는 쪽 VLM으로 채운 쪽을 다시 안 덧붙임
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        _vc.vlm_page = lambda img, det=None: ("VLM 2쪽 스캔 글", {"cached": True})
        with pc.PIPE.env(PARSE_POST="vlm_page"):
            represent(stack4, pd4, src=d4)
        v_out = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert v_out["rep"]["scan_fill"]["filled"] == {"2": "vlm_page"}
        assert v_out["text"].count("VLM 2쪽 스캔 글") == 1, v_out["text"]  # 채운 쪽을 apply_post가 또 덧붙이지 않음
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        _vc.vlm_page = orig_vlm_page
    print("[selftest] 10-29 — 스캔 쪽 쪽 VLM 글로 채움·채운 쪽 중복 덧붙임 없음 통과")

    # 10-29 P1-1·M4 — 쪽 VLM은 PARSE_POST에 vlm_page가 있을 때만(supsub만이면 호출 0) · 실패한 쪽도 한 represent에서 한 번만 부름
    calls = []
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        _vc.vlm_page = lambda img, det=None: (calls.append(1), ("", {"error": "가짜 실패", "cached": False}))[1]
        with pc.PIPE.env(PARSE_POST="supsub"):
            represent(stack4, pd4, src=d4)
        assert calls == [], "쪽 VLM이 꺼져 있는데(supsub만) VLM을 부름"
        with pc.PIPE.env(PARSE_POST="vlm_page"):
            represent(stack4, pd4, src=d4)
        assert len(calls) == 1, calls  # 스캔 쪽 1장 — scan_fill과 apply_post가 같은 결과를 씀(실패해도 다시 안 부름)
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        _vc.vlm_page = orig_vlm_page
    print("[selftest] 10-29 — 쪽 VLM 끔이면 호출 0 · 실패한 쪽 재호출 없음 통과")

    # 10-29 C — 이미지·스캔 문서를 VLM 엔진이 이미 옮겼으면 쪽 VLM 0회 · 쪽 전체 그림은 '쪽 VLM이 다룬 것'으로(그림 VLM 생략)

    from PIL import Image as _Image

    from pipeline.transform.figures.figure_extract import figures as _figures

    d6 = Path(_tf.mkdtemp())
    pd6 = d6 / "parse"
    (pd6 / "qwen_vlm").mkdir(parents=True)
    (pd6 / "_rep").mkdir()
    scan6 = d6 / "scan.pdf"
    sd6 = _fitz.open()
    buf6 = _io.BytesIO()
    _Image.new("RGB", (200, 200), "gray").save(buf6, "PNG")
    sd6.new_page(width=200, height=200).insert_image(_fitz.Rect(0, 0, 200, 200), stream=buf6.getvalue())
    sd6.save(scan6)
    sd6.close()
    (pd6 / "qwen_vlm" / "scan.pdf.json").write_text(json.dumps({"text": "VLM 엔진이 옮긴 글"}, ensure_ascii=False), encoding="utf-8")
    qa6 = {"docs": {"scan.pdf": {"format": ".pdf_image", "engines": {"qwen_vlm": {"ok": True}}, "ref": None, "pages": 1}}}
    (pd6 / "qa.json").write_text(json.dumps(qa6, ensure_ascii=False), encoding="utf-8")
    stack6 = {"parse": {".pdf_image": ["qwen_vlm"]}}
    calls.clear()
    try:
        _vc.vlm_page = lambda img, det=None: (calls.append(1), ("쪽 VLM 글", {"cached": False}))[1]
        with pc.PIPE.env(PARSE_POST="vlm_page"):
            represent(stack6, pd6, src=d6)
        assert calls == [], "VLM 엔진이 이미 옮긴 스캔 문서에 쪽 VLM을 또 부름"
        out6 = json.loads((pd6 / "_rep" / "scan.pdf.json").read_text(encoding="utf-8"))
        assert out6["text"].count("VLM 엔진이 옮긴 글") == 1 and "쪽 VLM 글" not in out6["text"], out6["text"]
        with pc.PIPE.env(PARSE_POST="figures"):  # 쪽 VLM 꺼짐 — 덮지 않으면 쪽 전체 그림은 그림 VLM 대상
            assert not any(f["loc"].get("page_vlm") for f in _figures(scan6) if f["loc"].get("page_render"))
            assert all(f["loc"].get("page_vlm") for f in _figures(scan6, page_covered=True) if f["loc"].get("page_render"))
        # run_pipeline light 레인처럼 vlm_page 없이 figures만 — VLM 엔진이 옮긴 문서의 쪽 전체 그림은 그림 VLM 0회
        from pipeline.transform.figures import figure_extract as _fig_mod

        fig_calls = []
        orig_vlm_fig = _fig_mod.vlm_fig
        _fig_mod.vlm_fig = lambda b, **kw: (fig_calls.append(1), ("그림 글", {}))[1]
        try:
            with pc.PIPE.env(PARSE_POST="figures"):
                represent(stack6, pd6, src=d6)
        finally:
            _fig_mod.vlm_fig = orig_vlm_fig
        assert fig_calls == [], "VLM 엔진이 옮긴 쪽 전체 그림에 그림 VLM을 또 부름"
    finally:
        _vc.vlm_page = orig_vlm_page
    # covered 판정 표 — 대표가 VLM 엔진·본문 있음·이미지/스캔 형식(run_all과 같은 형식 키)일 때만
    from pipeline.transform.represent.doc_represent import _vlm_transcribed as _vt

    def _r(engine, text):
        return {"rep": {"engine": engine}, "text": text}

    for rep_x, fmt, want in (
        (_r("qwen_vlm", "글"), ".pdf_image", True),  # 글자 쪽이 몇 장 섞인 .pdf_image도(is_scan과 달리)
        (_r("qwen_vlm", "글"), ".png", True),
        (_r("rapidocr_ko", "글"), ".pdf_image", False),  # OCR 엔진이 대표(옛 결과 — 0.2.0부터 OCR 엔진은 파싱에 안 돎)
        (_r("qwen_vlm", "  "), ".pdf_image", False),  # 빈 VLM 글은 쪽 VLM을 막지 않음
        (_r("qwen_vlm", "글"), ".pdf_text", False),
    ):
        assert _vt(rep_x, {"format": fmt}) is want, (rep_x, fmt)
    print("[selftest] 10-29 C — VLM 엔진이 옮긴 스캔 문서: 쪽 VLM 0회·쪽 전체 그림 VLM 생략(vlm_page 없을 때도)·covered 판정 표 통과")

    # AD29 P1 — 융합: 두 텍스트
    # 레이어 엔진이 동의한 값(430,000)이 OCR 혼자 낸 값(430.000)을 이기고 rep["fused"]["facts"]에 들어간다
    # (rep["text"]·rep["facts"](기존 칸)은 안 건드림 — 새 칸만 추가).
    pd5 = Path(tempfile.mkdtemp()) / "parse"
    for eng in ("pdfplumber", "pymupdf", "rapidocr_ko"):
        (pd5 / eng).mkdir(parents=True)
    (pd5 / "_rep").mkdir()
    doc5 = "e.txt"
    facts_text = [{"context": ["금액"], "value": "430,000"}]
    facts_ocr = [{"context": ["금액"], "value": "430.000"}]
    (pd5 / "pdfplumber" / f"{doc5}.json").write_text(
        json.dumps({"text": "본문", "facts": facts_text}, ensure_ascii=False), encoding="utf-8"
    )
    (pd5 / "pymupdf" / f"{doc5}.json").write_text(json.dumps({"text": "본문", "facts": facts_text}, ensure_ascii=False), encoding="utf-8")
    (pd5 / "rapidocr_ko" / f"{doc5}.json").write_text(
        json.dumps({"text": "본문", "facts": facts_ocr}, ensure_ascii=False), encoding="utf-8"
    )
    (pd5 / "qa.json").write_text(
        json.dumps(
            {
                "docs": {
                    doc5: {
                        "format": ".txt",
                        "engines": {"pdfplumber": {"ok": True}, "pymupdf": {"ok": True}, "rapidocr_ko": {"ok": True}},
                        "ref": None,
                        "pages": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    stack5 = {"name": "t5", "parse": {".txt": ["pdfplumber", "pymupdf", "rapidocr_ko"]}}
    represent(stack5, pd5)
    on5 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert on5["text"] == "본문" and on5["facts"] == facts_text  # 본문·기존 facts(대표 것)는 그대로
    by5 = {f["context"][0]: f for f in on5["fused"]["facts"]}
    assert by5["금액"]["value"] == "430,000" and set(by5["금액"]["engines"]) == {"pdfplumber", "pymupdf"}
    assert on5["fused"]["conflicts"][0]["losers"][0]["engines"] == ["rapidocr_ko"]
    assert "reread" not in on5["fused"]  # 재판독 칸 없음(pl-34에 지움)
    print("[selftest] AD29 P1 — 라벨:값 조각 투표(신뢰도 높은 쪽 승, 본문·기존 facts 불변) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
