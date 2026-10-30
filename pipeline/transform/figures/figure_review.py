#!/usr/bin/env python3
"""파싱 검토 루프(docs/testing.md §1) — 그림 기록(record) ↔ VLM 독립 추출(figure-v1) 대조·판정·보정.

흐름: extract(독립 추출, 우리 기록 안 보여줌) → compare(결정적 대조, 코드) → judge(VLM, 다른 지시문) → fix면 되돌이(최대 REVIEW_MAX_ROUNDS회).
원칙: 규칙·키워드는 샘플별로 만들지 않는다(일반 스키마 + 판정자). 고치지 못한 충돌은 사람 확인(human_queue)로 — 값을 임의로 바꾸지 않음.

VLM 연결: VLM_BASE_URL·VLM_MODEL(추출, role="vlm")·VLM_MODEL_ALT(판정, 없으면 VLM_MODEL, role="vlm_judge")·VLM_API_KEY·VLM_DEADLINE(기본 360초).
내부망 가드·재시도: common/adk.py complete()가 함(합성 데이터 실험만 VLM_ALLOW_EXTERNAL=1). 응답 캐시: output/parse/_review/_cache/.
VLM 없으면 verdict="skipped"(실패 아님) — 결정적 대조도 할 수 없으므로 기록만 남긴다.

CLI: python modules/parse/review/figure_review.py --figures <*.figures.json 폴더 또는 index.jsonl> --images <그림 폴더> --out output/parse/_review
"""

import argparse
import base64
import copy
import hashlib
import io
import json
import re
import time
import unicodedata
from pathlib import Path as _Path

from common.ai import adk as A
from common.ai.agent_prompts import tail as _tail_prompt
from common.ai.agent_prompts import template as _load_template
from common.config.settings import cfg as ccfg  # common 칸 설정 객체(S7c)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT  # 폴더 재편 뒤 이 상수만 바뀌면 됨(위 ROOT는 sys.path 부트스트랩에만 씀)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

ROOT = APP_ROOT


class VLMUnavailable(RuntimeError):
    pass


# ── figure-v1 독립 추출 지시문(추출기) — 글자는 dev/agents/figure_extract/prompt.md(AD33). extract()가 근처
# 맥락·이전 판정 지적을 문자열로 이어붙이므로 load()(템플릿+꼬리) 대신 template()(꼬리 없음)을 쓰고, 공용
# 꼬리(ADK14 P1)는 그 자료 뒤(샌드위치)에 직접 붙인다.
P_EXTRACT = _load_template("figure_extract", "extract")
P_EXTRACT_TAIL = _tail_prompt("figure_extract")
# ── 판정 지시문(판정자 — 추출기와 다른 역할: 감사자) — 글자는 dev/agents/figure_judge/prompt.md(AD33). 아래
# _vlm_call이 '우리 기록'·'자동 대조 결과'를 문자열로 이어붙이므로 load()(템플릿+꼬리) 대신 template()(꼬리
# 없음)을 쓰고, 공용 꼬리(ADK14 P1)는 그 자료 뒤(샌드위치)에 직접 붙인다.
P_JUDGE = _load_template("figure_judge", "judge")
P_JUDGE_TAIL = _tail_prompt("figure_judge")


# ── VLM 호출(이 모듈 안에 작게 — dev/tools/engines/는 import 안 함) ────────
def _downscale(image_bytes):
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((2000, 2000))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _cache_dir():
    d = ROOT / "output" / "parse" / "_review" / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _vlm_call(image_bytes, prompt, which="extract"):
    """VLM 1회 호출 → 응답 텍스트. judge는 VLM_MODEL_ALT(없으면 VLM_MODEL, role="vlm_judge"). 캐시·내부망 가드·재시도(429·5xx)는
    common/adk.py complete()가 함(role 자체가 model·주소 선택을 담당 — AD22 전제, 다른 VLM 서버는 아직 못 씀)."""
    _vm = ccfg().models.vlm  # S7c — 설정 객체
    base = _vm.base_url
    model = (_vm.model_alt if which == "judge" else None) or _vm.model
    if not (base and model):
        raise VLMUnavailable("VLM_BASE_URL·VLM_MODEL 미설정 — 검토 건너뜀")
    png = _downscale(image_bytes)
    img_sha = hashlib.sha256(image_bytes).hexdigest()
    key = hashlib.sha256(json.dumps([model, prompt, img_sha], ensure_ascii=False).encode()).hexdigest()
    cp = _cache_dir() / f"{key}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))["text"]
    extra = {"reasoning": {"enabled": False}} if "openrouter" in base else {"chat_template_kwargs": {"enable_thinking": False}}
    _dl = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체(옛 float(get(X) or 360))
    deadline = float(_dl if _dl is not None else 360)
    role = "vlm_judge" if which == "judge" else "vlm"
    try:
        text, _u = A.complete(
            role,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=1500,
            extra=extra,
            timeout=deadline,
            agent="figure_extract" if which == "extract" else "figure_judge",
        )
    except A.ModelUnavailable as ex:
        raise RuntimeError(f"VLM 호출 실패: {ex}") from ex
    cp.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    return text


