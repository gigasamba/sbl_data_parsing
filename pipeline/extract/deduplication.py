#!/usr/bin/env python3
"""중복 문서 감지 — 파일 내용 해시(SHA-256)가 같은 문서(완전 중복)를 찾는다. 삭제·이동은 하지 않는다(PRD pl-02).

- 폴더: run_folder() → <out>/keep.txt(대표만) · groups.csv · report.md · fingerprints.jsonl(다시 돌릴 때 캐시)
- 원본 받기(fetch_docs): find_duplicate()·record_duplicate() — 다른 원천과 같은 내용인지 <out>/dedup/manifest.jsonl로 본다

사용: python -m pipeline.extract.deduplication [--src <원본 문서 폴더>] [--out <폴더>]   (--src 생략 시 DOC_DIR)
"""

import argparse
import csv
import functools
import json
import os
import re
import time
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.contract import file_hash
from common.core.paths import APP_ROOT, doc_dir

# 대표 고르기 — 이름에 사본 표시("(1)"·"사본"·날짜 등)가 없는 것 → 최신 수정 → 큰 파일
_NOISE = re.compile(
    r"(\(\d+\)|\[\d+\]|[_\- ]?(copy|사본|복사본|최종|수정|final|rev\d*|v\d+(\.\d+)*)|(19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|\d{8})", re.I
)


def run_folder(src, out):
    """폴더의 파일을 해시로 묶어 대표만 keep — (keep 이름 목록, groups.csv 행, 중복 그룹 수).
    지문은 (경로·크기·수정 시각)이 같으면 fingerprints.jsonl 캐시를 다시 쓴다(새·바뀐 파일만 읽음)."""
    files = sorted(p for p in Path(src).iterdir() if p.is_file() and p.name != ".gitkeep")
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
            r = {"path": str(p), "size": st.st_size, "mtime": st.st_mtime, "sha": file_hash(p), "file_name": p.name, "source_id": None}
        info.append(r)
    cache_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in info) + "\n", encoding="utf-8")

    groups: dict[str, list[int]] = {}
    for i, r in enumerate(info):
        groups.setdefault(r["sha"], []).append(i)
    keep, rows, gid = [], [], 0
    for members in groups.values():
        rep = max(members, key=lambda i: (not _NOISE.search(Path(info[i]["path"]).stem), info[i]["mtime"], info[i]["size"]))
        keep.append(Path(info[rep]["path"]).name)
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
    (out / "keep.txt").write_text("\n".join(sorted(keep)) + "\n", encoding="utf-8")
    report = [f"# 중복 확인 — 파일 {len(files)}개 → 대표 {len(keep)}개", "", f"- 완전 중복 그룹 {gid}개", "- 삭제·이동은 하지 않았다.", ""]
    for g in sorted({r["group"] for r in rows}):
        report.append(f"## 그룹 {g}")
        report += [f"- {'★ ' if r['representative'] else ''}{r['file']} [{r['decision']}]" for r in rows if r["group"] == g]
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:4]))
    return keep, rows, gid


def find_duplicate(manifest_path, source_id, sha):
    """다른 원천(source_id가 다른)의 기록 중 sha256이 같은 것 — 있으면 그 기록(dict), 없으면 None.
    매니페스트는 덧붙이기만 하므로 원천(source_id, 없으면 sha)마다 마지막 줄만 본다."""
    p = Path(manifest_path)
    try:
        st = p.stat()
    except OSError:
        return None
    for r in _manifest_rows(str(p.resolve()), st.st_size, st.st_mtime_ns):
        if r.get("source_id") != source_id and r.get("sha") == sha:
            return r
    return None


@functools.lru_cache(maxsize=8)
def _manifest_rows(path, size, mtime_ns):
    """매니페스트 읽기 — (경로·크기·고친 시각)이 같으면 다시 읽지 않는다(문서마다 두 번 읽던 것)."""
    last = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            last[r.get("source_id") or r.get("sha")] = r
    return tuple(last.values())


def record_duplicate(manifest_path, source_id, duplicate_of, etag=None, size=None, updated_at=None, sha=None):
    """완전 중복으로 판단한 문서를 매니페스트에 한 줄 덧붙인다(`duplicate_of` = 일치한 다른 원천 — 다시 안 받고 결정이 보이게).
    다른 프로세스와 줄이 섞이지 않게 O_EXCL 잠금 파일(<매니페스트>.lock)을 잡는다 — 다른 프로세스가 쥐고 있으면 최대 30초 기다리고,
    쥔 프로세스가 죽었으면 잠금을 치우고 다시 잡는다."""
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lock = Path(str(manifest_path) + ".lock")
    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            finally:
                os.close(fd)
            break
        except FileExistsError as err:
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pid = None
            alive = False
            if pid and os.name == "nt":
                import subprocess

                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
                alive = str(pid) in (r.stdout.decode("utf-8", errors="replace") if r.stdout else "")
            elif pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    pass
            if not alive:
                lock.unlink(missing_ok=True)  # 죽은 프로세스의 잠금 — 치우고 다시 시도
                continue
            if time.monotonic() - t0 > 30.0:
                raise SystemExit(f"[dedup] manifest 잠금({lock})을 30초 안에 못 얻음 — 다른 프로세스와 계속 경합") from err
            time.sleep(0.02)
    try:
        record = {"source_id": source_id, "updated_at": updated_at, "etag": etag, "size": size, "sha": sha, "duplicate_of": duplicate_of}
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        for i in range(5):  # Windows — 다른 프로세스가 잠금 파일을 막 읽는 사이면 잠깐 PermissionError
            try:
                lock.unlink(missing_ok=True)
                break
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.02 * (i + 1))


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None, help="원본 문서 폴더(기본 DOC_DIR — --help 때는 풀지 않게 default=None)")
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "dedup"))
    a = ap.parse_args()
    run_folder(a.src or str(doc_dir()), a.out)
