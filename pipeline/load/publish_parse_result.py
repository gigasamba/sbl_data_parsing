#!/usr/bin/env python3
"""게시: 파싱이 끝난 문서의 대표 결과(.md)와 엔진별 원결과를 Object Storage에 올리고 EDW `AI.ParsingMeta`에 행을 쓴다.

규칙: 원본 파일은 올리지 않는다 · 겹침 키 = (source_system, 원본 전체 키) — 있으면 건너뜀, `--reparse` 목록만 새 날짜 폴더 ·
EDW는 INSERT만 · 게시 버킷이 원천 원본 버킷과 같으면 거부 · DRM·실패 문서는 EDW에 안 쓰고 `output/publish/excluded_<날짜>.md`에만.

사용: python -m pipeline.load.publish_parse_result [--out output] [--parse-date YYYY-MM-DD] [--reparse <키 목록 파일>] [--apply]
기본은 dry-run(표만 출력, 업로드·EDW 쓰기 0). 설정은 settings.yaml(게시 버킷·접두·표, EDW 쓰기 계정, Object Storage 접속 —
settings.sample.yaml `load.publish`·`required`). PC는 버킷 `file://<폴더>`·`RDB_SQLITE`로 로컬 대역을 쓴다.
DDL은 실행하지 않는다(표는 사람이 만듦). SQL은 식별자 화이트리스트·값 바인딩, 비밀값은 출력하지 않는다.

세부 규칙:
① 올릴 것 = **대표 결과(.md)** — `render_md()`가 `_rep/<doc>.json`(text·tables_std)에서 만든다. 같은 날짜 폴더에 파싱 결과
   원본도 함께(`raw_artifacts()` — <파일명>_<날짜>.json·<엔진>_<판>_<파일명>.json·vlm_<모델>_<파일명>.jsonl, rep.md를
   마지막에 써서 완료 표시). 원천 원본은 읽기만(수정·삭제·업로드 금지).
② 겹침/건너뜀 키(KEY) = (source_system, source_key) — source_key는 **원본 Object Storage 전체 키**(경로 포함,
   manifest의 "key" — 키가 없으면 상대 경로인 file_name). 두 폴더의 같은 이름 파일이 서로 안 겹친다.
③ Object Storage 키 = `rep_md_key()` → `<PM_PREFIX>/<source_system>/<원본 키 세그먼트별 safe_name>/<파일명>_<parse_date>.md`.
   이미 있으면 건너뜀(덮어쓰지 않음) — `--reparse` 목록만 예외로, 그때도 같은 날짜가 있으면 접미사를
   붙여(`_unique_parse_date`) 새 폴더를 만든다. 정리로 키가 바뀌면 원본 키의 짧은 해시를 덧붙인다(`rep_md_key()`).
④ EDW = INSERT만(KEY가 이미 있으면 건너뜀, 재파싱 행은 예외). UPDATE 없음.
⑥ DRM·파싱 실패(`EDW_EXCLUDED_STATUSES`)는 EDW에 넣지 않고 `render_excluded_report()`로 마크다운 보고서만.

상태(parse_status) = ok · partial(교차 정확도 < criteria.json run.cross_acc_full) · failed · skipped_drm(DRM·암호 래핑) ·
skipped_dup(dedup keep.txt에서 빠짐) · not_parsed(이번 파싱 대상 아님) · skipped_disk_cap(원본이 먼저 지워짐 — manifest의
disk_cap_sha256으로 행만 씀). 원본은 파싱이 끝나면 바로 지워지므로 ok·partial도 로컬 원본이 없을 수 있다 — 그때는
manifest의 "sha256"(fetch_docs가 지우기 전에 남김)으로 대체한다(parse_status는 그대로).

쓰기 대상: PM_TABLE(기본 AI.ParsingMeta) · PM_BUCKET(업로드 버킷, "file://<폴더>"면 로컬 폴더를 가짜 Object Storage로) ·
PM_PREFIX(버킷 안 경로 접두, 선택) · common.connections.rdb 쓰기 계정(RDB_HOST·RDB_PORT·RDB_DATABASE·RDB_WRITE_USER·
RDB_WRITE_PASSWORD) · RDB_SQLITE(설정하면 SQLite를 가짜 EDW로, 접속 칸 안 봄).
업로드 접속은 Object Storage 읽기와 같은 설정(OS_ENDPOINT·OS_ACCESS_KEY·OS_SECRET_KEY·OS_REGION·OS_VERIFY_TLS).

업로드 대상 상태(안전 기본값): 기본은 **ok·partial만 업로드**(DEFAULT_UPLOAD_STATUSES) — PM_UPLOAD_STATUSES(콤마 목록)로
넓힐 수 있다. DRM·실패는 ⑥로 EDW에도 안 들어간다(업로드 대상 여부와 별개 축).
"""

import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path

from common.config import settings as C  # common 칸(VLM_MODEL·OS_*) · 비밀 꺼내기
from common.core import span as SP  # 성능 span
from common.core.console import utf8_stdout
from common.core.contract import file_hash, jl, safe_filename, safe_path_join
from common.core.paths import APP_ROOT, CRITERIA_FILE
from pipeline import config as pc

