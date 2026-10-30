#!/usr/bin/env python3
"""서버 측정 묶음(server measurement pack) — 서버 대기 중인 파싱·색인 측정(AR6·T1)을 각각
한 명령으로 돌려 간단한 markdown/JSON 표를 낸다. 전부 읽기 전용(서버 데이터를 바꾸지 않음) · 결과는 output/ 아래에만
씀 · 새 유료 호출 없음(서버 내부 모델이 평소 돌던 경로 — 검색의 임베딩 호출 등 — 는 정상 동작이라 허용, 자세한 사유는
각 서브커맨드 설명 참고).
S5(10-26, T-15 — D-021 ④) — 검색 측정 br54·l8·gh114는 mcp_server/cli/search_checks.py로 옮김(파이프라인 도구가 검색 코드를
import하지 않게 — 결과 폴더 output/server_checks/<이름>은 그대로).

서브커맨드:
  ar6    기존 파싱 결과(_images/index.jsonl)에서 그림 종류별·문서 형식별 VLM 호출 수를 센다. 새 VLM 호출 없음.
         --ocr을 주면(선택, 로컬 OCR — VLM 아님) OCR 게이트(글자 수≥N·숫자 비율<0.30) 후보 비율도 같이 잰다.
  t1     PG 표본 청크의 chunk_term을 common.core.text.tokens로 다시 계산해 저장된 값과 비교(재색인 필요 여부).
         --bundle을 주면 그 번들의 head 포함 원문으로 더 정확히 비교(없으면 PG의 doc.file_name·client·chunk.section으로
         head를 재구성).

사용:
  python -m pipeline.eval.server_checks ar6 --parse-dir output/parse --src output/prepared [--ocr]
  python -m pipeline.eval.server_checks t1 [--sample 200] [--bundle output/edw/bundle] [--pool]
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from common.config import settings as C  # common 칸(S7e1 — MCP_BUNDLE)
from common.core.paths import APP_ROOT, PKG_ROOT  # 런타임 output/(패키지 폴더 DEV 아님, v4 leftover 수정) · 엔진 구성(S2)

HERE = Path(__file__).resolve().parent  # deploy/pipeline/eval(S4 — 옛 deploy/common_tools/cli)
DEV = PKG_ROOT  # 하위 프로세스 cwd — deploy/common/(S6a — 옛 deploy/common_tools/와 같은 깊이)

OUT_BASE = APP_ROOT / "output" / "server_checks"


def _out_dir(name, override=None):
    d = Path(override) if override else (OUT_BASE / name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ───────────────────────── AR6 — 기존 파싱 결과에서 VLM 호출 수·OCR 게이트 ─────────────────────────
def _meaningful_chars(s):
    import re

    return len(re.findall(r"[0-9A-Za-z가-힣]", s or ""))


def _digit_share(s):
    import re

    m = _meaningful_chars(s)
    return (len(re.findall(r"[0-9]", s or "")) / m) if m else 0.0


def _ar6_counts(parse_dir, ocr_fn=None, min_chars=10, digit_max=0.30):
    idx_path = Path(parse_dir) / "_images" / "index.jsonl"
    rows = [json.loads(ln) for ln in idx_path.read_text(encoding="utf-8").splitlines() if ln.strip()] if idx_path.exists() else []
    attempted = [r for r in rows if not r.get("skipped")]
    by_kind = Counter((r.get("provenance") or {}).get("fig_kind") or "unknown" for r in attempted)
    by_fmt = Counter((Path(r.get("source_file") or "").suffix.lower() or "unknown") for r in attempted)
    gate_detail, gate_eligible = [], 0
    if ocr_fn:
        for r in attempted:
            if not r.get("png"):
                continue
            png_path = Path(parse_dir) / r["png"]
            if not png_path.exists():
                continue
            text = ocr_fn(png_path.read_bytes())
            mc, ds = _meaningful_chars(text), _digit_share(text)
            kind = (r.get("provenance") or {}).get("fig_kind")
            eligible = mc >= min_chars and ds < digit_max and kind not in ("chart", "flow")
            gate_detail.append(
                {
                    "doc": r["doc"],
                    "image_id": r["image_id"],
                    "meaningful_chars": mc,
                    "digit_share": round(ds, 3),
                    "fig_kind": kind,
                    "gate_would_skip": eligible,
                }
            )
            if eligible:
                gate_eligible += 1
    n = len(attempted)
    return {
        "docs": sorted({r["doc"] for r in rows}),
        "figure_attempts": n,
        "by_kind": dict(by_kind),
        "by_format": dict(by_fmt),
        "pre_vlm_skipped": len(rows) - n,
        "gate_checked": len(gate_detail),
        "gate_would_skip": gate_eligible,
        "gate_skip_share": round(gate_eligible / n, 4) if (ocr_fn and n) else None,
        "gate_detail": gate_detail,
    }


def _ar6_page_counts(src_dir, docs):
    """쪽 VLM 대상 쪽 수(vlm_page.page_targets — 순수 신호 함수, 모델 호출 없음) — src_dir에 원본이 있을 때만."""
    from pipeline.transform.figures import vlm_page as VP

    out = {}
    for doc in docs:
        p = Path(src_dir) / doc
        if not p.exists():
            continue
        try:
            out[doc] = len(VP.page_targets(str(p)))
        except Exception:
            continue
    return out


def _ar6_markdown(report):
    L = [
        "# AR6 — VLM 호출 수(기존 파싱 결과 기준, 새 VLM 호출 없음)",
        "",
        f"그림 VLM 시도(실제 보낸 것만) {report['figure_attempts']}건 · 보내기 전 걸러짐(작음·중복·상한) {report['pre_vlm_skipped']}건 · "
        f"쪽 VLM 대상 쪽 {report.get('page_vlm_total', '—')}건",
        "",
        "## 그림 종류별",
        "",
        "| 종류 | 건수 |",
        "|---|---|",
    ]
    for k, v in sorted(report["by_kind"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")
    L += ["", "## 문서 형식별", "", "| 형식 | 건수 |", "|---|---|"]
    for k, v in sorted(report["by_format"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")
    if report.get("gate_checked"):
        L += [
            "",
            f"## OCR 게이트(글자≥N·숫자 비율<0.30·차트/흐름 제외) — {report['gate_checked']}건 중 생략 가능 {report['gate_would_skip']}건"
            f"({report['gate_skip_share']})",
            "",
            "| 문서 | 그림 | 의미 글자 | 숫자 비율 | 종류 | 생략 가능 |",
            "|---|---|---|---|---|---|",
        ]
        for g in report["gate_detail"]:
            L.append(
                f"| {g['doc']} | {g['image_id']} | {g['meaningful_chars']} | {g['digit_share']} | {g['fig_kind']} | {'예' if g['gate_would_skip'] else '아니오'} |"
            )
    return "\n".join(L) + "\n"


def cmd_ar6(args):
    report = _ar6_counts(
        Path(args.parse_dir), ocr_fn=_crop_ocr_lazy() if args.ocr else None, min_chars=args.min_chars, digit_max=args.digit_max
    )
    if args.src:
        page = _ar6_page_counts(Path(args.src), report["docs"])
        report["page_vlm_by_doc"], report["page_vlm_total"] = page, sum(page.values())
    out_dir = _out_dir("ar6", args.out)
    (out_dir / "ar6_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = _ar6_markdown(report)
    (out_dir / "ar6_report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def _crop_ocr_lazy():
    from pipeline.transform.figures.figures import _crop_ocr

    return _crop_ocr


# ───────────────────────── T1 — 재색인 검증 ─────────────────────────
def _reconstruct_head(file_name, client, section):
    parts = [x for x in (Path(file_name).stem, client, section) if x]
    return "[" + " · ".join(parts) + "]" if parts else ""


def _index_text_from_pg_row(row):
    head = _reconstruct_head(row["file_name"], row.get("client"), row.get("section"))
    text = row.get("chunk_text") or ""
    return (head + "\n" + text) if head else text


def cmd_t1(args, db_factory=None):
    from common.core.contract import jl
    from common.core.text import index_text, tokens
    from common.store import pg as PGC

    db = (db_factory or (lambda: PGC.PGPool(PGC.conf()) if args.pool else PGC.PG(PGC.conf())))()
    s = db.schema
    rows = db.q(
        f"SELECT c.chunk_id, c.chunk_text, c.section, c.seq, d.file_name, d.client, d.file_sha256 "
        f"FROM {s}.chunk c JOIN {s}.doc d ON d.doc_id=c.doc_id ORDER BY random() LIMIT %s",
        (args.sample,),
    )
    bundle_by_key = {}
    bundle = args.bundle or C.cfg().paths.mcp_bundle  # S7e1 — common 칸(두 앱이 읽음 — 옛 mcp 절 env 읽기, 사용자 Q9)
    if bundle and Path(bundle).exists():
        B = Path(bundle)
        chunks, docs = jl(B / "chunks.jsonl"), jl(B / "docs.jsonl")
        for c in chunks:
            bundle_by_key[f"{docs[c['doc']]['file_sha256']}:{c['seq']}"] = c
    mism, checked, bundle_hits, detail = 0, 0, 0, []
    for r in rows:
        key = f"{r['file_sha256']}:{r['seq']}"
        bc = bundle_by_key.get(key)
        text = index_text(bc) if bc is not None else _index_text_from_pg_row(r)
        if bc is not None:
            bundle_hits += 1
        want = dict(Counter(tokens(text)))
        got = {row["term"]: row["tf"] for row in db.q(f"SELECT term, tf FROM {s}.chunk_term WHERE chunk_id=%s", (r["chunk_id"],))}
        checked += 1
        if want != got:
            mism += 1
            detail.append(r["chunk_id"])
    rate = round(mism / checked, 4) if checked else None
    print(f"[t1] 표본 {checked}건(번들 대조 {bundle_hits}건) · 불일치 {mism}건 · 불일치율 {rate}")
    if mism:
        print("[t1] 불일치 > 0 — BM25_STAT_REBUILD=1 python cli/pipeline.py load --replace 아직 필요(T1 백로그)")
    out_dir = _out_dir("t1", args.out)
    (out_dir / "t1_report.json").write_text(
        json.dumps(
            {"checked": checked, "bundle_hits": bundle_hits, "mismatch": mism, "mismatch_rate": rate, "mismatch_chunk_ids": detail},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return 1 if mism else 0


# ───────────────────────── argparse 뼈대 ─────────────────────────
def _add_common(p, name):
    p.add_argument("--out", default=None, help=f"결과 폴더(기본 output/server_checks/{name})")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("ar6", help="기존 파싱 결과의 그림 VLM 호출 수·OCR 게이트")
    _add_common(p, "ar6")
    p.add_argument("--parse-dir", default=str(APP_ROOT / "output" / "parse"))
    p.add_argument("--src", default=None, help="쪽 VLM 대상 수도 보려면 원본 폴더(선택)")
    p.add_argument("--ocr", action="store_true", help="로컬 크롭 OCR을 다시 돌려 글자수·숫자 비율 게이트까지 잰다(VLM 아님, 선택)")
    p.add_argument("--min-chars", type=int, default=10)
    p.add_argument("--digit-max", type=float, default=0.30)

    p = sub.add_parser("t1", help="PG 재색인 검증(chunk_term)")
    _add_common(p, "t1")
    p.add_argument("--sample", type=int, default=200)
    p.add_argument("--bundle", default=None, help="기본 MCP_BUNDLE — 있으면 PG 재구성 대신 번들 head로 정확히 비교")
    p.add_argument("--pool", action="store_true")

    return ap


SUBCOMMANDS = {
    "ar6": cmd_ar6,
    "t1": cmd_t1,
}


def main(argv=None):
    utf8_stdout()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 1
    func = SUBCOMMANDS[args.cmd]
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
