#!/usr/bin/env python3
"""OP6 — MCP 질의 기록 90일 보존. question·stack_name·k·hits·answer·search_ms·asked_by를 output/ 아래 JSONL에 한 줄씩
남긴다 — 질의 기록은 이 파일뿐이다(mc-13, 사용자 10-30: PG qa_log 표는 만들지 않음). hits는 근거 chunk_id·rank·via만(원문·점수는 안 남김). 개인정보·시크릿(토큰)은
적지 않음 — asked_by는 mcp_server.py가 이미 'mcp:<호출자>'로 다듬은 값만 받는다(Authorization 값은 여기 안 옴).
기본 켬 — MCP_QUERY_LOG=0으로 끔. 90일 지난 줄은 기동 때 또는 마지막 정리로부터 24시간 지난 첫 기록 때 지운다.
"""

import json
import sys
import time
from pathlib import Path

from common.core.paths import APP_ROOT
from mcp_server import config as mc  # 설정 객체(S7d)

ROOT = APP_ROOT
RETAIN_DAYS = 90
_TIME_FMT = "%Y-%m-%dT%H:%M:%S"
_warned = False  # engine-qa BLOCK 1 — 쓰기 실패 경고는 프로세스당 한 번만(매 요청마다 stderr 스팸 금지)


def log_path():
    return Path(mc.cfg().query_log.dir or ROOT / "output" / "qa_log") / "qa_log.jsonl"


def enabled():
    return mc.cfg().query_log.enabled


def append(question, evidence, ms, asked_by, stack_name=None):
    """호출자·질문·돌려준 근거 id(chunk_id·rank·via)·지연을 한 줄 추가. MCP_QUERY_LOG=0이면 아무것도 안 함.
    engine-qa BLOCK 1 — output/qa_log 쓰기 실패(권한·디스크 풀)는 검색을 막으면 안 됨: 여기서 잡아 한 번만 경고하고
    조용히 넘어간다(호출부 do_search·_log가 죽지 않음 — mcp_server.py._log()도 방어적으로 한 번 더 감싼다)."""
    global _warned
    if not enabled():
        return
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": time.strftime(_TIME_FMT),
            "question": question,
            "stack_name": stack_name,
            "k": len(evidence),
            "hits": [{"chunk_id": e.get("chunk_id"), "rank": e.get("rank"), "via": e.get("via")} for e in evidence],
            "search_ms": round(ms, 1),
            "asked_by": asked_by,
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _cleanup_if_due(p)
    except OSError as ex:
        if not _warned:
            print(
                f"(질의 기록 실패 — 검색은 계속, 이후는 조용히 건너뜀: {type(ex).__name__}: {str(ex)[:120]})", file=sys.stderr, flush=True
            )
            _warned = True


def append_edw(sql, ok, row_count, elapsed_ms, error, asked_by):
    """EQ1 — audit record for query_edw/describe_edw, written to the same JSONL/toggle as append()
    (MCP_QUERY_LOG, same file) but tagged kind="edw_query" so it's distinguishable from search records.
    Never logs the connection string or a stack trace — only the SQL text, outcome, and a short error code."""
    global _warned
    if not enabled():
        return
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": time.strftime(_TIME_FMT),
            "kind": "edw_query",
            "sql": sql,
            "ok": ok,
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
            "error": error,
            "asked_by": asked_by,
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _cleanup_if_due(p)
    except OSError as ex:
        if not _warned:
            print(
                f"(질의 기록 실패 — 검색은 계속, 이후는 조용히 건너뜀: {type(ex).__name__}: {str(ex)[:120]})", file=sys.stderr, flush=True
            )
            _warned = True


def _cleanup_if_due(p):
    """기동 때(파일이 막 생김 — marker 없음) 또는 마지막 정리로부터 24시간 지났으면만 정리(매 기록마다 전체를 다시 쓰지 않음)."""
    marker = p.with_suffix(".cleaned")
    if marker.exists() and time.time() - marker.stat().st_mtime < 86400:
        return
    cleanup(p)
    marker.touch()


def cleanup(p=None):
    """90일 지난 줄 제거 — 시각을 못 읽는 줄(형식이 다른 옛 기록 등)은 알 수 없는 걸 지우지 않고 그대로 둔다."""
    p = p or log_path()
    if not p.exists():
        return 0
    cutoff = time.time() - RETAIN_DAYS * 86400
    kept, dropped = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            t = time.mktime(time.strptime(json.loads(line)["time"], _TIME_FMT))
        except Exception:
            kept.append(line)
            continue
        if t >= cutoff:
            kept.append(line)
        else:
            dropped += 1
    if dropped:
        p.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    return dropped
