"""pipeline.transform.figures.figure_extract 시험."""

import contextlib
import io
import json
import os
from pathlib import Path
from unittest import mock

import pipeline.transform.figures.figure_extract as M
from common.ai import llm as A  # 모델 호출(0.2.0 — 옛 common.ai.adk, pl-46)
from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.shared.raw_cache import raw_root, raw_vlm_path
from pipeline.transform.figures.figure_extract import (
    FIG_OCR_FALLBACK_MIN_CHARS_DEFAULT,
    FULL_VERSION,
    P_FIGJ,
    _meaningful_chars,
    _model_dir,
    _open_image,
    _pick_edges,
    _px_size,
    _save_png,
    _unconvertible_kind,
    build_records,
    classify_figure_kind,
    figures,
    parse_json,
    select_figures,
    sha,
    write_index,
)


def _senv(**names):
    """selftest용(S7c) — 옛 os.environ 쓰기·지움을 설정 객체 덮기(pc.PIPE.env·COMMON.env)로 대신. None = 지움. with로 쓰거나
    변수에 받아 .close()(겹쳐 쓰면 안쪽부터 되돌림) — os.environ은 안 건드린다(이 객체를 읽는 코드만 바뀜)."""
    from common.config.settings import CommonAppSettings, env_map

    common_keys = env_map(CommonAppSettings)  # 칸 이름으로 가름(common 칸 → COMMON, 그 밖 → PIPE — 손으로 적은 목록이 빠지지 않게)
    st = contextlib.ExitStack()
    st.enter_context(pc.PIPE.env(**{k: v for k, v in names.items() if k not in common_keys}))
    st.enter_context(COMMON.env(**{k: v for k, v in names.items() if k in common_keys}))
    return st


