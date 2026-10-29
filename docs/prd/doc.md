# Docs layout (do)

Source: COMPANY governance per-project review, 10-29 (interim standard — `agent-ops/docs/project-review.md#s_bio_data_parsing`).

## do-01
Move root `refactor.md` (184 KB) to `docs/refactoring/`. Why: the repo root should hold only entry files; the review asks for it.
- Steps: design check with the user → one commit that only moves → one commit that fixes links (`grep -rn "refactor.md"`: CLAUDE.md, README, docs/index.md, code comments).
- Not here: `settings.sample.yaml` also was asked to move, but `common/config/sample.py` writes it to the root and `appcheck`, `setarg`, `migrate`, env-guide and CLAUDE.md read that path — left to the settings-cleanup work / the user. Moving it may change code_fp (CLAUDE.md §4).
- Wait for: feature/test-parallel and feature/settings-cleanup merged (both edit refactor.md and CLAUDE.md).
- Acceptance / QA: no broken links (`grep` for the old path = 0), `selftest` unchanged.
- Status: todo

## do-02
`## Glossary` in `docs/index.md`. Why: old terms (지문, 판, 칸 …) still appear in comments and records; one place to look them up.
- Steps: move the "용어 대응" block from CLAUDE.md to `docs/index.md` `## Glossary`; CLAUDE.md keeps one link line.
- Acceptance / QA: every term in the old block appears once in the glossary.
- Status: todo

## do-03
Sync `refactor.md` with the 10-29 merges (PR #4). Why: a cross-check found stale lines.
- Fix: C-35/C-39/C-41 still name removed `SYNTHETIC_TRUTH`/`PADDLE_PYTHON`/`PHASE_REPORT_LEGACY` (mark "removed 10-29, do not carry over"); 9 "CLAUDE.md 3절" links → §4; appendix 1 HEAD row = CLAUDE.md §4 values; C items link their PRD rows (C-31 pl-26, C-52 pl-23, C-54 pl-12, C-60 pl-13, C-61 pl-17, C-56 e2-12, C-53 e2-14, C-33 pl-18, C-32 pl-19, C-50 pl-20); pl-21 drops `paddle_python`/`phase_report_legacy` (already removed in 8d211bf).
- Reviewer roles (user 10-29 grill): "engine-qa / be-qa" were role names with no person. Grade A review = the user, through a grill-me session where Claude walks through the change; replace the role names in refactor.md (line 8 and the C rows) and CLAUDE.md §5-3 says so.
- `valid_env/eval_sets/` deleted ([pipeline.md#pl-21](pipeline.md#pl-21)) — fix references in CLAUDE.md §6-5 (`list-smoke10.txt`), `valid_env/README.md`, `docs/prd/e2e.md`.
- Also: re-measure the CLAUDE.md §6-3 baseline (selftest 89/88, pytest 142/8 — test files were deleted 10-29).
- Status: todo — before do-01 moves the file.
