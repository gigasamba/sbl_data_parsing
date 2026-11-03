#!/bin/bash
# 덧씌우기 묶음 만들기(release-and-patch.md §3) — 바뀐 파일만 서버 코드 폴더(live) 경로 그대로 + PATCH_MANIFEST.txt + PATCH_NOTES.md(서버 LLM용) + CHANGES.md.
#   bash deploy/release/make_patch.sh <시작점> <출력 폴더> [이번 이유 한 줄] [이번 묶음 요약 md]
#     <시작점> = last  : 직전에 올린 패치(패치 브랜치 맨 위 PATCH_MANIFEST의 '이번 덧씌우기' 커밋) 이후 — **기본(증분, 사용자 10-08)**
#              = image : 이미지 기준판(IMAGE_BASE) 이후 전부
#              = <커밋> : 그 커밋 이후 — 서버에 아직 안 올린 패치가 여러 개 쌓였을 때(사용자가 알려 줌) 서버에 마지막으로
#                         적용된 패치의 main 커밋을 주면 그 뒤 전부를 하나로 묶음(기존 패치 파일을 유지하는 누적 묶음)
#   S6b(10-27, V3 R7) — 이 저장소 배치(루트에 common·pipeline·mcp_server·resources, 배포물은 deploy/{docker,release,host})를 읽고,
#   묶음은 서버 코드 폴더(live) 경로 그대로 담는다(코디네이터 답 Q3 a) — 서버 적용은 `cp -a <묶음>/app <묶음>/deploy <live>/`:
#     <저장소>/{common,pipeline,mcp_server,resources}/X       → <출력>/app/deploy/<폴더>/X   (컨테이너 /app/deploy/<폴더> — compose.patch*.yml 마운트 원본)
#     <저장소>/deploy/docker/entrypoint.sh                     → <출력>/app/docker/entrypoint.sh (컨테이너 /app/docker)
#     <저장소>/deploy/release/{selftest_gate.sh,known_fail.txt,assets.py} → <출력>/app/docker/<이름> + <출력>/deploy/release/<이름>
#     <저장소>/deploy/host/X · deploy/release/X               → <출력>/deploy/host/X · deploy/release/X (호스트 스크립트 — systemd·사람이 live에서 부름)
#     · <출력>/prev/<같은 경로> (바뀌기 직전 판 — 서버 LLM 비교용) · PATCH_MANIFEST.txt('M '·'D ' 줄 — live 기준 경로) · PATCH_NOTES.md · CHANGES.md
#   PATCH_COMMIT=1 이면 출력을 패치 브랜치(PATCH_BRANCH, 기본 dev_server_patch)에 새 커밋으로 쌓음(이전 패치 커밋이 부모 — 이력 유지). push는 사람.
#   NOTES_ONLY=1 이면 파일·매니페스트·브랜치 커밋 없이 설명서(NOTES_NAME, 기본 PATCH_NOTES.md)와 app/deploy/common/PATCH_VERSION만 — 전체 덮어쓰기
#     묶음(release-and-patch.md §4)용: NOTES_ONLY=1 NOTES_NAME=RELEASE_NOTES.md make_patch.sh <직전 반입 커밋> <출력> …
#   '재파싱 필요?'는 경로가 아니라 **값**으로 정한다(S6b, VS3 R-2): 시작점·HEAD 코드를 임시 폴더에 풀어 인계 지문(common.FINGERPRINT —
#     다르면 다음 모듈이 옛 결과를 거부)·엔진 지문 18개(pipeline.extract.run_all.engine_code_fp — 다르면 그 엔진 원문 재파싱)·code_fp 5개(참고)를
#     각각 계산해 비교한다. 계산에 PY(기본: 저장소 .venv/bin/python, 없으면 python3 — 이미지와 같은 패키지 필요)를 쓰고, 계산이 실패하면 '판정 불가'로 적는다.
#   env-guide.md '이번 판에서 바뀐 env' 절의 새 줄도 자동으로 넣음.
#   IMAGE_BASE·IMAGE_TAG — 의존성(requirements*·Dockerfile·wheels)이 이미지 기준판 뒤 바뀌었으면 종료 코드 3(새 이미지 판 필요).
#     기본값은 env로 주지 않으면 deploy/docker/IMAGE_BASE 파일(한 줄 "<커밋 7자> <이미지 태그>" — 새 이미지 판을 반입할 때 그 릴리스 절차가 씀)을 읽는다.
#   버전(D-036, 사용자 10-29): 묶음의 app/deploy/common/PATCH_VERSION = HEAD의 저장소 루트 VERSION(SemVer). 오버레이 패치는 VERSION의 PATCH 자리를
#     올린 뒤 만든다 — 이미지 태그(IMAGE_TAG — 0.1.0 꼴)와 같으면 종료 코드 2(서버 버전 표기가 이미지와 구분되지 않음). MAJOR·MINOR가 다르면 경고만
#     (MINOR = 새 이미지 버전 — D-009).
#   옛 배치 거부(종료 코드 3): 기준판·시작점이 이 배치가 아니면(S6b 전 docker/ 배치·upstream deploy/ 배치 — 이미지 COPY·compose 마운트·호스트 스크립트
#     자리가 다름) 파일 교체·삭제만으로는 맞지 않으므로 묶음을 만들지 않는다 — 새 이미지 판 + 전체 덮어쓰기(release-and-patch.md §4·§5).
set -euo pipefail
SINCE_ARG="${1:?시작점(last|image|커밋)}"; OUT="${2:?출력 폴더}"; WHY="${3:-}"; NOTES="${4:-}"
[ -n "$NOTES" ] && NOTES="$(cd "$(dirname "$NOTES")" && pwd)/$(basename "$NOTES")"   # 아래 cd 전에 절대 경로로
case "$OUT" in /*|[A-Za-z]:*) ;; *) OUT="$(pwd)/$OUT" ;; esac
cd "$(git rev-parse --show-toplevel)"
REPO=$(pwd)
IMAGE_BASE_FILE="${IMAGE_BASE_FILE:-deploy/docker/IMAGE_BASE}"
_FB_COMMIT=""; _FB_TAG=""
if [ -f "$IMAGE_BASE_FILE" ]; then read -r _FB_COMMIT _FB_TAG < "$IMAGE_BASE_FILE" || true; fi
IMAGE_BASE="${IMAGE_BASE:-${_FB_COMMIT:-}}"; IMAGE_TAG="${IMAGE_TAG:-${_FB_TAG:-}}"; BR="${PATCH_BRANCH:-dev_server_patch}"
[ -n "$IMAGE_BASE" ] || { echo "[make_patch] 이미지 기준판 없음 — $IMAGE_BASE_FILE 또는 IMAGE_BASE=<커밋>"; exit 2; }
git rev-parse -q --verify "$IMAGE_BASE^{commit}" >/dev/null || {
  echo "[make_patch] 이미지 기준판 $IMAGE_BASE 이 이 저장소에 없음 — 옛 배치(upstream) 기준판이면 덧씌우기 불가, 새 이미지 판 필요(release-and-patch.md §5)"; exit 3; }
HAS_BR=$(git rev-parse -q --verify "refs/heads/$BR" >/dev/null && echo 1 || echo 0)
case "$SINCE_ARG" in
  image) SINCE="$IMAGE_BASE" ;;
  last)  if [ "$HAS_BR" = 1 ]; then SINCE=$(git show "$BR:PATCH_MANIFEST.txt" 2>/dev/null | sed -n 's/^이번 덧씌우기: main \([0-9a-f]*\).*/\1/p' | head -1); fi
         SINCE="${SINCE:-$IMAGE_BASE}" ;;
  *)     SINCE="$SINCE_ARG" ;;
