"""파싱 실행 공용(0.2.0에 옛 pipeline/shared/artifacts.py·progress.py를 합침, pl-46): P0 원본 캐시 경로·지시문 id·엔진 버전·중간 캐시 정리 ·
환경 실패 단서(is_env_error)·문서 → 형식 키(doc_types)."""

import importlib.metadata
import json
import os
from pathlib import Path

from common.core.artifacts import sha8
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)


# ---- (옛 pipeline/shared/artifacts.py)
def prompt_id(name, version, text):
    """지시문 id = name-version-sha8(지시문 글자) — 코드 이름이 같아도 버전·글자가 바뀌면 다른 id."""
    return f"{name}-{version}-{sha8(text)}"


def raw_engine_path(store, engine, version, content_sha):
    """P0 엔진 결과 경로 — raw/<engine>@<version>/<sha12>.json (src/tools/qa/eval_hard_parse.py RAW 패턴과 동일)."""
    return Path(store) / "raw" / f"{engine}@{version}" / f"{content_sha[:12]}.json"


def raw_vlm_path(store, model, name, version, prompt_text, image_sha):
    """P0 VLM 쪽 결과 경로 — raw/vlm/<model>/<prompt_id>/<image_sha12>.json."""
    return Path(store) / "raw" / "vlm" / model / prompt_id(name, version, prompt_text) / f"{image_sha[:12]}.json"


# engine → importlib.metadata 패키지 이름("|"는 여러 후보) — src/tools/qa/eval_hard_parse.py의 PKG를 단일 인터프리터용으로
# 옮긴 사본(그쪽은 kreuzberg 등을 별도 venv(ALT_PY)에서 확인 — 그 교차 venv 조회는 이 계약 함수 범위 밖, 호출 쪽이 알아서).
ENGINE_PKG = {
    "html_stdlib": None,
    "pymupdf": "pymupdf",
    "kreuzberg": "kreuzberg",
    "rapidocr_ko": "rapidocr|rapidocr_onnxruntime|rapidocr-onnxruntime",
    "pptx": "python-pptx",
    "office": None,
    "mhtml": None,
}


def engine_version(engine):
    """엔진 이름 → 설치된 패키지 버전(importlib.metadata). 매핑에 없으면 엔진 이름을 패키지 이름으로 시도. 못 찾으면 "unknown"."""
    pkg = ENGINE_PKG.get(engine, engine)
    if not pkg:
        return "stdlib"
    for name in pkg.split("|"):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown"


# RV3(10-09 리뷰 후속, engine-qa BLOCK 반영) — 순수 캐시만(재생성 경로가 있는 것만). server-runbook.md 'C7. 파싱 결과
# 원본·그림 보관 위치' 표의 보관 결정을 그대로 따른다 — **raw/**(VLM 원본 응답 raw/vlm·엔진별 원본 raw/<엔진>@<버전>,
# C7: "남음")와 **_images**(그림 조각 PNG + index.jsonl, C7: "남음" — get_image가 읽는
# 정본 색인이라 파일만 지우면 참조가 깨짐)는 서버가 원본을 즉시 지워 재생성 경로가 없으므로 **정리 대상이 아니다**(안 지움).
# 정리 대상은 재판독 중간 캐시 3종뿐 — 전부 "없으면 다시 OCR·VLM 호출만 더 들 뿐"이라 영구 보관 결정이 없는 것들:
#   _reread_p3/_vlm_cache(옛 P3 재판독 캐시 — pl-34에 기능을 지웠지만 서버에 남은 폴더를 정리하려고 둠) · _agent/_vlm_cache(판단 세션 재판독 VLM 캐시) · signals(page_signals 쪽 신호).
# 엔진 원문 P0(output/parse/<엔진>/<문서>.json, p0_key)·대표 결과(_rep)·판단 세션 결정 기록(_agent/decisions)도 당연히 안 지움.
PURGE_CACHE_DIRS = ("_reread_p3/_vlm_cache", "_agent/_vlm_cache", "signals")


def _contained_dirs(root):
    """root(이미 resolve됨) 밑에 안전하게 들어갈 수 있는 디렉터리만 — 각 하위 디렉터리를 resolve()해서 여전히
    root 밑인지 다시 확인하고서야 스택에 넣는다. os.walk(followlinks=False)만으론 부족하다(engine-qa BLOCK② 재검토
    — os.walk은 심볼릭 링크는 걸러도 **Windows junction/mount point는 걸러내지 못함**, `os.path.islink()`가
    junction엔 False를 줘서 followlinks=False가 무력화되는 걸 실측으로 확인). 깊이 섞인 순서로 반환(정렬은 호출자)."""
    found = [root]
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=True):
                    rp = Path(e.path).resolve()
                    if (rp == root or root in rp.parents) and rp not in found:  # root 밑만(심링크·junction) · 자기 참조 링크 무한 순회 방지
                        found.append(rp)
                        stack.append(rp)
            except OSError:
                pass
    return found


