# synth-src-problem — 원본 문제(암호·DRM·압축·손상) 재현 [SYNTHETIC]

**왜(SI44·SI45)**: 서버 보고 — 옛 OLE 암호·DRM·압축·손상 파일은 코드로 못 고치는 "원본 문제"로 분류해야
한다(사람이 다시 올리거나 암호를 풀어야 함). PC에는 그 서버 파일이 없어, `deploy/data_parsing/prepare.py`의
암호·DRM·압축 판정과 `deploy/data_parsing/evaluation/run_board.py`의 분류(`SRC_RULES`·`SKIP_KIND`)가 기대대로 묶이는지 재현한다.

**무엇**: 파일 7개 + `expected.json`(파일명 → 기대 prepare 건너뜀 사유·run_board 분류).

| 파일 | 만든 방법 | 기대 분류(run_board) |
|---|---|---|
| `encrypted.doc` | `prepare._build_cfb`(선위험 selftest 공용 헬퍼)로 FIB `fEncrypted` 플래그만 있는 최소 CFB | `encrypted` |
| `encrypted.xls` | 같은 헬퍼로 BIFF `FILEPASS`(0x2F) 레코드만 있는 최소 CFB | `encrypted` |
| `drm.docx` | Fasoo DRM 머리 바이트(`prepare.py DRM_MARKERS`와 같은 표식) | `encrypted`(DRM도 SKIP_KIND에서 `encrypted`로 묶임) |
| `archive.zip` | stdlib `zipfile`로 실제 생성(날짜 고정) | `unsupported` |
| `archive.7z` | 매직바이트(`7z\xbc\xaf\x27\x1c`)만 — 진짜 7z 생성은 stdlib로 불가 | `unsupported` |
| `corrupt.pdf` | 정상 PDF(fitz)를 앞 500바이트만 남기고 자름(`%%EOF`·`trailer`·`startxref` 없음) | `corrupt`(단, 아래 '발견' 참고) |
| `normal.pdf` | 정상 1쪽 PDF | 없음(정상 대조군) |

진짜 암호 OLE·실제 7z를 stdlib만으로 만들 수 없어, `encrypted.doc`·`encrypted.xls`·`archive.7z`는 판정
함수가 보는 **최소 신호**만 재현했다(prepare.py selftest가 쓰는 것과 같은 헬퍼·같은 패턴).

**시험**: `dev_tools/unit_test/pipeline/test_synth_src_problem.py` — `prepare.py` 판정 함수 → `expected.json`의
`prepare_skip_reason`과 같은지, 그 사유를 `run_board.skip_kind`에 넣으면 `run_board_kind`와 같은지, 전부
`run_board.CLASS[kind] == "src"`(원본 문제)로 묶이는지.

## 발견 (코드는 고치지 않음 — 구현 세션이 판단)

`corrupt.pdf`를 `prepare.py`는 거르지 않는다(머리 바이트 `%PDF`가 정상이라 DRM·암호·미지원 판정 모두
통과 — 설계상 맞음, 엔진이 실제로 열다가 내는 오류로 분류하는 단계라서). 문제는 그 다음 단계: 이 파일을
**pypdfium2**로 직접 열면 실제로 나오는 오류 문구는

```
PdfiumError: Failed to load document (PDFium: Data format error).
```

인데, 이는 `run_board.py`의 `SRC_RULES`(`EOF marker|startxref|truncated|cannot identify image|invalid
(?:pdf|header)|corrupt|damaged|bad magic|premature end`) 어느 패턴에도 걸리지 않아 `src_kind()`가
`None`을 돌려준다(= "손상 의심"으로 못 묶임). `run_board.py` 자체 문서가 예로 드는 `PdfReadError: EOF
marker not found`(PyPDF2류 메시지)로는 정상적으로 `corrupt`가 나온다 — 즉 `SRC_RULES`는 PyPDF2/calamine류
엔진 메시지를 겨냥했고, pypdfium2가 직접 내는 메시지는 아직 안 걸린다.
`dev_tools/unit_test/pipeline/test_synth_src_problem.py::test_pypdfium2_actual_corrupt_message_matches_src_rules`에
`xfail`로 남겨 뒀다 — `run_all.py`가 실제로 pypdfium2 오류를 `runs.jsonl`에 그대로 적는 경로가 있다면
`SRC_RULES`에 `data format error` 같은 패턴을 추가할지 구현 세션이 판단.

다시 만들기: `PYTHONUTF8=1 .venv/Scripts/python.exe dev_tools/synthetic_data_gen/gen_synth_src_problem.py`
(zip은 `ZipInfo.date_time` 고정 + `ZIP_STORED`, pdf는 fitz 메타 고정 + `no_new_id=True` — 같은 입력이면
같은 바이트).
