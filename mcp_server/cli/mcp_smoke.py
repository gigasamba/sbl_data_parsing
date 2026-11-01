#!/usr/bin/env python3
"""검색 MCP 바깥 호출 점검 — 컨테이너 밖(호스트·다른 서버)에서 HTTP로 붙어 도구 목록·search.
사용: python -m mcp_server.cli.mcp_smoke --url http://127.0.0.1:18765/mcp [--token <MCP_TOKEN>] [--q "질문"]
통과 기준: 도구 4종(search·query_edw·parse_document·edw_meta — 지금 MCP 계약, S9 C-38 — 옛 5종 get_document·get_image·get_evidence_image·aggregate는
없어짐) · search 근거 1건+ · 근거마다 doc_key·chunk_key·source_uri. query_edw·edw_meta·parse_document는 회사 DB·파싱 서비스가 있어야 해서 목록만 본다.
실패면 종료 코드 1."""

import argparse
import asyncio
import json
import sys

TOOLS = {"search", "query_edw", "parse_document", "edw_meta"}


async def run(url, token, q):
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
                bad.append(f"도구 4종({', '.join(sorted(TOOLS))})과 다름")
            res = await s.call_tool("search", {"question": q, "k": 5})
            text = res.content[0].text if res.content else ""
            try:
                d = json.loads(text)
            except ValueError:  # 도구 오류는 JSON이 아닌 글자로 옴 — 트레이스백 대신 그 글자 앞부분을 실패 이유로
                bad.append(f"search 응답이 JSON이 아님(isError={res.isError}): {text[:300]!r}")
                return bad
            ev = d.get("evidence") or []
            print(f"search: 저장소 {d.get('store')} · 근거 {len(ev)}건 · notes {d.get('notes')}")
            for e in ev[:3]:
                print(
                    f"  - {e.get('file_name')} p.{e.get('page')} via {e.get('via')} · doc_key {str(e.get('doc_key'))[:12]}… · {e.get('source_uri')}"
                )
            if not ev:
                bad.append("근거 0건")
            elif any(
                not (e.get("doc_key") and e.get("chunk_key") and e.get("source_uri")) for e in ev if e.get("chunk_key") or e.get("doc_key")
            ):
                bad.append("근거에 doc_key·chunk_key·source_uri 빠짐")
    return bad


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="MCP 주소 — 비우면 설정 mcp.dev.mcp_url")
    ap.add_argument("--token", default="")
    ap.add_argument("--q", default="계약 단가")
    a = ap.parse_args()
    if not a.url:  # 주소를 주면 설정 파일 없이도(호스트·다른 서버에서 부름)
        from mcp_server import config as mc

        a.url = mc.cfg().dev.mcp_url
    bad = asyncio.run(run(a.url, a.token, a.q))
    print("MCP 바깥 호출 통과" if not bad else "실패: " + " · ".join(bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
