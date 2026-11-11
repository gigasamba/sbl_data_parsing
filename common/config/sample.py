"""settings.sample.yaml 만들기·대조 — 앱 설정 모델의 모든 칸을 배치(common.config.layout)대로 코드 기본값과 함께 낸다.
맨 위 required(사람이 채울 값 — 칸마다 [필수 · 언제·어느 앱] 또는 [선택]) → 역할 절(common·extract·transform·load·search·ops — 환경마다 정하는 값,
세부 카테고리 제목) → tuning(거의 안 바꾸는 값 — 분류별 제목) → dev(PC 전용). 값 자리는 코드 기본값(없으면 null), 주석은 NOTES 한 줄. 칸을 더하거나 바꾸면 다시 만든다.
사용: python -m common.config.sample            # 저장소 루트 settings.sample.yaml에 씀
      python -m common.config.sample --check    # 파일이 모델과 같은지(다르면 rc 1)
      python -m common.config.sample --where PG_HOST [이름…]   # 옛 env 이름 → 파일 자리·모델 경로·내부 표시(판정 꼴 등 — sample에서 뺀 것)
"""

import sys
from typing import Literal, get_args, get_origin

import yaml

from common.config import layout as L
from common.config import settings as S
from common.core.console import utf8_stdout

OUT = S.REPO_ROOT / "settings.sample.yaml"
HEAD = """# settings.sample.yaml — 설정 파일 구조와 설명. 생성: python -m common.config.sample (손으로 고치지 않음)
# 복사해 [필수] 칸을 채우면 시작된다 — PC: 저장소 루트 settings.yaml(권한 600) · 서버: <루트>/settings.yaml(루트 = 코드 폴더 자체 · UID 10001·권한 640).
# 순서: required(사람이 채울 값) → common·extract·transform·load·search·ops(환경마다 정하는 값) → tuning(거의 안 바꾸는 값) → dev(PC 전용 — 서버는 비움) → option(선택 기능 — 비우면 끔).
#   빈 칸(`이름:` 뒤가 비어 있음) = 사람이 꼭 적을 값([필수] — 주석에 예). null = 비워 두면 코드 기본값·계산값·끔(주석의 "null = …"). 그 밖의 값 = 코드 기본값.
#   복사할 때는 [필수] 칸과 바꿀 칸만 옮기기를 권장 — 적힌 값은 코드 기본값보다 이겨서, 나중에 코드 기본값이 바뀌어도 반영되지 않는다.
#   [필수 · 언제(어느 앱)] — 언제 = 모두·local(PC)·dev·prd(서버), 앱 = pipeline·mcp·호스트 스크립트. [선택] = 비워도 됨. [비밀] = settings.yaml에만(출력·로그에 안 나옴).
#   각 앱은 자기 칸만 읽는다(pipeline: required·common·extract·transform·load·ops·dev · mcp: required·common·search·ops·dev — tuning은 둘 다).
#   같은 칸 두 번·모르는 칸·옛 이름(자리가 다른 칸)은 시작 거부(칸 이름만 알림 — 옛 자리면 새 자리를 알려 줌).
#   한 번만 몇 칸 바꿀 때: --set 이름=값. 옛 env 이름 → 자리: python -m common.config.sample --where <이름>.
"""
# 역할 절 안 세부 카테고리 — (제목, 파일 자리 접두어들). 앞에서부터 처음 맞는 것. 안 드는 칸이 있으면 build가 멈춘다(새 칸이면 여기도).
CATEGORIES = {
    "common": (
        ("접속 — EDW·Object Storage 세부", ("common.connections",)),
        ("모델 호출 — 임베딩·LLM·VLM", ("common.models.embed", "common.models.llm", "common.models.vlm")),
        ("외부 전송 가드 — 내부망 판정", ("common.models.guard",)),
    ),
    "extract": (
        (
            "원천 받기·처리 상한",
            ("extract.source", "extract.max_new_docs_per_run", "extract.max_source_file_mb"),
        ),
        ("회전 준비(prepare)", ("extract.prepare",)),
        ("쪽 렌더·OCR", ("extract.page_render_dpi", "extract.ocr")),
    ),
    "transform": (
        ("대표 결과(represent)", ("transform.represent",)),
        ("VLM 호출", ("transform.vlm",)),
        ("청크·임베딩", ("transform.structure",)),
    ),
    "load": (("게시(publish)", ("load.stored_path_prefix",)), ("적재", ("load",))),
    "search": (
        ("MCP 서버", ("search.server",)),
        ("EDW 도구", ("search.edw_meta", "search.edw_query")),
    ),
    "ops": (
        ("실행 자원 — 비우면 CPU·메모리로 자동", ("ops.runtime",)),
        ("로그 — JSON·DB 기록", ("ops.log",)),
        ("경로", ("ops.paths",)),
        ("호스트 — 컨테이너 도구·이미지 정리", ("ops.host",)),
        ("상주 서비스 — parse MCP", ("ops.services",)),
        ("새벽 배치", ("ops.nightly",)),
        ("run_pipeline — 단계·레인", ("ops.run_pipeline",)),
    ),
    "dev": (
        ("local(PC) 전용 — 가짜 EDW·게시 폴더·원본 폴더·새 문서 상한(서버 전용 칸 대신)", ("dev.local",)),
        ("외부 모델 — 허용·지출 상한·단가", ("dev.models",)),
        ("가짜 LLM", ("dev.fake_llm",)),
        ("검증 페이지", ("dev.search_ui",)),
        ("PC 시험 Docker", ("dev.docker",)),
    ),
    "option": (("개발 작업 공간 — SSH·opencode(개발 서버 dev만)", ("option.devbox",)),),
    "tuning": (  # 거의 안 바꾸는 값을 분류별로(자리는 tuning.<역할 자리>)
        ("공통 — 접속·모델 호출(제한 시간·재시도·캐시)", ("tuning.common.connections", "tuning.common.models")),
        ("공통 — 검색 글자 정규화·용어 초안", ("tuning.common.text",)),
        ("추출 — 원천 목록 열·파싱 엔진·OCR·첨부", ("tuning.extract",)),
        ("변환 — 그림 고르기·그림 분류·청크·임베딩", ("tuning.transform",)),
        ("적재", ("tuning.load",)),
        ("검색 — 순위·도구 상한·감사 기록", ("tuning.search",)),
        ("로그 — DB 기록 대기열·묶음", ("tuning.ops.log",)),
        ("실행 자원 — 자동 계산 계수", ("tuning.ops.runtime",)),
        ("상주 서비스", ("tuning.ops.services",)),
    ),
}
NOTE_COL = 46  # 칸 주석이 시작하는 열(값 자리와 주석을 떼어 놓음)

