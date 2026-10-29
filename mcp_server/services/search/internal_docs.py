"""MCP에 노출하지 않는 내부 조회 — 문서 단건·그림·근거 이미지·집계·용어·문서 목록·하드 필터 문서 덤프(search 안쪽 경로·selftest).
S5(10-26, refactor_plan 5-1·D-007 — 코디네이터 답 Q5 a)에 mcp_server/main.py(옛 data_retrieval/mcp_server.py)에서 옮김 — 내용 그대로
(설정 상수만 mcp_server/config.py의 CFG로).
"""

import io
import json
import re
import threading
import time
from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(mcp 칸 — S7d)
from mcp_server.config import CFG
from mcp_server.services.search.server_state import _STATE, _retriever


def _images_index():
    p = Path(mc.cfg().output.images or APP_ROOT / "output" / "parse" / "_images" / "index.jsonl")  # S7d — 설정 객체
    if not p.exists():
        return None, p
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()], p


def do_get_document(doc, client=None):
    """BR50(I) — client 인자(명시적으로 줬을 때만) + SEARCH_CLIENT_HARD=1이면 다른 고객 문서는 거부(error) — 이전
    검색에서 얻은 키로 아무 고객 문서나 조회되던 구멍. client를 안 주면(기존 호출부 전부) 전과 바이트 동일 —
    하드 격리 중에도 그때는 지금처럼 그대로 돌려준다(알려진 한계, mcp-usage.md 문서화 — 서버 쪽 인가는 이 모듈 밖)."""
    R = _retriever()
    if R.pg:
        s = R.pg.schema
        key = str(doc).split(":")[0]  # doc_key(sha256) 또는 chunk_key(sha256:순번)도 받음
        cond, val = (
            ("doc_id = %s", int(doc))
            if str(doc).isdigit()
            else ("file_sha256 = %s", key)
            if len(key) == 64
            else ("file_name = %s", str(doc))
        )
        rows = R.pg.q(
            f"SELECT doc_id, file_path, file_name, file_sha256, source_uri, doc_format, pages, parse_engine, summary, overview, summary_src, "
            f"client, contract_no, contract, full_text FROM {s}.doc WHERE {cond} LIMIT 1",
            (val,),
        )
        d = rows[0] if rows else None
    else:
        docs = R.local.docs
        key = str(doc).split(":")[0]
        d = (
            docs[int(doc)]
            if str(doc).isdigit() and int(doc) < len(docs)
            else next((x for x in docs if x["file_name"] == str(doc) or x["file_sha256"] == key), None)
        )
        if d is not None:
            d = {**d, "doc_id": docs.index(d)}
    if d is None:
        return {"error": f"문서 없음: {doc}"}
    if d.get("file_sha256") in getattr(
        R, "hidden", ()
    ):  # OP1 — 숨김 문서는 본문 대신 이 메시지(error 관례, do_get_document 기존 패턴과 같음)
        return {"error": "숨김(원천에서 삭제됨)", "doc_key": d.get("file_sha256"), "hidden": True}
    from mcp_server.services.search import clientscope as CS

    allowed, strict, hard = CS.client_scope(None, client, R.clients())
    if hard and not CS.allows(d.get("client"), allowed, strict):
        return {"error": "다른 고객 문서 — 거부(SEARCH_CLIENT_HARD)", "doc_key": d.get("file_sha256")}
    out = {
        k: d.get(k)
        for k in (
            "doc_id",
            "file_path",
            "file_name",
            "doc_format",
            "pages",
            "parse_engine",
            "summary",
            "overview",
            "summary_src",
            "client",
            "contract_no",
            "contract",
        )
    }
    from common.core.contract import uri_from_path

    out.update(doc_key=d.get("file_sha256"), source_uri=d.get("source_uri") or uri_from_path(d.get("file_path")))
    text = d.get("full_text") or ""
    lim = max(1000, CFG.MAX_CHARS - len(json.dumps(out, ensure_ascii=False, default=str)) - 200)
    out.update(chars=len(text), text=text[:lim], truncated=len(text) > lim)
    return out


