"""pipeline.transform.figures.vlm_page 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.vlm_page`."""

import contextlib
import io
import json
from pathlib import Path

import pipeline.transform.figures.vlm_page as M
from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.shared.parse_run import raw_vlm_path
from pipeline.shared.postprocess import raw_root
from pipeline.shared.vlmcall import (
    MAX_SIDE,
    P_PAGE,
    PID_PAGE,
    _model_dir,
    det_key,
    det_path,
    page_count,
    render,
    sha,
    vlm_page,
)
from pipeline.transform.figures.vlm_page import (
    PAGE_HIDDEN_AREA,
    PAGE_HIDDEN_RATIO,
    PAGE_SCAN_AREA,
    PAGE_SCAN_CHARS,
    PAGE_SIGNALS_VERSION,
    _signals_path,
    is_scan,
    page_text,
    scan_pages,
    scan_pages_detail,
)


def _selftest_scan_wide():
    """AD31(남은 것, 10-08) — rotated·vectors 이유(ocr_gt_text는 pl-34 10-30에 지움 — 옛 캐시의 ocr_chars는 안 봄): page_signals·rotation_info를 흉내 내
    결정 로직만 확인(실 PDF 렌더·OCR 불필요, 빠름 — 그 둘의 실제 계산은 위 selftest의 다른 블록이 이미 확인)."""
    orig_ps, orig_rot = M.page_signals, M.rotation_info
    try:
        sig = [  # 1쪽 보통 글자(아무 이유도 안 걸림) · 2쪽 옛 캐시의 렌더 OCR≫글자층(이제 안 걸림) · 3쪽 회전됨 · 4쪽 벡터 도형 군집 많음
            {
                "page": 1,
                "chars": 500,
                "image_area_ratio": 0.0,
                "figures": 0,
                "vectors": 0,
                "garbage_ratio": 0.0,
                "hidden_ratio": 0.0,
                "hidden_over_image": False,
                "ocr_chars": 500,
            },
            {
                "page": 2,
                "chars": 10,
                "image_area_ratio": 0.1,
                "figures": 0,
                "vectors": 0,
                "garbage_ratio": 0.0,
                "hidden_ratio": 0.0,
                "hidden_over_image": False,
                "ocr_chars": 80,
            },
            {
                "page": 3,
                "chars": 300,
                "image_area_ratio": 0.0,
                "figures": 0,
                "vectors": 0,
                "garbage_ratio": 0.0,
                "hidden_ratio": 0.0,
                "hidden_over_image": False,
                "ocr_chars": None,
            },
            {
                "page": 4,
                "chars": 300,
                "image_area_ratio": 0.0,
                "figures": 0,
                "vectors": 4,
                "garbage_ratio": 0.0,
                "hidden_ratio": 0.0,
                "hidden_over_image": False,
                "ocr_chars": None,
            },
        ]
        M.page_signals = lambda p: sig  # selftest 흉내(아래서 원래 함수로 되돌림)
        M.rotation_info = lambda p: {3: {"angle": 90, "orig_sha256": "x"}}
        got = scan_pages_detail("fake.pdf")
        assert got == {3: "rotated", 4: "vectors"}, got  # pl-34 — 옛 캐시에 ocr_chars가 남아 있어도 ocr_gt_text 없음

        with pc.PIPE.env(PARSE_ROTATED_MAX="0", PARSE_VECTORS_MAX="0"):  # 끔 — 둘 다 조건 자체를 안 봄(S7c — 설정 객체만 바꿔 끼움)
            assert scan_pages_detail("fake.pdf") == {}
    finally:
        M.page_signals, M.rotation_info = orig_ps, orig_rot
    print("[selftest] AD31(남은 것) — rotated·vectors 이유 + 상한 env=0으로 끔(바이트 동일) · 옛 ocr_chars 무시 통과")


