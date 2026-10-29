#!/usr/bin/env python3
"""파싱 결과 요약 (정답지 없이) → output/parse/summary.md · engines.csv · docs.csv

엔진별: 성공·실패·시간 초과 · 평균/중앙 시간 · 표·facts·글자 수 · **다수 합의 수치 재현율**(참고용).
문서별: 형식 · 성공 엔진 수 · 최대 글자 수(0에 가까우면 스캔 의심) · 전 엔진 실패 여부.

다수 합의 수치 = 한 문서에서 **서로 다른 인식 계열(FAMILY)** 3개 이상이 뽑은 숫자 토큰. 같은 모델·같은 텍스트 레이어를 쓰는
엔진은 같은 곳에서 같이 틀리므로 1표로 센다. **정답이 아니다** — 쉬운 값의 공통분모일 뿐이고 모든 엔진이 놓친 값은 없다.
스택 비교의 1차 신호로만 쓰고, 성능 판정은 정답지 이후에.
사용: python modules/parse/summarize.py [--out output/parse] [--min-stacks 3]
"""

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT  # 폴더 재편 뒤 이 상수만 바뀌면 됨
from pipeline.extract.engines import registry

# 인식 계열: 같은 인식 모델(또는 같은 텍스트 레이어 추출기)을 쓰는 엔진 묶음. 목록에 없으면 스택 이름이 계열.
FAMILY = {
    # 이미지 인식 모델
    "paddleocr": "paddle",
    "rapidocr": "paddle",
    "rapidocr_ko": "paddle",
    "paddleocr_vl": "paddle-vl",
    "ocr_vlm": "ocr-vlm",
    "ppstructure": "paddle",
    "mineru": "paddle",  # RapidOCR = Paddle 모델 ONNX
    "tesseract": "tesseract",
    "unstructured_ocr": "tesseract",
    "kreuzberg_ocr": "tesseract",
    "tika": "tesseract",
    "easyocr": "easyocr",
    "docling_ocr": "easyocr",  # Docling OCR 기본 = EasyOCR
    "marker": "surya",
    "qwen_vlm": "qwen",
    "docling_vlm": "qwen",
    "marker_llm": "qwen",
    # 텍스트 레이어 추출기
    "pdfplumber": "pdfminer",
    "markitdown": "pdfminer",
    "unstructured": "pdfminer",
    "camelot": "pdfminer",
    "dual_local": "pdfminer",
    "pymupdf": "mupdf",
    "pymupdf4llm": "mupdf",
}

