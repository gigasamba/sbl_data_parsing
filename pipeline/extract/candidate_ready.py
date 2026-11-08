#!/usr/bin/env python3
"""파싱 대상 받기 — 고른 문서(candidate_pick)를 폴더 또는 Object Storage(staging)에서 받아 → 같은 내용은 하나만 → 형식·DRM·암호 거르기 →
파싱 입력 폴더(prepared/) · 끝 정리. 원본을 받는 길은 staging 하나다(stage 명령과 pipeline.cli parse --source가 같은 stage_batch를 부름).

  --source <서버 폴더>               같은 서버 폴더(샘플 데이터) — 그대로 씀
  --source rdb:csv:<경로>            문서 위치 표(csv — run_pipeline이 목록 파일에서 만든 batch.csv)의 키만 Object Storage에서 staging으로 받음

Object Storage 원본 처리: 받은 파일의 sha256은 받기(resolve)가 한 번 구해 manifest에, 대표 결과가 나온 문서는 parse 뒤 처리 기록만 남김(finish). 원본 삭제는 게시가 끝난 뒤 run_pipeline drop_original 한 곳.
처리한 객체((key, 증분값))는 output/parse/_source/processed.jsonl에 기록 → 다음 실행에서 다시 받지 않음. 실패한 문서는 남겨 다음 실행이 다시 시도.
검색 결과의 원본 위치(source_uri) = s3://버킷/키(SOURCE_MANIFEST로 common.core.ids.source_uri가 읽음).
접속: OS_ENDPOINT · OS_ACCESS_KEY · OS_SECRET_KEY · OS_REGION(기본 us-east-1) · OS_VERIFY_TLS(기본 1, 사내 CA면 경로) — 비밀값은 settings.yaml에만.
받기 전 대조 — size가 있으면 ContentLength와 비교(크기 불일치는 참고 기록만).
"""

import hashlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from common.config import settings as C
from common.core import span as SP  # 성능 span
from common.core.console import utf8_stdout
from common.core.contract import file_hash
from common.core.contract import safe_path_join as _safe_join  # 경로 잇기(load 단계와 같은 함수)
from common.core.paths import atomic_write_text, tmp_path_for
from common.store import objectstore
from pipeline import config as pc
from pipeline.extract import candidate_pick as CP
from pipeline.shared.runtrace import skip_event
from pipeline.shared.srcsha import sha_of, stat_of


def _read_manifest(state):
    """state/manifest.jsonl → {file_name: 행}(없으면 빈 사전) — 고쳐 다시 쓰므로 공용 읽기(span.manifest_rows)의 사본."""
    return dict(SP.manifest_rows(state / "manifest.jsonl"))


