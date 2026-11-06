"""메일(.eml·.msg)·압축 원본(.zip·.tar·.tgz·.tar.gz — pl-57) 후보정 — 첨부(압축은 안 파일) 다시 파싱 + 인용 스레드 단락화.
원본(doc_path)에서 첨부를 꺼내 형식별 구성 엔진 순서로 파싱하고, 결과는 P0 원본 층(raw_cache.raw_engine_path —
첨부 sha256 + 엔진@버전)에 캐시해 다시 안 돈다. 대표 본문에는 `[첨부 <파일명>]` 절로만 덧붙인다(base 본문은 그대로).
인라인 그림(cid)은 figure_extract가 맡아 image/* 첨부는 건너뛴다.
zip 첨부는 ATTACH_MAX_DEPTH(기본 1)만큼만 풀고, 크기(ATTACH_MAX_MB 기본 20)·개수(ATTACH_MAX_N 기본 10) 상한을 넘으면 건너뜀.
"""

import email
import io
import json
import re
import time
import zipfile
from email import policy
from pathlib import Path

from common.core.paths import APP_ROOT  # output/ 경계(attach_dir)
from pipeline import config as pc
from pipeline.extract import archive
from pipeline.shared.raw_cache import raw_engine_path, raw_root
from pipeline.shared.vlmcall import sha
from pipeline.transform.parse.parse_engines import engine_version


def attach_dir():
    """첨부 임시 파일 폴더 — PARSE_TMP의 형제(기본 output/_tmp_parse/attach). 쓰는 쪽이 파일 하나 끝낼 때마다
    finally로 직접 지운다. 지우는 대상이라 APP_ROOT/output 아래 2단 이상만 허용."""
    tmp = Path(pc.cfg().paths.parse_tmp or (APP_ROOT / "output" / "_tmp_parse" / "stream"))
    root_out = (APP_ROOT / "output").resolve()
    rp = (tmp.parent / "attach").resolve()
    try:
        rel = rp.relative_to(root_out)
    except ValueError:
        rel = None
    if rel is None or len(rel.parts) < 2:
        raise SystemExit(f"[attach] 경로 거부 — {rp}는 {root_out} 아래 2단 이상 하위 폴더여야 함(PARSE_TMP 확인)")
    return rp


def _max_n():
    return pc.cfg().extract.attach.max_n


# ── 첨부 꺼내기(형식별) ───────────────────────────────────────────────────
def _eml_attachments(path):
    """.eml — 이름이 있는 비-이미지 부분만(이미지는 인라인 그림 — figure_extract가 담당)."""
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=policy.default)
    out = []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() == "image":
            continue
        name = part.get_filename()
        if not name:
            continue  # 본문(text/plain·text/html) — 첨부 아님
        out.append({"name": str(name), "bytes": part.get_payload(decode=True) or b"", "depth": 0})
    return out


def _msg_attachments(path):
    """.msg — extract_msg(서버에만 설치, 개발 PC에 없으면 빈 목록으로 조용히 건너뜀)."""
    try:
        import extract_msg
    except ImportError:
        return []
    m = extract_msg.openMsg(str(path))
    try:
        out = []
        for a in m.attachments:
            name = a.longFilename or a.shortFilename
            data = getattr(a, "data", None)
            if name and isinstance(data, bytes):
                out.append({"name": str(name), "bytes": data, "depth": 0})
        return out
    finally:
        m.close()


