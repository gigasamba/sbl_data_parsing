"""research_judge — 근거 조각이 하위 질문에 답하는지 판정(검색한 사람과 다른 기준) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/search/research.py _judge() — _JUDGE_PROMPT.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "research_judge: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="research_judge", model=model, mode="single_turn", instruction="",
                     description='근거 조각이 하위 질문에 답하는지 판정(검색한 사람과 다른 기준)')
