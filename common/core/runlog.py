#!/usr/bin/env python3
"""로그 글자의 비밀 가림(_mask — jsonlog가 씀, _LABEL — settings가 씀). 실행 기록 파일·묶음(session·note)은 op-13에 지움
(로그는 Postgres applog만, 사람이 보는 실행 출력은 컨테이너 로그 `podman logs`)."""

import re

# L8a — 로그에 비밀값이 그대로 남지 않게. 커넥션
# 문자열의 UID= 같은 비식별 값은 안 가림 — 식별자(authorization·토큰·비밀번호·AWS 비밀키·DSN 비밀번호)만.
# 트레이스백이 접속 문자열을 그대로 물고 나오는 경우(pyodbc 등)까지 커버. key=value·key:"value"·JSON
# {"key": "value"}(앞뒤 따옴표 어느 쪽에도 가능) 세 모양 다 받음 — "토큰" 같은 일반 단어(completion_tokens=18,
# max_tokens, tokens(), token_budget, ev_tokens5)는 라벨 뒤에 구분자(=·:)가 바로 안 오므로 안 걸림(독립 검토
# 10-12, tests/server/common/test_jsonlog.py의 no-over-masking 표로 고정).
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
