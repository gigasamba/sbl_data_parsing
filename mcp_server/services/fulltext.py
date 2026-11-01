"""원문 도구(mc-17, 11-01) — list_doc_fulltext(gold doc에서 문서 고르기 + 대표 결과 폴더 목록 + sfid 발급) ·
get_doc_fulltext(sfid로 Object Storage에서 받기). 검색 중 EDW에 접속하지 않는다(G19 — 목록·거르기·등록 시각 가드 모두 gold doc).
sfid = `sf1.<base64url("버킷/키")>.<HMAC-SHA256 서명>` — 서명 키는 search.server.fulltext_secret(바꾸면 발급된 sfid 전부 무효).
응답 모양·한도는 mcp_server/schemas/fulltext.py.
"""

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

from common.config.settings import cfg as common_cfg
from common.config.settings import reveal
from mcp_server import config as mc
from mcp_server.schemas import fulltext as FT
from mcp_server.services.search.server_state import _retriever

KST = timezone(timedelta(hours=9))  # 시간대 없는 시각은 KST
_HEX64 = re.compile(r"[0-9a-f]{64}")
_REP_FILE = re.compile(r"_(\d{4}-\d{2}-\d{2}_\d{6})\.(md|json)$")  # <stem>_<parse_date>.md|json — parsing_meta.rep_md_key
_NAIVE = re.compile(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?")


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
    s = str(v).strip()
    if not _NAIVE.fullmatch(s):
        raise BadRequest(f"{name}: YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS(시간대 없이 — KST)")
    try:
        if len(s) == 10:
            d = datetime.combine(date.fromisoformat(s), datetime.min.time(), KST)
            return ("<", d + timedelta(days=1)) if upper else (">=", d)
        return ("<=" if upper else ">="), datetime.fromisoformat(s).replace(tzinfo=KST)
    except ValueError as e:
        raise BadRequest(f"{name}: {e}") from None


def _aware(v):
    """DB 값(PG는 datetime, SQLite 대역은 글자) → aware datetime(시간대 없으면 KST) 또는 None."""
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
    from common.store.objectstore import client

    return client(timeout=FT.FILE_TIMEOUT_SEC)


def _rep_files(s3, bucket, folder):
    """대표 결과 폴더 바로 아래의 최신 .md·.json(engine/ 하위·source.json 제외) → (parse_date, {"md": obj|None, "json": obj|None})."""
    best = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=folder):
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


def _norm_sys(v):
    v = str(v)
    return v[: -len("-test")] if v.lower().endswith("-test") else v  # G4 — SFDC-test = SFDC


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
    t0 = time.perf_counter()
    secret = _secret()
    if secret is None:
        return {"error": "not_configured", "detail": "search.server.fulltext_secret(sfid 서명 키)가 비어 있음"}
    conds, vals = ["rep_bucket IS NOT NULL", "rep_key LIKE %s"], ["%_/"]  # 폴더 키(끝 '/')만 — 빈 값·접두가 넓어지는 값 제외
    try:
        if not any(x not in (None, "", []) for x in (docs, source_system, doc_class, sf_op_id, since, until, created_since, created_until)):
            raise BadRequest("조건이 하나도 없음 — docs·source_system·doc_class·sf_op_id·since/until·created_since/until 중 하나 이상")
        if docs:
            if not isinstance(docs, list) or len(docs) > FT.DOCS_MAX:
                raise BadRequest(f"docs는 목록, {FT.DOCS_MAX}개 이하")
            keys = [x for x in docs if _HEX64.fullmatch(str(x))]
            names = [str(x) for x in docs if not _HEX64.fullmatch(str(x))]
            alt = []
            if names:  # 원본 파일 이름(확장자 포함) = 경로 마지막 조각
                alt.append("(" + " OR ".join(["file_path = %s OR file_path LIKE %s ESCAPE '!'"] * len(names)) + ")")
                for n in names:
                    vals += [n, "%/" + n.replace("!", "!!").replace("%", "!%").replace("_", "!_")]
            if keys:
                alt.append("doc_key IN (" + ",".join(["%s"] * len(keys)) + ")")
                vals += keys
            conds.append("(" + " OR ".join(alt) + ")")
        for col, v in (("source_system", source_system and _norm_sys(source_system)), ("doc_class", doc_class), ("sf_op_id", sf_op_id)):
            if v:
                conds.append(f"{col} = %s")
                vals.append(str(v))
        for col, name, v, upper in (
            ("parsed_at", "since", since, False),
            ("parsed_at", "until", until, True),
            ("created_at", "created_since", created_since, False),
            ("created_at", "created_until", created_until, True),
        ):
            if v:
                op, t = _when(v, upper, name)
                conds.append(f"{col} {op} %s")
                vals.append(t.isoformat())
        if cursor not in (None, ""):
            if not str(cursor).isdecimal() or not str(cursor).isascii():
                raise BadRequest("cursor는 앞 응답의 batch.next_cursor 값 그대로")
            conds.append("doc_id > %s")
            vals.append(int(cursor))
        lim = max(1, min(int(limit or FT.LIST_LIMIT_DEFAULT), FT.LIST_LIMIT_MAX))
    except (BadRequest, TypeError, ValueError) as e:
        return _bad(str(e))
    try:
        pg = _retriever().pg
        rows, matched = _select(pg, conds, vals, cursor not in (None, ""), lim)
    except Exception:
        return {"error": "registry_unavailable"}
    more, rows = len(rows) > lim, rows[:lim]
    s3 = _storage()
    if s3 is None and rows:
        return {"error": "source_storage_unavailable"}
    out, total = [], 0
    for r in rows:
        bucket, folder = r["rep_bucket"], r["rep_key"]
        try:
            parse_date, files = _rep_files(s3, bucket, folder)
        except Exception:
            return {"error": "source_storage_unavailable"}
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
                "doc_key": r["doc_key"],
                "source_system": r["source_system"],
                "doc_class": r["doc_class"],
                "sf_op_id": r["sf_op_id"],
                "created_at": _iso(r["created_at"]),
                "parse_date": parse_date,
                "rep_uri": f"s3://{bucket}/{folder}" if bucket else None,
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