# 칸마다 주석 한 줄 — 짧은 설명 · 값 또는 예. 기본값이 null인 선택 칸은 "(null = 비우면 되는 것)". 모든 칸이 있어야 한다(build가 확인).
NOTES = {
    "common.connections.redis.redis_host": "parse_document Redis 주소 · 컨테이너에서 서버 자신(compose-redis.yml)",
    "common.connections.redis.redis_port": "Redis 포트 · 서버마다 하나(compose-redis.yml이 8010에 연다)",
    "common.connections.redis.redis_password": "Redis 비밀번호(필수 — 서버마다 채움 · .env의 REDIS_PASSWORD와 같은 값) · 예 서버에서 openssl rand -hex 32를 실행해 나온 64자",
    "common.connections.redis.redis_db": "Redis 데이터베이스 번호",
    "common.connections.redis.redis_key_prefix": "Redis 키 접두 · 설정값 그대로(서버당 한 벌)",
    "common.parse_queue.mcp_parse_workers": "Redis 소비자 프로세스 수 · 1~2(현재 최대 2), 늘리려면 CPU·메모리·엔진 수도 조정",
    "common.parse_queue.mcp_parse_max_attempts": "죽은 worker 작업의 최대 전달 횟수",
    "common.parse_queue.mcp_parse_result_ttl_sec": "완료 HASH·LIST 보존 시간(초)",
    # required
    "common.run_env": "실행 환경 · local(PC)·dev(개발 서버)·prd(운영 서버)",
    "pipeline.extract.source.systems": "파싱할 원천 목록(FileStorageMap.source_system, 대소문자 무관) · SFDC·CRMS·LAS·FAQ·Other·DEV-<1~99> · 쉼표 구분 · 예 DEV-1 또는 DEV-1, DEV-2 또는 SFDC, CRMS (null = 운영 5개 원천 SFDC·CRMS·LAS·FAQ·Other — DEV-<n> 행은 뺌)",
    "common.connections.pg.host": "PG 주소 · 예 127.0.0.1",
    "common.connections.pg.port": "PG 포트 · 예 55433",
    "common.connections.pg.db": "PG 데이터베이스 이름 · 예 rag",
    "common.connections.pg.user": "PG 계정 · 예 rag_app",
    "common.connections.pg.password": "PG 비밀번호 · 서버는 8자 이상 · 예 DB 담당이 준 값",
    "common.connections.pg.db_schema": "검색 스키마(소문자·숫자·_)",
    "common.models.embed.base_url": "임베딩 주소(OpenAI 호환) · 예 http://10.0.0.5:8000/v1",
    "common.models.embed.model": "임베딩 모델 이름(색인과 같게) · 예 bge-m3",
    "common.models.embed.api_key": "임베딩 API 키 · 예 모델 담당이 준 키(sk-로 시작하는 글자 등) (null = 키 안 보냄)",
    "common.connections.rdb.host": "EDW(SQL Server) 주소 · 예 edw.corp.local",
    "common.connections.rdb.port": "EDW 포트 · 1~65535",
    "common.connections.rdb.database": "EDW 데이터베이스 이름 · 예 EDW",
    "common.connections.rdb.read.user": "EDW 읽기 계정(원천 목록·메타 사슬·query_edw) · 예 svc_parse_r",
    "common.connections.rdb.read.password": "EDW 읽기 비밀번호 · 예 DB 담당이 준 값",
    "common.connections.rdb.sqlite": "가짜 EDW sqlite 파일(저장소 기준 상대 가능) · 예 valid_env/edw/edw_copy.sqlite (null = valid_env/edw/edw_copy.sqlite — 없으면 edw.sqlite를 복사)",
    "pipeline.load.publish.local_dir": "게시 폴더(저장소 기준 상대 가능 — 처음 게시할 때 만듦) · 서버 publish_bucket 대신",
    "pipeline.extract.local_source": "파싱 원본 폴더(저장소 기준 상대 가능 — 게시 폴더는 원본에서 뺌) · source_input_location·--source가 없을 때",
    "pipeline.extract.local_max_new": "한 번에 새로 파싱할 문서 수 상한 · 0 = 제한 없음 · max_new_docs_per_run을 안 적었을 때",
    "pipeline.load.publish.bucket": "게시 버킷 — 파싱 결과(silver)를 올릴 Object Storage 버킷 이름(스토리지 담당이 만들어 줌 · 원본 버킷과 다르게 · 개발 벌끼리는 같은 버킷이어도 됨 — 키에 원천 DEV-<n>이 들어감) · 예 rag-silver",
    "pipeline.load.publish.prefix": "버킷 안 경로 접두 · 예 parse (null = 버킷 맨 위)",
    "common.connections.object_storage.endpoint": "S3 호환 주소 · 예 https://os.corp.local:9000",
    "common.connections.object_storage.access_key": "S3 액세스 키 · 예 스토리지 담당이 준 값",
    "common.connections.object_storage.secret_key": "S3 시크릿 키 · 예 스토리지 담당이 준 값",
    "common.models.llm.base_url": "LLM 주소(OpenAI 호환) · 예 http://10.0.0.6:8000/v1 — 적재 분류(doc_classify)가 씀",
    "common.models.llm.model": "LLM 모델 이름 · 예 qwen3-32b",
    "common.models.llm.api_key": "LLM API 키 · 예 모델 담당이 준 키(sk-로 시작하는 글자 등) (null = 키 안 보냄)",
    "common.models.vlm.base_url": "VLM 주소(OpenAI 호환) · 예 http://10.0.0.7:8000/v1 — 그림·쪽 VLM·스캔 PDF가 씀",
    "common.models.vlm.model": "VLM 모델 이름 · 예 qwen2.5-vl-7b",
    "common.models.vlm.api_key": "VLM API 키 · 예 모델 담당이 준 키(sk-로 시작하는 글자 등) (null = 키 안 보냄)",
    "common.tokens.mcp": "MCP 토큰(Authorization: Bearer — 검색 MCP 인증 · MCP를 띄우기 전에 정함 · 부르는 쪽도 같은 값) · 서버에서 openssl rand -hex 32를 실행해 나온 64자를 그대로 · 예 9f2c…(64자 16진수)",
    "mcp.server.fulltext_secret": "원문 도구 sfid 서명 키 — 원문 도구가 내주는 문서 번호(sfid)에 붙이는 서명용 비밀(바꾸면 이미 준 sfid 무효 · mcp_token과 다른 값) · 8자 이상 · 서버에서 openssl rand -hex 32를 실행해 나온 64자를 그대로 · 예 4be1…(64자 16진수)",
    "common.host.doc_src": "호스트 원본 문서 폴더 — 서버에 이미 있는 폴더(절대 경로 · UID 10001이 읽을 수 있게 — 컨테이너 /data/docs로 붙음 · 벌끼리 같아도 됨) · 예 /data/docs",
    "common.host.pg_container": "호스트 PG(pgvector) 컨테이너 이름(run_pipeline 문서 수·백업) · 예 pgvector",
    # common
    "common.connections.object_storage.region": "S3 리전 이름 · 예 us-east-1(스토리지 담당이 다른 값을 주면 그 값)",
    "common.connections.object_storage.verify_tls": "TLS 검증 · 1 검증·0 끔·사내 CA 파일 경로(예 /etc/pki/ca-trust/source/anchors/corp-ca.pem)",
    "common.connections.rdb.connect_kwargs": 'EDW pymssql 추가 인자 JSON · 예 {"login_timeout": 10} (null = 추가 인자 없음)',
    "common.models.embed.query_prefix": "질의 앞에 붙이는 지시문 · 예 'Query: ' (null = 질의 그대로)",
    "common.models.llm.cache_dir": "LLM 응답 캐시 폴더 · 예 /app/output/eval/llm_cache (null = output/eval/llm_cache)",
    "common.models.llm.extra_body": 'LLM 요청 본문에 합칠 JSON · 예 {"reasoning": {"enabled": false}} (null = 더하지 않음)',
    "common.models.llm.rpm": "LLM 분당 호출 상한 · 0 = 무제한",
    "common.models.vlm.concurrency": "문서 하나의 VLM 동시 요청 수",
    "common.models.vlm.extra_body": 'VLM 요청 본문에 합칠 JSON · 예 {"chat_template_kwargs": {"enable_thinking": false}} (null = 더하지 않음)',
    "common.models.vlm.max_concurrency": "프로세스 전체 VLM 동시 요청 상한",
    "common.models.vlm.timeout": "VLM 호출 1건 제한(초)",
    "common.models.guard.internal_host_suffixes": "내부망으로 볼 사내 도메인 접미사(이름이 사설 IP로 풀릴 때만) · 쉼표 구분 · 예 .mycorp.co.kr, .corp.local — 모델 주소가 '외부 주소'로 막힐 때만",
    "common.models.guard.internal_ip_ranges": "내부망으로 볼 사설 대역 밖 사내 IP 대역(CIDR) · 쉼표 구분 · 예 100.64.0.0/10, 10.200.0.0/16 — 모델 주소가 '외부 주소'로 막힐 때만",
    # extract
    "pipeline.extract.input_source": "파싱할 원본 · 폴더(예 /data/docs) 또는 rdb:csv:<목록 csv> (null = 준비 폴더)",
    "pipeline.connections.rdb.bucket": "원본 버킷 — 목록 key가 s3://버킷/… 꼴이 아닐 때 · 예 sfdc-files",
    "common.text.source_uri_prefix": "원본 주소 접두 · 예 s3://sfdc-files/docs (null = file://<docs_dir>)",
    "pipeline.extract.source.fetch_workers": "원본 받기 스레드 수",
    "pipeline.extract.source.staging": "미리 받기 폴더 · 예 /app/output/staging (null = 미리 받기 끔 — rdb:csv 원본을 못 받음)",
    "pipeline.extract.max_new": "이번 실행에서 새로 파싱할 문서 수 상한 · 0 = 제한 없음 (null = 제한 없음 · local은 local_max_new_docs_per_run)",
    "pipeline.extract.max_file_mb": "이 크기(MB)를 넘는 문서는 건너뜀 · 0 = 제한 없음",
    "pipeline.extract.prepare.rotate": "이미지·스캔 쪽 방향 바로잡기",
    "pipeline.extract.ocr.dpi": "쪽·그림 렌더 DPI(OCR·VLM 공용)",
    "pipeline.extract.ocr.max_pages": "문서당 OCR 쪽 상한 · 0 = 제한 없음",
    "pipeline.extract.ocr.threads": "onnxruntime 스레드 · 0 = 자동 (null = OMP_NUM_THREADS 또는 CPU 몫)",
    "pipeline.extract.rapidocr_page_workers": "rapidocr 쪽 병렬 스레드",
    # transform
    "pipeline.extract.doc_parallel": "represent 문서 병렬 스레드",
    "pipeline.transform.represent.post": "후처리 · all·none·쉼표 목록(vlm_page·supsub·charts·figures·context·attachments)",
    "pipeline.transform.represent.qa_light": "전체 문서 CER·순서 비교 생략",
    "pipeline.transform.represent.rep_select": "대표 엔진 고르기 · first·acc·best (null = best)",
    "pipeline.transform.vlm.figures_max": "문서당 그림 VLM 상한 · 0 = 그림 VLM 안 부름",
    "pipeline.transform.vlm.page_max": "문서당 쪽 VLM 상한 · 0 = 끔 (null = 전부)",
    "pipeline.transform.structure.embed_cache": "임베딩 캐시 sqlite · 0이면 끔 (null = output/edw/embed_cache.sqlite)",
    "pipeline.transform.structure.embed_concurrency": "임베딩 동시 호출 수",
    # load
    "pipeline.load.edw_path_prefix": "doc.file_path에 적을 경로 접두 · 예 /data/edw_files (null = 실제 경로 그대로)",
    "pipeline.load.bm25_threads": "BM25 계산 스레드",
    # search
    "mcp.server.host": "바인드 주소 · 127.0.0.1·auto(컨테이너 사설 IP)·사설 IP — 0.0.0.0은 거부",
    "mcp.server.port": "검색 MCP 포트 · 서버는 8051(컨테이너 안팎 같음) · 비우면 8765(PC)",
    "mcp.server.allowed_hosts": "더 허용할 Host 이름(리버스 프록시) · 쉼표 구분 · 예 rag.corp.local, rag2.corp.local",
    "mcp.server.manifest": "수집 manifest · 예 /app/output/parse/_source/manifest.jsonl (null = output/parse/_source/manifest.jsonl)",
    "mcp.server.max_concurrency": "도구 동시 실행 상한",
    "mcp.edw_meta.dir": "edw_meta 도구 카탈로그 폴더 · 예 /app/output/edw_meta (null = /app/config/edw_meta)",
    "mcp.edw_query.max_rows": "query_edw 행 상한",
    # ops
    "common.runtime.lib_env": "라이브러리 env(허용 목록만) · 예 {TZ: Asia/Seoul}",
    "common.runtime.pipe_procs": "엔진 프로세스 수 · 정수 또는 auto (null = CPU·메모리로 계산)",
    "common.runtime.pipe_workers": "VLM을 동시에 처리할 문서 수",
    "common.log.level": "DEBUG·INFO·WARNING·ERROR·CRITICAL",
    "common.log.dir": "JSON 로그 폴더 (null = PC output/logs · 서버 stdout)",
    "common.log.db_enabled": "DB 로그 켬/끔 (null = 이미지 켬 · PC 끔)",
    "common.log.fallback_dir": "DB 기록 실패 때 jsonl 폴더 · 예 /app/output/logs (null = output/logs)",
    "common.log.retention_days": "월 파티션 보존 일수",
    "common.paths.doc_dir": "원본 문서 폴더(PC는 저장소 기준 상대 가능) (null = 이미지 /data/docs · PC는 --src)",
    "common.paths.doc_dir_prepared": "준비 끝난 문서 폴더 · 예 /app/output/prepared (null = output/prepared)",
    "common.paths.draft_terms_out": "용어 초안 CSV · 예 /app/output/glossary_draft/terms.csv (null = output/glossary_draft/domain_terms_draft_auto.csv)",
    "common.paths.edw_chain": "EDW 사슬 파일 — 보통 비움 (null = 코드 폴더 맨 위 edw_chain.yaml — git으로 고침)",
    "common.paths.source_manifest": "원본 manifest.jsonl · 예 /data/docs/manifest.jsonl (null = docs_dir 기준 file://)",
    "pipeline.paths.images_root": "그림 PNG 폴더 · 예 /app/output/parse/_images (null = output/parse/_images)",
    "pipeline.paths.out_root": "파이프라인 결과 폴더(컨테이너 안) · 예 /app/output (null = <루트>/output)",
    "pipeline.paths.parse_tmp": "파싱 임시 폴더(output 아래 2단 이상) · 예 /app/output/_tmp_parse/stream (null = output/_tmp_parse/stream)",
    "pipeline.paths.raw_root": "raw·VLM 캐시 폴더 (null = 원본 층 캐시 안 씀)",
    "pipeline.paths.soffice_bin": "soffice 실행 파일 (null = PATH · 이미지 /usr/bin/soffice)",
    "common.host.docker": "컨테이너 명령 · docker·podman (null = podman, 없으면 docker)",
    "common.host.image_stage_dir": "prune_images.sh가 정리할 조각·tar 폴더 (null = 정리 안 함)",
    "common.host.prune_keep": "남길 이미지 판 수",
    "common.host.devbox.git_user_name": "git 커밋 이름(user.name) · 예 홍길동 (null = 설정 안 함)",
    "common.host.devbox.git_user_email": "git 커밋 메일(user.email) · 예 hong@corp.local (null = 설정 안 함)",
    "common.runtime.data_parsing_port": "더 쓰지 않음(#113 Redis 큐로 대체) — 다음 판에서 지움",
    "common.runtime.parse_max_mb": "parse_document 파일 상한(MB)",
    "pipeline.service.data_parsing.roots": "parse 서비스가 읽어도 되는 폴더 목록 · 쉼표 구분 · 예 /data/inbox, /data/shared (null = <서비스 폴더>/inbox)",
    "pipeline.host.nightly.time": "새벽 배치 시작 · HH:MM · 예 01:30 (null = 새벽 배치 없음 — 세 칸 다 적어야 켜짐)",
    "pipeline.host.nightly.max_docs": "새벽 배치 문서 수 · 1 이상 (null = 새벽 배치 없음)",
    "pipeline.host.nightly.deadline": "새벽 배치 멈춤 · HH:MM · 예 06:00 (null = 새벽 배치 없음)",
    "pipeline.host.run_pipeline_dir": "진행 기록 폴더(호스트) · 예 /srv/rag/run_pipeline-1(벌마다 다르게) (null = run_pipeline.py 옆 test_space/)",
    "pipeline.host.run_pipeline.run_limit": "사람이 돌릴 때 처리 건수 · 0 = 전체 (새벽 배치는 늘 전체 — 명령 인자 --limit이 덮음)",
    "pipeline.host.run_pipeline.steps_precheck": "① 사전 점검(설정·모델 연결·DB 판·배포 시험) — 실패하면 문서 처리 안 함",
    "pipeline.host.run_pipeline.steps_verify": "③ 적재·검색 확인(이번 실행 문서로 DB 검색 → 검색 MCP)",
    "pipeline.host.run_pipeline.staging": "미리 받아 둘 문서 수 · 1 이상",
    "pipeline.host.run_pipeline.staging_workers": "동시에 받는 문서 수 · 1 이상",
    "pipeline.host.run_pipeline.fetch_workers": "문서 하나 받기 스레드",
    "pipeline.host.run_pipeline.struct_workers": "구조화·적재 스레드",
    "pipeline.host.run_pipeline.struct_backlog": "구조화 대기 상한 · 0 = 없음 (null = workers × 2)",
    "pipeline.host.run_pipeline.embed_concurrency": "임베딩 동시 호출",
    "pipeline.host.run_pipeline.embed_batch": "호출당 청크 수",
    "pipeline.host.run_pipeline.bm25_threads": "BM25 스레드",
    "pipeline.host.run_pipeline.light_dedicated": "light 문서만 맡는 작업자",
    "pipeline.host.run_pipeline.light_shared": "light 먼저, 비면 다른 레인",
    "pipeline.host.run_pipeline.light_cpu_gate": "light 레인 CPU 문턱(부하÷코어)",
    "pipeline.host.run_pipeline.medium_dedicated": "medium 문서만 맡는 작업자",
    "pipeline.host.run_pipeline.medium_shared": "medium 먼저, 비면 다른 레인",
    "pipeline.host.run_pipeline.vlm_dedicated": "vlm 문서만 맡는 작업자",
    "pipeline.host.run_pipeline.vlm_shared": "vlm 먼저, 비면 다른 레인",
    "pipeline.host.run_pipeline.vlm_cap": "vlm 문서 동시 상한(GPU 예산) · 1 이상",
    "pipeline.host.run_pipeline.vlm_lane_concurrency": "vlm 문서 하나의 VLM 동시 요청",
    "pipeline.host.run_pipeline.vlm_lane_post": "vlm 레인 후처리 · 쉼표 목록",
    "pipeline.host.run_pipeline.vlm_concurrency": "light·medium 문서 하나의 VLM 동시 요청",
    "pipeline.host.run_pipeline.parse_post": "light·medium 후처리 · 쉼표 목록",
    "pipeline.host.run_pipeline.figures_max": "문서당 그림 VLM 상한",
    "pipeline.host.run_pipeline.rapidocr_page_workers": "rapidocr 쪽 스레드",
    "pipeline.host.run_pipeline.ocr_threads": "onnxruntime 스레드",
    "pipeline.host.run_pipeline.pipe_procs": "문서 하나의 엔진 프로세스",
    "pipeline.host.run_pipeline.rep_select": "대표 엔진 고르기 · first·acc·best",
    "pipeline.host.run_pipeline.qa_light": "전체 문서 CER·순서 비교 생략",
    "pipeline.host.run_pipeline.scan_rotate": "스캔 쪽 방향 바로잡기",
    "pipeline.host.run_pipeline.cpu_gate": "light 밖 레인 CPU 문턱(부하÷코어)",
    # tuning
    "common.connections.pg.connect_timeout": "PG 연결 제한(초)",
    "common.connections.pg.pool_max": "검색 MCP의 PG 연결 풀 크기",
    "common.models.embed.timeout": "임베딩 호출 제한(초)",
    "common.models.llm.empty_retry_max": "빈 응답 때 다시 요청할 토큰 상한",
    "common.models.llm.timeout": "LLM 호출 제한(초)",
    "common.models.transport.connect_timeout": "모델 연결 제한(초) · 0 = 끔",
    "common.models.transport.down_after": "이만큼 연속 실패하면 모델 서버를 내려감으로 봄",
    "common.models.transport.down_cooldown": "내려감 뒤 호출을 거부하는 시간(초)",
    "common.models.vlm.retry": "VLM 실패 재시도 횟수",
    "common.text.draft_terms_max": "용어 초안 행 상한",
    "common.text.search_en_stem": "검색 글자 영어 복수 → 단수",
    "common.text.token_num_norm": "검색 글자 숫자·단위 정규화",
    "pipeline.connections.rdb.file_table": "파싱 대상 파일 목록 EDW 표(<스키마>.<표> — 영문·숫자·_만) · 예 AI.FileStorageMap",
    "pipeline.connections.rdb.increment_col": "원천 목록 증분 판정 열 · 예 modified_at(원천 목록의 수정 시각 열) (null = 문서 ID 열)",
    "pipeline.connections.rdb.columns.doc_id": "원천 목록 열 이름 — 문서 ID · 예 id",
    "pipeline.connections.rdb.columns.filename": "원천 목록 열 이름 — 원래 파일 이름 · 예 original_filename",
    "pipeline.connections.rdb.columns.key": "원천 목록 열 이름 — Object Storage key · 예 s3_key",
    "pipeline.connections.rdb.columns.size": "원천 목록 열 이름 — 파일 크기 · 예 file_size",
    "pipeline.connections.rdb.columns.source_system": "원천 목록 열 이름 — 원천 · 예 source_system",
    "pipeline.extract.engine_retry": "엔진 비정상 종료 재시도 횟수",
    "pipeline.extract.fill_merged": "병합 셀 채우기",
    "pipeline.extract.hidden_overlap_max": "숨은 겹침 쪽 VLM 후보 상한 · 0 = 끔",
    "pipeline.extract.isolate_overhead": "별도 프로세스 시작 여유(초)",
    "pipeline.extract.kreuzberg_prose_filter": "평문을 표로 잘못 본 것 거르기",
    "pipeline.extract.low_priority": "엔진 프로세스 우선순위 낮춤(nice +10)",
    "pipeline.extract.rotated_max": "회전 쪽 VLM 후보 상한 · 0 = 끔",
    "pipeline.extract.text_page_sec": "글자 엔진 쪽당 제한(초)",
    "pipeline.extract.table_grid_max_rows": "표 격자 행 상한",
    "pipeline.extract.warmup_sec": "첫 문서 제한 시간 하한(초)",
    "pipeline.extract.archive.max_files": "압축 원본 안 파일 수 상한",
    "pipeline.extract.archive.max_total_mb": "압축 원본 풀린 크기 합계 상한(MB)",
    "pipeline.extract.attach.max_depth": "문서 안 문서(압축·첨부·개체) 깊이",
    "pipeline.extract.attach.max_mb": "메일 첨부·개체 1개 상한(MB)",
    "pipeline.extract.attach.max_n": "메일·오피스 파일 하나의 첨부·개체 수 상한",
    "pipeline.extract.attach.timeout": "첨부 파싱 제한(초)",
    "pipeline.extract.cache.parse_cache_max_gb": "재판독 캐시 상한(GB) · 0 = 끔",
    "pipeline.extract.ocr.table_grid": "OCR 글자 상자로 표 격자 만들기",
    "pipeline.transform.figures.ocr_fallback_min_chars": "OCR 글자가 이보다 적으면 로고로 보고 버림",
    "pipeline.transform.figures.ocr_parallel": "그림 OCR 병렬 스레드",
    "pipeline.transform.figures.pptx_convert_sec": "soffice 문서 → PDF 변환 제한(초)",
    "pipeline.transform.figures.pptx_render_max": "렌더할 슬라이드 상한",
    "pipeline.transform.figures.pptx_shapes_max": "도형 슬라이드 후보 상한 · 0 = 이 사유 안 봄",
    "pipeline.transform.figures.pptx_smartart_max": "SmartArt 슬라이드 후보 상한 · 0 = 이 사유 안 봄",
    "pipeline.transform.figures.vectors_max": "벡터 그림 쪽 후보 상한 · 0 = 이 사유 안 봄",
    "pipeline.transform.vlm.fig_min_px": "짧은 변이 이보다 작은 그림은 뺌(px)",
    "pipeline.transform.vlm.fig_ocr_max": "문서당 그림 OCR 횟수 상한",
    "pipeline.transform.vlm.fig_photo_area_min": "사진으로 볼 최소 면적 비율 · 0~1",
    "pipeline.transform.vlm.fig_photo_max_tokens": "사진 설명 응답 토큰 상한",
    "pipeline.transform.vlm.fig_photo_ocr_max": "OCR 글자가 이 이하면 사진류",
    "pipeline.transform.vlm.fig_text_ocr_min": "OCR 글자가 이 이상이면 글자 이미지",
    "pipeline.transform.structure.chunk_size": "청크 목표 글자 수 (null = 청커 기본 800)",
    "pipeline.transform.structure.chunk_table": "표 나누기 · rows (null = 표 통째로)",
    "pipeline.transform.structure.chunk_table_rows": "split_tables: rows일 때 청크당 행 수",
    "pipeline.transform.structure.embed_batch": "임베딩 호출당 청크 수",
    "pipeline.transform.structure.embed_max_chars": "임베딩할 글자 상한(넘으면 자름)",
    "pipeline.transform.structure.embed_retry": "임베딩 실패 재시도 횟수",
    "pipeline.load.publish.upload_statuses": "게시할 결과 상태 · ok·partial·failed 중 쉼표 구분 · 예 ok, partial, failed",
    "mcp.audit.max_queue_bytes": "감사 기록 대기 상한(바이트)",
    "mcp.audit.max_input_bytes": "감사 기록 입력 원문 상한(바이트)",
    "mcp.audit.max_output_bytes": "감사 기록 출력 원문 상한(바이트)",
    "mcp.edw_meta.max_bytes": "edw_meta 응답 크기 상한(바이트)",
    "mcp.edw_query.max_bytes": "query_edw 응답 크기 상한(바이트)",
    "mcp.edw_query.timeout_sec": "query_edw 질의 제한(초)",
    "mcp.output.max_chars": "search 응답 크기 상한(바이트)",
    "mcp.search.methods": "기본 검색 방법 · vector·bm25·id 중 쉼표 구분 · 예 vector, bm25",
    "mcp.search.pg.filter_exact_max": "걸러진 청크가 이 이하면 정확 검색",
    "mcp.search.weights.bm25": "순위 합치기(RRF) 가중치 — BM25",
    "mcp.search.weights.bm25_table": "집계 질문의 BM25 가중치",
    "mcp.search.weights.id": "순위 합치기(RRF) 가중치 — ID",
    "mcp.search.weights.vector": "순위 합치기(RRF) 가중치 — 벡터",
    "mcp.server.max_queue": "도구 대기 상한 · 0 = 무제한 (null = 동시 상한 × 4)",
    "mcp.server.pg_statement_timeout_sec": "검색 MCP PG 질의 하나의 제한(초) · 0 = 끔",
    "mcp.server.reload_check_sec": "적재 판 확인 간격(초)",
    "mcp.server.tool_timeout_sec": "도구 1회 제한(초) · 0 = 무제한",
    "common.log.queue_size": "DB 로그 대기열 크기",
    "common.log.batch_size": "DB 로그 INSERT 묶음 행 수",
    "common.log.flush_sec": "DB 로그 기록 간격(초)",
    "common.log.db_timeout_sec": "로그 DB 제한(초)",
    "common.log.shutdown_sec": "종료 때 로그 비우기 상한(초)",
    "common.runtime.cpu_max_load": "새 작업을 미루는 CPU 부하(부하÷코어)",
    "common.runtime.draft_terms_lock_timeout": "용어 초안 CSV 쓰기 잠금 대기(초)",
    "common.runtime.mem_max_pct": "새 프로세스를 띄울 메모리 상한(%)",
    "common.runtime.mem_settle_margin": "상한 아래 이만큼(%p) 내려올 때까지 쉼",
    "common.runtime.mem_settle_sec": "메모리 확인 사이 쉬는 시간(초)",
    "common.runtime.pipe_max_procs": "자동 계산 엔진 프로세스 상한",
    "common.runtime.pipe_proc_gb": "엔진 프로세스 하나가 쓴다고 볼 메모리(GB)",
    "common.runtime.pipe_reserve_cpus": "자동 계산 때 남길 코어 수",
    "common.runtime.pipe_reserve_gb": "자동 계산 때 남길 메모리(GB)",
    "common.runtime.pipe_threads": "프로세스당 OMP·MKL 스레드 (null = CPU ÷ 프로세스 수)",
    "pipeline.service.data_parsing.job_timeout_sec": "parse 작업 1건 제한(초)",
    "pipeline.service.data_parsing.procs": "parse 서비스 엔진 프로세스 (null = min(2, CPU − 1) — worker마다)",
    "common.parse_queue.queue_max": "parse 대기 작업 상한",
    "pipeline.service.data_parsing.text_page_sec": "parse 글자 엔진 쪽당 제한(초)",
    "pipeline.service.data_parsing.warmup_sec": "parse 첫 시도 제한 하한(초)",
    # dev
    "common.models.embed.allow_external": "외부 임베딩 허용(local만)",
    "common.models.llm.allow_external": "외부 LLM 허용(local만)",
    "common.models.vlm.allow_external": "외부 VLM 허용(local만)",
    "common.models.embed.est_usd": "외부 임베딩 1건 예상 비용($)",
    "common.models.llm.est_usd": "외부 LLM 도구 왕복 1턴 예상 비용($)",
    "common.models.vlm.est_usd": "외부 VLM 1건 예상 비용($)",
    "common.models.llm.price_in": "입력 단가($/백만 토큰) (null = 내장 가격표 — 표에 없으면 외부 호출 거부)",
    "common.models.llm.price_out": "출력 단가($/백만 토큰) (null = 내장 가격표)",
    "common.models.guard.budget_usd": "하루 외부 모델 지출 상한($)",
    "common.models.guard.spend_file": "지출 장부 · 예 output/_llm_spend/today.txt (null = output/_llm_spend/<날짜>.txt)",
    "common.dev.llm_fake": "가짜 LLM 응답(서버면 시작 거부)",
    "mcp.dev.mcp_url": "검증 페이지가 붙을 검색 MCP 주소 · 예 http://127.0.0.1:8765/mcp",
    "mcp.dev.ui_port": "검증 페이지 포트",
    "common.dev.docker.pg_image": "시험 PG 이미지 · 예 pgvector/pgvector:pg16",
    "common.dev.docker.mcp_publish_port": "시험 검색 MCP를 호스트에 게시할 포트",
    "common.dev.docker.smoke_settings": "스모크 시험용 settings.yaml — 스모크 시험 때 필수 · 예 /home/me/smoke/settings.yaml (null = 스모크 시작 안 함)",
    "common.dev.docker.smoke_pg_password": "스모크 시험 PG 비밀번호(스모크 시험 때 필수) · 예 아무 글자",
    "common.dev.docker.smoke_keep": "스모크 시험이 끝나도 PG를 남김",
    "common.dev.docker.smoke_limit": "스모크 시험 문서 수 · 0 = 제한 없음",
}

