"""pipeline.eval.report 자기 점검 — S9(D-018)에 모듈에서 옮김(함수 몸통 글자 그대로). 옛 사례 `python -m pipeline.eval.report --selftest`."""

import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from pipeline.eval.report import TAB_DEFS, _wcsv, build_report


def _wj(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _wl(p, lines):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")


def _fixture_criteria(tmp):
    p = tmp / "criteria.json"
    _wj(
        p,
        {
            "groups": {"native": [".docx"], "image": [".png"]},
            "parse": [{"id": "P0", "name": "처리율", "metric": "ok_rate", "dir": ">=", "native": 1.0, "image": 1.0, "desc": "d"}],
            "parse_reference_free": [{"id": "F1", "name": "빈 출력", "rule": "r"}],
            "chunk": [{"id": "C2", "name": "근거 온전율", "metric": "evidence_intact", "dir": ">=", "value": 0.9, "desc": "d"}],
            "retrieve": [
                {"id": "R5", "name": "R@5", "metric": "r5", "dir": ">=", "value": 0.9, "desc": "d"},
                {"id": "RM", "name": "MRR", "metric": "mrr", "dir": ">=", "value": 0.7, "desc": "d"},
                {"id": "RC", "name": "ctx5", "metric": "ctx5", "dir": "<=", "value": 6000, "desc": "d"},
            ],
            "graph": [{"id": "G2", "name": "앵커경로", "metric": "anchor_path", "dir": ">=", "value": 0.9, "desc": "d"}],
            "answer": [{"id": "A1", "name": "수치정답률", "metric": "num_acc", "dir": ">=", "value": 0.95, "desc": "d"}],
        },
    )
    return p


def _fixture_full(tmp):
    out = tmp / "full_out"
    catalog, server = tmp / "catalog.json", tmp / "server.json"
    criteria = _fixture_criteria(tmp)
    injected_doc = "<script>alert(1)</script>.png"
    _wj(
        catalog,
        {
            "version": "t",
            "source": "selftest",
            "evidence_legend": {"vendor": "벤더 발표"},
            "license_policy": {
                "exclude": [{"rule": "비상업 전용 가중치", "example": "MonkeyOCR"}],
                "conditional": [{"rule": "AGPL", "obligation": "소스 공개 또는 상용 라이선스 구매"}],
                "allowed": "MIT · Apache-2.0 · BSD",
            },
            "steps": [
                {
                    "id": "step_parse",
                    "title": "파싱",
                    "layers": ["parse"],
                    "kind": "엔진 비교",
                    "relation": "청킹 입력",
                    "shortlist": [injected_doc],
                    "shortlist_basis": "값 재현율 1위",
                }
            ],
            "layers": [
                {
                    "id": "parse",
                    "title": "파싱",
                    "desc": "d",
                    "techs": [
                        {
                            "name": injected_doc,
                            "adopted": True,
                            "engines": ["eng_a"],
                            "strengths": "s",
                            "weaknesses": "w",
                            "perf": "p",
                            "note": "n",
                            "evidence": "vendor",
                            "license": "MIT",
                            "license_status": "사용 가능",
                            "license_reason": "허용 목록",
                            "bench": [
                                {
                                    "bench": "B1",
                                    "lang": "en",
                                    "metric": "f1",
                                    "value": 0.9,
                                    "kind": "벤더 발표",
                                    "source": "https://example.com/b1",
                                },
                                {"bench": "B2", "lang": "ko", "metric": "cer", "value": 0.05, "kind": "독립", "source": "sheet"},
                            ],
                            "dummy": "표 구조 복원됨",
                            "tuning": "부분",
                            "tuning_left": "해상도 튜닝 남음",
                            "candidate": "운영",
                        },
                        {
                            "name": "eng_a_tech",
                            "adopted": False,
                            "engines": [],
                            "strengths": "s2",
                            "weaknesses": "w2",
                            "perf": "",
                            "note": "",
                            "evidence": "주장",
                            "license": "비상업 전용",
                            "license_status": "제외",
                            "license_reason": "비상업 전용 가중치",
                            "bench": [],
                            "dummy": "",
                            "tuning": "해당 없음",
                            "tuning_left": "",
                            "candidate": "제외",
                        },
                    ],
                }
            ],
        },
    )
    _wj(
        server,
        {
            "checked": "2026-09-29",
            "models": [
                {
                    "as_written": "m1",
                    "official_name": "Model One",
                    "role": "VLM",
                    "release": "r",
                    "params_total": "1B",
                    "params_active": "1B",
                    "vision": True,
                    "context": "1024",
                    "license": "MIT",
                    "quant": {"format": "fp8", "hardware": "h100", "weight_mem_gb": "10"},
                    "scores": [
                        {
                            "bench": "B1",
                            "lang": "ko",
                            "metric": "score",
                            "value": 90,
                            "kind": "벤더 발표",
                            "source": "https://example.com/m1",
                        }
                    ],
                    "weaknesses": ["w1"],
                    "pipeline_role": "OCR 엔진",
                }
            ],
            "env": [{"item": "GPU", "value": "B200", "source": "https://example.com/env"}],
            "unresolved": ["u1"],
            "verification": {"verdict": "검증됨", "by": "security", "items": ["ok"]},
        },
    )
    _wl(out / "parse" / "runs.jsonl", [{"doc": "doc2.docx", "engine": "eng_a", "format": ".docx", "ok": True, "sec": 0.2}])
    _wj(
        out / "parse" / "qa.json",
        {
            "meta": {"source": "selftest_src"},
            "docs": {
                injected_doc: {
                    "format": ".png",
                    "group": "image",
                    "pages": 1,
                    "ref": "consensus",
                    "ref_chars": 100,
                    "engines": {
                        "eng_a": {
                            "ok": True,
                            "sec": 0.4,
                            "chars": 95,
                            "lines": 10,
                            "tables": 0,
                            "nums": 3,
                            "ko_ratio": 0.8,
                            "garbage": 0.0,
                            "len_ratio": 0.95,
                            "consensus_recall": 0.9,
                            "cer": 0.02,
                            "value_recall": 0.9,
                            "num_halluc": 0.01,
                            "table_row_recall": 0.0,
                            "order": 0.9,
                            "diff": [["기준줄1", "출력줄1"], ["기준줄2", None]],
                        }
                    },
                },
                "doc2.docx": {
                    "format": ".docx",
                    "group": "native",
                    "pages": 2,
                    "ref": "native",
                    "ref_chars": 200,
                    "engines": {
                        "eng_a": {
                            "ok": True,
                            "sec": 0.2,
                            "chars": 190,
                            "cer": 0.01,
                            "value_recall": 0.99,
                            "num_halluc": 0.0,
                            "table_row_recall": 0.95,
                            "order": 0.95,
                            "len_ratio": 1.0,
                            "ko_ratio": 0.7,
                            "garbage": 0.0,
                            "diff": [],
                        }
                    },
                },
            },
            "engines": {
                "eng_a": {
                    "image": {
                        "ok_rate": 1.0,
                        "cer": 0.02,
                        "value_recall": 0.9,
                        "num_halluc": 0.01,
                        "table_row_recall": 0.0,
                        "order": 0.9,
                        "sec": 0.4,
                        "pass": {"P0": True},
                    },
                    "native": {
                        "ok_rate": 1.0,
                        "cer": 0.01,
                        "value_recall": 0.99,
                        "num_halluc": 0.0,
                        "table_row_recall": 0.95,
                        "order": 0.95,
                        "sec": 0.2,
                        "pass": {"P0": True},
                    },
                }
            },
        },
    )
    _wj(out / "parse" / "route.json", {".png": ["eng_a"], ".docx": ["eng_a"]})
    _wcsv(
        out / "dedup" / "groups.csv",
        ["group", "file", "representative", "reasons", "sha256", "size", "decision"],
        [["g1", "doc2.docx", "doc2.docx", "", "abc", "100", "keep"]],
    )
    _wcsv(
        out / "prepared" / "rotation.csv",
        ["file", "page", "angle", "s0", "s90", "s180", "s270"],
        [
            [injected_doc, "1", "90", "0.1", "0.9", "0.05", "0.02"],
            ["doc2.docx", "1", "0", "1", "0", "0", "0"],
            ["doc2.docx", "2", "0", "1", "0", "0", "0"],
        ],
    )
    _wj(out / "corpus" / "truth.json", {})
    _wl(out / "eval" / "anchors.jsonl", [{"id": "a1", "doc": "doc2.docx", "label": "L", "value": "V", "query": "q", "source": "truth"}])
    row1 = {
        "combo": {"parse": "route", "chunk": "fixed512", "embed": "none", "graph": "none", "retrieve": "bm25"},
        "stage": "chunk",
        "C": {"n": 10, "mean": 500, "p95": 600, "evidence_intact": 0.96, "table_split": 0.02},
        "R": {"r1": 0.5, "r5": 0.92, "r10": 0.95, "mrr": 0.75, "ctx5": 4000, "p50_ms": 10, "p95_ms": 20},
        "G": {},
        "n_anchors": 5,
        "sec": 1.2,
    }
    row2 = {
        "combo": {"parse": "route", "chunk": "fixed512", "embed": "e5-small", "graph": "struct", "retrieve": "hybrid"},
        "stage": "combo",
        "C": {"n": 10, "mean": 500, "p95": 600, "evidence_intact": 0.97, "table_split": 0.0},
        "R": {"r1": 0.6, "r5": 0.95, "r10": 0.97, "mrr": 0.8, "ctx5": 3000, "p50_ms": 12, "p95_ms": 25},
        "G": {"nodes": {"chunk": 50, "doc": 2}, "edges": {"adjacent": 40}, "anchor_path": 0.92, "isolated": 0.05, "load_sec": 0.8},
        "n_anchors": 5,
        "sec": 2.0,
    }
    row3 = {
        "combo": {"parse": "route2", "chunk": "recursive", "embed": "bge-m3", "graph": "none", "retrieve": "dense"},
        "stage": "combo",
        "C": {},
        "R": {"r1": 0.4, "r5": 0.7, "r10": 0.8, "mrr": 0.5, "ctx5": 5000, "p50_ms": 15, "p95_ms": 30},
        "G": {},
        "n_anchors": 5,
        "sec": 1.5,
    }
    _wl(out / "eval" / "results.jsonl", [row1, row2, row3])
    _wj(out / "eval" / "beam.json", {"parse": {"candidates": ["route", "route2"], "selected": ["route"], "tau": 0.8, "widened": False}})
    _wl(out / "eval" / "answers.jsonl", [{"num_acc": 1.0, "cite_acc": 0.9, "abstain_ok": 1.0}])
    return out, catalog, server, criteria


def _fixture_missing(tmp):
    out = tmp / "miss_out"
    _wl(out / "parse" / "runs.jsonl", [{"doc": "doc2.docx", "engine": "eng_a", "format": ".docx"}])
    _wcsv(out / "dedup" / "groups.csv", ["group", "file", "representative", "reasons", "sha256", "size", "decision"], [])
    _wcsv(
        out / "prepared" / "rotation.csv",
        ["file", "page", "angle", "s0", "s90", "s180", "s270"],
        [["doc2.docx", "1", "0", "1", "0", "0", "0"]],
    )
    return out


def _assert_no_bad_links(html_out):
    for m in re.finditer(r"https?://[^\s\"'<>]+", html_out):
        pre = html_out[max(0, m.start() - 100) : m.start()]
        assert 'href="' in pre or "href='" in pre, f"href 밖의 http(s) 참조: ...{html_out[max(0, m.start() - 30) : m.start() + 30]}..."


def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="report_selftest_"))
    try:
        full_out, catalog_p, server_p, criteria_p = _fixture_full(tmp)
        html_full = build_report(str(full_out), str(catalog_p), str(server_p), str(criteria_p), "테스트 보고서")
        miss_out = _fixture_missing(tmp)
        html_miss = build_report(
            str(miss_out), str(tmp / "nope_catalog.json"), str(tmp / "nope_server.json"), str(criteria_p), "테스트 보고서"
        )

        exp_ids = [t[0] for t in TAB_DEFS]
        ids_full = re.findall(r'data-tab="([a-z0-9\-]+)"', html_full)
        ids_miss = re.findall(r'data-tab="([a-z0-9\-]+)"', html_miss)
        assert ids_full == exp_ids, f"탭 순서 불일치(정상): {ids_full}"
        assert ids_miss == exp_ids, f"탭 순서 불일치(결손): {ids_miss}"
        assert "미실행" in html_miss, "결손 실행에 '미실행' 문구 없음"

        raw_payload = "<script>alert(1)</script>"
        assert raw_payload not in html_full, "스크립트 인젝션이 이스케이프되지 않음"
        assert html.escape(raw_payload) in html_full, "이스케이프된 페이로드를 찾지 못함"

        _assert_no_bad_links(html_full)
        _assert_no_bad_links(html_miss)

        assert "단계별 요약" in html_full, "기술 스택 절에 단계별 요약 없음"
        assert "검토 스택 수" in html_full, "단계별 요약 표 열 없음"
        assert '<span class="badge cand-excl">제외</span>' in html_full, "제외 후보 배지 렌더 실패"
        assert "muted-row" in html_full, "제외 행 음영(muted-row) 클래스 없음"
        assert "라이선스 판정 기준" in html_full, "라이선스 판정 기준 박스 없음"

        print("PASS: 14개 탭 id·순서 일치(정상·결손 실행 모두)")
        print("PASS: 결손 실행 절 7~11 등에서 '미실행' 노출 확인")
        print("PASS: <script> 인젝션 이스케이프 확인 (원문 없음, 이스케이프문 있음)")
        print("PASS: http(s) 참조는 href 인용 안에만 존재")
        print("PASS: 기술 스택 절 — 단계별 요약 표·라이선스 판정 기준·제외 배지·음영 행 렌더 확인")
        print(f"생성 파일 크기(정상): {len(html_full.encode('utf-8')):,} bytes")
        print(f"생성 파일 크기(결손): {len(html_miss.encode('utf-8')):,} bytes")
        return True
    except AssertionError as e:
        print(f"FAIL: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_main():  # 옛 main()의 `if args.selftest:` 갈래
    sys.exit(0 if selftest() else 1)
