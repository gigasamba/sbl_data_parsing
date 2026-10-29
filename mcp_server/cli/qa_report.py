#!/usr/bin/env python3
"""Q&A 결과 보고서(qa_report) — answer_stage(실제 LLM이 낸 답)와 선택적으로 mcp_eval(검색 근거)의 기존 산출물을
사람이 읽을 수 있는 HTML 한 장 + xlsx 한 장으로 렌더링한다. LLM 호출 0회 — 이미 있는 결과만 읽는다.
정본·열 순서·용어 정의는 docs/testing.md(바꾸면 거기도 같이 갱신).

읽는 것:
  --rows   dev_tools/perform_test/answer_stage/run.py가 쓴 answer_stage_<tag>_rows.json(필수) — 문항별 question·gold_docs·
           files5·answer·cls(OK/A-MISS/A-ABSTAIN/R-MISS/UNSCORED/REVIEW, 정의는 그 스크립트 머리말이 유일한 기준).
  --mcp-eval  (선택) 같은 질문 세트의 cli/mcp_eval.py 산출 json — (데이터셋,문항ID)로 조인해 검색 hit@1/5만 판정 칸에
           덧붙인다(없으면 그 칸은 비움, 오류 아님).
  --eval-sets-root  (선택, 기본 valid_env/unstructured) — qa.json에서 정답 텍스트(gold_answer/answer_keywords)를 찾아
           "정답" 칸에 보여준다(best-effort — 못 찾으면 "—", 채점 자체는 rows의 cls를 그대로 씀).

산출(쓰기는 --out 아래만):
  <out>/report/qa_report_<tag>.html  — 외부 자원 0(폰트·스크립트 전부 인라인). 요약(전체·세트별·유형별 분류 비율) +
      문항별 표(질문·정답·LLM 답변·판정·근거 문서 top5(정답 ★)·인용 문서) — 오답(A-MISS)·기권(A-ABSTAIN) 먼저.
  <out>/report/qa_report_<tag>.xlsx  — 같은 열, 줄바꿈·열 너비·맨 위 줄 고정·필터(openpyxl 없으면 건너뜀 — 경고만).
문서 이름은 기본 해시(doc-xxxxxxxx, cli/run_board.py와 같은 규칙) — --plain-names면 원래 이름(실데이터 반출 주의).

사용:
  python cli/qa_report.py --rows output/eval/answer_stage/answer_stage_real_rows.json
  python cli/qa_report.py --rows <rows.json> --mcp-eval output/eval/mcp_eval/<ts>_<set>.json --plain-names
  python cli/qa_report.py --selftest
"""

import argparse
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent  # dev/cli
DEV = HERE.parent
ROOT = DEV.parent
EVAL_SETS_DEFAULT = ROOT / "valid_env" / "unstructured"

# 분류 순서(사람이 먼저 봐야 할 것부터) · 정의는 answer_stage/run.py 머리말이 유일한 기준 — 여기서는 표시용 한국어 설명만.
CLS_ORDER = ["A-MISS", "A-ABSTAIN", "REVIEW", "R-MISS", "UNSCORED", "OK"]
CLS_LABEL = {
    "A-MISS": "오답(근거는 상위5에 있었음)",
    "A-ABSTAIN": "기권(모른다고 답)",
    "REVIEW": "판정 보류(비교 결론 불명 — 사람 확인)",
    "R-MISS": "검색 실패(정답 문서가 상위5에 없음 — LLM 안 부름)",
    "UNSCORED": "채점 불가(표 전체 정답 등 — 사람 확인)",
    "OK": "정답",
}
_CITE_RE = re.compile(r"\[(\d+)\]")


def name_fn(plain):
    """문서 이름 표시 함수 — cli/run_board.py의 해시 규칙과 같음(doc-xxxxxxxx)."""
    if plain:
        return lambda x: x
    return lambda x: "doc-" + hashlib.sha256(str(x).encode()).hexdigest()[:8]