def selftest():
    import tempfile

    d = Path(tempfile.mkdtemp())
    assert figures(d / "no-such.unknown") == []  # 모르는 확장자 — 그림 없음(오류 아님)
    # VLM 미설정일 때 vlm_fig는 오류를 담아 빈 글자(파싱은 계속) — PNG 3000바이트 이상인 더미 이미지
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (80, 80), "red").save(buf, "PNG")
    png = buf.getvalue()
    _env = _senv(VLM_BASE_URL=None, VLM_MODEL=None)  # S7c — 설정 객체만 바꿔 끼움(selftest 끝에서 되돌림)
    try:
        text, prov = M.vlm_fig(png)
        assert text == "" and "미설정" in prov["error"]
        rec = parse_json('```json\n{"kind": "표", "text": "a"}\n```')
        assert rec == {"kind": "표", "text": "a"}
        out = d / "images"
        rec0 = {
            "image_id": "doc.pdf#p1#i1",
            "doc": "doc.pdf",
            "source_file": "doc.pdf",
            "_bytes": png,
            "page": 1,
            "sheet": None,
            "anchor": None,
            "bbox": None,
            "origin": "raster",
            "sha256": sha(png),
            "text_layer": "",
            "kind": None,
            "vlm": {"model": None, "summary": None, "text": None, "content": {}},
            "caption": None,
            "caption_source": None,
            "mentions": [],
            "value_check": {},
            "vlm_error": None,
            "skipped": None,
            "parent_image_id": None,
            "depth": 0,
            "children": [],
            "page_render": False,
            "doc_sha256": "x",
            "run_id": 0,
            "provenance": {},
        }
        rows = write_index("doc.pdf", [dict(rec0)], out_images=out)
        assert len(rows) == 1 and (out / "doc.pdf" / "doc.pdf#p1#i1.png").exists()
        assert (out / "index.jsonl").exists()
        write_index("doc.pdf", [dict(rec0)], out_images=out)  # 다시 쓰면 upsert(중복 안 쌓임)
        assert len((out / "index.jsonl").read_text(encoding="utf-8").splitlines()) == 1
        print("[selftest] 그림 없음·VLM 미설정 안전 경로·index.jsonl upsert·PNG 저장 통과")

        # SI30 — _unconvertible_kind: 머리글로 WMF(Placeable·표준)·EMF·그 밖 형식 구분(순수 함수, Pillow 호출 없음)
        assert _unconvertible_kind(b"\xd7\xcd\xc6\x9a" + b"\x00" * 50) == "wmf"  # Placeable WMF(APM) — Word 삽입 그림 대부분
        assert _unconvertible_kind(b"\x01\x00\x09\x00" + b"\x00" * 50) == "wmf"  # 표준(비APM) WMF — mtType=1
        assert _unconvertible_kind(b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"\x00" * 20) == "emf"
        assert _unconvertible_kind(b"SI30-not-an-image-just-garbage-bytes" * 4) == "image"

        # SI30 — Pillow가 못 여는 그림(WMF/EMF 등, Linux에서 실제로 일어남 — 이 머신은 Windows라 가짜 WMF 머리글조차
        # 열릴 수 있어 여기서는 Pillow가 모든 플랫폼에서 못 여는 순수 쓰레기 바이트로 "못 엶" 경로만 확인)
        bad = b"SI30-not-an-image-just-garbage-bytes" * 4
        assert _open_image(bad) is None and _px_size(bad) == (0, 0)
        w, h, unconv = _save_png(bad, d / "bad.png")
        assert w is None and h is None and unconv == "image" and not (d / "bad.png").exists()
        rec_bad = {**rec0, "image_id": "doc.pdf#p1#i2", "_bytes": bad, "sha256": sha(bad), "skipped": None}
        rows2 = write_index("doc.pdf", [dict(rec0), dict(rec_bad)], out_images=out)  # 그림 하나 못 열어도 문서(다른 그림)는 계속
        by_id = {r["image_id"]: r for r in rows2}
        assert by_id["doc.pdf#p1#i2"]["png"] is None and by_id["doc.pdf#p1#i2"]["skipped"] == "unconvertible:image"
        assert by_id["doc.pdf#p1#i1"]["png"] is not None  # 정상 그림은 그대로(바이트 동일)
        text2, prov2 = M.vlm_fig(bad)
        assert text2 == "" and prov2["skipped"] == "unconvertible:image"  # vlm_fig 자체 가드(select_figures 분류와 무관)
        print("[selftest] SI30 — Pillow가 못 여는 그림은 예외 없이 unconvertible로 기록·다른 그림은 계속(write_index 안 멈춤) 통과")

        big_png = io.BytesIO()
        Image.new("RGB", (200, 200), "blue").save(big_png, "PNG")
        figs_mix = [{"bytes": bad, "area_ratio": None}, {"bytes": big_png.getvalue(), "area_ratio": None}]
        order, skip = select_figures(figs_mix, [{"caption": None, "mentions": []}, {"caption": None, "mentions": []}], 64)
        assert order == [1] and skip == {0: "unconvertible:image"}  # SI30 — "small"이 아니라 "unconvertible"로 구분
        print("[selftest] SI30 — select_figures가 못 여는 그림을 'small'이 아니라 'unconvertible'로 구분 통과")

        px = {1: [{"from": "A", "to": "B", "label": None}]}
        assert _pick_edges(".pptx", 1, px, [{"from": "X", "to": "Y"}]) == (px[1], "pptx_xml")  # 연결선 XML이 VLM보다 우선
        assert _pick_edges(".pptx", 2, px, [{"from": "X", "to": "Y"}]) == ([{"from": "X", "to": "Y"}], "vlm")  # 연결선 없는 슬라이드는 VLM
        assert _pick_edges(".pdf", 1, px, None) == (None, None)
        print("[selftest] pptx 연결선 우선순위(연결선 > VLM) 통과")

        # 독립 검토 B(AD12) — 기본 켬(AD31)이면 scan_pages() 쪽(글자 거의 없음+이미지 꽉 찬 쪽)도 쪽 전체 래스터
        # 기록은 figures()가 남긴다(BR56: 전엔 통째로 건너뛰어 그림 기록이 0건이 되는 버그였음) — loc.page_vlm=True만
        # 남겨 build_records가 VLM만 생략(쪽 VLM과 중복 호출 방지).
        import fitz

        mixed = d / "mixed.pdf"
        mdoc = fitz.open()
        mdoc.new_page(width=400, height=600).insert_text((50, 50), "본문 글자가 충분히 있는 쪽 " * 5)
        buf2 = io.BytesIO()
        Image.frombytes("RGB", (400, 600), os.urandom(400 * 600 * 3)).save(buf2, "PNG")  # 노이즈 — 3000바이트 필터 통과(AD9)
        mdoc.new_page(width=400, height=600).insert_image(fitz.Rect(0, 0, 400, 600), stream=buf2.getvalue())
        mdoc.new_page(width=400, height=600).insert_text((50, 50), "마지막 쪽도 글자가 있다 " * 5)
        mdoc.save(mixed)
        mdoc.close()
        _e = _senv(PARSE_RAW_ROOT=str(d / "store2"))
        try:
            recs_on = figures(mixed)
            rec2_on = next(r for r in recs_on if r["loc"]["page"] == 2)  # BR56 — 2쪽 scan_pages 대상이어도 기록은 남음
            assert rec2_on["loc"]["page_vlm"] is True
        finally:
            _e.close()
        print(
            "[selftest] BR56·독립 검토 B(AD12)·AD31 — scan_pages 쪽도 그림 기록은 남기고 page_vlm 표시만(VLM은 build_records가 생략) 통과"
        )

        # AD20 후속(10-11) — pptx_render.target_slides()가 돌려준 슬라이드(쪽 VLM이 이미 전체를 다룸)는 그 슬라이드의
        # 삽입 그림(shape_type==13)도 기록은 남기고(BR56) loc.page_vlm=True만 표시한다(그림 VLM·쪽 VLM 이중 호출 방지는
        # build_records 몫). soffice가 이 PC에 없을 수 있어(target_slides가 그럴 때 빈 집합을 돌림, 실제 soffice
        # 유무와 무관하게 로직만 확인) 여기선 target_slides를 직접 바꿔 끼운다.
        from pptx import Presentation as _Presentation

        import pipeline.transform.figures.pptx_render as _pr_mod

        buf3 = io.BytesIO()
        Image.frombytes("RGB", (150, 150), os.urandom(150 * 150 * 3)).save(buf3, "PNG")  # 노이즈 — 3000바이트 필터 통과(AD9)
        pic_bytes = buf3.getvalue()
        prs2 = _Presentation()
        sl1 = prs2.slides.add_slide(prs2.slide_layouts[6])  # 1쪽 — 쪽 VLM 대상(중복 방지 대상)
        sl1.shapes.add_picture(io.BytesIO(pic_bytes), 0, 0)
        sl2 = prs2.slides.add_slide(prs2.slide_layouts[6])  # 2쪽 — 대상 아님(평소처럼 그림 VLM 기록)
        sl2.shapes.add_picture(io.BytesIO(pic_bytes), 0, 0)
        pptx_dedup = d / "dedup.pptx"
        prs2.save(pptx_dedup)
        orig_target_slides = _pr_mod.target_slides
        _pr_mod.target_slides = lambda p: {1}  # 1쪽만 쪽 VLM 대상인 척
        try:
            figs_dedup = figures(pptx_dedup)
            rec1 = next(f for f in figs_dedup if f["loc"]["slide"] == 1)  # BR56 — 1쪽 그림도 기록은 남음
            assert rec1["loc"]["page_vlm"] is True
            rec2 = next(f for f in figs_dedup if f["loc"]["slide"] == 2)  # 2쪽 그림 — 평소처럼(표시 없음)
            assert rec2["loc"].get("page_vlm") is False
        finally:
            _pr_mod.target_slides = orig_target_slides
        print(
            "[selftest] BR56·AD20 후속 — target_slides가 고른 슬라이드의 삽입 그림도 기록은 남고 page_vlm 표시만(이중 VLM 호출은 build_records가 막음) 통과"
        )

        # BR56 — 단독 이미지 문서(screenshot_nested.png류): AD31/AD20과 무관하게 지금까지 figures()에 이 확장자 분기가
        # 전혀 없어 기록이 0건이었다(IQ049 — get_image가 그림을 못 찾던 원인). 문서 전체를 그림 1건으로 기록.
        standalone_png = d / "standalone.png"
        Image.frombytes("RGB", (120, 120), os.urandom(120 * 120 * 3)).save(standalone_png)  # 노이즈 — 3000바이트 필터 통과(AD9)
        _e = _senv(PARSE_RAW_ROOT=str(d / "store3"))
        try:
            figs_png = figures(standalone_png)
            assert len(figs_png) == 1 and figs_png[0]["image_id"] == "standalone.png#p1#page", figs_png  # F7 — 설계 §3 "#p<쪽>#page"
            assert figs_png[0]["loc"]["page_vlm"] is True  # 기본 켬 — 단독 이미지 전체가 쪽 VLM(page_text) 대상
        finally:
            _e.close()
        print("[selftest] BR56 — 단독 이미지 문서(figures() 분기 없던 공백)도 그림 1건으로 기록 통과")

        # BR56 — build_records: loc.page_vlm=True 그림은 그림 VLM을 안 부르고
        # (skip_reason="page_vlm") 기록은 그대로 남는다(VLM 호출 수 불변 확인).
        _e = _senv(PARSE_RAW_ROOT=str(d / "store4"), PARSE_IMAGES_ROOT=str(d / "images4"))
        calls = []

        def _fake_vlm_fig(img, max_tokens=None):  # 시험용 가짜 — 부른 횟수만 셈
            calls.append(1)
            return "", {}

        _p = mock.patch.object(M, "vlm_fig", _fake_vlm_fig)
        _p.start()
        try:
            recs_bm, _, _ = build_records("standalone.png", standalone_png, "", "docsha_br56c")
            assert len(recs_bm) == 1 and recs_bm[0]["skipped"] == "page_vlm" and calls == []
        finally:
            _p.stop()
            _e.close()
        print("[selftest] BR56 — build_records: page_vlm 그림은 기록은 남고 그림 VLM은 0회 통과")
    finally:
        _env.close()  # S7c — 맨 위에서 바꿔 끼운 VLM 미설정 되돌림(VS7c2 R-6 — 실패해도)


