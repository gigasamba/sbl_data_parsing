#!/usr/bin/env python3
"""답변 생성 점검(PC 전용) — 검색 MCP에 붙어 질문마다 rag_qa 에이전트(valid_env/answer_test/rag_qa/ — PC 전용 데이터는 valid_env에, 사용자 10-29)를 한 번씩 돌린다.
S10(10-28 — D-021 T-14): 옛 루트 answer_gen_test.py(agent_platform — D-013에 삭제)를 common/ai 임시 구현(I6)으로 되살림.

에이전트 루프 = common.ai.adk.run_agent("rag_qa", role="llm", per_turn_admit=True) — 턴마다 LLM_MAX_CALLS·LLM_BUDGET_USD 장부를
거친다(CLAUDE.md 5절). 도구는 MCP tools/list의 search·edw_meta·query_edw를 이 파일의 함수로 감싸 넘기고(설명은 MCP 계약 그대로,
parse_document는 QA와 무관해 뺌), 로컬 verify_citations는 이번 질문에 실제로 돌아온 근거(pool)로 인용을 검증한다 — 옛 agent.py
콜백 대신(run_agent가 패키지 콜백을 자기 것으로 덮음), 질문마다 새 pool이라 옛 턴 경계 문제도 없다.
답·상태·인용·인용 검증·모델/도구 호출 수·토큰·지연을 화면과 output/eval/answer_gen/<시각>.jsonl에 남기고 끝에 지연 p50/p95·상태
분포를 낸다. 채점은 안 함(사람이 읽고 검토). query_edw로 답한 행은 verify가 실패하고 verify_note로 그 이유를 적는다(C-56 — 지금대로 둠).

  PYTHONPATH=$PWD SETTINGS_FILE=<덮기 파일> python -m validation.e2e.answer_gen --url http://127.0.0.1:18767/mcp \\
      [--q "질문" ...] [--file 질문.txt|.jsonl] [--repeat N] [--concurrency N] [--k 5] [--timeout 180] [--fake]
질문을 안 주면 rag_qa/cases.json. 모델·키·상한은 settings.yaml common 절(LLM_* — 외부 모델이면 guard가 두 잠금·예산·범위를 그대로
봄), MCP 토큰은 로컬 mcp.server.token(있으면 Bearer — --url이 토큰이 다른 MCP면 401, VS10 P-3). --fake: 모델 없이 결정적 정책
(search → verify_citations → 답)으로 도구·MCP 경로만 확인(LLM_FAKE를 이 프로세스에만 켬 — 이 프로세스의 네트워크는 MCP만. MCP 서버가
외부 질의 임베딩을 부르면 그 비용은 MCP 쪽 장부에 남고 끝의 "장부 합계"에는 안 잡힘, VS10 P-1).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from common.core.paths import APP_ROOT, resolve_agent_dir

AGENT_ID = "rag_qa"
MCP_TOOLS = ("search", "edw_meta", "query_edw")  # 지금 검색 MCP 도구 중 QA가 쓰는 것(옛 6개 — aggregate 등은 search 근거로 흡수)
STOPS = {"예산 초과": "stopped_budget", "공유 호출 상한": "stopped_calls", "시간 상한": "stopped_time"}  # run_agent의 정상 멈춤 글자
#   ("공유 호출 상한" = 턴마다 장부 admit 거부 — LLM_MAX_CALLS와 LLM_BUDGET_USD 둘 다 · "예산 초과" = 매니페스트 턴·토큰 예산, VS10 L-3)
EDW_NOTE = (
    "이 답은 query_edw를 씀 — EDW 값은 인용 검증 대상이 아니라(pool은 search 근거만, 모델이 쓴 SQL은 근거가 못 됨 — "
    "refactor.md C-56) 수치·인용 실패가 EDW 값 때문일 수 있음: problems를 보고 판단"
)
_EVIDENCE_KEYS = ("doc_key", "chunk_key", "file_name", "page", "via", "score", "client", "text")  # 모델에 보이는 근거 칸(토큰 줄임)


def _verify_citations():
    """rag_qa 패키지의 verify_citations 함수 — 패키지는 valid_env/answer_test/rag_qa(파이썬 패키지 아님 · 10-29)라 파일 경로로 읽는다."""
    import importlib.util

    path = resolve_agent_dir(AGENT_ID) / "verify_citations.py"
    spec = importlib.util.spec_from_file_location(f"{AGENT_ID}_verify_citations", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.verify_citations


def _payload(res):
    """MCP CallToolResult → dict(오류면 {"error": 글자})."""
    text = "".join(getattr(c, "text", "") or "" for c in res.content or [])
    if res.isError:
        return {"error": text[:500]}
    if res.structuredContent is not None:
        return res.structuredContent
    try:
        out = json.loads(text)
    except ValueError:
        return {"text": text}
    return out if isinstance(out, dict) else {"result": out}


async def _mcp(url, token, name, args=None):
    """MCP 한 번(세션을 열어 부르고 닫음) — name이 None이면 tools/list → {이름: Tool}."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    hdr = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamablehttp_client(url, headers=hdr) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            if name is None:
                return {t.name: t for t in (await s.list_tools()).tools}
            return _payload(await s.call_tool(name, args or {}))


