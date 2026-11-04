#!/usr/bin/env python3
"""검색 MCP — 질문 하나로 근거(원문·원본 경로·쪽·위치·그림)를 돌려주는 한 창구(백로그 G1~G5). 답변 생성은 클라이언트(GLM 등) 몫.

도구(G2):
  search(question, k=8, 거르기 13칸 + attrs — pl-52) — 11-01(mc-16, 등급 A) 운영 계약: question 필수(비면 {"error"}) · k 기본 8·상한 50 ·
    거르기 source_system·client(+client_like)·project_id·division·service_type·FAQ_group·doc_class·sf_op_id·sf_op_name·contract_id·
    created_since/created_until(모두 AND, 같은 거르기의 목록은 OR, 맞는 것이 없으면 빈 결과) · 거르기에 맞는 문서(v_chunk_source) 범위 안에서만
    하이브리드 검색(vector·bm25·id — 서버 설정만) · 응답 {question, evidence[13칸 — attrs 포함], evidence_status, filter, scope_docs}
    (mcp_server/schemas/evidence.py). 덤프 방식·이름 있는 색인(index_id)·옛 입력(methods·decompose·limit)·옛 출력(subs·store·images·notes·ms)은 지움.
  MCP 노출 도구는 search·query_edw·parse_document·edw_meta·list_doc_fulltext·get_doc_fulltext(2026-10-20 사용자 결정 · 10-21 파싱 도구 · 11-01 원문 도구 mc-17).
  (EQ1, English docstrings per 10-15 user rule)
  query_edw(sql, max_rows=1000) Read-only SQL against EDW: SELECT/WITH only, one statement, table allowlist
    (EDW_QUERY_TABLES), row/time/response-size caps. Returns raw rows only — no summarization, the
    calling agent does its own post-processing. See mcp_server/services/edw_query.py for the full guard.
  (2026-10-21 사용자 요청·같은 날 단일화) parse_document(path, content_b64, filename, time_out_threshold=300, max_chars=200000) —
    비정형 파일 1건의 text 파싱 대표 결과: data-pipeline-mcp 컨테이너(11-03 — 옛 data-pipeline-parse)의 작업 서비스(PARSE_URL, 기본 http://127.0.0.1:8766 ·
    그 컨테이너의 주 프로세스 — 토큰은 그 컨테이너 settings.yaml required.tokens.parse_mcp)가
    prepare → run_all( phase 1·2만 — 그림[VLM] 파싱은 phase 3이라 실행 안 됨, 표 인식 유지) → parse_qa → represent(대표 결과)만
    수행(구조화·임베딩·EDW/OS 적재 없음). path는 허용 루트(/app/output/mcp_parse/inbox) 하위만(jail) · 파일 상한 100MB(path·content_b64 같음 — ops.runtime.parse_max_mb, 11-03) ·
    time_out_threshold(기본 300초) 안에 끝나야 결과를 돌려주고 못 끝내면 {"error": "시간 안에 수행 못했습니다", "job_id": …}만 반환 —
    노출 도구는 parse_document 하나뿐(사용자 결정: 결과 수령 도구 parse_result는 등록하지 않는다), 이 도구만 MCP_TOOL_TIMEOUT_SEC(기본 30초)
    대신 자체 예산으로 기다린다(_bg_long) · 응답 text는 max_chars(기본 20만자) 상한(초과 시 잘리고 text_truncated, 전체는 rep_path 파일에).
  (EM1, English docstrings per 10-15 user rule)
  edw_meta(schema, table=None, column_filter=None) — EDW 테이블·컬럼 한글 메타데이터 3단 계층 조회(정적 데이터셋, 2026-10-22 사용자 결정):
    인자 없음 → 스키마 5개 요약 · schema만 → 그 스키마 전체 테이블 메타(컬럼 제외) · schema+table → 그 테이블 전체 컬럼 한글 설명.
    벡터·임베딩·LLM·pgvector 불개입(rule-based — 비-RAG 원칙) · 데이터는 EDW_META_DIR(기본 /app/config/edw_meta)의
    catalog.json+columns.jsonl, mtime 재확인(기본 30초)으로 재빌드 반영 · sample_values는 어떤 응답에도 실리지 않음 ·
    도구 파일·데이터셋 부재 시 {"error": …} fail-soft(모듈 import는 do_edw_meta 안 lazy — 서버 부팅·기존 도구 계속).
저장소: common/store/pg.py connect(설정의 PostgreSQL — 없으면 거부, --local이면 로컬 묶음), 임베딩·LLM은 .env 내부망 주소만.

보안(G5): MCP_HOST(기본 127.0.0.1 · auto = 컨테이너 자기 사설 IP)는 내부망 주소만 · 루프백이 아니면 MCP_TOKEN 필수(Authorization: Bearer) ·
  루프백이 아니면 DNS 리바인딩 보호도 기본 켬(L8 — SDK TransportSecuritySettings, MCP_HOST[+포트]만 자동 허용 · 어긋난
  Host는 421·Origin은 403 · MCP_ALLOWED_HOSTS(쉼표 목록)로 추가 호스트) ·
  호출자(X-MCP-Client 머리글)는 질의 기록(qa_log.jsonl)의 asked_by에 'mcp:<호출자>'로 · 결과 크기 상한 MCP_MAX_CHARS(기본 20000자).
질의 기록(OP6): 호출자·질문·근거 chunk_id·rank·via·지연을 output/qa_log/qa_log.jsonl에 기록(PG 없는 로컬 묶음도, common/qa_log.py) —
  기본 켬, MCP_QUERY_LOG=0으로 끔. 90일 지난 줄은 기동 때 또는 마지막 정리 이후 24시간 지나면 지운다. 토큰·원문은 안 남김.
동시 접속(S12): 도구는 스레드로 돌림(MCP_MAX_CONCURRENCY 기본 8) · PG는 연결 풀(PG_POOL_MAX 기본 8) · GET /health(토큰 없이, 프로세스·준비 여부·적재 버전 ·
  MC1 — 기동 때 예열이 백그라운드로 도는 동안은 503 {"warming": true}, 끝나면 200 {"ready": true}, 예열 실패는 200 + {"warning": "warmup_failed"}(서버는 안 죽음),
  MCP_WARMUP=0으로 끔·기본 켬) ·
  load 재실행 뒤 데이터는 최소 MCP_RELOAD_CHECK_SEC(기본 30초) 간격으로 확인해 바뀌었으면 다시 읽음.
과부하 보호(MC2, RV2, 기본 켬): 요청 시간 상한 MCP_TOOL_TIMEOUT_SEC(기본 30초, 넘으면 {"error": "timeout"}) ·
  동시 상한보다 밀린 대기가 대기열 상한 MCP_MAX_QUEUE(기본 동시 상한×4)에 차면 기다리지 않고 바로 {"error": "busy"} ·
  각각 =0이면 그 상한 없음(이전 동작). 호출자별 상한은 안 둠(토큰이 서버 전체 하나뿐이라 호출자 구분이 신뢰 경계가 아님).
실행: python -m mcp_server.main               → HTTP(streamable) http://MCP_HOST:MCP_PORT/mcp (기본 127.0.0.1:8765)
      python -m mcp_server.main --stdio       → 같은 서버의 클라이언트가 프로세스로 띄울 때
파일 배치(S5 10-26, refactor_plan 5-1 — FastMCP 그대로): 이 파일은 앱 조립·토큰·서버 시작만 · 도구 등록 routers/ · 실제 일 services/
(검색 services/search/search_svc.py) · 출력 모양 schemas/ · 시작 때 읽는 설정 config.py(CFG). 위 설명의 함수 이름은 그대로다.
"""

