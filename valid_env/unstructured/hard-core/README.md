# hard-core — 반복해서 틀린 어려운 문항 묶음 (2026-10-11)

새 문서를 만들지 않고, **원래 세트 안에서 반복해서 틀린 문항·문서만** 고른 목록(`manifest.json`)이다.
원래 말뭉치(방해 문서 포함)를 그대로 쓰므로 난이도가 유지된다. 개선 하나를 고칠 때마다 여기만 빨리 다시 재고(무료·수십 초),
회귀 확인은 원래 세트 전체로 한다.

- 근거·사례: [docs/reviews/2026-10-11/case-study-parsing-retrieval.md](../../../docs/reviews/2026-10-11/case-study-parsing-retrieval.md)
- 고른 기준: 측정 2회 이상에서 틀림(mcp_eval 10-09 · OpenRouter 1·2차 · c0 근거 측정 10-11) 또는 원인 계열의 대표 사례. **채점 결함으로 틀렸던 문항(⑥)은 뺐다** — 10-11에 채점을 고쳐 지금은 정답.

## 근거 반환 (`retrieval`, 32문항)

| 세트 | 문항 | 원인 계열 |
|---|---|---|
| synth-4clients | QA003·QA009·QA098·QA010·QA076·QA080 | 다문서 종합(비교·집계의 한쪽 문서 빠짐) |
| synth-4clients | QA049·QA056·QA088·QA111 | 집계 경로(안 탐 / 타도 값 없음 — R5) |
| synth-4clients | QA035·QA066·QA074 | 형식 사본 혼동·메일 ID 색인(QA074는 상위 20에도 없음 — R1) |
| synth-4clients | QA095 | 구판 혼동(v1만 상위) |
| synth-distractors-v2 | V2-PQ015·HQ003·HQ004·IQ031·TQ009·UQ011 | 허브 문서 독점(fig_context_report.pdf — R1·R4) |
| synth-distractors-v2 | V2-IQ008 | 정답 문서 8위(R2) |
| synth-xling | XL013·XL014 | 같은 고객의 여러 계약 혼동 |
| synth-terms-hard | HQ-T017 | 허브(R4) |
| synth-4clients-cmp | CMP001~008 | 비교 원천 근거 — 계약별 금액이 여러 문서에 흩어짐(근거 키워드 비율 .371, BR40). 전부 키워드 6개 이상이라 엄격 hit 대신 evid_cov로 |

```bash
# 세트마다(서버·묶음 준비는 mcp_eval 사용법 그대로 — 묶음이 없는 세트는 건너뜀)
PYTHONUTF8=1 .venv/Scripts/python.exe deploy/common_tools/evaluation/mcp_eval.py --set synth-4clients --ids valid_env/unstructured/hard-core/manifest.json
PYTHONUTF8=1 .venv/Scripts/python.exe deploy/common_tools/evaluation/mcp_eval.py --set synth-distractors-v2 --pool --ids valid_env/unstructured/hard-core/manifest.json
```

synth-4clients-cmp는 `evidence_keywords`(BR30) 반영 뒤 편입(10-11). synth-r2는 근거 키워드 기준 상위 3에서 1.0이라 넣지 않음(어려운 문항 아님).

10-14(NM17): `light-hard`는 자동 시험 소비자가 없어 archive로 이동(git 제외, 로컬 `archive/valid_env/unstructured/light-hard/`만) —
아래 재현 명령은 그 로컬 사본이 있어야 돈다(새 체크아웃엔 없음). AD47 타겟 `textlayer_mismatch.pdf`만 `synth-mixedpdf/`로
옮겨 계속 추적한다.

## 파싱 (`parsing`, 15문서 — 세트 이름 = 정답 폴더 위치)

| 세트(정답 폴더) | 문서 | 원인 계열 |
|---|---|---|
| light-hard (`gold/`) | mixed_pages.pdf | 글자+스캔 섞인 PDF(0.667, 대표 선택 불일치) |
| light-hard | garbled_layer.pdf · textlayer_mismatch.pdf | 깨진·다른 숨은 글자층(대표 선택 불일치) |
| light-hard | hidden_term.pdf | 그림 속에만 있는 용어 |
| light-hard · synth-realpat (`gold_human/`) | symbol_spec.pdf | 기호·첨자(×10^6→106, OCR 기호 깨짐) |
| light-hard · synth-realpat | two_column.pdf | 2단 + 공백 든 표 칸 줄바꿈 |
| light-hard · synth-realpat | merged_table.docx | 2단 병합 머리글 |
| light-hard | numfmt_variants.pdf | 숫자 표기 8종(숫자 환각 0.71) |
| synth-realpat | hidden_term.pdf | 그림 속 용어(사람 정답 0.75 → 그림 OCR 대체로 1.0, 병합 뒤 2회 연속이면 뺌) |
| synth-gold-human2 (`gold_human/`) | longtable.pdf | 여러 쪽 표 쪼개짐(BR36) |
| synth-gold-human2 | mail_attach_pdf.eml | 메일 첨부 pdf 추출(BR37) |
| synth-gold-human2 | chart_stability.pdf | 쪽 안 선그림 — OCR 대체 뒤에도 값 1개 오독(0.82) |

이 문서만 파싱해서 채점(`run_all --docs-from`이 목록 문서만 파싱 → `score_gold`는 파싱된 문서만 채점):

```bash
PYTHONUTF8=1 .venv/Scripts/python.exe -c "import json;print('\n'.join(json.load(open('valid_env/unstructured/hard-core/manifest.json',encoding='utf-8'))['parsing']['light-hard']))" > output/hard-core-light.txt
PYTHONUTF8=1 .venv/Scripts/python.exe deploy/data_parsing/run_all.py --src valid_env/unstructured/light-hard --docs-from output/hard-core-light.txt --out output/hard-core/light/parse
PYTHONUTF8=1 .venv/Scripts/python.exe deploy/data_parsing/evaluation/score_gold.py --gold valid_env/unstructured/light-hard/gold --parse output/hard-core/light/parse --out output/hard-core/light/score --plain-names
```

## 갱신 규칙

- 고쳐서 **2회 연속 맞으면** 목록에서 빼고(이력은 이 README 아래에 한 줄), 새로 반복해서 틀리는 문항을 넣는다. 목록이 0이 되면 더 어려운 세트를 만든다.
- 사람 정답 샘플(BR29, `synth-gold-human2`)이 등록되면 그 세트의 놓친 문서를 `parsing`에 더한다.
- `mcp_eval --ids`는 manifest의 `retrieval.<세트>`만 읽는다(`parsing`은 사람이 읽는 목록 + 위 명령).

## 이력

| 날짜 | 문서·문항 | 결과 | 연속 통과 |
|---|---|---|---|
| 10-11 | light-hard mixed_pages.pdf | 0.667→1.0(그림 영역 OCR 대체 main 병합) | 1/2 |
| 10-11 | light-hard·synth-realpat hidden_term.pdf | 0.75→1.0(같은 수정) | 1/2 |
| 10-11 | synth-4clients QA074 | 상위 20 밖 → 해결(BR32 id 검색 문서 수 문턱) | 1/2 |
| 10-11 | synth-4clients-cmp CMP001·CMP002 | 근거 키워드 비율 1.0(BR40 계약 단위 원천 행) | 1/2 |
| 10-11 | synth-4clients-cmp CMP003~008 | .833~.938 — 각 1개 부족(환율 키워드, BR43) | 0/2 |
