"""doc_summary — 문서 본문을 한국어 3문장 이내로 요약 (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/structure/bundle.py llm_summary().
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "doc_summary: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="doc_summary", model=model, mode="single_turn", instruction="",
                     description='문서 본문을 한국어 3문장 이내로 요약')
