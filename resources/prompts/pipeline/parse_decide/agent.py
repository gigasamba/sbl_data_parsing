"""parse_decide — AG11 2단계 판단 세션(dev/docs/common/parse-agent-design.md '2단계 설계'). mode="chat"이라 도구
(dev/modules/parse/post/agent_step.py session_tools — list_fragments·reread_fragment·decide_fragment·finish)를 여러
턴에 걸쳐 부른다(되돌이 = 다른 방법으로 다시 reread_fragment, max_turns·budget으로 상한 — 콜백은 run_agentic).
지시문 글자는 prompt.md — parse_agent와 같은 관례로 instruction=""(호출자가 사용자 메시지에 담아 보냄)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    return LlmAgent(
        name="parse_decide",
        model=model,
        mode="chat",
        instruction="",
        description="AG11 2단계 — 규칙이 애매로 넘긴 조각만 다시 읽기 방법 선택·되돌이·끝낼지 판단",
        tools=list(tools),
    )
