"""figure_describe — 그림 1장을 검색용 기록(JSON)으로 — 종류·요약·글자·값·연결·표 (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/parse/post/figures.py vlm_fig() — P_FIGJ.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "figure_describe: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="figure_describe", model=model, mode="single_turn", instruction="",
                     description='그림 1장을 검색용 기록(JSON)으로 — 종류·요약·글자·값·연결·표')