def _iter_files(root):
    """root(resolve됨) 아래 파일만 — _contained_dirs로 확인된 디렉터리에서만 파일을 모은다. 파일 자체가 심링크면
    건너뜀(그 심링크가 가리키는 밖의 파일을 안 지움)."""
    for d in _contained_dirs(root):
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False):
                    yield Path(e.path)
            except OSError:
                pass


def purge_caches(parse_dir, max_gb=None, dirs=PURGE_CACHE_DIRS, log=print):
    """parse_dir(보통 output/parse) 아래 PURGE_CACHE_DIRS(재판독 중간 캐시 3종 — raw/·_images는 server-runbook.md C7
    표의 '원본 삭제 뒤에도 남음' 결정 때문에 대상 아님) 합계 용량이 PARSE_CACHE_MAX_GB(env, 기본 **5GB**·0=끔)를 넘으면
    가장 오래 안 쓴 파일(mtime)부터 지워 상한 밑으로 — 배치 시작 1회만 부른다(파싱 중간에는 안 지움, 그 배치가 막 쓴
    캐시까지 지우면 같은 배치 안에서 재계산이 생긴다). 지우는 파일은 parse_dir 아래로 resolve 확인(경로 탈출 방지) +
    심볼릭 링크·Windows junction 디렉터리는 안 들어감(_contained_dirs·_iter_files) — dirs에 없는 폴더(raw·_images·
    엔진 원문·_rep·_agent/decisions)는 절대 건드리지 않는다.
    ponytail: 폴더별 상한 대신 세 폴더 합계 하나(단순) — 폴더별로 따로 상한을 걸 필요가 생기면 dirs를 쪼개 각각 호출."""
    max_gb = float(pc.cfg().extract.cache.parse_cache_max_gb) if max_gb is None else float(max_gb)
    if not max_gb:
        return {"skipped": "PARSE_CACHE_MAX_GB=0"}
    root = Path(parse_dir).resolve()
    roots = []
    for d in dirs:
        p = (root / d).resolve()
        if root == p or root not in p.parents:  # 경로 탈출 방지(dirs는 상수라 정상적으로는 안 일어남)
            continue
        if p.exists() and not p.is_symlink():  # 캐시 루트 자체가 심링크면 건너뜀(루트 바꿔치기 방지)
            roots.append(p)
    entries = []
    for r in roots:
        for f in _iter_files(r):
            try:
                entries.append((f.stat().st_mtime, f.stat().st_size, f))
            except OSError:
                pass
    total_bytes = sum(sz for _, sz, _ in entries)
    total_gb = total_bytes / (1024**3)
    if total_gb <= max_gb:
        return {"total_gb": round(total_gb, 3), "removed": 0, "removed_gb": 0.0}
    entries.sort(key=lambda e: e[0])  # 오래된 mtime부터
    removed, removed_bytes = 0, 0
    for _, size, f in entries:
        if (total_bytes - removed_bytes) / (1024**3) <= max_gb:
            break
        try:
            f.unlink()
            removed += 1
            removed_bytes += size
        except OSError:
            pass
    for r in roots:  # 비게 된 폴더 정리(_contained_dirs — 깊은 것부터, 심링크·junction 디렉터리는 안 들어가 그 안은 안 봄)
        for d in sorted(_contained_dirs(r), key=lambda p: -len(str(p))):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
        # r 자신은 위에서 이미 지웠을 수 있음(흔한 경우 — 내부 폴더 없음) → 그 위 조상(dirs 항목이 "a/b"처럼
        # 중간 폴더일 때, 예: _reread_p3/_vlm_cache를 지운 뒤 비어버린 _reread_p3)도 비었으면 마저 지움
        d = r.parent if not r.exists() else r
        while d != root:
            try:
                if not d.exists() or d.is_symlink() or any(d.iterdir()):
                    break
                d.rmdir()
            except OSError:
                break
            d = d.parent
    log(f"[cache-purge] {total_gb:.2f}GB > 상한 {max_gb:g}GB — 오래된 캐시 파일 {removed}개({removed_bytes / 1024**3:.2f}GB) 지움 ({root})")
    return {"total_gb": round(total_gb, 3), "removed": removed, "removed_gb": round(removed_bytes / 1024**3, 3)}


# ---- (옛 pipeline/shared/progress.py)
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
