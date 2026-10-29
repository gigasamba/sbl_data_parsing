#!/usr/bin/env python3
"""원본 즉시 삭제(백로그 X2) 점검 — 처리 끝난 문서의 원본·사본·엔진별 중간 결과·임시 폴더 잔여물이 남아 있는지 확인.
어기면(잔여물 있음) 종료 코드 1. 경로·개수만 보이고 문서 내용은 찍지 않는다.

사용: python cli/check_residue.py output/parse [--tmp output/_tmp_parse/stream] [--keep-raw-layer 0|1]
  out_dir           파싱 모듈 출력(보통 output/parse) — _rep/index.json으로 처리 끝난 문서를 안다.
  --tmp             스트리밍 임시 폴더(기본 PARSE_TMP 또는 <out_dir>/../_tmp_parse/stream) — 남은 파일이 있으면 잔여.
                     형제 폴더 <--tmp>/../attach(post/attachments.py의 attach-* 임시 파일, MINOR 5·재검토 6번)도
                     같이 본다 — PARSE_TMP 자체가 아니라 그 옆이라 시작 시 통째 청소 대상이 아니다.
  --keep-raw-layer  0이면 <out_dir>/raw/** (P0 원본 층 캐시)도 잔여로 본다(기본 env KEEP_RAW_LAYER 또는 1 = 허용).

주의: 이 점검은 PARSE_STREAM=1(백로그 X2) 실행을 검증하기 위한 것이다. 일반(스트리밍 아닌) 파싱은 엔진별 중간 결과를
재사용하려고 일부러 남겨 두므로, 그 output/parse 폴더에 돌리면 당연히 '잔여 있음'으로 나온다.
"""

import argparse
import json
import sys
from pathlib import Path

from common.core.console import utf8_stdout
from common.core.paths import PKG_ROOT  # 공용 자산 루트(10-14 이미지 단위 분리)
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

ROOT = PKG_ROOT
SPECIAL = ("_rep", "_images", "raw", "_source")  # 엔진 폴더가 아닌 것(지우면 안 됨)


def check(out_dir, tmp_dir, keep_raw_layer):
    out_dir = Path(out_dir)
    issues = []

    if tmp_dir and Path(tmp_dir).exists():
        left = [p for p in Path(tmp_dir).rglob("*") if p.is_file()]
        if left:
            issues.append(f"임시 폴더({tmp_dir}) 잔여 파일 {len(left)}개 — 예: " + ", ".join(p.name for p in left[:5]))

    if tmp_dir:
        from pipeline.stream import attach_dir_of

        adir = attach_dir_of(tmp_dir)
        if adir.exists():
            left = [p for p in adir.rglob("*") if p.is_file()]
            if left:
                issues.append(f"첨부 임시 폴더({adir}) 잔여 파일 {len(left)}개 — 예: " + ", ".join(p.name for p in left[:5]))

    idx_f = out_dir / "_rep" / "index.json"
    done = []
    if idx_f.exists():
        done = [r for r in json.loads(idx_f.read_text(encoding="utf-8"))["docs"] if r.get("engine")]

    eng_dirs = [d for d in out_dir.iterdir() if d.is_dir() and d.name not in SPECIAL] if out_dir.exists() else []
    residue_docs = {}
    for r in done:
        doc = r["doc"]
        for ed in eng_dirs:
            if (ed / f"{doc}.json").exists():
                residue_docs.setdefault(doc, []).append(ed.name)
    if residue_docs:
        sample = list(residue_docs.items())[:5]
        issues.append(
            f"처리 끝난 문서의 엔진별 중간 결과가 남음 {len(residue_docs)}건 — 예: " + ", ".join(f"{d}({','.join(es)})" for d, es in sample)
        )

    if not pc.cfg().extract.cache.keep_local_originals:  # S7c — 설정 객체
        legacy_dirs = [out_dir.parent / "_source_files", out_dir.parent / "prepared"]
        orig_left = []
        for r in done:
            if not (r.get("uri") or "").startswith("s3://"):
                continue
            for d in legacy_dirs:
                if (d / r["doc"]).exists():
                    orig_left.append(r["doc"])
        if orig_left:
            issues.append(f"Object Storage에서 받은 원본·사본이 남음 {len(orig_left)}건 — 예: " + ", ".join(orig_left[:5]))

    if keep_raw_layer == "0":
        raw_dir = out_dir / "raw"
        if raw_dir.exists():
            left = [p for p in raw_dir.rglob("*") if p.is_file()]
            if left:
                issues.append(f"KEEP_RAW_LAYER=0인데 P0 원본 층 캐시({raw_dir}) 파일 {len(left)}개 남음")

    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--tmp", default=pc.cfg().paths.parse_tmp)
    ap.add_argument("--keep-raw-layer", default="1" if pc.cfg().extract.cache.keep_raw_layer else "0", choices=["0", "1"])
    a = ap.parse_args()
    tmp = a.tmp or str(Path(a.out_dir).resolve().parent / "_tmp_parse" / "stream")
    issues = check(a.out_dir, tmp, a.keep_raw_layer)
    if issues:
        print("잔여물 있음:\n- " + "\n- ".join(issues))
        sys.exit(1)
    print("잔여물 없음")


if __name__ == "__main__":
    utf8_stdout()
    main()
