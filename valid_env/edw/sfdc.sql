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

-- seed rows (Account links to CRMS via CRMS_Client_Code__c; one Opportunity per client-project, Project_Code__c = the
-- P-number in the valid_env/eval_sets/rfp folder name — DS2 dropped Merko, 4 client-projects remain)
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
