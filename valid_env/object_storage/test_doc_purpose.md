# PC 시험 문서 목적 안내

`valid_env/object_storage/`는 서버 Object Storage 버킷을 PC에서 흉내 낸 폴더다. 문서 1건 = `<원천>/<uuid>/<파일>` 객체 하나다(`CRMS/<uuid>/...`는 hard_cases 세트, `SFDC/<uuid>/...`는 rfp 세트, 이름이 `arg_`·`lmx_`로 시작하는 문서는 두 버킷 모두 한빛 업무 문서). `Parsing-Result/`는 파이프라인이 실행 중 쓰는 결과 폴더로 git에 없다. 이 파일(`test_doc_purpose.md`)은 시험 문서가 아니라 안내문이다 — `validation_catalog.py`·동기화 점검 둘 다 이 파일 이름을 예외로 둔다.

정답·목록 세트(`valid_env/eval_sets/` — rfp·hard_cases 정답, `object_keys.csv`, `doc_catalog.jsonl`)는 10-30 지웠다(사용자 — e2-10). 필요하면 git 이력에서 되살린다.

아래 표는 문서마다 "왜" 있는지 — 어떤 파싱 난도를 시험하는지 — 를 적는다. 자세한 요소 목록은 `docs/architecture.md` §10-3, 생성 배경은 `eval_sets/rfp/spec.json`·`eval_sets/hard_cases/spec.json`·`expected.json` 참고.

예상 결과: `ok` = 정상 대조군(완전 재현 기대) · `partial` = 어려운 요소가 있어 완전 재현을 보장하지 않음(이미지 기준 criteria ≥ 0.9, 1.0 아님) · `expected failure` = 파싱을 시도조차 못 하거나 열다가 오류가 날 것으로 설계상 기대.

## CRMS 버킷 (hard_cases 세트, 21건)

