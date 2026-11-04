# sbl_data_parsing — PRD

목표: 폐쇄망 회사 문서에서 출처 달린 근거를 찾는다 — 파싱 → 구조화 → 적재(pgvector) → 검색 MCP, 서버와 PC에서 같게.
행 = 요건 하나(끝난 것 포함) — 칸은 요건(무엇을, 어디서) · 기준·이유 · 상태 · ID. ID 하나가 여러 행에 나올 수 있다(상세는 ID 링크의 앵커). 상태: todo · dev · done.

## 지금 진행 중
- pl-25 DB 스키마 명세 — dev: 검색 DB(gold)·마스터·applog는 구현됨, EDW 쪽 DDL(ParsingMeta 칸 정리)은 DB 담당자 승인·실행 대기(refactor.md C-76).
- 열린 요건(todo): 저장 구조 [pl-32](prd/load-schema.md#pl-32) · 확장자 `.hwp` [pl-45](prd/transform.md#pl-45) · 그림 부가 기능 줄이기 [pl-05](prd/transform.md#pl-05) · 전체 e2e [pl-54](prd/ops.md#pl-54) · `gold_status` 칸 쓰기 [pl-55](prd/ops.md#pl-55) · pl-46 남은 정리 [pl-53](prd/transform-cleanup.md#pl-53) · prd 이미지에 settings.yaml 굽기 [op-12](prd/doc.md#op-12) · 판 묶기(잠재 문제) [pl-56](prd/load.md#pl-56).
- 서버 확인만 남음(dev): parse_document CPU 우선 [rn-03](prd/ops.md#rn-03).
- 시험 정리(todo): [e2-13](prd/test.md#e2-13) · [e2-15](prd/test.md#e2-15) · [e2-20](prd/test.md#e2-20) · [e2-21](prd/test.md#e2-21).

## 수집 (extract) — 서버에서 문서 목록을 정하고 받아 오기까지
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 문서 목록은 EDW 표 `AI.FileStorageMap`에서 읽는다(`id`·`s3_key`·`original_filename`·`file_size`) — 서버 러너 `run_docs.py`가 파일 이름 키워드(`--filter`)로 거르고 작은 파일부터 | 목록의 기준은 EDW다. Object Storage를 직접 훑지 않는다 | done | [pl-01](prd/extract.md#pl-01) |
| 새 문서만 고른다 — 목록에서 EDW `AI.ParsingMeta`에 끝난 행(`ok`·`partial`·`skipped_dup`)이 있는 원본 키(`s3_key`)를 뺀다. 파싱 입구(`pipeline/cli.py` `_unparsed`)가 EDW를 읽기 계정으로 한 번 읽음 | 끝난 문서를 다시 파싱하지 않는다. `not_parsed`·`skipped_disk_cap`·실패·기록 없음은 다시 고른다(사용자 11-01). 서버에서 EDW를 못 읽으면 시작하지 않는다(종료 4) | done | [pl-23](prd/ops.md#pl-23) |
| 파일은 Object Storage 버킷에서 `s3_key`로 받는다. 파싱 입력은 폴더 또는 목록 파일(`rdb:csv:<경로>`) 둘뿐 | 길을 하나로 | done | [pl-01](prd/extract.md#pl-01) |
| 미리 받기(warm) — `run_docs`가 파싱보다 앞서 문서를 최대 20개(`ops.run_docs.warm`)까지 받아 임시 폴더(`_warm`)에 둔다 | 다운로드를 기다리느라 파싱 워커가 놀지 않게. 받기 실패면 파싱 때 직접 받는다 | done | [pl-01](prd/extract.md#pl-01) |
| 병렬 다운로드 — 목록 파일의 여러 파일을 동시에 받는다(`source warm`·`rdb:csv` 받기 모두 `pipeline.extract.source.fetch_workers` — 기본 1개, 11-04에 미리받기 칸을 합침) | 큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 안 쓴다 | done | [pl-48](prd/extract.md#pl-48) |
| 서버 러너도 병렬로 받는다 — 받기 워커 `ops.run_docs.warm_workers`(기본 2)개. 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리) | 미리 받기 상한 `ops.run_docs.warm`(받는 중 포함)과 함께 작동 — 빈자리가 없으면 워커가 있어도 받지 않는다 | done | [pl-48](prd/extract.md#pl-48) |
| 레인 나누기 — 받은 직후 셋으로. **vlm**: 스캔 PDF(첫 3쪽 글자 평균 300자 미만)·그림 많은 오피스(내장 그림 8개 이상 또는 800 KB 이상)·pptx·ppt·검사 목록 밖 형식(mht·mhtml·이미지 등). **medium**: 검사한 pdf·오피스 중 가벼운데 큰 파일(docx·doc 300 KB, xlsx·xls·xlsm 500 KB, pdf 1 MB 이상). **light**: 글자형(txt·hwp·hwpx·csv·eml·msg·html)과 나머지 | 그림 읽는 모델(VLM)이 필요한 무거운 문서가 가벼운 문서를 막지 않게 — 레인마다 전담·공유 워커, vlm은 동시 2개(GPU), light는 CPU 부하 대기를 건너뜀(`run_docs.py` `classify_doc`, `docflow_probe.py`) | done | [rn-01](prd/ops.md#rn-01) |
| 완전히 같은 파일(sha256 같음)은 한 번만 파싱하고 결과를 재사용한다. 문서는 S3 키마다 따로 둔다 | 비싼 파싱을 중복하지 않는다. 키마다 메타(고객 등)가 달라 문서는 따로. 남길 사본: 사본 표시 없는 이름 → 최신 → 큰 파일(`dedup.py` `_rep_select`) | done | [pl-02](prd/extract.md#pl-02) |
| 회전 바로잡기 — 켜면(`pipeline.extract.prepare.rotate`, 기본 꺼짐) 이미지·스캔 PDF 쪽마다 4방향(0·90·180·270도) OCR 점수를 스레드 4개로 동시에 재 가장 높은 방향으로 돌린다(같으면 0도). 기록 `rotation.csv` | 돌아간 스캔은 엔진이 읽지 못한다. 꺼져 있으면 회전용 OCR을 하지 않는다 | done | [pl-02](prd/extract.md#pl-02) |
| DRM·암호 파일 감지 — 감지해서 표시만(`skipped_drm`) | 복호화는 흐름 안에서 하지 않고 수동 명령(`python -m pipeline.extract.secure_docs decrypt`)으로 | done | [pl-02](prd/extract.md#pl-02) |
| 압축 파일은 지원하지 않는다고 표시 | — | done | [pl-02](prd/extract.md#pl-02) |
| FAQ 원천 — 질의응답 엑셀을 행 단위로(시트 = FAQ 묶음, 행 하나 = 청크 하나). `FAQ/<uuid>/<파일>`을 FileStorageMap에 등록 | 질의응답을 문서 통째가 아니라 질문 하나 단위로 찾는다 | done | [pl-39](prd/extract.md#pl-39) |

## 변환 (transform) — 파싱·대표 결과 고르기·그림·구조화
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 파일 형식마다 엔진 구성 파일(`resources/config/pipeline_stack.json`)에 적힌 엔진을 **모두** 돌린다(하나씩 차례로 시도하지 않음) | 모든 형식을 잘 읽는 파서는 없다. 서버·PC가 같은 파일을 쓰고, 바꿀 때는 그 파일을 고쳐 코드 폴더를 바꾼다. 파일을 못 읽거나 모양이 틀리면 시작하지 않는다(종료 2) | done | [pl-03](prd/transform.md#pl-03) |
| PDF는 두 갈래 — 글자층이 쪽당 평균 20자 미만이면 스캔(`.pdf_image` → VLM 엔진만), 아니면 글자 PDF(`.pdf_text` → pymupdf·kreuzberg) | 스캔 PDF는 글자 엔진이 못 읽는다. 판정은 `_types.json`에 저장해 다시 쓴다 | done | [pl-03](prd/transform.md#pl-03) |
| 지원 형식 = 구성의 형식 키 43개(목록은 앵커). `.hwp`·압축(zip)은 미지원 | 구성 파일이 정본 | done | [pl-03](prd/transform.md#pl-03) · [pl-42](prd/transform.md#pl-42) |
| 엔진은 문서마다 동시에, 엔진마다 따로 떨어진 자식 프로세스 | 엔진 하나가 죽어도 다른 엔진을 막지 않는다 | done | [pl-22](prd/transform.md#pl-22) |
| 시간 제한 = 쪽 수 × 10초(글자 엔진)·× VLM 호출 제한 `common.models.vlm.timeout`(180초, VLM 엔진), 엔진 첫 문서는 최소 60초, 여기에 시작 여유 10초. 넘으면 두 배로 한 번 더, 그래도 넘으면 실패 기록 | 큰 문서도 쪽 수만큼 시간을 받는다 | done | [pl-22](prd/transform.md#pl-22) |
| 그림 글자 인식 엔진(OCR, `rapidocr_ko`)은 파싱에 돌지 않는다 — 이미지·스캔은 VLM만. 일괄 실행 엔진은 낮은 우선순위(nice +10) | OCR은 VLM과 겹치고 느리다. 검색 서비스 자원을 덜 뺏는다 | done | [pl-22](prd/transform.md#pl-22) |
| VLM 처리 한 길 — 엔진 `qwen_vlm`·쪽 VLM·그림 VLM이 같은 호출(`pipeline/shared/vlmcall.py`)과 같은 설정: 동시 수 `common.models.vlm.concurrency`(문서 하나 안 4)·`max_concurrency`(전체 합 8), 호출 1건 제한 `timeout`(180초)·재시도 `retry`·`extra_body`(생각 끄기 등), 해상도 `extract.ocr.dpi`(150), 쪽 상한 `transform.vlm.page_max` | 공유 VLM 서버를 넘치게 하지 않는다. 경로마다 손잡이·요청 모양이 달라 같은 설정이 일부에만 먹던 것을 없앤다(사용자 11-04) | done | [pl-43](prd/transform.md#pl-43) |
| 확장자 추가 1차: `.jpeg`·`.tif`·`.tiff`·`.bmp`(`.jpg`와 같은 엔진), `.mhtml`(`.mht`와 같음), `.hwpx` 시험 | 형식마다 임시 견본으로 파싱 시험(`test_ext_formats.py`) | done | [pl-42](prd/transform.md#pl-42) |
| 확장자 추가 2차: `.docm`·`.pptm`·`.rtf`·`.csv`·`.tsv`·`.md`·오픈문서·서식 파일·`.json`·`.xml`·`.log`는 끝, `.hwp`만 남음(실제 `.hwp` 문서로 시험한 뒤 더함) | 엔진 파일은 그대로 두고 등록부(`registry.py`)의 "엔진별 추가 확장자" 표에 더해 엔진 지문을 지킨다. `.json`·`.xml`·`.log`는 글 그대로. 사람 검토(등급 A) | todo | [pl-45](prd/transform.md#pl-45) |
| 대표 결과 고르기(represent): 엔진 결과 중 정확하고 풍부한 것을 대표로 고르고, 줄 단위 투표로 합치고, 엔진 사이 라벨·값을 서로 확인한다(`represent.py`·`fuse.py`·`crosscheck.py`) | 엔진마다 결과가 다르다. 다음 단계로 넘기는 글은 가장 정확해야 한다 | done | [pl-04](prd/transform.md#pl-04) |
| 표·기호 다듬기 — 여러 엔진의 표를 본문 제자리에 넣고(`table_inline.py`), 표준 표·윗첨자 `^`·아래첨자 `_`, 파싱 품질 점검(`parse_qa.py`) | 표가 문서 끝에 따로 붙으면 검색 근거가 끊긴다 | done | [pl-04](prd/transform.md#pl-04) |
| 글자 PDF 속 스캔 쪽만 쪽 전체를 VLM으로 읽어 채운다(회전된 쪽·숨은 글자 겹친 쪽 각각 최대 20쪽) | 스캔 쪽 몇 장 때문에 스캔용 엔진을 통째로 돌리지 않는다 | done | [pl-22](prd/transform.md#pl-22) |
| 메일 첨부 — `.eml`·`.msg`의 첨부를 깊이 1·20 MB·10개까지 파싱해 본문에 `[첨부 <파일명>]` 절로 붙이고, 인용 스레드는 접는다(`attachments.py`) | 메일의 핵심 내용이 첨부에 있는 경우가 많다 | done | [pl-36](prd/transform.md#pl-36) |
| 그림 근처 맥락 — 캡션·본문 언급을 연결하고 값이 맞는지 표시한다(`context.py`) | 그림 설명을 본문과 함께 찾게 한다 | done | [pl-37](prd/transform.md#pl-37) |
| 그림 설명 — 그림마다 VLM 한 번(문서당 최대 20개, 짧은 변 64 px 미만은 뺌). 차트 XML·벡터 차트 값은 VLM 없이, 슬라이드·도형은 soffice로 그려 읽는다 | 차트·도식에는 글자 추출이 놓치는 값이 있다 | todo | [pl-05](prd/transform.md#pl-05) |
| 그림 부가 기능 줄이기 — 화살표·겹침·도형 연결·Mermaid 따로 만들기를 VLM 한 번의 종류별 출력(도표 Mermaid·표 HTML·차트 값)으로 | 코드는 아직 부가 기능을 따로 만든다(`figures/figures.py`). 대표 결과 지문 p1이 바뀐다 | todo | [pl-05](prd/transform.md#pl-05) |
| 청크(검색 단위 조각) 나누기 — 구성의 `chunk`(지금 `structure` — 800자, 제목 기준, 표는 통째). 큰 표 25행씩 나누기는 `CHUNK_TABLE=rows`일 때만 | 검색은 출처가 달린 짧은 조각 단위로 한다 | done | [pl-06](prd/transform.md#pl-06) |
| 문서 요약 = 앞부분 300자 발췌. 본문 고객(`clients_doc`)은 명부 이름·별칭이 2번 이상 또는 제목·첫 400자에 나온 것 | 요약은 지어내지 않는다 | done | [pl-06](prd/transform.md#pl-06) |
| 임베딩(검색용 숫자 벡터) — 내부망 `api`(`required.embed`의 주소·모델)만(시험은 `none`) | 폐쇄망 안 모델 하나로 질의·문서를 같게 | done | [pl-06](prd/transform.md#pl-06) |
| 분류 — 적재 때 gold에 넣기 전 SFDC·LAS 문서에 종류 라벨 `doc_class`(SFDC 5종·LAS 7종). 근거 = gold `doc.attrs`의 분류 힌트 키(사슬 파일 `edw_chain.yaml` — 적재 때 EDW 조인) + 대표 결과 .md 앞 8,000자 | 운영 분류와 결과가 같게 — 지시문·사용자 쪽 글 운영 글자 그대로, 내부 모델·`llm.chat`, 집합 밖·장애는 그 문서의 적재 실패(다음 실행에 다시), 재시도·수동 명령 없음, 이미 있는 라벨 안 덮음 | done | [pl-33](prd/transform.md#pl-33) |
| 안 쓰는 엔진·`ocr_vlm`·`vlm.model_alt` 지우기 | 엔진 목록의 정본은 등록부. `docx2python`은 남김. 등급 A | done | [pl-31](prd/transform-cleanup.md#pl-31) |
| 대표 결과 다시 읽기(P2·P3)·스캔 중복 제거·렌더 OCR 신호 지우기 | 대표 결과는 융합 결과를 그대로 쓴다. 등급 A | done | [pl-34](prd/transform-cleanup.md#pl-34) |
| 지문에 영향 없는 잔재(문서 단위 병렬 실행기·자동 재파싱 스위치·그림 이어 하기) 지우기 | 처리는 새 문서만 고르는 증분 하나 | done | [pl-35](prd/transform-cleanup.md#pl-35) |
| 0.2.0 지문 배치 정리 — 안 쓰는 엔진·묶음 계약·OCR 대체 길·로컬 임베딩·첫 이관 호환 코드·ADK 장치를 한 번에 지운다. 모델 호출은 `llm.complete` HTTP 한 길 | 지문이 바뀌는 정리를 서버 재처리 한 번에 모은다. 등급 A. 남은 것은 [pl-53](prd/transform-cleanup.md#pl-53) | done | [pl-46](prd/transform-cleanup.md#pl-46) |
| 엔진 지문(p0) 범위 = 엔진 폴더 전부(`pipeline/extract/engines/**/*.py` + `run_all.py`) | 이름과 폴더가 다른 엔진(html_stdlib·msg_extract·rapidocr_ko·office)을 고쳐도 지문이 바뀌게. 등급 A | done | [pl-47](prd/transform-cleanup.md#pl-47) |
| 같은 결과로 덜 읽고 덜 띄우기 — 명부·사전·원본 해시·매니페스트·엔진 지문을 한 번만, 엔진 결과 한 번에 쓰기, 1건 중복 확인 자식 없이 | 결과는 바이트 그대로. 등급 A | done | [pl-49](prd/transform-cleanup.md#pl-49) |
| 층 지문 범위 바로잡기 + 단계 방향 자동 점검 — 결과를 바꾸는 파일은 층 목록에, 기록·DB 표 정의는 지문 계산에서 뺌. extract → transform → load 방향을 자동 점검 | 빠지면 고쳐도 옛 결과를 다시 쓰고, 넘치면 상관없는 수정에도 재처리 경보가 남. 등급 A | done | [pl-50](prd/transform-cleanup.md#pl-50) |
| pl-46 남은 정리 — 0.2.0 배포 뒤 `dbcompare`·`stamp` 지우기 · `google-adk`·`litellm` 패키지를 뺄지 정하기(지시서 `agent.py`만 import) | 첫 이관용 도구와 안 쓰는 패키지. 빼면 새 이미지 버전 | todo | [pl-53](prd/transform-cleanup.md#pl-53) |

## 적재 (load) — 검색 DB(pgvector)·게시·저장 구조·DB 스키마
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 문서마다 고객·원천 메타를 EDW 조인으로 붙인다 — SFDC 영업 기회(직접 > Task > Event, + 계정 직접 — 같은 단계 동률은 비움) → `Account.Name`, CRMS `RM_CM_PJTLIST`, LAS `LAS.Contract`. 적재 때(`pipeline/load/edw_meta.py`) 원천 스키마 `doc`(`client_edw`·`attrs`·`created_at`)에 쓴다 | 파싱·구조화는 이 값을 안 쓴다 — 매핑이 바뀌어도 다시 파싱하지 않는다. EDW를 못 읽으면 메타 없이 적재(`meta_missing`) — `--replace`로 다시 채움 | done | [pl-29](prd/load.md#pl-29) |
| 고객 조인 사슬은 운영 쪽이 고칠 수 있는 설정 파일 `resources/config/edw_chain.yaml` — 서버 사본 자리 `ops.paths.edw_chain`(적재·검색 MCP가 함께 읽음), 점검 `python -m pipeline.load.edw_meta --check`. Quote 표는 지금 없음 | 표·칸 이름이 바뀌어도 코드를 고치지 않는다 | done | [pl-29](prd/load.md#pl-29) |
| 원천마다 다른 문서 메타는 `doc.attrs`(JSONB) 한 칸에 — 고정 칸은 `doc_id`·`file_path`·`summary`·`created_at`·`client_edw`·`clients_doc`·`content_date`·`embed_model`뿐. 키·EDW 칸·검색 거르기 이름·근거 표시는 사슬 파일이 정하고, `search`는 `attrs: {키: 값}` 거르기와 근거 `attrs`를 낸다 | 원천 칸을 더할 때마다 판(Alembic)·코드를 고치지 않게. 판 0005(GIN 색인) · MCP 계약 — 등급 A | done | [pl-52](prd/load-schema.md#pl-52) |
| 검색 DB(gold — pgvector) 표 5개(`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat` — 원천 스키마마다 한 벌)와 뷰 1개(`v_chunk_source`)는 Alembic(DB 판 관리 도구)으로만 만든다 | 검색 MCP는 PG만 읽는다. 실행 중 DDL 금지 | done | [pl-07](prd/load.md#pl-07) |
| 문서 묶음 하나를 한 트랜잭션으로 적재한다(`pgvector_load load`) — 하나라도 실패하면 전부 되돌림 | 반쯤 들어간 문서가 검색에 보이지 않게 | done | [pl-07](prd/load.md#pl-07) |
| 이미 있는 문서는 `doc.file_path`가 같으면 건너뛴다. 바뀐 내용은 `--replace`로 | 내용 지문(sha) 칸이 없어 같은 경로에서 내용이 바뀌어도 건너뛴다(알려진 한계) | done | [pl-07](prd/load.md#pl-07) |
| 적재 전에 DB 판을 확인 — 판 기록이 없으면 경고 후 계속, 낮거나 모르는 판이면 종료 2. `--replace`는 판 표(`alembic_version`)가 있는 우리 스키마에서만 | 남의 스키마나 옛 판 DB를 망가뜨리지 않게 | done | [pl-07](prd/load.md#pl-07) |
| 처음 쓰는 PG에는 `vector` 확장을 관리자가 한 번 만든다(`CREATE EXTENSION vector`) — 없으면 적재가 멈춘다 | 서버 계정은 보통 우리 스키마 권한만 있다. 절차는 release-and-patch §5-5 ⓪ | done | [pl-07](prd/load.md#pl-07) |
| 적재는 더하고 고치기만 하고 지우지 않는다. 원천에서 지워진 문서·실패 문서는 로그에만. 원본 경로는 원천 스키마 5벌을 통틀어 하나 — `--replace` 없이 이미 있으면 건너뛰고, `--replace`면 다른 원천 스키마의 옛 사본을 지우고 옮긴다 | 건너뛴 문서가 지워지면 안 된다. 경로가 바뀐 옛 행은 사람이 지운다 | done | [pl-13](prd/load.md#pl-13) |
| 임베딩 없음(`embed` `none` 또는 청크가 있는데 차원 0)이면 적재를 시작할 때 거부한다 — 판 확인·배포·적재 전에 종료 2 | 검색에는 벡터가 필수 | done | [pl-16](prd/load.md#pl-16) |
| 묶음의 임베딩 모델(`meta.json` `embed_model`)이 검색 스키마(원천 5벌)에 이미 있는 문서의 모델(`doc.embed_model`)과 다르면 그 묶음 적재를 거부한다 — 아무것도 쓰지 않고 종료 2, 거부는 `applog.pipe_event`에(`stage` `load.embed_guard`) | 모델이 섞이면 검색이 그 원천의 벡터 검색을 거부한다(질의 모델이 하나라서) | done | [pl-51](prd/load.md#pl-51) |
| 이름 있는 색인 비교 예시(`index_a`·`index_b`)를 두지 않는다 | 검색 색인은 원천 스키마의 표 하나뿐 | done | [pl-19](prd/load.md#pl-19) |
| 게시(publish — 파싱 결과를 Object Storage에 올리고 EDW `AI.ParsingMeta`에 기록) — 대표 `.md`와 엔진별 원결과를 올리고 원본 파일은 올리지 않는다 | 다른 팀은 결과를 Object Storage와 ParsingMeta에서 읽는다 | done | [pl-09](prd/load.md#pl-09) |
| ParsingMeta에는 INSERT만 — 키 (`source_system`, `source_key` = 원본 전체 키)가 이미 있으면 건너뜀. UPDATE는 적재 때 `loaded_at`·`gold_version`뿐 | — | done | [pl-09](prd/load.md#pl-09) |
| DRM(`skipped_drm`)·실패(`failed`) 문서는 EDW에 쓰지 않고 `output/publish/excluded_<날짜>.md` 보고서에만. 업로드 대상 상태는 `tuning.load.publish.upload_statuses`(기본 ok·partial) | 깨진 결과가 다른 팀에 넘어가지 않게 | done | [pl-09](prd/load.md#pl-09) |
| 게시 버킷이 원천 원본 버킷과 같으면 게시를 거부한다 — 단 `run_docs`는 이 검사를 끄고 넘긴다(`PM_BUCKET_SKIP_OVERLAP_CHECK=1`) | 원본 덮어쓰기를 막는다 | done | [pl-09](prd/load.md#pl-09) |
| 게시는 늘 하고 게시·EDW 칸은 settings.yaml `required` 한곳(`publish`·`object_storage`·`edw`) — 서버는 접속 칸, PC(`local`)는 `file://<폴더 절대 경로>`와 가짜 EDW `sqlite`만 | `run_docs`는 문서마다 늘 게시하고 게시 위치·Object Storage·EDW 읽기·쓰기 칸이 비면 시작을 거부한다 | done | [pl-26](prd/load.md#pl-26) |
| FAQ를 다시 올리면 gold faq의 문서·청크를 모두 지우고 지금 FAQ 파일 전체를 다시 적재(판을 잇지 않음) | pl-13 "지우지 않음"의 FAQ 예외(등급 A) | done | [pl-41](prd/load.md#pl-41) |
| 정형 DB(`struct` 스키마 — 마스터·문서 대장·표·칸)를 두지 않는다. 엔진 구성은 파일만 | 쓰이지 않았다. 서버에 남은 표는 DB 담당자가 정리 | done | [pl-08](prd/load.md#pl-08) |
| 문서 대장(`doc_registry`)·숨김(`doc_hidden`)·원천 삭제 처리를 두지 않는다. 서버는 PG가 없으면 로컬 대체 DB로 바꿔 타지 않고 멈춘다 | 빼야 할 문서는 원천에서 지우거나 사람이 SQL로 | done | [pl-12](prd/load.md#pl-12) |
| 마스터 표 — 용어집·고객 명부 CSV 여섯 개를 검색 PG `<PG_SCHEMA>_master`로(Alembic 갈래 `master` · `dbtool master load`가 git CSV로 통째로 바꿈). 구조화 고객 판별과 검색이 PG에서 읽고, `gold_version` = `<VERSION>+m<마스터 해시 8자>` | 원본은 git CSV. 대표 결과(silver)는 마스터를 읽지 않는다. 서버는 마스터를 못 읽으면 시작 안 함 | done | [pl-38](prd/load.md#pl-38) |
| (잠재 문제) 같은 문서의 다른 판(`s3_key` 다름) 묶기 — 검색 '최신' 질문에서 옛 판이 위로 올 수 있음, 필요해지면 다시 설계 | — | todo | [pl-56](prd/load.md#pl-56) |
| 저장 자리 셋 — 파싱 결과 저장본(silver)은 Object Storage 문서 폴더(이름 = `s3_key`로 만든 uuid5), 메타는 EDW ParsingMeta, 검색 DB(gold)는 pgvector | 로컬에는 로그·임베딩 캐시만. 다시 처리하면 같은 폴더를 덮어쓴다(지금 게시는 실행마다 새 날짜 폴더) | todo | [pl-32](prd/load-schema.md#pl-32) |
| 같은 `s3_key`가 FileStorageMap에 여러 행이면 `created_at`이 가장 늦은 행만. 새 행은 `file_size`가 같으면 건너뛰고 다르면 같은 `doc_id`로 다시 처리, 밀려난 행은 EDW `SupersededRow`에 | 원본을 받지 않고 판별한다(같은 크기로 덮어쓴 경우는 놓침 — 받아들임) | todo | [pl-32](prd/load-schema.md#pl-32) |
| DB 스키마 명세는 `docs/architecture/db_schema.md` 하나(검색 DB·EDW·마스터·applog 표의 칸·타입·쓰고 읽는 코드), `test_db_schema.py`가 대조 | 정의를 한 곳에. EDW 쪽 DDL은 DB 담당자 승인 대기 | dev | [pl-25](prd/load-schema.md#pl-25) |
| ParsingMeta에는 파싱 정보만(원천 키·상태·silver 위치·엔진·`gold_status`·`silver_version`·`gold_version`·`sha256`), 고객·분류 라벨 같은 파일 메타는 검색 DB `doc`에만 | 중복 적재를 없앤다. 운영이 더한 칸은 DB 담당자가 지운다 | dev | [pl-25](prd/load-schema.md#pl-25) |
| 문서 키는 원본 경로 하나 — 검색 DB `doc.file_path` = Object Storage 원본 경로 = EDW `s3_key`(청크는 `doc_id`만), ParsingMeta와 이 값으로 잇는다 | sha256 `doc_key`는 검색 DB에 안 둔다(ParsingMeta `sha256`만) | dev | [pl-25](prd/load-schema.md#pl-25) |
| 원천 시스템별 PG 스키마 5벌(`<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`), 각자 `doc`·`chunk`·BM25 표, `doc_id` 시퀀스는 기준 스키마 하나를 함께 | 원천마다 메타가 다르고 BM25 점수를 섞지 않는다. MCP `source_system` 필수(등급 A) | done | [pl-28](prd/load-schema.md#pl-28) |
| 원천 = 원본 경로(`s3_key`) 첫 마디 — `SFDC`·`CRMS`·`LAS`·`FAQ`(대소문자 무관)이거나 `SFDC-`·`SFDC_`·`CRMS-`·`CRMS_`·`las_`·`LAS_`로 시작하면 그 원천, 아니면 `other`(`build_bundle`). `faq` 스키마만 `chunk.faq_group` 칸 | `AI.FileStorageMap.source_system` 칸은 읽지 않는다 — 경로만으로 정함 | done | [pl-28](prd/load-schema.md#pl-28) |

## 검색 MCP (mcp) — AI 클라이언트가 부르는 도구 서버(이미지 `mcp-server`)
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| `search` — 질문으로 근거 찾기. 혼합 검색 = 뜻이 비슷한 글(벡터) + 낱말 점수(BM25) + 드문 ID 일치를 순위 합치기(RRF)로 묶음 | 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구. 가중치 벡터 1·BM25 1·ID 2(`search.weights.*`) | done | [mc-01](prd/mcp.md#mc-01) |
| `search` 입력 `k` 기본 8·상한 50, 근거 13칸 `text`·`file_name`·`file_path`·`page`·`line`·`section`·`client`·`contract_no`·`doc_date`·`version`·`superseded`·`chunk_key`·`attrs`(`mcp_server/schemas/evidence.py`), 근거 상태 `evidence_status` found·weak·none. 응답은 20,000바이트까지(낮은 순위부터 줄임) | 근거 상태는 표시만 하고 근거를 빼지 않는다. 질문 핵심어가 근거에 없으면 weak | done | [mc-01](prd/mcp.md#mc-01) |
| 검색 저장소는 검색 DB(gold — pgvector) 하나. PC는 SQLite 대역(`pg_standin`) | 서버·PC가 같은 SQL | done | [mc-01](prd/mcp.md#mc-01) |
| 질문 + 하드 거르기(`client`·`client_like`·`source_system`·`project_id`·`division`·`service_type`) — 후보 `min(50, max(3k,30))`개에서 범위 안만 남김 | 조건 밖 문서가 근거에 섞이지 않게 | done | [mc-01](prd/mcp.md#mc-01) |
| 질문 넓히기 — 용어집으로 BM25 낱말을 더함(동의어 1.0·약어 0.8·약한 것 0.3), 고객 별칭 최대 20토큰 | 동의어·약어로 물어도 찾게 | done | [mc-02](prd/mcp.md#mc-02) |
| 고객 2명 이상 비교 질문은 고객별(최대 4명)로 나눠 찾고 번갈아 합침. 집계형 질문은 BM25 가중치 0.2 | 한 고객이 근거 자리를 독차지하지 않게 | done | [mc-02](prd/mcp.md#mc-02) |
| 고객 거르기는 EDW에서 붙인 고객(`client_edw`)만 본다(정확 일치, 목록은 OR, `client_like`는 부분 일치) | 답이 고객을 섞으면 안 된다(C6, 11-02). 별칭 그룹은 pl-38 | done | [mc-05](prd/mcp.md#mc-05) |
| 이름만 다른 사본은 하나로(사본 묶음) | 같은 문서의 다른 판 문제는 pl-56 행 | done | [mc-05](prd/mcp.md#mc-05) |
| 검색기가 지운 칸(`file_sha256` 등) 대신 문서 키 `doc_key`(= `file_path`)로 읽음 | 새 묶음으로 검색기를 만들면 실패하던 문제 | done | [mc-10](prd/mcp.md#mc-10) |
| 질의 기록은 DB `applog.mcp_call`만(질문·SQL은 `args`, 근거 키) — 파일 기록 없음 | 로그는 Postgres 한 곳(op-13) | done | [mc-13](prd/mcp.md#mc-13) · [mc-09](prd/mcp.md#mc-09) |
| 대표 파싱 결과 주소 `rep_uri`(`s3://<bucket>/<key>`)는 원문 도구가 부를 때 ParsingMeta에서 읽는다(검색 근거 13칸에는 없음) | 사용자 11-01 — 검색 DB에는 거르기 메타만(C8 바뀜) | done | [mc-15](prd/mcp.md#mc-15) |
| `search` 운영 계약 — `question` 필수, `source_system` 필수·값 하나(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`, `-test` 별칭도) | 운영 명세와 같게. 계약 변경이라 사람 검토(등급 A), 0.2.0 | done | [mc-16](prd/mcp.md#mc-16) |
| 거르기 추가 — `FAQ_group`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`·`created_since/until`(시간대 없으면 한국 시간) | 모두 AND, 목록은 OR. 맞는 값이 없으면 오류가 아니라 빈 결과 | done | [mc-16](prd/mcp.md#mc-16) |
| 출력 줄이기 — 맨 위 `question`·`evidence[]`·`evidence_status`·`filter`·`scope_docs`, 근거 키 `chunk_key` = `<doc_id>:<seq>` | `index_id`·`subs`·`images`·`notes`·`ms` 등을 지운다(`file_path`는 남김 — 사용자 11-03) | done | [mc-16](prd/mcp.md#mc-16) |
| 원문 도구 2개 — `list_doc_fulltext`(목록)·`get_doc_fulltext`(원문). 거르기는 원천 스키마 `doc`, 대표 결과 위치·`doc_key`는 부를 때 ParsingMeta에서 | 사용자 11-01 — 검색 DB에는 거르기 메타만(EDW를 못 읽으면 `registry_unavailable`). 새 도구라 등급 A, 0.2.0 | done | [mc-17](prd/mcp.md#mc-17) |
| 검색이 실행 중에 묶음 파일(`docs.jsonl`·`chunks.jsonl`·`meta.json`)을 읽지 않고 문서 날짜·임베딩 모델·차원을 PG에서 읽는다(판 0004 — gold doc `content_date`(문서에 적힌 날짜)·`embed_model`, `corpus_stat.dim` 지움) | 서버에서 묶음 경로를 맞출 필요가 없어진다. 검색 동작이 바뀌는 일이라 자기 PR + 평가 | done | [mc-19](prd/mcp.md#mc-19) |
| `query_edw` — EDW 읽기 전용 SQL(SELECT/WITH 한 문장, 읽기 계정), 1,000행(운영 서버와 같음 — 사용자 11-03)·20초·2 MB 상한 | 정형 숫자는 EDW에서 답한다. 표는 읽기 계정이 볼 수 있는 모든 스키마(시스템 표 제외 — 좁히기는 DB 권한) | done | [mc-06](prd/mcp.md#mc-06) |
| `edw_meta` — 정적 자료(`catalog.json`+`columns.jsonl`)로 스키마 → 표 → 칸 찾기, 모르는 이름은 비슷한 이름 제안, 응답 200 KB 상한 | SQL을 쓰기 전에 이름 확인. 표본 값은 내지 않는다 | done | [mc-07](prd/mcp.md#mc-07) |
| `parse_document` — 파일 1건(inbox 경로 또는 base64, 100 MB까지 — 두 길 같은 칸 `ops.runtime.parse_max_mb`, 사용자 11-03)을 파싱 서비스(127.0.0.1:8766, 토큰)로 넘겨 대표 본문·표를 받음. 300초 넘으면 `job_id` | 아직 적재되지 않은 파일을 바로 물을 때 | done | [mc-08](prd/mcp.md#mc-08) |
| 스캔 PDF(글자층 20자 미만) 파싱 다시 지원 — 내부망 VLM(`qwen_vlm`)으로 파싱. VLM 설정(주소·모델)이 없으면 빈 결과 + "스캔 PDF — VLM 미설정", 실패면 "스캔 PDF — VLM 파싱 실패" | 클라이언트가 스캔 문서도 글로 받는다. 시간 상한은 작업 제한 시간 하나(쪽 수 상한 없음, 사용자 11-03) | done | [mc-18](prd/mcp.md#mc-18) |
| 서버는 `/mcp`(기본 127.0.0.1:8765) 또는 `--stdio`로 뜬다. 내부망 주소만, 0.0.0.0 거부, 루프백이 아니면 `MCP_TOKEN` 필수 + DNS 리바인딩 막기. 서버에서 PG 접속 칸이 비면 시작 거부 | 공용 내부 서비스라 위험한 노출을 거부 | done | [mc-09](prd/mcp.md#mc-09) |
| 과부하 보호 — 동시 8개, 대기 32개(동시 × 4) 넘으면 바로 `busy`, 도구당 30초(`parse_document`는 자기 시간 + 10초) | 늘 떠 있게. `/health`는 예열 중 503, 새 적재는 30초마다 확인 | done | [mc-09](prd/mcp.md#mc-09) |

## 운영 (ops) — 서버 러너(run_docs)·실행 관리·종료 정리·계정·모델 가드·설정
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 서버 입구는 호스트의 `run_docs.py` 하나 — 상주 컨테이너 안에서 `docker exec`로 일을 시킨다. 이미지 명령은 `parse`·`publish`·`migrate`·`show-stack`·`idle`·`selftest` 등 | — | done | [pl-10](prd/ops.md#pl-10) |
| run_docs 흐름 — 문서마다 미리 받기 → 파싱 → 구조화+적재 → 게시 → 임시 폴더 삭제, 배치 장벽(앞 묶음이 다 끝날 때까지 기다리기) 없음 | 문서 수천 건을 사람 없이 처리 | done | [pl-10](prd/ops.md#pl-10) |
| 새 문서만 처리(목록 − ParsingMeta 끝난 행) — 파싱 입구는 구현됨(수집 표). 전체 재파싱은 사람이 전체 e2e로만 | 지문이 바뀔 때 전체 자동 재파싱을 하면 밤 시간을 넘긴다 | done | [pl-23](prd/ops.md#pl-23) |
| run_docs 대상 고르기를 위 규칙에 맞춘다 — 파일 이름 키워드(`--filter RFP,proposal`)·`--start-offset` 뒤 `--skip-done`이 ParsingMeta 끝난 행(ok·partial — gold_version도, skipped_dup)을 뺀다 | 새벽 배치는 이름에 RFP·proposal이 든 문서만 처리한다(키워드가 정기 운영에 맞는지는 C-72 ③) | done | [pl-23](prd/ops.md#pl-23) |
| 새벽 배치는 `ops.nightly.time`·`max_docs`·`deadline` 셋이 모두 있을 때만 돈다(하나라도 비면 안 돎 — 사용자 11-02) — systemd 타이머가 5분마다 `trigger.sh scheduled` → `run_docs.py --start-offset 0 --skip-done --max-docs --deadline` | 지금 서버는 비워 둠(꺼짐) — 켜는 것은 사람(C-72) | done | [pl-23](prd/ops.md#pl-23) |
| 전체 e2e는 local·dev·prd 셋에서 — 전체 문서 실행은 prd에서만 새 원천별 스키마 이름(새 `PG_SCHEMA`)으로, 옛 gold·`struct` 스키마는 2주 뒤 DB 담당자가 백업하고 지움 | 판 0002가 기준 스키마의 옛 표를 지운다. 사용자 11-02 | todo | [pl-54](prd/ops.md#pl-54) |
| 새벽 배치 칸 — 시작 시각·문서 수 상한·마감 시각(비면 안 돎), 칸 이름 하나로(`pipeline.host.nightly.time` ↔ `ops.nightly.time` 어긋남 고침) | 사용자 11-02 | done | [pl-23](prd/ops.md#pl-23) |
| 문서별 순서를 파싱 → silver 게시 → 원본 임시 파일 삭제 → gold로 | 게시가 gold를 기다리지 않고(게시 스레드 따로), 원본은 게시가 성공했을 때만 지운다(11-03) | done | [pl-24](prd/ops.md#pl-24) |
| gold 실패면 ParsingMeta 행은 남긴다. 파싱이 통째로 실패하면 EDW에 쓰지 않고 로그에만 — 다음 실행이 다시 고른다 | gold는 silver에서 다시 만들 수 있다(11-03) | done | [pl-24](prd/ops.md#pl-24) |
| gold 실패를 ParsingMeta 새 칸 `gold_status`=failed·이유로 적기 | 칸 추가는 DB 담당자 몫(등급 A — C-81), 칸이 생긴 뒤 코드 | todo | [pl-55](prd/ops.md#pl-55) |
| run_docs 종료 코드 — 대상 0건 = 0, 실패 있음 = 1, 마감 도달 = 75 | 스케줄러가 실패를 본다(C-33). 실패와 마감이 함께면 1 · 다른 run_docs가 도는 중도 75(11-03) | done | [pl-18](prd/ops.md#pl-18) |
| 새벽 run_docs에 문서 수 상한·마감 시각·겹침 막는 잠금 | `--max-docs`·`--deadline`(11-02) + `run_docs.py` 안 `flock` 잠금(`batch_progress/run_docs.lock`, 11-03). `TimeoutStartSec=6h`는 마지막 안전판 | done | [pl-18](prd/ops.md#pl-18) |
| 레인 3개(light·medium·vlm, 수집 표의 나누기 기준)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴 다른 레인) — `ops.run_docs.<레인>_dedicated`·`_shared` 기본 각 1 | 규칙을 표 하나(`pick_lane`)로 모으고 설정으로 조정 | done | [rn-01](prd/ops.md#rn-01) |
| vlm 레인 동시 파싱 상한 `ops.run_docs.vlm_cap` = 2. `warm`·`vlm_cap`이 1 미만이거나 워커가 없는 레인이 있으면 시작 거부 | GPU 예산을 지키고 끝나지 않을 설정을 막는다 | done | [rn-01](prd/ops.md#rn-01) |
| 미리 받기 상한 `ops.run_docs.warm` = 20, 구조화 워커 `struct_workers` = 2, 중간 대기열 상한 `struct_backlog`(기본 구조화 워커 × 2, 0이면 없음) | 구조화가 느릴 때 파싱 결과가 디스크에 쌓이지 않게 | done | [rn-02](prd/ops.md#rn-02) |
| 대기열 길이를 상태가 바뀔 때마다 `batch_progress/queue_depth.jsonl`에 한 줄 | 대기열 길이와 구조화 대기 시간의 관계를 잰다 | done | [rn-02](prd/ops.md#rn-02) |
| MCP `parse_document`(사람이 기다리는 요청)에 CPU를 먼저 준다 — 전용 컨테이너 + cgroup CPU 가중치 최고(10-31 결정). 11-03 재확인: 일괄 `data-pipeline`과 뗀 전용 `data-pipeline-mcp`(cpu_shares 4096 > 1024) | nice는 컨테이너끼리는 효과가 없다(옛 C-65 ⑥ — [이력](history/refactor_c_items.md)) | dev | [rn-03](prd/ops.md#rn-03) |
| MCP 업로드 작업이 있으면 medium 전담 워커를 쉬게 한다(이름 날짜가 어제·오늘·내일인 작업 폴더만 감시) | 5초마다 폴더 전체를 훑던 부담을 줄인다 | done | [rn-04](prd/ops.md#rn-04) |
| 프로세스가 끝날 때(정상·오류·SIGTERM) 임시 설정 덮기 파일·PID 기록을 지우고 자식을 끝내 회수(SIGTERM → 10초 → SIGKILL, 종료 143) — `common/core/exitclean.py` 한 곳 | 임시 파일이 쌓이고 soffice 좀비가 남던 문제 | done | [pl-27](prd/ops.md#pl-27) |
| EDW 접속 설정은 `common.connections.rdb` 하나(settings `required.edw`)에 계정 둘 — 읽기(목록·FileStorageMap·ParsingMeta 조회·MCP), 쓰기(ParsingMeta 게시만). MCP 프로세스에서는 쓰기 계정을 비운다 | 같은 값이 설정 블록 넷에 반복되던 것을 없앰. 등급 A | done | [op-03](prd/ops.md#op-03) |
| PC 대역 EDW는 sqlite 파일 하나(`valid_env/edw/edw.sqlite`)를 `AI`·`CRMS`·`LAS`·`SFDC`로 붙여 같은 SQL이 돌게 | PC에서 운영 EDW에 접속하지 않는다 | done | [op-03](prd/ops.md#op-03) |
| 모델 역할 llm·vlm·embed(OpenAI 호환). 외부 주소는 `dev.models.<역할>.allow_external`이 켜지고 `RUN_ENV=local`일 때만, 서버는 거부. 내부 판정 = 해석된 주소가 사설 IP(또는 `internal_ip_ranges`) + 호스트 접미(`internal_host_suffixes`) | 폐쇄망 밖으로 데이터를 보내지 않는다. 접미 목록에는 전체 호스트 이름이 아니라 상위 도메인을 적어야 맞는다(운영 고침 묶음) | done | [pl-11](prd/ops.md#pl-11) |
| 비용 상한 — `dev.models.guard.budget_usd`(외부 모델 하루 지출 $, 기본 0.1 — PC 사용자마다)·하루 장부(`spend_file` + 날짜, 비우면 `output/_llm_spend/<날짜>.txt`) | PC 호출을 싸게 유지. 응답 캐시·가짜 LLM도 여기 | done | [pl-11](prd/ops.md#pl-11) |
| 모델 — 개발 서버부터 내부망 GLM, PC는 OpenRouter | 사용자 11-02 | done | [pl-11](prd/ops.md#pl-11) |
| JSON Lines 사건 기록(공통 키·로그 수준·비밀 가림) + DB 감사·성능 로그 — 두 앱 `common.core.jsonlog`, MCP 도구 호출마다 `applog.mcp_call`, 파이프라인 실행·단계 `applog.pipe_run`·`pipe_event`(`dbtool up --target applog`) | 사건·감사·성능을 같은 형식으로 남긴다(코드 #87 병합 — 서버 적용은 C-79·C-80) | done | [op-01](prd/ops.md#op-01) |
| 실행 환경 `RUN_ENV`(`required.env.run_env`)는 `local`·`dev`·`prd`만, 어디서나 필수 — `stage`나 모르는 값이면 시작 거부 | `stage`는 `prd`와 똑같이 동작했다 | done | [op-02](prd/ops-settings.md#op-02) |
| 서버(`dev`·`prd`)는 가짜 LLM(`dev.llm_fake`)이 켜져 있거나 설정 파일을 못 읽으면 시작 거부 | 서버에서 가짜 답이 도는 것을 막는다 | done | [op-02](prd/ops-settings.md#op-02) |
| 설정은 settings.yaml 하나 — `settings.sample.yaml`에 모든 키가 기본값과 함께(`python -m common.config.sample`로 생성) | — | done | [op-05](prd/ops-settings.md#op-05) |
| 배치 — 맨 위 `required`(필수·비밀) → 역할 절 7개(환경마다 정하는 값) → `tuning`(거의 안 바꾸는 값 — 분류 제목, 11-04). 옛 배치는 시작 거부, `python -m common.config.migrate`로 변환 | sample과 실제 파일의 차이를 줄였다 | done | [op-08](prd/ops-settings.md#op-08) |
| 설정 이관은 옛 배치 settings.yaml → 새 배치만 | 운영 서버는 0.1.0(settings.yaml 하나). 사용자 11-02 | done | [op-08](prd/ops-settings.md#op-08) |
| 하드코딩 0 — 설정 값은 settings.yaml이나 이미지 기본값 표(`settings.py`)에서만, 호스트 셸은 `settings_env.sh`가 준 값만, PG 자동 찾기 없앰(PG 접속 필수) | 한 곳을 바꾸면 나머지가 어긋나던 문제. 남은 복사본 있음 | done | [op-09](prd/ops-settings.md#op-09) |
| 환경마다 다른 경로·접속은 settings.yaml 필수(코드 기본값 없음) — 컨테이너 안 경로는 이미지 기본값 표 하나만, 호스트 `PATCH_CODE` 기본값 지움 | 사용자 11-02 | done | [op-09](prd/ops-settings.md#op-09) |
| 은퇴한 설정 지우기 — `common.paths.korean_font`·`eval_sets_dir` 등(남아 있으면 경고만) | 지문이 바뀌어 0.1.0 묶음에 | done | [pl-21](prd/ops-settings.md#pl-21) |
| 아무도 안 읽는 env 4개(`FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`)를 run_docs 명령에서 뺌 | C-51 | done | [pl-30](prd/ops-settings.md#pl-30) |

## 테스트·평가 (test) — 변경을 어떻게 증명하나
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 시험 층 둘 — `tests/server/`(이미지 안 반입 시험, `python -m pipeline.cli selftest`, 네트워크 없음)와 `tests/general/`(PC 전용 — PG·Docker·느린 것) | 반입 판정은 폐쇄망 이미지 안에서 돌아야 한다 | done | [e2-02](prd/test.md#e2-02) |
| 기준선 — 바꾼 뒤 시험 결과가 기준선보다 나빠지면 안 된다(값은 앵커) | 지금 기준선은 11-04 selftest(pytest 수는 다시 잴 것 — 앵커) | done | [e2-02](prd/test.md#e2-02) |
| 알려진 실패 목록(`deploy/release/known_fail.txt`·`GENERAL_KNOWN_FAIL`) — 통과하면 "XPASS — 지울 수 있음" 경고 | 새 실패를 목록에 넣는 것은 고장을 숨기는 일 — 사람 승인 필요 | done | [e2-02](prd/test.md#e2-02) |
| PC 시험 자식 프로세스는 개발자 `settings.yaml` 대신 시험 전용 바탕(`run_env: local`만)을 쓴다 | 공용 개발 PG를 건드리지 않게 | done | [e2-02](prd/test.md#e2-02) · [e2-11](prd/test.md#e2-11) |
| 이미지 반입 관문 — `build_ship.sh`로 빌드하고 `selftest_gate.sh`가 종료 코드가 아니라 `[판정]` 줄로 판단(알려진 실패 밖 FAIL 0) | 서버는 반입 시험을 통과한 이미지만 받는다 | done | [e2-08](prd/test.md#e2-08) |
| 코드만 바뀌면 코드 폴더 바꾸기(이미지는 그대로) | 이미지를 다시 만들지 않는다 | done | [e2-08](prd/test.md#e2-08) |
| PC 일반 시험의 옛 실패 정리 — 공용 PG를 읽던 3개는 고치고, 지운 모듈의 시험은 지움 | 리팩토링 전부터 있던 실패. 남은 실패 0(`GENERAL_KNOWN_FAIL = {}`, `known_fail.txt` 빔) | done | [e2-11](prd/test.md#e2-11) |
| 옛 오버레이 패치 흔적 둘 — `common/core/fingerprint.py`의 `common/PATCH_VERSION` 후보(허브가 릴리스 지문 배치에서 지움)·`deploy/docker/IMAGE_BASE`(읽는 곳 없음 — 지울지 사용자가 정함) | `fingerprint.py`는 레이어 지문 파일이라 고치면 서버 문서가 모두 다시 처리된다 | todo | [e2-21](prd/test.md#e2-21) |
| 지시서 폴더 찾기(`paths.resolve_agent_dir`)에서 폴더가 없는 갈래 셋(`resources/prompts/mcp`·`validation/e2e`(`triple_extract` 지움)·`dev_tools/unit_test/fixtures`)과 그 설명 주석 지우기 | `paths.py`를 고치면 레이어 지문이 모두 바뀌어 다음 지문 배치에 | todo | [e2-15](prd/test.md#e2-15) |
| PC 스모크 — 문서 2~3건으로 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색(README §4-4) | 릴리스 전에 사슬 전체를 증명 | done | [e2-01](prd/test.md#e2-01) |
| PC Docker 스모크(`valid_env/docker/smoke_test.sh`)를 다시 돌려 검색까지 가는지 확인 | mc-10은 고쳐졌고 다시 돌려 보기만 남음 | todo | [e2-13](prd/test.md#e2-13) |
| 시험 자료 `valid_env/` — 문서 `object_storage/{SFDC,CRMS}/<uuid>/<파일>`, 합성 EDW `edw/` | 서버와 같은 배치. 서버 반입 시험은 자료를 임시 폴더에 만들어 쓴다 | done | [e2-09](prd/test.md#e2-09) |
| 배포 뒤 검색 스모크 — `mcp_smoke`로 도구 목록·`search` 근거 1건 이상·근거 칸 확인 | 서버에서 검색이 실제로 답하는지 한 번에 본다 | done | [e2-04](prd/test.md#e2-04) |
| 답변 점검(PC 전용) — `validation/e2e/answer_gen.py`가 `rag_qa` 에이전트로 `search`·`edw_meta`·`query_edw`를 불러 답하고 인용을 규칙으로 점검 | MCP는 근거만 준다. 유료 호출은 예산 장부를 거친다 | done | [e2-05](prd/test.md#e2-05) |
| answer_gen 인용 버그 고침 — 오류 구분·JSON으로 못 바꾸는 값·객체가 아닌 답·다시 직렬화 | 시험 `tests/general/e2e/test_answer_gen.py` | done | [e2-19](prd/test.md#e2-19) |
| 분류 수용 보고서(개발 서버) — 사람 정답 CSV(`s3_key`·정답 분류)와 비교해 원천·라벨별 일치율·혼동표 | 회사 데이터라 git 밖. 통과 기준은 첫 결과를 본 뒤 정한다 | todo | [e2-20](prd/test.md#e2-20) |
| 검색 점검 페이지 `validation/search_ui`(기본 포트 8790, MCP `127.0.0.1:8765/mcp`) | 사람이 브라우저로 근거를 본다 | done | [e2-07](prd/test.md#e2-07) |
| PC 평가 도구는 검색 점검 페이지·답변 점검 둘만 남기고 나머지 도구·설정을 지움 | PC 전용 설정 약 50개의 관리 비용 | done | [e2-10](prd/test.md#e2-10) |
| 안 쓰는 함수·요건 없는 코드(시험만 부르는 것 포함)를 지움 | 죽은 코드 비용. MCP 도구 이름·입출력은 그대로 | done | [e2-17](prd/test.md#e2-17) · [e2-18](prd/test.md#e2-18) |

## 문서·릴리스 (doc) — 문서 배치·버전·이미지·서버 설치
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 요건은 `docs/PRD.md` + `docs/prd/<카테고리>.md`, CLAUDE.md는 규칙·명령만, 지난 기록은 `docs/history/` | 겹치는 문서가 많고 요건이 흩어져 있었다 | done | [do-04](prd/doc.md#do-04) |
| PRD 카테고리 재편(수집·변환·적재·운영 등, ID 그대로 — 3부 #85)과 PRD 표를 한눈에 읽히게 다시 쓰기(4부) | 사람이 요건을 바로 이해하게 | done | [do-04](prd/doc.md#do-04) |
| 용어집 `docs/INDEX.md` `## Glossary` — 약어·옛 용어 대응, CLAUDE.md에는 링크 한 줄 | 옛 용어가 주석·기록에 아직 나온다 | done | [do-02](prd/doc.md#do-02) |
| `refactor.md`를 병합 결과와 맞춤 — 낡은 줄 정리, C 항목 → PRD 링크, 검토자 = 사용자(등급 A) | 교차 확인에서 낡은 줄이 나왔다 | done | [do-03](prd/doc.md#do-03) |
| `refactor.md`를 루트에서 `docs/refactoring/`으로(옮기는 커밋과 링크 고치는 커밋을 따로) | 루트에는 입구 파일만 | done | [do-01](prd/doc.md#do-01) |
| 버전은 루트 `VERSION` 하나(지금 0.1.0), 첫 태그 `v0.1.0` + 릴리스 노트 | 이미지 태그와 DB 버전 표기가 같은 값을 쓴다 | done | [op-04](prd/doc.md#op-04) |
| 코드 없는 실행 이미지(`data-pipeline-runtime`·`mcp-server-runtime`)에 코드 폴더를 `/app/deploy`로 읽기 전용 마운트 | 개발 서버에서 이미지를 다시 만들지 않고 코드만 바꿔 시험 | done | [op-06](prd/doc.md#op-06) |
| 시작 검사 `runtime_entry.sh` — 코드 폴더가 없거나 의존성 지문(`DEPS_HASH`)이 다르면 종료 2, 이미지 판·코드 커밋을 한 줄 기록 | 의존성 어긋남이 나중에 조용한 오류로 터지지 않게 | done | [op-06](prd/doc.md#op-06) |
| 개발 → 운영 굽기 `bake.sh` — 개발에서 쓴 실행 이미지 + 시험한 코드 폴더로 `Dockerfile.bake`(네트워크 없이), 반입 판정 뒤 저장·분할 | 운영에는 개발에서 시험한 그대로 올라간다 | done | [op-07](prd/doc.md#op-07) |
| 운영(prd) 이미지에 settings.yaml(비밀 포함)도 굽는다 — 🔒 검토 등급 A(비밀 처리) | 이미지 파일 = 비밀(반입 경로만), 키를 바꿀 때마다 다시 굽기. 사용자 11-02 | todo | [op-12](prd/doc.md#op-12) |
| 서버 설치 길은 하나(README §5-0·§5-3). 컨테이너 도구는 셸 env > `ops.host.docker` > podman > docker. 이미지는 `load.sh`로(45 MB 조각) | 문서마다 절차가 달랐다. 서버 기본 도구는 podman | done | [op-10](prd/doc.md#op-10) |
| 0.2.0 올리기·되돌리기(release-and-patch §8-3·§8-5) — DB 백업 → `migrate check` → `up`, 되돌릴 땐 `settings.yaml.0.1.0` 복원, 재처리 동안 밤 타이머 멈춤 | DB·EDW·전체 재처리가 함께 바뀐다 | done | [op-10](prd/doc.md#op-10) |
| 일회성 작업 컨테이너 지움 — 운영 작업·`dbtool`·`migrate`는 상주 `data-pipeline`에 `exec`, 이미지 점검(`docker run --rm … selftest`)은 그대로 | 사용자 11-02 | done | [op-10](prd/doc.md#op-10) |
| 사람 정답 폴더 칸(`GOLD_DIR`·이미지 `gold_mount`) 없음 — 점검기 정답 폴더 점검도 없음 | 사용자 11-04 — 상주 컨테이너에 붙지 않아 점검이 늘 건너뛰어짐 | done | [op-11](prd/doc.md#op-11) |
| 서버 루트 폴더 하나(예 `/home/dev/`) — `settings.yaml`·`edw_chain.yaml`·코드·이미지·`output/`가 그 아래, 판마다 새 루트(검색 PG는 공유), `/srv/rag`·`env/`·`code/live` 없음 | 사용자 11-04 | done | [op-13](prd/doc.md#op-13) |
