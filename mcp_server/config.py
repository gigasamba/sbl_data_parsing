"""검색 MCP 설정 — settings.yaml의 common + mcp 절(S7a 모델, refactor_plan 5-2 · D-015). 칸 표는 refactor_plan 부록 D.
mcp_server 코드가 읽는 객체는 설정 파일 기반 캐시 MCP다(S7e2 — 전환 다리 없앰: env의 옛 이름은 읽지 않음, 신호 SETTINGS_FILE·RUN_ENV만):
  `from mcp_server import config as mc` → `mc.cfg().search.methods`(mcp 절) · `mc.given("MCP_METHODS")`(준 값만) · `mc.checked(X)` ·
  시험 `with mc.senv(SEARCH_CLIENT_HARD="1", MCP_STORE=None):`(칸 이름으로 COMMON·MCP에 나눠 덮음 — os.environ 안 건드림, 인계 파일이
  env로 읽는 칸만 env에 씀). common 칸은 `common.config.settings.cfg()`로(COMMON).
요청마다 읽던 값(MCP_TOOL_TIMEOUT_SEC·SEARCH_* 등)은 쓰는 자리에서 요청마다 cfg()로 읽고, 시작 때 한 번 읽던 상수는 CFG(아래)에
모은다(S5 — 이름·기본값은 옛 mcp_server.py 모듈 상수 그대로, 읽는 시점도 같음 — 이 모듈 import 때).
SETTINGS(common + mcp 절)는 확인 명령(python -m mcp_server.config)·시험용.
사용: python -m mcp_server.config [--file 경로] · export --section mcp.host …
"""

import contextlib
import os
import sys

from pydantic import Field, SecretStr  # 칸 형식

from common.config.settings import (  # noqa: F401 — token_text: 토큰 규칙(mc.token_text)
    AppSettings,
    Cache,
    CommonSettings,
    CsvList,
    EnvView,
    F,
    JsonValue,
    Port,
    Section,
    image_default,
    token_text,
)

# ── settings.yaml mcp 절 모델(S7a) — 칸 표는 refactor_plan 부록 D ─────────────────────────────


class McpSearchAgg(Section):
    fx: bool | None = F(True, "SEARCH_AGG_FX", "통화가 2개 이상 섞인 집계에 환율 근거 추가 — 0이면 끔", off=("0",))
    llm: bool | None = F(False, "SEARCH_AGG_LLM", "집계 질문 분류에 LLM 경계 분류 사용 — 1이면 켬(기본 끔)", on=("1",))
    llm_min: float | None = F(0.6, "SEARCH_AGG_LLM_MIN", "집계 LLM 분류 확신도 하한(0~1) — 미달이면 검색으로 폴백")
    llm_timeout: float | None = F(8.0, "SEARCH_AGG_LLM_TIMEOUT", "집계 LLM 분류 호출 시간 상한(초)")
    route: bool | None = F(True, "SEARCH_AGG_ROUTE", "집계 질문이면 집계 결과를 근거 맨 앞에 — 0이면 끔", off=("0",))
    text_max_rows: int | None = F(30, "SEARCH_AGG_TEXT_MAX_ROWS", "집계 근거 text에 붙이는 표 행 상한(개)")
    text_max_src_rows: int | None = F(40, "SEARCH_AGG_TEXT_MAX_SRC_ROWS", "계약별 근거 행 상한(개)")


class McpSearchClient(Section):
    filter: bool | None = F(True, "SEARCH_CLIENT_FILTER", "질문에 나온 고객명으로 검색 범위 거르기 — 0이면 끔", off=("0",))
    hard: bool | None = F(False, "SEARCH_CLIENT_HARD", "고객 범위를 하드 격리(다른 고객 문서 제외) — 1이면 켬", on=("1",))
    strict: bool | None = F(False, "SEARCH_CLIENT_STRICT", "하드 격리에서 고객 미상 문서도 제외 — 1이면 켬", on=("1",))


class McpSearchPg(Section):
    filter_exact_max: int | None = F(20000, "PG_FILTER_EXACT_MAX", "고객 필터 허용 집합이 이 크기 이하면 벡터 정확 검색으로 전환(청크 수)")
    vector_search: str | None = F(None, "PG_VECTOR_SEARCH", "벡터 검색 방식 — exact면 색인 없이 정확 검색, 비우면 근사(HNSW)")


