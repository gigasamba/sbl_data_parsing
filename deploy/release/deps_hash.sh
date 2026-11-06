#!/usr/bin/env bash
# 의존성 지문 — 코드 폴더를 마운트해 쓰는 실행 이미지(*-runtime)와 그 코드가 같은 의존성 묶음인지 가르는 값.
# = sha256(deploy/docker/requirements-core.txt + requirements-image.txt, CR 뺌) 앞 16자. 이미지 빌드(Dockerfile *-runtime 단계)가 같은 계산으로
# /app/docker/deps_hash에 적고, 코드는 deploy/docker/DEPS_HASH(이 스크립트로 만든 파일)로 선언한다 — 실행 이미지 시작 때 둘이 다르면 멈춤.
# 휠 목록은 넣지 않는다(deploy/docker/wheels/는 git 밖이라 코드 쪽에서 같은 값을 못 만듦) — 휠 버전은 requirements의 == 고정이 정함.
# 사용: bash deploy/release/deps_hash.sh                 # 값 출력
#       bash deploy/release/deps_hash.sh > deploy/docker/DEPS_HASH   # requirements를 바꾼 커밋에서 다시 만듦(시험 test_deps_hash가 대조)
set -euo pipefail
cd "$(dirname "$0")/../.."
cat deploy/docker/requirements-core.txt deploy/docker/requirements-image.txt | tr -d '\r' | sha256sum | cut -c1-16
