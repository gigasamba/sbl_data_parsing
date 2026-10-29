"""gold_draft — 쪽 이미지 + 우리 파싱 참고 글(정답 아님) → 정답 초안 마크다운(GS2, GA2). Caller: data_parsing/gold_draft.py _vlm_gold().
page_transcribe와 다른 지시문 패키지(캐시 열쇠·prompt_id가 달라 page_transcribe의 파싱 VLM 캐시·동작에 영향 없음, GS2 설계).
Prompt text lives in this package prompts/*.md (AD33), loaded by common/agent_prompts.template(); the caller appends the
page's reference text + tail() itself (string-concat 호출부 — agent_prompts.py 모듈 설명의 template()+data+tail() 패턴).
instruction stays "" so ADK adds no identity system text (mode="single_turn")."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    assert not tools, "gold_draft: pipeline agent takes no tools (GA4 -- flow stays in caller code)"
    return LlmAgent(name="gold_draft", model=model, mode="single_turn", instruction="",
                     description="쪽 이미지 + 파싱 참고 글 → 정답 초안 마크다운(GS2)")