class McpSearchQueryExpand(Section):
    draft: bool | None = F(True, "QUERY_EXPAND_DRAFT", "질문 용어 확장에서 draft 용어 사전 사용 — 0이면 끔", off=("0",))
    enabled: bool | None = F(True, "QUERY_EXPAND", "질문 용어 확장(BM25, 용어 사전) 스위치 — 0이면 끔", off=("0",))
    shorttok: bool | None = F(True, "QUERY_EXPAND_SHORTTOK", "용어 확장에서 한 글자 비숫자 토큰 제거 — 0이면 제거 안 함", off=("0",))


class McpSearchWeights(Section):
    bm25: float | None = F(1.0, "SEARCH_W_BM25", "RRF 융합에서 BM25 가중치")
    bm25_table: float | None = F(0.2, "SEARCH_W_BM25_TABLE", "집계 질문일 때 BM25 가중치(SEARCH_TYPE_WEIGHTS 켠 경우)")
    id: float | None = F(2.0, "SEARCH_W_ID", "RRF 융합에서 ID(드문 식별자) 가중치")
    vector: float | None = F(1.0, "SEARCH_W_VECTOR", "RRF 융합에서 벡터 가중치")


class McpDev(Section):
    eval_s_parts: JsonValue | None = F(None, "EVAL_S_PARTS", "검색 평가가 고를 S 묶음 설정(JSON, 예 {'chunk_size':256})")
    mcp_url: str | None = F("http://127.0.0.1:18765/mcp", "MCP_URL", "검증 페이지가 붙을 MCP 서버 URL", blank="keep")
    ui_port: Port | None = F(8790, "UI_PORT", "검증 페이지(validation/search_ui) 서버 포트")


class McpEdwMeta(Section):
    dir: str | None = F(None, "EDW_META_DIR", "edw_meta 데이터셋(catalog.json·columns.jsonl) 폴더")
    max_bytes: int | None = F(200000, "EDW_META_MAX_BYTES", "edw_meta 응답 크기 상한(바이트) — 넘으면 목록 꼬리를 자름")


class McpEdwQuery(Section):
    REMOVED = frozenset(
        {"conn_file", "database", "password", "port", "server", "sqlite", "user"}
    )  # 사용자 10-29 — 접속은 common.connections.rdb 읽기 계정(ops.md#op-03)
    enabled: bool | None = F(True, "EDW_QUERY", "query_edw 도구 스위치 — 0이면 끔", off=("0",))
    max_bytes: int | None = F(2000000, "EDW_QUERY_MAX_BYTES", "query_edw 응답 크기 상한(바이트)")
    max_rows: int | None = F(2000, "EDW_QUERY_MAX_ROWS", "query_edw 실효 행 수 상한(도구 요청 max_rows와 작은 쪽)")
    tables: CsvList | None = F(
        None,
        "EDW_QUERY_TABLES",
        "query_edw 허용 표 목록(쉼표) — TABLES_STRICT=1일 때만 적용, 안 주면 코드가 정함(sqlite 기본 표 · mssql 없음), 빈 값은 전부 거부",
        blank="keep",
    )
    tables_strict: bool | None = F(
        False, "EDW_QUERY_TABLES_STRICT", "1이면 허용 표 목록(EDW_QUERY_TABLES) 검사를 켬 — 기본은 전 스키마 허용", on=("1",)
    )
    timeout_sec: float | None = F(20.0, "EDW_QUERY_TIMEOUT_SEC", "query_edw 질의 시간 상한(초)")


class McpHost(Section):
    cpus: float | None = F(1.0, "MCP_CPUS", "mcp-server 컨테이너 CPU 한도(compose cpus)")
    image: str | None = F(None, "MCP_SERVER_IMAGE", "mcp-server 컨테이너 이미지 이름:태그")
    jobs_dir: str | None = F(None, "MCP_JOBS_DIR", "MCP parse_document 업로드 작업 폴더(공유 볼륨) — medium 레인 양보 감지용")
    mem_limit: str | None = F("4g", "MCP_MEM_LIMIT", "mcp-server 컨테이너 메모리 한도(compose mem_limit)")
    tool_cpus: float | None = F(1.0, "RETRIEVAL_TOOL_CPUS", "검색 도구 실행 컨테이너(run_tool) CPU 한도")
    tool_mem_limit: str | None = F("2g", "RETRIEVAL_TOOL_MEM_LIMIT", "검색 도구 실행 컨테이너(run_tool) 메모리 한도")