| 파일 (s3_key) | 형식 | 세트 | 왜 있나 | gold | 예상 결과 | 관련 이슈 |
|---|---|---|---|---|---|---|
| `CRMS/19f7e8be-02be-5b8a-8918-64496e955191/normal_control.pdf` | pdf | hard_cases | 대조군 — 건너뜀 없음, 정상 파싱 | `expected.json` | ok | - |
| `CRMS/6b86ea92-cf9a-5ba7-9381-cf228e57bdb1/encrypted_ole.doc` | doc | hard_cases | 옛 OLE 암호(FIB fEncrypted) — prepare 단계가 "encrypted"로 사전 차단, 엔진이 열지 않음 | `expected.json` | expected failure | SI44①(✅ 완료) |
| `CRMS/734fac46-4194-5bbd-addc-2a28cfce78ce/drm_protected.docx` | docx | hard_cases | Fasoo DRM 머리 바이트(OOXML이 ZIP도 OLE도 아님) — prepare가 "encrypted"로 사전 차단 | `expected.json` | expected failure | SI44(✅ 완료) |
| `CRMS/fc06205e-ce08-5fc6-9de1-c3c29ea1bba4/archive_unsupported.zip` | zip | hard_cases | 압축 파일, 파싱 대상 형식 아님 — prepare가 "unsupported"로 사전 차단(카탈로그에도 안 올라감) | `expected.json` | expected failure | SI44②(✅ 완료) |
| `CRMS/c04c73a5-3f1d-59fe-b75b-948a1d87c858/corrupt_truncated.pdf` | pdf | hard_cases | 앞 500바이트만 남은 손상 PDF — prepare는 안 거르고 엔진이 실제로 열다가 오류("corrupt" 판정, 분류 로직에 알려진 틈 SI45 있음) | `expected.json` | expected failure(다른 경로 — 사전 차단 아님) | SI45(✅ 완료 — run_board 분류 규칙, pypdfium2 실제 메시지 불일치는 xfail로 남음) |
| `CRMS/1e573cf6-589a-59b8-bbdd-3bc47c800339/symbol_font_pua.docx` | docx | hard_cases | Symbol 글꼴 PUA 문자·`w:sym` 전용 칸·첨자 — 정규화 없이 읽으면 PUA가 그대로 남음 | `gold/symbol_font_pua.docx.md` | partial | SI13(진행)·SI17(✅ 완료)·SI18(🟡 진행, RC2) |
| `CRMS/9d9a56af-8105-5ba8-8db2-9f5ef122d4eb/merged_cells_tbl.docx` | docx | hard_cases | gridSpan(가로)·vMerge(세로) 병합 칸 | `gold/merged_cells_tbl.docx.md` | partial | SI13(진행)·SI16(⏳ 서버 확인) |
| `CRMS/e2ac272a-9ad3-54c8-837a-f4392abd493b/merged_visual_tbl.pdf` | pdf | hard_cases | 같은 값을 실제 셀 병합 없이 그림(벡터 표)으로만 병합 — 그리드 인식 실패 시 셀이 어긋남 | `gold/merged_visual_tbl.pdf.md` | partial | SI16(⏳ 서버 확인) |
| `CRMS/243f7ef5-e309-5808-b855-54e71426ad4e/hidden_textbox.docx` | docx | hard_cases | 용어가 머리글·바닥글·텍스트 상자·캡션에만 있음 — 본문 `w:t`만 읽으면 못 찾음 | `gold/hidden_textbox.docx.md` | partial | SI15(대기 — 완전 누락 원인 중 하나) |
| `CRMS/95194ebe-b50a-52f8-a457-3e4a07174053/text_only_control.pdf` | pdf | hard_cases | 글자 쪽만 — 혼합 문서 비교용 대조군 | `gold/text_only_control.pdf.md` | ok | - |
| `CRMS/de5289a4-a5b4-5dec-911a-d275e49d6500/mixed_scan_text.pdf` | pdf | hard_cases | 한 문서 안 글자 쪽+스캔 쪽 혼합 — 평균 글자수로 분류하면 스캔 전용 엔진이 후보에서 빠질 수 있음(PE1) | `gold/mixed_scan_text.pdf.md` | partial | PE1(열림 — rep 후보 선택이 아직 pymupdf 그대로) |
| `CRMS/f8b466f8-a7d4-559a-afaa-aaece7a8e27b/garbled_text_layer.pdf` | pdf | hard_cases | 그림은 정상인데 글자층이 그림과 무관한 깨진 텍스트 — OCR/VLM 없이는 값이 안 나옴(PE1보다 나쁜 사례) | `gold/garbled_text_layer.pdf.md` | partial | PE1(열림, PE1보다 나쁜 사례로 spec.json에 기록) |
| `CRMS/73ab2382-c016-58d4-9882-9776680bd177/scan_no_text.pdf` | pdf | hard_cases | 글자층 없는 스캔 3쪽(연속) — 전부 스캔이라 분류는 쉬운 대조군, OCR 재현율 확인용 | `gold/scan_no_text.pdf.md` | ok | - |
| `CRMS/d9170a4b-5a89-560f-8041-5c67e5a12ce0/cp949_mail.eml` | eml | hard_cases | `charset=cp949` 선언, 선언과 실제 바이트 일치(기본 케이스) | `gold/cp949_mail.eml.md` | ok | SI42(✅ 완료 — 기본 케이스라 수정 전에도 통과) |
| `CRMS/c63782bc-1d59-5cca-a199-b330a4f1f112/ksc5601_ext_mail.eml` | eml | hard_cases | `charset=ks_c_5601-1987` 선언 + CP949 확장 글자 — euc_kr 별칭만 쓰면 확장 글자가 깨짐 | `gold/ksc5601_ext_mail.eml.md` | partial | SI42(✅ 완료 — `mhtml.py decode_mail_text` ks_c_5601-1987→cp949 넓힘) |
| `CRMS/1ca833b4-daaa-563a-8a20-ad59728e81c7/no_charset_mail.eml` | eml | hard_cases | `charset` 선언 없음 — cp949→utf-8 순 구제 필요 | `gold/no_charset_mail.eml.md` | partial | SI42(✅ 완료) |
| `CRMS/2569a3ca-c945-5881-9eea-bae296e47120/qp_euckr_mail.eml` | eml | hard_cases | euc-kr + quoted-printable(본문이 `=XX`로 인코딩) | `gold/qp_euckr_mail.eml.md` | partial | SI42(✅ 완료) |
| `CRMS/e84d6a6f-d90a-5ae9-9617-3956f6a23a3e/b64_attach_mail.eml` | eml | hard_cases | 한글 첨부 파일명(RFC2231 cp949) + 첨부 내용 cp949 | `gold/b64_attach_mail.eml.md` | partial | SI42(✅ 완료) |
| `CRMS/6434280c-3427-5cac-8ce4-1f413ccce09b/ho_symbol_font_pua.docx` | docx | hard_cases(holdout) | `symbol_font_pua`와 같은 유형, 튜닝 금지 holdout | `gold/ho_symbol_font_pua.docx.md` | partial | SI13(진행)·SI17(✅ 완료)·SI18(🟡 진행) |
| `CRMS/80cad82c-deb0-53ab-853e-1687683d4836/ho_merged_cells_tbl.docx` | docx | hard_cases(holdout) | `merged_cells_tbl`과 같은 유형(머리글 순서 반전), holdout | `gold/ho_merged_cells_tbl.docx.md` | partial | SI13(진행)·SI16(⏳ 서버 확인) |
| `CRMS/f92c6ddb-2aae-5b43-ae62-30dbd022dbe6/ho_hidden_textbox.docx` | docx | hard_cases(holdout) | `hidden_textbox`와 같은 유형, holdout | `gold/ho_hidden_textbox.docx.md` | partial | SI15(대기) |

