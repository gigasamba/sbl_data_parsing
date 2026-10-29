#!/usr/bin/env python3
"""SI39 — 파싱이 끝난 뒤 별도로: 대표 결과(.md)를 Object Storage에 올리고 EDW `AI.ParsingMeta`에 행을 기록한다.
**맨 마지막 별도 단계**(설계 docs/architecture.md) — 앞 단계(파싱·구조화·적재·검색)는 Object
Storage·EDW를 **읽기만** 한다. 공용 로직은 modules/load/parsing_meta.py(이 CLI는 그 모듈의 함수만 부른다).

요건(SI39, 사용자 10-08 — backlog/server.md SI39): ① 올리는 것은 **대표 결과(.md)**, 원본 파일은 올리지 않는다
(원천 원본은 읽기만, 수정·삭제 금지) ② 겹침/건너뜀 키 = (source_system, 원본 전체 키) ③ Object Storage 키는
항상 `<PM_PREFIX>/<source_system 또는 PM_PATH_MAP 새 앞부분>/<원본 폴더>/<파일명>/<파일명>_<parse_date>.md`(사용자 10-14) — 이미 있으면 건너뜀, `--reparse`로 명시한
키만 새 날짜 폴더(옛 결과 안 덮음) ④ EDW는 INSERT만 + 상태 열(status·status_at)만 UPDATE 허용(`parsing_meta.
update_status()`) ⑤ PM_BUCKET이 원천 원본 버킷과 같으면 거부 ⑥ DRM·파싱 실패는 EDW에 안 넣고
`output/publish/excluded_<날짜>.md` 보고서로만.

OP1/OP9(원천 변경·삭제 탐지, --apply일 때만) — 문서 대장(AD16, common/registry.py)을 같이 갱신해 changed·deleted·
touched(AD17①, 원본 바이트는 같고 날짜만 바뀜) doc_key를 `parsing_meta.apply_registry_status()`로 EDW status
UPDATE(changed·deleted는 status 값 자체를 바꿈 · touched는 status 값은 그대로 두고 status_at만 — active는 안
건드림, 그 밖 UPDATE 없음). deleted는 문서 대장이 자동으로 검색에서 숨김(색인 행 삭제 아님, `cli/registry.py
unhide`로 되돌릴 수 있음) · changed는 보고만(`output/registry/report.md` — 사람이 `--reparse`로 명시하기 전까지
재파싱하지 않음, 옛 내용 그대로 검색됨) · touched는 재파싱·새 판·변경 보고 모두 제외(report.md엔 건수만, 목록
없음 — 파싱 결과끼리 비교하는 '판' 단위 작업(AD17②·D10)은 범위 밖·다음 단계). 문서 대장을 못 열면
(DOC_REGISTRY=0·DB 없음) 조용히 건너뜀 — 게시 자체는 그대로 진행(전과 동일).

사용(기본 --out의 하위 경로를 그대로 — pipeline.py와 같은 레이아웃):
  python cli/publish_parse.py [--out out] [--source-system FileStorageMap] [--version <판>] [--parse-date <날짜>]
                              [--reparse <키 목록 파일>] [--apply]
  기본은 **dry-run**(무엇을 올리고 쓸지 표만 출력, 실제 업로드·EDW 쓰기 0) — 실제로 쓰려면 --apply 명시.

env(전부 PM1 결정 대기 — 사람, docs/operations/server-guide.md 단계 6):
  PM_TABLE(기본 AI.ParsingMeta) · PM_BUCKET(업로드 버킷 — "file://<폴더>"면 로컬 폴더를 가짜 Object Storage로) ·
  PM_PREFIX(버킷 안 경로 접두, 선택) · PM_DB_HOST·PM_DB_PORT(1433)·PM_DB_DATABASE·PM_DB_USER·PM_DB_PASSWORD
  (EDW 쓰기 전용 계정 — RDB_* 읽기 계정과 분리) · PM_DB_SQLITE(설정하면 SQLite를 가짜 EDW로, PM_DB_* 안 봄) ·
  OS_ENDPOINT·OS_ACCESS_KEY·OS_SECRET_KEY·OS_REGION·OS_VERIFY_TLS(업로드 접속 — source.py·os_put.py와 같음) ·
  PM_UPLOAD_STATUSES(콤마 목록, 기본 "ok,partial"만 올림) · PM_PARSE_DATE(--parse-date 대신 env로, 선택).
원본 로컬 보존·즉시 삭제는 이제 modules/parse/source.py(SI39⑧ — 파싱이 끝나면 바로 지움, KEEP_LOCAL_ORIGINALS=1만
디버그 보존)가 맡는다 — 이 CLI는 원본 삭제를 하지 않는다(올리지도 않으므로, SI37 때와 달리 X2 책임이 없음).
DDL은 이 코드가 실행하지 않는다(설계 §2 초안 — 사람이 만듦). SQL은 식별자 화이트리스트·값 바인딩(AD44 관례),
비밀값(PM_DB_PASSWORD 등)은 어떤 모드에서도 출력하지 않는다.
"""