TITLES = {
    "tuning": "tuning — 거의 바꾸지 않는 값(분류별 — 결과 파라미터·내부 상한·제한 시간·자원 세부값). 코드 기본값 그대로 두는 것이 보통.",
    "dev": "dev — PC 전용(RUN_ENV=local): 외부 모델·지출 상한·PC 시험 도구. 서버(dev·prd)는 이 절을 비워 둔다(서버에서 거부).",
    "option": "option — 선택 기능(앱이 쓰지 않음 — 호스트 스크립트만). 비우면 끔.",
}


def build(classes=None):
    classes = classes or S.app_classes()
    rows = {}
    for cls in classes.values():
        for p, f, _ in S.walk(cls):
            rows.setdefault(p, f)
    # #113: queue_max를 common으로 옮겨도 기존 sample의 표시 순서(job timeout → procs → queue)를 유지.
    queue = "common.parse_queue.queue_max"
    procs = "pipeline.service.data_parsing.procs"
    if queue in rows and procs in rows:
        field = rows.pop(queue)
        ordered = {}
        for path, value in rows.items():
            ordered[path] = value
            if path == procs:
                ordered[queue] = field
        rows = ordered
    tree = {}
    for p, f in rows.items():
        L.set_path(tree, L.to_yaml(p), (p, f))
    missing = sorted(set(rows) - set(NOTES))
    if missing:
        raise SystemExit(f"sample: NOTES에 주석이 없는 칸 {missing}")
    if {"pipeline", "mcp"} <= set(classes):  # 시험이 앱 일부로 부를 때는 대조 안 함
        unknown = (set(L.REQUIRED) | set(L.PLACED) | L.TUNING | set(NOTES)) - set(rows)
        if unknown:
            raise SystemExit(f"sample: layout·NOTES에 모델에 없는 칸 {sorted(unknown)}")
    lines = [HEAD]
    for sec in L.SECTIONS:
        if sec not in tree:
            continue
        lines.append(f"\n# {'═' * 94}" if sec in ("common", "tuning", "dev", "option") else "")
        if sec in TITLES:
            lines.append(f"# {TITLES[sec]}")
            lines.append(f"# {'═' * 94}")
        lines.append(f"{sec}:")
        _emit(tree[sec], 1, sec, lines, [None])
    return "\n".join(lines) + "\n"