## SFDC 버킷 (rfp 세트, 12건)

| 파일 (s3_key) | 형식 | 세트 | 왜 있나(고객·프로젝트) | gold | 예상 결과 | 관련 이슈 |
|---|---|---|---|---|---|---|
| `SFDC/a274ce2c-45f7-4b63-8760-66bc552004eb/pfz_rfp_main.docx` | docx | rfp | Pfizar Biopharma·P2026014 상업 DS/DP RFP(8쪽) — 머리글표·병합칸·흐름도·첨자 등 난도 요소 다수 | `rfp/gold/pfz_rfp_main.docx.json` | partial | DX1(⬜ 열림 — docx2python KeyError 'r', office 엔진이 대표를 맡아 영향 없음) |
| `SFDC/72048b36-1ef9-479b-8f0d-6c7ad29b61b9/pfz_qa_thread_en.eml` | eml | rfp | Pfizar·P2026014 Q&A 메일 스레드 3통(인용·Message-ID 사슬·CC·서명·CSV 첨부) | `rfp/gold/pfz_qa_thread_en.eml.json` | partial | - |
| `SFDC/64d6f4fb-ac54-4323-82c3-4f679cb6f419/pfz_fwd_mail_ko.eml` | eml | rfp | Pfizar·P2026014 영문 고객 메일을 한글로 전달+회신(Outlook 원본 메시지 블록, base64) | `rfp/gold/pfz_fwd_mail_ko.eml.json` | partial | - |
| `SFDC/6dd6c33f-257c-4c9f-8729-a746849499b7/pfz_chat_capture.png` | png | rfp | Pfizar·P2026014 사내 메신저 캡처(한글, 시각 전용) | `rfp/gold/pfz_chat_capture.png.json` | partial | - |
| `SFDC/770f2b9c-691f-4d38-85b7-18fd0462bc05/astra_rfp_main.docx` | docx | rfp | AstraNova·P2026033 Phase2 백신 DP RFP — 행/열 병합·2단 구역·스윔레인 흐름도·쪽 넘는 표(머리글 반복 없음, 대조) | `rfp/gold/astra_rfp_main.docx.json` | partial | - |
| `SFDC/082a76fa-cb64-4225-8a00-b9deb0188233/astra_qa_thread_en.eml` | eml | rfp | AstraNova·P2026033 Q&A 메일 스레드 3통 | `rfp/gold/astra_qa_thread_en.eml.json` | partial | - |
| `SFDC/f685a4f7-d9fc-4ddf-8b66-53b34913d824/astra_chat_capture.png` | png | rfp | AstraNova·P2026033 모바일 메신저 캡처(한글) | `rfp/gold/astra_chat_capture.png.json` | partial | - |
| `SFDC/64960b49-fe52-4277-8c2e-2c3969c66bf6/astra_rfi_form.xlsx` | xlsx | rfp | AstraNova·P2026052(같은 고객, 다른 분자) RFI 3시트 — 병합 배너·Y/N 유효성·캐시 없는 SUM 수식 | `rfp/gold/astra_rfi_form.xlsx.json` | partial | - |
| `SFDC/17ae1841-d031-48b5-85b2-2df6058b5857/kvx_rfp_main.pdf` | pdf | rfp | Korvexa·P2026047 Word→PDF ADC RFP — 목차·회전 쪽·간트 표·RFI 부록 | `rfp/gold/kvx_rfp_main.pdf.json` | partial | - |
| `SFDC/1f450a85-3272-42a9-8664-893cff5bb22c/kvx_scan_copy.pdf` | pdf(스캔) | rfp | Korvexa·P2026047 서명 입찰 의향 회신(표지+팩스 양식) — 글자층 없음, 서명·인감·손글씨 | `rfp/gold/kvx_scan_copy.pdf.json` | partial | - |
| `SFDC/f55fa16f-bde6-4cab-831b-878c96c079f9/kvx_qa_thread_en.eml` | eml | rfp | Korvexa·P2026047 Q&A 메일 스레드 3통(DAR 범위 등) | `rfp/gold/kvx_qa_thread_en.eml.json` | partial | - |
| `SFDC/23213095-ea73-4db0-8107-f03a28ff3b78/kvx_internal_note.txt` | txt | rfp | Korvexa 주 + Pfizar 언급 한글 Go/No-go 메모 — 고객 필터 교차 시험 | `rfp/gold/kvx_internal_note.txt.json` | partial | SV15(열림 아님 — 3자 영문 별칭 PFZ/ANB/KVX이 의도적으로 걸러짐, spec.json `known_gap_sv15`) |

