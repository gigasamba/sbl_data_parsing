"""qa_draft — 쪽 이미지 → 구조 의존 질문-답변 초안 JSON(QA1, GA2). Caller: data_parsing/qa_draft.py _vlm_qa().
gold_draft(옮겨 적기)와 다른 지시문 패키지 — 캐시 열쇠·prompt_id가 달라 파싱 VLM·gold_draft 캐시에 영향 없음.
Prompt text lives in this package prompt.md, loaded by common_tools/agent_prompts.template(); the caller appends tail()
itself (template()+tail() 패턴). instruction stays "" so ADK adds no identity system text (mode="single_turn")."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "qa_draft: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="qa_draft", model=model, mode="single_turn", instruction="",
                     description="쪽 이미지 → 표·그래프·흐름도 질문-답변 초안(QA1)")
