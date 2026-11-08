"""압축 원본(.zip·.tar·.tgz·.tar.gz) 읽기 한 곳(pl-57) — 받기의 거르기(`check`)와 꺼내기(`members` — unpack, pl-63)가 같이 쓴다.
거르기는 안의 압축을 한 단계 더 열어 보고, 꺼내는 깊이는 설정 `tuning.extract.attach`(unpack). 안전 상한(풀린 크기 합계·파일 수)은 설정 `tuning.extract.archive`."""

import io
import tarfile
import zipfile
import zlib
from pathlib import Path

from pipeline import config as pc
from pipeline.shared.ext_groups import IMG_EXTS

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


def _cap_bytes():
    return pc.cfg().extract.archive.max_total_mb * 1024 * 1024


def _members(a, kind):
    """(이름, 풀린 크기, 암호?, 항목) — 폴더·링크는 뺌. 항목(ZipInfo·TarInfo)으로 읽는다(이름으로 다시 찾지 않음)."""
    if kind == "zip":
        return [(i.filename, i.file_size, bool(i.flag_bits & 1), i) for i in a.infolist() if not i.is_dir()]
    return [(m.name, m.size, False, m) for m in a.getmembers() if m.isfile()]


def _read(a, kind, item):
    return a.read(item) if kind == "zip" else a.extractfile(item).read()  # isfile()인 항목만 오므로 extractfile은 None이 아님


def _walk(p, kind):
    """거르기용 목록 (안 경로, 풀린 크기, 암호?) — 안의 압축은 크기가 상한 안일 때만 한 단계 풀고, 풀리지 않으면(tar 아닌 .gz·깨짐)
    보통 파일로 둔다(바깥 압축 전체를 버리지 않게). 안의 압축은 남은 상한(합계 − 지금까지)보다 작을 때만 연다."""
    cap, seen = _cap_bytes(), 0
    with _open(p, kind) as a:
        for name, size, enc, item in _members(a, kind):
            inner, b, sub = kind_of(name), None, []
            if inner and not enc and size <= cap - seen:
                try:
                    b = _open(io.BytesIO(_read(a, kind, item)), inner)
                    sub = _members(b, inner)
                except BROKEN:
                    if b is not None:
                        b.close()
                    b = None
            if b is None:
                seen += size
                yield name, size, enc
                continue
            with b:
                for n2, s2, e2, _ in sub:
                    seen += s2
                    yield f"{name}/{n2}", s2, e2


def check(p):
    """받기의 거르기 — 건너뛸 이유(`encrypted_archive`·`broken_archive`·`archive_too_big`·`unsupported_archive`) 또는 None(압축 아님·풀 수 있음)."""
    p = Path(p)
    kind = kind_of(p.name)
    if kind is None:
        return None
    if p.suffix.lower() == ".gz" and not tarfile.is_tarfile(p):
        return "unsupported_archive"
    max_files, cap = pc.cfg().extract.archive.max_files, _cap_bytes()
    total = n = 0
    try:
        for _name, size, enc in _walk(p, kind):
            if enc:
                return "encrypted_archive"
            n, total = n + 1, total + size
            if n > max_files or total > cap:
                return "archive_too_big"
    except BROKEN:
        return "broken_archive"
    return None


def members(p):
    """한 단계 안 파일을 하나씩 (이름, 바이트)로 내는 반복자 — 꺼내기(unpack, pl-63)가 쓴다. 폴더·링크·암호 항목은 빼고,
    그림 파일은 풀지 않고 뺀다(글자만). 합계·개수 상한에 닿으면 거기서 멈춘다(맨 바깥 원본은 check가 이미 봄 — 메일에 붙은
    압축 등). 열기·목록은 여기서 바로 해서 못 열면 BROKEN을 낸다(읽는 도중 깨짐은 반복 중에 BROKEN)."""
    p = Path(p)
    kind = kind_of(p.name)
    a = _open(p, kind)
    try:
        items = _members(a, kind)
    except BROKEN:
        a.close()
        raise
    max_files, cap = pc.cfg().extract.archive.max_files, _cap_bytes()

    def read_all():
        total = 0
        with a:
            for i, (name, size, enc, item) in enumerate(items):
                total += size
                if i >= max_files or total > cap:
                    return
                if not enc and Path(name).suffix.lower() not in IMG_EXTS:
                    yield name, _read(a, kind, item)

    return read_all()
