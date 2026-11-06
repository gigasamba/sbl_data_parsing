-- [SYNTHETIC] PC stand-in for the EDW schema CRMS (client master). Built into valid_env/edw/edw.sqlite (one file, all schemas — python -m validation.e2e.edw_standin), ATTACHed AS CRMS.
-- STRICT + CHECK(length) mirror NVARCHAR(n)/CHAR(1). Column names = the edw_masters mapping in config_examples/etl.example.json.

CREATE TABLE RM_MAS_CLIENT (
    CLIENT_CD        TEXT PRIMARY KEY CHECK (length(CLIENT_CD) BETWEEN 1 AND 20),
    CLIENT_ENG_NM    TEXT NOT NULL CHECK (length(CLIENT_ENG_NM) <= 200),
    CLIENT_TYPE      TEXT CHECK (CLIENT_TYPE IS NULL OR length(CLIENT_TYPE) <= 20),
    COUNTRY_CD       TEXT CHECK (COUNTRY_CD IS NULL OR length(COUNTRY_CD) = 2),                 -- ISO 3166 alpha-2
    PARENT_CLIENT_CD TEXT CHECK (PARENT_CLIENT_CD IS NULL OR length(PARENT_CLIENT_CD) <= 20),
    STATUS           TEXT NOT NULL CHECK (STATUS IN ('Y', 'N')),                                -- CHAR(1) use flag
    ALIAS_NM         TEXT CHECK (ALIAS_NM IS NULL OR length(ALIAS_NM) <= 500)                    -- aliases, ';' separated
) STRICT;

CREATE TABLE RM_MAS_CLIENT_GENERAL (
    CLIENT_CD     TEXT PRIMARY KEY REFERENCES RM_MAS_CLIENT (CLIENT_CD) CHECK (length(CLIENT_CD) BETWEEN 1 AND 20),
    CLIENT_KOR_NM TEXT CHECK (CLIENT_KOR_NM IS NULL OR length(CLIENT_KOR_NM) <= 200),
    ABBR_NM       TEXT CHECK (ABBR_NM IS NULL OR length(ABBR_NM) <= 100),
    KOR_ABBR_NM   TEXT CHECK (KOR_ABBR_NM IS NULL OR length(KOR_ABBR_NM) <= 100)
) STRICT;

-- seed rows (4 client-projects: Pfizar P2026014, AstraNova P2026033+P2026052, Korvexa P2026047)
INSERT INTO RM_MAS_CLIENT (CLIENT_CD, CLIENT_ENG_NM, CLIENT_TYPE, COUNTRY_CD, PARENT_CLIENT_CD, STATUS, ALIAS_NM) VALUES
    ('C9001', 'Pfizar Biopharma', 'Customer', 'KR', NULL, 'Y', 'PFZ;Pfizar Biopharma Inc.;Pfizar Inc.;파이자'),
    ('C9002', 'Pfizar Biopharma USA', 'Customer', 'US', 'C9001', 'Y', 'PFZ-US;Pfizar USA'),
    ('C9004', 'AstraNova Bio', 'Customer', 'US', NULL, 'Y', 'ANB;AstraNova Biotech;아스트라노바'),
    ('C9005', 'Korvexa Life Sciences', 'Prospect', 'JP', NULL, 'Y', 'KVX;Korvexa K.K.;코벡사');

INSERT INTO RM_MAS_CLIENT_GENERAL (CLIENT_CD, CLIENT_KOR_NM, ABBR_NM, KOR_ABBR_NM) VALUES
    ('C9001', '파이자바이오', 'PFZ', '파이자'),
    ('C9004', '아스트라노바바이오', 'ANB', '아스트라노바'),
    ('C9005', '코벡사라이프사이언스', 'KVX', '코벡사');

-- [SYNTHETIC] 11-02(pl-29) — 계약(프로젝트) 목록과 문서 표(운영 노트의 칸 이름, 값은 가짜). FileStorageMap_CRMS(ai.sql)로 이어짐.
CREATE TABLE RM_CM_PJTLIST (
    RM_CONTRACT_CODE TEXT PRIMARY KEY,
    SF_ACC_ID        TEXT,
    SF_ACC_NAME      TEXT,
    DIVISION         TEXT,
    RM_CONTRACT_NAME TEXT,
    INIT_DTTM        TEXT
) STRICT;
INSERT INTO RM_CM_PJTLIST SELECT rm_contract_code, NULL, 'Hanbit Synthetic Client ' || (docu_seq % 3), CASE docu_seq % 3 WHEN 0 THEN 'DS' WHEN 1 THEN 'DP' ELSE 'CD' END,
    'Synthetic Contract ' || rm_contract_code, '2025-01-15 09:00:00' FROM FileStorageMap_CRMS;
CREATE TABLE RM_CM_DOCU (
    RM_CONTRACT_CODE TEXT,
    GATE_CODE        TEXT,
    GATE_VERSION     TEXT,
    DOCU_SEQ         INTEGER,
    DOC_TYPE         TEXT,
    DOCU_NAME        TEXT,
    INIT_DTTM        TEXT
) STRICT;
INSERT INTO RM_CM_DOCU SELECT rm_contract_code, gate_code, gate_version, docu_seq, 'DOC', NULL, '2025-01-20 10:00:00' FROM FileStorageMap_CRMS;
