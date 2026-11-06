#!/usr/bin/env bash
# 실행 이미지(*-runtime)의 ENTRYPOINT. 이미지에는 코드가 없다 — 서버 코드 폴더(저장소 트리 그대로)를 /app/deploy에
# 읽기 전용으로 붙여 띄운다. 여기서 세 가지를 보고 코드 폴더의 entrypoint(deploy/docker/entrypoint.sh)로 넘긴다:
#   ① 코드 폴더가 붙었나(없으면 종료 2) ② 이미지의 의존성 지문(/app/docker/deps_hash — 빌드 때 계산)과 코드가 선언한 지문
#   (deploy/docker/DEPS_HASH — deploy/release/deps_hash.sh)이 같은가(다르면 종료 2 — 나중에 ImportError로 조용히 깨지지 않게)
#   ③ 이미지 판(/app/docker/image_ref)과 코드 커밋(CODE_COMMIT — 코드 폴더 묶음에 build_ship.sh가 넣음, git clone이면 .git의 HEAD)을
#      한 줄로 남김(실행 기록).
# 코드가 든 이미지(data-pipeline·mcp-server)는 이 파일을 쓰지 않는다(ENTRYPOINT /app/docker/entrypoint.sh 그대로).
set -u
CODE=/app/deploy
if [ -d "$CODE" ] && { [ ! -r "$CODE" ] || [ ! -x "$CODE" ] || { [ -e "$CODE/deploy/docker/entrypoint.sh" ] && [ ! -r "$CODE/deploy/docker/entrypoint.sh" ]; }; }; then
  echo "[image] 코드 폴더는 붙었지만 사용자 $(id -u)가 읽을 수 없음(권한) — 서버의 판 폴더를 chown -R 10001:10001 또는 chmod -R a+rX 로 고칠 것(op-06)" >&2
  exit 2
fi
if [ ! -f "$CODE/deploy/docker/entrypoint.sh" ]; then
  echo "[image] 코드 폴더가 마운트되지 않음 — 서버 코드 폴더를 -v <코드 폴더>:/app/deploy:ro,z 로 붙여 띄울 것(이 실행 이미지에는 코드가 없음 — op-06)" >&2
  exit 2
fi
img=$(tr -d '\r\n' < /app/docker/deps_hash 2>/dev/null)
want=$(tr -d '\r\n' < "$CODE/deploy/docker/DEPS_HASH" 2>/dev/null)
if [ -z "$want" ] || [ "$img" != "$want" ]; then
  echo "[image] 의존성 지문이 다름 — 이미지 ${img:-없음} · 코드 ${want:-없음}(deploy/docker/DEPS_HASH). 코드의 requirements가 바뀌었으면 새 실행 이미지가 필요함(op-06)" >&2
  exit 2
fi
commit=$(tr -d '\r\n' < "$CODE/CODE_COMMIT" 2>/dev/null)
case "$commit" in
  ''|'$Format'*)   # git clone — 틀 글자 그대로(entrypoint.sh와 같은 판단). .git이 있으면 HEAD(코드 폴더 소유자가 달라 safe.directory)
    commit=""
    if [ -d "$CODE/.git" ] && command -v git >/dev/null 2>&1; then commit=$(git -c safe.directory='*' -C "$CODE" rev-parse --short HEAD 2>/dev/null); fi ;;
  *) commit=${commit##* } ;;
esac
echo "[image] 이미지 $(cat /app/docker/image_ref 2>/dev/null || echo '?') · 코드 ${commit:-커밋 표시 없음} · 의존성 $img" >&2
exec bash "$CODE/deploy/docker/entrypoint.sh" "$@"