def _cat(y):
    """파일 자리 → (카테고리 번호, 제목). required는 REQUIRED_GROUPS 순서, 그 밖은 CATEGORIES."""
    sec = y.split(".", 1)[0]
    if sec == "required":  # (묶음 번호, 작은 묶음 번호) — 작은 묶음이 없으면 0·묶음 제목
        parts = y.split(".")
        g, leaf = parts[1], parts[2] if len(parts) > 2 else ""
        gi, (_k, title, rows) = next((i, r) for i, r in enumerate(L.REQUIRED_GROUPS) if r[0] == g)
        si = 0
        for r in rows:
            if isinstance(r, str):
                si, title = si + 1, r
            elif r[0] == leaf:
                return (gi, si), title
        return (gi, 0), L.REQUIRED_GROUPS[gi][1]
    for i, (title, pre) in enumerate(CATEGORIES[sec]):
        if any(y == x or y.startswith(x + ".") for x in pre):
            return i, title
    raise SystemExit(f"sample: 세부 카테고리(CATEGORIES)에 안 드는 칸 {y} — CATEGORIES에 접두어를 더함")


def _emit(node, depth, path, lines, last):
    """절 안 칸을 settings.yaml 꼴로 — 세부 카테고리 순서로 놓고, 카테고리가 바뀌는 자리에 제목 주석."""
    pad = "  " * depth

    def first(y, v):
        return _cat(y)[0] if isinstance(v, tuple) else min(first(f"{y}.{k}", x) for k, x in v.items())

    order = list(L.REQUIRED.values())  # required는 표 순서, 그 밖은 카테고리 안 모델 순서(안정 정렬)
    kids = sorted(
        ((first(f"{path}.{k}", v), k, v) for k, v in node.items()),
        key=lambda r: (r[0], order.index(f"{path}.{r[1]}") if f"{path}.{r[1]}" in order else 0),
    )
    for i, name, v in kids:
        y = f"{path}.{name}"
        group = path == "required" and not isinstance(v, tuple)  # required 묶음 줄은 묶음 제목 — 작은 묶음 제목은 그 안 칸 앞에
        if group:
            i = _cat(y)[0]
        if last[0] != (path.split(".")[0], i):
            last[0] = (path.split(".")[0], i)
            lines.append(f"{pad}# ---- {_cat(y if isinstance(v, tuple) or group else _first_leaf(y, v))[1]} ----")
        if not isinstance(v, tuple):
            lines.append(f"{pad}{name}:")
            _emit(v, depth + 1, y, lines, last)
            continue
        p, f = v
        value = _value(p, f)
        head = f"{pad}{name}:" + (f" {value}" if value else "")
        lines.append(f"{head.ljust(NOTE_COL - 2)}  # {_note(p, f)}")  # 주석을 한 열로


