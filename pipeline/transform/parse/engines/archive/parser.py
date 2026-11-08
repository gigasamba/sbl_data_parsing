"""압축 원본(.zip·.tar·.tgz·.tar.gz) — 안 파일 목록만 본문으로 낸다(pl-57). 안 파일의 글은 대표 결과의 첨부 단계
(represent/mail_attachments — 후보정 attachments)가 `[파일 <안 경로>]` 절로 붙인다. 표준 라이브러리만.

도구(tool) 인터페이스: ENGINES[이름](경로) → 공통 출력 계약(engines/_common/contract.py).
"""
import tarfile
import zipfile
from pathlib import Path

from pipeline.transform.parse.engines._common.contract import _with_tables


def parse_archive(path):
    """맨 바깥 목록만(안의 압축은 이름 그대로). zip·tar는 확장자로 고른다(내용으로 고르면 끝에 zip이 든 tar를 zip으로 읽음)."""
    if Path(path).suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
    else:
        with tarfile.open(path, mode="r:*") as t:
            names = [m.name for m in t.getmembers() if m.isfile()]
    return _with_tables(f"압축 안 파일 {len(names)}개\n" + "\n".join(names), [], "archive")


ENGINES = {"archive": parse_archive}
FORMATS = {"archive": (".zip", ".tar", ".tgz", ".gz")}
REQUIRES = {"modules": [], "tools": []}
PROFILED = set()
UNVERIFIED = set()
