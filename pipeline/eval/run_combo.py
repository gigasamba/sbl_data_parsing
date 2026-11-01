#!/usr/bin/env python3
"""조합 실험 CLI(eval-design.md §2) — 청킹·임베딩·그래프·검색 축을 빔 탐색으로 줄여 R 지표(§3-4)로 채점한다. LLM 없음.

단계 순서(§2-2): parse → chunk → embed → retrieve → graph. 각 단계에서 상위 B개(--beam)만 다음 단계로 넘기고,
상위 축의 선택지별 순위 일치도(Kendall τ)가 0.6 미만이면 그 단계를 전체 곱으로 넓혀 돈다(beam.json에 기록).
끝나면 살아남은 축값들의 전체 곱을 한 번 더 돌린다(§2-4). 모든 평가는 output/eval/results.jsonl에 한 줄씩 쌓이고,
이미 평가한 조합은 --force 없이는 건너뛴다(재개).

사용:
  python cli/run_combo.py --parse-dir output/parse --src output/corpus/docs [--truth output/corpus/truth.json]
    [--parse route,route2] [--chunk ...] [--embed ...] [--graph ...] [--retrieve ...] [--beam 2] [--full]
    [--out output/eval] [--rerank] [--force]

실행 조건(SI4) — parse_qa.py가 먼저 끝나 있어야 함(output/parse/route.json). 옵션으로 막아 둔 것(의도 — 코드로 그대로 유지):
  - `--embed`에 none 아닌 실제 모델(e5-small·e5-base·bge-m3)을 쓰려면 모델이 준비돼 있어야 함
    (HF_HUB_OFFLINE=1 + 반입 캐시, 또는 .env EMBED_BASE_URL·EMBED_MODEL) — AGENTS.md A9.
  - `--graph llm`은 LLM을 쓰는 유일한 옵션(그 외 축은 전부 LLM 0회 — S6a부터 PC 전용 validation/e2e/graph_llm.py, 서버 이미지에서는 ValueError) — LLM_BASE_URL(내부망, 서버 GLM)이 있어야 하고,
    외부 주소는 *_ALLOW_EXTERNAL=1 + RUN_ENV=local일 때만 common/guard.py가 통과시킨다.
    **실문서에는 외부 주소를 열지 않는다(DONT 13) — 이 가드는 완화하지 않는다.** AGENTS.md A10.
  - `--rerank`가 없으면 retrieve=rerank 조합은 combo_valid()가 걸러냄(CPU 재순위 느림 — 기본 off, 켜려면 이 플래그).
  - `--full`이 없으면 빔 탐색(기본, 적은 수만 평가) — 축 조합이 작을 때만 전체 곱(--full)을 켠다.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import hashlib
import itertools
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from common.config.settings import cfg  # common 칸(S7c — 설정 객체: LLM_BASE_URL·EMBED_BASE_URL)

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")  # env 남김 — 라이브러리(5-3 H)

from pipeline.eval import anchors as A
from pipeline.eval import stages as S

AXES = ["parse", "chunk", "embed", "retrieve", "graph"]
# 빔 단계: 임베딩×검색은 한 단계(임베딩 없음이면 dense·hybrid가 불가능해 따로 고르면 검색 축이 잘림),
# 그래프 연결 방식은 그래프를 쓰는 검색(graph)으로 평가(연결 방식 ≠ none이면 retrieve=graph로 고정, none은 앞 단계 검색 그대로 = 기준선)
STAGES = [("parse",), ("chunk",), ("embed", "retrieve"), ("graph",)]
DEFAULTS = {"chunk": "structure", "embed": "none", "graph": "none", "retrieve": "bm25"}


def with_defaults(combo):
    """아직 안 정한 축에 기본값 채움. retrieve 기본값은 embed != none이면 hybrid로 바뀐다(§2 빔 탐색 규칙)."""
    c = dict(combo)
    embed = c.get("embed", DEFAULTS["embed"])
    if "retrieve" not in c:
        c["retrieve"] = "hybrid" if embed != "none" else "bm25"
    for axis in ("chunk", "embed", "graph"):
        c.setdefault(axis, DEFAULTS[axis])
    return c


def combo_valid(combo, rerank_ok):
    if combo.get("embed", "none") == "none" and combo.get("retrieve") in S.NEEDS_EMBED:
        return False
    if combo.get("retrieve") == "rerank" and not rerank_ok:
        return False
    return True


def combo_hash(combo):
    """조합의 안정적 짧은 식별자 — results.jsonl의 "key" 필드이자 output/eval/hits/<key>.jsonl 파일명·재개 키."""
    return hashlib.sha256(json.dumps(combo, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def rank_key(r):
    """R@5 → MRR → 유의미 글자 수(많을수록 좋음) 순 정렬키(§2-4) — pipeline.eval.stages.rank_key."""
    return S.rank_key(r["R"])


def kendall_tau(a, b):
    """켄달 타우(scipy 없이) — 같은 항목 집합을 담은 두 순서열의 순위 일치도."""
    if len(a) < 2 or set(a) != set(b):
        return 1.0
    idx = {v: i for i, v in enumerate(b)}
    seq = [idx[v] for v in a]
    n = len(seq)
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            if (seq[i] - seq[j]) * (i - j) > 0:
                conc += 1
            else:
                disc += 1
    total = n * (n - 1) // 2
    return (conc - disc) / total if total else 1.0


def append_result(path, combo, r, stage, key):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"combo": combo, "stage": stage, "key": key, "R": r["R"], "C": r["C"], "G": r["G"], "n_anchors": r["n_anchors"], "sec": r["sec"]}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def write_hits(path, hit_rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in hit_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_done(path):
    """results.jsonl → {key: 결과} — 재개용(같은 조합 재평가 없음). key는 combo_hash와 같은 값."""
    path = Path(path)
    done = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        key = d.get("key") or combo_hash(d["combo"])
        done[key] = {"R": d["R"], "C": d["C"], "G": d["G"], "n_anchors": d["n_anchors"], "sec": d["sec"]}
    return done


# ── 조합 하나 채점 ───────────────────────────────────────────

_QVEC: dict = {}


def build_combo_state(combo, ctx):
    """조합 하나를 코퍼스·청크·임베딩·그래프·검색 함수로 재구성 — eval_combo·ranked_units(답변 도구용) 공용.
    반환 dict: corpus, anchors(이 조합의 코퍼스에 있는 문서만), chunks, run_query(앵커 dict -> ranked units), G, g_metrics."""
    used = {}
    corpus, facts_by_doc = S.load_corpus(ctx["parse_dir"], ctx["docs"], combo["parse"], ctx["route"], used)
    anchors = [a for a in ctx["anchors"] if a["doc"] in corpus]
    chunks = S.chunk_all(corpus, combo["chunk"], used)
    embed_vecs = embed_fn = None
    if combo["embed"] != "none":
        texts = [c["text"] for c in chunks]
        embed_vecs = S.cached_embed(combo["embed"], texts, "passage", ctx["cache_dir"]) if texts else None

        def embed_fn(qs, kind, _e=combo["embed"]):
            # 질의 벡터는 조합이 바뀌어도 같음 — 모델별로 한 번만 계산(bge-m3 조합 시간의 대부분이 질의 인코딩이었음).
            # ponytail: 그래서 p50·p95 지연은 두 번째 조합부터 질의 인코딩을 뺀 검색 시간 — 인코딩 지연은 모델 표(카탈로그) 참고
            miss = [q for q in qs if (_e, kind, q) not in _QVEC]
            if miss:
                for q, v in zip(miss, S.embed_texts(_e, miss, kind)):
                    _QVEC[(_e, kind, q)] = v
            return [_QVEC[(_e, kind, q)] for q in qs]

    G, g_metrics = None, {}
    if combo["graph"] != "none":
        G, g_metrics = S.build_graph(combo["graph"], chunks, embeddings=embed_vecs, facts_by_doc=facts_by_doc)

    def run_query(a):
        return S.retrieve(
            combo["retrieve"], a["query"], chunks, corpus, embed_vecs=embed_vecs, embed_fn=embed_fn, G=G, rerank_ok=ctx["rerank"]
        )

    return {"corpus": corpus, "anchors": anchors, "chunks": chunks, "run_query": run_query, "G": G, "g_metrics": g_metrics}


def eval_combo(combo, ctx):
    """반환: (결과 dict, 앵커별 hit 상세 목록 — output/eval/hits/<key>.jsonl로 저장됨)."""
    t0 = time.perf_counter()
    st = build_combo_state(combo, ctx)
    R, hit_rows = S.eval_retrieval(st["anchors"], st["run_query"])
    C = S.chunk_metrics(st["chunks"], st["anchors"], truth=ctx.get("truth"))
    Gd = dict(st["g_metrics"])
    if combo["graph"] != "none" and st["anchors"]:
        Gd["anchor_path"] = S.anchor_path_rate(st["anchors"], st["G"], st["chunks"])
    r = {"R": R, "C": C, "G": Gd, "n_anchors": len(st["anchors"]), "sec": round(time.perf_counter() - t0, 3)}
    return r, hit_rows


def ranked_units(combo, ctx):
    """조합 하나 재구성 → {anchor_id: [ranked units(topk=10, graph 조합이면 "parts" 포함)]} — 답변 도구(run_answers.py)가
    같은 검색 로직으로 LLM에 넘길 컨텍스트를 얻는다(eval_combo와 조합 구성 로직 중복 없음)."""
    st = build_combo_state(combo, ctx)
    return {a["id"]: st["run_query"](a) for a in st["anchors"]}


def _run_or_reuse(combo, ctx, stage):
    key = combo_hash(combo)
    hits_path = ctx["hits_dir"] / f"{key}.jsonl"
    if key in ctx["done"] and not ctx["force"] and hits_path.exists():
        return ctx["done"][key]
    r, hit_rows = eval_combo(combo, ctx)
    write_hits(hits_path, hit_rows)
    append_result(ctx["results_path"], combo, r, stage, key)
    ctx["done"][key] = r
    return r


# ── 빔 탐색 (§2-2·2-3) ──────────────────────────────────────


def run_stage(axes, choices, survivors, ctx):
    """axes: 이 단계에서 정하는 축 튜플, choices: 값 튜플 목록. survivors: 이전 단계까지 결정된 부분 조합 목록.
    choices × survivors 전수 평가 후 상위 beam개 유지."""
    axis = "+".join(axes)
    grid = {}  # key -> (부분조합, 전체조합)
    for up in survivors:
        for val in choices:
            partial = {**up, **dict(zip(axes, val))}
            if axes == ("graph",) and val[0] != "none":
                partial["retrieve"] = "graph"
            full = with_defaults(partial)
            if not combo_valid(full, ctx["rerank"]):
                continue
            grid[combo_hash(full)] = (partial, full)
    scored = [(p, f, _run_or_reuse(f, ctx, axis)) for p, f in grid.values()]
    if not scored:
        return survivors, {"axis": axis, "choices": choices, "tau": None, "widened": False, "grid": 0, "survivors": survivors}
    tau = None
    if len(survivors) >= 2:
        rankings = []
        for up in survivors:
            sub = [(f, r) for p, f, r in scored if all(f[k] == up[k] for k in up)]
            if len(sub) < 2:
                continue
            rankings.append(["/".join(str(f[a]) for a in axes) for f, r in sorted(sub, key=lambda fr: rank_key(fr[1]))])
        taus = [kendall_tau(rankings[i], rankings[j]) for i in range(len(rankings)) for j in range(i + 1, len(rankings))]
        tau = sum(taus) / len(taus) if taus else None
    widened = tau is not None and tau < 0.6
    top = []
    for p, _f, _r in sorted(scored, key=lambda pfr: rank_key(pfr[2])):
        if p not in top:
            top.append(p)
        if len(top) >= ctx["beam"] * (2 if widened else 1):  # 순위가 앞 단계에 따라 흔들리면(τ < 0.6) 빔을 2배로
            break
    return top, {"axis": axis, "choices": choices, "tau": tau, "widened": widened, "grid": len(scored), "survivors": top}


def run_beam(ctx, axes_choices):
    survivors, stages_info = [{}], []
    for axes in STAGES:
        choices = list(itertools.product(*[axes_choices[a] for a in axes]))
        survivors, info = run_stage(axes, choices, survivors, ctx)
        stages_info.append(info)
    axis_values = {
        axis: sorted({c.get(axis) for c in survivors if c.get(axis) is not None})
        or [with_defaults({})[axis] if axis != "parse" else axes_choices["parse"][0]]
        for axis in AXES
    }
    combos = [dict(zip(AXES, vals)) for vals in itertools.product(*[axis_values[a] for a in AXES])]
    final = []
    for combo in combos:
        if not combo_valid(combo, ctx["rerank"]):
            continue
        final.append((combo, _run_or_reuse(combo, ctx, "final")))
    final.sort(key=lambda cr: rank_key(cr[1]))
    return {"stages": stages_info, "final": {"axis_values": axis_values, "n_combos": len(combos), "best": final[0][0] if final else None}}


def run_full(ctx, axes_choices):
    combos = [dict(zip(AXES, vals)) for vals in itertools.product(*[axes_choices[a] for a in AXES])]
    out = []
    for combo in combos:
        if not combo_valid(combo, ctx["rerank"]):
            continue
        out.append((combo, _run_or_reuse(combo, ctx, "full")))
    out.sort(key=lambda cr: rank_key(cr[1]))
    return out


# ── 외부 스택 결과 채점 (§5 마지막 문단) ─────────────────────


def run_external(ctx, out_dir, anchors):
    """output/eval/external/<스택>.jsonl({"anchor_id","units"}) → combo {"parse":"external","retrieve":스택}로 채점."""
    ext_dir = Path(out_dir) / "external"
    if not ext_dir.exists():
        return []
    out = []
    for f in sorted(ext_dir.glob("*.jsonl")):
        stack = f.stem
        units = defaultdict(list)
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                units[d["anchor_id"]] = d.get("units", [])
        combo = {"parse": "external", "retrieve": stack}
        key = combo_hash(combo)
        hits_path = ctx["hits_dir"] / f"{key}.jsonl"
        if key in ctx["done"] and not ctx["force"] and hits_path.exists():
            out.append((combo, ctx["done"][key]))
            continue
        R, hit_rows = S.eval_retrieval(anchors, lambda a, u=units: u.get(a["id"], []))
        r = {"R": R, "C": {}, "G": {}, "n_anchors": R["n_anchors"], "sec": 0.0}
        write_hits(hits_path, hit_rows)
        append_result(ctx["results_path"], combo, r, "external", key)
        ctx["done"][key] = r
        out.append((combo, r))
    return out


# ── CLI ──────────────────────────────────────────────────────


def build_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parse-dir", default="output/parse")
    ap.add_argument("--src", help="원본 문서 폴더(문서 목록·확장자 판별용)")
    ap.add_argument("--truth", help="output/corpus/truth.json")
    ap.add_argument("--answer-key", help="answer_key/<문서>.json 폴더")
    ap.add_argument("--anchor-ref", default="route", help="앵커를 만들 기준 파싱 설정")
    ap.add_argument("--parse", default="route,route2")
    ap.add_argument("--chunk", default="fixed512,recursive,structure,sentence3,page")
    ap.add_argument("--embed", default="none,e5-small,e5-base,bge-m3", help="none 아니면 모델 준비 필요(위 '실행 조건' 참고)")
    ap.add_argument("--graph", default="none,struct,entity,knn,table", help="llm은 LLM_BASE_URL(내부망) 필요(위 '실행 조건' 참고)")
    ap.add_argument("--retrieve", default="bm25,dense,hybrid,hybrid_mmr,graph,parent,grep")
    ap.add_argument("--beam", type=int, default=2)
    ap.add_argument("--full", action="store_true", help="주어진 축 목록의 전체 곱(빔 탐색 대신)")
    ap.add_argument("--out", default="output/eval")
    ap.add_argument("--rerank", action="store_true", help="retrieve=rerank 허용(CPU 느림)")
    ap.add_argument("--force", action="store_true", help="이미 평가한 조합도 다시 돈다")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cap", type=int, default=10, help="문서당 앵커 최대 개수(§4)")
    return ap


def split_list(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def run(a):
    out_dir = Path(a.out)
    parse_dir = Path(a.parse_dir)
    if not a.src:
        raise SystemExit("--src 필요(원본 문서 폴더 — 문서 목록·확장자 판별용)")
    docs = sorted(p.name for p in Path(a.src).iterdir() if p.is_file())
    route = S.load_route(parse_dir)
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8")) if a.truth else None
    ref_corpus, _ = S.load_corpus(parse_dir, docs, a.anchor_ref, route)
    anchors = A.build_anchors(ref_corpus, docs, truth=truth, answer_key_dir=a.answer_key, seed=a.seed, cap=a.cap)
    A.write_anchors(anchors, out_dir / "anchors.jsonl")
    results_path = out_dir / "results.jsonl"
    ctx = {
        "parse_dir": parse_dir,
        "route": route,
        "docs": docs,
        "anchors": anchors,
        "truth": truth,
        "rerank": a.rerank,
        "cache_dir": out_dir / "cache",
        "hits_dir": out_dir / "hits",
        "results_path": results_path,
        "done": load_done(results_path),
        "beam": a.beam,
        "force": a.force,
    }
    axes_choices = {
        "parse": split_list(a.parse),
        "chunk": split_list(a.chunk),
        "embed": split_list(a.embed),
        "retrieve": split_list(a.retrieve),
        "graph": split_list(a.graph),
    }
    pc_only = [g for g in axes_choices["graph"] if g in S._PC_MODES and not S.graph_mode_ready(g)]
    if pc_only:  # S6a(T-02) — 서버 이미지에는 validation/이 없음: 파싱·임베딩·검색 단계를 다 돈 뒤 그래프 단계에서 죽지 않게 시작 때 거부
        raise SystemExit(f"--graph {','.join(pc_only)}: PC 전용 그래프 모드(validation/e2e) — 이 환경에 없음")
    # AD43 — 축(graph=llm·embed=api) 무관, 이번 실행이 쓰는 외부 주소 전부(LLM·EMBED) + 조합 수(다른 축 전부의 곱,
    # 보안 검토 10-07: graph=="llm"만 보면 --embed api 조합이 새 나감) 한 번에. 전부 내부면 바로 통과.
    from common.ai.guard import check_scope

    n_axis_combos = 1
    for vals in axes_choices.values():
        n_axis_combos *= len(vals)
    check_scope([cfg().models.llm.base_url, cfg().models.embed.base_url], n_combos=n_axis_combos, n_docs=len(docs))
    if a.full:
        results = run_full(ctx, axes_choices)
        print(f"앵커 {len(anchors)}개 · full 조합 {len(results)}개 → {results_path}")
    else:
        beam_doc = run_beam(ctx, axes_choices)
        (out_dir / "beam.json").write_text(json.dumps(beam_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"앵커 {len(anchors)}개 · beam.json → {out_dir / 'beam.json'} · results.jsonl → {results_path}")
    ext = run_external(ctx, out_dir, anchors)
    if ext:
        print(f"외부 스택 {len(ext)}개 채점 완료")
    from common.core.runlog import note

    rows = [json.loads(x) for x in results_path.read_text(encoding="utf-8").splitlines() if x.strip()] if results_path.exists() else []
    note(f"앵커 {len(anchors)}개 · 누적 조합 {len(rows)}개" + (f" · 외부 스택 {len(ext)}개" if ext else ""))
    if rows:
        b = sorted(rows, key=lambda r: S.rank_key(r["R"]))[0]
        c = b["combo"]
        note(
            f"1위: {c.get('parse')}·{c.get('chunk')}·{c.get('embed')}·{c.get('graph')}·{c.get('retrieve')} "
            f"R@5 {b['R']['r5']:.3f} · MRR {b['R']['mrr']:.3f} · ctx {b['R']['ctx5']:,}자"
        )


def main(argv=None):
    a = build_cli().parse_args(argv)
    run(a)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("run_combo"):
        main()