def _first_leaf(y, node):
    k, v = min(node.items(), key=lambda kv: _cat(f"{y}.{kv[0]}" if isinstance(kv[1], tuple) else _first_leaf(f"{y}.{kv[0]}", kv[1]))[0])
    return f"{y}.{k}" if isinstance(v, tuple) else _first_leaf(f"{y}.{k}", v)


_IMAGE_ENVS = {k for d in S._IMAGE_DEFAULTS.values() for k in d}
# 적었는지(기본값과 구별 — given()·resources._f)로 동작이 갈리는 칸 — 기본값이 계산값이라 적으면 계산이 꺼진다. null로 낸다.
# 시험 test_sample_yaml이 코드의 given("X")·_f("X", 기본) 이름이 여기 있거나, _f의 대체값이 모델 기본값과 같은지 본다.
SET_MATTERS = {"PIPE_PROCS", "PIPE_THREADS", "PM_BUCKET"}


def _value(p, f):
    """칸에 적을 값(YAML 한 줄) — 코드 기본값. 빈 글자: 사람이 꼭 적을 [필수] 칸(layout.NEED가 "필수"). null: 기본 없음·비밀·빈 글자·
    이미지 기본값 칸(이미지·PC 값이 다름)·SET_MATTERS·저장소 경로가 든 기본값. YAML에서 빈 칸과 null은 같다(둘 다 비움)."""
    d = f.get_default(call_default_factory=True)
    if L.NEED.get(p, "").startswith("필수") and d is None:  # 기본값이 있는 필수 칸은 그 값을 적어 둠(edw_file_table)
        return ""
    if S.is_secret(f) or d is None or d == "" or S.env_name(f) in _IMAGE_ENVS | SET_MATTERS:
        return "null"
    if isinstance(d, str) and str(S.REPO_ROOT) in d:
        return "null"
    if d == []:  # 빈 목록 = null(비우면 코드 기본값 [])
        return "null"
    # 글자 목록은 쉼표 구분(사람이 적기 쉽게 — CsvList가 읽음)
    if S.field_kind(f.annotation) == "list" and all(isinstance(x, str) for x in d):
        s = ", ".join(d)
        if yaml.safe_load(s) == s:
            return s
    return yaml.safe_dump(d, default_flow_style=True, allow_unicode=True, width=10**9).removesuffix("\n").removesuffix("\n...")


