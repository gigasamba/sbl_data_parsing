#!/usr/bin/env python3
"""문항 탐색기 HTML — 문항(파싱 QA 항목·검색 앵커)마다 파서·조합별 실제 출력과 정답 여부를 한 페이지에 (LLM 0회).

세트(데이터가 있는 것만, 순서 고정):
  파싱 — 텍스트형 / 이미지 : 행 = 정답 값 하나(truth.json, 없으면 anchors.jsonl), 열 = 파서, 펼치면 파서 출력에서 그 값이 나온 줄
  검색 : 행 = 앵커 질의, 열 = R@5 상위 조합(+ 외부 스택), ✓ 5위 안 · △ 6~10위 · ✗, 펼치면 조합별 상위 5개 조각
         (서버 LLM 단계의 output/eval/answers.jsonl이 있으면 같은 행에 답변·정답 여부)
템플릿: resources/config/report_templates/explorer.tpl.html (기존 A/B 문항 탐색기 틀). 보고서 본문은 tools/report.py.
사용: python cli/explorer.py [--out out] [--top 10] [--dest output/report/explorer.html]
"""

import argparse
import json
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import (  # 코드가 읽는 데이터(S2 — resources/config/)
    APP_ROOT,  # output/ 등 런타임 경로용(옛 dev/)
    CRITERIA_FILE,
    TEMPLATES_DIR,
)
from pipeline.transform.represent.parse_qa import _key, clean_commas, norm_nows, scoring_text  # 채점과 같은 정규화

TPL = TEMPLATES_DIR / "explorer.tpl.html"


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(p).exists() else []


def line_of(text, key):
    """출력에서 값이 나온 줄(정규화 비교) — 없으면 None."""
    for ln in (text or "").splitlines():
        if key and key in clean_commas(norm_nows(ln)):
            return ln.strip()[:160]
    return None


def parse_sets(out, truth, anchors):
    qa = json.loads((out / "parse" / "qa.json").read_text(encoding="utf-8")) if (out / "parse" / "qa.json").exists() else None
    if not qa:
        return []
    items = {}  # 문서 → [(라벨, 값, 출처)]
    for doc, t in (truth or {}).items():
        if not doc.startswith("_"):
            items[doc] = [(v.get("label", ""), v["value"], "truth") for v in t.get("values") or []]
    if not items:
        for a in anchors:
            items.setdefault(a["doc"], []).append((a.get("label", ""), a["value"], a.get("source", "")))
    sets = {}
    for doc, d in sorted(qa["docs"].items()):
        engs = sorted(d.get("engines") or {})
        texts = {}
        for e in engs:
            f = out / "parse" / e / (doc + ".json")
            texts[e] = scoring_text(json.loads(f.read_text(encoding="utf-8"))) if f.exists() and d["engines"][e].get("ok") else None
        grp = d.get("group") or "기타"
        n_ok = sum(1 for m in d["engines"].values() if m.get("ok"))
        low = n_ok <= 2 or (d.get("n_fam", 9) <= 2 and d.get("ref") not in ("truth", "answer_key"))  # parse_qa.LOW_N과 같은 규칙
        s = sets.setdefault(grp, {"rows": [], "arms": set()})
        s["arms"].update(engs)
        for k, (label, value, src) in enumerate(items.get(doc, [])):
            key, e, a = _key(value), {}, {}
            for eng, tx in texts.items():
                if tx is None:
                    e[eng], a[eng] = False, {"a": "실행 실패·출력 없음", "ok": False, "err": True}
                    continue
                ok = bool(key) and key in clean_commas(norm_nows(tx))
                e[eng], a[eng] = ok, {"a": line_of(tx, key) if ok else "없음", "ok": ok, "err": False}
            rows_fmt = d.get("format", "").lstrip(".").upper()
            s["rows"].append(
                {
                    "id": f"{doc}#{k + 1}",
                    "t": "parse",
                    "s": rows_fmt,
                    "sp": src,
                    "q": f"{label}: 값이 출력에 있나",
                    "g": str(value),
                    "ev": [],
                    "e": e,
                    "a": a,
                    "doc": doc,
                    "fmt": rows_fmt,
                    "low": low,
                }
            )
    title = {"native": "파싱 — 텍스트형 문서", "image": "파싱 — 이미지 문서"}
    crit = {c["id"]: c["name"] for c in json.loads(CRITERIA_FILE.read_text(encoding="utf-8")).get("parse", [])}

    def pass_info(g):
        """엔진 × 형식군의 QA 기준 판정(parse_qa aggregate의 pass) — 값 포함 표와 별개인 기준 전체 통과 여부."""
        out_ = {}
        for eng, groups_ in (qa.get("engines") or {}).items():
            p = (groups_.get(g) or {}).get("pass") or {}
            if p:
                out_[eng] = {
                    "ok": sum(bool(v) for v in p.values()),
                    "n": len(p),
                    "fail": [f"{k} {crit.get(k, '')}" for k, v in p.items() if not v],
                }
        return out_

    return [
        {
            "key": f"p_{g}",
            "title": title.get(g, f"파싱 — {g}"),
            "cat": "파싱 (문서 → 텍스트·표·수치, LLM 0회)",
            "mode": "parse",
            "note": "행 = 문서의 정답 값 하나, 열 = 파서. ✓ = 값이 출력에 있음(정규화 후). 행을 누르면 파서별로 그 값이 나온 줄. "
            "요약의 '정답 값 포함'은 값 재현율(정확도)만 — 파서마다 처리하는 문서 수가 달라 비율로 비교하고, "
            "CER·수치 환각·표 행·읽기 순서까지 포함한 QA 기준 통과는 옆 열(기준별 실패는 마우스를 올리면).",
            "n": len(s["rows"]),
            "evArms": sorted(s["arms"]),
            "anArms": [],
            "nAns": 0,
            "rows": s["rows"],
            "pass": pass_info(g),
        }
        for g, s in sorted(sets.items())
        if s["rows"]
    ]


