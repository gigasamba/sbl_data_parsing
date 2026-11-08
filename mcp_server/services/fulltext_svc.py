"""원문 도구 — list_doc_fulltext(gold doc에서 거르기·대표 결과 위치 읽기 → 폴더 목록 + sfid 발급) ·
get_doc_fulltext(sfid로 Object Storage에서 받기). 거르기 메타(doc_class·created_at·file_path 등)와 처리 기록(대표 결과 위치 silver_bucket·silver_key,
게시 시각 parsed_at, 원본 sha256 — op-17)은 모두 pgvector 원천 스키마 5벌의 doc 표에 있다 — PG를 못 읽으면 registry_unavailable.
sfid = `sf1.<base64url("버킷/키")>.<HMAC-SHA256 서명>` — 서명 키는 search.server.fulltext_secret(바꾸면 발급된 sfid 전부 무효).
응답 모양·한도는 mcp_server/schemas/fulltext.py.
"""

import base64
import hashlib
import hmac
import json
import operator
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import cache

from common.config.settings import cfg as common_cfg
from common.config.settings import reveal
from common.store.db.models import search_tables as ST
from mcp_server import config as mc
from mcp_server.schemas import fulltext as FT
from mcp_server.services.search.search_svc import KST, _like, kst_bound
from mcp_server.services.search.server_state import _retriever, dev_hint, dev_served

_HEX64 = re.compile(r"[0-9a-f]{64}")
_REP_FILE = re.compile(r"_(\d{4}-\d{2}-\d{2}_\d{6})\.(md|json)$")  # <stem>_<parse_date>.md|json — publish_parse_result.rep_md_key
_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?")
_OPS = {"<": operator.lt, "<=": operator.le, ">=": operator.ge}  # kst_bound가 주는 연산자
_WORKERS = 8  # 요청 하나 안의 저장소 목록·받기 동시 수


def _pool():
    """저장소 연결 풀 = (공용 자리 MCP_MAX_CONCURRENCY — list_doc_fulltext + get_doc_fulltext 자리) × 동시 _WORKERS.
    모자라면 boto3가 연결을 버렸다 다시 맺음."""
    from mcp_server.services.tool_runner import _OWN_SLOTS

    return (int(mc.cfg().server.max_concurrency or 0) + _OWN_SLOTS["do_get"]) * _WORKERS


class BadRequest(ValueError):
    pass


def _bad(detail):
    return {"error": "bad_request", "detail": detail}


def _secret():
    v = reveal(mc.cfg().server.fulltext_secret) or ""
    return v.encode("utf-8") if v else None


def _sig(secret, body):
    return base64.urlsafe_b64encode(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()).decode("ascii").rstrip("=")


def make_sfid(secret, bucket, key):
    body = base64.urlsafe_b64encode(f"{bucket}/{key}".encode()).decode("ascii").rstrip("=")
    return f"sf1.{body}.{_sig(secret, body)}"


def read_sfid(secret, sfid):
    """sfid → (버킷, 키) 또는 None(형식 틀림·서명 다름 — 위조이거나 서명 키가 바뀜)."""
    parts = str(sfid).split(".")
    try:
        if len(parts) != 3 or parts[0] != "sf1" or not hmac.compare_digest(parts[2].encode(), _sig(secret, parts[1]).encode()):
            return None
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode("utf-8")
    except (ValueError, UnicodeError):  # ASCII 아닌 글자·깨진 base64 — 위조로 봄
        return None
    bucket, _, key = raw.partition("/")
    return (bucket, key) if bucket and key else None


def _when(v, upper, name):
    """since/until·created_* — `YYYY-MM-DD` 또는 시간대 없는 `YYYY-MM-DD HH:MM:SS`(KST). 날짜만이면 until = 다음 날 00:00 미만(그날 전체).
    시간대가 붙었거나 형식이 틀리면 BadRequest. 반환 (연산자, aware datetime)."""
    if not _NAIVE.fullmatch(str(v).strip()):
        raise BadRequest(f"{name}: YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS(시간대 없이 — KST)")
    try:
        return kst_bound(v, upper)  # 검색 created_*와 같은 규칙 — 여기는 형식만 더 좁게(시간대 없이)
    except ValueError as e:
        raise BadRequest(f"{name}: {e}") from None


