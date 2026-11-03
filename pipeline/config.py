"""pipeline 앱 설정 — settings.yaml의 common + pipeline 절만 읽는다(S7a, refactor_plan 5-2 · D-015). 다른 앱(mcp) 절은 무시.
pipeline 코드가 읽는 객체는 설정 파일 기반 캐시 PIPE다(S7e2 — 전환 다리 없앰: env의 옛 이름은 읽지 않음, 신호 SETTINGS_FILE·RUN_ENV만):
  `from pipeline import config as pc` → `pc.cfg().extract.max_new`(pipeline 절) · `pc.given("PM_BUCKET")`(준 값만) · `pc.checked(X)` ·
  `pc.by_env(f"{p}_X")` · 시험 `with pc.PIPE.env(PARSE_TMP=…, PARSE_CACHE_MAX_GB=None):`(설정 위에 옛 env 이름으로 덮음 — os.environ 안 건드림).
  common 칸은 `common.config.settings.cfg()`로(COMMON). 값을 바꿔 자식에 넘길 때는 `settings.put()`·`settings.child_env()`(덮기 파일).
SETTINGS(common + pipeline 절)는 확인 명령(python -m pipeline.config)·시험용. 칸 표는 refactor_plan 부록 D.
사용: python -m pipeline.config [--file 경로]   # 읽어서 요약(비밀 가림) · export --section pipeline.host …
"""

import sys
from pathlib import Path

from pydantic import Field, SecretStr, field_validator  # 칸 형식

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


class PipelineConnectionsRdb(Section):
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
    parse_cache_max_gb: float | None = F(
        5.0, "PARSE_CACHE_MAX_GB", "재판독 중간 캐시 3종 합계 용량 상한(GB, 넘으면 오래된 것부터 삭제, 0=끔)"
    )


class PipelineExtractDedup(Section):
    """칸 없음 — 지운 칸만 남은 절(이름은 layout.REMOVED — 옛 파일이 경고만 받게)."""


class PipelineExtractOcr(Section):
    dpi: int | None = F(200, "OCR_DPI", "쪽 이미지 렌더링 해상도(DPI) — OCR·근거 이미지 좌표 환산에 씀")
    max_pages: int | None = F(0, "OCR_MAX_PAGES", "문서당 OCR·VLM 쪽 수 상한(쪽, 0=제한 없음)")
    table_grid: bool | None = F(True, "OCR_TABLE_GRID", "OCR 박스 좌표로 표 격자를 추정할지(=0이면 끔)")
    threads: int | None = F(
        None,
        "OCR_THREADS",
        "rapidocr onnxruntime 스레드 수(0=onnxruntime 자동, 비우거나 숫자(0~9만) 아니면(auto 등) OMP_NUM_THREADS·CPU 몫)",
        unset="nondigit",
    )


class PipelineExtractPrepare(Section):
    link: str | None = F("auto", "PREPARE_LINK", "회전 불필요 파일을 out으로 놓는 방식: auto|hardlink|symlink|copy")
    rotate: bool | None = F(
        False,
        "PREPARE_ROTATE",
        "이미지·스캔 PDF 쪽 방향 바로잡기 켬/끔 — 켜면 4방향 OCR 점수를 동시에 재 가장 높은 방향으로 돌림, 끄면 회전용 OCR 없이 그대로(사용자 11-02 기본 꺼짐)",
        off=("0",),
    )


class PipelineExtractSource(Section):
    fetch_workers: int | None = F(1, "SOURCE_FETCH_WORKERS", "원본 문서 병렬 다운로드 스레드 수(개)")
    warm: str | None = F(None, "SOURCE_WARM", "미리받기(warm) 저장 폴더 — 비면 warm 기능 꺼짐")


