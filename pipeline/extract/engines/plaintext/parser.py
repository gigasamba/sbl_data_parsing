"""표준 라이브러리 텍스트 읽기 (.txt) — 인코딩 판별(UTF-8·UTF-16 BOM·CP949) + 탭/파이프 구분 표 감지

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
단독 실행: python -m data_parsing.parse_one --engine plaintext <문서> <out.json>
"""
import re

from pipeline.extract.engines._common.contract import _md_tables, _with_tables

ENCODINGS = ("utf-8-sig", "utf-16", "cp949")


def _decode(raw):
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace"), "utf-8(깨짐 대체)"


def parse_plaintext(path):
    with open(path, "rb") as f:
        text, enc = _decode(f.read())
    tables = _md_tables(text)
    block = []                                     # 탭으로 나뉜 줄이 2줄 이상 이어지면 표
    for line in text.splitlines() + [""]:
        if "\t" in line:
            block.append([c.strip() for c in line.split("\t")])
        else:
            if len(block) >= 2:
                tables.append(block)
            block = []
    out = _with_tables(text, tables, "plaintext")
    out["trace"]["encoding"] = enc
    return out


ENGINES = {"plaintext": parse_plaintext}
FORMATS = {"plaintext": ('.txt',)}
REQUIRES = {"modules": [], "tools": []}
PROFILED = set()
UNVERIFIED = set()