def load_rows(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_mcp_index(path):
    """(dataset, 문항ID) -> {"hit1":…, "hit5":…} — path 없으면 빈 dict(조인 생략, 오류 아님)."""
    if not path:
        return {}
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for ds, entry in (report.get("sets") or {}).items():
        for r in entry.get("rows") or []:
            if r.get("id"):
                out[(ds, r["id"])] = {"hit1": r.get("hit1"), "hit5": r.get("hit5")}
    return out


def load_qa_raw(eval_sets_root):
    """dataset -> {문항ID -> qa.json 원본 항목}로 캐시해 돌려주는 조회 함수 — 파일 없거나 깨졌으면 빈 dict(정답 텍스트는
    "—"로만 보임, 채점 자체는 영향 없음 — best-effort 보강이라 예외를 밖으로 던지지 않는다)."""
    cache = {}

    def get(dataset):
        if dataset in cache:
            return cache[dataset]
        out = {}
        p = Path(eval_sets_root) / str(dataset) / "qa.json"
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                items = d.get("items") if isinstance(d, dict) else d
                out = {it["id"]: it for it in (items or []) if it.get("id")}
            except (OSError, ValueError):
                out = {}
        cache[dataset] = out
        return out

    return get


def gold_answer_text(item):
    """qa.json 원본 항목 → 정답 표시 글자(best-effort). gold_answer 우선 · 없으면 answer_keywords(그 중 하나로 채점) ·
    gold_table이면 표 전체라 안내만 · 아무 것도 없으면 None(UNSCORED로 이어지는 문항 — 사람이 qa.json을 직접 봐야 함)."""
    if not item:
        return None
    if item.get("gold_answer") is not None:
        return str(item["gold_answer"])
    kw = item.get("answer_keywords")
    if kw:
        return "그 중 하나: " + " | ".join(str(k) for k in kw)
    if item.get("gold_table"):
        return "[표 정답 — qa.json의 gold_table 참고]"
    return None


def cited_files(answer, files5):
    """답변 글자의 [n] 인용 → files5[n-1](중복 없이, 순서대로) — answer_stage/run.py classify()의 인용 추출과 같은 규칙."""
    out = []
    for n in _CITE_RE.findall(answer or ""):
        i = int(n)
        if 1 <= i <= len(files5) and files5[i - 1] and files5[i - 1] not in out:
            out.append(files5[i - 1])
    return out


def verdict_text(row, mcp_hit=None):
    """분류 + 사람이 읽을 사유 한 줄(subcause·error·compare_judge·ok_with_refusal_phrase를 있는 만큼, mcp_eval 조인이 있으면 hit@1/5도)."""
    cls = row.get("cls") or "UNSCORED"
    bits = [CLS_LABEL.get(cls, cls)]
    if row.get("subcause"):
        bits.append(row["subcause"])
    if row.get("compare_judge"):
        bits.append(f"compare_judge={row['compare_judge']}")
    if row.get("ok_with_refusal_phrase"):
        bits.append("정답인데 거부 문구도 있음")
    if row.get("error"):
        bits.append(f"오류: {row['error'][:120]}")
    if mcp_hit is not None:
        bits.append(f"검색 hit@1={mcp_hit.get('hit1')} hit@5={mcp_hit.get('hit5')}")
    return " · ".join(bits)


def build(rows, mcp_idx, qa_raw_get, plain=False):
    """rows(answer_stage 결과) → (표시용 행 목록, 요약) — 오답·기권 먼저 정렬."""
    name = name_fn(plain)
    out_rows = []
    for r in rows:
        ds, rid = r.get("dataset"), r.get("id")
        item = qa_raw_get(ds).get(rid) if ds else None
        gold_docs = set(r.get("gold_docs") or [])
        files5 = r.get("files5") or []
        cls = r.get("cls") or "UNSCORED"
        out_rows.append(
            {
                "dataset": ds,
                "id": rid,
                "type": r.get("type"),
                "question": r.get("question") or "",
                "gold_answer": gold_answer_text(item),
                "llm_answer": r.get("answer") or "",
                "cls": cls,
                "verdict": verdict_text(r, mcp_idx.get((ds, rid))),
                "retrieved": [(name(f), f in gold_docs) for f in files5 if f],
                "cited": [name(f) for f in cited_files(r.get("answer"), files5)],
            }
        )
    rank = {c: i for i, c in enumerate(CLS_ORDER)}
    out_rows.sort(key=lambda r: (rank.get(r["cls"], len(CLS_ORDER)), r["dataset"] or "", r["id"] or ""))
    cls_counts = Counter(r["cls"] for r in out_rows)
    by_set, by_type = defaultdict(Counter), defaultdict(Counter)
    for r in out_rows:
        by_set[r["dataset"] or "—"][r["cls"]] += 1
        by_type[r["type"] or "—"][r["cls"]] += 1
    summary = {
        "n": len(out_rows),
        "classification": dict(cls_counts),
        "by_set": {k: dict(v) for k, v in sorted(by_set.items())},
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
    }
    return out_rows, summary


# ───────────────────────── HTML(외부 자원 0) ─────────────────────────
def E(s):
    return html.escape(str(s)) if s is not None else ""


_CSS = """
:root{--paper:#F5F7FA;--surface:#FFFFFF;--ink:#1B2430;--muted:#5B6675;--line:#D3DAE3;
--ok:#2E7D32;--miss:#C62828;--abstain:#B26A00;--review:#6B4BB7;--rmiss:#7B4BB7;--unscored:#6B7A90}
@media (prefers-color-scheme:dark){:root{--paper:#11161D;--surface:#19202A;--ink:#E5E9EF;--muted:#9AA6B5;--line:#2C3643}}
body{background:var(--paper);color:var(--ink);font:14px/1.5 "Malgun Gothic","Noto Sans KR",system-ui,sans-serif;margin:0}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 56px;display:grid;gap:18px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 8px}
.meta{color:var(--muted);font-size:12.5px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.tiles{display:flex;flex-wrap:wrap;gap:16px}.tile b{display:block;font-size:20px}.tile span{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--surface)}
td.wrap-cell{max-width:360px;white-space:pre-wrap;word-break:break-word}
.pill{display:inline-block;padding:0 7px;border-radius:9px;font-size:11px;color:#fff;white-space:nowrap}
.pill-OK{background:var(--ok)}.pill-A-MISS{background:var(--miss)}.pill-A-ABSTAIN{background:var(--abstain)}
.pill-REVIEW{background:var(--review)}.pill-R-MISS{background:var(--rmiss)}.pill-UNSCORED{background:var(--unscored)}
.doc{display:inline-block;margin:0 4px 2px 0;padding:0 5px;border:1px solid var(--line);border-radius:4px;font-size:11px}
.doc.gold{border-color:var(--ok);font-weight:700}
.legend{color:var(--muted);font-size:12px}
details summary{cursor:pointer;font-weight:700}
"""


def _summary_table(counts_by_key, title, key_label):
    heads = "".join(f"<th>{E(c)}</th>" for c in CLS_ORDER) + "<th>합계</th>"
    rows = []
    for key, counts in counts_by_key.items():
        total = sum(counts.values())
        cells = "".join(f"<td>{counts.get(c, 0)}</td>" for c in CLS_ORDER)
        rows.append(f"<tr><td>{E(key)}</td>{cells}<td>{total}</td></tr>")
    return (
        f'<section class="panel"><h2>{E(title)}</h2><table><thead><tr><th>{E(key_label)}</th>{heads}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def render_html(out_rows, summary, tag):
    tiles = "".join(f'<div class="tile"><b>{summary["classification"].get(c, 0)}</b><span>{E(c)}</span></div>' for c in CLS_ORDER)
    legend = " · ".join(f"<b>{E(c)}</b> = {E(CLS_LABEL[c])}" for c in CLS_ORDER)
    trs = []
    for r in out_rows:
        docs_html = " ".join(f'<span class="doc{" gold" if g else ""}">{E(d)}{"★" if g else ""}</span>' for d, g in r["retrieved"]) or "—"
        cited_html = ", ".join(E(x) for x in r["cited"]) or "—"
        trs.append(
            f"<tr><td>{E(r['dataset'])}</td><td>{E(r['id'])}</td><td>{E(r['type'])}</td>"
            f'<td class="wrap-cell">{E(r["question"])}</td>'
            f'<td class="wrap-cell">{E(r["gold_answer"]) if r["gold_answer"] is not None else "—"}</td>'
            f'<td class="wrap-cell">{E(r["llm_answer"]) or "(빈 답)"}</td>'
            f'<td><span class="pill pill-{E(r["cls"])}">{E(r["cls"])}</span><br>{E(r["verdict"])}</td>'
            f"<td>{docs_html}</td><td>{cited_html}</td></tr>"
        )
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>Q&A 결과 보고서 — {E(tag)}</title>
<style>{_CSS}</style></head><body><main class="wrap">
<header><h1>Q&A 결과 보고서</h1><div class="meta">입력 {E(tag)} · 문항 {summary["n"]}건</div></header>
<section class="panel"><h2>전체 분류</h2><div class="tiles">{tiles}</div>
<div class="legend">{legend}</div></section>
{_summary_table(summary["by_set"], "세트별", "세트")}
{_summary_table(summary["by_type"], "문항 유형별", "유형")}
<section class="panel"><h2>문항별 — 오답·기권 먼저</h2><table><thead><tr>
<th>세트</th><th>ID</th><th>유형</th><th>질문</th><th>정답</th><th>LLM 답변</th><th>판정</th>
<th>근거 문서(top5, 정답★)</th><th>인용 문서</th></tr></thead><tbody>{"".join(trs)}</tbody></table></section>
</main></body></html>"""


# ───────────────────────── xlsx(openpyxl 있을 때만) ─────────────────────────
def write_xlsx(out_rows, path):
    try:
        from openpyxl import Workbook
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        return None

    def clean(v):
        return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v

    wb = Workbook()
    ws = wb.active
    ws.title = "qa_report"
    headers = ["세트", "문항ID", "유형", "질문", "정답", "LLM 답변", "판정", "판정 사유", "근거 문서(top5, 정답★)", "인용 문서"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for i, w in enumerate((14, 10, 14, 42, 30, 50, 14, 32, 36, 26), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in out_rows:
        docs = ", ".join(f"{d}{'★' if g else ''}" for d, g in r["retrieved"]) or "—"
        cited = ", ".join(r["cited"]) or "—"
        reason = r["verdict"].split(" · ", 1)
        reason = reason[1] if len(reason) > 1 else ""
        ws.append(
            [
                clean(v)
                for v in (
                    r["dataset"],
                    r["id"],
                    r["type"],
                    r["question"],
                    r["gold_answer"] or "—",
                    r["llm_answer"] or "(빈 답)",
                    r["cls"],
                    reason,
                    docs,
                    cited,
                )
            ]
        )
    wrap = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", help="answer_stage rows json(필수, --selftest 아니면)")
    ap.add_argument("--mcp-eval", default=None, help="같은 질문 세트의 mcp_eval 산출 json(선택 — hit@1/5 조인)")
    ap.add_argument("--eval-sets-root", default=str(EVAL_SETS_DEFAULT), help="qa.json 폴더(정답 텍스트 조회, best-effort)")
    ap.add_argument("--tag", default=None, help="출력 파일 이름(기본: rows 파일 이름에서 _rows를 뺀 것)")
    ap.add_argument("--out", default="output", help="저장 루트(<out>/report/qa_report_<tag>.{html,xlsx})")
    ap.add_argument("--plain-names", action="store_true", help="문서 원래 이름(기본 해시 — 실데이터 반출 주의)")
    ap.add_argument("--no-xlsx", action="store_true", help="xlsx 생략(html만)")
    a = ap.parse_args(argv)
    if not a.rows:
        ap.error("--rows 필요(또는 --selftest)")

    rows = load_rows(a.rows)
    mcp_idx = load_mcp_index(a.mcp_eval)
    qa_raw_get = load_qa_raw(a.eval_sets_root)
    out_rows, summary = build(rows, mcp_idx, qa_raw_get, plain=a.plain_names)
    tag = a.tag or Path(a.rows).stem.rsplit("_rows", 1)[0]

    out_dir = Path(a.out) / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"qa_report_{tag}.html"
    html_path.write_text(render_html(out_rows, summary, tag), encoding="utf-8")
    print(f"저장: {html_path}")
    if not a.no_xlsx:
        xlsx_path = write_xlsx(out_rows, out_dir / f"qa_report_{tag}.xlsx")
        print(f"저장: {xlsx_path}" if xlsx_path else "(xlsx 생략 — openpyxl 없음, html만 저장됨)")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return out_rows, summary


if __name__ == "__main__":
    main()
