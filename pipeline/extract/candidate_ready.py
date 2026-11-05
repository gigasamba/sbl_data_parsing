#!/usr/bin/env python3
"""파싱 대상 받기 — 고른 문서(candidate_pick)를 폴더 또는 Object Storage에서 받아 파싱 입력 폴더로 · 미리 받기(warm) · 중복 정리 호출 · 끝 정리.

  --source <서버 폴더>               같은 서버 폴더(샘플 데이터) — 그대로 씀
  --source rdb:csv:<경로>            문서 위치 표(csv — run_docs가 EDW FileStorageMap에서 만든 batch.csv)의 키만 Object Storage에서 받음

Object Storage 원본 처리: 대표 결과가 나온 문서의 내려받은 원본은 parse 뒤 바로 지움.
처리한 객체(ETag 또는 (key, 증분값))는 output/parse/_source/processed.jsonl에 기록 → 다음 실행에서 다시 받지 않음. 실패한 문서는 남겨 다음 실행이 다시 시도.
검색 결과의 원본 위치(source_uri) = s3://버킷/키(SOURCE_MANIFEST로 common.core.ids.source_uri가 읽음).
접속: OS_ENDPOINT · OS_ACCESS_KEY · OS_SECRET_KEY · OS_REGION(기본 us-east-1) · OS_VERIFY_TLS(기본 1, 사내 CA면 경로) — 비밀값은 settings.yaml에만.
받기 전 대조 — size가 있으면 ContentLength와 비교(크기 불일치는 참고 기록만).
"""

import csv
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from common.config import settings as C
from common.core import span as SP  # 성능 span
from common.core.console import utf8_stdout
from common.core.contract import jl
from common.core.contract import safe_path_join as _safe_join  # 경로 잇기(load 단계와 같은 함수)
from pipeline import config as pc
from pipeline.extract import candidate_pick as CP
from pipeline.extract.candidate_pick import _known_source, _processed_path, _rdb_bucket_and_key, _rdb_cols, _rdb_names, _tree_files


def _s3():
    """boto3 s3 클라이언트 — common.store.objectstore.client에 위임."""
    from common.store.objectstore import client

    return client()


# ── warm 저장소(프리페치) ──────────────────────────────────────────────
# 다음 배치 원본을 미리 받아 두는 1회용 캐시. `python -m pipeline.extract.candidate_ready warm --csv <배치csv>`(프리페치)가
# 파일을 내려 warm에 심고, 실제 파싱의 fetch_one이 같은 (bucket,key)를 만나면 네트워크 다운로드를 건너뛰고
# 곧바로 가져간다(warm에서 지움 — 사본 중복 저장 없음). SOURCE_WARM 미설정이면 전부 꺼진다(기존 동작 그대로).


def _warm_dir():
    """SOURCE_WARM — warm 저장소 폴더. 없으면 None(기능 꺼짐)."""
    v = pc.cfg().extract.source.warm  # S7c — 설정 객체
    return Path(v) if v else None


def _warm_index_path(wd):
    return wd / "_warm_index.jsonl"


def _warm_key_path(wd, bucket, key):
    return wd / (hashlib.sha1(f"{bucket}|{key}".encode()).hexdigest() + ".bin")


@contextmanager
def _warm_locked(wd):
    """warm 인덱스(읽기→고치기→쓰기)를 파싱(fetch_one의 _warm_take)·프리페치(warm 명령) 양쪽에서 잠근다
    (flock — 프로세스 간에도 유효). 잠금이 다르면 최악이 중복 다운로드일 뿐(맞잠금 실패해도 폴백 안전)."""
    wd.mkdir(parents=True, exist_ok=True)
    f = (wd / "_warm.lock").open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except ImportError:  # 비리눅스 개발 환경 — 잠금 없이 진행
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        f.close()


def _warm_read(wd):
    """인덱스의 살아있는 행들(bucket·key·path 있는 행만, 깨진 줄은 조용히 버림)."""
    p = _warm_index_path(wd)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
            if r.get("bucket") and r.get("key") and r.get("path"):
                out.append(r)
        except ValueError:
            pass
    return out