import argparse
import json
from pathlib import Path

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
    skipped = Path(skipped) if skipped else out / "prepared" / "skipped.jsonl"
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
    storage, db = PM.make_storage(), PM.make_db()
    md_dir = Path(a.out) / "publish" / "_md_tmp"
    try:
        result = PM.apply(rows, storage, db, md_dir, prefix)
        out["registry_status_update"] = _apply_registry_status(a.out, db)  # OP1/OP9 — changed·deleted만 status UPDATE(아래)
    finally:
        if hasattr(db, "close"):
            db.close()
    out["result"] = result
    report_dir = Path(a.out) / "publish"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"excluded_{parse_date}.md"
    report_path.write_text(PM.render_excluded_report(rows), encoding="utf-8")  # SI39⑥ — DRM·실패는 여기로만
    out["excluded_report"] = str(report_path)
    if out["registry_status_update"].get("changed_report"):
        out["changed_report"] = out["registry_status_update"].pop("changed_report")
    print(json.dumps(out, ensure_ascii=False))
    return out


def _apply_registry_status(out_dir, db):
    """OP1/OP9 — publish --apply에서만: 문서 대장을 갱신(scan·diff·apply — deleted는 apply()가 자동 hide, OP1)하고
    changed·deleted·touched(AD17①) doc_key의 EDW status UPDATE(PM.apply_registry_status, update_status()만 씀 —
    touched는 status 값은 그대로, status_at만). changed는 report.md로만(재파싱 안 함, OP1) — output/registry/report.md에
    이번 build의 new/touched/changed/deleted 요약(touched는 건수만, 목록 없음).
    문서 대장을 못 열면(DOC_REGISTRY=0·DB 없음·그 밖 오류) 조용히 건너뜀(게시 자체는 막지 않음 — 전과 동일)."""
    from common.store import registry as REG

    reg_db = REG.try_open_db()
    if reg_db is None:
        return {"changed": 0, "deleted": 0, "skipped": 0, "note": "문서 대장 사용 안 함(DOC_REGISTRY=0 또는 연결 안 됨)"}
    try:
        from common.store.db import dbtool
        from common.store.structdb import ensure_registry_schema

        dbtool.require_struct(reg_db)  # S8a — 판 확인(낮거나 모르는 판은 StructDBError → 아래에서 문서 대장만 건너뜀, 게시는 계속)
        ensure_registry_schema(reg_db)
        diff, build_id = REG.build(out_dir, reg_db)
        counts = PM.apply_registry_status(db, diff)
        report_path = Path(out_dir) / "registry" / "report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            f"# 문서 대장 build {build_id}\n\n"
            f"- 새 문서 {len(diff['new'])}건 · **날짜만 바뀜(touched, 원본 바이트는 같음 — 재파싱·새 판·변경 보고 제외) "
            f"{len(diff.get('touched') or [])}건** · **바뀜(보고만, 재파싱 안 함) {len(diff['changed'])}건** · "
            f"**삭제(검색에서 숨김) {len(diff['deleted'])}건** · 그대로 {len(diff['unchanged'])}건\n\n"
            + (
                "## 바뀜(changed) — 사람 조치 뒤 재파싱 전까지 옛 내용 그대로 서빙\n"
                + "\n".join(f"- {k}" for k in diff["changed"])
                + "\n\n"
                if diff["changed"]
                else ""
            )
            + (
                "## 삭제(deleted) — 검색에서 숨김(색인 행 삭제 아님, cli/registry.py unhide로 되돌릴 수 있음)\n"
                + "\n".join(f"- {k}" for k in diff["deleted"])
                + "\n"
                if diff["deleted"]
                else ""
            ),
            encoding="utf-8",
        )
        counts["changed_report"] = str(report_path)
        return counts
    except Exception as ex:
        return {
            "changed": 0,
            "deleted": 0,
            "skipped": 0,
            "note": f"문서 대장 갱신 실패 — EDW 상태 갱신 건너뜀: {type(ex).__name__}: {str(ex)[:160]}",
        }
    finally:
        reg_db.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "output"))
    ap.add_argument("--manifest", help="기본 <out>/parse/_source/manifest.jsonl")
    ap.add_argument("--source-dir", help="기본 <out>/_source_files")
    ap.add_argument("--rep", help="기본 <out>/parse/_rep/index.json")
    ap.add_argument("--summary", help="기본 <out>/parse/parse_summary.json")
    ap.add_argument("--skipped", help="기본 <out>/prepared/skipped.jsonl(DRM·암호 — 없으면 무시)")
    ap.add_argument("--keep", help="기본 <out>/dedup/keep.txt(중복 제외 — 없으면 dedup 정보 없음으로 전부 포함)")
    ap.add_argument(
        "--source-system",
        default="FileStorageMap",
        help="SI41 — manifest 행이 source_system을 들고 있으면(rdb:*·rdb:<이름>) 그 값을 쓰고, 이 값은 "
        "폴백(레거시 단일 표 소스)에만 쓰인다",
    )
    ap.add_argument("--version", help="기본 저장소 루트 VERSION(오버레이 패치면 PATCH_VERSION — common.pipeline_version, D-036)")
    ap.add_argument("--parse-date", help="기본 오늘(YYYY-MM-DD, 또는 env PM_PARSE_DATE) — Object Storage 키의 날짜 폴더(SI39③)")
    ap.add_argument("--reparse", help="사람 조치 뒤 재파싱 대상 원본 키 목록 파일(한 줄에 하나, SI39③) — 새 날짜 폴더로, 옛 결과는 안 지움")
    ap.add_argument("--apply", action="store_true", help="실제 업로드 + EDW 쓰기(기본은 dry-run — 표만 출력, 쓰기 0)")
    a = ap.parse_args(argv)
    run(a)


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A — 호스트 run_docs.py publish가 PM_BUCKET_SKIP_OVERLAP_CHECK를 넘김)
    utf8_stdout()
    main()