## 한빛 업무 문서 (46건 — 10-30 추가)

가상 CDMO "한빛 바이오솔루션"의 고객 Argen Biopharma(ABX-101·ARB-305)·Luminexis Therapeutics(LXT-204) 업무 문서다. 같은 내용을 한글(`_ko`)·영문(`_en`)과 형식별(docx·pptx·xlsx·pdf·png)로 둬서 형식·언어별 파싱과 검색을 비교한다. 영업 단계(제안·예산·견적·계약 검토안·고객 메일)는 SFDC, 수행 단계(분석·품질·안정성·기술이전·위험·운송·시험·시료)는 CRMS에 뒀다. gold는 아직 없고, Argen·Luminexis는 SFDC Opportunity에 없어 `sf_op_id`는 비어 있다(NULL).

### SFDC (10건)

| 파일 (s3_key) | 형식 | 내용 |
|---|---|---|
| `SFDC/6c52362c-2bd4-4320-8ef0-d581b2791caa/arg_abx101_proposal_ko.docx` | docx | Argen Biopharma·ABX-101 사업 제안서 (KO) |
| `SFDC/2ff751c2-3d5a-4456-a9f8-92c7da1b885e/arg_abx101_proposal_en.docx` | docx | Argen Biopharma·ABX-101 사업 제안서 (EN) |
| `SFDC/17ba4467-4820-4209-90d5-b5eb0d3f3632/arg_abx101_proposal_deck_ko.pptx` | pptx | Argen Biopharma·ABX-101 사업 제안 발표 자료 (KO) |
| `SFDC/8e479f2b-b35b-4e8d-bd4a-d1bc9a453072/arg_abx101_proposal_deck_en.pptx` | pptx | Argen Biopharma·ABX-101 사업 제안 발표 자료 (EN) |
| `SFDC/9aaae4d7-1442-43a0-8fde-10f95da3028a/arg_abx101_budget_ko.xlsx` | xlsx | Argen Biopharma·ABX-101 예산·집행표(수식 셀) (KO) |
| `SFDC/3de17d1c-4df3-4082-944d-31c7020401b4/arg_abx101_budget_en.xlsx` | xlsx | Argen Biopharma·ABX-101 예산·집행표(수식 셀) (EN) |
| `SFDC/54f7b5bd-1094-4b41-83e8-6b65d7b2a01a/arg_abx101_sow_cost_ko.pdf` | pdf | Argen Biopharma·ABX-101 개발 제안 비용·일정(SOW) (KO) |
| `SFDC/cbfcc6ad-2ed6-490d-a6cc-de943ea69ac2/arg_abx101_sow_cost_en.pdf` | pdf | Argen Biopharma·ABX-101 개발 제안 비용·일정(SOW) (EN) |
| `SFDC/b40eea44-d26a-450f-81c3-280caab7102f/arg_abx101_review_mail_ko.png` | png | Argen Biopharma·ABX-101 고객 자료 검토 요청 메일 캡처 (KO) |
| `SFDC/c344d2ee-e914-446f-9ced-9720397cda3e/arg_abx101_contract_draft_scan.png` | png | Argen Biopharma·ABX-101 위탁개발 계약서 서명 전 검토안 스캔(직인) |