def _warm_write(wd, rows):
    _warm_index_path(wd).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _warm_take(o, dest, name):
    """fetch_one 안에서 — 이 (bucket,key)가 warm에 있으면 파일을 dest/name으로 옮겨 와 반환(다운로드 스킵).
    1회용(warm 인덱스와 파일에서 제거). csv 쪽 크기가 알려져 있고 warm 사본과 어긋나면(새 판이 올라온 경우)
    그 항목은 버리고 None(=네트워크 다운로드로)."""
    wd = _warm_dir()
    if not wd:
        return None
    with _warm_locked(wd):
        rows = _warm_read(wd)
        hit = next((i for i, r in enumerate(rows) if r["bucket"] == o["bucket"] and r["key"] == o["key"]), None)
        if hit is None:
            return None
        r = rows.pop(hit)
        _warm_write(wd, rows)
    p = Path(r["path"])
    if o["size"] is not None and r.get("size") is not None and int(r["size"]) != int(o["size"]):
        p.unlink(missing_ok=True)  # warm 사본이 새 판과 어긋남 — 버리고 재다운로드
        return None
    if not p.exists():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    f = _safe_join(dest, name)
    try:
        os.replace(p, f)  # 같은 볼륨(/app/output 안이면 rename)
    except OSError:
        shutil.move(str(p), str(f))  # 다른 볼륨일 때 폴백
    return f


