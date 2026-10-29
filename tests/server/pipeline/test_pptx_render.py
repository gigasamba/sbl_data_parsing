"""pipeline.transform.figures.pptx_render 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.transform.figures.pptx_render`."""

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

import pipeline.transform.figures.pptx_render as M
from common.config.settings import COMMON
from pipeline import config as pc
from pipeline.transform.figures import shape_detect
from pipeline.transform.figures.pptx_render import _soffice_warned, pptx_slide_vlm, render_slides, shape_render_pages, target_slides


def selftest():
    import tempfile

    import fitz
    from pptx import Presentation
    from pptx.util import Inches

    from tests.server.pipeline.test_pptx_edges import _add_smartart

    with pc.PIPE.env(PARSE_PPTX_SLIDE_VLM="0"):  # S7c — 설정 객체만 바꿔 끼움
        assert pptx_slide_vlm("whatever.pptx") == []
    assert pptx_slide_vlm("x.docx") == []
    print("[selftest] PARSE_PPTX_SLIDE_VLM=0·pptx 아님 — 둘 다 즉시 빈 목록 통과")

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[6])  # 1쪽 — 도형 5개, 연결선 없음(shapes_no_connector)
    for i in range(5):
        box = s1.shapes.add_shape(1, Inches(i), Inches(1), Inches(0.8), Inches(0.8))
        box.text_frame.text = f"단계{i}"
    s2 = prs.slides.add_slide(prs.slide_layouts[6])  # 2쪽 — SmartArt
    _add_smartart(s2)
    s3 = prs.slides.add_slide(prs.slide_layouts[6])  # 3쪽 — 일반 슬라이드(후보 아님)
    s3.shapes.add_textbox(Inches(1), Inches(1), Inches(2), Inches(1)).text_frame.text = "본문"
    d = Path(tempfile.mkdtemp())
    pptx_path = d / "wide.pptx"
    prs.save(pptx_path)

    orig_soffice_bin = M.soffice_bin
    M.soffice_bin = lambda: None
    try:
        assert pptx_slide_vlm(pptx_path) == []  # 후보(1·2쪽) 있어도 soffice 없음 — 빈 목록
        assert target_slides(pptx_path) == set()  # AD20 후속 — soffice 없으면 빈 집합(figures()가 그림을 건너뛰지 않게)
    finally:
        M.soffice_bin = orig_soffice_bin
    print("[selftest] soffice 없음 — 후보 있어도 빈 목록(이전과 바이트 동일), 진단 1줄만(stderr) 통과")

    def _fake_convert(pptx_path_, out_dir, timeout):  # 실제 LibreOffice 없이 변환 결과만 흉내(3쪽짜리 빈 pdf)
        fd = fitz.open()
        for _ in range(3):
            fd.new_page(width=400, height=300)
        out = Path(out_dir) / (Path(pptx_path_).stem + ".pdf")
        fd.save(out)
        fd.close()
        return out

    store = d / "store"
    _env = contextlib.ExitStack()  # S7c — 설정 객체만 바꿔 끼움(os.environ 안 건드림), finally에서 닫음
    _env.enter_context(pc.PIPE.env(PARSE_RAW_ROOT=str(store)))
    _env.enter_context(COMMON.env(VLM_MODEL="test/model"))
    orig_convert, orig_soffice2, orig_vlm = M._convert_to_pdf, M.soffice_bin, M.vlm_page
    M._convert_to_pdf = _fake_convert
    M.soffice_bin = lambda: "fake-soffice"
    M.vlm_page = lambda img, det=None: ("가짜 VLM 전사", {"cached": False})
    try:
        got = pptx_slide_vlm(pptx_path)
        assert [n for n, _, _pv in got] == [1, 2], got  # 3쪽(후보 아님)은 호출 안 됨
        assert all(t == "가짜 VLM 전사" for _, t, _pv in got)
        assert got[0][2]["reason"] == "shapes_no_connector" and got[1][2]["reason"] == "smartart", got
        assert target_slides(pptx_path) == {1, 2}  # AD20 후속 — pptx_slide_vlm이 실제로 부른 슬라이드와 같은 집합

        with pc.PIPE.env(PARSE_PPTX_RENDER_MAX="1"):
            assert target_slides(pptx_path) == {1}  # 상한 1 — figures.py 중복 방지도 1쪽만 봄
            got2 = pptx_slide_vlm(pptx_path)
            assert [n for n, _, _pv in got2] == [1], got2  # 상한 1 — 2쪽은 안 부름
    finally:
        M._convert_to_pdf, M.soffice_bin, M.vlm_page = orig_convert, orig_soffice2, orig_vlm
        _env.close()
    print("[selftest] 가짜 soffice 변환 + 가짜 VLM — 후보 슬라이드만 호출·PARSE_PPTX_RENDER_MAX 상한 통과")

    # F7 — render_slides(): candidate_slides와 무관하게 호출부가 고른 슬라이드만(여기선 3쪽, AD20 후보 아님) 렌더
    _env = pc.PIPE.env(PARSE_RAW_ROOT=str(store))  # S7c — 설정 객체만 바꿔 끼움
    _env.__enter__()
    _convert_to_pdf_orig, soffice_orig = M._convert_to_pdf, M.soffice_bin
    M._convert_to_pdf = _fake_convert
    M.soffice_bin = lambda: "fake-soffice"
    try:
        assert render_slides(pptx_path, []) == {}  # 빈 목록 — 변환 자체를 안 함(즉시 반환)
        got3 = render_slides(pptx_path, [3, 99])  # 3쪽만(가짜 pdf는 3쪽, 99는 범위 밖이라 빠짐)
        assert list(got3.keys()) == [3] and got3[3].startswith(b"\x89PNG")
        assert render_slides("not_pptx.docx", [1]) == {}  # pptx 아님 — 즉시 빈 묶음
    finally:
        M._convert_to_pdf, M.soffice_bin = _convert_to_pdf_orig, soffice_orig
        _env.__exit__(None, None, None)
    print("[selftest] F7 — render_slides(): candidate_slides와 무관하게 호출부가 고른 슬라이드만 렌더(soffice 변환 재사용) 통과")

    orig_soffice_none = M.soffice_bin
    M.soffice_bin = lambda: None
    try:
        assert render_slides(pptx_path, [1]) == {}  # soffice 없음 — 빈 묶음(조용히 건너뜀)
    finally:
        M.soffice_bin = orig_soffice_none
    print("[selftest] F7 — render_slides(): soffice 없음 — 빈 묶음(조용히 건너뜀) 통과")

    # 타임아웃 경로 — soffice 있다고 치고(가짜) Popen이 wait()에서 TimeoutExpired를 던지는 느린 프로세스를 흉내
    class _FakeTimeoutProc:
        def __init__(self, *a, **k):
            self.killed = False

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="soffice", timeout=timeout)
            return 0

        def kill(self):
            self.killed = True

        def poll(self):  # exitclean.track·종료 정리가 부름
            return 0 if self.killed else None

    fake = _FakeTimeoutProc()
    orig_popen, orig_soffice3, orig_stop = subprocess.Popen, M.soffice_bin, M.exitclean.stop
    subprocess.Popen = lambda *a, **k: fake
    M.soffice_bin = lambda: "fake-soffice"
    M.exitclean.stop = lambda p, grace=10: p.kill()  # pl-27 — 묶음째 끝내기·회수(실제 신호·taskkill은 test_exitclean이 봄)
    try:
        r = M._convert_to_pdf(pptx_path, d, 0.01)
        assert r is None and fake.killed
    finally:
        subprocess.Popen, M.soffice_bin, M.exitclean.stop = orig_popen, orig_soffice3, orig_stop
    print("[selftest] 변환 타임아웃 — 자식 프로세스만 종료(kill)하고 None(빈 결과), 고아 없음 통과")

    # AD14 — shape_render_pages(): 꺼짐·확장자 아님·shape_detect 문턱 미달(soffice 호출 자체를 안 함)·soffice 없음
    assert shape_render_pages("x.pptx") == {}  # pptx는 이 함수 대상 아님(render_slides가 따로 담당)
    with pc.PIPE.env(PARSE_DOC_SHAPE_FIGURE="0"):  # S7c — 설정 객체만 바꿔 끼움
        assert shape_render_pages("x.docx") == {}
    print("[selftest] AD14 — pptx 대상 아님·PARSE_DOC_SHAPE_FIGURE=0 → 빈 묶음 통과")

    def _boom_soffice():
        raise AssertionError("shape_detect가 False인데 soffice_bin()이 불렸다")

    orig_has_shapes, orig_soffice4 = shape_detect.docx_has_shapes, M.soffice_bin
    shape_detect.docx_has_shapes = lambda p: False
    M.soffice_bin = _boom_soffice
    try:
        assert shape_render_pages("x.docx") == {}  # 문턱 미달 — soffice_bin()도 안 불림(비용 0)
    finally:
        shape_detect.docx_has_shapes, M.soffice_bin = orig_has_shapes, orig_soffice4
    print("[selftest] AD14 — shape_detect 문턱 미달이면 soffice 호출 자체를 안 함(비용 0) 통과")

    shape_detect.docx_has_shapes = lambda p: True
    M.soffice_bin = lambda: None
    try:
        assert shape_render_pages("x.docx") == {}  # soffice 없음 — 빈 묶음(진단 1줄만)
    finally:
        shape_detect.docx_has_shapes, M.soffice_bin = orig_has_shapes, orig_soffice4
    print("[selftest] AD14 — soffice 없음 — 빈 묶음(조용히 건너뜀) 통과")

    def _png_1x1():
        import io as _io

        from PIL import Image

        buf = _io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(buf, "PNG")
        return buf.getvalue()

    def _fake_convert_shapes(pptx_path_, out_dir, timeout):
        """가짜 변환 결과 — 4쪽: 1쪽 채워진 도형(우리 합성 상자 같은 solidFill, 이미지 없음, 후보) · 2쪽 삽입
        이미지만(후보 아님) · 3쪽 빈 쪽(후보 아님) · 4쪽 표 테두리(축 정렬 윤곽선 사각형, 채움 없음 — 독립 검토
        반영(10-13): _is_table_like가 걸러야 함, 후보 아님)."""
        fd = fitz.open()
        pg1 = fd.new_page(width=400, height=300)
        shp = pg1.new_shape()
        shp.draw_rect(fitz.Rect(10, 10, 100, 100))
        shp.finish(color=(0, 0, 0), fill=(0.9, 0.9, 1.0))
        shp.commit()
        pg2 = fd.new_page(width=400, height=300)
        pg2.insert_image(fitz.Rect(10, 10, 50, 50), stream=_png_1x1())
        fd.new_page(width=400, height=300)
        pg4 = fd.new_page(width=400, height=300)
        shp4 = pg4.new_shape()
        for r in range(3):
            shp4.draw_rect(fitz.Rect(10, 10 + r * 30, 150, 40 + r * 30))  # 표 셀 테두리(채움 없음, 축 정렬)
        shp4.finish(color=(0, 0, 0))
        shp4.commit()
        out = Path(out_dir) / (Path(pptx_path_).stem + ".pdf")
        fd.save(out)
        fd.close()
        return out

    shape_detect.docx_has_shapes = lambda p: True
    M.soffice_bin = lambda: "fake-soffice"
    M._convert_to_pdf = _fake_convert_shapes
    _env = pc.PIPE.env(PARSE_RAW_ROOT=str(store))  # S7c — 설정 객체만 바꿔 끼움
    _env.__enter__()
    try:
        got = shape_render_pages(d / "shapes.docx")
        assert list(got.keys()) == [1], got  # 2쪽(이미지 있음)·3쪽(그려진 것 없음)·4쪽(표 테두리)은 후보 아님
        assert got[1].startswith(b"\x89PNG")
        with pc.PIPE.env(PARSE_PPTX_RENDER_MAX="0"):
            assert shape_render_pages(d / "shapes.docx") == {}  # 상한 0 — 후보 있어도 안 돌려줌
    finally:
        shape_detect.docx_has_shapes, M.soffice_bin, M._convert_to_pdf = orig_has_shapes, orig_soffice4, orig_convert
        _env.__exit__(None, None, None)
    print("[selftest] AD14 — shape_render_pages(): 채워진 도형 쪽만 후보(이미지·빈·표 테두리 쪽은 빠짐)·상한 통과")