class PipelineHostNightly(Section):
    time: str | None = F(
        None,
        "NIGHTLY_TIME",
        "새벽 배치 시작 시각(HH:MM, 서버 시간) — 비우면 새벽 배치 없음. 타이머가 5분마다 깨워 이 시각부터 5분 안이면 시작(trigger.sh scheduled)",
        pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$",  # 틀린 꼴은 설정을 읽을 때 거부(타이머가 5분마다 실패로 남기지 않게)
    )
    # 사용자 11-02 — 시작 시각·문서 수 상한·마감 시각 셋이 모두 있어야 새벽 배치가 돈다(하나라도 비면 trigger.sh scheduled가 조용히 끝)
    max_docs: int | None = F(
        None, "NIGHTLY_MAX_DOCS", "새벽 배치 한 번에 처리할 새 문서 수 상한(이미 끝난 문서 뺀 뒤) — 비우면 새벽 배치 없음", ge=1
    )
    deadline: str | None = F(
        None,
        "NIGHTLY_DEADLINE",
        "새벽 배치 마감 시각(HH:MM, 서버 시간) — 지나면 새 문서를 받기 시작하지 않음(받은 문서는 끝까지). 비우면 새벽 배치 없음",
        pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$",
    )

    @field_validator("time", "deadline", "max_docs", mode="before")
    @classmethod
    def _blank_is_off(cls, v):
        """빈 글자·공백만 = 새벽 배치 없음(None) — sample·손으로 쓴 settings.yaml의 `time: ""`가 꼴 검사에 걸려 시작을 막지 않게(PR #44 리뷰)."""
        return None if isinstance(v, str) and not v.strip() else v


class PipelineLoadPublish(Section):
    bucket: str | None = F(None, "PM_BUCKET", "publish 대표 결과 업로드 Object Storage 버킷 이름(file://<폴더>면 로컬 가짜 저장소)")
    bucket_skip_overlap_check: bool | None = F(
        False, "PM_BUCKET_SKIP_OVERLAP_CHECK", "PM_BUCKET이 원천 원본 버킷과 같은지 검사 생략 — 1이면 생략", on=("1",)
    )
    parse_date: str | None = F(None, "PM_PARSE_DATE", "업로드 키의 날짜 폴더(YYYY-MM-DD) — 비면 오늘")
    path_map: CsvList | None = F([], "PM_PATH_MAP", "원본 키 앞부분 치환표 '이전=새' 쉼표 목록(결과 키 경로 구성용)")
    prefix: str | None = F(None, "PM_PREFIX", "버킷 안 업로드 경로 접두")
    upload_statuses: CsvList | None = F(
        ["ok", "partial"], "PM_UPLOAD_STATUSES", "원본을 업로드할 파싱 상태 목록(콤마 — 비면 parsing_meta.DEFAULT_UPLOAD_STATUSES)"
    )


class PipelineServiceParseMcp(Section):
    job_timeout_sec: float | None = F(600.0, "PARSE_MCP_JOB_TIMEOUT_SEC", "parse MCP 서비스 작업 1건 제한 시간(초)")
    jobs_dir: str | None = F(None, "PARSE_MCP_JOBS_DIR", "parse MCP 서비스 작업 기록 폴더")
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


class PipelineTransformFigures(Section):
    ocr_fallback_min_chars: int | None = F(
        10, "FIG_OCR_FALLBACK_MIN_CHARS", "OCR 대체 사용 최소 의미 글자 수(미만이면 로고·워터마크로 보고 버림)"
    )
    ocr_parallel: int | None = F(3, "FIGURES_OCR_PARALLEL", "그림 crop OCR 병렬 워커 수(OCR 대상 수가 상한)")
    pptx_convert_sec: int | None = F(60, "PARSE_PPTX_CONVERT_SEC", "soffice 문서→PDF 변환 시간 상한(초, 넘으면 해당 프로세스 종료)")
    pptx_render_max: int | None = F(10, "PARSE_PPTX_RENDER_MAX", "문서당 렌더·VLM 호출할 슬라이드·도형 쪽 수 상한")
    pptx_shapes_max: int | None = F(20, "PARSE_PPTX_SHAPES_MAX", "연결선 없는 도형 배치 슬라이드 후보 수 상한(0이면 이 사유는 안 봄)")
    pptx_smartart_max: int | None = F(20, "PARSE_PPTX_SMARTART_MAX", "SmartArt 슬라이드 후보 수 상한(0이면 이 사유는 안 봄)")
    vectors_max: int | None = F(20, "PARSE_VECTORS_MAX", "쪽 VLM 후보로 볼 벡터 도형 많은 쪽 수 상한(0이면 이 사유는 안 봄)")
    vlm_parallel: int | None = F(None, "FIGURES_VLM_PARALLEL", "그림 VLM 호출 병렬 워커 수")


