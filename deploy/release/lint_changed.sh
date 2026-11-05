#!/usr/bin/env bash
# 커밋 전 점검 — 바꾼 파이썬 파일만 ruff(린트·포맷)·mypy, 그리고 모듈 경계. CLAUDE.md "커밋 전 점검".
#   bash deploy/release/lint_changed.sh            # 스테이지·작업 트리에서 바뀐 파일(HEAD 기준)
#   bash deploy/release/lint_changed.sh <커밋>      # 그 커밋 이후 바뀐 파일(브랜치 전체 — push 전)
#   FIX=1 bash deploy/release/lint_changed.sh       # ruff 자동 수정·포맷까지(지문 보호 파일은 늘 제외)
#   ALL=1 bash deploy/release/lint_changed.sh       # 저장소 전체 파이썬 파일(push 전 — .githooks/pre-push)
# 종료 코드: 0 통과 · 1 경고 있음 · 2 도구 없음. 바이트가 캐시 열쇠인 파일(엔진·인계 4개·지시서 패키지·valid_env)은
# pyproject.toml의 제외 목록대로 빠진다(ruff force-exclude · 아래 SKIP). bash 3.2(macOS)·4/5(RHEL)·Git Bash(Windows).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
if [ -x .venv/bin/python ]; then BIN=.venv/bin; else BIN=.venv/Scripts; fi
for t in ruff mypy; do
  [ -x "$BIN/$t" ] || [ -x "$BIN/$t.exe" ] || { echo "[점검] $t 없음 — uv pip install --python $BIN/python -r requirements-dev.txt" >&2; exit 2; }
done
BASE=${1:-HEAD}
SKIP='^(pipeline/transform/parse/engines/|common/core/(contract|repfmt|terms|text)\.py$|resources/|valid_env/|output/|validation/e2e/triple_extract/)'
if [ "${ALL:-0}" = 1 ]; then
  FILES=$(git ls-files -- '*.py' | grep -Ev "$SKIP" || true)
else
  FILES=$( { git diff --name-only --diff-filter=ACMR "$BASE" -- '*.py'; git diff --name-only --cached --diff-filter=ACMR -- '*.py'; } \
           | sort -u | grep -Ev "$SKIP" || true)
fi
if [ -z "$FILES" ]; then echo "[점검] 바뀐 파이썬 파일 없음(지문 보호 파일 제외)"; else
  N=$(printf '%s\n' "$FILES" | wc -l | tr -d ' ')
  echo "[점검] 바뀐 파일 ${N}개"   # ${N} — bash 3.2는 변수 바로 뒤 한글을 이름으로 읽음
fi
rc=0
if [ -n "$FILES" ]; then
  # shellcheck disable=SC2086
  if [ "${FIX:-0}" = 1 ]; then "$BIN/ruff" check --force-exclude --fix $FILES; "$BIN/ruff" format --force-exclude $FILES; fi
  # shellcheck disable=SC2086
  "$BIN/ruff" check --force-exclude $FILES || rc=1
  # shellcheck disable=SC2086
  "$BIN/ruff" format --force-exclude --check $FILES || { echo "[점검] 포맷 다름 — FIX=1로 다시(포맷은 기능 변경과 다른 커밋)"; rc=1; }
  # shellcheck disable=SC2086
  PYTHONPATH=. "$BIN/mypy" --follow-imports=silent $FILES || rc=1
fi
PYTHONPATH=. "$BIN/python" -m common.check.check_modules >/dev/null || { echo "[점검] 모듈 경계 위반 — python -m common.check.check_modules"; rc=1; }
[ $rc = 0 ] && echo "[점검] 통과" || echo "[점검] 고칠 것 있음(위 출력)"
exit $rc