def _parse_json(text):
    """응답에서 JSON 객체 하나(코드펜스·앞뒤 설명 있어도)."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def extract(image_bytes, context=None, feedback=None):
    """VLM 독립 추출(figure-v1) — 우리 기록은 보여주지 않음. feedback = 이전 판정의 지적 사항(재추출용)."""
    prompt = P_EXTRACT
    if context:
        prompt += f"\n\n근처 맥락(참고만 — 그림에 없는 내용을 지어내지 말 것): {context}"
    if feedback:
        prompt += "\n\n이전 판정이 지적한 문제 — 다시 확인하라: " + " / ".join(str(x) for x in feedback)
    prompt += P_EXTRACT_TAIL  # 공용 꼬리(ADK14 P1) — 자료(맥락·이전 판정) 뒤(샌드위치)에 맨 끝으로
    data = _parse_json(_vlm_call(image_bytes, prompt, "extract"))
    return {
        "kind": data.get("kind") or "other",
        "texts": data.get("texts") or [],
        "meaning": data.get("meaning") or {},
        "values": data.get("values") or [],
        "nodes": data.get("nodes") or [],
        "edges": data.get("edges") or [],
        "order": data.get("order") or [],
        "table": data.get("table") or {"header": [], "rows": []},
        "uncertain": data.get("uncertain") or [],
    }


# ── 결정적 대조(코드, 무료) ────────────────────────────────────────────
def _norm(s):
    """이름 비교용 정규화 — NFKC·대소문자 무시·공백·기호 제거(윗첨자 ^·아래첨자 _·단위 %는 의미가 있어 남김)."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s)).casefold()
    return re.sub(r"[^\w^_%]+", "", t)


