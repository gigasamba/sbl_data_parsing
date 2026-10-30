#!/usr/bin/env python3
"""phase 결과 리포트 → output/parse/PHASE_REPORT.md — 10-29 phase 없앰: run_all이 더는 부르지 않고 옛 phase 기록(runs.jsonl의 phase 칸)
요약용으로만 남음(새 기록은 phase '-'). 오류 분류(kind·FIX)는 실행판(run_board)이 씀.

  A. phase별 결과(시도·성공·다음 phase로 넘김·실패·환경)          B. 다음 phase 대기 목록(문서 × 엔진 · 쪽 · 제한 · 걸린 시간)
  C. 연결되지 않는 엔진 이슈(원인 분류 · 오류 · 조치 · 영향 문서)    D. 기준점과 사람 검토 목록 — 정답이 없는 실데이터용:
     문서마다 여러 엔진 결과 중 **인식 계열 합의 수치를 가장 많이 담고(동률이면 더 많이 읽은)** 엔진을 기준으로 삼고,
     자동 판정이 어려운 문서를 사유와 함께 사람 검토 목록으로. 개발 PC(가상 문서)는 truth가 기준.
  함께 갱신: output/parse/qa.json · route.json(modules/parse/parse_qa.py와 같은 계산) → cli/report.py가 그대로 읽음.
직접 실행: python modules/parse/phase_report.py [--src output/prepared] [--out output/parse] [--truth output/corpus/truth.json]
"""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from common.config import settings as C  # common 칸(DOC_DIR, S7c)
from common.core.console import utf8_stdout
from common.core.paths import (
    APP_ROOT,  # 폴더 재편 뒤 이 상수만 바뀌면 됨
    atomic_write_text,  # RV6, tmp+os.replace 공용
)
from pipeline.shared.progress import doc_types, status
from pipeline.shared.summarize import nums

VLM = {"qwen_vlm", "docling_vlm", "marker_llm"}  # 값을 지어낼 수 있는 계열
# 연결 안 되는 엔진 → 조치 (SETUP.md 기준)
FIX = {
    "tesseract": "dnf(EPEL 9): tesseract + TESSDATA_PREFIX=<dev>/assets/tessdata",
    "unstructured_ocr": "tesseract 설치(위와 같음)",
    "kreuzberg_ocr": "tesseract 설치(위와 같음)",
    "tika": "pip tika + Tika 서버(docker apache/tika, TIKA_SERVER_ENDPOINT)",
    "opendataloader": "Java 11+ (java가 PATH에)",
    "mineru": ".venv-mineru + MINERU_BIN",
    "marker": "marker 2.x 이미지 OCR은 llama-server(llama.cpp) 필요 — 텍스트 PDF만이면 무시",
    "paddleocr": ".env PADDLE_PYTHON=.venv-paddle/bin/python(절대 경로) — run_all이 자동으로 그 venv 사용",
    "ppstructure": ".env PADDLE_PYTHON(위와 같음)",
    "paddleocr_vl": ".env PADDLE_PYTHON(위와 같음, 모델 큼)",
    "qwen_vlm": ".env VLM_BASE_URL · VLM_MODEL(내부망)",
    "docling_vlm": ".env VLM_BASE_URL · VLM_MODEL",
    "marker_llm": ".env VLM_BASE_URL · VLM_MODEL",
    "msg_extract": "pip extract-msg",
}


def kind(err):
    e = err or ""
    if "환경변수 미설정" in e:
        return "설정(.env)"
    if "미설치" in e or "ModuleNotFound" in e:
        return "파이썬 모듈 미설치"
    if any(k in e for k in ("URLError", "Connection", "refused", "timed out")):
        return "서버 연결"
    return "시스템 실행 파일·모델"


