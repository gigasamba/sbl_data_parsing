"""문서 안 문서 꺼내기(pl-63) — 받기 단계(filter_and_rotate)가 준비 폴더 `_parts/<원본 이름>/`에 파일로 꺼내 두고
`parts.json`에 적는다. 꺼내는 것: 압축 안 파일(pl-57)·메일 첨부와 메일 안 메일(pl-36)·새 형식 오피스 안 개체.
깊이는 원본에서 `extract.attach.max_depth`(2)까지 종류가 섞여도 같이 센다. 변환 단계(mail_attachments)는 이 목록만 읽는다.
안 파일 이름은 경로로 쓰지 않는다(`0001.docx`처럼 번호로 저장 — `../` 같은 이름이 폴더 밖으로 나가지 않게).
못 꺼낸 안 파일(깨짐·암호·상한·못 벗김)은 parts.json `failed`에 남기고, 받기가 except_doc_info part 행으로 적는다(pl-65)."""

import email
import hashlib
import io
import itertools
import json
import posixpath
import re
import shutil
import struct
import zipfile
from email import policy
from pathlib import Path
from xml.etree import ElementTree as ET

from common.core.paths import atomic_write_text
from pipeline import config as pc
from pipeline.extract import archive
from pipeline.shared.ext_groups import IMG_EXTS, MAIL_EXTS, OFFICE_EXTS
from pipeline.shared.srcsha import sha_of

KIND = {"archive": "파일", "mail": "첨부", "office": "개체"}  # 변환 단계 절 이름표
PARTS = "_parts"  # 준비 폴더 아래 꺼낸 안 문서 폴더(변환 단계 mail_attachments.parts_of도 이 이름)
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_OWNER = re.compile(r"word/_rels/document\.xml\.rels|ppt/slides/_rels/slide\d+\.xml\.rels|xl/worksheets/_rels/sheet\d+\.xml\.rels")
_OBJ = ("/oleObject", "/package")  # 개체 연결 — 차트 엑셀은 charts/_rels에서만 가리켜 여기 안 걸림
_OLE_DOCS = (("WordDocument", ".doc"), ("Workbook", ".xls"), ("Book", ".xls"), ("PowerPoint Document", ".ppt"))


def box_kind(name):
    ext = Path(name).suffix.lower()
    if archive.kind_of(name):
        return "archive"
    return "mail" if ext in MAIL_EXTS else "office" if ext in OFFICE_EXTS else None


# ── 메일 ─────────────────────────────────────────────────────────────────
def _eml_parts(part):
    """이름 있는 비-그림 부분 + 메일 안 메일(message/rfc822 — 이름이 없으면 제목.eml). 안 메일 속으로는 내려가지 않는다(다음 깊이).
    message/rfc822 부분은 안 메일 표시(True) — .eml 엔진이 그 글을 이미 읽으므로 목록에는 그 첨부만 남긴다.
    파일로 붙은 .eml(application/octet-stream)은 엔진이 읽지 않아 보통 첨부로 둔다."""
    for sub in part.iter_parts():
        if sub.get_content_type() == "message/rfc822":
            inner = sub.get_content()
            name = sub.get_filename() or inner["subject"] or "메일"
            yield (name if name.lower().endswith(".eml") else f"{name}.eml"), inner.as_bytes(), {}, True  # 이름에 .eml이 없어도 메일로 엶
        elif sub.is_multipart():
            yield from _eml_parts(sub)
        elif sub.get_content_maintype() != "image" and sub.get_filename():
            yield str(sub.get_filename()), sub.get_payload(decode=True) or b"", {}, False


def _mail_items(path):
    if path.suffix.lower() == ".eml":
        return list(_eml_parts(email.message_from_bytes(path.read_bytes(), policy=policy.default)))
    import extract_msg  # 서버 이미지에 있음(.msg 엔진과 같은 패키지)

    m = extract_msg.openMsg(str(path))
    try:
        out = []
        for a in m.attachments:
            name, data = a.longFilename or a.shortFilename or getattr(a, "displayName", None), a.data
            export = getattr(data, "exportBytes", None)
            if export:  # 메일 안 메일(.msg)
                name = name or getattr(data, "subject", None) or "메일"
                name, data = (name if name.lower().endswith(".msg") else f"{name}.msg"), export()
            if name and isinstance(data, bytes):
                out.append((str(name), data, {}, False))
        return out
    finally:
        m.close()