esac
HEAD_C=$(git rev-parse --short HEAD); SINCE_C=$(git rev-parse --short "$SINCE"); IMG_C=$(git rev-parse --short "$IMAGE_BASE")
MODE=$([ "$SINCE_C" = "$IMG_C" ] && echo "이미지 기준판 이후 전부" || { [ "$SINCE_ARG" = last ] && echo "증분(직전 패치 이후)" || echo "누적(서버에 마지막으로 적용된 $SINCE_C 이후 — 그 사이 패치 포함)"; })

# 배치 확인 — 이 배치의 표지 파일 두 개(배포물 deploy/docker/Dockerfile · 루트 공용 코드 common/core/fingerprint.py)가 다 있어야 함
layout_ok() { git cat-file -e "$1:deploy/docker/Dockerfile" 2>/dev/null && git cat-file -e "$1:common/core/fingerprint.py" 2>/dev/null; }
layout_ok HEAD || { echo "[make_patch] HEAD가 이 저장소 배치(deploy/docker/Dockerfile·common/core/fingerprint.py)가 아님 — 다른 저장소에서 돌렸는지 확인"; exit 2; }
OLD_LAYOUT=""
for rev in $(printf '%s\n' "$IMG_C" "$SINCE_C" | sort -u); do layout_ok "$rev" || OLD_LAYOUT="$OLD_LAYOUT $rev"; done
if [ -n "$OLD_LAYOUT" ]; then
  echo "[make_patch] 기준판·시작점(${OLD_LAYOUT# })이 옛 배치(S6b 전 docker/ 또는 upstream deploy/)라 덧씌우기 불가 — 이미지 COPY·compose 마운트·호스트 스크립트 자리가 다름. 새 이미지 판 + 전체 덮어쓰기(release-and-patch.md §4·§5)"; exit 3
