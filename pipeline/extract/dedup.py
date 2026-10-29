#!/usr/bin/env python3
"""중복 확인 (파싱 전 필수) → output/dedup/groups.csv · keep.txt · report.md

세 단계로 묶고, **삭제·이동은 하지 않는다**(사람이 groups.csv를 보고 확정):
  1. 완전 중복   — 파일 내용 해시(SHA-256)가 같음 → 자동으로 대표 1개만 keep
  2. 이름 유사   — 정규화한 파일명이 같거나 유사도 ≥ --name-sim(기본 0.9): "(1)"·"_v2"·"사본"·"최종"·날짜·공백/기호 차이
  3. 내용 유사   — 형식별 지문: 텍스트(오피스·txt·텍스트 PDF)는 문자 5-gram Jaccard ≥ --text-sim(기본 0.9),
                   이미지·이미지 PDF는 첫 쪽 차이 해시(dHash 16×16=256비트) 해밍 거리 ≤ --img-dist(기본 20)
  2·3은 **후보**일 뿐 — 같은 양식의 다른 문서도 이미지 해시가 거의 같다(개발 PC 실측: 다른 계약서 거리 5,
  같은 문서의 흐린 사본 16). 그래서 keep.txt에서는 **완전 중복만 빼고** 후보는 모두 남긴다.
  사람이 report.html(그룹별 썸네일)을 보고 groups.csv decision을 '같은 문서'로 바꾼 것만 keep.txt에서 뺀다.

사용: python modules/parse/dedup.py [--src <원본 문서 폴더>]   (--src 생략 시 DOC_DIR env 필수)
이후: python modules/parse/run_all.py --only output/dedup/keep.txt   (대표만 파싱)
"""

import argparse
import csv
import difflib
import hashlib
import os
import re
import unicodedata
import zipfile
import zlib
from collections import Counter
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, doc_dir  # 폴더 재편 뒤 이 상수만 바뀌면 됨
from pipeline import config as pc  # S7c: 설정 객체(옛 os.environ 읽기)

ROOT = APP_ROOT
IMG = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
_NOISE = re.compile(
    r"(\(\d+\)|\[\d+\]|[_\- ]?(copy|사본|복사본|최종|수정|final|rev\d*|v\d+(\.\d+)*)|(19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|\d{8})", re.I
)


def norm_name(p):
    s = unicodedata.normalize("NFKC", p.stem).lower()
    s = _NOISE.sub("", s)
    return re.sub(r"[\s_\-.()\[\]]+", "", s)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def text_of(p):
    """값싼 텍스트 추출(지문용). 실패하면 ''."""
    ext = p.suffix.lower()
    try:
        if ext == ".txt":
            raw = p.read_bytes()
            for enc in ("utf-8-sig", "cp949", "utf-16"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    pass
            return raw.decode("utf-8", "ignore")
        if ext in (".docx", ".xlsx", ".pptx"):
            with zipfile.ZipFile(p) as z:
                return " ".join(
                    re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore"))
                    for n in z.namelist()
                    if n.endswith(".xml")
                    and ("word/document" in n or "sharedStrings" in n or "slides/slide" in n or "worksheets/sheet" in n)
                )
        if ext == ".pdf":
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(p))
            return " ".join(doc[i].get_textpage().get_text_range() for i in range(min(len(doc), 20)))
        if ext == ".xls":
            from python_calamine import CalamineWorkbook

            wb = CalamineWorkbook.from_path(str(p))
            return " ".join(str(c) for n in wb.sheet_names for r in wb.get_sheet_by_name(n).to_python() for c in r)
    except Exception:
        return ""
    return ""


def shingles(t, k=5):
    t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", t))
    return {t[i : i + k] for i in range(max(len(t) - k + 1, 0))}


def first_page(p):
    from PIL import Image

    if p.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        return pdfium.PdfDocument(str(p))[0].render(scale=0.5).to_pil()
    return Image.open(p)


def dhash(p, n=16):
    """첫 쪽(또는 이미지)의 차이 해시 n×n비트 — 이웃 화소보다 밝은지. 실패하면 None."""
    try:
        b = first_page(p).convert("L").resize((n + 1, n)).tobytes()
        return sum(1 << (r * n + c) for r in range(n) for c in range(n) if b[r * (n + 1) + c] > b[r * (n + 1) + c + 1])
    except Exception:
        return None


def thumb(p):
    import base64
    import io

    try:
        im = first_page(p).convert("RGB")
        im.thumbnail((360, 480))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