import contextlib
import hmac
import ipaddress
import json
import logging
import sys
import threading

import anyio

from common.core import jsonlog
from common.core.console import utf8_stdout
from mcp_server import config as mc  # 설정 객체(S7d)
from mcp_server.routers import edw_tools, fulltext_tool, health, parse_tool, search_tool  # 도구·/health 등록(5-1)
from mcp_server.services import call_log, parse_proxy
from mcp_server.services.search.server_state import _warmup_bg

_DEFAULT_MCP_INSTRUCTIONS = (
    "CDMO 문서 검색 — search로 근거를 찾는다(하드 필터 조건을 함께 주면 그 범위 안에서 검색, "
    "question 없이 조건만 주면 해당 문서·청크 전체를 돌려준다), query_edw로 EDW 읽기 전용 SQL(SELECT/WITH만)을 실행, "
    "parse_document로 비정형 파일 1건의 text 파싱 대표 결과를 받는다(구조화·적재·그림 파싱 없음·표 인식 포함), "
    "edw_meta로 EDW 테이블·컬럼 한글 메타데이터를 3단 계층으로 조회한다(스키마 → 테이블 목록 → 전체 컬럼, "
    "정적 데이터셋 — SQL 작성 전 qualified_name 확보)."
)


def _mcp_instructions():
    """FastMCP instructions 글자(DT1 c1) — env MCP_INSTRUCTIONS(없으면 코드 기본값, CDMO)."""
    return mc.cfg().server.instructions or _DEFAULT_MCP_INSTRUCTIONS  # S7d — 설정 객체, 호출마다


