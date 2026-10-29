-- [SYNTHETIC] EDW 스타일 RDB 적재 형식(예시) — SQL Server(T-SQL), 문서 메타까지 RDB가 관리
CREATE TABLE edw.client_master (company_id varchar(10) PRIMARY KEY, company nvarchar(100) NOT NULL, aliases nvarchar(400) NULL);

CREATE TABLE edw.contract_master (
  contract_id        varchar(20)   NOT NULL PRIMARY KEY,
  company            nvarchar(100) NOT NULL,
  company_id         varchar(10)   NOT NULL,
  product_code       varchar(20)   NOT NULL,
  modality           varchar(20)   NOT NULL,
  site                varchar(10)   NOT NULL,   -- 생산 공장 ID
  line_id             varchar(10)   NULL,
  batches_contracted  int           NOT NULL,   -- 생산 배치 총 개수
  contract_value_usd  decimal(14,0) NOT NULL,   -- 계약 총액
  currency             char(3)       NOT NULL,
  term_months          int           NOT NULL,
  signed_on            date          NOT NULL,
  start_date           date          NOT NULL,
  end_date             date          NOT NULL,
  status                varchar(12)   NOT NULL
);

-- 문서 위치·판·삭제 메타(Object Storage 경유 파싱용, AD44) — RDB가 "무엇을 어디서 가져올지·최신판인지"를 쥐고 있어
-- 파싱은 이 표의 목록만큼만 Object Storage에서 받는다(버킷 prefix 전체 나열 대신). 목록 조회는 company_id·doc_type·updated_at로.
CREATE TABLE edw.doc_location (
  doc_id              varchar(80)   NOT NULL PRIMARY KEY,   -- 파일 stem(확장자 제외)
  bucket              varchar(63)   NOT NULL,
  object_key          nvarchar(400) NOT NULL,                -- clients/<company_id>/<yyyy>/<file>
  etag                varchar(40)   NOT NULL,                -- md5(쿼팅은 호출부)
  size_bytes          bigint        NOT NULL,
  content_type        varchar(120)  NOT NULL,
  company_id          varchar(10)   NOT NULL,                -- client_master.company_id로 조인
  doc_type            varchar(12)   NOT NULL,                 -- RFI_ANSWER|RFI|RFP|CONTRACT|QUOTE|MAIL|MINUTES
  contract_id         varchar(20)   NULL,                      -- contract_master.contract_id로 조인(모르면 NULL — RFI_ANSWER·실주)
  version             int           NOT NULL DEFAULT 1,        -- 같은 문서 계열 안에서 1부터
  supersedes_doc_id   varchar(80)   NULL,                      -- 이 판이 대체하는 이전 판(doc_location.doc_id)
  language            varchar(5)    NOT NULL,                  -- ko|en
  received_at         date          NOT NULL,
  updated_at          datetime2     NOT NULL,                  -- Object Storage 최종 수정 시각(증분 선별용)
  is_deleted          bit           NOT NULL DEFAULT 0          -- 1=삭제(목록·최신판에서 제외)
);

-- 문서↔계약 연결(추론 결과) — common/structdb.py의 doc_contract_link와 같은 모양. 파이프라인 link 명령이 채운다(이 세트는 빈 표).
CREATE TABLE edw.doc_contract_link (
  doc_key              varchar(80)  NOT NULL PRIMARY KEY,
  contract_id          varchar(20)  NULL,
  score                 int          NULL,
  how                    varchar(40)  NULL,
  status                 varchar(12)  NULL,                    -- 확정|후보
  evidence_chunk_keys  nvarchar(max) NULL,
  created_at            datetime2    NULL
);

-- 표·열 설명(스키마 자체 — LLM이 "SQL로 답할지 검색으로 답할지" 고를 때 참조)
CREATE TABLE edw.data_catalog (
  table_name   varchar(40)  NOT NULL,
  column_name  varchar(40)  NULL,     -- NULL = 표 단위 설명 행
  description  nvarchar(400) NOT NULL,
  unit          varchar(20)  NULL,
  example       nvarchar(200) NULL,
  allowed_values nvarchar(200) NULL,
  join_key      nvarchar(100) NULL,
  answers       nvarchar(200) NULL,    -- 이 열로 답할 수 있는 질문 유형(힌트)
  PRIMARY KEY (table_name, column_name)
);
