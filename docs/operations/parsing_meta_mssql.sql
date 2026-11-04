-- EDW(SQL Server) 파싱 결과 메타 표 AI.ParsingMeta — 사람·DBA가 실행(코드는 표를 만들지 않음). 다시 실행해도 안전(이미 있으면 건너뜀).
-- 쓰는 곳: pipeline/load/publish_parse_result.py(INSERT만 — 쓰기 계정 settings.yaml required.edw.write_*) ·
--   pipeline/load/pgvector_load.py(적재 때 loaded_at·gold_version UPDATE) · mcp_server/services/fulltext.py(list_doc_fulltext — 읽기 계정)
-- 열 이름·순서 = common/store/parsing_meta_db.py COLUMNS(tests/server/common/test_db_schema.py가 같은지 고정).
-- ⚠ 0.2.0 칸 바꾸기(칸 이름·loaded_at·gold_version 등 — refactor.md C-76)는 이 파일에 없다 — DB 담당·EDW 담당과 정한다.
-- rep_key = 문서 폴더 `.../Parsing-Result/<출처>/<UUID>/<원본파일명>/`(끝 '/'),
--   parse_date = 'YYYY-MM-DD_HHMMSS'(같은 이름 충돌 시 '-2'… 접미) — 날짜형이 아니라 글자.
-- 필수 열은 doc_key 하나(그 밖은 비어도 됨). 쓰인 파싱 엔진(VLM·OCR 포함) 전부를 engines_used·engines_summary에 기록.
-- 필터(WHERE) 유일 색인 때문에 표를 만들 때와 그 표에 쓰는 모든 세션에서 아래 SET 옵션 7개가 이대로여야 한다
--   (하나라도 어긋나면 INSERT·UPDATE가 "필터 색인이 있는 표에 맞지 않는 SET 옵션" 오류로 거부됨). 쓰기 쪽도 연결마다
--   같은 SET을 실행한다(common/store/parsing_meta_db.py).
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET ARITHABORT ON;
SET NUMERIC_ROUNDABORT OFF;
GO
-- 다른 스키마·표 이름이면 settings.yaml required.edw.parsing_meta_table(<스키마.표>)과 함께 아래 [AI].[ParsingMeta]를 바꿔 실행.
IF SCHEMA_ID(N'AI') IS NULL EXEC(N'CREATE SCHEMA [AI]');
GO
-- 독립 검토 반영 — 다시 실행해도 안전(이미 있으면 건너뜀, DBA가 실수로 두 번 돌려도 안 깨짐).
IF OBJECT_ID(N'AI.ParsingMeta', N'U') IS NULL
CREATE TABLE [AI].[ParsingMeta] (
    parse_meta_id     BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    source_system     NVARCHAR(64)   NULL,        -- 원천(예: FileStorageMap) — PM2: 비어도 됨(코드가 빈 값을 'unknown'으로)
    source_key        NVARCHAR(1024) NULL,        -- 원천 안 원본 키(Object Storage 키 상한 1024) — PM2: 없어도 됨(그때는 doc_key가 겹침 키)
    source_uri        NVARCHAR(2048) NULL,
    original_filename NVARCHAR(512)  NULL,
    file_format       NVARCHAR(32)   NULL,
    file_size         BIGINT         NULL,
    sha256            NVARCHAR(64)   NULL,
    rep_bucket        NVARCHAR(256)  NULL,
    rep_key           NVARCHAR(2048) NULL,       -- 문서 폴더(끝 '/') — 그 안 <파일명>_<parse_date>.md·.json·_meta.json·engine/·source.json
    rep_etag          NVARCHAR(128)  NULL,
    parse_status      NVARCHAR(32)   NULL,       -- ok·partial (failed·skipped_*는 EDW에 안 넣음)
    status_reason     NVARCHAR(2000) NULL,
    rep_engine        NVARCHAR(128)  NULL,
    rep_acc           FLOAT          NULL,
    page_count        INT            NULL,
    doc_key           NVARCHAR(64)   NOT NULL,   -- PM2 — 유일한 필수 열(원본 sha256, 회전 전). 게시 시점에 항상 구함
                                                  -- (대표 결과의 doc_key, 없으면 manifest의 원본 sha256) — 검색 MCP가 이 값으로 조회
    parse_date        NVARCHAR(32)   NULL,       -- PM2: 비어도 됨(코드가 처리 시각으로) — 글자 'YYYY-MM-DD_HHMMSS'[-n]
    pipeline_version  NVARCHAR(64)   NULL,
    status            NVARCHAR(16)   NULL,       -- active·changed·deleted
    status_at         NVARCHAR(32)   NULL,       -- UTC 'YYYY-MM-DDTHH:MM:SSZ'
    -- PM2 요건(b) — 이 문서에 실제로 쓰인 엔진 전부(대표·후보·OCR·VLM 쪽 옮기기·그림·재판독·AG11 에이전트).
    -- engines_used = JSON 배열 [{"engine","role":"rep|candidate|ocr|vlm_page|vlm_figure|reread|agent","status","version_or_model","calls"}],
    -- engines_summary = 사람이 읽는 한 줄(예 "rep=rapidocr_ko; text=kreuzberg,markitdown,pymupdf; vlm=<모델> page×3 fig×3").
    -- 만드는 곳: pipeline/load/parsing_meta.py의 engines_used() — _rep/<문서>.json만 읽는 순수 함수.
    engines_used      NVARCHAR(MAX)  NULL,
    engines_summary   NVARCHAR(512)  NULL,
    parsed_at         DATETIME2(0)   NOT NULL CONSTRAINT DF_ParsingMeta_parsed_at DEFAULT SYSUTCDATETIME(),
    -- source_key가 길어(1024자 = 2048바이트) 그대로는 색인 키 상한(1700바이트)을 넘음 → sha256으로 줄여 유일 키에
    -- (source_key가 NULL이면 이 값도 NULL — 그 행은 아래 두 번째 필터 색인(doc_key 기준)으로 겹침을 막는다)
    source_key_hash   AS CAST(HASHBYTES('SHA2_256', source_key) AS BINARY(32)) PERSISTED,
    CONSTRAINT CK_ParsingMeta_status CHECK (status IN (N'active', N'changed', N'deleted'))
);
GO
-- PM2 — 겹침/건너뜀 키를 둘로: source_key가 있으면 (출처, 원본 키, 날짜) · 없으면(최소 키 요건) doc_key만으로.
-- SQL Server는 CREATE TABLE 안 CONSTRAINT로 필터(WHERE) 유일 키를 못 만들어 표 밖에서 필터 색인 두 개로 대신.
-- 독립 검토 반영 — 세 색인 다 IF NOT EXISTS로(다시 실행해도 안전).
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UQ_ParsingMeta_key' AND object_id = OBJECT_ID(N'AI.ParsingMeta'))
CREATE UNIQUE INDEX UQ_ParsingMeta_key ON [AI].[ParsingMeta] (source_system, source_key_hash, parse_date)
    WHERE source_key IS NOT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UQ_ParsingMeta_dockey' AND object_id = OBJECT_ID(N'AI.ParsingMeta'))
CREATE UNIQUE INDEX UQ_ParsingMeta_dockey ON [AI].[ParsingMeta] (doc_key, parse_date)
    WHERE source_key IS NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ParsingMeta_doc_key' AND object_id = OBJECT_ID(N'AI.ParsingMeta'))
CREATE INDEX IX_ParsingMeta_doc_key ON [AI].[ParsingMeta] (doc_key);
GO
-- 쓰기 계정(common.connections.rdb.write)은 이 표에 SELECT·INSERT·UPDATE만(DELETE·DDL 없음), 읽기(검색 MCP)는 SELECT만.
-- ponytail: 이미 있는지 확인(SELECT … WHERE source_system=? AND source_key=? 또는 doc_key=?)은 색인을 못 타
--   표 훑기 일 수 있다 — 행 수가 수십만을 넘어 게시가 느려지면 코드 쪽 조회를 더 다듬을 것.