def write_phase_report(src, out, engines="", phase=0, truth=None, text_only=False):
    """PHASE_REPORT.md 갱신(+ qa.json·route.json·parse_summary). text_only=True면 md 파일은 안 쓰고 글만 돌려줌
    (OP23 — 실행판 run_board가 옛 보고서를 대신, qa·route 계산은 그대로)."""
    src, out = Path(src), Path(out)
    recs = (
        [json.loads(x) for x in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        if (out / "runs.jsonl").exists()
        else []
    )
    last = {}
    for r in recs:
        last[(r["doc"], r["engine"])] = r
    docs = sorted(p for p in src.iterdir() if p.is_file() and p.name not in (".gitkeep", "rotation.csv")) if src.is_dir() else []
    types = doc_types(docs, out)
    names = {d.name for d in docs}
    md = [
        f"# phase 결과 리포트 — {time.strftime('%Y-%m-%d %H:%M:%S')} 갱신" + (f" (phase {phase} 종료)" if phase else ""),
        "",
        "phase 1 = VLM·LLM 없는 엔진, 쪽당 0.1초 · phase 2 = phase 1 시간 초과분, 쪽당 1초 · phase 3 = 나머지(기본 제한) + VLM(쪽 수 비례·병렬 API). "
        "진행 중 현황은 [PROGRESS.md](PROGRESS.md).",
        "",
    ]
    # A. phase별
    by = defaultdict(Counter)
    for r in recs:
        if r.get("phase") and r["doc"] in names:
            by[r["phase"]][status(r)] += 1
            by[r["phase"]]["sec"] += r.get("sec") or 0
    md += [
        "## A. phase별 결과",
        "",
        "| phase | 시도 | 성공 | 다음 phase로(시간 초과) | 실패 | 환경(미설치·미설정) | 걸린 시간 |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in sorted(by):
        c = by[p]
        md.append(
            f"| {p} | {c['ok'] + c['timeout'] + c['fail'] + c['env']} | {c['ok']} | {c['timeout']} | {c['fail']} | {c['env']} | {c['sec'] / 60:.1f}분 |"
        )
    if not by:
        md.append("| — | 실행 기록 없음(`python -m pipeline.extract.run_all`) | | | | | |")
    # B. 다음 phase 대기
    wait = [r for r in last.values() if r["doc"] in names and status(r) == "timeout" and (r.get("phase") or 3) < 3]
    md += ["", f"## B. 다음 phase 대기 {len(wait)}건", ""]
    if wait:
        md += ["| 문서 | 엔진 | 넘어온 phase | 제한(초) | 걸린 시간(초) |", "|---|---|---|---|---|"]
        md += [
            f"| {r['doc']} | {r['engine']} | {r.get('phase')} | {r.get('limit', r.get('timeout'))} | {r['sec']} |"
            for r in sorted(wait, key=lambda r: (r["engine"], r["doc"]))[:200]
        ]
    md += [
        "",
        "다음 할 일: 옛 phase 시간 초과 — 다음 run_all 실행이 쪽당 제한(text_page_sec·vlm_page_sec)으로 다시 시도"
        if wait
        else "다음 할 일: 대기 없음",
    ]
    # C. 연결 안 되는 엔진
    env = defaultdict(list)
    for r in last.values():
        if r["doc"] in names and status(r) == "env":
            env[r["engine"]].append(r)
    md += ["", f"## C. 연결되지 않는 엔진 {len(env)}종 — 이슈 정리", ""]
    if env:
        md += ["| 엔진 | 원인 분류 | 오류(첫 줄) | 조치 | 영향 문서 |", "|---|---|---|---|---|"]
        for e, rs in sorted(env.items()):
            err = str(rs[0]["error"]).splitlines()[0][:110].replace("|", "/")
            md.append(f"| {e} | {kind(rs[0]['error'])} | {err} | {FIX.get(e, 'SETUP.md 해당 절')} | {len(rs)} |")
    else:
        md.append("- 없음")
    # D. 기준점·사람 검토
    md += ["", "## D. 문서별 기준점과 사람 검토 목록", ""]
    try:
        from pipeline.transform.represent.parse_qa import run as qa_run

        qa, route = qa_run(out, src, Path(truth) if truth else Path("__none__"), None)
        (out / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "route.json").write_text(json.dumps(route, ensure_ascii=False, indent=1), encoding="utf-8")
        from pipeline.transform.represent.parse_qa import summary_md, write_summary

        ps = write_summary(qa, src, out)
    except Exception as ex:
        md.append(f"- 채점 실패: {type(ex).__name__}: {ex}")
        qa, ps = {"docs": {}}, None
    rows, review = [], 0
    for doc in sorted(qa["docs"], key=lambda d: (types.get(d, ""), d)):
        if doc not in names:
            continue
        dd = qa["docs"][doc]
        ok = {e: m for e, m in dd["engines"].items() if m.get("ok")}
        why = []
        if dd["ref"] == "truth":
            ref_desc = "정답(truth)"
        elif dd["ref"] in ("answer_key", "native"):
            ref_desc = {"answer_key": "사람 정답지", "native": "원본 구조 파서"}[dd["ref"]]
        else:
            best = max(ok, key=lambda e: (ok[e].get("consensus_recall") or 0, e not in VLM, ok[e].get("chars", 0)), default=None)
            cr = ok[best].get("consensus_recall") if best else None
            ref_desc = (
                (f"{best} (" + (f"합의 {cr:.0%}" if cr is not None else "합의 없음") + f" · {ok[best].get('chars', 0):,}자)")
                if best
                else "—"
            )
            if best and cr is not None and cr < 0.8:
                why.append("기준 엔진도 합의 수치를 80% 미만만 담음")
        if not ok:
            why.append("성공한 엔진 없음")
        chars = sorted(m.get("chars", 0) for m in ok.values() if m.get("chars", 0) > 0)
        if len(chars) >= 2 and chars[-1] > 2 * chars[0] and dd["ref"] not in ("truth", "answer_key"):
            why.append(f"엔진 간 글자 수 차이 큼({chars[0]:,}~{chars[-1]:,})")
        if dd.get("group") == "image" and dd["ref"] in ("consensus", "none"):
            ncons = max((m.get("consensus_recall") is not None for m in ok.values()), default=False)
            if not ncons:
                why.append("이미지 문서 — 인식 계열 3개 이상이 합의한 수치가 없어 자동 기준 불가")
            vlm_only = _vlm_only_numbers(out, doc, ok)
            if vlm_only:
                why.append(f"VLM만 읽은 수치 {vlm_only}개(지어냈을 수 있음)")
        if why:
            review += 1
        rows.append(
            f"| {doc} | {types.get(doc, dd.get('format'))} | {ref_desc} | {len(ok)}/{len(dd['engines'])} | {' · '.join(why) or '—'} |"
        )
    md += [
        f"문서 {len(rows)}개 중 **사람 검토 {review}개**. 기준점 = 정답(개발 PC) → 사람 정답지 → 원본 구조 파서(텍스트형) → "
        "여러 인식 계열의 합의 수치를 가장 많이 담은 엔진(동률이면 VLM이 아닌 쪽, 그다음 더 많이 읽은 쪽).",
        "",
        "| 문서 | 타입 | 기준점 | 성공 엔진 | 사람 검토 사유 |",
        "|---|---|---|---|---|",
    ] + rows
    if qa["docs"]:
        md += ["", "## E. 타입별 수집 성공·정확도 (PDF는 텍스트/이미지 구분)", ""] + summary_md(ps)
    if text_only:
        return "\n".join(md) + "\n"
    text = "\n".join(md) + "\n"
    for _ in range(5):  # Windows는 다른 프로그램이 열고 있으면 잠깐 거부
        try:
            atomic_write_text(out / "PHASE_REPORT.md", text)  # RV6 — tmp 쓰기+os.replace 공용(common/atomic.py)
            break
        except PermissionError:
            time.sleep(0.3)
    else:
        raise PermissionError(f"{out / 'PHASE_REPORT.md'} 교체 실패(열려 있음)")
    return out / "PHASE_REPORT.md"


def _vlm_only_numbers(out, doc, ok):
    """VLM 계열만 읽은 수치 개수(다른 계열 어디에도 없음)."""
    got = {}
    for e in ok:
        f = out / e / (doc + ".json")
        try:
            got[e] = nums(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    vl = set().union(*[v for e, v in got.items() if e in VLM]) if any(e in VLM for e in got) else set()
    other = set().union(*[v for e, v in got.items() if e not in VLM]) if any(e not in VLM for e in got) else set()
    return len({n for n in vl - other if len(n.replace(".", "")) >= 2})


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=C.cfg().paths.doc_dir or str(APP_ROOT / "output" / "prepared"))
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "parse"))
    ap.add_argument("--truth", default="")
    a = ap.parse_args()
    print(write_phase_report(a.src, a.out, truth=a.truth or None).read_text(encoding="utf-8")[:3000])
