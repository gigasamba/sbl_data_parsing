"""엔진 구성 — 파일 → 검사(이미지에 없는 엔진 거부). 서버·PC가 같은 파일을 쓴다.
진입점(pipeline.cli·pipeline.parse_service)이 resolve()로 시작 때 검사하고, 층(parse_engines·mail_attachments·build_rep·gold_bundle)은
pipeline.config.stack()으로 같은 파일을 읽는다. 파일은 오버레이 패치로만 바뀐다(실행 중에는 그대로)."""

import sys

from pipeline import config as pc
from pipeline.shared.ext_groups import IMG_EXTS

EXIT_BAD_ENGINE = 2


def engines_of(body):
    """파싱이 돌릴 수 있는 엔진 전부 — parse 목록의 합집합(cli parse 기본 엔진과 같은 집합)."""
    return sorted({e for es in body.get("parse", {}).values() for e in es})


def engine_problems(body):
    """이미지(또는 PC)가 돌릴 수 없는 엔진 — 등록부(pipeline/transform/parse/engines)에 없거나 REQUIRES 모듈·도구가 없음. REQUIRES_ENV(모델 주소
    설정)는 설치 문제가 아니라 보지 않는다(Q8)."""
    from pipeline.transform.parse.engines import registry

    known = registry.engines()
    out = []
    for e in engines_of(body):
        if e not in known:
            out.append(f"{e}: 등록 안 됨(pipeline/transform/parse/engines에 없음)")
        elif not registry.installed(e):
            out.append(f"{e}: 설치 안 됨({', '.join(registry.missing_deps(e))})")
    return out


def require_engines(body, where):
    bad = engine_problems(body)
    if bad:
        print(f"[엔진 구성] {where} — 이 이미지에 없는 엔진: " + " · ".join(bad), file=sys.stderr, flush=True)
        raise SystemExit(EXIT_BAD_ENGINE)


def resolve(refresh=False):
    """엔진 구성 파일 → 엔진 검사. 반환: cfgfile.Active. 파일을 못 읽거나 없는 엔진이면 종료 2(시작하지 않음)."""
    from common.store.db import cfgfile

    a = cfgfile.active("stack", refresh=refresh)
    require_engines(a.body, a.label())
    print(f"[엔진 구성] {a.label()}", file=sys.stderr, flush=True)
    return a


def allowed_exts():
    """받는 확장자(MCP parse_document 작업 서비스) = 엔진 구성의 parse 키(.pdf_text·.pdf_image → .pdf) − 이미지(IMG_EXTS — "이미지 파싱은
    수행 안하고 꺼줘" 요구사항에 따라 원천 거부). 부를 때마다 읽는다(작업마다 다시 읽는 엔진 구성과 같게, 시작 점검보다 먼저 읽지 않게)."""
    return {".pdf" if e.startswith(".pdf_") else e for e in pc.stack()["parse"]} - IMG_EXTS
