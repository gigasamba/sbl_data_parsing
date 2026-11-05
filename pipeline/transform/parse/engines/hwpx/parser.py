"""표준 라이브러리 HWPX(한글 OWPML, zip+XML) 읽기 — 의존성 0

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(tools/engines/_common/contract.py).
Contents/section*.xml의 hp:p(문단) 안 hp:t(글자 조각)를 순서대로 이어 문단마다 줄바꿈.
섹션을 못 읽으면(파일 없음·손상) Preview/PrvText.txt(미리보기 본문)로 대신한다.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _section_text(xml_bytes):
    root = ET.fromstring(xml_bytes)
    paras = ["".join(n.text or "" for n in p.iter(_HP + "t")) for p in root.iter(_HP + "p")]
    return "\n".join(t for t in paras if t.strip())


def parse_hwpx(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n)),
                        key=lambda n: int(re.search(r"\d+", n).group()))
        texts = []
        for n in names:
            try:
                texts.append(_section_text(z.read(n)))
            except ET.ParseError:
                continue
        text = "\n\n".join(t for t in texts if t.strip())
        if not text.strip():
            try:
                text = z.read("Preview/PrvText.txt").decode("utf-8", "replace")
            except KeyError:
                text = ""
    return {"text": text, "tables": [], "facts": [], "chunks": None,
            "trace": {"engine": "hwpx[stdlib]", "sections": len(names)}}


ENGINES = {"hwpx": parse_hwpx}
FORMATS = {"hwpx": ('.hwpx',)}
REQUIRES = {"modules": [], "tools": []}
PROFILED = set()
UNVERIFIED = set()