class PipelineTransformRepresent(Section):
    post: CsvText | None = F(
        None,
        "PARSE_POST",
        "후보정 기능 선택: all(전부)|none(끔)|콤마 목록(vlm_page,supsub,charts,figures,context,attachments) — 없으면 자리마다 다름(파이프라인 all · parse MCP 서비스 supsub), 빈 값은 끔(옛 get(X, 'all')의 '' — blank keep) · 쓴 글자 그대로 rep.post.config에 남음(YAML 목록은 쉼표로 이음 — S7c2)",
        blank="keep",
    )
    qa_light: bool | None = F(False, "PARSE_QA_LIGHT", "=1이면 native 대비 풀문서 CER·순서 비교를 생략(경량화)", on=("1",))
    rep_select: str | None = F(None, "PARSE_REP_SELECT", "대표 엔진 선택 방식: first(첫 성공 엔진)|acc(정확도만)|그 외 best(정확도+풍부도)")


class PipelineTransformStructure(Section):
    chunk_overlap: int | None = F(64, "CHUNK_OVERLAP", "고정 길이 청커(chunk_fixed512)의 청크 간 겹침 글자 수")
    chunk_size: int | None = F(None, "CHUNK_SIZE", "청크 목표 길이(글자) — 청커별 기본이 다름")
    chunk_table: str | None = F(None, "CHUNK_TABLE", "'rows'이면 큰 표를 행 묶음 단위로 쪼갬(그 외 값·미설정은 표를 통째로 둠)")
    chunk_table_rows: int | None = F(25, "CHUNK_TABLE_ROWS", "표를 쪼갤 때 청크당 행 수(CHUNK_TABLE=rows일 때만)")
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


class PipelineTransformVlm(Section):
    deadline: float | None = F(360.0, "VLM_DEADLINE", "VLM 호출 1건 제한 시간(초)")
    fig_min_px: int | None = F(64, "VLM_FIG_MIN_PX", "이 값보다 짧은 변의 그림은 VLM 대상에서 제외(픽셀)")
    fig_ocr_max: int | None = F(8, "VLM_FIG_OCR_MAX", "문서당 그림 crop OCR 횟수 상한(비용 가드)")
    fig_photo_area_min: float | None = F(0.03, "VLM_FIG_PHOTO_AREA_MIN", "사진류(photo)로 볼 그림의 최소 면적 비율(쪽 대비)")
    fig_photo_max_tokens: int | None = F(300, "VLM_FIG_PHOTO_MAX_TOKENS", "사진류 그림 VLM 응답 최대 토큰 수(한 줄 요약 유도)")
    fig_photo_ocr_max: int | None = F(5, "VLM_FIG_PHOTO_OCR_MAX", "crop OCR 글자 수가 이 값 이하(+면적 충분)이면 사진류로 분류")
    fig_text_ocr_min: int | None = F(
        200, "VLM_FIG_TEXT_OCR_MIN", "crop OCR 글자 수(공백 제외)가 이 값 이상이면 글자 이미지(text_image)로 분류"
    )
    figures_max: int | None = F(20, "VLM_FIGURES_MAX", "문서당 VLM에 보낼 그림 수 상한(0이면 VLM 안 부름)")
    global_concurrency: int | None = F(12, "VLM_GLOBAL_CONCURRENCY", "모든 VLM 호출의 전역 동시 실행 수 합 상한")
    page_concurrency: int | None = F(None, "VLM_PAGE_CONCURRENCY", "쪽 VLM 병렬 워커 수 최대값")
    page_max: int | None = F(None, "VLM_PAGE_MAX", "문서당 쪽 VLM으로 읽을 쪽 수 상한(빈 값=전부, 0=쪽 VLM 끔)")
    page_min_concurrency: int | None = F(2, "VLM_PAGE_MIN_CONCURRENCY", "쪽 VLM 적응형 병렬에서 느릴 때 줄일 수 있는 최소 워커 수")
    page_slow: float | None = F(60.0, "VLM_PAGE_SLOW", "쪽 VLM 호출이 이 시간(초) 넘으면 다음 배치 병렬 수를 줄임")