### CRMS (36건)

| 파일 (s3_key) | 형식 | 내용 |
|---|---|---|
| `CRMS/775b466f-1615-527f-a17e-779818631db8/lmx_lxt204_analytical_plan_ko.docx` | docx | Luminexis Therapeutics·LXT-204 분석 개발 계획서 (KO) |
| `CRMS/fb6c50d3-d3d0-55be-8d66-dbb24b53d948/lmx_lxt204_analytical_plan_en.docx` | docx | Luminexis Therapeutics·LXT-204 분석 개발 계획서 (EN) |
| `CRMS/758e1ccf-4ae0-5db7-b57b-dd5ab0420054/arg_arb305_quality_stability_ko.docx` | docx | Argen Biopharma·ARB-305 품질·안정성 평가서 (KO) |
| `CRMS/a37fb1a1-e6f5-541c-b95f-57cffc099eb3/arg_arb305_quality_stability_en.docx` | docx | Argen Biopharma·ARB-305 품질·안정성 평가서 (EN) |
| `CRMS/5ed11a71-734b-5847-8c8d-ddcc71e175f3/arg_abx101_tech_transfer_plan_ko.docx` | docx | Argen Biopharma·ABX-101 기술이전 준비 계획서 (KO) |
| `CRMS/04e732cf-3493-54be-9ad5-930a6a79a594/arg_abx101_tech_transfer_plan_en.docx` | docx | Argen Biopharma·ABX-101 기술이전 준비 계획서 (EN) |
| `CRMS/01623e94-6221-5842-85c0-8bb117fe4bab/lmx_lxt204_process_risk_ko.docx` | docx | Luminexis Therapeutics·LXT-204 공정 개발·위험 관리 보고서 (KO) |
| `CRMS/40cb4df8-5ce1-564a-b6e8-539579122a8d/lmx_lxt204_process_risk_en.docx` | docx | Luminexis Therapeutics·LXT-204 공정 개발·위험 관리 보고서 (EN) |
| `CRMS/8d54ccca-cb70-5bec-b8d7-d1c21255aca5/lmx_lxt204_analytical_deck_ko.pptx` | pptx | Luminexis Therapeutics·LXT-204 분석 개발 발표 자료 (KO) |
| `CRMS/4d58683d-39cd-5397-8392-554fe8371380/lmx_lxt204_analytical_deck_en.pptx` | pptx | Luminexis Therapeutics·LXT-204 분석 개발 발표 자료 (EN) |
| `CRMS/7f224a5e-cb37-5e5a-b1cb-8bbd6897c60a/arg_arb305_quality_deck_ko.pptx` | pptx | Argen Biopharma·ARB-305 품질·안정성 발표 자료 (KO) |
| `CRMS/89caca4f-511d-5a4d-997d-2a11a9a83600/arg_arb305_quality_deck_en.pptx` | pptx | Argen Biopharma·ARB-305 품질·안정성 발표 자료 (EN) |
| `CRMS/59e05167-180f-5a35-b546-d4344491ca3b/arg_abx101_tech_transfer_deck_ko.pptx` | pptx | Argen Biopharma·ABX-101 기술이전 발표 자료 (KO) |
| `CRMS/8ea49c70-bb68-564d-b294-969cc208ca92/arg_abx101_tech_transfer_deck_en.pptx` | pptx | Argen Biopharma·ABX-101 기술이전 발표 자료 (EN) |
| `CRMS/3f09f2fe-6734-5c79-b2bd-9059854a52b3/lmx_lxt204_process_risk_deck_ko.pptx` | pptx | Luminexis Therapeutics·LXT-204 공정·위험 발표 자료 (KO) |
| `CRMS/8d94da26-88e9-5ed8-9491-ade1902a7be0/lmx_lxt204_process_risk_deck_en.pptx` | pptx | Luminexis Therapeutics·LXT-204 공정·위험 발표 자료 (EN) |
| `CRMS/fd13ded9-428f-5ea8-958f-f2bc32190c22/lmx_lxt204_qc_results_ko.xlsx` | xlsx | Luminexis Therapeutics·LXT-204 시험 결과 검토표 (KO) |
| `CRMS/b442533c-714c-5e81-a5a8-e42afd84f392/lmx_lxt204_qc_results_en.xlsx` | xlsx | Luminexis Therapeutics·LXT-204 시험 결과 검토표 (EN) |
| `CRMS/0386dd56-1b0d-56f5-9185-33fd6cc2cc54/arg_abx101_stability_trend_ko.xlsx` | xlsx | Argen Biopharma·ABX-101 안정성 추세표 (KO) |
| `CRMS/13f5ae03-9dc7-507d-9264-cb0abf371bd6/arg_abx101_stability_trend_en.xlsx` | xlsx | Argen Biopharma·ABX-101 안정성 추세표 (EN) |
| `CRMS/7d4fca0e-768c-5846-8d60-facf71830a84/lmx_lxt204_shipping_log_ko.xlsx` | xlsx | Luminexis Therapeutics·LXT-204 운송 온도·인수표 (KO) |
| `CRMS/b178799c-512f-58af-9cc8-e4e8bbcf7c72/lmx_lxt204_shipping_log_en.xlsx` | xlsx | Luminexis Therapeutics·LXT-204 운송 온도·인수표 (EN) |
| `CRMS/19432730-d249-5fbe-90d4-c8e342866870/arg_abx101_risk_actions_ko.xlsx` | xlsx | Argen Biopharma·ABX-101 위험·조치 현황표 (KO) |
| `CRMS/bfa18b73-0394-529c-8a71-7580c0354cc0/arg_abx101_risk_actions_en.xlsx` | xlsx | Argen Biopharma·ABX-101 위험·조치 현황표 (EN) |
| `CRMS/20286fa3-68d0-5a0c-bd84-7240b923343a/arg_abx101_analytical_report_ko.pdf` | pdf | Argen Biopharma·ABX-101 품질 분석 보고서 (KO) |
| `CRMS/0f02d780-bebe-5d28-8c68-33620e54e7ee/arg_abx101_analytical_report_en.pdf` | pdf | Argen Biopharma·ABX-101 품질 분석 보고서 (EN) |
| `CRMS/edd2e62f-2156-51af-a108-62bb13d40814/lmx_lxt204_stability_report_ko.pdf` | pdf | Luminexis Therapeutics·LXT-204 안정성 추세 보고서 (KO) |
| `CRMS/70ca1c93-831d-5532-abff-a219cf2693bf/lmx_lxt204_stability_report_en.pdf` | pdf | Luminexis Therapeutics·LXT-204 안정성 추세 보고서 (EN) |
| `CRMS/aa7294c0-e22f-5dda-a42f-4c694a6ad2a1/arg_abx101_tt_workflow_ko.pdf` | pdf | Argen Biopharma·ABX-101 기술이전 의사결정 흐름도 (KO) |
| `CRMS/d0c5fe0c-eca3-512f-a60f-08c7d23ffb4c/arg_abx101_tt_workflow_en.pdf` | pdf | Argen Biopharma·ABX-101 기술이전 의사결정 흐름도 (EN) |
| `CRMS/63255c9f-856e-5d65-92c3-b09b881c7b96/lmx_lxt204_shipping_record_ko.pdf` | pdf | Luminexis Therapeutics·LXT-204 시료 운송·인수 기록(쪽 넘는 표) (KO) |
| `CRMS/2995b35a-e08b-5288-9c0d-25f3008cef64/lmx_lxt204_shipping_record_en.pdf` | pdf | Luminexis Therapeutics·LXT-204 시료 운송·인수 기록(쪽 넘는 표) (EN) |
| `CRMS/dbf26861-3224-5759-926e-511574ff1d3d/lmx_lxt204_shipment_mail_en.png` | png | Luminexis Therapeutics·LXT-204 시료 발송 메일 캡처 (EN) |
| `CRMS/58ee9e22-34a3-5004-9104-924c49e3e287/arg_abx101_test_report_scan.png` | png | Argen Biopharma·ABX-101 시험 결과 보고서 스캔(손글씨 표시) |
| `CRMS/c6532711-6031-5a69-a504-985dd8a86fb1/lmx_lxt204_sample_receipt_photo.png` | png | Luminexis Therapeutics·LXT-204 시료 접수 양식 사진(손글씨·기울어짐) |
| `CRMS/ad0831fc-55a6-5a3d-8161-fcd3ab418236/arg_arb305_lims_stability_capture.png` | png | Argen Biopharma·ARB-305 LIMS 안정성 화면 캡처(그래프·표) |

