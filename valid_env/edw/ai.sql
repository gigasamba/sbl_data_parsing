-- [SYNTHETIC] PC stand-in for the EDW schema AI (real EDW = SQL Server). Built into valid_env/edw/ai.sqlite by
-- dev_tools/test_tools/edw_sample.py; the connector ATTACHes that file AS AI, so AI.FileStorageMap resolves like T-SQL.
-- STRICT tables + CHECK(length) mirror the NVARCHAR(n)/BIGINT/INT/FLOAT types, so a bad value fails here as on the server.

-- AI.FileStorageMap — one row per stored source file (s3_key 1:1). Columns read by data_etl/tools/source.py
-- (id, content_version_id, s3_key, original_filename, file_size) and by doc_meta_map.json (source_system, sf_op_id, contract_id).
CREATE TABLE FileStorageMap (
    id                 INTEGER PRIMARY KEY,                                                    -- BIGINT IDENTITY
    content_id         TEXT    NOT NULL CHECK (length(content_id) <= 64),                     -- same content across versions (SV10)
    content_version_id INTEGER NOT NULL CHECK (content_version_id >= 1),                      -- BIGINT
    s3_key             TEXT    NOT NULL UNIQUE CHECK (length(s3_key) BETWEEN 1 AND 1024),     -- NVARCHAR(1024)
    source_system      TEXT    NOT NULL CHECK (length(source_system) <= 64),                  -- NVARCHAR(64)
    original_filename  TEXT    NOT NULL CHECK (length(original_filename) <= 512),             -- NVARCHAR(512)
    file_size          INTEGER NOT NULL CHECK (file_size >= 0),                               -- BIGINT
    sha256             TEXT    CHECK (sha256 IS NULL OR length(sha256) = 64),                 -- NVARCHAR(64)
    sf_op_id           TEXT    CHECK (sf_op_id IS NULL OR length(sf_op_id) = 18),             -- SFDC.Opportunity.Id (NCHAR(18))
    contract_id        TEXT    CHECK (contract_id IS NULL OR length(contract_id) <= 64),      -- NVARCHAR(64)
    created_at         TEXT    NOT NULL CHECK (created_at = strftime('%Y-%m-%d %H:%M:%S', created_at))   -- DATETIME2(0)
) STRICT;

-- AI.ParsingMeta — same columns and keys as deploy/data_etl/tools/parsing_meta_mssql.sql
-- (common_tools/handoff_contract.py PARSING_META_COLUMNS). Written by data_etl/publish_results.py (PM_DB_SQLITE).
CREATE TABLE ParsingMeta (
    parse_meta_id     INTEGER PRIMARY KEY AUTOINCREMENT,                                          -- BIGINT IDENTITY
    source_system     TEXT    CHECK (source_system IS NULL OR length(source_system) <= 64),
    source_key        TEXT    CHECK (source_key IS NULL OR length(source_key) <= 1024),
    source_uri        TEXT    CHECK (source_uri IS NULL OR length(source_uri) <= 2048),
    original_filename TEXT    CHECK (original_filename IS NULL OR length(original_filename) <= 512),
    file_format       TEXT    CHECK (file_format IS NULL OR length(file_format) <= 32),
    file_size         INTEGER,                                                                    -- BIGINT
    sha256            TEXT    CHECK (sha256 IS NULL OR length(sha256) <= 64),
    rep_bucket        TEXT    CHECK (rep_bucket IS NULL OR length(rep_bucket) <= 256),
    rep_key           TEXT    CHECK (rep_key IS NULL OR length(rep_key) <= 2048),
    rep_etag          TEXT    CHECK (rep_etag IS NULL OR length(rep_etag) <= 128),
    parse_status      TEXT    CHECK (parse_status IS NULL OR length(parse_status) <= 32),
    status_reason     TEXT    CHECK (status_reason IS NULL OR length(status_reason) <= 2000),
    rep_engine        TEXT    CHECK (rep_engine IS NULL OR length(rep_engine) <= 128),
    rep_acc           REAL,                                                                       -- FLOAT
    page_count        INTEGER CHECK (page_count IS NULL OR page_count BETWEEN -2147483648 AND 2147483647),   -- INT
    doc_key           TEXT    NOT NULL CHECK (length(doc_key) <= 64),
    parse_date        TEXT    CHECK (parse_date IS NULL OR length(parse_date) <= 32),
    pipeline_version  TEXT    CHECK (pipeline_version IS NULL OR length(pipeline_version) <= 64),
    status            TEXT    CHECK (status IS NULL OR status IN ('active', 'changed', 'deleted')),
    status_at         TEXT    CHECK (status_at IS NULL OR length(status_at) <= 32),
    engines_used      TEXT,                                                                       -- NVARCHAR(MAX), JSON array
    engines_summary   TEXT    CHECK (engines_summary IS NULL OR length(engines_summary) <= 512),
    parsed_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))             -- DATETIME2(0) DEFAULT SYSUTCDATETIME()
) STRICT;
CREATE UNIQUE INDEX UQ_ParsingMeta_key    ON ParsingMeta (source_system, source_key, parse_date) WHERE source_key IS NOT NULL;
CREATE UNIQUE INDEX UQ_ParsingMeta_dockey ON ParsingMeta (doc_key, parse_date) WHERE source_key IS NULL;
CREATE INDEX IX_ParsingMeta_doc_key ON ParsingMeta (doc_key);

