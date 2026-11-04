#!/usr/bin/env python3
"""중복 확인 (파싱 전 필수) → output/dedup/groups.csv · keep.txt · report.md

완전 중복만 묶는다 — 파일 내용 해시(SHA-256)가 같으면 대표 1개만 keep. **삭제·이동은 하지 않는다**.
(11-01 — 이름·내용 유사 후보(파일명 유사도, 텍스트 5-gram Jaccard, 이미지 dHash)는 지움: 후보는 groups.csv 보고용일 뿐
keep.txt를 줄이지 않았다 — keep은 늘 해시로만 정해짐. 사용자 10-31 범위 축소 grill, PRD pl-02.)

사용: python -m pipeline.extract.deduplication [--src <원본 문서 폴더>]   (--src 생략 시 DOC_DIR 필수)
이후: python -m pipeline.extract.run_all --only output/dedup/keep.txt   (대표만 파싱)
"""

import argparse
import csv
import functools
import os
import re
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.contract import file_hash
from common.core.paths import APP_ROOT, doc_dir  # 폴더 재편 뒤 이 상수만 바뀌면 됨

ROOT = APP_ROOT
_NOISE = re.compile(
    r"(\(\d+\)|\[\d+\]|[_\- ]?(copy|사본|복사본|최종|수정|final|rev\d*|v\d+(\.\d+)*)|(19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|\d{8})", re.I
)


def sha(p):
    return file_hash(p)  # fp-perf C2 — 한 곳(같은 프로세스 안에서는 파일당 한 번 읽음)


def fingerprint_one(p, source_id=None):
    """파일 하나의 지문(캐시 없이, 1회 계산) — fingerprints()의 캐시 미스 계산과 공유. **폴더 모드
    (fingerprints()·decide()·run_folder) 전용** — 크기·수정 시각·해시(11-01 — 유사 후보용 sketch·ahash·name은 지움).
    source_id — 원천의 진짜 식별자(원격 URI·key, 폴더면 원본 폴더 기준 file:// URI) — load_manifest()가
    이것으로 "같은 문서"를 가린다(독립 검토 #3 재검토: file_name만으로 가리면 서로 다른 경로·접두의 같은
    이름 문서가 하나로 뭉개진다, 아래 load_manifest 참고).
    (스트리밍 파싱과 그 전용 최소 지문 record_fingerprint는 op-08에 지움.)"""
    st = p.stat()
    r = {
        "path": str(p),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "sha": sha(p),
        "file_name": p.name,  # 독립 검토(10-14) — 사람이 읽는 이름(표시용) · load_manifest의 식별 키는
        # source_id 우선(아래), source_id가 없을 때만 (file_name, sha) 폴백으로 씀
        "source_id": source_id,
    }
    return r


def fingerprints(files, cache_path):
    """파일별 지문 {sha, size, mtime} — (경로·크기·수정 시각)이 같으면
    캐시(fingerprints.jsonl) 재사용: 수집 서버처럼 문서가 많을 때 다시 돌려도 새·바뀐 파일만 읽음."""
    import json

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
        if r is None or "sha" not in r:  # 옛 캐시 줄(sketch·ahash 포함)도 sha만 있으면 그대로 씀
            r = fingerprint_one(p)
        info.append(r)
    cache_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in info) + "\n", encoding="utf-8")
    return info


def _manifest_lock_path(manifest_path):
    return Path(str(manifest_path) + ".lock")