# ── 오피스 개체 ───────────────────────────────────────────────────────────
def _native(b):
    """OLE `\\x01Ole10Native` 스트림 → (원래 이름, 바이트). 크기 DWORD · 표시 WORD · 이름\\0 · 원래 경로\\0 · 예약 DWORD ·
    임시 경로 길이 DWORD + 임시 경로 · 데이터 길이 DWORD + 데이터."""
    j = b.index(b"\0", 6)
    label = b[6:j].decode("cp949", "replace")
    i = b.index(b"\0", j + 1) + 1 + 4
    i += 4 + struct.unpack_from("<I", b, i)[0]
    n = struct.unpack_from("<I", b, i)[0]
    return label, b[i + 4 : i + 4 + n]


def _unwrap(name, data):
    """embeddings/ 파일 → (이름, 바이트) 또는 None. `.bin`(OLE로 싼 개체)은 olefile로 벗긴다 — 새 형식 오피스에 넣은 개체가
    무엇이든(패키지로 싼 원래 파일·PDF(CONTENTS)·옛 형식 문서 통째) 꺼낸다. 못 벗기면 None(건너뜀)."""
    if Path(name).suffix.lower() != ".bin":
        return name, data
    import olefile  # extract-msg와 함께 설치됨

    stem = Path(name).stem
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
        if ole.exists("\x01Ole10Native"):
            label, body = _native(ole.openstream("\x01Ole10Native").read())
            return (label or stem), body
        if ole.exists("CONTENTS"):
            body = ole.openstream("CONTENTS").read()
            return (f"{stem}.pdf", body) if body.startswith(b"%PDF") else None
        if ole.exists("Package"):  # 새 형식 문서를 OLE로 쌈
            body = ole.openstream("Package").read()
            ct = zipfile.ZipFile(io.BytesIO(body)).read("[Content_Types].xml")
            ext = ".docx" if b"/word/" in ct else ".pptx" if b"/ppt/" in ct else ".xlsx" if b"/xl/" in ct else None
            return (stem + ext, body) if ext else None
        for stream, ext in _OLE_DOCS:
            if ole.exists(stream):
                return stem + ext, data
    except (OSError, ValueError, IndexError, struct.error, zipfile.BadZipFile, KeyError):
        return None
    return None


def _rel_targets(z, base, part):
    """<base>/_rels/<part>.rels → {연결 id: zip 안 경로}."""
    return {
        r.get("Id"): posixpath.normpath(posixpath.join(base, r.get("Target")))
        for r in ET.fromstring(z.read(f"{base}/_rels/{part}.rels")).iter(_PR)
    }


def _slide_order(z):
    """ppt/slides/slideN.xml → 발표 순서(1부터) — 파일 번호와 순서가 다를 수 있다."""
    rels = _rel_targets(z, "ppt", "presentation.xml")
    ids = [s.get(_R_ID) for s in ET.fromstring(z.read("ppt/presentation.xml")).iter(_P + "sldId")]
    return {rels[i]: n for n, i in enumerate(ids, 1) if i in rels}


def _sheet_names(z):
    """xl/worksheets/sheetN.xml → (시트 이름, 다음 시트 이름) — 위치 표시를 그 시트 끝(다음 시트 이름표 앞)에."""
    rels = _rel_targets(z, "xl", "workbook.xml")
    sheets = [(rels.get(s.get(_R_ID)), s.get("name")) for s in ET.fromstring(z.read("xl/workbook.xml")).iter(_S + "sheet")]
    return {f: (n, sheets[i + 1][1] if i + 1 < len(sheets) else None) for i, (f, n) in enumerate(sheets)}


def _word_anchors(z):
    """워드 — 연결 id → 위치 {"after": 개체가 든 문단의 글(없으면 바로 앞 글 있는 문단)의 끝 40자, "nth": 그 글이 앞에 몇 번 더
    나왔나(0이면 뺌 — 같은 글이 앞에도 있으면 첫 자리가 아니라 그 차례에 표시)}. 문서를 한 번만 읽는다."""
    out, last, seen = {}, "", ""  # seen = 지금까지 글 있는 문단을 줄로 이은 것
    paras = list(ET.fromstring(z.read("word/document.xml")).iter(_W + "p"))
    inner = {q for p in paras for q in p.iter(_W + "p") if q is not p}  # 글상자(w:txbxContent) 속 문단 — 글은 바깥 문단에 이미 듦
    for p in paras:
        if p in inner:
            continue
        text = "".join(t.text or "" for t in p.iter(_W + "t")).strip()
        if text:
            seen += text + "\n"
        for el in p.iter():
            rid = el.get(_R_ID)
            if rid and rid not in out and (text or last):
                tail = (text or last)[-40:]
                nth = seen.count(tail) - 1
                out[rid] = {"after": tail, "nth": nth} if nth else {"after": tail}
        last = text or last
    return out


