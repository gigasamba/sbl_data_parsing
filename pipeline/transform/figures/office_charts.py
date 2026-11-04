"""W2 — 네이티브 차트 XML(charts/chart*.xml, xlsx·pptx·docx) 읽기. 원본: eval_hard_parse.chart_text.
제목·계열 이름·분류·값 캐시(numCache/strCache)를 본문 [차트] 줄로 — 네임스페이스 접두(c: 유무) 무관."""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def chart_text(p):
    p = Path(p)
    if p.suffix.lower() not in (".xlsx", ".pptx", ".docx"):
        return ""
    z = zipfile.ZipFile(p)
    lines = []
    loc = lambda e: e.tag.rsplit("}", 1)[-1]
    kids = lambda e, name: [x for x in e.iter() if loc(x) == name]
    pts = lambda e: [v.text for pt in kids(e, "pt") for v in pt if loc(v) == "v"]
    for n in sorted(x for x in z.namelist() if re.search(r"charts/chart\d+\.xml$", x)):
        root = ET.fromstring(z.read(n))
        for title in kids(root, "title")[:1]:
            lines.append("[차트] " + " ".join(x.text or "" for x in kids(title, "t")))
        for ser in kids(root, "ser"):
            name = " ".join(v.text or "" for tx in kids(ser, "tx")[:1] for v in kids(tx, "v"))
            cat = kids(ser, "cat")
            val = kids(ser, "val")
            lines.append(f"계열 {name}: " + ", ".join(f"{c}={v}" for c, v in zip(pts(cat[0]) if cat else [], pts(val[0]) if val else [])))
    return "\n".join(lines)
