"""VLM 호출 한 길: 엔진 qwen_vlm·쪽 VLM 후보정(vlm_page)·pptx 슬라이드·그림 VLM(figures)·중첩 그림(nested)이
모두 `ask()` 하나로 부른다 — llm.complete('vlm')(내부망 가드·예산 장부·모델 다운 감지·`common.models.vlm.extra_body`·재시도
`models.vlm.retry`·호출 1건 제한 시간 `models.vlm.timeout`) + 전역 동시 수 게이트(`models.vlm.max_concurrency` — 한 프로세스 안의
모든 VLM 호출 합). 렌더 해상도는 `extract.page_render_dpi` 하나(`dpi()`).
쪽 옮기기(`transcribe` → `vlm_page`)는 엔진과 후보정이 같은 지시문·렌더·캐시 열쇠를 써서, 한쪽이 옮긴 쪽은 다른 쪽이 다시 부르지 않는다.
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

from common.ai import llm as A  # 모델 호출
from common.ai.agent_prompts import load as _load_prompt
from common.config.settings import cfg as ccfg
from pipeline import config as pc
from pipeline.shared.raw_cache import prompt_id, raw_root, raw_vlm_path  # raw_root: PARSE_RAW_ROOT(이중 raw/ 방지 포함)

_LOCK = threading.Lock()
_SEM: dict = {}


def _sem():
    v = ccfg().models.vlm.max_concurrency  # 잠금 밖에서 읽음(객체를 다시 만들 때 다른 VLM 쓰레드가 기다리지 않게) · 비움·auto = 8
    n = max(1, int(v if v is not None else 8))
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

P_PAGE = _load_prompt("page_transcribe", "page")  # 쪽 옮기기 지시문
PID_PAGE = prompt_id("page", "v1", P_PAGE)  # 프로토타입과 같은 글자 → 같은 id(기존 VLM 캐시 재사용)
MAX_SIDE = 2000  # _png() 긴 변 상한 — 결정적 열쇠에 들어감(바뀌면 새 열쇠)
PAGE_SLOW, PAGE_MIN_CONC = (
    60.0,
    2,
)  # 쪽 옮기기 적응형 병렬 — 가장 느린 호출이 PAGE_SLOW초를 넘으면 다음 묶음 병렬 수를 절반(최소 PAGE_MIN_CONC)
EMPTY = "빈 응답"  # vlm_page가 빈 답에 남기는 오류 글자(엔진은 빈 쪽으로 받음 — 실패 아님)


def dpi():
    """쪽·그림 렌더 해상도(DPI) — `extract.page_render_dpi` 하나(엔진·쪽 VLM·pptx·그림·prepare 공용, 기본 150). 결정적 열쇠에 들어감."""
    return int(pc.cfg().extract.ocr.dpi)


def page_max():
    """문서당 VLM으로 옮길 쪽 수 상한 `transform.vlm.vlm_max_pages_per_doc` — None = 전부, 0 = 끔, N = 앞 N쪽(엔진 qwen_vlm·쪽 VLM 공통)."""
    pc.checked("VLM_PAGE_MAX")  # 형식이 틀리면 여기서 실패(기본값이 '제한 없음'이라 조용히 넘기지 않음)
    v = pc.cfg().transform.vlm.page_max
    return None if v is None else int(v)


def ask(prompt, png_bytes, *, agent, max_tokens=None):
    """VLM 호출 1건 → (응답 글자, usage). 전역 게이트 안에서 llm.complete('vlm') — 위 모듈 설명의 공통 규칙. ModelUnavailable은 그대로 던짐."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png_bytes).decode()}},
    ]
    with slot():
        return A.complete(
            "vlm",
            [{"role": "user", "content": content}],
            temperature=0,
            max_tokens=max_tokens,
            timeout=float(ccfg().models.vlm.timeout),
            agent=agent,
        )


def sha(b):
    return hashlib.sha256(b).hexdigest()


def page_count(p):
    """쪽 수 — PDF는 쪽 수, 그 밖(이미지 파일)은 1."""
    p = Path(p)
    if p.suffix.lower() != ".pdf":
        return 1
    import fitz

    with fitz.open(p) as d:
        return len(d)


def render(p, idxs):
    """쪽 번호(1부터) 목록 → 쪽 이미지 PNG bytes 목록 — PDF는 dpi() 렌더, 그 밖(이미지 파일)은 원본 파일 그대로."""
    p = Path(p)
    if p.suffix.lower() != ".pdf":
        return [p.read_bytes() for _ in idxs]
    import fitz

    with fitz.open(p) as d:
        return [d[i - 1].get_pixmap(dpi=dpi()).tobytes("png") for i in idxs]


def rotation_info(doc_path):
    """`<doc_path 폴더>/rotation.csv`에서 이 문서의 {쪽 번호: {angle, orig_sha256}} — filter_and_rotate가 남김. 없으면 빈 묶음(아래서 대체 경로)."""
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


def _png(img, max_side=MAX_SIDE):
    from PIL import Image

    im = Image.open(io.BytesIO(img))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), f"{im.width}x{im.height}"