def _png(im):
    im.thumbnail((CFG.MAX_IMAGE_PX, CFG.MAX_IMAGE_PX))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def do_get_image(image_id, as_data=False, client=None):
    """BR50(I) — do_get_document와 같은 규칙: client를 명시적으로 줬을 때만 + SEARCH_CLIENT_HARD=1이면 다른 고객
    문서의 그림은 거부(client 안 주면 전과 바이트 동일, 알려진 한계는 do_get_document와 같음)."""
    recs, p = _images_index()
    if recs is None:
        return {"error": f"그림 기록 없음({p}) — 그림 파싱(백로그 F1~F4) 결과가 필요"}, None
    r = next((x for x in recs if x.get("image_id") == image_id), None)
    if r is None:
        return {"error": f"그림 없음: {image_id}"}, None
    R = _retriever()
    if r.get("doc") in R.hidden_names():  # OP1(독립 검토 BLOCK 반영) — 그림 기록은 이름(doc)으로만 연결돼 R.hidden_names()로
        return {"error": "숨김(원천에서 삭제됨)", "doc": r.get("doc"), "hidden": True}, None
    from mcp_server.services.search import clientscope as CS

    allowed, strict, hard = CS.client_scope(None, client, R.clients())
    if hard and not CS.allows(R.client_map().get(r.get("doc")), allowed, strict):
        return {"error": "다른 고객 자료 — 거부(SEARCH_CLIENT_HARD)", "doc": r.get("doc")}, None
    png = (p.parent.parent / r["png"]) if r.get("png") else None  # png는 output/parse 기준 상대 경로
    meta = {
        k: r.get(k)
        for k in ("image_id", "doc", "source_file", "page", "sheet", "bbox", "origin", "kind", "parent_image_id", "depth", "children")
    }
    meta.update(summary=(r.get("vlm") or {}).get("summary"), content=(r.get("vlm") or {}).get("content"), png=str(png) if png else None)
    if as_data and png and png.exists():
        from PIL import Image as PI

        with PI.open(png) as im:
            return meta, _png(im.convert("RGB"))
    return meta, None


_OFFICE_RENDER_EXTS = {".docx", ".xlsx", ".pptx"}  # BR55 — PIL이 못 여는 원본 형식(쪽 렌더 대신 그림 파싱 결과로)


def _parse_bbox(bbox):
    """BR55 — bbox 입력 정규화: 'x0,y0,x1,y1' 문자열이나 숫자 4개짜리 list/tuple만 허용(do_get_image가 메타로
    돌려주는 bbox는 list라 그대로 get_evidence_image에 넣으면 전에는 AttributeError로 죽었음). bbox 없음(None)은
    (None, True)=크롭 안 함, 형식이 안 맞으면(None, False) — 호출부(신뢰 경계)가 error로 돌린다."""
    if bbox is None:
        return None, True
    if isinstance(bbox, str):
        parts = [x for x in re.split(r"[,\s]+", bbox.strip()) if x]
    elif isinstance(bbox, (list, tuple)):
        parts = list(bbox)
    else:
        return None, False
    if len(parts) != 4:
        return None, False
    try:
        return [float(x) for x in parts], True
    except (TypeError, ValueError):
        return None, False


def _render_crop(src, page, bbox, dpi):
    """원본 쪽(PDF) 또는 이미지 파일(로컬 경로 — 서버 디스크 원본이든 원천에서 받은 tmp 사본이든 같음, Office
    원본은 호출부가 먼저 걸러 여기 안 옴) → bbox([x0,y0,x1,y1], 이미 _parse_bbox로 숫자 정규화된 값 — 호출부
    책임) 영역을 잘라 (meta, PNG bytes). 열기·렌더 실패는 그대로 올린다(여기선 안 잡음 — _safe_render_crop이
    신뢰 경계에서 잡음)."""
    b = bbox
    if src.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(src))
        page = max(1, min(int(page or 1), len(pdf)))
        im = pdf[page - 1].render(scale=dpi / 72).to_pil().convert("RGB")
        k = dpi / 72
    else:
        from PIL import Image as PI

        im = PI.open(src).convert("RGB")
        k = mc.cfg().search.ocr_dpi / 72  # OCR 상자는 pt(= px × 72 / OCR_DPI)로 저장됨
    if b and len(b) == 4:
        pad = 12
        im = im.crop((max(0, b[0] * k - pad), max(0, b[1] * k - pad), min(im.width, b[2] * k + pad), min(im.height, b[3] * k + pad)))
    return {"page": page, "bbox": b, "w": im.width, "h": im.height}, _png(im)


def _safe_render_crop(src, page, bbox, dpi):
    """BR55 — _render_crop을 신뢰 경계(MCP 도구)에서 감싼 것: 열기·렌더 실패(PIL.UnidentifiedImageError·그 밖
    OSError·pdfium.PdfiumError — 손상·형식 불일치 파일)는 크래시 대신 {"error": "render_failed"}로, 그 밖
    예상 못 한 예외는 그대로 올린다(내부에서 조용히 삼키지 않음 — rules/code.md §경계·에러)."""
    try:
        return _render_crop(src, page, bbox, dpi)
    except Exception as e:
        import pypdfium2 as pdfium
        from PIL import Image as PI

        if isinstance(e, (PI.UnidentifiedImageError, OSError, pdfium.PdfiumError)):
            return {"error": "render_failed"}, None
        raise