def selftest_select():
    """AD9·AD21①②③ — 상한 2·그림 5개 문서: skipped 표시·우선순위(캡션·본문 언급·면적)·작은/반복 제외·
    이어서 처리(캐시 재사용 — 재호출 0) 통과(capped.jsonl은 0.2.0에 지움 — pl-46)."""
    import tempfile

    import docx as _docx
    from PIL import Image

    def _noise_png(w, h):
        buf = io.BytesIO()
        Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(buf, "PNG")  # 노이즈 — 3000바이트 필터를 통과시키려 압축 안 되게
        return buf.getvalue()

    big = _noise_png(300, 300)  # img_cap(1번째 신호) — 캡션 + 본문 언급 + 가장 큼
    mid = _noise_png(150, 150)  # img_mention(3번째 신호) — 본문 언급만
    plain = _noise_png(120, 120)  # img_plain(문서 1번째지만 신호 없음 — 상한에 밀려야 함)
    small = _noise_png(50, 50)  # img_small — 짧은 변 50 < VLM_FIG_MIN_PX(64)

    d = Path(tempfile.mkdtemp())
    doc = _docx.Document()
    for t in ("아무 설명 없음.", "특별한 내용 없음."):
        doc.add_paragraph(t)
    doc.add_paragraph().add_run().add_picture(io.BytesIO(plain))  # i1 — img_plain
    for t in ("이어지는 설명 글.", "추가 설명 글."):
        doc.add_paragraph(t)
    doc.add_paragraph().add_run().add_picture(io.BytesIO(big))  # i2 — img_cap
    doc.add_paragraph("그림 1. 공정 개요도")  # img_cap 캡션(아래 줄)
    doc.add_paragraph("별다른 내용 없음.")
    doc.add_paragraph().add_run().add_picture(io.BytesIO(big))  # i3 — img_dup(big과 같은 바이트)
    for t in ("표 아님.", "추가 문구."):
        doc.add_paragraph(t)
    doc.add_paragraph("다음 그래프를 참고해 수율을 확인하라.")  # img_mention 본문 언급(위 줄)
    doc.add_paragraph().add_run().add_picture(io.BytesIO(mid))  # i4 — img_mention
    for t in ("끝 설명.", "마지막 문구."):
        doc.add_paragraph(t)
    doc.add_paragraph().add_run().add_picture(io.BytesIO(small))  # i5 — img_small
    doc.add_paragraph("종료.")
    path = d / "sel.docx"
    doc.save(path)
    doc_text = "서론. 본문에서 그림 1을 보면 수율 상승이 보인다. 결론."  # img_cap 캡션(그림 1) 번호로 찾는 본문 언급

    # S7c — 설정 객체만 바꿔 끼움(finally에서 되돌림). 옛 시험은 앞 selftest()가 지운 VLM_BASE_URL이 그대로 지워진 채 돌았음 — 같은 상태 유지
    _env = _senv(
        PARSE_RAW_ROOT=str(d / "store"), VLM_MODEL="test/model", VLM_BASE_URL=None, PARSE_IMAGES_ROOT=str(d / "images")
    )  # AD10은 selftest_kind()가 따로 다룸 — 이 시험은 AD9·AD21(select/cap) 전용
    try:
        for data, summary in ((big, "공정 개요"), (mid, "수율 추이")):  # P0 캐시 미리 채움 — 네트워크 호출 0
            out = raw_vlm_path(raw_root(), _model_dir("test/model"), "figjson", "v2-nothink", P_FIGJ, sha(data))
            out.parent.mkdir(parents=True, exist_ok=True)
            rec = {"kind": "그래프", "summary": summary, "text": "", "values": [], "edges": [], "table_md": ""}
            out.write_text(
                json.dumps({"text": json.dumps(rec, ensure_ascii=False), "provenance": {"model": "test/model"}}, ensure_ascii=False),
                encoding="utf-8",
            )

        _env.enter_context(_senv(VLM_FIGURES_MAX="2"))
        recs, _, _ = build_records("sel.docx", path, doc_text, "docsha123")
        assert len(recs) == 5
        by_i = {r["image_id"].rsplit("#i", 1)[1]: r for r in recs}
        assert by_i["1"]["skipped"] == "VLM_FIGURES_MAX"  # img_plain — 문서 1번째지만 신호 없어 상한에 밀림(우선순위 재배열 확인)
        assert by_i["2"]["skipped"] is None and by_i["2"]["vlm"]["summary"] == "공정 개요"
        assert by_i["3"]["skipped"] == "duplicate"  # img_dup — big과 같은 sha
        assert by_i["4"]["skipped"] is None and by_i["4"]["vlm"]["summary"] == "수율 추이"
        assert by_i["5"]["skipped"] == "small"  # img_small — 짧은 변 < 64px
        print("[selftest] AD9·AD21② 우선순위(캡션·본문 언급·면적)·작은/반복 제외 통과")

        _env.enter_context(_senv(VLM_FIGURES_MAX="10"))  # ③ 이어서 VLM — 상한을 올려 나머지만 시도
        recs2, _, _ = build_records("sel.docx", path, doc_text, "docsha123")
        by_i2 = {r["image_id"].rsplit("#i", 1)[1]: r for r in recs2}
        assert (
            by_i2["2"]["vlm"]["summary"] == "공정 개요" and by_i2["4"]["vlm"]["summary"] == "수율 추이"
        )  # 앞서 처리한 둘 — 캐시 그대로(재호출 0)
        assert by_i2["1"]["skipped"] is None and by_i2["1"]["vlm_error"]  # 상한에 걸렸던 것만 새로 시도(VLM 미설정이라 호출은 안 나감)
        print("[selftest] AD21③ 이어서 VLM — 앞서 처리한 그림 재호출 0 통과")

        # out_images= 인자(AG11 2단계 착수 조건, 10-08) — write_index에 세션 폴더를 직접 주면 PNG가 그 폴더에만
        # 쓰이고 env 쪽(images_root())은 안 건드린다.
        out_images = d / "agent_session" / "_images"
        recs4, _, _ = build_records("sel.docx", path, doc_text, "docsha123")
        rows4 = write_index("sel.docx", recs4, out_images=out_images)
        assert (out_images / "sel.docx").is_dir() and not (d / "images" / "sel.docx").exists()  # PNG도 인자 폴더에만(env 쪽엔 안 생김)
        assert any(r.get("png") for r in rows4)
        print("[selftest] out_images= 인자 — PNG가 지정 폴더에만(env 쪽 안 건드림) 통과")
    finally:
        _env.close()


