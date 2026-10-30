"""validation.e2e.answer_gen 시험(S10) — 네트워크 없이: 가짜 MCP(call)·결정적 정책 모델(LLM_FAKE + fake_policy)로
rag_qa 패키지 로드(매니페스트·그래프 검사)·도구 이름 집합·근거 pool·verify_citations·최종 JSON 고르기를 끝까지 본다."""

import json
from types import SimpleNamespace

from common.config import settings
from validation.e2e import answer_gen as AG

_EV = {"doc_key": "d1", "chunk_key": "d1:0", "page": 1, "via": "v", "text": "시험 규격서 pH: 7.0 ± 0.2", "bbox": "1,2,3,4"}


def _contracts():
    return {n: SimpleNamespace(description=f"{n} 설명") for n in AG.MCP_TOOLS}


def test_tools_and_pool():
    calls, pool = [], []

    async def call(name, args):
        calls.append((name, args))
        return {"question": args.get("question"), "evidence": [_EV], "ms": 1.0}

    tools = AG.make_tools(call, _contracts(), pool, 5)
    assert set(tools) == {"search", "edw_meta", "query_edw", "verify_citations"}
    assert tools["search"].__doc__ == "search 설명"
    import asyncio

    out = asyncio.run(tools["search"](question="pH", client=""))
    assert calls == [("search", {"question": "pH", "k": 5})], calls  # 빈 필터는 안 보냄
    assert "bbox" not in out["evidence"][0] and "ms" not in out, out  # 모델에는 근거 칸만
    assert pool == [_EV]  # pool에는 원래 근거 그대로
    ok = {"answer": "pH 7.0", "status": "found", "citations": [{"doc_key": "d1", "chunk_key": "d1:0", "page": 1, "quote": "pH: 7.0 ± 0.2"}]}
    assert tools["verify_citations"](json.dumps(ok, ensure_ascii=False))["ok"] is True
    bad = dict(ok, citations=[dict(ok["citations"][0], quote="pH: 8.0")], answer="pH 8.0")
    assert tools["verify_citations"](json.dumps(bad, ensure_ascii=False))["ok"] is False
    assert tools["verify_citations"](ok)["ok"] is True  # VS11 CR-1 — 객체 인자도(TypeError 아님)
    assert tools["verify_citations"](bad)["ok"] is False
    assert AG.verify(None, pool)["problems"] == ["answer_json must be a JSON object"]
    assert AG.verify(json.dumps(ok).encode(), pool)["ok"] is True  # bytes는 옛처럼 json.loads로
    for arg, problem in (  # 모양 오류 — 질문을 멈추지 않고 problems로, format_error 표시(VS11 CR-2 · VS11b CR-5·CR-6)
        ("[1, 2]", "answer_json must be a JSON object"),  # 패키지 assert는 python -O에서 빠짐 — answer_gen이 먼저 거름
        ('"글자"', "answer_json must be a JSON object"),
        ({"answer": "a", "status": "found", "citations": [], "x": object()}, "answer_json must hold JSON values only"),
        ({"answer": "a", "status": "found", "citations": "c"}, "citations must be a list"),
    ):
        out = AG.verify(arg, pool)
        assert out["ok"] is False and out["problems"] == [problem] and out["format_error"] is True, (arg, out)
    assert AG.verify(bad, pool)["format_error"] is False  # 근거 대조 실패는 모양 오류 아님
    assert AG.verify(ok, pool)["format_error"] is False


def test_mcp_error_to_model():  # 연결 실패도 도구 오류 {"error"}로(질문 전체를 멈추지 않게 — S10 리뷰)
    import asyncio

    out = asyncio.run(AG._mcp_tool("http://127.0.0.1:1/mcp", "", "search", {"question": "x"}))
    assert set(out) == {"error"} and out["error"].startswith("MCP 호출 실패"), out
    assert "ExceptionGroup" not in out["error"], out  # 감싼 진짜 원인을 보임


def test_final_json():
    one = '{"answer": "a", "status": "found", "citations": []}'
    assert AG.final_json(one)["status"] == "found"
    two = 'prose\n```json\n{"answer": "x", "status": "partial", "citations": []}\n```\n```json\n' + one + "\n```"
    assert AG.final_json(two)["answer"] == "a"  # 블록이 여럿이면 마지막(S10 실호출)
    try:
        AG.final_json("JSON 없음")
        raise AssertionError("ValueError가 나야 함")
    except ValueError:
        pass


def test_fake_run():  # run_agent(rag_qa) 끝까지 — 정책: search → verify_citations → 답
    from google.genai import types

    from common.ai import adk

    pool = []

    async def call(name, args):
        return {"evidence": [_EV]}

    with settings.isolated(LLM_FAKE="1"):
        text, traj, usage = adk.run_agent(
            AG.AGENT_ID,
            types.Content(role="user", parts=[types.Part.from_text(text="pH?")]),
            role="llm",
            tools=AG.make_tools(call, _contracts(), pool, 3),
            per_turn_admit=True,
            fake_policy=AG.fake_policy("pH?"),
        )
    assert [t["tool"] for t in traj] == ["search", "verify_citations"], traj
    out = AG.final_json(text)
    assert out["status"] == "found" and out["citations"][0]["doc_key"] == "d1", out
    assert usage["model_calls"] == 3 and usage["tool_calls"] == 2, usage


def _ask_with(text, tools):  # run_agent를 정해진 답으로 바꿔 ask_one 한 번(LLM_FAKE — 바꿔치기가 빗나가도 실호출 없음)
    from common.ai import adk

    saved = adk.run_agent
    adk.run_agent = lambda *a, **k: (text, [{"tool": t} for t in tools], {"model_calls": 2, "tool_calls": len(tools)})
    try:
        with settings.isolated(LLM_FAKE="1"):
            return AG.ask_one(1, "q", 1, "http://127.0.0.1:1/mcp", "", _contracts(), 3, False, 5)
    finally:
        adk.run_agent = saved


def test_ask_one_bad_citations():  # VS10 M-2 — citations가 글자 목록이어도 출력에서 멈추지 않음 · L-1 — 글자 인용은 검증 실패
    row = _ask_with(json.dumps({"answer": "규격 충족", "status": "found", "citations": ["지어낸 인용"]}, ensure_ascii=False), ["query_edw"])
    assert row["run_status"] == "ok" and row["citations"] == ["지어낸 인용"] and "error" not in row, row
    assert row["verify"]["ok"] is False and any(p.startswith("citations 항목") for p in row["verify"]["problems"]), row
    assert "verify_note" not in row, row  # 형식 오류는 EDW 탓으로 적지 않음
    row = _ask_with(json.dumps({"answer": "규격 충족", "status": "found", "citations": "c"}, ensure_ascii=False), ["query_edw"])
    assert row["verify"]["format_error"] is True and "verify_note" not in row, row  # 목록 아닌 citations도(VS11 CR-2)


def test_ask_one_edw_note():  # VS10 M-1 — query_edw 값 답의 verify 실패 이유(C-56)
    row = _ask_with(json.dumps({"answer": "3건", "status": "found", "citations": []}, ensure_ascii=False), ["edw_meta", "query_edw"])
    assert row["verify"]["ok"] is False and row["verify_note"] == AG.EDW_NOTE, row
    row = _ask_with(json.dumps({"answer": "3건", "status": "found", "citations": []}, ensure_ascii=False), ["search"])
    assert row["verify"]["ok"] is False and "verify_note" not in row, row  # query_edw를 안 썼으면 표시 없음