def _aware(v):
    """DB 값(datetime 또는 ISO 글자) → aware datetime(시간대 없으면 KST) 또는 None."""
    if v in (None, ""):
        return None
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return t if t.tzinfo else t.replace(tzinfo=KST)


def _iso(v):
    t = _aware(v)
    return t.astimezone(KST).isoformat() if t else None


def _storage():
    """boto3 클라이언트 — Object Storage 설정이 없으면 None(source_storage_unavailable)."""
    if not common_cfg().connections.object_storage.endpoint:
        return None
    return _client()


@cache
def _client():
    """boto3 클라이언트 하나를 계속 씀(스레드 안전) — 요청마다 새로 만들지 않음."""
    from common.store.objectstore import client

    return client(timeout=FT.FILE_TIMEOUT_SEC, retries=1, max_pool=_pool())


def _rep_files(s3, bucket, folder):
    """대표 결과 폴더 바로 아래의 최신 .md·.json(engine/ 하위·source.json 제외) → (parse_date, {"md": obj|None, "json": obj|None})."""
    best = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=folder, Delimiter="/"):  # 바로 아래만
        for o in page.get("Contents", []):
            name = o["Key"][len(folder) :]
            m = _REP_FILE.search(name)
            if "/" in name or not m:
                continue
            kind = m.group(2)
            if kind not in best or m.group(1) > best[kind][0]:
                best[kind] = (m.group(1), o)
    dates = [d for d, _ in best.values()]
    return (max(dates) if dates else None), {k: (best[k][1] if k in best else None) for k in ("md", "json")}


def _pg(src):
    """원천 스키마 하나의 gold 연결(검색과 같은 연결 — 못 열거나 질의가 실패하면 예외, 호출부가 registry_unavailable로)."""
    return _retriever(src).pg


def _sources():
    """원천 스키마 전부 — 5벌 + 지금 검색하는 DEV 원천(server_state.dev_served — op-17)."""
    return [*ST.SOURCES, *dev_served()]


def _folder(key):
    """대표 결과 객체 키 → 그 문서 폴더(끝 '/') — 폴더가 없는 키는 None(목록을 보지 않음)."""
    return key.rsplit("/", 1)[0] + "/" if key and "/" in key else None