ROOT = APP_ROOT  # output/ 등 런타임 경로용
_CROSS_ACC_FULL = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))["run"][
    "cross_acc_full"
]  # partial 사유 글자도 같은 정본(판정은 parse_scoring이 이미 함)
# EDW AI.ParsingMeta 저장소 클래스(MssqlStore·SqliteStore)는 검색과 함께 쓰므로 common.store.parsing_meta_db에 있다.
from common.store.parsing_meta_db import (  # noqa: E402,F401
    _SQLITE_TYPE,
    COLUMNS,
    DEFAULT_TABLE,
    KEY,
    TABLE_ID_RE,
    MssqlStore,
    SqliteStore,
    _insert_new_rows,
    make_db,
)

STATUSES = ("ok", "partial", "failed", "skipped_drm", "skipped_dup", "not_parsed", "skipped_disk_cap")
DEFAULT_UPLOAD_STATUSES = ("ok", "partial")  # 안전 기본값 — DRM·실패·중복·미파싱은 EDW 행만(업로드 안 함)
EDW_EXCLUDED_STATUSES = ("skipped_drm", "failed")  # ⑥ EDW에 안 넣고 render_excluded_report()로만(소음 방지)


sha256_of = file_hash


def pipeline_version():
    """버전 — common.pipeline_version()(저장소 루트 VERSION·오버레이 패치 PATCH_VERSION 중 높은 것, 실행 보드와 같은 규칙)."""
    from common import pipeline_version as _pv

    return _pv()


def today():
    """이번 실행의 결과 시각 = 날짜+시간(대표 결과 파일 이름에 씀). 파일 이름에 쓰니 콜론 없이."""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")


_HASH_SUFFIX_RE = re.compile(r"__h[0-9a-f]{10}$")


def _hash10(value):
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:10]


def rep_md_key(prefix, source_system, source_key, parse_date):
    """대표 결과 .md 키 = <PM_PREFIX>/<source_system>/<원본 키 폴더, "/"마다 세그먼트별 safe_name>/
    <파일명>_<parse_date>.md — 원본 파일 자체는 올리지 않으므로 이 키는 Object Storage 안 '우리가 만든 결과' 자리일
    뿐 원본 자리가 아니다. 세그먼트별 safe_name으로 Windows 예약 이름·구분자를 정리하면서도 원본의 폴더 구조는
    그대로 유지한다(요건② "경로 포함").

    세그먼트별 safe_name만으로는 서로 다른 원본 키가 같은 결과 키로 접힐 수 있다
    (예: "a:b/c"의 safe_name 결과가 "a__b/c"가 되는데, 원본 키가 이미 "a__b/c"인 문서와 같아짐 — 두 번째
    문서의 결과가 다른 문서 폴더에 섞인다). 정리로
    세그먼트 중 하나라도 원본과 달라지면 마지막 세그먼트에 **원본 전체 키의 sha1 앞 10자**(`__h<hex10>`)를
    붙여 구분한다 — 정리가 필요 없는 흔한 경로(사용자가 읽는 대부분)는 그대로 둔다. 원본 키 자체가 이미 이
    해시 접미사 모양으로 끝나면(드물지만 가능) 그것도 해시를 붙여 "해시 붙은 키"와 "우연히 그렇게 생긴
    원본 키"가 서로 안 겹치게 한다. ponytail: 남는 이론상 충돌(sha1 10자 충돌)은 막지 않음."""
    key = str(source_key)
    raw_segs = [s for s in key.strip("/").split("/") if s not in ("", ".", "..")]
    segs = [safe_filename(s, "") for s in raw_segs] or [safe_filename(key, "")]
    # 정리된 경로를 원본 키 '문자열 전체'와 비교 — 세그먼트 치환뿐 아니라 빈 칸·'.'·'..'·앞뒤 '/' 걷어내기로 바뀐
    # 경우(예: 'a//b'·'a/./b'·'a/b/' → 'a/b')도 해시를 붙여 서로 다른 원본 키가 같은 결과 키로 접히지 않게
    if "/".join(segs) != key or (segs and _HASH_SUFFIX_RE.search(segs[-1])):
        h = f"h{_hash10(source_key)}"
        segs[-1] = f"{segs[-1]}__{h}" if segs[-1] else h
    # <출처>/<나머지 폴더>/<파일명>_<날짜>.md
    base = "/".join([safe_filename(source_system, ""), *segs[:-1], f"{doc_stem(source_key)}_{parse_date}.md"])
    return f"{prefix.rstrip('/')}/{base}" if prefix else base


def doc_stem(source_key):
    """결과 파일 이름 앞부분 = 원본 파일명에서 확장자 뺀 것(safe_name) — 예 'docs/abd.pdf' → 'abd'."""
    name = str(source_key).rstrip("/").rsplit("/", 1)[-1]
    return safe_filename(name.rsplit(".", 1)[0] if "." in name.strip(".") else name, "") or "doc"


def _dir_key(file_key):
    """대표 결과 파일 키 → 문서 폴더 키(끝 '/' 포함) — EDW rep_key에는 이 폴더를 넣는다
    ('.../Parsing-Result/<UUID>/<원본파일명>/'까지). 폴더 안 최신 결과는 parse_date(날짜+시간) 열로 가린다."""
    return file_key.rsplit("/", 1)[0] + "/"


def _unique_parse_date(storage, prefix, source_system, source_key, parse_date):
    """재파싱이 같은 날짜와 겹치면(이미 그 폴더가 있음) 접미사를 붙여 새 폴더를 찾는다(절대 덮어쓰지
    않음). 흔치 않은 경로라 선형 탐색으로 충분."""
    date, n = parse_date, 1
    while storage.head(rep_md_key(prefix, source_system, source_key, date)) is not None:
        n += 1
        date = f"{parse_date}-{n}"
    return date