def _office_items(path, miss):
    """개체 (이름, 바이트, 위치, False) — 크기 상한을 넘는 개체·그림은 읽기 전에 거르고, 개수 상한까지만 읽는다.
    크기·개수 상한을 넘은 개체와 못 벗긴 `.bin`은 miss(embeddings 파일 이름, 까닭)로 알린다(pl-65)."""
    att = pc.cfg().extract.attach
    cap, out = att.max_mb * 1024 * 1024, []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        try:
            slides = _slide_order(z) if "ppt/presentation.xml" in names else {}
            sheets = _sheet_names(z) if "xl/workbook.xml" in names else {}
            anchors = _word_anchors(z) if "word/document.xml" in names else {}
        except (KeyError, ET.ParseError):
            slides, sheets, anchors = {}, {}, {}
        for rels in sorted(n for n in names if _OWNER.fullmatch(n)):
            owner = rels.replace("_rels/", "")[: -len(".rels")]
            for r in ET.fromstring(z.read(rels)).iter(_PR):
                if r.get("TargetMode") == "External" or not r.get("Type", "").endswith(_OBJ):
                    continue  # 연결만 된 개체·그림·차트 등
                target = posixpath.normpath(posixpath.join(posixpath.dirname(owner), r.get("Target", "")))
                base = posixpath.basename(target)
                if target not in names or Path(target).suffix.lower() in IMG_EXTS:
                    continue
                if z.getinfo(target).file_size > cap or len(out) >= att.max_n:
                    miss(base, "too_big" if z.getinfo(target).file_size > cap else "too_many")
                    continue
                got = _unwrap(base, z.read(target))
                if got is None:
                    miss(base, "no_unwrap")
                    continue
                if Path(got[0]).suffix.lower() in IMG_EXTS:
                    continue
                if owner in slides:
                    where = {"slide": slides[owner], "slides": len(slides)}
                elif owner in sheets:
                    where = {"sheet": sheets[owner][0], "next": sheets[owner][1]}
                else:
                    where = anchors.get(r.get("Id"), {})
                out.append((*got, where, False))
    return out


# ── 꺼내기 ───────────────────────────────────────────────────────────────
READ_FAIL = (*archive.BROKEN, NotImplementedError, RuntimeError)  # 읽는 도중 깨짐·지원 안 하는 압축 방식(Deflate64 등)·암호 항목
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(name):
    """안 파일 이름 — 줄바꿈·제어 문자는 빈칸으로(절 제목 `## [첨부 …]`이 깨지지 않게), 글자로 못 쓰는 조각(surrogate)은 '?'로(pl-65)."""
    return _CTRL.sub(" ", name.encode("utf-8", "replace").decode("utf-8")).strip()


def _children(path, kind, miss):
    """한 단계 안 파일 (이름, 바이트, 위치, 안 메일?)들 — 열리지 않으면 None(그 파일은 보통 파일로 남음). 압축은 하나씩 읽는
    반복자(메모리에 다 올리지 않음). 그림은 상한을 세기 전에 뺀다(서명 그림이 개수 상한을 먹지 않게). 상한·암호·못 벗김으로
    뺀 안 파일은 miss(이름, 까닭)로 알린다."""
    if kind == "archive":
        try:
            return ((n, b, {}, False) for n, b in archive.members(path, miss))
        except READ_FAIL:
            return None
    att = pc.cfg().extract.attach
    try:
        items = _mail_items(path) if kind == "mail" else _office_items(path, miss)
    except Exception:  # 깨진 메일·오피스는 엔진이 각자 판정(꺼내기만 건너뜀)
        return None
    cap, kids = att.max_mb * 1024 * 1024, []
    for it in items:
        if Path(it[0]).suffix.lower() in IMG_EXTS:
            continue
        if len(it[1]) > cap or len(kids) >= att.max_n:
            miss(it[0], "too_big" if len(it[1]) > cap else "too_many")
        else:
            kids.append(it)
    return kids


