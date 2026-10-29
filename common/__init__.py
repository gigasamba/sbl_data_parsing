"""공용 패키지 — 모듈(파싱·구조화·적재·검색) 사이 계약 코드 — 모든 이미지에 같은 내용이 들어가야 하는 것만(docs/architecture.md §2).
config(설정 읽기) · core(인계 지문·문서 ID·토큰 규칙·경로·실행 기록) · ai(LLM·VLM·임베딩 호출·내부망 확인) ·
store(pgvector·S3·회사 DB 연결·문서 대장) · check(경계·모델 연결 점검). 모듈 코드끼리는 서로 import하지 않고 이 패키지만
함께 쓴다(refactor_plan 4-3).
S3(10-26, D-001) — 옛 common_tools/__init__.py를 쪼갬: 인계 지문·옛 이름 대응표·판 표기는 core/fingerprint.py. 여기는 그것을 부르고
쓰던 이름만 다시 내보낸다.
S7e2(D-028 ④⑤) — 옵션 카탈로그(options.conf)·전환 다리(env_files)를 지웠다. import 때 영구 다리(settings.pin_env — 엔진·인계 파일이 env로
읽는 28키를 settings.yaml 값으로 env에)만 한 번 부른다 — 다른 common 모듈이 env를 읽기 전에.
"""

import os as _os
from pathlib import Path as _Path


def _pin():
    """영구 다리 — 설정 파일이 없고 이미지 배치도 아니면(호스트 python·파일 없는 PC) pydantic도 import하지 않고 돌아온다(이미지는 파일이 없어도
    이미지 기본값 DOC_DIR 등을 냄 — B-2). 서버에서 파일이 틀리면 SettingsError로 시작 실패(STRICT), local은 경고 뒤 계속(settings.pin_env)."""
    root = _Path(__file__).resolve().parents[1]  # PC = 저장소 루트 · 이미지 = /app/deploy
    run = _os.environ.get("RUN_ENV") or None  # env 남김 — RUN_ENV 신호
    local = root / "settings.yaml"  # settings.LOCAL_FILE과 같은 자리(저장소 루트)
    if not (
        _os.environ.get("SETTINGS_FILE") or root.name == "deploy" or (run in (None, "local") and local.is_file())
    ):  # env 남김 — 설정 파일 자리 신호
        return
    import warnings  # python -m common.config.settings·pipeline.config·mcp_server.config — 영구 다리가 먼저 import해 runpy가 내는 경고(동작 무관)

    warnings.filterwarnings(
        "ignore", r"'(common\.config\.settings|pipeline\.config|mcp_server\.config)' found in sys\.modules", RuntimeWarning
    )
    from common.config import settings

    try:
        settings.pin_env()
    except (
        settings.SettingsError
    ) as e:  # 서버(dev·prd)에서 설정 파일을 못 읽거나 엔진·인계 칸이 틀림 — 시작하지 않음(STRICT, 값 없이 이유만)
        import sys

        print(
            f"[설정] 설정 파일 문제로 시작하지 않음(서버 — STRICT, 점검 명령은 entrypoint가 SETTINGS_LENIENT=1로 계속): {e}",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


_pin()
from common.core.fingerprint import CONTRACT, FINGERPRINT, legacy_names, pipeline_version  # noqa: E402,F401
