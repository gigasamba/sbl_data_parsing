#!/usr/bin/env python3
"""게시(publish — PRD pl-09): 파싱이 끝난 문서의 대표 결과(.md)와 엔진별 원결과를 Object Storage에 올리고 EDW `AI.ParsingMeta`에 행을 쓴다.
공용 로직은 pipeline/load/parsing_meta.py — 이 CLI는 그 함수만 부른다.

규칙: 원본 파일은 올리지 않는다 · 겹침 키 = (source_system, 원본 전체 키) — 있으면 건너뜀, `--reparse` 목록만 새 날짜 폴더 ·
EDW는 INSERT만 · 게시 버킷이 원천 원본 버킷과 같으면 거부 · DRM·실패 문서는 EDW에 안 쓰고 `output/publish/excluded_<날짜>.md`에만.

사용: python -m pipeline.load.publish_parse_result [--out output] [--parse-date YYYY-MM-DD] [--reparse <키 목록 파일>] [--apply]
기본은 dry-run(표만 출력, 업로드·EDW 쓰기 0). 설정은 settings.yaml(게시 버킷·접두·표, EDW 쓰기 계정, Object Storage 접속 —
settings.sample.yaml `load.publish`·`required`). PC는 버킷 `file://<폴더>`·`RDB_SQLITE`로 로컬 대역을 쓴다.
DDL은 실행하지 않는다. SQL은 식별자 화이트리스트·값 바인딩, 비밀값은 출력하지 않는다.
"""

import argparse
import json
from pathlib import Path

from common.core import span as SP  # op-01 성능 span
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from common.core.contract import jl  # noqa: E402
from pipeline import config as pc  # noqa: E402 — pipeline 칸 설정 객체(S7c)
from pipeline.load import parsing_meta as PM  # noqa: E402


def _load_inputs(out, manifest, source_dir, rep, summary, skipped, keep):
    out = Path(out)
    manifest = Path(manifest) if manifest else out / "parse" / "_source" / "manifest.jsonl"
    source_dir = Path(source_dir) if source_dir else out / "_source_files"
    rep = Path(rep) if rep else out / "parse" / "_rep" / "index.json"
    summary = Path(summary) if summary else out / "parse" / "parse_summary.json"
    if not skipped:  # 운영 고침 10(11-02) — prepare가 기록을 prepared/_records/에 씀(옛 자리 prepared/skipped.jsonl도 읽음)
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
    if status in PM.EDW_EXCLUDED_STATUSES:
        return f"상태={status} — EDW에도 안 들어감(SI39⑥, excluded_<날짜>.md 보고서로만)"
    return f"상태={status}(PM_UPLOAD_STATUSES 밖) — EDW 행만"


def run(a):
    entries, source_dir, rep_dir, rep_by_doc, summary, skipped, keep = _load_inputs(
        a.out, a.manifest, a.source_dir, a.rep, a.summary, a.skipped, a.keep
    )
    version = a.version or PM.pipeline_version()
    parse_date = a.parse_date or pc.cfg().load.publish.parse_date or PM.today()
    pub = pc.cfg().load.publish  # S7c — 설정 객체
    bucket = pub.bucket
    if not bucket:
        if a.apply:
            raise SystemExit("[publish_parse] PM_BUCKET 필요(PM1 결정 뒤) — --apply에는 반드시 설정")
        bucket = "(PM_BUCKET 미설정 — dry-run 미리보기 값)"
    else:
        if not pub.bucket_skip_overlap_check:
            PM.check_bucket_overlap(bucket, entries)  # SI39⑤ — 원천 원본 버킷과 같으면 여기서 거부(dry-run도)
    prefix = pub.prefix or ""
    upload_statuses = PM.parse_upload_statuses(",".join(pub.upload_statuses))  # 목록 → 옛 쉼표 글자(빈 목록 = 안전 기본값)
    reparse_keys = PM.load_reparse_keys(a.reparse)
    rows, missing = PM.plan(
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
    storage, db = PM.make_storage(), PM.make_db("write")
    md_dir = Path(a.out) / "publish" / "_md_tmp"
    try:
        with SP.span("load.publish", "load", cpu=True) as sp:  # op-01 — Object Storage 업로드 + EDW 쓰기 1행(대상 문서 수·결과 숫자)
            result = PM.apply(rows, storage, db, md_dir, prefix)
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
    report_path.write_text(PM.render_excluded_report(rows), encoding="utf-8")  # SI39⑥ — DRM·실패는 여기로만
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
    ap.add_argument("--parse-date", help="기본 오늘(YYYY-MM-DD, 또는 env PM_PARSE_DATE) — Object Storage 키의 날짜 폴더(SI39③)")
    ap.add_argument("--reparse", help="사람 조치 뒤 재파싱 대상 원본 키 목록 파일(한 줄에 하나, SI39③) — 새 날짜 폴더로, 옛 결과는 안 지움")
    ap.add_argument("--apply", action="store_true", help="실제 업로드 + EDW 쓰기(기본은 dry-run — 표만 출력, 쓰기 0)")
    a = ap.parse_args(argv)
    run(a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py publish가 PM_BUCKET_SKIP_OVERLAP_CHECK를 넘김)
    utf8_stdout()
    import sys

    from pipeline.shared import runtrace

    with runtrace.run("publish_parse_result", sys.argv[1:]):  # op-01 — 직접 실행이면 자기 run_id(부모가 이어줬으면 그대로)
        main()
