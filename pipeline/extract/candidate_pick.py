#!/usr/bin/env python3
"""파싱 대상 고르기(받기 전) — 원천 목록(폴더 또는 rdb:csv 문서 위치 표)에서 이미 처리한 판·ParsingMeta에 끝난 문서·
지원 안 하는 형식을 뺀다. 받기·미리 받기·끝 정리는 candidate_ready.

열: 실 EDW `AI.FileStorageMap`의 다섯 열만 읽는다 — doc_id=id · key=s3_key · size=file_size ·
filename=original_filename · content_version=content_version_id(열 이름이 다른 csv는 extract.connections.rdb.columns로 — 식별자 화이트리스트만).
버킷 — key가 `s3://버킷/…` 꼴이면 그 안의 버킷, 아니면 RDB_BUCKET.
이미 처리됐는지는 (key, 증분값) 쌍으로(`_rdb_is_done` — 같은 s3_key의 새 판을 "이미 처리됨"으로 오판하지 않게). 증분값 = RDB_INCREMENT_COL 열(비우면 doc_id 열).
문서 이름 — original_filename을 그대로(없으면 doc_id), 같은 이름이 여럿이면 doc_id 접두(`<doc_id>__<이름>`)로 구분.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from common.config import settings as C
from common.core.contract import jl
from common.core.contract import safe_filename as _safe_name
from pipeline import config as pc

COL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # csv 열 이름(RDB_COL_*) 화이트리스트


def is_remote(source):
    """원본이 Object Storage에서 오는지 — rdb:csv(표가 키를 알려줌)면 True, 폴더면 False."""
    return str(source).startswith("rdb:")


def _rdb_cols():
    """RDB 표의 열 이름(실 EDW `AI.FileStorageMap` 기본값 — 설정 extract.connections.rdb.columns). 열 이름도 식별자이므로
    화이트리스트로 확인(독립 검토 BLOCK 3 — SQL 삽입)."""
    c = pc.cfg().connections.rdb.columns
    cols = {"doc_id": c.doc_id, "key": c.key, "size": c.size, "filename": c.filename, "content_version": c.content_version}
    bad = {k: v for k, v in cols.items() if v and not COL_ID_RE.match(v)}
    if bad:
        raise ValueError(f"[source] RDB_COL_* 값이 올바르지 않음(영문·숫자·_ 만) — {bad}")
    return cols


def _rdb_increment_col(cols):
    """증분(since) 기준 열 — RDB_INCREMENT_COL(비우면 doc_id 열) — AI.FileStorageMap은 updated_at이 없어 id(또는
    content_version_id)로 전진 판정한다(같은 파일의 새 판이 새 행/새 content_version_id로 들어온다는 가정). 열 이름이므로 같은 화이트리스트(COL_ID_RE)."""
    col = pc.cfg().connections.rdb.increment_col or cols["doc_id"]
    if not COL_ID_RE.match(col):
        raise ValueError(f"[source] RDB_INCREMENT_COL 값이 올바르지 않음(영문·숫자·_ 만) — {col!r}")
    return col


def _inc_value(row, col):
    """증분 비교값 — 숫자 문자열(csv 시험의 id 등)은 int로(문자열 비교면 '10' < '9'가 되는 함정 방지), 그 외(ISO8601
    날짜 등)는 그대로 — PG·mssql 네이티브 열은 이미 올바른 타입(int·timestamp)으로 오므로 그대로 통과."""
    v = row.get(col)
    return int(v) if isinstance(v, str) and v.lstrip("-").isdigit() else v


def _rdb_bucket_and_key(cols, r):
    """버킷·키 — key가 `s3://버킷/…` 꼴이면 그 안의 버킷, 아니면 RDB_BUCKET."""
    raw_key = r[cols["key"]]
    if isinstance(raw_key, str) and raw_key.startswith("s3://"):
        bucket, _, key = raw_key[5:].partition("/")
        return bucket, key
    bucket = pc.cfg().connections.rdb.bucket  # S7c — 설정 객체
    if not bucket:
        raise ValueError(f"[source] 버킷을 알 수 없음 — key가 s3://버킷/… 꼴 아님, RDB_BUCKET 필요(key={raw_key!r})")
    return bucket, raw_key


def _load_done(state):
    """`_processed_path()`의 처리 기록을 key → 그 key로 지금까지 처리된 **모든** 레코드 목록으로 모은다
    (key당 마지막 한 건만 남기면: `inc_col >= since` 경계 재조회에서 같은 s3_key에 새 판(새 id·content_version_id)이
    들어온 표는 이전 판 행이 다시 조회될 때 "최신 판 기록"과 달라 매번 '미완료'로 오판해 since가 전진하지
    못하고 그 자리를 영원히 다시 긁는다). 파일 하나를
    한 번 읽을 뿐이라 비용은 같음, 같은 key가 아주 자주(수천 번) 재사용되는 표만
    목록이 길어짐(지금 규모에선 문제 없음)."""
    done = defaultdict(list)
    p = _processed_path(state)
    if p.exists():
        for r in jl(p):
            done[r["key"]].append(r)
    return done


def _rdb_is_done(done, key, etag, ver):
    """이미 처리됐는지 — ETag가 있으면 그 key로 처리된 기록 중 하나라도 ETag가 일치하면(바뀌면 다시 받음). 없으면
    (FileStorageMap처럼 ETag 열이 없는 표) (key, 증분값) 쌍이 기록 중 하나와 같은지로 — 키만 보면 같은 s3_key에
    새 id/content_version_id가 들어온 새 판(같은 경로에 새 파일을 올리는 EDW 흐름)을 "이미 처리됨"으로 오판해
    watermark까지 전진시켜 영영 못 받는다. etag·증분값 둘 다 없으면 식별할 수가 없으므로 늘
    '미완료'로 봐서 다시 시도(조용한 영구 누락보다 안전 — None과 None을 '같다'고 오판하는 함정은 이 단계에서도
    막는다). done은 key → 레코드 목록(`_load_done()`)."""
    recs = done.get(key)
    if not recs:
        return False
    if etag is not None:
        return any(r.get("etag") == etag for r in recs)
    if ver is not None:
        return any(r.get("ver") == ver for r in recs)
    return False


def _rdb_names(rows):
    """문서 이름 — original_filename(또는 그 대응 열)이 있으면 그걸, 없으면 doc_id. 같은 이름이 여럿이면 doc_id
    접두(`<doc_id>__<이름>`)로 구분 — _safe_name 재사용(경로 탈출 방어는 _safe_join이 마지막 방어선)."""
    by_key = {r["key"]: r for r in rows}
    base = {k: _safe_name(r["filename"] or r["doc_id"], "") for k, r in by_key.items()}
    counts = defaultdict(int)
    for n in base.values():
        counts[n] += 1
    return {k: (_safe_name(f"{by_key[k]['doc_id']}__{n}", "") if counts[n] > 1 else n) for k, n in base.items()}


def _processed_path(state):
    """처리 기록 파일."""
    return state / "processed.jsonl"


def _rdb_rows(table):
    """문서 위치 표(csv:<경로>)의 행을 공통 꼴로: doc_id·bucket·key·etag(늘 None — 표에 ETag 열 없음)·size·filename·content_version·
    updated_at(증분값 — 처리 여부 판단)·created_at. csv만 받는다."""
    if not table.startswith("csv:"):
        raise ValueError(f"[source] rdb:{table} — 원천은 rdb:csv:<경로>만(11-01 사용자: rdb:*·rdb:<이름>·표 직접 질의 지움)")
    cols = _rdb_cols()
    inc_col = _rdb_increment_col(cols)
    with open(table[4:], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    mapped = []
    for r in rows:
        bucket, key = _rdb_bucket_and_key(cols, r)
        mapped.append(
            {
                "doc_id": str(r[cols["doc_id"]]),
                "bucket": bucket,
                "key": key,
                "etag": None,
                "size": int(r[cols["size"]]) if r.get(cols["size"]) not in (None, "") else None,
                "filename": r.get(cols["filename"]) or None,
                "content_version": r.get(cols["content_version"]) or None,
                "updated_at": _inc_value(r, inc_col),
                "created_at": r.get("created_at") or None,  # 원천 등록 시각 — 표에 칸이 있을 때만
            }
        )
    return mapped


def _filter_unsupported_rows(rows, name_of):
    """압축(ARCHIVE_EXT)·처리 엔진 없는 확장자(registry.engines_for)는 받기 전에 걸러낸다(name_of
    계산 뒤 sample() 호출 전 — 다운로드 자체를 안 함). 사유 말은 filter_and_rotate의 skipped.jsonl과 같다
    (pipeline.extract.filter_and_rotate._unsupported_reason 재사용 — 같은 규칙 한 곳). 반환: (남은 rows, 걸러진 rows 목록)."""
    from pipeline.extract.filter_and_rotate import _unsupported_reason

    kept, skipped = [], []
    for r in rows:
        name = name_of[r["key"]]
        reason = (
            _unsupported_reason(Path(name)) if Path(name).suffix else None
        )  # 확장자 없는 이름(filename 열이 없어 doc_id로 대체)은 판정 보류 — filter_and_rotate가 그대로 봄
        (skipped if reason else kept).append({"row": r, "file": name, "reason": reason} if reason else r)
    return kept, skipped


def _record_source_skipped(state, skipped):
    """건너뛴 행 기록(state/source_skipped.jsonl, {file,key,reason} — filter_and_rotate.py skipped.jsonl과 같은 사유 말) +
    다시 받을 길이 없으므로(지원 안 하는 형식) 바로 처리 완료로 표시(watermark가 이 파일 때문에 영영 안 전진하는
    것을 막음 — finish()가 파싱 성공분을 기록하는 것과 같은 자리 `_processed_path`)."""
    with (state / "source_skipped.jsonl").open("a", encoding="utf-8") as f:
        for s in skipped:
            f.write(json.dumps({"file": s["file"], "key": s["row"]["key"], "reason": s["reason"]}, ensure_ascii=False) + "\n")
    with _processed_path(state).open("a", encoding="utf-8") as f:
        for s in skipped:
            r = s["row"]
            f.write(json.dumps({"key": r["key"], "etag": r.get("etag"), "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")


def _hidden(p):
    return p.name.startswith(".") or p.name == "__MACOSX"


def _known_source(seg):
    """원본 키 첫 마디가 원천 이름(SFDC·CRMS·LAS·FAQ — 검색 스키마 원천 목록, other 빼고)이면 대문자 이름, 아니면 None."""
    from common.store.db.models.search_tables import SOURCES

    return seg.upper() if seg.lower() in set(SOURCES) - {"other"} else None


def _tree_files(src):
    """폴더가 원천별 하위 폴더 모양(`<원천>/<id>/<파일>`)이면 그 아래 파일 목록, 아니면 None(평평한 폴더로).
    모양 = 맨 위에 파일이 없고(숨김 파일 빼고), 맨 위 폴더가 모두 원천 이름(_known_source)이며 그 아래 파일이 있음.
    숨김(점으로 시작)·__MACOSX는 어디서나 뺀다 — 흘린 sub/.DS_Store 하나로 평평한 폴더가 바뀌지 않게."""
    top = [p for p in src.iterdir() if not _hidden(p) and p.name != ".gitkeep"]
    dirs = [p for p in top if p.is_dir()]
    if not dirs or len(dirs) != len(top) or not all(_known_source(d.name) for d in dirs):
        return None
    files = sorted(
        p
        for d in dirs
        for p in d.rglob("*")
        if p.is_file() and not any(_hidden(q) for q in p.relative_to(src).parents if q.name) and not _hidden(p)
    )
    return files or None


def pick_new(src, out, max_new, only=None):
    """이번 실행에서 처음 파싱할 문서(ParsingMeta에 성공 행이 없는 것)를 max_new개까지 → 목록 파일 경로. only(목록 파일 — stage_batch가
    이미 끝난 문서를 뺀 목록)가 있으면 그 안에서만(EDW를 다시 읽지 않음)."""
    names = sorted(p.name for p in Path(src).iterdir() if p.is_file())
    if only:
        sel = set(Path(only).read_text(encoding="utf-8").splitlines())
        new = [n for n in names if n in sel]
    else:
        new = unparsed(names, out)
    pick = new[:max_new]
    f = Path(out) / "parse" / "_batch_docs.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(pick) + "\n", encoding="utf-8")
    print(f"[parse] 새·실패 문서 {min(len(new), max_new)}/{len(new)}개(PARSE_MAX_NEW {max_new}) — 나머지는 다음 실행", flush=True)
    return f


def done_keys():
    """EDW ParsingMeta에 끝난 행(parsing_meta_db.done_source_keys — ok·partial 등)이 있는 원본 키 집합. EDW를 한 번 읽는다
    (읽기 계정, PC는 EDW 대역 sqlite `RDB_SQLITE`). 통째 실패는 ParsingMeta에 안 쓰므로 실패한 문서는 행이 없어 다음 실행이 다시 고른다.
    못 읽으면: 서버(RUN_ENV dev·prd·모르는 값)는 종료 4(전체 재파싱 안 함), PC는 빈 집합(받은 목록 그대로) + 로그 한 줄."""
    from common.store import parsing_meta_db as PMDB

    try:
        db = PMDB.make_db("read")
        try:
            return db.done_source_keys()
        finally:
            db.close()
    except (Exception, SystemExit) as ex:  # make_db는 접속 정보가 없으면 SystemExit
        if C.guard_run_env() not in (None, "local"):  # pl-12 — 서버(dev·prd·모르는 값)
            print(
                f"[parse] EDW ParsingMeta를 읽지 못함 — 멈춤(종료 4, 전체 재파싱 안 함): {type(ex).__name__}", file=sys.stderr, flush=True
            )
            raise SystemExit(4) from None
        print(f"[parse] EDW ParsingMeta 못 읽음({type(ex).__name__}) — 이력 없이 받은 목록 그대로 처리", flush=True)
        return set()


def unparsed(names, out):
    """이름 목록 중 새 문서 후보(FileStorageMap ∖ ParsingMeta). 키 = manifest의 "key"(없으면 이름 그대로 — publish의
    source_key와 같은 규칙, parsing_meta.plan). out = 결과 루트(파싱 입구 pipeline.cli의 OUT). 순서는 받은 이름 순서 그대로."""
    done = done_keys()
    man = Path(out) / "parse" / "_source" / "manifest.jsonl"
    key_of = {r["file_name"]: r.get("key") for r in jl(man)} if man.exists() else {}
    return [n for n in names if (key_of.get(n) or n) not in done]


def rdb_pick(table, state, limit=0, done=frozenset()):
    """문서 위치 표(csv:)에서 이번에 받을 행 → {문서 이름: 행}(받기 전 — 다운로드 없음). 처리 기록(processed.jsonl)에 있는 판·
    ParsingMeta에 끝난 원본 키(done — done_keys())·압축·엔진 없는 확장자를 뺀다. 반환: (by_name, 이번에 뺀 행 수)."""
    seen = _load_done(state)
    every = _rdb_rows(table)
    rows = [r for r in every if not _rdb_is_done(seen, r["key"], r["etag"], r["updated_at"]) and r["key"] not in done]
    name_of = _rdb_names(rows)  # original_filename(또는 doc_id) — 충돌하면 doc_id 접두로 구분
    rows, skipped = _filter_unsupported_rows(rows, name_of)  # 압축·엔진 없는 확장자는 받기 전에 걸러냄
    if skipped:
        _record_source_skipped(state, skipped)
    name_of = {r["key"]: name_of[r["key"]] for r in rows}
    rows = sorted(rows, key=lambda r: r["key"])[: limit or None]
    return {name_of[r["key"]]: r for r in rows}, len(every) - len(name_of)


# ── 원천 목록(run_pipeline이 컨테이너 안에서 한 번 부름) ──────────────────────────
# `python -m pipeline.extract.candidate_pick list --filter RFP,proposal --start-offset N [--limit N] [--seqs 3,7] [--skip-done]
#  [--max-docs N] [--faq-seen <파일>] --out <목록 파일>` — EDW FileStorageMap 목록(파일 크기 오름차순) → 끝난 문서 빼기(--skip-done) →
# FAQ 먼저(--faq-seen, --seqs·--limit 실행은 건너뜀) → 앞 --max-docs개. 목록 파일(JSON): {"total": 목록 행 수, "start": 시작 자리,
# "docs": [{"seq", "id", "s3_key", "original_filename", "file_size"}, …]} — 처리 순서대로, seq = 목록 안 자리(FAQ 덧붙임 포함).
FSM_SQL = (
    "SELECT id, s3_key, original_filename, file_size FROM AI.FileStorageMap WHERE ({cond}) AND file_size IS NOT NULL ORDER BY file_size ASC"
)
FAQ_PREFIX = "FAQ/"


def edw_rows(edw, keywords=(), faq=False):
    """FileStorageMap 행(파일 크기 오름차순) — 이름 키워드(대소문자 무시, 하나라도 들면) 또는 faq=True면 FAQ 전체."""
    if faq:
        return edw.q(FSM_SQL.format(cond="s3_key LIKE ?"), [FAQ_PREFIX + "%"])
    if not keywords:
        raise SystemExit("[list] --filter 키워드가 비어 있음")
    cond = " OR ".join(["LOWER(original_filename) LIKE ?"] * len(keywords))
    return edw.q(FSM_SQL.format(cond=cond), [f"%{k.lower()}%" for k in keywords])


def faq_status():
    """ParsingMeta의 FAQ 키 → parse_status(읽기 계정)."""
    from common.store import parsing_meta_db as PMDB

    db = PMDB.make_db("read")
    try:
        return db.status_like(FAQ_PREFIX)
    finally:
        db.close()


def faq_sync(reset, out):
    """gold faq 교체 확인 — 적재 명령(pgvector_load faq-sync)을 자식으로. 결과(지운 수·남은 gold faq)를 못 읽으면 None(지웠는지 모름)."""
    import subprocess

    from common.core.paths import child_env

    out = Path(out)
    out.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "pipeline.load.pgvector_load", "faq-sync", *(["--reset"] if reset else []), "--out", str(out)]
    try:
        rc = subprocess.run(cmd, env=child_env(), timeout=1800).returncode
    except subprocess.TimeoutExpired:  # ponytail: 자식이 끝까지 돌았는지 모름 — 다음 실행의 채움이 메움
        rc = -1
    try:
        return json.loads(out.read_text(encoding="utf-8")) if rc == 0 else None
    except (OSError, ValueError):
        return None


def faq_first(rows, order, faq_rows, status, seen_f, sync):
    """FAQ는 판을 잇지 않고 통째로 교체. 새 FAQ(교체를 마친 키 목록 seen_f에 없는 키)가 있으면 sync(reset=True)로 gold faq를 비우고
    FAQ 전체를 맨 앞에 넣는다(--filter·--skip-done과 상관없이 — 목록에 없는 FAQ 행은 rows 뒤에 덧붙임). 새 FAQ가 없으면 지우지 않고
    gold에 없는 FAQ만 넣는다(중간에 멈춘 교체·파싱 실패를 채움 — 완전 중복 skipped_dup은 gold에 안 올라가므로 뺌). sync 결과를 못 읽으면
    FAQ 전체를 넣고 seen_f는 그대로 둬 다음 실행이 교체를 다시 시도한다(적재는 이미 있는 문서를 건너뜀).
    ParsingMeta는 새 FAQ 판정에 쓰지 않는다(--seqs·--limit 실행이 교체 없이 기록할 수 있어서)."""
    seen = set(seen_f.read_text(encoding="utf-8").splitlines()) if seen_f.exists() else set()
    seq = {r["s3_key"]: i for i, r in enumerate(rows)}
    for r in faq_rows:
        if r["s3_key"] not in seq:
            seq[r["s3_key"]] = len(rows)
            rows.append(r)
    faq = [seq[r["s3_key"]] for r in faq_rows]
    new = [r["s3_key"] for r in faq_rows if r["s3_key"] not in seen]
    got = sync(bool(new))
    if got is not None and new:  # 교체가 끝난 뒤에만 적음 — 실패하면 다음 실행이 다시 교체
        seen_f.parent.mkdir(parents=True, exist_ok=True)
        seen_f.write_text("".join(f"{k}\n" for k in sorted(seen | set(new))), encoding="utf-8")
    if got is None or new:
        print(
            f"[경고] FAQ 교체 확인(faq-sync) 결과 없음 — FAQ {len(faq)}건 전체를 넣음(이미 있는 문서는 적재가 건너뜀)"
            if got is None
            else f"FAQ 교체: 새 FAQ {len(new)}건 — gold faq 문서 {got['faq_reset']}건을 지우고 지금 FAQ {len(faq)}건 전체를 맨 앞에서 다시 처리",
            flush=True,
        )
        want = faq
    else:
        gold = set(got["gold"])
        want = [seq[r["s3_key"]] for r in faq_rows if r["s3_key"] not in gold and status.get(r["s3_key"]) != "skipped_dup"]
        if want:
            print(f"FAQ 채움: gold에 없는 FAQ {len(want)}건을 다시 처리(지우지 않음)", flush=True)
    keep = set(want)
    return want + [s for s in order if s not in keep]


def list_targets(keywords, start, limit=0, seqs=(), skip_done=False, max_docs=0, faq_seen=None, sync=None):
    """이번 실행의 대상 → (rows, order, start, total). rows = 목록 행(FAQ 덧붙임 포함), order = 처리할 rows 자리 순서,
    total = 키워드 목록 행 수. faq_seen(교체를 마친 FAQ 키 파일)을 주면 FAQ 먼저 — sync(reset) = faq_sync 자리."""
    from common.store import mssql

    use_faq = faq_seen is not None and not (seqs or limit)
    edw = mssql.EdwReader()
    try:
        rows = edw_rows(edw, keywords)
        faq_rows = edw_rows(edw, faq=True) if use_faq else []
    finally:
        edw.close()
    total = len(rows)
    if start >= len(rows):  # 대상은 없어도 FAQ 교체는 확인 — 할 일이 없으면 빈 목록
        print(f"start-offset {start} ≥ 대상 {len(rows)}건", flush=True)
        start = len(rows)
    order = sorted(seqs) if seqs else list(range(start, len(rows) if not limit else min(len(rows), start + limit)))
    if skip_done:
        from common.store.parsing_meta_db import DONE_STATUSES

        done = done_keys()
        before = len(order)
        order = [s for s in order if rows[s]["s3_key"] not in done]
        print(f"skip-done: {before - len(order)}건 이미 완료({'·'.join(DONE_STATUSES)}) — 남은 {len(order)}건 처리", flush=True)
    if use_faq:
        order = faq_first(rows, order, faq_rows, faq_status(), Path(faq_seen), sync)
    elif faq_seen is not None:
        print("FAQ 교체 확인(pl-41) 건너뜀 — --seqs·--limit 실행", flush=True)
    if max_docs and len(order) > max_docs:
        print(f"max-docs: {len(order)}건 중 앞 {max_docs}건만(나머지는 다음 실행)", flush=True)
        order = order[:max_docs]
    return rows, order, start, total


def _list_cmd(argv):
    import argparse

    ap = argparse.ArgumentParser(prog="pipeline.extract.candidate_pick list")
    ap.add_argument("--filter", default="RFP,proposal", help="원본 파일 이름 키워드(쉼표 — 하나라도 들면)")
    ap.add_argument("--start-offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="시험 — 이 개수만")
    ap.add_argument("--seqs", default="", help="목록 자리(쉼표) — 주면 연속 범위 대신 이것만")
    ap.add_argument("--skip-done", action="store_true", help="ParsingMeta에 끝난(ok·partial — gold_version도, skipped_dup) 문서 뺌")
    ap.add_argument("--max-docs", type=int, default=0, help="앞에서 이 개수만(0 = 상한 없음)")
    ap.add_argument("--faq-seen", default=None, help="교체를 마친 FAQ 키 파일 — 주면 FAQ 먼저(--seqs·--limit 실행은 건너뜀)")
    ap.add_argument("--out", required=True, help="목록 파일(JSON)")
    a = ap.parse_args(argv)
    keywords = [k.strip() for k in a.filter.split(",") if k.strip()]
    seqs = [int(x) for x in a.seqs.split(",") if x.strip()]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sync = lambda reset: faq_sync(reset, out.with_name("faq_sync.json"))  # 결과는 목록 파일 옆
    rows, order, start, total = list_targets(keywords, a.start_offset, a.limit, seqs, a.skip_done, a.max_docs, a.faq_seen, sync)
    docs = [{"seq": s, **{k: rows[s][k] for k in ("id", "s3_key", "original_filename", "file_size")}} for s in order]
    out.write_text(json.dumps({"total": total, "start": start, "docs": docs}, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[list] 대상 {len(docs)}건 → {out}", flush=True)
    return 0


if __name__ == "__main__":
    from common.config import setarg
    from common.core.console import utf8_stdout

    setarg.apply()  # --set 이름=값(run_pipeline이 넘김)
    utf8_stdout()
    if sys.argv[1:2] != ["list"]:
        raise SystemExit("사용: python -m pipeline.extract.candidate_pick list --out <목록 파일> [...]")
    from pipeline.shared import runtrace

    with runtrace.run("candidate_list", sys.argv[1:]):
        raise SystemExit(_list_cmd(sys.argv[2:]))
