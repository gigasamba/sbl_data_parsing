"""표 fact → pricing 입력 필드 타입 정규화 (결정적 규칙, LLM 미사용).

키는 pricing 입력 스키마의 deal 필드와 같다(contract_value 추가).
tools/engines/_common/contract.py(_fields)가 이 파일을 쓴다.

normalize_facts(facts) -> {key: {"value", "unit", "qualifiers", "raw", "source_label"}}
  - value는 기준 단위로 환산한 수(%, months 등), bool, 또는 None(해석 실패 — raw만 남김)
"""

import re

# 라벨 → 필드 키 (순서 중요: 구체적인 것 먼저)
_LABELS = [
    (r"shared\s*mtop", "shared_mtop"),
    (r"^\s*mtop|minimum take", "mtop"),
    (r"reserve\s*batch", "reserve_batch"),
    (r"price\s*adjustment\s*cap", "price_adjustment_cap"),
    (r"price\s*adjustment\s*waiver", "price_adjustment_waivers"),
    (r"binding\s*forecast", "binding_forecast"),
    (r"one-?way\s*partial\s*binding", "one_way_partial_binding"),
    (r"^\s*(제안\s*)?단가|unit\s*price|proposed\s*price", "proposed_price"),
    (r"총\s*계약\s*금액|예상\s*계약\s*규모|contract\s*value", "contract_value"),
    (r"배치\s*규모|batch\s*scale", "batch_scale"),
    (r"계약\s*물량", "committed_batch_total"),
    (r"effective\s*contract\s*term|계약\s*기간", "effective_contract_term"),
]

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_PURE_NUM = re.compile(r"^\s*\d[\d,]*(?:\.\d+)?\s*$")
_NONE = re.compile(r"(?i)없음|\bnone\b")
_NUM_ANY = re.compile(r"\d")
# RFP 양식의 '단위' 열 값 — 값이 아니라 머리말
_UNIT_CELL = re.compile(r"(?i)^\s*(yes\s*/\s*no|text|batches\s*/\s*year|years?|quarters?|%.*|L|USD.*/.*)\s*$")


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def field_key(label: str):
    low = label.lower()
    for pat, key in _LABELS:
        if re.search(pat, low):
            return key
    return None


def _split_value(cells: list[str]) -> tuple[str, str]:
    """다열 행([단위, 값, 비고] 등)에서 (값 텍스트, 단위 힌트)를 고른다.
    순수 숫자 셀이 있으면 그것이 값이고 바로 앞 셀이 단위 — 비고 속 다른 숫자에 끌려가지 않게."""
    for i, c in enumerate(cells):
        if _PURE_NUM.match(c):
            return c, (cells[i - 1] if i > 0 else "")
    # 숫자 셀이 없으면 단위 열('yes/no'·'text' 등 양식 머리말)을 건너뛴 첫 셀이 값
    vals = [c for c in cells if not _UNIT_CELL.match(c)]
    unit = next((c for c in cells if _UNIT_CELL.match(c)), "")
    return (vals[0] if vals else (cells[0] if cells else "")), unit


