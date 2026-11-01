"""교차 확인(파싱 모듈) — 엔진별 결과에서 서로 다른 계열 엔진 2개+가 같은 (라벨, 값)을 냈는지 → 대표 결과 rep.meta(pairs·all).
구조화는 이 결과만 읽음(엔진별 결과를 넘기지 않음)."""

import json
from collections import defaultdict
from pathlib import Path

from common.core.repfmt import EMPTY, locate, nlabel, pairs_of, pick  # noqa: F401
from common.core.text import normalize_value


def families():
    from pipeline.extract.engines import registry
    from pipeline.shared.summarize import FAMILY

    return {e: FAMILY.get(e, st) for e, (st, _) in registry.engines().items()}


def load_doc(parse_dir, eng, doc):
    f = Path(parse_dir) / eng / f"{doc}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return {"text": d.get("text") or "", "facts": d.get("facts") or []}


def locate_value(text, value, hint=None):
    """값(가능하면 hint와 같은 줄)이 있는 줄 → 근거 위치."""
    vn, hn = normalize_value(value), normalize_value(hint or "")
    lines = text.split("\n")
    pos = 0
    best = None
    for ln in lines:
        n = normalize_value(ln)
        if vn and vn in n:
            if not hn or hn in n:
                best = (pos, ln)
                break
            best = best or (pos, ln)
        pos += len(ln) + 1
    if not best:
        return None
    m = locate(text, best[0], best[0] + len(best[1]))
    return {"page": m["page"], "line": m["line"], "section": m["section"], "snippet": best[1].strip()[:200]}


def build(parse_dir, src, min_fams=2):
    """문서별 교차 확인 (라벨, 값) 사전 + 기준 엔진 텍스트(근거용)."""
    qa = json.loads((Path(parse_dir) / "qa.json").read_text(encoding="utf-8"))
    route = json.loads((Path(parse_dir) / "route.json").read_text(encoding="utf-8")) if (Path(parse_dir) / "route.json").exists() else {}
    fam = families()
    docs = {}
    for doc, dd in qa["docs"].items():
        oks = [e for e, m in dd["engines"].items() if m.get("ok")]
        order = [e for e in route.get(dd["format"], []) if e in oks] + sorted(e for e in oks if e not in route.get(dd["format"], []))
        if not order:
            continue
        outs = {e: load_doc(parse_dir, e, doc) for e in order}
        outs = {e: d for e, d in outs.items() if d}
        by = defaultdict(lambda: {"fams": set(), "label": None, "value": None})
        for e in order:
            if e not in outs:
                continue
            for label, value in pairs_of(outs[e]):
                k = (nlabel(label), normalize_value(value))
                if not k[0] or not k[1] or k[1] in EMPTY:
                    continue
                c = by[k]
                c["fams"].add(fam.get(e, e))
                if c["label"] is None:  # 표기는 순위 높은 엔진 것
                    c["label"], c["value"] = label.strip(), value.strip()
        ok = {k: v for k, v in by.items() if len(v["fams"]) >= min_fams}
        label_count = defaultdict(int)
        for (lk, _), _v in ok.items():
            label_count[lk] += 1
        ref = next(e for e in order if e in outs)
        docs[doc] = {
            "format": dd["format"],
            "ref": ref,
            "text": outs[ref]["text"],
            "outs": outs,
            "fam": fam,
            "pairs": [
                {"label": v["label"], "value": v["value"], "fams": len(v["fams"]), "lk": lk}
                for (lk, _), v in ok.items()
                if label_count[lk] == 1
            ],  # 같은 라벨에 값 둘 이상 = 모호
            "all": sorted(
                ({"label": v["label"], "value": v["value"], "fams": len(v["fams"]), "lk": lk} for (lk, _), v in by.items()),
                key=lambda p: -p["fams"],
            ),
        }
    return docs
