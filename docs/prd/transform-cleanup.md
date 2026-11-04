# 변환 — 엔진·대표 결과·층 지문의 모양

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md)의 하위 문서. 엔진·대표 결과·층 지문을 정하는 요건 — 고치면 지문이 바뀔 수 있어 모두 검토 등급 A(CLAUDE.md §4).

순서: pl-31 · pl-34 · pl-35 · pl-46 · pl-53 · pl-47 · pl-49 · pl-50.

<a id="pl-31"></a>
## pl-31 · 엔진은 쓰는 것만
- 이유: 쓰이지 않는 엔진과 설정은 지문·설정·이미지만 무겁게 한다.
- 요건(되어야 할 모습):
  1. 엔진 목록의 정본은 엔진 등록부(`registry.py`)다. 엔진 구성 파일에 없는 엔진은 두지 않는다 — 예외는 비교용 `docx2python`.
  2. OCR 전용 소형 VLM 엔진(`ocr_vlm`)과 대체 VLM 모델 칸(`vlm.model_alt`)은 없다 — VLM은 `qwen_vlm` 하나.
- Status: done

<a id="pl-34"></a>
## pl-34 · 대표 결과는 융합 결과 그대로
- 이유: 다시 읽기 단계는 비용에 비해 결과가 나아지지 않았다.
- 요건(되어야 할 모습): 대표 결과 단계는 융합(`fragment_vote.py`) 결과를 그대로 쓴다. 근소·미확인 조각을 다시 읽는 단계(P2·P3), 스캔 중복 제거, 렌더 OCR 신호는 없다.
- Status: done