_SH: dict = {}


def _shingles_of(p):
    """텍스트 5-gram 집합(후보 쌍 확인 때만 계산 — 메모리에 전부 들고 있지 않음)."""
    if p not in _SH:
        if len(_SH) >= 5000:  # 상한 — 문서가 많으면 전부 들고 있지 않음(필요하면 다시 읽음)
            _SH.clear()
        t = text_of(p)
        _SH[p] = shingles(t) if len(t.strip()) >= 50 else set()
    return _SH[p]


def fingerprint_one(p, source_id=None):
    """파일 하나의 지문(캐시 없이, 1회 계산) — fingerprints()의 캐시 미스 계산과 공유. **폴더 모드
    (fingerprints()·decide()·run_folder) 전용** — 이름 유사·내용 유사(sketch·ahash) 후보까지 낸다.
    source_id — 원천의 진짜 식별자(원격 URI·key, 폴더면 원본 폴더 기준 file:// URI) — load_manifest()가
    이것으로 "같은 문서"를 가린다(독립 검토 #3 재검토: file_name만으로 가리면 서로 다른 경로·접두의 같은
    이름 문서가 하나로 뭉개진다, 아래 load_manifest 참고).
    스트리밍·병렬(parse/stream.py·cli/parse_parallel.py)은 이 함수를 쓰지 않는다 — `record_fingerprint()`가
    훨씬 적은 필드만 쓴다(2026-10-14 재설계: 근사 중복 후보는 사람이 안 보는 산출물이라 뺐다 — 아래
    `record_fingerprint` 설명)."""
    st = p.stat()
    t = text_of(p) if p.suffix.lower() not in IMG else ""
    sh = shingles(t) if len(t.strip()) >= 50 else None
    r = {
        "path": str(p),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "sha": sha(p),
        "name": norm_name(p),
        "file_name": p.name,  # 독립 검토(10-14) — 사람이 읽는 이름(표시용) · load_manifest의 식별 키는
        # source_id 우선(아래), source_id가 없을 때만 (file_name, sha) 폴백으로 씀
        "source_id": source_id,
        "sketch": sorted({zlib.crc32(x.encode("utf-8")) for x in sh})[:64] if sh else None,
        "ahash": dhash(p) if (p.suffix.lower() in IMG or (p.suffix.lower() == ".pdf" and len(t.strip()) < 50)) else None,
    }
    return r


