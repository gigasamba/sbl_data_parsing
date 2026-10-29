-- [SYNTHETIC] EDW 적재 형식(예시) — SQL Server(T-SQL)
CREATE TABLE edw.contract_master (
  contract_id        varchar(20)   NOT NULL PRIMARY KEY,
  company            nvarchar(100) NOT NULL,
  company_id         varchar(10)   NOT NULL,
  product_code       varchar(20)   NOT NULL,
  modality           varchar(20)   NOT NULL,
  site               varchar(10)   NOT NULL,   -- 생산 공장 ID
  line_id            varchar(10)   NULL,
  batches_contracted int           NOT NULL,   -- 생산 배치 총 개수
  contract_value_usd decimal(14,0) NOT NULL,   -- 계약 총액
  currency           char(3)       NOT NULL,
  term_months        int           NOT NULL,
  signed_on          date          NOT NULL,
  start_date         date          NOT NULL,
  end_date           date          NOT NULL,
  status             varchar(12)   NOT NULL
);
CREATE TABLE edw.client_master (company_id varchar(10) PRIMARY KEY, company nvarchar(100) NOT NULL, aliases nvarchar(400) NULL);

-- 문서 위치 메타(Object Storage 경유 파싱용, 2026-10-07 RDB 기반 fetch 시험) — RDB가 "무엇을 어디서 가져올지"를 쥐고
-- 파싱은 이 표의 목록만큼만 Object Storage에서 받는다(버킷 prefix 전체 나열 대신).
CREATE TABLE edw.doc_location (
  doc_id       varchar(80)   NOT NULL PRIMARY KEY,   -- 파일 stem(확장자 제외) — 문서 식별자
  bucket       varchar(63)   NOT NULL,                -- Object Storage 버킷 이름
  object_key   nvarchar(400) NOT NULL,                -- 버킷 안 경로(접두 포함) — clients/<company_id>/<yyyy>/<file>
  etag         varchar(40)   NOT NULL,                -- Object Storage ETag(S3 호환, md5 — 쿼팅은 호출부에서)
  size_bytes   bigint        NOT NULL,
  content_type varchar(120)  NOT NULL,
  company_id   varchar(10)   NOT NULL,                -- client_master.company_id로 조인
  doc_type     varchar(10)   NOT NULL,                 -- RFI | RFP (업무 문서 종류)
  contract_id  varchar(20)   NULL,                      -- contract_master.contract_id로 조인(모르면 NULL — link로 추론)
  updated_at   datetime2     NOT NULL                   -- Object Storage 최종 수정 시각(증분 선별용)
);

-- 표·열 설명(스키마 자체 — LLM이 "SQL로 답할지 검색으로 답할지" 고를 때 참조)
CREATE TABLE edw.data_catalog (
  table_name  varchar(40)  NOT NULL,
  column_name varchar(40)  NULL,     -- NULL = 표 단위 설명 행
  description nvarchar(400) NOT NULL,
  PRIMARY KEY (table_name, column_name)
);