class McpOutput(Section):
    REMOVED = frozenset(
        {"list_docs_max", "evid_local_roots", "evid_max_concurrency", "evid_max_mb", "evid_timeout_sec", "images", "max_image_px"}
    )  # 사용자 10-29·10-30(e2-18 — 근거 이미지·그림 조회 지움) — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    cap_ranked: bool | None = F(
        True, "CAP_RANKED", "검색 응답 크기 상한(cap)을 순위 인지 방식으로 줄임 — 0이면 옛 방식(긴 본문부터 반씩 자름)", off=("0",)
    )
    evidence_paths: bool | None = F(
        True, "MCP_EVIDENCE_PATHS", "근거의 '파싱 결과 경로' 조회(AI.ParsingMeta) 스위치 — 0이면 시도 안 함", off=("0",)
    )
    max_chars: int | None = F(20000, "MCP_MAX_CHARS", "search 응답 크기 상한(JSON UTF-8 바이트) — 넘으면 근거 본문을 줄임")


class McpParseProxy(Section):
    token: SecretStr | None = F(None, "PARSE_SERVICE_TOKEN", "parse_document가 작업 서비스(mcp_parse_service)를 부를 때 쓰는 토큰")
    url: str | None = F("http://127.0.0.1:8766", "PARSE_SERVICE_URL", "parse_document가 부르는 작업 서비스 주소")


class McpQueryLog(Section):
    dir: str | None = F(None, "MCP_QUERY_LOG_DIR", "질의 기록 폴더")
    enabled: bool | None = F(True, "MCP_QUERY_LOG", "질의 기록(qa_log.jsonl) 스위치 — 0이면 기록 안 함", off=("0",))