def _contains(a, b):
    na, nb = _norm(a), _norm(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


_NUM = re.compile(r"[-+]?\d[\d,]*\.?\d*")
_SUF = {"k": 1e3, "m": 1e6, "b": 1e9}


def _parse_num(s):
    """ "1,234.5"·"1.2B"·"12%" → (수, 단위). 못 읽으면 None."""
    if s is None:
        return None
    s = str(s).strip()
    m = _NUM.search(s)
    if not m:
        return None
    num = float(m.group(0).replace(",", ""))
    rest = s[m.end() :].strip()
    if rest[:1].lower() in _SUF and (len(rest) == 1 or not rest[1].isalnum()):
        num *= _SUF[rest[:1].lower()]
        rest = rest[1:].strip()
    return num, _norm(rest)


def _num_eq(a, b, rel=1e-3, abs_tol=1e-6):
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _vals(items):
    out = []
    for v in items or []:
        pv = _parse_num(v.get("value"))
        if pv is None:
            continue
        num, vunit = pv
        out.append(
            {"label": v.get("label") or v.get("series") or v.get("x") or "", "value": num, "unit": _norm(v.get("unit")) or vunit, "raw": v}
        )
    return out


def _match_values(ours, ext):
    """라벨 포함 관계로 짝짓기(라벨이 둘 다 없으면 값 일치로) → matched, missing_in_ours, extra_in_ours."""
    ours_l, ext_l = _vals(ours), _vals(ext)
    used = set()
    matched, missing = [], []
    for e in ext_l:
        hit = None
        for i, o in enumerate(ours_l):
            if i in used:
                continue
            if (e["label"] and o["label"] and _contains(e["label"], o["label"])) or (
                not e["label"] and not o["label"] and _num_eq(e["value"], o["value"])
            ):
                hit = i
                break
        if hit is None:
            missing.append({"type": "value", "label": e["label"], "value": e["raw"].get("value"), "unit": e["raw"].get("unit")})
        else:
            used.add(hit)
            matched.append((ours_l[hit], e))
    extra = [
        {"type": "value", "label": o["label"], "value": o["raw"].get("value"), "unit": o["raw"].get("unit")}
        for i, o in enumerate(ours_l)
        if i not in used
    ]
    return matched, missing, extra


def _node_list(d):
    ns = d.get("nodes") or d.get("order")
    if ns:
        return list(ns)
    seen = []
    for e in d.get("edges") or []:
        for k in ("from", "to"):
            n = e.get(k)
            if n and n not in seen:
                seen.append(n)
    return seen


def _missing_names(ext_names, blob):
    """ext 노드·글자 이름이 우리 기록 어딘가(본문·연결·값 라벨)에 있는지 — 포함 여부(목록 일치 아님)."""
    return [{"type": "node", "name": n} for n in ext_names if _norm(n) and _norm(n) not in blob]


def _record_blob(record):
    """이름 포함 확인용 — 본문·요약·캡션·언급·표 + 연결(from·to·label)·값 라벨까지(record 스키마엔 nodes가 없어 edges·values가 출처)."""
    parts = [
        record.get("text") or "",
        record.get("summary") or "",
        record.get("caption") or "",
        " ".join(record.get("mentions") or []),
        record.get("table_md") or "",
    ]
    for e in record.get("edges") or []:
        parts += [e.get("from") or "", e.get("to") or "", e.get("label") or ""]
    for v in record.get("values") or []:
        parts += [str(v.get("label") or ""), str(v.get("series") or "")]
    return _norm(" ".join(str(p) for p in parts))


def _match_edges(ours_edges, ext_edges):
    key = lambda e: (_norm(e.get("from")), _norm(e.get("to")))
    oset = {key(e): e for e in ours_edges or [] if e.get("from") and e.get("to")}
    eset = {key(e): e for e in ext_edges or [] if e.get("from") and e.get("to")}
    missing = [[e["from"], e["to"]] for k, e in eset.items() if k not in oset]
    extra = [[e["from"], e["to"]] for k, e in oset.items() if k not in eset]
    return missing, extra


def _order_mismatch(ours_nodes, ext_nodes):
    """공통 노드의 상대 순서가 ext와 다르면(LCS가 전체가 아니면) 어긋남."""
    on, en = [_norm(n) for n in ours_nodes], [_norm(n) for n in ext_nodes]
    common = [n for n in on if n in en]
    idx = [en.index(n) for n in common]
    bad = any(idx[i] < idx[i - 1] for i in range(1, len(idx)))
    return bad, common


def _table_cells_md(md):
    if not md:
        return 0
    n = 0
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.fullmatch(r"\|[\s:\-|]+\|?", line):
            continue
        n += len(line.strip("|").split("|"))
    return n


def _table_cells_ext(table):
    if not table:
        return 0
    return len(table.get("header") or []) + sum(len(r) for r in (table.get("rows") or []))


def compare(record, ext):
    """결정적 대조(코드, 무료, LLM 없음) — 숫자 집합(단위 정규화)·이름 포함·연결 쌍·순서(LCS)·표 칸 수."""
    record, ext = record or {}, ext or {}
    matched, miss_v, extra_v = _match_values(record.get("values"), ext.get("values"))
    value_mismatch = []
    for o, e in matched:
        if not _num_eq(o["value"], e["value"]):
            value_mismatch.append({"label": o["label"] or e["label"], "ours": o["raw"].get("value"), "ext": e["raw"].get("value")})
        elif o["unit"] and e["unit"] and o["unit"] != e["unit"]:  # 값은 같은데 단위 의미가 다름(코드로 셀 수 있는 것)
            value_mismatch.append(
                {"label": o["label"] or e["label"], "ours": o["raw"].get("unit"), "ext": e["raw"].get("unit"), "field": "unit"}
            )

    ours_nodes, ext_nodes = _node_list(record), _node_list(ext)
    blob = _record_blob(record)
    miss_n = _missing_names(ext_nodes, blob)
    miss_t = [{"type": "text", "text": t} for t in (ext.get("texts") or []) if len(_norm(t)) >= 2 and _norm(t) not in blob]

    miss_e, extra_e = _match_edges(record.get("edges"), ext.get("edges"))
    has_order, common = _order_mismatch(ours_nodes, ext_nodes)

    ocells, ecells = _table_cells_md(record.get("table_md")), _table_cells_ext(ext.get("table"))
    return {
        "missing_in_ours": miss_v + miss_n + miss_t,
        "extra_in_ours": extra_v,
        "value_mismatch": value_mismatch,
        "edge_mismatch": {"missing_in_ours": miss_e, "extra_in_ours": extra_e},
        "order_mismatch": [{"common_order_ext": common}] if has_order else [],
        "table_mismatch": {"ours_cells": ocells, "ext_cells": ecells} if ecells and ocells < ecells else None,
    }


# ── 판정(VLM, 추출과 다른 지시문) ─────────────────────────────────────
def judge(image_bytes, record, diff, context=None):
    prompt = (
        P_JUDGE + "\n\n우리 기록: " + json.dumps(record, ensure_ascii=False) + "\n\n자동 대조 결과: " + json.dumps(diff, ensure_ascii=False)
    )
    if context:
        prompt += f"\n\n근처 맥락: {context}"
    prompt += P_JUDGE_TAIL  # 공용 꼬리(ADK14 P1) — 자료(기록·대조 결과·맥락) 전부 뒤(샌드위치)에 맨 끝으로
    data = _parse_json(_vlm_call(image_bytes, prompt, "judge"))
    return {
        "items": data.get("items") or [],
        "semantic_ok": data.get("semantic_ok"),
        "verdict": _verdict(data),
        "issues": data.get("issues") or [],
    }


def _verdict(data):
    """판정은 코드로 — material 항목만 센다(VLM이 사소한 표기·그림 밖 글자로 fix를 내던 잘못된 경보, 10-02 실측 2/2).
    material missing·wrong·order 또는 의미 불일치 → fix · material unsure만 → human · 없으면 pass · 항목을 못 읽으면 VLM 판정, 그것도 없으면 human."""
    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    mat = [i for i in items if (i.get("severity") or "material") == "material"]
    if any(i.get("verdict") in ("missing", "wrong", "order") for i in mat) or data.get("semantic_ok") is False:
        return "fix"
    if any(i.get("verdict") == "unsure" for i in mat):
        return "human"
    if items:
        return "pass"
    return data.get("verdict") if data.get("verdict") in ("pass", "fix", "human") else "human"


# ── 보정 — diff가 가리킨 항목만, 원본은 바꾸지 않고 사본에 ────────────────
def _apply_corrections(fixed, ext, diff):
    out = copy.deepcopy(fixed)
    vals = {_norm(v.get("label")): v for v in (out.get("values") or []) if v.get("label")}
    for m in diff.get("value_mismatch", []):
        v = vals.get(_norm(m["label"]))
        if v is not None:
            v["value"] = m["ext"]
    for miss in diff.get("missing_in_ours", []):
        if miss.get("type") == "value":
            out.setdefault("values", []).append({"label": miss["label"], "value": miss["value"], "unit": miss.get("unit")})
    em = diff.get("edge_mismatch") or {}
    have = {(_norm(e.get("from")), _norm(e.get("to"))) for e in (out.get("edges") or [])}
    for frm, to in em.get("missing_in_ours", []):
        if (_norm(frm), _norm(to)) not in have:
            out.setdefault("edges", []).append({"from": frm, "to": to, "label": None})
    if diff.get("order_mismatch"):
        ext_nodes = ext.get("order") or ext.get("nodes") or []
        pos = {_norm(n): i for i, n in enumerate(ext_nodes)}
        out["edges"] = sorted(out.get("edges") or [], key=lambda e: pos.get(_norm(e.get("from")), 10**9))
    return out


def _skipped(reason):
    return {
        "verdict": "skipped",
        "rounds": 0,
        "issues": [reason],
        "fixed_record": None,
        "human_queue": [],
        "provenance": {"reason": reason},
    }


def review(image_bytes, record, context=None, max_rounds=None):
    """검토 루프(흐름 1~5) — 입력 record는 바꾸지 않는다(사본만 고침). 최대 max_rounds(기본 REVIEW_MAX_ROUNDS)회 재추출."""
    if max_rounds is None:
        _mr = pc.cfg().eval.review_max_rounds  # S7c — 설정 객체(옛 int(get(X) or 2))
        max_rounds = int(_mr if _mr is not None else 2)
    t0 = time.perf_counter()
    try:
        ext = extract(image_bytes, context=context)
    except VLMUnavailable as e:
        return _skipped(str(e))
    fixed = copy.deepcopy(record or {})
    issues_all, rnd = [], 0
    while True:
        diff = compare(fixed, ext)
        try:
            jres = judge(image_bytes, fixed, diff, context=context)
        except VLMUnavailable as e:
            return _skipped(str(e))
        issues_all += jres.get("issues") or []
        _vm = ccfg().models.vlm  # S7c — 설정 객체(한 번 읽어 묶음 — VS7c2 R-10)
        prov = {"model": _vm.model, "judge_model": _vm.model_alt or _vm.model, "ms": round((time.perf_counter() - t0) * 1000)}
        if jres["verdict"] == "pass":
            return {
                "verdict": "pass",
                "rounds": rnd,
                "issues": issues_all,
                "fixed_record": {**fixed, "figure_v1": ext},
                "human_queue": [],
                "provenance": prov,
            }
        if jres["verdict"] == "human" or rnd >= max_rounds:
            hq = [i for i in (jres.get("items") or []) if i.get("verdict") in ("missing", "wrong", "order", "unsure")]
            return {
                "verdict": "human",
                "rounds": rnd,
                "issues": issues_all,
                "fixed_record": {**fixed, "figure_v1": ext},
                "human_queue": hq,
                "provenance": prov,
            }
        fixed = _apply_corrections(fixed, ext, diff)
        rnd += 1
        try:
            ext = extract(image_bytes, context=context, feedback=jres.get("issues") or [])
        except VLMUnavailable as e:
            return _skipped(str(e))


# ── 실행(폴더) ────────────────────────────────────────────────────────
def _load_records(figures_path):
    p = _Path(figures_path)
    files = [p] if p.is_file() else (sorted(p.glob("*.figures.json")) or ([p / "index.jsonl"] if (p / "index.jsonl").exists() else []))
    recs = []
    for f in files:
        if f.name == "index.jsonl" or f.suffix == ".jsonl":
            recs += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        else:
            data = json.loads(f.read_text(encoding="utf-8"))
            doc = f.name[: -len(".figures.json")] if f.name.endswith(".figures.json") else f.stem
            for r in data if isinstance(data, list) else [data]:
                r.setdefault("doc", doc)
                recs.append(r)
    return recs


def _find_image(images_dir, doc, image_id):
    d = _Path(images_dir)
    safe = re.sub(r"[^\w.-]+", "_", image_id or "")
    for c in (d / f"{safe}.png", d / doc / f"{safe}.png", d / doc / f"{safe}.jpg"):
        if c.exists():
            return c
    return None


def run(figures_dir, images_dir, out_dir):
    """figures_dir의 그림 기록마다 review() → out_dir/<doc>/<sha12>.json · index.jsonl · HUMAN.md."""
    out = _Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = _load_records(figures_dir)
    from common.ai.guard import check_scope  # AD43 — func 범위(문서 수 상한 + 예산 필수), 내부망이면 영향 없음

    check_scope([ccfg().models.vlm.base_url], n_docs=len({rec.get("doc") for rec in records}))  # S7c — 설정 객체
    index_rows, human_lines = [], []
    for rec in records:
        doc = rec.get("doc") or (rec.get("image_id") or "?").split("#")[0]
        img_path = _find_image(images_dir, doc, rec.get("image_id")) if images_dir else None
        result = review(img_path.read_bytes(), rec, context=rec.get("caption")) if img_path else _skipped("이미지 없음")
        (out / doc).mkdir(parents=True, exist_ok=True)
        sha12 = hashlib.sha256((rec.get("image_id") or json.dumps(rec, ensure_ascii=False)).encode()).hexdigest()[:12]
        (out / doc / f"{sha12}.json").write_text(
            json.dumps({"image_id": rec.get("image_id"), **result}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        index_rows.append({"doc": doc, "image_id": rec.get("image_id"), "verdict": result["verdict"], "rounds": result["rounds"]})
        if result["verdict"] == "human":
            human_lines.append(f"- {doc} / {rec.get('image_id')}: {', '.join(str(x) for x in result['issues'][:3]) or '(사유 없음)'}")
    (out / "index.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in index_rows), encoding="utf-8")
    (out / "HUMAN.md").write_text("# 사람 확인 대상\n\n" + ("\n".join(human_lines) if human_lines else "(없음)") + "\n", encoding="utf-8")
    return index_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--figures")
    ap.add_argument("--images")
    ap.add_argument("--out", default=str(ROOT / "output" / "parse" / "_review"))
    args = ap.parse_args()
    rows = run(args.figures, args.images, args.out)
    print(f"[review] {len(rows)}건 → {args.out}")


if __name__ == "__main__":
    utf8_stdout()
    main()
