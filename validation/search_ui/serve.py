"""검증 페이지 서버 — index.html을 내주고, 브라우저 요청을 검색 MCP와 pgvector로 넘긴다(로컬 전용, 127.0.0.1).

브라우저가 MCP(streamable HTTP)에 바로 붙으면 CORS·세션 처리가 번거로워서, 이 서버가 mcp 클라이언트로 대신 부른다.
새 패키지 없음: 표준 라이브러리 + 저장소 .venv에 이미 있는 mcp·psycopg.

  GET  /                  index.html
  GET  /api/health        MCP /health + 예산 장부(LLM_SPEND_FILE) + 설정 요약(비밀 제외)
  GET  /api/tools         MCP 도구 목록·입력 스키마
  POST /api/call          {"tool": "search", "args": {...}} → MCP 응답 JSON 그대로 + 걸린 시간
  GET  /api/chunk/<id>    pgvector에서 그 청크의 벡터(차원·L2 크기·값 분포)와 코사인으로 가까운 청크 — SQL만, 외부 호출 없음

설정은 저장소 루트 settings.yaml 하나: mcp.dev.mcp_url·ui_port ·
common.connections.pg · common.models.guard.spend_file·budget_usd · common.tokens.mcp.
"""

import asyncio
import json
import math
import re
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # 저장소 루트 — 설정 객체(common·mcp_server)를 읽으려고
from common.config.settings import cfg  # noqa: E402 — 설정 객체
from mcp_server import config as mc  # noqa: E402

_PG = cfg().connections.pg
MCP_URL = mc.cfg().dev.mcp_url  # 값은 설정에만(기본값은 설정 모델)
UI_PORT = int(mc.cfg().dev.ui_port)
SCHEMA = _PG.db_schema or ""  # 비우면 코드 기본값(data_parsing) — 빈 글자를 적었을 때만 아래에서 멈춤
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SCHEMA):
    sys.exit(f"PG_SCHEMA 이름이 이상함: {SCHEMA!r}")


def _health_url():
    return MCP_URL.rsplit("/mcp", 1)[0] + "/health"


async def _mcp(fn):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    hdr = {"X-MCP-Client": "test", "X-MCP-User": "test"}
    token = mc.token_text(mc.common_cfg().tokens.mcp)
    if token:
        hdr["Authorization"] = "Bearer " + token
    async with streamablehttp_client(MCP_URL, headers=hdr) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await fn(s)


def mcp_tools():
    async def f(s):
        return [
            {"name": t.name, "description": (t.description or "")[:600], "input_schema": t.inputSchema}
            for t in (await s.list_tools()).tools
        ]

    return asyncio.run(_mcp(f))


def mcp_call(tool, args):
    async def f(s):
        res = await s.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            return json.loads(text)
        except ValueError:
            return {"raw": text}

    t0 = time.monotonic()
    out = asyncio.run(_mcp(f))
    return {"result": out, "ui_ms": round((time.monotonic() - t0) * 1000)}


def spend():
    from common.ai import guard as G

    used = G.spend_total()  # 오늘(현지 날짜) 장부 합계 — 상한은 하루 단위
    budget = cfg().models.guard.budget_usd
    return {"used_usd": used, "budget_usd": float(budget) if budget is not None else None}