def _lock_pid_alive(pid):
    """잠금을 쥔 프로세스가 살아 있는지(Windows는 tasklist, 그 밖은 signal 0)."""
    if os.name == "nt":
        import subprocess

        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
        out = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_manifest_lock(lock, max_wait=30.0, poll=0.02):
    """O_EXCL 잠금 + 죽은 프로세스 자동 회수(독립 검토 #2) — 서로 다른 프로세스 둘이 같은 매니페스트에
    동시에 쓸 때만 줄 경계가 안 섞이게 기다린다(거부가 아니라 대기 — 여러 쓰기가 다 끝나야 하는 경우라
    순서대로 기다렸다 쓴다). **같은 프로세스 안의 동시 호출은 이 잠금이 막을 일이 없다**(코디네이터 메모 10-14)."""
    import time

    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            finally:
                os.close(fd)
            return
        except FileExistsError as err:
            try:
                other_pid = int(lock.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                other_pid = None
            if not (other_pid and _lock_pid_alive(other_pid)):
                try:
                    lock.unlink()  # 죽은 프로세스의 잠금 — 치우고 다시 시도
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - t0 > max_wait:
                raise SystemExit(f"[dedup] manifest 잠금({lock})을 {max_wait}초 안에 못 얻음 — 다른 프로세스와 계속 경합") from err
            time.sleep(poll)


def append_manifest(record, manifest_path):
    """지문 1개를 append-only JSONL에 **한 줄만** 덧붙임(열어서 쓰기 — 독립 검토 #2: 전엔 전체를 다시
    읽고 통째로 바꿔 써서 O(n²)였다). 서로 다른 프로세스가 같은 매니페스트에 동시에 쓸 수 있어(스트리밍
    여러 인스턴스·parse_parallel.py) 쓰기 전 파일 잠금(_acquire_manifest_lock)으로 줄 경계가 안 섞이게
    한다."""
    import json

    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lock = _manifest_lock_path(manifest_path)
    _acquire_manifest_lock(lock)
    try:
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        _unlink_retry(lock)


def _unlink_retry(p, tries=5):
    """Windows 실측(10-14) — 다른 프로세스가 같은 잠금 파일을 막 읾고 있는 사이 unlink()하면 짧게
    PermissionError가 난다(common/atomic.py._replace와 같은 성격) — 그 오류만 짧게 재시도."""
    import time

    for i in range(tries):
        try:
            p.unlink(missing_ok=True)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02 * (i + 1))


def record_duplicate(manifest_path, source_id, duplicate_of, etag=None, size=None, updated_at=None, sha=None):
    """받기 전(ETag+크기, 비멀티파트 전제) 또는 받은 뒤(sha256)에 다른 원천과 완전히 같은 내용으로 판단된
    문서 — `duplicate_of`(일치한 다른 원천의 source_id)를 남겨 결정이 사람에게도 보이게 한다(요건 — "기록해
    다시 안 받고 결정이 보이게"). 받기 전 판단이면 파일이 없어 sha는 모름(None 그대로)."""
    append_manifest(
        {"source_id": source_id, "updated_at": updated_at, "etag": etag, "size": size, "sha": sha, "duplicate_of": duplicate_of},
        manifest_path,
    )


def find_duplicate(manifest_path, source_id, *, etag=None, size=None, sha=None):
    """다른 원천(source_id가 다른) 기존 지문 중 이 문서와 완전히 같은 내용으로 볼 수 있는 것 — 있으면 그
    지문(dict), 없으면 None. `sha`가 주어지면 sha256 일치(받은 뒤 확인, 가장 믿을 수 있음)만 본다 ·
    아니면 `etag`+`size` 일치(받기 전 확인 — 비멀티파트 ETag 전제는 호출부 fetch_docs.py가 보장)만 본다.
    load_manifest()가 이미 source_id별 최신 1개로 정리해 주므로 그 결과만 본다(2026-10-14 재설계 —
    근사 중복은 더 안 봄, 완전 중복만 — pipeline/extract/fetch_docs.py의 받기 전·받은 뒤 확인이 쓴다)."""
    for r in load_manifest(manifest_path):
        if r.get("source_id") == source_id:
            continue
        if sha is not None:
            if r.get("sha") == sha:
                return r
        elif etag is not None and size is not None and r.get("etag") == etag and r.get("size") == size:
            return r
    return None


