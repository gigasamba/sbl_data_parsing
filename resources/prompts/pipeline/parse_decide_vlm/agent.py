"""parse_decide_vlm — parse_decide(AG11 2단계 판단 세션)의 VLM 모델판(AG11 3단계 b · AG6 M2: 이미지 있는 문서는 판단도
VLM — 판단·판독이 같은 모델). 도구·예산·지시문은 parse_decide와 같다(지시문 글자 = parse_decide/prompt.md, 호출자
dev/modules/parse/post/agent_step.py가 사용자 메시지에 담아 보냄 — 그래서 이 패키지엔 prompt.md가 없다)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    return LlmAgent(
        name="parse_decide_vlm",
        model=model,
        mode="chat",
        instruction="",
        description="AG11 3단계(AG6 M2) — 규칙이 애매로 넘긴 조각만 다시 읽기 방법 선택·되돌이·끝낼지 판단(VLM 모델)",
        tools=list(tools),
    )
