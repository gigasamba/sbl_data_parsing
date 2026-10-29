#!/usr/bin/env python3
"""OV1 — 대표 파싱 결과(_rep)를 OpenViking에 적재(REST, urllib만 — openviking_sdk는 이 이미지에 없음, 10-07
서버 이미지 경계 · 10-14 요건: OpenViking은 ①번 구조화 대상 — 자기 chunking·tree·L0/L1 요약을 스스로 만들고,
이 모듈은 올리기만 한다(받아오기는 cli/ov_export.py, OV_DOC_ROOT로 bundle.ov_summaries가 읽음)).

API(openviking_sdk 0.1.12 uploads.py `AsyncHTTPClient.add_resource`를 REST 두 호출로 재구현 — 2026-10-14
`.venv/Lib/site-packages/openviking_sdk/{client,options}.py` 직접 확인, 추측 없음):
  1. POST <url>/api/v1/resources/temp_upload  (multipart: file=<내용>)      → {"result": {"temp_file_id": ...}}
  2. POST <url>/api/v1/resources              (json: {parent, wait, timeout, temp_file_id, source_name, ...})
     → {"status": "ok"|"error", "result": {...}}  (error면 {"error": {"code", "message"}})
확인된 처리 옵션(`AddResourceOptions`, SDK가 검증하는 것만 — 그 밖은 추측하지 않음): `processing_mode`
("semantic_and_vectors"|"vectors_only") 하나뿐 — chunk·segment 크기를 직접 받는 필드는 SDK에 없음(grep 0건).
그런 서버 전용 처리 변수가 있다면 `AddResourceOptions.args`(Dict, SDK가 그대로 통과)로 받을 가능성은 있으나
실제 키 이름은 10-16 실 서버 확인 전까지 모른다 — OV_ARGS_JSON으로 통째로 넘기게만 해 둔다(추측한 키 이름 없음).

env:
  OV_URL · OV_ROOT(viking://resources/<root>)           — 없으면 둘 다 필요(services.py 접속 탐지와 같은 이름)
  OV_FEATURES에 "ingest"가 없으면 조용히 건너뜀(XS8과 같은 명시 스위치, common/services.ov_enabled)
  OV_PROCESSING_MODE(선택) — "semantic_and_vectors"|"vectors_only"
  OV_ARGS_JSON(선택) — 서버 전용 추가 옵션 JSON 객체 문자열, add_resource의 "args"로 그대로 전달
  OV_INGEST_TIMEOUT(선택, 기본 1800) — 문서 1건 적재 대기 초(wait=true)

사용: python load/ov_ingest.py [--rep-dir output/parse/_rep] [--out output/ov_ingest]
결과: <out>/result.json({문서: {status: ok|skip|fail, ...}}) — 이미 OV에 있는 문서(cli/ov_export.list_docs
이름 대조)·본문 없는 문서는 skip, 실패는 fail(다음 재실행에서 다시 시도 — skip 아님). 재실행은 멱등(OV에
있으면 다시 안 올림).
"""

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
from common.config import settings as C  # noqa: E402 — common 칸(OV_URL)·비밀 꺼내기(S7c)
from common.core.console import utf8_stdout  # noqa: E402 — 옆 import들과 같은 자리(앞 코드 뒤)
from common.core.paths import APP_ROOT  # noqa: E402
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)
from pipeline.load.openviking_api import list_docs  # noqa: E402 — cli/ov_export.py와 공용(이름 대조 규칙을 갈라지지 않게)
from pipeline.load.parsing_meta import render_md  # noqa: E402 — _rep/<doc>.json → 마크다운(SI39와 같은 렌더러)

PROCESSING_MODES = {"semantic_and_vectors", "vectors_only"}

FILE_META: dict = {}  # s3_key → EDW 메타 dict (--file-meta로 로드, build_bundle과 공용)
BUNDLE_DOCS: dict = {}  # file_name → docs.jsonl dict (division, prod_name, service_type 등 infer_categories 결과)


def _load_bundle_docs(rep_dir):
    """build_bundle 결과 docs.jsonl을 읽어 file_name → dict (division, prod_name 등). 같은 폴더의 edw/bundle/docs.jsonl."""
    p = Path(rep_dir).parent.parent / "edw" / "bundle" / "docs.jsonl"
    if not p.exists():
        return {}
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            d = json.loads(ln)
            fn = d.get("file_name")
            if fn:
                out[fn] = d
    return out


def _load_file_meta(path):
    """--file-meta 로 받은 JSONL(s3_key → EDW 메타 dict) 로드."""
    if not path:
        return {}
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        k = r.get("s3_key")
        if k:
            out[k] = r
    return out


