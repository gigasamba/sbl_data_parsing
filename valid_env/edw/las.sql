-- [SYNTHETIC] PC stand-in for the EDW schema LAS (product/service/division masters — real tables TBD on the server).
-- Built into valid_env/edw/edw.sqlite (one file, all schemas — python -m validation.e2e.edw_standin), ATTACHed AS LAS. Column names = the edw_masters mapping in config_examples/etl.example.json.

CREATE TABLE DIVISION_MAS (
    DIV_CD        TEXT PRIMARY KEY CHECK (length(DIV_CD) BETWEEN 1 AND 20),
    DIV_NM        TEXT NOT NULL CHECK (length(DIV_NM) <= 200),
    DIV_KOR_NM    TEXT CHECK (DIV_KOR_NM IS NULL OR length(DIV_KOR_NM) <= 200),
    DIV_TYPE      TEXT CHECK (DIV_TYPE IS NULL OR length(DIV_TYPE) <= 50),
    PARENT_DIV_CD TEXT CHECK (PARENT_DIV_CD IS NULL OR length(PARENT_DIV_CD) <= 20),
    STATUS        TEXT NOT NULL CHECK (STATUS IN ('Y', 'N')),
    DIV_ABBR      TEXT CHECK (DIV_ABBR IS NULL OR length(DIV_ABBR) <= 100)
) STRICT;

CREATE TABLE PROD_MAS (
    PROD_CD     TEXT PRIMARY KEY CHECK (length(PROD_CD) BETWEEN 1 AND 20),
    PROD_NM     TEXT NOT NULL CHECK (length(PROD_NM) <= 200),
    PROD_KOR_NM TEXT CHECK (PROD_KOR_NM IS NULL OR length(PROD_KOR_NM) <= 200),
    MODALITY    TEXT CHECK (MODALITY IS NULL OR length(MODALITY) <= 50),
    DIV_CD      TEXT REFERENCES DIVISION_MAS (DIV_CD),
    STATUS      TEXT NOT NULL CHECK (STATUS IN ('Y', 'N')),
    PROD_ABBR   TEXT CHECK (PROD_ABBR IS NULL OR length(PROD_ABBR) <= 100)
) STRICT;

CREATE TABLE SERVICE_MAS (
    SVC_CD     TEXT PRIMARY KEY CHECK (length(SVC_CD) BETWEEN 1 AND 20),
    SVC_NM     TEXT NOT NULL CHECK (length(SVC_NM) <= 200),
    SVC_KOR_NM TEXT CHECK (SVC_KOR_NM IS NULL OR length(SVC_KOR_NM) <= 200),
    SVC_TYPE   TEXT CHECK (SVC_TYPE IS NULL OR length(SVC_TYPE) <= 50),
    DIV_CD     TEXT REFERENCES DIVISION_MAS (DIV_CD),
    STATUS     TEXT NOT NULL CHECK (STATUS IN ('Y', 'N')),
    SVC_ABBR   TEXT CHECK (SVC_ABBR IS NULL OR length(SVC_ABBR) <= 100)
) STRICT;

-- seed rows (fits the style of valid_env/config_examples/division_master.example.csv, prod_master.example.csv,
-- service_master.example.csv — populated with the rfp clients' CDMO product/service vocabulary)
INSERT INTO DIVISION_MAS (DIV_CD, DIV_NM, DIV_KOR_NM, DIV_TYPE, PARENT_DIV_CD, STATUS, DIV_ABBR) VALUES
    ('D01', 'Biologics CDMO', '바이오로직스 CDMO', 'business_unit', NULL, 'Y', 'CDMO'),
    ('D02', 'Quality & Regulatory', '품질규제본부', 'business_unit', NULL, 'Y', 'QA/RA');

-- DS2 dropped the Merko client/project entirely — no MRK-SYN-BSA-07 product row (removed everywhere, incl. here)
INSERT INTO PROD_MAS (PROD_CD, PROD_NM, PROD_KOR_NM, MODALITY, DIV_CD, STATUS, PROD_ABBR) VALUES
    ('P001', 'PFZ-SYN-MAB-11', '파이자 항체-11', 'mAb', 'D01', 'Y', 'PFZ MAB11'),
    ('P003', 'ANB-SYN-VAC-03', '아스트라노바 백신-03', 'vaccine', 'D01', 'Y', 'ANB VAC03'),
    ('P004', 'ANB-SYN-RSV-07', '아스트라노바 백신-07', 'vaccine', 'D01', 'Y', 'ANB RSV07'),
    ('P005', 'KVX-SYN-ADC-02', '코벡사 ADC-02', 'ADC', 'D01', 'Y', 'KVX ADC02');

INSERT INTO SERVICE_MAS (SVC_CD, SVC_NM, SVC_KOR_NM, SVC_TYPE, DIV_CD, STATUS, SVC_ABBR) VALUES
    ('S001', 'Drug Substance Manufacturing', '원료의약품 생산', 'process', 'D01', 'Y', 'DS Manufacturing;DS'),
    ('S002', 'Drug Product Fill-Finish', '완제의약품 충전', 'process', 'D01', 'Y', 'DP Fill-Finish;DP'),
    ('S003', 'Process Development', '공정개발', 'process', 'D01', 'Y', 'CDO'),
    ('S004', 'Commercial Manufacturing', '상업생산', 'process', 'D01', 'Y', 'CMO');

-- [SYNTHETIC] 11-02(pl-29) — 계약·파일 표(운영 노트의 칸 이름, 값은 가짜). 상대사(PartnerCorpName)는 운영처럼 비워 둠(G2).
CREATE TABLE Contract (
    ContractID      INTEGER PRIMARY KEY,
    ManageNo        TEXT,
    IsActive        INTEGER,
    ContractDate    TEXT,
    PartnerID       TEXT,
    PartnerCorpName TEXT
) STRICT;
INSERT INTO Contract (ManageNo, IsActive, ContractDate, PartnerID, PartnerCorpName) SELECT manage_no, 1, '2025-03-01', NULL, NULL FROM FileStorageMap_LAS;
CREATE TABLE FileManager (
    FileID     TEXT PRIMARY KEY,
    CreateDate TEXT
) STRICT;
INSERT INTO FileManager SELECT las_file_id, '2025-03-02 11:00:00' FROM FileStorageMap_LAS;
-- [SYNTHETIC] 11-02(pl-33) — 분류 힌트 품의 제목(운영 노트의 칸 이름). 대역에는 LAS 문서가 아직 없어 행이 없다(갈래 시험은 tests/server/pipeline/test_edw_meta.py test_hints).
ALTER TABLE Contract ADD COLUMN ApprovalName TEXT;
