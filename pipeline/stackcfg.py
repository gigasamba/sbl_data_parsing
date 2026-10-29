"""엔진 구성 — 활성 판 → 검사 → 사본 파일(S8b, D-031 — 사용자 10-28 Q3·Q7·Q8·Q10 a).
진입점(pipeline.cli·stream·parse_parallel·mcp_parse_service·load.index)이 부른다: common.store.db.cfgtables.active("stack")(서버 = DB 활성 판,
PC = 파일) → 이미지에 없는 엔진 거부(등록부 + 설치 — parse ∪ candidates) → 결과 폴더 `_stack/stack-v<판>-<sha8>.json`(body + name +
version_id + body_sha)을 쓰고 설정 칸 STACK_SNAPSHOT(pipeline.paths.stack_snapshot)으로 넘긴다(put — 자식 프로세스도 받음).
층 파일(run_all·attachments)은 그 칸만 읽고, represent·build_bundle은 지금처럼 `--stack <사본>`을 받는다 — 판 표를 읽는 코드는 층의
의존이 아니다(code_fp). 같은 구성이면 같은 사본 바이트(색인 재빌드 판정 index_cfg.inputs도 같음)."""

import json
import os
import sys
from pathlib import Path

from common.core.console import utf8_stdout

EXIT_BAD_ENGINE = 2
MAX_PER_TYPE = 2  # 사용자 10-29 — 형식(parse 키)당 엔진 수 상한(run_all이 문서마다 그 엔진들을 동시에 돌림)


def engines_of(body):
    """파싱이 돌릴 수 있는 엔진 전부 — parse 목록 ∪ candidates(cli parse·night 기본 엔진과 같은 집합)."""
    return sorted({e for es in body.get("parse", {}).values() for e in es} | set(body.get("candidates") or []))


def over_limit(body):
    """형식당 엔진이 MAX_PER_TYPE개를 넘는 parse 키 — 설정 오류 목록(빈 목록 = 문제 없음)."""
    return [
        f"{k}: 엔진 {len(v)}개(형식당 최대 {MAX_PER_TYPE})" for k, v in sorted((body.get("parse") or {}).items()) if len(v) > MAX_PER_TYPE
    ]


def engine_problems(body):
    """이미지(또는 PC)가 돌릴 수 없는 엔진 — 등록부(pipeline/extract/engines)에 없거나 REQUIRES 모듈·도구가 없음. REQUIRES_ENV(모델 주소
    설정)는 설치 문제가 아니라 보지 않는다(Q8). 형식당 엔진 수 상한(over_limit)도 같이."""
    from pipeline.extract.engines import registry

    known = registry.engines()
    out = over_limit(body)
    for e in engines_of(body):
        if e not in known:
            out.append(f"{e}: 등록 안 됨(pipeline/extract/engines에 없음)")
        elif not registry.installed(e):
            out.append(f"{e}: 설치 안 됨({', '.join(registry.missing_deps(e))})")
    return out


def require_engines(body, where):
    bad = engine_problems(body)
    if bad:
        print(f"[엔진 구성] {where} — 이 이미지에 없는 엔진: " + " · ".join(bad), file=sys.stderr, flush=True)
        raise SystemExit(EXIT_BAD_ENGINE)


def snapshot_bytes(a):
    snap = {"name": a.name, "version_id": a.version_id, "body_sha": a.body_sha, **a.body}
    return (json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode(
        "utf-8"
    )  # 키 정렬 — DB(JSONB)·파일 키 순서와 무관


def write_snapshot(a, out_root):
    """사본 파일(같은 판·body면 같은 이름·바이트 — 있어도 바꿔 써 mtime이 새로 됨, S9b). 반환: 경로."""
    d = Path(out_root) / "_stack"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"stack-v{a.version_id if a.version_id is not None else 'file'}-{a.body_sha[:8]}.json"
    data = snapshot_bytes(a)
    # VS9 R-2 — 같은 바이트여도 늘 새로 씀: 이번에 쓴 사본이 가장 새 것(reuse()가 mtime으로 고름 — v1 → v2 → v1 되돌리기).
    # utime 대신 바꿔 쓰기 — 다른 UID가 쓴 파일이어도 폴더 쓰기 권한만 있으면 됨(S9b 리뷰)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return p


def resolve(out_root, refresh=False, publish=True):
    """활성 판 → 엔진 검사 → 사본 → (publish면) STACK_SNAPSHOT 칸으로 넘김. 반환: (사본 경로, 사본 dict). 서버에서 판 표를 못 읽으면 종료 4,
    없는 엔진이면 종료 2(시작하지 않음)."""
    from common.config import settings as C
    from common.store.db import cfgtables

    a = cfgtables.active("stack", refresh=refresh)
    require_engines(a.body, a.label())
    p = write_snapshot(a, out_root)
    if publish:
        C.put(STACK_SNAPSHOT=str(p))
    print(f"[엔진 구성] {a.label()} → {p.name}", file=sys.stderr, flush=True)
    return p, json.loads(p.read_text(encoding="utf-8"))


def current(out_root):
    """이미 넘겨받은 사본(STACK_SNAPSHOT — 진입점이 만듦, 자식 프로세스)이 있으면 그것, 없으면 resolve(out_root) — 함수로도 불리고
    단독으로도 도는 모듈(stream·parse_parallel·load.index)이 쓴다."""
    from pipeline import config as pc

    snap = pc.cfg().paths.stack_snapshot
    if snap and Path(snap).is_file():
        return Path(snap), json.loads(Path(snap).read_text(encoding="utf-8"))
    return resolve(out_root)


def reuse(out_root):
    """결과 폴더에 이미 쓴 사본(파싱이 만든 것 — `_stack/stack-v*.json`, 여럿이면 가장 새 것)이 있으면 (경로, dict), 없으면 None.
    호스트 run_docs.py 구조화가 문서별 폴더로 부른다(`--path`) — 파싱과 구조화 사이에 판이 바뀌어도 한 문서는 파싱한 판으로(VS8b R-1·C-50)."""
    snaps = sorted((Path(out_root) / "_stack").glob("stack-v*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    if not snaps:
        return None
    p = snaps[-1]
    body = json.loads(p.read_text(encoding="utf-8"))
    require_engines(body, p.name)
    print(
        f"[엔진 구성] 이 결과 폴더의 사본 다시 씀 → {p.name}" + (f"(사본 {len(snaps)}개 중 가장 새 것)" if len(snaps) > 1 else ""),
        file=sys.stderr,
        flush=True,
    )
    return p, body


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A)
    utf8_stdout()
    if (
        len(sys.argv) == 3 and sys.argv[1] == "--path"
    ):  # 셸용(호스트 run_docs.py 구조화) — 사본 경로만 stdout(안내는 stderr), 못 읽으면 종료 4·없는 엔진 2
        print(
            (reuse(sys.argv[2]) or current(sys.argv[2]))[0]
        )  # 그 폴더에 파싱이 쓴 사본이 있으면 그것(VS8b R-1), 없으면 넘겨받은 사본·활성 판
        raise SystemExit(0)
    raise SystemExit("사용: python -m pipeline.stackcfg --path <결과 폴더>")  # 자기 점검은 tests/server/pipeline/test_stackcfg.py(S9)
