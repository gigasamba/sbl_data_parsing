"""mermaid_check — 쪽 이미지 + 단계 이름 → 단계별 나가는 화살표 JSON(블라인드 — 앵커링 방지)(gold_draft Mermaid 2차 점검, GA2).
Caller: data_parsing/gold_draft.py _vlm_check_mermaid(). Prompt text in prompt.md (template()); caller appends the numbered
edge list + tail(). instruction stays "" so ADK adds no identity system text (mode="single_turn")."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "mermaid_check: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="mermaid_check", model=model, mode="single_turn", instruction="",
                     description="흐름도 화살표 목록을 쪽 이미지와 대조 점검")
