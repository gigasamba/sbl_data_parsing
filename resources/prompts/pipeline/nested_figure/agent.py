"""nested_figure — 쪽 전체 그림(page_render) 안의 자식 그림 bbox 찾기 (F7, 중첩 그림 설계 §2-5).
Caller: data_parsing.postprocess.nested.bbox_regions() — P_BBOX.
Prompt text lives in this package prompt.md (AD33 pattern), loaded by common/agent_prompts.load().
instruction stays "" so ADK adds no identity system text (mode="single_turn") — same request shape as figure_describe/page_transcribe."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "nested_figure: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="nested_figure", model=model, mode="single_turn", instruction="",
                     description="쪽 전체 그림 안의 자식 그림(그래프·사진·도면·표) bbox 찾기")