def _parse(key: str, text: str, unit_hint: str) -> dict:
    t, u = text.strip(), unit_hint.lower()
    q = {}
    m = re.search(r"대비\s*" + _NUM + r"\s*%\s*할인", t)
    if m:
        q["discount_pct"] = _f(m.group(1))
    elif re.search(r"할인\s*미적용", t):
        q["discount_pct"] = 0.0

    if key == "shared_mtop":
        m = re.match(r"(?i)\s*(yes|no|예|아니오)", t)
        return {"value": None if not m else m.group(1).lower() in ("yes", "예"), "unit": "bool", "qualifiers": q}
    if key in ("proposed_price", "contract_value"):
        m = re.search(r"(?:USD|US\$|\$)\s*" + _NUM + r"\s*(M|B|million|billion)?\s*(/\s*(g|kg|L))?", t, re.I)
        if not m:
            return {"value": None, "unit": None, "qualifiers": q}
        v = _f(m.group(1)) * {"m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}.get((m.group(2) or "").lower(), 1)
        unit = f"USD/{m.group(4)}" if m.group(4) else "USD"
        per = re.search(r"/\s*(\d+)\s*months?", t)
        if per:
            q["per_months"] = int(per.group(1))
        return {"value": v, "unit": unit, "qualifiers": q}
    if key in ("price_adjustment_cap", "one_way_partial_binding"):
        m = re.search(_NUM + r"\s*%", t)
        if m:
            return {"value": _f(m.group(1)), "unit": "%", "qualifiers": q}
        if _PURE_NUM.match(t) and "%" in u:            # 엑셀 비율 셀(0.03 + 단위 '% per annum')
            v = _f(t)
            return {"value": round(v * 100, 6) if v <= 1 else v, "unit": "%", "qualifiers": q}
        return {"value": None, "unit": "%", "qualifiers": q}
    if key in ("mtop", "reserve_batch", "committed_batch_total"):
        m = re.search(_NUM + r"\s*batch", t, re.I) or (re.match(_NUM, t) if _PURE_NUM.match(t) else None)
        if not m:
            # 숫자가 없을 때만 '없음'을 0으로 — 값 칸에 라벨 끝 글자가 넘어온 '간없음' 같은 추출 잡음도 수용
            if not _NUM_ANY.search(t) and _NONE.search(t):
                return {"value": 0.0, "unit": "batches/year" if key != "committed_batch_total" else "batches", "qualifiers": q}
            return {"value": None, "unit": None, "qualifiers": q}
        cum = re.search(r"누적\s*최소\s*" + _NUM, t)
        if cum:
            q["cumulative_min_batches"] = _f(cum.group(1))
        unit = "batches" if key == "committed_batch_total" else "batches/year"
        return {"value": _f(m.group(1)), "unit": unit, "qualifiers": q}
    if key in ("binding_forecast",):
        m = re.search(_NUM + r"\s*(quarters?|분기)", t, re.I) or (re.match(_NUM, t) if _PURE_NUM.match(t) else None)
        return {"value": _f(m.group(1)) if m else None, "unit": "quarters", "qualifiers": q}
    if key in ("price_adjustment_waivers", "effective_contract_term"):
        m = re.search(_NUM + r"\s*(years?|년|months?|개월)", t, re.I)
        if not m and not _NUM_ANY.search(t) and _NONE.search(t):
            return {"value": 0.0, "unit": "years", "qualifiers": q}
        if m:
            v = _f(m.group(1))
            return {"value": round(v / 12, 4) if m.group(2).lower().startswith(("month", "개월")) else v,
                    "unit": "years", "qualifiers": q}
        if _PURE_NUM.match(t) and "year" in u:
            return {"value": _f(t), "unit": "years", "qualifiers": q}
        return {"value": None, "unit": "years", "qualifiers": q}
    if key == "batch_scale":
        m = re.search(_NUM + r"\s*L\b", t)
        return {"value": _f(m.group(1)) if m else None, "unit": "L", "qualifiers": q}
    return {"value": None, "unit": None, "qualifiers": q}


def normalize_facts(facts: list[dict]) -> dict:
    """facts([{value, context:[label], cells?}]) → 타입 필드. 같은 키가 여러 번이면 첫 해석 성공분 유지."""
    out = {}
    for f in facts:
        label = (f.get("context") or [""])[0]
        key = field_key(label)
        if not key:
            continue
        cells = f.get("cells") or [f.get("value", "")]
        text, unit_hint = _split_value(cells) if len(cells) > 1 else (cells[0], "")
        parsed = _parse(key, text, unit_hint)
        parsed.update({"raw": f.get("value", ""), "source_label": label})
        if key not in out or (out[key]["value"] is None and parsed["value"] is not None):
            out[key] = parsed
    return out
