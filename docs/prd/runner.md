# Server flow runner — lanes and queues (rn)

Scope: `deploy/host/scripts/run_docs.py` (runs on the server host, outside the image — no fingerprint impact). Design: [../architecture/run_docs_design.md](../architecture/run_docs_design.md). Utterance log: [../requirements/run_docs_req.md](../requirements/run_docs_req.md).

User 10-29: "data-pipeline 하는데 3개 lane으로 해서, light/medium/vlm 구분해서 배분하고, 특정 lane은 담당, 일부 lane은 steal 허용하는 대신 우선순위는 담당 lane으로 지정. queue 관리해서 진입 시점 개수와 중간 개수 등을 관리."

## Already there (pass — no row)
- 3-lane split: `classify_doc()` sorts each warmed doc into light/medium/vlm; workers `LANE_N` light 1 / medium 2 / vlm 1; each worker drains its own lane first ([pipeline.md](pipeline.md) server flow runner).
- Entry queue: `WARM_TARGET` (12, `--warm`) docs downloaded ahead; in-flight docs not counted; temp files removed when a doc ends.
- MCP priority: `_mcp_pause_monitor()` stops the medium lane from taking new docs while `mcp_parse/jobs` is active (server measurement still open — design doc).

## rn-01
Lane policy as one table: owner lane first, steal only from listed lanes. Why: today the rules are hard-coded in `lane_worker()` (light/vlm never take medium; longest other queue first; vlm capped by `VLM_CAP`) with dead branches, and worker counts are a constant — tuning needs a code edit.
- Steps: (1) one policy table per lane: `workers`, `steal_from` (empty = dedicated lane). Default = today's behavior. (2) A worker steals only when its own queue is empty; among allowed lanes, longest first; `VLM_CAP` still applies. (3) Input: runner arg `--lanes` (host script — whether a settings.yaml section is needed is decided at design; never env, CLAUDE.md §3). (4) Remove dead branches.
- Acceptance / QA: table rows in `tests/general/deploy/test_run_docs.py` — (queues, policy) → picked doc. A dedicated lane never takes other docs even when they wait; own non-empty queue → no steal; vlm over cap is skipped; default policy picks the same docs as today.
- Files: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`, `docs/architecture/run_docs_design.md`.
- Overlap: parse "phase" removal on feature/settings-cleanup's follow-up touches the same runner — coordinate first.
- Status: todo

## rn-02
Mid-queue cap (parsed → waiting for structure) and queue depth log. Why: `struct_q` has no limit, so a slow structure step lets parsed results pile up (disk, wait time); the 10-22 ask "queue 더 쌓이면 구조화 대기가 더 오래 걸리는지" has no depth data — only per-doc `queue_wait` in `doc_stats.jsonl`.
- Steps: (1) `--struct-backlog N`: when N docs wait for structure, lane workers take no new doc (block at pick time in `lane_worker`, not at `struct_q.put`, so a parse worker never holds a finished result). 0 = no cap (today). (2) On every `mark()` event write one line `{t, warm, lanes: {light: [waiting, running], ...}, struct_wait}` to the progress folder (follow op-01's line format if it lands first).
- Acceptance / QA: with structure stubbed to stall, waiting-for-structure never exceeds N; N=0 matches today; depth lines parse as JSON and add up to the docs seen.
- Files: `deploy/host/scripts/run_docs.py`, `tests/general/deploy/test_run_docs.py`.
- Status: todo
