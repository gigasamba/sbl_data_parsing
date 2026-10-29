# synth-distractors — 방해 문서(negative control) [SYNTHETIC]

**왜**: 조합 비교(stack_matrix)에서 검색 범위가 세트 안(12~22문서)이라 R@5가 0.84~1.0으로 포화 → 상위 10개 중 9개가 "1위와 동급"으로 나와 순위가 결정을 못 한다(비교 보고서 구성안 9-2 F6).

**무엇**: 평가셋 정답 문서마다 같은 양식·주제의 **글자만 있는 사본**. 고객(이름·별칭)·설비/문서 ID·연도·수치(±5~10%)를 바꿨다. 그림·이미지는 넣지 않는다(그림 내용은 원본에만).
- 56문서 = synth-edw 10 · synth-hard 7 · synth-images 11 · synth-ops 12 · synth-plant 9 · synth-tables 7
- 파일 이름 `<원본 세트>__<원본 파일>` · 문서 첫 줄에 "[가상 예시] … (방해 문서)" 표시
- 만들지 않은 것: synth-charts(다른 세션 held-out — 내용을 보지 않음), 글자층 없는 스캔·그림뿐인 문서

**정답 영향** — `targets.json`의 `questions[].unique_under_distractors`
- true: 질문에 바뀐 토큰(ID·고객·연도)이 있음(57) · 정답이 그림에만 있음(45) · 정답 문서가 이미지·스캔(9)
- false(49): 질문만으로 원본과 방해 문서를 가를 수 없음(방해 문서에 같은 항목의 다른 값) → **방해 문서 채점에서 뺀다**
- 160문항 중 113문항이 방해 문서를 넣어도 정답이 하나로 정해진다.

**쓰는 법(평가 도구 쪽 — 다른 세션 작업, 백로그 V11)**: `--with-distractors`이면 세트 `X`의 묶음에 `source_dataset == X`인 방해 문서를 더해 색인하고, `unique_under_distractors == true`인 질문만 채점. 방해 문서가 상위 k에 들어간 비율(오인율)도 함께 남긴다.

다시 만들기: `.venv/Scripts/python.exe dev_tools/synthetic_data_gen/gen_synth_distractors.py` (같은 입력이면 같은 바이트). 평가셋(`eval_set.json`)이 바뀌면 다시 만든다.