class McpSearch(Section):
    REMOVED = frozenset(
        {"decompose", "decompose_llm", "graph", "ov_search_path", "rerank"}
    )  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    agg_today: str | None = F(None, "AGG_TODAY", "집계 질문의 '오늘' 기준일(YYYY-MM-DD) 고정 — 비우면 실제 오늘")
    agg_vocab_file: str | None = F(None, "AGG_VOCAB_FILE", "집계 지표 단서어 사전(agg_vocab.json)을 다른 경로로 지정")
    copy_group: bool | None = F(True, "SEARCH_COPY_GROUP", "같은 사건의 사본(형식·재명명) 근거를 묶어 대표만 남김 — 0이면 끔", off=("0",))
    data_catalog: str | None = F(None, "DATA_CATALOG", "데이터 카탈로그(표·열 설명) JSON 경로 — 없으면 카탈로그 없이 동작")
    entity_split: bool | None = F(True, "SEARCH_ENTITY_SPLIT", "비교 질문(고객 2명 이상)을 고객별로 나눠 검색 — 0이면 끔", off=("0",))
    evidence_gate: bool | None = F(True, "SEARCH_EVIDENCE_GATE", "근거 점수·evidence_status 표시 — 0이면 끔(점수 칸도 안 실림)", off=("0",))
    methods: CsvList | None = F(["vector", "bm25", "id"], "MCP_METHODS", "search 기본 검색 방법(쉼표 목록: vector·bm25·id 중에서)")
    min_score: float | None = F(None, "SEARCH_MIN_SCORE", "근거 점수 하한 — 미달 근거에 low_score 표시·전부 미달이면 weak")
    ocr_dpi: int | None = F(200, "OCR_DPI", "쪽 이미지 렌더링 해상도(DPI) — OCR·근거 이미지 좌표 환산에 씀", pinned="engine")
    struct_context_max: int | None = F(200, "STRUCT_CONTEXT_MAX", "집계 질문에서 계약 마스터 전체를 표로 넘길 때 계약 수 상한(개)")
    tie_break: bool | None = F(True, "SEARCH_TIE_BREAK", "동점 근거를 질문의 엔티티(고객·계약번호)로 깨기 — 0이면 끔", off=("0",))
    type_weights: bool | None = F(
        True,
        "SEARCH_TYPE_WEIGHTS",
        "집계 질문이면 BM25 가중을 SEARCH_W_BM25_TABLE로 교체 — 끄는 값 0·none·false·빈 값",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    vector_alias_expand: bool | None = F(
        True, "SEARCH_VECTOR_ALIAS_EXPAND", "벡터 질의에 교차 문자 체계 별칭을 덧붙임 — 0이면 끔", off=("0",)
    )
    agg: McpSearchAgg = Field(default_factory=McpSearchAgg)
    client: McpSearchClient = Field(default_factory=McpSearchClient)
    pg: McpSearchPg = Field(default_factory=McpSearchPg)
    query_expand: McpSearchQueryExpand = Field(default_factory=McpSearchQueryExpand)
    weights: McpSearchWeights = Field(default_factory=McpSearchWeights)


class McpServer(Section):
    allowed_hosts: CsvList | None = F([], "MCP_ALLOWED_HOSTS", "비루프백 바인드 때 추가로 허용할 Host(쉼표 목록, 리버스 프록시 이름 등)")
    host: str | None = F("127.0.0.1", "MCP_HOST", "MCP 서버 바인드 주소 — auto면 컨테이너 자기 사설 IP")
    instructions: str | None = F(None, "MCP_INSTRUCTIONS", "MCP 서버 instructions 글자(도구 안내문) 교체")
    manifest: str | None = F(None, "MCP_MANIFEST", "수집 manifest.jsonl 경로(문서 유형·버전·삭제 여부 출처)")
    max_concurrency: int | None = F(8, "MCP_MAX_CONCURRENCY", "도구 동시 실행 상한(개)")
    max_queue: int | None = F(None, "MCP_MAX_QUEUE", "도구 대기열 상한(개) — 넘으면 즉시 busy 응답, 0이면 무제한")
    port: Port | None = F(8765, "MCP_PORT", "MCP 서버 포트")
    query_cache: str | None = F(
        image_default("MCP_QUERY_CACHE"),
        "MCP_QUERY_CACHE",
        "검색 MCP의 질의 임베딩 캐시 sqlite 경로 — 있으면 시작 때 common.models.embed.query_cache를 이 값으로(mcp 이미지 안 기본 /tmp/mcp_query_cache.sqlite — 결과 폴더는 읽기 전용, 옛 compose EMBED_QUERY_CACHE 자리 — S7e2)",
    )
    reload_check_sec: float | None = F(30.0, "MCP_RELOAD_CHECK_SEC", "적재 버전 변경 확인 간격(초) — 바뀌면 검색기·edw_meta 다시 읽음")
    store: str | None = F(None, "MCP_STORE", "검색 저장소 종류 — pg 또는 local, 비우면 자동 탐지(Docker pgvector → 없으면 로컬 묶음)")
    token: SecretStr | None = F(None, "MCP_TOKEN", "MCP 서버 Bearer 토큰(비루프백 바인드면 필수)")
    tool_timeout_sec: float | None = F(30.0, "MCP_TOOL_TIMEOUT_SEC", "도구 1회 실행 시간 상한(초) — 넘으면 timeout 응답, 0이면 무제한")
    warmup: bool | None = F(True, "MCP_WARMUP", "기동 때 검색 1회로 예열 — 0이면 끔", off=("0",))


class McpAudit(Section):
    max_input_bytes: int = F(16384, "MCP_AUDIT_MAX_INPUT_BYTES", "감사 로그 입력 원문 UTF-8 바이트 상한", ge=0)
    max_output_bytes: int = F(65536, "MCP_AUDIT_MAX_OUTPUT_BYTES", "감사 로그 출력 원문 UTF-8 바이트 상한", ge=0)


class McpSettings(Section):
    audit: McpAudit = Field(default_factory=McpAudit)
    dev: McpDev = Field(default_factory=McpDev)
    edw_meta: McpEdwMeta = Field(default_factory=McpEdwMeta)
    edw_query: McpEdwQuery = Field(default_factory=McpEdwQuery)
    host: McpHost = Field(default_factory=McpHost)
    output: McpOutput = Field(default_factory=McpOutput)
    parse_proxy: McpParseProxy = Field(default_factory=McpParseProxy)
    query_log: McpQueryLog = Field(default_factory=McpQueryLog)
    search: McpSearch = Field(default_factory=McpSearch)
    server: McpServer = Field(default_factory=McpServer)


class McpAppSettings(AppSettings):
    common: CommonSettings = Field(default_factory=CommonSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)


SETTINGS = Cache(McpAppSettings)


class McpEnvSettings(AppSettings):
    """mcp 절만 — mcp_server 코드가 읽는 뿌리(MCP, S7d — S7e2부터 설정 파일 기반). common 칸은 common.config.settings.cfg()."""

    mcp: McpSettings = Field(default_factory=McpSettings)


MCP = Cache(McpEnvSettings)
_VIEW = EnvView(MCP, "mcp")


def cfg():
    """mcp 절 설정 객체(McpSettings) — 설정 파일 기반 캐시(위 모듈 설명)."""
    return MCP.get().mcp


by_env, given, dropped, checked = _VIEW.by_env, _VIEW.given, _VIEW.dropped, _VIEW.checked  # common.config.settings의 같은 이름 설명


def senv(**names):
    """selftest용(S7d) — 옛 os.environ 쓰기·지움을 설정 객체 덮기로 대신. None = 지움. 칸 이름으로 가름: common 칸 → COMMON.env,
    mcp 칸 → MCP.env, 인계 파일이 env로 읽는 칸(pinned="handoff" — GLOSSARY_DIR·CLIENT_ROSTER)은 os.environ에도 씀(끝나면 되돌림 —
    terms.py 등 인계 파일은 env를 그대로 읽음). 칸이 없는 이름은 거부(잘못된 이름으로 시험이 헛돌지 않게 — VS7c2 R-8).
    with로 쓰거나 변수에 받아 .close()(겹쳐 쓰면 안쪽부터 되돌림)."""
    from common.config.settings import COMMON, CommonAppSettings, env_map, env_name, walk

    common_keys, mcp_keys = env_map(CommonAppSettings), env_map(McpEnvSettings)
    unknown = sorted(set(names) - set(common_keys) - set(mcp_keys))
    if unknown:
        raise KeyError(f"senv: 설정 칸이 없는 이름 {unknown}")
    handoff = {env_name(f) for _, f, _ in walk(CommonAppSettings) if (f.json_schema_extra or {}).get("pinned") == "handoff"}
    st = contextlib.ExitStack()
    raw = {k: v for k, v in names.items() if k in handoff}
    if raw:
        saved = {k: os.environ.get(k) for k in raw}  # env 남김 — 시험: 인계 파일 env(아래에서 되돌림)
        _put_env(raw)
        st.callback(_put_env, saved)
    cn = {k: v for k, v in names.items() if k in common_keys}
    mn = {k: v for k, v in names.items() if k in mcp_keys and k not in common_keys}
    if cn:  # 준 칸이 있는 객체만 덮음(덮는 동안 그 객체는 os.environ 쓰기를 못 봄 — 필요 없는 객체까지 고정하지 않게)
        st.enter_context(COMMON.env(**cn))
    if mn:
        st.enter_context(MCP.env(**mn))
    return st


def _put_env(values):
    """시험 — 인계 파일이 env로 읽는 칸을 os.environ에 씀(None = 지움, senv가 씀)."""
    for k, v in values.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, str(v))  # env 남김 — 시험: 인계 파일(terms.py)이 env로 읽음


