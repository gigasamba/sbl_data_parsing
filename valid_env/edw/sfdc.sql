-- [SYNTHETIC] PC stand-in for the EDW schema SFDC (Salesforce copy). Built into valid_env/edw/edw.sqlite (one file, all schemas — python -m validation.e2e.edw_standin), ATTACHed AS SFDC.
-- STRICT + CHECK(length) mirror NVARCHAR(n)/NCHAR(18)/BIT/DATE/DECIMAL. Fictional data only.

CREATE TABLE Account (
    Id                  TEXT    PRIMARY KEY CHECK (length(Id) = 18),                                        -- NCHAR(18)
    Name                TEXT    NOT NULL CHECK (length(Name) <= 255),
    Account_Nickname__c TEXT    CHECK (Account_Nickname__c IS NULL OR length(Account_Nickname__c) <= 255),  -- aliases, ';' separated
    CRMS_Client_Code__c TEXT    CHECK (CRMS_Client_Code__c IS NULL OR length(CRMS_Client_Code__c) <= 20),   -- -> CRMS.RM_MAS_CLIENT.CLIENT_CD
    Type                TEXT    CHECK (Type IS NULL OR length(Type) <= 255),
    BillingCountry      TEXT    CHECK (BillingCountry IS NULL OR length(BillingCountry) <= 80),
    IsDeleted           INTEGER NOT NULL DEFAULT 0 CHECK (IsDeleted IN (0, 1))                               -- BIT
) STRICT;

CREATE TABLE Opportunity (
    Id                TEXT    PRIMARY KEY CHECK (length(Id) = 18),
    Name              TEXT    NOT NULL CHECK (length(Name) <= 120),
    AccountId         TEXT    NOT NULL REFERENCES Account (Id) CHECK (length(AccountId) = 18),
    Project_Code__c   TEXT    CHECK (Project_Code__c IS NULL OR length(Project_Code__c) <= 20),   -- e.g. P2026033 (matches the rfp folder)
    Service_Type__c   TEXT    CHECK (Service_Type__c IS NULL OR length(Service_Type__c) <= 100),
    Division__c       TEXT    CHECK (Division__c IS NULL OR length(Division__c) <= 100),
    Product_Name__c   TEXT    CHECK (Product_Name__c IS NULL OR length(Product_Name__c) <= 255),
    StageName         TEXT    NOT NULL CHECK (length(StageName) <= 255),
    CloseDate         TEXT    NOT NULL CHECK (CloseDate = date(CloseDate)),                        -- DATE 'YYYY-MM-DD'
    Amount            REAL    CHECK (Amount IS NULL OR Amount >= 0),                               -- DECIMAL(18,2)
    IsDeleted         INTEGER NOT NULL DEFAULT 0 CHECK (IsDeleted IN (0, 1))
) STRICT;

-- seed rows (Account links to CRMS via CRMS_Client_Code__c; one Opportunity per client-project, Project_Code__c = its P-number)
INSERT INTO Account (Id, Name, Account_Nickname__c, CRMS_Client_Code__c, Type, BillingCountry, IsDeleted) VALUES
    ('001900100000000000', 'Pfizar Biopharma', 'Pfizar Biopharma Inc.;Pfizar Inc.;PFZ', 'C9001', 'Customer', 'KR', 0),
    ('001900200000000000', 'Pfizar Biopharma USA', 'Pfizar USA;PFZ-US', 'C9002', 'Customer', 'US', 0),
    ('001900400000000000', 'AstraNova Bio', 'AstraNova Biotech;ANB', 'C9004', 'Customer', 'US', 0),
    ('001900500000000000', 'Korvexa Life Sciences', 'Korvexa K.K.;KVX', 'C9005', 'Prospect', 'JP', 0);

INSERT INTO Opportunity (Id, Name, AccountId, Project_Code__c, Service_Type__c, Division__c, Product_Name__c, StageName, CloseDate, Amount, IsDeleted) VALUES
    ('OPP202601400000000', 'Pfizar Biopharma RFP P2026014', '001900100000000000', 'P2026014', 'CMO', 'DP', 'PFZ-SYN-MAB-11', 'Proposal', '2026-12-12', 2000000.00, 0),
    ('OPP202603300000000', 'AstraNova Bio RFP P2026033', '001900400000000000', 'P2026033', 'CDO', 'DS', 'ANB-SYN-VAC-03', 'Proposal', '2026-12-01', 1500000.00, 0),
    ('OPP202605200000000', 'AstraNova Bio RFI P2026052', '001900400000000000', 'P2026052', 'CDO', 'DP', 'ANB-SYN-RSV-07', 'Proposal', '2027-01-15', 500000.00, 0),
    ('OPP202604700000000', 'Korvexa Life Sciences RFP P2026047', '001900500000000000', 'P2026047', 'CMO', 'DS', 'KVX-SYN-ADC-02', 'Proposal', '2026-12-15', 2200000.00, 0);

