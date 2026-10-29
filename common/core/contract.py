#!/usr/bin/env python3
"""모듈 사이 인계 계약 — 문서 ID·원문 조각 ID·원본 위치 규칙(ids.py 병합) + 인계 폴더 모양 점검(contract.py 병합,
CT1 — 둘 다 "모듈 사이 계약"이라 한 파일로 합침, docs/architecture.md §2).

ID·위치 규칙: doc_key = 원본 내용 sha256(64자, 같은 내용 사본은 같은 ID) · chunk_key = doc_key:순번 ·
source_uri = 원본 위치(file:/// · 나중 s3://). 파싱(만듦)·구조화(옮김)·적재(저장)·검색(돌려줌)이 같아야 함.

인계 점검: 넘겨받은 폴더가 다음 모듈이 쓸 수 있는 모양인지 — 구조화는 시작 전에 파싱 인계(_rep)를, 적재는
묶음을 점검하고 어긋나면 종료 코드 3으로 멈춘다(조용히 품질이 떨어지지 않게).
사용: python -m common.core.contract parse output/parse/_rep ·
      python -m common.core.contract structure output/edw/bundle ·
      python -m common.core.contract --selftest (dev/에서)
"""
import csv
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from common import CONTRACT

REP_KEYS = ("engine", "source", "format", "meta", "tried")                 # _rep/<문서>.json의 rep
SOURCE_KEYS = ("doc_key", "uri", "sha256")                                  # rep.source — 문서 ID·원본 위치
DOC_KEYS = ("file_path", "source_uri", "file_name", "file_sha256", "doc_format", "parse_engine")
CHUNK_KEYS = ("doc", "seq", "chunk_text", "n_terms")

WIN_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def make_chunk_key(doc_key, seq):
    return f"{doc_key}:{seq}"


def safe_filename(key, prefix):
    r"""S3 키·원본 파일 이름 → 평면 파일 이름 — `/`뿐 아니라 `\`·`:`도 `__`로 바꾼다(윈도 구분자·드라이브 표기 —
    독립 보안 검토 지적). 안 그러면 `C:\...` 절대경로나 `..\`가 이름에 그대로 남아 아래 safe_join의 범위 확인을
    하기 전부터 위험하다. Windows 예약 장치 이름(CON·PRN·AUX·NUL·COM1-9·LPT1-9, 대소문자 무시·확장자 있어도 적용
    — `CON.pdf`도 예약)이면 `_` 접두를 붙인다 — original_filename이 그대로 파일 이름이 되는 AD44(c)·SI37에서 그런
    이름이 오면 파일 생성이 OSError로 실패해 resolve()가 중단된다(독립 검토 MAJOR, 경로 탈출 쪽 예외 범위는 그대로
    — 여기서 예방만 한다). modules/parse/source.py(받기)·modules/load/parsing_meta.py(PM3 업로드 키, SI37)가 같이
    씀 — 모듈 경계상 import 방향(load는 parse를 import하지 않음)이라 common/으로 옮김."""
    n = key[len(prefix):].lstrip("/").replace("/", "__").replace("\\", "__").replace(":", "__")
    if n.split(".", 1)[0].upper() in WIN_RESERVED_NAMES:
        n = "_" + n
    if n in ("", ".", ".."):     # 구분자가 없어 위 치환을 통과한 '..'·'.'·빈 이름 — 키 마지막 칸이 폴더를 가리키지 않게(SI37 재검 MINOR)
        n = "_"
    return n


def safe_path_join(dest, name):
    """dest/name이 dest 밖으로 못 나가게 확인 뒤 경로를 돌려줌 — 이름 정리가 뚫려도 마지막 방어선(독립 보안 검토
    BLOCKER 2). source.py(원본 받기)·parsing_meta.LocalFolderStore(PM3 업로드, SI37)가 같이 씀."""
    dest = Path(dest)
    f = dest / name
    if dest.resolve() not in f.resolve().parents and f.resolve() != dest.resolve():
        raise ValueError(f"[ids] 경로 조작 의심 — {name!r}가 받는 폴더({dest}) 밖을 가리킴")
    return f


