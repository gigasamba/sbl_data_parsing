"""triple_extract — 청크 글자에서 (주어, 관계, 목적어) 삼중항을 뽑아 지식그래프 간선으로 (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: eval/stages.py build_graph() mode=="llm" — _TRIPLE_SYSTEM.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "triple_extract: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="triple_extract", model=model, mode="single_turn", instruction="",
                     description='청크 글자에서 (주어, 관계, 목적어) 삼중항을 뽑아 지식그래프 간선으로')