async def _mcp_tool(url, token, name, args):
    """도구 한 번 — 연결·전송 오류도 {"error"}로 모델에 돌려준다(질문 전체를 멈추지 않게 — 도구 오류와 같은 꼴).
    호출마다 세션을 새로 열어 지연(p50/p95)에 연결·initialize가 들어간다 — PC 점검 규모라 단순함을 택함."""
    try:
        return await _mcp(url, token, name, args)
    except Exception as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:  # anyio TaskGroup이 감싼 진짜 원인
            exc = exc.exceptions[0]
        return {"error": f"MCP 호출 실패 — {type(exc).__name__}: {str(exc)[:200]}"}


def record_evidence(pool, result):
    """search 결과의 근거("evidence" — text 있는 dict)를 pool에 쌓는다(verify_citations 대조용). 집계 근거도 search가 evidence 안에
    via="aggregate"·text "[집계] …"로 넣으므로 같은 길(옛 agent.py는 따로 있던 aggregate 도구의 표 결과도 받았음 — 지금은 없음)."""
    if isinstance(result, dict) and isinstance(result.get("evidence"), list):
        pool.extend(e for e in result["evidence"] if isinstance(e, dict) and e.get("text"))


def _for_model(result):
    """모델에 돌려줄 search 결과 — 근거 칸만 줄이고(_EVIDENCE_KEYS) 나머지 칸(notes·집계 등)은 그대로."""
    if not isinstance(result, dict) or not isinstance(result.get("evidence"), list):
        return result
    ev = [{k: e.get(k) for k in _EVIDENCE_KEYS if e.get(k) not in (None, "", [])} for e in result["evidence"] if isinstance(e, dict)]
    return {**{k: v for k, v in result.items() if k not in ("evidence", "images", "subs", "methods", "ms")}, "evidence": ev}


def verify(answer_json, pool):
    """rag_qa verify_citations + 인용 항목 형식 — 객체가 아닌 인용(글자 등)은 problems로(VS10 L-1 — 그냥 두면 숫자 없는 답이 ok.
    패키지 파일은 지시서 지문을 지키려고 안 고침, S11). 모델 도구와 최종 행 검증이 같이 씀. answer_json = JSON 글자 또는 이미 읽은 객체.
    format_error = 답 모양(객체·JSON 값·citations 목록·인용 항목) 문제 — found 답의 인용 0건은 EDW 답일 수 있어 넣지 않음 — 근거 대조 실패와 가름(VS11 CR-2)."""
    _verify = _verify_citations()
    try:  # 객체로 넘긴 인자는 다시 직렬화·파싱하지 않음(VS11 CR-1·VS11b CR-7)
        data = json.loads(answer_json) if isinstance(answer_json, (str, bytes, bytearray)) else answer_json
    except ValueError:
        data = None
    if not isinstance(data, dict):  # 패키지는 assert로 가려 python -O에서 빠짐(VS11b CR-6) — 여기서 먼저
        return {"ok": False, "problems": ["answer_json must be a JSON object"], "format_error": True}
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):  # JSON으로 못 바꾸는 값(VS11b CR-5 — TypeError로 질문이 멈추지 않게)
        return {"ok": False, "problems": ["answer_json must hold JSON values only"], "format_error": True}
    out = _verify(text, pool)
    cites = data.get("citations")
    bad = [c for c in cites if not isinstance(c, dict)] if isinstance(cites, list) else []
    if bad:
        out = {**out, "ok": False, "problems": [*out.get("problems", []), f"citations 항목은 객체여야 함: {len(bad)}개"]}
    return {**out, "format_error": not isinstance(cites, list) or bool(bad)}