def render_md(rep):
    """대표 결과(`_rep/<doc>.json`) → 마크다운(업로드 대상은 이것, 원본이 아님). 본문(쪽 구분 \\f는 빈
    줄로) + 표(`tables_std`가 있으면 GitHub 표, 없으면 원시 `tables[].text`를 코드블록으로) — 최소 결정적 렌더러
    (순수 함수, I/O 없음). `table_inline`이 표를 이미 본문 제자리에 넣은 표(entry["inline"] True)는
    여기서 다시 안 붙인다(끝에 또 붙으면 같은 표가 두 번). 자리를 못 찾아 본문엔 안
    들어간 표(inline False·끈 경우 inline 칸 자체가 없음)는 그대로 끝에 붙인다."""
    parts = []
    text = (rep.get("text") or "").replace("\f", "\n\n")
    if text.strip():
        parts.append(text.strip())
    tables_std = rep.get("tables_std") or []
    for t in tables_std:
        if t.get("inline"):
            continue
        header, rows = t.get("header") or [], t.get("rows") or []
        if not header and not rows:
            continue
        lines = []
        if header:
            lines.append("| " + " | ".join(str(c) for c in header) + " |")
            lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for r in rows:
            lines.append("| " + " | ".join(str(c) for c in r) + " |")
        parts.append("\n".join(lines))
    if not tables_std:
        for t in rep.get("tables") or []:
            if t.get("text"):
                parts.append("```\n" + t["text"] + "\n```")
    return ("\n\n".join(parts) + "\n") if parts else ""


def _local_md_name(row):
    """apply()가 올리기 전 잠깐 쓰는 로컬 파일 이름 — uuid(파일명 sha1 앞 10자 + 날짜)만 사용해 OS 제한(255자)을 피한다."""
    return f"tmp_{row.get('source_key', '')[:0]}{_hash10(row.get('source_key', ''))}_{row.get('parse_date', '')}.md"


def status_of(name, rep_by_doc, summary, skipped=None, keep=None):
    """문서 하나의 파싱 상태 — skipped(이름→drm_*·encrypted_* 사유, filter_and_rotate의 skipped.jsonl)·
    keep(dedup keep.txt에 있는 이름 집합, None = dedup 정보 없음 → 전부 포함) 순서로 먼저 걸러진 뒤 대표 결과(rep)를 본다."""
    if skipped and name in skipped and str(skipped[name]).startswith(("drm", "encrypted")):
        return "skipped_drm", skipped[name], None
    if keep is not None and name not in keep:
        return "skipped_dup", "완전 중복으로 제외(dedup keep.txt에 없음)", None
    r = rep_by_doc.get(name)
    if r is None:
        return "not_parsed", "이번 파싱 대상 아님(예: 새 판에 밀린 옛 판·이번 실행에서 안 받음)", None
    if not r.get("engine"):
        return "failed", r.get("reason") or "성공한 엔진 없음", r
    partial = {d for t in (summary.get("types") or {}).values() for d in t.get("partial") or []}
    return ("partial", f"교차 정확도 < {_CROSS_ACC_FULL}", r) if name in partial else ("ok", None, r)


def parse_upload_statuses(env_value):
    """PM_UPLOAD_STATUSES(콤마 목록) → 집합. 비었으면 안전 기본값(DEFAULT_UPLOAD_STATUSES = ok·partial만)."""
    vals = {s.strip() for s in (env_value or "").split(",") if s.strip()}
    bad = vals - set(STATUSES)
    if bad:
        raise ValueError(f"[parsing_meta] PM_UPLOAD_STATUSES에 모르는 상태 — {sorted(bad)}(허용: {STATUSES})")
    return vals or set(DEFAULT_UPLOAD_STATUSES)


def load_reparse_keys(path):
    """--reparse <파일> — 사람 조치 뒤 재파싱 대상으로 명시한 원본 전체 키 목록(한 줄에 하나, '#' 주석·빈 줄 무시).
    가장 단순한 명시적 입력(요건③ "명시적 입력" — 레지스트리 상태 열 대신 이 파일로)."""
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"[parsing_meta] --reparse 파일 없음 — {p}")
    return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")}


def _figures_by_doc(parse_dir):
    """`_images/index.jsonl`(그림 기록 — VLM 모델·prompt_id·캡션·본문 언급 = VLM에 같이 준 맥락) → {문서: [기록…]}."""
    f = Path(parse_dir) / "_images" / "index.jsonl"
    by = {}
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                by.setdefault(r.get("doc"), []).append(r)
    return by


def _runs_by_doc_engine(parse_dir):
    """`runs.jsonl`(엔진 실행 기록 — engine_version·p0_key·run_id) → {(문서, 엔진): 마지막 성공 기록}. 한 번만 읽어
    엔진별 원본 JSON을 다시 열지 않고 판 정보를 얻는다(dry-run 비용)."""
    f = Path(parse_dir) / "runs.jsonl"
    out = {}
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if not r.get("error"):
                    out[(r.get("doc"), r.get("engine"))] = r
    return out


_OCR_ENGINE_NAMES = {"rapidocr_ko"}  # role='ocr'로 구분할 알려진 OCR 엔진(그 밖 후보 텍스트 엔진은 role='candidate')


