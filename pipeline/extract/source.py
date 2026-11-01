#!/usr/bin/env python3
"""파싱 대상 문서 가져오기(파싱 모듈) — 폴더 또는 rdb:csv(문서 위치 표 csv → Object Storage에서 받음).

  --source /srv/rag/docs            같은 서버 폴더(샘플 데이터) — 그대로 씀
  --source rdb:csv:<경로>            문서 위치 표(csv — run_docs가 EDW FileStorageMap에서 만든 batch.csv)의 키만 Object Storage에서 받음(AD44)
  (11-01 사용자 지움: s3://버킷/접두 폴더 가져오기 · rdb:*·rdb:<이름>(원천 목록 sources.json) · rdb:<표> 직접 질의(watermark 포함) ·
   --mode test 표본 · 스트리밍용 plan())

Object Storage 원본 처리(백로그 O2 일부): 대표 결과가 나온 문서의 내려받은 원본은 parse 뒤 바로 지움.
처리한 객체(ETag 또는 (key, 증분값))는 output/parse/_source/processed.jsonl에 기록 → 다음 실행에서 다시 받지 않음. 실패한 문서는 남겨 다음 실행이 다시 시도.
검색 결과의 원본 위치(source_uri) = s3://버킷/키(SOURCE_MANIFEST로 common/ids.source_uri가 읽음).
접속: OS_ENDPOINT · OS_ACCESS_KEY · OS_SECRET_KEY · OS_REGION(기본 us-east-1) · OS_VERIFY_TLS(기본 1, 사내 CA면 경로) — 비밀값은 settings.yaml에만.

열 매핑(AD44): 기본은 실 EDW `AI.FileStorageMap`과 같음 — doc_id=id · key=s3_key · size=file_size ·
filename=original_filename · content_version=content_version_id. 이 표에 없는 열(bucket·etag·content_type·company_id·doc_type·
contract_id·updated_at·version·supersedes·is_deleted)은 선택(기본값 ""=미설정) — 열 이름이 다른 csv는 RDB_COL_<필드>로 맞춘다
(열 이름은 식별자 화이트리스트만). 고객·문서 종류 필터(RDB_COMPANY·RDB_DOC_TYPE)는 그 열이 없으면 경고 뒤 필터 없이 진행.
버킷 — bucket 열이 있으면 그 값, 없으면 key가 `s3://버킷/…` 꼴이면 그 안의 버킷, 둘 다 아니면 RDB_BUCKET.
받기 전 대조 — etag 열이 있으면 ETag 대조(head_object), 없고 size가 있으면 ContentLength와 비교(크기 불일치는 참고 기록만),
둘 다 없으면 대조 생략. 이미 처리됐는지는 ETag가 있으면 ETag로, 없으면 (key, 증분값) 쌍으로(`_rdb_is_done` — 같은 s3_key의
새 판을 "이미 처리됨"으로 오판하지 않게). 증분값 = updated_at 열, 없으면 RDB_INCREMENT_COL(기본 id).
문서 이름 — original_filename을 그대로(없으면 doc_id), 같은 이름이 여럿이면 doc_id 접두(`<doc_id>__<이름>`)로 구분.
Object Storage의 실제 값이 표가 적은 값과 다르면 받지 않고 거부·기록(output/parse/_source/rejected.jsonl) — 그 문서만 건너뜀.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from common.config import settings as C  # S7c: 설정 객체(common 칸 SOURCE_MANIFEST·비밀 꺼내기)
from common.core import span as SP  # op-01 성능 span
from common.core.console import utf8_stdout
from common.core.contract import jl
from pipeline import config as pc  # S7c: 설정 객체(pipeline 칸)

COL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # csv 열 이름(RDB_COL_*) 화이트리스트(옛 common.core.sources와 같은 규칙)


class EtagMismatch(ValueError):
    """RDB가 적은 값(ETag 또는 크기) ≠ Object Storage — 그 문서만 건너뜀. 경로 탈출(_safe_join ValueError)은 이걸로
    잡지 않고 그대로 크래시(독립 검토 AD44 재검)."""


class DuplicateContent(ValueError):
    """다른 원천(source_id)의 기존 지문(output/dedup/manifest.jsonl)과 완전히 같은 내용 — 받기 전(비멀티파트
    ETag+크기) 또는 받은 뒤(sha256)에 판단해 그 문서만 건너뜀(O3 재설계, 2026-10-14 — 근사 중복은 더 안
    보고 완전 중복만, `pipeline.extract.dedup.find_duplicate` 사용). EtagMismatch와 똑같이 그 문서
    하나만 영향(호출부가 같이 묶어 처리) — 경로 탈출(ValueError, _safe_join)과는 안 섞임(fail-loud 유지)."""


def _dedup_manifest_path(state):
    """state(관례상 `output/parse/_source`) → 중복 지문 매니페스트 `output/dedup/manifest.jsonl` 경로. state는
    plan()·resolve() 둘 다 항상 `Path(out) / "parse" / "_source"`로 만들므로 이 상대 위치로 되짚는다
    (out 자체를 모든 fetch_one 호출 경로에 새로 꿰지 않는다, ponytail)."""
    return state.parent.parent / "dedup" / "manifest.jsonl"


def _etag_duplicate(state, source_id, etag, size):
    """받기 전 완전 중복 사전 확인(O3 재설계) — 비멀티파트 ETag(하이픈 없음 = 단일 파트 업로드의 MD5
    그대로, 내용 해시와 같음)+크기가 다른 원천의 기존 지문과 일치하면 그 지문을, 아니면(멀티파트 ETag·
    크기 없음 등) None을 돌려준다. 멀티파트 ETag는 파트별 해시를 다시 해시한 값이라 내용과 무관하므로
    여기서 보지 않는다 — 그 경우는 받은 뒤 sha256로만 판단(`_sha_duplicate`)."""
    if not (etag and "-" not in etag and size is not None):
        return None
    from pipeline.extract import dedup as DEDUP

    return DEDUP.find_duplicate(_dedup_manifest_path(state), source_id, etag=etag, size=size)


def _sha_duplicate(state, source_id, path):
    """받은 뒤(또는 폴더 원본처럼 이미 로컬에 있는 파일) 완전 중복 확인 — sha256이 다른 원천의 기존 지문과
    일치하면 그 지문을, 아니면 None을 돌려준다."""
    from common.core.contract import file_hash
    from pipeline.extract import dedup as DEDUP

    return DEDUP.find_duplicate(_dedup_manifest_path(state), source_id, sha=file_hash(path))


def _record_duplicate(state, source_id, dup, etag=None, size=None, updated_at=None, sha=None):
    from pipeline.extract import dedup as DEDUP

    DEDUP.record_duplicate(
        _dedup_manifest_path(state), source_id, dup.get("source_id"), etag=etag, size=size, updated_at=updated_at, sha=sha
    )


def is_remote(source):
    """원본이 Object Storage에서 오는지 — rdb:csv(표가 키를 알려줌)면 True, 폴더면 False."""
    return str(source).startswith("rdb:")


# _safe_name·_safe_join은 common/ids.py(safe_name·safe_join)로 옮김(독립 검토 MAJOR-1 — modules/load도 같이 씀,
# modules/load가 modules/parse를 import하면 이미지 경계 위반이라 공용 위치는 common/). 동작은 바이트 동일(이름만 별칭).
from common.core.contract import safe_filename as _safe_name  # noqa: E402
from common.core.contract import safe_path_join as _safe_join  # noqa: E402


def _dedupe_names(name_of):
    """GH1-02 — _safe_name이 서로 다른 키를 같은 평면 이름으로 뭉개면(예: 다른 하위 폴더의 같은 파일 이름) 겹치는
    것만 전체 키의 짧은 해시(8자)를 이름에 붙여 갈라놓는다 — 이번 배치(목록 조회 1회) 안에서만 감지, 안 겹치면
    이름은 그대로(기존 이름·처리 기록과 호환)."""
    from collections import Counter

    counts = Counter(name_of.values())
    out = {}
    for k, n in name_of.items():
        if counts[n] <= 1:
            out[k] = n
            continue
        h = hashlib.sha256(k.encode("utf-8")).hexdigest()[:8]
        stem, dot, ext = n.rpartition(".")
        out[k] = f"{stem}__{h}.{ext}" if dot else f"{n}__{h}"
    return out


def _s3():
    """boto3 s3 클라이언트 — common/objectstore.py(OP21, modules/search/mcp_server.py 근거 이미지와 공용)로 승격,
    동작은 바이트 동일(그 함수에 그대로 위임)."""
    from common.store.objectstore import client

    return client()


def _rdb_cols():
    """RDB 표의 열 이름 — 기본값은 실 EDW `AI.FileStorageMap`(id·content_version_id·s3_key·original_filename·file_size)과
    같음. bucket·etag·content_type·company·doc_type·contract·updated·version·supersedes·is_deleted는 이 표에
    없다(기본값 ""=미설정) — 옛 synth 시험 표(doc_location.csv)처럼 다른 표를 쓸 땐 RDB_COL_<필드>로 전부 채운다.
    열 이름도 SQL에 그대로 끼워 넣으므로(mssql은 대괄호·pg는 f-string, 표 이름만 각각 Identifier) 표 이름과 같은
    화이트리스트로 확인(독립 검토 BLOCK 3 — SQL 삽입)."""
    required = {
        "doc_id": "id",
        "key": "s3_key",
        "size": "file_size",
        "filename": "original_filename",
        "content_version": "content_version_id",
    }
    optional = {
        "bucket": "",
        "etag": "",
        "content_type": "",
        "company": "",
        "doc_type": "",
        "contract": "",
        "updated": "",
        "version": "",
        "supersedes": "",
        "is_deleted": "",
    }
    # S7c — 설정 객체(이름을 글자로 지음: 칸 기본값 = 위 v와 같고, 비운 값은 필수 5칸만 ''로 유지(blank keep)·나머지는 기본값 ''라 같음)
    cols = {k: pc.by_env(f"RDB_COL_{k.upper()}", v) for k, v in {**required, **optional}.items()}
    bad = {k: v for k, v in cols.items() if v and not COL_ID_RE.match(v)}
    if bad:
        raise ValueError(f"[source] RDB_COL_* 값이 올바르지 않음(영문·숫자·_ 만) — {bad}")
    return cols


def _rdb_increment_col(cols):
    """증분(since) 기준 열 — updated_at 열이 있으면 그 열, 없으면 env RDB_INCREMENT_COL(기본 id) — AI.FileStorageMap처럼
    updated_at이 없는 표는 id(또는 content_version_id, env로 바꿈)로 전진 판정한다(같은 파일의 새 판이 새 행/새
    content_version_id로 들어온다는 가정). 열 이름이므로 같은 화이트리스트(COL_ID_RE)."""
    col = cols["updated"] or pc.cfg().connections.rdb.increment_col or cols["doc_id"]  # S7c — 설정 객체
    if not COL_ID_RE.match(col):
        raise ValueError(f"[source] RDB_INCREMENT_COL 값이 올바르지 않음(영문·숫자·_ 만) — {col!r}")
    return col


def _inc_value(row, col):
    """증분 비교값 — 숫자 문자열(csv 시험의 id 등)은 int로(문자열 비교면 '10' < '9'가 되는 함정 방지), 그 외(ISO8601
    날짜 등)는 그대로 — PG·mssql 네이티브 열은 이미 올바른 타입(int·timestamp)으로 오므로 그대로 통과."""
    v = row.get(col)
    return int(v) if isinstance(v, str) and v.lstrip("-").isdigit() else v


def _rdb_bucket_and_key(cols, r):
    """버킷·키 — bucket 열이 있으면 그 값, 없으면 key가 `s3://버킷/…` 꼴이면 그 안의 버킷, 둘 다 아니면 RDB_BUCKET."""
    raw_key = r[cols["key"]]
    if cols["bucket"] and r.get(cols["bucket"]):
        return r[cols["bucket"]], raw_key
    if isinstance(raw_key, str) and raw_key.startswith("s3://"):
        bucket, _, key = raw_key[5:].partition("/")
        return bucket, key
    bucket = pc.cfg().connections.rdb.bucket  # S7c — 설정 객체
    if not bucket:
        raise ValueError(f"[source] 버킷을 알 수 없음 — bucket 열 없음·key가 s3://버킷/… 꼴 아님, RDB_BUCKET 필요(key={raw_key!r})")
    return bucket, raw_key


def _load_done(state):
    """DET1 — `_processed_path()`의 처리 기록을 key → 그 key로 지금까지 처리된 **모든** 레코드 목록으로 모은다
    (key당 마지막 한 건만 남기면: `inc_col >= since` 경계 재조회에서 같은 s3_key에 새 판(새 id·content_version_id)이
    들어온 표는 옛 판 행이 다시 조회될 때 "최신 판 기록"과 달라 매번 '미완료'로 오판해 since가 전진하지
    못하고 그 자리를 영원히 다시 긁는다 — `_selftest_same_key_new_version`이 이 함정을 고정해 둠). 파일 하나를
    한 번 읽을 뿐이라 비용은 그대로(기존 — key당 1건)와 같음, 같은 key가 아주 자주(수천 번) 재사용되는 표만
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
    watermark까지 전진시켜 영영 못 받는다(독립 검토 BLOCK). etag·증분값 둘 다 없으면 식별할 수가 없으므로 늘
    '미완료'로 봐서 다시 시도(조용한 영구 누락보다 안전 — None과 None을 '같다'고 오판하는 함정은 이 단계에서도
    막는다). done은 key → 레코드 목록(`_load_done()`, DET1 — key당 1건만 남기면 `>=` 경계 재조회의 옛 판이
    오판된다)."""
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


def _rdb_filters():
    """env RDB_COMPANY·RDB_DOC_TYPE(콤마 목록, 선택) → 질의에 걸 값 목록(없으면 None = 필터 없음)."""

    def _list(name):
        v = pc.given(name)  # S7c — 설정 객체(목록 칸 RDB_COMPANY·RDB_DOC_TYPE — 준 값만: 없음·빈 글자 → None, 옛 `if v`)
        return list(v) if v is not None else None

    return _list("RDB_COMPANY"), _list("RDB_DOC_TYPE")


def _processed_path(state):
    """처리 기록 파일(11-01 — 원천 이름별 processed__<이름>.jsonl은 rdb:*·rdb:<이름>과 함께 지움)."""
    return state / "processed.jsonl"


def rdb_connect(extra_kwargs=True):
    """RDB(mssql) 연결 — SQLAlchemy `mssql+pymssql`(S8b, 5-4 — common.store.mssql, 연결 풀 없음). 접속은 common.connections.rdb의
    **읽기 계정**(사용자 10-29 — ops.md#op-03) + RDB_CONNECT_KWARGS(JSON — extra_kwargs=False면 안 넘김, gen_roster 옛 동작).
    rdb_discover·gen_roster도 이것으로."""
    from common.store import mssql

    kw, miss = mssql.login("read", extra=extra_kwargs)
    if miss:  # 옛 os.environ[name] — 없으면 KeyError(parsing_meta_db와 같은 꼴)
        raise KeyError(miss[0])
    return mssql.connect(**kw)


def _rdb_rows(table):
    """문서 위치 표(csv:<경로>)의 행을 공통 꼴로: doc_id·bucket·key·etag·size·filename·content_version·content_type·
    company_id·doc_type·contract_id·updated_at(증분값 — 처리 여부 판단)·version·supersedes_doc_id·is_deleted.
    (11-01 — 표 직접 질의(mssql·pg)·watermark·원천 목록 열 매핑은 지움 — csv만.)"""
    if not table.startswith("csv:"):
        raise ValueError(f"[source] rdb:{table} — 원천은 rdb:csv:<경로>만(11-01 사용자: rdb:*·rdb:<이름>·표 직접 질의 지움)")
    cols = _rdb_cols()
    company, doc_type = _rdb_filters()
    if company and not cols["company"]:
        print("[source] RDB_COMPANY 지정됐지만 이 표에 company 열이 없음(RDB_COL_COMPANY 미설정) — 경고, 필터 없이 진행", flush=True)
        company = None
    if doc_type and not cols["doc_type"]:
        print("[source] RDB_DOC_TYPE 지정됐지만 이 표에 doc_type 열이 없음(RDB_COL_DOC_TYPE 미설정) — 경고, 필터 없이 진행", flush=True)
        doc_type = None
    inc_col = _rdb_increment_col(cols)
    with open(table[4:], encoding="utf-8-sig", newline="") as f:
        rows = [
            r
            for r in csv.DictReader(f)
            if (not company or r.get(cols["company"]) in company) and (not doc_type or r.get(cols["doc_type"]) in doc_type)
        ]
    mapped = []
    for r in rows:
        bucket, key = _rdb_bucket_and_key(cols, r)
        etag = str(r[cols["etag"]]).strip('"') if cols["etag"] and r.get(cols["etag"]) not in (None, "") else None
        size = int(r[cols["size"]]) if r.get(cols["size"]) not in (None, "") else None
        mapped.append(
            {
                "doc_id": str(r[cols["doc_id"]]),
                "bucket": bucket,
                "key": key,
                "etag": etag,
                "size": size,
                "filename": r.get(cols["filename"]) or None,
                "content_version": r.get(cols["content_version"]) or None,
                "content_type": r.get(cols["content_type"]) or None,
                "company_id": r.get(cols["company"]) or None,
                "doc_type": r.get(cols["doc_type"]) or None,
                "contract_id": r.get(cols["contract"]) or None,
                "updated_at": _inc_value(r, inc_col),
                "version": r.get(cols["version"]) or None,
                "supersedes_doc_id": r.get(cols["supersedes"]) or None,  # AD38 list_documents 출처
                "is_deleted": str(r.get(cols["is_deleted"]) if r.get(cols["is_deleted"]) is not None else "0").strip().lower()
                in ("1", "true", "t"),
            }
        )
    return mapped


def _filter_unsupported_rows(rows, name_of):
    """SI44(source) — 압축(ARCHIVE_EXT)·처리 엔진 없는 확장자(registry.engines_for)는 받기 전에 걸러낸다(name_of
    계산 뒤 sample() 호출 전 — 다운로드 자체를 안 함). 사유 말은 prepare.py의 skipped.jsonl과 같다
    (pipeline.extract.prepare._unsupported_reason 재사용 — 같은 규칙 한 곳). 반환: (남은 rows, 걸러진 rows 목록)."""
    from pipeline.extract.prepare import _unsupported_reason

    kept, skipped = [], []
    for r in rows:
        name = name_of[r["key"]]
        reason = (
            _unsupported_reason(Path(name)) if Path(name).suffix else None
        )  # 확장자 없는 이름(옛 synth 표처럼 filename 열이 없어 doc_id로 대체)은 판정 보류 — prepare 단계가 그대로 봄
        (skipped if reason else kept).append({"row": r, "file": name, "reason": reason} if reason else r)
    return kept, skipped


def _record_source_skipped(state, skipped):
    """건너뛴 행 기록(state/source_skipped.jsonl, {file,key,reason} — prepare.py skipped.jsonl과 같은 사유 말) +
    다시 받을 길이 없으므로(지원 안 하는 형식) 바로 처리 완료로 표시(watermark가 이 파일 때문에 영영 안 전진하는
    것을 막음 — finish()가 파싱 성공분을 기록하는 것과 같은 자리 `_processed_path`)."""
    with (state / "source_skipped.jsonl").open("a", encoding="utf-8") as f:
        for s in skipped:
            f.write(json.dumps({"file": s["file"], "key": s["row"]["key"], "reason": s["reason"]}, ensure_ascii=False) + "\n")
    with _processed_path(state).open("a", encoding="utf-8") as f:
        for s in skipped:
            r = s["row"]
            f.write(json.dumps({"key": r["key"], "etag": r.get("etag"), "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")


# ── warm 저장소(2026-10-22, 프리페치) ──────────────────────────────────────────────
# 다음 배치 원본을 미리 받아 두는 1회용 캐시. `python -m pipeline.extract.source warm --csv <배치csv>`(프리페치)가
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
    """`python -m pipeline.extract.source warm --csv <batch.csv> [--workers N]` — 다음 배치 원본을 미리 받아
    SOURCE_WARM에 심는 프리페치(배치 러너가 현재 배치 파싱 중에 백그라운드로 돌린다). watermark·처리 기록·
    manifest는 전혀 건드리지 않고 파일만 내려놓는다 — 실제 파싱(fetch_one)이 warm 적중으로 가져간다.
    한 건 실패는 그 배치가 늦어질 뿐(일반 다운로드로 폴백)이라 조용히 넘어간다."""
    import argparse

    ap = argparse.ArgumentParser(prog="pipeline.extract.source warm")
    ap.add_argument("--csv", required=True, help="make_batch.py가 만든 다음 배치 csv(id·s3_key·original_filename·file_size)")
    ap.add_argument("--workers", type=int, default=max(1, int(pc.cfg().extract.prefetch_workers)))  # S7c — 설정 객체(기본 2)
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
        p = _warm_key_path(wd, t["bucket"], t["key"])
        p.unlink(missing_ok=True)  # 인덱스엔 없는데 파일만 남은 잔여도 이번에 갈아치움
        tmp = wd / (p.name + ".part")
        try:
            actual = cli.head_object(Bucket=t["bucket"], Key=t["key"]).get("ContentLength")
            if t["size"] is not None and actual is not None and int(actual) != int(t["size"]):
                print(f"[source] warm: 크기 불일치(참고) — RDB({t['size']}) ≠ OS({actual}): {t['bucket']}/{t['key']}", flush=True)
            cli.download_file(t["bucket"], t["key"], str(tmp))
            os.replace(tmp, p)  # 인덱스에 보이는 파일은 항상 완전한 내용
            with _warm_locked(wd):
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
            print(f"[source] warm: 실패(무시·폴백) — {t['bucket']}/{t['key']}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            return False

    with SP.span("extract.warm", "extract", total=len(targets)) as sp:  # op-01 — 프리페치 1회 = 1행(받은 수·실패 수)
        if a.workers > 1 and len(targets) > 1:
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
                done = sum(1 for r in ex.map(_one, targets) if r)
        else:
            done = sum(1 for r in (_one(t) for t in targets) if r)
        sp.add(done=done, failed=len(targets) - done)
    print(f"[source] warm: {done}/{len(targets)}건 · {time.time() - t0:.1f}s → {wd}", flush=True)
    return 0


def _rdb_resolve_spec(spec, state, limit):
    """rdb:<spec> → (names, fetch_one(name,dest)→Path, state) — resolve()가 부름. 11-01부터 csv:<경로>만."""
    return _rdb_plan(spec, state, limit)


def _rdb_plan(table, state, limit=0):
    """문서 위치 표(csv:)의 대상 행 → (names, fetch_one(name,dest)→Path, state). resolve()가 부르고 모든 이름을 즉시 받는다(AD44).
    받기 전 대조는 ETag가 있으면 ETag(head_object), 없으면 크기(ContentLength)로 — 불일치면 거부·기록하고 받지
    않는다(그 문서만 건너뛰고 나머지는 계속, 독립 검토 BLOCK 1 — 호출부 resolve()가 fetch_one 전체를
    try로 안 감싸면 크래시한다).
    O3 재설계(2026-10-14) — ETag 대조가 통과해도(이 원천 안에서는 정상) 받기 전에 다른 원천의 기존 지문과
    완전히 같은 내용인지(비멀티파트 ETag+크기) 한 번 더 보고, 일치하면 `DuplicateContent`를 던져 받지 않는다
    (처리 완료로도 기록 — 다시 안 받음). 멀티파트 ETag는 받은 뒤 sha256으로 같은 확인을 한다."""
    done = _load_done(state)
    rows = [r for r in _rdb_rows(table) if not _rdb_is_done(done, r["key"], r["etag"], r["updated_at"])]
    name_of = _rdb_names(rows)  # original_filename(또는 doc_id) — 충돌하면 doc_id 접두로 구분
    rows, skipped = _filter_unsupported_rows(rows, name_of)  # SI44(source) — 압축·엔진 없는 확장자는 받기 전에 걸러냄
    if skipped:
        _record_source_skipped(state, skipped)
    name_of = {r["key"]: name_of[r["key"]] for r in rows}
    rows = sorted(rows, key=lambda r: r["key"])[: limit or None]
    by_name = {name_of[r["key"]]: r for r in rows}
    names = sorted(by_name)
    cli = _s3()
    book = threading.Lock()  # 2026-10-22 — 병렬 fetch(SOURCE_FETCH_WORKERS)에서 기록(manifest 재작성·append)을 잠금

    def fetch_one(name, dest):
        o = by_name[name]
        source_id = f"s3://{o['bucket']}/{o['key']}"
        if o["etag"]:
            actual = cli.head_object(Bucket=o["bucket"], Key=o["key"])["ETag"].strip('"')
            if actual != o["etag"]:
                with book:
                    with (state / "rejected.jsonl").open("a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(
                                {
                                    "table": table,
                                    "doc_id": o["doc_id"],
                                    "bucket": o["bucket"],
                                    "key": o["key"],
                                    "etag_rdb": o["etag"],
                                    "etag_store": actual,
                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                raise EtagMismatch(
                    f"[source] ETag 불일치 — RDB({o['etag']}) ≠ Object Storage({actual}): {o['bucket']}/{o['key']} — 거부·기록"
                )
            # O3 재설계(2026-10-14) — 받기 전 완전 중복 사전 확인: 비멀티파트 ETag+크기가 다른 원천의 기존
            # 지문과 일치하면 받지 않고 건너뜀(캐비앗 — 멀티파트 ETag는 _etag_duplicate가 그대로 None을 줘
            # 아래 받은 뒤 sha256 확인으로 넘어간다).
            dup = _etag_duplicate(state, source_id, actual, o["size"])
            if dup:
                with book:
                    _record_duplicate(state, source_id, dup, etag=actual, size=o["size"], updated_at=o["updated_at"])
                    with _processed_path(state).open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"key": o["key"], "etag": o.get("etag"), "ver": o.get("updated_at")}, ensure_ascii=False) + "\n")
                raise DuplicateContent(f"[source] 받기 전 중복(ETag+크기) — {source_id} ≡ {dup.get('source_id')} — 받지 않음")
        elif o["size"] is not None:
            actual = cli.head_object(Bucket=o["bucket"], Key=o["key"]).get("ContentLength")
            if actual != o["size"]:
                # 2026-10-15(운영) — RDB file_size가 Object Storage와 어긋나 있어 필수 비교에서 제외:
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
        # etag·size 둘 다 없으면 받기 전 대조 생략(비교할 근거가 없음) — 그대로 받는다
        dest.mkdir(parents=True, exist_ok=True)
        f = _warm_take(o, dest, name)  # warm 프리페치(2026-10-22) — 받아 둔 다음 배치 원본이면 즉시 이동
        if f is not None:
            print(f"[source] warm 적중 — 다운로드 생략: {o['bucket']}/{o['key']}", flush=True)
        else:
            f = _safe_join(dest, name)  # (기존 경로) 원격에서 내려받기
            cli.download_file(o["bucket"], o["key"], str(f))
        # O3 재설계 — 받은 뒤 완전 중복 확인(멀티파트 ETag 등 사전 확인 못한 경우의 공용 경로): sha256이
        # 다른 원천 기록과 같으면 중복 — 파싱하지 않고 받은 사본은 지운다
        dup = _sha_duplicate(state, source_id, f)
        if dup:
            with book:
                _record_duplicate(state, source_id, dup, etag=o["etag"], size=o["size"], updated_at=o["updated_at"])
                with _processed_path(state).open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": o["key"], "etag": o.get("etag"), "ver": o.get("updated_at")}, ensure_ascii=False) + "\n")
            f.unlink(missing_ok=True)
            raise DuplicateContent(f"[source] 받은 뒤 중복(sha256) — {source_id} ≡ {dup.get('source_id')} — 파싱하지 않음")
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
                "company_id": o["company_id"],
                "doc_type": o["doc_type"],  # AD38 고객 하드 필터·list_documents 출처
                "contract_id": o["contract_id"],
                "updated_at": o["updated_at"],
                "content_type": o["content_type"],
                "version": o.get("version"),
                "supersedes_doc_id": o.get("supersedes_doc_id"),
                "is_deleted": o.get("is_deleted", False),
                "original_filename": o.get("filename"),
                "content_version_id": o.get("content_version"),  # AD44(c) FileStorageMap 고유 칸
                "source_system": _derive_source_from_key(o["key"]),
            }  # SI41 — publish_parse가 문서별로 이 값 사용(없으면 --source-system 폴백)
            man_f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in man.values()), encoding="utf-8")
        return f

    man_f = state / "manifest.jsonl"
    if not man_f.exists():  # fetch_one이 한 번도 안 불려도(대상 0건) 파일이 있어야 — 없으면 ids.source_uri가 조용히 file://로 떨어짐
        man_f.touch()
    C.put(SOURCE_MANIFEST=str(man_f))  # S7e2 — 덮기 파일(이 프로세스·하위 프로세스) + 인계 키라 env에도(contract.py)
    label = table
    print(f"[source] rdb:{label} · 대상 {len(names)}개(이미 처리 {len(done)}개 제외)", flush=True)
    return names, fetch_one, state


def resolve(source, out, limit=0):
    """→ (로컬 원본 폴더, 대상 파일 이름 목록, 상태 폴더). 폴더면 그대로, rdb:csv면 표의 키를 Object Storage에서 받음(AD44)."""
    state = Path(out) / "parse" / "_source"
    state.mkdir(parents=True, exist_ok=True)
    if str(source).startswith("s3://"):
        raise ValueError(f"[source] {source} — s3:// 폴더 가져오기는 11-01에 지움(사용자) — 폴더 또는 rdb:csv:<경로>")
    if str(source).startswith("rdb:"):
        local = Path(out) / "_source_files"
        names, fetch_one, state = _rdb_resolve_spec(source[len("rdb:") :], state, limit)
        ok = []
        nw = max(
            1, int(pc.cfg().extract.source.fetch_workers)
        )  # S7c — 설정 객체(기본 1) · 2026-10-22 — 문서별 병렬 다운로드(기본 1=기존 순차)
        if nw > 1 and len(names) > 1:
            # 병렬 — 다운로드·head_object(네트워크)를 워커에, 기록(manifest 재작성 등)은 fetch_one 안 잠금으로 안전.
            # 결과는 제출 순서(names 순)대로 회수해 manifest 행 순서를 기존과 같게. 원천 여러 개(rdb:*)면 이름 겹침
            # rename이 잠금 밖(_rename_manifest_entry)이라 이 경로는 단일 원천(rdb:csv 등)에만 권장 — 여럿이면 1로.
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=min(nw, len(names))) as ex:
                futs = {n: ex.submit(fetch_one, n, local) for n in names}
                for n in names:
                    try:
                        futs[n].result()
                        ok.append(n)
                    except (EtagMismatch, DuplicateContent) as e:  # ETag·크기 불일치·완전 중복 — 그 문서만 건너뛰고 계속
                        print(f"[source] {e}", flush=True)
            print(f"[source] 다운로드 병렬 {min(nw, len(names))}워커 완료 · {len(ok)}/{len(names)}건", flush=True)
        else:
            for n in names:
                try:
                    fetch_one(n, local)
                    ok.append(n)
                except (
                    EtagMismatch,
                    DuplicateContent,
                ) as e:  # ETag·크기 불일치 또는 완전 중복 — 그 문서만 건너뛰고 나머지는 계속(독립 검토 BLOCK 1)
                    print(f"[source] {e}", flush=True)
        if not Path(C.cfg().paths.source_manifest or "").exists():  # S7c — 설정 객체(위 put 뒤 다시 읽어 같은 값)
            raise RuntimeError("[source] rdb 모드인데 SOURCE_MANIFEST 파일이 없음 — 원본 위치가 조용히 file://로 떨어질 수 있어 멈춤")
        return local, ok, state
    src = Path(source)
    names = sorted(p.name for p in src.iterdir() if p.is_file() and p.name != ".gitkeep")[: limit or None]
    print(f"[source] 폴더 {src} · 대상 {len(names)}개", flush=True)
    return src, names, state


def _record_sha_before_delete(state, local, done, field="sha256"):
    """지우기 전에 sha256을 manifest.jsonl에 남겨 둠(SI39 요건⑧ — 원본을 즉시 지워도 publish_parse(`modules/load/
    parsing_meta.py`)가 로컬 없이도 EDW 행을 쓸 수 있게). 못 읽으면(파일이 이미 없는 등) 그 문서만 건너뜀."""
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
    (SI39 요건⑧, 2026-10-08 — publish_parse가 더는 원본을 올리지 않으므로 그걸 기다릴 이유가 없다. 옛
    PARSE_KEEP_ORIGINALS(publish 전까지 보존)는 폐지 · 디버그 보존 KEEP_LOCAL_ORIGINALS는 op-08에 지움).
    지우기 전에 항상 sha256을 manifest에 남긴다(`_record_sha_before_delete`) — publish_parse(modules/load/
    parsing_meta.py `plan()`)가 로컬 원본 없이도 이 값으로 EDW 행을 쓸 수 있게."""
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


def mark_done(state, done_names, is_s3):
    """스트리밍 묶음이 끝난 뒤 처리 기록(ETag 또는 (key, 증분값) 쌍) 남김 — Object Storage 기원(s3://·rdb:)일 때만
    (폴더는 추적할 상태가 없음, 받은 그대로 둠). is_s3 이름은 유지(호출부 호환) — 실제로는 is_remote(원격 기원이면
    True, rdb도 포함)."""
    if not is_s3 or not done_names:
        return
    man_f = state / "manifest.jsonl"
    man = {r["file_name"]: r for r in jl(man_f)} if man_f.exists() else {}
    rs = [man[n] for n in done_names if man.get(n)]
    with _processed_path(state).open("a", encoding="utf-8") as f:
        for r in rs:
            f.write(json.dumps({"key": r["key"], "etag": r["etag"], "ver": r.get("updated_at")}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py의 warm이 SOURCE_WARM을 넘김)
    utf8_stdout()
    if len(sys.argv) > 1 and sys.argv[1] == "warm":
        from pipeline.shared import runtrace

        with runtrace.run("source_warm", sys.argv[1:]):  # op-01 — run_docs가 부르는 자기 실행 1건
            raise SystemExit(_warm_cmd(sys.argv[2:]))  # 프리페치 — 다음 배치 원본을 SOURCE_WARM에 미리 받아 둠