def _office_evidence_image(doc_name, doc_format, page, bbox, dpi):
    """BR55 — Office 원본(.docx/.xlsx/.pptx)은 PIL이 못 열어 쪽 렌더가 안 됨. 그림 파싱(F1~F4) 결과(get_image이
    쓰는 같은 output/parse/_images/index.jsonl)에서 같은 문서의 저장된 PNG를 찾아(쪽이 맞는 그림 우선) 그 그림을
    근거로 돌려준다 — bbox가 있으면 그 PNG를 한 번 더 자름(_render_crop 재사용, PNG라 이미지 분기를 그대로
    탐). 맞는 그림 기록이 없으면(그림이 없거나 아직 파싱 전) 렌더 불가를 분명히 알리는 error만 — LibreOffice로
    쪽을 새로 그리는 건 parse/image 쪽 몫(이 도구 범위 밖, 안 만듦)."""
    recs, p = _images_index()
    cands = [r for r in (recs or []) if r.get("doc") == doc_name and r.get("png")]
    cands.sort(key=lambda r: 0 if r.get("page") == page else 1)  # 쪽이 맞는 그림 먼저
    rec = cands[0] if cands else None
    if rec is None:
        return {"error": f"{doc_format} 원본은 쪽 렌더 불가 — get_image(image_id) 사용"}, None
    png_path = p.parent.parent / rec["png"]  # png는 output/parse 기준 상대 경로(do_get_image와 같은 계산)
    meta, png = _safe_render_crop(png_path, rec.get("page") or page, bbox, dpi)
    if meta.get("error"):
        return meta, None
    return {**meta, "image_id": rec["image_id"], "file_path": str(png_path)}, png


_EVID_SEM = None


def _evid_limiter():
    """OP21(S78) — 근거 이미지 원천 재접근(Object Storage 다운로드) 동시 요청 상한(MCP_EVID_MAX_CONCURRENCY,
    기본 4) — 일반 도구 동시 실행 상한(_limiter(), MCP_MAX_CONCURRENCY)과 별도로, 네트워크·원천 서버 부담만 따로
    제한한다(이미 큰 상한에 끼어 느려지지 않게)."""
    global _EVID_SEM
    if _EVID_SEM is None:
        _EVID_SEM = threading.Semaphore(mc.cfg().output.evid_max_concurrency)  # S7d — 설정 객체(처음 만들 때 한 번 읽음, 옛과 같음)
    return _EVID_SEM


def _parse_s3_uri(uri):
    """'s3://버킷/키' → (버킷, 키) · 그 밖(없음·file://·상대경로)은 (None, None)."""
    if not uri or not str(uri).startswith("s3://"):
        return None, None
    bucket, _, key = str(uri)[5:].partition("/")
    return (bucket, key) if bucket and key else (None, None)


def _parse_file_uri(uri):
    """'file://<경로>' → Path(경로) · 그 밖(없음·s3://·상대경로)은 None. 접두만 떼고 그대로 쓴다(parsing_meta.
    make_storage()와 같은 단순 규칙 — URL 인코딩·urlparse 안 씀, 이 저장소의 file:// 값은 늘 common.core.contract.
    source_uri_of()가 만든 Path.as_uri() 모양이거나 사람이 그대로 적은 로컬 경로)."""
    if not uri or not str(uri).startswith("file://"):
        return None
    p = str(uri)[len("file://") :]
    return Path(p) if p else None


def _local_evid_roots():
    """MCP_EVID_LOCAL_ROOTS(콤마 목록, 폴더 저장소 환경 시험용 — 사용자 결정 10-08) → 허용 루트 Path 목록
    (resolve된 절대경로). 비어 있으면(기본, env 없음) 빈 리스트 — file:// 근거 이미지 재접근은 전부 거부
    (지금과 바이트 동일)."""
    return [
        Path(r).resolve() for r in mc.cfg().output.evid_local_roots
    ]  # S7d — 설정 객체(목록 칸: 쉼표로 나눠 strip·빈 것 버림 — 옛 식과 같음)


def _under_allowed_root(path, roots):
    """path(심볼릭 링크면 resolve로 실제 대상까지 따라감)가 roots 중 하나 아래(그 자체 포함)인지 — 경로
    탈출('..')·심볼릭 링크로 허용 루트를 벗어나는 것을 막는 마지막 방어선(독립 보안 검토 대상)."""
    try:
        rp = path.resolve()
    except OSError:
        return False
    return any(rp == root or root in rp.parents for root in roots)


class _EvidFetchTooLarge(Exception):
    """스트리밍 중 MCP_EVID_MAX_MB를 넘음 — 받던 파일은 호출부가 바로 지움."""


class _EvidFetchTimeout(Exception):
    """스트리밍 중 MCP_EVID_TIMEOUT_SEC를 넘음 — 받던 파일은 호출부가 바로 지움."""