def load_manifest(manifest_path):
    """매니페스트(append-only) → 원본 식별자별 가장 최근 지문 1개만. 식별자 = source_id(원천의 진짜 URI·
    key — 호출부가 넘겼으면)가 있으면 그것, 없으면 sha256 폴백(2026-10-14 재설계 —
    최소 지문은 file_name을 안 담아 (file_name, sha) 폴백을 못 쓴다; sha만으로도 같은 내용 재기록은
    여전히 1건으로 합쳐지고, 내용이 바뀌면 다른 키가 되어 옛 지문이 같이 남는 것도 그대로다 — 알려진
    한계, source_id가 있는 경로에서는 안 생김) — 독립 검토 #3 재검토(file_name만으로 묶으면 서로 다른
    경로·접두의 "다른" 문서가 하나로 뭉개지는 문제)는 source_id 우선 규칙 그대로 유지.
    알려진 한계: 코퍼스에서 완전히 빠진(삭제된) 이름은 이 함수만으로는 못 가려낸다 — 가지치기가 필요하면
    호출 쪽이 살아있는 이름 목록과 대조해야 한다."""
    manifest_path = Path(manifest_path)
    try:
        st = manifest_path.stat()
    except OSError:
        return []
    return list(_load_manifest(str(manifest_path.resolve()), st.st_size, st.st_mtime_ns))


@functools.lru_cache(maxsize=8)
def _load_manifest(path, size, mtime_ns):
    """load_manifest 본체 — 파일(경로·크기·고친 시각)이 같으면 다시 읽지 않음(fp-perf C5: 문서마다 받기 전·받은 뒤 두 번 읽던 것).
    다른 프로세스가 덧붙이면 크기·시각이 바뀌어 다시 읽는다."""
    import json

    last = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            key = r.get("source_id") or r.get("sha")
            last[key] = r
    return tuple(last.values())


def _rep_select(members, info):
    """그룹 안 대표 선택 — 이름에 노이즈 표시("(1)"·"사본" 등) 없음 → 최신 수정 → 큰 파일. info(지문)만
    보면 되므로 파일이 없어도(매니페스트 모드) 그대로 쓸 수 있다."""
    return max(members, key=lambda i: (not _NOISE.search(Path(info[i]["path"]).stem), info[i]["mtime"], info[i]["size"]))


def decide(info):
    """같은 해시(완전 중복)끼리 묶고 keep 목록·groups.csv 행을 만든다 — 폴더 모드(run_folder) 전용. 스트리밍은
    pipeline/extract/fetch_docs.py의 받기 전·받은 뒤 확인(find_duplicate)이 완전 중복만 본다."""
    groups = {}
    for i, r in enumerate(info):
        groups.setdefault(r["sha"], []).append(i)
    keep, rows, gid = [], [], 0
    for members in groups.values():
        rep = _rep_select(members, info)
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
    return keep, rows, gid


def _write_report(out, rows, gid, n, n_keep):
    """report.md — decide()가 낸 rows·keep 개수를 사람이 보는 형태로만(판정은 이미 끝남)."""
    rep = [f"# 중복 확인 — 파일 {n}개 → 대표 {n_keep}개", "", f"- 완전 중복 그룹 {gid}개", "- 삭제·이동은 하지 않았다.", ""]
    for g in sorted({r["group"] for r in rows}):
        rep.append(f"## 그룹 {g}")
        rep += [f"- {'★ ' if r['representative'] else ''}{r['file']} [{r['decision']}]" for r in rows if r["group"] == g]
    (out / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:4]))


def run_folder(src, out):
    """폴더 모드 전체(main()이 부름) — 파일 해시(fingerprints, 캐시)로 decide() 판정, keep.txt·groups.csv·report.md를 쓴다."""
    files = sorted(p for p in Path(src).iterdir() if p.is_file() and p.name != ".gitkeep")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    info = fingerprints(files, out / "fingerprints.jsonl")
    keep, rows, gid = decide(info)
    with (out / "groups.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "file", "representative", "reasons", "sha256", "size", "decision"])
        w.writeheader()
        w.writerows(rows)
    (out / "keep.txt").write_text("\n".join(sorted(keep)) + "\n", encoding="utf-8")
    _write_report(out, rows, gid, len(files), len(keep))
    return keep, rows, gid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src", default=None, help="원본 문서 폴더(기본 DOC_DIR env — --help·import 때는 안 풀어야 하므로 여기서는 default=None)"
    )
    ap.add_argument("--out", default=str(ROOT / "output" / "dedup"))
    a = ap.parse_args()
    src = a.src or str(doc_dir())
    run_folder(src, a.out)


if __name__ == "__main__":
    utf8_stdout()
    main()
