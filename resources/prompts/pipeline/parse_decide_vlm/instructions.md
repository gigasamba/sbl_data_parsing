# parse_decide_vlm — instructions (ADK13 형식)

`parse_decide`와 역할·입출력·도구·판단 기준·예산·사람 확인·금지가 **같다** — [../parse_decide/instructions.md](../parse_decide/instructions.md).
지시문 글자도 `parse_decide/prompt.md` 그대로(같은 바이트, agent_step이 이어붙임).

## 다른 점
- 모델 역할 `vlm`(agent.json `model_role`) — `PARSE_AGENT_MODEL=vlm`이고 문서에 이미지가 하나라도 있을 때(`vlm_session=true`)만
  `agent_step`이 이 패키지로 세션을 연다(AG6 M2: 판단과 판독이 같은 VLM, 맥락 누적은 `vlm_context` 판독이 이어받음).
  이미지 없는 문서·`PARSE_AGENT_MODEL=split`(기본)은 `parse_decide`(llm).
- 판단 세션 메시지에 이미지를 직접 넣지는 않는다(턴마다 이미지가 다시 실려 토큰 예산 24,000을 넘기기 쉬움) — 보는 일은 도구(`reread_fragment`)가 함.

## 예시
`parse_decide/cases.json`과 같다.
