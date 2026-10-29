"""figure_judge — 독립 추출과 우리 기록을 대조한 자동 diff를 감사(검토 루프 판정자) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/parse/review/figure_review.py _vlm_call(which="judge") — P_JUDGE.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "figure_judge: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="figure_judge", model=model, mode="single_turn", instruction="",
                     description='독립 추출과 우리 기록을 대조한 자동 diff를 감사(검토 루프 판정자)')
