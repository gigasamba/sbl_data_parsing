# 릴리스 이력 — 10-16 버전 설치 순서 · 10-21 오버레이 패치 번들

10-30(do-04)에 [server-guide.md](../operations/server-guide.md#5-릴리스--실행-이미지--코드-폴더)의 §8·§9에서 옮긴 기록이다. 내용은 그때 기준 그대로 두었다(이미지 3개·`docker/` 경로·옛 env 이름 — 지금 절차는 server-guide.md). 이 파일 안의 §3-3·§4·§5·§5-1·§5-2·§7은 server-guide.md의 절이다. 링크만 이 폴더 기준으로 고쳤다.

## 8. 10-16 판 설치 순서(1회 — 폴더 분리·output·3이미지)

> **기록(10-16 판)** — 아래 표의 이미지 3개·`docker/` 경로·`DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`는 그 판의 것이다. S6b(10-27, D-020)부터 이미지는 `data-pipeline`·`mcp-server` 2개, 스크립트는 `deploy/{docker,release,host}/`, 이미지 변수는 `DATA_PIPELINE_IMAGE`·`MCP_SERVER_IMAGE`, 컨테이너는 `data-pipeline-parse`·`data-pipeline-structure`·`mcp-server`, systemd는 `data-pipeline-nightly`·`mcp-server-keepalive`다 — 전환 절차는 §5-2 S6b 줄과 `refactor.md` C-04·C-29.

이번 판은 경로가 전부 바뀌어 덧씌우기가 아니라 **새 이미지 판 + 전체 재배포**다(§4·§5). 기준 커밋은 PC가 알려 준 main(10-14 컷 d82d6519 이후 통합 시험 수정 포함). 순서대로:

| # | 할 일 | 확인 |
|---|---|---|
| 1 | PC: 이미지 3개 빌드(`--target parse`·`structure`·`retrieval`, §5-1) — 옛 rag-core·rag-all·answer-agent 이미지는 없음(Answer Agent는 개발 서버 네이티브) | `bash docker/selftest_gate.sh docker run --rm <이미지> selftest` 3개 다 `[판정] 통과`(알려진 FAIL 밖 0, §3-3 — 10-16 당시 기준 "종료 코드 0"은 structure의 알려진 FAIL 2개 때문에 I3에서 바꿈) |
| 2 | 서버: 배치(systemd 타이머)·MCP·상주 트리거 컨테이너 멈춤 | `docker ps`에 data-*/rag-* 없음 |
| 3 | 서버: `sudo mv /srv/rag/out /srv/rag/output` · `pipeline.env`의 `RAG_OUT=/srv/rag/output`(결과 경로를 적어 둔 다른 값·systemd·cron도) | `ls /srv/rag/output` |
| 4 | 서버: 새 `pipeline.env.example`과 비교해 새·바뀐 키 반영 — `DATA_PARSING_IMAGE`·`DATA_STRUCTURE_IMAGE`·`DATA_RETRIEVAL_IMAGE`(옛 `RAG_*_IMAGE`는 한 판 동안 별칭) · 결과 게시 키는 예시 파일에 없음 — [env-guide.md](../operations/env-guide.md) 표의 `PM_*`(새 `PM_PATH_MAP` = 결과 경로 앞부분 바꾸기, 옛 PM_STRIP_PREFIX 대체) | `docker run --rm --env-file … data-parsing:<태그> check` |
| 5 | 서버: 이미지 적재(§5-2) | `docker images | grep data-` 3개 |
| 6 | **DBA**: EDW에 [`docs/operations/parsing_meta_mssql.sql`](../operations/parsing_meta_mssql.sql) 1회 실행(S1부터 저장소 문서 자리 — 코드 폴더·덧씌우기 묶음에 없으므로 DBA에게 따로 전달)(AI.ParsingMeta — `parse_date` 글자형 `YYYY-MM-DD_HHMMSS`, `rep_key` = 문서 폴더 URI) — **첫 `publish`(= `data_etl.load.publish_parse_result --apply`) 전에**. **PM2(10-15) 반영 — DBA가 이 표를 아직 한 번도 안 돌렸으면 지금 이 최신 판(필수 열은 `doc_key` 하나뿐, `engines_used`·`engines_summary` 포함)을 그대로 실행 — 옛 판 먼저 돌리지 않음** | 표·필터 유일 색인 두 개(source_key 있음/없음) 생성됨 |
| 7 | 서버: `docker port`로 기존 pgvector·OpenViking이 호스트 포트를 열었는지 확인(열려 있으면 host 네트워크 그대로 — XS5) · 실행 계정 docker 그룹(SI12) | 연결 점검 `services` |
| 8 | 서버: 샘플 몇 건 `smoke --src <폴더>`(data-parsing → data-structure → data-retrieval) | 요약에 단계 실패 없음 |
| 9 | 서버: 첫 실파싱 = **전체 재파싱 1회**(TB6로 27개 엔진 지문이 바뀜 · CT1로 인계 FINGERPRINT도 바뀌어 옛 `_DONE` 표식은 불일치 종료 코드 3 — 정상, 다시 돌리면 됨) + 구조화 1회 재실행 — 실행 시간을 미리 잡을 것 | `run_board` 실행판 |
| 10 | 서버: MCP 상주(`compose.mcp.yml`)·필요하면 상주 트리거(`serve-trigger`) 기동 · 자정 배치 다시 켬 | `/health` ready · `mcp_smoke` |
| 11 | 확인: G17(고객명 교차언어 별칭) 기본 켬 — 실문서에서 1위 정답 하락이면 `SEARCH_VECTOR_ALIAS_EXPAND=0` (10-21 판단) | 실문서 질문 몇 개 |
| 12 | `/srv/rag/reports/versions.md`에 판 기록(이미지 태그·기준 커밋) | — |

10-21: 위 9·11 결과와 긴급 수정을 담아 재설치·재시험(§7).

**알려진 차이(10-15 PC Docker 점검, 태그 20261016-4737a95)** — 한국어 OCR(rapidocr_ko)이 같은 모델 파일인데도 컨테이너(Linux)와 PC(Windows)에서 스캔 쪽 하나를 다르게 읽음(`scan_report.pdf` 2쪽 — PC "월간 생산 보고(2쪽)", 컨테이너 "() "). 통합 22문서를 컨테이너로 파싱해 PC 채점기로 매기면 값 재현율 0.9813·표 칸 1.0·검색 hit1 0.75·hit5 0.90은 기준선과 같고 글자 정확도만 0.7942 → 0.7912(−0.003, 그 문서 0.577 → 0.512) — 회귀 문턱 0.01 안. 라이브러리 버전은 numpy 2.5.4 vs 2.5.3 외 같음 → onnxruntime·opencv의 OS별 수치 차이로 보고 버전 고정은 안 함. 서버(Linux)에서 정답률을 잴 때 기준은 **컨테이너 결과**로 잡을 것.

**이미지 크기(같은 점검)**: data-parsing 3.25 GB(전송 tar.gz 858 MB, 95 MB 조각 10개) · data-structure 1.29 GB(286 MB, 4조각) · data-retrieval 1.29 GB(286 MB, 4조각) — 구조화·검색은 공통 기반 층을 같이 써서 서버 디스크엔 한 번만 올라감.

**10-16 최종 판(10-15 확정)** — 이미지 태그 `20261016-e305b14` · 기준 커밋 main `e305b14`(`deploy/docker/IMAGE_BASE`에 기록 — 이후 `make_patch.sh image`·`last`의 기준) · 전송 파일 `output/ship/data_parsing_split/images/20261016-e305b14/{data-parsing 858 MB·10조각, data-structure 286 MB·4조각, data-retrieval 286 MB·4조각}` + 각 `.sha256`.
PC 확인(10-15): 이미지 3개 컨테이너 selftest rc=0(parse 55/55·structure 30/30·retrieval 35/35, 건너뜀은 다른 이미지 모듈과 PC 전용 평가 도구 3개뿐) · 서버 받기 모의(sha256 확인→재조립→rmi→load→selftest) 3개 모두 통과 · 컨테이너 문서 3건(office·kreuzberg·rapidocr_ko) 파싱 · 같은 커밋 네이티브 전체 시험 920 통과·check_modules 통과 · 통합 22문서 e2e(고정 질문) 기준선과 같음(컨테이너는 위 '알려진 차이' −0.003만).
이미지에 없는 것(PC 전용): `openpyxl` — `mcp_eval --xlsx`(엑셀 보고서)는 서버에서 안 됨, 보고서는 PC에서.

## 9. 10-16 판 위 덧씌우기 묶음(10-21 반영 예정 — 기준 `IMAGE_BASE` = e305b14)

`make_patch.sh image <출력>`이 아래 파일을 모은다(바뀐 파일만, 새 이미지 판 아님). 적용 뒤 서버 단계까지 같이.

날짜·시각이 붙은 이력: [patch-history.md](patch-history.md)(이 절에서 자동 생성 — `backlog_xlsx.py`).

| 항목 | 커밋 | 파일(이미지) | 서버에서 할 일 |
|---|---|---|---|
| GL1 고객 명부 새 양식·용어집 빈칸 | 0e7d64cd | `common_tools/terms.py`(3개 모두) | 명부(`CLIENT_ROSTER`)·용어집(`GLOSSARY_DIR`)을 새 양식으로 — env-guide 해당 행 |
| GL2 검색 DB 고객 칸·OpenViking 머리말 | 45dd78f1 | `data_structure/pg/schema.sql`·`pgvector_load.py`·`openviking_load.py`(structure) · `data_retrieval/pgsearch.py`(retrieval) · `common_tools/store/pg_standin.py`(3개 모두) | 구조화 적재 1회(고객 칸·GIN 색인·기존 데이터 채우기, 200문서마다 저장) → **검색 MCP 재시작** · 끄기 `OV_TAGS=0` |
| PM2 파싱 메타 열·키 최소화 + 엔진 전부 기록 | 1db61d7f | `data_structure/sql/parsing_meta_mssql.sql`·`data_structure/tools/parsing_meta.py`·`data_structure/publish_parse_result.py`(structure) · `common_tools/store/parsing_meta_db.py`(3개 모두) · `data_parsing/represent.py`(parse — `tried`에 엔진 판, `post.vlm_models` 추가) | **DBA가 AI.ParsingMeta DDL을 아직 한 번도 안 돌렸으면** 이 판을 그대로 1회 실행(§8 단계 6) — 이미 PM1 옛 판을 돌렸다면 이 패치는 DBA 재작업이 더 생김(사람 조정 필요, 코드가 ALTER는 안 함) |
| OC1 OCR 스레드 상한 | 583127cb | `data_parsing/engines/rapidocr/parser.py`·`data_parsing/prepare.py`(parse) | 없음(자동 — 프로세스당 CPU 몫, 덮어쓰기 `OCR_THREADS`) |
| OC2 3단계(VLM) 스레드 몫 | 21365ffe | `data_parsing/run_all.py`·`data_parsing/tools/resources.py`(parse) | 없음(CPU ÷ (procs × workers)) |
| DT2 명부·용어집 예시 | eaafbc70 | `common_tools/glossary/*.example.csv`(3개 모두) | 예시 보고 명부·용어집 작성 — server-guide 5-1 |
| GL1b 명부 줄에 칸이 더 있어도 안 죽음 | 43f17721 | `common_tools/terms.py`·`common_tools/options.conf`(3개 모두) | 없음 |
| TA1 표 영역 조립(엔진 격자 모아 본문 제자리 표) | 9c3c9085 | `data_parsing/postprocess/table_inline.py`(새 파일)·`data_parsing/represent.py`(parse) · `data_structure/tools/parsing_meta.py`(structure) · `common_tools/cli/pipeline.py`·`options.conf`(3개 모두) | 파싱 본문이 바뀜 — 표가 있는 문서는 다음 재파싱 때 반영(급하면 해당 문서 `--force`) · 끄기 `PARSE_TABLE_INLINE=0` |
| TS1 표 구조 채점(평가 도구) | ebc92cca | `data_parsing/evaluation/score_gold.py`·`prompts/table_struct_judge/`(parse) · `common_tools/report_templates/criteria.json` | 없음(평가 때만, LLM 판정 기본 끔) |
| EQ1 EDW SQL 질의 도구(검색 MCP `describe_edw`·`query_edw`) | bc5facb3 | `data_retrieval/tools/edw_query.py`(새 파일)·`data_retrieval/mcp_server.py`·`data_retrieval/tools/qa_log.py`(retrieval) · `common_tools/options.conf`·`agent_platform/export_mcp_tool_schema.py`(3개 모두) | **DBA**: EDW 읽기 전용 계정(허용 표 SELECT만·`DENY VIEW DEFINITION`·다른 DB/연결 서버 권한 없음) → `pipeline.env`에 `EDW_QUERY_CONN_FILE`(또는 `EDW_QUERY_SERVER`)·`EDW_QUERY_TABLES`(비우면 전부 거부) → **검색 MCP 재시작** · 끄기 `EDW_QUERY=0` — server-guide 4-1 |
| GL3 명부 생성기 새 양식·상태 대소문자 무시·고객 마스터 예시 | 5da9bea9 | `common_tools/cli/gen_roster.py`·`common_tools/terms.py`·`common_tools/glossary/client_master.example.csv`·`client_master_map.example.json`(3개 모두) | 고객 마스터 → 명부 만들기 — server-guide 5-1 |

이 묶음에서 빠짐(사용자 10-15 결정 — 다음 묶음):

| 항목 | 브랜치 | 남은 일 |
|---|---|---|
| QM1 문서 단위 대기열 | jh/QM1-doc-queue @dc3e6a85 · jh/QM1b-doc-chain @3bc8000f | 묶어 넘기기(B) 검토 통과, 대기열(A)·서버 연결 미완·미검토 |
| OC3 OCR 실패여도 VLM으로 | (아직 없음) | 설계만 — docs/backlog/parse.md OC3 행. 그때까지 수집 서버는 OCR을 꺼 두고 운영 |
| OL1 확장자 위장 문서 판별 | jh/OL1-real-format-sniff @21e9fd31 | 구현 중 보류 |

