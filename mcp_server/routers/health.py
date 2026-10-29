"""GET /health 등록 — 토큰 없이(컨테이너 헬스체크용) 프로세스·준비 여부·적재 버전만(본문은 server_state._health).
S5(10-26, refactor_plan 5-1 routers/ — 코디네이터 답 Q5 a)에 mcp_server/main.py build() 안에서 옮김 — 응답 모양·상태 코드 그대로(MC1 — 예열 중 503).
"""

from mcp_server.services.search.server_state import _health


def register(app):
    from starlette.responses import JSONResponse

    async def health(request):  # 토큰 없이(컨테이너 헬스체크용) — 프로세스·준비 여부·적재 버전만
        body = _health()
        return JSONResponse(body, status_code=503 if body.get("warming") else 200)  # MC1 — 예열 중엔 not-ready

    app.add_route("/health", health, methods=["GET"])