def make_tools(call, contracts, pool, k_default):
    """run_agent에 넘길 도구 {이름: 함수}(패키지 local_tools와 같은 이름 집합). call(name, args) = MCP 부르기(코루틴)."""
    _verify = _verify_citations()

    async def search(question: str, k: int = k_default, client: str = "", source_system: str = "", project_id: str = "") -> dict:
        args = {
            "question": question,
            "k": k,
            **{n: v for n, v in (("client", client), ("source_system", source_system), ("project_id", project_id)) if v},
        }
        res = await call("search", args)
        record_evidence(pool, res)
        return _for_model(res)

    async def edw_meta(schema: str = "", table: str = "", column_filter: str = "") -> dict:
        return await call("edw_meta", {n: v for n, v in (("schema", schema), ("table", table), ("column_filter", column_filter)) if v})

    async def query_edw(sql: str, max_rows: int = 200) -> dict:
        return await call("query_edw", {"sql": sql, "max_rows": max_rows})

    def verify_citations(answer_json: str = "", answer: str = "", status: str = "", citations: list | None = None) -> dict:
        # 모델이 answer_json 대신 답 칸을 펼쳐 넘겨도 서명 TypeError 없이 같은 검사(VS11b CR-7)
        if not answer_json and (answer or status or citations is not None):
            return verify({"answer": answer, "status": status, "citations": citations}, pool)
        return verify(answer_json, pool)

    verify_citations.__doc__ = _verify.__doc__
    for fn in (search, edw_meta, query_edw):
        fn.__doc__ = contracts[fn.__name__].description  # MCP 계약 설명 그대로(모델이 보는 도구 설명)
    return {fn.__name__: fn for fn in (search, edw_meta, query_edw, verify_citations)}


def fake_policy(question):
    """--fake — search 한 번 → 첫 근거 인용으로 verify_citations → 그 JSON을 답으로(근거가 없으면 not_found)."""

    def policy(results):
        if not results:
            return "call", "search", {"question": question, "k": 3}
        ev = (results[0][1].get("evidence") or [])[:1]
        cand = json.dumps(
            {
                "answer": "[FAKE] 근거 첫 조각",
                "status": "found" if ev else "not_found",
                "citations": [
                    {
                        "doc_key": e.get("doc_key"),
                        "chunk_key": e.get("chunk_key"),
                        "page": e.get("page"),
                        "quote": str(e.get("text") or "")[:40],
                    }
                    for e in ev
                ],
            },
            ensure_ascii=False,
        )
        if len(results) == 1:
            return "call", "verify_citations", {"answer_json": cand}
        return "text", cand

    return policy


def final_json(text):
    """최종 답 JSON — 지시대로 객체 하나면 그대로, 모델이 설명문·코드펜스·여러 블록을 붙였으면 status 칸이 있는 마지막 객체
    (llm.parse_json은 첫 "{"~마지막 "}"이라 블록이 둘이면 깨짐 — S10 실호출). 없으면 ValueError."""
    dec, found = json.JSONDecoder(), None
    for pos in (n for n, ch in enumerate(text) if ch == "{"):
        try:
            obj, _ = dec.raw_decode(text, pos)
        except ValueError:
            continue
        if isinstance(obj, dict) and "status" in obj:
            found = obj
    if found is None:
        raise ValueError("JSON 없음")
    return found


