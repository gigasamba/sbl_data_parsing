#!/usr/bin/env python3
"""검색 측정 묶음 — 서버 대기 중인 검색 쪽 측정(BR54·L8·GH1-14 ef_search)을 각각 한 명령으로 돌려 간단한 markdown/JSON 표를 낸다.
S5(10-26, T-15 — D-021 ④)에 pipeline/eval/server_checks.py(서버 측정 묶음)에서 검색 측정만 옮김(함수 내용 그대로 — 파싱·색인 측정
ar1·ar6·t1은 그 파일에 남음). 전부 읽기 전용(서버 데이터를 바꾸지 않음) · 결과는 output/server_checks/<이름>/ 아래에만(옛 자리 그대로) ·
새 유료 호출 없음(검색의 임베딩 호출 등 서버가 평소 돌던 경로는 허용).

서브커맨드:
  br54   질문 목록으로 do_search를 운영 k로 돌려 — 문서별 상위5 등장 빈도(허브) · 허브 문서 상위 20 · 정답 문서가
         허브에 밀렸는지(정답 있을 때만).
  l8     MCP 서버에 올바른 Host+토큰 · 잘못된 Host · 외부 Origin으로 요청 — 200대/421/403 확인(urllib만, 토큰은
         환경변수 MCP_TOKEN에서 읽고 절대 출력하지 않음).
  gh114  PG 모드에서 벡터 질의 스코프(SET LOCAL + 같은 트랜잭션) 안에서 SHOW hnsw.ef_search로 GH1-14 반영 확인.

공통: 서브커맨드마다 --selftest(서버 없이 가짜 데이터로 돌아감). 전체 선택: `python -m mcp_server.cli.search_checks --selftest`.

사용(이미지 안은 `tool search_checks …` — retrieval 이미지):
  python -m mcp_server.cli.search_checks br54 --questions <질문.json> [--k 8] [--threshold 0.3]
  python -m mcp_server.cli.search_checks l8 --url http://<호스트>:8765/mcp
  python -m mcp_server.cli.search_checks gh114 [--ef-search 150] [--pool]
  python -m mcp_server.cli.search_checks --selftest   (또는 각 서브커맨드 뒤에 --selftest)
"""

import common  # noqa: F401 — 영구 다리(엔진·인계 칸 → env, settings.pin_env)를 첫 줄에서(S7e2 — 옛 옵션 카탈로그 채우기 자리)
from common.core.console import utf8_stdout

# isort: split
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from common.core.paths import APP_ROOT  # 런타임 output/
from mcp_server import config as mc  # 설정 객체(S7d)

OUT_BASE = APP_ROOT / "output" / "server_checks"  # 옛 server_checks.py와 같은 자리(output/server_checks/<이름>)