def selftest_kind():
    """AD10 — classify_figure_kind() 순수 분류(모델 호출 없음) + build_records 연동(기본은 분류만 기록하고 VLM은
    그대로 호출 — engine-qa BLOCK 10-08 ②, photo는 vlm_fig 출력 상한만 낮춤)."""
    assert classify_figure_kind({"loc": {"signals": {"bars": 4, "curve_diag_arrow": 0}}}) == "chart"
    assert classify_figure_kind({"loc": {"signals": {"bars": 0, "curve_diag_arrow": 4}}}) == "flow"
    assert classify_figure_kind({"loc": {"signals": {"bars": 1, "curve_diag_arrow": 1}}}) == "other"  # 약한 신호 — 안전하게 other
    assert classify_figure_kind({"loc": {"signals": {"bars": 0, "curve_diag_arrow": 0, "box_diagram": True}}}) == "flow"  # AD13
    assert classify_figure_kind({"loc": {}, "ocr_chars": 250, "area_ratio": 0.2}) == "text_image"
    assert classify_figure_kind({"loc": {}, "ocr_chars": 0, "area_ratio": 0.1}) == "photo"
    assert (
        classify_figure_kind({"loc": {}, "ocr_chars": 100, "area_ratio": 0.1}) == "other"
    )  # 모호한 글자 수(차트·흐름도 라벨 수준, 실측 10-08) — other
    assert classify_figure_kind({"loc": {}, "area_ratio": 0.1}) == "other"  # OCR 상한 소진(chars=None) — other
    print("[selftest] AD10 classify_figure_kind — 모델 호출 없이 chart·flow·text_image·photo·other 분류 통과")

    import tempfile

    import docx as _docx
    from PIL import Image

    def _noise_png(w, h):
        buf = io.BytesIO()
        Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(buf, "PNG")
        return buf.getvalue()

    img_text, img_photo = _noise_png(200, 200), _noise_png(201, 201)
    d = Path(tempfile.mkdtemp())
    doc = _docx.Document()
    doc.add_paragraph().add_run().add_picture(io.BytesIO(img_text))  # i1 — text_image(가짜 OCR 글자 많음)
    doc.add_paragraph().add_run().add_picture(io.BytesIO(img_photo))  # i2 — photo(가짜 OCR 글자 없음)
    path = d / "kind.docx"
    doc.save(path)

    ocr_texts = {sha(img_text): "가" * 250, sha(img_photo): ""}
    fake_ocr = lambda b: ocr_texts.get(sha(b), "")  # 모델 로드 없는 가짜 crop OCR(결정적)

    _env = _senv(
        PARSE_RAW_ROOT=str(d / "store"),
        PARSE_IMAGES_ROOT=str(d / "images"),  # S7c — 설정 객체만 바꿔 끼움(finally에서 되돌림)
        VLM_MODEL=None,
        VLM_BASE_URL=None,
    )
    try:
        # text_image도 "종류만 기록"하고 VLM은 그대로 호출(engine-qa BLOCK ②)
        recs0, _, _ = build_records("kind.docx", path, "", "docsha_kind", ocr_fn=fake_ocr)
        by_i0 = {r["image_id"].rsplit("#i", 1)[1]: r for r in recs0}
        assert by_i0["1"]["provenance"]["fig_kind"] == "text_image" and by_i0["1"]["vlm_error"] and "미설정" in by_i0["1"]["vlm_error"]
        assert by_i0["2"]["provenance"]["fig_kind"] == "photo" and by_i0["2"]["vlm_error"] and "미설정" in by_i0["2"]["vlm_error"]
        print("[selftest] AD10 — text_image도 분류만 기록, VLM은 그대로 호출 통과")

        # 종류와 무관하게 기존 VLM 캐시(모델·prompt_id·그림 sha)가 그대로 재사용되는지 — photo로 분류돼도(max_tokens=300)
        # 전체 캐시(FULL_VERSION)가 있으면 호출 0으로 그 내용을 그대로 돌려준다(지시문 글자·prompt_id를 안 바꿨기 때문)
        _env.enter_context(_senv(VLM_MODEL="test/model"))
        cached = {"kind": "그래프", "summary": "캐시 요약", "text": "", "values": [], "edges": [], "table_md": ""}
        out = raw_vlm_path(raw_root(), _model_dir("test/model"), "figjson", FULL_VERSION, P_FIGJ, sha(img_photo))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"text": json.dumps(cached, ensure_ascii=False), "provenance": {"model": "test/model"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        recs2, _, _ = build_records("kind.docx", path, "", "docsha_kind", ocr_fn=fake_ocr)
        by_i2 = {r["image_id"].rsplit("#i", 1)[1]: r for r in recs2}
        assert by_i2["2"]["vlm"]["summary"] == "캐시 요약" and by_i2["2"]["vlm_error"] is None  # 캐시 재사용(호출 0)
        print("[selftest] AD10 — photo로 분류돼도(max_tokens만 다름) 기존 VLM 캐시 그대로 재사용(prompt_id 안 바뀜) 통과")

        # OCR 실패(engine-qa BLOCK ③) — crop OCR이 예외를 던져도 분류는 other로 안전하게 떨어지고 문서는 계속
        def boom_ocr(b):
            raise RuntimeError("가짜 OCR 실패")

        recs_err, _, _ = build_records("kind.docx", path, "", "docsha_kind", ocr_fn=boom_ocr)
        by_ierr = {r["image_id"].rsplit("#i", 1)[1]: r for r in recs_err}
        assert by_ierr["1"]["provenance"]["fig_kind"] == "other" and by_ierr["2"]["provenance"]["fig_kind"] == "other"
        assert by_ierr["1"]["vlm_error"] and "미설정" in by_ierr["1"]["vlm_error"]  # other → vlm_fig 그대로 호출(생략 안 됨)
        print("[selftest] AD10 — crop OCR 실패해도 kind=other로 안전하게(기존 전체 VLM 그대로) 통과")
    finally:
        _env.close()


def selftest_mt_cache():
    """engine-qa BLOCK(10-08) ① — photo(max_tokens 축소) 응답이 기본(FULL_VERSION) 캐시 키를 오염시키지 않는지:
    photo가 먼저 캐시되면 자기 `_mt` 전용 키에만 저장되고, 같은 그림의 full 호출은 그 잘린 답을 읽지 않고
    실제로 다시 묻는다. full이 먼저 캐시되면(무해) photo 호출도 그 완전한 답을 그대로 재사용한다."""
    import io
    import tempfile

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (80, 80), "green").save(buf, "PNG")
    png = buf.getvalue()

    calls = []

    def fake_complete(role, messages, **kw):
        calls.append(kw.get("max_tokens"))
        body = {"kind": "그래프", "summary": f"응답(mt={kw.get('max_tokens')})", "text": "", "values": [], "edges": [], "table_md": ""}
        return json.dumps(body, ensure_ascii=False), {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0}

    d = Path(tempfile.mkdtemp())
    _env = _senv(
        PARSE_RAW_ROOT=str(d / "store"), VLM_BASE_URL="http://127.0.0.1:0", VLM_MODEL="test/mtmodel"
    )  # S7c — 설정 객체만 바꿔 끼움
    real_complete = A.complete
    A.complete = fake_complete
    try:
        text1, prov1 = M.vlm_fig(png, max_tokens=300)  # photo 먼저 — 캐시 없음 → 실제 호출(300), _mt 전용 경로에 저장
        assert calls == [300] and "mt=300" in json.loads(text1)["summary"] and not prov1.get("cached")

        text2, prov2 = M.vlm_fig(png)  # full 호출(1500) — FULL_VERSION 캐시 없음(방금 건 _mt 전용) → 다시 물어야 함
        assert calls == [300, 1500] and "mt=1500" in json.loads(text2)["summary"] and not prov2.get("cached")  # 잘린 답 재사용 안 함

        text3, prov3 = M.vlm_fig(png, max_tokens=300)  # photo 다시 — 이제 FULL_VERSION 캐시가 있으니 그걸 재사용(무해)
        assert calls == [300, 1500] and "mt=1500" in json.loads(text3)["summary"] and prov3.get("cached")

        text4, prov4 = M.vlm_fig(png)  # full 다시 — 캐시 재사용(호출 0)
        assert calls == [300, 1500] and prov4.get("cached")
        print(
            "[selftest] AD10 — photo(max_tokens 축소) 캐시가 기본 캐시를 오염시키지 않음"
            "(별도 키, full은 _mt 캐시를 절대 안 읽고, photo는 full 캐시가 있으면 재사용) 통과"
        )
    finally:
        A.complete = real_complete
        _env.close()