def health():
    out = {
        "mcp_url": MCP_URL,
        "spend": spend(),
        "config": {
            "EMBED_MODEL": cfg().models.embed.model,
            "EMBED_ALLOW_EXTERNAL": cfg().models.embed.allow_external,  # 꺼져 있으면 질의 임베딩 없음(키워드·ID만)
            "PG_HOST": _PG.host,
            "PG_PORT": _PG.port,
            "PG_SCHEMA": _PG.db_schema,
        },
        "vlm_configured": bool(cfg().models.vlm.base_url),
        "llm_configured": bool(cfg().models.llm.base_url),
    }
    try:
        with urllib.request.urlopen(_health_url(), timeout=5) as r:
            out["mcp"] = json.loads(r.read())
    except Exception as e:  # 503(예열 중)·연결 거부 모두 화면에 그대로 보여 줌
        out["mcp"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


def _pg():
    import psycopg

    from common.store.pg import conf

    try:
        c = conf()  # 본 코드와 같은 접속 값(빈 칸이면 채울 자리를 적고 거부)
    except SystemExit as e:  # 요청 처리기는 Exception만 받아 502로 — 스레드가 조용히 죽지 않게
        raise RuntimeError(str(e)) from None
    return psycopg.connect(
        host=c["PG_HOST"],
        port=int(c["PG_PORT"]),
        dbname=c["PG_DB"],
        user=c["PG_USER"],
        password=c["PG_PASSWORD"],
        connect_timeout=5,
    )


def _parse_vec(text):
    return [float(x) for x in text.strip("[]").split(",") if x]


def chunk_detail(chunk_id, n_neighbors=5, buckets=128):
    s = SCHEMA
    with _pg() as cn:
        row = cn.execute(
            f"""SELECT c.chunk_id, c.embed_model, vector_dims(c.embedding), c.embedding::text,
                       c.chunk_text, c.n_chars, c.page, c.line_start, c.line_end, d.file_path
                FROM {s}.chunk c JOIN {s}.doc d ON d.doc_id = c.doc_id
                WHERE c.chunk_id = %s""",
            (chunk_id,),
        ).fetchone()
        if not row:
            return {"error": f"chunk_id {chunk_id} 없음"}
        # 축소 스키마 — doc에 s3_key·file_name이 없어 file_path에서 유도
        (cid, model, dims, vtext, text, n_chars, page, l0, l1, file_path) = row
        s3_key, file_name = file_path, Path(file_path).name
        near = cn.execute(
            f"""SELECT c.chunk_id, regexp_replace(d.file_path, '^.*/', ''), left(c.chunk_text, 140), 1 - (c.embedding <=> t.embedding) AS cos
                FROM {s}.chunk c JOIN {s}.doc d ON d.doc_id = c.doc_id,
                     (SELECT embedding FROM {s}.chunk WHERE chunk_id = %s) t
                WHERE c.chunk_id <> %s AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> t.embedding LIMIT %s""",
            (chunk_id, chunk_id, n_neighbors),
        ).fetchall()
        total = cn.execute(f"SELECT count(*) FROM {s}.chunk WHERE embedding IS NOT NULL").fetchone()[0]
    v = _parse_vec(vtext) if vtext else []
    n = len(v)
    norm = math.sqrt(sum(x * x for x in v)) if v else 0.0
    step = max(1, math.ceil(n / buckets)) if n else 1
    profile = [sum(v[i : i + step]) / len(v[i : i + step]) for i in range(0, n, step)] if v else []
    return {
        "chunk_id": cid,
        "file_name": file_name,
        "s3_key": s3_key,
        "page": page,
        "lines": f"{l0}-{l1}" if l0 is not None else None,
        "n_chars": n_chars,
        "text": text,
        "embed_model": model,
        "dims": dims,
        "l2_norm": round(norm, 6),
        "min": round(min(v), 6) if v else None,
        "max": round(max(v), 6) if v else None,
        "mean": round(sum(v) / n, 6) if v else None,
        "head": [round(x, 5) for x in v[:16]],
        "profile": [round(x, 6) for x in profile],
        "profile_step": step,
        "neighbors": [{"chunk_id": a, "file_name": b, "text": c, "cosine": round(float(d), 4)} for a, b, c, d in near],
        "total_chunks": total,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "validation-ui/1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[ui] " + (fmt % args) + "\n")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        """127.0.0.1에서만 — 다른 주소에서 온 요청은 거부(이 서버는 비밀이 든 env로 돈다)."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._send(403, {"error": "local only"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        try:
            if self.path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/health":
                return self._send(200, health())
            if self.path == "/api/tools":
                return self._send(200, {"tools": mcp_tools()})
            m = re.fullmatch(r"/api/chunk/(\d+)", self.path)
            if m:
                return self._send(200, chunk_detail(int(m.group(1))))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(502, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self._guard():
            return
        if self.path != "/api/call":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            tool, args = req.get("tool"), req.get("args") or {}
            if tool not in ("search", "search_in_documents", "query_edw"):
                return self._send(400, {"error": f"모르는 도구: {tool}"})
            out = mcp_call(tool, args)
            out["spend"] = spend()
            self._send(200, out)
        except Exception as e:
            self._send(502, {"error": f"{type(e).__name__}: {e}"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", UI_PORT), Handler)
    print(f"[ui] http://127.0.0.1:{UI_PORT}  →  MCP {MCP_URL} · pgvector {_PG.host}:{_PG.port}/{SCHEMA}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