def _select(pg, conds, vals, has_cursor, lim):
    """(이 쪽 행 lim+1개, 쪽과 무관한 matched). cursor 조건·값은 늘 맨 끝."""
    s = pg.schema
    base = conds[:-1] if has_cursor else conds
    matched = pg.q(f"SELECT COUNT(*) AS n FROM {s}.doc WHERE " + " AND ".join(base), tuple(vals[:-1] if has_cursor else vals))[0]["n"]
    rows = pg.q(
        f"SELECT doc_id, file_path, doc_key, source_system, doc_class, sf_op_id, created_at, rep_bucket, rep_key FROM {s}.doc "
        "WHERE " + " AND ".join(conds) + " ORDER BY doc_id LIMIT %s",
        (*vals, lim + 1),
    )
    return rows, matched


def _created_ok(pg, bucket, folder, lo, hi, cache):
    """등록 시각 가드 — 이 대표 결과 폴더(rep_bucket·rep_key)를 가진 gold doc의 created_at이 범위 안인지. 행이 없거나 created_at이 모두 비면 False."""
    if (bucket, folder) not in cache:
        rows = pg.q(f"SELECT created_at FROM {pg.schema}.doc WHERE rep_bucket = %s AND rep_key = %s", (bucket, folder))
        ts = [t for t in (_aware(r["created_at"]) for r in rows) if t]
        cache[(bucket, folder)] = any((lo is None or _cmp(t, *lo)) and (hi is None or _cmp(t, *hi)) for t in ts)
    return cache[(bucket, folder)]


def _cmp(t, op, bound):
    return {"<": t < bound, "<=": t <= bound, ">=": t >= bound}[op]


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
    pg, guard_cache = None, {}
    if lo or hi:
        try:
            pg = _retriever().pg
        except Exception:
            return {"error": "registry_unavailable"}
    out, ok_n, total, truncated = [], 0, 0, False
    for sfid in files:
        loc = read_sfid(secret, sfid)
        if loc is None:
            out.append({"sfid": str(sfid)[:32], "skip_reason": "bad_sfid"})
            continue
        bucket, key = loc
        name = key.rsplit("/", 1)[-1]
        kind = "md" if name.endswith(".md") else "json"
        skip = {"sfid": sfid, "name": name, "kind": kind}
        if pg is not None:
            try:
                if not _created_ok(pg, bucket, key.rsplit("/", 1)[0] + "/", lo, hi, guard_cache):
                    out.append({**skip, "skip_reason": "created_out_of_range"})
                    continue
            except Exception:
                return {"error": "registry_unavailable"}  # 가드를 걸었는데 확인 못 하면 조용히 통과시키지 않음
        try:
            size = int(s3.head_object(Bucket=bucket, Key=key)["ContentLength"])
        except Exception as e:
            out.append({**skip, "skip_reason": "missing" if _not_found(e) else "download_failed"})
            continue
        if size > FT.FILE_MAX_BYTES:
            out.append({**skip, "skip_reason": "too_large"})
            continue
        if total + size > FT.BATCH_MAX_BYTES:
            out.append({**skip, "skip_reason": "batch_full"})
            truncated = True
            continue
        try:
            raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read(FT.FILE_MAX_BYTES + 1)  # head 뒤에 커져도 상한까지만 읽음
        except Exception as e:
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
