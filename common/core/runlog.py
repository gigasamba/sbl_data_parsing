#!/usr/bin/env python3
"""실행 기록 — 콘솔 로그가 빨리 밀려도 **모든 도구 실행의 핵심 요약**이 파일에 남게.

  output/RUNLOG.md      실행 1회 = 1항목(시각 · 명령 · 걸린 시간 · 결과 · 핵심 요약 · 다음 할 일 · 전체 로그 위치) — 사람·GLM이 읽는 곳
  output/runlog.jsonl   같은 내용(기계용)
  output/logs/<시각>_<도구>.log   콘솔 출력 전체(표준 출력·오류, --procs 하위 프로세스 출력도 같은 파일)
도구 쪽 사용:
    from common.core.runlog import session, note
    with session("run_all"):          # main() 전체를 감쌈 — 끝나면(오류여도) 항목 1개 추가
        note("phase 1: 성공 23 · 다음 phase로 8")   # 핵심 결과 1줄씩(없으면 출력 마지막 5줄을 요약으로)
    # next_step(cmd) — "다음 할 일" 한 줄 등록(같은 _state를 공유) — pipeline.shared.runlog로 옮김(10-14, P만 씀):
    #     from pipeline.shared.runlog import next_step
보기: python common/runlog.py --tail 5   (또는 output/RUNLOG.md 끝)
하위 프로세스(RUNLOG_CHILD=1)는 항목을 따로 만들지 않고 부모의 로그 파일(RUNLOG_FILE)에 출력만 이어 쓴다.

L8a 범위 한계(독립 보안 검토 10-12): `_mask()`는 **이 파일이 쓰는 output/logs/*.log만** 가린다. 컨테이너를
`docker logs`로 보거나 dev/docker/compose.*.yml의 json-file 로그 드라이버로 보면 같은 stdout이 그대로(가림 없이)
남는다 — compose 쪽은 다른 세션(OP25)이 건드리는 중이라 여기서 바꾸지 않음, 그 세션 몫."""

import argparse
import contextlib
import json
import os
import re
import shlex
import sys
import threading
import time
import traceback
from pathlib import Path

from common.config.settings import cfg, dropped  # S7b — 설정 객체(OUT은 옛 그대로 import 때 한 번 읽는 모듈 상수)
from common.core.console import utf8_stdout
from common.core.paths import APP_ROOT, PKG_ROOT

ROOT = PKG_ROOT  # 표시용(명령 줄을 짧은 상대경로로, 예: "cli/pipeline.py") — 쓰기는 모두 OUT(APP_ROOT) 기준
OUT = Path(cfg().paths.runlog_dir or APP_ROOT / "output")
_state: dict = {"notes": [], "next": [], "tail": [], "log": None}
_lock = threading.Lock()

# L8a — 로그(output/logs/*.log)에 비밀값이 그대로 남지 않게(콘솔 자체는 그대로, 파일에 쓸 때만 가림). 커넥션
# 문자열의 UID= 같은 비식별 값은 안 가림 — 식별자(authorization·토큰·비밀번호·AWS 비밀키·DSN 비밀번호)만.
# 트레이스백이 접속 문자열을 그대로 물고 나오는 경우(pyodbc 등)까지 커버. key=value·key:"value"·JSON
# {"key": "value"}(앞뒤 따옴표 어느 쪽에도 가능) 세 모양 다 받음 — "토큰" 같은 일반 단어(completion_tokens=18,
# max_tokens, tokens(), token_budget, ev_tokens5)는 라벨 뒤에 구분자(=·:)가 바로 안 오므로 안 걸림(독립 검토
# 10-12, dev_tools/unit_test/pipeline/test_runlog_mask_and_retention.py의 no-over-masking 표로 고정).
_LABEL = (
    r"(?:aws[_-]?)?secret[_-]?access[_-]?key"  # AWS_SECRET_ACCESS_KEY · SecretAccessKey(언더스코어 없어도)
    r"|(?:aws[_-]?)?api[_-]?key"
    r"|apikey"
    r"|token"
    r"|secret"
    r"|password"
    r"|passwd"
    r"|pwd"
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)[\"']?authorization[\"']?\s*:\s*[\"']?bearer\s+(?P<val>[^\"'\s,;}]+)"),
    # 따옴표로 감싼 값은 닫는 따옴표까지 통째로("p@ss w"처럼 공백이 있어도) — 아래 따옴표 없는 패턴보다 먼저
    re.compile(r"(?i)[\"']?(?:" + _LABEL + r")[\"']?\s*[=:]\s*\"(?P<val>[^\"]*)\""),
    re.compile(r"(?i)[\"']?(?:" + _LABEL + r")[\"']?\s*[=:]\s*'(?P<val>[^']*)'"),
    # key=value · "key": "value"(따옴표는 키·값 어느 쪽에 있어도, 서로 짝이 안 맞아도 넉넉히 받음)
    re.compile(r"(?i)[\"']?(?:" + _LABEL + r")[\"']?\s*[=:]\s*[\"']?(?P<val>[^,;&\s\"']+)"),
    # scheme://user:password@host — DSN의 비밀번호 부분만(스킴·계정은 안 가림)
    # 스킴 중간에서 다시 시작하지 않는다: 긴 본문에서 실패할 때 제곱 시간 역추적 방지.
    re.compile(r"(?i)(?<![a-z0-9+.\-])[0-9+.\-]*[a-z][a-z0-9+.\-]*://[^:/@\s]+:(?P<val>[^@\s]+)@"),
)


def _mask(s):
    for pat in _SECRET_PATTERNS:
        s = pat.sub(_mask_val, s)
    return s


