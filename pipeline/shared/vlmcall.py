"""전역 VLM in-flight 게이트 — 2026-10-22 사용자 지정(모든 VLM 호출의 동시 합 = VLM_GLOBAL_CONCURRENCY, 기본 12).

쪽 VLM(vlm_page — PDF 쪽·pptx 슬라이드 전사), 그림 VLM(vlm_fig·figoverlay), 엔진 qwen_vlm(_chat)이
**같은 서버 예산**을 공유한다 — 문서 병렬(PARSE_DOC_PARALLEL)로 문서 2개가 동시에 figures 풀에 몰려도,
또는 vlm_page 도중 다른 문서의 그림 VLM이 겹쳐도, 실제 서버에 날아가는 요청 수 합이 상한을 못 넘게 한다.
게이트는 호출 단위(1건 = 1 slot) — 풀의 워커 수(FIGURES_VLM_PARALLEL·VLM_PAGE_CONCURRENCY 등)는 그대로
각자의 상한으로 남고, 이 게이트가 그 위의 전역 합 상한이 된다.
"""

import base64
import hashlib
import io
import json
import re
import threading
import time
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

from common.ai import llm as A  # 모델 호출(0.2.0 — 옛 common.ai.adk, pl-46)
from common.ai.agent_prompts import load as _load_prompt
from common.config.settings import cfg as ccfg  # common 칸 설정 객체(S7c)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.parse_run import prompt_id, raw_vlm_path
from pipeline.shared.postprocess import raw_root  # PARSE_RAW_ROOT(이중 raw/ 방지 포함, post/__init__.py)

_LOCK = threading.Lock()
_SEM: dict = {}


def _sem():
    v = (
        pc.cfg().transform.vlm.global_concurrency
    )  # S7c — 설정 객체(옛 int(get(X) or "12")) — 잠금 밖에서 읽음(객체를 다시 만들 때 다른 VLM 쓰레드가 기다리지 않게)
    n = max(1, int(v if v is not None else 12))
    with _LOCK:
        if n not in _SEM:
            _SEM[n] = threading.BoundedSemaphore(n)
        return _SEM[n]


@contextmanager
def slot():
    """VLM 호출 1건 자리 — 획득 실패 없이 차례를 기다린다(합이 상한을 넘는 문서·쓰레드는 여기서 대기)."""
    s = _sem()
    s.acquire()
    try:
        yield
    finally:
        s.release()


NOW = time.strftime("%Y-%m-%dT%H:%M:%S")

P_PAGE = _load_prompt("page_transcribe", "page")  # AD33 — 글자는 dev/agents/page_transcribe/prompts/page.md
PID_PAGE = prompt_id("page", "v1", P_PAGE)  # 프로토타입과 같은 글자 → 같은 id(기존 VLM 캐시 재사용)
DPI, MAX_SIDE = 150, 2000  # pages_of()·_png() 렌더 매개변수 — 결정적 열쇠에 들어감(바뀌면 새 열쇠)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pages_of(p):
    """쪽 이미지 bytes 목록 — PDF는 150dpi 렌더(프로토타입과 같은 dpi라 쪽 이미지 sha가 맞음), 그 외는 원본 파일 그대로."""
    p = Path(p)
    if p.suffix.lower() == ".pdf":
        import fitz

        return [pg.get_pixmap(dpi=DPI).tobytes("png") for pg in fitz.open(p)]
    return [p.read_bytes()]


def rotation_info(doc_path):
    """`<doc_path 폴더>/rotation.csv`에서 이 문서의 {쪽 번호: {angle, orig_sha256}} — prepare.py가 남김. 없으면 빈 묶음(아래서 대체 경로)."""
    doc_path = Path(doc_path)
    f = doc_path.parent / "rotation.csv"
    out = {}
    if not f.exists():
        return out
    import csv

    with f.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("file") == doc_path.name:
                try:
                    out[int(row["page"])] = {"angle": int(row.get("angle") or 0), "orig_sha256": row.get("orig_sha256") or None}
                except (TypeError, ValueError):
                    pass
    return out


def det_key(source_sha256, page_idx, dpi, max_side, rotation_deg, model, prompt_id_):
    """결정적 P0 열쇠(16자) — 렌더 바이트가 아니라 원본·쪽·매개변수·모델로. 부분이 하나라도 바뀌면 다른 열쇠."""
    parts = {
        "source_sha256": source_sha256,
        "page": page_idx,
        "dpi": dpi,
        "max_side": max_side,
        "rotation_deg": rotation_deg,
        "model": model,
        "prompt_id": prompt_id_,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def det_path(store, model_dir, name, version, prompt_text, key16):
    """raw_vlm_path와 같은 폴더(raw/vlm/<모델>/<prompt_id>/)에 파일 이름만 'det-<열쇠>'로 — 렌더 sha(12자 hex)와 안 겹침."""
    return Path(store) / "raw" / "vlm" / model_dir / prompt_id(name, version, prompt_text) / f"det-{key16}.json"


def _model_dir(model):
    """프로토타입(eval_hard_parse.vlm_raw)과 같은 폴더 이름 정리 규칙 — '/'가 든 모델 이름도 기존 캐시와 같은 폴더로."""
    return re.sub(r"[^\w.-]+", "_", model or "unset")


def _png(img, max_side=2000):
    from PIL import Image

    im = Image.open(io.BytesIO(img))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), f"{im.width}x{im.height}"


