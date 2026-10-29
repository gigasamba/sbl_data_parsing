"""parse_agent — AG11 1단계 파싱 에이전트(dev/docs/common/parse-agent-design.md 'AG11 구현 계획' 절). mode="chat"이라
지금 함수를 감싼 도구(dev/tools/parse_agent_tools.py)를 여러 턴에 걸쳐 불러 다음 행동을 정한다(GA4 — 되돌이는 모델이
도구를 다시 부르는 것, max_turns·budget으로 상한). local_tools의 실제 python 함수는 호출자(dev/common/adk.py.
run_agent)가 FunctionTool로 감싸 주입한다 — 이 파일 자신은 dev/common·modules를 import하지 않는다(check_modules.py
⑦). 지시문 글자(기본 계획·판단 지점 4개)는 dev/agents/parse_agent/prompts/plan.md(AD33 ⓐ) — doc_summary 등 기존
패키지와 같은 관례로 **instruction=""로 두고 호출자가 사용자 메시지에 담아 보낸다**(ADK identity 시스템 문구를 안
붙이는 관례, GA2 I3/I4는 single_turn 패키지 얘기지만 parse_agent도 같은 이유로 지시문을 instruction에 안 둔다 —
instruction을 바꾸면 매 호출 agent.model_copy로 덮어쓰는 다른 패키지들과 달리 이 패키지는 고정 텍스트라 바꿀 일이
없고, 사용자 메시지 쪽에 두면 CLI(dev/cli/parse_agent.py)가 문서 신호 요약을 같은 메시지에 이어붙이기 쉽다)."""
from google.adk.agents import LlmAgent


def create_agent(model, tools):
    return LlmAgent(
        name="parse_agent",
        model=model,
        mode="chat",
        instruction="",
        description="AG11 1단계 — 지금 파싱 흐름을 기본 계획으로 따르고 애매한 지점만 도구로 판단하는 파싱 에이전트",
        tools=list(tools),
    )