def _fetch_capped(cli, bucket, key, dest, max_bytes, deadline):
    """OP21 독립 보안 검토(10-09) 반영 — get_object를 청크로 읽어 dest에 쓰며 **실제 받은 바이트**를 센다
    (head_object ContentLength는 원천이 보고하는 값일 뿐이라 믿지 않음 — download_file 내부 스트리밍 중에는
    상한이 안 걸리던 구멍). 청크마다 두 상한을 같이 확인: 누적 바이트 > max_bytes면 _EvidFetchTooLarge, 그
    시각이 deadline(time.monotonic() 기준)을 넘으면 _EvidFetchTimeout — 둘 다 즉시 중단하고 받던 파일을 지운
    뒤 예외를 올린다(크기·시간 상한이 같은 루프 안)."""
    body = cli.get_object(Bucket=bucket, Key=key)["Body"]
    got = 0
    try:
        with open(dest, "wb") as f:
            while True:
                if time.monotonic() > deadline:
                    raise _EvidFetchTimeout()
                chunk = body.read(1 << 20)  # 1MB씩
                if not chunk:
                    break
                got += len(chunk)
                if got > max_bytes:
                    raise _EvidFetchTooLarge()
                f.write(chunk)
    except (_EvidFetchTooLarge, _EvidFetchTimeout, Exception):
        dest.unlink(missing_ok=True)  # 부분 파일 잔여 0(S78)
        raise
    finally:
        try:
            body.close()
        except Exception:
            pass
    return got


