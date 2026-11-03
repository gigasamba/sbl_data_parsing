"""PC 답변 점검(answer_gen)만 쓰는 도구 왕복 — 지시문 패키지(rag_qa: agent.json·instructions.md, 바이트 그대로) + 모델이 도구를 골라 부르는
OpenAI 호환 /chat/completions 다중 턴(0.2.0 — 옛 common.ai.adk.run_agent의 ADK 장치를 지우고 이리로, pl-46).
모델 호출은 common.ai.llm.complete(tools=)로(가드·재시도·회로 차단기 그대로). 턴마다 공유 장부를 거친다(옛 per_turn_admit):
common.ai.llm.admit_turn() — 호출 수 세기 + 외부 LLM이면 LLM_BUDGET_USD 턴 선차감 → 응답 usage로 정산(못 받으면 반환).
멈춤 글자(answer_gen STOPS와 같음): "공유 호출 상한"(장부 거부) · "예산 초과"(매니페스트 턴·도구 호출 수) · "시간 상한"(budget.seconds·timeout).
LLM_FAKE=1이면 네트워크 없이: fake_policy가 있으면 결정적 정책으로 도구까지 돌리고, 없으면 모의 글자 한 줄(도구 0)."""

import asyncio
import inspect
import json
import time

from common.ai import llm as L
from common.core.paths import resolve_agent_dir

STOP_CALLS, STOP_BUDGET, STOP_TIME = "공유 호출 상한", "예산 초과", "시간 상한"
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object", list: "array"}


def _system(pkg_dir, manifest):
    """패키지 지시문 — instructions.md + 출력 JSON 스키마(옛 rag_qa/agent.py _instruction()과 같은 글자)."""
    return (
        (pkg_dir / "instructions.md").read_text(encoding="utf-8")
        + "\n## Output JSON schema — the response must be exactly one object matching this\n\n```json\n"
        + json.dumps(manifest["output_schema"], ensure_ascii=False, indent=1)
        + "\n```\n"
    )


def tool_spec(fn):
    """파이썬 함수 → OpenAI 함수 도구(이름·설명=docstring·인자 = 주석 타입, 기본값 없는 인자는 필수)."""
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        props[name] = {"type": _JSON_TYPES.get(p.annotation, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _call_tool(fn, args):
    """도구 한 번 — async면 새 루프에서. 인자 오류는 모델에 돌려줄 {"error"}(질문 전체를 멈추지 않게)."""
    try:
        out = fn(**args)
        return asyncio.run(out) if inspect.iscoroutine(out) else out
    except TypeError as e:
        return {"error": f"인자 오류 — {e}"}


def run(agent_id, question, tools, *, timeout=None, fake_policy=None):
    """→ (최종 글자 또는 멈춤 글자, 도구 궤적 [{"tool", "args"}], usage{model_calls, tool_calls, prompt_tokens, completion_tokens})."""
    pkg = resolve_agent_dir(agent_id)
    manifest = json.loads((pkg / "agent.json").read_text(encoding="utf-8"))
    if set(tools) != set(manifest.get("local_tools") or []):
        raise L.ModelUnavailable(
            f"{agent_id}: tools 이름이 local_tools와 다름 — {sorted(tools)} != {sorted(manifest.get('local_tools') or [])}"
        )
    usage = {"model_calls": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    traj = []
    fake = L.fake_llm()
    if fake and fake_policy is None:
        L.record_fake_call(len(question))
        return question[:200] + "[FAKE]", [], {**usage, "fake": True}
    budget = manifest.get("budget") or {}
    limit = min(x for x in (timeout, budget.get("seconds")) if x) if (timeout or budget.get("seconds")) else 120.0
    end = time.monotonic() + float(limit)
    messages = [{"role": "system", "content": _system(pkg, manifest)}, {"role": "user", "content": question}]
    specs = [tool_spec(fn) for fn in tools.values()]
    prof = None if fake else L.profile("llm")
    if not fake and prof is None:
        raise L.ModelUnavailable("LLM_BASE_URL·LLM_MODEL 미설정")
    results = []  # fake_policy용 — [(도구 이름, 응답 dict)]
    for _turn in range(int(manifest.get("max_turns") or 1)):
        left = end - time.monotonic()
        if left <= 0:
            return STOP_TIME, traj, usage
        if fake:
            L.record_fake_call(sum(len(str(m.get("content") or "")) for m in messages))
            act = fake_policy(results)
            msg = (
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": f"f{len(traj)}", "function": {"name": act[1], "arguments": json.dumps(act[2], ensure_ascii=False)}}
                    ],
                }
                if act[0] == "call"
                else {"role": "assistant", "content": act[1]}
            )
        else:
            turn = L.admit_turn("llm")
            if turn is None:
                return STOP_CALLS, traj, usage
            try:
                msg, u = L.complete(
                    "llm", messages, max_tokens=None, timeout=left, tools=specs, retries=1, agent=agent_id, call_reserved=True
                )  # 이 턴 자리는 admit_turn이 예약
            except Exception:
                turn.release()  # 응답을 못 받은 턴의 선차감 반환(옛 GA9)
                raise
            turn.settle(u)
            usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            usage["completion_tokens"] += u.get("completion_tokens", 0)
        usage["model_calls"] += 1
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or "", traj, usage
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
        for c in calls:
            if usage["tool_calls"] >= int(budget.get("tool_calls") or 1 << 30):
                return STOP_BUDGET, traj, usage
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = None
            res = (
                {"error": f"모르는 도구 {name}"}
                if name not in tools
                else {"error": "인자가 JSON 객체가 아님"}
                if not isinstance(args, dict)
                else _call_tool(tools[name], args)
            )
            traj.append({"tool": name, "args": args})
            usage["tool_calls"] += 1
            results.append((name, res if isinstance(res, dict) else {"result": res}))
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": json.dumps(res, ensure_ascii=False, default=str)})
    return STOP_BUDGET, traj, usage