def _warm_cmd(argv):
    """`python -m pipeline.extract.candidate_ready warm --csv <batch.csv> [--workers N]` — 다음 배치 원본을 미리 받아
    SOURCE_WARM에 심는 프리페치(배치 러너가 현재 배치 파싱 중에 백그라운드로 돌린다). watermark·처리 기록·
    manifest는 전혀 건드리지 않고 파일만 내려놓는다 — 실제 파싱(fetch_one)이 warm 적중으로 가져간다.
    한 건 실패는 그 배치가 늦어질 뿐(일반 다운로드로 폴백)이라 조용히 넘어간다."""
    import argparse

    ap = argparse.ArgumentParser(prog="pipeline.extract.candidate_ready warm")
    ap.add_argument("--csv", required=True, help="make_batch.py가 만든 다음 배치 csv(id·s3_key·original_filename·file_size)")
    ap.add_argument("--workers", type=int, default=max(1, int(pc.cfg().extract.source.fetch_workers)))  # 11-04 원본 받기와 같은 칸
    a = ap.parse_args(argv)
    wd = _warm_dir()
    if not wd:
        print("[source] warm: SOURCE_WARM 미설정 — 받아 둘 곳이 없어 종료", flush=True)
        return 0
    cols = _rdb_cols()
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    targets = []
    for r in rows:
        bucket, key = _rdb_bucket_and_key(cols, r)
        targets.append(
            {
                "bucket": bucket,
                "key": key,
                "size": int(r[cols["size"]]) if r.get(cols["size"]) not in (None, "") else None,
                "filename": r.get(cols["filename"]) or None,
            }
        )
    with _warm_locked(wd):
        targets = [t for t in targets if not any(x["bucket"] == t["bucket"] and x["key"] == t["key"] for x in _warm_read(wd))]
    if not targets:
        print("[source] warm: 이미 전부 받아 둠 — 다운로드 0건", flush=True)
        return 0
    cli = _s3()
    t0 = time.time()

    def _one(t):
        """파일(=문서) 1건 = extract.download span 1행 — doc_id는 extract.parse와 같은 파일 이름."""
        name = t["filename"] or t["key"]
        with SP.span("extract.download", "extract", doc_id=name, ext=Path(name).suffix.lower(), file_bytes=t["size"]) as sp:
            return _fetch(t, sp)

    def _fetch(t, sp):
        p = _warm_key_path(wd, t["bucket"], t["key"])
        p.unlink(missing_ok=True)  # 인덱스엔 없는데 파일만 남은 잔여도 이번에 갈아치움
        tmp = wd / (p.name + ".part")
        on_wire = False  # head·전송 중의 실패는 원인이 외부(스토리지·네트워크)라 err_kind=external — botocore 예외는 이름으로 못 가림
        try:
            on_wire = True
            t_head = time.monotonic()
            actual = cli.head_object(Bucket=t["bucket"], Key=t["key"]).get("ContentLength")
            head_ms = (time.monotonic() - t_head) * 1000
            if t["size"] is not None and actual is not None and int(actual) != int(t["size"]):
                print(f"[source] warm: 크기 불일치(참고) — RDB({t['size']}) ≠ OS({actual}): {t['bucket']}/{t['key']}", flush=True)
            t_dl = time.monotonic()
            cli.download_file(t["bucket"], t["key"], str(tmp))
            download_ms = (time.monotonic() - t_dl) * 1000
            on_wire = False
            os.replace(tmp, p)  # 인덱스에 보이는 파일은 항상 완전한 내용
            size = int(actual) if actual is not None else t["size"]
            if size is not None:
                sp.set(file_bytes=size)
            # 순수 전송 속도(head·잠금 대기 제외) — 네트워크 문제인지 코드 문제인지 가르는 값
            sp.add(head_ms=round(head_ms), download_ms=round(download_ms))
            if size and download_ms > 0:
                sp.add(mbps=round(size * 8 / 1e6 / (download_ms / 1000), 2))
            t_lock = time.monotonic()
            with _warm_locked(wd):
                sp.add(lock_wait_ms=round((time.monotonic() - t_lock) * 1000))
                rs = _warm_read(wd)
                rs.append(
                    {
                        "bucket": t["bucket"],
                        "key": t["key"],
                        "size": t["size"],
                        "path": str(p),
                        "filename": t["filename"],
                        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                )
                _warm_write(wd, rs)
            print(f"[source] warm: {t['filename'] or t['key']} ({actual if actual is not None else '?'}B) 완료", flush=True)
            return True
        except Exception as e:
            p.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
            code, kind = SP.classify(e)
            sp.result(code, "external" if on_wire and code == "fail" else kind, e)
            print(f"[source] warm: 실패(무시·폴백) — {t['bucket']}/{t['key']}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False

    with SP.span("extract.warm", "extract", total=len(targets)) as sp:  # 프리페치 1회 = 1행(받은 수·실패 수)
        if a.workers > 1 and len(targets) > 1:
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
                done = sum(1 for r in ex.map(SP.carry(_one), targets) if r)  # 풀 스레드에 run_id·부모 span을 이어줌
        else:
            done = sum(1 for r in (_one(t) for t in targets) if r)
        sp.add(done=done, failed=len(targets) - done)
    print(f"[source] warm: {done}/{len(targets)}건 · {time.time() - t0:.1f}s → {wd}", flush=True)
    return 0


def _rdb_plan(table, state, limit=0, done=frozenset()):
    """문서 위치 표(csv:)의 대상 행 → (names, fetch_one(name,dest)→Path, state). resolve()가 부르고 모든 이름을 즉시 받는다.
    받기 전 대조는 크기(ContentLength — 불일치는 참고 기록만). 다른 원천의 같은 내용 파일도 따로 받는다(원천마다 독립)."""
    by_name, n_seen = CP.rdb_pick(table, state, limit, done)
    names = sorted(by_name)
    cli = _s3()
    book = threading.Lock()  # 병렬 fetch(SOURCE_FETCH_WORKERS)에서 기록(manifest 재작성·append)을 잠금

    def fetch_one(name, dest):
        o = by_name[name]
        if o["size"] is not None:
            actual = cli.head_object(Bucket=o["bucket"], Key=o["key"]).get("ContentLength")
            if actual != o["size"]:
                # RDB file_size가 Object Storage와 어긋나 있어 필수 비교에서 제외:
                # 문서 식별은 uuid(doc_id·key)·내용은 sha256(hash) 기준만 쓰고, 크기는 참고 로그로만 남긴다.
                with book:
                    with (state / "size_mismatch.log").open("a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(
                                {
                                    "table": table,
                                    "doc_id": o["doc_id"],
                                    "bucket": o["bucket"],
                                    "key": o["key"],
                                    "size_rdb": o["size"],
                                    "size_store": actual,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                print(
                    f"[source] 크기 불일치(참고만 — 다운로드 진행) — RDB({o['size']}) ≠ Object Storage({actual}): {o['bucket']}/{o['key']}",
                    flush=True,
                )
        # size가 없으면 받기 전 대조 생략(비교할 근거가 없음) — 그대로 받는다
        dest.mkdir(parents=True, exist_ok=True)
        f = _warm_take(o, dest, name)  # warm 프리페치 — 받아 둔 다음 배치 원본이면 즉시 이동
        if f is not None:
            print(f"[source] warm 적중 — 다운로드 생략: {o['bucket']}/{o['key']}", flush=True)
        else:
            f = _safe_join(dest, name)  # (기존 경로) 원격에서 내려받기
            cli.download_file(o["bucket"], o["key"], str(f))
        with book:  # manifest.jsonl 재작성(전체 읽기→쓰기) — 병렬 fetch에서 반드시 잠금
            man_f = state / "manifest.jsonl"
            man = {r["file_name"]: r for r in jl(man_f)} if man_f.exists() else {}
            man[name] = {
                "file_name": name,
                "uri": f"s3://{o['bucket']}/{o['key']}",
                "key": o["key"],
                "etag": o["etag"],
                "size": o["size"],
                "doc_id": o["doc_id"],
                "updated_at": o["updated_at"],
                "original_filename": o.get("filename"),
                "content_version_id": o.get("content_version"),  # FileStorageMap 고유 칸
                "created_at": o.get("created_at"),  # 원천 등록 시각 → gold_bundle → gold doc.created_at
                "source_system": _derive_source_from_key(o["key"]),
            }  # publish_parse_result가 문서별로 이 값 사용(없으면 --source-system 폴백)
            man_f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in man.values()), encoding="utf-8")
        return f

    man_f = state / "manifest.jsonl"
    if not man_f.exists():  # fetch_one이 한 번도 안 불려도(대상 0건) 파일이 있어야 — 없으면 ids.source_uri가 조용히 file://로 떨어짐
        man_f.touch()
    C.put(SOURCE_MANIFEST=str(man_f))  # S7e2 — 덮기 파일(이 프로세스·하위 프로세스) + 인계 키라 env에도(contract.py)
    label = table
    print(f"[source] rdb:{label} · 대상 {len(names)}개(이미 처리 {n_seen}개 제외)", flush=True)
    return names, fetch_one, state


def resolve(source, out, limit=0, done=frozenset()):
    """→ (로컬 원본 폴더, 대상 파일 이름 목록, 상태 폴더). 폴더면 그대로, rdb:csv면 표의 키를 Object Storage에서 받음.
    done = 끝난 원본 키(candidate_pick.done_keys) — 받기·복사 전에 뺀다(키: rdb는 s3_key, 하위 폴더는 상대 경로, 평평한 폴더는 이름)."""
    state = Path(out) / "parse" / "_source"
    state.mkdir(parents=True, exist_ok=True)
    if str(source).startswith("s3://"):
        raise ValueError(f"[source] {source} — s3:// 폴더 가져오기는 11-01에 지움(사용자) — 폴더 또는 rdb:csv:<경로>")
    if str(source).startswith("rdb:"):
        local = Path(out) / "_source_files"
        names, fetch_one, state = _rdb_plan(source[len("rdb:") :], state, limit, done)
        ok = []
        nw = max(1, int(pc.cfg().extract.source.fetch_workers))  # 기본 1) · 2026-10-22 — 문서별 병렬 다운로드(기본 1=기존 순차
        if nw > 1 and len(names) > 1:
            # 병렬 — 다운로드·head_object(네트워크)를 워커에, 기록(manifest 재작성 등)은 fetch_one 안 잠금으로 안전.
            # 결과는 제출 순서(names 순)대로 회수해 manifest 행 순서를 기존과 같게. 원천 여러 개(rdb:*)면 이름 겹침
            # rename이 잠금 밖(_rename_manifest_entry)이라 이 경로는 단일 원천(rdb:csv 등)에만 권장 — 여럿이면 1로.
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=min(nw, len(names))) as ex:
                futs = {n: ex.submit(fetch_one, n, local) for n in names}
                for n in names:
                    futs[n].result()
                    ok.append(n)
            print(f"[source] 다운로드 병렬 {min(nw, len(names))}워커 완료 · {len(ok)}/{len(names)}건", flush=True)
        else:
            for n in names:
                fetch_one(n, local)
                ok.append(n)
        if not Path(C.cfg().paths.source_manifest or "").exists():  # S7c — 설정 객체(위 put 뒤 다시 읽어 같은 값)
            raise RuntimeError("[source] rdb 모드인데 SOURCE_MANIFEST 파일이 없음 — 원본 위치가 조용히 file://로 떨어질 수 있어 멈춤")
        return local, ok, state
    src = Path(source)
    files = _tree_files(src)
    if files is None:  # 평평한 폴더 — 그대로(키 = 파일 이름)
        names = sorted(p.name for p in src.iterdir() if p.is_file() and p.name != ".gitkeep" and p.name not in done)[: limit or None]
        print(f"[source] 폴더 {src} · 대상 {len(names)}개", flush=True)
        return src, names, state
    files = [p for p in files if p.relative_to(src).as_posix() not in done]
    return _folder_tree(src, files[: limit or None], Path(out), state)


def _folder_tree(src, files, out, state):
    """PC 폴더 원천이 원천별 하위 폴더(`SFDC/<uuid>/<파일>` — Object Storage 키 모양)면: rdb 배치와 같게
    평평한 폴더(`<out>/_source_files`)에 복사하고 manifest.jsonl에 상대 키(`key`)·원본 주소(`uri`)·원천을 적는다 — 구조화가 키 첫 마디로
    원천을 고르고(gold_bundle), 원본 주소가 원래 파일을 가리키게. 같은 이름은 rdb와 같은 규칙(`<상위 폴더>__<이름>`)."""
    local = out / "_source_files"
    local.mkdir(parents=True, exist_ok=True)
    rows = [{"key": p.relative_to(src).as_posix(), "filename": p.name, "doc_id": p.parent.name, "path": p} for p in files]
    name_of = _rdb_names(rows)
    man = []
    for r in rows:
        name = name_of[r["key"]]
        shutil.copy2(r["path"], _safe_join(local, name))
        man.append(
            {
                "file_name": name,
                "uri": r["path"].resolve().as_uri(),
                "key": r["key"],
                "original_filename": r["filename"],
                "source_system": _derive_source_from_key(r["key"]) or _known_source(r["key"].split("/", 1)[0]),
            }
        )
    man_f = state / "manifest.jsonl"
    man_f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in man), encoding="utf-8")
    C.put(SOURCE_MANIFEST=str(man_f))  # rdb 배치와 같은 인계(원본 위치 주소 — contract.make_source_uri)
    names = [m["file_name"] for m in man]
    print(f"[source] 폴더 {src}(하위 폴더 {len(names)}개 파일 — 상대 키로 manifest) · 대상 {len(names)}개", flush=True)
    return local, names, state


