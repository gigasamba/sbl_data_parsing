"""pipeline 앱 설정 — settings.yaml의 common + pipeline 절만 읽는다(S7a, refactor_plan 5-2 · D-015). 다른 앱(mcp) 절은 무시.
pipeline 코드가 읽는 객체는 설정 파일 기반 캐시 PIPE다(S7e2 — 전환 다리 없앰: env의 옛 이름은 읽지 않음, 신호 SETTINGS_FILE·RUN_ENV만):
  `from pipeline import config as pc` → `pc.cfg().extract.max_new`(pipeline 절) · `pc.given("PM_BUCKET")`(준 값만) · `pc.checked(X)` ·
  `pc.by_env(f"{p}_X")` · 시험 `with pc.PIPE.env(PARSE_TMP=…, KEEP_RAW_LAYER=None):`(설정 위에 옛 env 이름으로 덮음 — os.environ 안 건드림).
  common 칸은 `common.config.settings.cfg()`로(COMMON). 값을 바꿔 자식에 넘길 때는 `settings.put()`·`settings.child_env()`(덮기 파일).
SETTINGS(common + pipeline 절)는 확인 명령(python -m pipeline.config)·시험용. 칸 표는 refactor_plan 부록 D.
사용: python -m pipeline.config [--file 경로]   # 읽어서 요약(비밀 가림) · export --section pipeline.host … · --selftest
"""

import sys
from pathlib import Path

from pydantic import Field, SecretStr  # 칸 형식

from common.config.settings import (
    IMAGE_PATHS,
    IN_IMAGE,
    AppSettings,
    Cache,
    CommonSettings,
    CsvList,
    CsvText,
    EnvView,
    F,
    Port,
    Section,
    WordList,
    image_default,
)


class PipelineConnectionsRdbColumns(Section):
    bucket: str | None = F(None, "RDB_COL_BUCKET", "RDB 문서 위치 표에서 버킷 열의 이름(비우면 열 없음)")
    company: str | None = F(None, "RDB_COL_COMPANY", "RDB 문서 위치 표에서 회사 ID(필터용) 열의 이름(비우면 열 없음)")
    content_type: str | None = F(None, "RDB_COL_CONTENT_TYPE", "RDB 문서 위치 표에서 콘텐츠 타입 열의 이름(비우면 열 없음)")
    content_version: str | None = F(
        "content_version_id", "RDB_COL_CONTENT_VERSION", "RDB 문서 위치 표에서 문서 판(content version) ID 열의 이름", blank="keep"
    )
    contract: str | None = F(None, "RDB_COL_CONTRACT", "RDB 문서 위치 표에서 계약 ID 열의 이름(비우면 열 없음)")
    doc_id: str | None = F("id", "RDB_COL_DOC_ID", "RDB 문서 위치 표에서 문서 ID 열의 이름", blank="keep")
    doc_type: str | None = F(None, "RDB_COL_DOC_TYPE", "RDB 문서 위치 표에서 문서 유형(필터용) 열의 이름(비우면 열 없음)")
    etag: str | None = F(None, "RDB_COL_ETAG", "RDB 문서 위치 표에서 ETag 열의 이름(비우면 열 없음)")
    filename: str | None = F("original_filename", "RDB_COL_FILENAME", "RDB 문서 위치 표에서 원본 파일 이름 열의 이름", blank="keep")
    is_deleted: str | None = F(None, "RDB_COL_IS_DELETED", "RDB 문서 위치 표에서 삭제 표시 열의 이름(비우면 열 없음)")
    key: str | None = F("s3_key", "RDB_COL_KEY", "RDB 문서 위치 표에서 Object Storage 키(s3_key) 열의 이름", blank="keep")
    size: str | None = F("file_size", "RDB_COL_SIZE", "RDB 문서 위치 표에서 파일 크기 열의 이름", blank="keep")
    supersedes: str | None = F(None, "RDB_COL_SUPERSEDES", "RDB 문서 위치 표에서 대체 대상 문서 ID 열의 이름(비우면 열 없음)")
    updated: str | None = F(None, "RDB_COL_UPDATED", "RDB 문서 위치 표에서 갱신 시각(증분 기준) 열의 이름(비우면 열 없음)")
    version: str | None = F(None, "RDB_COL_VERSION", "RDB 문서 위치 표에서 문서 버전 열의 이름(비우면 열 없음)")


class PipelineTransformRepresentReread(Section):
    dpi: int | None = F(400, "FUSE_REREAD_DPI", "융합 재판독(P2)용 크롭 재렌더 해상도(dpi)")
    margin: float | None = F(1.5, "FUSE_REREAD_MARGIN", "승자와 최선 패자 점수차가 이 값 이하면 '근소'로 보고 재판독")
    max: int | None = F(20, "FUSE_REREAD_MAX", "문서당 융합 재판독(P2) 횟수 상한(0이면 재판독 안 함)")
    p3_img_max: int | None = F(2, "FUSE_REREAD_P3_IMG_MAX", "재판독 3단계에서 조각 하나당 다시 볼 그림 상한(가까운 순)")
    pad_pt: float | None = F(40.0, "FUSE_REREAD_PAD_PT", "재판독 때 bbox 둘레에 더할 여백(pt)")
    vlm_max: int | None = F(5, "FUSE_VLM_MAX", "문서당 재판독 3단계 VLM 호출 상한(비용 가드)")
    vlm_max_tokens: int | None = F(400, "FUSE_VLM_MAX_TOKENS", "재판독·맥락 판독 VLM 응답 최대 토큰 수")


