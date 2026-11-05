"""원본 sha256 한 번만 — 받기(candidate_ready)가 manifest.jsonl에 남긴 sha256을 뒤 프로세스가 다시 읽지 않고 쓴다.
manifest 행의 `sha256_stat`(해시한 파일의 [크기, 고친 시각 ns])이 지금 파일과 같을 때만 그 값을 쓰고(같은 파일·하드 링크), 아니면
(회전된 준비 파일·다른 파일·manifest 없음) contract.file_hash로 다시 구한다 — 결과는 바이트 그대로."""

import functools
import json
from pathlib import Path

from common.config import settings as C
from common.core.contract import file_hash


def stat_of(p):
    """manifest `sha256_stat` 값 — [크기, 고친 시각 ns](contract.file_hash 캐시와 같은 열쇠)."""
    st = Path(p).stat()
    return [st.st_size, st.st_mtime_ns]


@functools.cache
def _rows(man, mtime_ns):
    """manifest 경로(+ 고친 시각 — 다시 쓰면 다시 읽음) → {파일 이름: (sha256, sha256_stat)}."""
    out = {}
    for ln in Path(man).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("sha256") and r.get("sha256_stat"):
                out[r["file_name"]] = (r["sha256"], r["sha256_stat"])
    return out


def sha_of(p):
    """파일 p의 sha256 — 이번 실행 manifest(SOURCE_MANIFEST)에 같은 파일의 값이 있으면 그 값, 없으면 file_hash."""
    man = C.cfg().paths.source_manifest
    if man and Path(man).is_file():
        hit = _rows(man, Path(man).stat().st_mtime_ns).get(Path(p).name)
        if hit and hit[1] == stat_of(p):
            return hit[0]
    return file_hash(p)
