"""validation.e2e.stack_matrix 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m validation.e2e.stack_matrix selftest`."""

import argparse
import json
import tempfile
import time
from pathlib import Path

from common.config import settings as S
from common.core import artifacts as A
from validation.e2e import model_matrix as MM
from validation.e2e import stack_matrix as M
from validation.e2e.stack_matrix import (
    _CFG,
    AXES,
    CONFIG_PATH,
    DISTRACTOR_DS,
    DISTRACTOR_V2_DS,
    PROJ_ROOT,
    _answer_eval,
    _distractor_cache,
    _must_not_violations,
    _rank_confusion,
    cmd_answer,
    cmd_report,
    distractor_files_for,
    distractor_unique_ids,
    load_config,
    main,
    mirror_distractor_docs,
    mirror_parse_dir,
    mirror_pool,
    ofat_combos,
    p1_dir,
    p1_status,
    pool_distractor_files,
    pool_fp,
    pool_r_parts,
    qa_fp,
    r_parts,
    s_dir,
    vlm_fp,
)


def cmd_selftest(config, a):
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    # S2b(VS2 B-1) — 두 설정의 stack_json이 실제 엔진 구성 파일(resources/config/)을 가리키는지
    mm_config = MM.load_config()
    check(
        "stack_json이 있는 엔진 구성 파일을 가리킴(stack_matrix·model_matrix)",
        MM.stack_file(config).is_file() and MM.stack_file(mm_config).is_file() and MM.stack_file({}).is_file(),
    )
    # S6a2 — 설정의 상대 경로(eval_set_path·distractors.targets)는 저장소 루트 기준 — 저장소 밖이면 split·방해 문서가 조용히 빈 값
    rel = [c.get("eval_set_path") for c in (config, mm_config)] + [(config.get("distractors") or {}).get("targets")]
    check(
        "eval_set_path·distractors.targets가 저장소 안을 가리킴(stack_matrix·model_matrix)",
        all(not v or Path(v).is_absolute() or (PROJ_ROOT / v).resolve().is_relative_to(PROJ_ROOT.resolve()) for v in rel),
    )

    # 10-13 — VLM 지문이 주소·유료 차단을 구분하는지(빈 VLM P1·S 재사용 방지)
    with S.isolated(VLM_MODEL="m", VLM_BASE_URL="https://x/v1", NO_PAID_CALLS="0"):  # S7e2 — 시험 설정(끝나면 되돌림)
        fp_real = vlm_fp()
        S.put(NO_PAID_CALLS="1")
        fp_blocked = vlm_fp()
        S.put(NO_PAID_CALLS="0", VLM_BASE_URL="http://127.0.0.1:0")
        fp_dummy = vlm_fp()
    check("vlm_fp가 유료 차단·막힌 주소를 진짜 VLM과 구분", len({fp_real, fp_blocked, fp_dummy}) == 3)

    combos = ofat_combos(config)
    names = [c["name"] for c in combos]
    check("ofat: baseline 정확히 1개", names.count("baseline") == 1)
    import inspect as _insp

    check(
        "비용 관문: main이 실행별 LLM_SPEND_FILE을 자동 지정(10-05 재검증 — 빠지면 예산이 프로세스 수만큼 곱해짐)",
        "put(LLM_SPEND_FILE=" in _insp.getsource(main),
    )
    with S.isolated(SEARCH_RECENCY="1"):  # 10-05 회귀 — pool 열쇠도 스위치(최신본 우선)가 바뀌면 달라야 함(S7e2 시험 설정)
        p_on = pool_r_parts("s", combos[0], ["a"])
        r_on = r_parts("s", combos[0], "ds-없음")
        S.put(SEARCH_RECENCY="0")
        p_off = pool_r_parts("s", combos[0], ["a"])
        r_off = r_parts("s", combos[0], "ds-없음")
    check("열쇠: SEARCH_RECENCY가 따로 색인·pool R 열쇠 모두에 반영", p_on != p_off and r_on != r_off)
    check("ofat: 조합 이름 중복 없음", len(names) == len(set(names)))
    with tempfile.TemporaryDirectory() as td:  # 미러를 고쳐도 원본은 그대로(10-04 하드링크 오염 회귀 방지)
        src_t, mir_t = Path(td) / "src", Path(td) / "mir"
        (src_t / "eng").mkdir(parents=True)
        (src_t / "runs.jsonl").write_text("원본\n", encoding="utf-8")
        (src_t / "eng" / "a.json").write_text("{}", encoding="utf-8")
        mirror_parse_dir(src_t, mir_t)
        with (mir_t / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write("미러에 덧붙임\n")
        (mir_t / "eng" / "a.json").write_text('{"x": 1}', encoding="utf-8")
        check(
            "미러 수정이 원본을 안 바꿈(복사, 하드링크 아님)",
            (src_t / "runs.jsonl").read_text(encoding="utf-8") == "원본\n"
            and (src_t / "eng" / "a.json").read_text(encoding="utf-8") == "{}",
        )
    for c in combos[1:]:
        if c["name"].startswith("extra"):
            continue
        changed = sum(1 for ax in AXES if c[ax] != combos[0][ax])
        check(f"ofat: {c['name']}은 정확히 1개 축만 baseline과 다름", changed == 1)

    with tempfile.TemporaryDirectory() as td:
        store = Path(td) / "store"
        d = store / "s" / "abcd1234" / "structure-x@11112222"
        parts = {"post": "baseline", "dataset": "ds1", "chunker": "structure", "embed": "x", "chunk_size": None, "summary": "lead"}
        A.manifest(d, "s", parts)
        check("build 스킵 판정: 갓 만든 저장본은 reused(안 낡음)", A.is_stale(d) == (False, ""))

        p1_fail = p1_dir(store / "nope", {"id": "baseline"}, "ds-없음")
        s2, r2 = p1_status(p1_fail)
        check("p1_status: 없는 폴더는 missing", s2 == "missing" and r2 is None)

    # V11 — 방해 문서 미러 병합 + 열쇠 분리(평소 저장본과 안 섞임). _CFG를 fixture로 잠깐 바꿔쓰고 원복.
    saved_rb, saved_dist = dict(_CFG.get("reuse_bundles") or {}), dict(_CFG.get("distractors") or {})
    try:
        with tempfile.TemporaryDirectory() as td3:
            dd = Path(td3)
            dist_parse = dd / "distsrc"
            (dist_parse / "engineA").mkdir(parents=True)
            (dist_parse / "engineA" / "dsX__a.pdf.json").write_text(json.dumps({"text": "x"}), encoding="utf-8")
            (dist_parse / "qa.json").write_text(json.dumps({"docs": {"dsX__a.pdf": {"format": "pdf", "engines": {}}}}), encoding="utf-8")
            (dist_parse / "runs.jsonl").write_text(json.dumps({"doc": "dsX__a.pdf", "engine": "engineA"}) + "\n", encoding="utf-8")
            targets = dd / "targets.json"
            targets.write_text(
                json.dumps(
                    {
                        "documents": [{"file": "dsX__a.pdf", "source_dataset": "dsX"}],
                        "questions": [{"id": "Q1", "dataset": "dsX", "unique_under_distractors": True}],
                    }
                ),
                encoding="utf-8",
            )
            _CFG["reuse_bundles"] = {**saved_rb, DISTRACTOR_DS: {"parse_dir": str(dist_parse)}}
            _CFG["distractors"] = {"targets": str(targets)}
            _distractor_cache.clear()

            check("distractor_files_for: 방해 문서 1개 찾음", distractor_files_for("dsX") == {"dsX__a.pdf"})
            check("distractor_unique_ids: 유일 문항 1개", distractor_unique_ids("dsX") == {"Q1"})

            mirror = dd / "mirror"
            mirror.mkdir()
            (mirror / "qa.json").write_text(json.dumps({"docs": {}}), encoding="utf-8")
            merged = mirror_distractor_docs("dsX", mirror)
            check("mirror_distractor_docs: 방해 문서 1건 병합", merged == ["dsX__a.pdf"])
            check("mirror_distractor_docs: 엔진 파일 복사됨", (mirror / "engineA" / "dsX__a.pdf.json").exists())
            qa_after = json.loads((mirror / "qa.json").read_text(encoding="utf-8"))
            check("mirror_distractor_docs: qa.json에 문서 병합됨", "dsX__a.pdf" in qa_after["docs"])
            check("mirror_distractor_docs: runs.jsonl 1줄 추가", len((mirror / "runs.jsonl").read_text(encoding="utf-8").splitlines()) == 1)
            merged2 = mirror_distractor_docs("dsX", mirror)
            check("mirror_distractor_docs: 멱등(마커 재사용)", merged2 == merged)
            check(
                "mirror_distractor_docs: 재호출해도 runs.jsonl 중복 안 됨",
                len((mirror / "runs.jsonl").read_text(encoding="utf-8").splitlines()) == 1,
            )

            post0 = {"id": "baseline"}
            fake_store = Path("Z:/store")
            check("p1_dir: distractors on/off 경로 다름", p1_dir(fake_store, post0, "dsX", False) != p1_dir(fake_store, post0, "dsX", True))
            base_combo = {"chunker": "structure", "embed": "x", "chunk_size": None, "summary": "lead"}
            _, skey_off = s_dir(fake_store, post0, "dsX", base_combo, False)
            _, skey_on = s_dir(fake_store, post0, "dsX", base_combo, True)
            check("s_dir: distractors on/off 열쇠 다름", skey_off != skey_on)

            # D6 — VLM_MODEL·EMBED_MODEL이 다르면 P1·S 열쇠도 달라야(PC의 OpenRouter 결과를 서버 모델 결과로 조용히 재사용 안 함)
            with S.isolated(VLM_MODEL="openrouter/qwen-vl-a"):  # S7e2 — 시험 설정(끝나면 되돌림)
                p1_a = p1_dir(fake_store, post0, "dsX", False)
                S.put(VLM_MODEL="internal/qwen-vl-b")
                p1_b = p1_dir(fake_store, post0, "dsX", False)
                check("p1_dir: VLM_MODEL 다르면 P1 경로 다름", p1_a != p1_b)

                S.put(EMBED_MODEL="openrouter/qwen3-embed-a")
                _, s_a = s_dir(fake_store, post0, "dsX", base_combo, False)
                S.put(EMBED_MODEL="internal/qwen3-embed-b")
                _, s_b = s_dir(fake_store, post0, "dsX", base_combo, False)
                check("s_dir: EMBED_MODEL 다르면 S 열쇠 다름", s_a != s_b)
    finally:
        _CFG["reuse_bundles"], _CFG["distractors"] = saved_rb, saved_dist
        _distractor_cache.clear()

    # pool(V11 백로그, 2026-10-04) — 이름 충돌 접두·pool_fp 변화·oldver_confusion(distractor_confusion과 같은 규칙)
    with tempfile.TemporaryDirectory() as td5:
        pstore = Path(td5) / "store"
        post_p = {"id": "all", "env": {}}
        for ds, docs in (("dsA", ["shared.pdf", "a_only.pdf"]), ("dsB", ["shared.pdf", "b_only.pdf"])):
            rep = p1_dir(pstore, post_p, ds) / "_rep"
            rep.mkdir(parents=True, exist_ok=True)
            (rep / "index.json").write_text(
                json.dumps({"stack": None, "docs": [{"doc": d, "format": ".pdf_text"} for d in docs]}), encoding="utf-8"
            )
            for d in docs:
                (rep / f"{d}.json").write_text(json.dumps({"text": f"{ds}:{d}", "rep": {"engine": "x"}}), encoding="utf-8")
        pool_fixture = {"datasets": ["dsA", "dsB"]}
        present, missing, rename_map = mirror_pool(pstore, {"reuse_bundles": {}}, post_p, pool_fixture, pstore / "_mirror_test")
        check("mirror_pool: 멤버 둘 다 있음", present == ["dsA", "dsB"] and missing == [])
        check(
            "mirror_pool: 겹치는 파일은 두 쪽 다 <데이터셋>__ 접두",
            rename_map[("dsA", "shared.pdf")] == "dsA__shared.pdf" and rename_map[("dsB", "shared.pdf")] == "dsB__shared.pdf",
        )
        check("mirror_pool: 안 겹치는 파일은 그대로", rename_map[("dsA", "a_only.pdf")] == "a_only.pdf")
        merged_idx = json.loads((pstore / "_mirror_test" / "_rep" / "index.json").read_text(encoding="utf-8"))
        check("mirror_pool: 합친 문서 수 = 4", len(merged_idx["docs"]) == 4)
        check(
            "mirror_pool: 접두 파일이 실제로 복사됨",
            (pstore / "_mirror_test" / "_rep" / "dsA__shared.pdf.json").exists()
            and (pstore / "_mirror_test" / "_rep" / "dsB__shared.pdf.json").exists(),
        )

        pool_json_path = Path(td5) / "pool.json"
        pool_json_path.write_text(json.dumps(pool_fixture, ensure_ascii=False), encoding="utf-8")
        fp1 = pool_fp(pool_json_path, post_p, ["dsA", "dsB"])
        check("pool_fp: 결정적(같은 입력 같은 지문)", fp1 == pool_fp(pool_json_path, post_p, ["dsA", "dsB"]))
        pool_json_path.write_text(json.dumps({"datasets": ["dsA", "dsB", "dsC"]}, ensure_ascii=False), encoding="utf-8")
        check("pool_fp: pool.json 내용이 바뀌면 지문도 바뀜", fp1 != pool_fp(pool_json_path, post_p, ["dsA", "dsB", "dsC"]))

    ev1 = [{"file_name": "old.pdf"}, {"file_name": "gold.pdf"}, {"file_name": "other.pdf"}]
    rank1, conf1 = _rank_confusion(ev1, {"old.pdf"}, gold_rank=2)
    check("_rank_confusion: 구판이 정답보다 먼저면 오인", rank1 == 1 and conf1 is True)
    ev2 = [{"file_name": "gold.pdf"}] + [{"file_name": f"n{i}.pdf"} for i in range(9)] + [{"file_name": "old.pdf"}]
    rank2, conf2 = _rank_confusion(ev2, {"old.pdf"}, gold_rank=1)
    check("_rank_confusion: 정답보다 늦고 top10 밖이면 오인 아님", rank2 == 11 and conf2 is False)
    ev3 = [{"file_name": "gold.pdf"}] + [{"file_name": f"n{i}.pdf"} for i in range(8)] + [{"file_name": "old.pdf"}]
    rank3, conf3 = _rank_confusion(ev3, {"old.pdf"}, gold_rank=1)
    check("_rank_confusion: 정답보다 늦어도 top10 안이면 오인", rank3 == 10 and conf3 is True)

    # BR42 — pool_distractor_files: v1+v2만 모으고 다른 데이터셋은 제외(measure.py의 distractors-v2 풀 행이
    # distractor_files_for(DISTRACTOR_V2_DS)로 늘 빈 집합을 받던 결함의 대체 lookup)
    rmap_fixture = {(DISTRACTOR_DS, "a.pdf"): "a.pdf", (DISTRACTOR_V2_DS, "b.pdf"): "b.pdf", ("dsX", "c.pdf"): "c.pdf"}
    check("pool_distractor_files: v1+v2 합집합, 다른 데이터셋 제외", pool_distractor_files(rmap_fixture) == {"a.pdf", "b.pdf"})
    check("pool_distractor_files: rename_map 없으면 빈 집합", pool_distractor_files(None) == set())

    # W20 — must_not 위반(실제 synth-confuse spec.json, 읽기만)
    with tempfile.TemporaryDirectory() as td4:
        rep_dir = Path(td4)
        (rep_dir / "contract_htk_2026.pdf.json").write_text(json.dumps({"text": "본사 계약 금액 3,360,000 USD"}), encoding="utf-8")
        (rep_dir / "holden_email_2025.eml.json").write_text(json.dumps({"text": "2025-09-10 첫 배치"}), encoding="utf-8")
        viol = _must_not_violations("synth-confuse", rep_dir)
        if (MM.VALID / "synth-confuse" / "spec.json").exists():  # 10-15 — 실제 평가셋(valid_env)은 PC 전용, 이미지엔 없음
            check("_must_not_violations: 금지 값 있는 문서 잡음", viol.get("contract_htk_2026.pdf") == ["3,360,000"])
        check("_must_not_violations: 금지 값 없는 문서는 빈 채", "holden_email_2025.eml" not in viol)
    check("_must_not_violations: spec.json 없는 데이터셋은 빈 dict", _must_not_violations("ds-없음", Path(td)) == {})

    # qa_fp — 결정적·데이터셋마다 다름(스코어링 지문, 코디네이터 2026-10-04)
    check("qa_fp: 결정적(같은 호출 같은 값)", qa_fp("synth-images") == qa_fp("synth-images"))
    if (MM.VALID / "synth-images" / "qa.json").exists():  # 10-15 — 평가셋 없으면(이미지) 둘 다 "noqa"라 같음
        check("qa_fp: 데이터셋 다르면 다른 지문", qa_fp("synth-images") != qa_fp("synth-plant"))

    with tempfile.TemporaryDirectory() as td2:
        run_dir = Path(td2)
        ds = next(
            d for d, g in MM.read_split(config).items() if g == "dev"
        )  # 실제 config의 dev 세트 하나(그래야 report의 group 필터에 걸림)
        (run_dir / "results.json").write_text(
            json.dumps(
                [
                    {
                        "combo": "baseline",
                        "dataset": ds,
                        "group": "dev",
                        "retrieval": {
                            "r5": 0.6,
                            "r10": 0.8,
                            "mean_ms": 400,
                            "rows": [{"id": "q1", "hit5": True, "hit10": True}, {"id": "q2", "hit5": False, "hit10": True}],
                        },
                    },
                    {
                        "combo": "chunker=fixed512",
                        "dataset": ds,
                        "group": "dev",
                        "retrieval": {
                            "r5": 0.8,
                            "r10": 0.9,
                            "mean_ms": 350,
                            "rows": [{"id": "q1", "hit5": True, "hit10": True}, {"id": "q2", "hit5": True, "hit10": True}],
                        },
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run_dir / "layers_used.json").write_text(json.dumps([{"layer": "s", "dir": "x", "stale": False}]), encoding="utf-8")

        class A_:
            pass

        a2 = A_()
        a2.run_dir = str(run_dir)
        cmd_report(config, a2)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        row = next(r for r in summary["rows"] if r["combo"] == "chunker=fixed512")
        check("report: chunker=fixed512 dev R@5 델타 = +0.2", row["dev_delta"] is not None and abs(row["dev_delta"] - 0.2) < 1e-9)
        check("report: 낡은 층 없음 표시", summary["stale_layers"] == [])

    # 비용 관문(2026-10) — 가짜 LLM(네트워크 0)·예산 상한·k 재사용(검색 1회)·--context-only(LLM 0)
    # GA(2026-10-06): llm.chat()의 실호출은 common/adk.py complete()를 거침(urllib 직접 호출 아님) — 네트워크 0 확인은
    # 그 경계에서(L._g_urlopen은 더 없음, chat() 안에서 adk 모듈을 매번 import해 부르므로 common.ai.adk.complete를 바꿔도 먹음).
    from common.ai import adk as ADK
    from common.ai import llm as L

    _orig_complete = ADK.complete
    ADK.complete = lambda *a_, **k_: (_ for _ in ()).throw(AssertionError("LLM_FAKE인데 네트워크 호출"))
    try:
        with S.isolated(LLM_FAKE="1"):  # S7e2 — 시험 설정(끝나면 되돌림)
            before = dict(L.usage())
            txt = L.chat([{"role": "user", "content": "비용 관문 셀프테스트 질문"}], max_tokens=10)
            check("LLM_FAKE: 네트워크 없이 모의 응답([FAKE] 꼬리)", txt.endswith("[FAKE]"))
            check(
                "LLM_FAKE: usage() fake_calls·prompt_chars 집계",
                L.usage()["fake_calls"] > before.get("fake_calls", 0) and L.usage()["prompt_chars"] > before.get("prompt_chars", 0),
            )
    finally:
        ADK.complete = _orig_complete

    # 10-05 회귀 — --pool이 먼저 분기돼도 --estimate·--context-only면 LLM_FAKE가 켜져 있어야 함(유료 호출 0)
    _seen, _orig_pool = {}, M.cmd_answer_pool
    M.cmd_answer_pool = lambda cfg, aa: _seen.setdefault("fake", MM.own("LLM_FAKE"))
    try:
        for flag in ("estimate", "context_only"):
            _seen.clear()
            with S.isolated(LLM_FAKE=None):  # S7e2 — 시험 설정(cmd_answer의 put까지 끝나면 되돌림)
                cmd_answer(config, argparse.Namespace(pool="p.json", estimate=(flag == "estimate"), context_only=(flag == "context_only")))
            check(f"비용 관문: --pool + --{flag}도 LLM_FAKE 강제", _seen.get("fake") == "1")
    finally:
        M.cmd_answer_pool = _orig_pool

    # 예산 — 외부(유료) 주소 + 단가 지정 + 아주 작은 상한 → 공유 장부 선차감에서 거부(네트워크 전에). 내부망 LLM은 무료라 예산 대상 아님.
    _budget = S.isolated(
        LLM_BASE_URL="https://openrouter.ai/api/v1",
        LLM_MODEL="x-selftest-budget",
        LLM_BUDGET_USD="0.0000001",  # S7e2 — 시험 설정
        LLM_PRICE_IN="1",
        LLM_PRICE_OUT="1",
        LLM_SPEND_FILE=str(Path(tempfile.mkdtemp()) / "spend.txt"),
    )
    _orig_ok, _orig_complete2 = L._synthetic_ok, ADK.complete
    L._synthetic_ok = lambda: True
    ADK.complete = lambda *aa, **kk: (_ for _ in ()).throw(AssertionError("예산 거부 전에 네트워크를 부름"))
    try:
        with _budget:
            L.chat([{"role": "user", "content": f"예산 상한 테스트 {time.time()}"}], max_tokens=5, allow_external=True)
        check("LLM_BUDGET_USD: 한도 넘으면 호출 전에 거부(공유 장부 선차감)", False)
    except L.LLMUnavailable as e:
        check("LLM_BUDGET_USD: 한도 넘으면 호출 전에 거부(공유 장부 선차감)", "LLM_BUDGET_USD" in str(e))
    finally:
        L._synthetic_ok, ADK.complete = _orig_ok, _orig_complete2

    with tempfile.TemporaryDirectory() as td6:  # 작은 BM25 묶음(임베딩 없음) — k 재사용·--context-only 전용
        import numpy as _np

        from mcp_server.services.search import server_state as _M  # S5 — _STATE는 services/search/server_state.py
        from mcp_server.services.search.retriever import Retriever as _RT

        bdir = Path(td6)
        sha = "e" * 64
        (bdir / "meta.json").write_text(json.dumps({"dim": 0}), encoding="utf-8")
        (bdir / "docs.jsonl").write_text(
            json.dumps({"file_path": "p.txt", "file_name": "p.txt", "file_sha256": sha, "doc_format": ".txt"}) + "\n", encoding="utf-8"
        )
        cks = [
            {
                "doc": 0,
                "seq": i,
                "page": 1,
                "line_start": i + 1,
                "line_end": i + 1,
                "chunk_text": f"조항 {i}: 단가는 {100 + i} USD",
                "n_terms": 5,
                "bbox": None,
                "section": None,
            }
            for i in range(12)
        ]
        (bdir / "chunks.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cks) + "\n", encoding="utf-8")
        _np.save(bdir / "vectors.npy", _np.zeros((12, 0), dtype="float32"))
        _rr = S.isolated(SEARCH_RERANK=None)  # 꺼짐(기본) — k 재사용 동등성은 이 경우만 보장(S7e2 시험 설정 — 아래 finally에서 되돌림)
        _rr.__enter__()
        R6 = _RT(bdir)
        hits_max, _ = R6.search("단가는 얼마?", 10, methods=["bm25"])
        hits_direct, _ = R6.search("단가는 얼마?", 4, methods=["bm25"])
        check(
            "k 재사용: max-k(10) 슬라이스[:4] = 직접 k=4 검색(rerank off)",
            [h["chunk_key"] for h in hits_max[:4]] == [h["chunk_key"] for h in hits_direct],
        )

        _M._STATE.clear()
        _M._STATE["R"] = R6
        S.put(MCP_BUNDLE=str(bdir))  # S7e2 — 시험 설정(_rr이 되돌림)
        try:
            before2 = dict(L.usage())
            item = {"id": "q1", "question": "단가는 얼마?", "score_fn": lambda t: "100" in t, "gold_docs": set()}
            res = _answer_eval(None, ["bm25"], [1, 4], items_override=[item], score_mode=None, context_only=True)
            check("--context-only: LLM 호출 0건", L.usage()["calls"] == before2["calls"])
            check("--context-only: k별 결과(1·4) 반환", set(res.keys()) == {"1", "4"})
        finally:
            _M._STATE.clear()
            _rr.__exit__(None, None, None)
        del R6, hits_max, hits_direct, res  # vectors.npy는 mmap(local.py) — 참조를 끊어야 Windows가 임시 폴더를 지울 수 있음
        import gc as _gc

        _gc.collect()

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 `selftest` 하위 명령(main()의 `cmd_selftest(load_config(a.config), a)`)
    a = argparse.Namespace(config=str(CONFIG_PATH), cmd="selftest")  # 옛 main()의 ap.parse_args() 결과 꼴
    if not a.cmd.startswith("_"):  # 옛 main()의 실행 전체 지출 장부 지정(위 줄들 — main() 안에 그대로 남아 있음)
        if MM.own("LLM_SPEND_FILE") is None:
            S.put(LLM_SPEND_FILE=str(Path(tempfile.mkdtemp(prefix="llm_spend_")) / "spend.txt"))
    config = load_config(a.config)
    cmd_selftest(config, a)