def _key(name):
    """OV 폴더 이름 대조 — 공백·대소문자만 정규화(10-16 실 서버에서 OV가 확장자를 떼거나 바꾸면 보정 필요,
    지금은 ov_export.list_docs가 돌려주는 폴더 이름과 업로드 때 준 source_name을 그대로 비교)."""
    return (name or "").strip().lower()


def _result(resp):
    if resp.get("status") == "error":
        err = resp.get("error") or {}
        raise RuntimeError(f"{err.get('code', 'UNKNOWN')}: {err.get('message', '')}")
    return resp.get("result") or {}


def _ov_headers(extra=None):
    """trusted 모드 인증 헤더 — OV_API_KEY·OV_ACCOUNT(기본 default)·OV_USER(기본 default)."""
    h = {}
    key = C.reveal(pc.cfg().connections.openviking.api_key)  # S7c — 설정 객체(SecretStr)
    if key:
        h["X-API-Key"] = key
    h["X-OpenViking-Account"] = pc.cfg().connections.openviking.account
    h["X-OpenViking-User"] = pc.cfg().connections.openviking.user
    if extra:
        h.update(extra)
    return h


def _post_json(base, path, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{base}{path}", data=data, headers=_ov_headers({"Content-Type": "application/json"}), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post_multipart(base, path, filename, content, timeout):
    boundary = f"----ovingest{uuid.uuid4().hex}"
    pre = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/markdown; charset=utf-8\r\n\r\n"
    ).encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    body = pre + content.encode("utf-8") + post
    req = urllib.request.Request(
        f"{base}{path}", data=body, headers=_ov_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}), method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def add_resource(base, root, filename, content, *, wait=True, timeout=1800, processing_mode=None, args=None, tags=None, tag_mode="replace"):
    """temp_upload → resources(REST 재구현, SDK uploads.py의 add_resource와 같은 두 호출).
    tags를 직접 전달하면 리소스 생성 시점에 설정됨 (isLocked 이전)."""
    up = _result(_post_multipart(base, "/api/v1/resources/temp_upload", filename, content, min(timeout, 120)))
    temp_file_id = up.get("temp_file_id")
    if not temp_file_id:
        raise RuntimeError(f"temp_upload 응답에 temp_file_id 없음: {up}")
    parent = root if root.startswith("viking://") else f"viking://{root}"
    body = {
        "parent": parent,
        "wait": wait,
        "timeout": timeout,
        "temp_file_id": temp_file_id,
        "source_name": filename,
        "processing_mode": processing_mode,
        "args": args,
        "tags": tags,
        "tag_mode": tag_mode if tags else None,
    }
    body = {k: v for k, v in body.items() if v is not None}  # SDK _compact_request_body와 같은 생략 규칙
    return _result(_post_json(base, "/api/v1/resources", body, timeout + 30))


def _derive_source_system(source_uri):
    """s3://<bucket>/<s3_key> → s3_key prefix로 출처 시스템 판별(SFDC|CRMS|LAS). file:// 이면 None."""
    if not source_uri or not source_uri.startswith("s3://"):
        return None
    key = source_uri.split("/", 3)[-1] if source_uri.count("/") >= 3 else ""
    if key.startswith(("SFDC-", "SFDC_")):
        return "SFDC"
    if key.startswith(("CRMS-", "CRMS_")):
        return "CRMS"
    if key.startswith(("las_", "LAS_")):
        return "LAS"
    return None


def _extract_s3_key(source_uri):
    """s3://<bucket>/<s3_key> → <s3_key>. file:// 이면 None."""
    if not source_uri or not source_uri.startswith("s3://"):
        return None
    return source_uri.split("/", 3)[-1] if source_uri.count("/") >= 3 else None


def set_tags(base, uri, tags, timeout=30):
    """OV 리소스에 k=v 태그 설정 — /api/v1/fs/attrs/set_tags (mode=replace)."""
    body = {"uri": uri, "tags": tags, "mode": "replace"}
    return _result(_post_json(base, "/api/v1/fs/attrs/set_tags", body, timeout))