-- [SYNTHETIC] 11-02(pl-29) — 파일 → 영업 기회 사슬 표(운영 노트의 칸 이름, 값은 가짜). 첫 SFDC 파일들은 기회 직접(006)·Task(00T)·Event(00U)·
-- Quote(0Q0 — 운영 EDW 복사본에는 아직 없는 표, 사용자 11-02: 운영처럼 EDW 표로 재현)·계정 직접(001)으로 차례로 이어 둔다.
ALTER TABLE Opportunity ADD COLUMN Record_Type__c TEXT;
ALTER TABLE Opportunity ADD COLUMN X1st_Contract_Execution_Date__c TEXT;
UPDATE Opportunity SET Record_Type__c = Service_Type__c, X1st_Contract_Execution_Date__c = CloseDate;
CREATE TABLE ContentVersion (
    Id                TEXT PRIMARY KEY,
    ContentDocumentId TEXT,
    CreatedDate       TEXT
) STRICT;
UPDATE FileStorageMap SET content_version_id = id WHERE source_system = 'SFDC';  -- 파일마다 다른 판 id(가짜 — 운영은 SFDC ContentVersion Id)
INSERT INTO ContentVersion SELECT CAST(content_version_id AS TEXT), '069' || id, created_at FROM FileStorageMap WHERE source_system = 'SFDC';
UPDATE Opportunity SET Id = '006' || substr(Id, 4);  -- 운영 SFDC id처럼 접두 006(영업 기회) — 사슬이 접두로 길을 고름
UPDATE FileStorageMap SET sf_op_id = '006' || substr(sf_op_id, 4) WHERE sf_op_id LIKE 'OPP%';
CREATE TABLE ContentDocumentLink (
    ContentDocumentId TEXT,
    LinkedEntityId    TEXT,
    IsDeleted         INTEGER NOT NULL DEFAULT 0
) STRICT;
CREATE TABLE Task (Id TEXT PRIMARY KEY, WhatId TEXT) STRICT;
CREATE TABLE Event (Id TEXT PRIMARY KEY, WhatId TEXT) STRICT;
CREATE TABLE Quote (Id TEXT PRIMARY KEY, OpportunityId TEXT, AccountId TEXT) STRICT;
INSERT INTO Task VALUES ('00T000000000000001', '006202603300000000');
INSERT INTO Event VALUES ('00U000000000000001', '006202605200000000');
INSERT INTO Quote VALUES ('0Q0000000000000001', '006202604700000000', '001900500000000000');
INSERT INTO ContentDocumentLink (ContentDocumentId, LinkedEntityId)
SELECT cd, CASE rn % 5 WHEN 0 THEN '006202601400000000' WHEN 1 THEN '00T000000000000001' WHEN 2 THEN '00U000000000000001'
                       WHEN 3 THEN '0Q0000000000000001' ELSE '001900200000000000' END
FROM (SELECT ContentDocumentId AS cd, ROW_NUMBER() OVER (ORDER BY ContentDocumentId) AS rn FROM ContentVersion);

-- [SYNTHETIC] 11-02(pl-33) — 분류 힌트 칸(운영 노트의 칸 이름, 값은 가짜). 힌트 갈래마다 문서 하나 이상:
-- 제목 있음·비어 있음(파일 이름으로) · 연결 개체 Opportunity(단계·Real_RFP__c·RFP 기간)·Task(방향 있음·없음)·Event·Quote·Account·
-- Contract·IF_Log__c(a14)·모르는 접두(a99 → Unknown:a99) · User + Task(User는 건너뜀) · User만(user_only) · 연결 없음(unlinked).
ALTER TABLE ContentVersion ADD COLUMN Title TEXT;
UPDATE ContentVersion SET Title = (SELECT replace(substr(f.original_filename, 1, instr(f.original_filename, '.') - 1), '_', ' ') FROM FileStorageMap f WHERE CAST(f.content_version_id AS TEXT) = ContentVersion.Id);
UPDATE ContentVersion SET Title = NULL WHERE ContentDocumentId = '06926';
ALTER TABLE Task ADD COLUMN Subject TEXT;
ALTER TABLE Task ADD COLUMN Sent_Received__c TEXT;
ALTER TABLE Event ADD COLUMN Subject TEXT;
ALTER TABLE Event ADD COLUMN Sent_Received__c TEXT;
UPDATE Task SET Subject = 'RE: RFP package and Q&A for ANB-SYN-VAC-03', Sent_Received__c = 'Received';
UPDATE Event SET Subject = 'Proposal review call with AstraNova', Sent_Received__c = 'Sent';
INSERT INTO Task VALUES ('00T000000000000002', '006202603300000000', 'Internal follow-up', NULL);
ALTER TABLE Opportunity ADD COLUMN Real_RFP__c INTEGER;
ALTER TABLE Opportunity ADD COLUMN RFP_Received_Start_Date__c TEXT;
ALTER TABLE Opportunity ADD COLUMN RFP_Received_End_Date__c TEXT;
UPDATE Opportunity SET Real_RFP__c = 1, RFP_Received_Start_Date__c = '2026-03-02', RFP_Received_End_Date__c = '2026-03-20' WHERE Id = '006202601400000000';
UPDATE Opportunity SET Real_RFP__c = 0 WHERE Id <> '006202601400000000';
UPDATE ContentDocumentLink SET LinkedEntityId = '00T000000000000002' WHERE ContentDocumentId = '06932';
UPDATE ContentDocumentLink SET LinkedEntityId = 'a14000000000000001' WHERE ContentDocumentId = '06938';
UPDATE ContentDocumentLink SET LinkedEntityId = 'a99000000000000001' WHERE ContentDocumentId = '06939';
DELETE FROM ContentDocumentLink WHERE ContentDocumentId = '06940';
UPDATE ContentDocumentLink SET LinkedEntityId = '005000000000000001' WHERE ContentDocumentId = '06941';
INSERT INTO ContentDocumentLink (ContentDocumentId, LinkedEntityId) VALUES ('06942', '005000000000000001');
UPDATE ContentDocumentLink SET LinkedEntityId = '800000000000000001' WHERE ContentDocumentId = '06943';