def _vlm_model(model, env_fallback):
    """rep.post.vlm_models에 모델 이름이 있으면 그대로, 없으면(env_fallback=True일 때만) 지금 프로세스의
    VLM_MODEL로 대신한다(게시가 파싱과 다른 설정으로 돌 때의 마지막 대체 경로일 뿐 — rep가
    1차). 둘째 반환값 True = 대체를 썼다는 표시(engines_used()가 그 항목에 "source":"env_fallback"을 남김)."""
    if model:
        return model, False
    if not env_fallback:
        return None, False
    vlm = C.cfg().models.vlm
    fb = vlm.model
    return fb, bool(fb)


def engines_used(rep_json, env_fallback=True):
    """문서 하나의 대표 결과(`_rep/<문서>.json` 전체, status_of()가 쓰는 index.json 요약이 아님)
    에서 실제로 쓰인 엔진 전부(VLM·OCR 포함) → (engines_used 목록, 한 줄 요약) — EDW `engines_used`·
    `engines_summary` 두 열의 값. 순수 함수(rep_json만 읽음) — 단 env_fallback=True(기본)이면 rep에 VLM 모델
    이름이 없을 때만 현재 프로세스의 VLM_MODEL을 대신 읽는다(그 항목에 "source":"env_fallback"
    표시 — publish는 파싱과 다른 실행·env일 수 있어 rep를 1차로, env는 rep에 없을 때만의 대체).

    보는 자리(설계):
      rep.rep.engine(대표로 뽑힌 엔진) → role='rep' · rep.rep.tried(시도한 엔진 전부, rapidocr_ko·qwen_vlm 포함) 중
      대표가 아닌 것 → role='ocr'(_OCR_ENGINE_NAMES) 또는 'candidate'(그 밖 텍스트 엔진) · rep.post.vlm_page_calls
      (+모델 rep.post.vlm_models.page) → role='vlm_page' · rep.post.figures(+모델 rep.post.vlm_models.figure) →
      role='vlm_figure' · rep.agent(판단 기록, 있으면) →
      role='agent'. 항목 = {"engine","role","status","version_or_model","calls"}.
    rep_json이 비었으면([], None)."""
    if not rep_json:
        return [], None
    out = []
    rep = rep_json.get("rep") or {}
    tried = rep.get("tried") or {}
    chosen = rep.get("engine")
    text_names, ocr_names = [], []
    for eng in sorted(tried):
        info = tried[eng] or {}
        role = "rep" if eng == chosen else ("ocr" if eng in _OCR_ENGINE_NAMES else "candidate")
        out.append({"engine": eng, "role": role, "status": info.get("status"), "version_or_model": info.get("version"), "calls": 1})
        if role == "candidate":
            text_names.append(eng)
        elif role == "ocr":
            ocr_names.append(eng)
    post = rep_json.get("post") or {}
    vlm_models = post.get("vlm_models") or {}
    page_calls, fig_calls = post.get("vlm_page_calls") or 0, post.get("figures") or 0
    page_model, page_fb = _vlm_model(vlm_models.get("page"), env_fallback)
    fig_model, fig_fb = _vlm_model(vlm_models.get("figure"), env_fallback)
    if page_calls:
        row = {"engine": page_model or "vlm", "role": "vlm_page", "status": "ok", "version_or_model": page_model, "calls": page_calls}
        if page_fb:
            row["source"] = "env_fallback"
        out.append(row)
    if fig_calls:
        row = {"engine": fig_model or "vlm", "role": "vlm_figure", "status": "ok", "version_or_model": fig_model, "calls": fig_calls}
        if fig_fb:
            row["source"] = "env_fallback"
        out.append(row)
    agent = rep_json.get("agent") or {}
    if agent:
        out.append(
            {"engine": agent.get("agent") or "agent", "role": "agent", "status": agent.get("status"), "version_or_model": None, "calls": 1}
        )
    parts = [f"rep={chosen}"] if chosen else []
    if text_names:
        parts.append("text=" + ",".join(text_names))
    if ocr_names:
        parts.append("ocr=" + ",".join(ocr_names))
    vlm_bits = ([f"page×{page_calls}"] if page_calls else []) + ([f"fig×{fig_calls}"] if fig_calls else [])
    if vlm_bits:
        parts.append(f"vlm={page_model or fig_model or '모델?'} " + " ".join(vlm_bits))
    if agent:
        parts.append(f"agent={agent.get('agent') or 'agent'}")
    summary = "; ".join(parts) or None
    return out, (summary[:512] if summary else None)