def ingest(url, root, rep_dir, *, timeout=1800, processing_mode=None, args=None, log=print):
    """rep_dir(_rep)의 성공 문서 전부 → OV. 이미 있는 문서(list_docs 이름 대조)·본문 없는 문서는 skip.
    반환: {문서명: {"status": "ok"|"skip"|"fail", ...}}."""
    base = url.rstrip("/")
    rep_dir = Path(rep_dir)
    idx = json.loads((rep_dir / "index.json").read_text(encoding="utf-8"))["docs"]
    have = {_key(n) for n in list_docs(base, root)}
    out = {}
    for r in idx:
        name = r.get("doc")
        if not name or not r.get("engine"):
            continue  # 실패 문서(엔진 없음) — contract.check_parse과 같은 필터
        if _key(name) in have:
            out[name] = {"status": "skip", "reason": "OV에 이미 있음"}
            continue
        f = rep_dir / f"{name}.json"
        if not f.exists():
            out[name] = {"status": "fail", "reason": "대표 결과 파일 없음"}
            log(f"FAIL     0.0s  {name}  대표 결과 파일 없음")
            continue
        _rep_raw = json.loads(f.read_text(encoding="utf-8"))
        md = render_md(_rep_raw)
        if not md.strip():
            out[name] = {"status": "skip", "reason": "본문 없음"}
            continue
        _src_uri = ((_rep_raw.get("rep") or {}).get("source") or {}).get("uri", "")
        _src_sys = _derive_source_system(_src_uri)
        _s3_key = _extract_s3_key(_src_uri)
        _edw = FILE_META.get(_s3_key, {}) if _s3_key else {}
        _bd = BUNDLE_DOCS.get(name, {}) if BUNDLE_DOCS else {}
        t0 = time.perf_counter()
        try:
            _tags = []
            if _src_sys:
                _tags.append(f"source_system={_src_sys}")
            if _s3_key:
                _tags.append(f"s3_key={_s3_key}")
            for _k in ("content_version_id", "sf_acc_name", "sf_op_id", "sf_op_name", "project_code__c", "contract_id", "contract_date"):
                _tags.append(f"{_k}={_edw.get(_k) or ''}")
            for _k in ("prod_name", "division", "service_type"):
                _val = _bd.get(_k) or _edw.get(_k) or ""
                if _val and _val != "-":
                    _tags.append(f"{_k}={_val}")
            res = add_resource(base, root, name, md, wait=False, timeout=timeout, processing_mode=processing_mode, args=args, tags=_tags)
            _res_uri = res.get("root_uri") or res.get("uri") or f"{root.rstrip('/')}/{name}"
            try:
                set_tags(base, _res_uri, _tags)
            except Exception:
                pass
            out[name] = {"status": "ok", "elapsed_s": round(time.perf_counter() - t0, 1), "result": res, "tags": _tags}
            log(f"ok   {time.perf_counter() - t0:7.1f}s  {name}  tags={len(_tags)}", flush=True)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as ex:
            reason = f"{type(ex).__name__}: {str(ex)[:200]}"
            out[name] = {"status": "fail", "reason": reason}
            log(f"FAIL {time.perf_counter() - t0:7.1f}s  {name}  {reason}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=C.cfg().connections.openviking.url)
    ap.add_argument("--root", default=pc.cfg().connections.openviking.root)
    ap.add_argument("--rep-dir", default=str(APP_ROOT / "output" / "parse" / "_rep"))
    ap.add_argument("--out", default=str(APP_ROOT / "output" / "ov_ingest"))
    ap.add_argument("--timeout", type=float, default=float(pc.cfg().connections.openviking.ingest_timeout))
    ap.add_argument("--file-meta", default=pc.cfg().paths.file_meta_path, help="EDW 파일 메타 JSONL (s3_key → 메타)")
    a = ap.parse_args()
    global FILE_META
    FILE_META = _load_file_meta(a.file_meta)
    global BUNDLE_DOCS
    BUNDLE_DOCS = _load_bundle_docs(a.rep_dir)

    from common.store import services

    if not services.ov_enabled("ingest"):
        print("(OpenViking 적재 꺼짐 — OV_FEATURES에 ingest 없음)", flush=True)
        return
    if not a.url or not a.root:
        print("[ov_ingest] OV_URL·OV_ROOT 필요", flush=True)
        raise SystemExit(2)

    mode = pc.cfg().connections.openviking.processing_mode or None
    if mode and mode not in PROCESSING_MODES:
        raise SystemExit(f"[ov_ingest] OV_PROCESSING_MODE 모름: {mode!r} (허용: {sorted(PROCESSING_MODES)})")
    pc.checked("OV_ARGS_JSON")  # 형식 틀린 JSON은 옛 json.loads처럼 여기서 실패(S7c)
    args = pc.cfg().connections.openviking.args_json  # 객체는 이미 푼 사전·목록(없음·빈 값 = None)

    result = ingest(a.url, a.root, a.rep_dir, timeout=a.timeout, processing_mode=mode, args=args)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for v in result.values() if v["status"] == "ok")
    skip = sum(1 for v in result.values() if v["status"] == "skip")
    fail = sum(1 for v in result.values() if v["status"] == "fail")
    print(f"[ov_ingest] 완료 — 올림 {ok} · 건너뜀 {skip} · 실패 {fail} → {out_dir / 'result.json'}", flush=True)
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("ov_ingest"):
        main()
