# synth-distractors-v2 — 구판(옛 개정판) 방해 문서 + 최신본 질문 + 전체 합쳐 검색 [SYNTHETIC]

**왜**: v1(`synth-distractors`)은 오인율 0·포화 유지(다른 세션 loop2) — 채점 문항에 바뀐 ID·고객명이 남아 키워드로 쉽게 구분됐다.

**무엇**
- `docs/` 63건 — 평가셋 정답 문서의 **구판**: ID·고객명·제품명은 그대로, 연도 −1·수치만 바꿈, 첫 줄 `[구판] … 이전 개정판(최신본 아님)`. 그림은 넣지 않음.
- `qa.json` 25문항 — 기존 문항 앞에 "최신 문서 기준으로 답하라 —" · 근거는 원래 세트의 원본(`evidence[].dataset`) · 구판에서 바뀐 값은 `forbid_keywords`(구판 값을 답하면 오답). 세트별: plant 5 · hard 5 · images 5 · tables 6 · ops 2 · terms 2.
- `pool.json` 469문서 — **전체 합쳐 검색** 목록(평가셋 전 세트 150 + synth-4clients 200 + v1 56 + v2 63, synth-charts 제외 — 10-05 갱신). v1·v2는 같은 파일 이름 44건이 있어 색인 때 세트 접두어(`<세트>__`)로 구분. 세트 안(12~22문서) 대신 이 전체를 한 묶음으로 색인.

**쓰는 법(평가 도구 — 다른 세션)**: `--pool pool.json`으로 한 묶음 색인 → 기존 세트 문항 + 이 qa.json 채점 · 지표: 정답률 · 구판 오인율(근거 상위에 구판이 원본보다 먼저) · R@1·MRR.

다시 만들기: `.venv/Scripts/python.exe dev_tools/synthetic_data_gen/gen_synth_versions.py` (평가셋이 바뀌면 다시).