def _record_sha_before_delete(state, local, done, field="sha256"):
    """지우기 전에 sha256을 manifest.jsonl에 남겨 둠(원본을 즉시 지워도 publish_parse_result가 로컬 없이도 EDW 행을 쓸 수 있게). 못 읽으면(파일이 이미 없는 등) 그 문서만 건너뜀."""
    man_f = state / "manifest.jsonl"
    man = {r["file_name"]: r for r in jl(man_f)}
    changed = False
    for r in done:
        name = r["file_name"]
        p = Path(local) / name
        if name in man and p.exists():
            from common.core.contract import file_hash

            man[name] = {**man[name], field: file_hash(p)}
            changed = True
    if changed:
        man_f.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in man.values()), encoding="utf-8")


def finish(state, local, rep_index):
    """Object Storage에서 받은 원본: 대표 결과가 나온 문서는 처리 완료로 기록하고 로컬 원본·사본을 **바로** 지움
    (publish_parse_result가 원본을 올리지 않으므로 기다릴 이유가 없다).
    지우기 전에 항상 sha256을 manifest에 남긴다(`_record_sha_before_delete`) — publish_parse_result `plan()`이 로컬 원본 없이도 이 값으로 EDW 행을 쓸 수 있게."""
    man_f = state / "manifest.jsonl"
    if not man_f.exists():
        return
    man = {r["file_name"]: r for r in jl(man_f)}
    ok = (
        {r["doc"] for r in json.loads(Path(rep_index).read_text(encoding="utf-8"))["docs"] if r.get("engine")}
        if Path(rep_index).exists()
        else set()
    )
    done = [man[n] for n in ok if n in man]
    with _processed_path(state).open("a", encoding="utf-8") as f:
        for r in done:
            f.write(json.dumps({"key": r["key"], "etag": r["etag"], "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")
    _record_sha_before_delete(state, local, done)
    gone = 0
    for r in done:
        for p in (Path(local) / r["file_name"], Path(local).parent / "prepared" / r["file_name"]):
            if p.exists() or p.is_symlink():
                p.unlink()
                gone += 1
    print(
        f"[source] 처리 완료 {len(done)}개 기록 · 내려받은 원본·사본 {gone}개 즉시 지움(SI39 요건⑧ — 업로드를 "
        "기다리지 않음, 실패 문서는 다시 시도하도록 남김)",
        flush=True,
    )


def prepare_batch(source, out, limit, run_step):
    """파싱 전 extract — 끝난 문서(ParsingMeta ok·partial) 빼고 고르기 → 원본 가져오기 → 중복 확인.
    → (원본 폴더, 파싱할 이름 목록(받은 순서), 상태 폴더). run_step(args) → 종료 코드: 여러 건 중복 확인을 자식 프로세스로."""
    out = Path(out)
    local, names, state = resolve(source, out, limit, CP.done_keys())
    if not CP.is_remote(source):
        C.put(DOC_DIR=str(Path(local).resolve()))  # 원본 위치 주소 = 이 폴더의 file:///
    (state / "selected.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    if sum(1 for f in Path(local).iterdir() if f.is_file() and f.name != ".gitkeep") <= 1:  # 1건은 자식 없이 같은 함수로
        from pipeline.extract import deduplication as dedup

        try:
            dedup.run_folder(local, out / "dedup")
            rc = 0
        except Exception as e:  # 자식 실패와 같게 종료 코드로
            print(f"[dedup] 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            rc = 1
    else:
        rc = run_step(["pipeline.extract.deduplication", "--src", local, "--out", out / "dedup"])
    if rc != 0:
        raise SystemExit(rc)
    keep = set((out / "dedup" / "keep.txt").read_text(encoding="utf-8").splitlines())
    return local, [n for n in names if n in keep], state


def _derive_source_from_key(key):
    """s3_key prefix로 출처 시스템 판별 — OS 경로의 폴더명(SFDC-test/CRMS-test/las_test)을 그대로 사용."""
    if not key:
        return None
    first = key.split("/")[0] if "/" in key else key
    if first.startswith(("SFDC-", "SFDC_")):
        return "SFDC-test"
    if first.startswith(("CRMS-", "CRMS_")):
        return "CRMS-test"
    if first.startswith(("las_", "LAS_")):
        return "las_test"
    return None


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(호스트 run_docs.py의 warm이 SOURCE_WARM을 넘김)
    utf8_stdout()
    if len(sys.argv) > 1 and sys.argv[1] == "warm":
        from pipeline.shared import runtrace

        with runtrace.run("source_warm", sys.argv[1:]):  # run_docs가 부르는 자기 실행 1건
            raise SystemExit(_warm_cmd(sys.argv[2:]))  # 프리페치 — 다음 배치 원본을 SOURCE_WARM에 미리 받아 둠