def _log_failed_page_vlm(model, ms, reason):
    """2026-10-22 — 실패(취소·타임아웃·빈 응답)한 페이지 VLM 호출의 대기 시간을 raw/vlm/<model>/_failures.jsonl에 append.
    성공 provenance는 원래 캐시 파일로 남지만 실패는 안 남아 집계에서 빠졌었다 — 이제 실패 ms도 집계 가능."""
    try:
        from pipeline.shared.postprocess.rawstore import raw_vlm_path  # 있으면 사용, 없으면 아래 폴백
    except ImportError:
        raw_vlm_path = None
    try:
        _b = ccfg().models.vlm.base_url  # S7c — 설정 객체(옛 get(X, "") — 캐시 열쇠 글자 그대로)
        base = raw_vlm_path(_b if _b is not None else "", model, "page", "fail") if raw_vlm_path else None
        if base is None:
            base = _rawdir_default(model)
        base.parent.mkdir(parents=True, exist_ok=True)
        with (base.parent / "_failures.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ms": ms, "error": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rawdir_default(model):
    """raw_vlm_path가 없을 때 — PIPE_OUT_ROOT(없으면 런타임 루트 output/ — 이미지 안 /app/output)/parse/raw/vlm/<model>/page/ 기본 경로."""
    from pathlib import Path

    from common.core.paths import APP_ROOT

    m = (model or "unknown").replace("/", "_")
    from pipeline import config as pc

    return Path(pc.cfg().paths.out_root or APP_ROOT / "output") / "parse" / "raw" / "vlm" / m / "page" / "fail"


def _host(url):
    return urllib.parse.urlparse(url).hostname or url


def vlm_page(img_bytes, det=None):
    """쪽 1장 → (마크다운 글자, provenance). P0 — det(= {"source_sha256","page","rotation_deg"})가 있으면 결정적 열쇠로 찾는다(렌더
    바이트가 달라도 재사용) · 없으면(det None — 원본 sha를 못 구함) 렌더 바이트 sha로(예전 동작, 재준비하면 캐시가 깨질 수 있음).
    det가 있어도 결정적 캐시가 비었으면 렌더 sha(프로토타입 캐시) 경로를 읽기만 시도 — 맞으면 결정적 열쇠로도 복사해 다음부터 안 읽게.
    실패·빈 답은 저장 안 함. 프로토타입은 쪽 옮기기에서 추론을 끄지 않는다(그림 JSON과 달리 출력 상한을 넉넉히 써도 됨 — 실측 캐시에
    reasoning 끈 흔적 없음) — 여기도 같게 둔다."""
    base, model = ccfg().models.vlm.base_url, ccfg().models.vlm.model  # S7c — 설정 객체
    model_dir = _model_dir(model)
    render_sha = sha(img_bytes)
    legacy = raw_vlm_path(raw_root(), model_dir, "page", "v1", P_PAGE, render_sha)
    dpath = None
    if det and det.get("source_sha256"):
        k16 = det_key(
            det["source_sha256"], det["page"], DPI if det.get("is_pdf") else None, MAX_SIDE, det.get("rotation_deg") or 0, model, PID_PAGE
        )
        dpath = det_path(raw_root(), model_dir, "page", "v1", P_PAGE, k16)
        if dpath.exists():
            rec = json.loads(dpath.read_text(encoding="utf-8"))
            return rec["text"], {**rec["provenance"], "cached": True, "via": "det"}
    if legacy.exists():  # 읽기 대체 경로 — 프로토타입(또는 예전 운영) 캐시가 맞으면 그대로 쓰고 승격
        rec = json.loads(legacy.read_text(encoding="utf-8"))
        if dpath is not None:
            dpath.parent.mkdir(parents=True, exist_ok=True)
            dpath.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")  # 결정적 열쇠로 복사 — 다음부터 렌더 sha 안 봐도 됨
        return rec["text"], {**rec["provenance"], "cached": True, "via": "legacy_image_sha"}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 쪽 옮기기 없이 OCR만", "cached": False}
    data, px = _png(img_bytes)
    _dl = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체(옛 float(get(X) or 360))
    deadline = float(_dl if _dl is not None else 360)
    t0 = time.perf_counter()
    try:
        from pipeline.transform.figures.vgate import (
            slot as _vgate_slot,
        )  # 전역 VLM in-flight 게이트(합 VLM_GLOBAL_CONCURRENCY — 2026-10-22)

        with _vgate_slot():
            text, u = A.complete(
                "vlm",
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": P_PAGE},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                        ],
                    }
                ],
                temperature=0,
                max_tokens=None,
                timeout=deadline,
                agent="page_transcribe",
            )
    except A.ModelUnavailable as ex:
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"unavailable: {str(ex)[:120]}")
        return "", {"error": str(ex)[:200], "ms": _ms, "cached": False}
    except Exception as ex:  # 2026-10-22 — 취소·타임아웃 등 기타 예외도 시간 기록
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"{type(ex).__name__}: {str(ex)[:120]}")
        raise
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        _log_failed_page_vlm(model, ms, "빈 응답")
        return "", {"error": "빈 읭", "ms": ms, "cached": False}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
    prov = {
        "model": model,
        "endpoint_host": _host(base),
        "prompt_id": PID_PAGE,
        "image_sha256": render_sha,
        "px": px,
        "params": {"temperature": 0, "max_side": MAX_SIDE},
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
        "created_at": NOW,
        "cached": False,
    }  # image_sha256 = 렌더 바이트 sha(추적용, 열쇠 아님)
    rec = {"text": text, "provenance": {k: v for k, v in prov.items() if k != "cached"}}
    # 결정적 열쇠가 있으면 그쪽에 저장(앞으로 재사용), 없으면 예전처럼 렌더 sha 경로에(대체 경로)
    dest = dpath if dpath is not None else legacy
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return text, prov