def raw_artifacts(parse_dir, name, figs, runs=None):
    """rep.md와 같은 날짜 폴더에 함께 올릴 것
    [(파일 이름, 로컬 Path 또는 텍스트)]: rep.json(후보정까지 끝난 대표 결과 원본 전체) · engines/<엔진>.json(엔진별
    파싱 원본 — provenance.engine_version 포함) · figures.jsonl(이 문서 그림 기록 — VLM 모델·prompt_id·캡션·본문
    언급). 큰 파일은 Path로 넘겨 apply()가 그대로 올린다(메모리에
    안 담음)."""
    parse_dir = Path(parse_dir)
    out = []
    rep_p = parse_dir / "_rep" / f"{name}.json"
    rep = json.loads(rep_p.read_text(encoding="utf-8")) if rep_p.exists() else {}
    if rep:
        out.append(("<stem>_<date>.json", rep_p))
    for d in sorted(x for x in parse_dir.iterdir() if x.is_dir() and not x.name.startswith(("_", "."))):
        f = d / f"{name}.json"
        if not f.exists():
            continue
        run = (runs or {}).get((name, d.name))
        if run is None:  # runs.jsonl에 없음 — 그때만 파일의 provenance를 읽음
            prov = json.loads(f.read_text(encoding="utf-8")).get("provenance") or {}
            if not prov.get("engine"):  # 엔진 결과만(signals 등 다른 폴더 제외)
                continue
            run = {"engine_version": prov.get("engine_version"), "p0_key": prov.get("p0_key"), "at": prov.get("created_at")}
        ver = run.get("engine_version")
        out.append(("engine/" + safe_filename(d.name + ("_" + str(ver) if ver else ""), "") + "_<stem>.json", f))
    vlm_models = sorted({m for r in figs for m in ((r.get("vlm") or {}).get("model"), (r.get("provenance") or {}).get("model")) if m})
    if figs:  # 그림 기록 = VLM 결과·넘긴 맥락 — 이름에 VLM 모델 ID(판 포함)
        out.append(
            (
                "engine/" + safe_filename("vlm_" + ("+".join(m.rsplit("/", 1)[-1] for m in vlm_models) or "none"), "") + "_<stem>.jsonl",
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in figs),
            )
        )
    # meta.json·source.json 제외 — _meta.json은 EDW에, source.json은 내부용
    return [r for r in out if not r[0].endswith("_meta.json")]


def plan(
    entries,
    source_dir,
    rep_dir,
    rep_by_doc,
    summary,
    skipped,
    keep,
    version,
    bucket,
    prefix,
    source_system,
    upload_statuses=None,
    parse_date=None,
    reparse_keys=None,
):
    """로컬만 읽는다(네트워크·DB 접속 없음) — --dry-run이 그대로 쓸 수 있음.
    entries: manifest.jsonl 행(fetch_docs 형식 — file_name·key(원본 전체 키)·doc_id·uri·original_filename·
    source_system(있을 때만 — 없으면 이 함수의 source_system 인자를 폴백으로 쓴다) 등).
    rep_dir: `output/parse/_rep`(대표 결과 폴더 — `<name>.json` 전체를 읽어 업로드할 .md를 미리 만든다).
    upload_statuses: 원본을 실제로 올릴 상태 집합(None = DEFAULT_UPLOAD_STATUSES = ok·partial만).
    parse_date: 이 실행의 날짜 폴더 이름(None = today()).
    reparse_keys: 사람 조치 뒤 재파싱 대상으로 명시된 source_key 집합(load_reparse_keys()의 반환값).
    반환: (entries, missing) — entries=[{"row":row_dict,"local_path":Path|None,"upload":bool,"md_text":str|None,
    "doc_name":name,"reparse":bool}] · missing=로컬에 원본도 sha256도 없는 문서 수(크래시 대신 건수만 센다)."""
    allowed = set(upload_statuses) if upload_statuses is not None else set(DEFAULT_UPLOAD_STATUSES)
    reparse_keys = reparse_keys or set()
    parse_date = parse_date or today()
    out, missing = [], 0
    figs_by_doc = _figures_by_doc(Path(rep_dir).parent)
    runs = _runs_by_doc_engine(Path(rep_dir).parent)
    for e in entries:
        name = e.get("file_name")
        if not name:
            missing += 1
            continue
        source_key = e.get("key") or name  # 원본 Object Storage 전체 키(경로 포함); 없으면(폴더 직접 소스) 상대 경로(이름)
        f = Path(source_dir) / name
        cap_sha, gen_sha = e.get("disk_cap_sha256"), e.get("sha256")
        st, reason, rep = status_of(name, rep_by_doc, summary, skipped, keep)
        if f.exists():
            sha, file_size, local_path = sha256_of(f), f.stat().st_size, f
        elif cap_sha:  # PARSE_KEEP_MAX_GB 상한으로 원본이 먼저 지워짐 — 이 상태만 강제로 덮어씀
            sha, file_size, local_path = cap_sha, e.get("size"), None
            st, reason = "skipped_disk_cap", "원본 없음(PARSE_KEEP_MAX_GB 상한으로 publish 전에 지워짐)"
        elif gen_sha:  # 파싱이 끝나면 원본을 바로 지움(기본) — 상태는 그대로(ok/partial/failed/…), 로컬만 없음
            sha, file_size, local_path = gen_sha, e.get("size"), None
        else:
            missing += 1
            continue
        upload = st in allowed
        # 전체 대표 결과(_rep/<문서>.json, status_of()의 rep은 index.json 요약만)를 한 번만 읽어
        # engines_used()에도 쓰고(요건(b)) 올릴 때의 render_md·raw_artifacts에도 그대로 재사용(중복 읽기 없음).
        rep_path = Path(rep_dir) / f"{name}.json"
        full_rep = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else None
        eng_list, eng_summary = engines_used(full_rep) if full_rep else ([], None)
        row = {
            "source_system": e.get("source_system") or source_system,  # manifest이 들고 온 원천, 없으면 --source-system 폴백
            "source_key": source_key,
            "source_uri": e.get("uri"),
            "original_filename": e.get("original_filename") or name,
            "file_format": (rep or {}).get("format"),
            "file_size": file_size,
            "sha256": sha,
            "rep_bucket": bucket,
            "rep_key": _dir_key(rep_md_key(prefix, e.get("source_system") or source_system, source_key, parse_date)),  # EDW엔 문서 폴더
            "rep_etag": None,
            "parse_status": st,
            "status_reason": reason,
            "rep_engine": (rep or {}).get("engine"),
            "rep_acc": (rep or {}).get("acc"),
            "page_count": (rep or {}).get("pages"),
            "doc_key": (rep or {}).get("doc_key")
            or sha,  # 유일한 필수 열, 게시 시점엔 항상 구해짐(대표의 doc_key, 없으면 manifest 원본 sha256)
            "parse_date": parse_date,
            "pipeline_version": version,
            "status": "active",
            "status_at": None,
            "engines_used": json.dumps(eng_list, ensure_ascii=False) if eng_list else None,
            "engines_summary": eng_summary,
        }
        md_text, raw = None, []
        if upload:
            if full_rep is not None:
                md_text = render_md(full_rep)
                raw = raw_artifacts(Path(rep_dir).parent, name, figs_by_doc.get(name, []), runs)
            else:  # 대표 결과 파일이 없으면(있어선 안 되지만) 올릴 게 없음 — 안전 쪽으로 제외
                upload = False
        out.append(
            {
                "row": row,
                "local_path": local_path,
                "upload": upload,
                "md_text": md_text,
                "raw": raw,
                "file_key": rep_md_key(prefix, row["source_system"], source_key, parse_date),
                "doc_name": name,
                "reparse": source_key in reparse_keys,
            }
        )
    return out, missing


