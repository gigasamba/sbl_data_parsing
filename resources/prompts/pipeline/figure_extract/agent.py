"""figure_extract — 그림만 보고 독립적으로 재추출(기록 검토 루프 — 원본 기록은 보여주지 않음) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/parse/review/figure_review.py extract() — P_EXTRACT.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "figure_extract: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="figure_extract", model=model, mode="single_turn", instruction="",
                     description='그림만 보고 독립적으로 재추출(기록 검토 루프 — 원본 기록은 보여주지 않음)')
