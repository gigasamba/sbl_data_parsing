"""value_choice_ctx — value_choice(AD29 P3)의 맥락 포함판(AG11 2단계 D9 vlm_context). Caller:
modules/parse/post/agent_step.py _ctx_vlm_call(). 맥락이 다른 글자라 prompt_id를 따로 둔다(설계 §4 'context≠none이면
새 prompt_id' — value_choice 캐시 열쇠·패키지 지문은 안 건드림). instruction=""(다른 pipeline 패키지와 같은 관례)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "value_choice_ctx: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="value_choice_ctx", model=model, mode="single_turn", instruction="",
                     description="조각 재판독 후보 중 이미지에 보이는 값을 하나 고름(맥락 포함, AG11 2단계)")