_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def nums(res):
    """출력의 숫자 토큰(쉼표 제거, 1자리 정수·연도처럼 흔한 값도 포함 — 참고 지표라 단순하게)."""
    text = res.get("text", "") + " " + " ".join(t.get("text", "") for t in res.get("tables") or [])
    return {x.replace(",", "") for x in _NUM.findall(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "parse"))
    ap.add_argument("--min-stacks", type=int, default=3, help="합의로 셀 최소 인식 계열 수")
    a = ap.parse_args()
    out = Path(a.out)
    runs = {}
    for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        runs[(r["doc"], r["engine"])] = r  # 같은 쌍을 다시 돌렸으면 마지막 기록
    eng_stack = {e: s for e, (s, _) in registry.engines().items()}
    eng_fam = {e: FAMILY.get(e, s) for e, s in eng_stack.items()}
    res, per_doc_nums = {}, defaultdict(dict)
    for (doc, eng), r in runs.items():
        f = out / eng / (doc + ".json")
        if not r["error"] and f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            res[(doc, eng)] = d
            per_doc_nums[doc][eng] = nums(d)
    consensus = {}
    for doc, by_eng in per_doc_nums.items():
        stacks_of = defaultdict(set)
        for eng, ns in by_eng.items():
            for n in ns:
                stacks_of[n].add(eng_fam.get(eng, eng))
        consensus[doc] = {n for n, s in stacks_of.items() if len(s) >= a.min_stacks}

    rows = []
    for eng in sorted({e for _, e in runs}):
        rs = [r for (d, e), r in runs.items() if e == eng]
        ok = [r for r in rs if not r["error"]]
        secs = [r["sec"] for r in ok]
        hit = tot = 0
        for (doc, e), _d in res.items():
            if e == eng and consensus.get(doc):
                hit += len(per_doc_nums[doc][eng] & consensus[doc])
                tot += len(consensus[doc])
        mine = [d for (doc, e), d in res.items() if e == eng]
        rows.append(
            {
                "engine": eng,
                "stack": eng_stack.get(eng, "?"),
                "family": eng_fam.get(eng, "?"),
                "docs": len(rs),
                "ok": len(ok),
                "timeout": sum("Timeout" in (r["error"] or "") for r in rs),
                "missing": sum(any(k in (r["error"] or "") for k in ("미설치", "미설정")) for r in rs),
                "fail": sum(bool(r["error"]) for r in rs),
                "sec_mean": round(statistics.mean(secs), 2) if secs else "",
                "sec_median": round(statistics.median(secs), 2) if secs else "",
                "tables": sum(len(d.get("tables") or []) for d in mine),
                "facts": sum(len(d.get("facts") or []) for d in mine),
                "chars": sum(len(d.get("text", "")) for d in mine),
                "consensus_recall": f"{hit}/{tot} ({hit / tot:.0%})" if tot else "",
                "unverified": rs[0].get("unverified", False),
            }
        )
    with (out / "engines.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    docs = []
    for doc in sorted({d for d, _ in runs}):
        ok_engs = [e for (d, e) in res if d == doc]
        docs.append(
            {
                "doc": doc,
                "format": Path(doc).suffix.lower(),
                "engines_ok": len(ok_engs),
                "engines_run": sum(1 for (d, _) in runs if d == doc),
                "max_chars": max((len(res[(doc, e)].get("text", "")) for e in ok_engs), default=0),
                "consensus_nums": len(consensus.get(doc, ())),
                "all_failed": not ok_engs,
            }
        )
    with (out / "docs.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(docs[0]))
        w.writeheader()
        w.writerows(docs)

    fmt = Counter(d["format"] for d in docs)
    md = [
        f"# 파싱 결과 요약 — 문서 {len(docs)}개 · 엔진 {len(rows)}종",
        "",
        "형식: " + ", ".join(f"{k} {v}" for k, v in fmt.most_common()),
        "",
        f"다수 합의 수치 재현율 = 서로 다른 인식 계열 {a.min_stacks}개 이상이 뽑은 숫자 중 이 엔진이 뽑은 비율. **정답 아님(참고)**.",
        "",
        "| 엔진 | 스택 | 계열 | 성공/실행 | 시간 초과 | 미설치·미설정 | 평균 s | 표 | facts | 다수 합의 수치 | 미실측 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    md += [
        f"| {r['engine']} | {r['stack']} | {r['family']} | {r['ok']}/{r['docs']} | {r['timeout']} | {r['missing']} | {r['sec_mean']} | {r['tables']} | "
        f"{r['facts']} | {r['consensus_recall']} | {'예' if r['unverified'] else ''} |"
        for r in rows
    ]
    visual = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    bad = [d for d in docs if d["all_failed"] or (d["format"] in visual and d["max_chars"] < 200)]
    md += [
        "",
        f"## 확인 필요 문서 {len(bad)}개 (전 엔진 실패, 또는 PDF·이미지인데 최대 글자 수 < 200 — 글자가 거의 없거나 모든 엔진이 못 읽음)",
        "",
    ]
    md += [f"- {d['doc']} — 성공 {d['engines_ok']}/{d['engines_run']}, 최대 {d['max_chars']}자" for d in bad] or ["- 없음"]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("summarize"):
        main()
