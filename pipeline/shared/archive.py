"""압축 원본(.zip·.tar·.tgz·.tar.gz) 읽기 한 곳(pl-57) — 받기의 거르기(`check`)와 대표 결과의 첨부 단계(`entries`)가 같이 쓴다.
안의 압축은 한 단계 더 풀고 그 밑은 파일 그대로 둔다. 안전 상한(풀린 크기 합계·파일 수)은 설정 `tuning.extract.archive`."""

import io
import tarfile
import zipfile
import zlib
from pathlib import Path

from pipeline import config as pc

EXTS = (".zip", ".tar", ".tgz", ".gz")  # .tar.gz의 확장자는 .gz — tar가 아닌 .gz는 check가 unsupported_archive
BROKEN = (zipfile.BadZipFile, zipfile.LargeZipFile, tarfile.TarError, EOFError, OSError, zlib.error)


def kind_of(name):
    """확장자로 고름(내용으로 고르지 않음 — 끝에 zip이 든 tar를 zip으로 읽지 않게)."""
    ext = Path(name).suffix.lower()
    return "zip" if ext == ".zip" else "tar" if ext in EXTS else None


def _open(src, kind):
    if kind == "zip":
        return zipfile.ZipFile(src)
    return tarfile.open(name=src, mode="r:*") if isinstance(src, Path) else tarfile.open(fileobj=src, mode="r:*")


def _members(a, kind):
    """(이름, 풀린 크기, 암호?) — 폴더·링크는 뺌."""
    if kind == "zip":
        return [(i.filename, i.file_size, bool(i.flag_bits & 1)) for i in a.infolist() if not i.is_dir()]
    return [(m.name, m.size, False) for m in a.getmembers() if m.isfile()]


def _read(a, kind, name):
    return a.read(name) if kind == "zip" else a.extractfile(name).read()  # isfile()인 항목만 오므로 extractfile은 None이 아님


def _read_inner(data, kind, name):
    with _open(io.BytesIO(data), kind) as b:
        return _read(b, kind, name)


def _walk(p, kind):
    """(안 경로, 풀린 크기, 암호?, 읽기 함수) — 안의 압축은 크기가 상한 안일 때만 한 단계 풀고, 풀리지 않으면(tar 아닌 .gz·깨짐)
    보통 파일로 둔다(바깥 압축 전체를 버리지 않게). 읽기 함수는 다음 항목으로 넘어가기 전에만 쓴다."""
    cap = pc.cfg().extract.archive.max_total_mb * 1024 * 1024
    with _open(p, kind) as a:
        for name, size, enc in _members(a, kind):
            inner, sub, data = kind_of(name), None, b""
            if inner and not enc and size <= cap:
                data = _read(a, kind, name)
                try:
                    with _open(io.BytesIO(data), inner) as b:
                        sub = _members(b, inner)
                except BROKEN:
                    sub = None
            if sub is None:
                yield name, size, enc, lambda name=name: _read(a, kind, name)
            else:
                for n2, s2, e2 in sub:
                    yield f"{name}/{n2}", s2, e2, lambda n2=n2, data=data, inner=inner: _read_inner(data, inner, n2)


def check(p):
    """받기의 거르기 — 건너뛸 이유(`encrypted_archive`·`broken_archive`·`archive_too_big`·`unsupported_archive`) 또는 None(압축 아님·풀 수 있음)."""
    p = Path(p)
    kind = kind_of(p.name)
    if kind is None:
        return None
    if p.suffix.lower() == ".gz" and not tarfile.is_tarfile(p):
        return "unsupported_archive"
    cap = pc.cfg().extract.archive
    total = n = 0
    try:
        for _name, size, enc, _read_fn in _walk(p, kind):
            if enc:
                return "encrypted_archive"
            n, total = n + 1, total + size
            if n > cap.max_files or total > cap.max_total_mb * 1024 * 1024:
                return "archive_too_big"
    except BROKEN:
        return "broken_archive"
    return None


def entries(p):
    """첨부 단계 — 안 파일을 하나씩 {name, bytes, depth}로(메일 첨부 항목과 같은 모양). 거르기(check)를 지난 원본만 온다."""
    p = Path(p)
    kind = kind_of(p.name)
    if kind is None:
        return
    for name, _size, _enc, read in _walk(p, kind):
        yield {"name": name, "bytes": read(), "depth": 0}