class MCPConfig:
    """검색 MCP 시작 때 읽는 상수 한 묶음 — 속성 이름은 옛 모듈 상수 이름 그대로(시험은 속성을 바꿔 끼움, 예: CFG.MAX_CHARS).
    S7d: env 대신 설정 객체(cfg())에서 — 값·기본값·읽는 시점(이 모듈 import 때)은 그대로(S7e2 — 다리가 없어져 import 순서와 무관)."""

    def __init__(self):
        c = cfg()
        self.MAX_CHARS = c.output.max_chars  # GH1-13: cap()이 이 값을 바이트(UTF-8)로 씀 — 이름·기본값은 그대로(실측 재조정은 서버에서)
        self.MAX_K = 50
        self.CORE = ("vector", "bm25", "id")
        self.DEFAULT_METHODS = list(c.search.methods)  # 10-12 구조 검토: graph 기본에서 뺌 —
        # 그래프 단독 효과를 처음 따로 잼(9세트): 근거 지표 이득 0, 잡음 비율↑(4clients .366→.459), distractors-v2 정답 값 적중 .80→.72 ·
        # G10(10-02)의 비교형 6→12/12 개선은 분해(decompose) 몫 · 다시 켜기: MCP_METHODS=vector,bm25,id,graph
        # parse_document 프록시가 부르는 작업 서비스 주소(services/parse_proxy.py)
        self.PARSE_URL = c.parse_proxy.url


CFG = MCPConfig()


if __name__ == "__main__":
    from common.config import show

    sys.exit(show.main(McpAppSettings, sys.argv[1:], prog="python -m mcp_server.config"))
