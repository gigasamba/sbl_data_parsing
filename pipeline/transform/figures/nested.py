"""F7 — page_render(쪽 전체 그림) 안의 자식 그림(그래프·사진·도면) 찾기·자르기. 원본 설계:
git 이력 docs/plans/image-parsing-2026-10-01.md(c4874dd0^) §2-5("중첩 그림 찾기")·§3("중첩" 계약 — parent_image_id·depth·children·
page_render). 1차(이 구현의 전부) = VLM에 영역 bbox를 JSON(이미지 가로·세로 기준 0~1 비율, 해상도 무관)으로
요청하는 새 에이전트(nested_figure, figure_describe와 별도 prompt_id — 기존 VLM 캐시 전혀 안 건드림). 2차
후보(레이아웃 모델, PP-Structure류)는 새 패키지 의존이라 범위 밖(ponytail: VLM 전용, 레이아웃 모델은 실측
필요성이 생기면 별도 추가). VLM 미설정·오류·빈 응답·JSON 파싱 실패는 자식 없이 빈 목록(파싱은 계속 — figures.py가
부모 page_render 기록만 남긴다, LibreOffice처럼 "없으면 조용히 건너뜀"과 같은 관례).

VLM 호출 수: bbox 찾기(쪽마다 1회, P0 캐시)+자식마다 vlm_fig(기존 함수 재사용, 내용·값 추출) — 자식의 그래프 값
같은 구조화 내용을 뽑으려면 크롭마다 VLM이 한 번 더 필요해 호출 수는 늘어난다(F7 완료 기준이 요구하는 부분,
"VLM 호출 수 불변" 원칙의 명시된 예외)."""

import base64
import io
import json
import re
import time

from common.ai import adk as A
from common.ai.agent_prompts import load as _load_prompt
from common.config.settings import cfg as ccfg  # common 칸 설정 객체(S7c)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)
from pipeline.shared.parse_run import prompt_id, raw_vlm_path
from pipeline.shared.postprocess import raw_root  # PARSE_RAW_ROOT(이중 raw/ 방지, post/__init__.py)
from pipeline.transform.figures.vlm_page import _host, _model_dir, _png, sha  # 캐시 경로·PNG 축소 helper 재사용(중복 구현 금지)

P_BBOX = _load_prompt("nested_figure", "bbox")  # 글자는 prompts/nested_figure/prompt.md
PID_BBOX = prompt_id("bbox", "v1", P_BBOX)
MIN_AREA_RATIO = 0.05  # 설계 §2-5 — 쪽(또는 부모 그림) 면적의 5% 미만인 영역은 건너뜀
MAX_REGIONS = 4  # 1번의 bbox_regions() 호출 안에서 돌려주는 후보 상한(한 번의 VLM 응답을 믿는 범위)
MAX_DEPTH_DEFAULT = 2  # 설계 §2-5 — 중첩 깊이 상한(부모=0, 자식=1, 손자=2)
MAX_CHILDREN_TOTAL = 4  # 독립 검토 Minor(10-13) — 쪽 1장에서 나오는 자식(손자 포함) 총합 상한. MAX_REGIONS(4) ×
# depth 2를 그대로 두면 한 쪽에서 최대 20개까지 나와 VLM_FIGURES_MAX(기본 20) 전체를 자식이 차지해 문서의
# 다른(원래) 그림을 굶길 수 있다 — find_children()이 쪽 1장당 이 상한으로 너비 우선 탐색을 멈춘다.


def bbox_regions(img_bytes):
    """부모 그림(page_render 또는 그 자식) PNG bytes → ([{"bbox":[x0,y0,x1,y1](0~1 비율), "kind": str|None}], provenance).
    P0 캐시(모델·prompt_id·그림 sha가 같으면 재사용, 호출 0) — vlm_fig()와 같은 캐시 원칙. VLM 미설정/오류/빈 응답/
    JSON 파싱 실패/못 여는 이미지는 ([], {"error"|"skipped": ...})로 돌려주고 예외를 던지지 않는다(문서는 계속)."""
    from PIL import Image

    try:
        Image.open(io.BytesIO(img_bytes)).load()
    except Exception:  # 깨진/못 여는 이미지 1건이 문서를 막지 않게
        return [], {"skipped": "unconvertible"}
    base, model = ccfg().models.vlm.base_url, ccfg().models.vlm.model  # S7c — 설정 객체
    img_sha = sha(img_bytes)
    out = raw_vlm_path(raw_root(), _model_dir(model), "nested_bbox", "v1", P_BBOX, img_sha)
    if out.exists():
        rec = json.loads(out.read_text(encoding="utf-8"))
        return rec["regions"], {**rec["provenance"], "cached": True}
    if not (base and model):
        return [], {"error": "VLM_BASE_URL·VLM_MODEL 미설정 — 중첩 그림 찾기 생략(부모 기록만 남음)"}
    data, px = _png(img_bytes)
    extra = {"reasoning": {"enabled": False}} if "openrouter" in base else {"chat_template_kwargs": {"enable_thinking": False}}
    _dl = pc.cfg().transform.vlm.deadline  # S7c — 설정 객체(옛 float(get(X) or 360))
    deadline = float(_dl if _dl is not None else 360)
    t0 = time.perf_counter()
    try:
        text, u = A.complete(
            "vlm",
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": P_BBOX},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=500,
            extra=extra,
            timeout=deadline,
            agent="nested_figure",
        )
    except A.ModelUnavailable as ex:
        return [], {"error": str(ex)[:200], "ms": round((time.perf_counter() - t0) * 1000)}
    ms = round((time.perf_counter() - t0) * 1000)
    if not text.strip():
        return [], {"error": "빈 응답", "ms": ms}  # 실패·빈 답은 원본 층에 남기지 않음(다음 실행에서 다시)
    regions = _parse_regions(text)
    prov = {
        "model": model,
        "endpoint_host": _host(base),
        "prompt_id": PID_BBOX,
        "image_sha256": img_sha,
        "px": px,
        "ms": ms,
        "in": u.get("prompt_tokens"),
        "out": u.get("completion_tokens"),
        "cost": u.get("cost"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"regions": regions, "provenance": prov}, ensure_ascii=False), encoding="utf-8")
    return regions, prov


