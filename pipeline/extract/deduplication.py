#!/usr/bin/env python3
"""중복 문서 감지 — 한 번에 받은 원본 폴더 안에서 파일 내용 해시(SHA-256)가 같은 문서(완전 중복)를 찾는다. 삭제·이동은 하지 않는다.

- 폴더: run_folder() → (대표 {이름: sha256}, groups.csv 행, 그룹 수) · <out>/keep.txt(대표만 — write_keep=False면 안 씀: 받기
  candidate_ready._dedup은 자기 keep.txt를 씀) · groups.csv · report.md · fingerprints.jsonl(다시 돌릴 때 캐시)

사용: python -m pipeline.extract.deduplication [--src <원본 문서 폴더>] [--out <폴더>]   (--src 생략 시 DOC_DIR)
"""

import argparse
import csv
import json
import re
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, doc_dir
from pipeline.extract.candidate_pick import _hidden
from pipeline.shared.srcsha import sha_of

# 대표 고르기 — 이름에 사본 표시("(1)"·"사본"·날짜 등)가 없는 것 → 최신 수정 → 큰 파일
_NOISE = re.compile(
    r"(\(\d+\)|\[\d+\]|[_\- ]?(copy|사본|복사본|최종|수정|final|rev\d*|v\d+(\.\d+)*)|(19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|\d{8})", re.I
)


def run_folder(src, out, names=None, write_keep=True):
    """폴더의 파일(names를 주면 그 이름만 — 이번 묶음)을 해시로 묶어 대표만 keep — (keep {대표 이름: sha256}, groups.csv 행, 중복 그룹 수).
    write_keep=False면 <out>/keep.txt를 쓰지 않는다(부른 쪽이 씀). 파일이 1개 이하면 묶을 것이 없어 sha256만(받기가 manifest에 남긴 값 —
    srcsha.sha_of) 돌려주고 <out>에 아무것도 쓰지 않는다(keep.txt도).
    지문은 (경로·크기·수정 시각)이 같으면 fingerprints.jsonl 캐시를 다시 쓴다(새·바뀐 파일만 읽음)."""
    files = sorted(
        p for p in Path(src).iterdir() if p.is_file() and not _hidden(p) and p.name != ".gitkeep" and (names is None or p.name in names)
    )
    if len(files) <= 1:
        return {p.name: sha_of(p) for p in files}, [], 0
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / "fingerprints.jsonl"
    cache = {}
    if cache_path.exists():
        for ln in cache_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                cache[(r["path"], r["size"], r["mtime"])] = r
    info = []
    for p in files:
        st = p.stat()
        r = cache.get((str(p), st.st_size, st.st_mtime))
        if r is None or "sha" not in r:
            r = {"path": str(p), "size": st.st_size, "mtime": st.st_mtime, "sha": sha_of(p), "file_name": p.name, "source_id": None}
        info.append(r)
    cache_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in info) + "\n", encoding="utf-8")

    groups: dict[str, list[int]] = {}
    for i, r in enumerate(info):
        groups.setdefault(r["sha"], []).append(i)
    keep, rows, gid = {}, [], 0
    for members in groups.values():
        rep = max(members, key=lambda i: (not _NOISE.search(Path(info[i]["path"]).stem), info[i]["mtime"], info[i]["size"]))
        keep[Path(info[rep]["path"]).name] = info[rep]["sha"]
        if len(members) == 1:
            continue
        gid += 1
        for i in sorted(members):
            rows.append(
                {
                    "group": gid,
                    "file": Path(info[i]["path"]).name,
                    "representative": "예" if i == rep else "",
                    "reasons": "완전 중복(해시)",
                    "sha256": info[i]["sha"][:12],
                    "size": info[i]["size"],
                    "decision": "해시 대표" if i == rep else "중복(자동 제외)",
                }
            )

    with (out / "groups.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "file", "representative", "reasons", "sha256", "size", "decision"])
        w.writeheader()
        w.writerows(rows)
    if write_keep:
        (out / "keep.txt").write_text("\n".join(sorted(keep)) + "\n", encoding="utf-8")
    report = [f"# 중복 확인 — 파일 {len(files)}개 → 대표 {len(keep)}개", "", f"- 완전 중복 그룹 {gid}개", "- 삭제·이동은 하지 않았다.", ""]
    for g in sorted({r["group"] for r in rows}):
        report.append(f"## 그룹 {g}")
        report += [f"- {'★ ' if r['representative'] else ''}{r['file']} [{r['decision']}]" for r in rows if r["group"] == g]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:4]))
    return keep, rows, gid


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None, help="원본 문서 폴더(기본 DOC_DIR — --help 때는 풀지 않게 default=None)")
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "dedup"))
    a = ap.parse_args()
    run_folder(a.src or str(doc_dir()), a.out)
