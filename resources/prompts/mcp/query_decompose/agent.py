"""query_decompose — 검색 질문을 하위 질문 여러 개로 쪼갬(MCP 검색·수동 질의 공용) (GA2, dev/docs/common/ga-gamma-design.md SS1). Caller: modules/search/mcp_server.py do_search() · cli/pipeline.py ask() — decompose.split_question 호출.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- the request body matches pre-GA2 (I3/I4)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "query_decompose: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="query_decompose", model=model, mode="single_turn", instruction="",
                     description='검색 질문을 하위 질문 여러 개로 쪼갬(MCP 검색·수동 질의 공용)')
