"""pipeline.eval.run_board 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.run_board --selftest`."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from pipeline.eval.run_board import _fixture, build, digest, issue_files, write_issue_csv


def selftest():
    with tempfile.TemporaryDirectory() as td:
        t = _fixture(td)
        h, a, _ = build(t)
        iss = {d: v for d, v in a["issue"].items()}
        assert iss["계약서_A_사본.docx"][1] == "policy" and iss["견적서_10.pdf"][1] == "encrypted", iss  # DRM = 원본 문제(사람 조치)
        assert iss["자료모음.zip"][:2] == ("prepare", "unsupported"), iss  # zip = 파싱 대상 아님
        assert iss["단가표_보호.xlsx"][:2] == ("parse", "encrypted") and "암호" in iss["단가표_보호.xlsx"][2], (
            iss
        )  # 엔진 4종 메시지가 다 달라도
        assert iss["스캔본_깨짐.pdf"][:2] == ("parse", "corrupt") and iss["이상한.pdf"][1] == "fail", iss  # 전부 동의할 때만 원본 문제
        rows = issue_files(a, t)
        assert {r[0] for r in rows} == {"견적서_10.pdf", "자료모음.zip", "단가표_보호.xlsx", "스캔본_깨짐.pdf"}, rows
        assert "원본 문제 4건" in h and "issue_files.csv" in h
        write_issue_csv(rows, t / "report" / "issue_files.csv")
        assert "단가표_보호.xlsx" in (t / "report" / "issue_files.csv").read_text(encoding="utf-8-sig")
        assert iss["견적서_09.pdf"][:2] == ("parse", "timeout") and iss["견적서_08.pdf"][:2] == ("parse", "fail"), iss
        assert iss["견적서_03.pdf"][:2] == ("qa", "acc") and iss["계약서_A.docx"][1] == "nojudge", iss
        assert iss["견적서_07.pdf"][:2] == ("bundle", "noout"), iss  # 대표는 있는데 색인에 없음
        dd = {s["key"]: s["c"] for s in a["stages"]}["dedup"]
        assert (dd["ok"], dd["policy"], dd["review"]) == (11, 1, 1), dd  # 확인 필요는 파싱 계속(건너뜀 아님)
        assert "견적서_03.pdf" in iss and iss["견적서_03.pdf"][0] == "qa"  # 확인 필요가 뒤 단계 문제를 가리지 않음
        assert a["blocked"] is None and {s["key"]: s["st"] for s in a["stages"]}["parse"] == "dev"
        assert "견적서" not in h and "단가표" not in h and "doc-" in h  # 기본 해시 이름(원본 문제 표도)
        assert "소요 시간" in h and "병목" in h and a["timing"]["eng"]
        assert "phase 2" in a["phases"] and a["phases"]["phase 2"]["ok"] and 'class="keys"' in h  # phase별·핵심 이슈
        assert "형식별 교차 판정" in h and "연결 안 된 엔진" in h and "paddleocr" in a["env_eng"]  # 옛 phase 보고서 표를 실행판에(10-08)
        dg = digest(Path(td) / "digest", h, a, {}, str(t), when=datetime(2026, 10, 8, 9, 0))
        sj = json.loads((dg / "summary.json").read_text(encoding="utf-8"))
        assert (
            dg.name.startswith("2026-10-08__")
            and (dg / "run_board.html").exists()
            and sj["docs"] == len(a["docs"])
            and "phase 2" in sj["phases"]
        )
        assert sj["source_issues"] == {"암호·DRM": 2, "미지원 형식": 1, "손상 의심": 1} and (dg / "issue_files.csv").exists(), sj.get(
            "source_issues"
        )
        assert "견적서" not in json.dumps(sj, ensure_ascii=False) and "| 2026-10-08 09:00 |" in (
            Path(td) / "digest" / "INDEX.md"
        ).read_text(encoding="utf-8")
        (t / "edw" / "bundle" / "meta.json").unlink()
        (t / "edw" / "bundle" / "docs.jsonl").unlink()
        Path(t / "runlog.jsonl").write_text(
            json.dumps({"tool": "bundle", "status": "오류", "error": "ImportError"}) + "\n", encoding="utf-8"
        )
        h2, a2, _ = build(t)
        assert a2["blocked"] == "bundle" and "막힘" in h2, a2["blocked"]
        h3, _, _ = build(Path(td) / "없음")
        assert "읽을 결과가 없음" in h3
    with tempfile.TemporaryDirectory() as td2:  # SI23 — 두 번 실행 기록이 섞인 runs.jsonl → 이번 run_id만(엔진 범위가 바뀐 두 번째 실행)
        t2 = Path(td2)
        (t2 / "parse" / "_rep").mkdir(parents=True)
        runs = [
            {"doc": "a.pdf", "engine": "engA", "sec": 1, "error": None, "run_id": "20261001-010000"},
            {"doc": "a.pdf", "engine": "engB", "sec": 1, "error": None, "run_id": "20261001-010000"},
            {"doc": "a.pdf", "engine": "engC", "sec": 1, "error": None, "run_id": "20261002-020000"},
        ]
        (t2 / "parse" / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
        (t2 / "parse" / "_rep" / "_DONE.json").write_text(json.dumps({"run_id": "20261002-020000"}), encoding="utf-8")
        _, a3, _ = build(t2)
        assert set(a3["eng"]) == {"engC"}, a3["eng"]  # 이번 run_id(engC)만 — 옛 실행(engA·engB)은 안 보임
        _, a4, _ = build(t2, all_runs=True)
        assert set(a4["eng"]) == {"engA", "engB", "engC"}, a4["eng"]  # --all-runs = 전체(옛 동작)
    with tempfile.TemporaryDirectory() as td3:  # run_id 칸 없는 옛 형식 runs.jsonl → 폴백(문서×엔진마다 마지막 기록만, 지금까지 동작)
        t3 = Path(td3)
        (t3 / "parse").mkdir(parents=True)
        runs = [
            {"doc": "a.pdf", "engine": "engA", "sec": 1, "error": None},
            {"doc": "a.pdf", "engine": "engA", "sec": 2, "error": "TimeoutError: x"},
        ]
        (t3 / "parse" / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
        _, a5, _ = build(t3)
        assert a5["eng"]["engA"]["timeout"] == 1 and not a5["eng"]["engA"]["ok"], a5[
            "eng"
        ]  # 마지막 줄(시간 초과) 기준 — run_id 없어 거르지 않음
    print(
        "selftest OK — 원본 문제(암호 4종 메시지·DRM·zip·손상, 전부 동의할 때만)·issue_files.csv · 핵심 타일·이슈·phase별 · --digest(날짜·판 폴더·summary.json 해시 이름·INDEX) · 정책 건너뜀·환경·시간 초과·예외·정확도·판정 불가·색인 누락 분류 · 막힌 곳(도구 오류) · 빈 폴더 · 해시 이름"
        " · SI23 run_id 거르기(옛 실행 섞임·--all-runs·run_id 없는 옛 형식 폴백)"
    )


def test_main():  # 옛 main()의 `if a.selftest:` 갈래
    selftest()