def _note(p, f):
    """칸 주석 한 줄 — [필수·선택](required) + NOTES + [비밀]. 옛 env 이름·판정 꼴은 --where·docs/operations/env-guide.md에."""
    need = f"[{L.NEED[p]}] " if p in L.NEED else ""
    note = NOTES[p]
    hint = _allowed(f)
    if hint and hint not in note:  # 입력 후보(켜기·고른 글자·정수·숫자 + 범위)가 설명에 없으면 붙임
        note += f" · {hint}"
    return f"{need}{note}" + (" [비밀]" if S.is_secret(f) else "")


def _allowed(f):
    """칸 꼴 → 입력 후보 글자(켜기·고른 글자·정수·숫자 + 범위). 글자 칸은 ""(NOTES에 예를 적는다)."""
    args = S._args(f.annotation)
    if bool in args:
        return "true(켬)·false(끔)"
    lits = [x for a in args if get_origin(a) is Literal for x in get_args(a)]
    if lits:
        return "·".join(str(x) for x in lits)
    if any(a is float for a in args):
        kind = "숫자"
    elif any(a is int or get_args(a)[:1] == (int,) for a in args):  # Port = Annotated[int, …]
        kind = "정수"
    else:
        return ""
    lo = [f"{m.ge} 이상" for m in f.metadata if getattr(m, "ge", None) is not None]
    lo += [f"{m.gt} 초과" for m in f.metadata if getattr(m, "gt", None) is not None]
    hi = [f"{m.le} 이하" for m in f.metadata if getattr(m, "le", None) is not None]
    return " ".join([kind, *lo, *hi])


