#!/usr/bin/env python3
"""검색 MCP 바깥 호출 점검 — 컨테이너 밖(호스트·다른 서버)에서 HTTP로 붙어 도구 목록·search.
사용: python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:18765/mcp --source <원천> [--token <MCP_TOKEN>] [--q "질문"]
통과 기준: 도구 목록이 mcp_server.routers.TOOL_NAMES(지금 MCP 계약 6종 — search·query_edw·parse_document·edw_meta·list_doc_fulltext·
get_doc_fulltext, 0.2.0)와 같음 · search(원천 하나 — source_system 필수) 근거 1건+ · 근거마다 schemas.evidence.EVIDENCE_KEYS 칸 그대로,
chunk_key·file_path 값 있음. 그 밖 도구는 회사 DB·파싱 서비스·저장소가 있어야 해서 목록만 본다.
실패면 종료 코드 1."""

import argparse
import asyncio
import json

from common.core.console import utf8_stdout
from mcp_server.routers import TOOL_NAMES
from mcp_server.schemas.evidence import EVIDENCE_KEYS

TOOLS = set(TOOL_NAMES)  # 서버가 등록하는 이름 한 곳(routers.TOOL_NAMES — main.build와 시험이 대조)


def check_search(d):
    """search 응답(dict) → 실패 이유 목록(비면 통과). 근거 칸은 계약(EVIDENCE_KEYS) 그대로여야 한다."""
    if d.get("error"):
        return [f"search 오류: {d['error']}"]
    ev = d.get("evidence") or []
    if not ev:
        return ["근거 0건"]
    if any(not isinstance(e, dict) or tuple(e) != EVIDENCE_KEYS or not (e.get("chunk_key") and e.get("file_path")) for e in ev):
        return [f"근거 칸이 계약({len(EVIDENCE_KEYS)}칸)과 다르거나 chunk_key·file_path 빠짐"]
    return []


async def run(url, token, q, source):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    hdr = {"X-MCP-Client": "smoke"} | ({"Authorization": f"Bearer {token}"} if token else {})
    bad = []
    async with streamablehttp_client(url, headers=hdr) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            print("도구:", tools)
            if set(tools) != TOOLS:
                bad.append(f"도구 {len(TOOLS)}종({', '.join(TOOL_NAMES)})과 다름")
            res = await s.call_tool("search", {"question": q, "k": 5, "source_system": source})
            text = res.content[0].text if res.content else ""
            try:
                d = json.loads(text)
            except ValueError:  # 도구 오류는 JSON이 아닌 글자로 옴 — 트레이스백 대신 그 글자 앞부분을 실패 이유로
                bad.append(f"search 응답이 JSON이 아님(isError={res.isError}): {text[:300]!r}")
                return bad
            ev = d.get("evidence") or []
            print(f"search: 원천 {source} · 근거 {len(ev)}건 · 상태 {d.get('evidence_status')}")
            for e in ev[:3]:
                print(f"  - {e.get('file_name')} p.{e.get('page')} L.{e.get('line')} · {e.get('file_path')}")
            bad += check_search(d)
    return bad


def main(argv=None):
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="MCP 주소 — 비우면 설정 mcp.dev.mcp_url")
    ap.add_argument("--token", default=None, help="비우면 설정 required.tokens.mcp_token(명령 줄은 ps·로그에 남음 — 서버 안에서는 비워 둠)")
    ap.add_argument("--q", default="계약 단가")
    ap.add_argument(
        "--source", required=True, help="원천 하나(SFDC·CRMS·LAS·FAQ·Other, 개발 서버는 DEV-<숫자>도 — search의 source_system과 같음)"
    )
    a = ap.parse_args(argv)
    if not a.url or a.token is None:  # 주소·토큰(토큰 없는 서버는 --token "")을 둘 다 주면 설정 파일 없이도(호스트·다른 서버에서 부름)
        from mcp_server import config as mc

        a.url = a.url or mc.cfg().dev.mcp_url
        if a.token is None:
            a.token = mc.token_text(mc.common_cfg().tokens.mcp) or ""
    bad = asyncio.run(run(a.url, a.token, a.q, a.source))
    print("MCP 바깥 호출 통과" if not bad else "실패: " + " · ".join(bad))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