def render_excluded_report(entries):
    """EDW에 못 들어간 행(DRM·파싱 실패) → 마크다운 보고서 — 사유별로 묶어 원본 키를 보여준다(순수 함수,
    I/O 없음 — 파일로 쓰는 것은 호출부 main())."""
    by_reason = {}
    for e in entries:
        row = e["row"]
        if row["parse_status"] in EDW_EXCLUDED_STATUSES:
            by_reason.setdefault(row["parse_status"], []).append(row)
    if not by_reason:
        return "# EDW 제외 문서 없음(SI39⑥)\n"
    lines = ["# EDW 제외 문서 — DRM·파싱 실패(SI39⑥, EDW에 안 넣고 이 보고서로만)", ""]
    for status in sorted(by_reason):
        rows = by_reason[status]
        lines += [f"## {status} ({len(rows)}건)", "", "| source_system | 원본 키 | 사유 |", "|---|---|---|"]
        lines += [f"| {r['source_system']} | {r['source_key']} | {r.get('status_reason') or ''} |" for r in rows]
        lines.append("")
    return "\n".join(lines)


def apply(entries, storage, db, md_dir, prefix=""):
    """업로드(.md — 같은 이름이 이미 있으면 덮어쓰지 않고 접미사로 새 이름) + EDW INSERT(KEY가
    이미 있으면 건너뜀 — db.insert_new, UPDATE·MERGE 없음 · DRM·실패는 EDW_EXCLUDED_STATUSES라 아예 안 보냄).
    entries = plan()의 반환값 그대로. md_dir: .md를 잠깐 썼다가 올린 뒤 바로 지우는 로컬 폴더
    각 행에 "upload_result"를 채운다: "uploaded"(이 실행이 새로 올림) · "excluded"(PM_UPLOAD_STATUSES 밖이거나 렌더할 대표 결과가 없음).
    --apply일 때만 부른다(네트워크·쓰기)."""
    uploaded = excluded = 0
    for e in entries:
        row = e["row"]
        if not e["upload"]:
            e["upload_result"] = "excluded"
            excluded += 1
            continue
        fkey = e.get("file_key") or rep_md_key(prefix, row["source_system"], row["source_key"], row["parse_date"])
        if storage.head(fkey) is not None:  # 같은 시각 이름이 이미 있으면(드묾) 접미사로 새 이름 — 덮어쓰지 않음
            row["parse_date"] = _unique_parse_date(storage, prefix, row["source_system"], row["source_key"], row["parse_date"])
            fkey = rep_md_key(prefix, row["source_system"], row["source_key"], row["parse_date"])
        row["rep_key"] = _dir_key(fkey)
        folder = fkey.rsplit("/", 1)[0]
        Path(md_dir).mkdir(parents=True, exist_ok=True)
        for fname, src in e.get("raw") or []:  # 엔진별 원본(engine/)·후보정 대표 원본·meta — .md보다 먼저
            fname = fname.replace("<date>", row["parse_date"]).replace("<stem>", doc_stem(row["source_key"]))
            if isinstance(src, Path):
                storage.put(src, f"{folder}/{fname}")
            else:
                tmp = Path(md_dir) / f"tmp_{_hash10(row.get('source_key', '') + fname)}_{row.get('parse_date', '')}"
                tmp.write_text(src, encoding="utf-8")
                storage.put(tmp, f"{folder}/{fname}")
                tmp.unlink()
        md_path = Path(md_dir) / _local_md_name(row)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(e["md_text"] or "", encoding="utf-8")
        row["rep_etag"] = storage.put(md_path, fkey)
        md_path.unlink()
        e["upload_result"] = "uploaded"
        uploaded += 1
    rows_for_db = []
    for e in entries:
        if e["row"]["parse_status"] in EDW_EXCLUDED_STATUSES:  # DRM·실패는 EDW에 안 넣음(render_excluded_report로만)
            continue
        row = dict(e["row"])
        row["_reparse"] = e["reparse"]
        rows_for_db.append(row)
    inserted, key_skipped = db.insert_new(rows_for_db) if rows_for_db else (0, 0)
    edw_excluded = sum(1 for e in entries if e["row"]["parse_status"] in EDW_EXCLUDED_STATUSES)
    return {
        "uploaded": uploaded,
        "upload_excluded": excluded,
        "inserted": inserted,
        "edw_skip_existing": key_skipped,
        "edw_excluded_drm_failed": edw_excluded,
        "rows": len(entries),
    }


