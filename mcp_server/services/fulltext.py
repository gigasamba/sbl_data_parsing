"""원문 도구(mc-17, 11-01) — list_doc_fulltext(gold doc에서 거르기 → ParsingMeta에서 대표 결과 위치를 그때 읽음 → 폴더 목록 + sfid 발급) ·
get_doc_fulltext(sfid로 Object Storage에서 받기). pgvector에는 거르기 메타(원천 스키마 5벌 — doc_class·created_at·file_path 등)만, 대표 결과 위치·파싱 시각·원본 sha256은
EDW ParsingMeta에만(사용자 11-01) — ParsingMeta를 못 읽으면 registry_unavailable. 연결 키는 source_system + 원본 키(= gold doc.file_path — Object Storage 원본 경로).
sfid = `sf1.<base64url("버킷/키")>.<HMAC-SHA256 서명>` — 서명 키는 search.server.fulltext_secret(바꾸면 발급된 sfid 전부 무효).
응답 모양·한도는 mcp_server/schemas/fulltext.py.
"""

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import UTC, date, datetime, timedelta, timezone

from common.config.settings import cfg as common_cfg
from common.config.settings import reveal
from common.store.db.models import search_tables as ST
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


def _open_pm():
    from common.store import parsing_meta_db as PM

    try:
        return PM.make_db("read")
    except SystemExit as e:  # make_db는 접속 정보가 없으면 SystemExit
        raise RuntimeError("ParsingMeta 연결 정보 없음") from e


class _pm:
    """ParsingMeta 읽기 연결(common.connections.rdb 읽기 계정) — 못 열면 예외(호출부가 registry_unavailable로).
    조회가 실패하면(연결 끊김 등) 한 번 다시 연결해 다시 묻고, 또 실패하면 예외(운영 `_pm_retry`와 같음 — 사용자 11-02)."""

    def __init__(self):
        self.db = _open_pm()

    def _call(self, name, *args):
        try:
            return getattr(self.db, name)(*args)
        except Exception:
            self.close()
            self.db = _open_pm()
            return getattr(self.db, name)(*args)

    def rows_where(self, col, values):
        return self._call("rows_where", col, values)

    def rows_parsed(self, lo, hi):
        return self._call("rows_parsed", lo, hi)

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass  # 끊긴 연결을 닫다 난 오류는 무시


def _utc_text(bound):
    """(연산자, aware 시각) → (연산자, UTC 시간대 없는 글자) — ParsingMeta parsed_at은 SYSUTCDATETIME(UTC, 시간대 없음)."""
    op, t = bound
    return op, t.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


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
    """gold doc에서 거르기(분류·영업 기회·등록 시각·원천·이름/경로) → ParsingMeta에서 대표 결과 위치·파싱 시각·원본 sha256을 그때 읽음
    (pgvector에는 거르기 메타만 — 사용자 11-01). 연결 키는 source_system + 원본 키(= gold doc.file_path — Object Storage 원본 경로)."""
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
        p_lo = _utc_text(_when(since, False, "since")) if since else None
        p_hi = _utc_text(_when(until, True, "until")) if until else None
        if source_system and str(source_system).upper().removesuffix("-TEST") not in ("SFDC", "CRMS", "LAS", "FAQ", "OTHER"):
            raise BadRequest("source_system은 SFDC·CRMS·LAS·FAQ·Other 중 하나(-test 붙어도 됨)")
        srcs = [ST.source_of(source_system)] if source_system else list(ST.SOURCES)  # 원천 스키마 고르기(pl-28) — 안 주면 5벌 모두
        for col, v in (("doc_class", doc_class), ("sf_op_id", sf_op_id)):
            if v:
                conds.append(f"{col} = %s")
                vals.append(str(v))
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
    try:
        pm = _pm()
    except Exception:
        return {"error": "registry_unavailable"}
    try:
        # ParsingMeta에서 먼저 정해지는 범위(doc_key=sha256·파싱 시각) → 원본 경로 집합으로 gold를 좁힘
        if hexes:
            paths += [r["source_key"] for r in pm.rows_where("sha256", hexes) if r.get("source_key")]
        if docs:
            alt = []
            if paths:  # 원본 전체 경로(= gold file_path = ParsingMeta 키, 또는 doc_key로 찾은 경로)
                alt.append("file_path = ANY(%s)")
                vals.append(paths)
            for n in names:  # 원본 파일 이름(확장자 포함) = 경로 마지막 조각
                alt.append("(file_path = %s OR file_path LIKE %s ESCAPE '!')")
                vals += [n, "%/" + _esc(n)]
            conds.append("(" + " OR ".join(alt) + ")" if alt else "1 = 0")
        if p_lo or p_hi:
            keys = _parsed_keys(pm, p_lo, p_hi)
            # ponytail: 넓은 파싱 시각 범위는 원본 경로 목록이 커짐(배열 값 하나로 넘겨 자리표시자 상한은 없음, 수십만 건이면 느림)
            conds.append("file_path = ANY(%s)")
            vals.append(keys)
        if cursor not in (None, ""):
            conds.append("doc_id > %s")
            vals.append(int(cursor))
        rows, matched = [], 0
        for src in (
            srcs
        ):  # 원천 스키마마다 같은 조건 — doc_id는 5벌 공용 시퀀스라 합쳐서 한 줄로 정렬·쪽 넘김(대역은 스키마마다 파일이라 SQL로 못 합침)
            rs, m = _select(_retriever(src).pg, src, conds, vals, cursor not in (None, ""), lim)
            rows += rs
            matched += m
        rows.sort(key=lambda r: r["doc_id"])
        more, rows = len(rows) > lim, rows[:lim]
        from common.store import parsing_meta_db as PM

        by_key = {}
        for r in pm.rows_where("source_key", sorted({r["file_path"] for r in rows})):
            by_key.setdefault(r["source_key"], []).append(r)
        reps = {r["doc_id"]: PM.pick_rep(by_key.get(r["file_path"], []), r["source_system"]) for r in rows}
    except Exception:
        return {"error": "registry_unavailable"}
    finally:
        pm.close()
    s3 = _storage()
    if s3 is None and rows:
        return {"error": "source_storage_unavailable"}
    out, total = [], 0
    for r in rows:
        rep = reps[r["doc_id"]] or {}
        bucket, folder = rep.get("rep_bucket"), rep.get("rep_key")
        files = {"md": None, "json": None}
        parse_date = rep.get("parse_date")
        if bucket and folder and str(folder).endswith("/"):  # 폴더 키(끝 '/')만 — 빈 값·접두가 넓어지는 값은 목록을 보지 않음
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
                "doc_key": rep.get("sha256"),
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