class PipelineDev(Section):
    check_env_any_py: bool | None = F(
        False, "CHECK_ENV_ANY_PY", "check_env가 시스템 python에서도 멈추지 않고 계속할지(=1 계속 / 그 외 중단)", on=("1",)
    )


class PipelineEval(Section):
    """칸 없음 — 지운 칸만 남은 절(이름은 layout.REMOVED — 옛 파일이 경고만 받게)."""


class PipelineExtract(Section):
    doc_parallel: int | None = F(1, "PARSE_DOC_PARALLEL", "대표 결과 만들기(represent)에서 문서 병렬 처리 스레드 수(개)")
    engine_retry: int | None = F(1, "PARSE_ENGINE_RETRY", "엔진 별도 프로세스가 비정상 종료했을 때 바로 다시 시도할 횟수(회)")
    fill_merged: bool | None = F(True, "PARSE_FILL_MERGED", "표에서 병합 셀이 덮은 빈 칸을 원본 칸 값으로 채울지")
    hidden_overlap_max: int | None = F(
        20, "PARSE_HIDDEN_OVERLAP_MAX", "'숨은 글자-그림 겹침' 신호로 쪽 VLM 후보에 올릴 쪽 수 상한(쪽, 0=끔)"
    )
    input_source: str | None = F(None, "PARSE_SOURCE", "파싱 원본 위치: 폴더·rdb:csv:경로(11-01 — s3://·rdb:*·rdb:<이름>·rdb:<표> 지움)")
    isolate_overhead: float | None = F(10.0, "PARSE_ISOLATE_OVERHEAD", "별도 프로세스 실행 시 쪽당 제한 시간에 더해 줄 시작 여유(초)")
    kreuzberg_prose_filter: bool | None = F(True, "KREUZBERG_PROSE_FILTER", "kreuzberg가 평문을 표로 오인한 것을 거를지(=0이면 끔)")
    low_priority: bool | None = F(
        True,
        "PARSE_LOW_PRIORITY",
        "엔진 자식 프로세스를 낮은 우선순위로(POSIX nice +10 · Windows BELOW_NORMAL) — parse MCP 서비스 작업은 끔(=0)",
        off=("0",),
    )
    max_file_mb: float | None = F(0.0, "MAX_FILE_MB", "이 크기(MB)를 넘는 문서는 파싱에서 건너뜀(0=제한 없음)")
    max_new: int | None = F(0, "PARSE_MAX_NEW", "이번 실행에서 처음 파싱할 새 문서 수 상한(개, 0=제한 없음)")
    prefetch_workers: int | None = F(2, "PREFETCH_WORKERS", "미리받기(warm) 명령의 동시 다운로드 스레드 수(개)")
    rapidocr_page_workers: int | None = F(1, "RAPIDOCR_PAGE_WORKERS", "rapidocr 엔진이 문서 안 쪽별 OCR을 병렬로 돌리는 스레드 수(개)")
    rotated_max: int | None = F(20, "PARSE_ROTATED_MAX", "쪽 VLM 후보로 올릴 '회전된 쪽' 상한(쪽 수) — 0이면 rotation.csv를 안 읽음")
    skipped_log: str | None = F(None, "PARSE_SKIPPED_LOG", "건너뛴 문서(암호 PDF 등) 기록 jsonl 경로")
    source_limit: int | None = F(0, "PARSE_SOURCE_LIMIT", "원본에서 처리할 문서 건수 상한(0=제한 없음)")
    text_page_sec: float | None = F(
        10.0, "PARSE_TEXT_PAGE_SEC", "글자 엔진(VLM 아님) 문서×엔진 1건의 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )
    table_grid_max_rows: int | None = F(
        2000, "TABLE_GRID_MAX_ROWS", "표 grid JSON에 담는 최대 행 수(개) — 넘으면 앞부분만 자르고 truncated 표시"
    )
    vlm_page_sec: float | None = F(120.0, "PARSE_VLM_PAGE_SEC", "VLM 엔진 문서×엔진 1건의 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더")
    warmup_sec: float | None = F(60.0, "PARSE_WARMUP_SEC", "엔진 첫 문서의 제한 시간 하한(초) — import·모델 적재 여유")
    attach: PipelineExtractAttach = Field(default_factory=PipelineExtractAttach)
    cache: PipelineExtractCache = Field(default_factory=PipelineExtractCache)
    dedup: PipelineExtractDedup = Field(default_factory=PipelineExtractDedup)
    ocr: PipelineExtractOcr = Field(default_factory=PipelineExtractOcr)
    prepare: PipelineExtractPrepare = Field(default_factory=PipelineExtractPrepare)
    source: PipelineExtractSource = Field(default_factory=PipelineExtractSource)


class PipelineHostRunDocs(Section):
    """문서별 flow 러너(deploy/host/scripts/run_docs.py — 호스트에서 글자 그대로 읽음) 레인·대기열(사용자 10-29, docs/prd/runner.md rn-01·rn-02).
    기본값은 run_docs.py RUN_DOCS_DEFAULTS와 같다(tests/general/deploy/test_run_docs.py가 대조)."""

    warm: int | None = F(20, "RUN_DOCS_WARM", "진입 대기열 — 미리 받아 둘 문서 수(받는 중 포함·파싱 중 제외, 명령 인자 --warm이 덮음)")
    warm_workers: int | None = F(
        2, "RUN_DOCS_WARM_WORKERS", "미리 받기 동시 수 — 실제 동시 받기 = min(이 값, 대기열 빈자리)(pl-48, 사용자 11-02)"
    )
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
        "호스트의 사람 정답(gold) 폴더(서버 경로) — 컨테이너 /data/gold로 읽기 전용 마운트하는 원본(T-21 — 코드가 읽는 칸은 pipeline.paths.gold_dir · 붙이는 방식은 결정 대기 — doc.md)",
    )
    image: str | None = F(None, "DATA_PIPELINE_IMAGE", "data-pipeline 이미지 이름:태그(compose 필수 변수)")
    parse_cpus: float | None = F(
        5.0,
        "PARSE_CPUS",
        "일괄 상주 컨테이너(data-pipeline — compose.pipeline.yml) CPU 개수 상한(개) — docker는 호스트 CPU 수보다 큰 값을 거부(CPU 4개 개발 서버는 3 이하로)",
    )
    parse_mem_limit: str | None = F("24g", "PARSE_MEM_LIMIT", "일괄 상주 컨테이너(data-pipeline) 메모리·스왑 상한(docker 형식)")
    parse_mcp_cpus: float | None = F(
        3.0,
        "PARSE_MCP_CPUS",
        "parse_document 작업 컨테이너(data-pipeline-mcp — #107) CPU 개수 상한(개) — 줄이면 pipeline.service.parse_mcp.procs도 그 이하로",
    )
    parse_mcp_mem_limit: str | None = F(
        "8g", "PARSE_MCP_MEM_LIMIT", "parse_document 작업 컨테이너(data-pipeline-mcp) 메모리·스왑 상한(docker 형식)"
    )
    parse_mcp_cpu_shares: int | None = F(
        4096,
        "PARSE_MCP_CPU_SHARES",
        "parse_document 작업 컨테이너 CPU 나눔 비율(data-pipeline 1024의 4배 — CPU가 모자랄 때 먼저 받음, rn-03)",
    )
    run_docs_dir: str | None = F(
        None,
        "RUN_DOCS_DIR",
        "문서별 flow 러너(deploy/host/scripts/run_docs.py) 작업 폴더(호스트 — 진행 기록 batch_progress/·batches/) — 비우면 스크립트 옆 test_space/(C-29 ⑨, S7e1)",
    )
    nightly: PipelineHostNightly = Field(default_factory=PipelineHostNightly)
    run_docs: PipelineHostRunDocs = Field(default_factory=PipelineHostRunDocs)