# ── Object Storage 백엔드 ──────────────────────────────────────────
class LocalFolderStore:
    """가짜 Object Storage(PM_BUCKET="file://<폴더>") — 시험·PC 확인용. KEY가 이미 있는 키는 덮어쓰지 않는다(apply()가 head()로 먼저 확인).
    head·put 둘 다 common.core.contract.safe_join으로 root 밖 경로를 거부한다(rep_key는 safe_name으로
    이미 정리되지만 마지막 방어선)."""

    def __init__(self, root):
        self.root = Path(root)

    def head(self, key):
        p = safe_path_join(self.root, key)
        if not p.exists():
            return None
        return {"size": p.stat().st_size, "etag": hashlib.md5(p.read_bytes()).hexdigest()}

    def exists(self, key):
        return self.head(key) is not None

    def put(self, local_path, key):
        dst = safe_path_join(self.root, key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(local_path, dst)
        return hashlib.md5(Path(local_path).read_bytes()).hexdigest()


class S3Store:
    """실제 Object Storage(PM_BUCKET=버킷 이름) — boto3(pipeline/extract/fetch_docs.py·cli/os_put.py와 같은 접속 env OS_*)."""

    def __init__(self, bucket):
        import boto3
        from botocore.config import Config

        from common.store.objectstore import resolve_tls_verify  # OS_VERIFY_TLS=0 경고는 objectstore 한 곳

        self.bucket = bucket
        os_ = C.cfg().connections.object_storage  # S7c — 설정 객체(키는 SecretStr)
        self.cli = boto3.client(
            "s3",
            endpoint_url=os_.endpoint or None,
            region_name=os_.region or "us-east-1",
            aws_access_key_id=C.reveal(os_.access_key),
            aws_secret_access_key=C.reveal(os_.secret_key),
            verify=resolve_tls_verify(),
            config=Config(retries={"max_attempts": 3}),
        )

    def head(self, key):
        from botocore.exceptions import ClientError

        try:
            r = self.cli.head_object(Bucket=self.bucket, Key=key)
            return {"size": r.get("ContentLength"), "etag": (r.get("ETag") or "").strip('"')}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def exists(self, key):
        return self.head(key) is not None

    def put(self, local_path, key):
        self.cli.upload_file(str(local_path), self.bucket, key)
        return hashlib.md5(Path(local_path).read_bytes()).hexdigest()


def make_storage():
    bucket = pc.cfg().load.publish.bucket
    if not bucket:
        raise SystemExit("[parsing_meta] PM_BUCKET 필요(PM1 결정 뒤 채움) — 'file://<폴더>'(시험) 또는 실제 버킷 이름")
    if bucket.startswith("file://"):
        return LocalFolderStore(bucket[len("file://") :])
    return S3Store(bucket)


def _load_inputs(out, manifest, source_dir, rep, summary, skipped, keep):
    out = Path(out)
    manifest = Path(manifest) if manifest else out / "parse" / "_source" / "manifest.jsonl"
    source_dir = Path(source_dir) if source_dir else out / "_source_files"
    rep = Path(rep) if rep else out / "parse" / "_rep" / "index.json"
    summary = Path(summary) if summary else out / "parse" / "parse_summary.json"
    if not skipped:  # filter_and_rotate가 기록을 prepared/_records/에 씀(예전 자리 prepared/skipped.jsonl도 읽음)
        new, old = out / "prepared" / "_records" / "skipped.jsonl", out / "prepared" / "skipped.jsonl"
        skipped = new if new.exists() or not old.exists() else old
    skipped = Path(skipped)
    keep = Path(keep) if keep else out / "dedup" / "keep.txt"
    if not manifest.exists():
        raise SystemExit(f"[publish_parse] manifest 없음 — {manifest}(Object Storage·RDB 기원 파싱만 대상, 폴더 직접 파싱은 PM3 범위 밖)")
    entries = jl(manifest)
    rep_by_doc = {d["doc"]: d for d in json.loads(rep.read_text(encoding="utf-8")).get("docs", [])} if rep.exists() else {}
    summ = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
    skip_map = {r["file"]: r["reason"] for r in jl(skipped)} if skipped.exists() else {}
    keep_set = {x.strip() for x in keep.read_text(encoding="utf-8").splitlines() if x.strip()} if keep.exists() else None
    return entries, source_dir, rep.parent, rep_by_doc, summ, skip_map, keep_set


def _no_upload_reason(e):
    if e["upload"]:
        return None
    status = e["row"]["parse_status"]
    if status == "skipped_disk_cap":  # 원본이 없어서(상태 제외가 아니라) 못 올림
        return e["row"]["status_reason"]
    if status in EDW_EXCLUDED_STATUSES:
        return f"상태={status} — EDW에도 안 들어감(SI39⑥, excluded_<날짜>.md 보고서로만)"
    return f"상태={status}(PM_UPLOAD_STATUSES 밖) — EDW 행만"


def run(a):
    entries, source_dir, rep_dir, rep_by_doc, summary, skipped, keep = _load_inputs(
        a.out, a.manifest, a.source_dir, a.rep, a.summary, a.skipped, a.keep
    )
    version = a.version or pipeline_version()
    parse_date = a.parse_date or today()
    pub = pc.cfg().load.publish  # S7c — 설정 객체
    bucket = pub.bucket
    if not bucket:
        if a.apply:
            raise SystemExit("[publish_parse] PM_BUCKET 필요(PM1 결정 뒤) — --apply에는 반드시 설정")
        bucket = "(PM_BUCKET 미설정 — dry-run 미리보기 값)"
    prefix = C.publish_prefix(pub.prefix or "")  # 개발 서버 여러 벌이면 <접두>/<벌>
    upload_statuses = parse_upload_statuses(",".join(pub.upload_statuses))  # 목록 → 옛 쉼표 글자(빈 목록 = 안전 기본값)
    reparse_keys = load_reparse_keys(a.reparse)
    rows, missing = plan(
        entries,
        source_dir,
        rep_dir,
        rep_by_doc,
        summary,
        skipped,
        keep,
        version,
        bucket,
        prefix,
        a.source_system,
        upload_statuses,
        parse_date,
        reparse_keys,
    )
    by_status = {}
    for e in rows:
        by_status[e["row"]["parse_status"]] = by_status.get(e["row"]["parse_status"], 0) + 1
    sample_rows = [
        {
            "original_filename": e["row"]["original_filename"],
            "status": e["row"]["parse_status"],
            "upload": e["upload"],
            "rep_key": e["row"]["rep_key"],
            "no_upload_reason": _no_upload_reason(e),
            "raw_files": [n for n, _ in e.get("raw") or []],
        }
        for e in rows[:10]
    ]
    out = {
        "mode": "apply" if a.apply else "dry-run",
        "pipeline_version": version,
        "parse_date": parse_date,
        "bucket": bucket,
        "prefix": prefix,
        "upload_statuses": sorted(upload_statuses),
        "rows_planned": len(rows),
        "missing_file": missing,
        "by_status": by_status,
        "upload_plan": {"eligible": sum(e["upload"] for e in rows), "excluded": sum(not e["upload"] for e in rows)},
        "reparse_requested": sum(e["reparse"] for e in rows),
        "sample_rows": sample_rows,
    }
    if not a.apply:
        print(json.dumps(out, ensure_ascii=False))
        print("[dry-run] 쓰기 0 — 실제 업로드·EDW 쓰기는 --apply 명시")
        return out
    storage, db = make_storage(), make_db("write")
    md_dir = Path(a.out) / "publish" / "_md_tmp"
    try:
        with SP.span("load.publish", "load", cpu=True) as sp:  # Object Storage 업로드 + EDW 쓰기 1행(대상 문서 수·결과 숫자)
            result = apply(rows, storage, db, md_dir, prefix)
            sp.rows(len(rows)).add(
                eligible=out["upload_plan"]["eligible"], **{k: v for k, v in (result or {}).items() if isinstance(v, (int, float))}
            )
    finally:
        if hasattr(db, "close"):
            db.close()
    out["result"] = result
    report_dir = Path(a.out) / "publish"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"excluded_{parse_date}.md"
    report_path.write_text(render_excluded_report(rows), encoding="utf-8")  # DRM·실패는 여기로만
    out["excluded_report"] = str(report_path)
    print(json.dumps(out, ensure_ascii=False))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--manifest", help="기본 <out>/parse/_source/manifest.jsonl")
    ap.add_argument("--source-dir", help="기본 <out>/_source_files")
    ap.add_argument("--rep", help="기본 <out>/parse/_rep/index.json")
    ap.add_argument("--summary", help="기본 <out>/parse/parse_summary.json")
    ap.add_argument(
        "--skipped", help="기본 <out>/prepared/_records/skipped.jsonl(옛 자리 prepared/skipped.jsonl도 — DRM·암호, 없으면 무시)"
    )
    ap.add_argument("--keep", help="기본 <out>/dedup/keep.txt(중복 제외 — 없으면 dedup 정보 없음으로 전부 포함)")
    ap.add_argument(
        "--source-system",
        default="FileStorageMap",
        help="SI41 — manifest 행이 source_system을 들고 있으면(rdb:*·rdb:<이름>) 그 값을 쓰고, 이 값은 "
        "폴백(레거시 단일 표 소스)에만 쓰인다",
    )
    ap.add_argument("--version", help="기본 저장소 루트 VERSION(옛 PATCH_VERSION이 더 높으면 그것 — common.pipeline_version, D-036)")
    ap.add_argument("--parse-date", help="기본 오늘(YYYY-MM-DD) — Object Storage 키의 날짜 폴더(SI39③)")
    ap.add_argument("--reparse", help="사람 조치 뒤 재파싱 대상 원본 키 목록 파일(한 줄에 하나, SI39③) — 새 날짜 폴더로, 옛 결과는 안 지움")
    ap.add_argument("--apply", action="store_true", help="실제 업로드 + EDW 쓰기(기본은 dry-run — 표만 출력, 쓰기 0)")
    a = ap.parse_args(argv)
    run(a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값
    utf8_stdout()
    import sys

    from pipeline.shared import runtrace

    with runtrace.run("publish_parse_result", sys.argv[1:]):  # 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
