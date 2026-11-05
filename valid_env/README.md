# valid_env/ — 외부 시스템 대역(PC 전용, 어떤 이미지에도 들어가지 않음)

서버가 바깥 시스템에서 읽는 것을 PC에서 흉내 내는 데이터를 한곳에 둔다.

| 폴더 | 대신하는 것 | 내용 | git |
|---|---|---|---|
| `object_storage/` | Object Storage 버킷(원본 문서) | 문서 1건 = `<원천>/<uuid>/<파일>`: `CRMS/` 어려운 사례 21건 + hanbit 문서 36건, `SFDC/` RFP 12건 + hanbit 문서 10건, `FAQ/` FAQ 엑셀 1건. 문서마다 있는 이유: [object_storage/test_doc_purpose.md](object_storage/test_doc_purpose.md) | 추적, 바이트 그대로 |
| `edw/` | 회사 EDW(SQL Server) | `ai`·`crms`·`las`·`sfdc` `.sql`(표 정의 + 합성 행, `[SYNTHETIC]`)과 그것으로 만든 `edw.sqlite`(`python -m validation.e2e.edw_standin`). `meta_rdb/` = RDB 문서 위치·마스터 표(서버 배포 테스트가 읽음) | 추적 |
| `answer_test/rag_qa/` | 서빙 Answer Agent(PC 답변 점검) | `python -m validation.e2e.answer_gen`이 쓰는 agent 묶음 | 추적 |
| `docker/` | 서버 컨테이너 | PC 시험 compose(`compose.pg.yml`, `compose.test.yml`, `smoke_test.sh`) | 추적 |

- 여기 있는 것은 모두 합성 데이터다. 실행 중에는 여기에 쓰지 않는다 — 결과는 `output/` 아래로 간다. 예외 둘(PC `local` 기본값 — git이 무시함): 가짜 EDW 사본 `edw/edw_copy.sqlite`(없으면 `edw/edw.sqlite`를 복사해 만듦 — 원본은 그대로)와 게시 폴더 `object_storage/Parsing_Result/`(원본 목록에서 빠짐).
- `--src`는 폴더를 받는다. 몇 건만 돌릴 때는 고른 문서를 한 폴더에 복사해 넘긴다(README §4-4).
