"""pipeline 앱 설정 — settings.yaml의 common + pipeline 절만 읽는다(S7a, refactor_plan 5-2 · D-015). 다른 앱(mcp) 절은 무시.
pipeline 코드가 읽는 객체는 설정 파일 기반 캐시 PIPE다(S7e2 — 전환 다리 없앰: env의 옛 이름은 읽지 않음, 신호 SETTINGS_FILE·RUN_ENV만):
  `from pipeline import config as pc` → `pc.cfg().extract.max_new`(pipeline 절) · `pc.given("PM_BUCKET")`(준 값만) · `pc.checked(X)` ·
  `pc.by_env(f"{p}_X")` · 시험 `with pc.PIPE.env(PARSE_TMP=…, PARSE_CACHE_MAX_GB=None):`(설정 위에 옛 env 이름으로 덮음 — os.environ 안 건드림).
  common 칸은 `common.config.settings.cfg()`로(COMMON). 값을 바꿔 자식에 넘길 때는 `settings.put()`·`settings.child_env()`(덮기 파일).
SETTINGS(common + pipeline 절)는 확인 명령(python -m pipeline.config)·시험용. 칸 표는 refactor_plan 부록 D.
사용: python -m pipeline.config [--file 경로]   # 읽어서 요약(비밀 가림) · export --section pipeline.host …
"""

import re
import sys

from pydantic import Field, field_validator  # 칸 형식

from common.config.settings import (
    AppSettings,
    Cache,
    CommonSettings,
    CsvList,
    CsvText,
    EnvView,
    F,
    Section,
    image_default,
)


class PipelineConnectionsRdbColumns(Section):
    doc_id: str | None = F("id", "RDB_COL_DOC_ID", "RDB 문서 위치 표에서 문서 ID 열의 이름", blank="keep")
    filename: str | None = F("original_filename", "RDB_COL_FILENAME", "RDB 문서 위치 표에서 원본 파일 이름 열의 이름", blank="keep")
    key: str | None = F("s3_key", "RDB_COL_KEY", "RDB 문서 위치 표에서 Object Storage 키(s3_key) 열의 이름", blank="keep")
    size: str | None = F("file_size", "RDB_COL_SIZE", "RDB 문서 위치 표에서 파일 크기 열의 이름", blank="keep")
    source_system: str | None = F(
        "source_system", "RDB_COL_SOURCE_SYSTEM", "RDB 문서 위치 표에서 원천(source_system) 열의 이름", blank="keep"
    )


class PipelineConnectionsRdb(Section):
    bucket: str | None = F(None, "RDB_BUCKET", "RDB 표에 버킷 정보가 없을 때 쓸 Object Storage 버킷 이름(레거시 대체값)")
    file_table: str | None = F(
        "AI.FileStorageMap",
        "RDB_FILE_TABLE",
        "파싱 대상 파일 목록을 읽을 EDW 표(<스키마>.<표> — 영문·숫자·_만, SQL에 그대로 들어감)",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$",
    )
    increment_col: str | None = F(None, "RDB_INCREMENT_COL", "증분(since) 판정에 쓸 열 이름 — 비우면 문서 ID 열(columns.doc_id)")
    columns: PipelineConnectionsRdbColumns = Field(default_factory=PipelineConnectionsRdbColumns)


class PipelineExtractAttach(Section):
    max_depth: int | None = F(
        2,
        "ATTACH_MAX_DEPTH",
        "문서 안 문서(압축 안 파일·메일 첨부·오피스 개체)를 꺼낼 최대 깊이 — 원본에서 종류가 섞여도 같이 셈(단계, pl-63)",
    )
    max_mb: float | None = F(20.0, "ATTACH_MAX_MB", "메일 첨부·오피스 개체 1개당 크기 상한(MB, 넘으면 건너뜀)")
    max_n: int | None = F(10, "ATTACH_MAX_N", "메일·오피스 문서 하나에서 꺼낼 첨부·개체 개수 상한(개)")
    timeout: float | None = F(120.0, "ATTACH_TIMEOUT", "첨부 1개를 별도 프로세스로 파싱할 때 제한 시간(초)")


