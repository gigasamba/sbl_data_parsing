"""wiki_term_draft — 미등록 용어 1개의 사전 행 초안을 제안(자동 승인 없음 — status=draft만) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: cli/wiki_draft.py propose_term()/main() — _PROMPT.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "wiki_term_draft: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="wiki_term_draft", model=model, mode="single_turn", instruction="",
                     description='미등록 용어 1개의 사전 행 초안을 제안(자동 승인 없음 — status=draft만)')
