"""validation.e2e.model_matrix 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m validation.e2e.model_matrix selftest`."""

import argparse
from pathlib import Path

from validation.e2e.model_matrix import (
    CONFIG_PATH,
    _merge_stage2,
    _pick_stage1_winner,
    _recommend,
    _role_delta_row,
    _stage2_metrics,
    bootstrap_ci,
    dataset_fingerprint,
    design_combos,
    load_config,
    mcnemar_p,
    role_candidates,
    stage1_combos,
    stage2_combos,
    usable_candidates,
)


def cmd_selftest(config, a):
    import tempfile

    failures = []

    def check(name, cond):
        print(("OK   " if cond else "FAIL ") + name)
        if not cond:
            failures.append(name)

    # 1) 설정 파싱
    check("config: roles는 llm·vlm·embed 세 개", set(config["roles"]) == {"llm", "vlm", "embed"})
    check(
        "config: 역할마다 baseline이 candidates 안에 있음",
        all(config["roles"][r]["baseline"] in {c["id"] for c in config["roles"][r]["candidates"]} for r in config["roles"]),
    )
    check("config: design 필드 있음", "design" in config)

    # 2) OFAT 조합 생성 — baseline 1개 + 역할당 1개 바뀐 조합, 중복 없음
    combos = design_combos(config)
    names = [c["name"] for c in combos]
    check("ofat: baseline 정확히 1개", names.count("baseline") == 1)
    check("ofat: 조합 이름 중복 없음", len(names) == len(set(names)))
    expected_alt = sum(len(usable_candidates(config, r)[1]) - 1 for r in ("llm", "vlm", "embed"))
    check(f"ofat: baseline 제외 {expected_alt}개(역할당 후보수-1 합)", len(combos) - 1 >= expected_alt)
    for c in combos[1:]:
        if c["name"].startswith("extra"):
            continue
        changed = sum(1 for r in ("llm", "vlm", "embed") if c[r] != combos[0][r])
        check(f"ofat: {c['name']}은 정확히 1개 역할만 baseline과 다름", changed == 1)

    # 3) 데이터셋 지문 변화 감지
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "a.txt").write_text("hello", encoding="utf-8")
        fp1 = dataset_fingerprint("fake", root=td)
        check("fingerprint: 같은 내용 → 같은 지문", fp1 == dataset_fingerprint("fake", root=td))
        (td / "a.txt").write_text("hello world", encoding="utf-8")
        fp2 = dataset_fingerprint("fake", root=td)
        check("fingerprint: 파일 크기 바뀌면 → 다른 지문", fp1 != fp2)
        (td / "qa.json").write_text("{}", encoding="utf-8")
        check("fingerprint: qa.json 등 비문서 파일은 지문에서 빠짐", dataset_fingerprint("fake", root=td) == fp2)
        (td / "b.txt").write_text("x", encoding="utf-8")
        check("fingerprint: 파일이 늘면 → 다른 지문", dataset_fingerprint("fake", root=td) != fp2)

    # 4) report 델타 계산(가짜 결과)
    fake_metrics = {
        ("baseline", "synth-4clients"): {"retrieval_r5": 0.70, "mean_ms": 4000},
        ("baseline", "synth-plant"): {"retrieval_r5": 0.60, "mean_ms": 4100},
        ("embed=bge-m3", "synth-4clients"): {"retrieval_r5": 0.75, "mean_ms": 3500},
        ("embed=bge-m3", "synth-plant"): {"retrieval_r5": 0.55, "mean_ms": 3600},
    }
    fake_group = {"synth-4clients": "dev", "synth-plant": "holdout"}
    row = _role_delta_row(config, "embed", "bge-m3", fake_metrics, fake_group, "retrieval_r5", "mean_ms")
    check("report: dev 델타 = +0.05", row["dev_delta"] is not None and abs(row["dev_delta"] - 0.05) < 1e-9)
    check("report: held-out 델타 = -0.05", row["holdout_delta"] is not None and abs(row["holdout_delta"] - (-0.05)) < 1e-9)
    check("report: 갭(held-out-dev) = -0.10", row["gap"] is not None and abs(row["gap"] - (-0.10)) < 1e-9)
    check("report: 추천 = 품질 저하(갭 과다)로 기준 유지", _recommend(row) == "기준 유지(품질 저하 또는 held-out 갭 과다)")

    # 품질 우위 케이스
    fake_metrics2 = dict(fake_metrics)
    fake_metrics2[("embed=bge-m3", "synth-plant")] = {"retrieval_r5": 0.63, "mean_ms": 3600}
    row2 = _role_delta_row(config, "embed", "bge-m3", fake_metrics2, fake_group, "retrieval_r5", "mean_ms")
    check("report: 품질 우위 케이스 → 채택 후보", _recommend(row2).startswith("채택 후보"))

    # 5) staged 설계 — 1단계(embed만) · 2단계(llm×vlm 2x2) 조합
    s1 = stage1_combos(config)
    check("staged: 1단계은 embed 후보 수만큼(llm·vlm은 전부 기준)", len(s1) == len(usable_candidates(config, "embed")[1]))
    check("staged: 1단계 모든 콤보가 llm·vlm 기준 고정", all(c["llm"] == s1[0]["llm"] and c["vlm"] == s1[0]["vlm"] for c in s1))
    base_embed, _ = role_candidates(config, "embed")
    s2 = stage2_combos(config, base_embed)
    _, llm_c = usable_candidates(config, "llm")
    _, vlm_c = usable_candidates(config, "vlm")
    check("staged: 2단계는 llm×vlm 전체 곱(2x2 이상)", len(s2) == len(llm_c) * len(vlm_c))
    check("staged: 2단계 모든 콤보가 embed=승자로 고정", all(c["embed"] == base_embed for c in s2))

    # 6) 1단계 승자 선택 — held-out R@5 우선, 동률이면 dev
    fake_s1 = [
        {"combo": "embed=A", "dataset": "d1", "retrieval": {"r5": 0.80}},
        {"combo": "embed=A", "dataset": "d2", "retrieval": {"r5": 0.70}},
        {"combo": "embed=B", "dataset": "d1", "retrieval": {"r5": 0.75}},
        {"combo": "embed=B", "dataset": "d2", "retrieval": {"r5": 0.90}},
    ]
    fake_s1_combos = [{"name": "embed=A", "embed": "A"}, {"name": "embed=B", "embed": "B"}]
    fake_s1_group = {"d1": "dev", "d2": "holdout"}
    winner, scores = _pick_stage1_winner(fake_s1_combos, fake_s1, fake_s1_group)
    check("stage1 승자: held-out R@5가 더 높은 쪽(B, 0.90>0.70)", winner == "B")

    # 7) McNemar 정확검정·부트스트랩 CI
    check("mcnemar: 불일치 없으면 None", mcnemar_p([(True, True), (False, False)]) is None)
    pairs_diff = [(True, False)] * 10 + [(False, True)] * 1  # 10 vs 1 불일치 — 정확 p=0.012(8 vs 2는 0.109라 유의 아님)
    p_diff = mcnemar_p(pairs_diff)
    check("mcnemar: 불일치가 치우치면 p<0.05", p_diff is not None and p_diff < 0.05)
    pairs_even = [(True, False)] * 5 + [(False, True)] * 5  # 5 vs 5 — 완전 동률
    p_even = mcnemar_p(pairs_even)
    check("mcnemar: 불일치가 반반이면 p=1.0", p_even is not None and abs(p_even - 1.0) < 1e-9)
    lo, hi = bootstrap_ci([1.0] * 10)
    check("bootstrap: 전부 1이면 CI도 [1,1]", lo == 1.0 and hi == 1.0)
    lo2, hi2 = bootstrap_ci([1, 0, 1, 0, 1, 0, 1, 0])
    check("bootstrap: 섞인 값이면 CI가 0과 1 사이에 걸침", lo2 is not None and 0.0 <= lo2 <= 0.5 <= hi2 <= 1.0)

    # 8) staged report — repeats 병합 + 복합 콤보 이름 델타(10-13 — keyword_hit/research_answer_hit는 답변 경로
    # 통일 3단계로 drop, evidence_hit/research_evidence_hit로 같은 모양 재확인)
    fake_results = [
        {
            "combo": "llm=base+vlm=base",
            "dataset": "dsA",
            "repeat": 0,
            "research": {
                "report": {
                    "sets": {
                        "dsA": {"items": [{"id": "Q1", "evidence_hit": True, "ms": 1000}, {"id": "Q2", "evidence_hit": False, "ms": 1200}]}
                    }
                }
            },
        },
        {
            "combo": "llm=base+vlm=base",
            "dataset": "dsA",
            "repeat": 1,
            "research": {
                "report": {
                    "sets": {
                        "dsA": {"items": [{"id": "Q1", "evidence_hit": True, "ms": 900}, {"id": "Q2", "evidence_hit": False, "ms": 1100}]}
                    }
                }
            },
        },
        {
            "combo": "llm=alt+vlm=base",
            "dataset": "dsA",
            "repeat": 0,
            "research": {
                "report": {
                    "sets": {
                        "dsA": {"items": [{"id": "Q1", "evidence_hit": True, "ms": 800}, {"id": "Q2", "evidence_hit": True, "ms": 1000}]}
                    }
                }
            },
        },
        {
            "combo": "llm=alt+vlm=base",
            "dataset": "dsA",
            "repeat": 1,
            "research": {
                "report": {
                    "sets": {
                        "dsA": {"items": [{"id": "Q1", "evidence_hit": True, "ms": 850}, {"id": "Q2", "evidence_hit": True, "ms": 950}]}
                    }
                }
            },
        },
    ]
    merged = _merge_stage2(fake_results)
    check("staged report: repeats 병합 — items가 이어붙음(2+2=4)", len(merged[("llm=base+vlm=base", "dsA")]["research_items"]) == 4)
    smetrics = _stage2_metrics(merged)
    check(
        "staged report: evidence_hit 병합(base 0.5 < alt 1.0)",
        abs(smetrics[("llm=base+vlm=base", "dsA")]["research_evidence_hit"] - 0.5) < 1e-9
        and abs(smetrics[("llm=alt+vlm=base", "dsA")]["research_evidence_hit"] - 1.0) < 1e-9,
    )
    fake_group2 = {"dsA": "dev"}
    row3 = _role_delta_row(
        config,
        "llm",
        "alt",
        smetrics,
        fake_group2,
        "research_evidence_hit",
        "research_mean_ms",
        combo_name="llm=alt+vlm=base",
        baseline_name="llm=base+vlm=base",
    )
    check(
        "staged report: combo_name·baseline_name을 받으면 OFAT 이름 없이도 델타 계산",
        row3["dev_delta"] is not None and abs(row3["dev_delta"] - 0.5) < 1e-9,
    )

    print(f"\n{'모두 통과' if not failures else str(len(failures)) + '건 실패: ' + ', '.join(failures)}")
    if failures:
        raise SystemExit(1)


def test_main():  # 옛 `selftest` 하위 명령(main()의 `cmd_selftest(load_config(a.config), a)`)
    a = argparse.Namespace(config=str(CONFIG_PATH), cmd="selftest")  # 옛 main()의 ap.parse_args() 결과 꼴
    config = load_config(a.config)
    cmd_selftest(config, a)
