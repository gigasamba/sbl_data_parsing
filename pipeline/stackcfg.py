"""엔진 구성 — 활성 판 → 검사 → 판 번호를 자식에 넘김(S8b, D-031 · pl-32 사용자 10-30: 사본 파일 `_stack/stack-v*.json`·STACK_SNAPSHOT 없앰).
진입점(pipeline.cli·mcp_parse_service·load.index)이 부른다: common.store.db.cfgtables.active("stack")(서버 = DB 활성 판,
PC = 파일) → 이미지에 없는 엔진 거부(등록부 + 설치 — parse ∪ candidates) → 판 번호를 설정 칸 STACK_VERSION(pipeline.paths.stack_version)으로
넘긴다(put — 자식 프로세스도 받음). 자식·층(run_all·attachments·represent·build_bundle)은 pipeline.config.stack()으로 그 판을 판 표에서 읽는다 —
실행 중 활성 판이 바뀌어도 한 실행은 한 판. 호스트 스크립트(run_docs)는 `--version`으로 판 번호를 한 번 받아 파싱·구조화에 --set으로 준다."""

import json
import sys

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


def resolve(refresh=False, publish=True):
    """활성 판 → 엔진 검사 → (publish면) 판 번호를 STACK_VERSION 칸으로 넘김(PC 파일은 번호가 없어 안 넘김 — 자식도 파일을 읽음).
    반환: cfgtables.Active. 서버에서 판 표를 못 읽으면 종료 4, 없는 엔진이면 종료 2(시작하지 않음)."""
    from common.config import settings as C
    from common.store.db import cfgtables

    a = cfgtables.active("stack", refresh=refresh)
    require_engines(a.body, a.label())
    if publish and a.version_id is not None:
        C.put(STACK_VERSION=str(a.version_id))
    print(f"[엔진 구성] {a.label()}", file=sys.stderr, flush=True)
    return a


def current():
    """이미 넘겨받은 판(STACK_VERSION — 부모 진입점이 정함)이 있으면 그 판, 없으면 resolve() — 함수로도 불리고 단독으로도 도는
    모듈(load.index)이 쓴다. 반환: cfgtables.Active."""
    from common.store.db import cfgtables
    from pipeline import config as pc

    v = pc.cfg().paths.stack_version
    if v is None:
        return resolve()
    a = cfgtables.active("stack", version_id=v)
    require_engines(a.body, a.label())
    return a


if __name__ == "__main__":
    from common.config import setarg

    setarg.apply()  # --set 이름=값(S9 Step A)
    utf8_stdout()
    if sys.argv[1:] == ["--version"]:  # 셸용(호스트 run_docs.py) — 활성 판 번호만 stdout(PC 파일이면 빈 줄), 못 읽으면 종료 4·없는 엔진 2
        v = resolve(publish=False).version_id
        print("" if v is None else v)
        raise SystemExit(0)
    raise SystemExit("사용: python -m pipeline.stackcfg --version")  # 자기 점검은 tests/server/pipeline/test_stackcfg.py(S9)
