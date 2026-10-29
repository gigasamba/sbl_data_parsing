"""value_choice — 조각 재판독 후보 중 이미지에 보이는 값을 하나 고름(AD29 P3 VLM 선택형 재판독, GA2,
dev/docs/common/ga-gamma-design.md §1). Caller: modules/parse/post/reread_p3.py vlm_choose() — P_CHOOSE.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller
appends the candidate list and sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- matches other pipeline packages."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "value_choice: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="value_choice", model=model, mode="single_turn", instruction="",
                     description='조각 재판독 후보 중 이미지에 보이는 값을 하나 고름(AD29 P3)')