class PipelineExtractArchive(Section):
    max_total_mb: float | None = F(
        2048.0, "ARCHIVE_MAX_TOTAL_MB", "압축 원본 하나의 풀린 크기 합계 상한(MB, 넘으면 archive_too_big으로 건너뜀 — 안전 상한)"
    )
    max_files: int | None = F(
        1000, "ARCHIVE_MAX_FILES", "압축 원본 하나의 안 파일 수 상한(개, 넘으면 archive_too_big으로 건너뜀 — 안전 상한)"
    )


class PipelineExtractCache(Section):
    parse_cache_max_gb: float | None = F(
        5.0, "PARSE_CACHE_MAX_GB", "재판독 중간 캐시 3종 합계 용량 상한(GB, 넘으면 오래된 것부터 삭제, 0=끔)"
    )


class PipelineExtractOcr(Section):
    dpi: int | None = F(150, "OCR_DPI", "쪽·그림 이미지 렌더링 해상도(DPI, OCR 엔진·VLM 엔진·쪽 VLM·그림 VLM·pptx 슬라이드·prepare 공용)")
    max_pages: int | None = F(
        0,
        "OCR_MAX_PAGES",
        "문서당 OCR 엔진(rapidocr 등 — VLM 아님) 쪽 수 상한(쪽, 0=제한 없음 · VLM 쪽 수 상한은 transform.vlm.vlm_max_pages_per_doc)",
    )
    table_grid: bool | None = F(True, "OCR_TABLE_GRID", "OCR 박스 좌표로 표 격자를 추정할지(=0이면 끔)")
    threads: int | None = F(
        None,
        "OCR_THREADS",
        "rapidocr onnxruntime 스레드 수(0=onnxruntime 자동, 비우거나 숫자(0~9만) 아니면(auto 등) OMP_NUM_THREADS·CPU 몫)",
        unset="nondigit",
    )


class PipelineExtractPrepare(Section):
    rotate: bool | None = F(
        False,
        "PREPARE_ROTATE",
        "이미지·스캔 PDF 쪽 방향 바로잡기 켬/끔 — 켜면 4방향 OCR 점수를 동시에 재 가장 높은 방향으로 돌림, 끄면 회전용 OCR 없이 그대로(사용자 11-02 기본 꺼짐)",
        off=("0",),
    )


SOURCE_RE = re.compile(
    r"(SFDC|CRMS|LAS|FAQ|OTHER|DEV-[1-9][0-9]?)"
)  # 파싱할 원천 값(대문자로 바꾼 뒤) — DEV-<1~99>는 dev·local만(require_run_env)


class PipelineExtractSource(Section):
    systems: CsvList | None = F(
        None,
        "SOURCE_SYSTEMS",
        "파싱할 원천 목록(FileStorageMap.source_system — 대소문자 무관): SFDC·CRMS·LAS·FAQ·Other·DEV-<1~99>(dev·local만) — 비우면 운영 원천 5개(DEV 행 뺌)",
    )
    fetch_workers: int | None = F(1, "SOURCE_FETCH_WORKERS", "원본 문서 병렬 다운로드 스레드 수(개) — 미리 받기(candidate_ready stage)")
    staging: str | None = F(None, "SOURCE_STAGING", "미리 받기(staging) 폴더 — 원본을 받는 유일한 자리, 비면 rdb:csv 원본을 받지 못함")

    @field_validator("systems")
    @classmethod
    def _source_names(cls, v):
        """원천 이름은 대문자로(비교는 대소문자 무관) — 모르는 값은 거부."""
        if not v:
            return v
        up = [x.strip().upper() for x in v]
        bad = [x for x in up if not SOURCE_RE.fullmatch(x)]
        if bad:
            raise ValueError(f"모르는 원천 {bad} — SFDC·CRMS·LAS·FAQ·Other·DEV-<1~99>")
        return up