def do_list(
    docs=None,
    source_system=None,
    doc_class=None,
    sf_op_id=None,
    since=None,
    until=None,
    created_since=None,
    created_until=None,
    limit=FT.LIST_LIMIT_DEFAULT,
    cursor=None,
):
    """gold doc에서 거르기(분류·영업 기회·등록 시각·게시 시각·원천·이름/경로/sha256) — 대표 결과 위치·게시 시각·원본 sha256도 같은 doc 행에서."""
    t0 = time.perf_counter()
    secret = _secret()
    if secret is None:
        return {"error": "not_configured", "detail": "search.server.fulltext_secret(sfid 서명 키)가 비어 있음"}
    conds, vals = [], []
    try:
        if not any(x not in (None, "", []) for x in (docs, source_system, doc_class, sf_op_id, since, until, created_since, created_until)):
            raise BadRequest("조건이 하나도 없음 — docs·source_system·doc_class·sf_op_id·since/until·created_since/until 중 하나 이상")
        if docs and (not isinstance(docs, list) or len(docs) > FT.DOCS_MAX):
            raise BadRequest(f"docs는 목록, {FT.DOCS_MAX}개 이하")
        hexes = [str(x) for x in docs or [] if _HEX64.fullmatch(str(x))]
        paths = [str(x) for x in docs or [] if not _HEX64.fullmatch(str(x)) and "/" in str(x)]
        names = [str(x) for x in docs or [] if not _HEX64.fullmatch(str(x)) and "/" not in str(x)]
        for name, v, upper in (("since", since, False), ("until", until, True)):  # 게시 시각 축(doc.parsed_at)
            if v:
                op, t = _when(v, upper, name)
                conds.append(f"parsed_at {op} %s")
                vals.append(t.isoformat())
        if source_system and str(source_system).upper().removesuffix("-TEST") not in {s.upper() for s in ST.SOURCES}:
            src, found = ST.source_of(source_system), []
            if ST.is_dev(src):  # DEV-<n> 꼴만 DB를 봄 — 그 원천 스키마가 있을 때만(prd는 늘 없음, op-17)
                try:
                    found = dev_served()
                except Exception:
                    return {"error": "registry_unavailable"}
            if src not in found:
                raise BadRequest("source_system은 SFDC·CRMS·LAS·FAQ·Other 중 하나(-test 붙어도 됨)" + dev_hint(found))
        srcs = [ST.source_of(source_system)] if source_system else None  # 원천 스키마 고르기 — 안 주면 모두(5벌 + DEV)
        for col, v in (("doc_class", doc_class), ("sf_op_id", sf_op_id)):  # doc.attrs 키(없는 원천은 0건)
            if v:
                conds.append("attrs @> %s::jsonb")  # 담김 — GIN 색인을 탐
                vals.append(json.dumps({col: str(v)}))
        for name, v, upper in (("created_since", created_since, False), ("created_until", created_until, True)):
            if v:
                op, t = _when(v, upper, name)
                conds.append(f"created_at {op} %s")
                vals.append(t.isoformat())
        if cursor not in (None, "") and (not str(cursor).isdecimal() or not str(cursor).isascii()):
            raise BadRequest("cursor는 앞 응답의 batch.next_cursor 값 그대로")
        lim = max(1, min(int(limit or FT.LIST_LIMIT_DEFAULT), FT.LIST_LIMIT_MAX))
    except (BadRequest, TypeError, ValueError) as e:
        return _bad(str(e))
    if docs:
        alt = []
        if hexes:  # 원본 sha256(= 출력 doc_key)
            alt.append("sha256 = ANY(%s)")
            vals.append(hexes)
        if paths:  # 원본 전체 경로(= gold file_path)
            alt.append("file_path = ANY(%s)")
            vals.append(paths)
        for n in names:  # 원본 파일 이름(확장자 포함) = 경로 마지막 조각
            alt.append("(file_path = %s OR file_path LIKE %s ESCAPE '!')")
            vals += [n, "%/" + _like(n)]
        conds.append("(" + " OR ".join(alt) + ")" if alt else "1 = 0")
    if cursor not in (None, ""):
        conds.append("doc_id > %s")
        vals.append(int(cursor))
    try:
        rows, matched = [], 0
        for src in srcs or _sources():  # 원천 스키마마다 같은 조건 — doc_id는 5벌 공용 시퀀스라 합쳐서 한 줄로 정렬·쪽 넘김
            rs, m = _select(_pg(src), src, conds, vals, cursor not in (None, ""), lim)
            rows += rs
            matched += m
    except Exception:
        return {"error": "registry_unavailable"}
    rows.sort(key=lambda r: r["doc_id"])
    more, rows = len(rows) > lim, rows[:lim]
    s3 = _storage()
    if s3 is None and rows:
        return {"error": "source_storage_unavailable"}
    locs = [(r["silver_bucket"], _folder(r["silver_key"])) for r in rows]
    try:  # 폴더 목록은 동시에 — 결과는 행 순서대로, 하나라도 실패하면 source_storage_unavailable
        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            listed = list(ex.map(lambda loc: _rep_files(s3, *loc) if loc[0] and loc[1] else None, locs))
    except Exception:
        return {"error": "source_storage_unavailable"}
    out, total = [], 0
    for r, (bucket, folder), got in zip(rows, locs, listed):
        files = {"md": None, "json": None}
        hit = _REP_FILE.search(r["silver_key"] or "")
        parse_date = hit.group(1) if hit else None
        if got is not None:  # 폴더가 있는 결과 위치만 — 빈 값은 목록을 보지 않음
            parse_date, files = got
        ok = any(files.values())
        fl = None
        if ok:
            fl = {}
            for kind, o in files.items():
                if o is None:
                    fl[kind] = None
                    continue
                total += int(o["Size"])
                fl[kind] = {
                    "name": o["Key"].rsplit("/", 1)[-1],
                    "size": int(o["Size"]),
                    "etag": str(o.get("ETag", "")).strip('"'),
                    "sfid": make_sfid(secret, bucket, o["Key"]),
                }
        out.append(
            {
                "file_name": str(r["file_path"]).rsplit("/", 1)[-1],
                "doc_key": r["sha256"],
                "source_system": r["source_system"],
                "doc_class": r["doc_class"],
                "sf_op_id": r["sf_op_id"],
                "created_at": _iso(r["created_at"]),
                "parse_date": parse_date,
                "rep_uri": f"s3://{bucket}/{folder}" if bucket and folder else None,
                "status": "ok" if ok else "no_files",
                "files": fl,
            }
        )
    batch = {
        "matched": int(matched),
        "returned": len(out),
        "next_cursor": str(rows[-1]["doc_id"]) if more else None,
        "files_total_bytes": total,
    }
    return {"batch": batch, "documents": out, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _select(pg, src, conds, vals, has_cursor, lim):
    """원천 스키마 하나 — (이 쪽 행 lim+1개, 쪽과 무관한 matched). cursor 조건·값은 늘 맨 끝. doc_class·sf_op_id는 doc.attrs 키 —
    그 키가 없는 원천은 거르면 0건, 출력은 NULL. source_system 출력 = 스키마의 원천 이름(저장값)."""
    s = pg.schema
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    base = conds[:-1] if has_cursor else conds
    bwhere = (" WHERE " + " AND ".join(base)) if base else ""
    matched = pg.q(f"SELECT COUNT(*) AS n FROM {s}.doc{bwhere}", tuple(vals[:-1] if has_cursor else vals))[0]["n"]
    sel = ", ".join(f"attrs->>'{c}' AS {c}" for c in ("doc_class", "sf_op_id"))
    rows = pg.q(
        f"SELECT doc_id, file_path, {sel}, created_at, sha256, silver_bucket, silver_key FROM {s}.doc{where} ORDER BY doc_id LIMIT %s",
        (*vals, lim + 1),
    )
    return [{**r, "source_system": ST.label(src)} for r in rows], matched


def _created_ok(locs, lo, hi):
    """등록 시각 가드 — 대표 결과 파일(.md 또는 같은 이름 .json)마다 gold doc 행(silver_bucket·silver_key = 그 .md 키 — 정확히 같음)의
    created_at이 범위 안인지. 원천 스키마마다 질의 한 번(요청한 .md 키 전부). 반환 = 범위 안인 (버킷, .md 키) 집합 —
    행이 없거나(재게시로 옛 날짜가 된 파일 포함) created_at이 비면 빠짐(확인 못 하면 통과시키지 않음)."""
    want = {(b, _md_key(k)) for b, k in locs}
    ok: set = set()
    if not want:
        return ok
    mds = sorted({k for _, k in want})
    for src in _sources():
        pg = _pg(src)
        for r in pg.q(f"SELECT silver_bucket, silver_key, created_at FROM {pg.schema}.doc WHERE silver_key = ANY(%s)", (mds,)):
            t, loc = _aware(r["created_at"]), (r["silver_bucket"], r["silver_key"])
            if loc in want and t and (lo is None or _OPS[lo[0]](t, lo[1])) and (hi is None or _OPS[hi[0]](t, hi[1])):
                ok.add(loc)
    return ok


def _md_key(key):
    return key[: -len(".json")] + ".md" if key.endswith(".json") else key


def _try(fn):
    """(값, None) 또는 (None, 예외) — 동시 실행 결과를 입력 순서대로 따질 때."""
    try:
        return fn(), None
    except Exception as e:
        return None, e


def do_get(files=None, json_section=None, created_since=None, created_until=None):
    t0 = time.perf_counter()
    secret = _secret()
    if secret is None:
        return {"error": "not_configured", "detail": "search.server.fulltext_secret(sfid 서명 키)가 비어 있음"}
    if not isinstance(files, list) or not 1 <= len(files) <= FT.GET_FILES_MAX:
        return _bad(f"files는 sfid 1~{FT.GET_FILES_MAX}개 목록(list_doc_fulltext가 준 값 그대로)")
    try:
        lo = _when(created_since, False, "created_since") if created_since else None
        hi = _when(created_until, True, "created_until") if created_until else None
    except BadRequest as e:
        return _bad(str(e))
    keys = [k.strip() for k in str(json_section).split(",") if k.strip()] if json_section else None
    s3 = _storage()
    if s3 is None:
        return {"error": "source_storage_unavailable"}
    return _get_files(files, keys, json_section, s3, secret, lo, hi, t0)  # 가드를 걸었을 때만 gold를 읽음(안 걸면 저장소만)


def _get_files(files, keys, json_section, s3, secret, lo, hi, t0):
    """head는 모두 동시에 → 입력 순서대로 head 크기로 받을 파일을 미리 골라 동시에 받음 → 입력 순서대로 지금까지와 같은 판정.
    미리 받지 않은 파일(앞 파일이 받기 실패·깨진 JSON이라 자리가 남은 경우)은 그 자리에서 받음 — 결과는 한 줄씩 받던 때와 같다."""
    locs = [read_sfid(secret, sfid) for sfid in files]
    in_range = None
    if lo or hi:
        try:
            in_range = _created_ok({loc for loc in locs if loc}, lo, hi)
        except Exception:
            return {"error": "registry_unavailable"}  # 가드를 걸었는데 확인 못 하면 조용히 통과시키지 않음
    cand = [i for i, loc in enumerate(locs) if loc and (in_range is None or (loc[0], _md_key(loc[1])) in in_range)]

    def head(i):
        return _try(lambda: int(s3.head_object(Bucket=locs[i][0], Key=locs[i][1])["ContentLength"]))

    def fetch(i):  # head 뒤에 커져도 상한까지만 읽음
        return _try(lambda: s3.get_object(Bucket=locs[i][0], Key=locs[i][1])["Body"].read(FT.FILE_MAX_BYTES + 1))

    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        heads = dict(zip(cand, ex.map(head, cand)))
        pre, room = [], 0
        for i in cand:
            size = heads[i][0]
            if size is not None and size <= FT.FILE_MAX_BYTES and room + size <= FT.BATCH_MAX_BYTES:
                pre.append(i)
                room += size
        reads = dict(zip(pre, ex.map(fetch, pre)))
    out, ok_n, total, truncated = [], 0, 0, False
    for i, sfid in enumerate(files):
        loc = locs[i]
        if loc is None:
            out.append({"sfid": str(sfid)[:32], "skip_reason": "bad_sfid"})
            continue
        bucket, key = loc
        name = key.rsplit("/", 1)[-1]
        kind = "md" if name.endswith(".md") else "json"
        skip = {"sfid": sfid, "name": name, "kind": kind}
        if i not in heads:
            out.append({**skip, "skip_reason": "created_out_of_range"})
            continue
        size, e = heads[i]
        if size is None:
            out.append({**skip, "skip_reason": "missing" if _not_found(e) else "download_failed"})
            continue
        if size > FT.FILE_MAX_BYTES:
            out.append({**skip, "skip_reason": "too_large"})
            continue
        if total + size > FT.BATCH_MAX_BYTES:
            out.append({**skip, "skip_reason": "batch_full"})
            truncated = True
            continue
        raw, e = reads.get(i) or fetch(i)
        if raw is None:
            out.append({**skip, "skip_reason": "missing" if _not_found(e) else "download_failed"})
            continue
        if len(raw) > FT.FILE_MAX_BYTES:
            out.append({**skip, "skip_reason": "too_large"})
            continue
        if total + len(raw) > FT.BATCH_MAX_BYTES:
            out.append({**skip, "skip_reason": "batch_full"})
            truncated = True
            continue
        if kind == "md":
            content = raw.decode("utf-8", "replace")
        else:
            try:
                content = json.loads(raw.decode("utf-8"))
            except ValueError:  # 깨진 JSON — 이 파일만 건너뜀
                out.append({**skip, "skip_reason": "download_failed"})
                continue
            if keys and isinstance(content, dict):
                content = {k: content[k] for k in keys if k in content}
        total += len(raw)
        ok_n += 1
        out.append(
            {
                "sfid": sfid,
                "name": name,
                "kind": kind,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": "ok",
                "content": content,
            }
        )
    batch = {
        "requested": len(files),
        "ok": ok_n,
        "skipped": len(files) - ok_n,
        "total_bytes": total,
        "truncated": truncated,
        "json_section": json_section or None,
    }
    return {"batch": batch, "files": out, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _not_found(e):
    code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NotFound")
