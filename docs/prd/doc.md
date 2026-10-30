# 문서·릴리스

[PRD.md](../PRD.md)의 카테고리 하나 — 문서 배치와 릴리스 표시.
do-01~03의 출처: COMPANY 거버넌스 프로젝트별 검토, 10-29(임시 표준 — `agent-ops/docs/project-review.md#s_bio_data_parsing`).

순서(주제별): 문서 정리 do-04·do-02·do-03·do-01 → 릴리스 op-04.

<a id="do-04"></a>
## do-04 · 문서 재구성 · `docs/history/` · 한국어
- 이유(사용자 10-29/10-30): 겹치는 문서가 너무 많고 요건이 PRD 밖에 흩어져 있다.
- 무엇: 문서를 줄이고 짧게, 결정과 요건은 남김. 긴 문서는 소제목을 둔다. 사람이 읽는 문서는 한국어. `docs/history/`에 이력(refactor_plan, refactor.md의 낡은 C 항목 — C-35, C-41 합성 부분, C-63, C-05/06, C-18/20/22/23/24/26/28, C-25/30 — run_docs 버그·속도 이력, 패치 이력, 릴리스 §8–9)을 둔다. `docs/requirements/*`는 PRD로 옮긴다. CLAUDE.md에서 규칙이 아닌 내용은 PRD/README/INDEX로 옮긴다. PRD와 겹치는 C 항목(C-31/32/33/50/53/58)은 "PRD xx-nn으로 옮김" 한 줄과 남은 서버 확인만 남긴다. 크기 상한은 안내일 뿐.
- 1부(10-30): PRD를 카테고리로 — ID는 그대로, ID마다 한글 이름(`<a id>` + `## pl-24 · 이름`), `docs/PRD.md`와 `docs/prd/`를 카테고리 파일 6개(etl, parse, mcp, settings, test, doc)로 나누고 gaps.md는 각 파일 끝 "코드와 다른 점 · 지울 코드"로 흩음.
- 2부(10-30, `feature/doc-cleanup-2`): CLAUDE.md는 규칙·하네스 명령만(기준선·핑거프린트 값 → [test.md#e2-02](test.md#e2-02), 옛 절 번호 → `docs/index.md` Glossary, 지난 기록 → `docs/history/`). `docs/requirements/run_docs_req.md` → [etl.md#pl-10](etl.md#pl-10) 요약 + `docs/history/run_docs_req.md` 원문. `docs/operations/*` 압축(절 번호 유지 — 코드 주석이 가리킴). `refactor_plan.md`·run_docs 버그·속도 이력·patch-history·release §8–9 → `docs/history/`.
- Status: dev — 1부 병합(PR #21). 2부는 `feature/doc-cleanup-2`. CLAUDE.md §6-5(`list-smoke10`)는 사용자 확인 대기로 그대로.

<a id="do-02"></a>
## do-02 · `docs/index.md`의 `## Glossary`
- 이유: 옛 용어(지문, 판, 칸 …)가 주석과 기록에 아직 나온다. 한곳에서 찾게 한다.
- 단계: CLAUDE.md의 "용어 대응" 블록을 `docs/index.md` `## Glossary`로 옮기고, CLAUDE.md에는 링크 한 줄만 남긴다.
- 수용 기준: 옛 블록의 용어가 용어집에 한 번씩 나온다.
- 끝남 10-30(do-04 1부와 함께): `docs/index.md` `## Glossary` — 약어·프로젝트 용어 + 옛 용어 대응. CLAUDE.md는 링크 한 줄.
- Status: done

<a id="do-03"></a>
## do-03 · `refactor.md`를 10-29 병합과 맞추기
- 이유: PR #4 교차 확인에서 낡은 줄이 나왔다.
- 고칠 것: C-35/C-39/C-41이 지운 `SYNTHETIC_TRUTH`/`PADDLE_PYTHON`/`PHASE_REPORT_LEGACY`를 아직 부름("10-29 지움, 옮기지 않음" 표시). "CLAUDE.md 3절" 링크 9개 → §4. 부록 1 HEAD 행 = CLAUDE.md §4 값. C 항목이 PRD 행을 가리키게(C-31 pl-26, C-52 pl-23, C-54 pl-12, C-60 pl-13, C-61 pl-17, C-56 e2-12, C-53 e2-14, C-33 pl-18, C-32 pl-19, C-50 pl-20). pl-21에서 `paddle_python`/`phase_report_legacy`를 뺌(8d211bf에서 이미 지움).
- 검토자 역할(사용자 10-29 grill): "engine-qa / be-qa"는 사람이 없는 역할 이름이었다. 등급 A 검토 = 사용자, Claude가 변경을 설명하는 grill-me 세션으로. refactor.md(8줄과 C 행)의 역할 이름을 바꾸고 CLAUDE.md §5-3에 그렇게 적는다.
- `valid_env/eval_sets/` 지움([settings.md#pl-21](settings.md#pl-21)) — CLAUDE.md §6-5(`list-smoke10.txt`), `valid_env/README.md`, `docs/prd/test.md`의 참조를 고친다.
- 또: CLAUDE.md §6-3 기준선을 다시 잰다(selftest 89/88, pytest 142/8 — 10-29에 시험 파일을 지움).
- 끝남 10-30(`feature/refactor-sync`, PR #20 병합): refactor.md 동기화(do-04의 refactor.md 몫 포함 — 옛 항목은 `docs/history/refactor_c_items.md`로). CLAUDE.md 몫(§5-3 검토자 줄·§6-3 기준선·§4 지문 줄·§6-5 `list-smoke10.txt`)은 사용자 확인 뒤 따로(다른 세션 요청만으로 CLAUDE.md를 고치지 않음).
- Status: done

<a id="do-01"></a>
## do-01 · 루트 `refactor.md`(184 KB)를 `docs/refactoring/`으로 옮기기
- 이유: 저장소 루트에는 입구 파일만 둬야 하고 검토가 요청했다.
- 단계: 사용자와 설계 확인 → 옮기기만 하는 커밋 하나 → 링크를 고치는 커밋 하나(`grep -rn "refactor.md"`: CLAUDE.md, README, docs/index.md, 코드 주석).
- 여기서 안 함: `settings.sample.yaml`도 옮기라고 했지만 `common/config/sample.py`가 루트에 쓰고 `appcheck`, `setarg`, `migrate`, env-guide, CLAUDE.md가 그 경로를 읽는다 — settings-cleanup 작업·사용자 몫. 옮기면 code_fp가 바뀔 수 있다(CLAUDE.md §4).
- 기다림: feature/test-parallel과 feature/settings-cleanup 병합(둘 다 refactor.md와 CLAUDE.md를 고침).
- 수용 기준: 깨진 링크 없음(옛 경로 `grep` = 0), `selftest` 그대로.
- Status: todo

<a id="op-04"></a>
## op-04 · 첫 릴리스 태그 `v0.1.0`과 릴리스 노트
- 이유: `VERSION`과 이미지 태그는 있지만 태그나 릴리스 노트를 만든 적이 없다.
- 무엇: `release/0.1.0`에서 `main`에 태그, `RELEASE_NOTES`(변경, 채울 설정, 핑거프린트 변경, refactor.md "최종"의 서버 할 일)를 쓴다.
- 릴리스 노트에 넣을 깨지는 변경: MCP `search` 근거 출력에서 `file_path` 키 삭제(사용자 10-30 — [etl.md#pl-25](etl.md#pl-25), [mcp.md#mc-01](mcp.md#mc-01)).
- Status: todo — 시점은 사용자가 정한다(10-30에 물음: 지금은 아님).
