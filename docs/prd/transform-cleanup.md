# 변환 — 파싱 정리·지문 배치

[PRD.md](../PRD.md) 카테고리. [transform.md](transform.md)의 하위 문서. 엔진·대표 결과·층 지문이 바뀌는 정리 묶음 — 모두 검토 등급 A(CLAUDE.md §4).

순서: pl-31 · pl-34 · pl-35 · pl-46 · pl-53 · pl-47 · pl-49 · pl-50.

<a id="pl-31"></a>
## pl-31 · 안 쓰는 엔진·`ocr_vlm`·`vlm.model_alt` 지우기

### 무엇·왜
엔진 구성에 없어 쓰이지 않는 엔진과 설정을 지워 코드·설정을 줄인다. 엔진 목록의 정본은 등록부 `pipeline/extract/engines/registry.py`다. `docx2python`은 남긴다.
- Status: done

<a id="pl-34"></a>
## pl-34 · 대표 결과 다시 읽기(P2·P3)·스캔 중복 제거·렌더 OCR 신호 지우기

### 무엇·왜
대표 결과 단계는 융합(`fragment_vote.py`) 결과를 그대로 쓴다 — 근소·미확인 조각을 다시 읽는 단계는 없다.
- Status: done

<a id="pl-35"></a>
## pl-35 · 지문에 영향 없는 잔재 지우기

### 무엇·왜
문서 단위 병렬 실행기·자동 재파싱 스위치·그림 이어 하기 같은 잔재를 지운다. 처리는 새 문서만 고르는 증분 하나다([ops.md#pl-23](ops.md#pl-23)).
- Status: done

<a id="pl-46"></a>
## pl-46 · 0.2.0 지문 배치 정리

### 무엇·왜
지문이 바뀌는 정리를 서버 전체 재처리 한 번에 모은다. 남은 것은 [pl-53](#pl-53).

### 규칙
1. 이미지 형식과 `.pdf_image`의 엔진은 `qwen_vlm` 하나다([transform.md#pl-03](transform.md#pl-03)).
2. 모델 호출은 `common/ai/llm.py` `complete()`(OpenAI 호환 HTTP) 한 길이다. 앱 코드는 `litellm`·`google.adk`를 import하지 않는다(`check_modules` ④). PC 답변 점검의 여러 턴 도구 왕복만 `validation/e2e/tool_loop.py`.
3. CPU 부하(`common/core/resources.py` `cpu_load`) = cgroup CPU 한도가 있으면 그 cgroup 사용량 증가 ÷ (한도 코어 × 지난 시간)(한도가 호스트 코어보다 크면 호스트 코어), 한도가 없거나 못 읽으면 1분 부하 평균 ÷ 호스트 코어.
4. 지운 설정 칸은 표로 따로 두지 않는다 — settings.yaml에 남아 있으면 모르는 칸으로 시작 거부(`common/config/layout.py` `to_model`).
5. 환경·서비스·모델 점검은 `common/check/checker.py` 하나다.

### QA
- `tests/server/common/test_core_resources.py` · `tests/server/common/test_check_modules.py::test_main`(저장소 전체 ④) · `tests/server/common/test_layout.py`.
- Status: done

<a id="pl-53"></a>
## pl-53 · pl-46 남은 정리 — 첫 이관 DB 도구·안 쓰는 패키지

### 단계
1. 0.2.0이 서버에 배포된 뒤 `dbtool`의 비교(`common/store/db/dbcompare.py`)와 `stamp`(옛 코드가 만든 스키마에 판만 기록 — 첫 이관용)를 지운다. `tests/server/common/test_db_schema.py`가 `dbcompare.expected`를 쓰므로 그 시험도 함께 고친다.
2. 다음 이미지 빌드 때 `deploy/docker/requirements*`의 `google-adk`·`litellm`을 뺄지 정한다. 앱 코드는 둘 다 import하지 않고, 지시서 패키지의 `resources/prompts/**/agent.py`(지시서 지문 파일)만 `google-adk`를 import한다 — 빼려면 그 파일을 어떻게 할지 함께 정한다. 빼면 `deps_hash`가 바뀌어 새 이미지 버전이 필요하다.
- Status: todo

<a id="pl-47"></a>
## pl-47 · 엔진 지문(p0) 범위 — 모든 엔진 폴더

### 무엇·왜
엔진 이름과 폴더 이름이 다른 엔진(`html_stdlib`·`msg_extract` → `mhtml/`, `office` → `office_stdlib/`, `rapidocr_ko` → `rapidocr/`)을 고쳐도 지문이 바뀌어야 한다.

### 규칙
1. 층 지문 p0 범위 = `pipeline/extract/engines/**/*.py` + `pipeline/extract/run_engines.py`(`common/core/artifacts.py` `LAYER_CODE`).
2. 문서×엔진 결과 재사용 열쇠는 `pipeline.extract.run_engines.engine_code_fp()`(등록부의 엔진 폴더 + `_common`)다 — 층 지문이 아니다.

### QA
- `tests/server/pipeline/test_run_all.py::test_p0_layer_covers_every_engine_folder`.
- Status: done

<a id="pl-49"></a>
## pl-49 · 같은 결과로 덜 읽고 덜 띄우기

### 무엇·왜
명부·사전·원본 해시·매니페스트·엔진 지문을 프로세스마다 한 번만 읽고, 엔진 결과를 자식이 한 번에 쓰고, 1건 중복 확인을 자식 없이 한다. 결과(대표 결과·묶음)는 바이트 그대로다.
- Status: done

<a id="pl-50"></a>
## pl-50 · 층 지문 범위 + 단계 방향 자동 점검

### 무엇·왜
결과를 바꾸는 파일은 층 지문에 들고, 기록·DB 표 정의만 바꾼 변경은 층 지문을 바꾸지 않아야 한다. extract → transform → load 방향은 자동으로 점검한다.

### 규칙
1. 대표 결과 점수 `pipeline/transform/represent/rep_accuracy.py`는 p1, 고객 이름 찾기 `pipeline/transform/structure/client_roster.py`는 s 층 목록에 든다. 결과를 만들지 않는 오프라인 도구는 `NOT_LAYER`에 적는다.
2. `CODE_FP_SKIP`에 적은 파일(기록·DB 연결·표 정의·설정 도구)은 지문 계산에서 import를 따라가지 않는다. 설정 모델 `common/config/settings.py`는 기본값이 결과를 바꿀 수 있어 따라간다.
3. `common/check/check_modules.py` ⑫ — `pipeline` 안에서 뒤 단계를 import하면(함수 안 늦은 import 포함) 위반이다. 예외(`STAGE_ALLOW`) 없음 — `qwen_vlm` 엔진이 쓰던 VLM 게이트는 `pipeline/shared/vlmcall.py`로 옮겼다(11-04, [pl-43](transform.md#pl-43)).

### QA
- `tests/server/common/test_code_fp.py`(`pipeline/transform` 아래 빠진 파일 · 표 정의·기록 파일은 지문 그대로) · `tests/server/common/test_check_modules.py`.
- Status: done
