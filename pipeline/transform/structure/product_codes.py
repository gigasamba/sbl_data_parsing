#!/usr/bin/env python3
"""제품 코드 정규식(PRODUCT_CODE_RE — build_bundle의 용어 초안이 씀). 계약 사실 추출(contract_facts·MONEY_RE·DATE_RE·L_*)은
0.2.0에 지움(pl-46 — 묶음 docs.contract를 읽던 검색 집계가 없어짐)."""

import re


class _CodeRe:
    """제품 코드 정규식 + 코드 전체 목록(findall은 그룹만 돌려주므로)."""

    rx = re.compile(r"\b[A-Z]{2,5}-(ADC|MAB|BSA|BIS|BSP|VAC)-\d{1,3}\b")

    def search(self, s):
        return self.rx.search(s)

    def findall_codes(self, s):
        return [m.group(0) for m in self.rx.finditer(s)]


PRODUCT_CODE_RE = _CodeRe()