def _mask_val(m):
    """매치 전체에서 val 그룹 구간만 '***'로 — 양옆 따옴표·구분자·스킴은 그대로 남김."""
    s0 = m.start()
    return m.group(0)[: m.start("val") - s0] + "***" + m.group(0)[m.end("val") - s0 :]


def _prune_old_logs(days=None):
    """LOG_RETENTION_DAYS(기본 30)보다 오래된 .log만 output/logs 안에서 지움(L8a) — 그 밖 경로는 안 건드림."""
    if days is None and dropped("LOG_RETENTION_DAYS"):
        return  # 형식 틀린 값 — 옛 코드처럼 지우기를 건너뜀(int() ValueError → return, S7b)
    try:
        days = int(days if days is not None else cfg().runtime.log_retention_days)  # S7b — 설정 객체(기본 30)
    except (TypeError, ValueError):
        return
    if days <= 0:
        return
    logs_dir = OUT / "logs"
    if not logs_dir.is_dir():
        return
    cutoff = time.time() - days * 86400
    for p in logs_dir.glob("*.log"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


class _Tee:
    """콘솔과 로그 파일에 동시에 — 마지막 줄들은 요약 대체용으로 보관. 파일에 쓰는 내용은 비밀값을 가린다(L8a)."""

    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, s):
        self.stream.write(s)
        masked = _mask(s)
        with _lock:
            self.fh.write(masked)
            self.fh.flush()
            for line in masked.splitlines():
                if line.strip():
                    _state["tail"] = (_state["tail"] + [line.strip()])[-5:]
        return len(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, k):
        return getattr(self.stream, k)


def note(line):
    """핵심 결과 1줄(요약에 그대로 들어감)."""
    _state["notes"].append(str(line))


@contextlib.contextmanager
def session(tool):
    child = os.environ.get("RUNLOG_CHILD") == "1"  # env 남김 — 내부 신호(5-3 H)
    if not child:
        _prune_old_logs()  # L8a — 보존 기한(LOG_RETENTION_DAYS) 지난 output/logs/*.log 정리
    _state.update(notes=[], next=[], tail=[])  # 한 프로세스에서 여러 번 열어도 항목끼리 섞이지 않게
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    parent_log = os.environ.get(
        "RUNLOG_FILE"
    )  # env 남김 — 내부 신호(5-3 H): 부모가 정한 로그 파일(S7e2 — 설정 칸에서 내부 신호로, 사용자 10-28)
    log = Path(parent_log) if child and parent_log else OUT / "logs" / f"{stamp}_{tool}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("a", encoding="utf-8")
    _state["log"] = log
    os.environ["RUNLOG_FILE"] = str(log)  # env 남김 — 내부 신호(5-3 H): 하위 프로세스에 넘김(--procs·--isolate가 같은 파일에 이어 쓰게)
    old = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Tee(sys.stdout, fh), _Tee(sys.stderr, fh)
    t0, status, err = time.time(), "성공", None
    cmd = "python " + " ".join(
        shlex.quote(x) for x in [os.path.relpath(sys.argv[0], ROOT) if Path(sys.argv[0]).exists() else sys.argv[0]] + sys.argv[1:]
    )
    try:
        yield
    except SystemExit as ex:
        if ex.code not in (0, None):
            status, err = "중단", str(ex.code)[:300]
        raise
    except KeyboardInterrupt:
        status, err = "사용자 중지", "KeyboardInterrupt"
        raise
    except Exception as ex:
        status, err = "오류", f"{type(ex).__name__}: {ex}"[:300]
        traceback.print_exc()
        raise
    finally:
        sys.stdout, sys.stderr = old
        fh.close()
        if not child:
            _write_entry(tool, cmd, t0, status, err, log)


def _write_entry(tool, cmd, t0, status, err, log):
    sec = time.time() - t0
    dur = f"{sec / 60:.1f}분" if sec >= 60 else f"{sec:.1f}초"
    notes = _state["notes"] or [f"(출력 끝) {x[:200]}" for x in _state["tail"]]
    rec = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
        "tool": tool,
        "cmd": cmd,
        "sec": round(sec, 1),
        "status": status,
        "error": err,
        "notes": notes,
        "next": _state["next"],
        "log": os.path.relpath(log, ROOT) if str(log.resolve()).startswith(str(ROOT)) else str(log),
    }
    md = [f"## {rec['time']} · {tool} · {status} · {dur}", "", f"`{cmd}`", ""]
    md += [f"- {n}" for n in notes]
    if err:
        md.append(f"- **오류**: {err}")
    md += [f"- 다음: `{x}`" for x in rec["next"]]
    md += [f"- 전체 로그: `{rec['log']}`", ""]
    with _lock:
        if not (OUT / "RUNLOG.md").exists():
            (OUT / "RUNLOG.md").write_text("# 실행 기록 (도구 실행 1회 = 1항목, 최신이 아래)\n\n", encoding="utf-8")
        with (OUT / "RUNLOG.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        with (OUT / "runlog.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def tail(n=5):
    p = OUT / "runlog.jsonl"
    recs = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    for r in recs[-n:]:
        print(f"[{r['time']}] {r['tool']} · {r['status']} · {r['sec']}초 — {r['cmd']}")
        for x in r["notes"]:
            print(f"    · {x}")
        if r.get("error"):
            print(f"    ! {r['error']}")
        for x in r.get("next") or []:
            print(f"    → {x}")
        print(f"    로그: {r['log']}")


if __name__ == "__main__":
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=5, help="최근 N개 실행 요약")
    a = ap.parse_args()
    tail(a.tail)
