"""op-07(사용자 10-30) — 코드가 선언한 의존성 지문(deploy/docker/DEPS_HASH)이 지금 requirements와 같다(deploy/release/deps_hash.sh와 같은 계산).
실행 이미지(*-runtime)는 시작 때 이 값과 이미지의 /app/docker/deps_hash를 견줘 다르면 멈춘다 — requirements를 바꾸고 DEPS_HASH를 안 고치면
여기서 걸림. 코드가 든 이미지(deploy/docker가 없음)에서는 건너뜀."""

import hashlib

from common.core.paths import DEPLOY_ROOT

D = DEPLOY_ROOT / "deploy" / "docker"


def test_deps_hash_matches_requirements():
    if not (D / "DEPS_HASH").is_file():
        print("[시험] deploy/docker 없음(코드가 든 이미지) — 건너뜀")
        return
    raw = b"".join((D / n).read_bytes() for n in ("requirements-core.txt", "requirements-image.txt")).replace(b"\r", b"")
    want = hashlib.sha256(raw).hexdigest()[:16]
    got = (D / "DEPS_HASH").read_text(encoding="utf-8").strip()
    assert got == want, (
        f"deploy/docker/DEPS_HASH({got}) ≠ requirements 지문({want}) — bash deploy/release/deps_hash.sh > deploy/docker/DEPS_HASH"
    )
