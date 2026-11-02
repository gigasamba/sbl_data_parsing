"""엔진 구성 — 파일 → 검사(이미지에 없는 엔진 거부). 서버·PC 같은 파일(사용자 11-01: struct 판 표·판 번호 STACK_VERSION 없앰 — D-031·pl-08).
진입점(pipeline.cli·mcp_parse_service)이 resolve()로 시작 때 검사하고, 층(run_all·attachments·represent·build_bundle)은
pipeline.config.stack()으로 같은 파일을 읽는다. 파일은 오버레이 패치로만 바뀐다(실행 중에는 그대로)."""

import json
import sys

EXIT_BAD_ENGINE = 2
MAX_PER_TYPE = 2  # 사용자 10-29 — 형식(parse 키)당 엔진 수 상한(run_all이 문서마다 그 엔진들을 동시에 돌림)


def engines_of(body):
    """파싱이 돌릴 수 있는 엔진 전부 — parse 목록의 합집합(cli parse 기본 엔진과 같은 집합)."""
    return sorted({e for es in body.get("parse", {}).values() for e in es})


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
    snap = {"name": a.name, "body_sha": a.body_sha, **a.body}
    return (json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode(
        "utf-8"
    )  # 키 정렬 — DB(JSONB)·파일 키 순서와 무관


def resolve(refresh=False):
    """엔진 구성 파일 → 엔진 검사. 반환: cfgfile.Active. 파일을 못 읽거나 없는 엔진이면 종료 2(시작하지 않음)."""
    from common.store.db import cfgfile

    a = cfgfile.active("stack", refresh=refresh)
    require_engines(a.body, a.label())
    print(f"[엔진 구성] {a.label()}", file=sys.stderr, flush=True)
    return a
