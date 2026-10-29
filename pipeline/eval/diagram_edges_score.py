#!/usr/bin/env python3
"""F13 — 흐름도 edges 추출 채점(synth-diagrams-hard 같은 정답 세트용). 정답 폴더 구조(--dir):
  <id>.pdf|.docx|.pptx|.jpg  표현별 샘플 파일(파일 이름으로 repr 가늠: _vector/_glyph/_pptx/_raster)
  gold/<파일 이름>.json      {"nodes","edges":[{"from","to"}](directed),"template","orientation","repr"}

지표(edge_score): precision·recall·f1(정규화 (from,to) 집합 비교, diagram_edges.norm_node 재사용) · direction_acc
(상자 짝은 맞는데 방향만 틀린 edge는 "찾았지만 방향 오류" — 짝 맞은 것 중 방향까지 맞은 비율).
같은 템플릿 일관성(consistency) — 한 템플릿의 표현별(vector·glyph·pptx·raster) 추출 결과가 서로 같은 정규화
edge 집합을 내는 비율(제일 많이 나온 모양의 비율, "fraction of variants that yield the identical edge set").

래스터는 결정적 추출기가 없다(VLM만) — 이 채점기는 **가짜/스텁 VLM**만 쓴다(비용 규칙, 실모델 호출 없음):
raster_stub_extract()가 새 프롬프트(prompts/diagram_arrows)를 로드하고 크롭을 2~3배 확대하는 자리까지만
보이고, 실제 모델 호출 대신 빈 결과를 돌려준다 — 그 행의 수치는 "스텁일 뿐 실측 아님"으로 표에 표시한다.

사용: PYTHONPATH=deploy python -m pipeline.eval.diagram_edges_score --dir valid_env/unstructured/synth-diagrams-hard
      PYTHONPATH=deploy python -m pipeline.eval.diagram_edges_score --selftest
"""

import argparse
import io
import json
import sys
from pathlib import Path

from common.core.console import utf8_stdout
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸)
from pipeline.transform.figures import diagram_edges as DE
from pipeline.transform.figures.pptx_edges import pptx_edges

REPR_SUFFIXES = {"vector": "_vector", "glyph": "_glyph", "raster": "_raster", "pptx": "_pptx", "glyph_pdf": "_glyphpdf"}


def _repr_of(name):
    stem = Path(name).stem
    for r, suf in REPR_SUFFIXES.items():
        if stem.endswith(suf):
            return r
    return None


# ── 표현별 추출(결정적 vector·glyph·pptx, 래스터는 스텁) ─────────────────
def extract_vector(path):
    import fitz

    doc = fitz.open(path)
    try:
        pg = doc[0]
        return DE.vector_edges_from_page(pg, (0, 0, pg.rect.width, pg.rect.height))
    finally:
        doc.close()


def extract_glyph(path):
    import docx

    d = docx.Document(path)
    text = "\n".join(p.text for p in d.paragraphs)
    return DE.glyph_edges(text)


def extract_glyph_pdf(path):
    """F13 리뷰 — glyph_pdf(PDF 텍스트 층에 화살표 글자만 그린 변형): get_text()로 뽑은 글자를 glyph_edges()에."""
    import fitz

    doc = fitz.open(path)
    try:
        return DE.glyph_edges(doc[0].get_text())
    finally:
        doc.close()


def extract_pptx(path):
    edges_by_slide = pptx_edges(path)
    return edges_by_slide.get(1, [])


def raster_stub_extract(path):
    """래스터 — 결정적 추출기 없음(VLM만). 여기서는 **가짜 VLM**만: 새 프롬프트(prompts/diagram_arrows)를 실제로
    로드하고 크롭을 2~3배 확대하는 자리까지 보여주되, 모델 호출 대신 빈 결과를 돌려준다(DONT·비용 규칙 — 실
    VLM 호출은 비용 추정 + 사용자 승인 전까지 보류). 반환 edges는 늘 []— 이 함수의 점수는 "측정 안 됨"의 표시일
    뿐 실제 정답률이 아니다(아래 edge_score 호출부가 note로 밝힌다)."""
    from PIL import Image

    from common.ai.agent_prompts import load as _load_prompt

    _prompt = _load_prompt("diagram_arrows", "arrows")
    with Image.open(path) as im:
        _enlarged = im.convert("RGB").resize((im.width * 2, im.height * 2))  # 2배 확대(작은 글자·얇은 선)
        _enlarged_bytes = io.BytesIO()
        _enlarged.save(_enlarged_bytes, "PNG")
    if not pc.cfg().eval.diagram_raster_vlm:  # S7c — 설정 객체(옛 env != "1")
        return []  # 기본 = 가짜(실호출 0) — 실측은 DIAGRAM_RASTER_VLM=1 + 비용 상한(LLM_MAX_CALLS·LLM_BUDGET_USD), 사용자 승인 뒤
    import base64
    import json as _json

    from common.ai import adk as A

    url = "data:image/png;base64," + base64.b64encode(_enlarged_bytes.getvalue()).decode()
    text, _u = A.complete(
        "vlm",
        [{"role": "user", "content": [{"type": "text", "text": _prompt}, {"type": "image_url", "image_url": {"url": url}}]}],
        temperature=0,
        max_tokens=800,
        agent="diagram_arrows",
    )
    raw = (text or "").strip()
    raw = raw[raw.find("{") : raw.rfind("}") + 1] if "{" in raw else ""
    try:
        edges = _json.loads(raw).get("edges") or []
    except ValueError:
        return []
    return [
        {"from": e.get("from"), "to": e.get("to"), "label": e.get("label") or None}
        for e in edges
        if isinstance(e, dict) and e.get("from") and e.get("to")
    ]