class PipelineHostNightly(Section):
    time: str | None = F(
        None,
        "NIGHTLY_TIME",
        "새벽 배치 시작 시각(HH:MM, 서버 시간) — 비우면 새벽 배치 없음. 타이머가 5분마다 깨워 이 시각부터 5분 안이면 시작(nightly_batch.sh scheduled)",
        pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$",  # 틀린 꼴은 설정을 읽을 때 거부(타이머가 5분마다 실패로 남기지 않게)
    )
    # 사용자 11-02 — 시작 시각·문서 수 상한·마감 시각 셋이 모두 있어야 새벽 배치가 돈다(하나라도 비면 nightly_batch.sh scheduled가 조용히 끝)
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
    bucket: str | None = F(
        None, "PM_BUCKET", "publish 대표 결과 업로드 Object Storage 버킷 이름(file://<폴더>면 로컬 가짜 저장소)", repo="file://"
    )
    local_dir: str | None = F(
        "valid_env/object_storage/Parsing_Result",
        "LOCAL_PM_DIR",
        "PC(RUN_ENV=local) 게시 폴더(저장소 기준 상대 가능 — 처음 게시할 때 만듦) — local은 서버 게시 버킷(PM_BUCKET) 대신 이 폴더를 씀(op-14)",
    )
    prefix: str | None = F(None, "PM_PREFIX", "버킷 안 업로드 경로 접두")
    upload_statuses: CsvList | None = F(
        ["ok", "partial"], "PM_UPLOAD_STATUSES", "원본을 업로드할 파싱 상태 목록(쉼표 — ok·partial·failed 등 게시 STATUSES 중에서)"
    )


