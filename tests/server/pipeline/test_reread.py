"""pipeline.transform.represent.reread 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.reread`."""

from pathlib import Path

from pipeline import config as pc
from pipeline.transform.represent.reread import eligible, locate_region, on, render_crop, reread_matches, rereview_facts


def test_main():  # 옛 `if __name__ == "__main__":` 몸통

    # on() — PARSE_FUSE_REREAD 기본 켬, =0으로 끔
    with pc.PIPE.env(PARSE_FUSE_REREAD=None):  # S7c — 설정 객체만 바꿔 끼움
        assert on() is True and on("1") is True and on("0") is False
    print("[selftest] PARSE_FUSE_REREAD on() 기본 켬(=0으로 끔) 통과")

    # eligible() — 근소한 점수차(a) · 승자가 한 계열뿐(b) · 패자 없으면·승자가 다계열이면 대상 아님
    w = {"engines": ["pdfplumber", "pymupdf", "pypdf"], "score": 9.0, "text": "430.000"}
    l_small = [{"engines": ["rapidocr_ko"], "score": 8.2, "text": "430,000"}]
    l_far = [{"engines": ["rapidocr_ko"], "score": 1.1, "text": "430,000"}]
    assert eligible(w, l_small) == (True, "small_margin")
    assert eligible(w, l_far) == (True, "single_kind_winner")  # 점수차 커도 승자가 text 계열 하나뿐이면 대상
    assert eligible(w, []) == (False, None)  # 패자 없음(안 갈림) — 대상 아님
    w_mixed = {"engines": ["pdfplumber", "qwen_vlm"], "score": 9.0, "text": "A"}
    assert eligible(w_mixed, l_far) == (False, None)  # 승자가 이미 다계열 동의 + 점수차 큼 — 대상 아님
    print("[selftest] eligible — 근소 점수차·단일 계열 승자만 대상, 다계열 동의·무갈림은 제외 통과")

    # reread_matches — 표기까지 구분(정확 매치) · 숫자 보조 비교는 유일할 때만 · 모호하면 None
    winner, losers = (
        {"text": "430.000", "engines": ["pdfplumber"], "score": 9.0},
        [{"text": "430,000", "engines": ["rapidocr_ko"], "score": 1.1}],
    )
    assert reread_matches("최종 금액: 430,000", winner, losers)["text"] == "430,000"  # 패자 쪽 확정 — 채택(뒤집음)
    assert reread_matches("최종 금액: 430.000", winner, losers)["text"] == "430.000"  # 승자 쪽 확정 — 그대로(확인)
    assert reread_matches("전혀 다른 글", winner, losers) is None  # 아무도 안 맞음 — unverified
    assert reread_matches("430000", winner, losers)["text"] == "430,000"  # 구분자 없는 재판독 — norm_key가 쉼표는
    # 지우므로("430,000"→"430000") 패자와 그대로 맞음(마침표
    # 승자는 "430.000"이라 안 맞음) — 쉼표 쪽으로 정확 매치
    amb_winner = {"text": "4,30,000", "engines": ["pdfplumber"], "score": 9.0}  # 인도식 구분(쉼표) vs 3자리 구분(쉼표) —
    amb_losers = [{"text": "430,000", "engines": ["rapidocr_ko"], "score": 1.1}]  # PARSE_TOKEN_NORM 기본 켬(AD25(a))이라
    # tokens()가 무효 묶음(4,30,000)은 그대로 두고 유효
    # 묶음(430,000)만 "430000"으로 합친다 — 둘이 더는
    # 같은 토큰이 아니라서 재판독 글("430,000"→"430000")은
    # 유효 쪽(패자)과만 유일하게 맞는다(뒤집음, 잘못된 승자 교정)
    assert reread_matches("430,000", amb_winner, amb_losers) == amb_losers[0]
    print("[selftest] reread_matches — 표기 구분 정확 매치·모호하면 None(잘못 채택 방지) 통과")

    # locate_region·render_crop·rereview_facts — 실제 합성 PDF(글자층 "430.000"만 있음) + 가짜 OCR(시간 드는
    # 모델 로드 없이 결정적으로 "크롭한 자리 주변 글자"를 흉내) → 재판독이 자리를 찾아 승자를 뒤집는지 확인
    import fitz

    tdoc = fitz.open()
    tpg = tdoc.new_page(width=400, height=200)
    tpg.insert_text((50, 50), "최종 금액: 430.000")
    import tempfile

    tpdf = Path(tempfile.mkdtemp()) / "t.pdf"
    tdoc.save(str(tpdf))
    tdoc.close()

    page, bbox = locate_region(tpdf, ["430.000", "430,000"])
    assert page == 0 and bbox is not None
    png = render_crop(tpdf, page, bbox)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG 머리말 — 렌더됨
    none_page, none_bbox = locate_region(tpdf, ["전혀 없는 값"])
    assert (none_page, none_bbox) == (0, None)  # 못 찾으면 0쪽 전체 폴백

    engine_docs = {
        "pdfplumber": {"facts": [{"context": ["금액"], "value": "430.000"}]},
        "pymupdf": {"facts": [{"context": ["금액"], "value": "430.000"}]},
        "pypdf": {"facts": [{"context": ["금액"], "value": "430.000"}]},
        "rapidocr_ko": {"facts": [{"context": ["금액"], "value": "430,000"}]},
    }
    import pipeline.transform.represent.fuse as fuse_mod

    fused = fuse_mod.fuse(engine_docs, "pdfplumber")
    assert fused["facts"][0]["value"] == "430.000"  # P1만이면 글자층 3개가 이김(엔진 수) — 틀린 값

    fake_ocr = lambda png_bytes: "최종 금액: 430,000"  # 재판독은 '보이는' OCR 값을 다시 맞힌다고 가정(모델 호출 없음)
    out = rereview_facts(engine_docs, fused, "pdfplumber", tpdf, ocr_fn=fake_ocr)
    assert out["facts"][0]["value"] == "430,000"  # 재확인되어 승자가 뒤집힘
    assert out["facts"][0]["reread"]["confirmed"] == "loser"
    assert out["reread"]["flipped"] == 1 and out["reread"]["attempted"] == 1

    fake_ocr_none = lambda png_bytes: "알아볼 수 없는 글자뭉치"
    fused2 = fuse_mod.fuse(engine_docs, "pdfplumber")
    out2 = rereview_facts(engine_docs, fused2, "pdfplumber", tpdf, ocr_fn=fake_ocr_none)
    assert out2["facts"][0]["value"] == "430.000" and out2["facts"][0]["unverified"] is True  # 못 맞음 — 지우지 않고 표시만
    assert out2["reread"]["unverified"] == 1

    # 2026-10-22 사용자 지정 — P2도 못 가릴 때 산출 정확도 높은 엔진(engine_rank) 후보 폴백
    out3 = rereview_facts(
        engine_docs,
        fuse_mod.fuse(engine_docs, "pdfplumber"),
        "pdfplumber",
        tpdf,
        ocr_fn=fake_ocr_none,
        engine_rank=["rapidocr_ko", "pymupdf"],
    )
    assert out3["facts"][0]["value"] == "430,000"  # rank 최고 엔진(rapidocr_ko)의 후보로 교체
    assert out3["facts"][0]["reread"]["fallback"] == "best_engine" and out3["facts"][0]["reread"]["was"] == "430.000"
    assert out3["reread"]["fallback_best"] == 1 and out3["reread"]["unverified"] == 0
    out4 = rereview_facts(
        engine_docs, fuse_mod.fuse(engine_docs, "pdfplumber"), "pdfplumber", tpdf, ocr_fn=fake_ocr_none, engine_rank=["pymupdf"]
    )  # 최고 엔진이 승자 쪽 — 값 유지·표시만
    assert out4["facts"][0]["value"] == "430.000" and out4["facts"][0]["reread"]["fallback"] == "best_engine"
    assert out4["reread"]["fallback_kept"] == 1 and out4["reread"]["fallback_best"] == 0
    out5 = rereview_facts(
        engine_docs, fuse_mod.fuse(engine_docs, "pdfplumber"), "pdfplumber", tpdf, ocr_fn=fake_ocr_none, engine_rank=["없는엔진"]
    )  # rank가 후보 어디에도 없으면 종래 unverified
    assert out5["facts"][0]["unverified"] is True and out5["reread"]["unverified"] == 1
    print("[selftest] reread 폴백 — P2도 못 가리면 산출 정확도 최고 엔진 후보로 교체/유지/미적용 통과")

    not_pdf = rereview_facts(engine_docs, fuse_mod.fuse(engine_docs, "pdfplumber"), "pdfplumber", None)
    assert not_pdf["reread"]["skip_reason"] == "no_pdf" and not_pdf["facts"][0]["value"] == "430.000"  # doc_path 없음 — 전부 건너뜀
    print("[selftest] locate_region·render_crop·rereview_facts — 좌표 찾기·크롭 렌더·재판독으로 승자 뒤집기/확인/미확인 통과")
