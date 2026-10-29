#!/usr/bin/env python3
"""계약 사실 추출(구조화) — 라벨(값)·본문 패턴에서 제품·모달리티·체결일·단가·금액·통화·배치 → 묶음 docs.contract.
표 집계 질의(검색 modules/search/aggregate.py)는 이 결과(PostgreSQL doc.contract)를 읽기만 함."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from common.core.terms import modalities, norm  # noqa: E402 — 이름 정규화·모달리티 어휘(검색과 같은 규칙, DT1 c1: 용어집 modality_code 우선)

CODE_MOD = {"ADC": "ADC", "MAB": "mAb", "BSA": "bispecific", "BIS": "bispecific", "BSP": "bispecific", "VAC": "vaccine"}


class _CodeRe:
    """제품 코드 정규식 + 코드 전체 목록(findall은 그룹만 돌려주므로)."""

    rx = re.compile(r"\b[A-Z]{2,5}-(ADC|MAB|BSA|BIS|BSP|VAC)-\d{1,3}\b")

    def search(self, s):
        return self.rx.search(s)

    def findall_codes(self, s):
        return [m.group(0) for m in self.rx.finditer(s)]


PRODUCT_CODE_RE = _CodeRe()

MONEY_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(USD|EUR|KRW|JPY)\b", re.I)

DATE_RE = re.compile(r"\b((?:19|20)\d{2}-\d{2}-\d{2})\b")

L_PRODUCT = re.compile(r"^\s*(product(\s*(code|id))?|제품(\s*코드)?|품목\s*코드)\s*$", re.I)

L_SIGNED = re.compile(r"^\s*(signed(\s*(on|date))?|signing\s*date|date\s*signed|체결일|서명일|계약\s*(체결)?일)\s*$", re.I)

L_PRICE = re.compile(r"^\s*(unit\s*price|단가|배치당\s*단가)\s*$", re.I)

L_AMOUNT = re.compile(r"^\s*((total\s*)?contract\s*value|total\s*value|(총\s*)?계약\s*(금액|규모))\s*$", re.I)

L_VOLUME = re.compile(r"^\s*(annual\s*volume|batch\s*volume|batches|연간\s*물량|배치\s*수)\s*$", re.I)

L_MODALITY = re.compile(r"^\s*(modality|product\s*type|제품\s*종류)\s*$", re.I)


def _money(s):
    m = MONEY_RE.search(s or "")
    return (float(m.group(1).replace(",", "")), m.group(2).upper()) if m else None


def contract_facts(pairs, text, contract_no=None):
    """문서 하나의 계약 사실 dict(없는 값은 빠짐) — 라벨(교차 확인 쌍 먼저) 우선, 라벨이 없으면 값 모양.
    값 모양 대체는 문서 머리(300자)에 그 계약 번호가 있는 계약서에만(QBR·RFP처럼 금액을 인용하는 문서가 섞이지 않게)."""

    def lab(rx):
        return next((p["value"] for p in pairs if rx.search(p.get("label") or "")), None)

    out, src = {}, "label"
    code = PRODUCT_CODE_RE.search(lab(L_PRODUCT) or "")
    price, amount = _money(lab(L_PRICE)), _money(lab(L_AMOUNT))
    signed = DATE_RE.search(lab(L_SIGNED) or "")
    head = norm((text or "")[:300])
    if contract_no and norm(contract_no) in head:
        code = code or PRODUCT_CODE_RE.search(text or "")
        if not signed:  # 라벨 없음 → 가장 이른 날짜(체결일 < 만료일; 스캔 OCR은 줄 순서가 뒤집히기도 함)
            signed = min(DATE_RE.finditer(text or ""), key=lambda m: m.group(1), default=None)
        if not (price and amount):
            ms = sorted({_money(m.group(0)) for m in MONEY_RE.finditer(text or "")} - {None})
            if len(ms) >= 2:  # 작은 금액 = 단가, 큰 금액 = 계약 금액(데이터 관례: 금액 = 배치 × 단가)
                price, amount, src = price or ms[0], amount or ms[-1], "pattern"
    if code:
        out["product_code"] = code.group(0)
        out["modality"] = CODE_MOD.get(code.group(1))
    m = (lab(L_MODALITY) or "").strip().lower()
    out["modality"] = modalities().get(m, out.get("modality"))
    if signed:
        out["signed_on"] = signed.group(1)
    if price:
        out["unit_price"], out["currency"] = price
    if amount:
        out["amount"], out["currency"] = amount
    # 배치 수 = 연간 물량(라벨) → 라벨이 깨졌으면 'N batches/year' 값 중 MTOP(최소 보장)가 아닌 것 → 없으면 금액 ÷ 단가.
    #   금액 ÷ 단가는 다년 계약에서 기간 전체 배치가 됨(합성 4고객 C-MRH-2023-03: 32 vs 연간 8) — 마지막 대안으로만
    v = re.search(r"(\d+(?:\.\d+)?)", lab(L_VOLUME) or "")
    if not v and contract_no and norm(contract_no) in head:
        v = next(
            (
                m
                for ln in (text or "").splitlines()
                if not re.search(r"mtop|최소", ln, re.I)
                for m in [re.search(r"(\d+(?:\.\d+)?)\s*batch(?:es)?\s*/\s*(?:year|yr|년)", ln, re.I)]
                if m
            ),
            None,
        )
    if v:
        out["batches"] = int(float(v.group(1))) if float(v.group(1)).is_integer() else float(v.group(1))
    elif price and amount and price[0] and amount[1] == price[1] and abs(amount[0] / price[0] - round(amount[0] / price[0])) < 1e-6:
        out["batches"] = round(amount[0] / price[0])
    if price and not amount and out.get("batches"):  # 금액만 못 읽음(스캔 OCR) → 단가 × 배치(계산값으로 표시)
        out["amount"], out["currency"], src = round(price[0] * out["batches"], 2), price[1], "derived"
    if out.get("amount") or out.get("unit_price"):
        out["values_from"] = src
    return {k: v for k, v in out.items() if v is not None}
