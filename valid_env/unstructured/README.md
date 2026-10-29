# 검증 데이터

시험 문서·정답 세트 모음이다. **문서 목록(사용자 10-13)**: `list-smoke10.txt`(개발 기본 10건) · `list-integration.txt`(통합 시험 22건, 기준선 `dev_tools/pipeline_e2e_test/baseline-integration.json`, 검색 질문은 고정 세트 `integration-questions.jsonl` 20문항을 `--questions`로 — 10-14 고정, 파싱이 바뀌어도 같은 질문으로 비교) · `list-integration-holdout.txt`(holdout 6건, 튜닝 금지) — `dev_tools/pipeline_e2e_test/e2e.py --docs @<목록>`이 읽는다. 백로그 타겟 문서는 같은 꼴(`--docs 경로,경로`). **문서의 특징(형식·스캔 여부·그림·벡터 그림·내장 이미지·인코딩·고객·종류·정답 문항 수)은 폴더로 나누지 않고 메타 카탈로그 [`catalog.jsonl`](catalog.jsonl)의 열로 관리한다.** 원하는 문서는 카탈로그를 조회해 경로로 찾는다.

```bash
# 문서를 추가·수정한 뒤 다시 등록(문서는 읽기만)
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/validation_catalog.py build
# 찾기 — SQL WHERE 조건(표 이름 docs)
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/validation_catalog.py query "format='pdf' AND scanned=1"
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/validation_catalog.py query "tags LIKE '%figure:flowchart%'" --cols path,format,figure_kinds,qa_refs
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/validation_catalog.py query "dataset='synth-4clients' AND kind='contract' AND client LIKE 'Pfizer%'"
# SQLite 파일로 내보내기(생성물 — 커밋하지 않음)
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/validation_catalog.py export --db .cache/validation_catalog.sqlite
```

- 열 정의와 태그 규칙은 [`dev_tools/synthetic_data_gen/validation_catalog.py`](../../dev_tools/synthetic_data_gen/validation_catalog.py) 상단 설명을 따른다. `tags`의 `vector_figure`는 선·도형 10개 이상인 PDF·pptx 후보 표시라 표 테두리도 걸린다.
- 새 샘플은 카테고리 폴더를 새로 만들지 않는다. 기존 데이터셋 폴더(생성기 단위)에 두고 `build`로 등록한다. 기존 폴더(`synth-4clients/` 등)는 생성기·테스트·보고서가 경로를 참조하므로 그대로 둔다.
- 카탈로그가 실제 파일 목록과 어긋나면 `dev_tools/unit_test/qa/test_validation_catalog.py`가 실패한다.
- `goldenset/`은 다른 세션 소유 고정 정답 — 카탈로그는 읽기만 한다.

## 복합 문서 평가셋 (2026-10-02)

조합 성능 비교·파싱 튜닝 평가는 **복합 문서 6세트**만 쓴다 — dev: `synth-hard`(어려운 형식 22건) · `synth-images`(그림 13건) / holdout: `synth-plant`(가상 바이오 공장 12건, 다문서) · `synth-ops`(영업·품질 내용 14건) · `synth-tables`(표·구분 기호 7건) · `synth-charts`(다른 세션, 차트·흐름도 17건). 쉬운 세트(`synth-4clients`·`synth-clients*`·`synth-formats`)는 검색 방해·규모·형식 회귀용.

```bash
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/eval_set.py            # 목록·점검 기준 35개 커버리지·질문↔근거 문서·정답셋 점검 → eval_set.json
```
(파싱 후보정 A~F 비교·질의응답 튜닝 비교·보고서 생성 도구는 archive로 이동 — 되살릴 때는 `git log`로 삭제 커밋을 찾아 복구.)

