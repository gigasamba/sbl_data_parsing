"""pl-67 — 대표 결과 교차 병합(represent): 엔진 하나면 그대로, 여럿이면 대표 본문은 그대로 두고 다른 엔진에만 있는 조각을 끼움."""

import json
import tempfile
from pathlib import Path

from pipeline.transform.represent.doc_represent import represent

REP = "Intro line one\nwraps here\n\nTotal is 5"
CASES = [  # (이름, 엔진별 본문(첫 엔진이 대표), 기대 본문, 기대 rep.merge)
    ("one engine", [REP], REP, {}),
    ("same content", [REP, "Intro line one wraps here\n\nTotal is 5"], REP, {"e2": 0}),
    (
        "extra table",
        [REP, "Intro line one wraps here\n\n| a | b |\n| 1 | 2 |\n\nTotal is 5"],
        "Intro line one\nwraps here\n\n| a | b |\n| 1 | 2 |\n\nTotal is 5",
        {"e2": 1},
    ),
    ("extra paragraph at end", [REP, REP + "\n\nSigned by Kim"], REP + "\n\nSigned by Kim", {"e2": 1}),
    ("crlf same content", [REP, "Intro line one\r\nwraps here\r\n\r\nTotal is 5\r\n"], REP, {"e2": 0}),  # 옛 버그: \r\n이 길어 보여 교체됨
    ("page-aligned insert", ["p1 a\fp2 b", "p1 a\fp2 b\n\np2 extra"], "p1 a\fp2 b\n\np2 extra", {"e2": 1}),
]


def test_cross_merge():
    for name, texts, want, want_merge in CASES:
        pd = Path(tempfile.mkdtemp()) / "parse"
        engines = [f"e{i + 1}" for i in range(len(texts))]
        for eng, text in zip(engines, texts):
            (pd / eng).mkdir(parents=True)
            (pd / eng / "d.txt.json").write_text(json.dumps({"text": text, "tables": [], "facts": []}), encoding="utf-8")
        qa = {"docs": {"d.txt": {"format": ".txt", "engines": {e: {"ok": True} for e in engines}, "ref": None, "pages": None}}}
        (pd / "qa.json").write_text(json.dumps(qa), encoding="utf-8")
        represent({"name": "t", "parse": {".txt": engines}}, pd)
        out = json.loads((pd / "_rep" / "d.txt.json").read_text(encoding="utf-8"))
        assert out["text"] == want and out["rep"]["merge"] == want_merge, (name, out["text"], out["rep"]["merge"])
        assert out["rep"]["engine"] == "e1" and "fused" not in out, name
        assert not (pd / "_rep" / "conflicts.jsonl").exists(), name