class PipelineLoad(Section):
    bm25_threads: int | None = F(4, "BM25_THREADS", "BM25 항목(term,tf) 계산 병렬 스레드 수(개)")
    edw_path_prefix: str | None = F(None, "EDW_PATH_PREFIX", "저장소 doc.file_path에 기록할 원본 경로 접두(서버의 실제 보관 위치)")
    pg_create_extension: bool | None = F(
        False, "PG_CREATE_EXTENSION", "deploy 때 vector 확장 직접 생성 시도 — 1이면 켬(공유 PG에서는 금지)", on=("1",)
    )
    publish: PipelineLoadPublish = Field(default_factory=PipelineLoadPublish)


class PipelineNight(Section):
    vlm_concurrency: int | None = F(8, "NIGHT_VLM_CONCURRENCY", "새벽 배치: 문서 하나의 쪽 VLM 동시 요청 수(개)")
    workers: int | None = F(4, "NIGHT_WORKERS", "새벽 배치: 동시 처리 문서 수(개)")


class PipelinePaths(Section):
    edw_chain: str | None = F(
        None,
        "EDW_CHAIN_FILE",
        "EDW 조인 사슬 설정 파일 경로(적재만 읽음 — 비우면 resources/config/edw_chain.yaml · 서버에서 고친 사본은 컨테이너에서 보이는 자리, 예 "
        "/app/output/config/edw_chain.yaml — pl-29, 사용자 11-03 · 점검: python -m pipeline.load.edw_meta --check)",
    )
    gold_dir: str | None = F(
        None,
        "GOLD_DIR",
        "사람 정답(gold) 폴더 — score_gold·점검 도구의 기본 입력(코드가 읽는 경로 — 컨테이너 안은 /data/gold, 원본은 pipeline.host.gold_dir — T-21)",
    )
    images_root: str | None = F(None, "PARSE_IMAGES_ROOT", "그림 PNG·index.jsonl 저장 루트")
    out_root: str | None = F(None, "PIPE_OUT_ROOT", "파이프라인 출력 루트(output)")
    parse_tmp: str | None = F(None, "PARSE_TMP", "임시 폴더(첨부 임시 파일은 형제 attach/) — output 아래 2단 이상 하위만 허용")
    raw_root: str | None = F(None, "PARSE_RAW_ROOT", "P0 원본 층(raw/VLM) 캐시 저장소 루트")
    soffice_bin: str | None = F(
        image_default("SOFFICE_BIN"),
        "SOFFICE_BIN",
        "LibreOffice soffice 실행 파일 경로 — PATH·흔한 경로보다 먼저 봄(pipeline 이미지 안 기본 /usr/bin/soffice — 옛 Dockerfile ENV, B-2)",
    )