def selftest():
    import tempfile

    # 검토자 반영(10-08) — 이 selftest는 모델·네트워크를 안 써야 하는데(VLM_BASE_URL·VLM_MODEL을 지우는 것만으로
    # vlm_page()가 조용히 "미설정" 경로로 빠지게 짜여 있음), 혹시 이 프로세스에 그 두 값이 다시 생기는 경로가
    # 있어도(다른 코드·환경 상속 등) 오래 붙잡히지 않게 짧은 VLM_TIMEOUT(접속을 시도하면 몇 분이 아니라 몇 초 안에 실패)을 둔다
    # (옛 NO_PAID_CALLS 겹은 11-03에 스위치와 함께 지움) — 끝나면 원래 값으로 되돌린다.
    # S7c — 설정 객체만 바꿔 끼움(os.environ 안 건드림): VLM_BASE_URL·VLM_MODEL·VLM_TIMEOUT 모두 common 칸
    _top = contextlib.ExitStack()
    _top.enter_context(COMMON.env(VLM_BASE_URL=None, VLM_MODEL=None, VLM_TIMEOUT="5"))
    try:
        d = Path(tempfile.mkdtemp())
        assert not is_scan(d / "x.docx") and not is_scan(d / "x.xlsx")
        from PIL import Image

        img = d / "scan.png"
        Image.new("RGB", (80, 80), "white").save(img)
        assert is_scan(img)
        assert page_count(img) == 1 and render(img, [1]) == [img.read_bytes()]
        text, prov = vlm_page(img.read_bytes())
        assert text == "" and "미설정" in prov["error"]
        with pc.PIPE.env(VLM_PAGE_MAX="0"):
            assert page_text(img) == ("", [])  # 꺼짐 — is_scan조차 안 부름(호출 0 보장)
        t, provs = page_text(img)  # VLM 미설정 — 빈 글자(파싱은 계속), provenance는 오류로 남음
        assert t == "" and len(provs) == 1 and provs[0].get("error")
        assert PID_PAGE.startswith("page-v1-")
        print("[selftest] 스캔 판정·쪽 렌더·VLM_PAGE_MAX 끔·VLM 미설정 안전 경로 통과")

        # rotation.csv → {쪽: angle·orig_sha256}
        (d / "rotation.csv").write_text("file,page,angle,orig_sha256,s0,s90,s180,s270\nscan.png,1,90,deadbeef,1,2,3,4\n", encoding="utf-8")
        rot = M.rotation_info(img)
        assert rot == {1: {"angle": 90, "orig_sha256": "deadbeef"}}
        assert M.rotation_info(d / "없음.png") == {}

        store = d / "store"
        _e1 = contextlib.ExitStack()
        _e1.enter_context(pc.PIPE.env(PARSE_RAW_ROOT=str(store)))
        _e1.enter_context(COMMON.env(VLM_MODEL="test/model"))
        try:
            det = {"source_sha256": "deadbeef", "page": 1, "rotation_deg": 90, "is_pdf": False}
            # 결정적 캐시를 먼저 손으로 만들고(이전 호출이 저장해 둔 것처럼) — 렌더 바이트가 달라도(예: 재준비로 PNG가 달라짐) 맞아야 함
            k16 = det_key("deadbeef", 1, None, MAX_SIDE, 90, "test/model", PID_PAGE)
            dp = det_path(raw_root(), _model_dir("test/model"), "page", "v1", P_PAGE, k16)
            dp.parent.mkdir(parents=True, exist_ok=True)
            dp.write_text(
                json.dumps({"text": "결정적 캐시 글자", "provenance": {"model": "test/model"}}, ensure_ascii=False), encoding="utf-8"
            )
            text2, prov2 = vlm_page(b"\x89PNG-RENDER-A", det)  # 렌더 바이트 A
            text3, prov3 = vlm_page(b"\x89PNG-RENDER-B-DIFFERENT", det)  # 렌더 바이트 B(다름) — 그래도 같은 det → 같은 캐시
            assert text2 == text3 == "결정적 캐시 글자" and prov2["cached"] and prov3["cached"] and prov2["via"] == prov3["via"] == "det"

            # 대체 경로: 결정적 캐시가 없고 렌더 sha(legacy) 캐시만 있으면 그걸 읽고, 결정적 열쇠로도 승격해 남김
            legacy_bytes = b"legacy-render-bytes"
            legacy = raw_vlm_path(raw_root(), _model_dir("test/model"), "page", "v1", P_PAGE, sha(legacy_bytes))
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(
                json.dumps({"text": "예전 캐시 글자", "provenance": {"model": "test/model"}}, ensure_ascii=False), encoding="utf-8"
            )
            det2 = {"source_sha256": "other-source", "page": 1, "rotation_deg": 0, "is_pdf": False}
            text4, prov4 = vlm_page(legacy_bytes, det2)
            assert text4 == "예전 캐시 글자" and prov4["via"] == "legacy_image_sha"
            k16b = det_key("other-source", 1, None, MAX_SIDE, 0, "test/model", PID_PAGE)
            dp2 = det_path(raw_root(), _model_dir("test/model"), "page", "v1", P_PAGE, k16b)
            assert dp2.exists()  # 승격 확인 — 다음부터는 렌더 sha 없이도 찾음
            text5, prov5 = vlm_page(b"\x89PNG-COMPLETELY-DIFFERENT", det2)
            assert text5 == "예전 캐시 글자" and prov5["via"] == "det"
        finally:
            _e1.close()
        print("[selftest] 결정적 P0 열쇠 — 렌더 바이트 달라도 캐시 재사용 · 렌더 sha 대체 경로 → 승격 통과")

        # AD12·AD46 — 글자 PDF 안의 스캔 쪽만 쪽 VLM(문서 전체는 스캔 아님). 합성 혼합 PDF: 1·3쪽 글자, 2쪽만 쪽 전체 이미지(스캔).
        import fitz

        mixed = d / "mixed.pdf"
        mdoc = fitz.open()
        mdoc.new_page(width=400, height=600).insert_text((50, 50), "본문 글자가 충분히 있는 쪽 " * 5)
        buf = io.BytesIO()
        Image.new("RGB", (400, 600), "gray").save(buf, "PNG")
        mdoc.new_page(width=400, height=600).insert_image(fitz.Rect(0, 0, 400, 600), stream=buf.getvalue())
        mdoc.new_page(width=400, height=600).insert_text((50, 50), "마지막 쪽도 글자가 있다 " * 5)
        mdoc.save(mixed)
        mdoc.close()

        store2 = d / "store2"
        _e1 = pc.PIPE.env(PARSE_RAW_ROOT=str(store2))
        _e1.__enter__()
        try:
            sig = M.page_signals(mixed)
            assert [r["page"] for r in sig] == [1, 2, 3], sig
            assert sig[0]["chars"] >= PAGE_SCAN_CHARS and sig[0]["image_area_ratio"] == 0.0
            assert sig[1]["chars"] < PAGE_SCAN_CHARS and sig[1]["image_area_ratio"] >= PAGE_SCAN_AREA, sig[1]  # 2쪽 = 스캔 신호
            assert sig[2]["chars"] >= PAGE_SCAN_CHARS
            assert all("ocr_chars" not in r for r in sig)  # 렌더 OCR 신호는 pl-34에 지움
            assert _signals_path(sha(mixed.read_bytes())).exists()  # 한 번 계산해 캐시 — D2·D4·D6이 다시 읽음
            assert scan_pages(mixed) == [2]
            assert not is_scan(mixed)  # 문서 전체는 스캔 아님(1·3쪽 글자 있음, 기존 is_scan 그대로)

            t2, provs2 = page_text(mixed)  # AD31 — 기본 켬: 2쪽(스캔 쪽)만 대상 — 1·3쪽은 안 부름
            assert t2 == "" and len(provs2) == 1 and provs2[0].get("error"), (t2, provs2)
        finally:
            _e1.__exit__(None, None, None)
        print("[selftest] AD12·AD31 — page_signals·scan_pages·스캔 쪽만 쪽 VLM 대상 통과")

        # AD31 — 숨은 글자층(render_mode=3) 쪽: 시각은 정상 그림인데 그림과 무관한 보이지 않는 글자가 깔려 글자 수는
        # 차 있음(기존 ①chars<20 조건만으로는 스캔으로 못 잡음) → hidden_ratio 신호로 스캔 판정. 정상 글자 쪽은 그대로 아님.
        hidden_doc = d / "hidden.pdf"
        hdoc = fitz.open()
        hdoc.new_page(width=400, height=600).insert_text((50, 50), "정상 글자 쪽 " * 10)  # 1쪽 — 글자만, 스캔 아님
        pg2 = hdoc.new_page(width=400, height=600)
        buf2 = io.BytesIO()
        Image.new("RGB", (400, 600), "gray").save(buf2, "PNG")
        pg2.insert_image(fitz.Rect(0, 0, 400, 600), stream=buf2.getvalue())
        pg2.insert_text((50, 50), "그림과 무관한 숨은 글자 " * 10, render_mode=3)  # 2쪽 — 보이지 않는 글자층
        hdoc.save(hidden_doc)
        hdoc.close()

        store3 = d / "store3"
        _e1 = pc.PIPE.env(PARSE_RAW_ROOT=str(store3))
        _e1.__enter__()
        try:
            sig = M.page_signals(hidden_doc)
            assert sig[0]["chars"] >= PAGE_SCAN_CHARS and sig[0]["hidden_ratio"] == 0.0  # 1쪽 — 보통 글자, 숨은 글자 없음
            assert sig[1]["chars"] >= PAGE_SCAN_CHARS  # 2쪽 — 글자 수는 차 있음(①만으로는 못 잡음)
            assert sig[1]["hidden_ratio"] >= PAGE_HIDDEN_RATIO and sig[1]["image_area_ratio"] >= PAGE_HIDDEN_AREA, sig[1]
            assert scan_pages(hidden_doc) == [2]  # 숨은 글자층 신호로 2쪽만 스캔
            assert scan_pages_detail(hidden_doc) == {2: "hidden"}  # 이유도 남김(쪽 → 'chars'/'hidden'/'garbage')
        finally:
            _e1.__exit__(None, None, None)
        print("[selftest] AD31 — 숨은 글자층(render_mode=3) 쪽 → scan_pages 판정·정상 글자 쪽은 아님 통과")

        # 독립 검토 MAJOR(10-07) — '검색 가능 스캔 PDF'(이미지 위에 그 이미지와 같은 내용을 옮긴 양질의 render_mode=3
        # OCR 글자층)도 hidden_ratio·image_area_ratio가 똑같이 높아 조건②에 걸린다. 지금 동작은 **그대로 둠**(일부러
        # 보수적 — OCR 후보가 다시 돌아도 손해 없음) 대신 reason='hidden'을 남겨 다음 단계(represent.py, b2 범위)가
        # '숨은 층이 OCR과 일치하면 원래 글 유지'를 그 이유로 구분할 수 있게 한다.
        searchable = d / "searchable_scan.pdf"
        ssdoc = fitz.open()
        spg = ssdoc.new_page(width=400, height=600)
        buf4 = io.BytesIO()
        Image.new("RGB", (400, 600), "gray").save(buf4, "PNG")
        spg.insert_image(fitz.Rect(0, 0, 400, 600), stream=buf4.getvalue())
        spg.insert_text((50, 50), "이미지와 같은 내용을 옮긴 양질의 OCR 글자층 " * 10, render_mode=3)  # "검색 가능" PDF의 숨은 글자층
        ssdoc.save(searchable)
        ssdoc.close()
        with pc.PIPE.env(PARSE_RAW_ROOT=str(d / "store4")):  # S7c — 설정 객체만 바꿔 끼움
            assert scan_pages_detail(searchable) == {1: "hidden"}, scan_pages_detail(
                searchable
            )  # 지금 동작 명시(한계, 후속은 represent.py)
        print("[selftest] 독립 검토 MAJOR — 검색 가능 스캔 PDF(양질 OCR 숨은 층)도 reason='hidden'으로 잡힘(지금 동작) 통과")

        # AD47 — synth-mixedpdf textlayer_mismatch.pdf와 같은 모양: 쪽 대부분은 정상 글자(hidden_ratio·image_area_ratio
        # 둘 다 낮음)인데 값 하나만 그림 위에 숨은 글자(틀린 값)로 깔림 — 'chars'·'hidden'(쪽 전체 비율) 둘 다 못 잡고
        # hidden_over_image(국소 겹침)만 잡아야 한다.
        mismatch_doc = d / "mismatch.pdf"
        mdoc2 = fitz.open()
        mpg = mdoc2.new_page(width=595, height=842)
        mpg.insert_text((50, 50), "분기 정산 메모 " * 8)  # 정상 글자 — 충분히 많음(chars 조건 안 걸림)
        buf5 = io.BytesIO()
        Image.new("RGB", (333, 50), "white").save(buf5, "PNG")
        mpg.insert_image(fitz.Rect(100, 110, 433, 160), stream=buf5.getvalue())  # 그림(쪽 면적의 일부만 — image_area_ratio 낮음)
        mpg.insert_text((110, 140), "430.000", render_mode=3)  # 그림과 겹치는 숨은(틀린) 값 하나만
        mdoc2.save(mismatch_doc)
        mdoc2.close()

        _e1 = pc.PIPE.env(PARSE_RAW_ROOT=str(d / "store5"))
        _e1.__enter__()
        try:
            sig = M.page_signals(mismatch_doc)
            assert sig[0]["chars"] >= PAGE_SCAN_CHARS  # 'chars' 조건 안 걸림
            assert sig[0]["hidden_ratio"] < PAGE_HIDDEN_RATIO and sig[0]["image_area_ratio"] < PAGE_HIDDEN_AREA  # 쪽 전체 비율로는 못 잡음
            assert sig[0]["hidden_over_image"] is True, sig[0]  # 국소 겹침만 잡음
            assert scan_pages_detail(mismatch_doc) == {1: "hidden_overlap"}
            assert scan_pages(mismatch_doc) == [1]  # 쪽 VLM 대상(page_targets)이 그대로 재사용
            with pc.PIPE.env(PARSE_HIDDEN_OVERLAP_MAX="0"):  # 끔 — 이전과 바이트 동일(이 조건 자체를 안 봄)
                assert scan_pages_detail(mismatch_doc) == {}
        finally:
            _e1.__exit__(None, None, None)
        print(
            "[selftest] AD47 — 쪽 전체 비율로는 못 잡는 국소 숨은 글자-그림 겹침 → scan_pages_detail reason='hidden_overlap' · PARSE_HIDDEN_OVERLAP_MAX=0으로 끔 통과"
        )

        _selftest_scan_wide()

    finally:
        _top.close()  # 맨 위에서 켠 안전장치(설정 객체 덮기) 되돌림(VS7c2 R-6 — 실패해도)
    assert (
        PAGE_SIGNALS_VERSION == "v3"
    )  # 캐시 버전 — 판정 바뀜(AD31·AD47, 이유 추가는 버전 영향 없음) · 10-08 세 새 이유는 기존 필드만 다시 읽어 버전 영향 없음


def test_pick_pages():
    """10-29 — 쪽 VLM 대상 쪽(순수 함수): 전체 스캔이면 전부, 글자 PDF면 스캔 신호 쪽만, cap으로 앞에서 자름."""
    from pipeline.transform.figures.vlm_page import pick_pages

    assert pick_pages(3, True, [], None) == {1, 2, 3}
    assert pick_pages(3, True, [], 2) == {1, 2}
    assert pick_pages(0, False, [2, 5], None) == {2, 5}
    assert pick_pages(0, False, [5, 2, 7], 2) == {5, 2}  # 신호 순서대로 자름
    assert pick_pages(0, False, [], None) == set()  # 스캔 쪽 없음 — 쪽 VLM 호출 없음


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
