"""pipeline.mcp_parse_service — 작업 자식 설정(10-29): 서비스 쪽당 제한·첫 시도 하한·보통 우선순위."""

from unittest import mock

from pipeline import config as pc


def test_job_env_overrides():
    from pipeline import mcp_parse_service as S

    seen = {}

    def fake_env(**names):
        seen.update(names)
        return {"SETTINGS_FILE": "x"}

    S._JOB_ENVS.clear()
    with pc.PIPE.env(PARSE_MCP_TEXT_PAGE_SEC="1", PARSE_MCP_VLM_PAGE_SEC="60", PARSE_MCP_WARMUP_SEC="20"):
        with mock.patch.object(S, "settings_env", fake_env):
            S._job_env("supsub")
    S._JOB_ENVS.clear()
    assert seen["PARSE_LOW_PRIORITY"] == "0", seen  # 서비스 엔진 자식은 보통 우선순위(일괄 파싱보다 먼저)
    assert float(seen["PARSE_TEXT_PAGE_SEC"]) == 1 and float(seen["PARSE_VLM_PAGE_SEC"]) == 60, seen
    assert float(seen["PARSE_WARMUP_SEC"]) == 20 and seen["PARSE_POST"] == "supsub", seen


def test_ocr_follows_pipeline_switch():
    from pipeline import mcp_parse_service as S

    with pc.PIPE.env(PARSE_OCR_ENGINE="1"):
        assert S._engines_no_ocr_arg() == []  # 켜면 run_all 기본(OCR·VLM 포함)
    args = S._engines_no_ocr_arg()
    assert not args or not {"rapidocr_ko", "qwen_vlm"} & set(args[1].split(","))


def test_scan_pdf_note():
    """pl-03(사용자 10-31) — 스캔 PDF는 파이프라인 없이 임시 안내(돌 엔진이 없음), 표본보다 스캔으로 분류돼 엔진이 하나도 못 돌면
    run_all의 NO_JOB_MARK 줄로 같은 안내 — 엔진이 돌다 다 실패했을 때만 DRM 추정."""
    from pipeline import mcp_parse_service as S
    from pipeline.extract.run_all import IDLE_MARK, NO_JOB_MARK

    assert S.skip_note("a.pdf", 0) == S.SCAN_NOTE and S.skip_note("a.pdf", 19) == S.SCAN_NOTE
    assert S.skip_note("a.pdf", 20) is None and S.skip_note("a.pdf", -1) is None and S.skip_note("a.pdf", None) is None
    assert S.skip_note("a.png", None) == S.IMAGE_NOTE and S.skip_note("a.docx", None) is None
    assert "추후 지원 예정" in S.SCAN_NOTE
    assert S.empty_note(f"== run_all\n{IDLE_MARK}(비교하려면 stack json을 고침): docling\n{NO_JOB_MARK}\n") == S.SCAN_NOTE
    assert S.empty_note(f"== run_all\n{IDLE_MARK}(비교하려면 stack json을 고침): docling\n") == S.DRM_NOTE  # 일부만 안 돎
    assert S.empty_note("== run_all\nTraceback …") == S.DRM_NOTE and S.empty_note(None) == S.DRM_NOTE
