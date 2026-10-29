"""figure_chart_raster — F14(b) 래스터 차트 단계식 값 추출(눈금·격자선 픽셀 → 비율 배치 → 보간).
Caller: data_parsing/postprocess/chart_values.py — RASTER_PROMPT(아직 실 호출 배선 없음, 가짜/스텁 전용).
Prompt text lives in this package prompt.md, loaded by common_tools.agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- figure_overlay와 같은 패턴."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "figure_chart_raster: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="figure_chart_raster", model=model, mode="single_turn", instruction="",
                     description="래스터 차트 1장의 눈금·막대 위치를 JSON으로(값은 호출부가 보간)")
