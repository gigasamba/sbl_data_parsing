#!/bin/bash
# 반입 판정(V2-R5, I3 10-26) — selftest를 돌려 "알려진 FAIL(known_fail.txt) 밖의 FAIL 0개"면 종료 코드 0, 아니면 1.
#   selftest 자체의 종료 코드(FAIL이 하나라도 있으면 1)는 그대로 두고, 이 스크립트가 그 출력을 읽어 판정만 한다.
#   bash deploy/release/selftest_gate.sh docker run --rm <태그> selftest                # PC·서버 호스트(저장소·코드 폴더 루트에서 — S6b, 옛 docker/)
#   bash deploy/release/selftest_gate.sh ssh <서버> "docker run --rm <태그> selftest"    # 원격(build_ship.sh 4단계)
#   docker run --rm --entrypoint bash <태그> /app/docker/selftest_gate.sh /app/docker/entrypoint.sh selftest   # 이미지 안 목록으로
#   KNOWN_FAIL=<파일>로 목록을 바꿀 수 있다(기본: 이 스크립트 옆 known_fail.txt — 이미지에는 /app/docker/known_fail.txt).
# 통과 조건: 요약 줄("N/M 통과")이 있고 · selftest 종료 코드가 0, 또는 1이면서 FAIL 줄이 모두 목록 안.
#   (종료 코드 1인데 FAIL 줄이 없으면 — PC의 단계 4 도구 목록 어긋남 등 — 실패로 본다.)
#   S6b(D-020) — 이미지 2개: data-pipeline·mcp-server — 둘 다 FAIL 0(11-02 — 알려진 FAIL 목록 비움, 기대 줄 "[판정] 통과 — FAIL 0").
set -uo pipefail
[ $# -gt 0 ] || { echo "사용: bash selftest_gate.sh <selftest 명령…>" >&2; exit 2; }
KNOWN_FAIL=${KNOWN_FAIL:-$(dirname "$0")/known_fail.txt}
[ -f "$KNOWN_FAIL" ] || { echo "[판정] 알려진 FAIL 목록 없음: $KNOWN_FAIL" >&2; exit 2; }
known=$(sed 's/#.*//' "$KNOWN_FAIL" | tr -d ' \t\r' | grep -v '^$' || true)
is_known() { [ -n "$known" ] && printf '%s\n' "$known" | grep -qxF "$1"; }

log=$(mktemp); trap 'rm -f "$log"' EXIT
"$@" 2>&1 | tee "$log"; rc=${PIPESTATUS[0]}

fails=$(sed -n 's/^FAIL \([^ ]*\).*/\1/p' "$log")
unknown=""; nknown=0
for f in $fails; do
  if is_known "$f"; then nknown=$((nknown + 1)); else unknown="$unknown $f"; fi
done
for p in $(sed -n 's/^PASS \([^ ]*\).*/\1/p' "$log"); do
  is_known "$p" && echo "[안내] 알려진 FAIL $p 이 PASS — $KNOWN_FAIL 에서 지울 수 있음"
done

echo
if ! grep -Eq '^[0-9]+/[0-9]+ 통과' "$log"; then
  echo "[판정] 실패 — selftest 요약 줄 없음(종료 코드 $rc, 실행 자체가 중간에 멈춤)"; exit 1
elif [ -n "$unknown" ]; then
  echo "[판정] 실패 — 알려진 목록 밖 FAIL:$unknown (종료 코드 $rc)"; exit 1
elif [ "$rc" = 0 ]; then
  echo "[판정] 통과 — FAIL 0"; exit 0
elif [ "$rc" = 1 ] && [ "$nknown" -gt 0 ]; then
  echo "[판정] 통과 — FAIL ${nknown}개 모두 알려진 것($KNOWN_FAIL) · selftest 종료 코드 1"; exit 0
else
  echo "[판정] 실패 — 종료 코드 $rc, FAIL 줄 없음(도구 목록 어긋남 등 위 출력 확인)"; exit 1
fi
