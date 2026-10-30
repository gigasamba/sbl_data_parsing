# PC 시험 문서 목적 안내

`valid_env/object_storage/`는 서버 Object Storage 버킷을 PC에서 흉내 낸 폴더다. 문서 1건 = `<원천>/<uuid>/<파일>` 객체 하나다(`CRMS/<uuid>/...`는 hard_cases 세트, `SFDC/<uuid>/...`는 rfp 세트). `Parsing-Result/`는 파이프라인이 실행 중 쓰는 결과 폴더로 git에 없다. 이 파일(`test_doc_purpose.md`)은 시험 문서가 아니라 안내문이다 — `validation_catalog.py`·동기화 점검 둘 다 이 파일 이름을 예외로 둔다.

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