def do_evidence_image(doc, page=1, bbox=None, dpi=150, client=None):
    """원본 쪽(PDF) 또는 이미지 파일 → bbox(pt, 'x0,y0,x1,y1' 문자열이나 숫자 4개 list/tuple — do_get_image가
    메타로 돌려주는 bbox도 그대로 받음, BR55) 영역을 잘라 PNG 바이트. bbox 형식이 안 맞으면(그 밖 타입·개수)
    크래시 대신 {"error"}(MCP 신뢰 경계 검증). 원본이 Office 파일(.docx/.xlsx/.pptx, PIL이 못 엶)이면 쪽 렌더
    대신 그림 파싱 결과의 저장된 PNG로(`_office_evidence_image`, BR55) — 맞는 그림이 없으면 명확한 error.
    그 밖 열기·렌더 실패(손상 파일 등)도 `_safe_render_crop`이 잡아 {"error": "render_failed"}로(크래시 안 함).
    BR50(I) — client 범위 확인은 do_get_document(client=)에 그대로 맡김(같은 doc 키 해석·같은 거부 규칙, 중복 없음).
    원본이 이 서버 디스크에 없으면(SI39⑧ — 파싱 끝나면 바로 지움이 기본) OP21(S78): source_uri(s3://버킷/키)로
    원천 Object Storage에서 tmp 폴더로 받아 자르고 **바로 지운다**(받은 원본·tmp 둘 다 — finally에서, 크롭이
    실패해도 지움) — Object Storage 접속 설정(OS_ACCESS_KEY·OS_SECRET_KEY)이 있어야 가능(boto3는 rag-core
    이미지에도 있음, requirements-core.txt), 없으면 명확한 '사용 불가' 응답(크래시·조용한 빈 응답 아님 —
    OS_ACCESS_KEY를 안 설정한 판은 늘 이 경로, env-guide·mcp-usage.md 참고). 크기 상한(MCP_EVID_MAX_MB, 기본 50MB)·받기 시간 상한
    (MCP_EVID_TIMEOUT_SEC, 기본 20초)은 `_fetch_capped`가 받는 **동안**(스트리밍 청크마다) 확인한다(독립
    보안 검토 10-09 반영 — head_object 사전 확인만으로는 download_file 내부 스트리밍 중 상한이 안 걸림) ·
    동시 요청 상한(_evid_limiter). 응답 error는 코드만(`source_fetch_*`) — 버킷·키·엔드포인트·예외 원문은
    서버 로그에만(독립 보안 검토 CONCERN 반영 — 원천 내부 정보 노출 금지), MCP 서버는 실패해도 계속 동작.

    source_uri가 `file://<경로>`면(폴더 저장소 환경 시험, 사용자 결정 10-08) 원천이 이미 로컬 파일이라
    받기·지우기 없이 그 파일에서 바로 자른다 — MCP_EVID_LOCAL_ROOTS(콤마 목록 env)로 허용한 루트 아래일
    때만(비어 있으면, 기본, 전부 거부 — 지금과 바이트 동일), `_under_allowed_root`가 resolve() 뒤 그 루트
    아래인지 확인(경로 탈출·심볼릭 링크 차단). 크기 상한(MCP_EVID_MAX_MB)은 같이 적용, 시간 상한·동시 요청
    상한은 네트워크 왕복이 없어 해당 없음(디스크 읽기만)."""
    d = do_get_document(doc, client=client)
    if d.get("error"):
        return d, None
    b, ok = _parse_bbox(bbox)
    if not ok:
        return {"error": f"bbox 형식 오류: {bbox!r}"}, None
    if (d.get("doc_format") or "").lower() in _OFFICE_RENDER_EXTS:
        return _office_evidence_image(d.get("file_name"), d.get("doc_format"), page, b, dpi)
    src = Path(d["file_path"])
    if src.exists():
        meta, png = _safe_render_crop(src, page, b, dpi)
        if meta.get("error"):
            return meta, None
        return {**meta, "file_path": str(src)}, png

    bucket, key = _parse_s3_uri(d.get("source_uri"))
    if bucket is None:
        local = _parse_file_uri(d.get("source_uri"))
        roots = _local_evid_roots() if local is not None else []
        if local is None or not roots or not _under_allowed_root(local, roots) or not local.is_file():
            return {"error": "source_unknown"}, None
        local = local.resolve()  # 검사한 실제 경로 그대로 연다(검사-사용 사이 링크 교체 방지 — 보안 검토 10-08 권고)
        max_mb = mc.cfg().output.evid_max_mb  # S7d — 설정 객체
        try:
            too_big = local.stat().st_size > max_mb * 1e6
        except OSError:
            return {"error": "source_unknown"}, None
        if too_big:
            return {"error": "source_fetch_too_large"}, None
        meta, png = _safe_render_crop(local, page, b, dpi)
        if meta.get("error"):
            return meta, None
        return {**meta, "file_path": str(local)}, png
    from common.store import objectstore as OS
    from mcp_server.services import objectstore_access as OSA

    if not OSA.configured():
        return {"error": "source_storage_unavailable"}, None
    sem = _evid_limiter()
    if not sem.acquire(blocking=False):
        return {"error": "source_fetch_busy"}, None
    try:
        _o = mc.cfg().output  # S7d — 설정 객체(요청마다 한 번 묶어 읽음)
        timeout = _o.evid_timeout_sec
        max_mb = _o.evid_max_mb
        import tempfile

        from common.core.contract import safe_filename, safe_path_join

        cli = OS.client(timeout=timeout)
        with tempfile.TemporaryDirectory(prefix="mcp_evid_") as td:
            tmp_path = safe_path_join(Path(td), safe_filename(Path(key).name, "") or "orig")
            try:
                _fetch_capped(cli, bucket, key, tmp_path, int(max_mb * 1e6), time.monotonic() + timeout)
            except _EvidFetchTooLarge:
                print(f"[mcp] 근거 이미지 — 크기 상한 초과(MCP_EVID_MAX_MB={max_mb}) bucket={bucket} key={key}", flush=True)
                return {"error": "source_fetch_too_large"}, None
            except _EvidFetchTimeout:
                print(f"[mcp] 근거 이미지 — 시간 상한 초과(MCP_EVID_TIMEOUT_SEC={timeout}) bucket={bucket} key={key}", flush=True)
                return {"error": "source_fetch_timeout"}, None
            except Exception as e:  # 버킷·키·엔드포인트·예외 원문은 서버 로그에만(독립 보안 검토 반영 — 클라이언트 응답에 안 실음)
                print(f"[mcp] 근거 이미지 — 원천 받기 실패 bucket={bucket} key={key}: {e}", flush=True)
                return {"error": "source_fetch_failed"}, None
            try:
                meta, png = _safe_render_crop(tmp_path, page, b, dpi)
            finally:
                tmp_path.unlink(missing_ok=True)  # TemporaryDirectory가 폴더 전체도 지우지만(S78 디스크 잔여 0) 크롭 실패해도 먼저 지움
            if meta.get("error"):
                return meta, None
            return {**meta, "file_path": f"s3://{bucket}/{key}"}, png
    finally:
        sem.release()


