"""검색 MCP 설정 — settings.yaml의 common + mcp 절(S7a 모델, refactor_plan 5-2 · D-015). 칸 표는 refactor_plan 부록 D.
mcp_server 코드가 읽는 객체는 설정 파일 기반 캐시 MCP다(S7e2 — 전환 다리 없앰: env의 옛 이름은 읽지 않음, 신호 SETTINGS_FILE·RUN_ENV만):
  `from mcp_server import config as mc` → `mc.cfg().search.methods`(mcp 절) · `mc.given("MCP_METHODS")`(준 값만) · `mc.checked(X)` ·
  시험 `with mc.senv(MCP_TOOL_TIMEOUT_SEC="5", MCP_METHODS=None):`(칸 이름으로 COMMON·MCP에 나눠 덮음 — os.environ 안 건드림, 인계 파일이
  env로 읽는 칸만 env에 씀). common 칸은 `common.config.settings.cfg()`로(COMMON).
요청마다 읽던 값(MCP_TOOL_TIMEOUT_SEC·SEARCH_* 등)은 쓰는 자리에서 요청마다 cfg()로 읽고, 시작 때 한 번 읽던 상수는 CFG(아래)에
모은다(S5 — 이름·기본값은 옛 mcp_server.py 모듈 상수 그대로, 읽는 시점도 같음 — 이 모듈 import 때).
SETTINGS(common + mcp 절)는 확인 명령(python -m mcp_server.config)·시험용.
사용: python -m mcp_server.config [--file 경로] · export --section mcp.host …
"""

import contextlib
import sys

from pydantic import Field, SecretStr  # 칸 형식

from common.config.settings import (  # noqa: F401 — token_text: 토큰 규칙(mc.token_text)
    AppSettings,
    Cache,
    CommonSettings,
    CsvList,
    EnvView,
    F,
    Port,
    Section,
    image_default,
    token_text,
)

# ── settings.yaml mcp 절 모델(S7a) — 칸 표는 refactor_plan 부록 D ─────────────────────────────


class McpSearchPg(Section):
    filter_exact_max: int | None = F(20000, "PG_FILTER_EXACT_MAX", "고객 필터 허용 집합이 이 크기 이하면 벡터 정확 검색으로 전환(청크 수)")


class McpSearchWeights(Section):
    bm25: float | None = F(1.0, "SEARCH_W_BM25", "RRF 융합에서 BM25 가중치")
    bm25_table: float | None = F(0.2, "SEARCH_W_BM25_TABLE", "집계 질문일 때 BM25 가중치")
    id: float | None = F(2.0, "SEARCH_W_ID", "RRF 융합에서 ID(드문 식별자) 가중치")
    vector: float | None = F(1.0, "SEARCH_W_VECTOR", "RRF 융합에서 벡터 가중치")


class McpDev(Section):
    mcp_url: str | None = F("http://127.0.0.1:8765/mcp", "MCP_URL", "검증 페이지가 붙을 MCP 서버 URL", blank="keep")
    ui_port: Port | None = F(8790, "UI_PORT", "검증 페이지(validation/search_ui) 서버 포트")


class McpEdwMeta(Section):
    dir: str | None = F(
        None,
        "EDW_META_DIR",
        "EDW 표 설명 자료 폴더(컨테이너 안 경로 — catalog.json·columns.jsonl, 개인정보 없는 자료만. 서버는 <루트>/output/edw_meta/에 복사하고 "
        "/app/output/edw_meta로 적음 — 결과 폴더가 검색 MCP에 읽기 전용으로 붙음) — catalog.json(JSON 하나: tables[] 표마다 schema·table·"
        "qualified_name·table_desc_ko·row_count·data_period·column_count 등 + meta{as_of·schemas}) · columns.jsonl(한 줄에 열 하나: schema·table·"
        "column_name·data_type·nullable·description_ko·primary_key·foreign_key·fk_reference 등). 두 파일이 없으면 edw_meta 도구가 not_configured로 "
        "답해 에이전트가 EDW 표·열 설명을 못 찾음(query_edw는 그대로 동작)",
    )
    max_bytes: int | None = F(200000, "EDW_META_MAX_BYTES", "edw_meta 응답 크기 상한(바이트) — 넘으면 목록 꼬리를 자름")


class McpEdwQuery(Section):
    enabled: bool | None = F(True, "EDW_QUERY", "query_edw 도구 스위치 — 0이면 끔", off=("0",))
    max_bytes: int | None = F(2000000, "EDW_QUERY_MAX_BYTES", "query_edw 응답 크기 상한(바이트)")
    max_rows: int | None = F(1000, "EDW_QUERY_MAX_ROWS", "query_edw 실효 행 수 상한(도구 요청 max_rows와 작은 쪽)")
    timeout_sec: float | None = F(20.0, "EDW_QUERY_TIMEOUT_SEC", "query_edw 질의 시간 상한(초)")