## 알려진 이슈 요약 (백로그 기준, 이 문서들에 닿는 것만)

| ID | 증상 | 해당 문서 | 상태 |
|---|---|---|---|
| SI13 | 표 칸 재현율 50~60%(최저 17.7%) — 표 구조·기호 표기 정규화 미완 | symbol_font_pua.docx·merged_cells_tbl.docx(+holdout 2건) | 진행(완료 2/3) |
| SI15 | 특정 단어 완전 누락(그림 속 글자·머리말/각주·숨은 글자층·글꼴 대응표 없음 중 원인 미확정) | hidden_textbox.docx(+holdout) | 대기 |
| SI16 | 표 구조 추출 실패 — pdfplumber·kreuzberg·markitdown이 다열·병합 칸을 못 읽음 | merged_cells_tbl.docx·merged_visual_tbl.pdf(+holdout) | ⏳ 서버 확인 대기 |
| SI18 | `w:sym` 칸(예: ≥)이 빔 — `standardize_rep`가 grid 칸을 표준화 안 함 | symbol_font_pua.docx(+holdout) | 🟡 진행(RC2) |
| PE1 | 문서 평균 글자수로만 분류하면 스캔 전용 엔진이 후보에서 빠질 수 있음 — 대표(rep) 선택이 아직 pymupdf 그대로 | mixed_scan_text.pdf·garbled_text_layer.pdf | 열림 |
| DX1 | docx2python이 `pfz_rfp_main.docx`에서 KeyError 'r' — office 엔진이 대표를 맡아 결과엔 영향 없음 | pfz_rfp_main.docx | 열림(⬜ 미착수) |
| SV17 | 파싱 임시 저장 경로 길이 제한(uuid+원천+원본명+엔진명/버전이 다 들어가 초과) — 로컬 사본 이름을 `<uuid><확장자>`로 바꿔 해소 중, 모든 object_storage 문서의 임시 경로에 공통 적용 | 전체 object_storage 문서(개별 문서 한정 아님) | 🟡 거의 끝(서버 실데이터 긴 이름 1건 확인 남음) |

완료(✅)로 표시된 SI42(한글 인코딩 판별, eml 5건)·SI44(암호·DRM·압축 판별, encrypted_ole/drm_protected/archive_unsupported)·SI45(손상 PDF 분류, corrupt_truncated)·SI17(특수문자·첨자 표기)은 위 표에서 뺐다 — 위 두 표의 "관련 이슈" 칸에 완료 표시로 남아있다.

## 시험 문서를 추가하려면
1. 파일을 `valid_env/object_storage/<원천>/<uuid>/<파일>`(s3_key)에 둔다.
2. `valid_env/edw/ai.sql`의 `FileStorageMap` INSERT에 같은 행을 더하고 `python -m validation.e2e.edw_standin`으로 `valid_env/edw/edw.sqlite`를 다시 만든다.
3. 이 파일에도 행 하나를 더한다.
