#!/usr/bin/env python3
"""외부 서비스 연결 — pgvector는 설정(required.pg)으로만 붙는다(op-09 — docker ps·포트 자동 탐지 없음, 빈 칸이면 거부).
모델(LLM·VLM·OCR VLM·임베딩)은 OpenAI 호환 주소를 설정으로 바꿔 끼움 — 회사 문서가 나가므로 **내부망 주소만**(DONT 13).

모델 엔드포인트(접두어 LLM·VLM·EMBED): <접두어>_BASE_URL(…/v1) · <접두어>_MODEL · <접두어>_API_KEY(선택).
  외부 주소는 거부 — 개발 PC 실험에서만 <접두어>_ALLOW_EXTERNAL=1(RUN_ENV=local일 때만 — common/ai/guard.py).
사용: python common/services.py        → 연결 상태 표(비밀값은 출력 안 함)
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from common.ai.guard import external_allowed, is_internal, require_internal  # noqa: F401 — 내부망 가드는 common/guard.py 한 곳
from common.ai.guard import urlopen as guard_urlopen
from common.config.settings import by_env, reveal  # S7b 설정 객체
from common.core.console import utf8_stdout

HERE = Path(__file__).resolve().parent


def _pg_capable(c):
    """이름이 아니라 붙어서 능력 확인(XS1): SELECT 1 + vector 확장 존재 + PG_SCHEMA 접근 가능(있음 또는 만들 권한).
    → (ok, 설명). 비밀값은 반환·로그에 내지 않는다."""
    from common.store.pg import PG

    db = PG(c)
    db.q("SELECT 1")
    if not db.q("SELECT 1 FROM pg_extension WHERE extname='vector'"):
        return False, "vector 확장 없음"
    if not db.q("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (c["PG_SCHEMA"],)):
        priv = db.q("SELECT has_database_privilege(current_user, current_database(), 'CREATE') p")
        if not (priv and priv[0].get("p")):
            return False, f"스키마 {c['PG_SCHEMA']} 없음·만들 권한 없음"
    return True, "능력 확인됨"


def detect_pg():
    """설정의 PG에 붙어 능력 확인 → (ok, 설명). 접속 칸이 비면 pg.conf()가 거부(SystemExit — 채울 자리를 적음)."""
    from common.store.pg import conf

    c = conf()
    try:
        ok, why = _pg_capable(c)  # 이름이 아니라 붙어서 확인(vector 확장·스키마) — XS1
    except Exception as e:
        return False, f"{c['PG_HOST']}:{c['PG_PORT']}: 접속 실패({type(e).__name__})"
    return ok, f"{c['PG_HOST']}:{c['PG_PORT']}" + ("" if ok else f": {why}")


def connect(a):
    """명령 인자 a(--pg·--local): --local이면 로컬 묶음, 아니면 PostgreSQL 필수(op-09 — 못 붙으면 거부, 로컬로 조용히 빠지지 않음)."""
    if getattr(a, "local", False):
        a.pg = False
        print("[연결] 저장소: 로컬 묶음(--local)", flush=True)
        return
    ok, why = detect_pg()
    if not ok:
        raise SystemExit(f"[연결] PostgreSQL에 붙지 못함: {why}")
    a.pg = True
    print(f"[연결] 저장소: pgvector({why})", flush=True)


def model_status(prefix):
    base, model = by_env(f"{prefix}_BASE_URL"), by_env(f"{prefix}_MODEL")  # S7b — 설정 객체(이름을 글자로 지음)
    if not base:
        return "미설정", "", ""
    internal = (
        "내부"
        if is_internal(base)
        else ("외부(허용 — 개발 PC)" if external_allowed(prefix) else "외부 — 거부됨(ALLOW_EXTERNAL=1 + RUN_ENV=local 필요)")
    )
    if internal.startswith("외부 — 거부"):  # 막힌 외부 주소에는 /models도 안 보냄(키가 헤더로 나감 — 재검증 10-02)
        return internal, model or "(모델 미설정)", "확인 안 함(외부 거부)"
    req = urllib.request.Request(base.rstrip("/") + "/models")
    key = reveal(by_env(f"{prefix}_API_KEY"))
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with guard_urlopen(req, 5, prefix) as r:
            ids = [m.get("id") for m in json.load(r).get("data", [])]
        reach = "응답" + ("" if not model else (" · 모델 있음" if model in ids else f" · 모델 없음(서버: {', '.join(ids[:3])})"))
    except Exception as e:
        reach = f"응답 없음({type(e).__name__})"
    return internal, model or "(모델 미설정)", reach


def status():
    print("| 항목 | 연결 |", "|---|---|", sep="\n")
    try:
        ok, why = detect_pg()
    except SystemExit as e:  # 접속 칸이 빔 — 표에는 채울 자리를 적음
        ok, why = False, str(e)
    print(f"| pgvector | {'✓ ' if ok else '✗ '}{why} |")
    print("\n| 모델 | 주소 구분 | 모델 | 상태 |", "|---|---|---|---|", sep="\n")
    for p, label in (("LLM", "LLM(답변·분해·그래프)"), ("VLM", "VLM(이미지 파싱)"), ("EMBED", "임베딩")):
        print(f"| {label} | " + " | ".join(model_status(p)) + " |")


if __name__ == "__main__":
    utf8_stdout()
    status()