- **개정판 세트** `synth-revisions/`(2026-10-05, holdout, L3-1) — '[구판]' 표시 없이 날짜·개정 번호·'그 밖은 직전 개정을 따른다' 문장으로만 최신 판단 · 특정 판을 묻는 문항은 현재 값이 금지어(늘 최신만 고르면 틀림) · 금지어는 '보관 기간은 5년'처럼 옛 값을 답으로 단정할 때만 걸림(이력 언급은 허용).
- **개정판 튜닝용 세트** `synth-revisions-tune/`(2026-10-05, **dev**, L4-8) — holdout `synth-revisions`와 같은 현상(현재 값·특정 판·최신 개정에 없는 항목·파일 이름 함정·없는 판)이지만 문서·값·형식은 다름. 최신판 규칙 튜닝은 이 세트로만.
- **어려운 용어 세트** `synth-terms-hard/`(2026-10-05, holdout) — 같은 양식 SOP 10건이 이름만 다름 · 질문은 다른 표기로만 · 동음이의 짝은 다른 뜻 문서 값이 금지어. 값은 두 자리 수(2개월 ⊂ 12개월 같은 부분 일치 채점 오인 방지).
- **방해 문서 v2** `synth-distractors-v2/`(2026-10-04) — v1이 효과 없어(오인율 0) 다시 설계: ID·고객명은 그대로 둔 **구판** 문서 63건 + '최신 문서 기준' 25문항(구판 값은 금지어) + **전체 합쳐 검색** 목록 `pool.json`(231문서). 평가 세트가 아니라 검색 범위를 넓히는 용도.
- **약한 그림 유형 세트** `synth-visual/`(2026-10-04, holdout) — 손그림 공정 스케치·워터마크가 값 위에 겹친 막대·2단 병합 머리글 표 이미지·누적 막대·로그 축. 다른 세션 차트 세트(66%)의 약한 **유형만** 참고(내용·정답은 보지 않음).
- **실데이터 난제 세트** `synth-edge/`(2026-10-04, holdout, V12) — 320쪽 PDF(중간 쪽 값)·암호 PDF 2종(열기 가능/불가 — 불가는 `expect`가 '암호 문서로 기록·건너뜀')·메일 안 메일+zip 첨부·숨긴/매우 숨긴 시트·저장값 없는 `=SUM`·그림 22장(문서당 상한 20 초과)·HWPX 최소 구조·초대형 스캔. HWP 바이너리·DRM·레거시 OLE는 여기 없음(서버 실문서·synth-formats).
- **용어 표현 차이 세트** `synth-terms/`(2026-10-04, holdout) — 문서는 한 표기, 질문은 다른 표기(약어·동의어·별칭·약한 연관어·동음이의 약어). qa 항목 `term`{concept(예제 사전 개념 ID)·query_form·doc_form·kind} — 용어 사전 질문 확장(X3)·용어 위키(X4) 효과를 종류별로 잰다.
- **혼동·plot·RFI 재사용 세트** `synth-confuse/`(2026-10-03, holdout) — 같은 제품의 이름 비슷한 두 법인·한 글자 다른 별개 회사·비슷한 제품 코드, 기존과 다른 양식 plot(가로 막대·원형·묶음 막대·이중 축·산점도·스윔레인), 2023/2025 원소 분석, 2024 RFI 답변서를 2026 다른 고객 RFI에 재사용(qa `references`에 문서 경로·절·image_id, `expected_attachments`). `spec.json` `must_not` = 그 문서에 없어 파싱 결과에 나오면 안 되는 값.
- **방해 문서 세트** `synth-distractors/`(2026-10-03, V11) — 검색 포화를 깨려고 정답 문서의 글자만 사본(고객·ID·연도·수치 치환). 평가 세트가 아니라 각 세트 묶음에 더하는 용도 — `synth-distractors/README.md`.
- **메일 인코딩 재현 세트** `synth-eml-charset/`(2026-10-11, SI42) — EUC-KR·CP949 메일 깨짐 서버 보고 재현용 `.eml` 7건(charset 선언 3종·무선언 8bit·quoted-printable·base64·한글 첨부 파일명). 형식 회귀용 — `synth-eml-charset/README.md`.
- **원본 문제 재현 세트** `synth-src-problem/`(2026-10-11, SI44·SI45) — 옛 OLE 암호·DRM·압축·손상 파일 7건이 `prepare.py`·`run_board.py` 분류에서 "원본 문제"로 묶이는지 재현용. 형식 회귀용 — `synth-src-problem/README.md`(pypdfium2 오류 문구 불일치 '발견' 포함).

### 튜닝용(dev) · 처음 보는 평가용(holdout) 구분 — 샘플을 만들고 고칠 때 지킬 것

- `eval_set.json`의 `split`: **dev** = `synth-images`·`synth-hard`(파싱 규칙·후보정을 맞춰 온 세트) · **holdout** = `synth-plant`(이 세션 생성, 규칙 미반영) · `synth-charts`(다른 세션 생성).
- holdout 실패를 보고 그 샘플에 맞춘 규칙을 만들지 않는다. 고칠 때는 dev에 비슷한 사례를 추가해 고치고 holdout으로 확인한다. 결과는 dev와 holdout을 나란히 보고한다.
- 정답 정의 오류(채점 규칙·문서에 없는 값)는 holdout이어도 고친다 — 파싱 규칙 튜닝과 다르다. 고친 내용은 보고서에 남긴다.
- 주기적으로 holdout을 dev로 넘기고, 새 holdout은 다른 세션·다른 생성기로 만든다(규칙 작성자가 내용을 보지 않게). 실문서 holdout(서버, 사람 정답)이 최종 기준.
- 새 샘플은 정답을 문서의 실제 글자·값으로만 만든다(계산값은 질문 정답에만, 파싱 사실(facts)에는 넣지 않음). 한두 자리 숫자 키워드는 단위와 함께(`strengthen_keywords`), 표 한 행 값은 `A~~B`(같은 줄), 첨자는 `^`·`_` 표기만 보존으로 인정.