def _log_failed_page_vlm(model, ms, reason):
    """실패(취소·타임아웃·빈 응답)한 페이지 VLM 호출의 대기 시간을 raw/vlm/<model>/_failures.jsonl에 append.
    성공 provenance는 원래 캐시 파일로 남지만 실패는 안 남아 집계에서 빠졌었다 — 이제 실패 ms도 집계 가능."""
    try:
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
    실패·빈 답은 저장 안 함. 출력 상한은 두지 않는다(max_tokens 없음) — 생각(추론) 끄기는 모든 VLM 호출 공통 `common.models.vlm.extra_body`."""
    base, model = ccfg().models.vlm.base_url, ccfg().models.vlm.model
    model_dir = _model_dir(model)
    render_sha = sha(img_bytes)
    legacy = raw_vlm_path(raw_root(), model_dir, "page", "v1", P_PAGE, render_sha)
    dpath = None
    if det and det.get("source_sha256"):
        k16 = det_key(
            det["source_sha256"], det["page"], dpi() if det.get("is_pdf") else None, MAX_SIDE, det.get("rotation_deg") or 0, model, PID_PAGE
        )
        dpath = det_path(raw_root(), model_dir, "page", "v1", P_PAGE, k16)
        if dpath.exists():
            rec = _read(dpath)
            if rec:
                return rec["text"], {**rec["provenance"], "cached": True, "via": "det"}
    rec = _read(legacy) if legacy.exists() else None  # 읽기 대체 경로 — 프로토타입(또는 예전 운영) 캐시가 맞으면 그대로 쓰고 승격
    if rec:
        if dpath is not None:
            _write(dpath, rec)  # 결정적 열쇠로 복사 — 다음부터 렌더 sha 안 봐도 됨
        return rec["text"], {**rec["provenance"], "cached": True, "via": "legacy_image_sha"}
    if not (base and model):
        return "", {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 쪽 옮기기 없이 OCR만", "cached": False}
    data, px = _png(img_bytes)
    t0 = time.perf_counter()
    try:
        text, u = ask(P_PAGE, data, agent="page_transcribe")
    except A.ModelUnavailable as ex:
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"unavailable: {str(ex)[:120]}")
        return "", {"error": str(ex)[:200], "ms": _ms, "cached": False}
    except Exception as ex:  # 취소·타임아웃 등 기타 예외도 시간 기록
        _ms = round((time.perf_counter() - t0) * 1000)
        _log_failed_page_vlm(model, _ms, f"{type(ex).__name__}: {str(ex)[:120]}")
        raise
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        _log_failed_page_vlm(model, ms, EMPTY)
        return "", {"error": EMPTY, "ms": ms, "cached": False}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
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
    _write(dest, rec)
    return text, prov


def _read(path):
    """캐시 파일 → 기록 사전, 못 읽으면(깨진 JSON·권한) None = 캐시 없음으로(엔진·후보정·parse MCP가 같은 파일을 씀)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, rec):
    """캐시 쓰기 — 임시 파일 뒤 os.replace(읽는 쪽이 반쯤 쓴 파일을 보지 않게). 못 쓰면(디스크·권한) 건너뜀 — VLM 답은 이미 받았다."""
    import os

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as ex:
        print(f"[vlm] 캐시 저장 실패(건너뜀): {type(ex).__name__}", flush=True)


def transcribe(path, idxs):
    """쪽 번호(1부터) 목록 → [(쪽, 글, provenance)](쪽 순서) — 엔진 qwen_vlm과 쪽 VLM 후보정(page_text_pages)이 함께 쓴다.
    결정적 열쇠(det)는 rotation.csv의 orig_sha256·angle로(없으면 렌더 바이트 sha). 병렬 = `models.vlm.concurrency`(문서 하나 안),
    묶음마다 그 쪽만 렌더(메모리에는 동시 수만큼의 쪽 이미지만). 느린 응답이면 병렬 수를 줄이고 빨라지면 되돌린다(GPU 부하 완화)."""
    from concurrent.futures import ThreadPoolExecutor
    from itertools import islice

    from common.core import span as SP  # 풀 스레드에 run/span ID를 실음

    p = Path(path)
    idxs = sorted(idxs)
    rot = rotation_info(p)
    is_pdf = p.suffix.lower() == ".pdf"

    def _one(i, img):
        info = rot.get(i) or {}
        det = (
            {"source_sha256": info.get("orig_sha256"), "page": i, "rotation_deg": info.get("angle") or 0, "is_pdf": is_pdf}
            if info.get("orig_sha256")
            else None
        )
        text, prov = vlm_page(img, det)
        return (i, text, prov)

    _c = ccfg().models.vlm.concurrency
    n_max = max(1, int(_c if _c is not None else 4))
    n, it, out = min(n_max, max(1, len(idxs))), iter(idxs), []
    while batch := list(islice(it, n)):
        with ThreadPoolExecutor(max_workers=len(batch)) as ex:
            got = list(ex.map(SP.carry(_one), batch, render(p, batch)))
        out.extend(got)
        slowest = max((float(pv.get("ms") or 0) for _, _, pv in got if isinstance(pv, dict)), default=0.0)
        if slowest > PAGE_SLOW * 1000 and n > PAGE_MIN_CONC:
            n = max(PAGE_MIN_CONC, n // 2)
            print(f"[vlm] VLM 응답 {slowest / 1000:.0f}초 > {PAGE_SLOW:.0f}초 → 병렬 수 {n * 2}→{n} 감소", flush=True)
        elif slowest < PAGE_SLOW * 500 and n < n_max:
            n = min(n_max, n * 2)
    return out
