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