def _parsed_keys(pm, lo, hi):
    """파싱 시각(since/until)에 맞는 원본 경로 — 범위 안 행이 있는 원본마다 쓸 행(pick_rep: active 중 최신)을 다시 골라
    그 행의 parsed_at이 범위 안일 때만(옛 행만 범위 안이면 빼서, 출력 parse_date와 거르기가 어긋나지 않게)."""
    from common.store import parsing_meta_db as PM

    cand = sorted({r["source_key"] for r in pm.rows_parsed(lo, hi) if r.get("source_key")})
    groups = {}
    for r in pm.rows_where("source_key", cand):
        groups.setdefault((r["source_key"], r.get("source_system")), []).append(r)
    out = set()
    for (key, sys_), rows in groups.items():
        pick = PM.pick_rep(rows, sys_) or {}
        t = str(pick.get("parsed_at") or "")[:19].replace("T", " ")
        if t and (not lo or _cmp_text(t, *lo)) and (not hi or _cmp_text(t, *hi)):
            out.add(key)
    return sorted(out)


def _cmp_text(t, op, bound):
    return {"<": t < bound, "<=": t <= bound, ">=": t >= bound}[op]


def _esc(x):
    """LIKE 안에서 글자 그대로(ESCAPE '!')."""
    return x.replace("!", "!!").replace("%", "!%").replace("_", "!_")


_SYS_LABEL = {"sfdc": "SFDC", "crms": "CRMS", "las": "LAS", "faq": "FAQ", "other": "Other"}


def _select(pg, src, conds, vals, has_cursor, lim):
    """원천 스키마 하나 — (이 쪽 행 lim+1개, 쪽과 무관한 matched). cursor 조건·값은 늘 맨 끝. 그 스키마에 없는 칸(doc_class·sf_op_id)을
    거르면 0건, 출력은 NULL. source_system 출력 = 스키마의 원천 이름(저장값 — 사용자 11-01 승인)."""
    have = set(ST.doc_columns(src))
    if any(c.split()[0] not in have for c in conds if c.split()[0] in ("doc_class", "sf_op_id")):
        return [], 0
    s = pg.schema
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    base = conds[:-1] if has_cursor else conds
    bwhere = (" WHERE " + " AND ".join(base)) if base else ""
    matched = pg.q(f"SELECT COUNT(*) AS n FROM {s}.doc{bwhere}", tuple(vals[:-1] if has_cursor else vals))[0]["n"]
    sel = ", ".join(c if c in have else f"NULL AS {c}" for c in ("doc_class", "sf_op_id"))
    rows = pg.q(f"SELECT doc_id, file_path, {sel}, created_at FROM {s}.doc{where} ORDER BY doc_id LIMIT %s", (*vals, lim + 1))
    return [{**r, "source_system": _SYS_LABEL[src]} for r in rows], matched


def _created_ok(pm, bucket, folder, lo, hi, cache):
    """등록 시각 가드 — 이 대표 결과 폴더(rep_bucket·rep_key)를 ParsingMeta에서 찾아 그 원본(source_key)의 gold doc.created_at이 범위 안인지.
    행이 없거나 created_at이 모두 비면 False(확인 못 하면 통과시키지 않음)."""
    if (bucket, folder) not in cache:
        keys = sorted(
            {r["source_key"] for r in pm.rows_where("rep_key", [folder]) if r.get("rep_bucket") == bucket and r.get("source_key")}
        )
        ts = []
        for src in ST.SOURCES if keys else ():
            pg = _retriever(src).pg
            ts += [
                t
                for t in (
                    _aware(r["created_at"]) for r in pg.q(f"SELECT created_at FROM {pg.schema}.doc WHERE file_path = ANY(%s)", (keys,))
                )
                if t
            ]
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
    pm, guard_cache = None, {}
    if lo or hi:  # 가드를 걸었을 때만 ParsingMeta·gold를 읽음(안 걸면 저장소만 — 운영과 같음)
        try:
            pm = _pm()
        except Exception:
            return {"error": "registry_unavailable"}
    try:
        return _get_files(files, keys, json_section, s3, secret, pm, lo, hi, guard_cache, t0)
    finally:
        if pm is not None:
            pm.close()


def _get_files(files, keys, json_section, s3, secret, pm, lo, hi, guard_cache, t0):
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
        if pm is not None:
            try:
                if not _created_ok(pm, bucket, key.rsplit("/", 1)[0] + "/", lo, hi, guard_cache):
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
