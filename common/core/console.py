"""표준 출력 글자 — CLI 진입점이 한 줄로 UTF-8 출력을 켠다(Windows cp949 콘솔·파이프 출력에서 한글이 깨지지 않게).

이 파일은 모든 층의 공용 의존이 되므로(code_fp) 작고 바뀌지 않게 둔다.
"""

import sys


def utf8_stdout(errors="replace"):
    """sys.stdout을 UTF-8로 — 쓸 수 없는 글자는 errors 규칙(None이면 인자를 안 준 것과 같음 = strict).
    실제 sys.stdout은 TextIOWrapper라 reconfigure가 있다."""
    sys.stdout.reconfigure(encoding="utf-8", errors=errors)
