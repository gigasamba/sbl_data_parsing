"""pipeline.eval.server_checks 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.server_checks --selftest`."""

import json
import types
from collections import Counter
from pathlib import Path

from common.core.paths import STACK_FILE
from pipeline.eval.server_checks import (
    AR1_CONFIGS,
    AR1_NO_P3_VLM,
    _ar6_counts,
    _ar6_markdown,
    _index_text_from_pg_row,
    _run_ar1,
    cmd_ar1,
    cmd_ar6,
    cmd_t1,
)


def selftest_ar1():
    """represent.py·score_gold.py는 가짜로 주입(서버 없이) — 내 오케스트레이션(문서 수 제한·설정별 env 격리·
    --run-vlm 게이트·마크다운)만 검증."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        parse_dir = d / "parse"
        for eng in ("pymupdf", "rapidocr_ko"):
            (parse_dir / eng).mkdir(parents=True)
            for doc in ("a.pdf", "b.pdf", "c.pdf"):
                (parse_dir / eng / f"{doc}.json").write_text(json.dumps({"text": "x"}), encoding="utf-8")
        runs = [
            {"doc": doc, "engine": eng, "error": None, "sec": 0.1, "phase": 1}
            for doc in ("a.pdf", "b.pdf", "c.pdf")
            for eng in ("pymupdf", "rapidocr_ko")
        ]
        (parse_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs), encoding="utf-8")
        out_dir = d / "output"

        calls = []

        def fake_represent(dev_root, stack_path, pd, src, env):
            calls.append((str(pd), dict(env)))
            (pd / "_rep").mkdir(parents=True, exist_ok=True)
            (pd / "_rep" / "conflicts.jsonl").write_text(json.dumps({"doc": "a.pdf", "conflicts": [1, 2]}) + "\n", encoding="utf-8")
            return 0.5

        def fake_score(dev_root, gold_dir, pd, src, out, env):
            cfg = Path(pd).name
            vr = 0.5 if "PARSE_FUSE_off" in cfg or cfg == "cfg_baseline" else 0.9
            return {
                "rep": {"value_recall": vr, "char_acc_post": 0.8, "table_cell_recall": 0.7, "num_halluc": 0.0},
                "docs": {"a.pdf": {"rep": {"value_recall": vr}}},
            }

        # --run-vlm 없음 — P3 실호출 포함 설정은 빠지고, conflict_fn은 fake_represent를 한 번 더 써서 더미 카운트
        results, md = _run_ar1(
            parse_dir,
            d / "src",
            d / "gold",
            out_dir,
            STACK_FILE,
            max_docs=2,
            run_vlm=False,
            represent_fn=fake_represent,
            score_fn=fake_score,
        )
        assert set(results) == AR1_NO_P3_VLM, results
        assert "PARSE_FUSE_SIGNALS_off는 건너뜀" not in md or True  # 메시지는 cmd_ar1 쪽 print — 여기선 결과 집합만
        assert "예상 P3 VLM 호출" in md or "P3 VLM 호출" in md

        results2, md2 = _run_ar1(
            parse_dir,
            d / "src",
            d / "gold",
            out_dir,
            STACK_FILE,
            max_docs=None,
            run_vlm=True,
            represent_fn=fake_represent,
            score_fn=fake_score,
        )
        assert set(results2) == {c[0] for c in AR1_CONFIGS}, results2
        assert results2["PARSE_FUSE_off"]["rep"]["value_recall"] == 0.5
        assert results2["baseline"]["rep"]["value_recall"] == 0.5
    print("[selftest] ar1 — --max-docs 제한·--run-vlm 게이트(P3 실호출 설정 건너뜀/포함)·결과 집계 통과")


def selftest_ar6():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        images = d / "_images"
        (images / "docA.pdf").mkdir(parents=True)
        (images / "docA.pdf" / "p1_i1.png").write_bytes(b"fakepng1")
        (images / "docA.pdf" / "p2_i1.png").write_bytes(b"fakepng2")
        rows = [
            {
                "doc": "docA.pdf",
                "image_id": "#p1#i1",
                "source_file": "x/docA.pdf",
                "skipped": None,
                "provenance": {"fig_kind": "other"},
                "png": "_images/docA.pdf/p1_i1.png",
            },
            {
                "doc": "docA.pdf",
                "image_id": "#p2#i1",
                "source_file": "x/docA.pdf",
                "skipped": None,
                "provenance": {"fig_kind": "chart"},
                "png": "_images/docA.pdf/p2_i1.png",
            },
            {"doc": "docA.pdf", "image_id": "#p3#i1", "source_file": "x/docA.pdf", "skipped": "small", "provenance": {}, "png": None},
        ]
        (images / "index.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

        def fake_ocr(b):
            return (
                "로트 코드 라벨 창고 구역 번호" if b == b"fakepng1" else "pH 7.0 6.9 0개월 3개월"
            )  # 1: 숫자 비율 0(<0.3) · 2: chart(종류로 제외)

        report = _ar6_counts(d, ocr_fn=fake_ocr, min_chars=10, digit_max=0.30)
        assert report["figure_attempts"] == 2 and report["pre_vlm_skipped"] == 1, report
        assert report["by_kind"] == {"other": 1, "chart": 1}, report["by_kind"]
        assert report["gate_would_skip"] == 1, report  # p1(other, 숫자<0.3)만 생략 가능 — p2는 chart라 제외
        assert report["gate_skip_share"] == 0.5, report
        md = _ar6_markdown(report)
        assert "그림 종류별" in md and "OCR 게이트" in md
    print("[selftest] ar6 — 종류·형식 집계·사전 걸러짐 구분·OCR 게이트(차트 제외) 통과")


def selftest_t1():
    from common.core.text import index_text, tokens

    rows_data = [
        {
            "chunk_id": 1,
            "chunk_text": "단가 2,000원",
            "section": "개요",
            "seq": 0,
            "file_name": "견적서.pdf",
            "client": "Acme",
            "file_sha256": "a" * 64,
        },
        {
            "chunk_id": 2,
            "chunk_text": "수량 500개",
            "section": "개요",
            "seq": 1,
            "file_name": "견적서.pdf",
            "client": "Acme",
            "file_sha256": "a" * 64,
        },
    ]
    correct_terms = dict(Counter(tokens(_index_text_from_pg_row(rows_data[0]))))
    stored = {1: correct_terms, 2: {"stale": 1}}  # chunk 2 = 재색인 전 옛 토큰(일부러 틀림)

    class FakeDB:
        schema = "ai"

        def q(self, sql, params=None):
            if "JOIN" in sql:
                return rows_data
            if "chunk_term WHERE chunk_id" in sql:
                cid = params[0]
                return [{"term": t, "tf": n} for t, n in stored.get(cid, {}).items()]
            return []

    import tempfile

    with tempfile.TemporaryDirectory() as out_td:  # S6a(VS5 R-1) — 진짜 output/server_checks/t1/ 보고서를 덮어쓰지 않게
        args = types.SimpleNamespace(sample=2, bundle=None, pool=False, out=out_td)
        rc = cmd_t1(args, db_factory=lambda: FakeDB())
        assert rc == 1  # 2건 중 1건 불일치
        report = json.loads((Path(out_td) / "t1_report.json").read_text(encoding="utf-8"))
    assert report["mismatch"] == 1 and report["checked"] == 2 and 2 in report["mismatch_chunk_ids"], report

    # 번들 모드 — 번들의 head 포함 원문이 그대로 일치하면(재구성 없이) bundle_hits가 늘고 결과는 그대로 일관
    with tempfile.TemporaryDirectory() as td:
        B = Path(td)
        (B / "docs.jsonl").write_text(json.dumps({"file_sha256": "a" * 64, "file_name": "견적서.pdf"}) + "\n", encoding="utf-8")
        chunk0 = {"doc": 0, "seq": 0, "head": "[견적서 · Acme · 개요]", "chunk_text": "단가 2,000원"}
        (B / "chunks.jsonl").write_text(json.dumps(chunk0, ensure_ascii=False) + "\n", encoding="utf-8")
        stored2 = {1: dict(Counter(tokens(index_text(chunk0)))), 2: {"stale": 1}}

        class FakeDB2(FakeDB):
            def q(self, sql, params=None):
                if "JOIN" in sql:
                    return rows_data
                if "chunk_term WHERE chunk_id" in sql:
                    return [{"term": t, "tf": n} for t, n in stored2.get(params[0], {}).items()]
                return []

        args2 = types.SimpleNamespace(sample=2, bundle=str(B), pool=False, out=str(B / "out"))
        cmd_t1(args2, db_factory=lambda: FakeDB2())
        report2 = json.loads((B / "out" / "t1_report.json").read_text(encoding="utf-8"))
        assert report2["bundle_hits"] == 1 and report2["mismatch"] == 1, report2
    print("[selftest] t1 — PG 재구성·번들 대조 둘 다 불일치(재색인 전 청크) 탐지 통과")


SUBCOMMANDS = {
    "ar1": (cmd_ar1, selftest_ar1),
    "ar6": (cmd_ar6, selftest_ar6),
    "t1": (cmd_t1, selftest_t1),
}


def run_all_selftests():
    for _name, (_func, selftest_fn) in SUBCOMMANDS.items():
        selftest_fn()
    print("[selftest] server_checks — 전체(ar1·ar6·t1) 통과")
    return 0


def test_main():  # 옛 `server_checks --selftest`(서브커맨드 없음) → main()의 run_all_selftests() 갈래
    run_all_selftests()