def _out_dir(name, override=None):
    d = Path(override) if override else (OUT_BASE / name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ───────────────────────── BR54 — 허브 문서 쏠림 ─────────────────────────
def _load_questions(path):
    """일반 질문 목록(id·question·gold_docs) 또는 qa.json 스키마({"items":[...]})를 읽는다 — evidence의
    doc·file_name·doc_id를 정답 문서 후보로(수동 doc_id→파일명 매핑이 필요한 세트(예 synth-4clients manifest)는
    이 간이 로더로 못 풀 수 있음 — 그런 세트는 --questions에 이미 file_name으로 푼 사본을 준다)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    items = d.get("items") if isinstance(d, dict) else d
    out = []
    for i, it in enumerate(items):
        gold = set(it.get("gold_docs") or [])
        for e in it.get("evidence") or []:
            for k in ("doc", "file_name", "doc_id"):
                if e.get(k):
                    gold.add(e[k])
        out.append({"id": it.get("id") or str(i + 1), "question": it["question"], "gold_docs": gold or None})
    return out


def _br54_aggregate(records, threshold):
    n = len(records)
    hub = Counter()
    for rec in records:
        for fn in set(rec["top"][:5]):
            hub[fn] += 1
    flagged = {fn for fn, c in hub.items() if n and (c / n) > threshold}
    displaced = []
    for rec in records:
        top5 = set(rec["top"][:5])
        gold = rec.get("gold")
        if gold and not (gold & top5) and (top5 & flagged):
            displaced.append(
                {"id": rec["id"], "question": rec["question"][:120], "hub_in_top5": sorted(top5 & flagged), "gold": sorted(gold)}
            )
    top20 = sorted(hub.items(), key=lambda kv: -kv[1])[:20]
    return {"n_questions": n, "hub_top20": top20, "flagged_hubs": sorted(flagged), "displaced": displaced}


def _chunk_counts(R, file_names):
    file_names = set(file_names)
    if not file_names:
        return {}
    if R.pg:
        s = R.pg.schema
        rows = R.pg.q(
            f"SELECT d.file_name, COUNT(*) n FROM {s}.chunk c JOIN {s}.doc d ON d.doc_id=c.doc_id "
            f"WHERE d.file_name = ANY(%s) GROUP BY d.file_name",
            (sorted(file_names),),
        )
        return {r["file_name"]: r["n"] for r in rows}
    c = Counter()
    for ch in R.local.chunks:
        fn = R.local.docs[ch["doc"]].get("file_name")
        if fn in file_names:
            c[fn] += 1
    return dict(c)


def _br54_markdown(agg, chunk_counts, threshold):
    L = [
        "# BR54 — 허브 문서 쏠림",
        "",
        f"질문 {agg['n_questions']}건 · 상위5 등장 비율 > {threshold} 허브 {len(agg['flagged_hubs'])}건 · "
        f"정답이 허브에 밀린 질문 {len(agg['displaced'])}건",
        "",
        "## 상위 20 허브",
        "",
        "| 문서 | 상위5 등장 횟수 | 등장 비율 | 청크 수 | 허브 판정 |",
        "|---|---|---|---|---|",
    ]
    n = agg["n_questions"] or 1
    for fn, c in agg["hub_top20"]:
        L.append(f"| {fn} | {c} | {round(c / n, 3)} | {chunk_counts.get(fn, '—')} | {'예' if fn in agg['flagged_hubs'] else '아니오'} |")
    if agg["displaced"]:
        L += ["", "## 정답 문서가 허브에 밀린 질문", "", "| id | 질문 | 허브(상위5 안) | 정답 |", "|---|---|---|---|"]
        for d in agg["displaced"]:
            L.append(f"| {d['id']} | {d['question']} | {', '.join(d['hub_in_top5'])} | {', '.join(d['gold'])} |")
    return "\n".join(L) + "\n"


def cmd_br54(args, search_fn=None):
    items = _load_questions(args.questions)
    if args.max_q:
        items = items[: args.max_q]
    from mcp_server.services.search import search_svc as M  # S5 — do_search·_STATE(옛 mcp_server.py)
    from mcp_server.services.search import server_state as ST

    sfn = search_fn or (lambda q, k: M.do_search(q, k=k, methods=["vector", "bm25", "id"], decompose=False))
    records = []
    for it in items:
        res = sfn(it["question"], args.k)
        top = [e.get("file_name") for e in (res.get("evidence") or []) if e.get("file_name")]
        records.append({"id": it["id"], "question": it["question"], "top": top, "gold": it.get("gold_docs")})
    agg = _br54_aggregate(records, args.threshold)
    chunk_counts = {}
    if search_fn is None:
        R = ST._STATE.get("R")
        if R is not None:
            chunk_counts = _chunk_counts(R, [fn for fn, _ in agg["hub_top20"]])
    out_dir = _out_dir("br54", args.out)
    (out_dir / "hub_report.json").write_text(
        json.dumps({**agg, "chunk_counts": chunk_counts}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md = _br54_markdown(agg, chunk_counts, args.threshold)
    (out_dir / "hub_report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


# ───────────────────────── L8 — MCP 전송 보안(Host/Origin) ─────────────────────────
def _interpret_l8(ok_status, wrong_host_status, foreign_origin_status):
    return {
        "ok": ok_status not in (401, 403, 421),
        "wrong_host_rejected": wrong_host_status == 421,
        "foreign_origin_rejected": foreign_origin_status == 403,
        "ok_status": ok_status,
        "wrong_host_status": wrong_host_status,
        "foreign_origin_status": foreign_origin_status,
    }


def cmd_l8(args):
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    token = mc.token_text(mc.cfg().server.token)  # 절대 출력하지 않음(R1) · 공백뿐인 토큰 = 토큰 없음(사용자 결정 10-27)
    netloc = urlsplit(args.url).netloc
    body = b'{"jsonrpc":"2.0"}'

    def post(extra_headers):
        req = urllib.request.Request(args.url, data=body, method="POST", headers={"Content-Type": "application/json", **extra_headers})
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:
            return f"요청 실패: {type(e).__name__}"

    auth = {"Authorization": f"Bearer {token}"} if token else {}
    ok = post({**auth, "Host": netloc})
    wrong_host = post({**auth, "Host": "evil.example:9999"})
    foreign_origin = post({**auth, "Host": netloc, "Origin": "http://evil.example"})
    report = _interpret_l8(ok, wrong_host, foreign_origin)
    if not token:
        report["warning"] = "MCP_TOKEN env 없음 — 루프백 밖이면 401이 날 수 있음"
    out_dir = _out_dir("l8", args.out)
    (out_dir / "l8_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[l8] 정상 Host+토큰: {ok} · 잘못된 Host: {wrong_host}(421 기대) · 외부 Origin: {foreign_origin}(403 기대)")
    print(
        f"[l8] 판정: ok={report['ok']} · wrong_host_rejected={report['wrong_host_rejected']} · foreign_origin_rejected={report['foreign_origin_rejected']}"
    )
    return 0 if (report["ok"] and report["wrong_host_rejected"] and report["foreign_origin_rejected"]) else 1


# ───────────────────────── GH1-14 — PG hnsw.ef_search SET LOCAL 확인 ─────────────────────────
def cmd_gh114(args, db_factory=None):
    from common.store import pg as PGC

    db = (db_factory or (lambda: PGC.PGPool(PGC.conf()) if args.pool else PGC.PG(PGC.conf())))()
    with db.scope() as c:
        c.q(f"SET LOCAL hnsw.ef_search = {int(args.ef_search)}")
        rows = c.q("SHOW hnsw.ef_search")
    shown = rows[0] if rows else {}
    val = next(iter(shown.values()), None) if shown else None
    ok = str(val) == str(args.ef_search)
    print(f"[gh114] SET LOCAL hnsw.ef_search={args.ef_search} → SHOW 결과: {shown} · 일치: {'예' if ok else '아니오'}")
    out_dir = _out_dir("gh114", args.out)
    (out_dir / "gh114_report.json").write_text(
        json.dumps({"set": args.ef_search, "shown": shown, "match": ok}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0 if ok else 1


# ───────────────────────── argparse 뼈대 ─────────────────────────
def _add_common(p, name):
    p.add_argument("--out", default=None, help=f"결과 폴더(기본 output/server_checks/{name})")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("br54", help="허브 문서 쏠림")
    _add_common(p, "br54")
    p.add_argument("--questions", default=None)
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--max-q", type=int, default=None)
    p.add_argument("--threshold", type=float, default=0.3)

    p = sub.add_parser("l8", help="MCP Host/Origin 전송 보안 확인")
    _add_common(p, "l8")
    p.add_argument("--url", default=None)
    p.add_argument("--timeout", type=float, default=10)

    p = sub.add_parser("gh114", help="PG hnsw.ef_search SET LOCAL 확인")
    _add_common(p, "gh114")
    p.add_argument("--ef-search", type=int, default=150)
    p.add_argument("--pool", action="store_true")

    return ap


SUBCOMMANDS = {
    "br54": cmd_br54,
    "l8": cmd_l8,
    "gh114": cmd_gh114,
}


def main(argv=None):
    utf8_stdout()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 1
    func = SUBCOMMANDS[args.cmd]
    if args.cmd == "br54" and not args.questions:
        ap.error("--questions 필요")
    if args.cmd == "l8" and not args.url:
        ap.error("--url 필요")
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
