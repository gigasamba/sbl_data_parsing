# sbl_data_parsing — PRD

목표: 폐쇄망 회사 문서에서 출처 달린 근거를 찾는다 — 파싱 → 구조화 → 적재(pgvector) → 검색 MCP, 서버와 PC에서 같게.
행 = 되어야 할 모습(요건) 하나(끝난 것 포함) — 칸은 요건(무엇을, 어디서) · 기준·이유 · 상태 · ID · 비고(지금 코드가 요건과 다른 점 — 비면 같음). 할 일 목록이 아니다: 비고의 차이를 줄여 가는 것이 할 일이다. ID 하나가 여러 행에 나올 수 있다(상세는 ID 링크의 앵커). 상태: todo · dev · done.

## 지금 진행 중
- pl-25 DB 스키마 명세 — dev: 검색 DB(gold — 처리 기록 `doc` 칸 판 0006 포함)·마스터·applog는 구현됨, 서버 판 올리기·ParsingMeta 기록 옮기기는 DB 담당자 승인·실행 대기(refactor.md C-107).
- 열린 요건(todo): run_pipeline 지휘만 [rn-05](prd/ops.md#rn-05) · 저장 구조 [pl-32](prd/load-schema.md#pl-32) · 확장자 `.hwp` [pl-45](prd/transform.md#pl-45) · 그림 부가 기능 줄이기 [pl-05](prd/transform.md#pl-05) · 전체 e2e [pl-54](prd/ops.md#pl-54) · prd 이미지에 settings.yaml 굽기 [op-12](prd/doc.md#op-12) · 판 묶기(잠재 문제) [pl-56](prd/load.md#pl-56).
- 서버 확인만 남음(dev): parse_document CPU 우선 [rn-03](prd/ops.md#rn-03).
- 정리·구조(todo, 사용자 11-08): 옛 오피스 검사기 [pl-66](prd/extract.md#pl-66) · 대표 결과 교차 병합 [pl-67](prd/transform.md#pl-67) · 실버 먼저 적재 [pl-68](prd/load.md#pl-68) · DB 시험 [e2-22](prd/test.md#e2-22).
- 시험 정리(todo): [e2-13](prd/test.md#e2-13) · [e2-20](prd/test.md#e2-20).

## 수집 (extract) — 서버에서 문서 목록을 정하고 받아 오기까지
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 문서 목록은 EDW 표 `AI.FileStorageMap`에서 읽는다(`id`·`s3_key`·`original_filename`·`file_size`·`source_system`) — 컨테이너 안 `candidate_pick list`(서버 러너 `run_pipeline.py`가 부름)가 원천 목록(`required.source.source_systems` — 비우면 운영 5개 원천, `DEV-<숫자>` 행은 뺌)과 파일 이름 키워드(`--filter`)로 거르고 작은 파일부터 | 목록의 기준은 EDW다. Object Storage를 직접 훑지 않는다 | done | [pl-01](prd/extract.md#pl-01) |  |
| 새 문서만 고른다 — 목록에서 gold `doc` 행(원천 스키마 5벌 어디든)이 있는 원본 키(`s3_key` = `doc.file_path`)를 뺀다. `pipeline/extract/candidate_pick.py` `done_keys` 하나가 PG를 한 번 읽음(`pipeline/shared/gold_docs.py` — 서버는 `list --skip-done`, PC 직접 파싱은 `unparsed`) | 끝난 문서를 다시 파싱하지 않는다. 파싱·게시·적재 실패는 `doc` 행이 없어 다시 고른다. 영구 건너뜀 문서도 뺀다([pl-58](prd/extract.md#pl-58)). 서버에서 PG를 못 읽으면 시작하지 않는다(종료 4) | done | [pl-23](prd/ops.md#pl-23) |  |
| 파일은 Object Storage 버킷에서 `s3_key`로 받는다. 파싱 입력은 폴더 또는 목록 파일(`rdb:csv:<경로>`) 둘뿐 | 길을 하나로 | done | [pl-01](prd/extract.md#pl-01) |  |
| 미리 받기(staging) — `run_pipeline`이 파싱보다 앞서 문서를 최대 20개(`ops.run_pipeline.staging.staging_max_docs`)까지 컨테이너 안 `candidate_ready stage`로 받아 `_staging`에 둔다. 원본을 받는 길은 이것 하나 — 같은 단계에서 같은 내용 하나만·형식·DRM·암호 거르기까지 하고 파싱은 남은 문서만 읽는다 | 다운로드를 기다리느라 파싱 워커가 놀지 않게. 받기에 실패한 문서는 파싱 실패로 끝난다(따로 받는 길 없음) | done | [pl-01](prd/extract.md#pl-01) |  |
| 병렬 다운로드 — 목록 파일의 여러 파일을 동시에 받는다(`candidate_ready stage`의 staging 받기 — `extract.source.source_fetch_threads`, 기본 1개) | 큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 안 쓴다 | done | [pl-48](prd/extract.md#pl-48) |  |
| 서버 러너도 병렬로 받는다 — 받기 워커 `ops.run_pipeline.staging.staging_workers`(기본 2)개. 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리) | 미리 받기 상한 `ops.run_pipeline.staging.staging_max_docs`(받는 중 포함)과 함께 작동 — 빈자리가 없으면 워커가 있어도 받지 않는다 | done | [pl-48](prd/extract.md#pl-48) |  |
| 레인 나누기 — 받은 직후 셋으로. **vlm**: 스캔 PDF(첫 3쪽 글자 평균 300자 미만)·그림 많은 오피스(내장 그림 8개 이상 또는 800 KB 이상)·pptx·ppt·내용 검사 실패·검사 목록 밖 형식(mht·mhtml·이미지 등). **medium**: 검사한 pdf·오피스 중 가벼운데 큰 파일(docx·doc 300 KB, xlsx·xls·xlsm 500 KB, pdf 1 MB 이상). **light**: 글자형(txt·hwp·hwpx·csv·eml·msg·html)과 나머지 | 그림 읽는 모델(VLM)이 필요한 무거운 문서가 가벼운 문서를 막지 않게 — 레인마다 전담·공유 워커, vlm은 동시 2개(GPU), light는 CPU 부하 대기를 건너뜀(규칙은 `doc_lane_group.py` `doc_lane_group()` 하나 — `run_pipeline.py` `classify_doc`이 컨테이너 안에서 부름) | done | [rn-01](prd/ops.md#rn-01) |  |
| 받기 → 중복 제외 → 거르기 순서로 한 번씩(`candidate_ready.stage_batch`). 중복 = 받은 파일 sha256이 같은 묶음 안 다른 파일, 또는 gold `doc.sha256`이 같은 다른 원본 키 — 하나만 파싱하고 나머지는 건너뜀 + `applog.except_doc_info` `skip` `duplicate_sha256`(서버 러너는 건너뜀으로 셈). 건너뛴 문서(중복·DRM·암호·미지원)는 문서마다 `pipe_event` 한 행(`extract.skip`) | 비싼 파싱을 중복하지 않는다(S3 키가 달라도 내용이 같으면 중복). 키마다 메타(고객 등)가 달라 문서는 따로. 남길 사본: 사본 표시 없는 이름 → 최신 → 큰 파일(`deduplication.py` `run_folder()`) | done | [pl-02](prd/extract.md#pl-02) |  |
| 회전 바로잡기 — 켜면(`extract.prepare.rotate_pages`, 기본 꺼짐) 이미지·스캔 PDF 쪽마다 4방향(0·90·180·270도) OCR 점수를 스레드 4개로 동시에 재 가장 높은 방향으로 돌린다(같으면 0도). 기록 `rotation.csv` | 돌아간 스캔은 엔진이 읽지 못한다. 꺼져 있으면 회전용 OCR을 하지 않는다 | done | [pl-02](prd/extract.md#pl-02) |  |
| 다시 받아도 파싱할 수 없는 원본(지원 안 하는 확장자·확장자 없음·DRM·암호)과 내용 중복(`duplicate_sha256` — 같은 묶음·같은 밤·끝난 문서)은 `applog.except_doc_info`에 원본 키당 `skip` 한 행(이유·`level` `error`·처음·마지막 시각·횟수)을 남기고, 대상 목록 `candidate_pick list --skip-done`이 그 키를 뺀다 — 받기 전(`rdb_pick`)·받은 뒤(`filter_and_rotate`·중복 제외) 쓴다. 파싱·적재 실패는 `error` 행(기록만 — 다음 실행이 다시 고름, op-17) | 같은 문서를 밤마다 다시 받지 않고 `--max-docs`가 새 문서를 고르게(사용자 11-05). DB 스키마 — 사람 검토 | dev | [pl-58](prd/extract.md#pl-58) | 서버 `migrate up --target applog`(판 0003)·DB 담당 승인 대기(refactor.md C-96) |
| DRM·암호 파일 감지 — 감지해서 표시만(`skipped_drm`) | 복호화는 하지 않는다 — 수동 명령도 없음(사용자 11-08) | done | [pl-02](prd/extract.md#pl-02) |  |
| 압축 원본(zip·tar·tar.gz)은 풀어서 안 파일의 글을 그 문서 본문에 `[파일 …]` 절로 넣는다 — 메일 첨부와 같게(pl-36), 암호·깨짐·안전 상한은 건너뛰고 기록 | zip 안의 문서도 검색되어야 한다(사용자 11-05·11-06) | done | [pl-57](prd/extract.md#pl-57) |  |
| 문서 안 문서(압축 안 파일·메일 첨부·메일 안 메일·새 형식 오피스 안 개체)는 받기 단계가 준비 폴더 `_parts/`에 깊이 2까지 꺼내 두고, 첨부 단계가 파싱해 본문 끝 `[파일]`·`[첨부]`·`[개체 …]` 절로 붙인다 — 개체는 있던 자리에 위치 표시 | 안의 문서가 같은 길로 검색되게(사용자 11-06). 엔진은 고치지 않음 | done | [pl-63](prd/extract.md#pl-63) |  |
| 옛 형식(.doc·.xls·.ppt)·PDF·한글(.hwpx) 안 개체도 같은 길로 | pl-63과 같은 이유 | todo | [pl-64](prd/extract.md#pl-64) | 반영 없음 |
| FAQ 원천 — 질의응답 엑셀을 행 단위로(시트 = FAQ 묶음, 행 하나 = 청크 하나). `FAQ/<uuid>/<파일>`을 FileStorageMap에 등록 | 질의응답을 문서 통째가 아니라 질문 하나 단위로 찾는다 | done | [pl-39](prd/extract.md#pl-39) |  |
| 같은 밤에 받은 같은 내용 문서는 하나만 파싱한다 — 문서마다 따로 받는(stage) 서버 흐름에서도 이번 실행이 이미 받은 sha256과 같으면 건너뜀 + `applog.except_doc_info` `skip` `duplicate_sha256`(먼저 받은 원본 키는 `pipe_event` `dup_of`) · staging 재사용은 내용이 같을 때만(ETag) | 같은 파일을 두 번 파싱·적재하지 않는다. 크기만 같은 새 판을 옛 파일로 파싱하지 않는다 | dev | [pl-59](prd/extract.md#pl-59) | 러너 `stage_one`이 앞 실행 문서 폴더를 원본 키만 보고 다시 씀(ETag 비교·이번 실행 표지 없음) · 원본 삭제가 `.etag` 옆 파일을 남김 |
| 고르기·받기(extract)는 변환(transform)을 import하지 않는다 — 지원 확장자 목록은 `pipeline/shared`에 · 원천 이름은 FileStorageMap `source_system` 값 하나 | ETL 방향을 지킨다(rn-08). 원천 이름이 자리마다 다르면 게시·구조화·건너뜀 기록의 원천이 어긋난다 | todo | [pl-59](prd/extract.md#pl-59) | `candidate_pick`·`filter_and_rotate`가 `transform.parse.engines.registry`를 import |
| 안 문서를 꺼내지 못한 경우(깨짐·암호·상한) 성한 안 파일은 그대로 붙여 적재하고, `applog.except_doc_info`에 원본 키당 종류 `part`·수준 `warn` 한 행(이유 = 못 꺼낸 안 파일 이름과 까닭)을 남긴다. 꺼내기는 이름 글자(cp949·cp437)를 바로 읽고, 원본 하나의 꺼낸 합계 크기 상한을 두고, 목록 `parts.json`은 다 쓴 뒤에만 보이게 쓰고, 신선도는 원본 sha256으로 본다. 같은 내용 첨부는 한 번만, 이름 속 줄바꿈은 지워 절 제목이 깨지지 않게. 붙인 절은 제목 줄(`## [첨부 …]`)로 시작 | 무엇이 빠졌는지 알 수 있게(사용자 11-08). 표 구조는 그대로 — 새 종류 값 `part`는 DB 담당자에게 알림(C-111) | done | [pl-65](prd/extract.md#pl-65) |  |
| 옛 형식 오피스(`.doc`·`.xls`·`.ppt`)의 암호·DRM·안 구조 검사는 읽기 코드 하나(olefile)로 한다 — 견본 문서로 두 코드 결과가 같음을 시험으로 확인한 뒤 | 같은 일을 두 벌로 하지 않는다. 옛 형식도 지금처럼 잘 돌아야 한다(사용자 11-08) | todo | [pl-66](prd/extract.md#pl-66) | 지금 olefile과 직접 짠 `_cfb_sectors` 두 벌 |

## 변환 (transform) — 파싱·대표 결과 고르기·그림·구조화
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 파일 형식마다 엔진 구성 파일(`resources/config/pipeline_stack.json`)에 적힌 엔진을 **모두** 돌린다(하나씩 차례로 시도하지 않음) | 모든 형식을 잘 읽는 파서는 없다. 서버·PC가 같은 파일을 쓰고, 바꿀 때는 그 파일을 고쳐 코드 폴더를 바꾼다. 파일을 못 읽거나 모양이 틀리면 시작하지 않는다(종료 2) | done | [pl-03](prd/transform.md#pl-03) |  |
| PDF는 두 갈래 — 글자층이 쪽당 평균 20자 미만이면 스캔(`.pdf_image` → VLM 엔진만), 아니면 글자 PDF(`.pdf_text` → pymupdf·kreuzberg) | 스캔 PDF는 글자 엔진이 못 읽는다. 판정은 `_types.json`에 저장해 다시 쓴다 | done | [pl-03](prd/transform.md#pl-03) |  |
| 지원 형식 = 구성 파일의 형식 키(목록은 앵커) | 구성 파일이 정본 | done | [pl-03](prd/transform.md#pl-03) · [pl-42](prd/transform.md#pl-42) |  |
| 엔진은 문서마다 동시에, 엔진마다 따로 떨어진 자식 프로세스 | 엔진 하나가 죽어도 다른 엔진을 막지 않는다 | done | [pl-22](prd/transform.md#pl-22) |  |
| 시간 제한 = 쪽 수 × 10초(글자 엔진)·× VLM 호출 제한 `common.models.vlm.vlm_timeout_sec`(180초, VLM 엔진), 엔진 첫 문서는 최소 60초, 여기에 시작 여유 10초. 넘으면 두 배로 한 번 더, 그래도 넘으면 실패 기록 | 큰 문서도 쪽 수만큼 시간을 받는다 | done | [pl-22](prd/transform.md#pl-22) |  |
| 그림 글자 인식 엔진(OCR, `rapidocr_ko`)은 파싱에 돌지 않는다 — 이미지·스캔은 VLM만. 일괄 실행 엔진은 낮은 우선순위(nice +10) | OCR은 VLM과 겹치고 느리다. 검색 서비스 자원을 덜 뺏는다 | done | [pl-22](prd/transform.md#pl-22) |  |
| VLM 처리 한 길 — 엔진 `qwen_vlm`·쪽 VLM·그림 VLM이 같은 호출(`pipeline/shared/vlmcall.py`)과 같은 설정: 동시 수 `common.models.vlm.vlm_requests_per_doc`(문서 하나 안 4)·`vlm_max_total_requests`(전체 합 8), 호출 1건 제한 `vlm_timeout_sec`(180초)·재시도 `tuning.common.models.vlm.vlm_retries`·`vlm_extra_request_body`(생각 끄기 등), 해상도 `extract.page_render_dpi`(150), 쪽 상한 `transform.vlm.vlm_max_pages_per_doc` | 공유 VLM 서버를 넘치게 하지 않는다. 경로마다 손잡이·요청 모양이 달라 같은 설정이 일부에만 먹던 것을 없앤다(사용자 11-04) | done | [pl-43](prd/transform.md#pl-43) |  |
| 확장자 `.jpeg`·`.tif`·`.tiff`·`.bmp`는 `.jpg`와, `.mhtml`은 `.mht`와 같은 엔진. `.hwpx` 지원 | 형식마다 임시 견본으로 파싱 시험(`test_ext_formats.py`) | done | [pl-42](prd/transform.md#pl-42) |  |
| 확장자 `.docm`·`.pptm`·`.rtf`·`.csv`·`.tsv`·`.md`·오픈문서·서식 파일·`.json`·`.xml`·`.log`·`.hwp` 지원 — 엔진 파일은 그대로 두고 등록부(`registry.py`)의 "엔진별 추가 확장자" 표로 | 엔진 지문을 지킨다. `.json`·`.xml`·`.log`는 글 그대로. 사람 검토(등급 A) | todo | [pl-45](prd/transform.md#pl-45) | `.hwp`가 없다 — 실제 `.hwp` 문서로 시험한 뒤 더함 |
| 대표 결과 고르기(represent): 엔진 결과 중 정확하고 풍부한 것을 대표로 고르고, 줄 단위 투표로 합치고, 엔진 사이 라벨·값을 서로 확인한다(`doc_represent.py`·`fragment_vote.py`·`crosscheck.py`) | 엔진마다 결과가 다르다. 다음 단계로 넘기는 글은 가장 정확해야 한다 | done | [pl-04](prd/transform.md#pl-04) |  |
| 표·기호 다듬기 — 여러 엔진의 표를 본문 제자리에 넣고(`table_inline.py`), 표준 표·윗첨자 `^`·아래첨자 `_`, 파싱 품질 점검(`parse_scoring.py`) | 표가 문서 끝에 따로 붙으면 검색 근거가 끊긴다 | done | [pl-04](prd/transform.md#pl-04) |  |
| 글자 PDF 속 스캔 쪽만 쪽 전체를 VLM으로 읽어 채운다(회전된 쪽·숨은 글자 겹친 쪽 각각 최대 20쪽) | 스캔 쪽 몇 장 때문에 스캔용 엔진을 통째로 돌리지 않는다 | done | [pl-22](prd/transform.md#pl-22) |  |
| 메일 첨부 — `.eml`·`.msg`의 첨부·메일 안 메일을 깊이 2·20 MB·10개까지 파싱해 본문에 `[첨부 <파일명>]` 절로 붙이고(꺼내기는 받기 단계 — pl-63), 인용 스레드는 접는다(`mail_attachments.py`) | 메일의 핵심 내용이 첨부에 있는 경우가 많다 | done | [pl-36](prd/transform.md#pl-36) | 글자 첨부(text/plain)는 `.eml` 엔진 본문과 `[첨부 …]` 절에 두 번 들어감 |
| 그림 근처 맥락 — 캡션·본문 언급을 연결하고 값이 맞는지 표시한다(`figure_context.py`) | 그림 설명을 본문과 함께 찾게 한다 | done | [pl-37](prd/transform.md#pl-37) |  |
| 그림 설명 — 그림마다 VLM 한 번(문서당 최대 20개, 짧은 변 64 px 미만은 뺌). 차트 XML·벡터 차트 값은 VLM 없이, 슬라이드·도형은 soffice로 그려 읽는다 | 차트·도식에는 글자 추출이 놓치는 값이 있다 | todo | [pl-05](prd/transform.md#pl-05) |  |
| 그림 부가 정보는 VLM 한 번의 종류별 출력(도표 Mermaid·표 HTML·차트 값)으로만 — 화살표·겹침·도형 연결·Mermaid를 따로 만드는 단계는 없다 | 같은 정보를 두 길로 만들지 않는다. 바꾸면 대표 결과 지문 p1이 바뀐다 | todo | [pl-05](prd/transform.md#pl-05) | `figures/`에 부가 기능 파일(`diagram_edges.py`·`overlay_groups.py`·`pptx_edges.py`·`nested_figures.py` 등)이 따로 돈다 |
| 청크(검색 단위 조각) 나누기 — 구성의 `chunk`(지금 `structure` — 800자, 제목 기준, 표는 통째). 큰 표 25행씩 나누기는 `CHUNK_TABLE=rows`일 때만 | 검색은 출처가 달린 짧은 조각 단위로 한다 | done | [pl-06](prd/transform.md#pl-06) |  |
| 문서 요약 = 앞부분 300자 발췌. 본문 고객(`clients_doc`)은 명부 이름·별칭이 2번 이상 또는 제목·첫 400자에 나온 것 | 요약은 지어내지 않는다 | done | [pl-06](prd/transform.md#pl-06) |  |
| 임베딩(검색용 숫자 벡터) — 내부망 `api`(`required.models.embed_base_url`·`embed_model`)만(시험은 `none`) | 폐쇄망 안 모델 하나로 질의·문서를 같게 | done | [pl-06](prd/transform.md#pl-06) |  |
| 분류 — 적재 때 gold에 넣기 전 SFDC·LAS 문서에 종류 라벨 `doc_class`(SFDC 5종·LAS 7종). 근거 = gold `doc.attrs`의 분류 힌트 키(사슬 파일 `edw_chain.yaml` — 적재 때 EDW 조인) + 대표 결과 .md 앞 8,000자 | 운영 분류와 결과가 같게 — 지시문·사용자 쪽 글 운영 글자 그대로, 내부 모델·`llm.chat`, 집합 밖·장애는 그 문서의 적재 실패(다음 실행에 다시), 재시도·수동 명령 없음, 이미 있는 라벨 안 덮음 | done | [pl-33](prd/transform.md#pl-33) |  |
| 엔진은 구성 파일에 쓰이는 것만(비교용 `docx2python` 예외) — 엔진 목록의 정본은 등록부. `ocr_vlm` 엔진·`vlm.model_alt` 칸 없음 | 쓰지 않는 엔진은 지문·이미지만 무겁게 한다. 등급 A | done | [pl-31](prd/transform-cleanup.md#pl-31) |  |
| 대표 결과는 융합 결과를 그대로 쓴다 — 다시 읽기(P2·P3)·스캔 중복 제거·렌더 OCR 신호 없음 | 비용에 비해 결과가 나아지지 않았다. 등급 A | done | [pl-34](prd/transform-cleanup.md#pl-34) |  |
| 처리는 새 문서만 고르는 증분 하나 — 문서 단위 병렬 실행기·자동 재파싱 스위치·그림 이어 하기 없음 | 실행 길이 여럿이면 서버에서 어느 길을 탔는지 모른다 | done | [pl-35](prd/transform-cleanup.md#pl-35) |  |
| 0.2.0 지문 배치의 모양 — 이미지·`.pdf_image` 엔진은 `qwen_vlm` 하나, 모델 호출은 `llm.complete` HTTP 한 길(앱은 `litellm`·`google.adk` import 0), 지운 설정 칸 표 없음, 점검은 `checker.py` 하나 | 지문이 바뀌는 정리를 서버 재처리 한 번에 모았다. 등급 A | done | [pl-46](prd/transform-cleanup.md#pl-46) |  |
| 엔진 지문(p0) 범위 = 엔진 폴더의 모든 `.py` + 엔진 실행 파일 + 엔진이 import하는 pipeline 파일 | 이름과 폴더가 다른 엔진(html_stdlib·msg_extract·rapidocr_ko·office)을 고쳐도 지문이 바뀌게. 등급 A | done | [pl-47](prd/transform-cleanup.md#pl-47) |  |
| 명부·사전·원본 해시·매니페스트·엔진 지문은 프로세스마다 한 번만 읽고, 엔진 결과는 자식이 한 번에 쓰고, 1건 중복 확인은 자식 없이 | 결과는 바이트 그대로. 등급 A | done | [pl-49](prd/transform-cleanup.md#pl-49) |  |
| 결과를 바꾸는 파일은 층 지문 목록에 들고, 기록·DB 표 정의는 지문 계산에서 빠진다. extract → transform → load 방향은 자동 점검(`check_modules` ⑫, 예외 없음) | 빠지면 고쳐도 옛 결과를 다시 쓰고, 넘치면 상관없는 수정에도 재처리 경보가 남. 등급 A | done | [pl-50](prd/transform-cleanup.md#pl-50) |  |
| `dbtool`에 첫 이관 도구(`dbcompare`·`stamp`)가 없고(0.2.0 배포 뒤), 이미지 의존성에는 앱 코드가 쓰는 패키지만 | 첫 이관 도구와 안 쓰는 패키지는 이미지와 점검 범위만 키운다. 패키지를 빼면 새 이미지 버전 | done | [pl-53](prd/transform-cleanup.md#pl-53) |  |
| 쪽 수 세기는 함수 하나 — `pdf_kind.doc_pages`와 `vlmcall.page_count`가 같은 규칙 | 쪽 수가 자리마다 다르면 제한 시간·쪽 VLM 상한이 어긋난다. `vlmcall.py`는 엔진 지문에 들어가 사람 검토(등급 A) | todo | [pl-60](prd/transform.md#pl-60) | 두 함수가 따로 있음 |
| 대표 결과가 엔진이 읽은 글을 흐리거나 버리지 않는다 — 표 칸을 다른 칸 글자 안에서 찾지 않음 · 쪽 VLM 글이 없는 쪽의 그림은 빈 블록으로 넣지 않음 · docx에서 anydoc만 읽은 글을 합침 · VLM 엔진 쪽 글도 되풀이 고장을 거름 | 검색 조각에 쓰레기 줄이 섞이거나 글상자·병합 칸 글이 빠진다(0.3.0 엔진 비교 11-06) | todo | [pl-62](prd/transform.md#pl-62) | 표 조각 30줄(stability_trend_ko) · 빈 그림 블록 5개(tt_workflow_en) · anydoc 글 합침 0 · VLM 엔진 되풀이 거름 없음(vlmcall — 사람 검토) |
| 대표 결과 — 확장자에 성공한 엔진이 하나면 그대로 쓴다. 여럿이 성공하고 내용이 서로 다르면 소제목·표·쪽·위치(bbox) 조각 단위로 교차 병합한다. 먼저 쪽마다 가벼운 값(글 길이·요약값)으로 서로 다른 쪽만 골라 병합해 시간을 줄인다(시간 제한은 두지 않음 — 앞쪽에만 시간을 쓰게 되므로) | 엔진이 서로 보완하는 내용을 잃지 않게(사용자 11-08) | todo | [pl-67](prd/transform.md#pl-67) | 지금은 대표 엔진 하나 + 다른 엔진의 표 행·키-값 보충. 조각 투표(`fragment_vote` — `fused`·`conflicts.jsonl`)와 교차 확인(`crosscheck` — `meta`) 결과는 아무도 읽지 않음 |

## 적재 (load) — 검색 DB(pgvector)·게시·저장 구조·DB 스키마
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 문서마다 고객·원천 메타를 EDW 조인으로 붙인다 — SFDC 영업 기회(직접 > Task > Event, + 계정 직접 — 같은 단계 동률은 비움) → `Account.Name`, CRMS `RM_CM_PJTLIST`, LAS `LAS.Contract`. 적재 때(`pipeline/load/edw_doc_meta.py`) 원천 스키마 `doc`(`client_edw`·`attrs`·`created_at`)에 쓴다 | 파싱·구조화는 이 값을 안 쓴다 — 매핑이 바뀌어도 다시 파싱하지 않는다. EDW를 못 읽으면 메타 없이 적재(`meta_missing`) — `--replace`로 다시 채움 | done | [pl-29](prd/load.md#pl-29) |  |
| 고객 조인 사슬은 운영 쪽이 고칠 수 있는 설정 파일 `resources/config/edw_chain.yaml` — 서버 사본 자리 `ops.paths.edw_chain_file`(적재·검색 MCP가 함께 읽음), 점검 `python -m pipeline.load.edw_doc_meta --check`. Quote 표는 지금 없음 | 표·칸 이름이 바뀌어도 코드를 고치지 않는다 | done | [pl-29](prd/load.md#pl-29) |  |
| 원천마다 다른 문서 메타는 `doc.attrs`(JSONB) 한 칸에 — 고정 칸은 `doc_id`·`file_path`·`summary`·`created_at`·`client_edw`·`clients_doc`·`content_date`·`embed_model`뿐. 키·EDW 칸·검색 거르기 이름·근거 표시는 사슬 파일이 정하고, `search`는 `attrs: {키: 값}` 거르기와 근거 `attrs`를 낸다 | 원천 칸을 더할 때마다 판(Alembic)·코드를 고치지 않게. 판 0005(GIN 색인) · MCP 계약 — 등급 A | done | [pl-52](prd/load-schema.md#pl-52) |  |
| 검색 DB(gold — pgvector) 표 5개(`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` — 원천 스키마마다 한 벌)와 뷰 1개(`v_chunk_source`)는 Alembic(DB 판 관리 도구)으로만 만든다 | 검색 MCP는 PG만 읽는다. 실행 중 DDL 금지 | done | [pl-07](prd/load.md#pl-07) |  |
| 문서 묶음 하나를 한 트랜잭션으로 적재한다(`pgvector_load load`) — 하나라도 실패하면 전부 되돌림 | 반쯤 들어간 문서가 검색에 보이지 않게 | done | [pl-07](prd/load.md#pl-07) |  |
| 이미 있는 문서는 `doc.file_path`가 같으면 건너뛴다. 바뀐 내용은 `--replace`로 | 내용 지문(sha) 칸이 없어 같은 경로에서 내용이 바뀌어도 건너뛴다(알려진 한계) | done | [pl-07](prd/load.md#pl-07) |  |
| 적재 전에 DB 판을 확인 — 판 기록이 없으면 경고 후 계속, 낮거나 모르는 판이면 종료 2. `--replace`는 판 표(`alembic_version`)가 있는 우리 스키마에서만 | 남의 스키마나 옛 판 DB를 망가뜨리지 않게 | done | [pl-07](prd/load.md#pl-07) |  |
| 처음 쓰는 PG에는 `vector` 확장을 관리자가 한 번 만든다(`CREATE EXTENSION vector`) — 없으면 적재가 멈춘다 | 서버 계정은 보통 우리 스키마 권한만 있다. 절차는 release-and-patch §5-5 ⓪ | done | [pl-07](prd/load.md#pl-07) |  |
| 적재는 더하고 고치기만 하고 지우지 않는다. 원천에서 지워진 문서·실패 문서는 로그에만. 원본 경로는 원천 스키마 5벌을 통틀어 하나 — `--replace` 없이 이미 있으면 건너뛰고, `--replace`면 다른 원천 스키마의 옛 사본을 지우고 옮긴다 | 건너뛴 문서가 지워지면 안 된다. 경로가 바뀐 옛 행은 사람이 지운다 | done | [pl-13](prd/load.md#pl-13) |  |
| 임베딩 없음(`embed` `none` 또는 청크가 있는데 차원 0)이면 적재를 시작할 때 거부한다 — 판 확인·배포·적재 전에 종료 2 | 검색에는 벡터가 필수 | done | [pl-16](prd/load.md#pl-16) |  |
| 묶음의 임베딩 모델(`meta.json` `embed_model`)이 검색 스키마(원천 5벌)에 이미 있는 문서의 모델(`doc.embed_model`)과 다르면 그 묶음 적재를 거부한다 — 아무것도 쓰지 않고 종료 2, 거부는 `applog.pipe_event`에(`stage` `load.embed_guard`) | 모델이 섞이면 검색이 그 원천의 벡터 검색을 거부한다(질의 모델이 하나라서) | done | [pl-51](prd/load.md#pl-51) |  |
| 이름 있는 색인 비교 예시(`index_a`·`index_b`)를 두지 않는다 | 검색 색인은 원천 스키마의 표 하나뿐 | done | [pl-19](prd/load.md#pl-19) |  |
| 게시(publish — 파싱 결과를 Object Storage에 올리고 처리 기록 파일 `publish/silver.jsonl`을 남김 — 적재가 gold `doc` 칸으로) — 대표 `.md`와 엔진별 원결과를 올리고 원본 파일은 올리지 않는다 | 다른 팀은 결과를 Object Storage에서, 위치는 원문 도구로 읽는다 | done | [pl-09](prd/load.md#pl-09) |  |
| 게시는 gold에 이미 있는 원본 키는 올리지 않는다(`--reparse` 목록만 새 이름으로). EDW에는 쓰지 않는다 | 결과를 덮어쓰지 않는다 | done | [pl-09](prd/load.md#pl-09) |  |
| DRM(`skipped_drm`)·실패(`failed`) 문서는 EDW에 쓰지 않고 `output/publish/excluded_<날짜>.md` 보고서에만. 업로드 대상 상태는 `tuning.load.publish.publish_upload_statuses`(기본 ok·partial) | 깨진 결과가 다른 팀에 넘어가지 않게 | done | [pl-09](prd/load.md#pl-09) |  |
| 게시 버킷과 원천 원본 버킷이 같은지는 검사하지 않는다 — `required.publish.publish_bucket`을 다르게 두는 것은 운영자 몫 | 늘 꺼져 있던 검사 | done | [pl-09](prd/load.md#pl-09) |  |
| 게시는 늘 하고 게시·EDW 칸은 settings.yaml `required` 한곳(`publish`·`object_storage`·`edw`) — 서버는 접속 칸, PC(`local`)는 채우지 않음(`dev.local` 게시 폴더·가짜 EDW — op-14) | `run_pipeline`는 문서마다 늘 게시하고 게시 위치·Object Storage·EDW 읽기 계정 칸이 비면 시작을 거부한다(쓰기 계정은 쓰지 않음) | done | [pl-26](prd/load.md#pl-26) |  |
| FAQ를 다시 올리면 gold faq의 문서·청크를 모두 지우고 지금 FAQ 파일 전체를 다시 적재(판을 잇지 않음) | pl-13 "지우지 않음"의 FAQ 예외(등급 A) | done | [pl-41](prd/load.md#pl-41) |  |
| 정형 DB(`struct` 스키마 — 마스터·문서 대장·표·칸)를 두지 않는다. 엔진 구성은 파일만 | 쓰이지 않았다. 서버에 남은 표는 DB 담당자가 정리 | done | [pl-08](prd/load.md#pl-08) |  |
| 문서 대장(`doc_registry`)·숨김(`doc_hidden`)·원천 삭제 처리를 두지 않는다. 서버는 PG가 없으면 로컬 대체 DB로 바꿔 타지 않고 멈춘다 | 빼야 할 문서는 원천에서 지우거나 사람이 SQL로 | done | [pl-12](prd/load.md#pl-12) |  |
| 마스터 표 — 용어집·고객 명부·ID 꼴 CSV 하나(`glossary.csv`)를 검색 PG `<PG_SCHEMA>_master.glossary`로(Alembic 갈래 `master` · `dbtool master load`가 git CSV로 통째로 바꿈). 구조화 고객 판별과 검색이 PG에서 읽고, `gold_version` = `<VERSION>+m<마스터 해시 8자>` | 원본은 git CSV. 대표 결과(silver)는 마스터를 읽지 않는다. 서버는 마스터를 못 읽으면 시작 안 함 | done | [pl-38](prd/load.md#pl-38) |  |
| (잠재 문제) 같은 문서의 다른 판(`s3_key` 다름) 묶기 — 검색 '최신' 질문에서 옛 판이 위로 올 수 있음, 필요해지면 다시 설계 | — | todo | [pl-56](prd/load.md#pl-56) |  |
| 저장 자리 셋 — 파싱 결과 저장본(silver)은 Object Storage 문서 폴더(이름 = `s3_key`로 만든 uuid5), 처리 기록과 검색 DB(gold)는 pgvector | 로컬에는 로그·임베딩 캐시만. 다시 처리하면 같은 폴더를 덮어쓴다(지금 게시는 실행마다 새 날짜 폴더) | todo | [pl-32](prd/load-schema.md#pl-32) |  |
| 같은 `s3_key`가 FileStorageMap에 여러 행이면 `created_at`이 가장 늦은 행만. 새 행은 `file_size`가 같으면 건너뛰고 다르면 같은 `doc_id`로 다시 처리, 밀려난 행은 `applog.superseded_doc_log`에 | 원본을 받지 않고 판별한다(같은 크기로 덮어쓴 경우는 놓침 — 받아들임) | todo | [pl-32](prd/load-schema.md#pl-32) |  |
| DB 스키마 명세는 `docs/architecture/db_schema.md` 하나(검색 DB·EDW·마스터·applog 표의 칸·타입·쓰고 읽는 코드), `test_db_schema.py`가 대조 | 정의를 한 곳에. EDW 쪽 DDL은 DB 담당자 승인 대기 | dev | [pl-25](prd/load-schema.md#pl-25) |  |
| 처리 기록은 검색 DB `doc` 칸(판 0006 — `sha256`·silver 위치·`engines`·`parse_status`·`silver_version`·`gold_version`·`parsed_at`·`loaded_at`), EDW에는 쓰지 않는다 | 기록을 한곳에 둔다(op-17). 서버의 ParsingMeta 기록은 사람이 옮긴다(refactor.md C-107) | dev | [pl-25](prd/load-schema.md#pl-25) |  |
| 문서 키는 원본 경로 하나 — 검색 DB `doc.file_path` = Object Storage 원본 경로 = EDW `s3_key`(청크는 `doc_id`만) | 원본 sha256은 `doc.sha256`(원문 도구 `doc_key`) | dev | [pl-25](prd/load-schema.md#pl-25) |  |
| 원천 시스템별 PG 스키마 5벌(`<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`), 각자 `doc`·`chunk`·BM25 표, `doc_id` 시퀀스는 기준 스키마 하나를 함께 | 원천마다 메타가 다르고 BM25 점수를 섞지 않는다. MCP `source_system` 필수(등급 A) | done | [pl-28](prd/load-schema.md#pl-28) |  |
| 원천 = EDW `AI.FileStorageMap.source_system` 칸 값 하나 — 고르기·구조화·적재(`SFDC`·`CRMS`·`LAS`·`FAQ`, 그 밖은 `other`)·게시가 모두 그 값을 쓴다(목록 파일·manifest로 넘김, PC 폴더는 맨 위 폴더 이름). `faq` 스키마만 `chunk.faq_group` 칸 | 원본 경로에서 원천을 다시 구하지 않는다 — 원천 칸 하나로 정함 | done | [pl-28](prd/load-schema.md#pl-28) |  |
| 게시는 gold `doc`에 같은 원본 키가 이미 있는지 먼저 보고, 있으면 올리지 않는다(`--reparse` 목록만 예외) | 끝난 문서의 결과를 Object Storage에 또 쌓지 않는다 | done | [pl-61](prd/load.md#pl-61) |  |
| 단계 순서는 받기 → 변환(실버 → 골드) → 적재다. 예외 하나 — 실버 대표 결과는 골드 변환 전에 먼저 게시·적재해도 된다(골드 중 프로세스가 꺼져도 실버가 남게). 골드가 실패·중단되었거나 실버까지만 돌린 실행은 상태 기록을 보고 실버만 게시한다 | 사용자 11-08. 이 예외 말고 변환이 적재를 부르는 역방향 호출은 없다 | todo | [pl-68](prd/load.md#pl-68) | 설계 전 — 지금 흐름과 차이 확인 필요 |

## 검색 MCP (mcp) — AI 클라이언트가 부르는 도구 서버(이미지 `mcp-server`)
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| `search` — 질문으로 근거 찾기. 혼합 검색 = 뜻이 비슷한 글(벡터) + 낱말 점수(BM25) + 드문 ID 일치를 순위 합치기(RRF)로 묶음 | 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구. 가중치 벡터 1·BM25 1·ID 2(`tuning.search.weights.*_weight`) | done | [mc-01](prd/mcp.md#mc-01) |  |
| `search` 입력 `k` 기본 8·상한 50, 근거 13칸 `text`·`file_name`·`file_path`·`page`·`line`·`section`·`client`·`contract_no`·`doc_date`·`version`·`superseded`·`chunk_key`·`attrs`(`mcp_server/schemas/evidence.py`), 근거 상태 `evidence_status` found·weak·none. 응답은 20,000바이트까지(낮은 순위부터 줄임) | 근거 상태는 표시만 하고 근거를 빼지 않는다. 질문 핵심어가 근거에 없으면 weak | done | [mc-01](prd/mcp.md#mc-01) |  |
| 검색 저장소는 검색 DB(gold — pgvector) 하나. PC는 SQLite 대역(`pg_standin`) | 서버·PC가 같은 SQL | done | [mc-01](prd/mcp.md#mc-01) |  |
| 질문 + 하드 거르기(`client`·`client_like`·`source_system`·`project_id`·`division`·`service_type`) — 후보 `min(50, max(3k,30))`개에서 범위 안만 남김 | 조건 밖 문서가 근거에 섞이지 않게 | done | [mc-01](prd/mcp.md#mc-01) |  |
| 질문 넓히기 — 용어집으로 BM25 낱말을 더함(동의어 1.0·약어 0.8·약한 것 0.3), 고객 별칭 최대 20토큰 | 동의어·약어로 물어도 찾게 | done | [mc-02](prd/mcp.md#mc-02) |  |
| 고객 2명 이상 비교 질문은 고객별(최대 4명)로 나눠 찾고 번갈아 합침. 집계형 질문은 BM25 가중치 0.2 | 한 고객이 근거 자리를 독차지하지 않게 | done | [mc-02](prd/mcp.md#mc-02) |  |
| 고객 거르기는 EDW에서 붙인 고객(`client_edw`)만 본다(정확 일치, 목록은 OR, `client_like`는 부분 일치) | 답이 고객을 섞으면 안 된다(C6, 11-02). 별칭 그룹은 pl-38 | done | [mc-05](prd/mcp.md#mc-05) |  |
| 이름만 다른 사본은 하나로(사본 묶음) | 같은 문서의 다른 판 문제는 pl-56 행 | done | [mc-05](prd/mcp.md#mc-05) |  |
| 검색기는 문서 키 `doc_key`(= `file_path`)로 읽는다 — 묶음에 없는 칸(`file_sha256` 등)을 읽지 않는다 | 새 묶음으로 검색기를 만들면 실패하던 문제 | done | [mc-10](prd/mcp.md#mc-10) |  |
| 질의 기록은 DB `applog.mcp_log`만(질문·SQL은 `args`, 근거 키) — 파일 기록 없음 | 로그는 Postgres 한 곳(op-13) | done | [mc-13](prd/mcp.md#mc-13) · [mc-09](prd/mcp.md#mc-09) |  |
| 대표 파싱 결과 주소 `rep_uri`(`s3://<bucket>/<key>`)는 원문 도구가 부를 때 gold `doc.silver_bucket`·`silver_key`에서 읽는다(검색 근거 13칸에는 없음) | 처리 기록은 gold `doc` 칸(op-17) | done | [mc-15](prd/mcp.md#mc-15) |  |
| `search` 운영 계약 — `question` 필수, `source_system` 필수·값 하나(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`, `-test` 별칭도) | 운영 명세와 같게. 계약 변경이라 사람 검토(등급 A), 0.2.0 | done | [mc-16](prd/mcp.md#mc-16) |  |
| 거르기 추가 — `FAQ_group`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`·`created_since/until`(시간대 없으면 한국 시간) | 모두 AND, 목록은 OR. 맞는 값이 없으면 오류가 아니라 빈 결과 | done | [mc-16](prd/mcp.md#mc-16) |  |
| 출력 줄이기 — 맨 위 `question`·`evidence[]`·`evidence_status`·`filter`·`scope_docs`, 근거 키 `chunk_key` = `<doc_id>:<seq>` | `index_id`·`subs`·`images`·`notes`·`ms` 등을 지운다(`file_path`는 남김 — 사용자 11-03) | done | [mc-16](prd/mcp.md#mc-16) |  |
| 원문 도구 2개 — `list_doc_fulltext`(목록)·`get_doc_fulltext`(원문). 거르기와 대표 결과 위치·`doc_key`(`sha256`)는 원천 스키마 `doc`에서 | PG를 못 읽으면 `registry_unavailable`. 새 도구라 등급 A, 0.2.0 | done | [mc-17](prd/mcp.md#mc-17) |  |
| 검색이 실행 중에 묶음 파일(`docs.jsonl`·`chunks.jsonl`·`meta.json`)을 읽지 않고 문서 날짜·임베딩 모델·차원을 PG에서 읽는다(판 0004 — gold doc `content_date`(문서에 적힌 날짜)·`embed_model`, `corpus_stat.dim` 지움) | 서버에서 묶음 경로를 맞출 필요가 없어진다. 검색 동작이 바뀌는 일이라 자기 PR + 평가 | done | [mc-19](prd/mcp.md#mc-19) |  |
| `query_edw` — EDW 읽기 전용 SQL(SELECT/WITH 한 문장, 읽기 계정), 1,000행(운영 서버와 같음 — 사용자 11-03)·20초·2 MB 상한 | 정형 숫자는 EDW에서 답한다. 표는 읽기 계정이 볼 수 있는 모든 스키마(시스템 표 제외 — 좁히기는 DB 권한) | done | [mc-06](prd/mcp.md#mc-06) |  |
| `edw_meta` — 정적 자료(`catalog.json`+`columns.jsonl`)로 스키마 → 표 → 칸 찾기, 모르는 이름은 비슷한 이름 제안, 응답 200 KB 상한 | SQL을 쓰기 전에 이름 확인. 표본 값은 내지 않는다 | done | [mc-07](prd/mcp.md#mc-07) |  |
| `parse_document` — 파일 1건(inbox 경로 또는 base64, 100 MB까지 — 두 길 같은 칸 `ops.services.data_parsing.mcp_parse_max_file_mb`, 사용자 11-03)을 파싱 서비스(127.0.0.1:8766, 토큰)로 넘겨 대표 본문·표를 받음. 300초 넘으면 `job_id` | 아직 적재되지 않은 파일을 바로 물을 때 | done | [mc-08](prd/mcp.md#mc-08) |  |
| 스캔 PDF(글자층 20자 미만) 파싱 다시 지원 — 내부망 VLM(`qwen_vlm`)으로 파싱. VLM 설정(주소·모델)이 없으면 빈 결과 + "스캔 PDF — VLM 미설정", 실패면 "스캔 PDF — VLM 파싱 실패" | 클라이언트가 스캔 문서도 글로 받는다. 시간 상한은 작업 제한 시간 하나(쪽 수 상한 없음, 사용자 11-03) | done | [mc-18](prd/mcp.md#mc-18) |  |
| 서버는 `/mcp`(기본 127.0.0.1:8765) 또는 `--stdio`로 뜬다. 내부망 주소만, 0.0.0.0 거부, 루프백이 아니면 `MCP_TOKEN` 필수 + DNS 리바인딩 막기. 서버에서 PG 접속 칸이 비면 시작 거부 | 공용 내부 서비스라 위험한 노출을 거부 | done | [mc-09](prd/mcp.md#mc-09) |  |
| 과부하 보호 — 동시 8개, 대기 32개(동시 × 4) 넘으면 바로 `busy`, 도구당 30초(`parse_document`는 자기 시간 + 10초) | 늘 떠 있게. `/health`는 예열 중 503, 새 적재는 30초마다 확인 | done | [mc-09](prd/mcp.md#mc-09) |  |
| 요청 권한 관리 — 머리글(`Authorization`)로 신원을 확인(agent별 토큰 또는 사내 로그인이 서명한 사용자 증표)한 뒤, DB 권한 표로 그 신원이 볼 수 있는 범위만 돌려준다(`search`·원문·`query_edw` 결과 거르기). 도구 계약은 그대로, 감사 기록에 확인된 신원 | 요청에 적힌 user id·agent id는 꾸밀 수 있어 신원 확인이 먼저다. 부서·고객 담당에 따라 볼 문서가 다르다 | todo | [mc-20](prd/mcp.md#mc-20) | 코드에 없다 — 지금은 공용 토큰 하나로 허용 클라이언트인지만 본다. 방식(agent 토큰·사내 로그인)·권한 단위·검색 DB 거르기 칸은 미정 |
| 질문 유형 단서(`question_type.AGGREGATE_RE`)는 쓰는 값만 가진다 | 쓰지 않는 칸(첫 도구·검색 설정)은 고칠 때 헷갈리게 한다 | done | [mc-21](prd/mcp.md#mc-21) |  |

## 운영 (ops) — 서버 러너(run_pipeline)·실행 관리·종료 정리·계정·모델 가드·설정
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 서버 입구는 호스트의 `run_pipeline.py` 하나 — 상주 컨테이너 안에서 `docker exec`로 일을 시킨다. 이미지 명령은 `parse`·`publish`·`migrate`·`show-stack`·`idle`·`selftest` 등 | — | done | [pl-10](prd/ops.md#pl-10) |  |
| run_pipeline 흐름 — 문서마다 미리 받기 → 파싱 → 구조화+적재 → 게시 → 임시 폴더 삭제, 배치 장벽(앞 묶음이 다 끝날 때까지 기다리기) 없음 | 문서 수천 건을 사람 없이 처리 | done | [pl-10](prd/ops.md#pl-10) |  |
| 새 문서만 처리(목록 − gold `doc` 행) — 파싱 입구는 구현됨(수집 표). 전체 재파싱은 사람이 전체 e2e로만 | 지문이 바뀔 때 전체 자동 재파싱을 하면 밤 시간을 넘긴다 | done | [pl-23](prd/ops.md#pl-23) |  |
| run_pipeline은 지휘만(레인·워커·임시 폴더·`docker exec`) — 대상 목록·끝난 문서·FAQ 순서는 컨테이너 `candidate_pick list`, 받기는 `candidate_ready stage` 한 길(받기 → 중복 → 거르기, 파싱은 받은 파일만), PC도 가짜 대상으로 같은 run_pipeline E2E, 커밋 전 점검 스크립트는 `common/check/` | 같은 판단이 두 곳이면 어긋나고 PC E2E가 서버를 증명하지 못한다(사용자 11-04·11-05) | todo | [rn-05](prd/ops.md#rn-05) | PC 실행 거부(PC는 `pipeline.cli parse`를 바로), 점검은 `deploy/release/lint_changed.sh` |
| 같은 일은 한 곳(파싱 단계 사슬·프로세스 묶음 실행 = `parse_steps.py`, 날짜 조건 `_when` 한 벌), 서버·릴리스 스크립트 이름은 하는 일로, 같은 파일 이름 두 번 없음(보호 파일·공용 모듈 제외) | 같은 일이 여러 곳이면 한쪽만 고쳐진다(사용자 11-04) | done | [rn-06](prd/ops.md#rn-06) |  |
| 여러 벌은 컨테이너 이름·포트로 갈림(데이터 이름에 벌 표시 없음), 파싱 MCP `mcp-data-parsing`·칸 `data_parsing`, 늘 같은 스위치·옛 칸 표 없음, 주석은 목적 한 줄 | 여러 벌이 서로 덮지 않고 설정을 읽기 쉽게(사용자 11-05) | done | [rn-07](prd/ops.md#rn-07) |  |
| 파이프라인 폴더는 ETL 뜻대로 — extract는 고르기·받기·준비만, 엔진 파싱은 `transform/parse/`(엔진 실행 한 파일), 파일 이름은 하는 일로, 요건에 닿지 않는 코드·두 번째 같은 코드는 없음 | 폴더만 보고 단계의 일을 안다(사용자 11-05) | done | [rn-08](prd/ops.md#rn-08) |  |
| run_pipeline 대상 고르기 — 기본은 모든 문서·시작 자리 0(`--filter <키워드>`로 이름을 좁힐 수 있음)·`--start-offset` 뒤 `--skip-done`이 끝난 문서(gold `doc` 행)·영구 뺌(`except_doc_info` `skip`)을 뺀다 | 새벽 배치는 FileStorageMap의 모든 새 문서를 처리한다(사용자 11-05) | done | [pl-23](prd/ops.md#pl-23) |  |
| 새벽 배치는 `ops.nightly.nightly_start_time`·`nightly_max_docs`·`nightly_stop_time` 셋이 모두 있을 때만 돈다(하나라도 비면 안 돎 — 사용자 11-02) — systemd 타이머가 5분마다 `nightly_batch.sh scheduled` → `run_pipeline.py --start-offset 0 --skip-done --max-docs --deadline` | 지금 서버는 비워 둠(꺼짐) — 켜는 것은 사람(C-72) | done | [pl-23](prd/ops.md#pl-23) |  |
| 전체 e2e는 local·dev·prd 셋에서 — 전체 문서 실행은 prd에서만 새 원천별 스키마 이름(새 `PG_SCHEMA`)으로, 옛 gold·`struct` 스키마는 2주 뒤 DB 담당자가 백업하고 지움 | 판 0002가 기준 스키마의 옛 표를 지운다. 사용자 11-02 | todo | [pl-54](prd/ops.md#pl-54) |  |
| 새벽 배치 칸은 `ops.nightly.nightly_start_time`·`max_docs`·`stop_time`(시작 시각·문서 수 상한·마감 시각) 한 벌 — 하나라도 비면 안 돎 | 사용자 11-02 | done | [pl-23](prd/ops.md#pl-23) |  |
| 문서별 순서는 파싱 → silver 게시 → 원본 임시 파일 삭제 → gold. 받기가 뺀 문서(중복·DRM·암호)는 파싱 없이 게시·원본 삭제만(실패 아님) | 게시가 gold를 기다리지 않고(게시 스레드 따로), 원본은 게시가 성공했을 때만 지운다(11-03) | done | [pl-24](prd/ops.md#pl-24) |  |
| gold 실패면 게시한 silver는 남긴다. 파싱·게시·적재 실패는 로그와 `applog.except_doc_info` `error`에 — `doc` 행이 없어 다음 실행이 다시 고른다 | gold는 silver에서 다시 만들 수 있다(11-03) | done | [pl-24](prd/ops.md#pl-24) |  |
| run_pipeline 종료 코드 — 대상 0건 = 0, 실패 있음 = 1, 마감 도달 = 75 | 스케줄러가 실패를 본다(C-33). 실패와 마감이 함께면 1 · 다른 run_pipeline이 도는 중도 75(11-03) | done | [pl-18](prd/ops.md#pl-18) |  |
| 새벽 run_pipeline에 문서 수 상한·마감 시각·겹침 막는 잠금 | `--max-docs`·`--deadline`(11-02) + `run_pipeline.py` 안 `flock` 잠금(`batch_progress/run_pipeline.lock`, 11-03). `TimeoutStartSec=6h`는 마지막 안전판 | done | [pl-18](prd/ops.md#pl-18) |  |
| 레인 3개(light·medium·vlm, 수집 표의 나누기 기준)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴 다른 레인) — `ops.run_pipeline.<레인>_dedicated`·`_shared` 기본 각 1 | 규칙을 표 하나(`pick_lane`)로 모으고 설정으로 조정 | done | [rn-01](prd/ops.md#rn-01) |  |
| vlm 레인 동시 파싱 상한 `ops.run_pipeline.vlm_lane.vlm_lane_max_concurrent_docs` = 2. `staging.staging_max_docs`·`vlm_lane.vlm_lane_max_concurrent_docs`가 1 미만이거나 워커가 없는 레인이 있으면 시작 거부 | GPU 예산을 지키고 끝나지 않을 설정을 막는다 | done | [rn-01](prd/ops.md#rn-01) |  |
| 미리 받기 상한 `ops.run_pipeline.staging.staging_max_docs` = 20, 구조화 워커 `structure.structure_workers` = 2, 중간 대기열 상한 `structure.structure_max_backlog`(기본 구조화 워커 × 2, 0이면 없음) | 구조화가 느릴 때 파싱 결과가 디스크에 쌓이지 않게 | done | [rn-02](prd/ops.md#rn-02) |  |
| 대기열 길이를 상태가 바뀔 때마다 `batch_progress/queue_depth.jsonl`에 한 줄 | 대기열 길이와 구조화 대기 시간의 관계를 잰다 | done | [rn-02](prd/ops.md#rn-02) |  |
| MCP `parse_document`(사람이 기다리는 요청)에 CPU를 먼저 준다 — 일괄 `data-pipeline`과 뗀 전용 컨테이너 `mcp-data-parsing`, cgroup CPU 가중치 최고(cpu_shares 4096 > 1024) | nice는 컨테이너끼리는 효과가 없다 | dev | [rn-03](prd/ops.md#rn-03) | 서버에서 일괄 파싱 중 응답 시간 확인 남음(C-83 ①) |
| MCP 업로드 작업이 있으면 medium 전담 워커를 쉬게 한다(이름 날짜가 어제·오늘·내일인 작업 폴더만 감시) | 5초마다 폴더 전체를 훑던 부담을 줄인다 | done | [rn-04](prd/ops.md#rn-04) |  |
| 프로세스가 끝날 때(정상·오류·SIGTERM) 임시 설정 덮기 파일·PID 기록을 지우고 자식을 끝내 회수(SIGTERM → 10초 → SIGKILL, 종료 143) — `common/core/exitclean.py` 한 곳 | 임시 파일이 쌓이고 soffice 좀비가 남던 문제 | done | [pl-27](prd/ops.md#pl-27) |  |
| EDW 접속 설정은 `common.connections.rdb` 하나(settings `required.edw`) — 읽기 계정(목록·FileStorageMap·메타 사슬·MCP)만 쓴다(EDW에 쓰지 않음 — op-17 · 쓰기 계정 칸 없음) | 같은 값이 설정 블록 넷에 반복되던 것을 없앰. 등급 A | done | [op-03](prd/ops.md#op-03) |  |
| PC 대역 EDW는 sqlite 파일 하나(`valid_env/edw/edw.sqlite`)를 `AI`·`CRMS`·`LAS`·`SFDC`로 붙여 같은 SQL이 돌게 | PC에서 운영 EDW에 접속하지 않는다 | done | [op-03](prd/ops.md#op-03) |  |
| 모델 역할 llm·vlm·embed(OpenAI 호환). 외부 주소는 `dev.models.<역할>.allow_external`이 켜지고 `RUN_ENV=local`일 때만, 서버는 거부. 내부 판정 = 해석된 주소가 사설 IP(또는 `internal_ip_ranges`) + 호스트 접미(`internal_host_suffixes`) | 폐쇄망 밖으로 데이터를 보내지 않는다. 접미 목록에는 전체 호스트 이름이 아니라 상위 도메인을 적어야 맞는다(운영 고침 묶음) | done | [pl-11](prd/ops.md#pl-11) |  |
| 비용 상한 — `dev.models.guard.daily_budget_usd`(외부 모델 하루 지출 $, 기본 0.1 — PC 사용자마다)·하루 장부(`spend_ledger_file` + 날짜, 비우면 `output/_llm_spend/<날짜>.txt`) | PC 호출을 싸게 유지. 응답 캐시·가짜 LLM도 여기 | done | [pl-11](prd/ops.md#pl-11) |  |
| 모델 — 개발 서버부터 내부망 GLM, PC는 OpenRouter | 사용자 11-02 | done | [pl-11](prd/ops.md#pl-11) |  |
| JSON Lines 사건 기록(공통 키·로그 수준·비밀 가림) + DB 감사·성능 로그 — 두 앱 `common.core.jsonlog`, MCP 도구 호출마다 `applog.mcp_log`, 파이프라인 실행·단계 `applog.pipe_run`·`pipe_event`(`dbtool up --target applog`) — 문서 사건 행은 원천·확장자·크기(`source_system` 판 0004·`ext`·`file_bytes`) | 사건·감사·성능을 같은 형식으로 남긴다(코드 #87 병합 — 서버 적용은 C-79·C-80) | done | [op-01](prd/ops.md#op-01) |  |
| 실행 환경 `RUN_ENV`(`required.env.run_env`)는 `local`·`dev`·`prd`만, 어디서나 필수 — `stage`나 모르는 값이면 시작 거부 | `stage`는 `prd`와 똑같이 동작했다 | done | [op-02](prd/ops-settings.md#op-02) |  |
| 서버(`dev`·`prd`)는 가짜 LLM(`dev.fake_llm`)이 켜져 있거나 설정 파일을 못 읽으면 시작 거부 | 서버에서 가짜 답이 도는 것을 막는다 | done | [op-02](prd/ops-settings.md#op-02) |  |
| PC(`local`)는 가짜 대상만 — `dev.local`의 가짜 EDW·게시 폴더·원본 폴더·새 문서 상한을 쓰고, 서버 전용 칸(EDW·Object Storage·서버 게시 버킷)은 비우고 경고, 경로는 저장소 루트 기준 상대 경로 | PC 시험에 EDW·Object Storage·토큰·배포 값이 필요 없게. 사용자 11-04·11-05 | done | [op-14](prd/ops-settings.md#op-14) |  |
| 한 서버에 여러 벌(개발자별) — 코드 폴더 이름 끝 `-<숫자>`(벌 번호)가 컨테이너·compose 묶음·타이머 이름 끝에 붙고, 포트는 벌마다 설정으로(스키마는 함께 씀) | 개발 서버에 개발자마다 컨테이너를 띄움. 사용자 11-04 | done | [op-15](prd/ops-settings.md#op-15) | 밑 이름(컨테이너·묶음)·덧붙일 compose 파일·사슬·홈 자리는 settings.yaml(사용자 11-06) |
| 네 이미지에 개발 도구(sshd·git·uv·ruff·mypy·pytest 등)와 opencode(선택)가 들어 있고, 개발 서버에서 `option.devbox.ssh_port`를 적으면 `data-pipeline`이 SSH 작업 공간(코드 폴더 쓰기 가능·홈 `<루트>/home`)으로 뜬다 — 비우면 지금과 같고, prd는 거부 | 개발 서버 컨테이너 안에서 바로 고치고 시험한다. opencode는 내부망 모델만. 사용자 11-05 | done | [op-16](prd/ops.md#op-16) |  |
| 개발 서버 개인 시험 벌 — 벌 폴더 = 코드 폴더, 원천 `DEV-<숫자>`(dev만 — 원천 스키마를 설정에 따라 만듦), 파싱할 원천 목록은 settings.yaml 맨 위, 처리 기록은 pgvector `doc` 칸 + `applog.except_doc_info`(EDW `ParsingMeta`는 안 씀) | 개발자마다 자기 문서만 파싱·검색해 시험한다. 사용자 11-06 — 0.3.0 | todo | [op-17](prd/ops.md#op-17) | 규칙 1~5·8·9·11·12·14~21 반영(벌 폴더 = 코드 폴더, 파싱할 원천 목록 `required.source.source_systems`, 원천 = FileStorageMap `source_system` 칸, 처리 기록 `doc` 칸 판 0006·`except_doc_info` 판 0003(+ `file_ext`·`file_size` 판 0004), EDW 쓰기 없음 · DB 담당 검토용 `dbtool up --sql`). 규칙 6·7 DEV 원천 스키마 `<기준>_dev_<숫자>`(dbtool up이 설정·DB의 DEV 스키마를 만들고 올림, 적재는 없으면 멈춤) 반영. 규칙 7의 검색 MCP 원천 목록·10(MCP `search`·원문 도구의 `DEV-<숫자>` — dev·local만, prd는 거부) 반영. 남은 13(ParsingMeta 기록 옮기기 — 사람, refactor.md C-107) 마스터 표 `glossary` 판 0002_master 반영 — 서버 마스터 판 올리기·실명 자료 옮기기(`common.store.master convert`)는 사람(refactor.md C-108). |
| 설정은 settings.yaml 하나 — `settings.sample.yaml`에 모든 키가 기본값과 함께(`python -m common.config.sample`로 생성) | — | done | [op-05](prd/ops-settings.md#op-05) |  |
| 배치 — 맨 위 `required`(필수·비밀) → 역할 절 7개(환경마다 정하는 값) → `tuning`(거의 안 바꾸는 값 — 분류 제목, 11-04). 옛 배치·옛 자리·모르는 칸은 시작 거부(칸 이름만 알림 — rn-07) | sample과 실제 파일의 차이를 줄였다 | done | [op-08](prd/ops-settings.md#op-08) |  |
| 설정 이관은 옛 배치 settings.yaml → 새 배치만 | 운영 서버는 0.1.0(settings.yaml 하나). 사용자 11-02 | done | [op-08](prd/ops-settings.md#op-08) |  |
| 하드코딩 0 — 설정 값은 settings.yaml이나 이미지 기본값 표(`settings.py`)에서만, 호스트 셸은 `load_settings.sh`가 준 값만, PG 자동 찾기 없음(PG 접속 필수) | 한 곳을 바꾸면 나머지가 어긋나던 문제. 남은 복사본 있음 | done | [op-09](prd/ops-settings.md#op-09) |  |
| 환경마다 다른 경로·접속은 settings.yaml 필수(코드 기본값 없음) — 컨테이너 안 경로는 이미지 기본값 표 하나만, 호스트 `PATCH_CODE` 기본값 없음 | 사용자 11-02 | done | [op-09](prd/ops-settings.md#op-09) |  |
| 은퇴한 설정(`common.paths.korean_font`·`eval_sets_dir` 등)은 없다 — 남아 있으면 시작 거부 | 쓰지 않는 칸 | done | [pl-21](prd/ops-settings.md#pl-21) |  |
| run_pipeline 명령은 아무도 안 읽는 env(`FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`)를 넘기지 않는다 | C-51 | done | [pl-30](prd/ops-settings.md#pl-30) |  |
| 서버 러너의 컨테이너 명령은 한 도우미가 만든다(`docker exec` · `PYTHONPATH` · 라이브러리 env 같게) · 게시·구조화가 시간 초과면 그 문서의 컨테이너 안 프로세스도 끈다 · 벌 번호 규칙은 한 곳 · 스캔 회전 정책은 설정 칸 하나를 컨테이너가 직접 읽는다 · 레인 분류는 받기 단계 안에서(문서마다 따로 `docker exec` 없음) · 분류 캐시는 덧붙여 쓴다 | 명령마다 env가 다르면 같은 코드가 다르게 돈다. 끄지 않은 프로세스는 다음 문서와 CPU·메모리를 다툰다 | todo | [rn-09](prd/ops.md#rn-09) | 한 도우미·시간 초과 정리는 반영. 스캔 회전 값이 run_pipeline → `stage --no-scan-rotate` → `stage_batch(scan_rotate)` → `filter_and_rotate --no-scan-rotate` 네 겹으로 전달. 분류는 문서마다 `docker exec`, 캐시는 문서마다 파일 전체를 다시 씀 |
| 문서 1건의 반복 비용을 줄인다 — 원본 sha256은 한 번만 구하고 넘겨 씀 · 적재의 스키마 확인 질의는 하나(UNION) · 설정 파일은 프로세스마다 한 번 읽음 · `--set` 처리(`setarg.apply`)는 무거운 import 전에 | 문서 수천 건에서 같은 일을 되풀이하지 않는다 | todo | [rn-10](prd/ops.md#rn-10) | sha256은 받기가 한 번 구해 manifest로 넘기고 중복 제외·거르기·파싱·구조화·게시가 씀 — 대표 결과(`contract.source_record`, 핸드오프 파일)만 다시 구함. `pgvector_load`가 원천 스키마마다 따로 묻는다. 측정 전 — 줄일 크기는 `perf_report`로 먼저 잰다 |
| 코드가 읽지 않는 설정 칸은 없다 — 지운 칸은 판 올리기 안내(upgrade-guide)에 적고 서버 `settings.yaml`에서도 지운다. PC 덮어쓰기 설정 파일 도구는 없다 — 한 번만 다른 값은 모든 진입점(`mcp_server.main`·`ask` 포함)의 `--set` | 사용자 11-08 | done | [op-18](prd/ops-settings.md#op-18) |  |

## 테스트·평가 (test) — 변경을 어떻게 증명하나
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 시험 층 둘 — `tests/server/`(이미지 안 반입 시험, `python -m pipeline.cli selftest`, 네트워크 없음)와 `tests/general/`(PC 전용 — PG·Docker·느린 것) | 반입 판정은 폐쇄망 이미지 안에서 돌아야 한다 | done | [e2-02](prd/test.md#e2-02) |  |
| 기준선 — 바꾼 뒤 시험 결과가 기준선보다 나빠지면 안 된다(값은 앵커) | 지금 기준선은 11-04 selftest(pytest 수는 다시 잴 것 — 앵커) | done | [e2-02](prd/test.md#e2-02) |  |
| 알려진 실패 목록(`deploy/release/known_fail.txt`·`GENERAL_KNOWN_FAIL`) — 통과하면 "XPASS — 지울 수 있음" 경고 | 새 실패를 목록에 넣는 것은 고장을 숨기는 일 — 사람 승인 필요 | done | [e2-02](prd/test.md#e2-02) |  |
| PC 시험 자식 프로세스는 개발자 `settings.yaml` 대신 시험 전용 바탕(`run_env: local`만)을 쓴다 | 공용 개발 PG를 건드리지 않게 | done | [e2-02](prd/test.md#e2-02) · [e2-11](prd/test.md#e2-11) |  |
| 이미지 반입 관문 — `build_ship.sh`로 빌드하고 `selftest_gate.sh`가 종료 코드가 아니라 `[판정]` 줄로 판단(알려진 실패 밖 FAIL 0) | 서버는 반입 시험을 통과한 이미지만 받는다 | done | [e2-08](prd/test.md#e2-08) |  |
| 코드만 바뀌면 코드 폴더 바꾸기(이미지는 그대로) | 이미지를 다시 만들지 않는다 | done | [e2-08](prd/test.md#e2-08) |  |
| PC 일반 시험의 알려진 실패 0(`GENERAL_KNOWN_FAIL = {}`, `known_fail.txt` 빔) — 시험은 공용 PG를 읽지 않고, 지운 모듈의 시험은 없다 | 리팩토링 전부터 있던 실패를 없앴다 | done | [e2-11](prd/test.md#e2-11) |  |
| 옛 오버레이 패치 흔적이 없다 — 버전 읽기(`common/core/fingerprint.py`)에 `common/PATCH_VERSION` 후보 없음, 읽는 곳 없는 `deploy/docker/IMAGE_BASE` 없음 | 없어진 길만 읽던 것이 남으면 헷갈린다 | done | [e2-21](prd/test.md#e2-21) |  |
| 지시서 폴더 찾기(`paths.resolve_agent_dir`)는 있는 폴더 갈래만 본다 | 없는 폴더를 찾는 갈래는 헷갈린다 | done | [e2-15](prd/test.md#e2-15) |  |
| PC 스모크 — 문서 2~3건으로 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색(README §4-4) | 릴리스 전에 사슬 전체를 증명 | done | [e2-01](prd/test.md#e2-01) |  |
| PC Docker 스모크(`valid_env/docker/smoke_test.sh`)가 검색까지 통과한다 | 이미지 사슬 전체를 PC에서 증명 | todo | [e2-13](prd/test.md#e2-13) | mc-10을 고친 뒤 다시 돌리지 않았다 |
| 시험 자료 `valid_env/` — 문서 `object_storage/{SFDC,CRMS}/<uuid>/<파일>`, 합성 EDW `edw/` | 서버와 같은 배치. 서버 반입 시험은 자료를 임시 폴더에 만들어 쓴다 | done | [e2-09](prd/test.md#e2-09) |  |
| 배포 뒤 검색 스모크 — `mcp_smoke`로 도구 목록·`search` 근거 1건 이상·근거 칸 확인 | 서버에서 검색이 실제로 답하는지 한 번에 본다 | done | [e2-04](prd/test.md#e2-04) |  |
| 답변 점검(PC 전용) — `validation/e2e/answer_gen.py`가 `rag_qa` 에이전트로 `search`·`edw_meta`·`query_edw`를 불러 답하고 인용을 규칙으로 점검 | MCP는 근거만 준다. 유료 호출은 예산 장부를 거친다 | done | [e2-05](prd/test.md#e2-05) |  |
| answer_gen 인용 점검은 오류를 구분하고, JSON으로 못 바꾸는 값·객체가 아닌 답·다시 직렬화를 처리한다 | 시험 `tests/general/e2e/test_answer_gen.py` | done | [e2-19](prd/test.md#e2-19) |  |
| 분류 수용 보고서(개발 서버) — 사람 정답 CSV(`s3_key`·정답 분류)와 비교해 원천·라벨별 일치율·혼동표 | 회사 데이터라 git 밖. 통과 기준은 첫 결과를 본 뒤 정한다 | todo | [e2-20](prd/test.md#e2-20) |  |
| 검색 점검 페이지 `validation/search_ui`(기본 포트 8790, MCP `127.0.0.1:8765/mcp`) | 사람이 브라우저로 근거를 본다 | done | [e2-07](prd/test.md#e2-07) |  |
| PC 평가 도구는 검색 점검 페이지·답변 점검 둘뿐 | PC 전용 설정 약 50개의 관리 비용 | done | [e2-10](prd/test.md#e2-10) |  |
| 요건에 닿지 않는 함수·코드(시험만 부르는 것 포함)는 없다 | 죽은 코드 비용. MCP 도구 이름·입출력은 그대로 | done | [e2-17](prd/test.md#e2-17) · [e2-18](prd/test.md#e2-18) |  |
| 배포 판정 시험의 DB 시험은 진짜 pgvector로 돈다 — PC는 시험 pgvector 컨테이너(없으면 띄움), 개발 서버(dev)는 쓰는 시험까지(임시 스키마 `test_*`를 만들고 지움), 운영 서버(prd)는 읽기만(접속·vector 확장·판 번호·표·색인·검색 1회). sqlite 대역 없음 | 대역과 실 DB 차이로 판정이 틀리지 않게. 운영 DB에는 쓰지 않는다(사용자 11-08) | todo | [e2-22](prd/test.md#e2-22) | 지금 서버 판정 시험은 sqlite 대역(`common/store/pg_standin.py`)으로 돈다 |
| 모듈 경계 점검은 import 규칙(앱 사이·단계 방향·`validation`/`tests` import 금지·routers)만 코드 분석으로, 설정 env 읽기 규칙(⑩⑪)은 글자 검색으로 본다 | 점검 코드를 줄인다(사용자 11-08) | done | [e2-23](prd/test.md#e2-23) | 글자 검색은 앱 코드(common·pipeline·mcp_server)만 본다 |

## 문서·릴리스 (doc) — 문서 배치·버전·이미지·서버 설치
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID | 비고 |
|---|---|---|---|---|
| 요건은 `docs/PRD.md` + `docs/prd/<카테고리>.md`, CLAUDE.md는 규칙·명령만, 지난 기록은 `docs/history/` | 겹치는 문서가 많고 요건이 흩어져 있었다 | done | [do-04](prd/doc.md#do-04) |  |
| PRD는 카테고리(수집·변환·적재·검색·운영·시험·문서)별 표, 행 = 되어야 할 모습 하나, ID 그대로 | 사람이 요건을 바로 이해하게 | done | [do-04](prd/doc.md#do-04) |  |
| 용어집 `docs/INDEX.md` `## Glossary` — 약어·옛 용어 대응, CLAUDE.md에는 링크 한 줄 | 옛 용어가 주석·기록에 아직 나온다 | done | [do-02](prd/doc.md#do-02) |  |
| `refactor.md`는 병합 결과와 맞다 — C 항목은 PRD 링크, 검토자 = 사용자(등급 A) | 낡은 줄이 요건을 흐린다 | done | [do-03](prd/doc.md#do-03) |  |
| `refactor.md`는 `docs/refactoring/`에 있다 | 루트에는 입구 파일만 | done | [do-01](prd/doc.md#do-01) |  |
| 버전은 루트 `VERSION` 하나(SemVer), 태그 `v<버전>` + 릴리스 노트 | 이미지 태그와 DB 버전 표기가 같은 값을 쓴다 | done | [op-04](prd/doc.md#op-04) |  |
| 코드 없는 실행 이미지(`data-pipeline-runtime`·`mcp-server-runtime`)에 코드 폴더를 `/app/deploy`로 읽기 전용 마운트 | 개발 서버에서 이미지를 다시 만들지 않고 코드만 바꿔 시험 | done | [op-06](prd/doc.md#op-06) |  |
| 시작 검사 `runtime_entry.sh` — 코드 폴더가 없거나 의존성 지문(`DEPS_HASH`)이 다르면 종료 2, 이미지 판·코드 커밋을 한 줄 기록 | 의존성 어긋남이 나중에 조용한 오류로 터지지 않게 | done | [op-06](prd/doc.md#op-06) |  |
| 개발 → 운영 굽기 `bake_prod_image.sh` — 개발에서 쓴 실행 이미지 + 시험한 코드 폴더로 `Dockerfile.bake`(네트워크 없이), 반입 판정 뒤 저장·분할 | 운영에는 개발에서 시험한 그대로 올라간다 | done | [op-07](prd/doc.md#op-07) |  |
| 운영(prd) 이미지에 settings.yaml(비밀 포함)도 굽는다 — 🔒 검토 등급 A(비밀 처리) | 이미지 파일 = 비밀(반입 경로만), 키를 바꿀 때마다 다시 굽기. 사용자 11-02 | todo | [op-12](prd/doc.md#op-12) |  |
| 서버 설치 길은 하나(README §5-0·§5-3). 컨테이너 도구는 셸 env > `ops.host.container_cli` > podman > docker. 이미지는 `load.sh`로(45 MB 조각) | 문서마다 절차가 달랐다. 서버 기본 도구는 podman | done | [op-10](prd/doc.md#op-10) |  |
| 판 올리기·되돌리기는 upgrade-guide 하나 — 밤 타이머 멈춤 → DB·벌 폴더 백업 → 새 코드 덮어쓰기 → `migrate up` → 점검, 되돌릴 땐 백업 복원 | DB·EDW·전체 재처리가 함께 바뀐다 | done | [op-10](prd/doc.md#op-10) |  |
| 일회성 작업 컨테이너 없음 — 운영 작업·`dbtool`·`migrate`는 상주 `data-pipeline`에 `exec`, 이미지 점검(`docker run --rm … selftest`)만 일회성 | 사용자 11-02 | done | [op-10](prd/doc.md#op-10) |  |
| 사람 정답 폴더 칸(`GOLD_DIR`·이미지 `gold_mount`) 없음 — 점검기 정답 폴더 점검도 없음 | 사용자 11-04 — 상주 컨테이너에 붙지 않아 점검이 늘 건너뛰어짐 | done | [op-11](prd/doc.md#op-11) |  |
| 서버 루트 = 코드 폴더(예 `/home/sbl/sbl_data_parsing-main-1/`) — `settings.yaml`·`edw_chain.yaml`·`output/`가 그 안, 새 판은 덮어쓰기(검색 PG는 공유), `/srv/rag`·`env/`·`code/live` 없음 | 사용자 11-04 | done | [op-13](prd/doc.md#op-13) |  |