class McpHost(Section):
    cpus: float | None = F(1.0, "MCP_CPUS", "mcp-server 컨테이너 CPU 한도(compose cpus)")
    image: str | None = F(None, "MCP_SERVER_IMAGE", "mcp-server 컨테이너 이미지 이름:태그")
    jobs_dir: str | None = F(None, "MCP_JOBS_DIR", "MCP parse_document 업로드 작업 폴더(공유 볼륨) — medium 레인 양보 감지용")
    mem_limit: str | None = F("4g", "MCP_MEM_LIMIT", "mcp-server 컨테이너 메모리 한도(compose mem_limit)")


class McpOutput(Section):
    max_chars: int | None = F(20000, "MCP_MAX_CHARS", "search 응답 크기 상한(JSON UTF-8 바이트) — 넘으면 근거 본문을 줄임")


class McpParseProxy(Section):
    token: SecretStr | None = F(None, "PARSE_SERVICE_TOKEN", "parse_document가 작업 서비스(parse_service)를 부를 때 쓰는 토큰")
    url: str | None = F("http://127.0.0.1:8766", "PARSE_SERVICE_URL", "parse_document가 부르는 작업 서비스 주소")


class McpSearch(Section):
    methods: CsvList | None = F(["vector", "bm25", "id"], "MCP_METHODS", "search 기본 검색 방법(쉼표 목록: vector·bm25·id 중에서)")
    pg: McpSearchPg = Field(default_factory=McpSearchPg)
    weights: McpSearchWeights = Field(default_factory=McpSearchWeights)


class McpServer(Section):
    fulltext_secret: SecretStr | None = F(
        None,
        "FULLTEXT_SIGN_SECRET",
        "원문 도구(list/get_doc_fulltext) 파일 손잡이 sfid 서명 키 — 비면 두 도구는 not_configured, 바꾸면 발급된 sfid 전부 무효",
    )
    allowed_hosts: CsvList | None = F([], "MCP_ALLOWED_HOSTS", "비루프백 바인드 때 추가로 허용할 Host(쉼표 목록, 리버스 프록시 이름 등)")
    host: str | None = F("127.0.0.1", "MCP_HOST", "MCP 서버 바인드 주소 — auto면 컨테이너 자기 사설 IP")
    manifest: str | None = F(None, "MCP_MANIFEST", "수집 manifest.jsonl 경로(문서 유형·버전·삭제 여부 출처)")
    max_concurrency: int | None = F(8, "MCP_MAX_CONCURRENCY", "도구 동시 실행 상한(개)")
    max_queue: int | None = F(None, "MCP_MAX_QUEUE", "도구 대기열 상한(개) — 넘으면 즉시 busy 응답, 0이면 무제한")
    port: Port | None = F(8765, "MCP_PORT", "MCP 서버 포트")
    reload_check_sec: float | None = F(30.0, "MCP_RELOAD_CHECK_SEC", "적재 버전 변경 확인 간격(초) — 바뀌면 검색기·edw_meta 다시 읽음")
    token: SecretStr | None = F(None, "MCP_TOKEN", "MCP 서버 Bearer 토큰(비루프백 바인드면 필수)")
    tool_timeout_sec: float | None = F(30.0, "MCP_TOOL_TIMEOUT_SEC", "도구 1회 실행 시간 상한(초) — 넘으면 timeout 응답, 0이면 무제한")
    warmup: bool | None = F(True, "MCP_WARMUP", "기동 때 검색 1회로 예열 — 0이면 끔", off=("0",))


class McpAudit(Section):
    max_queue_bytes: int = F(268435456, "MCP_AUDIT_MAX_QUEUE_BYTES", "감사 대기/처리 중 본문 추정 바이트 합계 상한(기본 256MiB)", ge=0)
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
    mcp 칸 → MCP.env. 칸이 없는 이름은 거부(잘못된 이름으로 시험이 헛돌지 않게 — VS7c2 R-8).
    with로 쓰거나 변수에 받아 .close()(겹쳐 쓰면 안쪽부터 되돌림)."""
    from common.config.settings import COMMON, CommonAppSettings, env_map

    common_keys, mcp_keys = env_map(CommonAppSettings), env_map(McpEnvSettings)
    unknown = sorted(set(names) - set(common_keys) - set(mcp_keys))
    if unknown:
        raise KeyError(f"senv: 설정 칸이 없는 이름 {unknown}")
    st = contextlib.ExitStack()
    cn = {k: v for k, v in names.items() if k in common_keys}
    mn = {k: v for k, v in names.items() if k in mcp_keys and k not in common_keys}
    if cn:  # 준 칸이 있는 객체만 덮음(덮는 동안 그 객체는 os.environ 쓰기를 못 봄 — 필요 없는 객체까지 고정하지 않게)
        st.enter_context(COMMON.env(**cn))
    if mn:
        st.enter_context(MCP.env(**mn))
    return st


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