def _expand_zip(entry, cap):
    """zip 첨부를 cap단(기본 1)까지만 풀기 — 그 밑은 손 안 댐(opaque로 둠, 맞는 엔진 없으면 parse_attachment가 자연히 건너뜀)."""
    if Path(entry["name"]).suffix.lower() != ".zip" or entry["depth"] >= cap:
        return [entry]
    try:
        zf = zipfile.ZipFile(io.BytesIO(entry["bytes"]))
        infos = [zi for zi in zf.infolist() if not zi.is_dir()][: _max_n()]  # 읽기 전에 개수·풀린 크기 확인(zip 폭탄)
        cap_b, total = pc.cfg().extract.attach.max_mb * 1024 * 1024, 0
        inner = []
        for zi in infos:
            total += zi.file_size
            if zi.file_size > cap_b or total > cap_b:
                break  # 상한 넘으면 그 뒤는 안 풂(읽은 것까지만)
            inner.append({"name": f"{entry['name']}#{zi.filename}", "bytes": zf.read(zi), "depth": entry["depth"] + 1})
    except (zipfile.BadZipFile, OSError):
        return [entry]
    if not inner:
        return [entry]
    return [e for ie in inner for e in _expand_zip(ie, cap)]


def extract(doc_path):
    """doc_path(.eml·.msg) → 꺼낸 첨부 목록(개수 상한 적용 후 zip 전개) — 다른 형식·오류는 빈 목록."""
    ext = Path(doc_path).suffix.lower()
    try:
        atts = _eml_attachments(doc_path) if ext == ".eml" else _msg_attachments(doc_path) if ext == ".msg" else []
    except Exception:
        return []
    cap = pc.cfg().extract.attach.max_depth
    out = []
    for e in atts[: _max_n()]:
        out += _expand_zip(e, cap)
    return out


# ── 첨부 1건 파싱(+ P0 캐시) ─────────────────────────────────────────────
def _stack_parse():
    return pc.stack().get("parse", {})  # 엔진 구성 파일(서버·PC 같음)


def parse_attachment(entry, store=None):
    """첨부 1건 → (텍스트, 캐시 적중?, 엔진) — stack.json이 그 형식에 지정한 엔진 순서로 시도해
    15자 이상 나온 첫 결과를 씀. P0 원본 층 키 = 첨부 sha256 + 엔진@버전(pipeline.shared.raw_cache.raw_engine_path) —
    같은 첨부를 같은 엔진으로 다시 안 돎."""

    store = store or raw_root()
    ext = Path(entry["name"]).suffix.lower()
    content_sha = sha(entry["bytes"])
    stack = _stack_parse()
    # stack.json은 PDF를 .pdf_text/.pdf_image로 나눠 둠(parse_engines와 같은 키) — 글자층 엔진 먼저, 15자 못 넘으면 OCR 엔진
    engines = stack.get(".pdf_text", []) + stack.get(".pdf_image", []) if ext == ".pdf" else stack.get(ext, [])
    for eng in engines:
        ver = engine_version(eng)
        dst = raw_engine_path(store, eng, ver, content_sha)
        if dst.exists():
            try:
                return json.loads(dst.read_text(encoding="utf-8")).get("text") or "", True, eng
            except (OSError, ValueError):
                pass
        adir = attach_dir()  # 강제 종료돼도 남은 파일은 다음 실행이 같은 이름으로 덮음
        adir.mkdir(parents=True, exist_ok=True)
        tmp = adir / f"attach-{content_sha[:12]}{ext}"
        out_json = tmp.with_suffix(tmp.suffix + ".json")
        try:
            tmp.write_bytes(entry["bytes"])
            # 별도 프로세스 + 시간 제한 — 멈추는 엔진이 대표 결과 만들기 전체를 세우지 않게
            from pipeline.transform.parse.parse_engines import _isolated

            _isolated(eng, tmp, out_json, "default", pc.cfg().extract.attach.timeout)
            res = json.loads(out_json.read_text(encoding="utf-8"))
        except Exception:
            continue  # 미설치·파싱 실패·시간 초과 — 스택 순서대로 다음 엔진
        finally:
            tmp.unlink(missing_ok=True)
            out_json.unlink(missing_ok=True)
        text = (res.get("text") or "").strip()
        if len(text) < 15:
            continue
        res["provenance"] = {
            "engine": eng,
            "engine_version": ver,
            "source_file": entry["name"],
            "source_sha256": content_sha,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return res.get("text") or "", False, eng
    return "", False, None


# ── 인용 스레드 단락화 ───────────────────────────────────────────────────
_WROTE = re.compile(r"^On\s+(?P<rest>.+)\s+wrote:\s*$", re.I)  # "On <날짜>, <발신자> wrote:" — 날짜 안에도 쉼표가 있어 마지막 쉼표로 가름
_ORIG = re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.I)
_HDR = re.compile(r"^(?P<key>From|Sent|Date|보낸\s*사람|날짜)\s*[:：]\s*(?P<val>.+)$", re.I)
_QUOTE = re.compile(r"^>+\s?")