def _expand(path, label, depth, dst, out, ctx):
    """path가 상자면 안 파일을 dst에 꺼내 out에 더한다(깊이 상한까지 다시). 열렸으면 True. 읽기 실패만 거기서 멈추고
    쓰기 실패(디스크 가득 등)는 그대로 올린다(덜 꺼낸 목록을 다 꺼낸 것처럼 남기지 않게).
    목록에서 그 안 파일로 대신하는 것: 열린 안 압축(압축 엔진 글은 목록뿐) · 안 메일(.eml 엔진이 글을 이미 읽음 — 깊이 상한으로
    못 열어도 뺌). ctx = 원본 하나의 꺼내기 상태(pl-65): seq 파일 번호 · left 남은 합계 바이트(압축 안전 상한 — 오피스 개체로 된
    크기 폭탄도 여기서 멈춤) · seen 꺼낸 내용 sha256(같은 내용은 처음 것만) · failed 못 꺼낸 안 파일 [{name, why}]."""
    kind = box_kind(path.name)
    if kind is None or depth >= pc.cfg().extract.attach.max_depth:
        return False

    def miss(name, why):
        ctx["failed"].append({"name": f"{label}/{_clean(name)}" if label else _clean(name), "why": why})

    kids = _children(path, kind, miss)
    if kids is None:
        # 맨 바깥 원본이 안 열리면 엔진이 판정(기록은 안 문서만) · tar 아닌 .gz는 보통 파일(archive._walk와 같음 — 못 꺼낸 것이 아님)
        if depth and archive.check(path) != "unsupported_archive":
            ctx["failed"].append({"name": label, "why": "cannot_open"})
        return False
    it = iter(kids)
    while True:
        try:
            name, data, where, inline = next(it)
        except StopIteration:
            break
        except READ_FAIL:
            ctx["failed"].append({"name": label or path.name, "why": "read_failed"})
            break  # 읽는 도중 깨진 압축 — 거기까지 꺼낸 것만
        name = _clean(name)
        full = f"{label}/{name}" if label else name
        digest = hashlib.sha256(data).hexdigest()
        if digest in ctx["seen"]:
            continue  # 같은 내용은 처음 것만(못 꺼낸 것이 아님)
        if len(data) > ctx["left"]:
            ctx["failed"].append({"name": full, "why": "total_cap"})
            continue
        ctx["seen"].add(digest)
        # 목록에서 안 파일로 대신할 수 있는 것 — 합계에는 안 파일만 셈(같은 바이트를 두 번 세지 않게)
        boxed = inline or box_kind(name) == "archive"
        if not boxed:
            ctx["left"] -= len(data)
        f = dst / f"{next(ctx['seq']):05d}{re.sub(r'[^.\w]', '', Path(name).suffix.lower())[:10]}"
        f.write_bytes(data)
        item = {"file": f.name, "name": full, "depth": depth + 1, "kind": KIND[kind], "where": where}
        out.append(item)
        opened = _expand(f, full, depth + 1, dst, out, ctx)
        if inline or (opened and boxed):
            out.remove(item)
            f.unlink()
        elif boxed:  # 못 연 안 압축은 파일로 남음
            ctx["left"] -= len(data)
    return True


def _manifest(doc, parts_root):
    """parts.json → {"sha256": 원본 sha256, "parts": [...], "failed": [...]} 또는 None(없음·깨짐·옛 목록 형식)."""
    try:
        m = json.loads((Path(parts_root) / Path(doc).name / "parts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) else None


def is_fresh(doc, parts_root):
    """상자가 아니거나 꺼낸 목록이 지금 원본(sha256)에서 나온 것이면 True — 원본이 안 바뀐 재실행은 다시 거르거나 풀지 않는다."""
    if box_kind(Path(doc).name) is None:
        return True
    m = _manifest(doc, parts_root)
    return m is not None and m.get("sha256") == sha_of(doc)


def failed_of(doc, parts_root):
    """못 꺼낸 안 파일 목록 [{name, why}] — 꺼낸 적 없으면 빈 목록."""
    return (_manifest(doc, parts_root) or {}).get("failed") or []


def miss_reason(failed, n=10):
    """except_doc_info part 행의 이유 — 앞 n개 `이름(까닭)`을 `; `로 잇고 나머지는 개수만."""
    head = "; ".join(f"{f['name']}({f['why']})" for f in failed[:n])
    return head + (f" 외 {len(failed) - n}개" if len(failed) > n else "")


def unpack(doc, parts_root):
    """준비 폴더의 원본 doc → parts_root/<doc 이름>/에 꺼내고 목록을 돌려준다. 상자가 아니면 아무것도 만들지 않는다.
    상자면 안 파일이 없어도 parts.json을 써 둔다(is_fresh가 원본 sha256을 본다). parts.json은 다 쓴 뒤 한 번에 바꿔 놓는다
    (덜 쓴 목록이 보이지 않게)."""
    doc = Path(doc)
    dst = Path(parts_root) / doc.name
    shutil.rmtree(dst, ignore_errors=True)
    if box_kind(doc.name) is None:
        return []
    out: list[dict] = []
    dst.mkdir(parents=True, exist_ok=True)
    ctx = {"seq": itertools.count(1), "left": archive.cap_bytes(), "seen": set(), "failed": []}
    _expand(doc, "", 0, dst, out, ctx)
    body = {"sha256": sha_of(doc), "parts": out, "failed": ctx["failed"]}
    atomic_write_text(dst / "parts.json", json.dumps(body, ensure_ascii=False, indent=1))
    return out
