"""pipeline.transform.structure.build_bundle 시험."""

import json
from pathlib import Path

import pipeline.transform.structure.build_bundle as M
from common.core import docmeta as DM
from common.core.paths import STACK_FILE
from common.core.text import tokens
from pipeline import config as pc
from pipeline.transform.structure.build_bundle import (
    embed_all,
    fig_empty,
    fig_host,
    fig_page_child,
    figure_chunk,
    figure_chunk_text,
    infer_clients,
    load_figures,
    main,
    warn_if_no_client_roster,
)


def selftest():
    # L3-1: docs.jsonl에 날짜·개정·구판·문서군(DM.doc_meta)이 실제로 섞여 들어가는지(결합 지점) — 규칙 자체는 common/docmeta.py --selftest
    m = DM.doc_meta("msa_rev2.docx", "[구판] 작성일 2026-05-01")
    assert m == {"doc_date": "2026-05-01", "version": "2", "superseded": True}  # family는 pl-38에 지움
    print("[selftest] docs 메타(날짜·개정·구판, L3-1) 결합 통과")

    # canon_clients(OCR 오탈자 고객 이름 맞추기)는 pl-38에 지움 — 교차 확인 고객(meta_confirmed)을 묶음이 더 만들지 않아 늘 할 일이 없었음
    ds = [
        {"client": "Pfizer Inc.", "meta_confirmed": True},
        {"full_text": "Supply Agreement · Pfizer Inc. / PFE-MAB-02 (C-PFE-2024-03)"},
        {"full_text": "QBR — 미르하제약(주) / MRH-ADC-04"},
        {"full_text": "··· / MRH-MAB-01 (C-MRH-2023-02)", "contract": {"product_code": "MRH-MAB-01"}},
    ]
    infer_clients(ds, roster={"미르하제약(주)": ["미르하제약"]})
    assert ds[1]["client"] == "Pfizer Inc." and ds[1]["client_src"] == "text" and ds[2]["client"] == "미르하제약(주)"
    import tempfile

    calls = []
    orig = M._embed
    M._embed = lambda m, t, kind: (calls.append(len(t)), __import__("numpy").ones((len(t), 4), dtype="float32"))[1]
    try:
        c = str(Path(tempfile.mkdtemp()) / "e.sqlite")
        embed_all("api", ["가", "나"], cache=c)
        v = embed_all("api", ["가", "나", "다"], cache=c)
        assert calls == [2, 1] and v.shape == (3, 4)  # 두 번째는 새 청크 1개만 API로

        # 안전망(L3-3): EMBED_MAX_CHARS보다 긴 본문은 잘라서 보냄 — vectors:chunks 1:1 정렬은 그대로
        received = []
        M._embed = lambda m, t, kind: (received.extend(t), __import__("numpy").ones((len(t), 4), dtype="float32"))[1]
        with pc.PIPE.env(EMBED_MAX_CHARS="5"):  # S7c — 설정 객체
            v2 = embed_all("api", ["짧음", "매우매우매우매우긴본문글자"], cache=str(Path(tempfile.mkdtemp()) / "e2.sqlite"))
        assert v2.shape == (2, 4) and max(len(t) for t in received) <= 5
    finally:
        M._embed = orig
    assert ds[3]["client"] == "미르하제약(주)" and ds[3]["client_src"] == "product"

    # BR57 — warn_if_no_client_roster: 명부 없음 + client 전부 빈 채일 때만 경고 한 줄(동작은 안 바꿈).
    import contextlib
    import io
    from unittest import mock

    from common.store import master

    with mock.patch.object(master, "get", lambda: master.Master({})):  # pl-38 — 빈 마스터(명부 없음)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([{"client": None}, {"client": ""}])
        assert "dbtool master load" in buf.getvalue() and "WARNING" in buf.getvalue(), buf.getvalue()

        buf = io.StringIO()  # 명부 없어도 client가 하나라도 있으면 경고 안 함
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([{"client": "Pfizer Inc."}, {"client": None}])
        assert buf.getvalue() == ""

        buf = io.StringIO()  # docs 비어 있으면(묶음 자체가 빈 경우) 경고 안 함
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([])
        assert buf.getvalue() == ""
    print("[selftest] BR57 — warn_if_no_client_roster: 명부 없음+client 전부 빔일 때만 경고, 동작(docs)은 안 바뀜 통과")
    print("[selftest] 고객사 이름 보정 통과")

    rec = {
        "image_id": "d.pdf#p2#i1",
        "doc": "d.pdf",
        "kind": "그래프",
        "caption": "그림 2. 배치별 titer",
        "vlm": {
            "model": "qwen-vlm",
            "summary": "요약",
            "text": "글자",
            "content": {"values": [{"label": "A", "value": "1", "unit": "g"}], "edges": [], "table_md": None},
        },
        "page": 2,
        "sheet": None,
        "bbox": [1, 2, 3, 4],
        "value_check": {"conflict": {"A": {"그림": "1", "본문": "2"}}, "agree": {}},
        "provenance": {"model": "qwen-vlm"},
    }
    text = figure_chunk_text(rec)
    assert "[그림 d.pdf#p2#i1]" in text and "캡션: 그림 2" in text and "값: A=1g" in text
    ch = figure_chunk(0, 5, rec)
    assert ch == {
        "doc": 0,
        "seq": 5,
        "page": 2,
        "sheet": None,
        "line_start": None,
        "line_end": None,
        "char_start": None,
        "char_end": None,
        "bbox": [1, 2, 3, 4],
        "section": None,
        "chunk_text": text,
        "n_chars": len(text),
        "n_terms": len(tokens(text)),
        "image_id": "d.pdf#p2#i1",
        "provenance_model": "qwen-vlm",
        "value_check_status": "conflict",
        "source_system": None,
    }  # S9 정리(Q7 a) — 서버가 그림 청크에 source_system 칸을 더함(10-20 서버 수정 — 기대값만 맞춤)

    # F14(c) — trend 필드가 있으면 그림 청크 본문에 추세 줄이 붙음(값 없으면 이전과 바이트 동일, 위 text가 그 증거)
    rec_trend = {**rec, "trend": {"direction": "증가", "period": "Q1–Q4", "basis": "Q1 41 → Q4 52"}}
    text_trend = figure_chunk_text(rec_trend)
    assert text_trend.startswith(text) and "추세: 증가(Q1–Q4, Q1 41 → Q4 52)" in text_trend
    print("[selftest] F14(c) — trend 필드가 있으면 그림 청크 본문에 추세 줄 추가(없으면 바이트 동일) 통과")
    import tempfile

    idir = Path(tempfile.mkdtemp())
    (idir / "index.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    by_doc = load_figures(idir)
    assert list(by_doc) == ["d.pdf"] and by_doc["d.pdf"][0]["image_id"] == "d.pdf#p2#i1"
    assert load_figures(idir / "없음") == {}
    print("[selftest] 그림 기록 → 청크 1개(L1, image_id·값 확인 상태 포함) 통과")

    # AD21③ — 빈·플레이스홀더 그림은 검색 청크로 안 만듦(fig_empty) · 상한/작은/반복(skipped)도 빈 것으로
    assert fig_empty(rec) is False  # 위 rec은 요약·값이 있어 빈 것 아님
    empty_vlm = {
        "image_id": "d.pdf#p1#i2",
        "vlm": {"model": "m", "summary": "", "text": None, "content": {"values": [], "edges": [], "table_md": ""}},
    }
    skipped_cap = {
        "image_id": "d.pdf#p1#i3",
        "vlm": {"model": None, "summary": None, "text": None, "content": {}},
        "skipped": "VLM_FIGURES_MAX",
    }
    for r in (empty_vlm, skipped_cap):
        assert fig_empty(r) is True, r
    print("[selftest] AD21③ 빈·플레이스홀더·상한 그림 기록 fig_empty 판정 통과")
    child = {"image_id": "s.jpg#p1#page.c1", "parent_image_id": "s.jpg#p1#page"}
    assert fig_page_child(child, {"s.jpg#p1#page"}) and not fig_page_child(child, set()) and not fig_page_child(rec, {"s.jpg#p1#page"})
    print("[selftest] F11 쪽 VLM 부모의 하위 그림은 청크 안 만듦 통과")

    # 독립 검토 MINOR② — fig_host: 같은 쪽 있으면 그 쪽(마지막 것) · 없으면 쪽 번호가 가장 가까운 청크(동점은 앞선 것) · 전부 쪽 없으면 첫 청크
    cs = [{"page": 1, "i": "a"}, {"page": None, "i": "b"}, {"page": 6, "i": "c"}, {"page": 3, "i": "d"}, {"page": 3, "i": "e"}]
    assert fig_host(cs, 3) == cs[4]  # 같은 쪽(3) 여러 개 → 마지막
    assert fig_host(cs, 4) == cs[3]  # 같은 쪽 없음 → 가장 가까움(|3-4|=1인 d·e 동점 → 앞선 것 d, c는 |6-4|=2로 밀림)
    assert fig_host([{"page": None, "i": "x"}], 9) == {"page": None, "i": "x"}  # 쪽 있는 청크 전혀 없음 → 첫 청크
    assert fig_host([], 1) is None
    print("[selftest] 독립 검토 MINOR② fig_host(같은 쪽 → 가까운 쪽 → 첫 청크) 통과")

    # 독립 검토 MAJOR① · MINOR③·④ — main()의 실제 분기를 거쳐 확인: 빠진 그림도 seq를 소비해 그 뒤 청크의 seq(=chunk_key)가
    # 어느 그림이 비었는지와 무관하게 고정 · image_ids는 같은 쪽 청크에 · meta.json에 figure_chunks_dropped.
    import tempfile

    def _ad21_fixture(mid_empty):
        root = Path(tempfile.mkdtemp())
        pd, sd = root / "parse", root / "src"
        sd.mkdir(parents=True)
        (pd / "_rep").mkdir(parents=True)
        (pd / "_images").mkdir(parents=True)
        doc = "d.pdf"
        (sd / doc).write_bytes(b"fixture source bytes")
        rep_doc = {
            "text": "1쪽 본문 문장.\n\f\n2쪽 본문 문장.",
            "tables": [],
            "facts": [],
            "chunks": [],
            "trace": {},
            "fields": {},
            "provenance": {},
            "rep": {
                "engine": "pymupdf",
                "acc": 1.0,
                "candidates": [],
                "fallback": False,
                "tried": [],
                "source": {},
                "format": ".pdf_text",
                "pages": 2,
                "meta": {"pairs": [], "all": []},
                "facts_added": 0,
                "table_fix": False,
                "low_n": False,
            },
            "post": {},
        }
        (pd / "_rep" / f"{doc}.json").write_text(json.dumps(rep_doc, ensure_ascii=False), encoding="utf-8")
        (pd / "_rep" / "index.json").write_text(
            json.dumps({"docs": [{"doc": doc, "engine": "pymupdf"}]}, ensure_ascii=False), encoding="utf-8"
        )
        mid_vlm = (
            {"model": None, "summary": None, "text": None, "content": {}}
            if mid_empty
            else {"model": "m", "summary": "2쪽 그림 B 요약", "text": "", "content": {"values": [], "edges": [], "table_md": ""}}
        )
        figs = [
            {
                "image_id": f"{doc}#p1#iA",
                "doc": doc,
                "page": 1,
                "sheet": None,
                "bbox": None,
                "kind": "그래프",
                "caption": None,
                "vlm": {"model": "m", "summary": "1쪽 그림 A 요약", "text": "", "content": {"values": [], "edges": [], "table_md": ""}},
                "value_check": {},
                "provenance": {"model": "m"},
                "skipped": None,
            },
            {
                "image_id": f"{doc}#p2#iB",
                "doc": doc,
                "page": 2,
                "sheet": None,
                "bbox": None,
                "kind": None,
                "caption": None,
                "vlm": mid_vlm,
                "value_check": {},
                "provenance": {},
                "skipped": "VLM_FIGURES_MAX" if mid_empty else None,
            },
            {
                "image_id": f"{doc}#p2#iC",
                "doc": doc,
                "page": 2,
                "sheet": None,
                "bbox": None,
                "kind": "표",
                "caption": None,
                "vlm": {"model": "m", "summary": "2쪽 그림 C 요약", "text": "", "content": {"values": [], "edges": [], "table_md": ""}},
                "value_check": {},
                "provenance": {"model": "m"},
                "skipped": None,
            },
        ]
        with open(pd / "_images" / "index.jsonl", "w", encoding="utf-8") as f:
            for r in figs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return pd, sd, root / "output" / "bundle"

    def _run(mid_empty):
        pd, sd, out = _ad21_fixture(mid_empty)
        # 엔진 구성은 파일로 명시(시험 전용 덮기 — 2b 전 기본값과 같은 git 파일). 서버 모드 이미지(RUN_ENV≠local)에서 판 번호 없이
        # pc.stack()이 거부(종료 2)하던 것 — 이미지 관문 10-30
        main(["--parse-dir", str(pd), "--src", str(sd), "--embed", "none", "--stack", str(STACK_FILE), "--out", str(out)])
        m = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        cs = [json.loads(ln) for ln in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        return m, cs, out

    m_empty, cs_empty, out_empty = _run(mid_empty=True)
    m_full, cs_full, out_full = _run(mid_empty=False)
    text_n_empty = sum(1 for c in cs_empty if c.get("image_id") is None)
    text_n_full = sum(1 for c in cs_full if c.get("image_id") is None)
    assert text_n_empty == text_n_full  # 텍스트 청크 수는 그림 유무와 무관(두 run 입력 본문이 같음)
    fig_a_full = next(c for c in cs_full if c.get("image_id") == "d.pdf#p1#iA")
    assert fig_a_full["seq"] == text_n_full  # 그림 A는 항상 텍스트 청크 바로 다음 seq
    fig_c_empty = next(c for c in cs_empty if c.get("image_id") == "d.pdf#p2#iC")
    fig_c_full = next(c for c in cs_full if c.get("image_id") == "d.pdf#p2#iC")
    assert (
        fig_c_empty["seq"] == fig_c_full["seq"] == text_n_full + 2
    )  # MAJOR① — 가운데 그림 B가 비든 안 비든 C의 seq(=chunk_key)는 같음(A·B·C 중 3번째)
    assert len(cs_empty) == text_n_empty + 2 and len(cs_full) == text_n_full + 3  # B는 빠지고(기본) 안 비면 3개 다 들어감
    assert m_empty["figure_chunks_dropped"] == 1 and m_full["figure_chunks_dropped"] == 0  # 실제로 뺀 그림 수
    hosts = [c for c in cs_empty if c.get("image_ids")]
    assert len(hosts) == 1 and hosts[0]["image_ids"] == [
        "d.pdf#p2#iB"
    ]  # 빠진 그림 B의 image_id는 텍스트 청크 하나에 연결(get_image 조회용)
    print("[selftest] 독립 검토 MAJOR① — 빠진 그림도 seq 소비(결정성) · image_ids 텍스트 청크 연결 통과")

    # pl-06(11-01) · pl-46(0.2.0) — 그림 행·사실·개념·그래프(kg) 파일은 안 만듦
    for gone in ("images.jsonl", "facts.jsonl", "concept_chunk.jsonl", "kg_nodes.jsonl", "kg_edges.jsonl"):
        assert not (out_empty / gone).exists(), gone
    print("[selftest] pl-06·pl-46 — 그래프·개념·그림 행·사실 파일 없음 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
