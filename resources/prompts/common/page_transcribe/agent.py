"""page_transcribe — 스캔·이미지 문서 쪽 1장을 마크다운으로 옮김(OCR 교차 확인용) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/parse/post/vlm_page.py vlm_page() — P_PAGE.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "page_transcribe: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="page_transcribe", model=model, mode="single_turn", instruction="",
                     description='스캔·이미지 문서 쪽 1장을 마크다운으로 옮김(OCR 교차 확인용)')