class PipelineConnectionsGraphiti(Section):
    REMOVED = frozenset({"neo4j_uri"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    neo4j_password: SecretStr | None = F(None, "GRAPHITI_NEO4J_PASSWORD", "Graphiti용 Neo4j 접속 비밀번호")
    neo4j_user: str | None = F("neo4j", "GRAPHITI_NEO4J_USER", "Graphiti용 Neo4j 접속 사용자 이름", blank="keep")


class PipelineConnectionsRdb(Section):
    REMOVED = frozenset(
        {"connect_kwargs", "database", "host", "password", "port", "user"}
    )  # 사용자 10-29 — 접속은 common.connections.rdb(ops.md#op-03)
    bucket: str | None = F(None, "RDB_BUCKET", "RDB 표에 버킷 정보가 없을 때 쓸 Object Storage 버킷 이름(레거시 대체값)")
    company: CsvList | None = F([], "RDB_COMPANY", "RDB에서 가져올 회사 ID 필터(쉼표 목록, 비우면 필터 없음)")
    doc_type: CsvList | None = F([], "RDB_DOC_TYPE", "RDB에서 가져올 문서 유형 필터(쉼표 목록, 비우면 필터 없음)")
    engine: str | None = F(
        "mssql", "RDB_ENGINE", "RDB 종류(mssql | pg) — mssql 접속은 common.connections.rdb(읽기 계정 · PC 시험은 그 sqlite)", blank="keep"
    )
    increment_col: str | None = F(None, "RDB_INCREMENT_COL", "증분(since) 판정에 쓸 열 이름(updated 열이 없을 때 대체)")
    columns: PipelineConnectionsRdbColumns = Field(default_factory=PipelineConnectionsRdbColumns)


class PipelineConnectionsSecureDoc(Section):
    password: SecretStr | None = F(None, "SECURE_DOC_PASSWORD", "암호 걸린 문서를 여는 암호 1개(secure_docs decrypt에서 시도)")
    passwords_file: str | None = F(None, "SECURE_DOC_PASSWORDS_FILE", "암호 걸린 문서용 암호 목록 파일 경로(한 줄에 암호 하나)")


class PipelineExtractAttach(Section):
    max_depth: int | None = F(1, "ATTACH_MAX_DEPTH", "메일 등 첨부 안의 첨부를 따라갈 최대 깊이(단계)")
    max_mb: float | None = F(20.0, "ATTACH_MAX_MB", "첨부 1개당 크기 상한(MB, 넘으면 건너뜀)")
    max_n: int | None = F(10, "ATTACH_MAX_N", "문서 하나에서 처리할 첨부 개수 상한(개)")
    timeout: float | None = F(120.0, "ATTACH_TIMEOUT", "첨부 1개를 별도 프로세스로 파싱할 때 제한 시간(초)")


class PipelineExtractCache(Section):
    keep_engine_cache: bool | None = F(
        False, "KEEP_ENGINE_CACHE", "엔진별 중간 결과(output/parse/<엔진>/<문서>.json)를 지우지 않고 남길지(=1 보관)", on=("1",)
    )
    keep_local_originals: bool | None = F(
        False, "KEEP_LOCAL_ORIGINALS", "내려받은 원본을 파싱 뒤에도 지우지 않고 남길지(=1 보관, 디버그·샘플용)", on=("1",)
    )
    keep_raw_layer: bool | None = F(
        True, "KEEP_RAW_LAYER", "P0 원본 층 캐시(output/parse/raw/**)를 유지할지(1 유지 / 그 외 이번 묶음 것 삭제)", on=("1",)
    )
    parse_cache_max_gb: float | None = F(
        5.0, "PARSE_CACHE_MAX_GB", "재판독 중간 캐시 3종 합계 용량 상한(GB, 넘으면 오래된 것부터 삭제, 0=끔)"
    )
    parse_keep_max_gb: float | None = F(
        None, "PARSE_KEEP_MAX_GB", "보존 폴더(KEEP_LOCAL_ORIGINALS=1) 용량 상한(GB, 넘으면 보존 포기·즉시 삭제)"
    )
    parse_tmp_max_gb: float | None = F(0.0, "PARSE_TMP_MAX_GB", "PARSE_TMP 사용량 상한(GB, 넘으면 다음 묶음 받기 전 대기, 0=제한 없음)")


class PipelineExtractDedup(Section):
    common_max: int | None = F(None, "DEDUP_COMMON_MAX", "중복 검사에서 '흔한 조각'으로 보고 열쇠에서 뺄 공통 문서 수 기준(개)")
    fuzzy_max: int | None = F(50000, "DEDUP_FUZZY_MAX", "문서가 이 수보다 많으면 이름 유사도 비교를 생략(개)")


class PipelineExtractOcr(Section):
    dpi: int | None = F(200, "OCR_DPI", "쪽 이미지 렌더링 해상도(DPI) — OCR·근거 이미지 좌표 환산에 씀", pinned="engine")
    max_pages: int | None = F(0, "OCR_MAX_PAGES", "문서당 OCR·VLM 쪽 수 상한(쪽, 0=제한 없음)", pinned="engine")
    table_grid: bool | None = F(True, "OCR_TABLE_GRID", "OCR 박스 좌표로 표 격자를 추정할지(=0이면 끔)", pinned="engine")
    threads: int | None = F(
        None,
        "OCR_THREADS",
        "rapidocr onnxruntime 스레드 수(0=onnxruntime 자동, 비우거나 숫자(0~9만) 아니면(auto 등) OMP_NUM_THREADS·CPU 몫)",
        pinned="engine",
        unset="nondigit",
    )


class PipelineExtractParallel(Section):
    io_workers: int | None = F(
        None, "PARSE_PARALLEL_IO_WORKERS", "문서 단위 병렬 파이프라인에서 받기·게시 포함 전체 동시 진행 수(개, workers 이상)"
    )
    pipeline: bool | None = F(
        False, "PARSE_PARALLEL_PIPELINE", "--source 파싱을 문서 단위 병렬 파이프라인(받기→파싱→게시→삭제)으로 돌릴지(=1)", on=("1",)
    )
    workers: int | None = F(None, "PARSE_PARALLEL_WORKERS", "문서 단위 병렬 파싱의 CPU 동시 문서 수(개)")


class PipelineExtractPrepare(Section):
    link: str | None = F("auto", "PREPARE_LINK", "회전 불필요 파일을 out으로 놓는 방식: auto|hardlink|symlink|copy")
    ocr: str | None = F("auto", "PREPARE_OCR", "회전 검토용 OCR 엔진 선택: auto|v1|v3(v3=rapidocr 3.x 강제)", blank="keep")
    rotate: bool | None = F(True, "PREPARE_ROTATE", "스캔 PDF 회전 검토(OCR 점수) 켬/끔 — 0이면 생략하고 그대로 복사", off=("0",))
    rotate_fast: bool | None = F(
        True, "PREPARE_ROTATE_FAST", "회전 검토 빠른 경로(앞쪽 공통 각도 힌트+축소 점검) 켬/끔 — 0이면 매 쪽 4방향 전체", off=("0",)
    )
    rotate_lead: int | None = F(3, "PREPARE_ROTATE_LEAD", "빠른 회전 검토에서 기대 각도를 정하는 문서 맨 앞 쪽 수(개)")
    rotate_probe_fast: int | None = F(480, "PREPARE_ROTATE_PROBE_FAST", "빠른 회전 검토의 축소 점검 이미지 크기(px)")
    rotate_s0_min: float | None = F(150.0, "PREPARE_ROTATE_S0_MIN", "빠른 회전 검토에서 힌트 각도를 믿는 최소 OCR 점수")


class PipelineExtractSource(Section):
    fetch_workers: int | None = F(1, "SOURCE_FETCH_WORKERS", "원본 문서 병렬 다운로드 스레드 수(개)")
    warm: str | None = F(None, "SOURCE_WARM", "미리받기(warm) 저장 폴더 — 비면 warm 기능 꺼짐")


class PipelineExtractStream(Section):
    batch: int | None = F(1, "PARSE_STREAM_BATCH", "스트리밍 파싱에서 한 바퀴에 받아 처리할 문서 수(건)")
    fingerprint: bool | None = F(
        True, "PARSE_STREAM_FINGERPRINT", "받은 파일 삭제 전 최소 지문을 dedup manifest에 남길지 — 0이면 끔", off=("0",)
    )
    stream: bool | None = F(False, "PARSE_STREAM", "스트리밍 파싱(묶음씩 받아 처리 후 즉시 삭제) 사용 — 1이면 켬", on=("1",))


class PipelineHostNightly(Section):
    enabled: bool | None = F(False, "NIGHTLY_ENABLED", "새벽 배치 타이머 켬/끔 — 1이면 실행, 그 외엔 로그 1줄 남기고 종료")
    max_new: int | None = F(2000, "NIGHTLY_MAX_NEW", "새벽 배치 parse가 밤당 처음 파싱할 문서 수 상한(건)")
    modules: WordList | None = F(
        ["parse", "publish", "structure", "load"], "NIGHTLY_MODULES", "새벽 배치가 차례로 돌릴 모듈(공백 구분 목록 — trigger.sh 기본)"
    )
    publish: bool | None = F(True, "NIGHTLY_PUBLISH", "새벽 배치에서 publish 단계 실행 여부 — 1이면 실행")


class PipelineLoadPublish(Section):
    bucket: str | None = F(None, "PM_BUCKET", "publish 대표 결과 업로드 Object Storage 버킷 이름(file://<폴더>면 로컬 가짜 저장소)")
    bucket_skip_overlap_check: bool | None = F(
        False, "PM_BUCKET_SKIP_OVERLAP_CHECK", "PM_BUCKET이 원천 원본 버킷과 같은지 검사 생략 — 1이면 생략", on=("1",)
    )
    parse_date: str | None = F(None, "PM_PARSE_DATE", "업로드 키의 날짜 폴더(YYYY-MM-DD) — 비면 오늘")
    path_map: CsvList | None = F([], "PM_PATH_MAP", "원본 키 앞부분 치환표 '이전=새' 쉼표 목록(결과 키 경로 구성용)")
    prefix: str | None = F(None, "PM_PREFIX", "버킷 안 업로드 경로 접두")
    source_system: str | None = F(
        "FileStorageMap", "PM_SOURCE_SYSTEM", "병렬 파싱 경로에서 게시 행에 기록하는 source_system 이름", blank="keep"
    )
    upload_raw: bool | None = F(
        True, "PM_UPLOAD_RAW", "rep.md 옆에 rep.json·엔진 원본·figures·meta도 올릴지 — 0이면 rep.md 등 옛 동작", off=("0",)
    )
    upload_statuses: CsvList | None = F(
        ["ok", "partial"], "PM_UPLOAD_STATUSES", "원본을 업로드할 파싱 상태 목록(콤마 — 비면 parsing_meta.DEFAULT_UPLOAD_STATUSES)"
    )


class PipelineServiceParseMcp(Section):
    REMOVED = frozenset({"ocr"})  # 사용자 10-29 — PARSE_MCP_OCR를 pipeline.extract.ocr_engine으로 합침(남아 있어도 경고만 — 한 판 동안)
    job_timeout_sec: float | None = F(600.0, "PARSE_MCP_JOB_TIMEOUT_SEC", "parse MCP 서비스 작업 1건 제한 시간(초)")
    jobs_dir: str | None = F(None, "PARSE_MCP_JOBS_DIR", "parse MCP 서비스 작업 기록 폴더")
    max_mb: float | None = F(64.0, "PARSE_MCP_MAX_MB", "parse MCP 서비스가 받는 파일 크기 상한(MB)")
    port: Port | None = F(8766, "PARSE_MCP_PORT", "parse MCP 서비스 포트")
    procs: int | None = F(None, "PARSE_MCP_PROCS", "parse MCP 서비스 엔진 묶음 병렬 프로세스 수(개)")
    queue_max: int | None = F(8, "PARSE_MCP_QUEUE_MAX", "parse MCP 서비스 대기 작업 상한(건)")
    roots: CsvList | None = F(
        None, "PARSE_MCP_ROOTS", "parse MCP 서비스가 읽을 수 있는 허용 루트 폴더(쉼표 목록) — 비면 코드가 정함(<서비스 폴더>/inbox)"
    )
    text_page_sec: float | None = F(
        1.0, "PARSE_MCP_TEXT_PAGE_SEC", "parse MCP 서비스 작업의 글자 엔진 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )
    token: SecretStr | None = F(None, "PARSE_MCP_TOKEN", "parse MCP 서비스 Bearer 토큰(MCP 서버 MCP_TOKEN과 같은 값)")
    warmup_sec: float | None = F(
        20.0,
        "PARSE_MCP_WARMUP_SEC",
        "parse MCP 서비스 작업의 첫 시도 제한 하한(초) — 새 프로세스에서 엔진을 처음 띄울 때(import·모델 적재) 여유",
    )
    vlm_page_sec: float | None = F(
        60.0, "PARSE_MCP_VLM_PAGE_SEC", "parse MCP 서비스 작업의 VLM 엔진 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )


class PipelineServiceTrigger(Section):
    allow_no_token: bool | None = F(
        False, "TRIGGER_ALLOW_NO_TOKEN", "TRIGGER_TOKEN 없이 무인증 시작 허용 — 1이면 허용(PC 전용, 경고)", on=("1",)
    )
    chain_structure_url: CsvList | None = F(
        [],
        "CHAIN_STRUCTURE_URL",
        "parse 성공 뒤 structure 작업을 올릴 트리거 서버 URL(쉼표로 여러 개) — 비면 이어 올리지 않음(서버 compose는 http://127.0.0.1:8771을 줌)",
    )
    client_timeout: float | None = F(10.0, "TRIGGER_CLIENT_TIMEOUT", "트리거 서버 CLI 클라이언트 HTTP 제한 시간(초)")
    host: str | None = F(
        "127.0.0.1", "TRIGGER_HOST", "트리거 서버 바인딩 주소 — 비우면 127.0.0.1(모든 인터페이스는 0.0.0.0을 명시 — C-37, 사용자 10-27)"
    )
    parse_port: Port | None = F(
        8770,
        "TRIGGER_PARSE_PORT",
        "parse 상주 트리거 서버 포트(--module parse — port 칸이 비었을 때, S7e2: 옛 compose가 TRIGGER_PORT로 넘기던 호스트 칸을 앱 칸으로)",
    )
    port: Port | None = F(
        None,
        "TRIGGER_PORT",
        "트리거 서버 포트 — 모듈 칸(parse_port·structure_port)을 따로 주지 않았을 때 두 모듈 모두 이 포트(PC 직접 실행만 — 이미지 안 상주 서버는 이 칸을 쓰지 않고 모듈 칸, VS7e2 R-1)",
    )
    structure_port: Port | None = F(
        8771, "TRIGGER_STRUCTURE_PORT", "structure 상주 트리거 서버 포트(--module structure — port 칸이 비었을 때, S7e2)"
    )
    queue_max: int | None = F(100, "TRIGGER_QUEUE_MAX", "트리거 서버 대기 작업 상한(건) — 넘으면 429")
    shutdown_timeout_sec: float | None = F(300.0, "TRIGGER_SHUTDOWN_TIMEOUT_SEC", "SIGTERM 뒤 실행 중 작업을 기다리는 한도(초)")
    socket_timeout_sec: int | None = F(30, "TRIGGER_SOCKET_TIMEOUT_SEC", "연결당 소켓 read 제한(초) — 느린 클라이언트 차단")
    token: SecretStr | None = F(None, "TRIGGER_TOKEN", "트리거 서버 Bearer 토큰 — 필수(없으면 시작 거부)")
    upload_max_mb: int | None = F(50, "TRIGGER_UPLOAD_MAX_MB", "트리거 서버 /upload 본문 크기 상한(MB)")


class PipelineTransformFigures(Section):
    chart_values_det: bool | None = F(
        True, "CHART_VALUES_DET", "차트 값을 결정적(규칙) 추출로 보정(=0이면 VLM 눈대중 값만 사용)", off=("0",)
    )
    diagram_edges_det: bool | None = F(
        True, "DIAGRAM_EDGES_DET", "도식 연결선을 결정적 추출로 보강(=0이면 pptx_xml·vlm 경로만)", off=("0",)
    )
    doc_shape_figure: bool | None = F(
        True, "PARSE_DOC_SHAPE_FIGURE", "docx·xlsx 도형 도식을 soffice로 렌더해 그림 기록(=0이면 끔)", off=("0",)
    )
    nested_figure: bool | None = F(
        True, "PARSE_NESTED_FIGURE", "그림 안 자식 그림 찾기·VLM 기록(=0이면 VLM 설정과 무관하게 안 함)", off=("0",)
    )
    ocr_fallback: bool | None = F(True, "FIG_OCR_FALLBACK", "VLM 결과가 빈 그림에 같은 crop OCR 글자를 대신 채움(=0이면 끔)", off=("0",))
    ocr_fallback_min_chars: int | None = F(
        10, "FIG_OCR_FALLBACK_MIN_CHARS", "OCR 대체 사용 최소 의미 글자 수(미만이면 로고·워터마크로 보고 버림)"
    )
    ocr_parallel: int | None = F(3, "FIGURES_OCR_PARALLEL", "그림 crop OCR 병렬 워커 수(OCR 대상 수가 상한)")
    ocrvlm_prompt: str | None = F(None, "OCRVLM_PROMPT", "OCR 전용 소형 VLM 엔진(ocr_vlm)에 보낼 지시문(모델 카드 권장값)", pinned="engine")
    overlay_cluster: bool | None = F(
        True, "FIG_OVERLAY_CLUSTER", "겹친 개체(그림+글상자·도형)를 한 묶음으로 찾아 기록(=0이면 그림마다 따로)", off=("0",)
    )
    page_child_dedup: bool | None = F(
        True, "FIG_PAGE_CHILD_DEDUP", "쪽 VLM이 이미 옮긴 쪽의 하위 그림은 검색 청크를 안 만듦(=0이면 옛 동작)", off=("0",)
    )
    pptx_convert_sec: int | None = F(60, "PARSE_PPTX_CONVERT_SEC", "soffice 문서→PDF 변환 시간 상한(초, 넘으면 해당 프로세스 종료)")
    pptx_render_max: int | None = F(10, "PARSE_PPTX_RENDER_MAX", "문서당 렌더·VLM 호출할 슬라이드·도형 쪽 수 상한")
    pptx_shapes_max: int | None = F(20, "PARSE_PPTX_SHAPES_MAX", "연결선 없는 도형 배치 슬라이드 후보 수 상한(0이면 이 사유는 안 봄)")
    pptx_slide_vlm: bool | None = F(True, "PARSE_PPTX_SLIDE_VLM", "pptx 슬라이드 쪽 VLM 전사 기능(=0이면 끔)", off=("0",))
    pptx_smartart_max: int | None = F(20, "PARSE_PPTX_SMARTART_MAX", "SmartArt 슬라이드 후보 수 상한(0이면 이 사유는 안 봄)")
    vector_box_diagram: bool | None = F(
        True, "VECTOR_BOX_DIAGRAM", "상자+직선만 있는 벡터 영역도 도식으로 인정(=0이면 표 격자로 버리는 옛 동작)", off=("0",)
    )
    vectors_max: int | None = F(20, "PARSE_VECTORS_MAX", "쪽 VLM 후보로 볼 벡터 도형 많은 쪽 수 상한(0이면 이 사유는 안 봄)")
    vlm_parallel: int | None = F(None, "FIGURES_VLM_PARALLEL", "그림 VLM 호출 병렬 워커 수")


class PipelineTransformRepresent(Section):
    context: bool | None = F(
        True, "PARSE_CONTEXT", "문서·쪽 신호 맥락(rep.context·decisions) 기록(=0이면 안 남김)", off=("", "0", "none", "false"), fold="lower"
    )
    fuse: bool | None = F(
        True, "PARSE_FUSE", "엔진별 결과 조각 투표(융합 P1) 사용(=0이면 끔)", off=("", "0", "none", "false"), fold="lower"
    )
    fuse_reread: bool | None = F(
        True,
        "PARSE_FUSE_REREAD",
        "융합 뒤 근소·미확인 자리를 다시 읽는 재판독(P2) 사용(=0이면 끔)",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    fuse_reread_p3: bool | None = F(
        True, "PARSE_FUSE_REREAD_P3", "재판독 3단계(그림 경계 OCR·VLM 선택형) 사용(=0이면 끔)", off=("", "0", "none", "false"), fold="lower"
    )
    fuse_signals: bool | None = F(
        True,
        "PARSE_FUSE_SIGNALS",
        "융합 점수에 사전·명부·교차 언급 신호를 반영(=0이면 기본 점수만)",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    post: CsvText | None = F(
        None,
        "PARSE_POST",
        "후보정 기능 선택: all(전부)|none(끔)|콤마 목록(vlm_page,supsub,charts,figures,context,attachments) — 없으면 자리마다 다름(파이프라인 all · parse MCP 서비스 supsub), 빈 값은 끔(옛 get(X, 'all')의 '' — blank keep) · 쓴 글자 그대로 rep.post.config에 남음(YAML 목록은 쉼표로 이음 — S7c2)",
        blank="keep",
    )
    qa_carry_forward: bool | None = F(
        True, "PARSE_QA_CARRY_FORWARD", "parse_qa가 지워진 문서 결과를 이전 qa.json에서 가져옴(=0이면 안 가져옴)", off=("0",)
    )
    qa_light: bool | None = F(False, "PARSE_QA_LIGHT", "=1이면 native 대비 풀문서 CER·순서 비교를 생략(경량화)", on=("1",))
    rep_select: str | None = F(None, "PARSE_REP_SELECT", "대표 엔진 선택 방식: first(첫 성공 엔진)|acc(정확도만)|그 외 best(정확도+풍부도)")
    reread_fallback_best: bool | None = F(
        True, "REREAD_FALLBACK_BEST", "P2도 못 가리면 산출 정확도 최고 엔진 후보로 대체(=0이면 안 함)", off=("0",)
    )
    shadow: bool | None = F(
        False, "PARSE_SHADOW", "그림자 모드(파싱 판단 규칙 vs LLM 제안 비교)를 켬(=1이면 켬)", off=("", "0", "none", "false"), fold="lower"
    )
    shadow_max: int | None = F(50, "PARSE_SHADOW_MAX", "그림자 모드 한 번에 훑는 문서 수 상한")
    standardize: bool | None = F(
        True, "PARSE_STANDARDIZE", "엔진 묶음 직후 기호 맵·첨자 표기 표준화(=0이면 끔)", off=("", "0", "none", "false"), fold="lower"
    )
    table_db: bool | None = F(True, "PARSE_TABLE_DB", "구조화 뒤 _rep의 표를 정형 저장소 doc_table·doc_cell로 적재(=0이면 끔)", off=("0",))
    table_inline: bool | None = F(
        True,
        "PARSE_TABLE_INLINE",
        "엔진별 표 그리드를 모아 본문 제자리에 GFM 표로 넣음(=0이면 대표 엔진 표만)",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    table_std: bool | None = F(
        True,
        "PARSE_TABLE_STD",
        "표를 표준 형식(tables_std 칸)으로 변환(=0이면 칸 자체가 안 생김)",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    table_stitch: bool | None = F(
        True,
        "PARSE_TABLE_STITCH",
        "쪽 경계에서 쪼개진 표를 이어 붙임(=0이면 쪽마다 쪼개진 채 둠)",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    reread: PipelineTransformRepresentReread = Field(default_factory=PipelineTransformRepresentReread)


class PipelineTransformStructure(Section):
    bundle_keep_empty_fig: bool | None = F(
        False, "BUNDLE_KEEP_EMPTY_FIG", "=1이면 내용이 빈 VLM 그림도 청크로 색인(되돌리기), 기본 0은 빈 그림 청크 안 만듦", on=("1",)
    )
    chunk_head: bool | None = F(True, "CHUNK_HEAD", "청크 앞에 [문서명·고객·절 제목] 머리말을 붙임(=0이면 안 붙임)", off=("0",))
    chunk_overlap: int | None = F(64, "CHUNK_OVERLAP", "고정 길이 청커(chunk_fixed512)의 청크 간 겹침 글자 수")
    chunk_size: int | None = F(None, "CHUNK_SIZE", "청크 목표 길이(글자) — 청커별 기본이 다름")
    chunk_table: str | None = F(None, "CHUNK_TABLE", "'rows'이면 큰 표를 행 묶음 단위로 쪼갬(그 외 값·미설정은 표를 통째로 둠)")
    chunk_table_rows: int | None = F(25, "CHUNK_TABLE_ROWS", "표를 쪼갤 때 청크당 행 수(CHUNK_TABLE=rows일 때만)")
    client_roster_seed: bool | None = F(
        True, "CLIENT_ROSTER_SEED", "고객 추론에 주요 바이오·제약사 공개 이름 seed 명부를 더함(=0이면 안 더함)", off=("0",)
    )
    draft_terms: bool | None = F(True, "DRAFT_TERMS", "새 회사 이름 후보를 용어집 draft로 자동 추가(=0이면 안 함)", off=("0",))
    edw_embed: str | None = F(None, "EDW_EMBED", "build_bundle 임베딩 방식(--embed 기본값) — api 또는 bge-m3 등")
    edw_summary_llm: bool | None = F(
        False, "EDW_SUMMARY_LLM", "=1이면 묶음 요약을 LLM으로 생성(--summary auto일 때만, 기본은 앞부분 발췌)", on=("1",)
    )
    embed: str | None = F(
        image_default("PIPE_EMBED"),
        "PIPE_EMBED",
        "구조화·적재에 쓸 임베딩 방식(api 등, none이면 임베딩 없음 — 이미지 안 기본 api: 옛 Dockerfile ENV, B-2)",
    )
    embed_batch: int | None = F(32, "EMBED_BATCH", "임베딩 API 한 번에 보내는 청크 수")
    embed_cache: str | None = F(None, "EMBED_CACHE", "임베딩 캐시 sqlite 경로(0 또는 빈 값이면 캐시 끔)")
    embed_concurrency: int | None = F(4, "EMBED_CONCURRENCY", "임베딩 호출 병렬 수(EMBED_BATCH 묶음을 동시에 전송)")
    embed_max_chars: int | None = F(8000, "EMBED_MAX_CHARS", "임베딩 입력 청크 최대 글자 수(넘으면 자름, 400 오류 방지 안전망)")
    embed_retry: int | None = F(2, "EMBED_RETRY", "임베딩 API 실패 시 재시도 횟수")
    page_chunk_max: int | None = F(None, "PAGE_CHUNK_MAX", "쪽 청크 최대 글자 수(임베딩 입력 한도 초과 방지)")
    wiki_domain_phrase: str | None = F(
        "바이오 CDMO", "WIKI_DOMAIN_PHRASE", "위키 초안 지시문의 도메인 예시 문구(기본 '바이오 CDMO')를 바꿈"
    )


class PipelineTransformVlm(Section):
    deadline: float | None = F(360.0, "VLM_DEADLINE", "VLM 호출 1건 제한 시간(초)")
    fig_kind: bool | None = F(True, "VLM_FIG_KIND", "그림 종류(차트·사진·글자 이미지) 분류를 기록(=0이면 분류 끔)", off=("0",))
    fig_min_px: int | None = F(64, "VLM_FIG_MIN_PX", "이 값보다 짧은 변의 그림은 VLM 대상에서 제외(픽셀)")
    fig_ocr_max: int | None = F(8, "VLM_FIG_OCR_MAX", "문서당 그림 crop OCR 횟수 상한(비용 가드)")
    fig_photo_area_min: float | None = F(0.03, "VLM_FIG_PHOTO_AREA_MIN", "사진류(photo)로 볼 그림의 최소 면적 비율(쪽 대비)")
    fig_photo_max_tokens: int | None = F(300, "VLM_FIG_PHOTO_MAX_TOKENS", "사진류 그림 VLM 응답 최대 토큰 수(한 줄 요약 유도)")
    fig_photo_ocr_max: int | None = F(5, "VLM_FIG_PHOTO_OCR_MAX", "crop OCR 글자 수가 이 값 이하(+면적 충분)이면 사진류로 분류")
    fig_select: bool | None = F(True, "VLM_FIG_SELECT", "VLM 보낼 그림을 크기·반복 기준으로 선별(=0이면 문서 순서로 상한만)", off=("0",))
    fig_text_ocr_min: int | None = F(
        200, "VLM_FIG_TEXT_OCR_MIN", "crop OCR 글자 수(공백 제외)가 이 값 이상이면 글자 이미지(text_image)로 분류"
    )
    fig_text_skip: bool | None = F(False, "VLM_FIG_TEXT_SKIP", "=1이면 글자 이미지(text_image)로 분류된 그림은 VLM 호출 생략", off=("0",))
    figures_max: int | None = F(20, "VLM_FIGURES_MAX", "문서당 VLM에 보낼 그림 수 상한(0이면 VLM 안 부름)")
    global_concurrency: int | None = F(12, "VLM_GLOBAL_CONCURRENCY", "모든 VLM 호출의 전역 동시 실행 수 합 상한")
    page_concurrency: int | None = F(None, "VLM_PAGE_CONCURRENCY", "쪽 VLM 병렬 워커 수 최대값")
    page_max: int | None = F(None, "VLM_PAGE_MAX", "문서당 쪽 VLM으로 읽을 쪽 수 상한(빈 값=전부, 0=쪽 VLM 끔)")
    page_min_concurrency: int | None = F(2, "VLM_PAGE_MIN_CONCURRENCY", "쪽 VLM 적응형 병렬에서 느릴 때 줄일 수 있는 최소 워커 수")
    page_slow: float | None = F(60.0, "VLM_PAGE_SLOW", "쪽 VLM 호출이 이 시간(초) 넘으면 다음 배치 병렬 수를 줄임")


class PipelineDev(Section):
    REMOVED = frozenset({"parse_agent_fake"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    allow_common_mismatch: bool | None = F(
        False, "ALLOW_COMMON_MISMATCH", "앞 모듈 결과의 공통 코드 지문이 달라도 계속 진행할지(=1 계속 / 그 외 중단)", on=("1",)
    )
    check_env_any_py: bool | None = F(
        False, "CHECK_ENV_ANY_PY", "check_env가 시스템 python에서도 멈추지 않고 계속할지(=1 계속 / 그 외 중단)", on=("1",)
    )
    parallel_test_crash: bool | None = F(
        False, "PARSE_PARALLEL_TEST_CRASH", "시험용 — =1이면 문서 병렬 파싱의 첫 문서에서 강제 종료(os._exit 17)", on=("1",)
    )
    stream_test_crash: bool | None = F(
        False, "PARSE_STREAM_TEST_CRASH", "시험용 — =1이면 스트리밍 파싱의 첫 묶음에서 강제 종료(os._exit 17)", on=("1",)
    )
    test_min_docs: int | None = F(50, "TEST_MIN_DOCS", "시험 모드(--mode test)에서 표본 추출을 시작하는 최소 문서 수(개)")
    test_per_type: int | None = F(5, "TEST_PER_TYPE", "시험 모드 표본에서 확장자별로 고르는 문서 수(개)")


class PipelineEval(Section):
    REMOVED = frozenset({"phase_report_legacy"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    diagram_raster_vlm: bool | None = F(
        False, "DIAGRAM_RASTER_VLM", "도식 간선 채점에서 raster 케이스에 실제 VLM을 부를지(=1 실호출 / 그 외 가짜)", on=("1",)
    )
    e2e_qa_set: str | None = F(None, "E2E_QA_SET", "e2e 시험 질문 묶음 이름(valid_env/unstructured/<이름>/qa.json)")
    e2e_questions: str | None = F(None, "E2E_QUESTIONS", "e2e 질문 파일 경로(또는 auto = 그 자리에서 생성)")
    gold_draft_max_pages: int | None = F(30, "GOLD_DRAFT_MAX_PAGES", "정답 초안 생성(gold_draft)에서 문서당 처리할 쪽 수 상한(쪽)")
    gold_draft_mermaid_check: bool | None = F(
        True,
        "GOLD_DRAFT_MERMAID_CHECK",
        "정답 초안의 Mermaid 블록 2차 점검을 켤지(0/false/no면 끔)",
        off=("0", "false", "no"),
        fold="strip",
    )
    qa_draft_max_pages: int | None = F(20, "QA_DRAFT_MAX_PAGES", "질문 초안 생성(qa_draft)에서 문서당 처리할 쪽 수 상한(쪽)")
    qa_draft_per_page: int | None = F(5, "QA_DRAFT_PER_PAGE", "질문 초안 생성에서 쪽당 질문 수 상한(개)")
    review_max_rounds: int | None = F(2, "REVIEW_MAX_ROUNDS", "도식 검토 루프의 최대 재추출 횟수(회)")
    score_table_judge: str | None = F("0", "SCORE_TABLE_JUDGE", "표 구조 채점의 경계 표 판정자(0 없음 | llm 경계 표만 LLM 판정)")


class PipelineExtract(Section):
    REMOVED = frozenset({"phases", "phase_sec"})  # 사용자 10-29 — phase 없앰(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    auto_reparse_changed: bool | None = F(
        False, "AUTO_REPARSE_CHANGED", "야간 계획에서 바뀐 문서(changed) 전체를 다시 파싱할지(=1 재파싱)", on=("1",)
    )
    dedup_scan: bool | None = F(
        False,
        "PARSE_DEDUP_SCAN",
        "스캔 쪽의 OCR 본문과 쪽 VLM 전사 중복을 쪽마다 하나로 정리할지",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    disk_free_warn_gb: float | None = F(10.0, "DISK_FREE_WARN_GB", "디스크 남은 용량이 이 값(GB)보다 작으면 보관 용량 경고 출력")
    doc_parallel: int | None = F(1, "PARSE_DOC_PARALLEL", "대표 결과 만들기(represent)에서 문서 병렬 처리 스레드 수(개)")
    engine_cache_warn_gb: float | None = F(20.0, "ENGINE_CACHE_WARN_GB", "엔진별 중간 결과 합계가 이 값(GB)을 넘으면 보관 용량 경고 출력")
    engine_retry: int | None = F(1, "PARSE_ENGINE_RETRY", "엔진 별도 프로세스가 비정상 종료했을 때 바로 다시 시도할 횟수(회)")
    engine_scope: str | None = F(
        None, "PARSE_ENGINE_SCOPE", "문서마다 돌릴 엔진 범위(stack = 형식별 stack.json 목록만 / all = 등록 엔진 전부)"
    )
    fill_merged: bool | None = F(True, "PARSE_FILL_MERGED", "표에서 병합 셀이 덮은 빈 칸을 원본 칸 값으로 채울지", pinned="engine")
    hidden_overlap_max: int | None = F(
        20, "PARSE_HIDDEN_OVERLAP_MAX", "'숨은 글자-그림 겹침' 신호로 쪽 VLM 후보에 올릴 쪽 수 상한(쪽, 0=끔)"
    )
    input_source: str | None = F(None, "PARSE_SOURCE", "파싱 원본 위치: 폴더·s3://버킷/접두·rdb:csv:경로·rdb:표")
    isolate_overhead: float | None = F(10.0, "PARSE_ISOLATE_OVERHEAD", "별도 프로세스 실행 시 쪽당 제한 시간에 더해 줄 시작 여유(초)")
    kreuzberg_prose_filter: bool | None = F(
        True, "KREUZBERG_PROSE_FILTER", "kreuzberg가 평문을 표로 오인한 것을 거를지(=0이면 끔)", pinned="engine"
    )
    low_priority: bool | None = F(
        True,
        "PARSE_LOW_PRIORITY",
        "엔진 자식 프로세스를 낮은 우선순위로(POSIX nice +10 · Windows BELOW_NORMAL) — parse MCP 서비스 작업은 끔(=0)",
        off=("0",),
    )
    max_file_mb: float | None = F(0.0, "MAX_FILE_MB", "이 크기(MB)를 넘는 문서는 파싱에서 건너뜀(0=제한 없음)")
    max_new: int | None = F(0, "PARSE_MAX_NEW", "이번 실행에서 처음 파싱할 새 문서 수 상한(개, 0=제한 없음)")
    merge_pages: bool | None = F(True, "PARSE_MERGE_PAGES", "엔진 간 쪽·문단 단위 보정(쪽 합치기)을 켤지(=0이면 끔)", off=("0",))
    ocr_engine: bool | None = F(
        False,
        "PARSE_OCR_ENGINE",
        "OCR 엔진(rapidocr·rapidocr_ko)을 파싱 엔진으로 돌릴지(=1 켬) — 끄면 이미지·스캔 문서는 VLM 엔진만",
        on=("1",),
    )
    ocr_gt_max: int | None = F(20, "PARSE_OCR_GT_MAX", "'OCR 글자 수가 글자층의 3배 이상'인 쪽을 쪽 VLM 후보로 올릴 상한(쪽, 0=끔)")
    page_scan: bool | None = F(True, "PARSE_PAGE_SCAN", "글자 PDF 안의 스캔 쪽을 신호로 찾아 쪽 VLM에 보낼지(=0이면 끔)", off=("0",))
    prefetch_workers: int | None = F(2, "PREFETCH_WORKERS", "미리받기(warm) 명령의 동시 다운로드 스레드 수(개)")
    rapidocr_page_workers: int | None = F(
        1, "RAPIDOCR_PAGE_WORKERS", "rapidocr 엔진이 문서 안 쪽별 OCR을 병렬로 돌리는 스레드 수(개)", pinned="engine"
    )
    rotated_max: int | None = F(20, "PARSE_ROTATED_MAX", "쪽 VLM 후보로 올릴 '회전된 쪽' 상한(쪽 수) — 0이면 rotation.csv를 안 읽음")
    scan_fill: bool | None = F(
        True,
        "PARSE_SCAN_FILL",
        "스캔 쪽을 OCR로 채우는 대표 결과 보정 켬/끔 — 0이면 이전 동작과 바이트 동일",
        off=("", "0", "none", "false"),
        fold="lower",
    )
    signal_ocr: bool | None = F(False, "PARSE_SIGNAL_OCR", "쪽 신호 계산에 렌더 OCR 글자 수를 채울지 — 1이면 켬(비용 큼)", on=("1",))
    skipped_log: str | None = F(None, "PARSE_SKIPPED_LOG", "건너뛴 문서(암호 PDF 등) 기록 jsonl 경로")
    source_limit: int | None = F(0, "PARSE_SOURCE_LIMIT", "원본에서 처리할 문서 건수 상한(0=제한 없음)")
    text_page_sec: float | None = F(
        10.0, "PARSE_TEXT_PAGE_SEC", "글자 엔진(VLM 아님) 문서×엔진 1건의 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )
    table_grid_max_rows: int | None = F(
        2000, "TABLE_GRID_MAX_ROWS", "표 grid JSON에 담는 최대 행 수(개) — 넘으면 앞부분만 자르고 truncated 표시", pinned="engine"
    )
    vlm_page_sec: float | None = F(120.0, "PARSE_VLM_PAGE_SEC", "VLM 엔진 문서×엔진 1건의 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더")
    warmup_sec: float | None = F(60.0, "PARSE_WARMUP_SEC", "엔진 첫 문서의 제한 시간 하한(초) — import·모델 적재 여유")
    attach: PipelineExtractAttach = Field(default_factory=PipelineExtractAttach)
    cache: PipelineExtractCache = Field(default_factory=PipelineExtractCache)
    dedup: PipelineExtractDedup = Field(default_factory=PipelineExtractDedup)
    ocr: PipelineExtractOcr = Field(default_factory=PipelineExtractOcr)
    parallel: PipelineExtractParallel = Field(default_factory=PipelineExtractParallel)
    prepare: PipelineExtractPrepare = Field(default_factory=PipelineExtractPrepare)
    source: PipelineExtractSource = Field(default_factory=PipelineExtractSource)
    stream: PipelineExtractStream = Field(default_factory=PipelineExtractStream)


class PipelineHostRunDocs(Section):
    """문서별 flow 러너(deploy/host/scripts/run_docs.py — 호스트에서 글자 그대로 읽음) 레인·대기열(사용자 10-29, docs/prd/runner.md rn-01·rn-02).
    기본값은 run_docs.py RUN_DOCS_DEFAULTS와 같다(tests/general/deploy/test_run_docs.py가 대조)."""

    warm: int | None = F(20, "RUN_DOCS_WARM", "진입 대기열 — 미리 받아 둘 문서 수(진행 중 제외, 명령 인자 --warm이 덮음)")
    struct_workers: int | None = F(2, "RUN_DOCS_STRUCT_WORKERS", "구조화·적재 스레드 수(명령 인자 --struct-workers가 덮음)")
    struct_backlog: int | None = F(
        None, "RUN_DOCS_STRUCT_BACKLOG", "중간 대기열 상한(파싱 끝·구조화 대기 문서 수) — 비우면 구조화 스레드 × 2, 0이면 상한 없음"
    )
    vlm_cap: int | None = F(2, "RUN_DOCS_VLM_CAP", "vlm 레인 문서 동시 파싱 상한(gpu 예산)")
    light_dedicated: int | None = F(1, "RUN_DOCS_LIGHT_DEDICATED", "light 레인 전담 워커 수(light 문서만)")
    light_shared: int | None = F(1, "RUN_DOCS_LIGHT_SHARED", "light 레인 공유 워커 수(light 먼저, 비면 가장 긴 다른 레인에서 가져옴)")
    medium_dedicated: int | None = F(1, "RUN_DOCS_MEDIUM_DEDICATED", "medium 레인 전담 워커 수(MCP 업로드 처리 중에는 쉼)")
    medium_shared: int | None = F(1, "RUN_DOCS_MEDIUM_SHARED", "medium 레인 공유 워커 수(medium 먼저, 비면 다른 레인)")
    vlm_dedicated: int | None = F(1, "RUN_DOCS_VLM_DEDICATED", "vlm 레인 전담 워커 수(vlm 문서만)")
    vlm_shared: int | None = F(1, "RUN_DOCS_VLM_SHARED", "vlm 레인 공유 워커 수(vlm 먼저, 비면 다른 레인)")


class PipelineHost(Section):
    gold_dir: str | None = F(
        None,
        "GOLD_DIR",
        "호스트의 사람 정답(gold) 폴더(서버 경로) — run_tool.sh가 컨테이너 /data/gold로 읽기 전용 마운트하는 원본(T-21 — 코드가 읽는 칸은 pipeline.paths.gold_dir)",
    )
    image: str | None = F(None, "DATA_PIPELINE_IMAGE", "data-pipeline 이미지 이름:태그(compose 필수 변수)")
    index_conf_dir: str | None = F(
        None, "INDEX_CONF_DIR", "색인 설정 json 폴더(호스트 경로) — 컨테이너 /app/output/index-conf에 읽기 전용 연결"
    )
    load_cpus: float | None = F(1.0, "LOAD_CPUS", "load 컨테이너 CPU 개수 상한(개)")
    load_mem_limit: str | None = F("4g", "LOAD_MEM_LIMIT", "load 컨테이너 메모리·스왑 상한(docker 형식, 예 4g)")
    parse_cpus: float | None = F(3.0, "PARSE_CPUS", "parse 컨테이너(1회 job·상주 트리거) CPU 개수 상한(개)")
    parse_mem_limit: str | None = F("16g", "PARSE_MEM_LIMIT", "parse 컨테이너 메모리·스왑 상한(docker 형식)")
    publish_cpus: float | None = F(1.0, "PUBLISH_CPUS", "publish 컨테이너 CPU 개수 상한(개)")
    publish_mem_limit: str | None = F("2g", "PUBLISH_MEM_LIMIT", "publish 컨테이너 메모리·스왑 상한(docker 형식)")
    run_docs_dir: str | None = F(
        None,
        "RUN_DOCS_DIR",
        "문서별 flow 러너(deploy/host/scripts/run_docs.py) 작업 폴더(호스트 — 진행 기록 batch_progress/·batches/) — 비우면 스크립트 옆 test_space/(C-29 ⑨, S7e1)",
    )
    structure_cpus: float | None = F(2.0, "STRUCTURE_CPUS", "structure 컨테이너(job·상주 트리거·색인) CPU 개수 상한(개)")
    structure_mem_limit: str | None = F("8g", "STRUCTURE_MEM_LIMIT", "structure 컨테이너 메모리·스왑 상한(docker 형식)")
    nightly: PipelineHostNightly = Field(default_factory=PipelineHostNightly)
    run_docs: PipelineHostRunDocs = Field(default_factory=PipelineHostRunDocs)


class PipelineLoad(Section):
    REMOVED = frozenset(
        {"structure_target", "edw_load"}
    )  # 사용자 10-29(edw_load — EDW 벡터 경로 삭제, ops.md#op-03) — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    bm25_stat_rebuild: bool | None = F(False, "BM25_STAT_REBUILD", "적재 때 키워드 문서 빈도를 전체 다시 셈 — 1이면 켬", on=("1",))
    bm25_threads: int | None = F(4, "BM25_THREADS", "BM25 항목(term,tf) 계산 병렬 스레드 수(개)")
    edw_path_prefix: str | None = F(None, "EDW_PATH_PREFIX", "저장소 doc.file_path에 기록할 원본 경로 접두(서버의 실제 보관 위치)")
    index_lock_stale_sec: float | None = F(21600.0, "INDEX_LOCK_STALE_SEC", "색인 빌드 잠금 파일을 죽은 빌드로 보고 회수하는 경과 시간(초)")
    pg_create_extension: bool | None = F(
        False, "PG_CREATE_EXTENSION", "deploy 때 vector 확장 직접 생성 시도 — 1이면 켬(공유 PG에서는 금지)", on=("1",)
    )
    prune_force: bool | None = F(False, "PRUNE_FORCE", "옛 기록 정리 안전장치(묶음 문서 수 비율 미달 거부) 무시 — 1이면 진행", on=("1",))
    prune_min_ratio: float | None = F(0.5, "PRUNE_MIN_RATIO", "옛 기록 정리 허용 최소 비율(묶음 문서 수 / 저장 문서 수)")
    publish: PipelineLoadPublish = Field(default_factory=PipelineLoadPublish)


class PipelineNight(Section):
    deadline: str | None = F("06:30", "NIGHT_DEADLINE", "새벽 파싱 배치 마감 시각(HH:MM, 컨테이너 TZ 기준)", blank="keep")
    parse_deadline: str | None = F(None, "PARSE_DEADLINE", "새벽 배치 parse 단계 마감 시각(HH:MM) — 비우면 무제한")
    vlm_concurrency: int | None = F(8, "NIGHT_VLM_CONCURRENCY", "새벽 배치: 문서 하나의 쪽 VLM 동시 요청 수(개)")
    workers: int | None = F(4, "NIGHT_WORKERS", "새벽 배치: 동시 처리 문서 수(개)")


class PipelinePaths(Section):
    REMOVED = frozenset(
        {"mineru_bin", "paddle_python", "soffice_candidates"}
    )  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    file_meta_path: str | None = F(None, "FILE_META_PATH", "EDW 파일 메타 JSONL 경로(s3_key → 메타)")
    gold_dir: str | None = F(
        None,
        "GOLD_DIR",
        "사람 정답(gold) 폴더 — score_gold·점검 도구의 기본 입력(코드가 읽는 경로 — 컨테이너 안은 run_tool.sh가 /data/gold로 줌, 원본은 pipeline.host.gold_dir — T-21)",
    )
    images_root: str | None = F(None, "PARSE_IMAGES_ROOT", "그림 PNG·index.jsonl 저장 루트")
    index_conf: str | None = F(None, "INDEX_CONF", "색인 설정 JSON 경로(있으면 색인 모듈로 구조화)")
    out_root: str | None = F(None, "PIPE_OUT_ROOT", "파이프라인 출력 루트(output)")
    parse_tmp: str | None = F(None, "PARSE_TMP", "스트리밍·병렬 파싱 임시 폴더 — output 아래 2단 이상 하위만 허용")
    raw_root: str | None = F(None, "PARSE_RAW_ROOT", "P0 원본 층(raw/VLM) 캐시 저장소 루트")
    report_digest_dir: str | None = F(None, "REPORT_DIGEST_DIR", "run_board 날짜·판 요약 폴더 루트(비우면 요약 안 만듦)")
    soffice_bin: str | None = F(
        image_default("SOFFICE_BIN"),
        "SOFFICE_BIN",
        "LibreOffice soffice 실행 파일 경로 — PATH·흔한 경로보다 먼저 봄(pipeline 이미지 안 기본 /usr/bin/soffice — 옛 Dockerfile ENV, B-2)",
    )
    stack_snapshot: str | None = F(
        None, "STACK_SNAPSHOT", "엔진 구성 사본 파일(내부 신호 — 진입점이 활성 판에서 만들어 자식에 넘김, 사람이 쓰지 않음 · S8b)"
    )


class PipelineConnections(Section):
    REMOVED = frozenset({"openviking"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    graphiti: PipelineConnectionsGraphiti = Field(default_factory=PipelineConnectionsGraphiti)
    rdb: PipelineConnectionsRdb = Field(default_factory=PipelineConnectionsRdb)
    secure_doc: PipelineConnectionsSecureDoc = Field(default_factory=PipelineConnectionsSecureDoc)


class PipelineService(Section):
    parse_mcp: PipelineServiceParseMcp = Field(default_factory=PipelineServiceParseMcp)
    trigger: PipelineServiceTrigger = Field(default_factory=PipelineServiceTrigger)


class PipelineTransform(Section):
    REMOVED = frozenset({"agent"})  # 사용자 10-29 — 지운 칸·절(옛 서버 설정 파일에 남아 있어도 경고만 — 한 판 동안)
    figures: PipelineTransformFigures = Field(default_factory=PipelineTransformFigures)
    represent: PipelineTransformRepresent = Field(default_factory=PipelineTransformRepresent)
    structure: PipelineTransformStructure = Field(default_factory=PipelineTransformStructure)
    vlm: PipelineTransformVlm = Field(default_factory=PipelineTransformVlm)


class PipelineSettings(Section):
    connections: PipelineConnections = Field(default_factory=PipelineConnections)
    dev: PipelineDev = Field(default_factory=PipelineDev)
    eval: PipelineEval = Field(default_factory=PipelineEval)
    extract: PipelineExtract = Field(default_factory=PipelineExtract)
    host: PipelineHost = Field(default_factory=PipelineHost)
    load: PipelineLoad = Field(default_factory=PipelineLoad)
    night: PipelineNight = Field(default_factory=PipelineNight)
    paths: PipelinePaths = Field(default_factory=PipelinePaths)
    service: PipelineService = Field(default_factory=PipelineService)
    transform: PipelineTransform = Field(default_factory=PipelineTransform)


class PipelineAppSettings(AppSettings):
    common: CommonSettings = Field(default_factory=CommonSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)


SETTINGS = Cache(PipelineAppSettings)


class PipelineEnvSettings(AppSettings):
    """pipeline 절만 — pipeline 코드가 읽는 뿌리(PIPE, S7c — S7e2부터 설정 파일 기반). common 칸은 common.config.settings.cfg()."""

    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)


PIPE = Cache(PipelineEnvSettings)
_VIEW = EnvView(PIPE, "pipeline")


def cfg():
    """pipeline 절 설정 객체(PipelineSettings) — 설정 파일 기반 캐시(위 모듈 설명)."""
    return PIPE.get().pipeline


by_env, given, dropped, checked = _VIEW.by_env, _VIEW.given, _VIEW.dropped, _VIEW.checked  # common.config.settings의 같은 이름 설명

GOLD_MOUNT = Path(
    IMAGE_PATHS["gold_mount"]
)  # run_tool.sh가 사람 정답 폴더를 붙이는 컨테이너 자리(이미지 약속 — 표는 settings.IMAGE_PATHS 한 곳, R-12)


def gold_dir():
    """사람 정답 폴더 — pipeline.paths.gold_dir, 비었고 이미지 안이며 /data/gold가 붙어 있으면 그것(S7e2 — 옛 run_tool.sh `-e GOLD_DIR=/data/gold`
    자리, 사용자 10-28)."""
    v = cfg().paths.gold_dir
    if not v and IN_IMAGE and GOLD_MOUNT.is_dir():
        return str(GOLD_MOUNT)
    return v


def stack_path():
    """엔진 구성 파일(S8b — D-031 Q10 a): 진입점(pipeline/stackcfg.py)이 활성 판에서 만든 사본(STACK_SNAPSHOT). 없으면 PC(paths.LOCAL_RUN)는
    PC 파일(common.paths.stack_file — 비우면 resources/config/pipeline_stack.json), 서버는 거부(종료 2 — git 기본 파일로 넘어가지 않게, Q7).
    층 파일(run_all·attachments)이 이것만 부른다 — 이 모듈은 층의 code_fp 의존이 아니다(common 아래만 셈)."""
    snap = cfg().paths.stack_snapshot
    if snap:
        return Path(snap)
    from common.core import paths

    if paths.LOCAL_RUN:
        from common.store.db import cfgtables  # PC 파일 자리 규칙 한 곳(이 모듈은 층의 code_fp 의존이 아님)

        return cfgtables.pc_file("stack")
    print(
        "[엔진 구성] 사본 없음(STACK_SNAPSHOT) — 서버는 진입점(pipeline.cli·stream·parse_parallel·mcp_parse_service·load.index)으로 "
        "실행해야 판 표 활성 판의 사본을 만든다. 도구를 따로 돌릴 때는 사본을 먼저 만들어 넘긴다: "
        "S=$(python -m pipeline.stackcfg --path <결과 폴더>) 뒤 represent·build_bundle은 --stack $S, 그 밖은 --set을 받는 진입점(pipeline.cli 등 — D-032)에 --set STACK_SNAPSHOT=$S(VS8b R-4)",
        file=sys.stderr,
        flush=True,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    from common.config import show

    sys.exit(show.main(PipelineAppSettings, sys.argv[1:], prog="python -m pipeline.config"))