def selftest_soffice_resolution():
    """독립 검토(10-13) — PATH에 soffice가 없어도(이 PC가 실측 사례: LibreOffice가 깔려 있지만 PATH엔 없음)
    흔한 설치 경로(가짜 목록으로 시험)에서 찾는지 · 다 없으면 None + 경고가 이 프로세스에서 1번만(반복 호출해도
    추가 안 됨)인지."""
    import io
    import tempfile

    orig_which, orig_common = shutil.which, M._common_soffice_paths

    # ① PATH에 없어도 흔한 설치 경로(가짜 목록)에서 찾음
    d = Path(tempfile.mkdtemp())
    fake_soffice = d / "fake_program_files" / "soffice.exe"
    fake_soffice.parent.mkdir(parents=True, exist_ok=True)
    fake_soffice.write_text("fake", encoding="utf-8")
    shutil.which = lambda name: None  # PATH에는 없는 척
    M._common_soffice_paths = lambda: [str(d / "nope" / "soffice"), str(fake_soffice)]
    try:
        with pc.PIPE.env(SOFFICE_BIN=""):  # S7c — 설정 객체에서만 비움(S7e2 — 빈 글자: 이미지 기본값 /usr/bin/soffice도 안 씀)
            assert M.soffice_bin() == str(fake_soffice)
    finally:
        shutil.which, M._common_soffice_paths = orig_which, orig_common
    print("[selftest] soffice_bin() — PATH에 없어도 흔한 설치 경로(가짜 목록)에서 찾음 통과")

    # ② 다 없으면 None + 경고 1번만(stderr) — 반복 호출해도 추가 안 됨
    shutil.which = lambda name: None
    M._common_soffice_paths = lambda: []
    _soffice_warned[0] = False
    captured, orig_stderr = io.StringIO(), sys.stderr
    sys.stderr = captured
    try:
        with pc.PIPE.env(SOFFICE_BIN=""):  # (옛 시험은 위 ①에서 지운 SOFFICE_BIN이 그대로 지워진 채 — S7e2 빈 글자: 이미지 기본값도 안 씀)
            assert M.soffice_bin() is None
            assert M.soffice_bin() is None  # 두 번째 호출 — 경고 추가 안 됨
    finally:
        sys.stderr = orig_stderr
        shutil.which, M._common_soffice_paths = orig_which, orig_common
        _soffice_warned[0] = False
    msg = captured.getvalue()
    assert msg.count("[pptx_render] soffice를 못 찾음") == 1, msg
    print("[selftest] soffice_bin() — 다 없으면 None, 경고는 프로세스당 1번만(반복 호출해도 추가 안 됨) 통과")


def test_main():  # 옛 `if __name__ == "__main__":` 몸통
    selftest()
    selftest_soffice_resolution()
