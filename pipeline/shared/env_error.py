"""엔진 실패가 환경(미설치·미설정) 탓인지 — 글자 단서로 가른다."""

# 환경(미설치·미설정) 실패 단서 — 한 곳(parse_engines·parse_scoring·실행판 공용). "not found"·"NotFoundError"처럼 넓게 잡으면
# 손상 PDF의 'PdfReadError: EOF marker not found'까지 env로 잡아 그 엔진을 실행 전체에서 건너뛰게 했음 → 구체적인 표현만.
ENV_ERR = (
    "미설정",
    "미설치",
    "ModuleNotFoundError",
    "No module named",
    "command not found",
    "FileNotFoundError",
    "TesseractNotFoundError",
    "NotInstalledError",
    "not installed",
    "SpawnError",
    "initialization fai",
)


def is_env_error(err):
    return bool(err) and any(k in err for k in ENV_ERR)
