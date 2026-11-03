# sbl_data_parsing — PRD

목표: 폐쇄망 회사 문서에서 출처 달린 근거를 찾는다 — 파싱 → 구조화 → 적재(pgvector) → 검색 MCP, 서버와 PC에서 같게.
행 = 요건 하나(끝난 것 포함) — 칸은 요건(무엇을, 어디서) · 기준·이유 · 상태 · ID. ID 하나가 여러 행에 나올 수 있다(상세는 ID 링크의 앵커). 상태: todo · dev · done(그 밖에 partly done) · dropped(요건에서 뺌 — 행은 남김, 사용자 10-31 범위 축소). ID는 그대로 두고 카테고리 파일이 자리를 정한다(do-04 3부 11-01 — 수집·변환·적재·검색·운영·테스트·문서, 2만 자 넘는 카테고리는 `<분류>-<하위>.md`). 상세는 ID 링크.

## 지금 진행 중
- pl-25 DB 스키마 명세 — dev: `docs/architecture/db_schema.md` 병합됨 → 사용자·DB 담당자 승인 대기(ParsingMeta 판 칸은 11-02 결정 — `silver_version`·`gold_version`, `stack_version` 없음).
- 0.2.0 묶음(todo — 순서는 허브가 정함): 저장 구조 [pl-32](prd/load-schema.md#pl-32) · 원천별 gold 스키마 [pl-28](prd/load-schema.md#pl-28) · run_docs 순서 [pl-24](prd/ops.md#pl-24)(done 11-03 — `gold_status` 칸만 C-81) · 게시 필수 [pl-26](prd/load.md#pl-26)(done) · 분류 [pl-33](prd/transform.md#pl-33) · FAQ [pl-39](prd/extract.md#pl-39)·[pl-41](prd/load.md#pl-41) · 지문 배치 [pl-46](prd/transform-cleanup.md#pl-46)·[pl-47](prd/transform-cleanup.md#pl-47) · 확장자 2차 [pl-45](prd/transform.md#pl-45) · `search` 계약 [mc-16](prd/mcp.md#mc-16) · 원문 도구 [mc-17](prd/mcp.md#mc-17).
- 운영 고침 묶음(todo — 사용자 11-02 결정, 코드는 따로): 회전 판정 병렬·기본 적용 끄기 [pl-02](prd/extract.md#pl-02) · 서버 러너 병렬 받기 [pl-48](prd/extract.md#pl-48) · `run_docs` 끝난 문서에 `skipped_dup` 넣기(done — `DONE_STATUSES`) · EDW 고객 매핑 적재로 옮김 [pl-29](prd/load.md#pl-29).
- 검색 — PG만, 실행 중 묶음 없음 [mc-19](prd/mcp.md#mc-19)(done 11-03 — 판 0004).
- do-04 문서 재구성 — 4부: PRD 표를 요건 한 줄씩 다시 씀 `feature/do04-prd-rows`(이 PR).

## 수집 (extract) — 서버에서 문서 목록을 정하고 받아 오기까지
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 문서 목록은 EDW 표 `AI.FileStorageMap`에서 읽는다(`id`·`s3_key`·`original_filename`·`file_size`) — 서버 러너 `run_docs.py`가 파일 이름 키워드(`--filter`)로 거르고 작은 파일부터 | 목록의 기준은 EDW다. Object Storage를 직접 훑지 않는다 | done | [pl-01](prd/extract.md#pl-01) |
| 새 문서만 고른다 — 목록에서 EDW `AI.ParsingMeta`에 끝난 행(`ok`·`partial`·`skipped_dup`)이 있는 원본 키(`s3_key`)를 뺀다. 파싱 입구(`pipeline/cli.py` `_unparsed`)가 EDW를 읽기 계정으로 한 번 읽음 | 끝난 문서를 다시 파싱하지 않는다. `not_parsed`·`skipped_disk_cap`·실패·기록 없음은 다시 고른다(사용자 11-01). 서버에서 EDW를 못 읽으면 시작하지 않는다(종료 4) | done | [pl-23](prd/ops.md#pl-23) |
| 파일은 Object Storage 버킷에서 `s3_key`로 받는다. 파싱 입력은 폴더 또는 목록 파일(`rdb:csv:<경로>`) 둘뿐 | `s3://` 직접 입력·RDB 표 직접 조회·원천 목록 파일(`sources.json`)은 지웠다(사용자 11-01) — 길을 하나로 | done | [pl-01](prd/extract.md#pl-01) |
| 미리 받기(warm) — `run_docs`가 파싱보다 앞서 문서를 최대 20개(`ops.run_docs.warm`)까지 받아 임시 폴더(`_warm`)에 둔다 | 다운로드를 기다리느라 파싱 워커가 놀지 않게. 받기 실패면 파싱 때 직접 받는다 | done | [pl-01](prd/extract.md#pl-01) |
| 병렬 다운로드 — 목록 파일의 여러 파일을 동시에 받는다(`source warm` 기본 2개 `extract.prefetch_workers` · `rdb:csv` 받기 기본 1개 `extract.source.fetch_workers`) | 큰 목록을 빨리 받는다. 받기는 네트워크 대기라 CPU를 거의 안 쓴다 | done | [pl-48](prd/extract.md#pl-48) |
| 서버 러너도 병렬로 받는다 — 받기 워커 `ops.run_docs.warm_workers`(기본 2)개가 차례대로 집어 동시에 받는다. 실제 동시 받기 수 = min(받기 워커 수, 미리 받기 빈자리) | 미리 받기 상한 `ops.run_docs.warm`(받는 중 포함)과 함께 작동 — 빈자리가 없으면 워커가 있어도 받지 않는다(사용자 11-02) | done | [pl-48](prd/extract.md#pl-48) |
| 레인 나누기 — 받은 직후 셋으로. **vlm**: 스캔 PDF(첫 3쪽 글자 평균 300자 미만)·그림 많은 오피스(내장 그림 8개 이상 또는 800 KB 이상)·pptx·ppt·검사 목록 밖 형식(mht·mhtml·이미지 등). **medium**: 검사한 pdf·오피스 중 가벼운데 큰 파일(docx·doc 300 KB, xlsx·xls·xlsm 500 KB, pdf 1 MB 이상). **light**: 글자형(txt·hwp·hwpx·csv·eml·msg·html)과 나머지 | 그림 읽는 모델(VLM)이 필요한 무거운 문서가 가벼운 문서를 막지 않게 — 레인마다 전담·공유 워커, vlm은 동시 2개(GPU), light는 CPU 부하 대기를 건너뜀(`run_docs.py` `classify_doc`, `docflow_probe.py`) | done | [rn-01](prd/ops.md#rn-01) |
| 완전히 같은 파일(sha256 같음)은 한 번만 파싱하고 결과를 재사용한다. 문서는 S3 키마다 따로 둔다 | 비싼 파싱을 중복하지 않는다. 키마다 메타(고객 등)가 달라 문서는 따로. 남길 사본: 사본 표시 없는 이름 → 최신 → 큰 파일(`dedup.py` `_rep_select`) | done | [pl-02](prd/extract.md#pl-02) |
| ~~비슷한 문서 묶기(이름·내용 유사도)~~ | 지움(사용자 10-31, 코드 11-01) — 완전 중복만 남긴다 | dropped | [pl-02](prd/extract.md#pl-02) |
| 회전 바로잡기 — 켜면(`extract.prepare.rotate`) 이미지·스캔 PDF 쪽마다 4방향(0·90·180·270도) OCR 점수를 스레드 4개로 동시에 재 가장 높은 방향으로 돌린다(같으면 0도). 기록 `rotation.csv` | 돌아간 스캔은 엔진이 읽지 못한다. 판단 규칙(문턱·1.3배·기대 각도·빠른 경로)은 지우고 기능만 남겼다(사용자 11-02). `rotation.csv`는 쪽 VLM·원본 sha 확인이 읽어 남김 | done | [pl-02](prd/extract.md#pl-02) |
| 회전은 기본으로 끈다(`extract.prepare.rotate: false`) — 꺼지면 회전용 OCR을 전혀 하지 않고 그대로 놓는다 | 사용자 11-02. 옛 기본은 켬(이미지·스캔 PDF 쪽마다 OCR 점수 2~4번) | done | [pl-02](prd/extract.md#pl-02) |
| DRM·암호 파일 감지 — 감지해서 표시만 | 복호화는 흐름 안에서 하지 않고 수동 명령(`python -m pipeline.extract.secure_docs decrypt`)으로 — 요건과 다르게 동작(앵커 표) | done | [pl-02](prd/extract.md#pl-02) |
| 압축 파일은 지원하지 않는다고 표시 | — | done | [pl-02](prd/extract.md#pl-02) |
| FAQ 원천 — 질의응답 엑셀을 행 단위로(시트 = FAQ 묶음, 행 하나 = 청크 하나). `FAQ/<uuid>/<파일>`을 FileStorageMap `source_system='FAQ'`로 등록 | 질의응답을 문서 통째가 아니라 질문 하나 단위로 찾는다. 0.2.0 | done | [pl-39](prd/extract.md#pl-39) |

## 변환 (transform) — 파싱·대표 결과 고르기·그림·구조화
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 파일 형식마다 형식별 엔진 목록(stack — `resources/config/pipeline_stack.json`)에 적힌 엔진을 **모두** 돌린다(하나씩 차례로 시도하지 않음) | 모든 형식을 잘 읽는 파서는 없다. 서버·PC가 같은 파일을 쓰고, 바꿀 때는 그 파일을 고쳐 오버레이 패치한다. 파일을 못 읽거나 모양이 틀리면 시작하지 않는다(종료 2) | done | [pl-03](prd/transform.md#pl-03) |
| PDF는 두 갈래 — 글자층이 쪽당 평균 20자 미만이면 스캔(`.pdf_image` → 그림 읽는 모델 VLM만), 아니면 글자 PDF(`.pdf_text` → pymupdf·kreuzberg) | 스캔 PDF는 글자 엔진이 못 읽는다. 판정은 `_types.json`에 저장해 다시 쓴다 | done | [pl-03](prd/transform.md#pl-03) |
| 지원 형식: pdf · doc(x) · ppt(x) · xls(x/m) · hwpx · txt · html/htm · mht/mhtml · eml · msg · png/jpg/jpeg/tif/tiff/bmp. 옛 `.hwp`·압축(zip)은 미지원 | stack의 형식 키 24개 | done | [pl-03](prd/transform.md#pl-03) · [pl-42](prd/transform.md#pl-42) |
| 엔진은 문서마다 동시에, 엔진마다 따로 떨어진 자식 프로세스 | 형식당 상한(`MAX_PER_TYPE`)은 0.2.0에 지움(pl-46). 옛 단계(phase)별 다시 돌리기는 없앰 | done | [pl-22](prd/transform.md#pl-22) |
| 시간 제한 = 쪽 수 × 10초(글자 엔진)·× 120초(VLM 엔진), 엔진 첫 문서는 최소 60초 + 시작 여유 10초. 넘으면 두 배로 한 번 더, 그래도 넘으면 실패 기록 | 큰 문서도 쪽 수만큼 시간을 받는다 | done | [pl-22](prd/transform.md#pl-22) |
| 그림 글자 인식 엔진(OCR, `rapidocr_ko`)은 기본으로 끈다 — 이미지·스캔은 VLM만. 일괄 실행 엔진은 낮은 우선순위(nice +10) | OCR은 VLM과 겹치고 느리다. 검색 서비스 자원을 덜 뺏는다 | done | [pl-22](prd/transform.md#pl-22) |
| VLM 동시 호출 수는 설정 키로 조절한다(`common.models.vlm.concurrency` 문서당 4, 전체 관문 12) | 엔진마다 따로 손잡이를 두지 않는다(허브 10-31). 실제 키는 여러 개 — 앵커 정리 필요 | done | [pl-43](prd/transform.md#pl-43) |
| 확장자 추가 1차: `.jpeg`·`.tif`·`.tiff`·`.bmp`(엔진은 `.jpg`와 같음), `.mhtml`(`.mht`와 같음), `.hwpx` 시험 | 형식마다 임시 견본으로 파싱 시험(`test_ext_formats.py`) | done | [pl-42](prd/transform.md#pl-42) |
| 확장자 추가 2차: `.hwp`·`.docm`·`.pptm`·`.rtf`·`.csv`·`.tsv`·`.md`·오픈문서·서식 파일·`.json`·`.xml`·`.log` | 엔진 파일은 그대로 두고 등록부(`registry.py`)에 "엔진별 추가 확장자" 표를 둬 엔진 지문을 지킨다. 0.2.0 · 사람 검토(등급 A) | todo | [pl-45](prd/transform.md#pl-45) |
| ~~엔진 구성 사본 파일(`stack-v*.json`)~~ | 대체됨 — 저장 구조 [pl-32](prd/load-schema.md#pl-32) | done | [pl-20](prd/transform.md#pl-20) |
| ~~파싱 코드를 `transform/parse/`로 옮기기~~ | 속도·품질 이득 없이 레이어 코드 지문(code_fp — 바뀌면 재처리)만 바뀐다(사용자 10-31) | dropped | [pl-17](prd/transform.md#pl-17) |
| 대표 결과 고르기(represent): 엔진 결과 중 정확하고 풍부한 것을 대표로 고르고, 줄 단위 투표로 합치고, 엔진 사이 라벨·값을 서로 확인한다(`represent.py`·`fuse.py`·`crosscheck.py`) | 엔진마다 결과가 다르다. 다음 단계로 넘기는 글은 가장 정확해야 한다 | done | [pl-04](prd/transform.md#pl-04) |
| 표·기호 다듬기 — 여러 엔진의 표를 본문 제자리에 넣고(`table_inline.py`), 표준 표·윗첨자 `^`·아래첨자 `_`, 파싱 품질 점검(`parse_qa.py`) | 표가 문서 끝에 따로 붙으면 검색 근거가 끊긴다 | done | [pl-04](prd/transform.md#pl-04) |
| 글자 PDF 속 스캔 쪽만 쪽 전체를 VLM으로 읽어 채운다(회전된 쪽·숨은 글자 겹친 쪽 각각 최대 20쪽) | 스캔 쪽 몇 장 때문에 스캔용 엔진을 통째로 돌리지 않는다 | done | [pl-22](prd/transform.md#pl-22) |
| 메일 첨부 — `.eml`·`.msg`의 첨부를 깊이 1·20 MB·10개까지 파싱해 본문에 `[첨부 <파일명>]` 절로 붙이고, 인용 스레드는 접는다(`attachments.py`) | 메일의 핵심 내용이 첨부에 있는 경우가 많다 | done | [pl-36](prd/transform.md#pl-36) |
| 그림 근처 맥락 — 캡션·본문 언급을 연결하고 값이 맞는지 표시한다(`context.py`) | 그림 설명을 본문과 함께 찾게 한다 | done | [pl-37](prd/transform.md#pl-37) |
| 그림 설명 — 그림마다 VLM 한 번(문서당 최대 20개, 짧은 변 64 px 미만은 뺌). 차트 XML·벡터 차트 값은 VLM 없이, 슬라이드·도형은 soffice로 그려 읽는다 | 차트·도식에는 글자 추출이 놓치는 값이 있다 | done | [pl-05](prd/transform.md#pl-05) |
| 그림 부가 기능 줄이기 — 화살표·겹침·도형 연결·Mermaid 따로 만들기를 VLM 한 번의 종류별 출력(도표 Mermaid·표 HTML·차트 값)으로 | 결정 10-31. **코드는 아직 옛 기능을 씀**(`figures/figures.py:29-38`) — 0.2.0(대표 결과 지문 p1 바뀜) | todo | [pl-05](prd/transform.md#pl-05) |
| 청크(검색 단위 조각) 나누기 — 기본 `structure`(800자, 제목 기준, 표는 통째). 큰 표 25행씩 나누기는 `CHUNK_TABLE=rows`일 때만 | 검색은 출처가 달린 짧은 조각 단위로 한다 | done | [pl-06](prd/transform.md#pl-06) |
| 문서 요약 = 앞부분 300자 발췌, 고객·계약 이름은 엔진끼리 서로 확인된 것만 | LLM 요약은 지웠다(op-08) | done | [pl-06](prd/transform.md#pl-06) |
| 임베딩(검색용 숫자 벡터) — 내부망 `api`(`EMBED_BASE_URL`·`EMBED_MODEL`)만(시험은 `none`) | 로컬 모델 길(bge-m3·e5 — sentence-transformers)은 0.2.0에 지움([pl-46](prd/transform-cleanup.md#pl-46)) — 패키지는 다음 이미지 빌드 때 requirements에서 뺌(todo) | done | [pl-06](prd/transform.md#pl-06) |
| ~~지식 그래프·개념 청크·그림 행·집계 사실 만들기~~ | 아무도 적재·조회하지 않았다(11-01 지움) | done | [pl-06](prd/transform.md#pl-06) |
| ~~구조화·적재 묶음 계약(`DOC_KEYS`) 고치기~~ | 서버가 이 검사를 쓰지 않는다. 0.2.0에 코드째 지운다(pl-46) | dropped | [pl-15](prd/transform.md#pl-15) |
| 분류 — 적재 때 gold에 넣기 전 SFDC·LAS 문서에 종류 라벨 `doc_class`(SFDC 5종·LAS 7종). 근거 = gold 분류 힌트 칸(판 0003 — 적재 때 EDW 조인) + 게시 .md 앞 8,000자 | 운영 분류와 결과가 같게(사용자 11-02) — 지시문·사용자 쪽 글 운영 글자 그대로, 적재와 같은 규칙(따로 고르지 않음), 내부 모델·`llm.chat`, 집합 밖·장애는 그 문서의 적재 실패(다음 실행에 다시), 재시도·수동 명령 없음, 이미 있는 라벨 안 덮음 | dev | [pl-33](prd/transform.md#pl-33) |
| ~~`ocr_vlm` 엔진·`vlm.model_alt`·안 쓰는 엔진 8개~~ 지움(엔진 18개 남음) | stack에 없어 안 쓰였다. 엔진 지문 바뀜(0.1.0, 등급 A) | done | [pl-31](prd/transform-cleanup.md#pl-31) |
| ~~다시 읽기(P2·P3)·스캔 중복 제거·렌더 OCR 신호~~ 지움 | 대표 결과 단계 정리. p1 지문 바뀜(0.1.0, 등급 A) | done | [pl-34](prd/transform-cleanup.md#pl-34) |
| ~~`parse_parallel`·`AUTO_REPARSE_CHANGED`·`figures_resume`~~ 지움 | 지문에 영향 없는 잔재. 증분 처리만 남긴다 | done | [pl-35](prd/transform-cleanup.md#pl-35) |
| 0.2.0 지문 묶음 정리 — 안 쓰는 엔진 5개(pdfplumber·pypdf·calamine·python_pptx·pymupdf4llm)·묶음 계약·OCR 대체 길·로컬 임베딩·첫 이관 호환 코드를 한 번에 지운다 | 지문이 바뀌는 정리를 서버 재처리 한 번에 모은다. 등급 A | todo | [pl-46](prd/transform-cleanup.md#pl-46) |
| `adk.py` — 지시문은 두고 장치는 `llm.py` 호출 하나로 줄임 · CPU 부하 고침 | 0.2.0 지문 배치(p1·s·r 지문). 사용자 11-02 | todo | [pl-46](prd/transform-cleanup.md#pl-46) |
| 엔진 지문(p0) 범위 확인 — 엔진 이름과 폴더 이름이 다른 엔진(html_stdlib·msg_extract·rapidocr_ko·office·pptx)을 고치면 다시 파싱되는지 | 놓치면 엔진을 고쳐도 낡은 결과가 남는다. 0.2.0 · 등급 A. 11-03: 문서별 재사용 열쇠(`engine_code_fp`)는 이미 맞았고, 층 지문 p0 범위만 엔진 파일을 하나도 안 담고 있었음 — 고침 | done | [pl-47](prd/transform-cleanup.md#pl-47) |
| 0.2.0 지문 배치 후속 — 같은 결과로 덜 읽고 덜 띄우기: 명부·사전·원본 해시·매니페스트·엔진 지문을 한 번만, 엔진 결과 한 번에 쓰기, 1건 중복 확인 자식 없이, 문 기다림을 잠금 밖에서 | 결과는 바이트 그대로(전·후 비교). 지문이 바뀌는 파일이라 pl-46과 같은 판 · 등급 A | done | [pl-49](prd/transform-cleanup.md#pl-49) |
| 층 지문 범위 바로잡기 + 단계 방향 자동 점검 — 결과를 바꾸는 파일 2개가 층 목록에서 빠졌고, DB 표 정의 한 줄에도 모든 층 지문이 바뀌었음. extract → transform → load 방향을 자동 점검 | 빠지면 고쳐도 옛 결과를 다시 쓰고, 넘치면 상관없는 수정에도 재처리 경보가 남. 0.2.0 · 등급 A | done | [pl-50](prd/transform-cleanup.md#pl-50) |

## 적재 (load) — 검색 DB(pgvector)·게시·저장 구조·DB 스키마
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 문서마다 고객·원천 메타를 EDW 조인으로 붙인다 — SFDC `FileStorageMap.content_version_id → ContentVersion → ContentDocumentLink`로 영업 기회(직접 > Task > Event, + 계정 직접 — 같은 단계 동률은 비움 · Quote 표는 지금 없음, 생기면 설정 한 줄) → `Account.Name`, CRMS `FileStorageMap_CRMS.rm_contract_code → RM_CM_PJTLIST`, LAS `FileStorageMap_LAS.manage_no → LAS.Contract`. 적재 때(`pipeline/load/edw_meta.py`, 표·칸 이름·단계는 설정 파일 `resources/config/edw_chain.yaml` — 운영 쪽이 고침, 사용자 11-02) 원천 스키마 `doc`(`client_edw`·원천 칸·`created_at`)에 쓴다 | 파싱·구조화는 이 값을 안 쓴다 — 매핑이 바뀌어도 다시 파싱하지 않는다(사용자 11-02). 외부 `file_meta_new.jsonl`은 지웠다. EDW를 못 읽으면 메타 없이 적재(`meta_missing`) — `--replace`로 다시 채움 | done | [pl-29](prd/load.md#pl-29) |
| 고객 조인 사슬을 운영 쪽이 고칠 수 있는 설정 파일로 — Quote 표는 지금 없음 | `resources/config/edw_chain.yaml`(사용자 11-02 — `feature/edw-chain-config`) | done | [pl-29](prd/load.md#pl-29) |
| 검색 DB(gold — pgvector) 표 6개(`load_run`·`doc`·`chunk`·`chunk_term`·`term_stat`·`corpus_stat`)와 뷰 1개(`v_chunk_source`)는 Alembic(DB 판 관리 도구)으로만 만든다 | 검색 MCP는 PG만 읽는다. 실행 중 DDL 금지 | done | [pl-07](prd/load.md#pl-07) |
| 문서 묶음 하나를 한 트랜잭션으로 적재한다(`pgvector_load load`) — 하나라도 실패하면 전부 되돌림 | 반쯤 들어간 문서가 검색에 보이지 않게 | done | [pl-07](prd/load.md#pl-07) |
| 이미 있는 문서는 `doc.file_path`가 같으면 건너뛴다. 바뀐 내용은 `--replace`로 | 내용 지문(sha) 칸이 없어 같은 경로에서 내용이 바뀌어도 건너뛴다(알려진 한계) | done | [pl-07](prd/load.md#pl-07) |
| 적재 전에 DB 판을 확인 — 판 기록이 없으면 경고 후 계속, 낮거나 모르는 판이면 종료 2. `--replace`는 `load_run` 표가 있는 우리 스키마에서만 | 남의 스키마나 옛 판 DB를 망가뜨리지 않게 | done | [pl-07](prd/load.md#pl-07) |
| 처음 쓰는 PG에는 `vector` 확장을 관리자가 한 번 만든다(`CREATE EXTENSION vector`) — 없으면 적재가 멈춘다 | 서버 계정은 보통 우리 스키마 권한만 있다. 서버 절차 문서에 이 단계가 빠져 있다(운영 고침 묶음) | done | [pl-07](prd/load.md#pl-07) |
| 적재는 더하고 고치기만 하고 지우지 않는다(`--prune` 없앰). 원천에서 지워진 문서·실패 문서는 로그에만. 원본 경로는 원천 스키마 5벌을 통틀어 하나 — `--replace` 없이 이미 있으면 건너뛰고, `--replace`면 다른 원천 스키마의 옛 사본을 지우고 옮긴다 | 건너뛴 문서까지 지워지던 문제(C-60). 경로가 바뀐 옛 행은 사람이 지운다 | done | [pl-13](prd/load.md#pl-13) |
| ~~배포 때 `chunk.clients`를 `doc.clients`로 채운다~~ | 11-02(pl-28) 지움 — 청크·문서의 본문 고객 칸과 backfill을 없앰(고객은 `client_edw`만) | done | [pl-14](prd/load.md#pl-14) |
| 임베딩 없음(`PIPE_EMBED=none`)이면 적재를 시작할 때 거부한다 | 검색에는 벡터가 필수. 11-03 — `pgvector_load`가 판 확인·배포·적재 전에 종료 코드 2로 거부 | done | [pl-16](prd/load.md#pl-16) |
| 색인 비교 예시 `index_a`·`index_b`(`compose.index.yml`) 지우기 | 끝까지 돌리면 실패한다(C-32) — 11-01 이름 있는 색인째 지움(mc-16) | done | [pl-19](prd/load.md#pl-19) |
| 게시(publish — 파싱 결과를 Object Storage에 올리고 EDW `AI.ParsingMeta`에 기록) — 대표 `.md`와 엔진별 원결과를 올리고 원본 파일은 올리지 않는다 | 다른 팀은 결과를 Object Storage와 ParsingMeta에서 읽는다 | done | [pl-09](prd/load.md#pl-09) |
| ParsingMeta에는 INSERT만 — 키 (`source_system`, `source_key` = 원본 전체 키)가 이미 있으면 건너뜀, UPDATE 없음 | 상태를 고쳐 쓰는 길은 10-31에 지웠다 | done | [pl-09](prd/load.md#pl-09) |
| DRM(`skipped_drm`)·실패(`failed`) 문서는 EDW에 쓰지 않고 `output/publish/excluded_<날짜>.md` 보고서에만. 업로드 대상 상태는 `load.publish.upload_statuses`(기본 ok·partial) | 깨진 결과가 다른 팀에 넘어가지 않게 | done | [pl-09](prd/load.md#pl-09) |
| 게시 버킷이 원천 원본 버킷과 같으면 게시를 거부한다 | 원본 덮어쓰기를 막는다. 단, `run_docs`가 이 검사를 끈다(`PM_BUCKET_SKIP_OVERLAP_CHECK=1`) — 확인 필요 | done | [pl-09](prd/load.md#pl-09) |
| 게시는 늘 하고 게시 대상(버킷·접두)은 필수 — `local`·`dev`는 로컬 대역이나 실제 접속, `prd`는 실제 접속만 | `run_docs`는 문서마다 늘 게시하고 버킷·접두가 없으면 시작을 거부한다 | done | [pl-26](prd/load.md#pl-26) |
| FAQ를 다시 올리면 gold faq의 문서·청크를 모두 지우고 지금 FAQ 파일 전체를 다시 적재(판을 잇지 않음) | pl-13 "지우지 않음"의 FAQ 예외(등급 A). 11-03 사용자 — 판 잇기 없이 전체 교체 | done | [pl-41](prd/load.md#pl-41) |
| ~~수동 갱신 명령 2개(분류만 / EDW 메타만)~~ | `load --replace`나 다시 실행으로 대신(사용자 10-31) | dropped | [pl-40](prd/load.md#pl-40) |
| 정형 DB `struct` 스키마(마스터·문서 대장·표·칸)를 코드에서 모두 없앤다. 엔진 구성은 파일만 | 쓰이지 않았다(서버 `doc_registry` 0행). 서버에 남은 표는 DB 담당자가 정리 | done | [pl-08](prd/load.md#pl-08) |
| 문서 대장(`doc_registry`)·숨김(`doc_hidden`)·원천 삭제 처리를 모두 지운다. 서버는 PG가 없으면 로컬 대체 DB로 바꿔 타지 않고 멈춘다 | 빼야 할 문서는 원천에서 지우거나 사람이 SQL로. 늘 꺼져 있던 source.json 게시 가드는 11-02에 지움(알려진 실패 0) | done | [pl-12](prd/load.md#pl-12) |
| 알려진 실패 0 — 쓰이지 않는 게시 가드와 `test_publish_guard` 지우고 `known_fail.txt` 비움 | 사용자 11-02 | done | [pl-12](prd/load.md#pl-12) |
| 마스터 표 — 용어집·고객 명부 CSV 여섯 개를 검색 PG `<PG_SCHEMA>_master`로(Alembic 갈래 `master` · `dbtool master load`가 git CSV로 통째로 바꿈). 구조화 고객 판별과 검색이 PG에서 읽고, `gold_version` = `<VERSION>+m<마스터 해시 8자>` | 원본은 git CSV. 대표 결과(silver)는 마스터를 읽지 않는다(ETL 규칙, 사용자 11-03). 서버는 마스터를 못 읽으면 시작 안 함 | dev | [pl-38](prd/load.md#pl-38) |
| (잠재 문제) 같은 문서의 다른 판(`s3_key` 다름) 묶기 — 검색 '최신' 질문에서 옛 판이 위로 올 수 있음, 필요해지면 다시 설계 | 판 묶음(`family`, id_patterns)을 지움(사용자 11-03) | todo | [pl-38](prd/load.md#pl-38) |
| 저장 자리 셋 — 파싱 결과 저장본(silver)은 Object Storage 문서 폴더(이름 = `s3_key`로 만든 uuid5), 메타는 EDW ParsingMeta, 검색 DB(gold)는 pgvector | 로컬에는 로그·임베딩 캐시만. 다시 처리하면 같은 폴더를 덮어쓴다 | todo | [pl-32](prd/load-schema.md#pl-32) |
| 같은 `s3_key`가 FileStorageMap에 여러 행이면 `created_at`이 가장 늦은 행만. 새 행은 `file_size`가 같으면 건너뛰고 다르면 같은 `doc_id`로 다시 처리, 밀려난 행은 EDW `SupersededRow`에 | 원본을 받지 않고 판별한다(같은 크기로 덮어쓴 경우는 놓침 — 받아들임) | todo | [pl-32](prd/load-schema.md#pl-32) |
| 실행을 넘어 남는 로컬 완료 표시(`_DONE`, `runs.jsonl` 재사용)를 없애고 실패 문서는 다음 실행이 다시 고르게 | 저장 자리는 하나라는 원칙 | todo | [pl-32](prd/load-schema.md#pl-32) |
| DB 스키마 명세는 `docs/architecture/db_schema.md` 하나(검색 DB·EDW·마스터 CSV의 칸·타입·쓰고 읽는 코드), `test_db_schema.py`가 대조 | 정의가 흩어져 있었다. 사용자·DB 담당자 승인 대기 | dev | [pl-25](prd/load-schema.md#pl-25) |
| ParsingMeta에는 파싱 정보만(원천 키·상태·silver 위치·엔진·`gold_status`·`silver_version`·`gold_version`·`sha256`), 고객·분류 라벨 같은 파일 메타는 검색 DB `doc`에만 | 중복 적재를 없앤다. 운영이 더한 칸은 0.2.0에 지운다(D-3). `stack_version`은 만들지 않음(11-02) | dev | [pl-25](prd/load-schema.md#pl-25) |
| 문서 키는 원본 경로 하나 — 검색 DB `doc.file_path` = Object Storage 원본 경로 = EDW `s3_key`(청크는 `doc_id`만), ParsingMeta와 이 값으로 잇는다 | sha256 `doc_key`는 검색 DB에 안 둔다(ParsingMeta `sha256`만). 사용자 11-02 — 경로 칸 하나 | dev | [pl-25](prd/load-schema.md#pl-25) |
| 원천 시스템별 PG 스키마 5벌(`<PG_SCHEMA>_sfdc`·`_crms`·`_las`·`_faq`·`_other`), 각자 `doc`·`chunk`·BM25 표, `doc_id` 시퀀스는 기준 스키마 하나를 함께 | 원천마다 메타 칸이 다르다. 판 0002 — 전체 다시 적재·MCP `source_system` 필수(등급 A, 11-02) | done | [pl-28](prd/load-schema.md#pl-28) |
| 원천 = `FileStorageMap.source_system`(`SFDC`·`CRMS`·`LAS`·`FAQ`, `-test` 붙어도 같음), 비었거나 다른 값이면 `other`. `faq` 스키마만 `chunk.faq_group` 칸 | 원본 경로 첫 마디로도 정함 | done | [pl-28](prd/load-schema.md#pl-28) |

## 검색 MCP (mcp) — AI 클라이언트가 부르는 도구 서버(이미지 `mcp-server`)
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| `search` — 질문으로 근거 찾기. 혼합 검색 = 뜻이 비슷한 글(벡터) + 낱말 점수(BM25) + 드문 ID 일치를 순위 합치기(RRF)로 묶음 | 클라이언트가 출처 달린 근거를 얻는 단 하나의 입구. 가중치 벡터 1·BM25 1·ID 2(`search.weights.*`) | done | [mc-01](prd/mcp.md#mc-01) |
| `search` 입력 `k` 기본 8·상한 50, 근거 칸 `chunk_id`·`source_uri`·`page`·`bbox`·`text`·`score`·`via`, 근거 상태 `evidence_status` found·weak·none. 응답은 20,000바이트까지(낮은 순위부터 줄임) | 근거 상태는 표시만 하고 근거를 빼지 않는다. 최고 점수가 `search.min_score` 미만이면 weak | done | [mc-01](prd/mcp.md#mc-01) |
| 검색 저장소는 검색 DB(gold — pgvector) 하나. PC는 SQLite 대역(`pg_standin`) | PC 전용 묶음 검색은 지웠다(11-01) — 서버·PC가 같은 SQL | done | [mc-01](prd/mcp.md#mc-01) |
| 질문 + 하드 거르기(`client`·`client_like`·`source_system`·`project_id`·`division`·`service_type`) — 후보 `min(50, max(3k,30))`개에서 범위 안만 남김 | 조건 밖 문서가 근거에 섞이지 않게 | done | [mc-01](prd/mcp.md#mc-01) |
| 질문 넓히기 — 용어집으로 BM25 낱말을 더함(동의어 1.0·약어 0.8·약한 것 0.3), 고객 별칭 최대 20토큰 | 동의어·약어로 물어도 찾게 | done | [mc-02](prd/mcp.md#mc-02) |
| 고객 2명 이상 비교 질문은 고객별(최대 4명)로 나눠 찾고 번갈아 합침. 집계형 질문은 BM25 가중치 0.2 | 한 고객이 근거 자리를 독차지하지 않게 | done | [mc-02](prd/mcp.md#mc-02) |
| 고객 거르기는 EDW에서 붙인 고객(`client_edw`)만 본다(정확 일치, 목록은 OR, `client_like`는 부분 일치) — 본문 라벨 순위 올리기(AD38·BR23·BR50)는 지움 | 답이 고객을 섞으면 안 된다(C6, 11-02). 별칭 그룹은 pl-38 | done | [mc-05](prd/mcp.md#mc-05) |
| 이름만 다른 사본은 하나로(사본 묶음 — 남김) · ~~"최신"을 묻는 질문은 같은 문서군의 새 판을 위로(`common.text.search_recency`)~~ | 최신성 순위는 판 묶음(family)과 함께 11-03에 지움(사용자 — pl-38). 잠재 문제는 pl-38 행 | done | [mc-05](prd/mcp.md#mc-05) |
| ~~집계 답(건수·합계·환율 메모·LLM 라우터)과 그 길이 읽던 지운 칸·표~~ | 11-01 지움 — 숫자 질문은 `query_edw`로 | done | [mc-04](prd/mcp.md#mc-04) · [mc-11](prd/mcp.md#mc-11) · [mc-12](prd/mcp.md#mc-12) |
| ~~숨김 문서를 검색에서 빼기~~ | 숨김 기능 자체를 지움(pl-12) | dropped | [mc-14](prd/mcp.md#mc-14) |
| 검색기가 지운 칸(`file_sha256` 등) 대신 문서 키 `doc_key`(= `file_path`)로 읽음 | 새 묶음으로 검색기를 만들면 실패하던 문제 | done | [mc-10](prd/mcp.md#mc-10) |
| 질의 기록은 파일 `qa_log.jsonl`만(호출자·질문·근거·지연), 90일 보관·24시간마다 정리 | PG `qa_log` 표는 마이그레이션에 없었다. 토큰·원문은 남기지 않는다 | done | [mc-13](prd/mcp.md#mc-13) · [mc-09](prd/mcp.md#mc-09) |
| 대표 파싱 결과 주소 `rep_uri`(`s3://<bucket>/<key>`)는 원문 도구가 부를 때 ParsingMeta에서 읽는다(검색 근거 12칸에는 없음) | 사용자 11-01 — 검색 DB에는 거르기 메타만(C8 바뀜) | done | [mc-15](prd/mcp.md#mc-15) |
| `search` 운영 계약 — `question` 필수, `source_system` 필수·값 하나(`SFDC`·`CRMS`·`LAS`·`FAQ`·`Other`, `-test` 별칭도) | 운영 명세와 같게. 계약 변경이라 사람 검토(등급 A), 0.2.0 | done | [mc-16](prd/mcp.md#mc-16) |
| 거르기 추가 — `FAQ_group`·`doc_class`·`sf_op_id`·`sf_op_name`·`contract_id`·`created_since/until`(시간대 없으면 한국 시간) | 모두 AND, 목록은 OR. 맞는 값이 없으면 오류가 아니라 빈 결과 | done | [mc-16](prd/mcp.md#mc-16) |
| 출력 줄이기 — 맨 위 `question`·`evidence[]`·`evidence_status`·`filter`·`scope_docs`, 근거 키 `chunk_key` = `<doc_id>:<seq>` | `file_path`·`index_id`·`subs`·`images`·`notes`·`ms` 등을 지운다 | done | [mc-16](prd/mcp.md#mc-16) |
| 원문 도구 2개 — `list_doc_fulltext`(목록)·`get_doc_fulltext`(원문). 거르기는 원천 스키마 `doc`, 대표 결과 위치·`doc_key`는 부를 때 ParsingMeta에서 | 사용자 11-01 — 검색 DB에는 거르기 메타만(EDW를 못 읽으면 `registry_unavailable`). 새 도구라 등급 A, 0.2.0 | done | [mc-17](prd/mcp.md#mc-17) |
| 검색이 실행 중에 묶음 파일(`docs.jsonl`·`chunks.jsonl`·`meta.json`)을 읽지 않고 문서 날짜·임베딩 모델·차원을 PG에서 읽는다(판 0004 — gold doc `content_date`(문서에 적힌 날짜)·`embed_model`, `corpus_stat.dim` 지움) | 서버에서 묶음 경로를 맞출 필요가 없어진다. 검색 동작이 바뀌는 일이라 자기 PR + 평가 | done | [mc-19](prd/mcp.md#mc-19) |
| `query_edw` — EDW 읽기 전용 SQL(SELECT/WITH 한 문장, 읽기 계정), 1,000행(운영 서버와 같음 — 사용자 11-03)·20초·2 MB 상한 | 정형 숫자는 EDW에서 답한다. 표 허용 목록은 `tables_strict`를 켤 때만(기본 꺼짐) | done | [mc-06](prd/mcp.md#mc-06) |
| `edw_meta` — 정적 자료(`catalog.json`+`columns.jsonl`)로 스키마 → 표 → 칸 찾기, 모르는 이름은 비슷한 이름 제안, 응답 200 KB 상한 | SQL을 쓰기 전에 이름 확인. 표본 값은 내지 않는다 | done | [mc-07](prd/mcp.md#mc-07) |
| `parse_document` — 파일 1건(inbox 경로 또는 base64, 100 MB까지 — 두 길 같은 칸 `ops.runtime.parse_max_mb`, 사용자 11-03)을 파싱 서비스(127.0.0.1:8766, 토큰)로 넘겨 대표 본문·표를 받음. 300초 넘으면 `job_id` | 아직 적재되지 않은 파일을 바로 물을 때 | done | [mc-08](prd/mcp.md#mc-08) |
| 스캔 PDF(글자층 20자 미만) 파싱 다시 지원 — 지금은 빈 결과 + 안내만 | 어떤 엔진(OCR·VLM)을 쓸지와 응답 시간을 정해야 함(등급 A) | todo | [mc-18](prd/mcp.md#mc-18) |
| 서버는 `/mcp`(기본 127.0.0.1:8765) 또는 `--stdio`로 뜬다. 내부망 주소만, 0.0.0.0 거부, 루프백이 아니면 `MCP_TOKEN` 필수 + DNS 리바인딩 막기. 서버에서 PG 접속 칸이 비면 시작 거부 | 공용 내부 서비스라 위험한 노출을 거부 | done | [mc-09](prd/mcp.md#mc-09) |
| 과부하 보호 — 동시 8개, 대기 32개(동시 × 4) 넘으면 바로 `busy`, 도구당 30초(`parse_document`는 자기 시간 + 10초) | 늘 떠 있게. `/health`는 예열 중 503, 새 적재는 30초마다 확인 | done | [mc-09](prd/mcp.md#mc-09) |

## 운영 (ops) — 서버 러너(run_docs)·실행 관리·종료 정리·계정·모델 가드·설정
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 서버 입구는 호스트의 `run_docs.py` 하나 — 상주 컨테이너 안에서 `docker exec`로 일을 시킨다. 이미지 명령은 `parse`·`publish`·`migrate`·`show-stack`·`idle`·`selftest` 등 | night·full·structure·load·trigger 서버는 11-01에 지웠다 | done | [pl-10](prd/ops.md#pl-10) |
| run_docs 흐름 — 문서마다 미리 받기 → 파싱 → 구조화+적재 → 게시 → 임시 폴더 삭제, 배치 장벽(앞 묶음이 다 끝날 때까지 기다리기) 없음 | 문서 수천 건을 사람 없이 처리 | done | [pl-10](prd/ops.md#pl-10) |
| 새 문서만 처리(목록 − ParsingMeta 끝난 행) — 파싱 입구는 구현됨(수집 표). 전체 재파싱은 사람이 전체 e2e로만 | 지문이 바뀔 때 전체 자동 재파싱을 하면 밤 시간을 넘긴다 | done | [pl-23](prd/ops.md#pl-23) |
| run_docs 대상 고르기를 위 규칙에 맞춘다 — 파일 이름 키워드(`--filter RFP,proposal`)·`--start-offset` 뒤 `--skip-done`이 ParsingMeta 끝난 행(ok·partial — gold_version도, skipped_dup)을 뺀다 | 새벽 배치는 이름에 RFP·proposal이 든 문서만 처리한다(키워드가 정기 운영에 맞는지는 C-72 ③) | done | [pl-23](prd/ops.md#pl-23) |
| 새벽 배치는 `ops.nightly.time`·`max_docs`·`deadline` 셋이 모두 있을 때만 돈다(하나라도 비면 안 돎 — 사용자 11-02) — systemd 타이머가 5분마다 `trigger.sh scheduled` → `run_docs.py --start-offset 0 --skip-done --max-docs --deadline` | 지금 서버는 비워 둠(꺼짐) — 켜는 것은 사람(C-72) | done | [pl-23](prd/ops.md#pl-23) |
| 전체 e2e는 local·dev·prd 셋에서 — 전체 문서 실행은 prd에서만 새 원천별 스키마 이름(새 `PG_SCHEMA`)으로, 옛 gold·`struct` 스키마는 2주 뒤 DB 담당자가 백업하고 지움 | 판 0002가 기준 스키마의 옛 표를 지운다. 사용자 11-02 | todo | [pl-23](prd/ops.md#pl-23) |
| 새벽 배치 칸 — 시작 시각·문서 수 상한·마감 시각(비면 안 돎), 칸 이름 하나로(`pipeline.host.nightly.time` ↔ `ops.nightly.time` 어긋남 고침) | 사용자 11-02 | done | [pl-23](prd/ops.md#pl-23) |
| 문서별 순서를 파싱 → silver 게시 → 원본 임시 파일 삭제 → gold로 | 게시가 gold를 기다리지 않고(게시 스레드 따로), 원본은 게시가 성공했을 때만 지운다(11-03) | done | [pl-24](prd/ops.md#pl-24) |
| gold 실패면 ParsingMeta 행은 남기고 새 칸 `gold_status`=failed·이유. 파싱이 통째로 실패하면 EDW에 쓰지 않고 로그에만 — 다음 실행이 다시 고른다 | gold는 silver에서 다시 만들 수 있다. 행 남김·로그·파싱 실패 길은 됨(11-03). 칸 추가는 DB 담당자 몫(등급 A — C-81) | partly done | [pl-24](prd/ops.md#pl-24) |
| run_docs 종료 코드 — 대상 0건 = 0, 실패 있음 = 1, 마감 도달 = 75 | 스케줄러가 실패를 본다(C-33). 실패와 마감이 함께면 1 · 다른 run_docs가 도는 중도 75(11-03) | done | [pl-18](prd/ops.md#pl-18) |
| 새벽 run_docs에 문서 수 상한·마감 시각·겹침 막는 잠금 | `--max-docs`·`--deadline`(11-02) + `run_docs.py` 안 `flock` 잠금(`batch_progress/run_docs.lock`, 11-03). `TimeoutStartSec=6h`는 마지막 안전판 | done | [pl-18](prd/ops.md#pl-18) |
| 레인 3개(light·medium·vlm, 수집 표의 나누기 기준)마다 전담 워커(자기 레인만)·공유 워커(자기 레인 먼저, 비면 가장 긴 다른 레인) — `ops.run_docs.<레인>_dedicated`·`_shared` 기본 각 1 | 규칙을 표 하나(`pick_lane`)로 모으고 설정으로 조정 | done | [rn-01](prd/ops.md#rn-01) |
| vlm 레인 동시 파싱 상한 `ops.run_docs.vlm_cap` = 2. `warm`·`vlm_cap`이 1 미만이거나 워커가 없는 레인이 있으면 시작 거부 | GPU 예산을 지키고 끝나지 않을 설정을 막는다 | done | [rn-01](prd/ops.md#rn-01) |
| 미리 받기 상한 `ops.run_docs.warm` = 20, 구조화 워커 `struct_workers` = 2, 중간 대기열 상한 `struct_backlog`(기본 구조화 워커 × 2, 0이면 없음) | 구조화가 느릴 때 파싱 결과가 디스크에 쌓이지 않게 | done | [rn-02](prd/ops.md#rn-02) |
| 대기열 길이를 상태가 바뀔 때마다 `batch_progress/queue_depth.jsonl`에 한 줄 | 대기열 길이와 구조화 대기 시간의 관계를 잰다 | done | [rn-02](prd/ops.md#rn-02) |
| MCP `parse_document`(사람이 기다리는 요청)에 CPU를 먼저 준다 — 전용 컨테이너 + cgroup CPU 가중치 최고(10-31 결정). 11-03 재확인: 일괄 `data-pipeline`과 뗀 전용 `data-pipeline-mcp`(cpu_shares 4096 > 1024) | nice는 컨테이너끼리는 효과가 없다(C-65 ⑥) | dev | [rn-03](prd/ops.md#rn-03) |
| MCP 업로드 작업이 있으면 medium 전담 워커를 쉬게 한다(이름 날짜가 어제·오늘·내일인 작업 폴더만 감시) | 5초마다 폴더 전체를 훑던 부담을 줄인다 | done | [rn-04](prd/ops.md#rn-04) |
| 프로세스가 끝날 때(정상·오류·SIGTERM) 임시 설정 덮기 파일·PID 기록을 지우고 자식을 끝내 회수(SIGTERM → 10초 → SIGKILL, 종료 143) — `common/core/exitclean.py` 한 곳 | 임시 파일이 쌓이고 soffice 좀비가 남던 문제 | done | [pl-27](prd/ops.md#pl-27) |
| ~~강제 종료(SIGKILL·OOM)로 남은 임시 설정 파일을 다음 시작 때 지우기~~ | 남아 있어도 된다(사용자 10-31) | dropped | [pl-44](prd/ops.md#pl-44) |
| EDW 접속 설정은 `common.connections.rdb` 하나(settings `required.edw`)에 계정 둘 — 읽기(목록·FileStorageMap·ParsingMeta 조회·MCP), 쓰기(ParsingMeta 게시만). MCP 프로세스에서는 쓰기 계정을 비운다 | 같은 값이 설정 블록 넷에 반복되던 것을 없앰. 등급 A | done | [op-03](prd/ops.md#op-03) |
| PC 대역 EDW는 sqlite 파일 하나(`valid_env/edw/edw.sqlite`)를 `AI`·`CRMS`·`LAS`·`SFDC`로 붙여 같은 SQL이 돌게 | PC에서 운영 EDW에 접속하지 않는다 | done | [op-03](prd/ops.md#op-03) |
| 모델 역할 llm·vlm·embed(OpenAI 호환). 외부 주소는 `common.models.<역할>.allow_external`이 켜지고 `RUN_ENV=local`일 때만, 서버는 거부. 내부 판정 = 해석된 주소가 사설 IP(또는 `internal_ip_ranges`) + 호스트 접미(`internal_host_suffixes`) | 폐쇄망 밖으로 데이터를 보내지 않는다. 접미 목록에는 전체 호스트 이름이 아니라 상위 도메인을 적어야 맞는다(운영 고침 묶음) | done | [pl-11](prd/ops.md#pl-11) |
| 비용 상한 — `common.models.guard.budget_usd`(누적 $)·`max_calls`·지출 장부 `spend_file`·`no_paid_calls` | PC 호출을 싸게 유지. 응답 캐시·가짜 LLM도 여기 | done | [pl-11](prd/ops.md#pl-11) |
| 모델 — 개발 서버부터 내부망 GLM, PC는 OpenRouter | 사용자 11-02 | done | [pl-11](prd/ops.md#pl-11) |
| JSON Lines 사건 기록(공통 키·로그 수준·비밀 가림) + DB 감사·성능 로그 — 두 앱 `common.core.jsonlog`, MCP 도구 호출마다 `applog.mcp_call`, 파이프라인 실행·단계 `applog.pipe_run`·`pipe_event`(`dbtool up --target applog`) | 사건·감사·성능을 같은 형식으로 남긴다(feature/logging, 서버 적용 전 — C-79·C-80) | dev | [op-01](prd/ops.md#op-01) |
| 실행 환경 `RUN_ENV`(`required.env.run_env`)는 `local`·`dev`·`prd`만, 어디서나 필수 — `stage`나 모르는 값이면 시작 거부 | `stage`는 `prd`와 똑같이 동작했다 | done | [op-02](prd/ops-settings.md#op-02) |
| 서버(`dev`·`prd`)는 가짜 LLM(`dev.llm_fake`)이 켜져 있거나 설정 파일을 못 읽으면 시작 거부 | 서버에서 가짜 답이 도는 것을 막는다 | done | [op-02](prd/ops-settings.md#op-02) |
| 설정은 settings.yaml 하나 — `settings.sample.yaml`에 모든 키가 기본값과 함께(`python -m common.config.sample`로 생성) | 파라미터 파일 분리안을 대신했다 | done | [op-05](prd/ops-settings.md#op-05) |
| 배치 — 맨 위 `required`(필수·비밀) → 역할 절 7개 → `tuning`(내부 조정값). 옛 배치는 시작 거부, `python -m common.config.migrate`로 변환 | sample과 실제 파일의 차이를 줄였다 | done | [op-08](prd/ops-settings.md#op-08) |
| 설정 이관은 옛 배치 settings.yaml → 새 배치만 — env 파일 옮기기·`--compare` 지움 | 운영 서버는 0.1.0(settings.yaml 하나). 사용자 11-02 | todo | [op-08](prd/ops-settings.md#op-08) |
| 하드코딩 0 — 설정 값은 settings.yaml이나 이미지 기본값 표(`settings.py`)에서만, 호스트 셸은 `settings_env.sh`가 준 값만, PG 자동 찾기 없앰(PG 접속 필수) | 한 곳을 바꾸면 나머지가 어긋나던 문제. 남은 복사본 있음(`/srv/rag/code/live` 기본값 등) | done | [op-09](prd/ops-settings.md#op-09) |
| 환경마다 다른 경로·접속은 settings.yaml 필수(코드 기본값 없음) — 컨테이너 안 경로는 이미지 기본값 표 하나만, 호스트 `PATCH_CODE` 기본값 지움 | 사용자 11-02 | dev | [op-09](prd/ops-settings.md#op-09) |
| 은퇴한 설정 지우기 — `common.paths.korean_font`·`eval_sets_dir` 등(남아 있으면 경고만) | 지문이 바뀌어 0.1.0 묶음에 | done | [pl-21](prd/ops-settings.md#pl-21) |
| 아무도 안 읽는 env 4개(`FIG_OCR_BUDGET`·`SERVICE_MASTER_CSV`·`DIVISION_MASTER_CSV`·`PROD_MASTER_CSV`)를 run_docs 명령에서 뺌 | C-51 | done | [pl-30](prd/ops-settings.md#pl-30) |

## 테스트·평가 (test) — 변경을 어떻게 증명하나
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 시험 층 둘 — `tests/server/`(이미지 안 반입 시험, `python -m pipeline.cli selftest`, 네트워크 없음)와 `tests/general/`(PC 전용 — PG·Docker·느린 것) | 반입 판정은 폐쇄망 이미지 안에서 돌아야 한다 | done | [e2-02](prd/test.md#e2-02) |
| 기준선 — 바꾼 뒤 시험 결과가 기준선보다 나빠지면 안 된다(값은 앵커) | 기준선 숫자는 11-01 삭제 뒤 다시 재야 함 | done | [e2-02](prd/test.md#e2-02) |
| 알려진 실패 목록(`deploy/release/known_fail.txt`·`GENERAL_KNOWN_FAIL`) — 통과하면 "XPASS — 지울 수 있음" 경고 | 새 실패를 목록에 넣는 것은 고장을 숨기는 일 — 사람 승인 필요 | done | [e2-02](prd/test.md#e2-02) |
| PC 시험 자식 프로세스는 개발자 `settings.yaml` 대신 시험 전용 바탕(`run_env: local`만)을 쓴다 | 공용 개발 PG를 건드리지 않게 | done | [e2-02](prd/test.md#e2-02) · [e2-11](prd/test.md#e2-11) |
| 이미지 반입 관문 — `build_ship.sh`로 빌드하고 `selftest_gate.sh`가 종료 코드가 아니라 `[판정]` 줄로 판단(알려진 실패 밖 FAIL 0) | 서버는 반입 시험을 통과한 이미지만 받는다 | done | [e2-08](prd/test.md#e2-08) |
| 코드만 바뀌면 오버레이 패치(코드 폴더만 바꾸는 배포, `make_patch.sh`) | 이미지를 다시 만들지 않는다 | done | [e2-08](prd/test.md#e2-08) |
| ~~시험을 바꾸면 새 이미지가 필요~~ | 이미지에 코드 폴더를 붙이는 방식(op-06)이라 시험도 코드 폴더에서 돌아 해소 | done | [e2-14](prd/test.md#e2-14) |
| PC 일반 시험의 옛 실패 정리 — 공용 PG를 읽던 3개는 고치고, 지운 모듈의 시험은 지움 | 리팩토링 전부터 있던 실패. 코드상 남은 실패 0(`GENERAL_KNOWN_FAIL = {}`) — 앵커 상태 확인 필요 | partly done | [e2-11](prd/test.md#e2-11) |
| 에이전트 시험 패키지 `example_agentic`을 저장소 안에서 찾게 — 지금은 없는 폴더를 봐서 `run_agent` 시험이 건너뛰어짐 | `paths.py`를 고치면 지문이 바뀌어 0.2.0에 | todo | [e2-15](prd/test.md#e2-15) |
| PC 스모크 — 문서 2~3건으로 파싱 → 임베딩 → 마이그레이션 → 적재 → 검색(README §4-4) | 릴리스 전에 사슬 전체를 증명 | done | [e2-01](prd/test.md#e2-01) |
| PC Docker 스모크(`valid_env/docker/smoke_test.sh`)를 다시 돌려 검색까지 가는지 확인 | mc-10은 고쳐졌고 다시 돌려 보기만 남음 | todo | [e2-13](prd/test.md#e2-13) |
| 시험 자료 `valid_env/` — 문서 `object_storage/{SFDC,CRMS}/<uuid>/<파일>`, 합성 EDW `edw/` | 서버와 같은 배치. 서버 반입 시험은 자료를 임시 폴더에 만들어 쓴다 | done | [e2-09](prd/test.md#e2-09) |
| ~~파싱 품질 평가·검색 평가(hit@k)·스택·모델 비교 도구~~ | e2-10에서 도구를 지움 — 필요할 때 다시 만든다 | done | [e2-03](prd/test.md#e2-03) · [e2-04](prd/test.md#e2-04) · [e2-06](prd/test.md#e2-06) |
| 답변 점검(PC 전용) — `validation/e2e/answer_gen.py`가 `rag_qa` 에이전트로 `search`·`edw_meta`·`query_edw`를 불러 답하고 인용을 규칙으로 점검 | MCP는 근거만 준다. 유료 호출은 예산 장부를 거친다 | done | [e2-05](prd/test.md#e2-05) |
| `query_edw` 값을 인용한 답은 인용 점검 실패로 기록하고 그대로 둔다 | 사용자 결정(바꾸지 않음) | done | [e2-12](prd/test.md#e2-12) |
| answer_gen 인용 버그 고침 — 오류 구분·JSON으로 못 바꾸는 값·객체가 아닌 답·다시 직렬화 | 시험 `tests/general/e2e/test_answer_gen.py` | done | [e2-19](prd/test.md#e2-19) |
| 분류 수용 보고서(개발 서버) — 사람 정답 CSV(`s3_key`·정답 분류)와 비교해 원천·라벨별 일치율·혼동표 | 회사 데이터라 git 밖. 통과 기준은 첫 결과를 본 뒤 정한다 | todo | [e2-20](prd/test.md#e2-20) |
| 검색 점검 페이지 `validation/search_ui`(기본 포트 8790, MCP `127.0.0.1:18765/mcp`) | 사람이 브라우저로 근거를 본다 | done | [e2-07](prd/test.md#e2-07) |
| ~~점검 페이지 고정 글 "10 documents (20 chunks)" 고치기~~ | 범위 축소로 뺌 | dropped | [e2-16](prd/test.md#e2-16) |
| PC 평가 도구는 검색 점검 페이지·답변 점검 둘만 남기고 나머지 도구·설정을 지움 | PC 전용 설정 약 50개의 관리 비용 | done | [e2-10](prd/test.md#e2-10) |
| 안 쓰는 함수·요건 없는 코드(시험만 부르는 것 포함)를 지움 | 죽은 코드 비용. MCP 도구 이름·입출력은 그대로 | done | [e2-17](prd/test.md#e2-17) · [e2-18](prd/test.md#e2-18) |

## 문서·릴리스 (doc) — 문서 배치·버전·이미지·서버 설치
| 요건(무엇을, 어디서) | 기준·이유 | 상태 | ID |
|---|---|---|---|
| 요건은 `docs/PRD.md` + `docs/prd/<카테고리>.md`, CLAUDE.md는 규칙·명령만, 지난 기록은 `docs/history/` | 겹치는 문서가 많고 요건이 흩어져 있었다 | dev | [do-04](prd/doc.md#do-04) |
| PRD 카테고리 재편(수집·변환·적재·운영 등, ID 그대로 — 3부 #85)과 PRD 표를 한눈에 읽히게 다시 쓰기(4부) | 사람이 요건을 바로 이해하게 | dev | [do-04](prd/doc.md#do-04) |
| 용어집 `docs/INDEX.md` `## Glossary` — 약어·옛 용어 대응, CLAUDE.md에는 링크 한 줄 | 옛 용어가 주석·기록에 아직 나온다 | done | [do-02](prd/doc.md#do-02) |
| `refactor.md`를 병합 결과와 맞춤 — 낡은 줄 정리, C 항목 → PRD 링크, 검토자 = 사용자(등급 A) | 교차 확인에서 낡은 줄이 나왔다 | done | [do-03](prd/doc.md#do-03) |
| `refactor.md`를 루트에서 `docs/refactoring/`으로(옮기는 커밋과 링크 고치는 커밋을 따로) | 루트에는 입구 파일만 | done | [do-01](prd/doc.md#do-01) |
| 버전은 루트 `VERSION` 하나(지금 0.1.0), 첫 태그 `v0.1.0` + 릴리스 노트 | 이미지 태그와 DB 버전 표기가 같은 값을 쓴다 | done | [op-04](prd/doc.md#op-04) |
| 코드 없는 실행 이미지(`data-pipeline-runtime`·`mcp-server-runtime`)에 코드 폴더를 `/app/deploy`로 읽기 전용 마운트 | 개발 서버에서 이미지를 다시 만들지 않고 코드만 바꿔 시험 | done | [op-06](prd/doc.md#op-06) |
| 시작 검사 `runtime_entry.sh` — 코드 폴더가 없거나 의존성 지문(`DEPS_HASH`)이 다르면 종료 2, 이미지 판·코드 커밋을 한 줄 기록 | 의존성 어긋남이 나중에 조용한 오류로 터지지 않게 | done | [op-06](prd/doc.md#op-06) |
| 개발 → 운영 굽기 `bake.sh` — 개발에서 쓴 실행 이미지 + 시험한 코드 폴더로 `Dockerfile.bake`(네트워크 없이), 반입 판정 뒤 저장·분할 | 운영에는 개발에서 시험한 그대로 올라간다 | done | [op-07](prd/doc.md#op-07) |
| 운영(prd) 이미지에 settings.yaml(비밀 포함)도 굽는다 — 🔒 검토 등급 A(비밀 처리) | 이미지 파일 = 비밀(반입 경로만), 키를 바꿀 때마다 다시 굽기. 사용자 11-02 | todo | [op-07](prd/doc.md#op-07) |
| 서버 설치 길은 하나(README §5-0·§5-3). 컨테이너 도구는 셸 env > `ops.host.docker` > podman > docker. 이미지는 `load.sh`로(45 MB 조각) | 문서마다 절차가 달랐다. 서버 기본 도구는 podman | done | [op-10](prd/doc.md#op-10) |
| 0.2.0 올리기·되돌리기(release-and-patch §5-7) — DB 백업 → `migrate check` → `up`, 되돌릴 땐 `settings.yaml.0.1.0` 복원, 재처리 동안 밤 타이머 멈춤 | DB·EDW·전체 재처리가 함께 바뀐다 | done | [op-10](prd/doc.md#op-10) |
| 일회성 작업 컨테이너 지움 — 운영 작업·`dbtool`·`migrate`는 상주 `data-pipeline`에 `exec`, 이미지 점검(`docker run --rm … selftest`)은 그대로 | 사용자 11-02 | dev | [op-10](prd/doc.md#op-10) |