fi

DEPS=$(git diff --name-only "$IMAGE_BASE"..HEAD -- 'deploy/docker/requirements*.txt' 'deploy/docker/Dockerfile' 'deploy/docker/wheels' || true)
if [ -n "$DEPS" ]; then
  echo "[make_patch] 의존성이 기준판($IMG_C) 뒤 바뀜 — 덧씌우기 불가, 새 이미지 판 필요:"; echo "$DEPS" | sed 's/^/  /'; exit 3
fi

# 저장소 경로 → live 경로(한 파일이 두 자리에 갈 수 있음 — /app/docker에 들어가는 반입 도구는 호스트 deploy/release/에도)
CODE_SPECS=(common/ pipeline/ mcp_server/ resources/ deploy/docker/entrypoint.sh deploy/release/ deploy/host/)
IMG_TOOLS=" selftest_gate.sh known_fail.txt assets.py "
live_paths() {
  case "$1" in
    common/*|pipeline/*|mcp_server/*|resources/*) echo "app/deploy/$1" ;;
    deploy/docker/entrypoint.sh) echo "app/docker/entrypoint.sh" ;;
    deploy/release/*) echo "$1"; case "$IMG_TOOLS" in *" ${1#deploy/release/} "*) echo "app/docker/${1#deploy/release/}" ;; esac ;;
    deploy/host/*) echo "$1" ;;
  esac
}

NOTES_ONLY="${NOTES_ONLY:-0}"; NOTES_NAME="${NOTES_NAME:-PATCH_NOTES.md}"
rm -rf "$OUT"; mkdir -p "$OUT"
CHANGED=(); DELETED=(); NPREV=0
put() {   # put <git 판> <저장소 경로> <출력 하위 폴더(빈 값 = 묶음, prev = 비교용)>
  local lp
  for lp in $(live_paths "$2"); do mkdir -p "$OUT/${3:+$3/}$(dirname "$lp")"; git show "$1:$2" > "$OUT/${3:+$3/}$lp"; done
}
while IFS=$'\t' read -r st a b; do
  case "$st" in
    D) DELETED+=("$a") ;;
    R*) DELETED+=("$a"); CHANGED+=("$b") ;;
    *) CHANGED+=("$a") ;;
  esac
done < <(git diff --name-status -M "$SINCE"..HEAD -- "${CODE_SPECS[@]}")
if [ "$NOTES_ONLY" != 1 ]; then
  for f in ${CHANGED[@]+"${CHANGED[@]}"}; do
    put HEAD "$f" ""
    if git cat-file -e "$SINCE:$f" 2>/dev/null; then put "$SINCE" "$f" prev; NPREV=$((NPREV+1)); fi
  done
  for f in ${DELETED[@]+"${DELETED[@]}"}; do put "$SINCE" "$f" prev; done
fi
MCH=(); MDEL=()   # 매니페스트 줄(live 경로)
for f in ${CHANGED[@]+"${CHANGED[@]}"}; do for lp in $(live_paths "$f"); do MCH+=("$lp"); done; done
for f in ${DELETED[@]+"${DELETED[@]}"}; do for lp in $(live_paths "$f"); do MDEL+=("$lp"); done; done
# 버전 표기 파일(git 밖, 묶음에만 — D-036) — 이미지의 /app/deploy/VERSION은 오버레이로 못 바꿔서, 코드 버전을 오버레이 연결 폴더 common/에 둔다.
#   common.pipeline_version()이 VERSION·PATCH_VERSION 중 높은 버전을 쓴다(새 이미지 뒤 남은 옛 PATCH_VERSION은 지지 않음).
APP_VER=$(git show HEAD:VERSION 2>/dev/null | tr -d ' \t\r\n' || true)
printf '%s\n' "$APP_VER" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "[make_patch] HEAD의 저장소 루트 VERSION이 없거나 MAJOR.MINOR.PATCH 꼴이 아님(D-036)"; exit 2; }
if [ "$NOTES_ONLY" != 1 ]; then
  [ "$APP_VER" != "$IMAGE_TAG" ] || { echo "[make_patch] VERSION($APP_VER)이 이미지 태그와 같음 — 오버레이 패치는 VERSION의 PATCH 자리를 올린 뒤 만든다(D-009·D-036)"; exit 2; }
  [ "${APP_VER%.*}" = "${IMAGE_TAG%.*}" ] || echo "[make_patch] 경고: VERSION($APP_VER)의 MAJOR.MINOR가 이미지 태그($IMAGE_TAG)와 다름 — MINOR는 새 이미지 버전(D-009)"
fi
mkdir -p "$OUT/app/deploy/common"
echo "$APP_VER" > "$OUT/app/deploy/common/PATCH_VERSION"
[ "$NOTES_ONLY" = 1 ] || MCH+=("app/deploy/common/PATCH_VERSION")

# 재파싱 필요? — 값 비교(VS3 R-2). 판마다 코드를 임시 폴더에 풀어(git archive) 같은 python으로 계산한다.
PY=${PY:-}; [ -n "$PY" ] || { [ -x "$REPO/.venv/bin/python" ] && PY="$REPO/.venv/bin/python" || PY=python3; }
FP_CODE='import json, common
from common.core import artifacts as a
from pipeline.extract import run_all
print(json.dumps({"FINGERPRINT": common.FINGERPRINT, "code_fp": {l: a.code_fp(l) for l in sorted(a.LAYER_CODE)},
                  "engines": {e: run_all.engine_code_fp(e) for e in sorted(run_all.registry.engines())}}, sort_keys=True))'
FPTMP=$(mktemp -d); trap 'rm -rf "$FPTMP"' EXIT
fp_of() {   # fp_of <판> → JSON 한 줄(실패하면 빈 출력)
  local d="$FPTMP/$1"; mkdir -p "$d"
  local p specs=""   # mcp_server — 층 r(검색) 파일(VS6b R-1: 빠지면 r의 code_fp가 양쪽 다 빈 집합이라 늘 "같음"). 그 판에 있는 폴더만(git archive는 없는 경로에서 실패)
  for p in common pipeline mcp_server resources; do git cat-file -e "$1:$p" 2>/dev/null && specs="$specs $p"; done
  # shellcheck disable=SC2086
  git archive "$1" $specs | tar -x -C "$d" 2>/dev/null || return 0
  # 서버처럼 계산 — 신호(RUN_ENV·SETTINGS_FILE)를 빼고, S7b 전 판(옛 env LOCAL_RUN을 읽음)이면 그것도 뺀다. S7e2 — 코드가 읽은 적 없는 ENV_AUTOLOAD=0·
  # 옛 NO_PAID_CALLS env(11-03에 칸도 지움 — 지문 계산은 모델을 부르지 않음)는 지움(VS7e1 흔적 정리)
  (cd "$d" && env -u LOCAL_RUN -u RUN_ENV -u SETTINGS_FILE PYTHONPATH=. "$PY" -c "$FP_CODE" 2>/dev/null | tail -1) || true
}
FP_OLD=$(fp_of "$SINCE_C"); FP_NEW=$(fp_of "$HEAD_C")
REPARSE=$("$PY" - "$FP_OLD" "$FP_NEW" <<'EOF' 2>/dev/null || echo "판정 불가 — 지문 비교 스크립트 실패(사람이 FINGERPRINT·엔진 지문을 직접 비교)"
import json, sys
try:
    old, new = json.loads(sys.argv[1]), json.loads(sys.argv[2])
except ValueError:
    print("판정 불가 — 시작점 또는 HEAD의 지문 계산 실패(PY에 이미지와 같은 패키지가 있는지 확인, 사람이 FINGERPRINT·엔진 지문을 직접 비교)")
    sys.exit(0)
lines = []
if old["FINGERPRINT"] != new["FINGERPRINT"]:
    lines.append(f"예 — 인계 지문(FINGERPRINT) {old['FINGERPRINT']} → {new['FINGERPRINT']}: 적용 뒤 parse부터 다시(옛 _rep로 structure를 돌리면 종료 코드 3)")
eng = sorted(e for e in set(old["engines"]) | set(new["engines"]) if old["engines"].get(e) != new["engines"].get(e))
if eng:
    lines.append(f"예 — 엔진 지문이 바뀐 엔진 {len(eng)}개({', '.join(eng)}): 그 엔진의 원문 파싱 결과가 낡음으로 잡혀 다시 파싱")
if not lines:
    lines.append(f"아니오 — 인계 지문 {new['FINGERPRINT']}·엔진 지문 {len(new['engines'])}개 모두 같음(옛 결과로 다음 모듈 계속 가능)")
cf = [l for l in sorted(new["code_fp"]) if old["code_fp"].get(l) != new["code_fp"][l]]
lines.append("참고 — code_fp 바뀐 층: " + (", ".join(f"{l} {old['code_fp'].get(l)}→{new['code_fp'][l]}" for l in cf) if cf else "없음")
             + " (층 캐시 — p0는 엔진 지문과 별개로 run_all.py도 봄)")
print("\n- ".join(lines))
EOF
)
# env-guide.md '이번 판에서 바뀐 env' 절(번호가 아니라 제목으로 찾음) — 이 범위에서 새로 생긴 표 줄만(S1 전 판은 옛 자리 runbooks/)
sec3() { { git show "$1:docs/operations/env-guide.md" 2>/dev/null || git show "$1:runbooks/env-guide.md" 2>/dev/null; } \
  | awk '/^## .*이번 판에서 바뀐 env/{f=1;next} /^## /{f=0} f && /^\| / && !/^\| 판 \|/ && !/^\|---/' || true; }
ENVROWS=$(comm -13 <(sec3 "$SINCE" | sort) <(sec3 HEAD | sort) || true)

[ "$NOTES_ONLY" = 1 ] || {
  echo "기준 이미지 판: $IMAGE_TAG (main $IMG_C)"
  echo "이번 덧씌우기: main $HEAD_C ($(date +%Y-%m-%d))"
  echo "범위: main $SINCE_C..$HEAD_C — $MODE"
  echo "서버 전제: 서버 코드가 main $SINCE_C 판이어야 함(이미지 $IMAGE_TAG + 그 시점까지의 패치). 아니면 적용하지 말고 누적 묶음을 요청"
  echo "적용: release-and-patch.md §3-2 · PATCH_NOTES.md — 경로는 서버 코드 폴더(live) 기준 그대로(app/deploy/<폴더>/·app/docker/ = 컨테이너 마운트 원본, deploy/host/·deploy/release/ = 호스트 스크립트) 교체·'D ' 줄 삭제 · prev/는 비교용(적용 대상 아님)"
  echo; echo "## 바뀐 파일 (${#MCH[@]})"; [ ${#MCH[@]} -gt 0 ] && printf 'M %s\n' "${MCH[@]}" || true
  echo; echo "## 지울 파일 (${#MDEL[@]})"; [ ${#MDEL[@]} -gt 0 ] && printf 'D %s\n' "${MDEL[@]}" || true
} > "$OUT/PATCH_MANIFEST.txt"

[ "$NOTES_ONLY" = 1 ] || { if [ "$HAS_BR" = 1 ] && git cat-file -e "$BR:CHANGES.md" 2>/dev/null; then git show "$BR:CHANGES.md"; else echo "# 덧씌우기 이력 (지우지 않음 — 패치마다 한 절)"; fi
  echo; echo "## $(date +%Y-%m-%d) · main $SINCE_C..$HEAD_C · $MODE · 파일 ${#MCH[@]}개 · 지울 ${#MDEL[@]}개"
  [ -n "$WHY" ] && echo "- $WHY"
  git log --no-merges --format='- %h %s' "$SINCE".."HEAD" -- "${CODE_SPECS[@]}" | cut -c1-160
} > "$OUT/CHANGES.md"

# PATCH_NOTES.md — 서버(개발·수집) 로컬 LLM이 먼저 읽는 설명서(사용자 10-08): 무엇을 왜 바꿨나·어떤 파일·적용 때 비교할 점.
{
  echo "# 패치 설명서 — 이미지 $IMAGE_TAG 위 덧씌우기 · main $SINCE_C → $HEAD_C ($(date +%Y-%m-%d), $MODE)"
  echo
  echo "> 서버 LLM에게: 이 폴더의 파일을 **무조건 덮어쓰지 말고**, 이 설명서와 PATCH_MANIFEST.txt를 먼저 끝까지 읽은 뒤"
  echo "> 서버의 현재 코드(live)와 비교해서 적용하세요. 절차 정본: docs/operations/release-and-patch.md §3-2(덧씌우기)·§4(전체 덮어쓰기)."
  echo "> **서버에서 자체로 진행한 것이 먼저입니다.** 적용 전에 /srv/rag/reports/server-changes.md(+ server-changes/<ID>.diff)와 서버 설정 파일(/srv/rag/env/settings.yaml — S7e1 판 전에는 pipeline.env)을 읽고, 서버의 코드 수정·옵션 값·서버 전용 스크립트를 살린 채 이 패치를 그 위에 합치세요. 충돌이 나도 멈추지 말고 아래 기준으로 합친 뒤 합친 방법을 기록에 남기세요."
  echo
  echo "## 적용 규칙 요약"
  if [ "$NOTES_ONLY" = 1 ]; then   # 전체 덮어쓰기(release-and-patch §4): 매니페스트·prev/ 없음
    echo "0. 서버 판 기록(OP7)의 마지막 반입이 main $SINCE_C 인지 확인 — 더 앞이면 그 사이 RELEASE_NOTES도 같이 읽기."
    echo "1. 코드 폴더 전체를 backup-<날짜시각>/ 으로 복사한 뒤 받은 묶음으로 통째 교체(live/app/ = 컨테이너 마운트 원본, live/deploy/ = 호스트 스크립트). 설정 파일(/srv/rag/env/settings.yaml — S7e1 판 전에는 pipeline.env)·sources.json(/srv/rag/env/)은 코드 밖이라 그대로."
    echo "2. 서버 자체 개발 기록(/srv/rag/reports/server-changes.md)의 '서버에만'·'PC 보냄' 행마다 — 새 코드에 그 변경이 이미 있으면(아래 커밋 목적에 그 SC- ID) 행을 'PC 반영됨 <커밋>'으로, 없으면 새 코드 위에 다시 얹는다: <ID>.diff가 그대로 안 얹히면 행의 '무엇·왜'대로 새 구조에 손으로 옮기고, 같은 줄·같은 동작이 다르면 서버 쪽 동작을 남긴 채 새 기능을 둘레에 붙인다. 행에 '다시 얹음' + 합친 방법 한 줄. 기록 밖에서 backup과 새 코드가 다른 파일(기록 안 된 서버 수정)도 서버 자체 변경으로 보고 같은 방식 + 기록에 행 추가."
    echo "3. 옵션: 서버 설정 파일(settings.yaml — 옛 pipeline.env)에 서버가 적은 값은 그대로(패치가 기본값을 바꿔도). 서버가 코드 안 기본값을 바꿨던 것은 같은 칸으로 설정 파일에 옮겨 유지. 아래 '바뀐 env'에서 이름이 바뀌거나 없어진 옵션은 서버 값을 새 이름으로 옮기고, 새 옵션은 기본값이되 서버에서 일부러 끈 기능(=0)과 겹치면 끈 채로. 옮기거나 유지한 옵션은 기록에 적는다."
    echo "4. 확인: \`docker run --rm <연결 옵션> <태그> check-modules\` · \`bash deploy/release/selftest_gate.sh docker run --rm <연결 옵션> <태그> selftest\`(release-and-patch.md §3-3). 실패하면 서버 변경은 살린 채 패치 쪽 연결(함수 이름·인자·import)을 맞춰 다시 확인, 그래도 안 되면 그 패치 항목만 빼고(서버 쪽 판 유지) 적용한 뒤 issues.md에 적는다. 서버 변경을 버려서 통과시키지 않는다."
    echo "5. 보고(표, 적용 뒤): 다시 얹은 서버 변경(SC- ID·합친 방법) · 유지·이전한 옵션 · 뺀 패치 항목(있으면) · 판 = main $HEAD_C (판 기록 OP7에 한 줄)."
  else
    echo "0. 전제 확인: 서버 판 기록(OP7)의 마지막 적용 패치가 main $SINCE_C 인지 본다. 다르면(더 앞이면) 적용하지 말고 멈춘 뒤 '누적 묶음 필요 — 서버 마지막 적용 = <커밋>'으로 보고."
    echo "1. live 전체를 backup-<날짜시각>/ 으로 먼저 복사. 서버 자체 개발 기록(/srv/rag/reports/server-changes.md)과 서버 설정 파일(settings.yaml — 옛 pipeline.env)을 읽어 '서버에만'·'PC 보냄' 행의 파일·옵션 목록을 뽑아 둔다 — 이것들이 이번 병합에서 가장 먼저 지킬 대상."
    echo "2. 대상은 PATCH_MANIFEST.txt의 줄만 — \`M\` 교체, \`D\` 삭제. 경로는 live 기준 그대로: app/deploy/<폴더>/X → live/app/deploy/<폴더>/X · app/docker/X → live/app/docker/X · deploy/host/X·deploy/release/X → live/deploy/…/X. 목록 밖 파일·prev/ 폴더는 적용 대상 아님."
    echo "3. M 파일마다 live와 **prev/(바뀌기 직전 판)** 를 비교 — 같으면(서버에서 안 고침) 새 파일로 그대로 교체 · 다르면 서버 자체 변경(기록에 없어도 — 그 자리에서 기록에 행 추가):"
    echo "   - 새 파일에 그 변경이 이미 있으면(아래 커밋 목적에 그 SC- ID) 교체하고 행을 'PC 반영됨 <커밋>'으로."
    echo "   - 없으면 새 파일 위에 서버 변경을 다시 얹는다. <ID>.diff가 그대로 안 얹히면 행의 '무엇·왜'대로 새 구조에 손으로 옮긴다. 패치와 서버가 같은 줄·같은 동작을 다르게 바꿨으면 서버 쪽 동작을 남기고 패치의 나머지 새 기능을 그 둘레에 붙인다. 행에 '다시 얹음 <패치 커밋>' + 합친 방법 한 줄."
    echo "   - prev/에 없는데 live에 있는 파일은 서버가 만든 파일 — 덮지 말고, 새 파일과 합칠 수 있으면 같은 기준으로 합친다."
    echo "   D 파일: live가 prev/와 같으면 삭제. 다르면 패치 노트에서 코드가 옮겨진 곳에 서버 변경을 다시 얹고, 옮겨진 곳이 없으면(기능 삭제) 서버가 쓰는지 보고 쓰면 파일을 남긴다."
    echo "4. 옵션: 서버 설정 파일(settings.yaml — 옛 pipeline.env)에 서버가 적은 값은 그대로(패치가 기본값을 바꿔도). 서버가 코드 안 기본값(상수·options.conf 등)을 바꿨던 것은 같은 칸으로 설정 파일에 옮겨 둔 뒤 새 파일로 교체. 아래 '바뀐 env'에서 이름이 바뀌거나 없어진 옵션은 서버 값을 새 이름으로 옮기고, 새 옵션은 기본값이되 서버에서 일부러 끈 기능(=0)과 겹치면 끈 채로. 옮기거나 유지한 옵션은 기록에 적는다."
    echo "5. 확인: \`docker run --rm <연결 옵션> <태그> check-modules\` 통과 · 작업 컨테이너 selftest 1개(\`bash deploy/release/selftest_gate.sh …\`). 실패하면 서버 변경은 살린 채 패치 쪽 연결(함수 이름·인자·import)을 맞춰 다시 확인, 그래도 안 되면 그 패치 항목만 빼고(서버 쪽 판 유지) 나머지를 적용한 뒤 뺀 항목·이유를 issues.md에. 서버 변경을 버려서 통과시키지 않는다."
    echo "6. 보고(표, 적용 뒤): 교체·삭제 수 · 다시 얹은 서버 변경(SC- ID·합친 방법) · 유지·이전한 옵션 · 뺀 패치 항목(있으면) · 판 = 이미지 $IMAGE_TAG + patch $HEAD_C (판 기록 OP7에 한 줄)."
  fi
  echo
  echo "## 재파싱 필요? (main $SINCE_C ↔ $HEAD_C 지문 값 비교)"
  echo "- $REPARSE"
  echo
  echo "## 이번 판에서 바뀐 env (env-guide.md §3에서 자동 — .env와 대조)"
  if [ -n "$ENVROWS" ]; then echo "| 판 | 바뀐 것 | 서버 할 일 |"; echo "|---|---|---|"; echo "$ENVROWS"; else echo "- 없음(이 범위에서 env-guide §3 새 줄 없음)"; fi
  echo
  echo "## 이번 묶음 요약 (사람이 씀)"
  if [ -n "$NOTES" ] && [ -f "$NOTES" ]; then cat "$NOTES"; else echo "(요약 없음 — make_patch.sh 4번째 인자로 요약 md를 주세요. 아래 자동 항목만 참고.)"; fi
  echo
  echo "## 항목별 변경 (커밋 기록에서 자동 — 오래된 것부터, 문서만 바꾼 커밋은 뺌)"
  for c in $(git log --no-merges --reverse --format=%h "$SINCE".."HEAD" -- "${CODE_SPECS[@]}"); do
    files=$(git diff-tree --no-commit-id --name-only -r "$c" -- "${CODE_SPECS[@]}" | grep -v -E '\.md$' | tr '\n' ' ' || true)
    [ -z "${files// /}" ] && continue
    echo; echo "### $c $(git log -1 --format=%s "$c" | cut -c1-200)"
    git log -1 --format=%b "$c" | grep -v -E '^(Co-Authored-By|Claude-Session):' | sed '/^$/d' | head -6 | sed 's/^/> /' || true
    echo "- 파일: $(echo "$files" | cut -c1-600)"
  done
  echo; echo "## 지울 파일"; [ ${#MDEL[@]} -gt 0 ] && printf -- '- %s\n' "${MDEL[@]}" || echo "- 없음"
} > "$OUT/$NOTES_NAME"

MSG="[make_patch] $OUT — 바뀐 ${#MCH[@]}(직전 판 $NPREV) · 지울 ${#MDEL[@]} · $SINCE_C → $HEAD_C · $MODE · $NOTES_NAME$([ -n "$NOTES" ] && [ -f "$NOTES" ] && echo ' (요약 포함)' || echo ' (요약 없음)')"
if [ "${PATCH_COMMIT:-0}" = 1 ] && [ "$NOTES_ONLY" != 1 ]; then   # 패치 브랜치에 새 커밋(트리 = 이번 묶음만, 부모 = 이전 패치 커밋)
  IDX=$(mktemp); rm -f "$IDX"
  T=$(GIT_INDEX_FILE="$IDX" git --work-tree="$OUT" add -A . 2>/dev/null && GIT_INDEX_FILE="$IDX" git write-tree); rm -f "$IDX"
  P=$([ "$HAS_BR" = 1 ] && echo "-p $(git rev-parse "$BR")" || true)
  C=$(printf '덧씌우기: main %s → %s (%s)\n\n%s\n' "$SINCE_C" "$HEAD_C" "$MODE" "${WHY:-}$(printf '\n\nCo-Authored-By: Claude <noreply@anthropic.com>')" | git commit-tree "$T" $P)
  git update-ref "refs/heads/$BR" "$C"
  MSG="$MSG · 브랜치 $BR ← $(git rev-parse --short "$C")"
fi
echo "$MSG"