def ask_one(i, q, n, url, token, contracts, k, fake, timeout):
    from google.genai import types

    from common.ai import adk

    pool = []
    tools = make_tools(lambda name, args: _mcp_tool(url, token, name, args), contracts, pool, k)
    t0 = time.perf_counter()
    row = {"i": i, "question": q}
    try:
        text, traj, usage = adk.run_agent(
            AGENT_ID,
            types.Content(role="user", parts=[types.Part.from_text(text=q)]),
            role="llm",
            tools=tools,
            timeout=timeout,
            per_turn_admit=True,
            fake_policy=fake_policy(q) if fake else None,
        )
        row.update(
            run_status=STOPS.get(text.strip(), "ok"),
            model_calls=usage.get("model_calls", 0),
            tool_calls=usage.get("tool_calls", 0),
            tokens=usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            tools_used=[t["tool"] for t in traj],
        )
        try:
            out = final_json(text)
            row.update({k2: out.get(k2) for k2 in ("answer", "status", "citations")})
            row["verify"] = verify(out, pool)  # 최종 답을 이번 근거로 다시 검증(결정적)
            if "query_edw" in row["tools_used"] and not row["verify"]["ok"] and not row["verify"]["format_error"]:
                row["verify_note"] = EDW_NOTE  # 모양 오류는 EDW와 무관(VS11 CR-2 — problems 글 머리가 아니라 format_error로 가름)
        except ValueError:
            row["raw_output"] = text
            if row["run_status"] == "ok":
                row["run_status"] = "no_json"  # 답 JSON이 없음 — 상태 분포에서 성공으로 세지 않게
    except Exception as exc:  # 한 질문 실패가 다른 질문을 멈추지 않게
        row.update(run_status="failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    row["sec"] = round(time.perf_counter() - t0, 2)
    v = row.get("verify") or {}
    print(
        f"\n[{i}/{n}] {q}\n  상태 {row.get('status') or row['run_status']} · {row['sec']}s · 모델 {row.get('model_calls', 0)} · "
        f"도구 {row.get('tool_calls', 0)} {row.get('tools_used', '')} · 인용 검증 {'통과' if v.get('ok') else v.get('problems', '-')}"
        f"{' · ' + row['verify_note'] if row.get('verify_note') else ''}"
        f"{' · 오류 ' + row['error'] if row.get('error') else ''}\n  답: {row.get('answer', row.get('raw_output'))}",
        flush=True,
    )
    cites = row.get("citations")
    for c in cites if isinstance(cites, list) else [cites]:  # 모델이 형식을 어겨도(글자 목록 등) 출력에서 멈추지 않게(VS10 M-2)
        if isinstance(c, dict):
            print(f"  - 인용 {c.get('doc_key')} p{c.get('page')}: {str(c.get('quote'))[:120]}", flush=True)
        elif c is not None:
            print(f"  - 인용(형식 아님) {str(c)[:120]}", flush=True)
    return row


def load_questions(a):
    qs = list(a.q)
    if a.file:
        for line in Path(a.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                qs.append(json.loads(line)["question"] if line.startswith("{") else line)
    if not qs:
        cases = json.loads((resolve_agent_dir(AGENT_ID) / "cases.json").read_text(encoding="utf-8"))
        qs = [c["turns"][0]["input"] for c in cases]
    return qs * a.repeat


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True, help="검색 MCP 주소(…/mcp) — PC 검증 페이지 MCP는 http://127.0.0.1:18767/mcp")
    ap.add_argument("--q", action="append", default=[], help="질문(여러 번)")
    ap.add_argument("--file", help='질문 파일 — 줄마다 질문 또는 {"question":…} jsonl')
    ap.add_argument("--concurrency", type=int, default=2, help="동시에 돌릴 질문 수")
    ap.add_argument("--repeat", type=int, default=1, help="질문 목록 반복(부하 시험)")
    ap.add_argument("--k", type=int, default=5, help="search 기본 k(모델이 바꿀 수 있음)")
    ap.add_argument("--timeout", type=float, default=180, help="질문 하나의 시간 상한(초 — run_agent)")
    ap.add_argument("--fake", action="store_true", help="모델 없이 결정적 정책으로 도구·MCP 경로만(LLM_FAKE)")
    if not (argv if argv is not None else sys.argv[1:]):
        ap.print_help()
        raise SystemExit(2)
    a = ap.parse_args(argv)
    qs = load_questions(a)
    if not qs:
        raise SystemExit("질문이 없음 — --q·--file을 주거나 --repeat을 1 이상으로")

    from common.ai import guard as G
    from common.ai.llm import profile
    from common.config import settings
    from mcp_server import config as mc

    if a.fake:
        settings.put(LLM_FAKE="1")
    else:
        prof = profile("llm")
        if prof is None:
            raise SystemExit("LLM 모델 설정 없음 — settings.yaml common.models.llm(base_url·model·api_key) 또는 --fake")
        G.check_scope([prof.base_url], n_combos=1, n_questions=len(qs))  # 외부 모델 범위 가드(옛과 같음 — 예산 없으면 거부)
    token = mc.token_text(mc.cfg().server.token)  # 공백만이면 토큰 없음(C-42·C-44) — 출력하지 않음
    contracts = asyncio.run(_mcp(a.url, token, None))
    missing = [n for n in MCP_TOOLS if n not in contracts]
    if missing:
        raise SystemExit(f"MCP tools/list에 없음: {missing}")

    out_dir = APP_ROOT / "output" / "eval" / "answer_gen"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    t0 = time.perf_counter()
    with out.open("w", encoding="utf-8") as f, ThreadPoolExecutor(max(1, a.concurrency)) as ex:
        futs = [ex.submit(ask_one, i, q, len(qs), a.url, token, contracts, a.k, a.fake, a.timeout) for i, q in enumerate(qs, 1)]
        rows = []
        for fut in futs:
            rows.append(fut.result())
            f.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
            f.flush()
    secs = sorted(r["sec"] for r in rows)
    p95 = secs[min(len(secs) - 1, int(round(0.95 * (len(secs) - 1))))]
    print(
        f"\n== {len(rows)}건 · 동시 {a.concurrency} · 전체 {time.perf_counter() - t0:.1f}s · 지연 p50 "
        f"{statistics.median(secs):.1f}s / p95 {p95:.1f}s · 상태 {dict(Counter(str(r.get('status') or r['run_status']) for r in rows))} · "
        f"모델 호출 {sum(r.get('model_calls', 0) for r in rows)} · 장부 합계 ${G.spend_total():.4f}"
    )
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
