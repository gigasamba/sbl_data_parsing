#!/usr/bin/env python3
"""용어·개념 위키(X4) — 구조화 묶음(output/edw/bundle)의 개념→청크 역색인(concept_chunk.jsonl) + 용어 사전(GLOSSARY_DIR)
→ 개념마다 markdown 페이지 1장(정의·별칭·약어·상위/관련 개념 링크·나오는 문서·대표 청크 ID — 수치는 원문 발췌로만, 지어내지 않음).

코퍼스가 바뀌면 그 개념의 근거(청크·횟수)가 바뀐 개념만 다시 쓴다(지문 비교, _manifest.json).
사용: python cli/wiki.py [--bundle output/edw/bundle] [--glossary-dir] [--out output/wiki] [--selftest]
"""

import argparse
import hashlib
import json
from pathlib import Path

from common.core import terms as T
from common.core.console import utf8_stdout
from common.core.contract import jl
from common.core.paths import APP_ROOT

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)


def concept_evidence(cid, concept_chunk, docs, chunks, top=5):
    """개념이 나오는 문서(횟수 많은 순) · 대표 청크(원문 발췌, top개)."""
    key_to_ci = {f"{docs[c['doc']]['file_sha256']}:{c['seq']}": i for i, c in enumerate(chunks)}
    rows = sorted((r for r in concept_chunk if r["concept_id"] == cid), key=lambda r: -r["count"])
    doc_counts, reps = {}, []
    for r in rows:
        ci = key_to_ci.get(r["chunk_key"])
        if ci is None:
            continue
        d = docs[chunks[ci]["doc"]]
        doc_counts[d["file_name"]] = doc_counts.get(d["file_name"], 0) + r["count"]
        if len(reps) < top:
            reps.append({"chunk_key": r["chunk_key"], "doc": d["file_name"], "text": chunks[ci]["chunk_text"][:300]})
    return sorted(doc_counts, key=lambda n: -doc_counts[n]), reps


def render(cid, r, glossary, doc_names, reps):
    """개념 1개 → markdown. 수치는 대표 청크 발췌 안의 원문 그대로만(청크 ID와 함께) — 새로 계산·요약하지 않음."""
    lines = [f"# {r.get('canonical') or cid} ({cid})", ""]
    defs = [x for x in (r.get("definition_ko"), r.get("definition_en")) if x]
    if defs:
        lines += ["## 정의"] + defs + [""]
    aliases, abbr = T.split_terms(r.get("synonyms")), T.split_terms(r.get("abbreviations"))
    if aliases or abbr:
        lines.append("## 별칭·약어")
        if aliases:
            lines.append(f"- 별칭: {', '.join(aliases)}")
        if abbr:
            lines.append(f"- 약어: {', '.join(abbr)}")
        lines.append("")
    rel, broader_ids = T.related_concepts(cid, glossary), set(T.split_terms(r.get("broader")))
    if rel:
        lines.append("## 상위·관련 개념")
        lines += [
            f"- {'상위' if x['concept_id'] in broader_ids else '관련'}: [{x['canonical']}]({x['concept_id']}.md) ({x['concept_id']})"
            for x in rel
        ]
        lines.append("")
    if doc_names:
        lines.append("## 이 개념이 나오는 문서")
        lines += [f"- {n}" for n in doc_names]
        lines.append("")
    if reps:
        lines.append("## 대표 청크(원문 발췌 — 수치는 출처 청크로만 인용)")
        lines += [f"- `{rp['chunk_key']}` ({rp['doc']}): {rp['text']}" for rp in reps]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def evidence_hash(cid, concept_chunk):
    """개념의 근거(청크·횟수)가 바뀌었는지 — 바뀐 개념만 다시 씀."""
    rows = sorted((r["chunk_key"], r["count"]) for r in concept_chunk if r["concept_id"] == cid)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def build(bundle, out, glossary_dir=None):
    """개념 페이지 생성(변경분만). 반환: 다시 쓴 concept_id 목록."""
    B = Path(bundle)
    docs, chunks = jl(B / "docs.jsonl"), jl(B / "chunks.jsonl")
    cc = jl(B / "concept_chunk.jsonl") if (B / "concept_chunk.jsonl").exists() else []
    glossary = T.load_glossary(glossary_dir)
    O = Path(out)  # noqa: E741 — 결과 폴더(이 함수 안 짧은 이름)
    O.mkdir(parents=True, exist_ok=True)
    mpath = O / "_manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    new_manifest, changed = {}, []
    for cid, r in glossary.items():
        h = evidence_hash(cid, cc)
        new_manifest[cid] = h
        if manifest.get(cid) == h and (O / f"{cid}.md").exists():
            continue
        doc_names, reps = concept_evidence(cid, cc, docs, chunks)
        (O / f"{cid}.md").write_text(render(cid, r, glossary, doc_names, reps), encoding="utf-8")
        changed.append(cid)
    mpath.write_text(json.dumps(new_manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=str(ROOT / "output" / "edw" / "bundle"))
    ap.add_argument("--glossary-dir", default=None, help="없으면 GLOSSARY_DIR 환경변수")
    ap.add_argument("--out", default=str(ROOT / "output" / "wiki"))
    a = ap.parse_args(argv)
    changed = build(a.bundle, a.out, a.glossary_dir)
    print(
        f"개념 페이지: 다시 씀 {len(changed)}개 → {a.out}"
        + (f" ({', '.join(changed[:10])}{'…' if len(changed) > 10 else ''})" if changed else " (변경 없음)")
    )


if __name__ == "__main__":
    utf8_stdout()
    main()
