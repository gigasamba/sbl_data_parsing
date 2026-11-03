# start_mcp.sh·start_ui.sh가 source — 저장소 루트 settings.yaml 하나만 읽게 하고(사용자 10-29 — 옛 이 폴더 settings.yaml 덮기 파일·validation.env
# 없앰), 저장소 루트에서 띄운다. 페이지 칸은 루트 파일의 mcp 절(mcp.dev·mcp.server)과 PG 접속(required.pg — mc-19), 외부 임베딩은 guard.no_paid_calls.
# 파일 안 상대 경로는 저장소 루트 기준이라 다른 장비·OS에서도 저장소 위치만 맞으면 그대로 돈다.
V="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$V/../.." && pwd)"   # validation/search_ui/ → 저장소 루트(S6a — 한 단 깊어짐)
cd "$REPO"
[ -f "$REPO/settings.yaml" ] || { echo "[검증 페이지] $REPO/settings.yaml 없음 — settings.sample.yaml을 보고 만듦(README §4-2)" >&2; exit 2; }
unset SETTINGS_FILE   # 셸에 남은 다른 설정 파일 자리를 쓰지 않음 — RUN_ENV=local이면 코드가 루트 settings.yaml을 읽음
export PYTHONPATH="$REPO" PYTHONUTF8=1
# Windows(Git Bash)면 .venv/Scripts, 그 밖은 .venv/bin
if [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"; else PY="$REPO/.venv/Scripts/python.exe"; fi