def do_aggregate(question, client=None):
    """client(BR50 D) — do_search의 client 인자와 같은 범위: SEARCH_CLIENT_HARD=1이면 route() 전에 다른 고객
    문서를 뺀다(clientscope 공용 규칙, aggregate.local()·aggregate.pg()에서 — 집계가 '최상위 근거'로 다른 고객
    구조화 행을 돌려주던 구멍). client를 안 주면(기존 호출부 전부) 전과 바이트 동일.
    struct()(doc_link_list 등, X1/X1b 옵트인) 경로는 이번 범위 밖 — 남은 한계로 보고에 적음."""
    from mcp_server.services.search import aggregate as AG

    # OP1(독립 검토 BLOCK 반영) — 이미 떠 있는 Retriever가 있으면만 hidden을 건넴(_retriever()를 새로 만들지 않음 —
    # AG.struct()는 원래 Retriever·검색 묶음과 독립적으로 동작(정형 저장소 연결만 필요)이라 여기서 강제로 만들면
    # 묶음이 없는 상태(기동 직후·시험)에서도 쓸데없이 묶음 로딩을 시도해 죽는다, _selftest_aggregate_struct_fail).
    hidden = _STATE["R"].hidden if _STATE.get("R") is not None else None
    st = AG.struct(question, hidden=hidden)  # 정형 저장소 질문(X1/X1b) — ask·평가와 같은 한 곳(OP1 — hidden 적용, doc_link_list만)
    if st is not None:
        return st
    R = _retriever()
    from mcp_server.services.search import clientscope as CS

    allowed, strict, hard = CS.client_scope(question, client, R.clients())
    cl_kw = {"client": allowed, "client_strict": strict} if hard else {}
    llm_complete = _agg_llm_complete()  # R1(AD42·AD45②) — SEARCH_AGG_LLM=1이고 LLM 설정됐을 때만(아니면 None)
    r = (
        AG.pg(R.pg, question, llm_complete=llm_complete, hidden=R.hidden, **cl_kw)
        if R.pg
        else AG.local(_STATE["bundle"], question, llm_complete=llm_complete, hidden=R.hidden, **cl_kw)
    )  # OP1 — 숨김 문서는 집계(건수·합계·표)에서도 제외
    return r or {"note": "집계 질문으로 판별되지 않음(건수·합계·표) — search를 쓰세요"}


def _agg_llm_complete():
    """R1(AD42·AD45②) — SEARCH_AGG_LLM(기본 끔, =1로 켬 — AR3 10-12)이고 LLM이 설정돼 있을 때만 aggregate.route()에 줄 콜백을 만든다(아니면 None
    → route()가 조용히 regex 결과만 씀, 꺼짐이면 완전히 지금과 같음 · LLM 미설정이면 여기서 조용히 None — 외부 호출 없음).
    gamma 패키지 agg_llm_route 경유(GA2, agent= 필수) — decompose.split_question에 L.chat을 주입하는 것과 같은 방식(mcp_server.py do_search)."""
    from mcp_server.services.search.aggregate import agg_llm_on  # 단일 읽기 지점(aggregate.route()와 공용)

    if not agg_llm_on():
        return None
    from common.ai import llm as L

    if not L.configured():
        return None
    tmo = mc.cfg().search.agg.llm_timeout  # MCP p95 3초 목표(OP8) — 검색 경로라 짧게, 넘으면 검색으로 폴백(OP11 검토)
    return lambda p: L.chat(
        [{"role": "user", "content": p}], temperature=0.0, max_tokens=500, json_mode=True, agent="agg_llm_route", timeout=tmo
    )


def do_lookup_term(term, k=5, client=None):
    """용어(정식명·동의어·약어) → 정의·별칭·관련 개념 + 관련 문서·청크 상위 N(X4).
    BR50(I) — client 인자 + SEARCH_CLIENT_HARD=1이면 다른 고객 청크·문서는 docs·chunks에서 뺀다(clientscope 공용
    규칙, client 안 주면 전과 바이트 동일)."""
    from mcp_server.services.search import clientscope as CS
    from mcp_server.services.search.terms import lookup_term

    info = lookup_term(term)
    if info is None:
        return {"error": f"사전에 없음: {term}"}
    R = _retriever()
    chunks = R._concept_top(info["concept_id"], k)
    allowed, strict, hard = CS.client_scope(None, client, R.clients())
    docs, out_chunks = {}, []
    for chunk_key, count in chunks:
        ci = R.key_local.get(chunk_key)
        d = R.local.docs[R.local.chunks[ci]["doc"]] if ci is not None else None
        if hard and d is not None and not CS.allows(d.get("client"), allowed, strict):
            continue
        if d is not None:
            docs[d["file_name"]] = docs.get(d["file_name"], 0) + count
        out_chunks.append((chunk_key, count))
    return {**info, "docs": sorted(docs, key=lambda n: -docs[n])[:k], "chunks": [{"chunk_key": c, "count": n} for c, n in out_chunks]}


def do_related(concept_id):
    """개념의 상위(broader)·관련(related) 개념 목록(X4).
    BR50(I) 검토 — 용어 사전(glossary) 메타데이터만 돌려줌(T.related_concepts), 문서·고객 연결이 전혀 없어 client
    인자를 안 더함(해당 없음, do_lookup_term·do_get_document와 달리 실제 거를 "문서"가 없음)."""
    from common.core import terms as T

    return {"concept_id": concept_id, "related": T.related_concepts(concept_id)}


