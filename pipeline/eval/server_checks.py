#!/usr/bin/env python3
"""서버 측정 묶음(server measurement pack) — 서버 대기 중인 파싱·색인 측정(AR1·AR6·T1)을 각각
한 명령으로 돌려 간단한 markdown/JSON 표를 낸다. 전부 읽기 전용(서버 데이터를 바꾸지 않음) · 결과는 output/ 아래에만
씀 · 새 유료 호출 없음(서버 내부 모델이 평소 돌던 경로 — 검색의 임베딩 호출 등 — 는 정상 동작이라 허용, VLM은
ar1만 --run-vlm 없이는 안 부름, 자세한 사유는 각 서브커맨드 설명 참고).
S5(10-26, T-15 — D-021 ④) — 검색 측정 br54·l8·gh114는 mcp_server/cli/search_checks.py로 옮김(파이프라인 도구가 검색 코드를
import하지 않게 — 결과 폴더 output/server_checks/<이름>은 그대로).

서브커맨드:
  ar1    조각 투표 계열(PARSE_FUSE·_SIGNALS·_REREAD·_REREAD_P3) 끄고 켬 — 사람 정답(GOLD_DIR) 기준 재채점.
         기존 엔진 결과(--parse-dir)를 복사해 다시 represent만 돈다(엔진 재실행 없음). P3는 그림 영역 VLM을 실제로
         부르므로 --run-vlm 없이는 그 VLM 호출 수 추정치만 찍고 baseline·PARSE_FUSE_SIGNALS_off는 건너뜀.
  ar6    기존 파싱 결과(_images/index.jsonl)에서 그림 종류별·문서 형식별 VLM 호출 수를 센다. 새 VLM 호출 없음.
         --ocr을 주면(선택, 로컬 OCR — VLM 아님) OCR 게이트(글자 수≥N·숫자 비율<0.30) 후보 비율도 같이 잰다.
  t1     PG 표본 청크의 chunk_term을 common.core.text.tokens로 다시 계산해 저장된 값과 비교(재색인 필요 여부).
         --bundle을 주면 그 번들의 head 포함 원문으로 더 정확히 비교(없으면 PG의 doc.file_name·client·chunk.section으로
         head를 재구성 — CHUNK_HEAD 끔이면 머리말 없음).

사용:
  python -m pipeline.eval.server_checks ar1 --gold /srv/rag/answer-key --parse-dir output/parse --src output/prepared [--max-docs 5] [--run-vlm]
  python -m pipeline.eval.server_checks ar6 --parse-dir output/parse --src output/prepared [--ocr]
  python -m pipeline.eval.server_checks t1 [--sample 200] [--bundle output/edw/bundle] [--pool]
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from common.config import settings as C  # common 칸(S7e1 — MCP_BUNDLE)
from common.core.paths import APP_ROOT, PKG_ROOT  # 런타임 output/(패키지 폴더 DEV 아님, v4 leftover 수정) · 엔진 구성(S2)
from pipeline import config as pc  # S7c — 설정 객체(pipeline 칸: GOLD_DIR·CHUNK_HEAD)

HERE = Path(__file__).resolve().parent  # deploy/pipeline/eval(S4 — 옛 deploy/common_tools/cli)
DEV = PKG_ROOT  # 하위 프로세스 cwd — deploy/common/(S6a — 옛 deploy/common_tools/와 같은 깊이)

OUT_BASE = APP_ROOT / "output" / "server_checks"


def _out_dir(name, override=None):
    d = Path(override) if override else (OUT_BASE / name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ───────────────────────── AR1 — 조각 투표 계열 끄고 켬(사람 정답 재채점) ─────────────────────────
AR1_SWITCH_KEYS = ("PARSE_FUSE", "PARSE_FUSE_SIGNALS", "PARSE_FUSE_REREAD", "PARSE_FUSE_REREAD_P3")
AR1_CONFIGS = [
    ("baseline", {}),
    ("PARSE_FUSE_off", {"PARSE_FUSE": "0"}),
    ("PARSE_FUSE_SIGNALS_off", {"PARSE_FUSE_SIGNALS": "0"}),
    ("PARSE_FUSE_REREAD_off", {"PARSE_FUSE_REREAD": "0"}),
    ("PARSE_FUSE_REREAD_P3_off", {"PARSE_FUSE_REREAD_P3": "0"}),
]
AR1_NO_P3_VLM = {"PARSE_FUSE_off", "PARSE_FUSE_REREAD_off", "PARSE_FUSE_REREAD_P3_off"}  # 이 설정들은 P3가 안 돎(실호출 없음)


def _build_engine_base(parse_dir, dest, max_docs=None):
    """parse_dir(엔진 원본 결과)에서 _rep·_images 등을 뺀 엔진별 결과만 dest에 복사 — --max-docs면 문서 수를 줄여 복사.
    반환: 복사한 문서 이름 목록(정렬)."""
    parse_dir = Path(parse_dir)
    runs = [json.loads(ln) for ln in (parse_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    docs = sorted({r["doc"] for r in runs})
    if max_docs:
        docs = docs[: int(max_docs)]
    docset = set(docs)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs if r["doc"] in docset), encoding="utf-8")
    for eng_dir in parse_dir.iterdir():
        if not eng_dir.is_dir() or eng_dir.name.startswith("_") or eng_dir.name == "raw":
            continue
        for f in eng_dir.glob("*.json"):
            if f.stem in docset:
                (dest / eng_dir.name).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest / eng_dir.name / f.name)
    return docs


def _run_represent(dev_root, stack_path, parse_dir, src_dir, env):
    cmd = [
        sys.executable,
        "-m",
        "pipeline.transform.represent.represent",
        "--stack",
        str(stack_path),
        "--parse-dir",
        str(parse_dir),
        "--src",
        str(src_dir),
    ]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=str(dev_root), env=env, capture_output=True, text=True)
    sec = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"represent.py 실패(rc={r.returncode}):\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return sec


def _run_score_gold(dev_root, gold_dir, parse_dir, src_dir, out_dir, env):
    cmd = [
        sys.executable,
        "-m",
        "pipeline.eval.score_gold",
        "--gold",
        str(gold_dir),
        "--parse",
        str(parse_dir),
        "--src",
        str(src_dir),
        "--out",
        str(out_dir),
        "--plain-names",
    ]
    r = subprocess.run(cmd, cwd=str(dev_root), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"score_gold.py 실패(rc={r.returncode}):\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads((out_dir / "score.json").read_text(encoding="utf-8"))


def _dry_p3_conflict_count(dev_root, stack_path, engine_base, src_dir, out_dir, represent_fn=_run_represent):
    """VLM_BASE_URL·VLM_MODEL을 잠깐 비우고 represent 1회(네트워크 호출 0, vlmgate.md 확인된 단락회로) —
    _rep/conflicts.jsonl 개수 = P3가 실제로 부를 그림 VLM 호출 수의 상한 추정(과대추정 쪽 — P2가 먼저 푸는 충돌도 셈)."""
    env = C.child_env(VLM_BASE_URL=None, VLM_MODEL=None)  # 하위 프로세스(represent) — 덮기 파일(S7e2, VLM_*는 엔진 키라 env에서도 지움)
    env["PYTHONUTF8"] = "1"
    dry_dir = out_dir / "_dry"
    if dry_dir.exists():
        shutil.rmtree(dry_dir)
    shutil.copytree(engine_base, dry_dir)
    try:
        represent_fn(dev_root, stack_path, dry_dir, src_dir, env)
        conf = dry_dir / "_rep" / "conflicts.jsonl"
        n = 0
        if conf.exists():
            for ln in conf.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    n += len(json.loads(ln).get("conflicts") or [])
        return n
    finally:
        shutil.rmtree(dry_dir, ignore_errors=True)


def _ar1_markdown(results, n_conflict_est, ran_vlm):
    L = [
        "# AR1 — 조각 투표 계열 끄고 켬(사람 정답 기준)",
        "",
        f"P3 VLM 호출 추정(드라이런, 네트워크 0회, 과대추정 쪽) ≈ **{n_conflict_est}건**"
        + ("" if ran_vlm else " · --run-vlm 없음 — P3 실호출 포함 설정(baseline·PARSE_FUSE_SIGNALS_off)은 건너뜀"),
        "",
        "| 설정 | value_recall | char_acc_post | table_cell_recall | num_halluc | represent 초 |",
        "|---|---|---|---|---|---|",
    ]
    base = (results.get("baseline") or {}).get("rep") or {}
    for name, r in results.items():
        rep = r.get("rep") or {}
        L.append(
            f"| {name} | {rep.get('value_recall', '—')} | {rep.get('char_acc_post', '—')} | "
            f"{rep.get('table_cell_recall', '—')} | {rep.get('num_halluc', '—')} | {r.get('represent_sec', '—')} |"
        )
    if base:
        L += ["", "## baseline 대비 문서별 value_recall 변화", "", "| 설정 | 문서 | baseline | 이 설정 | Δ |", "|---|---|---|---|---|"]
        base_docs = (results.get("baseline") or {}).get("docs") or {}
        for name, r in results.items():
            if name == "baseline":
                continue
            for doc, v in (r.get("docs") or {}).items():
                bv = base_docs.get(doc)
                if bv is None or v is None:
                    continue
                d = round(v - bv, 4)
                if d:
                    L.append(f"| {name} | {doc} | {bv} | {v} | {d:+.4f} |")
    return "\n".join(L) + "\n"


def _run_ar1(
    parse_dir,
    src_dir,
    gold_dir,
    out_dir,
    stack_path,
    max_docs,
    run_vlm,
    represent_fn=_run_represent,
    score_fn=_run_score_gold,
    conflict_fn=_dry_p3_conflict_count,
):
    docs = _build_engine_base(Path(parse_dir), out_dir / "engine_base", max_docs)
    print(f"[ar1] 대상 문서 {len(docs)}건(max_docs={max_docs or '전체'})")
    n_conflict = conflict_fn(DEV, stack_path, out_dir / "engine_base", src_dir, out_dir, represent_fn)
    print(f"[ar1] 예상 P3 VLM 호출 수(상한 추정) ≈ {n_conflict}건")
    configs = AR1_CONFIGS if run_vlm else [c for c in AR1_CONFIGS if c[0] in AR1_NO_P3_VLM]
    if not run_vlm:
        print("[ar1] --run-vlm 없음 — baseline·PARSE_FUSE_SIGNALS_off(P3 실호출 포함)는 건너뜀")
    results = {}
    for name, overrides in configs:
        cfg_dir = out_dir / f"cfg_{name}"
        if cfg_dir.exists():
            shutil.rmtree(cfg_dir)
        shutil.copytree(out_dir / "engine_base", cfg_dir)
        names = {**{k: None for k in AR1_SWITCH_KEYS}, **overrides, "PARSE_IMAGES_ROOT": str(cfg_dir / "_images")}
        env = C.child_env(**names)  # 하위 프로세스(represent·score_gold) — 덮기 파일(S7e2 — 옛 env 사본에 스위치 지움·덮기)
        env["PYTHONUTF8"] = "1"
        sec = represent_fn(DEV, stack_path, cfg_dir, src_dir, env)
        score_out = out_dir / f"gold_score_{name}"
        if score_out.exists():
            shutil.rmtree(score_out)
        score = score_fn(DEV, gold_dir, cfg_dir, src_dir, score_out, env)
        docs_rec = {doc: (d.get("rep") or {}).get("value_recall") for doc, d in score["docs"].items()}
        results[name] = {"rep": score.get("rep") or {}, "docs": docs_rec, "represent_sec": round(sec, 2)}
        print(f"[ar1] {name}: {results[name]['rep']} · {sec:.1f}s")
        shutil.rmtree(cfg_dir, ignore_errors=True)
    (out_dir / "ablation_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    md = _ar1_markdown(results, n_conflict, run_vlm)
    (out_dir / "ablation_report.md").write_text(md, encoding="utf-8")
    return results, md


def cmd_ar1(args):
    out_dir = _out_dir("ar1", args.out)
    gold = args.gold or pc.gold_dir()  # S7c — 설정 객체(S7e2 — 이미지 안 /data/gold 마운트 기본)
    if not gold:
        print("[ar1] --gold 필요(또는 환경변수 GOLD_DIR)", file=sys.stderr)
        return 2
    if args.stack:
        stack_path = Path(args.stack)
    else:  # S8b — 엔진 구성 활성 판의 사본(서버 = 판 표, PC = 파일)
        from pipeline import stackcfg

        stack_path = stackcfg.current(out_dir)[0]
    _results, md = _run_ar1(Path(args.parse_dir), Path(args.src), Path(gold), out_dir, stack_path, args.max_docs, args.run_vlm)
    print(md)
    return 0


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


def _ar6_p3_counts(parse_dir):
    p = Path(parse_dir) / "_rep" / "conflicts.jsonl"
    if not p.exists():
        return None
    n = 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            n += len(json.loads(ln).get("conflicts") or [])
    return n


def _ar6_markdown(report):
    L = [
        "# AR6 — VLM 호출 수(기존 파싱 결과 기준, 새 VLM 호출 없음)",
        "",
        f"그림 VLM 시도(실제 보낸 것만) {report['figure_attempts']}건 · 보내기 전 걸러짐(작음·중복·상한) {report['pre_vlm_skipped']}건 · "
        f"쪽 VLM 대상 쪽 {report.get('page_vlm_total', '—')}건 · P3 충돌(그림 영역 VLM 선택형) 추정 {report.get('p3_conflicts_estimate', '없음(사전 _rep 없음)')}건",
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
    report["p3_conflicts_estimate"] = _ar6_p3_counts(args.parse_dir)
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
    if not pc.cfg().transform.structure.chunk_head:  # S7c — 설정 객체(옛 env == "0"이면 끔)
        return ""
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

    p = sub.add_parser("ar1", help="조각 투표 계열 끄고 켬 — 사람 정답 재채점")
    _add_common(p, "ar1")
    p.add_argument("--parse-dir", default=str(APP_ROOT / "output" / "parse"))
    p.add_argument("--src", default=str(APP_ROOT / "output" / "prepared"))
    p.add_argument("--gold", default=pc.gold_dir())  # S7c — 설정 객체(S7e2 — 이미지 안 /data/gold 마운트 기본)
    p.add_argument("--stack", default=None)
    p.add_argument("--max-docs", type=int, default=None)
    p.add_argument("--run-vlm", action="store_true", help="P3 실 VLM 호출 포함 설정(baseline·PARSE_FUSE_SIGNALS_off)까지 실행")

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
    "ar1": cmd_ar1,
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