-- seed rows (FileStorageMap only; ParsingMeta starts empty — publish writes it)

INSERT INTO FileStorageMap (id, content_id, s3_key, source_system, original_filename, content_version_id, file_size, sha256, sf_op_id, contract_id, created_at) VALUES
    (1, 'd2139fbd2cbe40341dbe83966c9ad767066ad1333806a21d45295223262b0660', 'CRMS/19f7e8be-02be-5b8a-8918-64496e955191/normal_control.pdf', 'CRMS', 'normal_control.pdf', 1, 918, 'd2139fbd2cbe40341dbe83966c9ad767066ad1333806a21d45295223262b0660', NULL, NULL, '2026-10-15 09:00:00'),
    (2, 'ebf47eee5071b959b75ac083976bc5b6437d51803bb9d29a71e905e3fa2c1844', 'CRMS/1ca833b4-daaa-563a-8a20-ad59728e81c7/no_charset_mail.eml', 'CRMS', 'no_charset_mail.eml', 1, 275, 'ebf47eee5071b959b75ac083976bc5b6437d51803bb9d29a71e905e3fa2c1844', NULL, NULL, '2026-10-15 09:00:00'),
    (3, '21c6661ba7346ab1a86ecaed2411de9ceecdce3f2b27ef9da5704f3dd2d77e99', 'CRMS/1e573cf6-589a-59b8-bbdd-3bc47c800339/symbol_font_pua.docx', 'CRMS', 'symbol_font_pua.docx', 1, 37319, '21c6661ba7346ab1a86ecaed2411de9ceecdce3f2b27ef9da5704f3dd2d77e99', NULL, NULL, '2026-10-15 09:00:00'),
    (4, 'a1f38846c018e6e6d5638b2091538374ef739c4f29b6d14228c9c3a9945a3d4d', 'CRMS/243f7ef5-e309-5808-b855-54e71426ad4e/hidden_textbox.docx', 'CRMS', 'hidden_textbox.docx', 1, 38771, 'a1f38846c018e6e6d5638b2091538374ef739c4f29b6d14228c9c3a9945a3d4d', NULL, NULL, '2026-10-15 09:00:00'),
    (5, '08d7cc13b7d05f507dd4ddfa63bd2768424c1f55fad6e5c080494ed78bbfcda7', 'CRMS/2569a3ca-c945-5881-9eea-bae296e47120/qp_euckr_mail.eml', 'CRMS', 'qp_euckr_mail.eml', 1, 461, '08d7cc13b7d05f507dd4ddfa63bd2768424c1f55fad6e5c080494ed78bbfcda7', NULL, NULL, '2026-10-15 09:00:00'),
    (6, '7417dc5103260eef7727ea541597625eabbca8ac7e9cc952112cede1268fd1b2', 'CRMS/6434280c-3427-5cac-8ce4-1f413ccce09b/ho_symbol_font_pua.docx', 'CRMS', 'ho_symbol_font_pua.docx', 1, 37315, '7417dc5103260eef7727ea541597625eabbca8ac7e9cc952112cede1268fd1b2', NULL, NULL, '2026-10-15 09:00:00'),
    (7, '7a575acce4dad1fcfaf15ef74d6fd1d0e291dec878c9e82fd9707db060e642c8', 'CRMS/6b86ea92-cf9a-5ba7-9381-cf228e57bdb1/encrypted_ole.doc', 'CRMS', 'encrypted_ole.doc', 1, 2048, '7a575acce4dad1fcfaf15ef74d6fd1d0e291dec878c9e82fd9707db060e642c8', NULL, NULL, '2026-10-15 09:00:00'),
    (8, 'd9ad7c45e9fef7023fa83219d28c30965522fa2738916c2615e0a25cccd834fd', 'CRMS/734fac46-4194-5bbd-addc-2a28cfce78ce/drm_protected.docx', 'CRMS', 'drm_protected.docx', 1, 125, 'd9ad7c45e9fef7023fa83219d28c30965522fa2738916c2615e0a25cccd834fd', NULL, NULL, '2026-10-15 09:00:00'),
    (9, '687f8fe3cfc04079c454fb66d967592bda3595bdb82b5664d18ddf791cf5d75e', 'CRMS/73ab2382-c016-58d4-9882-9776680bd177/scan_no_text.pdf', 'CRMS', 'scan_no_text.pdf', 1, 71849, '687f8fe3cfc04079c454fb66d967592bda3595bdb82b5664d18ddf791cf5d75e', NULL, NULL, '2026-10-15 09:00:00'),
    (10, '19e1ae7a2e05fa2b5458e7de41cddcde23122d57d24c01284155311156887000', 'CRMS/80cad82c-deb0-53ab-853e-1687683d4836/ho_merged_cells_tbl.docx', 'CRMS', 'ho_merged_cells_tbl.docx', 1, 37234, '19e1ae7a2e05fa2b5458e7de41cddcde23122d57d24c01284155311156887000', NULL, NULL, '2026-10-15 09:00:00'),
    (11, 'bdab222b2dd1593e1020f4e689f06ad5b6bf6ae4c6ef6cde9da308ff2b8e67f2', 'CRMS/95194ebe-b50a-52f8-a457-3e4a07174053/text_only_control.pdf', 'CRMS', 'text_only_control.pdf', 1, 75902, 'bdab222b2dd1593e1020f4e689f06ad5b6bf6ae4c6ef6cde9da308ff2b8e67f2', NULL, NULL, '2026-10-15 09:00:00'),
    (12, '172bbfa21562955911f21826a90605c4f56be5be8d89fbd7e1c7781e432ef770', 'CRMS/9d9a56af-8105-5ba8-8db2-9f5ef122d4eb/merged_cells_tbl.docx', 'CRMS', 'merged_cells_tbl.docx', 1, 37243, '172bbfa21562955911f21826a90605c4f56be5be8d89fbd7e1c7781e432ef770', NULL, NULL, '2026-10-15 09:00:00'),
    (13, '1e18addf37aa76b587dfe446395d5148f3b98fb36c481c1acac1ff0fcd3f2f8c', 'CRMS/c04c73a5-3f1d-59fe-b75b-948a1d87c858/corrupt_truncated.pdf', 'CRMS', 'corrupt_truncated.pdf', 1, 500, '1e18addf37aa76b587dfe446395d5148f3b98fb36c481c1acac1ff0fcd3f2f8c', NULL, NULL, '2026-10-15 09:00:00'),
    (14, '5f58526c1c976a63963efd6a4916417af3d1df324db60c57694e77cb98d9b540', 'CRMS/c63782bc-1d59-5cca-a199-b330a4f1f112/ksc5601_ext_mail.eml', 'CRMS', 'ksc5601_ext_mail.eml', 1, 318, '5f58526c1c976a63963efd6a4916417af3d1df324db60c57694e77cb98d9b540', NULL, NULL, '2026-10-15 09:00:00'),
    (15, 'c39037da793a7ae1cadf5732e0391d071d51d89e8a5bfb30b82a80c1d3764925', 'CRMS/d9170a4b-5a89-560f-8041-5c67e5a12ce0/cp949_mail.eml', 'CRMS', 'cp949_mail.eml', 1, 279, 'c39037da793a7ae1cadf5732e0391d071d51d89e8a5bfb30b82a80c1d3764925', NULL, NULL, '2026-10-15 09:00:00'),
    (16, 'a9a3611c44440c229108486761cf6b7baa64b9c01de542e913ae19d3ef77daa7', 'CRMS/de5289a4-a5b4-5dec-911a-d275e49d6500/mixed_scan_text.pdf', 'CRMS', 'mixed_scan_text.pdf', 1, 107848, 'a9a3611c44440c229108486761cf6b7baa64b9c01de542e913ae19d3ef77daa7', NULL, NULL, '2026-10-15 09:00:00'),
    (17, '677969f10f40c6b7d714cf1d579ef69ca63bbae4e606164c51e0404854fe932d', 'CRMS/e2ac272a-9ad3-54c8-837a-f4392abd493b/merged_visual_tbl.pdf', 'CRMS', 'merged_visual_tbl.pdf', 1, 79196, '677969f10f40c6b7d714cf1d579ef69ca63bbae4e606164c51e0404854fe932d', NULL, NULL, '2026-10-15 09:00:00'),
    (18, 'c295f09ee5f6744384885b7da4078b7f8df040252e9cf55c8eff777469a2331d', 'CRMS/e84d6a6f-d90a-5ae9-9617-3956f6a23a3e/b64_attach_mail.eml', 'CRMS', 'b64_attach_mail.eml', 1, 674, 'c295f09ee5f6744384885b7da4078b7f8df040252e9cf55c8eff777469a2331d', NULL, NULL, '2026-10-15 09:00:00'),
    (19, '76762af2b7c92f062149cf2ead21b126108bf0affb04a83b17a0d62e2039ad7a', 'CRMS/f8b466f8-a7d4-559a-afaa-aaece7a8e27b/garbled_text_layer.pdf', 'CRMS', 'garbled_text_layer.pdf', 1, 102136, '76762af2b7c92f062149cf2ead21b126108bf0affb04a83b17a0d62e2039ad7a', NULL, NULL, '2026-10-15 09:00:00'),
    (20, '8c3b5e3c1ff8de4a5bc22352a0f9b221df7d207d6e8c97aaf4fc05d2cd741e29', 'CRMS/f92c6ddb-2aae-5b43-ae62-30dbd022dbe6/ho_hidden_textbox.docx', 'CRMS', 'ho_hidden_textbox.docx', 1, 38786, '8c3b5e3c1ff8de4a5bc22352a0f9b221df7d207d6e8c97aaf4fc05d2cd741e29', NULL, NULL, '2026-10-15 09:00:00'),
    (21, '91c85ece453b4f4f75f62f55f587156d743bbd3a98beaf98a4f64af55d230d31', 'CRMS/fc06205e-ce08-5fc6-9de1-c3c29ea1bba4/archive_unsupported.zip', 'CRMS', 'archive_unsupported.zip', 1, 158, '91c85ece453b4f4f75f62f55f587156d743bbd3a98beaf98a4f64af55d230d31', NULL, NULL, '2026-10-15 09:00:00'),
    (22, '5f3598c412e4c4e75648abdc485bec5b0aaac3cba1255f4126c969774a33bc4b', 'SFDC/082a76fa-cb64-4225-8a00-b9deb0188233/astra_qa_thread_en.eml', 'SFDC', 'astra_qa_thread_en.eml', 1, 2806, '5f3598c412e4c4e75648abdc485bec5b0aaac3cba1255f4126c969774a33bc4b', 'OPP202603300000000', NULL, '2026-10-15 09:00:00'),
    (23, 'f3d1f8067a62934dd233c3ce35555685915938d714d2d3abc66d5ea097318028', 'SFDC/17ae1841-d031-48b5-85b2-2df6058b5857/kvx_rfp_main.pdf', 'SFDC', 'kvx_rfp_main.pdf', 1, 448556, 'f3d1f8067a62934dd233c3ce35555685915938d714d2d3abc66d5ea097318028', 'OPP202604700000000', NULL, '2026-10-15 09:00:00'),
    (24, '1f8e3a3fd8f65d87e46f7d99ddaea9124be28b4c3026f7c3268b8fca49846020', 'SFDC/1f450a85-3272-42a9-8664-893cff5bb22c/kvx_scan_copy.pdf', 'SFDC', 'kvx_scan_copy.pdf', 1, 313690, '1f8e3a3fd8f65d87e46f7d99ddaea9124be28b4c3026f7c3268b8fca49846020', 'OPP202604700000000', NULL, '2026-10-15 09:00:00'),
    (25, 'a5fb5c2dd6ce491949f0be196f6a2803e7c37f799d469326ad9260a623c4fb46', 'SFDC/23213095-ea73-4db0-8107-f03a28ff3b78/kvx_internal_note.txt', 'SFDC', 'kvx_internal_note.txt', 1, 2004, 'a5fb5c2dd6ce491949f0be196f6a2803e7c37f799d469326ad9260a623c4fb46', 'OPP202604700000000', NULL, '2026-10-15 09:00:00'),
    (26, 'cde44b5ceb255d3d84fd915130bf717760d00ab822a11a1ff88f048418a283d5', 'SFDC/64960b49-fe52-4277-8c2e-2c3969c66bf6/astra_rfi_form.xlsx', 'SFDC', 'astra_rfi_form.xlsx', 1, 11001, 'cde44b5ceb255d3d84fd915130bf717760d00ab822a11a1ff88f048418a283d5', 'OPP202605200000000', NULL, '2026-10-15 09:00:00'),
    (27, 'bae7ac48e0765e4c9aba181071a9c3484547bdcab8cb0edbb15f318ef27a2dc5', 'SFDC/64d6f4fb-ac54-4323-82c3-4f679cb6f419/pfz_fwd_mail_ko.eml', 'SFDC', 'pfz_fwd_mail_ko.eml', 1, 4607, 'bae7ac48e0765e4c9aba181071a9c3484547bdcab8cb0edbb15f318ef27a2dc5', 'OPP202601400000000', NULL, '2026-10-15 09:00:00'),
    (28, '820258dae83577a85a3f671348db364a2af3bff987738bb1e49c3872559fe4f1', 'SFDC/6dd6c33f-257c-4c9f-8729-a746849499b7/pfz_chat_capture.png', 'SFDC', 'pfz_chat_capture.png', 1, 51307, '820258dae83577a85a3f671348db364a2af3bff987738bb1e49c3872559fe4f1', 'OPP202601400000000', NULL, '2026-10-15 09:00:00'),
    (29, '981c2750c5140217319d6116b38968f1966ba1b7fb087a78f51b102bf547c470', 'SFDC/72048b36-1ef9-479b-8f0d-6c7ad29b61b9/pfz_qa_thread_en.eml', 'SFDC', 'pfz_qa_thread_en.eml', 1, 4283, '981c2750c5140217319d6116b38968f1966ba1b7fb087a78f51b102bf547c470', 'OPP202601400000000', NULL, '2026-10-15 09:00:00'),
    (30, 'fc9ff03457d35fe400d04c4b7d5bc2febaeef44a7f4f67b964d93f42e5b2d9ec', 'SFDC/770f2b9c-691f-4d38-85b7-18fd0462bc05/astra_rfp_main.docx', 'SFDC', 'astra_rfp_main.docx', 1, 213168, 'fc9ff03457d35fe400d04c4b7d5bc2febaeef44a7f4f67b964d93f42e5b2d9ec', 'OPP202603300000000', NULL, '2026-10-15 09:00:00'),
    (31, '536cca25f785386a39d1f4a689d9888c729200c1cf30973d26bccfb89b9e16e5', 'SFDC/a274ce2c-45f7-4b63-8760-66bc552004eb/pfz_rfp_main.docx', 'SFDC', 'pfz_rfp_main.docx', 1, 215636, '536cca25f785386a39d1f4a689d9888c729200c1cf30973d26bccfb89b9e16e5', 'OPP202601400000000', NULL, '2026-10-15 09:00:00'),
    (32, 'ca368c8c3088e98f437c17e27ac5ded7291b3c660d99c7ba16aad73a295c2a56', 'SFDC/f55fa16f-bde6-4cab-831b-878c96c079f9/kvx_qa_thread_en.eml', 'SFDC', 'kvx_qa_thread_en.eml', 1, 2706, 'ca368c8c3088e98f437c17e27ac5ded7291b3c660d99c7ba16aad73a295c2a56', 'OPP202604700000000', NULL, '2026-10-15 09:00:00'),
    (33, '634563b249456f64babfa8a7a60bfcb472a56f6caf6a9082630b991cd4699c6a', 'SFDC/f685a4f7-d9fc-4ddf-8b66-53b34913d824/astra_chat_capture.png', 'SFDC', 'astra_chat_capture.png', 1, 71087, '634563b249456f64babfa8a7a60bfcb472a56f6caf6a9082630b991cd4699c6a', 'OPP202603300000000', NULL, '2026-10-15 09:00:00');