def _parse_regions(text):
    """VLM 응답 글자 → [{"bbox":[4개 숫자], "kind"}], 모양이 안 맞는 항목·전체 JSON 파싱 실패는 빈 목록(안전 기본값)."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for r in (data.get("regions") or [])[:MAX_REGIONS]:
        bbox = r.get("bbox") if isinstance(r, dict) else None
        if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            out.append({"bbox": [float(v) for v in bbox], "kind": r.get("kind")})
    return out


def child_crops(parent_png_bytes):
    """부모(page_render 또는 그 자식) PNG bytes → ([{"bbox_frac":[x0,y0,x1,y1](0~1, 부모 기준), "bytes": 자른 PNG,
    "kind": str|None}], provenance). 면적(비율) < MIN_AREA_RATIO는 건너뜀(설계 §2-5). 좌표를 '원본 쪽 좌표'로
    바꾸는 일은 호출부(figures.py) 몫 — 이 함수는 부모 바이트의 픽셀 크기만 알고 원본 쪽의 실제 단위(PDF pt·
    pptx EMU·PNG px)는 모른다(비율이라 단위 무관하게 그대로 곱하면 됨)."""
    regions, prov = bbox_regions(parent_png_bytes)
    if not regions:
        return [], prov
    from PIL import Image

    im = Image.open(io.BytesIO(parent_png_bytes))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    out = []
    for r in regions:
        x0, y0, x1, y1 = r["bbox"]
        # G4(10-13) — Qwen-VL 계열은 지시문이 0~1을 요구해도 0~1000 정규화 좌표를 돌려줌(실측: screenshot_nested.png
        # 1280×720에서 [204,400,865,647] = 흐름도 상자 x258~1120·y298~480과 /1000 환산이 일치, 픽셀로 보면 어긋남).
        # 1을 넘는 값이 있고 전부 0~1000이면 /1000으로 읽는다 — 그 밖(음수·1000 초과)은 여전히 신뢰 못 함.
        if any(v > 1.001 for v in (x0, y0, x1, y1)) and all(0 <= v <= 1000 for v in (x0, y0, x1, y1)):
            x0, y0, x1, y1 = x0 / 1000, y0 / 1000, x1 / 1000, y1 / 1000
        if not all(-0.001 <= v <= 1.001 for v in (x0, y0, x1, y1)):  # 0~1 비율이 아닌 값(모델 오류)은 신뢰 못 함 — 건너뜀
            continue
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) < MIN_AREA_RATIO:
            continue
        px0, py0, px1, py1 = round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)
        if px1 <= px0 or py1 <= py0:
            continue
        crop = im.crop((px0, py0, px1, py1))
        buf = io.BytesIO()
        crop.save(buf, "PNG")
        out.append({"bbox_frac": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)], "bytes": buf.getvalue(), "kind": r.get("kind")})
    return out, prov


def find_children(parent_bytes, max_depth=MAX_DEPTH_DEFAULT):
    """부모(page_render 등) 바이트 → [{"local_id": "c1"|"c1.c2"..., "parent_local": None|"c1"..., "depth": 1..max_depth,
    "bbox_frac": [x0,y0,x1,y1](그 depth의 직속 부모 기준 0~1), "bytes": 자른 PNG, "kind": str|None}, ...].
    local_id는 설계 §3의 ".c<순번>" 접미사 그대로(점으로 이으면 그대로 image_id 접미사가 된다) — 호출부
    (figures.py)가 실제 부모 image_id 앞에 이어붙인다. 너비 우선, depth마다 child_crops() 한 번씩(설계 §2-5
    "1~4를 반복"), 형제가 여럿이면 부모별로 번호를 따로 세 섞이지 않는다.
    독립 검토 Minor(10-13) — 쪽 1장에서 나오는 자식 총합이 MAX_CHILDREN_TOTAL(기본 4, 손자 포함)을 넘으면 그
    자리에서 멈춘다(MAX_REGIONS×depth 조합이 그대로면 쪽 1장에서 최대 20개까지 나와 VLM_FIGURES_MAX를 자식이
    혼자 다 쓸 수 있었음)."""
    out = []
    counters = {}  # parent_local(또는 None=최상위) → 지금까지 매긴 자식 수
    queue = [(None, 1, parent_bytes)]
    while queue:
        if len(out) >= MAX_CHILDREN_TOTAL:
            break
        parent_local, depth, data = queue.pop(0)
        if depth > max_depth:
            continue
        crops, _prov = child_crops(data)
        for c in crops:
            if len(out) >= MAX_CHILDREN_TOTAL:
                break
            counters[parent_local] = counters.get(parent_local, 0) + 1
            local_id = f"{parent_local}.c{counters[parent_local]}" if parent_local else f"c{counters[parent_local]}"
            out.append(
                {
                    "local_id": local_id,
                    "parent_local": parent_local,
                    "depth": depth,
                    "bbox_frac": c["bbox_frac"],
                    "bytes": c["bytes"],
                    "kind": c["kind"],
                }
            )
            if depth < max_depth:
                queue.append((local_id, depth + 1, c["bytes"]))
    return out