def combo_label(c):
    return " · ".join(str(c.get(k, "")) for k in ("parse", "chunk", "embed", "graph", "retrieve") if c.get(k) not in (None, "", "none"))


def search_set(out, anchors, top):
    res = [r for r in jl(out / "eval" / "results.jsonl") if r.get("key")]
    if not anchors or not res:
        return None, {}
    best = {}
    for r in res:  # 같은 조합을 다시 돌렸으면 마지막 기록
        best[r["key"]] = r
    ranked = sorted(
        best.values(), key=lambda r: (-r["R"]["r5"], -r["R"]["mrr"], -(r["R"].get("ctx5m") or 0))
    )  # R@5 → MRR → 유의미 글자 수(많을수록)
    keep = [r for r in ranked if r["combo"].get("parse") == "external"] + [r for r in ranked if r["combo"].get("parse") != "external"][:top]
    names = {r["key"]: combo_label(r["combo"]) for r in keep}
    hits = {r["key"]: {h["anchor_id"]: h for h in jl(out / "eval" / "hits" / f"{r['key']}.jsonl")} for r in keep}
    ans = {}
    for a in jl(out / "eval" / "answers.jsonl"):
        ans.setdefault(a["anchor_id"], {})[a.get("key") or combo_label(a.get("combo") or {})] = {
            "a": str(a.get("answer", ""))[:120],
            "ok": bool(a.get("correct")),
            "err": bool(a.get("error")),
            "c": a.get("class") or ("y" if a.get("correct") else "n"),
        }
    rows = []
    for a in anchors:
        e, t = {}, {}
        for k in names:
            h = hits[k].get(a["id"])
            if h is None:
                continue
            rk = h.get("rank")
            e[k] = "y" if rk and rk <= 5 else "near" if rk and rk <= 10 else "n"
            t[k] = [{"doc": u.get("doc", ""), "text": u.get("text", "")[:300], "hit": u.get("hit")} for u in h.get("top") or []]
        rows.append(
            {
                "id": a["id"],
                "t": "retrieve",
                "s": a.get("source", ""),
                "sp": a["doc"],
                "q": a["query"],
                "g": str(a["value"]),
                "ev": [f"{a.get('label', '')} → {a['value']}"],
                "e": e,
                "a": ans.get(a["id"], {}),
                "top": t,
                "doc": a["doc"],
                "fmt": Path(a["doc"]).suffix.lstrip(".").upper(),
            }
        )
    an_arms = sorted({k for v in ans.values() for k in v})
    return (
        {
            "key": "search",
            "title": f"검색 근거 · 앵커 {len(rows)}",
            "cat": "검색 근거(LLM 0회) + 답변(LLM, 서버)",
            "rows": rows,
            "note": f"R@5 상위 조합 {len(names)}개(+외부 스택). 조합 이름 = 파싱 · 청킹 · 임베딩 · 그래프 · 검색. 분할 = 앵커 문서.",
            "n": len(rows),
            "evArms": list(names),
            "anArms": an_arms,
            "nAns": sum(1 for r in rows if r["a"]),
        },
        names,
    )


def build(out, top=10, eyebrow=""):
    truth_p = out / "corpus" / "truth.json"
    truth = json.loads(truth_p.read_text(encoding="utf-8")) if truth_p.exists() else None
    anchors = jl(out / "eval" / "anchors.jsonl")
    sets = parse_sets(out, truth, anchors)
    ss, names = search_set(out, anchors, top)
    if ss:
        sets.append(ss)
    if not sets:  # 템플릿은 세트 1개 이상을 전제
        sets = [
            {
                "key": "none",
                "title": "미실행",
                "cat": "미실행",
                "note": "파싱 채점(pipeline/transform/represent/parse_qa.py)·조합 실험(pipeline/eval/run_combo.py) 결과가 없습니다.",
                "n": 0,
                "evArms": [],
                "anArms": [],
                "nAns": 0,
                "rows": [],
            }
        ]
    data = {"arms": names, "sets": sets, "eyebrow": eyebrow or ("가상 문서(개발 PC)" if truth else "서버 문서")}
    return TPL.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("�", "\\ufffd")
    )  # 파서가 깨뜨린 글자 = JS 이스케이프로 보존


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(APP_ROOT / "output"))
    ap.add_argument("--top", type=int, default=10, help="검색 세트에 보일 R@5 상위 조합 수")
    ap.add_argument("--dest", default="")
    ap.add_argument("--eyebrow", default="")
    a = ap.parse_args()
    out = Path(a.out)
    html = build(out, a.top, a.eyebrow)
    dest = Path(a.dest or out / "report" / "explorer.html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    print(f"작성 완료: {dest} ({len(html):,} bytes)")


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("explorer"):
        main()