def fingerprints(files, cache_path):
    """파일별 지문 {sha, name, sketch(텍스트 5-gram 해시 중 가장 작은 64개), ahash, size, mtime} — (경로·크기·수정 시각)이 같으면
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
        r = cache.get((str(p), st.st_size, st.st_mtime)) or fingerprint_one(p)
        info.append(r)
    cache_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in info) + "\n", encoding="utf-8")
    return info


def _manifest_lock_path(manifest_path):
    return Path(str(manifest_path) + ".lock")


def _lock_pid_alive(pid):
    """parse/stream.py._pid_alive와 같은 판정 — dedup↔stream 순환 import를 피하려고 그대로 복붙한다
    (둘 다 10줄 안팎이라 공용 모듈로 뽑는 비용이 더 큼)."""
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
    """O_EXCL 잠금 + 죽은 프로세스 자동 회수(parse/stream.py와 같은 패턴, 독립 검토 #2) — 서로 다른
    프로세스 둘이 같은 매니페스트에 동시에 쓸 때(예: 스트리밍 두 인스턴스가 서로 다른 PARSE_TMP로 동시에
    돌 때)만 줄 경계가 안 섞이게 기다린다(거부가 아니라 대기 — stream.py의 '이미 돌고 있음 거부'와 달리
    여러 쓰기가 다 끝나야 하는 경우라 순서대로 기다렸다 쓴다). **같은 프로세스 안의 동시 호출은 이 잠금이
    막을 일이 없다** — 호출부(parse_parallel.py는 게시 전용 스레드 하나, stream.py는 배치를 순차 처리)가
    이미 한 스레드로 몰아 둔다(코디네이터 메모 10-14)."""
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


def record_fingerprint(p, manifest_path, source_id=None, etag=None, updated_at=None):
    """스트리밍(parse/stream.py)·병렬(cli/parse_parallel.py) 전용 — 원본이 지워지기 전에 **최소** 지문
    (source_id·updated_at·etag·size·sha256)만 매니페스트(보통 output/dedup/manifest.jsonl)에 append-only로
    남긴다. 2026-10-14 재설계(사용자 결정) — 근사 중복(MinHash·이미지 dHash·64개 sketch)은 뺐다: keep 결정은
    완전 중복(sha256)만으로 이미 정해지고(decide()의 by_sha 선택 — 근사 중복 연결은 keep 집합을 줄이지
    않는다), 근사 중복 후보는 사람이 보는 report.html용 부산물일 뿐인데 스트리밍에선 파일이 없어 그 report도
    못 만든다(아무도 안 보는 산출물, no-human-in-loop). 완전 중복 판정 자체는 parse/source.py의 받기 전
    (ETag+크기)·받은 뒤(sha256) 확인이 `find_duplicate()`로 한다 — 이 함수는 지문만 남긴다.
    source_id — 원천의 진짜 식별자(원격 URI·key·폴더면 file:// URI) — load_manifest()가 같은 이름·다른
    경로의 서로 다른 문서를 안 뭉개게 한다(독립 검토 #3 재검토, 그대로 유지)."""
    p = Path(p)
    append_manifest(
        {"source_id": source_id, "updated_at": updated_at, "etag": etag, "size": p.stat().st_size, "sha": sha(p)}, manifest_path
    )


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
    아니면 `etag`+`size` 일치(받기 전 확인 — 비멀티파트 ETag 전제는 호출부 source.py가 보장)만 본다.
    load_manifest()가 이미 source_id별 최신 1개로 정리해 주므로 그 결과만 본다(2026-10-14 재설계 —
    근사 중복은 더 안 봄, 완전 중복만 — parse/source.py의 받기 전·받은 뒤 확인이 쓴다)."""
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
    key — 호출부가 record_fingerprint에 넘겼으면)가 있으면 그것, 없으면 sha256 폴백(2026-10-14 재설계 —
    최소 지문은 file_name을 안 담아 (file_name, sha) 폴백을 못 쓴다; sha만으로도 같은 내용 재기록은
    여전히 1건으로 합쳐지고, 내용이 바뀌면 다른 키가 되어 옛 지문이 같이 남는 것도 그대로다 — 알려진
    한계, source_id가 있는 경로에서는 안 생김) — 독립 검토 #3 재검토(file_name만으로 묶으면 서로 다른
    경로·접두의 "다른" 문서가 하나로 뭉개지는 문제)는 source_id 우선 규칙 그대로 유지.
    알려진 한계: 코퍼스에서 완전히 빠진(삭제된) 이름은 이 함수만으로는 못 가려낸다 — 가지치기가 필요하면
    호출 쪽이 살아있는 이름 목록과 대조해야 한다."""
    import json

    manifest_path = Path(manifest_path)
    last = {}
    if manifest_path.exists():
        for ln in manifest_path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                key = r.get("source_id") or r.get("sha")
                last[key] = r
    return list(last.values())


def _rep_select(members, info):
    """그룹 안 대표 선택 — 이름에 노이즈 표시("(1)"·"사본" 등) 없음 → 최신 수정 → 큰 파일. info(지문)만
    보면 되므로 파일이 없어도(매니페스트 모드) 그대로 쓸 수 있다."""
    return max(members, key=lambda i: (not _NOISE.search(Path(info[i]["path"]).stem), info[i]["mtime"], info[i]["size"]))


def decide(info, img_dist, name_sim, text_sim, fuzzy, jaccard_of):
    """DSU로 완전 중복·이름 유사·내용 유사 그룹을 묶고 keep 목록·groups.csv 행을 만든다 — **폴더 모드
    (run_folder) 전용**(2026-10-14 재설계로 스트리밍용 decide_from_manifest()는 없앴다 — 스트리밍은 완전
    중복만 보고, 그 판정은 parse/source.py의 받기 전·받은 뒤 확인(find_duplicate)이 한다. keep 집합 자체는
    근사 중복 연결 여부와 무관하게 "그룹 안 같은 sha는 대표 1개만"으로만 줄어든다는 사실이 이 설계 변경의
    근거: by_sha 선택이 항상 sha로만 걸러, 이름·텍스트·이미지 유사 연결은 groups.csv 보고용일 뿐 keep을
    더 줄이지 않는다)."""
    n = len(info)
    for r in info:
        r["sk"] = set(r["sketch"]) if r["sketch"] else None
    cand = candidate_pairs(info, img_dist=img_dist, name_sim=name_sim, fuzzy_names=fuzzy)
    dsu, reasons = DSU(n), {}

    def link(i, j, why):
        dsu.union(i, j)
        reasons.setdefault((min(i, j), max(i, j)), []).append(why)

    for i, j in cand["sha"]:
        if info[i]["sha"] == info[j]["sha"]:
            link(i, j, "완전 중복(해시)")
    for i, j in cand["name"]:
        A, B = info[i]["name"], info[j]["name"]
        if info[i]["sha"] != info[j]["sha"] and (A == B or (fuzzy and name_ratio(A, B, name_sim) >= name_sim)):
            link(i, j, f"이름 유사({difflib.SequenceMatcher(None, A, B).ratio():.2f})")
    for i, j in cand["text"]:
        A, B = info[i]["sk"], info[j]["sk"]
        # 최소 해시 64개 중 겹치는 수로 먼저 거름(후보 쌍만 정확 Jaccard 계산) — main()과 같은 1차 필터
        if info[i]["sha"] != info[j]["sha"] and A and B and len(A & B) >= 0.6 * min(len(A), len(B)):
            jac = jaccard_of(i, j)
            if jac >= text_sim:
                link(i, j, f"내용 유사(텍스트 {jac:.2f})")
    for i, j in cand["img"]:
        if info[i]["sha"] != info[j]["sha"]:
            d = bin(info[i]["ahash"] ^ info[j]["ahash"]).count("1")
            if d <= img_dist:
                link(i, j, f"내용 유사(이미지 거리 {d})")

    groups = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(i)
    why_of = {}
    for (x, y), ws in reasons.items():
        why_of.setdefault(x, set()).update(ws)
        why_of.setdefault(y, set()).update(ws)
    keep, rows, gid = [], [], 0
    for members in groups.values():
        rep = _rep_select(members, info)
        by_sha = {}
        for i in sorted(members, key=lambda i: i != rep):  # 해시별 1개(대표 우선) — 후보는 전부 keep
            by_sha.setdefault(info[i]["sha"], i)
        keep += [Path(info[i]["path"]).name for i in by_sha.values()]
        if len(members) == 1:
            continue
        gid += 1
        n_sha = Counter(info[m]["sha"] for m in members)
        for i in sorted(members):
            why = sorted(why_of.get(i, ()))
            exact = n_sha[info[i]["sha"]] > 1
            rows.append(
                {
                    "group": gid,
                    "file": Path(info[i]["path"]).name,
                    "representative": "예" if i == rep else "",
                    "reasons": "; ".join(why),
                    "sha256": info[i]["sha"][:12],
                    "size": info[i]["size"],
                    "decision": ("중복(자동 제외)" if i not in by_sha.values() else "해시 대표") if exact else "확인 필요",
                }
            )
    return keep, rows, gid


def name_ratio(x, y, r):
    """difflib 유사도 — 값싼 상한(real_quick·quick)이 r 미만이면 0(같은 판정, 계산만 줄임)."""
    sm = difflib.SequenceMatcher(None, x, y)
    return sm.ratio() if sm.real_quick_ratio() >= r and sm.quick_ratio() >= r else 0.0


def candidate_pairs(info, img_bits=256, img_dist=20, name_sim=0.9, sketch_k=8, name_min=0.8, fuzzy_names=True):
    """후보 쌍(i<j) — 판정 기준을 만족할 수 있는 쌍만:
    해시 같음 · 이미지 해시를 (거리+1)조각으로 나눠 한 조각이라도 같음(비둘기집 — 거리 ≤ img_dist면 반드시 걸림) ·
    텍스트 최소 해시 sketch_k개 중 하나라도 같음(Jaccard ≥ 0.9면 거의 확실히 겹침) · 이름은 유사도 하한에서 계산한 3글자 조각 공유 수 이상(짧은 이름은 글자 몇 개 지운 형태가 같음)."""
    from collections import defaultdict

    out, pairs = {}, set()

    def add_block(keys):
        idx = defaultdict(list)
        for i, ks in keys:
            for k in ks:
                idx[k].append(i)
        for members in idx.values():
            if len(members) > 1:
                for x in range(len(members)):
                    for y in range(x + 1, len(members)):
                        pairs.add((min(members[x], members[y]), max(members[x], members[y])))

    add_block((i, [r["sha"]]) for i, r in enumerate(info))
    out["sha"], pairs = pairs, set()
    nb = img_dist + 1
    w = -(-img_bits // nb)
    add_block((i, [(b, (r["ahash"] >> (b * w)) & ((1 << w) - 1)) for b in range(nb)]) for i, r in enumerate(info) if r["ahash"] is not None)
    out["img"], pairs = pairs, set()
    # 텍스트: 최소 해시 중 '흔한 조각'(문서 DEDUP_COMMON_MAX(기본 max(200, 문서 2%))개 넘게 공통 = 양식·상용구)은 열쇠에서 뺌 —
    #   상용구 하나로 수천 문서가 한 묶음이 돼 쌍이 폭증(1만 문서 실측 2,800만 쌍). ponytail: 전부 상용구인 문서끼리는 이름·해시로만 걸림
    df = Counter(x for r in info if r["sketch"] for x in r["sketch"])
    cap = pc.cfg().extract.dedup.common_max  # S7c — 설정 객체(옛 `int(get or 계산)`: "0"은 0 — 그래서 None일 때만 계산)
    cap = int(cap) if cap is not None else max(200, len(info) // 50)
    add_block((i, [x for x in r["sketch"] if df[x] <= cap][:sketch_k]) for i, r in enumerate(info) if r["sketch"])
    out["text"], pairs = pairs, set()
    add_block((i, [r["name"]]) for i, r in enumerate(info) if r["name"])
    # 이름: 유사도 r 이상이면 맞지 않는 글자 U ≤ (1−r)(la+lb) — 글자 하나가 3글자 조각을 최대 3개 깨므로
    #   공유 조각 ≥ max(la, lb) − 2 − 3U(하한, 길이 합 ≥ 20에서 1 이상).
    names = {i: r["name"] for i, r in enumerate(info) if r["name"]} if fuzzy_names else {}
    grams = {i: [nm[k : k + 3] for k in range(max(len(nm) - 2, 1))] for i, nm in names.items()}
    idx = defaultdict(set)
    for i, gs in grams.items():
        for g in set(gs):
            idx[g].add(i)

    def len_ok(la, lb):
        return min(la, lb) >= name_min * max(la, lb)  # 유사도 r ≥ 0.9면 짧은 쪽 ≥ 0.818 × 긴 쪽

    # 짧은 쌍(길이 합 < 20)은 하한이 안 서므로: U ≤ d = ⌊(1−r)·19⌋ → 양쪽에서 글자를 d개 이하로 지우면 같은 문자열(공통 부분열)이 됨
    #   → 이름마다 '글자 d개 이하 지운 형태'를 열쇠로 묶음(r=0.9면 d=1). 같은 열쇠 = 후보.
    from itertools import combinations

    d = int((1 - name_sim) * 19 + 1e-9)
    add_block(
        (i, {"".join(c for k, c in enumerate(nm) if k not in rm) for m in range(d + 1) for rm in combinations(range(len(nm)), m)})
        for i, nm in names.items()
        if len(nm) <= 19
    )
    for i, gs in grams.items():
        cnt = defaultdict(int)
        for g in set(gs):
            if len(idx[g]) <= 5000:  # 아주 흔한 조각(수천 개 이름에 공통)은 세지 않음 — ponytail: 그런 이름끼리는 놓칠 수 있음
                for j in idx[g]:
                    if j > i:
                        cnt[j] += 1
        for j, c in cnt.items():
            la, lb = len(names[i]), len(names[j])
            u = int((1 - name_sim) * (la + lb) + 1e-9)
            if len_ok(la, lb) and c >= max(1, max(la, lb) - 2 - 3 * u):
                pairs.add((i, j))
    out["name"] = pairs
    return out


class DSU:
    def __init__(s, n):
        s.p = list(range(n))

    def find(s, x):
        while s.p[x] != x:
            s.p[x] = s.p[s.p[x]]
            x = s.p[x]
        return x

    def union(s, a, b):
        s.p[s.find(a)] = s.find(b)


def _write_report(src, out, rows, gid, n, n_keep):
    """report.md·report.html(그룹별 썸네일) — 폴더 모드만(파일이 있어야 썸네일을 그린다). decide()가 낸
    rows·keep 개수를 사람이 보는 형태로만 바꾼다(판정 자체는 이미 끝남)."""
    need = len({r["group"] for r in rows if r["decision"] == "확인 필요"})
    rep = [
        f"# 중복 확인 — 파일 {n}개 → 대표 {n_keep}개",
        "",
        f"- 중복 그룹 {gid}개 (완전 중복만인 그룹 {gid - need} · **사람 확인 필요 {need}**)",
        "- 확인 방법: `report.html`에서 썸네일을 보고 `groups.csv` decision을 '같은 문서'/'다른 판본'/'다른 문서'로 기록. '같은 문서'로 확정한 파일만 keep.txt에서 뺀다(후보는 기본으로 모두 keep)",
        "- 삭제·이동은 하지 않았다.",
        "",
    ]
    for g in sorted({r["group"] for r in rows}):
        rep.append(f"## 그룹 {g}")
        rep += [f"- {'★ ' if r['representative'] else ''}{r['file']} — {r['reasons']} [{r['decision']}]" for r in rows if r["group"] == g]
    (out / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    import html

    cards = []
    for g in sorted({r["group"] for r in rows}):
        items = "".join(
            f'<figure><img src="{thumb(Path(src) / r["file"])}" alt=""><figcaption>{"★ " if r["representative"] else ""}'
            f"{html.escape(r['file'])}<br><small>{html.escape(r['reasons'])} · {r['decision']}</small></figcaption></figure>"
            for r in rows
            if r["group"] == g
        )
        cards.append(f"<section><h2>그룹 {g}</h2><div class=row>{items}</div></section>")
    head = (
        '<meta charset="utf-8"><title>중복 후보</title><style>body{font-family:system-ui,sans-serif;margin:16px}'
        ".row{display:flex;gap:12px;flex-wrap:wrap}figure{margin:0;width:360px}img{max-width:100%;border:1px solid #ccc}"
        "small{color:#666}</style>"
    )
    (out / "report.html").write_text(head + "<br>".join(html.escape(x) for x in rep[:5]) + "".join(cards), encoding="utf-8")
    print("\n".join(rep[:5]))


def run_folder(src, out, name_sim=0.9, text_sim=0.9, img_dist=20):
    """폴더 모드 전체(main()이 부름) — 파일을 직접 읽어 지문을 내고(fingerprints, 캐시) decide()로 판정,
    keep.txt·groups.csv·report.md·report.html을 쓴다. 테스트가 CLI 없이 바로 부를 수 있게 main()에서
    분리. 이 동작은 2026-10-14 스트리밍 재설계와 무관(그대로) — 스트리밍은 더 이상 decide()를 쓰지 않고
    parse/source.py의 완전 중복 확인(find_duplicate)만 쓴다."""
    files = sorted(p for p in Path(src).iterdir() if p.is_file() and p.name != ".gitkeep")
    n = len(files)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    info = fingerprints(files, out / "fingerprints.jsonl")
    fuzzy = n <= int(
        pc.cfg().extract.dedup.fuzzy_max
    )  # S7c — 설정 객체(기본 50000) · 아주 많으면 이름은 정규화 이름 일치만(1만 문서 실측: 유사도 포함 13초)
    if not fuzzy:
        print(f"[안내] 문서 {n}개 > DEDUP_FUZZY_MAX — 이름은 정규화 이름(사본·버전·날짜 표시 제거) 일치만 비교", flush=True)

    def jaccard_of(i, j):
        # 최소 해시로 거른 후보만 — 파일에서 전체 5-gram을 다시 읽어 정확한 Jaccard(폴더 모드는 파일이 있음)
        ta, tb = _shingles_of(files[i]), _shingles_of(files[j])
        return len(ta & tb) / len(ta | tb) if ta and tb else 0

    keep, rows, gid = decide(info, img_dist=img_dist, name_sim=name_sim, text_sim=text_sim, fuzzy=fuzzy, jaccard_of=jaccard_of)
    with (out / "groups.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "file", "representative", "reasons", "sha256", "size", "decision"])
        w.writeheader()
        w.writerows(rows)
    (out / "keep.txt").write_text("\n".join(sorted(keep)) + "\n", encoding="utf-8")
    _write_report(src, out, rows, gid, n, len(keep))
    return keep, rows, gid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src", default=None, help="원본 문서 폴더(기본 DOC_DIR env — --help·import 때는 안 풀어야 하므로 여기서는 default=None)"
    )
    ap.add_argument("--out", default=str(ROOT / "output" / "dedup"))
    ap.add_argument("--name-sim", type=float, default=0.9)
    ap.add_argument("--text-sim", type=float, default=0.9)
    ap.add_argument("--img-dist", type=int, default=20)
    a = ap.parse_args()
    src = a.src or str(doc_dir())
    run_folder(src, a.out, name_sim=a.name_sim, text_sim=a.text_sim, img_dist=a.img_dist)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("dedup"):
        main()
