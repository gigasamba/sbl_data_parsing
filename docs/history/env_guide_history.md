# env-guide 이력 — 옛 동작 기록

10-30(do-04)에 [env-guide.md](../operations/env-guide.md) 0~4절에서 옮긴 기록이다. 지금 운영 절차에는 영향이 없다(지금 규칙은 env-guide). 버전별 서버 할 일은 env-guide §5 표에 그대로 있다.

## 설정 파일
- PC `settings.yaml`은 10-29에 `valid_env/local/`에서 저장소 루트로 옮겼다.
- 서버 settings.yaml 하나로 모은 것은 S7e1(D-015·D-028)부터다. 그 전에는 `pipeline.env`(+ 옛 옵션 카탈로그)를 읽었다.
- env로 준 값을 읽지 않게 된 것은 S7e2부터다. 서버에서 settings.yaml을 직접 고치고 오버레이 설정 파일 도구를 PC 전용으로 막은 것은 S7e3(사용자 10-28)이다(VS7e2 B-2 — compose가 오버레이 파일만 붙여 `base`가 컨테이너 안에 없었음).
- 서버에서 설정 파일을 못 읽거나 이미지 절이 틀리면 시작하지 않게 된 것은 S7e2부터다. 옛 버전은 기본값으로 떴다(VS7e1 U-1).
- 엔진·핸드오프 파일이 env로 읽는 항목이 컨테이너 안 프로세스 env에 들어가는 것은 사용자가 10-27에 받아들였다.
- `--set 이름=값`은 S9 Step A(사용자 10-28)에 생겼다. S9b에서 서버에 설정 파일이 없으면 종료 2로 바꿨다(VS9 R-1 — 전에는 원본 없는 오버레이 파일이 "설정 파일 필수" 관문을 지나갔음). S7e2~S8b 버전의 `run_docs.py`는 `bash -c 'X=값 python …'` env로 넘겨 효과가 없었다(VS8b U-1).
- 라이브러리 env를 `common.runtime.lib_env`로 내보내는 방식은 S7e2부터다.
- `RUN_ENV` 필수는 S7a, settings.yaml의 `common.run_env`로 줘도 되게 한 것은 S7a2다. settings.yaml 작성 규칙은 S7a2, 켜기 항목 판정(`[켬: …]`·`[끔: …]`)은 S7b, 앱 절별 다리(`RAG_MODULE`)는 S7d에서 정했다.
- `PARSE_POST`에 `''`·`[]`를 쓰면 끔이 되는 동작은 VS7c2 R-1에서 확인했다.
- 옛 `common/config/options.conf`(옵션 카탈로그)는 S7e2에 지웠다 — 그 값은 sample의 `[서버 옛 값: …]`로 옮겼다(C-39).

## 항목별
- 이미지 이름: S6b(D-020, 이름은 사용자 10-27)에 이미지 2개 `data-pipeline`·`mcp-server`로 바꿨다. 새벽 배치 systemd 이름도 S6b 전에는 `rag-nightly`였다.
- `MCP_METHODS`: graph·concept·image·openviking 방법은 10-29에 지웠다. `OV_TAGS`(OpenViking 머리말)도 같이 지웠다.
- `MCP_TOKEN`: 공백만인 토큰을 없음으로 보는 것과 `PARSE_SERVICE_TOKEN`의 코드 대체 토큰 삭제는 S7d다(C-44).
- EDW 쿼리 도구는 EQ1에서 생겼고, 검색 MCP에 읽기 계정만 주기로 한 것은 사용자 10-29 결정이다(op-03).
- `SOURCES_FILE`: S8b 버전부터 PC 파일 경로만 읽는다. I4~S8a 버전은 호스트 python이 `SERVER_ENV_DIR`이 있을 때만 `$SERVER_ENV_DIR/sources.json`을 봤다.
- `SERVER_ENV_DIR`: I4에서 생겼다. 전에는 코드·스크립트에 경로가 박혀 있었다.
- `GOLD_DIR`: 호스트 항목에만 적는 규칙과 migrate 동작은 S7e3 B-3이다.
- `CLIENT_ROSTER` 권장 CSV 형식과 `GLOSSARY_DIR` 빈칸 허용은 10-15에 생겼다. 고객 필터 검색(`PG_FILTER_EXACT_MAX`)은 10-15 GL2다.
- `AGG_VOCAB_FILE`: S2 버전 전에는 `data_retrieval/agg_vocab.json`이었다.
- `parsing_meta_mssql.sql`: S1부터 저장소 문서 자리(`docs/operations/`)에 있다(PM2, 10-15).
- 상주 트리거 서버는 10-14에 생겼다. S7e2부터 트리거 포트는 앱 항목이 되었고 compose가 env로 주지 않는다. 옛 compose는 서비스마다 `TRIGGER_PORT`를 덮었다(S7e3 R-1). `CHAIN_STRUCTURE_URL`의 `http://127.0.0.1:8771`은 옛 compose 기본값이었다.
- Agent Platform: `agent_platform/`을 10-26에 지웠다(I5, D-013). `PLATFORM_CONFIG`·`PLATFORM_STATE_DIR`은 그 뒤 읽히지 않는다. 모델 접속은 I6 임시 대체 구현(`common/ai/adk.py`·`llm.py`)으로 `LLM_`·`VLM_`·`OCRVLM_`·`EMBED_` 항목만 받는다.
