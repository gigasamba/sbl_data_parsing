"""pipeline.eval.stack_report 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.stack_report --selftest`."""

import json
from pathlib import Path

import pipeline.eval.stack_report as M
from pipeline.eval.stack_report import (
    POOL_V2_DS,
    TABS,
    availability_note,
    build_context,
    build_data_quality_warnings,
    build_html,
    build_onoff_table,
    build_parsing_tab,
    build_ref_attach_table,
    compute_ranking,
    dataset_group_map,
    dataset_valid,
    determine_operating_k,
    discriminating_datasets,
    flatten_answers,
    flatten_answers_at_k,
    fmt_abs,
    fmt_delta,
    fmt_ms,
    human_label,
    index_answers_raw,
    load_eval_set,
    load_stack_cfg,
    mcnemar_p,
    paired_diff_ci,
    pooled_mean,
    pooled_rate,
    rank_confusion_split,
    resolve_split_label,
    saturation_by_dataset,
    saturation_provisional,
)


# ───────────────────────── selftest(오프라인, 가짜 파일) ─────────────────────────
def cmd_selftest():
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    check("mcnemar_p: 불일치 0이면 None", mcnemar_p([(True, True), (False, False)]) is None)
    check("mcnemar_p: 완전히 갈리면 p 작음", mcnemar_p([(True, False)] * 10) < 0.01)
    lo, hi = paired_diff_ci([(True, False)] * 10 + [(False, True)] * 1)
    check("paired_diff_ci: 범위 반환", lo is not None and hi is not None and lo <= hi)

    # K1 — 짝 유지 버그 재발 방지: A·B가 섞여 있어도(값 자체는 다양) 모든 문항에서 A==B(불일치 0)면 CI는 반드시 [0,0].
    # (예전 버그: 리샘플마다 A·B를 따로 뽑아 인덱스가 어긋나 — 이 섞인 입력에서 가짜 비0 CI가 나왔었음, synth-confuse 사례.)
    pairs_mixed_concordant = [(True, True), (False, False), (True, True), (False, False), (True, True)]
    check("paired_diff_ci(K1): 섞여 있어도 전부 일치(concordant)면 CI=[0,0]", paired_diff_ci(pairs_mixed_concordant) == (0.0, 0.0))
    # 문항 1개, off=False→on=True — 리샘플마다 그 문항만 뽑히므로 차는 항상 +1(부호·범위 확인).
    check("paired_diff_ci(K1): 단일 문항 off=False→on=True면 CI=[+1,+1]", paired_diff_ci([(False, True)]) == (1.0, 1.0))
    check("fmt_abs: 부호 없음", fmt_abs(0.5) == "0.500" and "+" not in fmt_abs(0.5))
    check("fmt_delta: 부호 있음", fmt_delta(0.5).startswith("+") and fmt_delta(-0.5).startswith("-"))

    # L3-2 — rank_confusion_split: 엄격(strict, 모든 정답보다 위)/느슨(loose, top10 참고용) 분리.
    rows_oc = [
        {"oldver_rank": 1, "gold_rank": 3},  # 엄격 히트(1<3)·느슨 히트(<=10)
        {"oldver_rank": 7, "gold_rank": 3},  # 엄격 아님(7>3)·느슨 히트
        {"oldver_rank": None, "gold_rank": 3},  # 후보 문서를 못 찾음 — 둘 다 아님
        {"oldver_rank": 12, "gold_rank": 2},  # 둘 다 아님(12>10)
        {"gold_rank": 3},  # oldver_rank 필드 자체가 없음 — n에서 제외
    ]
    strict_oc, loose_oc, n_oc = rank_confusion_split(rows_oc, "oldver_rank")
    check("rank_confusion_split: rank_key 없는 행은 n에서 제외(4)", n_oc == 4)
    check("rank_confusion_split: 엄격 1/4=0.25", abs(strict_oc - 0.25) < 1e-9)
    check("rank_confusion_split: 느슨 2/4=0.5(≥엄격)", abs(loose_oc - 0.5) < 1e-9 and loose_oc >= strict_oc)

    # J1 — pooled_mean: 불리언 비율이 아니라 값의 평균(합/n), 무효 세트 제외는 pooled_rate와 같은 규칙.
    idx_mrr = {
        ("c1", "dsA"): {"valid": True, "rows": [{"id": "q1", "v": 1.0}, {"id": "q2", "v": 0.5}]},
        ("c1", "dsB"): {"valid": False, "rows": [{"id": "q3", "v": 0.0}]},
    }
    grp_mrr = {"dsA": "holdout", "dsB": "holdout"}
    check("pooled_mean: 무효 세트 제외, (1.0+0.5)/2=0.75", abs(pooled_mean(idx_mrr, "c1", grp_mrr, "holdout", "v", idx_mrr) - 0.75) < 1e-9)

    # J1 — compute_ranking: 답변 데이터가 없고 pool_ctx가 있으면 별도 색인 R@5가 아니라 pool R@1(+MRR 타이브레이크)로 순위.
    idx_retr_j1 = {("c1", "dsJ"): {"r5": 1.0, "valid": True}, ("c2", "dsJ"): {"r5": 1.0, "valid": True}}  # 둘 다 R@5 포화(동률)
    idx_pool_j1 = {
        ("c1", "dsJ"): {"rows": [{"id": "q1", "hit1": True, "inv_rank": 1.0}, {"id": "q2", "hit1": False, "inv_rank": 0.5}]},
        ("c2", "dsJ"): {"rows": [{"id": "q1", "hit1": False, "inv_rank": 0.33}, {"id": "q2", "hit1": False, "inv_rank": 0.25}]},
    }
    pool_ctx_j1 = {"idx_retr_pool": idx_retr_j1, "idx_hit1": idx_pool_j1}
    grp_j1 = {"dsJ": "holdout"}
    m_j1, _, kept_j1 = compute_ranking(["c1", "c2"], idx_retr_j1, {}, grp_j1, pool_ctx=pool_ctx_j1)
    check("J1: 답변 없음+pool_ctx면 metric=pool_r1(별도 R@5 포화라도 안 씀)", m_j1 == "pool_r1")
    check("J1: pool R@1 기준 1위=c1(1/2=0.5 > c2의 0/2=0.0)", kept_j1[0]["combo"] == "c1" and abs(kept_j1[0]["holdout"] - 0.5) < 1e-9)
    m_noPool_j1, _, _ = compute_ranking(["c1", "c2"], idx_retr_j1, {}, grp_j1)  # pool_ctx 없으면 기존처럼 retrieval_r5
    check("J1: pool_ctx 없으면 여전히 retrieval_r5(하위호환)", m_noPool_j1 == "retrieval_r5")

    # J2 — build_onoff_table: 두 실행 폴더의 공통 데이터셋만, hit1 짝으로 McNemar p·CI를 계산.
    with tempfile.TemporaryDirectory() as td_onoff:
        dir_off, dir_on = Path(td_onoff) / "off", Path(td_onoff) / "on"
        dir_off.mkdir()
        dir_on.mkdir()
        off_rows = [
            {
                "combo": "baseline",
                "dataset": "dsOnOff",
                "retrieval": {"recall_at": {"1": 0.0}, "mrr": 0.3, "rows": [{"id": "q1", "gold_rank": 3}, {"id": "q2", "gold_rank": 2}]},
            },
            # K1 재발 방지(synth-confuse 사례) — 두 문항 다 off==on(불일치 0)이지만 문항끼리 값은 다름(q3 적중·q4 비적중).
            {
                "combo": "baseline",
                "dataset": "dsSame",
                "retrieval": {"recall_at": {"1": 0.5}, "mrr": 0.6, "rows": [{"id": "q3", "gold_rank": 1}, {"id": "q4", "gold_rank": 3}]},
            },
        ]
        on_rows = [
            {
                "combo": "baseline",
                "dataset": "dsOnOff",
                "retrieval": {"recall_at": {"1": 1.0}, "mrr": 1.0, "rows": [{"id": "q1", "gold_rank": 1}, {"id": "q2", "gold_rank": 1}]},
            },
            {
                "combo": "baseline",
                "dataset": "dsSame",
                "retrieval": {"recall_at": {"1": 0.5}, "mrr": 0.6, "rows": [{"id": "q3", "gold_rank": 1}, {"id": "q4", "gold_rank": 2}]},
            },
        ]
        (dir_off / "results.json").write_text(json.dumps(off_rows, ensure_ascii=False), encoding="utf-8")
        (dir_on / "results.json").write_text(json.dumps(on_rows, ensure_ascii=False), encoding="utf-8")
        grp_onoff = {"dsOnOff": "holdout", "dsSame": "dev"}
        rows_onoff = build_onoff_table(dir_off, dir_on, "baseline", grp_onoff)
        r_onoff = next(r for r in rows_onoff if r["dataset"] == "dsOnOff")
        r_same = next(r for r in rows_onoff if r["dataset"] == "dsSame")
        check("J2: 공통 데이터셋 2개·dsOnOff n=2", len(rows_onoff) == 2 and r_onoff["n"] == 2)
        check(
            "J2: R@1 off=0.0→on=1.0, MRR off=0.3→on=1.0",
            r_onoff["r1_off"] == 0.0 and r_onoff["r1_on"] == 1.0 and r_onoff["mrr_off"] == 0.3 and r_onoff["mrr_on"] == 1.0,
        )
        check(
            "J2: 두 문항 모두 off→on으로 갈림(불일치 2, n=2라 p=0.5 — 완전히 한쪽으로만 쏠림)",
            r_onoff["mcnemar_p"] is not None and abs(r_onoff["mcnemar_p"] - 0.5) < 1e-9,
        )
        check("J2: holdout 라벨이 그대로 전달됨", r_onoff["group"] == "holdout")
        # K1 — dsSame: q3는 off·on 둘 다 hit1(gold_rank==1), q4는 둘 다 비적중(hit1=False) → 불일치 0, p=None, CI=[0,0].
        check("K1: dsSame은 불일치 0(n_discordant=0)", r_same["n_discordant"] == 0)
        check(
            "K1: dsSame McNemar p=None(불일치 0이라 정의상 계산 불가) + CI=[0,0]",
            r_same["mcnemar_p"] is None and r_same["ci"] == (0.0, 0.0),
        )

    # K3 — resolve_split_label: grp_map에 없는(혼합) 데이터셋은 evidence[0].dataset을 grp_map으로 매핑해 dev/holdout 문항 수를 센다.
    with tempfile.TemporaryDirectory() as td_mix:
        mix_ds_dir = Path(td_mix) / "valid_env" / "unstructured" / "ds_mix"
        mix_ds_dir.mkdir(parents=True)
        mix_qa = {
            "items": [
                {"id": "m1", "evidence": [{"dataset": "src_dev"}]},
                {"id": "m2", "evidence": [{"dataset": "src_dev"}]},
                {"id": "m3", "evidence": [{"dataset": "src_hold"}]},
            ]
        }
        (mix_ds_dir / "qa.json").write_text(json.dumps(mix_qa, ensure_ascii=False), encoding="utf-8")
        grp_mix = {"src_dev": "dev", "src_hold": "holdout"}
        old_valid = M.VALID
        M.VALID = Path(td_mix) / "valid_env" / "unstructured"
        try:
            check("K3: 단일 세트는 grp_map 값 그대로", resolve_split_label("src_dev", grp_mix) == "dev")
            check(
                "K3: 혼합 세트는 '혼합(dev N · holdout M)' 형식(여기선 dev 2 · holdout 1)",
                resolve_split_label("ds_mix", grp_mix) == "혼합(dev 2 · holdout 1)",
            )
            check("K3: qa.json도 없는 알 수 없는 세트는 '-'", resolve_split_label("ds_unknown", grp_mix) == "-")
        finally:
            M.VALID = old_valid

    # I1 — 포화는 결정 지표(정답률)로 판정 — R@5는 포화(모두 1.0)인데 정답률은 변별(0.5 vs 0.9)이면 use_accuracy=True에서 '포화 아님'.
    idx_i1 = {
        ("c1", "dsI1"): {"r5": 1.0, "recall_at": {"1": 0.9}, "mrr": 0.95},
        ("c2", "dsI1"): {"r5": 1.0, "recall_at": {"1": 0.8}, "mrr": 0.85},
    }
    flat_i1 = {
        ("c1", "dsI1"): {"rows": [{"id": f"q{i}", "correct": i < 9} for i in range(10)]},  # 0.9
        ("c2", "dsI1"): {"rows": [{"id": f"q{i}", "correct": i < 5} for i in range(10)]},
    }  # 0.5
    grp_i1 = {"dsI1": "holdout"}
    sat_r5 = saturation_by_dataset(idx_i1, ["dsI1"])
    sat_acc = saturation_by_dataset(idx_i1, ["dsI1"], flat_ans=flat_i1, grp_map=grp_i1, combos=["c1", "c2"], use_accuracy=True)
    check("I1: R@5 기준은 포화(모두 1.0)", sat_r5["dsI1"]["saturated"] is True and sat_r5["dsI1"]["metric"] == "retrieval_r5")
    check(
        "I1: 정답률 기준은 변별 있음(0.5~0.9, 포화 아님) + R@1 범위 포함",
        sat_acc["dsI1"]["saturated"] is False
        and sat_acc["dsI1"]["metric"] == "answer_accuracy"
        and sat_acc["dsI1"]["r1_min"] == 0.8
        and sat_acc["dsI1"]["r1_max"] == 0.9,
    )

    # I2 — 동률(holdout 비율·n 정확히 같음)이면 더 단순한 조합(baseline)을 1위로, '동률' 표시.
    rows_i2 = [{"id": f"q{i}", "correct": i < 9} for i in range(10)]  # 9/10 — 두 콤보 모두 같은 값(완전 동률)
    flat_i2 = {("structure_table", "dsI2"): {"rows": rows_i2}, ("baseline", "dsI2"): {"rows": rows_i2}}
    grp_i2 = {"dsI2": "holdout"}
    _, _, kept_i2 = compute_ranking(["structure_table", "baseline"], {}, flat_i2, grp_i2)
    check("I2: 동률이면 baseline이 1위(더 단순한 쪽 우선)", kept_i2[0]["combo"] == "baseline")
    check("I2: 1위에 동률 표시 + 동률 상대 기록", kept_i2[0]["tie"] is True and "structure_table" in kept_i2[0]["tied_combos"])

    # I3 — 방해 문서 실행이 있어도 포화가 '해소'되지 않으면(relief != '해소') 잠정 꼬리표를 유지한다.
    sat_i3 = {"dsA": {"saturated": True}, "dsB": {"saturated": True}, "dsC": {"saturated": False}}
    check(
        "I3: 방해 문서 실행은 있지만 전부 '유지'면 여전히 잠정",
        saturation_provisional(sat_i3, [{"relief": "유지"}, {"relief": "-"}]) is True,
    )
    check("I3: 한 세트라도 '해소'면 잠정 해제", saturation_provisional(sat_i3, [{"relief": "유지"}, {"relief": "해소"}]) is False)
    check("I3: 방해 문서 실행 자체가 없으면(None) 잠정 유지", saturation_provisional(sat_i3, None) is True)
    check("fmt_ms: 정수", fmt_ms(991.4989628315094) == "991")
    check("human_label: baseline", human_label("baseline") == "기준 조합")
    check("human_label: post=none", "끔" in human_label("post=none"))
    check("availability_note: 미실행", availability_note(0) == "미실행")
    check("availability_note: 무효", availability_note(10, valid=False) == "무효(정답 문서 포함률<95%)")
    check("availability_note: 데이터 부족", availability_note(2) is not None and "부족" in availability_note(2))

    # G1 — 손으로 다시 계산해 pooled_rate가 맞는지 확인(무효 세트 제외 + 문항 단위 풀링, 세트 평균 아님).
    idx_syn = {
        ("c1", "dsA"): {"valid": True, "rows": [{"id": "q1", "hit5": True}, {"id": "q2", "hit5": False}]},  # dev: 1/2
        ("c1", "dsB"): {
            "valid": True,
            "rows": [{"id": "q3", "hit5": True}, {"id": "q4", "hit5": True}, {"id": "q5", "hit5": False}],
        },  # holdout 유효: 2/3
        ("c1", "dsC"): {"valid": False, "rows": [{"id": "q6", "hit5": True}]},  # holdout 무효 — 제외돼야 함
    }
    grp_syn = {"dsA": "dev", "dsB": "holdout", "dsC": "holdout"}
    rate, n = pooled_rate(idx_syn, "c1", grp_syn, "holdout", "hit5", idx_syn)
    check("pooled_rate: 무효 세트(dsC) 제외하고 dsB만 풀링 — n=3, rate=2/3(손계산)", n == 3 and abs(rate - 2 / 3) < 1e-9)
    rate_dev, n_dev = pooled_rate(idx_syn, "c1", grp_syn, "dev", "hit5", idx_syn)
    check("pooled_rate: dev는 dsA만 — n=2, rate=1/2", n_dev == 2 and abs(rate_dev - 0.5) < 1e-9)
    check("dataset_valid: dsC는 c1에 대해 False", dataset_valid(idx_syn, "c1", "dsC") is False)

    # G3 — 조합 80% 이상이 1.0이면 변별력 있는 순위에서 제외.
    idx_sat = {
        ("c1", "dsSat"): {"r5": 1.0},
        ("c2", "dsSat"): {"r5": 1.0},
        ("c3", "dsSat"): {"r5": 1.0},
        ("c4", "dsSat"): {"r5": 0.8},
        ("c1", "dsFull"): {"r5": 1.0},
        ("c2", "dsFull"): {"r5": 1.0},
        ("c3", "dsFull"): {"r5": 1.0},
        ("c4", "dsFull"): {"r5": 1.0},
        ("c1", "dsOk"): {"r5": 0.7},
        ("c2", "dsOk"): {"r5": 0.9},
    }
    keep = discriminating_datasets(idx_sat, ["dsSat", "dsFull", "dsOk"], ["c1", "c2", "c3", "c4"])
    check(
        "discriminating_datasets: dsSat(3/4=0.75<0.8) 포함, dsFull(4/4=1.0≥0.8) 제외, dsOk(변별력 있음) 포함",
        "dsSat" in keep and "dsFull" not in keep and "dsOk" in keep,
    )

    # G7 — 여러 답 실행 합치기 + --invalid-runs로 통째로 무효 처리.
    raw_valid = [{"combo": "c1", "dataset": "dsB", "k": 10, "answer": {"n": 1, "rows": [{"id": "q3", "correct": True}]}}]
    raw_invalid = [{"combo": "c1", "dataset": "dsB", "k": 10, "answer": {"n": 1, "rows": [{"id": "q3", "correct": False}]}}]
    merged = index_answers_raw(
        [{**r, "_run": "runA", "_invalid": False} for r in raw_valid] + [{**r, "_run": "runB", "_invalid": True} for r in raw_invalid]
    )
    check("index_answers_raw: 무효 실행이 유효 실행을 덮어쓰지 않음", merged[("c1", "dsB", 10)]["rows"][0]["correct"] is True)
    check(
        "flatten_answers: 무효 실행뿐이면 그 (combo,ds)는 아예 빠짐",
        flatten_answers(index_answers_raw([{**r, "_run": "runB", "_invalid": True} for r in raw_invalid])) == {},
    )

    # 운영 k(§1) — baseline 조합의 holdout 정답률이 가장 높은 k를 고른다(손으로 다시 계산).
    idx_ans_mk = index_answers_raw(
        [
            {"combo": "baseline", "dataset": "dsH", "k": 5, "answer": {"rows": [{"id": f"q{i}", "correct": i < 3} for i in range(10)]}},
            {"combo": "baseline", "dataset": "dsH", "k": 10, "answer": {"rows": [{"id": f"q{i}", "correct": i < 5} for i in range(10)]}},
            {"combo": "baseline", "dataset": "dsH", "k": 20, "answer": {"rows": [{"id": f"q{i}", "correct": i < 9} for i in range(10)]}},
        ]
    )
    grp_mk = {"dsH": "holdout"}
    idx_retr_mk = {}  # 검색 데이터 없어도(G1 valid 기본 True) pooled_rate가 동작해야 함
    check("flatten_answers_at_k: 정확히 그 k만(폴백 없음)", set(flatten_answers_at_k(idx_ans_mk, 10)) == {("baseline", "dsH")})
    check(
        "determine_operating_k: holdout 정답률 최고(k=20, 9/10=0.9) 선택",
        determine_operating_k(idx_ans_mk, grp_mk, idx_retr_mk, [5, 10, 20]) == 20,
    )

    # W20 — ref_hit·attach_hit pooled_rate(기존 pooled_rate 재사용, hit_key만 다름).
    flat_ref = {("c1", "dsR"): {"rows": [{"id": "r1", "ref_hit": True}, {"id": "r2", "ref_hit": False}, {"id": "r3", "attach_hit": None}]}}
    grp_ref = {"dsR": "holdout"}
    rows_ref = build_ref_attach_table(flat_ref, {}, grp_ref, ["c1"])
    check(
        "build_ref_attach_table: ref_hit만 있는 세트 — n=2, rate=1/2",
        len(rows_ref) == 1 and rows_ref[0]["ref_n"] == 2 and abs(rows_ref[0]["ref_rate"] - 0.5) < 1e-9 and rows_ref[0]["attach_n"] == 0,
    )

    # 데이터 품질 경고 — gold_doc_coverage<1 또는 valid=false인 세트만 뽑힌다.
    idx_dq = {
        ("baseline", "dsGood"): {"valid": True, "gold_doc_coverage": 1.0},
        ("baseline", "dsBad"): {"valid": False, "gold_doc_coverage": 0.8, "missing_gold_docs": ["m1.pdf", "m2.pdf"]},
        ("chunker=x", "dsBad"): {"valid": False, "gold_doc_coverage": 0.8},
    }  # baseline이 아닌 콤보는 대표에서 제외
    warn = build_data_quality_warnings(idx_dq)
    check(
        "build_data_quality_warnings: dsBad만 뽑히고(baseline 기준) dsGood은 빠짐, 중복 없음",
        len(warn) == 1 and warn[0]["dataset"] == "dsBad" and warn[0]["missing"] == ["m1.pdf", "m2.pdf"],
    )

    # W20 — 파싱 탭 금지 값 위반 집계(must_not_violations).
    doc_stats_mnv = [
        {"doc": "a.pdf", "format": ".pdf", "engine": "pymupdf", "fact_hits_proxy": 1.0, "must_not_violations": [], "ms": {}},
        {
            "doc": "b.pdf",
            "format": ".pdf",
            "engine": "pymupdf",
            "fact_hits_proxy": 0.5,
            "must_not_violations": [{"field": "amount", "value": "N/A"}],
            "ms": {},
        },
    ]
    fmt_rows_mnv, _ = build_parsing_tab(doc_stats_mnv, {}, {})
    check("build_parsing_tab: 금지 값 위반 1문서·1건 집계", fmt_rows_mnv[0]["mnv_docs"] == 1 and fmt_rows_mnv[0]["mnv_total"] == 1)

    # S9 — 옛 `global STACK_CFG_PATH` → `M.<이름>`(모듈 전역 대입)
    saved_cfg_path = M.STACK_CFG_PATH
    try:
        with tempfile.TemporaryDirectory() as td:
            retr_dir = Path(td) / "retr"
            ans_dir = Path(td) / "ans"
            retr_dir.mkdir()
            ans_dir.mkdir()
            grp_map = dataset_group_map(load_eval_set(), load_stack_cfg())
            if not {"dev", "holdout"} <= set(grp_map.values()):  # S6a — 설정이 PC 전용 validation/e2e/로 가 이미지에는 없음(S6b VS6a R-8 —
                M.STACK_CFG_PATH = (
                    Path(td) / "stack_matrix.json"
                )  # 계산된 묶음에 dev·holdout이 다 있는지로 판단): 가짜 dev·holdout 세트를 더함(PC는 실제 설정 그대로)
                M.STACK_CFG_PATH.write_text(json.dumps({"datasets": {"dev": ["ds_dev"], "holdout": ["ds_hold"]}}), encoding="utf-8")
                grp_map = dataset_group_map(load_eval_set(), load_stack_cfg())
            dev_ds = next((d for d, g in grp_map.items() if g == "dev"), None)
            hold_ds = next((d for d, g in grp_map.items() if g == "holdout"), None)
            check("selftest 전제: eval_set에 dev·holdout 세트가 있음", dev_ds is not None and hold_ds is not None)
            fake_results = []
            for ds in filter(None, [dev_ds, hold_ds]):
                fake_results.append(
                    {
                        "combo": "baseline",
                        "dataset": ds,
                        "group": grp_map[ds],
                        "retrieval": {
                            "r5": 0.6,
                            "r10": 0.8,
                            "mean_ms": 400,
                            "p90_ms": 500,
                            "gold_doc_coverage": 1.0,
                            "valid": True,
                            "rows": [
                                {"id": "q1", "hit5": True, "hit10": True, "ms": 100, "top_chunk_ids": []},
                                {"id": "q2", "hit5": False, "hit10": True, "ms": 200, "top_chunk_ids": []},
                            ],
                        },
                    }
                )
                fake_results.append(
                    {
                        "combo": "chunker=fixed512",
                        "dataset": ds,
                        "group": grp_map[ds],
                        "retrieval": {
                            "r5": 0.8,
                            "r10": 0.9,
                            "mean_ms": 350,
                            "p90_ms": 450,
                            "gold_doc_coverage": 1.0,
                            "valid": True,
                            "rows": [
                                {"id": "q1", "hit5": True, "hit10": True, "ms": 90, "top_chunk_ids": []},
                                {"id": "q2", "hit5": True, "hit10": True, "ms": 190, "top_chunk_ids": []},
                            ],
                        },
                    }
                )
            # 데이터 품질 경고(§4) — grp_map 밖의 고립된 가짜 세트라 다른 검증에 영향 없음.
            fake_results.append(
                {
                    "combo": "baseline",
                    "dataset": "ds_bad_coverage",
                    "retrieval": {"r5": None, "valid": False, "gold_doc_coverage": 0.8, "missing_gold_docs": ["missing1.pdf"], "rows": []},
                }
            )
            (retr_dir / "results.json").write_text(json.dumps(fake_results, ensure_ascii=False), encoding="utf-8")
            (retr_dir / "run_meta.json").write_text(
                json.dumps(
                    [
                        {
                            "combo": "baseline",
                            "dataset": dev_ds,
                            "git_commit": "deadbeef",
                            "embed_model": "x",
                            "rerank_model": "off",
                            "dataset_fingerprint": "f",
                            "split": "dev",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (retr_dir / "layers_used.json").write_text(
                json.dumps([{"layer": "s", "dir": "x", "stale": False}], ensure_ascii=False), encoding="utf-8"
            )
            fake_answers = [
                {
                    "combo": "baseline",
                    "dataset": dev_ds,
                    "group": "dev",
                    "k": 10,
                    "status": "built",
                    "answer": {
                        "dataset": dev_ds,
                        "k": 10,
                        "n": 2,
                        "accuracy": 0.5,
                        "kw_in_context": 1.0,
                        "empty_rate": 0.0,
                        "errors": 0,
                        "p50_ms": 500,
                        "rows": [
                            {
                                "id": "q1",
                                "type": "t",
                                "negative": False,
                                "correct": True,
                                "kw_in_context": True,
                                "evidence_hit": True,
                                "empty_answer": False,
                                "retry": False,
                                "error": None,
                                "evidence": [],
                                "answer": "정답",
                                "ms": 500,
                                "tokens_in": 10,
                            },
                            {
                                "id": "q2",
                                "type": "t",
                                "negative": False,
                                "correct": False,
                                "kw_in_context": True,
                                "evidence_hit": True,
                                "empty_answer": False,
                                "retry": False,
                                "error": None,
                                "evidence": [],
                                "answer": "오답",
                                "ms": 500,
                                "tokens_in": 10,
                            },
                        ],
                    },
                }
            ]
            (ans_dir / "answers.json").write_text(json.dumps(fake_answers, ensure_ascii=False), encoding="utf-8")

            ctx = build_context(retr_dir, [ans_dir], invalid_run_names={"ans"})  # G7 — 이 fake 답 실행을 통째로 무효 처리
            check("build_context: 콤보 2개", len(ctx["combos"]) == 2)
            check("ranking: 답 실행이 --invalid-runs로 무효 처리돼 검색 전용으로 대체", ctx["ranking"]["metric"] == "retrieval_r5")
            check(
                "ranking: baseline보다 chunker=fixed512 holdout이 높거나 같음",
                ctx["ranking"]["kept"][0]["combo"] in ("chunker=fixed512", "baseline"),
            )
            check("ranking: holdout(n)이 채워짐(G4)", all(r["n_holdout"] is not None for r in ctx["ranking"]["kept"]))
            check("failures: q2가 더 많이 실패해 위로 옴(혹은 적어도 존재)", any(r["id"] == "q2" for r in ctx["failures"]))
            check("question_scope: 질문 범위가 집계됨", ctx["question_scope"]["total"] >= 2)
            check("invalid_run_notes: 무효 실행이 기록됨", ctx["invalid_run_notes"] and ctx["invalid_run_notes"][0]["run"] == "ans")

            ctx2 = build_context(retr_dir, [ans_dir])  # 무효 처리 없이 — 정상적으로 답 데이터가 쓰이는지
            check("build_context(무효 처리 없음): flat_ans에 데이터가 있음", bool(ctx2["flat_ans"]))
            check(
                "data_quality_warnings: 고립 세트가 경고에 뽑힘",
                any(w["dataset"] == "ds_bad_coverage" for w in ctx2["data_quality_warnings"]),
            )

            # 운영 k(§1) — holdout(hold_ds)에 k=5/10/20 답을 추가(G7: 여러 답 실행 디렉터리 병합)해 baseline은 k=20이,
            # chunker=fixed512는 k=5가 최고이게 만든다 — 운영 k 선택이 '모든 콤보 평균'이 아니라 baseline 기준임을 검증.
            def mk_rows(n_correct, n_total, prefix):
                return [
                    {
                        "id": f"{prefix}{i}",
                        "type": "t",
                        "negative": False,
                        "correct": i < n_correct,
                        "kw_in_context": True,
                        "evidence_hit": True,
                        "empty_answer": False,
                        "retry": False,
                        "error": None,
                        "evidence": [],
                        "answer": "x",
                        "ms": 500,
                        "tokens_in": 10,
                    }
                    for i in range(n_total)
                ]

            mk_specs = [
                ("baseline", 5, 5),
                ("baseline", 10, 5),
                ("baseline", 20, 9),
                ("chunker=fixed512", 5, 9),
                ("chunker=fixed512", 10, 6),
                ("chunker=fixed512", 20, 6),
            ]
            ans_mk_dir = Path(td) / "ans_mk"
            ans_mk_dir.mkdir()
            fake_answers_mk = [
                {
                    "combo": combo,
                    "dataset": hold_ds,
                    "group": "holdout",
                    "k": k,
                    "status": "built",
                    "answer": {
                        "dataset": hold_ds,
                        "k": k,
                        "n": 10,
                        "accuracy": n_ok / 10,
                        "kw_in_context": 1.0,
                        "empty_rate": 0.0,
                        "errors": 0,
                        "p50_ms": 500,
                        "rows": mk_rows(n_ok, 10, f"{combo[:3]}{k}_"),
                    },
                }
                for combo, k, n_ok in mk_specs
            ]
            (ans_mk_dir / "answers.json").write_text(json.dumps(fake_answers_mk, ensure_ascii=False), encoding="utf-8")

            # V11 — 방해 문서: hold_ds는 built(비교 가능), dev_ds는 skipped(미실행, 사유 표시) — 실제 loop1d 데이터와 같은 모양.
            retr_dist_dir = Path(td) / "retr_dist"
            ans_dist_dir = Path(td) / "ans_dist"
            retr_dist_dir.mkdir()
            ans_dist_dir.mkdir()
            dist_results = [
                {"combo": "baseline", "dataset": dev_ds, "status": "skipped", "reason": "S 없음 — build 먼저 --with-distractors"},
                {
                    "combo": "baseline",
                    "dataset": hold_ds,
                    "retrieval": {"n": 8, "r5": 0.75, "recall_at": {"1": 0.5}, "mrr": 0.6, "distractor_confusion_rate": 0.1, "rows": []},
                },
            ]
            (retr_dist_dir / "results.json").write_text(json.dumps(dist_results, ensure_ascii=False), encoding="utf-8")
            dist_answers = [
                {
                    "combo": "baseline",
                    "dataset": hold_ds,
                    "group": "holdout",
                    "k": 10,
                    "status": "built",
                    "answer": {"dataset": hold_ds, "k": 10, "n": 8, "accuracy": 0.75, "rows": mk_rows(6, 8, "dist_")},
                },
                # dev_ds는 검색 S가 없어도(위 dist_results에서 skipped) 답 실행은 따로 됨(실제 loop1d와 같은 모양) —
                # 정답률은 검색 미실행과 무관하게 떠야 한다.
                {
                    "combo": "baseline",
                    "dataset": dev_ds,
                    "group": "dev",
                    "k": 10,
                    "status": "built",
                    "answer": {"dataset": dev_ds, "k": 10, "n": 4, "accuracy": 0.25, "rows": mk_rows(1, 4, "distdev_")},
                },
            ]
            (ans_dist_dir / "answers.json").write_text(json.dumps(dist_answers, ensure_ascii=False), encoding="utf-8")

            ctx3 = build_context(retr_dir, [ans_dir, ans_mk_dir], retr_dist_dir=retr_dist_dir, answer_dist_dirs=[ans_dist_dir])
            check("operating_k: baseline(k=20, 9/10) 기준으로 20 선택 — chunker 쪽 k=5가 더 높아도 영향 없음", ctx3["operating_k"] == 20)
            check("ranking_by_k: k=5/10/20 각각 독립 순위", set(ctx3["ranking_by_k"]) == {5, 10, 20})
            check(
                "ranking_by_k: k=5는 chunker=fixed512가 1위(9/10), k=20은 baseline이 1위(9/10 vs 6/10)",
                ctx3["ranking_by_k"][5]["kept"][0]["combo"] == "chunker=fixed512"
                and ctx3["ranking_by_k"][20]["kept"][0]["combo"] == "baseline",
            )
            check("distractor_rows: hold_ds·dev_ds 둘 다 있음", ctx3["distractor_rows"] is not None and len(ctx3["distractor_rows"]) >= 2)
            dist_dev = next(r for r in ctx3["distractor_rows"] if r["dataset"] == dev_ds)
            dist_hold = next(r for r in ctx3["distractor_rows"] if r["dataset"] == hold_ds)
            check(
                "distractor_rows: dev_ds는 검색 미실행 사유 표시",
                dist_dev["dist"]["retrieval_status"] and "S 없음" in dist_dev["dist"]["retrieval_status"],
            )
            check(
                "distractor_rows: dev_ds는 검색 미실행이어도 답 정답률은 따로 채워짐(검색 S 없음≠답 미실행)",
                dist_dev["dist"]["acc"] == 0.25 and dist_dev["dist"]["n"] == 4,
            )
            check("distractor_rows: hold_ds는 오인율·R@5 채워짐", dist_hold["dist"]["confusion"] == 0.1 and dist_hold["dist"]["r5"] == 0.75)

            out_html3 = build_html(ctx3)
            check("build_html(V11): 방해 문서 탭 id 포함", "id='distractors'" in out_html3)
            check("build_html(V11): 미실행 사유가 탭에 보임", "S 없음" in out_html3)
            check("build_html(V11): 오인율 수치 등장", "0.100" in out_html3)
            check("build_html(V11): 검색 미실행이어도 답 정답률(0.250) 등장", "0.250" in out_html3)
            check("build_html(운영 k): '운영 k=20' 문구 등장", "운영 k=20" in out_html3)
            check("build_html(데이터 품질): 경고 배너 등장", "데이터 품질 경고" in out_html3 and "ds_bad_coverage" in out_html3)
            check("build_html 크기: 5MB 미만", len(out_html3.encode("utf-8")) < 5_000_000)

            # L3-2 — pool(합친 색인) 엔드투엔드: build_context/tab_pool/decision 탭 배선 확인.
            pool_retr_dir = Path(td) / "pool_retr"
            pool_ans_dir = Path(td) / "pool_ans"
            pool_retr_dir.mkdir()
            pool_ans_dir.mkdir()
            pool_results = [
                {
                    "combo": "baseline",
                    "dataset": hold_ds,
                    "pool": True,
                    "status": "built",
                    "retrieval": {
                        "dataset": hold_ds,
                        "n": 4,
                        "r5": 1.0,
                        "recall_at": {"1": 0.25},
                        "mrr": 0.6,
                        "rows": [
                            {"id": "p1", "gold_rank": 3, "oldver_rank": 1, "distractor_rank": 9},
                            {"id": "p2", "gold_rank": 3, "oldver_rank": 7, "distractor_rank": None},
                            {"id": "p3", "gold_rank": 1, "oldver_rank": None, "distractor_rank": 2},
                            {"id": "p4", "gold_rank": 2, "oldver_rank": 12, "distractor_rank": 12},
                        ],
                    },
                }
            ]
            (pool_retr_dir / "results.json").write_text(json.dumps(pool_results, ensure_ascii=False), encoding="utf-8")
            pool_answers = [
                {
                    "combo": "baseline",
                    "dataset": POOL_V2_DS,
                    "k": 15,
                    "answer": {"n": 4, "accuracy": 0.5, "oldver_value_in_answer_rate": 0.25},
                }
            ]
            (pool_ans_dir / "answers.json").write_text(json.dumps(pool_answers, ensure_ascii=False), encoding="utf-8")

            ctx4 = build_context(retr_dir, [ans_dir], pool_retr_dir=pool_retr_dir, pool_answer_dirs=[pool_ans_dir])
            pd4 = ctx4["pool_data"]
            check("pool_data: retrieval_rows 1행(baseline×hold_ds)", pd4 is not None and len(pd4["retrieval_rows"]) == 1)
            pr4 = pd4["retrieval_rows"][0]
            check(
                "pool_data: 콤보·데이터셋 row의 엄격/느슨이 함수와 일치(엄격 0.25, 느슨 0.5)",
                abs(pr4["oldver_strict"] - 0.25) < 1e-9 and abs(pr4["oldver_loose"] - 0.5) < 1e-9,
            )
            check(
                "pool_data: 별도 색인(retr_dir)엔 recall_at이 없어 r1_separate·delta는 n/a",
                pr4["r1_separate"] is None and pr4["r1_delta"] is None,
            )
            check("pool_data: answer_rows에 v2 구판값 유출률", pd4["answer_rows"][0]["oldver_value_in_answer_rate"] == 0.25)
            out_html4 = build_html(ctx4)
            check("build_html(pool): pool 탭에 데이터 등장", "id='pool'" in out_html4 and POOL_V2_DS in out_html4)
            check("build_html(pool): decision 탭 요약 한 줄 등장", "pool(2-4 탭)" in out_html4)

            out_html = build_html(ctx)
            check("build_html: <html> 포함", "<html" in out_html)
            check("build_html: 탭 id 전부 포함", all(f"id='{tid}'" in out_html for tid, _ in TABS))
            check("build_html: 콤보 이름 등장", "chunker=fixed512" in out_html)
            check("build_html(G6): 첫 탭이 서버에서부터 active", "id='decision' class='tab active'" in out_html)
            check("build_html(G4): 순위 표에 n= 표시", "(n=" in out_html)
            check("build_html: 무효 실행 사유 표시", "하네스 결함" in out_html)

            out_path = Path(td) / "report.html"
            out_path.write_text(out_html, encoding="utf-8")
            check("출력 파일 생성됨", out_path.exists() and out_path.stat().st_size > 0)
    finally:
        M.STACK_CFG_PATH = saved_cfg_path  # 실패해도 지운 임시 파일을 가리키지 않게

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    cmd_selftest()
