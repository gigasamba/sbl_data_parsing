"""pipeline.eval.run_combo 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.run_combo --selftest`."""

import json
import time
from pathlib import Path

from pipeline.eval import anchors as A
from pipeline.eval import stages as S
from pipeline.eval.run_combo import STAGES, combo_hash, eval_combo, load_done, run_beam, run_full

# ── 자기 점검 (--selftest) ───────────────────────────────────


def _build_fixture(base):
    """가짜 output/parse(엔진 2 × 문서 4) + route.json + truth.json + --src 폴더. engineB는 doc2를 일부러 실패시킨다."""
    base = Path(base)
    src = base / "src"
    src.mkdir(parents=True, exist_ok=True)
    parse_dir = base / "parse"
    docs = {
        "doc1.txt": "계약번호: CT-1001\n공급업체: 가나다상사\n계약금액: 1,200,000원\n계약일자: 2026-01-15\n"
        "담당자 이메일: kim@example.com\n본 계약은 사무용품 공급에 관한 사항을 정한다. "
        "공급 범위는 문구류와 사무기기를 포함한다.\n",
        "doc2.txt": "계약번호: CT-1002\n공급업체: 나라기업\n계약금액: 980,000원\n계약일자: 2026-02-20\n"
        "담당자 이메일: lee@example.com\n본 계약은 청소용역에 관한 사항을 정한다. "
        "용역 범위는 사무실 정기 청소를 포함한다.\n",
        "doc3.pdf": "계약번호: CT-1003\n공급업체: 다라물산\n계약금액: 2,300,000원\n계약일자: 2026-03-11\n"
        "담당자 이메일: park@example.com\n본 계약은 인쇄물 제작에 관한 사항을 정한다.\n",
        "doc4.pdf": "계약번호: CT-1004\n설비ID: EQ-4400\n공급업체: 마바테크\n계약금액: 3,150,000원\n"
        "계약일자: 2026-04-05\n담당자 이메일: choi@example.com\n본 계약은 설비 유지보수에 관한 사항을 정한다.\n",
    }
    for name in docs:
        (src / name).write_text("", encoding="utf-8")  # --src는 목록·확장자 판별용, 내용은 parse 결과가 정본
    for eng in ("engineA", "engineB"):
        (parse_dir / eng).mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        for eng in ("engineA", "engineB"):
            if eng == "engineB" and name == "doc2.txt":
                continue  # engineB가 doc2를 실패했다고 가정 — 미스 테스트용
            variant = text if eng == "engineA" else text.replace("본 계약은", "본 계약(사본)은")
            tables, facts = [], []
            if name == "doc1.txt" and eng == "engineA":
                amount = text.split("계약금액: ")[1].split("\n")[0]
                tables = [{"rows": 1, "cols": 2, "text": "계약금액 " + amount}]
                facts = [{"value": amount, "context": ["계약금액"]}]
            (parse_dir / eng / f"{name}.json").write_text(
                json.dumps({"text": variant, "tables": tables, "facts": facts}, ensure_ascii=False), encoding="utf-8"
            )
    route = {".txt": ["engineA", "engineB"], ".pdf_text": ["engineA", "engineB"]}
    (parse_dir / "route.json").write_text(json.dumps(route, ensure_ascii=False), encoding="utf-8")
    truth = {
        "doc1.txt": {
            "values": [
                {"label": "계약번호", "value": "CT-1001", "kind": "id"},
                {"label": "계약금액", "value": "1,200,000원", "kind": "amount"},
            ]
        },
        "doc2.txt": {
            "values": [
                {"label": "계약번호", "value": "CT-1002", "kind": "id"},
                {"label": "계약금액", "value": "980,000원", "kind": "amount"},
            ],
            "tables": [[["항목", "금액"], ["기본료", "980,000원"]]],
        },
    }
    truth_path = base / "truth.json"
    truth_path.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    return src, parse_dir, truth_path