def make_source_uri(doc, path):
    """원본 위치 주소 — SOURCE_URI_PREFIX(예: s3://버킷/접두 · file:///srv/rag/docs)가 있으면 그 아래 이름, 없으면 원본 폴더(DOC_DIR)의
    같은 이름 파일, 그것도 없으면 파싱한 파일의 file:// 주소. 검색(MCP)이 결과와 함께 돌려줌 — 나중에 Object Storage면 s3:// 그대로."""
    man = os.environ.get("SOURCE_MANIFEST")                # Object Storage에서 받은 문서 → s3://버킷/키(modules/parse/source.py)
    if man and Path(man).exists():
        for ln in Path(man).read_text(encoding="utf-8").splitlines():
            if ln.strip() and json.loads(ln)["file_name"] == doc:
                return json.loads(ln)["uri"]
    pre = os.environ.get("SOURCE_URI_PREFIX")
    if pre:
        return pre.rstrip("/") + "/" + doc
    d = os.environ.get("DOC_DIR")
    if d and (Path(d) / doc).is_file():
        return (Path(d) / doc).resolve().as_uri()
    return Path(path).resolve().as_uri()


def original_file_hash(path):
    """GH1-04 — 회전 전 원본 바이트의 sha256. `path`와 같은 폴더(보통 output/prepared)의 rotation.csv(prepare.py가
    남김, orig_sha256 열)에서 이 파일 이름의 값을 찾는다. 없으면(이미지·이미지 PDF가 아니어서 회전 대상이
    아니었거나, rotation.csv가 없는 옛 prepared) None — 호출자가 file_sha256(path)로 대체한다. structure
    모듈(build_bundle.py)도 같은 함수로 같은 값을 계산해야 doc_key가 양쪽에서 맞는다(HANDOFF_FILES).
    GH1-04b — rotation.csv가 깨진 바이너리면(UnicodeDecodeError) 또는 못 읽으면(OSError·csv.Error) 여기서
    None으로 — 그 폴더 전체가 파싱 실패로 번지지 않게(호출자는 파일 없음과 같게 file_sha256로 대체)."""
    p = Path(path)
    f = p.parent / "rotation.csv"
    if not f.exists():
        return None
    try:
        with f.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row.get("file") == p.name and row.get("orig_sha256"):
                    return row["orig_sha256"]
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return None


def source_record(src, doc):
    """원본 정보 {doc_key · uri · path · sha256 · prepared_sha256 · size} — 파싱 모듈이 대표 결과(rep.source)에 남김.
    doc_key·sha256 = 회전 전 **원본** 바이트 식별(인용·중복 판정 안정, GH1-04) — rotation.csv에 orig_sha256이
    있으면 그 값, 없으면 준비된 파일과 같음. prepared_sha256 = 지금 파일(회전됐을 수 있음)의 sha — 파서 캐시
    키(run_all.py의 P0 열쇠)는 이 값과 별개로 자기 쪽에서 직접 다시 계산해 쓴다(여기 칸은 참고용)."""
    p = Path(src) / doc if src else None
    if not p or not p.is_file():
        return None
    prepared = file_hash(p)
    h = original_file_hash(p) or prepared
    return {"doc_key": h, "uri": make_source_uri(doc, p), "path": str(p.resolve()), "sha256": h,
            "prepared_sha256": prepared, "size": p.stat().st_size}


def uri_from_path(path):
    """원본 위치 주소가 저장 안 된 예전 기록 → 경로에서(이미 주소면 그대로)."""
    return path if "://" in (path or "") else (Path(path).as_uri() if path and Path(path).is_absolute() else path)


def openviking_key(s):
    """OpenViking 문서 이름 ↔ 우리 파일 이름 대조용: 확장자·경로 제거, NFKC, 소문자, 공백·기호 제거(파싱 엔진·구조화 요약·검색 공통)."""
    s = unicodedata.normalize("NFKC", Path(str(s).rstrip("/")).name)
    s = re.sub(r"\.(pdf|docx?|xlsx?|pptx?|txt|png|jpe?g|tiff?|bmp|md|hwp)$", "", s, flags=re.I)
    s = re.sub(r"\s*(\(\d+\)|\[\d+\]|[_\- ](copy|사본|복사본))$", "", s, flags=re.I)   # 사본 표시 "(1)" 등은 떼고 대조
    return re.sub(r"[\s_\-.()\[\]]+", "", s.lower())


