#!/usr/bin/env python3
"""검색 MCP — 질문 하나로 근거(원문·원본 경로·쪽·위치·그림)를 돌려주는 한 창구(백로그 G1~G5). 답변 생성은 클라이언트(GLM 등) 몫.

도구(G2):
  search(question, k=8, methods=[vector,bm25,id], decompose=false, client=None)  근거 목록 — BM25는 용어 사전으로 확장(X3, notes에 표시) ·
    methods는 vector·bm25·id만(graph·image·openviking·concept·decompose는 10-29에 지움 — 입력은 받고 무시). client(AD38): 고객 명시(SEARCH_CLIENT_HARD=1이면 저장소 질의
    단계에서 다른 고객 제외, 기본 꺼짐). AD42(R3·R1): 응답에
    evidence_status(found/weak/none)·근거별 low_score(SEARCH_MIN_SCORE 문턱) 표시만(근거는 안 줄임) · 늘
    집계 질문을 aggregate.detect()로 가려 집계 결과(기존 정해진 함수만, 자유 SQL 없음)를 근거 맨 앞에 via="aggregate"로 · 집계 결과 통화가 2개 이상 섞이면(비교
    질문 등) 고정 질의(BR43)("환율 exchange rate USD KRW", bm25+id)로 1위 근거를
    더 찾아 진짜 환율 패턴일 때만 집계 근거 text 끝에 붙인다(단일 통화면 영향 없음).
    근거마다 doc_type·version·supersedes_doc_id·is_deleted·contract_id·updated_at·company는 RDB 문서 위치 메타(AD44
    manifest)에 그 문서가 있을 때만(없으면 칸 자체가 없음).
  (2026-10-20 사용자 결정·같은 날 통합 · 10-21 파싱 도구 추가) MCP 노출 도구는 search·query_edw·parse_document·edw_meta — 문서 목록(list_documents)·문서 단건
    (get_document)·그림(get_image)·근거 이미지(get_evidence_image)·집계 질의(aggregate)·요건별 연구(research)·용어(lookup_term)·
    개념(related)·describe_edw는 노출에서 뺐다. 내부 구현(do_*)은 search 안쪽 경로·셀프테스트만 남아 있고 MCP로는 호출 불가.
  search(question, k=8, methods=[vector,bm25,id], decompose, client, index_id, source_system, project_id, division,
    service_type, limit=100)  근거 검색 + 하드 필터 통합(2026-10-20) —
    · question만: 기존 하이브리드 검색 그대로(근거 상위 k) ·
    · 하드 필터만(question 없이 client·source_system·project_id·division·service_type): 조건에 정확히 맞는 문서 전부와
      그 청크 전부를 점수·임베딩 없이 돌려줌(do_filter_documents 응답 모양 — 문서 수 상한 limit 기본 100, 0이면 무제한,
      넘으면 truncated=true) ·
    · question + 하드 필터: 조건에 정확히 맞는 문서(v_chunk_source) 범위 안에서만 검색 — 풀을 넉넉히 잡아(k×3,
      상한 MAX_K) 파일 단위 후치 필터 뒤 근거 재순위·k로 자름(응답에 filter·scope_docs 표시) · 집계 근거는 전체 구조화
      집계라 범위가 안 맞아 이 결합에서는 생략 · 조건은 모두 정확 일치(부분 문자열 불가) — client는 고객명 전체
      (sf_acc_name·clients JSON 라벨) · source_system 'SFDC'/'CRMS'/'LAS' · project_id 프로젝트 코드(예: 'E54B') ·
      division 'DS'/'DP'/'CD'/'CM'/'AD'/'AS' · service_type 'CMO DS'/'CMO DP'/'CDO'/'ADC' 등 · 범위 산정은 PG 적재
      저장소만(로컬 묶음이면 필터 안내 후 전체 검색).
  (EQ1, English docstrings per 10-15 user rule)
  query_edw(sql, max_rows=2000) Read-only SQL against EDW: SELECT/WITH only, one statement, table allowlist
    (EDW_QUERY_TABLES), row/time/response-size caps. Returns raw rows only — no summarization, the
    calling agent does its own post-processing. See mcp_server/services/edw_query.py for the full guard.
  (2026-10-21 사용자 요청·같은 날 단일화) parse_document(path, content_b64, filename, time_out_threshold=300, max_chars=200000) —
    비정형 파일 1건의 text 파싱 대표 결과: data-pipeline-parse 컨테이너(S6b — 옛 data-parsing)의 작업 서비스(PARSE_URL, 기본 http://127.0.0.1:8766 ·
    docker exec -d data-pipeline-parse python -m pipeline.mcp_parse_service — 토큰은 그 컨테이너 settings.yaml required.tokens.parse_mcp)가
    prepare → run_all( phase 1·2만 — 그림[VLM] 파싱은 phase 3이라 실행 안 됨, 표 인식 유지) → parse_qa → represent(대표 결과)만
    수행(구조화·임베딩·EDW/OS 적재 없음). path는 허용 루트(/app/output/mcp_parse/inbox) 하위만(jail) · content_b64 상한 100MB ·
    time_out_threshold(기본 300초) 안에 끝나야 결과를 돌려주고 못 끝내면 {"error": "시간 안에 수행 못했습니다", "job_id": …}만 반환 —
    노출 도구는 parse_document 하나뿐(사용자 결정: 결과 수령 도구 parse_result는 등록하지 않는다), 이 도구만 MCP_TOOL_TIMEOUT_SEC(기본 30초)
    대신 자체 예산으로 기다린다(_bg_long) · 응답 text는 max_chars(기본 20만자) 상한(초과 시 잘리고 text_truncated, 전체는 rep_path 파일에).
  (EM1, English docstrings per 10-15 user rule)
  edw_meta(schema, table=None, column_filter=None) — EDW 테이블·컬럼 한글 메타데이터 3단 계층 조회(정적 데이터셋, 2026-10-22 사용자 결정):
    인자 없음 → 스키마 5개 요약 · schema만 → 그 스키마 전체 테이블 메타(컬럼 제외) · schema+table → 그 테이블 전체 컬럼 한글 설명.
    벡터·임베딩·LLM·pgvector 불개입(rule-based — 비-RAG 원칙) · 데이터는 EDW_META_DIR(기본 /app/config/edw_meta)의
    catalog.json+columns.jsonl, mtime 재확인(기본 30초)으로 재빌드 반영 · sample_values는 어떤 응답에도 실리지 않음 ·
    도구 파일·데이터셋 부재 시 {"error": …} fail-soft(모듈 import는 do_edw_meta 안 lazy — 서버 부팅·기존 도구 계속).
저장소: common/services.py 자동 연결(Docker PostgreSQL → 없으면 로컬 묶음), 임베딩·LLM은 .env 내부망 주소만.

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

import hmac
import ipaddress
import sys
import threading

from common.core.console import utf8_stdout
from mcp_server import config as mc  # 설정 객체(S7d)
from mcp_server.routers import edw_tools, health, parse_tool, search_tool  # 도구·/health 등록(5-1)
from mcp_server.services.search.server_state import CALLER, _warmup_bg

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


# ── MCP 서버 ─────────────────────────────────────────────────────
def build(host="127.0.0.1", port=8765):
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
    )

    search_tool.register(m)  # 등록 순서 = tools/list 순서(MCP 계약 바이트) — search · query_edw · parse_document · edw_meta
    edw_tools.register_query_edw(m)
    parse_tool.register(m)
    edw_tools.register_edw_meta(m)
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

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            if scope.get("path") == "/health":
                return await inner(scope, receive, send)
            hdr = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if token and not hmac.compare_digest(
                (hdr.get("authorization") or "").encode(), f"Bearer {token}".encode()
            ):  # 상수 시간 비교(보안 검토 10-02)
                return await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            CALLER.set("mcp:" + (hdr.get("x-mcp-client") or "http")[:60])
        await inner(scope, receive, send)

    return guarded


def serve_http(host, port, token):
    import uvicorn

    guarded = build_guarded_app(host, port, token)
    threading.Thread(target=_warmup_bg, daemon=True).start()  # MC1 — 예열은 백그라운드, /health가 그 사이 503 'warming'
    uvicorn.run(guarded, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    utf8_stdout()
    from common.config.settings import edw_read_only, require_run_env

    edw_read_only()  # 검색 MCP는 EDW 읽기 계정만 — 공용 설정 파일의 쓰기 계정 칸은 이 프로세스에서 비움(사용자 10-29, ops.md#op-03)
    require_run_env("mcp_server.main", sections=("mcp",))  # S7a(D-028 ②) — 실행 환경 없으면 시작 거부(서버면 설정 검증 실패도 — S7e2 U-1)
    from common.store.db import cfgtables

    print(
        f"[엔진 구성] {cfgtables.active('stack').label()}", file=sys.stderr, flush=True
    )  # stderr — --stdio면 stdout은 JSON-RPC 채널   # S8b(Q3·Q7) — 시작 때 한 번(서버 = 판 표 — 못 읽으면 시작 거부, 종료 4)
    if "--stdio" in sys.argv:
        build().run(transport="stdio")
    else:
        mc.checked("MCP_PORT")  # 접속 포트 — 형식 틀리면 옛처럼 시작 실패(S7d, 값은 안 찍음)
        _c = mc.cfg().server
        host, port, token = (
            _c.host or "127.0.0.1",
            int(_c.port if _c.port is not None else 8765),
            mc.token_text(_c.token),
        )  # 공백뿐인 토큰 = 토큰 없음(사용자 결정 10-27)
        if host == "auto":  # 브리지 네트워크 컨테이너: 자기 사설 IP(포트 게시로 밖에서 부름) — 토큰 필수
            import socket

            host = socket.gethostbyname(socket.gethostname())
        check_bind(host, token)
        print(f"검색 MCP http://{host}:{port}/mcp" + (" (토큰 인증)" if token else " (루프백 — 토큰 없음)"), flush=True)
        serve_http(host, port, token)
