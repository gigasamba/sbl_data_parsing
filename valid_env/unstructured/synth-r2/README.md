# synth-r2

구현 세션 c0의 1차 실패 분석(`round1/failures.md` §5)이 요청한 샘플 4~9번과 백로그 BR9(큰 표)·BR13(줄바꿈·문단)을
재현하는 새 세트. 기존 세트(`gen_synth_4clients.py`·`gen_synth_hard.py` 등)는 다시 돌리지 않았다 — 전부 새
생성기 `dev_tools/synthetic_data_gen/gen_synth_r2.py`로, 새 가상 고객/CDMO("코발트팜(주)" · "루멘바이오(주)")와 새 문서로 만든다.

용도: c0의 2차 검증과 답변 단계 평가 도구(`dev_tools/perform_test/answer_stage`)가 쓴다. 모든 회사·값은 가상이다.

## 재생성

```
.venv/Scripts/python.exe dev_tools/synthetic_data_gen/gen_synth_r2.py [--out valid_env/unstructured/synth-r2] [--selftest]
```

`--selftest`: 각 질문의 `answer_keywords`가 정답 문서의 "파싱 전 생성 원문"에 실제로 있는지 확인(생성기 자기 점검).
결정적(같은 코드 → 같은 바이트) — 오피스 파일(docx·xlsx)은 zip 항목·docProps 시각을 고정(`_stable_zip`),
PDF는 생성 시각 메타 고정(`_save_pdf`), eml은 멀티파트를 쓰지 않아(단일 text/plain) boundary 임의성이 없다.
mht만 멀티파트이며 boundary를 고정 문자열로 박아 둔다.

## 정답 형식

`qa.json`의 `answer_keywords`: 리스트 항목 사이는 AND(하위 사실마다 따로 채점), 한 항목 안 `|`는 OR,
`A~B`는 "A 뒤 20자 안에 B", `A~~B`는 "같은 줄(행) 안에 A와 B" — `dev_tools/synthetic_data_gen/_synth_images_qa.py`의
`score()`와 완전히 같은 규칙.

## 요청 → 문서 · 질문 대응표

| 요청 | 재현할 특징 | 문서 | 질문 |
|---|---|---|---|
| 4 | 같은 메일의 형식 사본(eml·htm·mht·스크린샷) 여럿 + 답은 메일이 아니라 별도 계약서·견적서에만 | `mail_notice.eml/.htm/.mht/.png`(동일 내용 4벌, 가격 없음) · `contract_C-LUX-2026-09.docx`(단가) · `quote_C-LUX-2026-09.pdf`(MTOP) | R2Q001·R2Q002 |
| 5 | 3종 문서에서 하위 사실 3개 이상을 모으는 질문(사실마다 따로 채점) | `spec_LUX-ADC-04.pdf`(제품 사양) · `contract_C-LUX-2025-11.docx`(계약) · `mail_delivery_LUX-ADC-04.eml`(메일) | R2Q003·R2Q004 |
| 6 | 허브 문서(같은 고객·제품명 20회+ 반복)가 검색을 독점 + 실제 값은 xlsx·긴 표의 소수 행에만 | `hub_report_LUX-VAC-03.docx`(허브, 2025 Q3=11배치는 함정) · `hub_data.xlsx`(2026 Q3=14배치, 진짜 값) · `hub_long_table.docx`(60행 표, LUX-ADC-37 1행만 대상) | R2Q005·R2Q006 |
| 7 | 표 모양이 같은 옛 판·방해 판 xlsx(평탄 값 시트 + 수식 시트), 판 구분은 기준일 | `rates_v1.xlsx`(기준일 2025-01-01, 단가·합계 모두 함정) · `rates_v2.xlsx`(기준일 2026-01-01, 최신) | R2Q007·R2Q008 |
| 8 | ID가 파일명에만 있고 본문에는 없는 메일(eml) | `MAIL-LUX-14.eml` · `MAIL-LUX-15.eml`(본문은 배치 번호·출하일만, 파일명의 ID는 본문에 없음) | R2Q009·R2Q010 |
| 9 | 비었거나 거의 빈 이미지 여러 장(스크린샷 머리글만) + 답은 다른 문서 | `blank_mail_1/2/3.png`(머리글만, 근거면 오탐) · `target_memo.docx`(실제 답) | R2Q011·R2Q012 |
| BR9 | 큰 표 — 240행 xlsx(2시트) + 70행 PDF(쪽 넘김·머리글 반복), 행 조회 + 집계(최댓값·합계) | `big_table.xlsx`(2026H1/2026H2 시트, 240행) · `big_table.pdf`(4쪽, 70행 + 합계 줄) | R2Q013~R2Q016 |
| BR13 | 줄바꿈·문단 순서가 의미를 바꿈(단계 목록) + 2단 레이아웃(좌우 값 섞임 위험) | `steps_order.docx`(현재 5단계 + 개정 전 순서를 언급하는 참고 문단) · `two_col_layout.pdf`(협력사 A·B 2단) | R2Q017~R2Q020 |

문서 24개 · 질문 20개(요청당 2개, BR9·BR13은 4개). `msg` 형식은 만들지 않았다(순수 파이썬 OLE2 writer가
없음 — `gen_synth_formats.py`와 같은 사유, 어려우면 뺀다는 지시에 따름).

## 확인된 것

- 생성기를 2번 돌려 바이트까지 동일(파일별 diff 없음).
- 생성 전/후 `git diff --stat` — 기존 세트 파일 변경 0(이 세트의 신규 파일과 `catalog.jsonl`/`eval_set.json`만 변경).
- `dev_tools/synthetic_data_gen/eval_set.py` · `dev_tools/synthetic_data_gen/validation_catalog.py build` · `pytest dev_tools/unit_test/qa/test_validation_catalog.py` 통과.
- `--selftest`: 20문항 전부 정답 문서의 생성 원문에서 키워드 확인됨.
