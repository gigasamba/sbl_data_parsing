#!/usr/bin/env python3
"""검색 CLI — 질문 → 근거(ask). S5(10-26, T-15 — D-021 ④)에 파이프라인 진입점(pipeline/cli.py)에서 옮김: 파이프라인 CLI가
검색 코드(mcp_server)를 import하지 않게(refactor_plan 2-2 — pipeline ↔ mcp_server import 금지).

  ask   질문 → 근거 청크 + 원본 경로·쪽·줄·절 — mcp_server.services.search.search_svc.do_search()에 위임(AR10) — MCP와 같은 결과.
        답변은 만들지 않음(답변은 서빙되는 Answer Agent rag_qa — valid_env/answer_test/rag_qa, 점검 validation/e2e/answer_gen.py).
(11-01 지움 — 문항 세트 시험 test-stack, 예전 검색 경로 --retrieve cosine, 로컬 묶음 --local: 검색은 PG 하나, PRD mc-01·e2-10.)
사용: python -m mcp_server.cli.search_ask ask --source CRMS --k 3 --q "<질문>"(원천 하나 필수 — search와 같음 · 검색은 settings.yaml의 PG 스키마 — mc-19부터 묶음 폴더를 읽지 않음)
(이미지 안: 엔트리포인트 명령 ask가 이 모듈을 부름 — deploy/docker/entrypoint.sh)
"""

import common  # noqa: F401 — 설정 파일 검사(settings.pin_env)를 첫 줄에서

# isort: split
import argparse
import json

from common.core.console import utf8_stdout


def _stack():
    """엔진 구성 파일(서버·PC 같음 — 사용자 11-01) → body + name(옛 stack.json 꼴)."""
    from common.store.db import cfgfile

    cur = cfgfile.active("stack")
    return cur.named()


def ask(a):
    """질문 → 근거(파일·쪽·줄·절). AR10(구조 리뷰 10-12 round4 QA095) — MCP search의 do_search()에 그대로 위임.
    질의 파일 기록은 없다(op-13 — MCP 호출은 DB applog.mcp_log, 이 명령은 MCP를 거치지 않음)."""
    st = _stack()
    from mcp_server.services.search import search_svc as MCP

    k = a.k or st.get("k", 8)
    res = MCP.do_search(a.q, k, methods=None, source_system=a.source)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    if res.get("error"):
        raise SystemExit(f"[ask] {res['error']}")
    if a.json:
        return
    # 0.2.0 응답은 운영 search 계약(SEARCH_TOP_KEYS — 검색 시간·방법·순위 칸 없음)
    print(f"질문: {res['question']}  (원천 {a.source} · 근거 {len(res.get('evidence') or [])}건)")
    for i, e in enumerate(res.get("evidence") or [], 1):
        print(f"[{i}] {e.get('file_path')}  p.{e.get('page')} L.{e.get('line')}" + (f"  §{e['section']}" if e.get("section") else ""))
        print("    " + (e.get("text") or "").replace("\n", " ")[:220])
    if res.get("evidence_status"):
        print(f"\n근거 상태: {res['evidence_status']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask")
    p.add_argument("--bundle", help=argparse.SUPPRESS)  # 옛 호출 호환 — 검색은 PG만(mc-19), 받기만
    p.add_argument("--pg", action="store_true", help=argparse.SUPPRESS)  # 옛 호출 호환 — 검색은 늘 PG(mc-01), 받기만
    p.add_argument("--k", type=int, default=8, help="근거 수 — MCP search 기본과 같게 8(AR5 측정: k=8이 k=10과 같거나 나음, 잘림 적음)")
    p.add_argument("--q", required=True)
    p.add_argument("--source", required=True, help="원천 하나(SFDC·CRMS·LAS·FAQ·Other — search의 source_system과 같음)")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ask(a)


if __name__ == "__main__":
    utf8_stdout()
    main()
