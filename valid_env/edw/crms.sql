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

-- seed rows (CRMS clients = valid_env/eval_sets/rfp/{client_master,client_roster}.csv exactly — DS2 dropped Merko,
-- 4 client-project folders remain: Pfizar P2026014, AstraNova P2026033+P2026052, Korvexa P2026047)
INSERT INTO RM_MAS_CLIENT (CLIENT_CD, CLIENT_ENG_NM, CLIENT_TYPE, COUNTRY_CD, PARENT_CLIENT_CD, STATUS, ALIAS_NM) VALUES
    ('C9001', 'Pfizar Biopharma', 'Customer', 'KR', NULL, 'Y', 'PFZ;Pfizar Biopharma Inc.;Pfizar Inc.;파이자'),
    ('C9002', 'Pfizar Biopharma USA', 'Customer', 'US', 'C9001', 'Y', 'PFZ-US;Pfizar USA'),
    ('C9004', 'AstraNova Bio', 'Customer', 'US', NULL, 'Y', 'ANB;AstraNova Biotech;아스트라노바'),
    ('C9005', 'Korvexa Life Sciences', 'Prospect', 'JP', NULL, 'Y', 'KVX;Korvexa K.K.;코벡사');

INSERT INTO RM_MAS_CLIENT_GENERAL (CLIENT_CD, CLIENT_KOR_NM, ABBR_NM, KOR_ABBR_NM) VALUES
    ('C9001', '파이자바이오', 'PFZ', '파이자'),
    ('C9004', '아스트라노바바이오', 'ANB', '아스트라노바'),
    ('C9005', '코벡사라이프사이언스', 'KVX', '코벡사');