def bundle_chunk_keys(bundle):
    """묶음 청크 순서대로 chunk_key 목록('<doc_key>:<seq>')."""
    B = Path(bundle)
    docs = jl(B / "docs.jsonl")
    return [make_chunk_key(docs[c["doc"]]["file_sha256"], c["seq"]) for c in jl(B / "chunks.jsonl")]


def jl(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def check_parse(rep_dir, sample=0):
    """파싱 → 구조화 인계 폴더(output/parse/_rep). sample>0이면 문서 그만큼만 열어 봄(대량 폴더 빠른 점검)."""
    d, bad = Path(rep_dir), []
    for f in ("_DONE.json", "index.json", "sources.jsonl"):
        if not (d / f).exists():
            bad.append(f"{f} 없음")
    if bad:
        return bad
    m = json.loads((d / "_DONE.json").read_text(encoding="utf-8"))
    if m.get("contract") != CONTRACT:
        bad.append(f"계약 버전 {m.get('contract')} ≠ {CONTRACT}")
    idx = [r for r in json.loads((d / "index.json").read_text(encoding="utf-8"))["docs"] if r.get("engine")]
    keys = {r["doc_key"] for r in jl(d / "sources.jsonl")}
    for r in idx[:sample] if sample else idx:
        f = d / f"{r['doc']}.json"
        if not f.exists():
            bad.append(f"{r['doc']}: 대표 결과 파일 없음")
            continue
        rep = (json.loads(f.read_text(encoding="utf-8")).get("rep") or {})
        miss = [k for k in REP_KEYS if k not in rep] + [f"source.{k}" for k in SOURCE_KEYS if not (rep.get("source") or {}).get(k)]
        if miss:
            bad.append(f"{r['doc']}: rep에 {', '.join(miss)} 없음")
        elif rep["source"]["doc_key"] not in keys:
            bad.append(f"{r['doc']}: sources.jsonl에 문서 ID 없음")
    return bad


def check_bundle(bundle_dir):
    """구조화 → 적재·검색 인계(output/edw/bundle): 파일·필드·벡터 행 수·차원."""
    import numpy as np
    d, bad = Path(bundle_dir), []
    for f in ("meta.json", "docs.jsonl", "chunks.jsonl", "vectors.npy", "kg_nodes.jsonl", "kg_edges.jsonl"):
        if not (d / f).exists():
            bad.append(f"{f} 없음")
    if bad:
        return bad
    meta, docs, chunks = json.loads((d / "meta.json").read_text(encoding="utf-8")), jl(d / "docs.jsonl"), jl(d / "chunks.jsonl")
    v = np.load(d / "vectors.npy", mmap_mode="r")
    if v.shape[0] != len(chunks):
        bad.append(f"벡터 {v.shape[0]}행 ≠ 청크 {len(chunks)}개")
    if (v.shape[1] if v.ndim == 2 else 0) != meta.get("dim"):
        bad.append(f"벡터 차원 {v.shape[1] if v.ndim == 2 else '?'} ≠ meta.dim {meta.get('dim')}")
    for i, x in enumerate(docs):
        miss = [k for k in DOC_KEYS if not x.get(k)]
        if miss:
            bad.append(f"docs[{i}] {x.get('file_name')}: {', '.join(miss)} 없음")
            break
    for i, c in enumerate(chunks):
        if any(k not in c for k in CHUNK_KEYS) or not 0 <= c["doc"] < len(docs):
            bad.append(f"chunks[{i}]: 필드 없음 또는 문서 번호 범위 밖")
            break
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kind, path = sys.argv[1], sys.argv[2]
    errs = check_parse(path) if kind == "parse" else check_bundle(path)
    print("계약 일치" if not errs else "계약 불일치:\n- " + "\n- ".join(errs[:50]))
    sys.exit(3 if errs else 0)