def thread_paragraphs(text):
    """'>' 인용·Outlook 'Original Message' 구간을 날짜·발신자 단락으로(헤더 못 찾으면 '[인용]'만) — 모자라게.
    인용 구간이 없으면 빈 글자(mail_blocks가 블록으로만 덧붙이므로 base_text는 항상 그대로)."""
    plain = [(_QUOTE.sub("", ln.lstrip(), count=1) if _QUOTE.match(ln.lstrip()) else ln) for ln in (text or "").splitlines()]
    starts = [i for i, ln in enumerate(plain) if _WROTE.match(ln.strip()) or _ORIG.match(ln.strip())]
    if not starts:
        return ""
    starts.append(len(plain))
    paras = []
    for a, b in zip(starts, starts[1:]):
        head, body = plain[a].strip(), plain[a + 1 : b]
        m = _WROTE.match(head)
        if m:
            rest = m["rest"].strip()
            date, _, sender = rest.rpartition(",")
            date, sender = (date.strip(), sender.strip()) if date else (None, rest)
            sender = re.sub(r"\s*<[^>]+>\s*$", "", sender).strip() if sender else sender
        else:
            sender, date = None, None
        for ln in body[:6]:
            hm = _HDR.match(ln.strip())
            if hm:
                key = hm["key"].strip().lower()
                if key in ("from", "보낸 사람") and not sender:
                    sender = hm["val"].strip()
                elif key in ("sent", "date", "날짜") and not date:
                    date = hm["val"].strip()
        label = " · ".join(x for x in (date, sender) if x)
        content = "\n".join(ln for ln in body if ln.strip())
        if content:
            paras.append((f"[인용 {label}]" if label else "[인용]") + "\n" + content)
    return "\n\n".join(paras)


# ── doc_represent.apply_post가 부르는 진입점 ─────────────────────────────────────────
def mail_blocks(doc_path, base_text):
    """.eml·.msg: 인용 스레드 단락 + 첨부별 `[첨부 <파일명>]` 절 · 압축 원본: 안 파일별 `[파일 <안 경로>]` 절(크기·개수 상한은
    받기의 거르기가 이미 봄 — archive.check) → (덧붙일 블록 목록, 통계{n, parsed, cached, sources}). 다른 형식·오류는 (빈 목록, 0 통계)."""
    stats = {"n": 0, "parsed": 0, "cached": 0, "sources": []}
    blocks = []
    ext = Path(doc_path).suffix.lower()
    if ext in archive.EXTS:
        items, label = archive.entries(doc_path), "파일"
    elif ext in (".eml", ".msg"):
        th = thread_paragraphs(base_text)
        if th:
            blocks.append(th)
        cap = pc.cfg().extract.attach.max_mb * 1024 * 1024
        items, label = (
            (e for e in extract(doc_path) if len(e["bytes"]) <= cap),
            "첨부",
        )  # 크기 상한 초과는 시도하지 않음(통계 n에도 안 넣음)
    else:
        return blocks, stats
    for entry in items:
        stats["n"] += 1
        text, cached, eng = parse_attachment(entry)
        if not text:
            continue
        stats["parsed"] += 1
        stats["cached"] += int(cached)
        stats["sources"].append(f"{Path(doc_path).name}#{entry['name']}")  # 원본 위치 = 메일#첨부명
        blocks.append(f"[{label} {entry['name']}]\n{text}")
    return blocks, stats
