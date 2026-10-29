#!/usr/bin/env python3
"""AD21③ — '이어서 VLM': 상한(VLM_FIGURES_MAX)에 걸려 건너뛴 그림만 마저 처리한다.
modules/parse/post/figures.py의 capped.jsonl(AD21①)에 오른 문서만 대상으로 상한을 올려 build_records를 다시 돌린다.
이미 처리한 그림은 VLM 캐시(모델·지시문·이미지 sha)가 그대로라 재호출 0, 상한 밖이던 그림만 새로 부른다.
대표 결과(output/parse/_rep/<문서>.json)의 text·post를 갱신하고(pipeline.transform.represent.represent.apply_post 재사용 — vlm_page·
charts·supsub·attachments도 캐시로 그대로, figures만 cap 효과), 색인(검색) 반영은 다음 structure 실행이 하게
_rep/_DONE.json의 run_id를 올려 둔다(cli/pipeline.py need()가 새 run_id로 보고 다시 처리).
한계: 스트리밍 모드(PARSE_STREAM=1)로 처리돼 원본이 이미 지워진 문서는 다시 판독할 수 없어 건너뜀(목록에 남음) — 원본을 다시 받아야 함.
사용: python cli/figures_resume.py [--max N] [--doc 문서이름] [--parse-dir output/parse]
"""

import argparse
import json
import time
from pathlib import Path

from common.core.paths import APP_ROOT
from pipeline import config as pc  # pipeline 칸 설정 객체(S7c)

ROOT = APP_ROOT  # output/ 등 런타임 경로용(옛 dev/)
from pipeline.transform.figures import figures as fig_mod  # noqa: E402
from pipeline.transform.represent.represent import apply_post  # noqa: E402


def capped_docs(doc_filter=None):
    """capped.jsonl 줄 목록(건너뛴 그림이 있는 문서만, AD21①) — doc_filter가 있으면 그 문서만."""
    p = fig_mod.capped_path()
    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.exists() else []
    return [r for r in rows if not doc_filter or r["doc"] == doc_filter]


def resume_one(row, parse_dir, cap):
    """문서 1건 — 대표 결과를 다시 읽어 상한을 올리고 apply_post로 그림 기록·text·post를 갱신. (바뀐 문서 수, 그림 수, 남은 건너뜀 수)."""
    pd = Path(parse_dir)
    rep_path = pd / "_rep" / f"{row['doc']}.json"
    if not rep_path.exists():
        print(f"[figures_resume] {row['doc']}: _rep 결과 없음 — 건너뜀")
        return False, 0, 0
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    engine = (rep.get("rep") or {}).get("engine")
    source = (rep.get("rep") or {}).get("source") or {}
    doc_path = source.get("path")
    if not (engine and doc_path and Path(doc_path).exists()):
        print(f"[figures_resume] {row['doc']}: 원본·엔진 결과를 찾을 수 없음 — 건너뜀(엔진 {engine}, 경로 {doc_path})")
        return False, 0, 0
    base_file = pd / engine / f"{row['doc']}.json"  # 후보정 전 본문(apply_post가 쌓기 전 원본 층, W10)
    base = json.loads(base_file.read_text(encoding="utf-8")).get("text") or "" if base_file.exists() else (rep.get("text") or "")
    feats = frozenset((rep.get("post") or {}).get("features") or [])
    fresh = {"text": base, "rep": rep.get("rep")}
    info = apply_post(
        fresh, row["doc"], Path(doc_path), feats, figures_max=cap
    )  # S7c2 — 상한은 인자로(전엔 env VLM_FIGURES_MAX를 잠깐 바꿈)
    rep["text"], rep["post"] = fresh["text"], info
    rep_path.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    remaining = sum(1 for r in capped_docs(row["doc"]))
    return True, info.get("figures", 0), remaining


def bump_parse_mark(parse_dir):
    """_rep/_DONE.json의 run_id·finished_at만 올림(나머지 필드 유지) — 다음 structure 실행이 새 run_id로 보고 다시 처리(docs/architecture.md)."""
    p = Path(parse_dir) / "_rep" / "_DONE.json"
    if not p.exists():
        print("[figures_resume] _rep/_DONE.json 없음 — parse 모듈을 아직 안 끝냄(끝 표시 갱신 건너뜀)")
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    m["run_id"] = time.strftime("%Y%m%d-%H%M%S")
    m["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[figures_resume] _rep/_DONE.json run_id → {m['run_id']}(다음 structure 실행이 다시 처리)")
    return m["run_id"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-dir", default=str(ROOT / "output" / "parse"))
    ap.add_argument("--max", type=int, default=None, help="새 상한(비우면 VLM_FIGURES_MAX 환경변수 또는 그 2배)")
    ap.add_argument("--doc", default=None, help="이 문서만(비우면 capped.jsonl 전부)")
    a = ap.parse_args(argv)
    rows = capped_docs(a.doc)
    if not rows:
        print("[figures_resume] capped.jsonl에 상한 걸린 문서 없음 — 할 일 없음")
        return
    _fm = pc.cfg().transform.vlm.figures_max  # S7c — 설정 객체(옛 int(get(X) or 20))
    cap = a.max if a.max is not None else int(_fm if _fm is not None else 20) * 2
    done, total_figs = 0, 0
    for row in rows:
        ok, n_figs, remaining = resume_one(row, a.parse_dir, cap)
        if ok:
            done += 1
            total_figs += n_figs
            print(f"[figures_resume] {row['doc']}: 그림 {n_figs}개 다시 기록(상한 {cap}) · 남은 건너뜀 {remaining}건")
    print(f"[figures_resume] 문서 {done}/{len(rows)}건 갱신 · 그림 기록 {total_figs}개")
    if done:
        bump_parse_mark(a.parse_dir)
    from common.core.runlog import note

    note(f"그림 이어서 VLM: 문서 {done}/{len(rows)}건 · 상한 {cap}")


if __name__ == "__main__":
    main()