def selftest_ocr_fallback():
    """OP11(10-11) — 글자 쪽 안에 박힌 그림(스캔 라벨 등)의 VLM 응답이 빈 경우(미설정·오류·빈 응답)만 같은 crop의
    OCR 글자로 채운다 · 분류(AD10) OCR이 이미 돈 그림은 fallback이 재호출 안 함(호출 수 공유 상한) ·
    OCR도 글자가 없거나 실패해도 문서는 계속 ·
    engine-qa CONCERN(10-11) ① — 의미 있는 글자 수가 문턱(기본 10) 미만인 로고·워터마크 조각은 안 씀 ·
    ② — 복구돼도 원래 VLM 실패 사유(vlm_error)는 지우지 않음."""
    import tempfile

    import docx as _docx
    from PIL import Image

    def _noise_png(w, h):
        buf = io.BytesIO()
        Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(buf, "PNG")
        return buf.getvalue()

    img = _noise_png(200, 200)
    d = Path(tempfile.mkdtemp())
    doc = _docx.Document()
    doc.add_paragraph().add_run().add_picture(io.BytesIO(img))
    path = d / "fb.docx"
    doc.save(path)

    calls = []

    def fake_ocr(b):
        calls.append(1)
        return "숨은 라벨 velorimab"

    _env = _senv(
        PARSE_RAW_ROOT=str(d / "store"), PARSE_IMAGES_ROOT=str(d / "images"), VLM_MODEL=None, VLM_BASE_URL=None
    )  # S7c — 설정 객체만 바꿔 끼움
    try:
        # AD10 분류가 이미 ocr_text를 채워 둠 → fallback은 재호출 없이 그대로 재사용
        recs, _, _ = build_records("fb.docx", path, "", "docsha_fb1", ocr_fn=fake_ocr)
        r = recs[0]
        assert len(calls) == 1  # 분류 때 1번만(fallback 재호출 없음)
        assert r["vlm"]["text"] == "숨은 라벨 velorimab"
        assert r["vlm_error"] and "미설정" in r["vlm_error"]  # engine-qa CONCERN ② — 원래 VLM 실패 사유를 안 지움
        assert r["provenance"].get("ocr_fallback") is True and r["provenance"]["model"] == "ocr:rapidocr_ko"
        print("[selftest] OP11 — VLM 빈 결과(미설정) → crop OCR(분류 때 이미 돈 결과 재사용, 재호출 없음) · vlm_error 보존 통과")

        # OCR도 글자가 없으면(진짜 로고·백지) 복구할 것이 없음 — VLM 실패 기록 그대로, 재호출도 없음(이미 분류 때 "" 확정)
        recs4, _, _ = build_records("fb.docx", path, "", "docsha_fb4", ocr_fn=lambda b: "")
        assert recs4[0]["vlm"]["text"] is None and not recs4[0]["provenance"].get("ocr_fallback")
        print("[selftest] OP11 — OCR도 글자 없음 → 복구할 것 없음(VLM 실패 기록 그대로) 통과")

        # OCR이 예외를 던져도 문서는 계속(engine-qa BLOCK ③과 같은 관례)
        def boom_ocr(b):
            raise RuntimeError("가짜 OCR 실패")

        recs5, _, _ = build_records("fb.docx", path, "", "docsha_fb5", ocr_fn=boom_ocr)
        assert recs5[0]["vlm"]["text"] is None and not recs5[0]["provenance"].get("ocr_fallback")
        print("[selftest] OP11 — OCR 실패해도 문서는 계속(VLM 실패 기록 그대로) 통과")

        # engine-qa CONCERN(10-11) ① — 로고·워터마크·짧은 머리글 조각(의미 있는 글자 10 미만)은 안 씀
        assert _meaningful_chars("# Outlook") == 7 and _meaningful_chars("OK") == 2  # 실측 — 문턱(기본 10) 미만
        recs6, _, _ = build_records("fb.docx", path, "", "docsha_fb6", ocr_fn=lambda b: "# Outlook")
        assert recs6[0]["vlm"]["text"] is None and not recs6[0]["provenance"].get("ocr_fallback")
        recs7, _, _ = build_records("fb.docx", path, "", "docsha_fb7", ocr_fn=lambda b: "OK")
        assert recs7[0]["vlm"]["text"] is None and not recs7[0]["provenance"].get("ocr_fallback")
        print("[selftest] OP11 — 의미 있는 글자 10 미만(로고·워터마크 조각)은 안 씀 통과")

        # 문턱을 낮추면(FIG_OCR_FALLBACK_MIN_CHARS) 같은 짧은 글자도 복구 — env로 조정 가능 확인
        with _senv(FIG_OCR_FALLBACK_MIN_CHARS="2"):
            recs8, _, _ = build_records("fb.docx", path, "", "docsha_fb8", ocr_fn=lambda b: "OK")
            assert recs8[0]["vlm"]["text"] == "OK" and recs8[0]["provenance"].get("ocr_fallback") is True
        print("[selftest] OP11 — FIG_OCR_FALLBACK_MIN_CHARS로 문턱 조정 가능 통과")

        # 실측 4건(velorimab·MX-W11·MX-W12 중 가장 짧은 19자·chart류)이 기본 문턱(10)을 넉넉히 넘는지 — 회귀 가드
        measured = [
            "제품 라벨 (가상) 제품명:velorimab 10 mg 로트:LOT-VLM-2601 (가상)",
            "라벨 스캔 창고 코드:MX-W12 수량:500개",
            "월별 생산량(그림,가상) 120kg 100kg 95kg 1월 2월 3월",
            "pH 안정성,충일(그림,가상) pH기춘:7.0±0.2 7.0 6.9 0개월 3개월 6개월",
        ]
        assert all(_meaningful_chars(t) >= FIG_OCR_FALLBACK_MIN_CHARS_DEFAULT for t in measured), [
            (_meaningful_chars(t), t) for t in measured
        ]
        print("[selftest] OP11 — 실측으로 되살린 값 4건이 기본 문턱(10)을 넉넉히 넘음(회귀 가드) 통과")
    finally:
        _env.close()


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
    selftest_select()
    selftest_kind()
    selftest_mt_cache()
    selftest_ocr_fallback()