def _manifest_by_name():
    """AD44 rdb 수집 manifest(output/parse/_source/manifest.jsonl) — doc_type·version·대체 문서·삭제 여부(RDB doc_location 메타)의
    가장 가까운 출처(AD45 완료 전까지 structdb에는 doc_location이 없음). 없으면 빈 dict — list_documents의 그 칸들은 None."""
    from common.core.contract import jl

    p = Path(mc.cfg().server.manifest or APP_ROOT / "output" / "parse" / "_source" / "manifest.jsonl")  # S7d — 설정 객체
    return {r["file_name"]: r for r in jl(p)} if p.exists() else {}


def do_list_documents(client=None, doc_type=None, since=None, latest_only=True, include_deleted=False):
    """AD38 — k 없이 적재된 문서 전체 목록(메타 질문: '~ 문서 전부'·'목록'). doc_type·version·date·contract_no는
    RDB doc_location 메타(manifest, AD44)가 있을 때만 채워짐(없으면 None — 파일명 규칙으로 문서 종류를 추정하지 않음, 범위 밖).
    client: 검색 search()와 같은 고객 명부(common.core.terms.match_clients)로 해석 — 별칭은 그 규칙을 그대로 따름(설정 안 됐으면 못 잡음).
    latest_only=True(기본): manifest의 supersedes_doc_id로 대체된 구판은 뺌(AR4② modules/search/supersede.py 공용 규칙,
    aggregate.doc_location_list와 같음). include_deleted=False(기본): is_deleted 문서는 뺌.
    LIST_DOCS_MAX(200건 — mcp_server/config.py) 넘으면 documents를 자르고 count=전체 건수·
    truncated=true·note에 "외 N건"(AD38 남은 것 — 코퍼스가 커지면 상한 없이 응답이 그대로 커지던 문제)."""
    from common.core.contract import uri_from_path
    from common.core.terms import match_clients
    from mcp_server.services.search import supersede as SS  # AR4② — aggregate.doc_location_list와 공용 규칙

    R = _retriever()
    man = _manifest_by_name()
    if R.pg:
        s = R.pg.schema
        rows = R.pg.q(f"SELECT file_sha256, file_name, file_path, source_uri, client, contract_no FROM {s}.doc")
        docs = [
            {
                "file_sha256": r["file_sha256"],
                "file_name": r["file_name"],
                "file_path": r["file_path"],
                "source_uri": r.get("source_uri"),
                "client": r.get("client"),
                "contract_no": r.get("contract_no"),
            }
            for r in rows
        ]
    else:
        docs = [
            {
                "file_sha256": d["file_sha256"],
                "file_name": d["file_name"],
                "file_path": d["file_path"],
                "source_uri": d.get("source_uri"),
                "client": d.get("client"),
                "contract_no": d.get("contract_no"),
            }
            for d in R.local.docs
        ]
    cl = set(match_clients(client, R.clients())) if client else None
    superseded = SS.superseded_set(man.values())  # AR4② — aggregate.doc_location_list와 공용 규칙(modules/search/supersede.py)
    out = []
    for d in docs:
        if d["file_sha256"] in R.hidden:  # OP1(독립 검토 BLOCK 반영) — 숨김 문서는 목록에도 안 올림
            continue
        if cl is not None and d.get("client") not in cl:
            continue
        m = man.get(d["file_name"]) or {}
        dt = m.get("doc_type")
        if doc_type and dt != doc_type:
            continue
        date = m.get("updated_at")
        if since and (not date or date < since):
            continue
        if not include_deleted and m.get("is_deleted"):
            continue
        if latest_only and SS.is_superseded(
            m.get("doc_id"), superseded
        ):  # GH1-15: supersedes_doc_id는 manifest doc_id(RDB 원천 키) 네임스페이스,
            continue  # file_name과 비교하면 거의 안 걸림 — 이 문서 자신의 doc_id로 비교(AR4②, supersede.py 공용)
        out.append(
            {
                "doc_key": d["file_sha256"],
                "file_name": d["file_name"],
                "source_uri": d.get("source_uri") or uri_from_path(d["file_path"]),
                "client": d.get("client"),
                "doc_type": dt,
                "version": m.get("version"),
                "date": date,
                "contract_no": m.get("contract_id") or d.get("contract_no"),
            }
        )
    out.sort(key=lambda r: r["file_name"])
    total = len(out)
    if CFG.LIST_DOCS_MAX > 0 and total > CFG.LIST_DOCS_MAX:  # AD38 남은 것 — 코퍼스가 커지면 상한 없이 그대로 커지던 응답(=0으로 끔)
        return {
            "documents": out[: CFG.LIST_DOCS_MAX],
            "count": total,
            "truncated": True,
            "note": f"상한 {CFG.LIST_DOCS_MAX}건까지만 반환 — 외 {total - CFG.LIST_DOCS_MAX}건",
        }
    return {"documents": out, "count": total}