def marks(f):
    """sample 주석에서 뺀 내부 표시(op-08 ②) — 지문 고정·빈 글자 유지·켜기 판정 꼴·auto."""
    extra = f.json_schema_extra or {}
    out = []
    if S.keeps_blank(f):
        out.append("[빈 글자 유지]")
    truth = extra.get("truth")
    if truth:
        words = "·".join(repr(x) if x == "" else x for x in (truth["on"] or truth["off"]))
        out.append(f"[{'켬' if truth['on'] else '끔'}: {words}{'' if len(truth['on'] or truth['off']) > 1 else '만'}]")
    if extra.get("unset") == ["auto"]:
        out.append("[auto = 비움]")
    elif extra.get("unset") == "nondigit":
        out.append("[숫자 아니면 비움]")
    return out


def where(names):
    """옛 env 이름 → (이름, 파일 자리, 모델 경로, 표시) — 모르는 이름은 자리 None."""
    from common.config.setarg import _fields  # 같은 이름이 호스트 칸·앱 칸 둘 다면 앱 칸(--set과 같은 규칙)

    paths = _fields()
    rows = {p: f for cls in (S.CommonAppSettings, *S.app_classes().values()) for p, f, _ in S.walk(cls)}
    out = []
    for n in names:
        p = paths.get(n, (None,))[0]
        f = rows.get(p)
        out.append((n, L.to_yaml(p) if p else None, p, marks(f) if f is not None else []))
    return out


def main(argv):
    utf8_stdout()
    if "--where" in argv:
        found = where(argv[argv.index("--where") + 1 :])
        for n, y, p, m in found:
            print(f"{n}\t{y or '(설정 칸 없음)'}" + (f"\t(모델 {p}) {' '.join(m)}".rstrip() if p else ""))
        return 0 if all(y for _, y, _, _ in found) else 1
    text = build()
    if "--check" in argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        ok = cur == text
        print(
            "settings.sample.yaml: 모델과 같음" if ok else "settings.sample.yaml: 모델과 다름 — python -m common.config.sample로 다시 만듦"
        )
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"씀: {OUT.relative_to(S.REPO_ROOT)} ({text.count(chr(10))}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
