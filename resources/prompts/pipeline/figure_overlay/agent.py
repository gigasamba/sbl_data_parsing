"""figure_overlay — F12(10-14) 겹친 개체 묶음(그림+글상자/화살표/도형) 1장을 검색용 기록(JSON)으로.
Caller: parse/postprocess/figures.py vlm_fig_overlay() — P_FIGOVERLAY.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- figure_describe과 같은 패턴(GA2)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "figure_overlay: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="figure_overlay", model=model, mode="single_turn", instruction="",
                     description='겹친 개체 묶음(그림+글상자/화살표/도형) 1장을 검색용 기록(JSON)으로')
