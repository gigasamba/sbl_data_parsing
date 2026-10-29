# synth-eml-charset — EUC-KR/CP949 메일 인코딩 재현 [SYNTHETIC]

**왜(SI42)**: 서버 운영 중 EUC-KR·CP949로 쓰인 메일이 한글이 깨져 보인다는 보고. PC에는 그 서버 메일이 없어
재현 샘플이 필요했다 — `decode_mail_text`(`deploy/data_parsing/engines/mhtml/parser.py`)가 실제 깨짐 패턴을 전부
덮는지 PC에서 확인하는 용도.

**무엇**: `.eml` 7건, 가상 CDMO "버추얼팜코"가 가상 고객에게 보내는 배치·계약 통지 메일(계약번호·배치
수·금액). 제목은 전부 RFC2047 `=?euc-kr?B?...?=` 인코딩.

| 파일 | 특징 |
|---|---|
| `notice_euckr.eml` | `Content-Type charset="euc-kr"`, 8bit |
| `notice_cp949.eml` | `charset="cp949"`, 8bit |
| `notice_ksc5601_ext.eml` | `charset="ks_c_5601-1987"` 선언인데 실제 바이트는 CP949 확장 글자(똠·쀍) 포함 — Python의 `ks_c_5601-1987`→`euc_kr` 별칭이면 이 글자만 깨진다. `decode_mail_text`의 widen 규칙(선언→cp949)을 직접 건드리는 케이스 |
| `notice_no_charset.eml` | `Content-Type`에 charset 파라미터 없음, 8bit cp949 바이트 |
| `notice_qp.eml` | `Content-Transfer-Encoding: quoted-printable`(euc-kr) |
| `notice_base64.eml` | `Content-Transfer-Encoding: base64`(cp949) |
| `notice_attachment.eml` | 한글 첨부 파일명(`배치내역.csv`, RFC2231 `filename*=cp949''...`) + 첨부 본문도 cp949 |

`.msg`는 만들지 않았다 — MsgKit(.NET, `_msg_writer`)으로 만들어야 하는데, 이 세트가 필요한 건 `.eml`의
MIME 헤더 charset 조합(선언 불일치·전송 인코딩·RFC2231)뿐이라 `.msg`까지 늘리는 건 이 재현 목적에 비해
과하다(기존 `synth-legacy/notice.msg`가 이미 `.msg` 경로를 덮는다).

**정답**: `spec.json`(문서별 facts) · `qa.json`(문항 4개, `valid_env/unstructured/synth-legacy` 형식과 같음,
`_synth_images_qa.score`로 채점) · `gold/`(문서별 `.md` + `values.csv`).

**시험**: `dev_tools/unit_test/pipeline/test_synth_eml_charset.py` — `parse_mhtml`·`decode_mail_text`로 7건을 읽어
치환 문자(`�`) 없이 사실 값이 나오는지, 제목이 RFC2047로 풀리는지, 첨부 파일명·본문이 복원되는지.

다시 만들기: `PYTHONUTF8=1 .venv/Scripts/python.exe dev_tools/synthetic_data_gen/gen_synth_eml_charset.py`
(stdlib(`base64`·`quopri`)만 써서 같은 입력이면 같은 바이트 — 시각·GUID 없음).