def _write_manifest(state, rows):
    """state/manifest.jsonl을 rows로 통째로(원자적으로) 다시 씀 → 파일 경로."""
    return atomic_write_text(state / "manifest.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _hashed(f):
    """받은 파일의 sha256(문서마다 여기서 한 번) + 해시한 파일의 [크기, 고친 시각 ns] — manifest 칸. 뒤 단계·프로세스는
    srcsha.sha_of로 이 값을 다시 쓴다(같은 파일일 때만)."""
    return {"sha256": file_hash(f), "sha256_stat": stat_of(f)}


# ── staging(미리 받기) — 원본을 받는 유일한 자리 ─────────────────────────────
# Object Storage 원본은 SOURCE_STAGING/<sha1(버킷|키)>.bin으로 한 번만 받는다(ETag가 같은 판이 이미 있으면 다시 받지 않음 — 완성된 파일만 그 이름으로 보임).
# 파싱 입력 폴더(_source_files/<이름>)에는 하드 링크로 놓는다(같은 볼륨 — 사본·두 번째 다운로드 없음). staging 파일은 게시가 끝난 뒤
# run_pipeline이 지운다(파싱·게시 실패면 남아 다음 실행이 다시 받지 않음).


def _staging_dir():
    """SOURCE_STAGING — 미리 받기 폴더. 비었으면 rdb:csv 원본을 받을 수 없어 멈춤."""
    v = pc.cfg().extract.source.staging  # S7c — 설정 객체
    if not v:
        raise RuntimeError("[source] extract.source.source_staging_dir(SOURCE_STAGING) 미설정 — rdb:csv 원본을 받을 자리가 없음")
    return Path(v)


def _staging_path(wd, bucket, key):
    return wd / (hashlib.sha1(f"{bucket}|{key}".encode()).hexdigest() + ".bin")


def download(rows, state, workers=1):
    """고른 행(candidate_pick.rdb_pick 값)의 원본을 staging에 받는다 — 받아 둔 파일의 ETag(옆 `<이름>.etag`)가 지금
    ETag와 같을 때만 다시 쓰고, 다르거나 ETag가 없으면 다시 받음(크기만 같은 새 판을 옛 파일로 파싱하지 않게). RDB 크기와의 불일치는 state/size_mismatch.log에 참고 기록만. 파일(=문서) 1건 = extract.download span 1행.
    반환: 받지 못한 행 수."""
    wd = _staging_dir()
    wd.mkdir(parents=True, exist_ok=True)
    todo = list(rows)
    if not todo:
        return 0
    cli = objectstore.client()
    book = threading.Lock()  # 병렬 받기에서 size_mismatch.log 쓰기를 잠금

    def _one(o):
        name = o["filename"] or o["key"]
        with SP.span(
            "extract.download",
            "extract",
            doc_id=name,
            ext=Path(name).suffix.lower(),
            file_bytes=o["size"],
            source_system=o.get("source_system"),
        ) as sp:
            p = _staging_path(wd, o["bucket"], o["key"])
            tmp = wd / (p.name + ".part")
            on_wire = True  # head·전송 중의 실패는 원인이 외부(스토리지·네트워크)라 err_kind=external — botocore 예외는 이름으로 못 가림
            try:
                t_head = time.monotonic()
                head = cli.head_object(Bucket=o["bucket"], Key=o["key"])
                actual, etag = head.get("ContentLength"), head.get("ETag")
                head_ms = (time.monotonic() - t_head) * 1000
                tag = p.with_suffix(".etag")  # 받은 판의 ETag — 다시 쓸지는 이 값으로만(크기만 같은 새 판을 옛 파일로 파싱하지 않게)
                if o["size"] is not None and actual is not None and int(actual) != int(o["size"]):
                    # RDB file_size가 Object Storage와 어긋날 수 있어 필수 비교에서 뺀다 — 문서 식별은 키, 내용은 sha256. 크기는 참고 기록만.
                    rec = {"doc_id": o["doc_id"], "bucket": o["bucket"], "key": o["key"], "size_rdb": o["size"], "size_store": actual}
                    with book, (state / "size_mismatch.log").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({**rec, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
                    print(
                        f"[source] 크기 불일치(참고만 — 받기 진행) — RDB({o['size']}) ≠ Object Storage({actual}): {o['bucket']}/{o['key']}",
                        flush=True,
                    )
                # 같은 판을 받아 둠(앞선 실행이 게시 전에 멈춤)
                if etag and p.exists() and tag.is_file() and tag.read_text(encoding="utf-8") == etag:
                    sp.add(head_ms=round(head_ms), reused=1)
                    return True
                t_dl = time.monotonic()
                cli.download_file(o["bucket"], o["key"], str(tmp))
                download_ms = (time.monotonic() - t_dl) * 1000
                on_wire = False
                os.replace(tmp, p)  # 그 이름으로 보이는 파일은 항상 완전한 내용
                if etag:
                    atomic_write_text(tag, etag)
                else:
                    tag.unlink(missing_ok=True)
                size = int(actual) if actual is not None else o["size"]
                if size is not None:
                    sp.set(file_bytes=size)
                # 순수 전송 속도(head 제외) — 네트워크 문제인지 코드 문제인지 가르는 값
                sp.add(head_ms=round(head_ms), download_ms=round(download_ms))
                if size and download_ms > 0:
                    sp.add(mbps=round(size * 8 / 1e6 / (download_ms / 1000), 2))
                print(f"[source] staging: {o['filename'] or o['key']} ({actual if actual is not None else '?'}B) 받음", flush=True)
                return True
            except Exception as e:
                tmp.unlink(missing_ok=True)
                code, kind = SP.classify(e)
                sp.result(code, "external" if on_wire and code == "fail" else kind, e)
                print(f"[source] staging: 받기 실패 — {o['bucket']}/{o['key']}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                return False

    t0 = time.time()
    with SP.span("extract.staging", "extract", total=len(todo)) as sp:  # 받기 1회 = 1행(받은 수·실패 수)
        if workers > 1 and len(todo) > 1:
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=min(workers, len(todo))) as ex:
                got = sum(1 for r in ex.map(SP.carry(_one), todo) if r)  # 풀 스레드에 run_id·부모 span을 이어줌
        else:
            got = sum(1 for r in (_one(o) for o in todo) if r)
        sp.add(done=got, failed=len(todo) - got)
    print(f"[source] staging: {got}/{len(todo)}건 · {time.time() - t0:.1f}s → {wd}", flush=True)
    return len(todo) - got


def _rdb_plan(table, state, limit=0, done=frozenset()):
    """문서 위치 표(csv:)의 대상 행 → (names, fetch_one(name, dest) → manifest 행). 고르고(rdb_pick) staging에 받은 뒤(download)
    fetch_one이 staging 파일을 dest/name으로 하드 링크한다(받지 못한 문서가 있으면 멈춤). 다른 원천의 같은 내용 파일도 따로 받는다."""
    by_name, n_seen = CP.rdb_pick(table, state, limit, done)
    rows = list(by_name.values())
    name_of = _rerun_names({r["key"]: n for n, r in by_name.items()}, rows, _read_manifest(state))  # 앞 실행 이름과 겹치지 않게
    by_name = {name_of[r["key"]]: r for r in rows}
    names = sorted(by_name)
    failed = download(list(by_name.values()), state, max(1, int(pc.cfg().extract.source.fetch_workers)))
    if failed:
        raise RuntimeError(f"[source] staging에 받지 못한 문서 {failed}건 — 멈춤(다음 실행이 다시 받음)")
    wd = _staging_dir()

    def fetch_one(name, dest):
        o = by_name[name]
        f = _safe_join(dest, name)
        if f.exists() or f.is_symlink():
            f.unlink()
        os.link(_staging_path(wd, o["bucket"], o["key"]), f)  # staging과 같은 볼륨 — 사본 없음
        return {
            "file_name": name,
            "uri": f"s3://{o['bucket']}/{o['key']}",
            "key": o["key"],
            "size": o["size"],
            "doc_id": o["doc_id"],
            "updated_at": o["updated_at"],
            "original_filename": o.get("filename"),
            "source_system": o["source_system"],  # FileStorageMap.source_system(op-17 — 키에서 다시 구하지 않음)
            **_hashed(f),
        }  # publish_parse_result가 문서별로 이 값 사용(없으면 --source-system 폴백)

    print(f"[source] rdb:{table} · 대상 {len(names)}개(끝난 문서·처리 기록·지원 안 함 {n_seen}개 제외)", flush=True)
    return names, fetch_one


def resolve(source, out, limit=0, done=frozenset()):
    """→ (로컬 원본 폴더, 대상 파일 이름 목록, 상태 폴더). 폴더면 그대로, rdb:csv면 표의 키를 Object Storage에서 받음.
    done = 끝난 원본 키(candidate_pick.done_keys) — 받기·복사 전에 뺀다(키: rdb는 s3_key, 하위 폴더는 상대 경로, 평평한 폴더는 이름)."""
    state = Path(out) / "parse" / "_source"
    state.mkdir(parents=True, exist_ok=True)
    if str(source).startswith("s3://"):
        raise ValueError(f"[source] {source} — s3:// 폴더 가져오기는 11-01에 지움(사용자) — 폴더 또는 rdb:csv:<경로>")
    if str(source).startswith("rdb:"):
        local = Path(out) / "_source_files"
        local.mkdir(parents=True, exist_ok=True)  # 대상 0건(모두 지원 안 함 등)이어도 중복 제외가 훑을 폴더
        names, fetch_one = _rdb_plan(source[len("rdb:") :], state, limit, done)
        man = _read_manifest(state)
        for n in names:  # 받기는 download가 끝냄 — 여기는 하드 링크만(차례로)
            man[n] = fetch_one(n, local)
        # 대상 0건이어도 파일을 씀 — 없으면 ids.source_uri가 조용히 file://로 떨어짐
        C.put(SOURCE_MANIFEST=str(_write_manifest(state, man.values())))  # 덮기 파일(이 프로세스·하위 프로세스) + 인계 키(contract.py)
        return local, names, state
    src = Path(source)
    files = CP._tree_files(src)
    if files is None:  # 평평한 폴더 — 그대로(키 = 파일 이름)
        names = sorted(p.name for p in src.iterdir() if p.is_file() and not CP._hidden(p) and p.name not in done)[: limit or None]
        print(f"[source] 폴더 {src} · 대상 {len(names)}개", flush=True)
        return src, names, state
    files = [p for p in files if p.relative_to(src).as_posix() not in done]
    return _folder_tree(src, files[: limit or None], Path(out), state)


def _rerun_names(name_of, rows, man):
    """이번 행의 문서 이름(name_of = 이번 실행 안에서 고른 원본 키 → 이름) → 앞 실행 manifest 행과도 겹치지 않는 이름(rdb·PC 폴더 같음).
    같은 키면 그 문서라 앞 이름 그대로, 다른 키가 쓴 이름이면 `_rdb_names`와 같은 꼴(`<상위 폴더>__<이름>`, 그래도 겹치면 키 전체를 `__`로 이음)."""
    by_key = {r["key"]: r for r in rows}
    out = {r.get("key"): n for n, r in man.items() if r.get("key") in by_key}  # 같은 문서 다시 — 앞 이름 그대로
    taken = set(man)
    for k, n in name_of.items():
        if k not in out:
            r = by_key[k]
            out[k] = next(
                c
                for c in (
                    n,
                    CP._safe_name(f"{r['doc_id']}__{r.get('filename') or r['doc_id']}", ""),
                    CP._safe_name(k.replace("/", "__"), ""),
                )
                if c not in taken
            )
            taken.add(out[k])
    return out


def _folder_tree(src, files, out, state):
    """PC 폴더 원천이 원천별 하위 폴더(`SFDC/<uuid>/<파일>` — Object Storage 키 모양)면: rdb 배치와 같게
    평평한 폴더(`<out>/_source_files`)에 복사하고 manifest.jsonl에 상대 키(`key`)·원본 주소(`uri`)·원천(맨 위 폴더 이름)을 적는다 —
    구조화·적재·게시가 그 원천을 쓰고(gold_bundle), 원본 주소가 원래 파일을 가리키게. 같은 이름은 rdb와 같은 규칙(`<상위 폴더>__<이름>`)."""
    local = out / "_source_files"
    local.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "key": p.relative_to(src).as_posix(),
            "filename": p.name,
            "doc_id": p.parent.name,
            "path": p,
            "source": p.relative_to(src).parts[0],
        }
        for p in files
    ]
    man, names = _read_manifest(state), []  # 앞 실행 행은 남김(rdb와 같음) — 같은 결과 폴더의 앞 문서도 구조화·적재가 원천·키를 찾음
    name_of = _rerun_names(CP._rdb_names(rows), rows, man)
    for r in rows:
        name = name_of[r["key"]]
        f = _safe_join(local, name)
        shutil.copy2(r["path"], f)
        names.append(name)
        man[name] = {
            "file_name": name,
            "uri": r["path"].resolve().as_uri(),
            "key": r["key"],
            "original_filename": r["filename"],
            "source_system": CP._known_source(r["source"]),  # 맨 위 폴더 = 원천(_tree_files가 확인함)
            **_hashed(f),
        }
    C.put(SOURCE_MANIFEST=str(_write_manifest(state, man.values())))  # rdb 배치와 같은 인계(원본 위치 주소 — contract.make_source_uri)
    print(f"[source] 폴더 {src}(하위 폴더 {len(names)}개 파일 — 상대 키로 manifest) · 대상 {len(names)}개", flush=True)
    return local, names, state


def finish(state, rep_index):
    """Object Storage에서 받은 원본: 대표 결과가 나온 문서를 처리 완료로 기록한다(processed.jsonl). sha256은 받기(`_hashed`)가
    manifest에 이미 남겼다(publish_parse_result `plan()`이 로컬 원본 없이도 그 값을 gold 처리 기록으로 넘김).
    파일은 지우지 않는다 — 원본 삭제는 게시가 끝난 뒤 run_pipeline `drop_original()` 한 곳."""
    man = _read_manifest(state)
    if not man:
        return
    ok = (
        {r["doc"] for r in json.loads(Path(rep_index).read_text(encoding="utf-8"))["docs"] if r.get("engine")}
        if Path(rep_index).exists()
        else set()
    )
    done = [man[n] for n in ok if n in man]
    with CP._processed_path(state).open("a", encoding="utf-8") as f:
        for r in done:
            f.write(json.dumps({"key": r["key"], "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")
    print(f"[source] 처리 완료 {len(done)}개 기록(원본은 게시 뒤 drop_original이 지움)", flush=True)


def stage_batch(source, out, prepared, limit, run_step, done=frozenset(), scan_rotate=True, seen=None):
    """파싱 전 extract 한 번 — 세 단계를 이 순서로 한 번씩:
    1. 받기 — `resolve`: 고르기(처리 기록·지원 안 함·done) → rdb:csv는 staging에 받아(`download`) 파싱 원본 폴더에 놓음.
       받은 파일의 sha256은 여기서 한 번 구해 manifest에 둔다(뒤 단계는 그 값을 씀).
    2. 중복 제외 — `_dedup`: 받은 파일의 sha256으로 같은 묶음 안 같은 내용은 대표 하나만, 남은 것 중 gold에 끝난 다른 원본과
       sha256이 같으면 뺀다. seen(이번 실행의 받은 sha256 표지 폴더 — 문서마다 stage를 부르는 서버 흐름)을 주면 이번 실행에서 다른 원본이
       먼저 받은 sha256도 뺀다. 뺀 중복은 모두 except_doc_info skip(`duplicate_sha256`). <out>/dedup/keep.txt = 남은 이름.
    3. 거르기 — filter_and_rotate(only.txt의 이름만 → prepared/): DRM·암호·지원 안 함은 건너뜀 기록만(처리하지 않음), 방향 보정.
    건너뛴 문서는 문서마다 `skip_event` 1행(applog.pipe_event — status=skip, err_kind=doc). 거르기가 뺀 영구 이유(지원 안 함·DRM·암호)는
    applog.except_doc_info skip에도(`_record_filtered` — 다음 대상 목록이 뺌, op-17).
    → (원본 폴더, 남은 이름 목록(받은 순서), 상태 폴더, 남은 이름 목록 파일 only.txt). run_step(args) → 종료 코드(자식 프로세스).
    scan_rotate=False면 이미지 PDF는 돌리지 않는다(run_pipeline의 스캔 문서 정책)."""
    out = Path(out)
    local, names, state = resolve(source, out, limit, done)  # 1. 받기
    if not CP.is_remote(source):
        C.put(DOC_DIR=str(Path(local).resolve()))  # 원본 위치 주소 = 이 폴더의 file:///
    keep_names = _dedup(local, names, out / "dedup", state, seen)  # 2. 중복 제외
    only = state / "only.txt"
    only.write_text("\n".join(keep_names) + "\n", encoding="utf-8")
    extra = [] if scan_rotate else ["--no-scan-rotate"]
    rc = run_step(["pipeline.extract.filter_and_rotate", "--src", local, "--out", prepared, "--only", only, *extra])  # 3. 거르기
    if rc != 0:
        raise SystemExit(rc)
    _record_filtered(prepared, state)
    left = [n for n in keep_names if (Path(prepared) / n).exists()]  # 거르기를 지난 것만 파싱
    if left != keep_names:  # 거르기가 뺀 것이 있을 때만 다시 씀
        only.write_text("\n".join(left) + "\n", encoding="utf-8")
    return local, left, state, only


def _dedup(local, names, dedup_dir, state, seen=None):
    """받은 파일의 sha256으로 중복 제외 → 남은 이름(names 순서). 같은 묶음 안(이번 names만 — 폴더에 남은 앞 실행 파일은 안 봄)은
    deduplication.run_folder(대표 하나 — 1건 이하면 해시만), 그다음 gold 문서(candidate_pick.done_by_sha — doc.sha256)가 같은 sha256을
    다른 원본 키로 가지면 뺀다(같은 키면 그 문서의 재처리라 남김), seen이 있으면 이번 실행에서 다른 원본이 먼저 받은 sha256이면 뺀다(`_claim`).
    뺀 중복(dup_batch·dup_done·dup_run)은 모두 except_doc_info skip(`duplicate_sha256` — op-17). 원본 키 = manifest의 "key"(없으면 이름 — 게시와 같은 규칙).
    sha256은 받기가 manifest에 남긴 값(srcsha.sha_of — 없으면 한 번 구함).
    keep.txt = 폴더 파일 중 이번에 중복으로 뺀 것만 없는 목록(게시는 빠진 것을 올리지 않고, 앞 실행의 남은 문서는 그대로 둠)."""
    from pipeline.extract import deduplication as dedup

    if len(names) <= 1:  # 묶을 것이 없음(서버 stage는 문서 하나씩) — 해시만
        keep, rows = {n: sha_of(Path(local) / n) for n in names}, []
    else:
        keep, rows = dedup.run_folder(local, set(names))
    rep = {r["group"]: r["file"] for r in rows if r["representative"]}
    man = _read_manifest(state)
    key_of = {n: r.get("key") or n for n, r in man.items()}
    src_of = {n: r.get("source_system") for n, r in man.items()}
    dups: list[str] = []
    for r in rows:
        if not r["representative"]:
            skip_event(r["file"], "dup_batch", src_of.get(r["file"]), dup_of=rep[r["group"]])
            dups.append(r["file"])
    picked = [n for n in names if n in keep]
    done = CP.done_by_sha({keep[n] for n in picked})
    left = []
    for n in picked:
        key, hit = key_of.get(n, n), done.get(keep[n])
        if hit and hit[0] != key:
            skip_event(n, "dup_done", src_of.get(n), dup_of=hit[0])
            dups.append(n)
            continue
        first = _claim(seen, keep[n], key) if seen is not None else None
        if first:
            skip_event(n, "dup_run", src_of.get(n), dup_of=first)
            dups.append(n)
        else:
            left.append(n)
    if dups:  # 같은 내용의 원본이 이미 있음(같은 묶음·gold·이번 실행) — 다음 대상 목록에서도 뺌
        from pipeline.shared import except_docs

        except_docs.record([_skip_row(key_of.get(n, n), n, "duplicate_sha256", man.get(n)) for n in dups])
    Path(dedup_dir).mkdir(parents=True, exist_ok=True)
    dropped = set(dups)
    rest = sorted(f.name for f in Path(local).iterdir() if f.is_file() and not CP._hidden(f) and f.name not in dropped)
    (Path(dedup_dir) / "keep.txt").write_text("\n".join(rest) + "\n", encoding="utf-8")
    return left


def _claim(seen, sha, key):
    """이번 실행에서 이 sha256을 처음 받은 원본이면 표지 `<seen>/<sha256>`(내용 = 원본 키)를 만들고 None, 다른 원본이 먼저 받았으면 그 원본 키.
    표지는 다 쓴 임시 파일을 os.link로 붙여 만든다 — 동시에 받는 stage 둘 중 하나만 이기고, 읽는 쪽은 늘 다 쓴 내용을 본다.
    같은 원본(받기 다시 시도)이면 None."""
    seen = Path(seen)
    seen.mkdir(parents=True, exist_ok=True)
    f = seen / sha
    tmp = tmp_path_for(f)
    tmp.write_text(key, encoding="utf-8")
    try:
        os.link(tmp, f)
        return None
    except FileExistsError:
        first = f.read_text(encoding="utf-8")
        return None if first == key else first
    finally:
        tmp.unlink(missing_ok=True)


def _skip_row(key, name, reason, man_row):
    """except_docs.record 행 하나 — 원천·크기는 manifest 행의 source_system·크기(span.manifest_size — 없으면 None)."""
    man_row = man_row or {}
    return {
        "source_key": key,
        "source_system": man_row.get("source_system"),
        "file_name": name,
        "file_size": SP.manifest_size(man_row),
        "reason": reason,
    }


def _record_filtered(prepared, state):
    """거르기(filter_and_rotate)가 이번에 뺀 문서(`prepared/_records/skipped.csv`)를 except_doc_info skip에(영구 이유만 — except_docs.record),
    안 문서를 못 꺼낸 문서(`parts_failed.csv` — pl-65)를 part 행에(except_docs.record_part). 원본 키 = manifest의 "key"(없으면 이름 — 게시와 같은 규칙)."""
    import csv

    from pipeline.shared import except_docs

    man = None
    for name, write in (("skipped.csv", except_docs.record), ("parts_failed.csv", except_docs.record_part)):
        f = Path(prepared) / "_records" / name
        if not f.exists():
            continue
        with f.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        man = _read_manifest(state) if man is None else man
        write([_skip_row((man.get(r["file"]) or {}).get("key") or r["file"], r["file"], r["reason"], man.get(r["file"])) for r in rows])


def _stage_cmd(argv):
    """`python -m pipeline.extract.candidate_ready stage --csv <문서 위치 표> --out <결과 폴더> --prepared <준비 폴더>` — run_pipeline이
    문서마다 부른다: 받기(staging) → 중복(이번 실행의 다른 문서와 같은 내용도 — `<out>/../_seen_sha`) → 거르기 →
    <out>/parse/_source/only.txt(파싱할 이름). 파싱은 `pipeline.cli parse --staged`."""
    import argparse

    from common.core.paths import child_env
    from pipeline.parse_steps import run_step

    ap = argparse.ArgumentParser(prog="pipeline.extract.candidate_ready stage")
    ap.add_argument("--csv", required=True, help="문서 위치 표(id·s3_key·original_filename·file_size·source_system)")
    ap.add_argument("--out", required=True, help="문서 결과 폴더(_source_files·parse/_source·dedup이 여기에)")
    ap.add_argument("--prepared", required=True, help="파싱 입력 폴더(거르기를 지난 파일)")
    ap.add_argument("--no-scan-rotate", action="store_true", help="이미지 PDF는 방향 보정 안 함(스캔 문서 정책)")
    a = ap.parse_args(argv)
    _, left, _, only = stage_batch(
        f"rdb:csv:{a.csv}",
        a.out,
        a.prepared,
        0,
        lambda args: run_step(args, child_env()).returncode,
        scan_rotate=not a.no_scan_rotate,
        seen=Path(a.out).parent / CP.RUN_SEEN,  # 문서 폴더 _docflow/<순번>의 위 = 이번 실행 목록 파일 자리(list가 비움)
    )
    print(f"[source] stage: 파싱할 문서 {len(left)}건 → {only}", flush=True)
    return 0


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(run_pipeline의 stage가 SOURCE_STAGING 등을 넘김)
    utf8_stdout()
    if sys.argv[1:2] != ["stage"]:
        raise SystemExit("사용: python -m pipeline.extract.candidate_ready stage --csv <표> --out <폴더> --prepared <폴더>")
    from pipeline.shared import runtrace

    with runtrace.run("source_stage", sys.argv[1:]):  # run_pipeline이 부르는 자기 실행 1건
        raise SystemExit(_stage_cmd(sys.argv[2:]))
