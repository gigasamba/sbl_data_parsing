#!/usr/bin/env python3
"""청크(chunks.jsonl)에서 괄호 약어 정의 패턴("정식명(약어)"·"약어(정식명)")을 찾아 용어 사전
후보를 draft CSV로 적는다. **검색에 쓰이지 않는다** — 사람이 검토해 glossary.csv로 옮겨야 반영됨(status=draft만).

사용: python -m pipeline.transform.structure.glossary_suggest --chunks <chunks.jsonl> [--out output/glossary/domain_terms_draft.csv]
      [--glossary-dir <glossary.csv가 있는 폴더>]
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서

# isort: split
import argparse
import csv
import datetime
import json
from pathlib import Path

from common.core.terms import filter_definitions, load_glossary, scan_definitions

FIELDS = [
    "concept_id",
    "canonical",
    "category",
    "synonyms",
    "abbreviations",
    "weak_synonyms",
    "broader",
    "related",
    "context_required",
    "case_sensitive",
    "definition_ko",
    "definition_en",
    "source",
    "owner",
    "status",
    "updated",
]


def _records(chunks_path):
    """chunks.jsonl → (본문, 위치) — 위치 = "<doc>#p<page>"(없으면 chunk seq)."""
    with open(chunks_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            loc = f"{c.get('doc', '?')}#p{c.get('page') if c.get('page') is not None else c.get('seq', '?')}"
            yield c.get("chunk_text", ""), loc


def _glossary(folder):
    """기준 사전(approved) — None = 마스터 표, 폴더 = 그 폴더 glossary.csv(마스터와 같은 길: read_csv → 옛 행 모양).
    옛 domain_terms.csv만 있는 폴더는 거부(낡은 사전을 조용히 읽지 않음 — `python -m common.store.master convert`로 옮김)."""
    if folder is None:
        return load_glossary()
    from common.core.terms import _master_glossary
    from common.store import master as M

    if not (Path(folder) / M.CSV_NAME).is_file():
        raise SystemExit(f"[glossary_suggest] {folder}에 {M.CSV_NAME} 없음 — 옛 CSV면 `python -m common.store.master convert`로 옮김")
    return dict(_master_glossary(M.Master(M.read_csv(Path(folder)))))


def build_rows(chunks_path, glossary_dir):
    glossary = {} if glossary_dir == "" else _glossary(glossary_dir)
    candidates = scan_definitions(_records(chunks_path))
    new = filter_definitions(candidates, glossary=glossary)
    today = datetime.date.today().isoformat()
    rows = []
    for i, c in enumerate(new, 1):
        rows.append(
            {
                "concept_id": f"DRAFT.{i:04d}",
                "canonical": c["term"],
                "category": "",
                "synonyms": "",
                "abbreviations": c["abbr"],
                "weak_synonyms": "",
                "broader": "",
                "related": "",
                "context_required": "",
                "case_sensitive": "Y",
                "definition_ko": "",
                "definition_en": "",
                "source": f"auto:count={c['count']};ex={c['example']}",
                "owner": "",
                "status": "draft",
                "updated": today,
            }
        )
    return rows, len(candidates)


def build_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", required=True, help="구조화 묶음 chunks.jsonl 경로")
    ap.add_argument("--out", default="output/glossary/domain_terms_draft.csv")
    ap.add_argument(
        "--glossary-dir",
        help="이미 있는 짝을 거를 기준 사전(approved만) — 기본 마스터 표, 폴더면 그 폴더 glossary.csv, 빈 문자열이면 안 거름",
    )
    return ap


def main(argv=None):
    a = build_cli().parse_args(argv)
    rows, n_candidates = build_rows(a.chunks, a.glossary_dir)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"후보 {n_candidates}건 중 새 후보 {len(rows)}건 → {out_path} (status=draft, 검색에 안 쓰임)")


if __name__ == "__main__":
    main()
