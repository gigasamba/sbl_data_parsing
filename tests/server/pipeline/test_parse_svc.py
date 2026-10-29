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