class PipelineConnections(Section):
    rdb: PipelineConnectionsRdb = Field(default_factory=PipelineConnectionsRdb)
    secure_doc: PipelineConnectionsSecureDoc = Field(default_factory=PipelineConnectionsSecureDoc)


class PipelineService(Section):
    parse_mcp: PipelineServiceParseMcp = Field(default_factory=PipelineServiceParseMcp)


class PipelineTransform(Section):
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

GOLD_MOUNT = Path(IMAGE_PATHS["gold_mount"])  # 사람 정답 폴더가 붙는 컨테이너 자리(이미지 약속 — 표는 settings.IMAGE_PATHS 한 곳, R-12)


def gold_dir():
    """사람 정답 폴더 — pipeline.paths.gold_dir, 비었고 이미지 안이며 /data/gold가 붙어 있으면 그것(S7e2 — 옛 run_tool.sh `-e GOLD_DIR=/data/gold`
    자리, 사용자 10-28)."""
    v = cfg().paths.gold_dir
    if not v and IN_IMAGE and GOLD_MOUNT.is_dir():
        return str(GOLD_MOUNT)
    return v


def stack():
    """엔진 구성(사전 — name·body_sha + body). 서버·PC 같은 파일(common.paths.stack_file — 비우면 resources/config/pipeline_stack.json,
    사용자 11-01: 판 표 없음). 층 파일(run_all·attachments)이 이것만 부른다 — 이 모듈은 층의 code_fp 의존이 아니다(common 아래만 셈)."""
    from common.store.db import cfgfile  # 파일 읽기 한 곳(이 모듈은 층의 code_fp 의존이 아님)

    a = cfgfile.active("stack")
    return {"name": a.name, "body_sha": a.body_sha, **a.body}


if __name__ == "__main__":
    from common.config import show

    sys.exit(show.main(PipelineAppSettings, sys.argv[1:], prog="python -m pipeline.config"))
