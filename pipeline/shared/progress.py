#!/usr/bin/env python3
"""파싱 공용 도우미 — 환경(미설치·미설정) 실패 단서(is_env_error)와 문서 → 형식 키(doc_types, _types.json 캐시).
진행 현황 파일 output/parse/PROGRESS.md 쓰기(write_progress)는 0.2.0에 지움(pl-46 — 읽는 곳 없음, 콘솔 큐 줄로 충분).
"""

import json
from pathlib import Path

# 환경(미설치·미설정) 실패 단서 — 한 곳(run_all RB3② env_failed·parse_qa·실행판 공용). SI45: 예전 "not found"·"NotFoundError"는
# 손상 PDF의 'PdfReadError: EOF marker not found'까지 env로 잡아 그 엔진을 실행 전체에서 건너뛰게 했음 → 구체적인 표현만.
ENV_ERR = (
    "미설정",
    "미설치",
    "ModuleNotFoundError",
    "No module named",
    "command not found",
    "FileNotFoundError",
    "TesseractNotFoundError",
    "NotInstalledError",
    "not installed",
    "SpawnError",
    "initialization fai",
)


def is_env_error(err):
    return bool(err) and any(k in err for k in ENV_ERR)


def doc_types(docs, out):
    """문서 → 타입(.pdf는 .pdf_text / .pdf_image — 쪽당 글자 레이어 20자 기준). 판정은 <out>/_types.json에 캐시(크기·수정 시각)."""
    from pipeline.transform.represent.parse_qa import pdf_kind

    cache_f = Path(out) / "_types.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    res, dirty = {}, False
    for d in docs:
        if d.suffix.lower() != ".pdf":
            res[d.name] = d.suffix.lower()
            continue
        st = d.stat()
        key = f"{d.name}|{st.st_size}|{int(st.st_mtime)}"
        if key not in cache:
            cache[key], dirty = "." + pdf_kind(d)[0], True
        res[d.name] = cache[key]
    if dirty:
        Path(out).mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return res


def _fill_chars(runs, out):
    """글자 수 없는 옛 기록(성공)은 출력 JSON에서 한 번 읽어 <out>/_chars.json에 캐시."""
    cache_f = Path(out) / "_chars.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    dirty = False
    for (doc, eng), r in runs.items():
        if "chars" in r or r.get("error"):
            continue
        k = f"{eng}|{doc}"
        if k not in cache:
            try:
                cache[k] = len((json.loads((Path(out) / eng / (doc + ".json")).read_text(encoding="utf-8")).get("text") or "").strip())
            except (OSError, ValueError):
                cache[k] = 0
            dirty = True
        r["chars"] = cache[k]
    if dirty:
        cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
