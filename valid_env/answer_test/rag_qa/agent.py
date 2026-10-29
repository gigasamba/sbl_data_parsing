"""rag_qa — agentic 검색 QA(PC 답변 점검 — validation/e2e/answer_gen.py가 common.ai.adk.run_agent로 돌림, S10).
검색 MCP 도구(search·edw_meta·query_edw — 이름은 MCP 그대로)와 로컬 verify_citations를 매 턴 스스로 골라 부른다. 도구 함수는
호출자가 질문마다 만들어 넘긴다(agent.json local_tools와 같은 이름 — 인용 근거 pool도 호출자 쪽, 옛 agent_platform 판의
before/after_tool_callback은 run_agent가 콜백을 자기 것으로 덮어 쓰지 않음). 지시문은 instructions.md + 출력 JSON 스키마."""
import json
from pathlib import Path

from google.adk.agents import LlmAgent


def _instruction():
    here = Path(__file__).parent
    schema = json.loads((here / "agent.json").read_text(encoding="utf-8"))["output_schema"]
    return ((here / "instructions.md").read_text(encoding="utf-8")
            + "\n## Output JSON schema — the response must be exactly one object matching this\n\n```json\n"
            + json.dumps(schema, ensure_ascii=False, indent=1) + "\n```\n")


def create_agent(model, tools):
    return LlmAgent(
        name="rag_qa",
        model=model,
        mode="chat",
        instruction=_instruction(),
        description="검색 MCP 근거로 숫자마다 인용을 붙여 답하는 agentic 검색 QA",
        tools=list(tools),
    )
