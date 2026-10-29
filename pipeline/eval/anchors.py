"""검색 앵커 생성(eval-design.md §4) — LLM 없이 {id, doc, label, value, query, source} 세트를 만든다.

정답 우선순위: truth.json(source=truth) > answer_key/<문서>.json(source=answer_key) >
기준 코퍼스(--anchor-ref)에서 '라벨: 값' 줄 추출 — 문서 확장자가 텍스트형(native 그룹)이면 source=native,
이미지형이면 source=consensus(진짜 다중 엔진 합의 검증은 parse_qa.py 몫 — 여기선 이미지 문서라는 사실만 표시).
값이 기준 코퍼스 2개 이상 문서에 나오면 모호하므로 제외 — 단 **같은 내용 묶음**(truth의 variant_of·본문 동일 사본:
회전본·doc↔docx·xlsx↔xlsm)은 한 문서로 본다. 질문은 묶음마다 한 번, 적중은 묶음 안 어느 사본이든(앵커 `docs`). 문서당 최대 cap개(시드 고정 선택).
질의에는 값을 절대 넣지 않는다 — 라벨에 값이 섞였거나 tf-idf 용어가 값을 포함하면 그 앵커는 버린다.
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import hashlib
import json
from pathlib import Path

from pipeline.eval.stages import extract_label_values, normalize_value, tfidf_top_terms

NATIVE_EXT = {
    ".pdf_text",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".pptx",
    ".ppt",
    ".html",
    ".htm",
    ".mht",
    ".mhtml",
    ".txt",
    ".eml",
    ".msg",
}


def _seed_for(doc, seed):
    """random.Random 시드 — hash()는 프로세스마다 달라(PYTHONHASHSEED) 재현 안 되므로 sha256 사용."""
    return seed + int(hashlib.sha256(doc.encode("utf-8")).hexdigest()[:8], 16)


def _candidates_from_values(values):
    return [{"label": v.get("label", ""), "value": v.get("value", "")} for v in values if v.get("value")]


def _doc_candidates(doc, corpus, truth, answer_key_dir):
    if truth and doc in truth and isinstance(truth[doc], dict):
        return _candidates_from_values(truth[doc].get("values", [])), "truth"
    if answer_key_dir:
        f = Path(answer_key_dir) / f"{doc}.json"
        if f.exists():
            info = json.loads(f.read_text(encoding="utf-8"))
            return _candidates_from_values(info.get("values", [])), "answer_key"
    source = "native" if Path(doc).suffix.lower() in NATIVE_EXT else "consensus"
    seen, out = set(), []
    for label, value in extract_label_values(corpus.get(doc, "")):
        key = (label, value)
        if key not in seen:
            seen.add(key)
            out.append({"label": label, "value": value})
    return out, source


def content_groups(docs, truth):
    """문서 → 같은 내용 묶음(정렬된 문서 목록). truth 없으면(서버) 문서마다 자기 혼자 — 서버는 dedup이 사본을 거른다."""
    root = {d: d for d in docs}

    def find(d):
        while root[d] != d:
            d = root[d]
        return d

    by_text = {}
    for d in docs:
        t = (truth or {}).get(d)
        if not isinstance(t, dict):
            continue
        v = t.get("variant_of")
        if v in root:
            root[find(d)] = find(v)
        k = normalize_value(t.get("text", ""))
        if k:
            if k in by_text:
                root[find(d)] = find(by_text[k])
            else:
                by_text[k] = d
    groups = {}
    for d in docs:
        groups.setdefault(find(d), []).append(d)
    return {d: sorted(groups[find(d)]) for d in docs}


def build_anchors(corpus, docs, truth=None, answer_key_dir=None, seed=0, cap=10):
    """corpus: {doc: text}(기준 파싱 결과). docs: 대상 문서 목록(코퍼스에 없어도 truth/answer_key로 만들 수 있음)."""
    import random

    norm_corpus = {d: normalize_value(t) for d, t in corpus.items()}
    groups = content_groups(docs, truth)
    anchors = []
    for doc in docs:
        if groups[doc][0] != doc:
            continue  # 묶음 대표(이름순 첫 문서)만 질문을 만든다
        same = set(groups[doc])
        cands, source = _doc_candidates(doc, corpus, truth, answer_key_dir)
        kept = []
        for c in cands:
            vn = normalize_value(c["value"])
            if not vn:
                continue
            if sum(1 for d2, t2 in norm_corpus.items() if d2 not in same and vn in t2) > 0:
                continue  # 값이 여러 문서에 나오면 모호 → 제외 (§4)
            kept.append(c)
        if len(kept) > cap:
            rnd = random.Random(_seed_for(doc, seed))
            rnd.shuffle(kept)
            kept = kept[:cap]
        terms_pool = tfidf_top_terms(doc, corpus, n=6)
        for c in kept:
            vn = normalize_value(c["value"])
            label = c["label"]
            if vn and vn in normalize_value(label):
                continue  # 라벨에 값이 섞여 있으면 질의에 값이 노출됨 → 앵커 제외
            terms = [t for t in terms_pool if not (vn and vn in normalize_value(t))][:2]
            query = " ".join([label] + terms).strip()
            if vn and vn in normalize_value(query):
                continue  # 안전장치 — 그래도 값이 섞이면 버린다
            anchors.append(
                {
                    "id": f"{doc}::a{len(anchors)}",
                    "doc": doc,
                    "docs": groups[doc],
                    "label": label,
                    "value": c["value"],
                    "query": query,
                    "source": source,
                }
            )
    return anchors


def write_anchors(anchors, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for a in anchors:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")


def load_anchors(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