def selftest():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="run_combo_selftest_") as tmp:
        tmp = Path(tmp)
        src, parse_dir, truth_path = _build_fixture(tmp)
        out_dir = tmp / "out_eval"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        docs = sorted(p.name for p in src.iterdir())
        route = S.load_route(parse_dir)

        # 1) 앵커 — 값이 질의에 노출되면 안 됨
        ref_corpus, _ = S.load_corpus(parse_dir, docs, "route", route)
        anchors = A.build_anchors(ref_corpus, docs, truth=truth, seed=0, cap=10)
        assert anchors, "앵커가 하나도 안 만들어짐"
        for anc in anchors:
            assert S.normalize_value(anc["value"]) not in S.normalize_value(anc["query"]), f"질의에 값 노출: {anc}"
        print(f"[selftest] 앵커 {len(anchors)}개 — 값 비노출 확인")

        # 2) 엔진이 실패한 문서(doc2, engineB) → 그 문서 앵커는 전부 미스
        corpus_b, _ = S.load_corpus(parse_dir, docs, "engineB", route)
        assert corpus_b["doc2.txt"] == "", "engineB가 doc2를 실패했다고 가정했는데 텍스트가 있음"
        doc2_anchors = [a for a in anchors if a["doc"] == "doc2.txt"]
        assert doc2_anchors, "doc2 앵커가 없어 미스 테스트 불가"
        hits_dir = out_dir / "hits"
        ctx0 = {
            "parse_dir": parse_dir,
            "route": route,
            "docs": docs,
            "anchors": doc2_anchors,
            "truth": truth,
            "rerank": False,
            "cache_dir": out_dir / "cache",
            "hits_dir": hits_dir,
            "results_path": out_dir / "results.jsonl",
            "done": {},
            "beam": 2,
            "force": False,
        }
        combo_b = {"parse": "engineB", "chunk": "fixed512", "embed": "none", "retrieve": "bm25", "graph": "none"}
        r_doc2, hit_rows_doc2 = eval_combo(combo_b, ctx0)
        assert r_doc2["R"]["r10"] == 0.0, f"engineB 실패 문서(doc2)인데 적중함: {r_doc2['R']}"
        assert all(row["rank"] is None for row in hit_rows_doc2), "미스여야 하는데 hits에 rank가 있음"
        print("[selftest] 엔진 실패 문서 → 미스 확인")

        # 3) full 조합 — 명세가 지정한 작은 전체 곱(2 parse × 2 chunk × 2 embed × 2 graph × 4 retrieve)
        ctx = {
            "parse_dir": parse_dir,
            "route": route,
            "docs": docs,
            "anchors": anchors,
            "truth": truth,
            "rerank": False,
            "cache_dir": out_dir / "cache",
            "hits_dir": hits_dir,
            "results_path": out_dir / "results.jsonl",
            "done": load_done(out_dir / "results.jsonl"),
            "beam": 2,
            "force": False,
        }
        axes_full = {
            "parse": ["route", "engineB"],
            "chunk": ["fixed512", "structure"],
            "embed": ["none", "e5-small"],
            "graph": ["none", "entity"],
            "retrieve": ["bm25", "hybrid", "graph", "grep"],
        }
        t0 = time.perf_counter()
        res1 = run_full(ctx, axes_full)
        sec_full = time.perf_counter() - t0
        assert res1, "full 조합 결과가 하나도 없음"
        for combo, r in res1:
            assert r["R"]["r1"] <= r["R"]["r5"] <= r["R"]["r10"], f"R@k 단조성 깨짐: {combo} {r['R']}"
            hp = hits_dir / f"{combo_hash(combo)}.jsonl"
            assert hp.exists(), f"hits 파일 없음: {combo}"
            hit_lines = [ln for ln in hp.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert len(hit_lines) == r["n_anchors"], f"hits 줄 수 불일치: {combo} {len(hit_lines)} != {r['n_anchors']}"
            row0 = json.loads(hit_lines[0]) if hit_lines else {}
            assert set(row0) >= {"anchor_id", "rank", "top"}, f"hits 줄 형식 이상: {row0}"
        n1 = len(out_dir.joinpath("results.jsonl").read_text(encoding="utf-8").splitlines())
        assert all(
            "key" in json.loads(ln) for ln in out_dir.joinpath("results.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()
        ), "results.jsonl에 key 없는 줄이 있음"
        print(
            f"[selftest] full 조합 {len(res1)}개 평가({sec_full:.1f}s) — R@k 단조성·hits 파일(조합당 앵커 줄 수 일치)·key 필드 확인, results.jsonl {n1}줄"
        )

        # 4) resume — 재실행 시 새 줄이 붙으면 안 됨
        ctx["done"] = load_done(out_dir / "results.jsonl")
        res2 = run_full(ctx, axes_full)
        n2 = len(out_dir.joinpath("results.jsonl").read_text(encoding="utf-8").splitlines())
        assert n2 == n1, f"resume 실패 — 재실행에서 {n2 - n1}줄 추가됨"
        assert len(res2) == len(res1), "resume 후 결과 개수가 달라짐"
        print(f"[selftest] resume 확인 — 재실행 후에도 results.jsonl {n2}줄(추가 없음)")

        # 5) beam.json — 단계별 tau
        ctx["done"] = load_done(out_dir / "results.jsonl")
        axes_beam = {
            "parse": ["route", "engineB"],
            "chunk": ["fixed512", "structure"],
            "embed": ["none", "e5-small"],
            "graph": ["none", "entity"],
            "retrieve": ["bm25", "hybrid"],
        }
        beam_doc = run_beam(ctx, axes_beam)
        (out_dir / "beam.json").write_text(json.dumps(beam_doc, ensure_ascii=False, indent=1), encoding="utf-8")
        stage_axes = [s["axis"] for s in beam_doc["stages"]]
        assert stage_axes == ["+".join(x) for x in STAGES], f"beam 단계 순서가 다름: {stage_axes}"
        for s in beam_doc["stages"]:
            assert "tau" in s, f"{s['axis']} 단계에 tau 없음"
        assert beam_doc["stages"][0]["tau"] is None, "parse 단계는 상위 비교 대상이 없어 tau가 None이어야 함"
        n_hits = len(list(hits_dir.glob("*.jsonl")))
        assert n_hits > 0, "hits 폴더가 비어 있음"
        print(f"[selftest] beam.json 단계별 tau: {[(s['axis'], s['tau']) for s in beam_doc['stages']]} · hits 파일 {n_hits}개")

        print("[selftest] 전부 통과")


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