EXTRACTORS = {
    "vector": extract_vector,
    "glyph": extract_glyph,
    "glyph_pdf": extract_glyph_pdf,
    "pptx": extract_pptx,
    "raster": raster_stub_extract,
}


# ── 채점 ──────────────────────────────────────────────────────────────
def edge_score(extracted, gold_edges):
    """extracted·gold_edges: [{"from","to",...}] → precision·recall·f1·direction_acc(상자 짝 맞은 것 중 방향도
    맞은 비율, 짝 자체가 없으면 None)·n_extracted·n_gold·n_pair_matched."""
    ext = {(DE.norm_node(e.get("from")), DE.norm_node(e.get("to"))) for e in extracted if e.get("from") and e.get("to")}
    gold = {(DE.norm_node(e.get("from")), DE.norm_node(e.get("to"))) for e in gold_edges if e.get("from") and e.get("to")}
    ext_u = {frozenset(p) for p in ext}
    gold_u = {frozenset(p) for p in gold}
    pair_matched = ext_u & gold_u  # 노드 짝은 맞음(방향 무관)
    tp = ext & gold  # 방향까지 맞음
    precision = (len(tp) / len(ext)) if ext else (1.0 if not gold else 0.0)
    recall = (len(tp) / len(gold)) if gold else 1.0
    f1 = 0.0 if (precision + recall) == 0 else round(2 * precision * recall / (precision + recall), 4)
    direction_acc = round(len(tp) / len(pair_matched), 4) if pair_matched else None
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": f1,
        "direction_acc": direction_acc,
        "n_extracted": len(ext),
        "n_gold": len(gold),
        "n_pair_matched": len(pair_matched),
    }


def consistency(edge_lists):
    """같은 템플릿의 변형(표현)별 추출 결과 — 정규화 (from,to) 집합이 서로 같은 비율(제일 많이 나온 모양 ÷ 전체).
    변형이 0~1개면 정의상 1.0(비교 대상 없음)."""
    if len(edge_lists) < 2:
        return 1.0
    shapes = [
        frozenset((DE.norm_node(e.get("from")), DE.norm_node(e.get("to"))) for e in es if e.get("from") and e.get("to"))
        for es in edge_lists
    ]
    counts = {}
    for s in shapes:
        counts[s] = counts.get(s, 0) + 1
    return round(max(counts.values()) / len(shapes), 4)


def measure(dir_path):
    """dir_path(eval set 폴더) → {"rows": [{template,orientation,repr,**edge_score}], "consistency": {template: 값},
    "negatives": {"n","fp","fp_files"}}. consistency는 **결정적 표현(vector·glyph·glyph_pdf·pptx)만** 비교한다
    — raster는 스텁(늘 빈 결과)이라 섞으면 "같은 템플릿인데 표현만 바꿔도 같은가"라는 원래 물음과 무관하게
    수치가 떨어진다(raster 자체 점수는 rows에 그대로 남음). negatives — template이 "neg_"로 시작하는 음성
    샘플(화살표 없음, gold edges: []) 중 edge를 하나라도 낸 건수(오탐, 독립 검토 요구)."""
    d = Path(dir_path)
    gold_dir = d / "gold"
    rows, by_template = [], {}
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        gf = gold_dir / f"{f.name}.json"
        if not gf.exists():
            continue
        gold = json.loads(gf.read_text(encoding="utf-8"))
        repr_name = gold.get("repr") or _repr_of(f.name)
        extractor = EXTRACTORS.get(repr_name)
        if extractor is None:
            continue
        extracted = extractor(f)
        score = edge_score(extracted, gold["edges"])
        row = {"file": f.name, "template": gold["template"], "orientation": gold["orientation"], "repr": repr_name, **score}
        rows.append(row)
        if repr_name != "raster":
            by_template.setdefault(gold["template"], {})[repr_name] = extracted
    cons = {tid: consistency(list(variants.values())) for tid, variants in by_template.items()}
    neg_rows = [r for r in rows if r["template"].startswith("neg_")]
    fp_files = [r["file"] for r in neg_rows if r["n_extracted"] > 0]
    negatives = {"n": len(neg_rows), "fp": len(fp_files), "fp_files": fp_files}
    return {"rows": rows, "consistency": cons, "negatives": negatives}


def format_table(result):
    """orientation × repr × 스타일 표(Markdown) — 셀마다 P/R/F1·방향정확도, 템플릿별 일관성, 음성 샘플 오탐 수."""
    lines = ["| orientation | repr | file | P | R | F1 | 방향acc | 비고 |", "|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        note = (
            ("실 VLM" if pc.cfg().eval.diagram_raster_vlm else "스텁(실측 아님)")
            if r["repr"] == "raster"
            else ("음성(화살표없음)" if r["template"].startswith("neg_") else "")
        )
        da = "" if r["direction_acc"] is None else f"{r['direction_acc']:.2f}"
        lines.append(
            f"| {r['orientation']} | {r['repr']} | {r['file']} | {r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} | {da} | {note} |"
        )
    lines.append("")
    lines.append("| template | consistency |")
    lines.append("|---|---|")
    for tid, c in result["consistency"].items():
        lines.append(f"| {tid} | {c:.2f} |")
    neg = result["negatives"]
    lines.append("")
    lines.append(f"음성 샘플 오탐(false positive): {neg['fp']}/{neg['n']}" + (f" — {neg['fp_files']}" if neg["fp"] else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", help="eval set 폴더(파일 + gold/<파일>.json)")
    a = ap.parse_args(argv)
    if not a.dir:
        ap.error("--dir 필수")
    result = measure(a.dir)
    print(format_table(result))
    return 0


if __name__ == "__main__":
    utf8_stdout()
    sys.exit(main())
