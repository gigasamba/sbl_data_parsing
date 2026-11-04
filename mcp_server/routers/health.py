"""GET /health 등록 — 토큰 없이(컨테이너 헬스체크용) 프로세스·준비 여부·적재 버전만(본문은 server_state.health_body).
예열 중이면 503.
"""

from mcp_server.services.search.server_state import health_body


def register(app):
    from starlette.responses import JSONResponse

    async def health(request):  # 토큰 없이(컨테이너 헬스체크용) — 프로세스·준비 여부·적재 버전만
        body = health_body()
        return JSONResponse(body, status_code=503 if body.get("warming") else 200)  # 예열 중엔 not-ready

    app.add_route("/health", health, methods=["GET"])
