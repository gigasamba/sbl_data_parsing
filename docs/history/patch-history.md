# 긴급 패치 이력

> 자동 생성 — 손으로 고치지 말 것. 원본: [`docs/history/release_history.md`](release_history.md) §9(10-30 do-04에 release-and-patch.md §9에서 옮김) · 만드는 곳: upstream `dev_tools/repo_maintain/backlog_xlsx.py`(main에서 실행, xlsx '긴급 패치' 시트와 같은 행 — 이 저장소에는 없음. S1에서 `runbooks/` → `docs/operations/`, 10-30에 `docs/history/`로 옮기며 원본 경로만 고침). 행의 "§8 단계 6"은 release_history.md §8.
> 날짜·시각 = 반영 항목은 병합 커밋 시각, 보류 항목은 브랜치 끝 커밋 시각(없으면 결정일).

| ID | 항목 | 상태 | 날짜·시각 | 커밋·브랜치 | 바뀐 파일(이미지) | 서버에서 할 일 / 남은 일 |
|---|---|---|---|---|---|---|
| GL1 | 고객 명부 새 양식·용어집 빈칸 | 반영 — 10-21 덧씌우기 | 2026-10-15 17:24 +0900 | 0e7d64cd | common_tools/terms.py(3개 모두) | 명부(CLIENT_ROSTER)·용어집(GLOSSARY_DIR)을 새 양식으로 — env-guide 해당 행 |
| GL2 | 검색 DB 고객 칸·OpenViking 머리말 | 반영 — 10-21 덧씌우기 | 2026-10-15 18:16 +0900 | 45dd78f1 | data_structure/pg/schema.sql·pgvector_load.py·openviking_load.py(structure) · data_retrieval/pgsearch.py(retrieval) · common_tools/store/pg_standin.py(3개 모두) | 구조화 적재 1회(고객 칸·GIN 색인·기존 데이터 채우기, 200문서마다 저장) → **검색 MCP 재시작** · 끄기 OV_TAGS=0 |
| PM2 | 파싱 메타 열·키 최소화 + 엔진 전부 기록 | 반영 — 10-21 덧씌우기 | 2026-10-15 19:38 +0900 | 1db61d7f | data_structure/sql/parsing_meta_mssql.sql·data_structure/tools/parsing_meta.py·data_structure/publish_parse_result.py(structure) · common_tools/store/parsing_meta_db.py(3개 모두) · data_parsing/represent.py(parse — tried에 엔진 판, post.vlm_models 추가) | **DBA가 AI.ParsingMeta DDL을 아직 한 번도 안 돌렸으면** 이 판을 그대로 1회 실행(§8 단계 6) — 이미 PM1 옛 판을 돌렸다면 이 패치는 DBA 재작업이 더 생김(사람 조정 필요, 코드가 ALTER는 안 함) |
| OC1 | OCR 스레드 상한 | 반영 — 10-21 덧씌우기 | 2026-10-15 18:10 +0900 | 583127cb | data_parsing/engines/rapidocr/parser.py·data_parsing/prepare.py(parse) | 없음(자동 — 프로세스당 CPU 몫, 덮어쓰기 OCR_THREADS) |
| OC2 | 3단계(VLM) 스레드 몫 | 반영 — 10-21 덧씌우기 | 2026-10-15 18:41 +0900 | 21365ffe | data_parsing/run_all.py·data_parsing/tools/resources.py(parse) | 없음(CPU ÷ (procs × workers)) |
| DT2 | 명부·용어집 예시 | 반영 — 10-21 덧씌우기 | 2026-10-15 18:40 +0900 | eaafbc70 | common_tools/glossary/*.example.csv(3개 모두) | 예시 보고 명부·용어집 작성 — server-guide 5-1 |
| GL1b | 명부 줄에 칸이 더 있어도 안 죽음 | 반영 — 10-21 덧씌우기 | 2026-10-15 18:42 +0900 | 43f17721 | common_tools/terms.py·common_tools/options.conf(3개 모두) | 없음 |
| TA1 | 표 영역 조립(엔진 격자 모아 본문 제자리 표) | 반영 — 10-21 덧씌우기 | 2026-10-15 19:38 +0900 | 9c3c9085 | data_parsing/postprocess/table_inline.py(새 파일)·data_parsing/represent.py(parse) · data_structure/tools/parsing_meta.py(structure) · common_tools/cli/pipeline.py·options.conf(3개 모두) | 파싱 본문이 바뀜 — 표가 있는 문서는 다음 재파싱 때 반영(급하면 해당 문서 --force) · 끄기 PARSE_TABLE_INLINE=0 |
| TS1 | 표 구조 채점(평가 도구) | 반영 — 10-21 덧씌우기 | 2026-10-15 19:38 +0900 | ebc92cca | data_parsing/evaluation/score_gold.py·prompts/table_struct_judge/(parse) · common_tools/report_templates/criteria.json | 없음(평가 때만, LLM 판정 기본 끔) |
| EQ1 | EDW SQL 질의 도구(검색 MCP describe_edw·query_edw) | 반영 — 10-21 덧씌우기 | 2026-10-15 21:56 +0900 | bc5facb3 | data_retrieval/tools/edw_query.py(새 파일)·data_retrieval/mcp_server.py·data_retrieval/tools/qa_log.py(retrieval) · common_tools/options.conf·agent_platform/export_mcp_tool_schema.py(3개 모두) | **DBA**: EDW 읽기 전용 계정(허용 표 SELECT만·DENY VIEW DEFINITION·다른 DB/연결 서버 권한 없음) → pipeline.env에 EDW_QUERY_CONN_FILE(또는 EDW_QUERY_SERVER)·EDW_QUERY_TABLES(비우면 전부 거부) → **검색 MCP 재시작** · 끄기 EDW_QUERY=0 — server-guide 4-1 |
| GL3 | 명부 생성기 새 양식·상태 대소문자 무시·고객 마스터 예시 | 반영 — 10-21 덧씌우기 | 2026-10-15 21:55 +0900 | 5da9bea9 | common_tools/cli/gen_roster.py·common_tools/terms.py·common_tools/glossary/client_master.example.csv·client_master_map.example.json(3개 모두) | 고객 마스터 → 명부 만들기 — server-guide 5-1 |
| QM1 | 문서 단위 대기열 | 보류 — 다음 묶음 | 2026-10-15 19:48 +0900 | jh/QM1-doc-queue @dc3e6a85 · jh/QM1b-doc-chain @3bc8000f |  | 묶어 넘기기(B) 검토 통과, 대기열(A)·서버 연결 미완·미검토 |
| OC3 | OCR 실패여도 VLM으로 | 보류 — 다음 묶음 | 2026-10-15 | (아직 없음) |  | 설계만 — docs/backlog/parse.md OC3 행. 그때까지 수집 서버는 OCR을 꺼 두고 운영 |
| OL1 | 확장자 위장 문서 판별 | 보류 — 다음 묶음 | 2026-10-15 19:45 +0900 | jh/OL1-real-format-sniff @21e9fd31 |  | 구현 중 보류 |