<a id="pl-35"></a>
## pl-35 · 처리는 증분 하나
- 이유: 실행 길이 여럿이면 서버에서 어느 길을 탔는지 알기 어렵다.
- 요건(되어야 할 모습): 처리는 새 문서만 고르는 증분 하나다([ops.md#pl-23](ops.md#pl-23)). 문서 단위 병렬 실행기, 자동 재파싱 스위치, 그림 이어 하기는 없다.
- Status: done

<a id="pl-46"></a>
## pl-46 · 0.2.0 지문 배치의 모양
- 이유: 지문이 바뀌는 정리는 서버 전체 재처리 한 번에 모은다(0.2.0).
- 요건(되어야 할 모습):
  1. 이미지 형식과 `.pdf_image`의 엔진은 `qwen_vlm` 하나다([transform.md#pl-03](transform.md#pl-03)).
  2. 모델 호출은 `common/ai/llm.py` `complete()`(OpenAI 호환 HTTP) 한 길이다. 앱 코드는 `litellm`·`google.adk`를 import하지 않는다(`check_modules` ④). PC 답변 점검의 여러 턴 도구 왕복만 `validation/e2e/tool_loop.py`.
  3. CPU 부하(`common/core/resources.py` `cpu_load`) = cgroup CPU 한도가 있으면 그 cgroup 사용량 증가 ÷ (한도 코어 × 지난 시간)(한도가 호스트 코어보다 크면 호스트 코어), 한도가 없거나 못 읽으면 1분 부하 평균 ÷ 호스트 코어.
  4. 지운 설정 칸의 표는 없다 — settings.yaml에 남아 있으면 모르는 칸으로 시작 거부(`common/config/layout.py` `to_model`).
  5. 환경·서비스·모델 점검은 `common/check/checker.py` 하나다.
- QA: `tests/server/common/test_core_resources.py` · `tests/server/common/test_check_modules.py::test_main`(저장소 전체 ④) · `tests/server/common/test_layout.py`.
- Status: done

<a id="pl-53"></a>
## pl-53 · 첫 이관 도구와 안 쓰는 패키지 없음
- 이유: 첫 이관용 도구와 앱이 쓰지 않는 패키지는 이미지와 점검 범위만 키운다.
- 요건(되어야 할 모습):
  1. 0.2.0이 서버에 배포된 뒤 DB 도구 `dbtool`에는 첫 이관용 기능이 없다 — 옛 스키마와 견주는 비교(`dbcompare`)와 판만 기록하는 `stamp`.
  2. 이미지 의존성(`deploy/docker/requirements*`)에는 앱 코드가 쓰는 패키지만 둔다. 빼면 `deps_hash`가 바뀌어 새 이미지 버전이 필요하다.
- 비고(현재와 다른 점, 11-05 확인):
  - `common/store/db/dbcompare.py`와 `dbtool stamp`가 있다(0.2.0 서버 배포 대기). `tests/server/common/test_db_schema.py`가 `dbcompare.expected`를 쓴다 — 함께 고친다.
  - `requirements-core.txt`·`requirements-image.txt`·`requirements.txt`에 `google-adk`·`litellm`이 있다. 앱 코드는 둘 다 import하지 않고, 지시서 패키지의 `resources/prompts/**/agent.py`(지시서 지문 파일)만 `google-adk`를 import한다 — 뺄지는 그 파일 처리와 함께 정한다(미정).
- Status: todo

<a id="pl-47"></a>
## pl-47 · 엔진 지문(p0) 범위 — 모든 엔진 폴더
- 이유: 엔진 이름과 폴더 이름이 다른 엔진(`html_stdlib`·`msg_extract` → `mhtml/`, `office` → `office_stdlib/`, `rapidocr_ko` → `rapidocr/`)을 고쳐도 지문이 바뀌어야 한다.
- 요건(되어야 할 모습):
  1. 층 지문 p0 범위 = 엔진 폴더의 모든 `.py` + 엔진 실행 파일 + 엔진이 import하는 pipeline 파일(`config.py`·`post_config.py`·`vlmcall.py` 등)(`common/core/artifacts.py` `LAYER_CODE`).
  2. 문서×엔진 결과 재사용 열쇠는 `engine_code_fp()`(등록부의 엔진 폴더 + `_common`)다 — 층 지문이 아니다.
- QA: `tests/server/pipeline/test_run_all.py::test_p0_layer_covers_every_engine_folder`.
- Status: done

<a id="pl-49"></a>
## pl-49 · 같은 결과로 덜 읽고 덜 띄우기
- 이유: 같은 파일을 여러 번 읽고 자식 프로세스를 자주 띄우면 문서 수천 건에서 시간이 커진다.
- 요건(되어야 할 모습): 명부·사전·원본 해시·매니페스트·엔진 지문은 프로세스마다 한 번만 읽는다. 엔진 결과는 자식이 한 번에 쓴다. 1건 중복 확인은 자식 없이 한다. 결과(대표 결과·묶음)는 바이트 그대로다.
- Status: done

<a id="pl-50"></a>
## pl-50 · 층 지문 범위 + 단계 방향 자동 점검
- 이유: 결과를 바꾸는 파일이 층 지문에서 빠지면 고쳐도 옛 결과를 다시 쓰고, 넘치면 상관없는 수정에도 재처리 경보가 난다.
- 요건(되어야 할 모습):
  1. 대표 결과 점수(`parse_scoring.doc_accuracy`)는 p1, 고객 이름 찾기 `pipeline/transform/structure/client_roster.py`는 s 층 목록에 든다. 결과를 만들지 않는 오프라인 도구는 `NOT_LAYER`에 적는다. 층 파일이 import하는 pipeline 파일은 같은 층에 든다(엔진 코드는 p0, 실행 기록 `runtrace.py`만 뺌 — `test_code_fp.test_layer_imports_in_layer`).
  2. `CODE_FP_SKIP`에 적은 파일(기록·DB 연결·표 정의·설정 도구)은 지문 계산에서 import를 따라가지 않는다. 설정 모델 `common/config/settings.py`는 기본값이 결과를 바꿀 수 있어 따라간다.
  3. `common/check/check_modules.py` ⑫ — `pipeline` 안에서 뒤 단계를 import하면(함수 안 늦은 import 포함) 위반이다. 예외(`STAGE_ALLOW`)는 없다 — VLM 호출 게이트는 `vlmcall.py`([pl-43](transform.md#pl-43)).
- QA: `tests/server/common/test_code_fp.py`(`pipeline/transform` 아래 빠진 파일 · 표 정의·기록 파일은 지문 그대로) · `tests/server/common/test_check_modules.py`.
- Status: done
