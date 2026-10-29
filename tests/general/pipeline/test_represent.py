"""pipeline.transform.represent.represent 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.represent --selftest`."""

import json
from pathlib import Path

from common.config.settings import COMMON
from common.core.contract import source_record
from pipeline import config as pc
from pipeline.transform.represent import reread_stage3 as reread_p3_mod
from pipeline.transform.represent import trace as trace_mod
from pipeline.transform.represent.represent import (
    _number_fixes,
    _unique_on_page,
    apply_post,
    fill_scan_pages,
    fix_tables,
    represent,
    row_key,
    scan_fill_on,
    standardize_on,
    standardize_rep,
    status,
)

_TIME_KEYS = ("post_times", "stage_times")  # 실제 소요 초(0.01초 반올림 — represent.py 10-22) — 실행마다 다름


def _no_times(o):
    """rep 비교에서 소요 초 칸(post.post_times·rep.stage_times)만 뺀다(S11 — 사용자 10-28, VS9b R-2 · test_parse_agent와 같은 꼴)."""
    if isinstance(o, dict):
        return {k: _no_times(v) for k, v in o.items() if k not in _TIME_KEYS}
    return [_no_times(v) for v in o] if isinstance(o, list) else o


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
    import os
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "a.pdf").write_bytes(b"x")
    os.environ["SOURCE_URI_PREFIX"] = "s3://bucket/raw/"  # env 남김 — 시험: 인계 파일(contract.py)이 env로 읽음
    s = source_record(d, "a.pdf")
    assert s["uri"] == "s3://bucket/raw/a.pdf" and s["doc_key"] == s["sha256"] and len(s["doc_key"]) == 64  # 원본 위치(나중 Object Storage)
    del os.environ["SOURCE_URI_PREFIX"]  # env 남김 — 시험: 인계 파일(contract.py)이 env로 읽음
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

    # AD39 — PARSE_DEDUP_SCAN(기본 꺼짐): 같은 쪽 OCR 본문 + 쪽 VLM 전사가 둘 다 rep.text에 들어가던 것을
    # 하나만 남기고 다른 하나는 rep.post.page_alt로. 끄면(기본) 위 vlm_page 경로와 바이트 동일.
    from pipeline.transform.figures import vlm_page as _vp_mod

    _orig_vlm_page = _vp_mod.vlm_page
    try:
        _vp_mod.vlm_page = lambda img, det=None: ("쪽 VLM 전사 D-2024-999", {"cached": False})
        rep3 = {"text": "OCR 본문 저품질", "rep": {"source": None}}
        info3 = apply_post(rep3, "scan.png", png, {"vlm_page"})  # 기본 꺼짐 — 이전 동작(덧붙이기)과 같음
        assert "page_alt" not in info3 and rep3["text"] == "OCR 본문 저품질\n\n쪽 VLM 전사 D-2024-999"
        with pc.PIPE.env(PARSE_DEDUP_SCAN="1"):  # S7c — 설정 객체만 바꿔 끼움
            rep4 = {"text": "OCR 본문 저품질", "rep": {"source": None}}
            info4 = apply_post(rep4, "scan.png", png, {"vlm_page"})  # 켜면 — 하나만 본문, 다른 하나는 page_alt
        assert rep4["text"].startswith("쪽 VLM 전사") and "쪽 VLM 전사" in rep4["text"]
        assert "OCR 본문 저품질" not in rep4["text"]  # 중복 제거됨 — 본문에 두 번 안 들어감
        assert info4["page_alt"][1] == {"from": "ocr", "text": "OCR 본문 저품질"}
        assert info4["dedup_scan"] == 1
        # 한쪽(OCR)에만 있던 ID는 이긴 쪽(VLM) 글 끝에 남아 값 재현율이 지켜진다
        rep5 = {"text": "계약 D-2024-123 금액 500,000", "rep": {"source": None}}
        _vp_mod.vlm_page = lambda img, det=None: ("정돈된 쪽 전사 금액 500,000", {"cached": False})
        with pc.PIPE.env(PARSE_DEDUP_SCAN="1"):
            apply_post(rep5, "scan.png", png, {"vlm_page"})
        assert "d-2024-123" in rep5["text"].lower()
    finally:
        _vp_mod.vlm_page = _orig_vlm_page
    print("[selftest] AD39 — PARSE_DEDUP_SCAN 끔=이전과 동일(덧붙임)·켬=쪽마다 하나만(page_alt 보존)·한쪽에만 있는 ID 보존 통과")

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

    # SI20·AD46⑤ — 산출 표준화(PARSE_STANDARDIZE, 기본 켬, =0으로 끔): 기호 맵(canon_symbols) + 첨자 표기 통일을 본문·facts·표 칸에
    with pc.PIPE.env(PARSE_STANDARDIZE=None):  # S7c — 설정 객체만 바꿔 끼움
        assert standardize_on() is True and standardize_on("1") is True and standardize_on("0") is False
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
    with pc.PIPE.env(PARSE_STANDARDIZE="0"):  # S7c — 설정 객체만 바꿔 끼움
        represent(stack3, pd3)  # =0 — rep 본문이 이전 동작과 바이트 동일
    saved3 = json.loads((pd3 / "_rep" / f"{doc3}.json").read_text(encoding="utf-8"))
    assert saved3["text"] == raw3["text"] and saved3["rep"]["standardize"] == {"on": False, "changed": 0}, saved3["rep"]["standardize"]
    represent(stack3, pd3)  # 기본(미설정) = 켬
    saved3b = json.loads((pd3 / "_rep" / f"{doc3}.json").read_text(encoding="utf-8"))
    assert (
        saved3b["text"] == "≥ 1.0×10^6 B-1" and saved3b["rep"]["standardize"]["on"] is True and saved3b["rep"]["standardize"]["changed"] > 0
    )
    print("[selftest] SI20 — PARSE_STANDARDIZE 기본 켬=표준화 적용 · =0이면 rep 바이트 동일 통과")

    # AD23·SI20③ — tables_std 연결: grid 있는 표(엔진 산출 흉내)가 있으면 기본(PARSE_TABLE_STD 켬)으로 tables_std가 생기고
    # 끄면(0) 키 자체가 없음(기존 text·tables·facts는 영향 없음 — 새 칸 추가뿐).
    # TA1(PARSE_TABLE_INLINE)이 기본 켬이라 이 자리는 이제 보통 table_inline이 가로채므로(아래 별도 시험), 이
    # 블록은 table_std 자신의 on/off만 보려고 PARSE_TABLE_INLINE=0으로 옛 호출 경로를 그대로 쓴다.
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
    with pc.PIPE.env(PARSE_TABLE_INLINE="0"):  # S7c — 설정 객체만 바꿔 끼움
        represent(stack4b, pd4b)
        saved4 = json.loads((pd4b / "_rep" / f"{doc4b}.json").read_text(encoding="utf-8"))
        assert saved4["tables_std"] == [
            {"id": "t0", "page": None, "source_engine": "eng1", "header": ["a", "b"], "rows": [["1", "2"]], "merged": []}
        ], saved4["tables_std"]
        with pc.PIPE.env(PARSE_TABLE_STD="0"):
            represent(stack4b, pd4b)
        saved4b = json.loads((pd4b / "_rep" / f"{doc4b}.json").read_text(encoding="utf-8"))
        assert "tables_std" not in saved4b and saved4b["text"] == raw4["text"]  # 끄면 키 자체가 없음·기존 칸 불변
    print("[selftest] AD23·SI20③ — represent → tables_std 연결(기본 켬) · PARSE_TABLE_STD=0 끔=키 없음(PARSE_TABLE_INLINE=0일 때) 통과")

    # TA1 — PARSE_TABLE_INLINE 기본 켬: 같은 입력으로 다시 돌리면(이번엔 env 원복해 기본값) table_inline이
    # 그 자리를 가로채 rep["rep"]["table_inline"]을 남기고, tables_std 항목에 inline 칸이 생긴다(찾았으면 True).
    represent(stack4b, pd4b)
    saved4c = json.loads((pd4b / "_rep" / f"{doc4b}.json").read_text(encoding="utf-8"))
    assert "table_inline" in saved4c["rep"], saved4c["rep"]
    assert saved4c["tables_std"][0]["source_engine"] == "eng1" and "inline" in saved4c["tables_std"][0]
    print("[selftest] TA1 — PARSE_TABLE_INLINE 기본 켬=represent가 table_inline으로 넘김(rep.rep.table_inline 기록) 통과")

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

    # PE1 후속(2026-10-07) — PARSE_SCAN_FILL(기본 켬): fill_scan_pages() 단위 — 혼합 3쪽(.pdf_text) 중 스캔 쪽(2쪽)만
    # OCR 엔진(.pdf_image 계열)의 쪽 글로 채움(글자층 쪽은 그대로).
    import tempfile as _tf

    import fitz as _fitz

    from pipeline.transform.figures import vlm_page as _vp

    d4 = Path(_tf.mkdtemp())
    pd4 = d4 / "parse"
    (pd4 / "pymupdf").mkdir(parents=True)
    (pd4 / "rapidocr_ko").mkdir(parents=True)
    doc4 = "mixed.pdf"
    pdf4 = d4 / doc4
    mdoc4 = _fitz.open()
    mdoc4.new_page(width=200, height=200).insert_text((10, 10), "1쪽 글자층 문서 본문이 충분히 길다")  # is_scan() = False(혼합)이 되게
    mdoc4.new_page(width=200, height=200)  # 2쪽 — 글자층 없음(스캔)
    mdoc4.new_page(width=200, height=200).insert_text((10, 10), "3쪽 글자층 문서 본문이 충분히 길다")
    mdoc4.save(pdf4)
    mdoc4.close()
    base_rep4 = {"text": "1쪽 글자\f\f3쪽 글자", "facts": [], "tables": []}  # 2쪽은 스캔이라 글자층이 비어 있음
    (pd4 / "pymupdf" / f"{doc4}.json").write_text(json.dumps(base_rep4, ensure_ascii=False), encoding="utf-8")
    ocr_out4 = {
        "text": "",
        "boxes": [{"page": 1, "text": "OCR 1쪽"}, {"page": 2, "text": "OCR 2쪽 스캔 글"}, {"page": 3, "text": "OCR 3쪽"}],
    }
    (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(json.dumps(ocr_out4, ensure_ascii=False), encoding="utf-8")
    dd4 = {"format": ".pdf_text", "engines": {"pymupdf": {"ok": True}, "rapidocr_ko": {"ok": True}}, "ref": None}
    stack4 = {"parse": {".pdf_text": ["pymupdf"], ".pdf_image": ["rapidocr_ko"]}}
    orig_scan_pages_detail = _vp.scan_pages_detail
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}  # 2쪽만 스캔(page_signals 재계산 생략, 신호만 가짜로)
        rep4 = dict(base_rep4)
        fill4 = fill_scan_pages(rep4, doc4, dd4, stack4, pd4, pdf4)
        assert fill4 == {"filled": {"2": "rapidocr_ko"}, "skip": None}, fill4
        assert rep4["text"] == "1쪽 글자\fOCR 2쪽 스캔 글\f3쪽 글자", rep4["text"]  # 글자 쪽(1·3)은 그대로, 스캔 쪽(2)만 OCR 글로

        # 쪽 번호 불명(대표 쪽 \f 개수 ≠ 실제 쪽 수, boxes 없음) → 건너뜀(원문 그대로, 기록만)
        rep4b = {"text": "1쪽 글자\f3쪽 글자", "facts": [], "tables": []}  # \f 1개(2조각) — 실제는 3쪽
        fill4b = fill_scan_pages(rep4b, doc4, dd4, stack4, pd4, pdf4)
        assert fill4b["skip"] and "확정 불가" in fill4b["skip"] and rep4b["text"] == "1쪽 글자\f3쪽 글자"

        # OCR(.pdf_image) 후보가 하나도 성공 못 하면 채울 것 없음 — 건너뜀 기록
        dd4c = {"format": ".pdf_text", "engines": {"pymupdf": {"ok": True}, "rapidocr_ko": {"ok": False}}, "ref": None}
        rep4c = dict(base_rep4)
        fill4c = fill_scan_pages(rep4c, doc4, dd4c, stack4, pd4, pdf4)
        assert fill4c == {"filled": {}, "skip": "OCR 엔진(.pdf_image) 성공 결과 없음"} and rep4c["text"] == base_rep4["text"]

        # 형식이 .pdf_text 아니면(이미 OCR이 대표) 호출 대상 없음 — None
        assert fill_scan_pages(dict(base_rep4), doc4, {**dd4, "format": ".pdf_image"}, stack4, pd4, pdf4) is None

        # 쪽 단위 품질 검사(독립 검토 보강) — 그 쪽 OCR 글이 깨져 있으면(garbage_ratio > 0.1, scan_dedup.pick과 같은
        # 기준) 덮지 않고 원래 글 유지 + page_skip에 기록
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(
                {"text": "", "boxes": [{"page": 1, "text": "OCR 1쪽"}, {"page": 2, "text": "�" * 30}, {"page": 3, "text": "OCR 3쪽"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rep4d = dict(base_rep4)
        fill4d = fill_scan_pages(rep4d, doc4, dd4, stack4, pd4, pdf4)
        assert fill4d == {"filled": {}, "skip": None, "page_skip": {"2": "OCR 글 품질 낮음(garbage_ratio > 0.1) — 원래 글 유지"}}, fill4d
        assert rep4d["text"] == base_rep4["text"]  # 깨진 OCR 글로 안 덮음 — 원래 글(2쪽 빈 글자층) 유지

        # AD31 독립 검토 MAJOR 후속 — reason='hidden'인 쪽만: 원래 글(숨은 층)과 OCR 글의 일치도(_page_agreement,
        # 정규화 후 글자 2-gram Jaccard) 검사. 독립 검토자 경계 사례 그대로.
        _vp.scan_pages_detail = lambda p: {2: "hidden"}
        hidden_a = "창고 코드 MX-H99 입고량 500개 단가 430,000원 입고일 2026-10-02"

        # (a) 검색 가능 스캔 PDF — 공백·구분자 표기만 다름(430,000 vs 430.000·"창고 코드" vs "창고코드") → 정규화하면
        # 같은 글 → 일치도 1.0 → 원래 글(숨은 층) 유지, OCR로 안 덮음
        rep_h1 = {"text": f"1쪽 글자\f{hidden_a}\f3쪽 글자", "facts": [], "tables": []}
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(
                {
                    "text": "",
                    "boxes": [
                        {"page": 1, "text": "OCR 1쪽"},
                        {"page": 2, "text": "창고코드 MX-H99 입고량 500개 단가 430.000원 입고일 2026-10-02"},
                        {"page": 3, "text": "OCR 3쪽"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fill_h1 = fill_scan_pages(rep_h1, doc4, dd4, stack4, pd4, pdf4)
        assert fill_h1["filled"] == {} and "hidden-agree" in (fill_h1.get("page_skip") or {}).get("2", ""), fill_h1
        assert rep_h1["text"] == f"1쪽 글자\f{hidden_a}\f3쪽 글자"  # 원래 글(숨은 층) 그대로 — OCR로 안 덮음

        # (b) 같은 내용인데 OCR이 1~2자를 다르게 읽음(500개→508개) — 글자 2-gram 대부분 겹쳐 일치도 ≥ 0.6 → 원래 글 유지
        rep_h2 = {"text": f"1쪽 글자\f{hidden_a}\f3쪽 글자", "facts": [], "tables": []}
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(
                {
                    "text": "",
                    "boxes": [
                        {"page": 1, "text": "OCR 1쪽"},
                        {"page": 2, "text": "창고코드 MX-H99 입고량 508개 단가 430.000원 입고일 2026-10-02"},
                        {"page": 3, "text": "OCR 3쪽"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fill_h2 = fill_scan_pages(rep_h2, doc4, dd4, stack4, pd4, pdf4)
        assert fill_h2["filled"] == {} and "hidden-agree" in (fill_h2.get("page_skip") or {}).get("2", ""), fill_h2
        assert rep_h2["text"] == f"1쪽 글자\f{hidden_a}\f3쪽 글자"

        # (c) garbled_layer처럼 그림과 무관한 숨은 글자층(길이는 충분하되 일치도 낮음) → OCR로 채움(지금 동작 그대로)
        rep_h3 = {
            "text": "1쪽 글자\f잡음 글자층 임의 문자열 QZV204 XK930 깨짐 테스트 무관함 완전 다른 내용\f3쪽 글자",
            "facts": [],
            "tables": [],
        }
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(
                {
                    "text": "",
                    "boxes": [
                        {"page": 1, "text": "OCR 1쪽"},
                        {"page": 2, "text": "점검 ID MX-Q21의 결과는 재검토이며 측정값은 5.8 mg/L이다"},
                        {"page": 3, "text": "OCR 3쪽"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fill_h3 = fill_scan_pages(rep_h3, doc4, dd4, stack4, pd4, pdf4)
        assert fill_h3 == {"filled": {"2": "rapidocr_ko"}, "skip": None}, fill_h3
        assert "MX-Q21" in rep_h3["text"] and "5.8" in rep_h3["text"]  # 무관한 숨은 글자층 대신 OCR 글로 채워짐(값 복원)

        # (d) 짧은 쪽 가드 — 정규화한 글이 둘 중 하나라도 짧으면(HIDDEN_AGREE_MIN_LEN 미만) 판단 불가 → 원래 글 유지
        rep_h4 = {"text": "1쪽 글자\fMX-H1\f3쪽 글자", "facts": [], "tables": []}
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(
                {
                    "text": "",
                    "boxes": [
                        {"page": 1, "text": "OCR 1쪽"},
                        {"page": 2, "text": "완전히 다른 긴 내용의 텍스트인데 짧은 쪽 기준으로 판단 불가라서 원래 글 유지되어야 함"},
                        {"page": 3, "text": "OCR 3쪽"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fill_h4 = fill_scan_pages(rep_h4, doc4, dd4, stack4, pd4, pdf4)
        assert fill_h4["filled"] == {} and "판단 불가" in (fill_h4.get("page_skip") or {}).get("2", ""), fill_h4
        assert rep_h4["text"] == "1쪽 글자\fMX-H1\f3쪽 글자"
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        (pd4 / "rapidocr_ko" / f"{doc4}.json").write_text(
            json.dumps(ocr_out4, ensure_ascii=False), encoding="utf-8"
        )  # 되돌림(아래 통합 테스트가 씀)
    print(
        "[selftest] PE1 후속 — fill_scan_pages(): 스캔 쪽만 OCR 글로 채움·쪽 번호 불명 건너뜀·OCR 후보 없음 건너뜀·.pdf_text 아니면 대상 없음·깨진 OCR 글 건너뜀(page_skip)·AD31 reason='hidden' 정규화 후 글자 2-gram 일치도 — 표기만 다름·오타 1~2자는 유지·무관한 내용은 채움·짧으면 판단 불가로 유지 통과"
    )

    # AD47 검토자 반영(10-08, CONCERN) — reason='hidden_overlap'은 쪽 전체가 아니라 겹친 숨은 글자 상자
    # 주변(국소)만 보고 교체 여부를 정한다(_hidden_overlap_conflict) — 겹침만으로 쪽 전체를 바꾸던 설계는
    # 워터마크·접근성용 숨은 글자처럼 우연히 겹친 정상 쪽까지 바꿀 위험이 있었다. 합성 회귀 사례 2개(겹치지만
    # 맞는 쪽·워터마크형) + 확인된 충돌 1개 — 실제 PDF(image·render_mode=3)로 hidden_overlap_spans()까지 통째로.
    import io as _io

    from PIL import Image as _PILImage

    def _make_ho_doc(name, hidden_text):
        """vlm_page.py selftest의 mismatch_doc과 같은 모양(그림 rect(100,110,433,160) 위에 숨은 글자)."""
        pg_doc = _fitz.open()
        pg = pg_doc.new_page(width=595, height=842)
        pg.insert_text((50, 50), "분기 정산 메모 " * 8)
        buf = _io.BytesIO()
        _PILImage.new("RGB", (333, 50), "white").save(buf, "PNG")
        pg.insert_image(_fitz.Rect(100, 110, 433, 160), stream=buf.getvalue())
        pg.insert_text((110, 140), hidden_text, render_mode=3)
        path = d4 / name
        pg_doc.save(path)
        pg_doc.close()
        return path

    _ocr_box = {"page": 1, "text": "430,000", "bbox": [104.8, 122.7, 230.8, 143.5]}  # 그림 속 OCR 결과(세 사례 공통)
    try:
        _vp.scan_pages_detail = lambda p: {1: "hidden_overlap"}

        # (e) 겹치지만 숨은 글자가 이미 맞는 쪽(표기까지 같음) — 교체 0
        pdf_ho1 = _make_ho_doc("ho_match.pdf", "430,000")
        (pd4 / "rapidocr_ko" / "ho_match.pdf.json").write_text(
            json.dumps({"text": "", "boxes": [_ocr_box]}, ensure_ascii=False), encoding="utf-8"
        )
        rep_ho1 = {"text": "분기 정산 메모 430,000", "facts": [], "tables": []}
        fill_ho1 = fill_scan_pages(rep_ho1, "ho_match.pdf", dd4, stack4, pd4, pdf_ho1)
        assert fill_ho1["filled"] == {} and "hidden-overlap-local" in (fill_ho1.get("page_skip") or {}).get("1", ""), fill_ho1
        assert rep_ho1["text"] == "분기 정산 메모 430,000"  # 교체 안 됨 — 원래 글 유지

        # (f) 워터마크형 — 겹치지만 숨은 글자가 그림과 무관(국소 느슨 일치가 낮음) → 교체 0(회귀 방지가 목적)
        pdf_ho2 = _make_ho_doc("ho_watermark.pdf", "DRAFT COPY ONLY")
        (pd4 / "rapidocr_ko" / "ho_watermark.pdf.json").write_text(
            json.dumps({"text": "", "boxes": [_ocr_box]}, ensure_ascii=False), encoding="utf-8"
        )
        rep_ho2 = {"text": "분기 정산 메모 DRAFT COPY ONLY", "facts": [], "tables": []}
        fill_ho2 = fill_scan_pages(rep_ho2, "ho_watermark.pdf", dd4, stack4, pd4, pdf_ho2)
        assert fill_ho2["filled"] == {} and "hidden-overlap-local" in (fill_ho2.get("page_skip") or {}).get("1", ""), fill_ho2
        assert rep_ho2["text"] == "분기 정산 메모 DRAFT COPY ONLY"  # 교체 안 됨 — 그림과 무관(워터마크류)

        # (g) 확인된 충돌 — 내용은 같은데 숫자 구분자만 다름(430.000 vs 430,000) → 이 쪽만 OCR 글로 교체
        pdf_ho3 = _make_ho_doc("ho_conflict.pdf", "430.000")
        (pd4 / "rapidocr_ko" / "ho_conflict.pdf.json").write_text(
            json.dumps({"text": "", "boxes": [_ocr_box]}, ensure_ascii=False), encoding="utf-8"
        )
        rep_ho3 = {"text": "분기 정산 메모 430.000", "facts": [], "tables": []}
        fill_ho3 = fill_scan_pages(rep_ho3, "ho_conflict.pdf", dd4, stack4, pd4, pdf_ho3)
        assert fill_ho3 == {"filled": {"1": "rapidocr_ko"}, "skip": None}, fill_ho3
        assert rep_ho3["text"] == "분기 정산 메모 430,000"  # AD47② 충돌 숫자만 OCR 표기로(나머지 글자층 유지)
        assert _number_fixes("합계 430.000 · 1.5", "합계 430,000 1.5") == {"430.000": "430,000"}  # 같은 숫자열 후보 하나만
        assert _number_fixes("430.000", "430,000 4300.00") == {}  # 후보 2개 — 애매하면 안 바꿈
        assert _unique_on_page({"430.000": "430,000"}, "합계 430.000\n소계 430.000") == {}  # 쪽에 두 번 — 어느 것인지 몰라 안 바꿈
        assert _unique_on_page({"430.000": "430,000"}, "합계 ４３０.０００") == {"430.000": "430,000"}  # 전각 숫자도 같은 값으로 셈
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
    print(
        "[selftest] AD47 검토자 반영 — fill_scan_pages() reason='hidden_overlap': 국소(겹친 상자 주변)만 보고 "
        "표기까지 일치·내용이 그림과 무관(워터마크)이면 유지, 숫자 구분자만 다르면 확인된 충돌로 그 쪽만 교체 통과"
    )

    # 통합 — represent() 안에서 PARSE_SCAN_FILL(기본 켬)이 .pdf_text 대표에 적용되고, 끄면(0) 이전 동작과 바이트 동일
    assert scan_fill_on() is True and scan_fill_on("1") is True and scan_fill_on("0") is False
    qa4 = {
        "docs": {doc4: {"format": ".pdf_text", "engines": {"pymupdf": {"ok": True}, "rapidocr_ko": {"ok": True}}, "ref": None, "pages": 3}}
    }
    (pd4 / "qa.json").write_text(json.dumps(qa4, ensure_ascii=False), encoding="utf-8")
    (pd4 / "_rep").mkdir(exist_ok=True)
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        with pc.PIPE.env(PARSE_POST="none", PARSE_SCAN_FILL="0"):  # apply_post를 그대로 통과시켜 본문만 확인 — S7c: 설정 객체만 바꿔 끼움
            represent(stack4, pd4, src=d4)
        off4 = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert off4["text"] == base_rep4["text"] and "scan_fill" not in off4["rep"]  # 꺼짐 — 이전 동작과 바이트 동일

        with pc.PIPE.env(PARSE_POST="none", PARSE_SCAN_FILL="1"):
            represent(stack4, pd4, src=d4)
        on4 = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert on4["text"] == "1쪽 글자\fOCR 2쪽 스캔 글\f3쪽 글자" and on4["rep"]["scan_fill"] == {
            "filled": {"2": "rapidocr_ko"},
            "skip": None,
        }
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
    print("[selftest] PE1 후속 — represent(): PARSE_SCAN_FILL 끔=rep 바이트 동일 · 켬=스캔 쪽만 채움(rep.rep.scan_fill 기록) 통과")

    # 독립 검토 보강 — PARSE_SCAN_FILL(기본 켬) × PARSE_DEDUP_SCAN=1(AD39) 동시 켜짐: 스캔 쪽을 OCR로 채운 뒤
    # apply_post의 쪽 VLM 중복 제거가 같은 쪽을 다시 봐도 쪽 번호가 안 섞이고 값이 안 없어진다(한쪽에만 있는 ID는
    # scan_dedup._extra_values가 보존).
    orig_vlm_page = _vp.vlm_page
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        _vp.vlm_page = lambda img, det=None: ("정돈된 VLM 글 설명(OCR과 다른 표현)", {"cached": False})
        # PARSE_PAGE_SCAN=1: page_text_pages가 스캔 쪽(2쪽)만 VLM 호출 · PARSE_POST=vlm_page: vlm_page 기능만(supsub 등 다른 후보정이 \f를 흔드는 것과 분리)
        with pc.PIPE.env(
            PARSE_PAGE_SCAN="1", PARSE_DEDUP_SCAN="1", PARSE_POST="vlm_page", PARSE_SCAN_FILL="1"
        ):  # S7c — 설정 객체만 바꿔 끼움
            represent(stack4, pd4, src=d4)
        combo = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert combo["rep"]["scan_fill"] == {"filled": {"2": "vlm_page"}, "skip": None}  # 10-29 — 쪽 VLM 글이 있으면 그것으로 채움
        parts = combo["text"].split("\f")
        assert len(parts) == 3 and parts[0] == "1쪽 글자" and parts[2] == "3쪽 글자"  # 쪽 번호 안 섞임(1·3쪽 그대로)
        assert "OCR 2쪽 스캔 글" in combo["text"] or "정돈된 VLM 글" in combo["text"]  # 2쪽 글 중 하나는 남음(값 손실 없음)
        assert combo["post"].get("dedup_scan_skipped") is None  # 쪽 번호 확정돼 dedup 정상 수행
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        _vp.vlm_page = orig_vlm_page
    print("[selftest] PE1 후속 — PARSE_SCAN_FILL × PARSE_DEDUP_SCAN=1 동시 켜짐: 쪽 번호 안 섞임·값 손실 없음 통과")

    # 10-29 — 스캔 쪽은 쪽 VLM 글로 채움(OCR 엔진 결과보다 먼저) · VLM 글이 비면 옛 OCR 경로 · apply_post는 채운 쪽을 다시 안 덧붙임
    try:
        _vp.scan_pages_detail = lambda p: {2: "chars"}
        fake_vlm = lambda p: [(2, "VLM 2쪽 스캔 글", {"cached": True})]  # 쪽 VLM 가짜(모델 호출 없음)
        rep_v = dict(base_rep4)
        assert fill_scan_pages(rep_v, doc4, dd4, stack4, pd4, pdf4, page_vlm=fake_vlm) == {"filled": {"2": "vlm_page"}, "skip": None}
        assert rep_v["text"] == "1쪽 글자\fVLM 2쪽 스캔 글\f3쪽 글자", rep_v["text"]
        rep_e = dict(base_rep4)  # VLM 글이 비면(호출 실패 등) 옛 OCR 엔진 결과로
        fill_e = fill_scan_pages(rep_e, doc4, dd4, stack4, pd4, pdf4, page_vlm=lambda p: [(2, "", {})])
        assert fill_e == {"filled": {"2": "rapidocr_ko"}, "skip": None}, fill_e
        _vp.vlm_page = lambda img, det=None: ("VLM 2쪽 스캔 글", {"cached": True})
        with pc.PIPE.env(PARSE_PAGE_SCAN="1", PARSE_DEDUP_SCAN="0", PARSE_POST="vlm_page", PARSE_SCAN_FILL="1"):
            represent(stack4, pd4, src=d4)
        v_out = json.loads((pd4 / "_rep" / f"{doc4}.json").read_text(encoding="utf-8"))
        assert v_out["rep"]["scan_fill"]["filled"] == {"2": "vlm_page"}
        assert v_out["text"].count("VLM 2쪽 스캔 글") == 1, v_out["text"]  # 채운 쪽을 apply_post가 또 덧붙이지 않음
    finally:
        _vp.scan_pages_detail = orig_scan_pages_detail
        _vp.vlm_page = orig_vlm_page
    print("[selftest] 10-29 — 스캔 쪽 쪽 VLM 글로 채움·VLM 빈 글이면 OCR 경로·채운 쪽 중복 덧붙임 없음 통과")

    # AD29 P1 — PARSE_FUSE(기본 꺼짐): 끄면 rep에 "fused" 키 자체가 안 생기고 나머지 바이트 동일 · 켜면 두 텍스트
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
    FUSE_FAM = ("PARSE_FUSE", "PARSE_FUSE_REREAD", "PARSE_FUSE_REREAD_P3")
    ALL_OFF = FUSE_FAM + ("PARSE_CONTEXT",)  # 아래 off5·off6가 같은 "전부 =0" 바탕이게(PARSE_CONTEXT도 기본 켬이라 같이 꺼야 함)
    with pc.PIPE.env(**{k: "0" for k in ALL_OFF}):  # S7c — 설정 객체만 바꿔 끼움
        represent(stack5, pd5)  # =0 — 전부 꺼짐
    off5 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert "fused" not in off5 and off5["text"] == "본문" and "context" not in off5
    with pc.PIPE.env(PARSE_FUSE_REREAD="0"):  # P1만 보려고 REREAD는 꺼둠(PARSE_FUSE는 기본 켬 그대로)
        represent(stack5, pd5)
    on5 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert on5["text"] == off5["text"] and on5["facts"] == off5["facts"]  # 켜도 본문·기존 facts는 그대로
    by5 = {f["context"][0]: f for f in on5["fused"]["facts"]}
    assert by5["금액"]["value"] == "430,000" and set(by5["금액"]["engines"]) == {"pdfplumber", "pymupdf"}
    assert on5["fused"]["conflicts"][0]["losers"][0]["engines"] == ["rapidocr_ko"]
    assert "reread" not in on5["fused"]  # REREAD=0이라 재판독 칸 없음
    print(
        "[selftest] AD29 P1 — PARSE_FUSE =0=rep 바이트 동일(fused 키 없음) · 기본 켬=라벨:값 조각 투표(신뢰도 높은 쪽 승, 본문·기존 facts 불변) 통과"
    )

    # PA0 — PARSE_CONTEXT(기본 켬, =0으로 끔): =0이면 rep에 context·decisions 키 자체가 없고 나머지 바이트 동일 · 기본(켬)이면 둘 다 생김
    with pc.PIPE.env(PARSE_CONTEXT=None):  # S7c — 설정 객체만 바꿔 끼움
        assert trace_mod.on() is True and trace_mod.on("0") is False
    with pc.PIPE.env(PARSE_CONTEXT="0", **{k: "0" for k in FUSE_FAM}):
        represent(stack5, pd5)  # 위 off5와 같은 모양(FUSE 가족·CONTEXT 모두 =0)
    off6 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert (
        "context" not in off6 and "decisions" not in off6 and _no_times(off6) == _no_times(off5)
    )  # 아래 "바이트 동일" = 소요 초 칸 빼고(S11)
    with pc.PIPE.env(**{k: "0" for k in FUSE_FAM}):  # CONTEXT만 보려고 FUSE 가족은 꺼둠(CONTEXT는 기본 켬 그대로)
        represent(stack5, pd5)
    on6 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert _no_times({k: v for k, v in on6.items() if k not in ("context", "decisions")}) == _no_times(off6)  # 다른 칸은 그대로
    assert on6["context"]["format"] == ".txt" and set(on6["context"]["engines"]) == {"pdfplumber", "pymupdf", "rapidocr_ko"}
    assert [x["step"] for x in on6["decisions"]][:2] == ["engine_scope", "representative"]
    print("[selftest] PA0 — PARSE_CONTEXT =0=rep 바이트 동일(context·decisions 키 없음) · 기본 켬=문서·엔진 신호 + 규칙 결정 기록 통과")

    # AD29 P2 — PARSE_FUSE_REREAD(기본 켬, =0으로 끔, PARSE_FUSE 전제): =0이면(또는 PARSE_FUSE가 =0이면) rep["fused"]에
    # "reread" 칸 자체가 안 생겨 바이트 동일 · 켜져도 이 문서(doc5="e.txt")는 source 경로가 없어(합성 selftest라
    # 실제 파일이 없음) 전부 건너뛰고 reason만 남긴다 — 실제 PDF로 좌표를 찾아 뒤집는 전 과정은 reread.py 자체
    # selftest(합성 PDF + 주입 OCR)와 cli/eval_fuse_conflicts.py --reread(실제 judge-conflicts 문서)가 맡는다
    # (무거운 OCR 모델을 매번 represent 선택 검사에서 불러오지 않으려는 의도, 결정적·가벼움 우선).
    with pc.PIPE.env(PARSE_FUSE="0"):  # PARSE_FUSE_REREAD는 기본 켬 그대로 — PARSE_FUSE 꺼짐이 우선인지 확인
        represent(stack5, pd5)
    off_rr = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert "fused" not in off_rr  # PARSE_FUSE 꺼짐이 우선 — PARSE_FUSE_REREAD가 켜져 있어도 아무 효과 없음
    with pc.PIPE.env(PARSE_FUSE_REREAD_P3="0"):  # P2만 보려고 P3는 꺼둠(PARSE_FUSE·PARSE_FUSE_REREAD는 기본 켬 그대로)
        represent(stack5, pd5)
    on_rr = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert on_rr["fused"]["facts"] == on5["fused"]["facts"]  # source 없음(doc_path None) — 재판독이 값을 안 건드림
    assert on_rr["fused"]["reread"]["skip_reason"] == "no_pdf"
    assert "p3" not in on_rr["fused"]["reread"]  # P3는 이 블록에서 꺼둠
    print(
        "[selftest] AD29 P2 — PARSE_FUSE_REREAD =0(또는 PARSE_FUSE =0)=rep 바이트 동일 · 기본 켬 + PDF 없는 문서는 건너뛰고 이유만 기록 통과"
    )

    # AD29 P3 — PARSE_FUSE_REREAD_P3(기본 켬, =0으로 끔, PARSE_FUSE_REREAD 전제): =0이면(위 on_rr과) rep["fused"]가
    # 바이트 동일(P3 모듈을 아예 안 부름) · 기본(켬)이어도 doc5는 source 경로가 없어(합성 selftest) 전부 건너뛰고
    # reason만 남긴다 — 실제 PDF로 그림을 찾아 뒤집는 전 과정은 reread_stage3.py 자체 selftest와
    # cli/eval_fuse_conflicts.py --reread --p3(실제 judge-conflicts 문서)가 맡는다(결정적·가벼움 우선, P2와 같은 설계).
    assert reread_p3_mod.on() is True and reread_p3_mod.on("0") is False
    with pc.PIPE.env(PARSE_FUSE_REREAD_P3="0"):
        represent(stack5, pd5)
    off_p3 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert _no_times(off_p3) == _no_times(on_rr)  # PARSE_FUSE_REREAD_P3 =0 — 위 P2-켬 결과와 같음(소요 초 칸 빼고 — S11)
    represent(stack5, pd5)  # 기본(미설정) = 전부 켬
    on_p3 = json.loads((pd5 / "_rep" / f"{doc5}.json").read_text(encoding="utf-8"))
    assert on_p3["fused"]["facts"] == on_rr["fused"]["facts"]  # source 없음(doc_path None) — P3도 값을 안 건드림
    assert on_p3["fused"]["reread"]["p3"]["skip_reason"] == "no_pdf"
    print("[selftest] AD29 P3 — PARSE_FUSE_REREAD_P3 =0(또는 P2 =0)=rep 바이트 동일 · 기본 켬 + PDF 없는 문서는 건너뛰고 이유만 기록 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
