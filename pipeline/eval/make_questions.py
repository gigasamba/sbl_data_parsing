#!/usr/bin/env python3
"""output/corpus/truth.json(개발 PC 가상 문서 정답) → output/eval/questions.jsonl(§3-6 질문 스키마) 결정적 생성.
유형별(value·client·count·sum·rfi) --per-category개. 회전·저하 사본(variant_of)은 원본과 같은 문서로 보고
중복 제외(pipeline.eval.anchors.content_groups 재사용 — 앵커와 같은 사본 묶음 규칙). 정답 계산이 모호하면 만들지 않는다.

사용: python cli/make_questions.py [--truth output/corpus/truth.json] [--out output/eval/questions.jsonl]
      [--per-category 8] [--seed 0]
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)

# isort: split
import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.eval.anchors import content_groups  # 사본 묶음 로직 재사용(중복 없음)

CLIENT_LABELS = {"고객사/client", "고객사", "client"}
SUPPLIER_LABELS = {"공급사/supplier", "공급사", "supplier"}
CONTRACT_LABELS = {"계약 번호/contract no.", "계약 번호", "contract no."}
UNIT_PRICE_LABELS = {"단가/unit price", "단가", "unit price"}
VALID_UNTIL_LABELS = {"유효 기간/valid until", "유효 기간", "valid until"}

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_QTY_RE = re.compile(r"qty|수량", re.I)


def _num(s):
    if s is None:
        return None
    t = re.sub(r"(?<=\d),(?=\d)", "", str(s))
    m = _NUM_RE.search(t)
    return float(m.group()) if m else None


def _norm_label(label):
    return (label or "").strip().lower()


def _find_value(values, label_set):
    for v in values:
        if _norm_label(v.get("label", "")) in label_set:
            return v.get("value")
    return None


def _reps(truth, groups):
    """사본 묶음 대표 문서(이름순 첫 문서)만 — variant_of 사본 중복 제외."""
    return sorted(d for d in truth if isinstance(truth.get(d), dict) and groups.get(d, [d])[0] == d)


def _unique_labeled(values):
    """라벨이 문서 안에서 한 번만 나오는 값만 — 같은 라벨이 품목별로 반복되면 질문이 어느 값을 가리키는지 모호해진다."""
    counts = Counter(v.get("label", "") for v in values)
    return [v for v in values if counts[v.get("label", "")] == 1]


# ── value ────────────────────────────────────────────────────


def gen_value_questions(truth, groups, n, seed):
    candidates = []
    for doc in _reps(truth, groups):
        values = truth[doc].get("values") or []
        contract = _find_value(values, CONTRACT_LABELS)
        if not contract:
            continue
        for v in _unique_labeled(values):
            if v.get("kind") != "num" or _norm_label(v.get("label", "")) in UNIT_PRICE_LABELS:
                continue  # 단가는 client 문항이 따로 씀 — 모호하지 않은 값 중 겹치지 않게
            candidates.append((doc, contract, v))
    rnd = random.Random(seed)
    rnd.shuffle(candidates)
    out = []
    for i, (doc, contract, v) in enumerate(candidates[:n]):
        docs = groups.get(doc, [doc])
        out.append(
            {
                "id": f"value::{i}",
                "category": "value",
                "question": f"계약번호 {contract} 문서에서 '{v['label']}'의 값은 얼마입니까?",
                "answer": v["value"],
                "docs": docs,
                "doc": doc,
                "query": f"{v['label']} {contract}",
            }
        )
    return out


# ── client ───────────────────────────────────────────────────


def gen_client_questions(truth, groups, n, seed):
    candidates = []
    for doc in _reps(truth, groups):
        values = truth[doc].get("values") or []
        client, contract, price = (_find_value(values, s) for s in (CLIENT_LABELS, CONTRACT_LABELS, UNIT_PRICE_LABELS))
        if client and contract and price:
            candidates.append((doc, client, contract, price))
    rnd = random.Random(seed + 1)
    rnd.shuffle(candidates)
    out = []
    for i, (doc, client, contract, price) in enumerate(candidates[:n]):
        docs = groups.get(doc, [doc])
        out.append(
            {
                "id": f"client::{i}",
                "category": "client",
                "client": client,
                "question": f"고객사 {client}의 계약(번호 {contract}) 단가는 얼마입니까?",
                "answer": price,
                "docs": docs,
                "doc": doc,
                "query": f"{client} {contract} 단가",
            }
        )
    return out


# ── count(고객사별 서로 다른 계약 번호 수) ──────────────────────


def gen_count_questions(truth, groups, n, seed):
    contracts_by_client, docs_by_client = defaultdict(set), defaultdict(set)
    for doc in _reps(truth, groups):
        values = truth[doc].get("values") or []
        client, contract = _find_value(values, CLIENT_LABELS), _find_value(values, CONTRACT_LABELS)
        if not client or not contract:
            continue
        contracts_by_client[client].add(contract)
        docs_by_client[client].update(groups.get(doc, [doc]))
    rnd = random.Random(seed + 2)
    clients = sorted(contracts_by_client)
    rnd.shuffle(clients)
    out = []
    for i, client in enumerate(clients[:n]):
        out.append(
            {
                "id": f"count::{i}",
                "category": "count",
                "client": client,
                "question": f"고객사 {client}와 맺은 서로 다른 계약 건수는 몇 건입니까?",
                "answer": len(contracts_by_client[client]),
                "tolerance": 0,
                "docs": sorted(docs_by_client[client]),
                "query": f"{client} 계약",
            }
        )
    return out


# ── sum(고객사별/제품코드별 수량(L) 합계, 표의 Qty 열) ──────────


def _qty_col(header):
    for i, h in enumerate(header):
        if _QTY_RE.search(h):
            return i
    return None


def _product_code(item):
    m = re.match(r"^(\S+)", item or "")
    return m.group(1) if m else item


def gen_sum_questions(truth, groups, n, seed):
    by_client, by_code = defaultdict(float), defaultdict(float)
    client_docs, code_docs = defaultdict(set), defaultdict(set)
    for doc in _reps(truth, groups):
        info = truth[doc]
        client = _find_value(info.get("values") or [], CLIENT_LABELS)
        for table in info.get("tables") or []:
            if len(table) < 2:
                continue
            qi = _qty_col(table[0])
            if qi is None:
                continue
            for row in table[1:]:
                if qi >= len(row):
                    continue
                qty = _num(row[qi])
                if qty is None:
                    continue
                code = _product_code(row[0] if row else "")
                if client:
                    by_client[client] += qty
                    client_docs[client].update(groups.get(doc, [doc]))
                by_code[code] += qty
                code_docs[code].update(groups.get(doc, [doc]))
    rnd = random.Random(seed + 3)
    client_keys, code_keys = sorted(by_client), sorted(by_code)
    rnd.shuffle(client_keys)
    rnd.shuffle(code_keys)
    out = []
    half = (n + 1) // 2
    for i, client in enumerate(client_keys[:half]):
        out.append(
            {
                "id": f"sum::client::{i}",
                "category": "sum",
                "client": client,
                "unit": "L",
                "question": f"고객사 {client}에 공급한 총 수량(L)은 얼마입니까?",
                "answer": round(by_client[client], 3),
                "tolerance": 0.005,
                "docs": sorted(client_docs[client]),
                "query": f"{client} 수량 합계",
            }
        )
    for i, code in enumerate(code_keys[: max(0, n - len(out))]):
        out.append(
            {
                "id": f"sum::code::{i}",
                "category": "sum",
                "unit": "L",
                "question": f"제품코드 {code}의 총 수량(L)은 얼마입니까?",
                "answer": round(by_code[code], 3),
                "tolerance": 0.005,
                "docs": sorted(code_docs[code]),
                "query": f"{code} 수량 합계",
            }
        )
    return out


# ── rfi(계약 하나 주요 조건 요약) ────────────────────────────────


def gen_rfi_questions(truth, groups, n, seed):
    candidates = []
    for doc in _reps(truth, groups):
        values = truth[doc].get("values") or []
        contract, client, supplier, price, valid_until = (
            _find_value(values, s) for s in (CONTRACT_LABELS, CLIENT_LABELS, SUPPLIER_LABELS, UNIT_PRICE_LABELS, VALID_UNTIL_LABELS)
        )
        kp = [v for v in (contract, client, supplier, price, valid_until) if v]
        if len(kp) < 3:
            continue
        candidates.append((doc, contract, client, supplier, price, valid_until, kp))
    rnd = random.Random(seed + 4)
    rnd.shuffle(candidates)
    out = []
    for i, (doc, contract, client, supplier, price, valid_until, kp) in enumerate(candidates[:n]):
        docs = groups.get(doc, [doc])
        parts = []
        for label, val in (("고객사", client), ("공급사", supplier), ("단가", price), ("유효 기간", valid_until), ("계약번호", contract)):
            if val:
                parts.append(f"{label} {val}")
        out.append(
            {
                "id": f"rfi::{i}",
                "category": "rfi",
                "question": f"계약번호 {contract} 문서의 주요 조건(고객사·공급사·단가·유효 기간 등)을 요약해 주세요.",
                "answer": ", ".join(parts),
                "key_points": kp,
                "docs": docs,
                "doc": doc,
                "query": f"{contract} 계약 조건 요약",
            }
        )
    return out


GENERATORS = {
    "value": gen_value_questions,
    "client": gen_client_questions,
    "count": gen_count_questions,
    "sum": gen_sum_questions,
    "rfi": gen_rfi_questions,
}


def build_questions(truth, per_category, seed):
    docs = sorted(truth)
    groups = content_groups(docs, truth)
    rows = []
    for cat in ("value", "client", "count", "sum", "rfi"):
        rows += GENERATORS[cat](truth, groups, per_category, seed)
    return rows


def build_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", default="output/corpus/truth.json")
    ap.add_argument("--out", default="output/eval/questions.jsonl")
    ap.add_argument("--per-category", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    return ap


def main(argv=None):
    a = build_cli().parse_args(argv)
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
    rows = build_questions(truth, a.per_category, a.seed)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = Counter(r["category"] for r in rows)
    for cat in ("value", "client", "count", "sum", "rfi"):
        print(f"  {cat}: {counts.get(cat, 0)}개")
    print(f"총 {len(rows)}문항 → {out_path}")


if __name__ == "__main__":
    main()