def do_filter_documents(client=None, source_system=None, project_id=None, division=None, service_type=None, limit=100, client_like=None):
    """하드 필터(2026-10-20) — PG v_chunk_source 뷰에서 조건에 정확히 맞는 문서 전부와 그 청크 전부를 점수·임베딩 없이 돌려준다.
    조건: client(고객명)·source_system(SFDC/CRMS/LAS)·project_id(프로젝트 코드)·division(DS/DP/CD/CM/AD/AS)·
    service_type(CMO DS/CMO DP/CDO/ADC/...). 안 준 조건은 무시(전체 대상) · 문서 수가 limit(기본 100, 0이면 무제한)을
    넘으면 잘리고 truncated=true · client는 sf_acc_name·clients(JSON 텍스트, clientscope.doc_clients로 해석) 정확 일치 —
    참고: 중첩 사본(data_retrieval/data_retrieval)의 초안은 SQL에 client = %s 컬럼을 썼지만 v_chunk_source에 그 칸이
    없어 UndefinedColumn으로 죽는다(2026-10-20 축소 스키마) — 여기서는 스키마에 맞게 고침.
    반환: {total_docs, total_chunks, truncated, docs: [{doc_id, file_name, source_system, sf_acc_name, division,
    service_type, project_code__c, chunks: [{chunk_id, page, seq, section, chunk_text, bbox, ...}]}]}
    청크 텍스트는 MAX_CHARS 상한으로 자를 수 있다. 로컬 묶음(비PG) 저장소면 {"error": ...}."""
    R = _retriever()
    if not R.pg:
        return {"error": "PG(pgvector) 연결 없음 — 로컬 묶음만으로는 이 도구를 못 씀"}
    from mcp_server.services.search import clientscope as CS

    s = R.pg.schema
    t0 = time.perf_counter()
    conds, vals = [], []
    if source_system:
        conds.append("(source_system = %s OR doc_source_system = %s)")
        vals += [source_system, source_system]
    if project_id:
        conds.append("project_code__c = %s")
        vals.append(project_id)
    if division:
        conds.append("division = %s")
        vals.append(division)
    if service_type:
        conds.append("service_type = %s")
        vals.append(service_type)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    try:
        rows = R.pg.q(f"SELECT * FROM {s}.v_chunk_source{where} ORDER BY doc_id, chunk_id", tuple(vals))
    except Exception as e:
        return {"error": f"필터 조회 실패: {e}"}
    if client:
        if client_like:  # 2026-10-22 사용자: client_like=true → 포함매칭 — Python 후치필터도 LIKE로

            def _hit(r):
                if client in (r.get("sf_acc_name") or ""):
                    return True
                names = CS.doc_clients(None, r.get("clients"))
                if isinstance(names, str):
                    return client in names
                return bool(names) and any(client in str(n) for n in names)
        else:  # 기본: 정확 일치

            def _hit(r):
                if r.get("sf_acc_name") == client:
                    return True
                names = CS.doc_clients(None, r.get("clients"))
                if isinstance(names, str):
                    return names == client
                return bool(names) and client in names

        rows = [r for r in rows if _hit(r)]
    docs = {}
    for r in rows:
        d = r["doc_id"]
        if d not in docs:
            docs[d] = {
                "doc_id": d,
                "file_name": r.get("file_name"),
                "source_system": r.get("doc_source_system") or r.get("source_system"),
                "sf_acc_name": r.get("sf_acc_name"),
                "division": r.get("division"),
                "service_type": r.get("service_type"),
                "project_code__c": r.get("project_code__c"),
                "chunks": [],
            }
        docs[d]["chunks"].append(
            {
                k: r.get(k)
                for k in (
                    "chunk_id",
                    "page",
                    "line_start",
                    "line_end",
                    "bbox",
                    "section",
                    "seq",
                    "chunk_text",
                    "summary",
                    "clients",
                    "chunk_source_system",
                    "sf_op_id",
                    "sf_op_name",
                    "contract_id",
                    "contract_date",
                    "prod_name",
                )
            }
        )
    out = [docs[k] for k in sorted(docs)]
    truncated = bool(limit) and len(out) > int(limit)
    if truncated:
        out = out[: int(limit)]
    lim = CFG.MAX_CHARS
    for d in out:
        for c in d["chunks"]:
            t = c.get("chunk_text") or ""
            if len(t) > lim:
                c["chunk_text"] = t[:lim]
                c["truncated"] = True
    return {
        "total_docs": len(out),
        "total_chunks": sum(len(d["chunks"]) for d in out),
        "truncated": truncated,
        "docs": out,
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }
