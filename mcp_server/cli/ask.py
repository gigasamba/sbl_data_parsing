#!/usr/bin/env python3
"""검색 CLI — 질문 → 근거(ask). S5(10-26, T-15 — D-021 ④)에 파이프라인 진입점(pipeline/cli.py)에서 옮김: 파이프라인 CLI가
검색 코드(mcp_server)를 import하지 않게(refactor_plan 2-2 — pipeline ↔ mcp_server import 금지).

  ask   질문 → 근거 청크 + 원본 경로·쪽·줄·쪽 안 위치(bbox) — mcp_server.services.search.search_svc.do_search()에 위임(AR10) — MCP와 같은 결과.
        답변은 만들지 않음(답변은 서빙되는 Answer Agent rag_qa — valid_env/answer_test/rag_qa, 점검 validation/e2e/answer_gen.py).
(11-01 지움 — 문항 세트 시험 test-stack, 예전 검색 경로 --retrieve cosine, 로컬 묶음 --local: 검색은 PG 하나, PRD mc-01·e2-10.)
사용: python -m mcp_server.cli.ask ask --bundle output/<이름>/bundle --k 3 --q "<질문>"
(이미지 안: 엔트리포인트 명령 ask가 이 모듈을 부름 — deploy/docker/entrypoint.sh)
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서

# isort: split
import argparse
import json

from common.config import settings as C  # 설정 객체(S7d)
from common.core.console import utf8_stdout


def _stack():
    """엔진 구성 파일(서버·PC 같음 — 사용자 11-01) → body + name(옛 stack.json 꼴)."""
    from common.store.db import cfgfile

    cur = cfgfile.active("stack")
    return cur.named()


def ask(a):
    """질문 → 근거(파일·쪽·줄·bbox·점수·via). AR10(구조 리뷰 10-12 round4 QA095) — MCP search의 do_search()에 그대로 위임.
    MCP_BUNDLE만 --bundle에 맞춰 세팅한다. 질의 기록은 do_search() 안 _log()가 함(qa_log.append — 파일만, mc-13)."""
    st = _stack()
    C.put(MCP_BUNDLE=str(a.bundle))  # S7e2 — 덮기 파일(이 프로세스·하위 프로세스)
    from mcp_server.services.search import search_svc as MCP

    k = a.k or st.get("k", 8)
    res = MCP.do_search(a.q, k, methods=None)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    print(f"질문: {res['question']}  ({res.get('store')} · 방법 {','.join(res.get('methods') or [])}, 검색 {res['ms']:.1f} ms)")
    for i, s in enumerate(res.get("subs") or [], 1):
        print(f"  하위 질문 {i}: {s}")
    for n in res.get("notes") or []:
        print(f"  note: {n}")
    for e in res.get("evidence") or []:
        rank = f"[{e['rank']}]" if e.get("rank") is not None else "   "
        print(
            f"{rank} {e.get('file_path')}  p.{e.get('page')} L.{e.get('line')}"
            + (f"  bbox={e['bbox']}" if e.get("bbox") else "")
            + (f"  ({e['via']})" if e.get("via") else "")
            + (f"  §{e['section']}" if e.get("section") else "")
        )
        print("    " + (e.get("text") or "").replace("\n", " ")[:220])
    if res.get("evidence_status"):
        print(f"\n근거 상태: {res['evidence_status']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask")
    p.add_argument("--bundle", default="output/edw/bundle")
    p.add_argument("--pg", action="store_true", help=argparse.SUPPRESS)  # 옛 호출 호환 — 검색은 늘 PG(mc-01), 받기만
    p.add_argument("--k", type=int, default=8, help="근거 수 — MCP search 기본과 같게 8(AR5 측정: k=8이 k=10과 같거나 나음, 잘림 적음)")
    p.add_argument("--q", required=True)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ask(a)


if __name__ == "__main__":
    utf8_stdout()
    from common.core.runlog import session

    with session("pipeline"):  # 옛 pipeline/cli.py와 같은 실행 기록 이름(output/logs/<시각>_pipeline.log)
        main()
