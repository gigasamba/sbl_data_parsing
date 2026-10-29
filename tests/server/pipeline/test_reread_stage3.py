"""pipeline.transform.represent.reread_stage3 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.represent.reread_stage3`."""

import hashlib
import json
from pathlib import Path

from common.config import settings as C
from pipeline import config as pc
from pipeline.transform.represent.reread_stage3 import (
    _VLM_CACHE_DIR,
    _other_pages_with_images,
    _parse_answer,
    _vlm_cache_path,
    nearby_page_images,
    on,
    p3_once,
    rereview_facts_p3,
    vlm_choose,
)


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    import tempfile
    import uuid

    # on() — PARSE_FUSE_REREAD_P3 기본 켬, =0으로 끔
    with pc.PIPE.env(PARSE_FUSE_REREAD_P3=None):  # S7c — 설정 객체만 바꿔 끼움
        assert on() is True and on("1") is True and on("0") is False
    print("[selftest] PARSE_FUSE_REREAD_P3 on() 기본 켬(=0으로 끔) 통과")

    # _parse_answer — 코드펜스·군더더기 있어도 answer만
    assert _parse_answer('```json\n{"answer": "430,000"}\n```') == "430,000"
    assert _parse_answer('설명: {"answer": "NONE"} 끝') == "NONE"
    assert _parse_answer("깨진 글") == ""
    print("[selftest] _parse_answer — JSON 글 밖 군더더기 있어도 answer 추출 통과")

    # nearby_page_images·vlm_choose·p3_once — 합성 PDF(글자층엔 틀린 값만, 그림 두 장에 각각 다른 참값)
    import fitz

    tdoc = fitz.open()
    tpg = tdoc.new_page(width=500, height=400)
    tpg.insert_text((50, 50), "최종 금액: 430.000")  # 글자층 — 일부러 틀린 표기(마침표)
    import io

    from PIL import Image

    def _mkpng(w, h, color):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), color).save(buf, "PNG")
        return buf.getvalue()

    img_far = _mkpng(60, 60, "red")  # 줄에서 먼 그림(값과 무관한 그림 — 가까운 그림이 먼저 와야 함)
    img_near = _mkpng(60, 60, "blue")  # 줄 바로 옆 그림(실제론 OCR 안 됨 — 단색이라 글자 없음, 매칭 테스트용 fake ocr_fn만 씀)
    tpg.insert_image(fitz.Rect(300, 45, 360, 105), stream=img_near)  # 글자(y 40~65)와 겹치는 가까운 그림
    tpg.insert_image(fitz.Rect(300, 250, 360, 310), stream=img_far)  # 먼 그림
    tmpd = Path(tempfile.mkdtemp())
    tpdf = tmpd / "t.pdf"
    tdoc.save(str(tpdf))
    tdoc.close()

    imgs = nearby_page_images(tpdf, 0, [50, 40, 230, 65], max_n=2)
    assert len(imgs) == 2
    assert imgs[0][0] == [300.0, 45.0, 360.0, 105.0]  # 가까운(겹치는) 그림이 먼저
    assert imgs[1][0] == [300.0, 250.0, 360.0, 310.0]
    print("[selftest] nearby_page_images — bbox에 가까운 그림부터(결정적) 통과")

    bbox_none_imgs = nearby_page_images(tpdf, 0, None, max_n=1)  # bbox 없음 — 가장 큰 그림부터(둘 다 60x60 동률 → xref 순)
    assert len(bbox_none_imgs) == 1
    print("[selftest] nearby_page_images — bbox 없으면 가장 큰 그림부터 폴백 통과")

    winner = {"text": "430.000", "engines": ["pdfplumber"], "score": 9.0, "losers": []}
    losers = [{"text": "430,000", "engines": ["rapidocr_ko"], "score": 1.1}]

    # p3_once — ① 그림 OCR(가짜 ocr_fn으로 '가까운 그림'만 패자 값을 흉내)
    fake_ocr = lambda png: "430,000" if png == imgs[0][1] else "알아볼 수 없음"
    out1 = p3_once(tpdf, 1, [50, 40, 230, 65], winner, losers, ocr_fn=fake_ocr, vlm_allowed=True)
    assert out1["img_matched"] is True and out1["img_match"]["text"] == "430,000" and out1["vlm_called"] is False
    print("[selftest] p3_once — ① 그림 경계 OCR로 맞으면 VLM 호출 0(모델 호출 절약) 통과")

    # p3_once — ①b AD29 스캔 쪽 함정(judge-conflicts mixedpdf-*, 2026-10-08): P2가 짚은 쪽(1쪽)엔 그림이 하나도
    # 없고(= 그 쪽은 이 조각의 출처가 아니라는 신호) 실제 값은 **다른** 쪽(2쪽)의 그림 안에만 있을 때 — 그 다른
    # 쪽까지 쪽 순서로 돌아 찾는다(그림이 있는 쪽만, 결정적). out["page"]가 P2의 1쪽이 아니라 실제로 맞은 2쪽으로
    # 바뀌는 것까지 확인(호출부 `_apply_p3_match`가 이 page로 기록 — 더는 rr["page"]로 덮어쓰지 않음).
    tdoc2 = fitz.open()
    tdoc2.new_page(width=400, height=200).insert_text((50, 50), "엉뚱한 쪽 — 그림 없음")  # 1쪽(트랩, 그림 없음)
    tpg2 = tdoc2.new_page(width=400, height=200)
    tpg2.insert_image(fitz.Rect(100, 50, 160, 110), stream=_mkpng(60, 60, "green"))  # 2쪽(실제 값이 있는 그림)
    tmpd2 = Path(tempfile.mkdtemp())
    tpdf2 = tmpd2 / "t2.pdf"
    tdoc2.save(str(tpdf2))
    tdoc2.close()

    assert _other_pages_with_images(tpdf2, 0) == [1]  # 1쪽(스킵) 말고 그림 있는 쪽만(0-base)
    winner2 = {"text": "430.000", "engines": ["pdfplumber"], "score": 9.0}
    losers2 = [{"text": "640,000", "engines": ["rapidocr_ko"], "score": 1.0}]
    out1b = p3_once(tpdf2, 1, None, winner2, losers2, ocr_fn=lambda png: "640,000", vlm_allowed=True)
    assert out1b["img_matched"] is True and out1b["img_match"]["text"] == "640,000" and out1b["page"] == 2
    print(
        "[selftest] p3_once — ①b AD29 스캔 쪽 함정: P2가 짚은 쪽에 그림이 없으면 그림 있는 다른 쪽까지 돌아 찾고 page도 그 쪽으로 보정 통과"
    )

    # p3_once — ①이 못 맞추면(가짜 ocr_fn이 전부 모름) ②로 넘어가 VLM(가짜 vlm_fn)이 고름
    fake_ocr_none = lambda png: "알아볼 수 없음"
    fake_vlm = lambda png, cands: json.dumps({"answer": "430,000"}, ensure_ascii=False)
    out2 = p3_once(tpdf, 1, [50, 40, 230, 65], winner, losers, ocr_fn=fake_ocr_none, vlm_fn=fake_vlm, vlm_allowed=True)
    assert out2["img_matched"] is False and out2["vlm_called"] is True and out2["vlm_matched"] is True
    assert out2["vlm_match"]["text"] == "430,000"
    print("[selftest] p3_once — ①도 못 맞으면 ②VLM 선택형으로 넘어가 후보 중 고름 통과")

    # p3_once — vlm_allowed=False(상한 소진)면 VLM 호출 안 함, unverified 유지
    out3 = p3_once(tpdf, 1, [50, 40, 230, 65], winner, losers, ocr_fn=fake_ocr_none, vlm_fn=fake_vlm, vlm_allowed=False)
    assert out3["img_matched"] is False and out3["vlm_called"] is False
    print("[selftest] p3_once — VLM 상한 소진(vlm_allowed=False)이면 호출 안 하고 미확인 유지 통과")

    # VLM이 NONE·후보 밖 답을 주면 unverified 유지(값을 지어내지 않음) — 캐시 열쇠(크롭 sha·후보)가 out2와 같으므로
    # 매번 캐시 폴더를 비워 실제로 다른 vlm_fn이 불리는지 본다(캐시 자체는 바로 아래 블록에서 따로 검증).
    import shutil

    losers_b = [{"text": "6,30,000", "engines": ["rapidocr_ko"], "score": 1.1}]  # out2와 다른 후보 글 — 캐시 열쇠를 다르게
    fake_vlm_none = lambda png, cands: json.dumps({"answer": "NONE"}, ensure_ascii=False)
    out4 = p3_once(tpdf, 1, [50, 40, 230, 65], winner, losers_b, ocr_fn=fake_ocr_none, vlm_fn=fake_vlm_none, vlm_allowed=True)
    assert out4["vlm_called"] is True and out4["vlm_matched"] is False and out4["vlm_match"] is None
    losers_c = [{"text": "9,30,000", "engines": ["rapidocr_ko"], "score": 1.1}]  # 또 다른 후보 글 — 캐시 열쇠 또 다르게
    fake_vlm_outside = lambda png, cands: json.dumps({"answer": "엉뚱한 값"}, ensure_ascii=False)
    out5 = p3_once(tpdf, 1, [50, 40, 230, 65], winner, losers_c, ocr_fn=fake_ocr_none, vlm_fn=fake_vlm_outside, vlm_allowed=True)
    assert out5["vlm_matched"] is False and out5["vlm_match"] is None  # 후보 밖 답 — 못 맞은 것으로 처리
    shutil.rmtree(_VLM_CACHE_DIR, ignore_errors=True)  # 다음 블록(vlm_choose 캐시 전용 검증)이 깨끗한 폴더에서 시작하게
    print("[selftest] p3_once — VLM NONE·후보 밖 답은 둘 다 미확인(값 지어내지 않음) 통과")

    # vlm_choose — 캐시(크롭 sha·후보 같으면 vlm_fn 재호출 0)
    calls = {"n": 0}

    def _counting_vlm(png, cands):
        calls["n"] += 1
        return json.dumps({"answer": cands[0]}, ensure_ascii=False)

    uniq_png = _mkpng(10, 10, (uuid.uuid4().int % 255, 1, 1))
    cand_pair = [{"text": "A"}, {"text": "B"}]
    with pc.PIPE.env(
        PARSE_RAW_ROOT=str(tmpd / "unused")
    ):  # 이 모듈은 PARSE_RAW_ROOT를 안 쓰지만 다른 테스트와 격리 — S7c: 객체만 바꿔 끼움
        r1 = vlm_choose(uniq_png, cand_pair, vlm_fn=_counting_vlm)
        r2 = vlm_choose(uniq_png, cand_pair, vlm_fn=_counting_vlm)
    assert r1 == r2 == {"text": "A"} and calls["n"] == 1  # 두 번째는 캐시(파일)로 재호출 0
    print("[selftest] vlm_choose — (크롭 sha·후보) 캐시로 같은 자리 재호출 0 통과")

    # vlm_choose — 버그 수정: 미설정(_default_vlm_call이 None)은 캐시에 쓰지 않는다. 나중에 VLM을 설정해도
    # (가짜 vlm_fn으로 흉내) 캐시가 없으니 실제로 물어야 한다 — 예전엔 빈 답("")을 캐시해 영영 다시 안 물었다.
    uniq_png2 = _mkpng(11, 11, (uuid.uuid4().int % 255, 2, 2))
    cache_path2 = _vlm_cache_path(hashlib.sha256(uniq_png2).hexdigest(), ["A", "B"])
    with C.COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None):  # S7c — 설정 객체만 바꿔 끼움(_default_vlm_call이 객체로 읽음)
        r_unconf = vlm_choose(uniq_png2, cand_pair)  # vlm_fn 생략 → 기본 _default_vlm_call, VLM_BASE_URL·VLM_MODEL 미설정
    assert r_unconf is None and not cache_path2.exists()  # 미설정 결과는 캐시 파일 자체가 생기지 않는다
    calls2 = {"n": 0}

    def _counting_vlm2(png, cands):
        calls2["n"] += 1
        return json.dumps({"answer": cands[1]}, ensure_ascii=False)

    r_now = vlm_choose(uniq_png2, cand_pair, vlm_fn=_counting_vlm2)  # "VLM 설정 뒤" 흉내 — 캐시가 없었으니 실제로 물어야 함
    assert r_now == {"text": "B"} and calls2["n"] == 1 and cache_path2.exists()
    print("[selftest] vlm_choose — 미설정 결과는 캐시하지 않음(나중에 VLM 설정하면 다시 물음, 버그 수정) 통과")

    # rereview_facts_p3 — P2가 unverified로 남긴 자리만, engine_docs로 후보를 다시 구해 맞춘다(모델 호출 0 — 가짜 ocr_fn)
    engine_docs = {
        "pdfplumber": {"facts": [{"context": ["금액"], "value": "430.000"}]},
        "pymupdf": {"facts": [{"context": ["금액"], "value": "430.000"}]},
        "rapidocr_ko": {"facts": [{"context": ["금액"], "value": "430,000"}]},
    }
    fused = {
        "facts": [
            {
                "context": ["금액"],
                "value": "430.000",
                "engines": ["pdfplumber", "pymupdf"],
                "score": 6.0,
                "unverified": True,
                "reread": {"page": 1, "bbox": [50, 40, 230, 65], "text": "모름", "matched": False},
            }
        ],
        "conflicts": [
            {
                "label": "금액",
                "winner": "430.000",
                "winner_engines": ["pdfplumber", "pymupdf"],
                "losers": [{"engines": ["rapidocr_ko"], "text": "430,000", "score": 1.1}],
            }
        ],
    }
    out_doc = rereview_facts_p3(engine_docs, fused, "pdfplumber", tpdf, ocr_fn=fake_ocr, max_vlm=2)
    assert out_doc["facts"][0]["value"] == "430,000" and out_doc["facts"][0]["unverified"] is False
    assert out_doc["facts"][0]["reread"]["p3"]["method"] == "image_ocr" and out_doc["facts"][0]["reread"]["p3"]["confirmed"] == "loser"
    assert out_doc["conflicts"][0]["winner"] == "430,000"
    assert out_doc["reread"]["p3"]["image_ocr_matched"] == 1 and out_doc["reread"]["p3"]["vlm_calls"] == 0
    print("[selftest] rereview_facts_p3 — P2 미확인 자리를 그림 경계 OCR로 뒤집고 conflicts도 맞바꿈(AD19 확인되면 채택) 통과")

    # 확인만(값이 이미 맞던 자리) — confirmed="winner", value 안 바뀜
    fused_conf = {
        "facts": [
            {
                "context": ["금액"],
                "value": "430,000",
                "engines": ["rapidocr_ko"],
                "score": 1.1,
                "unverified": True,
                "reread": {"page": 1, "bbox": [50, 40, 230, 65], "matched": False},
            }
        ],
        "conflicts": [],
    }
    engine_docs_conf = {
        "rapidocr_ko": {"facts": [{"context": ["금액"], "value": "430,000"}]},
        "pdfplumber": {"facts": [{"context": ["금액"], "value": "430.000"}]},
    }
    fake_ocr_conf = lambda png: "430,000"
    out_conf = rereview_facts_p3(engine_docs_conf, fused_conf, "rapidocr_ko", tpdf, ocr_fn=fake_ocr_conf, max_vlm=2)
    assert out_conf["facts"][0]["unverified"] is False and out_conf["facts"][0]["reread"]["p3"]["confirmed"] == "winner"
    print("[selftest] rereview_facts_p3 — 그림 OCR이 이미 맞던 값을 재확인하면 confirmed=winner(값 안 바뀜) 통과")

    # doc_path가 PDF 아님/없음 — 전부 건너뜀(P2와 같은 전제)
    skip = rereview_facts_p3(engine_docs, {"facts": [], "conflicts": []}, "pdfplumber", None)
    assert skip["reread"]["p3"]["skip_reason"] == "no_pdf"
    print("[selftest] rereview_facts_p3 — doc_path 없음(PDF 아님) — 전부 건너뛰고 이유만 기록 통과")