def _transport_security(host):
    """L8: 비루프백 바인드에서 DNS 리바인딩 보호 켬(기본 ON) — allowed_hosts/origins는 MCP_HOST(와일드카드 포트)
    + MCP_ALLOWED_HOSTS(쉼표 목록, 리버스 프록시 이름 등을 추가할 때만). 어긋난 Host/Origin은 SDK가 421/403으로 거부."""
    from mcp.server.transport_security import TransportSecuritySettings

    extra = list(mc.cfg().server.allowed_hosts)  # S7d — 설정 객체(쉼표 목록 — strip·빈 것 버림)
    hosts = [f"{host}:*"] + extra
    origins = [f"{scheme}://{h}" for h in hosts for scheme in ("http", "https")]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def _sdk_logging():
    """FastMCP가 만들어질 때 root에 거는 기본 처리(INFO, 일반 글자, stderr)를 SDK(mcp.*) 줄에서 끊는다.
    요청마다 나오는 INFO는 감사 행(mcp.call)과 겹치므로 common.log.level이 DEBUG일 때만 남기고, 그 밖의 줄(WARNING 이상,
    예외)은 비밀값을 가린 JSON으로 stderr에 낸다 — stdio의 stdout은 JSON-RPC 전용이고 감사 로그(logs/mcp.jsonl)와도 섞지 않는다."""
    from common.config.settings import cfg

    level = cfg().log.level
    sdk = logging.getLogger("mcp")
    for handler in sdk.handlers[:]:
        sdk.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(jsonlog.JsonFormatter("mcp"))
    sdk.addHandler(handler)
    sdk.setLevel(logging.DEBUG if level == "DEBUG" else max(logging.WARNING, logging.getLevelName(level)))
    sdk.propagate = False  # root의 기본 핸들러로 예외 글이 가림 없이 나가는 길을 막는다


_BIG_BODY = 4 * 1048576  # SDK 기본 본문 상한 — 이보다 큰(또는 길이를 안 밝힌) POST만 동시 수를 묶는다
_BIG_SLOTS = 2  # ponytail: 고정 2개(4g 컨테이너에서 100MB 파일 base64·디코드 사본 기준) — 메모리를 바꾸면 설정 항목으로


# ── MCP 서버 ─────────────────────────────────────────────────────
def build(host, port):
    from mcp.server.fastmcp import FastMCP

    loop = host in ("127.0.0.1", "localhost", "::1")
    m = FastMCP(
        "rag-search",
        instructions=_mcp_instructions(),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        transport_security=None if loop else _transport_security(host),
        max_request_body_size=parse_proxy.body_cap(),  # 11-03 — SDK 기본 4MiB면 parse_document content_b64가 약 3MB에서 413
    )
    _sdk_logging()  # FastMCP가 로깅을 설정한 뒤에 덮는다

    search_tool.register(
        m
    )  # 등록 순서 = tools/list 순서(MCP 계약 바이트) — search · query_edw · parse_document · edw_meta · list/get_doc_fulltext
    edw_tools.register_query_edw(m)
    parse_tool.register(m)
    edw_tools.register_edw_meta(m)
    fulltext_tool.register(m)  # mc-17(11-01)
    return m


def check_bind(host, token):
    """G5: 내부망 주소만 · 루프백이 아니면 토큰 필수."""
    from common.ai.guard import is_internal

    if host in ("0.0.0.0", "::"):
        raise SystemExit("MCP_HOST=0.0.0.0(모든 주소)은 쓰지 않음 — 사내 대역의 이 서버 IP를 지정")
    if not is_internal(f"http://{host}"):
        raise SystemExit(f"MCP_HOST={host}는 내부망 주소가 아님 — 거부")
    try:
        loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loop = host == "localhost"
    if not loop and not token:
        raise SystemExit("루프백이 아닌 주소에 열려면 MCP_TOKEN 필수(클라이언트는 Authorization: Bearer <토큰>)")


