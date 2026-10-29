"""pipeline.transform.structure.build_bundle 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.structure.build_bundle --selftest`."""

import json
import os
from pathlib import Path

import pipeline.transform.structure.build_bundle as M
from common.core import docmeta as DM
from common.core.text import tokens
from pipeline import config as pc
from pipeline.transform.structure.build_bundle import (
    BIZ_REL,
    HUB_MAX,
    build_concept_chunk,
    build_graph,
    canon_clients,
    doc_facts,
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
    assert m == {"doc_date": "2026-05-01", "version": "2", "superseded": True, "family": "msa"}
    print("[selftest] docs 메타(날짜·개정·구판·문서군, L3-1) 결합 통과")

    ds = [{"client": "Northfield Biologics", "meta_confirmed": True}, {"client": "Northfeld Biologics"}, {"client": "Contoso Pharma"}]
    canon_clients(ds)
    assert ds[1] == {"client": "Northfield Biologics", "client_raw": "Northfeld Biologics"} and ds[2]["client"] == "Contoso Pharma"
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

    old_gdir = os.environ.pop("GLOSSARY_DIR", None)  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음
    old_roster = os.environ.pop("CLIENT_ROSTER", None)  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음
    try:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([{"client": None}, {"client": ""}])
        assert "GLOSSARY_DIR" in buf.getvalue() and "WARNING" in buf.getvalue(), buf.getvalue()

        buf = io.StringIO()  # 명부 없어도 client가 하나라도 있으면 경고 안 함
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([{"client": "Pfizer Inc."}, {"client": None}])
        assert buf.getvalue() == ""

        buf = io.StringIO()  # docs 비어 있으면(묶음 자체가 빈 경우) 경고 안 함
        with contextlib.redirect_stderr(buf):
            warn_if_no_client_roster([])
        assert buf.getvalue() == ""
    finally:
        if old_gdir is not None:
            os.environ["GLOSSARY_DIR"] = old_gdir  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음(복원)
        if old_roster is not None:
            os.environ["CLIENT_ROSTER"] = old_roster  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음(복원)
    print("[selftest] BR57 — warn_if_no_client_roster: 명부 없음+client 전부 빔일 때만 경고, 동작(docs)은 안 바뀜 통과")
    raw = {
        "text": "",
        "facts": [
            {"context": ["항목"], "cells": ["단가", "수량(L)"]},
            {"context": ["A-1"], "cells": ["USD 1", "1,000"]},
            {"context": ["A-1 "], "cells": ["USD 1", "1000"]},
            {"context": [" a-1"], "cells": ["USD 1", "1 000"]},
        ],
    }
    assert [f["num"] for f in doc_facts(0, raw, [])] == [1000.0]  # E2: 쉼표·공백·대소문자 변형 같은 A-1 행 3개 → 사실 1개·SUM 1,000
    print("[selftest] 고객사 이름 보정 통과")

    # AD24④ — 그림 속 표(table_md)의 첫 열이 단계 번호(1,2,3… 연속 일련번호)일 때 식별 열(장비 이름)을 item으로,
    # 값의 단위를 채움(꼬리의 첫 토큰만 — review 1차④, "20 L 유리병" → "L")
    fig_table = {
        "text": (
            "| 단계 | 장비/용기 | 용량 | 기간 |\n|---|---|---|---|\n"
            "| 1 | 20 L 플라스크 | 20 L | Day 0-4 |\n| 2 | SB-0201 | 200 L | Day 4-8 |\n"
            "| 3 | BR-2001 | 2,000 L 스테인리스 | Day 8-22 |"
        ),
        "facts": [],
    }
    ff = doc_facts(0, fig_table, [])
    assert [f["item"] for f in ff] == ["20 L 플라스크", "SB-0201", "BR-2001"], ff  # 번호 열 "1/2/3"이 아니라 장비 이름
    assert [f["unit"] for f in ff] == ["L", "L", "L"], ff  # "2,000 L 스테인리스"도 단위는 "L"만(꼬리 첫 토큰)
    print("[selftest] 집계 사실 item=식별 열·단위 채움(AD24④) 통과")

    # review 1차③ — 행 라벨이 숫자이기만 하고 연속 일련번호가 아니면(품목 코드) item을 그대로 둠
    code_table = {"text": "| 코드 | 품목 | 수량 |\n|---|---|---|\n| 1001 | 위젯 | 5 개 |\n| 2050 | 가젯 | 3 개 |", "facts": []}
    cf = doc_facts(0, code_table, [])
    assert [f["item"] for f in cf] == ["1001", "2050"], cf  # 연속 아님 → 품목 코드 그대로(장비 이름으로 안 바꿈)
    print("[selftest] 연속 아닌 숫자 행 라벨(품목 코드) 보존(review 1차③) 통과")

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
    # 어느 그림이 비었는지와 무관하게 고정 · image_ids는 같은 쪽 청크에 · 꺼짐(BUNDLE_KEEP_EMPTY_FIG=1)은 바이트 동일(복제 로직 없이
    # figure_chunk()를 그대로 호출한 것과 일치) · meta.json의 figure_chunks_dropped는 켜졌을 때만.
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

    def _run(mid_empty, env_keep, chunk_head=True):
        pd, sd, out = _ad21_fixture(mid_empty)
        # S7c — 설정 객체(env 안 건드림) · CHUNK_HEAD: G9 머리말·n_terms 재계산은 AD21과 무관 — 끄고 figure_chunk() 그대로 비교(MINOR③④)
        with pc.PIPE.env(BUNDLE_KEEP_EMPTY_FIG="1" if env_keep else "0", CHUNK_HEAD="1" if chunk_head else "0"):
            main(["--parse-dir", str(pd), "--src", str(sd), "--embed", "none", "--out", str(out)])
        m = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        cs = [json.loads(ln) for ln in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        return m, cs, out

    m_empty, cs_empty, out_empty = _run(mid_empty=True, env_keep=False)
    m_full, cs_full, out_full = _run(mid_empty=False, env_keep=False)
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
    assert m_empty["figure_chunks_dropped"] == 1 and m_full["figure_chunks_dropped"] == 0  # 둘 다 켜짐(기본) — 실제로 뺀 그림 수만 다름
    hosts = [c for c in cs_empty if c.get("image_ids")]
    assert len(hosts) == 1 and hosts[0]["image_ids"] == [
        "d.pdf#p2#iB"
    ]  # 빠진 그림 B의 image_id는 텍스트 청크 하나에 연결(get_image 조회용)
    print("[selftest] 독립 검토 MAJOR① — 빠진 그림도 seq 소비(결정성) · image_ids 텍스트 청크 연결 통과")

    # F8 — images.jsonl(추가 파일, doc_image·chunk_image 적재 원본): 3개 그림 모두 기록, chunk/rel이 실제 chunks.jsonl 쪽을 가리킴
    imgs_empty = [json.loads(ln) for ln in (out_empty / "images.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert {r["image_id"] for r in imgs_empty} == {"d.pdf#p1#iA", "d.pdf#p2#iB", "d.pdf#p2#iC"}
    rel = {r["image_id"]: r["rel"] for r in imgs_empty}
    assert rel == {"d.pdf#p1#iA": "figure_chunk", "d.pdf#p2#iB": "host", "d.pdf#p2#iC": "figure_chunk"}
    by_id = {r["image_id"]: r for r in imgs_empty}
    assert cs_empty[by_id["d.pdf#p1#iA"]["chunk"]]["image_id"] == "d.pdf#p1#iA"  # 자신의 그림 청크
    assert cs_empty[by_id["d.pdf#p2#iC"]["chunk"]]["image_id"] == "d.pdf#p2#iC"
    assert cs_empty[by_id["d.pdf#p2#iB"]["chunk"]]["image_ids"] == ["d.pdf#p2#iB"]  # 빈 그림 B → host 텍스트 청크(hosts[0]과 같은 것)
    imgs_full = [json.loads(ln) for ln in (out_full / "images.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert all(r["rel"] == "figure_chunk" for r in imgs_full)  # BUNDLE_KEEP_EMPTY_FIG 없이도 안 빈 그림은 전부 자신의 청크
    print("[selftest] F8 — images.jsonl(doc_image·chunk_image 적재 원본) 생성·chunk/rel 연결 통과")

    m_keep, cs_keep, out_keep = _run(mid_empty=True, env_keep=True, chunk_head=False)  # MINOR③④ — BUNDLE_KEEP_EMPTY_FIG=1(꺼짐)
    assert "figure_chunks_dropped" not in m_keep  # 꺼짐 — meta.json에 새 키를 안 넣음(독립 검토 MINOR④)
    text_n = sum(1 for c in cs_keep if c.get("image_id") is None)
    expected = [
        figure_chunk(0, text_n + i, r)
        for i, r in enumerate(
            [
                json.loads(ln)
                for ln in (out_keep.parent.parent / "parse" / "_images" / "index.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        )
    ]
    assert [
        c for c in cs_keep if c.get("image_id") is not None
    ] == expected  # 복제 로직 없이 figure_chunk()를 그대로 쓴 것과 일치(바이트 동일)
    print("[selftest] 독립 검토 MINOR③④ — BUNDLE_KEEP_EMPTY_FIG=1은 figure_chunk() 그대로(바이트 동일)·meta 새 키 없음 통과")

    docs2 = [
        {"doc_key": "c" * 64}
    ]  # S9b(C-54) — 10-20 축소 스키마: 문서 행 키가 file_sha256 → doc_key(build_bundle 문서 행·build_concept_chunk 모두) — 시험 데이터만 낡았음
    chunks2 = [
        {"doc": 0, "seq": 0, "chunk_text": "DSP 공정에서 바이러스 불활화(VI)를 수행"},
        {"doc": 0, "seq": 1, "chunk_text": "관련 없는 문장"},
    ]
    g = {
        "PROC.VI": {"canonical": "Viral Inactivation", "synonyms": "바이러스 불활화", "abbreviations": "VI", "weak_synonyms": ""},
        "PROC.DSP": {"canonical": "DSP", "synonyms": "", "abbreviations": "", "weak_synonyms": ""},
    }
    cc = build_concept_chunk(docs2, chunks2, g)
    assert {(r["concept_id"], r["chunk_key"], r["count"]) for r in cc} == {
        ("PROC.VI", f"{'c' * 64}:0", 2),
        ("PROC.DSP", f"{'c' * 64}:0", 1),
    }
    assert build_concept_chunk(docs2, chunks2, {}) == []  # 사전 없음 — 빈 목록(추가 파일이라 기본 흐름 불변)
    print("[selftest] 개념→청크 역색인(X4) 통과")

    _selftest_build_graph()


def _selftest_build_graph():
    """AD28②③ — build_graph()가 기존 entity·label·value에 더해 업무 개체(client·contract·product·modality·batch·id)·
    업무 관계(client-has-contract·contract-covers-product·doc-links-contract)·개념 노드(concept, broader·related)를
    만드는지. glossary·concept_chunk를 안 주면(기존 호출자) 개념 쪽은 생기지 않음(바이트 동일 하위 호환)도 같이 확인.
    engine-qa MAJOR(10-08) — 관계 간선·그 노드 props(confirmed·prov)는 doc.meta_confirmed(교차 확인)일 때만."""
    import tempfile

    gdir = Path(tempfile.mkdtemp())
    (gdir / "id_patterns.csv").write_text(
        'id_type,regex,example,note,updated\ncontract_no,"C-[A-Z]{2,4}-\\d{4}-\\d{2}",C-PFE-2024-02,,\nlot_no,"LOT-\\d{4}-\\d{3,}",LOT-2025-324,,\n',
        encoding="utf-8",
    )
    (gdir / "domain_terms.csv").write_text(  # T._aliases()가 GLOSSARY_DIR을 보면 load_glossary도 돎 — 머리글만(빈 사전)
        "concept_id,canonical,category,synonyms,abbreviations,weak_synonyms,broader,related,context_required,"
        "case_sensitive,definition_ko,definition_en,status\n",
        encoding="utf-8",
    )
    os.environ["GLOSSARY_DIR"] = str(
        gdir
    )  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음 · id_patterns.csv(contract_no·lot_no)만 — load_id_patterns_typed용
    try:
        sha = "a" * 64
        docs = [
            {
                "doc_key": sha,
                "doc_name": "a.pdf",
                "file_path": "d/a.pdf",  # S9b(C-54) — 10-20 축소 스키마 문서 행 키(옛 file_sha256·file_name)
                "client": "Pfizer Inc.",
                "contract_no": "C-PFE-2024-03",
                "contract": {"product_code": "PFE-MAB-02"},
                "summary": "",
                "meta_confirmed": True,
            }
        ]
        chunks = [{"doc": 0, "seq": 0, "chunk_text": "Pfizer Inc.와 PFE-MAB-02(mAb) 계약 C-PFE-2024-03, 로트 LOT-2025-324"}]
        folder_of = lambda d: d["file_path"].rsplit("/", 1)[0]
        nodes, edges = build_graph(docs, chunks, folder_of)  # glossary·concept_chunk 생략 — 기존 호출자 그대로
        by_kind = {}
        for n in nodes:
            by_kind.setdefault(n["kind"], set()).add(n["node_key"])
        assert by_kind.get("client") == {"pfizerinc."} and by_kind.get("contract") == {"c-pfe-2024-03"}
        assert by_kind.get("product") == {"pfe-mab-02"} and by_kind.get("modality") == {"mab"}
        assert by_kind.get("batch") == {"lot-2025-324"}, by_kind.get("batch")
        assert "concept" not in by_kind  # glossary 생략 → 개념 노드 없음(하위 호환)
        rel_set = {(nodes[e["src"]]["kind"], nodes[e["dst"]]["kind"], e["rel"]) for e in edges}
        assert ("doc", "contract", "doc-links-contract") in rel_set
        assert ("client", "contract", "client-has-contract") in rel_set
        assert ("contract", "product", "contract-covers-product") in rel_set
        assert ("chunk", "client", "mentions") in rel_set and ("chunk", "contract", "mentions") in rel_set
        assert ("chunk", "product", "mentions") in rel_set and ("chunk", "modality", "mentions") in rel_set
        assert ("chunk", "batch", "mentions") in rel_set
        biz_edges = [e for e in edges if e["rel"] in BIZ_REL]
        assert biz_edges and all(e.get("confirmed") is True and e.get("prov") == "bundle" for e in biz_edges), biz_edges
        contract_node = next(n for n in nodes if n["kind"] == "contract")
        assert contract_node["props"] == {"confirmed": True, "prov": "bundle"}, contract_node
        print("[selftest] AD28② engine-qa MAJOR — 교차 확인된 문서(meta_confirmed=True)의 관계 간선·노드 props(confirmed·prov) 통과")

        # engine-qa MAJOR(10-08) — meta_confirmed=False(단일 엔진 추정값)면 관계 간선 0, mentions만 그대로
        docs_u = [{**docs[0], "meta_confirmed": False}]
        nodes_u, edges_u = build_graph(docs_u, chunks, folder_of)
        rel_set_u = {(nodes_u[e["src"]]["kind"], nodes_u[e["dst"]]["kind"], e["rel"]) for e in edges_u}
        assert not any(r in BIZ_REL for _, _, r in rel_set_u), rel_set_u  # 관계 간선 0
        assert ("chunk", "client", "mentions") in rel_set_u and ("chunk", "contract", "mentions") in rel_set_u  # mentions는 그대로
        assert ("chunk", "product", "mentions") in rel_set_u and ("chunk", "batch", "mentions") in rel_set_u
        contract_node_u = next(n for n in nodes_u if n["kind"] == "contract")
        assert "props" not in contract_node_u, contract_node_u  # 관계 경로를 안 타 confirmed·prov props도 안 실림(mentions 전용 생성)
        docs_missing = [{**docs[0]}]
        del docs_missing[0]["meta_confirmed"]  # meta_confirmed 키 자체가 없는 문서(옛 호출자)도 False와 같게 처리
        nodes_m, edges_m = build_graph(docs_missing, chunks, folder_of)
        rel_set_m = {(nodes_m[e["src"]]["kind"], nodes_m[e["dst"]]["kind"], e["rel"]) for e in edges_m}
        assert not any(r in BIZ_REL for _, _, r in rel_set_m), rel_set_m
        print("[selftest] AD28② engine-qa MAJOR — meta_confirmed=False(또는 없음) 문서는 관계 간선 0, mentions만 유지 통과")
    finally:
        os.environ.pop("GLOSSARY_DIR", None)  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음(복원)
    print("[selftest] AD28② build_graph 업무 개체(client·contract·product·modality·batch)·관계(doc-links-contract 등) 통과")

    # AD28③ — 개념 노드 + broader·related(둘 다 실제 멘션됐을 때만) + 멘션 안 된 형제 개념은 노드 자체가 안 생김
    docs2 = [{"doc_key": "b" * 64, "doc_name": "b.pdf", "file_path": "d/b.pdf", "summary": ""}]  # S9b(C-54) — 축소 스키마 키
    chunks2 = [{"doc": 0, "seq": 0, "chunk_text": "DSP 공정에서 바이러스 불활화(VI)를 수행"}]
    g = {
        "PROC.VI": {
            "canonical": "Viral Inactivation",
            "synonyms": "바이러스 불활화",
            "abbreviations": "VI",
            "weak_synonyms": "",
            "broader": "PROC.DSP",
            "related": "PROC.UNSEEN",
        },
        "PROC.DSP": {"canonical": "DSP", "synonyms": "", "abbreviations": "", "weak_synonyms": "", "broader": "", "related": ""},
        "PROC.UNSEEN": {"canonical": "Unseen", "synonyms": "", "abbreviations": "", "weak_synonyms": "", "broader": "", "related": ""},
    }
    cc2 = build_concept_chunk(docs2, chunks2, g)
    n2, e2 = build_graph(docs2, chunks2, folder_of, g, cc2)
    k2 = {n["id"]: n["kind"] for n in n2}
    ck2 = {n["id"]: n["node_key"] for n in n2}
    assert {ck2[n["id"]] for n in n2 if n["kind"] == "concept"} == {"PROC.VI", "PROC.DSP"}  # PROC.UNSEEN은 멘션이 없어 노드 자체가 없음
    rel2 = {(k2[e["src"]], k2[e["dst"]], e["rel"]) for e in e2}
    assert ("chunk", "concept", "concept_chunk") in rel2
    assert ("concept", "concept", "broader") in rel2 and ("concept", "concept", "related") not in rel2  # related 상대(UNSEEN)는 없음
    print("[selftest] AD28③ build_graph 개념 노드·broader(둘 다 멘션됐을 때만, 고아 노드 없음) 통과")

    # 허브 규칙(HUB_MAX)이 새 개체·개념에도 적용되는지 — 같은 개체가 HUB_MAX(5) 넘는 문서에 걸치면 청크 연결이 끊김
    many_docs = [{"doc_key": f"{i:064d}", "doc_name": f"{i}.pdf", "file_path": f"d/{i}.pdf", "summary": ""} for i in range(HUB_MAX + 1)]
    many_chunks = [{"doc": i, "seq": 0, "chunk_text": "흔한 모달리티 mAb 공정 설명"} for i in range(HUB_MAX + 1)]
    n3, e3 = build_graph(many_docs, many_chunks, folder_of)
    k3 = {n["id"]: n for n in n3}
    mab_id = next(n["id"] for n in n3 if n["kind"] == "modality" and n["node_key"] == "mab")
    assert k3[mab_id].get("props", {}).get("hub_docs") == HUB_MAX + 1  # 노드는 남되 허브 표시
    assert not any(e["dst"] == mab_id and e["rel"] == "mentions" for e in e3)  # 청크 연결은 끊김(기존 entity와 같은 규칙)
    print("[selftest] AD28② HUB_MAX가 새 업무 개체에도 적용 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