class PipelineServiceDataParsing(Section):
    job_timeout_sec: float | None = F(600.0, "DATA_PARSING_JOB_TIMEOUT_SEC", "parse MCP 서비스 작업 1건 제한 시간(초)")
    procs: int | None = F(
        None, "DATA_PARSING_PROCS", "parse MCP 서비스 worker마다 엔진 묶음 병렬 프로세스 수(개) — 비우면 max(1, min(2, CPU − 1))"
    )
    roots: CsvList | None = F(
        None, "DATA_PARSING_ROOTS", "parse MCP 서비스가 읽을 수 있는 허용 루트 폴더(쉼표 목록) — 비면 코드가 정함(<서비스 폴더>/inbox)"
    )
    text_page_sec: float | None = F(
        1.0, "DATA_PARSING_TEXT_PAGE_SEC", "parse MCP 서비스 작업의 글자 엔진 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )
    warmup_sec: float | None = F(
        20.0,
        "DATA_PARSING_WARMUP_SEC",
        "parse MCP 서비스 작업의 첫 시도 제한 하한(초) — 새 프로세스에서 엔진을 처음 띄울 때(import·모델 적재) 여유",
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
    chunk_size: int | None = F(None, "CHUNK_SIZE", "청크 목표 길이(글자) — 비우면 800")
    chunk_table: str | None = F(None, "CHUNK_TABLE", "'rows'이면 큰 표를 행 묶음 단위로 쪼갬(그 외 값·미설정은 표를 통째로 둠)")
    chunk_table_rows: int | None = F(25, "CHUNK_TABLE_ROWS", "표를 쪼갤 때 청크당 행 수(CHUNK_TABLE=rows일 때만)")
    embed_batch: int | None = F(32, "EMBED_BATCH", "임베딩 API 한 번에 보내는 청크 수")
    embed_cache: str | None = F(None, "EMBED_CACHE", "임베딩 캐시 sqlite 경로(0 또는 빈 값이면 캐시 끔)")
    embed_concurrency: int | None = F(4, "EMBED_CONCURRENCY", "임베딩 호출 병렬 수(EMBED_BATCH 묶음을 동시에 전송)")
    embed_max_chars: int | None = F(8000, "EMBED_MAX_CHARS", "임베딩 입력 청크 최대 글자 수(넘으면 자름, 400 오류 방지 안전망)")
    embed_retry: int | None = F(2, "EMBED_RETRY", "임베딩 API 실패 시 재시도 횟수")


class PipelineTransformVlm(Section):
    fig_min_px: int | None = F(64, "VLM_FIG_MIN_PX", "이 값보다 짧은 변의 그림은 VLM 대상에서 제외(픽셀)")
    fig_ocr_max: int | None = F(8, "VLM_FIG_OCR_MAX", "문서당 그림 crop OCR 횟수 상한(비용 가드)")
    fig_photo_area_min: float | None = F(0.03, "VLM_FIG_PHOTO_AREA_MIN", "사진류(photo)로 볼 그림의 최소 면적 비율(쪽 대비)")
    fig_photo_max_tokens: int | None = F(300, "VLM_FIG_PHOTO_MAX_TOKENS", "사진류 그림 VLM 응답 최대 토큰 수(한 줄 요약 유도)")
    fig_photo_ocr_max: int | None = F(5, "VLM_FIG_PHOTO_OCR_MAX", "crop OCR 글자 수가 이 값 이하(+면적 충분)이면 사진류로 분류")
    fig_text_ocr_min: int | None = F(
        200, "VLM_FIG_TEXT_OCR_MIN", "crop OCR 글자 수(공백 제외)가 이 값 이상이면 글자 이미지(text_image)로 분류"
    )
    figures_max: int | None = F(20, "VLM_FIGURES_MAX", "문서당 VLM에 보낼 그림 수 상한(0이면 VLM 안 부름)")
    page_max: int | None = F(
        None, "VLM_PAGE_MAX", "문서당 VLM으로 옮길 쪽 수 상한(VLM 엔진 qwen_vlm·쪽 VLM 공통 — 빈 값=전부, 0=쪽 VLM 끔·VLM 엔진은 빈 결과)"
    )


class PipelineExtract(Section):
    doc_parallel: int | None = F(1, "PARSE_DOC_PARALLEL", "대표 결과 만들기(represent)에서 문서 병렬 처리 스레드 수(개)")
    engine_retry: int | None = F(1, "PARSE_ENGINE_RETRY", "엔진 별도 프로세스가 비정상 종료했을 때 바로 다시 시도할 횟수(회)")
    fill_merged: bool | None = F(True, "PARSE_FILL_MERGED", "표에서 병합 셀이 덮은 빈 칸을 원본 칸 값으로 채울지")
    hidden_overlap_max: int | None = F(
        20, "PARSE_HIDDEN_OVERLAP_MAX", "'숨은 글자-그림 겹침' 신호로 쪽 VLM 후보에 올릴 쪽 수 상한(쪽, 0=끔)"
    )
    input_source: str | None = F(
        None, "PARSE_SOURCE", "파싱 원본 위치: 폴더·rdb:csv:경로(11-01 — s3://·rdb:*·rdb:<이름>·rdb:<표> 지움)", repo=True
    )
    isolate_overhead: float | None = F(10.0, "PARSE_ISOLATE_OVERHEAD", "별도 프로세스 실행 시 쪽당 제한 시간에 더해 줄 시작 여유(초)")
    kreuzberg_prose_filter: bool | None = F(True, "KREUZBERG_PROSE_FILTER", "kreuzberg가 평문을 표로 오인한 것을 거를지(=0이면 끔)")
    low_priority: bool | None = F(
        True,
        "PARSE_LOW_PRIORITY",
        "엔진 자식 프로세스를 낮은 우선순위로(POSIX nice +10 · Windows BELOW_NORMAL) — parse MCP 서비스 작업은 끔(=0)",
        off=("0",),
    )
    max_file_mb: float | None = F(0.0, "MAX_FILE_MB", "이 크기(MB)를 넘는 문서는 파싱에서 건너뜀(0=제한 없음)")
    max_new: int | None = F(
        None, "PARSE_MAX_NEW", "이번 실행에서 처음 파싱할 새 문서 수 상한(개, 0=제한 없음) — 비우면 제한 없음(local은 local_max_new)"
    )
    local_max_new: int | None = F(
        5,
        "LOCAL_PARSE_MAX_NEW",
        "PC(RUN_ENV=local) 한 번에 처음 파싱할 새 문서 수 상한(개, 0=제한 없음) — PARSE_MAX_NEW를 안 적었을 때(op-14)",
    )
    local_source: str | None = F(
        "valid_env/object_storage",
        "LOCAL_PARSE_SOURCE",
        "PC(RUN_ENV=local) 파싱 원본 폴더(저장소 기준 상대 가능) — PARSE_SOURCE를 안 적었을 때(op-14). 게시 폴더(local_dir)는 원본으로 읽지 않음",
    )
    rapidocr_page_workers: int | None = F(1, "RAPIDOCR_PAGE_WORKERS", "rapidocr 엔진이 문서 안 쪽별 OCR을 병렬로 돌리는 스레드 수(개)")
    rotated_max: int | None = F(20, "PARSE_ROTATED_MAX", "쪽 VLM 후보로 올릴 '회전된 쪽' 상한(쪽 수) — 0이면 rotation.csv를 안 읽음")
    text_page_sec: float | None = F(
        10.0, "PARSE_TEXT_PAGE_SEC", "글자 엔진(VLM 아님) 문서×엔진 1건의 쪽당 제한 시간(초) — 넘으면 두 배로 한 번 더"
    )
    table_grid_max_rows: int | None = F(
        2000, "TABLE_GRID_MAX_ROWS", "표 grid JSON에 담는 최대 행 수(개) — 넘으면 앞부분만 자르고 truncated 표시"
    )
    warmup_sec: float | None = F(60.0, "PARSE_WARMUP_SEC", "엔진 첫 문서의 제한 시간 하한(초) — import·모델 적재 여유")
    archive: PipelineExtractArchive = Field(default_factory=PipelineExtractArchive)
    attach: PipelineExtractAttach = Field(default_factory=PipelineExtractAttach)
    cache: PipelineExtractCache = Field(default_factory=PipelineExtractCache)
    ocr: PipelineExtractOcr = Field(default_factory=PipelineExtractOcr)
    prepare: PipelineExtractPrepare = Field(default_factory=PipelineExtractPrepare)
    source: PipelineExtractSource = Field(default_factory=PipelineExtractSource)


class PipelineHostRunPipeline(Section):
    """문서별 flow 러너(deploy/host/scripts/run_pipeline.py — 호스트에서 글자 그대로 읽음) 레인·대기열(사용자 10-29, docs/prd/runner.md rn-01·rn-02).
    기본값은 run_pipeline.py RUN_PIPELINE_DEFAULTS와 같다(tests/general/deploy/test_run_pipeline.py가 대조)."""

    staging: int | None = F(
        20, "RUN_PIPELINE_STAGING", "진입 대기열 — 미리 받아 둘 문서 수(받는 중 포함·파싱 중 제외, 명령 인자 --staging이 덮음)"
    )
    staging_workers: int | None = F(
        2, "RUN_PIPELINE_STAGING_WORKERS", "미리 받기 동시 수 — 실제 동시 받기 = min(이 값, 대기열 빈자리)(pl-48, 사용자 11-02)"
    )
    struct_workers: int | None = F(2, "RUN_PIPELINE_STRUCT_WORKERS", "구조화·적재 스레드 수(명령 인자 --struct-workers가 덮음)")
    struct_backlog: int | None = F(
        None, "RUN_PIPELINE_STRUCT_BACKLOG", "중간 대기열 상한(파싱 끝·구조화 대기 문서 수) — 비우면 구조화 스레드 × 2, 0이면 상한 없음"
    )
    vlm_cap: int | None = F(2, "RUN_PIPELINE_VLM_CAP", "vlm 레인 문서 동시 파싱 상한(gpu 예산)")
    light_dedicated: int | None = F(1, "RUN_PIPELINE_LIGHT_DEDICATED", "light 레인 전담 워커 수(light 문서만)")
    light_shared: int | None = F(1, "RUN_PIPELINE_LIGHT_SHARED", "light 레인 공유 워커 수(light 먼저, 비면 가장 긴 다른 레인에서 가져옴)")
    medium_dedicated: int | None = F(1, "RUN_PIPELINE_MEDIUM_DEDICATED", "medium 레인 전담 워커 수(MCP 업로드 처리 중에는 쉼)")
    medium_shared: int | None = F(1, "RUN_PIPELINE_MEDIUM_SHARED", "medium 레인 공유 워커 수(medium 먼저, 비면 다른 레인)")
    vlm_dedicated: int | None = F(1, "RUN_PIPELINE_VLM_DEDICATED", "vlm 레인 전담 워커 수(vlm 문서만)")
    vlm_shared: int | None = F(1, "RUN_PIPELINE_VLM_SHARED", "vlm 레인 공유 워커 수(vlm 먼저, 비면 다른 레인)")
    # 컨테이너 안 파싱·구조화 명령에 --set으로 넘기는 값(문서 하나씩 도는 서버 배치 — 앱 기본값과 다름)
    vlm_concurrency: int | None = F(
        8, "RUN_PIPELINE_VLM_CONCURRENCY", "light·medium 문서 하나의 VLM 동시 요청 수(VLM_MAX_CONCURRENCY·VLM_CONCURRENCY로 넘김)"
    )
    vlm_lane_concurrency: int | None = F(
        6, "RUN_PIPELINE_VLM_LANE_CONCURRENCY", "vlm 레인 문서 하나의 VLM 동시 요청 수(vlm_cap 문서가 GPU 서버를 나눔)"
    )
    figures_max: int | None = F(10, "RUN_PIPELINE_FIGURES_MAX", "문서당 그림 VLM 상한(VLM_FIGURES_MAX)")
    parse_post: str | None = F(
        "supsub,charts,figures,context,attachments", "RUN_PIPELINE_PARSE_POST", "light·medium 문서의 후처리 목록(PARSE_POST)"
    )
    vlm_lane_post: str | None = F(
        "supsub,charts,figures,context,attachments,vlm_page",
        "RUN_PIPELINE_VLM_LANE_POST",
        "vlm 레인 문서의 후처리 목록(PARSE_POST — vlm_page는 스캔 쪽만 VLM 전사, 쪽 상한 없음)",
    )
    rapidocr_page_workers: int | None = F(2, "RUN_PIPELINE_RAPIDOCR_PAGE_WORKERS", "rapidocr 쪽 병렬 스레드 수(RAPIDOCR_PAGE_WORKERS)")
    ocr_threads: int | None = F(1, "RUN_PIPELINE_OCR_THREADS", "rapidocr onnxruntime 스레드 수(OCR_THREADS)")
    pipe_procs: int | None = F(4, "RUN_PIPELINE_PIPE_PROCS", "문서 하나의 엔진 묶음 병렬 프로세스 수(PIPE_PROCS)")
    fetch_workers: int | None = F(2, "RUN_PIPELINE_FETCH_WORKERS", "원본 받기 스레드 수(SOURCE_FETCH_WORKERS)")
    rep_select: str | None = F("first", "RUN_PIPELINE_REP_SELECT", "대표 엔진 선택 방식(PARSE_REP_SELECT — first·acc·best)")
    qa_light: bool | None = F(True, "RUN_PIPELINE_QA_LIGHT", "풀문서 CER·순서 비교 생략(PARSE_QA_LIGHT)")
    scan_rotate: bool | None = F(
        False, "RUN_PIPELINE_SCAN_ROTATE", "이미지 PDF 쪽 방향 바로잡기 — false면 받기(stage)에 --no-scan-rotate를 붙여 회전 OCR 생략"
    )
    # e2e 단계(rn-05) — 한 번 실행 = ① 사전 점검 → ② 문서 처리 → ③ 적재·검색 확인(①③만 끄고 켬, ②는 항상). 명령 인자(--set·--limit)가 덮음
    steps_precheck: bool | None = F(
        True, "RUN_PIPELINE_STEPS_PRECHECK", "① 사전 점검(설정·모델 연결·DB 판·배포 시험) — 실패하면 문서를 처리하지 않음"
    )
    steps_verify: bool | None = F(
        True,
        "RUN_PIPELINE_STEPS_VERIFY",
        "③ 적재·검색 확인(이번 실행 문서로 DB 검색 → 검색 MCP 바깥 호출 — 주소 dev.search_ui.search_ui_mcp_url)",
    )
    run_limit: int | None = F(
        2, "RUN_PIPELINE_RUN_LIMIT", "사람이 돌릴 때 처리 건수 — 0 = 전체(새벽 배치는 --limit 0, 명령 인자 --limit이 덮음)"
    )
    cpu_gate: float | None = F(1.3, "RUN_PIPELINE_CPU_GATE", "light 밖 레인의 파싱 CPU 게이트(CPU_MAX_LOAD — 명령 인자 --cpu-gate가 덮음)")
    light_cpu_gate: float | None = F(9.0, "RUN_PIPELINE_LIGHT_CPU_GATE", "light 레인 CPU 게이트(CPU_MAX_LOAD — 높게 두어 바로 소화)")
    embed_concurrency: int | None = F(6, "RUN_PIPELINE_EMBED_CONCURRENCY", "구조화·적재 임베딩 호출 병렬 수(EMBED_CONCURRENCY)")
    embed_batch: int | None = F(32, "RUN_PIPELINE_EMBED_BATCH", "임베딩 한 번에 보내는 청크 수(EMBED_BATCH)")
    bm25_threads: int | None = F(3, "RUN_PIPELINE_BM25_THREADS", "BM25 계산 스레드 수(BM25_THREADS)")


class PipelineHost(Section):
    run_pipeline_dir: str | None = F(
        None,
        "RUN_PIPELINE_DIR",
        "문서별 flow 러너(deploy/host/scripts/run_pipeline.py) 작업 폴더(호스트 — 진행 기록 batch_progress/·batches/) — 비우면 스크립트 옆 test_space/(C-29 ⑨, S7e1)",
    )
    nightly: PipelineHostNightly = Field(default_factory=PipelineHostNightly)
    run_pipeline: PipelineHostRunPipeline = Field(default_factory=PipelineHostRunPipeline)


class PipelineLoad(Section):
    bm25_threads: int | None = F(4, "BM25_THREADS", "BM25 항목(term,tf) 계산 병렬 스레드 수(개)")
    edw_path_prefix: str | None = F(None, "EDW_PATH_PREFIX", "저장소 doc.file_path에 기록할 원본 경로 접두(서버의 실제 보관 위치)")
    publish: PipelineLoadPublish = Field(default_factory=PipelineLoadPublish)


class PipelinePaths(Section):
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


class PipelineService(Section):
    data_parsing: PipelineServiceDataParsing = Field(default_factory=PipelineServiceDataParsing)


class PipelineTransform(Section):
    figures: PipelineTransformFigures = Field(default_factory=PipelineTransformFigures)
    represent: PipelineTransformRepresent = Field(default_factory=PipelineTransformRepresent)
    structure: PipelineTransformStructure = Field(default_factory=PipelineTransformStructure)
    vlm: PipelineTransformVlm = Field(default_factory=PipelineTransformVlm)


class PipelineSettings(Section):
    connections: PipelineConnections = Field(default_factory=PipelineConnections)
    extract: PipelineExtract = Field(default_factory=PipelineExtract)
    host: PipelineHost = Field(default_factory=PipelineHost)
    load: PipelineLoad = Field(default_factory=PipelineLoad)
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


def stack():
    """엔진 구성(사전 — name·body_sha + body). 서버·PC 같은 파일(resources/config/pipeline_stack.json —
    사용자 11-01: 판 표 없음). 층 파일(run_all·attachments)이 이것만 부른다 — 이 모듈은 층의 code_fp 의존이 아니다(common 아래만 셈)."""
    from common.store.db import cfgfile  # 파일 읽기 한 곳(이 모듈은 층의 code_fp 의존이 아님)

    a = cfgfile.active("stack")
    return {"name": a.name, "body_sha": a.body_sha, **a.body}


FEATURES = ("vlm_page", "supsub", "charts", "figures", "context", "attachments")


def active_features(config=None):
    """PARSE_POST 글자 → 켠 기능 집합(결정적 — 순서 섞이지 않게 set 아닌 frozenset도 괜찮지만 멤버십만 씀)."""
    if config is None:  # 없음 = "all", 빈 글자 = 끔
        v = cfg().transform.represent.post
        config = "all" if v is None else v
    config = (config or "").strip()
    if config in ("", "none"):
        return frozenset()
    if config == "all":
        return frozenset(FEATURES)
    return frozenset(f.strip() for f in config.split(",") if f.strip())


if __name__ == "__main__":
    from common.config import show

    sys.exit(show.main(PipelineAppSettings, sys.argv[1:], prog="python -m pipeline.config"))
