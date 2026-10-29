"""parse_shadow — PA2 그림자 모드: rep.context·rep.decisions(PA0)를 보고 결정 지점마다 다음 행동만 제안
(실행은 규칙 그대로) (GA2, dev/docs/common/ga-gamma-design.md §1). Caller: dev/cli/parse_shadow.py ←
modules/parse/post/shadow.py propose_llm().
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends
it as the user message. instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the
request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "parse_shadow: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="parse_shadow", model=model, mode="single_turn", instruction="",
                     description="PA2 그림자 모드 — rep.context·rep.decisions를 보고 결정 지점별 다음 행동만 제안")
