"""중복 문서 감지 — 한 번에 받은 원본 폴더 안에서 파일 내용 해시(SHA-256)가 같은 문서(완전 중복)를 찾는다. 삭제·이동은 하지 않는다.
받기(candidate_ready._dedup)가 부른다 — 파일은 쓰지 않는다(keep.txt는 _dedup이 씀)."""

import re
from pathlib import Path

from pipeline.extract.candidate_pick import _hidden
from pipeline.shared.srcsha import sha_of

# 대표 고르기 — 이름에 사본 표시("(1)"·"사본"·날짜 등)가 없는 것 → 최신 수정 → 큰 파일
_NOISE = re.compile(
    r"(\(\d+\)|\[\d+\]|[_\- ]?(copy|사본|복사본|최종|수정|final|rev\d*|v\d+(\.\d+)*)|(19|20)\d{2}[-_.]?\d{2}[-_.]?\d{2}|\d{8})", re.I
)


def run_folder(src, names):
    """폴더의 파일 중 names(이번 묶음)만 해시로 묶어 대표만 keep → (keep {대표 이름: sha256}, 중복 그룹 행).
    그룹 행 = {group, file, representative} — 2개 이상인 그룹만. sha256은 받기가 manifest에 남긴 값(srcsha.sha_of)."""
    files = sorted(p for p in Path(src).iterdir() if p.is_file() and not _hidden(p) and p.name in names)
    info = [(p, p.stat(), sha_of(p)) for p in files]
    groups: dict[str, list[int]] = {}
    for i, (_, _, sha) in enumerate(info):
        groups.setdefault(sha, []).append(i)
    keep, rows, gid = {}, [], 0
    for members in groups.values():
        rep = max(members, key=lambda i: (not _NOISE.search(info[i][0].stem), info[i][1].st_mtime, info[i][1].st_size))
        keep[info[rep][0].name] = info[rep][2]
        if len(members) == 1:
            continue
        gid += 1
        rows += [{"group": gid, "file": info[i][0].name, "representative": i == rep} for i in sorted(members)]
    return keep, rows