def build_guarded_app(host, port, token):
    """serve_http 뼈대 ASGI 앱(health 라우트 + 토큰 검사) — uvicorn은 안 띔(시험용 — in-process ASGI 클라이언트로
    Host/Origin·토큰 규칙을 네트워크 없이 확인, L8). Host/Origin 검증은 build()의 transport_security(SDK 내부)가 함."""
    from starlette.responses import JSONResponse

    app = build(host, port).streamable_http_app()

    health.register(app)

    inner = app
    # 본문 상한(약 151MB)은 /mcp 하나라 모든 도구에 걸림 — 큰 요청은 본문을 읽기 전에 줄 세워 메모리를 묶는다(PR #110 리뷰)
    big_slots = anyio.Semaphore(_BIG_SLOTS)

    async def guarded(scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await inner(scope, receive, send)
        hdr = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        client_ip = (scope.get("client") or (None,))[0]  # 소켓 주소 — 프록시 뒤면 프록시 IP다
        if token and not hmac.compare_digest(
            (hdr.get("authorization") or "").encode(), f"Bearer {token}".encode()
        ):  # 인증 실패는 본문 수신을 기다리지 않고 바로 거부한다.
            with call_log.request_context(hdr, client_ip) as context:
                await anyio.to_thread.run_sync(call_log.unauthorized)
                return await JSONResponse({"error": "unauthorized"}, status_code=401, headers={"X-Request-Id": context["request_id"]})(
                    scope, receive, send
                )
        with call_log.request_context(hdr, client_ip) as context:
            # SDK가 받는 ASGI 청크를 즉시 그대로 전달한다. 감사용 사본은 최대 1MiB.
            # 큰 요청은 _meta/initialize 추출만 생략하며 도구 입력/제한은 바꾸지 않는다.
            metadata_limit = 1024 * 1024
            body, body_size = bytearray(), 0
            init_call = None
            response_body, response_status = bytearray(), 200

            async def observed_receive():
                nonlocal body_size, init_call
                message = await receive()
                if scope.get("method") == "POST" and message["type"] == "http.request":
                    chunk = message.get("body", b"")
                    body_size += len(chunk)
                    if body_size <= metadata_limit:
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            try:
                                payload = await anyio.to_thread.run_sync(json.loads, body)
                            except (ValueError, UnicodeError):
                                payload = None  # 기존 MCP 오류는 SDK가 처리한다.
                            call_log.update_request(context, payload)
                            init_call = call_log.initialize_call(payload)
                            body.clear()
                    else:
                        body.clear()
                return message

            async def correlated_send(message):
                nonlocal response_status
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                    message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", context["request_id"].encode())]}
                elif init_call is not None and message["type"] == "http.response.body":
                    response_body.extend(message.get("body", b"")[: max(0, metadata_limit - len(response_body))])
                await send(message)

            size = hdr.get("content-length", "")
            big = scope.get("method") == "POST" and (not size.isdigit() or int(size) > _BIG_BODY)  # 길이 모름 = 큰 것
            try:
                async with big_slots if big else contextlib.nullcontext():
                    await inner(scope, observed_receive, correlated_send)
            except BaseException as exc:
                if init_call is not None:
                    init_call.finish(status="error", err=str(exc))
                raise
            finally:
                if init_call is not None:
                    await anyio.to_thread.run_sync(call_log.finish_initialize, init_call, response_body, response_status)

    guarded.big_slots = big_slots  # 시험이 대기 수를 본다
    return guarded


def serve_http(host, port, token):
    import uvicorn

    guarded = build_guarded_app(host, port, token)
    threading.Thread(target=_warmup_bg, daemon=True).start()  # MC1 — 예열은 백그라운드, /health가 그 사이 503 'warming'
    uvicorn.run(guarded, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    utf8_stdout()
    if "--stdio" in sys.argv:
        call_log.configure_stdio()
    from common.config.settings import edw_read_only, require_run_env

    edw_read_only()  # 검색 MCP는 EDW 읽기 계정만 — 공용 설정 파일의 쓰기 계정 칸은 이 프로세스에서 비움(사용자 10-29, ops.md#op-03)
    require_run_env("mcp_server.main", sections=("mcp",))  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    from common.store.db import cfgfile

    print(
        f"[엔진 구성] {cfgfile.active('stack').label()}", file=sys.stderr, flush=True
    )  # stderr — --stdio면 stdout은 JSON-RPC 채널 · 시작 때 한 번(파일 — 못 읽으면 시작 거부, 종료 2)
    from mcp_server.services.search.server_state import check_store

    check_store()  # op-09 — 서버면 PG 접속 칸이 비면 시작 거부
    if "--stdio" in sys.argv:
        build("127.0.0.1", int(mc.cfg().server.port)).run(transport="stdio")  # stdio는 바인드 안 함 — 늘 루프백 규칙
    else:
        mc.checked("MCP_PORT")  # 접속 포트 — 형식 틀리면 옛처럼 시작 실패(S7d, 값은 안 찍음)
        _c = mc.cfg().server
        host, port, token = (
            _c.host,  # op-09 — 기본값은 설정 모델 한 곳
            int(_c.port),
            mc.token_text(_c.token),
        )  # 공백뿐인 토큰 = 토큰 없음(사용자 결정 10-27)
        if host == "auto":  # 브리지 네트워크 컨테이너: 자기 사설 IP(포트 게시로 밖에서 부름) — 토큰 필수
            import socket

            host = socket.gethostbyname(socket.gethostname())
        check_bind(host, token)
        print(f"검색 MCP http://{host}:{port}/mcp" + (" (토큰 인증)" if token else " (루프백 — 토큰 없음)"), flush=True)
        serve_http(host, port, token)
