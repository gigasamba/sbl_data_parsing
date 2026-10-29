"""agg_llm_route -- 집계(SQL 틀) vs 검색 분류 + 인자 추출(R1, AD42.AD45②, dev/docs/common/ga-gamma-design.md §1).
Caller: modules/search/aggregate.py llm_plan() <- mcp_server.py do_aggregate() -- SEARCH_AGG_LLM=1일 때만.
Prompt text lives in this package prompts/*.md, loaded by common/agent_prompts.load(); the caller sends it as the user message.
instruction stays "" so ADK adds no identity system text (mode="single_turn") -- matches query_decompose's request shape."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "agg_llm_route: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="agg_llm_route", model=model, mode="single_turn", instruction="",
                     description='집계(SQL 틀) vs 검색 분류 + 인자 추출(R1)')
