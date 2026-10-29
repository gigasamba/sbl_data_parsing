"""table_struct_judge — 경계 표(행 30~90% 일치)만, 정답 표와 출력 표가 같은 행×열 관계인지 판정(TS1, GA2).
Caller: data_parsing/evaluation/score_gold.py _table_judge_fn()._judge() — SCORE_TABLE_JUDGE=llm.
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.load(); the caller sends it
as the user message. instruction stays "" so ADK adds no identity system text (mode="single_turn")."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "table_struct_judge: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="table_struct_judge", model=model, mode="single_turn", instruction="",
                     description="경계 표만 — 정답 표와 출력 표가 같은 행×열 관계인지 판정")
